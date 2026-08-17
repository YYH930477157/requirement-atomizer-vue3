from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from claim_artifacts import (
    CLAIM_EFFECTIVE_ARTIFACT_PROTOCOL_VERSION,
    CLAIM_EFFECTIVE_HEALTH,
    CLAIM_EFFECTIVE_PUBLICATION_JOURNAL,
    CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
    CLAIM_REVIEW_EVENTS,
    LEGACY_CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
    ClaimArtifactError,
    ClaimBaseMigrationRequired,
    _REPLACE_ATTEMPTS,
    _REPLACE_RETRY_DELAY_S,
    _atomic_write_bytes,
    _validate_schema,
    canonical_target_fingerprint,
    canonical_json_value_bytes,
    claim_artifact_path,
    claim_base_generation_id,
    claim_publication_lock,
    digest_hex,
    effective_versions_are_current,
    hash_json,
    load_committed_claim_base,
    load_committed_effective_refold_seed,
    load_committed_shadow,
    publish_effective_snapshot,
    semantic_negative_id,
    sha256_bytes,
)
from claim_ledger import (
    CLAIM_EFFECTIVE_LEDGER_SCHEMA,
    CLAIM_EFFECTIVE_REDUCER_VERSION,
    CLAIM_QUEUE_PROPOSAL_SCHEMA,
    CLAIM_QUEUE_VERSION,
    CLAIM_REVIEW_BRIDGE_VERSION,
    CLAIM_REVIEW_EVENT_SCHEMA,
    LEGACY_CLAIM_REVIEW_EVENT_SCHEMA,
    SEMANTIC_NEGATIVE_CHECKS,
    a_track_effective_authority,
    atomic_requirement_id,
    b_track_effective_authority,
    effective_review_adapter_versions,
    evidence_is_current,
    reduce_claim,
    semantic_validation_fingerprint,
)
from review_state import CLAIM_AUTHORITY_WRITE_PROTOCOL_VERSION


LOGGER = logging.getLogger("requirement_atomizer")
# M9 第 5 刀：事件日志 journal 簇逐字搬到 claim_events_journal，原名重导出——调用面
# （含 claim_artifacts 对 _scan_event_log_unlocked 的消费）零变化；7 个 patch 目标
# 全部留守本模块。
from claim_events_journal import (  # noqa: E402,F401
    _EMPTY_SHA256,
    _EVENT_QUARANTINE_PREFIX,
    _event_hash_domain,
    _event_id,
    _event_schema_file,
    _event_without_hash,
    _quarantine_suffix,
    _repair_event_suffix,
    _scan_event_log_unlocked,
    ClaimReviewActionError,
    EventLogSnapshot,
)
_B_TARGET_STORE = "ai_requirements.jsonl"
_B_REVIEW_STORE = "ai_review_states.jsonl"
_A_TARGET_STORE = "atomic_requirements.jsonl"
_A_REVIEW_STORE = "review_states.jsonl"
_HEALTH_SCHEMA = "claim-effective-health/v1"
_RESOLUTION_EVENT_KINDS = frozenset({
    "target_invalidated",
    "target_reactivated",
    "expert_adjudication",
    "audit_conflict",
})
_EXPERT_EXCLUSION_REASONS = frozenset({
    "scope_statement",
    "definition",
    "informative",
    "example",
    "instrument_only",
})


class ClaimProjectionCasMismatch(ClaimReviewActionError):
    """A bridge event was built from an obsolete base/effective snapshot."""


class ClaimAdjudicationCasMismatch(ClaimReviewActionError):
    """A claim fact was built from an obsolete effective claim revision."""


@dataclass(frozen=True)
class TargetLink:
    target_kind: str
    target_requirement_id: str
    target_fingerprint: str
    claim_ids: tuple[str, ...]
    baseline_eligibility: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _validate_projection_cas_drafts(
    drafts: Iterable[dict[str, Any]],
    *,
    existing_rows: list[dict[str, Any]],
    existing_idempotency_keys: frozenset[str],
    base_by_claim: dict[str, dict[str, Any]],
    effective_by_claim: dict[str, dict[str, Any]],
) -> None:
    """Validate only new bridge projections against the locked snapshot.

    The effective revision is an append-time precondition, not a replay-time
    predicate: an accepted historical event necessarily predates the current
    effective revision after a successful fold.
    """
    for draft in drafts:
        idempotency_key = str(draft.get("idempotency_key") or "")
        if not idempotency_key or idempotency_key in existing_idempotency_keys:
            continue
        event_kind = str(draft.get("event_kind") or "")
        claim_id = str(draft.get("claim_id") or "")
        base_row = base_by_claim.get(claim_id)
        if base_row is None:
            raise ClaimProjectionCasMismatch(
                f"projection claim is absent from committed base: {claim_id}"
            )
        expected_base_hash = hash_json("claim-base-row/v1", base_row)
        if draft.get("expected_base_claim_row_hash") != expected_base_hash:
            raise ClaimProjectionCasMismatch(
                f"projection base hash changed for claim {claim_id}"
            )
        effective = effective_by_claim.get(claim_id)
        has_v2_effective = bool(
            effective is not None
            and effective.get("schema") == CLAIM_EFFECTIVE_LEDGER_SCHEMA
            and isinstance(effective.get("claim_effective_revision"), str)
        )
        if event_kind in {
            "expert_adjudication",
            "audit_conflict",
            "structural_falsification",
        }:
            if not has_v2_effective:
                raise ClaimAdjudicationCasMismatch(
                    f"claim has no current effective revision: {claim_id}"
                )
            expected_revision = draft.get("expected_claim_effective_revision")
            if expected_revision != effective.get("claim_effective_revision"):
                raise ClaimAdjudicationCasMismatch(
                    f"claim effective revision changed for claim {claim_id}"
                )
            if event_kind == "expert_adjudication" and any(
                row.get("schema") == CLAIM_REVIEW_EVENT_SCHEMA
                and row.get("event_kind") == "expert_adjudication"
                and row.get("claim_id") == claim_id
                and row.get("claim_hash") == draft.get("claim_hash")
                and row.get("expected_claim_effective_revision")
                == expected_revision
                for row in existing_rows
            ):
                raise ClaimAdjudicationCasMismatch(
                    f"claim effective revision was already adjudicated: {claim_id}"
                )
            continue
        mode = str(draft.get("projection_mode") or "")
        if mode == "cas_effective":
            if not has_v2_effective:
                raise ClaimProjectionCasMismatch(
                    f"projection lost effective row for claim {claim_id}"
                )
            if draft.get("expected_claim_effective_revision") != effective.get(
                "claim_effective_revision"
            ):
                raise ClaimProjectionCasMismatch(
                    f"projection effective revision changed for claim {claim_id}"
                )
        elif mode == "bootstrap_base":
            if draft.get("expected_claim_effective_revision") is not None:
                raise ClaimProjectionCasMismatch(
                    f"bootstrap projection carries an effective revision for {claim_id}"
                )
            if has_v2_effective:
                raise ClaimProjectionCasMismatch(
                    f"bootstrap projection is stale for claim {claim_id}"
                )
        else:
            raise ClaimProjectionCasMismatch(
                f"unsupported projection mode for claim {claim_id}: {mode!r}"
            )


def _read_claim_review_events_readonly(root: Path) -> EventLogSnapshot:
    """Read a stable event-log snapshot without touching publication locks."""
    path = claim_artifact_path(root, CLAIM_REVIEW_EVENTS)
    before = path.read_bytes() if path.is_file() else None
    snapshot = _scan_event_log_unlocked(root, repair=False, raw=before)
    after = path.read_bytes() if path.is_file() else None
    if after != before:
        raise ClaimReviewActionError("claim review event log changed during read-only read")
    return snapshot


def read_claim_review_events(
    out_dir: Path | str,
    *,
    repair: bool = False,
    readonly: bool = False,
) -> EventLogSnapshot:
    root = Path(out_dir).expanduser().resolve()
    if readonly:
        if repair:
            raise ValueError("read-only claim event reads cannot repair")
        return _read_claim_review_events_readonly(root)
    with claim_publication_lock(root):
        return _scan_event_log_unlocked(root, repair=repair)


def append_claim_review_events(
    out_dir: Path | str,
    drafts: Iterable[dict[str, Any]],
    *,
    base_by_claim: dict[str, dict[str, Any]] | None = None,
    effective_by_claim: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Append canonical bridge events and absorb already committed idempotency keys."""
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    draft_rows = [dict(raw_draft) for raw_draft in drafts]
    if (base_by_claim is None) != (effective_by_claim is None):
        raise ValueError("projection CAS requires both base and effective mappings")
    with claim_publication_lock(root):
        snapshot = _scan_event_log_unlocked(root, repair=True)
        if base_by_claim is not None and effective_by_claim is not None:
            _validate_projection_cas_drafts(
                draft_rows,
                existing_rows=snapshot.rows,
                existing_idempotency_keys=snapshot.idempotency_keys,
                base_by_claim=base_by_claim,
                effective_by_claim=effective_by_claim,
            )
        idempotency_keys = set(snapshot.idempotency_keys)
        rows = list(snapshot.rows)
        appended: list[dict[str, Any]] = []
        handle = None
        try:
            for draft in draft_rows:
                forbidden = {"event_seq", "event_id", "prev_event_hash", "event_hash"}
                if forbidden.intersection(draft):
                    raise ClaimReviewActionError("claim review event draft contains chain fields")
                draft.setdefault("schema", CLAIM_REVIEW_EVENT_SCHEMA)
                draft.setdefault("recorded_at", _utc_now())
                idempotency_key = str(draft.get("idempotency_key") or "")
                if not idempotency_key:
                    raise ClaimReviewActionError("claim review event idempotency key is required")
                if idempotency_key in idempotency_keys:
                    continue
                event_seq = len(rows) + 1
                event = {
                    **draft,
                    "event_seq": event_seq,
                    "event_id": _event_id(event_seq, idempotency_key),
                    "prev_event_hash": (
                        str(rows[-1]["event_hash"]) if rows else _EMPTY_SHA256
                    ),
                }
                event["event_hash"] = hash_json(
                    _event_hash_domain(event),
                    _event_without_hash(event),
                )
                _validate_schema(
                    event,
                    _event_schema_file(event),
                    label="claim review event",
                )
                if handle is None:
                    path = claim_artifact_path(root, CLAIM_REVIEW_EVENTS)
                    # Windows AV/索引器瞬态占用：open 重试预算耗尽后如实抛出（响亮失败），
                    # 与 claim_artifacts 的共享文件纪律同款。
                    for attempt in range(_REPLACE_ATTEMPTS):
                        try:
                            handle = path.open("ab")
                            break
                        except PermissionError:
                            if attempt + 1 >= _REPLACE_ATTEMPTS:
                                raise
                            time.sleep(_REPLACE_RETRY_DELAY_S * (attempt + 1))
                handle.write(canonical_json_value_bytes(event) + b"\n")
                rows.append(event)
                appended.append(event)
                idempotency_keys.add(idempotency_key)
            if handle is not None:
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            if handle is not None:
                handle.close()
        committed = _scan_event_log_unlocked(root, repair=False)
        return {
            "appended": appended,
            "appended_count": len(appended),
            "event_prefix_sha256": committed.event_prefix_sha256,
            "last_event_seq": committed.last_event_seq,
            "last_event_hash": committed.last_event_hash,
            "torn_tail_recovered": snapshot.torn_tail_recovered,
            "quarantine_file": snapshot.quarantine_file,
        }


def _parse_jsonl_objects(raw: bytes, *, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(raw.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ClaimReviewActionError(
                f"invalid {label} row {line_number}"
            ) from exc
        if not isinstance(row, dict):
            raise ClaimReviewActionError(f"invalid {label} row {line_number}")
        rows.append(row)
    return rows


def _read_optional_authority_bytes(
    path: Path,
    *,
    label: str,
) -> tuple[bool, bytes]:
    try:
        return True, path.read_bytes()
    except FileNotFoundError:
        return False, b""
    except OSError as exc:
        raise ClaimReviewActionError(
            f"{label} is unavailable for a consistent read"
        ) from exc


def _confirm_readonly_target_snapshot(
    path: Path,
    *,
    label: str,
    expected_present: bool,
    expected_bytes: bytes,
) -> None:
    actual_present, actual_bytes = _read_optional_authority_bytes(
        path,
        label=label,
    )
    if (
        actual_present != expected_present
        or actual_bytes != expected_bytes
    ):
        raise ClaimReviewActionError(
            f"{label} changed during read-only authority read"
        )


def _target_publication_revision(
    source_store: str,
    source_file_sha256: str,
    *,
    source_present: bool,
) -> str:
    return hash_json(
        "claim-target-publication-revision/v1",
        {
            "source_store": source_store,
            "source_present": source_present,
            "source_file_sha256": source_file_sha256,
        },
    )


def _resolve_b_target_store(root: Path) -> str:
    """§3.4：B 轨 fold/权威读取的 target store。

    权威顺序（复审 2026-08-15 P1）：**已提交 generation meta 记录的 store 优先**——
    旧 ai_requirements.jsonl 残留时文件在场启发式会劫持当前 functional generation，
    让 fold/队列走向旧原子产物。无已提交 meta 时才按文件在场（原子优先，直抽次之）。
    """
    try:
        from claim_artifacts import CLAIM_GENERATION_META, _read_json

        meta = _read_json(
            claim_artifact_path(root, CLAIM_GENERATION_META),
            label="claim generation meta",
        )
        committed = str(meta.get("requirements_store") or "").strip()
    except Exception:  # noqa: BLE001 — 无已提交 meta（未发布过 claim）→ 文件启发式
        committed = ""
    if committed in ("ai_requirements.jsonl", "functional_requirements.json"):
        return committed
    if (root / _B_TARGET_STORE).is_file():
        return _B_TARGET_STORE
    functional_store = "functional_requirements.json"
    if (root / functional_store).is_file():
        return functional_store
    return _B_TARGET_STORE


def _parse_b_target_rows(
    target_bytes: bytes, *, present: bool, store: str,
) -> list[dict[str, Any]]:
    """按 store 解析 B 轨 target 行：JSONL（原子）/ JSON items（直抽）。"""
    if not present:
        return []
    if store == "functional_requirements.json":
        try:
            payload = json.loads(target_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ClaimReviewActionError(
                "functional requirements store is not valid JSON"
            ) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise ClaimReviewActionError(
                "functional requirements store has no items list"
            )
        return [row for row in payload["items"] if isinstance(row, dict)]
    return _parse_jsonl_objects(target_bytes, label="AI requirements")


def _load_b_track_authority(
    root: Path,
    *,
    readonly: bool = False,
) -> dict[str, Any]:
    from ai_review_actions import (
        read_ai_review_authority_snapshot,
        read_ai_review_authority_snapshot_readonly,
    )

    target_store = _resolve_b_target_store(root)
    target_path = root / target_store
    target_present, target_bytes = _read_optional_authority_bytes(
        target_path,
        label="B-track requirements",
    )
    requirements = _parse_b_target_rows(
        target_bytes, present=target_present, store=target_store,
    )
    try:
        review_snapshot = (
            read_ai_review_authority_snapshot_readonly(root)
            if readonly
            else read_ai_review_authority_snapshot(root)
        )
    except (OSError, ValueError) as exc:
        raise ClaimReviewActionError(
            "AI review authority is unavailable for a consistent read"
        ) from exc
    if readonly:
        _confirm_readonly_target_snapshot(
            target_path,
            label="AI requirements",
            expected_present=target_present,
            expected_bytes=target_bytes,
        )
    authority = b_track_effective_authority(
        requirements,
        dict(review_snapshot["states"]),
    )
    target_file_sha256 = sha256_bytes(target_bytes)
    return {
        **authority,
        "requirements": requirements,
        "target_source_store": target_store,
        "review_source_store": _B_REVIEW_STORE,
        "target_file_sha256": target_file_sha256,
        "target_publication_revision": _target_publication_revision(
            target_store,
            target_file_sha256,
            source_present=target_present,
        ),
        "review_snapshot": review_snapshot,
    }


def _load_a_track_authority(
    root: Path,
    *,
    readonly: bool = False,
) -> dict[str, Any]:
    from review_state import (
        read_review_authority_snapshot,
        read_review_authority_snapshot_readonly,
    )

    target_path = root / _A_TARGET_STORE
    target_present, target_bytes = _read_optional_authority_bytes(
        target_path,
        label="atomic requirements",
    )
    requirements = (
        _parse_jsonl_objects(target_bytes, label="atomic requirements")
        if target_present
        else []
    )
    try:
        review_snapshot = (
            read_review_authority_snapshot_readonly(root)
            if readonly
            else read_review_authority_snapshot(root)
        )
    except (OSError, ValueError) as exc:
        raise ClaimReviewActionError(
            "review authority is unavailable for a consistent read"
        ) from exc
    if readonly:
        _confirm_readonly_target_snapshot(
            target_path,
            label="atomic requirements",
            expected_present=target_present,
            expected_bytes=target_bytes,
        )
    authority = a_track_effective_authority(
        requirements,
        list(review_snapshot["states"]),
    )
    target_file_sha256 = sha256_bytes(target_bytes)
    return {
        **authority,
        "requirements": requirements,
        "target_source_store": _A_TARGET_STORE,
        "review_source_store": _A_REVIEW_STORE,
        "target_file_sha256": target_file_sha256,
        "target_publication_revision": _target_publication_revision(
            _A_TARGET_STORE,
            target_file_sha256,
            source_present=target_present,
        ),
        "review_snapshot": review_snapshot,
    }


def _load_declared_authority(
    root: Path,
    generation: dict[str, Any],
    *,
    readonly: bool = False,
) -> dict[str, Any]:
    declared = (
        str(generation.get("delivery_track") or ""),
        str(generation.get("target_kind") or ""),
    )
    if declared == ("B", "ai_requirement"):
        return _load_b_track_authority(root, readonly=readonly)
    if declared == ("A", "atomic_requirement"):
        return _load_a_track_authority(root, readonly=readonly)
    raise ClaimReviewActionError(
        "unsupported claim authority adapter declaration: "
        f"delivery_track={declared[0]!r}, target_kind={declared[1]!r}"
    )


def _authority_cas_identity(authority: dict[str, Any]) -> dict[str, Any]:
    review_snapshot = dict(authority["review_snapshot"])
    return {
        "target_file_sha256": authority["target_file_sha256"],
        "target_publication_revision": authority["target_publication_revision"],
        "target_set_hash": authority["target_set_hash"],
        "requirement_review_state_hash": authority[
            "requirement_review_state_hash"
        ],
        "review_authority_file_sha256": review_snapshot[
            "authority_file_sha256"
        ],
    }


def _target_links(base: dict[str, Any]) -> dict[tuple[str, str, str], TargetLink]:
    claims_by_key: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    eligibility_by_key: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for group in base.get("groups") or []:
        claim_id = str(group.get("claim_id") or "")
        for edge in group.get("edges") or []:
            key = (
                str(edge.get("target_kind") or ""),
                str(edge.get("target_requirement_id") or ""),
                canonical_target_fingerprint(edge.get("target_fingerprint")),
            )
            claims_by_key[key].add(claim_id)
            eligibility_by_key[key].add(
                str(edge.get("target_review_eligibility") or "unknown")
            )
    links: dict[tuple[str, str, str], TargetLink] = {}
    for key, claim_ids in claims_by_key.items():
        values = eligibility_by_key[key]
        baseline = next(iter(values)) if len(values) == 1 else "unknown"
        links[key] = TargetLink(
            target_kind=key[0],
            target_requirement_id=key[1],
            target_fingerprint=key[2],
            claim_ids=tuple(sorted(claim_ids)),
            baseline_eligibility=baseline,
        )
    return links


def _records_by_target_id(
    authority: dict[str, Any],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    result: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in authority.get("records") or []:
        result[(
            str(record.get("target_kind") or ""),
            str(record.get("target_requirement_id") or ""),
        )].append(record)
    return result


def _missing_review_revision(link: TargetLink) -> str:
    return hash_json(
        "claim-target-review-missing/v1",
        {
            "target_kind": link.target_kind,
            "target_requirement_id": link.target_requirement_id,
            "target_fingerprint": link.target_fingerprint,
        },
    )


def _current_target_fact(
    link: TargetLink,
    records_by_id: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    candidates = records_by_id.get(
        (link.target_kind, link.target_requirement_id),
        [],
    )
    exact = [
        row for row in candidates
        if canonical_target_fingerprint(row.get("target_fingerprint"))
        == link.target_fingerprint
    ]
    if len(exact) == 1:
        record = exact[0]
        review = dict(record.get("review") or {})
        return {
            "eligibility": str(review.get("eligibility") or "unknown"),
            "reason": str(review.get("reason") or "review_unknown"),
            "observed_target_fingerprint": link.target_fingerprint,
            "target_review_revision": str(
                review.get("target_review_revision")
                or _missing_review_revision(link)
            ),
            "record": record,
        }
    if len(exact) > 1:
        review = dict(exact[0].get("review") or {})
        return {
            "eligibility": "unknown",
            "reason": "duplicate_target_requirement_id",
            "observed_target_fingerprint": link.target_fingerprint,
            "target_review_revision": str(
                review.get("target_review_revision")
                or _missing_review_revision(link)
            ),
            "record": exact[0],
        }
    if candidates:
        observed = canonical_target_fingerprint(
            candidates[0].get("target_fingerprint")
        )
        review = dict(candidates[0].get("review") or {})
        return {
            "eligibility": "unknown",
            "reason": "target_fingerprint_mismatch",
            "observed_target_fingerprint": observed,
            "target_review_revision": str(
                review.get("target_review_revision")
                or _missing_review_revision(link)
            ),
            "record": candidates[0],
        }
    return {
        "eligibility": "unknown",
        "reason": "target_missing",
        "observed_target_fingerprint": None,
        "target_review_revision": _missing_review_revision(link),
        "record": None,
    }


def _projection_cas(
    claim_id: str,
    base_by_claim: dict[str, dict[str, Any]],
    effective_by_claim: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    base_row = base_by_claim[claim_id]
    effective = effective_by_claim.get(claim_id)
    if (
        effective is not None
        and effective.get("schema") == CLAIM_EFFECTIVE_LEDGER_SCHEMA
        and isinstance(effective.get("claim_effective_revision"), str)
    ):
        return {
            "projection_mode": "cas_effective",
            "expected_base_claim_row_hash": hash_json(
                "claim-base-row/v1",
                base_row,
            ),
            "expected_claim_effective_revision": effective[
                "claim_effective_revision"
            ],
        }
    return {
        "projection_mode": "bootstrap_base",
        "expected_base_claim_row_hash": hash_json("claim-base-row/v1", base_row),
        "expected_claim_effective_revision": None,
    }


def _event_drafts_for_transition(
    *,
    link: TargetLink,
    before: str,
    after: str,
    reason: str,
    trigger_kind: str,
    source_store: str,
    source_event_revision: str,
    target_review_revision: str,
    observed_target_fingerprint: str | None,
    base: dict[str, Any],
    base_by_claim: dict[str, dict[str, Any]],
    effective_by_claim: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    generation = dict(base["generation_meta"])
    event_kind = "target_reactivated" if after == "active" else "target_invalidated"
    drafts: list[dict[str, Any]] = []
    for claim_id in link.claim_ids:
        base_row = base_by_claim[claim_id]
        idempotency_key = hash_json(
            "claim-review-event-idempotency/v1",
            {
                "document_generation_id": generation["document_generation_id"],
                "catalog_generation_id": generation["catalog_generation_id"],
                "claim_hash": base_row["claim_hash"],
                "source_store": source_store,
                "source_event_revision": source_event_revision,
                "target_kind": link.target_kind,
                "target_requirement_id": link.target_requirement_id,
                "target_fingerprint": link.target_fingerprint,
                "observed_target_fingerprint": observed_target_fingerprint,
                "claim_id": claim_id,
                "event_kind": event_kind,
                "bridge_version": CLAIM_REVIEW_BRIDGE_VERSION,
            },
        )
        drafts.append({
            "schema": CLAIM_REVIEW_EVENT_SCHEMA,
            "claim_id": claim_id,
            "claim_hash": base_row["claim_hash"],
            "document_generation_id": generation["document_generation_id"],
            "catalog_generation_id": generation["catalog_generation_id"],
            "event_kind": event_kind,
            "eligibility_before": before,
            "eligibility_after": after,
            "actor": "system:claim-review-bridge",
            "reason": reason or "review_state_changed",
            "trigger_kind": trigger_kind,
            "source_store": source_store,
            "source_event_revision": source_event_revision,
            "target_review_revision": target_review_revision,
            "target_kind": link.target_kind,
            "target_requirement_id": link.target_requirement_id,
            "target_fingerprint": link.target_fingerprint,
            "observed_target_fingerprint": observed_target_fingerprint,
            "linked_claim_ids": list(link.claim_ids),
            "idempotency_key": idempotency_key,
            **_projection_cas(
                claim_id,
                base_by_claim,
                effective_by_claim,
            ),
            "bridge_version": CLAIM_REVIEW_BRIDGE_VERSION,
            "route": "deterministic",
        })
    return drafts


def _historical_b_track_review_drafts(
    base: dict[str, Any],
    authority: dict[str, Any],
    links: dict[tuple[str, str, str], TargetLink],
    base_by_claim: dict[str, dict[str, Any]],
    effective_by_claim: dict[str, dict[str, Any]],
    workload: dict[str, int],
) -> list[dict[str, Any]]:
    review_snapshot = dict(authority["review_snapshot"])
    links_by_id: dict[
        tuple[str, str],
        list[tuple[tuple[str, str, str], TargetLink]],
    ] = defaultdict(list)
    for key, link in links.items():
        if link.target_kind != "ai_requirement":
            continue
        links_by_id[(link.target_kind, link.target_requirement_id)].append(
            (key, link)
        )
        workload["link_index_insert_count"] += 1
    records_by_identity: dict[
        tuple[str, str, str],
        list[dict[str, Any]],
    ] = defaultdict(list)
    for record in authority.get("records") or []:
        identity = (
            str(record.get("target_kind") or ""),
            str(record.get("target_requirement_id") or ""),
            canonical_target_fingerprint(record.get("target_fingerprint")),
        )
        records_by_identity[identity].append(record)
    timeline = {key: "active" for key in links}
    drafts: list[dict[str, Any]] = []
    for source_record in review_snapshot.get("ordered_records") or []:
        workload["history_record_count"] += 1
        state = dict(source_record.get("state") or {})
        target_id = str(state.get("ai_req_id") or "")
        matching_links = links_by_id.get(("ai_requirement", target_id), [])
        for key, link in matching_links:
            workload["link_candidate_check_count"] += 1
            exact_records = records_by_identity.get(key, [])
            if len(exact_records) != 1:
                continue
            record = b_track_effective_authority(
                [dict(exact_records[0]["requirement"])],
                {target_id: state},
            )["records"][0]
            review = dict(record["review"])
            before = timeline[key]
            after = str(review.get("eligibility") or "unknown")
            timeline[key] = after
            if before == after:
                continue
            drafts.extend(_event_drafts_for_transition(
                link=link,
                before=before,
                after=after,
                reason=str(review.get("reason") or "review_state_changed"),
                trigger_kind="review_authority",
                source_store=_B_REVIEW_STORE,
                source_event_revision=str(source_record["source_event_revision"]),
                target_review_revision=str(review["target_review_revision"]),
                observed_target_fingerprint=link.target_fingerprint,
                base=base,
                base_by_claim=base_by_claim,
                effective_by_claim=effective_by_claim,
            ))
    return drafts


def _historical_a_track_review_drafts(
    base: dict[str, Any],
    authority: dict[str, Any],
    links: dict[tuple[str, str, str], TargetLink],
    base_by_claim: dict[str, dict[str, Any]],
    effective_by_claim: dict[str, dict[str, Any]],
    workload: dict[str, int],
) -> list[dict[str, Any]]:
    review_snapshot = dict(authority["review_snapshot"])
    links_by_id: dict[
        tuple[str, str],
        list[tuple[tuple[str, str, str], TargetLink]],
    ] = defaultdict(list)
    for key, link in links.items():
        if link.target_kind != "atomic_requirement":
            continue
        links_by_id[(link.target_kind, link.target_requirement_id)].append(
            (key, link)
        )
        workload["link_index_insert_count"] += 1
    records_by_identity: dict[
        tuple[str, str, str],
        list[dict[str, Any]],
    ] = defaultdict(list)
    for record in authority.get("records") or []:
        identity = (
            str(record.get("target_kind") or ""),
            str(record.get("target_requirement_id") or ""),
            canonical_target_fingerprint(record.get("target_fingerprint")),
        )
        records_by_identity[identity].append(record)

    timeline = {key: "active" for key in links}
    drafts: list[dict[str, Any]] = []
    for source_record in review_snapshot.get("ordered_records") or []:
        workload["history_record_count"] += 1
        identity_keys = {
            str(value) for value in (source_record.get("identity_keys") or [])
            if str(value)
        }
        history_event = source_record.get("history_event")
        state = source_record.get("state")
        if not isinstance(history_event, dict) or not isinstance(state, dict):
            continue
        after_status = str(history_event.get("to_status") or "unknown")
        matching_links: dict[
            tuple[str, str, str],
            TargetLink,
        ] = {}
        for identity in identity_keys:
            for key, link in links_by_id.get(
                ("atomic_requirement", identity),
                [],
            ):
                matching_links[key] = link
        for key, link in matching_links.items():
            workload["link_candidate_check_count"] += 1
            exact_records = records_by_identity.get(key, [])
            if len(exact_records) != 1:
                continue
            event_state = dict(state)
            event_state["status"] = after_status
            record = a_track_effective_authority(
                [dict(exact_records[0]["requirement"])],
                [event_state],
            )["records"][0]
            review = dict(record["review"])
            before = timeline[key]
            after = str(review.get("eligibility") or "unknown")
            timeline[key] = after
            if before == after:
                continue
            drafts.extend(_event_drafts_for_transition(
                link=link,
                before=before,
                after=after,
                reason=str(review.get("reason") or "review_state_changed"),
                trigger_kind="review_authority",
                source_store=_A_REVIEW_STORE,
                source_event_revision=str(
                    source_record["source_event_revision"]
                ),
                target_review_revision=str(review["target_review_revision"]),
                observed_target_fingerprint=link.target_fingerprint,
                base=base,
                base_by_claim=base_by_claim,
                effective_by_claim=effective_by_claim,
            ))
    return drafts


def _historical_review_drafts(
    base: dict[str, Any],
    authority: dict[str, Any],
    links: dict[tuple[str, str, str], TargetLink],
    base_by_claim: dict[str, dict[str, Any]],
    effective_by_claim: dict[str, dict[str, Any]],
    workload: dict[str, int],
) -> list[dict[str, Any]]:
    target_kind = str(authority.get("target_kind") or "")
    if target_kind == "ai_requirement":
        return _historical_b_track_review_drafts(
            base,
            authority,
            links,
            base_by_claim,
            effective_by_claim,
            workload,
        )
    if target_kind == "atomic_requirement":
        return _historical_a_track_review_drafts(
            base,
            authority,
            links,
            base_by_claim,
            effective_by_claim,
            workload,
        )
    raise ClaimReviewActionError(
        f"unsupported historical review adapter: {target_kind!r}"
    )


def _current_transition_drafts(
    base: dict[str, Any],
    authority: dict[str, Any],
    links: dict[tuple[str, str, str], TargetLink],
    event_rows: list[dict[str, Any]],
    base_by_claim: dict[str, dict[str, Any]],
    effective_by_claim: dict[str, dict[str, Any]],
    workload: dict[str, int],
) -> list[dict[str, Any]]:
    by_id = _records_by_target_id(authority)
    review_snapshot = dict(authority["review_snapshot"])
    last_event_by_link: dict[tuple[str, str, str], dict[str, Any]] = {}
    last_target_event_by_link: dict[tuple[str, str, str], dict[str, Any]] = {}
    for event in event_rows:
        key = (
            str(event.get("target_kind") or ""),
            str(event.get("target_requirement_id") or ""),
            str(event.get("target_fingerprint") or ""),
        )
        last_event_by_link[key] = event
        if event.get("trigger_kind") == "target_set":
            last_target_event_by_link[key] = event
        workload["event_index_insert_count"] += 1
    drafts: list[dict[str, Any]] = []
    for key, link in links.items():
        fact = _current_target_fact(link, by_id)
        previous = last_event_by_link.get(key)
        previous_target_event = last_target_event_by_link.get(key)
        before = (
            str(previous.get("eligibility_after") or "unknown")
            if previous is not None
            else "active"
        )
        after = str(fact["eligibility"])
        prior_hash = (
            str(previous.get("event_hash")) if previous is not None else _EMPTY_SHA256
        )
        previous_observed = (
            previous_target_event.get("observed_target_fingerprint")
            if previous_target_event is not None
            else link.target_fingerprint
        )
        target_changed = (
            previous_observed != fact["observed_target_fingerprint"]
            or (
                fact["reason"] == "duplicate_target_requirement_id"
                and previous_target_event is None
            )
            or (
                before != after
                and fact["reason"] in {
                    "target_missing",
                    "target_fingerprint_mismatch",
                    "duplicate_target_requirement_id",
                }
            )
        )
        if before == after and not target_changed:
            continue
        if target_changed:
            source_store = str(authority["target_source_store"])
            trigger_kind = "target_set"
            source_event_revision = hash_json(
                "claim-target-source-event-revision/v2",
                {
                    "source_store": source_store,
                    "target_publication_revision": authority[
                        "target_publication_revision"
                    ],
                    "target_set_hash": authority["target_set_hash"],
                    "target_kind": link.target_kind,
                    "target_requirement_id": link.target_requirement_id,
                    "target_fingerprint": link.target_fingerprint,
                    "observed_target_fingerprint": fact[
                        "observed_target_fingerprint"
                    ],
                    "previous_transition_event_hash": prior_hash,
                },
            )
        else:
            source_store = str(authority["review_source_store"])
            trigger_kind = "review_authority"
            latest_record = review_snapshot.get("source_records", {}).get(
                link.target_requirement_id
            )
            if (
                authority.get("target_kind") == "atomic_requirement"
                and not isinstance(latest_record, dict)
            ):
                # A-track review authority is the embedded history. A legacy
                # current state without a source history event still affects
                # the fold, but cannot be projected with a fabricated event.
                continue
            source_event_revision = (
                str(latest_record["source_event_revision"])
                if isinstance(latest_record, dict)
                else hash_json(
                    "claim-review-authority-observation/v1",
                    {
                        "source_store": source_store,
                        "authority_file_sha256": review_snapshot[
                            "authority_file_sha256"
                        ],
                        "target_kind": link.target_kind,
                        "target_requirement_id": link.target_requirement_id,
                        "target_fingerprint": link.target_fingerprint,
                        "previous_transition_event_hash": prior_hash,
                    },
                )
            )
        drafts.extend(_event_drafts_for_transition(
            link=link,
            before=before,
            after=after,
            reason=str(fact["reason"]),
            trigger_kind=trigger_kind,
            source_store=source_store,
            source_event_revision=source_event_revision,
            target_review_revision=str(fact["target_review_revision"]),
            observed_target_fingerprint=fact["observed_target_fingerprint"],
            base=base,
            base_by_claim=base_by_claim,
            effective_by_claim=effective_by_claim,
        ))
    return drafts


def reconcile_claim_review_events(
    out_dir: Path | str,
    *,
    base: dict[str, Any] | None = None,
    authority: dict[str, Any] | None = None,
    effective_by_claim: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Project review history and current target transitions into the audit log."""
    root = Path(out_dir).expanduser().resolve()
    with claim_publication_lock(root):
        current_base = base or load_committed_claim_base(root)
        generation = dict(current_base["generation_meta"])
        current_authority = authority or _load_declared_authority(
            root,
            generation,
        )
        expected_kind = str(generation.get("target_kind") or "")
        if current_authority.get("target_kind") != expected_kind:
            raise ClaimReviewActionError(
                "claim authority adapter differs from the committed target kind"
            )
        if effective_by_claim is None:
            snapshot = load_committed_shadow(root)
            effective_by_claim = {
                str(row.get("claim_id") or ""): row
                for row in snapshot.get("effective_ledger") or []
            }
        links = _target_links(current_base)
        base_by_claim = {
            str(row.get("claim_id") or ""): row
            for row in current_base["ledger"]
        }
        workload = {
            "history_record_count": 0,
            "link_index_insert_count": 0,
            "link_candidate_check_count": 0,
            "event_index_insert_count": 0,
        }
        historical = _historical_review_drafts(
            current_base,
            current_authority,
            links,
            base_by_claim,
            effective_by_claim,
            workload,
        )
        first = append_claim_review_events(
            root,
            historical,
            base_by_claim=base_by_claim,
            effective_by_claim=effective_by_claim,
        )
        event_snapshot = _scan_event_log_unlocked(root, repair=False)
        current = _current_transition_drafts(
            current_base,
            current_authority,
            links,
            event_snapshot.rows,
            base_by_claim,
            effective_by_claim,
            workload,
        )
        second = append_claim_review_events(
            root,
            current,
            base_by_claim=base_by_claim,
            effective_by_claim=effective_by_claim,
        )
        committed = _scan_event_log_unlocked(root, repair=False)
        return {
            "appended_count": int(first["appended_count"])
            + int(second["appended_count"]),
            "historical_appended_count": int(first["appended_count"]),
            "current_appended_count": int(second["appended_count"]),
            "event_prefix_sha256": committed.event_prefix_sha256,
            "last_event_seq": committed.last_event_seq,
            "last_event_hash": committed.last_event_hash,
            "workload": workload,
            "torn_tail_recovered": bool(
                first.get("torn_tail_recovered")
                or second.get("torn_tail_recovered")
            ),
            "quarantine_files": [
                value for value in (
                    first.get("quarantine_file"),
                    second.get("quarantine_file"),
                ) if value
            ],
        }


def _groups_by_claim(base: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group in base.get("groups") or []:
        result[str(group.get("claim_id") or "")].append(group)
    return result


def claim_coverage_group_hash(group: dict[str, Any]) -> str:
    """Return the stable hash experts must bind to for group evidence."""
    return hash_json("claim-coverage-group-fact/v1", group)


def claim_source_evidence_hash(claim: dict[str, Any]) -> str:
    """Bind an expert source locator to the exact current claim text."""
    return hash_json(
        "claim-source-evidence/v1",
        {
            "claim_hash": claim.get("claim_hash"),
            "locator": claim.get("locator"),
            "text": claim.get("text"),
        },
    )


def _resolution_fact_hash(kind: str, payload: Any) -> str:
    return hash_json(
        "claim-resolution-fact/v1",
        {"kind": kind, "payload": payload},
    )


def _base_resolution_facts(
    claim: dict[str, Any],
    reduced: dict[str, Any],
    adjusted_groups: list[dict[str, Any]],
) -> list[dict[str, str]]:
    facts: list[dict[str, str]] = [
        {
            "fact_hash": _resolution_fact_hash(
                "coverage_group",
                {
                    "claim_hash": claim.get("claim_hash"),
                    "coverage_group_id": group.get("coverage_group_id"),
                    "coverage_group_hash": claim_coverage_group_hash(group),
                },
            ),
            "kind": "coverage_group",
            "polarity": "positive",
        }
        for group in adjusted_groups
        if group.get("status") == "validated"
    ]
    semantic_negative = reduced.get("semantic_negative")
    if (
        isinstance(semantic_negative, dict)
        and semantic_negative.get("status") == "validated"
    ):
        facts.append({
            "fact_hash": _resolution_fact_hash(
                "semantic_negative",
                {
                    "claim_hash": claim.get("claim_hash"),
                    "semantic_negative_id": semantic_negative_id(semantic_negative),
                },
            ),
            "kind": "semantic_negative",
            "polarity": "negative",
        })
    if reduced.get("exclusion_kind") == "structural":
        facts.append({
            "fact_hash": _resolution_fact_hash(
                "structural_exclusion",
                {
                    "claim_hash": claim.get("claim_hash"),
                    "exclusion": claim.get("exclusion"),
                },
            ),
            "kind": "structural_exclusion",
            "polarity": "negative",
        })
    return facts


def _base_resolution_fact_hashes(
    claim: dict[str, Any],
    reduced: dict[str, Any],
    adjusted_groups: list[dict[str, Any]],
) -> dict[str, set[str]]:
    facts = _base_resolution_facts(claim, reduced, adjusted_groups)
    return {
        "positive": {
            fact["fact_hash"] for fact in facts if fact["polarity"] == "positive"
        },
        "negative": {
            fact["fact_hash"] for fact in facts if fact["polarity"] == "negative"
        },
    }


def claim_required_supersedes_fact_hashes(
    adjudication: str,
    active_facts: Iterable[dict[str, Any]],
) -> list[str]:
    """The exact supersedes set the server requires for one adjudication.

    An active audit conflict must be explicitly closed by every action; an
    active polarity conflict must be superseded on both sides; otherwise only
    the opposing polarity is required.  ``reopen`` supersedes everything.
    """
    facts = list(active_facts)
    audits = {
        str(fact["fact_hash"])
        for fact in facts
        if fact.get("kind") == "audit_conflict"
    }
    positive = {
        str(fact["fact_hash"])
        for fact in facts
        if fact.get("polarity") == "positive"
    }
    negative = {
        str(fact["fact_hash"])
        for fact in facts
        if fact.get("polarity") == "negative"
    }
    if adjudication == "covered":
        required = audits | negative
    elif adjudication == "excluded_non_normative":
        required = audits | positive
    elif adjudication == "reopen":
        required = audits | positive | negative
    else:
        raise ValueError("unsupported claim adjudication")
    if positive and negative and adjudication != "reopen":
        required |= positive | negative
    return sorted(required)


def claim_base_resolution_fact_hashes(
    claim: dict[str, Any],
    base_row: dict[str, Any],
    groups: Iterable[dict[str, Any]],
) -> dict[str, list[str]]:
    """Expose concrete base fact hashes for an expert supersession request."""
    adjusted = [dict(group) for group in groups]
    reduced = {
        "exclusion_kind": base_row.get("exclusion_kind"),
        "semantic_negative": base_row.get("semantic_negative"),
    }
    facts = _base_resolution_fact_hashes(claim, reduced, adjusted)
    return {key: sorted(value) for key, value in facts.items()}


def _source_evidence_is_current(
    evidence: dict[str, Any],
    claim: dict[str, Any],
) -> bool:
    return (
        evidence.get("source_locator") == claim.get("locator")
        and evidence.get("source_text_hash") == claim_source_evidence_hash(claim)
    )


def _expert_evidence_state(
    event: dict[str, Any],
    *,
    claim: dict[str, Any],
    groups: list[dict[str, Any]],
    adjusted_by_id: dict[str, dict[str, Any]],
    records_by_id: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    evidence = dict(event.get("evidence") or {})
    kind = str(evidence.get("kind") or "")
    state: dict[str, Any] = {
        "current": False,
        "reason": "unsupported_evidence_kind",
        "coverage_group_ids": [],
        "state_inputs": {},
    }
    if kind == "coverage_group":
        group_id = str(evidence.get("coverage_group_id") or "")
        matches = [
            group for group in groups
            if group.get("coverage_group_id") == group_id
        ]
        if len(matches) != 1:
            state["reason"] = "coverage_group_missing"
            return state
        group = matches[0]
        adjusted = adjusted_by_id.get(group_id) or {}
        state["state_inputs"] = {
            "coverage_group_id": group_id,
            "coverage_group_hash": claim_coverage_group_hash(group),
            "coverage_group_status": adjusted.get("status"),
        }
        if evidence.get("coverage_group_hash") != claim_coverage_group_hash(group):
            state["reason"] = "coverage_group_hash_stale"
            return state
        if adjusted.get("status") != "validated":
            state["reason"] = "coverage_group_not_current"
            return state
        state.update({
            "current": True,
            "reason": "",
            "coverage_group_ids": [group_id],
        })
        return state
    if kind == "target_evidence":
        if not _source_evidence_is_current(evidence, claim):
            state["reason"] = "source_locator_or_hash_stale"
            return state
        try:
            target_fingerprint = canonical_target_fingerprint(
                evidence.get("target_fingerprint")
            )
        except ClaimArtifactError:
            state["reason"] = "target_fingerprint_invalid"
            return state
        link = TargetLink(
            target_kind=str(evidence.get("target_kind") or ""),
            target_requirement_id=str(evidence.get("target_requirement_id") or ""),
            target_fingerprint=target_fingerprint,
            claim_ids=(str(claim.get("claim_id") or ""),),
            baseline_eligibility="unknown",
        )
        fact = _current_target_fact(link, records_by_id)
        state["state_inputs"] = {
            "target_kind": link.target_kind,
            "target_requirement_id": link.target_requirement_id,
            "target_fingerprint": link.target_fingerprint,
            "target_eligibility": fact.get("eligibility"),
            "target_review_revision": fact.get("target_review_revision"),
            "observed_target_fingerprint": fact.get(
                "observed_target_fingerprint"
            ),
        }
        if fact.get("eligibility") != "active" or fact.get("record") is None:
            state["reason"] = str(fact.get("reason") or "target_not_active")
            return state
        produced = dict(evidence.get("produced_evidence") or {})
        requirement = dict(fact["record"].get("requirement") or {})
        if not evidence_is_current(produced, requirement):
            state["reason"] = "produced_evidence_stale"
            return state
        matching_groups: list[str] = []
        for group in groups:
            for edge in group.get("edges") or []:
                try:
                    edge_fingerprint = canonical_target_fingerprint(
                        edge.get("target_fingerprint")
                    )
                except ClaimArtifactError:
                    continue
                if (
                    edge.get("target_kind") == link.target_kind
                    and edge.get("target_requirement_id")
                    == link.target_requirement_id
                    and edge_fingerprint == link.target_fingerprint
                    and produced in (edge.get("produced_evidence") or [])
                ):
                    matching_groups.append(str(group.get("coverage_group_id") or ""))
                    break
        matching_groups = sorted({value for value in matching_groups if value})
        if not matching_groups:
            state["reason"] = "target_evidence_not_linked_to_claim"
            return state
        state.update({
            "current": True,
            "reason": "",
            "coverage_group_ids": matching_groups,
        })
        return state
    if kind == "source_exclusion":
        state["state_inputs"] = {
            "source_text_hash": claim_source_evidence_hash(claim),
            "exclusion_reason": evidence.get("exclusion_reason"),
        }
        if not _source_evidence_is_current(evidence, claim):
            state["reason"] = "source_locator_or_hash_stale"
            return state
        if evidence.get("exclusion_reason") not in _EXPERT_EXCLUSION_REASONS:
            state["reason"] = "unsupported_exclusion_reason"
            return state
        state.update({"current": True, "reason": ""})
        return state
    return state


def _expert_semantic_negative(
    event: dict[str, Any],
    claim: dict[str, Any],
) -> dict[str, Any]:
    evidence = dict(event["evidence"])
    text = str(claim.get("text") or "")
    reason = str(evidence["exclusion_reason"])
    event_id = str(event["event_id"])
    version = "claim-expert-adjudication-v1"
    evidence_rows = [{"start": 0, "end": len(text), "text": text}]
    checks = {name: True for name in SEMANTIC_NEGATIVE_CHECKS}
    return {
        "schema": "claim-semantic-negative/v3",
        "document_generation_id": claim["document_generation_id"],
        "catalog_generation_id": claim["catalog_generation_id"],
        "claim_id": claim["claim_id"],
        "claim_hash": claim["claim_hash"],
        "verifier_runtime_fingerprint": hash_json(
            "claim-expert-runtime/v1",
            {"actor": event["actor"], "version": version},
        ),
        "validation_input_hash": str(event["event_hash"]),
        "proposal": {
            "request_id": event_id,
            "version": version,
            "reason": reason,
            "evidence": evidence_rows,
            "rationale": str(event["reason"]),
        },
        "validation": {
            "request_id": event_id,
            "version": version,
            "reason": reason,
            "checks": checks,
            "evidence": evidence_rows,
            "rationale": str(event["reason"]),
        },
        "validation_source": {
            "generation_run_id": str(event["catalog_generation_id"]),
            "request_id": event_id,
        },
        "status": "validated",
        "invalid_reason": "",
        "validation_reused": False,
    }


def _current_adjusted_groups_for_expert(
    groups: list[dict[str, Any]],
    records_by_id: dict[tuple[str, str], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    adjusted_groups: list[dict[str, Any]] = []
    for group in groups:
        adjusted = dict(group)
        reason = ""
        if group.get("status") != "validated":
            reason = str(group.get("invalid_reason") or "base_group_not_validated")
        else:
            try:
                semantic_validation_fingerprint(group)
            except (ClaimArtifactError, KeyError, TypeError, ValueError):
                reason = "semantic_validation_fingerprint_invalid"
        for edge in group.get("edges") or []:
            try:
                target_fingerprint = canonical_target_fingerprint(
                    edge.get("target_fingerprint")
                )
            except ClaimArtifactError:
                reason = reason or "target_fingerprint_invalid"
                continue
            link = TargetLink(
                target_kind=str(edge.get("target_kind") or ""),
                target_requirement_id=str(
                    edge.get("target_requirement_id") or ""
                ),
                target_fingerprint=target_fingerprint,
                claim_ids=(str(group.get("claim_id") or ""),),
                baseline_eligibility=str(
                    edge.get("target_review_eligibility") or "unknown"
                ),
            )
            fact = _current_target_fact(link, records_by_id)
            if fact.get("eligibility") != "active":
                reason = reason or str(fact.get("reason") or "review_not_active")
            elif fact.get("record") is None:
                reason = reason or "target_missing"
            elif not all(
                evidence_is_current(item, fact["record"]["requirement"])
                for item in edge.get("produced_evidence") or []
            ):
                reason = reason or "produced_evidence_drift"
        if reason:
            adjusted["status"] = "invalid"
            adjusted["invalid_reason"] = reason
        else:
            adjusted["status"] = "validated"
            adjusted["invalid_reason"] = ""
        adjusted_groups.append(adjusted)
    return adjusted_groups


def _apply_expert_overlay(
    *,
    claim: dict[str, Any],
    reduced: dict[str, Any],
    groups: list[dict[str, Any]],
    adjusted_groups: list[dict[str, Any]],
    records_by_id: dict[tuple[str, str], list[dict[str, Any]]],
    relevant_events: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    result = dict(reduced)
    base_valid_group_ids = sorted({
        str(group.get("coverage_group_id") or "")
        for group in adjusted_groups
        if group.get("status") == "validated"
    } - {""})
    diagnostics: list[dict[str, Any]] = []
    if result.get("exclusion_kind") == "structural":
        base_facts = _base_resolution_fact_hashes(
            claim, result, adjusted_groups
        )
        structural_facts = sorted(
            _base_resolution_facts(claim, result, adjusted_groups),
            key=lambda fact: fact["fact_hash"],
        )
        return result, base_valid_group_ids, {
            "base_fact_hashes": {
                key: sorted(value) for key, value in base_facts.items()
            },
            "superseded_base_fact_hashes": [],
            "active_resolution_facts": structural_facts,
            "events": diagnostics,
            "forced_invalid_group_reasons": {},
        }

    adjusted_by_id = {
        str(group.get("coverage_group_id") or ""): group
        for group in adjusted_groups
    }
    base_facts = _base_resolution_fact_hashes(claim, result, adjusted_groups)
    expert_events = [
        event for event in relevant_events
        if event.get("event_kind") == "expert_adjudication"
    ]
    audited_events = [
        event for event in relevant_events
        if event.get("event_kind") == "audit_conflict"
    ]
    evaluated: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for event in expert_events:
        state = _expert_evidence_state(
            event,
            claim=claim,
            groups=groups,
            adjusted_by_id=adjusted_by_id,
            records_by_id=records_by_id,
        )
        adjudication = str(event.get("adjudication") or "")
        supersedes = {
            str(value) for value in event.get("supersedes_fact_hashes") or []
        }
        required_base: set[str] = set()
        base_conflict_facts = set(base_facts["positive"] | base_facts["negative"])
        if base_facts["positive"] and base_facts["negative"]:
            required_base = base_conflict_facts
        elif result.get("resolution") == "covered" and adjudication in {
            "excluded_non_normative", "reopen",
        }:
            required_base = set(base_facts["positive"])
        elif result.get("resolution") == "excluded" and adjudication in {
            "covered", "reopen",
        }:
            required_base = set(base_facts["negative"])
        base_conflict = bool(base_facts["positive"] and base_facts["negative"])
        supersession_sufficient = (
            required_base.issubset(supersedes)
            if base_conflict
            else bool(required_base.intersection(supersedes))
        )
        if required_base and not supersession_sufficient:
            state = {
                **state,
                "current": False,
                "reason": "opposing_base_fact_not_superseded",
            }
        evaluated.append((event, state))

    known_fact_hashes = set(base_facts["positive"] | base_facts["negative"])
    known_fact_hashes.update(
        str(event.get("event_hash") or "")
        for event, state in evaluated
        if state.get("current")
    )
    superseded: set[str] = set()
    for event, state in evaluated:
        if state.get("current"):
            superseded.update(
                str(value) for value in event.get("supersedes_fact_hashes") or []
            )

    active_experts: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for event, state in evaluated:
        active = bool(
            state.get("current")
            and event.get("event_hash") not in superseded
        )
        diagnostics.append({
            "event_hash": event.get("event_hash"),
            "event_kind": "expert_adjudication",
            "adjudication": event.get("adjudication"),
            "evidence_current": bool(state.get("current")),
            "evidence_reason": str(state.get("reason") or ""),
            "active": active,
            "state_inputs": state.get("state_inputs") or {},
        })
        if active:
            active_experts.append((event, state))

    active_audits: list[dict[str, Any]] = []
    for event in audited_events:
        evidence_states = []
        for evidence in event.get("evidence") or []:
            evidence_states.append(_expert_evidence_state(
                {**event, "evidence": evidence},
                claim=claim,
                groups=groups,
                adjusted_by_id=adjusted_by_id,
                records_by_id=records_by_id,
            ))
        conflict_hashes = {
            str(value) for value in event.get("conflicting_fact_hashes") or []
        }
        current = bool(
            evidence_states
            and all(state.get("current") for state in evidence_states)
            and conflict_hashes.issubset(known_fact_hashes)
        )
        active = current and event.get("event_hash") not in superseded
        diagnostics.append({
            "event_hash": event.get("event_hash"),
            "event_kind": "audit_conflict",
            "evidence_current": current,
            "evidence_reason": (
                "" if current else "conflict_fact_or_evidence_stale"
            ),
            "active": active,
            "state_inputs": [
                state.get("state_inputs") or {} for state in evidence_states
            ],
        })
        if active:
            active_audits.append(event)

    adjudications = {
        str(event.get("adjudication") or "") for event, _ in active_experts
    }
    conflict = bool(
        active_audits
        or {"covered", "excluded_non_normative"}.issubset(adjudications)
    )
    reopen = "reopen" in adjudications
    valid_group_ids = base_valid_group_ids
    forced_invalid_group_reasons: dict[str, str] = {}
    if conflict or reopen:
        overlay_reason = "expert_fact_conflict" if conflict else "expert_reopen"
        overlay_invalid_reasons = [overlay_reason] if groups else list(
            result.get("invalid_reasons") or []
        )
        result.update({
            "resolution": "uncertain",
            "classification": "unknown",
            "classification_status": "needs_review",
            "exclusion_kind": None,
            "semantic_negative": None,
            "invalid_reasons": sorted(set(
                overlay_invalid_reasons
            )),
        })
        valid_group_ids = []
        forced_invalid_group_reasons = {
            str(group.get("coverage_group_id")): overlay_reason
            for group in groups
            if group.get("coverage_group_id")
        }
    elif active_experts:
        event, state = active_experts[-1]
        adjudication = str(event.get("adjudication") or "")
        if adjudication == "covered":
            valid_group_ids = sorted(set(state.get("coverage_group_ids") or []))
            result.update({
                "resolution": "covered",
                "classification": "normative",
                "classification_status": "validated",
                "exclusion_kind": None,
                "semantic_negative": None,
                "invalid_reasons": [],
            })
        elif adjudication == "excluded_non_normative":
            valid_group_ids = []
            forced_invalid_group_reasons = {
                str(group.get("coverage_group_id")): "expert_semantic_exclusion"
                for group in groups
                if group.get("coverage_group_id")
            }
            result.update({
                "resolution": "excluded",
                "classification": "non_normative",
                "classification_status": "validated",
                "exclusion_kind": "semantic",
                "semantic_negative": _expert_semantic_negative(event, claim),
                "invalid_reasons": [],
            })
    elif evaluated and result.get("resolution") == "uncertain":
        result["invalid_reasons"] = sorted(set(
            list(result.get("invalid_reasons") or [])
            + ["expert_evidence_stale"]
        ))
    active_facts: list[dict[str, str]] = [
        fact
        for fact in _base_resolution_facts(claim, result, adjusted_groups)
        if fact["fact_hash"] not in superseded
    ]
    active_facts.extend(
        {
            "fact_hash": str(event.get("event_hash") or ""),
            "kind": "expert_adjudication",
            "polarity": (
                "positive"
                if str(event.get("adjudication") or "") == "covered"
                else "negative"
            ),
        }
        for event, _state in active_experts
    )
    active_facts.extend(
        {
            "fact_hash": str(event.get("event_hash") or ""),
            "kind": "audit_conflict",
            "polarity": "negative",
        }
        for event in active_audits
    )
    active_facts = sorted(
        (fact for fact in active_facts if fact["fact_hash"]),
        key=lambda fact: fact["fact_hash"],
    )
    return result, valid_group_ids, {
        "base_fact_hashes": {
            key: sorted(value) for key, value in base_facts.items()
        },
        "superseded_base_fact_hashes": sorted(
            superseded.intersection(
                base_facts["positive"] | base_facts["negative"]
            )
        ),
        "active_resolution_facts": active_facts,
        "events": diagnostics,
        "forced_invalid_group_reasons": forced_invalid_group_reasons,
    }


def apply_claim_adjudication(
    out_dir: Path | str,
    *,
    claim_id: str,
    claim_hash: str,
    adjudication: str,
    reason: str,
    evidence: dict[str, Any],
    actor: str,
    expected_claim_effective_revision: str,
    supersedes_fact_hashes: Iterable[str] = (),
    request_idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Append one current expert fact, then fold it outside the event lock."""
    if adjudication not in {"covered", "excluded_non_normative", "reopen"}:
        raise ClaimReviewActionError("unsupported claim adjudication")
    if not isinstance(reason, str) or not reason.strip():
        raise ClaimReviewActionError("claim adjudication reason is required")
    if not isinstance(actor, str) or not actor.strip():
        raise ClaimReviewActionError("claim adjudication actor is required")
    if not isinstance(evidence, dict):
        raise ClaimReviewActionError("claim adjudication evidence must be an object")
    supersedes = sorted({str(value) for value in supersedes_fact_hashes})
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    with claim_publication_lock(root):
        base = load_committed_claim_base(root)
        snapshot = load_committed_shadow(root)
        base_by_claim = {
            str(row.get("claim_id") or ""): row for row in base["ledger"]
        }
        catalog_by_claim = {
            str(row.get("claim_id") or ""): row for row in base["catalog"]
        }
        effective_by_claim = {
            str(row.get("claim_id") or ""): row
            for row in snapshot.get("effective_ledger") or []
        }
        base_row = base_by_claim.get(claim_id)
        claim = catalog_by_claim.get(claim_id)
        effective = effective_by_claim.get(claim_id)
        if base_row is None or claim is None or effective is None:
            raise ClaimAdjudicationCasMismatch(
                f"claim is absent from the current committed snapshot: {claim_id}"
            )
        if claim.get("claim_hash") != claim_hash:
            raise ClaimAdjudicationCasMismatch(
                f"claim hash changed for claim {claim_id}"
            )
        if (
            effective.get("claim_effective_revision")
            != expected_claim_effective_revision
        ):
            raise ClaimAdjudicationCasMismatch(
                f"claim effective revision changed for claim {claim_id}"
            )
        if claim.get("eligibility") == "excluded":
            raise ClaimReviewActionError(
                "structural exclusions require a structural override and base rebuild"
            )

        generation = dict(base["generation_meta"])
        authority = _load_declared_authority(root, generation)
        records_by_id = _records_by_target_id(authority)
        groups = _groups_by_claim(base).get(claim_id, [])
        adjusted_groups = _current_adjusted_groups_for_expert(
            groups,
            records_by_id,
        )
        adjusted_by_id = {
            str(group.get("coverage_group_id") or ""): group
            for group in adjusted_groups
        }
        draft_for_validation = {
            "evidence": dict(evidence),
            "adjudication": adjudication,
        }
        evidence_state = _expert_evidence_state(
            draft_for_validation,
            claim=claim,
            groups=groups,
            adjusted_by_id=adjusted_by_id,
            records_by_id=records_by_id,
        )
        if not evidence_state.get("current"):
            raise ClaimReviewActionError(
                "claim adjudication evidence is stale: "
                + str(evidence_state.get("reason") or "unknown")
            )

        reduced = reduce_claim(
            claim,
            validated_groups=[
                group for group in adjusted_groups
                if group.get("status") == "validated"
            ],
            validated_negative=(
                base_row.get("semantic_negative")
                if isinstance(base_row.get("semantic_negative"), dict)
                else None
            ),
            all_groups=adjusted_groups,
        )
        event_snapshot = _scan_event_log_unlocked(root, repair=True)
        relevant = _relevant_events(event_snapshot.rows, base_row)
        _overlay_result, _overlay_valid_ids, overlay = _apply_expert_overlay(
            claim=claim,
            reduced=reduced,
            groups=groups,
            adjusted_groups=adjusted_groups,
            records_by_id=records_by_id,
            relevant_events=relevant,
        )
        # The server recomputes the required supersedes set under the lock:
        # a missing active fact, an inactive/history hash, or a changed
        # revision is a conflict (409), never a silent partial supersession.
        active_facts = list(overlay.get("active_resolution_facts") or [])
        required = set(
            claim_required_supersedes_fact_hashes(adjudication, active_facts)
        )
        superseded_set = set(supersedes)
        missing = required - superseded_set
        if missing:
            raise ClaimAdjudicationCasMismatch(
                "supersedes_fact_hashes is missing an active fact: "
                + ", ".join(sorted(missing))
            )
        active_hashes = {str(fact["fact_hash"]) for fact in active_facts}
        stale_superseded = superseded_set - active_hashes
        if stale_superseded:
            raise ClaimAdjudicationCasMismatch(
                "supersedes_fact_hashes contains an inactive or historical fact: "
                + ", ".join(sorted(stale_superseded))
            )
        if adjudication == "reopen" and not supersedes:
            raise ClaimReviewActionError("reopen must supersede a concrete fact")

        request_key = str(request_idempotency_key or "")
        idempotency_key = hash_json(
            "claim-expert-adjudication-idempotency/v1",
            {
                "claim_id": claim_id,
                "claim_hash": claim_hash,
                "expected_claim_effective_revision": (
                    expected_claim_effective_revision
                ),
                "adjudication": adjudication,
                "reason": reason.strip(),
                "evidence": evidence,
                "actor": actor.strip(),
                "supersedes_fact_hashes": supersedes,
                "request_idempotency_key": request_key,
            },
        )
        draft = {
            "schema": CLAIM_REVIEW_EVENT_SCHEMA,
            "claim_id": claim_id,
            "claim_hash": claim_hash,
            "document_generation_id": generation["document_generation_id"],
            "catalog_generation_id": generation["catalog_generation_id"],
            "event_kind": "expert_adjudication",
            "actor": actor.strip(),
            "reason": reason.strip(),
            "idempotency_key": idempotency_key,
            "expected_base_claim_row_hash": hash_json(
                "claim-base-row/v1", base_row
            ),
            "expected_claim_effective_revision": (
                expected_claim_effective_revision
            ),
            "adjudication": adjudication,
            "evidence": dict(evidence),
            "supersedes_fact_hashes": supersedes,
            "route": "expert",
        }
        appended = append_claim_review_events(
            root,
            [draft],
            base_by_claim=base_by_claim,
            effective_by_claim=effective_by_claim,
        )
        if appended["appended"]:
            event = dict(appended["appended"][0])
        else:
            event = next(
                dict(row) for row in _scan_event_log_unlocked(
                    root, repair=False
                ).rows
                if row.get("idempotency_key") == idempotency_key
            )
    folded = fold_effective_ledger(
        root,
        actor_trigger="expert_adjudication",
    )
    return {"ok": True, "event": event, "fold": folded}


def _relevant_events(
    event_rows: list[dict[str, Any]],
    base_row: dict[str, Any],
) -> list[dict[str, Any]]:
    # The base-row hash is an append-time CAS token. A later target-only base
    # rebuild can legitimately change that row while preserving the claim,
    # document, and catalog identities below. Replay revalidates the event's
    # concrete evidence and superseded facts against the new base instead of
    # treating the historical CAS token as a permanent equality predicate.
    relevant = [
        row for row in event_rows
        if row.get("claim_id") == base_row.get("claim_id")
        and row.get("claim_hash") == base_row.get("claim_hash")
        and row.get("document_generation_id")
        == base_row.get("document_generation_id")
        and row.get("catalog_generation_id")
        == base_row.get("catalog_generation_id")
    ]
    return [
        row for row in relevant
        if row.get("event_kind") in _RESOLUTION_EVENT_KINDS
    ]


def _effective_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    from claim_effective_contract import compute_effective_metrics

    return compute_effective_metrics(rows)


def _build_effective_rows(
    base: dict[str, Any],
    authority: dict[str, Any],
    event_rows: list[dict[str, Any]],
    old_effective_by_claim: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    # Kept in the signature for compatibility with callers migrating from the
    # transition-based implementation.  Current rows are derived exclusively
    # from committed base facts, the event prefix and authority projection.
    del old_effective_by_claim
    catalog_by_claim = {
        str(row.get("claim_id") or ""): row for row in base["catalog"]
    }
    groups_by_claim = _groups_by_claim(base)
    records_by_id = _records_by_target_id(authority)
    rows: list[dict[str, Any]] = []
    for base_row in base["ledger"]:
        claim_id = str(base_row.get("claim_id") or "")
        claim = catalog_by_claim[claim_id]
        adjusted_groups: list[dict[str, Any]] = []
        valid_group_ids: list[str] = []
        invalid_group_reasons: dict[str, str] = {}
        invalidated_targets: dict[tuple[str, str, str], dict[str, Any]] = {}
        linked_targets: dict[tuple[str, str, str], dict[str, Any]] = {}
        for group in groups_by_claim.get(claim_id, []):
            adjusted = dict(group)
            group_id = str(group.get("coverage_group_id") or "")
            reason = ""
            if group.get("status") != "validated":
                reason = str(group.get("invalid_reason") or "base_group_not_validated")
            else:
                try:
                    semantic_validation_fingerprint(group)
                except (ClaimArtifactError, KeyError, TypeError, ValueError):
                    reason = "semantic_validation_fingerprint_invalid"
            for edge in group.get("edges") or []:
                link = TargetLink(
                    target_kind=str(edge.get("target_kind") or ""),
                    target_requirement_id=str(
                        edge.get("target_requirement_id") or ""
                    ),
                    target_fingerprint=canonical_target_fingerprint(
                        edge.get("target_fingerprint")
                    ),
                    claim_ids=(claim_id,),
                    baseline_eligibility=str(
                        edge.get("target_review_eligibility") or "unknown"
                    ),
                )
                fact = _current_target_fact(link, records_by_id)
                identity = (
                    link.target_kind,
                    link.target_requirement_id,
                    link.target_fingerprint,
                )
                linked_targets[identity] = {
                    "target_kind": link.target_kind,
                    "target_requirement_id": link.target_requirement_id,
                    "target_fingerprint": link.target_fingerprint,
                    "target_review_revision": fact["target_review_revision"],
                }
                edge_reason = ""
                if fact["eligibility"] != "active":
                    edge_reason = str(fact["reason"] or "review_not_active")
                elif fact["record"] is None:
                    edge_reason = "target_missing"
                elif not all(
                    evidence_is_current(item, fact["record"]["requirement"])
                    for item in edge.get("produced_evidence") or []
                ):
                    edge_reason = "produced_evidence_drift"
                if edge_reason:
                    reason = reason or edge_reason
                    invalidated_targets.setdefault(identity, {
                        "target_kind": link.target_kind,
                        "target_requirement_id": link.target_requirement_id,
                        "target_fingerprint": link.target_fingerprint,
                        "observed_target_fingerprint": fact[
                            "observed_target_fingerprint"
                        ],
                        "reason": edge_reason,
                        "target_review_revision": fact[
                            "target_review_revision"
                        ],
                    })
            if reason:
                adjusted["status"] = "invalid"
                adjusted["invalid_reason"] = reason
                invalid_group_reasons[group_id] = reason
            else:
                adjusted["status"] = "validated"
                adjusted["invalid_reason"] = ""
                valid_group_ids.append(group_id)
            adjusted_groups.append(adjusted)

        reduced = reduce_claim(
            claim,
            validated_groups=[
                group for group in adjusted_groups
                if group.get("status") == "validated"
            ],
            validated_negative=(
                base_row.get("semantic_negative")
                if isinstance(base_row.get("semantic_negative"), dict)
                else None
            ),
            all_groups=adjusted_groups,
        )
        relevant = _relevant_events(event_rows, base_row)
        reduced, valid_group_ids, expert_overlay = _apply_expert_overlay(
            claim=claim,
            reduced=reduced,
            groups=groups_by_claim.get(claim_id, []),
            adjusted_groups=adjusted_groups,
            records_by_id=records_by_id,
            relevant_events=relevant,
        )
        forced_invalid_group_reasons = dict(
            expert_overlay.get("forced_invalid_group_reasons") or {}
        )
        if forced_invalid_group_reasons:
            invalid_group_reasons = forced_invalid_group_reasons
        else:
            invalid_group_reasons = {
                group_id: reason
                for group_id, reason in invalid_group_reasons.items()
                if group_id not in set(valid_group_ids)
            }
        reactivated_target_keys = {
            (
                str(event.get("target_kind") or ""),
                str(event.get("target_requirement_id") or ""),
                canonical_target_fingerprint(event.get("target_fingerprint")),
            )
            for event in relevant
            if event.get("event_kind") == "target_reactivated"
        }
        reused = sorted({
            str(group.get("coverage_group_id") or "")
            for group in groups_by_claim.get(claim_id, [])
            if str(group.get("coverage_group_id") or "") in set(valid_group_ids)
            and any(
                (
                    str(edge.get("target_kind") or ""),
                    str(edge.get("target_requirement_id") or ""),
                    canonical_target_fingerprint(edge.get("target_fingerprint")),
                ) in reactivated_target_keys
                for edge in group.get("edges") or []
            )
        } - {""})
        base_row_hash = hash_json("claim-base-row/v1", base_row)
        linked_target_rows = [linked_targets[key] for key in sorted(linked_targets)]
        effective_facts = {
            "valid_group_ids": sorted(valid_group_ids),
            "invalid_group_reasons": {
                key: invalid_group_reasons[key]
                for key in sorted(invalid_group_reasons)
            },
            "validated_negative_id": semantic_negative_id(
                reduced.get("semantic_negative")
            ),
            "invalidated_targets": [
                invalidated_targets[key] for key in sorted(invalidated_targets)
            ],
            "reused_validation_group_ids": reused,
            "superseded_base_fact_hashes": list(
                expert_overlay.get("superseded_base_fact_hashes") or []
            ),
            "active_resolution_facts": list(
                expert_overlay.get("active_resolution_facts") or []
            ),
        }
        last_relevant_event_seq = (
            int(relevant[-1]["event_seq"]) if relevant else 0
        )
        effective_state = {
            **{
                field: reduced[field]
                for field in (
                    "resolution",
                    "classification",
                    "classification_status",
                    "exclusion_kind",
                    "invalid_reasons",
                )
            },
            "semantic_negative": reduced.get("semantic_negative"),
            "effective_facts": effective_facts,
            "last_relevant_event_seq": last_relevant_event_seq,
        }
        from claim_effective_contract import (
            build_claim_revision_inputs,
            compute_claim_effective_revision,
        )

        revision_inputs = build_claim_revision_inputs(
            base_claim_row_hash=base_row_hash,
            ordered_relevant_event_hashes=[
                str(row["event_hash"]) for row in relevant
            ],
            linked_targets=linked_target_rows,
            expert_overlay=dict(expert_overlay),
            effective_state=effective_state,
        )
        claim_revision = compute_claim_effective_revision(revision_inputs)
        rows.append({
            **base_row,
            **effective_state,
            "schema": CLAIM_EFFECTIVE_LEDGER_SCHEMA,
            "base_ledger_schema": base_row["schema"],
            "base_claim_row_hash": base_row_hash,
            "claim_effective_revision": claim_revision,
            "revision_inputs": revision_inputs,
        })
    return rows


def derive_authoritative_effective_rows(
    base: dict[str, Any],
    authority: dict[str, Any],
    event_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Pure current-row reduction shared by fold, publish and read validation."""
    return _build_effective_rows(base, authority, event_rows, {})


def _build_queue(
    root: Path,
    base: dict[str, Any],
    effective_rows: list[dict[str, Any]],
    authority: dict[str, Any],
) -> list[dict[str, Any]]:
    from claim_focus import (
        CLAIM_FOCUS_ADAPTER_VERSION,
        ClaimFocusError,
        build_claim_focus_adapter,
    )
    from claim_reextract_attempts import derive_attempt_states, read_attempt_log

    catalog_by_claim = {
        str(row.get("claim_id") or ""): row for row in base["catalog"]
    }
    try:
        blocks = _parse_jsonl_objects(
            (root / "blocks.jsonl").read_bytes(),
            label="claim queue blocks",
        )
    except (FileNotFoundError, OSError, ClaimReviewActionError):
        blocks = []
    try:
        table_items = _parse_jsonl_objects(
            (root / "table_items.jsonl").read_bytes(),
            label="claim queue table items",
        )
    except (FileNotFoundError, OSError, ClaimReviewActionError):
        table_items = []
    try:
        table_cell_items = _parse_jsonl_objects(
            (root / "table_cell_items.jsonl").read_bytes(),
            label="claim queue table cell items",
        )
    except (FileNotFoundError, OSError, ClaimReviewActionError):
        table_cell_items = []
    try:
        attempt_states = derive_attempt_states(read_attempt_log(root).rows)
    except ClaimArtifactError:
        attempt_states = {}
    latest_by_proposal: dict[str, dict[str, Any]] = {}
    for state in attempt_states.values():
        proposal_id = str(state.get("proposal_id") or "")
        previous = latest_by_proposal.get(proposal_id)
        if previous is None or int(
            dict(state.get("last_event") or {}).get("event_seq") or 0
        ) > int(dict(previous.get("last_event") or {}).get("event_seq") or 0):
            latest_by_proposal[proposal_id] = state
    queue: list[dict[str, Any]] = []
    for row in effective_rows:
        if row.get("resolution") != "uncertain":
            continue
        claim_id = str(row["claim_id"])
        claim = catalog_by_claim[claim_id]
        proposal_hash = hash_json(
            "claim-queue-proposal-id/v3",
            {
                "claim_id": claim_id,
                "claim_effective_revision": row["claim_effective_revision"],
                "action": "needs_extraction",
                "queue_version": CLAIM_QUEUE_VERSION,
            },
        )
        proposal_id = (
                f"CQP-{digest_hex(row['claim_hash'])[:8]}-"
                f"{digest_hex(proposal_hash)[:8]}"
        )
        latest_attempt = latest_by_proposal.get(proposal_id)
        lifecycle = "open"
        latest_attempt_summary = None
        if latest_attempt is not None:
            attempt_lifecycle = str(latest_attempt.get("lifecycle") or "")
            if attempt_lifecycle in {"executing", "rebuild_pending", "succeeded"}:
                lifecycle = (
                    "executed" if attempt_lifecycle == "succeeded" else attempt_lifecycle
                )
            terminal = dict(latest_attempt.get("terminal_event") or {})
            latest_attempt_summary = {
                "attempt_id": str(latest_attempt.get("attempt_id") or ""),
                "request_idempotency_key": str(
                    latest_attempt.get("request_idempotency_key") or ""
                ),
                "lifecycle": attempt_lifecycle,
                "last_event_seq": int(
                    dict(latest_attempt.get("last_event") or {}).get("event_seq") or 0
                ),
                "outcome": dict(terminal.get("outcome") or {}) or None,
            }
        try:
            focus = build_claim_focus_adapter(claim, blocks, table_items, table_cell_items)
            focus_error = None
        except ClaimFocusError as exc:
            focus = {
                "kind": "unavailable",
                "adapter_version": CLAIM_FOCUS_ADAPTER_VERSION,
                "reason": str(exc),
            }
            focus_error = str(exc)
        queue.append({
            "schema": CLAIM_QUEUE_PROPOSAL_SCHEMA,
            "proposal_id": proposal_id,
            "claim_id": claim_id,
            "claim_hash": row["claim_hash"],
            "parent_block_id": (
                claim.get("parent_block_id")
                or dict(claim.get("locator") or {}).get("block_id")
            ),
            "locator": claim.get("locator"),
            "claim_source_fingerprint": canonical_target_fingerprint(
                claim["claim_hash"]
            ),
            "document_generation_id": row["document_generation_id"],
            "catalog_generation_id": row["catalog_generation_id"],
            "claim_effective_revision": row["claim_effective_revision"],
            "action": "needs_extraction",
            "dry_run": False,
            "queue_version": CLAIM_QUEUE_VERSION,
            "expected_ledger_state": "uncertain",
            "created_from_event_seq": row["last_relevant_event_seq"],
            "lifecycle": lifecycle,
            "latest_attempt": latest_attempt_summary,
            "focus": focus,
            "focus_error": focus_error,
            "execution_preconditions": {
                "claim_id": claim_id,
                "claim_hash": row["claim_hash"],
                "claim_source_fingerprint": canonical_target_fingerprint(
                    claim["claim_hash"]
                ),
                "expected_claim_effective_revision": row[
                    "claim_effective_revision"
                ],
                "expected_ledger_state": "uncertain",
                "document_generation_id": row["document_generation_id"],
                "catalog_generation_id": row["catalog_generation_id"],
                "parent_block_fingerprint": focus.get(
                    "parent_block_fingerprint"
                ),
                "target_publication_revision": authority[
                    "target_publication_revision"
                ],
                "target_set_hash": authority["target_set_hash"],
                "requirement_review_state_hash": authority[
                    "requirement_review_state_hash"
                ],
                "focus_adapter_version": CLAIM_FOCUS_ADAPTER_VERSION,
            },
        })
    return queue


def _health_default() -> dict[str, Any]:
    return {
        "schema": _HEALTH_SCHEMA,
        "bridge_fold_lag": 0,
        "torn_tail_recovered": 0,
        "event_quarantine_count": 0,
        "authority_audit_gap": False,
        "authority_cas_gap": False,
        "authority_write_protocol_version": (
            CLAIM_AUTHORITY_WRITE_PROTOCOL_VERSION
        ),
        "legacy_authority_write_gap_count": 0,
        "legacy_authority_write_gaps": [],
        "effective_snapshot_migrations": [],
        "last_success_at": None,
        "last_failure_at": None,
        "last_error": None,
    }


def read_effective_health(out_dir: Path | str) -> dict[str, Any]:
    root = Path(out_dir).expanduser().resolve()
    path = claim_artifact_path(root, CLAIM_EFFECTIVE_HEALTH)
    if not path.is_file():
        return _health_default()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        # Health v1 predated migration auditing. Accept an already-written
        # sidecar and materialize the additive field on its next maintenance
        # write.
        if isinstance(value, dict):
            value.setdefault(
                "authority_write_protocol_version",
                CLAIM_AUTHORITY_WRITE_PROTOCOL_VERSION,
            )
            value.setdefault("legacy_authority_write_gap_count", 0)
            value.setdefault("legacy_authority_write_gaps", [])
            value.setdefault("effective_snapshot_migrations", [])
            for migration in value["effective_snapshot_migrations"]:
                if isinstance(migration, dict) and not migration.get("migration_id"):
                    migration["migration_id"] = hash_json(
                        "claim-effective-migration/v1",
                        {
                            "base_generation_id": migration.get(
                                "base_generation_id"
                            ),
                            "source_effective_snapshot_version": migration.get(
                                "source_effective_snapshot_version"
                            ),
                            "target_effective_snapshot_version": migration.get(
                                "target_effective_snapshot_version"
                            ),
                        },
                    )
        _validate_schema(
            value,
            "claim_effective_health.schema.json",
            label="claim effective health",
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ClaimArtifactError) as exc:
        raise ClaimReviewActionError("invalid claim effective health") from exc
    return value


def _reconcile_migration_health_from_meta(
    health: dict[str, Any],
    effective_meta: dict[str, Any],
    *,
    actor_trigger: str,
) -> bool:
    """Idempotently backfill the migration record from committed meta.

    The migration identity lives in the effective meta (committed atomically
    with the snapshot), so a crash between commit and the health write is
    healed by the next fold rather than lost.
    """
    migrated_from = str(effective_meta.get("migrated_from_version") or "")
    migration_id = str(effective_meta.get("migration_id") or "")
    if not migrated_from or not migration_id:
        return False
    record = {
        "migration_id": migration_id,
        "base_generation_id": str(effective_meta.get("base_generation_id") or ""),
        "source_effective_snapshot_version": migrated_from,
        "target_effective_snapshot_version": CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
        "effective_run_id": str(effective_meta.get("run_id") or ""),
        "migrated_at": str(effective_meta.get("committed_at") or ""),
        "actor_trigger": actor_trigger,
    }
    migrations = list(health.get("effective_snapshot_migrations") or [])
    for item in migrations:
        if migration_id and item.get("migration_id") == migration_id:
            return False
        if (
            item.get("base_generation_id") == record["base_generation_id"]
            and item.get("source_effective_snapshot_version")
            == record["source_effective_snapshot_version"]
            and item.get("target_effective_snapshot_version")
            == record["target_effective_snapshot_version"]
        ):
            return False
    migrations.append(record)
    health["effective_snapshot_migrations"] = migrations
    return True


def assess_effective_freshness(
    out_dir: Path | str,
    snapshot: dict[str, Any],
    *,
    readonly: bool = True,
) -> dict[str, Any]:
    """Compare a committed snapshot with live authority without mutating files."""
    from claim_artifacts import effective_versions_are_current

    root = Path(out_dir).expanduser().resolve()
    effective = dict(snapshot.get("effective_meta") or {})
    reasons: list[str] = []
    authority_audit_gap = False
    if not effective_versions_are_current(snapshot):
        reasons.append("effective_version_stale")

    event_snapshot = read_claim_review_events(
        root,
        repair=False,
        readonly=readonly,
    )
    committed_count = int(effective.get("last_event_seq") or 0)
    if committed_count > event_snapshot.last_event_seq:
        raise ClaimReviewActionError(
            "effective meta points beyond the claim review event log"
        )
    committed_prefix = b"".join(
        canonical_json_value_bytes(row) + b"\n"
        for row in event_snapshot.rows[:committed_count]
    )
    if sha256_bytes(committed_prefix) != effective.get("event_prefix_sha256"):
        raise ClaimReviewActionError(
            "effective event prefix does not match the committed event log"
        )
    if event_snapshot.last_event_seq > committed_count:
        reasons.append("event_prefix_advanced")

    generation = dict(snapshot.get("generation_meta") or {})
    from claim_structural_overrides import (
        CLAIM_STRUCTURAL_OVERRIDE_VERSION,
        current_structural_override_identity,
    )

    live_structural_overrides = current_structural_override_identity(root)
    if (
        generation.get("structural_override_version")
        != CLAIM_STRUCTURAL_OVERRIDE_VERSION
        or generation.get("structural_override_prefix_sha256")
        != live_structural_overrides.get("prefix_sha256")
        or generation.get("structural_override_prefix_count")
        != live_structural_overrides.get("prefix_count")
    ):
        reasons.append("structural_override_changed")
    try:
        authority = _load_declared_authority(
            root,
            generation,
            readonly=readonly,
        )
        if (
            authority["target_set_hash"] != effective.get("target_set_hash")
            or authority["target_publication_revision"]
            != effective.get("target_publication_revision")
        ):
            reasons.append("target_set_changed")
        if authority["requirement_review_state_hash"] != effective.get(
            "requirement_review_state_hash"
        ):
            reasons.append("review_authority_changed")
        authority_audit_gap = bool(
            dict(authority["review_snapshot"]).get("audit_gaps")
        )
        if authority_audit_gap:
            reasons.append("review_authority_changed")
    except ClaimReviewActionError:
        raise
    ordered_reasons = sorted(set(reasons))
    return {
        "effective_fresh": not ordered_reasons,
        "freshness_reasons": ordered_reasons,
        "authority_audit_gap": authority_audit_gap,
    }


def _write_effective_health(root: Path, health: dict[str, Any]) -> None:
    _validate_schema(
        health,
        "claim_effective_health.schema.json",
        label="claim effective health",
    )
    _atomic_write_bytes(
        claim_artifact_path(root, CLAIM_EFFECTIVE_HEALTH),
        canonical_json_value_bytes(health),
    )


def record_legacy_authority_write_gap(
    out_dir: Path | str,
    *,
    route: str,
    reason: str,
) -> dict[str, Any]:
    """Record a skipped authority write that could not supply the umbrella CAS."""
    if not str(route or "").strip() or not str(reason or "").strip():
        raise ValueError("legacy authority gap route and reason are required")
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    with claim_publication_lock(root):
        health = read_effective_health(root)
        occurrence = int(health["legacy_authority_write_gap_count"]) + 1
        gaps = list(health.get("legacy_authority_write_gaps") or [])
        gaps.append({
            "occurrence": occurrence,
            "route": str(route).strip(),
            "reason": str(reason).strip(),
            "observed_at": _utc_now(),
        })
        health.update({
            "authority_write_protocol_version": (
                CLAIM_AUTHORITY_WRITE_PROTOCOL_VERSION
            ),
            "legacy_authority_write_gap_count": occurrence,
            "legacy_authority_write_gaps": gaps[-100:],
        })
        _write_effective_health(root, health)
    return health


def _record_fold_failure(root: Path, error: Exception, *, cas_gap: bool) -> None:
    try:
        with claim_publication_lock(root):
            health = read_effective_health(root)
            health.update({
                "bridge_fold_lag": int(health["bridge_fold_lag"]) + 1,
                "authority_cas_gap": bool(cas_gap),
                "last_failure_at": _utc_now(),
                "last_error": f"{type(error).__name__}: {error}"[:1000],
            })
            _write_effective_health(root, health)
    except Exception:
        LOGGER.exception("failed to update claim effective health")


def _document_effective_revision(
    *,
    base_generation_id: str,
    last_event_seq: int,
    event_prefix_sha256: str,
    target_set_hash: str,
    requirement_review_state_hash: str,
    authority_projection_hash: str,
) -> str:
    from claim_effective_contract import compute_document_effective_revision

    return compute_document_effective_revision(
        base_generation_id=base_generation_id,
        last_event_seq=last_event_seq,
        event_prefix_sha256=event_prefix_sha256,
        target_set_hash=target_set_hash,
        requirement_review_state_hash=requirement_review_state_hash,
        authority_projection_hash=authority_projection_hash,
    )


def _effective_snapshot_matches_candidate(
    committed: dict[str, Any],
    effective_rows: list[dict[str, Any]],
    queue: list[dict[str, Any]],
    *,
    event_prefix_sha256: str,
    last_event_seq: int,
    document_effective_revision: str,
    authority: dict[str, Any],
    effective_metrics: dict[str, Any],
) -> bool:
    from claim_effective_contract import compute_effective_authority_projection_hash

    if not effective_versions_are_current(committed):
        return False
    if committed.get("effective_ledger") != effective_rows:
        return False
    if committed.get("queue_proposals") != queue:
        return False
    meta = dict(committed.get("effective_meta") or {})
    expected = {
        "event_prefix_sha256": event_prefix_sha256,
        "last_event_seq": last_event_seq,
        "document_effective_revision": document_effective_revision,
        "target_set_hash": authority["target_set_hash"],
        "target_publication_revision": authority["target_publication_revision"],
        "requirement_review_state_hash": authority[
            "requirement_review_state_hash"
        ],
        "authority_projection_hash": compute_effective_authority_projection_hash(
            effective_rows
        ),
        "effective_ledger_schema": CLAIM_EFFECTIVE_LEDGER_SCHEMA,
        "review_adapter_versions": effective_review_adapter_versions(),
        "reducer_version": CLAIM_EFFECTIVE_REDUCER_VERSION,
        "bridge_version": CLAIM_REVIEW_BRIDGE_VERSION,
        "queue_version": CLAIM_QUEUE_VERSION,
        "effective_metrics": effective_metrics,
    }
    return all(meta.get(field) == value for field, value in expected.items())


def fold_effective_ledger(
    out_dir: Path | str,
    *,
    actor_trigger: str,
    max_attempts: int = 3,
    authority_hook_track: str | None = None,
) -> dict[str, Any]:
    """Fold live authority into an effective snapshot without invoking any LLM."""
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not isinstance(actor_trigger, str) or not actor_trigger.strip():
        raise ValueError("actor_trigger must be a non-empty string")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    if authority_hook_track not in {None, "A", "B"}:
        raise ValueError("authority_hook_track must be A, B, or None")
    last_cas_error: Exception | None = None
    interrupted_recovery_recorded = False
    try:
        for attempt in range(1, max_attempts + 1):
            with claim_publication_lock(root):
                interrupted_effective_publication = (
                    claim_artifact_path(root, CLAIM_EFFECTIVE_PUBLICATION_JOURNAL)
                ).is_file()
                try:
                    base = load_committed_claim_base(root)
                except ClaimBaseMigrationRequired:
                    # S11：陈旧产物协议与版本闸同口径——结构化 base_migration_required，
                    # 不抛裸协议错误（唯一恢复路径是重跑 atomize）
                    return {
                        "ok": False,
                        "error": "base_migration_required",
                        "reason": "base_migration_required",
                        "publication_skipped": True,
                        "actor_trigger": actor_trigger,
                        "attempt": attempt,
                        "event_append_count": 0,
                    }
                from claim_artifacts import committed_base_versions_are_current

                if not committed_base_versions_are_current(
                    base,
                    require_environment_match=False,
                ):
                    return {
                        "ok": False,
                        "error": "base_migration_required",
                        "reason": "base_migration_required",
                        "publication_skipped": True,
                        "actor_trigger": actor_trigger,
                        "attempt": attempt,
                        "event_append_count": 0,
                    }
                if (
                    interrupted_effective_publication
                    and not interrupted_recovery_recorded
                ):
                    interrupted_health = read_effective_health(root)
                    interrupted_health.update({
                        "bridge_fold_lag": int(
                            interrupted_health["bridge_fold_lag"]
                        ) + 1,
                        "last_failure_at": _utc_now(),
                        "last_error": (
                            "ClaimEffectivePublicationInterrupted: "
                            "recovered unfinished effective publication"
                        ),
                    })
                    _write_effective_health(root, interrupted_health)
                    interrupted_recovery_recorded = True
                generation = dict(base["generation_meta"])
                if authority_hook_track is not None:
                    expected_declaration = {
                        "A": ("A", "atomic_requirement"),
                        "B": ("B", "ai_requirement"),
                    }[authority_hook_track]
                    generation_declaration = (
                        str(generation.get("delivery_track") or ""),
                        str(generation.get("target_kind") or ""),
                    )
                    producer_meta = dict(generation.get("shadow_meta") or {})
                    producer_declaration = (
                        str(producer_meta.get("delivery_track") or ""),
                        str(producer_meta.get("target_kind") or ""),
                    )
                    if (
                        generation_declaration != expected_declaration
                        or producer_declaration != expected_declaration
                    ):
                        return {
                            "ok": True,
                            "actor_trigger": actor_trigger,
                            "attempt": attempt,
                            "publication_skipped": True,
                            "reason": "authority_hook_declaration_mismatch",
                            "event_append_count": 0,
                        }
                refold_seed = load_committed_effective_refold_seed(root)
                source_effective_meta = dict(
                    refold_seed["source_effective_meta"]
                )
                committed = refold_seed.get("trusted_current_snapshot")
                source_effective_version = str(
                    source_effective_meta.get("effective_snapshot_version") or ""
                )
                migration_health = read_effective_health(root)
                if _reconcile_migration_health_from_meta(
                    migration_health,
                    source_effective_meta,
                    actor_trigger=actor_trigger,
                ):
                    # The source meta can be replaced later in this fold. Make
                    # its committed migration durable before that overwrite.
                    _write_effective_health(root, migration_health)
                authority = _load_declared_authority(root, generation)
                authority_identity = _authority_cas_identity(authority)
                pre_reconcile_events = _scan_event_log_unlocked(
                    root,
                    repair=False,
                )
                pre_reconcile_rows = derive_authoritative_effective_rows(
                    base,
                    authority,
                    pre_reconcile_events.rows,
                )
                effective_by_claim = {
                    str(row.get("claim_id") or ""): row
                    for row in pre_reconcile_rows
                }
                try:
                    reconcile = reconcile_claim_review_events(
                        root,
                        base=base,
                        authority=authority,
                        effective_by_claim=effective_by_claim,
                    )
                except ClaimProjectionCasMismatch as exc:
                    last_cas_error = exc
                    continue
                event_snapshot = _scan_event_log_unlocked(root, repair=False)
                effective_rows = derive_authoritative_effective_rows(
                    base, authority, event_snapshot.rows
                )
                queue = _build_queue(root, base, effective_rows, authority)
                effective_metrics = _effective_metrics(effective_rows)
                from claim_effective_contract import (
                    compute_effective_authority_projection_hash,
                )

                authority_projection_hash = (
                    compute_effective_authority_projection_hash(effective_rows)
                )
                document_revision = _document_effective_revision(
                    base_generation_id=claim_base_generation_id(generation),
                    last_event_seq=event_snapshot.last_event_seq,
                    event_prefix_sha256=event_snapshot.event_prefix_sha256,
                    target_set_hash=authority["target_set_hash"],
                    requirement_review_state_hash=authority[
                        "requirement_review_state_hash"
                    ],
                    authority_projection_hash=authority_projection_hash,
                )
                confirmed = _load_declared_authority(root, generation)
                if _authority_cas_identity(confirmed) != authority_identity:
                    last_cas_error = ClaimReviewActionError(
                        f"authority changed during effective fold attempt {attempt}"
                    )
                    continue
                if committed is not None and _effective_snapshot_matches_candidate(
                    committed,
                    effective_rows,
                    queue,
                    event_prefix_sha256=event_snapshot.event_prefix_sha256,
                    last_event_seq=event_snapshot.last_event_seq,
                    document_effective_revision=document_revision,
                    authority=authority,
                    effective_metrics=effective_metrics,
                ):
                    health = read_effective_health(root)
                    migration_backfilled = _reconcile_migration_health_from_meta(
                        health,
                        dict(committed["effective_meta"]),
                        actor_trigger=actor_trigger,
                    )
                    if (
                        migration_backfilled
                        or int(health["bridge_fold_lag"])
                        or interrupted_recovery_recorded
                    ):
                        health.update({
                            "bridge_fold_lag": 0,
                            "authority_cas_gap": False,
                            "last_success_at": _utc_now(),
                            "last_error": None,
                        })
                        _write_effective_health(root, health)
                    return {
                        "ok": True,
                        "actor_trigger": actor_trigger,
                        "attempt": attempt,
                        "publication_skipped": True,
                        "effective_meta": dict(committed["effective_meta"]),
                        "effective_metrics": effective_metrics,
                        "queue_count": len(queue),
                        "event_append_count": reconcile["appended_count"],
                        "health": health,
                    }
                migrating_from = (
                    source_effective_version
                    if source_effective_version != CLAIM_EFFECTIVE_SNAPSHOT_VERSION
                    else None
                )
                migration_id = (
                    hash_json(
                        "claim-effective-migration/v1",
                        {
                            "base_generation_id": claim_base_generation_id(generation),
                            "source_effective_snapshot_version": migrating_from,
                            "target_effective_snapshot_version": (
                                CLAIM_EFFECTIVE_SNAPSHOT_VERSION
                            ),
                        },
                    )
                    if migrating_from
                    else None
                )
                meta = publish_effective_snapshot(
                    root,
                    effective_rows,
                    queue,
                    meta={
                        "run_id": f"effective-{uuid.uuid4().hex}",
                        "event_prefix_sha256": event_snapshot.event_prefix_sha256,
                        "last_event_seq": event_snapshot.last_event_seq,
                        "document_effective_revision": document_revision,
                        "target_set_hash": authority["target_set_hash"],
                        "target_publication_revision": authority[
                            "target_publication_revision"
                        ],
                        "requirement_review_state_hash": authority[
                            "requirement_review_state_hash"
                        ],
                        "authority_projection_hash": authority_projection_hash,
                        "effective_ledger_schema": CLAIM_EFFECTIVE_LEDGER_SCHEMA,
                        "review_adapter_versions": (
                            effective_review_adapter_versions()
                        ),
                        "reducer_version": CLAIM_EFFECTIVE_REDUCER_VERSION,
                        "bridge_version": CLAIM_REVIEW_BRIDGE_VERSION,
                        "queue_version": CLAIM_QUEUE_VERSION,
                        "effective_metrics": effective_metrics,
                        "migrated_from_version": migrating_from,
                        "migration_id": migration_id,
                    },
                )
                health = read_effective_health(root)
                _reconcile_migration_health_from_meta(
                    health,
                    meta,
                    actor_trigger=actor_trigger,
                )
                review_snapshot = dict(authority["review_snapshot"])
                health.update({
                    "bridge_fold_lag": 0,
                    "torn_tail_recovered": int(health["torn_tail_recovered"])
                    + int(bool(reconcile["torn_tail_recovered"]))
                    + int(bool(review_snapshot.get("torn_tail_recovered"))),
                    "event_quarantine_count": int(
                        health["event_quarantine_count"]
                    ) + len(reconcile["quarantine_files"]),
                    "authority_audit_gap": bool(
                        review_snapshot.get("audit_gaps")
                    ),
                    "authority_cas_gap": False,
                    "last_success_at": _utc_now(),
                    "last_error": None,
                })
                _write_effective_health(root, health)
                return {
                    "ok": True,
                    "actor_trigger": actor_trigger,
                    "attempt": attempt,
                    "publication_skipped": False,
                    "effective_meta": meta,
                    "effective_metrics": effective_metrics,
                    "queue_count": len(queue),
                    "event_append_count": reconcile["appended_count"],
                    "health": health,
                }
        error = last_cas_error or ClaimReviewActionError(
            "authority did not stabilize during effective fold"
        )
        _record_fold_failure(root, error, cas_gap=True)
        raise error
    except Exception as exc:
        if exc is not last_cas_error:
            _record_fold_failure(root, exc, cas_gap=False)
        raise
