"""M0 冻结基线 runner（docs/quality-first-unit-routing-complete-plan-2026-08-16.md §25 M0）.

对一份真实文档执行"当前默认链"的冷启动（缓存为空）与热复跑（缓存复用），逐阶段记录
provider 调用数与 token 消耗，以及效果指标（功能直抽执行状态/守恒/需求数/成文行数），
落 JSON + Markdown 基线报告。纯测量工具：不改变任何流水线行为，不写任何密钥。

用法（密钥只经环境变量传入，绝不落盘）::

    RATOMIZER_LLM_API_KEY=... python tools/m0_baseline.py \
        --input "C:/.../Appendix 9-ABNT NBR 16968-2022 EN.docx" \
        --label abnt --template "C:/.../公司模板.xlsx"

计量口径：
- 调用数/token 取自 ``llm_trace.jsonl`` 增量（每行一次 provider 收发，成功行含
  ``response.usage``）；逐阶段快照差分得到 per-stage 归属。
- ``llm_budget.json``（RATOMIZER_LLM_BUDGET=1 时存在）原文并入报告作交叉证据。
- 效果指标只读现有产物，不另建判定口径。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

REPORT_SCHEMA = "m0-baseline-report/v1"

# §3.1 当前默认运行（UI plannedAutomaticStages 的 LLM 全开投影）。注意两点：
# 1) functional-extract 默认开时 chain_task 把 ai-extract（或 functional-synthesis）
#    单点替换为 functional-extract——逐阶段计量时两个旧名会各触发一次替换执行
#    （首跑失败不缓存则双倍付费），故只保留 ai-extract 一个旧名入口；
# 2) llm-review 是独立可选项，不在 CHAIN_ORDER，M0 基线不包含（如实记录口径）。
STAGES_DEFAULT = (
    "ai-extract", "assemble", "requirements-analysis",
    "template-write", "clarification-report", "full-translation", "compose",
    "export-annotation-html",
)

DEFAULT_TEMPLATE = Path(
    "C:/Users/YYHwudi/Desktop/Canna-29/电表软件标准化需求列表-V2.3.12 - 2026-4-14..xlsx"
)

FINAL_XLSX = "软件需求列表-成文.xlsx"


def _trace_path(out_dir: Path) -> Path:
    from result_package import governed_artifact_path

    return governed_artifact_path(out_dir, "llm_trace.jsonl", category="logs",
                                  for_write=False)


def _trace_snapshot(path: Path) -> dict[str, object]:
    """统计 llm_trace.jsonl 当前总量（行数/成功/失败/token 三项和）。"""
    if not path.is_file():
        return {"lines": 0, "ok": 0, "failed": 0, "prompt_tokens": 0,
                "completion_tokens": 0, "total_tokens": 0}
    lines = ok = failed = 0
    prompt = completion = total = 0
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            lines += 1
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                failed += 1
                continue
            response = record.get("response")
            if isinstance(response, dict):
                ok += 1
                usage = response.get("usage") or {}
                if isinstance(usage, dict):
                    prompt += int(usage.get("prompt_tokens") or 0)
                    completion += int(usage.get("completion_tokens") or 0)
                    total += int(usage.get("total_tokens")
                                 or ((usage.get("prompt_tokens") or 0)
                                     + (usage.get("completion_tokens") or 0)))
            else:
                failed += 1
    return {"lines": lines, "ok": ok, "failed": failed, "prompt_tokens": prompt,
            "completion_tokens": completion, "total_tokens": total}


def _delta(before: dict[str, object], after: dict[str, object]) -> dict[str, object]:
    return {key: int(after[key]) - int(before[key]) for key in before}


def _budget_snapshot(path: Path) -> dict[str, int]:
    """llm_budget.json consumed 摊平为 {stage.calls / stage.tokens} 整数快照。"""
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return {}
    flat: dict[str, int] = {}
    for stage, item in (payload.get("consumed") or {}).items():
        if isinstance(item, dict):
            flat[f"{stage}.calls"] = int(item.get("calls") or 0)
            flat[f"{stage}.tokens"] = int(item.get("tokens") or 0)
            flat[f"{stage}.failed_calls"] = int(item.get("failed_calls") or 0)
    return flat


def _budget_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    delta = {key: after.get(key, 0) - before.get(key, 0)
             for key in sorted(set(before) | set(after))}
    # 只保留有变化的键——预算账本不覆盖翻译路径（如实保留空 delta，由 trace 口径补）
    return {key: value for key, value in delta.items() if value}


def _read_json(path: Path) -> object | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _effect_metrics(run_dir: Path) -> dict[str, object]:
    """只读收集效果产物现状（不建新判定口径，缺什么记什么）。"""
    metrics: dict[str, object] = {}
    try:
        from requirements_analysis_rules import _read_functional_requirements_payload

        payload = _read_functional_requirements_payload(run_dir)
    except Exception as exc:  # noqa: BLE001 — 只读收集，失败如实记录
        payload = None
        metrics["functional_product_error"] = f"{type(exc).__name__}: {exc}"
    if isinstance(payload, dict):
        items = payload.get("items")
        conservation = payload.get("conservation")
        metrics["functional"] = {
            "execution_status": payload.get("execution_status"),
            "item_count": len(items) if isinstance(items, list) else None,
            "conservation_ok": (conservation.get("ok")
                                if isinstance(conservation, dict) else None),
            "guards_version": payload.get("guards_version"),
            "prompt_version": payload.get("prompt_version"),
        }
    final_xlsx = run_dir / FINAL_XLSX
    metrics["final_xlsx_exists"] = final_xlsx.is_file()
    if final_xlsx.is_file():
        try:
            from ab_runner import _read_final_xlsx_rows

            struct = _read_final_xlsx_rows(final_xlsx)
            metrics["final_xlsx"] = {
                "ok": struct["ok"], "row_count": struct["row_count"],
                "error": struct.get("error"),
            } if struct else None
        except Exception as exc:  # noqa: BLE001
            metrics["final_xlsx"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    deliverables = sorted(
        p.name for p in run_dir.iterdir()
        if p.is_file() and not p.name.startswith(".")
    ) if run_dir.is_dir() else []
    metrics["root_files"] = deliverables
    return metrics


def _run_stage(run_dir: Path, stage: str, *, route: str, template: Path | None) -> dict[str, object]:
    from desktop_tasks import chain_task

    started = time.time()
    try:
        payload = chain_task(run_dir, stages=[stage], route=route, template_path=template)
        error = None
        skipped = [name for name, item in (payload.get("results") or {}).items()
                   if isinstance(item, dict) and item.get("skipped")]
    except Exception as exc:  # noqa: BLE001 — 基线测量：单阶段失败记录后继续
        error = f"{type(exc).__name__}: {exc}"
        skipped = []
        traceback.print_exc()
    return {"stage": stage, "error": error, "skipped": skipped,
            "duration_s": round(time.time() - started, 1)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M0 冻结基线：冷/热两轮逐阶段计量")
    parser.add_argument("--input", type=Path, required=True, help="真实文档路径")
    parser.add_argument("--label", required=True, help="基线标签（如 abnt）")
    parser.add_argument("--route", default="openai_compatible")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE,
                        help="公司模板路径（template-write 需要）")
    parser.add_argument("--work-root", type=Path, default=None,
                        help="运行目录（默认 out/m0-<label>-<日期>）")
    parser.add_argument("--stages", default=",".join(STAGES_DEFAULT),
                        help="逗号分隔逻辑阶段（默认 §3.1 全链投影）")
    parser.add_argument("--skip-parse", action="store_true",
                        help="复用已存在的 parse 目录（跳过重新解析）")
    parser.add_argument("--runs", default="cold,warm", help="逗号分隔运行轮次标签")
    args = parser.parse_args(argv)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    work_root = (args.work_root or REPO_ROOT / "out" / f"m0-{args.label}-{stamp}").resolve()
    parse_dir = work_root / "parse"
    work_root.mkdir(parents=True, exist_ok=True)

    # 1) 确定性解析（零 LLM）；--skip-parse 时校验 blocks.jsonl 在场
    if args.skip_parse:
        if not (parse_dir / "blocks.jsonl").is_file():
            print(f"[m0] --skip-parse 但 {parse_dir} 缺 blocks.jsonl", file=sys.stderr)
            return 2
    else:
        from atomize import run_atomizer_pipeline
        from requirement_kb.cli import default_kb_paths

        print(f"[m0] atomize: {args.input} -> {parse_dir}（默认 KB）")
        run_atomizer_pipeline(args.input, parse_dir, kb_paths=default_kb_paths())

    from ab_runner import _copy_parsed_artifacts
    from desktop_tasks import chain_task  # noqa: F401 — 提前暴露导入错误

    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    runs = [r.strip() for r in args.runs.split(",") if r.strip()]
    template = args.template if (args.template and args.template.is_file()) else None

    report: dict[str, object] = {
        "schema": REPORT_SCHEMA,
        "label": args.label,
        "input": str(args.input),
        "route": args.route,
        "kb": "default (compiled_from_obsidian.json)",
        "template": str(template) if template else None,
        "stages": stages,
        "runs": [],
        "llm_review_note": ("llm-review 是 UI 可选项且不在 CHAIN_ORDER，"
                            "本基线未包含（§3.1 口径决定，如实记录）"),
    }

    run_dir: Path | None = None
    for index, run_label in enumerate(runs):
        if index == 0:
            run_dir = work_root / run_label
            run_dir.mkdir(parents=True, exist_ok=True)
            _copy_parsed_artifacts(parse_dir, run_dir)
        assert run_dir is not None
        run_report: dict[str, object] = {"label": run_label, "stages": []}
        trace = _trace_path(run_dir)
        budget_path = run_dir / "llm_budget.json"
        # 直接调用 chain_task 不经过 CLI 落账面——手动挂 run logging（含 llm_trace），
        # 否则翻译/抽取调用不落 trace，成本口径缺整段
        from desktop_tasks import setup_run_logging, teardown_run_logging

        setup_run_logging(run_dir)
        try:
            for stage in stages:
                before = _trace_snapshot(trace)
                before_budget = _budget_snapshot(budget_path)
                outcome = _run_stage(run_dir, stage, route=args.route, template=template)
                after = _trace_snapshot(trace)
                outcome["trace_delta"] = _delta(before, after)
                outcome["budget_delta"] = _budget_delta(
                    before_budget, _budget_snapshot(budget_path))
                run_report["stages"].append(outcome)
                print(f"[m0:{run_label}] {stage}: {'ERROR: ' + outcome['error'] if outcome['error'] else 'ok'}"
                      f" trace_calls=+{outcome['trace_delta']['lines']}"
                      f" trace_tokens=+{outcome['trace_delta']['total_tokens']}"
                      f" budget_delta={outcome['budget_delta'] or '{}'}")
        finally:
            teardown_run_logging()
        run_report["trace_total"] = _trace_snapshot(trace)
        run_report["budget"] = _read_json(budget_path)
        report["runs"].append(run_report)

    assert run_dir is not None
    report["effect"] = _effect_metrics(run_dir)
    report["work_root"] = str(work_root)
    report["generated_at"] = datetime.now(timezone.utc).isoformat()

    docs_dir = REPO_ROOT / "docs"
    json_path = docs_dir / f"m0-baseline-{args.label}-{stamp}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    print(f"[m0] report -> {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
