"""新旧表格解析路径 A/B 门禁（WS1 第 8 周，方案 v1.1 §3.2.4 / §3.3.1）。

对给定语料目录逐文档并行运行：
  * **旧路径** ``table_structure.analyze_table``（确定性几何单轨，生产默认）；
  * **新路径** ``table_structure.analyze_table_dual_track``（强制开 ``RATOMIZER_TABLE_DUAL_TRACK``
    + 注入假设或由调用方提供假设文件，"假设优先、校验签发"）。

逐文档对比并输出"不劣化"裁决报告：
  * **受保护编码零漂移**（HARD）：OBIS / 事件号 / hex 经 ``table_geometry_validator``
    复核，任何 ``protected_encoding_drift`` 即红灯（exit 2）——这条独立于三指标，任一漂移
    即阻断切换（"OBIS 错一位是严重缺陷"）。
  * **结构增量**（informational）：每表 title/header/data 行集合在新旧路径下的差异、
    签发模式（``hypothesis_signed`` / ``fallback_*``）分布。结构差异是双轨制要测的语义变化
    本身，不单独构成 pass/fail。
  * **corpus_eval 三指标**（碎片率/漏值/覆盖率）：需要真实 atomize 输出目录
    （``--corpus-eval-roots OLD NEW``）。无真实语料时如实标注 pending，不伪造数字。

现实约束：金标 A/B 实跑依赖机器本地语料资产与冻结 ``out/`` 基线（见 AGENTS.md）。本 worktree
无这些资产，故实跑裁决标记 pending-human；本工具交付"门禁工具链就绪 + 在可用夹具上的自证"。

退出码对齐 ``docs/cli-contract.md``：0 不劣化达标 / 2 劣化或漂移或输入错误 / 3 校验错误 / 4 环境错误。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cosem_behavior_spec import extract_codes                     # noqa: E402
from docx_table_parser import ParsedCell, ParsedCellContent, ParsedDocxTable  # noqa: E402
from output_writer import write_json                               # noqa: E402
from table_geometry_validator import (                             # noqa: E402
    CODE_PROTECTED_ENCODING_DRIFT,
    validate_table_geometry,
)
from table_structure import analyze_table, analyze_table_dual_track  # noqa: E402

AB_GATE_TOOL = "parse-ab-gate"
AB_GATE_VERSION = "parse-ab-gate-v1"
AB_GATE_REPORT_SCHEMA = "parse-ab-gate-report/v1"
AB_GATE_DOCUMENT_SCHEMA = "ab-gate-document/v1"
DUAL_TRACK_SWITCH = "RATOMIZER_TABLE_DUAL_TRACK"

# corpus_eval 三指标名（碎片率/漏值/覆盖率）。碎片率映射到 self_check_ratio——自检补充
# 是"原句被拆碎后补救"的直接量化；漏值=values_left_behind；覆盖率=coverage_pct。
FRAGMENTATION_KEY = "self_check_ratio"
MISSING_VALUE_KEY = "values_left_behind"
COVERAGE_KEY = "coverage_pct"
CORPUS_EVAL_METRICS = (FRAGMENTATION_KEY, MISSING_VALUE_KEY, COVERAGE_KEY)

# 指标"不劣化"方向：True=越大越好（覆盖率），False=越小越好（碎片率、漏值）。
HIGHER_IS_BETTER = {COVERAGE_KEY: True, FRAGMENTATION_KEY: False, MISSING_VALUE_KEY: False}

# 浮点比较容差：corpus_eval 指标允许的噪声边界（避免尺子抖动误判为链路退化，方案 §4.3.1）。
DEFAULT_TOLERANCE = 0.0


# =============================================================================
# 夹具载入与 ParsedDocxTable 构造
# =============================================================================


def _parsed_cell(row: int, col: int, text: str, covered: tuple[tuple[int, int], ...] = ()) -> ParsedCell:
    return ParsedCell(
        row_index=row,
        column_index=col,
        text=text,
        raw_text=text,
        covered_coordinates=covered,
        content=ParsedCellContent((), 0),
        style_evidence={"bold": False},
    )


def build_parsed_table(table: dict[str, Any]) -> ParsedDocxTable:
    """Build a ``ParsedDocxTable`` from a fixture table dict.

    This reuses the real OOXML geometry type so the validator and both parsing
    entries see an authentic physical matrix (no parallel coordinate system).
    ``merge_ranges`` tuples are ``(r1, c1, r2, c2)``; covered coordinates are
    derived so anchors carry their covered set exactly as the parser would
    (covered coordinates never become standalone cells).
    """
    matrix = [list(row) for row in (table.get("matrix") or [])]
    width = max((len(r) for r in matrix), default=0)
    merge_ranges = [tuple(int(x) for x in mr) for mr in (table.get("merge_ranges") or [])]
    covered_set: set[tuple[int, int]] = set()
    covered_by_anchor: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for r1, c1, r2, c2 in merge_ranges:
        anchor = (r1, c1)
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                if (r, c) != anchor:
                    covered_set.add((r, c))
                    covered_by_anchor.setdefault(anchor, []).append((r, c))
    cells: dict[tuple[int, int], ParsedCell] = {}
    for r in range(1, len(matrix) + 1):
        row = matrix[r - 1]
        for c in range(1, width + 1):
            if (r, c) in covered_set:
                continue  # covered coordinate: not a canonical cell
            text = str(row[c - 1]) if c - 1 < len(row) else ""
            covered = tuple(covered_by_anchor.get((r, c), ()))
            cells[(r, c)] = _parsed_cell(r, c, text, covered)
    return ParsedDocxTable(
        width=width,
        matrix=matrix,
        raw_matrix=[list(r) for r in matrix],
        cells=cells,
        merge_ranges=merge_ranges,
        explicit_header_rows=list(table.get("explicit_header_rows") or []),
        nested_tables=[],
        parse_incomplete=False,
        parse_incomplete_reason={},
        raw_text=" ".join(str(x) for row in matrix for x in row),
    )


def load_documents(corpus: Path) -> list[dict[str, Any]]:
    """Load ``*.tables.json`` document fixtures from ``--corpus``.

    Each fixture is one document (``ab-gate-document/v1``): a list of parsed
    tables with optional hypotheses. This is the deterministic self-proof
    contract; the real-corpus A/B (full atomize twice) is pending-human.
    """
    corpus = Path(corpus).expanduser().resolve()
    if not corpus.exists():
        raise FileNotFoundError(f"corpus not found: {corpus}")
    docs: list[dict[str, Any]] = []
    if corpus.is_file():
        docs.append(json.loads(corpus.read_text(encoding="utf-8")))
        return docs
    for path in sorted(corpus.glob("*.tables.json")):
        docs.append(json.loads(path.read_text(encoding="utf-8")))
    if not docs:
        raise FileNotFoundError(
            f"no *.tables.json fixtures under {corpus} "
            "(real-corpus A/B requires atomize outputs — use --corpus-eval-roots)"
        )
    return docs


# =============================================================================
# 单表 A/B 对比
# =============================================================================


def _row_set(structure: dict[str, Any], key: str) -> set[int]:
    return set(int(x) for x in (structure.get(key) or []))


def compare_table(table: dict[str, Any]) -> dict[str, Any]:
    """Run OLD vs NEW on one table and return the per-table comparison record."""
    matrix = [list(r) for r in (table.get("matrix") or [])]
    merge_ranges = [tuple(int(x) for x in mr) for mr in (table.get("merge_ranges") or [])]
    explicit = list(table.get("explicit_header_rows") or [])
    hypothesis = table.get("hypothesis")

    structure_old = analyze_table(matrix, merge_ranges=merge_ranges, explicit_header_rows=explicit)

    parsed = build_parsed_table(table)
    # Validate the hypothesis once and reuse the result both for the dual-track
    # entry (via validator_result=) and for the independent drift sweep — avoids
    # running the deterministic validator twice per table.
    validator_result = None
    if hypothesis is not None:
        validator_result = validate_table_geometry(dict(hypothesis), parsed)

    saved = os.environ.get(DUAL_TRACK_SWITCH)
    os.environ[DUAL_TRACK_SWITCH] = "1"
    try:
        structure_new = analyze_table_dual_track(
            matrix,
            merge_ranges=merge_ranges,
            explicit_header_rows=explicit,
            hypothesis=hypothesis,
            parsed_table=parsed if hypothesis is not None else None,
            validator_result=validator_result,
        )
    finally:
        if saved is None:
            os.environ.pop(DUAL_TRACK_SWITCH, None)
        else:
            os.environ[DUAL_TRACK_SWITCH] = saved

    dual = structure_new.get("dual_track") or {}
    mode = str(dual.get("mode") or "off")

    # 受保护编码零漂移：从复跑的几何校验结果捕获 protected_encoding_drift。
    drift_reasons: list[dict[str, Any]] = []
    signed = mode == "hypothesis_signed"
    if validator_result is not None:
        for reason in validator_result.reasons:
            if reason.code == CODE_PROTECTED_ENCODING_DRIFT:
                drift_reasons.append({
                    "code": reason.code,
                    "cells": [list(c) for c in reason.cells],
                    "detail": reason.detail,
                })
    # 额外独立复核：矩阵中出现的受保护编码集合，应在新旧两路的数据格文本中都不丢失
    # （旧路无合并，恒保持；此处只对新路签发后的数据区做一次诚实核对，仅作报告，不单列红灯——
    # 几何校验器的逐字漂移检查才是权威 HARD 门）。
    codes_in_matrix = extract_codes(parsed.raw_text)
    new_data_text = " ".join(
        str(matrix[r - 1][c - 1])
        for r in (structure_new.get("data_row_indexes") or [])
        for c in range(1, (structure_new.get("width") or 0) + 1)
        if r - 1 < len(matrix) and c - 1 < len(matrix[r - 1])
    )
    codes_in_new_data = extract_codes(new_data_text)

    return {
        "table_id": str(table.get("table_id") or ""),
        "table_block_id": str(table.get("table_block_id") or ""),
        "family_id": str(table.get("family_id") or "unmatched"),
        "has_hypothesis": hypothesis is not None,
        "new_mode": mode,
        "validator_status": dual.get("validator_status"),
        "signed": signed,
        "title_rows": {"old": sorted(_row_set(structure_old, "title_row_indexes")),
                       "new": sorted(_row_set(structure_new, "title_row_indexes"))},
        "header_rows": {"old": sorted(_row_set(structure_old, "header_row_indexes")),
                        "new": sorted(_row_set(structure_new, "header_row_indexes"))},
        "data_rows": {"old": sorted(_row_set(structure_old, "data_row_indexes")),
                      "new": sorted(_row_set(structure_new, "data_row_indexes"))},
        "data_rows_reclassified_count": len(_row_set(structure_old, "data_row_indexes")
                                            .symmetric_difference(_row_set(structure_new, "data_row_indexes"))),
        "protected_encoding_drift": drift_reasons,
        "protected_encoding_drift_count": len(drift_reasons),
        "codes_in_matrix_count": len(codes_in_matrix),
        "codes_in_new_data_count": len(codes_in_new_data),
        "codes_lost_in_new_data": sorted(codes_in_matrix - codes_in_new_data),
    }


# =============================================================================
# corpus_eval 三指标对比（真实语料路径）
# =============================================================================


def _corpus_eval_compare(old_root: Path, new_root: Path) -> dict[str, Any]:
    """Run ``corpus_eval.evaluate`` on two atomize outputs and diff the 3 metrics.

    Only the three A/B metrics are compared; both dirs must contain
    ``ai_requirements.jsonl``. ``self_check_ratio`` / ``values_left_behind`` are
    float/int counts; ``coverage_pct`` may be None when ``ai_extract_quality.json``
    is absent — that is reported honestly as ``unavailable``.
    """
    from corpus_eval import evaluate as corpus_evaluate

    old = corpus_evaluate(Path(old_root))
    new = corpus_evaluate(Path(new_root))
    metric_rows: list[dict[str, Any]] = []
    degraded: list[str] = []
    for key in CORPUS_EVAL_METRICS:
        ov, nv = old.get(key), new.get(key)
        if ov is None or nv is None:
            metric_rows.append({"metric": key, "old": ov, "new": nv, "delta": None,
                                "status": "unavailable", "higher_is_better": HIGHER_IS_BETTER[key]})
            continue
        delta = round(float(nv) - float(ov), 4)
        higher_better = HIGHER_IS_BETTER[key]
        # 不劣化：好方向上 new 不低于 old（含容差），坏方向上 new 不高于 old（含容差）。
        ok = (delta >= -1e-9) if higher_better else (delta <= 1e-9)
        status = "no_degradation" if ok else "degraded"
        if not ok:
            degraded.append(key)
        metric_rows.append({"metric": key, "old": ov, "new": nv, "delta": delta,
                            "status": status, "higher_is_better": higher_better})
    return {
        "old_root": str(old_root),
        "new_root": str(new_root),
        "metrics": metric_rows,
        "degraded_metrics": degraded,
    }


# =============================================================================
# 命令
# =============================================================================


def _fail_envelope(command: str, error_type: str, message: str, *, exit_code: int) -> None:
    print(json.dumps({
        "tool": "requirement-atomizer",
        "command": command,
        "ok": False,
        "error": {"type": error_type, "message": message},
    }, ensure_ascii=False))
    raise SystemExit(exit_code)


def cmd_run(args: argparse.Namespace) -> int:
    report_path = Path(args.report).expanduser().resolve() if args.report else None
    fixture_source = str(args.corpus)

    documents = load_documents(Path(args.corpus))
    per_doc: list[dict[str, Any]] = []
    total_tables = 0
    total_drift = 0
    signed_count = 0
    fallback_count = 0
    drift_tables: list[str] = []
    for doc in documents:
        tables = doc.get("tables") or []
        doc_tables = []
        for table in tables:
            cmp = compare_table(table)
            total_tables += 1
            total_drift += cmp["protected_encoding_drift_count"]
            if cmp["signed"]:
                signed_count += 1
            else:
                fallback_count += 1
            if cmp["protected_encoding_drift_count"]:
                drift_tables.append(f"{doc.get('document_id')}/{cmp['table_id']}")
            doc_tables.append(cmp)
        per_doc.append({
            "document_id": str(doc.get("document_id") or ""),
            "tables": doc_tables,
        })

    corpus_eval_section: dict[str, Any] | None = None
    corpus_eval_degraded: list[str] = []
    if args.corpus_eval_roots is not None:
        if len(args.corpus_eval_roots) != 2:
            _fail_envelope("parse-ab-gate", "input_error",
                           "--corpus-eval-roots requires exactly two dirs (OLD NEW)", exit_code=2)
        old_root, new_root = args.corpus_eval_roots
        if not Path(old_root).is_dir() or not Path(new_root).is_dir():
            _fail_envelope("parse-ab-gate", "input_error",
                           f"corpus-eval roots must exist: {old_root} / {new_root}", exit_code=2)
        corpus_eval_section = _corpus_eval_compare(Path(old_root), Path(new_root))
        corpus_eval_degraded = corpus_eval_section.get("degraded_metrics", [])

    # 裁决：受保护编码零漂移是 HARD（任一漂移即红灯）；corpus_eval 指标劣化即红灯；
    # 无 corpus_eval 时（夹具模式）只以 HARD 门裁决，并如实标注 corpus_eval 为 pending。
    drift_red = total_drift > 0
    metric_red = bool(corpus_eval_degraded)
    decision = "fail" if (drift_red or metric_red) else "pass"

    report = {
        "schema": AB_GATE_REPORT_SCHEMA,
        "tool": AB_GATE_TOOL,
        "version": AB_GATE_VERSION,
        "fixture_source": fixture_source,
        "fixture_mode": args.corpus_eval_roots is None,
        "summary": {
            "documents": len(per_doc),
            "tables": total_tables,
            "signed": signed_count,
            "fallback": fallback_count,
            "protected_encoding_drift_total": total_drift,
            "drift_tables": drift_tables,
        },
        "documents": per_doc,
        "corpus_eval": corpus_eval_section if corpus_eval_section is not None else {
            "status": "pending",
            "reason": ("corpus_eval 三指标对比需要真实 atomize 输出目录（--corpus-eval-roots OLD NEW）。"
                       " 本 worktree 无金标语料/冻结 out/ 基线，实跑裁决 pending-human。"),
        },
        "decision": decision,
        "red_lights": {
            "protected_encoding_drift": drift_red,
            "corpus_eval_degraded_metrics": corpus_eval_degraded,
        },
        "note": ("受保护编码零漂移为 HARD 门（独立于三指标）；corpus_eval 碎片率/漏值/覆盖率"
                 " 需真实 atomize 输出；结构增量（title/header/data 行差异）为 informational，"
                 " 不单独构成 pass/fail。"),
    }
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(report_path, report)

    envelope = {
        "tool": "requirement-atomizer",
        "command": "parse-ab-gate",
        "ok": decision == "pass",
        "decision": decision,
        "documents": len(per_doc),
        "tables": total_tables,
        "signed": signed_count,
        "fallback": fallback_count,
        "protected_encoding_drift_total": total_drift,
        "corpus_eval_status": ("compared" if corpus_eval_section else "pending"),
        "report": str(report_path) if report_path else None,
        "error": ({"type": "degradation_detected",
                   "message": (("protected-encoding drift on: " + ", ".join(drift_tables))
                               if drift_red else "corpus_eval degraded: " + ", ".join(corpus_eval_degraded))}
                  if decision == "fail" else None),
    }
    print(json.dumps(envelope, ensure_ascii=False))
    return 0 if decision == "pass" else 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parse_ab_gate.py",
        description="新旧表格解析路径 A/B 门禁（WS1 wk8）。退出码 0/2/3/4 对齐 cli-contract。",
    )
    parser.add_argument("--corpus", type=Path, required=True,
                        help="语料目录（*.tables.json 夹具，或单个夹具文件）")
    parser.add_argument("--corpus-eval-roots", type=Path, nargs=2, default=None,
                        metavar=("OLD", "NEW"),
                        help="真实 atomize 输出目录对（旧/新），用于 corpus_eval 三指标对比")
    parser.add_argument("--report", type=Path, default=None, help="输出裁决报告 JSON")
    parser.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        try:
            return int(args.func(args))
        except FileNotFoundError as exc:
            _fail_envelope("parse-ab-gate", "input_error", str(exc), exit_code=2)
        except (ValueError, KeyError, TypeError) as exc:
            _fail_envelope("parse-ab-gate", "validation_error",
                           f"{type(exc).__name__}: {exc}", exit_code=3)
        except OSError as exc:
            _fail_envelope("parse-ab-gate", "environment_error",
                           f"{type(exc).__name__}: {exc}", exit_code=4)
    except SystemExit as exc:
        # _fail_envelope / argparse abort by raising SystemExit(code). In-process
        # callers (tests) get the int code; the ``__main__`` block still exits
        # with it via ``sys.exit(main())``.
        return int(exc.code) if isinstance(exc.code, int) else 1


if __name__ == "__main__":
    sys.exit(main())
