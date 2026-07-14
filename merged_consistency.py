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

_MIN_QUOTE_CHARS = 12  # 太短的引用片段（如"see 4.2"）不作重复判据，防误判


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


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


def coverage_gaps(requirements: list[dict[str, Any]],
                  req_like_blocks: list[dict[str, Any]] | None) -> dict[str, Any]:
    """文档级覆盖：requirement_like 语句里，没被任何需求 source_quote 覆盖的 → 遗漏候选。"""
    if req_like_blocks is None:
        return {"measured": False}
    quotes = [q for q in (_norm(r.get("source_quote")) for r in requirements) if q]
    uncovered: list[dict[str, str]] = []
    seen: set[str] = set()
    total = 0
    for block in req_like_blocks:
        bt = _norm(block.get("text"))
        if not bt or bt in seen:
            continue
        seen.add(bt)
        total += 1
        if not any(q in bt or bt in q for q in quotes):
            # 带溯源（0714 批次一）：此前样本只有裸文本,遗漏候选无法回链批注视图/澄清清单;
            # block_id + 末级章节让"疑似漏抽"可逐条 triage（消费端兼容旧的裸字符串形状）
            section_path = [str(s) for s in (block.get("section_path") or []) if str(s).strip()]
            uncovered.append({
                "block_id": str(block.get("block_id") or ""),
                "section": section_path[-1] if section_path else "",
                "text": str(block.get("text") or "").strip()[:200],
            })
    covered = total - len(uncovered)
    return {
        "measured": True,
        "requirement_like": total,
        "covered": covered,
        "uncovered_count": len(uncovered),
        "coverage_ratio": round(covered / total, 4) if total else 1.0,
        "uncovered_samples": uncovered[:30],
    }


def analyze_consistency(requirements: list[dict[str, Any]],
                        req_like_blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    duplicates = find_cross_section_duplicates(requirements)
    obis_groups = find_obis_coreference(requirements)
    coverage = coverage_gaps(requirements, req_like_blocks)
    return {
        "requirements": len(requirements),
        "duplicate_groups": duplicates,
        "obis_coreference": obis_groups,
        "coverage": coverage,
        "summary": {
            "duplicate_groups": len(duplicates),
            "obis_coreference_groups": len(obis_groups),
            "obis_values_differ": sum(1 for g in obis_groups if g["values_differ"]),
            "uncovered_requirement_like": coverage.get("uncovered_count", 0) if coverage.get("measured") else None,
        },
    }
