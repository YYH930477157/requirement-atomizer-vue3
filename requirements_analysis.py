from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from ai_review_actions import read_ai_review_states, source_ai_requirement_id
from io_utils import read_jsonl
from requirements_analysis_agent import build_analysis_prompt, validate_llm_item
from requirements_analysis_excel import write_software_requirements_xlsx
from requirements_analysis_rules import classify_ownership
from requirements_analysis_schema import (
    OWNERSHIP_CO_DESIGN,
    OWNERSHIP_HARDWARE,
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
ANALYZE_PROMPT_VERSION = "analyze-llm-v6"  # v6：冻结归属注入 prompt（模型不再重判,只按给定归属定正文深度）；v5：注入文档背景/条款原文/相邻需求,正文连贯成文（2026-07-12 富化深度）
ANALYZE_MIN_MAX_TOKENS = 8192  # 连贯多段正文+更长输入;推理模型思维链挤占,低于下限 JSON 截断
ANALYZE_ENRICH_CACHE = "analyze_enrich_cache.json"
# W1 上下文注入帽：条款原文与 prompt/指纹/校验三处用同一字符串（单一构造点）
SECTION_CONTEXT_MAX_CHARS = 2000
SIBLING_TITLES_MAX = 8
# 合批富化（0714 批次一 S1）：同模块多条一次调用——prompt 骨架/词表/推理开销只花一遍
# （EN 16314 实测富化 126 次调用累计 66 分钟）。4 是推理模型输出预算与超时的稳妥点；
# 1=回到逐条。硬件翻译输出短，批量 ×2 封顶 8。
ANALYZE_BATCH_ENV = "RATOMIZER_ANALYZE_BATCH"
DEFAULT_ANALYZE_BATCH = 4
MAX_ANALYZE_BATCH = 8


def _resolve_analyze_batch(explicit: int | None = None) -> int:
    raw: Any = explicit if explicit is not None else os.environ.get(ANALYZE_BATCH_ENV)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_ANALYZE_BATCH
    return max(1, min(MAX_ANALYZE_BATCH, value))
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
    if synthesized_path.exists():
        try:
            synthesized_payload = json.loads(synthesized_path.read_text(encoding="utf-8"))
            requirements = synthesized_payload.get("items") if isinstance(synthesized_payload, dict) else None
        except (OSError, json.JSONDecodeError):
            requirements = None
        # C4（0710 评审）：消费端血统校验（§43）——陈旧/异源 functional_requirements.json
        # 会被静默采信（链内指纹只管要不要重跑，不做产物互一致校验）。producer 家族不符
        # 即告警并回退逐原子输入；只校验家族名不校验版本号（版本演进由指纹层负责失效）。
        if isinstance(requirements, list) and isinstance(synthesized_payload, dict):
            producer = str(synthesized_payload.get("producer") or "")
            if not producer.startswith("functional-synthesis"):
                LOGGER.warning("functional_requirements.json producer 异常（%s），回退逐原子输入", producer or "缺失")
                requirements = None
        if not isinstance(requirements, list):
            requirements = read_jsonl(source_path)
    else:
        requirements = read_jsonl(source_path)
    # 容错读（坏行跳过）+ 最新覆盖，与裁决回流同一读取器——单条撕裂写不弄死整跑
    states = read_ai_review_states(out_dir)
    vocabulary = extract_template_vocabulary(template_path)
    # 公司标准做法知识：从模板现读（不进仓不落索引），富化时按模块+词面相关注入
    knowledge = extract_template_knowledge(template_path)
    # 裁决样本库（env 指路，未配置=空库零注入）+ 澄清答复（评审会回灌，权威客户输入）
    from adjudication_bank import load_bank, render_exemplars, resolve_bank_path, select_exemplars
    from clarification_report import load_answers
    bank = load_bank(resolve_bank_path())
    answers_by_source: dict[str, list[dict[str, Any]]] = {}
    for (sid, _q), row in load_answers(out_dir).items():
        if row.get("adopted", True) and sid:
            answers_by_source.setdefault(sid, []).append(row)

    # LLM 富化层：注入的 chat 优先（测试/嵌入）；否则请求 LLM 路由时按 pipeline 解析端点，
    # 端点缺失则降级为纯确定性（executed_route=stub），出处如实记录。
    active_chat, model = _resolve_chat(route, chat, pipeline_path)
    executed_route = STUB_ROUTE
    note = ""
    if route != STUB_ROUTE and active_chat is None:
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
                    module_ctx_memo[module_name] = (
                        "\n".join(f"- {t}" for t in all_titles[:SIBLING_TITLES_MAX]),
                        render_exemplars(select_exemplars(bank, module_name, " ".join(all_titles))),
                    )
                siblings_text, exemplars = module_ctx_memo[module_name]
            else:
                req_text = " ".join(str(reviewed_req.get(k) or "") for k in ("title", "description", "source_quote"))
                exemplars = render_exemplars(select_exemplars(bank, module_name, req_text))
                own_title = str(reviewed_req.get("title") or "").strip()[:40]
                siblings = [t for t in titles_by_module.get(module_name, [])
                            if t != own_title][:SIBLING_TITLES_MAX]
                siblings_text = "\n".join(f"- {t}" for t in siblings)
            ctx = {"template_refs": render_template_references(refs),
                   "exemplars": exemplars,
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
        _save_enrich_cache(out_dir, model, enrich_cache)
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
        "enriched": enriched_count,
        "enrich_degraded": degraded_count,
        "items": items,
        "issues": issues,
    }
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

    result = {
        "kind": "requirements_analysis",
        "analysis_count": len(items),
        "issues": len(issues),
        "route": executed_route,
        "route_requested": route,
        "enriched": enriched_count,
        "enrich_degraded": degraded_count,
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
        model,
    ])
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def _load_enrich_cache(out_dir: Path, model: str) -> dict[str, Any]:
    path = out_dir / ANALYZE_ENRICH_CACHE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    # prompt 版本/模型漂移则弃用旧缓存（防复用不同模型/prompt 的产物）
    meta = data.get("_meta") or {}
    if meta.get("prompt") != ANALYZE_PROMPT_VERSION or meta.get("model") != model:
        return {}
    items = data.get("items")
    return items if isinstance(items, dict) else {}


def _save_enrich_cache(out_dir: Path, model: str, cache: dict[str, Any]) -> None:
    path = out_dir / ANALYZE_ENRICH_CACHE
    payload = {"_meta": {"prompt": ANALYZE_PROMPT_VERSION, "model": model}, "items": cache}
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:  # pragma: no cover - 缓存写失败不致命
        LOGGER.warning("富化缓存写入失败（忽略）: %s", exc)


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
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """key/prompt 载荷单一构造点（单条与合批共用）。

    返回 (slim_vocab, prompt_req, cache_key)。key 只由本条内容 + 模块级/条级注入构成，
    与批组成无关——合批与否、批里还有谁，都不改变本条的缓存命中。
    冻结归属注入（0714）：prompt 只写不判；归属变化（专家改判）→ key 变 → 重富化。
    """
    from requirements_analysis_agent import slim_vocabulary
    slim_vocab = slim_vocabulary(vocabulary, str(source_req.get("module") or ""))
    frozen_ownership = str(item.get("ownership") or "")
    prompt_req = dict(source_req)
    prompt_req["ownership"] = frozen_ownership
    context_basis = "".join([ctx.get(k, "") for k in (
        "template_refs", "exemplars", "answers", "doc_context", "section_context", "siblings"
    )] + [json.dumps(slim_vocab, ensure_ascii=False), frozen_ownership])
    return slim_vocab, prompt_req, _enrich_key(source_req, model, context_basis)


def _apply_llm_item(
    item: dict[str, Any],
    source_req: dict[str, Any],
    llm_item: dict[str, Any],
    ctx: dict[str, str],
) -> tuple[bool, list[str]]:
    """验证 + 采纳（单条与合批共用）——合批不放宽任何护栏：validate 逐条，
    基线只含本条自己的条款原文/答复，批内其它条的数值不进有据基线
    （模型跨条借数即硬拒/软标）。"""
    drift = validate_llm_item(llm_item, source_req, template_text=ctx.get("template_refs", ""),
                              section_context=ctx.get("section_context", ""),
                              context_text=ctx.get("doc_context", ""))
    fabricated_codes = [d for d in drift if d.startswith("fabricated code")]
    if fabricated_codes:
        return False, [f"LLM 富化编造结构编码，已拒绝并降级: {'; '.join(fabricated_codes)}"]

    accepted = False
    for field in _ENRICH_FIELDS_TEXT:
        value = str(llm_item.get(field) or "").strip()
        if value:
            item[field] = value
            accepted = True
    for field in _ENRICH_FIELDS_LIST:
        values = [str(x).strip() for x in _as_list(llm_item.get(field)) if str(x).strip()]
        if values:
            item[field] = values
            accepted = True
    reason = str(llm_item.get("ownership_reason") or "").strip()
    # 恒真 guard 修复（2026-07-12）：classify_ownership 对所有类别都前置填了规则原因,
    # 旧条件 `not item.get("ownership_reason")` 恒假 → 软件/协同的 LLM 原因永不被采纳。
    # 采纳三条件：原因非空;LLM 若自带 ownership 须与冻结归属一致（不一致=模型想借"原因"
    # 字段改写归属叙事,保留规则原因并记 issue）;人工覆盖过的归属其叙事权威不被 LLM 冲掉。
    # 归属值/置信度仍冻结;reason 本就在 validate_llm_item 的 analysis_text 扫描内（编码硬拒）。
    reason_issues: list[str] = []
    if reason and str(item.get("ownership_source") or "") != "reviewer_override":
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
        return False, ["LLM 富化未返回可采纳的叙述字段，已降级为确定性"]
    item["analysis_source"] = "llm"

    soft = [d for d in drift if not d.startswith("fabricated code")]
    # 软标必须随交付物同行（2026-07-08 审计 B1）：此前只进 run 级 issues（excel/成文不读），
    # 编造数字以零可见标记落进公司模板成文 xlsx。现在钉在 item 上，_notes_text/成文同列渲染。
    if soft:
        item["enrichment_warnings"] = soft
    else:
        item.pop("enrichment_warnings", None)   # 重富化后旧警告不残留
    issues = reason_issues + ([f"富化软提示（数字/遗漏漂移，未阻断，请对照 source_quote 核）: {'; '.join(soft)}"]
                              if soft else [])
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
) -> tuple[bool, list[str]]:
    """用 LLM 填充叙述字段（software_requirement_text 等），结构字段一律不动。

    防幻觉红线：validate_llm_item 检出**编造**的 OBIS/编码/数字（换位 OBIS 也逃不掉）→ 整条
    富化拒绝、item 保持确定性空值、记 issue；**遗漏**类是软提示，不阻断富化。任何调用/解析失败
    都非致命：该条降级为确定性，返回 (False, [原因])。lock：并发跑时保护共享 cache 的读写。
    """
    from contextlib import nullcontext
    guard = lock if lock is not None else nullcontext()

    ctx = context or {}
    slim_vocab, prompt_req, key = _software_prompt_parts(item, source_req, vocabulary, model, ctx)
    with guard:
        llm_item = cache.get(key)
    if llm_item is None:
        prompt = build_analysis_prompt([prompt_req], slim_vocab, ctx.get("template_refs", ""),
                                       exemplars=ctx.get("exemplars", ""),
                                       answers=ctx.get("answers", ""),
                                       doc_context=ctx.get("doc_context", ""),
                                       section_context=ctx.get("section_context", ""),
                                       siblings=ctx.get("siblings", ""))
        try:
            payload = chat(prompt["system"], prompt["user"])
        except Exception as exc:  # 调用失败非致命
            return False, [f"LLM 富化调用失败，已降级为确定性: {exc}"]
        llm_item = _first_item(payload)
        if llm_item is None:
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
) -> list[tuple[dict[str, Any], bool, list[str]]]:
    """同模块软件/协同需求合批富化（0714 批次一 S1）。

    经济性：富化是调用量大头（EN 16314 实测 126 次调用累计 66 分钟），逐条调用把
    词表/文档背景/推理开销重复 N 遍；合批共享 prompt 骨架，条级上下文（条款原文/
    模板参考/答复）嵌进各自需求 JSON。正确性等价：缓存 key 逐条且与批组成无关；
    验证逐条同基线；槽位缺失/整批失败 → 该条回退单条路径重试，再失败才降级。
    """
    from contextlib import nullcontext
    guard = lock if lock is not None else nullcontext()
    parts = [_software_prompt_parts(item, req, vocabulary, model, ctx)
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
            else:
                ok, item_issues = _llm_enrich_item(item, req, vocabulary, chat, cache, model,
                                                   lock=lock, context=ctx)
            results[i] = (item, ok, item_issues)
    return [r for r in results if r is not None]


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
) -> list[tuple[dict[str, Any], bool, list[str]]]:
    """硬件翻译合批（0714 批次一 S1）——输出短，批量可比软件大；护栏/缓存语义同软件合批。"""
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
            else:
                ok, item_issues = _llm_enrich_hardware_item(item, req, chat, cache, model, lock=lock)
            results[i] = (item, ok, item_issues)
    return [r for r in results if r is not None]


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
    - **增量缓存**：每完成一个任务落一次 analyze_enrich_cache.json——中途被杀/断网不丢已完成的调用。
    - **进度回调**：每完成一批上报（GUI 显示 n/total，不再像卡死）。
    0714 批次一 S1：batch_size>1 时同模块软件/协同需求合批、硬件翻译合批（输出短，
    批量 ×2 封顶 8）；批与批之间仍并发。单条尾巴走原单条路径。
    每个任务相互独立：各线程只写自己的 item dict；cache/计数由锁保护。单任务失败不影响其余。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from threading import Lock

    from ai_extract import resolve_concurrency

    lock = Lock()
    enriched = 0
    degraded = 0
    completed = 0
    total = len(jobs)

    def emit(done: int) -> None:
        if progress_callback is not None and total:
            progress_callback({"stage": "analyze", "completed": done, "total": total,
                               "percent": int(round(done * 100 / total)), "model": model})

    def work_single(job: tuple[dict[str, Any], dict[str, Any], dict[str, str], str]) -> list:
        item, reviewed_req, ctx, mode = job
        if mode == "hardware":
            ok, item_issues = _llm_enrich_hardware_item(item, reviewed_req, chat, cache, model, lock=lock)
        else:
            ok, item_issues = _llm_enrich_item(item, reviewed_req, vocabulary, chat, cache, model,
                                               lock=lock, context=ctx)
        return [(item, ok, item_issues)]

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
                    tasks.append(lambda c=chunk: _llm_enrich_batch(c, vocabulary, chat, cache, model, lock))
        hw_batch = min(8, batch_size * 2)
        for k in range(0, len(hardware), hw_batch):
            chunk = hardware[k:k + hw_batch]
            if len(chunk) == 1:
                tasks.append(lambda j=chunk[0]: work_single(j))
            else:
                tasks.append(lambda c=chunk: _llm_enrich_hardware_batch(c, chat, cache, model, lock))

    emit(0)
    with ThreadPoolExecutor(max_workers=resolve_concurrency(concurrency)) as executor:
        futures = [executor.submit(task) for task in tasks]
        for future in as_completed(futures):
            outcomes = future.result()
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
                cache_snapshot = dict(cache)
            # 增量落盘：合批一次 ≥4 条真实调用，丢不起——每任务完成即写
            _save_enrich_cache(out_dir, model, cache_snapshot)
            for done in dones:   # 进度契约保持逐条（GUI n/total 逐条推进）
                emit(done)
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
            lines.extend([
                f"- 软件需求: {row.get('software_requirement_text') or row.get('requirement') or ''}",
                f"- 为什么判断为协同设计: {row.get('ownership_reason') or ''}",
            ])
            lines.extend(f"- 研发指引: {value}" for value in row.get("developer_guidance") or [])
            lines.extend(f"- 设计候选: {value}" for value in row.get("design_options") or [])
            lines.extend(f"- 验收点: {value}" for value in row.get("acceptance_criteria") or [])
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


def _as_list(value: Any) -> list[Any]:
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
