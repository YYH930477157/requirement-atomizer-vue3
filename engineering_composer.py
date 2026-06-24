"""Compose atomized requirements into developer-facing engineering requirements.

The atomizer deliberately keeps requirements small for review and traceability.
This module restores implementation context without changing atomization output:

- requirement functions are grouped by domain and nearby document context
- DLMS objects are sourced from the deterministic COSEM object model
"""
from __future__ import annotations

import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any

from cosem_object_model import build_object_model


FUNCTION_REQUIREMENT_TYPES = {
    "functional",
    "communication",
    "event_definition",
    "event_group_retention",
    "capability_matrix",
    "association_security_matrix",
}
OUTPUT_DIR = "engineering_requirements"
WEAK_OBJECT_TOPICS = {
    "at",
    "there",
    "these",
    "this",
    "value",
    "key",
    "reset",
    "period",
    "collection",
    "register",
    "object",
    "secure",
    "during o",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def compose_engineering_requirements(out_dir: Path) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    atomic_rows = read_jsonl(out_dir / "atomic_requirements.jsonl")
    object_model = build_object_model(out_dir)

    dlms_objects = _compose_dlms_objects(object_model, atomic_rows)
    functions = _compose_requirement_functions(atomic_rows, dlms_objects)
    _link_functions_to_objects(functions, dlms_objects)

    return {
        "meta": {
            "source_out_dir": str(out_dir),
            "composition": "engineering_requirement_composer",
            "output_sections": ["requirement_functions", "dlms_objects"],
        },
        "requirement_functions": functions,
        "dlms_objects": dlms_objects,
        "analysis": {
            "requirement_functions": len(functions),
            "dlms_objects": len(dlms_objects),
            "orphan_dlms_attributes": object_model.get("counts", {}).get("orphan_attributes", 0),
            "source_atomic_requirements": len(atomic_rows),
        },
    }


def write_engineering_requirements(out_dir: Path, model: dict[str, Any]) -> list[str]:
    target_dir = out_dir.expanduser().resolve() / OUTPUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    json_path = target_dir / "engineering_requirements.json"
    functions_md = target_dir / "requirement_functions.md"
    objects_md = target_dir / "dlms_objects.md"

    json_path.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    functions_md.write_text(render_requirement_functions_markdown(model), encoding="utf-8")
    objects_md.write_text(render_dlms_objects_markdown(model), encoding="utf-8")

    return [
        f"{OUTPUT_DIR}/engineering_requirements.json",
        f"{OUTPUT_DIR}/requirement_functions.md",
        f"{OUTPUT_DIR}/dlms_objects.md",
    ]


def render_requirement_functions_markdown(model: dict[str, Any]) -> str:
    lines = ["# 研发需求功能", ""]
    by_domain: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for item in model.get("requirement_functions", []):
        by_domain.setdefault(str(item.get("domain") or "其它"), []).append(item)

    for domain, items in by_domain.items():
        lines.extend([f"## {domain}", ""])
        for item in items:
            lines.extend([
                f"### {item['id']} {item['title']}",
                "",
                str(item.get("description") or ""),
                "",
                f"- 相关 DLMS 对象：{_join_or_dash(item.get('related_dlms_objects'))}",
                f"- 原子需求：{_join_or_dash(item.get('source_atomic_requirements'))}",
                f"- 来源：{_join_or_dash(item.get('source_refs'))}",
                "",
            ])
            constraints = item.get("constraints") or []
            if constraints:
                lines.append("- 约束：" + "；".join(str(x) for x in constraints))
                lines.append("")
            questions = item.get("open_questions") or []
            if questions:
                lines.append("- 待澄清：" + "；".join(str(x) for x in questions))
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_dlms_objects_markdown(model: dict[str, Any]) -> str:
    lines = ["# DLMS 对象", ""]
    for item in model.get("dlms_objects", []):
        lines.extend([
            f"## {item['id']} {item['object_name']}",
            "",
            f"- OBIS：{item.get('obis') or '-'}",
            f"- Interface class：{item.get('class_id') or '-'}",
            f"- 关联功能：{_join_or_dash(item.get('related_functions'))}",
            f"- 原子需求：{_join_or_dash(item.get('source_atomic_requirements'))}",
            f"- 来源：{_join_or_dash(item.get('source_refs'))}",
            "",
        ])
        attrs = item.get("attributes") or []
        if attrs:
            lines.extend([
                "| # | 属性 | 类型 | 访问权限 | 默认值 |",
                "|---|---|---|---|---|",
            ])
            for attr in attrs:
                lines.append(
                    "| "
                    + " | ".join([
                        _md_cell(attr.get("index")),
                        _md_cell(attr.get("name")),
                        _md_cell(attr.get("type")),
                        _md_cell(attr.get("access_rights")),
                        _md_cell(attr.get("default")),
                    ])
                    + " |"
                )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _compose_requirement_functions(
    atomic_rows: list[dict[str, Any]],
    dlms_objects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    known_object_names = [str(obj.get("object_name") or "") for obj in dlms_objects]
    grouped: OrderedDict[tuple[str, str, str], dict[str, Any]] = OrderedDict()
    for row in atomic_rows:
        if row.get("requirement_type") not in FUNCTION_REQUIREMENT_TYPES:
            continue
        rid = _row_id(row)
        text = str(row.get("requirement") or row.get("object") or rid)
        domain = _domain_label(row)
        title = _semantic_title(row) or _context_title(row) or _title_from_text(text, row)
        topic = _function_topic(row, known_object_names)
        key = (domain, title.lower(), topic.lower())
        related_objects = _related_object_names(row, known_object_names)

        item = grouped.setdefault(key, {
            "id": "FUNC-TMP",
            "title": title,
            "domain": domain,
            "description": "",
            "functional_details": [],
            "constraints": [],
            "source_atomic_requirements": [],
            "source_refs": [],
            "related_dlms_objects": [],
            "acceptance_criteria": [],
            "open_questions": [],
        })
        if text and text not in item["functional_details"]:
            item["functional_details"].append(text)
        _append_unique(item["source_atomic_requirements"], rid)
        _extend_unique(item["source_refs"], row.get("source_refs") or [])
        _extend_unique(item["related_dlms_objects"], related_objects)
        _extend_unique(item["constraints"], _constraints(row))
        _extend_unique(item["open_questions"], _open_questions(row))

    functions = list(grouped.values())
    for index, item in enumerate(functions, 1):
        item["id"] = f"FUNC-{index:03d}"
        item["description"] = _function_description(item)
    return functions


def _compose_dlms_objects(object_model: dict[str, Any], atomic_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_ids_by_object = _source_ids_by_object(atomic_rows, {obj["object"] for obj in object_model.get("objects", [])})
    objects: list[dict[str, Any]] = []
    for source in object_model.get("objects", []):
        source_refs: list[str] = []
        _extend_unique(source_refs, source.get("source_refs") or [])
        for attr in source.get("attributes") or []:
            _extend_unique(source_refs, attr.get("source_refs") or [])

        objects.append({
            "id": f"DLMS-{len(objects) + 1:03d}",
            "object_name": str(source.get("object") or ""),
            "class_id": str(source.get("class_id") or ""),
            "obis": str(source.get("obis") or ""),
            "attributes": [_attribute_from_model(attr) for attr in source.get("attributes") or []],
            "methods": [],
            "access_rights": {},
            "mandatory": _infer_mandatory_from_model(source),
            "source_atomic_requirements": source_ids_by_object.get(str(source.get("object") or ""), []),
            "source_refs": source_refs,
            "related_functions": [],
            "open_questions": [],
        })
    return objects


def _source_ids_by_object(atomic_rows: list[dict[str, Any]], known_objects: set[str]) -> dict[str, list[str]]:
    source_ids: dict[str, list[str]] = {name: [] for name in known_objects}
    for row in atomic_rows:
        requirement_type = row.get("requirement_type")
        if requirement_type == "cosem_object_instance":
            object_name = str(row.get("object") or "").strip()
        elif requirement_type == "cosem_attribute_access":
            object_name, _ = _split_object_attribute(row)
        else:
            continue
        if object_name in source_ids:
            _append_unique(source_ids[object_name], _row_id(row))
    return source_ids


def _attribute_from_model(attr: dict[str, Any]) -> dict[str, str]:
    return {
        "index": str(attr.get("index") or ""),
        "name": str(attr.get("name") or ""),
        "type": str(attr.get("type") or ""),
        "access_rights": str(attr.get("access_raw") or _format_access(attr.get("access") or {})),
        "default": str(attr.get("default") or ""),
    }


def _format_access(access: dict[str, Any]) -> str:
    parts = [str(access.get(key) or "") for key in ("RC", "PC", "SC", "LC")]
    return "/".join(parts).strip("/")


def _infer_mandatory_from_model(source: dict[str, Any]) -> str:
    text = f"{source.get('object') or ''} {source.get('meaning') or ''}".lower()
    if "optional" in text:
        return "optional"
    if "mandatory" in text:
        return "mandatory"
    return ""


def _link_functions_to_objects(functions: list[dict[str, Any]], objects: list[dict[str, Any]]) -> None:
    for obj in objects:
        object_name = str(obj.get("object_name") or "")
        obj["related_functions"] = [
            str(fn["id"])
            for fn in functions
            if object_name in fn.get("related_dlms_objects", [])
        ]


def _related_object_names(row: dict[str, Any], known_object_names: list[str]) -> list[str]:
    haystack = f"{row.get('object') or ''} {row.get('requirement') or ''}".lower()
    return [name for name in known_object_names if name and name.lower() in haystack]


def _split_object_attribute(row: dict[str, Any]) -> tuple[str, str]:
    raw = str(row.get("object") or "").strip()
    if "." in raw:
        object_name, attribute_name = raw.split(".", 1)
        return object_name.strip(), attribute_name.strip()
    return raw, ""


def _domain_label(row: dict[str, Any]) -> str:
    if row.get("requirement_type") in {"event_definition", "event_group_retention"}:
        return "事件记录"
    section = _context_title(row).lower()
    text = f"{row.get('domain') or ''} {row.get('object') or ''} {row.get('requirement') or ''} {section}".lower()
    if "security" in section or "security" in text:
        return "安全"
    mapping = (
        ("结算", ("billing", "settlement", "invoicing", "period")),
        ("时钟", ("time", "clock", "rtc")),
        ("事件记录", ("event", "log")),
        ("安全", ("security", "auth", "cipher", "key", "hls", "lls")),
        ("需量", ("demand",)),
        ("费率", ("tariff", "rate")),
        ("Push", ("push", "notification")),
        ("升级", ("firmware", "upgrade", "image transfer")),
        ("曲线", ("load profile", "mass memory", "collection", "capture period", "storage capacity")),
        ("计量", ("metering", "energy", "register", "measurement", "voltage", "current")),
        ("通信协议", ("dlms", "cosem", "xdlms", "association", "service")),
    )
    for label, keywords in mapping:
        if any(keyword in text for keyword in keywords):
            return label
    return "通信协议"


def _context_title(row: dict[str, Any]) -> str:
    path = row.get("section_path") or []
    if isinstance(path, list) and path:
        last = str(path[-1]).strip()
        cleaned = re.sub(r"^\d+(?:\.\d+)*\s+", "", last).strip()
        return (cleaned or last)[:80]
    return ""


def _semantic_title(row: dict[str, Any]) -> str:
    text = f"{row.get('object') or ''} {row.get('requirement') or ''}".lower()
    section = _context_title(row).lower()
    if row.get("requirement_type") == "event_definition" and (
        "secure" in text or "password" in text or "encryption" in text or "authentication" in text
    ):
        return "Security event definitions"
    if "billing" in text or "invoicing" in text or "billing" in section:
        return "Control of billing period"
    if "collection" in text or "mass memory" in text or "storage capacity" in text:
        return "Load profile collection and storage"
    if "security" in text or "cipher" in text or "key" in text or "security" in section:
        return "Security and key management"
    if section in {"20 control of", "control of"}:
        domain = _domain_label(row)
        return {
            "事件记录": "Event recording behavior",
            "计量": "Measurement data behavior",
            "结算": "Billing period behavior",
            "通信协议": "Protocol support behavior",
        }.get(domain, "")
    return ""


def _function_topic(row: dict[str, Any], known_object_names: list[str]) -> str:
    related = _related_object_names(row, known_object_names)
    if related:
        return "|".join(related)
    if row.get("requirement_type") == "event_definition":
        return _semantic_title(row) or "event definitions"
    obj = str(row.get("object") or "").strip().lower()
    if obj and obj not in WEAK_OBJECT_TOPICS:
        return obj
    return _context_title(row).lower()


def _function_description(item: dict[str, Any]) -> str:
    details = [str(detail) for detail in item.get("functional_details") or [] if str(detail)]
    if not details:
        return f"研发实现应覆盖 {item.get('title') or item.get('id')} 相关规范要求。"
    if len(details) == 1:
        return f"研发实现应覆盖以下规范要求：{details[0]}"
    joined = "；".join(details)
    return f"研发实现应将同一上下文中的 {len(details)} 条原子要求合并实现：{joined}"


def _constraints(row: dict[str, Any]) -> list[str]:
    constraints: list[str] = []
    if row.get("condition"):
        constraints.append(str(row["condition"]))
    if row.get("verification_method"):
        constraints.append(f"验证方式：{row['verification_method']}")
    return constraints


def _open_questions(row: dict[str, Any]) -> list[str]:
    questions: list[str] = []
    if row.get("ambiguity"):
        questions.append("原子需求存在歧义，需要专家确认")
    if row.get("confidence") is not None:
        try:
            if float(row["confidence"]) < 0.6:
                questions.append("抽取置信度较低，需要复核")
        except (TypeError, ValueError):
            pass
    return questions


def _title_from_text(text: str, row: dict[str, Any]) -> str:
    obj = str(row.get("object") or "").strip()
    base = obj or text
    base = " ".join(base.split())
    if len(base) > 72:
        base = base[:72].rstrip() + "..."
    return base or _row_id(row) or "未命名需求"


def _row_id(row: dict[str, Any]) -> str:
    return str(row.get("stable_req_id") or row.get("req_id") or row.get("requirement_id") or "").strip()


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    _extend_unique(result, values)
    return result


def _append_unique(values: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in values:
        values.append(text)


def _extend_unique(values: list[str], incoming: list[Any]) -> None:
    for item in incoming:
        _append_unique(values, item)


def _join_or_dash(values: Any) -> str:
    if not values:
        return "-"
    return "、".join(str(item) for item in values)


def _md_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")
