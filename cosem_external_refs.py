"""P4：外部规范交叉引用索引（确定性扫描，零 LLM，零文档外知识）。

ABNT profile 的行为/协议层（GET/SET 语义、HLS 握手、加密、错误码）多为"按 IEC 62056-x-x
第 X 节"的交叉引用，原子里没有实际内容。本模块不派生这些内容（避免幻觉），而是把文档里所有
指向外部规范的引用点识别出来，产出一份"实现本 profile 还需查阅哪些外部规范"的索引交给研发。

防幻觉原则：只用文档自身文字——引用编号靠正则、规范标题取自文档 Normative References 节原文。
不从模型自身知识编造"每个 part 覆盖什么"。仅 Green/Blue Book 俗称作可选附注，且明确标注为公开常识。

materiality：
- normative —— 被真·需求（atomic_requirements）或正文/表格引用，研发实现必查
- listed_only —— 只出现在 Normative References / Bibliography 引用目录里

用法：python -m cosem_external_refs --out <atomizer 输出目录>
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from cosem_object_model import build_source_index, read_jsonl

# 标准机构前缀 + 编号（IEC 62056-5-3 / IEC 61334-4-32 / ISO/IEC 8802-2 / ABNT NBR 14522 / ITU-T ...）
SPEC_RE = re.compile(
    r"(ISO/IEC|IEC|ISO|ABNT\s+NBR|ITU-T|EN)\s*([0-9]{3,5}(?:-[0-9]+)*)",
    flags=re.IGNORECASE,
)
REFERENCE_LIST_SECTIONS = ("normative references", "bibliography")
SNIPPET_MAX = 200

# 仅放教科书级、无争议的 DLMS UA 俗称对应；缺失即不附注（宁缺毋滥）。明确标注为文档外公开常识。
DLMS_UA_ALIASES = {
    "IEC 62056-6-1": "DLMS UA Blue Book（OBIS 标识系统）",
    "IEC 62056-6-2": "DLMS UA Blue Book（COSEM 接口类）",
    "IEC 62056-5-3": "DLMS UA Green Book（COSEM 应用层 / APDU·服务）",
}


def normalize_spec_id(prefix: str, number: str) -> str:
    prefix_norm = re.sub(r"\s+", " ", prefix).strip().upper()
    return f"{prefix_norm} {number}"


def find_spec_ids(text: str) -> list[str]:
    seen: list[str] = []
    for match in SPEC_RE.finditer(text or ""):
        spec_id = normalize_spec_id(match.group(1), match.group(2))
        if spec_id not in seen:
            seen.append(spec_id)
    return seen


def spec_base(spec_id: str) -> str:
    """机构前缀 + 首个数字段（去掉 part/年份后缀），用于自引用归并。

    'ABNT NBR 16968' / 'ABNT NBR 16968-2022' → 'ABNT NBR 16968'；'IEC 62056-5-3' → 'IEC 62056'。
    """
    tokens = spec_id.split()
    if not tokens:
        return spec_id
    prefix, number = " ".join(tokens[:-1]), tokens[-1]
    return f"{prefix} {number.split('-')[0]}".strip()


def document_self_bases(out_dir: Path) -> set[str]:
    """从 manifest 的源文件名取文档自身标准号基（自引用，不算"需另查的外部规范"）。"""
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.exists():
        return set()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    return {spec_base(spec_id) for spec_id in find_spec_ids(str(manifest.get("input") or ""))}


def is_reference_list_section(section_path: Any) -> bool:
    joined = " / ".join(str(p) for p in (section_path or [])).lower()
    return any(marker in joined for marker in REFERENCE_LIST_SECTIONS)


def snippet(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= SNIPPET_MAX else text[: SNIPPET_MAX - 1].rstrip() + "…"


def build_external_refs(out_dir: Path) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    blocks = read_jsonl(out_dir / "blocks.jsonl")
    requirements = read_jsonl(out_dir / "atomic_requirements.jsonl")
    table_items = read_jsonl(out_dir / "table_items.jsonl")

    # 1) 从 Normative References / Bibliography 节取权威标题（文档原文）
    titles: dict[str, str] = {}
    for block in blocks:
        if not is_reference_list_section(block.get("section_path")):
            continue
        text = re.sub(r"\s+", " ", str(block.get("text") or "")).strip()
        for spec_id in find_spec_ids(text):
            # 标题行通常以 spec_id 开头：用整行原文作标题（去掉开头编号本身的重复无碍）
            if spec_id not in titles and text[: len(spec_id) + 2].upper().startswith(spec_id.split()[0]):
                titles[spec_id] = text

    # 2) 聚合引用站点
    refs: dict[str, dict[str, Any]] = {}

    def ensure(spec_id: str) -> dict[str, Any]:
        return refs.setdefault(spec_id, {
            "spec_id": spec_id,
            "title": titles.get(spec_id, ""),
            "citations": [],
            "cited_by_requirements": 0,
            "body_citations": 0,
            "listed_in_references": False,
        })

    def add_site(spec_id: str, *, kind: str, ref_id: str, section_path: Any, text: str, in_list: bool, is_requirement: bool) -> None:
        entry = ensure(spec_id)
        entry["citations"].append({
            "kind": kind,
            "id": ref_id,
            "section_path": list(section_path or []),
            "snippet": snippet(text),
            "in_reference_list": in_list,
        })
        if in_list:
            entry["listed_in_references"] = True
        elif is_requirement:
            entry["cited_by_requirements"] += 1
        else:
            entry["body_citations"] += 1

    for block in blocks:
        text = str(block.get("text") or "")
        in_list = is_reference_list_section(block.get("section_path"))
        for spec_id in find_spec_ids(text):
            add_site(spec_id, kind="block", ref_id=str(block.get("block_id") or ""),
                     section_path=block.get("section_path"), text=text, in_list=in_list, is_requirement=False)

    for row in requirements:
        text = str(row.get("requirement") or "")
        in_list = is_reference_list_section(row.get("section_path"))
        for spec_id in find_spec_ids(text):
            add_site(spec_id, kind="requirement", ref_id=str(row.get("stable_req_id") or row.get("req_id") or ""),
                     section_path=row.get("section_path"), text=text, in_list=in_list, is_requirement=True)

    for item in table_items:
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        text = " | ".join(str(v) for v in fields.values())
        in_list = is_reference_list_section(item.get("section_path"))
        for spec_id in find_spec_ids(text):
            add_site(spec_id, kind="table_row", ref_id=str(item.get("item_id") or ""),
                     section_path=item.get("section_path"), text=text, in_list=in_list, is_requirement=False)

    # 3) 排除文档自身标准号（自引用，非"需另查的外部规范"）
    self_bases = document_self_bases(out_dir)
    excluded_self: list[str] = []

    # 4) materiality + 俗称附注 + 排序
    references: list[dict[str, Any]] = []
    for entry in refs.values():
        if spec_base(entry["spec_id"]) in self_bases:
            excluded_self.append(entry["spec_id"])
            continue
        material = entry["cited_by_requirements"] > 0 or entry["body_citations"] > 0
        entry["materiality"] = "normative" if material else "listed_only"
        alias = DLMS_UA_ALIASES.get(entry["spec_id"])
        if alias:
            entry["dlms_ua_note"] = f"{alias}（公开常识，非本文档内容）"
        references.append(entry)

    references.sort(key=lambda e: (e["materiality"] != "normative", -len(e["citations"]), e["spec_id"]))

    normative = sum(1 for e in references if e["materiality"] == "normative")
    return {
        "references": references,
        "excluded_self_references": sorted(excluded_self),
        "counts": {
            "specs": len(references),
            "normative": normative,
            "listed_only": len(references) - normative,
            "total_citations": sum(len(e["citations"]) for e in references),
            "excluded_self_references": len(excluded_self),
        },
    }


# --- 渲染 -----------------------------------------------------------------------

def write_external_refs(out_dir: Path, model: dict[str, Any]) -> list[str]:
    out_dir = out_dir.expanduser().resolve()
    written: list[str] = []
    (out_dir / "cosem_external_refs.json").write_text(
        json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    written.append("cosem_external_refs.json")
    (out_dir / "cosem_external_refs.md").write_text(render_markdown(model), encoding="utf-8")
    written.append("cosem_external_refs.md")
    return written


def render_markdown(model: dict[str, Any]) -> str:
    counts = model["counts"]
    lines = [
        "# 外部规范交叉引用索引",
        "",
        "> 确定性扫描文档对外部标准的引用（IEC/ISO/ABNT 等），供研发查阅。零派生、零文档外知识。",
        "> **normative** = 被需求/正文引用，实现必查；**listed_only** = 仅出现在引用目录。",
        "",
        f"- 外部规范数：**{counts['specs']}**（必查 {counts['normative']} / 仅列目录 {counts['listed_only']}）",
        f"- 引用站点总数：{counts['total_citations']}",
        "",
        "## 实现必查（normative）",
        "",
    ]
    normative = [e for e in model["references"] if e["materiality"] == "normative"]
    listed = [e for e in model["references"] if e["materiality"] != "normative"]

    if not normative:
        lines.append("_（无）_")
        lines.append("")
    for entry in normative:
        lines.extend(_render_entry(entry))

    if listed:
        lines.append("## 仅出现在引用目录（listed_only）")
        lines.append("")
        for entry in listed:
            title = entry["title"] or "（文档未给标题）"
            lines.append(f"- `{entry['spec_id']}` — {title}")
        lines.append("")
    return "\n".join(lines)


def _render_entry(entry: dict[str, Any]) -> list[str]:
    title = entry["title"] or "（文档未给标题）"
    lines = [f"### {entry['spec_id']}", "", f"- 标题（文档原文）：{title}"]
    if entry.get("dlms_ua_note"):
        lines.append(f"- 俗称：{entry['dlms_ua_note']}")
    lines.append(f"- 被需求引用：{entry['cited_by_requirements']}　正文引用：{entry['body_citations']}")
    lines.append("- 引用位置：")
    for cite in entry["citations"][:10]:
        sp = " / ".join(cite["section_path"]) or "—"
        lines.append(f"  - [{cite['kind']} {cite['id']}] 〔{sp}〕 {cite['snippet']}")
    if len(entry["citations"]) > 10:
        lines.append(f"  - …另有 {len(entry['citations']) - 10} 处")
    lines.append("")
    return lines


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Index external-spec cross-references (IEC/ISO/ABNT) from atomizer output.")
    parser.add_argument("--out", type=Path, required=True, help="Atomizer output directory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model = build_external_refs(args.out)
    written = write_external_refs(args.out, model)
    print(json.dumps({"out": str(args.out.expanduser().resolve()), "written": written, "counts": model["counts"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
