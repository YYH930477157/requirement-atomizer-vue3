from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import time
from dataclasses import replace
from pathlib import Path

from result_package import governed_artifact_path
from typing import Any, Callable

from ai_review_actions import read_ai_review_states, source_ai_requirement_id
from compliance import build_compliance_payload, is_compliance_requirement
from io_utils import read_jsonl, read_jsonl_recover_torn_tail
from requirements_analysis_agent import build_analysis_prompt, validate_llm_item
from requirements_analysis_excel import _fallback_lines, clarify_display_text, write_software_requirements_xlsx
from requirements_analysis_rules import classify_ownership
from requirements_analysis_schema import (
    OWNERSHIP_CO_DESIGN,
    OWNERSHIP_HARDWARE,
    OWNERSHIP_SOFTWARE,
    apply_ownership_override,
    build_analysis_id,
    normalize_ownership,
    validate_analysis_item,
)
from requirements_analysis_template import (
    extract_template_knowledge,
    extract_template_vocabulary,
    render_template_references,
    select_template_references,
)


LOGGER = logging.getLogger("requirement_atomizer")

ChatFn = Callable[[str, str], dict[str, Any]]

SCHEMA_VERSION = "requirements-analysis/v1"
# v7：无依据富化字段强制"待澄清"（Agent Phase 2 WP2，规则版本 analyze-unfounded-v1 随行）；
# v6：冻结归属注入 prompt（模型不再重判,只按给定归属定正文深度）；
# v5：注入文档背景/条款原文/相邻需求,正文连贯成文（2026-07-12 富化深度）
ANALYZE_PROMPT_VERSION = "analyze-llm-v8"
# P0-8：负例 few-shot 注入数量上限（可配）。
ANALYZE_NEGATIVE_K = int(os.environ.get("RATOMIZER_ANALYZE_NEGATIVE_K", "2"))
# WP2 待澄清规则版本——确定性后处理（拒/无据 → 待澄清 + open_questions 同步）变更必须
# bump 并进 analyze_enrich_cache 指纹与阶段 producer（AGENTS.md 缓存指纹纪律）
# v4：编造编码字段级拒收（只拒含码字段,干净字段放行;同判据逐字段重检保防幻觉红线）
# v3：归属护栏（software 项不采纳 LLM 写入的 hardware_dependency）+ 富化调用失败/返回非法同样标待澄清
UNFOUNDED_RULE_VERSION = "analyze-unfounded-v4"  # v2:渲染兜底（clarify_fallback 原始候选标注透出）
CLARIFY_MARK = "待澄清"
# WP2 触发面（冻结点 4）：仅富化叙述字段；确定性 join 字段（id/归属/引句/模块）永不标待澄清
_UNFOUNDED_TEXT_FIELDS = ("software_requirement_text", "hardware_dependency")
_UNFOUNDED_LIST_FIELDS = ("developer_guidance", "design_options", "acceptance_criteria")
_UNFOUNDED_FIELD_LABELS = {
    "software_requirement_text": "软件需求正文",
    "hardware_dependency": "硬件依赖",
    "developer_guidance": "研发指引",
    "design_options": "设计候选",
    "acceptance_criteria": "验收标准",
}
ANALYZE_MIN_MAX_TOKENS = 8192  # 连贯多段正文+更长输入;推理模型思维链挤占,低于下限 JSON 截断
# 富化缓存（性能 2026-08-14）：v2 起为增量 JSONL（meta 行 + key/item 行）——旧版每完成一个
# 任务把**整个** items dict json.dumps+整写,是 O(任务数×缓存体积) 的二次开销;现每任务
# 只追加一行并 fsync（镜像 ai_extract.append_cache 的 JSONL 纪律）。读侧 last-write-wins。
# 写入全在跨进程锁内（世代探测/撕裂尾行截断/追加/世代翻转整替,详见 _save_enrich_cache）。
ANALYZE_ENRICH_CACHE = "analyze_enrich_cache.jsonl"
ANALYZE_ENRICH_CACHE_LEGACY = "analyze_enrich_cache.json"   # v1 单 JSON：只读兼容,不再写出
# 写入侧跨进程锁文件（process_file_lock 不删锁 inode 的 no-unlink 纪律；与
# doc_map_cache/functional_extract_cache 等追加式缓存同款 sidecar 锁）。
ANALYZE_ENRICH_CACHE_LOCK = "analyze_enrich_cache.lock"
# 缓存**文件格式**版本（区别于内容指纹）：行形状/键方案变更必须 bump。同时折进 _enrich_key——
# 旧形状的键永不与新形状的键碰撞,即使读侧兼容层缺失也不可能误读（AGENTS.md 缓存指纹纪律）。
# v1=单 JSON 整写（隐含）;v2=JSONL 追加（meta 行 + key/item 行）,五段上下文 "".join 进键;
# v3=JSONL 行形状不变,键方案改 canonical JSON 数组——"".join 有确定性边界碰撞
# （("ab","c") vs ("a","bc") 同键 → 一条需求的富化结果可被错用到另一上下文）,
# v2 中间文件不得在 v3 格式号下续读（meta format 不匹配 → 读侧弃用/写侧世代翻转）。
ENRICH_CACHE_FORMAT_VERSION = "analyze-enrich-cache-v3"
# 写侧 PermissionError 重试：8 次 × 线性退避 0.02..0.14s——Windows AV/索引器/杀毒对目标
# 句柄的短占常超单次预算（review_state._REPLACE_ATTEMPTS 同口径,repo 标准）。
_ENRICH_SAVE_ATTEMPTS = 8
_ENRICH_SAVE_RETRY_DELAY_S = 0.02
_ENRICH_SAVE_LOCK_TIMEOUT_S = 10.0
# W1 上下文注入帽：条款原文与 prompt/指纹/校验三处用同一字符串（单一构造点）
SECTION_CONTEXT_MAX_CHARS = 2000
SIBLING_TITLES_MAX = 8
# 合批富化（0714 批次一 S1）：同模块多条一次调用——prompt 骨架/词表/推理开销只花一遍
# （EN 16314 实测富化 126 次调用累计 66 分钟）。4 是推理模型输出预算与超时的稳妥点；
# 1=回到逐条。硬件翻译输出短，批量 ×2 封顶 8。
ANALYZE_BATCH_ENV = "RATOMIZER_ANALYZE_BATCH"
REQUIREMENTS_ANALYSIS_ENRICH_ENV = "RATOMIZER_REQUIREMENTS_ANALYSIS_ENRICH"
DEFAULT_ANALYZE_BATCH = 4
MAX_ANALYZE_BATCH = 8


def _resolve_analyze_batch(explicit: int | None = None) -> int:
    raw: Any = explicit if explicit is not None else os.environ.get(ANALYZE_BATCH_ENV)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_ANALYZE_BATCH
    return max(1, min(MAX_ANALYZE_BATCH, value))


def requirements_analysis_enrichment_enabled() -> bool:
    """返回普通应用调用是否启用需求分析 LLM 富化；默认关闭。"""
    return os.environ.get(REQUIREMENTS_ANALYSIS_ENRICH_ENV, "0").strip().lower() in {
        "1", "true", "yes", "on",
    }


# 确定性分析层（规则+模板+裁决）恒在；openai_compatible 追加 LLM 富化层，只填叙述字段、
# 结构/归属/路由字段全冻结。请求 LLM 但端点未配置时如实降级并记 route_requested（出处诚实）。
STUB_ROUTE = "stub"
DEGRADE_NOTE = "openai_compatible 端点未配置，本次按规则/模板/裁决确定性运行（未做 LLM 富化）"
# LLM 只允许填这些叙述字段；OBIS/class/访问位/归属/id 等结构字段永不被 LLM 覆盖（防幻觉红线）
_ENRICH_FIELDS_TEXT = ("software_requirement_text", "hardware_dependency")
_ENRICH_FIELDS_LIST = ("developer_guidance", "design_options", "acceptance_criteria", "open_questions", "assumptions")
OUTPUT_FILES = [
    "software_requirements.xlsx",
    "engineering_analysis.json",
    "hardware_items.md",
    "co_design_items.md",
    "compliance_items.json",
    "compliance_items.md",
]


def _read_term_map_text(out_dir: Path) -> str:
    """term_map.json（抽取轨缓存）只读渲染——分析轨零额外调用,中文译法与抽取轨一致。"""
    try:
        cached = json.loads((out_dir / "term_map.json").read_text(encoding="utf-8"))
        terms = cached.get("terms") or []
    except (OSError, json.JSONDecodeError, AttributeError):
        return ""
    if not terms:
        return ""
    from ai_extract import _render_term_map
    return _render_term_map(terms)


def _build_doc_context(out_dir: Path, blocks: list[dict[str, Any]]) -> str:
    """文档背景（表计画像+大纲+术语表+译法对照）——复用抽取轨实现（W1,2026-07-12）。

    此前富化 prompt 无任何文档级背景,是"不如把需求粘给聊天 AI"的结构性原因之一。"""
    context = ""
    try:
        from ai_extract import build_doc_context
        context = build_doc_context(out_dir, blocks)
    except Exception as exc:  # pragma: no cover - 背景失败不阻断富化
        LOGGER.warning("文档背景构建失败（富化退回无背景）：%s", exc)
    term_text = _read_term_map_text(out_dir)
    if term_text:
        context = f"{context}\n{term_text}" if context else term_text
    return context


def _section_context(req: dict[str, Any], blocks_by_id: dict[str, dict[str, Any]],
                     blocks_by_section: dict[tuple[str, ...], list[dict[str, Any]]]) -> str:
    """需求所在条款族原文（≤SECTION_CONTEXT_MAX_CHARS,以需求块为中心向两侧扩展）。

    解析不了 → ""，**绝不回退整章**——这个字符串同时进 prompt/缓存指纹/漂移基线
    （单一构造点），基线只收模型实际看到的注入串。"""
    from extract_units import clean_block_text

    section_key: tuple[str, ...] | None = None
    anchor_bid = ""
    for bid in (str(b) for b in _as_list(req.get("source_block_ids"))):
        block = blocks_by_id.get(bid)
        if block is not None:
            section_key = tuple(str(s) for s in (block.get("section_path") or []))
            anchor_bid = bid
            break
    if section_key is None:
        target = str(req.get("source_section") or "").strip()
        if target:
            section_key = next((key for key in blocks_by_section if key and key[-1].strip() == target), None)
    if not section_key:
        return ""
    texts: list[str] = []
    anchor_index = 0
    for block in blocks_by_section.get(section_key) or []:
        if block.get("noise"):
            continue
        text = clean_block_text(block)
        if not text:
            continue
        if str(block.get("block_id") or "") == anchor_bid:
            anchor_index = len(texts)
        texts.append(text)
    if not texts:
        return ""
    # 中心扩展：先取需求块本体,再左右交替补齐到帽值——长条款不会只剩开头
    picked = [anchor_index]
    total = len(texts[anchor_index])
    left, right = anchor_index - 1, anchor_index + 1
    while total < SECTION_CONTEXT_MAX_CHARS and (left >= 0 or right < len(texts)):
        for candidate in (right, left):
            if candidate == right and right < len(texts):
                picked.append(right)
                total += len(texts[right])
                right += 1
            elif candidate == left and left >= 0:
                picked.insert(0, left)
                total += len(texts[left])
                left -= 1
            if total >= SECTION_CONTEXT_MAX_CHARS:
                break
    joined = "\n".join(texts[i] for i in sorted(set(picked)))
    return joined[:SECTION_CONTEXT_MAX_CHARS]


# S1-3：functional_requirements.json 的合法 producer 家族白名单。functional-synthesis
# （旧原子化→合成路径）与 functional-extract（WS2 直抽）同为功能需求级产物来源；只校验
# 家族前缀不校验版本号（版本演进由指纹层负责失效）。
_FUNCTIONAL_PRODUCER_FAMILIES = ("functional-synthesis", "functional-extract")


def _raise_if_functional_extract_unconserved(synthesized_payload: dict[str, Any]) -> None:
    """S1-2 成文导出闸门：functional-extract 直抽产物守恒未闭合即 raise，阻断成文上游。

    functional_extract 的 ``conservation_report`` 投影在 ``functional_requirements.json``
    的 ``conservation`` 块（``ok`` / missing/duplicate/extra/evidence_mismatches）。守恒未
    闭合即调 ``functional_extract.raise_if_unconserved`` 抛 ``FunctionalConservationError``，
    不让不守恒的功能需求级产物静默进归属分类 / 软件 LLM / 研发模板成文（仅 payload 标志位
    不够——验收要求「导出被阻断」）。functional-synthesis 无守恒块，缺块时按现状放行。
    """
    conservation = synthesized_payload.get("conservation")
    if not isinstance(conservation, dict):
        return
    from functional_extract import raise_if_unconserved
    raise_if_unconserved(conservation)


def run_requirements_analysis(
    out_dir: Path,
    *,
    route: str = "stub",
    template_path: Path | None = None,
    chat: ChatFn | None = None,
    pipeline_path: Path | None = None,
    concurrency: int | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    out_dir = Path(out_dir).expanduser().resolve()
    synthesized_path = out_dir / "functional_requirements.json"
    source_path = out_dir / "ai_requirements.jsonl"
    if not source_path.exists():
        # 缺输入必须响亮失败：静默产出"0 条 0 问题"的空交付物会掩盖打错目录（仓库纪律）
        raise FileNotFoundError(
            f"ai_requirements.jsonl not found in {out_dir} — 请先运行「AI 抽取」再做需求分析")
    raw_requirements = read_jsonl(source_path)
    if synthesized_path.exists():
        try:
            synthesized_payload = json.loads(synthesized_path.read_text(encoding="utf-8"))
            requirements = synthesized_payload.get("items") if isinstance(synthesized_payload, dict) else None
        except (OSError, json.JSONDecodeError):
            requirements = None
        # C4（0710 评审）：消费端血统校验（§43）——陈旧/异源 functional_requirements.json
        # 会被静默采信（链内指纹只管要不要重跑，不做产物互一致校验）。producer 家族不符
        # 即告警并回退逐原子输入；只校验家族名不校验版本号（版本演进由指纹层负责失效）。
        # S1-3：白名单接纳 functional-extract 直抽家族（与 functional-synthesis 同为合法来源）。
        # S1-2：functional-extract 产物携带 conservation 守恒报告——未闭合即 raise 阻断成文上游。
        if isinstance(requirements, list) and isinstance(synthesized_payload, dict):
            producer = str(synthesized_payload.get("producer") or "")
            if not any(producer.startswith(family) for family in _FUNCTIONAL_PRODUCER_FAMILIES):
                LOGGER.warning("functional_requirements.json producer 异常（%s），回退逐原子输入", producer or "缺失")
                requirements = None
            elif producer.startswith("functional-extract"):
                _raise_if_functional_extract_unconserved(synthesized_payload)
        if not isinstance(requirements, list):
            requirements = raw_requirements
    else:
        requirements = raw_requirements
    # 容错读（坏行跳过）+ 最新覆盖，与裁决回流同一读取器——单条撕裂写不弄死整跑
    states = read_ai_review_states(out_dir)
    compliance_source: list[dict[str, Any]] = []
    for requirement in raw_requirements:
        source_id = _source_requirement_id(requirement)
        state = states.get(source_id)
        if _is_rejected(state) or not is_compliance_requirement(requirement):
            continue
        reviewed = dict(requirement)
        reviewed["ai_req_id"] = source_id
        if state and str(state.get("status") or "").strip():
            reviewed["status"] = str(state.get("status") or "").strip()
        compliance_source.append(reviewed)
    # 防御旧 functional_requirements.json：即使上游产物来自隔离修复前，也不能让合规项
    # 进入归属分类、软件 LLM 或研发模板。
    requirements = [row for row in requirements if not is_compliance_requirement(row)]
    vocabulary = extract_template_vocabulary(template_path)
    # 显式注入 chat 是测试/嵌入方的主动 opt-in；普通应用只有开关开启且请求 LLM
    # 路由时才解析端点。默认关闭时连端点、模板知识和裁决样本都不读取。
    enrichment_enabled = chat is not None or (
        route != STUB_ROUTE and requirements_analysis_enrichment_enabled()
    )
    active_chat, model = (
        _resolve_chat(route, chat, pipeline_path) if enrichment_enabled else (None, "")
    )
    # 公司标准做法知识：从模板现读（不进仓不落索引），仅供启用后的富化使用。
    knowledge = extract_template_knowledge(template_path) if active_chat is not None else {}
    # 裁决样本库（env 指路，未配置=空库零注入）+ 澄清答复（评审会回灌，权威客户输入）
    from adjudication_bank import (load_bank, render_exemplars, render_negative_exemplars,
                                   resolve_bank_path, select_exemplars, select_negative_exemplars)
    from clarification_report import load_current_answers
    bank = load_bank(resolve_bank_path()) if active_chat is not None else {}
    answers_by_source: dict[str, list[dict[str, Any]]] = {}
    for (sid, _q), row in load_current_answers(out_dir).items():
        if row.get("adopted", True) and sid:
            answers_by_source.setdefault(sid, []).append(row)

    executed_route = STUB_ROUTE
    note = ""
    if enrichment_enabled and route != STUB_ROUTE and active_chat is None:
        note = DEGRADE_NOTE
        LOGGER.warning(note)
    enrich_cache = _load_enrich_cache(out_dir, model) if active_chat is not None else {}
    enriched_count = 0
    degraded_count = 0
    enrich_jobs: list[tuple[dict[str, Any], dict[str, Any], dict[str, str], str]] = []
    analyze_batch = _resolve_analyze_batch() if active_chat is not None else 1
    # 合批模式的模块级 siblings/exemplars 备忘（与批组成无关 → 缓存 key 稳定）
    module_ctx_memo: dict[str, tuple[str, str]] = {}

    # W1（2026-07-12 富化深度）：文档背景/条款原文/相邻需求标题——仅 LLM 模式构建,
    # blocks.jsonl 缺失 → 空上下文优雅降级（行为同旧版）
    doc_context = ""
    blocks_by_id: dict[str, dict[str, Any]] = {}
    blocks_by_section: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    titles_by_module: dict[str, list[str]] = {}
    if active_chat is not None:
        analysis_blocks = read_jsonl(out_dir / "blocks.jsonl")
        if analysis_blocks:
            doc_context = _build_doc_context(out_dir, analysis_blocks)
            for block in analysis_blocks:
                bid = str(block.get("block_id") or "")
                if bid:
                    blocks_by_id[bid] = block
                blocks_by_section.setdefault(
                    tuple(str(s) for s in (block.get("section_path") or [])), []).append(block)
        for req in requirements:
            module = str(req.get("module") or "").strip()
            title = str(req.get("title") or "").strip()
            if module and title:
                titles_by_module.setdefault(module, []).append(title[:40])

    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for req in requirements:
        source_id = _source_requirement_id(req)
        source_atom_ids = list(dict.fromkeys(
            [str(value).strip() for value in _as_list(req.get("source_ai_requirement_ids")) if str(value).strip()]
            + [source_id]
        ))
        state = states.get(source_id)
        if _is_rejected(state):
            continue
        reviewed_req = _apply_module_override(req, state)
        item = _base_item(len(items) + 1, reviewed_req, vocabulary)
        item.update(classify_ownership(reviewed_req))
        effective_state = dict(state or {})
        embedded_ownership = str(reviewed_req.get("ownership_override") or "").strip()
        if embedded_ownership and not effective_state.get("ownership_override"):
            effective_state["ownership_override"] = embedded_ownership
        try:
            item = apply_ownership_override(item, effective_state)
        except ValueError as exc:  # 非法归属覆盖：单条降级记 issue，不整跑死（设计文档要求逐条继续）
            issues.append({
                "analysis_id": item.get("analysis_id"),
                "source_requirement_ids": item.get("source_requirement_ids") or [],
                "issues": [f"ownership_override 非法，已忽略: {exc}"],
            })
        if item.get("ownership") == OWNERSHIP_HARDWARE:
            _normalize_hardware_item(item, reviewed_req)

        # 富化只做软件/协同（硬件按 GLM prompt 只需简要说明，硬件项走 ownership_reason/引用，
        # 不产 software_requirement_text——跳过省真实调用）；先收集、循环后并发执行
        ans_rows = [row for atom_id in source_atom_ids for row in (answers_by_source.get(atom_id) or [])]
        if ans_rows:
            answers_text = "；".join(f"问：{r.get('question')} 答：{r.get('answer')}" for r in ans_rows)
            reviewed_req = dict(reviewed_req)
            reviewed_req["clarification_answers_text"] = answers_text   # 进有据基线（validate 读它）
            item["notes"] = list(item.get("notes") or []) + [f"客户答复：{r.get('answer')}" for r in ans_rows]
        if active_chat is not None:
            refs = select_template_references(knowledge, reviewed_req)
            module_name = str(reviewed_req.get("module") or "").strip()
            if analyze_batch > 1:
                # 合批模式：siblings/exemplars 用模块级视图（与批组成无关 → key 稳定）；
                # 单条模式保留"排除自身标题"的旧构造，两种模式各自确定性
                if module_name not in module_ctx_memo:
                    all_titles = titles_by_module.get(module_name, [])
                    module_text = " ".join(all_titles[:SIBLING_TITLES_MAX])
                    module_ctx_memo[module_name] = (
                        "\n".join(f"- {t}" for t in all_titles[:SIBLING_TITLES_MAX]),
                        render_exemplars(select_exemplars(bank, module_name, module_text)),
                        render_negative_exemplars(select_negative_exemplars(bank, module_name, module_text, k=ANALYZE_NEGATIVE_K)),
                    )
                siblings_text, exemplars, negative_exemplars = module_ctx_memo[module_name]
            else:
                req_text = " ".join(str(reviewed_req.get(k) or "") for k in ("title", "description", "source_quote"))
                exemplars = render_exemplars(select_exemplars(bank, module_name, req_text))
                negative_exemplars = render_negative_exemplars(select_negative_exemplars(bank, module_name, req_text, k=ANALYZE_NEGATIVE_K))
                own_title = str(reviewed_req.get("title") or "").strip()[:40]
                siblings = [t for t in titles_by_module.get(module_name, [])
                            if t != own_title][:SIBLING_TITLES_MAX]
                siblings_text = "\n".join(f"- {t}" for t in siblings)
            ctx = {"template_refs": render_template_references(refs),
                   "exemplars": exemplars,
                   "negative_exemplars": negative_exemplars,
                   "answers": reviewed_req.get("clarification_answers_text") or "",
                   "doc_context": doc_context,
                   "section_context": _section_context(reviewed_req, blocks_by_id, blocks_by_section),
                   "siblings": siblings_text}
            mode = "hardware" if item.get("ownership") == OWNERSHIP_HARDWARE else "software"
            enrich_jobs.append((item, reviewed_req, ctx, mode))

        item_issues = validate_analysis_item(item)
        if item_issues:
            issues.append({
                "analysis_id": item.get("analysis_id"),
                "source_requirement_ids": item.get("source_requirement_ids") or [],
                "issues": item_issues,
            })
        items.append(item)

    if active_chat is not None and enrich_jobs:
        enriched_count, degraded_count = _run_enrichment(
            out_dir, enrich_jobs, vocabulary, active_chat, enrich_cache, model,
            issues=issues, concurrency=concurrency, progress_callback=progress_callback,
            batch_size=analyze_batch)
        # 增量 JSONL 落盘已在 _run_enrichment 内逐任务完成（每任务追加新键一行）,无需收尾整写
        if enriched_count > 0:
            executed_route = "openai_compatible"
            if degraded_count > 0:
                # 部分降级必须可见（0714 批次一）：此前只有"全灭"才提示,100/288 条静默退回
                # 浅描述时 GUI 全绿,专家以为拿到的是 LLM 富化结果
                note = (f"LLM 富化部分降级：{degraded_count}/{len(enrich_jobs)} 条回退确定性描述"
                        "（逐条原因见 engineering_analysis.json 的 issues）")
        else:
            note = "LLM 富化结果均未被采纳，本次交付物仅包含确定性分析结果"

    from requirement_record import provenance
    payload = {
        "schema_version": SCHEMA_VERSION,
        "provenance": provenance("requirements_analysis", ANALYZE_PROMPT_VERSION),
        "route": executed_route,        # 实际执行的路由（出处诚实）
        "route_requested": route,
        "enrichment_enabled": enrichment_enabled,
        "enriched": enriched_count,
        "enrich_degraded": degraded_count,
        "items": items,
        "compliance": {
            "count": len(compliance_source),
            "files": ["compliance_items.json", "compliance_items.md"],
        },
        "issues": issues,
    }
    from input_completeness import attach_input_completeness

    attach_input_completeness(payload, out_dir)
    if note:
        payload["note"] = note
    # xlsx 最先写（openpyxl 是最可能失败的一步）：失败时 JSON/MD 未动，不留半套新旧混杂的交付物
    xlsx_path = write_software_requirements_xlsx(items, out_dir / "software_requirements.xlsx")
    (out_dir / "engineering_analysis.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_report(
        out_dir / "hardware_items.md",
        [item for item in items if item.get("ownership") == OWNERSHIP_HARDWARE],
        "Hardware Items",
    )
    _write_report(
        out_dir / "co_design_items.md",
        [item for item in items if item.get("ownership") == OWNERSHIP_CO_DESIGN],
        "Co-design Items",
        co_design=True,
    )
    compliance_payload = build_compliance_payload(compliance_source)
    compliance_payload.update({
        "producer": ANALYZE_PROMPT_VERSION,
        "source": source_path.name,
        "analysis": "deterministic_compliance_projection",
        "incomplete_inputs": payload["incomplete_inputs"],
        "input_completeness": payload["input_completeness"],
    })
    (out_dir / "compliance_items.json").write_text(
        json.dumps(compliance_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_compliance_report(out_dir / "compliance_items.md", compliance_payload["items"])

    result = {
        "kind": "requirements_analysis",
        "analysis_count": len(items),
        "compliance_count": len(compliance_payload["items"]),
        "issues": len(issues),
        "route": executed_route,
        "route_requested": route,
        "enrichment_enabled": enrichment_enabled,
        "enriched": enriched_count,
        "enrich_degraded": degraded_count,
        "incomplete_inputs": payload["incomplete_inputs"],
        "input_completeness": payload["input_completeness"],
        "written": [xlsx_path.name] + [n for n in OUTPUT_FILES if n != "software_requirements.xlsx"],
    }
    if xlsx_path.name != "software_requirements.xlsx":
        result["note_xlsx"] = f"目标被占用，已另存 {xlsx_path.name}"
    if note:
        result["note"] = note
    return result


def _resolve_chat(route: str, chat: ChatFn | None, pipeline_path: Path | None) -> tuple[ChatFn | None, str]:
    """决定本次是否有可用 LLM，返回 (chat, model)。

    注入的 chat 优先（测试/嵌入调用），model 记 "injected"。否则仅当请求非 stub 路由时按
    pipeline 解析端点：解析出 openai_compatible 配置才启用，否则返回 (None, "") 触发降级。
    与 ai_extract 复用同一 config_for_route，不另起一套端点解析。
    """
    if chat is not None:
        return chat, "injected"
    if route == STUB_ROUTE:
        return None, ""
    try:
        from ai_extract import DEFAULT_PIPELINE_PATH, config_for_route
        from llm_client import chat_json
        config = config_for_route(route, pipeline_path or DEFAULT_PIPELINE_PATH)
    except Exception as exc:  # pragma: no cover - 端点/pipeline 解析异常一律降级
        LOGGER.warning("LLM 路由解析失败，降级为确定性: %s", exc)
        return None, ""
    if config is None:
        return None, ""
    # 密钥缺失即视为端点不可用：无 key 调用必 401，不如如实降级（也让离线测试免打网）。
    # 密钥只走环境变量，绝不落盘（仓库红线）。
    if not os.environ.get(config.api_key_env):
        LOGGER.warning("LLM 路由 %s 已解析但环境变量 %s 未设置，降级为确定性", route, config.api_key_env)
        return None, ""
    from llm_client import apply_min_tokens
    config = apply_min_tokens(config, "analyze")
    batch = _resolve_analyze_batch()
    if batch > 1:
        # 合批一次产多条正文：输出下限按批量抬（封顶 16384——extract-chapter 同级、已实证），
        # 超时同步放宽——推理模型合批单次可达数分钟，120s 超时会白白整批重试
        config = replace(config,
                         max_tokens=max(config.max_tokens,
                                        min(16384, ANALYZE_MIN_MAX_TOKENS + 2048 * batch)),
                         timeout_s=max(config.timeout_s, 60.0 * batch))
    return (lambda system, user: chat_json(config, system, user)), config.model


def _enrich_key(req: dict[str, Any], model: str, template_refs: str = "") -> str:
    """内容指纹缓存键：源内容 + 注入参考 + prompt 版本 + 模型。源/模板行不变则重跑免调用。"""
    basis = "\n".join([
        str(req.get("source_quote") or ""),
        str(req.get("description") or ""),
        str(req.get("requirement") or ""),
        str(req.get("module") or ""),
        template_refs,   # 模板行内容变 → 缓存失效（镜像 spec_enrich 折 entry hash 的做法）
        ANALYZE_PROMPT_VERSION,
        UNFOUNDED_RULE_VERSION,   # WP2：待澄清确定性后处理变更必须使缓存失效（防旧产物漏标）
        ENRICH_CACHE_FORMAT_VERSION,   # 文件格式版本随行：旧形状键永不与新形状键碰撞
        model,
    ])
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def _load_enrich_cache(out_dir: Path, model: str) -> dict[str, Any]:
    """读富化缓存（read-both）：v2+ JSONL（meta 行 + key/item 行,撕裂尾行自愈）为主,
    v1 单 JSON 只读兼容。同键冲突时 JSONL（新写入侧）后读覆盖；任一文件的
    格式/prompt/模型 meta 不匹配 → 该文件整份弃用（防复用异模型/prompt/形状的产物）。"""
    items: dict[str, Any] = {}
    legacy_path = governed_artifact_path(out_dir, ANALYZE_ENRICH_CACHE_LEGACY,
                                        category="cache", for_write=False)
    if legacy_path.exists():
        try:
            data = json.loads(legacy_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = None
        if isinstance(data, dict):
            meta = data.get("_meta") or {}
            if meta.get("prompt") == ANALYZE_PROMPT_VERSION and meta.get("model") == model:
                cached = data.get("items")
                if isinstance(cached, dict):
                    items.update(cached)
    path = governed_artifact_path(out_dir, ANALYZE_ENRICH_CACHE, category="cache", for_write=False)
    if not path.exists():
        return items
    try:
        rows = read_jsonl_recover_torn_tail(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return items   # 中段损坏：JSONL 整份不可信——宁可重富化,不猜半份（宁漏勿错）
    format_ok = False
    for row in rows:
        if not isinstance(row, dict):
            return items
        if row.get("_meta"):
            meta = row
            format_ok = (meta.get("format") == ENRICH_CACHE_FORMAT_VERSION
                         and meta.get("prompt") == ANALYZE_PROMPT_VERSION
                         and meta.get("model") == model)
            if not format_ok:
                return items
            continue
        if not format_ok:
            return items   # 首行不是 meta 行 → 形状不可信
        key = str(row.get("key") or "")
        value = row.get("item")
        if key and isinstance(value, dict):
            items[key] = value   # 后写覆盖（last-write-wins）
    return items


def _probe_enrich_cache_generation(path: Path, model: str) -> str:
    """锁内探测缓存文件当前世代（与 _load_enrich_cache 同判据扫描 meta 行）：

    - 'absent'：文件缺失/空 → 建文件（meta+行）；
    - 'match'：所有 meta 行与当前 format/prompt/model 一致且首行即 meta → 撕裂尾行已被
      read_jsonl_recover_torn_tail 原子截断,可直接追加；
    - 'mismatch'：格式/prompt/模型漂移,或形状不可信（首行非 meta/中段坏行/无 meta）——
      读侧本就整份弃用,写侧按世代翻转处理（原子整替,旧世代弃用）；
    - 'unreadable'：瞬态读失败（如 Windows 读句柄短占）——不弃旧世代,本次写入如实失败,
      调用方保留未落盘键待下次重试（宁漏勿错：读不出就不动旧文件）。
    """
    try:
        if not path.exists() or path.stat().st_size == 0:
            return "absent"
        rows = read_jsonl_recover_torn_tail(path)
    except (ValueError, json.JSONDecodeError):   # 含 UnicodeDecodeError：中段损坏,形状不可信
        return "mismatch"
    except OSError:
        return "unreadable"
    seen_meta = False
    for row in rows:
        if row.get("_meta"):
            if not (row.get("format") == ENRICH_CACHE_FORMAT_VERSION
                    and row.get("prompt") == ANALYZE_PROMPT_VERSION
                    and row.get("model") == model):
                return "mismatch"
            seen_meta = True
        elif not seen_meta:
            return "mismatch"   # meta 行之前出现数据行 → 形状不可信（读侧同判据弃用）
    return "match" if seen_meta else "mismatch"


def _append_enrich_rows_with_retry(path: Path, lines: list[str]) -> None:
    """锁内单次 fsync 追加（O(1) 稳态——不整写文件）：PermissionError 短占 8 次线性退避。"""
    for attempt in range(_ENRICH_SAVE_ATTEMPTS):
        try:
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                for line in lines:
                    handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return
        except PermissionError:
            if attempt + 1 >= _ENRICH_SAVE_ATTEMPTS:
                raise
            time.sleep(_ENRICH_SAVE_RETRY_DELAY_S * (attempt + 1))


def _replace_enrich_file_with_retry(path: Path, lines: list[str]) -> None:
    """建文件/世代翻转：tmp+fsync+os.replace 原子整替（PermissionError 重试同口径）。"""
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
            for line in lines:
                handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(_ENRICH_SAVE_ATTEMPTS):
            try:
                os.replace(tmp_path, path)
                return
            except PermissionError:
                if attempt + 1 >= _ENRICH_SAVE_ATTEMPTS:
                    raise
                time.sleep(_ENRICH_SAVE_RETRY_DELAY_S * (attempt + 1))
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _save_enrich_cache(out_dir: Path, model: str,
                       new_items: list[tuple[str, dict[str, Any]]]) -> bool:
    """增量落盘（v3 JSONL,返回是否成功——失败时调用方保留未落盘键待重试,paid 结果不丢）。

    跨进程锁（process_file_lock,不删锁 inode）内三态（2026-08-14 缺陷修复）：
    (a) 文件缺失/空 → 写 meta 行 + 新行；
    (b) meta 与当前 format/prompt/model 一致 → 撕裂尾行截断后单次 fsync 追加新行
        （O(1) 每任务,不整写）；
    (c) meta 不一致（模型/prompt/格式漂移）→ **世代翻转**：原子整替为新 meta + 新行,
        旧世代弃用——与读侧 mismatch 整份弃用同语义。旧实现只在建文件时写 meta,
        模型切换后把新行追加在旧 meta 之后 → 读侧永远整份弃用,缓存永久变砖。
    并发纪律（缺陷修复）：世代探测/撕裂尾行截断/追加/整替全在锁内——裸 append 会交叉
    追加或写双 meta 行,读侧命中中段损坏即整份弃用。"""
    if not new_items:
        return True
    path = governed_artifact_path(out_dir, ANALYZE_ENRICH_CACHE, category="cache")
    lock_path = governed_artifact_path(out_dir, ANALYZE_ENRICH_CACHE_LOCK, category="cache")
    meta_line = json.dumps({"_meta": True, "format": ENRICH_CACHE_FORMAT_VERSION,
                            "prompt": ANALYZE_PROMPT_VERSION, "model": model},
                           ensure_ascii=False)
    item_lines = [json.dumps({"key": key, "item": llm_item}, ensure_ascii=False)
                  for key, llm_item in new_items]
    from process_file_lock import process_file_lock
    try:
        with process_file_lock(lock_path, timeout_s=_ENRICH_SAVE_LOCK_TIMEOUT_S,
                               label="analyze_enrich_cache"):
            generation = _probe_enrich_cache_generation(path, model)
            if generation == "unreadable":
                LOGGER.warning("富化缓存暂时不可读，本批保留待下次重试: %s", path)
                return False
            if generation == "match":
                _append_enrich_rows_with_retry(path, item_lines)
            else:   # absent（建文件）或 mismatch（世代翻转）
                _replace_enrich_file_with_retry(path, [meta_line] + item_lines)
        return True
    except OSError as exc:   # 含 TimeoutError（锁超时）：缓存写失败不致命,但要如实报告
        LOGGER.warning("富化缓存写入失败（本批保留待下次重试）: %s", exc)
        return False


def _first_item(payload: Any) -> dict[str, Any] | None:
    """从 LLM 返回里取单条分析产物，容忍 {items:[...]} / 裸对象 / 裸数组 三种形状。"""
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            return items[0]
        if "software_requirement_text" in payload or "ownership" in payload:
            return payload
        return None
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    return None


def _software_prompt_parts(
    item: dict[str, Any],
    source_req: dict[str, Any],
    vocabulary: dict[str, Any],
    model: str,
    ctx: dict[str, str],
    vocab_memo: dict[str, tuple[dict[str, Any], str]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """key/prompt 载荷单一构造点（单条与合批共用）。

    返回 (slim_vocab, prompt_req, cache_key)。key 只由本条内容 + 模块级/条级注入构成，
    与批组成无关——合批与否、批里还有谁，都不改变本条的缓存命中;
    软背景（doc_context/siblings/exemplars）不进 key（S3,见下方注释）。
    冻结归属注入（0714）：prompt 只写不判；归属变化（专家改判）→ key 变 → 重富化。

    vocab_memo（性能 2026-08-14）：词表瘦身+序列化按 (run, module) 记忆化——memo 由
    _run_enrichment 每次运行新建（词表对象随 run 重建,等价于按 (module, template) 键）,
    同模块多条不再逐条重复 slim_vocabulary + json.dumps（结果确定性,逐字节等价,key 不变）。
    """
    from requirements_analysis_agent import slim_vocabulary
    module_name = str(source_req.get("module") or "")
    if vocab_memo is not None and module_name in vocab_memo:
        slim_vocab, serialized = vocab_memo[module_name]
    else:
        slim_vocab = slim_vocabulary(vocabulary, module_name)
        serialized = json.dumps(slim_vocab, ensure_ascii=False)
        if vocab_memo is not None:
            vocab_memo[module_name] = (slim_vocab, serialized)
    frozen_ownership = str(item.get("ownership") or "")
    prompt_req = dict(source_req)
    prompt_req["ownership"] = frozen_ownership
    # key 收窄（0714 批次二 S3）：只折**有据基底与硬约束**——源字段(在 _enrich_key 内)、
    # 条款原文、客户答复、模板参考、词表、冻结归属。软背景（doc_context/siblings/exemplars）
    # 进 prompt 不进 key：它们只影响文风/粒度,验证每次运行按当前基线重跑（护栏不受缓存影响,
    # 背景码从不豁免,复用最多多出软标）;而背景漂移导致整库缓存报废（test18 事故:术语表
    # 一变全文档重富化、同模块加一条全模块重富化）的代价远大于文风陈旧。
    # v3（2026-08-14 缺陷修复）：五段改 canonical JSON 数组编码（ensure_ascii+紧凑分隔符）——
    # 旧 "".join 有确定性边界碰撞（("ab","c") vs ("a","bc") 同键）,一条需求的富化结果可被
    # 错用到另一上下文;JSON 数组每段带引号/逗号定界,拼接永不歧义。
    context_basis = json.dumps(
        [ctx.get("template_refs", ""), ctx.get("answers", ""), ctx.get("section_context", ""),
         serialized, frozen_ownership],
        ensure_ascii=True, separators=(",", ":"))
    return slim_vocab, prompt_req, _enrich_key(source_req, model, context_basis)


def _mark_unfounded_field(item: dict[str, Any], field: str, reason: str) -> None:
    """WP2：单字段写"待澄清"并同步一条 open_questions（内部核对受众,进既有澄清闭环——
    clarification_report 读 engineering_analysis.json 的 open_questions 通道已存在;
    xlsx「待确认：…」/成文列渲染通道原样透出）。

    兜底（2026-07-23 用户裁定）：覆盖前的原值存入 item["clarify_fallback"][field]——
    渲染层以"待澄清 + 标注的原始候选"呈现,交付物既诚实又保留可读内容;数据层字段本身
    仍恒为待澄清（不做"看起来完整"的假交付）。"""
    original = item.get(field)
    if original and original != CLARIFY_MARK and original != [CLARIFY_MARK]:
        fallback = item.setdefault("clarify_fallback", {})
        if isinstance(fallback, dict):
            fallback.setdefault(field, original)
    item[field] = [CLARIFY_MARK] if field in _UNFOUNDED_LIST_FIELDS else CLARIFY_MARK
    questions = item.setdefault("open_questions", [])
    if not isinstance(questions, list):
        questions = []
        item["open_questions"] = questions
    label = _UNFOUNDED_FIELD_LABELS.get(field, field)
    entry = f"内部核对·待澄清：{label}无依据（{reason}），需专家核补"
    if entry not in questions:
        questions.append(entry)


def _mark_rejected_enrichment_fields(item: dict[str, Any], fields: set[str], reason: str) -> None:
    """按字段应用"整条拒绝"的单字段规则（v4 字段级拒收）：只标被点名字段,逐字段规则
    与 _mark_enrichment_rejected 完全一致——正文恒标（base 是原始描述而非分析正文）;
    硬件依赖仅协同项（纯软件项留空是设计语义,非缺失）;列表字段仅 base 为空时标
    （base 非空=源文有据内容——只对"无依据"下手,有据字段逐字节不动）。"""
    if "software_requirement_text" in fields:
        _mark_unfounded_field(item, "software_requirement_text", reason)
    if "hardware_dependency" in fields and str(item.get("ownership") or "") == OWNERSHIP_CO_DESIGN:
        _mark_unfounded_field(item, "hardware_dependency", reason)
    for field in _UNFOUNDED_LIST_FIELDS:
        if field in fields and not item.get(field):
            _mark_unfounded_field(item, field, reason)


def _mark_enrichment_rejected(item: dict[str, Any], reason: str) -> None:
    """WP2 规则 1：富化被护栏整体拒绝（回退 base 值）→ 无依据字段写"待澄清"，
    不再静默以 base 文本充当软件需求正文。（v4 起字段级拒收共享同一套单字段规则。）"""
    _mark_rejected_enrichment_fields(
        item, set(_UNFOUNDED_TEXT_FIELDS) | set(_UNFOUNDED_LIST_FIELDS), reason)


# v4 字段级拒收的判定细节：编造码**绝不进 open_questions 文本**——码只进 run 级 issues
# （engineering_analysis.json 审计行）,item 字段对编造码零容纳（防幻觉红线从严一档）。
_FABRICATED_REJECT_REASON = "LLM 富化编造结构编码被护栏拒收"


def _fabricated_code_fields(
    llm_item: dict[str, Any],
    source_req: dict[str, Any],
    ctx: dict[str, str],
) -> dict[str, list[str]]:
    """逐字段重检编造编码（与 validate_llm_item **同基线同提取器**）：返回 {字段: [编造码]}。

    正文侧（software_requirement_text/hardware_dependency/ownership_reason——validate 的
    analysis_text 成员,除永不被采纳的 requirement 外）基线=源文并集∪条款原文,背景/模板
    编码不豁免；交付列表侧（guidance 三件套+assumptions/open_questions——validate 的
    delivery_text 成员）基线=源文并集∪模板注入。判据逐字段等价于整体检测：被整体检出的
    编造码只要落在可采纳字段,必被归属到该字段——这是"字段级拒收不放走任何编造码"的安全
    前提（宁漏勿错：拒错字段只是少富化,放走编造码是红线事故）。"""
    from cosem_behavior_spec import extract_codes

    union_text = " ".join(
        str(source_req.get(field) or "")
        for field in ("source_quote", "description", "requirement", "clarification_answers_text")
    ) + " " + str(ctx.get("section_context") or "")
    union_codes = extract_codes(union_text)
    template_codes = extract_codes(str(ctx.get("template_refs") or ""))
    fabricated: dict[str, list[str]] = {}
    for field in _UNFOUNDED_TEXT_FIELDS + ("ownership_reason",):
        codes = sorted(extract_codes(str(llm_item.get(field) or "")) - union_codes)
        if codes:
            fabricated[field] = codes
    for field in _UNFOUNDED_LIST_FIELDS + ("open_questions", "assumptions"):
        field_text = " ".join(str(value) for value in _as_list(llm_item.get(field))
                              if str(value).strip())
        codes = sorted(extract_codes(field_text) - union_codes - template_codes)
        if codes:
            fabricated[field] = codes
    return fabricated


def _replace_unfounded_adopted_fields(
    item: dict[str, Any],
    source_req: dict[str, Any],
    ctx: dict[str, str],
    adopted_fields: set[str],
) -> list[str]:
    """WP2 规则 2：富化被接受但某采纳字段证据校验降级（validate_llm_item 软标判据细化
    到字段）→ 该字段写"待澄清"。返回追加的 issue 说明。

    判据与 validate_llm_item 同源：extract_ints 差集（正文基线=源文∪条款原文∪答复,
    指引基线=源文∪模板注入,均豁免 doc_context 背景整数）；字段侧先剥枚举标号
    （"1. 2. 3."是格式归一不是编造数字,test18 已立此判例）。编造编码在整体硬拒阶段
    已拦截,走不到这里;模板来源编码/遗漏类软标不标待澄清（有依据,归专家审查）。
    只查本次 LLM 采纳的字段——base 值（源文派生）永不标。"""
    from cosem_behavior_spec import extract_ints
    from text_normalize import strip_enum_markers

    union_text = " ".join(
        str(source_req.get(field) or "")
        for field in ("source_quote", "description", "requirement", "clarification_answers_text")
    ) + " " + str(ctx.get("section_context") or "")
    context_ints = extract_ints(str(ctx.get("doc_context") or ""))
    union_ints = extract_ints(union_text)
    guidance_basis_ints = extract_ints(f"{union_text} {ctx.get('template_refs') or ''}")
    issues: list[str] = []
    for field in _UNFOUNDED_TEXT_FIELDS:
        if field not in adopted_fields:
            continue
        unfounded = sorted(
            extract_ints(strip_enum_markers(str(item.get(field) or ""))) - union_ints - context_ints)
        if unfounded:
            detail = f"含源文/条款/背景均无据的数字: {', '.join(unfounded[:6])}"
            _mark_unfounded_field(item, field, detail)
            issues.append(f"{_UNFOUNDED_FIELD_LABELS[field]}无依据已标待澄清: {detail}")
    for field in _UNFOUNDED_LIST_FIELDS:
        if field not in adopted_fields:
            continue
        field_text = " ".join(str(value) for value in _as_list(item.get(field)))
        unfounded = sorted(
            extract_ints(strip_enum_markers(field_text)) - guidance_basis_ints - context_ints)
        if unfounded:
            detail = f"含源文/模板/背景均无据的数字: {', '.join(unfounded[:6])}"
            _mark_unfounded_field(item, field, detail)
            issues.append(f"{_UNFOUNDED_FIELD_LABELS[field]}无依据已标待澄清: {detail}")
    return issues


def _apply_llm_item(
    item: dict[str, Any],
    source_req: dict[str, Any],
    llm_item: dict[str, Any],
    ctx: dict[str, str],
) -> tuple[bool, list[str]]:
    """验证 + 采纳（单条与合批共用）——合批不放宽任何护栏：validate 逐条，
    基线只含本条自己的条款原文/答复，批内其它条的数值不进有据基线
    （模型跨条借数即硬拒/软标）。

    WP2（Agent Phase 2）：无依据富化字段强制"待澄清"——整体拒绝（回退 base）
    或采纳字段证据校验降级时,该字段写"待澄清"并同步 open_questions,不再静默放行。

    v4 字段级拒收（2026-08-14）：检出编造结构编码时只拒"自己的文本里就有该码"的字段
    （_fabricated_code_fields 与整体检测同基线同提取器,归属完备）,干净字段照常采纳——
    不再一条编造毁掉整条富化。安全前提：任何被整体检出的编造码,只要落在可采纳字段,
    必被该字段的同判据重检拦下,绝不随采纳进交付物（防幻觉红线,宁漏勿错）。"""
    drift = validate_llm_item(llm_item, source_req, template_text=ctx.get("template_refs", ""),
                              section_context=ctx.get("section_context", ""),
                              context_text=ctx.get("doc_context", ""))
    fabricated_codes = [d for d in drift if d.startswith("fabricated code")]
    blocked_fields: dict[str, list[str]] = (
        _fabricated_code_fields(llm_item, source_req, ctx) if fabricated_codes else {})
    fabricated_issues: list[str] = []
    if fabricated_codes:
        _mark_rejected_enrichment_fields(item, set(blocked_fields), _FABRICATED_REJECT_REASON)
        fabricated_issues = [
            f"{_UNFOUNDED_FIELD_LABELS.get(field, field)}含编造结构编码，已拒收该字段: "
            f"{', '.join(codes)}"
            for field, codes in blocked_fields.items()]
        if not blocked_fields:
            # 编造码只出现在不可采纳位置（如 llm 自带的 requirement 字段,本就不进交付物）——
            # 干净字段照常采纳,但发现必须留痕（出处诚实,不静默吞护栏命中）
            fabricated_issues.append(
                "LLM 富化编造结构编码位于不可采纳字段（未进交付物）: " + "; ".join(fabricated_codes))

    accepted = False
    adopted_fields: set[str] = set()
    # 归属护栏（审计 r2 S1）：hardware_dependency 仅 hardware/co_design 可采纳——software 项
    # 被 LLM 写入硬件依赖属越权注入（内容护栏不管归属），确定性跳过；非空值如实留痕，不静默吞
    ownership_skips: list[str] = []
    for field in _ENRICH_FIELDS_TEXT:
        if field in blocked_fields:   # 字段自身含编造码：不采纳（红线）
            continue
        value = str(llm_item.get(field) or "").strip()
        if not value:
            continue
        if field == "hardware_dependency" and str(item.get("ownership") or "") == OWNERSHIP_SOFTWARE:
            ownership_skips.append(f"归属护栏：software 项不采纳 LLM 写入的硬件依赖，需人工核对: {value}")
            continue
        item[field] = value
        adopted_fields.add(field)
        accepted = True
    for field in _ENRICH_FIELDS_LIST:
        if field in blocked_fields:   # 字段自身含编造码：不采纳（红线）
            continue
        values = [str(x).strip() for x in _as_list(llm_item.get(field)) if str(x).strip()]
        if values:
            item[field] = values
            if field in _UNFOUNDED_LIST_FIELDS:
                adopted_fields.add(field)
            accepted = True
    reason = str(llm_item.get("ownership_reason") or "").strip()
    # 恒真 guard 修复（2026-07-12）：classify_ownership 对所有类别都前置填了规则原因,
    # 旧条件 `not item.get("ownership_reason")` 恒假 → 软件/协同的 LLM 原因永不被采纳。
    # 采纳三条件：原因非空;LLM 若自带 ownership 须与冻结归属一致（不一致=模型想借"原因"
    # 字段改写归属叙事,保留规则原因并记 issue）;人工覆盖过的归属其叙事权威不被 LLM 冲掉。
    # 归属值/置信度仍冻结;reason 本就在 validate_llm_item 的 analysis_text 扫描内（编码硬拒）。
    # v4：reason 自身含编造码（blocked_fields 点名）时不采纳,规则原因保留。
    reason_issues: list[str] = []
    if (reason and "ownership_reason" not in blocked_fields
            and str(item.get("ownership_source") or "") != "reviewer_override"):
        llm_ownership = str(llm_item.get("ownership") or "").strip()
        consistent = True
        if llm_ownership:
            try:
                consistent = normalize_ownership(llm_ownership) == str(item.get("ownership") or "")
            except ValueError:
                consistent = False
        if consistent:
            item["ownership_reason"] = reason
            item["ownership_reason_source"] = "llm"
            accepted = True
        else:
            reason_issues.append(
                f"LLM 归属叙述与冻结归属不一致（{llm_ownership} vs {item.get('ownership')}），保留规则原因")
    if not accepted:
        reject_reason = (_FABRICATED_REJECT_REASON if fabricated_codes
                         else "LLM 富化未返回可采纳的叙述字段")
        _mark_enrichment_rejected(item, reject_reason)
        base_issues = ownership_skips + (
            [f"LLM 富化编造结构编码，已拒绝并降级: {'; '.join(fabricated_codes)}"] if fabricated_codes
            else ["LLM 富化未返回可采纳的叙述字段，已降级为确定性"])
        return False, fabricated_issues + base_issues
    item["analysis_source"] = "llm"
    clarify_issues = _replace_unfounded_adopted_fields(item, source_req, ctx, adopted_fields)

    soft = [d for d in drift if not d.startswith("fabricated code")]
    # 软标必须随交付物同行（2026-07-08 审计 B1）：此前只进 run 级 issues（excel/成文不读），
    # 编造数字以零可见标记落进公司模板成文 xlsx。现在钉在 item 上，_notes_text/成文同列渲染。
    warnings = soft + ownership_skips   # 归属护栏跳过同样钉 item（审计 r2 S1：留痕随交付物同行）
    if warnings:
        item["enrichment_warnings"] = warnings
    else:
        item.pop("enrichment_warnings", None)   # 重富化后旧警告不残留
    issues = fabricated_issues + reason_issues + clarify_issues + ownership_skips + (
        [f"富化软提示（数字/遗漏漂移，未阻断，请对照 source_quote 核）: {'; '.join(soft)}"] if soft else [])
    return True, issues


def _llm_enrich_item(
    item: dict[str, Any],
    source_req: dict[str, Any],
    vocabulary: dict[str, Any],
    chat: ChatFn,
    cache: dict[str, Any],
    model: str,
    lock: Any = None,
    context: dict[str, str] | None = None,
    vocab_memo: dict[str, tuple[dict[str, Any], str]] | None = None,
) -> tuple[bool, list[str]]:
    """用 LLM 填充叙述字段（software_requirement_text 等），结构字段一律不动。

    防幻觉红线：validate_llm_item 检出**编造**的 OBIS/编码/数字（换位 OBIS 也逃不掉）→ 编造
    编码字段级拒收（v4）/编造数字软标，item 结构字段恒确定性；任何调用/解析失败都非致命：
    该条降级为确定性，返回 (False, [原因])。lock：并发跑时保护共享 cache 的读写；
    vocab_memo：模块词表瘦身+序列化的 run 级记忆（性能,输出逐字节不变）。
    """
    from contextlib import nullcontext
    guard = lock if lock is not None else nullcontext()

    ctx = context or {}
    slim_vocab, prompt_req, key = _software_prompt_parts(item, source_req, vocabulary, model, ctx,
                                                         vocab_memo=vocab_memo)
    with guard:
        llm_item = cache.get(key)
    if llm_item is None:
        prompt = build_analysis_prompt([prompt_req], slim_vocab, ctx.get("template_refs", ""),
                                       exemplars=ctx.get("exemplars", ""),
                                       negative_exemplars=ctx.get("negative_exemplars", ""),
                                       answers=ctx.get("answers", ""),
                                       doc_context=ctx.get("doc_context", ""),
                                       section_context=ctx.get("section_context", ""),
                                       siblings=ctx.get("siblings", ""))
        try:
            payload = chat(prompt["system"], prompt["user"])
        except Exception as exc:  # 调用失败非致命
            # 与护栏拒绝同纪律（审计 r2 S2）：没采到 LLM 内容 → 无依据字段标待澄清、
            # base 值保留进 clarify_fallback、open_questions 留痕，base 文本不得静默充当正文透出
            _mark_enrichment_rejected(item, "LLM 富化调用失败")
            return False, [f"LLM 富化调用失败，已降级为确定性: {exc}"]
        llm_item = _first_item(payload)
        if llm_item is None:
            _mark_enrichment_rejected(item, "LLM 富化返回空或格式非法")
            return False, ["LLM 富化返回空或格式非法，已降级为确定性"]
        with guard:
            cache[key] = llm_item
    return _apply_llm_item(item, source_req, llm_item, ctx)


def _map_batch_items(payload, expected: int) -> dict[int, dict[str, Any]]:
    """合批响应 → 槽位映射：优先 enrich_slot 回填；全体缺槽且数量吻合才按序对齐，
    其余情况宁缺勿错（缺槽条目走单条回退，绝不张冠李戴）。"""
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return {}
    by_slot: dict[int, dict[str, Any]] = {}
    unslotted: list[dict[str, Any]] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        try:
            slot = int(entry.get("enrich_slot"))
        except (TypeError, ValueError):
            slot = None
        if slot is not None and 0 <= slot < expected and slot not in by_slot:
            by_slot[slot] = entry
        else:
            unslotted.append(entry)
    if not by_slot and len(unslotted) == expected:
        return dict(enumerate(unslotted))
    return by_slot


def _llm_enrich_batch(
    jobs: list[tuple[dict[str, Any], dict[str, Any], dict[str, str], str]],
    vocabulary: dict[str, Any],
    chat: ChatFn,
    cache: dict[str, Any],
    model: str,
    lock: Any = None,
    vocab_memo: dict[str, tuple[dict[str, Any], str]] | None = None,
) -> tuple[list[tuple[dict[str, Any], bool, list[str]]],
           list[tuple[dict[str, Any], dict[str, Any], dict[str, str], str]]]:
    """同模块软件/协同需求合批富化（0714 批次一 S1）。

    经济性：富化是调用量大头（EN 16314 实测 126 次调用累计 66 分钟），逐条调用把
    词表/文档背景/推理开销重复 N 遍；合批共享 prompt 骨架，条级上下文（条款原文/
    模板参考/答复）嵌进各自需求 JSON。正确性等价：缓存 key 逐条且与批组成无关；
    验证逐条同基线；槽位缺失/整批失败 → 该条回退单条路径重试，再失败才降级。

    性能（2026-08-14）：缺槽不再在批任务内**串行**单条重试（一个降级批会把 N 次单发
    连同放宽到 60×batch 的超时全部压在同一池线程上）——缺槽 job 原样返回给编排器
    (第二个返回值),由其以独立单条任务重发到同一线程池,重试获得真正的并发度。
    """
    from contextlib import nullcontext
    guard = lock if lock is not None else nullcontext()
    parts = [_software_prompt_parts(item, req, vocabulary, model, ctx, vocab_memo=vocab_memo)
             for item, req, ctx, _mode in jobs]
    results: list = [None] * len(jobs)
    pending: list[int] = []
    for i, (job, part) in enumerate(zip(jobs, parts)):
        item, req, ctx, _mode = job
        with guard:
            cached = cache.get(part[2])
        if cached is not None:
            ok, item_issues = _apply_llm_item(item, req, cached, ctx)
            results[i] = (item, ok, item_issues)
        else:
            pending.append(i)
    if pending:
        entries: list[dict[str, Any]] = []
        for slot, i in enumerate(pending):
            _item, _req, ctx, _mode = jobs[i]
            entry = dict(parts[i][1])
            entry["enrich_slot"] = slot
            if ctx.get("section_context"):
                entry["section_context"] = ctx["section_context"]
            if ctx.get("template_refs"):
                entry["template_refs"] = ctx["template_refs"]
            entries.append(entry)
        lead_ctx = jobs[pending[0]][2]
        prompt = build_analysis_prompt(entries, parts[pending[0]][0], "",
                                       exemplars=lead_ctx.get("exemplars", ""),
                                       negative_exemplars=lead_ctx.get("negative_exemplars", ""),
                                       answers="",
                                       doc_context=lead_ctx.get("doc_context", ""),
                                       section_context="",
                                       siblings=lead_ctx.get("siblings", ""),
                                       per_item_fields=True)
        mapped: dict[int, dict[str, Any]] = {}
        try:
            payload = chat(prompt["system"], prompt["user"])
            mapped = _map_batch_items(payload, len(pending))
        except Exception as exc:  # 整批失败非致命：逐条回退
            LOGGER.warning("合批富化调用失败，逐条回退: %s", exc)
        for slot, i in enumerate(pending):
            item, req, ctx, _mode = jobs[i]
            llm_item = mapped.get(slot)
            if llm_item is not None:
                with guard:
                    cache[parts[i][2]] = llm_item
                ok, item_issues = _apply_llm_item(item, req, llm_item, ctx)
                results[i] = (item, ok, item_issues)
            # 缺槽：不在此串行重试——交还编排器以独立单条任务重发（见 docstring）
    return ([r for r in results if r is not None],
            [jobs[i] for slot, i in enumerate(pending) if mapped.get(slot) is None])


def _build_hardware_prompt(source_reqs: list[dict[str, Any]]) -> dict[str, str]:
    system = "你是电表标准文档的硬件条目审查助手。"
    user = "\n".join([
        "以下条目已由规则/人工归类为 hardware。",
        "只输出硬件翻译和判断依据，不要输出软件研发指引、测试指引、验收标准或实现方案。",
        "输出 JSON 对象 {\"items\":[{\"hardware_translation\":\"...\",\"ownership_reason\":\"...\"}]}，"
        "items 与输入需求一一对应；输入条目若带 enrich_slot，每个 item 必须原样回填对应的 enrich_slot。",
        "hardware_translation: 将原文翻译为中文；若原文已是中文，则做简洁中文说明。",
        "ownership_reason: 用一句话说明为什么判断为硬件，必须引用原文中的关键词或设备/部件/制造主体依据。",
        "不得新增原文没有的容量、数量、协议编号、OBIS 或测试建议。",
        "需求 JSON:",
        json.dumps(source_reqs, ensure_ascii=False),
    ])
    return {"system": system, "user": user}


def _apply_hardware_item(
    item: dict[str, Any],
    source_req: dict[str, Any],
    llm_item: dict[str, Any],
) -> tuple[bool, list[str]]:
    """硬件翻译验证 + 采纳（单条与合批共用）：漂移护栏与字段清空语义不变。"""
    translation = str(llm_item.get("hardware_translation") or llm_item.get("hardware_summary") or "").strip()
    reason = str(llm_item.get("ownership_reason") or "").strip()
    # 漂移护栏（评审修正 2026-07-09）：这是新增的 LLM→交付物通路（hardware_items.md/批注视图），
    # 与其他富化路径同纪律。忠实翻译不会引入源文没有的编码/数字——出现即拒绝整条富化。
    # int 提取先剥枚举标号（test18：a) b) c) 转写成 1. 2. 3. 被误拒）;编码扫描仍严格不剥。
    from cosem_behavior_spec import extract_codes, extract_ints
    from text_normalize import strip_enum_markers
    source_basis = " ".join(
        str(source_req.get(k) or "") for k in ("source_quote", "description", "requirement", "title"))
    produced = f"{translation} {reason}"
    fabricated = sorted((extract_codes(produced) - extract_codes(source_basis))
                        | (extract_ints(strip_enum_markers(produced)) - extract_ints(source_basis)))
    if fabricated:
        return False, [f"硬件翻译含无据编码/数字，已保留原文说明: {', '.join(fabricated[:6])}"]
    if not translation and not reason:
        return False, ["LLM 硬件富化未返回可采纳的翻译或判断依据，已保留原文说明"]
    if translation:
        item["hardware_translation"] = translation
        item["hardware_summary"] = f"硬件项：{translation}"
    if reason:
        item["ownership_reason"] = reason
    item["software_requirement_text"] = ""
    item["developer_guidance"] = []
    item["design_options"] = []
    item["acceptance_criteria"] = []
    item["hardware_dependency"] = ""
    item["analysis_source"] = "llm"
    return True, []


def _llm_enrich_hardware_item(
    item: dict[str, Any],
    source_req: dict[str, Any],
    chat: ChatFn,
    cache: dict[str, Any],
    model: str,
    lock: Any = None,
) -> tuple[bool, list[str]]:
    """硬件项只做翻译/判断依据富化，绝不接收研发或测试字段。"""
    from contextlib import nullcontext

    guard = lock if lock is not None else nullcontext()
    key = _enrich_key(source_req, model, "hardware-only")
    with guard:
        llm_item = cache.get(key)
    if llm_item is None:
        prompt = _build_hardware_prompt([source_req])
        try:
            payload = chat(prompt["system"], prompt["user"])
        except Exception as exc:
            return False, [f"硬件翻译调用失败，已保留原文说明: {exc}"]
        llm_item = _first_item(payload)
        if llm_item is None:
            return False, ["硬件翻译返回空或格式非法，已保留原文说明"]
        with guard:
            cache[key] = llm_item
    return _apply_hardware_item(item, source_req, llm_item)


def _llm_enrich_hardware_batch(
    jobs: list[tuple[dict[str, Any], dict[str, Any], dict[str, str], str]],
    chat: ChatFn,
    cache: dict[str, Any],
    model: str,
    lock: Any = None,
) -> tuple[list[tuple[dict[str, Any], bool, list[str]]],
           list[tuple[dict[str, Any], dict[str, Any], dict[str, str], str]]]:
    """硬件翻译合批（0714 批次一 S1）——输出短，批量可比软件大；护栏/缓存语义同软件合批。
    缺槽同样交还编排器以独立单条任务重发（2026-08-14,不再批任务内串行重试）。"""
    from contextlib import nullcontext
    guard = lock if lock is not None else nullcontext()
    keys = [_enrich_key(req, model, "hardware-only") for _item, req, _ctx, _mode in jobs]
    results: list = [None] * len(jobs)
    pending: list[int] = []
    for i, (job, key) in enumerate(zip(jobs, keys)):
        item, req, _ctx, _mode = job
        with guard:
            cached = cache.get(key)
        if cached is not None:
            ok, item_issues = _apply_hardware_item(item, req, cached)
            results[i] = (item, ok, item_issues)
        else:
            pending.append(i)
    if pending:
        entries: list[dict[str, Any]] = []
        for slot, i in enumerate(pending):
            entry = dict(jobs[i][1])
            entry["enrich_slot"] = slot
            entries.append(entry)
        mapped: dict[int, dict[str, Any]] = {}
        prompt = _build_hardware_prompt(entries)
        try:
            payload = chat(prompt["system"], prompt["user"])
            mapped = _map_batch_items(payload, len(pending))
        except Exception as exc:  # 整批失败非致命：逐条回退
            LOGGER.warning("硬件翻译合批调用失败，逐条回退: %s", exc)
        for slot, i in enumerate(pending):
            item, req, _ctx, _mode = jobs[i]
            llm_item = mapped.get(slot)
            if llm_item is not None:
                with guard:
                    cache[keys[i]] = llm_item
                ok, item_issues = _apply_hardware_item(item, req, llm_item)
                results[i] = (item, ok, item_issues)
            # 缺槽：交还编排器以独立单条任务重发
    return ([r for r in results if r is not None],
            [jobs[i] for slot, i in enumerate(pending) if mapped.get(slot) is None])


def _run_enrichment(
    out_dir: Path,
    jobs: list[tuple[dict[str, Any], dict[str, Any], dict[str, str], str]],
    vocabulary: dict[str, Any],
    chat: ChatFn,
    cache: dict[str, Any],
    model: str,
    *,
    issues: list[dict[str, Any]],
    concurrency: int | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    batch_size: int = 1,
) -> tuple[int, int]:
    """并发跑 LLM 富化（真实规模的关键）。返回 (enriched, degraded)。

    288 条 × 推理模型逐条串行 ≈ 数小时且全程零落盘/零进度——真实 ABNT 跑挂过。三个对策：
    - **并发**：线程池，并发度与 AI 抽取同一来源（GUI 设置 → RATOMIZER_LLM_CONCURRENCY）。
    - **增量缓存**：每完成一个任务把**新增**键追加进 analyze_enrich_cache.jsonl（v2 起
      一行一键 + fsync,替代整 dict 重写的二次开销）——中途被杀/断网不丢已完成的调用。
    - **进度回调**：每完成一批上报（GUI 显示 n/total，不再像卡死）。
    0714 批次一 S1：batch_size>1 时同模块软件/协同需求合批、硬件翻译合批（输出短，
    批量 ×2 封顶 8）；批与批之间仍并发。单条尾巴走原单条路径。
    2026-08-14：合批缺槽/整批失败由编排器以**独立单条任务重发到同一线程池**（work_single），
    不再在批任务内串行重试——一个降级批不再占死一个池线程。
    每个任务相互独立：各线程只写自己的 item dict；cache/计数由锁保护。单任务失败不影响其余。
    """
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
    from threading import Lock

    from ai_extract import resolve_concurrency

    lock = Lock()
    enriched = 0
    degraded = 0
    completed = 0
    total = len(jobs)
    flushed_keys = set(cache.keys())   # 已在盘上的键不重放——每任务只追加本 run 新增键
    vocab_memo: dict[str, tuple[dict[str, Any], str]] = {}   # 模块词表瘦身+序列化记忆（FIX 6）

    def emit(done: int) -> None:
        if progress_callback is not None and total:
            progress_callback({"stage": "analyze", "completed": done, "total": total,
                               "percent": int(round(done * 100 / total)), "model": model})

    def work_single(job: tuple[dict[str, Any], dict[str, Any], dict[str, str], str]
                    ) -> tuple[list, list]:
        item, reviewed_req, ctx, mode = job
        if mode == "hardware":
            ok, item_issues = _llm_enrich_hardware_item(item, reviewed_req, chat, cache, model, lock=lock)
        else:
            ok, item_issues = _llm_enrich_item(item, reviewed_req, vocabulary, chat, cache, model,
                                               lock=lock, context=ctx, vocab_memo=vocab_memo)
        return [(item, ok, item_issues)], []

    def flush_new_cache_rows() -> None:
        with lock:
            new_items = [(key, value) for key, value in cache.items() if key not in flushed_keys]
        # 先存后记（2026-08-14 缺陷修复）：只有真正落盘的键才进 flushed_keys——瞬态写失败
        # 时本批保留,下次 flush 原样重试（一次失败绝不把已付费结果当作已落盘而丢失）。
        if _save_enrich_cache(out_dir, model, new_items):
            with lock:
                flushed_keys.update(key for key, _value in new_items)

    tasks: list = []
    if batch_size <= 1:
        tasks = [(lambda j=job: work_single(j)) for job in jobs]
    else:
        software = [j for j in jobs if j[3] != "hardware"]
        hardware = [j for j in jobs if j[3] == "hardware"]
        by_module: dict[str, list] = {}
        for job in software:
            by_module.setdefault(str(job[1].get("module") or ""), []).append(job)
        for module_jobs in by_module.values():
            for k in range(0, len(module_jobs), batch_size):
                chunk = module_jobs[k:k + batch_size]
                if len(chunk) == 1:
                    tasks.append(lambda j=chunk[0]: work_single(j))
                else:
                    tasks.append(lambda c=chunk: _llm_enrich_batch(
                        c, vocabulary, chat, cache, model, lock, vocab_memo))
        hw_batch = min(8, batch_size * 2)
        for k in range(0, len(hardware), hw_batch):
            chunk = hardware[k:k + hw_batch]
            if len(chunk) == 1:
                tasks.append(lambda j=chunk[0]: work_single(j))
            else:
                tasks.append(lambda c=chunk: _llm_enrich_hardware_batch(c, chat, cache, model, lock))

    emit(0)
    with ThreadPoolExecutor(max_workers=resolve_concurrency(concurrency)) as executor:
        from context_submit import submit_with_context

        futures = {submit_with_context(executor, task) for task in tasks}
        while futures:
            done_now, futures = wait(futures, return_when=FIRST_COMPLETED)
            for future in done_now:
                outcomes, retry_jobs = future.result()
                dones: list[int] = []
                with lock:
                    for item, ok, item_issues in outcomes:
                        enriched += 1 if ok else 0
                        degraded += 0 if ok else 1
                        completed += 1
                        dones.append(completed)
                        if item_issues:
                            issues.append({
                                "analysis_id": item.get("analysis_id"),
                                "source_requirement_ids": item.get("source_requirement_ids") or [],
                                "issues": item_issues,
                            })
                # 增量落盘：合批一次 ≥4 条真实调用，丢不起——每任务完成即追加新键
                flush_new_cache_rows()
                for done in dones:   # 进度契约保持逐条（GUI n/total 逐条推进）
                    emit(done)
                # 缺槽/整批失败重发：独立单条任务回同一线程池（不占批任务线程串行等待）
                for job in retry_jobs:
                    futures.add(submit_with_context(executor, work_single, job))
    # 终局 flush（2026-08-15 P2）：循环内最后一次 flush 失败时,其后不再有任务完成事件,
    # 本 run 已付费键会全部丢失、下个 run 重付费——循环结束后（含重发单条路径）必须再
    # 补一次。已全部落盘时 new_items 为空,save 直接短路返回,零额外开销。
    flush_new_cache_rows()
    return enriched, degraded


def _base_item(index: int, req: dict[str, Any], vocabulary: dict[str, Any]) -> dict[str, Any]:
    module = _module_or_unmapped(req, vocabulary)
    source_id = _source_requirement_id(req)
    description = str(req.get("title") or req.get("description") or req.get("requirement") or "").strip()
    requirement_text = str(req.get("description") or req.get("requirement") or "").strip()
    developer_guidance = [str(value).strip() for value in _as_list(req.get("dev_guidance") or req.get("developer_guidance")) if str(value).strip()]
    design_options = [str(value).strip() for value in _as_list(req.get("design_options")) if str(value).strip()]
    acceptance_criteria = [str(value).strip() for value in _as_list(req.get("acceptance_criteria")) if str(value).strip()]
    assumptions = [str(value).strip() for value in _as_list(req.get("assumptions")) if str(value).strip()]

    return {
        "analysis_id": build_analysis_id(index),
        "source_kind": "ai_requirement",
        "source_requirement_type": str(req.get("type") or req.get("requirement_type") or ""),
        "source_requirement_ids": [str(value) for value in _as_list(req.get("source_ai_requirement_ids")) if str(value).strip()] or [source_id],
        "source_block_ids": [str(value) for value in _as_list(req.get("source_block_ids"))],
        "module": module,
        "submodule": str(req.get("module") or module),
        "template_match": "matched" if module in vocabulary.get("modules", []) else "unmapped",
        "description": description,
        "requirement": requirement_text,
        "software_requirement_text": requirement_text,
        "developer_guidance": developer_guidance,
        "design_options": design_options,
        "hardware_dependency": "",
        "acceptance_criteria": acceptance_criteria,
        "open_questions": [],
        "assumptions": assumptions,
        "objective": str(req.get("objective") or "").strip(),
        "behaviors": [str(value).strip() for value in _as_list(req.get("behaviors")) if str(value).strip()],
        "lifecycle_behaviors": [dict(value) for value in _as_list(req.get("lifecycle_behaviors")) if isinstance(value, dict)],
        "source_modules": [str(value).strip() for value in _as_list(req.get("source_modules")) if str(value).strip()],
        "preconditions": [str(value).strip() for value in _as_list(req.get("preconditions")) if str(value).strip()],
        "data_constraints": [str(value).strip() for value in _as_list(req.get("data_constraints")) if str(value).strip()],
        "variants": [dict(value) for value in _as_list(req.get("variants")) if isinstance(value, dict)],
        "exceptions": [str(value).strip() for value in _as_list(req.get("exceptions")) if str(value).strip()],
        "related_dlms_objects": [str(value).strip() for value in _as_list(req.get("related_dlms_objects")) if str(value).strip()],
        "functional_requirement_id": str(req.get("functional_requirement_id") or "").strip(),
        "functional_key": str(req.get("functional_key") or "").strip(),
        "merge_method": str(req.get("merge_method") or "").strip(),
        "merge_confidence": req.get("merge_confidence"),
        "synthesis_reason": str(req.get("synthesis_reason") or "").strip(),
        "conflict_flags": [str(value).strip() for value in _as_list(req.get("conflict_flags")) if str(value).strip()],
        "notes": [],
        "threshold_table": req.get("threshold_table") if isinstance(req.get("threshold_table"), dict) else None,
        "analysis_source": "deterministic",  # LLM 富化成功则改写为 "llm"（叙述字段来源追溯）
        "source_quote": str(req.get("source_quote") or "\n".join(str(value) for value in _as_list(req.get("source_quotes")) if str(value).strip())),
        "source_section": str(req.get("source_section") or " / ".join(str(value) for value in _as_list(req.get("source_sections")) if str(value).strip())),
    }


def _normalize_hardware_item(item: dict[str, Any], req: dict[str, Any]) -> None:
    source_text = _source_text_for_summary(req)
    item["software_requirement_text"] = ""
    item["developer_guidance"] = []
    item["acceptance_criteria"] = []
    item["hardware_dependency"] = ""
    item["hardware_translation"] = _hardware_translation(source_text)
    item["hardware_summary"] = f"硬件项：{item['hardware_translation']}"
    reason = str(item.get("ownership_reason") or "").strip()
    if reason:
        item["ownership_reason"] = reason
    else:
        item["ownership_reason"] = "已归类为硬件项；仅保留原文翻译/说明，不生成软件研发或测试指引。"


def _source_text_for_summary(req: dict[str, Any]) -> str:
    return next(
        (str(req.get(field) or "").strip()
         for field in ("source_quote", "description", "requirement", "title")
         if str(req.get(field) or "").strip()),
        "",
    )


def _hardware_translation(text: str) -> str:
    if not text:
        return "原文未提供可翻译内容。"
    return text


def _source_requirement_id(req: dict[str, Any]) -> str:
    # 与裁决回流/批注视图共用同一主键函数（ai_review_actions.source_ai_requirement_id），
    # 三处各写一份迟早分叉——这正是 io_utils 去重要防的问题。
    return source_ai_requirement_id(req)


def _is_rejected(state: dict[str, Any] | None) -> bool:
    return str((state or {}).get("status") or "").strip() == "rejected"


def _apply_module_override(req: dict[str, Any], state: dict[str, Any] | None) -> dict[str, Any]:
    module_override = str((state or {}).get("module_override") or "").strip()
    if not module_override:
        return req
    reviewed_req = dict(req)
    reviewed_req["module"] = module_override
    return reviewed_req


def _module_or_unmapped(req: dict[str, Any], vocabulary: dict[str, Any]) -> str:
    module = str(req.get("module") or "").strip()
    if module in vocabulary.get("modules", []):
        return module
    return module or "unmapped"


def _write_report(path: Path, rows: list[dict[str, Any]], title: str, *, co_design: bool = False) -> None:
    lines = [f"# {title}", ""]
    if not rows:
        lines.extend(["No items.", ""])
    for row in rows:
        lines.append(f"## {row.get('analysis_id')} {row.get('description') or ''}".rstrip())
        if co_design:
            # 待澄清渲染兜底（审计 r2 S5）：四字段与硬件依赖同走 clarify 通道——标了待澄清
            # 且留有原始候选时带"未经依据校验+候选"标注透出，不再裸值输出
            lines.extend([
                f"- 软件需求: {clarify_display_text(row, 'software_requirement_text') or row.get('requirement') or ''}",
                f"- 为什么判断为协同设计: {row.get('ownership_reason') or ''}",
            ])
            for field, label in (("developer_guidance", "研发指引"),
                                 ("design_options", "设计候选"),
                                 ("acceptance_criteria", "验收点")):
                fallback = _fallback_lines(row, field, f"- {label}: ")
                if fallback:
                    lines.extend(fallback)
                else:
                    lines.extend(f"- {label}: {value}" for value in row.get(field) or [])
            # 硬件依赖透出（审计 P1-b）——过 clarify_display_text：待澄清时带
            # "未经依据校验+原始候选"标注，仅在字段非空时输出
            hardware_dependency = clarify_display_text(row, "hardware_dependency").strip()
            if hardware_dependency:
                lines.append(f"- 硬件依赖: {hardware_dependency}")
        else:
            lines.extend([
                f"- 中文翻译/说明: {row.get('hardware_summary') or row.get('hardware_translation') or row.get('description') or ''}",
                f"- 为什么判断为硬件: {row.get('ownership_reason') or ''}",
            ])
        lines.extend([
            f"- Source: {', '.join(str(value) for value in row.get('source_requirement_ids') or [])}",
            f"- Source quote: {row.get('source_quote') or ''}",
            "",
        ])
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_compliance_report(path: Path, rows: list[dict[str, Any]]) -> None:
    """Render the independent compliance delivery list without deriving implementation advice."""
    lines = ["# 合规交付项", ""]
    if not rows:
        lines.extend(["无。", ""])
    for row in rows:
        lines.append(f"## {row.get('id') or ''} {row.get('title') or ''}".rstrip())
        if row.get("instrument"):
            lines.append(f"- 法规/标准依据: {row['instrument']}")
        obligations = row.get("obligations") or []
        if obligations:
            lines.append("- 交付义务:")
            for obligation in obligations:
                label = str(obligation.get("label") or "").strip()
                prefix = f"{label} " if label else ""
                lines.append(f"  - {prefix}{obligation.get('text') or ''}".rstrip())
        lines.extend([
            f"- 来源章节: {row.get('source_section') or ''}",
            f"- 原文依据: {row.get('source_quote') or ''}",
            "",
        ])
    path.write_text("\n".join(lines), encoding="utf-8")


def _as_list(value: Any) -> list[Any]:
    """载荷归一为 list 形态（None→[]、list 原样、tuple→list、其它标量含 str→单元素列表）。
    与 requirements_analysis_agent._as_list 同口径（防幻觉红线 2026-08-15：str 列表字段
    载荷绝不逐字符迭代）——两处实现必须保持一致，tests.test_analyze_unfounded 有 parity 钉。"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run requirements analysis agent.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--route", default="stub", choices=["stub", "openai_compatible"])
    parser.add_argument("--template", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_requirements_analysis(args.out, route=args.route, template_path=args.template)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
