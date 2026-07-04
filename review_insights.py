"""专家裁决学习回路（确定性、零 LLM）：从 override 模式里提炼规则改进建议。

专家在批注视图的每次改判（module_override / ownership_override / rejected）都是免费的
规则改进信号：反复把"通信协议"改成"事件记录"说明 map_labels 的关键词该挪窝；反复把规则判
software 的某类对象改判 hardware 说明 classify_ownership 缺一条规则。此前这些信号只写进
ai_review_states.jsonl 就睡着了——本模块把它们汇总成可审阅的复盘报告 + 建议（人审后采纳，
不自动改规则）。

用法：python -m review_insights --out <atomizer 输出目录>
产物：review_insights.json + review_insights.md（写进 out 目录）。
挂载：rebuild_merged_spec 每次裁决回流后自动刷新（失败不阻断交付物）。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from ai_review_actions import read_ai_review_states, source_ai_requirement_id
from io_utils import read_jsonl

SCHEMA_VERSION = "review-insights/v1"
SUGGESTION_THRESHOLD = 3  # 同一改判模式出现 ≥N 次才升级为建议（少于此视作个案）
INSIGHTS_JSON = "review_insights.json"
INSIGHTS_MD = "review_insights.md"


def build_insights(out_dir: Path) -> dict[str, Any]:
    out_dir = Path(out_dir).expanduser().resolve()
    requirements = read_jsonl(out_dir / "ai_requirements.jsonl")
    states = read_ai_review_states(out_dir)
    by_id = {source_ai_requirement_id(req): req for req in requirements}

    module_transitions: Counter[tuple[str, str]] = Counter()
    ownership_transitions: Counter[tuple[str, str]] = Counter()
    ownership_examples: dict[tuple[str, str], list[str]] = {}
    rejected_by_module: Counter[str] = Counter()
    decided = 0

    for rid, state in states.items():
        req = by_id.get(rid)
        if req is None:
            continue  # 裁决对应的需求已不在（重抽后 id 漂移等）——不计入
        decided += 1
        original_module = str(req.get("module") or (req.get("labels") or [""])[0] or "").strip()

        override = str(state.get("module_override") or "").strip()
        if override and original_module and override != original_module:
            module_transitions[(original_module, override)] += 1

        ownership_override = str(state.get("ownership_override") or "").strip()
        if ownership_override:
            rule_verdict = _rule_ownership(req)
            if rule_verdict and ownership_override != rule_verdict:
                key = (rule_verdict, ownership_override)
                ownership_transitions[key] += 1
                ownership_examples.setdefault(key, [])
                if len(ownership_examples[key]) < 3:
                    ownership_examples[key].append(str(req.get("title") or rid)[:60])

        if str(state.get("status") or "") == "rejected":
            rejected_by_module[original_module or "(未分模块)"] += 1

    suggestions = _build_suggestions(module_transitions, ownership_transitions, ownership_examples)
    return {
        "schema_version": SCHEMA_VERSION,
        "decided_states": decided,
        "module_transitions": _serialize(module_transitions),
        "ownership_transitions": _serialize(ownership_transitions),
        "rejected_by_module": dict(rejected_by_module.most_common()),
        "suggestions": suggestions,
    }


def _rule_ownership(req: dict[str, Any]) -> str:
    """规则初判（与 analyze/批注视图同一分类器）。分类器不可用时返回空——不猜。"""
    try:
        from requirements_analysis_rules import classify_ownership
        return str(classify_ownership(req).get("ownership") or "")
    except Exception:  # pragma: no cover - 分类器缺失/异常时跳过归属分析
        return ""


def _serialize(counter: Counter) -> list[dict[str, Any]]:
    return [{"from": k[0], "to": k[1], "count": n} for k, n in counter.most_common()]


def _build_suggestions(
    module_transitions: Counter,
    ownership_transitions: Counter,
    ownership_examples: dict[tuple[str, str], list[str]],
) -> list[str]:
    """确定性建议模板：只描述观察到的模式与该看的代码位置，不自动改规则（人审采纳）。"""
    suggestions: list[str] = []
    for (src, dst), n in module_transitions.most_common():
        if n < SUGGESTION_THRESHOLD:
            continue
        suggestions.append(
            f"模块「{src}」被专家改为「{dst}」共 {n} 次——考虑调整 requirement_schema.map_labels /"
            f" ai_extract.MODULE_VOCAB 提示词里两者的关键词边界。")
    for (rule, expert), n in ownership_transitions.most_common():
        if n < SUGGESTION_THRESHOLD:
            continue
        examples = "、".join(ownership_examples.get((rule, expert), []))
        suggestions.append(
            f"归属规则判「{rule}」、专家改判「{expert}」共 {n} 次（样例：{examples}）——"
            f"考虑在 requirements_analysis_rules.classify_ownership 增补对应规则。")
    return suggestions


def render_markdown(insights: dict[str, Any]) -> str:
    lines = ["# 专家裁决复盘（确定性统计，供规则改进参考）", ""]
    lines.append(f"- 有效裁决数：{insights['decided_states']}")
    lines.append("")
    if insights["suggestions"]:
        lines.append("## 建议（模式 ≥ %d 次，人审后采纳）" % SUGGESTION_THRESHOLD)
        for s in insights["suggestions"]:
            lines.append(f"- {s}")
        lines.append("")
    for title, key in (("模块改判", "module_transitions"), ("归属改判", "ownership_transitions")):
        rows = insights[key]
        if not rows:
            continue
        lines.append(f"## {title}")
        for row in rows:
            lines.append(f"- {row['from']} → {row['to']}：{row['count']} 次")
        lines.append("")
    if insights["rejected_by_module"]:
        lines.append("## 拒绝分布（按模块）")
        for module, n in insights["rejected_by_module"].items():
            lines.append(f"- {module}：{n} 次")
        lines.append("")
    if not insights["suggestions"] and insights["decided_states"] == 0:
        lines.append("（暂无裁决——专家在批注视图裁决后此报告自动累积。）")
        lines.append("")
    return "\n".join(lines)


def write_insights(out_dir: Path) -> dict[str, Any]:
    out_dir = Path(out_dir).expanduser().resolve()
    insights = build_insights(out_dir)
    (out_dir / INSIGHTS_JSON).write_text(
        json.dumps(insights, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / INSIGHTS_MD).write_text(render_markdown(insights), encoding="utf-8")
    return insights


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarise expert override patterns into rule-improvement hints.")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    insights = write_insights(args.out)
    print(json.dumps({"kind": "review_insights", "decided_states": insights["decided_states"],
                      "suggestions": len(insights["suggestions"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
