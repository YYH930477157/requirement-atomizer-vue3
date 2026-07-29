from __future__ import annotations

import json
import logging
import os
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from claim_artifacts import (
    CLAIM_EFFECTIVE_ARTIFACT_PROTOCOL_VERSION,
    CLAIM_EFFECTIVE_HEALTH,
    CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
    CLAIM_REVIEW_EVENTS,
    LEGACY_CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
    ClaimArtifactError,
    _atomic_write_bytes,
    _validate_schema,
    canonical_target_fingerprint,
    canonical_json_value_bytes,
    claim_base_generation_id,
    claim_publication_lock,
    digest_hex,
    hash_json,
    load_committed_claim_base,
    load_committed_shadow,
    publish_effective_snapshot,
    semantic_negative_id,
    sha256_bytes,
)
from claim_ledger import (
    CLAIM_EFFECTIVE_LEDGER_SCHEMA,
    CLAIM_EFFECTIVE_REDUCER_VERSION,
    CLAIM_QUEUE_VERSION,
    CLAIM_REVIEW_BRIDGE_VERSION,
    CLAIM_REVIEW_EVENT_SCHEMA,
    a_track_effective_authority,
    atomic_requirement_id,
    b_track_effective_authority,
    effective_review_adapter_versions,
    evidence_is_current,
    reduce_claim,
    semantic_validation_fingerprint,
)


LOGGER = logging.getLogger("requirement_atomizer")
_EMPTY_SHA256 = sha256_bytes(b"")
_EVENT_QUARANTINE_PREFIX = ".claim-review-events-quarantine-"
_B_TARGET_STORE = "ai_requirements.jsonl"
_B_REVIEW_STORE = "ai_review_states.jsonl"
_A_TARGET_STORE = "atomic_requirements.jsonl"
_A_REVIEW_STORE = "review_states.jsonl"
_HEALTH_SCHEMA = "claim-effective-health/v1"


class ClaimReviewActionError(ClaimArtifactError):
    pass


class ClaimProjectionCasMismatch(ClaimReviewActionError):
    """A bridge event was built from an obsolete base/effective snapshot."""


@dataclass(frozen=True)
class EventLogSnapshot:
    rows: list[dict[str, Any]]
    prefix_bytes: bytes
    event_prefix_sha256: str
    last_event_seq: int
    last_event_hash: str
    idempotency_keys: frozenset[str]
    torn_tail_recovered: bool = False
    quarantine_file: str | None = None


@dataclass(frozen=True)
class TargetLink:
    target_kind: str
    target_requirement_id: str
    target_fingerprint: str
    claim_ids: tuple[str, ...]
    baseline_eligibility: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _event_without_hash(event: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if key != "event_hash"}


def _event_id(event_seq: int, idempotency_key: str) -> str:
    return f"CRE-{event_seq}-{digest_hex(idempotency_key)[:12]}"


def _validate_projection_cas_drafts(
    drafts: Iterable[dict[str, Any]],
    *,
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


def _quarantine_suffix(root: Path, suffix: bytes) -> str:
    digest = digest_hex(sha256_bytes(suffix))
    name = f"{_EVENT_QUARANTINE_PREFIX}{digest}.bin"
    path = root / name
    if path.is_file():
        if path.read_bytes() != suffix:
            raise ClaimReviewActionError("claim event quarantine digest collision")
        return name
    _atomic_write_bytes(path, suffix)
    return name


def _repair_event_suffix(
    root: Path,
    raw: bytes,
    valid_end: int,
    *,
    torn_tail: bool,
) -> tuple[bytes, str | None]:
    suffix = raw[valid_end:]
    quarantine_file = None
    if suffix and not torn_tail:
        quarantine_file = _quarantine_suffix(root, suffix)
    _atomic_write_bytes(root / CLAIM_REVIEW_EVENTS, raw[:valid_end])
    return raw[:valid_end], quarantine_file


def _scan_event_log_unlocked(
    root: Path,
    *,
    repair: bool,
    raw: bytes | None = None,
) -> EventLogSnapshot:
    path = root / CLAIM_REVIEW_EVENTS
    if raw is None and not path.exists():
        return EventLogSnapshot(
            rows=[],
            prefix_bytes=b"",
            event_prefix_sha256=_EMPTY_SHA256,
            last_event_seq=0,
            last_event_hash=_EMPTY_SHA256,
            idempotency_keys=frozenset(),
        )

    if raw is None:
        raw = path.read_bytes()
    rows: list[dict[str, Any]] = []
    idempotency_keys: set[str] = set()
    previous_hash = _EMPTY_SHA256
    offset = 0
    valid_end = 0
    torn_tail = False
    failure: Exception | None = None

    while offset < len(raw):
        newline = raw.find(b"\n", offset)
        if newline < 0:
            torn_tail = True
            failure = ClaimReviewActionError("claim review event log has a torn tail")
            break
        line_end = newline + 1
        line = raw[offset:line_end]
        try:
            if line in {b"\n", b"\r\n"} or line.endswith(b"\r\n"):
                raise ClaimReviewActionError("claim review event log is not canonical JSONL")
            row = json.loads(line[:-1].decode("utf-8"))
            if not isinstance(row, dict):
                raise ClaimReviewActionError("claim review event is not an object")
            if canonical_json_value_bytes(row) + b"\n" != line:
                raise ClaimReviewActionError("claim review event line is not canonical")
            _validate_schema(
                row,
                "claim_review_event.schema.json",
                label="claim review event",
            )
            expected_seq = len(rows) + 1
            if row.get("event_seq") != expected_seq:
                raise ClaimReviewActionError("claim review event sequence is not contiguous")
            if row.get("event_id") != _event_id(expected_seq, str(row["idempotency_key"])):
                raise ClaimReviewActionError("claim review event id is invalid")
            if row.get("prev_event_hash") != previous_hash:
                raise ClaimReviewActionError("claim review event hash chain is broken")
            expected_hash = hash_json(
                "claim-review-event/v1",
                _event_without_hash(row),
            )
            if row.get("event_hash") != expected_hash:
                raise ClaimReviewActionError("claim review event hash is invalid")
            idempotency_key = str(row.get("idempotency_key") or "")
            if idempotency_key in idempotency_keys:
                raise ClaimReviewActionError("claim review event idempotency key is duplicated")
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
            ClaimArtifactError,
        ) as exc:
            failure = exc
            break
        rows.append(row)
        idempotency_keys.add(idempotency_key)
        previous_hash = str(row["event_hash"])
        valid_end = line_end
        offset = line_end

    recovered = False
    quarantine_file = None
    if failure is not None:
        if not repair:
            raise ClaimReviewActionError(str(failure)) from failure
        raw, quarantine_file = _repair_event_suffix(
            root,
            raw,
            valid_end,
            torn_tail=torn_tail,
        )
        recovered = torn_tail
        LOGGER.warning(
            "recovered claim review event suffix at byte %d (%s)",
            valid_end,
            "torn tail" if torn_tail else f"quarantine={quarantine_file}",
        )
    prefix = raw[:valid_end] if failure is not None else raw
    return EventLogSnapshot(
        rows=rows,
        prefix_bytes=prefix,
        event_prefix_sha256=sha256_bytes(prefix),
        last_event_seq=len(rows),
        last_event_hash=previous_hash,
        idempotency_keys=frozenset(idempotency_keys),
        torn_tail_recovered=recovered,
        quarantine_file=quarantine_file,
    )


def _read_claim_review_events_readonly(root: Path) -> EventLogSnapshot:
    """Read a stable event-log snapshot without touching publication locks."""
    path = root / CLAIM_REVIEW_EVENTS
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
                    "claim-review-event/v1",
                    _event_without_hash(event),
                )
                _validate_schema(
                    event,
                    "claim_review_event.schema.json",
                    label="claim review event",
                )
                if handle is None:
                    handle = (root / CLAIM_REVIEW_EVENTS).open("ab")
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


def _load_b_track_authority(
    root: Path,
    *,
    readonly: bool = False,
) -> dict[str, Any]:
    from ai_review_actions import (
        read_ai_review_authority_snapshot,
        read_ai_review_authority_snapshot_readonly,
    )

    target_path = root / _B_TARGET_STORE
    target_present, target_bytes = _read_optional_authority_bytes(
        target_path,
        label="AI requirements",
    )
    requirements = (
        _parse_jsonl_objects(target_bytes, label="AI requirements")
        if target_present
        else []
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
        "target_source_store": _B_TARGET_STORE,
        "review_source_store": _B_REVIEW_STORE,
        "target_file_sha256": target_file_sha256,
        "target_publication_revision": _target_publication_revision(
            _B_TARGET_STORE,
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


def _relevant_events(
    event_rows: list[dict[str, Any]],
    base_row: dict[str, Any],
) -> list[dict[str, Any]]:
    relevant = [
        row for row in event_rows
        if row.get("claim_id") == base_row.get("claim_id")
        and row.get("claim_hash") == base_row.get("claim_hash")
        and row.get("document_generation_id")
        == base_row.get("document_generation_id")
        and row.get("catalog_generation_id")
        == base_row.get("catalog_generation_id")
    ]
    expected_base_hash = hash_json("claim-base-row/v1", base_row)
    for event in relevant:
        if event.get("expected_base_claim_row_hash") != expected_base_hash:
            raise ClaimProjectionCasMismatch(
                "claim review event base precondition does not match committed base"
            )
    return relevant


def _effective_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    eligible = [row for row in rows if row.get("exclusion_kind") != "structural"]
    covered = sum(row.get("resolution") == "covered" for row in rows)
    semantic = sum(row.get("exclusion_kind") == "semantic" for row in rows)
    structural = sum(row.get("exclusion_kind") == "structural" for row in rows)
    uncertain = sum(row.get("resolution") == "uncertain" for row in rows)

    def ratio(numerator: int, denominator: int) -> dict[str, Any]:
        return {
            "numerator": numerator,
            "denominator": denominator,
            "value": numerator / denominator if denominator else None,
        }

    return {
        "catalog_total_count": total,
        "eligible_claim_count": len(eligible),
        "covered_count": covered,
        "semantic_excluded_count": semantic,
        "structural_excluded_count": structural,
        "uncertain_count": uncertain,
        "inventory_accounted_ratio": ratio(total, total),
        "verified_coverage_ratio": ratio(covered, len(eligible)),
        "verified_semantic_exclusion_ratio": ratio(semantic, len(eligible)),
        "verified_exclusion_ratio": ratio(structural + semantic, total),
        "eligible_resolution_ratio": ratio(covered + semantic, len(eligible)),
        "structural_exclusion_ratio": ratio(structural, total),
    }


def _build_effective_rows(
    base: dict[str, Any],
    authority: dict[str, Any],
    event_rows: list[dict[str, Any]],
    old_effective_by_claim: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    catalog_by_claim = {
        str(row.get("claim_id") or ""): row for row in base["catalog"]
    }
    groups_by_claim = _groups_by_claim(base)
    records_by_id = _records_by_target_id(authority)
    adapter_versions = effective_review_adapter_versions()
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
        previous = old_effective_by_claim.get(claim_id) or {}
        previous_invalid = set(
            dict(previous.get("effective_facts") or {}).get(
                "invalid_group_reasons", {}
            )
        )
        reused = sorted(previous_invalid.intersection(valid_group_ids))
        base_row_hash = hash_json("claim-base-row/v1", base_row)
        linked_target_rows = [linked_targets[key] for key in sorted(linked_targets)]
        claim_revision = hash_json(
            "claim-effective-revision/v1",
            {
                "base_claim_row_hash": base_row_hash,
                "ordered_relevant_event_hashes": [
                    row["event_hash"] for row in relevant
                ],
                "linked_targets": linked_target_rows,
                "effective_ledger_schema": CLAIM_EFFECTIVE_LEDGER_SCHEMA,
                "reducer_version": CLAIM_EFFECTIVE_REDUCER_VERSION,
                "bridge_version": CLAIM_REVIEW_BRIDGE_VERSION,
                "review_adapter_versions": adapter_versions,
            },
        )
        rows.append({
            **base_row,
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
            "schema": CLAIM_EFFECTIVE_LEDGER_SCHEMA,
            "base_ledger_schema": base_row["schema"],
            "base_claim_row_hash": base_row_hash,
            "claim_effective_revision": claim_revision,
            "effective_facts": {
                "valid_group_ids": sorted(valid_group_ids),
                "invalid_group_reasons": {
                    key: invalid_group_reasons[key]
                    for key in sorted(invalid_group_reasons)
                },
                "validated_negative_id": semantic_negative_id(
                    base_row.get("semantic_negative")
                ),
                "invalidated_targets": [
                    invalidated_targets[key]
                    for key in sorted(invalidated_targets)
                ],
                "reused_validation_group_ids": reused,
            },
            "last_relevant_event_seq": (
                int(relevant[-1]["event_seq"]) if relevant else 0
            ),
        })
    return rows


def _build_queue(
    base: dict[str, Any],
    effective_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    catalog_by_claim = {
        str(row.get("claim_id") or ""): row for row in base["catalog"]
    }
    queue: list[dict[str, Any]] = []
    for row in effective_rows:
        if row.get("resolution") != "uncertain":
            continue
        claim_id = str(row["claim_id"])
        claim = catalog_by_claim[claim_id]
        proposal_hash = hash_json(
            "claim-queue-proposal-id/v1",
            {
                "claim_id": claim_id,
                "claim_effective_revision": row["claim_effective_revision"],
                "action": "needs_extraction",
                "queue_version": CLAIM_QUEUE_VERSION,
            },
        )
        queue.append({
            "schema": "claim-queue-proposal/v1",
            "proposal_id": (
                f"CQP-{digest_hex(row['claim_hash'])[:8]}-"
                f"{digest_hex(proposal_hash)[:8]}"
            ),
            "claim_id": claim_id,
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
            "dry_run": True,
            "queue_version": CLAIM_QUEUE_VERSION,
            "expected_ledger_state": "uncertain",
            "created_from_event_seq": row["last_relevant_event_seq"],
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
        "effective_snapshot_migrations": [],
        "last_success_at": None,
        "last_failure_at": None,
        "last_error": None,
    }


def read_effective_health(out_dir: Path | str) -> dict[str, Any]:
    root = Path(out_dir).expanduser().resolve()
    path = root / CLAIM_EFFECTIVE_HEALTH
    if not path.is_file():
        return _health_default()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        # Health v1 predated migration auditing. Accept an already-written
        # sidecar and materialize the additive field on its next maintenance
        # write.
        if isinstance(value, dict):
            value.setdefault("effective_snapshot_migrations", [])
        _validate_schema(
            value,
            "claim_effective_health.schema.json",
            label="claim effective health",
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ClaimArtifactError) as exc:
        raise ClaimReviewActionError("invalid claim effective health") from exc
    return value


def _record_effective_snapshot_migration(
    health: dict[str, Any],
    *,
    source_version: str,
    effective_meta: dict[str, Any],
    base_generation_id: str,
    actor_trigger: str,
) -> None:
    if source_version != LEGACY_CLAIM_EFFECTIVE_SNAPSHOT_VERSION:
        return
    record = {
        "base_generation_id": base_generation_id,
        "source_effective_snapshot_version": source_version,
        "target_effective_snapshot_version": CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
        "effective_run_id": str(effective_meta["run_id"]),
        "migrated_at": str(effective_meta["committed_at"]),
        "actor_trigger": actor_trigger,
    }
    migration_key = (
        record["base_generation_id"],
        record["source_effective_snapshot_version"],
        record["target_effective_snapshot_version"],
    )
    migrations = list(health.get("effective_snapshot_migrations") or [])
    if not any(
        (
            item.get("base_generation_id"),
            item.get("source_effective_snapshot_version"),
            item.get("target_effective_snapshot_version"),
        ) == migration_key
        for item in migrations
    ):
        migrations.append(record)
    health["effective_snapshot_migrations"] = migrations


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
        root / CLAIM_EFFECTIVE_HEALTH,
        canonical_json_value_bytes(health),
    )


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
) -> str:
    return hash_json(
        "claim-document-effective-revision/v1",
        {
            "base_generation_id": base_generation_id,
            "last_event_seq": last_event_seq,
            "event_prefix_sha256": event_prefix_sha256,
            "target_set_hash": target_set_hash,
            "requirement_review_state_hash": requirement_review_state_hash,
            "effective_ledger_schema": CLAIM_EFFECTIVE_LEDGER_SCHEMA,
            "effective_snapshot_version": CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
            "effective_artifact_version": (
                CLAIM_EFFECTIVE_ARTIFACT_PROTOCOL_VERSION
            ),
            "reducer_version": CLAIM_EFFECTIVE_REDUCER_VERSION,
            "bridge_version": CLAIM_REVIEW_BRIDGE_VERSION,
            "queue_version": CLAIM_QUEUE_VERSION,
        },
    )


def fold_effective_ledger(
    out_dir: Path | str,
    *,
    actor_trigger: str,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Fold live authority into an effective snapshot without invoking any LLM."""
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not isinstance(actor_trigger, str) or not actor_trigger.strip():
        raise ValueError("actor_trigger must be a non-empty string")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    last_cas_error: Exception | None = None
    try:
        for attempt in range(1, max_attempts + 1):
            with claim_publication_lock(root):
                base = load_committed_claim_base(root)
                generation = dict(base["generation_meta"])
                committed = load_committed_shadow(root)
                source_effective_version = str(
                    dict(committed.get("effective_meta") or {}).get(
                        "effective_snapshot_version"
                    ) or ""
                )
                old_effective_by_claim = {
                    str(row.get("claim_id") or ""): row
                    for row in committed.get("effective_ledger") or []
                }
                authority = _load_declared_authority(root, generation)
                authority_identity = _authority_cas_identity(authority)
                try:
                    reconcile = reconcile_claim_review_events(
                        root,
                        base=base,
                        authority=authority,
                        effective_by_claim=old_effective_by_claim,
                    )
                except ClaimProjectionCasMismatch as exc:
                    last_cas_error = exc
                    continue
                event_snapshot = _scan_event_log_unlocked(root, repair=False)
                effective_rows = _build_effective_rows(
                    base,
                    authority,
                    event_snapshot.rows,
                    old_effective_by_claim,
                )
                queue = _build_queue(base, effective_rows)
                effective_metrics = _effective_metrics(effective_rows)
                document_revision = _document_effective_revision(
                    base_generation_id=claim_base_generation_id(generation),
                    last_event_seq=event_snapshot.last_event_seq,
                    event_prefix_sha256=event_snapshot.event_prefix_sha256,
                    target_set_hash=authority["target_set_hash"],
                    requirement_review_state_hash=authority[
                        "requirement_review_state_hash"
                    ],
                )
                confirmed = _load_declared_authority(root, generation)
                if _authority_cas_identity(confirmed) != authority_identity:
                    last_cas_error = ClaimReviewActionError(
                        f"authority changed during effective fold attempt {attempt}"
                    )
                    continue
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
                        "effective_ledger_schema": CLAIM_EFFECTIVE_LEDGER_SCHEMA,
                        "review_adapter_versions": (
                            effective_review_adapter_versions()
                        ),
                        "reducer_version": CLAIM_EFFECTIVE_REDUCER_VERSION,
                        "bridge_version": CLAIM_REVIEW_BRIDGE_VERSION,
                        "queue_version": CLAIM_QUEUE_VERSION,
                        "effective_metrics": effective_metrics,
                    },
                )
                health = read_effective_health(root)
                _record_effective_snapshot_migration(
                    health,
                    source_version=source_effective_version,
                    effective_meta=meta,
                    base_generation_id=claim_base_generation_id(generation),
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
