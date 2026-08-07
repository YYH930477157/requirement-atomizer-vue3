"""角色语义抽审门禁工具（WS1 第 8 周 A/B 第四项，规格 `03-角色语义抽审门禁规格.md`）。

三个子命令：``sample`` / ``record`` / ``evaluate``。本工具是方案 v1.1 §3.2.4 / §3.3.1
「角色语义抽审 ≥95%」的执行口径——几何校验器签发只保证几何合法、不保证语义正确，
真正的质量闸门在这里：对**签发成功**的假设按 ``文档 × 表格族`` 分层抽样，专家逐格
裁定角色对错，按族分别计算准确率，任一族低于阈值即阻断切换。

纪律（规格 §1-§5）：
  * 抽样框仅含签发成功的假设（``validator_status == "issued"``）。校验失败入人工面板
    的不在内——那部分已有专家全量兜底。
  * 分层：``文档 × 表格族``（parameter_matrix / obis_object / event_code，复用
    ``table_family_templates``）；每层 ``min(per_family, 签发量的 20%)`` 且覆盖
    ≥ ``min_cells`` 个数据格；种子固定并记录，周五门禁可复现。
  * 逐格二元判定：假设角色 ≠ 专家判定即错格，无部分分；语义合并声明按"格组"单独判。
  * 指标按族分别计算，**禁止跨族合并平均**。
  * 坐标体系必须复用 ``table_cell_items.jsonl``（cell_id + [row_index, column_index]），
    不新造坐标系——否则专家裁定无法回指批注 HTML。

退出码对齐 ``docs/cli-contract.md``：0 达标 / 2 不达标或输入错误 / 3 校验错误 / 4 环境错误。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

# Make the repo root importable when run as ``python tools/table_role_audit.py``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from io_utils import read_jsonl                        # noqa: E402
from output_writer import write_json, write_jsonl      # noqa: E402
from table_family_templates import (                   # noqa: E402
    TableFamilyTemplate,
    load_table_family_templates,
    match_table_family,
)
from table_structure import STRUCTURAL_ROLES           # noqa: E402

# --- schema 版本常量（工作单/裁定/报告三件存档）---------------------------------
ROLE_AUDIT_TOOL = "table-role-audit"
ROLE_AUDIT_VERSION = "table-role-audit-v1"
WORKSHEET_SCHEMA = "role-audit-worksheet/v1"
VERDICT_SCHEMA = "role-audit-verdict/v1"
REPORT_SCHEMA = "role-audit-report/v1"
SIGNED_HYPOTHESIS_SCHEMA = "signed-table-hypothesis/v1"

# 受保护的角色枚举——与 table_structure.STRUCTURAL_ROLES / 复核面板逐项对齐。
ROLE_SET = set(STRUCTURAL_ROLES)

# 默认阈值（方案 §3.3.1 估算初值 0.95）；第 8 周首轮实测后以"误判导致的下游条款候选
# 错误率"回填标定，记录进指标台账。
DEFAULT_THRESHOLD = 0.95


# =============================================================================
# 语料 / 假设载入
# =============================================================================


def _iter_corpus_docs(corpus: Path) -> list[tuple[str, Path]]:
    """Yield ``(document_id, dir)`` pairs under ``--corpus``.

    A document is an atomize output directory that contains
    ``table_cell_items.jsonl``. If ``corpus`` itself is such a directory it is
    treated as one document (id = its name); otherwise each first-level
    subdirectory that contains the file is a document.
    """
    corpus = Path(corpus).expanduser().resolve()
    if not corpus.is_dir():
        raise FileNotFoundError(f"corpus directory not found: {corpus}")
    if (corpus / "table_cell_items.jsonl").is_file():
        return [(corpus.name or str(corpus), corpus)]
    docs: list[tuple[str, Path]] = []
    for child in sorted(p for p in corpus.iterdir() if p.is_dir()):
        if (child / "table_cell_items.jsonl").is_file():
            docs.append((child.name or str(child), child))
    return docs


def load_cell_items(corpus: Path) -> dict[str, list[dict[str, Any]]]:
    """Read ``table_cell_items.jsonl`` across the corpus, keyed by ``table_id``.

    Coordinate authority lives here (规格 §5). Every worksheet cell reuses the
    ``cell_id`` and ``[row_index, column_index]`` from these records — no new
    coordinate system is invented.
    """
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for _doc_id, doc_dir in _iter_corpus_docs(corpus):
        for item in read_jsonl(doc_dir / "table_cell_items.jsonl"):
            table_id = str(item.get("table_id") or "")
            if table_id:
                grouped[table_id].append(item)
    return grouped


def load_signed_hypotheses(
    corpus: Path, explicit: Path | None
) -> list[dict[str, Any]]:
    """Load signed table-structure hypotheses (one record per table).

    Sources, in priority order: an explicit ``--hypotheses`` JSONL file, else
    ``<corpus>/table_structure_hypotheses.jsonl`` (single-doc corpus) or
    ``<doc>/table_structure_hypotheses.jsonl`` per document. Only records whose
    ``validator_status == "issued"`` enter the sampling frame (规格 §1).
    """
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    sources: list[Path] = []
    if explicit is not None:
        sources.append(Path(explicit).expanduser().resolve())
    else:
        for _doc_id, doc_dir in _iter_corpus_docs(corpus):
            hyp = doc_dir / "table_structure_hypotheses.jsonl"
            if hyp.is_file():
                sources.append(hyp)
    for src in sources:
        if not src.is_file():
            continue
        for row in read_jsonl(src):
            key = (str(row.get("document_id") or ""), str(row.get("table_id") or ""))
            if key in seen:
                continue
            seen.add(key)
            records.append(row)
    return records


def _resolve_family(
    record: dict[str, Any],
    cells: list[dict[str, Any]],
    library: TableFamilyTemplate | None,
) -> str:
    """Family for a table: explicit ``family_id`` > ``match_table_family`` on headers.

    Falls back to ``"unmatched"`` so the table is still auditable; the report
    surfaces unmatched families separately and they never get averaged into a
    named family (规格 §2 禁止跨族平均同样适用于无名族)。
    """
    family_id = str(record.get("family_id") or "").strip()
    if family_id:
        return family_id
    headers = record.get("headers")
    if not headers and cells:
        # Reconstruct a header list from header-role cells, falling back to the
        # column's header_path. Stable ordering by column_index.
        header_cells = [c for c in cells if c.get("structural_role") == "header"]
        headers = []
        for c in sorted(header_cells, key=lambda c: int(c.get("column_index") or 0)):
            hp = c.get("header_path") or []
            headers.append(str(hp[0]) if hp else str(c.get("text") or ""))
    if library is not None and headers:
        matched = match_table_family(list(headers), library)
        if matched is not None:
            return matched.family_id
    return "unmatched"


def _hypothesis_cell_roles(hypothesis: dict[str, Any]) -> dict[tuple[int, int], tuple[str, str]]:
    """``(row, col) -> (role, confidence)`` from a signed hypothesis object."""
    out: dict[tuple[int, int], tuple[str, str]] = {}
    for entry in hypothesis.get("cells") or []:
        coord = entry.get("coordinate")
        if not (isinstance(coord, (list, tuple)) and len(coord) == 2):
            continue
        r, c = int(coord[0]), int(coord[1])
        out[(r, c)] = (str(entry.get("role") or ""), str(entry.get("confidence") or ""))
    return out


# =============================================================================
# sample
# =============================================================================


def _stable_seed(seed: str, document_id: str, family_id: str) -> int:
    """Deterministic per-stratum RNG seed (固定并记录，周五门禁可复现)."""
    digest = hashlib.sha256(f"{seed}|{document_id}|{family_id}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _annotation_anchor(record: dict[str, Any], cells: list[dict[str, Any]]) -> dict[str, Any]:
    """``doc_annotation_export`` 定位锚点（规格 §1）。

    Stores the stable block id + section path so the expert can re-locate the
    table in the annotation HTML without inventing geometry (geometry legality
    is already guaranteed by signing — 规格 §1 不裁定几何).
    """
    block_id = str(record.get("table_block_id") or "")
    if not block_id and cells:
        block_id = str(cells[0].get("table_block_id") or "")
    section_path: list[str] = []
    if cells:
        section_path = [str(s) for s in (cells[0].get("section_path") or [])]
    row_indexes = sorted({int(c.get("row_index") or 0) for c in cells if c.get("row_index")})
    return {
        "block_id": block_id,
        "section_path": section_path,
        "row_indexes": row_indexes,
    }


def cmd_sample(args: argparse.Namespace) -> int:
    corpus = Path(args.corpus).expanduser().resolve()
    worksheet_path = Path(args.worksheet).expanduser().resolve()
    seed = str(args.seed)
    per_family = int(args.per_family)
    min_cells = int(args.min_cells)
    library = load_table_family_templates()

    cells_by_table = load_cell_items(corpus)
    records = load_signed_hypotheses(corpus, args.hypotheses)

    # 抽样框：仅含签发成功的假设（规格 §1）。
    frame: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    skipped_not_issued = 0
    skipped_no_cells = 0
    for record in records:
        if str(record.get("validator_status") or "").strip() != "issued":
            skipped_not_issued += 1
            continue
        table_id = str(record.get("table_id") or "")
        cells = cells_by_table.get(table_id) or []
        if not cells:
            skipped_no_cells += 1
            continue
        document_id = str(record.get("document_id") or corpus.name or "doc")
        family_id = _resolve_family(record, cells, library)
        record["_cells"] = cells
        record["_document_id"] = document_id
        record["_family_id"] = family_id
        frame[(document_id, family_id)].append(record)

    worksheet_rows: list[dict[str, Any]] = []
    strata_meta: list[dict[str, Any]] = []
    for (document_id, family_id), issued in sorted(frame.items()):
        issued_sorted = sorted(issued, key=lambda r: str(r.get("table_id") or ""))
        issued_count = len(issued_sorted)
        # 每层 min(per_family, 签发量的 20%) 张表（规格 §1）。
        cap = min(per_family, max(1, round(0.20 * issued_count)))
        rng = random.Random(_stable_seed(seed, document_id, family_id))
        # Stable, seed-driven selection: shuffle deterministically then take cap.
        order = list(range(issued_count))
        rng.shuffle(order)
        # Keep growing the selection until both the table cap and the
        # ≥min_cells data-cell floor are met, or the stratum is exhausted.
        chosen_indexes: list[int] = []
        acc_cells = 0
        for idx in order:
            if len(chosen_indexes) >= cap and acc_cells >= min_cells:
                break
            chosen_indexes.append(idx)
            table_cells = issued_sorted[idx].get("_cells") or []
            acc_cells += sum(1 for c in table_cells if c.get("structural_role") == "data")
        chosen_indexes = sorted(chosen_indexes)
        strata_meta.append({
            "document_id": document_id,
            "family_id": family_id,
            "issued_tables": issued_count,
            "table_cap": cap,
            "min_cells": min_cells,
            "sampled_tables": len(chosen_indexes),
            "sampled_data_cells": acc_cells,
            "seed_digest": format(_stable_seed(seed, document_id, family_id), "x"),
        })
        for idx in chosen_indexes:
            record = issued_sorted[idx]
            cells = record["_cells"]
            hyp_roles = _hypothesis_cell_roles(record.get("hypothesis") or {})
            cell_entries: list[dict[str, Any]] = []
            for cell in sorted(cells, key=lambda c: (int(c.get("row_index") or 0), int(c.get("column_index") or 0))):
                r = int(cell.get("row_index") or 0)
                c = int(cell.get("column_index") or 0)
                role, confidence = hyp_roles.get((r, c), ("", ""))
                cell_entries.append({
                    "cell_id": str(cell.get("cell_id") or f"R{r:06d}-C{c:06d}"),
                    "coordinate": [r, c],
                    "text": str(cell.get("text") or ""),
                    "hypothesized_role": role,
                    "confidence": confidence,
                })
            hypothesis = record.get("hypothesis") or {}
            merges = [
                {"coordinates": [list(coord) for coord in group.get("coordinates") or []]}
                for group in hypothesis.get("semantic_merges") or []
            ]
            worksheet_rows.append({
                "schema": WORKSHEET_SCHEMA,
                "document_id": document_id,
                "table_id": str(record.get("table_id") or ""),
                "table_block_id": str(record.get("table_block_id") or ""),
                "table_title": str(record.get("table_title") or ""),
                "family_id": family_id,
                "annotation_anchor": _annotation_anchor(record, cells),
                "cells": cell_entries,
                "semantic_merge_groups": merges,
            })

    worksheet_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(worksheet_path, worksheet_rows)
    meta_path = worksheet_path.with_suffix(worksheet_path.suffix + ".meta.json")
    write_json(meta_path, {
        "tool": ROLE_AUDIT_TOOL,
        "version": ROLE_AUDIT_VERSION,
        "seed": seed,
        "per_family": per_family,
        "min_cells": min_cells,
        "issued_records": len(records),
        "skipped_not_issued": skipped_not_issued,
        "skipped_no_cells": skipped_no_cells,
        "strata": strata_meta,
        "sampled_tables": len(worksheet_rows),
    })

    envelope = {
        "tool": "requirement-atomizer",
        "command": "table-role-audit sample",
        "ok": True,
        "worksheet": str(worksheet_path),
        "meta": str(meta_path),
        "sampled_tables": len(worksheet_rows),
        "strata": len(strata_meta),
        "skipped_not_issued": skipped_not_issued,
    }
    print(json.dumps(envelope, ensure_ascii=False))
    return 0


# =============================================================================
# record
# =============================================================================


def _read_expert_input(path: Path | None) -> dict[str, dict[str, str]]:
    """``cell_id -> expert_role`` from an optional expert-filled JSONL.

    Each input row may be either ``{"cell_id": ..., "expert_role": ...}`` or a
    table-scoped ``{"table_id": ..., "cells": [{"cell_id":..., "expert_role":...}]}``.
    Unknown roles are kept as-is and validated against the role enum later.
    """
    mapping: dict[str, dict[str, str]] = {}
    if path is None:
        return mapping
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"expert input not found: {path}")
    for row in read_jsonl(path):
        if "cells" in row and isinstance(row["cells"], list):
            for entry in row["cells"]:
                cid = str(entry.get("cell_id") or "")
                if cid:
                    mapping[cid] = {"expert_role": str(entry.get("expert_role") or "").strip()}
        else:
            cid = str(row.get("cell_id") or "")
            if cid:
                mapping[cid] = {"expert_role": str(row.get("expert_role") or "").strip()}
    return mapping


def cmd_record(args: argparse.Namespace) -> int:
    worksheet_path = Path(args.worksheet).expanduser().resolve()
    verdicts_path = Path(args.verdicts).expanduser().resolve()
    if not worksheet_path.is_file():
        _fail_envelope("table-role-audit record", "input_error",
                       f"worksheet not found: {worksheet_path}", exit_code=2)
    worksheet = read_jsonl(worksheet_path)
    expert = _read_expert_input(args.expert_input)

    verdict_rows: list[dict[str, Any]] = []
    blanks = 0
    filled = 0
    for table in worksheet:
        if table.get("schema") != WORKSHEET_SCHEMA:
            _fail_envelope("table-role-audit record", "validation_error",
                           f"worksheet row schema mismatch: {table.get('schema')!r}", exit_code=3)
        cell_verdicts: list[dict[str, Any]] = []
        for cell in table.get("cells") or []:
            cid = str(cell.get("cell_id") or "")
            hypo = str(cell.get("hypothesized_role") or "")
            expert_role = expert.get(cid, {}).get("expert_role", "")
            if expert_role == "":
                # No expert input for this cell → leave blank for manual fill.
                cell_verdicts.append({
                    "cell_id": cid,
                    "coordinate": cell.get("coordinate"),
                    "hypothesized_role": hypo,
                    "expert_role": None,
                    "correct": None,
                })
                blanks += 1
            else:
                correct = bool(expert_role) and expert_role == hypo
                cell_verdicts.append({
                    "cell_id": cid,
                    "coordinate": cell.get("coordinate"),
                    "hypothesized_role": hypo,
                    "expert_role": expert_role,
                    "correct": correct,
                })
                filled += 1
        merge_verdicts: list[dict[str, Any]] = []
        for group in table.get("semantic_merge_groups") or []:
            coords = group.get("coordinates") or []
            key = ",".join(f"{int(r)}:{int(c)}" for r, c in coords)
            group_entry = expert.get(key, {}).get("expert_role")
            merge_verdicts.append({
                "coordinates": coords,
                "expert_judgement": group_entry,  # None until expert fills
            })
        verdict_rows.append({
            "schema": VERDICT_SCHEMA,
            "document_id": table.get("document_id"),
            "table_id": table.get("table_id"),
            "family_id": table.get("family_id"),
            "reviewer": str(args.reviewer or ""),
            "cell_verdicts": cell_verdicts,
            "merge_group_verdicts": merge_verdicts,
        })

    verdicts_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(verdicts_path, verdict_rows)
    envelope = {
        "tool": "requirement-atomizer",
        "command": "table-role-audit record",
        "ok": True,
        "verdicts": str(verdicts_path),
        "tables": len(verdict_rows),
        "cells_filled": filled,
        "cells_blank": blanks,
    }
    print(json.dumps(envelope, ensure_ascii=False))
    return 0


# =============================================================================
# evaluate
# =============================================================================


def _fail_envelope(command: str, error_type: str, message: str, *, exit_code: int) -> None:
    """Emit a failure envelope to stdout and ``sys.exit`` with ``exit_code``."""
    print(json.dumps({
        "tool": "requirement-atomizer",
        "command": command,
        "ok": False,
        "error": {"type": error_type, "message": message},
    }, ensure_ascii=False))
    raise SystemExit(exit_code)


def cmd_evaluate(args: argparse.Namespace) -> int:
    worksheet_path = Path(args.worksheet).expanduser().resolve()
    verdicts_path = Path(args.verdicts).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve() if args.report else None
    threshold = float(args.threshold)
    if not worksheet_path.is_file():
        _fail_envelope("table-role-audit evaluate", "input_error",
                       f"worksheet not found: {worksheet_path}", exit_code=2)
    if not verdicts_path.is_file():
        _fail_envelope("table-role-audit evaluate", "input_error",
                       f"verdicts not found: {verdicts_path}", exit_code=2)

    worksheet = {(row.get("table_id")): row for row in read_jsonl(worksheet_path) if row.get("table_id")}
    verdicts = read_jsonl(verdicts_path)

    # Validate every verdict row's schema + role enum before scoring (校验错误 → exit 3).
    family_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "wrong": 0, "judged": 0})
    family_merge_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "wrong": 0, "judged": 0})
    per_table: list[dict[str, Any]] = []
    judged_cells_total = 0
    for verdict in verdicts:
        if verdict.get("schema") != VERDICT_SCHEMA:
            _fail_envelope("table-role-audit evaluate", "validation_error",
                           f"verdict row schema mismatch: {verdict.get('schema')!r}", exit_code=3)
        table_id = verdict.get("table_id")
        ws = worksheet.get(table_id)
        # S1-9：family_id 以抽样框（工作单）为准，不信 verdicts 自带值——否则伪造 verdicts
        # 可自报通过族以混入平均掩盖失败族。
        family_id = str((ws.get("family_id") if ws else "") or verdict.get("family_id") or "unmatched")
        # S1-9：假设角色真值取自工作单（抽样框），按 cell_id 建索引——evaluate 必须用 verdicts
        # 的 expert_role 与工作单的 hypothesized_role **重算** correct，不信任 verdicts 里预固化
        # 的 ``correct`` 布尔（手填 correct:true 可骗过门禁）。
        ws_hypo_by_cell: dict[str, str] = {}
        if ws:
            for c in ws.get("cells") or []:
                cid = str(c.get("cell_id") or "")
                if cid:
                    ws_hypo_by_cell[cid] = str(c.get("hypothesized_role") or "")
        t_correct = t_wrong = t_judged = 0
        for cv in verdict.get("cell_verdicts") or []:
            expert_role = cv.get("expert_role")
            if expert_role is None or expert_role == "":
                continue  # 未裁定格不计入分母
            if expert_role not in ROLE_SET:
                _fail_envelope("table-role-audit evaluate", "validation_error",
                               f"cell {cv.get('cell_id')}: expert_role {expert_role!r} not in {sorted(ROLE_SET)}",
                               exit_code=3)
            t_judged += 1
            judged_cells_total += 1
            # 重算 correct：专家裁定 == 工作单假设角色。工作单无此 cell_id（抽样框外）→ 无法
            # 核验，记为错（防伪造：verdict 引用了工作单不存在的格时不能凭 verdict 自填值通过）。
            hypo = ws_hypo_by_cell.get(str(cv.get("cell_id") or ""))
            correct = bool(hypo) and str(expert_role) == str(hypo)
            if correct:
                t_correct += 1
                family_stats[family_id]["correct"] += 1
            else:
                t_wrong += 1
                family_stats[family_id]["wrong"] += 1
        family_stats[family_id]["judged"] += t_judged
        # 语义合并按格组单独判（规格 §2），不混入格级准确率。
        m_correct = m_wrong = m_judged = 0
        for mv in verdict.get("merge_group_verdicts") or []:
            judgement = mv.get("expert_judgement")
            if judgement is None or judgement == "":
                continue
            m_judged += 1
            # Expert judgement: "correct" / "wrong" for the declared merge group.
            if str(judgement).strip().lower() in {"correct", "true", "1", "yes"}:
                m_correct += 1
                family_merge_stats[family_id]["correct"] += 1
            else:
                m_wrong += 1
                family_merge_stats[family_id]["wrong"] += 1
        family_merge_stats[family_id]["judged"] += m_judged
        per_table.append({
            "document_id": verdict.get("document_id"),
            "table_id": table_id,
            "family_id": family_id,
            "cells_judged": t_judged,
            "cells_correct": t_correct,
            "cells_wrong": t_wrong,
            "cell_accuracy": round(t_correct / t_judged, 4) if t_judged else None,
            "merge_groups_judged": m_judged,
            "merge_groups_correct": m_correct,
        })

    if judged_cells_total == 0:
        _fail_envelope("table-role-audit evaluate", "validation_error",
                       "no judged cells (fill verdicts with expert_role before evaluating)",
                       exit_code=3)

    # 按族分别计算准确率，禁止跨族合并平均（规格 §2）。
    families: list[dict[str, Any]] = []
    failing: list[str] = []
    for family_id in sorted(family_stats):
        stats = family_stats[family_id]
        judged = stats["judged"]
        accuracy = round(stats["correct"] / judged, 4) if judged else None
        meets = accuracy is not None and accuracy >= threshold
        if not meets:
            failing.append(family_id)
        merge = family_merge_stats.get(family_id, {"correct": 0, "wrong": 0, "judged": 0})
        families.append({
            "family_id": family_id,
            "cells_judged": judged,
            "cells_correct": stats["correct"],
            "cells_wrong": stats["wrong"],
            "cell_accuracy": accuracy,
            "meets_threshold": meets,
            "merge_groups_judged": merge.get("judged", 0),
            "merge_groups_correct": merge.get("correct", 0),
        })

    decision = "pass" if not failing else "fail"
    report = {
        "schema": REPORT_SCHEMA,
        "tool": ROLE_AUDIT_TOOL,
        "version": ROLE_AUDIT_VERSION,
        "threshold": threshold,
        "judged_cells_total": judged_cells_total,
        "families": families,
        "per_table": per_table,
        "failing_families": failing,
        "decision": decision,
        "note": "准确率按族分别计算，禁止跨族合并平均（规格 §2）。",
    }
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(report_path, report)

    envelope = {
        "tool": "requirement-atomizer",
        "command": "table-role-audit evaluate",
        "ok": decision == "pass",
        "decision": decision,
        "threshold": threshold,
        "families": [
            {"family_id": f["family_id"], "cell_accuracy": f["cell_accuracy"],
             "meets_threshold": f["meets_threshold"], "cells_judged": f["cells_judged"]}
            for f in families
        ],
        "failing_families": failing,
        "report": str(report_path) if report_path else None,
        "error": ({"type": "threshold_not_met",
                   "message": f"families below threshold: {', '.join(failing)}"}
                  if failing else None),
    }
    print(json.dumps(envelope, ensure_ascii=False))
    # 0 达标 / 2 不达标（规格 §3）。
    return 0 if decision == "pass" else 2


# =============================================================================
# CLI
# =============================================================================


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="table_role_audit.py",
        description="角色语义抽审门禁工具（WS1 wk8 A/B 第四项）。退出码 0/2/3/4 对齐 cli-contract。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_sample = sub.add_parser("sample", help="按 文档×表格族 分层抽样签发成功的假设")
    p_sample.add_argument("--corpus", type=Path, required=True,
                          help="语料目录（atomize 输出目录，或其父目录）")
    p_sample.add_argument("--hypotheses", type=Path, default=None,
                          help="显式签发假设 JSONL（缺省读 <corpus>/table_structure_hypotheses.jsonl）")
    p_sample.add_argument("--per-family", type=int, default=10,
                          help="每族抽样表数上限（默认 10）")
    p_sample.add_argument("--min-cells", type=int, default=300,
                          help="每层最少覆盖数据格（默认 300）")
    p_sample.add_argument("--seed", type=str, default="ws1-wk8",
                          help="抽样种子（固定并记录，周五门禁可复现）")
    p_sample.add_argument("--worksheet", type=Path, required=True,
                          help="输出工作单 JSONL 路径")
    p_sample.set_defaults(func=cmd_sample)

    p_record = sub.add_parser("record", help="把专家裁定合并为裁定 JSONL")
    p_record.add_argument("--worksheet", type=Path, required=True, help="sample 输出的工作单")
    p_record.add_argument("--verdicts", type=Path, required=True, help="输出裁定 JSONL")
    p_record.add_argument("--expert-input", type=Path, default=None,
                          help="专家填写的格级裁定 JSONL（缺省输出空白模板供人工填写）")
    p_record.add_argument("--reviewer", type=str, default="")
    p_record.set_defaults(func=cmd_record)

    p_eval = sub.add_parser("evaluate", help="按族计算格级准确率并裁决门禁")
    p_eval.add_argument("--worksheet", type=Path, required=True, help="工作单 JSONL")
    p_eval.add_argument("--verdicts", type=Path, required=True, help="record 输出的裁定 JSONL")
    p_eval.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help="格级准确率阈值（默认 0.95）")
    p_eval.add_argument("--report", type=Path, default=None, help="输出报告 JSON")
    p_eval.set_defaults(func=cmd_evaluate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        try:
            return int(args.func(args))
        except FileNotFoundError as exc:
            _fail_envelope("table-role-audit " + (args.command or ""),
                           "input_error", str(exc), exit_code=2)
        except (ValueError, KeyError, TypeError) as exc:
            _fail_envelope("table-role-audit " + (args.command or ""),
                           "validation_error", f"{type(exc).__name__}: {exc}", exit_code=3)
        except OSError as exc:
            _fail_envelope("table-role-audit " + (args.command or ""),
                           "environment_error", f"{type(exc).__name__}: {exc}", exit_code=4)
    except SystemExit as exc:
        # _fail_envelope / argparse abort by raising SystemExit(code). In-process
        # callers (tests) get the int code; the ``__main__`` block still exits
        # with it via ``sys.exit(main())``.
        return int(exc.code) if isinstance(exc.code, int) else 1


if __name__ == "__main__":
    sys.exit(main())
