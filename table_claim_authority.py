"""Read-only projection of Claim Ledger structural authority onto table cells."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any


TABLE_CLAIM_AUTHORITY_VERSION = "table-claim-authority-v1"


def _cell_id_from_exclusion(exclusion: Any) -> str:
    if not isinstance(exclusion, dict):
        return ""
    evidence = exclusion.get("evidence")
    if not isinstance(evidence, dict):
        return ""
    return str(evidence.get("table_cell_id") or "")


def _claim_cell_id(claim: dict[str, Any]) -> str:
    locator = claim.get("locator")
    if isinstance(locator, dict):
        value = str(locator.get("table_cell_id") or "")
        if value:
            return value
    return _cell_id_from_exclusion(claim.get("exclusion"))


def build_table_claim_authority_projection(
    *,
    catalog: list[dict[str, Any]],
    generation_meta: dict[str, Any],
    candidate_decisions: list[dict[str, Any]],
    structural_overrides: list[dict[str, Any]],
    pending_operations: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return the current terminal/pending claim state keyed by table cell ID."""
    from claim_structural_overrides import CELL_REVIEW_STRUCTURAL_REASONS

    document_generation_id = str(
        generation_meta.get("document_generation_id") or ""
    )
    catalog_generation_id = str(
        generation_meta.get("catalog_generation_id") or ""
    )
    claims_by_identity = {
        (str(row.get("claim_id") or ""), str(row.get("claim_hash") or "")): row
        for row in catalog
    }
    decisions_by_identity = {
        (str(row.get("claim_id") or ""), str(row.get("claim_hash") or "")): row
        for row in candidate_decisions
        if str(row.get("document_generation_id") or "") == document_generation_id
        and str(row.get("catalog_generation_id") or "") == catalog_generation_id
    }
    overrides_by_identity = {
        (str(row.get("claim_id") or ""), str(row.get("claim_hash") or "")): row
        for row in structural_overrides
    }
    projection: dict[str, dict[str, Any]] = {}

    for identity, claim in claims_by_identity.items():
        claim_id, claim_hash = identity
        exclusion = claim.get("exclusion")
        reason = (
            str(exclusion.get("reason") or "")
            if isinstance(exclusion, dict)
            else ""
        )
        override = overrides_by_identity.get(identity)
        decision = decisions_by_identity.get(identity)
        cell_id = _claim_cell_id(claim)
        if not cell_id and override is not None:
            cell_id = _cell_id_from_exclusion(override.get("original_exclusion"))
        if not cell_id:
            continue

        status = ""
        authority: dict[str, Any] = {
            "version": TABLE_CLAIM_AUTHORITY_VERSION,
            "claim_id": claim_id,
            "claim_hash": claim_hash,
            "document_generation_id": document_generation_id,
            "catalog_generation_id": catalog_generation_id,
        }
        if (
            override is not None
            and claim.get("eligibility") == "claim"
            and claim.get("exclusion") is None
        ):
            status = "promoted"
            authority.update({
                "override_id": str(override.get("override_id") or ""),
                "override_hash": str(override.get("override_hash") or ""),
                "prior_structural_reason": str(
                    override.get("prior_structural_reason") or ""
                ),
            })
        elif decision is not None:
            status = "confirmed_excluded"
            authority.update({
                "decision_id": str(decision.get("decision_id") or ""),
                "decision_hash": str(decision.get("decision_hash") or ""),
                "prior_structural_reason": str(
                    decision.get("prior_structural_reason") or reason
                ),
            })
        elif claim_id in pending_operations:
            status = "promotion_pending"
            authority["operation"] = dict(pending_operations[claim_id])
            authority["prior_structural_reason"] = reason
        elif claim.get("eligibility") == "excluded" and reason in CELL_REVIEW_STRUCTURAL_REASONS:
            status = "pending_review"
            authority["prior_structural_reason"] = reason
        if not status:
            continue
        authority["status"] = status
        if cell_id in projection and projection[cell_id] != authority:
            raise ValueError(
                f"multiple current claim structural authorities for table cell {cell_id}"
            )
        projection[cell_id] = authority
    return projection


def load_table_claim_authority_projection(
    out_dir: Path | str,
) -> dict[str, dict[str, Any]]:
    """Load current committed claim authority without performing recovery writes."""
    from claim_artifacts import (
        CLAIM_EFFECTIVE_META,
        CLAIM_GENERATION_META,
        claim_artifact_path,
        load_committed_effective_snapshot_cached,
    )
    from claim_structural_operations import pending_structural_operations
    from claim_structural_overrides import (
        read_structural_candidate_decisions,
        read_structural_overrides,
    )

    root = Path(out_dir).expanduser().resolve()
    generation_meta_path = claim_artifact_path(root, CLAIM_GENERATION_META)
    effective_meta_path = claim_artifact_path(root, CLAIM_EFFECTIVE_META)
    # B-track extraction predates the claim ledger and legitimately has no
    # structural snapshot. Treat that absence as an empty projection; once
    # either anchor exists, a missing counterpart is a corrupt/incomplete
    # claim artifact and must still fail closed in the loader below.
    if not generation_meta_path.is_file() and not effective_meta_path.is_file():
        return {}
    if generation_meta_path.is_file() != effective_meta_path.is_file():
        raise FileNotFoundError(
            "claim authority snapshot requires both generation and effective metadata"
        )
    # 2026-08-14 性能：GET /table-reviews 每次轮询都全文重读 claim 快照；切换到
    # stat 签名缓存版（写路径改动输入文件 → 缓存自然失效）。本函数及其消费方对
    # snapshot 只读（.get/迭代），符合共享只读契约。
    snapshot = load_committed_effective_snapshot_cached(root, require_v2=False)
    return build_table_claim_authority_projection(
        catalog=list(snapshot.get("catalog") or []),
        generation_meta=dict(snapshot.get("generation_meta") or {}),
        candidate_decisions=read_structural_candidate_decisions(root).rows,
        structural_overrides=read_structural_overrides(root).rows,
        pending_operations=pending_structural_operations(root),
    )


def project_table_dispositions(
    dispositions: list[dict[str, Any]],
    cells: list[dict[str, Any]],
    authority_by_cell: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Overlay claim terminal state while leaving deterministic source rows intact."""
    cells_by_id = {
        str(cell.get("cell_id") or ""): cell
        for cell in cells
        if str(cell.get("cell_id") or "")
    }
    projected: list[dict[str, Any]] = []
    for original in dispositions:
        row = dict(original)
        cell_id = str(row.get("cell_id") or "")
        authority = authority_by_cell.get(cell_id)
        if authority is not None:
            row["claim_authority"] = dict(authority)
        if str(row.get("disposition") or "") != "review" or authority is None:
            projected.append(row)
            continue
        status = str(authority.get("status") or "")
        if status == "promoted":
            leaf_kind = str((cells_by_id.get(cell_id) or {}).get("leaf_kind") or "")
            row["disposition"] = "composite" if leaf_kind == "row" else "target"
            row["confidence"] = "high"
            row["decision_source"] = "claim_authority"
            row["decision_version"] = TABLE_CLAIM_AUTHORITY_VERSION
            row["evidence"] = [
                *(row.get("evidence") or []),
                "claim_structural_override",
            ]
        elif status == "confirmed_excluded":
            row["disposition"] = "excluded"
            row["confidence"] = "high"
            row["decision_source"] = "claim_authority"
            row["decision_version"] = TABLE_CLAIM_AUTHORITY_VERSION
            row["exclusion_reason"] = str(
                authority.get("prior_structural_reason") or "confirmed_exclusion"
            )
            row["evidence"] = [
                *(row.get("evidence") or []),
                "claim_structural_exclusion_confirmed",
            ]
        projected.append(row)

    pending_by_table = Counter(
        str(row.get("table_id") or "")
        for row in projected
        if str(row.get("disposition") or "") == "review"
    )
    for row in projected:
        row["structure_review_status"] = (
            "pending" if pending_by_table[str(row.get("table_id") or "")] else "ready"
        )
    return projected
