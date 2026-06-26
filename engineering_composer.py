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

from cosem_object_model import build_object_model, build_source_index, source_order_for_row
from requirement_kb import KnowledgeRepository
from requirement_kb.cli import default_kb_paths


FUNCTION_REQUIREMENT_TYPES = {
    "functional",
    "communication",
    "event_definition",
    "event_group_retention",
    "capability_matrix",
    "association_security_matrix",
    "cosem_object",
}
OUTPUT_DIR = "engineering_requirements"
MAX_OBJECT_TASK_ITEMS = 8
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
METHOD_NAMES = {
    "add_mask",
    "add_register",
    "capture",
    "connect",
    "delete_mask",
    "execute",
    "image_activate",
    "image_block_transfer",
    "image_transfer_initiate",
    "image_verify",
    "next_period",
    "push",
    "remote_connect",
    "remote_disconnect",
    "remove_function",
    "reset",
    "security activate",
    "set_function_status",
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
    source_index = build_source_index(read_jsonl(out_dir / "table_items.jsonl"))
    object_model = build_object_model(out_dir)
    kb_entry_index = _load_default_kb_entry_index()

    dlms_objects = _compose_dlms_objects(object_model, atomic_rows)
    functions = _compose_requirement_functions(atomic_rows, dlms_objects, kb_entry_index, source_index)
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
    by_module: OrderedDict[str, OrderedDict[str, list[dict[str, Any]]]] = OrderedDict()
    for item in model.get("requirement_functions", []):
        module = str(item.get("module") or "general")
        domain = str(item.get("domain") or "其它")
        by_module.setdefault(module, OrderedDict()).setdefault(domain, []).append(item)

    for module, domains in by_module.items():
        lines.extend([f"## Module: {module}", ""])
        for domain, items in domains.items():
            lines.extend([f"### {domain}", ""])
            for item in items:
                _append_function_markdown(lines, item, heading_level=4)
    return "\n".join(lines).rstrip() + "\n"


def _append_function_markdown(lines: list[str], item: dict[str, Any], *, heading_level: int) -> None:
    heading = "#" * heading_level
    lines.extend([
        f"{heading} {item['id']} {item['title']}",
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
    acceptance = item.get("acceptance_criteria") or []
    if acceptance:
        lines.append("- Acceptance criteria: " + "; ".join(str(x) for x in acceptance))
        lines.append("")
    spec = item.get("implementation_spec") or {}
    if spec:
        lines.append("- Implementation spec:")
        trigger = str(spec.get("trigger_or_input") or "").strip()
        if trigger:
            lines.append(f"  - Trigger/Input: {trigger}")
        event_handling = spec.get("event_handling") if isinstance(spec.get("event_handling"), dict) else {}
        if event_handling:
            lines.append("  - Event handling:")
            for key, label in (
                ("condition", "Condition"),
                ("recording_action", "Recording"),
                ("notification_action", "Notification"),
            ):
                value = str(event_handling.get(key) or "").strip()
                if value:
                    lines.append(f"    - {label}: {value}")
        event_retention = spec.get("event_retention") if isinstance(spec.get("event_retention"), dict) else {}
        event_subgroups = event_retention.get("subgroups") if isinstance(event_retention.get("subgroups"), list) else []
        if event_subgroups:
            lines.append("  - Event retention:")
            for subgroup in event_subgroups:
                if not isinstance(subgroup, dict):
                    continue
                subgroup_id = str(subgroup.get("subgroup") or "").strip()
                minimum_records = subgroup.get("minimum_records")
                event_scope = str(subgroup.get("event_scope") or "").strip()
                if subgroup_id and minimum_records:
                    suffix = f" ({event_scope})" if event_scope else ""
                    lines.append(f"    - {subgroup_id}: keep at least {minimum_records} records{suffix}")
        event_definitions = spec.get("event_definitions") if isinstance(spec.get("event_definitions"), dict) else {}
        event_rows = event_definitions.get("events") if isinstance(event_definitions.get("events"), list) else []
        if event_rows:
            lines.append("  - Event definitions:")
            for event in event_rows:
                if not isinstance(event, dict):
                    continue
                event_code = str(event.get("event_code") or "").strip()
                description = str(event.get("description") or "").strip()
                if event_code and description:
                    lines.append(f"    - {event_code}: {description}")
        billing_period = spec.get("billing_period") if isinstance(spec.get("billing_period"), dict) else {}
        if billing_period:
            lines.append("  - Billing period:")
            for key, label in (
                ("trigger", "Trigger"),
                ("minimum_records", "Minimum records"),
            ):
                value = str(billing_period.get(key) or "").strip()
                if value:
                    lines.append(f"    - {label}: {value}")
            for required_object in billing_period.get("required_objects") or []:
                lines.append(f"    - Required object: {required_object}")
        load_profile = spec.get("load_profile") if isinstance(spec.get("load_profile"), dict) else {}
        if load_profile:
            lines.append("  - Load profile:")
            for key, label in (
                ("collection_interval", "Collection interval"),
                ("storage_capacity", "Storage capacity"),
            ):
                value = str(load_profile.get(key) or "").strip()
                if value:
                    lines.append(f"    - {label}: {value}")
        capability_matrix = spec.get("capability_matrix") if isinstance(spec.get("capability_matrix"), dict) else {}
        actors = capability_matrix.get("actors") if isinstance(capability_matrix.get("actors"), dict) else {}
        if actors:
            lines.append("  - Capability matrix:")
            for actor, services in actors.items():
                joined = ", ".join(str(service) for service in services)
                lines.append(f"    - {actor}: {joined}")
        access_control_matrix = spec.get("access_control_matrix") if isinstance(spec.get("access_control_matrix"), dict) else {}
        access_actors = access_control_matrix.get("actors") if isinstance(access_control_matrix.get("actors"), dict) else {}
        if access_actors:
            lines.append("  - Access control matrix:")
            for actor, grants in access_actors.items():
                for grant in grants:
                    target = str(grant.get("target") or "").strip()
                    security_level = str(grant.get("security_level") or "").strip()
                    if target and security_level:
                        lines.append(f"    - {actor} -> {target}: {security_level}")
        security_policy = spec.get("security_policy") if isinstance(spec.get("security_policy"), dict) else {}
        if security_policy:
            lines.append("  - Security policy:")
            for key, label in (
                ("security_suite", "Security suite"),
                ("unprotected_clients", "Unprotected clients"),
                ("supported_keys", "Supported keys"),
                ("key_expiration", "Key expiration"),
                ("invocation_counters", "Invocation counters"),
            ):
                value = str(security_policy.get(key) or "").strip()
                if value:
                    lines.append(f"    - {label}: {value}")
        key_management = spec.get("key_management") if isinstance(spec.get("key_management"), dict) else {}
        if key_management:
            lines.append("  - Key management:")
            for key, label in (
                ("key_loading_integrity", "Key loading integrity"),
                ("protected_message_counters", "Protected message counters"),
            ):
                value = str(key_management.get(key) or "").strip()
                if value:
                    lines.append(f"    - {label}: {value}")
        _append_spec_list(lines, "Processing rules", spec.get("processing_rules") or [])
        _append_spec_list(lines, "DLMS object impact", spec.get("dlms_object_impact") or [])
        _append_spec_list(lines, "Error and boundary behavior", spec.get("error_and_boundary_behavior") or [])
        _append_spec_list(lines, "Acceptance checks", spec.get("acceptance_checks") or [])
        lines.append("")
    tasks = item.get("implementation_tasks") or []
    if tasks:
        lines.append("- Implementation tasks:")
        for task in tasks:
            lines.append(f"  - {task}")
        lines.append("")
    class_hints = item.get("class_hints") or []
    if class_hints:
        lines.append("- COSEM class hints:")
        for hint in class_hints:
            label = str(hint.get("name") or hint.get("entry_id") or "COSEM class")
            class_id = str(hint.get("class_id") or "").strip()
            suffix = f" (class {class_id})" if class_id else ""
            lines.append(f"  - {label}{suffix}")
            definition = str(hint.get("definition") or "").strip()
            if definition:
                lines.append(f"    - Definition: {definition}")
            for note in hint.get("behavior_notes") or []:
                lines.append(f"    - Behavior: {note}")
            for note in hint.get("access_semantics") or []:
                lines.append(f"    - Access: {note}")
        lines.append("")
    questions = item.get("open_questions") or []
    if questions:
        lines.append("- 待澄清：" + "；".join(str(x) for x in questions))
        lines.append("")


def render_dlms_objects_markdown(model: dict[str, Any]) -> str:
    lines = ["# DLMS objects", ""]
    for item in model.get("dlms_objects", []):
        lines.extend([
            f"## {item['id']} {item['object_name']}",
            "",
            f"- OBIS: {item.get('obis') or '-'}",
            f"- Interface class: {item.get('class_id') or '-'}",
            f"- Implementation summary: {item.get('implementation_summary') or '-'}",
            f"- Access summary: {item.get('access_summary') or '-'}",
            f"- Related functions: {_join_or_dash(item.get('related_functions'))}",
            f"- Atomic requirements: {_join_or_dash(item.get('source_atomic_requirements'))}",
            f"- Sources: {_join_or_dash(item.get('source_refs'))}",
            "",
        ])
        attrs = item.get("attributes") or []
        if attrs:
            lines.extend([
                "| # | Attribute | Type | Access rights | Default |",
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
        methods = item.get("methods") or []
        if methods:
            lines.extend([
                "| # | Method | Access rights |",
                "|---|---|---|",
            ])
            for method in methods:
                lines.append(
                    "| "
                    + " | ".join([
                        _md_cell(method.get("index")),
                        _md_cell(method.get("name")),
                        _md_cell(method.get("access_rights")),
                    ])
                    + " |"
                )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _compose_requirement_functions(
    atomic_rows: list[dict[str, Any]],
    dlms_objects: list[dict[str, Any]],
    kb_entry_index: dict[str, dict[str, Any]] | None = None,
    source_index: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    kb_entry_index = kb_entry_index or {}
    source_index = source_index or {}
    object_index = _dlms_object_index(dlms_objects)
    known_object_names = list(object_index["names"])
    grouped: OrderedDict[tuple[str, str, str, str], dict[str, Any]] = OrderedDict()
    for row in atomic_rows:
        if row.get("requirement_type") not in FUNCTION_REQUIREMENT_TYPES:
            continue
        if _is_low_information_function_row(row):
            continue
        rid = _row_id(row)
        text = str(row.get("requirement") or row.get("object") or rid)
        domain = _domain_label(row)
        module = _module_label(row, domain)
        title = _semantic_title(row) or _context_title(row) or _title_from_text(text, row)
        topic = _function_topic(row, object_index)
        key = (module, domain, title.lower(), topic.lower())
        class_hints = _class_hints(row, kb_entry_index)
        related_objects = _related_object_names(row, object_index)
        _extend_unique(related_objects, _related_object_names_from_source_context(row, object_index, source_index))

        item = grouped.setdefault(key, {
            "id": "FUNC-TMP",
            "title": title,
            "module": module,
            "domain": domain,
            "description": "",
            "functional_details": [],
            "constraints": [],
            "source_atomic_requirements": [],
            "source_refs": [],
            "related_dlms_objects": [],
            "class_hints": [],
            "implementation_tasks": [],
            "acceptance_criteria": [],
            "_row_acceptance_criteria": [],
            "open_questions": [],
        })
        text = _clean_requirement_detail(text)
        if text and text not in item["functional_details"]:
            item["functional_details"].append(text)
        _append_unique(item["source_atomic_requirements"], rid)
        _extend_unique(item["source_refs"], row.get("source_refs") or [])
        _extend_unique(item["related_dlms_objects"], related_objects)
        _merge_class_hints(item["class_hints"], class_hints)
        _extend_unique(item["constraints"], _constraints(row))
        _extend_unique(item["_row_acceptance_criteria"], _row_acceptance_criteria(row))
        _extend_unique(item["acceptance_criteria"], _class_hint_acceptance_criteria(row, kb_entry_index))
        _extend_unique(item["open_questions"], _open_questions(row))

    functions = list(grouped.values())
    for index, item in enumerate(functions, 1):
        item["id"] = f"FUNC-{index:03d}"
        item["description"] = _function_description(item)
        item["acceptance_criteria"] = _acceptance_criteria(item)
        item.pop("_row_acceptance_criteria", None)
        item["implementation_tasks"] = _implementation_tasks(item)
        item["implementation_spec"] = _implementation_spec(item)
    return functions


def _compose_dlms_objects(object_model: dict[str, Any], atomic_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for source in object_model.get("objects", []):
        source_refs: list[str] = []
        _extend_unique(source_refs, source.get("source_refs") or [])
        for attr in source.get("attributes") or []:
            _extend_unique(source_refs, attr.get("source_refs") or [])

        raw_members = [_attribute_from_model(attr) for attr in source.get("attributes") or []]
        attributes = _collapse_attributes([attr for attr in raw_members if not _is_method_member(attr)])
        methods = _collapse_methods([attr for attr in raw_members if _is_method_member(attr)])
        obj = {
            "id": f"DLMS-{len(objects) + 1:03d}",
            "object_name": str(source.get("object") or ""),
            "class_id": str(source.get("class_id") or ""),
            "obis": str(source.get("obis") or ""),
            "attributes": attributes,
            "methods": methods,
            "access_rights": {},
            "mandatory": _infer_mandatory_from_model(source),
            "source_atomic_requirements": _unique_strings(source.get("source_atomic_requirements") or []),
            "source_refs": source_refs,
            "source_table_ids": _unique_strings(source.get("source_table_ids") or []),
            "source_order": source.get("source_order"),
            "section_path": source.get("section_path") or [],
            "related_functions": [],
            "open_questions": [],
        }
        obj["implementation_summary"] = _object_implementation_summary(obj)
        obj["access_summary"] = _object_access_summary(attributes)
        obj["method_summary"] = _object_method_summary(methods)
        objects.append(obj)
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


def _attribute_from_model(attr: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": str(attr.get("index") or ""),
        "name": str(attr.get("name") or ""),
        "type": str(attr.get("type") or ""),
        "access_rights": str(attr.get("access_raw") or _format_access(attr.get("access") or {})),
        "default": str(attr.get("default") or ""),
        "observed_values": [str(attr.get("default") or "")] if str(attr.get("default") or "") else [],
    }


def _collapse_attributes(attributes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: OrderedDict[tuple[str, str, str, str], dict[str, Any]] = OrderedDict()
    for attr in attributes:
        key = (
            str(attr.get("index") or ""),
            str(attr.get("name") or ""),
            str(attr.get("type") or ""),
            str(attr.get("access_rights") or ""),
        )
        target = grouped.setdefault(key, dict(attr))
        values = target.setdefault("observed_values", [])
        for value in attr.get("observed_values") or []:
            _append_unique(values, value)
        if not target.get("default"):
            target["default"] = str(attr.get("default") or "")
    for attr in grouped.values():
        values = attr.get("observed_values") or []
        if len(values) > 1:
            attr["default"] = "; ".join(str(value) for value in values)
    return list(grouped.values())


def _collapse_methods(methods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
    for method in methods:
        key = (str(method.get("index") or ""), str(method.get("name") or ""))
        target = grouped.setdefault(key, {
            "index": str(method.get("index") or ""),
            "name": str(method.get("name") or ""),
            "access_rights": str(method.get("access_rights") or ""),
        })
        if not target.get("access_rights"):
            target["access_rights"] = str(method.get("access_rights") or "")
    return list(grouped.values())


def _is_method_member(member: dict[str, Any]) -> bool:
    access = str(member.get("access_rights") or "")
    name = str(member.get("name") or "").strip().lower()
    value_type = str(member.get("type") or "").strip().lower()
    if "A" in access.split("/"):
        return True
    if value_type == "method":
        return True
    return name in METHOD_NAMES and "-W" in access.split("/")


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


def _dlms_object_index(dlms_objects: list[dict[str, Any]]) -> dict[str, Any]:
    names: list[str] = []
    by_obis: dict[str, str] = {}
    by_class_id: dict[str, list[dict[str, Any]]] = {}
    by_table_id: dict[str, list[dict[str, Any]]] = {}
    for obj in dlms_objects:
        name = str(obj.get("object_name") or "").strip()
        if name:
            names.append(name)
        obis = str(obj.get("obis") or "").strip()
        if name and obis:
            by_obis[obis.lower()] = name
            by_obis[obis.replace("-", ".").replace(":", ".").lower()] = name
        class_id = str(obj.get("class_id") or "").strip()
        if class_id and name:
            by_class_id.setdefault(class_id, []).append(obj)
        for table_id in obj.get("source_table_ids") or []:
            if name and table_id:
                by_table_id.setdefault(str(table_id), []).append(obj)
    return {"names": names, "by_obis": by_obis, "by_class_id": by_class_id, "by_table_id": by_table_id}


def _related_object_names(row: dict[str, Any], object_index: dict[str, Any]) -> list[str]:
    if row.get("requirement_type") == "event_group_retention":
        return []
    object_text = str(row.get("object") or "")
    requirement_text = str(row.get("requirement") or "")
    cleaned_requirement_text = _clean_requirement_detail(requirement_text)
    haystack = f"{object_text} {requirement_text} {cleaned_requirement_text}".lower()
    related: list[str] = []
    for name in object_index["names"]:
        if _mentions_object_name(haystack, name):
            _append_unique(related, name)
    for obis, name in object_index["by_obis"].items():
        if obis and obis in haystack:
            _append_unique(related, name)
    for phrase in _required_object_phrases(f"{requirement_text} {cleaned_requirement_text}"):
        for name in object_index["names"]:
            if _object_name_matches_phrase(name, phrase):
                _append_unique(related, name)
    _extend_unique(related, _semantic_related_object_names(row, object_index, haystack))
    return related


def _semantic_related_object_names(row: dict[str, Any], object_index: dict[str, Any], haystack: str) -> list[str]:
    related: list[str] = []
    module_hint = f"{row.get('domain') or ''} {_context_title(row)}".lower()
    security_object_context = _has_security_object_context(module_hint, haystack)
    if security_object_context or "invocation counter" in haystack:
        for name in object_index["names"]:
            lowered = name.lower()
            if ("security setup" in lowered and security_object_context) \
                    or ("security-invocation counter" in lowered and "invocation counter" in haystack):
                _append_unique(related, name)
    if "load_profile" in module_hint or "load profile" in haystack or "mass memory" in haystack:
        for name in object_index["names"]:
            if "load profile" in name.lower():
                _append_unique(related, name)
    return related


def _has_security_object_context(module_hint: str, haystack: str) -> bool:
    text = f"{module_hint} {haystack}".lower()
    return any(
        phrase in text
        for phrase in (
            "security suite",
            "security policy",
            "security setup",
            "protected",
            "secure client",
            "encryption key",
            "authentication key",
            "master key",
            "dedicated key",
        )
    )


def _required_object_phrases(text: str) -> list[str]:
    phrases: list[str] = []
    if re.search(r"\bFilter of event logs?\b", str(text or ""), flags=re.IGNORECASE):
        _append_unique(phrases, "Event Log Filter")
    if re.search(r"\bLoad profile\b", str(text or ""), flags=re.IGNORECASE):
        _append_unique(phrases, "Load profile")
    for match in re.finditer(r"\bobject\s+(.+?)\s+must be used\b", str(text or ""), flags=re.IGNORECASE):
        phrase = match.group(1).strip(" .,:;\"'")
        if phrase:
            _append_unique(phrases, phrase)
    for match in re.finditer(r"\"(.+?)\"\s+object\s+must be used\b", str(text or ""), flags=re.IGNORECASE):
        phrase = match.group(1).strip(" .,:;\"'")
        if phrase:
            _append_unique(phrases, phrase)
    for match in re.finditer(
        r"\bmust\s+to\s+be\s+used\s+O\s+object\s+[\"“](.+?)[\"”]",
        str(text or ""),
        flags=re.IGNORECASE,
    ):
        phrase = match.group(1).strip(" .,:;\"'")
        if phrase:
            _append_unique(phrases, phrase)
    return phrases


def _object_name_matches_phrase(name: str, phrase: str) -> bool:
    object_name = " ".join(str(name or "").lower().split())
    required = _normalize_object_phrase(str(phrase or "")).lower()
    required = " ".join(required.split())
    if not object_name or not required:
        return False
    return object_name == required or object_name.startswith(f"{required} ") or required in object_name


def _normalize_object_phrase(value: str) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(r"\bData of billing period\b", "Date of billing period", text, flags=re.IGNORECASE)
    text = re.sub(r"\bFilter of event logs?\b", "Event Log Filter", text, flags=re.IGNORECASE)
    return text


def _related_object_names_from_source_context(
    row: dict[str, Any],
    object_index: dict[str, Any],
    source_index: dict[str, dict[str, Any]],
) -> list[str]:
    row_order = source_order_for_row(row, source_index)
    table_id, row_index, _ = row_order
    if not table_id:
        return []
    candidates = list(object_index.get("by_table_id", {}).get(table_id, []))
    if not candidates:
        return []
    row_section = _section_key(row)
    scored: list[tuple[int, str]] = []
    for obj in candidates:
        object_order = obj.get("source_order", ("", 0, ""))
        try:
            object_row_index = int(object_order[1])
        except (TypeError, ValueError, IndexError):
            continue
        distance = abs(row_index - object_row_index)
        if distance > 3:
            continue
        if row_section and row_section != _section_key(obj):
            continue
        object_name = str(obj.get("object_name") or "").strip()
        if object_name:
            scored.append((distance, object_name))
    if not scored:
        return []
    scored.sort(key=lambda item: (item[0], item[1].lower()))
    nearest_distance = scored[0][0]
    return [name for distance, name in scored if distance == nearest_distance]


def _mentions_object_name(haystack: str, name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return False
    if len(text) <= 3:
        return re.search(rf"(?<![A-Za-z0-9]){re.escape(text.lower())}(?![A-Za-z0-9])", haystack) is not None
    return text.lower() in haystack


def _section_key(row: dict[str, Any]) -> str:
    path = row.get("section_path") or []
    if not isinstance(path, list):
        return ""
    return " > ".join(str(part).strip().lower() for part in path if str(part).strip())


def _load_default_kb_entry_index() -> dict[str, dict[str, Any]]:
    try:
        repo = KnowledgeRepository.from_paths(default_kb_paths())
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return {entry.entry_id: entry.to_dict(include_metadata=True) for entry in repo.entries}


def _class_hints(row: dict[str, Any], kb_entry_index: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    kb_entry_index = kb_entry_index or {}
    hints: list[dict[str, Any]] = []
    for match in row.get("kb_matches") or []:
        if not isinstance(match, dict):
            continue
        if str(match.get("type") or "") != "cosem_interface_class":
            continue
        expanded = _expand_kb_match(match, kb_entry_index)
        hint = {
            "entry_id": str(expanded.get("entry_id") or expanded.get("id") or "").strip(),
            "name": str(expanded.get("name") or "").strip(),
            "class_id": str(expanded.get("class_id") or "").strip(),
            "definition": str(expanded.get("definition") or "").strip(),
            "behavior_notes": _unique_strings(expanded.get("behavior_notes") or []),
            "access_semantics": _unique_strings(expanded.get("access_semantics") or []),
        }
        if hint["entry_id"] or hint["name"]:
            hints.append(hint)
    return hints


def _expand_kb_match(match: dict[str, Any], kb_entry_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    entry_id = str(match.get("entry_id") or match.get("id") or "").strip()
    expanded = dict(match)
    indexed = kb_entry_index.get(entry_id)
    if not indexed:
        return expanded
    metadata = indexed.get("metadata") if isinstance(indexed.get("metadata"), dict) else {}
    for key in ("definition", "layer", "domain_tags"):
        if not expanded.get(key) and indexed.get(key):
            expanded[key] = indexed[key]
    for key in ("class_id", "version", "attributes", "methods", "access_semantics", "behavior_notes", "coverage_level"):
        if not expanded.get(key) and metadata.get(key) is not None:
            expanded[key] = metadata[key]
    return expanded


def _merge_class_hints(target: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> None:
    seen = {
        (
            str(item.get("entry_id") or ""),
            str(item.get("name") or ""),
            str(item.get("class_id") or ""),
        )
        for item in target
    }
    for hint in incoming:
        key = (
            str(hint.get("entry_id") or ""),
            str(hint.get("name") or ""),
            str(hint.get("class_id") or ""),
        )
        if key not in seen:
            seen.add(key)
            target.append(hint)


def _class_hint_acceptance_criteria(
    row: dict[str, Any],
    kb_entry_index: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    criteria: list[str] = []
    for hint in _class_hints(row, kb_entry_index):
        label = str(hint.get("name") or hint.get("entry_id") or "COSEM class").strip()
        class_id = str(hint.get("class_id") or "").strip()
        if label and class_id:
            criteria.append(f"COSEM class hint: {label} (class {class_id}).")
        elif label:
            criteria.append(f"COSEM class hint: {label}.")
    return criteria


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
    if str(row.get("domain") or "").lower() == "load_profile" or any(
        keyword in text for keyword in ("load profile", "load curve", "mass memory", "capture period", "storage capacity")
    ):
        return "曲线"
    if "security" in section or "security" in text:
        return "安全"
    if any(keyword in text for keyword in ("smtp", "m-bus", "gprs", "tcp", "udp", "ipv4", "ipv6", "communication")):
        return "通信协议"
    mapping = (
        ("结算", ("billing", "settlement", "invoicing", "period")),
        ("时钟", ("time", "clock", "rtc")),
        ("事件记录", ("event", "log")),
        ("安全", ("security", "auth", "cipher", "key", "hls", "lls")),
        ("需量", ("demand",)),
        ("费率", ("tariff", "rate")),
        ("Push", ("push",)),
        ("升级", ("firmware", "upgrade", "image transfer")),
        ("曲线", ("load profile", "mass memory", "collection", "capture period", "storage capacity")),
        ("计量", ("metering", "energy", "register", "measurement", "voltage", "current")),
        ("通信协议", ("dlms", "cosem", "xdlms", "association", "service")),
    )
    for label, keywords in mapping:
        if any(keyword in text for keyword in keywords):
            return label
    return "通信协议"


def _module_label(row: dict[str, Any], domain: str) -> str:
    text = f"{row.get('domain') or ''} {row.get('object') or ''} {row.get('requirement') or ''} {_context_title(row)}".lower()
    if str(row.get("domain") or "").lower() == "load_profile" or any(
        keyword in text for keyword in ("load profile", "load curve", "mass memory", "capture period", "storage capacity")
    ):
        return "load_profile"
    domain_map = {
        "结算": "billing",
        "时钟": "time",
        "事件记录": "events",
        "安全": "security",
        "需量": "demand",
        "费率": "tariff",
        "Push": "push",
        "升级": "firmware",
        "曲线": "load_profile",
        "计量": "metering",
        "通信协议": "communication",
    }
    if domain in domain_map:
        return domain_map[domain]
    keyword_map = (
        ("security", ("security", "secure", "auth", "cipher", "key", "hls", "lls")),
        ("billing", ("billing", "settlement", "invoicing")),
        ("events", ("event", "log")),
        ("time", ("clock", "time synchronization", "rtc")),
        ("load_profile", ("load profile", "mass memory", "capture period", "storage capacity")),
        ("metering", ("metering", "energy", "register", "measurement", "voltage", "current", "obis")),
        ("communication", ("dlms", "cosem", "xdlms", "association", "smtp", "m-bus", "gprs", "tcp", "udp", "ip")),
    )
    for module, keywords in keyword_map:
        if any(keyword in text for keyword in keywords):
            return module
    return "general"


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
    if row.get("requirement_type") == "event_group_retention":
        return "Event retention requirements"
    if row.get("requirement_type") == "event_definition":
        if (
            "secure" in text
            or "security policy" in text
            or "password" in text
            or "encryption" in text
            or "authentication" in text
            or "master key" in text
            or "dedicated key" in text
        ):
            return "Security event definitions"
        return "Event recording behavior"
    if "billing" in text or "invoicing" in text or "billing" in section:
        return "Control of billing period"
    if "load profile" in text or "load curve" in text or "collection" in text or "mass memory" in text or "storage capacity" in text:
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


def _function_topic(row: dict[str, Any], object_index: dict[str, Any]) -> str:
    requirement_type = row.get("requirement_type")
    semantic_title = _semantic_title(row)
    cleaned_text = _clean_requirement_detail(str(row.get("requirement") or "")).lower()
    raw_text = str(row.get("requirement") or "").lower()
    if (
        "event recording and push notification" in cleaned_text
        or "shipping of event" in raw_text
        or "event-notification" in raw_text
    ):
        return "event handling"
    if requirement_type == "event_group_retention":
        return "event retention requirements"
    if requirement_type in {"capability_matrix", "association_security_matrix"}:
        return semantic_title or _context_title(row).lower()
    if semantic_title in {"Control of billing period", "Load profile collection and storage"}:
        return semantic_title.lower()
    if semantic_title == "Security and key management":
        return semantic_title.lower()
    if requirement_type == "event_definition":
        return semantic_title or "event definitions"
    related = _related_object_names(row, object_index)
    if related:
        return "|".join(related)
    obj = str(row.get("object") or "").strip().lower()
    if obj and obj not in WEAK_OBJECT_TOPICS:
        return obj
    return _context_title(row).lower()


def _is_low_information_function_row(row: dict[str, Any]) -> bool:
    text = " ".join(str(row.get("requirement") or "").split()).strip().rstrip(".")
    if not text:
        return False
    lowered = text.lower()
    requirement_type = str(row.get("requirement_type") or "")
    parameters = row.get("parameters") if isinstance(row.get("parameters"), dict) else {}
    fields = parameters.get("fields") if isinstance(parameters.get("fields"), dict) else {}
    if requirement_type == "cosem_object" and fields.get("Object/attribute name") and fields.get("#"):
        return True
    if (
        "functionality" in lowered
        and "objects in support" in lowered
        and "implemented as defined" in lowered
    ):
        return True
    if re.fullmatch(r'\d+\s*\|\s*not used,\s*must be set to "?0"?', text, flags=re.IGNORECASE):
        return True
    ordinal = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
    if re.fullmatch(rf"{ordinal}\s+shall\s+support\s+Value", text, flags=re.IGNORECASE) is None:
        return False
    if requirement_type in {"functional", "cosem_object"}:
        return True
    return (
        requirement_type == "capability_matrix"
        and str(parameters.get("subject_header") or "").strip() == "#"
        and str(parameters.get("predicate_header") or "").strip().lower() == "value"
    )


def _function_description(item: dict[str, Any]) -> str:
    if _event_handling_spec(item):
        return "研发实现应覆盖事件记录与事件推送控制：按事件寄存器位记录事件，按事件推送位发送 push notification。"
    security_policy = _security_policy_spec(item)
    key_management = _key_management_spec(item)
    access_control = _access_control_matrix_spec(item)
    if security_policy or key_management or access_control:
        parts = []
        if security_policy:
            parts.append("安全套件/安全策略")
        if key_management:
            parts.append("密钥装载、有效期与调用计数器")
        if access_control:
            parts.append("客户端访问安全级别")
        return "研发实现应覆盖" + "、".join(parts) + "：按结构化安全策略配置对象、密钥流程和安全访问规则。"
    load_profile = _load_profile_spec(item)
    if load_profile:
        return "研发实现应覆盖负荷曲线采集与存储：按可编程采集周期采集曲线数据，并满足质量/状态记录和存储容量要求。"
    billing_period = _billing_period_spec(item)
    if billing_period:
        return "研发实现应覆盖结算周期数据：周期结束时生成结算记录，并使用规范指定的结算对象。"
    capability_matrix = _capability_matrix_spec(item)
    if capability_matrix:
        return "研发实现应覆盖 xDLMS 能力矩阵：按客户端角色启用允许的服务集合。"
    details = [str(detail) for detail in item.get("functional_details") or [] if str(detail)]
    if not details:
        return f"研发实现应覆盖 {item.get('title') or item.get('id')} 相关规范要求。"
    if len(details) == 1:
        return f"研发实现应覆盖以下规范要求：{details[0]}"
    joined = "；".join(details)
    return f"研发实现应将同一上下文中的 {len(details)} 条原子要求合并实现：{joined}"


def _implementation_tasks(item: dict[str, Any]) -> list[str]:
    tasks: list[str] = []
    source_ids = item.get("source_atomic_requirements") or []
    if source_ids:
        _append_unique(
            tasks,
            "Implement normative behavior from atomic requirements: " + ", ".join(str(x) for x in source_ids) + ".",
        )
    related_objects = item.get("related_dlms_objects") or []
    if len(related_objects) > MAX_OBJECT_TASK_ITEMS:
        _append_unique(tasks, f"Configure {len(related_objects)} related DLMS objects; see DLMS object impact list.")
    else:
        for object_name in related_objects:
            _append_unique(tasks, f"Configure DLMS object: {object_name}.")
    for hint in item.get("class_hints") or []:
        label = str(hint.get("name") or hint.get("entry_id") or "COSEM class").strip()
        class_id = str(hint.get("class_id") or "").strip()
        if label and class_id:
            _append_unique(tasks, f"Apply COSEM class semantics: {label} (class {class_id}).")
        elif label:
            _append_unique(tasks, f"Apply COSEM class semantics: {label}.")
    for constraint in item.get("constraints") or []:
        text = str(constraint)
        if text.startswith("验证方式："):
            method = text.split("：", 1)[1].strip()
            if method:
                _append_unique(tasks, f"Verify with {method}.")
    return tasks


def _implementation_spec(item: dict[str, Any]) -> dict[str, Any]:
    spec = {
        "trigger_or_input": _trigger_or_input(item),
        "processing_rules": _processing_rules(item),
        "dlms_object_impact": _dlms_object_impact(item),
        "error_and_boundary_behavior": _error_and_boundary_behavior(item),
        "acceptance_checks": list(item.get("acceptance_criteria") or []),
    }
    event_handling = _event_handling_spec(item)
    if event_handling:
        spec["event_handling"] = event_handling
    event_retention = _event_retention_spec(item)
    if event_retention:
        spec["event_retention"] = event_retention
    event_definitions = _event_definitions_spec(item)
    if event_definitions:
        spec["event_definitions"] = event_definitions
    billing_period = _billing_period_spec(item)
    if billing_period:
        spec["billing_period"] = billing_period
    load_profile = _load_profile_spec(item)
    if load_profile:
        spec["load_profile"] = load_profile
    capability_matrix = _capability_matrix_spec(item)
    if capability_matrix:
        spec["capability_matrix"] = capability_matrix
    access_control_matrix = _access_control_matrix_spec(item)
    if access_control_matrix:
        spec["access_control_matrix"] = access_control_matrix
    security_policy = _security_policy_spec(item)
    if security_policy:
        spec["security_policy"] = security_policy
    key_management = _key_management_spec(item)
    if key_management:
        spec["key_management"] = key_management
    return spec


def _trigger_or_input(item: dict[str, Any]) -> str:
    refs = [str(value) for value in item.get("source_refs") or [] if str(value)]
    title = str(item.get("title") or item.get("domain") or "source context").strip()
    if refs and all(ref.startswith("TBL-") for ref in refs):
        return f"Table-derived requirements for {title}."
    if refs and all(ref.startswith("BLK-") for ref in refs):
        return f"Requirements from {title}."
    return f"Requirements from {title} source context."


def _processing_rules(item: dict[str, Any]) -> list[str]:
    rules: list[str] = []
    event_handling = _event_handling_spec(item)
    if event_handling:
        _append_unique(rules, event_handling["condition"])
        _append_unique(rules, event_handling["recording_action"])
        _append_unique(rules, event_handling["notification_action"])
    event_retention = _event_retention_spec(item)
    if event_retention:
        for subgroup in event_retention["subgroups"]:
            suffix = f" ({subgroup['event_scope']})" if subgroup.get("event_scope") else ""
            _append_unique(
                rules,
                f"Keep at least {subgroup['minimum_records']} records for event subgroup {subgroup['subgroup']}{suffix}.",
            )
    event_definitions = _event_definitions_spec(item)
    if event_definitions:
        for event in event_definitions["events"]:
            _append_unique(rules, f"Map event {event['event_code']} to description: {event['description']}.")
    billing_period = _billing_period_spec(item)
    if billing_period:
        _append_unique(rules, billing_period["trigger"])
        _append_unique(rules, billing_period["minimum_records"])
        for required_object in billing_period["required_objects"]:
            _append_unique(rules, f"Use billing object: {required_object}.")
    load_profile = _load_profile_spec(item)
    if load_profile:
        if load_profile.get("collection_interval"):
            _append_unique(rules, load_profile["collection_interval"])
        if load_profile.get("storage_capacity"):
            _append_unique(rules, load_profile["storage_capacity"])
    capability_matrix = _capability_matrix_spec(item)
    if capability_matrix:
        for actor, services in capability_matrix["actors"].items():
            for service in services:
                _append_unique(rules, f"Allow {actor} to use {service}.")
    access_control_matrix = _access_control_matrix_spec(item)
    if access_control_matrix:
        for actor, grants in access_control_matrix["actors"].items():
            for grant in grants:
                target = str(grant.get("target") or "").strip()
                security_level = str(grant.get("security_level") or "").strip()
                if target and security_level:
                    _append_unique(rules, f"Require {actor} to access {target} with {security_level}.")
    security_policy = _security_policy_spec(item)
    if security_policy:
        for value in security_policy.values():
            _append_unique(rules, str(value))
    key_management = _key_management_spec(item)
    if key_management:
        for value in key_management.values():
            _append_unique(rules, str(value))
    structured_patterns: list[str] = []
    if event_handling:
        structured_patterns.extend([
            "event recording and push notification",
            "case o bit corresponding to the shipping of event",
        ])
    for detail in item.get("functional_details") or []:
        if _detail_is_covered_by_structured_spec(detail, structured_patterns):
            continue
        _append_unique(rules, _normalize_requirement_sentence(detail))
    for hint in item.get("class_hints") or []:
        label = str(hint.get("name") or hint.get("entry_id") or "COSEM class").strip()
        class_id = str(hint.get("class_id") or "").strip()
        if label and class_id:
            _append_unique(rules, f"Apply COSEM class semantics: {label} (class {class_id}).")
        elif label:
            _append_unique(rules, f"Apply COSEM class semantics: {label}.")
    return rules


def _detail_is_covered_by_structured_spec(detail: Any, patterns: list[str]) -> bool:
    text = str(detail or "").lower()
    return any(pattern in text for pattern in patterns)


def _dlms_object_impact(item: dict[str, Any]) -> list[str]:
    impacts: list[str] = []
    for object_name in item.get("related_dlms_objects") or []:
        _append_unique(impacts, f"Configure {object_name}.")
    return impacts


def _event_handling_spec(item: dict[str, Any]) -> dict[str, str] | None:
    text = " ".join(str(detail).lower() for detail in item.get("functional_details") or [])
    domain = str(item.get("domain") or "").lower()
    title = str(item.get("title") or "").lower()
    if "event" not in f"{domain} {title} {text}":
        return None
    has_register_rule = "event register" in text or ("register bit" in text and "event" in text)
    has_log_rule = "event log" in text or "registered in the corresponding" in text
    has_push_rule = "push" in text or "shipping of event" in text or "event-notification" in text
    if not (has_register_rule and (has_log_rule or has_push_rule)):
        return None
    return {
        "condition": "Evaluate the configured event register and event shipping bits for each detected event.",
        "recording_action": "When the register bit is enabled, persist the event in the corresponding event log.",
        "notification_action": "When the shipping bit is enabled, send the event through push communication.",
    }


def _event_retention_spec(item: dict[str, Any]) -> dict[str, Any] | None:
    subgroups: list[dict[str, Any]] = []
    for detail in item.get("functional_details") or []:
        match = re.search(
            r"\bEvent subgroup\s+([A-Za-z0-9-]+)\s+shall keep at least\s+(\d+)\s+records for\s+(.+?)\s*\.?$",
            str(detail),
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        subgroup = _normalize_event_subgroup(match.group(1))
        event_scope = match.group(3).strip(" .")
        payload = {
            "subgroup": subgroup,
            "minimum_records": int(match.group(2)),
            "event_scope": event_scope,
        }
        if payload not in subgroups:
            subgroups.append(payload)
    return {"subgroups": subgroups} if subgroups else None


def _normalize_event_subgroup(value: str) -> str:
    match = re.fullmatch(r"(G\w+)-SG(\w+)", str(value or "").strip(), flags=re.IGNORECASE)
    if not match:
        return str(value or "").strip()
    return f"{_normalize_event_token(match.group(1))}-SG{_normalize_event_token(match.group(2))}"


def _event_definitions_spec(item: dict[str, Any]) -> dict[str, Any] | None:
    events: list[dict[str, Any]] = []
    for detail in item.get("functional_details") or []:
        match = re.search(
            r"\bEvent\s+(G\w+)-SG(\w+)-E(\w+)\s+shall be defined as:\s+(.+?)\s*\.?$",
            str(detail),
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        group = _normalize_event_token(match.group(1))
        subgroup = "SG" + _normalize_event_token(match.group(2))
        event_number_text = _normalize_event_token(match.group(3))
        try:
            event_number: int | str = int(event_number_text)
        except ValueError:
            event_number = event_number_text
        description = _normalize_event_description(match.group(4).strip(" ."))
        payload = {
            "event_code": f"{group}-{subgroup}-E{event_number_text}",
            "group": group,
            "subgroup": subgroup,
            "event_number": event_number,
            "description": description,
        }
        if payload not in events:
            events.append(payload)
    return {"events": events} if events else None


def _normalize_event_description(value: str) -> str:
    text = " ".join(str(value or "").split())
    replacements = (
        (r"\bat the door PLC\b", "on the PLC port"),
        (r"\bat the door optics\b", "on the optical port"),
        (r"\bat the door serial\b", "on the serial port"),
        (r"\bat the door RF\b", "on the RF port"),
        (r"\bon the door PLC\b", "on the PLC port"),
        (r"\bon the door optics\b", "on the optical port"),
        (r"\bon the door serial\b", "on the serial port"),
        (r"\bon the door RF\b", "on the RF port"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _normalize_event_token(value: str) -> str:
    text = str(value or "").strip()
    replacements = {
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8",
        "nine": "9",
        "ten": "10",
    }
    lowered = text.lower()
    if lowered in replacements:
        return replacements[lowered]
    prefixed = re.fullmatch(r"([A-Za-z]+)(one|two|three|four|five|six|seven|eight|nine|ten)", text, flags=re.IGNORECASE)
    if prefixed:
        return f"{prefixed.group(1)}{replacements[prefixed.group(2).lower()]}"
    return text


def _billing_period_spec(item: dict[str, Any]) -> dict[str, Any] | None:
    text = " ".join(str(detail) for detail in item.get("functional_details") or [])
    lowered = text.lower()
    if "billing" not in f"{item.get('module') or ''} {item.get('domain') or ''} {item.get('title') or ''} {lowered}".lower():
        return None
    result: dict[str, Any] = {
        "trigger": "At billing period close, finalize the period data set.",
        "minimum_records": "",
        "required_objects": [],
    }
    records_match = re.search(r"at least\s+(\d+)\s+billing records", lowered)
    if records_match:
        result["minimum_records"] = f"Keep at least {records_match.group(1)} billing period records."
    else:
        result["minimum_records"] = "Keep billing period records according to the source requirements."
    required_objects: list[str] = []
    for detail in item.get("functional_details") or []:
        match = re.search(r"object\s+(.+?)\s+must be used", str(detail), flags=re.IGNORECASE)
        if match:
            _append_unique(required_objects, match.group(1).strip(" ."))
    result["required_objects"] = required_objects
    return result if result["minimum_records"] or result["required_objects"] else None


def _load_profile_spec(item: dict[str, Any]) -> dict[str, str] | None:
    text = " ".join(str(detail) for detail in item.get("functional_details") or [])
    lowered = text.lower()
    if "load_profile" not in str(item.get("module") or "") and not any(
        keyword in lowered for keyword in ("load profile", "mass memory", "collection")
    ):
        return None
    result: dict[str, str] = {}
    interval_match = re.search(r"(\d+)\s*min\s+to\s+(\d+)\s*min", lowered)
    if interval_match:
        result["collection_interval"] = (
            f"Support programmable collection intervals from {interval_match.group(1)} min to {interval_match.group(2)} min."
        )
    if "mass memory" in lowered:
        days_match = re.search(r"at least\s+(\d+)\s+days", lowered)
        if days_match:
            result["storage_capacity"] = f"Maintain mass memory storage for at least {days_match.group(1)} days."
        else:
            result["storage_capacity"] = "Maintain mass memory storage according to the source requirements."
    return result or None


def _capability_matrix_spec(item: dict[str, Any]) -> dict[str, Any] | None:
    details = [str(detail) for detail in item.get("functional_details") or []]
    if not details or not any("xdlms service" in detail.lower() for detail in details):
        return None
    actors: dict[str, list[str]] = {}
    for detail in details:
        match = re.search(r"^(.*?)\s+shall support xDLMS Service:\s*(.+?)\.?$", detail.strip(), flags=re.IGNORECASE)
        if not match:
            continue
        actor = _clean_actor_label(match.group(1))
        service = match.group(2).strip()
        if actor and service:
            actors.setdefault(actor, [])
            _append_unique(actors[actor], service)
    return {"actors": actors} if actors else None


def _access_control_matrix_spec(item: dict[str, Any]) -> dict[str, Any] | None:
    details = [str(detail) for detail in item.get("functional_details") or []]
    if not details or not any("server application process" in detail.lower() for detail in details):
        return None
    actors: dict[str, list[dict[str, str]]] = {}
    for detail in details:
        match = re.search(
            r"^(.*?)\s+shall have Server application process:\s*(.+?)\s+set to\s+(.+?)\.?$",
            detail.strip(),
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        actor = _clean_actor_label(match.group(1))
        target = _clean_matrix_value(match.group(2))
        security_level = _clean_matrix_value(match.group(3))
        if not (actor and target and security_level):
            continue
        grant = {"target": target, "security_level": security_level}
        existing = actors.setdefault(actor, [])
        if grant not in existing:
            existing.append(grant)
    return {"actors": actors} if actors else None


def _security_policy_spec(item: dict[str, Any]) -> dict[str, str] | None:
    text = " ".join(str(detail) for detail in item.get("functional_details") or [])
    lowered = text.lower()
    if "security" not in f"{item.get('module') or ''} {item.get('domain') or ''} {item.get('title') or ''} {lowered}".lower():
        return None
    result: dict[str, str] = {}
    if "security suite" in lowered or ("cryptographic" in lowered and ("key size" in lowered or "sizes of keys" in lowered)):
        result["security_suite"] = (
            "Define the cryptographic algorithms and key sizes that must be available for each supported security suite."
        )
    if "does not need protection" in lowered or "no need to be protected" in lowered or 'remain "0"' in lowered:
        result["unprotected_clients"] = (
            'Keep the corresponding security policy object at "0" when a client implementation does not require protection.'
        )
    if "following keys" in lowered or "support the following keys" in lowered:
        result["supported_keys"] = (
            "Support the security keys required by the standard and expose them through the configured key management flow."
        )
    if "key" in lowered and ("expire" in lowered or "expiration" in lowered or "re-established" in lowered or "reestablished" in lowered):
        result["key_expiration"] = (
            "Expire secure keys at the programmed time and require them to be re-established before protected communication continues."
        )
    if "invocation counter" in lowered and ("secure client" in lowered or "secure customer" in lowered) and "independent" in lowered:
        result["invocation_counters"] = (
            "Maintain an independent unicast communication invocation counter for each secure client."
        )
    return result or None


def _key_management_spec(item: dict[str, Any]) -> dict[str, str] | None:
    text = " ".join(str(detail) for detail in item.get("functional_details") or [])
    lowered = text.lower()
    if "security" not in f"{item.get('module') or ''} {item.get('domain') or ''} {item.get('title') or ''} {lowered}".lower():
        return None
    result: dict[str, str] = {}
    if "integrity" in lowered and "key" in lowered and (
        "unwrapping" in lowered or "unveiling" in lowered or "loading" in lowered
    ):
        result["key_loading_integrity"] = (
            "During key unwrapping and loading, verify the integrity of each new master key and global key before accepting it."
        )
    if "invocation counter" in lowered and "protected message" in lowered and ("reset" in lowered or "replaced" in lowered):
        result["protected_message_counters"] = (
            'Increment invocation counters for each protected message and reset the corresponding counter to "0" when its key is replaced or reset.'
        )
    return result or None


def _clean_matrix_value(value: str) -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:1].upper() + text[1:] if text else ""


def _clean_actor_label(value: str) -> str:
    text = " ".join(str(value or "").strip().split())
    text = re.sub(r"\s+It is\s+(?:measurement|management|local|remote)\b.*$", "", text, flags=re.IGNORECASE).strip()
    if not text:
        return ""
    return text[:1].upper() + text[1:]


def _error_and_boundary_behavior(item: dict[str, Any]) -> list[str]:
    behavior: list[str] = []
    for question in item.get("open_questions") or []:
        _append_unique(behavior, str(question))
    for criterion in item.get("acceptance_criteria") or []:
        text = str(criterion)
        if "ambiguity" in text.lower() or "confidence" in text.lower():
            _append_unique(behavior, text)
    return behavior


def _normalize_requirement_sentence(value: Any) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _clean_requirement_detail(value: Any) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(
        r"\bEvent\s+(G\w+)-SG(\w+)-E(\w+)\s+shall be defined as:\s+(.+?)\s*\.?$",
        lambda match: (
            f"Event {_normalize_event_token(match.group(1))}-SG{_normalize_event_token(match.group(2))}-"
            f"E{_normalize_event_token(match.group(3))} shall be defined as: "
            f"{_normalize_event_description(match.group(4).strip(' .'))}."
        ),
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\bEvent subgroup\s+([A-Za-z0-9-]+)\s+shall keep at least\b",
        lambda match: f"Event subgroup {_normalize_event_subgroup(match.group(1))} shall keep at least",
        text,
        flags=re.IGNORECASE,
    )
    if re.search(r"\bO record in one event\b", text, flags=re.IGNORECASE) and "Filter of event logs" in text:
        return (
            'Event recording and push notification must follow the configured "Filter of event logs"; '
            "when the event register bit is set, persist the event in the corresponding event log."
        )
    if re.search(r"\bCase O bit corresponding to the shipping of event\b", text, flags=re.IGNORECASE):
        return (
            "When the event shipping bit is set, send an EVENT-NOTIFICATION-REQUEST "
            "through push communication to notify the client."
        )
    if re.search(
        r"To the magnitudes whose objects they were defined in this Standard they are presented in the Tables 13 The 17",
        text,
        flags=re.IGNORECASE,
    ):
        return (
            "The quantities whose objects are defined in this Standard are listed in Tables 13 to 17; "
            "the concessionaire must define the quantities that are effectively captured in the meter "
            "technical specification according to operational needs, and may organize them into two lists "
            "with programmable capture periods."
        )
    if re.search(r"\blist of catch\b", text, flags=re.IGNORECASE):
        return (
            "The timestamp at the end of the capture period and the meter profile status code must be recorded "
            "in the capture list."
        )
    if re.search(r"\bO set in security determines O set in algorithms cryptographic\b", text, flags=re.IGNORECASE):
        return "The security suite determines the cryptographic algorithms and key sizes that must be available."
    text = re.sub(
        r"\bAt the case in what one Implementation of client no need to be protected,\s*The policy in security must remain",
        "When a client implementation does not need protection, the security policy must remain",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r'\bindependent\s+"\s*unicast\s+"\s+communication invocation counter for each secure customer\b',
                  "independent unicast communication invocation counter for each secure client",
                  text, flags=re.IGNORECASE)
    text = re.sub(r"\s+It is\s+(?:measurement|management|local|remote)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"For to the information of invoicing at the Final of period,\s*(?:he\s+)?must to be used O object\s+\"(.+?)\"",
        r'For final-period invoicing information, the "\1" object must be used',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"For to the information of invoicing at the Final of period,\s*must be used O object\s+\"(.+?)\"",
        r'For final-period invoicing information, the "\1" object must be used',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\bA collect he must to be carried out in breaks programmable\b", "Collection must be carried out at programmable intervals", text, flags=re.IGNORECASE)
    text = re.sub(r"\ball you days\b", "every day", text, flags=re.IGNORECASE)
    text = re.sub(r",?\s*It is The capacity in record he must to be in at the Minimum three months", ", and record capacity must be at least three months", text, flags=re.IGNORECASE)
    text = re.sub(r"\bhe must to be\b", "must be", text, flags=re.IGNORECASE)
    text = re.sub(r"\bThe be\b", "to be", text, flags=re.IGNORECASE)
    text = re.sub(r"\bData of billing period\b", "Date of billing period", text, flags=re.IGNORECASE)
    text = re.sub(r"\bprogrammable intervals in\b", "programmable intervals of", text, flags=re.IGNORECASE)
    text = re.sub(r"\bcollected every day to the\b", "collected every day at", text, flags=re.IGNORECASE)
    return text.strip()


def _constraints(row: dict[str, Any]) -> list[str]:
    constraints: list[str] = []
    if row.get("condition"):
        constraints.append(str(row["condition"]))
    if row.get("verification_method"):
        constraints.append(f"验证方式：{row['verification_method']}")
    return constraints


def _acceptance_criteria(item: dict[str, Any]) -> list[str]:
    source_count = len(item.get("source_atomic_requirements") or [])
    noun = "requirement" if source_count == 1 else "requirements"
    criteria = [f"Covers {source_count} source atomic {noun}."]
    _extend_unique(criteria, item.get("_row_acceptance_criteria") or [])
    _extend_unique(criteria, item.get("acceptance_criteria") or [])
    return criteria


def _row_acceptance_criteria(row: dict[str, Any]) -> list[str]:
    criteria: list[str] = []
    if row.get("verification_method"):
        criteria.append(f"Verification method: {row['verification_method']}.")
    if row.get("ambiguity"):
        criteria.append("Resolve ambiguity before implementation baseline.")
    if row.get("confidence") is not None:
        try:
            if float(row["confidence"]) < 0.6:
                criteria.append("Review original context because extraction confidence is below 0.6.")
        except (TypeError, ValueError):
            pass
    return criteria


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


def _object_implementation_summary(item: dict[str, Any]) -> str:
    name = str(item.get("object_name") or "DLMS object")
    obis = str(item.get("obis") or "-")
    class_id = str(item.get("class_id") or "-")
    attr_count = len(item.get("attributes") or [])
    noun = "attribute" if attr_count == 1 else "attributes"
    return f"Implement {name} with OBIS {obis} and interface class {class_id}; cover {attr_count} {noun}."


def _object_access_summary(attributes: list[dict[str, str]]) -> str:
    parts = [
        f"{attr.get('name')}: {attr.get('access_rights')}"
        for attr in attributes
        if attr.get("name") and attr.get("access_rights")
    ]
    return "; ".join(parts)


def _object_method_summary(methods: list[dict[str, Any]]) -> str:
    return "; ".join(
        f"{method.get('name')}: {method.get('access_rights')}"
        for method in methods
        if method.get("name")
    )


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


def _append_spec_list(lines: list[str], label: str, values: list[Any]) -> None:
    if not values:
        return
    lines.append(f"  - {label}:")
    for value in values:
        lines.append(f"    - {value}")
