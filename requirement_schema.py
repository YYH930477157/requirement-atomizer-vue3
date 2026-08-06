"""把内部行为模型映射到**公司标准需求列表格式**（meta / requirements / analysis）。

对齐公司 requirement-analyst-pro 的 schema（参考用，非接管其流水线）：
- requirements 每条带 id/title/description/type/priority/status/source_section/source_quote/
  threshold_table/acceptance_criteria/dependencies/parent/children/labels/notes
- labels 取自公司 21 域（保持兼容），但**按 DLMS/COSEM 协议 profile 适配映射**，不硬塞产品域
- analysis 含 by_type/by_priority/by_domain/conflicts/gaps/validation_result/coverage_report
- 13 条提取质量规则见 references/behavior_derivation_guide.md（指导 LLM 派生内容，本模块保证字段完备）

source_quote 恒非空、type/priority/status 不为 pending —— 满足公司校验底线。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any


# 公司 21 域（labels 合法取值，保持兼容）
VALID_LABELS = (
    "计量", "时钟", "事件记录", "曲线", "需量", "费率", "结算", "状态字", "窃电",
    "电网质量", "预付费", "CIU", "门限范围", "Push", "显示", "升级", "负控",
    "节假日", "通信协议", "安全", "环境可靠性",
)

# 关键词 → 域（按 DLMS/COSEM 对象名/行为实际适配）。
# 顺序即优先级：map_labels 按本表顺序收集所有命中标签，labels[0]（最特定的域）成为分段主标签，
# 因此特定域必须排在宽泛的「通信协议」之前；「通信协议」放最后，仅在没有更具体匹配时兜底
# （DLMS profile 里大量对象本就是对象模型/管理面，归「通信协议」是正确的，而非误分）。
_LABEL_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("安全", ("secur", " key", "key ", "cipher", "encrypt", "auth", "hls", "lls",
             "invocation counter", "integrity", "master key", "protected", "ciphered",
             "certificate", "esam")),
    ("升级", ("firmware", "image transfer", "image activation", "upgrade")),
    ("负控", ("disconnect", "relay", "load control", "limiter")),
    ("门限范围", ("threshold", "voltage sag", "voltage swell", "limit value")),
    ("节假日", ("special day", "holiday")),
    ("费率", ("tariff", "rate ", "activity calendar", "day profile", "week profile", "season")),
    ("结算", ("billing", "settlement", "end of billing", "mdi reset", "billing reset")),
    # 事件记录/状态字 必须排在「计量」之前：计量含 voltage/current/export 等宽词，
    # 而对象名里 current 常指「当前」、export 常出现在事件名里（假朋友），靠顺序让语义更强的
    # event/log/power failure/status 先赢，避免电压事件、失压时长被误判为计量。
    ("状态字", ("status word", "status flag", "status bit")),
    ("事件记录", ("event", "logbook", " log", "reboot", "power failure", "power down",
               "power up", "diagnostic", "error")),
    ("需量", ("demand",)),
    ("计量", ("energy", "metering", "register", "measurement", "active power", "reactive",
             "apparent", "instantaneous", "cumulative", " import", " export", " wh",
             "varh", "vah", "power factor", "voltage", "current", "frequency")),
    ("时钟", ("clock", " rtc", "time synchron", "time sync")),
    ("Push", ("push", "datanotification", "notification", "asynchron")),
    ("显示", ("display",)),
    ("通信协议", ("dlms", "cosem", "xdlms", "obis", "association", "sap", "logical device",
               "profile generic", "script", "schedule", "service", "pull", " get", "set ",
               "action", "block transfer", "hdlc", "tcp", "gprs", "ppp", "management", "reset")),
)

# 适配后的 DLMS/COSEM 行为覆盖清单（公司 20 项的协议 profile 子集）
COVERAGE_CHECKLIST = (
    "安全", "事件记录", "通信协议", "Push", "计量", "时钟", "费率", "升级", "需量", "状态字",
)


def map_labels(text: str) -> list[str]:
    lower = str(text or "").lower()
    labels = [label for label, kws in _LABEL_KEYWORDS if any(kw in lower for kw in kws)]
    # 去重保序
    seen: set[str] = set()
    result = [x for x in labels if not (x in seen or seen.add(x))]
    return result or ["通信协议"]


# 非功能触发词：性能/时序/可靠性/环境——泛词易误伤（"maximum"/"at least" 裸用会命中功能性逻辑），
# 故只取语义明确的整词；"至少 N 条记录"这类容量约束用正则单独匹配（见 _CAPACITY_PATTERN）。
_NON_FUNCTIONAL_TERMS = (
    "accuracy", "precision", "reliability", "mtbf", "failure rate",
    "temperature range", "ip5", "ip6",
    "response time", "latency", "timeout", "throughput",
)
# 容量/保留约束：at least / minimum / maximum 紧跟数字 + 计量名词（records/entries/periods/…）。
# 裸 "at least" 会误伤（"at least one association"=功能性），故限定为『量词 + 容量名词』模式。
_CAPACITY_PATTERN = re.compile(
    r"\b(?:at least|minimum of|max(?:imum)?(?:\s+of)?)\s+\d+\s+"
    r"(?:\w+\s+){0,3}"  # 容许修饰词：billing/load profile 等（at least 12 billing records）
    r"(?:records?|entries|periods|days?|intervals?|profiles?|objects?|associations?)\b",
    re.IGNORECASE,
)
# 明确的存储/容量表述（低误伤）
_CAPACITY_TERMS = ("storage capacity", "record retention", "retention period", "number of records")


def classify_type(text: str) -> str:
    lower = str(text or "").lower()
    if _CAPACITY_PATTERN.search(text or "") or any(w in lower for w in _NON_FUNCTIONAL_TERMS + _CAPACITY_TERMS):
        return "non_functional"
    if any(w in lower for w in ("shall not", "must not", "only be", "limited to", "reserved")):
        return "constraint"
    return "functional"


def classify_priority(labels: list[str], decision: str, confidence: Any) -> str:
    # 启发式且保守：行为类不因「安全」标签即判 P0（P0 留给 assemble_spec 的安全基础设施）；
    # 待审/低置信 → P2，需专家/需修订 → P1，其余默认 P1。最终优先级由专家复核。
    try:
        low_conf = confidence is not None and float(confidence) < 0.6
    except (TypeError, ValueError):
        low_conf = False
    if decision == "pending" or low_conf:
        return "P2"
    if decision in ("needs_expert", "revise"):
        return "P1"
    return "P1"


def map_status(decision: str) -> str:
    return "confirmed" if decision == "accept" else "draft"


def _source_section(item: dict[str, Any]) -> str:
    path = item.get("section_path") or []
    if isinstance(path, list) and path:
        return " / ".join(str(p) for p in path)
    refs = item.get("source_refs") or []
    return str(refs[0]) if refs else ""


def to_requirement(item: dict[str, Any], req_id: str) -> dict[str, Any]:
    decision = str(item.get("decision") or "pending")
    original = str(item.get("original") or "")
    derived = bool(item.get("derived"))
    behavior = str(item.get("behavior") or "")
    obj = str(item.get("object") or "")

    description = behavior if derived else (f"（待 LLM 审查）{original}" if original else obj)
    description = description or req_id
    source_quote = original or obj or "（原文缺失）"
    title = (obj or behavior or req_id).strip().replace("\n", " ")[:80]
    labels = map_labels(f"{original} {obj}")

    notes_parts = list(item.get("review_notes") or [])
    for q in item.get("expert_questions") or []:
        notes_parts.append(f"专家问题：{q}")
    if item.get("drift_codes"):
        notes_parts.append(f"编码漂移（已标记待核，文本保留）：{', '.join(item['drift_codes'])}")
    lower = original.lower()
    if any(kw in lower for kw in ("threshold", "limit", "at least", "records")) or \
            any(kw in original for kw in ("门限", "阈值", "记录")):
        notes_parts.append("相关门限/参数/容量表见对象模型(P1)与访问安全规格(P2)")
    notes_parts.append("type/priority/status 为启发式赋值，待专家确认")

    return {
        "id": req_id,
        "title": title,
        "description": description,
        "type": classify_type(original),
        "priority": classify_priority(labels, decision, item.get("confidence")),
        "status": map_status(decision),
        "source_section": _source_section(item),
        "source_quote": source_quote,
        "threshold_table": None,
        "acceptance_criteria": list(item.get("acceptance") or []),
        "dependencies": [],
        "parent": None,
        "children": [],
        "labels": labels,
        "notes": "；".join(notes_parts),
    }


def coverage_gaps(requirements: list[dict[str, Any]]) -> tuple[list[dict[str, str]], int]:
    present = {label for req in requirements for label in req.get("labels", [])}
    gaps = [
        {"domain": domain,
         "description": f"未发现『{domain}』相关行为需求，请核对原文是否遗漏",
         "suggested_requirement": ""}
        for domain in COVERAGE_CHECKLIST if domain not in present
    ]
    passed = len(COVERAGE_CHECKLIST) - len(gaps)
    return gaps, passed


def make_doc(
    requirements: list[dict[str, Any]],
    *,
    source: str,
    extracted_at: str,
    meter_type: str = "electric",
    target_standards: list[str] | None = None,
) -> dict[str, Any]:
    """从一组（任意层产出的）公司格式 requirement 装配整份文档：全局重编号 REQ-NNN + 重算 analysis。"""
    for i, req in enumerate(requirements, 1):
        req["id"] = f"REQ-{i:03d}"

    # 全部用 .get() 兜底：裸下标会在缺字段时 KeyError 崩掉整个 make_doc（进而整个 rebuild/装配
    # 任务，且只报 {"error": "'labels'"} 这类不透明信息）。裁决回流读原始 ai_requirements、或
    # 无裁决时跳过 ensure_domain_labels，都可能缺 labels/source_section；用户也可能手改该文件。
    # 默认值取 normalize_requirement 的同款默认（functional/P2），字段齐全时行为完全不变。
    by_type: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    for req in requirements:
        rtype = req.get("type") or "functional"
        priority = req.get("priority") or "P2"
        by_type[rtype] = by_type.get(rtype, 0) + 1
        by_priority[priority] = by_priority.get(priority, 0) + 1
        for label in req.get("labels") or []:
            by_domain[label] = by_domain.get(label, 0) + 1

    # 两条写入路径的 note 串不同：behavior-spec/P3 写「编码漂移（已标记待核…）」，
    # AI 抽取主路径写「结构漂移已拦截（编码…）」（原仅匹配前者 → 主路径 conflicts 恒空）。
    # 这里同时认两个标记串，让两种来源的编码漂移都进 conflicts/coverage_report。
    _DRIFT_MARKERS = ("编码漂移", "结构漂移已拦截")
    conflicts = [
        {"requirement_ids": [req["id"]], "description": req.get("notes", "")}
        for req in requirements if any(m in req.get("notes", "") for m in _DRIFT_MARKERS)
    ]
    gaps, passed = coverage_gaps(requirements)
    sections = sorted({s for req in requirements if (s := req.get("source_section"))})

    return {
        "meta": {
            "source": source,
            "extracted_at": extracted_at,
            "sections_analyzed": sections,
            "total_sections_in_document": len(sections),
            "meter_type": meter_type,
            "target_standards": target_standards or [],  # 空=未从文档推断出，不再写死电表标准；专家补
        },
        "requirements": requirements,
        "analysis": {
            "total_count": len(requirements),
            "by_type": by_type,
            "by_priority": by_priority,
            "by_domain": by_domain,
            "conflicts": conflicts,
            "gaps": gaps,
            "validation_result": {
                "original_re_read": True,
                "omissions_found": len(gaps),
                "omissions_fixed": 0,
                "domain_checklist_passed": passed,
                "domain_checklist_total": len(COVERAGE_CHECKLIST),
            },
            "coverage_report": (
                f"需求 {len(requirements)} 条，覆盖 {passed}/{len(COVERAGE_CHECKLIST)} 个适配域；"
                f"缺口 {len(gaps)} 项；编码漂移拦截 {len(conflicts)} 处。"
                "依赖/层级关系(parent/children/dependencies)待后续完善。"
            ),
        },
    }


def build_requirements_doc(
    model: dict[str, Any],
    *,
    source: str,
    extracted_at: str,
    meter_type: str = "electric",
    target_standards: list[str] | None = None,
) -> dict[str, Any]:
    requirements = [to_requirement(item, "REQ-TMP") for item in model["items"]]
    return make_doc(requirements, source=source, extracted_at=extracted_at,
                    meter_type=meter_type, target_standards=target_standards)


# ===========================================================================
# WS4 能力补齐：verification 子对象 + 四态状态机 + 手工入口 + 需求库 + 依赖推荐
# ---------------------------------------------------------------------------
# 本节是 WS4 六项能力的**纯域契约**（无 I/O）：定义 verification 子对象形状、
# 与导出 xlsx 六列的双向映射、确定性驱动的四态生命周期、手工录入记录构造、
# 需求库词面检索、依赖/父子候选的确定性推荐。共享状态文件的读写（锁 + 原子替换）
# 在 review_state.py；写入策略（reviewer_override 通道、CAS、回退留痕）在
# requirements_analysis_rules.py；消费侧在 requirements_analysis_excel.py /
# clarification_report.py / desktop_tasks.py / api_server.py。
# 全程零 LLM 调用——所有判定均为确定性代码。
# ===========================================================================

VERIFICATION_SCHEMA_VERSION = "verification-v1"

# implemented 枚举（功能是否实现列）
IMPLEMENTED_NOT_STARTED = "not_started"
IMPLEMENTED_IN_PROGRESS = "in_progress"
IMPLEMENTED_DONE = "done"
IMPLEMENTED_VALUES = (IMPLEMENTED_NOT_STARTED, IMPLEMENTED_IN_PROGRESS, IMPLEMENTED_DONE)
_IMPLEMENTED_LABELS_ZH = {
    IMPLEMENTED_NOT_STARTED: "未开始",
    IMPLEMENTED_IN_PROGRESS: "进行中",
    IMPLEMENTED_DONE: "已完成",
}
_IMPLEMENTED_LABEL_TO_VALUE = {
    "未开始": IMPLEMENTED_NOT_STARTED,
    "进行中": IMPLEMENTED_IN_PROGRESS,
    "已完成": IMPLEMENTED_DONE,
    "done": IMPLEMENTED_DONE,
    "complete": IMPLEMENTED_DONE,
    "completed": IMPLEMENTED_DONE,
}

# 三个确认位角色（与六列前三列一一对应：项目负责人/测试负责人/研发测试确认）
CONFIRM_ROLES = ("project_manager", "test_lead", "dev_test")
_CONFIRM_ROLE_LABELS = {
    "project_manager": "项目负责人",
    "test_lead": "测试负责人",
    "dev_test": "研发测试",
}

# 四态生命周期（与裁决层 candidate/accepted/rejected 正交）
LIFECYCLE_DRAFT = "draft"
LIFECYCLE_CONFIRMED = "confirmed"
LIFECYCLE_IMPLEMENTED = "implemented"
LIFECYCLE_VERIFIED = "verified"
LIFECYCLE_VALUES = (LIFECYCLE_DRAFT, LIFECYCLE_CONFIRMED, LIFECYCLE_IMPLEMENTED, LIFECYCLE_VERIFIED)
_LIFECYCLE_INDEX = {state: index for index, state in enumerate(LIFECYCLE_VALUES)}

# provenance 来源标记（手工入口新增 manual 取值，与 rule/llm/reviewer_override 并列）
PROVENANCE_RULE = "rule"
PROVENANCE_LLM = "llm"
PROVENANCE_REVIEWER_OVERRIDE = "reviewer_override"
PROVENANCE_MANUAL = "manual"
VERIFICATION_SOURCE = PROVENANCE_REVIEWER_OVERRIDE  # 状态写入挂人工覆盖通道


def confirm_triple(confirmed: bool = False, by: str = "", at: str = "") -> dict[str, Any]:
    """单个确认位：布尔 + 确认人 + 时间戳三元组。"""
    return {"confirmed": bool(confirmed), "by": str(by or ""), "at": str(at or "")}


def default_verification() -> dict[str, Any]:
    """全空的 verification 子对象（与六列一一对应、不扩张）。"""
    return {
        "project_manager_confirm": confirm_triple(),
        "test_lead_confirm": confirm_triple(),
        "dev_test_confirm": confirm_triple(),
        "implemented": IMPLEMENTED_NOT_STARTED,
        "test_case_ids": [],
        "test_completed": False,
    }


def _normalize_confirm(raw: Any) -> dict[str, Any]:
    """确认位宽容归一：dict 取三字段；裸 bool 直接用；非空标量=已确认（无确认人/时间）。"""
    if isinstance(raw, dict):
        return confirm_triple(raw.get("confirmed"), raw.get("by"), raw.get("at"))
    if isinstance(raw, bool):
        return confirm_triple(raw)
    if raw in (None, "", "False", "false", "0", 0):
        return confirm_triple()
    return confirm_triple(True)


def normalize_verification(value: Any) -> dict[str, Any]:
    """把任意/部分输入归一为结构完备的 verification 子对象。"""
    base = default_verification()
    if not isinstance(value, dict):
        return base
    for role in CONFIRM_ROLES:
        base[f"{role}_confirm"] = _normalize_confirm(value.get(f"{role}_confirm"))
    implemented = str(value.get("implemented") or "").strip()
    if implemented in IMPLEMENTED_VALUES:
        base["implemented"] = implemented
    elif implemented in _IMPLEMENTED_LABEL_TO_VALUE:
        base["implemented"] = _IMPLEMENTED_LABEL_TO_VALUE[implemented]
    tids = value.get("test_case_ids")
    if isinstance(tids, list):
        base["test_case_ids"] = [str(item).strip() for item in tids if str(item).strip()]
    elif tids not in (None, ""):
        base["test_case_ids"] = [str(tids).strip()] if str(tids).strip() else []
    base["test_completed"] = bool(value.get("test_completed"))
    return base


def _confirm_cell(triple: dict[str, Any]) -> str:
    """确认位 → xlsx 单元格：未确认空串；已确认渲染「已确认（确认人 时间）」。"""
    if not triple.get("confirmed"):
        return ""
    person = str(triple.get("by") or "").strip() or "已确认"
    timestamp = str(triple.get("at") or "").strip()
    return f"已确认（{person}{' ' + timestamp if timestamp else ''}）"


def verification_excel_columns(verification: Any) -> tuple[str, str, str, str, str, str]:
    """verification 子对象 → xlsx 六列值（与 HEADERS[10:16] 一一对应、不扩张）。

    顺序：项目负责人确认 / 测试负责人确认 / 研发测试确认 / 功能是否实现 / 测试用例号 / 测试是否完成。
    列位与样式由 requirements_analysis_excel.py 保持不变，本函数只产单元格文本。
    """
    ver = normalize_verification(verification)
    cols = [_confirm_cell(ver[f"{role}_confirm"]) for role in CONFIRM_ROLES]
    cols.append(_IMPLEMENTED_LABELS_ZH[ver["implemented"]])
    cols.append("; ".join(ver["test_case_ids"]))
    cols.append("是" if ver["test_completed"] else "")
    return tuple(cols)  # type: ignore[return-value]


# 解析回灌时宽松识别「已确认」——任何非空单元格都视为已确认，尽量提取确认人/时间。
_CONFIRM_PERSON_RE = re.compile(r"已确认[（(]\s*([^)）]*?)\s*[)）]")


def _parse_confirm_cell(cell: Any, *, actor_fallback: str = "") -> dict[str, Any]:
    text = str(cell or "").strip()
    if not text or text in ("否", "未确认", "no", "N", "n", "False", "false"):
        return confirm_triple()
    person = actor_fallback
    timestamp = ""
    match = _CONFIRM_PERSON_RE.search(text)
    if match:
        remainder = match.group(1).strip()
        parts = remainder.rsplit(" ", 1)
        if len(parts) == 2 and _looks_like_timestamp(parts[1]):
            person, timestamp = parts[0] or actor_fallback, parts[1]
        else:
            person = remainder or actor_fallback
    elif text not in ("是", "已确认", "yes", "Y", "y", "True", "true", "1"):
        # 自由文本签名（如仅写姓名）——整段当确认人
        person = text
    return confirm_triple(True, person, timestamp)


_TIMESTAMP_HINT_RE = re.compile(r"\d{4}|T\d|:\d{2}|^\d")


def _looks_like_timestamp(text: str) -> bool:
    return bool(_TIMESTAMP_HINT_RE.search(text or ""))


def parse_verification_columns(
    cells: Any,
    *,
    actor_fallback: str = "",
) -> dict[str, Any]:
    """xlsx 六列单元格 → verification 子对象（回灌解析，与 verification_excel_columns 对偶）。

    ``cells`` 为六列的值（list/tuple，顺序同 HEADERS[10:16]）。确认列宽松：非空=已确认。
    """
    values = list(cells) if isinstance(cells, (list, tuple)) else [cells]
    while len(values) < 6:
        values.append("")
    pm, tl, dt, implemented_cell, tids_cell, done_cell = values[:6]
    verification = default_verification()
    verification["project_manager_confirm"] = _parse_confirm_cell(pm, actor_fallback=actor_fallback)
    verification["test_lead_confirm"] = _parse_confirm_cell(tl, actor_fallback=actor_fallback)
    verification["dev_test_confirm"] = _parse_confirm_cell(dt, actor_fallback=actor_fallback)
    impl_text = str(implemented_cell or "").strip()
    verification["implemented"] = _IMPLEMENTED_LABEL_TO_VALUE.get(
        impl_text, _IMPLEMENTED_LABEL_TO_VALUE.get(impl_text.lower(), IMPLEMENTED_NOT_STARTED)
    )
    if impl_text in IMPLEMENTED_VALUES:
        verification["implemented"] = impl_text
    tids_raw = str(tids_cell or "").strip()
    verification["test_case_ids"] = [item.strip() for item in re.split(r"[;\n,、 ]+", tids_raw) if item.strip()]
    done_text = str(done_cell or "").strip()
    verification["test_completed"] = done_text in ("是", "yes", "Y", "y", "true", "True", "1", "已完成", "done")
    return verification


def derived_lifecycle(verification: Any) -> str:
    """前进生命周期——纯由 verification 字段确定性派生（LLM 不参与状态判定）。

    draft → confirmed（三确认位全部确认）→ implemented（implemented==done）→ verified（test_completed）。
    回退不由本函数产生（仅人工触发，见 requirements_analysis_rules.rollback_requirement_lifecycle）。
    """
    ver = normalize_verification(verification)
    if not all(ver[f"{role}_confirm"]["confirmed"] for role in CONFIRM_ROLES):
        return LIFECYCLE_DRAFT
    if ver["implemented"] != IMPLEMENTED_DONE:
        return LIFECYCLE_CONFIRMED
    if not ver["test_completed"]:
        return LIFECYCLE_IMPLEMENTED
    return LIFECYCLE_VERIFIED


def advance_lifecycle(current_state: str, verification: Any) -> str:
    """应用一次 verification 更新后的生命周期：取「当前态」与「派生态」的较高者。

    永不自动降级（自动降级不存在）：派生值低于当前态时保留当前态；只有显式人工回退才下降。
    """
    current_index = _LIFECYCLE_INDEX.get(str(current_state or LIFECYCLE_DRAFT), 0)
    derived_index = _LIFECYCLE_INDEX[derived_lifecycle(verification)]
    return LIFECYCLE_VALUES[max(current_index, derived_index)]


def lifecycle_rank(state: str) -> int:
    return _LIFECYCLE_INDEX.get(str(state or LIFECYCLE_DRAFT), 0)


# --- 需求内容指纹（CAS：verification 回写绑定到特定需求内容版本）--------------
# 只取稳定识别字段（子模块/描述/来源章节）。**刻意不含 requirement/software_requirement_text**：
# 导出 col5 是 clarify_display_text 渲染结果（待澄清时多行），与 item["requirement"] 不一致，
# 进 CAS 会让待澄清条目回灌永远 false-stale。CAS 只比对稳定身份，渲染字段不参与。
_REQUIREMENT_FINGERPRINT_FIELDS = ("submodule", "description", "source_section")


def _fingerprint_text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return " ".join(str(item) for item in value)
    return str(value or "")


_FINGERPRINT_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _fingerprint_normalize(value: Any) -> str:
    """指纹归一：去控制字符 + 折叠空白 + 小写。使 xlsx 单元格（经 _safe_cell 剥控制字符）
    与原始 item 字段产生相同指纹，CAS 不因无害字符差异误判 stale。"""
    text = _fingerprint_text(value)
    text = _FINGERPRINT_CTRL_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text


def requirement_content_fingerprint(item: dict[str, Any]) -> str:
    """需求的稳定内容指纹：用于 verification CAS——需求重新生成后内容漂移则失配。

    取分析项/功能需求都有的稳定识别字段（子模块/描述/需求正文/来源章节），归一后 sha1。
    """
    parts = [_fingerprint_normalize(item.get(field)) for field in _REQUIREMENT_FINGERPRINT_FIELDS]
    # 功能需求形态（无 submodule/requirement，有 objective/behaviors）的兼容补充
    if not any(parts):
        parts = [
            _fingerprint_normalize(item.get("objective")),
            _fingerprint_normalize(item.get("behaviors")),
            _fingerprint_normalize(item.get("title")),
        ]
    payload = "\x1f".join(parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def fingerprint_from_cells(
    submodule: Any, description: Any, source_section: Any,
) -> str:
    """从 xlsx 行单元格构造内容指纹（与 requirement_content_fingerprint 同归一），供回灌 CAS。

    只取稳定识别列（子模块/描述/客户需求章节）；刻意不取「需求」列——它是渲染字段，
    待澄清时为多行串，进 CAS 会让待澄清条目永远 false-stale。
    """
    return requirement_content_fingerprint({
        "submodule": submodule,
        "description": description,
        "source_section": source_section,
    })


def requirement_identity(item: dict[str, Any]) -> str:
    """需求的稳定主键：优先 functional_requirement_id（内容哈希稳定），回退 analysis_id。"""
    for key in ("functional_requirement_id", "analysis_id", "id"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    # 兜底：内容指纹保证唯一性
    return "REQ-" + requirement_content_fingerprint(item)[:12]


# --- 手工建需求入口（数据面）------------------------------------------------
MANUAL_MODULE_DEFAULT = "手工录入"


def _manual_description(objective: str, behaviors: list[str]) -> str:
    parts = [f"目标：{objective}"] if objective else []
    if behaviors:
        parts.append("行为：" + "；".join(behaviors))
    if not parts:
        parts.append("（手工录入需求，待补充目标与行为）")
    parts.append("来源：手工录入（无文档来源，追溯列以空明示）")
    return "\n".join(parts)


def build_manual_requirement(
    *,
    objective: str,
    behaviors: Any = None,
    module: str = "",
    ownership: str = "",
    priority: str = "P1",
    notes: str = "",
    actor: str = "",
    requirement_id: str = "",
) -> dict[str, Any]:
    """构造一条手工录入的功能需求记录（provenance=manual，source_quote/source_block_ids 留空不伪引）。

    手工条目走完全相同下游：归属/conflict_flags/澄清/导出/状态机。UI 留给 WS-F，本函数只产数据。
    """
    behavior_list = [str(item).strip() for item in (behaviors or []) if str(item).strip()]
    text = " ".join([str(objective or ""), *behavior_list])
    stable = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    frid = str(requirement_id or f"FREQ-MANUAL-{stable}").strip()
    return {
        "functional_requirement_id": frid,
        "functional_key": f"manual:{_simple_normalize(objective)}",
        "title": str(objective or "手工录入需求").strip().replace("\n", " ")[:80],
        "objective": str(objective or "").strip(),
        "behaviors": behavior_list,
        "lifecycle_behaviors": [],
        "source_modules": [module] if module else [],
        "preconditions": [],
        "data_constraints": [],
        "variants": [],
        "exceptions": [],
        "related_dlms_objects": [],
        "description": _manual_description(str(objective or "").strip(), behavior_list),
        "module": str(module or MANUAL_MODULE_DEFAULT).strip(),
        "type": "functional",
        "priority": str(priority or "P1"),
        "labels": map_labels(text) or ["通信协议"],
        "source_ai_requirement_ids": [],
        "source_block_ids": [],
        "source_quotes": [],
        "source_sections": [],
        "source_quote": "",   # 留空不伪引原文
        "source_section": "",  # 无文档来源
        "evidence": [],
        "developer_guidance": [],
        "design_options": [],
        "acceptance_criteria": [],
        "assumptions": [],
        "ownership_override": str(ownership or "").strip(),
        "merge_method": "manual",
        "merge_confidence": 1.0,
        "synthesis_reason": "手工录入需求（无文档来源）",
        "conflict_flags": [],
        "source_kind": PROVENANCE_MANUAL,
        "notes": str(notes or ""),
        "manual_actor": str(actor or ""),
    }


def _simple_normalize(value: Any) -> str:
    return re.sub(r"[^0-9a-z一-鿿]+", "", str(value or "").casefold())


# --- 需求库词面检索（Cap5）--------------------------------------------------
_LIBRARY_SCHEMA = "requirement-library/v1"

_TOKEN_RE = re.compile(r"[0-9a-z]+|[一-鿿]+", re.IGNORECASE)
# 中文单字过多会制造海量噪声 token——CJK 只取连续 ≥2 字的段作为词面（粗分词，宁漏勿错）
_CJK_RUN_RE = re.compile(r"[一-鿿]+")
_LIB_STOPWORDS = frozenset({
    "the", "a", "an", "of", "for", "and", "to", "in", "on", "shall", "must", "should",
    "be", "is", "are", "with", "by", "or", "as", "at", "per", "when", "that", "this",
    "需求", "要求", "功能", "支持", "应", "必须", "可", "及", "与", "和", "或",
})


def tokenize_requirement(text: Any) -> set[str]:
    """词面分词集合（拉丁整词 + 中文 ≥2 字连续段）。明确不引入向量检索与 LLM 相似度。"""
    raw = str(text or "").casefold()
    tokens: set[str] = set()
    for match in _TOKEN_RE.findall(raw):
        token = match.casefold()
        if token not in _LIB_STOPWORDS and len(token) >= 2:
            tokens.add(token)
    # 中文段切 2-gram，避免整段长串无重叠
    for run in _CJK_RUN_RE.findall(raw):
        for index in range(len(run) - 1):
            tokens.add(run[index:index + 2])
        if len(run) >= 2:
            tokens.add(run)
    return {token for token in tokens if token}


def library_entry_from_requirement(
    item: dict[str, Any],
    *,
    project: str,
    doc_source: str,
    created_at: str,
) -> dict[str, Any]:
    """把一条功能需求拍平为带项目元数据的检索库条目（JSONL，沿用既有惯例，不引入数据库）。"""
    ownership = str(item.get("ownership_override") or item.get("ownership") or "").strip()
    objective = str(item.get("objective") or item.get("title") or "").strip()
    behaviors = [str(b).strip() for b in (item.get("behaviors") or []) if str(b).strip()]
    return {
        "schema": _LIBRARY_SCHEMA,
        "project": str(project or ""),
        "doc_source": str(doc_source or ""),
        "created_at": str(created_at or ""),
        "functional_requirement_id": str(item.get("functional_requirement_id") or requirement_identity(item)),
        "objective": objective,
        "behaviors": behaviors,
        "module": str(item.get("module") or ""),
        "ownership": ownership,
        "ownership_corrected": bool(item.get("ownership_override") or item.get("ownership_source") == PROVENANCE_REVIEWER_OVERRIDE),
        "source_kind": str(item.get("source_kind") or ""),
        "title": str(item.get("title") or objective)[:120],
        "tokens": sorted(tokenize_requirement(f"{objective} {' '.join(behaviors)}")),
    }


def search_requirement_library(
    query_text: str,
    library: list[dict[str, Any]],
    *,
    limit: int = 20,
    min_overlap: int = 1,
) -> list[dict[str, Any]]:
    """词面集合重叠度召回历史相似需求（Jaccard）。reviewer_override 修正过的归属优先展示。

    召回率低但精确率可控、零幻觉风险——明确不引入向量检索与 LLM 相似度判定。
    """
    query_tokens = tokenize_requirement(query_text)
    if not query_tokens:
        return []
    scored: list[tuple[float, bool, str, dict[str, Any]]] = []
    for entry in library:
        entry_tokens = set(entry.get("tokens") or [])
        if not entry_tokens:
            entry_tokens = tokenize_requirement(
                f"{entry.get('objective')} {' '.join(entry.get('behaviors') or [])}"
            )
        intersection = query_tokens & entry_tokens
        if len(intersection) < min_overlap:
            continue
        union = query_tokens | entry_tokens
        score = len(intersection) / len(union) if union else 0.0
        if score <= 0.0:
            continue
        # reviewer_override 修正过的归属结论优先展示（次要排序键，同分时靠前）
        corrected = bool(entry.get("ownership_corrected"))
        title = str(entry.get("title") or entry.get("objective") or "")
        scored.append((score, corrected, title, entry))
    # 主键 score 降序；修正优先；标题稳定排序
    scored.sort(key=lambda row: (-row[0], 0 if row[1] else 1, row[2]))
    results = []
    for score, corrected, _title, entry in scored[:limit]:
        rendered = {key: value for key, value in entry.items() if key != "tokens"}
        rendered["overlap_score"] = round(score, 4)
        results.append(rendered)
    return results


# --- dependencies/parent/children 半自动推荐（Cap6）------------------------
DEPENDENCY_DEPEND = "depend"
DEPENDENCY_EXCLUDE = "exclude"
DEPENDENCY_REFINE = "refine"
DEPENDENCY_KINDS = (DEPENDENCY_DEPEND, DEPENDENCY_EXCLUDE, DEPENDENCY_REFINE)

_OBIS_PATTERN = re.compile(r"\b\d+-\d+:[0-9.*xX]+(?:\.[0-9.*xX]+){1,4}\b")


def _related_obis_codes(item: dict[str, Any]) -> set[str]:
    """从 related_dlms_objects / 源文里确定性提取 OBIS 码集合。"""
    codes: set[str] = set()
    for value in (item.get("related_dlms_objects") or []):
        codes.update(_OBIS_PATTERN.findall(str(value)))
    for field in ("source_quote", "description", "requirement", "title", "objective"):
        codes.update(_OBIS_PATTERN.findall(str(item.get(field) or "")))
    return codes


def _section_key(item: dict[str, Any]) -> str:
    section = item.get("source_section")
    if isinstance(section, (list, tuple)):
        return " / ".join(str(value).strip() for value in section if str(value).strip())
    return str(section or "").strip()


def _section_adjacent(a: str, b: str) -> bool:
    """同一或相邻 source_section（粗判：前缀共享末级章节，或数字编号相邻）。"""
    if not a or not b:
        return False
    if a == b:
        return True
    # 末级数字编号相邻（如 4.1.2 / 4.1.3）
    a_parts = re.findall(r"\d+", a)
    b_parts = re.findall(r"\d+", b)
    if len(a_parts) >= 2 and len(b_parts) >= 2 and a_parts[:-1] == b_parts[:-1]:
        try:
            return abs(int(a_parts[-1]) - int(b_parts[-1])) == 1
        except ValueError:
            return False
    # 前缀共享（去掉末级后相同章节）
    return a.rsplit(".", 1)[0] == b.rsplit(".", 1)[0] and a.rsplit(".", 1)[0] != a


def recommend_dependency_candidates(
    requirements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """不动 schema（dependencies/parent/children 字段已存在），只生产候选值。

    两个确定性信号源：related_dlms_objects 引用同一 OBIS 码 → 依赖/互斥候选；
    同一或相邻 source_section → 细化候选。候选由专家接受后才写库，拒绝不落库。
    """
    candidates: list[dict[str, Any]] = []
    seen: set[frozenset[str]] = set()
    for index, a in enumerate(requirements):
        id_a = requirement_identity(a)
        obis_a = _related_obis_codes(a)
        section_a = _section_key(a)
        for b in requirements[index + 1:]:
            id_b = requirement_identity(b)
            if id_a == id_b:
                continue
            pair = frozenset((id_a, id_b))
            obis_b = _related_obis_codes(b)
            shared_obis = sorted(obis_a & obis_b)
            if shared_obis:
                # 同 OBIS 既可能是依赖也可能是互斥——专家裁决，两者并列为候选
                for kind in (DEPENDENCY_DEPEND, DEPENDENCY_EXCLUDE):
                    key = frozenset((id_a, id_b, kind))
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append({
                        "from": id_a, "to": id_b, "kind": kind,
                        "signal": "shared_obis", "evidence": shared_obis[:6],
                    })
            if _section_adjacent(section_a, _section_key(b)):
                key = frozenset((id_a, id_b, DEPENDENCY_REFINE))
                if key in seen:
                    continue
                seen.add(key)
                # 细化方向：标题更短/更泛者为父，更具体者为子
                parent, child = (id_a, id_b) if len(str(a.get("title") or "")) <= len(str(b.get("title") or "")) else (id_b, id_a)
                candidates.append({
                    "from": parent, "to": child, "kind": DEPENDENCY_REFINE,
                    "signal": "adjacent_section",
                    "evidence": sorted({section_a, _section_key(b)}),
                })
    return candidates
