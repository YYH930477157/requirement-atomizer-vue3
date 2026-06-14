"""P2：COSEM 访问 / 安全矩阵生成器（装配优先，纯确定性 pivot，零 LLM）。

把关联/安全类原子装配成实现规格的「谁能做什么、用什么安全」一章：
- association_security_matrix → 关联安全矩阵（客户端 × 服务端逻辑设备 → 安全级别）
- capability_matrix          → 能力矩阵（客户端 × xDLMS 服务 → 支持）
- security_suite_definition  → 安全套件表（套件 × 密码原语）
- security_policy_state/_bit  → 安全策略枚举
- access_control             → 客户端 / 关联参考（正文）

复用 P1（cosem_object_model）的 join 助手；矩阵按源表列动态 pivot，可逐字段溯源。
用法：python -m cosem_access_security --out <atomizer 输出目录>
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from cosem_object_model import (
    build_source_index,
    read_jsonl,
    review_status_by_id,
    source_fields,
    status_of,
)
from text_normalize import normalize_numeric


IDENTITY_KEY = "Customer application process"


def _clean(value: object) -> str:
    return str(value or "").strip()


def _clean_col(key: str, strip_prefixes: tuple[str, ...]) -> str:
    label = key
    for prefix in strip_prefixes:
        if label.startswith(prefix):
            label = label[len(prefix):]
            break
    return label.strip().strip('"').strip()


def _fields_with_key(row: dict[str, Any], index: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
    """取该原子第一个 fields 里**含指定列**的源表行——保证拿到的是矩阵表本身，
    而非串入的属性表（避免列污染）。"""
    for ref in row.get("source_refs", []) or []:
        item = index.get(str(ref))
        if item and isinstance(item.get("fields"), dict) and key in item["fields"]:
            return item["fields"]
    return {}


def pivot_matrix(
    requirements: list[dict[str, Any]],
    index: dict[str, dict[str, Any]],
    requirement_type: str,
    strip_prefixes: tuple[str, ...],
) -> dict[str, Any]:
    """按 IDENTITY_KEY 作行、其余字段作列，pivot 出 客户端×列 矩阵。"""
    clients: list[str] = []
    columns: list[str] = []
    seen_cols: set[str] = set()
    matrix: dict[str, dict[str, str]] = {}
    for row in requirements:
        if row.get("requirement_type") != requirement_type:
            continue
        fields = _fields_with_key(row, index, IDENTITY_KEY)
        if not fields:
            continue
        client = _clean(fields.get(IDENTITY_KEY))
        if not client:
            continue
        if client not in matrix:
            matrix[client] = {}
            clients.append(client)
        for key, value in fields.items():
            if key == IDENTITY_KEY:
                continue
            label = _clean_col(key, strip_prefixes)
            if not label:
                continue
            if label not in seen_cols:
                seen_cols.add(label)
                columns.append(label)
            matrix[client][label] = _clean(value)
    return {"clients": clients, "columns": columns, "matrix": matrix}


def build_access_security(out_dir: Path) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    requirements = read_jsonl(out_dir / "atomic_requirements.jsonl")
    index = build_source_index(read_jsonl(out_dir / "table_items.jsonl"))
    status_by_id = review_status_by_id(read_jsonl(out_dir / "review_states.jsonl"))

    association_security = pivot_matrix(
        requirements, index, "association_security_matrix",
        ("Server application process / ", "Server application process /"),
    )
    capability = pivot_matrix(
        requirements, index, "capability_matrix",
        ("xDLMS Service / ", "xDLMS Service /"),
    )

    suites: list[dict[str, Any]] = []
    for row in requirements:
        if row.get("requirement_type") != "security_suite_definition":
            continue
        f = source_fields(row, index)
        suites.append({
            "id": normalize_numeric(f.get("ID")),
            "name": _clean(f.get("Name") or row.get("object")),
            "authenticated_encryption": _clean(f.get("Authenticated encryption")),
            "digital_signature": _clean(f.get("Digital signature")),
            "key_agreement": _clean(f.get("Key Agreement")),
            "hash": _clean(f.get('"Hash"') or f.get("Hash")),
            "transport_key": _clean(f.get("Transport key")),
            "compression": _clean(f.get("Compression")),
            "review_status": status_of(row, status_by_id),
        })

    policy_states = [
        {"state": normalize_numeric(f.get("State")), "policy": _clean(f.get("Security policy"))}
        for row in requirements if row.get("requirement_type") == "security_policy_state"
        for f in [source_fields(row, index)]
    ]
    policy_bits = [
        {"bit": normalize_numeric(f.get("bit")), "meaning": _clean(f.get("Security Policy - Security States"))}
        for row in requirements if row.get("requirement_type") == "security_policy_bit"
        for f in [source_fields(row, index)]
    ]
    clients = [
        {"client": _clean(row.get("object")), "text": _clean(row.get("requirement")),
         "review_status": status_of(row, status_by_id)}
        for row in requirements if row.get("requirement_type") == "access_control"
    ]

    return {
        "association_security": association_security,
        "capability": capability,
        "security_suites": suites,
        "security_policy_states": policy_states,
        "security_policy_bits": policy_bits,
        "clients": clients,
        "counts": {
            "association_clients": len(association_security["clients"]),
            "capability_clients": len(capability["clients"]),
            "security_suites": len(suites),
            "security_policy_states": len(policy_states),
            "security_policy_bits": len(policy_bits),
            "access_control_clients": len(clients),
        },
    }


# --- 渲染 -----------------------------------------------------------------------

def _matrix_md(title: str, pivot: dict[str, Any], *, check: bool) -> list[str]:
    if not pivot["clients"]:
        return []
    lines = [f"## {title}", ""]
    header = "| 客户端 | " + " | ".join(pivot["columns"]) + " |"
    sep = "|---|" + "|".join("---" for _ in pivot["columns"]) + "|"
    lines.append(header)
    lines.append(sep)
    for client in pivot["clients"]:
        cells = []
        for col in pivot["columns"]:
            value = pivot["matrix"][client].get(col, "")
            if check:
                value = "✓" if value.upper() == "X" else ""
            cells.append(value)
        lines.append(f"| {client} | " + " | ".join(cells) + " |")
    lines.append("")
    return lines


def render_markdown(model: dict[str, Any]) -> str:
    counts = model["counts"]
    lines = [
        "# COSEM 访问与安全规格",
        "",
        "> 由原子需求确定性装配（关联/能力/安全套件/策略），可逐字段溯源。",
        "",
        f"- 关联安全：{counts['association_clients']} 个客户端　能力矩阵：{counts['capability_clients']} 个客户端",
        f"- 安全套件：{counts['security_suites']}　策略状态：{counts['security_policy_states']}　策略位：{counts['security_policy_bits']}",
        "",
    ]
    lines += _matrix_md("关联安全矩阵（客户端 × 服务端逻辑设备 → 安全级别）", model["association_security"], check=False)
    lines += _matrix_md("能力矩阵（客户端 × xDLMS 服务）", model["capability"], check=True)

    if model["security_suites"]:
        lines += ["## 安全套件", "",
                  "| ID | 名称 | 认证加密 | 数字签名 | 密钥协商 | Hash | 传输密钥 | 压缩 |",
                  "|----|------|----------|----------|----------|------|----------|------|"]
        for s in model["security_suites"]:
            lines.append(f"| {s['id']} | {s['name']} | {s['authenticated_encryption']} | "
                         f"{s['digital_signature']} | {s['key_agreement']} | {s['hash']} | "
                         f"{s['transport_key']} | {s['compression']} |")
        lines.append("")

    if model["security_policy_states"]:
        lines += ["## 安全策略状态", "", "| 状态 | 安全策略 |", "|------|----------|"]
        for p in model["security_policy_states"]:
            lines.append(f"| {p['state']} | {p['policy']} |")
        lines.append("")

    if model["security_policy_bits"]:
        lines += ["## 安全策略位", "", "| 位 | 含义 |", "|----|------|"]
        for p in model["security_policy_bits"]:
            lines.append(f"| {p['bit']} | {p['meaning']} |")
        lines.append("")

    if model["clients"]:
        lines += ["## 客户端 / 关联定义（参考）", ""]
        for c in model["clients"]:
            text = re.sub(r"\s+", " ", c["text"]).strip()
            lines.append(f"- **{c['client']}** — {text}")
        lines.append("")

    return "\n".join(lines)


def write_access_security(out_dir: Path, model: dict[str, Any]) -> list[str]:
    out_dir = out_dir.expanduser().resolve()
    (out_dir / "cosem_access_security.json").write_text(
        json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "cosem_access_security.md").write_text(render_markdown(model), encoding="utf-8")
    return ["cosem_access_security.json", "cosem_access_security.md"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble a COSEM access & security spec from atomizer output.")
    parser.add_argument("--out", type=Path, required=True, help="Atomizer output directory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model = build_access_security(args.out)
    written = write_access_security(args.out, model)
    print(json.dumps({"out": str(args.out.expanduser().resolve()), "written": written, "counts": model["counts"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
