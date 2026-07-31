"""Append-only authority for accepted claim structural overrides."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable

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
CLAIM_STRUCTURAL_DECISIONS_DIR = "claim_structural_decisions"
CLAIM_STRUCTURAL_DECISION_SCHEMA = "claim-structural-verifier-decision/v1"
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


CLAIM_STRUCTURAL_ROUTE_CONFIG_VERSION = "claim-structural-route-config-v2"


def _route_preflight(route: str, allow_llm: bool) -> dict[str, Any]:
    if not allow_llm:
        return {"route_config_revision": None, "model": None, "config": None}
    from ai_extract import config_for_route
    from llm_client import apply_min_tokens

    raw_config = config_for_route(route)
    if raw_config is None:
        raise ClaimStructuralOverrideError(
            "the authorized structural verifier route is not configured"
        )
    config = apply_min_tokens(raw_config, "extract")
    api_key_env = str(config.api_key_env or "")
    credential = os.environ.get(api_key_env, "") if api_key_env else ""
    revision = hash_json(
        CLAIM_STRUCTURAL_ROUTE_CONFIG_VERSION,
        {
            "route": str(route),
            "base_url": str(config.base_url),
            "model": str(config.model),
            "api_key_env": api_key_env,
            "credential_present": bool(credential),
            "credential_fingerprint": (
                hash_json(
                    "claim-structural-route-credential/v1",
                    {"api_key_env": api_key_env, "credential": credential},
                )
                if credential else None
            ),
            "temperature": float(config.temperature),
            "max_tokens": int(config.max_tokens),
            "timeout_s": float(config.timeout_s),
            "max_retries": int(config.max_retries),
        },
    )
    return {
        "route_config_revision": revision,
        "model": str(config.model),
        "config": config,
    }


def _event_key(operation: str, kind: str, detail: Any = "") -> str:
    return hash_json(
        "claim-structural-operation-event/v2",
        {"operation_id": operation, "kind": kind, "detail": detail},
    )


def _request_without_preconditions(request: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in request.items() if key != "preconditions"
    }


def _initial_preflight(
    root: Path,
    request: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], Any | None]:
    from claim_artifacts import load_committed_shadow
    from claim_review_actions import assess_effective_freshness, read_claim_review_events

    try:
        snapshot = load_committed_shadow(root)
        freshness = assess_effective_freshness(root, snapshot, readonly=False)
    except ClaimArtifactError as exc:
        raise ClaimStructuralOverrideStale(
            "the committed claim snapshot is unavailable; refresh before confirming"
        ) from exc
    if freshness.get("effective_fresh") is not True:
        raise ClaimStructuralOverrideStale(
            "claim snapshot changed; refresh before confirming the structural override"
        )
    generation = dict(snapshot.get("generation_meta") or {})
    if generation.get("catalog_generation_id") != request[
        "expected_catalog_generation_id"
    ]:
        raise ClaimStructuralOverrideStale("catalog generation changed")
    catalog_row = next(
        (
            row for row in snapshot.get("catalog") or []
            if row.get("claim_id") == request["claim_id"]
        ),
        None,
    )
    effective_row = next(
        (
            row for row in snapshot.get("effective_ledger") or []
            if row.get("claim_id") == request["claim_id"]
        ),
        None,
    )
    if (
        catalog_row is None
        or effective_row is None
        or catalog_row.get("claim_hash") != request["claim_hash"]
    ):
        raise ClaimStructuralOverrideStale("claim identity changed")
    if effective_row.get("claim_effective_revision") != request[
        "expected_claim_effective_revision"
    ]:
        raise ClaimStructuralOverrideStale("claim effective revision changed")
    exclusion = catalog_row.get("exclusion")
    if catalog_row.get("eligibility") != "excluded" or not isinstance(exclusion, dict):
        raise ClaimStructuralOverrideError("claim is not structurally excluded")
    _validate_original_exclusion(request["prior_structural_reason"], exclusion)
    effective_meta = dict(snapshot.get("effective_meta") or {})
    event_snapshot = read_claim_review_events(root, repair=False)
    route_state = _route_preflight(
        str(request["route"]), bool(request["allow_llm"]),
    )
    preconditions = {
        "document_effective_revision": str(
            effective_meta.get("document_effective_revision") or ""
        ),
        "event_prefix_sha256": event_snapshot.event_prefix_sha256,
        "last_event_seq": event_snapshot.last_event_seq,
        "target_generation_id": str(generation.get("target_generation_id") or ""),
        "target_review_authority_revision": str(
            generation.get("target_review_authority_revision") or ""
        ),
        "route_config_revision": route_state["route_config_revision"],
        "route_model": route_state["model"],
    }
    if not all(
        isinstance(preconditions[key], str) and preconditions[key]
        for key in (
            "document_effective_revision",
            "event_prefix_sha256",
            "target_generation_id",
            "target_review_authority_revision",
        )
    ):
        raise ClaimStructuralOverrideStale(
            "claim snapshot lacks authority revisions required for confirmation"
        )
    return snapshot, preconditions, route_state["config"]


def _resume_preflight(
    root: Path,
    request: dict[str, Any],
    state: dict[str, Any],
) -> tuple[dict[str, Any], Any | None]:
    from claim_artifacts import load_committed_shadow_for_effective_refold
    from claim_review_actions import assess_effective_freshness, read_claim_review_events

    try:
        # An in-flight operation intentionally advances structural authority
        # before publishing the rebuilt base. This write-side loader preserves
        # hash validation while allowing that expected stale-current window.
        snapshot = load_committed_shadow_for_effective_refold(root)
        freshness = assess_effective_freshness(root, snapshot, readonly=False)
    except ClaimArtifactError as exc:
        raise ClaimStructuralOverrideStale(
            "the committed claim snapshot is unavailable during structural resume"
        ) from exc
    checkpoints = dict(state.get("checkpoints") or {})
    allowed_reasons: set[str] = set()
    if "override_registered" in checkpoints:
        allowed_reasons.add("structural_override_changed")
    if "audit_appended" in checkpoints:
        allowed_reasons.add("event_prefix_advanced")
    reasons = set(freshness.get("freshness_reasons") or [])
    if not reasons.issubset(allowed_reasons):
        raise ClaimStructuralOverrideStale(
            "claim authority changed after structural confirmation"
        )
    generation = dict(snapshot.get("generation_meta") or {})
    preconditions = dict(request.get("preconditions") or {})
    effective_meta = dict(snapshot.get("effective_meta") or {})
    if (
        generation.get("catalog_generation_id")
        != request["expected_catalog_generation_id"]
        or generation.get("target_generation_id")
        != preconditions.get("target_generation_id")
        or generation.get("target_review_authority_revision")
        != preconditions.get("target_review_authority_revision")
        or effective_meta.get("document_effective_revision")
        != preconditions.get("document_effective_revision")
    ):
        raise ClaimStructuralOverrideStale(
            "claim or target authority changed after structural confirmation"
        )
    catalog_row = next(
        (
            row for row in snapshot.get("catalog") or []
            if row.get("claim_id") == request["claim_id"]
        ),
        None,
    )
    effective_row = next(
        (
            row for row in snapshot.get("effective_ledger") or []
            if row.get("claim_id") == request["claim_id"]
        ),
        None,
    )
    if (
        catalog_row is None
        or effective_row is None
        or catalog_row.get("claim_hash") != request["claim_hash"]
        or effective_row.get("claim_effective_revision")
        != request["expected_claim_effective_revision"]
    ):
        raise ClaimStructuralOverrideStale(
            "claim identity or effective revision changed during structural resume"
        )
    event_snapshot = read_claim_review_events(root, repair=False)
    audit_checkpoint = checkpoints.get("audit_appended")
    expected_event_prefix = (
        str(audit_checkpoint.get("event_prefix_sha256") or "")
        if isinstance(audit_checkpoint, dict)
        else str(preconditions.get("event_prefix_sha256") or "")
    )
    expected_event_count = (
        int(audit_checkpoint.get("last_event_seq") or 0)
        if isinstance(audit_checkpoint, dict)
        else int(preconditions.get("last_event_seq") or 0)
    )
    if (
        event_snapshot.event_prefix_sha256 != expected_event_prefix
        or event_snapshot.last_event_seq != expected_event_count
    ):
        raise ClaimStructuralOverrideStale(
            "claim review event prefix changed during structural resume"
        )
    route_state = _route_preflight(
        str(request["route"]), bool(request["allow_llm"]),
    )
    if (
        route_state["route_config_revision"]
        != preconditions.get("route_config_revision")
        or route_state["model"] != preconditions.get("route_model")
    ):
        raise ClaimStructuralOverrideStale(
            "structural verifier route configuration changed; reconfirmation is required"
        )
    override_checkpoint = checkpoints.get("override_registered")
    if isinstance(override_checkpoint, dict):
        registry = read_structural_overrides(root)
        identity = structural_override_identity(registry)
        if (
            identity.get("prefix_sha256")
            != override_checkpoint.get("registry_prefix_sha256")
            or identity.get("prefix_count")
            != override_checkpoint.get("registry_prefix_count")
            or not any(
            row.get("override_id") == override_checkpoint.get("override_id")
            and row.get("override_hash") == override_checkpoint.get("override_hash")
            for row in registry.rows
            )
        ):
            raise ClaimStructuralOverrideStale(
                "structural override authority changed during resume"
            )
    return snapshot, route_state["config"]


def _effective_binding(
    root: Path,
    snapshot: dict[str, Any],
    *,
    claim_id: str,
    override_hash: str,
) -> dict[str, Any]:
    from claim_artifacts import (
        CLAIM_EFFECTIVE_META,
        claim_base_generation_id,
        file_sha256,
    )

    effective_row = next(
        (
            row for row in snapshot.get("effective_ledger") or []
            if row.get("claim_id") == claim_id
        ),
        None,
    )
    if effective_row is None:
        raise ClaimStructuralOverrideStale(
            "rebuilt structural claim is absent from the effective ledger"
        )
    return {
        "override_hash": str(override_hash),
        "base_generation_id": claim_base_generation_id(
            dict(snapshot.get("generation_meta") or {})
        ),
        "document_effective_revision": str(
            dict(snapshot.get("effective_meta") or {}).get(
                "document_effective_revision"
            )
            or ""
        ),
        "claim_effective_revision": str(
            effective_row.get("claim_effective_revision") or ""
        ),
        "effective_meta_sha256": file_sha256(root / CLAIM_EFFECTIVE_META),
    }


def _load_verified_replay(
    root: Path,
    state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    from claim_artifacts import load_committed_effective_snapshot_readonly
    from claim_review_actions import assess_effective_freshness

    terminal = dict(state.get("terminal") or {})
    expected_binding = dict(terminal.get("binding") or {})
    request = dict(state.get("request") or {})
    try:
        snapshot = load_committed_effective_snapshot_readonly(root)
        freshness = assess_effective_freshness(root, snapshot, readonly=True)
        current_binding = _effective_binding(
            root,
            snapshot,
            claim_id=str(request.get("claim_id") or ""),
            override_hash=str(expected_binding.get("override_hash") or ""),
        )
    except (ClaimArtifactError, OSError) as exc:
        raise ClaimStructuralOverrideStale(
            "completed structural operation cannot verify its current artifacts"
        ) from exc
    registry = read_structural_overrides(root)
    if (
        freshness.get("effective_fresh") is not True
        or current_binding != expected_binding
        or not any(
            row.get("override_hash") == expected_binding.get("override_hash")
            for row in registry.rows
        )
    ):
        raise ClaimStructuralOverrideStale(
            "completed structural operation no longer matches the current effective snapshot"
        )
    return snapshot, current_binding


class _StructuralBudgetProxy:
    """Multiplex the artifact checkpoint and structural WAL checkpoint."""

    def __init__(
        self,
        budget: Any,
        observer: Callable[[dict[str, Any]], None],
    ) -> None:
        self._budget = budget
        self._observer = observer
        self._primary: Callable[[dict[str, Any]], None] | None = None
        self._budget.set_checkpoint(self._dispatch)

    def _dispatch(self, snapshot: dict[str, Any]) -> None:
        self._observer(dict(snapshot))
        if self._primary is not None:
            self._primary(dict(snapshot))

    def set_checkpoint(
        self,
        checkpoint: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        if checkpoint is not None and self._primary is not None:
            raise RuntimeError("structural verifier budget already has a primary checkpoint")
        self._primary = checkpoint
        if checkpoint is not None:
            checkpoint(self.snapshot())

    def reserve(self, payload: dict[str, Any]) -> int:
        return self._budget.reserve(payload)

    def commit(self, reservation_id: int, usage: object) -> None:
        self._budget.commit(reservation_id, usage)

    def fail(self, reservation_id: int) -> None:
        self._budget.fail(reservation_id)

    def snapshot(self) -> dict[str, Any]:
        return self._budget.snapshot()

    def close(self) -> None:
        self._primary = None
        self._budget.set_checkpoint(None)


def _operation_usage(state: dict[str, Any]) -> dict[str, Any] | None:
    latest = state.get("latest_budget")
    return dict(latest) if isinstance(latest, dict) else None


def _canonical_copy(value: Any) -> Any:
    return json.loads(canonical_json_value_bytes(value).decode("utf-8"))


def _minimal_reusable_group(raw_group: dict[str, Any]) -> dict[str, Any]:
    """Keep only evidence identity and the independently validated decision."""
    from claim_ledger import semantic_validation_fingerprint

    status = str(raw_group.get("status") or "")
    if not (
        status == "validated"
        or (
            status == "invalid"
            and raw_group.get("invalid_reason") == "semantic_not_entailed"
        )
    ):
        raise ClaimStructuralOverrideError(
            "paid semantic coverage decision is not safely reusable"
        )
    if (
        raw_group.get("validation_method") != "independent_semantic"
        or raw_group.get("validation_reused") is True
        or not str(raw_group.get("validator_request_id") or "")
    ):
        raise ClaimStructuralOverrideError(
            "structural verifier group is not a new independent decision"
        )
    semantic_validation_fingerprint(raw_group)
    source = dict(raw_group.get("source_evidence") or {})
    prefilter = dict(raw_group.get("prefilter") or {})
    projection = {
        "coverage_group_id": str(raw_group.get("coverage_group_id") or ""),
        "claim_id": str(raw_group.get("claim_id") or ""),
        "claim_hash": str(raw_group.get("claim_hash") or ""),
        "source_evidence": {
            "text": source.get("text"),
            "claim_start": source.get("claim_start"),
            "claim_end": source.get("claim_end"),
            "match_method": source.get("match_method"),
        },
        "edges": [{
            "target_kind": edge.get("target_kind"),
            "target_requirement_id": edge.get("target_requirement_id"),
            "target_fingerprint": _canonical_copy(
                edge.get("target_fingerprint")
            ),
            "relation": edge.get("relation"),
            "produced_evidence": [{
                "field": item.get("field"),
                "item_index": item.get("item_index"),
                "start": item.get("start"),
                "end": item.get("end"),
                "position_basis": item.get("position_basis"),
                "field_value_hash": item.get("field_value_hash"),
            } for item in (edge.get("produced_evidence") or [])],
        } for edge in (raw_group.get("edges") or [])],
        "prefilter": {
            "version": prefilter.get("version"),
            "status": prefilter.get("status"),
            "missing_protected_facts": [{
                "kind": fact.get("kind"),
                "value": fact.get("value"),
                "aliases": list(fact.get("aliases") or []),
            } for fact in (prefilter.get("missing_protected_facts") or [])],
        },
        "validation_method": raw_group.get("validation_method"),
        "validator_version": raw_group.get("validator_version"),
        "verifier_runtime_fingerprint": raw_group.get(
            "verifier_runtime_fingerprint"
        ),
        "status": status,
        "invalid_reason": str(raw_group.get("invalid_reason") or ""),
        "validator_request_id": raw_group.get("validator_request_id"),
        "validator_checks": _canonical_copy(
            raw_group.get("validator_checks") or {}
        ),
        "validator_reason": str(raw_group.get("validator_reason") or ""),
        "validation_source": _canonical_copy(
            raw_group.get("validation_source") or {}
        ),
    }
    if (
        not projection["coverage_group_id"]
        or semantic_validation_fingerprint(projection)
        != semantic_validation_fingerprint(raw_group)
    ):
        raise ClaimStructuralOverrideError(
            "structural verifier group projection changed its evidence identity"
        )
    return _canonical_copy(projection)


def _operation_decision_projection(
    shadow: dict[str, Any],
    *,
    claim_id: str,
    claim_hash: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """Extract only new, reusable decisions owned by this structural claim."""
    metrics = dict(shadow.get("metrics") or {})
    if int(metrics.get("verifier_operation_failure_count") or 0) > 0:
        raise ClaimStructuralOverrideError(
            "structural verifier produced an incomplete decision set"
        )
    groups: list[dict[str, Any]] = []
    negatives: list[dict[str, Any]] = []
    runtime_fingerprints: set[str] = set()
    for raw in shadow.get("groups") or []:
        if not isinstance(raw, dict):
            continue
        is_new_paid = (
            raw.get("validation_method") == "independent_semantic"
            and raw.get("validation_reused") is not True
            and bool(str(raw.get("validator_request_id") or ""))
        )
        if not is_new_paid:
            continue
        if (
            raw.get("claim_id") != claim_id
            or raw.get("claim_hash") != claim_hash
        ):
            raise ClaimStructuralOverrideError(
                "structural rebuild paid for an unrelated coverage decision"
            )
        projected = _minimal_reusable_group(raw)
        groups.append(projected)
        runtime_fingerprints.add(str(
            projected.get("verifier_runtime_fingerprint") or ""
        ))
    for raw in shadow.get("negative_decisions") or []:
        if not isinstance(raw, dict) or raw.get("validation_reused") is True:
            continue
        proposal = dict(raw.get("proposal") or {})
        validation = dict(raw.get("validation") or {})
        is_new_paid = bool(
            str(proposal.get("request_id") or "")
            or str(validation.get("request_id") or "")
        )
        if not is_new_paid:
            continue
        if (
            raw.get("claim_id") != claim_id
            or raw.get("claim_hash") != claim_hash
        ):
            raise ClaimStructuralOverrideError(
                "structural rebuild paid for an unrelated negative decision"
            )
        if raw.get("status") != "validated":
            raise ClaimStructuralOverrideError(
                "paid semantic-negative decision is not safely reusable"
            )
        record = _canonical_copy(raw)
        negatives.append(record)
        runtime_fingerprints.add(str(
            record.get("verifier_runtime_fingerprint") or ""
        ))
    runtime_fingerprints.discard("")
    if not groups and not negatives:
        raise ClaimStructuralOverrideError(
            "paid structural verifier work has no reusable claim decision"
        )
    if len(runtime_fingerprints) != 1:
        raise ClaimStructuralOverrideError(
            "structural verifier decisions do not share one runtime identity"
        )
    groups.sort(key=lambda row: str(row.get("coverage_group_id") or ""))
    negatives.sort(key=lambda row: str(row.get("claim_id") or ""))
    return groups, negatives, next(iter(runtime_fingerprints))


def _decision_binding(
    request: dict[str, Any],
    state: dict[str, Any],
    *,
    runtime_fingerprint: str,
) -> dict[str, Any]:
    checkpoints = dict(state.get("checkpoints") or {})
    override = dict(checkpoints.get("override_registered") or {})
    budget = dict(state.get("latest_budget") or {})
    budget_event = dict(state.get("latest_budget_event") or {})
    preconditions = dict(request.get("preconditions") or {})
    if (
        not override
        or not budget
        or int(budget.get("attempted_calls") or 0) <= 0
        or int(budget.get("reserved_tokens") or 0) != 0
        or not str(budget_event.get("event_hash") or "")
    ):
        raise ClaimStructuralOverrideError(
            "verifier decision is not bound to a settled paid checkpoint"
        )
    return {
        "claim_id": str(request["claim_id"]),
        "claim_hash": str(request["claim_hash"]),
        "expected_catalog_generation_id": str(
            request["expected_catalog_generation_id"]
        ),
        "expected_claim_effective_revision": str(
            request["expected_claim_effective_revision"]
        ),
        "target_generation_id": str(preconditions["target_generation_id"]),
        "target_review_authority_revision": str(
            preconditions["target_review_authority_revision"]
        ),
        "override_hash": str(override["override_hash"]),
        "route_config_revision": preconditions.get("route_config_revision"),
        "route_model": preconditions.get("route_model"),
        "verifier_runtime_fingerprint": runtime_fingerprint,
        "budget_event_hash": str(budget_event["event_hash"]),
        "budget_checkpoint_hash": hash_json(
            "claim-structural-budget-checkpoint/v1", budget,
        ),
    }


def _write_decision_sidecar(
    root: Path,
    *,
    operation_id: str,
    request: dict[str, Any],
    state: dict[str, Any],
    shadow: dict[str, Any],
) -> dict[str, Any]:
    groups, negatives, runtime_fingerprint = _operation_decision_projection(
        shadow,
        claim_id=str(request["claim_id"]),
        claim_hash=str(request["claim_hash"]),
    )
    binding = _decision_binding(
        request, state, runtime_fingerprint=runtime_fingerprint,
    )
    body = {
        "schema": CLAIM_STRUCTURAL_DECISION_SCHEMA,
        "operation_id": operation_id,
        "binding": binding,
        "groups": groups,
        "negative_decisions": negatives,
    }
    decision_hash = hash_json(CLAIM_STRUCTURAL_DECISION_SCHEMA, body)
    record = {**body, "decision_payload_hash": decision_hash}
    _validate_schema(
        record,
        "claim_structural_verifier_decision.schema.json",
        label="claim structural verifier decision",
    )
    artifact_bytes = canonical_json_value_bytes(record) + b"\n"
    artifact_sha256 = sha256_bytes(artifact_bytes)
    relative_path = (
        f"{CLAIM_STRUCTURAL_DECISIONS_DIR}/"
        f"{digest_hex(decision_hash)}.json"
    )
    path = root / Path(relative_path)
    if path.is_file():
        if path.read_bytes() != artifact_bytes:
            raise ClaimStructuralOverrideError(
                "claim structural decision content address is occupied"
            )
    else:
        _atomic_write_bytes(path, artifact_bytes)
    return {
        "decision_artifact": relative_path,
        "decision_artifact_sha256": artifact_sha256,
        "decision_payload_hash": decision_hash,
        "binding": binding,
    }


def _load_decision_sidecar(
    root: Path,
    *,
    operation_id: str,
    request: dict[str, Any],
    state: dict[str, Any],
    checkpoint: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    relative_path = str(checkpoint.get("decision_artifact") or "")
    decision_hash = str(checkpoint.get("decision_payload_hash") or "")
    expected_relative = (
        f"{CLAIM_STRUCTURAL_DECISIONS_DIR}/"
        f"{digest_hex(decision_hash)}.json"
    )
    if relative_path != expected_relative:
        raise ClaimStructuralOverrideError(
            "structural verifier checkpoint has an invalid content address"
        )
    path = (root / Path(relative_path)).resolve()
    decision_root = (root / CLAIM_STRUCTURAL_DECISIONS_DIR).resolve()
    if path.parent != decision_root or not path.is_file():
        raise ClaimStructuralOverrideError(
            "structural verifier decision sidecar is unavailable"
        )
    raw = path.read_bytes()
    if sha256_bytes(raw) != checkpoint.get("decision_artifact_sha256"):
        raise ClaimStructuralOverrideError(
            "structural verifier decision sidecar hash changed"
        )
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClaimStructuralOverrideError(
            "structural verifier decision sidecar is invalid JSON"
        ) from exc
    if (
        not isinstance(record, dict)
        or canonical_json_value_bytes(record) + b"\n" != raw
    ):
        raise ClaimStructuralOverrideError(
            "structural verifier decision sidecar is not canonical"
        )
    _validate_schema(
        record,
        "claim_structural_verifier_decision.schema.json",
        label="claim structural verifier decision",
    )
    body = {
        key: value for key, value in record.items()
        if key != "decision_payload_hash"
    }
    if (
        record.get("schema") != CLAIM_STRUCTURAL_DECISION_SCHEMA
        or record.get("operation_id") != operation_id
        or record.get("decision_payload_hash") != decision_hash
        or hash_json(CLAIM_STRUCTURAL_DECISION_SCHEMA, body) != decision_hash
        or record.get("binding") != checkpoint.get("binding")
    ):
        raise ClaimStructuralOverrideError(
            "structural verifier decision sidecar binding is invalid"
        )
    expected_binding = _decision_binding(
        request,
        state,
        runtime_fingerprint=str(
            dict(record["binding"])["verifier_runtime_fingerprint"]
        ),
    )
    if record["binding"] != expected_binding:
        raise ClaimStructuralOverrideStale(
            "structural verifier decision authority changed during resume"
        )
    groups = [_canonical_copy(row) for row in record.get("groups") or []]
    negatives = [
        _canonical_copy(row) for row in record.get("negative_decisions") or []
    ]
    if any(
        row.get("claim_id") != request["claim_id"]
        or row.get("claim_hash") != request["claim_hash"]
        for row in [*groups, *negatives]
    ):
        raise ClaimStructuralOverrideError(
            "structural verifier sidecar contains an unrelated claim"
        )
    for group in groups:
        _minimal_reusable_group(group)
    return groups, negatives


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
    operation_id: str | None = None,
    reconfirm_paid_work: bool = False,
) -> dict[str, Any]:
    """Execute or resume one structural override under all mutation fences."""
    from claim_structural_confirmation import (
        confirm_structural_override as execute,
    )

    return execute(
        out_dir,
        claim_id=claim_id,
        claim_hash=claim_hash,
        expected_catalog_generation_id=expected_catalog_generation_id,
        expected_claim_effective_revision=expected_claim_effective_revision,
        prior_structural_reason=prior_structural_reason,
        actor=actor,
        reason=reason,
        request_idempotency_key=request_idempotency_key,
        allow_llm=allow_llm,
        route=route,
        verifier_max_calls=verifier_max_calls,
        verifier_max_total_tokens=verifier_max_total_tokens,
        operation_id=operation_id,
        reconfirm_paid_work=reconfirm_paid_work,
    )
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
