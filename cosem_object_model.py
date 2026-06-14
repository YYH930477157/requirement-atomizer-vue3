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
from collections import defaultdict
from pathlib import Path
from typing import Any

from text_normalize import normalize_numeric


# 源表字段键（取自真实 ABNT 输出）
F_NAME = "Object/attribute name"
F_CLASS = "CL"
F_OBIS = "Value"          # 对象行：OBIS；属性行：默认值
F_TYPE = "Type"
F_ACCESS = "Access rights RC/PC/SC/LC"
F_MEANING = "Meaning"
F_INDEX = "#"
ASSOCIATIONS = ("RC", "PC", "SC", "LC")


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


def build_object_model(out_dir: Path) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    requirements = read_jsonl(out_dir / "atomic_requirements.jsonl")
    index = build_source_index(read_jsonl(out_dir / "table_items.jsonl"))
    status_by_id = review_status_by_id(read_jsonl(out_dir / "review_states.jsonl"))

    objects: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    orphan_attributes: list[dict[str, Any]] = []
    units: list[dict[str, Any]] = []

    # 1) 对象实例
    for row in requirements:
        if row.get("requirement_type") != "cosem_object_instance":
            continue
        fields = source_fields(row, index)
        name = str(row.get("object") or fields.get(F_NAME) or "").strip()
        if not name:
            continue
        obis = str(fields.get(F_OBIS) or "").strip()
        class_id = str(fields.get(F_CLASS) or "").strip()
        existing = objects.get(name)
        if existing is not None:
            if (existing["obis"], existing["class_id"]) != (obis, class_id):
                conflicts.append({
                    "object": name,
                    "kind": "duplicate_object_instance",
                    "existing": {"obis": existing["obis"], "class_id": existing["class_id"]},
                    "incoming": {"obis": obis, "class_id": class_id},
                })
            continue
        objects[name] = {
            "object": name,
            "obis": obis,
            "class_id": class_id,
            "meaning": str(fields.get(F_MEANING) or "").strip(),
            "domain": str(row.get("domain") or ""),
            "section_path": row.get("section_path") or [],
            "confidence": row.get("confidence"),
            "review_status": status_of(row, status_by_id),
            "source_refs": row.get("source_refs") or [],
            "attributes": [],
        }

    # 2) 属性访问 → 挂到父对象
    for row in requirements:
        if row.get("requirement_type") != "cosem_attribute_access":
            continue
        fields = source_fields(row, index)
        obj_attr = str(row.get("object") or "").strip()
        parent, _, attr_inline = obj_attr.partition(".")
        attr_name = str(fields.get(F_NAME) or attr_inline or "").strip()
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
        }
        parent_obj = objects.get(parent)
        if parent_obj is None:
            orphan_attributes.append({"parent": parent, **attribute})
        else:
            parent_obj["attributes"].append(attribute)

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

    object_list = sorted(objects.values(), key=lambda o: (o["obis"] or "~", o["object"]))
    attr_total = sum(len(o["attributes"]) for o in object_list) + len(orphan_attributes)
    return {
        "objects": object_list,
        "orphan_attributes": orphan_attributes,
        "units": units,
        "conflicts": conflicts,
        "counts": {
            "objects": len(object_list),
            "attributes": attr_total,
            "attributes_attached": attr_total - len(orphan_attributes),
            "orphan_attributes": len(orphan_attributes),
            "units": len(units),
            "conflicts": len(conflicts),
        },
    }


# --- 渲染 -----------------------------------------------------------------------

def write_object_model(out_dir: Path, model: dict[str, Any]) -> list[str]:
    out_dir = out_dir.expanduser().resolve()
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
                    access = attr["access"] or {}
                    lines.append(
                        f"| {attr['index']} | {attr['name']} | {attr['type']} | "
                        f"{access.get('RC', attr['access_raw'])} | {access.get('PC', '')} | "
                        f"{access.get('SC', '')} | {access.get('LC', '')} | {attr['default']} |"
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
                access = attr["access"] or {}
                lines.append(
                    f"| {attr['index']} | {attr['name']} | {attr['type']} | "
                    f"{access.get('RC', attr['access_raw'])} | {access.get('PC', '')} | "
                    f"{access.get('SC', '')} | {access.get('LC', '')} | {attr['default']} |"
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

    return "\n".join(lines)


def write_attribute_matrix_csv(path: Path, model: dict[str, Any]) -> None:
    columns = [
        "object", "obis", "class_id", "attr_index", "attribute", "type",
        "RC", "PC", "SC", "LC", "default", "verification_method",
        "confidence", "ambiguity", "review_status", "source_refs",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for obj in model["objects"]:
            for attr in obj["attributes"]:
                access = attr["access"] or {}
                writer.writerow({
                    "object": obj["object"],
                    "obis": obj["obis"],
                    "class_id": obj["class_id"],
                    "attr_index": attr["index"],
                    "attribute": attr["name"],
                    "type": attr["type"],
                    "RC": access.get("RC", attr["access_raw"]),
                    "PC": access.get("PC", ""),
                    "SC": access.get("SC", ""),
                    "LC": access.get("LC", ""),
                    "default": attr["default"],
                    "verification_method": attr["verification_method"],
                    "confidence": attr["confidence"],
                    "ambiguity": attr["ambiguity"],
                    "review_status": attr["review_status"],
                    "source_refs": "; ".join(str(r) for r in attr["source_refs"]),
                })


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
