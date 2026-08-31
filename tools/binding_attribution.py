# -*- coding: utf-8 -*-
"""守恒绑定失配（binding_mismatches）归因诊断库——只读，不改任何守恒语义。

背景（2026-08-31）：WS0 门禁 v2 的 B 轨守恒失败面收敛到 binding_mismatches
（跨条款借位叙述为主）之后，需要把每条失配确定性归因到四类：

- ``a_narrative_true_borrowing``：FRE 叙述实质复述了未声明条款的义务内容
  （LLM 输出问题——修复方向在抽取 prompt / 后处理）；
- ``b_check_false_positive_suspect``：FRE 内容确实属于声明条款，检查因边判定
  语义缺口未能建边（**只报告不修**——放宽检查语义须审核方裁定）；
- ``c_clause_segmentation_or_baseline_drift``：条款边界/路由基线本身漂移
  （解析切分病理、旧产物在新路由/新切分下重放），FRE 只是如实继承
  （修复方向在 parse/outline/routing，不在本诊断范围）；
- ``d_stub_entry``：stub 占位条目引发的失配（heading-only/降级路由课题）。

本模块**镜像** ``functional_extract.conservation_report`` 检查 3 的绑定判定逻辑
（同一批内部权威函数、同一判定顺序），但不设 [:50] 截断并携带条款索引级上下文，
供归因脚本与单测使用。镜像的正确性由运行侧断言（与 conservation_report 输出的
(fre_id, reason) 序列逐条相等）与 tests/test_binding_attribution.py 钉住。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Sequence

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

CATEGORY_TRUE_BORROWING = "a_narrative_true_borrowing"
CATEGORY_CHECK_FALSE_POSITIVE = "b_check_false_positive_suspect"
CATEGORY_CLAUSE_DRIFT = "c_clause_segmentation_or_baseline_drift"
CATEGORY_STUB = "d_stub_entry"

# functional_extract._stub_item 的确定性字面（objective = f"实现{heading}，并满足来源条款。"）
_STUB_OBJECTIVE_PREFIX = "实现"
_STUB_OBJECTIVE_SUFFIX = "，并满足来源条款。"


def is_stub_item(item: dict[str, Any]) -> bool:
    """stub 占位条目判定——匹配 ``functional_extract._stub_item`` 的确定性 objective 字面。"""
    objective = str(item.get("objective") or "")
    return (
        objective.startswith(_STUB_OBJECTIVE_PREFIX)
        and objective.endswith(_STUB_OBJECTIVE_SUFFIX)
    )


def collect_binding_findings(
    sections: Sequence[dict[str, Any]],
    items: Sequence[dict[str, Any]],
    *,
    blocks: Sequence[dict[str, Any]] | None = None,
    out_dir: Path | str | None = None,
) -> list[dict[str, Any]]:
    """不截断地镜像 conservation_report 检查 3 的 binding_mismatches 判定。

    返回的每条 finding 除 conservation_report 的原字段外，额外携带条款**索引**
    （``home_with_units_indices`` / ``covered_clause_indices``）——SBD 语料存在大量
    section_id 撞名（337/358 chunk 共享同一 id），字符串 id 不足以定位条款。
    """
    import functional_extract as fe

    baseline_sections, _delegated = fe._conservation_baseline_sections(
        sections, out_dir=out_dir, blocks=blocks,
    )
    section_block_ids = [
        sorted({str(b) for b in (section.get("block_ids") or []) if str(b)})
        for section in sections
    ]
    narratives = [fe.item_narrative(item) for item in items]
    edges = fe._obligation_evidence_edges(items, baseline_sections)
    edges_by_item: dict[int, list[dict[str, Any]]] = {}
    for edge in edges:
        edges_by_item.setdefault(edge["item_index"], []).append(edge)
    ignore_tokens = fe._known_section_tokens(baseline_sections)
    clause_units = [fe._obligation_index(s) for s in baseline_sections]

    findings: list[dict[str, Any]] = []
    for item_index, item in enumerate(items):
        narrative = narratives[item_index]
        ids = [str(b) for b in (item.get("source_block_ids") or []) if str(b)]
        fre_id = str(item.get("functional_requirement_id") or "")
        if not ids:
            continue  # 无声明块 → items_without_evidence（不属于绑定失配）
        declared_set = set(ids)
        home_indices = [
            i for i, blocks_ids in enumerate(section_block_ids)
            if blocks_ids and set(blocks_ids) & declared_set
        ]
        home_with_units = [
            i for i in home_indices
            if clause_units[i]
            and not fe._scripts_disjoint(
                fe._script_profile(str(baseline_sections[i].get("text") or "")),
                fe._script_profile(narrative),
            )
        ]
        if not (home_with_units and narrative.strip()):
            continue
        local_edge_sections = {
            edge["section_index"] for edge in (edges_by_item.get(item_index) or [])
        }
        if not (set(home_with_units) & local_edge_sections):
            # conservation v7：引句逐字锚定声明条款 = 本地锚，不记 reason 1，落入 reason 2。
            if not fe._quote_verbatim_in_home_clauses(
                item, baseline_sections, home_with_units,
            ):
                findings.append({
                    "functional_requirement_id": fre_id,
                    "item_index": item_index,
                    "reason": "declared_section_has_no_local_obligation_coverage",
                    "declared_block_ids": ids,
                    "home_with_units_indices": list(home_with_units),
                    "declared_section_ids": [
                        str(baseline_sections[i].get("section_id") or "")
                        for i in home_with_units
                    ],
                    "covered_clause_indices": [],
                })
                continue
        covered_clause_indices = {
            i for i, units in enumerate(clause_units)
            if any(
                fe._sentence_covered_by(
                    unit["sentence"], narrative, ignore_tokens=ignore_tokens)
                for unit in units
            )
        }
        if covered_clause_indices and not (
            set(home_with_units) & covered_clause_indices
        ):
            findings.append({
                "functional_requirement_id": fre_id,
                "item_index": item_index,
                "reason": "narrative_covers_other_clauses_not_declared",
                "declared_block_ids": ids,
                "home_with_units_indices": list(home_with_units),
                "declared_section_ids": [
                    str(baseline_sections[i].get("section_id") or "")
                    for i in home_with_units
                ],
                "covered_clause_indices": sorted(covered_clause_indices),
            })
    return findings


def build_signals(
    finding: dict[str, Any],
    *,
    item: dict[str, Any],
    baseline_sections: Sequence[dict[str, Any]],
    clause_units: Sequence[Sequence[dict[str, Any]]],
    all_sections: Sequence[dict[str, Any]] | None = None,
    kept_section_keys: set[tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    """从 finding + 语料上下文提取归因信号（确定性布尔量，供 classify_signals）。

    ``all_sections``：完整条款集（含被路由出基线的条款）——判断引句真实落点是否
    已离开守恒基线。``kept_section_keys``：基线内条款的身份键集合
    （``section_identity_key``），缺省时以 baseline_sections 现算。
    """
    import functional_extract as fe

    quote = fe._strip_table_markers(str(item.get("source_quote") or ""))
    quote_sq = fe._squashed(quote)
    home_indices = list(finding.get("home_with_units_indices") or [])

    quote_in_home = False
    home_unit_in_quote = False
    for i in home_indices:
        if i >= len(baseline_sections):
            continue
        text_sq = fe._squashed(str(baseline_sections[i].get("text") or ""))
        if quote_sq and quote_sq in text_sq:
            quote_in_home = True
        for unit in (clause_units[i] if i < len(clause_units) else []):
            unit_sq = fe._squashed(str(unit.get("sentence") or ""))
            if quote_sq and unit_sq and unit_sq in quote_sq:
                home_unit_in_quote = True

    if kept_section_keys is None:
        kept_section_keys = {
            section_identity_key(s) for s in baseline_sections
        }
    quote_site_sections: list[dict[str, Any]] = []
    if quote_sq:
        for section in (all_sections or []):
            text_sq = fe._squashed(str(section.get("text") or ""))
            if quote_sq in text_sq:
                quote_site_sections.append(section)
    quote_in_kept_other = any(
        section_identity_key(s) in kept_section_keys
        for s in quote_site_sections
    ) and not quote_in_home
    quote_in_dropped_only = bool(quote_site_sections) and not any(
        section_identity_key(s) in kept_section_keys
        for s in quote_site_sections
    )

    source_section_matches_quote_site = False
    declared_label = _normalize_label(str(item.get("source_section") or ""))
    if declared_label:
        for section in quote_site_sections:
            site_labels = [str(section.get("heading") or "")] + [
                str(seg) for seg in (section.get("section_path") or [])
            ] + [str(section.get("section_id") or "")]
            for label in site_labels:
                normalized = _normalize_label(label)
                if normalized and (
                    declared_label in normalized or normalized in declared_label
                ):
                    source_section_matches_quote_site = True
                    break

    covered_other_text_in_home = False
    for i in (finding.get("covered_clause_indices") or []):
        if i in home_indices or i >= len(clause_units):
            continue
        for unit in clause_units[i]:
            unit_sq = fe._squashed(str(unit.get("sentence") or ""))
            if not unit_sq:
                continue
            for h in home_indices:
                home_sq = fe._squashed(
                    str(baseline_sections[h].get("text") or ""))
                if unit_sq in home_sq:
                    covered_other_text_in_home = True

    # reason 1（declared_no_local_coverage）短路在叙述覆盖检测之前——这里补算
    # "叙述是否覆盖了任何非 home 条款的义务单元"（跨条款借位信号，不受短路遮蔽）。
    narrative = fe.item_narrative(item)
    ignore_tokens = fe._known_section_tokens(baseline_sections)
    home_set = set(home_indices)
    narrative_covers_nonhome = False
    if narrative.strip():
        for i, units in enumerate(clause_units):
            if i in home_set:
                continue
            if any(
                fe._sentence_covered_by(
                    unit["sentence"], narrative, ignore_tokens=ignore_tokens)
                for unit in units
            ):
                narrative_covers_nonhome = True
                break

    return {
        "reason": str(finding.get("reason") or ""),
        "is_stub": is_stub_item(item),
        "quote_present": bool(quote_sq),
        "quote_in_home": quote_in_home,
        "home_unit_in_quote": home_unit_in_quote,
        "quote_in_kept_other": quote_in_kept_other,
        "quote_in_dropped_only": quote_in_dropped_only,
        "source_section_matches_quote_site": source_section_matches_quote_site,
        "covered_other_text_in_home": covered_other_text_in_home,
        "narrative_covers_nonhome": narrative_covers_nonhome,
    }


def classify_signals(signals: dict[str, Any]) -> dict[str, str]:
    """确定性归因：信号布尔量 → 四类之一 + 细节说明。

    判定顺序（宁保守勿武断——(b) 是"疑似检查误报"，最终裁定权在审核方）：

    1. stub 条目 → ``d_stub_entry``；
    2. ``declared_section_has_no_local_obligation_coverage``：
       - 引句在声明条款基线文本内 → ``b``（疑似边判定语义缺口：内容在场但
         lexical / cross_script / source_quote 三种方法全部建不了边——义务
         单元切分/碎片过滤/无模态清单内容所致），只报告。其中叙述同时词面
         覆盖非 home 条款义务单元的子集以独立 detail 标出（人工抽查实证该
         子集混有「吞并 heading 切分病理」与重复文本双病灶，确定性信号
         不足以细分——见报告 §b/§c）；
       - 引句只出现在**基线外**条款（被路由出/被重切走）→ ``c``（真实归属
         条款已离开守恒基线，声明残留是切分/路由漂移的如实继承）；
       - 引句出现在基线内**其他**条款：source_section 字段与引句落点条款
         对得上 → ``c``（抽取时条款边界与当前切分不一致，声明按旧边界继承）；
         对不上 → ``a``（声明与内容真实错位——LLM 声明了错误的块）；
       - 引句缺席/全文无落点 → ``a``（叙述无可锚定内容，抽取输出问题）；
    3. ``narrative_covers_other_clauses_not_declared``：
       - 被覆盖条款的义务句文本同时逐字出现在声明条款文本内 → ``b``（条款间
         共享文本使"覆盖他款"与"覆盖本款"不可区分，疑似误报），只报告；
       - 否则 → ``a``（叙述实质复述未声明条款的义务——跨条款借位）。
    """
    if signals.get("is_stub"):
        return {"category": CATEGORY_STUB, "detail": "stub_placeholder_item"}
    reason = str(signals.get("reason") or "")
    if reason == "declared_section_has_no_local_obligation_coverage":
        if signals.get("quote_in_home"):
            if signals.get("narrative_covers_nonhome"):
                return {
                    "category": CATEGORY_CHECK_FALSE_POSITIVE,
                    "detail": (
                        "quote_in_home_no_edge_with_crossclause_lexical_overlap"
                    ),
                }
            return {
                "category": CATEGORY_CHECK_FALSE_POSITIVE,
                "detail": "quote_present_in_declared_clause_but_no_edge_formed",
            }
        if signals.get("quote_in_dropped_only"):
            return {
                "category": CATEGORY_CLAUSE_DRIFT,
                "detail": "quote_site_clause_left_conservation_baseline",
            }
        if signals.get("quote_in_kept_other"):
            if signals.get("source_section_matches_quote_site"):
                return {
                    "category": CATEGORY_CLAUSE_DRIFT,
                    "detail": "declared_blocks_follow_stale_clause_boundary",
                }
            return {
                "category": CATEGORY_TRUE_BORROWING,
                "detail": "declared_blocks_disagree_with_quote_site",
            }
        return {
            "category": CATEGORY_TRUE_BORROWING,
            "detail": "quote_unanchorable_in_current_sections",
        }
    if reason == "narrative_covers_other_clauses_not_declared":
        if signals.get("covered_other_text_in_home"):
            return {
                "category": CATEGORY_CHECK_FALSE_POSITIVE,
                "detail": "covered_clause_text_duplicated_in_declared_clause",
            }
        return {
            "category": CATEGORY_TRUE_BORROWING,
            "detail": "narrative_retells_undeclared_clause_obligations",
        }
    return {"category": CATEGORY_TRUE_BORROWING, "detail": "unknown_reason"}


def section_identity_key(section: dict[str, Any]) -> tuple[str, ...]:
    """条款身份键：block_ids 序列（SBD 语料 section_id 大面积撞名，id 不可作身份）。"""
    return tuple(
        str(b) for b in (section.get("block_ids") or []) if str(b)
    )


def _normalize_label(label: str) -> str:
    """条款标签归一（比对 source_section 与条款 heading/path 用）。"""
    return " ".join(str(label or "").casefold().split())
