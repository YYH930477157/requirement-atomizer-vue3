"""Prompt registry (WS-D1): central catalog of all LLM prompt / guard / cache versions.

Each entry carries a stable ``id``, the current pinned ``version`` string, the
``owner_module`` where the constant lives, and a one-line ``purpose``.

The registry is the single source of truth for prompt governance.  The
accompanying lint (``lint_source`` / ``lint_directory``) scans Python source for
prompt-like version constants and fails if any value is not registered.  Tests
must prove the lint catches a deliberately unregistered prompt.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


PROMPT_REGISTRY_VERSION = "prompt-registry-v1"

# Central catalog.  Keep sorted by id for stable diffs.
# The version strings are the *current* pinned values; bump the registry entry
# when the owning module bumps its constant, and never leave stale entries.
PROMPT_REGISTRY: list[dict[str, str]] = [
    # Core extraction / verification prompts and guards
    {"id": "ai-extract", "version": "ai-extract-v25", "owner_module": "ai_extract",
     "purpose": "Main AI extraction prompt for clause-level requirements"},
    {"id": "ai-verify", "version": "ai-verify-v4", "owner_module": "ai_extract",
     "purpose": "Second-pass semantic verification prompt"},
    {"id": "extract-guards", "version": "guards-v23", "owner_module": "ai_extract",
     "purpose": "Extraction anti-drift guard version pinned into cache/lineage"},
    {"id": "ai-normative-framing", "version": "ai-normative-framing-v2", "owner_module": "ai_extract",
     "purpose": "Target obligation framing grammar pinned into extract/verify lineage"},
    {"id": "claim-focus-critique", "version": "claim-focus-critique-v3", "owner_module": "ai_extract",
     "purpose": "Claim-targeted re-extraction critique prompt"},

    # Requirements analysis enrichment
    {"id": "analyze-llm", "version": "analyze-llm-v8", "owner_module": "requirements_analysis",
     "purpose": "Requirements analysis LLM enrichment prompt"},
    {"id": "analyze-unfounded", "version": "analyze-unfounded-v4", "owner_module": "requirements_analysis",
     "purpose": "Unfounded-field downgrade rule version pinned into analyze cache"},
    {"id": "analyze-rules", "version": "analyze-rules-v1", "owner_module": "requirements_analysis_rules",
     "purpose": "Ownership/compliance deterministic rule version"},

    # LLM review / tool-loop
    {"id": "m2-review", "version": "m2-review-v3", "owner_module": "llm_pipeline",
     "purpose": "M2-style detailed LLM review prompt"},
    {"id": "m2-review-batch", "version": "m2-review-v4-batch", "owner_module": "llm_pipeline",
     "purpose": "Opt-in single-shot batch review prompt"},
    {"id": "llm-review-cache", "version": "llm-review-cache-v7", "owner_module": "llm_pipeline",
     "purpose": "Review cache fingerprint (pins prompt/tools/schema versions)"},
    {"id": "review-tools", "version": "review-tools-v5", "owner_module": "review_tools",
     "purpose": "Tool-using reviewer tools schema version"},

    # Assembly / spec enrichment
    {"id": "enrich", "version": "enrich-v4", "owner_module": "spec_enrich",
     "purpose": "Assembly description enrichment prompt"},
    {"id": "enrich-guards", "version": "enrich-guards-v1", "owner_module": "spec_enrich",
     "purpose": "Enrichment anti-drift guard version"},

    # Functional-extract direct path
    # v4（2026-08-18 10% 诊断）：硬约束⑥保真落数——引用号（Table N/图号/条款号/标准号）
    # 与数值必须原样进叙述字段（flash 意译丢表号 → preservation 假 blocking）。
    # v5（2026-09-06 证据收口）：表格参数行的字段名/值/单位/适用条件进所属需求
    # data_constraints；表头/示例/上下文数字仅在条款定义为约束时进入。同一 bump
    # 顺带覆盖 09-07 轨道分离提交的粒度契约提示词改动（dc34f25 改文本未 bump）。
    {"id": "functional-extract", "version": "functional-extract-prompt-v5", "owner_module": "functional_extract",
     "purpose": "Functional requirement direct extraction prompt"},
    {"id": "functional-extract-guards", "version": "functional-extract-guards-v6", "owner_module": "functional_extract",
     "purpose": "Functional extract anti-drift guard version"},
    # 四轮复审 P2：守恒模型版本显式登记——守恒载荷语义演进（如 cross_script_review
    # 携带文本身份）随 registry/指纹/producer stamp/claim lineage 四处同步失效。
    # v5（2026-08-27 审查修复）：同文本多表格块按委托块数剔除出现位置（replace-all
    # 会静默剥掉非委托块内容）。
    # v6（2026-08-30 门禁复盘）：义务基线剔除内容词<2 的 lead-in/空壳碎片单元
    # （_is_fragment_obligation_unit），剔除量在 conservation 报告 fragment_units_excluded 审计。
    # v7（2026-08-31）：绑定检查 reason 1 承认「引句逐字锚定声明条款」为本地锚
    # （义务覆盖检查 2 不动；放行后 reason 2 不再被短路）。
    # v8（2026-09-07 用户裁定）：reason 2 豁免逐字重复——被覆盖义务句逐字出现在
    # 声明条款基线文本内判疑似误报豁免（covered_clause_text_dup_exemptions 审计，
    # 不影响 ok）；任一被覆盖句不在声明条款内照旧 blocking。
    {"id": "functional-extract-conservation", "version": "functional-conservation-obligation-evidence-v8",
     "owner_module": "functional_extract",
     "purpose": "Functional extract obligation/evidence conservation model version"},

    # partial export（2026-09-01，用户拍板政策反转）：守恒待核行级标记算法身份。
    # 登记 + 进 requirements-analysis/template-write 的 stage producer 与指纹
    # （desktop_tasks.stage_producer——只登记不进戳不够，续跑会复用未标记旧产物）。
    # v2（2026-09-01b）：mixed 载荷 stub 占位条目加独立失败类 extract_degraded
    # （标记侧确定性形状比对，见 functional_extract.extract_degraded_marks）。
    # v3（2026-09-01c，hotfix）：governed 寻址 + draft 拦截 + 红字/守恒待核 sheet
    # （conservation_pending_gaps）——与常量同步进两阶段 producer/指纹。
    {"id": "conservation-partial-export", "version": "conservation-partial-export-v3",
     "owner_module": "functional_extract",
     "purpose": "Partial export pending-mark algorithm identity (marks + extract_degraded + gaps)"},

    # Table understanding
    {"id": "llm-table-understanding", "version": "llm-table-understanding-prompt-v1",
     "owner_module": "llm_table_understanding",
     "purpose": "LLM-assisted table understanding prompt"},

    # Claim ledger shadow verifier
    {"id": "claim-ledger-shadow", "version": "claim-ledger-shadow-prompt-v4", "owner_module": "claim_ledger",
     "purpose": "Claim ledger shadow coverage proposer prompt"},
    {"id": "claim-coverage-validator", "version": "claim-coverage-validator-v7", "owner_module": "claim_ledger",
     "purpose": "Claim coverage verifier prompt / policy version"},
    {"id": "claim-negative-policy", "version": "claim-negative-policy-v2", "owner_module": "claim_ledger",
     "purpose": "Semantic negative proposal policy version"},
    {"id": "claim-negative-validator", "version": "claim-negative-validator-v4", "owner_module": "claim_ledger",
     "purpose": "Semantic negative validator prompt / policy version"},

    # Agent orchestration
    {"id": "agent-decider", "version": "agent-decider-v1", "owner_module": "agent_decider",
     "purpose": "LLM agent decider prompt"},
    {"id": "agent-policy", "version": "agent-policy-v3", "owner_module": "agent_policy",
     "purpose": "Agent loop policy version pinned into trace/cache lineage"},

    # Translation
    {"id": "translation", "version": "translation-prompt-v3", "owner_module": "api_server",
     "purpose": "Requirement text translation prompt"},
    {"id": "annotation-translation-batch", "version": "translation-prompt-v5",
     "owner_module": "doc_annotation_export",
     "purpose": "Annotation marker batch translation prompt (dual-limit batch array contract)"},
    {"id": "annotation-translation-guards", "version": "annotation-translation-guards-v5",
     "owner_module": "api_server",
     "purpose": "Annotation translation anti-drift guard version"},

    # V3 new prompts (WS-A / WS-B)
    {"id": "doc-map", "version": "doc-map-prompt-v1", "owner_module": "doc_map",
     "purpose": "Whole-document clause map prompt (V3-1)"},
    {"id": "reconcile", "version": "reconcile-prompt-v1", "owner_module": "reconcile",
     "purpose": "Whole-document consistency reconciliation prompt (V3-3)"},
    {"id": "adjudicate", "version": "adjudicate-prompt-v1", "owner_module": "adjudicate",
     "purpose": "AI adjudication three-path prompt (WS-B)"},
]


_REGISTERED_VERSIONS: frozenset[str] = frozenset(entry["version"] for entry in PROMPT_REGISTRY)
_REGISTERED_IDS: frozenset[str] = frozenset(entry["id"] for entry in PROMPT_REGISTRY)


def is_registered(version: str) -> bool:
    return version in _REGISTERED_VERSIONS


def registry_by_id(prompt_id: str) -> dict[str, str] | None:
    for entry in PROMPT_REGISTRY:
        if entry["id"] == prompt_id:
            return dict(entry)
    return None


# Regex to find prompt-like version constants in Python source.
# It catches constants whose name contains PROMPT, REVIEW_CACHE, DECIDER,
# NORMATIVE_FRAMING, FOCUS_CRITIQUE, UNFOUNDED, RULES, TOOLS, or GUARDS
# and whose value is a version string literal.
_PROMPT_VERSION_RE = re.compile(
    r"^\s*(?P<constant>[A-Z_]*(?:PROMPT|REVIEW_CACHE|DECIDER|NORMATIVE_FRAMING|"
    r"FOCUS_CRITIQUE|UNFOUNDED|RULES|TOOLS|GUARDS)[A-Z_]*VERSION)\s*=\s*"
    r"[\"'](?P<version>[^\"']+)[\"']",
    re.MULTILINE,
)


def scan_prompt_version_constants(source: str) -> list[tuple[str, str]]:
    """Return (constant_name, version_string) pairs found in source."""
    return [(m.group("constant"), m.group("version")) for m in _PROMPT_VERSION_RE.finditer(source)]


def lint_source(
    source: str,
    *,
    extra_allowed: set[str] | None = None,
    excluded_constants: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return unregistered prompt version constants found in source.

    ``extra_allowed`` permits additional version strings (e.g. test fixtures
    that intentionally use a fake version).  ``excluded_constants`` skips
    constants whose names are known not to be prompt versions (e.g. schema
    versions that happen to match the regex).
    """
    allowed = set(_REGISTERED_VERSIONS) | set(extra_allowed or [])
    skip = set(excluded_constants or [])
    issues: list[dict[str, Any]] = []
    for constant, version in scan_prompt_version_constants(source):
        if constant in skip:
            continue
        if version not in allowed:
            issues.append({
                "constant": constant,
                "version": version,
                "reason": "unregistered prompt version",
            })
    return issues


def lint_directory(
    path: Path,
    *,
    extra_allowed: set[str] | None = None,
    excluded_constants: set[str] | None = None,
    skip_dirs: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Lint all ``*.py`` files under ``path``."""
    skip = set(skip_dirs or {
        "build", "dist", ".git", "__pycache__", "node_modules",
        # 非源码目录（主检出才有）：历史 worktree 残影与构建/产物目录不参与 lint，
        # 否则陈旧副本里的旧版本常量会误报未登记（2026-08-07 main 合并实测）。
        ".claude", ".worktrees", ".pytest_cache", "out",
        "dist-backend", "build-electron-backend", "requirement_atomizer.egg-info",
    })
    issues: list[dict[str, Any]] = []
    for py_file in path.rglob("*.py"):
        if any(part in skip for part in py_file.parts):
            continue
        source = py_file.read_text(encoding="utf-8")
        for issue in lint_source(source, extra_allowed=extra_allowed, excluded_constants=excluded_constants):
            issue["file"] = str(py_file)
            issues.append(issue)
    return issues
