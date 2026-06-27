"""KB 覆盖度报表：统计 Blue Book 知识库的实际细粒度覆盖。

纯读取已编译 KB 的 JSON，不编造任何数据。输出三张表：
- Part 1 每个 OBIS table 的 row-level 覆盖数
- Part 2 每个 interface class 的 enrichment level（rich vs catalogue-only seed）
- object instance 按 class_id / medium / table_no 的分布

用途：交接要求的"覆盖仪表"。每批 KB 扩展后跑一次，对比 before/after，
并用于发现"目录已建但 row-level 仍空"的真实缺口。
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def _table_no(entry: dict[str, Any]):
    """取 instance 的 Blue Book table 号（可能在顶层 blue_book_table_ref 或 metadata）。"""
    if entry.get("table_no") is not None:
        return entry.get("table_no")
    if entry.get("table") is not None:
        return entry.get("table")
    bt = entry.get("blue_book_table_ref")
    if isinstance(bt, dict) and bt.get("table_no") is not None:
        return bt.get("table_no")
    meta = entry.get("metadata")
    if isinstance(meta, dict):
        return meta.get("table_no") or meta.get("table")
    return None


CATALOGUE_ONLY_OBIS_TABLE_FAMILIES = {
    "obis_code_structure",
    "specific_code_ranges",
    "value_group_definition",
    "tariff_rates",
}


def _object_family(entry: dict[str, Any]) -> str:
    family = entry.get("object_family")
    if family is None and isinstance(entry.get("metadata"), dict):
        family = entry["metadata"].get("object_family")
    return str(family or "").strip()


def _expects_row_level_instances(entry: dict[str, Any]) -> bool:
    return _object_family(entry) not in CATALOGUE_ONLY_OBIS_TABLE_FAMILIES


def build_coverage_report(kb_path: Path) -> dict[str, Any]:
    """读取单个编译 KB JSON，返回覆盖度报表。"""
    path = kb_path.expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = list(payload.get("entries") or [])
    by_type = Counter(str(e.get("type") or "unknown") for e in entries)

    instances = [e for e in entries if e.get("type") == "cosem_object_instance"]
    tables_catalogue = [e for e in entries if e.get("type") == "obis_table"]
    classes = [e for e in entries if e.get("type") == "cosem_interface_class"]

    # Part 1 row-level instance 覆盖，按 table_no
    by_table: dict[Any, int] = {}
    for inst in instances:
        tn = _table_no(inst)
        key = tn if tn is not None else "?"
        by_table[key] = by_table.get(key, 0) + 1

    catalogue_by_table_no = {
        _table_no(t): t for t in tables_catalogue if _table_no(t) is not None
    }

    # 已知 OBIS table catalogue 条目（说明这些 table 至少有目录级覆盖）
    known_table_nos = sorted(set(catalogue_by_table_no) | {tn for tn in by_table if tn != "?"})

    catalogue_only_table_nos = sorted(
        tn for tn, entry in catalogue_by_table_no.items()
        if by_table.get(tn, 0) == 0 and not _expects_row_level_instances(entry)
    )

    # 哪些 table 有目录但 row-level 为空
    tables_with_catalogue_no_rows = sorted(
        tn for tn in known_table_nos
        if tn != "?"
        and by_table.get(tn, 0) == 0
        and tn not in catalogue_only_table_nos
    )

    # Part 2 class enrichment level
    rich_classes = 0
    seed_classes = 0
    seed_class_ids: list[Any] = []
    for c in classes:
        attrs = c.get("attributes")
        meths = c.get("methods")
        has_rich = (isinstance(attrs, list) and len(attrs) > 0) or (
            isinstance(meths, list) and len(meths) > 0
        )
        if has_rich:
            rich_classes += 1
        else:
            seed_classes += 1
            seed_class_ids.append(c.get("class_id") or c.get("id") or c.get("name"))

    # semantic depth: 类有多少带 access_rights 的属性 / 是否有 behavior_notes / access_semantics
    attrs_with_access_rights = 0
    classes_with_behavior_notes = 0
    classes_with_access_semantics = 0
    classes_with_access_rights = 0
    for c in classes:
        attrs = c.get("attributes")
        if isinstance(attrs, list):
            for a in attrs:
                if isinstance(a, dict) and a.get("access_rights"):
                    attrs_with_access_rights += 1
            if any(isinstance(a, dict) and a.get("access_rights") for a in attrs):
                classes_with_access_rights += 1
        if c.get("behavior_notes") or c.get("access_semantics"):
            if c.get("behavior_notes"):
                classes_with_behavior_notes += 1
            if c.get("access_semantics"):
                classes_with_access_semantics += 1

    # instance 分布
    by_medium = Counter(str(e.get("medium") or "?") for e in instances)
    by_class_id = Counter(str(e.get("likely_interface_class_id") or "?") for e in instances)

    return {
        "kb_file": str(path),
        "kb_id": payload.get("kb_id"),
        "total_entries": len(entries),
        "entries_by_type": dict(by_type.most_common()),
        "part1_obis": {
            "table_catalogue_entries": len(tables_catalogue),
            "row_level_instances": len(instances),
            "instances_by_table_no": dict(sorted(by_table.items(), key=lambda x: str(x[0]))),
            "tables_with_catalogue_but_no_rows": tables_with_catalogue_no_rows,
            "tables_not_expected_to_have_row_instances": catalogue_only_table_nos,
        },
        "part2_interface_classes": {
            "total": len(classes),
            "with_attributes_or_methods": rich_classes,
            "catalogue_only_seed": seed_classes,
            "seed_class_ids": seed_class_ids,
            "semantic_depth": {
                "classes_with_access_rights": classes_with_access_rights,
                "classes_with_behavior_notes": classes_with_behavior_notes,
                "classes_with_access_semantics": classes_with_access_semantics,
                "attributes_with_access_rights": attrs_with_access_rights,
            },
        },
        "instance_distribution": {
            "by_medium": dict(by_medium),
            "by_likely_interface_class_id": dict(sorted(by_class_id.items(), key=lambda x: str(x[0]))),
        },
    }


def render_report(report: dict[str, Any]) -> str:
    """把覆盖度报表渲染成人读的 markdown。"""
    lines: list[str] = []
    lines.append(f"# KB Coverage Report — `{report['kb_id']}`")
    lines.append("")
    lines.append(f"- Source: `{report['kb_file']}`")
    lines.append(f"- Total entries: **{report['total_entries']}**")
    lines.append("")
    lines.append("## Entries by type")
    for k, v in report["entries_by_type"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    p1 = report["part1_obis"]
    lines.append("## Part 1 — Blue Book OBIS")
    lines.append(f"- Table catalogue entries: {p1['table_catalogue_entries']}")
    lines.append(f"- Row-level instances: **{p1['row_level_instances']}**")
    lines.append("- Instances by table_no:")
    for tn, cnt in p1["instances_by_table_no"].items():
        lines.append(f"  - table {tn}: {cnt}")
    if p1["tables_with_catalogue_but_no_rows"]:
        lines.append("- ⚠ Tables with catalogue but NO row-level instances: "
                     + ", ".join(f"table {tn}" for tn in p1["tables_with_catalogue_but_no_rows"]))
    if p1.get("tables_not_expected_to_have_row_instances"):
        lines.append("- Catalogue/structure tables not expected to have row-level instances: "
                     + ", ".join(f"table {tn}" for tn in p1["tables_not_expected_to_have_row_instances"]))
    lines.append("")
    p2 = report["part2_interface_classes"]
    lines.append("## Part 2 — COSEM Interface Classes")
    lines.append(f"- Total: {p2['total']}")
    lines.append(f"- With attributes/methods (rich): **{p2['with_attributes_or_methods']}**")
    lines.append(f"- Catalogue-only (seed): {p2['catalogue_only_seed']}")
    if p2["seed_class_ids"]:
        lines.append("- Seed class ids: " + ", ".join(str(x) for x in p2["seed_class_ids"]))
    sd = p2.get("semantic_depth", {})
    if sd:
        lines.append("- Semantic depth:")
        lines.append(f"  - Classes with attribute access_rights: **{sd.get('classes_with_access_rights', 0)}**")
        lines.append(f"  - Classes with behavior_notes: **{sd.get('classes_with_behavior_notes', 0)}**")
        lines.append(f"  - Classes with access_semantics: **{sd.get('classes_with_access_semantics', 0)}**")
        lines.append(f"  - Total attributes with access_rights: {sd.get('attributes_with_access_rights', 0)}")
    lines.append("")
    dist = report["instance_distribution"]
    lines.append("## Object instance distribution")
    lines.append("- By medium: " + ", ".join(f"{k}={v}" for k, v in dist["by_medium"].items()))
    lines.append("- By likely interface class id: "
                 + ", ".join(f"CL {k}={v}" for k, v in dist["by_likely_interface_class_id"].items()))
    lines.append("")
    return "\n".join(lines)
