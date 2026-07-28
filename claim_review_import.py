"""Validate and import an offline Phase 0 claim-review decision export."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import tempfile
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from jsonschema import Draft202012Validator, FormatChecker

from claim_acceptance import ClaimAcceptanceInputError, load_input_manifest
from claim_artifacts import (
    ClaimArtifactError,
    atomic_write_text,
    claim_publication_lock,
    paths_alias,
)
from claim_held_out import (
    HeldOutEvidenceError,
    load_golden_held_out,
    summarize_held_out_review,
)
from claim_review_packet import (
    REVIEW_DECISIONS_SCHEMA as REVIEW_DECISIONS_WIRE_SCHEMA,
    ReviewPacketError,
    build_review_packet,
)


REVIEW_IMPORT_VERSION = "claim-shadow-review-import-v1"
REVIEW_DECISIONS_SCHEMA_VERSION = REVIEW_DECISIONS_WIRE_SCHEMA
ENVELOPE_SCHEMA_VERSION = "1.0"
ROOT = Path(__file__).resolve().parent
REVIEW_DECISIONS_SCHEMA_PATH = ROOT / "schemas" / "claim_shadow_review_decisions.schema.json"


class ReviewImportError(ValueError):
    """Exported decisions cannot be bound to the current review evidence."""


def _read_json(path: Path | str, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewImportError(f"{label} is missing or invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ReviewImportError(f"{label} must be a JSON object")
    return payload


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def load_review_decisions(path: Path | str) -> dict[str, Any]:
    payload = _read_json(path, label="review decisions")
    try:
        schema = _read_json(REVIEW_DECISIONS_SCHEMA_PATH, label="review decisions schema")
    except ReviewImportError as exc:
        raise ReviewImportError("review decisions schema is unavailable") from exc
    errors = sorted(
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        location = ".".join(str(value) for value in errors[0].absolute_path) or "$"
        raise ReviewImportError(f"review decisions schema violation at {location}")
    if _timestamp(payload.get("reviewed_at")) is None:
        raise ReviewImportError("review time must include a timezone")
    return payload


def _shadow_binding(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(row.get(key) or "") for key in (
        "run_id",
        "claim_id",
        "claim_hash",
        "review_evidence_fingerprint",
        "ledger_resolution",
        "category",
    ))


def _held_out_binding(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(row.get(key) or "") for key in (
        "case_id",
        "claim_id",
        "claim_hash",
        "fixture_hash",
    ))


def _exact_bindings(
    actual: list[dict[str, Any]],
    expected: list[dict[str, Any]],
    *,
    identity,
    label: str,
) -> None:
    actual_ids = [identity(row) for row in actual]
    expected_ids = [identity(row) for row in expected]
    if len(expected_ids) != len(set(expected_ids)):
        raise ReviewImportError(f"current review packet contains duplicate {label}")
    if len(actual_ids) != len(set(actual_ids)):
        raise ReviewImportError(f"review decisions contain duplicate {label}")
    if set(actual_ids) != set(expected_ids):
        raise ReviewImportError(f"review decisions have missing, extra, or stale {label}")


def _reject_overwrite(current: dict[str, Any], candidate: dict[str, Any], *, label: str) -> None:
    if str(current.get("human_review_status") or "pending") != "reviewed":
        return
    current_projection = {
        "reviewed_by": current.get("reviewed_by"),
        "reviewed_at": current.get("reviewed_at"),
        "adjudications": current.get(
            "adjudications",
            current.get("held_out_adjudications"),
        ),
    }
    candidate_projection = {
        "reviewed_by": candidate.get("reviewed_by"),
        "reviewed_at": candidate.get("reviewed_at"),
        "adjudications": candidate.get(
            "adjudications",
            candidate.get("held_out_adjudications"),
        ),
    }
    if current_projection != candidate_projection:
        raise ReviewImportError(f"{label} already contains a different completed review")


def prepare_review_updates(
    input_manifest: dict[str, Any],
    decisions: dict[str, Any],
    packet: dict[str, Any],
    held_out: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    template = dict(packet.get("decision_template") or {})
    if (
        decisions.get("schema") != REVIEW_DECISIONS_SCHEMA_VERSION
        or str(decisions.get("dataset_id") or "")
        != str(input_manifest.get("dataset_id") or "")
        or str(template.get("dataset_id") or "")
        != str(input_manifest.get("dataset_id") or "")
    ):
        raise ReviewImportError("review decisions dataset binding is stale")

    reviewed_by = str(decisions.get("reviewed_by") or "").strip()
    reviewed_at = str(decisions.get("reviewed_at") or "").strip()
    if not reviewed_by or _timestamp(reviewed_at) is None:
        raise ReviewImportError("review metadata is incomplete")

    shadow = [dict(row) for row in decisions.get("shadow_adjudications") or []]
    expected_shadow = [dict(row) for row in template.get("shadow_adjudications") or []]
    _exact_bindings(
        shadow,
        expected_shadow,
        identity=_shadow_binding,
        label="shadow adjudications",
    )
    for row in shadow:
        if (
            str(row.get("verdict") or "") != "agree"
            and not str(row.get("rationale") or "").strip()
        ):
            raise ReviewImportError(
                "disagree and needs-followup shadow decisions require a rationale"
            )

    golden = dict(decisions.get("golden_held_out") or {})
    expected_golden = dict(template.get("golden_held_out") or {})
    manifest = dict(held_out.get("manifest") or {})
    if (
        str(golden.get("dataset_id") or "") != str(manifest.get("dataset_id") or "")
        or str(golden.get("dataset_version") or "") != str(manifest.get("version") or "")
        or str(golden.get("dataset_id") or "") != str(expected_golden.get("dataset_id") or "")
        or str(golden.get("dataset_version") or "")
        != str(expected_golden.get("dataset_version") or "")
    ):
        raise ReviewImportError("held-out dataset binding is stale")
    held_out_adjudications = [
        dict(row) for row in golden.get("adjudications") or []
    ]
    expected_held_out = [
        dict(row) for row in expected_golden.get("adjudications") or []
    ]
    _exact_bindings(
        held_out_adjudications,
        expected_held_out,
        identity=_held_out_binding,
        label="held-out adjudications",
    )

    prepared_by = str(dict(manifest.get("curation") or {}).get("prepared_by") or "").strip()
    if prepared_by and reviewed_by.casefold() == prepared_by.casefold():
        raise ReviewImportError("held-out reviewer must be independent from the preparer")

    reviewed_input = copy.deepcopy(input_manifest)
    input_curation = reviewed_input["curation"]
    input_candidate = {
        **input_curation,
        "human_review_status": "reviewed",
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at,
        "adjudications": shadow,
    }
    _reject_overwrite(input_curation, input_candidate, label="acceptance input")
    reviewed_input["curation"] = input_candidate

    reviewed_manifest = copy.deepcopy(manifest)
    manifest_curation = reviewed_manifest["curation"]
    manifest_candidate = {
        **manifest_curation,
        "human_review_status": "reviewed",
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at,
        "held_out_adjudications": held_out_adjudications,
    }
    _reject_overwrite(manifest_curation, manifest_candidate, label="golden manifest")
    reviewed_manifest["curation"] = manifest_candidate

    held_out_candidate = {**held_out, "manifest": reviewed_manifest}
    held_out_summary = summarize_held_out_review(held_out_candidate)
    if held_out_summary.get("evidence_status") in {"invalid", "pending"}:
        raise ReviewImportError("held-out adjudications are incomplete or invalid")
    return reviewed_input, reviewed_manifest, held_out_summary


def _pretty_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _review_import_lock_root(golden_manifest: Path) -> Path:
    normalized = os.path.normcase(str(golden_manifest))
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return Path(tempfile.gettempdir()) / "requirement-atomizer-review-import-locks" / digest


def _review_import_lock_roots(golden_manifest: Path, output: Path) -> tuple[Path, ...]:
    return tuple(sorted(
        {
            _review_import_lock_root(golden_manifest),
            _review_import_lock_root(output),
        },
        key=lambda path: str(path),
    ))


def _is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _packet_from_manifest_snapshot(input_manifest: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="requirement-atomizer-review-input-") as root:
        snapshot = Path(root) / "acceptance-input.json"
        snapshot.write_text(_pretty_json(input_manifest), encoding="utf-8")
        return build_review_packet(snapshot)


def import_review_decisions(
    input_path: Path | str,
    decisions_path: Path | str,
    output_path: Path | str,
    golden_manifest_path: Path | str,
) -> dict[str, Any]:
    source = Path(input_path).expanduser().resolve()
    decisions_source = Path(decisions_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    golden_manifest = Path(golden_manifest_path).expanduser().resolve()
    if paths_alias(source, output):
        raise ReviewImportError("reviewed acceptance output must differ from pending input")
    if paths_alias(decisions_source, output):
        raise ReviewImportError("reviewed acceptance output must differ from review decisions")
    if golden_manifest.name != "manifest.json":
        raise ReviewImportError("golden manifest path must name manifest.json")
    if _is_within(output, golden_manifest.parent) or paths_alias(output, golden_manifest):
        raise ReviewImportError("reviewed acceptance output must be outside the golden corpus")

    with ExitStack() as locks:
        for lock_root in _review_import_lock_roots(golden_manifest, output):
            locks.enter_context(claim_publication_lock(lock_root))
        input_manifest = load_input_manifest(source)
        decisions = load_review_decisions(decisions_source)
        packet = _packet_from_manifest_snapshot(input_manifest)
        held_out = load_golden_held_out(golden_manifest.parent)
        reviewed_input, reviewed_manifest, held_out_summary = prepare_review_updates(
            input_manifest,
            decisions,
            packet,
            held_out,
        )
        if output.exists():
            try:
                existing_output = load_input_manifest(output)
            except ClaimAcceptanceInputError as exc:
                raise ReviewImportError(
                    "reviewed acceptance output already exists but is invalid"
                ) from exc
            _reject_overwrite(
                dict(existing_output["curation"]),
                dict(reviewed_input["curation"]),
                label="reviewed acceptance output",
            )
            if existing_output != reviewed_input:
                raise ReviewImportError(
                    "reviewed acceptance output already contains different content"
                )

        # Both candidates are fully validated before either authoritative file is replaced.
        atomic_write_text(output, _pretty_json(reviewed_input))
        load_input_manifest(output)
        atomic_write_text(golden_manifest, _pretty_json(reviewed_manifest))
        load_golden_held_out(golden_manifest.parent)
    return {
        "schema": "claim-shadow-review-import-result/v1",
        "importer_version": REVIEW_IMPORT_VERSION,
        "dataset_id": str(reviewed_input["dataset_id"]),
        "reviewed_by": str(decisions["reviewed_by"]),
        "reviewed_at": str(decisions["reviewed_at"]),
        "shadow_adjudication_count": len(decisions["shadow_adjudications"]),
        "held_out_adjudication_count": len(
            decisions["golden_held_out"]["adjudications"]
        ),
        "held_out_evidence_status": str(held_out_summary["evidence_status"]),
        "reviewed_input": str(output),
        "golden_manifest": str(golden_manifest),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and import Phase 0 claim review decisions."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--golden-manifest", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        result = import_review_decisions(
            args.input,
            args.decisions,
            args.output,
            args.golden_manifest,
        )
        envelope = {
            "tool": "requirement-atomizer",
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "command": "claim-shadow-review-import",
            "ok": True,
            "result": result,
        }
        code = 0
    except (ReviewImportError, ClaimAcceptanceInputError) as exc:
        envelope = {
            "tool": "requirement-atomizer",
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "command": "claim-shadow-review-import",
            "ok": False,
            "error": {"type": "input_error", "message": str(exc)},
        }
        code = 2
    except (ReviewPacketError, HeldOutEvidenceError, ClaimArtifactError, TimeoutError):
        envelope = {
            "tool": "requirement-atomizer",
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "command": "claim-shadow-review-import",
            "ok": False,
            "error": {
                "type": "artifact_error",
                "message": "Review evidence is missing, stale, or invalid.",
            },
        }
        code = 3
    except OSError:
        envelope = {
            "tool": "requirement-atomizer",
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "command": "claim-shadow-review-import",
            "ok": False,
            "error": {
                "type": "io_error",
                "message": "Review decisions could not be written atomically.",
            },
        }
        code = 3
    except Exception:  # pragma: no cover - final CLI privacy boundary
        envelope = {
            "tool": "requirement-atomizer",
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "command": "claim-shadow-review-import",
            "ok": False,
            "error": {
                "type": "unexpected_error",
                "message": "Review decision import failed unexpectedly.",
            },
        }
        code = 1
    print(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
