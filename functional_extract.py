"""WS2 功能需求直抽（旁路新入口，默认关闭）。

以 ``extract_units`` 的条款切分结果（章节/条款单元）为直接输入，LLM 单次调用直接产出
功能需求级条目，写入 ``functional_requirements.json``。字段模型完整复用
``functional_catalog`` 既有合成模型（objective / behaviors / preconditions /
data_constraints / variants / exceptions / related_dlms_objects + 三级追溯
source_quote / source_section / source_block_ids），下游成文与评审界面无需感知粒度变化。

防幻觉纪律全部继承，不因粒度抬升而松动（与 ``ai_extract`` / ``functional_synthesis``
同源纪律）：

* **结构字段冻结**：``functional_requirement_id`` / ``source_block_ids`` /
  ``source_section`` / ``module`` / ``ownership`` / OBIS 等结构字段由确定性后处理从条款
  证据派生，LLM 不得填写；LLM 只填叙述字段（objective / behaviors / preconditions /
  data_constraints / variants / exceptions / related_dlms_objects 叙述引用 / description）。
* **受保护编码漂移硬拦**：OBIS / hex / class_id / 外标准号在 LLM 产出但不在来源条款原文
  中出现的，一律剔除并记 ``rejected_codes``（复用 ``cosem_behavior_spec.extract_codes``）。
* **普通数字漂移软标**：LLM 产出的纯数字不在原文中的，保留但置 ``numeric_drift_flag``
  （与既有"受保护编码硬拦、普通数字软标"风险分级一致）。
* **温度 0**：经 ``llm_client`` 配置强制可复现。
* **LLM 不可用走 stub 路由**：route 为 stub / 无 key / 调用失败时，确定性退化每条款一条
  占位功能需求，``provenance`` 如实标 ``stub``，绝不伪装真 LLM 输出。
* **测试中禁止真实 LLM 调用**：单测注入 ``chat`` 回调或走 stub 路由。

入口开关 ``RATOMIZER_FUNCTIONAL_EXTRACT``（默认 ``0``=旧原子化路径）。=1 时 chain_task 把
``ai-extract``+``functional-synthesis`` 两阶段整体替换为本模块（``functional-extract`` 阶段）；
也可经 ``ratomizer functional-extract`` 单步子命令直跑。产物路径走
``result_package.governed_artifact_path``，缓存指纹按仓库既有模式接入
（``FUNCTIONAL_EXTRACT_VERSION`` + prompt 版本 + 护栏版本）。

守恒核对（exactly-once）：功能需求集合必须恰好消费条款集合——每条来源条款的 block_ids
被且只被一条功能需求覆盖；下钻条款递归生效。取证复用
``merged_consistency.match_source_quote_blocks``（与 ``review_tools.coverage_check`` 同源
匹配器），不重写核对逻辑。未闭合条款标 "未闭合" 并经 ``raise_if_unconserved`` 阻塞成文
导出（强制人工），不静默放行。

WS0 功能需求级真值集尚是 pending-human，本切片只交付工程机制：新路径默认关闭、旧路径
始终合法，验收门禁是"机制正确性可演示"，不是查全/查准数字。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from cosem_behavior_spec import extract_codes, extract_ints
from requirement_record import provenance

FUNCTIONAL_EXTRACT_VERSION = "functional-extract-v1"
FUNCTIONAL_EXTRACT_PROMPT_VERSION = "functional-extract-prompt-v2"
# S1-8：bump v1→v2。``_reject_drifted_codes`` 清洗范围从仅 objective 扩到全部叙述字段
# （behaviors/data_constraints/variants/exceptions/preconditions/description），缓存产物内容
# 变化——指纹含 guards 版本，bump 后旧 stub/LLM 缓存（behaviors 里残留幻觉编码）自然失效。
FUNCTIONAL_EXTRACT_GUARDS_VERSION = "functional-extract-guards-v2"
FUNCTIONAL_REQUIREMENTS_FILENAME = "functional_requirements.json"
FUNCTIONAL_EXTRACT_CACHE = "functional_extract_cache.jsonl"

# P0-8：负例 few-shot 注入数量上限（可配）。
FUNCTIONAL_EXTRACT_NEGATIVE_K = int(os.environ.get("RATOMIZER_FUNCTIONAL_EXTRACT_NEGATIVE_K", "2"))

LOGGER = logging.getLogger("requirement_atomizer")

# 入口开关（config.ENV_REGISTRY 登记）：默认 0=旧原子化路径，本模块不运行。
ENTRY_SWITCH_ENV = "RATOMIZER_FUNCTIONAL_EXTRACT"

# --- V3 WS-A A2 上下文包策略（默认 legacy=遗留切片，行为面不变）---
# legacy：_build_user_prompt 遗留 4000 字符切片（保留，默认）。
# clause_family：按条款自然边界组装上下文包——目标条款整文（绝不截断）+ 同族相邻条款
# （复用 extract_units.clause_key 两级族键）+ doc_map 热区摘要（A1 有地图时）；包大小上限
# 只约束拼包（邻居可舍弃），单条款自身超限仍整文进包（条款是自然原子，宁超勿截）。
CONTEXT_PACK_STRATEGY_ENV = "RATOMIZER_CONTEXT_PACK_STRATEGY"
CONTEXT_PACK_MAX_CHARS_ENV = "RATOMIZER_CONTEXT_PACK_MAX_CHARS"
CONTEXT_PACK_DEFAULT_MAX_CHARS = 24000
CONTEXT_PACK_STRATEGIES = ("legacy", "clause_family")

# 模态动词（与 functional_drilldown 同源；用于确定性兜底与叙述校验，非下钻判定本身）
_OBLIGATION_MODALS = (
    "shall", "must", "will", "may", "should",
    "应", "必须", "须", "可", "宜",
)

_SYSTEM_PROMPT_BASE = (
    "你是 DLMS/COSEM 电表标准的功能需求抽取器。输入是已切好的条款单元（章节号 + 原文 + 块溯源）。"
    "对每个条款，直接产出功能需求级条目：以「一个可独立测试的系统行为目标」为一条，"
    "同一目标下的多个行为归入 behaviors 列表不拆条，表格行机械事实（单个参数值/单条 OBIS 取值）"
    "归并入所属需求的 data_constraints。\n"
    "硬约束：①只能引用输入条款中已存在的原文，禁止臆造 OBIS/hex/class_id/标准号/数值；"
    "②只填叙述字段（objective/behaviors/preconditions/data_constraints/variants/exceptions/"
    "related_dlms_objects/description）；③不得填写 id/模块/归属/编码等结构字段（由下游确定性派生）；"
    "④每条产出必须回指来源条款的 section 与 block_ids（取自输入，原样回填）。"
    "输出 JSON：{\"items\":[{objective, behaviors[], preconditions[], data_constraints[], "
    "variants[], exceptions[], related_dlms_objects[], description, source_quote, source_section, "
    "source_block_ids[]}]}。"
)


def _system_prompt(negative_exemplars: str = "") -> str:
    """P0-8：负例 few-shot 可注入系统提示；无负例时不残留空壳。"""
    if not negative_exemplars:
        return _SYSTEM_PROMPT_BASE
    return (
        _SYSTEM_PROMPT_BASE + "\n"
        "【专家已拒绝的范例——请勿产出同类问题】\n"
        + negative_exemplars
    )


ExtractChat = Callable[[str, str], dict[str, Any]]


class FunctionalConservationError(RuntimeError):
    """守恒核对未闭合：功能需求集合未恰好消费条款集合，阻塞成文导出（强制人工）。"""


# ---------------------------------------------------------------------------
# 入口开关
# ---------------------------------------------------------------------------

def functional_extract_enabled(value: str | None = None) -> bool:
    """RATOMIZER_FUNCTIONAL_EXTRACT 是否开启（默认关）。"""
    raw = os.environ.get(ENTRY_SWITCH_ENV) if value is None else value
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# 条款指纹 / 缓存键
# ---------------------------------------------------------------------------

def clause_fingerprint(section: dict[str, Any]) -> str:
    """条款单元的内容指纹（section_id + block_ids + 文本 hash）；缓存放行/失效依据。"""
    payload = {
        "section_id": str(section.get("section_id") or ""),
        "section_path": [str(s) for s in (section.get("section_path") or [])],
        "heading": str(section.get("heading") or ""),
        "text": str(section.get("text") or ""),
        "block_ids": [str(b) for b in (section.get("block_ids") or [])],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def extraction_fingerprint(
    sections: Sequence[dict[str, Any]],
    *,
    route_key: str = "",
    context_strategy: str = "",
    doc_map_key: str = "",
) -> str:
    """整批条款的指纹，叠加版本/prompt/护栏/route 维度进缓存键。

    S1-7：``route_key`` 必须进指纹——历史 stub 产物（route_key='stub'）不得被后续真实 LLM
    请求（route_key='llm:<model>'/'injected'）静默复用（重构结论 §1.3 实证缺陷）。route 或
    模型变化即指纹失配，旧 stub 缓存自然失效——这是**预期行为**（它们本就不该被复用），不是
    回归。``run_functional_extract`` 在算指纹前先用 ``_resolve_route_label`` 把 route 解析成
    稳定身份标签再传入。

    A2：``context_strategy``/``doc_map_key`` 仅在非 legacy 时进键——legacy 指纹与特性引入前
    逐字节一致（旧缓存继续有效，默认行为面零变化）；clause_family 策略或 doc_map 摘要进入
    prompt 时换键空间，两策略产物绝不共键。
    """
    canonical = {
        "version": FUNCTIONAL_EXTRACT_VERSION,
        "prompt": FUNCTIONAL_EXTRACT_PROMPT_VERSION,
        "guards": FUNCTIONAL_EXTRACT_GUARDS_VERSION,
        "route_key": str(route_key or ""),
        "clauses": [clause_fingerprint(section) for section in sections],
    }
    if context_strategy and context_strategy != "legacy":
        canonical["context_strategy"] = str(context_strategy)
        canonical["doc_map_key"] = str(doc_map_key or "")
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 受保护编码 / 数值漂移护栏（确定性，零 LLM）
# ---------------------------------------------------------------------------

def _reject_drifted_codes(narrative_text: str, source_text: str) -> tuple[str, list[str]]:
    """受保护编码漂移硬拦：剔除 LLM 产出但来源条款没有的 OBIS/hex/class_id/标准号。

    返回 (清洗后文本, 被剔除编码列表)。编码纪律与 claim_ledger.extract_protected_facts /
    extract_guards 同源——"OBIS 错一位是严重缺陷"，宁剔勿留。
    """
    produced = extract_codes(narrative_text)
    allowed = extract_codes(source_text) | extract_codes(narrative_text)
    # 仅剔除"LLM 新增、来源没有"的编码；来源本身有的不动。
    drifted = sorted({code for code in produced if code not in extract_codes(source_text)})
    cleaned = narrative_text
    for code in drifted:
        cleaned = cleaned.replace(code, "")
    return cleaned, drifted


def _flag_numeric_drift(narrative_text: str, source_text: str) -> tuple[list[str], bool]:
    """普通数字漂移软标：LLM 产出但来源没有的纯数字 → 保留但置标记。

    与"受保护编码硬拦"风险分级一致：编码错一位=严重（硬拦），普通数字可能是合理的
    聚合/换算表达（软标，留待评审）。返回 (漂移数字列表, 是否漂移)。
    """
    source_ints = extract_ints(source_text)
    drifted = sorted({n for n in extract_ints(narrative_text) if n not in source_ints})
    # 过滤明显无害的枚举/序号（单字符且来源无）——保留全部漂移数字以备审计，仅设布尔标记
    return drifted, bool(drifted)


# ---------------------------------------------------------------------------
# 结构字段确定性派生
# ---------------------------------------------------------------------------

def _stable_requirement_id(section: dict[str, Any], index: int) -> str:
    basis = "\x1f".join([
        str(section.get("section_id") or ""),
        str(section.get("heading") or ""),
        "|".join(str(b) for b in (section.get("block_ids") or [])),
        str(index),
    ])
    return "FRE-" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def _derive_module(section: dict[str, Any]) -> str:
    path = [str(s) for s in (section.get("section_path") or [])]
    for candidate in reversed(path):
        text = candidate.strip()
        if text and text.lower() not in {"root", "(root)"}:
            return text
    return str(section.get("heading") or "未分类").strip() or "未分类"


def _source_text(section: dict[str, Any]) -> str:
    return " ".join(
        str(section.get(key) or "")
        for key in ("heading", "text")
        if str(section.get(key) or "").strip()
    )


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    if isinstance(value, (tuple, set)):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    text = str(value).strip()
    return [text] if text else []


def _coerce_item(
    raw: dict[str, Any],
    section: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    """把 LLM 产出的一条例子收敛到 functional_catalog 字段模型，结构字段确定性冻结。

    LLM 只贡献叙述字段；id / module / ownership / source_block_ids / source_section 全部
    由来源条款派生，防止模型篡改溯源与归属。
    """
    source_text = _source_text(section)
    block_ids = [str(b) for b in (section.get("block_ids") or []) if str(b)]
    section_label = " / ".join(str(s) for s in (section.get("section_path") or [])) or str(
        section.get("section_id") or ""
    )

    objective = str(raw.get("objective") or "").strip() or f"实现{_derive_module(section)}相关功能。"
    behaviors = _as_str_list(raw.get("behaviors")) or [str(section.get("heading") or objective).strip()]
    preconditions = _as_str_list(raw.get("preconditions"))
    data_constraints = _as_str_list(raw.get("data_constraints"))
    variants = _as_str_list(raw.get("variants"))
    exceptions = _as_str_list(raw.get("exceptions"))
    related = _as_str_list(raw.get("related_dlms_objects"))

    # 受保护编码硬拦：叙述字段合集 vs 来源条款原文（数字软标用原始合集）
    narrative = "\n".join([objective, *behaviors, *data_constraints, *related])
    numeric_drifted, numeric_drift = _flag_numeric_drift(narrative, source_text)

    # S1-8：``_reject_drifted_codes`` 的 docstring 承诺"剔除 LLM 产出但来源条款没有的
    # OBIS/hex/class_id/标准号"——清洗范围必须覆盖**全部叙述字段**（objective/behaviors/
    # data_constraints/variants/exceptions/preconditions），而非只清 objective。旧实现只把剔除
    # 反映回 objective，幻觉编码在 behaviors/data_constraints 里原样保留到产物。这里逐字段清洗，
    # 聚合 rejected_codes 留痕（related 在下方按编码归属单独过滤）。docstring 怎么写就怎么实现，
    # 不许反过来改 docstring 迁就实现。
    rejected: set[str] = set()

    def _clean_field(value: str) -> str:
        cleaned, drifted = _reject_drifted_codes(value, source_text)
        rejected.update(drifted)
        return cleaned

    objective = _clean_field(objective) or objective
    behaviors = [_clean_field(b) or b for b in behaviors]
    data_constraints = [_clean_field(c) or c for c in data_constraints]
    variants = [_clean_field(v) or v for v in variants]
    exceptions = [_clean_field(e) or e for e in exceptions]
    preconditions = [_clean_field(p) or p for p in preconditions]
    rejected_codes = sorted(rejected)

    related_filtered = [
        value for value in related
        # 受保护编码归属也走硬拦：related_dlms_objects 里的编码必须来源有
        if not (extract_codes(value) - extract_codes(source_text))
    ]

    description = str(raw.get("description") or "").strip()
    if description:
        # S1-8：description 同属 LLM 叙述字段，幻觉编码一并清洗（与 objective/behaviors 同口径）
        description = _clean_field(description) or description
    if not description:
        description = _render_description(objective, behaviors, data_constraints)

    return {
        "functional_requirement_id": _stable_requirement_id(section, index),
        "functional_key": f"{_derive_module(section)}:{_normalize_key(objective)}",
        "title": str(section.get("heading") or objective).strip() or objective,
        "objective": objective,
        "behaviors": behaviors,
        "preconditions": preconditions,
        "data_constraints": data_constraints,
        "variants": variants,
        "exceptions": exceptions,
        "related_dlms_objects": related_filtered,
        "description": description,
        # 结构字段冻结（确定性派生，LLM 不得填写）
        "module": _derive_module(section),
        "type": "functional",
        "priority": "P1",
        "labels": [],
        "ownership_override": None,
        "source_section": section_label,
        "source_quote": str(raw.get("source_quote") or "").strip()
        or str(section.get("text") or source_text).strip(),
        "source_block_ids": block_ids,
        # 三级追溯审计
        "evidence": [
            {
                "section": section_label,
                "source_quote": str(raw.get("source_quote") or "").strip()
                or str(section.get("text") or "").strip(),
                "source_block_ids": block_ids,
                "protected_tokens": sorted(extract_codes(source_text)),
            }
        ],
        # 护栏留痕
        "rejected_codes": rejected_codes,
        "numeric_drift_flag": numeric_drift,
        "numeric_drift_values": numeric_drifted,
        "merge_method": "functional_extract",
        "merge_confidence": 1.0,
        "source_kind": "functional_extract",
    }


def _normalize_key(value: str) -> str:
    import re
    return re.sub(r"[^0-9a-z一-鿿]+", "", str(value or "").casefold())


# ---------------------------------------------------------------------------
# T3-1 跨再生成稳定 ID（与内容哈希解耦）
# ---------------------------------------------------------------------------
# 旧 ``functional_requirement_id``（``_stable_requirement_id``）含 heading/block_ids/output
# index 等内容派生输入——LLM 输出顺序/数量一变或重解析改 block_ids 即漂移，做不了长期 RTM
# 主键。``requirement_uid`` 改为**条款序号定位**：条款在确定性 sections 列表里的位置（来自
# chunks.jsonl，parser-deterministic）——同一源文件再生成，条款序号稳定 → UID 稳定，与 LLM
# 叙述抖动/输出顺序解耦。旧 id **保留为别名映射字段**（``functional_requirement_id`` 不动），
# 不做原地替换；下游可逐步改用 uid 作长期主键。
STABLE_UID_VERSION = "functional-stable-uid-v1"


def assign_stable_uids(
    items: Sequence[dict[str, Any]],
    sections: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """给每条功能需求盖 ``requirement_uid``——按其来源条款在 sections 里的序号定位。

    稳定性来源：条款序号取自确定性 sections 列表顺序（parser 决定，不依赖 LLM 输出顺序/数量
    或叙述内容）。同一源文件再生成（即使 LLM 改了措辞、换了输出顺序）→ 同一条款 → 同一序号 →
    同一 UID。多条落在同一条款时按其既有别名 id（``functional_requirement_id``）稳定排序后缀
    ``.2``/``.3``，使子序在再生成间确定（前提：两条内容不同，别名 id 可区分——成立）。

    每条 item 同时盖 ``stable_uid_version`` 与 ``stable_uid_basis``（条款序号，审计可解释）。
    """
    block_to_ordinal: dict[str, int] = {}
    section_id_to_ordinal: dict[str, int] = {}
    for ordinal, section in enumerate(sections):
        for block in (section.get("block_ids") or []):
            block_to_ordinal.setdefault(str(block), ordinal)
        sid = str(section.get("section_id") or "").strip()
        if sid:
            section_id_to_ordinal.setdefault(sid, ordinal)

    def _ordinal_for(item: dict[str, Any], fallback: int) -> int:
        for block in (item.get("source_block_ids") or []):
            key = str(block)
            if key in block_to_ordinal:
                return block_to_ordinal[key]
        # 兜底：按 source_section 文本匹配 section_id（不应触发——每条 item 都挂回条款）
        label = " / ".join(str(s) for s in (item.get("source_section") or "").split(" / "))
        for sid, ordinal in section_id_to_ordinal.items():
            if sid and sid == label:
                return ordinal
        return fallback

    by_ordinal: dict[int, list[dict[str, Any]]] = {}
    fallback_ordinal = len(sections)
    for item in items:
        ordinal = _ordinal_for(item, fallback_ordinal)
        # fallback 仅对挂不回条款的孤儿 item 生效；多个孤儿各占一格避免撞 UID
        if ordinal >= len(sections):
            fallback_ordinal += 1
        by_ordinal.setdefault(ordinal, []).append(item)

    for ordinal in sorted(by_ordinal):
        group = sorted(
            by_ordinal[ordinal],
            key=lambda it: str(it.get("functional_requirement_id") or ""),
        )
        for sub, item in enumerate(group, start=1):
            uid = f"FR-{ordinal + 1:04d}" if sub == 1 else f"FR-{ordinal + 1:04d}.{sub}"
            item["requirement_uid"] = uid
            item["stable_uid_version"] = STABLE_UID_VERSION
            item["stable_uid_basis"] = {"clause_ordinal": ordinal, "sub": sub}
    return list(items)


def _render_description(objective: str, behaviors: list[str], constraints: list[str]) -> str:
    parts = [f"目标：{objective}"]
    if behaviors:
        parts.append("行为：" + "；".join(behaviors))
    if constraints:
        parts.append("约束：" + "、".join(constraints))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# stub 路由（LLM 不可用 / 无 key / 调用失败）——诚实退化，不伪装
# ---------------------------------------------------------------------------

def _stub_item(section: dict[str, Any], index: int) -> dict[str, Any]:
    source_text = _source_text(section)
    heading = str(section.get("heading") or "未命名功能").strip() or "未命名功能"
    objective = f"实现{heading}，并满足来源条款。"
    behaviors = [source_text[:200]] if source_text.strip() else [heading]
    return _coerce_item(
        {
            "objective": objective,
            "behaviors": behaviors,
            "description": _render_description(objective, behaviors, []),
            "source_quote": str(section.get("text") or source_text),
        },
        section,
        index,
    )


# ---------------------------------------------------------------------------
# LLM 路由解析（复用 ai_extract.config_for_route 同款纪律）
# ---------------------------------------------------------------------------

def _route_config(route: str | None):
    """解析 route 到 ``LLMClientConfig``，校验 key 可用；不可用返回 None（→ stub）。

    S1-7：抽出为单一真相源，``_resolve_route_label``（缓存键）与 ``_resolve_extract_chat``
    （执行）共用，避免两处分别判定 route 能力导致缓存键与实际执行路径漂移。
    """
    if not route or route == "stub":
        return None
    try:
        from ai_extract import DEFAULT_PIPELINE_PATH, config_for_route
        config = config_for_route(route, DEFAULT_PIPELINE_PATH)
    except Exception:
        return None
    if config is None:
        return None
    local_endpoint = any(
        host in config.base_url.casefold() for host in ("127.0.0.1", "localhost", "::1")
    )
    if not local_endpoint and not os.environ.get(config.api_key_env):
        return None
    return config


def _resolve_route_label(route: str | None, chat: ExtractChat | None) -> str:
    """缓存键用的路由身份标签（与 ``_resolve_extract_chat`` 的执行标签同源，无副作用）。

    S1-7：stub 与 openai_compatible 产物从此不共键。``chat`` 注入 → 'injected'；route 解析
    出可用 config → 'llm:<model>'；否则 'stub'。标签必须与 ``_resolve_extract_chat`` 返回的
    执行标签一致——两者都经 ``_route_config`` 派生，唯一差异是执行路径还构造 invoke 回调。
    """
    if chat is not None:
        return "injected"
    config = _route_config(route)
    if config is None:
        return "stub"
    return f"llm:{config.model}"


def _resolve_extract_chat(
    route: str | None,
    chat: ExtractChat | None,
) -> tuple[ExtractChat | None, str]:
    """返回 (回调, 执行路由标签)。标签如实反映实际能力，绝不夸大。

    stub / 无 route / 无 key → (None, 'stub')，调用方走确定性退化。injected chat → 'injected'。
    执行标签与 ``_resolve_route_label`` 同源（都从 ``_route_config`` 派生），保证缓存键与实际
    执行路径不漂移。
    """
    if chat is not None:
        return chat, "injected"
    config = _route_config(route)
    if config is None:
        return None, "stub"
    from llm_client import chat_json
    # 温度 0 可复现（config 层默认已是 0，此处显式断言不放松）
    try:
        temperature = float(getattr(config, "temperature", 0.0) or 0.0)
    except (TypeError, ValueError):
        temperature = 0.0
    if temperature != 0.0:
        LOGGER.warning("functional_extract 要求温度 0，当前 %.2f 已强制归零", temperature)
        try:
            config.temperature = 0.0  # type: ignore[misc]
        except Exception:
            pass

    def invoke(system: str, user: str) -> dict[str, Any]:
        return chat_json(config, system, user, max_truncation_escalations=1)

    return invoke, f"llm:{config.model}"


def _build_user_prompt(sections: Sequence[dict[str, Any]]) -> str:
    compact = []
    for section in sections:
        compact.append({
            "section": " / ".join(str(s) for s in (section.get("section_path") or []))
            or str(section.get("section_id") or ""),
            "heading": str(section.get("heading") or ""),
            "text": str(section.get("text") or "")[:4000],
            "block_ids": [str(b) for b in (section.get("block_ids") or [])],
        })
    return json.dumps({"clauses": compact}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# A2 上下文包（clause_family 策略）：条款自然边界组装，目标条款绝不截断
# ---------------------------------------------------------------------------

_PACKAGE_SYSTEM_PROMPT_BASE = (
    "你是 DLMS/COSEM 电表标准的功能需求抽取器。输入分三段：[TARGET_CLAUSE] 是本次要抽取的"
    "目标条款（整文，未经截断）；[CONTEXT] 是同族相邻条款（仅作上下文，帮助理解目标条款，"
    "不得从中产出条目）；[DOC_MAP] 是整篇地图热区摘要（仅作定位参考，可能缺席）。\n"
    "只对目标条款产出功能需求级条目：以「一个可独立测试的系统行为目标」为一条，同一目标下的"
    "多个行为归入 behaviors 列表不拆条，表格行机械事实归并入所属需求的 data_constraints。\n"
    "硬约束：①只能引用目标条款中已存在的原文，禁止臆造 OBIS/hex/class_id/标准号/数值；"
    "②只填叙述字段（objective/behaviors/preconditions/data_constraints/variants/exceptions/"
    "related_dlms_objects/description）；③不得填写 id/模块/归属/编码等结构字段；"
    "④每条产出必须回指目标条款的 source_block_ids（取自输入，原样回填）。\n"
    "输出 JSON：{\"items\":[{objective, behaviors[], preconditions[], data_constraints[], "
    "variants[], exceptions[], related_dlms_objects[], description, source_quote, "
    "source_block_ids[]}]}。"
)


def _package_system_prompt(negative_exemplars: str = "") -> str:
    """P0-8：clause_family 策略下的系统提示，负例可注入。"""
    if not negative_exemplars:
        return _PACKAGE_SYSTEM_PROMPT_BASE
    return (
        _PACKAGE_SYSTEM_PROMPT_BASE + "\n"
        "【专家已拒绝的范例——请勿产出同类问题】\n"
        + negative_exemplars
    )


def context_pack_strategy(value: str | None = None) -> str:
    """上下文包组装策略（ENV_REGISTRY 登记）：默认 legacy=遗留切片，行为面不变。"""
    raw = os.environ.get(CONTEXT_PACK_STRATEGY_ENV) if value is None else value
    token = str(raw or "").strip().lower()
    return token if token in CONTEXT_PACK_STRATEGIES else "legacy"


def context_pack_max_chars(value: str | None = None) -> int:
    """上下文包大小上限（只约束拼包；目标条款自身超限仍整文进包）。"""
    raw = os.environ.get(CONTEXT_PACK_MAX_CHARS_ENV) if value is None else value
    try:
        parsed = int(str(raw or "").strip())
    except (TypeError, ValueError):
        return CONTEXT_PACK_DEFAULT_MAX_CHARS
    return parsed if parsed > 0 else CONTEXT_PACK_DEFAULT_MAX_CHARS


def _clause_text_size(section: dict[str, Any]) -> int:
    return len(str(section.get("text") or "")) + len(str(section.get("heading") or "")) + 4


def _doc_map_summary_for(section: dict[str, Any], doc_map: dict[str, Any] | None) -> str:
    """从 A1 整篇地图摘取本条款的热区/域摘要（无地图或无论点如实空串）。"""
    if not isinstance(doc_map, dict) or doc_map.get("status") != "ok":
        return ""
    path = [str(s) for s in (section.get("section_path") or []) if str(s).strip()]
    chapter = path[0] if path else ""
    section_id = str(section.get("section_id") or "")
    lines: list[str] = []
    annotations = doc_map.get("llm_annotations") or {}
    for domain in annotations.get("domains") or []:
        if section_id and section_id in [str(s) for s in (domain.get("section_ids") or [])]:
            lines.append(f"功能域 {domain.get('name') or ''}: {domain.get('summary') or ''}".strip())
    scaffold = doc_map.get("scaffold") or {}
    density = {
        str(row.get("chapter") or ""): row
        for row in (scaffold.get("density_hotspots") or [])
    }
    if chapter and chapter in density:
        row = density[chapter]
        lines.append(
            f"章节 {chapter} 需求密度 {row.get('density')}"
            f"（{row.get('requirement_like_blocks')}/{row.get('total_blocks')} 块）"
        )
    for entry in annotations.get("hotspot_rationale") or []:
        if chapter and str(entry.get("chapter") or "") == chapter:
            rationale = str(entry.get("rationale") or "").strip()
            if rationale:
                lines.append(f"热区理由：{rationale}")
    return "\n".join(lines)


def build_context_packages(
    sections: Sequence[dict[str, Any]],
    *,
    doc_map: dict[str, Any] | None = None,
    max_chars: int | None = None,
) -> list[dict[str, Any]]:
    """按条款自然边界组装上下文包：目标条款整文 + 同族相邻条款 + doc_map 热区摘要。

    上限 ``max_chars`` 只约束拼包——装不下的**邻居**整条舍弃（不截断），目标条款自身
    超限仍整文进包（条款是自然原子，宁超勿截）。同族判定复用 ``extract_units.clause_key``
    两级族键；无编号条款（族键 None）不带邻居（宁缺勿猜）。
    """
    from extract_units import clause_key

    cap = max_chars if max_chars and max_chars > 0 else CONTEXT_PACK_DEFAULT_MAX_CHARS
    families: dict[str, list[dict[str, Any]]] = {}
    for section in sections:
        key = clause_key(section)
        if key is not None:
            families.setdefault(key, []).append(section)
    packages: list[dict[str, Any]] = []
    for section in sections:
        key = clause_key(section)
        budget = cap - _clause_text_size(section)
        neighbors: list[dict[str, Any]] = []
        if key is not None:
            for sibling in families.get(key, []):
                if sibling is section:
                    continue
                size = _clause_text_size(sibling)
                if size > budget:
                    continue  # 装不下的邻居整条舍弃（不截断）；后续小邻居仍可入包
                neighbors.append(sibling)
                budget -= size
        packages.append({
            "target": section,
            "neighbors": neighbors,
            "clause_family": key,
            "doc_map_summary": _doc_map_summary_for(section, doc_map),
        })
    return packages


def _package_clause_payload(section: dict[str, Any]) -> dict[str, Any]:
    return {
        "section": " / ".join(str(s) for s in (section.get("section_path") or []))
        or str(section.get("section_id") or ""),
        "heading": str(section.get("heading") or ""),
        # 条款自然边界：整文，不切片（与 legacy _build_user_prompt 的 [:4000] 相对）
        "text": str(section.get("text") or ""),
        "block_ids": [str(b) for b in (section.get("block_ids") or [])],
    }


def _build_package_prompt(package: dict[str, Any]) -> str:
    parts = ["[TARGET_CLAUSE]", json.dumps(
        _package_clause_payload(package["target"]), ensure_ascii=False
    )]
    neighbors = [_package_clause_payload(s) for s in package.get("neighbors") or []]
    if neighbors:
        parts.append("[CONTEXT]")
        parts.append(json.dumps({"neighbor_clauses": neighbors}, ensure_ascii=False))
    summary = str(package.get("doc_map_summary") or "").strip()
    if summary:
        parts.append("[DOC_MAP]")
        parts.append(summary)
    return "\n".join(parts)


def _parse_llm_items(payload: Any, sections: Sequence[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """校验 LLM 返回并按条款顺序 coerce。返回 None 表示返回非法（调用方走 stub）。"""
    if not isinstance(payload, dict):
        return None
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return None
    # 把每条例子关联到来源条款：优先用 LLM 回填的 source_block_ids 命中，否则按序落到条款
    section_by_blocks: dict[tuple[str, ...], dict[str, Any]] = {}
    section_order: list[dict[str, Any]] = []
    for section in sections:
        section_order.append(section)
        key = tuple(str(b) for b in (section.get("block_ids") or []))
        if key:
            section_by_blocks.setdefault(key, section)
    used_sections: list[dict[str, Any] | None] = [None] * len(items)
    for idx, raw in enumerate(items):
        if not isinstance(raw, dict):
            return None
        block_ids = tuple(str(b) for b in _as_str_list(raw.get("source_block_ids")))
        section = section_by_blocks.get(block_ids)
        if section is not None:
            used_sections[idx] = section
    # 未命中的按序补位到未消费条款（保序，避免乱挂）
    pending = [section for section in section_order if section not in used_sections]
    pending_iter = iter(pending)
    for idx in range(len(items)):
        if used_sections[idx] is None:
            used_sections[idx] = next(pending_iter, None)
    coerced: list[dict[str, Any]] = []
    for idx, (raw, section) in enumerate(zip(items, used_sections)):
        if section is None:
            # LLM 多产了无法挂回条款的例子——丢弃（守恒纪律：无来源即无条目），记审计
            LOGGER.warning("functional_extract 丢弃无法挂回条款的 LLM 产出 #%d", idx)
            continue
        coerced.append(_coerce_item(raw, section, idx + 1))
    return coerced or None


# ---------------------------------------------------------------------------
# 守恒核对（exactly-once，复用 match_source_quote_blocks 取证）
# ---------------------------------------------------------------------------

def conservation_report(
    sections: Sequence[dict[str, Any]],
    items: Sequence[dict[str, Any]],
    *,
    blocks: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """功能需求集合必须恰好消费条款集合：每条来源 block_id 被且只被一条功能需求覆盖。

    取证复用 ``merged_consistency.match_source_quote_blocks``（与
    ``review_tools.coverage_check`` 同源匹配器）校验每条 item 的 source_quote 是否真的命中
    其声明的 source_block_ids——不重写核对逻辑，只做 exactly-once 集合运算 + 证据完整性复核。

    下钻条款递归生效：若 item 带 ``drilled_subatoms``，其子原子的 block_ids 并集必须恰好
    等于父条款 block_ids（见 functional_drilldown 回填）。
    """
    from collections import Counter
    from merged_consistency import match_source_quote_blocks

    clause_block_ids: list[str] = []
    for section in sections:
        clause_block_ids.extend(str(b) for b in (section.get("block_ids") or []) if str(b))
    clause_set = sorted(set(clause_block_ids))

    assigned: list[str] = []
    evidence_mismatches: list[dict[str, Any]] = []
    for item in items:
        ids = [str(b) for b in (item.get("source_block_ids") or []) if str(b)]
        assigned.extend(ids)
        # 证据完整性：source_quote 命中的块集合应与声明的 source_block_ids 有交集
        if blocks is not None:
            quote = str(item.get("source_quote") or "")
            if quote.strip():
                hit_block_ids, _method = match_source_quote_blocks(quote, list(blocks))
                if hit_block_ids and not set(hit_block_ids).intersection(ids):
                    evidence_mismatches.append({
                        "functional_requirement_id": str(item.get("functional_requirement_id") or ""),
                        "declared_block_ids": ids,
                        "quote_hit_block_ids": hit_block_ids,
                    })
        # 下钻子原子递归守恒：并集 == 父条款 block_ids
        subatoms = item.get("drilled_subatoms")
        if isinstance(subatoms, list) and subatoms:
            child_blocks: set[str] = set()
            for sub in subatoms:
                if isinstance(sub, dict):
                    child_blocks.update(
                        str(b) for b in (sub.get("source_block_ids") or []) if str(b)
                    )
            parent_blocks = set(ids)
            if child_blocks and parent_blocks and child_blocks != parent_blocks:
                evidence_mismatches.append({
                    "functional_requirement_id": str(item.get("functional_requirement_id") or ""),
                    "reason": "drilldown_subatoms_do_not_consume_parent",
                    "parent_block_ids": sorted(parent_blocks),
                    "child_block_union": sorted(child_blocks),
                })

    counter = Counter(assigned)
    duplicate_assignments = sorted(k for k, v in counter.items() if v > 1)
    assigned_set = set(assigned)
    missing = sorted(set(clause_set) - assigned_set)
    extra = sorted(assigned_set - set(clause_set))
    ok = not (missing or duplicate_assignments or extra or evidence_mismatches)
    return {
        "ok": ok,
        "clause_block_count": len(clause_set),
        "covered_block_count": len(assigned_set & set(clause_set)),
        "missing_block_ids": missing[:50],
        "duplicate_assignments": duplicate_assignments[:50],
        "extra_block_ids": extra[:50],
        "evidence_mismatches": evidence_mismatches[:50],
        "block_export": not ok,  # 未闭合 → 阻塞成文导出（强制人工）
    }


def raise_if_unconserved(report: dict[str, Any]) -> None:
    """成文导出闸门：守恒核对未闭合即抛 FunctionalConservationError，不静默放行。"""
    if not report.get("ok"):
        raise FunctionalConservationError(
            "功能需求守恒核对未闭合，阻塞成文导出（强制人工）："
            f"missing={len(report.get('missing_block_ids') or [])} "
            f"duplicate={len(report.get('duplicate_assignments') or [])} "
            f"extra={len(report.get('extra_block_ids') or [])} "
            f"evidence_mismatch={len(report.get('evidence_mismatches') or [])}"
        )


def _notify_budget_degraded(reason: str) -> None:
    """S1-1：通知活动文档预算单 functional_extract 降级（mark_degraded）。

    ``llm_client`` 的文档预算钩子（``LLMBudgetLedger`` 经 ``attach()`` 挂载）由 desktop_tasks
    在开启 ``RATOMIZER_LLM_BUDGET`` 时安装。``mark_degraded(STAGE_FUNCTIONAL_EXTRACT, reason)``
    会把 ``document_needs_work`` 置真（核心交付物降级强制文档级 NEEDS WORK）。无活动预算单
    （开关未开 / 非桌面入口）时空操作——本模块不依赖预算单存在，行为面不动。
    """
    try:
        import llm_client
        from llm_budget import STAGE_FUNCTIONAL_EXTRACT

        hook = llm_client.get_document_budget_hook()
    except Exception:  # noqa: BLE001 — 预算通知失败不得影响抽取主流程
        return
    if hook is None:
        return
    try:
        hook.mark_degraded(STAGE_FUNCTIONAL_EXTRACT, str(reason))
    except Exception:  # noqa: BLE001 — 同上
        pass


# ---------------------------------------------------------------------------
# 缓存（按仓库既有 ai_extract_cache 模式：指纹命中放行，否则写新条目）
# ---------------------------------------------------------------------------

def _cache_path(out_dir: Path, *, for_write: bool = False) -> Path:
    from result_package import governed_artifact_path
    return governed_artifact_path(
        out_dir, FUNCTIONAL_EXTRACT_CACHE, category="cache", for_write=for_write
    )


def _read_cache(out_dir: Path) -> dict[str, dict[str, Any]]:
    path = _cache_path(out_dir, for_write=False)
    if not path.is_file():
        return {}
    cache: dict[str, dict[str, Any]] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            fp = str(row.get("fingerprint") or "")
            if fp:
                cache[fp] = row
    except (OSError, json.JSONDecodeError):
        return {}
    return cache


def _write_cache_entry(out_dir: Path, fingerprint: str, payload: dict[str, Any]) -> None:
    from result_package import governed_artifact_path
    path = _cache_path(out_dir, for_write=True)
    entry = {"fingerprint": fingerprint, "payload": payload}
    # 跨进程锁 + 原子追加（与 ai_review_actions / review_state 同纪律）
    import tempfile
    lock_path = governed_artifact_path(
        out_dir, "functional_extract_cache.lock", category="cache", for_write=True
    )
    tmp: Path | None = None
    try:
        from process_file_lock import process_file_lock
        with process_file_lock(lock_path, timeout_s=10.0, label="functional_extract_cache"):
            existing = []
            if path.is_file():
                existing = [
                    line for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip() and json.loads(line).get("fingerprint") != fingerprint
                ]
            with tempfile.NamedTemporaryFile(
                mode="w", dir=path.parent, prefix=".functional_extract_cache.",
                suffix=".tmp", delete=False, encoding="utf-8", newline="\n",
            ) as handle:
                tmp = Path(handle.name)
                for line in existing:
                    handle.write(line + "\n")
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            _replace_with_retry(tmp, path)
            tmp = None
    except Exception as exc:  # 缓存写失败不阻断主流程，只记日志
        LOGGER.warning("functional_extract 缓存写入失败：%s", exc)
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass


def _replace_with_retry(source: Path, target: Path) -> None:
    for attempt in range(5):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt + 1 >= 5:
                raise
            import time
            time.sleep(0.02 * (attempt + 1))


def _load_adjudication_bank() -> dict[str, Any]:
    """P0-8：只读消费裁决样本库；未配置或不存在 → 空库零注入。"""
    from adjudication_bank import load_bank, resolve_bank_path
    return load_bank(resolve_bank_path())


def _negative_exemplars_for_section(section: dict[str, Any], bank: dict[str, Any]) -> str:
    """为单条条款选取同模块相关负例并渲染为 prompt 文本。"""
    if not bank or not bank.get("rejected"):
        return ""
    from adjudication_bank import render_negative_exemplars, select_negative_exemplars
    module = _derive_module(section)
    text = _source_text(section)
    negs = select_negative_exemplars(bank, module, text, k=FUNCTIONAL_EXTRACT_NEGATIVE_K)
    return render_negative_exemplars(negs) if negs else ""


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def extract_functional_requirements(
    sections: Sequence[dict[str, Any]],
    *,
    chat: ExtractChat | None = None,
    route: str | None = "stub",
    blocks: Sequence[dict[str, Any]] | None = None,
    strategy: str = "legacy",
    doc_map: dict[str, Any] | None = None,
    max_chars: int | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """条款集合 → 功能需求条目列表 + 执行路由标签（如实，不夸大）。

    LLM 单次调用直出（route=openai_compatible 且有 key）；stub / 调用失败 / 返回非法 →
    确定性退化每条款一条，路由标签如实为 'stub'。返回的 items 字段模型与
    functional_catalog 同构，结构字段确定性冻结、叙述字段经护栏清洗。

    A2：``strategy="clause_family"`` 时按条款自然边界逐包调用（目标条款整文不截断 +
    同族邻居 + doc_map 热区摘要）；部分包 LLM 失败只对受影响条款诚实 stub 退化，
    路由标签如实为 'mixed'（全部失败为 'stub'，绝不夸大为纯 LLM 路由）。
    """
    if not sections:
        return [], "stub"
    active_chat, executed_route = _resolve_extract_chat(route, chat)
    # P0-8：LLM 路径才需负例；stub 路径不读库。
    bank = _load_adjudication_bank() if active_chat is not None else {}
    if strategy == "clause_family":
        return _extract_by_context_packages(
            sections, active_chat, executed_route, doc_map=doc_map, max_chars=max_chars,
            bank=bank,
        )
    items: list[dict[str, Any]] | None = None
    negative_exemplars = _negative_exemplars_for_section(sections[0], bank) if bank else ""
    if active_chat is not None:
        try:
            payload = active_chat(_system_prompt(negative_exemplars), _build_user_prompt(sections))
            items = _parse_llm_items(payload, sections)
        except Exception as exc:
            LOGGER.warning("functional_extract LLM 调用失败，退回 stub 路由：%s", exc)
            items = None
    degraded_to_stub = False
    if items is None:
        # stub 路由：确定性退化，每条款一条占位功能需求，provenance 如实标 stub
        items = [_stub_item(section, idx + 1) for idx, section in enumerate(sections)]
        executed_route = "stub"
        # 仅当 LLM 被实际尝试过却退化（route 非 stub）才算降级；route=stub 是请求的本意，不算
        degraded_to_stub = active_chat is not None
    # 事后校正路由标签：route 声称 llm 但产出非法全部退回 stub 时，不得夸大
    if executed_route.startswith("llm:") and not items:
        executed_route = "stub"
    if degraded_to_stub:
        # S1-1：功能需求直抽是核心交付物——降级 stub 时在文档预算单上记 mark_degraded，
        # 强制 document_needs_work=True（不允许仅 provenance 标注静默通过；无活动预算单则空操作）。
        _notify_budget_degraded("functional_extract_degraded_to_stub")
    # T3-1：盖跨再生成稳定 UID（条款序号定位，与内容哈希解耦）。旧 functional_requirement_id
    # 保留为别名映射字段不动。
    assign_stable_uids(items, sections)
    return items, executed_route


def _extract_by_context_packages(
    sections: Sequence[dict[str, Any]],
    active_chat: ExtractChat | None,
    executed_route: str,
    *,
    doc_map: dict[str, Any] | None,
    max_chars: int | None,
    bank: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """clause_family 策略：每条款包一次 LLM 调用；包级失败只退化受影响条款。"""
    packages = build_context_packages(sections, doc_map=doc_map, max_chars=max_chars)
    items: list[dict[str, Any]] = []
    llm_ok = 0
    stub_fallback = 0
    bank = bank or {}
    for package in packages:
        target = package["target"]
        package_items: list[dict[str, Any]] | None = None
        negative_exemplars = _negative_exemplars_for_section(target, bank)
        if active_chat is not None:
            try:
                payload = active_chat(_package_system_prompt(negative_exemplars), _build_package_prompt(package))
                package_items = _parse_llm_items(payload, [target])
            except Exception as exc:
                LOGGER.warning("functional_extract 条款包 LLM 调用失败，该条款退回 stub：%s", exc)
                package_items = None
        if package_items is None:
            items.append(_stub_item(target, 1))
            stub_fallback += 1
        else:
            items.extend(package_items)
            llm_ok += 1
    if active_chat is None or llm_ok == 0:
        final_route = "stub"
    elif stub_fallback:
        final_route = "mixed"  # 部分包 LLM 部分 stub——如实标混合，不夸大
    else:
        final_route = executed_route
    if stub_fallback and active_chat is not None:
        # 核心交付物部分降级同样记预算单（S1-1 同款纪律：不允许仅 provenance 静默通过）
        _notify_budget_degraded(
            "functional_extract_partial_stub_fallback" if llm_ok
            else "functional_extract_degraded_to_stub"
        )
    assign_stable_uids(items, sections)
    return items, final_route


def functional_direct_basis(root: Path | str) -> list[dict[str, Any]] | None:
    """直抽产物可否作为唯一需求依据（无原子链形态，RATOMIZER_FUNCTIONAL_EXTRACT=1）。

    供 requirements_analysis / clarification_report 的缺原子门共用：三查 producer 家族
    （functional-extract）、items 为列表、守恒闭合。守恒未闭合不在此二值判断内——直接
    ``raise_if_unconserved`` 响亮失败（成文闸门纪律），绝不静默回退空表产"0 条"假交付物。
    不满足前置返回 None，调用方维持各自的响亮失败。
    """
    from requirements_analysis_rules import _read_functional_requirements_payload

    payload = _read_functional_requirements_payload(Path(root))
    if not isinstance(payload, dict):
        return None
    if not str(payload.get("producer") or "").startswith("functional-extract"):
        return None
    conservation = payload.get("conservation")
    if isinstance(conservation, dict):
        # 缺守恒块按现状放行（与 requirements_analysis 消费端闸门同口径）；
        # 有块未闭合 = 响亮失败，绝不静默进成文。
        raise_if_unconserved(conservation)
    items = payload.get("items")
    return items if isinstance(items, list) else None


def run_functional_extract(
    out_dir: Path | str,
    *,
    sections: Sequence[dict[str, Any]] | None = None,
    route: str | None = "stub",
    chat: ExtractChat | None = None,
    blocks: Sequence[dict[str, Any]] | None = None,
    strategy: str | None = None,
    doc_map: dict[str, Any] | None = None,
    max_chars: int | None = None,
) -> dict[str, Any]:
    """运行功能需求直抽，写 functional_requirements.json（governed 路径 + 原子写）。

    ``sections`` 缺省时从 ``chunks.jsonl``（extract_units 条款切分产物）惰性加载——
    不改 extract_units / atomize（硬边界：直抽是旁路新入口，默认关）。

    A2：``strategy`` 缺省读 ``RATOMIZER_CONTEXT_PACK_STRATEGY``（默认 legacy 不变）；
    clause_family 下自动只读加载 A1 整篇地图（``doc_map.load_doc_map``，缺席/不可用
    则不带摘要，退回无地图包——不伪造）。
    """
    out_dir = Path(out_dir).expanduser().resolve()
    if sections is None:
        sections = load_clauses(out_dir)
    sections = list(sections)
    resolved_strategy = context_pack_strategy(strategy)
    if resolved_strategy == "clause_family" and doc_map is None:
        try:
            from doc_map import load_doc_map
            doc_map = load_doc_map(out_dir)
        except Exception:  # noqa: BLE001 — 无地图时退回无地图包，不阻断
            doc_map = None
    # S1-7：指纹并入 route 维度——算指纹前先把 route 解析成稳定身份标签（与执行路径同源）。
    route_label = _resolve_route_label(route, chat)
    fingerprint = extraction_fingerprint(
        sections,
        route_key=route_label,
        context_strategy=resolved_strategy,
        doc_map_key=str(doc_map.get("fingerprint") or "") if isinstance(doc_map, dict) else "",
    )

    # 缓存命中放行（指纹含版本/prompt/护栏/route；clause_family 另含策略与地图键）
    cache = _read_cache(out_dir)
    cached = cache.get(fingerprint)
    if cached is not None and isinstance(cached.get("payload"), dict):
        payload = dict(cached["payload"])
        from result_package import governed_artifact_path
        target = governed_artifact_path(
            out_dir, FUNCTIONAL_REQUIREMENTS_FILENAME, category="pipeline", for_write=False
        )
        if not target.is_file():
            # 缓存命中但产物文件缺席（被清理/损坏）——用缓存负载原样补写：不花 LLM 调用，
            # 也不让阶段陷入"报成功但产物永远缺席"（chain 复用按产物存在性判定）。
            return _finalize_payload(payload, out_dir, route, write=True)
        # 缓存里的 route 如实保留；route 变化已并入指纹，旧产物自然失效（S1-7：stub/openai_compatible 不共键）
        return _finalize_payload(payload, out_dir, route)

    if blocks is None:
        blocks = _load_blocks(out_dir)

    items, executed_route = extract_functional_requirements(
        sections, chat=chat, route=route, blocks=blocks,
        strategy=resolved_strategy, doc_map=doc_map, max_chars=max_chars,
    )
    conservation = conservation_report(sections, items, blocks=blocks)

    payload = {
        "schema_version": 1,
        "producer": FUNCTIONAL_EXTRACT_VERSION,
        "prompt_version": FUNCTIONAL_EXTRACT_PROMPT_VERSION,
        "guards_version": FUNCTIONAL_EXTRACT_GUARDS_VERSION,
        "provenance": provenance("functional_extract", FUNCTIONAL_EXTRACT_VERSION),
        "route_requested": route or "stub",
        "route": executed_route,
        "context_pack_strategy": resolved_strategy,
        "clause_count": len(sections),
        "functional_requirements": len(items),
        "fingerprint": fingerprint,
        "conservation": conservation,
        "items": items,
    }
    # 缓存 stub 与 llm 产物（指纹一致即放行，route 标签随产物保留）
    _write_cache_entry(out_dir, fingerprint, payload)
    return _finalize_payload(payload, out_dir, route, write=True)


def _finalize_payload(
    payload: dict[str, Any],
    out_dir: Path,
    route: str | None,
    *,
    write: bool = False,
) -> dict[str, Any]:
    """原子写盘（仅 write=True）并返回 result 摘要。"""
    from input_completeness import attach_input_completeness
    attach_input_completeness(payload, out_dir)
    if write:
        from result_package import governed_artifact_path
        target = governed_artifact_path(out_dir, FUNCTIONAL_REQUIREMENTS_FILENAME, category="pipeline")
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _replace_with_retry(tmp, target)
    result = {
        "kind": "functional_extract",
        "out_dir": str(out_dir),
        "clause_count": payload.get("clause_count", 0),
        "functional_requirements": payload.get("functional_requirements", 0),
        "route_requested": route or "stub",
        "route": payload.get("route", "stub"),
        "conservation": payload.get("conservation", {}),
        "written": [FUNCTIONAL_REQUIREMENTS_FILENAME] if write else [],
    }
    result["incomplete_inputs"] = payload.get("incomplete_inputs", False)
    result["input_completeness"] = payload.get("input_completeness", {})
    return result


# ---------------------------------------------------------------------------
# 条款加载（不改 extract_units / atomize）
# ---------------------------------------------------------------------------

def load_clauses(out_dir: Path | str) -> list[dict[str, Any]]:
    """从 extract_units 条款切分产物惰性加载条款单元。

    优先读 governed ``chunks.jsonl``（每行一个章节/条款单元，含 section_path/text/block_ids），
    缺失则退回 ``blocks.jsonl`` 经 ``extract_units.assemble_sections`` 现场聚合——两条路径
    都不改 extract_units / atomize 主线（硬边界：直抽是旁路新入口）。
    """
    from io_utils import read_jsonl
    from result_package import governed_artifact_path

    out_dir = Path(out_dir).expanduser().resolve()
    chunks_path = governed_artifact_path(out_dir, "chunks.jsonl", category="pipeline", for_write=False)
    if chunks_path.is_file():
        rows = read_jsonl(chunks_path)
        sections: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            section_path = [str(s) for s in (row.get("section_path") or [])]
            sections.append({
                "section_id": " / ".join(section_path) or str(row.get("chunk_id") or ""),
                "section_path": section_path,
                "heading": str(row.get("heading") or (section_path[-1] if section_path else "")),
                "text": str(row.get("text") or ""),
                "block_ids": [str(b) for b in (row.get("block_ids") or [])],
            })
        if sections:
            return sections
    # 兜底：现场聚合 blocks（不改 atomize，只读其产物）
    blocks_path = governed_artifact_path(out_dir, "blocks.jsonl", category="pipeline", for_write=False)
    if blocks_path.is_file():
        from extract_units import assemble_sections
        return list(assemble_sections(read_jsonl(blocks_path)))
    return []


def _load_blocks(out_dir: Path) -> list[dict[str, Any]]:
    from io_utils import read_jsonl
    from result_package import governed_artifact_path
    path = governed_artifact_path(out_dir, "blocks.jsonl", category="pipeline", for_write=False)
    return read_jsonl(path) if path.is_file() else []
