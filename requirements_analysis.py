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
ANALYZE_PROMPT_VERSION = "analyze-llm-v3"  # v3：assumptions 契约——推导前提必须显性记录（缓存失效重富化）
ANALYZE_MIN_MAX_TOKENS = 6144  # 与 ai_extract 同：推理模型（如 mimo-v2.5-pro）会输出思维链，2048 会截断 JSON
ANALYZE_ENRICH_CACHE = "analyze_enrich_cache.json"
# 确定性分析层（规则+模板+裁决）恒在；openai_compatible 追加 LLM 富化层，只填叙述字段、
# 结构/归属/路由字段全冻结。请求 LLM 但端点未配置时如实降级并记 route_requested（出处诚实）。
STUB_ROUTE = "stub"
DEGRADE_NOTE = "openai_compatible 端点未配置，本次按规则/模板/裁决确定性运行（未做 LLM 富化）"
# LLM 只允许填这些叙述字段；OBIS/class/访问位/归属/id 等结构字段永不被 LLM 覆盖（防幻觉红线）
_ENRICH_FIELDS_TEXT = ("software_requirement_text", "hardware_dependency")
_ENRICH_FIELDS_LIST = ("developer_guidance", "acceptance_criteria", "open_questions", "assumptions")
OUTPUT_FILES = [
    "software_requirements.xlsx",
    "engineering_analysis.json",
    "hardware_items.md",
    "co_design_items.md",
]


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
    source_path = out_dir / "ai_requirements.jsonl"
    if not source_path.exists():
        # 缺输入必须响亮失败：静默产出"0 条 0 问题"的空交付物会掩盖打错目录（仓库纪律）
        raise FileNotFoundError(
            f"ai_requirements.jsonl not found in {out_dir} — 请先运行「AI 抽取」再做需求分析")
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
    executed_route = "openai_compatible" if active_chat is not None else STUB_ROUTE
    note = ""
    if route != STUB_ROUTE and active_chat is None:
        note = DEGRADE_NOTE
        LOGGER.warning(note)
    enrich_cache = _load_enrich_cache(out_dir, model) if active_chat is not None else {}
    enriched_count = 0
    degraded_count = 0
    enrich_jobs: list[tuple[dict[str, Any], dict[str, Any], dict[str, str], str]] = []

    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for req in requirements:
        source_id = _source_requirement_id(req)
        state = states.get(source_id)
        if _is_rejected(state):
            continue
        reviewed_req = _apply_module_override(req, state)
        item = _base_item(len(items) + 1, reviewed_req, vocabulary)
        item.update(classify_ownership(reviewed_req))
        try:
            item = apply_ownership_override(item, state)
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
        ans_rows = answers_by_source.get(source_id) or []
        if ans_rows:
            answers_text = "；".join(f"问：{r.get('question')} 答：{r.get('answer')}" for r in ans_rows)
            reviewed_req = dict(reviewed_req)
            reviewed_req["clarification_answers_text"] = answers_text   # 进有据基线（validate 读它）
            item["notes"] = list(item.get("notes") or []) + [f"客户答复：{r.get('answer')}" for r in ans_rows]
        if active_chat is not None:
            refs = select_template_references(knowledge, reviewed_req)
            req_text = " ".join(str(reviewed_req.get(k) or "") for k in ("title", "description", "source_quote"))
            exemplars = render_exemplars(select_exemplars(bank, str(reviewed_req.get("module") or ""), req_text))
            ctx = {"template_refs": render_template_references(refs),
                   "exemplars": exemplars,
                   "answers": reviewed_req.get("clarification_answers_text") or ""}
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
            issues=issues, concurrency=concurrency, progress_callback=progress_callback)
        _save_enrich_cache(out_dir, model, enrich_cache)

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
    context_basis = "".join(ctx.get(k, "") for k in ("template_refs", "exemplars", "answers"))
    key = _enrich_key(source_req, model, context_basis)
    with guard:
        llm_item = cache.get(key)
    if llm_item is None:
        prompt = build_analysis_prompt([source_req], vocabulary, ctx.get("template_refs", ""),
                                       exemplars=ctx.get("exemplars", ""),
                                       answers=ctx.get("answers", ""))
        try:
            payload = chat(prompt["system"], prompt["user"])
        except Exception as exc:  # 调用失败非致命
            return False, [f"LLM 富化调用失败，已降级为确定性: {exc}"]
        llm_item = _first_item(payload)
        if llm_item is None:
            return False, ["LLM 富化返回空或格式非法，已降级为确定性"]
        with guard:
            cache[key] = llm_item

    drift = validate_llm_item(llm_item, source_req, template_text=ctx.get("template_refs", ""))
    # 与 ai_extract 双引擎同一分级纪律：**编码漂移**（OBIS/hex/事件号）严格拒绝——"错一位即
    # 严重"；**普通整数漂移**（散文里的步骤序号"1.2.3."、复述计数等）只软标记不阻断——结构字段
    # 已确定性冻结、source_quote 随交付物同行可核，把整数当硬拒会误伤合格富化（真实 A/B 验证）。
    fabricated_codes = [d for d in drift if d.startswith("fabricated code")]
    if fabricated_codes:
        return False, [f"LLM 富化编造结构编码，已拒绝并降级: {'; '.join(fabricated_codes)}"]

    for field in _ENRICH_FIELDS_TEXT:
        value = str(llm_item.get(field) or "").strip()
        if value:
            item[field] = value
    for field in _ENRICH_FIELDS_LIST:
        values = [str(x).strip() for x in _as_list(llm_item.get(field)) if str(x).strip()]
        if values:
            item[field] = values
    reason = str(llm_item.get("ownership_reason") or "").strip()
    if reason and not item.get("ownership_reason"):
        item["ownership_reason"] = reason
    item["analysis_source"] = "llm"

    soft = [d for d in drift if not d.startswith("fabricated code")]
    # 软标必须随交付物同行（2026-07-08 审计 B1）：此前只进 run 级 issues（excel/成文不读），
    # 编造数字以零可见标记落进公司模板成文 xlsx。现在钉在 item 上，_notes_text/成文同列渲染。
    if soft:
        item["enrichment_warnings"] = soft
    else:
        item.pop("enrichment_warnings", None)   # 重富化后旧警告不残留
    return True, ([f"富化软提示（数字/遗漏漂移，未阻断，请对照 source_quote 核）: {'; '.join(soft)}"]
                  if soft else [])


def _build_hardware_prompt(source_req: dict[str, Any]) -> dict[str, str]:
    system = "你是电表标准文档的硬件条目审查助手。"
    user = "\n".join([
        "该条目已由规则/人工归类为 hardware。",
        "只输出硬件翻译和判断依据，不要输出软件研发指引、测试指引、验收标准或实现方案。",
        "输出 JSON 对象 {\"items\":[{\"hardware_translation\":\"...\",\"ownership_reason\":\"...\"}]}。",
        "hardware_translation: 将原文翻译为中文；若原文已是中文，则做简洁中文说明。",
        "ownership_reason: 用一句话说明为什么判断为硬件，必须引用原文中的关键词或设备/部件/制造主体依据。",
        "不得新增原文没有的容量、数量、协议编号、OBIS 或测试建议。",
        "需求 JSON:",
        json.dumps([source_req], ensure_ascii=False),
    ])
    return {"system": system, "user": user}


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
        prompt = _build_hardware_prompt(source_req)
        try:
            payload = chat(prompt["system"], prompt["user"])
        except Exception as exc:
            return False, [f"硬件翻译调用失败，已保留原文说明: {exc}"]
        llm_item = _first_item(payload)
        if llm_item is None:
            return False, ["硬件翻译返回空或格式非法，已保留原文说明"]
        with guard:
            cache[key] = llm_item

    translation = str(llm_item.get("hardware_translation") or llm_item.get("hardware_summary") or "").strip()
    reason = str(llm_item.get("ownership_reason") or "").strip()
    # 漂移护栏（评审修正 2026-07-09）：这是新增的 LLM→交付物通路（hardware_items.md/批注视图），
    # 与其他富化路径同纪律。忠实翻译不会引入源文没有的编码/数字——出现即拒绝整条富化。
    from cosem_behavior_spec import extract_codes, extract_ints
    source_basis = " ".join(
        str(source_req.get(k) or "") for k in ("source_quote", "description", "requirement", "title"))
    produced = f"{translation} {reason}"
    fabricated = sorted((extract_codes(produced) - extract_codes(source_basis))
                        | (extract_ints(produced) - extract_ints(source_basis)))
    if fabricated:
        return False, [f"硬件翻译含无据编码/数字，已保留原文说明: {', '.join(fabricated[:6])}"]
    if translation:
        item["hardware_translation"] = translation
        item["hardware_summary"] = f"硬件项：{translation}"
    if reason:
        item["ownership_reason"] = reason
    item["software_requirement_text"] = ""
    item["developer_guidance"] = []
    item["acceptance_criteria"] = []
    item["hardware_dependency"] = ""
    item["analysis_source"] = "llm"
    return True, []


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
) -> tuple[int, int]:
    """并发跑 LLM 富化（真实规模的关键）。返回 (enriched, degraded)。

    288 条 × 推理模型逐条串行 ≈ 数小时且全程零落盘/零进度——真实 ABNT 跑挂过。三个对策：
    - **并发**：线程池，并发度与 AI 抽取同一来源（GUI 设置 → RATOMIZER_LLM_CONCURRENCY）。
    - **增量缓存**：每完成 10 条落一次 analyze_enrich_cache.json——中途被杀/断网不丢已完成的调用。
    - **进度回调**：每完成一条上报（GUI 显示 n/total，不再像卡死）。
    每条相互独立：各线程只写自己的 item dict；cache/计数由锁保护。单条失败不影响其余。
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

    def work(job: tuple[dict[str, Any], dict[str, Any], dict[str, str], str]) -> tuple[dict[str, Any], bool, list[str]]:
        item, reviewed_req, ctx, mode = job
        if mode == "hardware":
            ok, item_issues = _llm_enrich_hardware_item(item, reviewed_req, chat, cache, model, lock=lock)
        else:
            ok, item_issues = _llm_enrich_item(item, reviewed_req, vocabulary, chat, cache, model,
                                               lock=lock, context=ctx)
        return item, ok, item_issues

    emit(0)
    with ThreadPoolExecutor(max_workers=resolve_concurrency(concurrency)) as executor:
        futures = [executor.submit(work, job) for job in jobs]
        for future in as_completed(futures):
            item, ok, item_issues = future.result()
            with lock:
                enriched += 1 if ok else 0
                degraded += 0 if ok else 1
                completed += 1
                done = completed
                if item_issues:
                    issues.append({
                        "analysis_id": item.get("analysis_id"),
                        "source_requirement_ids": item.get("source_requirement_ids") or [],
                        "issues": item_issues,
                    })
                cache_snapshot = dict(cache) if completed % 10 == 0 else None
            if cache_snapshot is not None:  # 增量落盘：中途被杀不丢已完成的真实调用
                _save_enrich_cache(out_dir, model, cache_snapshot)
            emit(done)
    return enriched, degraded


def _base_item(index: int, req: dict[str, Any], vocabulary: dict[str, Any]) -> dict[str, Any]:
    module = _module_or_unmapped(req, vocabulary)
    source_id = _source_requirement_id(req)
    description = str(req.get("title") or req.get("description") or req.get("requirement") or "").strip()
    requirement_text = str(req.get("description") or req.get("requirement") or "").strip()

    return {
        "analysis_id": build_analysis_id(index),
        "source_kind": "ai_requirement",
        "source_requirement_ids": [source_id],
        "source_block_ids": [str(value) for value in _as_list(req.get("source_block_ids"))],
        "module": module,
        "submodule": str(req.get("module") or module),
        "template_match": "matched" if module in vocabulary.get("modules", []) else "unmapped",
        "description": description,
        "requirement": requirement_text,
        "software_requirement_text": "",
        "developer_guidance": [],
        "hardware_dependency": "",
        "acceptance_criteria": [],
        "open_questions": [],
        "assumptions": [],
        "notes": [],
        "threshold_table": req.get("threshold_table") if isinstance(req.get("threshold_table"), dict) else None,
        "analysis_source": "deterministic",  # LLM 富化成功则改写为 "llm"（叙述字段来源追溯）
        "source_quote": str(req.get("source_quote") or ""),
        "source_section": str(req.get("source_section") or ""),
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


def _write_report(path: Path, rows: list[dict[str, Any]], title: str) -> None:
    lines = [f"# {title}", ""]
    if not rows:
        lines.extend(["No items.", ""])
    for row in rows:
        lines.extend([
            f"## {row.get('analysis_id')} {row.get('description') or ''}".rstrip(),
            f"- 中文翻译/说明: {row.get('hardware_summary') or row.get('hardware_translation') or row.get('description') or ''}",
            f"- 为什么判断为硬件: {row.get('ownership_reason') or ''}",
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
