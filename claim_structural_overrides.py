"""Append-only authority for accepted claim structural overrides."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from claim_artifacts import (
    ClaimArtifactError,
    _atomic_write_bytes,
    _validate_schema,
    canonical_json_value_bytes,
    claim_publication_lock,
    digest_hex,
    hash_json,
    load_committed_claim_base,
    sha256_bytes,
)
from process_file_lock import process_file_lock


CLAIM_STRUCTURAL_OVERRIDES = "claim_structural_overrides.jsonl"
CLAIM_STRUCTURAL_OVERRIDE_SCHEMA = "claim-structural-override/v1"
CLAIM_STRUCTURAL_OVERRIDE_VERSION = "claim-structural-override-v1"
ALLOWED_STRUCTURAL_OVERRIDE_REASONS = frozenset({"repeated_page_furniture"})

_LOCK_NAME = "claim_structural_overrides.lock"
_LOCK_TIMEOUT_S = 15.0
_EMPTY_SHA256 = sha256_bytes(b"")
_PROCESS_LOCKS: dict[Path, RLock] = {}
_PROCESS_LOCKS_GUARD = RLock()


class ClaimStructuralOverrideError(ClaimArtifactError):
    """Raised when the structural-override authority is invalid."""


class ClaimStructuralOverrideStale(ClaimStructuralOverrideError):
    """Raised when an override request no longer refers to the current base."""


@dataclass(frozen=True)
class StructuralOverrideSnapshot:
    rows: list[dict[str, Any]]
    prefix_bytes: bytes
    prefix_sha256: str
    last_override_seq: int
    last_override_hash: str
    idempotency_keys: frozenset[str]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _process_lock(root: Path) -> RLock:
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(root, RLock())


def _override_id(claim_hash: str, idempotency_key: str) -> str:
    digest = hash_json(
        "claim-structural-override-id/v1",
        {"claim_hash": claim_hash, "idempotency_key": idempotency_key},
    )
    return "CSO-" + digest_hex(digest)[:16]


def _without_hash(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "override_hash"}


def empty_structural_override_snapshot() -> StructuralOverrideSnapshot:
    return StructuralOverrideSnapshot(
        rows=[],
        prefix_bytes=b"",
        prefix_sha256=_EMPTY_SHA256,
        last_override_seq=0,
        last_override_hash=_EMPTY_SHA256,
        idempotency_keys=frozenset(),
    )


def empty_structural_override_identity() -> dict[str, Any]:
    return {
        "version": CLAIM_STRUCTURAL_OVERRIDE_VERSION,
        "prefix_sha256": _EMPTY_SHA256,
        "prefix_count": 0,
    }


def structural_override_identity(
    snapshot: StructuralOverrideSnapshot,
) -> dict[str, Any]:
    return {
        "version": CLAIM_STRUCTURAL_OVERRIDE_VERSION,
        "prefix_sha256": snapshot.prefix_sha256,
        "prefix_count": snapshot.last_override_seq,
    }


def _scan_bytes(raw: bytes) -> StructuralOverrideSnapshot:
    if not raw:
        return empty_structural_override_snapshot()
    rows: list[dict[str, Any]] = []
    keys: set[str] = set()
    targets: set[tuple[str, str]] = set()
    previous_hash = _EMPTY_SHA256
    offset = 0
    while offset < len(raw):
        newline = raw.find(b"\n", offset)
        if newline < 0:
            raise ClaimStructuralOverrideError(
                "claim structural override registry has a torn tail"
            )
        line = raw[offset:newline + 1]
        try:
            row = json.loads(line[:-1].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ClaimStructuralOverrideError(
                "invalid claim structural override JSONL"
            ) from exc
        if not isinstance(row, dict) or canonical_json_value_bytes(row) + b"\n" != line:
            raise ClaimStructuralOverrideError(
                "claim structural override row is not canonical"
            )
        try:
            _validate_schema(
                row,
                "claim_structural_override.schema.json",
                label="claim structural override",
            )
        except ClaimArtifactError as exc:
            raise ClaimStructuralOverrideError(str(exc)) from exc
        expected_seq = len(rows) + 1
        idempotency_key = str(row.get("idempotency_key") or "")
        if row.get("override_seq") != expected_seq:
            raise ClaimStructuralOverrideError(
                "claim structural override sequence is not contiguous"
            )
        if row.get("override_id") != _override_id(
            str(row.get("claim_hash") or ""), idempotency_key
        ):
            raise ClaimStructuralOverrideError("claim structural override id is invalid")
        if row.get("registry_prefix_sha256") != sha256_bytes(raw[:offset]):
            raise ClaimStructuralOverrideError(
                "claim structural override prefix binding is invalid"
            )
        if row.get("prev_override_hash") != previous_hash:
            raise ClaimStructuralOverrideError(
                "claim structural override hash chain is broken"
            )
        expected_hash = hash_json(
            CLAIM_STRUCTURAL_OVERRIDE_SCHEMA,
            _without_hash(row),
        )
        if row.get("override_hash") != expected_hash:
            raise ClaimStructuralOverrideError(
                "claim structural override hash is invalid"
            )
        if idempotency_key in keys:
            raise ClaimStructuralOverrideError(
                "claim structural override idempotency key is duplicated"
            )
        target = (str(row.get("claim_id") or ""), str(row.get("claim_hash") or ""))
        if target in targets:
            raise ClaimStructuralOverrideError(
                "claim has more than one structural override"
            )
        rows.append(row)
        keys.add(idempotency_key)
        targets.add(target)
        previous_hash = str(row["override_hash"])
        offset = newline + 1
    return StructuralOverrideSnapshot(
        rows=rows,
        prefix_bytes=raw,
        prefix_sha256=sha256_bytes(raw),
        last_override_seq=len(rows),
        last_override_hash=previous_hash,
        idempotency_keys=frozenset(keys),
    )


def read_structural_overrides(
    out_dir: Path | str,
) -> StructuralOverrideSnapshot:
    root = Path(out_dir).expanduser().resolve()
    path = root / CLAIM_STRUCTURAL_OVERRIDES
    try:
        raw = path.read_bytes() if path.is_file() else b""
    except OSError as exc:
        raise ClaimStructuralOverrideError(
            "failed to read claim structural override registry"
        ) from exc
    return _scan_bytes(raw)


def current_structural_override_identity(out_dir: Path | str) -> dict[str, Any]:
    return structural_override_identity(read_structural_overrides(out_dir))


def _validate_original_exclusion(
    prior_structural_reason: str,
    original_exclusion: dict[str, Any],
) -> None:
    if prior_structural_reason not in ALLOWED_STRUCTURAL_OVERRIDE_REASONS:
        raise ClaimStructuralOverrideError(
            f"structural reason is not runtime-overridable: {prior_structural_reason}"
        )
    if not isinstance(original_exclusion, dict):
        raise ClaimStructuralOverrideError("original structural proof is required")
    if original_exclusion.get("reason") != prior_structural_reason:
        raise ClaimStructuralOverrideError(
            "original structural proof reason does not match the override"
        )
    if (
        original_exclusion.get("rule_id") != "catalog-repeated-page-furniture"
        or not isinstance(original_exclusion.get("rule_version"), str)
        or not original_exclusion.get("rule_version")
        or not isinstance(original_exclusion.get("evidence"), dict)
    ):
        raise ClaimStructuralOverrideError(
            "original repeated-page-furniture proof is malformed"
        )


def _idempotency_key(
    *,
    claim_id: str,
    claim_hash: str,
    document_generation_id: str,
    catalog_generation_id: str,
    prior_structural_reason: str,
    original_exclusion: dict[str, Any],
    actor: str,
    reason: str,
    request_idempotency_key: str,
) -> str:
    return hash_json(
        "claim-structural-override-idempotency/v1",
        {
            "claim_id": claim_id,
            "claim_hash": claim_hash,
            "document_generation_id": document_generation_id,
            "catalog_generation_id": catalog_generation_id,
            "prior_structural_reason": prior_structural_reason,
            "original_exclusion": original_exclusion,
            "actor": actor,
            "reason": reason,
            "request_idempotency_key": request_idempotency_key,
        },
    )


def append_structural_override(
    out_dir: Path | str,
    *,
    claim_id: str,
    claim_hash: str,
    document_generation_id: str,
    catalog_generation_id: str,
    prior_structural_reason: str,
    original_exclusion: dict[str, Any],
    actor: str,
    reason: str,
    request_idempotency_key: str,
    expected_registry_prefix_sha256: str,
) -> dict[str, Any]:
    """Append one verified override with prefix CAS and idempotent retry."""
    if not all(isinstance(value, str) and value.strip() for value in (
        claim_id,
        claim_hash,
        document_generation_id,
        catalog_generation_id,
        actor,
        reason,
        request_idempotency_key,
        expected_registry_prefix_sha256,
    )):
        raise ClaimStructuralOverrideError(
            "structural override identity, actor, reason, and CAS prefix are required"
        )
    proof = dict(original_exclusion)
    _validate_original_exclusion(prior_structural_reason, proof)
    key = _idempotency_key(
        claim_id=claim_id,
        claim_hash=claim_hash,
        document_generation_id=document_generation_id,
        catalog_generation_id=catalog_generation_id,
        prior_structural_reason=prior_structural_reason,
        original_exclusion=proof,
        actor=actor.strip(),
        reason=reason.strip(),
        request_idempotency_key=request_idempotency_key,
    )
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    with _process_lock(root):
        with process_file_lock(
            root / _LOCK_NAME,
            timeout_s=_LOCK_TIMEOUT_S,
            label="claim structural override lock",
        ):
            snapshot = read_structural_overrides(root)
            for row in snapshot.rows:
                if row.get("idempotency_key") == key:
                    return {
                        "override": dict(row),
                        "appended": False,
                        "registry": structural_override_identity(snapshot),
                    }
            if snapshot.prefix_sha256 != expected_registry_prefix_sha256:
                raise ClaimStructuralOverrideStale(
                    "claim structural override registry prefix changed"
                )
            if any(
                row.get("claim_id") == claim_id and row.get("claim_hash") == claim_hash
                for row in snapshot.rows
            ):
                raise ClaimStructuralOverrideError(
                    "claim already has a structural override"
                )
            seq = snapshot.last_override_seq + 1
            row = {
                "schema": CLAIM_STRUCTURAL_OVERRIDE_SCHEMA,
                "override_seq": seq,
                "override_id": _override_id(claim_hash, key),
                "prev_override_hash": snapshot.last_override_hash,
                "registry_prefix_sha256": snapshot.prefix_sha256,
                "claim_id": claim_id,
                "claim_hash": claim_hash,
                "document_generation_id": document_generation_id,
                "catalog_generation_id": catalog_generation_id,
                "prior_structural_reason": prior_structural_reason,
                "original_exclusion": proof,
                "actor": actor.strip(),
                "reason": reason.strip(),
                "recorded_at": _utc_now(),
                "idempotency_key": key,
            }
            row["override_hash"] = hash_json(
                CLAIM_STRUCTURAL_OVERRIDE_SCHEMA,
                _without_hash(row),
            )
            _validate_schema(
                row,
                "claim_structural_override.schema.json",
                label="claim structural override",
            )
            payload = snapshot.prefix_bytes + canonical_json_value_bytes(row) + b"\n"
            _atomic_write_bytes(root / CLAIM_STRUCTURAL_OVERRIDES, payload)
            committed = read_structural_overrides(root)
            return {
                "override": dict(row),
                "appended": True,
                "registry": structural_override_identity(committed),
            }


def register_structural_override(
    out_dir: Path | str,
    *,
    claim_id: str,
    claim_hash: str,
    expected_catalog_generation_id: str,
    prior_structural_reason: str,
    actor: str,
    reason: str,
    request_idempotency_key: str,
) -> dict[str, Any]:
    """Validate against the committed base, then advance the registry authority."""
    root = Path(out_dir).expanduser().resolve()
    with claim_publication_lock(root):
        base = load_committed_claim_base(root)
        generation = dict(base.get("generation_meta") or {})
        if generation.get("catalog_generation_id") != expected_catalog_generation_id:
            raise ClaimStructuralOverrideStale("catalog generation changed")
        claim = next(
            (
                row for row in base.get("catalog") or []
                if row.get("claim_id") == claim_id
            ),
            None,
        )
        if claim is None or claim.get("claim_hash") != claim_hash:
            raise ClaimStructuralOverrideStale("claim identity changed")
        exclusion = claim.get("exclusion")
        if claim.get("eligibility") != "excluded" or not isinstance(exclusion, dict):
            raise ClaimStructuralOverrideError("claim is not structurally excluded")
        _validate_original_exclusion(prior_structural_reason, exclusion)
        catalog_meta = dict(base.get("catalog_meta") or {})
        committed_prefix = str(
            catalog_meta.get("structural_override_prefix_sha256") or ""
        )
        if (
            catalog_meta.get("structural_override_version")
            != CLAIM_STRUCTURAL_OVERRIDE_VERSION
            or not committed_prefix
        ):
            raise ClaimStructuralOverrideStale(
                "catalog does not carry the current structural override protocol"
            )
        # append_structural_override checks idempotency before its prefix CAS. A
        # retry can therefore finish the audit/rebuild steps after the registry
        # already advanced, while a different request against this stale base is
        # still rejected by the committed-prefix CAS.
        return append_structural_override(
            root,
            claim_id=claim_id,
            claim_hash=claim_hash,
            document_generation_id=str(generation.get("document_generation_id") or ""),
            catalog_generation_id=expected_catalog_generation_id,
            prior_structural_reason=prior_structural_reason,
            original_exclusion=dict(exclusion),
            actor=actor,
            reason=reason,
            request_idempotency_key=request_idempotency_key,
            expected_registry_prefix_sha256=committed_prefix,
        )


def confirm_structural_override(
    out_dir: Path | str,
    *,
    claim_id: str,
    claim_hash: str,
    expected_catalog_generation_id: str,
    expected_claim_effective_revision: str,
    prior_structural_reason: str,
    actor: str,
    reason: str,
    request_idempotency_key: str,
    allow_llm: bool,
    route: str,
    verifier_max_calls: int,
    verifier_max_total_tokens: int,
) -> dict[str, Any]:
    """Register, audit, and rebuild an explicitly authorized override.

    Registry and audit writes are durable before rebuild starts. Any rebuild
    failure therefore leaves an honest ``rebuild_pending`` result whose prior
    effective snapshot is already stale by registry-prefix comparison.
    """
    if not isinstance(allow_llm, bool):
        raise ClaimStructuralOverrideError("allow_llm must be boolean")
    if not isinstance(route, str) or not route.strip():
        raise ClaimStructuralOverrideError("route is required")
    if (
        not isinstance(verifier_max_calls, int)
        or isinstance(verifier_max_calls, bool)
        or verifier_max_calls < 0
        or not isinstance(verifier_max_total_tokens, int)
        or isinstance(verifier_max_total_tokens, bool)
        or verifier_max_total_tokens < 0
    ):
        raise ClaimStructuralOverrideError(
            "verifier budgets must be non-negative integers"
        )
    if allow_llm and (verifier_max_calls <= 0 or verifier_max_total_tokens <= 0):
        raise ClaimStructuralOverrideError(
            "allow_llm requires positive verifier call and token budgets"
        )
    root = Path(out_dir).expanduser().resolve()
    with claim_publication_lock(root):
        from claim_review_actions import (
            append_claim_review_events,
            read_claim_review_events,
        )

        from claim_artifacts import load_committed_shadow

        base = load_committed_claim_base(root)
        effective_snapshot = load_committed_shadow(root)
        base_by_claim = {
            str(row.get("claim_id") or ""): row for row in base.get("ledger") or []
        }
        effective_by_claim = {
            str(row.get("claim_id") or ""): row
            for row in effective_snapshot.get("effective_ledger") or []
        }
        base_row = base_by_claim.get(claim_id)
        effective_row = effective_by_claim.get(claim_id)
        if base_row is None or effective_row is None:
            raise ClaimStructuralOverrideStale(
                "claim is absent from the current effective snapshot"
            )
        if effective_row.get("claim_effective_revision") != (
            expected_claim_effective_revision
        ):
            raise ClaimStructuralOverrideStale("claim effective revision changed")
        registered = register_structural_override(
            root,
            claim_id=claim_id,
            claim_hash=claim_hash,
            expected_catalog_generation_id=expected_catalog_generation_id,
            prior_structural_reason=prior_structural_reason,
            actor=actor,
            reason=reason,
            request_idempotency_key=request_idempotency_key,
        )
        override = dict(registered["override"])
        event_key = hash_json(
            "claim-structural-falsification-idempotency/v1",
            {
                "override_id": override["override_id"],
                "override_hash": override["override_hash"],
            },
        )
        generation = dict(base.get("generation_meta") or {})
        event_result = append_claim_review_events(
            root,
            [{
                "schema": "claim-review-event/v2",
                "claim_id": claim_id,
                "claim_hash": claim_hash,
                "document_generation_id": generation["document_generation_id"],
                "catalog_generation_id": generation["catalog_generation_id"],
                "event_kind": "structural_falsification",
                "actor": actor.strip(),
                "reason": reason.strip(),
                "idempotency_key": event_key,
                "expected_base_claim_row_hash": hash_json(
                    "claim-base-row/v1", base_row
                ),
                "expected_claim_effective_revision": (
                    expected_claim_effective_revision
                ),
                "prior_structural_reason": prior_structural_reason,
                "override_id": override["override_id"],
                "override_hash": override["override_hash"],
                "route": "deterministic",
            }],
            base_by_claim=base_by_claim,
            effective_by_claim=effective_by_claim,
        )
        if event_result["appended"]:
            event = dict(event_result["appended"][0])
        else:
            event = next(
                dict(row)
                for row in read_claim_review_events(root, repair=False).rows
                if row.get("idempotency_key") == event_key
            )

    try:
        from ai_extract import refresh_claim_shadow

        refresh = refresh_claim_shadow(
            root,
            route=route.strip(),
            allow_llm=allow_llm,
            verifier_max_calls=verifier_max_calls,
            verifier_max_total_tokens=verifier_max_total_tokens,
        )
        from claim_views import build_claim_view

        view = build_claim_view(root, "metrics")
        if not view.get("effective_fresh"):
            raise ClaimStructuralOverrideError(
                "structural override rebuild did not publish a fresh effective snapshot"
            )
    except Exception as exc:
        return {
            "ok": False,
            "status": "rebuild_pending",
            "override": override,
            "event": event,
            "registry": registered["registry"],
            "route_requested": route.strip(),
            "allow_llm": allow_llm,
            "verifier_budget": {
                "max_calls": verifier_max_calls,
                "max_total_tokens": verifier_max_total_tokens,
            },
            "effective_fresh": False,
            "error": f"{type(exc).__name__}: {exc}"[:1000],
        }
    return {
        "ok": True,
        "status": "rebuilt",
        "override": override,
        "event": event,
        "registry": registered["registry"],
        "route_requested": route.strip(),
        "allow_llm": allow_llm,
        "verifier_budget": {
            "max_calls": verifier_max_calls,
            "max_total_tokens": verifier_max_total_tokens,
        },
        "effective_fresh": True,
        "refresh": refresh,
    }


def apply_structural_overrides(
    rows: list[dict[str, Any]],
    snapshot: StructuralOverrideSnapshot,
) -> int:
    """Make only exact, still-current repeated-furniture proofs eligible."""
    by_identity = {
        (str(row.get("claim_id") or ""), str(row.get("claim_hash") or "")): row
        for row in rows
    }
    applied = 0
    for override in snapshot.rows:
        row = by_identity.get((
            str(override.get("claim_id") or ""),
            str(override.get("claim_hash") or ""),
        ))
        if row is None:
            continue
        exclusion = row.get("exclusion")
        if (
            row.get("eligibility") != "excluded"
            or not isinstance(exclusion, dict)
            or exclusion != override.get("original_exclusion")
            or exclusion.get("reason") != "repeated_page_furniture"
        ):
            continue
        row["eligibility"] = "claim"
        row["exclusion"] = None
        applied += 1
    return applied
