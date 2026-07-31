"""Frozen synthetic held-out evidence for the Phase 0 claim-ledger gate."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

import claim_catalog
import claim_ledger


GOLDEN_MANIFEST_SCHEMA_VERSION = "claim-ledger-golden-manifest/v3"
GOLDEN_DATASET_VERSION = "claim-ledger-golden-v4"
HELD_OUT_FIXTURE_HASH_VERSION = "claim-golden-heldout-fixture-hash-v1"
HELD_OUT_REVIEW_CONTRACT_VERSION = "claim-golden-heldout-review-v2"
BASELINE_REVISION_SCHEMA_VERSION = "claim-ledger-golden-baseline-revision/v1"
HELD_OUT_REVIEW_DIMENSIONS = (
    "claim_boundary",
    "eligibility",
    "resolution",
    "coverage",
    "target_obligation_subject",
    "target_modality",
    "role_object_preservation",
)
HELD_OUT_DIMENSION_VERDICTS = frozenset({
    "agree",
    "disagree",
    "needs_followup",
    "not_reviewed",
})

# Catalog version each frozen golden dataset generation was adjudicated under.
# Frozen claim identities embed the catalog version, so replay must pin the
# historical version instead of drifting with CLAIM_CATALOG_VERSION.
GOLDEN_CATALOG_VERSIONS = {
    "claim-ledger-golden-v2": "claim-catalog-v2",
    "claim-ledger-golden-v3": "claim-catalog-v4",
    "claim-ledger-golden-v4": "claim-catalog-v4",
}

ROOT = Path(__file__).resolve().parent
DEFAULT_GOLDEN_DIR = ROOT / "golden_sets" / "claim_ledger_v1"
GOLDEN_MANIFEST_SCHEMA = ROOT / "schemas" / "claim_ledger_golden_manifest.schema.json"


class HeldOutEvidenceError(ValueError):
    """Frozen held-out files are missing, malformed, or internally inconsistent."""


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HeldOutEvidenceError(f"{label} is missing or invalid") from exc
    if not isinstance(payload, dict):
        raise HeldOutEvidenceError(f"{label} must be a JSON object")
    return payload


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _raw_hash(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _overall_verdict(dimension_verdicts: Any) -> str | None:
    if (
        not isinstance(dimension_verdicts, dict)
        or set(dimension_verdicts) != set(HELD_OUT_REVIEW_DIMENSIONS)
        or any(
            value not in HELD_OUT_DIMENSION_VERDICTS
            for value in dimension_verdicts.values()
        )
    ):
        return None
    values = set(dimension_verdicts.values())
    if "disagree" in values:
        return "disagree"
    if "needs_followup" in values or "not_reviewed" in values:
        return "needs_followup"
    return "agree"


def _fixture_hash(
    *,
    manifest: dict[str, Any],
    declaration: dict[str, Any],
    input_case: dict[str, Any],
    expected_case: dict[str, Any],
) -> str:
    return _canonical_hash({
        "schema": HELD_OUT_FIXTURE_HASH_VERSION,
        "dataset_id": manifest["dataset_id"],
        "dataset_version": manifest["version"],
        "declaration": declaration,
        "input": input_case,
        "expected": expected_case,
    })


def _claim_matches(claim: dict[str, Any], selector: dict[str, Any]) -> bool:
    locator = dict(claim.get("locator") or {})
    locator_fields = {
        "block_id",
        "table_item_id",
        "row_index",
        "row_start",
        "row_end",
        "fallback_group_id",
        "start",
        "end",
    }
    return all(
        (locator.get(key) if key in locator_fields else claim.get(key)) == expected
        for key, expected in selector.items()
    )


def _negative_callbacks(case: dict[str, Any]):
    fixture = copy.deepcopy(case.get("semantic_negative_fixture"))
    if not isinstance(fixture, dict):
        return None, None

    def proposer(_unit_id: str, claims: list[dict[str, Any]]) -> dict[str, Any]:
        claim = claims[0]
        text = str(claim["source_evidence"]["text"])
        return {
            "request_id": "golden-negative-proposal",
            "usage_complete": True,
            "decisions": {claim["claim_id"]: {
                "non_normative": True,
                "reason": fixture["proposal_reason"],
                "evidence": [{"start": 0, "end": len(text), "text": text}],
            }},
        }

    def verifier(_unit_id: str, claims: list[dict[str, Any]]) -> dict[str, Any]:
        claim = claims[0]
        text = str(claim["source_evidence"]["text"])
        return {
            "request_id": "golden-negative-verifier",
            "usage_complete": True,
            "decisions": {claim["claim_id"]: {
                "non_normative": True,
                "reason": fixture["validator_reason"],
                "checks": {
                    name: fixture.get("all_checks") is True
                    for name in claim_ledger.SEMANTIC_NEGATIVE_CHECKS
                },
                "evidence": [{"start": 0, "end": len(text), "text": text}],
            }},
        }

    return proposer, verifier


def _coverage_summary(groups: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not groups:
        return None
    if len(groups) != 1:
        raise HeldOutEvidenceError("golden expected claim has ambiguous coverage groups")
    group = groups[0]
    return {
        "validation_method": group.get("validation_method"),
        "status": group.get("status"),
        "prefilter_status": dict(group.get("prefilter") or {}).get("status"),
        "edge_count": len(group.get("edges") or []),
    }


def _rebuild_case(
    case: dict[str, Any],
    expected: dict[str, Any],
    fixture_hash: str,
    *,
    replay_catalog_version: str | None = None,
) -> list[dict[str, Any]]:
    proposer, verifier = _negative_callbacks(case)
    catalog_build = claim_catalog.build_claim_catalog(
        copy.deepcopy(case.get("blocks") or []),
        copy.deepcopy(case.get("table_items") or []),
        scope=str(case.get("scope") or "full"),
        replay_catalog_version=replay_catalog_version,
    )
    ledger_build = claim_ledger.build_shadow_ledger(
        catalog_build,
        copy.deepcopy(case.get("requirements") or []),
        review_states=copy.deepcopy(case.get("review_states") or {}),
        controlled_term_aliases=copy.deepcopy(case.get("controlled_term_aliases") or {}),
        semantic_negative_proposer=proposer,
        semantic_negative_verifier=verifier,
    )
    catalog = list(catalog_build.get("catalog") or [])
    ledger = list(ledger_build.get("ledger") or [])
    groups = list(ledger_build.get("groups") or [])
    if (
        len(catalog) != expected.get("catalog_count")
        or len(groups) != expected.get("group_count")
        or len(catalog_build.get("meta", {}).get("container_mappings") or [])
        != expected.get("container_mapping_count")
        or catalog_build.get("meta", {}).get("accounting_status")
        != expected.get("accounting_status")
        or ledger_build.get("meta", {}).get("resolution_status")
        != expected.get("resolution_status")
    ):
        raise HeldOutEvidenceError("golden expected case no longer matches its rebuild")

    ledger_by_claim = {str(row.get("claim_id") or ""): row for row in ledger}
    groups_by_claim: dict[str, list[dict[str, Any]]] = {}
    for group in groups:
        groups_by_claim.setdefault(str(group.get("claim_id") or ""), []).append(group)

    items: list[dict[str, Any]] = []
    matched: set[str] = set()
    for claim_expected in expected.get("claims") or []:
        if not isinstance(claim_expected, dict):
            raise HeldOutEvidenceError("golden expected claim is malformed")
        selector = dict(claim_expected.get("selector") or {})
        matches = [row for row in catalog if _claim_matches(row, selector)]
        if len(matches) != 1:
            raise HeldOutEvidenceError("golden expected selector is missing or ambiguous")
        claim = matches[0]
        claim_id = str(claim.get("claim_id") or "")
        if not claim_id or claim_id in matched:
            raise HeldOutEvidenceError("golden expected claim is duplicated")
        matched.add(claim_id)
        row = ledger_by_claim.get(claim_id)
        if row is None:
            raise HeldOutEvidenceError("golden expected claim has no ledger row")
        for key, value in dict(claim_expected.get("catalog") or {}).items():
            if claim.get(key) != value:
                raise HeldOutEvidenceError("golden expected catalog projection is stale")
        for key, value in dict(claim_expected.get("ledger") or {}).items():
            if row.get(key) != value:
                raise HeldOutEvidenceError("golden expected ledger projection is stale")
        claim_groups = groups_by_claim.get(claim_id, [])
        if _coverage_summary(claim_groups) != claim_expected.get("coverage"):
            raise HeldOutEvidenceError("golden expected coverage projection is stale")
        items.append({
            "case_id": str(case.get("case_id") or ""),
            "claim_id": claim_id,
            "claim_hash": str(claim.get("claim_hash") or ""),
            "fixture_hash": fixture_hash,
            "source_text": str(claim.get("text") or ""),
            "raw_text": str(claim.get("raw_text") or ""),
            "section_path": list(claim.get("section_path") or []),
            "locator": dict(claim.get("locator") or {}),
            "expected": copy.deepcopy(claim_expected),
            "actual": {
                "catalog": {
                    key: claim.get(key)
                    for key in dict(claim_expected.get("catalog") or {})
                },
                "ledger": {
                    key: row.get(key)
                    for key in dict(claim_expected.get("ledger") or {})
                },
                "coverage": _coverage_summary(claim_groups),
            },
            "requirements": copy.deepcopy(case.get("requirements") or []),
            "review_expectations": copy.deepcopy(
                case.get("review_expectations") or {}
            ),
        })
    if len(matched) != len(catalog):
        raise HeldOutEvidenceError("golden expected claims do not conserve the rebuilt catalog")
    return items


def _history_path(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise HeldOutEvidenceError("golden history path is missing")
    candidate = (root / value).resolve()
    if not candidate.is_relative_to(root):
        raise HeldOutEvidenceError("golden history path escapes the dataset")
    return candidate


def _replay_baseline_revision(
    record: dict[str, Any],
    *,
    path: str,
    raw_sha256: str,
) -> dict[str, Any]:
    if record.get("schema") != BASELINE_REVISION_SCHEMA_VERSION:
        raise HeldOutEvidenceError("golden history schema is stale")
    if record.get("fixture_hash_version") != HELD_OUT_FIXTURE_HASH_VERSION:
        raise HeldOutEvidenceError("golden history fixture hash version is stale")
    declaration = record.get("declaration")
    input_case = record.get("input")
    expected_case = record.get("expected")
    adjudication = record.get("adjudication")
    if not all(
        isinstance(value, dict)
        for value in (declaration, input_case, expected_case, adjudication)
    ):
        raise HeldOutEvidenceError("golden history record is malformed")

    case_id = str(declaration.get("case_id") or "")
    if (
        not case_id
        or str(input_case.get("case_id") or "") != case_id
        or str(expected_case.get("case_id") or "") != case_id
        or str(adjudication.get("case_id") or "") != case_id
        or declaration.get("partition") != "held_out"
        or declaration.get("tuning_eligible") is not False
    ):
        raise HeldOutEvidenceError("golden history case binding is invalid")
    source = input_case.get("source")
    if (
        not isinstance(source, dict)
        or source.get("origin") != "synthetic"
        or source.get("contains_customer_wording") is not False
    ):
        raise HeldOutEvidenceError("golden history source is not synthetic")

    fixture_hash = _fixture_hash(
        manifest={
            "dataset_id": record.get("dataset_id"),
            "version": record.get("dataset_version"),
        },
        declaration=declaration,
        input_case=input_case,
        expected_case=expected_case,
    )
    if fixture_hash != str(adjudication.get("fixture_hash") or ""):
        raise HeldOutEvidenceError("golden history fixture hash does not replay")
    historical_catalog_versions = GOLDEN_CATALOG_VERSIONS
    replay_catalog_version = historical_catalog_versions.get(
        str(record.get("dataset_version") or "")
    )
    if not replay_catalog_version:
        raise HeldOutEvidenceError("golden history catalog version is unknown")
    items = _rebuild_case(
        input_case,
        expected_case,
        fixture_hash,
        replay_catalog_version=replay_catalog_version,
    )
    identity = (
        str(adjudication.get("claim_id") or ""),
        str(adjudication.get("claim_hash") or ""),
        str(adjudication.get("fixture_hash") or ""),
    )
    matches = [
        item for item in items
        if (
            str(item.get("claim_id") or ""),
            str(item.get("claim_hash") or ""),
            str(item.get("fixture_hash") or ""),
        ) == identity
    ]
    if len(matches) != 1:
        raise HeldOutEvidenceError("golden history adjudication does not bind a replayed claim")

    derived_verdict = _overall_verdict(adjudication.get("dimension_verdicts"))
    prepared_by = str(adjudication.get("prepared_by") or "").strip()
    reviewed_by = str(adjudication.get("reviewed_by") or "").strip()
    if (
        adjudication.get("review_contract_version")
        != HELD_OUT_REVIEW_CONTRACT_VERSION
        or derived_verdict is None
        or str(adjudication.get("overall_verdict") or "") != derived_verdict
        or not prepared_by
        or not reviewed_by
        or prepared_by.casefold() == reviewed_by.casefold()
        or _timestamp(adjudication.get("reviewed_at")) is None
        or not str(adjudication.get("rationale") or "").strip()
    ):
        raise HeldOutEvidenceError("golden history adjudication is invalid")
    return {
        "path": path,
        "raw_sha256": raw_sha256,
        "record": record,
        "review_items": items,
    }


def _load_baseline_revisions(
    root: Path,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    revisions: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    seen_revision_ids: set[str] = set()
    for reference in manifest.get("baseline_revisions") or []:
        if not isinstance(reference, dict):
            raise HeldOutEvidenceError("golden history reference is malformed")
        path_value = str(reference.get("path") or "")
        raw_sha256 = str(reference.get("raw_sha256") or "")
        if path_value in seen_paths:
            raise HeldOutEvidenceError("golden history path is duplicated")
        seen_paths.add(path_value)
        path = _history_path(root, path_value)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise HeldOutEvidenceError("golden history is missing or invalid") from exc
        if _raw_hash(raw) != raw_sha256:
            raise HeldOutEvidenceError("golden history digest does not match")
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise HeldOutEvidenceError("golden history is missing or invalid") from exc
        if not isinstance(record, dict):
            raise HeldOutEvidenceError("golden history must be a JSON object")
        revision_id = str(record.get("revision_id") or "")
        if not revision_id or revision_id in seen_revision_ids:
            raise HeldOutEvidenceError("golden history revision id is missing or duplicated")
        seen_revision_ids.add(revision_id)
        revisions.append(_replay_baseline_revision(
            record,
            path=path_value,
            raw_sha256=raw_sha256,
        ))
    return revisions


def load_golden_held_out(
    golden_dir: Path | str = DEFAULT_GOLDEN_DIR,
) -> dict[str, Any]:
    """Load and deterministically rebuild the repository-owned held-out partition."""
    root = Path(golden_dir).expanduser().resolve()
    manifest = _read_json(root / "manifest.json", label="golden manifest")
    schema = _read_json(GOLDEN_MANIFEST_SCHEMA, label="golden manifest schema")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise HeldOutEvidenceError("golden manifest violates its schema")
    if (
        manifest.get("schema") != GOLDEN_MANIFEST_SCHEMA_VERSION
        or manifest.get("version") != GOLDEN_DATASET_VERSION
    ):
        raise HeldOutEvidenceError("golden manifest version is stale")
    curation = manifest.get("curation")
    if (
        not isinstance(curation, dict)
        or curation.get("review_contract_version")
        != HELD_OUT_REVIEW_CONTRACT_VERSION
    ):
        raise HeldOutEvidenceError("golden review contract version is stale")

    baseline_revisions = _load_baseline_revisions(root, manifest)

    files = dict(manifest.get("files") or {})
    inputs = _read_json(root / str(files.get("inputs") or ""), label="golden inputs")
    expected = _read_json(root / str(files.get("expected") or ""), label="golden expected")
    if inputs.get("schema") != "claim-ledger-golden-inputs/v1":
        raise HeldOutEvidenceError("golden inputs schema is stale")
    if expected.get("schema") != "claim-ledger-golden-expected/v1":
        raise HeldOutEvidenceError("golden expected schema is stale")

    declarations = list(manifest.get("cases") or [])
    input_cases = list(inputs.get("cases") or [])
    expected_cases = list(expected.get("cases") or [])
    declaration_by_id = {str(row.get("case_id") or ""): row for row in declarations}
    input_by_id = {str(row.get("case_id") or ""): row for row in input_cases}
    expected_by_id = {str(row.get("case_id") or ""): row for row in expected_cases}
    case_ids = [str(row.get("case_id") or "") for row in declarations]
    if (
        not all(case_ids)
        or len(case_ids) != len(set(case_ids))
        or set(case_ids) != set(input_by_id)
        or set(case_ids) != set(expected_by_id)
        or int(manifest.get("case_count") or -1) != len(case_ids)
    ):
        raise HeldOutEvidenceError("golden case sets are incomplete or inconsistent")

    held_out_ids = [
        case_id
        for case_id in case_ids
        if declaration_by_id[case_id].get("partition") == "held_out"
    ]
    if not held_out_ids or any(
        declaration_by_id[case_id].get("tuning_eligible") is not False
        for case_id in held_out_ids
    ):
        raise HeldOutEvidenceError("golden held-out partition is missing or tuning eligible")
    development_ids = [
        case_id
        for case_id in case_ids
        if declaration_by_id[case_id].get("partition") == "development"
    ]
    if any(
        declaration_by_id[case_id].get("tuning_eligible") is not True
        for case_id in development_ids
    ):
        raise HeldOutEvidenceError("golden development partition is not tuning eligible")
    partition_counts = dict(manifest.get("partition_counts") or {})
    if (
        int(partition_counts.get("held_out") or 0) != len(held_out_ids)
        or sum(int(value or 0) for value in partition_counts.values()) != len(case_ids)
    ):
        raise HeldOutEvidenceError("golden partition counts are inconsistent")

    review_items: list[dict[str, Any]] = []
    for case_id in held_out_ids:
        fixture_hash = _fixture_hash(
            manifest=manifest,
            declaration=declaration_by_id[case_id],
            input_case=input_by_id[case_id],
            expected_case=expected_by_id[case_id],
        )
        review_items.extend(_rebuild_case(
            input_by_id[case_id],
            expected_by_id[case_id],
            fixture_hash,
            replay_catalog_version=GOLDEN_CATALOG_VERSIONS.get(
                str(manifest.get("version") or "")
            ),
        ))
    return {
        "manifest": manifest,
        "inputs": inputs,
        "expected": expected,
        "held_out_case_ids": held_out_ids,
        "review_items": review_items,
        "baseline_revisions": baseline_revisions,
    }


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def summarize_held_out_review(dataset: dict[str, Any]) -> dict[str, Any]:
    """Reduce held-out curation to path-free, wording-free gate evidence."""
    manifest = dict(dataset.get("manifest") or {})
    curation = dict(manifest.get("curation") or {})
    items = list(dataset.get("review_items") or [])
    baseline_revisions = list(dataset.get("baseline_revisions") or [])
    historical_adjudications = [
        record
        for revision in baseline_revisions
        if isinstance(revision, dict)
        for record in [dict(revision.get("record") or {}).get("adjudication")]
        if isinstance(record, dict)
    ]
    historical_disagreement_count = sum(
        _overall_verdict(row.get("dimension_verdicts")) == "disagree"
        for row in historical_adjudications
    )
    current_by_identity = {
        (str(item["case_id"]), str(item["claim_id"])): item
        for item in items
    }
    adjudications = [
        dict(row) for row in (curation.get("held_out_adjudications") or [])
        if isinstance(row, dict)
    ]
    seen: set[tuple[str, str]] = set()
    duplicate_count = 0
    stale_count = 0
    invalid_count = 0
    disagreement_count = 0
    followup_count = 0
    approved: set[tuple[str, str]] = set()
    current_bindings: set[tuple[str, str]] = set()
    reviewed_cases: set[str] = set()
    for row in adjudications:
        identity = (str(row.get("case_id") or ""), str(row.get("claim_id") or ""))
        if identity in seen:
            duplicate_count += 1
            continue
        seen.add(identity)
        current = current_by_identity.get(identity)
        if current is None or (
            str(row.get("claim_hash") or "") != str(current.get("claim_hash") or "")
            or str(row.get("fixture_hash") or "") != str(current.get("fixture_hash") or "")
        ):
            stale_count += 1
            continue
        current_bindings.add(identity)
        reviewed_cases.add(identity[0])
        expected_fields = {
            "case_id",
            "claim_id",
            "claim_hash",
            "fixture_hash",
            "dimension_verdicts",
            "rationale",
        }
        verdict = _overall_verdict(row.get("dimension_verdicts"))
        if (
            set(row) != expected_fields
            or verdict is None
            or not str(row.get("rationale") or "").strip()
        ):
            invalid_count += 1
            continue
        if verdict == "agree":
            approved.add(identity)
        elif verdict == "disagree":
            disagreement_count += 1
        elif verdict == "needs_followup":
            followup_count += 1
        else:
            invalid_count += 1

    expected_identities = set(current_by_identity)
    missing_count = len(expected_identities - seen)
    extra_count = len(seen - expected_identities)
    prepared_by = str(curation.get("prepared_by") or "").strip()
    reviewed_by = str(curation.get("reviewed_by") or "").strip()
    reviewer_independent = bool(
        reviewed_by
        and prepared_by
        and reviewed_by.casefold() != prepared_by.casefold()
    )
    review_status = str(curation.get("human_review_status") or "pending")
    metadata_valid = bool(reviewer_independent and _timestamp(curation.get("reviewed_at")))
    binding_invalid = any((
        duplicate_count,
        stale_count,
        invalid_count,
        missing_count,
        extra_count,
    ))
    if review_status != "reviewed":
        evidence_status = "pending"
    elif not metadata_valid or binding_invalid:
        evidence_status = "invalid"
    elif disagreement_count or followup_count:
        evidence_status = "not_approved"
    elif approved != expected_identities:
        evidence_status = "invalid"
    else:
        evidence_status = "complete"
    return {
        "artifact_status": "valid",
        "error_code": None,
        "dataset_id": str(manifest.get("dataset_id") or "") or None,
        "dataset_version": str(manifest.get("version") or "") or None,
        "human_review_status": (
            "reviewed" if review_status == "reviewed" else "pending"
        ),
        "evidence_status": evidence_status,
        "held_out_case_count": len(dataset.get("held_out_case_ids") or []),
        "held_out_claim_count": len(items),
        "reviewed_case_count": len(reviewed_cases),
        "reviewed_claim_count": len(current_bindings),
        "approved_claim_count": len(approved),
        "stale_adjudication_count": stale_count,
        "duplicate_adjudication_count": duplicate_count,
        "missing_adjudication_count": missing_count,
        "extra_adjudication_count": extra_count,
        "invalid_adjudication_count": invalid_count,
        "disagreement_count": disagreement_count,
        "followup_count": followup_count,
        "historical_review_count": len(historical_adjudications),
        "historical_disagreement_count": historical_disagreement_count,
        "baseline_revision_count": len(baseline_revisions),
    }


def invalid_held_out_summary(error_code: str) -> dict[str, Any]:
    return {
        "artifact_status": "invalid",
        "error_code": error_code,
        "dataset_id": None,
        "dataset_version": None,
        "human_review_status": "pending",
        "evidence_status": "invalid",
        "held_out_case_count": 0,
        "held_out_claim_count": 0,
        "reviewed_case_count": 0,
        "reviewed_claim_count": 0,
        "approved_claim_count": 0,
        "stale_adjudication_count": 0,
        "duplicate_adjudication_count": 0,
        "missing_adjudication_count": 0,
        "extra_adjudication_count": 0,
        "invalid_adjudication_count": 0,
        "disagreement_count": 0,
        "followup_count": 0,
        "historical_review_count": 0,
        "historical_disagreement_count": 0,
        "baseline_revision_count": 0,
    }
