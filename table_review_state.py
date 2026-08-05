"""Table-level structural review state and optimistic-concurrency writes."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections import Counter, defaultdict
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from io_utils import read_jsonl
from process_file_lock import process_file_lock
from result_package import governed_artifact_path
from table_claim_authority import (
    load_table_claim_authority_projection,
    project_table_dispositions,
)
from table_dispositions import DISPOSITIONS, validate_disposition_conservation


TABLE_REVIEW_VIEW_SCHEMA = "table-review-view/v1"
TABLE_REVIEW_STATE_SCHEMA = "table-review-state/v1"
TABLE_REVIEW_EVENT_SCHEMA = "table-review-event/v1"
TABLE_REVIEW_DECISION_VERSION = "table-review-decision-v1"
TABLE_REVIEW_STATES = "table_review_states.jsonl"
TABLE_REVIEW_EVENTS = "table_review_events.jsonl"
TABLE_REVIEW_LOCK = "table_review_states.lock"
# WS1 dual-track degradation exit (plan §3.2.2): when the geometry validator returns
# partial_conflict / invalidated for a table, the conflict-cell set is recorded here and
# surfaced in the review view so a human can adjudicate. The adjudication writeback reuses
# the existing disposition channel (apply_table_review_decision) — same state/event format,
# no new writeback shape — and clears the record once the table is resolved.
TABLE_GEOMETRY_CONFLICTS = "table_geometry_conflicts.jsonl"
TABLE_GEOMETRY_CONFLICT_SCHEMA = "table-geometry-conflict/v1"

_VALID_ROLES = {
    "title",
    "header",
    "row_header",
    "group_header",
    "data",
    "note",
    "unknown",
}
_REPLACE_ATTEMPTS = 8
_REPLACE_RETRY_DELAY_S = 0.025
_LOCKS: dict[Path, RLock] = {}
_LOCKS_GUARD = RLock()


class TableReviewConflict(ValueError):
    """The table evidence changed after the reviewer loaded it."""

    def __init__(self, message: str, *, current_fingerprint: str = "") -> None:
        super().__init__(message)
        self.current_fingerprint = current_fingerprint


def _fingerprint(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def table_evidence_fingerprint(
    table_id: str,
    dispositions: list[dict[str, Any]],
) -> str:
    """Hash the exact structural evidence and decisions shown for one table."""
    rows = []
    for row in dispositions:
        if str(row.get("table_id") or "") != str(table_id or ""):
            continue
        rows.append({
            key: row.get(key)
            for key in (
                "cell_id",
                "table_block_id",
                "text",
                "role",
                "disposition",
                "confidence",
                "evidence",
                "decision_source",
                "decision_version",
                "table_structure_version",
                "exclusion_reason",
                "applicability",
                "linked_leaf_ids",
            )
        })
    rows.sort(key=lambda row: str(row.get("cell_id") or ""))
    return _fingerprint({"table_id": str(table_id or ""), "cells": rows})


def _iter_table_blocks(blocks: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "") == "table":
            yield block
        yield from _iter_table_blocks(list(block.get("nested_tables") or []))


def _artifact_rows(root: Path, filename: str) -> list[dict[str, Any]]:
    return read_jsonl(governed_artifact_path(
        root,
        filename,
        for_write=False,
    ))


def _current_claim_projection(root: Path) -> dict[str, dict[str, Any]]:
    from claim_artifacts import CLAIM_CATALOG, claim_artifact_path

    if not claim_artifact_path(root, CLAIM_CATALOG).is_file():
        return {}
    return load_table_claim_authority_projection(root)


# --- geometry-conflict degradation exit (WS1 dual-track) ----------------------


def _normalize_conflict_cell(cell: Any) -> tuple[int, int] | None:
    """Accept (row, col) pair, [row, col] list, or {'row_index','column_index'} dict."""
    if isinstance(cell, Mapping):
        row = cell.get("row_index")
        column = cell.get("column_index")
    elif isinstance(cell, (list, tuple)) and len(cell) == 2:
        row, column = cell
    else:
        return None
    if (
        isinstance(row, int) and not isinstance(row, bool)
        and isinstance(column, int) and not isinstance(column, bool)
        and row >= 1 and column >= 1
    ):
        return (int(row), int(column))
    return None


def load_table_geometry_conflicts(root: Path) -> dict[str, dict[str, Any]]:
    """Read the geometry-conflict registry as ``{table_id: record}``.

    Absent file → empty dict (the proposer/validator simply produced no conflicts).
    """
    root = Path(root).expanduser().resolve()
    path = governed_artifact_path(root, TABLE_GEOMETRY_CONFLICTS, category="state")
    if not path.is_file():
        return {}
    records: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        table_id = str(row.get("table_id") or "")
        if table_id:
            records[table_id] = row
    return records


def _write_geometry_conflicts(root: Path, records: dict[str, dict[str, Any]]) -> None:
    path = governed_artifact_path(root, TABLE_GEOMETRY_CONFLICTS, category="state")
    rows = [records[table_id] for table_id in sorted(records)]
    _atomic_write_jsonl(path, rows)


def record_table_geometry_conflicts(
    out_dir: Path,
    *,
    table_id: str,
    conflict_cells: list[Any],
    validator_status: str,
    reasons: list[dict[str, Any]] | str = "",
    table_block_id: str = "",
) -> dict[str, Any]:
    """Record a validator-failed table's conflict-cell set for the human panel.

    ``conflict_cells`` accepts coordinate pairs (``[r, c]`` / ``(r, c)``) or
    ``{'row_index','column_index'}`` dicts — the shape ``analyze_table_dual_track``
    attaches at ``structure["dual_track"]["conflict_cells"]``. ``validator_status`` is
    ``partial_conflict`` or ``invalidated``. The read path (build_table_review_payload)
    resolves these coordinates to cell_ids when surfacing them.

    Idempotent upsert keyed by ``table_id`` under the table-review lock; the same table
    recording twice (e.g. on a re-parse) overwrites the prior record. An empty
    conflict-cell set clears the table's record (no-op degradation exit).
    """
    root = Path(out_dir).expanduser().resolve()
    table_id = str(table_id or "").strip()
    if not table_id:
        raise ValueError("table_id is required")
    coordinates: list[tuple[int, int]] = []
    for cell in conflict_cells or []:
        normalized = _normalize_conflict_cell(cell)
        if normalized is not None and normalized not in coordinates:
            coordinates.append(normalized)
    coordinates.sort()
    normalized_reasons: list[dict[str, Any]]
    if isinstance(reasons, str):
        normalized_reasons = [{"detail": reasons}] if reasons else []
    else:
        normalized_reasons = [dict(reason) for reason in reasons if isinstance(reason, Mapping)]
    with _table_review_lock(root):
        records = load_table_geometry_conflicts(root)
        if not coordinates:
            records.pop(table_id, None)
            _write_geometry_conflicts(root, records)
            return {"table_id": table_id, "cleared": True}
        record = {
            "schema": TABLE_GEOMETRY_CONFLICT_SCHEMA,
            "table_id": table_id,
            "table_block_id": str(table_block_id or ""),
            "validator_status": str(validator_status or ""),
            "conflict_cells": [
                {"row_index": row, "column_index": column} for row, column in coordinates
            ],
            "reasons": normalized_reasons,
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        records[table_id] = record
        _write_geometry_conflicts(root, records)
    return record


def clear_table_geometry_conflicts(out_dir: Path, table_id: str) -> bool:
    """Remove one table's geometry-conflict record. Returns whether a record existed."""
    root = Path(out_dir).expanduser().resolve()
    table_id = str(table_id or "").strip()
    if not table_id:
        return False
    with _table_review_lock(root):
        records = load_table_geometry_conflicts(root)
        existed = table_id in records
        if existed:
            records.pop(table_id, None)
            _write_geometry_conflicts(root, records)
    return existed



def build_table_review_payload(out_dir: Path) -> dict[str, Any]:
    """Build the read-only table review view from governed artifacts."""
    root = Path(out_dir).expanduser().resolve()
    blocks = _artifact_rows(root, "blocks.jsonl")
    cells = _artifact_rows(root, "table_cell_items.jsonl")
    dispositions_path = governed_artifact_path(
        root, "table_cell_dispositions.jsonl", for_write=False
    )
    if cells and not dispositions_path.is_file():
        # Kimi #4 遗留 / F1：有 cell_items 无 dispositions 文件 = 旧/未完成 base。与 #5 写侧门
        # 同源——读视图不得用空 dispositions 把表显示成 ready 掩盖 stale。抛
        # ClaimBaseMigrationRequired，由 GET handler（#4）映射结构化 503 提示重跑 atomize。
        from claim_artifacts import ClaimBaseMigrationRequired

        raise ClaimBaseMigrationRequired(
            "base_migration_required: table_cell_dispositions.jsonl absent while "
            "table_cell_items.jsonl is present; rerun atomize"
        )
    dispositions = _artifact_rows(root, "table_cell_dispositions.jsonl")
    dispositions = project_table_dispositions(
        dispositions,
        cells,
        _current_claim_projection(root),
    )
    geometry_conflicts = load_table_geometry_conflicts(root)
    cells_by_table: dict[str, list[dict[str, Any]]] = defaultdict(list)
    dispositions_by_table: dict[str, list[dict[str, Any]]] = defaultdict(list)
    blocks_by_table = {
        str(block.get("table_id") or ""): block
        for block in _iter_table_blocks(blocks)
        if str(block.get("table_id") or "")
    }
    for cell in cells:
        cells_by_table[str(cell.get("table_id") or "")].append(cell)
    for row in dispositions:
        dispositions_by_table[str(row.get("table_id") or "")].append(row)

    tables: list[dict[str, Any]] = []
    for table_id in sorted(
        set(cells_by_table) | set(dispositions_by_table) | set(geometry_conflicts)
    ):
        table_cells = cells_by_table.get(table_id, [])
        table_dispositions = dispositions_by_table.get(table_id, [])
        disposition_by_cell = {
            str(row.get("cell_id") or ""): row for row in table_dispositions
        }
        # WS1 dual-track degradation exit: resolve the validator's conflict coordinates
        # to cell_ids so the conflict-cell set can ride the existing review view. The
        # overlay is read-side only — it does not mutate authority dispositions. A
        # conflict cell that is not already terminal surfaces as disposition=review with
        # a geometry_conflict highlight, so the existing panel machinery and the existing
        # disposition writeback (apply_table_review_decision) handle it unchanged.
        conflict_record = geometry_conflicts.get(table_id) or {}
        conflict_coords: set[tuple[int, int]] = {
            (int(entry.get("row_index") or 0), int(entry.get("column_index") or 0))
            for entry in (conflict_record.get("conflict_cells") or [])
            if int(entry.get("row_index") or 0) >= 1
            and int(entry.get("column_index") or 0) >= 1
        }
        rendered_cells = []
        conflict_overlay_active = False
        for cell in sorted(
            table_cells,
            key=lambda row: (
                int(row.get("row_index") or 0),
                int(row.get("column_index") or 0),
                str(row.get("cell_id") or ""),
            ),
        ):
            rendered = dict(cell)
            rendered.update(disposition_by_cell.get(str(cell.get("cell_id") or ""), {}))
            coordinate = (
                int(cell.get("row_index") or 0),
                int(cell.get("column_index") or 0),
            )
            if coordinate in conflict_coords:
                current_disposition = str(rendered.get("disposition") or "")
                # Only escalate to review if the cell is not already terminal — a
                # promoted/excluded cell keeps its authority disposition; the conflict
                # just records the geometry evidence alongside it.
                if current_disposition not in {"target", "composite", "excluded"}:
                    if current_disposition != "review":
                        rendered["disposition"] = "review"
                    conflict_overlay_active = True
                rendered["decision_source"] = (
                    str(rendered.get("decision_source") or "") or "geometry_conflict"
                )
                rendered["geometry_conflict"] = True
            rendered_cells.append(rendered)
        counts = Counter(
            str(row.get("disposition") or "")
            for row in (rendered_cells or table_dispositions)
        )
        block = blocks_by_table.get(table_id, {})
        status = "pending" if counts["review"] or conflict_overlay_active else "ready"
        sources = {str(row.get("decision_source") or "") for row in table_dispositions}
        if conflict_overlay_active:
            sources.add("geometry_conflict")
        table_entry: dict[str, Any] = {
            "table_id": table_id,
            "table_block_id": str(block.get("block_id") or block.get("table_block_id") or ""),
            "title": str(block.get("table_title") or block.get("text") or ""),
            "section_path": list(block.get("section_path") or []),
            "structure_review_status": status,
            "review_mode": (
                "human" if "human" in sources
                else "geometry_conflict" if "geometry_conflict" in sources
                else "llm_assisted" if "llm_assisted" in sources
                else "automatic" if status == "ready"
                else "pending"
            ),
            "cell_count": len(table_cells),
            "target_count": counts["target"],
            "context_count": counts["context"],
            "composite_count": counts["composite"],
            "excluded_count": counts["excluded"],
            "review_count": counts["review"],
            "evidence_fingerprint": table_evidence_fingerprint(
                table_id, table_dispositions
            ),
            "cells": rendered_cells,
        }
        if conflict_record:
            table_entry["geometry_conflict"] = {
                "validator_status": str(conflict_record.get("validator_status") or ""),
                "reasons": list(conflict_record.get("reasons") or []),
                "conflict_cell_count": len(conflict_coords),
            }
        tables.append(table_entry)
    return {"schema": TABLE_REVIEW_VIEW_SCHEMA, "tables": tables}


def _process_lock_for(root: Path) -> RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(root, RLock())


@contextmanager
def _table_review_lock(root: Path) -> Iterator[None]:
    with _process_lock_for(root):
        with process_file_lock(
            governed_artifact_path(root, TABLE_REVIEW_LOCK, category="state"),
            timeout_s=10.0,
            label="table review state lock",
        ):
            yield


def _atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.{os.getpid()}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(temporary, path)
                temporary = None
                return
            except PermissionError:
                if attempt + 1 >= _REPLACE_ATTEMPTS:
                    raise
                time.sleep(_REPLACE_RETRY_DELAY_S * (attempt + 1))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _validate_role_mapping(
    table_id: str,
    table_rows: list[dict[str, Any]],
    role_mapping: dict[str, dict[str, Any]],
    *,
    resolvable_cell_ids: set[str] | None = None,
) -> None:
    if not isinstance(role_mapping, dict) or not role_mapping:
        raise ValueError("role_mapping must contain at least one cell decision")
    cell_ids = {str(row.get("cell_id") or "") for row in table_rows}
    unknown = sorted(set(role_mapping) - cell_ids)
    if unknown:
        raise ValueError(
            f"role_mapping contains cells outside table {table_id}: {unknown[:5]}"
        )
    extra_resolvable = resolvable_cell_ids or set()
    for cell_id, decision in role_mapping.items():
        if not isinstance(decision, dict):
            raise ValueError(f"role_mapping[{cell_id}] must be an object")
        role = str(decision.get("role") or "").strip()
        disposition = str(decision.get("disposition") or "").strip()
        if role not in _VALID_ROLES:
            raise ValueError(f"invalid table cell role: {role}")
        if disposition not in DISPOSITIONS:
            raise ValueError(f"invalid table cell disposition: {disposition}")
        current = next(
            row for row in table_rows if str(row.get("cell_id") or "") == cell_id
        )
        current_disposition = str(current.get("disposition") or "")
        # A cell is resolvable when it is pending review in the authority projection,
        # OR it carries an active geometry-conflict overlay (WS1 dual-track degradation
        # exit) — the overlay surfaces such cells as review in the view, and resolving
        # them through this same channel clears the conflict. The writeback format is
        # unchanged; this only widens the set of cells the existing channel accepts.
        if current_disposition != "review" and cell_id not in extra_resolvable:
            raise ValueError(
                f"table review decisions may only resolve pending review cells: {cell_id}"
            )


def _delegate_claim_cell_decision(
    root: Path,
    *,
    cell_id: str,
    requested_disposition: str,
    actor: str,
    reason: str,
    request_idempotency_key: str,
) -> dict[str, Any]:
    """Commit one terminal table-cell decision through current claim authority."""
    from claim_artifacts import load_committed_effective_snapshot_readonly
    from claim_structural_overrides import (
        CELL_REVIEW_STRUCTURAL_REASONS,
        ClaimStructuralOverrideError,
        confirm_structural_exclusion,
        confirm_structural_override,
    )

    projection = load_table_claim_authority_projection(root)
    existing = projection.get(cell_id)
    terminal_class = (
        "promote" if requested_disposition in {"target", "composite"} else "exclude"
    )
    if existing is not None:
        status = str(existing.get("status") or "")
        if (
            terminal_class == "promote" and status == "promoted"
        ) or (
            terminal_class == "exclude" and status == "confirmed_excluded"
        ):
            return {"ok": True, "status": status, "replay": True, "authority": existing}
        if status in {"promoted", "confirmed_excluded"}:
            raise ClaimStructuralOverrideError(
                f"table cell {cell_id} already has terminal claim decision {status}"
            )

    snapshot = load_committed_effective_snapshot_readonly(root, require_v2=False)
    candidates = []
    for claim in snapshot.get("catalog") or []:
        locator = claim.get("locator")
        exclusion = claim.get("exclusion")
        reason_code = (
            str(exclusion.get("reason") or "")
            if isinstance(exclusion, dict)
            else ""
        )
        if (
            isinstance(locator, dict)
            and str(locator.get("table_cell_id") or "") == cell_id
            and claim.get("eligibility") == "excluded"
            and reason_code in CELL_REVIEW_STRUCTURAL_REASONS
        ):
            candidates.append(claim)
    if len(candidates) != 1:
        raise ClaimStructuralOverrideError(
            "base_migration_required: table review cell must bind exactly one current "
            f"claim structural candidate ({cell_id}, found={len(candidates)})"
        )
    claim = candidates[0]
    effective = next((
        row for row in snapshot.get("effective_ledger") or []
        if row.get("claim_id") == claim.get("claim_id")
    ), None)
    if effective is None:
        raise ClaimStructuralOverrideError(
            f"current effective claim row is missing for table cell {cell_id}"
        )
    generation = dict(snapshot.get("generation_meta") or {})
    common = {
        "claim_id": str(claim.get("claim_id") or ""),
        "claim_hash": str(claim.get("claim_hash") or ""),
        "expected_catalog_generation_id": str(
            generation.get("catalog_generation_id") or ""
        ),
        "expected_claim_effective_revision": str(
            effective.get("claim_effective_revision") or ""
        ),
        "prior_structural_reason": str(
            dict(claim.get("exclusion") or {}).get("reason") or ""
        ),
        "actor": actor or "table-review",
        "reason": reason or "Table-level structural review",
        "request_idempotency_key": request_idempotency_key,
    }
    if terminal_class == "exclude":
        return confirm_structural_exclusion(root, **common)
    return confirm_structural_override(
        root,
        **common,
        allow_llm=False,
        route="openai_compatible",
        verifier_max_calls=0,
        verifier_max_total_tokens=0,
    )


def _run_table_recompute(
    root: Path,
    *,
    table_id: str,
    cells: list[dict[str, Any]],
    dispositions: list[dict[str, Any]],
    changed_cell_ids: set[str],
) -> tuple[list[str], str]:
    """表级 recompute + effective fold，持 extraction_operation_lock（Kimi 高危 #3）。

    返回 (recomputed_artifacts, recompute_error)；recompute_error == "" 即成功。抽出来供
    apply_table_review_decision 与启动维护 run_table_review_recompute_recovery 复用——后者扫描
    ready+recompute_error 的表自动重试，使 recompute_error 不再是无重试的死端。
    extraction_operation_lock 撞上主抽取时抛 OmissionConflictError(ValueError)，记为可重试错误。
    """
    recomputed_artifacts = ["table_cell_dispositions.jsonl"]
    recompute_error = ""
    try:
        from omission_actions import extraction_operation_lock
        from table_recompute import recompute_confirmed_table_requirements

        with extraction_operation_lock(root, operation="table-recompute"):
            recomputed_artifacts.extend(recompute_confirmed_table_requirements(
                root,
                table_id=table_id,
                changed_cell_ids=set(changed_cell_ids),
                cells=cells,
                dispositions=dispositions,
            ))
        claim_generation_path = governed_artifact_path(
            root,
            "claim_generation.meta.json",
            category="state",
        )
        if (
            "ai_requirements.jsonl" in recomputed_artifacts
            and claim_generation_path.is_file()
        ):
            from claim_review_actions import fold_effective_ledger

            fold = fold_effective_ledger(
                root,
                actor_trigger="table-review-recompute",
                authority_hook_track="B",
            )
            if fold.get("ok") is not True:
                raise ValueError(
                    "claim effective fold failed after table recompute: "
                    f"{fold.get('reason') or fold.get('error') or 'unknown'}"
                )
    except (OSError, TimeoutError, ValueError) as exc:
        recompute_error = f"{type(exc).__name__}: {exc}"
    return recomputed_artifacts, recompute_error


def run_table_review_recompute_recovery(root: Path) -> dict[str, Any]:
    """启动维护：扫描 ready+recompute_error 的表幂等重试 recompute（Kimi #3 跟进 #1b）。

    recompute_confirmed_table_requirements 按 changed cell 替换需求、是幂等的，故失败留下的
    ready+recompute_error 表可在启动 / claim-maintenance 时整体重试：成功则清除 recompute_error，
    仍失败则保留（更新错误串）等下次。全程持 _table_review_lock。
    """
    root = Path(root).expanduser().resolve()
    states_path = governed_artifact_path(root, TABLE_REVIEW_STATES, category="state")
    if not states_path.is_file():
        return {"ok": True, "attempted": 0, "recovered": 0, "still_failing": 0}
    with _table_review_lock(root):
        states = read_jsonl(states_path)
        pending = [
            (i, row) for i, row in enumerate(states)
            if str(row.get("structure_review_status") or "") == "ready"
            and row.get("recompute_error")
        ]
        if not pending:
            return {"ok": True, "attempted": 0, "recovered": 0, "still_failing": 0}
        cells = _artifact_rows(root, "table_cell_items.jsonl")
        raw_dispositions = _artifact_rows(root, "table_cell_dispositions.jsonl")
        projection = _current_claim_projection(root)
        all_dispositions = project_table_dispositions(raw_dispositions, cells, projection)
        recovered = 0
        still_failing = 0
        changed = False
        for index, row in pending:
            table_id = str(row.get("table_id") or "")
            if not table_id:
                continue
            table_dispositions = [
                disposition for disposition in all_dispositions
                if str(disposition.get("table_id") or "") == table_id
            ]
            changed_cell_ids = {
                str(disposition.get("cell_id") or "")
                for disposition in table_dispositions
                if str(disposition.get("disposition") or "") in {"target", "composite"}
            }
            _artifacts, recompute_error = _run_table_recompute(
                root,
                table_id=table_id,
                cells=cells,
                dispositions=table_dispositions,
                changed_cell_ids=changed_cell_ids,
            )
            if recompute_error:
                still_failing += 1
                if states[index].get("recompute_error") != recompute_error:
                    states[index]["recompute_error"] = recompute_error
                    changed = True
            else:
                recovered += 1
                states[index].pop("recompute_error", None)
                changed = True
        if changed:
            _atomic_write_jsonl(states_path, states)
    return {
        "ok": True,
        "attempted": len(pending),
        "recovered": recovered,
        "still_failing": still_failing,
    }


def apply_table_review_decision(
    out_dir: Path,
    *,
    table_id: str,
    expected_evidence_fingerprint: str,
    role_mapping: dict[str, dict[str, Any]],
    actor: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    """Delegate one table-scoped decision batch to Claim Ledger authority."""
    root = Path(out_dir).expanduser().resolve()
    table_id = str(table_id or "").strip()
    expected = str(expected_evidence_fingerprint or "").strip()
    if not table_id or not expected:
        raise ValueError("table_id and expected_evidence_fingerprint are required")

    with _table_review_lock(root):
        blocks = _artifact_rows(root, "blocks.jsonl")
        cells = _artifact_rows(root, "table_cell_items.jsonl")
        raw_dispositions = _artifact_rows(root, "table_cell_dispositions.jsonl")
        dispositions = project_table_dispositions(
            raw_dispositions,
            cells,
            _current_claim_projection(root),
        )
        table_rows = [
            row for row in dispositions
            if str(row.get("table_id") or "") == table_id
        ]
        if not table_rows:
            raise ValueError(f"table not found: {table_id}")
        # WS1 dual-track: resolve any geometry-conflict overlay to cell_ids so the
        # existing writeback channel can resolve conflict cells too. Pure overlay cells
        # (projected disposition != review) are cleared from the conflict registry
        # instead of routed through claim delegation — the writeback FORMAT (state /
        # events / dispositions) is unchanged; only the set of accepted cells widens.
        conflict_record = load_table_geometry_conflicts(root).get(table_id) or {}
        coord_to_cell_id: dict[tuple[int, int], str] = {
            (int(cell.get("row_index") or 0), int(cell.get("column_index") or 0)):
                str(cell.get("cell_id") or "")
            for cell in cells
            if str(cell.get("table_id") or "") == table_id
        }
        conflict_cell_ids: set[str] = set()
        for entry in conflict_record.get("conflict_cells") or []:
            coord = _normalize_conflict_cell(entry)
            if coord is not None and coord in coord_to_cell_id:
                conflict_cell_ids.add(coord_to_cell_id[coord])
        current = table_evidence_fingerprint(table_id, dispositions)
        if current != expected:
            raise TableReviewConflict(
                "table evidence changed; refresh before confirming structure",
                current_fingerprint=current,
            )
        _validate_role_mapping(
            table_id,
            table_rows,
            role_mapping,
            resolvable_cell_ids=conflict_cell_ids,
        )

        before_mapping = {
            str(row.get("cell_id") or ""): {
                "role": str(row.get("role") or ""),
                "disposition": str(row.get("disposition") or ""),
            }
            for row in table_rows
        }
        claim_results: list[dict[str, Any]] = []
        decision_error: Exception | None = None
        cleared_conflict_cell_ids: set[str] = set()
        for cell_id in sorted(role_mapping):
            requested_disposition = str(
                role_mapping[cell_id].get("disposition") or ""
            )
            request_key = _fingerprint({
                "version": TABLE_REVIEW_DECISION_VERSION,
                "table_id": table_id,
                "cell_id": cell_id,
                "evidence_fingerprint": current,
                "terminal_class": (
                    "promote"
                    if requested_disposition in {"target", "composite"}
                    else "exclude"
                ),
                "actor": actor or "table-review",
            })
            # Pure geometry-conflict overlay cell (not pending review in the authority):
            # resolve by clearing the overlay, not by claim delegation (the cell may have
            # no structural candidate). Same result record shape so the caller sees one
            # uniform writeback channel.
            projected_disposition = str(
                next(
                    (row.get("disposition") for row in table_rows
                     if str(row.get("cell_id") or "") == cell_id),
                    "",
                )
            )
            if (
                cell_id in conflict_cell_ids
                and projected_disposition != "review"
            ):
                cleared_conflict_cell_ids.add(cell_id)
                claim_results.append({
                    "cell_id": cell_id,
                    "requested_disposition": requested_disposition,
                    "request_idempotency_key": request_key,
                    "result": {
                        "ok": True,
                        "status": "geometry_conflict_cleared",
                        "cell_id": cell_id,
                    },
                })
                continue
            try:
                claim_result = _delegate_claim_cell_decision(
                    root,
                    cell_id=cell_id,
                    requested_disposition=requested_disposition,
                    actor=actor or "table-review",
                    reason=str(reason or ""),
                    request_idempotency_key=request_key,
                )
            except Exception as exc:
                decision_error = exc
                break
            claim_results.append({
                "cell_id": cell_id,
                "requested_disposition": requested_disposition,
                "request_idempotency_key": request_key,
                "result": claim_result,
            })
            if cell_id in conflict_cell_ids:
                cleared_conflict_cell_ids.add(cell_id)

        dispositions = project_table_dispositions(
            raw_dispositions,
            cells,
            _current_claim_projection(root),
        )

        selected = [
            row for row in dispositions
            if str(row.get("table_id") or "") == table_id
        ]
        status = (
            "pending"
            if any(str(row.get("disposition") or "") == "review" for row in selected)
            else "ready"
        )
        for row in selected:
            row["structure_review_status"] = status
        validate_disposition_conservation(blocks, cells, dispositions)
        completed_cell_ids = sorted(
            str(row.get("cell_id") or "")
            for row in selected
            if str(row.get("cell_id") or "") in role_mapping
            and str(row.get("disposition") or "") != "review"
        )
        remaining_cell_ids = sorted(
            str(row.get("cell_id") or "")
            for row in selected
            if str(row.get("disposition") or "") == "review"
        )
        if decision_error is not None and not completed_cell_ids:
            raise decision_error
        partial = decision_error is not None

        disposition_path = governed_artifact_path(
            root, "table_cell_dispositions.jsonl"
        )
        _atomic_write_jsonl(disposition_path, dispositions)

        # WS1 dual-track: clear resolved geometry-conflict overlay cells from the
        # registry. A coord leaves the registry when its cell was adjudicated in this
        # batch OR is now terminal in the authority projection. Empty registry → drop
        # the table's record so the panel stops showing it as a degradation exit.
        if conflict_record:
            terminal_now = {
                str(row.get("cell_id") or "")
                for row in selected
                if str(row.get("disposition") or "") in {"target", "composite", "excluded"}
            }
            remaining_coords: list[dict[str, Any]] = []
            for entry in conflict_record.get("conflict_cells") or []:
                coord = _normalize_conflict_cell(entry)
                if coord is None:
                    continue
                cell_id = coord_to_cell_id.get(coord, "")
                if cell_id in cleared_conflict_cell_ids or cell_id in terminal_now:
                    continue
                remaining_coords.append({"row_index": coord[0], "column_index": coord[1]})
            conflict_records = load_table_geometry_conflicts(root)
            if remaining_coords:
                conflict_records[table_id] = {
                    **conflict_record,
                    "conflict_cells": remaining_coords,
                }
            else:
                conflict_records.pop(table_id, None)
            _write_geometry_conflicts(root, conflict_records)

        # 下游传播（recompute + fold）持 _table_review_lock + extraction_operation_lock（Kimi 高危 #3）。
        # recompute 在持久化 state 前跑、失败把 recompute_error 写入 state/events（持久化记录诚实）；
        # 启动维护 run_table_review_recompute_recovery 会扫描 ready+recompute_error 的表自动重试。
        if status == "ready":
            recomputed_artifacts, recompute_error = _run_table_recompute(
                root,
                table_id=table_id,
                cells=cells,
                dispositions=dispositions,
                changed_cell_ids=set(role_mapping),
            )
        else:
            recomputed_artifacts = ["table_cell_dispositions.jsonl"]
            recompute_error = ""

        next_fingerprint = table_evidence_fingerprint(table_id, dispositions)
        recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        after_mapping = {
            str(row.get("cell_id") or ""): {
                "role": str(row.get("role") or ""),
                "disposition": str(row.get("disposition") or ""),
            }
            for row in selected
        }
        state = {
            "schema": TABLE_REVIEW_STATE_SCHEMA,
            "table_id": table_id,
            "structure_review_status": status,
            "evidence_fingerprint_before": current,
            "evidence_fingerprint": next_fingerprint,
            "role_mapping_before": before_mapping,
            "role_mapping_after": after_mapping,
            "actor": actor,
            "reason": str(reason or ""),
            "recorded_at": recorded_at,
            "decision_version": TABLE_REVIEW_DECISION_VERSION,
            "claim_results": claim_results,
            "partial": partial,
            "completed_cell_ids": completed_cell_ids,
            "remaining_cell_ids": remaining_cell_ids,
            "recomputed_artifacts": recomputed_artifacts,
        }
        if recompute_error:
            state["recompute_error"] = recompute_error
        if decision_error is not None:
            state["decision_error"] = {
                "type": type(decision_error).__name__,
                "message": str(decision_error),
                "retryable": isinstance(decision_error, (OSError, TimeoutError)),
            }
        states_path = governed_artifact_path(
            root, TABLE_REVIEW_STATES, category="state"
        )
        states = read_jsonl(states_path)
        states_by_table = {
            str(row.get("table_id") or ""): row for row in states
        }
        states_by_table[table_id] = state
        _atomic_write_jsonl(
            states_path,
            [states_by_table[key] for key in sorted(states_by_table)],
        )
        events_path = governed_artifact_path(
            root, TABLE_REVIEW_EVENTS, category="state"
        )
        events = read_jsonl(events_path)
        events.append({
            "schema": TABLE_REVIEW_EVENT_SCHEMA,
            **state,
        })
        _atomic_write_jsonl(events_path, events)

    return {**state, "claim_results": claim_results}
