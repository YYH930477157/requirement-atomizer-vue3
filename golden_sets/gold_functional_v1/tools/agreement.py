"""gold_functional_v1 双专家标注一致率计算（WS0 D3 输入）。

参考实现落仓自 ``02-WS0一致率算法规格.md`` 第 5 节，核心算法字节级保持一致；本文件在其上
补齐 §1 协议合规预检、模块化函数导出（供 ``tests/test_gold_agreement.py`` 与
``tools/functional_truth_eval.py`` 复用匹配口径）与命令行入口。

口径要点（与规格一致，勿混淆）：

* **成条一致率**用 **Dice**（``2M/(|A|+|B|)``），不用 Jaccard——Jaccard 0.80 ≡ Dice 0.89，
  阈值不可互换。冻结硬条件 ≥0.80。
* **匹配规则**：甲条目 a 与乙条目 b 匹配 ⟺ section 相同 且 锚点坐标区间有交集（≥1 个共享
  坐标）。贪心二部匹配：按重叠坐标数从大到小配对，每条只参与一对。
* **冲突对豁免**：携带 ``conflict_with`` 的条目从双方文件剔除（"标记不消解"惯例——冲突条款
  成条与否本就不应一致，否则系统性压低一致率）。
* **字段取值一致率**仅对匹配对计算、登记入册不做门槛：objective 串相等；behaviors/
  preconditions/variants/exceptions 句集 Dice；data_constraints/related_dlms_objects 集合
  严格相等（保护字段不用 Dice——Dice 掩盖单值错误；转录是机械动作，不一致即有一方未逐字转录）。
  字段级一致率按字段分别报告，**不聚合**。

机械判定，禁止模糊匹配与 LLM 参与。
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any

# 与规格 §5 参考实现完全一致的字段分组。
LIST_FIELDS = ("behaviors", "preconditions", "variants", "exceptions")
EXACT_SET_FIELDS = ("data_constraints", "related_dlms_objects")
FREEZE_THRESHOLD = 0.80

# 让本模块可被 ``python -m`` / 直接导入 / 从仓库根导入三种方式使用。
_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def norm(s: str) -> str:
    """归一化：NFKC 全半角统一 + 折叠连续空白 + 去首尾空白 + 去句末标点。"""
    s = unicodedata.normalize("NFKC", str(s))
    return " ".join(s.split()).rstrip("。.;;,")


def anchors(e: dict) -> set:
    """条目的锚点坐标集合：{(section, coordinate)}。"""
    a = e.get("source_anchor") or {}
    return {(a.get("section"), c) for c in a.get("coordinates", [])}


def section_of(e: dict) -> Any:
    return (e.get("source_anchor") or {}).get("section")


def match(a_entries, b_entries):
    """贪心二部匹配：section 相同且锚点有交集的对，按重叠坐标数从大到小配对，每条只参与一对。

    与规格 §5 参考实现一致。返回 ``(i, j)`` 下标对列表。
    """
    cand = []
    for i, a in enumerate(a_entries):
        for j, b in enumerate(b_entries):
            ov = len(anchors(a) & anchors(b))
            sec = section_of(a)
            if ov and sec and sec == section_of(b):
                cand.append((-ov, i, j))
    used_a, used_b, pairs = set(), set(), []
    for _, i, j in sorted(cand):
        if i not in used_a and j not in used_b:
            used_a.add(i); used_b.add(j); pairs.append((i, j))
    return pairs


def dice(x: set, y: set) -> float:
    """句集 Dice：双方皆空=1（同义空）；一空一非空=0。"""
    if not x and not y:
        return 1.0
    return 2 * len(x & y) / (len(x) + len(y))


def field_scores(a: dict, b: dict) -> dict:
    """单匹配对的逐字段得分（objective/列表字段/严格相等字段）。"""
    out = {"objective": 1.0 if norm(a.get("objective", "")) == norm(b.get("objective", "")) else 0.0}
    for f in LIST_FIELDS:
        out[f] = dice({norm(s) for s in a.get(f, [])}, {norm(s) for s in b.get(f, [])})
    for f in EXACT_SET_FIELDS:
        out[f] = 1.0 if {norm(s) for s in a.get(f, [])} == {norm(s) for s in b.get(f, [])} else 0.0
    return out


def load_entries(path) -> list[dict]:
    """读 JSONL，跳过空行。"""
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def protocol_violations(entries: list[dict]) -> list[dict]:
    """§1 协议合规预检：违规条目不进统计、单独列清单退回。

    检查：必填字段（objective、source_anchor）缺失；source_anchor 缺 section 或 coordinates；
    conflict_with 引用的对方 entry_id 在本文件内不存在（无法互引）。列表字段非列表不在此处
    判（schema 已约束），但缺字段视为空列表（§1 允许空列表，禁止省略字段——schema required
    未把列表字段列为必填，故这里只校验必填锚点字段）。
    """
    ids = {str(e.get("entry_id") or "") for e in entries}
    violations: list[dict] = []
    for idx, e in enumerate(entries):
        reasons: list[str] = []
        if not str(e.get("objective") or "").strip():
            reasons.append("missing_objective")
        anchor = e.get("source_anchor") or {}
        if not isinstance(anchor, dict):
            reasons.append("missing_source_anchor")
        else:
            if not str(anchor.get("section") or "").strip():
                reasons.append("missing_anchor_section")
            coords = anchor.get("coordinates")
            if not isinstance(coords, list) or not coords:
                reasons.append("missing_anchor_coordinates")
        cw = e.get("source_anchor", {}).get("conflict_with") if isinstance(e.get("source_anchor"), dict) else None
        if cw and str(cw) not in ids:
            reasons.append("conflict_with_target_missing")
        if reasons:
            violations.append({
                "entry_id": str(e.get("entry_id") or f"#{idx}"),
                "reasons": reasons,
            })
    return violations


def compute(a_entries: list[dict], b_entries: list[dict]) -> dict:
    """核心计算：返回完整报告 dict（冻结口径 + 字段分报）。冲突对豁免在统计前剔除。

    与规格 §5 参考实现的报告字段完全一致，并增补 ``violations``/``exempted_*`` 审计计数。
    """
    violations_a = protocol_violations(a_entries)
    violations_b = protocol_violations(b_entries)
    bad_a = {v["entry_id"] for v in violations_a}
    bad_b = {v["entry_id"] for v in violations_b}

    def clean(rows, bad):
        return [e for e in rows
                if str(e.get("entry_id") or "") not in bad and not (e.get("source_anchor") or {}).get("conflict_with")]

    A = clean(a_entries, bad_a)
    B = clean(b_entries, bad_b)
    pairs = match(A, B)
    entry_dice = 2 * len(pairs) / (len(A) + len(B)) if (A or B) else 1.0
    fields: dict[str, list[float]] = {}
    for i, j in pairs:
        for k, v in field_scores(A[i], B[j]).items():
            fields.setdefault(k, []).append(v)
    report = {
        "entry_agreement_dice": round(entry_dice, 4),
        "freeze_threshold": FREEZE_THRESHOLD,
        "freeze_pass": entry_dice >= FREEZE_THRESHOLD,
        "counts": {
            "expert_a": len(A), "expert_b": len(B), "matched": len(pairs),
            "exempted_conflict_a": sum(1 for e in a_entries if (e.get("source_anchor") or {}).get("conflict_with")) - len(bad_a),
            "exempted_conflict_b": sum(1 for e in b_entries if (e.get("source_anchor") or {}).get("conflict_with")) - len(bad_b),
        },
        "field_agreement": {k: round(sum(v) / len(v), 4) for k, v in sorted(fields.items())},
        "violations": {"expert_a": violations_a, "expert_b": violations_b},
    }
    return report


def main(pa, pb, report_path="agreement_report.json") -> int:
    """命令行入口：``python agreement.py expert_a.jsonl expert_b.jsonl --report report.json``。"""
    A = load_entries(pa)
    B = load_entries(pb)
    report = compute(A, B)
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["freeze_pass"] else 2


def _cli() -> int:
    parser = argparse.ArgumentParser(
        prog="agreement.py",
        description="gold_functional_v1 双专家标注一致率（WS0 D3）。退出码 0=达标(≥0.80) / 2=未达标。",
    )
    parser.add_argument("expert_a", help="专家 A 标注 JSONL")
    parser.add_argument("expert_b", help="专家 B 标注 JSONL")
    parser.add_argument("--report", default="agreement_report.json", help="输出报告 JSON 路径")
    args = parser.parse_args()
    return main(args.expert_a, args.expert_b, args.report)


if __name__ == "__main__":
    sys.exit(_cli())
