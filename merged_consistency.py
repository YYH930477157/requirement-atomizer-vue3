"""P1：合并后全局一致性 critic（确定性、零 LLM、零幻觉）。

各章节独立并行抽取，缺一个全文档视角：同一需求在概览章 + 详情章各写一遍（跨章重复）、
同一 OBIS 在不同章带不同数值（潜在冲突）、requirement_like 语句整篇没被任何需求覆盖（遗漏），
单章视角都看不到。本模块在合并后扫一遍整份需求，产出**可审查的一致性报表**。

纪律：非破坏——只**标记**供人核，绝不自动删改（同 cosem_external_refs 零 LLM 哲学；结构字段
一位不动）。冲突只作"待核"提示，不断言 bug（确定性无法判语义等价，宁可提示不可误杀）。
"""
from __future__ import annotations

import re
from typing import Any

from cosem_behavior_spec import extract_codes, extract_ints

MERGED_CONSISTENCY_VERSION = "merged-consistency/v2-triage-strict-evidence"
_MIN_QUOTE_CHARS = 12  # 太短的引用片段（如"see 4.2"）不作重复判据，防误判
_MIN_SOURCE_MATCH_CHARS = 12
_MAX_SOURCE_WINDOW_BLOCKS = 12
_MIN_REVERSE_CONTAINMENT_RATIO = 0.75
_RELIABLE_SOURCE_MAPPINGS = frozenset({"exact", "contains", "multi_block"})

# 覆盖/遗漏口径的假阳性剔除（0714 批次二 E3b,实证 EN 16314:113 条"未覆盖"混着
# 引用书目/编号短标题/前言声明,覆盖率被稀释、真漏项被淹没）
_REF_LINE = re.compile(r"^(?:EN|IEC|ISO|CEN|CENELEC|ETSI|IEEE|ITU)[\s/–-]?\d", re.IGNORECASE)
_HEADING_LINE = re.compile(r"^\d+(?:\.\d+)*\s+[A-Za-z][A-Za-z /\-]{0,40}$")
_SOURCE_EXCERPT_SEPARATOR_RE = re.compile(r"(?:\r?\n+|\.{3,}|…+)")


def is_coverage_candidate(block: dict[str, Any]) -> bool:
    """覆盖率分母 /「未覆盖」标记的统一谓词。

    requirement_like 是**候选生成**的宽口径（atomize/golden 不动）；覆盖/遗漏是**质量
    指标**口径——剔除三类实证假阳性：非正文区（前言/目录的版式假阳性）、标题行
    （类型或"编号+短名词"形态,如 "4.5.1 Requirements"）、规范性引用书目行（标准号
    开头的短行,如 "EN 60950-1, … General requirements"）。消费方：覆盖率
    （quality/consistency）、批注视图未覆盖标记（双渲染器同源）、澄清清单遗漏候选。
    """
    if not block.get("requirement_like") or block.get("noise"):
        return False
    if str(block.get("doc_region") or "body") != "body":
        return False
    if str(block.get("type") or "") == "heading":
        return False
    text = str(block.get("text") or "").strip()
    if not text:
        return False
    if len(text) <= 160 and _REF_LINE.match(text):
        return False
    if _HEADING_LINE.match(text):
        return False
    return True


def coverage_denominator_blocks(blocks: Any) -> list[dict[str, Any]]:
    return [b for b in blocks if is_coverage_candidate(b)]


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def compact_source_text(text: Any) -> str:
    """来源匹配底座：忽略 PDF 词内空格差异，但保留标点、数字和编码。"""
    return re.sub(r"\s+", "", str(text or "")).casefold()


def _ordered_source_blocks(blocks: Any) -> list[dict[str, Any]]:
    rows = [block for block in (blocks or []) if isinstance(block, dict) and block.get("block_id")]
    return sorted(rows, key=lambda block: (
        int(block.get("order") or 0), str(block.get("block_id") or "")
    ))


def _source_texts(requirement: dict[str, Any]) -> list[str]:
    values = [str(requirement.get("source_quote") or "")]
    values.extend(str(value or "") for value in (requirement.get("source_quotes") or []))
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        compact = compact_source_text(value)
        if len(compact) >= _MIN_SOURCE_MATCH_CHARS and compact not in seen:
            seen.add(compact)
            result.append(value)
    return result


def _match_compact_quote(
    quote: str,
    normalized: list[tuple[dict[str, Any], str]],
) -> tuple[list[str], str]:
    exact = [
        str(block.get("block_id")) for block, text in normalized
        if len(text) >= _MIN_SOURCE_MATCH_CHARS and text == quote
    ]
    if exact:
        return exact, "exact" if len(exact) == 1 else "multi_block"
    containing = [
        str(block.get("block_id")) for block, text in normalized
        if len(text) >= _MIN_SOURCE_MATCH_CHARS and quote in text
    ]
    if containing:
        return containing, "contains" if len(containing) == 1 else "multi_block"
    # LLM 引句偶尔比单块多一个短前/后缀。只在该块覆盖引句主体时允许反向包含；否则
    # 长引句里的两个不相邻片段会被误认成一个 multi_block 来源。
    reverse_containing = [
        str(block.get("block_id")) for block, text in normalized
        if len(text) >= _MIN_SOURCE_MATCH_CHARS
        and text in quote
        and len(text) / len(quote) >= _MIN_REVERSE_CONTAINMENT_RATIO
    ]
    if reverse_containing:
        return (
            reverse_containing,
            "contains" if len(reverse_containing) == 1 else "multi_block",
        )

    # 引句可能恰好跨段落边界，单块均不完整。按最小窗口优先，避免把邻接无关块带入来源。
    for width in range(2, min(_MAX_SOURCE_WINDOW_BLOCKS, len(normalized)) + 1):
        for start in range(0, len(normalized) - width + 1):
            window = normalized[start:start + width]
            texts = [text for _block, text in window]
            if any(len(text) < _MIN_SOURCE_MATCH_CHARS for text in texts):
                continue
            joined = "".join(texts)
            if (
                quote in joined
                or (
                    joined in quote
                    and len(joined) / len(quote) >= _MIN_REVERSE_CONTAINMENT_RATIO
                )
            ):
                return [str(block.get("block_id")) for block, _text in window], "multi_block"
    return [], ""


def match_source_quote_blocks(source_quote: Any, blocks: Any) -> tuple[list[str], str]:
    """把逐字引句映射到一个或多个原文块。

    Google 机翻 PDF 会在词内插入真实空格，因此匹配时只忽略空白；标点、数字和编码仍需
    原样一致。过短块不参与反向包含，避免页码 ``2`` 被当成整段合规引句的来源。换行或
    省略号明确分隔的多段摘录分别匹配，不能用一个短页码替代整条长引句的来源。
    """
    ordered = _ordered_source_blocks(blocks)
    normalized: list[tuple[dict[str, Any], str]] = [
        (block, compact_source_text(block.get("text"))) for block in ordered
    ]
    raw_quote = str(source_quote or "")
    excerpts = [
        compact_source_text(value)
        for value in _SOURCE_EXCERPT_SEPARATOR_RE.split(raw_quote)
        if len(compact_source_text(value)) >= _MIN_SOURCE_MATCH_CHARS
    ]
    if len(excerpts) > 1:
        excerpt_matches: list[str] = []
        for excerpt in excerpts:
            matched, _method = _match_compact_quote(excerpt, normalized)
            if not matched:
                return [], ""
            excerpt_matches.extend(matched)
        excerpt_matches = list(dict.fromkeys(excerpt_matches))
        return (
            excerpt_matches,
            "multi_block" if len(excerpt_matches) > 1 else "contains",
        )

    quote = compact_source_text(raw_quote)
    if len(quote) < _MIN_SOURCE_MATCH_CHARS:
        return [], ""
    return _match_compact_quote(quote, normalized)


def reliable_echo_block_ids(requirement: dict[str, Any], blocks: Any) -> list[str]:
    """Return duplicate source blocks that pass the shared deterministic echo gate."""
    from extract_guards import _gram_jaccard, _num_multiset

    ordered = _ordered_source_blocks(blocks)
    quote = compact_source_text(requirement.get("source_quote"))
    source_ids = {str(value) for value in (requirement.get("source_block_ids") or []) if str(value)}
    anchor = str(requirement.get("anchor_block_id") or "")
    if anchor:
        source_ids.add(anchor)
    text_by_id = {
        str(block.get("block_id") or ""): str(block.get("text") or "") for block in ordered
    }
    references: list[tuple[str, str, tuple[str, ...]]] = []
    for block_id in source_ids:
        raw = text_by_id.get(block_id, "")
        compact = compact_source_text(raw)
        if len(compact) >= 60:
            references.append((raw, compact, _num_multiset(raw)))

    echoes: list[str] = []
    for block in ordered:
        block_id = str(block.get("block_id") or "")
        if not block_id or block_id in source_ids or block.get("noise"):
            continue
        raw = str(block.get("text") or "")
        compact = compact_source_text(raw)
        if len(compact) < 30:
            continue
        if len(quote) >= 30 and (quote in compact or compact in quote):
            echoes.append(block_id)
            continue
        if len(compact) < 60:
            continue
        for reference_raw, reference_compact, reference_numbers in references:
            if compact == reference_compact or (
                _num_multiset(raw) == reference_numbers
                and _gram_jaccard(raw, reference_raw) >= 0.8
            ):
                echoes.append(block_id)
                break
    return echoes


def covered_block_ids(requirements: list[dict[str, Any]], blocks: Any) -> set[str]:
    """返回有可靠来源证据的块 ID；section_fallback 的整章跨度不直接算覆盖。"""
    ordered = _ordered_source_blocks(blocks)
    by_id = {str(block.get("block_id")): block for block in ordered}
    covered: set[str] = set()
    for requirement in requirements:
        for source_text in _source_texts(requirement):
            matched, _method = match_source_quote_blocks(source_text, ordered)
            covered.update(matched)
        mapping = str(requirement.get("source_mapping") or "")
        if mapping in _RELIABLE_SOURCE_MAPPINGS:
            # 可靠映射可补充表格/短句等无法通过最小长度门的来源；fallback 绝不走此路。
            covered.update(
                str(block_id) for block_id in (requirement.get("source_block_ids") or [])
                if str(block_id) in by_id
            )
        declared_echoes = {
            str(block_id) for block_id in (requirement.get("echo_block_ids") or [])
            if str(block_id) in by_id
        }
        if declared_echoes:
            covered.update(declared_echoes.intersection(reliable_echo_block_ids(requirement, ordered)))
    return covered


def _req_id(req: dict[str, Any]) -> str:
    for key in ("id", "requirement_id", "ai_req_id", "stable_req_id"):
        value = str(req.get(key) or "").strip()
        if value:
            return value
    return str(req.get("title") or "")[:40]


def _req_text(req: dict[str, Any]) -> str:
    return " ".join(str(req.get(k) or "") for k in ("title", "description", "source_quote"))


def find_cross_section_duplicates(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一 source_quote（归一后）被 ≥2 条需求引用 → 疑似跨章重复，列出成员 + 各自章节。"""
    groups: dict[str, list[dict[str, Any]]] = {}
    for req in requirements:
        quote = _norm(req.get("source_quote"))
        if len(quote) < _MIN_QUOTE_CHARS:
            continue
        groups.setdefault(quote, []).append(req)
    duplicates: list[dict[str, Any]] = []
    for quote, members in groups.items():
        if len(members) < 2:
            continue
        duplicates.append({
            "source_quote": str(members[0].get("source_quote") or "").strip(),
            "members": [_req_id(m) for m in members],
            "sections": sorted({str(m.get("source_section") or "") for m in members if m.get("source_section")}),
            "count": len(members),
        })
    duplicates.sort(key=lambda d: (-d["count"], d["source_quote"]))
    return duplicates


def find_obis_coreference(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一 OBIS 码被 ≥2 条需求引用 → 交叉引用组。数值上下文不一致的标 values_differ=待核。

    不断言冲突——确定性无法判"class_id 3"与"class_id 3, 100 entries"是否语义冲突；只把同码分组
    交给研发核实，数值发散的优先看。
    """
    by_code: dict[str, list[dict[str, Any]]] = {}
    for req in requirements:
        text = _req_text(req)
        codes = extract_codes(text)
        ints = extract_ints(text) - extract_ints(" ".join(codes))  # 剔除 OBIS 自身数字，留真·数值上下文
        for code in codes:
            by_code.setdefault(code, []).append({"id": _req_id(req), "ints": frozenset(ints),
                                                 "section": str(req.get("source_section") or "")})
    groups: list[dict[str, Any]] = []
    for code, members in by_code.items():
        if len(members) < 2:
            continue
        int_sets = {m["ints"] for m in members}
        groups.append({
            "obis": code,
            "members": [m["id"] for m in members],
            "sections": sorted({m["section"] for m in members if m["section"]}),
            "count": len(members),
            "values_differ": len(int_sets) > 1,  # 数值上下文不一致 → 待核
        })
    # 待核的（数值发散）排前面，其次按引用数
    groups.sort(key=lambda g: (not g["values_differ"], -g["count"], g["obis"]))
    return groups


def coverage_gaps(
    requirements: list[dict[str, Any]],
    req_like_blocks: list[dict[str, Any]] | None,
    *,
    source_blocks: Any | None = None,
) -> dict[str, Any]:
    """文档级覆盖：requirement_like 语句里，没被任何需求 source_quote 覆盖的 → 遗漏候选。"""
    if req_like_blocks is None:
        return {"measured": False}
    # 分母只含正文候选，但来源匹配必须看完整块序列。否则标题/页码被过滤后，原本不相邻的
    # 两个正文块会被错误拼成一个多块引句；同时，跨候选/非候选边界的真实引句也会丢锚点。
    source_pool = req_like_blocks if source_blocks is None else source_blocks
    covered_ids = covered_block_ids(requirements, source_pool)
    covered_texts = {
        compact_source_text(block.get("text")) for block in req_like_blocks
        if str(block.get("block_id") or "") in covered_ids
    }
    uncovered: list[dict[str, str]] = []
    seen: set[str] = set()
    total = 0
    for block in req_like_blocks:
        bt = _norm(block.get("text"))
        if not bt or bt in seen:
            continue
        seen.add(bt)
        total += 1
        block_id = str(block.get("block_id") or "")
        is_covered = block_id in covered_ids or compact_source_text(block.get("text")) in covered_texts
        if not is_covered:
            # 带溯源（0714 批次一）：此前样本只有裸文本,遗漏候选无法回链批注视图/澄清清单;
            # block_id + 末级章节让"疑似漏抽"可逐条 triage（消费端兼容旧的裸字符串形状）
            section_path = [str(s) for s in (block.get("section_path") or []) if str(s).strip()]
            uncovered.append({
                "block_id": block_id,
                "section": section_path[-1] if section_path else "",
                "text": str(block.get("text") or "").strip()[:200],
            })
    covered = total - len(uncovered)
    return {
        "measured": True,
        "requirement_like": total,
        "covered": covered,
        "uncovered_count": len(uncovered),
        "uncovered_block_ids": [row["block_id"] for row in uncovered if row["block_id"]],
        "coverage_ratio": round(covered / total, 4) if total else 1.0,
        "uncovered_samples": uncovered[:30],
    }


def _excluded_coverage_reason(block: dict[str, Any], *, expert_non_requirement: bool = False) -> str:
    if expert_non_requirement:
        return "expert_non_requirement"
    if block.get("noise"):
        return "noise"
    if str(block.get("doc_region") or "body") != "body":
        return "non_body"
    if str(block.get("type") or "") == "heading":
        return "heading"
    text = str(block.get("text") or "").strip()
    if not text:
        return "empty"
    if len(text) <= 160 and _REF_LINE.match(text):
        return "reference"
    if _HEADING_LINE.match(text):
        return "heading"
    return "not_candidate"


def layered_coverage(
    requirements: list[dict[str, Any]],
    req_like_blocks: list[dict[str, Any]] | None,
    *,
    source_blocks: Any | None = None,
    allowed_block_ids: set[str] | None = None,
    expert_excluded_block_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Split coverage into product behavior, compliance delivery, and excluded text.

    Backward-compatible top-level counters mirror the ``core`` layer. Compliance is measured
    independently so a generic software requirement cannot hide a missed certificate or legal
    obligation. Excluded rows remain auditable but never dilute the readiness denominator.
    """
    if req_like_blocks is None:
        return {"measured": False, "scope": "core"}

    from compliance import is_compliance_requirement, looks_like_compliance

    source_pool = [
        block for block in (source_blocks if source_blocks is not None else req_like_blocks)
        if isinstance(block, dict)
    ]
    expert_excluded = {str(value) for value in (expert_excluded_block_ids or set()) if str(value)}
    candidates = [
        block for block in req_like_blocks
        if isinstance(block, dict)
        and str(block.get("block_id") or "") not in expert_excluded
        and (
            allowed_block_ids is None
            or str(block.get("block_id") or "") in allowed_block_ids
        )
    ]
    compliance_requirements = [row for row in requirements if is_compliance_requirement(row)]
    core_requirements = [row for row in requirements if not is_compliance_requirement(row)]
    compliance_evidence_ids = covered_block_ids(compliance_requirements, source_pool)

    compliance_blocks: list[dict[str, Any]] = []
    core_blocks: list[dict[str, Any]] = []
    for block in candidates:
        block_id = str(block.get("block_id") or "")
        if block_id in compliance_evidence_ids or looks_like_compliance(block.get("text")):
            compliance_blocks.append(block)
        else:
            core_blocks.append(block)

    core = coverage_gaps(core_requirements, core_blocks, source_blocks=source_pool)
    compliance = coverage_gaps(
        compliance_requirements,
        compliance_blocks,
        source_blocks=source_pool,
    )

    candidate_ids = {str(block.get("block_id") or "") for block in candidates}
    excluded_rows: list[dict[str, str]] = []
    for block in source_pool:
        block_id = str(block.get("block_id") or "")
        if not block.get("requirement_like") or block_id in candidate_ids:
            continue
        if allowed_block_ids is not None and block_id not in allowed_block_ids:
            continue
        excluded_rows.append({
            "block_id": block_id,
            "section": " / ".join(str(value) for value in (block.get("section_path") or [])),
            "reason": _excluded_coverage_reason(
                block, expert_non_requirement=block_id in expert_excluded,
            ),
            "text": str(block.get("text") or "").strip()[:200],
        })
    excluded = {
        "count": len(excluded_rows),
        "block_ids": [row["block_id"] for row in excluded_rows if row["block_id"]],
        "samples": excluded_rows[:30],
    }

    # Existing consumers continue to read coverage.requirement_like/covered/coverage_ratio and now
    # receive the readiness-relevant core scope. New consumers use the explicit layer objects.
    return {
        **core,
        "scope": "core",
        "core": core,
        "compliance": compliance,
        "excluded": excluded,
    }


def analyze_consistency(
    requirements: list[dict[str, Any]],
    req_like_blocks: list[dict[str, Any]] | None = None,
    *,
    source_blocks: Any | None = None,
    expert_excluded_block_ids: set[str] | None = None,
) -> dict[str, Any]:
    duplicates = find_cross_section_duplicates(requirements)
    obis_groups = find_obis_coreference(requirements)
    coverage = layered_coverage(
        requirements,
        req_like_blocks,
        source_blocks=source_blocks,
        expert_excluded_block_ids=expert_excluded_block_ids,
    )
    return {
        "producer_version": MERGED_CONSISTENCY_VERSION,
        "requirements": len(requirements),
        "duplicate_groups": duplicates,
        "obis_coreference": obis_groups,
        "coverage": coverage,
        "summary": {
            "duplicate_groups": len(duplicates),
            "obis_coreference_groups": len(obis_groups),
            "obis_values_differ": sum(1 for g in obis_groups if g["values_differ"]),
            "uncovered_requirement_like": coverage.get("uncovered_count", 0) if coverage.get("measured") else None,
            "uncovered_compliance": (
                (coverage.get("compliance") or {}).get("uncovered_count", 0)
                if coverage.get("measured") else None
            ),
            "excluded_requirement_like": (
                (coverage.get("excluded") or {}).get("count", 0)
                if coverage.get("measured") else None
            ),
        },
    }
