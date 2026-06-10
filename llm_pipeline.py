from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from domain_pack import load_domain_pack
from llm_review_schema import validate_llm_review_results
from review_state import RequirementReviewState


@dataclass(frozen=True)
class ReviewPipeline:
    pipeline_id: str
    operations: list[dict[str, Any]]
    model_routing: dict[str, Any]
    risk_policy: dict[str, Any]


def load_review_pipeline(path: Path) -> ReviewPipeline:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ReviewPipeline(
        pipeline_id=str(payload.get("pipeline_id") or path.stem),
        operations=list(payload.get("operations", [])),
        model_routing=dict(payload.get("model_routing", {})),
        risk_policy=dict(payload.get("risk_policy", {})),
    )


def merge_review_policy(pipeline: ReviewPipeline, domain_pack_path: Path | None) -> ReviewPipeline:
    if domain_pack_path is None:
        return pipeline
    pack = load_domain_pack(domain_pack_path)
    review_policy = dict(pack.payload.get("review_policy") or {})
    merged_risk_policy = dict(pipeline.risk_policy)
    for key in ("mandatory_review_types", "high_risk_types"):
        values = [
            *list(merged_risk_policy.get(key, [])),
            *list(review_policy.get(key, [])),
        ]
        merged_risk_policy[key] = list(dict.fromkeys(str(value) for value in values))
    if "low_confidence_threshold" in review_policy:
        merged_risk_policy["low_confidence_threshold"] = review_policy["low_confidence_threshold"]
    return ReviewPipeline(
        pipeline_id=pipeline.pipeline_id,
        operations=pipeline.operations,
        model_routing=pipeline.model_routing,
        risk_policy=merged_risk_policy,
    )


def classify_review_risk(requirement: dict[str, Any], pipeline: ReviewPipeline) -> str:
    mandatory_review_types = set(pipeline.risk_policy.get("mandatory_review_types", []))
    high_risk_types = set(pipeline.risk_policy.get("high_risk_types", []))
    threshold = float(pipeline.risk_policy.get("low_confidence_threshold", 0.75))
    if requirement.get("requirement_type") in mandatory_review_types:
        return "mandatory_review"
    if requirement.get("requirement_type") in high_risk_types:
        return "high_risk"
    if float(requirement.get("confidence", 0)) < threshold:
        return "high_risk"
    if requirement.get("ambiguity"):
        return "high_risk"
    return "low_risk"


def requirement_identity(requirement: dict[str, Any]) -> str:
    return str(requirement.get("stable_req_id") or requirement.get("req_id") or requirement.get("source_id") or "UNKNOWN")


def build_stub_review(requirement: dict[str, Any], pipeline: ReviewPipeline) -> dict[str, Any]:
    risk = classify_review_risk(requirement, pipeline)
    needs_expert = risk in {"high_risk", "mandatory_review"}
    decision = "needs_expert" if needs_expert else "accept"
    requirement_id = requirement_identity(requirement)
    route_key = "high_risk" if risk == "mandatory_review" else risk
    return {
        "task_id": f"REVIEW-{requirement_id}",
        "requirement_id": requirement_id,
        "req_id": requirement.get("req_id"),
        "stable_req_id": requirement.get("stable_req_id"),
        "source_refs": requirement.get("source_refs", []),
        "risk": risk,
        "decision": decision,
        "revised_requirement": requirement.get("requirement", ""),
        "review_notes": [f"Stub review routed to {risk}."],
        "expert_questions": requirement.get("review_questions", []) if needs_expert else [],
        "confidence": 0.5 if needs_expert else 0.8,
        "model_route": pipeline.model_routing.get(route_key, {}),
    }


def review_requirements(
    requirements: list[dict[str, Any]],
    pipeline: ReviewPipeline,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reviews: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    for requirement in requirements:
        review = build_stub_review(requirement, pipeline)
        reviews.append(review)
        state = RequirementReviewState(requirement_identity(requirement))
        state.metadata.update(
            {
                "req_id": requirement.get("req_id"),
                "stable_req_id": requirement.get("stable_req_id"),
                "source_id": requirement.get("source_id"),
                "requirement_type": requirement.get("requirement_type"),
            }
        )
        state.transition("llm_reviewed", actor="llm_pipeline", reason=f"decision={review['decision']}")
        if review["decision"] == "needs_expert":
            state.transition("expert_pending", actor="llm_pipeline", reason=f"risk={review['risk']}")
        elif review["decision"] == "accept":
            state.transition("accepted", actor="llm_pipeline", reason="low-risk stub acceptance")
        else:
            state.transition("flagged", actor="llm_pipeline", reason=f"decision={review['decision']}")
        states.append(state.to_dict())
    return reviews, states


def assert_valid_review_results(rows: list[dict[str, Any]]) -> None:
    issues = validate_llm_review_results(rows)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        message = "; ".join(f"{issue.path}: {issue.message}" for issue in errors[:5])
        raise ValueError(f"invalid llm review results: {message}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def append_review_state_events(path: Path, states: list[dict[str, Any]]) -> int:
    count = 0
    with path.open("a", encoding="utf-8", newline="\n") as f:
        for state in states:
            metadata = dict(state.get("metadata") or {})
            for event in state.get("history", []):
                row = {
                    "requirement_id": state.get("requirement_id"),
                    "req_id": metadata.get("req_id"),
                    "stable_req_id": metadata.get("stable_req_id"),
                    "status_after": event.get("to_status"),
                    "current_status": state.get("status"),
                    **event,
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                count += 1
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local requirement review pipeline over atomizer output.")
    parser.add_argument("--out", type=Path, required=True, help="Atomizer output directory containing atomic_requirements.jsonl")
    parser.add_argument(
        "--pipeline",
        type=Path,
        default=Path("llm_agents/review_pipeline.yaml"),
        help="Review pipeline YAML",
    )
    parser.add_argument(
        "--domain-pack",
        type=Path,
        default=Path("domain_packs/dlms_cosem/pack.yaml"),
        help="Optional domain pack whose review_policy is merged into runtime risk policy",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional max requirement count for trial runs")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = args.out.expanduser().resolve()
    pipeline_path = args.pipeline.expanduser().resolve()
    requirements = read_jsonl(out_dir / "atomic_requirements.jsonl")
    if args.limit > 0:
        requirements = requirements[: args.limit]
    domain_pack_path = args.domain_pack.expanduser().resolve() if args.domain_pack else None
    pipeline = merge_review_policy(load_review_pipeline(pipeline_path), domain_pack_path)
    reviews, states = review_requirements(requirements, pipeline)
    assert_valid_review_results(reviews)
    write_jsonl(out_dir / "llm_review_results.jsonl", reviews)
    write_jsonl(out_dir / "review_states.jsonl", states)
    event_count = append_review_state_events(out_dir / "review_state_events.jsonl", states)
    print(
        json.dumps(
            {
                "pipeline_id": pipeline.pipeline_id,
                "out": str(out_dir),
                "requirements": len(requirements),
                "reviews": len(reviews),
                "review_state_events": event_count,
                "expert_pending": sum(1 for state in states if state.get("status") == "expert_pending"),
                "accepted": sum(1 for state in states if state.get("status") == "accepted"),
                "files": {
                    "llm_review_results": "llm_review_results.jsonl",
                    "review_states": "review_states.jsonl",
                    "review_state_events": "review_state_events.jsonl",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
