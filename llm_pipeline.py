from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from domain_pack import load_domain_pack
from llm_client import LLMClientConfig, LLMConnectionError, LLMError, LLMResponseError, chat_json, chat_json_messages
from llm_review_schema import validate_llm_review_result_payload, validate_llm_review_results
from review_state import RequirementReviewState


LOGGER = logging.getLogger("requirement_atomizer")
_PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_PIPELINE_PATH = _PACKAGE_ROOT / "llm_agents" / "review_pipeline.yaml"
DEFAULT_DOMAIN_PACK_PATH = _PACKAGE_ROOT / "domain_packs" / "dlms_cosem" / "pack.yaml"
PROMPT_VERSION = "m2-review-v1"
FAST_FAIL_SAMPLE_SIZE = 5
PROGRESS_INTERVAL = 20
SOURCE_TYPE_CONFIDENCE_THRESHOLD = 0.85


SYSTEM_PROMPT = """You are a DLMS/COSEM requirements review expert.
Review one atomic requirement candidate at a time.
Return only JSON with these fields:
- decision: one of accept, revise, split, merge, reject, needs_expert
- risk: low_risk, high_risk, or mandatory_review
- confidence: number from 0 to 1
- revised_requirement: optional corrected requirement text
- review_notes: list of short review notes
- expert_questions: list of questions for a human expert
Do not add Markdown fences or explanatory prose."""


@dataclass(frozen=True)
class ReviewPipeline:
    pipeline_id: str
    operations: list[dict[str, Any]]
    model_routing: dict[str, Any]
    risk_policy: dict[str, Any]
    model_routes: dict[str, Any]
    review_scope: dict[str, Any]


@dataclass(frozen=True)
class ReviewBatchResult:
    reviews: list[dict[str, Any]]
    states: list[dict[str, Any]]
    llm_reviewed: int
    rule_stub: int
    llm_failed: int


def load_review_pipeline(path: Path) -> ReviewPipeline:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ReviewPipeline(
        pipeline_id=str(payload.get("pipeline_id") or path.stem),
        operations=list(payload.get("operations", [])),
        model_routing=dict(payload.get("model_routing", {})),
        risk_policy=dict(payload.get("risk_policy", {})),
        model_routes=dict(payload.get("model_routes") or {"default": "stub"}),
        review_scope=dict(payload.get("review_scope") or {}),
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
        model_routes=pipeline.model_routes,
        review_scope=pipeline.review_scope,
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


def build_stub_review(
    requirement: dict[str, Any],
    pipeline: ReviewPipeline,
    *,
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    risk = classify_review_risk(requirement, pipeline)
    needs_expert = risk in {"high_risk", "mandatory_review"}
    decision = "needs_expert" if needs_expert else "accept"
    requirement_id = requirement_identity(requirement)
    route_key = "high_risk" if risk == "mandatory_review" else risk
    review_notes = [f"Stub review routed to {risk}."]
    if unavailable_reason:
        review_notes.append(f"llm_unavailable: {unavailable_reason}")
    return {
        "task_id": f"REVIEW-{requirement_id}",
        "requirement_id": requirement_id,
        "req_id": requirement.get("req_id"),
        "stable_req_id": requirement.get("stable_req_id"),
        "source_refs": requirement.get("source_refs", []),
        "risk": risk,
        "decision": decision,
        "revised_requirement": requirement.get("requirement", ""),
        "review_notes": review_notes,
        "expert_questions": requirement.get("review_questions", []) if needs_expert else [],
        "confidence": 0.5 if needs_expert else 0.8,
        "model_route": pipeline.model_routing.get(route_key, {}),
        "generated_by": "rule_stub",
    }


def review_requirements(
    requirements: list[dict[str, Any]],
    pipeline: ReviewPipeline,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    result = review_requirements_detailed(requirements, pipeline)
    return result.reviews, result.states


def review_requirements_detailed(
    requirements: list[dict[str, Any]],
    pipeline: ReviewPipeline,
    *,
    out_dir: Path | None = None,
    route: str | None = None,
    scope: str | None = None,
) -> ReviewBatchResult:
    route_name = resolve_route_name(pipeline, route)
    if route_name == "stub":
        reviews = [build_stub_review(requirement, pipeline) for requirement in requirements]
        return ReviewBatchResult(
            reviews=reviews,
            states=build_review_states(requirements, reviews),
            llm_reviewed=0,
            rule_stub=len(reviews),
            llm_failed=0,
        )
    if route_name != "openai_compatible":
        raise ValueError(f"Unsupported LLM route: {route_name}")
    if out_dir is None:
        raise ValueError("out_dir is required for openai_compatible review caching")
    return review_requirements_with_openai(requirements, pipeline, out_dir=out_dir, scope=scope)


def resolve_route_name(pipeline: ReviewPipeline, route: str | None) -> str:
    if route:
        return route
    return str(pipeline.model_routes.get("default") or "stub")


def review_requirements_with_openai(
    requirements: list[dict[str, Any]],
    pipeline: ReviewPipeline,
    *,
    out_dir: Path,
    scope: str | None,
) -> ReviewBatchResult:
    route_payload = dict(pipeline.model_routes.get("openai_compatible") or {})
    client_config = llm_config_from_route(route_payload)
    scope_config = effective_review_scope(pipeline, scope)
    concurrency = max(1, int(route_payload.get("concurrency", 1) or 1))
    cache_path = out_dir / "llm_review_cache.jsonl"
    cache = read_llm_review_cache(cache_path)

    reviews: list[dict[str, Any] | None] = [None] * len(requirements)
    pending: list[int] = []
    llm_reviewed = 0
    rule_stub = 0
    llm_failed = 0
    new_cache_rows: list[dict[str, Any]] = []

    for index, requirement in enumerate(requirements):
        if not should_llm_review(requirement, pipeline, scope_config):
            reviews[index] = build_stub_review(requirement, pipeline)
            rule_stub += 1
            continue
        cache_key = llm_cache_key(requirement, client_config.model)
        cached_review = cache.get(cache_key)
        if cached_review is not None:
            reviews[index] = cached_review
            llm_reviewed += 1
        else:
            pending.append(index)

    selected_total = llm_reviewed + len(pending)
    completed_llm = llm_reviewed

    def record_progress() -> None:
        if completed_llm and completed_llm % PROGRESS_INTERVAL == 0:
            LOGGER.info("llm review %s/%s", completed_llm, selected_total)

    sample = pending[:FAST_FAIL_SAMPLE_SIZE]
    sample_connection_failures = 0
    sample_connection_errors: list[str] = []
    for index in sample:
        requirement = requirements[index]
        try:
            review = build_openai_review(requirement, pipeline, client_config)
        except LLMConnectionError as exc:
            sample_connection_failures += 1
            sample_connection_errors.append(str(exc))
            review = build_stub_review(requirement, pipeline, unavailable_reason=str(exc))
            rule_stub += 1
            llm_failed += 1
        except LLMError as exc:
            review = build_stub_review(requirement, pipeline, unavailable_reason=str(exc))
            rule_stub += 1
            llm_failed += 1
        else:
            llm_reviewed += 1
            completed_llm += 1
            record_progress()
            new_cache_rows.append(llm_cache_row(requirement, client_config.model, review))
        reviews[index] = review

    if sample and sample_connection_failures == len(sample):
        detail = sample_connection_errors[0] if sample_connection_errors else "initial review attempts failed"
        raise LLMConnectionError(f"LLM service unavailable: all initial review attempts failed: {detail}")

    remaining = pending[FAST_FAIL_SAMPLE_SIZE:]
    if remaining:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(build_openai_review, requirements[index], pipeline, client_config): index
                for index in remaining
            }
            for future in as_completed(futures):
                index = futures[future]
                requirement = requirements[index]
                try:
                    review = future.result()
                except LLMError as exc:
                    review = build_stub_review(requirement, pipeline, unavailable_reason=str(exc))
                    rule_stub += 1
                    llm_failed += 1
                else:
                    llm_reviewed += 1
                    completed_llm += 1
                    record_progress()
                    new_cache_rows.append(llm_cache_row(requirement, client_config.model, review))
                reviews[index] = review

    final_reviews = [review for review in reviews if review is not None]
    if len(final_reviews) != len(requirements):
        raise ValueError("review batch did not produce one review per requirement")
    append_llm_review_cache(cache_path, new_cache_rows)
    return ReviewBatchResult(
        reviews=final_reviews,
        states=build_review_states(requirements, final_reviews),
        llm_reviewed=llm_reviewed,
        rule_stub=rule_stub,
        llm_failed=llm_failed,
    )


def build_review_states(requirements: list[dict[str, Any]], reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    for requirement, review in zip(requirements, reviews):
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
            state.transition("expert_pending", actor="llm_pipeline", reason=f"risk={review.get('risk', '')}")
        elif review["decision"] == "accept":
            state.transition("accepted", actor="llm_pipeline", reason="low-risk acceptance")
        elif review["decision"] == "reject":
            state.transition("rejected", actor="llm_pipeline", reason="review rejected")
        else:
            state.transition("flagged", actor="llm_pipeline", reason=f"decision={review['decision']}")
        states.append(state.to_dict())
    return states


def llm_config_from_route(payload: dict[str, Any]) -> LLMClientConfig:
    base_url = str(payload.get("base_url") or "").strip()
    model = str(payload.get("model") or "").strip()
    if not base_url or not model:
        raise ValueError("openai_compatible route requires base_url and model")
    return LLMClientConfig(
        base_url=base_url,
        model=model,
        api_key_env=str(payload.get("api_key_env", "RATOMIZER_LLM_API_KEY")),
        temperature=float(payload.get("temperature", 0.0)),
        max_tokens=int(payload.get("max_tokens", 1024)),
        timeout_s=float(payload.get("timeout_s", 60.0)),
        max_retries=int(payload.get("max_retries", 3)),
    )


def effective_review_scope(pipeline: ReviewPipeline, scope: str | None) -> dict[str, Any]:
    payload = {
        "mode": "targeted",
        "confidence_below": 0.75,
        "always_review_ambiguous": True,
        "always_review_source_types": ["paragraph", "table_row"],
        "always_review_types": [],
    }
    payload.update(dict(pipeline.review_scope or {}))
    if scope:
        payload["mode"] = scope
    return payload


def should_llm_review(requirement: dict[str, Any], pipeline: ReviewPipeline, scope_config: dict[str, Any]) -> bool:
    mode = str(scope_config.get("mode") or "targeted")
    if mode == "all":
        return True
    if mode != "targeted":
        raise ValueError(f"Unsupported review scope: {mode}")
    if scope_config.get("always_review_ambiguous", True) and requirement.get("ambiguity"):
        return True
    confidence = safe_float(requirement.get("confidence"), 0.0)
    if confidence < float(scope_config.get("confidence_below", 0.75)):
        return True
    always_types = {
        *{str(item) for item in scope_config.get("always_review_types", [])},
        *{str(item) for item in pipeline.risk_policy.get("mandatory_review_types", [])},
    }
    if str(requirement.get("requirement_type") or "") in always_types:
        return True
    source_types = {str(item) for item in scope_config.get("always_review_source_types", [])}
    if str(requirement.get("source_type") or "") in source_types and confidence < SOURCE_TYPE_CONFIDENCE_THRESHOLD:
        return True
    return False


def safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_openai_review(
    requirement: dict[str, Any],
    pipeline: ReviewPipeline,
    config: LLMClientConfig,
) -> dict[str, Any]:
    user_prompt = build_user_prompt(requirement)
    payload = chat_json(config, SYSTEM_PROMPT, user_prompt)
    review, errors = review_with_validation_errors(requirement, pipeline, payload, model=config.model)
    if errors:
        repair_prompt = (
            "Only output valid JSON matching the required review schema. "
            "The previous JSON schema validation failed: "
            + "; ".join(f"{issue.path}: {issue.message}" for issue in errors[:5])
        )
        payload = chat_json_messages(
            config,
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)},
                {"role": "user", "content": repair_prompt},
            ],
        )
        review, errors = review_with_validation_errors(requirement, pipeline, payload, model=config.model)
    if errors:
        message = "; ".join(f"{issue.path}: {issue.message}" for issue in errors[:5])
        raise LLMResponseError(f"invalid LLM review result: {message}")
    return review


def review_with_validation_errors(
    requirement: dict[str, Any],
    pipeline: ReviewPipeline,
    payload: dict[str, Any],
    *,
    model: str,
) -> tuple[dict[str, Any], list[Any]]:
    review = complete_llm_review_payload(requirement, pipeline, payload, model=model)
    issues = validate_llm_review_result_payload(review)
    errors = [issue for issue in issues if issue.severity == "error"]
    return review, errors


def build_user_prompt(requirement: dict[str, Any]) -> str:
    kb_matches = []
    for item in requirement.get("kb_matches", [])[:5]:
        if isinstance(item, dict):
            kb_matches.append(
                {
                    "name": item.get("name"),
                    "definition": item.get("definition"),
                }
            )
    prompt_payload = {
        "requirement_id": requirement_identity(requirement),
        "req_id": requirement.get("req_id"),
        "stable_req_id": requirement.get("stable_req_id"),
        "requirement": requirement.get("requirement"),
        "requirement_type": requirement.get("requirement_type"),
        "confidence": requirement.get("confidence"),
        "ambiguity": requirement.get("ambiguity"),
        "source_type": requirement.get("source_type"),
        "source_refs": requirement.get("source_refs", []),
        "source_context": requirement.get("source_context") or requirement.get("parameters") or {},
        "section_path": requirement.get("section_path", []),
        "kb_matches": kb_matches,
    }
    return json.dumps(prompt_payload, ensure_ascii=False, indent=2)


def complete_llm_review_payload(
    requirement: dict[str, Any],
    pipeline: ReviewPipeline,
    payload: dict[str, Any],
    *,
    model: str,
) -> dict[str, Any]:
    requirement_id = requirement_identity(requirement)
    review = {
        "task_id": f"REVIEW-{requirement_id}",
        "requirement_id": requirement_id,
        "req_id": requirement.get("req_id"),
        "stable_req_id": requirement.get("stable_req_id"),
        "source_refs": requirement.get("source_refs", []),
        "risk": payload.get("risk") or classify_review_risk(requirement, pipeline),
        "decision": payload.get("decision"),
        "revised_requirement": payload.get("revised_requirement") or requirement.get("requirement", ""),
        "review_notes": payload.get("review_notes", []),
        "expert_questions": payload.get("expert_questions", []),
        "confidence": payload.get("confidence"),
        "model_route": {"provider": "openai_compatible", "model": model},
        "generated_by": f"llm:{model}",
    }
    return review


def llm_cache_key(requirement: dict[str, Any], model: str) -> tuple[str, str, str]:
    return (requirement_identity(requirement), model, PROMPT_VERSION)


def read_llm_review_cache(path: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    cache: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in read_jsonl(path):
        review = row.get("review")
        if not isinstance(review, dict):
            continue
        key = (
            str(row.get("stable_req_id") or row.get("requirement_id") or ""),
            str(row.get("model") or ""),
            str(row.get("prompt_version") or ""),
        )
        if all(key):
            cache[key] = review
    return cache


def llm_cache_row(requirement: dict[str, Any], model: str, review: dict[str, Any]) -> dict[str, Any]:
    requirement_id = requirement_identity(requirement)
    return {
        "stable_req_id": requirement_id,
        "requirement_id": requirement_id,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "review": review,
    }


def append_llm_review_cache(path: Path, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    count = 0
    with path.open("a", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


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
        default=DEFAULT_PIPELINE_PATH,
        help="Review pipeline YAML",
    )
    parser.add_argument(
        "--domain-pack",
        type=Path,
        default=DEFAULT_DOMAIN_PACK_PATH,
        help="Optional domain pack whose review_policy is merged into runtime risk policy",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional max requirement count for trial runs")
    parser.add_argument("--llm-route", choices=["stub", "openai_compatible"], default=None)
    parser.add_argument("--review-scope", choices=["targeted", "all"], default=None)
    return parser.parse_args()


def run_review_pipeline(
    out_dir: Path,
    *,
    pipeline_path: Path = DEFAULT_PIPELINE_PATH,
    domain_pack_path: Path | None = DEFAULT_DOMAIN_PACK_PATH,
    limit: int = 0,
    route: str | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    pipeline_path = pipeline_path.expanduser().resolve()
    LOGGER.info("loading review pipeline")
    requirements = read_jsonl(out_dir / "atomic_requirements.jsonl")
    if limit > 0:
        requirements = requirements[:limit]
    domain_pack_path = domain_pack_path.expanduser().resolve() if domain_pack_path else None
    pipeline = merge_review_policy(load_review_pipeline(pipeline_path), domain_pack_path)
    LOGGER.info("reviewing %s requirements", len(requirements))
    result = review_requirements_detailed(requirements, pipeline, out_dir=out_dir, route=route, scope=scope)
    reviews = result.reviews
    states = result.states
    assert_valid_review_results(reviews)
    write_jsonl(out_dir / "llm_review_results.jsonl", reviews)
    write_jsonl(out_dir / "review_states.jsonl", states)
    event_count = append_review_state_events(out_dir / "review_state_events.jsonl", states)
    return {
        "pipeline_id": pipeline.pipeline_id,
        "out": str(out_dir),
        "requirements": len(requirements),
        "reviews": len(reviews),
        "llm_reviewed": result.llm_reviewed,
        "rule_stub": result.rule_stub,
        "llm_failed": result.llm_failed,
        "review_state_events": event_count,
        "expert_pending": sum(1 for state in states if state.get("status") == "expert_pending"),
        "accepted": sum(1 for state in states if state.get("status") == "accepted"),
        "files": {
            "llm_review_results": "llm_review_results.jsonl",
            "review_states": "review_states.jsonl",
            "review_state_events": "review_state_events.jsonl",
        },
    }


def main() -> int:
    args = parse_args()
    summary = run_review_pipeline(
        args.out,
        pipeline_path=args.pipeline,
        domain_pack_path=args.domain_pack,
        limit=args.limit,
        route=args.llm_route,
        scope=args.review_scope,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
