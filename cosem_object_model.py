"""P1：COSEM 对象模型 / 数据字典生成器（装配优先，纯确定性 join，零 LLM）。

把已抽取的 cosem 原子装配成给研发的实现规格：
- cosem_object_instance 原子 → 每个 COSEM 对象（OBIS / class_id / 名称 / 含义）
- cosem_attribute_access 原子 → 对象下的属性（索引 / 类型 / 访问矩阵 RC·PC·SC·LC / 默认值）
- measurement_quantity_unit 原子 → 计量量纲单位附录

join 依据原子已带的结构化来源（source_refs → table_items.fields）与分组字段（domain / section_path）。
结果可被原子计数精确校验；冲突（同名对象 OBIS/CL 不一致、属性父对象缺失）显式落到 conflicts / orphan，不静默吞。

用法：python -m cosem_object_model --out <atomizer 输出目录>
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from text_normalize import formula_safe, normalize_numeric


# 源表字段键（取自真实 ABNT 输出）
F_NAME = "Object/attribute name"
F_CLASS = "CL"
F_OBIS = "Value"          # 对象行：OBIS；属性行：默认值
F_TYPE = "Type"
F_ACCESS = "Access rights RC/PC/SC/LC"
F_MEANING = "Meaning"
F_INDEX = "#"
ASSOCIATIONS = ("RC", "PC", "SC", "LC")
CLASS_NAME_TO_ID = {
    "Data": "1",
    "Register": "3",
    "Extended Register": "4",
    "Demand Register": "5",
    "Register Activation": "6",
    "Profile Generic": "7",
    "Clock": "8",
    "Script Table": "9",
    "Schedule": "10",
    "Special Days Table": "11",
    "Association SN": "12",
    "Association LN": "15",
    "SAP Assignment": "17",
    "Image Transfer": "18",
    "Activity Calendar": "20",
    "Single Action Schedule": "22",
    "Register Table": "61",
    "Compact Data": "62",
    "Security Setup": "64",
    "Disconnect Control": "70",
}
CLASS_LEVEL_ATTRIBUTE_NAMES = {
    "Data": {
        "logical_name",
        "value",
        "device_operation",
        "modem_versions",
        "devAddr",
        "join_strategy",
        "multicasts_parameters",
        "disconnect_from_network()",
        "change_class(data)",
        "change_region(data)",
    },
    "Register": {"logical_name", "value", "scaler_unit"},
    "Extended Register": {"logical_name", "value", "scaler_unit", "status", "capture_time", "reset"},
    "Demand Register": {
        "logical_name",
        "current_average_value",
        "last_average_value",
        "scaler_unit",
        "status",
        "capture_time",
        "start_time_current",
        "period",
        "number_of_periods",
        "reset",
        "next_period",
    },
    "Profile Generic": {
        "logical_name",
        "buffer",
        "capture_objects",
        "capture_period",
        "sort_method",
        "sort_object",
        "entries_in_use",
        "profile_entries",
        "reset",
        "capture",
    },
    "Association LN": {
        "logical_name",
        "object_list",
        "associated_partners_id",
        "application_context_ name",
        "xDLMS_context_info",
        "authentication_mechanism_name",
        "LLS_secret",
        "association_status",
        "Security setup reference",
        "User_list",
        "current_user",
        "N_successive_ password_errors",
        "Time_without_ communication",
        "change_HLS_secret (date)",
        "add_object(date)",
        "remove_object(date)",
        "add_user (date)",
        "remove_user (date)",
    },
    "Script Table": {"logical_name", "scripts", "execute"},
    "Single Action Schedule": {"logical_name", "executed_script", "type", "execution_time"},
    "Register Table": {"logical_name", "table_cell_values", "table_cell_definition", "capture"},
    "Compact Data": {"logical_name", "compact_buffer", "capture_objects", "template_id", "template_description", "capture_method"},
    "Security Setup": {
        "logical_name",
        "reply_to_HLS_ authentication (data)",
        "security policy",
        "security suite",
        "client system title",
        "server system title",
        "Certificates",
        "security activate",
        "key transfer",
        "Key agreement",
        "Generate Key pair",
        "Generate certificate request",
        "Import certificate",
        "Export certificate",
        "Remove certificate",
    },
    "Disconnect Control": {"logical_name", "output_state", "control_state", "control_mode", "remote_disconnect", "remote_connect"},
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_source_index(table_items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for item in table_items:
        item_id = str(item.get("item_id") or "")
        if item_id:
            index[item_id] = item
    return index


def review_status_by_id(states: list[dict[str, Any]]) -> dict[str, str]:
    by_id: dict[str, str] = {}
    for state in states:
        status = str(state.get("status") or "candidate")
        for key in ("requirement_id", "stable_req_id", "req_id"):
            value = str(state.get(key) or "")
            if value:
                by_id[value] = status
        metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
        for key in ("stable_req_id", "req_id"):
            value = str(metadata.get(key) or "")
            if value:
                by_id[value] = status
    return by_id


def source_fields(row: dict[str, Any], index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """取该原子第一个能在 table_items 里解析到的来源行的 fields。"""
    for ref in row.get("source_refs", []) or []:
        item = index.get(str(ref))
        if item and isinstance(item.get("fields"), dict):
            return item["fields"]
    return {}


def status_of(row: dict[str, Any], status_by_id: dict[str, str]) -> str:
    for key in ("stable_req_id", "req_id"):
        value = str(row.get(key) or "")
        if value in status_by_id:
            return status_by_id[value]
    return str(row.get("review_status") or "candidate")


def parse_access(raw: str) -> dict[str, str]:
    parts = [p.strip() for p in str(raw or "").split("/")]
    if len(parts) == len(ASSOCIATIONS):
        return dict(zip(ASSOCIATIONS, parts))
    return {}


def attr_access_unresolved(attr: dict[str, Any]) -> bool:
    """True when an attribute carries a non-empty raw access string that did
    not parse into the four expected associations (RC/PC/SC/LC)."""
    return bool(str(attr.get("access_raw") or "").strip()) and not (attr.get("access") or {})


def access_cells(attr: dict[str, Any]) -> tuple[str, str, str, str]:
    """Return the (RC, PC, SC, LC) display cells for an attribute.

    When the raw access string could not be parsed into the four expected
    associations, all four cells are left blank instead of dumping the whole
    raw string into the RC column. The old ``access.get("RC", access_raw)``
    fallback silently mislabelled access rights (a reader would appear to be
    granted everything under RC). The unparsed raw string is preserved
    separately via ``access_raw`` / the unresolved-access appendix so the row
    can still be traced and confirmed by an expert.
    """
    access = attr.get("access") or {}
    if not access:
        return ("", "", "", "")
    return (
        str(access.get("RC", "")),
        str(access.get("PC", "")),
        str(access.get("SC", "")),
        str(access.get("LC", "")),
    )


def build_object_model(out_dir: Path) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    requirements = read_jsonl(out_dir / "atomic_requirements.jsonl")
    index = build_source_index(read_jsonl(out_dir / "table_items.jsonl"))
    status_by_id = review_status_by_id(read_jsonl(out_dir / "review_states.jsonl"))

    objects: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    object_keys_by_name: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    object_keys_by_class_id: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    conflicts: list[dict[str, Any]] = []
    orphan_attributes: list[dict[str, Any]] = []
    units: list[dict[str, Any]] = []
    source_attribute_requirements = 0
    projected_class_attributes = 0

    # 1) 对象实例
    for row in requirements:
        if row.get("requirement_type") != "cosem_object_instance":
            continue
        fields = source_fields(row, index)
        name = str(row.get("object") or fields.get(F_NAME) or "").strip()
        if not name:
            continue
        # 一个源单元格可能含多个 OBIS（ABNT 把主码 + 94.55 国别码同格登记）。
        # 拆成独立对象实例：每个 OBIS 各一个实例（同 name/class_id/attributes）。
        obis_values = split_obis_values(fields.get(F_OBIS))
        if not obis_values:
            obis_values = [""]
        for obis in obis_values:
            class_id = str(fields.get(F_CLASS) or "").strip()
            object_key = (name, obis, class_id, first_source_item_id(row, index))
            existing = objects.get(object_key)
            if existing is not None:
                conflicts.append({
                    "object": name,
                    "kind": "duplicate_object_instance",
                    "existing": {"obis": existing["obis"], "class_id": existing["class_id"]},
                    "incoming": {"obis": obis, "class_id": class_id},
                })
                continue
            objects[object_key] = {
                "object": name,
                "obis": obis,
                "class_id": class_id,
                "source_table_ids": table_ids_for_row(row, index),
                "source_table_title": table_title_for_row(row, index),
                "source_item_id": first_source_item_id(row, index),
                "source_order": source_order_for_row(row, index),
                "meaning": str(fields.get(F_MEANING) or "").strip(),
                "domain": str(row.get("domain") or ""),
                "section_path": row.get("section_path") or [],
                "confidence": row.get("confidence"),
                "review_status": status_of(row, status_by_id),
                "source_refs": row.get("source_refs") or [],
                "source_atomic_requirements": [_row_id(row)],
                "attributes": [],
            }
            object_keys_by_name[name].append(object_key)
            if class_id:
                object_keys_by_class_id[class_id].append(object_key)

    # 2) 属性访问 → 挂到父对象
    for row in requirements:
        if row.get("requirement_type") != "cosem_attribute_access":
            continue
        source_attribute_requirements += 1
        fields = source_fields(row, index)
        obj_attr = str(row.get("object") or "").strip()
        parent, _, attr_inline = obj_attr.partition(".")
        raw_attr_name = str(fields.get(F_NAME) or attr_inline or "").strip()
        attr_name = canonical_attribute_name(parent, raw_attr_name)
        access_raw = str(fields.get(F_ACCESS) or "").strip()
        attribute = {
            "index": normalize_numeric(fields.get(F_INDEX)),
            "name": attr_name,
            "type": str(fields.get(F_TYPE) or "").strip(),
            "access": parse_access(access_raw),
            "access_raw": access_raw,
            "default": str(fields.get(F_OBIS) or "").strip(),
            "meaning": str(fields.get(F_MEANING) or "").strip(),
            "verification_method": str(row.get("verification_method") or ""),
            "confidence": row.get("confidence"),
            "ambiguity": bool(row.get("ambiguity")),
            "review_status": status_of(row, status_by_id),
            "source_refs": row.get("source_refs") or [],
            "source_atomic_requirements": [_row_id(row)],
        }
        parent_objs = find_parent_objects(parent, row, objects, object_keys_by_name, object_keys_by_class_id, index, attr_name)
        if not parent_objs:
            orphan_attributes.append({"parent": parent, **attribute})
        else:
            for parent_obj in parent_objs:
                template_parent = template_parent_for_attachment(parent, attr_name, parent_obj)
                is_class_template = template_parent is not None
                attached_attribute = dict(attribute)
                if is_class_template and str(parent_obj.get("object") or "") != parent:
                    attached_attribute["scope"] = "class_template"
                    attached_attribute["template_parent"] = template_parent
                    projected_class_attributes += 1
                parent_obj["attributes"].append(attached_attribute)
                for req_id in attribute["source_atomic_requirements"]:
                    if req_id and req_id not in parent_obj["source_atomic_requirements"]:
                        parent_obj["source_atomic_requirements"].append(req_id)

    # 3) 计量量纲单位（附录）
    for row in requirements:
        if row.get("requirement_type") != "measurement_quantity_unit":
            continue
        fields = source_fields(row, index)
        units.append({
            "quantity": str(row.get("object") or fields.get("Greatness_2") or "").strip(),
            "group": str(fields.get("Greatness") or "").strip(),
            "unit": str(fields.get("Unit") or "").strip(),
            "review_status": status_of(row, status_by_id),
            "source_refs": row.get("source_refs") or [],
        })

    object_list = sorted(objects.values(), key=lambda o: (o.get("source_order", ("~", 0, "")), o["obis"] or "~", o["object"]))
    attr_total = sum(len(o["attributes"]) for o in object_list) + len(orphan_attributes)
    unresolved_access: list[dict[str, Any]] = []
    for obj in object_list:
        for attr in obj["attributes"]:
            if attr_access_unresolved(attr):
                unresolved_access.append({
                    "object": obj["object"],
                    "obis": obj["obis"],
                    "class_id": obj["class_id"],
                    "attribute": attr["name"],
                    "access_raw": attr["access_raw"],
                    "source_refs": attr.get("source_refs") or [],
                })
    for attr in orphan_attributes:
        if attr_access_unresolved(attr):
            unresolved_access.append({
                "object": str(attr.get("parent") or ""),
                "obis": "",
                "class_id": "",
                "attribute": attr["name"],
                "access_raw": attr["access_raw"],
                "source_refs": attr.get("source_refs") or [],
            })
    return {
        "objects": object_list,
        "orphan_attributes": orphan_attributes,
        "units": units,
        "conflicts": conflicts,
        "unresolved_access": unresolved_access,
        "counts": {
            "objects": len(object_list),
            "attributes": attr_total,
            "attributes_attached": attr_total - len(orphan_attributes),
            "orphan_attributes": len(orphan_attributes),
            "units": len(units),
            "conflicts": len(conflicts),
            "unresolved_access": len(unresolved_access),
            "source_attribute_requirements": source_attribute_requirements,
            "projected_class_attributes": projected_class_attributes,
        },
    }


def _row_id(row: dict[str, Any]) -> str:
    return str(row.get("stable_req_id") or row.get("req_id") or row.get("requirement_id") or "").strip()


def first_source_item_id(row: dict[str, Any], index: dict[str, dict[str, Any]]) -> str:
    for ref in row.get("source_refs", []) or []:
        if str(ref) in index:
            return str(ref)
    return ""


def source_order_for_row(row: dict[str, Any], index: dict[str, dict[str, Any]]) -> tuple[str, int, str]:
    for ref in row.get("source_refs", []) or []:
        item = index.get(str(ref))
        if not item:
            continue
        table_id = str(item.get("table_id") or "")
        try:
            row_index = int(item.get("row_index") or 0)
        except (TypeError, ValueError):
            row_index = 0
        return (table_id, row_index, str(ref))
    return ("", 0, "")


def table_ids_for_row(row: dict[str, Any], index: dict[str, dict[str, Any]]) -> list[str]:
    table_ids: list[str] = []
    for ref in row.get("source_refs", []) or []:
        item = index.get(str(ref))
        table_id = str(item.get("table_id") or "") if item else ""
        if table_id and table_id not in table_ids:
            table_ids.append(table_id)
    return table_ids


def table_title_for_row(row: dict[str, Any], index: dict[str, dict[str, Any]]) -> str:
    """取该对象首个来源表的标题（如 'Table 33 - Energy registration objects'），
    供装配规格做细粒度溯源——section_path 常粗到整章（ABNT 所有对象表都在
    "20 Control of objects" 下），table_title 才是研发可读的业务分组。"""
    for ref in row.get("source_refs", []) or []:
        item = index.get(str(ref))
        title = str(item.get("table_title") or "").strip() if item else ""
        if title:
            return title
    return ""


def is_class_template_attribute(parent: str) -> bool:
    return parent in CLASS_LEVEL_ATTRIBUTE_NAMES


def canonical_attribute_name(parent: str, attr_name: str) -> str:
    allowed_attrs = CLASS_LEVEL_ATTRIBUTE_NAMES.get(parent)
    if not allowed_attrs:
        return attr_name
    normalized = normalize_attribute_name(attr_name)
    for allowed in allowed_attrs:
        if normalize_attribute_name(allowed) == normalized:
            return allowed
    return attr_name


def normalize_attribute_name(value: str) -> str:
    return "_".join(str(value or "").replace("-", "_").split()).lower()


def find_parent_objects(
    parent: str,
    row: dict[str, Any],
    objects: dict[tuple[str, str, str, str], dict[str, Any]],
    object_keys_by_name: dict[str, list[tuple[str, str, str, str]]],
    object_keys_by_class_id: dict[str, list[tuple[str, str, str, str]]],
    index: dict[str, dict[str, Any]],
    attr_name: str,
) -> list[dict[str, Any]]:
    keys = object_keys_by_name.get(parent) or []
    if keys:
        row_order = source_order_for_row(row, index)
        row_table = row_order[0]
        candidates = [objects[key] for key in keys]
        same_table_previous = [
            obj
            for obj in candidates
            if obj.get("source_order", ("", 0, ""))[0] == row_table
            and obj.get("source_order", ("", 0, ""))[1] <= row_order[1]
            and attribute_matches_parent_context(row, obj, index, attr_name)
        ]
        if same_table_previous:
            return [max(same_table_previous, key=lambda obj: obj.get("source_order", ("", 0, ""))[1])]

        previous = [
            obj
            for obj in candidates
            if obj.get("source_order", ("", 0, "")) <= row_order
            and attribute_matches_parent_context(row, obj, index, attr_name)
        ]
        if previous:
            return [max(previous, key=lambda obj: obj.get("source_order", ("", 0, "")))]
        valid_candidates = [obj for obj in candidates if attribute_matches_parent_context(row, obj, index, attr_name)]
        if valid_candidates:
            return [valid_candidates[0]]

    same_table_prefix = same_table_prefix_parent_objects(parent, row, objects, index, attr_name)
    if same_table_prefix:
        return same_table_prefix

    same_table_attribute_parent = same_table_attribute_name_parent_objects(parent, row, objects, index, attr_name)
    if same_table_attribute_parent:
        return same_table_attribute_parent

    continuation_template_parent = immediate_previous_table_attribute_parent_objects(parent, row, objects, index, attr_name)
    if continuation_template_parent:
        return continuation_template_parent

    opening_continuation_parent = opening_table_attribute_parent_objects(parent, row, objects, index, attr_name)
    if opening_continuation_parent:
        return opening_continuation_parent

    attached_continuation_parent = previous_table_attached_attribute_parent_objects(row, objects, index, attr_name)
    if attached_continuation_parent:
        return attached_continuation_parent

    return class_template_parent_objects(parent, row, objects, object_keys_by_class_id, index, attr_name)


def template_parent_for_attachment(parent: str, attr_name: str, parent_obj: dict[str, Any]) -> str | None:
    class_name = class_name_for_id(str(parent_obj.get("class_id") or ""))
    if is_class_template_attribute(parent):
        if class_name == parent:
            return parent
        return template_parent_for_class_attribute(parent_obj, attr_name)
    object_name = str(parent_obj.get("object") or "")
    if normalized_name(object_name).startswith(normalized_name(parent)):
        return None
    return template_parent_for_class_attribute(parent_obj, attr_name)


def template_parent_for_class_attribute(parent_obj: dict[str, Any], attr_name: str) -> str | None:
    class_name = class_name_for_id(str(parent_obj.get("class_id") or ""))
    allowed_attrs = CLASS_LEVEL_ATTRIBUTE_NAMES.get(class_name, set())
    if canonical_allowed_attribute(allowed_attrs, attr_name) is None:
        return None
    return class_name


def class_template_parent_objects(
    parent: str,
    row: dict[str, Any],
    objects: dict[tuple[str, str, str, str], dict[str, Any]],
    object_keys_by_class_id: dict[str, list[tuple[str, str, str, str]]],
    index: dict[str, dict[str, Any]],
    attr_name: str,
) -> list[dict[str, Any]]:
    class_id = CLASS_NAME_TO_ID.get(parent)
    allowed_attrs = CLASS_LEVEL_ATTRIBUTE_NAMES.get(parent)
    if not class_id or allowed_attrs is None or canonical_allowed_attribute(allowed_attrs, attr_name) is None:
        return class_template_parent_objects_by_attribute(row, objects, index, attr_name)

    candidates = [objects[key] for key in object_keys_by_class_id.get(class_id, [])]
    if not candidates:
        return class_template_parent_objects_by_attribute(row, objects, index, attr_name)

    row_order = source_order_for_row(row, index)
    row_table = row_order[0]
    if row_table:
        same_table_previous = [
            obj
            for obj in candidates
            if obj.get("source_order", ("", 0, ""))[0] == row_table
            and obj.get("source_order", ("", 0, ""))[1] <= row_order[1]
            and attribute_matches_parent_context(row, obj, index, attr_name)
        ]
        if same_table_previous:
            return [max(same_table_previous, key=lambda obj: obj.get("source_order", ("", 0, ""))[1])]

        previous_table = immediate_previous_table_candidate(row_table, row, candidates, index, attr_name)
        if previous_table is not None:
            return [previous_table]

    if len(candidates) == 1:
        return candidates
    return class_template_parent_objects_by_attribute(row, objects, index, attr_name)


def class_template_parent_objects_by_attribute(
    row: dict[str, Any],
    objects: dict[tuple[str, str, str, str], dict[str, Any]],
    index: dict[str, dict[str, Any]],
    attr_name: str,
) -> list[dict[str, Any]]:
    row_order = source_order_for_row(row, index)
    row_table = row_order[0]
    if not row_table:
        return []
    matches: list[dict[str, Any]] = []
    following_matches: list[dict[str, Any]] = []
    for obj in objects.values():
        object_order = obj.get("source_order", ("", 0, ""))
        if object_order[0] != row_table:
            continue
        if template_parent_for_class_attribute(obj, attr_name) is None:
            continue
        if not attribute_matches_parent_context(row, obj, index, attr_name):
            continue
        matches.append(obj)
        if object_order[1] > row_order[1]:
            following_matches.append(obj)
    if len(matches) == 1:
        return matches
    if following_matches:
        return [min(following_matches, key=lambda obj: obj.get("source_order", ("", 0, ""))[1])]
    return []


def immediate_previous_table_candidate(
    row_table: str,
    row: dict[str, Any],
    candidates: list[dict[str, Any]],
    index: dict[str, dict[str, Any]],
    attr_name: str,
) -> dict[str, Any] | None:
    row_table_number = table_sequence_number(row_table)
    if row_table_number is None:
        return None
    previous_candidates: list[dict[str, Any]] = []
    for obj in candidates:
        object_order = obj.get("source_order", ("", 0, ""))
        object_table = str(object_order[0] or "")
        object_table_number = table_sequence_number(object_table)
        if object_table_number is None or row_table_number - object_table_number != 1:
            continue
        if not attribute_matches_parent_context(row, obj, index, attr_name):
            continue
        previous_candidates.append(obj)
    if not previous_candidates:
        return None
    return max(previous_candidates, key=lambda obj: obj.get("source_order", ("", 0, ""))[1])


def table_sequence_number(table_id: str) -> int | None:
    suffix = ""
    for char in reversed(str(table_id or "")):
        if not char.isdigit():
            break
        suffix = char + suffix
    if not suffix:
        return None
    return int(suffix)


def immediate_previous_table_attribute_parent_objects(
    parent: str,
    row: dict[str, Any],
    objects: dict[tuple[str, str, str, str], dict[str, Any]],
    index: dict[str, dict[str, Any]],
    attr_name: str,
) -> list[dict[str, Any]]:
    row_order = source_order_for_row(row, index)
    row_table_number = table_sequence_number(row_order[0])
    if row_table_number is None:
        return []
    matches: list[dict[str, Any]] = []
    for obj in objects.values():
        object_order = obj.get("source_order", ("", 0, ""))
        object_table_number = table_sequence_number(str(object_order[0] or ""))
        if object_table_number is None or row_table_number - object_table_number != 1:
            continue
        if template_parent_for_attachment(parent, attr_name, obj) is None:
            continue
        if not attribute_matches_parent_context(row, obj, index, attr_name):
            continue
        matches.append(obj)
    if not matches:
        return []
    return [max(matches, key=lambda obj: obj.get("source_order", ("", 0, ""))[1])]


def opening_table_attribute_parent_objects(
    parent: str,
    row: dict[str, Any],
    objects: dict[tuple[str, str, str, str], dict[str, Any]],
    index: dict[str, dict[str, Any]],
    attr_name: str,
) -> list[dict[str, Any]]:
    row_order = source_order_for_row(row, index)
    row_table_number = table_sequence_number(row_order[0])
    if row_table_number is None or row_order[1] > 3:
        return []
    previous_table_candidates: list[dict[str, Any]] = []
    same_table_previous_objects = False
    for obj in objects.values():
        object_order = obj.get("source_order", ("", 0, ""))
        object_table_number = table_sequence_number(str(object_order[0] or ""))
        if object_order[0] == row_order[0] and object_order[1] <= row_order[1]:
            same_table_previous_objects = True
        if object_table_number is None or row_table_number - object_table_number != 1:
            continue
        if template_parent_for_attachment(parent, attr_name, obj) is None:
            continue
        if not attribute_matches_parent_context(row, obj, index, attr_name):
            continue
        previous_table_candidates.append(obj)
    if same_table_previous_objects or not previous_table_candidates:
        return []
    return [max(previous_table_candidates, key=lambda obj: obj.get("source_order", ("", 0, ""))[1])]


def previous_table_attached_attribute_parent_objects(
    row: dict[str, Any],
    objects: dict[tuple[str, str, str, str], dict[str, Any]],
    index: dict[str, dict[str, Any]],
    attr_name: str,
) -> list[dict[str, Any]]:
    row_order = source_order_for_row(row, index)
    row_table = row_order[0]
    row_table_number = table_sequence_number(row_table)
    if row_table_number is None or table_has_object_before_or_after(row_table, objects):
        return []
    normalized_attr = normalize_attribute_name(attr_name)
    for distance in range(1, 4):
        matches: list[dict[str, Any]] = []
        for obj in objects.values():
            object_order = obj.get("source_order", ("", 0, ""))
            object_table_number = table_sequence_number(str(object_order[0] or ""))
            if object_table_number is None or row_table_number - object_table_number != distance:
                continue
            if not any(normalize_attribute_name(attr.get("name", "")) == normalized_attr for attr in obj.get("attributes", [])):
                continue
            if template_parent_for_class_attribute(obj, attr_name) is None:
                continue
            matches.append(obj)
        if matches:
            return [max(matches, key=lambda obj: obj.get("source_order", ("", 0, ""))[1])]
    return []


def table_has_object_before_or_after(table_id: str, objects: dict[tuple[str, str, str, str], dict[str, Any]]) -> bool:
    return any(obj.get("source_order", ("", 0, ""))[0] == table_id for obj in objects.values())


def same_table_prefix_parent_objects(
    parent: str,
    row: dict[str, Any],
    objects: dict[tuple[str, str, str, str], dict[str, Any]],
    index: dict[str, dict[str, Any]],
    attr_name: str,
) -> list[dict[str, Any]]:
    row_order = source_order_for_row(row, index)
    row_table = row_order[0]
    if not parent or not row_table:
        return []
    matches: list[dict[str, Any]] = []
    normalized_parent = normalized_name(parent)
    for obj in objects.values():
        object_order = obj.get("source_order", ("", 0, ""))
        if object_order[0] != row_table or object_order[1] > row_order[1]:
            continue
        object_name = str(obj.get("object") or "")
        if not normalized_name(object_name).startswith(normalized_parent):
            continue
        class_id = str(obj.get("class_id") or "")
        allowed_attrs = CLASS_LEVEL_ATTRIBUTE_NAMES.get(class_name_for_id(class_id) or "", set())
        if canonical_allowed_attribute(allowed_attrs, attr_name) is None:
            continue
        if attribute_matches_parent_context(row, obj, index, attr_name):
            matches.append(obj)
    if not matches:
        return []
    return [max(matches, key=lambda obj: obj.get("source_order", ("", 0, ""))[1])]


def same_table_attribute_name_parent_objects(
    parent: str,
    row: dict[str, Any],
    objects: dict[tuple[str, str, str, str], dict[str, Any]],
    index: dict[str, dict[str, Any]],
    attr_name: str,
) -> list[dict[str, Any]]:
    row_order = source_order_for_row(row, index)
    row_table = row_order[0]
    if not row_table or normalize_attribute_name(parent) != normalize_attribute_name(attr_name):
        return []
    matches: list[dict[str, Any]] = []
    for obj in objects.values():
        object_order = obj.get("source_order", ("", 0, ""))
        if object_order[0] != row_table or object_order[1] > row_order[1]:
            continue
        class_name = class_name_for_id(str(obj.get("class_id") or ""))
        allowed_attrs = CLASS_LEVEL_ATTRIBUTE_NAMES.get(class_name, set())
        if canonical_allowed_attribute(allowed_attrs, attr_name) is not None:
            matches.append(obj)
    if not matches:
        return []
    return [max(matches, key=lambda obj: obj.get("source_order", ("", 0, ""))[1])]


def normalized_name(value: str) -> str:
    return " ".join(str(value or "").replace(".", " ").split()).lower()


OBIS_HEAD = re.compile(r"\d+-\d+:")


def split_obis_values(raw: Any) -> list[str]:
    """把可能含多个 OBIS 的源单元格拆成多个规范化 OBIS。

    ABNT 源表有时把同一计量对象登记在两套编码下（主码 + 94.55 国别码），两码同处一个单元格、
    以空格分隔。检测依据：仅当出现 >=2 个 'A-B:' 头时才拆（多 OBIS）；否则按
    normalize_obis_value 的单串处理（保留 Phase 1 的"空格=丢失的分隔点"还原，
    不影响其余单 OBIS 行）。
    """
    text = " ".join(str(raw or "").split()).strip()
    if len(OBIS_HEAD.findall(text)) >= 2:
        parts = re.split(r"(?=\d+-\d+:)", text)
        normalized: list[str] = []
        for part in parts:
            value = normalize_obis_value(part)
            if value:
                normalized.append(value)
        return normalized
    value = normalize_obis_value(text)
    return [value] if value else []


def normalize_obis_value(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    if " " not in text:
        return _normalize_single_obis_value(text)
    # 含空格：在 OBIS 形态里，值组区的空格几乎总是丢失的分隔点（如 "0 4" 实为 "0.4"）。
    # 把空格直接还原为点以保留分隔证据，而不是先 compact 成相邻数字——后者会迫使下游用
    # 无证据的数字拆分，可能把合法的 2 位值组（如 96）错切成 9.6，腐蚀 OBIS 码。
    head, sep, tail = text.partition(":")
    if sep:
        tail_dotted = re.sub(r"\s+", ".", tail.strip())
        text = f"{head.replace(' ', '')}:{tail_dotted}"
    compact = text.replace(" ", "")
    if re.fullmatch(r"\d+-\d+:[0-9A-Za-z]+(?:\.[0-9A-Za-z]+){2,3}", compact):
        return _normalize_single_obis_value(compact)
    return text


def _normalize_single_obis_value(value: str) -> str:
    text = str(value or "").strip()
    # 修复值组与 A-B 头颠倒的写法（"A:B-C.D.E.F" -> "A-B:C.D.E.F"）——有依据的格式归一。
    match = re.fullmatch(r"(\d+):(\d+)-([0-9A-Za-z]+(?:\.[0-9A-Za-z]+){3})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}:{match.group(3)}"
    # 刻意不做"把 2 位值组拆成两个单数字"的无证据数字拆分。历史实现会把
    # "0-0:96.1.0" 静默改成 "0-0:9.6.1.0"——把合法的 C=96 腐蚀成 9.6，违反
    # "OBIS 码错一位即严重缺陷" 的纪律。缺分隔点的修复改由 normalize_obis_value
    # 的空格还原路径处理（仅在有空格证据时），不再盲拆相邻数字。
    return text


def class_name_for_id(class_id: str) -> str:
    for name, candidate_id in CLASS_NAME_TO_ID.items():
        if str(candidate_id) == str(class_id):
            return name
    return ""


def canonical_allowed_attribute(allowed_attrs: set[str], attr_name: str) -> str | None:
    normalized = normalize_attribute_name(attr_name)
    for allowed in allowed_attrs:
        if normalize_attribute_name(allowed) == normalized:
            return allowed
    return None


def find_parent_object(
    parent: str,
    row: dict[str, Any],
    objects: dict[tuple[str, str, str, str], dict[str, Any]],
    object_keys_by_name: dict[str, list[tuple[str, str, str, str]]],
    index: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    result = find_parent_objects(parent, row, objects, object_keys_by_name, defaultdict(list), index, "")
    return result[0] if result else None


PROFILE_ATTRIBUTE_NAMES = {
    "buffer",
    "capture_objects",
    "capture_period",
    "sort_method",
    "sort_object",
    "entries_in_use",
    "profile_entries",
}


def attribute_matches_parent_context(
    row: dict[str, Any],
    parent_obj: dict[str, Any],
    index: dict[str, dict[str, Any]],
    attr_name: str,
) -> bool:
    parent_table_ids = set(parent_obj.get("source_table_ids") or [])
    class_id = str(parent_obj.get("class_id") or "")
    if str(attr_name or "").strip() in PROFILE_ATTRIBUTE_NAMES and class_id != "7":
        return False
    if not parent_table_ids:
        return True
    row_table_ids = set(table_ids_for_row(row, index))
    if not row_table_ids:
        return True
    if parent_table_ids & row_table_ids:
        return True
    row_order = source_order_for_row(row, index)
    parent_order = parent_obj.get("source_order", ("", 0, ""))
    return parent_order <= row_order


# --- 渲染 -----------------------------------------------------------------------

def write_object_model(out_dir: Path, model: dict[str, Any]) -> list[str]:
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    (out_dir / "cosem_object_model.json").write_text(
        json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    written.append("cosem_object_model.json")

    (out_dir / "cosem_object_model.md").write_text(render_markdown(model), encoding="utf-8")
    written.append("cosem_object_model.md")

    write_attribute_matrix_csv(out_dir / "cosem_attribute_matrix.csv", model)
    written.append("cosem_attribute_matrix.csv")
    return written


def render_markdown(model: dict[str, Any]) -> str:
    counts = model["counts"]
    lines = [
        "# COSEM 对象模型 / 数据字典",
        "",
        "> 由原子需求确定性装配（cosem_object_instance + cosem_attribute_access），可逐字段溯源。",
        "",
        f"- 对象数：**{counts['objects']}**",
        f"- 属性数：**{counts['attributes']}**（已挂载 {counts['attributes_attached']} / 孤立 {counts['orphan_attributes']}）",
        f"- 计量单位条目：{counts['units']}　冲突：{counts['conflicts']}",
        "",
    ]
    # 按 domain 分组
    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obj in model["objects"]:
        by_domain[obj["domain"] or "（未分类）"].append(obj)

    for domain in sorted(by_domain):
        lines.append(f"## 域：{domain}")
        lines.append("")
        for obj in by_domain[domain]:
            header = f"### {obj['object']} — OBIS `{obj['obis']}` / CL `{obj['class_id']}`"
            lines.append(header)
            if obj["meaning"]:
                lines.append(f"_{obj['meaning']}_")
            lines.append("")
            if obj["attributes"]:
                lines.append("| # | 属性 | 类型 | RC | PC | SC | LC | 默认值 |")
                lines.append("|---|------|------|----|----|----|----|--------|")
                for attr in obj["attributes"]:
                    rc, pc, sc, lc = access_cells(attr)
                    lines.append(
                        f"| {attr['index']} | {attr['name']} | {attr['type']} | "
                        f"{rc} | {pc} | {sc} | {lc} | {attr['default']} |"
                    )
                lines.append("")

    if model["conflicts"]:
        lines.append("## ⚠ 冲突")
        lines.append("")
        for c in model["conflicts"]:
            lines.append(f"- `{c['object']}`（{c['kind']}）：已记 {c['existing']} ↔ 新 {c['incoming']}")
        lines.append("")

    if model["orphan_attributes"]:
        by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for attr in model["orphan_attributes"]:
            by_parent[attr["parent"] or "（空）"].append(attr)
        lines.append(f"## 类级 / 未匹配父对象的属性定义（按父名分组，共 {len(model['orphan_attributes'])} 条）")
        lines.append("")
        lines.append("> 父名未出现在对象实例表中——多为 COSEM **类级**属性模板（如 Register / Profile Generic），"
                     "少数为抽取噪声（父名==属性名）。P1.1 可按 IC 类归并。")
        lines.append("")
        for parent in sorted(by_parent, key=lambda p: (-len(by_parent[p]), p)):
            attrs = by_parent[parent]
            lines.append(f"### {parent}（{len(attrs)}）")
            lines.append("| # | 属性 | 类型 | RC | PC | SC | LC | 默认值 |")
            lines.append("|---|------|------|----|----|----|----|--------|")
            for attr in attrs:
                rc, pc, sc, lc = access_cells(attr)
                lines.append(
                    f"| {attr['index']} | {attr['name']} | {attr['type']} | "
                    f"{rc} | {pc} | {sc} | {lc} | {attr['default']} |"
                )
            lines.append("")

    if model["units"]:
        lines.append("## 附录：计量量纲单位")
        lines.append("")
        lines.append("| 量 | 组 | 单位 |")
        lines.append("|----|----|------|")
        for unit in model["units"]:
            lines.append(f"| {unit['quantity']} | {unit['group']} | {unit['unit']} |")
        lines.append("")

    if model.get("unresolved_access"):
        lines.append(f"## ⚠ 访问权限未解析（待专家确认，共 {len(model['unresolved_access'])} 条）")
        lines.append("")
        lines.append("> 原始访问串无法切分为 RC/PC/SC/LC 四关联，已在属性表中留空以免错列；"
                     "以下保留原始串供核对。")
        lines.append("")
        lines.append("| 对象 | OBIS | 属性 | 原始访问串 |")
        lines.append("|------|------|------|-----------|")
        for item in model["unresolved_access"]:
            lines.append(
                f"| {item['object']} | {item['obis']} | {item['attribute']} | `{item['access_raw']}` |"
            )
        lines.append("")

    return "\n".join(lines)


def write_attribute_matrix_csv(path: Path, model: dict[str, Any]) -> None:
    columns = [
        "object", "obis", "class_id", "attr_index", "attribute", "type",
        "RC", "PC", "SC", "LC", "access_raw", "default", "verification_method",
        "confidence", "ambiguity", "review_status", "source_refs",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for obj in model["objects"]:
            for attr in obj["attributes"]:
                rc, pc, sc, lc = access_cells(attr)
                row = {
                    "object": obj["object"],
                    "obis": obj["obis"],
                    "class_id": obj["class_id"],
                    "attr_index": attr["index"],
                    "attribute": attr["name"],
                    "type": attr["type"],
                    "RC": rc,
                    "PC": pc,
                    "SC": sc,
                    "LC": lc,
                    "access_raw": attr["access_raw"],
                    "default": attr["default"],
                    "verification_method": attr["verification_method"],
                    "confidence": attr["confidence"],
                    "ambiguity": attr["ambiguity"],
                    "review_status": attr["review_status"],
                    "source_refs": "; ".join(str(r) for r in attr["source_refs"]),
                }
                writer.writerow({key: formula_safe(value) for key, value in row.items()})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble a COSEM object model / data dictionary from atomizer output.")
    parser.add_argument("--out", type=Path, required=True, help="Atomizer output directory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model = build_object_model(args.out)
    written = write_object_model(args.out, model)
    print(json.dumps({"out": str(args.out.expanduser().resolve()), "written": written, "counts": model["counts"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
