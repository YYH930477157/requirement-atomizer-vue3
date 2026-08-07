"""WS2 原子级下钻判定器（确定性规则，LLM 不参与"是否下钻"决策）。

直抽把粒度抬升到功能需求级后，少数条款需要在原子级逐句/逐行取证（多行为、多条件、参数
矩阵；以及质量信号：ambiguity / conflict_flags / 评审逐句取证质疑）。本模块用**纯确定性
规则**判定哪些功能需求条目应下钻，并把下钻子原子回填所属功能需求条目——评审界面始终以
功能需求级条目为裁决对象，下钻只在需要时为取证服务。

设计依据（方案 §4.1.1）：两类信号全部由确定性代码判定——模态词计数、条件连接词检测、表
引用几何检查，**LLM 不参与"是否下钻"的决策**，防止下钻范围被模型自行放大而抵消成本收益。
误判代价在两个方向上不对称但均无正确性风险：漏下钻延迟到评审质疑时补钻，误下钻仅多付一条
条款的原子化成本。

阈值设计为配置项（见 ``config.ENV_REGISTRY`` 的 functional-drilldown 系列），正式阈值按
DLMS 文档族金标回归标定（WS0 真值集 pending-human，本切片只交付机制）。
"""
from __future__ import annotations

import os
import re
from typing import Any, Callable, Sequence

FUNCTIONAL_DRILLDOWN_VERSION = "functional-drilldown-v1"

# 模态动词（义务性）：multi_behavior 信号计数基准
_OBLIGATION_MODALS = (
    "shall", "must", "will", "may", "should", "need to",
    "应", "必须", "须", "可", "宜", "需要",
)
# 条件连接词 / 互斥分支标记：multi_condition 信号计数基准（与 semantic_quality 互斥限定词
# 判据同源——functional_catalog.opposed_qualifiers 检测互斥分支）。
#
# S1-8：旧实现用裸子串匹配（``"or " in lowered``），``"or "`` 是 ``"for "``/``"author "``/
# ``"priority "`` 的子串→含 ``for`` 的普通条款近恒 fired。英文连接词改 **词边界** 正则
# （``\bor\b``），杜绝子串误命中；中文单字 ``"当"``/``"若"`` 同样过宽（命中 ``适当``/``当地``/
# ``若干``），收紧为 **词组级判据**（``当…时``/``若是``/``若…则``）。
_CONDITION_CONNECTORS_EN = (
    "if", "when", "unless", "in case", "where", "depending on",
    "either", "or", "otherwise",
)
_CONDITION_CONNECTORS_ZH_PATTERNS = (
    r"如果",
    r"若是",
    r"若.{0,8}则",      # 若…则（条件推导）
    r"当.{0,12}时",     # 当…时（避免命中 当然/适当/当时/当地）
    r"除非",
    r"或者",
    r"否则",
    r"在.{0,12}时",     # 在…时（原有判据，加界防过宽）
    r"视.{0,8}而定",    # 视…而定（原有判据，加界防过宽）
)
_EN_CONNECTOR_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in _CONDITION_CONNECTORS_EN) + r")\b",
    re.IGNORECASE,
)
_ZH_CONNECTOR_RE = re.compile("|".join(_CONDITION_CONNECTORS_ZH_PATTERNS))
_CHALLENGE_MARKERS = ("challenge", "质疑", "取证", "逐句", "存疑", "disagree", "需复核")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return default
    return value if value >= 1 else default


def default_thresholds() -> dict[str, int]:
    """从 config.ENV_REGISTRY 读取阈值（正式值待 WS0 金标回归标定）。"""
    return {
        "multi_behavior": _env_int("RATOMIZER_FUNCTIONAL_DRILLDOWN_MULTI_BEHAVIOR", 2),
        "multi_condition": _env_int("RATOMIZER_FUNCTIONAL_DRILLDOWN_MULTI_CONDITION", 1),
        "matrix_rows": _env_int("RATOMIZER_FUNCTIONAL_DRILLDOWN_MATRIX_ROWS", 2),
    }


# ---------------------------------------------------------------------------
# 信号 1：多行为（同一主语 ≥N 个义务性模态动词支配不同动作）
# ---------------------------------------------------------------------------

def _action_after_modal(text: str) -> set[str]:
    """提取每个义务性模态动词后紧跟的动作词（粗粒度，仅用于计数不同动作）。

    计数的是"模态词 + 不同动作词干"组合数，而非模态词本身——单个 shall 管多个动作也算。
    """
    lowered = " " + text.lower() + " "
    actions: set[str] = set()
    # 英文：modal + verb
    for modal in ("shall", "must", "will", "may", "should", "need to"):
        for match in re.finditer(rf"\b{re.escape(modal)}\s+([a-z]+)", lowered):
            actions.add(match.group(1))
    # 中文：模态词 + 紧邻 1-6 字动作（CJK）
    for modal in ("应", "必须", "须", "可", "宜", "需要"):
        for match in re.finditer(rf"{re.escape(modal)}([一-鿿]{{1,6}})", text):
            actions.add(match.group(1))
    return actions


def multi_behavior_signal(text: str, *, threshold: int = 2) -> dict[str, Any]:
    actions = _action_after_modal(text)
    return {
        "name": "multi_behavior",
        "fired": len(actions) >= threshold,
        "modal_action_count": len(actions),
        "threshold": threshold,
        "actions": sorted(actions),
    }


# ---------------------------------------------------------------------------
# 信号 2：多条件（条件从句嵌套或互斥分支，与 semantic_quality 互斥限定词判据同源）
# ---------------------------------------------------------------------------

def multi_condition_signal(
    text: str,
    *,
    threshold: int = 1,
    opposed_check: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """条件从句 / 互斥分支检测。

    ``opposed_check`` 注入是为了与 ``functional_catalog.opposed_qualifiers`` 同源——但
    opposed_qualifiers 是成对需求间判定，单条款内只能用连接词检测；成对互斥在 catalog 层
    已分家（不在此处）。这里只做单条款内的条件连接词/分支计数。

    S1-8：英文连接词用词边界正则（``\bor\b``，避免 ``"or "`` 命中 ``"for "``）；中文用词组
    级判据（``当…时`` 等，避免单字 ``"当"`` 命中 ``适当/当地``）。命中连接词的种类数（去重）
    达阈值即 fired。
    """
    en_terms = {m.group(0).lower() for m in _EN_CONNECTOR_RE.finditer(text)}
    zh_terms = {m.group(0) for m in _ZH_CONNECTOR_RE.finditer(text)}
    hit_terms = sorted(en_terms | zh_terms)
    hits = len(hit_terms)
    return {
        "name": "multi_condition",
        "fired": hits >= threshold,
        "condition_count": hits,
        "threshold": threshold,
        "connectors": hit_terms,
    }


# ---------------------------------------------------------------------------
# 信号 3：参数矩阵（条款引用多行参数组合表）
# ---------------------------------------------------------------------------

def parameter_matrix_signal(
    section: dict[str, Any],
    *,
    threshold: int = 2,
    table_items: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """条款来源块引用了含 ≥N 数据行的参数组合表 → 每行构成独立取值情形。

    判定纯几何：条款 source_block_ids 命中的表块，其 table_items 数据行数 ≥ 阈值。
    无 table_items 证据时不猜（宁漏勿错）。
    """
    block_ids = {str(b) for b in (section.get("block_ids") or []) if str(b)}
    if not block_ids or not table_items:
        return {"name": "parameter_matrix", "fired": False, "row_count": 0, "threshold": threshold}
    rows_for_clause = 0
    matched_tables: set[str] = set()
    for item in table_items:
        table_block = str(item.get("table_block_id") or "")
        if table_block in block_ids:
            matched_tables.add(table_block)
    # 粗粒度：命中的表块下 table_items 条数视作数据行数（参数表行级化产物本就是逐行一条）
    if matched_tables:
        rows_for_clause = sum(
            1 for item in table_items
            if str(item.get("table_block_id") or "") in matched_tables
        )
    return {
        "name": "parameter_matrix",
        "fired": rows_for_clause >= threshold,
        "row_count": rows_for_clause,
        "threshold": threshold,
        "matched_table_block_ids": sorted(matched_tables),
    }


# ---------------------------------------------------------------------------
# 质量信号：ambiguity / conflict_flags / 评审逐句取证质疑
# ---------------------------------------------------------------------------

def ambiguity_signal(item: dict[str, Any]) -> dict[str, Any]:
    fired = bool(item.get("ambiguity")) or bool(item.get("ambiguous"))
    return {"name": "ambiguity", "fired": fired, "source": "item.ambiguity"}


def conflict_signal(item: dict[str, Any]) -> dict[str, Any]:
    flags = item.get("conflict_flags") or []
    fired = bool(flags)
    return {"name": "conflict_flags", "fired": fired, "count": len(flags) if isinstance(flags, list) else 0}


def review_challenge_signal(review_state: dict[str, Any] | None) -> dict[str, Any]:
    """评审专家对该条目提出逐句取证质疑（reason / status 标记）。"""
    if not review_state or not isinstance(review_state, dict):
        return {"name": "review_challenge", "fired": False}
    blob = " ".join(str(review_state.get(k) or "") for k in ("reason", "status", "note", "actor"))
    fired = any(marker in blob.lower() for marker in _CHALLENGE_MARKERS)
    return {"name": "review_challenge", "fired": fired}


# ---------------------------------------------------------------------------
# 下钻子原子（确定性切分，非 LLM）
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。.!?；;])\s+|\n+")

def _split_to_subatoms(section: dict[str, Any]) -> list[dict[str, Any]]:
    """把一条条款确定性切成原子级子条目（句号/分号/换行切分），回填溯源。

    切分只为取证——每条子原子继承父条款 block_ids，并标注所属父功能需求。LLM 不参与。
    """
    text = str(section.get("text") or "")
    heading = str(section.get("heading") or "")
    block_ids = [str(b) for b in (section.get("block_ids") or []) if str(b)]
    section_path = [str(s) for s in (section.get("section_path") or [])]
    if not text.strip():
        return []
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if len(sentences) <= 1:
        # 单句不切；但若 multi_behavior 触发（一句多义务），按义务词再切一刀
        parts = re.split(r"(?<=[。.；;])|(?<=shall )|(?<=必须)|(?<=应)", text)
        sentences = [s.strip() for s in parts if s.strip() and len(s.strip()) >= 3]
    subatoms: list[dict[str, Any]] = []
    for idx, sentence in enumerate(sentences, start=1):
        if not sentence:
            continue
        subatoms.append({
            "subatom_index": idx,
            "text": sentence,
            "source_quote": sentence,
            "source_section": " / ".join(section_path),
            "source_block_ids": block_ids,
        })
    return subatoms


# ---------------------------------------------------------------------------
# 主判定
# ---------------------------------------------------------------------------

def decide_drilldown(
    item: dict[str, Any],
    section: dict[str, Any],
    *,
    thresholds: dict[str, int] | None = None,
    table_items: Sequence[dict[str, Any]] | None = None,
    review_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """判定一条功能需求是否需要原子级下钻，并确定性产出子原子。

    返回 ``{"drill": bool, "signals": [...], "subatoms": [...], "version": ...}``。
    LLM 不参与决策。下钻结果回填所属功能需求条目（caller 把 subatoms 写入 item["drilled_subatoms"]）。
    """
    thresholds = thresholds or default_thresholds()
    text = " ".join(
        str(section.get(k) or item.get(k) or "")
        for k in ("heading", "text", "source_quote")
    )
    signals = [
        multi_behavior_signal(text, threshold=thresholds["multi_behavior"]),
        multi_condition_signal(text, threshold=thresholds["multi_condition"]),
        parameter_matrix_signal(section, threshold=thresholds["matrix_rows"], table_items=table_items),
        ambiguity_signal(item),
        conflict_signal(item),
        review_challenge_signal(review_state),
    ]
    drill = any(bool(signal.get("fired")) for signal in signals)
    subatoms = _split_to_subatoms(section) if drill else []
    return {
        "version": FUNCTIONAL_DRILLDOWN_VERSION,
        "drill": drill,
        "signals": signals,
        "subatom_count": len(subatoms),
        "subatoms": subatoms,
    }


def apply_drilldown(
    items: Sequence[dict[str, Any]],
    sections_by_id: dict[str, dict[str, Any]] | Callable[[dict[str, Any]], dict[str, Any] | None] | None,
    *,
    thresholds: dict[str, int] | None = None,
    table_items: Sequence[dict[str, Any]] | None = None,
    review_states_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """对一批功能需求条目批量判定下钻，回填 ``drilled_subatoms`` 到每条 item。

    ``sections_by_id`` 可以是"item → 来源条款"的映射或回调；review_states_by_id 按
    functional_requirement_id 提供评审状态（缺省视为无质疑）。返回汇总报告。
    """
    resolve_section = sections_by_id
    if isinstance(sections_by_id, dict):
        resolve_section = lambda item, _m=sections_by_id: _m.get(str(item.get("functional_requirement_id") or ""))  # noqa: E731
    drilled_count = 0
    total_subatoms = 0
    decisions: list[dict[str, Any]] = []
    for item in items:
        section = resolve_section(item) if resolve_section else None
        review_state = None
        if review_states_by_id is not None:
            review_state = review_states_by_id.get(
                str(item.get("functional_requirement_id") or "")
            )
        if section is None:
            # 无来源条款则无法下钻（直抽已保证每条 item 有来源；防御）
            continue
        decision = decide_drilldown(
            item, section,
            thresholds=thresholds, table_items=table_items, review_state=review_state,
        )
        if decision["drill"]:
            item["drilled_subatoms"] = decision["subatoms"]
            item["drilldown_signals"] = [s["name"] for s in decision["signals"] if s.get("fired")]
            drilled_count += 1
            total_subatoms += decision["subatom_count"]
        decisions.append({
            "functional_requirement_id": str(item.get("functional_requirement_id") or ""),
            "drill": decision["drill"],
            "signals": [s["name"] for s in decision["signals"] if s.get("fired")],
            "subatom_count": decision["subatom_count"],
        })
    return {
        "version": FUNCTIONAL_DRILLDOWN_VERSION,
        "item_count": len(items),
        "drilled_count": drilled_count,
        "total_subatoms": total_subatoms,
        "decisions": decisions,
    }
