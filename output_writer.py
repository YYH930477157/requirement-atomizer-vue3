from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_quality_report(
    blocks: list[dict[str, Any]],
    table_items: list[dict[str, Any]],
    atomic_candidates: list[dict[str, Any]],
    llm_tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    type_counts = Counter(row.get("requirement_type", "unknown") for row in atomic_candidates)
    source_counts = Counter(row.get("source_type", "unknown") for row in atomic_candidates)
    verification_counts = Counter(row.get("verification_method", "unknown") for row in atomic_candidates)
    domain_counts = Counter(row.get("domain", "unknown") for row in atomic_candidates)
    ambiguous = [row for row in atomic_candidates if row.get("ambiguity")]
    low_confidence = [row for row in atomic_candidates if float(row.get("confidence", 0)) < 0.75]

    table_item_ids_with_candidates = {
        ref
        for row in atomic_candidates
        for ref in row.get("source_refs", [])
        if str(ref).startswith("TBL-")
    }
    body_table_items = [item for item in table_items if item.get("doc_region") == "body"]
    body_tables_with_domain = [item for item in body_table_items if item.get("domain_tags")]

    return {
        "quality_report_version": "1.0",
        "counts": {
            "blocks": len(blocks),
            "table_items": len(table_items),
            "body_table_items": len(body_table_items),
            "atomic_requirements": len(atomic_candidates),
            "llm_tasks": len(llm_tasks),
            "ambiguous_atomic_requirements": len(ambiguous),
            "low_confidence_atomic_requirements": len(low_confidence),
            "body_table_items_with_domain_tags": len(body_tables_with_domain),
            "table_items_with_atomic_candidates": len(table_item_ids_with_candidates),
        },
        "coverage": {
            "body_table_candidate_ratio": ratio(len(table_item_ids_with_candidates), len(body_table_items)),
            "domain_table_candidate_ratio": ratio(len(table_item_ids_with_candidates), len(body_tables_with_domain)),
        },
        "requirement_type_counts": dict(type_counts.most_common()),
        "source_type_counts": dict(source_counts.most_common()),
        "verification_method_counts": dict(verification_counts.most_common()),
        "domain_counts": dict(domain_counts.most_common()),
        "review_queues": {
            "ambiguous": [compact_requirement(row) for row in ambiguous[:50]],
            "low_confidence": [compact_requirement(row) for row in low_confidence[:50]],
        },
    }


def ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def compact_requirement(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "req_id": row.get("req_id"),
        "stable_req_id": row.get("stable_req_id"),
        "requirement_type": row.get("requirement_type"),
        "source_id": row.get("source_id"),
        "object": row.get("object"),
        "requirement": row.get("requirement"),
        "confidence": row.get("confidence"),
        "review_questions": row.get("review_questions", []),
    }


def write_summary(
    path: Path,
    manifest: dict[str, Any],
    domain_counts: Counter[str],
    kb_counts: Counter[str],
    quality_report: dict[str, Any] | None = None,
) -> None:
    lines = [
        "# Requirement Atomizer Summary",
        "",
        f"- Input: `{manifest['input']}`",
        f"- Generated at: `{manifest['generated_at']}`",
        f"- Blocks: `{manifest['counts']['blocks']}`",
        f"- Chunks: `{manifest['counts']['chunks']}`",
        f"- Table items: `{manifest['counts']['table_items']}`",
        f"- Atomic requirement candidates: `{manifest['counts'].get('atomic_requirements', 0)}`",
        f"- LLM tasks: `{manifest['counts']['llm_tasks']}`",
        "",
        "## Top Domain Tags",
        "",
    ]
    for tag, count in domain_counts.most_common(20):
        lines.append(f"- `{tag}`: {count}")
    if kb_counts:
        lines.extend(["", "## Top Knowledge Base Matches", ""])
        for name, count in kb_counts.most_common(30):
            lines.append(f"- `{name}`: {count}")
    if quality_report:
        lines.extend(["", "## Atomic Requirement Types", ""])
        for name, count in list(quality_report.get("requirement_type_counts", {}).items())[:25]:
            lines.append(f"- `{name}`: {count}")
        lines.extend(
            [
                "",
                "## Quality Signals",
                "",
                f"- Ambiguous atomic requirements: `{quality_report['counts']['ambiguous_atomic_requirements']}`",
                f"- Low-confidence atomic requirements: `{quality_report['counts']['low_confidence_atomic_requirements']}`",
                f"- Body table candidate ratio: `{quality_report['coverage']['body_table_candidate_ratio']}`",
                f"- Domain table candidate ratio: `{quality_report['coverage']['domain_table_candidate_ratio']}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Next Step",
            "",
            "Review `atomic_requirements.jsonl` first. Then send `llm_tasks.jsonl` to your model worker for correction, gap-finding, and enrichment while keeping `source_id` plus `source_refs` for traceability.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
