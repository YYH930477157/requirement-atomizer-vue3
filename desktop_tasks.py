from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import ai_extract
from assemble_spec import assemble
from atomize import run_atomizer_pipeline
from engineering_composer import compose_engineering_requirements, write_engineering_requirements
from export_requirements import export_requirements
from llm_pipeline import read_jsonl, run_review_pipeline
from requirement_kb.cli import default_kb_paths, package_root
from requirements_analysis import run_requirements_analysis
from requirements_analysis_schema import normalize_ownership
from spec_export import export_spec


ASSEMBLED_JSON = "dlms_cosem_spec_requirements.json"
PROGRESS_PREFIX = "__RATOMIZER_PROGRESS__"
BLUE_BOOK_INDEX_ENV = "RATOMIZER_BLUE_BOOK_INDEX"
REQUIREMENTS_ANALYSIS_OUTPUTS = [
    "engineering_analysis.json",
    "hardware_items.md",
    "co_design_items.md",
    "software_requirements.xlsx",
]


def resolve_bundled_path(path: Path | None) -> Path | None:
    """把前端预设送来的相对资源路径解析成可用的绝对路径。

    前端预设送相对名（KB 用 "knowledge_bases/…json"、domain pack 用 "domain_packs/dlms_cosem"），
    dev 下 cwd=仓库根能命中，但打包后后端 cwd=resources/backend 命中不到。这里：绝对路径或 cwd 下
    已存在的相对路径原样保留（兼容 CLI 习惯）；否则按 package_root() 解析（dev=仓库根 /
    Electron=resources/，捆绑资源真正所在）。
    """
    if path is None:
        return None
    path = Path(path)
    if path.is_absolute() or path.exists():
        return path
    return package_root() / path


def resolve_kb_paths(kb_paths: list[Path] | None) -> list[Path]:
    """把显式 --kb 路径列表逐个解析（见 resolve_bundled_path）；None 时用 default_kb_paths()。"""
    if kb_paths is None:
        return default_kb_paths()
    return [resolve_bundled_path(path) for path in kb_paths]


def run_pipeline_task(
    input_path: Path,
    out_dir: Path,
    *,
    skip_review: bool = False,
    llm_route: str | None = None,
    review_scope: str | None = None,
    llm_review_limit: int = 0,
    chunk_chars: int = 3500,
    kb_paths: list[Path] | None = None,
    domain_pack_dir: Path | None = None,
) -> dict[str, Any]:
    input_path = input_path.expanduser().resolve()
    out_dir = out_dir.expanduser().resolve()
    manifest = run_atomizer_pipeline(
        input_path,
        out_dir,
        chunk_chars=chunk_chars,
        kb_paths=resolve_kb_paths(kb_paths),
        domain_pack_dir=resolve_bundled_path(domain_pack_dir),
    )
    review = None if skip_review else run_review_pipeline(
        out_dir,
        route=llm_route,
        scope=review_scope,
        llm_review_limit=llm_review_limit,
        progress_callback=emit_progress,
    )
    return {
        "kind": "pipeline",
        "out_dir": str(out_dir),
        "input": str(input_path),
        "manifest": manifest,
        "review": review,
        "summary": build_output_summary(out_dir),
    }


def export_task(out_dir: Path, formats: list[str]) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    written = export_requirements(out_dir, formats=formats)
    return {
        "kind": "export",
        "out_dir": str(out_dir),
        "written": written,
        "summary": build_output_summary(out_dir),
    }


def resolve_blue_book_index(explicit: Path | None, out_dir: Path) -> Path | None:
    """蓝皮书索引路径：显式参数 > 环境变量 > 约定位置自动探测；都没有 → None（与无索引一致）。

    桌面「运行」链没有索引输入口（GUI 面板本期不做）——自动探测让桌面用户零配置享受 P2 行为
    富化：把编译好的 blue_book_index.json 放在输出目录（或 dev 仓库 out/bluebook/）即可。
    """
    if explicit is not None:
        return explicit
    env_value = os.environ.get(BLUE_BOOK_INDEX_ENV, "").strip()
    if env_value:
        return Path(env_value)
    candidates = (
        out_dir / "blue_book_index.json",
        out_dir / "bluebook" / "blue_book_index.json",
        package_root() / "out" / "bluebook" / "blue_book_index.json",  # dev 仓库编译位置
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def assemble_task(
    out_dir: Path,
    *,
    formats: list[str] | None = None,
    enrich_route: str | None = None,
    blue_book_index_path: Path | None = None,
) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    reviews = out_dir / "llm_review_results.jsonl"
    reviews_path = reviews if reviews.exists() else None
    blue_book_index_path = resolve_blue_book_index(blue_book_index_path, out_dir)
    doc, breakdown = assemble(
        out_dir,
        reviews_path,
        source=out_dir.name,
        extracted_at=datetime.datetime.now().isoformat(timespec="seconds"),
        enrich_route=enrich_route,
        blue_book_index_path=blue_book_index_path,
    )
    target = out_dir / ASSEMBLED_JSON
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    written = [str(target)]
    if formats:
        written.extend(str(out_dir / name) for name in export_spec(out_dir, formats=formats, reviews_path=reviews_path))
    return {
        "kind": "assemble",
        "out_dir": str(out_dir),
        "count": len(doc.get("requirements", [])),
        "analysis": doc.get("analysis", {}),
        "breakdown": breakdown,
        # 出处追溯：本次装配用了哪个蓝皮书索引（None=未注入，行为与 P2 之前一致）
        "blue_book_index": str(blue_book_index_path) if blue_book_index_path else None,
        "written": written,
        "summary": build_output_summary(out_dir),
    }


def compose_task(out_dir: Path) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    model = compose_engineering_requirements(out_dir)
    written = write_engineering_requirements(out_dir, model)
    analysis = model.get("analysis", {})
    return {
        "kind": "compose",
        "out_dir": str(out_dir),
        "count": int(analysis.get("requirement_functions") or len(model.get("requirement_functions", []))),
        "analysis": analysis,
        "written": written,
        "summary": build_output_summary(out_dir),
    }


def requirements_analysis_task(
    out_dir: Path,
    *,
    route: str = "stub",
    template_path: Path | None = None,
) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    analysis = run_requirements_analysis(
        out_dir,
        route=route,
        template_path=resolve_template_path(template_path),
        progress_callback=emit_progress,  # 富化逐条上报（GUI n/total，并发度走 RATOMIZER_LLM_CONCURRENCY）
    )
    # 只上报真实存在的产物（此前无条件列出 4 个文件，失败时载荷撒谎）
    names = analysis.get("written") or REQUIREMENTS_ANALYSIS_OUTPUTS
    written = [str(out_dir / name) for name in names if (out_dir / name).exists()]
    return {
        "kind": "requirements_analysis",
        "out_dir": str(out_dir),
        "analysis": analysis,
        "written": written,
        "summary": build_output_summary(out_dir),
    }


def resolve_template_path(template_path: Path | None) -> Path | None:
    if template_path is None:
        return None
    path = Path(template_path).expanduser()
    if not path.is_absolute() and not path.exists():
        path = resolve_bundled_path(path) or path
    if not path.exists():
        raise FileNotFoundError(f"Template file does not exist: {path}")
    return path.resolve()


def clarification_report_task(out_dir: Path) -> dict[str, Any]:
    """澄清问题清单 + 就绪判定（确定性零 LLM）：全链疑问信号聚合成评审会可用的问客户清单。"""
    from clarification_report import run_report

    out_dir = out_dir.expanduser().resolve()
    report = run_report(out_dir)
    return {
        "kind": "clarification_report",
        "out_dir": str(out_dir),
        "questions": report["questions"],
        "by_category": report["by_category"],
        "readiness": report["readiness"],
        "written": [str(out_dir / name) for name in report.get("written") or []
                    if (out_dir / name).exists()],
        "summary": build_output_summary(out_dir),
    }


def template_write_task(out_dir: Path, template_path: Path) -> dict[str, Any]:
    """成文：analyze 结果按公司标准化需求列表 V2.3.x 格式追加进对应模块 sheet（确定性零 LLM）。"""
    from template_writer import run_writer

    out_dir = out_dir.expanduser().resolve()
    report = run_writer(out_dir, template_path.expanduser().resolve())
    return {
        "kind": "template_write",
        "out_dir": str(out_dir),
        "report": report,
        "written": [str(out_dir / name) for name in report.get("written") or []
                    if (out_dir / name).exists()],
        "summary": build_output_summary(out_dir),
    }


def ai_extract_task(out_dir: Path, *, route: str | None, limit_sections: int | None = None,
                    sample_ratio: float | None = None) -> dict[str, Any]:
    """AI 主抽 + 双引擎合并：AI 行为需求 + 确定性结构需求 → merged_spec.xlsx/json。

    试抽模式（「测试运行」用）：sample_ratio 按比例抽样（0.2=全文 1/5，随文档自适应）；
    limit_sections 固定 N 章（CLI 用）。"""
    out_dir = out_dir.expanduser().resolve()
    result = ai_extract.run_ai_extract(out_dir, route=route, merge_deterministic=True,
                                       progress_callback=emit_progress,
                                       limit_sections=limit_sections,
                                       sample_ratio=sample_ratio)
    return {
        "kind": "ai_extract",
        "out_dir": str(out_dir),
        "route": result.get("route"),
        "count": result.get("requirements", 0),
        "merged": result.get("merged", {}),
        "sections": result.get("sections", 0),
        "failed_sections": result.get("failed_sections", 0),
        "code_drift_flagged": result.get("code_drift_flagged", 0),
        "int_drift_flagged": result.get("int_drift_flagged", 0),
        "note": result.get("note", ""),
        "quality": result.get("quality", {}),
        "sampled": result.get("sampled"),
        "consistency": result.get("consistency", {}),
        "written": [str(out_dir / name) for name in result.get("written", [])],
        "summary": build_output_summary(out_dir),
    }


RUN_MANIFEST = "run_manifest.json"

# 阶段名 == 子命令名（manifest 键与 CLI 一致，GUI 单步按钮与 chain 写同一本账）
CHAIN_ORDER = ["ai-extract", "assemble", "requirements-analysis", "template-write",
               "clarification-report", "compose", "export-annotation-html"]


def stage_producer(stage: str) -> str:
    """阶段 → 生产者版本戳（产物血统：今天拿 v9 数据当新结果看的事故，靠它绝迹）。"""
    try:
        if stage == "ai-extract":
            from ai_extract import AI_EXTRACT_PROMPT_VERSION
            return AI_EXTRACT_PROMPT_VERSION
        if stage == "requirements-analysis":
            from requirements_analysis import ANALYZE_PROMPT_VERSION
            return ANALYZE_PROMPT_VERSION
    except Exception:  # pragma: no cover - 版本戳失败不阻断任务
        pass
    return {"assemble": "assemble_spec/v1", "template-write": "template_writer/v1",
            "clarification-report": "clarification/v2-tiered", "compose": "engineering_composer/v1",
            "export-annotation-html": "doc_annotation_export/v1", "run": "pipeline/v1",
            "llm-review": "review/v1"}.get(stage, stage)


def update_run_manifest(out_dir: Path, stage: str, status: str, *,
                        error: str | None = None) -> None:
    """run_manifest.json：out_dir 的显式状态账本（阶段/状态/版本/时间）。写失败不阻断任务。"""
    import datetime as _dt
    path = Path(out_dir).expanduser().resolve() / RUN_MANIFEST
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    stages = data.get("stages")
    if not isinstance(stages, dict):
        stages = {}
    now = _dt.datetime.now().isoformat(timespec="seconds")
    entry = stages.get(stage) if isinstance(stages.get(stage), dict) else {}
    if status == "running":
        entry = {"status": "running", "started": now, "producer": stage_producer(stage)}
    else:
        entry.update({"status": status, "finished": now, "producer": stage_producer(stage)})
        if error:
            entry["error"] = str(error)[:300]
        else:
            entry.pop("error", None)
    stages[stage] = entry
    data.update({"manifest_version": 1, "stages": stages, "updated": now})
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:  # pragma: no cover - manifest 写失败不阻断任务本体
        LOGGER.warning("run_manifest 写入失败（忽略）：%s", path)


def chain_task(out_dir: Path, *, stages: list[str], route: str = "stub",
               template_path: Path | None = None,
               sample_ratio: float | None = None,
               limit_sections: int | None = None) -> dict[str, Any]:
    """交付物链的后端单命令编排（F1：编排从 App.vue 搬回后端——headless/批量/CI 的地基）。

    阶段按 CHAIN_ORDER 归一排序去重；template-write 无模板路径时前置报错（不跑一半才死）；
    逐阶段发进度事件并记 run_manifest；任一阶段失败 → 记账后整链响亮失败。
    """
    out_dir = out_dir.expanduser().resolve()
    unknown = [s for s in stages if s not in CHAIN_ORDER]
    if unknown:
        raise ValueError(f"未知阶段：{', '.join(unknown)}（可用：{', '.join(CHAIN_ORDER)}）")
    ordered = [s for s in CHAIN_ORDER if s in set(stages)]
    if not ordered:
        raise ValueError("阶段清单为空")
    if "template-write" in ordered and template_path is None:
        raise ValueError("template-write 阶段需要 --template（公司需求列表模板路径）")

    runners: dict[str, Any] = {
        "ai-extract": lambda: ai_extract_task(out_dir, route=route,
                                              limit_sections=limit_sections,
                                              sample_ratio=sample_ratio),
        "assemble": lambda: assemble_task(out_dir, enrich_route=route if route != "stub" else None),
        "requirements-analysis": lambda: requirements_analysis_task(
            out_dir, route=route, template_path=template_path),
        "template-write": lambda: template_write_task(out_dir, template_path),
        "clarification-report": lambda: clarification_report_task(out_dir),
        "compose": lambda: compose_task(out_dir),
        "export-annotation-html": lambda: export_annotation_html_task(out_dir),
    }

    results: dict[str, Any] = {}
    payload: dict[str, Any] = {"kind": "chain", "out_dir": str(out_dir), "stages": ordered}
    for index, stage in enumerate(ordered, start=1):
        emit_progress({"stage": "chain", "step": stage, "completed": index - 1,
                       "total": len(ordered), "percent": int((index - 1) * 100 / len(ordered))})
        update_run_manifest(out_dir, stage, "running")
        try:
            stage_payload = runners[stage]()
        except Exception as exc:
            update_run_manifest(out_dir, stage, "failed", error=str(exc))
            raise RuntimeError(f"{stage} 阶段失败：{exc}") from exc
        update_run_manifest(out_dir, stage, "ok")
        stage_payload = dict(stage_payload or {})
        stage_payload.pop("summary", None)   # 各阶段的 summary 体积大且重复，链尾统一给一份
        results[stage] = stage_payload
        # 顶层聚合：GUI 消息只看这几个键，不必翻 results
        if stage == "ai-extract":
            for key in ("consistency", "sampled", "quality", "count"):
                if stage_payload.get(key) is not None:
                    payload[key] = stage_payload[key]
        elif stage == "requirements-analysis":
            payload["analysis"] = stage_payload.get("analysis")
        elif stage == "template-write":
            payload["template"] = stage_payload.get("report")
        elif stage == "clarification-report":
            payload["readiness"] = stage_payload.get("readiness")
            payload["questions"] = stage_payload.get("questions")
        emit_progress({"stage": "chain", "step": stage, "completed": index,
                       "total": len(ordered), "percent": int(index * 100 / len(ordered))})

    from adjudication_bank import resolve_bank_path, update_bank
    bank_path = resolve_bank_path()
    if bank_path and "requirements-analysis" in ordered:
        try:   # 收割失败不影响链结果
            payload["adjudication_bank"] = update_bank(bank_path, out_dir)
        except Exception as exc:  # pragma: no cover
            LOGGER.warning("裁决样本库收割失败（忽略）：%s", exc)
    payload["results"] = results
    payload["summary"] = build_output_summary(out_dir)
    return payload


def export_annotation_html_task(out_dir: Path) -> dict[str, Any]:
    """生成自包含文档批注 HTML（独立、可分享、内含 localStorage 裁决 + 导出 JSON）。"""
    import doc_annotation_export
    out_dir = out_dir.expanduser().resolve()
    path = doc_annotation_export.export_annotation_html(out_dir)
    return {"kind": "annotation_html", "out_dir": str(out_dir),
            "path": str(path), "written": [str(path)]}


def import_ai_decisions_task(out_dir: Path, decisions_file: Path) -> dict[str, Any]:
    """把 HTML 导出的裁决 JSON 回灌到 ai_review_states.jsonl（合进交付物）。"""
    import ai_review_actions
    out_dir = out_dir.expanduser().resolve()
    data = json.loads(Path(decisions_file).expanduser().read_text(encoding="utf-8"))
    decisions = data.get("decisions") if isinstance(data, dict) else data
    applied = 0
    skipped = 0
    ownership_skipped = 0
    for d in (decisions or []):
        rid = str((d or {}).get("ai_req_id") or "").strip()
        status = str((d or {}).get("status") or "").strip()
        if not rid or not status:
            skipped += 1
            continue
        # 归属值单独校验：仅归属非法时丢归属、保留整行裁决（status/模块/意见不陪葬）
        ownership = str(d.get("ownership_override") or "").strip() or None
        if ownership:
            try:
                normalize_ownership(ownership)
            except ValueError:
                ownership = None
                ownership_skipped += 1
        try:
            ai_review_actions.apply_ai_review_action(
                out_dir, rid, status,
                module_override=(d.get("module_override") or None),
                ownership_override=ownership,
                reason=(d.get("reason") or ""), actor="html-import")
            applied += 1
        except ValueError:
            skipped += 1
    payload: dict[str, Any] = {"kind": "ai_decisions_import", "out_dir": str(out_dir),
                               "applied": applied, "skipped": skipped}
    if ownership_skipped:
        payload["ownership_skipped"] = ownership_skipped
    # 裁决回流交付物：导入后立即重建 merged_spec（免 LLM）
    if applied and (out_dir / "ai_requirements.jsonl").exists():
        rebuilt = ai_extract.rebuild_merged_spec(out_dir)
        payload["rebuilt"] = rebuilt
    return payload


def build_output_summary(out_dir: Path) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    requirements = read_jsonl(out_dir / "atomic_requirements.jsonl")
    reviews = read_jsonl(out_dir / "llm_review_results.jsonl")
    states = read_jsonl(out_dir / "review_states.jsonl")
    status_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    confidence_counts = {"high": 0, "medium": 0, "low": 0}
    for row in requirements:
        requirement_type = str(row.get("requirement_type") or row.get("type") or "unknown")
        type_counts[requirement_type] = type_counts.get(requirement_type, 0) + 1
        confidence = row.get("confidence")
        if isinstance(confidence, (int, float)):
            if confidence >= 0.9:
                confidence_counts["high"] += 1
            elif confidence >= 0.7:
                confidence_counts["medium"] += 1
            else:
                confidence_counts["low"] += 1
    for state in states:
        status = str(state.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "counts": {
            "requirements": len(requirements),
            "reviews": len(reviews),
            "review_states": len(states),
        },
        "status_counts": status_counts,
        "type_counts": type_counts,
        "confidence_counts": confidence_counts,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Requirement Atomizer desktop tasks.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--input", type=Path, required=True)
    run_parser.add_argument("--out", type=Path, required=True)
    run_parser.add_argument("--skip-review", action="store_true")
    run_parser.add_argument("--llm-route", choices=["stub", "openai_compatible"], default=None)
    run_parser.add_argument("--review-scope", choices=["targeted", "all"], default=None)
    run_parser.add_argument("--llm-review-limit", type=int, default=0)
    run_parser.add_argument("--chunk-chars", type=int, default=3500)
    run_parser.add_argument("--kb", type=Path, action="append", default=[])
    run_parser.add_argument("--domain-pack", type=Path, default=None)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--out", type=Path, required=True)
    export_parser.add_argument("--formats", default="csv,md")

    assemble_parser = subparsers.add_parser("assemble")
    assemble_parser.add_argument("--out", type=Path, required=True)
    assemble_parser.add_argument("--formats", default="xlsx,docx,md")
    assemble_parser.add_argument("--enrich-route", default="")
    assemble_parser.add_argument("--blue-book-index", type=Path, default=None)

    compose_parser = subparsers.add_parser("compose")
    compose_parser.add_argument("--out", type=Path, required=True)

    bank_parser = subparsers.add_parser("adjudication-bank")
    bank_parser.add_argument("--out", type=Path, required=True)
    bank_parser.add_argument("--bank", type=Path, required=True)

    answers_parser = subparsers.add_parser("import-clarification-answers")
    answers_parser.add_argument("--out", type=Path, required=True)
    answers_parser.add_argument("--file", type=Path, required=True)

    chain_parser = subparsers.add_parser("chain")
    chain_parser.add_argument("--out", type=Path, required=True)
    chain_parser.add_argument("--stages", required=True, help="逗号分隔的阶段清单（按依赖自动排序）")
    chain_parser.add_argument("--llm-route", default="stub", choices=["stub", "openai_compatible"])
    chain_parser.add_argument("--template", type=Path, default=None)
    chain_parser.add_argument("--sample-ratio", type=float, default=None)
    chain_parser.add_argument("--limit-sections", type=int, default=None)

    clarification_parser = subparsers.add_parser("clarification-report")
    clarification_parser.add_argument("--out", type=Path, required=True)

    template_write_parser = subparsers.add_parser("template-write")
    template_write_parser.add_argument("--out", type=Path, required=True)
    template_write_parser.add_argument("--template", type=Path, required=True)

    requirements_analysis_parser = subparsers.add_parser("requirements-analysis")
    requirements_analysis_parser.add_argument("--out", type=Path, required=True)
    requirements_analysis_parser.add_argument("--template", type=Path, default=None)
    requirements_analysis_parser.add_argument("--llm-route", choices=["stub", "openai_compatible"], default="stub")

    ai_extract_parser = subparsers.add_parser("ai-extract")
    ai_extract_parser.add_argument("--out", type=Path, required=True)
    ai_extract_parser.add_argument("--llm-route", choices=["stub", "openai_compatible"], default="openai_compatible")
    ai_extract_parser.add_argument("--limit-sections", type=int, default=0)
    ai_extract_parser.add_argument("--sample-ratio", type=float, default=0.0)

    summary_parser = subparsers.add_parser("summary")
    summary_parser.add_argument("--out", type=Path, required=True)

    anno_parser = subparsers.add_parser("export-annotation-html")
    anno_parser.add_argument("--out", type=Path, required=True)

    import_parser = subparsers.add_parser("import-ai-decisions")
    import_parser.add_argument("--out", type=Path, required=True)
    import_parser.add_argument("--file", type=Path, required=True, help="HTML 导出的裁决 JSON")
    return parser.parse_args(argv)


def setup_run_logging(out_dir: Path | None) -> None:
    """后端任务日志：stderr（Electron 收集持久化）+ <输出目录>/run.log（跟着交付物走）。

    此前 GUI 路径全链路零日志：LOGGER.info（LLM 调用时长/自检轮次/富化被拒原因/降级）被
    Python 兜底 handler 丢弃，Electron 只在任务失败时把 stderr 拼进弹窗。排查"为什么慢/
    为什么产物长这样"无从下手——本函数让每次运行在输出目录留下完整可追溯日志。幂等可重入。
    """
    logger = logging.getLogger("requirement_atomizer")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    have = {getattr(h, "_ratomizer_tag", None) for h in logger.handlers}
    if "stderr" not in have:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(fmt)
        handler._ratomizer_tag = "stderr"  # type: ignore[attr-defined]
        logger.addHandler(handler)
    if out_dir is not None and "runlog" not in have:
        try:
            out_dir = Path(out_dir).expanduser().resolve()
            out_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(out_dir / "run.log", encoding="utf-8")
            file_handler.setFormatter(fmt)
            file_handler._ratomizer_tag = "runlog"  # type: ignore[attr-defined]
            logger.addHandler(file_handler)
        except OSError:  # 日志落盘失败不阻断任务
            pass
    # LLM 消息级追踪：完整收发落 <out>/llm_trace.jsonl（含 prompt/响应全文/token 用量）。
    # 默认开（体量 ~几 MB/次运行，与 blocks.jsonl 同量级）；设 RATOMIZER_LLM_TRACE=0 可关。
    if out_dir is not None and os.environ.get("RATOMIZER_LLM_TRACE", "").strip() != "0":
        import llm_client
        llm_client.set_trace_path(Path(out_dir) / "llm_trace.jsonl")


def teardown_run_logging() -> None:
    """关闭并摘除 run.log 的 FileHandler（任务进程一次性；不关会锁住输出目录文件句柄）。"""
    logger = logging.getLogger("requirement_atomizer")
    for handler in list(logger.handlers):
        if getattr(handler, "_ratomizer_tag", None) == "runlog":
            handler.close()
            logger.removeHandler(handler)
    import llm_client
    llm_client.set_trace_path(None)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_run_logging(getattr(args, "out", None))
    logging.getLogger("requirement_atomizer").info("desktop task 开始：%s", args.command)
    try:
        if args.command == "run":
            payload = run_pipeline_task(
                args.input,
                args.out,
                skip_review=args.skip_review,
                llm_route=args.llm_route,
                review_scope=args.review_scope,
                llm_review_limit=args.llm_review_limit,
                chunk_chars=args.chunk_chars,
                kb_paths=args.kb,
                domain_pack_dir=args.domain_pack,
            )
        elif args.command == "export":
            payload = export_task(args.out, split_formats(args.formats))
        elif args.command == "assemble":
            payload = assemble_task(
                args.out,
                formats=split_formats(args.formats),
                enrich_route=args.enrich_route or None,
                blue_book_index_path=args.blue_book_index,
            )
        elif args.command == "compose":
            payload = compose_task(args.out)
        elif args.command == "adjudication-bank":
            from adjudication_bank import update_bank
            payload = {"kind": "adjudication_bank", **update_bank(args.bank, args.out)}
        elif args.command == "import-clarification-answers":
            from clarification_report import import_answers
            payload = {"kind": "clarification_answers", "out_dir": str(args.out),
                       **import_answers(args.out, args.file)}
        elif args.command == "chain":
            payload = chain_task(args.out, stages=[x.strip() for x in args.stages.split(",") if x.strip()],
                                 route=args.llm_route, template_path=args.template,
                                 sample_ratio=args.sample_ratio or None,
                                 limit_sections=args.limit_sections or None)
        elif args.command == "clarification-report":
            payload = clarification_report_task(args.out)
        elif args.command == "template-write":
            payload = template_write_task(args.out, args.template)
        elif args.command == "requirements-analysis":
            payload = requirements_analysis_task(args.out, route=args.llm_route, template_path=args.template)
        elif args.command == "ai-extract":
            payload = ai_extract_task(args.out, route=args.llm_route,
                                      limit_sections=args.limit_sections or None,
                                      sample_ratio=args.sample_ratio or None)
        elif args.command == "export-annotation-html":
            payload = export_annotation_html_task(args.out)
        elif args.command == "import-ai-decisions":
            payload = import_ai_decisions_task(args.out, args.file)
        else:
            payload = {"kind": "summary", "out_dir": str(args.out.expanduser().resolve()), "summary": build_output_summary(args.out)}
    except Exception as exc:
        logging.getLogger("requirement_atomizer").exception("desktop task 失败：%s", args.command)
        # 单步命令也记账（chain 内部已逐阶段记，不重复）
        if args.command in CHAIN_ORDER and getattr(args, "out", None):
            update_run_manifest(args.out, args.command, "failed", error=str(exc))
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        teardown_run_logging()
    if args.command in CHAIN_ORDER and getattr(args, "out", None):
        update_run_manifest(args.out, args.command, "ok")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def split_formats(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def emit_progress(event: dict[str, Any]) -> None:
    print(f"{PROGRESS_PREFIX}{json.dumps(event, ensure_ascii=False)}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
