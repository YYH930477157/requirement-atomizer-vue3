"""Table-level structural review state and optimistic-concurrency writes."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from io_utils import read_jsonl
from process_file_lock import process_file_lock
from result_package import governed_artifact_path
from table_dispositions import DISPOSITIONS, validate_disposition_conservation


TABLE_REVIEW_VIEW_SCHEMA = "table-review-view/v1"
TABLE_REVIEW_STATE_SCHEMA = "table-review-state/v1"
TABLE_REVIEW_EVENT_SCHEMA = "table-review-event/v1"
TABLE_REVIEW_DECISION_VERSION = "table-review-decision-v1"
TABLE_REVIEW_STATES = "table_review_states.jsonl"
TABLE_REVIEW_EVENTS = "table_review_events.jsonl"
TABLE_REVIEW_LOCK = "table_review_states.lock"

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


def build_table_review_payload(out_dir: Path) -> dict[str, Any]:
    """Build the read-only table review view from governed artifacts."""
    root = Path(out_dir).expanduser().resolve()
    blocks = _artifact_rows(root, "blocks.jsonl")
    cells = _artifact_rows(root, "table_cell_items.jsonl")
    dispositions = _artifact_rows(root, "table_cell_dispositions.jsonl")
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
    for table_id in sorted(set(cells_by_table) | set(dispositions_by_table)):
        table_cells = cells_by_table.get(table_id, [])
        table_dispositions = dispositions_by_table.get(table_id, [])
        disposition_by_cell = {
            str(row.get("cell_id") or ""): row for row in table_dispositions
        }
        rendered_cells = []
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
            rendered_cells.append(rendered)
        counts = Counter(
            str(row.get("disposition") or "") for row in table_dispositions
        )
        block = blocks_by_table.get(table_id, {})
        status = "pending" if counts["review"] else "ready"
        sources = {str(row.get("decision_source") or "") for row in table_dispositions}
        tables.append({
            "table_id": table_id,
            "table_block_id": str(block.get("block_id") or block.get("table_block_id") or ""),
            "title": str(block.get("table_title") or block.get("text") or ""),
            "section_path": list(block.get("section_path") or []),
            "structure_review_status": status,
            "review_mode": (
                "human" if "human" in sources
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
        })
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
) -> None:
    if not isinstance(role_mapping, dict) or not role_mapping:
        raise ValueError("role_mapping must contain at least one cell decision")
    cell_ids = {str(row.get("cell_id") or "") for row in table_rows}
    unknown = sorted(set(role_mapping) - cell_ids)
    if unknown:
        raise ValueError(
            f"role_mapping contains cells outside table {table_id}: {unknown[:5]}"
        )
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
        if str(current.get("disposition") or "") != "review":
            raise ValueError(
                f"table review decisions may only resolve pending review cells: {cell_id}"
            )


def apply_table_review_decision(
    out_dir: Path,
    *,
    table_id: str,
    expected_evidence_fingerprint: str,
    role_mapping: dict[str, dict[str, Any]],
    actor: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    """Apply one table-scoped human role decision under a CAS fingerprint."""
    root = Path(out_dir).expanduser().resolve()
    table_id = str(table_id or "").strip()
    expected = str(expected_evidence_fingerprint or "").strip()
    if not table_id or not expected:
        raise ValueError("table_id and expected_evidence_fingerprint are required")

    with _table_review_lock(root):
        blocks = _artifact_rows(root, "blocks.jsonl")
        cells = _artifact_rows(root, "table_cell_items.jsonl")
        dispositions = _artifact_rows(root, "table_cell_dispositions.jsonl")
        table_rows = [
            row for row in dispositions
            if str(row.get("table_id") or "") == table_id
        ]
        if not table_rows:
            raise ValueError(f"table not found: {table_id}")
        current = table_evidence_fingerprint(table_id, dispositions)
        if current != expected:
            raise TableReviewConflict(
                "table evidence changed; refresh before confirming structure",
                current_fingerprint=current,
            )
        _validate_role_mapping(table_id, table_rows, role_mapping)

        before_mapping = {
            str(row.get("cell_id") or ""): {
                "role": str(row.get("role") or ""),
                "disposition": str(row.get("disposition") or ""),
            }
            for row in table_rows
        }
        for row in dispositions:
            if str(row.get("table_id") or "") != table_id:
                continue
            cell_id = str(row.get("cell_id") or "")
            decision = role_mapping.get(cell_id)
            if decision is not None:
                row["role"] = str(decision["role"])
                row["disposition"] = str(decision["disposition"])
                row["confidence"] = "high"
                row["decision_source"] = "human"
                row["decision_version"] = TABLE_REVIEW_DECISION_VERSION
                evidence = [str(value) for value in (row.get("evidence") or [])]
                row["evidence"] = list(dict.fromkeys([
                    *evidence,
                    "human_table_role_confirmation",
                ]))
            row["structure_review_status"] = "pending"

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

        disposition_path = governed_artifact_path(
            root, "table_cell_dispositions.jsonl"
        )
        _atomic_write_jsonl(disposition_path, dispositions)
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

    recomputed_artifacts = ["table_cell_dispositions.jsonl"]
    recompute_error = ""
    if status == "ready":
        try:
            from table_recompute import recompute_confirmed_table_requirements

            recomputed_artifacts.extend(recompute_confirmed_table_requirements(
                root,
                table_id=table_id,
                changed_cell_ids=set(role_mapping),
                cells=cells,
                dispositions=dispositions,
            ))
        except (OSError, TimeoutError, ValueError) as exc:
            recompute_error = f"{type(exc).__name__}: {exc}"

    return {
        **state,
        "recomputed_artifacts": recomputed_artifacts,
        **({"recompute_error": recompute_error} if recompute_error else {}),
    }
