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


def build_table_review_payload(out_dir: Path) -> dict[str, Any]:
    """Build the read-only table review view from governed artifacts."""
    root = Path(out_dir).expanduser().resolve()
    blocks = _artifact_rows(root, "blocks.jsonl")
    cells = _artifact_rows(root, "table_cell_items.jsonl")
    dispositions = _artifact_rows(root, "table_cell_dispositions.jsonl")
    dispositions = project_table_dispositions(
        dispositions,
        cells,
        _current_claim_projection(root),
    )
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
        claim_results: list[dict[str, Any]] = []
        decision_error: Exception | None = None
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

        # 下游传播（recompute + fold）移入 _table_review_lock 临界区，并持
        # extraction_operation_lock 保护 ai_requirements.jsonl 读-改-写（Kimi 高危 #3）：
        # 原在锁外执行，ThreadingHTTPServer 下跨表并发会丢更新；且 state 先落 ready、
        # recompute 失败只进 HTTP 响应、无重试路径。现 recompute 在持久化 state 前跑，
        # 失败把 recompute_error 写入 state/events（持久化记录诚实），下次 ready 迁移
        # 或 claim-maintenance 自然重试。extraction_operation_lock 撞上主抽取时抛
        # OmissionConflictError(ValueError) → 记为可重试 recompute_error，不阻塞裁决本身。
        recomputed_artifacts = ["table_cell_dispositions.jsonl"]
        recompute_error = ""
        if status == "ready":
            try:
                from omission_actions import extraction_operation_lock
                from table_recompute import recompute_confirmed_table_requirements

                with extraction_operation_lock(root, operation="table-recompute"):
                    recomputed_artifacts.extend(recompute_confirmed_table_requirements(
                        root,
                        table_id=table_id,
                        changed_cell_ids=set(role_mapping),
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
