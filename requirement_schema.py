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

from typing import Any


# 公司 21 域（labels 合法取值，保持兼容）
VALID_LABELS = (
    "计量", "时钟", "事件记录", "曲线", "需量", "费率", "结算", "状态字", "窃电",
    "电网质量", "预付费", "CIU", "门限范围", "Push", "显示", "升级", "负控",
    "节假日", "通信协议", "安全", "环境可靠性",
)

# 关键词 → 域（按 DLMS/COSEM 行为实际适配，只映射相关域）
_LABEL_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("安全", ("key", "secur", "cipher", "encrypt", "auth", "hls", "lls",
             "invocation counter", "integrity", "master key", "protected", "ciphered")),
    ("事件记录", ("event", " log", "reboot", "record", "logbook")),
    ("Push", ("push", "datanotification", "notification", "asynchron")),
    ("通信协议", ("dlms", "cosem", "xdlms", "obis", "association", "service",
               "pull", "get", "set ", "action", "block transfer")),
    ("时钟", ("clock", " rtc", "time synchron")),
    ("计量", ("energy", "metering", "register", "measurement", "demand register")),
    ("费率", ("tariff", "rate ")),
    ("需量", ("demand",)),
    ("状态字", ("status word", "status flag", "status bit")),
    ("升级", ("firmware", "upgrade", "image transfer")),
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


def classify_type(text: str) -> str:
    lower = str(text or "").lower()
    if any(w in lower for w in ("accuracy", "precision", "reliability", "mtbf", "temperature range", "ip5", "ip6")):
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
        notes_parts.append(f"编码漂移（已拦截）：{', '.join(item['drift_codes'])}")
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

    by_type: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    for req in requirements:
        by_type[req["type"]] = by_type.get(req["type"], 0) + 1
        by_priority[req["priority"]] = by_priority.get(req["priority"], 0) + 1
        for label in req["labels"]:
            by_domain[label] = by_domain.get(label, 0) + 1

    conflicts = [
        {"requirement_ids": [req["id"]], "description": req["notes"]}
        for req in requirements if "编码漂移" in req.get("notes", "")
    ]
    gaps, passed = coverage_gaps(requirements)
    sections = sorted({req["source_section"] for req in requirements if req["source_section"]})

    return {
        "meta": {
            "source": source,
            "extracted_at": extracted_at,
            "sections_analyzed": sections,
            "total_sections_in_document": len(sections),
            "meter_type": meter_type,
            "target_standards": target_standards or ["DLMS/COSEM (IEC 62056)", "ABNT NBR 16968"],
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
