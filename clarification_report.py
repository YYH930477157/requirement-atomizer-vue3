"""澄清问题清单 + 就绪判定（确定性零 LLM）。

真实需求评审的标配产物是"问客户清单"——文档说要做 X 但没给限值、A 章与 B 章数值矛盾、
推导时不得不做的假设……这些疑问信号管线里全都有（open_questions / suspicion_reasons /
一致性报告 / assumptions / 富化降级），但散落各处没人汇总。本模块把它们聚合成一份
评审会直接可用的清单，并给出 READY / NEEDS WORK 就绪判定（吸收 BMAD 的
assumptions 契约 + FR 覆盖门模式，用代码实现它只用提示词说的事）。

分类沿用 hs-req 三分类 + 假设：模糊（说了但不可测/不逐字）、缺失（该有数值没给）、
矛盾（跨章数值发散/重复表述）、假设待确认（LLM 推导中记录的前提）。

用法：python -m clarification_report --out <atomizer 输出目录>
产物：clarification_questions.md / clarification_questions.xlsx / clarification_report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from io_utils import read_jsonl
from text_normalize import formula_safe

REPORT_JSON = "clarification_report.json"
REPORT_MD = "clarification_questions.md"
REPORT_XLSX = "clarification_questions.xlsx"
ANSWERS_FILE = "clarification_answers.jsonl"   # 评审会答复回灌（answer 列填写后 import 回来）

CAT_AMBIGUOUS = "模糊"
CAT_MISSING = "缺失"
CAT_CONFLICT = "矛盾"
CAT_ASSUMPTION = "假设待确认"

# 信号分级（真实教训：v10 数据上模型自报 303 条假设 + 277 条 open_questions，清单膨胀到
# 612 条评审会没法用）。硬信号=确定性机器检出（矛盾/漏值/验收不可测/引用不逐字）——必答；
# 软信号=模型自报（assumptions/open_questions）——价值在"可见"，留档备查不算就绪门。
TIER_HARD = "必答"
TIER_SOFT = "参考"
# 必答再分受众（真实产物观察：56 条必答被"引用非逐字"占领——它是审核员在批注视图核的
# **内部核对项**，不是评审会问客户的问题。分开后评审会拿到的是十几条纯客户问题）
AUDIENCE_CUSTOMER = "问客户"
AUDIENCE_INTERNAL = "内部核对"

# 就绪门默认阈值（NEEDS WORK 触发条件；试点后按真实分布调）
READY_MAX_QUESTIONS = 30
READY_MIN_COVERAGE = 60.0


def _entry(category: str, question: str, *, section: str = "", quote: str = "",
           source_id: str = "", signal: str = "", tier: str = TIER_HARD,
           audience: str = AUDIENCE_CUSTOMER) -> dict[str, Any]:
    return {"category": category, "question": question, "section": section,
            "quote": quote[:200], "source_id": source_id, "signal": signal, "tier": tier,
            "audience": audience}


def collect_questions(out_dir: Path) -> list[dict[str, Any]]:
    """聚合全链疑问信号（每个来源都可缺席——有什么聚什么，出处如实标注 signal）。"""
    entries: list[dict[str, Any]] = []

    # ① 抽取层 suspicion（ai_requirements.jsonl）
    reqs_path = out_dir / "ai_requirements.jsonl"
    reqs = read_jsonl(reqs_path) if reqs_path.exists() else []
    from ai_review_actions import source_ai_requirement_id
    for req in reqs:
        rid = source_ai_requirement_id(req)
        sec = str(req.get("source_section") or "")
        quote = str(req.get("source_quote") or "")
        title = str(req.get("title") or "")
        for reason in (req.get("suspicion_reasons") or []):
            if reason == "原文数值未带全":
                entries.append(_entry(
                    CAT_MISSING,
                    f"文档 §{sec}「{title}」附近的数值清单未完整进入需求，请逐项核对并确认参数",
                    section=sec, quote=quote, source_id=rid, signal="suspicion:漏值"))
            elif reason == "引用非逐字":
                entries.append(_entry(
                    CAT_AMBIGUOUS,
                    f"§{sec}「{title}」的引用与原文不逐字一致，请核对该需求是否忠实原文",
                    section=sec, quote=quote, source_id=rid, signal="suspicion:引用",
                    audience=AUDIENCE_INTERNAL))
            elif reason == "验收不可测":
                entries.append(_entry(
                    CAT_AMBIGUOUS,
                    f"§{sec}「{title}」的验收标准含不可测表述（如\"符合要求\"），请给出可判定的通过/失败条件",
                    section=sec, quote=quote, source_id=rid, signal="suspicion:验收"))

    # ② 分析层 open_questions + assumptions（engineering_analysis.json）
    ana_path = out_dir / "engineering_analysis.json"
    if ana_path.exists():
        try:
            payload = json.loads(ana_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        for item in payload.get("items") or []:
            sec = str(item.get("source_section") or "")
            rid = (item.get("source_requirement_ids") or [""])[0]
            quote = str(item.get("source_quote") or "")
            for q in (item.get("open_questions") or []):
                entries.append(_entry(CAT_MISSING, str(q), section=sec, quote=quote,
                                      source_id=str(rid), signal="analyze:open_question",
                                      tier=TIER_SOFT))
            for a in (item.get("assumptions") or []):
                entries.append(_entry(
                    CAT_ASSUMPTION, f"推导时假设：{a}——请确认该前提是否成立",
                    section=sec, quote=quote, source_id=str(rid), signal="analyze:assumption",
                    tier=TIER_SOFT))

    # ③ 一致性层（consistency_report.json）：跨章数值矛盾 + 重复表述
    con_path = out_dir / "consistency_report.json"
    if con_path.exists():
        try:
            con = json.loads(con_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            con = {}
        for g in (con.get("obis_coreference") or []):
            if g.get("values_differ"):
                code = g.get("code") or ""
                entries.append(_entry(
                    CAT_CONFLICT,
                    f"OBIS {code} 在多处被引用且数值不一致，请确认以哪一处为准",
                    signal="consistency:obis_values_differ"))
        for g in (con.get("duplicate_groups") or []):
            quote = str(g.get("source_quote") or "")
            entries.append(_entry(
                CAT_CONFLICT,
                "同一原文语句被抽为多条需求，请确认是否合并或存在语义差异",
                quote=quote, signal="consistency:duplicate"))

    return entries


def readiness_verdict(out_dir: Path, questions: int) -> dict[str, Any]:
    """就绪判定（确定性规则）：失败单元>0 / 覆盖率过低 / **必答**澄清过多 → NEEDS WORK。
    questions 传入的是硬信号（必答）条数——软信号（模型自报）不进门限。"""
    reasons: list[str] = []
    quality: dict[str, Any] = {}
    qp = out_dir / "ai_extract_quality.json"
    if qp.exists():
        try:
            quality = json.loads(qp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            quality = {}
    failed = int(quality.get("failed_sections") or 0)
    coverage = quality.get("coverage_pct")
    if failed > 0:
        reasons.append(f"抽取失败单元 {failed} 个")
    if isinstance(coverage, (int, float)) and coverage < READY_MIN_COVERAGE:
        reasons.append(f"覆盖率 {coverage}% < {READY_MIN_COVERAGE:g}%")
    if questions > READY_MAX_QUESTIONS:
        reasons.append(f"必答澄清 {questions} 条 > {READY_MAX_QUESTIONS}")
    return {"verdict": "NEEDS WORK" if reasons else "READY",
            "reasons": reasons, "questions": questions,
            "coverage_pct": coverage, "failed_sections": failed}


def render_markdown(entries: list[dict[str, Any]], readiness: dict[str, Any]) -> str:
    hard = [e for e in entries if e.get("tier") != TIER_SOFT]
    soft = [e for e in entries if e.get("tier") == TIER_SOFT]
    lines = ["# 需求澄清问题清单", "",
             f"**就绪判定：{readiness['verdict']}**"
             + (f"（{'；'.join(readiness['reasons'])}）" if readiness["reasons"] else ""),
             f"必答 {len(hard)} 条 · 参考 {len(soft)} 条（模型自报的假设/开放问题，留档备查）", ""]

    def emit(group_entries: list[dict[str, Any]], heading: str) -> None:
        lines.append(f"# {heading}")
        order = [CAT_CONFLICT, CAT_MISSING, CAT_AMBIGUOUS, CAT_ASSUMPTION]
        for cat in order:
            group = [e for e in group_entries if e["category"] == cat]
            if not group:
                continue
            lines.append(f"## {cat}（{len(group)}）")
            for i, e in enumerate(group, 1):
                lines.append(f"{i}. {e['question']}")
                meta = [x for x in (f"§{e['section']}" if e["section"] else "",
                                    f"来源 {e['source_id'][:12]}" if e["source_id"] else "",
                                    e["signal"]) if x]
                if e["quote"]:
                    lines.append(f"   > {e['quote']}")
                if meta:
                    lines.append(f"   *{' · '.join(meta)}*")
            lines.append("")

    customer = [e for e in hard if e.get("audience") != AUDIENCE_INTERNAL]
    internal = [e for e in hard if e.get("audience") == AUDIENCE_INTERNAL]
    if customer:
        emit(customer, f"必答·问客户（{len(customer)}）——评审会逐条确认")
    if internal:
        emit(internal, f"必答·内部核对（{len(internal)}）——审核员在批注视图核对")
    if soft:
        emit(soft, f"参考（{len(soft)}）——模型自报，抽查即可")
    if not entries:
        lines.append("（无待澄清问题）")
    return "\n".join(lines) + "\n"


def write_xlsx(entries: list[dict[str, Any]], readiness: dict[str, Any], path: Path) -> None:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "必答-问客户"
    header = ["序号", "分类", "问题", "出处章节", "原文引用", "来源需求", "信号", "答复", "采纳(是/否)"]
    ws.append(header)
    hard = [e for e in entries if e.get("tier") != TIER_SOFT]
    soft = [e for e in entries if e.get("tier") == TIER_SOFT]
    customer = [e for e in hard if e.get("audience") != AUDIENCE_INTERNAL]
    internal = [e for e in hard if e.get("audience") == AUDIENCE_INTERNAL]
    for i, e in enumerate(customer, 1):
        ws.append([i, e["category"], formula_safe(e["question"]), e["section"],
                   formula_safe(e["quote"]), e["source_id"], e["signal"]])
    ws_int = wb.create_sheet("必答-内部核对")
    ws_int.append(header[:7])
    for i, e in enumerate(internal, 1):
        ws_int.append([i, e["category"], formula_safe(e["question"]), e["section"],
                       formula_safe(e["quote"]), e["source_id"], e["signal"]])
    ws_soft = wb.create_sheet("参考(模型自报)")
    ws_soft.append(header[:7])
    for i, e in enumerate(soft, 1):
        ws_soft.append([i, e["category"], formula_safe(e["question"]), e["section"],
                        formula_safe(e["quote"]), e["source_id"], e["signal"]])
    ws2 = wb.create_sheet("就绪判定")
    ws2.append(["判定", readiness["verdict"]])
    for r in readiness["reasons"]:
        ws2.append(["原因", formula_safe(r)])
    ws2.append(["待澄清条数", readiness["questions"]])
    ws2.append(["覆盖率%", readiness.get("coverage_pct")])
    ws2.append(["失败单元", readiness.get("failed_sections")])
    from xlsx_io import safe_save_workbook
    safe_save_workbook(wb, path)


def load_answers(out_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """已回灌答复：(来源需求id, 问题) → 答复条目。容错读，坏行跳过。"""
    path = Path(out_dir) / ANSWERS_FILE
    answers: dict[tuple[str, str], dict[str, Any]] = {}
    if not path.exists():
        return answers
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = (str(row.get("source_id") or ""), str(row.get("question") or ""))
        answers[key] = row
    return answers


def import_answers(out_dir: Path, xlsx_path: Path) -> dict[str, Any]:
    """从填好的 clarification_questions.xlsx「必答」sheet 读回答复列 → 落 ANSWERS_FILE。

    闭环的另一半：评审会带走清单，答复填回同一文件，导入后 analyze 把答复当权威客户输入
    （注入富化 prompt + 数值有据基线），澄清报告把已采纳答复的问题消解出必答区。
    """
    from openpyxl import load_workbook
    out_dir = Path(out_dir).expanduser().resolve()
    wb = load_workbook(Path(xlsx_path).expanduser(), data_only=True, read_only=True)
    try:
        sheet_name = next((n for n in ("必答-问客户", "必答") if n in wb.sheetnames), None)
        if sheet_name is None:
            raise ValueError("工作簿缺少「必答-问客户」sheet——请用本工具导出的澄清清单填写答复")
        ws = wb[sheet_name]
        merged = load_answers(out_dir)
        imported = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or len(row) < 8:
                continue
            answer = str(row[7] or "").strip()
            if not answer:
                continue
            entry = {
                "source_id": str(row[5] or "").strip(),
                "category": str(row[1] or "").strip(),
                "question": str(row[2] or "").strip(),
                "answer": answer,
                "adopted": str(row[8] if len(row) > 8 else "").strip() not in ("否", "no", "N", "n"),
            }
            merged[(entry["source_id"], entry["question"])] = entry
            imported += 1
    finally:
        wb.close()
    with (out_dir / ANSWERS_FILE).open("w", encoding="utf-8", newline="\n") as f:
        for entry in merged.values():
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"imported": imported, "total_answers": len(merged),
            "written": [ANSWERS_FILE]}


def run_report(out_dir: Path) -> dict[str, Any]:
    out_dir = Path(out_dir).expanduser().resolve()
    if not (out_dir / "ai_requirements.jsonl").exists():
        # 缺输入响亮失败（仓库纪律：不产"0 问题"的假清单掩盖打错目录）
        raise FileNotFoundError(
            f"ai_requirements.jsonl not found in {out_dir} — 先跑「AI 抽取」再生成澄清清单")
    entries = collect_questions(out_dir)
    answers = load_answers(out_dir)
    resolved = 0
    if answers:
        kept: list[dict[str, Any]] = []
        for e in entries:
            hit = answers.get((e.get("source_id") or "", e.get("question") or ""))
            if hit and hit.get("adopted", True):
                resolved += 1            # 已答复采纳 → 消解，不再出现在清单
                continue
            kept.append(e)
        entries = kept
    hard_count = sum(1 for e in entries if e.get("tier") != TIER_SOFT)
    readiness = readiness_verdict(out_dir, hard_count)
    (out_dir / REPORT_MD).write_text(render_markdown(entries, readiness), encoding="utf-8")
    write_xlsx(entries, readiness, out_dir / REPORT_XLSX)
    by_cat: dict[str, int] = {}
    for e in entries:
        by_cat[e["category"]] = by_cat.get(e["category"], 0) + 1
    from requirement_record import check_provenance, provenance
    warnings: list[str] = []
    ana_path = out_dir / "engineering_analysis.json"
    if ana_path.exists():
        try:
            from requirements_analysis import ANALYZE_PROMPT_VERSION
            warn = check_provenance(json.loads(ana_path.read_text(encoding="utf-8")),
                                    expect_producer="requirements_analysis",
                                    current_version=ANALYZE_PROMPT_VERSION)
            if warn:
                warnings.append(warn)
        except Exception:  # 血统校验永不阻断出报告
            pass
    report = {"questions": hard_count,        # 必答数（就绪门口径；GUI 消息同源）
              "provenance": provenance("clarification_report", "clarification/v2-tiered"),
              "upstream_warnings": warnings,
              "questions_total": len(entries),
              "soft_questions": len(entries) - hard_count,
              "customer_questions": sum(1 for e in entries
                                         if e.get("tier") != TIER_SOFT
                                         and e.get("audience") != AUDIENCE_INTERNAL),
              "internal_checks": sum(1 for e in entries
                                     if e.get("tier") != TIER_SOFT
                                     and e.get("audience") == AUDIENCE_INTERNAL),
              "resolved_by_answers": resolved,
              "by_category": by_cat,
              "readiness": readiness, "entries": entries,
              "written": [REPORT_MD, REPORT_XLSX, REPORT_JSON]}
    (out_dir / REPORT_JSON).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate clarification questions + readiness verdict.")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run_report(args.out)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({k: report[k] for k in ("questions", "by_category", "readiness", "written")},
                     ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
