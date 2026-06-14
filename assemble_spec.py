"""P5：装配完整《DLMS/COSEM 实现规格》—— 把 P1/P2/P3 三层统一成公司标准需求列表格式。

- P1 对象模型 → 每个 COSEM 对象一条需求，属性访问表进 threshold_table
- P2 访问/安全 → 关联安全矩阵 / 能力矩阵 / 安全套件 / 策略枚举 各一条需求（矩阵进 threshold_table）
- P3 行为 → 复用 requirement_schema 的行为需求
- 全部经 requirement_schema.make_doc 合并：全局 REQ-NNN 重编号 + 重算 analysis

产出 dlms_cosem_spec_requirements.json，可直接喂公司 validate/xmind/excel 工具链。
用法：python -m assemble_spec --out <atomizer 输出目录> [--reviews <reviews.jsonl>]
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
from typing import Any

import requirement_schema as rs
from cosem_access_security import build_access_security
from cosem_behavior_spec import build_behavior_spec
from cosem_object_model import build_object_model


_DOMAIN_LABEL = {
    "security": "安全", "access_control": "安全", "metering": "计量",
    "communication": "通信协议", "time": "时钟", "alarm": "事件记录",
    "event": "事件记录", "tariff": "费率",
}


def _req(*, title: str, description: str, source_quote: str, labels: list[str],
         priority: str = "P1", source_section: str = "", threshold_table: dict | None = None,
         acceptance: list[str] | None = None, notes: str = "") -> dict[str, Any]:
    return {
        "id": "REQ-TMP", "title": title[:80], "description": description, "type": "functional",
        "priority": priority, "status": "confirmed", "source_section": source_section,
        "source_quote": source_quote or "（源表，见 source_refs）", "threshold_table": threshold_table,
        "acceptance_criteria": acceptance or [], "dependencies": [], "parent": None, "children": [],
        "labels": labels or ["通信协议"], "notes": notes,
    }


def p1_requirements(model: dict[str, Any]) -> list[dict[str, Any]]:
    reqs = []
    for obj in model["objects"]:
        label = _DOMAIN_LABEL.get(str(obj.get("domain") or ""), "通信协议")
        attrs = obj["attributes"]
        tt = None
        if attrs:
            tt = {
                "description": f"{obj['object']} 属性访问表",
                "columns": ["#", "属性", "类型", "RC", "PC", "SC", "LC", "默认值"],
                "rows": [[a["index"], a["name"], a["type"],
                          a["access"].get("RC", a["access_raw"]), a["access"].get("PC", ""),
                          a["access"].get("SC", ""), a["access"].get("LC", ""), a["default"]]
                         for a in attrs],
            }
        reqs.append(_req(
            title=f"{obj['object']} (OBIS {obj['obis']} / CL {obj['class_id']})",
            description=(f"计量软件 SHALL 实现 COSEM 对象 {obj['object']}（OBIS {obj['obis']}，接口类 "
                         f"{obj['class_id']}），其属性的数据类型与各关联(RC/PC/SC/LC)访问权限按属性表实现。"),
            source_quote=f"COSEM object {obj['object']} / CL {obj['class_id']} / OBIS {obj['obis']} shall be defined by the profile.",
            labels=[label],
            priority="P1",  # 对象模型统一 P1；P0 留给安全基础设施(P2 套件/关联/策略)
            source_section=" / ".join(str(p) for p in (obj.get("section_path") or [])) or str(obj.get("domain") or ""),
            threshold_table=tt,
            acceptance=[f"读取 {obj['object']} 的 logical_name 返回 OBIS {obj['obis']}",
                        "各属性的访问权限与数据类型符合属性表"],
            notes=f"对象模型由确定性装配(P1)，OBIS/CL/访问位来自源表、未经 LLM。",
        ))
    return reqs


def p1_class_template_requirements(model: dict[str, Any]) -> list[dict[str, Any]]:
    """把 P1 的孤立属性（父类未在对象实例表出现，多为 COSEM 类级属性模板如 Register/Profile Generic）
    按父类归并成「类级属性模板」需求，属性进 threshold_table —— 回收这部分有价值的类定义。"""
    from collections import defaultdict

    by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for attr in model.get("orphan_attributes", []):
        by_parent[str(attr.get("parent") or "（未命名类）")].append(attr)

    reqs = []
    for parent, attrs in sorted(by_parent.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        tt = {
            "description": f"{parent} 类级属性模板",
            "columns": ["#", "属性", "类型", "RC", "PC", "SC", "LC", "默认值"],
            "rows": [[a["index"], a["name"], a["type"],
                      a["access"].get("RC", a["access_raw"]), a["access"].get("PC", ""),
                      a["access"].get("SC", ""), a["access"].get("LC", ""), a["default"]]
                     for a in attrs],
        }
        reqs.append(_req(
            title=f"COSEM 类级属性模板：{parent}",
            description=(f"计量软件 SHALL 为 COSEM 接口类 {parent} 的实例实现下表定义的属性"
                         f"（数据类型与各关联 RC/PC/SC/LC 访问权限）。"),
            source_quote=f"Class {parent} attribute definitions (per-class template).",
            labels=["通信协议"], priority="P1", threshold_table=tt,
            notes=f"类级属性定义({len(attrs)} 条)，父类未在对象实例表出现；确定性装配，未经 LLM。",
        ))
    return reqs


def _pivot_table(pivot: dict[str, Any], description: str) -> dict | None:
    if not pivot["clients"]:
        return None
    return {
        "description": description,
        "columns": ["客户端", *pivot["columns"]],
        "rows": [[client, *[pivot["matrix"][client].get(col, "") for col in pivot["columns"]]]
                 for client in pivot["clients"]],
    }


def p2_requirements(model: dict[str, Any]) -> list[dict[str, Any]]:
    reqs = []
    assoc = _pivot_table(model["association_security"], "关联安全矩阵（客户端 × 服务端逻辑设备 → 安全级别）")
    if assoc:
        reqs.append(_req(title="关联安全矩阵", labels=["安全"], priority="P0",
                         description="计量软件 SHALL 对各客户端应用进程按下表要求的安全级别（HLS/LLS）建立关联。",
                         source_quote="关联安全矩阵（见源表 association_security_matrix）", threshold_table=assoc))
    cap = _pivot_table(model["capability"], "能力矩阵（客户端 × xDLMS 服务）")
    if cap:
        reqs.append(_req(title="客户端能力矩阵", labels=["通信协议"],
                         description="计量软件 SHALL 为各客户端应用进程支持下表标记的 xDLMS 服务，未标记的服务应拒绝。",
                         source_quote="能力矩阵（见源表 capability_matrix）", threshold_table=cap))
    if model["security_suites"]:
        reqs.append(_req(title="安全套件定义", labels=["安全"], priority="P0",
                         description="计量软件 SHALL 支持下表定义的安全套件及其密码学原语。",
                         source_quote="；".join(f"Suite {s['id']}={s['name']}" for s in model["security_suites"]),
                         threshold_table={
                             "description": "安全套件",
                             "columns": ["ID", "名称", "认证加密", "数字签名", "密钥协商", "Hash", "传输密钥", "压缩"],
                             "rows": [[s["id"], s["name"], s["authenticated_encryption"], s["digital_signature"],
                                       s["key_agreement"], s["hash"], s["transport_key"], s["compression"]]
                                      for s in model["security_suites"]],
                         }))
    if model["security_policy_states"]:
        reqs.append(_req(title="安全策略状态", labels=["安全"],
                         description="计量软件 SHALL 按下表定义安全策略状态的语义。",
                         source_quote="安全策略状态枚举（见源表）",
                         threshold_table={"description": "安全策略状态", "columns": ["状态", "安全策略"],
                                          "rows": [[p["state"], p["policy"]] for p in model["security_policy_states"]]}))
    if model["security_policy_bits"]:
        reqs.append(_req(title="安全策略位", labels=["安全"],
                         description="计量软件 SHALL 按下表定义安全策略位的含义。",
                         source_quote="安全策略位枚举（见源表）",
                         threshold_table={"description": "安全策略位", "columns": ["位", "含义"],
                                          "rows": [[p["bit"], p["meaning"]] for p in model["security_policy_bits"]]}))
    return reqs


def assemble(out_dir: Path, reviews_path: Path | None, *, source: str, extracted_at: str) -> tuple[dict, dict]:
    out_dir = out_dir.expanduser().resolve()
    p1 = build_object_model(out_dir)
    p2 = build_access_security(out_dir)
    p3 = build_behavior_spec(out_dir, reviews_path)
    p1_obj_reqs = p1_requirements(p1)
    p1_cls_reqs = p1_class_template_requirements(p1)
    p2_reqs = p2_requirements(p2)
    p3_reqs = rs.build_requirements_doc(p3, source=source, extracted_at=extracted_at)["requirements"]
    doc = rs.make_doc(p1_obj_reqs + p1_cls_reqs + p2_reqs + p3_reqs, source=source, extracted_at=extracted_at)
    breakdown = {"p1_object_requirements": len(p1_obj_reqs),
                 "p1_class_template_requirements": len(p1_cls_reqs),
                 "p2_matrix_requirements": len(p2_reqs),
                 "p3_behavior_requirements": len(p3_reqs), "total": len(doc["requirements"])}
    return doc, breakdown


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble the full DLMS/COSEM implementation spec (company schema).")
    parser.add_argument("--out", type=Path, required=True, help="Atomizer output directory")
    parser.add_argument("--reviews", type=Path, default=None, help="Behaviour LLM reviews jsonl")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = args.out.expanduser().resolve()
    doc, breakdown = assemble(args.out, args.reviews, source=out_dir.name,
                              extracted_at=datetime.datetime.now().isoformat(timespec="seconds"))
    target = out_dir / "dlms_cosem_spec_requirements.json"
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out_dir), "written": [target.name], "breakdown": breakdown,
                      "validation_result": doc["analysis"]["validation_result"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
