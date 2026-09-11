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
SEMANTIC_SECTION_LOADER_VERSION = "semantic-section-loader-v2"
FUNCTIONAL_EXTRACT_PROMPT_VERSION = "functional-extract-prompt-v5"  # v5（2026-09-06）：明确表格参数行的字段名/值/单位/适用条件进入所属需求 data_constraints；表头、示例与上下文数字只有在条款定义为约束时才进入。v4 及以前见 CLAUDE.md。
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
# v6 → v7：证据诊断覆盖完整叙述字段，并在同条款合并后重新计算。
FUNCTIONAL_EXTRACT_GUARDS_VERSION = "functional-extract-guards-v7"
# §3.1 新守恒模型版本戳（进 conservation 报告与抽取指纹；模型演进时 bump）。
# M1（2026-08-16 修复方案 §3.4）：obligation 覆盖从全局叙述并集改为声明局部绑定
# （eligible-only 边；source_quote 只作锚）——产物语义变化，v1 → v2。
# 三轮复审 P1-2：同上——conservation 载荷语义变化（cross_script_review 携带文本身份），
# bump v2 → v3。
# WS-A（2026-08-27）：基线按单元类型分轨——a_track/context 表格单元出 narrative
# preservation，改记 delegated_to_cell_conservation；义务单元只从散文与
# b_track/mixed 表格取。v3 → v4。
# R1（同日返工）：委托粒度从单元 source_text 子串替换改为块粒度——某表格块上
# 全部 table_row/table_cell 均为 a_track/context 才剔除该块完整 block.text
# （行渲染文本对不上条款扁平 text 时不再静默失败）；部分委托整块保留。
# v4 → v5（2026-08-27 审查修复）：同文本多表格块按委托块数剔除出现位置——
# replace-all 会把字节级相同的非委托块一并剥出基线（无 cell 守恒兜底的静默丢账）。
# v7 → v8（2026-09-07，用户裁定：豁免逐字重复）：绑定检查 reason 2
# （narrative_covers_other_clauses_not_declared）——被覆盖义务句逐字出现在声明条款
# 基线文本内时，条款间共享文本使「覆盖他款」与「覆盖本款」不可区分，判疑似检查
# 误报豁免（审计列表 covered_clause_text_dup_exemptions，不静默、不影响 ok）；
# 任一被覆盖句不在声明条款内 → 照旧 blocking（真借位）。豁免口径与
# tools/binding_attribution.py 的 covered_clause_text_in_home 信号（b 类）同源。
# v8 → v9：重复文本归一保留数值小数点、正负号、运算符和词界，避免数值语义碰撞。
FUNCTIONAL_CONSERVATION_MODEL_VERSION = "functional-conservation-obligation-evidence-v9"
# v6 → v7（2026-08-31，绑定检查 reason 1 本地锚）：声明条款含义务单元却建不成
# lexical/cross_script/source_quote 边时，若引句（剥表格标记后）逐字落在该声明条款
# 基线文本内，不再判「占位声明」——SBD 清单/表格行无模态动词、永远成不了义务单元，
# 诚实抽取会被 reason 1 误伤并短路 reason 2。义务覆盖（检查 2）分母与判定不动；
# 放行后落入 reason 2（叙述覆盖未声明条款）。空引句不算锚定。
# v5 → v6（2026-08-30，门禁复盘）：义务基线剔除 lead-in/悬空碎片单元（"shall include:"、
# "will be issued and"、主语缺失的 "must be authenticated" 类——SBD 实测两侧各 21 条
# 假义务污染 obligation_coverage 信号）。判据见 _is_fragment_obligation_unit；剔除量
# 在 conservation 报告 fragment_units_excluded 审计，不静默。带主语完整句一律保留。
# §17 unit 级路由接线（2026-08-17）：clause_family 策略下表格主导条款路由出 B 轨输入
# 与守恒基线（表格内容归 A 轨/上下文，phase2 探针实证其混入 B 轨是守恒失败根因之一）。
# 接线版本只进 clause_family 缓存指纹维度（legacy 指纹逐字节不变）；路由判据演进时 bump。
FUNCTIONAL_UNIT_ROUTING_VERSION = "functional-unit-routing-v8"  # v8（2026-08-31，heading-only 条款出抽取池）：只有标题没有实质正文的条款（全部块为 heading/heading 回显、义务单元数 0、无表格块）确定性路由出 B 轨输入与守恒基线——SBD result3 实证 TGS 章 24 个 heading-only 条款在 LLM 失败时退化 stub（"实现{heading}，并满足来源条款。"），成功时也只能回显标题（零义务内容，无可抽取）。判据三条全满足才路由出（宁漏勿错：非 heading 块有任何实质文本即保留，含 v6 碎片过滤会剔掉义务的碎片正文）；meta 新增 heading_only_sections_routed_out/heading_only_section_ids，块入 routed_out_block_ids/review_units 四桶合并。v7（2026-08-30，路由连坐窄门修）：tender 聚合路由出之前，条款内 confirmed 的被吞并 heading（document_outline 报告，只读）先切开再分别路由——程序性残骸照旧路由出，被连坐的技术内容（SBD 实证 2.3 STATEMENT OF REQUIREMENTS 整章）获得独立判定。纯切分零块位移（不做 toc 剔除/demoted 并入——那是 outline authority flag 的语义）；无 confirmed 吞并时行为与 v6 一致；routed_out_block_ids 补齐 tender 两桶（兑现 docstring「全部写入 meta」承诺）。v6（2026-08-27，WS-B）：节级 tender 判定改为义务主体+跨度聚合。R2 返工：标题词表先验（own title 程序性且非产品主语）；跨度改为非产品主语即可（不再要求无模态）；technical 否决改为 own title/path（块内吞进的下一章 technical heading 不否决程序性残骸）。v5（2026-08-27，P3）：逐标题路由分支补 technical 反向否决 + P2 路由键并入 tender_region_filter 版本。v4：句子形程序性 heading 窄锚点 + v3 跨度继承/前置样板编号剥离
FUNCTIONAL_REQUIREMENTS_FILENAME = "functional_requirements.json"
FUNCTIONAL_EXTRACT_CACHE = "functional_extract_cache.jsonl"
# 待核成文（partial export，2026-09-01 用户拍板的政策反转）：守恒未闭合/直抽
# partial（mixed）时分析·成文·澄清照跑并如实标 partial，失败面行级「待核」标记
# 算法身份。进 requirements-analysis / template-write 的 stage producer 与阶段
# 指纹（含 RATOMIZER_PARTIAL_EXPORT 有效值）——不进 functional-extract 指纹，
# 不 bump 守恒模型（判定语义零改动）。开关 RATOMIZER_PARTIAL_EXPORT=0 回旧行为。
# v2（2026-09-01b，方案 grok 审核第 3 条补全）：mixed 载荷的 stub 占位条目加
# 独立失败类 extract_degraded（标记侧确定性形状比对，抽取侧/缓存零改动）——
# 分析行与成文说明列新增一类标记，旧产物复用时无该类（算法身份随版本失效）。
# v3（2026-09-01c，hotfix）：①寻址修复——分析 attach/unclosed_basis 改 governed
# 双路径读（package_v1 桌面跑此前漏标记出假干净表）；②draft+未闭合一律拦；
# ③extract_degraded 比对 _stub_item（coerce 后）字段；④红字+「守恒待核」清单
# sheet + conservation_pending_gaps。不进 functional-extract 指纹、不 bump 守恒
# 模型——v3 戳使 package_v1 上「ok 但零标记」的旧分析/成文代失效重跑（零 LLM）。
CONSERVATION_PARTIAL_EXPORT_VERSION = "conservation-partial-export-v3"

# P0-8：负例 few-shot 注入数量上限（可配）。§3.6：改经 config 单源读取（运行时求值，
# 进程内改 env 即生效——旧 import 时常量在同进程 shadow 场景下不刷新）。
def functional_extract_negative_k() -> int:
    from config import get_env_int
    return max(0, get_env_int("RATOMIZER_FUNCTIONAL_EXTRACT_NEGATIVE_K"))


# 兼容别名：desktop_tasks 阶段指纹等既有消费点引用的模块常量（真实读取走上面的函数）。
FUNCTIONAL_EXTRACT_NEGATIVE_K = functional_extract_negative_k()

LOGGER = logging.getLogger("requirement_atomizer")

# 入口开关（config.ENV_REGISTRY 登记）：默认 1=功能需求直抽路径；显式 0
# 仅用于兼容旧 A 轨/迁移回放。本模块不应因普通运行配置而退回碎原子链。
ENTRY_SWITCH_ENV = "RATOMIZER_FUNCTIONAL_EXTRACT"

# --- V3 WS-A A2 上下文包策略 ---
# legacy：_build_user_prompt 遗留 4000 字符切片（显式回滚 / 直抽关闭时的默认）。
# clause_family：按条款自然边界组装上下文包——目标条款整文（绝不截断）+ 同族相邻条款
# （复用 extract_units.clause_key 两级族键）+ doc_map 热区摘要（A1 有地图时）；包大小上限
# 只约束拼包（邻居可舍弃），单条款自身超限仍整文进包（条款是自然原子，宁超勿截）。
# 直抽默认开启后：未显式指定策略时生效 clause_family（单元路由只在此策略下接线）。
# 显式 RATOMIZER_CONTEXT_PACK_STRATEGY=legacy 仍可用，但是已证伪的文档级大包组合。
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
    "对每个条款，默认只产出一条完整功能需求：保留条款的一句话/一段话作为上下文；"
    "同一目标下的多个行为归入 behaviors 列表，不要按 shall、分号或动作拆成伪原子。"
    "只有条款明确包含不同责任主体、生命周期或互斥对象时才允许拆条；表格行机械事实"
    "（单个参数值/单条 OBIS 取值）归并入 data_constraints。"
    "归并入所属需求的 data_constraints。\n"
    "硬约束：①只能引用输入条款中已存在的原文，禁止臆造 OBIS/hex/class_id/标准号/数值；"
    "②只填叙述字段（objective/behaviors/preconditions/data_constraints/variants/exceptions/"
    "related_dlms_objects/description）；③不得填写 id/模块/归属/编码等结构字段（由下游确定性派生）；"
    "④每条产出必须回指来源条款的 section 与 block_ids（取自输入，原样回填）。"
    "⑤叙述字段必须使用与来源条款相同的语言（英文条款→英文叙述，禁止翻译成中文）；"
    "source_quote 必须是条款原文的逐字摘录（禁止改写/翻译/截断）。"
    "⑥表格参数行处理：将同一功能目标下的字段名、值、单位、档位和适用条件逐字归入"
    "所属需求的 data_constraints；表头、示例值或仅用于定位的上下文数字，只有条款明确"
    "把它们定义为约束时才写入，不能为了凑数复制整张表。"
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
    limit_sections: int | None = None,
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
    # A caller that supplies the first N clauses explicitly must not share a
    # cache entry with a full-document run over the same short list.  The
    # execution scope is part of the product identity, even though the clause
    # content is already represented above.
    if limit_sections is not None:
        canonical["limit_sections"] = int(limit_sections)
    # Phase 2b：大纲权威重切改变条款集（clauses 已承载），此处钉住接线身份——
    # flag 开时键存在（legacy/clause_family 两键空间都进），flag 关时键缺席
    # （指纹逐字节不变）。重切是策略无关的装配层行为，不挂在策略门控的
    # unit_routing_key 下。
    from document_outline import outline_authority_lineage

    canonical.update(outline_authority_lineage())
    if context_strategy and context_strategy != "legacy":
        canonical["context_strategy"] = str(context_strategy)
        canonical["doc_map_key"] = str(doc_map_key or "")
        # §17 unit 路由维度：接线/规划器/路由器任一版本演进 → clause_family 键空间更换
        # （legacy 不进键，指纹逐字节不变）。路由结果本身已由 clauses 列表承载（被路由
        # 出的条款不进 sections），这里钉住的是"路由判据的版本身份"。
        canonical["unit_routing_key"] = _unit_routing_key()
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def routing_lineage_versions() -> dict[str, str]:
    """路由判据血统版本（stage producer 与抽取缓存键同源，P1/P2 2026-08-27）。

    路由直接决定**哪些条款进产物**——判据版本必须同时进两级指纹：
    ``extraction_fingerprint`` 的 unit_routing_key（JSONL 缓存层）与
    ``desktop_tasks.stage_producer("functional-extract")``（chain 阶段复用层），
    任一缺席都会让旧路由下的产物在新判据代码下被静默复用。大纲报告版本也纳入
    血统，因为大纲裁决会改变路由可见的条款边界。
    """
    from extraction_units import EXTRACTION_UNIT_PLANNER_VERSION
    from document_outline import DOCUMENT_OUTLINE_VERSION
    from tender_regions import TENDER_REGION_FILTER_VERSION
    from unit_router import UNIT_ROUTER_VERSION

    return {
        "functional_unit_routing": FUNCTIONAL_UNIT_ROUTING_VERSION,
        "extraction_unit_planner": EXTRACTION_UNIT_PLANNER_VERSION,
        "unit_router": UNIT_ROUTER_VERSION,
        # E1：路由前的大纲裁决会改变条款边界与可见单元。即使大纲 authority
        # 开关关闭，当前路由仍会读取其旁证；版本必须进入同一血统，避免裁决器
        # 演进后静默复用旧的路由/抽取缓存。
        "document_outline": DOCUMENT_OUTLINE_VERSION,
        # P2：路由判定大量消费 tender_regions 词表（逐标题/跨度/句子锚点）——
        # 词表版本不进键则改词表只有人工 bump FUNCTIONAL_UNIT_ROUTING_VERSION 才失效。
        "tender_region_filter": TENDER_REGION_FILTER_VERSION,
    }


def _unit_routing_key() -> str:
    """unit 路由判据的身份键（接线/规划器/路由器/招标区域词表四版本）。"""
    return "|".join(routing_lineage_versions().values())


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


def _local_source_quote(candidate: Any, section: dict[str, Any]) -> tuple[str, bool]:
    """Keep evidence quotes local to the section that owns the requirement.

    A model can return a plausible quote copied from a neighbouring clause. The
    quote is evidence, not prose: if it is not contained in the owning section
    after whitespace/case normalization, fall back to the deterministic section
    text and leave an audit flag for the reviewer.
    """
    quote = str(candidate or "").strip()
    source = str(section.get("text") or "").strip()
    if not source:
        source = _source_text(section)
    normalized_source = " ".join(source.casefold().split())
    normalized_quote = " ".join(quote.casefold().split())
    if normalized_quote and normalized_quote in normalized_source:
        return quote, False
    return source, bool(quote)


def _refresh_item_evidence_integrity(item: dict[str, Any], section: dict[str, Any]) -> None:
    """Diagnose the final narrative; evidence quotes never fill narrative gaps."""
    findings = _preservation_findings(section, item_narrative(item))
    item["evidence_integrity"] = {
        "ok": not any(f.get("severity") == "blocking" for f in findings),
        "findings": findings,
    }


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

    # 受保护编码硬拦：叙述字段合集 vs 来源条款原文（数字软标用原始合集）。
    # ``_as_str_list`` 接受模型偶尔返回的 scalar；因此先把每个叙述字段放回
    # provisional item，再做数字扫描，不能只覆盖 objective/behaviors，否则
    # scalar data_constraints/preconditions 等会从 item_narrative 中漏掉。
    narrative = item_narrative({
        "objective": objective,
        "description": str(raw.get("description") or "").strip(),
        "behaviors": behaviors,
        "preconditions": preconditions,
        "data_constraints": data_constraints,
        "variants": variants,
        "exceptions": exceptions,
        "related_dlms_objects": related,
    })
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

    objective = _clean_field(objective)
    if not objective:
        # Never restore a field made entirely of hallucinated protected codes.
        objective = f"实现{_derive_module(section)}相关功能。"
    behaviors = [cleaned for value in behaviors if (cleaned := _clean_field(value))]
    if not behaviors:
        behaviors = [objective]
    data_constraints = [cleaned for value in data_constraints if (cleaned := _clean_field(value))]
    variants = [cleaned for value in variants if (cleaned := _clean_field(value))]
    exceptions = [cleaned for value in exceptions if (cleaned := _clean_field(value))]
    preconditions = [cleaned for value in preconditions if (cleaned := _clean_field(value))]

    related_filtered = [
        value for value in related
        # 受保护编码归属也走硬拦：related_dlms_objects 里的编码必须来源有
        if not (extract_codes(value) - extract_codes(source_text))
    ]

    description = str(raw.get("description") or "").strip()
    if description:
        # S1-8：description 同属 LLM 叙述字段，幻觉编码一并清洗（与 objective/behaviors 同口径）
        # 清洗后为空时必须走确定性渲染；不能用原 description 回填，否则
        # 只含幻觉编码的描述会被悄悄恢复到最终需求正文。
        description = _clean_field(description).strip()
    if not description:
        description = _render_description(objective, behaviors, data_constraints)

    source_quote, quote_replaced = _local_source_quote(raw.get("source_quote"), section)
    item = {
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
        "source_quote": source_quote,
        "source_block_ids": block_ids,
        # 三级追溯审计
        "evidence": [
            {
                "section": section_label,
                "source_quote": source_quote,
                "source_block_ids": block_ids,
                "protected_tokens": sorted(extract_codes(source_text)),
            }
        ],
        # 护栏留痕
        "rejected_codes": sorted(rejected),
        "numeric_drift_flag": numeric_drift,
        "numeric_drift_values": numeric_drifted,
        "evidence_quote_replaced": quote_replaced,
        "merge_method": "functional_extract",
        "merge_confidence": 1.0,
        "source_kind": "functional_extract",
    }
    # Advisory per-item diagnostics use the same complete narrative as the
    # section-level gate, after guards have finished cleaning every field.
    _refresh_item_evidence_integrity(item, section)
    return item


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

def _stub_shape(section: dict[str, Any]) -> tuple[str, list[str]]:
    """stub 占位条目的确定性形状（objective, behaviors）——``_stub_item`` 与
    ``extract_degraded_marks`` 的比对同源，形状变了两处一起变。

    提取为独立函数是 extract_degraded 标记（2026-09-01b）的前提：标记侧不信任
    字段标记（缓存产物可能早于本版本），改用与构造侧逐字节的形状比对。
    """
    source_text = _source_text(section)
    heading = str(section.get("heading") or "未命名功能").strip() or "未命名功能"
    objective = f"实现{heading}，并满足来源条款。"
    behaviors = [source_text] if source_text.strip() else [heading]
    return objective, behaviors


def _stub_item(section: dict[str, Any], index: int) -> dict[str, Any]:
    # §3.1：回显全文（旧 [:200] 截断会让长条款的义务句在守恒核对中"失踪"——stub 是
    # 占位条目，逐字回显是它对条款集合最诚实的覆盖方式）。
    objective, behaviors = _stub_shape(section)
    return _coerce_item(
        {
            "objective": objective,
            "behaviors": behaviors,
            "description": _render_description(objective, behaviors, []),
            "source_quote": str(section.get("text") or _source_text(section)),
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
    from llm_client import apply_min_tokens, chat_json
    # 用途级 max_tokens floor（2026-08-30 接线）：B 轨直抽此前从未接
    # apply_min_tokens（A 轨 ai_extract/claim_artifacts 都接了），一直用全局默认
    # 4096 裸奔——推理模型思考吃光预算后"烧完-重来"重复付费（SBD 实证 62/241 次）。
    # 单一权威在 llm_client.PURPOSE_MIN_TOKENS，此处不另写数字。
    config = apply_min_tokens(config, "extract")
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
        # 截断升级 2 轮（2026-08-18 10% 诊断）：deepseek-v4-flash 属推理型，小 max_tokens
        # 下 finish=length 且内容为空（推理耗尽预算）——1 轮升到 8192 仍空，2 轮给足预算。
        return chat_json(config, system, user, max_truncation_escalations=2)

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
    "只对目标条款默认产出一条完整功能需求：保留目标条款的一句话/一段话作为上下文；"
    "同一目标下的多个行为归入 behaviors 列表，不要按 shall、分号或动作拆成伪原子。"
    "只有不同责任主体、生命周期或互斥对象才允许拆条；表格行机械事实归并入 data_constraints。\n"
    "硬约束：①只能引用目标条款中已存在的原文，禁止臆造 OBIS/hex/class_id/标准号/数值；"
    "②只填叙述字段（objective/behaviors/preconditions/data_constraints/variants/exceptions/"
    "related_dlms_objects/description）；③不得填写 id/模块/归属/编码等结构字段；"
    "④每条产出必须回指目标条款的 source_block_ids（取自输入，原样回填）。\n"
    "⑤叙述字段必须使用与目标条款相同的语言（英文条款→英文叙述，禁止翻译成中文）；"
    "source_quote 必须是条款原文的逐字摘录（禁止改写/翻译/截断）。\n"
    "⑥保真落数：目标条款里的所有数值、单位、档位与引用号（Table N/图号/条款号/标准号）"
    "必须原样进入该条需求的相关叙述字段（objective/behaviors/data_constraints 等）——"
    "意译措辞可以，改写或漏掉编号不可以；研发拿不到编号等于没写。\n"
    "⑦表格参数行处理：同一功能目标下的字段名、值、单位、档位和适用条件逐字进入"
    "该需求的 data_constraints；表头、示例值或仅作上下文的数字不自动复制，除非目标条款"
    "明确将其定义为约束。\n"
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
    """上下文包组装策略。

    显式传入或环境变量命中合法值时按该值。
    未指定时：功能直抽开启 → ``clause_family``（按条款切 + 单元路由可接线）；
    直抽关闭 → ``legacy``（旧原子化回滚路径保持文档级切片）。
    未知值回退 ``legacy``，避免误启新行为。
    """
    if value is not None:
        token = str(value).strip().lower()
        return token if token in CONTEXT_PACK_STRATEGIES else "legacy"
    if CONTEXT_PACK_STRATEGY_ENV in os.environ:
        token = str(os.environ.get(CONTEXT_PACK_STRATEGY_ENV) or "").strip().lower()
        return token if token in CONTEXT_PACK_STRATEGIES else "legacy"
    return "clause_family" if functional_extract_enabled() else "legacy"


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


def _semantic_pre_review_summary_for(section: dict[str, Any], pre_review: dict[str, Any] | None) -> str:
    """Expose compact, source-linked context hypotheses to extraction prompts."""
    if not isinstance(pre_review, dict):
        return ""
    ids = {str(x) for x in (section.get("source_block_ids") or section.get("block_ids") or [])}
    rows = [row for row in (pre_review.get("elements") or [])
            if isinstance(row, dict) and (not ids or str(row.get("element_id")) in ids)]
    if not rows:
        return ""
    relations = [str(row.get("relation_to_previous") or "independent") for row in rows]
    uncertain = sum(str(row.get("uncertainty") or "low") != "low" for row in rows)
    if set(relations) <= {"independent"} and not uncertain:
        return ""
    return f"语义预审关系（仅作上下文提示，原文优先）：{', '.join(relations)}；不确定项 {uncertain}"


def build_context_packages(
    sections: Sequence[dict[str, Any]],
    *,
    doc_map: dict[str, Any] | None = None,
    semantic_pre_review: dict[str, Any] | None = None,
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
            "doc_map_summary": "\n".join(filter(None, [
                _doc_map_summary_for(section, doc_map),
                _semantic_pre_review_summary_for(section, semantic_pre_review),
            ])),
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


def _parse_llm_items(payload: Any, sections: Sequence[dict[str, Any]], *, coalesce_per_clause: bool = False) -> list[dict[str, Any]] | None:
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
    coerced_sections: list[dict[str, Any]] = []
    for idx, (raw, section) in enumerate(zip(items, used_sections)):
        if section is None:
            # LLM 多产了无法挂回条款的例子——丢弃（守恒纪律：无来源即无条目），记审计
            LOGGER.warning("functional_extract 丢弃无法挂回条款的 LLM 产出 #%d", idx)
            continue
        coerced.append(_coerce_item(raw, section, idx + 1))
        coerced_sections.append(section)
    if not coerced:
        return None
    if not coalesce_per_clause:
        return coerced
    # Product granularity contract: one natural clause is one requirement by
    # default. Models may return several actions for a clause, but those
    # actions belong in behaviors/constraints instead of becoming token-heavy
    # pseudo-atoms. Explicit A-track splitting remains in atomize.py.
    merged: list[dict[str, Any]] = []
    groups: dict[int, dict[str, Any]] = {}
    for item, section in zip(coerced, coerced_sections):
        key = id(section)
        base = groups.get(key)
        if base is None:
            base = dict(item)
            groups[key] = base
            merged.append(base)
            continue
        for field in ("behaviors", "preconditions", "data_constraints", "variants",
                      "exceptions", "related_dlms_objects"):
            values = list(base.get(field) or [])
            for value in item.get(field) or []:
                if value not in values:
                    values.append(value)
            base[field] = values
        for field in ("source_quote",):
            quotes = [str(base.get(field) or "").strip(), str(item.get(field) or "").strip()]
            base[field] = "\n".join(dict.fromkeys(q for q in quotes if q))
        base["evidence"] = list(base.get("evidence") or []) + list(item.get("evidence") or [])
        for field in ("rejected_codes", "numeric_drift_values"):
            base[field] = sorted(set(base.get(field) or []) | set(item.get(field) or []))
        for field in ("evidence_quote_replaced", "numeric_drift_flag"):
            base[field] = bool(base.get(field) or item.get(field))
        base["description"] = _render_description(
            str(base.get("objective") or ""),
            list(base.get("behaviors") or []),
            list(base.get("data_constraints") or []),
        )
        _refresh_item_evidence_integrity(base, section)
    return merged


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
# 表格标题前缀（chunk 渲染产物，形如 "[TBL-000008] Table 7 (continuation)"）是管线
# 定位符而非原文内容：LLM 引句常原样带回该前缀导致引文零命中（evidence 假失败）；
# 其中的 6 位数字也不得进入保真基线（preservation 假 blocking）。守恒检查侧统一剥离。
_TABLE_MARKER_RE = re.compile(r"\[TBL-\d{6}\][^\n]*")


def _strip_table_markers(text: str) -> str:
    return _TABLE_MARKER_RE.sub("", text)




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


def _quote_verbatim_in_home_clauses(
    item: dict[str, Any],
    baseline_sections: Sequence[dict[str, Any]],
    home_indices: Sequence[int],
) -> bool:
    """引句（剥表格标记后）逐字落在任一给定声明条款的基线文本内。

    conservation v7 仅把这条通道用作绑定检查 reason 1 的本地锚豁免——义务覆盖
    （检查 2）不认。空引句不算锚定。
    """
    quote = _strip_table_markers(str(item.get("source_quote") or ""))
    quote_sq = _squashed(quote)
    if not quote_sq:
        return False
    for index in home_indices:
        if index < 0 or index >= len(baseline_sections):
            continue
        text_sq = _squashed(str(baseline_sections[index].get("text") or ""))
        if quote_sq in text_sq:
            return True
    return False


def _unit_sentence_duplicated_in_home_clauses(
    sentence: str,
    baseline_sections: Sequence[dict[str, Any]],
    home_indices: Sequence[int],
) -> bool:
    """义务句逐字落在声明条款内，忽略大小写、空白和普通句读标点。

    v9 保留词界、数值小数点/符号与运算符，避免将 1.5 V 与 15 V 等同。

    conservation v8（2026-09-07 用户裁定：豁免逐字重复）用于绑定检查 reason 2
    （narrative_covers_other_clauses_not_declared）的疑似误报豁免：条款间共享
    文本使「覆盖他款」与「覆盖本款」不可区分。口径源自 tools/binding_attribution.py
    的 covered_other_text_in_home 信号（b 类），边界略宽：句末/句中标点不敏感
    （重复句常作为更长句的片段出现在声明条款内）。
    """
    sentence_sq = _dup_content_squash(sentence)
    if not sentence_sq:
        return False
    for index in home_indices:
        if index < 0 or index >= len(baseline_sections):
            continue
        text_sq = _dup_content_squash(
            str(baseline_sections[index].get("text") or ""))
        if f" {sentence_sq} " in f" {text_sq} ":
            return True
    return False


def _dup_content_squash(text: str) -> str:
    """重复豁免专用：忽略普通句读，保留数字、符号与词边界。"""
    tokens = re.findall(
        r"<=|>=|!=|==|<>|≤|≥|≈|"
        r"[+\-−]?\s*\d+(?:[.,]\d+)*(?:[eE][+\-−]?\d+)?|"
        r"[\u4e00-\u9fff]|[^\W\d_\u4e00-\u9fff]+|[^\s]",
        str(text or "").lower(),
    )
    return " ".join(
        "".join(token.split()) for token in tokens
        if token not in ".,;:!?。，；：！？"
    )


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


# --- 义务基线碎片判据（conservation v6，2026-08-30 门禁复盘）--------------------
# SBD 实测两侧各 21 条假义务（"shall include:" / "will be issued and" / 助动词空壳
# "must be authenticated"）——它们是表格/列表 lead-in 或主语缺失的被动残片，不是
# 独立可测义务。注意两个陷阱：①义务单元由 _OBLIGATION_UNIT_SPLIT_RE 在模态词处
# 切分，**天生以模态词开头**（主语不在单元内），不能用"模态开头"判碎片；②复合谓语
# 的模态切分会留下连接尾（"shall log events and [shall send alarms]"），连接尾本身
# 不是碎片证据。统一收敛到内容词计数：<2 即碎片（冒号尾 lead-in 的内容词也必然 <2，
# 保留显式判断只为可读）。_content_tokens 含中文字符，CJK 单元天然不误伤。
def _is_fragment_obligation_unit(unit: str) -> bool:
    """lead-in/空壳碎片判据（确定性）：内容词 <2（含显式冒号尾 lead-in）。"""
    text = str(unit or "").strip()
    if not text:
        return True
    if text.endswith(":"):
        return True
    return len(_content_tokens(text)) < 2


def _obligation_index_with_fragment_audit(
    section: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    """``_obligation_index`` 的审计形态：额外返回被碎片判据剔除的单元数。"""
    rows: list[dict[str, Any]] = []
    fragments = 0
    for sentence_index, sentence in enumerate(_section_sentences(section)):
        for unit in _obligation_units(sentence):
            if _is_fragment_obligation_unit(unit):
                fragments += 1
                continue
            rows.append({
                "sentence_index": sentence_index,
                "unit_index": len(rows),
                "sentence": unit,
            })
    return rows, fragments


def _obligation_index(section: dict[str, Any]) -> list[dict[str, Any]]:
    """条款的义务单元清单（模态动词支配的独立行为；判据与 drilldown 多行为信号同源）。

    ``unit_index`` 是条款内义务单元的顺序号（跨句连续），作守恒/判重的稳定键。
    conservation v6 起 lead-in/悬空碎片单元不入基线（单一权威：守恒检查/绑定
    检查/claim_ledger 共用本定义；审计计数走 ``_obligation_index_with_fragment_audit``）。
    """
    return _obligation_index_with_fragment_audit(section)[0]


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
    # 表格标记（[TBL-NNNNNN] …）是管线定位符：其数字不是文档内容，剥离后再建基线（guards-v6）
    source_text = _strip_table_markers(str(section.get("text") or ""))
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


# WS-A：表格单元中可委托给 cell 守恒的路由（数字/结构事实归 A 轨处置权威）。
_CONSERVATION_DELEGATE_ROUTES = frozenset({"a_track", "context"})
_CONSERVATION_TABLE_UNIT_KINDS = frozenset({"table_row", "table_cell"})


def _table_blocks_missing_dispositions(
    out_dir: Path,
    table_block_ids: set[str],
) -> set[str]:
    """cell dispositions 缺席的表格块——退回全量入守恒基线（与 routing unavailable 同保守）。"""
    from io_utils import read_jsonl
    from result_package import governed_artifact_path

    path = governed_artifact_path(
        out_dir, "table_cell_dispositions.jsonl",
        category="pipeline", for_write=False,
    )
    if not path.is_file():
        return set(table_block_ids)
    covered: set[str] = set()
    for row in read_jsonl(path):
        bid = str(row.get("table_block_id") or "")
        if bid:
            covered.add(bid)
    return set(table_block_ids) - covered


def _conservation_blocks_by_id(
    out_path: Path,
    blocks: Sequence[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """守恒委托用块索引：优先调用方块流，缺席则读 pipeline blocks.jsonl。"""
    if blocks:
        return {
            str(block.get("block_id")): block
            for block in blocks
            if str(block.get("block_id") or "")
        }
    from io_utils import read_jsonl
    from result_package import governed_artifact_path

    path = governed_artifact_path(
        out_path, "blocks.jsonl", category="pipeline", for_write=False,
    )
    if not path.is_file():
        return {}
    return {
        str(block.get("block_id")): block
        for block in read_jsonl(path)
        if str(block.get("block_id") or "")
    }


def _conservation_baseline_sections(
    sections: Sequence[dict[str, Any]],
    *,
    out_dir: Path | str | None = None,
    blocks: Sequence[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按块粒度构建守恒基线条款（义务/preservation 用）与委托审计清单。

    某表格块上的全部 table_row/table_cell 均为 a_track/context 时，剔除该块
    完整 ``block.text``（条款文本的逐字组成部分）。字节级相同的多表格块按
    **委托块数**剔除出现位置——非委托块的同文本内容必须留在基线。部分委托 /
    dispositions 缺席 / 单元不可得：整块保留在基线（宁多记账）。无 out_dir
    退回条款全文。
    """
    if out_dir is None:
        return [dict(section) for section in sections], []
    out_path = Path(out_dir).expanduser().resolve()
    try:
        units, _replanned = _load_routing_units(out_path)
        route_by_unit, _recomputed = _routing_decisions_for(out_path, units)
    except Exception:  # noqa: BLE001 — 规划失败退回全量基线
        return [dict(section) for section in sections], []
    if not units:
        return [dict(section) for section in sections], []

    blocks_by_id = _conservation_blocks_by_id(out_path, blocks)
    if not blocks_by_id:
        return [dict(section) for section in sections], []

    table_block_ids = {
        bid for bid, block in blocks_by_id.items()
        if str(block.get("type") or "") == "table"
    }
    fallback_blocks = _table_blocks_missing_dispositions(out_path, table_block_ids)

    units_by_block: dict[str, dict[str, dict[str, Any]]] = {}
    for unit in units:
        kind = str(unit.get("unit_kind") or "")
        if kind not in _CONSERVATION_TABLE_UNIT_KINDS:
            continue
        uid = str(unit.get("unit_id") or "")
        if not uid:
            continue
        for block_id in (unit.get("source_block_ids") or []):
            units_by_block.setdefault(str(block_id), {})[uid] = unit

    delegated: list[dict[str, Any]] = []
    adjusted: list[dict[str, Any]] = []
    for section in sections:
        section_bids = [
            str(bid) for bid in (section.get("block_ids") or []) if str(bid)
        ]
        text = str(section.get("text") or "")
        removal_counts: dict[str, int] = {}
        for bid in section_bids:
            block = blocks_by_id.get(bid)
            if block is None or str(block.get("type") or "") != "table":
                continue
            if bid in fallback_blocks:
                continue
            table_units = list(units_by_block.get(bid, {}).values())
            if not table_units:
                continue
            details: list[dict[str, str]] = []
            fully_delegable = True
            for unit in sorted(
                table_units, key=lambda row: str(row.get("unit_id") or "")
            ):
                route = str(
                    route_by_unit.get(str(unit.get("unit_id") or ""), "") or "")
                if route not in _CONSERVATION_DELEGATE_ROUTES:
                    fully_delegable = False
                    break
                details.append({
                    "unit_id": str(unit.get("unit_id") or ""),
                    "unit_kind": str(unit.get("unit_kind") or ""),
                    "route": route,
                })
            if not fully_delegable:
                continue
            block_text = str(block.get("text") or "").strip()
            if block_text and block_text not in text:
                continue
            if block_text:
                removal_counts[block_text] = removal_counts.get(block_text, 0) + 1
            delegated.append({
                "block_id": bid,
                "block_ids": [bid],
                "units": details,
                "reason": "table_block_fully_delegated_to_cell_conservation",
            })
        for block_text, count in removal_counts.items():
            # count 感知剔除：同文本的另一个非委托表格块（或正文里的同文片段）
            # 的出现位置必须保留，否则其数字在无 cell 守恒兜底的情况下静默出账。
            text = text.replace(block_text, " ", count)
        copy = dict(section)
        copy["text"] = text
        adjusted.append(copy)
    return adjusted, delegated


def conservation_report(
    sections: Sequence[dict[str, Any]],
    items: Sequence[dict[str, Any]],
    *,
    blocks: Sequence[dict[str, Any]] | None = None,
    out_dir: Path | str | None = None,
) -> dict[str, Any]:
    """obligation/evidence 守恒报告（§3.1 多对多模型，五项分项检查）。

    取证复用 ``merged_consistency.match_source_quote_blocks``（与
    ``review_tools.coverage_check`` 同源匹配器）校验每条 item 的 source_quote 是否命中
    其声明的 source_block_ids。下钻条款递归守恒保留：``drilled_subatoms`` 的子原子
    block_ids 并集必须等于父条款 block_ids。

    报告同时保留旧字段镜像（missing/extra/duplicate_assignments/evidence_mismatches），
    但语义随模型升级：``duplicate_assignments`` 现在指"重复需求组涉及的块"（多消费合法，
    只有义务句+叙述双重命中才判重），不再是"被多条需求声明的块"。

    WS-A：``out_dir`` 在场时义务/preservation 基线按表格块分轨（整块 a_track/
    context 才剔除 block.text）；缺席则沿用条款全文（既有直调测试与 legacy
    路径签名兼容）。
    """
    from merged_consistency import match_source_quote_blocks

    baseline_sections, delegated = _conservation_baseline_sections(
        sections, out_dir=out_dir, blocks=blocks,
    )

    section_block_ids = [
        sorted({str(b) for b in (section.get("block_ids") or []) if str(b)})
        for section in sections
    ]
    clause_block_set = {b for blocks_ids in section_block_ids for b in blocks_ids}

    narratives = [item_narrative(item) for item in items]
    # M1：统一边生成——守恒检查与证据锚共用同一结果；持久化 anchors 只是下游展示数据，
    # 守恒永远现算（产物里被篡改/陈旧的锚不能伪造覆盖结论）。
    edges = _obligation_evidence_edges(items, baseline_sections)
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
    ignore_tokens = _known_section_tokens(baseline_sections)
    uncovered_obligations: list[dict[str, Any]] = []
    cross_script_review: list[dict[str, Any]] = []
    sentence_cover_items: dict[tuple[str, int], list[int]] = {}
    fragment_units_excluded = 0
    for section, blocks_ids in zip(baseline_sections, section_block_ids):
        section_id = str(section.get("section_id") or "")
        obligation_rows, section_fragments = (
            _obligation_index_with_fragment_audit(section)
        )
        fragment_units_excluded += section_fragments
        for obligation in obligation_rows:
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
    quote_verbatim_local_anchors = 0
    covered_clause_text_dup_exemptions: list[dict[str, Any]] = []
    # 错绑检测（审查 2026-08-15 P1）：声明的 source_block_ids 与叙述实际覆盖的义务单元
    # 所属条款不一致——叙述互换/错误溯源会让条款覆盖假通过。跨语种（token 覆盖失效）
    # 与无义务单元的家条款无从判定，跳过（宁漏勿错，不误报 blocking）。
    clause_units: list[list[dict[str, Any]]] = [_obligation_index(s) for s in baseline_sections]
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
            # 表格标题前缀是渲染产物不是原文——剥离后再匹配（guards-v6）
            quote = _strip_table_markers(str(item.get("source_quote") or ""))
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
                _script_profile(str(baseline_sections[i].get("text") or "")),
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
                # v7：引句逐字锚定声明条款 = 本地锚，不判占位声明；落入 reason 2。
                if _quote_verbatim_in_home_clauses(
                    item, baseline_sections, home_with_units,
                ):
                    quote_verbatim_local_anchors += 1
                else:
                    binding_mismatches.append({
                        "functional_requirement_id": fre_id,
                        "reason": "declared_section_has_no_local_obligation_coverage",
                        "declared_block_ids": ids,
                        "declared_section_ids": [
                            str(baseline_sections[i].get("section_id") or "")
                            for i in home_with_units
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
                # conservation v8（2026-09-07 用户裁定：豁免逐字重复）：被覆盖义务句
                # 逐字出现在声明条款基线文本内 → 条款间共享文本使「覆盖他款」与
                # 「覆盖本款」不可区分，判疑似检查误报，豁免（审计列表非静默）；
                # 任一被覆盖句不在声明条款内 → 照旧 blocking（真借位）。
                duplicated_explained = all(
                    _unit_sentence_duplicated_in_home_clauses(
                        unit["sentence"], baseline_sections, home_with_units)
                    for i in covered_clause_indices
                    for unit in clause_units[i]
                    if _sentence_covered_by(
                        unit["sentence"], narrative, ignore_tokens=ignore_tokens)
                )
                if duplicated_explained:
                    covered_clause_text_dup_exemptions.append({
                        "functional_requirement_id": fre_id,
                        "reason": "covered_clause_text_duplicated_in_declared_clause",
                        "declared_block_ids": ids,
                        "covered_section_ids": [
                            str(baseline_sections[i].get("section_id") or "")
                            for i in sorted(covered_clause_indices)
                        ],
                    })
                else:
                    binding_mismatches.append({
                        "functional_requirement_id": fre_id,
                        "reason": "narrative_covers_other_clauses_not_declared",
                        "declared_block_ids": ids,
                        "declared_section_ids": [
                            str(baseline_sections[i].get("section_id") or "")
                            for i in home_with_units
                        ],
                        "narrative_covers_section_ids": [
                            str(baseline_sections[i].get("section_id") or "")
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
    for section_index, (section, blocks_ids) in enumerate(
        zip(baseline_sections, section_block_ids)
    ):
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
                # Keep physical clause identity beside the human-facing section id.
                # Section ids are not unique in real standards (for example, repeated
                # "Security" table sections), so downstream diagnostics must never
                # infer jurisdiction from the label alone.  These fields are additive
                # audit data; preservation severity and gate semantics are unchanged.
                "section_block_ids": list(blocks_ids),
                "section_path": [
                    str(part) for part in (section.get("section_path") or [])
                    if str(part).strip()
                ],
                "section_heading": str(section.get("heading") or "")[:120],
                "section_index": section_index,
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
            # conservation v6：lead-in/悬空碎片单元剔出基线的审计计数（不静默）
            "fragment_units_excluded": fragment_units_excluded,
        },
        "evidence_presence": {
            "ok": not no_evidence_items and not evidence_mismatches
            and not binding_mismatches,
            "items_without_evidence": no_evidence_items[:50],
            "evidence_mismatches": evidence_mismatches[:50],
            "binding_mismatches": binding_mismatches[:50],
            # conservation v7：reason 1 被引句逐字锚定豁免的条数（不静默）
            "quote_verbatim_local_anchors": quote_verbatim_local_anchors,
            # conservation v8（2026-09-07 用户裁定）：reason 2 逐字重复豁免的
            # 行级审计（fre_id + 覆盖条款），豁免不进 binding_mismatches、不影响 ok
            "covered_clause_text_dup_exemptions": covered_clause_text_dup_exemptions[:50],
        },
        "duplicates": {
            "ok": not duplicate_groups,
            "groups": duplicate_groups[:50],
        },
        "preservation": {
            "ok": not blocking_losses,
            "blocking_losses": blocking_losses[:50],
            "warning_losses": warning_losses[:50],
            "delegated_to_cell_conservation": delegated[:200],
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


def raise_if_unconserved(
    report: dict[str, Any], *, allow_unclosed: bool = False,
) -> dict[str, Any] | None:
    """成文导出闸门：守恒核对存在任一 blocking 失败类别即抛 FunctionalConservationError。

    兼容旧形报告（只有顶层 ok）——ok=False 一律阻塞；新形报告按分项类别给出计数。
    partial export（2026-09-01，用户拍板的政策反转）：``allow_unclosed=True`` 时
    不抛，返回待核摘要（``{ok, pending_fre_ids}``，FRE id 取自
    :func:`conservation_pending_marks` 的直接点名集合）——守恒判定本身不动，
    只是分析/成文层获准在未闭合基线上继续并如实标 partial。
    """
    if report.get("ok", True):
        return {"ok": True, "pending_fre_ids": []}
    if allow_unclosed:
        return {"ok": False, "pending_fre_ids": sorted(_pending_direct_fre_ids(report))}
    raise FunctionalConservationError(
        f"功能需求守恒核对未闭合（{conservation_failure_detail(report)}），"
        "阻塞成文导出（强制人工）"
    )


def conservation_failure_detail(report: dict[str, Any]) -> str:
    """守恒失败面 → 分项计数摘要（raise 文案与链层运行页信号同源单源）。

    2026-09-05（review P2）：GUI 日常链无分析/成文阶段时，守恒未闭合被 partial
    export 吸收、链层无任何信号——chain 尾聚合复用本函数生成人读摘要，与
    FunctionalConservationError 措辞一致。新旧形报告兼容口径与原 raise 分支相同。
    """
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    if checks:
        return "；".join(
            f"{name}={_check_failure_count(name, result)}"
            for name, result in sorted(checks.items())
            if not result.get("ok", True)
        )
    return (
        f"missing={len(report.get('missing_block_ids') or [])} "
        f"duplicate={len(report.get('duplicate_assignments') or [])} "
        f"extra={len(report.get('extra_block_ids') or [])} "
        f"evidence_mismatch={len(report.get('evidence_mismatches') or [])}"
    )


# --- 待核成文（partial export，2026-09-01）标记权威 ----------------------------
# 方案 docs/pending-export-plan-2026-08-31.md v2（grok 审核三条）。守恒判定/报告
# 零改动；这里只把失败面投影成「FRE id → 失败类」供成文行级标记与 UI 计数。
# 判据纪律：定位键 = 条款 block_ids 元组（禁 section_id 字符串定位，SBD 撞名病理）；
# uncovered/preservation finding 只带 section_id——按 id 候选 + 内容证据（义务句
# squash-包含 / 保留 token 在场）确定性还原到块集；无法唯一还原时对同 id 候选
# 取并集（宁多标不漏标）。duplicates 组自带 FRE id 清单，只标组内成员。
# 零 FRE 条款不造占位行（没有行可标）。版本：CONSERVATION_PARTIAL_EXPORT_VERSION。
_PENDING_CLASS_LABELS = {
    "binding": "绑定失配",
    "evidence": "证据失配",
    "uncovered": "义务未覆盖",
    "preservation": "保留丢失",
    "duplicate": "重复需求",
    # 2026-09-01b（方案 grok 审核第 3 条补全）：mixed 载荷中 stub 退化占位条的
    # 独立失败类——与守恒待核区分（数据降级，不是守恒缺口）。
    "extract_degraded": "抽取降级",
}


def pending_class_label(classes: Sequence[str]) -> str:
    """失败类 → 人读标签（分析说明列 / 成文说明列共用，单一措辞权威）。"""
    return "、".join(
        _PENDING_CLASS_LABELS.get(str(cls), str(cls)) for cls in classes
    )


def _pending_direct_fre_ids(report: dict[str, Any]) -> set[str]:
    """binding/evidence/duplicates 直接点名的 FRE id 集。"""
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    named: set[str] = set()
    evidence = checks.get("evidence_presence") if isinstance(checks.get("evidence_presence"), dict) else {}
    for row in (evidence.get("binding_mismatches") or []) + (
            evidence.get("evidence_mismatches") or []) + (
            evidence.get("items_without_evidence") or []):
        if isinstance(row, dict) and row.get("functional_requirement_id"):
            named.add(str(row["functional_requirement_id"]))
    duplicates = checks.get("duplicates") if isinstance(checks.get("duplicates"), dict) else {}
    for group in duplicates.get("groups") or []:
        if isinstance(group, dict):
            named.update(
                str(fre_id) for fre_id in (group.get("functional_requirement_ids") or [])
                if fre_id
            )
    return named


def _squash_contains(haystack: str, needle: str) -> bool:
    return bool(needle) and needle in haystack


def _clause_block_candidates(
    sections: Sequence[dict[str, Any]], section_id: str, *,
    sentence: str = "", token: str = "",
    block_ids: Sequence[Any] | None = None,
) -> list[tuple[str, ...]]:
    """finding → 候选条款块集（block_ids 元组）。id 撞名时按内容证据收窄。"""
    candidates = [
        tuple(str(b) for b in (s.get("block_ids") or []) if str(b))
        for s in sections if str(s.get("section_id") or "") == section_id
    ]
    # New conservation findings carry the physical block jurisdiction.  Prefer it
    # when it exactly identifies one of the same-id sections; old reports simply
    # omit the field and continue through the content-evidence fallback below.
    explicit = tuple(str(b) for b in (block_ids or ()) if str(b))
    if explicit:
        explicit_set = set(explicit)
        exact = [candidate for candidate in candidates
                 if set(candidate) == explicit_set]
        if exact:
            return [tuple(sorted(explicit_set))]
    if len(candidates) > 1:
        if sentence:
            needle = _squashed(sentence)
            narrowed = [
                blocks for blocks, s in zip(candidates, [
                    sec for sec in sections
                    if str(sec.get("section_id") or "") == section_id
                ])
                if _squash_contains(_squashed(str(s.get("text") or "")), needle)
            ]
            if narrowed:
                return narrowed
        if token:
            narrowed = [
                blocks for blocks, s in zip(candidates, [
                    sec for sec in sections
                    if str(sec.get("section_id") or "") == section_id
                ])
                if token.lower() in str(s.get("text") or "").lower()
            ]
            if narrowed:
                return narrowed
    return candidates


def extract_degraded_marks(
    payload: dict[str, Any],
    sections: Sequence[dict[str, Any]],
) -> dict[str, list[str]]:
    """mixed 载荷中 stub 退化占位条目 → ``{fre_id: ["extract_degraded"]}``。

    方案 pending-export-plan grok 审核第 3 条的行级补全：partial（mixed）运行中
    包级 stub 退化的条款**确实产出占位 FRE**（``_stub_item`` 每条款一条），这些
    行会无标注流进成文——本函数把它们确定性识别出来，标记侧挂独立失败类
    ``extract_degraded``（与守恒待核区分：这是抽取降级，不是守恒缺口）。

    判据（缓存安全，不在抽取侧打标）：
    - 仅 ``payload["route"] == "mixed"`` 启用（纯 llm 载荷没有 stub 条目；
      纯 stub 载荷 execution_status=failed 一律仍拦，到不了标记层）；
    - item 声明块与某条款块相交，且 ``(objective, behaviors)`` 与该条款
      ``_stub_item(section, 1)`` 的字段**逐字节相等**（v3 Task3：比落盘条目
      同一清洗链的产物，不比 coerce 前模板——防清洗链演进后标记漂移；
      只借字段，不用其重算的 id 对 payload）。
    LLM 真产出恰好逐字复刻占位模板的概率可忽略；即使发生，内容即占位文本，
    标记语义仍成立。
    """
    if str(payload.get("route") or "") != "mixed":
        return {}
    sections_by_block: dict[str, dict[str, Any]] = {}
    for section in sections:
        for block_id in (section.get("block_ids") or []):
            sections_by_block.setdefault(str(block_id), section)
    # stub 形状按块 memoize（2026-09-05 review P3）——原实现每 item×声明块重建一次
    # 完整 _stub_item（含 description 渲染 + coerce），大文档纯浪费；比对语义不变。
    stub_fields_by_block: dict[str, tuple[str, list[str]]] = {}
    marks: dict[str, list[str]] = {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        declared = {str(b) for b in (item.get("source_block_ids") or []) if str(b)}
        if not declared:
            continue
        item_objective = str(item.get("objective") or "")
        item_behaviors = [str(b) for b in (item.get("behaviors") or [])]
        for block_id in declared:
            section = sections_by_block.get(block_id)
            if section is None:
                continue
            stub_fields = stub_fields_by_block.get(block_id)
            if stub_fields is None:
                stub = _stub_item(section, 1)
                stub_fields = (str(stub.get("objective") or ""),
                               [str(b) for b in (stub.get("behaviors") or [])])
                stub_fields_by_block[block_id] = stub_fields
            if item_objective == stub_fields[0] and item_behaviors == stub_fields[1]:
                fre_id = str(item.get("functional_requirement_id") or "")
                if fre_id:
                    marks[fre_id] = ["extract_degraded"]
                break
    return marks


def conservation_pending_marks(
    report: dict[str, Any],
    items: Sequence[dict[str, Any]],
    sections: Sequence[dict[str, Any]],
) -> dict[str, list[str]]:
    """守恒失败面 → ``{functional_requirement_id: [失败类]}``（待核行级标记权威）。

    - binding / evidence / duplicate：直接点名（duplicates 只标组内成员）；
    - uncovered / preservation：finding 所在条款（块集定位）上**声明的** FRE 连带
      （``source_block_ids`` 与条款 ``block_ids`` 相交——与检查 5 叙述并集同口径）；
    - 报告闭合（ok=True）返回空——无失败即无待核。
    """
    if report.get("ok", True):
        return {}
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    evidence = checks.get("evidence_presence") if isinstance(
        checks.get("evidence_presence"), dict) else {}
    duplicates = checks.get("duplicates") if isinstance(
        checks.get("duplicates"), dict) else {}
    obligation = checks.get("obligation_coverage") if isinstance(
        checks.get("obligation_coverage"), dict) else {}
    preservation = checks.get("preservation") if isinstance(
        checks.get("preservation"), dict) else {}
    marks: dict[str, list[str]] = {}

    def _mark(fre_id: str, cls: str) -> None:
        if not fre_id:
            return
        classes = marks.setdefault(fre_id, [])
        if cls not in classes:
            classes.append(cls)

    for row in evidence.get("binding_mismatches") or []:
        if isinstance(row, dict):
            _mark(str(row.get("functional_requirement_id") or ""), "binding")
    for row in (evidence.get("evidence_mismatches") or []) + (
            evidence.get("items_without_evidence") or []):
        if isinstance(row, dict):
            _mark(str(row.get("functional_requirement_id") or ""), "evidence")
    for group in duplicates.get("groups") or []:
        if isinstance(group, dict):
            for fre_id in group.get("functional_requirement_ids") or []:
                _mark(str(fre_id), "duplicate")

    def _connect(rows: Sequence[dict[str, Any]], cls: str, *, key: str) -> None:
        block_union: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            evidence_value = str(row.get(key) or "")
            for blocks in _clause_block_candidates(
                sections, str(row.get("section_id") or ""),
                **({key: evidence_value} if evidence_value else {}),
                block_ids=row.get("section_block_ids"),
            ):
                block_union.update(blocks)
        if not block_union:
            return
        for item in items:
            declared = {str(b) for b in (item.get("source_block_ids") or [])}
            if declared & block_union:
                _mark(str(item.get("functional_requirement_id") or ""), cls)

    _connect(obligation.get("uncovered_obligations") or [], "uncovered", key="sentence")
    _connect(preservation.get("blocking_losses") or [], "preservation", key="token")
    return {fre_id: classes for fre_id, classes in marks.items() if classes}


def load_conservation_baseline(out_dir: Path | str) -> list[dict[str, Any]]:
    """守恒基线条款（路由保留集）——标记侧与 conservation_report 同口径重建。

    供 partial export 标记与 UI 计数复用；不写任何产物。
    """
    root = Path(out_dir).expanduser().resolve()
    sections = load_clauses(root)
    if not sections:
        return []
    from io_utils import read_jsonl
    from result_package import governed_artifact_path

    blocks_path = governed_artifact_path(root, "blocks.jsonl", category="pipeline", for_write=False)
    blocks = read_jsonl(blocks_path) if blocks_path.is_file() else []
    try:
        kept, _meta = apply_unit_routing(sections, blocks=blocks, out_dir=root)
        return kept
    except Exception:  # noqa: BLE001 — 路由不可得（旧包/产物缺席）退全量条款，宁多标不漏标
        return sections


# 「守恒待核」清单 sheet 的缺口类别 → 人读标签（与 _PENDING_CLASS_LABELS 同措辞风格）
_PENDING_GAP_LABELS = {
    "clause_gap": "条款缺口",
    "uncovered": "义务未覆盖",
}


def pending_gap_label(category: str) -> str:
    """缺口类别机键 → 人读标签；未知键原样返回（不猜）。"""
    key = str(category or "")
    return _PENDING_GAP_LABELS.get(key, key)


def conservation_pending_gaps(
    report: dict[str, Any],
    items: Sequence[dict[str, Any]],
    sections: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """守恒失败面里**零 FRE 可挂**的缺口行（v3 Task4，只进「守恒待核」清单 sheet）。

    与 :func:`conservation_pending_marks` 的分工：marks 把失败连带到已声明 FRE
    （行级标红）；本函数只收集**没有任何 FRE 可挂**的缺口——清单可见、但绝不
    造需求占位行（零 FRE 条款不进需求 sheet）：

    - ``clause_gap``：``checks.clause_coverage.uncovered_sections`` 全部——标记
      函数本就不收这一类（无声明 FRE 可连带）；
    - ``uncovered``：``uncovered_obligations`` 中按 ``_clause_block_candidates``
      还原块集后与任何 item 的 ``source_block_ids`` 都不相交的义务——已连带挂
      到 FRE 的不重复（需求 sheet 已标红，清单不再造无 id 行）。

    守恒闭合（ok=True）返回空。只读 report，不 bump 守恒模型。
    """
    if report.get("ok", True):
        return []
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    gaps: list[dict[str, Any]] = []

    clause = checks.get("clause_coverage") if isinstance(
        checks.get("clause_coverage"), dict) else {}
    for row in clause.get("uncovered_sections") or []:
        if not isinstance(row, dict):
            continue
        gaps.append({
            "category": "clause_gap",
            "reason": "条款块无任何功能需求声明",
            "section_id": str(row.get("section_id") or ""),
            "functional_requirement_id": "",
            "token": "",
            "detail": str(row.get("heading") or "")[:120],
        })

    obligation = checks.get("obligation_coverage") if isinstance(
        checks.get("obligation_coverage"), dict) else {}
    declared_blocks = {
        str(b) for item in items
        if isinstance(item, dict)
        for b in (item.get("source_block_ids") or []) if str(b)
    }
    for row in obligation.get("uncovered_obligations") or []:
        if not isinstance(row, dict):
            continue
        sentence = str(row.get("sentence") or "")
        block_union: set[str] = set()
        for blocks in _clause_block_candidates(
            sections, str(row.get("section_id") or ""),
            **({"sentence": sentence} if sentence else {}),
            block_ids=row.get("section_block_ids"),
        ):
            block_union.update(blocks)
        if block_union & declared_blocks:
            continue  # 已连带挂 FRE——需求 sheet 行级已标，不重复造缺口行
        gaps.append({
            "category": "uncovered",
            "reason": "义务句未被任何功能需求覆盖",
            "section_id": str(row.get("section_id") or ""),
            "functional_requirement_id": "",
            "token": "",
            "detail": sentence[:160],
        })
    return gaps


def _check_failure_count(name: str, result: dict[str, Any]) -> int:
    if name == "evidence_presence":
        # 该检查同时写 items_without_evidence / evidence_mismatches /
        # binding_mismatches；先读到空的 items_without_evidence 不得把失败数报成 0。
        total = sum(
            len(result[key])
            for key in (
                "items_without_evidence",
                "evidence_mismatches",
                "binding_mismatches",
            )
            if isinstance(result.get(key), list)
        )
        if total:
            return total
        return 0 if result.get("ok", True) else 1
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

def _emit_functional_extract_progress(
    progress_callback: Callable[[dict[str, Any]], None] | None,
    *,
    completed: int,
    total: int,
) -> None:
    """桌面进度条：每条款包一次。不传回调则静默（测试/CLI 直调零变化）。"""
    if progress_callback is None or total <= 0:
        return
    progress_callback({
        "stage": "functional_extract",
        "completed": completed,
        "total": total,
        "percent": int(round(completed * 100 / total)),
        "unit": "clauses",
    })


def extract_functional_requirements(
    sections: Sequence[dict[str, Any]],
    *,
    chat: ExtractChat | None = None,
    route: str | None = "stub",
    blocks: Sequence[dict[str, Any]] | None = None,
    strategy: str = "legacy",
    doc_map: dict[str, Any] | None = None,
    semantic_pre_review: dict[str, Any] | None = None,
    max_chars: int | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """条款集合 → 功能需求条目列表 + 执行路由标签（如实，不夸大）。

    LLM 单次调用直出（route=openai_compatible 且有 key）；stub / 调用失败 / 返回非法 →
    确定性退化每条款一条，路由标签如实为 'stub'。返回的 items 字段模型与
    functional_catalog 同构，结构字段确定性冻结、叙述字段经护栏清洗。

    A2：``strategy="clause_family"`` 时按条款自然边界逐包调用（目标条款整文不截断 +
    同族邻居 + doc_map 热区摘要）；部分包 LLM 失败只对受影响条款诚实 stub 退化，
    路由标签如实为 'mixed'（全部失败为 'stub'，绝不夸大为纯 LLM 路由）。

    ``progress_callback``：每完成一个条款包回调一次（GUI 进度条用；不传则静默）。
    """
    if not sections:
        return [], "stub"
    active_chat, executed_route = _resolve_extract_chat(route, chat)
    # P0-8：LLM 路径才需负例；stub 路径不读库。
    bank = _load_adjudication_bank() if active_chat is not None else {}
    if strategy == "clause_family":
        return _extract_by_context_packages(
            sections, active_chat, executed_route, doc_map=doc_map, semantic_pre_review=semantic_pre_review, max_chars=max_chars,
            bank=bank,
            progress_callback=progress_callback,
        )
    items: list[dict[str, Any]] | None = None
    negative_exemplars = _negative_exemplars_for_section(sections[0], bank) if bank else ""
    _emit_functional_extract_progress(
        progress_callback, completed=0, total=len(sections),
    )
    if active_chat is not None:
        try:
            payload = active_chat(_system_prompt(negative_exemplars), _build_user_prompt(sections))
            items = _parse_llm_items(payload, sections, coalesce_per_clause=False)
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
    _emit_functional_extract_progress(
        progress_callback, completed=len(sections), total=len(sections),
    )
    return items, executed_route


def _extract_by_context_packages(
    sections: Sequence[dict[str, Any]],
    active_chat: ExtractChat | None,
    executed_route: str,
    *,
    doc_map: dict[str, Any] | None,
    semantic_pre_review: dict[str, Any] | None = None,
    max_chars: int | None,
    bank: dict[str, Any] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """clause_family 策略：每条款包一次 LLM 调用；包级失败只退化受影响条款。"""
    packages = build_context_packages(sections, doc_map=doc_map, semantic_pre_review=semantic_pre_review, max_chars=max_chars)
    items: list[dict[str, Any]] = []
    llm_ok = 0
    stub_fallback = 0
    bank = bank or {}
    total = len(packages)
    _emit_functional_extract_progress(progress_callback, completed=0, total=total)
    for index, package in enumerate(packages, start=1):
        target = package["target"]
        package_items: list[dict[str, Any]] | None = None
        negative_exemplars = _negative_exemplars_for_section(target, bank)
        if active_chat is not None:
            try:
                payload = active_chat(_package_system_prompt(negative_exemplars), _build_package_prompt(package))
                package_items = _parse_llm_items(payload, [target], coalesce_per_clause=True)
            except Exception as exc:
                LOGGER.warning("functional_extract 条款包 LLM 调用失败，该条款退回 stub：%s", exc)
                package_items = None
        if package_items is None:
            items.append(_stub_item(target, 1))
            stub_fallback += 1
        else:
            items.extend(package_items)
            llm_ok += 1
        _emit_functional_extract_progress(
            progress_callback, completed=index, total=total,
        )
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


# ---------------------------------------------------------------------------
# §17 unit 级路由接线：表格主导条款出 B 轨输入与守恒基线（仅 clause_family）
# ---------------------------------------------------------------------------

# 阻拦路由出的轨道信号：b_track/mixed 单元携带真义务内容（义务模态/强 normative 模式），
# 其所在条款必须留在 B 轨。review 单元不阻拦——review 语义本就是"物化待审、不做付费
# 提取"（unit_routing_decisions.jsonl 已留痕，M5 routing_escalation 可接手），不因其
# 弱信号把整张表留在 B 轨（phase2 实证：Table 7/8/9 事件目录的 colon_spec 弱信号单元
# 正是 flash 重复的来源）。
_ROUTING_KEEP_ROUTES = frozenset({"b_track", "mixed"})

# §7.5 前置样板章节（2026-08-18 10% 诊断三轮实证）：Scope/Normative references/
# Terms and Definitions/Foreword/Introduction 是标准文档的通用前言结构——范围声明、
# 引用清单、术语定义从不产出功能需求，flash 在这些章节上只会产出噪声条目并丢引用号
# （NBR 61334/IEC 62056 → preservation 假 blocking）。归一化小写匹配顶层路径。
_FRONT_MATTER_TOP_LEVEL = frozenset({
    "scope", "normative references", "terms and definitions", "definitions",
    "foreword", "introduction", "abstract", "目的", "规范性引用文件", "术语和定义",
    # DLMS/COSEM 文档的行规清单章（引用性列表，同 Normative references 类）
    "communication profiles",
})
# SBD 顶级标题带编号前缀（"2 DEFINITIONS"）；剥离后与集合比对。
# 保守：只剥 ``^\d+(\.\d+)*\s+``，"2 20 Control of" → "20 control of" 不命中 definitions。
_FRONT_MATTER_NUMBER_PREFIX = re.compile(r"^\d+(\.\d+)*\s+")

# 招标程序性区域：投标须知/商务附件出 B 轨。不含 tender_preface——
# Introduction 会出现在正文技术条款标题里，误伤电表功能章。
_TENDER_PROCEDURAL_REGIONS = frozenset({"tender_instructions", "tender_commercial"})


def _front_matter_top_key(title: str) -> str:
    """顶级标题归一化：折叠空白并剥离前导条款编号后再比对前置样板集合。"""
    normalized = " ".join(str(title or "").lower().split())
    return _FRONT_MATTER_NUMBER_PREFIX.sub("", normalized, count=1)


def _section_own_tender_titles(section: dict[str, Any]) -> list[str]:
    titles: list[str] = []
    for raw in (
        section.get("heading"),
        section.get("section_id"),
        *((section.get("section_path") or [])),
    ):
        title = str(raw or "").strip()
        if title and title not in titles:
            titles.append(title)
    return titles


def _section_block_heading_titles(
    section: dict[str, Any],
    blocks_by_id: dict[str, dict[str, Any]] | None,
) -> list[str]:
    if not blocks_by_id:
        return []
    titles: list[str] = []
    for block_id in (section.get("block_ids") or []):
        block = blocks_by_id.get(str(block_id))
        if block is None or str(block.get("type") or "") != "heading":
            continue
        title = str(block.get("text") or "").strip()
        if title and title not in titles:
            titles.append(title)
    return titles


def _section_tender_titles(
    section: dict[str, Any],
    blocks_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    titles = _section_own_tender_titles(section)
    for title in _section_block_heading_titles(section, blocks_by_id):
        if title not in titles:
            titles.append(title)
    return titles


def _title_is_tender_procedural(title: str) -> bool:
    from tender_regions import classify_tender_region

    return (
        classify_tender_region({"type": "heading", "text": title})
        in _TENDER_PROCEDURAL_REGIONS
    )


def _title_is_tender_technical(title: str) -> bool:
    from tender_regions import classify_tender_region

    return classify_tender_region({"type": "heading", "text": title}) == "tender_technical"


def _section_is_tender_procedural(
    section: dict[str, Any],
    blocks_by_id: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """【已退役独立权威】旧节级词表判定，仅作辅助证据/测试对照。

    WS-B（2026-08-27，architecture-convergence-plan）：条款是否路由出 B 轨改由
    ``_section_tender_aggregate_route_out`` 聚合。own title 词表判据作为义务
    单元第三条先验，不再是独立整节权威。本函数不再被 ``apply_unit_routing`` 调用。
    """
    if any(_title_is_tender_procedural(title) for title in _section_own_tender_titles(section)):
        if not _section_has_tender_technical_title(section, blocks_by_id):
            return True
    if not any(
        _title_is_tender_procedural(title)
        for title in _section_block_heading_titles(section, blocks_by_id)
    ):
        return False
    from tender_regions import classify_tender_region

    return not any(
        classify_tender_region({"type": "heading", "text": title}) == "tender_technical"
        for title in _section_own_tender_titles(section)
    )


def _section_has_tender_technical_title(
    section: dict[str, Any],
    blocks_by_id: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """任一标题/路径分类为 tender_technical → 保留（宁漏勿错，防程序跨度误伤技术章）。"""
    from tender_regions import classify_tender_region

    return any(
        classify_tender_region({"type": "heading", "text": title}) == "tender_technical"
        for title in _section_tender_titles(section, blocks_by_id)
    )


def _section_is_tender_span_procedural(
    section: dict[str, Any],
    span_by_block: dict[str, str],
    blocks_by_id: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """第二级：条款全部块落在 instructions/commercial 跨度内，且自身无 technical 标题。

    tender_preface 跨度不得导致路由出（Introduction 保护）。任一块在程序跨度外 → 保留。
    """
    block_ids = [str(b) for b in (section.get("block_ids") or []) if str(b)]
    if not block_ids:
        return False
    if any(span_by_block.get(bid) not in _TENDER_PROCEDURAL_REGIONS for bid in block_ids):
        return False
    if _section_has_tender_technical_title(section, blocks_by_id):
        return False
    return True


def _unit_is_obligation_bearing(
    unit: dict[str, Any],
    decision: dict[str, Any] | None,
) -> bool:
    """义务承载单元：散文信号句，或带义务模态 / b_track|mixed 的表格单元。"""
    kind = str(unit.get("unit_kind") or "")
    if kind in ("heading", "definition", "reference"):
        return False
    text = str(unit.get("source_text") or "")
    route = str((decision or {}).get("route") or "")
    if kind == "clause_segment":
        return True
    if kind == "narrative":
        return _has_obligation_modal(text)
    if kind in ("table_row", "table_cell"):
        return route in _ROUTING_KEEP_ROUTES or _has_obligation_modal(text)
    return False


def _section_own_title_is_tender_procedural(section: dict[str, Any]) -> bool:
    """条款自身标题（heading/id/path）经既有词表判为程序性——标题先验，不是独立权威。"""
    return any(
        _title_is_tender_procedural(title)
        for title in _section_own_tender_titles(section)
    )


def _unit_satisfies_tender_procedural(
    unit: dict[str, Any],
    decision: dict[str, Any] | None,
    span_by_block: dict[str, str],
    *,
    title_procedural: bool = False,
) -> bool:
    if (decision or {}).get("procedural_subject"):
        return True
    text = str(unit.get("source_text") or "")
    from unit_router import unit_has_product_subject

    product, _word = unit_has_product_subject(text)
    # 标题先验：own title 程序性 + 该单元不是产品主语（税清 certificate shall
    # 等程序性残骸）。产品主语句即使落在程序性标题下也保留。
    if title_procedural and not product:
        return True
    # 跨度：块在程序性区域内且该单元不是产品主语。产品主语句即使落在
    # ITB 跨度内也保留（15 GUARANTEED LIFE SPAN）。无产品主语的程序性残骸
    # （certificate shall / variation should）允许跨度召回。
    block_ids = [str(bid) for bid in (unit.get("source_block_ids") or []) if str(bid)]
    if not block_ids:
        return False
    if product:
        return False
    return all(
        span_by_block.get(bid) in _TENDER_PROCEDURAL_REGIONS for bid in block_ids
    )


def _section_tender_aggregate_route_out(
    section: dict[str, Any],
    units: Sequence[dict[str, Any]],
    decisions_by_unit: dict[str, dict[str, Any]],
    span_by_block: dict[str, str],
    blocks_by_id: dict[str, dict[str, Any]] | None,
) -> tuple[bool, str]:
    """WS-B 聚合：路由出 iff 全部义务承载单元满足程序性，且无 technical 硬信号。

    单元程序性三条：procedural_subject；无模态且块在程序跨度内；own title
    词表程序性且该单元不是产品主语。无义务单元时只走跨度回退。
    """
    # technical 否决用条款自身标题/路径（heading/id/path），不用块内吞进的
    # 下一章 heading——否则 delivery period / supply history 这类程序性残骸
    # 会被块流吞进的 "technical specification" 句子标题整节留下。
    # 技术章 1/6/7/8/9/11/21 的 own title 仍命中 tender_technical，保护不变。
    if any(
        _title_is_tender_technical(title)
        for title in _section_own_tender_titles(section)
    ):
        return False, ""
    title_procedural = _section_own_title_is_tender_procedural(section)
    section_bids = {
        str(bid) for bid in (section.get("block_ids") or []) if str(bid)
    }
    overlapping = [
        unit for unit in units
        if section_bids & {str(bid) for bid in (unit.get("source_block_ids") or [])}
    ]
    bearing: list[dict[str, Any]] = []
    for unit in overlapping:
        decision = decisions_by_unit.get(str(unit.get("unit_id") or ""))
        if _unit_is_obligation_bearing(unit, decision):
            bearing.append(unit)
    if bearing:
        if not all(
            _unit_satisfies_tender_procedural(
                unit, decisions_by_unit.get(str(unit.get("unit_id") or "")),
                span_by_block, title_procedural=title_procedural,
            )
            for unit in bearing
        ):
            return False, ""
        if all(
            (decisions_by_unit.get(str(unit.get("unit_id") or "")) or {}).get(
                "procedural_subject")
            for unit in bearing
        ) or title_procedural:
            return True, "tender_procedural"
        return True, "tender_span"
    if _section_is_tender_span_procedural(section, span_by_block, blocks_by_id):
        return True, "tender_span"
    return False, ""


def _load_routing_units(out_dir: Path) -> tuple[list[dict[str, Any]], bool]:
    """加载（必要时现场规划）extraction units；返回 (units, planned_now)。

    规划器版本陈旧或产物缺席时确定性重规划（零 LLM）——stale 单元缺格会把真表格
    内容误判成可路由，版本门是最便宜的护栏。
    """
    from extraction_units import (
        EXTRACTION_UNIT_PLANNER_VERSION,
        load_extraction_units,
        plan_extraction_units,
    )

    units = load_extraction_units(out_dir)
    current = {str(unit.get("planner_version") or "") for unit in units}
    if units and current == {EXTRACTION_UNIT_PLANNER_VERSION}:
        return units, False
    plan_extraction_units(out_dir)
    units = load_extraction_units(out_dir)
    return units, True


def _table_parse_inputs_present(out_dir: Path) -> bool:
    """表格解析产物是否在场（table_items / table_cell_items 任一存在）。"""
    from result_package import governed_artifact_path

    return any(
        governed_artifact_path(out_dir, name, category="pipeline",
                               for_write=False).is_file()
        for name in ("table_items.jsonl", "table_cell_items.jsonl")
    )


def _routing_decision_rows_for(
    out_dir: Path, units: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """完整决策行；决策产物与单元集/版本失配时现场重算（确定性零 LLM）。"""
    from unit_router import UNIT_ROUTER_VERSION, load_routing_decisions, route_units

    decisions = load_routing_decisions(out_dir)
    versions = {str(row.get("router_version") or "") for row in decisions}
    unit_ids = {str(unit.get("unit_id") or "") for unit in units}
    decision_ids = {str(row.get("unit_id") or "") for row in decisions}
    if decisions and unit_ids == decision_ids and versions == {UNIT_ROUTER_VERSION}:
        return list(decisions), False
    recomputed, _summary = route_units(units)
    return list(recomputed), True


def _routing_decisions_for(out_dir: Path, units: list[dict[str, Any]]) -> tuple[dict[str, str], bool]:
    """unit_id → route 决策表；决策产物与单元集失配时现场重算（确定性零 LLM）。"""
    rows, recomputed = _routing_decision_rows_for(out_dir, units)
    return {str(row.get("unit_id")): str(row.get("route") or "") for row in rows}, recomputed


def _confirmed_swallowed_cut_ids(
    blocks: Sequence[dict[str, Any]],
    sections: Sequence[dict[str, Any]],
) -> set[str]:
    """document_outline 报告里 confirmed 的被吞并 heading 块集（只读、确定性）。

    报告不可得（异常/无 heading）→ 空集 = 不切分（v6 行为，宁漏勿错）。
    """
    try:
        from document_outline import build_outline_report

        report = build_outline_report(
            [block for block in blocks if isinstance(block, dict)],
            sections=list(sections),
        )
    except Exception:  # noqa: BLE001 — 大纲是路由窄门修的旁证，失败退回 v6 行为
        return set()
    verdicts = {
        str(row.get("block_id") or ""): str(row.get("verdict") or "")
        for row in (report.get("headings") or []) if isinstance(row, dict)
    }
    swallowed = {
        str(item.get("block_id") or "")
        for item in (report.get("swallowed_headings") or []) if isinstance(item, dict)
    }
    return {bid for bid in swallowed if verdicts.get(bid) == "confirmed"}


def _split_section_at_confirmed_headings(
    section: dict[str, Any],
    blocks_by_id: dict[str, dict[str, Any]],
    cut_ids: set[str],
) -> tuple[list[dict[str, Any]], list[str]] | None:
    """在 confirmed 吞并 heading 处纯切分条款（零块位移；routing v7 窄门修）。

    复用 document_outline 的分解/形状/拼接契约（切分语义单一权威）；刻意不做
    toc 剔除与 demoted 并入——那是 outline authority flag 的语义，路由层只拿
    切分救"整条款被 tender 聚合连坐路由出"的内容。首片保留原条款身份，后续片
    身份 = [heading 文本]（与 recut 同式，不继承病理父链）。
    """
    if not cut_ids:
        return None
    from document_outline import (  # noqa: SLF001 — 切分契约单一权威在 document_outline
        _build_clause,
        _decompose_section,
        _section_shape,
    )

    units, decomposable = _decompose_section(section, blocks_by_id)
    if not decomposable:
        return None
    pieces_units: list[list[dict[str, Any]]] = []
    cut_here: list[str] = []
    current: list[dict[str, Any]] = []
    for unit in units:
        bid = str(unit.get("block_id") or "")
        if bid in cut_ids and current:
            pieces_units.append(current)
            cut_here.append(bid)
            current = [unit]
            continue
        current.append(unit)
    if current:
        pieces_units.append(current)
    if len(pieces_units) < 2:
        return None
    shape = _section_shape(section)
    pieces: list[dict[str, Any]] = []
    for index, piece in enumerate(pieces_units):
        if index == 0:
            identity = (
                str(section.get("section_id") or ""),
                [str(part) for part in (section.get("section_path") or [])],
                str(section.get("heading") or ""),
            )
        else:
            heading_text = str(
                (blocks_by_id.get(cut_here[index - 1]) or {}).get("text") or ""
            ).strip()
            identity = (heading_text, [heading_text], heading_text)
        pieces.append(_build_clause(shape, identity, piece, {}))
    return pieces, cut_here


# --- heading-only 条款判据（routing v8，2026-08-31）--------------------------
# SBD result3 实证：TGS 章 24 个「只有标题没有正文」的条款进了抽取池——LLM 失败退化
# stub（objective 模板回显 heading），成功也只能回显标题（零义务内容）。它们应作
# context 路由出（宁漏勿错方向：零义务内容，路由出不丢真需求）。判据必须保守：
# 任何非 heading 实质文本（含会被 v6 碎片过滤剔掉义务的碎片正文）都保留。
_HEADING_NUM_PREFIX_RE = re.compile(r"^\s*(?:#+\s*)?\d+(?:[.．]\d+)*[.．]?\s*")


def _heading_norm(text: str) -> str:
    """heading 归一键：小写、去标点、空白折叠（内容 token 序列）。"""
    tokens = re.findall(r"[0-9A-Za-z一-鿿]+", str(text or "").casefold())
    return " ".join(tokens)


def _heading_norm_variants(text: str) -> set[str]:
    """heading 文本的归一变体：原文 + 剥条款编号前缀（"22.6.5. TITLE" ↔ "TITLE"）。"""
    text = str(text or "").strip()
    variants = {_heading_norm(text)}
    stripped = _HEADING_NUM_PREFIX_RE.sub("", text)
    if stripped != text:
        variants.add(_heading_norm(stripped))
    variants.discard("")
    return variants


def _section_is_heading_only(
    section: dict[str, Any],
    blocks_by_id: dict[str, dict[str, Any]],
    table_block_ids: set[str],
) -> bool:
    """heading-only 条款判定（三条全满足才 True，任何不确定即 False——宁漏勿错）。

    ① 无表格块（block_ids 与表格块集合零交集——表格条款有独立路由通道，不碰）；
    ② 全部块要么是 heading 块，要么其文本归一化后为空（仅标点）或等于某个 heading
      归一键（heading 回显）——非 heading 块只要有任何实质文本即保留，包括会被
      conservation v6 碎片过滤剔掉义务的碎片正文（正文非空 ≠ heading-only）；
    ③ ``_obligation_index``（v6 碎片过滤后）义务单元数为 0。
    块不可得（blocks 清单缺席该 id）= 判据无法核验 → False（保留）。
    """
    block_ids = [str(b) for b in (section.get("block_ids") or []) if str(b)]
    if not block_ids:
        return False
    if any(bid in table_block_ids for bid in block_ids):
        return False
    heading_keys: set[str] = set()
    for candidate in [section.get("heading"), *(section.get("section_path") or [])]:
        heading_keys |= _heading_norm_variants(str(candidate or ""))
    body_norms: list[str] = []
    for bid in block_ids:
        block = blocks_by_id.get(bid)
        if block is None:
            return False  # 块不可得——无法核验，保守保留
        if str(block.get("type") or "") == "table":
            return False
        text = str(block.get("text") or "")
        if str(block.get("type") or "") == "heading":
            heading_keys |= _heading_norm_variants(text)
            continue
        body_norms.append(_heading_norm(text))
    if not heading_keys:
        return False  # 无任何 heading 身份——不是 heading-only 形态
    for norm in body_norms:
        if norm and norm not in heading_keys:
            return False  # 非 heading 实质文本在场——保留（宁漏勿错）
    if _obligation_index(section):
        return False
    return True


def apply_unit_routing(
    sections: Sequence[dict[str, Any]],
    *,
    blocks: Sequence[dict[str, Any]],
    out_dir: Path | str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """表格主导条款路由出 B 轨输入与守恒基线；返回 (保留条款, 审计 meta)。

    判据（确定性、宁漏勿错）：
    - 条款的**全部**声明块都是表格块（纯表格条款；表格+正文混合条款整体保留，
      计数进 meta `mixed_table_sections_kept`——B 输入粒度是条款，混合条款的正文
      义务不允许为去表格而丢）；
    - 这些块上的单元路由无 b_track/mixed（review/context/a_track 不阻拦，见
      ``_ROUTING_KEEP_ROUTES`` 注释）；
    - 单元/决策不可得（产物缺席且无法规划）→ **不路由任何条款**，meta 如实
      `status="unavailable"`——退回全量输入是保守行为（B 多覆盖不丢内容），绝不静默。

    被路由出的条款清单（section/block id）全部写入 meta；`routed_out_review_units`
    记录其上的 review 单元数（这些单元已在路由产物中物化待审，不因路由出而消失）。

    routing v8 新增 heading-only 通道：只有标题没有实质正文的条款（全部块为
    heading/heading 回显、``_obligation_index`` 义务单元数 0、无表格块）作 context
    路由出——判据三条全满足才出（``_section_is_heading_only``，宁漏勿错），
    meta `heading_only_sections_routed_out`/`heading_only_section_ids` 审计。
    """
    from extraction_units import EXTRACTION_UNIT_PLANNER_VERSION
    from unit_router import UNIT_ROUTER_VERSION

    meta: dict[str, Any] = {
        "routing_version": FUNCTIONAL_UNIT_ROUTING_VERSION,
        "planner_version": EXTRACTION_UNIT_PLANNER_VERSION,
        "router_version": UNIT_ROUTER_VERSION,
    }
    if out_dir is None:
        meta.update(status="unavailable", reason="no_out_dir")
        return list(sections), meta
    out_dir = Path(out_dir).expanduser().resolve()
    try:
        units, replanned = _load_routing_units(out_dir)
        decision_rows, recomputed = _routing_decision_rows_for(out_dir, units)
        route_by_unit = {
            str(row.get("unit_id")): str(row.get("route") or "")
            for row in decision_rows
        }
        decisions_by_unit = {
            str(row.get("unit_id")): row for row in decision_rows if row.get("unit_id")
        }
    except Exception as exc:  # noqa: BLE001 — 规划/路由失败退回全量输入（保守），如实记录
        meta.update(status="unavailable", reason=f"planning_failed:{exc}")
        return list(sections), meta
    if not units:
        meta.update(status="unavailable", reason="extraction_units_empty")
        return list(sections), meta

    table_block_ids = {
        str(block.get("block_id")) for block in blocks
        if str(block.get("block_id")) and str(block.get("type") or "") == "table"
    }
    if table_block_ids and not _table_parse_inputs_present(out_dir):
        # 有表格块但表格解析产物缺席（旧输出/未跑表格链）——表格内容不可核验，
        # 路由出去就是盲丢内容。如实 unavailable，退回全量输入（保守）。
        meta.update(status="unavailable", reason="table_parse_inputs_missing")
        return list(sections), meta
    routes_by_block: dict[str, set[str]] = {}
    review_units_by_block: dict[str, int] = {}
    for unit in units:
        route = route_by_unit.get(str(unit.get("unit_id") or ""))
        if not route:
            continue
        for block_id in (unit.get("source_block_ids") or []):
            bid = str(block_id)
            routes_by_block.setdefault(bid, set()).add(route)
            if route == "review":
                review_units_by_block[bid] = review_units_by_block.get(bid, 0) + 1

    from tender_regions import tender_region_spans

    span_by_block = tender_region_spans(list(blocks))
    blocks_by_id = {
        str(block.get("block_id")): block
        for block in blocks
        if str(block.get("block_id") or "")
    }
    kept: list[dict[str, Any]] = []
    routed_out: list[dict[str, Any]] = []
    front_matter: list[dict[str, Any]] = []
    tender_procedural: list[dict[str, Any]] = []
    tender_span: list[dict[str, Any]] = []
    heading_only: list[dict[str, Any]] = []
    mixed_kept = 0
    # routing v7 窄门修：confirmed 吞并 heading 块集（只读旁证；不可得=不切分）
    meta.setdefault("outline_veto_split_sections", 0)
    meta.setdefault("outline_veto_split_block_ids", [])
    outline_cut_ids = _confirmed_swallowed_cut_ids(blocks, sections)

    def _classify(section: dict[str, Any]) -> None:
        nonlocal mixed_kept
        path = [str(part).strip() for part in (section.get("section_path") or [])]
        top = _front_matter_top_key(path[0]) if path else ""
        if top in _FRONT_MATTER_TOP_LEVEL:
            # §7.5 前置样板章节：范围/引用/术语定义——归 context 索引，不进 B 轨
            # （单独计数，与表格路由区分审计）。
            front_matter.append(section)
            return
        # WS-B：路由出 = 义务主体/标题先验/跨度聚合 + technical 否决。
        tender_out, tender_bucket = _section_tender_aggregate_route_out(
            section, units, decisions_by_unit, span_by_block, blocks_by_id)
        if tender_out:
            # routing v7：整条款路由出之前，先在 confirmed 吞并 heading 处切开——
            # 程序性残骸照旧路由出，被连坐的技术内容获得独立判定（SBD 实证 2.3
            # STATEMENT OF REQUIREMENTS 整章被利益冲突条款连坐）。切分零块位移。
            split = (
                _split_section_at_confirmed_headings(
                    section, blocks_by_id, outline_cut_ids)
                if outline_cut_ids else None
            )
            if split is not None:
                pieces, cut_here = split
                meta["outline_veto_split_sections"] += 1
                meta["outline_veto_split_block_ids"].extend(cut_here)
                for piece in pieces:
                    _classify(piece)
                return
            if tender_bucket == "tender_procedural":
                tender_procedural.append(section)
            else:
                tender_span.append(section)
            return
        # routing v8：heading-only 条款（无实质正文/零义务单元/无表格块）作 context
        # 路由出——LLM 对它们只能回显标题或退化 stub，零可抽取内容（宁漏勿错：
        # 判据三条全满足才出，非 heading 实质文本在场即保留）。
        if _section_is_heading_only(section, blocks_by_id, table_block_ids):
            heading_only.append(section)
            return
        block_ids = [str(b) for b in (section.get("block_ids") or []) if str(b)]
        has_table = bool(block_ids) and any(b in table_block_ids for b in block_ids)
        all_table = bool(block_ids) and all(b in table_block_ids for b in block_ids)
        if has_table and not all_table:
            mixed_kept += 1
        if all_table:
            block_routes: set[str] = set()
            for bid in block_ids:
                block_routes |= routes_by_block.get(bid, set())
            if not (block_routes & _ROUTING_KEEP_ROUTES):
                routed_out.append(section)
                return
        kept.append(section)

    for section in sections:
        _classify(section)

    meta.update(
        status="ok",
        sections_total=len(sections),
        sections_extracted=len(kept),
        table_dominated_routed_out=len(routed_out),
        front_matter_routed_out=len(front_matter),
        front_matter_section_ids=[
            " / ".join(str(p) for p in (section.get("section_path") or []))
            for section in front_matter],
        tender_procedural_routed_out=len(tender_procedural),
        tender_procedural_section_ids=[
            str(section.get("section_id") or "") for section in tender_procedural],
        tender_span_routed_out=len(tender_span),
        tender_span_section_ids=[
            str(section.get("section_id") or "") for section in tender_span],
        # routing v8：heading-only 条款桶（只有标题没有实质正文，零义务单元，无表格块）。
        heading_only_sections_routed_out=len(heading_only),
        heading_only_section_ids=[
            str(section.get("section_id") or "") for section in heading_only],
        routed_out_section_ids=[
            str(section.get("section_id") or "") for section in routed_out
        ] + [
            str(section.get("section_id") or "") for section in tender_procedural
        ] + [
            str(section.get("section_id") or "") for section in tender_span
        ] + [
            str(section.get("section_id") or "") for section in heading_only
        ],
        # routing v7：三桶（表格/tender 程序性/tender 跨度）的块全部入清单——
        # docstring「被路由出的条款清单（section/block id）全部写入 meta」承诺兑现
        # （v6 只含表格桶，tender 两桶的块不在清单里，审计面不完整）。
        # routing v8：heading_only 第四桶同样并入（承诺对全部路由出桶生效）。
        routed_out_block_ids=sorted({
            str(b)
            for section in (
                routed_out + tender_procedural + tender_span + heading_only)
            for b in (section.get("block_ids") or []) if str(b)
        }),
        routed_out_review_units=sum(
            review_units_by_block.get(str(b), 0)
            for section in (
                routed_out + tender_procedural + tender_span + heading_only)
            for b in (section.get("block_ids") or []) if str(b)
        ),
        mixed_table_sections_kept=mixed_kept,
        units_replanned=replanned,
        decisions_recomputed=recomputed,
    )
    return kept, meta


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


def functional_direct_basis(
    root: Path | str, *, allow_unclosed: bool = False,
) -> list[dict[str, Any]] | None:
    """直抽产物可否作为唯一需求依据（无原子链形态，RATOMIZER_FUNCTIONAL_EXTRACT=1）。

    供 requirements_analysis / clarification_report 的缺原子门共用：三查 producer 家族
    （functional-extract）、items 为列表、守恒闭合。守恒未闭合不在此二值判断内——直接
    ``raise_if_unconserved`` 响亮失败（成文闸门纪律），绝不静默回退空表产"0 条"假交付物。
    不满足前置返回 None，调用方维持各自的响亮失败。
    partial export（2026-09-01）：``allow_unclosed=True`` 时守恒未闭合与
    execution_status=partial（mixed，SBD 主形态）放行——调用方继续并如实标
    partial；execution_status=failed（整段 stub）**无论开关一律照旧 raise**
    （数据不完整不是守恒未闭合，旁路不放行）。
    v3（2026-09-01c，Task2）：``draft:true``（stub 草稿水印）且守恒未闭合——
    **无论开关一律 raise Incomplete**：旁路放行的前提是"数据本身可信，只是
    守恒有缺口"，draft+未闭合意味着占位数据+缺口叠加，不能出表。draft+守恒
    闭合（显式 stub opt-in/烟测）保持现状不扩大拦截。
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
        # 有块未闭合 = 响亮失败，绝不静默进成文（partial export 旁路除外）。
        raise_if_unconserved(conservation, allow_unclosed=allow_unclosed)
    # §3.5：执行不完整（stub 降级 / mixed 部分失败）同样响亮阻断下游——缓存行携带的
    # 失败语义在这里保持为失败（_payload_execution_status 不用当前请求路由重算）。
    # partial export：partial（mixed）在 allow_unclosed 下放行；failed 一律拦。
    status = _payload_execution_status(payload)
    if status == "failed" or (status != "ok" and not allow_unclosed):
        raise FunctionalExtractionIncompleteError(
            f"功能直抽执行不完整（execution_status={status}，"
            f"route_requested={payload.get('route_requested')}, route={payload.get('route')}），"
            "阻塞需求分析/澄清/成文下游；请修复 LLM 路由后重跑直抽"
            "（显式 route=stub 仅限测试/烟测 opt-in）"
        )
    conservation_closed = (
        not isinstance(conservation, dict) or bool(conservation.get("ok", True))
    )
    if payload.get("draft") and not conservation_closed:
        raise FunctionalExtractionIncompleteError(
            "功能直抽产物带 stub 草稿水印且守恒未闭合（draft=true），"
            "阻塞需求分析/澄清/成文下游；partial export 旁路不放行 draft"
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
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    truth_set: Path | str | None = None,
    limit_sections: int | None = None,
) -> dict[str, Any]:
    """运行功能需求直抽，写 functional_requirements.json（governed 路径 + 原子写）。

    ``sections`` 缺省时从 ``chunks.jsonl``（extract_units 条款切分产物）惰性加载——
    不改 extract_units / atomize（硬边界：直抽替换下游两阶段，旧路径可显式回滚）。

    A2：``strategy`` 缺省读 ``context_pack_strategy()``（直抽开启且未显式指定时
    为 clause_family；显式 legacy 仍可用）。clause_family 下自动只读加载 A1
    整篇地图（``doc_map.load_doc_map``，缺席/不可用则不带摘要，退回无地图包——不伪造）。

    ``limit_sections``（2026-09-07 WS0 成本受限冒烟）：条款池截前 N——抽取输入与
    守恒基线同源同截（conservation 在本函数内以同一 sections 计算，子集自洽）；
    批指纹随 clauses 列表自然换键，与全量键空间不串。None = 全量（默认，行为不变）。
    """
    out_dir = Path(out_dir).expanduser().resolve()
    if limit_sections is not None and (
        type(limit_sections) is not int or limit_sections <= 0
    ):
        raise ValueError("limit_sections must be a positive integer")
    outline_authority_audit: dict[str, Any] | None = None
    if sections is None:
        # Phase 2b：flag 开时 load_clauses_detailed 产出重切条款 + 审计；
        # 报告不可得时如实回退原始边界并记 unavailable（审计随产物落盘）。
        sections, outline_authority_audit = load_clauses_detailed(out_dir)
    sections = list(sections)
    # 候选筛选层：只把需求/表格/待判断语义单元对应的条款送入抽取，
    # 缺少候选产物时保持兼容并继续使用完整条款池。
    try:
        from result_package import governed_artifact_path
        import json
        candidate_path = governed_artifact_path(out_dir, "requirement_candidates.json", for_write=False)
        if candidate_path.is_file():
            candidate_payload = json.loads(candidate_path.read_text(encoding="utf-8"))
            selected_ids = {str(block_id) for row in (candidate_payload.get("units") or [])
                            if row.get("category") in {"requirement_candidate", "table_candidate", "needs_review"}
                            for block_id in (row.get("source_block_ids") or [])}
            filtered = [section for section in sections if selected_ids.intersection(str(x) for x in (section.get("block_ids") or []))]
            if filtered:
                sections = filtered
    except Exception:
        pass
    source_section_count = len(sections)
    if limit_sections is not None:
        sections = sections[:limit_sections]
    _emit_functional_extract_progress(
        progress_callback, completed=0, total=len(sections),
    )
    resolved_strategy = context_pack_strategy(strategy)
    if resolved_strategy == "clause_family" and doc_map is None:
        try:
            from doc_map import load_doc_map
            doc_map = load_doc_map(out_dir)
        except Exception:  # noqa: BLE001 — 无地图时退回无地图包，不阻断
            doc_map = None
    # §17 unit 级路由接线：仅 clause_family——表格主导条款出 B 轨输入与守恒基线
    # （legacy 零变化：不加载单元、不过滤、产物不带 unit_routing 块）。指纹在过滤后
    # 计算——被路由出的条款不进 clauses 列表，路由判据版本另由 unit_routing_key 钉住。
    unit_routing: dict[str, Any] | None = None
    if resolved_strategy == "clause_family":
        if blocks is None:
            blocks = _load_blocks(out_dir)
        sections, unit_routing = apply_unit_routing(
            sections, blocks=blocks, out_dir=out_dir)
        _emit_functional_extract_progress(
            progress_callback, completed=0, total=len(sections),
        )
    # S1-7：指纹并入 route 维度——算指纹前先把 route 解析成稳定身份标签（与执行路径同源）。
    route_label = _resolve_route_label(route, chat)
    fingerprint = extraction_fingerprint(
        sections,
        route_key=route_label,
        context_strategy=resolved_strategy,
        doc_map_key=str(doc_map.get("fingerprint") or "") if isinstance(doc_map, dict) else "",
        limit_sections=limit_sections,
    )

    # 缓存命中放行（指纹含版本/prompt/护栏/route；clause_family 另含策略与地图键）
    cache = _read_cache(out_dir)
    cached = cache.get(fingerprint)
    if cached is not None and isinstance(cached.get("payload"), dict):
        payload = dict(cached["payload"])
        _emit_functional_extract_progress(
            progress_callback,
            completed=len(sections),
            total=len(sections) or 1,
        )
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
        progress_callback=progress_callback,
    )
    conservation = conservation_report(
        sections, items, blocks=blocks, out_dir=out_dir)
    # §3.5：执行结果类别随产物持久化（缓存行同样携带——重放不洗白失败语义）。
    resolved_status = execution_status(
        route, executed_route, requested_label=route_label,
    )

    quality_gate: dict[str, Any] = {
        "status": "NO_GATE",
        "evaluator": "tools/functional_truth_eval.py",
        "reason": "human truth set evaluation has not been supplied",
    }
    if truth_set is not None:
        # 阈值权威在评估工具（当前 0.0="不劣于空尺"起点，见该模块注释）——此处
        # 必须引用常量而非字面量，否则阈值上调时产物里的 PASS 判定静默停在旧值。
        from tools.functional_truth_eval import (
            DEFAULT_PRECISION_THRESHOLD,
            DEFAULT_RECALL_THRESHOLD,
            _load_truth,
            evaluate_doc,
        )
        truth_entries = _load_truth(Path(truth_set).expanduser().resolve())
        evaluation = evaluate_doc(truth_entries, items)
        quality_gate = {
            "status": (
                "PASS"
                if truth_entries
                and evaluation["recall"] >= DEFAULT_RECALL_THRESHOLD
                and evaluation["precision"] >= DEFAULT_PRECISION_THRESHOLD
                else "NO_GATE"
            ),
            "evaluator": "tools/functional_truth_eval.py",
            "truth_set": str(Path(truth_set).expanduser().resolve()),
            "metrics": evaluation,
        }
        if not truth_entries:
            quality_gate["reason"] = "truth set is empty"
        elif limit_sections is not None:
            quality_gate["status"] = "NO_GATE"
            quality_gate["reason"] = (
                "limited section smoke cannot establish full-document quality"
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
        "input_scope": {
            "mode": "limited_smoke" if limit_sections is not None else "full_document",
            "limit_sections": limit_sections,
            "selected_section_count": len(sections),
            "source_section_count": source_section_count,
        },
        "functional_requirements": len(items),
        "fingerprint": fingerprint,
        "conservation": conservation,
        "items": items,
        # A functional result is usable for review, but it is not a release
        # quality claim until the human truth set evaluator has been run.
        "quality_gate": quality_gate,
    }
    if unit_routing is not None:
        # §17：路由审计块（被路由出条款清单/计数/版本身份）；legacy 产物不带此块。
        payload["unit_routing"] = unit_routing
    if outline_authority_audit is not None:
        # Phase 2b：大纲权威重切审计（flag 开才出现；缓存行随负载携带，重放不洗白）。
        payload["outline_authority"] = outline_authority_audit
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
    # 领域映射只是确定性审计提示，不参与抽取/守恒判定；在这里附加也能
    # 给旧缓存补齐同一份扩展契约，避免缓存命中时字段形状分叉。
    from cosem_mapping import attach_functional_mappings
    attach_functional_mappings(payload)
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
        "quality_gate": payload.get("quality_gate", {"status": "NO_GATE"}),
        "written": [FUNCTIONAL_REQUIREMENTS_FILENAME] if write else [],
    }
    result["incomplete_inputs"] = payload.get("incomplete_inputs", False)
    result["input_completeness"] = payload.get("input_completeness", {})
    result["input_scope"] = payload.get("input_scope", {
        "mode": "full_document",
        "limit_sections": None,
        "selected_section_count": payload.get("clause_count", 0),
    })
    routing = payload.get("unit_routing")
    if isinstance(routing, dict):
        # §17：结果摘要镜像路由事实（CLI/manifest/链路日志可见，不进产物考古）
        result["unit_routing"] = {
            "status": routing.get("status"),
            "table_dominated_routed_out": routing.get("table_dominated_routed_out", 0),
            "sections_extracted": routing.get("sections_extracted"),
        }
    authority = payload.get("outline_authority")
    if isinstance(authority, dict):
        # Phase 2b：结果摘要镜像大纲权威状态（applied / unavailable:<reason>）
        result["outline_authority"] = {"status": authority.get("status")}
    return result


# ---------------------------------------------------------------------------
# 条款加载（不改 extract_units / atomize）
# ---------------------------------------------------------------------------

def load_clauses(
    out_dir: Path | str,
    *,
    outline_authority: bool | None = None,
) -> list[dict[str, Any]]:
    """从 extract_units 条款切分产物惰性加载条款单元。

    优先读 governed ``chunks.jsonl``（每行一个章节/条款单元，含 section_path/text/block_ids），
    缺失则退回 ``blocks.jsonl`` 经 ``extract_units.assemble_sections`` 现场聚合——两条路径
    都不改 extract_units / atomize 主线（硬边界：直抽是旁路新入口）。

    Phase 2b（大纲权威第一片）：``outline_authority=None``（默认）按
    ``RATOMIZER_OUTLINE_AUTHORITY`` 门控重切（与 assemble_sections 同一权威、
    逐字节同口径）；``False`` 强制取**原始边界**（报告构建等调用方）；
    ``True`` 强制重切。需要重切审计的调用方用 :func:`load_clauses_detailed`。
    """
    return load_clauses_detailed(out_dir, outline_authority=outline_authority)[0]


def load_clauses_detailed(
    out_dir: Path | str,
    *,
    outline_authority: bool | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """``load_clauses`` 的详细形态：额外返回大纲权威重切审计。

    flag 关（默认）→ ``(sections, None)``（零行为变化）；flag 开 → 重切 +
    审计；报告不可得（blocks 缺席/条款无块序列）→ 原始边界 +
    ``{"status": "unavailable:<reason>"}``（如实回退，绝不静默假装重切过）。
    """
    from io_utils import read_jsonl
    from result_package import governed_artifact_path

    out_dir = Path(out_dir).expanduser().resolve()
    semantic_sections = _load_semantic_sections(out_dir)
    if semantic_sections:
        if outline_authority is not False:
            from document_outline import apply_outline_authority

            return apply_outline_authority(
                _load_blocks(out_dir), semantic_sections, enabled=outline_authority)
        return semantic_sections, None
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
            if outline_authority is not False:
                from document_outline import apply_outline_authority

                return apply_outline_authority(
                    _load_blocks(out_dir), sections, enabled=outline_authority)
            return sections, None
    # 兜底：现场聚合 blocks（不改 atomize，只读其产物）；chunks 缺席时 assemble
    # 路径自带同一大纲权威（assemble_sections_detailed），审计原样上抛。
    blocks_path = governed_artifact_path(out_dir, "blocks.jsonl", category="pipeline", for_write=False)
    if blocks_path.is_file():
        from extract_units import assemble_sections_detailed

        return assemble_sections_detailed(
            read_jsonl(blocks_path), outline_authority=outline_authority)
    return [], None


def _load_semantic_sections(out_dir: Path) -> list[dict[str, Any]]:
    """Load the validated semantic partition produced by the parse stage.

    The sidecar is an input contract for functional extraction, so malformed or
    stale reports must fall back to the existing chunks path rather than
    silently dropping source blocks.

    noise 块（页眉/页脚/版权行，parser 标 ``noise: true``）不进条款文本与守恒基线
    ——与旧 chunks 路径同口径（``build_chunks`` 跳过 noise）。语义单元按"全块覆盖"
    校验，因此 noise 块从覆盖要求中放行并从单元文本/块锚中剔除，而不是让页脚文本
    携带页码/标准号进入 preservation 基线（否则守恒对噪声行假 blocking）。
    """
    from io_utils import read_jsonl
    from result_package import governed_artifact_path

    report_path = governed_artifact_path(
        out_dir, "semantic_segmentation.json", category="pipeline", for_write=False,
    )
    blocks_path = governed_artifact_path(out_dir, "blocks.jsonl", category="pipeline", for_write=False)
    if not report_path.is_file() or not blocks_path.is_file():
        return []
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if (report.get("configuration") or {}).get("mode") == "off":
            return []
        units = report.get("units")
        blocks = [row for row in read_jsonl(blocks_path) if isinstance(row, dict)]
        blocks_by_id = {
            str(row["block_id"]): row for row in blocks if row.get("block_id") is not None
        }
        required_ids = {
            block_id for block_id, row in blocks_by_id.items() if not row.get("noise")
        }
        sections: list[dict[str, Any]] = []
        seen: set[str] = set()
        seen_units: set[str] = set()
        for unit in units if isinstance(units, list) else []:
            if not isinstance(unit, dict):
                return []
            source_ids = [str(value) for value in (unit.get("source_block_ids") or [])]
            unit_id = str(unit.get("semantic_unit_id") or "")
            if (not unit_id or unit_id in seen_units or not source_ids
                    or len(source_ids) != len(set(source_ids))
                    or any(value not in blocks_by_id for value in source_ids)):
                return []
            seen_units.add(unit_id)
            kept_ids = [
                block_id for block_id in source_ids
                if not blocks_by_id[block_id].get("noise")
            ]
            if not kept_ids:
                # 纯 noise 单元（孤立页脚等）没有可抽取/可守恒的正文，整单元放行。
                continue
            if any(block_id in seen for block_id in kept_ids):
                # 分区契约：每块恰好一次。重复声明块的 sidecar 视为畸形，回落 chunks。
                return []
            seen.update(kept_ids)
            path = [str(value) for value in (unit.get("section_path") or [])]
            sections.append({
                "section_id": unit_id,
                "section_path": path,
                "heading": path[-1] if path else "",
                # 语义单元不改写文本（member text 以 "\n" 拼接），从保留块重建与
                # sidecar 文本逐字节一致——noise 成员被剔除。
                "text": "\n".join(
                    str(blocks_by_id[block_id].get("text") or "") for block_id in kept_ids
                ),
                "block_ids": kept_ids,
            })
        if not sections or seen != required_ids:
            return []
        return sections
    except (OSError, ValueError, TypeError, KeyError):
        return []


def _load_blocks(out_dir: Path) -> list[dict[str, Any]]:
    from io_utils import read_jsonl
    from result_package import governed_artifact_path
    path = governed_artifact_path(out_dir, "blocks.jsonl", category="pipeline", for_write=False)
    return read_jsonl(path) if path.is_file() else []
