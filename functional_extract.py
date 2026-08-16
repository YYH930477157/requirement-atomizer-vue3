"""WS2 功能需求直抽（默认生产入口，可显式回滚）。

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

入口开关 ``RATOMIZER_FUNCTIONAL_EXTRACT``（默认 ``1``=功能直抽路径）。=1 时 chain_task 把
``ai-extract``+``functional-synthesis`` 两阶段整体替换为本模块（``functional-extract`` 阶段）；
显式设为 ``0`` 时回滚到旧原子化路径。
也可经 ``ratomizer functional-extract`` 单步子命令直跑。产物路径走
``result_package.governed_artifact_path``，缓存指纹按仓库既有模式接入
（``FUNCTIONAL_EXTRACT_VERSION`` + prompt 版本 + 护栏版本）。

守恒核对（§3.1 obligation/evidence 模型，2026-08-15 起）：条款与功能需求是**多对多**关系
——一个条款可产出多条需求（一句多 shall），一条需求可关联多个来源条款（跨条款引用合法，
不判重复抽取）。守恒分五项检查（条款覆盖/义务覆盖/无证据需求/重复需求/保留完整性），
判据全部确定性（句切分与义务模态复用 ``functional_drilldown``；取证复用
``merged_consistency.match_source_quote_blocks``，与 ``review_tools.coverage_check`` 同源）。
证据锚（``evidence_anchors``）由确定性后处理派生，LLM 不得填写。任一 blocking 类别未闭合
即经 ``raise_if_unconserved`` 阻塞成文导出（强制人工），不静默放行。

失败语义（§3.5）：执行结果类别 ``execution_status`` ∈ ok/partial/failed——真实生产运行
出现 stub 降级（请求了 LLM 路由却全部退化）、mixed（部分条款失败）时，阶段不得记 ok，
下游 ``functional_direct_basis`` 响亮阻断；缓存行保留执行结果类别，重放不洗白。
显式 ``route="stub"`` 是测试/烟测的合法 opt-in，不算失败。

WS0 功能需求级真值集尚是 pending-human；默认翻转不放宽守恒、执行完整性或发布门禁，
旧路径继续作为 ``RATOMIZER_FUNCTIONAL_EXTRACT=0`` 的显式回滚通道。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from cosem_behavior_spec import extract_codes, extract_ints
from requirement_record import provenance

FUNCTIONAL_EXTRACT_VERSION = "functional-extract-v1"
FUNCTIONAL_EXTRACT_PROMPT_VERSION = "functional-extract-prompt-v2"
# S1-8：bump v1→v2。``_reject_drifted_codes`` 清洗范围从仅 objective 扩到全部叙述字段
# （behaviors/data_constraints/variants/exceptions/preconditions/description），缓存产物内容
# 变化——指纹含 guards 版本，bump 后旧 stub/LLM 缓存（behaviors 里残留幻觉编码）自然失效。
#
# 2026-08-15 去原子化方案 §3.1：bump v2→v3。守恒模型从 block exactly-once 换成
# obligation/evidence 多对多（多义务条款出多条不判重、跨条款引用合法），并新增五项分项
# 检查（条款覆盖/义务覆盖/无证据需求/重复需求/保留完整性）——产物语义变化，旧缓存失效。
# 三轮复审 P1-2（2026-08-16）：cross_script_review 记录新增 source_text_hash/句子
# 摘录（跨语种确认身份绑定义务文本）——守恒载荷内容变化，bump v4 → v5 使存量
# 缓存失效，否则旧缓存恢复的 cross_script_review 无哈希，绕过确认失效机制。
FUNCTIONAL_EXTRACT_GUARDS_VERSION = "functional-extract-guards-v5"
# §3.1 新守恒模型版本戳（进 conservation 报告与抽取指纹；模型演进时 bump）。
# M1（2026-08-16 修复方案 §3.4）：obligation 覆盖从全局叙述并集改为声明局部绑定
# （eligible-only 边；source_quote 只作锚）——产物语义变化，v1 → v2。
# 三轮复审 P1-2：同上——conservation 载荷语义变化（cross_script_review 携带文本身份），
# bump v2 → v3。
FUNCTIONAL_CONSERVATION_MODEL_VERSION = "functional-conservation-obligation-evidence-v3"
FUNCTIONAL_REQUIREMENTS_FILENAME = "functional_requirements.json"
FUNCTIONAL_EXTRACT_CACHE = "functional_extract_cache.jsonl"

# P0-8：负例 few-shot 注入数量上限（可配）。§3.6：改经 config 单源读取（运行时求值，
# 进程内改 env 即生效——旧 import 时常量在同进程 shadow 场景下不刷新）。
def functional_extract_negative_k() -> int:
    from config import get_env_int
    return max(0, get_env_int("RATOMIZER_FUNCTIONAL_EXTRACT_NEGATIVE_K"))


# 兼容别名：desktop_tasks 阶段指纹等既有消费点引用的模块常量（真实读取走上面的函数）。
FUNCTIONAL_EXTRACT_NEGATIVE_K = functional_extract_negative_k()

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
    """守恒核对未闭合：功能需求集合存在 blocking 失败类别，阻塞成文导出（强制人工）。"""


class FunctionalExtractionIncompleteError(RuntimeError):
    """§3.5 失败语义：直抽执行不完整（stub 降级 / mixed 部分失败），阻塞下游分析与成文。"""


# ---------------------------------------------------------------------------
# 入口开关
# ---------------------------------------------------------------------------

def functional_extract_enabled(value: str | None = None) -> bool:
    """RATOMIZER_FUNCTIONAL_EXTRACT 是否开启（默认开，单源默认值在 config.ENV_REGISTRY）。"""
    from config import get_env_bool
    return get_env_bool(ENTRY_SWITCH_ENV, override=value)


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
        "conservation_model": FUNCTIONAL_CONSERVATION_MODEL_VERSION,
        "route_key": str(route_key or ""),
        # 负例条数改变 prompt 内容 → 必须换键（§3.6：经 config 单源函数运行时读取）。
        "negative_k": functional_extract_negative_k(),
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
    # §3.1：回显全文（旧 [:200] 截断会让长条款的义务句在守恒核对中"失踪"——stub 是
    # 占位条目，逐字回显是它对条款集合最诚实的覆盖方式）。
    behaviors = [source_text] if source_text.strip() else [heading]
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
# 守恒核对（§3.1 obligation/evidence 多对多模型）
# ---------------------------------------------------------------------------
# 旧模型（exactly-once：每 block 被且只被一条需求消费）把"一句多 shall 的条款"压成一条、
# 把合法的跨条款引用误判为重复抽取。新模型：
#   1. 多对多合法——一个条款可产出多条需求，一条需求可关联多个来源条款；
#   2. 证据锚（evidence anchors）由确定性后处理派生（句切分与义务模态判据复用
#      functional_drilldown，LLM 不得填写——结构字段冻结纪律不变）；
#   3. 分项检查各自定性（替换单一 ok 布尔）：
#      - 条款覆盖率：每条款块至少被一条需求的证据锚覆盖（未覆盖=漏抽，blocking）；
#      - 义务覆盖率：每个义务句至少被一条需求覆盖（未覆盖=义务丢失，blocking）；
#      - 无证据需求：source_block_ids 为空或引句不命中任何声明块（blocking）；
#      - 重复需求：同一义务句被多条需求覆盖**且**叙述高度相似（多视角引用不判重）；
#      - 保留完整性：条件/例外/否定/数值/单位在需求叙述中的保存（分级：研发直接
#        执行的数值/单位/否定丢失为 blocking，条件/例外丢失为 warning）。

# 与 functional_drilldown 同源：句切分 + 义务模态词表（不重写判据）。
from functional_drilldown import (  # noqa: E402 — 同源复用，避免两份判据漂移
    _OBLIGATION_MODALS as _DRILLDOWN_OBLIGATION_MODALS,
    _SENTENCE_SPLIT_RE as _DRILLDOWN_SENTENCE_SPLIT_RE,
)

_EN_MODAL_RE = re.compile(
    r"\b(?:" + "|".join(
        re.escape(m) for m in _DRILLDOWN_OBLIGATION_MODALS if m.isascii() and " " not in m
    ) + r")\b",
    re.IGNORECASE,
)
_EN_MODAL_PHRASE_RE = re.compile(
    r"\b(?:" + "|".join(
        re.escape(m) for m in _DRILLDOWN_OBLIGATION_MODALS if m.isascii() and " " in m
    ) + r")\b",
    re.IGNORECASE,
)
# 中文模态词按字面匹配；"可"排除"可能"（副词，非义务），"须/应/宜/必须/需要"无此歧义。
_ZH_MODAL_RE = re.compile(r"必须|需要|应|须|宜|可(?!能)")

def _has_obligation_modal(text: str) -> bool:
    return bool(
        _EN_MODAL_RE.search(text)
        or _EN_MODAL_PHRASE_RE.search(text)
        or _ZH_MODAL_RE.search(text)
    )

# 义务单元切分：在**每个模态词前**切开——"shall A ... shall B" → ["…subject", "shall A…",
# "shall B…"]。带头模态 + 至少一个内容词的片段才是义务单元（"The meter shall " 这种
# 无动作尾巴不成义务；主语片段无模态词不成义务）。
_OBLIGATION_UNIT_SPLIT_RE = re.compile(
    r"(?=\b(?:" + "|".join(
        re.escape(m) for m in _DRILLDOWN_OBLIGATION_MODALS if m.isascii()
    ) + r")\b)"
    r"|(?=必须|需要|应|须|宜|可(?!能))"
)

# 保留完整性标记（确定性；中文否定词只取短语级——单字 不/无/非 在 无线/非常 等词内
# 误伤率过高，宁漏报 warning 也不误报 blocking）。
_PRESERVATION_PATTERNS: dict[str, re.Pattern[str]] = {
    "condition": re.compile(
        r"\b(?:if|when|whenever|in case|where|depending on|either|or|otherwise|once)\b"
        r"|如果|若是|或者|否则|视.{0,8}而定|当.{0,12}时|在.{0,12}时",
        re.IGNORECASE,
    ),
    "exception": re.compile(r"\b(?:except|unless)\b|除非|除外", re.IGNORECASE),
    "negation": re.compile(
        r"\b(?:not|no|neither|nor|never|without|cannot)\b"
        r"|不得|不能|不应|不可|无法|禁止|尚未",
        re.IGNORECASE,
    ),
}
# 数值/单位/否定 = 研发直接执行的字段（丢失即 blocking）；条件/例外 = 上下文修饰（warning）。
_PRESERVATION_SEVERITY = {
    "condition": "warning",
    "exception": "warning",
    "negation": "blocking",
    "number": "blocking",
    "unit": "blocking",
}
_NUMBER_UNIT_RE = re.compile(
    r"(?<![A-Za-z0-9])(\d+(?:\.\d+)?)\s*"
    r"(kWh|kvar|kVA|kHz|MHz|GHz|Hz|kV|mV|V|mA|A|kW|W|var|ms|s|min|h|°C|%)(?![A-Za-z])"
)

_CONTENT_WORD_RE = re.compile(r"[a-z]{3,}|\d+(?:\.\d+)?|[一-鿿]")
_EN_STOPWORDS = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "been", "have", "has", "had", "but", "all", "any", "its", "their", "when",
    "than", "then", "into", "shall", "must", "will", "should", "may", "not",
    "set", "one", "two", "used", "using", "use", "each", "which", "who", "such",
})


def _content_tokens(text: str) -> set[str]:
    """内容 token 集：≥3 字符英文词（去停用词）+ 数字 + 中文字符。"""
    tokens = set()
    for raw in _CONTENT_WORD_RE.findall(str(text or "").casefold()):
        if raw.isascii() and raw.isalpha() and raw in _EN_STOPWORDS:
            continue
        tokens.add(raw)
    return tokens


def _squashed(text: str) -> str:
    return "".join(str(text or "").split())


def _sentence_covered_by(
    sentence: str, narrative: str, *, ignore_tokens: frozenset[str] | set[str] = frozenset(),
) -> bool:
    """义务单元是否被需求叙述覆盖：逐字包含，或内容 token 重叠率 ≥ 0.6（确定性）。

    ``ignore_tokens`` 剔除章节引用号等非内容 token（"as defined in 4.1" 的 4.1 是引用，
    不是覆盖义务的一部分）。
    """
    sentence = str(sentence or "").strip()
    narrative = str(narrative or "")
    if not sentence:
        return True
    if not narrative.strip():
        return False
    if _squashed(sentence) in _squashed(narrative):
        return True
    sentence_tokens = _content_tokens(sentence) - set(ignore_tokens)
    if not sentence_tokens:
        return True  # 纯停用词/标点/引用号单元——无从判漏，视为覆盖（宁漏勿错作用于门禁）
    narrative_tokens = _content_tokens(narrative)
    overlap = len(sentence_tokens & narrative_tokens)
    return overlap / len(sentence_tokens) >= 0.6


def _narrative_similarity(a: str, b: str) -> float:
    ta, tb = _content_tokens(a), _content_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


_NARRATIVE_FIELDS = (
    "objective", "description", "preconditions", "variants", "exceptions",
)


def item_narrative(item: dict[str, Any]) -> str:
    """需求自己的叙述（不含 source_quote——保留完整性检查的对象是叙述本身）。"""
    parts: list[str] = []
    for field in _NARRATIVE_FIELDS:
        parts.append(str(item.get(field) or ""))
    for field in ("behaviors", "data_constraints", "related_dlms_objects"):
        values = item.get(field)
        if isinstance(values, list):
            parts.extend(str(v) for v in values)
    return "\n".join(p for p in parts if p.strip())


def _section_sentences(section: dict[str, Any]) -> list[str]:
    """条款句切分（句号/分号/换行级，切分正则与 functional_drilldown 同源）。"""
    text = str(section.get("text") or "")
    return [s.strip() for s in _DRILLDOWN_SENTENCE_SPLIT_RE.split(text) if s.strip()]


def _obligation_units(sentence: str) -> list[str]:
    """句内义务单元：模态词带头、且除模态/停用词外至少一个内容词的片段。"""
    units: list[str] = []
    for part in _OBLIGATION_UNIT_SPLIT_RE.split(sentence):
        part = part.strip()
        if not part or not _has_obligation_modal(part):
            continue
        if _content_tokens(part):
            units.append(part)
    return units


def _obligation_index(section: dict[str, Any]) -> list[dict[str, Any]]:
    """条款的义务单元清单（模态动词支配的独立行为；判据与 drilldown 多行为信号同源）。

    ``unit_index`` 是条款内义务单元的顺序号（跨句连续），作守恒/判重的稳定键。
    """
    rows: list[dict[str, Any]] = []
    for sentence_index, sentence in enumerate(_section_sentences(section)):
        for unit in _obligation_units(sentence):
            rows.append({
                "sentence_index": sentence_index,
                "unit_index": len(rows),
                "sentence": unit,
            })
    return rows


def _script_profile(text: str) -> set[str]:
    """文本使用的文字系统（latin/cjk）——跨语种叙述的确定性判据。

    按**实质内容**判定：单个拉丁字母（id 里的 B1/FRE- 尾巴）不算 latin——须有 ≥3
    连续字母的英文词；≥2 个汉字才算 cjk。否则 ZH 叙述里引一个编号就会误判双语境。
    """
    scripts: set[str] = set()
    if re.search(r"[A-Za-z]{3,}", text or ""):
        scripts.add("latin")
    if len(re.findall(r"[一-鿿]", text or "")) >= 2:
        scripts.add("cjk")
    return scripts


def _scripts_disjoint(a: set[str], b: set[str]) -> bool:
    """语种不相交：token 覆盖/词面保留对跨语种转述（EN 条款 ↔ ZH 叙述）天然失效。"""
    return not (a & b)


def _preservation_findings(
    section: dict[str, Any], narrative_union: str,
    known_section_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """条款中的条件/例外/否定/数值/单位在需求叙述并集里是否保留（丢失=分级 finding）。

    基准文本只取条款正文（``text``）——heading 是条款编号/标题，其编号数字不该要求在
    需求叙述里复现。正文里对**其他条款的引用编号**（"as defined in 4.1"）同样不是可执行
    数值：已知章节号先从基准文本剔除，再抽数值/单位。

    跨语种（条款与叙述语种不相交）：条件/例外/否定的**词面**标记无法跨语种核对
    （EN "not" 不会出现在 ZH 叙述里），跳过词面检查只保留数值/单位（数字跨语种通用）；
    义务覆盖侧同理由锚定回退（见 conservation_report）——确定性判据宁漏勿错，不误报 blocking。
    """
    source_text = str(section.get("text") or "")
    if _scripts_disjoint(
        _script_profile(source_text), _script_profile(narrative_union),
    ):
        word_kinds: tuple[str, ...] = ()
    else:
        word_kinds = tuple(_PRESERVATION_PATTERNS)
    own_ids = {str(section.get("section_id") or "")}
    for segment in (section.get("section_path") or []):
        text_segment = str(segment or "").strip()
        if text_segment:
            own_ids.add(text_segment)
    for token in sorted(own_ids | set(known_section_ids or ())):
        if token:
            source_text = source_text.replace(token, " ")
    findings: list[dict[str, Any]] = []
    for kind in word_kinds:
        pattern = _PRESERVATION_PATTERNS[kind]
        source_hits = {m.group(0).lower() for m in pattern.finditer(source_text)}
        narrative_hits = {m.group(0).lower() for m in pattern.finditer(narrative_union)}
        for token in sorted(source_hits - narrative_hits):
            findings.append({
                "kind": kind, "token": token,
                "severity": _PRESERVATION_SEVERITY[kind],
            })
    source_ints = set(extract_ints(source_text))
    narrative_ints = set(extract_ints(narrative_union))
    for value in sorted(source_ints - narrative_ints):
        findings.append({"kind": "number", "token": str(value), "severity": "blocking"})
    narrative_squashed_units = {
        m.group(2).lower() for m in _NUMBER_UNIT_RE.finditer(narrative_union)
    }
    for match in _NUMBER_UNIT_RE.finditer(source_text):
        number, unit = match.group(1), match.group(2)
        if number in narrative_ints and unit.lower() not in narrative_squashed_units:
            findings.append({
                "kind": "unit", "token": f"{number} {unit}", "severity": "blocking",
            })
    return findings


def _known_section_tokens(sections: Sequence[dict[str, Any]]) -> set[str]:
    """全部已知章节号/路径段（义务覆盖判定的引用号剔除集）。"""
    tokens: set[str] = set()
    for section in sections:
        sid = str(section.get("section_id") or "").strip()
        if sid:
            tokens.add(sid)
        for segment in (section.get("section_path") or []):
            text_segment = str(segment or "").strip()
            if text_segment:
                tokens.add(text_segment)
    return tokens


def _obligation_evidence_edges(
    items: Sequence[dict[str, Any]],
    sections: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """M1（§3.2/3.3）：obligation/evidence 局部绑定边——守恒检查与证据锚的唯一权威。

    eligible = 声明块与该义务所属条款块**相交**的 item（声明即绑定）。义务覆盖只在
    eligible items 内判定，彻底删除"所有叙述的全局并集"借位——F1 声明 B1 却复述 B2、
    F2 占位声明 B2 的组合不再可能假通过。

    ``match_method`` 优先级：
    - ``lexical``：需求叙述对义务单元的确定性 token 覆盖（计入义务覆盖）；
    - ``source_quote``：引句逐字含义务单元——只作证据锚（下游展示/Claim 溯源），
      **不计入义务覆盖**（占位叙述不能靠引句回充当覆盖，测试矩阵 §3.5-1）；
    - ``cross_script_review``：跨语言无法确定性比较，但声明有效且引句命中该条款——
      覆盖成立、必须进入人工复核，且只能覆盖**当前声明**的条款（不得借他款叙述）。

    合法多对多保留：一个义务可有多条边；一条 FRE 可声明多个 section 并各得边。
    """
    edges: list[dict[str, Any]] = []
    ignore_tokens = _known_section_tokens(sections)
    for section_index, section in enumerate(sections):
        section_blocks = {
            str(b) for b in (section.get("block_ids") or []) if str(b)
        }
        if not section_blocks:
            continue
        section_id = str(section.get("section_id") or "")
        section_text = str(section.get("text") or "")
        section_label = " / ".join(
            str(s) for s in (section.get("section_path") or [])
        ) or section_id
        clause_scripts = _script_profile(section_text)
        for obligation in _obligation_index(section):
            sentence = obligation["sentence"]
            source_text_hash = hashlib.sha256(
                sentence.encode("utf-8")).hexdigest()
            for item_index, item in enumerate(items):
                declared = {
                    str(b) for b in (item.get("source_block_ids") or []) if str(b)
                }
                if not declared & section_blocks:
                    continue  # 未声明该条款——不是 eligible，不得借位
                narrative = item_narrative(item)
                quote = str(item.get("source_quote") or "")
                if _sentence_covered_by(
                        sentence, narrative, ignore_tokens=ignore_tokens):
                    method = "lexical"
                elif (
                    narrative.strip()
                    and quote.strip()
                    and _scripts_disjoint(clause_scripts, _script_profile(narrative))
                    and (
                        _squashed(quote) in _squashed(section_text)
                        or _squashed(section_text) in _squashed(quote)
                    )
                ):
                    # 跨语种优先于 source_quote：引句回显验证不了跨语种叙述，
                    # 诚实语义是"声明+引句有效 → 覆盖成立但须人工复核"。
                    method = "cross_script_review"
                elif quote.strip() and _squashed(sentence) in _squashed(quote):
                    method = "source_quote"
                else:
                    continue
                edges.append({
                    "functional_requirement_id": str(
                        item.get("functional_requirement_id") or ""),
                    "item_index": item_index,
                    "section_index": section_index,
                    "section_id": section_id,
                    "section": section_label,
                    "sentence_index": obligation["sentence_index"],
                    "unit_index": obligation["unit_index"],
                    "declared_block_ids": sorted(declared),
                    "block_ids": sorted(section_blocks),
                    "quote": sentence[:400],
                    "source_text_hash": source_text_hash,
                    "match_method": method,
                })
    return edges


# 计入义务覆盖的边方法（source_quote 只作锚，不当覆盖——占位叙述不得靠引句回充）
_COVERAGE_EDGE_METHODS = frozenset({"lexical", "cross_script_review"})


def _edges_as_anchors(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """边 → 持久化 evidence_anchors 形态（下游展示/Claim 溯源用；守恒永远现算）。"""
    return [
        {
            "section_id": edge["section_id"],
            "section": edge["section"],
            "block_ids": edge["block_ids"],
            "quote": edge["quote"],
            "sentence_index": edge["sentence_index"],
            "unit_index": edge["unit_index"],
            "source_text_hash": edge["source_text_hash"],
            "match_method": edge["match_method"],
            "kind": "obligation",
            "origin": "declared",
        }
        for edge in edges
    ]


def _anchors_for_item(
    item: dict[str, Any],
    sections: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """单条 item 的证据锚（= 其全部绑定边；与守恒共用 _obligation_evidence_edges）。"""
    edges = _obligation_evidence_edges([item], sections)
    return _edges_as_anchors(edges)


def assign_evidence_anchors(
    items: Sequence[dict[str, Any]],
    sections: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """给每条需求盖确定性证据锚（``evidence_anchors``）——LLM 不得填写。

    M1 起，锚 = 该 item 的全部 obligation/evidence 绑定边（含 match_method 与
    source_text_hash）。只声明才锚定：叙述复述未声明条款不再产生锚。
    """
    edges = _obligation_evidence_edges(items, sections)
    by_item: dict[int, list[dict[str, Any]]] = {}
    for edge in edges:
        by_item.setdefault(edge["item_index"], []).append(edge)
    for index, item in enumerate(items):
        item["evidence_anchors"] = _edges_as_anchors(by_item.get(index, []))
    return list(items)


def conservation_report(
    sections: Sequence[dict[str, Any]],
    items: Sequence[dict[str, Any]],
    *,
    blocks: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """obligation/evidence 守恒报告（§3.1 多对多模型，五项分项检查）。

    取证复用 ``merged_consistency.match_source_quote_blocks``（与
    ``review_tools.coverage_check`` 同源匹配器）校验每条 item 的 source_quote 是否命中
    其声明的 source_block_ids。下钻条款递归守恒保留：``drilled_subatoms`` 的子原子
    block_ids 并集必须等于父条款 block_ids。

    报告同时保留旧字段镜像（missing/extra/duplicate_assignments/evidence_mismatches），
    但语义随模型升级：``duplicate_assignments`` 现在指"重复需求组涉及的块"（多消费合法，
    只有义务句+叙述双重命中才判重），不再是"被多条需求声明的块"。
    """
    from merged_consistency import match_source_quote_blocks

    section_block_ids = [
        sorted({str(b) for b in (section.get("block_ids") or []) if str(b)})
        for section in sections
    ]
    clause_block_set = {b for blocks_ids in section_block_ids for b in blocks_ids}

    narratives = [item_narrative(item) for item in items]
    # M1：统一边生成——守恒检查与证据锚共用同一结果；持久化 anchors 只是下游展示数据，
    # 守恒永远现算（产物里被篡改/陈旧的锚不能伪造覆盖结论）。
    edges = _obligation_evidence_edges(items, sections)
    edges_by_obligation: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for edge in edges:
        edges_by_obligation.setdefault(
            (edge["section_id"], edge["unit_index"]), []).append(edge)
    edges_by_item: dict[int, list[dict[str, Any]]] = {}
    for edge in edges:
        edges_by_item.setdefault(edge["item_index"], []).append(edge)

    # ---- 检查 1：条款覆盖率（每条款块至少被一条需求的声明/绑定边覆盖）----
    covered_blocks: set[str] = set()
    for item in items:
        covered_blocks.update(str(b) for b in (item.get("source_block_ids") or []) if str(b))
    for edge in edges:
        covered_blocks.update(str(b) for b in (edge.get("block_ids") or []) if str(b))
    uncovered_sections: list[dict[str, Any]] = []
    for section, blocks_ids in zip(sections, section_block_ids):
        if blocks_ids and not set(blocks_ids) & covered_blocks:
            uncovered_sections.append({
                "section_id": str(section.get("section_id") or ""),
                "heading": str(section.get("heading") or "")[:80],
                "block_ids": blocks_ids,
            })
    missing_block_ids = sorted(clause_block_set - covered_blocks)
    declared_ids = [str(b) for item in items for b in (item.get("source_block_ids") or []) if str(b)]
    extra_block_ids = sorted({b for b in declared_ids if b not in clause_block_set})

    # ---- 检查 2：义务覆盖率（局部绑定：每个义务单元至少被一条 eligible 边覆盖）----
    # M1：覆盖只认 lexical / cross_script_review 边（声明即绑定）；source_quote 边只作
    # 证据锚。跨语种边覆盖成立但必须人工复核（cross_script_review 清单留痕，warning 级）。
    ignore_tokens = _known_section_tokens(sections)
    uncovered_obligations: list[dict[str, Any]] = []
    cross_script_review: list[dict[str, Any]] = []
    sentence_cover_items: dict[tuple[str, int], list[int]] = {}
    for section, blocks_ids in zip(sections, section_block_ids):
        section_id = str(section.get("section_id") or "")
        for obligation in _obligation_index(section):
            key = (section_id, obligation["unit_index"])
            obligation_edges = edges_by_obligation.get(key) or []
            covering = [
                edge["item_index"] for edge in obligation_edges
                if edge["match_method"] == "lexical"
            ]
            if covering:
                sentence_cover_items[key] = covering
            if any(
                edge["match_method"] in _COVERAGE_EDGE_METHODS
                for edge in obligation_edges
            ):
                for edge in obligation_edges:
                    if edge["match_method"] == "cross_script_review":
                        # 复审 P1-2 二轮：复核记录必须绑定**源义务文本身份**——
                        # 只有 FRE id/section/unit 的话，专家确认后改义务文本，
                        # 确认 ID 与指纹都不变，旧确认被自动沿用。source_text_hash
                        # 随义务文本变化，下游澄清问题的身份随之换新。
                        cross_script_review.append({
                            "section_id": section_id,
                            "unit_index": obligation["unit_index"],
                            "functional_requirement_id":
                                edge["functional_requirement_id"],
                            "source_text_hash": edge["source_text_hash"],
                            "sentence": obligation["sentence"][:160],
                        })
            else:
                uncovered_obligations.append({
                    "section_id": section_id,
                    "sentence_index": obligation["sentence_index"],
                    "unit_index": obligation["unit_index"],
                    "sentence": obligation["sentence"][:160],
                })

    # ---- 检查 3：无证据需求（无声明块 / 引句零命中或不命中声明块 / 叙述与声明条款错绑）----
    no_evidence_items: list[dict[str, Any]] = []
    evidence_mismatches: list[dict[str, Any]] = []
    binding_mismatches: list[dict[str, Any]] = []
    # 错绑检测（审查 2026-08-15 P1）：声明的 source_block_ids 与叙述实际覆盖的义务单元
    # 所属条款不一致——叙述互换/错误溯源会让条款覆盖假通过。跨语种（token 覆盖失效）
    # 与无义务单元的家条款无从判定，跳过（宁漏勿错，不误报 blocking）。
    clause_units: list[list[dict[str, Any]]] = [_obligation_index(s) for s in sections]
    for item_index, item in enumerate(items):
        narrative = narratives[item_index]
        ids = [str(b) for b in (item.get("source_block_ids") or []) if str(b)]
        fre_id = str(item.get("functional_requirement_id") or "")
        if not ids:
            no_evidence_items.append({
                "functional_requirement_id": fre_id, "reason": "empty_source_block_ids",
            })
            continue
        if blocks:  # 空列表 = 无 blocks 证据可用，不做引句命中校验（不伪造通过也不误报）
            quote = str(item.get("source_quote") or "")
            if quote.strip():
                hit_block_ids, _method = match_source_quote_blocks(quote, list(blocks))
                if not hit_block_ids:
                    # 引句在全文零命中 = 无效证据（审查 P1：旧逻辑零命中直接放行）
                    evidence_mismatches.append({
                        "functional_requirement_id": fre_id,
                        "reason": "quote_matches_no_block",
                        "declared_block_ids": ids,
                        "quote_hit_block_ids": [],
                    })
                elif not set(hit_block_ids).intersection(ids):
                    evidence_mismatches.append({
                        "functional_requirement_id": fre_id,
                        "declared_block_ids": ids,
                        "quote_hit_block_ids": hit_block_ids,
                    })
        declared_set = set(ids)
        home_indices = [
            i for i, blocks_ids in enumerate(section_block_ids) if blocks_ids and set(blocks_ids) & declared_set
        ]
        home_with_units = [
            i for i in home_indices
            if clause_units[i]
            and not _scripts_disjoint(
                _script_profile(str(sections[i].get("text") or "")),
                _script_profile(narrative),
            )
        ]
        if home_with_units and narrative.strip():
            # M1 §3.3-7：声明了含义务单元的条款（同语种），却连一条本地边都没有
            # （lexical/cross_script_review/source_quote 任一方法）——叙述与引句都
            # 锚不住本条款的占位声明。注意：义务覆盖缺口由检查 2 兜底（eligible-only），
            # 此处不要求"覆盖级"边——合法的多视角转述（0.5 重叠 + 引句锚）不受罚。
            local_edge_sections = {
                edge["section_index"] for edge in (edges_by_item.get(item_index) or [])
            }
            if not (set(home_with_units) & local_edge_sections):
                binding_mismatches.append({
                    "functional_requirement_id": fre_id,
                    "reason": "declared_section_has_no_local_obligation_coverage",
                    "declared_block_ids": ids,
                    "declared_section_ids": [
                        str(sections[i].get("section_id") or "") for i in home_with_units
                    ],
                })
                continue
            covered_clause_indices = {
                i for i, units in enumerate(clause_units)
                if any(
                    _sentence_covered_by(unit["sentence"], narrative, ignore_tokens=ignore_tokens)
                    for unit in units
                )
            }
            if covered_clause_indices and not (
                set(home_with_units) & covered_clause_indices
            ):
                binding_mismatches.append({
                    "functional_requirement_id": fre_id,
                    "reason": "narrative_covers_other_clauses_not_declared",
                    "declared_block_ids": ids,
                    "declared_section_ids": [
                        str(sections[i].get("section_id") or "") for i in home_with_units
                    ],
                    "narrative_covers_section_ids": [
                        str(sections[i].get("section_id") or "")
                        for i in sorted(covered_clause_indices)
                    ],
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
                    "functional_requirement_id": fre_id,
                    "reason": "drilldown_subatoms_do_not_consume_parent",
                    "parent_block_ids": sorted(parent_blocks),
                    "child_block_union": sorted(child_blocks),
                })

    # ---- 检查 4：重复需求（同一义务句被多条覆盖**且**叙述高度相似）----
    duplicate_groups: list[dict[str, Any]] = []
    duplicate_block_ids: set[str] = set()
    section_by_id = {
        str(section.get("section_id") or ""): blocks_ids
        for section, blocks_ids in zip(sections, section_block_ids)
    }
    for (section_id, unit_index), covering in sorted(sentence_cover_items.items()):
        if len(covering) < 2:
            continue
        pairs: set[frozenset[int]] = set()
        for i in covering:
            for j in covering:
                if i < j and _narrative_similarity(narratives[i], narratives[j]) >= 0.8:
                    pairs.add(frozenset((i, j)))
        if not pairs:
            continue  # 多视角引用同一义务单元——合法，不判重
        group_items = sorted(
            {i for pair in pairs for i in pair},
            key=lambda i: str(items[i].get("functional_requirement_id") or ""),
        )
        group_blocks = sorted(
            {b for i in group_items for b in (items[i].get("source_block_ids") or [])}
            | set(section_by_id.get(section_id) or [])
        )
        duplicate_block_ids.update(group_blocks)
        duplicate_groups.append({
            "section_id": section_id,
            "unit_index": unit_index,
            "functional_requirement_ids": [
                str(items[i].get("functional_requirement_id") or "") for i in group_items
            ],
            "block_ids": group_blocks,
        })

    # ---- 检查 5：保留完整性（条件/例外/否定/数值/单位，分级）----
    known_section_ids: set[str] = set()
    for section in sections:
        sid = str(section.get("section_id") or "")
        if sid:
            known_section_ids.add(sid)
        for segment in (section.get("section_path") or []):
            text_segment = str(segment or "").strip()
            if text_segment:
                known_section_ids.add(text_segment)
    preservation_losses: list[dict[str, Any]] = []
    for section, blocks_ids in zip(sections, section_block_ids):
        # M1：保留完整性的叙述并集 = 声明了该条款的 items（绑定边只落在声明条款上）
        anchored_narratives = [
            narratives[i] for i, item in enumerate(items)
            if set(str(b) for b in (item.get("source_block_ids") or []) if str(b)) & set(blocks_ids)
        ]
        if not anchored_narratives:
            continue  # 条款本身未覆盖——已由检查 1 阻塞，保留完整性无从谈起
        narrative_union = "\n".join(anchored_narratives)
        for finding in _preservation_findings(section, narrative_union, known_section_ids):
            preservation_losses.append({
                "section_id": str(section.get("section_id") or ""),
                **finding,
            })

    blocking_losses = [f for f in preservation_losses if f.get("severity") == "blocking"]
    warning_losses = [f for f in preservation_losses if f.get("severity") != "blocking"]

    checks = {
        "clause_coverage": {
            "ok": not uncovered_sections,
            "uncovered_sections": uncovered_sections[:50],
        },
        "obligation_coverage": {
            "ok": not uncovered_obligations,
            "uncovered_obligations": uncovered_obligations[:50],
            # 跨语种边：覆盖成立但必须人工复核（M1 §3.2 cross_script_review）
            "cross_script_review": cross_script_review[:50],
        },
        "evidence_presence": {
            "ok": not no_evidence_items and not evidence_mismatches
            and not binding_mismatches,
            "items_without_evidence": no_evidence_items[:50],
            "evidence_mismatches": evidence_mismatches[:50],
            "binding_mismatches": binding_mismatches[:50],
        },
        "duplicates": {
            "ok": not duplicate_groups,
            "groups": duplicate_groups[:50],
        },
        "preservation": {
            "ok": not blocking_losses,
            "blocking_losses": blocking_losses[:50],
            "warning_losses": warning_losses[:50],
        },
    }
    failure_categories = sorted(
        name for name, result in checks.items() if not result["ok"]
    )
    ok = not failure_categories
    return {
        "model": FUNCTIONAL_CONSERVATION_MODEL_VERSION,
        "ok": ok,
        "failure_categories": failure_categories,
        "checks": checks,
        "warning_count": len(warning_losses) + len(cross_script_review),
        # 旧字段镜像（adjudicate / orchestration_gaps / shadow 门等消费点不变，
        # 语义随模型升级——见 docstring）
        "clause_block_count": len(clause_block_set),
        "covered_block_count": len(covered_blocks & clause_block_set),
        "missing_block_ids": missing_block_ids[:50],
        "duplicate_assignments": sorted(duplicate_block_ids)[:50],
        "extra_block_ids": extra_block_ids[:50],
        "evidence_mismatches": evidence_mismatches[:50],
        "block_export": not ok,  # 存在任一 blocking 类别 → 阻塞成文导出（强制人工）
    }


def raise_if_unconserved(report: dict[str, Any]) -> None:
    """成文导出闸门：守恒核对存在任一 blocking 失败类别即抛 FunctionalConservationError。

    兼容旧形报告（只有顶层 ok）——ok=False 一律阻塞；新形报告按分项类别给出计数。
    """
    if report.get("ok", True):
        return
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    if checks:
        detail = "；".join(
            f"{name}={_check_failure_count(name, result)}"
            for name, result in sorted(checks.items())
            if not result.get("ok", True)
        )
    else:
        detail = (
            f"missing={len(report.get('missing_block_ids') or [])} "
            f"duplicate={len(report.get('duplicate_assignments') or [])} "
            f"extra={len(report.get('extra_block_ids') or [])} "
            f"evidence_mismatch={len(report.get('evidence_mismatches') or [])}"
        )
    raise FunctionalConservationError(
        f"功能需求守恒核对未闭合（{detail}），阻塞成文导出（强制人工）"
    )


def _check_failure_count(name: str, result: dict[str, Any]) -> int:
    for key in ("uncovered_sections", "uncovered_obligations", "items_without_evidence",
                "evidence_mismatches", "binding_mismatches", "groups", "blocking_losses"):
        value = result.get(key)
        if isinstance(value, list):
            return len(value)
    return 1


# ---------------------------------------------------------------------------
# §3.5 执行结果类别（ok / partial / failed）——manifest、readiness、结果包完成证据、
# 缓存行、下游闸门共用同一份语义：真实生产运行出现 stub 降级或 mixed 部分失败，
# 不得记 ok。显式 route="stub"（测试/烟测 opt-in）不算失败。
# ---------------------------------------------------------------------------

def execution_status(
    route_requested: Any,
    executed_route: Any,
    *,
    requested_label: str = "",
) -> str:
    """从请求/执行路由标签推导执行结果类别。

    ``requested_label`` 是 ``_resolve_route_label`` 的缓存键标签（injected / llm:model /
    stub）——非 stub 即"LLM 能力被真实尝试过"。执行侧全部退化为 stub → failed；部分
    条款 stub（mixed）→ partial；显式 stub 请求且无 LLM 尝试 → ok（诚实 opt-in）。
    """
    executed = str(executed_route or "stub")
    if executed == "mixed":
        return "partial"
    attempted = bool(requested_label) and requested_label != "stub"
    if executed == "stub" and attempted:
        return "failed"
    return "ok"


def _payload_execution_status(payload: dict[str, Any]) -> str:
    """产物/缓存行的执行结果类别：优先读持久化字段；旧缓存行按路由字段推导。"""
    stored = str(payload.get("execution_status") or "").strip()
    if stored in {"ok", "partial", "failed"}:
        return stored
    requested = str(payload.get("route_requested") or "stub")
    executed = str(payload.get("route") or "stub")
    if executed == "mixed":
        return "partial"
    if executed == "stub" and requested not in ("", "stub", None):
        return "failed"
    return "ok"


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
    negs = select_negative_exemplars(bank, module, text, k=functional_extract_negative_k())
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
    # §3.1：盖确定性证据锚（义务句 → block/引句/句序），LLM 不得填写。
    assign_stable_uids(items, sections)
    assign_evidence_anchors(items, sections)
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
    assign_evidence_anchors(items, sections)
    return items, final_route


def current_producer_lineage() -> dict[str, str]:
    """直抽产物的代码 lineage（发布侧记录与 currency 校验侧比较共用单源）。

    只含代码版本常量——execution_status 是运行态不是 lineage，进了比较会让
    ok/partial 之间的合法重跑被误判为陈旧。
    """
    return {
        "producer": FUNCTIONAL_EXTRACT_VERSION,
        "prompt_version": FUNCTIONAL_EXTRACT_PROMPT_VERSION,
        "guards_version": FUNCTIONAL_EXTRACT_GUARDS_VERSION,
        # 三轮复审 P1-2：守恒模型版本进 lineage——generation 的 currency 校验随
        # 守恒载荷语义演进同步失效（与缓存指纹同源）。
        "conservation_model": FUNCTIONAL_CONSERVATION_MODEL_VERSION,
    }


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
    # §3.5：执行不完整（stub 降级 / mixed 部分失败）同样响亮阻断下游——缓存行携带的
    # 失败语义在这里保持为失败（_payload_execution_status 不用当前请求路由重算）。
    status = _payload_execution_status(payload)
    if status != "ok":
        raise FunctionalExtractionIncompleteError(
            f"功能直抽执行不完整（execution_status={status}，"
            f"route_requested={payload.get('route_requested')}, route={payload.get('route')}），"
            "阻塞需求分析/澄清/成文下游；请修复 LLM 路由后重跑直抽"
            "（显式 route=stub 仅限测试/烟测 opt-in）"
        )
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
    不改 extract_units / atomize（硬边界：直抽替换下游两阶段，旧路径可显式回滚）。

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
    # §3.5：执行结果类别随产物持久化（缓存行同样携带——重放不洗白失败语义）。
    resolved_status = execution_status(
        route, executed_route, requested_label=route_label,
    )

    payload = {
        "schema_version": 1,
        "producer": FUNCTIONAL_EXTRACT_VERSION,
        "prompt_version": FUNCTIONAL_EXTRACT_PROMPT_VERSION,
        "guards_version": FUNCTIONAL_EXTRACT_GUARDS_VERSION,
        "conservation_model": FUNCTIONAL_CONSERVATION_MODEL_VERSION,
        "provenance": provenance("functional_extract", FUNCTIONAL_EXTRACT_VERSION),
        "route_requested": route or "stub",
        "route": executed_route,
        "execution_status": resolved_status,
        # §3.5 stub 草稿水印：占位条目永不形成可发布成功产物（claim 不绑定、
        # full closure 显式缺口、结果包完成证据拒绝）。
        "draft": executed_route == "stub",
        "context_pack_strategy": resolved_strategy,
        "clause_count": len(sections),
        "functional_requirements": len(items),
        "fingerprint": fingerprint,
        "conservation": conservation,
        "items": items,
    }
    # §3.5 缓存纪律：ok/partial 照常缓存（缓存行携带 execution_status，重放保留失败语义
    # ——mixed 重放仍是 partial）；**failed 不落缓存**——全退化多为瞬时故障（网络/超时），
    # 钉进缓存会让下次健康重跑永远重放失败；重跑就该真实再试。
    if resolved_status != "failed":
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
        # §3.5：结果摘要与产物/manifest 同一失败语义（ok/partial/failed）+ 草稿水印。
        "execution_status": _payload_execution_status(payload),
        "draft": bool(payload.get("draft")),
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
                # 回滚演练实证（2026-08-16）：真实 parse 产物的 chunks.jsonl 用
                # source_block_ids 字段——只认 block_ids 会让守恒锚定全空（义务
                # 覆盖/evidence 双 blocking 的假失败）。两字段都认（真实优先）。
                "block_ids": [str(b) for b in (
                    row.get("block_ids")
                    if isinstance(row.get("block_ids"), list) and row.get("block_ids")
                    else row.get("source_block_ids") or [])],
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
