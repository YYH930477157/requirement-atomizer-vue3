"""P3：COSEM 功能/行为规格装配器（LLM 派生 + 防幻觉护栏）。

把**行为类**原子（functional / communication / event / event_group_retention）与 LLM 审查产出
（revised_requirement / acceptance / decision / expert_questions）装配成实现规格的「功能/行为」章。

防幻觉护栏（铁律）：LLM 绝不产出/修改数字与编码。
- 装配时对 LLM 改写文本做 **code-drift 检测**：改写里出现的 OBIS/事件号/十六进制，若不在原始原子文本里 → 标 `number_drift` → 强制 `needs_expert`（打回专家队列）。
- 整数差异作为 `int_note` 软提示。
- 凡有 LLM 产出且 decision≠accept 或带 flag 的条目，一律进 expert_queue。

derivations 来源：默认读 out_dir/llm_review_results.jsonl（生产管线写在此）；开发期可用 --reviews 指向
我（Claude）在 session 内亲手产的参考派生（同 schema），充当 fixture / few-shot 种子。

用法：python -m cosem_behavior_spec --out <atomizer 输出目录> [--reviews <reviews.jsonl>]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from cosem_object_model import read_jsonl


BEHAVIORAL_TYPES = ("functional", "communication", "event_definition", "event_group_retention")

# 受保护编码：OBIS、事件号(G..-SG..-E..)、十六进制。这些只能来自确定性层/原文。
CODE_PATTERNS = (
    r"\d+-\d+:\d+(?:\.\d+)+",      # OBIS 形如 0-0:41.0.0.255（结尾停在数字，不吞句尾句号）
    r"G[\d,\s]*-?SG[\w]+-E[\w]+",  # 事件号 G1-SG10-E1
    r"0x[0-9A-Fa-f]+",            # 十六进制
)


def reviews_by_id(reviews: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for review in reviews:
        for key in ("stable_req_id", "requirement_id", "req_id", "task_id"):
            value = str(review.get(key) or "")
            if value:
                index.setdefault(value, review)
    return index


def extract_codes(text: str) -> set[str]:
    found: set[str] = set()
    for pattern in CODE_PATTERNS:
        found |= {m.group(0).strip() for m in re.finditer(pattern, str(text or ""))}
    return found


def extract_ints(text: str) -> set[str]:
    return set(re.findall(r"\d+", str(text or "")))


def derive_item(row: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    rid = next((str(row.get(k)) for k in ("stable_req_id", "req_id") if row.get(k)), "")
    original = str(row.get("requirement") or "")
    revised = str(review.get("revised_requirement") or "")
    derived = bool(review) and bool(revised) and revised.strip() != original.strip()

    flags: list[str] = []
    drift_codes: list[str] = []
    int_notes: list[str] = []
    if derived:
        drift_codes = sorted(extract_codes(revised) - extract_codes(original))
        int_notes = sorted(extract_ints(revised) - extract_ints(original))
        if drift_codes:
            flags.append("number_drift")
    if row.get("ambiguity"):
        flags.append("ambiguity")
    if review.get("expert_questions"):
        flags.append("expert_question")

    if not review:
        decision = "pending"
    else:
        decision = str(review.get("decision") or "accept")
    if drift_codes:                       # 护栏：编码漂移一律打回专家
        decision = "needs_expert"

    in_queue = (decision != "accept") or bool(flags)
    return {
        "stable_req_id": rid,
        "type": row.get("requirement_type"),
        "object": row.get("object"),
        "original": original,
        "behavior": revised if derived else original,
        "derived": derived,
        "acceptance": list(review.get("acceptance") or []),
        "verification_method": row.get("verification_method") or "",
        "decision": decision,
        "expert_questions": list(review.get("expert_questions") or []),
        "review_notes": list(review.get("review_notes") or []),
        "flags": flags,
        "drift_codes": drift_codes,
        "int_notes": int_notes,
        "confidence": row.get("confidence"),
        "source_refs": row.get("source_refs") or [],
        "in_expert_queue": in_queue,
    }


def build_behavior_spec(out_dir: Path, reviews_path: Path | None = None) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    requirements = read_jsonl(out_dir / "atomic_requirements.jsonl")
    rpath = Path(reviews_path).expanduser().resolve() if reviews_path else out_dir / "llm_review_results.jsonl"
    reviews = reviews_by_id(read_jsonl(rpath)) if rpath.exists() else {}

    items: list[dict[str, Any]] = []
    for row in requirements:
        if row.get("requirement_type") not in BEHAVIORAL_TYPES:
            continue
        rid = next((str(row.get(k)) for k in ("stable_req_id", "req_id") if row.get(k)), "")
        items.append(derive_item(row, reviews.get(rid, {})))

    derived = [i for i in items if i["derived"]]
    queue = [i for i in items if i["in_expert_queue"]]
    return {
        "items": items,
        "expert_queue": [i["stable_req_id"] for i in queue],
        "counts": {
            "behavioral_atoms": len(items),
            "llm_derived": len(derived),
            "pending_review": sum(1 for i in items if i["decision"] == "pending"),
            "number_drift": sum(1 for i in items if i["drift_codes"]),
            "expert_queue": len(queue),
        },
    }


# --- 渲染 -----------------------------------------------------------------------

def render_markdown(model: dict[str, Any]) -> str:
    c = model["counts"]
    lines = [
        "# COSEM 功能 / 行为规格",
        "",
        "> 行为类原子 + LLM 派生（改写为 SHALL + 验收点），数字/编码受确定性护栏保护。",
        "",
        f"- 行为原子：**{c['behavioral_atoms']}**　已派生：{c['llm_derived']}　待审：{c['pending_review']}",
        f"- 编码漂移拦截：{c['number_drift']}　专家队列：**{c['expert_queue']}**",
        "",
    ]
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in model["items"]:
        by_type[item["type"]].append(item)

    for rtype in sorted(by_type):
        lines.append(f"## {rtype}")
        lines.append("")
        for item in by_type[rtype]:
            badge = {
                "accept": "✅", "pending": "⏳", "needs_expert": "🧑‍⚖️",
            }.get(item["decision"], "✎")
            lines.append(f"### {badge} {item['object'] or item['stable_req_id']}  ·  `{item['decision']}`")
            if item["derived"]:
                lines.append(f"- **SHALL**：{item['behavior']}")
                lines.append(f"  - <sub>原文（机翻）：{item['original']}</sub>")
            else:
                lines.append(f"- **（待 LLM 审查）**原文：{item['behavior']}")
            for point in item["acceptance"]:
                lines.append(f"  - 验收：{point}")
            for question in item["expert_questions"]:
                lines.append(f"  - ❓专家：{question}")
            if item["drift_codes"]:
                lines.append(f"  - ⚠ **编码漂移（已拦截，打回专家）**：{', '.join(item['drift_codes'])}")
            if item["int_notes"]:
                lines.append(f"  - 数字提示：改写引入 {', '.join(item['int_notes'])}（核对来源）")
            meta = f"verify={item['verification_method']} · conf={item['confidence']} · src={'; '.join(str(r) for r in item['source_refs'])}"
            lines.append(f"  - <sub>{meta}</sub>")
            lines.append("")
    return "\n".join(lines)


def write_behavior_spec(out_dir: Path, model: dict[str, Any]) -> list[str]:
    out_dir = out_dir.expanduser().resolve()
    (out_dir / "cosem_behavior_spec.json").write_text(
        json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "cosem_behavior_spec.md").write_text(render_markdown(model), encoding="utf-8")
    return ["cosem_behavior_spec.json", "cosem_behavior_spec.md"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble a COSEM behaviour spec from behavioural atoms + LLM reviews.")
    parser.add_argument("--out", type=Path, required=True, help="Atomizer output directory")
    parser.add_argument("--reviews", type=Path, default=None,
                        help="LLM review results jsonl (default: out/llm_review_results.jsonl)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model = build_behavior_spec(args.out, args.reviews)
    written = write_behavior_spec(args.out, model)
    print(json.dumps({"out": str(args.out.expanduser().resolve()), "written": written, "counts": model["counts"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
