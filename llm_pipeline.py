from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

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


def classify_review_risk(requirement: dict[str, Any], pipeline: ReviewPipeline) -> str:
    high_risk_types = set(pipeline.risk_policy.get("high_risk_types", []))
    threshold = float(pipeline.risk_policy.get("low_confidence_threshold", 0.75))
    if requirement.get("requirement_type") in high_risk_types:
        return "high_risk"
    if float(requirement.get("confidence", 0)) < threshold:
        return "high_risk"
    if requirement.get("ambiguity"):
        return "high_risk"
    return "low_risk"


def build_stub_review(requirement: dict[str, Any], pipeline: ReviewPipeline) -> dict[str, Any]:
    risk = classify_review_risk(requirement, pipeline)
    decision = "needs_expert" if risk == "high_risk" else "accept"
    return {
        "task_id": f"REVIEW-{requirement.get('req_id', requirement.get('source_id', 'UNKNOWN'))}",
        "requirement_id": requirement.get("req_id"),
        "source_refs": requirement.get("source_refs", []),
        "risk": risk,
        "decision": decision,
        "revised_requirement": requirement.get("requirement", ""),
        "review_notes": [f"Stub review routed to {risk}."],
        "expert_questions": requirement.get("review_questions", []) if risk == "high_risk" else [],
        "confidence": 0.5 if risk == "high_risk" else 0.8,
        "model_route": pipeline.model_routing.get(risk, {}),
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
        state = RequirementReviewState(str(requirement.get("req_id") or requirement.get("source_id") or "UNKNOWN"))
        state.transition("llm_reviewed", actor="llm_pipeline", reason=f"decision={review['decision']}")
        if review["decision"] == "needs_expert":
            state.transition("expert_pending", actor="llm_pipeline", reason=f"risk={review['risk']}")
        elif review["decision"] == "accept":
            state.transition("accepted", actor="llm_pipeline", reason="low-risk stub acceptance")
        else:
            state.transition("flagged", actor="llm_pipeline", reason=f"decision={review['decision']}")
        states.append(state.to_dict())
    return reviews, states


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local requirement review pipeline over atomizer output.")
    parser.add_argument("--out", type=Path, required=True, help="Atomizer output directory containing atomic_requirements.jsonl")
    parser.add_argument(
        "--pipeline",
        type=Path,
        default=Path("llm_agents/review_pipeline.yaml"),
        help="Review pipeline YAML",
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
    pipeline = load_review_pipeline(pipeline_path)
    reviews, states = review_requirements(requirements, pipeline)
    write_jsonl(out_dir / "llm_review_results.jsonl", reviews)
    write_jsonl(out_dir / "review_states.jsonl", states)
    print(
        json.dumps(
            {
                "pipeline_id": pipeline.pipeline_id,
                "out": str(out_dir),
                "requirements": len(requirements),
                "reviews": len(reviews),
                "expert_pending": sum(1 for state in states if state.get("status") == "expert_pending"),
                "accepted": sum(1 for state in states if state.get("status") == "accepted"),
                "files": {
                    "llm_review_results": "llm_review_results.jsonl",
                    "review_states": "review_states.jsonl",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
