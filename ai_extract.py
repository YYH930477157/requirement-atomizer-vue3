"""AI 主导需求抽取（杠杆②）。

LLM 逐章节读已解析文本 → 直接产出功能级结构化需求（标题/自包含描述/类型/优先级/标签/
原文引用/验收）。面向"通用文档解读"：DLMS 结构化与通用标准文档统一一套流程。

防幻觉（数字双引擎，分严/松级）：
- 受保护编码（OBIS / 事件号 / 十六进制，extract_codes）只能来自源文/确定性层。LLM 输出里
  冒出原文没有的这类编码 → **严格拦**：该条降级 draft + 记 note，不当已确认。
- 普通整数（extract_ints）漂移 → **软标**：可能是 LLM 合理展开（如"RS-485"），记 note 待核，保留。

可复现（稳定）：温度 0 + 章节内容指纹缓存（同文本 + 同模型 → 命中、零再调，重跑逐字一致）。
成本：相邻小章节合并到目标字数再调（少调用）+ 并发；失败按章节降级、不崩。

route（复用 review_pipeline.yaml）：默认 stub（零 LLM）；openai_compatible 才真调
（DeepSeek / Ollama 等，OpenAI 兼容）。

用法：python -m ai_extract --out <atomizer 输出目录> [--route openai_compatible] [--doc]
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
import os
import re
import tempfile
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import OrderedDict
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from cosem_behavior_spec import extract_codes, extract_ints
from compliance import (
    COMPLIANCE_TYPE,
    build_compliance_payload,
    is_compliance_requirement,
    is_compliance_umbrella_source,
    normalize_obligations,
    resolve_source_backed_instrument,
)
from llm_client import (
    LLMClientConfig,
    LLMError,
    LLMRequestBudget,
    chat_json,
    llm_attempt_policy,
)
from io_utils import read_jsonl_recover_torn_tail
from llm_pipeline import (
    DEFAULT_PIPELINE_PATH,
    apply_llm_environment_overrides,
    llm_config_from_route,
    load_review_pipeline,
    read_jsonl,
    resolve_route_name,
)
from spec_excel import METERING_DOMAINS  # 受控模块词表（DLMS 域 + 通用补充）
import table_structure

OTHER_MODULE = "其它"  # LLM 判定"无贴切模块"的逃生项（与 spec_export.OTHER_DOMAIN 对齐）
MODULE_VOCAB = list(METERING_DOMAINS) + [OTHER_MODULE]

from extract_units import (  # noqa: F401 —— F3 拆分门面：旧名保持可用
    CHAPTER_MAX_CHARS, CHAPTER_MIN_MAX_TOKENS, CLAUSE_FAMILY_MAX_FACTOR,
    MAX_REFS_PER_SECTION, REF_EXCERPT_CHARS, TERM_DEFS_MAX, TERM_DEF_CHARS, UNIT_MODE_ENV,
    _CLAUSE_HEADING_RE, _CLAUSE_REF_RE, _TERMS_HEADING_RE, _TERM_NAME_RE,
    _TOC_LEADER_RUN_RE, _TOC_LINE_END_RE, _finalize_merged, _is_toc_line,
    DEFAULT_MERGE_CHARS, _normalize_clause_ref, _pack_sections, _split_text, assemble_sections,
    attach_term_definitions, body_blocks, clause_key, clean_block_text, collect_term_entries,
    merge_sections, resolve_section_refs, sample_sections,
)
from extract_guards import (  # noqa: F401
    _LEFT_BEHIND_MIN, _LEFT_BEHIND_WINDOW, _TESTABLE_HINT_RE, _VAGUE_PHRASES,
    foreign_standard_refs, _gram_jaccard, _is_definition_stub, _modal_inflation,
    _multi_value_pairing_risk, _norm_ws, _num_multiset, _produced_text, _req_key,
    _threshold_desc_mismatch, strip_produced_refs, vague_acceptance, values_left_behind,
)

LOGGER = logging.getLogger("requirement_atomizer")

AI_EXTRACT_PROMPT_VERSION = "ai-extract-v23"  # v23：正式 target 叶子强制自包含产品义务成文
CLAIM_FOCUS_CRITIQUE_VERSION = "claim-focus-critique-v1"
SELF_CHECK_ENV = "RATOMIZER_AI_SELFCHECK"  # 完整性自检开关（默认开；=0/false/off 关）
SELF_CHECK_ROUNDS_ENV = "RATOMIZER_AI_SELFCHECK_ROUNDS"  # 自检收敛轮数上限（默认 3，防发散）
DEFAULT_SELF_CHECK_MAX_ROUNDS = 3
MAX_SELF_CHECK_ROUNDS = 6  # 硬上限：再多也几乎无新增，纯烧 token
DOC_CONTEXT_GLOSSARY_MAX = 1800   # 术语表注入上限（控 token 成本）
DOC_CONTEXT_OUTLINE_MAX = 60      # 章节大纲最多条目
AI_EXTRACT_CACHE = "ai_extract_cache.jsonl"
AI_REQUIREMENTS = "ai_requirements.jsonl"
AI_REQUIREMENTS_META = "ai_requirements.meta.json"
AI_REQUIREMENTS_PRODUCER_LINEAGE_VERSION = "ai-requirements-producer-lineage-v3"  # v3:lineage 经共享 deterministic_extraction_versions() 纳入 compliance_schema(v2 漏钉)
AI_NORMATIVE_FRAMING_VERSION = "ai-normative-framing-v2"
NO_LEDGER_BASELINE_LINEAGE_VERSION = "no-ledger-baseline-lineage-v2"
COMPLIANCE_REQUIREMENTS = "compliance_requirements.json"
AI_REQUIREMENTS_PARTIAL = "ai_requirements.partial.json"
AI_PARTIAL_SCHEMA = "ai-requirements-partial/v1"
DEFAULT_CONCURRENCY = 8   # 4→8（2026-07-14 提速）：IO 等待型并发,mimo 端点 8 并发实测稳定
MAX_CONCURRENCY = 16
CONCURRENCY_ENV = "RATOMIZER_LLM_CONCURRENCY"
# 推理模型（如 deepseek-v4-flash / GLM-5.2）会先花大量 token 在隐藏 reasoning 上，
# max_tokens 太小会把正文 JSON 截断 → finish_reason=length → 解析失败 → 整章节判失败。
# 实测 deepseek-v4-flash：1024 必截断；2800 字章节正文最高用到 ~3500 token，6144 留足余量。
# 注意：仅抬 max_tokens 不够——超大源章节（5k-9k 字）即便 8192 也会截断，必须配合 merge_sections
# 的拆分（每次 LLM 输入 ≤target_chars），二者缺一不可。
AI_EXTRACT_MIN_MAX_TOKENS = 6144

ChatFn = Callable[[str, str], dict[str, Any]]
_DEFAULT_CHAT_JSON = chat_json
CLAIM_SHADOW_VERIFY_ENV = "RATOMIZER_CLAIM_SHADOW_VERIFY"
CLAIM_SHADOW_VERIFY_ROUNDS_ENV = "RATOMIZER_CLAIM_SHADOW_VERIFY_ROUNDS"
CLAIM_SHADOW_VERIFY_MAX_CALLS_ENV = "RATOMIZER_CLAIM_SHADOW_VERIFY_MAX_CALLS"
CLAIM_SHADOW_VERIFY_MAX_TOTAL_TOKENS_ENV = (
    "RATOMIZER_CLAIM_SHADOW_VERIFY_MAX_TOTAL_TOKENS"
)


def resolve_claim_shadow_verify(explicit: bool | None = None) -> bool:
    """Independent claim coverage verification is on for real LLM shadow runs."""
    if explicit is not None:
        return bool(explicit)
    raw = os.environ.get(CLAIM_SHADOW_VERIFY_ENV, "").strip().lower()
    if not raw:
        return True
    return raw not in ("0", "false", "no", "off")


def resolve_claim_shadow_verify_rounds(explicit: int | None = None) -> int:
    if explicit is None:
        try:
            explicit = int(os.environ.get(CLAIM_SHADOW_VERIFY_ROUNDS_ENV, "1"))
        except ValueError:
            explicit = 1
    return max(1, min(3, int(explicit)))


def _resolve_nonnegative_int_env(name: str, explicit: int | None = None) -> int:
    if explicit is None:
        try:
            explicit = int(os.environ.get(name, "0"))
        except ValueError:
            explicit = 0
    if isinstance(explicit, bool):
        return 0
    return max(0, int(explicit))


def resolve_claim_shadow_verify_max_calls(explicit: int | None = None) -> int:
    """Return the explicitly authorized verifier HTTP-attempt ceiling."""
    return _resolve_nonnegative_int_env(CLAIM_SHADOW_VERIFY_MAX_CALLS_ENV, explicit)


def resolve_claim_shadow_verify_max_total_tokens(explicit: int | None = None) -> int:
    """Return the explicitly authorized verifier aggregate-token ceiling."""
    return _resolve_nonnegative_int_env(
        CLAIM_SHADOW_VERIFY_MAX_TOTAL_TOKENS_ENV,
        explicit,
    )


def claim_shadow_verifier_budget(
    *,
    max_calls: int | None = None,
    max_total_tokens: int | None = None,
) -> LLMRequestBudget | None:
    """Create one generation-wide budget only when both hard limits are authorized."""
    resolved_calls = resolve_claim_shadow_verify_max_calls(max_calls)
    resolved_tokens = resolve_claim_shadow_verify_max_total_tokens(max_total_tokens)
    if resolved_calls <= 0 or resolved_tokens <= 0:
        return None
    return LLMRequestBudget(max_calls=resolved_calls, max_tokens=resolved_tokens)


def _chat_json_accounted(
    config: LLMClientConfig,
    system: str,
    user: str,
    *,
    request_budget: LLMRequestBudget | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Preserve test/injected chat functions while collecting exact production usage."""
    if chat_json is _DEFAULT_CHAT_JSON:
        from llm_client import chat_json_with_meta

        return chat_json_with_meta(
            config,
            system,
            user,
            request_budget=request_budget,
        )
    return chat_json(config, system, user), {
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "usage_complete": False,
        "call_count": 1,
        "failed_call_count": 0,
    }


def _replace_with_retry(source: Path, target: Path, *, attempts: int = 8) -> None:
    """Atomic replace with a short Windows reader-lock retry window."""
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt + 1 >= attempts:
                raise
            time.sleep(0.02 * (attempt + 1))


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.{os.getpid()}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = b"".join(
        (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
        for row in rows
    )
    _atomic_write_bytes(path, payload)


def extraction_input_fingerprint(out_dir: Path) -> str:
    """Bind partial generations to the exact parsed document consumed by extraction."""
    path = Path(out_dir).expanduser().resolve() / "blocks.jsonl"
    digest = hashlib.sha256()
    if not path.exists() or not path.is_file():
        return ""
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def no_ledger_baseline_lineage(
    *,
    input_fingerprint: str,
    route_mode: str,
    config: LLMClientConfig | None,
    unit_mode: str,
    concurrency: int,
    merge_chars: int,
    limit_sections: int | None,
    sample_ratio: float | None,
    scope: str,
    self_check: bool,
    self_check_rounds: int,
    verify_enabled: bool,
    verify_rounds: int,
) -> dict[str, Any]:
    """Build a key-free lineage binding for the no-ledger extraction denominator."""
    context = {
        "input_fingerprint": str(input_fingerprint),
        "route_mode": str(route_mode),
        "unit_mode": str(unit_mode),
        "concurrency": int(concurrency),
        "merge_chars": int(merge_chars),
        "limit_sections": int(limit_sections) if limit_sections is not None else None,
        "sample_ratio": float(sample_ratio) if sample_ratio is not None else None,
        "scope": str(scope),
        "self_check": bool(self_check),
        "self_check_rounds": int(self_check_rounds),
        "verify_enabled": bool(verify_enabled),
        "verify_rounds": int(verify_rounds),
    }
    config_payload = None if config is None else {
        "base_url": str(config.base_url).rstrip("/"),
        "model": str(config.model),
        "api_key_env": str(config.api_key_env),
        "temperature": float(config.temperature),
        "max_tokens": int(config.max_tokens),
        "timeout_s": float(config.timeout_s),
        "max_retries": int(config.max_retries),
    }
    json_mode_raw = os.environ.get("RATOMIZER_LLM_JSON_SCHEMA", "").strip().lower()
    json_mode_enabled = not json_mode_raw or json_mode_raw in {"1", "true", "yes", "on"}
    payload = {
        "version": NO_LEDGER_BASELINE_LINEAGE_VERSION,
        "context": context,
        "llm_config": config_payload,
        "json_mode_enabled": json_mode_enabled,
        "attempt_policy": llm_attempt_policy(),
        "versions": {
            "extract_prompt": AI_EXTRACT_PROMPT_VERSION,
            "extract_guards": EXTRACT_GUARDS_VERSION,
            "verify_prompt": AI_VERIFY_PROMPT_VERSION,
            "normative_framing": AI_NORMATIVE_FRAMING_VERSION,
        },
    }
    digest = hashlib.sha256(json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return {
        "lineage_version": NO_LEDGER_BASELINE_LINEAGE_VERSION,
        "lineage_fingerprint": f"sha256:{digest}",
        "lineage_context": context,
    }


def no_ledger_baseline_lineage_matches(
    baseline_cost: dict[str, Any],
    *,
    config: LLMClientConfig | None,
) -> bool:
    """Recompute saved baseline lineage under the current effective route config."""
    context = baseline_cost.get("lineage_context")
    expected_keys = {
        "input_fingerprint", "route_mode", "unit_mode", "concurrency", "merge_chars",
        "limit_sections", "sample_ratio", "scope", "self_check",
        "self_check_rounds", "verify_enabled", "verify_rounds",
    }
    if not isinstance(context, dict) or set(context) != expected_keys:
        return False
    if (
        context.get("route_mode") not in {"llm", "stub"}
        or context.get("unit_mode") not in {"clause", "chapter"}
        or context.get("scope") not in {"full", "sample"}
        or not isinstance(context.get("input_fingerprint"), str)
        or not context.get("input_fingerprint")
        or not isinstance(context.get("merge_chars"), int)
        or isinstance(context.get("merge_chars"), bool)
        or context["merge_chars"] <= 0
        or not isinstance(context.get("concurrency"), int)
        or isinstance(context.get("concurrency"), bool)
        or not 1 <= context["concurrency"] <= MAX_CONCURRENCY
        or context.get("limit_sections") is not None
        and (
            not isinstance(context.get("limit_sections"), int)
            or isinstance(context.get("limit_sections"), bool)
            or context["limit_sections"] <= 0
        )
        or context.get("sample_ratio") is not None
        and (
            not isinstance(context.get("sample_ratio"), (int, float))
            or isinstance(context.get("sample_ratio"), bool)
            or not 0 < float(context["sample_ratio"]) <= 1
        )
        or not isinstance(context.get("self_check"), bool)
        or not isinstance(context.get("verify_enabled"), bool)
        or not isinstance(context.get("self_check_rounds"), int)
        or isinstance(context.get("self_check_rounds"), bool)
        or context["self_check_rounds"] < 0
        or not isinstance(context.get("verify_rounds"), int)
        or isinstance(context.get("verify_rounds"), bool)
        or context["verify_rounds"] < 0
    ):
        return False
    candidate = no_ledger_baseline_lineage(
        input_fingerprint=context["input_fingerprint"],
        route_mode=context["route_mode"],
        config=config,
        unit_mode=context["unit_mode"],
        concurrency=context["concurrency"],
        merge_chars=context["merge_chars"],
        limit_sections=context["limit_sections"],
        sample_ratio=context["sample_ratio"],
        scope=context["scope"],
        self_check=context["self_check"],
        self_check_rounds=context["self_check_rounds"],
        verify_enabled=context["verify_enabled"],
        verify_rounds=context["verify_rounds"],
    )
    return (
        baseline_cost.get("lineage_version") == candidate["lineage_version"]
        and baseline_cost.get("lineage_fingerprint") == candidate["lineage_fingerprint"]
        and context == candidate["lineage_context"]
    )


def section_cache_versions() -> dict[str, str]:
    """Versions that change the paid per-section cache payload itself.

    Normative framing and merged consistency run after cached rows are loaded, so
    their versions belong to publication lineage but not this paid cache key. The
    verify prompt is already included in ``context_key`` only when verification is
    enabled; keeping it out here avoids invalidating verify-off caches.
    """
    from compliance import COMPLIANCE_SCHEMA

    return {
        "extract_prompt_version": AI_EXTRACT_PROMPT_VERSION,
        "extract_guards_version": EXTRACT_GUARDS_VERSION,
        "compliance_schema": COMPLIANCE_SCHEMA,
        "table_structure_version": table_structure.TABLE_STRUCTURE_VERSION,
    }


def producer_lineage_versions() -> dict[str, str]:
    """Complete version vector for published ai-extract artifacts."""
    from compliance import COMPLIANCE_SCHEMA
    from merged_consistency import MERGED_CONSISTENCY_VERSION

    return {
        "extract_prompt_version": AI_EXTRACT_PROMPT_VERSION,
        "extract_guards_version": EXTRACT_GUARDS_VERSION,
        "verify_prompt_version": AI_VERIFY_PROMPT_VERSION,
        "normative_framing_version": AI_NORMATIVE_FRAMING_VERSION,
        "merged_consistency_version": MERGED_CONSISTENCY_VERSION,
        "compliance_schema": COMPLIANCE_SCHEMA,
    }


def deterministic_extraction_versions() -> dict[str, str]:
    """Backward-compatible name for the complete producer lineage vector."""
    return producer_lineage_versions()


def current_ai_requirements_producer_lineage() -> dict[str, str]:
    """Return the code lineage that defines the published B-track target text."""
    return {
        "schema": AI_REQUIREMENTS_PRODUCER_LINEAGE_VERSION,
        "producer": "ai_extract",
        **producer_lineage_versions(),
    }


def ai_requirements_producer_is_current(out_dir: Path) -> bool:
    """Return whether the complete published target was built by the current producer."""
    path = Path(out_dir).expanduser().resolve() / AI_REQUIREMENTS_META
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(metadata, dict)
        and metadata.get("schema") == "ai-requirements-final/v1"
        and metadata.get("producer_lineage") == current_ai_requirements_producer_lineage()
    )


def write_ai_requirements_metadata(
    out_dir: Path,
    *,
    input_fingerprint: str = "",
    run_id: str = "",
    failed_sections: int = 0,
    failed_section_ids: list[str] | None = None,
    failed_section_block_ids: list[str] | None = None,
    no_ledger_baseline_cost: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind the published final JSONL to the parsed document generation it consumed."""
    root = Path(out_dir).expanduser().resolve()
    from claim_artifacts import file_sha256

    requirements_path = root / AI_REQUIREMENTS
    requirements_sha256 = (
        file_sha256(requirements_path) if requirements_path.is_file() else None
    )
    payload = {
        "schema": "ai-requirements-final/v1",
        "producer_lineage": current_ai_requirements_producer_lineage(),
        "input_fingerprint": str(input_fingerprint or extraction_input_fingerprint(root)),
        "run_id": str(run_id or ""),
        "selected_snapshot": "final",
        "requirements_sha256": requirements_sha256,
        "failed_sections": int(failed_sections),
        "failed_section_ids": list(failed_section_ids or []),
        "failed_section_block_ids": list(failed_section_block_ids or []),
        "no_ledger_baseline_cost": {
            "call_count": max(0, int((no_ledger_baseline_cost or {}).get("call_count") or 0)),
            "failed_call_count": max(
                0, int((no_ledger_baseline_cost or {}).get("failed_call_count") or 0)
            ),
            "total_tokens": max(0, int((no_ledger_baseline_cost or {}).get("total_tokens") or 0)),
            "usage_complete": (no_ledger_baseline_cost or {}).get("usage_complete") is True,
            "lineage_version": str(
                (no_ledger_baseline_cost or {}).get("lineage_version") or ""
            ),
            "lineage_fingerprint": str(
                (no_ledger_baseline_cost or {}).get("lineage_fingerprint") or ""
            ),
            "lineage_context": dict(
                (no_ledger_baseline_cost or {}).get("lineage_context") or {}
            ),
            "lineage_match": (no_ledger_baseline_cost or {}).get("lineage_match") is True,
        },
    }
    _atomic_write_bytes(
        root / AI_REQUIREMENTS_META,
        (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"),
    )
    return payload


def reusable_claim_groups_for_runtime(
    snapshot: dict[str, Any] | None,
    verifier_runtime: dict[str, Any],
) -> list[dict[str, Any]]:
    """Reuse terminal semantic decisions only under the identical verifier runtime."""
    if not _claim_runtime_matches(snapshot, verifier_runtime):
        return []
    return [dict(group) for group in ((snapshot or {}).get("groups") or [])
            if isinstance(group, dict)]


def _claim_runtime_matches(
    snapshot: dict[str, Any] | None,
    verifier_runtime: dict[str, Any],
) -> bool:
    current_fingerprint = str(verifier_runtime.get("fingerprint") or "")
    generation = dict((snapshot or {}).get("generation_meta") or {})
    shadow_meta = dict(generation.get("shadow_meta") or {})
    previous_runtime = dict(shadow_meta.get("verifier_runtime") or {})
    return bool(
        current_fingerprint
        and previous_runtime.get("fingerprint") == current_fingerprint
    )


def reusable_claim_negatives_for_runtime(
    snapshot: dict[str, Any] | None,
    verifier_runtime: dict[str, Any],
) -> list[dict[str, Any]]:
    """Reuse validated negative facts only when their full runtime is unchanged."""
    if not _claim_runtime_matches(snapshot, verifier_runtime):
        return []
    rows: list[dict[str, Any]] = []
    for ledger_row in (snapshot or {}).get("ledger") or []:
        negative = ledger_row.get("semantic_negative") if isinstance(ledger_row, dict) else None
        if isinstance(negative, dict) and negative.get("status") == "validated":
            rows.append(dict(negative))
    return rows


def refresh_claim_shadow(
    out_dir: Path,
    *,
    route: str | None,
    scope: str = "full",
    allow_llm: bool | None = None,
    verifier_max_calls: int | None = None,
    verifier_max_total_tokens: int | None = None,
    verifier_request_budget: LLMRequestBudget | None = None,
    resolved_route_config: LLMClientConfig | None = None,
    claim_mutation_attempt_id: str | None = None,
    shadow_built_hook: Any | None = None,
    extra_reusable_groups: list[dict[str, Any]] | None = None,
    extra_reusable_negatives: list[dict[str, Any]] | None = None,
    operation_lock_held: bool = False,
) -> dict[str, Any]:
    """Rebuild only claim artifacts from committed requirements; never call extraction LLMs."""
    from claim_artifacts import (
        CLAIM_SNAPSHOT_FILES,
        CLAIM_VERIFIER_ATTEMPTS,
        ClaimArtifactError,
        bootstrap_legacy_attempt_lineage,
        claim_verifier_attempt_scope,
        file_sha256,
        hash_json,
        load_committed_attempt_lineage,
        load_committed_shadow,
    )
    from claim_ledger import (
        b_track_authority_state,
        make_semantic_coverage_verifier,
        make_semantic_negative_proposer,
        make_semantic_negative_verifier,
        publish_b_track_shadow,
        semantic_verifier_runtime,
    )

    root = Path(out_dir).expanduser().resolve()
    requirements_path = root / AI_REQUIREMENTS
    requirements_meta_path = root / AI_REQUIREMENTS_META
    if not requirements_path.is_file() or not requirements_meta_path.is_file():
        raise FileNotFoundError("committed AI requirements and metadata are required")
    try:
        requirements_meta = json.loads(requirements_meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid AI requirements metadata") from exc
    if not isinstance(requirements_meta, dict):
        raise ValueError("invalid AI requirements metadata")
    expected_input = str(requirements_meta.get("input_fingerprint") or "")
    if not expected_input or expected_input != extraction_input_fingerprint(root):
        raise ValueError("AI requirements belong to a different parsed document")
    failed_sections = int(requirements_meta.get("failed_sections") or 0)
    failed_section_block_ids = [
        str(block_id)
        for block_id in (requirements_meta.get("failed_section_block_ids") or [])
        if str(block_id)
    ]
    baseline_cost = dict(requirements_meta.get("no_ledger_baseline_cost") or {})
    run_id = uuid.uuid4().hex
    from omission_actions import extraction_operation_lock

    operation_lock = (
        nullcontext()
        if operation_lock_held
        else extraction_operation_lock(root, operation="claim-shadow-refresh")
    )
    with operation_lock:
        try:
            previous_snapshot = load_committed_shadow(root)
        except Exception:
            previous_snapshot = None
        mutation_attempt_id = str(claim_mutation_attempt_id or "").strip()
        mutation_refresh = bool(mutation_attempt_id)
        committed_attempt_lineage: dict[str, Any] | None = None
        if mutation_refresh:
            if previous_snapshot is None:
                raise ClaimArtifactError(
                    "claim mutation refresh requires the previous committed shadow"
                )
            from claim_reextract_attempts import require_published_attempt

            current_requirements_hash = file_sha256(requirements_path)
            mutation = require_published_attempt(
                root,
                attempt_id=mutation_attempt_id,
                requirements_sha256=current_requirements_hash,
            )
            previous_generation = dict(previous_snapshot.get("generation_meta") or {})
            previous_requirements_hash = str(
                previous_generation.get("requirements_sha256") or ""
            )
            if not previous_requirements_hash:
                raise ClaimArtifactError(
                    "claim mutation refresh has no previous target provenance"
                )
            previous_publication_revision = hash_json(
                "claim-target-publication-revision/v1",
                {
                    "source_store": AI_REQUIREMENTS,
                    "source_present": True,
                    "source_file_sha256": previous_requirements_hash,
                },
            )
            started_preconditions = dict(
                dict(mutation.get("started") or {}).get("preconditions") or {}
            )
            if (
                started_preconditions.get("target_publication_revision")
                != previous_publication_revision
            ):
                raise ClaimArtifactError(
                    "claim mutation attempt is not based on the committed target"
                )
            current_publication_revision = hash_json(
                "claim-target-publication-revision/v1",
                {
                    "source_store": AI_REQUIREMENTS,
                    "source_present": True,
                    "source_file_sha256": current_requirements_hash,
                },
            )
            if (
                dict(mutation.get("publication") or {}).get(
                    "target_publication_revision"
                )
                != current_publication_revision
            ):
                raise ClaimArtifactError(
                    "claim mutation publication revision is invalid"
                )
        else:
            try:
                committed_attempt_lineage = load_committed_attempt_lineage(root)
            except ClaimArtifactError as lineage_error:
                try:
                    committed_attempt_lineage = bootstrap_legacy_attempt_lineage(root)
                except ClaimArtifactError:
                    raise lineage_error
        route_config = (
            resolved_route_config
            if allow_llm is not False and resolved_route_config is not None
            else config_for_route(route) if allow_llm is not False else None
        )
        baseline_context = baseline_cost.get("lineage_context")
        baseline_unit_mode = (
            str(baseline_context.get("unit_mode") or "")
            if isinstance(baseline_context, dict)
            else ""
        )
        baseline_config = route_config
        if baseline_config is not None:
            from llm_client import apply_min_tokens

            baseline_config = apply_min_tokens(
                baseline_config,
                "extract-chapter" if baseline_unit_mode == "chapter" else "extract",
            )
        lineage_match = (
            isinstance(baseline_context, dict)
            and baseline_context.get("input_fingerprint") == expected_input
            and no_ledger_baseline_lineage_matches(
                baseline_cost,
                config=baseline_config,
            )
        )
        baseline_cost["lineage_match"] = lineage_match
        if not lineage_match:
            baseline_cost["usage_complete"] = False

        config = route_config
        if config is not None:
            from llm_client import apply_min_tokens

            config = apply_min_tokens(config, "extract")
        verifier_requested = (
            config is not None and resolve_claim_shadow_verify(explicit=allow_llm)
        )
        verifier_budget = None
        if verifier_requested:
            if verifier_request_budget is not None:
                # Keep an exhausted externally-accounted budget attached so
                # checkpointed semantic decisions retain their original runtime
                # fingerprint. Any uncovered decision still fails at reserve()
                # before an HTTP request can escape the cumulative ceiling.
                verifier_budget = verifier_request_budget
            else:
                verifier_budget = claim_shadow_verifier_budget(
                    max_calls=verifier_max_calls,
                    max_total_tokens=verifier_max_total_tokens,
                )
        verifier_enabled = verifier_requested and verifier_budget is not None
        if verifier_requested and verifier_budget is None:
            LOGGER.warning(
                "claim shadow verifier requested but no positive call/token budget was authorized"
            )
        verifier_rounds = resolve_claim_shadow_verify_rounds()
        budget_snapshot = verifier_budget.snapshot() if verifier_budget is not None else {}
        verifier_runtime = semantic_verifier_runtime(
            route_mode="stub" if config is None else "llm",
            enabled=verifier_enabled,
            rounds=verifier_rounds,
            config=config,
            policy_source="environment",
            budget_policy_version=LLMRequestBudget.VERSION,
            max_calls=int(budget_snapshot.get("max_calls") or 0),
            max_total_tokens=int(budget_snapshot.get("max_tokens") or 0),
        )
        reusable_groups = (
            []
            if mutation_refresh
            else reusable_claim_groups_for_runtime(previous_snapshot, verifier_runtime)
        )
        if extra_reusable_groups:
            reusable_groups = [*reusable_groups, *extra_reusable_groups]
        reusable_negatives = (
            []
            if mutation_refresh
            else reusable_claim_negatives_for_runtime(previous_snapshot, verifier_runtime)
        )
        if extra_reusable_negatives:
            reusable_negatives = [
                *reusable_negatives, *extra_reusable_negatives,
            ]
        semantic_verifier = None
        semantic_negative_proposer = None
        semantic_negative_verifier = None
        if verifier_enabled:
            accounted_chat = lambda system, user: _chat_json_accounted(
                config,
                system,
                user,
                request_budget=verifier_budget,
            )
            semantic_verifier = make_semantic_coverage_verifier(
                accounted_chat,
                rounds=verifier_rounds,
            )
            semantic_negative_proposer = make_semantic_negative_proposer(accounted_chat)
            semantic_negative_verifier = make_semantic_negative_verifier(
                accounted_chat,
                rounds=verifier_rounds,
            )
        current_requirements = read_jsonl(requirements_path)
        from ai_review_actions import read_ai_review_states
        from claim_catalog import build_catalog_from_directory

        current_catalog = build_catalog_from_directory(root, scope=scope)
        target_state = b_track_authority_state(
            current_requirements,
            read_ai_review_states(root),
        )
        requirements_request_id = str(requirements_meta.get("run_id") or run_id)
        attempt_scope: dict[str, Any] = {
            "attempt_kind": "cold" if mutation_refresh else "ledger_only",
            "attempt_request_id": run_id,
            "requirements_request_id": requirements_request_id,
        }
        if not mutation_refresh:
            assert committed_attempt_lineage is not None
            previous_attempt = dict(
                committed_attempt_lineage.get("attempt_chain") or {}
            )
            reuse_generation_run_id = str(
                committed_attempt_lineage.get("generation_run_id") or ""
            )
            reuse_attempt_id = str(previous_attempt.get("attempt_id") or "")
            if not reuse_generation_run_id or not reuse_attempt_id:
                raise ValueError(
                    "committed verifier attempt lineage is required for refresh"
                )
            attempt_scope.update({
                "reuse_generation_run_id": reuse_generation_run_id,
                "reuse_attempt_id": reuse_attempt_id,
            })
        with claim_verifier_attempt_scope(
            root,
            failure_context={
                "catalog_build": current_catalog,
                "target_generation_id": target_state["target_generation_id"],
                "requirements_sha256": file_sha256(requirements_path),
                "verifier_runtime": verifier_runtime,
                "baseline_cost": baseline_cost,
                "verifier_budget": verifier_budget,
            },
            **attempt_scope,
        ):
            published = publish_b_track_shadow(
                root,
                run_id=run_id,
                route_mode="stub" if config is None else "llm",
                extraction_status="partial" if failed_sections else "success",
                catalog_build=current_catalog,
                requirements=current_requirements,
                scope=scope,
                controlled_term_aliases=load_controlled_term_aliases(root),
                failed_section_block_ids=failed_section_block_ids,
                semantic_verifier=semantic_verifier,
                semantic_negative_proposer=semantic_negative_proposer,
                semantic_negative_verifier=semantic_negative_verifier,
                reusable_groups=reusable_groups,
                reusable_negatives=reusable_negatives,
                baseline_cost=baseline_cost,
                verifier_runtime=verifier_runtime,
                verifier_budget=verifier_budget,
                on_shadow_built=shadow_built_hook,
            )
    shadow = dict(published.get("shadow") or {})
    shadow_meta = dict(shadow.get("meta") or {})
    effective_fold_error = ""
    try:
        from claim_review_actions import fold_effective_ledger

        fold_effective_ledger(
            root,
            actor_trigger="claim-shadow-refresh-publish",
        )
    except Exception as exc:
        effective_fold_error = f"{type(exc).__name__}: {exc}"[:300]
        LOGGER.warning(
            "claim shadow base published but effective fold lagged: %s",
            effective_fold_error,
        )
    try:
        if effective_fold_error:
            raise RuntimeError(effective_fold_error)
        from claim_views import build_claim_view

        effective_view = build_claim_view(root, "metrics")
        effective_metrics = dict(effective_view.get("effective_metrics") or {})
        effective_summary = {
            "document_ready": effective_view.get("document_ready"),
            "effective_fresh": bool(effective_view.get("effective_fresh")),
            "open_claim_count": effective_metrics.get("uncertain_count"),
        }
    except Exception as exc:
        effective_summary = {
            "document_ready": None,
            "effective_fresh": False,
            "open_claim_count": None,
            "effective_error": str(exc)[:300],
        }
    return {
        "kind": "claim_shadow_refresh",
        "route": "stub" if config is None else "openai_compatible",
        "run_id": run_id,
        "ledger_only": True,
        "failed_sections": failed_sections,
        "claim_shadow": {
            "status": "published",
            "accounting_status": shadow_meta.get("accounting_status"),
            "resolution_status": shadow_meta.get("resolution_status"),
            "metrics": shadow.get("metrics") or {},
            **effective_summary,
        },
        "verifier_budget": (
            verifier_budget.snapshot() if verifier_budget is not None else None
        ),
        "written": [
            name for name in (
                *CLAIM_SNAPSHOT_FILES,
                "claim_queue_proposals.jsonl",
                "claim_effective_health.json",
                CLAIM_VERIFIER_ATTEMPTS,
            )
            if (root / name).is_file()
        ],
    }


def write_compliance_requirements(
    out_dir: Path,
    requirements: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = build_compliance_payload(requirements)
    payload.update({
        "producer": AI_EXTRACT_PROMPT_VERSION,
        "source": AI_REQUIREMENTS,
        "input_fingerprint": extraction_input_fingerprint(out_dir),
    })
    _atomic_write_bytes(
        Path(out_dir).expanduser().resolve() / COMPLIANCE_REQUIREMENTS,
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return payload


def _supplement_uncovered_compliance(
    requirements: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """确定性合规兜底：LLM 未覆盖的合规块 → 补 draft 需求行（逐字引句 + 正则文号 +
    suspicion 标记）。补行进 ai_requirements.jsonl——suspicion 随澄清报告进必答清单,
    漏抽即入澄清而非静默漏（test3 实证 LLM 把 terse 证书句当行政文本跳过,召回 2/7）。"""
    from compliance import is_compliance_requirement, looks_like_compliance, resolve_source_backed_instrument
    from merged_consistency import coverage_gaps

    source_pool = [b for b in blocks if isinstance(b, dict)]
    compliance_blocks = [b for b in source_pool if looks_like_compliance(b.get("text"))]
    if not compliance_blocks:
        return requirements
    compliance_reqs = [r for r in requirements if is_compliance_requirement(r)]
    gaps = coverage_gaps(compliance_reqs, compliance_blocks, source_blocks=source_pool)
    uncovered_ids = set(gaps.get("uncovered_block_ids") or [])
    if not uncovered_ids:
        return requirements

    block_map = {str(b.get("block_id") or ""): b for b in compliance_blocks}
    supplemented = list(requirements)
    for block_id in sorted(uncovered_ids):
        block = block_map.get(block_id)
        if block is None:
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        instrument, _note = resolve_source_backed_instrument("", text)
        section_path = [str(s) for s in (block.get("section_path") or []) if str(s).strip()]
        supplemented.append({
            "ai_req_id": f"COMP-DET-{block_id}",
            "title": text[:120],
            "description": text,
            "type": "compliance",
            "priority": "P1",
            "status": "draft",
            "labels": ["测试合规"],
            "compliance_instrument": instrument,
            "compliance_obligations": [{"text": text}],
            "source_section": section_path[-1] if section_path else "",
            "source_quote": text,
            "source_block_ids": [block_id],
            "source_mapping": "deterministic_fallback",
            "suspicion_reasons": ["确定性合规兜底（LLM 未覆盖）"],
            "notes": "合规交付义务由确定性规则检出（LLM 未覆盖），引句逐字来自原文，请人工审核后确认",
        })
    LOGGER.info("合规兜底：补入 %d 条 LLM 未覆盖的合规交付义务", len(supplemented) - len(requirements))
    return supplemented


# --- 确定性参数表行展开（2026-07-27 STO 实证：143 行参数表 LLM 只合并出 31 条）---------
# 用户裁定：参数表每行都是一条需求。行是结构化的（编号+名称+要求列），逐行展开不需要
# LLM——确定性生成,引句逐字来自扁平渲染行,结构化字段不猜。

_PARAM_REQ_CELL_RE = table_structure.PARAM_REQ_CELL_RE
_PARAM_DEF_CELL_RE = table_structure.PARAM_DEF_CELL_RE
_PARAM_SECTION_RE = table_structure.PARAM_SECTION_RE
_PARAM_INDEX_CELL_RE = table_structure.PARAM_INDEX_CELL_RE
_PARAM_ROW_MIN_CELLS = 2
PARAM_ROW_EXPANSION_VERSION = "param-row-expand-v3"  # v3:删≥3数据行硬门(行数只作置信证据)+权威row/cell ID去重键+merge anchor分组标题;v2:英文表头扩展+classify_table_kind;v1:参数表行确定性展开首版


def _is_parameter_table(block: dict[str, Any]) -> bool:
    """需求型参数表判定（保守,宁漏勿错）。

    param-row-expand-v3 起删除 ≥3 数据行硬门：行数只是分类置信证据，行数不足的
    规范性内容由 cell 层闭环，不得静默丢失。判据委托 table_structure（有表头、
    非术语/定义表、含要求类列、章节不在术语/参考文献区）。"""
    table_kind = str(block.get("table_kind") or "")
    if table_kind:
        return table_kind == "parameter"
    return table_structure.is_parameter_table(
        [str(h or "") for h in (block.get("headers") or [])],
        [list(row) for row in (block.get("data_rows") or [])],
        [str(s) for s in (block.get("section_path") or [])],
    )


def classify_table_kind(block: dict[str, Any]) -> str:
    """表型分类（行级化底座）——判定集中在 table_structure，此处只做块字段适配。

    返回 'parameter' | 'mapping_matrix' | 'prose_grid' | 'other'。
    v2 结构块直接读 atomize 期算好的 table_kind（含合并证据）；旧块现场分类。
    """
    table_kind = str(block.get("table_kind") or "")
    if table_kind in table_structure.TABLE_KINDS:
        return table_kind
    return table_structure.classify_table_kind(
        [str(h or "") for h in (block.get("headers") or [])],
        [list(row) for row in (block.get("data_rows") or [])],
        [str(s) for s in (block.get("section_path") or [])],
    )


def _row_render_line(headers: list[str], row: list[Any]) -> str:
    """与 render_table_text 完全同款的行渲染——引句逐字锚定块扁平文本的前提。"""
    cells = [str(cell or "") for cell in row]
    padded = cells + [""] * max(0, len(headers) - len(cells))
    return " | ".join(padded[: len(headers)])


def _row_name_cell(headers: list[str], row: list[Any]) -> str:
    seen: set[str] = set()
    for header, cell in zip(headers, row):
        text = str(cell or "").strip()
        if not text or _PARAM_INDEX_CELL_RE.match(text) or text in seen:
            continue
        seen.add(text)
        if _PARAM_REQ_CELL_RE.search(str(header)):
            continue
        return text
    for cell in row:
        text = str(cell or "").strip()
        if text and not _PARAM_INDEX_CELL_RE.match(text):
            return text
    return ""


def _supplement_parameter_table_rows(
    requirements: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """确定性参数表行展开：需求型参数表的每个未被 LLM 覆盖的数据行 → 一条 draft 需求
    （逐字引句 + suspicion 标记进澄清）。已覆盖的行不重复补（compact 文本在引用该块的
    任一需求的引句/描述中命中即视为已覆盖）。"""
    from merged_consistency import compact_source_text

    table_blocks = [
        b for b in blocks
        if isinstance(b, dict) and str(b.get("type") or "") == "table" and _is_parameter_table(b)
    ]
    if not table_blocks:
        return requirements

    covered_by_block: dict[str, str] = {}
    for req in requirements:
        haystack = compact_source_text(
            f"{req.get('source_quote') or ''} {req.get('description') or ''} {req.get('title') or ''}"
        )
        for block_id in req.get("source_block_ids") or []:
            covered_by_block[str(block_id)] = covered_by_block.get(str(block_id), "") + " " + haystack

    supplemented = list(requirements)
    added = 0
    for block in sorted(table_blocks, key=lambda b: str(b.get("block_id") or "")):
        block_id = str(block.get("block_id") or "")
        headers = [str(h or "") for h in (block.get("headers") or [])]
        data_rows = block.get("data_rows") or []
        covered_text = covered_by_block.get(block_id, "")
        section_path = [str(s) for s in (block.get("section_path") or []) if str(s).strip()]
        table_id = str(block.get("table_id") or block_id)
        # 权威行号 = 表头数 + 标题数 + 数据区偏移（与 table_items.jsonl 的 item_id 对齐；
        # 缺 header_row_count 的旧夹具按"有表头即 1"回退，与 catalog 遗留口径一致）
        header_row_count = int(
            block.get("header_row_count")
            if block.get("header_row_count") is not None
            else (1 if block.get("headers") else 0)
        )
        header_offset = header_row_count + len(block.get("title_row_indexes") or [])
        merge_ranges = table_structure.normalize_merge_ranges(block.get("merge_ranges") or [])
        width = int(block.get("columns") or 0)
        for row_index, row in enumerate(data_rows, start=1):
            physical_row = header_offset + row_index
            cells = [str(cell or "").strip() for cell in row]
            non_empty = [cell for cell in cells if cell]
            if not non_empty:
                continue
            # 分组标题行：全宽合并 anchor + 所有非空单元格同值 + 非规范性（STO 实证
            # "3. TECHNICAL REQUIREMENTS"×6 列）——是章节标题不是需求行,跳过；
            # 无合并证据时退回历史同值启发式
            if table_structure.is_group_header_row(
                cells, physical_row, width=width, merge_ranges=merge_ranges or None
            ):
                continue
            if len(non_empty) < _PARAM_ROW_MIN_CELLS and not any(
                table_structure.is_normative_text(cell) for cell in non_empty
            ):
                # 单格行只要包含规范性内容就必须保留（不受"至少两个非空格"限制）
                continue
            quote = _row_render_line(headers, row)
            if not quote.strip():
                continue
            # 覆盖判定：行内最长实质单元格（≥16 字符防"230 V"类短词假命中）的 compact
            # 文本已在引用本块的任一需求文本中出现 → 该行已被 LLM 覆盖,不重复补;
            # 判不出来的行宁补勿漏（补行带 suspicion 进澄清,重复可在审核时剔除）
            substantive = sorted(
                (compact_source_text(cell) for cell in non_empty),
                key=len,
                reverse=True,
            )
            key_cell = next((cell for cell in substantive if len(cell) >= 16), "")
            if key_cell and key_cell in covered_text:
                continue
            name = _row_name_cell(headers, row)
            title = name[:120] if name else quote[:120]
            supplemented.append({
                "ai_req_id": f"PROW-DET-{block_id}-R{row_index:04d}",
                "title": title,
                "description": quote,
                "type": "functional",
                "priority": "P1",
                "status": "draft",
                "labels": ["参数表"],
                "source_section": section_path[-1] if section_path else "",
                "source_quote": quote,
                "source_block_ids": [block_id],
                # 权威 row ID（param-row-expand-v3 去重键）
                "source_item_id": f"{table_id}-R{physical_row:06d}",
                "source_row_index": physical_row,
                "source_mapping": "deterministic_fallback",
                "suspicion_reasons": ["参数表行确定性展开"],
                "notes": "参数表行由确定性规则逐行展开（用户裁定：参数表每行都是需求），引句逐字来自原文表格渲染行，请人工审核后确认",
            })
            added += 1
    if added:
        LOGGER.info("参数表行展开：补入 %d 条 LLM 未逐行覆盖的参数行需求", added)
    return supplemented


def _assert_source_references(
    requirements: list[dict[str, Any]],
    table_items: list[dict[str, Any]],
    table_cell_items: list[dict[str, Any]],
) -> None:
    """发布前断言：每个 source_item_id/source_cell_id 都真实存在（权威 row/cell ID）。

    引用表缺失或引用悬空都是旧产物/伪造迁移信号——大声失败，要求重跑 atomize，
    绝不带着悬空溯源发布。"""
    item_ids = {str(item.get("item_id") or "") for item in table_items}
    cell_ids = {str(cell.get("cell_id") or "") for cell in table_cell_items}
    dangling_items = sorted({
        str(req.get("source_item_id"))
        for req in requirements
        if str(req.get("source_item_id") or "").startswith("TBL-")
        and str(req.get("source_item_id")) not in item_ids
    })
    dangling_cells = sorted({
        str(req.get("source_cell_id"))
        for req in requirements
        if str(req.get("source_cell_id") or "").startswith("TBL-")
        and str(req.get("source_cell_id")) not in cell_ids
    })
    if dangling_items or dangling_cells:
        raise ValueError(
            "source reference assertion failed "
            f"(dangling source_item_id={dangling_items[:5]} "
            f"source_cell_id={dangling_cells[:5]}): "
            "base_migration_required——请重跑 atomize 再执行 ai-extract"
        )


def _merge_llm_into_deterministic_rows(
    requirements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """封堵二:参数表 LLM 叙述需求并入同行确定性展开行(PROW-DET),避免同行双份。

    Phase 2 行级化后,LLM 逐行抽叙述需求与 _supplement_parameter_table_rows 确定性逐字行
    可能同行并存(LLM 措辞不含行 key_cell → supplement 未判覆盖 → 补了 PROW-DET)。本步把
    命中同一渲染行的 LLM 需求叙述并入对应 PROW-DET 的 llm_narrative(无则丢弃),merge_trace
    记审计;未命中任何 PROW-DET 的 LLM 需求正常成行。宁漏勿错——判不出的双份保留(审核时
    剔除),不强行并入。新增可选字段 llm_narrative(str)/merge_trace(list[dict]) 向后兼容。"""
    prow_by_block: dict[str, list[dict[str, Any]]] = {}
    for req in requirements:
        if not str(req.get("ai_req_id") or "").startswith("PROW-DET-"):
            continue
        for bid in req.get("source_block_ids") or []:
            prow_by_block.setdefault(str(bid), []).append(req)
    if not prow_by_block:
        return requirements

    kept: list[dict[str, Any]] = []
    merged_count = 0
    for req in requirements:
        if str(req.get("ai_req_id") or "").startswith("PROW-DET-"):
            kept.append(req)
            continue
        target_prow = _llm_row_target(req, prow_by_block)
        if target_prow is None:
            kept.append(req)
            continue
        narrative = str(req.get("description") or req.get("source_quote") or "").strip()
        if narrative:
            existing = str(target_prow.get("llm_narrative") or "")
            target_prow["llm_narrative"] = (existing + "\n" if existing else "") + narrative
        target_prow.setdefault("merge_trace", []).append({
            "llm_requirement_id": str(req.get("ai_req_id") or ""),
            "merged_into": str(target_prow.get("ai_req_id") or ""),
            "reason": "row_overlap",
        })
        merged_count += 1
    if merged_count:
        LOGGER.info("参数表去重:并入 %d 条同行 LLM 叙述需求到确定性展开行", merged_count)
    return kept


def _llm_row_target(
    req: dict[str, Any],
    prow_by_block: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    """LLM 需求命中某 PROW-DET 行则返回该 PROW-DET,否则 None。

    判等(沿用 guards-v16 key_cell 口径 + 边界补充2 短行回退):
    - 行渲染 compact(≥12 字符)出现在 LLM 文本(source_quote+description+title) → 命中;
    - 短行回退:行渲染 compact == LLM 引句 compact(精确相等,覆盖纯数值短行)。"""
    from merged_consistency import compact_source_text

    haystack = compact_source_text(
        f"{req.get('source_quote') or ''} {req.get('description') or ''} {req.get('title') or ''}"
    )
    quote = compact_source_text(req.get("source_quote"))
    if not haystack:
        return None
    for bid in req.get("source_block_ids") or []:
        for prow_req in prow_by_block.get(str(bid), []):
            # param-row-expand-v3：权威 row/cell ID 是第一去重键（结构一致即同行），
            # 文本匹配只作无 ID 旧路径的回退
            req_item_id = str(req.get("source_item_id") or "")
            prow_item_id = str(prow_req.get("source_item_id") or "")
            if req_item_id and prow_item_id:
                if req_item_id == prow_item_id:
                    return prow_req
                continue
            row_line = compact_source_text(prow_req.get("source_quote"))
            if not row_line:
                continue
            if len(row_line) >= 12 and row_line in haystack:
                return prow_req
            if quote and row_line == quote:
                return prow_req
    return None


def _coverage_quality_fields(
    requirements: list[dict[str, Any]],
    blocks: Any,
    *,
    allowed_block_ids: set[str] | None = None,
    expert_excluded_block_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Build quality counters from the same coverage engine used by consistency/export."""
    from merged_consistency import coverage_denominator_blocks, layered_coverage

    source_blocks = [block for block in blocks if isinstance(block, dict)]
    denominator = [
        block for block in coverage_denominator_blocks(source_blocks)
        if clean_block_text(block)
        and (
            allowed_block_ids is None
            or str(block.get("block_id") or "") in allowed_block_ids
        )
    ]
    coverage = layered_coverage(
        requirements,
        denominator,
        source_blocks=source_blocks,
        allowed_block_ids=allowed_block_ids,
        expert_excluded_block_ids=expert_excluded_block_ids,
    )
    total = int(coverage.get("requirement_like") or 0)
    covered = int(coverage.get("covered") or 0)
    compliance = coverage.get("compliance") or {}
    excluded = coverage.get("excluded") or {}
    compliance_total = int(compliance.get("requirement_like") or 0)
    compliance_covered = int(compliance.get("covered") or 0)
    return {
        "requirement_like_blocks": total,
        "covered_blocks": covered,
        "coverage_pct": round(covered * 100 / total, 1) if total else None,
        "coverage_scope": "core",
        "core_requirement_like_blocks": total,
        "core_covered_blocks": covered,
        "core_uncovered_blocks": int(coverage.get("uncovered_count") or 0),
        "core_coverage_pct": round(covered * 100 / total, 1) if total else None,
        "compliance_requirement_like_blocks": compliance_total,
        "compliance_covered_blocks": compliance_covered,
        "compliance_uncovered_blocks": int(compliance.get("uncovered_count") or 0),
        "compliance_coverage_pct": (
            round(compliance_covered * 100 / compliance_total, 1)
            if compliance_total else None
        ),
        "excluded_requirement_like_blocks": int(excluded.get("count") or 0),
    }


def _current_non_requirement_ids(out_dir: Path) -> set[str]:
    from omission_actions import current_non_requirement_block_ids

    return current_non_requirement_block_ids(Path(out_dir))


def refresh_ai_extract_quality(
    out_dir: Path,
    requirements: list[dict[str, Any]],
) -> dict[str, Any]:
    """Recompute requirement-derived quality fields after a targeted supplement."""
    root = Path(out_dir).expanduser().resolve()
    quality_path = root / "ai_extract_quality.json"
    try:
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        quality = {}
    if not isinstance(quality, dict):
        quality = {}

    blocks = body_blocks(read_jsonl(root / "blocks.jsonl"))
    coverage_fields = _coverage_quality_fields(
        requirements,
        blocks,
        expert_excluded_block_ids=_current_non_requirement_ids(root),
    )
    by_module: dict[str, int] = {}
    for row in requirements:
        module = str((row.get("labels") or ["未分模块"])[0])
        by_module[module] = by_module.get(module, 0) + 1
    quality.update({
        "requirements": len(requirements),
        "self_check_added": sum(1 for row in requirements if row.get("self_check_added")),
        "code_drift_flagged": sum(
            1 for row in requirements if "结构漂移已拦截" in str(row.get("notes") or "")
        ),
        "int_drift_flagged": sum(
            1 for row in requirements if "数字漂移" in str(row.get("notes") or "")
        ),
        "by_module": dict(sorted(by_module.items(), key=lambda item: -item[1])),
        **coverage_fields,
    })
    from requirement_record import provenance

    quality["provenance"] = provenance("ai_extract", AI_EXTRACT_PROMPT_VERSION)
    _atomic_write_bytes(
        quality_path,
        (json.dumps(quality, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return quality


def write_partial_snapshot(
    path: Path,
    *,
    run_id: str,
    completed: int,
    total: int,
    complete: bool,
    rows: list[dict[str, Any]],
    input_fingerprint: str = "",
    failed: bool = False,
    error: str = "",
) -> dict[str, Any]:
    payload = {
        "schema": AI_PARTIAL_SCHEMA,
        "run_id": str(run_id),
        "completed": int(completed),
        "total": int(total),
        "complete": bool(complete),
        "failed": bool(failed),
        "input_fingerprint": str(input_fingerprint or ""),
        "rows": rows,
    }
    if error:
        payload["error"] = str(error)[:500]
    _atomic_write_bytes(
        path,
        (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"),
    )
    return payload


def read_partial_snapshot(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != AI_PARTIAL_SCHEMA:
        return None
    if not isinstance(payload.get("rows"), list) or not payload.get("run_id"):
        return None
    return payload


def resolve_concurrency(explicit: int | None = None) -> int:
    """并发度：显式参数优先，其次环境变量 RATOMIZER_LLM_CONCURRENCY（GUI 设置面板写入），否则默认。夹在 1..MAX。"""
    raw: Any = explicit if explicit is not None else os.environ.get(CONCURRENCY_ENV)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_CONCURRENCY
    return max(1, min(MAX_CONCURRENCY, value))


def resolve_self_check(explicit: bool | None = None) -> bool:
    """完整性自检开关：显式参数优先，否则环境变量 RATOMIZER_AI_SELFCHECK。

    默认开；仅显式的 0/false/no/off 关。未设或空字符串一律回落默认（空串≠关闭）。
    """
    if explicit is not None:
        return bool(explicit)
    raw = os.environ.get(SELF_CHECK_ENV, "").strip().lower()
    if not raw:
        return True
    return raw not in ("0", "false", "no", "off")


def resolve_self_check_rounds(explicit: int | None = None) -> int:
    """自检收敛轮数上限：显式参数优先，其次环境变量 RATOMIZER_AI_SELFCHECK_ROUNDS，否则默认 3。

    夹在 1..MAX_SELF_CHECK_ROUNDS。收敛循环通常 1-2 轮就 dry（零新增）提前停，上限只是防发散兜底。
    """
    raw: Any = explicit if explicit is not None else os.environ.get(SELF_CHECK_ROUNDS_ENV)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_SELF_CHECK_MAX_ROUNDS
    return max(1, min(MAX_SELF_CHECK_ROUNDS, value))


VERIFY_ENV = "RATOMIZER_AI_VERIFY"  # 二遍语义复核开关（默认开；=0/false/off 关）
VERIFY_ROUNDS_ENV = "RATOMIZER_AI_VERIFY_ROUNDS"  # 复核投票轮数（默认 2,1..4）
AI_VERIFY_PROMPT_VERSION = "ai-verify-v4"
DEFAULT_VERIFY_ROUNDS = 2
MAX_VERIFY_ROUNDS = 4


def resolve_verify_enabled(explicit: bool | None = None) -> bool:
    """二遍语义复核开关：显式参数优先，否则 env RATOMIZER_AI_VERIFY;默认开。"""
    if explicit is not None:
        return bool(explicit)
    raw = os.environ.get(VERIFY_ENV, "").strip().lower()
    if not raw:
        return True
    return raw not in ("0", "false", "no", "off")


def resolve_verify_rounds(explicit: int | None = None) -> int:
    """复核投票轮数:单轮对细微语义错误命中率实测仅 ~1/3(温度方向探针 1/3,
    单条聚焦同样 1/3——是模型判断随机性不是注意力稀释),N 轮取并集是机制性
    提召回手段(2 轮≈55%、3 轮≈70%)。锚定采纳门不随轮数放宽,精度不掉。"""
    raw: Any = explicit if explicit is not None else os.environ.get(VERIFY_ROUNDS_ENV)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_VERIFY_ROUNDS
    return max(1, min(MAX_VERIFY_ROUNDS, value))

VALID_TYPES = {"functional", "non_functional", "constraint", "business_rule", COMPLIANCE_TYPE}
VALID_PRIORITIES = {"P0", "P1", "P2"}

SYSTEM_PROMPT = (
    "你是表计行业（电表/水表/气表）需求分析师。读给定的标准/规范文本，抽取其中的需求条目。"
    "把同一功能的零散语句**合并成一条功能需求**，不要逐句拆；表格类规范化为一条带说明的需求。"
    "每条需求输出：title（不超过 80 字）、"
    "functional_key（跨章节合并的连接键——构造规则：「对象/主题＋动作」的受控中文名词短语，"
    "2-6 个词，不含数值/编码/章节号/标点；跨章节属同一研发功能时必须**逐字相同**。"
    "正例：「阀门关闭控制」「远程固件升级」「事件记录存储」；反例：「4.6 的设备要求」（带章节号）、「阀门在 5s 内关闭」（带数值））、"
    "description（自包含中文叙述：背景+具体要求+适用条件+参数）、"
    "type（functional/non_functional/constraint/business_rule/compliance）；证书、法令、法规、"
    "初始检定周期、符合性声明等交付/法定义务必须标 compliance，不得归入软件功能。"
    "compliance 条目可保留一个 umbrella 父条目并用 compliance_obligations/sub_items 列多项义务，"
    "不要为了凑数量强拆；compliance_instrument 必须逐字来自当前章节原文。"
    "技术性能、环境等级、通信或计量要求若只是引用标准/法规作为依据，仍按其技术实质标为"
    "functional/non_functional/constraint；不得仅因出现标准号、法规号就标 compliance。"
    "priority（判级基准：P0=安全/计量准确性/法规强制项；P1=核心功能与协议一致性；P2=辅助/诊断/可选功能。"
    "**资料性内容不升格**：informative 附录、标注 not a priority/optional/推荐 的内容最高只到 P2——"
    "『某项不适用』是排除声明,不得反写成禁止实现的需求）、"
    "module（该需求归属的模块，**必须原样照抄下面清单里的一个词**，按需求实质语义选最贴切的；"
    "确实都不贴切时才填\"" + OTHER_MODULE + "\"）：" + "、".join(MODULE_VOCAB) + "。"
    "labels（额外的细分标签，至少一个，可自由）、source_quote（原文逐字引用，不可改写）、"
    "source_section（该需求所属的章节号/标题，从文本里的小节标题判断）、"
    "acceptance_criteria（可测试的验收点数组）、"
    "sub_items（**可选**：条款枚举子项数组，每项 {\"label\": \"a\", \"text\": \"该子项的自包含中文要求\"}——"
    "原文以 a) b) c) 枚举多个要求时逐项填写，作为需求的二级结构）、"
    "dev_guidance（**规范直接支持的研发落地指引**数组：为满足本需求必须实现的功能/逻辑/接口，不复述原文）、"
    "design_options（**非规范约束的设计候选**数组：原文未指定但可供研发选型的队列/缓存/分层方案，不得给无依据容量或默认值）、"
    "threshold_table（**仅当原文含参数/门限/档位表**时输出 {\"columns\": [...], \"rows\": [[...]]}，"
    "数字逐格照抄原文，不重排不换算；原文无表格则省略此字段）。"
    "质量准则：description 必须自包含（研发不回原文即可实现：条件+动作+参数齐全）；"
    "acceptance_criteria 必须可测（有明确的通过/失败判据，避免\"符合要求\"这类空话）；"
    "一个需求点不拆散成多条，不同需求点不合并成一条。"
    "**产品义务主体**：对已经判定为产品能力需求的句子，description 必须以产品、设备或对应组件"
    "作为规范义务主体。原文使用被动能力句或角色能力表达（如 X can be configured by Y）时，"
    "规范化为“产品应支持/允许 Y 配置 X”，不得只写成“Y 可以配置 X”；必须完整保留角色、动作、"
    "对象、条件和原始约束强度，不得把具体对象泛化。"
    "每个 description 句子和 sub_items 叶子都必须能脱离相邻句独立读成正式需求；不得借前一句的"
    "产品主体，让后一个叶子只剩“可以/可由/可通过/能够”等描述性能力表达。"
    "示例：原文 \"The meter shall store at least 12 monthly billing records.\" → "
    "{\"title\": \"存储至少12个月的月结算记录\", "
    "\"description\": \"电表须在本地存储不少于12个月的月结算记录，供结算追溯读取。\", "
    "\"type\": \"non_functional\", \"priority\": \"P1\", \"module\": \"结算\", \"labels\": [\"数据存储\"], "
    "\"source_quote\": \"The meter shall store at least 12 monthly billing records.\", "
    "\"dev_guidance\": [\"实现月结算记录存储区，容量不少于12条，写满后新记录覆盖最旧记录\", "
    "\"提供按月份读取历史结算记录的访问接口\"], "
    "\"acceptance_criteria\": [\"连续产生12个月结算记录后，最早一个月的记录仍可完整读出\"]}。"
    "术语定义中的固定起止规则、允许取值、有效期范围、边界条件或枚举值也是约束/业务规则，"
    "不要仅因其位于 Terms and definitions 而忽略；例如 billing period 定义里 "
    "\"always begins ... ends ... can be valid for 1, 2, 3, 4, 6, 12 months\" "
    "应抽为结算周期约束，并保留 1, 2, 3, 4, 6, 12 months。"
    "若提供了【文档背景/章节大纲/术语定义】，据此保持术语一致、模块判断准确、解析跨章节引用；"
    "但这些背景仅供参考——需求内容与 source_quote 必须来自【当前章节】原文，不得从背景里搬运。"
    "严禁编造原文没有的 OBIS 码、事件号、十六进制、数字——这些只能原样引用或不出现。"
    "acceptance_criteria 和 dev_guidance 同样不得引入原文没有的容量、周期、协议编号或默认数值；"
    "若实现需要容量/保留期等设计参数，只写“由产品配置/相关条款确定、需澄清”，不得给默认建议值。"
    "**不要输出**：目录/标题行、参考文献条目、范围声明（This standard specifies/applies to…）、"
    "仅引用其他标准编号而无本设备行为要求的语句、"
    "测试装置/夹具/图例说明（仅描述试验器材构成与操作步骤、对设备本身无行为约束的内容——"
    "试验中体现的设备限值/合格判据要归入对应需求的验收，不单独成需求）——这些不是需求。"
    "**忠实性**：描述必须与引句同向——不得升格约束强度（should/宜/建议 ≠ 必须），"
    "不得反转方向或互换主客体，不得添加原文没有的适用条件或限定词；"
    "引用标准号只能照抄本章节原文里出现的，绝不凭印象归属。"
    "**免责/例外从句保向**：unless/without/except/provided that 这类从句表达的是例外或"
    "免责条件（如\"不得漂移超过 X——除非显示了错误标志\"意为超限时须报警才合规），"
    "绝不能改写成禁止项或独立义务（写成\"不得显示错误标志\"就是反向误读）。"
    "**量符号下标**：原文里 \"Q max\"\"Q min\"\"P max\" 这类拆开的写法是同一量符号的"
    "下标排版（Qmax/Qmin/Pmax），按一个符号理解，不得当作独立单词或把系数误读成倍率"
    "（\"0.25 Q max\" 是流量点 0.25·Qmax，不是\"额定流量的0.25倍\"这类另起炉灶的换算）。"
    "**单位/等级词不猜译**：grade、mesh、class 等粒度/等级/量纲词拿不准中文对应时，"
    "保留英文原词并括注说明，不得猜一个具体中文单位（把 \"300 to 400 grade dust\" 猜译成"
    "\"300-400目\"会让研发配错试验材料）。"
    "**条款族=一条需求**：输入单元若是条款族（如 X.Y 条款含 X.Y.1 Requirements 与 X.Y.2 Test 子节）："
    "以条款为单位产出**一条**需求——Requirements 的枚举项 a)b)c)d) 逐项写进 sub_items，"
    "对应的 Test 项按 a↔a、b↔b 对应写进 acceptance_criteria；**Test/测试方法不单独抽成需求**。"
    "**数值必须落地**：原文列出的数值清单（粒径/成分百分比/档位/限值/容差）必须**逐项完整**"
    "进入 threshold_table 或 description，绝不许用\"规定的范围\"\"指定成分\"这类指代替代——"
    "研发拿不到数值等于没写。若给出【被引用条款】，把其中的具体数值整合进描述（引用视为有据），"
    "不要只写\"见 X.X 节\"。"
    "只输出 JSON：{\"requirements\": [ {…}, … ]}。"
)


# --- 章节聚合与合并：见 extract_units（F3 拆分） ---------------------------




# --- 抽取与防幻觉护栏 -----------------------------------------------------

# 确定性后处理层(护栏/桩过滤/折叠)版本——缓存存的是**终处理结果**,指纹若只含
# prompt 版本,护栏升级会被旧缓存整体绕过(v5 实测:种子 v4 缓存 wall=0s 结果逐字节
# 相同,新护栏零生效)。护栏行为变更必须 bump 此值。
EXTRACT_GUARDS_VERSION = "guards-v19"  # v19:table-structure-v2 接入(删参数表≥3行硬门/merge anchor分组标题/权威row/cell ID去重键/cell级assemble输入+TABLE_STRUCTURE_VERSION与leaf plan结构hash进section指纹);v18:section cache 与完整 producer lineage 分层纳入 compliance_schema,堵死 v17 漏钉且避免缓存后处理版本触发付费重抽;v17:表型分类器 classify_table_kind + 参数表英文表头扩展(value/spec/min/max/limit/rating/nominal/tolerance/range/unit 等),进 section_fingerprint;v16:参数表行确定性展开(用户裁定:参数表每行皆需求,LLM 未覆盖行确定性补 draft 行);v15:噪声贯通抽取路径;v14:匹配各路径噪声块不成来源;v13:fallback 裸节号前缀;v12:引句多段窗口跳过噪声块;v11:section_fallback 按所属小节收窄;v10:引用三层分流;v9:合规 umbrella/instrument 只认确定性证据


def section_fingerprint(section: dict[str, Any], model: str, context_key: str = "") -> str:
    refs = (section.get("ref_texts") or []) + (section.get("term_defs") or [])
    refs_key = hashlib.sha256(json.dumps(refs, ensure_ascii=False).encode("utf-8")).hexdigest()[:12] if refs else ""
    drift_source = str(section.get("drift_source") or section.get("text") or "")
    drift_key = hashlib.sha256(drift_source.encode("utf-8")).hexdigest()[:16]
    version_key = "+".join(section_cache_versions().values())
    # leaf plan 结构 hash（guards-v19）：source_blocks 的权威 row/cell ID 骨架——
    # 结构路由（row/cell owner）变化即使文本不变也必须让缓存失效
    structure_skeleton = [
        {
            "block_id": str(sb.get("block_id") or ""),
            "rows": [str(row.get("item_id") or "") for row in (sb.get("rows") or [])],
            "cells": [str(cell.get("cell_id") or "") for cell in (sb.get("cells") or [])],
        }
        for sb in (section.get("source_blocks") or [])
        if isinstance(sb, dict) and (sb.get("rows") or sb.get("cells"))
    ]
    struct_key = (
        hashlib.sha256(
            json.dumps(structure_skeleton, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:12]
        if structure_skeleton
        else ""
    )
    digest = hashlib.sha256(
        f"{section.get('text', '')}\n{model}\n{version_key}"
        f"\n{context_key}\n{refs_key}\n{drift_key}\n{struct_key}".encode("utf-8")
    ).hexdigest()
    return digest[:24]


EXTRACT_EXEMPLARS_MAX = 8


def render_extract_exemplars(bank: dict[str, Any]) -> str:
    """裁决样本 → 抽取轨 few-shot（0714 批次三 E6）。

    此前裁决只反哺 analyze 富化,专家对**抽取粒度/模块判断**的验收从不回灌抽取——
    抽取质量不随使用积累。只用「模块+标题」（不携描述/数值,最小化搬运面）;
    每模块最多 2 条、总量 8 条（模块多样性优先）;按 rid 排序确定性可复现。
    """
    accepted = bank.get("accepted") or {}
    by_module: dict[str, list[str]] = {}
    for rid in sorted(accepted):
        entry = accepted.get(rid) or {}
        module = str(entry.get("module") or "").strip()
        title = str(entry.get("title") or "").strip()
        if not module or not title:
            continue
        titles = by_module.setdefault(module, [])
        if len(titles) < 2:
            titles.append(title[:60])
    lines: list[str] = []
    for module in sorted(by_module):
        for title in by_module[module]:
            lines.append(f"-【{module}】{title}")
            if len(lines) >= EXTRACT_EXEMPLARS_MAX:
                return "\n".join(lines)
    return "\n".join(lines)


def build_section_prompt(section: dict[str, Any]) -> str:
    payload = {"heading": section.get("heading"), "text": section.get("text", "")}
    base = json.dumps(payload, ensure_ascii=False, indent=2)
    refs = section.get("ref_texts") or []
    terms = section.get("term_defs") or []
    term_block = ""
    if terms:
        joined = "\n".join(f"- {t['term']}: {t['text']}" for t in terms)
        term_block = f"\n\n【本章节用到的术语定义（引用其内容视为有据）】\n{joined}"
    if not refs:
        return base + term_block
    ref_block = "\n\n".join(
        f"【被引用条款 {r['clause']}——本章节文字引用了它。请把其中的具体数值/限值整合进需求描述，"
        f"引用这些数值视为有据】\n{r['text']}" for r in refs)
    return f"{base}{term_block}\n\n{ref_block}"


# --- 跨章节引用解析 -------------------------------------------------------
# "the leak rate does not exceed the values given in 7.13.4.5.1"——限值正文在别的单元，
# 抽取时看不见 → 描述只能写"不得超过 7.13.4.5.1 规定的限值"（不自包含，研发还得回原文）。
# 检测内部条款引用，把被引条款的正文摘录注入 prompt（并入漂移基线：引用其数值=有据）。
# 条款/附录标题索引：数字条款（7.13.4.5.1）、附录节（A.1.4.6）、附录整章（Annex A）


# --- 中英术语对照（每文档一次 LLM，缓存复用） ------------------------------
# 交付物是中文：同一英文术语（pressure absorption 等）在上百条需求里译法漂移，研发读起来
# 像多份文档。对照表注入 doc_context（折进缓存指纹），全文统一译法。失败静默跳过（可选增强）。
TERM_MAP_FILE = "term_map.json"
TERM_MAP_MAX = 40
TERM_MAP_SCHEMA = "ai-term-map/v1"
_TERM_MAP_HASH_RE = re.compile(r"[0-9a-f]{16}")


def _canonical_term_alias(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def _term_map_basis(source_terms: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(source_terms, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]


def load_controlled_term_aliases(out_dir: Path) -> dict[str, list[str]]:
    """Load the source-to-target glossary already fixed before extraction.

    The prefilter must not invent translations. ``term_map.json`` is the only
    document-local bilingual glossary injected into the extraction prompt, so
    the ledger consumes that exact mapping and never asks another model to
    translate protected terms during verification.
    """
    path = Path(out_dir).expanduser().resolve() / TERM_MAP_FILE
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid extraction term map JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("extraction term map must be an object")
    schema = payload.get("schema")
    if schema != TERM_MAP_SCHEMA:
        raise ValueError("extraction term map lacks source-backed schema lineage")
    source_hash = payload.get("hash")
    terms = payload.get("terms")
    if (
        not isinstance(source_hash, str)
        or _TERM_MAP_HASH_RE.fullmatch(source_hash) is None
        or not isinstance(terms, list)
    ):
        raise ValueError("extraction term map is missing its source fingerprint or terms")
    source_terms = payload.get("source_terms")
    if (
        not isinstance(source_terms, list)
        or not source_terms
        or len(source_terms) > TERM_MAP_MAX
        or not all(isinstance(value, str) and value.strip() for value in source_terms)
        or _term_map_basis(source_terms) != source_hash
        or len(terms) > TERM_MAP_MAX
    ):
        raise ValueError("extraction term map source lineage is invalid")
    allowed_sources = {
        _canonical_term_alias(value).casefold() for value in source_terms
    }

    aliases_by_source: dict[str, list[str]] = {}
    seen_aliases: dict[str, set[str]] = {}
    for index, row in enumerate(terms[:TERM_MAP_MAX]):
        if not isinstance(row, dict):
            raise ValueError(f"extraction term map row {index} must be an object")
        source_value = row.get("en")
        target_value = row.get("zh")
        if not isinstance(source_value, str) or not isinstance(target_value, str):
            raise ValueError(f"extraction term map row {index} must contain string en/zh")
        source = _canonical_term_alias(source_value).casefold()
        target = _canonical_term_alias(target_value)
        if not source or not target:
            raise ValueError(f"extraction term map row {index} contains an empty en/zh value")
        if source not in allowed_sources:
            raise ValueError(f"extraction term map row {index} is not source-backed")
        aliases = aliases_by_source.setdefault(source, [])
        normalized_targets = seen_aliases.setdefault(source, set())
        normalized_target = target.casefold()
        if normalized_target not in normalized_targets:
            normalized_targets.add(normalized_target)
            aliases.append(target)
    return {source: aliases_by_source[source] for source in sorted(aliases_by_source)}


def ensure_term_map(out_dir: Path, chat: ChatFn, entries: list[tuple[str, str]]) -> str:
    """返回注入 doc_context 的对照表文本（空=无术语/生成失败）。缓存按术语清单哈希复用。"""
    if not entries:
        return ""
    names = [term for term, _ in entries][:TERM_MAP_MAX]
    basis = _term_map_basis(names)
    cache_path = out_dir / TERM_MAP_FILE
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("hash") == basis and cached.get("terms"):
                load_controlled_term_aliases(out_dir)
                return _render_term_map(cached["terms"])
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    try:
        payload = chat(
            "你是表计行业术语翻译员。给出每个英文术语的**统一中文译法**（简洁、行业惯用）。"
            "只输出 JSON：{\"terms\": [{\"en\": \"...\", \"zh\": \"...\"}]}。",
            json.dumps({"terms": names}, ensure_ascii=False))
        allowed_sources = {
            _canonical_term_alias(name).casefold(): _canonical_term_alias(name)
            for name in names
        }
        terms: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for row in payload.get("terms") or []:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("en"), str)
                or not isinstance(row.get("zh"), str)
            ):
                continue
            source_key = _canonical_term_alias(row["en"]).casefold()
            target = _canonical_term_alias(row["zh"])
            dedupe_key = (source_key, target.casefold())
            if (
                source_key not in allowed_sources
                or not target
                or dedupe_key in seen
            ):
                continue
            seen.add(dedupe_key)
            terms.append({"en": allowed_sources[source_key], "zh": target})
            if len(terms) >= TERM_MAP_MAX:
                break
    except Exception as exc:  # 可选增强：失败不影响抽取
        LOGGER.warning("术语对照生成失败（跳过）：%s", str(exc)[:120])
        return ""
    if not terms:
        return ""
    cache_path.write_text(json.dumps({
        "schema": TERM_MAP_SCHEMA,
        "hash": basis,
        "source_terms": names,
        "terms": terms,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return _render_term_map(terms)


def _render_term_map(terms: list[dict[str, str]]) -> str:
    lines = "\n".join(f"- {t['en']} → {t['zh']}" for t in terms[:TERM_MAP_MAX])
    return f"【术语译法对照（全文统一使用这些中文译法）】\n{lines}"


# --- 术语定向注入 ---------------------------------------------------------
# 术语表整体注入只带头 1800 字（后面的术语被截断）。改为按单元定向：本单元文本里出现的
# 已定义术语，注入其**定义原文**（出自 Terms and definitions 小节的对应子节）。


# --- 上下文工程：文档全局背景注入 ---------------------------------------

_CTX_GARBAGE_RE = re.compile(r"(?:\d+\s+)?[,`'=\-*_~|+…]{4,}")  # PDF 框线乱码片段


def _clean_ctx_text(text: str) -> str:
    """上下文文本清洁：剥离框线乱码、折叠空白。"""
    return re.sub(r"\s+", " ", _CTX_GARBAGE_RE.sub(" ", text or "")).strip()


def _outline_from_blocks(blocks: list[dict[str, Any]]) -> str:
    """章节大纲：去重的章节标题序列（给 LLM 文档结构感，解析跨章节引用）。每条限长、去乱码。"""
    seen: list[str] = []
    seen_set: set[str] = set()
    for b in blocks:
        path = b.get("section_path") or []
        head = _clean_ctx_text(str(path[-1]))[:70].strip() if path else ""
        if len(head) > 1 and head not in seen_set:
            seen_set.add(head)
            seen.append(head)
        if len(seen) >= DOC_CONTEXT_OUTLINE_MAX:
            break
    return " / ".join(seen)


def _glossary_from_blocks(blocks: list[dict[str, Any]]) -> str:
    """术语表：Terms/Definitions 节的文本（确定性截取 + 去乱码，不做脆弱的 term→def 解析）。"""
    parts: list[str] = []
    total = 0
    for b in blocks:
        if b.get("noise"):
            continue
        path = b.get("section_path") or []
        if not any(_TERMS_HEADING_RE.search(str(p)) for p in path):
            continue
        text = _clean_ctx_text(str(b.get("text") or ""))
        if not text:
            continue
        parts.append(text)
        total += len(text) + 1
        if total >= DOC_CONTEXT_GLOSSARY_MAX:
            break
    return "\n".join(parts)[:DOC_CONTEXT_GLOSSARY_MAX]


def build_doc_context(out_dir: Path, blocks: list[dict[str, Any]]) -> str:
    """文档全局上下文（表计类型/目标标准/章节大纲/术语表），注入每次章节抽取。确定性、可复现。

    只作术语与模块一致性、跨章节引用解析的**参考**；需求内容与 source_quote 仍须来自当前章节
    原文，且结构字段仍过双引擎漂移护栏（context 里的编码不会因此被当作源）。
    """
    try:
        from meter_profile import infer_meter_profile
        profile = infer_meter_profile(out_dir)
    except Exception as exc:  # pragma: no cover - 兜底，缺 manifest 等
        LOGGER.warning("文档画像失败，上下文降级：%s", exc)
        profile = {"meter_type": "", "target_standards": []}
    meter_type = str(profile.get("meter_type") or "未定")
    stds = "、".join(profile.get("target_standards") or []) or "未提取到"
    outline = _outline_from_blocks(blocks)
    glossary = _glossary_from_blocks(blocks)

    lines = [f"【文档背景】表计类型：{meter_type}；目标标准：{stds}。"]
    if outline:
        lines.append(f"【章节大纲】{outline}")
    if glossary:
        lines.append("【术语/定义（节选，仅供术语与模块一致性参考，勿据此编造原文没有的编码/数字）】")
        lines.append(glossary)
    return "\n".join(lines)


def code_drift(requirement: dict[str, Any], source_text: str) -> list[str]:
    """受保护编码漂移：需求里出现、源文没有的 OBIS/事件号/十六进制（严格）。"""
    return sorted(extract_codes(_produced_text(requirement)) - extract_codes(source_text))


def int_drift(requirement: dict[str, Any], source_text: str) -> list[str]:
    """普通整数漂移：需求里出现、源文没有的数字（软标）。
    两侧同口径(0715):基线含英文数词折算与千分位并组;产出侧同样并组。"""
    from extract_guards import produced_ints, source_int_baseline
    return sorted(produced_ints(_produced_text(requirement)) - source_int_baseline(source_text))


def extract_drift(requirement: dict[str, Any], source_text: str) -> list[str]:
    """编码 + 整数漂移合并（保留以兼容外部调用）。"""
    return sorted(set(code_drift(requirement, source_text)) | set(int_drift(requirement, source_text)))


def normalize_requirement(raw: dict[str, Any], section: dict[str, Any]) -> dict[str, Any]:
    source_quote = str(raw.get("source_quote") or "").strip()
    rtype = str(raw.get("type") or "functional").strip().casefold()
    if rtype not in VALID_TYPES:
        rtype = "functional"
    source_is_compliance = is_compliance_requirement({"source_quote": source_quote})
    if source_is_compliance:
        rtype = COMPLIANCE_TYPE
    elif rtype == COMPLIANCE_TYPE:
        # Compliance changes both delivery routing and the core coverage denominator. The model
        # cannot make that structural decision without a deterministic source-text signal.
        rtype = "functional"
    priority = str(raw.get("priority") or ("P0" if rtype == COMPLIANCE_TYPE else "P2"))
    if priority not in VALID_PRIORITIES:
        priority = "P0" if rtype == COMPLIANCE_TYPE else "P2"
    labels = [str(x) for x in (raw.get("labels") or []) if str(x).strip()]
    acceptance = [str(x) for x in (raw.get("acceptance_criteria") or []) if str(x).strip()]
    sub_items = [{"label": str(item.get("label") or "").strip()[:8],
                  "text": str(item.get("text") or "").strip()}
                 for item in (raw.get("sub_items") or [])
                 if isinstance(item, dict) and str(item.get("text") or "").strip()]
    dev_guidance = [str(x) for x in (raw.get("dev_guidance") or []) if str(x).strip()]
    design_options = [str(x) for x in (raw.get("design_options") or []) if str(x).strip()]
    module = str(raw.get("module") or ("测试合规" if rtype == COMPLIANCE_TYPE else "")).strip()
    compliance_obligations = normalize_obligations(
        raw.get("compliance_obligations") or raw.get("obligations")
    )
    instrument, instrument_audit = ("", "")
    if rtype == COMPLIANCE_TYPE:
        instrument, instrument_audit = resolve_source_backed_instrument(
            raw.get("compliance_instrument") or raw.get("instrument"), source_quote
        )
    return {
        "title": str(raw.get("title") or "").strip()[:80],
        "functional_key": str(raw.get("functional_key") or "").strip()[:100],
        "description": str(raw.get("description") or "").strip(),
        "type": rtype,
        "priority": priority,
        "module": module,
        "status": "draft",
        "source_section": str(raw.get("source_section") or section.get("heading") or section.get("section_id") or "").strip(),
        "source_quote": source_quote,
        "threshold_table": raw.get("threshold_table") if isinstance(raw.get("threshold_table"), dict) else None,
        "sub_items": sub_items,
        "acceptance_criteria": acceptance,
        "dev_guidance": dev_guidance,
        "design_options": design_options,
        "compliance_instrument": instrument,
        "compliance_obligations": compliance_obligations if rtype == COMPLIANCE_TYPE else [],
        "compliance_umbrella": (
            is_compliance_umbrella_source(source_quote) if rtype == COMPLIANCE_TYPE else False
        ),
        "dependencies": [],
        "parent": None,
        "children": [],
        "labels": labels,
        "notes": instrument_audit,
        "extracted_by": "ai_extract",
        "source_block_ids": list(section.get("block_ids") or []),
    }


# 纯引用/范围声明剔除（确定性、保守）：只杀两类明确无行为要求的条目——
# ① source_quote 本身就是标准号（"EN 16314:2013 (E)"）；② 范围声明（"This (European)
# Standard specifies/applies to ..."）。提及标准号但带设备行为的（"按 EN 1359 的方法测试
# 后应…"）不受影响。test7 实测 9 条此类条目混进交付物。
_CITATION_ONLY_RE = re.compile(r"^[\s]*(?:pr)?(?:EN|ISO|IEC|OIML|NBR|ABNT)[\s\d:.,/()\-+A-Z]*$")
_SCOPE_STMT_RE = re.compile(
    r"^\s*this\s+(?:european\s+|international\s+)?standard\s+(?:specifies|applies|is\s+applicable|covers|defines)",
    re.IGNORECASE)

_UNSUPPORTED_IMPLEMENTATION_TERMS = (
    ("FIFO", ("fifo", "fi-fo", "first in first out")),
    ("循环缓冲区", ("循环缓冲", "环形缓冲", "circular buffer", "ring buffer")),
    ("队列", ("队列", "queue")),
    ("断线续传", ("断线续传", "补传", "重传", "store-and-forward", "retransmit")),
    ("LoRa", ("lora",)),
    ("无线 M-Bus", ("无线 m-bus", "wireless m-bus", "wmbus", "wm-bus")),
)


def _is_reference_stub(req: dict[str, Any]) -> bool:
    quote = str(req.get("source_quote") or "").strip()
    if quote and _CITATION_ONLY_RE.match(quote):
        return True
    basis = quote or str(req.get("description") or "")
    return bool(_SCOPE_STMT_RE.match(basis))


def _append_note(req: dict[str, Any], note: str) -> None:
    req["notes"] = f"{req['notes']}；{note}" if req.get("notes") else note


_TARGET_SENTENCE_SPLIT_RE = re.compile(r"([。！？!?；;\n]+)")
_SOURCE_NON_MANDATORY_RE = re.compile(
    r"\b(?:may|should|could|might|optional(?:ly)?|informative|advisory|"
    r"recommend(?:ed|ation|s)?)\b|(?:资料性|非强制|可选|建议|宜)",
    re.IGNORECASE,
)


def _source_allows_normative_framing(requirement: dict[str, Any]) -> bool:
    quote = str(requirement.get("source_quote") or "").strip()
    suspicion = " ".join(str(value) for value in (
        requirement.get("suspicion_reasons") or []
    ))
    return bool(
        quote
        and not _SOURCE_NON_MANDATORY_RE.search(quote)
        and "资料性" not in suspicion
    )


def _rewrite_weak_capability_leaves(text: str) -> tuple[str, int]:
    """Make target-language capability leaves self-contained without changing their facts."""
    value = str(text or "")
    if not value:
        return value, 0
    parts = _TARGET_SENTENCE_SPLIT_RE.split(value)
    rewritten = 0
    for index in range(0, len(parts), 2):
        segment = parts[index]
        stripped = segment.strip()
        from normative_framing import (
            has_weak_capability,
            target_is_self_contained_product_obligation,
        )

        if (not stripped or target_is_self_contained_product_obligation(stripped)
                or not has_weak_capability(stripped)):
            continue
        leading = segment[:len(segment) - len(segment.lstrip())]
        trailing = segment[len(segment.rstrip()):]
        parts[index] = f"{leading}产品应支持以下能力：{stripped}{trailing}"
        rewritten += 1
    return "".join(parts), rewritten


def enforce_normative_framing(requirements: list[dict[str, Any]]) -> dict[str, int]:
    """Enforce a formal product-obligation contract on description/sub-item leaves.

    The guard operates on target-language grammar rather than enumerating source verbs. It only
    adds a normative wrapper, so roles, objects, conditions, codes, and numbers remain byte-for-byte
    inside the original leaf.
    """
    rewritten_leaves = 0
    rewritten_requirements = 0
    source_modality_blocked_leaves = 0
    source_modality_blocked_requirements = 0
    for requirement in requirements:
        changed = 0
        blocked = 0
        source_allows = _source_allows_normative_framing(requirement)
        description, count = _rewrite_weak_capability_leaves(
            str(requirement.get("description") or "")
        )
        if count:
            if source_allows:
                requirement["description"] = description
                changed += count
            else:
                blocked += count
        for item in requirement.get("sub_items") or []:
            if not isinstance(item, dict):
                continue
            item_text, count = _rewrite_weak_capability_leaves(
                str(item.get("text") or "")
            )
            if count:
                if source_allows:
                    item["text"] = item_text
                    changed += count
                else:
                    blocked += count
        if changed:
            rewritten_requirements += 1
            rewritten_leaves += changed
            _append_note(
                requirement,
                f"规范性成文护栏已补充产品义务主体（{AI_NORMATIVE_FRAMING_VERSION}）",
            )
        if blocked:
            source_modality_blocked_requirements += 1
            source_modality_blocked_leaves += blocked
            reasons = list(requirement.get("suspicion_reasons") or [])
            requirement["suspicion_reasons"] = list(dict.fromkeys([
                *reasons,
                "规范性成文待核",
            ]))
            note = (
                f"规范性成文待核（来源缺少可安全升格的强制依据，"
                f"未自动补充产品义务；{AI_NORMATIVE_FRAMING_VERSION}）"
            )
            if note not in str(requirement.get("notes") or ""):
                _append_note(requirement, note)
    return {
        "rewritten_leaf_count": rewritten_leaves,
        "rewritten_requirement_count": rewritten_requirements,
        "source_modality_blocked_leaf_count": source_modality_blocked_leaves,
        "source_modality_blocked_requirement_count": (
            source_modality_blocked_requirements
        ),
    }


def _unsupported_implementation_terms(text: str, source_text: str) -> list[str]:
    source_low = str(source_text or "").lower()
    text_low = str(text or "").lower()
    unsupported: list[str] = []
    for label, variants in _UNSUPPORTED_IMPLEMENTATION_TERMS:
        if any(v in text_low for v in variants) and not any(v in source_low for v in variants):
            unsupported.append(label)
    return unsupported


def _move_unsupported_delivery_items(req: dict[str, Any], source_text: str) -> tuple[set[str], set[str]]:
    """把无来源数字/编码/实现假设移出正式交付字段，并在 notes 留审计痕迹。

    普通整数在 title/description 里仍按“数字漂移”软标，避免误伤 RS-485 这类术语；但
    acceptance_criteria/dev_guidance 是研发会直接执行的字段，里面不能保留无依据容量、
    周期、默认值或具体实现策略。编码也必须查（2026-07-08 审计 B4）：编造 OBIS 拆成
    整数后在源文里几乎必然全部存在，只查 extract_ints 拦不住假 OBIS。
    返回 (漂移整数集, 漂移编码集)——编码并入 code_drift 走硬标（draft+拦截注）。
    """
    from extract_guards import produced_ints, source_int_baseline
    allowed = source_int_baseline(source_text)   # 含数词折算+千分位并组,防有据验收被剥
    allowed_codes = extract_codes(source_text)
    drifted: set[str] = set()
    drifted_codes: set[str] = set()
    removed: list[str] = []
    design_options = [str(value).strip() for value in (req.get("design_options") or []) if str(value).strip()]
    for field in ("acceptance_criteria", "dev_guidance"):
        kept: list[str] = []
        for raw in req.get(field) or []:
            text = str(raw).strip()
            # 整移判定剥引用编号(条款/标准号/表图号是"地址"不是"数值"):v5 审计里验收行
            # 因带 EN 标准号示例被整行误移,把核心阈值一起带走。软标漂移仍按原文本计算。
            unsupported = produced_ints(strip_produced_refs(text)) - allowed
            unsupported_codes = extract_codes(text) - allowed_codes
            unsupported_terms = _unsupported_implementation_terms(text, source_text)
            if unsupported or unsupported_terms or unsupported_codes:
                drifted |= unsupported
                drifted_codes |= unsupported_codes
                if field == "dev_guidance" and unsupported_terms and not unsupported and not unsupported_codes:
                    design_options.append(text)
                    continue
                reasons: list[str] = []
                if unsupported_codes:
                    reasons.append(f"无依据编码：{', '.join(sorted(unsupported_codes))}")
                if unsupported:
                    reasons.append(f"无依据数字：{', '.join(sorted(unsupported))}")
                if unsupported_terms:
                    reasons.append(f"无依据实现假设：{', '.join(unsupported_terms)}")
                removed.append(f"{field}: {text[:180]}（{'；'.join(reasons)}）")
            else:
                kept.append(text)
        req[field] = kept
    kept_obligations: list[dict[str, str]] = []
    for obligation in normalize_obligations(req.get("compliance_obligations")):
        text = str(obligation.get("text") or "").strip()
        unsupported = produced_ints(strip_produced_refs(text)) - allowed
        unsupported_codes = extract_codes(text) - allowed_codes
        unsupported_refs = foreign_standard_refs(
            {"compliance_obligations": [obligation]}, source_text
        )
        unsupported_terms = _unsupported_implementation_terms(text, source_text)
        if unsupported or unsupported_codes or unsupported_refs or unsupported_terms:
            drifted |= unsupported
            drifted_codes |= unsupported_codes
            reasons: list[str] = []
            if unsupported_codes:
                reasons.append(f"无依据编码：{', '.join(sorted(unsupported_codes))}")
            if unsupported:
                reasons.append(f"无依据数字：{', '.join(sorted(unsupported))}")
            if unsupported_refs:
                reasons.append(f"无依据标准号：{', '.join(unsupported_refs)}")
            if unsupported_terms:
                reasons.append(f"无依据实现假设：{', '.join(unsupported_terms)}")
            removed.append(
                f"compliance_obligations: {text[:180]}（{'；'.join(reasons)}）"
            )
        else:
            kept_obligations.append(obligation)
    req["compliance_obligations"] = kept_obligations
    # C1（0710 评审）：design_options 本体同样要洗——它是"非规范候选"但直达交付描述，
    # 实现方案词条（FIFO/缓存）是其用途所以保留，无据数字/编码仍必须移除（其自身契约
    # "不得带无依据容量或默认值"此前只是提示词约定）。降级来的条目已验证干净，不受影响。
    kept_options: list[str] = []
    for text in design_options:
        unsupported = extract_ints(text) - allowed
        unsupported_codes = extract_codes(text) - allowed_codes
        if unsupported or unsupported_codes:
            drifted |= unsupported
            drifted_codes |= unsupported_codes
            reasons = []
            if unsupported_codes:
                reasons.append(f"无依据编码：{', '.join(sorted(unsupported_codes))}")
            if unsupported:
                reasons.append(f"无依据数字：{', '.join(sorted(unsupported))}")
            removed.append(f"design_options: {text[:180]}（{'；'.join(reasons)}）")
        else:
            kept_options.append(text)
    req["design_options"] = list(dict.fromkeys(kept_options))
    if removed:
        suffix = "；…" if len(removed) > 6 else ""
        _append_note(req, "无依据条目已移入备注：" + "；".join(removed[:6]) + suffix)
    return drifted, drifted_codes


def _map_requirement_source(req: dict[str, Any], section: dict[str, Any]) -> None:
    source_blocks = [row for row in (section.get("source_blocks") or []) if isinstance(row, dict)]
    from merged_consistency import compact_source_text, match_source_quote_blocks

    matched, mapping = match_source_quote_blocks(req.get("source_quote"), source_blocks)
    quote = compact_source_text(req.get("source_quote"))
    if not matched and quote and source_blocks:
        from difflib import SequenceMatcher
        scored = [
            (SequenceMatcher(None, quote, compact_source_text(row.get("text"))).ratio(),
             str(row.get("block_id") or ""))
            for row in source_blocks
            if row.get("block_id") and not row.get("noise")
            and len(compact_source_text(row.get("text"))) >= 12
        ]
        score, block_id = max(scored, default=(0.0, ""))
        if score >= 0.82 and block_id:
            matched = [block_id]
            mapping = "fuzzy"
    if matched:
        req["source_block_ids"] = list(dict.fromkeys(matched))
        req["anchor_block_id"] = req["source_block_ids"][0]
        req["source_mapping"] = mapping
        _annotate_row_source(req, source_blocks, set(req["source_block_ids"]))
    else:
        span = list(section.get("block_ids") or [])
        narrowed = _narrow_span_to_req_section(req, source_blocks, span)
        # 页码/水印等噪声块不成来源（guards-v15，test10 实证：fallback span 带进噪声块）
        noise_ids = {str(row.get("block_id") or "") for row in source_blocks if row.get("noise")}
        req["source_block_ids"] = [
            block_id for block_id in (narrowed or span) if block_id not in noise_ids]
        if req["source_block_ids"]:
            req["anchor_block_id"] = req["source_block_ids"][0]
        req["source_mapping"] = "section_fallback"
        if narrowed and len(narrowed) < len(span):
            _append_note(req, f"来源回退已按所属小节收窄（{len(span)}→{len(narrowed)} 块）")


def _annotate_row_source(
    req: dict[str, Any],
    source_blocks: list[dict[str, Any]],
    matched_block_ids: set[str],
) -> None:
    """封堵一-B:行级溯源。parameter 表 source_block 携带行级明细(rows)时,把引句落点
    定位到具体数据行,记 source_row_index/source_item_id(可选字段,向后兼容)。block 级
    消费者零感知;批注热区等行级消费者可直接用,免文本重匹配。"""
    from merged_consistency import compact_source_text

    quote = compact_source_text(req.get("source_quote"))
    if not quote:
        return
    for sb in source_blocks:
        if str(sb.get("block_id") or "") not in matched_block_ids:
            continue
        for row in sb.get("rows") or []:
            cell_text = compact_source_text(row.get("text"))
            if not cell_text or len(cell_text) < 12:
                continue
            if cell_text in quote or quote in cell_text:
                try:
                    req["source_row_index"] = int(row.get("row_index"))
                except (TypeError, ValueError):
                    continue
                if row.get("item_id"):
                    req["source_item_id"] = str(row["item_id"])
                return
        # cell 级溯源（table-structure-v2）：引句命中 cell 上下文文本落 source_cell_id
        for cell in sb.get("cells") or []:
            cell_text = compact_source_text(cell.get("text"))
            if not cell_text or len(cell_text) < 12:
                continue
            if cell_text in quote or quote in cell_text:
                if cell.get("cell_id"):
                    req["source_cell_id"] = str(cell["cell_id"])
                try:
                    req["source_row_index"] = int(cell.get("row_index"))
                    req["source_column_index"] = int(cell.get("column_index"))
                except (TypeError, ValueError):
                    pass
                return


_SECTION_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)*$")
_SECTION_LEADING_NUMBER_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\b")


def _wanted_section_matchers(source_section: str) -> list[str]:
    """source_section 归一成可匹配的节号/节名集合。

    真实形态（test8 实证）：裸节号 "4.1"（块末段却是 "4.1 For local ..."）、
    多节号 "4.2, 4.3"。裸节号按块末段的引导数字前缀精确匹配（"4.1" 可命中
    "4.1 For local..."，"4.10" 不会误中）；含文字的节名仍逐字匹配。"""
    wanted: list[str] = []
    for part in re.split(r"[,，、/]", str(source_section or "")):
        wanted_part = _norm_verbatim(part)
        if wanted_part:
            wanted.append(wanted_part)
    return wanted


def _section_path_tail_matches(path_tail: str, wanted: list[str]) -> bool:
    tail = _norm_verbatim(path_tail)
    if not tail:
        return False
    leading = _SECTION_LEADING_NUMBER_RE.match(tail)
    leading_number = leading.group(1) if leading else ""
    for wanted_part in wanted:
        if _SECTION_NUMBER_RE.match(wanted_part):
            if leading_number == wanted_part:
                return True
        elif tail == wanted_part:
            return True
    return False


def _narrow_span_to_req_section(
    req: dict[str, Any], source_blocks: list[dict[str, Any]], span: list[str]
) -> list[str]:
    """section_fallback 收窄：抽取单元跨小节时只留需求所属小节的块（溯源宁窄勿滥）。

    真实案例（test5 招标 PDF）：单元跨 3.4.4/3.4.5/3.4.6 三小节，引句被块内碎句
    截断匹配失败后，旧口径把 24 块全标来源——无关清单段（端子列表 "- DAY1"）被
    误标"分析范围"。按 req.source_section 与块的 section_path 末段匹配收窄
    （支持裸节号前缀与多节号）；一个都匹配不上时返回空（调用方退回整单元，
    如实保留"定位不精"原口径），不猜。
    """
    wanted = _wanted_section_matchers(str(req.get("source_section") or ""))
    if not wanted:
        return []
    scoped: set[str] = set()
    for block in source_blocks:
        block_id = str(block.get("block_id") or "")
        path = block.get("section_path") or []
        if block_id and path and _section_path_tail_matches(str(path[-1]), wanted):
            scoped.add(block_id)
    return [block_id for block_id in span if block_id in scoped]


def _norm_verbatim(text: str) -> str:
    """NFKC + lowercase + collapse whitespace for verbatim-quote comparison."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(text or ""))).strip().lower()


def _char_verbatim(text: str) -> str:
    """NFKC + casefold 后只留 [a-z0-9]——标点归一差异层的比较底座（test3 分诊：37 条
    引用非逐字里 17 条是括号/冒号/µ/空格类出入,内容逐字）。quote 剥空时不判此层
    （空串是任意文本的子串,会假阳）——调用方须先查 quote_chars 非空。"""
    return re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKC", str(text or "")).casefold())


def _is_sentence_subsequence(quote: str, source: str) -> bool:
    """True if every sentence-like fragment of *quote* appears in *source* (cross-paragraph
    verbatim reassembly). Softer than exact substring — flags as 引用跨段 not 引用非逐字."""
    fragments = [f.strip() for f in re.split(r"[.!?;。！？；]\s*", quote) if f.strip()]
    if not fragments:
        return False
    norm_source = _norm_verbatim(source)
    return all(_norm_verbatim(f) in norm_source for f in fragments)


def _downgrade_cross_block_verbatim(requirements: list[dict[str, Any]], blocks: list[dict[str, Any]]) -> None:
    """跨块逐字降级：quote 在所属 section 内非逐字、但在全文（跨块拼接底座）逐字命中 →
    硬标"引用非逐字"改挂软标"引用跨段"（test3 分诊：37 条里 4 条是跨 section 边界的
    完整逐字引用,属锚点严格性误报,不该进必答清单）。"""
    full_norm = _norm_verbatim("\n".join(str(b.get("text") or "") for b in blocks))
    if not full_norm:
        return
    for req in requirements:
        reasons = req.get("suspicion_reasons") or []
        if "引用非逐字" not in reasons:
            continue
        quote_norm = _norm_verbatim(req.get("source_quote"))
        if quote_norm and quote_norm in full_norm:
            req["suspicion_reasons"] = ["引用跨段" if r == "引用非逐字" else r for r in reasons]


def _process_raw_requirements(raw_reqs: list[Any], section: dict[str, Any],
                              context_ints: frozenset[str] | set[str] = frozenset()) -> list[dict[str, Any]]:
    """raw LLM 需求 → 归一 + 分级漂移护栏。抽取与完整性自检共用（补的也过同一套护栏）。

    context_ints：文档背景（画像/术语表）里出现过的普通整数。LLM 引用背景里的标准号
    （如"依据 EN 12345"这类背景标准号）属合理行为，不软标为数字漂移——否则每条都是假阳性，稀释真漂移信号。
    受保护编码（OBIS/事件号/十六进制）**不豁免**：仍只认当前章节原文。
    """
    source = section.get("drift_source") or section.get("text", "")
    results: list[dict[str, Any]] = []
    for raw in raw_reqs:
        if not isinstance(raw, dict):
            continue
        req = normalize_requirement(raw, section)
        _map_requirement_source(req, section)
        _correct_source_section(req, section)   # 原文标题是硬证据,LLM 标错节号以它为准
        cleaned_desc = _strip_meta_text(req["description"])
        if cleaned_desc != req["description"]:   # 自检旁白泄漏进正文:句级剥除留痕
            req["description"] = cleaned_desc
            _append_note(req, "已剥除流程元话语（自检旁白不进交付正文）")
        if not req["description"] and not req["source_quote"]:
            continue
        if _is_reference_stub(req):
            # 纯标准引用/范围声明不是设备需求（用户裁定当前阶段忽略）：剔除并留痕
            LOGGER.info("剔除引用/范围声明条目：%s | quote=%s",
                        req.get("title", "")[:40], req.get("source_quote", "")[:60])
            continue
        if _is_definition_stub(req, section):
            # 纯术语定义不是需求（0715 内容审计:14 条"定义X术语"是单一最大噪声源）;
            # 带固定规则/取值的定义有约束力标记,不会命中此筛
            LOGGER.info("剔除纯术语定义条目：%s | quote=%s",
                        req.get("title", "")[:40], req.get("source_quote", "")[:60])
            continue
        removed_ints, removed_codes = _move_unsupported_delivery_items(req, source)
        codes = sorted(set(code_drift(req, source)) | removed_codes)
        ints = sorted(set(i for i in int_drift(req, source) if i not in context_ints) | removed_ints)
        notes = []
        if codes:  # 受保护编码漂移 → 严格：降级 draft 待核
            req["status"] = "draft"
            notes.append(f"结构漂移已拦截（编码，原文未见）：{', '.join(codes[:8])}")
        if ints:  # 普通整数漂移 → 软标：保留，待核
            notes.append(f"数字漂移（待核）：{', '.join(ints[:8])}")
        if not codes:
            # 无编码漂移：若模型给了状态信号则尊重，否则默认 draft（AI 抽取一律待审）
            req["status"] = "draft"
        if notes:
            _append_note(req, "；".join(notes))
        # 可疑度信号（零 LLM）：给审核视图排优先级——先审最可疑的
        suspicion: list[str] = []
        if codes:
            suspicion.append("编码漂移")
        if ints:
            suspicion.append("数字漂移")
        quote_norm = _norm_verbatim(req["source_quote"])
        if quote_norm and quote_norm not in _norm_verbatim(source):
            quote_chars = _char_verbatim(req["source_quote"])
            if quote_chars and quote_chars in _char_verbatim(source):
                # 标点归一差异（µs/括号/冒号出入,内容逐字）→ 软标,不进必答
                suspicion.append("引用标点差异")
            elif _is_sentence_subsequence(req["source_quote"], source):
                suspicion.append("引用跨段")
            else:
                suspicion.append("引用非逐字")
        left_behind = values_left_behind(req, source)
        if left_behind:
            suspicion.append("原文数值未带全")
            note = f"原文数值未带全（引句附近 {left_behind} 个数值未进需求，请核对参数清单）"
            _append_note(req, note)
        vague = vague_acceptance(req)
        if vague:
            suspicion.append("验收不可测")
            note = f"验收不可测（空话验收 {len(vague)} 条，如「{vague[0][:40]}」，请给出可判定条件）"
            _append_note(req, note)
        # 资料性来源（v5 审计最大病灶:Annex B(informative) 对照表被升格成 9 条 P1/P2
        # 强制需求——资料性内容对设备无强制力,升格即误导研发排期）。位置判据优先
        # (跨单元状态机,治混装/续表单元);无标注时退回单元级 heading/前 300 字判据。
        if _in_informative_range(req, section):
            if str(req.get("priority")) in ("P0", "P1"):
                req["priority"] = "P2"
                _append_note(req, "资料性附录来源:优先级已降为 P2（原文为 informative 附录,不构成强制义务）")
            suspicion.append("资料性附录来源")
            _append_note(req, "资料性附录来源（引句位于 informative 附录区段,默认不升格为义务,待专家裁定）")
        else:
            origin = " ".join([str(section.get("heading") or ""), str(section.get("text") or "")[:300]])
            if re.search(r"informative|资料性附录", origin, re.IGNORECASE) and str(req.get("priority")) in ("P0", "P1"):
                suspicion.append("资料性来源待核")
                _append_note(req, "资料性来源待核（本单元为 informative 附录/资料性内容,标成 P0/P1 强制需求请人工确认）")
        # 忠实性守恒（0715 内容审计:29 处误读全数绕过旧护栏——旧护栏只看编码/数字）
        if _modal_inflation(req, source):
            # v6 审计:should→必须 升格反复出现,prompt 约束挡不住(u36 差评);引句
            # should-only 时强制措辞是确定性可证的误译——按引句软化(必须→宜),
            # 软标保留供人工复核
            from extract_guards import _soften_modals
            req["title"] = _soften_modals(req["title"])
            req["description"] = _soften_modals(req["description"])
            for item in req.get("sub_items") or []:
                item["text"] = _soften_modals(item.get("text"))
            suspicion.append("情态升格待核")
            _append_note(req, "情态已按引句校正（引句为 should/建议性表述,强制措辞已软化为「宜」,请复核约束强度）")
        foreign_refs = foreign_standard_refs(req, source)
        if foreign_refs:
            suspicion.append("标准号待核")
            _append_note(req, f"标准号待核（{', '.join(foreign_refs[:3])} 不在本节原文,请核对是否张冠李戴）")
        pairing = _multi_value_pairing_risk(req, source)
        if pairing:
            suspicion.append("数值配对待核")
            _append_note(req, f"数值配对待核（{'、'.join(pairing[:3])} 存在多档数值,请对照原文核对数值与适用条件的配对）")
        # 表文一致性(v5 审计:表通道可靠,自然语言通道抄错——Type 1 阀门 1 l/h 被正文
        # 写成 5 l/h,同条目的表是对的且因"有表豁免"漏标)。单元格级核对,以表为准待核。
        table_mismatch = _threshold_desc_mismatch(req)
        if table_mismatch:
            suspicion.append("表文数值不一致")
            _append_note(req, f"表文数值不一致（正文/验收与自身阈值表不符,以表为准待核：{'; '.join(table_mismatch[:3])}）")
        if suspicion:
            req["suspicion_reasons"] = suspicion
        results.append(req)
    return results


# 模糊验收检测（BMAD "Done-ness clarity" 模式）：封杀"符合要求/正常工作"式空话验收——
# 研发看不出"完成"长什么样。命中空话短语且不含任何数字/编码/比较判据的验收条 → 标记待澄清。


def critique_section(section: dict[str, Any], existing: list[dict[str, Any]],
                     chat: ChatFn, doc_context: str = "",
                     context_ints: frozenset[str] | set[str] = frozenset(),
                     focus_lines: list[str] | None = None, *,
                     strict_focus: bool = False) -> list[dict[str, Any]]:
    """完整性自检：对着原文找已抽取需求**未覆盖**的遗漏项，补上（去重 + 同一套漂移护栏）。

    focus_lines：解析层标记 requirement_like 但未被任何已抽需求覆盖的原文语句——
    定向查漏的重点核查清单（比盲查更准）。strict_focus 默认关闭；开启时
    focus_lines 是唯一允许的来源证据，且 supplements 被确定性禁用。
    """
    # 给模型看**结构摘要**而非裸标题：真实案例（4.14）——初抽按条款族正确合成一条（子项
    # a-e + 验收），自检只见标题、看不见 a-e 已在 sub_items 里 → 判"遗漏"又拆回 4 条碎片，
    # 一个条款 18 个批注点。摘要必须暴露子项与验收，让"已覆盖"判断有据。
    # target_slot 编号定位(0716 补,镜像 verify_slot):同名条目 by_title 会并错目标。
    # 摘要行必须带描述片段——真实探针:两条同题条目只给标题时,模型选 slot 靠猜,
    # 把 AFD1 义务填进了 AFD3 的 slot(slot 只解决"传输保真",判据得喂给模型)
    summaries = "\n".join(
        f"- [target_slot {i}] {r.get('title', '')}"
        + f"｜描述:{_norm_ws(r.get('description'))[:48]}"
        + (f"｜子项:{','.join(str(s.get('label') or '·') for s in r.get('sub_items') or [])}"
           if r.get("sub_items") else "")
        + (f"｜验收 {len(r.get('acceptance_criteria') or [])} 条"
           if r.get("acceptance_criteria") else "")
        for i, r in enumerate(existing, 1)) or "（无）"
    parts: list[str] = []
    if doc_context:
        parts.append(doc_context)
        parts.append("---")
    parts.append(
        "【查漏补缺任务】下面是一个章节的原文 + 已抽取的需求结构摘要。找出章节里**尚未被覆盖**的"
        "需求/约束/可测语句。输出 JSON 对象，含两个数组："
        "{\"requirements\": [...], \"supplements\": [...]}，都可为空。"
        "**归属判定**（0715 降碎+v3 召回修正）：遗漏语句**确定**属于某条已抽需求的范围"
        "（同一条款/同一功能的枚举项、条件、参数、验收判据）——放进 supplements；"
        "**吃不准从属关系时,宁可作为独立需求输出到 requirements,不要硬塞 supplements**"
        "（塞错目标会被守卫丢弃,反而丢失内容）。放进 supplements 的格式："
        "{\"target_slot\": <该已抽需求的 target_slot 编号原样回填>, "
        "\"target_title\": \"<该已抽需求的 title 原样回填,仅作辅助核对>\", "
        "\"sub_items\": [{\"label\": \"c\", \"text\": \"…\"}], "
        "\"acceptance_criteria\": [\"…\"], \"description_append\": \"<可选的一句补充>\"}；"
        "只有与全部已抽需求都无从属关系的**独立功能点**才进 requirements（同样的 JSON schema、"
        "同样的 module 受控清单）。"
        "已覆盖的不要重复；原文没有的绝不编造；若无遗漏，两个数组都为空。"
        "**覆盖判定**：已抽需求的 sub_items（枚举子项 a/b/c…）与 acceptance_criteria 覆盖的语句"
        "算已覆盖——条款的枚举项、测试前/后判据、测试方法是该条款需求的组成部分，"
        "**不要**把它们拆成新需求（条款族=一条需求的原则对遗漏项同样适用）。"
        "**顺带复核**：若发现已抽需求的描述与其引句矛盾（约束强度升格、方向/主客体反转、"
        "无据添加适用条件），在 supplements 里回填该 target_slot/target_title 并给 "
        "\"faithfulness_note\": \"<必须同时逐字引出描述片段与引句片段来证明矛盾>\"——"
        "没有可引证的具体矛盾就不要报（空泛怀疑是噪声），不要改写原需求。"
        "supplements 里已存在于该需求 sub_items/验收里的内容**不要重复回填**。"
        "**数值配对复核**（同样走 faithfulness_note）：原文同一单位出现多档数值时"
        "（如不同型号/压力条件各有限值），逐条核对已抽需求里数值与其适用条件的配对"
        "是否与原文一致——张冠李戴（甲条件配了乙限值）是最严重的一类错误。"
        "**步骤编号配对复核**：已抽需求引用\"步骤 n)\"/\"step n\"时，逐字对照原文的步骤"
        "编号——比较基准错位（原文与步骤3比较、产出写成与步骤1比较）会让合格品被误判。")
    parts.append(f"当前章节：\n{build_section_prompt(section)}")
    parts.append(f"已抽取（勿重复）：\n{summaries}")
    if focus_lines:
        hints = "\n".join(f"- {line}" for line in focus_lines[:12])
        parts.append(f"重点核查以下原文语句是否含被遗漏的需求（解析层判定疑似需求但尚无需求覆盖）：\n{hints}")
    if strict_focus:
        strict_lines = [str(line or "").strip() for line in (focus_lines or []) if str(line or "").strip()]
        if not strict_lines:
            return [], 0
        hints = "\n".join(f"- {line}" for line in strict_lines[:12])
        parts = [
            "【严格定向需求抽取】只能依据下面的 focus evidence 生成 requirements。"
            "不要使用章节中的相邻行、文档上下文或已有需求作为来源证据。"
            "输出 JSON 对象 {\"requirements\": [...], \"supplements\": []}。"
            "每条 requirement 的 source_quote 必须逐字复制某一条 focus evidence 的连续片段；"
            "无法从 focus evidence 独立形成需求时返回两个空数组。",
            f"唯一允许的 focus evidence：\n{hints}",
        ]
    payload = chat(SYSTEM_PROMPT, "\n\n".join(parts))
    raw = payload.get("requirements") if isinstance(payload, dict) else None
    if strict_focus:
        supplements_applied, converted = 0, []
    else:
        supplements_applied, converted = _apply_supplements(
            payload.get("supplements") if isinstance(payload, dict) else None,
            existing, section)
    converted_titles = {_norm_ws(c.get("title")) for c in converted}
    raw = (list(raw) if isinstance(raw, list) else []) + converted
    if not raw:
        return [], supplements_applied
    seen = {_req_key(r) for r in existing}
    # 包含式去重基底：真实案例里自检补的"新"条目引句是已抽引句的**前缀子串**（精确匹配拦不住）
    existing_quotes = [q for q in (_norm_ws(r.get("source_quote")) for r in existing) if len(q) >= 20]
    extra: list[dict[str, Any]] = []
    for req in _process_raw_requirements(raw, section, context_ints):
        if strict_focus:
            quote = _norm_ws(req.get("source_quote"))
            if len(quote) < 3 or not any(
                quote in _norm_ws(line) for line in (focus_lines or [])
            ):
                continue
        key = _req_key(req)
        if not key or key in seen:
            continue
        quote = _norm_ws(req.get("source_quote"))
        if len(quote) >= 20 and any(quote in q or q in quote for q in existing_quotes):
            continue   # 与已抽需求同源（引句互为包含）→ 重复，弃
        seen.add(key)
        if len(quote) >= 20:
            existing_quotes.append(quote)
        req["self_check_added"] = True  # 初抽遗漏、自检补回——审核时优先看
        req["suspicion_reasons"] = list(req.get("suspicion_reasons") or []) + ["自检补充（初抽遗漏）"]
        if _norm_ws(req.get("title")) in converted_titles:
            req["suspicion_reasons"].append("自检补充转独立（原目标未匹配,请核归属）")
        extra.append(req)
    return extra, supplements_applied


def _near_dup(text: str, existing: list[str]) -> bool:
    """近重复判定(0715 v2 审计:并入的同义复述堆叠 2-4 遍)——归一后互含即重复。

    v5 校准加固:互含拦不住换词复述("温度曲线"↔"温度分布"),但纯相似度阈值也不可行
    (实测语义不同的两档判据 J=0.57 高于部分真复读的 0.40)——J≥0.5 **且数字多重集
    相同**才判重:数字守卫恰好保住 1型/2型、20/75 mbar 这类关键差异。"""
    t = _norm_ws(text)
    if not t:
        return True
    nums = _num_multiset(text)
    for e in existing:
        en = _norm_ws(e)
        if not en:
            continue
        if t in en or en in t:
            return True
        if _gram_jaccard(t, en) >= 0.5 and nums == _num_multiset(e):
            return True
    return False


_CLAUSE_MARK_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)+)(?![\d.])")


def _supplement_clause_mismatch(sup_text: str, section_text: str, target_section: str) -> bool:
    """跨条款越界并入守卫(0715 v2 审计:7.6 的义务被并进 7.4 的需求)。

    在单元原文里定位补充文本,取其前方最近的条款号;与 target 的 source_section
    互为前缀才放行。定位不到/无条款号 → 不判(宁放勿错杀,单元多为同条款族)。"""
    frag = _norm_ws(sup_text)[:80]
    if not frag or not target_section:
        return False
    hay = _norm_ws(section_text)
    pos = hay.find(frag)
    if pos < 0:
        return False
    marks = [(m.start(), m.group(1)) for m in _CLAUSE_MARK_RE.finditer(hay[:pos])]
    if not marks:
        return False
    nearest = marks[-1][1]
    tgt = str(target_section).strip().split()[0]
    if not re.match(r"^\d+(?:\.\d+)*$", tgt):
        return False
    return not (nearest.startswith(tgt) or tgt.startswith(nearest))


# 自检流程元话语(管线自述词面,客户需求正文不会出现):v5 审计 6+ 处自检旁白整段
# 泄漏进交付正文("本条已抽需求聚焦…""故不单独成需求""可作为本需求的背景或扩展")。
# 词表只收多字强标记——"自检/查漏/补漏/已覆盖"等短词是计量领域真实需求词面,不进表
_META_DISCOURSE_RE = re.compile(
    r"已抽需求|已抽取的需求|不单独成需求|不再单独成|查漏补缺|补漏内容|"
    r"整合[进至]|已在后续条款|已在验收标准|本需求的背景|作为背景或扩展|"
    r"自检(?:补充|并入|复核)|需求应明确|描述已覆盖|已覆盖要求|无补充")


def _strip_meta_text(text: str) -> str:
    """句级剥除流程元话语,保留正常需求句;整段皆元话语则返回空。"""
    parts = re.split(r"(?<=[。;；!?\n])", str(text or ""))
    kept = [p for p in parts if p.strip() and not _META_DISCOURSE_RE.search(p)]
    return "".join(kept).strip()


def _locate_verbatim(fragment: str, section_text: str) -> str:
    """在单元原文里定位片段(空白弹性),返回原文原样子串——供转换需求当逐字引句。"""
    frag = str(fragment or "").strip()
    if len(frag) < 20:
        return ""
    pattern = re.compile(r"\s+".join(re.escape(w) for w in frag.split()[:24]), re.IGNORECASE)
    m = pattern.search(section_text or "")
    return m.group(0) if m else ""


def _apply_supplements(raw_supplements: Any, existing: list[dict[str, Any]],
                       section: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    """自检并入（0715 降碎）：把补漏内容并进已有需求的 sub_items/验收,不新开碎条。

    护栏不放宽:补充文本过同一套漂移检查(编码硬拒该条补充、整数软标随行);
    目标定位 slot 优先(0716 补,镜像 verify_slot——专家审核:同名条目 by_title
    覆盖会并错目标):target_slot 有效直接用;否则 title 回退但**仅当唯一**,
    同名歧义不裁走未匹配路径(转独立/丢弃留痕,宁缺勿错)。返回采纳的补充数。
    v2 审计加固:同标签子项不重复加(标签在需求内唯一)、近重复文本不加(同义复述
    堆叠)、跨条款越界并入丢弃、忠实性复核须有可锚定证据才挂 suspicion。
    """
    if not isinstance(raw_supplements, list):
        return 0, []
    source = section.get("drift_source") or section.get("text", "")
    section_text = section.get("text", "")
    by_slot = {i: r for i, r in enumerate(existing, 1)}
    slots_by_title: dict[str, list[int]] = {}
    for slot, req in by_slot.items():
        title_key = _norm_ws(req.get("title"))
        if title_key:
            slots_by_title.setdefault(title_key, []).append(slot)

    def _resolve_target(sup: dict[str, Any]) -> dict[str, Any] | None:
        try:
            slot = int(sup.get("target_slot"))
        except (TypeError, ValueError):
            slot = 0
        if slot in by_slot:
            return by_slot[slot]
        title_slots = slots_by_title.get(_norm_ws(sup.get("target_title"))) or []
        if len(title_slots) == 1:
            return by_slot[title_slots[0]]
        if len(title_slots) > 1:
            LOGGER.info("自检补充目标同名歧义(%d 条同题)且无有效 slot,不裁：%s",
                        len(title_slots), str(sup.get("target_title") or "")[:40])
        return None

    applied = 0
    converted: list[dict[str, Any]] = []
    for sup in raw_supplements:
        if not isinstance(sup, dict):
            continue
        # 元话语消毒(v5 审计:自检旁白整段泄漏进交付正文):append 句级剥除;
        # 子项/验收是单判据,含元话语整条丢弃(半句残留没有交付价值)
        sup = dict(sup)
        sup["description_append"] = _strip_meta_text(sup.get("description_append"))
        sup["sub_items"] = [s for s in (sup.get("sub_items") or [])
                            if isinstance(s, dict)
                            and not _META_DISCOURSE_RE.search(str(s.get("text") or ""))]
        sup["acceptance_criteria"] = [x for x in (sup.get("acceptance_criteria") or [])
                                      if not _META_DISCOURSE_RE.search(str(x))]
        pseudo = {"title": "", "description": str(sup.get("description_append") or ""),
                  "source_quote": "",
                  "sub_items": [s for s in (sup.get("sub_items") or []) if isinstance(s, dict)],
                  "acceptance_criteria": [str(x) for x in (sup.get("acceptance_criteria") or [])],
                  "dev_guidance": [], "design_options": [], "notes": ""}
        removed_ints, removed_codes = _move_unsupported_delivery_items(pseudo, source)
        # 自检补充与首轮抽取共用交付字段护栏。先回写清洗结果,再进入匹配/转换路径,
        # 防止无据数字、编码或实现假设借 supplements 绕过首轮处理。
        sup["acceptance_criteria"] = list(pseudo["acceptance_criteria"])
        guard_note = str(pseudo.get("notes") or "")
        target = _resolve_target(sup)
        if target is None:
            # v3 召回修正:未匹配不再直接丢——内容能在原文逐字定位的,转为独立需求原料
            # (走同一套 _process 护栏与去重;定位不到的仍丢弃留痕,宁缺勿错)
            texts = [str(s.get("text") or "") for s in (sup.get("sub_items") or [])
                     if isinstance(s, dict)] + [str(x) for x in (sup.get("acceptance_criteria") or [])]
            quote = next((q for q in (_locate_verbatim(t, section.get("text", "")) for t in texts) if q), "")
            # 正文取第一个够长的候选:短 append + 长子项是常态,append 过短不应整条丢弃
            body = next((b.strip() for b in [str(sup.get("description_append") or "")] + texts
                         if len(b.strip()) >= 20), "")
            if quote and body:
                converted.append({
                    "title": str(sup.get("target_title") or "")[:80] or body[:40],
                    "description": body, "source_quote": quote,
                    "sub_items": [s for s in (sup.get("sub_items") or []) if isinstance(s, dict)],
                    "acceptance_criteria": [str(x) for x in (sup.get("acceptance_criteria") or [])],
                    "type": "functional", "priority": "P2", "labels": [],
                })
                LOGGER.info("自检补充目标未匹配,转独立需求：%s", str(sup.get("target_title") or "")[:40])
            else:
                LOGGER.info("自检补充目标未匹配且无法定位,丢弃：%s", str(sup.get("target_title") or "")[:40])
            continue
        codes = code_drift(pseudo, source)
        if codes:
            LOGGER.info("自检补充编码漂移,拒绝并入：%s", ", ".join(sorted(codes)[:4]))
            continue
        probe_text = " ".join([str(s.get("text") or "") for s in pseudo["sub_items"]]
                              + pseudo["acceptance_criteria"]) or pseudo["description"]
        if _supplement_clause_mismatch(probe_text, section_text,
                                       str(target.get("source_section") or "")):
            LOGGER.info("自检补充跨条款越界,丢弃：target=%s", str(target.get("title") or "")[:30])
            continue
        changed = False
        have_labels = {_norm_ws(s.get("label")) for s in target.get("sub_items") or []}
        have_labels.discard("")
        have_sub_texts = [str(s.get("text") or "") for s in target.get("sub_items") or []]
        for item in pseudo["sub_items"]:
            label = str(item.get("label") or "").strip()
            text = str(item.get("text") or "").strip()
            if not text or _near_dup(text, have_sub_texts):
                continue
            if label and _norm_ws(label) in have_labels:
                continue   # 标签在需求内唯一:同标签重复=模型复读,不并
            target.setdefault("sub_items", []).append({"label": label, "text": text})
            have_sub_texts.append(text)
            if label:
                have_labels.add(_norm_ws(label))
            changed = True
        have_acc = [str(x) for x in target.get("acceptance_criteria") or []]
        for text in pseudo["acceptance_criteria"]:
            if text.strip() and not _near_dup(text, have_acc):
                target.setdefault("acceptance_criteria", []).append(text.strip())
                have_acc.append(text)
                changed = True
        append = str(sup.get("description_append") or "").strip()
        if append and not _near_dup(append, [str(target.get("description") or "")]):
            target["description"] = (str(target.get("description") or "").rstrip() + "\n" + append).strip()
            changed = True
        note = str(sup.get("faithfulness_note") or "").strip()
        if note:
            # 证据锚定(v2 审计:5 处复核标记全为空泛误报):note 里须含能在原文/引句里
            # 找到的 ≥8 字片段才挂 suspicion;无锚定证据的只记 note 不标复核
            anchor_ok = any(
                _norm_ws(note[i:i + 12]) and _norm_ws(note[i:i + 12]) in _norm_ws(
                    section_text + " " + str(target.get("source_quote") or ""))
                for i in range(0, max(1, len(note) - 11), 6))
            if anchor_ok:
                target["suspicion_reasons"] = list(dict.fromkeys(
                    list(target.get("suspicion_reasons") or []) + ["自检复核:描述与引句疑似矛盾"]))
                _append_note(target, f"自检复核：{note[:120]}")
                changed = True
            else:
                LOGGER.info("自检复核缺锚定证据,不挂标记：%s", note[:60])
        ints = sorted(set(int_drift(pseudo, source)) | removed_ints)
        if ints and changed:
            _append_note(target, f"自检补充含数字漂移（待核）：{', '.join(ints[:6])}")
        if removed_codes and changed:
            _append_note(target, f"自检补充无据编码已移除：{', '.join(sorted(removed_codes)[:6])}")
        if guard_note and changed:
            _append_note(target, guard_note)
        elif guard_note:
            LOGGER.info("自检补充交付字段经护栏清空,未并入：target=%s", str(target.get("title") or "")[:30])
        if changed:
            _append_note(target, "自检并入：补漏内容已并入本需求（未新开条目）")
            applied += 1
    return applied, converted


def _uncovered_requirement_lines(section: dict[str, Any], existing: list[dict[str, Any]],
                                 block_info: dict[str, dict[str, Any]] | None) -> list[str] | None:
    """本章节内 requirement_like 且未被任何已抽 source_quote 覆盖的原文语句。

    返回 None 表示无块信息（调用方回退全量盲查）。拆分片段只核查落在本片段文本里的语句，
    防同一遗漏被多个片段重复补。
    """
    if not block_info:
        return None
    from merged_consistency import compact_source_text, covered_block_ids

    section_blocks = [
        block_info[str(block_id)]
        for block_id in (section.get("block_ids") or [])
        if str(block_id) in block_info
    ]
    covered_ids = covered_block_ids(existing, section_blocks)
    # 子项覆盖记账：条款族合并后 a)b)c) 各行活在 sub_items 里而非 source_quote 里——
    # 不认子项标签会把它们永远判"未覆盖"，定向自检轮轮追打、拆碎条款（真实案例 4.14）
    sub_labels = {str(s.get("label") or "").strip().lower()
                  for r in existing for s in (r.get("sub_items") or [])}
    sub_labels.discard("")
    # 子项文本也算覆盖(0715 自检并入):supplements 并进来的无标签子项/验收要能消掉
    # 对应未覆盖行,否则收敛循环轮轮追打同一句
    covered_texts = [t for t in (
        [compact_source_text(s.get("text")) for r in existing for s in (r.get("sub_items") or [])]
        + [compact_source_text(x) for r in existing for x in (r.get("acceptance_criteria") or [])])
        if len(t) >= 20]
    section_text = _norm_ws(section.get("text"))
    uncovered: list[str] = []
    seen: set[str] = set()
    for bid in section.get("block_ids") or []:
        block = block_info.get(str(bid))
        if not block or not block.get("requirement_like") or block.get("noise"):
            continue
        if block.get("type") == "heading":
            continue   # 标题被关键词误标 requirement_like（如 "4.14.1 Requirement"）——不是内容
        cleaned = clean_block_text(block)   # 目录点线行不进自检焦点（追着目录行查漏纯烧调用）
        bt = _norm_ws(cleaned)
        if not bt or bt in seen or bt not in section_text:
            continue
        seen.add(bt)
        compact = compact_source_text(cleaned)
        if str(bid) in covered_ids or any(
            text in compact or compact in text for text in covered_texts
        ):
            continue
        m = re.match(r"^\(?([a-z])\)", bt)
        if m and m.group(1) in sub_labels:
            continue   # 该枚举项已被某条需求的 sub_items 覆盖
        uncovered.append(cleaned[:200])
    return uncovered


# Annex 标题独占行(EN 惯例:字母+资料性/规范性标记独占一行,标题在下一行);
# 行文里的 "given in Annex A" 提及不匹配(行锚定+行尾)
_ANNEX_HEAD_RE = re.compile(
    r"(?m)^\s*(Annex\s+[A-Z])\s*(\((?:informative|normative)\))\s*$", re.IGNORECASE)


def _annotate_annex_scopes(sections: list[dict[str, Any]]) -> None:
    """文档级资料性区段标注(跨单元携带状态):给每个 section 写 informative_ranges。

    v5 审计最大病灶:Annex B (informative) 的对照表被升格成 9 条 P1/P2 强制需求——
    单元级 heading/前 300 字判据探不到(打包单元混装资料性 B 表与规范性 C 正文,
    且续表单元里根本没有标记,标记在上一单元)。状态机按文档顺序扫 Annex 标题行,
    informative 状态跨单元携带,直到下一个 normative 标记为止。"""
    state_informative = False
    for section in sections:
        text = str(section.get("text") or "")
        ranges: list[tuple[int, int]] = []
        open_start = 0 if state_informative else None
        for m in _ANNEX_HEAD_RE.finditer(text):
            informative = "informative" in m.group(2).casefold()
            if informative and open_start is None:
                open_start = m.start()
            elif not informative and open_start is not None:
                ranges.append((open_start, m.start()))
                open_start = None
            state_informative = informative
        if open_start is not None:
            ranges.append((open_start, len(text)))
        section["informative_ranges"] = ranges


def _in_informative_range(req: dict[str, Any], section: dict[str, Any]) -> bool:
    ranges = section.get("informative_ranges")
    if not ranges:
        return False
    text = str(section.get("text") or "")
    quote = str(req.get("source_quote") or "")
    pos = text.find(quote) if quote else -1
    if pos < 0 and quote:
        located = _locate_verbatim(quote, text)
        pos = text.find(located) if located else -1
    if pos < 0:
        # 引句定位不到:整单元均为资料性时仍判定(续表单元常无可定位标题行)
        return len(ranges) == 1 and ranges[0][0] == 0 and ranges[0][1] >= len(text)
    return any(s <= pos < e for s, e in ranges)


# 锚点质量门(v6 回归教训:PDF 把正文编号行/图注标成标题块——"## 3 % by gaseous
# volume…"被当"第 3 章"覆盖了正确的 D.3.3):数字锚点必须带点(裸整数=章号与图注
# 无法区分,不作覆盖证据);支持字母条款(D.3.3);标题尾 ≤60 字(超长=正文行)
_HEADING_ANCHOR_RE = re.compile(
    r"(?m)^(?:##+\s*((?:\d+(?:\.\d+)+|[A-Z]\.\d+(?:\.\d+)*))\s*(.{0,60})"
    r"|\s*(Annex\s+[A-Z])\s*(\((?:informative|normative)\))\s*)$",
    re.IGNORECASE)


def _derive_source_section(quote: str, section_text: str) -> str:
    """由引句在原文中的位置取最近前置小节标题——溯源节号的确定性证据。

    v5 审计:某单元 5 条 source_section 全被 LLM 标成邻近章节号(quote 本身逐字正确),
    原文标题是硬证据,以它为准。定位不到引句/引句前无合格标题行 → 返回空(不裁)。"""
    quote = str(quote or "").strip()
    text = str(section_text or "")
    if not quote:
        return ""
    pos = text.find(quote)
    if pos < 0:
        located = _locate_verbatim(quote, text)
        pos = text.find(located) if located else -1
    if pos < 0:
        return ""
    best = ""
    for m in _HEADING_ANCHOR_RE.finditer(text):
        if m.start() >= pos:
            break
        if m.group(1):
            best = f"{m.group(1)} {(m.group(2) or '').strip()}".strip()
        else:
            best = f"{m.group(3)} {(m.group(4) or '').strip()}".strip()
    return best[:100]


def _sec_anchor_key(s: str) -> tuple[str, str] | None:
    """节号语义键:数字/字母条款号 或 附录字母。识别不出返回 None(不作证据)。"""
    s = str(s or "").strip()
    m = re.match(r"(\d+(?:\.\d+)*|[A-Z]\.\d+(?:\.\d+)*)\b", s)
    if m:
        return ("clause", m.group(1))
    m = re.match(r"(?i)annex\s+([A-Z])\b", s)
    if m:
        return ("annex", m.group(1).upper())
    return None


def _correct_source_section(req: dict[str, Any], section: dict[str, Any]) -> None:
    derived = _derive_source_section(req.get("source_quote"), section.get("text"))
    if not derived:
        return
    dk = _sec_anchor_key(derived)
    if dk is None:
        return   # 派生结果本身不像节号:不作证据(宁缺勿错)
    claimed = str(req.get("source_section") or "").strip()
    ck = _sec_anchor_key(claimed)
    if ck is not None:
        if dk == ck:
            return
        if dk[0] == ck[0] == "clause":
            dn, cn = dk[1], ck[1]
            if dn.startswith(cn + ".") or cn.startswith(dn + "."):
                return   # 互为前缀(粗细粒度差异):不动
        # 字母条款与同字母附录互认(claimed=D.3.3 与 derived=Annex D 一致,保留更细的 claimed)
        if dk[0] == "annex" and ck[0] == "clause" and ck[1][:1].upper() == dk[1]:
            return
        if ck[0] == "annex" and dk[0] == "clause" and dk[1][:1].upper() == ck[1]:
            pass   # claimed 只给了附录字母,derived 更细:覆盖
    req["source_section"] = derived
    if claimed:
        _append_note(req, f"溯源节号按原文校正：{claimed[:40]} → {derived[:60]}")


_CLAUSE_TAIL_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\s*(.*)$")
# 纯测试类标题尾(整尾匹配,防"Test interface"这类实体名误折)
_PURE_TEST_TAIL_RE = re.compile(
    r"^(?:tests?|test\s+methods?|test\s+procedures?|verifications?|试验|测试|检验|验证)"
    r"(?:\s*(?:methods?|procedures?|方法|程序))?\s*$", re.IGNORECASE)
# 纯要求类标题尾:多个非测试兄弟平票时的结构裁决(X.Y.1 Requirement + X.Y.2 Test 惯例)
_PURE_REQ_TAIL_RE = re.compile(r"^(?:requirements?|要求)\s*$", re.IGNORECASE)


def _fold_test_siblings(reqs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """条款族=一条需求的确定性兜底：`X.Y.n Test` 独立条并回同族 Requirement 条的验收。

    prompt（v9 起）已约束 Test→验收,但 LLM 采样方差偶发拆条（v4 实测 3 处、v3 1 处）。
    判据纯结构：条款号 + 纯测试类标题尾；目标=同父唯一非测试兄弟条目,无兄弟时取父条款
    条目；候选歧义（≥2 兄弟）不动——并错目标比拆条更糟,宁缺勿错。
    """
    parsed: list[tuple[str, str]] = []
    by_num: dict[str, list[int]] = {}
    for i, r in enumerate(reqs):
        m = _CLAUSE_TAIL_RE.match(str(r.get("source_section") or ""))
        num, tail = (m.group(1), m.group(2)) if m else ("", "")
        parsed.append((num, tail))
        if num:
            by_num.setdefault(num, []).append(i)
    drop: set[int] = set()
    for i, r in enumerate(reqs):
        num, tail = parsed[i]
        if not num or "." not in num or not _PURE_TEST_TAIL_RE.match(tail):
            continue
        parent = num.rsplit(".", 1)[0]
        siblings = [j for j, (n2, t2) in enumerate(parsed)
                    if j != i and j not in drop and n2 and n2 != num
                    and n2.rsplit(".", 1)[0] == parent
                    and not _PURE_TEST_TAIL_RE.match(t2)]
        if len(siblings) == 1:
            tgt = reqs[siblings[0]]
        elif len(siblings) > 1:
            # 平票裁决:恰有一个纯"Requirement"尾的兄弟(X.Y.1 Requirement + X.Y.2 Test 惯例)
            req_tail = [j for j in siblings if _PURE_REQ_TAIL_RE.match(parsed[j][1])]
            if len(req_tail) != 1:
                continue
            tgt = reqs[req_tail[0]]
        else:
            parents = [j for j in by_num.get(parent, []) if j != i and j not in drop]
            if len(parents) != 1:
                continue
            tgt = reqs[parents[0]]
        lines = [str(x).strip() for x in (r.get("acceptance_criteria") or []) if str(x).strip()]
        if not lines and str(r.get("description") or "").strip():
            lines = [str(r["description"]).strip()]
        lines += [str(s.get("text") or "").strip() for s in (r.get("sub_items") or [])
                  if isinstance(s, dict) and str(s.get("text") or "").strip()]
        have = [str(x) for x in (tgt.get("acceptance_criteria") or [])]
        for ln in lines:
            if not _near_dup(ln, have):
                tgt.setdefault("acceptance_criteria", []).append(ln)
                have.append(ln)
        if r.get("threshold_table") and not tgt.get("threshold_table"):
            tgt["threshold_table"] = r["threshold_table"]
        carried = [s for s in (r.get("suspicion_reasons") or [])]
        if carried:
            tgt["suspicion_reasons"] = list(dict.fromkeys(
                list(tgt.get("suspicion_reasons") or []) + carried))
        source_ids = list(tgt.get("source_block_ids") or [])
        for block_id in r.get("source_block_ids") or []:
            if block_id not in source_ids:
                source_ids.append(block_id)
        if source_ids:
            tgt["source_block_ids"] = source_ids
        _append_note(tgt, f"同族 Test 条款已并入验收：{num}（条款族=一条需求）")
        drop.add(i)
    if not drop:
        return reqs
    return [r for i, r in enumerate(reqs) if i not in drop]


# --- 二遍语义复核(0715:v6 审计残余差评全是语义理解错误,确定性护栏无法核验,
# prompt v18 针对性约束实证挡不住——独立对抗性核查视角是剩下的机制层手段) ----

_VERIFY_KINDS = {
    "exemption_reversal": "免责从句反转",
    "direction": "方向或上下限反转",
    "quantifier": "数量词范围改写",
    "subject": "主体或受试对象错置",
    "value_pairing": "数值条件配对",
    "step_ref": "步骤编号错位",
    "attribution": "条款或标准归属",
    "obligation_framing": "产品义务主体缺失",
}

VERIFY_SYSTEM_PROMPT = (
    "你是需求抽取的语义复核员。对照【章节原文】逐条核查【已抽需求】,只查八类语义错误:"
    "① 免责/例外从句方向(unless/without/except/provided that——豁免条件被写成禁止项或独立义务,"
    "如\"不得漂移超限——除非显示错误标志\"被写成\"不得显示错误标志\");"
    "② 范围/方向(\"at least X to Y\"的覆盖语义:声明范围须覆盖[X,Y]即下限≤X 且上限≥Y;"
    "不小于/不大于、上下限方向);"
    "③ 数量词(one or more/any/all/each 与产出的\"全部/任一/至少\"是否对应,"
    "\"one or more of the following\"写成\"全部必备\"是典型错误);"
    "④ 主体/受试对象错置(原文约束甲对象,产出写成乙对象);"
    "⑤ 数值与适用条件配对(型号/压力/温度档张冠李戴:甲条件配了乙限值);"
    "⑥ 步骤编号引用(产出引用\"步骤 n\"时与原文该步骤内容是否对应,比较基准错位会误判合格品);"
    "⑦ 条款/标准号归属(产出引用的编号是否确属原文所述标准/条款);"
    "⑧ 产品义务主体缺失(原文是产品应提供的可配置/可选择能力，产出却只写角色“可以做什么”，"
    "没有写产品应支持或允许该能力；同时核对角色和具体对象是否保留)。"
    "**只报实错**:每个发现必须同时给出原文逐字片段(evidence_source,从章节原文原样复制)"
    "与产出逐字片段(evidence_produced,从该需求文本原样复制),两者对照能直接看出矛盾;"
    "吃不准/需要推测的不报;纯表述风格、翻译措辞、粒度、遗漏问题都不报；产品规范义务主体缺失"
    "属于上述第八类语义错误，不按风格问题忽略。"
    "每条已抽需求都带 verify_slot。发现必须原样回填对应 verify_slot；title 仅作辅助核对。"
    "correction 可选:给出把 evidence_produced 改正后的最小建议文本——只改错的部分,"
    "不新增原文没有的内容,数值/编码只准来自原文；系统只留痕建议,不会自动改写需求。"
    "只输出 JSON:{\"findings\": [{\"verify_slot\": 1, \"title\": \"<该需求 title 原样回填>\", \"kind\": "
    "\"exemption_reversal|direction|quantifier|subject|value_pairing|step_ref|attribution|obligation_framing\", "
    "\"evidence_source\": \"…\", \"evidence_produced\": \"…\", \"correction\": \"<可选>\"}]}"
    "。无发现输出 {\"findings\": []}。"
)


def _anchored(fragment: str, hay: str, min_len: int = 8) -> bool:
    """全剥空白后的包含式锚定(证据片段必须逐字可定位;短于 min_len 不算证据)。

    剥空白而非归并:CJK 产出无空格,模型复制证据时插入的空格不该导致锚定失败。"""
    frag = re.sub(r"\s+", "", str(fragment or ""))
    return len(frag) >= min_len and frag.casefold() in re.sub(r"\s+", "", str(hay or "")).casefold()


def _entry_produced_text(req: dict[str, Any]) -> str:
    return " ".join([str(req.get("title") or ""), str(req.get("description") or "")]
                    + [str(s.get("text") or "") for s in req.get("sub_items") or []]
                    + [str(s.get("text") or "") for s in req.get("compliance_obligations") or []]
                    + [str(x) for x in req.get("acceptance_criteria") or []])


def _verify_section(section: dict[str, Any], results: list[dict[str, Any]], chat: ChatFn,
                    rounds: int = 1) -> int:
    """对本章节最终条目做 N 轮语义复核投票,并集采纳双侧锚定的发现。返回采纳数。

    多轮取并集:单轮对细微语义错误命中率实测 ~1/3(模型判断随机性),并集是
    机制性提召回;锚定门不随轮数放宽(精度不掉)。同(slot,kind)跨轮去重,
    发现全部收集完再统一采纳(轮间无顺序效应)。
    契约:复核**绝不新增或自动改写**需求内容;锚定成立 → 软标+双证据留痕;
    correction 只作为模型复核建议记录,由人工裁决。"""
    if not results:
        return 0
    entries = []
    for i, r in enumerate(results, 1):
        subs = "; ".join(str(s.get("text") or "") for s in r.get("sub_items") or [])[:400]
        acc = "; ".join(str(x) for x in r.get("acceptance_criteria") or [])[:600]
        entries.append(
            f"[{i}] verify_slot: {i}\ntitle: {r.get('title', '')}\n描述: {str(r.get('description') or '')[:800]}"
            + (f"\n子项: {subs}" if subs else "")
            + (f"\n验收: {acc}" if acc else "")
            + f"\n引句: {str(r.get('source_quote') or '')[:300]}")
    user = ("【章节原文】\n" + str(section.get("text") or "")
            + "\n\n【已抽需求】\n" + "\n\n".join(entries))
    by_slot = {i: r for i, r in enumerate(results, 1)}
    slots_by_title: dict[str, list[int]] = {}
    for slot, req in by_slot.items():
        title_key = _norm_ws(req.get("title"))
        if title_key:
            slots_by_title.setdefault(title_key, []).append(slot)
    # 收集期:N 轮调用,锚定过滤,(slot,kind) 去重——首个锚定证据胜出
    accepted: dict[tuple[int, str], dict[str, str]] = {}
    for round_no in range(max(1, rounds)):
        try:
            payload = chat(VERIFY_SYSTEM_PROMPT, user)
        except LLMError as exc:  # 单轮失败不吞掉其他轮(首轮失败仍尝试后续轮)
            LOGGER.warning("二遍复核第 %d 轮失败：%s", round_no + 1, exc)
            continue
        findings = payload.get("findings") if isinstance(payload, dict) else None
        if not isinstance(findings, list):
            continue
        for f in findings:
            if not isinstance(f, dict):
                continue
            title_key = _norm_ws(f.get("title"))
            try:
                slot = int(f.get("verify_slot"))
            except (TypeError, ValueError):
                slot = 0
            req = by_slot.get(slot)
            if req is None:
                title_slots = slots_by_title.get(title_key) or []
                if len(title_slots) == 1:
                    slot = title_slots[0]
                    req = by_slot[slot]
            kind = _VERIFY_KINDS.get(str(f.get("kind") or "").strip())
            src_ev = str(f.get("evidence_source") or "").strip()
            prod_ev = str(f.get("evidence_produced") or "").strip()
            if req is None or kind is None or (slot, kind) in accepted:
                continue
            # 双侧锚定:原文侧在章节原文、产出侧在该条目文本,都逐字可定位才算证据
            if not _anchored(src_ev, section.get("text", "")) or not _anchored(prod_ev, _entry_produced_text(req)):
                LOGGER.info("二遍复核发现无锚定证据,丢弃：%s(%s)", str(f.get("title") or "")[:30], kind)
                continue
            accepted[(slot, kind)] = {"src": src_ev, "prod": prod_ev,
                                      "corr": str(f.get("correction") or "").strip()}
    # 采纳期:统一挂标、留证据与建议,不改写自然语言需求
    applied = 0
    for (slot, kind), ev in accepted.items():
        req = by_slot[slot]
        req["suspicion_reasons"] = list(dict.fromkeys(
            list(req.get("suspicion_reasons") or []) + [f"二遍复核:{kind}"]))
        _append_note(req, f"二遍复核（{kind}）：原文「{ev['src'][:80]}」vs 产出「{ev['prod'][:80]}」")
        applied += 1
        corr, prod_ev = ev["corr"], ev["prod"]
        if corr and corr != prod_ev:
            _append_note(req, f"复核建议（未自动改写）：{corr[:160]}")
    return applied


def _finalize_section(section: dict[str, Any], results: list[dict[str, Any]],
                      chat: ChatFn, verify: bool, verify_rounds: int = 1) -> list[dict[str, Any]]:
    results = _fold_test_siblings(results)
    if verify and results:
        try:
            n = _verify_section(section, results, chat, rounds=verify_rounds)
            if n:
                LOGGER.info("二遍复核采纳 %d 处（章节 %s）", n, section.get("section_id"))
        except LLMError as exc:  # 复核失败非致命:保留未复核产出
            LOGGER.warning("二遍语义复核失败（保留未复核产出）：%s", exc)
    return results


def extract_section(section: dict[str, Any], chat: ChatFn, doc_context: str = "",
                    self_check: bool = False,
                    block_info: dict[str, dict[str, Any]] | None = None,
                    self_check_rounds: int | None = None,
                    exemplars: str = "",
                    verify: bool = False,
                    verify_rounds: int | None = None) -> list[dict[str, Any]]:
    """对一个章节调 chat 抽取需求，归一 + 分级漂移护栏。doc_context 注入文档全局背景。

    self_check：抽完**收敛式**查漏补缺——每轮对着当前已抽集重算未覆盖清单再补，直到某轮零新增
    /全覆盖/触顶为止。单趟只能补"第一层可见"的遗漏；有些遗漏要等前几条补进去、覆盖清单缩小后才
    暴露，收敛循环才抓得到。有 block_info 时**定向**（未覆盖 requirement_like 语句作重点核查
    清单）；全覆盖则提前停。无 block_info 回退全量盲查，靠"零新增"收敛。自检失败不致命——保留已抽。
    verify：末尾一次二遍语义复核调用（七类误读清单,双侧锚定采纳,失败非致命）。
    """
    user = build_section_prompt(section)
    prefix_parts: list[str] = []
    if doc_context:
        prefix_parts.append(doc_context)
    if exemplars:
        # 裁决回灌（0714 批次三 E6）：专家已验收范例作模块判定/粒度 few-shot。软背景不进
        # 章节指纹（S3 同理）;漂移基线仍是章节原文——范例里的编码/数值被搬运即照常拦截。
        prefix_parts.append(
            "【专家已验收范例——模块判定与需求粒度基准,仅供对齐;"
            "范例中的数值/编码/内容一律不得搬运进本章节需求】\n" + exemplars)
    if prefix_parts:
        joined = "\n\n".join(prefix_parts)
        user = f"{joined}\n\n---\n以下是待抽取的**当前章节**（需求内容与 source_quote 只能来自这段原文）：\n{user}"
    context_ints = frozenset(extract_ints(doc_context)) if doc_context else frozenset()
    payload = chat(SYSTEM_PROMPT, user)
    raw_reqs = payload.get("requirements") if isinstance(payload, dict) else None
    results = _process_raw_requirements(raw_reqs, section, context_ints) if isinstance(raw_reqs, list) else []
    if not self_check:
        return _finalize_section(section, results, chat, verify,
                             resolve_verify_rounds(verify_rounds))

    # 收敛循环只在**定向模式**（有 block_info，确定性覆盖信号）多轮：每轮针对仍未覆盖的
    # requirement_like 语句补，覆盖清单随之缩小，直到全覆盖/零新增/触顶。有些遗漏要等前几条
    # 补进去、清单缩小后才暴露，单趟抓不到。盲查（无 block_info）保持单趟——无覆盖锚点时反复
    # 追问会诱发过度生成（幻觉压力），得不偿失。
    max_rounds = resolve_self_check_rounds(self_check_rounds) if block_info else 1
    added_total = 0
    for round_no in range(1, max_rounds + 1):
        uncovered = _uncovered_requirement_lines(section, results, block_info)
        # 定向模式下 requirement_like 全覆盖即收敛（无可查项，省一次调用）
        if uncovered is not None and not uncovered and results:
            LOGGER.info("自检收敛（requirement_like 全覆盖，章节 %s，第 %d 轮）",
                        section.get("section_id"), round_no)
            break
        try:
            extra, supplements = critique_section(section, results, chat, doc_context, context_ints,
                                                  focus_lines=uncovered or None)
        except LLMError as exc:  # 自检失败不致命，保留已抽（含前几轮成果）
            LOGGER.warning("完整性自检第 %d 轮失败（保留已抽）：%s", round_no, exc)
            break
        if not extra and not supplements:  # 零新增且零并入 → 已收敛，无需再问
            LOGGER.info("自检收敛（零新增，章节 %s，第 %d 轮）", section.get("section_id"), round_no)
            break
        results = results + extra
        added_total += len(extra)
        LOGGER.info("完整性自检第 %d 轮补充 %d 条、并入 %d 处（章节 %s）",
                    round_no, len(extra), supplements, section.get("section_id"))
        if round_no == max_rounds:  # 触顶仍有新增：记一笔，未必已穷尽（防发散优先）
            LOGGER.info("自检触顶 %d 轮仍有新增（章节 %s，累计补 %d 条）",
                        max_rounds, section.get("section_id"), added_total)
    return _finalize_section(section, results, chat, verify,
                             resolve_verify_rounds(verify_rounds))


# --- 缓存 + 批处理 --------------------------------------------------------

def read_cache(path: Path) -> dict[str, list[dict[str, Any]]]:
    cache: dict[str, list[dict[str, Any]]] = {}
    for row in read_jsonl_recover_torn_tail(path):
        key = str(row.get("fingerprint") or "")
        if key:
            cache[key] = row.get("requirements") or []
    return cache


def append_cache(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("a", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _prepare_requirement_rows(
    rows: list[dict[str, Any]], extraction_fingerprint: str,
) -> list[dict[str, Any]]:
    """Apply deterministic producer metadata before a section becomes visible."""
    from ai_review_actions import ensure_requirement_identity

    prepared = [dict(row) for row in rows if isinstance(row, dict)]
    ensure_domain_labels(prepared)
    for row in prepared:
        ensure_requirement_identity(row, extraction_fingerprint=extraction_fingerprint)
    return prepared


def extract_all(
    sections: list[dict[str, Any]],
    chat: ChatFn,
    *,
    model: str,
    cache_path: Path,
    concurrency: int = 1,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    stats: dict[str, Any] | None = None,
    doc_context: str = "",
    self_check: bool = False,
    self_check_rounds: int | None = None,
    block_info: dict[str, dict[str, Any]] | None = None,
    exemplars: str = "",
    partial_path: Path | None = None,
    run_id: str | None = None,
    partial_input_fingerprint: str = "",
) -> list[dict[str, Any]]:
    """逐章节抽取（缓存优先 + 并发 + 失败降级）。返回扁平需求列表，可复现。

    progress_callback：每完成一章节回调一次（GUI 进度条用，否则界面看着像卡死）。
    逐章节增量写缓存：长跑中途被中断也不丢已完成章节。
    stats：可选 out-dict，回填 total_sections / cached_sections / failed_sections。
    doc_context：文档全局上下文，注入每次抽取并计入指纹（背景变→缓存失效重抽）。
    self_check_rounds：自检收敛轮数上限（None 走默认/env）；计入指纹，改轮数→缓存失效重抽。
    """
    rounds = resolve_self_check_rounds(self_check_rounds) if self_check else 0
    verify = resolve_verify_enabled()
    verify_rounds = resolve_verify_rounds() if verify else 0
    context_key = (hashlib.sha256(doc_context.encode("utf-8")).hexdigest()[:12] if doc_context else "")
    if self_check:  # 自检开/关 + 轮数不同 → 产出不同，计入指纹，缓存不串
        context_key += f"|selfcheck{rounds}"
    if verify:  # 复核开关+版本+轮数 → 产出不同,计入指纹(缓存教训:后处理状态必须进键)
        context_key += f"|verify:{AI_VERIFY_PROMPT_VERSION}:r{verify_rounds}"
    cache = read_cache(cache_path)
    results: list[list[dict[str, Any]] | None] = [None] * len(sections)
    section_done = [False] * len(sections)
    pending: list[tuple[int, dict[str, Any], str]] = []
    for i, section in enumerate(sections):
        fp = section_fingerprint(section, model, context_key)
        hit = cache.get(fp)
        if hit is not None:
            results[i] = _prepare_requirement_rows(hit, fp)
            section_done[i] = True
        else:
            pending.append((i, section, fp))

    total = len(sections)
    cached = total - len(pending)
    completed = cached
    failed = 0
    failed_indexes: list[int] = []

    def publish(*, complete: bool = False) -> None:
        if partial_path is None or not run_id:
            return
        visible: list[dict[str, Any]] = []
        for index, reqs in enumerate(results):
            if section_done[index]:
                visible.extend(reqs or [])
        enforce_normative_framing(visible)
        write_partial_snapshot(
            partial_path,
            run_id=run_id,
            completed=sum(section_done),
            total=total,
            complete=complete,
            rows=visible,
            input_fingerprint=partial_input_fingerprint,
        )

    def emit() -> None:
        if progress_callback is not None and total:
            progress_callback({
                "stage": "ai_extract",
                "completed": completed,
                "total": total,
                "percent": int(round(completed * 100 / total)),
                "model": model,
            })

    publish()  # 新 run 先覆盖旧快照；缓存命中章节可立即审查
    emit()  # 初始进度（含缓存命中数），让界面立刻有反馈

    def work(item: tuple[int, dict[str, Any], str]) -> tuple[int, str, list[dict[str, Any]], bool]:
        idx, section, fp = item
        try:
            return idx, fp, extract_section(section, chat, doc_context, self_check, block_info,
                                            self_check_rounds=rounds or None,
                                            exemplars=exemplars, verify=verify,
                                            verify_rounds=verify_rounds or None), True
        except LLMError as exc:  # 最佳努力：该章节降级、不崩、不缓存（留待重跑）
            LOGGER.warning("AI 抽取章节失败：%s", exc)
            return idx, fp, [], False

    if pending:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
            futures = [executor.submit(work, item) for item in pending]
            for future in as_completed(futures):
                idx, fp, reqs, ok = future.result()
                prepared = _prepare_requirement_rows(reqs, fp)
                results[idx] = prepared
                section_done[idx] = True
                if ok:
                    # 逐章节增量缓存：中途中断不丢已完成章节
                    append_cache(cache_path, [{"fingerprint": fp, "model": model,
                                               "prompt_version": AI_EXTRACT_PROMPT_VERSION,
                                               "requirements": prepared}])
                else:
                    failed += 1
                    failed_indexes.append(idx)
                completed += 1
                publish()
                emit()

    if stats is not None:
        stats["total_sections"] = total
        stats["cached_sections"] = cached
        stats["failed_sections"] = failed
        stats["failed_section_ids"] = [
            str(sections[index].get("section_id") or sections[index].get("heading") or index)
            for index in sorted(failed_indexes)
        ]
        stats["failed_section_block_ids"] = list(dict.fromkeys(
            str(block_id)
            for index in sorted(failed_indexes)
            for block_id in (sections[index].get("block_ids") or [])
            if str(block_id)
        ))

    flat: list[dict[str, Any]] = []
    for reqs in results:
        flat.extend(reqs or [])
    return flat


# --- skill 格式 doc / Excel ----------------------------------------------

def ensure_domain_labels(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """定首要领域（labels[0]，按域分组/出 Excel 都用它），优先级：

    1. LLM 选的 module 在受控词表内 → 直接作首要领域（LLM 读了整段、最懂上下文）。
    2. LLM 明确判 "其它" → 尊重其判断，归 OTHER（不再被 map_labels 误塞进通信协议）。
    3. module 缺失/越界 → 确定性 map_labels 关键词兜底。

    LLM 的自由 labels 始终保留为补充。对缓存结果也生效、不需重调 LLM。
    """
    import requirement_schema as rs
    domain_set = set(METERING_DOMAINS)
    for req in requirements:
        existing = [str(x) for x in (req.get("labels") or [])]
        module = str(req.get("module") or "").strip()
        if module in domain_set or module == OTHER_MODULE:  # LLM 受控分类优先
            req["labels"] = [module] + [label for label in existing if label != module]
            continue
        if any(label in domain_set for label in existing):
            continue
        text = f"{req.get('title', '')} {req.get('description', '')} {req.get('source_quote', '')}"
        domains = [d for d in rs.map_labels(text) if d in domain_set]
        req["labels"] = domains + [label for label in existing if label not in domains]
    return requirements


def build_skill_doc(requirements: list[dict[str, Any]], *, source: str, extracted_at: str,
                    meter_type: str = "multi", target_standards: list[str] | None = None) -> dict[str, Any]:
    """把 AI 抽取的需求装配成公司 skill 格式 doc（REQ-NNN 重编号 + analysis）。"""
    import requirement_schema as rs
    return rs.make_doc(requirements, source=source, extracted_at=extracted_at,
                       meter_type=meter_type, target_standards=target_standards)


# --- 双引擎合并 -----------------------------------------------------------

def merge_requirements(deterministic: list[dict[str, Any]],
                       ai_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """双引擎合并：确定性的**结构**需求（有属性/访问表，OBIS 权威）+ AI 的**行为**需求。

    丢掉确定性里纯散文模板需求（无 threshold_table）——这部分由 AI 行为需求替代，避免模板与
    AI 叙述重复。确定性结构需求逐字保留（OBIS/数字一位不动）。
    """
    structural: list[dict[str, Any]] = []
    for req in deterministic:
        tt = req.get("threshold_table")
        if isinstance(tt, dict) and tt.get("rows"):
            req.setdefault("extracted_by", "deterministic")
            structural.append(req)
    return structural + list(ai_requirements)


def load_or_build_deterministic(out_dir: Path, *, source: str, extracted_at: str) -> list[dict[str, Any]]:
    """取确定性装配需求：优先读已有 dlms_cosem_spec_requirements.json，否则现装配。"""
    doc_path = out_dir / "dlms_cosem_spec_requirements.json"
    if doc_path.exists():
        return json.loads(doc_path.read_text(encoding="utf-8")).get("requirements", [])
    from assemble_spec import assemble
    reviews = out_dir / "llm_review_results.jsonl"
    doc, _ = assemble(out_dir, reviews if reviews.exists() else None,
                      source=source, extracted_at=extracted_at)
    return doc.get("requirements", [])


def apply_ai_decisions(out_dir: Path, ai_requirements: list[dict[str, Any]],
                       stats: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """把专家裁决（批注视图/HTML 导入 → ai_review_states.jsonl）应用到 AI 需求，回流交付物。

    rejected → 剔除（不进研发规格）；module_override → 生效并重定首要领域；
    accepted → status=confirmed；reason → 追加"专家意见"到 notes。无裁决原样保留。
    """
    from ai_review_actions import (
        read_ai_review_states,
        review_state_for_requirement,
        review_state_needs_reconfirmation,
        source_ai_requirement_id,
    )
    states = read_ai_review_states(out_dir)
    applied = 0
    dropped = 0
    reconfirmation = 0
    kept: list[dict[str, Any]] = []
    for req in ai_requirements:
        state = review_state_for_requirement(req, states) if states else None
        if not state:
            kept.append(req)
            continue
        if review_state_needs_reconfirmation(req, state):
            reconfirmation += 1
            kept.append(req)
            continue
        applied += 1
        if state.get("status") == "rejected":
            dropped += 1
            continue
        req = dict(req)
        if state.get("module_override"):
            req["module"] = state["module_override"]  # ensure_domain_labels 会按 module 重排首要领域
        if state.get("status") == "accepted":
            req["status"] = "confirmed"
        if state.get("reason"):
            note = f"专家意见：{state['reason']}"
            req["notes"] = f"{req.get('notes') or ''}；{note}".strip("；")
        kept.append(req)
    if applied:
        ensure_domain_labels(kept)  # module（含 override）重新驱动首要领域
    if stats is not None:
        stats["decisions_applied"] = applied
        stats["rejected_dropped"] = dropped
        stats["decisions_need_reconfirmation"] = reconfirmation
    return kept


def build_merged_doc(out_dir: Path, ai_requirements: list[dict[str, Any]],
                     *, source: str, extracted_at: str,
                     stats: dict[str, Any] | None = None) -> dict[str, Any]:
    """合并 AI 行为需求（先应用专家裁决）+ 确定性结构需求 → skill 格式 doc。"""
    ai_requirements = apply_ai_decisions(out_dir, ai_requirements, stats)
    deterministic = load_or_build_deterministic(out_dir, source=source, extracted_at=extracted_at)
    merged = merge_requirements(deterministic, ai_requirements)
    from meter_profile import infer_meter_profile
    profile = infer_meter_profile(out_dir)
    document = build_skill_doc(
        merged,
        source=source,
        extracted_at=extracted_at,
        meter_type=profile["meter_type"],
        target_standards=profile["target_standards"],
    )
    from input_completeness import attach_input_completeness

    return attach_input_completeness(document, out_dir)


def _write_merged_outputs(out_dir: Path, merged: dict[str, Any]) -> list[str]:
    """写 merged_spec_requirements.json + merged_spec.xlsx，返回写出的文件名。"""
    written: list[str] = []
    merged_json = out_dir / "merged_spec_requirements.json"
    merged_json.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    written.append(merged_json.name)
    try:
        from spec_excel import write_xlsx
        merged_xlsx = out_dir / "merged_spec.xlsx"
        write_xlsx(merged, merged_xlsx)
        written.append(merged_xlsx.name)
    except Exception as exc:  # Excel 失败不阻断 JSON 产出
        LOGGER.warning("合并 Excel 生成失败：%s", exc)
    try:
        written.append(_write_consistency_report(out_dir, merged).name)
    except Exception as exc:  # 一致性报表失败不阻断交付物产出
        LOGGER.warning("全局一致性报表生成失败：%s", exc)
    return written


def _write_consistency_report(out_dir: Path, merged: dict[str, Any]) -> Path:
    """P1 全局一致性 critic：跨章去重 + OBIS 共引 + 覆盖缺口（确定性，非破坏，只标记）。"""
    import merged_consistency
    blocks = read_jsonl(out_dir / "blocks.jsonl")
    # 覆盖分母统一口径（E3b）：剔除标题/引用书目/非正文假阳性,详见 is_coverage_candidate
    req_like = ([b for b in merged_consistency.coverage_denominator_blocks(blocks) if clean_block_text(b)]
                if blocks else None)
    report = merged_consistency.analyze_consistency(
        merged.get("requirements") or [],
        req_like,
        source_blocks=blocks,
        expert_excluded_block_ids=_current_non_requirement_ids(out_dir),
    )
    from input_completeness import attach_input_completeness

    attach_input_completeness(report, out_dir)
    path = out_dir / "consistency_report.json"
    _atomic_write_bytes(
        path,
        (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    dg = report["summary"]["duplicate_groups"]
    vd = report["summary"]["obis_values_differ"]
    if dg or vd:
        LOGGER.info("全局一致性：疑似跨章重复 %d 组、OBIS 数值待核 %d 组（详见 consistency_report.json）", dg, vd)
    return path


def refresh_consistency_report(
    out_dir: Path,
    fallback_requirements: list[dict[str, Any]],
) -> Path:
    """Refresh deterministic consistency output after expert-only coverage triage."""
    root = Path(out_dir).expanduser().resolve()
    merged: dict[str, Any] = {"requirements": fallback_requirements}
    merged_path = root / "merged_spec_requirements.json"
    if merged_path.exists():
        try:
            candidate = json.loads(merged_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            candidate = None
        if isinstance(candidate, dict) and isinstance(candidate.get("requirements"), list):
            merged = candidate
    return _write_consistency_report(root, merged)


def rebuild_merged_spec(out_dir: Path) -> dict[str, Any]:
    """免 LLM 重建交付物：读已抽 ai_requirements.jsonl + 最新裁决，重合并重写 json/xlsx。

    批注视图裁决、导入裁决 JSON 后调用——专家的接受/拒绝/改模块即时反映到 merged_spec。
    """
    out_dir = Path(out_dir).expanduser().resolve()
    ai_requirements = read_jsonl(out_dir / AI_REQUIREMENTS)
    effective_requirements = apply_ai_decisions(out_dir, ai_requirements)
    write_compliance_requirements(out_dir, effective_requirements)
    stats: dict[str, Any] = {}
    merged = build_merged_doc(out_dir, ai_requirements, source=out_dir.name,
                              extracted_at=datetime.datetime.now().isoformat(timespec="seconds"),
                              stats=stats)
    written = _write_merged_outputs(out_dir, merged)
    written.append(COMPLIANCE_REQUIREMENTS)
    try:
        # 裁决学习回路：每次裁决回流后刷新 override 复盘报告（确定性，失败不阻断交付物）
        import review_insights
        review_insights.write_insights(out_dir)
        written.append(review_insights.INSIGHTS_JSON)
    except Exception as exc:  # pragma: no cover - 复盘失败不影响交付物
        LOGGER.warning("裁决复盘报告生成失败（忽略）：%s", exc)
    return {
        "written": written,
        "total": merged["analysis"]["total_count"],
        "incomplete_inputs": bool(merged.get("incomplete_inputs")),
        "input_completeness": dict(merged.get("input_completeness") or {}),
        **stats,
    }


# --- 主入口 ---------------------------------------------------------------

def config_for_route(route: str | None, pipeline_path: Path = DEFAULT_PIPELINE_PATH) -> LLMClientConfig | None:
    pipeline = load_review_pipeline(pipeline_path)
    route_name = resolve_route_name(pipeline, route)
    if route_name != "openai_compatible":
        return None
    # 复用 review 同一套 env 覆盖：GUI 在设置面板配的端点经 RATOMIZER_LLM_* 覆盖 yaml
    payload = apply_llm_environment_overrides(dict(pipeline.model_routes.get("openai_compatible") or {}))
    return llm_config_from_route(payload)


def run_ai_extract(out_dir: Path, *, route: str | None, merge_chars: int = DEFAULT_MERGE_CHARS,
                   write_doc: bool = False, merge_deterministic: bool = False,
                   pipeline_path: Path = DEFAULT_PIPELINE_PATH,
                   progress_callback: Callable[[dict[str, Any]], None] | None = None,
                   concurrency: int | None = None,
                   self_check: bool | None = None,
                   limit_sections: int | None = None,
                   sample_ratio: float | None = None,
                   unit_mode: str | None = None) -> dict[str, Any]:
    """读 blocks → 章节合并 → AI 抽取 → 写 ai_requirements.jsonl（可选 skill doc + Excel + 双引擎合并）。

    试抽模式（分钟级出质量样本，不等全量）：limit_sections=固定 N 章；sample_ratio=按比例
    （如 0.2 = 全文 1/5，随文档规模自适应——「测试运行」用这个，不写死条数）。两者都给时固定数优先。
    """
    from omission_actions import extraction_operation_lock

    out_dir = out_dir.expanduser().resolve()
    with extraction_operation_lock(out_dir, operation="full"):
        previous_partial = read_partial_snapshot(out_dir / AI_REQUIREMENTS_PARTIAL)
        previous_run_id = str((previous_partial or {}).get("run_id") or "")
        attempt_input_fingerprint = extraction_input_fingerprint(out_dir)
        try:
            return _run_ai_extract_locked(
                out_dir,
                route=route,
                merge_chars=merge_chars,
                write_doc=write_doc,
                merge_deterministic=merge_deterministic,
                pipeline_path=pipeline_path,
                progress_callback=progress_callback,
                concurrency=concurrency,
                self_check=self_check,
                limit_sections=limit_sections,
                sample_ratio=sample_ratio,
                unit_mode=unit_mode,
            )
        except Exception as exc:
            partial_path = out_dir / AI_REQUIREMENTS_PARTIAL
            partial = read_partial_snapshot(partial_path)
            try:
                if (partial
                        and str(partial.get("run_id") or "") != previous_run_id):
                    partial_input = str(partial.get("input_fingerprint") or "")
                    write_partial_snapshot(
                        partial_path,
                        run_id=str(partial["run_id"]),
                        completed=int(partial.get("completed") or 0),
                        total=int(partial.get("total") or 0),
                        complete=False,
                        failed=True,
                        error=str(exc),
                        rows=list(partial.get("rows") or []),
                        input_fingerprint=partial_input,
                    )
                elif attempt_input_fingerprint:
                    # Preprocessing can fail before _run_ai_extract_locked publishes its
                    # initial snapshot. Create a distinct terminal generation instead of
                    # mutating a completed snapshot from an earlier run.
                    write_partial_snapshot(
                        partial_path,
                        run_id=uuid.uuid4().hex,
                        completed=0,
                        total=0,
                        complete=False,
                        failed=True,
                        error=str(exc),
                        rows=[],
                        input_fingerprint=attempt_input_fingerprint,
                    )
            except OSError:
                LOGGER.exception("AI partial 失败终态写入失败")
            raise


def _run_ai_extract_locked(out_dir: Path, *, route: str | None,
                           merge_chars: int = DEFAULT_MERGE_CHARS,
                           write_doc: bool = False, merge_deterministic: bool = False,
                           pipeline_path: Path = DEFAULT_PIPELINE_PATH,
                           progress_callback: Callable[[dict[str, Any]], None] | None = None,
                           concurrency: int | None = None,
                           self_check: bool | None = None,
                           limit_sections: int | None = None,
                           sample_ratio: float | None = None,
                           unit_mode: str | None = None) -> dict[str, Any]:
    """Implementation body for :func:`run_ai_extract` under the operation lease."""
    try:
        from claim_artifacts import load_committed_shadow

        previous_claim_snapshot = load_committed_shadow(out_dir)
    except Exception:
        previous_claim_snapshot = None
    catalog_scope = (
        "sample"
        if (limit_sections is not None and limit_sections > 0)
        or (sample_ratio is not None and 0 < sample_ratio < 1)
        else "full"
    )
    claim_catalog_build: dict[str, Any] | None = None
    claim_shadow_error = ""
    try:
        from claim_artifacts import CLAIM_GENERATION_META, publish_catalog_probe
        from claim_catalog import build_catalog_from_directory

        claim_catalog_build = build_catalog_from_directory(out_dir, scope=catalog_scope)
        if (
            previous_claim_snapshot is None
            and not (out_dir / CLAIM_GENERATION_META).is_file()
        ):
            publish_catalog_probe(out_dir, claim_catalog_build)
    except Exception as exc:  # Shadow probe must not change extraction success semantics.
        claim_shadow_error = f"catalog_probe_failed:{type(exc).__name__}:{exc}"
        LOGGER.warning("claim catalog probe failed; AI extraction continues: %s", exc)

    blocks = read_jsonl(out_dir / "blocks.jsonl")
    blocks = body_blocks(blocks)   # 封面/目录区不进抽取（EN 16314：目录条目被抽成 11 条空壳需求）
    # table-structure-v2：权威 row/cell 身份进章节装配（无文件时保持旧行为）
    try:
        table_items = read_jsonl(out_dir / "table_items.jsonl")
    except (OSError, ValueError):
        table_items = []
    try:
        table_cell_items = read_jsonl(out_dir / "table_cell_items.jsonl")
    except (OSError, ValueError):
        table_cell_items = []
    resolved_mode = (unit_mode or os.environ.get(UNIT_MODE_ENV) or "clause").strip().lower()
    if resolved_mode not in ("clause", "chapter"):
        resolved_mode = "clause"
    all_sections = merge_sections(
        assemble_sections(blocks, table_items=table_items, table_cell_items=table_cell_items),
        target_chars=merge_chars,
        unit_mode=resolved_mode,
    )
    resolve_section_refs(all_sections)  # 跨章节引用注入（须在采样前，被引条款可能不在样本里）
    attach_term_definitions(all_sections, collect_term_entries(all_sections))  # 术语定向注入
    _annotate_annex_scopes(all_sections)  # 资料性附录区段标注（跨单元状态机,须在采样前）
    if not limit_sections and sample_ratio and 0 < sample_ratio < 1:
        limit_sections = max(1, round(len(all_sections) * sample_ratio))
    sections, sampled = sample_sections(all_sections, limit_sections)
    if sampled:
        LOGGER.info("试抽模式：全文 %d 章均匀抽样 %d 章（质量指标只对样本计算）",
                    len(all_sections), len(sections))

    run_id = uuid.uuid4().hex
    partial_path = out_dir / AI_REQUIREMENTS_PARTIAL
    input_fingerprint = extraction_input_fingerprint(out_dir)
    write_partial_snapshot(
        partial_path,
        run_id=run_id,
        completed=0,
        total=len(sections),
        complete=False,
        rows=[],
        input_fingerprint=input_fingerprint,
    )

    config = config_for_route(route, pipeline_path)
    if config is not None:
        from llm_client import apply_min_tokens

        verifier_config = apply_min_tokens(config, "extract")
    else:
        verifier_config = None
    verifier_requested = verifier_config is not None and resolve_claim_shadow_verify()
    verifier_budget = claim_shadow_verifier_budget() if verifier_requested else None
    verifier_enabled = verifier_requested and verifier_budget is not None
    if verifier_requested and verifier_budget is None:
        LOGGER.warning(
            "claim shadow verifier requested but no positive call/token budget was authorized"
        )
    verifier_rounds = resolve_claim_shadow_verify_rounds()
    from claim_ledger import semantic_verifier_runtime
    budget_snapshot = verifier_budget.snapshot() if verifier_budget is not None else {}
    verifier_runtime = semantic_verifier_runtime(
        route_mode="stub" if config is None else "llm",
        enabled=verifier_enabled,
        rounds=verifier_rounds,
        config=verifier_config,
        policy_source="environment",
        budget_policy_version=LLMRequestBudget.VERSION,
        max_calls=int(budget_snapshot.get("max_calls") or 0),
        max_total_tokens=int(budget_snapshot.get("max_tokens") or 0),
    )
    reusable_claim_groups = reusable_claim_groups_for_runtime(
        previous_claim_snapshot,
        verifier_runtime,
    )
    reusable_claim_negatives = reusable_claim_negatives_for_runtime(
        previous_claim_snapshot,
        verifier_runtime,
    )
    no_ledger_baseline_cost: dict[str, Any] = {
        "call_count": 0,
        "failed_call_count": 0,
        "total_tokens": 0,
        "usage_complete": config is not None,
    }
    baseline_cost_lock = Lock()
    semantic_verifier = None
    semantic_negative_proposer = None
    semantic_negative_verifier = None
    written: list[str] = []
    code_flagged = 0
    int_flagged = 0
    failed_sections = 0
    extract_stats: dict[str, Any] = {}
    model: str | None = None
    result_quality: dict[str, Any] | None = None
    normative_framing_stats = {
        "rewritten_leaf_count": 0,
        "rewritten_requirement_count": 0,
    }

    if config is not None:
        from llm_client import apply_min_tokens

        config = apply_min_tokens(
            config,
            "extract-chapter" if resolved_mode == "chapter" else "extract",
        )
    resolved_self_check = resolve_self_check(self_check)
    resolved_self_check_rounds = (
        resolve_self_check_rounds() if resolved_self_check else 0
    )
    resolved_verify_enabled = resolve_verify_enabled()
    resolved_verify_rounds = (
        resolve_verify_rounds() if resolved_verify_enabled else 0
    )
    resolved_concurrency = resolve_concurrency(concurrency)
    no_ledger_baseline_cost.update(no_ledger_baseline_lineage(
        input_fingerprint=input_fingerprint,
        route_mode="stub" if config is None else "llm",
        config=config,
        unit_mode=resolved_mode,
        concurrency=resolved_concurrency,
        merge_chars=merge_chars,
        limit_sections=limit_sections,
        sample_ratio=sample_ratio,
        scope=catalog_scope,
        self_check=resolved_self_check,
        self_check_rounds=resolved_self_check_rounds,
        verify_enabled=resolved_verify_enabled,
        verify_rounds=resolved_verify_rounds,
    ))
    no_ledger_baseline_cost["lineage_match"] = True

    if config is None:
        # stub 路由：不调 LLM，AI 行为需求为空——但确定性引擎（双引擎之一）仍照常
        # 产出结构规格，所以不在此 early-return，继续走 write_doc / merge_deterministic。
        requirements: list[dict[str, Any]] = []
        route_label = "stub"
        # 补抽补丁是专家已确认的独立审计资产，不是本轮 LLM 产出——stub 路由也必须
        # 重放，否则正式文件会被空结果静默覆盖（补丁日志虽可重放，其间批注丢行）。
        from omission_actions import apply_supplement_patches
        requirements = apply_supplement_patches(out_dir, requirements)
        ensure_domain_labels(requirements)
        normative_framing_stats = enforce_normative_framing(requirements)
    else:
        def chat(system: str, user: str) -> dict[str, Any]:
            try:
                data, meta = _chat_json_accounted(config, system, user)
            except Exception:
                with baseline_cost_lock:
                    no_ledger_baseline_cost["usage_complete"] = False
                raise
            usage = meta.get("usage") if isinstance(meta, dict) else None
            with baseline_cost_lock:
                no_ledger_baseline_cost["call_count"] += max(
                    1, int((meta or {}).get("call_count") or 1)
                )
                no_ledger_baseline_cost["failed_call_count"] += max(
                    0, int((meta or {}).get("failed_call_count") or 0)
                )
                no_ledger_baseline_cost["total_tokens"] += max(
                    0, int((usage or {}).get("total_tokens") or 0)
                )
                if not isinstance(meta, dict) or meta.get("usage_complete") is not True:
                    no_ledger_baseline_cost["usage_complete"] = False
            return data

        if verifier_enabled:
            from claim_ledger import (
                make_semantic_coverage_verifier,
                make_semantic_negative_proposer,
                make_semantic_negative_verifier,
            )

            accounted_chat = lambda system, user: _chat_json_accounted(
                verifier_config,
                system,
                user,
                request_budget=verifier_budget,
            )
            semantic_verifier = make_semantic_coverage_verifier(
                accounted_chat,
                rounds=verifier_rounds,
            )
            semantic_negative_proposer = make_semantic_negative_proposer(accounted_chat)
            semantic_negative_verifier = make_semantic_negative_verifier(
                accounted_chat,
                rounds=verifier_rounds,
            )

        doc_context = build_doc_context(out_dir, blocks)  # 上下文工程：文档全局背景注入每次抽取
        term_map = ensure_term_map(out_dir, chat, collect_term_entries(all_sections))
        if term_map:   # 中英术语对照：全文统一译法（折进 context_key → 指纹自动失效）
            doc_context = f"{doc_context}\n{term_map}" if doc_context else term_map
        block_info = {str(b.get("block_id")): b for b in blocks if b.get("block_id")}  # 定向自检/覆盖率用
        # 裁决回灌（E6）：样本库 few-shot 注入抽取（软背景不进指纹,加载失败零注入不阻断）
        try:
            from adjudication_bank import load_bank, resolve_bank_path
            bank_exemplars = render_extract_exemplars(load_bank(resolve_bank_path()))
        except Exception as exc:  # pragma: no cover - 样本库异常不影响抽取
            LOGGER.warning("裁决样本库加载失败（抽取零注入）：%s", exc)
            bank_exemplars = ""
        requirements = extract_all(sections, chat, model=config.model,
                                   cache_path=out_dir / AI_EXTRACT_CACHE,
                                   concurrency=resolved_concurrency,
                                   progress_callback=progress_callback,
                                   stats=extract_stats,
                                   doc_context=doc_context,
                                   self_check=resolved_self_check,
                                   self_check_rounds=resolved_self_check_rounds,
                                   block_info=block_info,
                                   exemplars=bank_exemplars,
                                   partial_path=partial_path,
                                   run_id=run_id,
                                   partial_input_fingerprint=input_fingerprint)
        # 定点补抽补丁是独立审计层。全量抽取以新鲜基础结果为准，只重放来源与
        # 策略仍匹配的补丁，防下一次全量运行静默覆盖专家已确认的补漏。
        from omission_actions import apply_supplement_patches
        requirements = apply_supplement_patches(out_dir, requirements)
        ensure_domain_labels(requirements)  # 确定性补领域标签，保证按域 Excel 不塌进未分类
        normative_framing_stats = enforce_normative_framing(requirements)
        code_flagged = sum(1 for r in requirements if "结构漂移已拦截" in (r.get("notes") or ""))
        int_flagged = sum(1 for r in requirements if "数字漂移" in (r.get("notes") or ""))
        failed_sections = int(extract_stats.get("failed_sections", 0))
        model = config.model
        route_label = "openai_compatible"

        from requirement_record import validate_rows
        validate_rows(requirements, where=AI_REQUIREMENTS)  # 行契约告警（F2，不拦截）

        # 质量报表：这轮抽取的可核指标（覆盖率/漂移/自检补充/模块分布），落盘供追溯。
        # 覆盖分母统一口径（E3b）：与 consistency/批注/澄清同用同一匹配底座。
        sampled_ids = (
            {str(bid) for section in sections for bid in (section.get("block_ids") or [])}
            if sampled else None
        )
        coverage_fields = _coverage_quality_fields(
            requirements,
            block_info.values(),
            allowed_block_ids=sampled_ids,
            expert_excluded_block_ids=_current_non_requirement_ids(out_dir),
        )
        by_module: dict[str, int] = {}
        for r in requirements:
            m = str((r.get("labels") or ["未分模块"])[0])
            by_module[m] = by_module.get(m, 0) + 1
        quality = {
            "sections": len(sections),
            "sections_total": len(sections),
            "requirements": len(requirements),
            "failed_sections": int(extract_stats.get("failed_sections", 0)),
            "failed_section_ids": list(extract_stats.get("failed_section_ids") or []),
            "failed_section_block_ids": list(
                extract_stats.get("failed_section_block_ids") or []
            ),
            "cached_sections": int(extract_stats.get("cached_sections", 0)),
            "self_check_added": sum(1 for r in requirements if r.get("self_check_added")),
            "code_drift_flagged": code_flagged,
            "int_drift_flagged": int_flagged,
            "normative_framing_rewritten_leaf_count": normative_framing_stats[
                "rewritten_leaf_count"
            ],
            "normative_framing_rewritten_requirement_count": normative_framing_stats[
                "rewritten_requirement_count"
            ],
            "by_module": dict(sorted(by_module.items(), key=lambda x: -x[1])),
            "no_ledger_baseline_cost": dict(no_ledger_baseline_cost),
            **coverage_fields,
        }
        from requirement_record import provenance
        quality["provenance"] = provenance("ai_extract", AI_EXTRACT_PROMPT_VERSION)
        quality_path = out_dir / "ai_extract_quality.json"
        quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(quality_path.name)
        result_quality = quality

    # 正式产物与 complete 快照都采用同目录原子替换。先发布正式文件，再把 partial
    # 标成 complete，读侧不会观察到“运行完成但最终文件仍是旧内容”的窗口。
    _downgrade_cross_block_verbatim(requirements, blocks)   # 跨块逐字硬标→软标（写盘前统一过一遍）
    requirements = _supplement_uncovered_compliance(requirements, blocks)   # 合规漏抽兜底,进 jsonl+澄清
    requirements = _supplement_parameter_table_rows(requirements, blocks)   # 参数表逐行确定性展开,LLM 未覆盖行进澄清
    requirements = _merge_llm_into_deterministic_rows(requirements)   # 封堵二:同行 LLM 叙述并入确定性展开行,免双份
    _assert_source_references(requirements, table_items, table_cell_items)   # 发布前断言:row/cell 引用真实存在
    target = out_dir / AI_REQUIREMENTS
    atomic_write_jsonl(target, requirements)
    written.append(target.name)
    compliance_payload = write_compliance_requirements(out_dir, requirements)
    written.append(COMPLIANCE_REQUIREMENTS)
    write_ai_requirements_metadata(
        out_dir,
        input_fingerprint=input_fingerprint,
        run_id=run_id,
        failed_sections=failed_sections,
        failed_section_ids=list(extract_stats.get("failed_section_ids") or []),
        failed_section_block_ids=list(
            extract_stats.get("failed_section_block_ids") or []
        ),
        no_ledger_baseline_cost=no_ledger_baseline_cost,
    )
    written.append(AI_REQUIREMENTS_META)

    claim_shadow_summary: dict[str, Any]
    if claim_catalog_build is None:
        claim_shadow_summary = {"status": "failed", "error": claim_shadow_error}
    else:
        try:
            from claim_artifacts import (
                CLAIM_CATALOG,
                CLAIM_CATALOG_META,
                CLAIM_COVERAGE_GROUPS,
                CLAIM_EFFECTIVE_LEDGER,
                CLAIM_EFFECTIVE_HEALTH,
                CLAIM_EFFECTIVE_META,
                CLAIM_GENERATION_META,
                CLAIM_LEDGER,
                CLAIM_QUEUE_PROPOSALS,
                CLAIM_REVIEW_EVENTS,
                CLAIM_SHADOW_METRICS,
                CLAIM_VERIFIER_ATTEMPTS,
                claim_verifier_attempt_scope,
                file_sha256,
            )
            from ai_review_actions import read_ai_review_states
            from claim_ledger import b_track_authority_state, publish_b_track_shadow

            extraction_status = "partial" if failed_sections else "success"
            requirements_sha256 = file_sha256(target)
            target_state = b_track_authority_state(
                requirements,
                read_ai_review_states(out_dir),
            )
            with claim_verifier_attempt_scope(
                out_dir,
                attempt_kind="cold",
                attempt_request_id=run_id,
                requirements_request_id=run_id,
                failure_context={
                    "catalog_build": claim_catalog_build,
                    "target_generation_id": target_state["target_generation_id"],
                    "requirements_sha256": requirements_sha256,
                    "verifier_runtime": verifier_runtime,
                    "baseline_cost": no_ledger_baseline_cost,
                    "verifier_budget": verifier_budget,
                },
            ):
                published = publish_b_track_shadow(
                    out_dir,
                    run_id=run_id,
                    route_mode="stub" if route_label == "stub" else "llm",
                    extraction_status=extraction_status,
                    catalog_build=claim_catalog_build,
                    requirements=requirements,
                    scope=catalog_scope,
                    controlled_term_aliases=load_controlled_term_aliases(out_dir),
                    failed_section_block_ids=list(
                        extract_stats.get("failed_section_block_ids") or []
                    ),
                    semantic_verifier=semantic_verifier,
                    semantic_negative_proposer=semantic_negative_proposer,
                    semantic_negative_verifier=semantic_negative_verifier,
                    reusable_groups=reusable_claim_groups,
                    reusable_negatives=reusable_claim_negatives,
                    baseline_cost=no_ledger_baseline_cost,
                    verifier_runtime=verifier_runtime,
                    verifier_budget=verifier_budget,
                )
            shadow = dict(published.get("shadow") or {})
            shadow_meta = dict(shadow.get("meta") or {})
            claim_shadow_summary = {
                "status": "published",
                "accounting_status": shadow_meta.get("accounting_status"),
                "resolution_status": shadow_meta.get("resolution_status"),
                "metrics": shadow.get("metrics") or {},
            }
            effective_fold_error = ""
            try:
                from claim_review_actions import fold_effective_ledger

                fold_effective_ledger(
                    out_dir,
                    actor_trigger="ai-extract-publish",
                )
            except Exception as exc:
                effective_fold_error = f"{type(exc).__name__}: {exc}"[:300]
                LOGGER.warning(
                    "claim shadow base published but effective fold lagged: %s",
                    effective_fold_error,
                )
            try:
                if effective_fold_error:
                    raise RuntimeError(effective_fold_error)
                from claim_views import build_claim_view

                effective_view = build_claim_view(out_dir, "metrics")
                effective_metrics = dict(
                    effective_view.get("effective_metrics") or {}
                )
                claim_shadow_summary.update({
                    "document_ready": effective_view.get("document_ready"),
                    "effective_fresh": bool(
                        effective_view.get("effective_fresh")
                    ),
                    "open_claim_count": effective_metrics.get(
                        "uncertain_count"
                    ),
                })
            except Exception as exc:
                claim_shadow_summary.update({
                    "document_ready": None,
                    "effective_fresh": False,
                    "open_claim_count": None,
                    "effective_error": str(exc)[:300],
                })
            for name in (
                CLAIM_CATALOG,
                CLAIM_CATALOG_META,
                CLAIM_COVERAGE_GROUPS,
                CLAIM_LEDGER,
                CLAIM_EFFECTIVE_LEDGER,
                CLAIM_QUEUE_PROPOSALS,
                CLAIM_SHADOW_METRICS,
                CLAIM_GENERATION_META,
                CLAIM_EFFECTIVE_META,
                CLAIM_EFFECTIVE_HEALTH,
                CLAIM_REVIEW_EVENTS,
                CLAIM_VERIFIER_ATTEMPTS,
            ):
                if (out_dir / name).is_file() and name not in written:
                    written.append(name)
        except Exception as exc:  # Shadow failure never turns a good extraction into a failed section.
            claim_shadow_error = f"shadow_publish_failed:{type(exc).__name__}:{exc}"
            claim_shadow_summary = {"status": "failed", "error": claim_shadow_error}
            LOGGER.warning("claim shadow ledger failed; primary requirements remain valid: %s", exc)

    write_partial_snapshot(
        partial_path,
        run_id=run_id,
        completed=len(sections),
        total=len(sections),
        complete=True,
        failed=bool(failed_sections),
        error=(f"{failed_sections} section(s) failed" if failed_sections else ""),
        rows=requirements,
        input_fingerprint=input_fingerprint,
    )

    result: dict[str, Any] = {"route": route_label, "sections": len(sections),
              "requirements": len(requirements), "code_drift_flagged": code_flagged,
              "int_drift_flagged": int_flagged, "failed_sections": failed_sections,
              "normative_framing": normative_framing_stats,
              "failed_section_ids": list(extract_stats.get("failed_section_ids") or []),
              "failed_section_block_ids": list(
                  extract_stats.get("failed_section_block_ids") or []
              ),
              "compliance_requirements": int(compliance_payload.get("count") or 0),
              "written": written, "run_id": run_id,
              "claim_shadow": claim_shadow_summary}
    if sampled:
        result["sampled"] = {"sections": len(sections), "total_sections": len(all_sections)}
    if model:
        result["model"] = model
    if config is None:
        result["note"] = "stub 路由：未调 LLM（AI 行为需求为空，仅产确定性结构规格）"
    elif failed_sections:
        result["note"] = (f"{failed_sections} 个章节 LLM 调用失败（端点/Key/超时）——"
                          "已按可用结果产出，请用「测试连接」确认配置后重跑")
    if result_quality is not None:
        result["quality"] = result_quality

    if write_doc:
        from meter_profile import infer_meter_profile
        profile = infer_meter_profile(out_dir)
        doc = build_skill_doc(requirements, source=out_dir.name,
                              extracted_at=datetime.datetime.now().isoformat(timespec="seconds"),
                              meter_type=profile["meter_type"], target_standards=profile["target_standards"])
        doc_path = out_dir / "ai_requirements_doc.json"
        doc_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(doc_path.name)
        try:
            from spec_excel import write_xlsx
            xlsx_path = out_dir / "ai_requirements.xlsx"
            write_xlsx(doc, xlsx_path)
            written.append(xlsx_path.name)
        except Exception as exc:  # Excel 失败不阻断 JSON 产出
            LOGGER.warning("AI 需求 Excel 生成失败：%s", exc)
        result["analysis"] = doc.get("analysis", {}).get("by_priority", {})

    if merge_deterministic:
        merge_stats: dict[str, Any] = {}
        merged = build_merged_doc(out_dir, requirements, source=out_dir.name,
                                  extracted_at=datetime.datetime.now().isoformat(timespec="seconds"),
                                  stats=merge_stats)
        written.extend(_write_merged_outputs(out_dir, merged))
        ai_in_merged = len(requirements) - int(merge_stats.get("rejected_dropped", 0))
        result["merged"] = {"total": merged["analysis"]["total_count"],
                            "ai_behavioral": ai_in_merged,
                            "deterministic_structural": merged["analysis"]["total_count"] - ai_in_merged,
                            **merge_stats}
        # 一致性闭环：报表摘要随任务载荷透出（GUI 跑完消息 + 批注视图标记都吃它，不再只写不读）
        try:
            report = json.loads((out_dir / "consistency_report.json").read_text(encoding="utf-8"))
            result["consistency"] = report.get("summary", {})
        except (OSError, json.JSONDecodeError):
            pass

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI-first requirement extraction.")
    parser.add_argument("--out", type=Path, required=True, help="Atomizer output directory (含 blocks.jsonl)")
    parser.add_argument("--route", default=None, help="stub | openai_compatible")
    parser.add_argument("--limit-sections", type=int, default=0,
                        help="试抽模式：均匀抽样 N 章快速看质量（0=全量）")
    parser.add_argument("--merge-chars", type=int, default=DEFAULT_MERGE_CHARS, help="章节合并目标字数")
    parser.add_argument("--doc", action="store_true", help="同时产 skill 格式 doc + Excel（仅 AI 需求）")
    parser.add_argument("--merge", action="store_true", help="双引擎合并：AI 行为 + 确定性结构 → merged_spec")
    parser.add_argument("--concurrency", type=int, default=None,
                        help=f"LLM 并发章节数（默认 {DEFAULT_CONCURRENCY}，或环境变量 {CONCURRENCY_ENV}；夹在 1..{MAX_CONCURRENCY}）")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_ai_extract(args.out, route=args.route, merge_chars=args.merge_chars,
                            write_doc=args.doc, merge_deterministic=args.merge,
                            concurrency=args.concurrency,
                            limit_sections=args.limit_sections or None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
