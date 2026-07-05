"""回归语料指标评估器（确定性零 LLM）——把"质量在变好"从感觉变成数字。

对一个抽取输出目录（ai_requirements.jsonl + ai_extract_quality.json + blocks.jsonl）计算
质量指标：碎片率、重复对、噪声条数、漏值标记、覆盖率等。用途：

- 回归防倒退：每次动 prompt/切分，全语料重跑后逐指标对比，修复变永久棘轮
- 架构 A/B 裁判：整章阅读 vs 条款窗口等大改由指标裁决，不靠肉眼
- 进度显影：逐版本曲线让"补丁"读成"质量爬升"

语料文档本身（客户 blocks.jsonl）不进仓——本工具只算指标。
用法：python -m corpus_eval --out <dir> [--label v10-clause] [--json <路径>]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from ai_extract import _is_reference_stub, _is_toc_line
from io_utils import read_jsonl


def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def evaluate(out_dir: Path) -> dict[str, Any]:
    out_dir = Path(out_dir).expanduser().resolve()
    reqs = read_jsonl(out_dir / "ai_requirements.jsonl")
    quality: dict[str, Any] = {}
    qp = out_dir / "ai_extract_quality.json"
    if qp.exists():
        try:
            quality = json.loads(qp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            quality = {}

    total = len(reqs)
    self_check = sum(1 for r in reqs if r.get("self_check_added"))

    # 重复对：引句互为包含（≥20 字）——自检拆碎/同源重复的直接量化（真实案例 4.14 的 #1/#2）
    quotes = [(_norm(r.get("source_quote")), i) for i, r in enumerate(reqs)]
    quotes = [(q, i) for q, i in quotes if len(q) >= 20]
    dup_pairs = 0
    for a in range(len(quotes)):
        for b in range(a + 1, len(quotes)):
            qa, qb = quotes[a][0], quotes[b][0]
            if qa in qb or qb in qa:
                dup_pairs += 1

    # 噪声：目录点线/引用桩当成需求（test7 教训）
    toc_noise = sum(1 for r in reqs if _is_toc_line(str(r.get("source_quote") or "")))
    ref_noise = sum(1 for r in reqs if _is_reference_stub(r))

    # 漏值/可疑度（漏值=数值清单没带进交付物的确定性信号）
    left_behind = sum(1 for r in reqs
                      if "原文数值未带全" in (r.get("suspicion_reasons") or []))
    vague_acceptance = sum(1 for r in reqs
                           if "验收不可测" in (r.get("suspicion_reasons") or []))
    suspicious = sum(1 for r in reqs if r.get("suspicion_reasons"))

    with_subs = sum(1 for r in reqs if r.get("sub_items"))
    with_thresholds = sum(1 for r in reqs if r.get("threshold_table"))

    return {
        "out_dir": str(out_dir),
        "requirements": total,
        "self_check_added": self_check,
        "self_check_ratio": round(self_check / total, 3) if total else 0.0,
        "duplicate_quote_pairs": dup_pairs,
        "toc_noise": toc_noise,
        "reference_noise": ref_noise,
        "values_left_behind": left_behind,
        "vague_acceptance": vague_acceptance,
        "suspicious": suspicious,
        "with_sub_items": with_subs,
        "with_threshold_table": with_thresholds,
        "sections": quality.get("sections"),
        "failed_sections": quality.get("failed_sections"),
        "coverage_pct": quality.get("coverage_pct"),
    }


METRIC_ORDER = [
    ("requirements", "需求条数"),
    ("sections", "抽取单元"),
    ("failed_sections", "失败单元"),
    ("coverage_pct", "覆盖率%"),
    ("self_check_added", "自检补充"),
    ("self_check_ratio", "自检占比"),
    ("duplicate_quote_pairs", "重复对(引句互含)"),
    ("toc_noise", "目录噪声"),
    ("reference_noise", "引用桩噪声"),
    ("values_left_behind", "漏值标记"),
    ("vague_acceptance", "验收不可测"),
    ("suspicious", "可疑标记总数"),
    ("with_sub_items", "带子项"),
    ("with_threshold_table", "带参数表"),
]


def render_comparison(results: dict[str, dict[str, Any]]) -> str:
    """多份评估结果并排成 Markdown 表（A/B、版本对比通用）。"""
    labels = list(results)
    lines = ["| 指标 | " + " | ".join(labels) + " |",
             "|---|" + "---|" * len(labels)]
    for key, name in METRIC_ORDER:
        row = [str(results[lb].get(key, "-")) for lb in labels]
        lines.append(f"| {name} | " + " | ".join(row) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate extraction quality metrics for an output dir.")
    parser.add_argument("--out", type=Path, required=True, action="append",
                        help="输出目录（可多次给出做对比）")
    parser.add_argument("--label", action="append", default=None)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    labels = args.label or []
    results: dict[str, dict[str, Any]] = {}
    for i, out in enumerate(args.out):
        label = labels[i] if i < len(labels) else Path(out).name
        results[label] = evaluate(out)
    if args.json:
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    print(render_comparison(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
