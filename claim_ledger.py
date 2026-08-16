"""Phase 0B shadow coverage ledger.

This module is intentionally reject-biased: deterministic checks may invalidate a
candidate, but only exact verbatim preservation or an independent verifier may
validate coverage.  Source provenance fields are candidate locators, never closure
evidence.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import unicodedata
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable

from ai_review_actions import review_subject_fingerprint, source_fingerprint, source_ai_requirement_id
from cosem_behavior_spec import extract_codes
from extract_guards import _unit_values, produced_ints, source_int_baseline
from llm_client import (
    LLMBudgetExceeded,
    LLMClientConfig,
    LLMRequestBudget,
    build_chat_json_request_payload,
    serialize_json_request_body,
)
from text_normalize import strip_enum_markers, strip_reference_numbers


CLAIM_LEDGER_SCHEMA_VERSION = "claim-ledger-v3"
CLAIM_LEDGER_SCHEMA = "claim-ledger/v3"
CLAIM_SEMANTIC_NEGATIVE_SCHEMA = "claim-semantic-negative/v3"
CLAIM_COVERAGE_GROUP_SCHEMA = "claim-coverage-group/v3"
CLAIM_LEDGER_PROMPT_VERSION = "claim-ledger-shadow-prompt-v4"
# WS2 §4.2 claim 账本抽检模式（full/sampling/baseline_gate）。mode 只是配置开关——
# build_shadow_ledger 默认 mode='full' 与现状逐字节一致；sampling/baseline_gate 收窄 verifier
# 闭合面（sampling=分层抽样+全部高风险 claim，baseline_gate=发布门禁全量闭合）。高风险判定
# 是确定性正则（is_high_risk_claim），不引入新 LLM 调用。claim_ledger.py 与 4.1 万行测试
# 资产不动行为面——只有显式传 mode!=full 才进入抽样分支。
CLAIM_LEDGER_MODE_VERSION = "claim-ledger-mode-v1"
CLAIM_LEDGER_MODES = ("full", "sampling", "baseline_gate")
DEFAULT_CLAIM_LEDGER_MODE = "sampling"
DEFAULT_CLAIM_LEDGER_SAMPLING_RATE = 0.10
DEFAULT_CLAIM_LEDGER_SAMPLING_FLOOR_RATE = 0.30
# v5: table_cell claim 的 source_quote 与格全文逐字相等时授予 source_quote_span
# （marker 格 "X" 仅 1 alnum，此前永落在 shared_block_locator 而被候选闸拒绝，
#  marker claim 在生产上永远无法到达独立 verifier——P1-4 复审实测）。豁免只
# 放行候选；闭合仍由 verifier 按完整 semantic_context 七维严格裁定。
CLAIM_CANDIDATE_POLICY_VERSION = "claim-coverage-candidate-v5-table-cell-exact-text"
CLAIM_EDGE_PREFILTER_VERSION = "claim-edge-prefilter-v3"
CLAIM_COVERAGE_VALIDATOR_VERSION = "claim-coverage-validator-v6"
CLAIM_NEGATIVE_POLICY_VERSION = "claim-negative-policy-v2"
CLAIM_NEGATIVE_VALIDATOR_VERSION = "claim-negative-validator-v4"  # v4: 负向上下文补父容器映射（清单/表格容器结构入 validation 输入指纹）
CLAIM_REVIEW_ADAPTER_VERSION = "ai-review-adapter-v1"
CLAIM_EFFECTIVE_B_REVIEW_ADAPTER_VERSION = "ai-review-effective-adapter-v1"
CLAIM_EFFECTIVE_A_REVIEW_ADAPTER_VERSION = "atomic-review-effective-adapter-v1"
CLAIM_REVIEW_BRIDGE_VERSION = "claim-review-bridge-v2"
CLAIM_REDUCER_VERSION = "claim-reducer-v2"
CLAIM_EFFECTIVE_REDUCER_VERSION = "claim-effective-reducer-v3"
CLAIM_EFFECTIVE_LEDGER_SCHEMA = "claim-effective-ledger/v2"
LEGACY_CLAIM_REVIEW_EVENT_SCHEMA = "claim-review-event/v1"
CLAIM_REVIEW_EVENT_SCHEMA = "claim-review-event/v2"
CLAIM_VALIDATION_REUSE_VERSION = "claim-validation-reuse-v2"
CLAIM_QUEUE_VERSION = "claim-queue-v4"
CLAIM_QUEUE_PROPOSAL_SCHEMA = "claim-queue-proposal/v3"
CLAIM_AUDIT_POLICY_VERSION = "claim-audit-shadow-v4"
CLAIM_COVERAGE_RUNTIME_VERSION = "claim-coverage-runtime-v11"
CLAIM_VERIFIER_BATCH_POLICY_VERSION = "claim-verifier-batch-v3-full-http-body"
CLAIM_COST_POLICY_VERSION = "claim-cost-policy-v3-user-approved"
CLAIM_VERIFIER_CALL_INCREASE_LIMIT = 0.25
CLAIM_VERIFIER_TOKEN_INCREASE_LIMIT = 0.65
CLAIM_EXTERNAL_BUDGET_POLICY_VERSION = "claim-verifier-external-accounting-v1"

# The planner leaves 25% of the relative call allowance for provider retries,
# JSON repair, response-format fallback, and truncation escalation.
CLAIM_VERIFIER_LOGICAL_CALL_HEADROOM = 0.75
CLAIM_COVERAGE_BATCH_MAX_GROUPS = 24
CLAIM_COVERAGE_BATCH_MAX_UTF8_BYTES = 48_000
CLAIM_NEGATIVE_BATCH_MAX_CLAIMS = 48
CLAIM_NEGATIVE_BATCH_MAX_UTF8_BYTES = 48_000
CLAIM_NEGATIVE_MAX_BATCH_PAIRS = 2
CLAIM_NEGATIVE_UNITS_PER_BATCH = 8

FORMAL_TARGET_FIELDS = ("title", "description", "sub_items", "acceptance_criteria")
SemanticVerifier = Callable[[str, list[dict[str, Any]]], dict[str, Any]]
SemanticNegativeProposer = Callable[[str, list[dict[str, Any]]], dict[str, Any]]
SemanticNegativeVerifier = Callable[[str, list[dict[str, Any]]], dict[str, Any]]
VerifierAttemptProgress = Callable[[int, int], None]

SEMANTIC_COVERAGE_CHECKS = (
    "subject",
    "modality",
    "polarity",
    "quantities_units",
    "conditions_exceptions",
    "scope",
    "target_obligation_framing",
)
SEMANTIC_NEGATIVE_REASONS = frozenset({
    "scope_statement",
    "definition",
    "informative",
    "example",
    "instrument_only",
})
SEMANTIC_NEGATIVE_CHECKS = (
    "reason_supported",
    "no_normative_obligation",
    "context_complete",
    "no_requirement_dependency",
    "homogeneous_span",
)

_VERIFIER_RUNTIME_PAYLOAD_FIELDS = (
    "version",
    "policy_source",
    "route_mode",
    "enabled",
    "rounds",
    "model",
    "base_url",
    "temperature",
    "max_tokens",
    "credential_available",
    "budget_policy_version",
    "max_calls",
    "max_total_tokens",
    "prompt_version",
    "validator_version",
    "negative_policy_version",
    "negative_validator_version",
    "batch_policy_version",
    "cost_policy_version",
)

_SEMANTIC_VERIFIER_SYSTEM = """You are an independent coverage verifier.
Each group is [group_ref, complete_source_claim, target_refs]. target_evidence is indexed by target_refs.
Decide whether the union of the referenced target-field evidence fully entails the complete source claim.
Check in this exact order: subject, modality, polarity, quantities_units, conditions_exceptions, scope,
target_obligation_framing. The last check is true only when the target evidence for this specific source claim is
written as a self-contained product/system obligation. A product/system normative clause that syntactically governs
the capability in the same sentence, including a colon-headed capability complement, satisfies this check even when
the governed complement preserves descriptive voice. A descriptive capability alone (for example, only saying that
a role can act or that an output can be configured) is false when the product obligation appears only in an unrelated
neighboring sentence or clause.
Do not infer from shared source locations, omitted fields, or likely intent.
Return exactly one JSON object: {"decisions":[[group_ref,covered,[seven_checks]],...]}.
covered must be true, false, or null and every check must be boolean. Return exactly one decision for every
group_ref, with no rationale or additional keys. Use null when the evidence is insufficient."""

_SEMANTIC_NEGATIVE_PROPOSER_SYSTEM = """You propose, but never validate, semantic non-normative classifications.
unit_contexts is indexed by each claim's unit_ref. Return only claims that may be non-normative, using one reason from:
scope_statement, definition, informative, example, instrument_only.
Treat any implementation, range, interface, acceptance, modality, condition, exception, or requirement-defining content
as normative or uncertain. Return JSON with proposals: [{claim_id, non_normative, reason, evidence, rationale}].
Evidence entries use exact claim-relative {start, end, text}. Omit normative or uncertain claims."""

_SEMANTIC_NEGATIVE_VERIFIER_SYSTEM = """You independently verify semantic non-normative claims without seeing proposals.
unit_contexts is indexed by each claim's unit_ref. For every complete claim, decide non_normative as true, false, or null and independently select one
reason from scope_statement, definition, informative, example, instrument_only. A definition or scope statement that
constrains implementation, values, interfaces, acceptance, or another requirement is normative. Mixed spans, missing
context, or any normative obligation must not validate. Return JSON with decisions: [{claim_id, non_normative, reason,
checks, evidence, rationale}]. checks must contain reason_supported, no_normative_obligation, context_complete,
no_requirement_dependency, and homogeneous_span. Evidence entries use exact claim-relative {start, end, text}."""

_STANDARD_RE = re.compile(
    r"\b(?:ABNT(?:\s+NBR)?|EN|IEC|ISO|IEEE|DIN|BS|ASTM|ETSI|CEN|STN|CSN)"
    r"\s*[-:]?\s*\d[0-9A-Za-z./-]*(?::\d{4})?\b",
    re.IGNORECASE,
)
_WS_RE = re.compile(r"\s+")
_QUOTE_SPAN_MIN_ALNUM = 6


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    payload = value if isinstance(value, bytes) else _canonical_bytes(value)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def semantic_verifier_runtime(
    *,
    route_mode: str,
    enabled: bool,
    rounds: int,
    config: Any | None = None,
    policy_source: str = "explicit",
    budget_policy_version: str | None = None,
    max_calls: int = 0,
    max_total_tokens: int = 0,
) -> dict[str, Any]:
    """Build a secret-free fingerprint for coverage validation runtime policy."""
    normalized_route = "stub" if route_mode == "stub" else "llm"
    normalized_source = "environment" if policy_source == "environment" else "explicit"
    effective_enabled = bool(enabled and normalized_route == "llm")
    effective_rounds = max(1, min(3, int(rounds))) if effective_enabled else 0
    effective_max_calls = max(0, int(max_calls)) if effective_enabled else 0
    effective_max_total_tokens = (
        max(0, int(max_total_tokens)) if effective_enabled else 0
    )
    effective_budget_version = str(budget_policy_version or "")
    if not effective_budget_version:
        effective_budget_version = (
            CLAIM_EXTERNAL_BUDGET_POLICY_VERSION
            if effective_enabled and (
                effective_max_calls <= 0 or effective_max_total_tokens <= 0
            )
            else LLMRequestBudget.VERSION
        )
    key_env = str(getattr(config, "api_key_env", "") or "") if effective_enabled else ""
    payload = {
        "version": CLAIM_COVERAGE_RUNTIME_VERSION,
        "policy_source": normalized_source,
        "route_mode": normalized_route,
        "enabled": effective_enabled,
        "rounds": effective_rounds,
        "model": str(getattr(config, "model", "") or "") if effective_enabled else "",
        "base_url": (
            str(getattr(config, "base_url", "") or "").rstrip("/")
            if effective_enabled else ""
        ),
        "temperature": (
            float(getattr(config, "temperature", 0.0) or 0.0)
            if effective_enabled else 0.0
        ),
        "max_tokens": (
            int(getattr(config, "max_tokens", 0) or 0) if effective_enabled else 0
        ),
        "credential_available": bool(os.environ.get(key_env)) if key_env else False,
        "budget_policy_version": effective_budget_version,
        "max_calls": effective_max_calls,
        "max_total_tokens": effective_max_total_tokens,
        "prompt_version": CLAIM_LEDGER_PROMPT_VERSION,
        "validator_version": CLAIM_COVERAGE_VALIDATOR_VERSION,
        "negative_policy_version": CLAIM_NEGATIVE_POLICY_VERSION,
        "negative_validator_version": CLAIM_NEGATIVE_VALIDATOR_VERSION,
        "batch_policy_version": CLAIM_VERIFIER_BATCH_POLICY_VERSION,
        "cost_policy_version": CLAIM_COST_POLICY_VERSION,
    }
    return {**payload, "fingerprint": _sha256(payload)}


def semantic_verifier_runtime_is_valid(runtime: object) -> bool:
    """Return whether a persisted verifier runtime is complete and replayable."""
    if not isinstance(runtime, dict):
        return False
    expected_fields = {*_VERIFIER_RUNTIME_PAYLOAD_FIELDS, "fingerprint"}
    if set(runtime) != expected_fields:
        return False
    payload = {name: runtime.get(name) for name in _VERIFIER_RUNTIME_PAYLOAD_FIELDS}
    enabled = payload["enabled"]
    rounds = payload["rounds"]
    temperature = payload["temperature"]
    max_tokens = payload["max_tokens"]
    max_calls = payload["max_calls"]
    max_total_tokens = payload["max_total_tokens"]
    credential_available = payload["credential_available"]
    if (
        payload["version"] != CLAIM_COVERAGE_RUNTIME_VERSION
        or payload["policy_source"] not in {"explicit", "environment"}
        or payload["route_mode"] not in {"llm", "stub"}
        or not isinstance(enabled, bool)
        or not isinstance(rounds, int)
        or isinstance(rounds, bool)
        or not isinstance(temperature, (int, float))
        or isinstance(temperature, bool)
        or not isinstance(max_tokens, int)
        or isinstance(max_tokens, bool)
        or max_tokens < 0
        or not isinstance(max_calls, int)
        or isinstance(max_calls, bool)
        or max_calls < 0
        or not isinstance(max_total_tokens, int)
        or isinstance(max_total_tokens, bool)
        or max_total_tokens < 0
        or not isinstance(credential_available, bool)
        or not all(isinstance(payload[name], str) for name in (
            "model", "base_url", "budget_policy_version", "prompt_version", "validator_version",
            "negative_policy_version", "negative_validator_version", "batch_policy_version",
            "cost_policy_version",
        ))
        or payload["prompt_version"] != CLAIM_LEDGER_PROMPT_VERSION
        or payload["validator_version"] != CLAIM_COVERAGE_VALIDATOR_VERSION
        or payload["negative_policy_version"] != CLAIM_NEGATIVE_POLICY_VERSION
        or payload["negative_validator_version"] != CLAIM_NEGATIVE_VALIDATOR_VERSION
        or payload["batch_policy_version"] != CLAIM_VERIFIER_BATCH_POLICY_VERSION
        or payload["cost_policy_version"] != CLAIM_COST_POLICY_VERSION
    ):
        return False
    if enabled:
        if payload["route_mode"] != "llm" or not 1 <= rounds <= 3:
            return False
        if payload["policy_source"] == "environment" and (
            payload["budget_policy_version"] != LLMRequestBudget.VERSION
            or max_calls <= 0
            or max_total_tokens <= 0
        ):
            return False
    elif (
        rounds != 0
        or payload["model"] != ""
        or payload["base_url"] != ""
        or temperature != 0
        or max_tokens != 0
        or credential_available
        or max_calls != 0
        or max_total_tokens != 0
    ):
        return False
    return runtime.get("fingerprint") == _sha256(payload)


def _normalized(text: object) -> str:
    value = unicodedata.normalize("NFKC", str(text or ""))
    return _WS_RE.sub(" ", value).strip().casefold()


def target_source_fingerprint(requirement: dict[str, Any]) -> str:
    return source_fingerprint(requirement)


def target_fingerprint(requirement: dict[str, Any]) -> str:
    return review_subject_fingerprint(requirement)


def _field_value(requirement: dict[str, Any], field: str, item_index: int | None) -> str | None:
    if field in {"title", "description", "requirement", "condition"}:
        return str(requirement.get(field) or "")
    if field == "sub_items":
        rows = requirement.get("sub_items") or []
        if item_index is None or not isinstance(rows, list) or not 0 <= item_index < len(rows):
            return None
        item = rows[item_index]
        return str(item.get("text") or "") if isinstance(item, dict) else None
    if field == "acceptance_criteria":
        rows = requirement.get("acceptance_criteria") or []
        if item_index is None or not isinstance(rows, list) or not 0 <= item_index < len(rows):
            return None
        return str(rows[item_index] or "")
    return None


def target_evidence(requirement: dict[str, Any]) -> list[dict[str, Any]]:
    """Return exact, recomputable locators for declared formal output fields."""
    evidence: list[dict[str, Any]] = []
    for field in ("title", "description"):
        value = str(requirement.get(field) or "")
        if value:
            evidence.append({
                "field": field,
                "item_index": None,
                "start": 0,
                "end": len(value),
                "position_basis": "target_field_unicode_codepoints",
                "field_value_hash": _sha256(value.encode("utf-8")),
                "text": value,
            })
    for index, item in enumerate(requirement.get("sub_items") or []):
        value = str(item.get("text") or "") if isinstance(item, dict) else ""
        if value:
            evidence.append({
                "field": "sub_items",
                "item_index": index,
                "start": 0,
                "end": len(value),
                "position_basis": "target_field_unicode_codepoints",
                "field_value_hash": _sha256(value.encode("utf-8")),
                "text": value,
            })
    for index, item in enumerate(requirement.get("acceptance_criteria") or []):
        value = str(item or "")
        if value:
            evidence.append({
                "field": "acceptance_criteria",
                "item_index": index,
                "start": 0,
                "end": len(value),
                "position_basis": "target_field_unicode_codepoints",
                "field_value_hash": _sha256(value.encode("utf-8")),
                "text": value,
            })
    return evidence


def evidence_is_current(evidence: dict[str, Any], requirement: dict[str, Any]) -> bool:
    value = _field_value(
        requirement,
        str(evidence.get("field") or ""),
        evidence.get("item_index") if isinstance(evidence.get("item_index"), int) else None,
    )
    if value is None or _sha256(value.encode("utf-8")) != str(evidence.get("field_value_hash") or ""):
        return False
    try:
        start, end = int(evidence["start"]), int(evidence["end"])
    except (KeyError, TypeError, ValueError):
        return False
    return 0 <= start <= end <= len(value) and value[start:end] == str(evidence.get("text") or "")


# M2 §4.4：coverage edge 源锚字段（FRE evidence_anchors 的确定性投影）
FUNCTIONAL_SOURCE_ANCHOR_FIELDS = (
    "section_id",
    "block_ids",
    "sentence_index",
    "unit_index",
    "source_text_hash",
    "match_method",
)


# 锚 match_method 的合法取值（与 functional_extract._obligation_evidence_edges 同源；
# 三轮复审 P2：forged 之类的伪造方法名不得通过）
VALID_SOURCE_ANCHOR_MATCH_METHODS = frozenset({
    "lexical", "cross_script_review", "source_quote",
})


def functional_anchor_obligation_hashes(
    root: Path | str,
) -> dict[tuple[str, int], dict[str, Any]]:
    """复审 P2-1（2026-08-16）+ 三轮 P2：按当前条款重算义务单元**完整身份**。

    返回 {(section_id, unit_index): {"sentence_index": i, "source_text_hash": sha}}——
    锚的四元组（section/unit/sentence/hash）必须**联合指向同一个当前义务单元**：
    unit 存在、句序一致、哈希一致。条款产物缺失/解析失败返回空表（调用方按
    "不可核验"处理，不伪造通过）。
    """
    try:
        from functional_extract import _obligation_index, load_clauses

        sections = load_clauses(Path(root))
    except Exception:  # noqa: BLE001 — 无条款产物（legacy/测试）→ 不可核验
        return {}
    import hashlib as _hashlib

    identities: dict[tuple[str, int], dict[str, Any]] = {}
    for section in sections:
        section_id = str(section.get("section_id") or "")
        if not section_id:
            continue
        section_blocks = frozenset(
            str(b) for b in (section.get("block_ids") or []) if str(b)
        )
        for obligation in _obligation_index(section):
            identities[(section_id, obligation["unit_index"])] = {
                "sentence_index": obligation["sentence_index"],
                "source_text_hash": _hashlib.sha256(
                    obligation["sentence"].encode("utf-8")).hexdigest(),
                # 四轮复审 P1-2：section 的实际块集——锚的 block_ids 必须落在
                # 所属 section 的真实块集内，否则"合法 section/unit/hash + 外条款
                # block"的伪锚可跨条款借位参与他款 Claim 闭合。
                "section_block_ids": section_blocks,
            }
    return identities


def functional_source_anchors(requirement: dict[str, Any]) -> list[dict[str, Any]]:
    """把 FRE 的确定性 ``evidence_anchors`` 投影为 coverage edge 源锚（§4.4）。

    只取锚的可复核身份字段（section_id/block_ids/sentence_index/unit_index/
    source_text_hash/match_method——后两者由 obligation/evidence 绑定模型提供，
    缺席时如实缺席）；不可定位（无 section_id 或无 block_ids）的锚不进 edge。
    原子需求无 ``evidence_anchors`` → 空表（edge 不加该键，行为不变）。
    """
    anchors = requirement.get("evidence_anchors")
    if not isinstance(anchors, list):
        return []
    projected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        row: dict[str, Any] = {}
        for field in ("section_id", "source_text_hash", "match_method"):
            value = str(anchor.get(field) or "").strip()
            if value:
                row[field] = value
        block_ids = list(dict.fromkeys(
            str(block) for block in (anchor.get("block_ids") or []) if str(block)
        ))
        if block_ids:
            row["block_ids"] = block_ids
        for field in ("sentence_index", "unit_index"):
            value = anchor.get(field)
            if isinstance(value, int) and not isinstance(value, bool):
                row[field] = value
        # 复审 P2 二轮（2026-08-16）：六字段合同强制——section_id/block_ids/
        # sentence_index/unit_index/source_text_hash/match_method 缺一不可，
        # 不完整锚不得成为非 stale edge（此前缺 match_method/sentence_index
        # 仍能通过）。缺席如实缺席：剔除，不补默认值。
        if any(field not in row for field in (
                "sentence_index", "unit_index", "source_text_hash", "match_method")):
            continue
        if not row.get("section_id") or not row.get("block_ids"):
            continue  # 锚无法定位——宁缺勿假，不进 edge
        key = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        projected.append(row)
    return projected


def _claim_locator_blocks(claim: dict[str, Any]) -> frozenset[str]:
    """claim locator 指向的源块集合（edge 源锚的辖域）。"""
    locator = claim.get("locator")
    locator = locator if isinstance(locator, dict) else {}
    blocks = {str(locator.get("block_id") or "")}
    blocks.update(str(value or "") for value in (locator.get("block_ids") or []))
    blocks.discard("")
    return frozenset(blocks)


def _fact(kind: str, value: str, *, aliases: Iterable[str] = ()) -> dict[str, Any]:
    return {"kind": kind, "value": value, "aliases": list(dict.fromkeys(str(x) for x in aliases))}


def extract_protected_facts(
    text: str,
    *,
    controlled_term_aliases: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Extract only versioned, deterministically comparable facts from a claim."""
    value = str(text or "")
    facts: list[dict[str, Any]] = []
    for code in sorted(extract_codes(value), key=str.casefold):
        facts.append(_fact("code", code))
    for standard in sorted({match.group(0).strip() for match in _STANDARD_RE.finditer(value)}, key=str.casefold):
        facts.append(_fact("standard", standard))
    unit_values = _unit_values(value)
    for unit in sorted(unit_values):
        for number in sorted(unit_values[unit]):
            facts.append(_fact("unit_value", f"{number} {unit}"))
    number_basis = strip_reference_numbers(strip_enum_markers(value))
    for number in sorted(source_int_baseline(number_basis), key=lambda token: (len(token), token)):
        facts.append(_fact("number", number))
    for source_term, aliases in sorted((controlled_term_aliases or {}).items()):
        if _normalized(source_term) and _normalized(source_term) in _normalized(value):
            facts.append(_fact("controlled_term", source_term, aliases=[source_term, *aliases]))
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for fact in facts:
        key = (str(fact["kind"]), _normalized(fact["value"]))
        if key not in seen:
            seen.add(key)
            deduped.append(fact)
    return deduped


def _fact_present(fact: dict[str, Any], evidence_text: str) -> bool:
    kind = str(fact.get("kind") or "")
    value = str(fact.get("value") or "")
    if kind == "code":
        return value.casefold() in {code.casefold() for code in extract_codes(evidence_text)}
    if kind == "standard":
        standards = {_normalized(match.group(0)) for match in _STANDARD_RE.finditer(evidence_text)}
        return _normalized(value) in standards
    if kind == "unit_value":
        number, _, unit = value.partition(" ")
        return number in _unit_values(evidence_text).get(unit.casefold(), set())
    if kind == "number":
        return value in produced_ints(evidence_text)
    if kind == "controlled_term":
        normalized_evidence = _normalized(evidence_text)
        return any(_normalized(alias) in normalized_evidence for alias in (fact.get("aliases") or []))
    return False


def reject_only_prefilter(
    claim_text: str,
    produced_evidence: list[dict[str, Any]],
    *,
    controlled_term_aliases: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    facts = extract_protected_facts(
        claim_text,
        controlled_term_aliases=controlled_term_aliases,
    )
    evidence_text = "\n".join(str(row.get("text") or "") for row in produced_evidence)
    missing = [fact for fact in facts if not _fact_present(fact, evidence_text)]
    if missing:
        status = "reject"
    elif facts:
        status = "pass"
    else:
        status = "not_applicable"
    return {
        "version": CLAIM_EDGE_PREFILTER_VERSION,
        "status": status,
        "protected_facts": facts,
        "missing_protected_facts": missing,
    }


def _target_review(
    requirement: dict[str, Any],
    states: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    target_id = source_ai_requirement_id(requirement)
    target_hash = target_fingerprint(requirement)
    source_hash = target_source_fingerprint(requirement)
    state = states.get(target_id)
    status = "unreviewed"
    eligibility = "active"
    reason = ""
    canonical_state: dict[str, Any] = {"status": status}
    if state is not None:
        status = str(state.get("status") or "unknown")
        expected_source = str(state.get("source_fingerprint") or "")
        expected_subject = str(state.get("review_subject_fingerprint") or "")
        if not expected_source or not expected_subject:
            eligibility, reason = "unknown", "legacy_review_without_fingerprint"
        elif expected_source != source_hash or expected_subject != target_hash:
            eligibility, reason = "unknown", "review_fingerprint_mismatch"
        elif status == "rejected":
            eligibility, reason = "rejected", "expert_rejected"
        canonical_state = {
            "status": status,
            "source_fingerprint": expected_source,
            "review_subject_fingerprint": expected_subject,
            "recorded_at": str(state.get("recorded_at") or ""),
        }
    revision = _sha256({
        "source_store": "ai_review_states.jsonl",
        "target_id": target_id,
        "target_fingerprint": target_hash,
        "effective_state": canonical_state,
        "adapter_version": CLAIM_REVIEW_ADAPTER_VERSION,
    })
    return {
        "status": status,
        "eligibility": eligibility,
        "reason": reason,
        "target_review_revision": revision,
        "review_adapter_version": CLAIM_REVIEW_ADAPTER_VERSION,
    }


def _targets(
    requirements: list[dict[str, Any]],
    review_states: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], str, str]:
    records: list[dict[str, Any]] = []
    for requirement in requirements:
        target_id = source_ai_requirement_id(requirement)
        review = _target_review(requirement, review_states)
        records.append({
            "target_requirement_id": target_id,
            "target_fingerprint": target_fingerprint(requirement),
            "source_fingerprint": target_source_fingerprint(requirement),
            "requirement": requirement,
            "evidence": target_evidence(requirement),
            # M2 §4.4：FRE 目标附确定性源锚（原子目标为空表，不影响权威哈希）
            "source_anchors": functional_source_anchors(requirement),
            "review": review,
        })
    id_counts: dict[str, int] = defaultdict(int)
    for record in records:
        id_counts[str(record["target_requirement_id"])] += 1
    for record in records:
        target_id = str(record["target_requirement_id"])
        if id_counts[target_id] <= 1:
            continue
        previous_review = dict(record["review"])
        record["review"] = {
            **previous_review,
            "eligibility": "unknown",
            "reason": "duplicate_target_requirement_id",
            "target_review_revision": _sha256({
                "previous_revision": previous_review["target_review_revision"],
                "target_id": target_id,
                "target_fingerprint": record["target_fingerprint"],
                "ambiguity": "duplicate_target_requirement_id",
                "adapter_version": CLAIM_REVIEW_ADAPTER_VERSION,
            }),
        }
    target_generation = _sha256([
        {"target_requirement_id": row["target_requirement_id"],
         "target_fingerprint": row["target_fingerprint"]}
        for row in sorted(
            records,
            key=lambda value: (
                str(value["target_requirement_id"]),
                str(value["target_fingerprint"]),
            ),
        )
    ])
    authority_revision = _sha256([
        {
            "target_requirement_id": row["target_requirement_id"],
            "target_fingerprint": row["target_fingerprint"],
            "target_review_revision": row["review"]["target_review_revision"],
        }
        for row in sorted(
            records,
            key=lambda value: (
                str(value["target_requirement_id"]),
                str(value["target_fingerprint"]),
            ),
        )
    ])
    return records, target_generation, authority_revision


def b_track_authority_state(
    requirements: list[dict[str, Any]],
    review_states: dict[str, dict[str, Any]],
) -> dict[str, str]:
    _records, target_generation, authority_revision = _targets(requirements, review_states)
    return {
        "target_generation_id": target_generation,
        "target_review_authority_revision": authority_revision,
    }


def b_track_coverage_targets(
    requirements: list[dict[str, Any]],
    review_states: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return target records bound to the current B-track review authority."""
    records, _target_generation, _authority_revision = _targets(requirements, review_states)
    return records


def effective_review_adapter_versions() -> list[dict[str, str]]:
    """Canonical adapter-version vector used by effective row revisions."""
    return [
        {
            "target_kind": "ai_requirement",
            "adapter_version": CLAIM_EFFECTIVE_B_REVIEW_ADAPTER_VERSION,
        },
        {
            "target_kind": "atomic_requirement",
            "adapter_version": CLAIM_EFFECTIVE_A_REVIEW_ADAPTER_VERSION,
        },
    ]


def atomic_requirement_id(requirement: dict[str, Any]) -> str:
    """Return the declared A-track identity without inferring a delivery track."""
    for key in ("stable_req_id", "requirement_id", "req_id"):
        value = str(requirement.get(key) or "").strip()
        if value:
            return value
    return ""


def atomic_target_source_fingerprint(requirement: dict[str, Any]) -> str:
    """Fingerprint the source provenance carried by an atomic requirement."""
    from claim_artifacts import hash_json

    return hash_json(
        "claim-atomic-target-source/v1",
        {
            "source_id": str(requirement.get("source_id") or ""),
            "source_type": str(requirement.get("source_type") or ""),
            "source_refs": [
                str(value) for value in (requirement.get("source_refs") or [])
            ],
            "section_path": [
                str(value) for value in (requirement.get("section_path") or [])
            ],
            "source_context": requirement.get("source_context"),
        },
    )


def atomic_target_fingerprint(requirement: dict[str, Any]) -> str:
    """Fingerprint the formal A-track fields reviewed as one requirement."""
    from claim_artifacts import hash_json

    return hash_json(
        "claim-atomic-target-subject/v1",
        {
            "domain": requirement.get("domain"),
            "object": requirement.get("object"),
            "requirement_type": requirement.get("requirement_type"),
            "requirement": requirement.get("requirement"),
            "condition": requirement.get("condition"),
            "parameters": requirement.get("parameters"),
            "verification_method": requirement.get("verification_method"),
        },
    )


def atomic_target_evidence(requirement: dict[str, Any]) -> list[dict[str, Any]]:
    """Return locators into real atomic-requirement fields, not a B-track alias."""
    evidence: list[dict[str, Any]] = []
    for field in ("requirement", "condition"):
        value = requirement.get(field)
        if not isinstance(value, str) or not value:
            continue
        evidence.append({
            "field": field,
            "item_index": None,
            "start": 0,
            "end": len(value),
            "position_basis": "target_field_unicode_codepoints",
            "field_value_hash": _sha256(value.encode("utf-8")),
            "text": value,
        })
    return evidence


def _a_review_state_identity_keys(state: dict[str, Any]) -> tuple[str, ...]:
    keys: list[str] = []
    metadata = state.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    for container, names in (
        (state, ("requirement_id", "stable_req_id", "req_id")),
        (metadata, ("stable_req_id", "req_id")),
    ):
        for name in names:
            value = str(container.get(name) or "").strip()
            if value and value not in keys:
                keys.append(value)
    return tuple(keys)


def a_track_effective_authority(
    requirements: list[dict[str, Any]],
    review_states: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Project A-track targets plus embedded review-state history into live facts."""
    from claim_artifacts import canonical_target_fingerprint, hash_json

    source_store = "review_states.jsonl"
    target_kind = "atomic_requirement"
    adapter_version = CLAIM_EFFECTIVE_A_REVIEW_ADAPTER_VERSION
    state_rows = [dict(row) for row in review_states if isinstance(row, dict)]
    states_by_identity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for state in state_rows:
        for identity in _a_review_state_identity_keys(state):
            states_by_identity[identity].append(state)

    id_counts: dict[str, int] = defaultdict(int)
    for requirement in requirements:
        id_counts[atomic_requirement_id(requirement)] += 1

    records: list[dict[str, Any]] = []
    for requirement in requirements:
        target_id = atomic_requirement_id(requirement)
        target_hash = canonical_target_fingerprint(
            atomic_target_fingerprint(requirement)
        )
        current_source_hash = canonical_target_fingerprint(
            atomic_target_source_fingerprint(requirement)
        )
        matching_states = states_by_identity.get(target_id, [])
        status = "unreviewed"
        eligibility = "active"
        reason = "no_review_record"
        source_hash: str | None = None
        subject_hash: str | None = None
        needs_reconfirmation = False
        if len(matching_states) == 1:
            state = matching_states[0]
            metadata = state.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            status = str(state.get("status") or "unknown")
            raw_source_hash = str(
                state.get("source_fingerprint")
                or metadata.get("source_fingerprint")
                or ""
            )
            raw_subject_hash = str(
                state.get("review_subject_fingerprint")
                or metadata.get("review_subject_fingerprint")
                or ""
            )
            source_hash = (
                canonical_target_fingerprint(raw_source_hash)
                if raw_source_hash
                else None
            )
            subject_hash = (
                canonical_target_fingerprint(raw_subject_hash)
                if raw_subject_hash
                else None
            )
            needs_reconfirmation = bool(
                state.get("needs_reconfirmation")
                or metadata.get("needs_reconfirmation")
            )
            if needs_reconfirmation:
                eligibility, reason = "unknown", "review_needs_reconfirmation"
            elif source_hash is None or subject_hash is None:
                eligibility, reason = "unknown", "legacy_review_without_fingerprint"
                needs_reconfirmation = True
            elif source_hash != current_source_hash or subject_hash != target_hash:
                eligibility, reason = "unknown", "review_fingerprint_mismatch"
                needs_reconfirmation = True
            elif status == "rejected":
                eligibility, reason = "rejected", "expert_rejected"
            else:
                eligibility, reason = "active", "review_active"
        elif len(matching_states) > 1:
            status = "ambiguous"
            eligibility, reason = "unknown", "duplicate_review_state_identity"
            needs_reconfirmation = True

        if not target_id or id_counts[target_id] > 1:
            eligibility = "unknown"
            reason = (
                "missing_target_requirement_id"
                if not target_id
                else "duplicate_target_requirement_id"
            )
            needs_reconfirmation = True

        effective_state = {
            "status": status,
            "eligibility": eligibility,
            "reason": reason,
            "source_fingerprint": source_hash,
            "review_subject_fingerprint": subject_hash,
            "needs_reconfirmation": needs_reconfirmation,
        }
        review_revision = hash_json(
            "claim-target-review-revision/v1",
            {
                "source_store": source_store,
                "target_kind": target_kind,
                "target_requirement_id": target_id,
                "target_fingerprint": target_hash,
                "effective_state": effective_state,
                "adapter_version": adapter_version,
            },
        )
        records.append({
            "target_kind": target_kind,
            "target_requirement_id": target_id,
            "target_fingerprint": target_hash,
            "source_fingerprint": current_source_hash,
            "requirement": requirement,
            "evidence": atomic_target_evidence(requirement),
            "review": {
                **effective_state,
                "target_review_revision": review_revision,
                "review_adapter_version": adapter_version,
            },
        })

    records.sort(key=lambda row: (
        str(row["target_kind"]),
        str(row["target_requirement_id"]),
        str(row["target_fingerprint"]),
    ))
    target_projection = [{
        "target_kind": row["target_kind"],
        "target_requirement_id": row["target_requirement_id"],
        "target_fingerprint": row["target_fingerprint"],
    } for row in records]
    review_projection = [{
        **identity,
        "eligibility": row["review"]["eligibility"],
        "target_review_revision": row["review"]["target_review_revision"],
    } for row, identity in zip(records, target_projection, strict=True)]
    return {
        "source_store": source_store,
        "target_kind": target_kind,
        "adapter_version": adapter_version,
        "records": records,
        "target_set_hash": hash_json("claim-target-set/v1", target_projection),
        "requirement_review_state_hash": hash_json(
            "claim-review-authority/v1",
            review_projection,
        ),
    }


def b_track_effective_authority(
    requirements: list[dict[str, Any]],
    review_states: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Project current B-track targets and review authority into Phase 1 identities.

    This projection is deliberately separate from the frozen generation-time adapter.
    It never changes base groups and excludes timestamps and free-form review rationale
    from semantic revisions.
    """
    from claim_artifacts import canonical_target_fingerprint, hash_json

    source_store = "ai_review_states.jsonl"
    target_kind = "ai_requirement"
    adapter_version = CLAIM_EFFECTIVE_B_REVIEW_ADAPTER_VERSION
    records: list[dict[str, Any]] = []
    id_counts: dict[str, int] = defaultdict(int)
    for requirement in requirements:
        id_counts[source_ai_requirement_id(requirement)] += 1

    for requirement in requirements:
        target_id = source_ai_requirement_id(requirement)
        target_hash = canonical_target_fingerprint(target_fingerprint(requirement))
        current_source_hash = canonical_target_fingerprint(
            target_source_fingerprint(requirement)
        )
        state = review_states.get(target_id)
        status = "unreviewed"
        eligibility = "active"
        reason = "no_review_record"
        source_hash: str | None = None
        subject_hash: str | None = None
        needs_reconfirmation = False
        if state is not None:
            status = str(state.get("status") or "unknown")
            raw_source_hash = str(state.get("source_fingerprint") or "")
            raw_subject_hash = str(state.get("review_subject_fingerprint") or "")
            source_hash = (
                canonical_target_fingerprint(raw_source_hash)
                if raw_source_hash
                else None
            )
            subject_hash = (
                canonical_target_fingerprint(raw_subject_hash)
                if raw_subject_hash
                else None
            )
            needs_reconfirmation = bool(state.get("needs_reconfirmation"))
            if needs_reconfirmation:
                eligibility, reason = "unknown", "review_needs_reconfirmation"
            elif source_hash is None or subject_hash is None:
                eligibility, reason = "unknown", "legacy_review_without_fingerprint"
                needs_reconfirmation = True
            elif source_hash != current_source_hash or subject_hash != target_hash:
                eligibility, reason = "unknown", "review_fingerprint_mismatch"
                needs_reconfirmation = True
            elif status == "rejected":
                eligibility, reason = "rejected", "expert_rejected"
            else:
                eligibility, reason = "active", "review_active"

        if id_counts[target_id] > 1:
            eligibility = "unknown"
            reason = "duplicate_target_requirement_id"
            needs_reconfirmation = True

        effective_state = {
            "status": status,
            "eligibility": eligibility,
            "reason": reason,
            "source_fingerprint": source_hash,
            "review_subject_fingerprint": subject_hash,
            "needs_reconfirmation": needs_reconfirmation,
        }
        review_revision = hash_json(
            "claim-target-review-revision/v1",
            {
                "source_store": source_store,
                "target_kind": target_kind,
                "target_requirement_id": target_id,
                "target_fingerprint": target_hash,
                "effective_state": effective_state,
                "adapter_version": adapter_version,
            },
        )
        records.append({
            "target_kind": target_kind,
            "target_requirement_id": target_id,
            "target_fingerprint": target_hash,
            "source_fingerprint": current_source_hash,
            "requirement": requirement,
            "evidence": target_evidence(requirement),
            "review": {
                **effective_state,
                "target_review_revision": review_revision,
                "review_adapter_version": adapter_version,
            },
        })

    records.sort(key=lambda row: (
        str(row["target_kind"]),
        str(row["target_requirement_id"]),
        str(row["target_fingerprint"]),
    ))
    target_projection = [{
        "target_kind": row["target_kind"],
        "target_requirement_id": row["target_requirement_id"],
        "target_fingerprint": row["target_fingerprint"],
    } for row in records]
    review_projection = [{
        **identity,
        "eligibility": row["review"]["eligibility"],
        "target_review_revision": row["review"]["target_review_revision"],
    } for row, identity in zip(records, target_projection, strict=True)]
    return {
        "source_store": source_store,
        "target_kind": target_kind,
        "adapter_version": adapter_version,
        "records": records,
        "target_set_hash": hash_json("claim-target-set/v1", target_projection),
        "requirement_review_state_hash": hash_json(
            "claim-review-authority/v1",
            review_projection,
        ),
    }


def _claim_content(claim: dict[str, Any]) -> tuple[str, int, int]:
    # table_cell claim：裸格（"X"）对匹配/验证没有语义——证据文本采用确定性
    # semantic_context（表标题+行头+列头+正文），span 指正文在上下文行内的位置
    semantic = str(claim.get("semantic_context") or "")
    if str(claim.get("source_kind") or "") == "table_cell" and semantic:
        text = str(claim.get("text") or "")
        anchor = semantic.rfind(text) if text else -1
        if anchor >= 0:
            return semantic, anchor, anchor + len(text)
        return semantic, 0, len(semantic)
    text = str(claim.get("text") or "")
    leading = len(text) - len(text.lstrip())
    trailing_end = len(text.rstrip())
    if trailing_end < leading:
        return text, 0, len(text)
    return text[leading:trailing_end], leading, trailing_end


def _candidate_basis(claim: dict[str, Any], target: dict[str, Any]) -> list[str]:
    content, _, _ = _claim_content(claim)
    claim_norm = _normalized(content)
    requirement = target["requirement"]
    quote_norm = _normalized(requirement.get("source_quote"))
    basis: list[str] = []
    if claim_norm and quote_norm:
        if claim_norm == quote_norm:
            basis.append("source_quote_span")
        elif (
            str(claim.get("source_kind") or "") == "table_cell"
            and quote_norm == _normalized(claim.get("text"))
        ):
            # marker 格 claim（"X"/"●"）：claim 正文 = 格全文，source_quote 与格
            # 全文逐字相等是精确的格身份绑定，不是 6-alnum 下限要防的残缺片段
            # 子串（页码/标点/残词形成的笛卡尔误配）。豁免下限只让 claim 到达
            # 独立 verifier——主体/维度仍按完整 semantic_context 七维严格裁定，
            # 同表其余 marker 格不会被同一 requirement 闭合。
            basis.append("source_quote_span")
        elif claim_norm in quote_norm or quote_norm in claim_norm:
            matched = claim_norm if len(claim_norm) <= len(quote_norm) else quote_norm
            if sum(char.isalnum() for char in matched) >= _QUOTE_SPAN_MIN_ALNUM:
                basis.append("source_quote_span")
    block_id = str((claim.get("locator") or {}).get("block_id") or "")
    if block_id and block_id in {str(value) for value in (requirement.get("source_block_ids") or [])}:
        basis.append("shared_block_locator")
    return basis


def _verbatim_evidence(content: str, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    if not content:
        return matches
    for row in evidence:
        field_text = str(row.get("text") or "")
        start = field_text.find(content)
        if start < 0:
            continue
        match = dict(row)
        match["start"] = start
        match["end"] = start + len(content)
        match["text"] = content
        matches.append(match)
    return matches


def _edge(
    target: dict[str, Any],
    *,
    claim_hash: str,
    target_generation_id: str,
    produced_evidence: list[dict[str, Any]],
    relation: str,
    claim_locator_blocks: frozenset[str] | None = None,
    obligation_hashes: dict[tuple[str, int], str] | None = None,
) -> dict[str, Any]:
    edge_hash = _sha256({
        "claim_hash": claim_hash,
        "target_id": target["target_requirement_id"],
        "target_fingerprint": target["target_fingerprint"],
        "produced_evidence": produced_evidence,
    })
    review = target["review"]
    edge = {
        "edge_id": "CED-" + edge_hash.removeprefix("sha256:")[:16],
        "target_kind": "ai_requirement",
        "target_generation_id": target_generation_id,
        "target_requirement_id": target["target_requirement_id"],
        "target_fingerprint": target["target_fingerprint"],
        "target_review_status": review["status"],
        "target_review_eligibility": review["eligibility"],
        "target_review_revision": review["target_review_revision"],
        "review_adapter_version": review["review_adapter_version"],
        "relation": relation,
        "produced_evidence": produced_evidence,
    }
    # M2 §4.4：FRE 目标带源锚时，edge 只携带落在该 claim locator 块内的锚（锚必须
    # 能定位到本 claim 的源，跨条款锚不参与本 edge 的闭合依据）；全部锚都在辖域外
    # → edge 标 stale（不得用于关闭 Claim）。无锚目标不加该键（原子目标行为不变）。
    anchors = target.get("source_anchors")
    if isinstance(anchors, list) and anchors:
        locator = claim_locator_blocks if claim_locator_blocks is not None else frozenset()
        confined = []
        text_identity_dropped = 0
        for anchor in anchors:
            if not isinstance(anchor, dict):
                continue
            if not locator & {
                str(block) for block in (anchor.get("block_ids") or []) if str(block)
            }:
                continue  # 辖域外——不参与本 edge（M2 语义不变）
            # 复审 P2-1：文本身份核验——按当前义务重算 sha256 比对锚的
            # source_text_hash；义务缺席或哈希失配的锚不可用于关闭 Claim。
            # 六字段合同:缺 sentence_index/unit_index/source_text_hash/match_method
            # 的不完整锚直接剔除(与 functional_source_anchors 投影同口径)
            if not all(
                anchor.get(field) is not None
                for field in ("sentence_index", "unit_index",
                              "source_text_hash", "match_method")
            ):
                text_identity_dropped += 1
                continue
            # 三轮复审 P2：字段**语义**校验——match_method 必须是合法枚举（forged
            # 之类直接拒），四元组必须联合指向同一个当前义务单元（unit 存在、
            # 句序与哈希一致；999 之类的伪句序过不了）。
            if str(anchor.get("match_method")) not in VALID_SOURCE_ANCHOR_MATCH_METHODS:
                text_identity_dropped += 1
                continue
            if obligation_hashes is not None:
                key = (
                    str(anchor.get("section_id") or ""),
                    anchor.get("unit_index"),
                )
                identity = obligation_hashes.get(key) if isinstance(key[1], int) else None
                anchor_hash = str(anchor.get("source_text_hash") or "")
                anchor_blocks = {
                    str(b) for b in (anchor.get("block_ids") or []) if str(b)
                }
                # 子集合同：锚块集必须非空且 ⊆ 所属 section 的实际块集——
                # 外条款块（借位）与空块集都拒；Claim locator 辖域过滤在此之后执行。
                section_blocks = (
                    identity.get("section_block_ids")
                    if isinstance(identity, dict) else None
                )
                if (
                    not isinstance(identity, dict)
                    or identity.get("sentence_index") != anchor.get("sentence_index")
                    or not anchor_hash
                    or anchor_hash != identity.get("source_text_hash")
                    or not isinstance(section_blocks, frozenset)
                    or not anchor_blocks
                    or not anchor_blocks <= section_blocks
                ):
                    text_identity_dropped += 1
                    continue
            confined.append(dict(anchor))
        edge["target_source_anchors"] = confined
        if text_identity_dropped:
            edge["target_source_anchor_text_mismatch"] = text_identity_dropped
        if not confined:
            edge["target_source_anchor_stale"] = True
    return edge


def _group(
    claim: dict[str, Any],
    *,
    target_generation_id: str,
    targets: list[tuple[dict[str, Any], list[str], list[dict[str, Any]]]],
    validation_method: str,
    verifier_runtime_fingerprint: str,
    validation_generation_run_id: str,
    controlled_term_aliases: dict[str, list[str]] | None,
    obligation_hashes: dict[tuple[str, int], str] | None = None,
) -> dict[str, Any]:
    content, claim_start, claim_end = _claim_content(claim)
    relation = "merged_into" if len(targets) > 1 else "generated_from"
    locator_blocks = _claim_locator_blocks(claim)
    edges = [
        _edge(
            target,
            claim_hash=str(claim.get("claim_hash") or ""),
            target_generation_id=target_generation_id,
            produced_evidence=evidence,
            relation=relation,
            claim_locator_blocks=locator_blocks,
            obligation_hashes=obligation_hashes,
        )
        for target, _basis, evidence in targets
    ]
    basis = list(dict.fromkeys(value for _target, values, _evidence in targets for value in values))
    produced = [item for edge in edges for item in edge["produced_evidence"]]
    group_hash = _sha256({
        "claim_hash": claim.get("claim_hash"),
        "edges": [edge["edge_id"] for edge in edges],
        "validation_method": validation_method,
    })
    prefilter = (
        {"version": CLAIM_EDGE_PREFILTER_VERSION, "status": "not_required",
         "protected_facts": [], "missing_protected_facts": []}
        if validation_method == "deterministic_verbatim"
        else reject_only_prefilter(
            content,
            produced,
            controlled_term_aliases=controlled_term_aliases,
        )
    )
    inactive = [edge for edge in edges if edge["target_review_eligibility"] != "active"]
    # M2 §4.4：源锚全部落在 claim locator 辖域外的 edge 标 stale——组保持审计行
    # 但不得用于关闭 Claim（与 target_rejected 同款 invalid 语义，不改账本行数）。
    anchor_stale = [
        edge for edge in edges if edge.get("target_source_anchor_stale") is True
    ]
    status = "validated" if validation_method == "deterministic_verbatim" else "proposed"
    invalid_reason = ""
    if inactive:
        status = "invalid"
        invalid_reason = (
            "target_rejected" if any(edge["target_review_eligibility"] == "rejected" for edge in inactive)
            else "target_review_unknown"
        )
    elif anchor_stale:
        status = "invalid"
        invalid_reason = "target_source_anchor_stale"
    elif prefilter["status"] == "reject":
        status = "invalid"
        invalid_reason = "protected_fact_missing"
    group = {
        "schema": CLAIM_COVERAGE_GROUP_SCHEMA,
        "document_generation_id": claim["document_generation_id"],
        "catalog_generation_id": claim["catalog_generation_id"],
        "claim_id": claim["claim_id"],
        "claim_hash": claim["claim_hash"],
        "coverage_group_id": "CGR-" + group_hash.removeprefix("sha256:")[:16],
        "source_evidence": {
            "text": content,
            "claim_start": claim_start,
            "claim_end": claim_end,
            "match_method": "verbatim_span",
            "locator": dict(claim.get("locator") or {}),
        },
        "edges": edges,
        "proposal_basis": basis,
        "prefilter": prefilter,
        "validation_method": validation_method,
        "verifier_runtime_fingerprint": verifier_runtime_fingerprint,
        "validator_version": (
            "deterministic-verbatim-v2-product-obligation"
            if validation_method == "deterministic_verbatim"
            else CLAIM_COVERAGE_VALIDATOR_VERSION
        ),
        "validator_request_id": "",
        "validator_checks": (
            {name: True for name in SEMANTIC_COVERAGE_CHECKS}
            if validation_method == "deterministic_verbatim"
            else {}
        ),
        "validator_reason": "",
        "validation_source": {
            "generation_run_id": (
                "" if validation_method == "deterministic_verbatim"
                else validation_generation_run_id
            ),
            "request_id": "",
        },
        "status": status,
        "invalid_reason": invalid_reason,
        "validation_reused": False,
    }
    group["validation_input_hash"] = _sha256({
        "claim_hash": group["claim_hash"],
        "source_evidence": group["source_evidence"],
        "edges": [{
            "target_requirement_id": edge["target_requirement_id"],
            "target_fingerprint": edge["target_fingerprint"],
            "target_review_revision": edge["target_review_revision"],
            "relation": edge["relation"],
            "produced_evidence": edge["produced_evidence"],
        } for edge in edges],
        "prefilter": prefilter,
        "validation_method": validation_method,
        "verifier_runtime_fingerprint": verifier_runtime_fingerprint,
        "validator_version": group["validator_version"],
    })
    return group


def coverage_group_record_error(
    group: dict[str, Any],
    claim: dict[str, Any],
    *,
    target_records: list[dict[str, Any]] | None = None,
    target_generation_id: str = "",
    verifier_runtime_fingerprint: str = "",
    obligation_hashes: dict[tuple[str, int], str] | None = None,
) -> str | None:
    """Return why a persisted coverage group is not a deterministic replay.

    Target existence, review authority, and target-field locators require the
    current target store and are checked by ``claim_artifacts``.  This function
    owns every identity/hash derived solely from the claim and persisted edge
    evidence so publish and load cannot drift into separate formulas.
    """
    content, claim_start, claim_end = _claim_content(claim)
    expected_source = {
        "text": content,
        "claim_start": claim_start,
        "claim_end": claim_end,
        "match_method": "verbatim_span",
        "locator": dict(claim.get("locator") or {}),
    }
    if group.get("source_evidence") != expected_source:
        return "source_evidence_mismatch"

    edges = group.get("edges")
    if not isinstance(edges, list) or not edges:
        return "edges_missing"
    expected_edge_ids: list[str] = []
    for edge in edges:
        if not isinstance(edge, dict):
            return "edge_invalid"
        produced_evidence = edge.get("produced_evidence")
        if not isinstance(produced_evidence, list) or not produced_evidence:
            return "edge_evidence_missing"
        edge_hash = _sha256({
            "claim_hash": claim.get("claim_hash"),
            "target_id": edge.get("target_requirement_id"),
            "target_fingerprint": edge.get("target_fingerprint"),
            "produced_evidence": produced_evidence,
        })
        expected_edge_id = "CED-" + edge_hash.removeprefix("sha256:")[:16]
        if str(edge.get("edge_id") or "") != expected_edge_id:
            return "edge_id_mismatch"
        expected_edge_ids.append(expected_edge_id)

    validation_method = str(group.get("validation_method") or "")
    validation_source = group.get("validation_source")
    if (
        not isinstance(validation_source, dict)
        or set(validation_source) != {"generation_run_id", "request_id"}
        or not isinstance(validation_source.get("generation_run_id"), str)
        or not isinstance(validation_source.get("request_id"), str)
    ):
        return "validation_source_invalid"
    if str(group.get("verifier_runtime_fingerprint") or "") != str(
        verifier_runtime_fingerprint or ""
    ):
        return "verifier_runtime_fingerprint_mismatch"
    if validation_method == "deterministic_verbatim":
        if group.get("validator_version") != "deterministic-verbatim-v2-product-obligation":
            return "deterministic_validator_version_mismatch"
        if group.get("validator_request_id") != "":
            return "deterministic_validator_request_invalid"
        if validation_source != {"generation_run_id": "", "request_id": ""}:
            return "deterministic_validation_source_invalid"
        if group.get("validator_checks") != {
            name: True for name in SEMANTIC_COVERAGE_CHECKS
        }:
            return "deterministic_obligation_checks_incomplete"
    elif validation_method == "independent_semantic":
        if group.get("validator_version") != CLAIM_COVERAGE_VALIDATOR_VERSION:
            return "semantic_validator_version_mismatch"
        if group.get("status") == "validated" and (
            not str(group.get("validator_request_id") or "")
            or not _semantic_checks_complete({
                "checks": dict(group.get("validator_checks") or {})
            })
        ):
            return "semantic_validation_not_current"
        request_id = str(group.get("validator_request_id") or "")
        if request_id and (
            validation_source.get("request_id") != request_id
            or not validation_source.get("generation_run_id")
        ):
            return "semantic_validation_source_invalid"
    elif validation_method == "expert":
        pass
    else:
        return "validation_method_invalid"
    group_hash = _sha256({
        "claim_hash": claim.get("claim_hash"),
        "edges": expected_edge_ids,
        "validation_method": validation_method,
    })
    expected_group_id = "CGR-" + group_hash.removeprefix("sha256:")[:16]
    if str(group.get("coverage_group_id") or "") != expected_group_id:
        return "coverage_group_id_mismatch"

    prefilter = group.get("prefilter")
    expected_input_hash = _sha256({
        "claim_hash": claim.get("claim_hash"),
        "source_evidence": expected_source,
        "edges": [{
            "target_requirement_id": edge.get("target_requirement_id"),
            "target_fingerprint": edge.get("target_fingerprint"),
            "target_review_revision": edge.get("target_review_revision"),
            "relation": edge.get("relation"),
            "produced_evidence": edge.get("produced_evidence"),
        } for edge in edges],
        "prefilter": prefilter,
        "validation_method": validation_method,
        "verifier_runtime_fingerprint": verifier_runtime_fingerprint,
        "validator_version": group.get("validator_version"),
    })
    if str(group.get("validation_input_hash") or "") != expected_input_hash:
        return "validation_input_hash_mismatch"

    if target_records is not None:
        targets_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for target in target_records:
            targets_by_key[(
                str(target.get("target_requirement_id") or ""),
                str(target.get("target_fingerprint") or ""),
            )].append(target)
        expected_basis: list[str] = []
        relation = "merged_into" if len(edges) > 1 else "generated_from"
        locator_blocks = _claim_locator_blocks(claim)
        for edge in edges:
            key = (
                str(edge.get("target_requirement_id") or ""),
                str(edge.get("target_fingerprint") or ""),
            )
            matches = targets_by_key.get(key, [])
            if len(matches) != 1:
                return "target_missing_or_ambiguous"
            target = matches[0]
            evidence = [dict(item) for item in (edge.get("produced_evidence") or [])]
            expected_edge = _edge(
                target,
                claim_hash=str(claim.get("claim_hash") or ""),
                target_generation_id=target_generation_id,
                produced_evidence=evidence,
                relation=relation,
                claim_locator_blocks=locator_blocks,
                obligation_hashes=obligation_hashes,
            )
            if edge != expected_edge:
                return "edge_target_authority_mismatch"
            # §4.4 加载/fold 校验：stale 源锚 edge 不得支撑 validated 组（发布与加载
            # 同一公式，锚漂移/辖域失配在此 fail-closed）。
            if (
                edge.get("target_source_anchor_stale") is True
                and str(group.get("status") or "") == "validated"
            ):
                return "target_source_anchor_stale"
            expected_basis.extend(_candidate_basis(claim, target))
        if group.get("proposal_basis") != list(dict.fromkeys(expected_basis)):
            return "proposal_basis_mismatch"
    return None


def _semantic_verifier_request(group: dict[str, Any]) -> dict[str, Any]:
    """Strip proposer conclusions before the independent validation request."""
    return {
        "coverage_group_id": str(group.get("coverage_group_id") or ""),
        "claim_id": str(group.get("claim_id") or ""),
        "claim_hash": str(group.get("claim_hash") or ""),
        "source_evidence": dict(group.get("source_evidence") or {}),
        "edges": [{
            "target_requirement_id": str(edge.get("target_requirement_id") or ""),
            "target_fingerprint": str(edge.get("target_fingerprint") or ""),
            "produced_evidence": [dict(item) for item in (edge.get("produced_evidence") or [])],
        } for edge in (group.get("edges") or [])],
    }


def _compact_coverage_transport(
    groups: list[dict[str, Any]],
) -> tuple[list[list[str]], list[list[Any]], dict[int, str]]:
    """Deduplicate target evidence while retaining one independent row per group."""
    target_refs: dict[tuple[str, str, str], int] = {}
    target_evidence: list[list[str]] = []
    compact_groups: list[list[Any]] = []
    group_ids: dict[int, str] = {}
    for group_ref, group in enumerate(groups):
        group_id = str(group.get("coverage_group_id") or "")
        group_ids[group_ref] = group_id
        edge_refs: list[int] = []
        for edge in group.get("edges") or []:
            evidence_texts = [
                str(item.get("text") or "")
                for item in (edge.get("produced_evidence") or [])
            ]
            key = (
                str(edge.get("target_requirement_id") or ""),
                str(edge.get("target_fingerprint") or ""),
                _sha256(evidence_texts),
            )
            if key not in target_refs:
                target_refs[key] = len(target_evidence)
                target_evidence.append(evidence_texts)
            edge_refs.append(target_refs[key])
        compact_groups.append([
            group_ref,
            str((group.get("source_evidence") or {}).get("text") or ""),
            list(dict.fromkeys(edge_refs)),
        ])
    return target_evidence, compact_groups, group_ids


def _compact_negative_transport(
    claims: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deduplicate owner-unit context across a bounded negative batch."""
    context_refs: dict[tuple[str, str], int] = {}
    contexts: list[dict[str, Any]] = []
    compact_claims: list[dict[str, Any]] = []
    for claim in claims:
        context = dict(claim.get("unit_context") or {})
        context_key = (
            str(context.get("unit_id") or ""),
            str(context.get("prompt_hash") or ""),
        )
        if context_key not in context_refs:
            context_refs[context_key] = len(contexts)
            contexts.append({
                "unit_id": context_key[0],
                "section_path": list(context.get("section_path") or []),
                "prompt": str(context.get("prompt") or ""),
                "prompt_hash": context_key[1],
            })
        source = dict(claim.get("source_evidence") or {})
        compact_claims.append({
            "claim_id": str(claim.get("claim_id") or ""),
            "source_evidence": {
                "text": str(source.get("text") or ""),
                "claim_start": source.get("claim_start"),
                "claim_end": source.get("claim_end"),
            },
            "unit_ref": context_refs[context_key],
        })
    return contexts, compact_claims


def _payload_utf8_size(payload: dict[str, Any]) -> int:
    return len(serialize_json_request_body(payload))


def _verifier_user_prompt(user_request: dict[str, Any]) -> str:
    return json.dumps(
        user_request,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _verifier_http_payload(
    runtime: dict[str, Any] | None,
    system_prompt: str,
    user_request: dict[str, Any],
) -> dict[str, Any]:
    """Build a conservative, exact-shape first-attempt chat HTTP body."""
    resolved = dict(runtime or {})
    config = LLMClientConfig(
        base_url=str(resolved.get("base_url") or ""),
        model=str(resolved.get("model") or ""),
        temperature=float(resolved.get("temperature") or 0.0),
        max_tokens=int(resolved.get("max_tokens") or 0),
    )
    return build_chat_json_request_payload(
        config,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _verifier_user_prompt(user_request)},
        ],
        json_mode=True,
    )


def _coverage_verifier_request_payload(
    groups: list[dict[str, Any]],
    *,
    batch_id: str,
    request_id: str,
    round_index: int,
) -> dict[str, Any]:
    target_evidence, compact_groups, _group_ids = _compact_coverage_transport(groups)
    return {
        "schema": "claim-coverage-verifier-request/v2",
        "request_id": f"{request_id}-R{round_index}",
        "batch_request_id": request_id,
        "verification_round": round_index,
        "batch_id": batch_id,
        "target_evidence": target_evidence,
        "groups": compact_groups,
    }


def _negative_proposer_request_payload(
    claims: list[dict[str, Any]],
    *,
    batch_id: str,
    request_id: str,
) -> dict[str, Any]:
    unit_contexts, compact_claims = _compact_negative_transport(claims)
    return {
        "schema": "claim-negative-proposer-request/v1",
        "request_id": request_id,
        "batch_id": batch_id,
        "unit_contexts": unit_contexts,
        "claims": compact_claims,
    }


def _negative_verifier_request_payload(
    claims: list[dict[str, Any]],
    *,
    batch_id: str,
    request_id: str,
    round_index: int,
) -> dict[str, Any]:
    unit_contexts, compact_claims = _compact_negative_transport(claims)
    return {
        "schema": "claim-negative-verifier-request/v1",
        "request_id": f"{request_id}-R{round_index}",
        "batch_request_id": request_id,
        "verification_round": round_index,
        "batch_id": batch_id,
        "unit_contexts": unit_contexts,
        "claims": compact_claims,
    }


def _batch_index_width(row_count: int) -> int:
    # A batch count cannot exceed its input row count. Pinning this maximum
    # width keeps the planning placeholder at least as large as every real ID.
    return max(4, len(str(max(1, row_count))))


def _bounded_batches(
    rows: list[dict[str, Any]],
    *,
    max_items: int,
    max_utf8_bytes: int,
    payload: Callable[[list[dict[str, Any]]], dict[str, Any]],
) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    oversized: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for row in rows:
        if _payload_utf8_size(payload([row])) > max_utf8_bytes:
            if current:
                batches.append(current)
                current = []
            oversized.append(row)
            continue
        candidate = [*current, row]
        if current and (
            len(candidate) > max_items
            or _payload_utf8_size(payload(candidate)) > max_utf8_bytes
        ):
            batches.append(current)
            current = [row]
        else:
            current = candidate
    if current:
        batches.append(current)
    return batches, oversized


def _coverage_batches(
    rows: list[dict[str, Any]],
    *,
    runtime: dict[str, Any] | None = None,
) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]]]:
    index_width = _batch_index_width(len(rows))
    request_id = "CVR-" + "0" * 32
    return _bounded_batches(
        rows,
        max_items=CLAIM_COVERAGE_BATCH_MAX_GROUPS,
        max_utf8_bytes=CLAIM_COVERAGE_BATCH_MAX_UTF8_BYTES,
        payload=lambda batch: _verifier_http_payload(
            runtime,
            _SEMANTIC_VERIFIER_SYSTEM,
            _coverage_verifier_request_payload(
                batch,
                batch_id="COVERAGE-BATCH-" + "0" * index_width,
                request_id=request_id,
                round_index=1,
            ),
        ),
    )


def _negative_batches(
    rows: list[dict[str, Any]],
    *,
    runtime: dict[str, Any] | None = None,
    operation: str = "verifier",
) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]]]:
    index_width = _batch_index_width(len(rows))
    if operation == "proposer":
        request_id = "CNP-" + "0" * 32
        payload = lambda batch: _verifier_http_payload(
            runtime,
            _SEMANTIC_NEGATIVE_PROPOSER_SYSTEM,
            _negative_proposer_request_payload(
                batch,
                batch_id="NEGATIVE-PROPOSER-BATCH-" + "0" * index_width,
                request_id=request_id,
            ),
        )
    elif operation == "verifier":
        request_id = "CNV-" + "0" * 32
        payload = lambda batch: _verifier_http_payload(
            runtime,
            _SEMANTIC_NEGATIVE_VERIFIER_SYSTEM,
            _negative_verifier_request_payload(
                batch,
                batch_id="NEGATIVE-VERIFIER-BATCH-" + "0" * index_width,
                request_id=request_id,
                round_index=1,
            ),
        )
    else:
        raise ValueError("unknown negative verifier batch operation")
    return _bounded_batches(
        rows,
        max_items=CLAIM_NEGATIVE_BATCH_MAX_CLAIMS,
        max_utf8_bytes=CLAIM_NEGATIVE_BATCH_MAX_UTF8_BYTES,
        payload=payload,
    )


def _logical_call_ceiling(
    *,
    baseline_calls: int,
    baseline_usage_complete: bool,
    baseline_lineage_match: bool,
) -> int | None:
    if not baseline_usage_complete or not baseline_lineage_match or baseline_calls <= 0:
        return None
    relative_limit = int(baseline_calls * CLAIM_VERIFIER_CALL_INCREASE_LIMIT)
    return max(1, int(relative_limit * CLAIM_VERIFIER_LOGICAL_CALL_HEADROOM))


def _select_negative_probe_requests(
    requests: list[dict[str, Any]],
    *,
    max_claims: int,
    max_units: int,
) -> list[dict[str, Any]]:
    """Select whole, evenly spaced owner units; never classify omitted claims."""
    if max_claims <= 0 or max_units <= 0:
        return []
    by_unit: dict[str, list[dict[str, Any]]] = {}
    for request in requests:
        unit_id = str((request.get("unit_context") or {}).get("unit_id") or "")
        by_unit.setdefault(unit_id, []).append(request)
    unit_ids = list(by_unit)
    selected_unit_count = min(len(unit_ids), max_units)
    if selected_unit_count == len(unit_ids):
        selected_ids = unit_ids
    elif selected_unit_count == 1:
        selected_ids = [unit_ids[len(unit_ids) // 2]]
    else:
        selected_indexes = {
            round(index * (len(unit_ids) - 1) / (selected_unit_count - 1))
            for index in range(selected_unit_count)
        }
        selected_ids = [unit_ids[index] for index in sorted(selected_indexes)]
    selected: list[dict[str, Any]] = []
    for unit_id in selected_ids:
        for request in by_unit[unit_id]:
            if len(selected) >= max_claims:
                return selected
            selected.append(request)
    return selected


def _strict_nonnegative_int(value: object, *, default: int = 0) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return default


def _strict_boolean_checks(
    value: object,
    names: tuple[str, ...],
) -> dict[str, bool] | None:
    if not isinstance(value, dict) or set(value) != set(names):
        return None
    if any(not isinstance(value[name], bool) for name in names):
        return None
    return {name: value[name] for name in names}


def _coverage_decision_is_consistent(
    covered: object,
    checks: dict[str, bool],
) -> bool:
    if covered is not True and covered is not False and covered is not None:
        return False
    all_checks_pass = all(checks.values())
    return (covered is True) == all_checks_pass


def _verifier_usage_complete(
    *,
    call_count: int,
    tokens: int,
    declared_complete: object,
) -> bool:
    """A successful verifier operation cannot consume zero provider tokens."""
    return declared_complete is True and (call_count == 0 or tokens > 0)


def make_semantic_coverage_verifier(
    chat_with_meta: Callable[[str, str], tuple[dict[str, Any], dict[str, Any]]],
    *,
    rounds: int = 1,
) -> SemanticVerifier:
    """Create the independent, unit-batched verifier used by the Phase 0B probe."""
    resolved_rounds = max(1, min(3, int(rounds)))

    def verify(batch_id: str, groups: list[dict[str, Any]]) -> dict[str, Any]:
        expected_ids = {str(group.get("coverage_group_id") or "") for group in groups}
        _target_evidence, _compact_groups, group_ids = _compact_coverage_transport(groups)
        request_id = "CVR-" + uuid.uuid4().hex
        round_decisions: list[dict[str, dict[str, Any]]] = []
        total_tokens = 0
        usage_complete = True
        failed_calls = 0
        operation_failures = 0
        call_count = 0
        for round_index in range(resolved_rounds):
            payload = _coverage_verifier_request_payload(
                groups,
                batch_id=batch_id,
                request_id=request_id,
                round_index=round_index + 1,
            )
            try:
                response, meta = chat_with_meta(
                    _SEMANTIC_VERIFIER_SYSTEM,
                    _verifier_user_prompt(payload),
                )
            except LLMBudgetExceeded:
                raise
            except Exception:
                failed_calls += 1
                operation_failures += 1
                usage_complete = False
                round_decisions.append({})
                call_count += 1
                continue
            round_calls = max(1, _strict_nonnegative_int(
                (meta or {}).get("call_count"), default=1,
            ))
            round_failed_calls = _strict_nonnegative_int(
                (meta or {}).get("failed_call_count"),
            )
            usage = meta.get("usage") if isinstance(meta, dict) else None
            round_tokens = _strict_nonnegative_int(
                (usage or {}).get("total_tokens") if isinstance(usage, dict) else None,
            )
            call_count += round_calls
            failed_calls += round_failed_calls
            total_tokens += round_tokens
            if not _verifier_usage_complete(
                call_count=round_calls,
                tokens=round_tokens,
                declared_complete=(meta or {}).get("usage_complete"),
            ):
                usage_complete = False
            raw_decisions = response.get("decisions") if isinstance(response, dict) else None
            if not isinstance(raw_decisions, list):
                operation_failures += 1
                round_decisions.append({})
                continue
            parsed: dict[str, dict[str, Any]] = {}
            duplicate_ids: set[str] = set()
            malformed = False
            for raw in raw_decisions:
                reason = ""
                if isinstance(raw, list) and len(raw) == 3:
                    group_ref, covered, raw_checks = raw
                    if (
                        not isinstance(group_ref, int)
                        or isinstance(group_ref, bool)
                        or group_ref not in group_ids
                        or (covered is not True and covered is not False and covered is not None)
                        or not isinstance(raw_checks, list)
                        or len(raw_checks) != len(SEMANTIC_COVERAGE_CHECKS)
                        or any(not isinstance(value, bool) for value in raw_checks)
                    ):
                        malformed = True
                        continue
                    group_id = group_ids[group_ref]
                    checks = dict(zip(SEMANTIC_COVERAGE_CHECKS, raw_checks))
                    if not _coverage_decision_is_consistent(covered, checks):
                        malformed = True
                        continue
                elif isinstance(raw, dict):
                    group_id = str(raw.get("coverage_group_id") or "")
                    covered = raw.get("covered")
                    reason = str(raw.get("reason") or "")[:1000]
                    checks = _strict_boolean_checks(
                        raw.get("checks"), SEMANTIC_COVERAGE_CHECKS,
                    )
                    if (
                        "covered" not in raw
                        or checks is None
                        or not _coverage_decision_is_consistent(covered, checks)
                    ):
                        malformed = True
                        continue
                else:
                    malformed = True
                    continue
                if group_id not in expected_ids:
                    malformed = True
                    continue
                if group_id in parsed:
                    duplicate_ids.add(group_id)
                    malformed = True
                    continue
                parsed[group_id] = {
                    "covered": covered,
                    "checks": checks,
                    "reason": reason,
                }
            for group_id in duplicate_ids:
                parsed.pop(group_id, None)
            if malformed or set(parsed) != expected_ids:
                operation_failures += 1
            round_decisions.append(parsed)

        decisions: dict[str, dict[str, Any]] = {}
        for group_id in sorted(expected_ids):
            rows = [batch.get(group_id) for batch in round_decisions]
            if not rows or any(not isinstance(row, dict) for row in rows):
                continue
            covered_values = [row.get("covered") for row in rows if isinstance(row, dict)]
            covered: bool | None = None
            if all(value is True for value in covered_values):
                covered = True
            elif all(value is False for value in covered_values):
                covered = False
            checks = {
                name: (
                    True if all((row.get("checks") or {}).get(name) is True for row in rows)
                    else False if all((row.get("checks") or {}).get(name) is False for row in rows)
                    else None
                )
                for name in SEMANTIC_COVERAGE_CHECKS
            }
            decisions[group_id] = {
                "covered": covered,
                "checks": checks,
                "reason": " | ".join(
                    str(row.get("reason") or "") for row in rows if row.get("reason")
                )[:2000],
            }
        return {
            "request_id": request_id,
            "call_count": call_count,
            "failed_call_count": failed_calls,
            "operation_failure_count": operation_failures,
            "tokens": total_tokens,
            "usage_complete": usage_complete,
            "decisions": decisions,
        }

    return verify


def _negative_evidence_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        start = item.get("start")
        end = item.get("end")
        if (not isinstance(start, int) or isinstance(start, bool)
                or not isinstance(end, int) or isinstance(end, bool)):
            continue
        text = str(item.get("text") or "")
        if start < 0 or end <= start or not text:
            continue
        rows.append({
            "start": start,
            "end": end,
            "text": text,
        })
    return rows


def make_semantic_negative_proposer(
    chat_with_meta: Callable[[str, str], tuple[dict[str, Any], dict[str, Any]]],
) -> SemanticNegativeProposer:
    """Create the unit-batched negative proposer; its output never closes a claim."""
    def propose(batch_id: str, claims: list[dict[str, Any]]) -> dict[str, Any]:
        expected_ids = {str(claim.get("claim_id") or "") for claim in claims}
        request_id = "CNP-" + uuid.uuid4().hex
        payload = _negative_proposer_request_payload(
            claims,
            batch_id=batch_id,
            request_id=request_id,
        )
        try:
            response, meta = chat_with_meta(
                _SEMANTIC_NEGATIVE_PROPOSER_SYSTEM,
                _verifier_user_prompt(payload),
            )
        except LLMBudgetExceeded:
            raise
        except Exception:
            return {
                "request_id": request_id,
                "call_count": 1,
                "failed_call_count": 1,
                "operation_failure_count": 1,
                "tokens": 0,
                "usage_complete": False,
                "decisions": {},
            }
        raw_rows = response.get("proposals") if isinstance(response, dict) else None
        decisions: dict[str, dict[str, Any]] = {}
        duplicates: set[str] = set()
        operation_failures = 0
        if isinstance(raw_rows, list):
            for raw in raw_rows:
                if not isinstance(raw, dict):
                    operation_failures = 1
                    continue
                claim_id = str(raw.get("claim_id") or "")
                if claim_id not in expected_ids:
                    operation_failures = 1
                    continue
                if claim_id in decisions:
                    duplicates.add(claim_id)
                    operation_failures = 1
                    continue
                non_normative = raw.get("non_normative")
                if non_normative not in {True, False, None}:
                    non_normative = None
                reason = str(raw.get("reason") or "")
                if reason not in SEMANTIC_NEGATIVE_REASONS:
                    reason = ""
                decisions[claim_id] = {
                    "non_normative": non_normative,
                    "reason": reason,
                    "evidence": _negative_evidence_rows(raw.get("evidence")),
                    "rationale": str(raw.get("rationale") or "")[:2000],
                }
        for claim_id in duplicates:
            decisions.pop(claim_id, None)
        if not isinstance(raw_rows, list):
            operation_failures = 1
        usage = meta.get("usage") if isinstance(meta, dict) else None
        call_count = max(1, _strict_nonnegative_int(
            (meta or {}).get("call_count"), default=1,
        ))
        tokens = _strict_nonnegative_int(
            (usage or {}).get("total_tokens") if isinstance(usage, dict) else None,
        )
        return {
            "request_id": request_id,
            "call_count": call_count,
            "failed_call_count": _strict_nonnegative_int(
                (meta or {}).get("failed_call_count"),
            ),
            "operation_failure_count": operation_failures,
            "tokens": tokens,
            "usage_complete": _verifier_usage_complete(
                call_count=call_count,
                tokens=tokens,
                declared_complete=(meta or {}).get("usage_complete"),
            ),
            "decisions": decisions,
        }

    return propose


def make_semantic_negative_verifier(
    chat_with_meta: Callable[[str, str], tuple[dict[str, Any], dict[str, Any]]],
    *,
    rounds: int = 1,
) -> SemanticNegativeVerifier:
    """Create a proposal-blind, multi-round semantic-negative verifier."""
    resolved_rounds = max(1, min(3, int(rounds)))

    def verify(batch_id: str, claims: list[dict[str, Any]]) -> dict[str, Any]:
        expected_ids = {str(claim.get("claim_id") or "") for claim in claims}
        source_text_by_id = {
            str(claim.get("claim_id") or ""): str(
                (claim.get("source_evidence") or {}).get("text") or ""
            )
            for claim in claims
        }
        request_id = "CNV-" + uuid.uuid4().hex
        round_decisions: list[dict[str, dict[str, Any]]] = []
        total_tokens = 0
        usage_complete = True
        failed_calls = 0
        operation_failures = 0
        call_count = 0
        for round_index in range(resolved_rounds):
            payload = _negative_verifier_request_payload(
                claims,
                batch_id=batch_id,
                request_id=request_id,
                round_index=round_index + 1,
            )
            try:
                response, meta = chat_with_meta(
                    _SEMANTIC_NEGATIVE_VERIFIER_SYSTEM,
                    _verifier_user_prompt(payload),
                )
            except LLMBudgetExceeded:
                raise
            except Exception:
                call_count += 1
                failed_calls += 1
                operation_failures += 1
                usage_complete = False
                round_decisions.append({})
                continue
            round_calls = max(1, _strict_nonnegative_int(
                (meta or {}).get("call_count"), default=1,
            ))
            round_failed_calls = _strict_nonnegative_int(
                (meta or {}).get("failed_call_count"),
            )
            usage = meta.get("usage") if isinstance(meta, dict) else None
            round_tokens = _strict_nonnegative_int(
                (usage or {}).get("total_tokens") if isinstance(usage, dict) else None,
            )
            call_count += round_calls
            failed_calls += round_failed_calls
            total_tokens += round_tokens
            if not _verifier_usage_complete(
                call_count=round_calls,
                tokens=round_tokens,
                declared_complete=(meta or {}).get("usage_complete"),
            ):
                usage_complete = False
            raw_rows = response.get("decisions") if isinstance(response, dict) else None
            parsed: dict[str, dict[str, Any]] = {}
            duplicates: set[str] = set()
            malformed = False
            if isinstance(raw_rows, list):
                for raw in raw_rows:
                    if not isinstance(raw, dict):
                        malformed = True
                        continue
                    claim_id = str(raw.get("claim_id") or "")
                    if claim_id not in expected_ids:
                        malformed = True
                        continue
                    if claim_id in parsed:
                        duplicates.add(claim_id)
                        malformed = True
                        continue
                    non_normative = raw.get("non_normative")
                    checks = _strict_boolean_checks(
                        raw.get("checks"), SEMANTIC_NEGATIVE_CHECKS,
                    )
                    reason = raw.get("reason")
                    evidence = _negative_evidence_rows(raw.get("evidence"))
                    if (
                        "non_normative" not in raw
                        or (
                            non_normative is not True
                            and non_normative is not False
                            and non_normative is not None
                        )
                        or checks is None
                        or (non_normative is True) != all(checks.values())
                        or not isinstance(reason, str)
                        or reason not in SEMANTIC_NEGATIVE_REASONS
                        or not isinstance(raw.get("evidence"), list)
                        or evidence != raw.get("evidence")
                        or not _negative_evidence_is_current(
                            evidence, source_text_by_id[claim_id],
                        )
                    ):
                        malformed = True
                        continue
                    parsed[claim_id] = {
                        "non_normative": non_normative,
                        "reason": reason,
                        "checks": checks,
                        "evidence": evidence,
                        "rationale": str(raw.get("rationale") or "")[:2000],
                    }
            for claim_id in duplicates:
                parsed.pop(claim_id, None)
            if not isinstance(raw_rows, list) or malformed or set(parsed) != expected_ids:
                operation_failures += 1
            round_decisions.append(parsed)

        decisions: dict[str, dict[str, Any]] = {}
        for claim_id in sorted(expected_ids):
            rows = [batch.get(claim_id) for batch in round_decisions]
            if not rows or any(not isinstance(row, dict) for row in rows):
                continue
            non_normative_values = [row.get("non_normative") for row in rows]
            non_normative: bool | None = None
            if all(value is True for value in non_normative_values):
                non_normative = True
            elif all(value is False for value in non_normative_values):
                non_normative = False
            reasons = [str(row.get("reason") or "") for row in rows]
            reason = reasons[0] if reasons and reasons[0] and len(set(reasons)) == 1 else ""
            checks = {
                name: (
                    True if all((row.get("checks") or {}).get(name) is True for row in rows)
                    else False if all((row.get("checks") or {}).get(name) is False for row in rows)
                    else None
                )
                for name in SEMANTIC_NEGATIVE_CHECKS
            }
            evidence_rows = [row.get("evidence") or [] for row in rows]
            evidence = evidence_rows[0] if evidence_rows and all(
                item == evidence_rows[0] for item in evidence_rows
            ) else []
            decisions[claim_id] = {
                "non_normative": non_normative,
                "reason": reason,
                "checks": checks,
                "evidence": evidence,
                "rationale": " | ".join(
                    str(row.get("rationale") or "") for row in rows
                    if row.get("rationale")
                )[:2000],
                "disagreement": (
                    len(set(non_normative_values)) > 1
                    or len(set(reasons)) > 1
                    or any(value is None for value in checks.values())
                    or not evidence
                ),
            }
        return {
            "request_id": request_id,
            "call_count": call_count,
            "failed_call_count": failed_calls,
            "operation_failure_count": operation_failures,
            "tokens": total_tokens,
            "usage_complete": usage_complete,
            "decisions": decisions,
        }

    return verify


def _semantic_checks_complete(decision: dict[str, Any]) -> bool:
    checks = decision.get("checks")
    return isinstance(checks, dict) and all(checks.get(name) is True for name in SEMANTIC_COVERAGE_CHECKS)


def _semantic_verifier_envelope(result: object) -> dict[str, Any] | None:
    """Normalize the batch contract while accepting the initial Phase 0 probe shape."""
    if not isinstance(result, dict):
        return None
    if isinstance(result.get("decisions"), dict):
        call_count = max(1, _strict_nonnegative_int(
            result.get("call_count"), default=1,
        ))
        tokens = _strict_nonnegative_int(result.get("tokens"))
        return {
            "decisions": result["decisions"],
            "request_id": str(result.get("request_id") or ""),
            "call_count": call_count,
            "failed_call_count": _strict_nonnegative_int(
                result.get("failed_call_count")
            ),
            "operation_failure_count": _strict_nonnegative_int(
                result.get("operation_failure_count")
            ),
            "tokens": tokens,
            "usage_complete": _verifier_usage_complete(
                call_count=call_count,
                tokens=tokens,
                declared_complete=result.get("usage_complete"),
            ),
        }
    meta = result.get("__meta__")
    decisions = {key: value for key, value in result.items() if key != "__meta__"}
    if isinstance(meta, dict):
        call_count = max(1, _strict_nonnegative_int(
            meta.get("call_count"), default=1,
        ))
        tokens = _strict_nonnegative_int(meta.get("total_tokens"))
        return {
            "decisions": decisions,
            "request_id": str(meta.get("request_id") or ""),
            "call_count": call_count,
            "failed_call_count": _strict_nonnegative_int(
                meta.get("failed_call_count")
            ),
            "operation_failure_count": _strict_nonnegative_int(
                meta.get("operation_failure_count")
            ),
            "tokens": tokens,
            "usage_complete": _verifier_usage_complete(
                call_count=call_count,
                tokens=tokens,
                declared_complete=meta.get("usage_complete"),
            ),
        }
    request_ids = {
        str(decision.get("request_id") or "")
        for decision in decisions.values()
        if isinstance(decision, dict) and decision.get("request_id")
    }
    return {
        "decisions": decisions,
        "request_id": request_ids.pop() if len(request_ids) == 1 else "",
        "call_count": 1,
        "failed_call_count": 0,
        "operation_failure_count": 0,
        "tokens": sum(
            _strict_nonnegative_int(decision.get("tokens"))
            for decision in decisions.values()
            if isinstance(decision, dict)
        ),
        "usage_complete": False,
    }


def _negative_claim_request(
    claim: dict[str, Any],
    unit: dict[str, Any],
) -> dict[str, Any]:
    content, claim_start, claim_end = _claim_content(claim)
    return {
        "claim_id": str(claim.get("claim_id") or ""),
        "claim_hash": str(claim.get("claim_hash") or ""),
        "source_evidence": {
            "text": content,
            "claim_start": claim_start,
            "claim_end": claim_end,
            "locator": dict(claim.get("locator") or {}),
        },
        "unit_context": {
            "unit_id": str(unit.get("unit_id") or ""),
            "section_path": list(unit.get("section_path") or []),
            "prompt": str(unit.get("prompt") or ""),
            "prompt_hash": str(unit.get("prompt_hash") or ""),
            "container_mappings": list(unit.get("container_mappings") or []),
        },
    }


def _negative_evidence_is_current(
    evidence: list[dict[str, Any]],
    claim_text: str,
) -> bool:
    if not evidence:
        return False
    for row in evidence:
        try:
            start = row["start"]
            end = row["end"]
        except (KeyError, TypeError):
            return False
        if (not isinstance(start, int) or isinstance(start, bool)
                or not isinstance(end, int) or isinstance(end, bool)
                or not 0 <= start < end <= len(claim_text)
                or claim_text[start:end] != str(row.get("text") or "")):
            return False
    return True


def _negative_checks_complete(decision: dict[str, Any]) -> bool:
    checks = decision.get("checks")
    return isinstance(checks, dict) and all(
        checks.get(name) is True for name in SEMANTIC_NEGATIVE_CHECKS
    )


def _negative_validation_input_hash(
    claim: dict[str, Any],
    request: dict[str, Any],
    verifier_runtime_fingerprint: str,
) -> str:
    return _sha256({
        "document_generation_id": claim.get("document_generation_id"),
        "catalog_generation_id": claim.get("catalog_generation_id"),
        "claim_hash": claim.get("claim_hash"),
        "source_evidence": request.get("source_evidence"),
        "unit_prompt_hash": request.get("unit_context", {}).get("prompt_hash"),
        "verifier_runtime_fingerprint": verifier_runtime_fingerprint,
        "proposal_version": CLAIM_LEDGER_PROMPT_VERSION,
        "negative_policy_version": CLAIM_NEGATIVE_POLICY_VERSION,
        "negative_validator_version": CLAIM_NEGATIVE_VALIDATOR_VERSION,
    })


def _negative_record(
    claim: dict[str, Any],
    request: dict[str, Any],
    proposal: dict[str, Any],
    *,
    request_id: str,
    verifier_runtime: dict[str, Any],
    validation_generation_run_id: str,
) -> dict[str, Any]:
    source_text = str(request.get("source_evidence", {}).get("text") or "")
    evidence = _negative_evidence_rows(proposal.get("evidence"))
    proposed_reason = str(proposal.get("reason") or "")
    proposal_valid = (
        proposal.get("non_normative") is True
        and proposed_reason in SEMANTIC_NEGATIVE_REASONS
        and _negative_evidence_is_current(evidence, source_text)
    )
    record = {
        "schema": CLAIM_SEMANTIC_NEGATIVE_SCHEMA,
        "document_generation_id": str(claim.get("document_generation_id") or ""),
        "catalog_generation_id": str(claim.get("catalog_generation_id") or ""),
        "claim_id": str(claim.get("claim_id") or ""),
        "claim_hash": str(claim.get("claim_hash") or ""),
        "verifier_runtime_fingerprint": str(verifier_runtime.get("fingerprint") or ""),
        "validation_input_hash": _negative_validation_input_hash(
            claim,
            request,
            str(verifier_runtime.get("fingerprint") or ""),
        ),
        "proposal": {
            "request_id": request_id,
            "version": CLAIM_LEDGER_PROMPT_VERSION,
            "reason": proposed_reason if proposed_reason in SEMANTIC_NEGATIVE_REASONS else "",
            "evidence": evidence,
            "rationale": str(proposal.get("rationale") or "")[:2000],
        },
        "validation": {
            "request_id": "",
            "version": CLAIM_NEGATIVE_VALIDATOR_VERSION,
            "reason": "",
            "checks": {},
            "evidence": [],
            "rationale": "",
        },
        "validation_source": {
            "generation_run_id": validation_generation_run_id,
            "request_id": "",
        },
        "status": "proposed" if proposal_valid else "invalid",
        "invalid_reason": "" if proposal_valid else "negative_proposal_incomplete",
        "validation_reused": False,
    }
    return record


def semantic_negative_record_error(
    record: object,
    claim: dict[str, Any],
    unit: dict[str, Any] | None,
    verifier_runtime: dict[str, Any],
) -> str | None:
    """Validate a persisted semantic-negative fact against its complete context."""
    if not isinstance(record, dict):
        return "negative_record_invalid"
    expected_fields = {
        "schema", "document_generation_id", "catalog_generation_id", "claim_id",
        "claim_hash", "verifier_runtime_fingerprint", "validation_input_hash",
        "proposal", "validation", "validation_source", "status", "invalid_reason",
        "validation_reused",
    }
    if set(record) != expected_fields or record.get("schema") != CLAIM_SEMANTIC_NEGATIVE_SCHEMA:
        return "negative_record_invalid"
    if claim.get("eligibility") != "claim" or unit is None:
        return "negative_owner_invalid"
    if str(unit.get("unit_id") or "") != str(claim.get("owner_unit_id") or ""):
        return "negative_owner_invalid"
    for field in (
        "document_generation_id", "catalog_generation_id", "claim_id", "claim_hash",
    ):
        if str(record.get(field) or "") != str(claim.get(field) or ""):
            return f"negative_{field}_mismatch"
    if not semantic_verifier_runtime_is_valid(verifier_runtime):
        return "negative_runtime_invalid"
    runtime_fingerprint = str(verifier_runtime.get("fingerprint") or "")
    if str(record.get("verifier_runtime_fingerprint") or "") != runtime_fingerprint:
        return "negative_runtime_mismatch"
    if verifier_runtime.get("enabled") is not True:
        return "negative_runtime_disabled"

    request = _negative_claim_request(claim, unit)
    expected_input_hash = _negative_validation_input_hash(
        claim,
        request,
        runtime_fingerprint,
    )
    if str(record.get("validation_input_hash") or "") != expected_input_hash:
        return "negative_validation_input_mismatch"

    proposal = record.get("proposal")
    validation = record.get("validation")
    validation_source = record.get("validation_source")
    if not isinstance(proposal, dict) or set(proposal) != {
        "request_id", "version", "reason", "evidence", "rationale",
    }:
        return "negative_proposal_invalid"
    if not isinstance(validation, dict) or set(validation) != {
        "request_id", "version", "reason", "checks", "evidence", "rationale",
    }:
        return "negative_validation_invalid"
    if (
        not isinstance(validation_source, dict)
        or set(validation_source) != {"generation_run_id", "request_id"}
        or not isinstance(validation_source.get("generation_run_id"), str)
        or not validation_source.get("generation_run_id")
        or not isinstance(validation_source.get("request_id"), str)
    ):
        return "negative_validation_source_invalid"
    if (
        not isinstance(proposal.get("request_id"), str)
        or not proposal.get("request_id")
        or proposal.get("version") != CLAIM_LEDGER_PROMPT_VERSION
        or not isinstance(proposal.get("reason"), str)
        or not isinstance(proposal.get("rationale"), str)
        or not isinstance(proposal.get("evidence"), list)
        or _negative_evidence_rows(proposal.get("evidence")) != proposal.get("evidence")
    ):
        return "negative_proposal_invalid"
    checks = validation.get("checks")
    if (
        not isinstance(validation.get("request_id"), str)
        or validation.get("version") != CLAIM_NEGATIVE_VALIDATOR_VERSION
        or not isinstance(validation.get("reason"), str)
        or not isinstance(validation.get("rationale"), str)
        or not isinstance(checks, dict)
        or not set(checks).issubset(SEMANTIC_NEGATIVE_CHECKS)
        or any(value is not True and value is not False and value is not None
               for value in checks.values())
        or not isinstance(validation.get("evidence"), list)
        or _negative_evidence_rows(validation.get("evidence")) != validation.get("evidence")
        or not isinstance(record.get("invalid_reason"), str)
        or not isinstance(record.get("validation_reused"), bool)
    ):
        return "negative_validation_invalid"

    status = record.get("status")
    if status not in {"proposed", "validated", "invalid"}:
        return "negative_status_invalid"
    claim_text = str(request.get("source_evidence", {}).get("text") or "")
    proposal_reason = str(proposal.get("reason") or "")
    if status == "proposed":
        if (
            proposal_reason not in SEMANTIC_NEGATIVE_REASONS
            or not _negative_evidence_is_current(proposal["evidence"], claim_text)
            or record.get("invalid_reason") != ""
            or validation.get("request_id") != ""
            or validation.get("reason") != ""
            or validation.get("checks") != {}
            or validation.get("evidence") != []
            or validation_source.get("request_id") != ""
        ):
            return "negative_proposal_not_current"
    elif status == "validated":
        validation_request_id = str(validation.get("request_id") or "")
        if validation_request_id == proposal.get("request_id"):
            return "negative_validator_request_not_independent"
        if (
            proposal_reason not in SEMANTIC_NEGATIVE_REASONS
            or validation.get("reason") != proposal_reason
            or not validation_request_id
            or not _negative_checks_complete(validation)
            or not _negative_evidence_is_current(proposal["evidence"], claim_text)
            or not _negative_evidence_is_current(validation["evidence"], claim_text)
            or record.get("invalid_reason") != ""
            or validation_source.get("request_id") != validation_request_id
        ):
            return "negative_validation_not_current"
    else:
        if not record.get("invalid_reason"):
            return "negative_invalid_reason_missing"
        validation_request_id = str(validation.get("request_id") or "")
        if validation_request_id and validation_source.get("request_id") != validation_request_id:
            return "negative_validation_source_invalid"
    return None


def _apply_negative_validation(
    record: dict[str, Any],
    decision: dict[str, Any],
    *,
    request_id: str,
    source_text: str,
    validation_generation_run_id: str,
) -> None:
    reason = str(decision.get("reason") or "")
    evidence = _negative_evidence_rows(decision.get("evidence"))
    record["validation"] = {
        "request_id": request_id,
        "version": CLAIM_NEGATIVE_VALIDATOR_VERSION,
        "reason": reason if reason in SEMANTIC_NEGATIVE_REASONS else "",
        "checks": {
            name: (decision.get("checks") or {}).get(name)
            for name in SEMANTIC_NEGATIVE_CHECKS
        },
        "evidence": evidence,
        "rationale": str(decision.get("rationale") or "")[:2000],
    }
    record["validation_source"] = {
        "generation_run_id": validation_generation_run_id,
        "request_id": request_id,
    }
    proposed_reason = str(record.get("proposal", {}).get("reason") or "")
    if decision.get("disagreement") is True:
        record["status"] = "invalid"
        record["invalid_reason"] = "negative_validator_disagreement"
    elif decision.get("non_normative") is not True:
        record["status"] = "invalid"
        record["invalid_reason"] = "negative_not_validated"
    elif reason != proposed_reason:
        record["status"] = "invalid"
        record["invalid_reason"] = "negative_reason_disagreement"
    elif not _negative_checks_complete(decision):
        record["status"] = "invalid"
        record["invalid_reason"] = "negative_checks_incomplete"
    elif not _negative_evidence_is_current(evidence, source_text):
        record["status"] = "invalid"
        record["invalid_reason"] = "negative_evidence_invalid"
    else:
        record["status"] = "validated"
        record["invalid_reason"] = ""


def _reuse_semantic_validation(
    groups: list[dict[str, Any]],
    reusable_groups: list[dict[str, Any]],
) -> int:
    from claim_artifacts import ClaimArtifactError

    prior = {
        str(group.get("coverage_group_id") or ""): group
        for group in reusable_groups
        if isinstance(group, dict)
    }
    reused = 0
    for group in groups:
        if group.get("status") != "proposed" or group.get("validation_method") != "independent_semantic":
            continue
        previous = prior.get(str(group.get("coverage_group_id") or ""))
        if not previous:
            continue
        reusable_terminal = (
            previous.get("status") == "validated"
            or (
                previous.get("status") == "invalid"
                and previous.get("invalid_reason") == "semantic_not_entailed"
            )
        )
        if not reusable_terminal:
            continue
        try:
            previous_fingerprint = semantic_validation_fingerprint(previous)
            current_fingerprint = semantic_validation_fingerprint(group)
        except (ClaimArtifactError, TypeError, ValueError):
            continue
        if previous_fingerprint != current_fingerprint:
            continue
        request_id = str(previous.get("validator_request_id") or "")
        validation_source = previous.get("validation_source")
        if (
            not request_id
            or not isinstance(validation_source, dict)
            or validation_source.get("request_id") != request_id
            or not str(validation_source.get("generation_run_id") or "")
        ):
            continue
        group.update({
            "status": previous["status"],
            "invalid_reason": str(previous.get("invalid_reason") or ""),
            "validator_request_id": request_id,
            "validator_checks": dict(previous.get("validator_checks") or {}),
            "validator_reason": str(previous.get("validator_reason") or ""),
            "validation_source": dict(validation_source),
            "validation_reused": True,
        })
        reused += 1
    return reused


def semantic_validation_fingerprint(group: dict[str, Any]) -> str:
    """Identity of semantic evidence, deliberately excluding review eligibility."""
    from claim_artifacts import (
        canonical_json_value_bytes,
        canonical_target_fingerprint,
        hash_json,
        sha256_bytes,
    )

    source = group.get("source_evidence")
    if not isinstance(source, dict):
        raise ValueError("semantic validation has no source evidence")
    source_text = source.get("text")
    if not isinstance(source_text, str) or not source_text:
        raise ValueError("semantic validation source evidence is empty")
    source_evidence = {
        "text_hash": sha256_bytes(source_text.encode("utf-8")),
        "claim_start": int(source["claim_start"]),
        "claim_end": int(source["claim_end"]),
        "match_method": str(source["match_method"]),
    }

    def canonical_fact(raw_fact: object) -> dict[str, Any]:
        if not isinstance(raw_fact, dict):
            raise ValueError("semantic prefilter fact is not an object")
        aliases = raw_fact.get("aliases")
        if not isinstance(aliases, list):
            raise ValueError("semantic prefilter fact aliases are not a list")
        return {
            "kind": str(raw_fact.get("kind") or ""),
            "value": str(raw_fact.get("value") or ""),
            "aliases": sorted(str(value) for value in aliases),
        }

    raw_prefilter = group.get("prefilter")
    if not isinstance(raw_prefilter, dict):
        raise ValueError("semantic validation has no prefilter")
    missing_facts = [
        canonical_fact(raw_fact)
        for raw_fact in (raw_prefilter.get("missing_protected_facts") or [])
    ]
    missing_facts.sort(key=lambda fact: (
        fact["kind"],
        fact["value"],
        tuple(fact["aliases"]),
    ))
    prefilter = {
        "version": str(raw_prefilter.get("version") or ""),
        "status": str(raw_prefilter.get("status") or ""),
        "missing_protected_facts": missing_facts,
    }

    edges: list[dict[str, Any]] = []
    for raw_edge in group.get("edges") or []:
        edge = dict(raw_edge)
        evidence = []
        for raw_item in edge.get("produced_evidence") or []:
            item = dict(raw_item)
            evidence.append({
                "field": item.get("field"),
                "item_index": item.get("item_index"),
                "start": item.get("start"),
                "end": item.get("end"),
                "position_basis": item.get("position_basis"),
                "field_value_hash": item.get("field_value_hash"),
            })
        evidence.sort(key=lambda item: (
            str(item.get("field") or ""),
            -1 if item.get("item_index") is None else int(item["item_index"]),
            int(item.get("start") or 0),
            int(item.get("end") or 0),
            str(item.get("position_basis") or ""),
            str(item.get("field_value_hash") or ""),
        ))
        edges.append({
            "target_kind": str(edge.get("target_kind") or ""),
            "target_requirement_id": str(edge.get("target_requirement_id") or ""),
            "target_fingerprint": canonical_target_fingerprint(
                edge.get("target_fingerprint")
            ),
            "relation": str(edge.get("relation") or ""),
            "produced_evidence": evidence,
        })
    edges.sort(key=lambda edge: (
        edge["target_kind"],
        edge["target_requirement_id"],
        edge["target_fingerprint"],
        edge["relation"],
        canonical_json_value_bytes(edge["produced_evidence"]),
    ))
    payload = {
        "claim_hash": str(group.get("claim_hash") or ""),
        "source_evidence": source_evidence,
        "edges": edges,
        "prefilter": prefilter,
        "validation_method": str(group.get("validation_method") or ""),
        "validator_version": str(group.get("validator_version") or ""),
        "verifier_runtime_fingerprint": str(
            group.get("verifier_runtime_fingerprint") or ""
        ),
        "reuse_version": CLAIM_VALIDATION_REUSE_VERSION,
    }
    return hash_json("claim-semantic-validation/v1", payload)


def reduce_claim(
    claim: dict[str, Any],
    *,
    validated_groups: list[dict[str, Any]] | None = None,
    validated_negative: dict[str, Any] | None = None,
    all_groups: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    validated_groups = validated_groups or []
    all_groups = all_groups or []
    positive = any(group.get("status") == "validated" for group in validated_groups)
    negative = bool(validated_negative and validated_negative.get("status") == "validated")
    invalid_reasons: list[str] = []
    exclusion_kind: str | None = None
    if claim.get("eligibility") == "excluded":
        resolution = "excluded"
        classification, classification_status = "non_normative", "validated"
        exclusion_kind = "structural"
    elif positive and negative:
        resolution = "uncertain"
        classification, classification_status = "unknown", "invalid"
        invalid_reasons.append("positive_negative_conflict")
    elif positive:
        resolution = "covered"
        classification, classification_status = "normative", "validated"
    elif negative:
        resolution = "excluded"
        classification, classification_status = "non_normative", "validated"
        exclusion_kind = "semantic"
    else:
        resolution = "uncertain"
        classification, classification_status = "unknown", "needs_review"
        invalid_reasons.extend(sorted({
            str(group.get("invalid_reason") or "") for group in all_groups
            if group.get("status") == "invalid" and group.get("invalid_reason")
        }))
        if (validated_negative and validated_negative.get("status") == "invalid"
                and validated_negative.get("invalid_reason")):
            invalid_reasons.append(str(validated_negative["invalid_reason"]))
    linked_revisions = sorted({
        str(edge.get("target_review_revision") or "")
        for group in all_groups for edge in (group.get("edges") or [])
        if edge.get("target_review_revision")
    })
    relevant_groups = [{
        "coverage_group_id": group.get("coverage_group_id"),
        "status": group.get("status"),
        "validator_request_id": group.get("validator_request_id"),
        "invalid_reason": group.get("invalid_reason"),
    } for group in all_groups]
    revision = _sha256({
        "claim_hash": claim.get("claim_hash"),
        "groups": relevant_groups,
        "linked_target_review_revisions": linked_revisions,
        "negative": validated_negative,
        "reducer_version": CLAIM_REDUCER_VERSION,
    })
    return {
        "schema": CLAIM_LEDGER_SCHEMA,
        "ledger_schema_version": CLAIM_LEDGER_SCHEMA_VERSION,
        "document_generation_id": claim.get("document_generation_id"),
        "catalog_generation_id": claim.get("catalog_generation_id"),
        "claim_id": claim.get("claim_id"),
        "claim_hash": claim.get("claim_hash"),
        "owner_unit_id": claim.get("owner_unit_id"),
        "resolution": resolution,
        "classification": classification,
        "classification_status": classification_status,
        "exclusion_kind": exclusion_kind,
        "coverage_group_ids": [str(group.get("coverage_group_id")) for group in all_groups],
        "semantic_negative": dict(validated_negative) if validated_negative else None,
        "invalid_reasons": invalid_reasons,
        "claim_effective_revision": revision,
    }


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": (numerator / denominator if denominator else None),
    }


def _budget_delta(
    start: dict[str, Any],
    budget: LLMRequestBudget | None,
) -> tuple[int, int]:
    if budget is None:
        return 0, 0
    current = budget.snapshot()
    return (
        max(0, int(current.get("attempted_calls") or 0)
            - int(start.get("attempted_calls") or 0)),
        max(0, int(current.get("tokens") or 0) - int(start.get("tokens") or 0)),
    )


def _verifier_budget_outcome(
    budget: LLMRequestBudget | None,
    runtime: dict[str, Any],
    *,
    attempted_calls: int,
    failed_calls: int,
    accounted_tokens: int,
    usage_complete: bool,
    budget_exhausted: bool,
) -> dict[str, Any]:
    if budget is not None:
        snapshot = budget.snapshot()
        return {
            "schema": "claim-verifier-budget-outcome/v1",
            "policy_version": str(snapshot.get("version") or ""),
            "max_calls": int(snapshot.get("max_calls") or 0),
            "max_total_tokens": int(snapshot.get("max_tokens") or 0),
            "attempted_calls": int(snapshot.get("attempted_calls") or 0),
            "failed_calls": int(snapshot.get("failed_calls") or 0),
            "accounted_tokens": int(snapshot.get("tokens") or 0),
            "remaining_calls": int(snapshot.get("remaining_calls") or 0),
            "remaining_tokens": int(snapshot.get("remaining_tokens") or 0),
            "usage_complete": snapshot.get("usage_complete") is True,
            "denied": snapshot.get("denied") is True,
            "exhaustion_reason": str(snapshot.get("termination_reason") or ""),
        }
    return {
        "schema": "claim-verifier-budget-outcome/v1",
        "policy_version": str(
            runtime.get("budget_policy_version") or CLAIM_EXTERNAL_BUDGET_POLICY_VERSION
        ),
        "max_calls": int(runtime.get("max_calls") or 0),
        "max_total_tokens": int(runtime.get("max_total_tokens") or 0),
        "attempted_calls": max(0, int(attempted_calls)),
        "failed_calls": max(0, int(failed_calls)),
        "accounted_tokens": max(0, int(accounted_tokens)),
        "remaining_calls": 0,
        "remaining_tokens": 0,
        "usage_complete": bool(usage_complete),
        "denied": bool(budget_exhausted),
        "exhaustion_reason": "external_budget_exhausted" if budget_exhausted else "",
    }


def _metrics(
    catalog: list[dict[str, Any]],
    ledger: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    negative_decisions: list[dict[str, Any]],
    requirements: list[dict[str, Any]],
    *,
    unit_count: int,
    verifier_calls: int,
    verifier_tokens: int,
    verifier_failed_calls: int,
    verifier_operation_failure_count: int,
    verifier_usage_complete: bool,
    semantic_verifier_enabled: bool,
    semantic_validation_reused: int,
    semantic_verifier_candidate_count: int,
    coverage_verifier_calls: int,
    coverage_verifier_tokens: int,
    negative_proposer_calls: int,
    negative_proposer_tokens: int,
    negative_verifier_calls: int,
    negative_verifier_tokens: int,
    negative_validation_reused: int,
    logical_call_ceiling: int | None,
    planned_logical_call_count: int,
    coverage_verifier_deferred_count: int,
    coverage_verifier_oversized_count: int,
    negative_proposer_eligible_count: int,
    negative_proposer_selected_count: int,
    negative_proposer_deferred_count: int,
    negative_proposer_oversized_count: int,
    negative_verifier_deferred_count: int,
    negative_verifier_oversized_count: int,
    shared_block_only_hints: int,
    baseline_call_count: int,
    baseline_failed_call_count: int,
    baseline_tokens: int,
    baseline_usage_complete: bool,
    baseline_lineage_match: bool,
    verifier_budget_outcome: dict[str, Any],
    failed_extraction_units: int,
) -> dict[str, Any]:
    eligible = [row for row in ledger if next(
        (claim.get("eligibility") for claim in catalog if claim.get("claim_id") == row.get("claim_id")),
        "claim",
    ) == "claim"]
    covered = sum(row["resolution"] == "covered" for row in eligible)
    semantic_excluded = sum(row["resolution"] == "excluded" and row["exclusion_kind"] == "semantic"
                            for row in eligible)
    uncertain = sum(row["resolution"] == "uncertain" for row in eligible)
    structural = sum(row["resolution"] == "excluded" and row["exclusion_kind"] == "structural"
                     for row in ledger)
    semantic_groups = [group for group in groups
                       if group.get("validation_method") == "independent_semantic"]
    verbatim_groups = [group for group in groups
                       if group.get("validation_method") == "deterministic_verbatim"]
    prefilter_rejected = sum(group.get("prefilter", {}).get("status") == "reject"
                             for group in semantic_groups)
    negative_validated = sum(row.get("status") == "validated" for row in negative_decisions)
    negative_invalid = sum(row.get("status") == "invalid" for row in negative_decisions)
    negative_disagreements = sum(row.get("invalid_reason") in {
        "negative_reason_disagreement", "negative_validator_disagreement",
    } for row in negative_decisions)
    multi_claim_quotes = 0
    multi_claim_quote_ids: set[str] = set()
    for requirement in requirements:
        quote = _normalized(requirement.get("source_quote"))
        if not quote:
            continue
        matched = [
            str(claim.get("claim_id") or "")
            for claim in catalog
            if claim.get("eligibility") == "claim"
            and _normalized(_claim_content(claim)[0])
            and _normalized(_claim_content(claim)[0]) in quote
        ]
        if len(matched) > 1:
            multi_claim_quotes += 1
            multi_claim_quote_ids.update(matched)
    open_siblings = sum(
        row["resolution"] == "uncertain"
        and str(row.get("claim_id") or "") in multi_claim_quote_ids
        for row in ledger
    )

    groups_by_claim: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group in groups:
        groups_by_claim[str(group.get("claim_id") or "")].append(group)
    sibling_paths = {
        "merged_into_group": 0,
        "post_reextract_coverage": 0,
        "expert_adjudication": 0,
        "other_validated_coverage": 0,
        "semantic_exclusion": 0,
        "still_open": 0,
    }
    for row in ledger:
        claim_id = str(row.get("claim_id") or "")
        if claim_id not in multi_claim_quote_ids:
            continue
        claim_groups = groups_by_claim.get(claim_id, [])
        if row.get("resolution") == "covered":
            validated = [group for group in claim_groups if group.get("status") == "validated"]
            if any(group.get("validation_method") == "expert" for group in validated):
                sibling_paths["expert_adjudication"] += 1
            elif any(any(edge.get("relation") == "merged_into" for edge in group.get("edges") or [])
                     for group in validated):
                sibling_paths["merged_into_group"] += 1
            elif any("targeted_reextract" in (group.get("proposal_basis") or [])
                     for group in validated):
                sibling_paths["post_reextract_coverage"] += 1
            else:
                sibling_paths["other_validated_coverage"] += 1
        elif row.get("resolution") == "excluded":
            sibling_paths["semantic_exclusion"] += 1
        else:
            sibling_paths["still_open"] += 1

    edge_count = sum(len(group.get("edges") or []) for group in groups)
    produced_evidence_chars = sum(
        len(str(item.get("text") or ""))
        for group in groups
        for edge in (group.get("edges") or [])
        for item in (edge.get("produced_evidence") or [])
    )
    call_increase = _ratio(verifier_calls, baseline_call_count)
    token_increase = _ratio(verifier_tokens, baseline_tokens)
    cost_gate_met = None
    if (
        semantic_verifier_enabled
        and verifier_calls > 0
        and verifier_tokens > 0
        and baseline_call_count > 0
        and baseline_tokens > 0
        and baseline_usage_complete
        and baseline_lineage_match
        and verifier_usage_complete
        and verifier_operation_failure_count == 0
        and verifier_budget_outcome.get("denied") is not True
    ):
        cost_gate_met = (
            (call_increase["value"] or 0.0) <= CLAIM_VERIFIER_CALL_INCREASE_LIMIT
            and (token_increase["value"] or 0.0) <= CLAIM_VERIFIER_TOKEN_INCREASE_LIMIT
        )
    cost_gate_status = (
        "not_run"
        if not semantic_verifier_enabled
        else "insufficient_data" if cost_gate_met is None
        else "pass" if cost_gate_met else "fail"
    )
    return {
        "catalog_total_count": len(catalog),
        "failed_extraction_units": max(0, int(failed_extraction_units)),
        "eligible_claim_count": len(eligible),
        "covered_count": covered,
        "semantic_excluded_count": semantic_excluded,
        "structural_excluded_count": structural,
        "uncertain_count": uncertain,
        "inventory_accounted_ratio": _ratio(len(ledger), len(catalog)),
        "verified_coverage_ratio": _ratio(covered, len(eligible)),
        "verified_semantic_exclusion_ratio": _ratio(semantic_excluded, len(eligible)),
        "verified_exclusion_ratio": _ratio(structural + semantic_excluded, len(catalog)),
        "eligible_resolution_ratio": _ratio(covered + semantic_excluded, len(eligible)),
        "structural_exclusion_ratio": _ratio(structural, len(catalog)),
        "invalid_group_count": sum(group.get("status") == "invalid" for group in groups),
        "invalid_edge_count": sum(len(group.get("edges") or []) for group in groups
                                  if group.get("status") == "invalid"),
        "deterministic_verbatim_ratio": _ratio(len(verbatim_groups), len(groups)),
        "prefilter_reject_rate": _ratio(prefilter_rejected, len(semantic_groups)),
        "semantic_verifier_candidate_ratio": _ratio(
            semantic_verifier_candidate_count,
            len(eligible),
        ),
        "semantic_verifier_candidate_count": semantic_verifier_candidate_count,
        "coverage_group_count": len(groups),
        "coverage_edge_count": edge_count,
        "produced_evidence_character_count": produced_evidence_chars,
        "shared_block_only_hint_count": shared_block_only_hints,
        "verifier_call_count": verifier_calls,
        "verifier_failed_calls": verifier_failed_calls,
        "verifier_operation_failure_count": verifier_operation_failure_count,
        "verifier_tokens": verifier_tokens,
        "verifier_usage_complete": verifier_usage_complete,
        "verifier_budget_policy_version": str(
            verifier_budget_outcome.get("policy_version") or ""
        ),
        "verifier_budget_max_calls": int(
            verifier_budget_outcome.get("max_calls") or 0
        ),
        "verifier_budget_max_total_tokens": int(
            verifier_budget_outcome.get("max_total_tokens") or 0
        ),
        "verifier_budget_remaining_calls": int(
            verifier_budget_outcome.get("remaining_calls") or 0
        ),
        "verifier_budget_remaining_tokens": int(
            verifier_budget_outcome.get("remaining_tokens") or 0
        ),
        "verifier_budget_denied": verifier_budget_outcome.get("denied") is True,
        "verifier_budget_exhaustion_reason": str(
            verifier_budget_outcome.get("exhaustion_reason") or ""
        ),
        "ledger_llm_call_count": verifier_calls,
        "ledger_llm_failed_call_count": verifier_failed_calls,
        "ledger_llm_tokens": verifier_tokens,
        "semantic_validation_reused_group_count": semantic_validation_reused,
        "semantic_validation_reused_group_ratio": _ratio(
            semantic_validation_reused,
            semantic_verifier_candidate_count,
        ),
        "verifier_batch_policy_version": CLAIM_VERIFIER_BATCH_POLICY_VERSION,
        "verifier_cost_policy_version": CLAIM_COST_POLICY_VERSION,
        "verifier_call_increase_limit": CLAIM_VERIFIER_CALL_INCREASE_LIMIT,
        "verifier_token_increase_limit": CLAIM_VERIFIER_TOKEN_INCREASE_LIMIT,
        "verifier_logical_call_ceiling": logical_call_ceiling,
        "verifier_planned_logical_call_count": planned_logical_call_count,
        "coverage_verifier_call_count": coverage_verifier_calls,
        "coverage_verifier_tokens": coverage_verifier_tokens,
        "coverage_verifier_deferred_count": coverage_verifier_deferred_count,
        "coverage_verifier_oversized_count": coverage_verifier_oversized_count,
        "negative_proposer_call_count": negative_proposer_calls,
        "negative_proposer_tokens": negative_proposer_tokens,
        "negative_proposer_eligible_count": negative_proposer_eligible_count,
        "negative_proposer_selected_count": negative_proposer_selected_count,
        "negative_proposer_deferred_count": negative_proposer_deferred_count,
        "negative_proposer_oversized_count": negative_proposer_oversized_count,
        "negative_verifier_call_count": negative_verifier_calls,
        "negative_verifier_tokens": negative_verifier_tokens,
        "negative_verifier_deferred_count": negative_verifier_deferred_count,
        "negative_verifier_oversized_count": negative_verifier_oversized_count,
        "independent_verifier_call_count": (
            coverage_verifier_calls + negative_verifier_calls
        ),
        "independent_verifier_tokens": (
            coverage_verifier_tokens + negative_verifier_tokens
        ),
        "semantic_negative_validation_reused_count": negative_validation_reused,
        "semantic_negative_candidate_count": len(negative_decisions),
        "semantic_negative_validated_count": negative_validated,
        "semantic_negative_invalid_count": negative_invalid,
        "semantic_negative_validation_pass_rate": _ratio(
            negative_validated, len(negative_decisions)),
        "negative_validation_disagreement_rate": _ratio(
            negative_disagreements, len(negative_decisions)),
        # 抽样审计率 Phase 0 占位：真值由 claim_acceptance 的 held-out 审计计算，
        # 此处如实标 0/0 而非伪造已审计（review G6a 留痕）
        "negative_audit_disagreement_rate": _ratio(0, 0),
        "avg_verifier_calls_per_unit": _ratio(verifier_calls, unit_count),
        "verifier_tokens_per_claim": _ratio(verifier_tokens, len(eligible)),
        "no_ledger_baseline_call_count": baseline_call_count,
        "no_ledger_baseline_failed_call_count": baseline_failed_call_count,
        "no_ledger_baseline_tokens": baseline_tokens,
        "no_ledger_baseline_usage_complete": baseline_usage_complete,
        "no_ledger_baseline_lineage_match": baseline_lineage_match,
        "verifier_call_increase_ratio": call_increase,
        "verifier_token_increase_ratio": token_increase,
        "relative_verifier_call_increase": call_increase,
        "relative_verifier_token_increase": token_increase,
        "phase0_cost_gate_met": cost_gate_met,
        "verifier_cost_gate_status": cost_gate_status,
        "multi_claim_quote_count": multi_claim_quotes,
        "sibling_claim_open_rate": _ratio(open_siblings, len(multi_claim_quote_ids)),
        "merged_quote_sibling_resolution_paths": sibling_paths,
        "open_ledger_units": len({
            str(row.get("owner_unit_id") or "")
            for row in eligible
            if row.get("resolution") == "uncertain" and row.get("owner_unit_id")
        }),
        "target_invalidated_count": sum(group.get("invalid_reason") in {
            "target_rejected", "target_review_unknown"
        } for group in groups),
    }


# ---------------------------------------------------------------------------
# WS2 §4.2 claim 账本抽检模式（full / sampling / baseline_gate）
# ---------------------------------------------------------------------------

def resolve_claim_ledger_mode(value: str | None = None) -> str:
    """解析 mode 配置（env ``RATOMIZER_CLAIM_LEDGER_MODE``，默认 sampling）。

    非法值回退默认档并告警——mode 是配置开关，非法配置不得让流水线裸崩。
    """
    raw = os.environ.get("RATOMIZER_CLAIM_LEDGER_MODE") if value is None else value
    mode = str(raw or "").strip().lower() or DEFAULT_CLAIM_LEDGER_MODE
    if mode not in CLAIM_LEDGER_MODES:
        logging.getLogger("requirement_atomizer").warning(
            "非法 claim ledger mode %r，回退默认 %s", raw, DEFAULT_CLAIM_LEDGER_MODE,
        )
        return DEFAULT_CLAIM_LEDGER_MODE
    return mode


def _resolve_sampling_rate(value: float | None = None) -> float:
    raw = os.environ.get("RATOMIZER_CLAIM_LEDGER_SAMPLING_RATE") if value is None else value
    try:
        rate = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_CLAIM_LEDGER_SAMPLING_RATE
    if not 0.0 <= rate <= 1.0:
        return DEFAULT_CLAIM_LEDGER_SAMPLING_RATE
    return rate


def _resolve_sampling_floor_rate(value: float | None = None) -> float:
    raw = os.environ.get("RATOMIZER_CLAIM_LEDGER_SAMPLING_FLOOR_RATE") if value is None else value
    try:
        rate = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_CLAIM_LEDGER_SAMPLING_FLOOR_RATE
    if not 0.0 <= rate <= 1.0:
        return DEFAULT_CLAIM_LEDGER_SAMPLING_FLOOR_RATE
    return rate


def is_high_risk_claim(claim: dict[str, Any]) -> bool:
    """确定性高风险 claim 识别（零 LLM）。

    与既有"受保护编码漂移硬拦、普通数字漂移软标"的风险分级同源：claim 文本含受保护编码
    （OBIS / hex / 外标准号，经 extract_codes）或数值命题（经 extract_protected_facts 的
    unit_value / number）即为高风险，sampling 模式下必经 verifier 闭合。
    """
    content, _, _ = _claim_content(claim)
    if not str(content or "").strip():
        return False
    if extract_codes(content):
        return True
    facts = extract_protected_facts(content)
    for fact in facts:
        kind = str(fact.get("kind") or "")
        if kind in {"unit_value", "number"}:
            return True
    return False


def select_verifier_claim_ids(
    catalog: list[dict[str, Any]],
    *,
    mode: str = DEFAULT_CLAIM_LEDGER_MODE,
    sampling_rate: float | None = None,
    floor_rate: float | None = None,
) -> dict[str, Any]:
    """按 mode 选出 sampling 模式下需 verifier 闭合的 claim_id 集合（确定性，零 LLM）。

    * ``full`` / ``baseline_gate``：全部 eligible claim（baseline_gate 的重型机制联动由
      caller 在发布门禁触发，这里只负责"闭合面=全量"）。
    * ``sampling``（默认）：分层抽样 ``sampling_rate``（默认 10%）+ 全部高风险 claim。
      抽样用稳定 stride（按 claim_id 排序后等距取样），无随机数——同输入同输出、可复算。
      抽检闭合率低于 ``floor_rate`` 时 ``escalate=True``（建议扩大抽样或转全量），判定依据
      留账本。

    返回 ``{mode, selected_ids, sampled_ids, high_risk_ids, deferred_ids, sampling_rate,
    escalate, threshold_met}``。selected_ids = sampled ∪ high_risk。
    """
    eligible = [
        claim for claim in catalog
        if isinstance(claim, dict) and claim.get("eligibility") == "claim"
    ]
    eligible_ids = [str(claim.get("claim_id") or "") for claim in eligible]
    eligible_by_id = {
        str(claim.get("claim_id") or ""): claim for claim in eligible
    }

    if mode in {"full", "baseline_gate"}:
        return {
            "mode": mode,
            "selected_ids": set(eligible_ids),
            "sampled_ids": [],
            "high_risk_ids": [],
            "deferred_ids": [],
            "eligible_count": len(eligible_ids),
            "sampling_rate": 1.0,
            "floor_rate": _resolve_sampling_floor_rate(floor_rate),
            "escalate": False,
            "threshold_met": True,
        }

    # sampling
    rate = _resolve_sampling_rate(sampling_rate)
    floor = _resolve_sampling_floor_rate(floor_rate)
    ordered = sorted(eligible_ids)
    high_risk_ids = sorted(
        cid for cid in ordered if is_high_risk_claim(eligible_by_id.get(cid, {}))
    )
    # 分层抽样：在全部 eligible 上等距取样（非高风险也参与，保证覆盖率估计无偏）
    sample_target = max(1, int(round(len(ordered) * rate))) if ordered else 0
    if ordered and sample_target >= len(ordered):
        sampled_ids = list(ordered)
    else:
        stride = len(ordered) / sample_target if sample_target else 0
        sampled_ids = [
            ordered[int(i * stride)]
            for i in range(sample_target)
            if 0 <= int(i * stride) < len(ordered)
        ] if stride else []
        sampled_ids = sorted(set(sampled_ids))
    selected = set(sampled_ids) | set(high_risk_ids)
    deferred = sorted(set(ordered) - selected)
    # 抽检闭合率估计：实际选中比例低于 floor → escalate=True（建议扩大抽样或转全量）。
    selected_ratio = (len(selected) / len(ordered)) if ordered else 1.0
    threshold_met = selected_ratio >= floor
    return {
        "mode": mode,
        "selected_ids": selected,
        "sampled_ids": sampled_ids,
        "high_risk_ids": high_risk_ids,
        "deferred_ids": deferred,
        "eligible_count": len(ordered),
        "sampling_rate": rate,
        "floor_rate": floor,
        "selected_ratio": selected_ratio,
        "escalate": not threshold_met,
        "threshold_met": threshold_met,
    }


def build_shadow_ledger(
    catalog_build: dict[str, Any],
    requirements: list[dict[str, Any]],
    *,
    review_states: dict[str, dict[str, Any]] | None = None,
    controlled_term_aliases: dict[str, list[str]] | None = None,
    semantic_verifier: SemanticVerifier | None = None,
    semantic_negative_proposer: SemanticNegativeProposer | None = None,
    semantic_negative_verifier: SemanticNegativeVerifier | None = None,
    reusable_groups: list[dict[str, Any]] | None = None,
    reusable_negatives: list[dict[str, Any]] | None = None,
    route_mode: str = "llm",
    extraction_status: str = "success",
    failed_section_block_ids: Iterable[str] | None = None,
    baseline_call_count: int = 0,
    baseline_failed_call_count: int = 0,
    baseline_tokens: int = 0,
    baseline_usage_complete: bool = False,
    baseline_cost: dict[str, Any] | None = None,
    verifier_runtime: dict[str, Any] | None = None,
    verifier_budget: LLMRequestBudget | None = None,
    verifier_attempt_progress: VerifierAttemptProgress | None = None,
    validation_generation_run_id: str = "unpublished",
    mode: str = "full",
    anchor_obligation_hashes: dict[tuple[str, int], str] | None = None,
) -> dict[str, Any]:
    """Build a B-track ledger beside final requirements without changing readiness.

    WS2 §4.2 ``mode``（默认 ``full``，与现状逐字节一致）：

    * ``full``：全量闭合（现状）。
    * ``sampling``：verifier 闭合只覆盖分层抽样 + 全部高风险 claim（确定性正则识别，零 LLM）；
      未抽中的 claim 标 ``sampling_deferred`` 保持 uncertain，闭合面收窄、调用数下降。
    * ``baseline_gate``：全量闭合（=full 的闭合面），发布门禁重型机制联动由 caller 触发。

    只有显式 ``mode != "full"`` 才进入抽样分支，默认调用方（含 4.1 万行测试）行为不动。
    """
    catalog = list(catalog_build.get("catalog") or [])
    units = list(catalog_build.get("units") or [])
    # 负向验证上下文补父容器映射（规格 §2.3：兄弟 claim + 父容器映射）——
    # 清单/表格容器的结构（intro 与 members）是判断"混合 span/语义性排除"的必需证据
    container_by_block = {
        str(mapping.get("container_block_id") or ""): mapping
        for mapping in (catalog_build.get("container_mappings") or [])
        if isinstance(mapping, dict) and mapping.get("container_block_id")
    }
    for unit in units:
        unit["container_mappings"] = [
            container_by_block[block_id]
            for block_id in (unit.get("block_ids") or [])
            if block_id in container_by_block
        ]
    failed_blocks = {
        str(block_id) for block_id in (failed_section_block_ids or []) if str(block_id)
    }
    failed_extraction_unit_ids = {
        str(claim.get("owner_unit_id") or "")
        for claim in catalog
        if str((claim.get("locator") or {}).get("block_id") or "") in failed_blocks
        and str(claim.get("owner_unit_id") or "")
    }
    effective_extraction_status = (
        "partial"
        if failed_extraction_unit_ids and extraction_status == "success"
        else extraction_status
    )
    target_rows, target_generation, authority_revision = _targets(
        requirements,
        review_states or {},
    )
    if route_mode == "stub":
        semantic_verifier = None
        semantic_negative_proposer = None
        semantic_negative_verifier = None
    baseline_lineage_match = False
    if isinstance(baseline_cost, dict):
        baseline_call_count = int(baseline_cost.get("call_count") or 0)
        baseline_failed_call_count = int(baseline_cost.get("failed_call_count") or 0)
        baseline_tokens = int(baseline_cost.get("total_tokens") or 0)
        baseline_usage_complete = baseline_cost.get("usage_complete") is True
        baseline_lineage_match = bool(
            baseline_cost.get("lineage_match") is True
            and isinstance(baseline_cost.get("lineage_version"), str)
            and bool(baseline_cost.get("lineage_version"))
            and isinstance(baseline_cost.get("lineage_fingerprint"), str)
            and re.fullmatch(
                r"sha256:[0-9a-f]{64}",
                str(baseline_cost.get("lineage_fingerprint") or ""),
            )
            and isinstance(baseline_cost.get("lineage_context"), dict)
            and bool(baseline_cost.get("lineage_context"))
        )
    ledger_llm_enabled = any((
        semantic_verifier is not None,
        semantic_negative_proposer is not None,
        semantic_negative_verifier is not None,
    ))
    runtime = dict(verifier_runtime or semantic_verifier_runtime(
        route_mode=route_mode,
        enabled=ledger_llm_enabled,
        rounds=1,
    ))
    if not semantic_verifier_runtime_is_valid(runtime):
        raise ValueError("semantic verifier runtime is malformed or not replayable")
    if runtime.get("enabled") is not ledger_llm_enabled:
        raise ValueError("semantic verifier runtime does not match the configured verifier")
    if (
        runtime.get("policy_source") == "environment"
        and runtime.get("enabled") is True
        and verifier_budget is None
    ):
        raise ValueError("environment-managed verifier requires a hard request budget")
    if verifier_budget is not None:
        budget_policy = verifier_budget.snapshot()
        if (
            runtime.get("budget_policy_version") != budget_policy.get("version")
            or int(runtime.get("max_calls") or 0)
            != int(budget_policy.get("max_calls") or 0)
            or int(runtime.get("max_total_tokens") or 0)
            != int(budget_policy.get("max_tokens") or 0)
        ):
            raise ValueError("semantic verifier runtime does not match its request budget")
    groups: list[dict[str, Any]] = []
    groups_by_claim: dict[str, list[dict[str, Any]]] = defaultdict(list)
    shared_block_only_hints = 0

    # WS2 §4.2 抽检模式：mode != full 时计算 verifier 闭合选择集，gate 语义候选创建。
    # 默认 mode='full' → verifier_selection=None → 全量闭合，与现状逐字节一致。
    mode_resolved = resolve_claim_ledger_mode(mode) if mode else "full"
    verifier_selection: dict[str, Any] | None = None
    sampling_deferred_claim_ids: list[str] = []
    if mode_resolved != "full":
        verifier_selection = select_verifier_claim_ids(catalog, mode=mode_resolved)

    for claim in catalog:
        if claim.get("eligibility") != "claim":
            continue
        content, _, _ = _claim_content(claim)
        candidates: list[tuple[dict[str, Any], list[str], list[dict[str, Any]]]] = []
        exact: list[tuple[dict[str, Any], list[str], list[dict[str, Any]]]] = []
        for target in target_rows:
            basis = _candidate_basis(claim, target)
            if not basis:
                continue
            exact_evidence = _verbatim_evidence(content, target["evidence"])
            if exact_evidence:
                exact.append((target, basis, exact_evidence))
            elif "source_quote_span" in basis:
                candidates.append((target, basis, target["evidence"]))
            elif "shared_block_locator" in basis:
                # A shared block is useful for diagnostics and targeted re-extraction,
                # but it is too broad to justify a semantic verifier request.
                shared_block_only_hints += 1
        from normative_framing import product_obligation_governs_span

        formal_exact = [
            target
            for target in exact
            if any(
                product_obligation_governs_span(
                    str(full.get("text") or ""),
                    int(match.get("start") or 0),
                    int(match.get("end") or 0),
                )
                for match in target[2]
                for full in target[0]["evidence"]
                if full.get("field") == match.get("field")
                and full.get("item_index") == match.get("item_index")
            )
        ]
        # Only an active formal exact may bypass the semantic verifier.  An
        # inactive (rejected/unknown) verbatim target keeps its audit group but
        # must never suppress active semantic candidates for the same claim.
        active_formal_exact = [
            target for target in formal_exact
            if target[0]["review"]["eligibility"] == "active"
        ]
        inactive_formal_exact = [
            target for target in formal_exact
            if target[0]["review"]["eligibility"] != "active"
        ]
        semantic_exact = [target for target in exact if target not in formal_exact]
        candidates = [
            *[(target, basis, target["evidence"])
              for target, basis, _evidence in semantic_exact],
            *candidates,
        ]
        claim_groups: list[dict[str, Any]] = []
        if active_formal_exact:
            claim_groups.extend(
                _group(
                    claim,
                    target_generation_id=target_generation,
                    targets=[target],
                    validation_method="deterministic_verbatim",
                    verifier_runtime_fingerprint=str(runtime.get("fingerprint") or ""),
                    validation_generation_run_id=validation_generation_run_id,
                    controlled_term_aliases=controlled_term_aliases,
                obligation_hashes=anchor_obligation_hashes,
                )
                for target in active_formal_exact
            )
        claim_groups.extend(
            _group(
                claim,
                target_generation_id=target_generation,
                targets=[target],
                validation_method="deterministic_verbatim",
                verifier_runtime_fingerprint=str(runtime.get("fingerprint") or ""),
                validation_generation_run_id=validation_generation_run_id,
                controlled_term_aliases=controlled_term_aliases,
                obligation_hashes=anchor_obligation_hashes,
            )
            for target in inactive_formal_exact
        )
        if not active_formal_exact and candidates:
            # WS2 §4.2 sampling/baseline_gate：未选入闭合面的 claim 不创建语义候选组，
            # 保持 uncertain 并记 sampling_deferred（确定性 verbatim 组仍照常，零 LLM）。
            claim_id_text = str(claim.get("claim_id") or "")
            if (
                verifier_selection is not None
                and claim_id_text not in verifier_selection["selected_ids"]
            ):
                sampling_deferred_claim_ids.append(claim_id_text)
            else:
                active = [target for target in candidates
                          if target[0]["review"]["eligibility"] == "active"]
                inactive = [target for target in candidates
                            if target[0]["review"]["eligibility"] != "active"]
                if active:
                    claim_groups.append(_group(
                        claim,
                        target_generation_id=target_generation,
                        targets=active,
                        validation_method="independent_semantic",
                        verifier_runtime_fingerprint=str(runtime.get("fingerprint") or ""),
                        validation_generation_run_id=validation_generation_run_id,
                        controlled_term_aliases=controlled_term_aliases,
                obligation_hashes=anchor_obligation_hashes,
                    ))
                claim_groups.extend(
                    _group(
                        claim,
                        target_generation_id=target_generation,
                        targets=[target],
                        validation_method="independent_semantic",
                        verifier_runtime_fingerprint=str(runtime.get("fingerprint") or ""),
                        validation_generation_run_id=validation_generation_run_id,
                        controlled_term_aliases=controlled_term_aliases,
                obligation_hashes=anchor_obligation_hashes,
                    )
                    for target in inactive
                )
        groups.extend(claim_groups)
        groups_by_claim[str(claim["claim_id"])].extend(claim_groups)

    verifier_calls = 0
    verifier_tokens = 0
    verifier_failed_calls = 0
    verifier_operation_failure_count = 0
    verifier_usage_complete = True
    budget_exhausted = False
    coverage_budget_start = (
        verifier_budget.snapshot() if verifier_budget is not None else {}
    )
    semantic_verifier_candidate_count = sum(
        group.get("validation_method") == "independent_semantic"
        and group.get("status") == "proposed"
        and group.get("prefilter", {}).get("status") in {"pass", "not_applicable"}
        for group in groups
    )
    semantic_validation_reused = _reuse_semantic_validation(
        groups,
        list(reusable_groups or []),
    )
    if verifier_attempt_progress is not None:
        verifier_attempt_progress(
            semantic_verifier_candidate_count,
            semantic_validation_reused,
        )
    logical_call_ceiling = _logical_call_ceiling(
        baseline_calls=baseline_call_count,
        baseline_usage_complete=baseline_usage_complete,
        baseline_lineage_match=baseline_lineage_match,
    )
    planned_logical_call_count = 0
    coverage_verifier_deferred_count = 0
    coverage_verifier_oversized_count = 0
    negative_proposer_eligible_count = 0
    negative_proposer_selected_count = 0
    negative_proposer_deferred_count = 0
    negative_proposer_oversized_count = 0
    negative_verifier_deferred_count = 0
    negative_verifier_oversized_count = 0
    if semantic_verifier is not None:
        coverage_candidates = [
            _semantic_verifier_request(group)
            for group in groups
            if (
                group.get("status") == "proposed"
                and group.get("validation_method") == "independent_semantic"
                and group.get("prefilter", {}).get("status") in {"pass", "not_applicable"}
            )
        ]
        coverage_batches, oversized_coverage = _coverage_batches(
            coverage_candidates,
            runtime=runtime,
        )
        coverage_verifier_oversized_count = len(oversized_coverage)
        oversized_group_ids = {
            str(candidate.get("coverage_group_id") or "")
            for candidate in oversized_coverage
        }
        for group in groups:
            if str(group.get("coverage_group_id") or "") in oversized_group_ids:
                group["status"] = "invalid"
                group["invalid_reason"] = "verifier_request_too_large"
        rounds = max(1, int(runtime.get("rounds") or 1))
        if logical_call_ceiling is not None:
            coverage_batch_limit = max(
                1 if coverage_batches else 0,
                (logical_call_ceiling - planned_logical_call_count) // rounds,
            )
            selected_coverage_batches = coverage_batches[:coverage_batch_limit]
        else:
            selected_coverage_batches = coverage_batches
        coverage_verifier_deferred_count = len(oversized_coverage) + sum(
            len(batch) for batch in coverage_batches[len(selected_coverage_batches):]
        )
        planned_logical_call_count += len(selected_coverage_batches) * rounds
        for batch_index, candidates in enumerate(selected_coverage_batches, start=1):
            try:
                result = semantic_verifier(
                    f"COVERAGE-BATCH-{batch_index:04d}",
                    candidates,
                )
            except LLMBudgetExceeded:
                budget_exhausted = True
                break
            except Exception:
                verifier_calls += 1
                verifier_failed_calls += 1
                verifier_operation_failure_count += 1
                verifier_usage_complete = False
                continue
            try:
                envelope = _semantic_verifier_envelope(result)
            except (TypeError, ValueError):
                envelope = None
            if envelope is None:
                verifier_calls += 1
                verifier_failed_calls += 1
                verifier_operation_failure_count += 1
                verifier_usage_complete = False
                continue
            verifier_calls += int(envelope["call_count"])
            verifier_failed_calls += int(envelope["failed_call_count"])
            envelope_operation_failures = int(envelope["operation_failure_count"])
            verifier_operation_failure_count += envelope_operation_failures
            decisions = envelope["decisions"]
            request_id = str(envelope["request_id"] or "")
            if not isinstance(decisions, dict) or not request_id:
                verifier_failed_calls += 1
                if envelope_operation_failures == 0:
                    verifier_operation_failure_count += 1
                verifier_usage_complete = False
                candidate_ids = {
                    str(candidate.get("coverage_group_id") or "") for candidate in candidates
                }
                for group in groups:
                    if str(group.get("coverage_group_id") or "") in candidate_ids:
                        group["status"] = "invalid"
                        group["invalid_reason"] = "validator_response_invalid"
                continue
            verifier_tokens += int(envelope["tokens"])
            if envelope["usage_complete"] is not True:
                verifier_usage_complete = False
            missing_decision = False
            candidate_ids = {
                str(candidate.get("coverage_group_id") or "") for candidate in candidates
            }
            candidate_groups = [
                group for group in groups
                if str(group.get("coverage_group_id") or "") in candidate_ids
            ]
            for group in candidate_groups:
                decision = decisions.get(str(group["coverage_group_id"])) if isinstance(decisions, dict) else None
                if not isinstance(decision, dict):
                    missing_decision = True
                    group["status"] = "invalid"
                    group["invalid_reason"] = "validator_decision_missing"
                    continue
                group["validator_request_id"] = request_id
                group["validation_source"] = {
                    "generation_run_id": validation_generation_run_id,
                    "request_id": request_id,
                }
                group["validator_checks"] = dict(decision.get("checks") or {})
                group["validator_reason"] = str(decision.get("reason") or "")
                covered = decision.get("covered")
                if covered is True:
                    if _semantic_checks_complete(decision):
                        group["status"] = "validated"
                    else:
                        group["status"] = "invalid"
                        group["invalid_reason"] = "validator_evidence_incomplete"
                elif covered is False:
                    group["status"] = "invalid"
                    group["invalid_reason"] = "semantic_not_entailed"
            if missing_decision and envelope_operation_failures == 0:
                verifier_operation_failure_count += 1

    if verifier_budget is not None:
        coverage_verifier_calls, coverage_verifier_tokens = _budget_delta(
            coverage_budget_start,
            verifier_budget,
        )
    else:
        coverage_verifier_calls = verifier_calls
        coverage_verifier_tokens = verifier_tokens
    negative_proposer_calls = 0
    negative_proposer_tokens = 0
    negative_verifier_calls = 0
    negative_verifier_tokens = 0
    negative_proposer_budget_start = (
        verifier_budget.snapshot() if verifier_budget is not None else {}
    )
    negative_validation_reused = 0
    negative_by_claim: dict[str, dict[str, Any]] = {}
    negative_requests: dict[str, dict[str, Any]] = {}
    unit_by_id = {str(unit.get("unit_id") or ""): unit for unit in units}
    claim_by_id = {str(claim.get("claim_id") or ""): claim for claim in catalog}
    prior_negative_by_claim = {
        str(record.get("claim_id") or ""): record
        for record in (reusable_negatives or [])
        if isinstance(record, dict) and record.get("status") == "validated"
    }

    if (
        not budget_exhausted
        and semantic_negative_proposer is not None
        and route_mode != "stub"
    ):
        eligible_negative_requests: list[dict[str, Any]] = []
        for claim in catalog:
            if claim.get("eligibility") != "claim":
                continue
            claim_id = str(claim.get("claim_id") or "")
            # WS2 §4.2 sampling：未选入闭合面的 claim 也跳过负向验证（闭合面一致收窄）。
            if (
                verifier_selection is not None
                and claim_id not in verifier_selection["selected_ids"]
            ):
                continue
            if any(group.get("status") == "validated"
                   for group in groups_by_claim.get(claim_id, [])):
                continue
            unit_id = str(claim.get("owner_unit_id") or "")
            unit = unit_by_id.get(unit_id)
            if not unit:
                continue
            request = _negative_claim_request(claim, unit)
            negative_requests[claim_id] = request
            previous = prior_negative_by_claim.get(claim_id)
            if (previous
                    and semantic_negative_verifier is not None
                    and semantic_negative_record_error(
                        previous,
                        claim,
                        unit,
                        runtime,
                    ) is None):
                reused = dict(previous)
                reused["proposal"] = dict(previous.get("proposal") or {})
                reused["validation"] = dict(previous.get("validation") or {})
                reused["validation_reused"] = True
                negative_by_claim[claim_id] = reused
                negative_validation_reused += 1
                continue
            eligible_negative_requests.append(request)

        negative_proposer_eligible_count = len(eligible_negative_requests)
        if logical_call_ceiling is not None:
            remaining_planned_calls = max(
                0, logical_call_ceiling - planned_logical_call_count
            )
            pair_cost = 1 + max(1, int(runtime.get("rounds") or 1))
            negative_batch_pair_limit = min(
                CLAIM_NEGATIVE_MAX_BATCH_PAIRS,
                remaining_planned_calls // pair_cost,
            )
            selected_negative_requests = _select_negative_probe_requests(
                eligible_negative_requests,
                max_claims=negative_batch_pair_limit * CLAIM_NEGATIVE_BATCH_MAX_CLAIMS,
                max_units=negative_batch_pair_limit * CLAIM_NEGATIVE_UNITS_PER_BATCH,
            )
            proposer_batches, oversized_proposer = _negative_batches(
                selected_negative_requests,
                runtime=runtime,
                operation="proposer",
            )
            proposer_batches = proposer_batches[:negative_batch_pair_limit]
        else:
            proposer_batches, oversized_proposer = _negative_batches(
                eligible_negative_requests,
                runtime=runtime,
                operation="proposer",
            )
        negative_proposer_oversized_count = len(oversized_proposer)
        selected_negative_requests = [
            request for batch in proposer_batches for request in batch
        ]
        selected_negative_ids = {
            str(request.get("claim_id") or "") for request in selected_negative_requests
        }
        negative_proposer_selected_count = len(selected_negative_ids)
        negative_proposer_deferred_count = max(
            0, negative_proposer_eligible_count - negative_proposer_selected_count
        )
        planned_logical_call_count += len(proposer_batches)

        for batch_index, requests in enumerate(proposer_batches, start=1):
            try:
                result = semantic_negative_proposer(
                    f"NEGATIVE-PROPOSER-BATCH-{batch_index:04d}", requests
                )
                envelope = _semantic_verifier_envelope(result)
            except LLMBudgetExceeded:
                budget_exhausted = True
                break
            except Exception:
                envelope = None
            if envelope is None:
                verifier_calls += 1
                negative_proposer_calls += 1
                verifier_failed_calls += 1
                verifier_operation_failure_count += 1
                verifier_usage_complete = False
                continue
            calls = int(envelope["call_count"])
            tokens = int(envelope["tokens"])
            verifier_calls += calls
            verifier_tokens += tokens
            negative_proposer_calls += calls
            negative_proposer_tokens += tokens
            verifier_failed_calls += int(envelope["failed_call_count"])
            envelope_operation_failures = int(envelope["operation_failure_count"])
            verifier_operation_failure_count += envelope_operation_failures
            if envelope["usage_complete"] is not True:
                verifier_usage_complete = False
            decisions = envelope["decisions"]
            request_id = str(envelope["request_id"] or "")
            if not isinstance(decisions, dict) or not request_id:
                verifier_failed_calls += 1
                if envelope_operation_failures == 0:
                    verifier_operation_failure_count += 1
                verifier_usage_complete = False
                continue
            for request in requests:
                claim_id = str(request.get("claim_id") or "")
                decision = decisions.get(claim_id)
                if not isinstance(decision, dict) or decision.get("non_normative") is not True:
                    continue
                claim = claim_by_id.get(claim_id)
                if claim is None:
                    continue
                negative_by_claim[claim_id] = _negative_record(
                    claim,
                    request,
                    decision,
                    request_id=request_id,
                    verifier_runtime=runtime,
                    validation_generation_run_id=validation_generation_run_id,
                )

    if verifier_budget is not None:
        negative_proposer_calls, negative_proposer_tokens = _budget_delta(
            negative_proposer_budget_start,
            verifier_budget,
        )

    negative_verifier_budget_start = (
        verifier_budget.snapshot() if verifier_budget is not None else {}
    )
    if (
        not budget_exhausted
        and semantic_negative_verifier is not None
        and negative_by_claim
    ):
        proposed_requests: list[dict[str, Any]] = []
        for claim_id, record in negative_by_claim.items():
            if record.get("status") != "proposed":
                continue
            request = negative_requests[claim_id]
            proposed_requests.append(request)
        verifier_batches, oversized_negative_verifier = _negative_batches(
            proposed_requests,
            runtime=runtime,
            operation="verifier",
        )
        negative_verifier_oversized_count = len(oversized_negative_verifier)
        if logical_call_ceiling is not None:
            rounds = max(1, int(runtime.get("rounds") or 1))
            remaining_planned_calls = max(
                0, logical_call_ceiling - planned_logical_call_count
            )
            verifier_batch_limit = remaining_planned_calls // rounds
            selected_verifier_batches = verifier_batches[:verifier_batch_limit]
        else:
            selected_verifier_batches = verifier_batches
        negative_verifier_deferred_count = len(oversized_negative_verifier) + sum(
            len(batch) for batch in verifier_batches[len(selected_verifier_batches):]
        )
        planned_logical_call_count += (
            len(selected_verifier_batches) * max(1, int(runtime.get("rounds") or 1))
        )
        for batch_index, requests in enumerate(selected_verifier_batches, start=1):
            records = [negative_by_claim[str(request["claim_id"])] for request in requests]
            try:
                result = semantic_negative_verifier(
                    f"NEGATIVE-VERIFIER-BATCH-{batch_index:04d}", requests
                )
                envelope = _semantic_verifier_envelope(result)
            except LLMBudgetExceeded:
                budget_exhausted = True
                break
            except Exception:
                envelope = None
            if envelope is None:
                verifier_calls += 1
                negative_verifier_calls += 1
                verifier_failed_calls += 1
                verifier_operation_failure_count += 1
                verifier_usage_complete = False
                for record in records:
                    record["status"] = "invalid"
                    record["invalid_reason"] = "negative_validator_failed"
                continue
            calls = int(envelope["call_count"])
            tokens = int(envelope["tokens"])
            verifier_calls += calls
            verifier_tokens += tokens
            negative_verifier_calls += calls
            negative_verifier_tokens += tokens
            verifier_failed_calls += int(envelope["failed_call_count"])
            envelope_operation_failures = int(envelope["operation_failure_count"])
            verifier_operation_failure_count += envelope_operation_failures
            if envelope["usage_complete"] is not True:
                verifier_usage_complete = False
            decisions = envelope["decisions"]
            request_id = str(envelope["request_id"] or "")
            if not isinstance(decisions, dict) or not request_id:
                verifier_failed_calls += 1
                if envelope_operation_failures == 0:
                    verifier_operation_failure_count += 1
                verifier_usage_complete = False
                for record in records:
                    record["status"] = "invalid"
                    record["invalid_reason"] = "negative_validator_response_invalid"
                continue
            missing_decision = False
            for request, record in zip(requests, records):
                claim_id = str(request.get("claim_id") or "")
                decision = decisions.get(claim_id)
                if not isinstance(decision, dict):
                    missing_decision = True
                    record["status"] = "invalid"
                    record["invalid_reason"] = "negative_validator_decision_missing"
                    continue
                _apply_negative_validation(
                    record,
                    decision,
                    request_id=request_id,
                    source_text=str(request.get("source_evidence", {}).get("text") or ""),
                    validation_generation_run_id=validation_generation_run_id,
                )
            if missing_decision and envelope_operation_failures == 0:
                verifier_operation_failure_count += 1

    if verifier_budget is not None:
        negative_verifier_calls, negative_verifier_tokens = _budget_delta(
            negative_verifier_budget_start,
            verifier_budget,
        )

    for claim_id, record in negative_by_claim.items():
        claim = claim_by_id[claim_id]
        unit = unit_by_id.get(str(claim.get("owner_unit_id") or ""))
        error = semantic_negative_record_error(record, claim, unit, runtime)
        if error:
            record["status"] = "invalid"
            record["invalid_reason"] = error

    verifier_budget_outcome = _verifier_budget_outcome(
        verifier_budget,
        runtime,
        attempted_calls=verifier_calls,
        failed_calls=verifier_failed_calls,
        accounted_tokens=verifier_tokens,
        usage_complete=verifier_usage_complete,
        budget_exhausted=budget_exhausted,
    )
    if verifier_budget is not None:
        verifier_calls = int(verifier_budget_outcome["attempted_calls"])
        verifier_failed_calls = int(verifier_budget_outcome["failed_calls"])
        verifier_tokens = int(verifier_budget_outcome["accounted_tokens"])
        verifier_usage_complete = verifier_budget_outcome["usage_complete"] is True
    budget_exhausted = (
        budget_exhausted or verifier_budget_outcome.get("denied") is True
    )

    negative_decisions = [negative_by_claim[key] for key in sorted(negative_by_claim)]
    ledger: list[dict[str, Any]] = []
    for claim in catalog:
        claim_id = str(claim.get("claim_id") or "")
        claim_groups = groups_by_claim.get(claim_id, [])
        ledger.append(reduce_claim(
            claim,
            validated_groups=[group for group in claim_groups if group.get("status") == "validated"],
            validated_negative=negative_by_claim.get(claim_id),
            all_groups=claim_groups,
        ))
    metrics = _metrics(
        catalog,
        ledger,
        groups,
        negative_decisions,
        requirements,
        unit_count=len(units),
        verifier_calls=verifier_calls,
        verifier_tokens=verifier_tokens,
        verifier_failed_calls=verifier_failed_calls,
        verifier_operation_failure_count=verifier_operation_failure_count,
        verifier_usage_complete=verifier_usage_complete,
        semantic_verifier_enabled=ledger_llm_enabled,
        semantic_validation_reused=semantic_validation_reused,
        semantic_verifier_candidate_count=semantic_verifier_candidate_count,
        coverage_verifier_calls=coverage_verifier_calls,
        coverage_verifier_tokens=coverage_verifier_tokens,
        negative_proposer_calls=negative_proposer_calls,
        negative_proposer_tokens=negative_proposer_tokens,
        negative_verifier_calls=negative_verifier_calls,
        negative_verifier_tokens=negative_verifier_tokens,
        negative_validation_reused=negative_validation_reused,
        logical_call_ceiling=logical_call_ceiling,
        planned_logical_call_count=planned_logical_call_count,
        coverage_verifier_deferred_count=coverage_verifier_deferred_count,
        coverage_verifier_oversized_count=coverage_verifier_oversized_count,
        negative_proposer_eligible_count=negative_proposer_eligible_count,
        negative_proposer_selected_count=negative_proposer_selected_count,
        negative_proposer_deferred_count=negative_proposer_deferred_count,
        negative_proposer_oversized_count=negative_proposer_oversized_count,
        negative_verifier_deferred_count=negative_verifier_deferred_count,
        negative_verifier_oversized_count=negative_verifier_oversized_count,
        shared_block_only_hints=shared_block_only_hints,
        baseline_call_count=max(0, int(baseline_call_count)),
        baseline_failed_call_count=max(0, int(baseline_failed_call_count)),
        baseline_tokens=max(0, int(baseline_tokens)),
        baseline_usage_complete=bool(baseline_usage_complete),
        baseline_lineage_match=bool(baseline_lineage_match),
        verifier_budget_outcome=verifier_budget_outcome,
        failed_extraction_units=len(failed_extraction_unit_ids),
    )
    accounting_status = (
        "complete"
        if catalog_build.get("meta", {}).get("accounting_status") == "complete"
        and len(ledger) == len(catalog)
        else "incomplete"
    )
    resolution_status = "resolved" if metrics["uncertain_count"] == 0 else "open"
    termination_reason = (
        "budget_exhausted"
        if budget_exhausted
        else "converged" if resolution_status == "resolved"
        else "llm_error" if verifier_operation_failure_count else "stalled_open"
    )
    return {
        "catalog": catalog,
        "groups": groups,
        "negative_decisions": negative_decisions,
        "ledger": ledger,
        "metrics": metrics,
        "meta": {
            "schema": "claim-shadow-result/v1",
            "ledger_schema_version": CLAIM_LEDGER_SCHEMA_VERSION,
            "catalog_generation_id": catalog_build.get("meta", {}).get("catalog_generation_id"),
            "target_generation_id": target_generation,
            "target_review_authority_revision": authority_revision,
            "delivery_track": "B",
            "target_kind": "ai_requirement",
            "route_mode": route_mode,
            "semantic_verifier_enabled": ledger_llm_enabled,
            "coverage_verifier_enabled": semantic_verifier is not None,
            "semantic_negative_proposer_enabled": semantic_negative_proposer is not None,
            "semantic_negative_verifier_enabled": semantic_negative_verifier is not None,
            "verifier_runtime": runtime,
            "verifier_budget": verifier_budget_outcome,
            "scope": catalog_build.get("meta", {}).get("scope", "full"),
            "extraction_status": effective_extraction_status,
            "accounting_status": accounting_status,
            "resolution_status": resolution_status,
            "termination_reason": termination_reason,
            "document_ready": False,
            "versions": current_base_versions(),
            # WS2 §4.2 抽检模式留痕（mode='full' 时 sampling=None，与现状 meta 同形）
            "claim_ledger_mode": mode_resolved,
            "claim_ledger_mode_version": CLAIM_LEDGER_MODE_VERSION,
            "sampling": (
                None if verifier_selection is None
                else {
                    "mode": verifier_selection.get("mode"),
                    "eligible_count": verifier_selection.get("eligible_count"),
                    "selected_count": len(verifier_selection.get("selected_ids") or set()),
                    "sampled_count": len(verifier_selection.get("sampled_ids") or []),
                    "high_risk_count": len(verifier_selection.get("high_risk_ids") or []),
                    "deferred_count": len(verifier_selection.get("deferred_ids") or []),
                    "sampling_rate": verifier_selection.get("sampling_rate"),
                    "selected_ratio": verifier_selection.get("selected_ratio", 1.0),
                    "escalate": verifier_selection.get("escalate"),
                    "threshold_met": verifier_selection.get("threshold_met"),
                    # S1-5：未抽中 claim 清单=抽样决策的完整 deferred 集（selection-time 权威）。
                    # 此前只用 sampling_deferred_claim_ids——它只收录带语义候选的 deferred claim，
                    # 无候选的 deferred claim（如无 target 匹配）被漏记，清单与 deferred_count 不一致。
                    "deferred_in_run": sorted(set(
                        list(verifier_selection.get("deferred_ids") or [])
                        + list(sampling_deferred_claim_ids)
                    )),
                }
            ),
        },
    }


def current_base_versions() -> dict[str, str]:
    """Versions that invalidate immutable generation facts, never extraction output."""
    return {
        "ledger": CLAIM_LEDGER_SCHEMA_VERSION,
        "prompt": CLAIM_LEDGER_PROMPT_VERSION,
        "candidate_policy": CLAIM_CANDIDATE_POLICY_VERSION,
        "prefilter": CLAIM_EDGE_PREFILTER_VERSION,
        "coverage_validator": CLAIM_COVERAGE_VALIDATOR_VERSION,
        "batch_policy": CLAIM_VERIFIER_BATCH_POLICY_VERSION,
        "cost_policy": CLAIM_COST_POLICY_VERSION,
        "negative_policy": CLAIM_NEGATIVE_POLICY_VERSION,
        "negative_validator": CLAIM_NEGATIVE_VALIDATOR_VERSION,
        "review_adapter": CLAIM_REVIEW_ADAPTER_VERSION,
        "reducer": CLAIM_REDUCER_VERSION,
        "validation_reuse": CLAIM_VALIDATION_REUSE_VERSION,
        "audit": CLAIM_AUDIT_POLICY_VERSION,
    }


def current_effective_versions() -> dict[str, str]:
    from claim_artifacts import (
        CLAIM_EFFECTIVE_ARTIFACT_PROTOCOL_VERSION,
        CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
    )

    return {
        "effective_snapshot": CLAIM_EFFECTIVE_SNAPSHOT_VERSION,
        "effective_artifacts": CLAIM_EFFECTIVE_ARTIFACT_PROTOCOL_VERSION,
        "effective_ledger_schema": CLAIM_EFFECTIVE_LEDGER_SCHEMA,
        "effective_reducer": CLAIM_EFFECTIVE_REDUCER_VERSION,
        "review_bridge": CLAIM_REVIEW_BRIDGE_VERSION,
        "review_event_schema": CLAIM_REVIEW_EVENT_SCHEMA,
        "queue": CLAIM_QUEUE_VERSION,
    }


def current_shadow_versions() -> dict[str, str]:
    """Legacy alias retained for callers that mean immutable base versions."""
    return current_base_versions()


def _publish_claim_ledger_mode() -> str:
    """S1-5：B 轨发布路径的 claim ledger mode。

    * env ``RATOMIZER_CLAIM_LEDGER_MODE`` **显式设置**（sampling/baseline_gate/full）→
      经 ``resolve_claim_ledger_mode`` 解析后在发布路径真实生效（sampling 收窄闭合面并留痕
      未抽中 claim，baseline_gate 触发发布门禁全量闭合）。
    * env **未设置** → ``"full"``（生产默认行为逐字节不变——硬边界「其余各项默认行为不变」；
      把 sampling 翻转为生产默认属语义变更，留待 S2 数字后显式决策）。

    注意 ``resolve_claim_ledger_mode()`` 自身在 env 未设时返回 ``DEFAULT_CLAIM_LEDGER_MODE``
    （"sampling"）——那是配置解析层的默认档；本函数把「发布路径默认 full」与「解析层默认
    sampling」两个口径分开，使 env 设置在发布路径 opt-in 生效而不悄悄翻转生产行为。
    """
    raw = os.environ.get("RATOMIZER_CLAIM_LEDGER_MODE")
    if raw is None or not str(raw).strip():
        return "full"
    return resolve_claim_ledger_mode(raw)


def _write_sampling_deferred_summary(root: Path, shadow: dict[str, Any]) -> None:
    """S1-5 留痕：sampling/baseline_gate 模式下未抽中 claim 的计数/清单写入 governed summary。

    「保障被推迟至发布门禁」的事实必须留痕（方案原话）：sampling 收窄闭合面后被延迟到发布
    门禁的 claim 清单不能只活在内存 shadow 里。写 ``claim_sampling_summary.json``（governed
    state 路径 + 跨进程锁 + 原子替换），与 shadow meta 的 sampling 块同源。full 模式不写
    （无延迟，行为面不动）。落盘失败不阻断发布——shadow meta 已是权威记录，此处只补一份
    人读/机器读的独立 quality_report 口径留痕。
    """
    meta = (shadow or {}).get("meta") or {}
    mode = str(meta.get("claim_ledger_mode") or "")
    sampling = meta.get("sampling")
    if mode == "full" or not isinstance(sampling, dict):
        return
    from result_package import governed_artifact_path

    summary = {
        "schema": "claim-sampling-summary/v1",
        "mode": mode,
        "eligible_count": int(sampling.get("eligible_count") or 0),
        "selected_count": int(sampling.get("selected_count") or 0),
        "deferred_count": int(sampling.get("deferred_count") or 0),
        "deferred_claim_ids": list(sampling.get("deferred_in_run") or []),
        "sampling_rate": sampling.get("sampling_rate"),
        "selected_ratio": sampling.get("selected_ratio"),
        "escalate": sampling.get("escalate"),
    }
    target = governed_artifact_path(
        root, "claim_sampling_summary.json", category="state", for_write=True
    )
    lock_path = governed_artifact_path(
        root, "claim_sampling_summary.lock", category="state", for_write=True
    )
    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        from process_file_lock import process_file_lock

        with process_file_lock(lock_path, timeout_s=10.0, label="claim_sampling_summary"):
            tmp.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            os.replace(tmp, target)
    except Exception as exc:  # 留痕失败不阻断发布（shadow meta 已是权威记录）
        logging.getLogger("requirement_atomizer").warning(
            "claim_sampling_summary 落盘失败：%s", exc
        )
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _read_store_rows(root: Path, store: str) -> list[dict[str, Any]]:
    """显式 store 的行读取（JSONL 原子 / JSON items 直抽）。"""
    from claim_artifacts import _read_b_track_requirements

    return _read_b_track_requirements(root, store)


def resolve_b_track_target_store(root: Path | str) -> tuple[str, list[dict[str, Any]]]:
    """§3.4：解析 B 轨 target store——原子产物在场优先；否则直抽产物（FRE- 主键）。

    返回 (store 文件名, target 行)。直抽产物必须守恒闭合且执行完整
    （``functional_direct_basis`` 会响亮 raise），不让失败/不守恒产物进 claim 绑定。
    两者都不在场时抛 FileNotFoundError（与旧缺文件行为同族，不静默空账本）。
    """
    from claim_artifacts import FUNCTIONAL_REQUIREMENTS_STORE

    root = Path(root).expanduser().resolve()
    atomic_path = root / "ai_requirements.jsonl"
    if atomic_path.is_file():
        from io_utils import read_jsonl
        return "ai_requirements.jsonl", list(read_jsonl(atomic_path))
    from functional_extract import functional_direct_basis

    direct = functional_direct_basis(root)
    if direct is not None:
        return FUNCTIONAL_REQUIREMENTS_STORE, list(direct)
    raise FileNotFoundError(
        f"no B-track target store under {root}: ai_requirements.jsonl / "
        f"{FUNCTIONAL_REQUIREMENTS_STORE} are both absent or not a valid direct product"
    )


def publish_b_track_shadow(
    out_dir: Path | str,
    run_id: str,
    route_mode: str,
    extraction_status: str,
    catalog_build: dict[str, Any] | None = None,
    requirements: list[dict[str, Any]] | None = None,
    requirements_store: str | None = None,
    scope: str = "full",
    controlled_term_aliases: dict[str, list[str]] | None = None,
    failed_section_block_ids: Iterable[str] | None = None,
    semantic_verifier: SemanticVerifier | None = None,
    semantic_negative_proposer: SemanticNegativeProposer | None = None,
    semantic_negative_verifier: SemanticNegativeVerifier | None = None,
    reusable_groups: list[dict[str, Any]] | None = None,
    reusable_negatives: list[dict[str, Any]] | None = None,
    baseline_call_count: int = 0,
    baseline_failed_call_count: int = 0,
    baseline_tokens: int = 0,
    baseline_usage_complete: bool = False,
    baseline_cost: dict[str, Any] | None = None,
    verifier_runtime: dict[str, Any] | None = None,
    verifier_budget: LLMRequestBudget | None = None,
    on_shadow_built: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Rebuild and atomically publish the B-track Phase 0 shadow generation."""
    from ai_review_actions import read_ai_review_states
    from claim_artifacts import (
        B_TRACK_TARGET_STORES,
        file_sha256,
        publish_shadow_generation,
        record_verifier_attempt_progress,
    )
    from claim_catalog import build_catalog_from_directory
    from io_utils import read_jsonl

    root = Path(out_dir).expanduser().resolve()
    # §3.4：target store 解析——显式传入优先；未传时按在场产物解析（原子优先，直抽次之）。
    if requirements_store is None:
        try:
            requirements_store, resolved_rows = resolve_b_track_target_store(root)
        except FileNotFoundError:
            requirements_store, resolved_rows = "ai_requirements.jsonl", read_jsonl(
                root / "ai_requirements.jsonl")
    elif requirements_store not in B_TRACK_TARGET_STORES:
        raise ValueError(f"unknown B-track requirements store: {requirements_store}")
    else:
        resolved_rows = None
    current_requirements = (
        list(requirements)
        if requirements is not None
        else (resolved_rows if resolved_rows is not None else (
            _read_store_rows(root, requirements_store)))
    )
    normalized_route = "stub" if route_mode == "stub" else "llm"
    normalized_extraction_status = (
        extraction_status
        if extraction_status in {"success", "partial", "failed"}
        else "success" if extraction_status == "stub" else "failed"
    )
    current_catalog = catalog_build or build_catalog_from_directory(root, scope=scope)
    # 复审 P2-1：functional store 的源锚按当前义务重算文本身份（原子目标无锚，
    # 索引只对带 evidence_anchors 的 target 生效；计算失败=不可核验，如实跳过）
    from claim_artifacts import FUNCTIONAL_REQUIREMENTS_STORE

    anchor_hashes = (
        functional_anchor_obligation_hashes(root)
        if requirements_store == FUNCTIONAL_REQUIREMENTS_STORE
        else None
    )
    shadow = build_shadow_ledger(
        current_catalog,
        current_requirements,
        review_states=read_ai_review_states(root),
        controlled_term_aliases=controlled_term_aliases,
        semantic_verifier=semantic_verifier,
        semantic_negative_proposer=semantic_negative_proposer,
        semantic_negative_verifier=semantic_negative_verifier,
        reusable_groups=reusable_groups,
        reusable_negatives=reusable_negatives,
        route_mode=normalized_route,
        extraction_status=normalized_extraction_status,
        failed_section_block_ids=failed_section_block_ids,
        baseline_call_count=baseline_call_count,
        baseline_failed_call_count=baseline_failed_call_count,
        baseline_tokens=baseline_tokens,
        baseline_usage_complete=baseline_usage_complete,
        baseline_cost=baseline_cost,
        verifier_runtime=verifier_runtime,
        verifier_budget=verifier_budget,
        verifier_attempt_progress=lambda candidates, reused: (
            record_verifier_attempt_progress(
                root,
                candidate_group_count=candidates,
                reused_group_count=reused,
            )
        ),
        validation_generation_run_id=run_id,
        # S1-5：env 显式设置的 claim ledger mode 在发布路径真实生效（build_shadow_ledger 自身
        # 默认 full，直接调用者/既有测试不动）；env 未设时发布路径默认 full（生产行为不变）。
        mode=_publish_claim_ledger_mode(),
        anchor_obligation_hashes=anchor_hashes,
    )
    if on_shadow_built is not None:
        # Crash window probe: the paid verifier decisions exist only in memory
        # until the WAL commits them; the hook makes them durable beforehand.
        on_shadow_built(shadow)
    # S1-5：sampling/baseline_gate 模式留痕未抽中 claim 清单到 governed summary（quality_report 口径）。
    _write_sampling_deferred_summary(root, shadow)
    requirements_path = root / requirements_store
    requirements_hash = (
        file_sha256(requirements_path) if requirements_path.is_file() else ""
    )
    generation = publish_shadow_generation(
        root,
        current_catalog,
        shadow,
        run_id=run_id,
        requirements_sha256=requirements_hash,
        requirements_store=requirements_store,
    )
    effective_fold: dict[str, Any] | None = None
    try:
        from claim_review_actions import fold_effective_ledger

        effective_fold = fold_effective_ledger(
            root,
            actor_trigger="ai-extract-publish",
        )
    except Exception as exc:
        # Base generation is authoritative and already committed. Runtime ledger
        # lag must never turn a successful extraction into a failed extraction.
        logging.getLogger("requirement_atomizer").warning(
            "claim effective fold lagged after base publication: %s",
            exc,
        )
    return {
        "generation_meta": generation,
        "shadow": shadow,
        "effective_fold": effective_fold,
    }
