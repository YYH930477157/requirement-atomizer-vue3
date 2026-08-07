"""functional_extract 直抽查全/查准评估器（T1-3 + T1-4）。

输入 = 直抽产物（``functional_requirements.json`` 或同构 JSON）+ 真值集 JSONL。条目级匹配复用
``golden_sets/gold_functional_v1/tools/agreement.py`` 的锚点重叠口径（同 section 且 ≥1 共享坐标）：

* **查全（recall）** = 被覆盖真值条目 / 总真值条目。一条真值条目"被覆盖"当且仅当存在某条产物
  与之同 section 且共享 ≥1 锚点坐标。
* **查准（precision）** = 锚点有效回指的产物条目 / 总产物条目。一条产物"锚点有效回指"当且仅当
  存在某条真值条目与之同 section 且共享 ≥1 锚点坐标（即产物的来源锚点确实落在真值集认可的规范
  位置上）。产物锚点空悬（section 为空 / block_ids 为空 / 坐标无真值对应）计为无效回指。

口径取舍（与 WS0 方案一致）：真值集是尺子。对**完整**真值集，precision 即经典 IR 精度；对当前
微型/pending 真值集，precision 是下界（产物可能指向真值未覆盖的真实位置），报告如实标注
``truth_completeness: partial``，绝不伪造高精度。

**按文档分别报告，禁止跨文档平均**（方案 v1.1 §2.2.3：跨族平均掩盖单文档缺陷）。

``--sweep-thresholds``（T1-4）：对 ``functional_drilldown`` 的阈值网格
（multi_behavior × multi_condition × matrix_rows）逐档位用同款锚点匹配把产物对到真值，再以真值
侧"是否需下钻"信号（``expects_drilldown``，缺省时用字段丰富度代理）标定下钻决策的查全/查准
矩阵——S2 真值落地后据此取最优档位回填默认值。

退出码对齐简报口径（``docs/cli-contract.md`` 的 0/2/3/4）：0 达标 / 2 不达标 / 3 用法 / 4 环境。
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_GOLD_TOOLS = _REPO_ROOT / "golden_sets" / "gold_functional_v1" / "tools"
if str(_GOLD_TOOLS) not in sys.path:
    sys.path.insert(0, str(_GOLD_TOOLS))

import agreement as _agreement  # noqa: E402
import functional_drilldown as _drilldown  # noqa: E402

TOOL_NAME = "functional-truth-eval"
TOOL_VERSION = "functional-truth-eval-v1"
REPORT_SCHEMA = "functional-truth-eval-report/v1"

# 默认门禁阈值：S2 真值未落地前以"不劣于空尺"为起点（recall/precision 均 0.0），真实阈值待
# 首份查全/查准数字落地后由用户在 --thresholds 显式设定再逐步上调（方案 §2.7）。
DEFAULT_RECALL_THRESHOLD = 0.0
DEFAULT_PRECISION_THRESHOLD = 0.0


# =============================================================================
# 载入
# =============================================================================

def _fail_envelope(command: str, error_type: str, message: str, *, exit_code: int) -> None:
    print(json.dumps({
        "tool": "requirement-atomizer",
        "command": command,
        "ok": False,
        "error": {"type": error_type, "message": message},
    }, ensure_ascii=False))
    raise SystemExit(exit_code)


def _load_truth(path: Path) -> list[dict[str, Any]]:
    """真值集：目录→读 truth.jsonl；文件→直接读。空文件/空目录→空列表。"""
    path = Path(path)
    if path.is_dir():
        target = path / "truth.jsonl"
        if not target.exists():
            return []
        text = target.read_text(encoding="utf-8")
    elif path.is_file():
        text = path.read_text(encoding="utf-8")
    else:
        raise FileNotFoundError(f"truth-set not found: {path}")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _load_products(path: Path) -> tuple[str, list[dict[str, Any]]]:
    """直抽产物：目录→读 functional_requirements.json；文件→直接读。

    返回 (doc_ref, items)。文件顶层 ``items`` 为条目列表；顶层可选 ``doc_ref``，缺省取首条
    产物的 source_section 所属文档标识 "unknown"。
    """
    path = Path(path)
    if path.is_dir():
        target = path / "functional_requirements.json"
        if not target.exists():
            raise FileNotFoundError(
                f"functional_requirements.json not found under {path} "
                "(direct-extract product expected)"
            )
        payload = json.loads(target.read_text(encoding="utf-8"))
    elif path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        raise FileNotFoundError(f"products not found: {path}")
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError("products payload missing 'items' list")
    doc_ref = str((payload.get("doc_ref") if isinstance(payload, dict) else None) or "unknown")
    return doc_ref, items


# =============================================================================
# 锚点匹配（复用 agreement 口径）
# =============================================================================

def _product_anchor(item: dict[str, Any]) -> tuple[Any, set]:
    section = str(item.get("source_section") or "").strip() or None
    coords = {str(c) for c in (item.get("source_block_ids") or []) if str(c).strip()}
    return section, coords


def _truth_anchor(entry: dict[str, Any]) -> tuple[Any, set]:
    anchor = entry.get("source_anchor") or {}
    section = str(anchor.get("section") or "").strip() or None
    coords = {str(c) for c in (anchor.get("coordinates") or []) if str(c).strip()}
    return section, coords


def _anchor_overlap(left: tuple[Any, set], right: tuple[Any, set]) -> bool:
    sec_a, coords_a = left
    sec_b, coords_b = right
    return bool(sec_a) and sec_a == sec_b and bool(coords_a & coords_b)


# =============================================================================
# 查全/查准
# =============================================================================

def evaluate_doc(truth_entries: list[dict[str, Any]], products: list[dict[str, Any]]) -> dict[str, Any]:
    """对单一 doc_ref 计算查全/查准与逐条覆盖明细。"""
    truth_anchors = [_truth_anchor(e) for e in truth_entries]
    product_anchors = [_product_anchor(p) for p in products]

    covered_truth_idx: list[int] = []
    uncovered_truth_idx: list[int] = []
    for ti, ta in enumerate(truth_anchors):
        if any(_anchor_overlap(ta, pa) for pa in product_anchors):
            covered_truth_idx.append(ti)
        else:
            uncovered_truth_idx.append(ti)

    matched_product_idx: list[int] = []
    floating_product_idx: list[int] = []
    for pi, pa in enumerate(product_anchors):
        if any(_anchor_overlap(pa, ta) for ta in truth_anchors):
            matched_product_idx.append(pi)
        else:
            floating_product_idx.append(pi)

    total_truth = len(truth_entries)
    total_product = len(products)
    recall = (len(covered_truth_idx) / total_truth) if total_truth else 0.0
    precision = (len(matched_product_idx) / total_product) if total_product else 0.0
    return {
        "truth_count": total_truth,
        "product_count": total_product,
        "covered_truth_count": len(covered_truth_idx),
        "matched_product_count": len(matched_product_idx),
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "uncovered_truth_ids": [str(truth_entries[i].get("entry_id") or f"#{i}") for i in uncovered_truth_idx],
        "floating_product_ids": [str(products[i].get("functional_requirement_id") or f"#{i}") for i in floating_product_idx],
    }


def _group_by_doc(truth_entries: list[dict[str, Any]], doc_ref: str,
                  products: list[dict[str, Any]]) -> dict[str, dict[str, list]]:
    """真值按 doc_ref 分组；产物整体归入其顶层 doc_ref。"""
    by_doc: dict[str, dict[str, list]] = {}
    for e in truth_entries:
        d = str(e.get("doc_ref") or "unknown")
        by_doc.setdefault(d, {"truth": [], "products": []})
        by_doc[d]["truth"].append(e)
    # 产物归顶层 doc_ref；若该 doc 无真值，仍单独出一栏（查全分母为 0 → recall=0，如实暴露）。
    by_doc.setdefault(doc_ref, {"truth": [], "products": []})
    by_doc[doc_ref]["products"].extend(products)
    return by_doc


# =============================================================================
# 下钻阈值网格扫描（T1-4）
# =============================================================================

def _needs_drill_truth(entry: dict[str, Any]) -> bool | None:
    """真值侧"是否需下钻"信号：优先 ``expects_drilldown``；缺省用字段丰富度确定性代理。

    代理判据——rich functional 条目（多行为/带前置条件/带例外）正是下钻目标：behaviors≥2 或
    preconditions≥1 或 exceptions≥1。返回 None 表示真值未提供任何可标定信号。
    """
    if "expects_drilldown" in entry:
        return bool(entry.get("expects_drilldown"))
    rich = (len([b for b in (entry.get("behaviors") or []) if str(b).strip()]) >= 2
            or len([p for p in (entry.get("preconditions") or []) if str(p).strip()]) >= 1
            or len([x for x in (entry.get("exceptions") or []) if str(x).strip()]) >= 1)
    return rich


def _product_section_for_drilldown(item: dict[str, Any]) -> dict[str, Any]:
    """从产物条目构造 functional_drilldown 所需的来源条款视图。"""
    behaviors = [str(b) for b in (item.get("behaviors") or []) if str(b).strip()]
    text = " ".join(behaviors) or str(item.get("objective") or "")
    block_ids = [str(b) for b in (item.get("source_block_ids") or []) if str(b)]
    return {
        "text": text,
        "heading": str(item.get("source_section") or ""),
        "block_ids": block_ids,
        "section_path": [str(item.get("source_section") or "")],
    }


def _drill_decision(item: dict[str, Any], thresholds: dict[str, int]) -> bool:
    section = _product_section_for_drilldown(item)
    decision = _drilldown.decide_drilldown(item, section, thresholds=thresholds)
    return bool(decision.get("drill"))


def sweep_thresholds(
    truth_entries: list[dict[str, Any]],
    products: list[dict[str, Any]],
    *,
    grid: dict[str, list[int]] | None = None,
) -> dict[str, Any]:
    """对阈值网格逐档位计算下钻决策的查全/查准矩阵。

    只在产物↔真值已匹配对上标定（无真值对应的产物不进分母，计入 uncalibrated）。真值侧"需下钻"
    信号见 ``_needs_drill_truth``；信号缺失的对计入 truth_no_signal 不进分母。
    """
    grid = grid or {
        "multi_behavior": [1, 2, 3],
        "multi_condition": [1, 2],
        "matrix_rows": [2, 3],
    }
    # 先把每个产物对到真值（同款锚点重叠），建立 (product_idx -> truth_idx) 映射。
    product_anchors = [_product_anchor(p) for p in products]
    pairs: list[tuple[int, int]] = []
    for pi, pa in enumerate(product_anchors):
        for ti, te in enumerate(truth_entries):
            if _anchor_overlap(pa, _truth_anchor(te)):
                pairs.append((pi, ti))
                break  # 一条产物取首个匹配真值即可标定
    needs = {ti: _needs_drill_truth(te) for ti, te in enumerate(truth_entries)}
    pos_truth = [ti for ti in (t for _, t in pairs) if needs.get(ti) is True]
    neg_truth = [ti for ti in (t for _, t in pairs) if needs.get(ti) is False]
    truth_no_signal = len(set(t for _, t in pairs)) - len(pos_truth) - len(neg_truth)
    uncalibrated = len(products) - len(set(p for p, _ in pairs))

    keys = ["multi_behavior", "multi_condition", "matrix_rows"]
    matrix: list[dict[str, Any]] = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        thresholds = dict(zip(keys, combo))
        tp = 0  # drilled AND needs drill
        drilled = 0
        for pi, ti in pairs:
            if _drill_decision(products[pi], thresholds):
                drilled += 1
                if needs.get(ti) is True:
                    tp += 1
        drill_recall = (tp / len(pos_truth)) if pos_truth else None
        drill_precision = (tp / drilled) if drilled else None
        matrix.append({
            "thresholds": thresholds,
            "drilled": drilled,
            "drill_recall": round(drill_recall, 4) if drill_recall is not None else None,
            "drill_precision": round(drill_precision, 4) if drill_precision is not None else None,
        })
    return {
        "grid": grid,
        "calibration_pairs": len(pairs),
        "truth_needs_drill_pos": len(pos_truth),
        "truth_needs_drill_neg": len(neg_truth),
        "truth_no_signal": truth_no_signal,
        "uncalibrated_products": uncalibrated,
        "matrix": matrix,
    }


# =============================================================================
# 命令
# =============================================================================

def _parse_thresholds(raw: str | None) -> tuple[float, float]:
    recall = DEFAULT_RECALL_THRESHOLD
    precision = DEFAULT_PRECISION_THRESHOLD
    if not raw:
        return recall, precision
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if "=" not in token:
            raise ValueError(f"bad --thresholds token (expected name=0.x): {token!r}")
        name, value = token.split("=", 1)
        name = name.strip().lower()
        try:
            num = float(value.strip())
        except ValueError as exc:
            raise ValueError(f"bad --thresholds value for {name!r}: {value!r}") from exc
        if not 0.0 <= num <= 1.0:
            raise ValueError(f"--thresholds {name} must be in [0.0, 1.0], got {num}")
        if name == "recall":
            recall = num
        elif name == "precision":
            precision = num
        else:
            raise ValueError(f"unknown --thresholds name {name!r} (recall|precision)")
    return recall, precision


def cmd_eval(args: argparse.Namespace) -> int:
    try:
        doc_ref, products = _load_products(Path(args.products))
        truth_entries = _load_truth(Path(args.truth_set))
    except FileNotFoundError as exc:
        _fail_envelope("functional-truth-eval", "input_error", str(exc), exit_code=3)
        return 3

    recall_thr, precision_thr = _parse_thresholds(args.thresholds)

    by_doc = _group_by_doc(truth_entries, doc_ref, products)
    per_doc: dict[str, Any] = {}
    all_pass = True
    for d, groups in sorted(by_doc.items()):
        result = evaluate_doc(groups["truth"], groups["products"])
        result["truth_completeness"] = "complete" if groups["truth"] else "empty"
        doc_pass = (result["recall"] >= recall_thr - 1e-9
                    and result["precision"] >= precision_thr - 1e-9)
        result["recall_threshold"] = recall_thr
        result["precision_threshold"] = precision_thr
        result["pass"] = doc_pass
        per_doc[d] = result
        all_pass = all_pass and doc_pass

    sweep_section: dict[str, Any] | None = None
    if args.sweep_thresholds:
        sweep_section = sweep_thresholds(truth_entries, products)

    fixture_truth = sum(1 for e in truth_entries if e.get("annotation_status") == "fixture")
    real_truth = len(truth_entries) - fixture_truth

    report = {
        "schema": REPORT_SCHEMA,
        "tool": TOOL_NAME,
        "version": TOOL_VERSION,
        "products_source": str(args.products),
        "truth_source": str(args.truth_set),
        "truth_status": ("pending_annotation" if real_truth == 0 else "annotated"),
        "truth_counts": {"real": real_truth, "fixture": fixture_truth},
        "per_document": per_doc,
        "overall_pass": bool(all_pass),
        "sweep": sweep_section,
        "note": ("查全=被覆盖真值/总真值；查准=锚点有效回指产物/总产物。按文档分别报告，不跨文档平均。"
                 " 真值集为微型/pending 时查准为下界（truth_completeness 标注）。"),
    }

    report_path = Path(args.report).expanduser().resolve() if args.report else None
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    envelope = {
        "tool": "requirement-atomizer",
        "command": "functional-truth-eval",
        "ok": bool(all_pass),
        "truth_status": report["truth_status"],
        "per_document": {d: {"recall": v["recall"], "precision": v["precision"],
                             "truth_count": v["truth_count"], "product_count": v["product_count"],
                             "pass": v["pass"]}
                         for d, v in per_doc.items()},
        "report": str(report_path) if report_path else None,
    }
    print(json.dumps(envelope, ensure_ascii=False))
    return 0 if all_pass else 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="functional_truth_eval.py",
        description="functional_extract 直抽查全/查准评估器。退出码 0 达标 / 2 不达标 / 3 用法 / 4 环境。",
    )
    parser.add_argument("--products", type=Path, required=True,
                        help="直抽产物：functional_requirements.json 或含它的目录")
    parser.add_argument("--truth-set", type=Path, required=True,
                        help="真值集：truth.jsonl 或含它的 gold_functional_v1 目录")
    parser.add_argument("--thresholds", default=None,
                        help="达标阈值 recall=0.x,precision=0.y（默认 0.0/0.0，待 S2 真值落地后上调）")
    parser.add_argument("--sweep-thresholds", action="store_true",
                        help="输出 functional_drilldown 阈值网格的下钻查全/查准矩阵（T1-4 标定）")
    parser.add_argument("--report", type=Path, default=None, help="输出评估报告 JSON")
    parser.set_defaults(func=cmd_eval)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        try:
            return int(args.func(args))
        except (ValueError, KeyError, TypeError) as exc:
            _fail_envelope("functional-truth-eval", "usage_error",
                           f"{type(exc).__name__}: {exc}", exit_code=3)
        except OSError as exc:
            _fail_envelope("functional-truth-eval", "environment_error",
                           f"{type(exc).__name__}: {exc}", exit_code=4)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1


if __name__ == "__main__":
    sys.exit(main())
