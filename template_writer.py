"""模板成文器（终局架构的第三步，用户两轮裁定后的最终形态）。

  理解（AI 抽取，按文档逻辑） → 分析（软件需求分析轨：软/硬/协同 + 可研发正文 + 研发指引）
  → **成文（本模块）：分析结果按公司标准化需求列表 V2.3.x 的格式写入对应模块 sheet**

模板 = 交付格式与风格样本，**不是问题库**——已有行原样保留（风格参照），每条分析后的客户
需求作为**新行追加**到对应模块 sheet 尾部：子模块/描述/需求/说明/是否客户需求=是/客户需求
章节/驱动硬件相关。纯确定性（零 LLM）：分析内容来自 analyze 轨，这里只做格式装配。

模块 → sheet 映射按模板实际 sheet 清单构建；没有对应 sheet 的模块（如 安全/环境可靠性）落到
新建的「其他需求(新增)」sheet——诚实存放，不硬塞。

用法：python -m template_writer --out <目录（含 engineering_analysis.json）>
      --template <V2.3.x.xlsx>
产物：<out>/软件需求列表-成文.xlsx + <out>/template_writer_report.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from requirements_analysis_excel import _notes_text, _safe_cell, clarify_display_text
from requirements_analysis_schema import OWNERSHIP_CO_DESIGN, OWNERSHIP_HARDWARE
from compliance import is_compliance_requirement

LOGGER = logging.getLogger("requirement_atomizer")

WRITTEN_WORKBOOK = "软件需求列表-成文.xlsx"
WRITER_REPORT = "template_writer_report.json"
FALLBACK_SHEET = "其他需求(新增)"

# 模板统一列位（V2.3.x 实测 19 个需求 sheet 一致）
_COL_SEQ = 2
_COL_SUBMODULE = 3
_COL_QUESTION = 4    # 描述
_COL_ANSWER = 6      # 需求
_COL_NOTES = 7       # 说明、示例、注意事项
_COL_IS_CUSTOMER = 8
_COL_SECTION = 9
_COL_HW = 10         # 驱动/硬件相关

# 需求 sheet 表头签名 + 列契约（读取侧 ab_runner 门禁共享；V2.3.x 实测布局）。
# 计量需求 sheet 的「需求」列被电表类型列拆分（1P2W_SP/3P4W_DC/... 表头别名定位
# 失效）——写入与读取共用此固定列位权威，读取的正是写入器写入的位置。
REQUIREMENT_SHEET_SIGNATURE = ("序号", "子模块")
WRITER_COLUMN_CONTRACT = {
    "module": _COL_SUBMODULE,
    "body": _COL_ANSWER,
    "notes": _COL_NOTES,
    "section": _COL_SECTION,
}

# 抽取轨模块名 → 模板 sheet 名（sheet 存在性运行时校验；缺的落 FALLBACK）
MODULE_TO_SHEET = {
    "计量": "计量需求", "时钟": "时钟需求", "费率": "费率需求", "显示": "显示需求",
    "需量": "需量需求", "结算": "结算需求", "曲线": "负荷曲线", "窃电": "报警窃电需求",
    "电网质量": "电网质量需求", "升级": "升级需求", "负控": "负控需求", "状态字": "状态字需求",
    "事件记录": "事件需求", "通信协议": "协议栈需求", "Push": "push需求", "预付费": "预付费需求",
    "计量精度": "计量需求", "门限范围": "系统需求", "数据存储": "系统需求",
    "CIU": FALLBACK_SHEET, "其它": FALLBACK_SHEET, "安全": FALLBACK_SHEET,
    "机械结构": FALLBACK_SHEET, "测试合规": FALLBACK_SHEET, "环境可靠性": FALLBACK_SHEET,
    "节假日": FALLBACK_SHEET, "附加功能": FALLBACK_SHEET,
}


def target_sheet(item: dict[str, Any], sheetnames: list[str]) -> str:
    # module 是模板词表归一后的值，submodule 保留抽取轨原模块名——两级尝试
    for key in ("module", "submodule"):
        sheet = MODULE_TO_SHEET.get(str(item.get(key) or "").strip(), "")
        if sheet in sheetnames:
            return sheet
    return FALLBACK_SHEET


def module_mapping_drift() -> tuple[list[str], list[str]]:
    """MODULE_TO_SHEET 与抽取轨 MODULE_VOCAB 的漂移检查（0711 评审）。

    返回 (vocab 里没有映射的模块, 映射表里多余的、不在 vocab 的键)。两份词表分头维护
    易漂移：新增模块没进映射表 → 静默落 FALLBACK_SHEET；映射表里写错/多写 → 永不命中。
    报告里显式列出，供人核，不阻断成文。
    """
    try:
        from ai_extract import MODULE_VOCAB
    except Exception:
        return ([], [])
    vocab = set(MODULE_VOCAB)
    mapped = set(MODULE_TO_SHEET)
    unmapped = sorted(vocab - mapped)
    extra = sorted(mapped - vocab)
    return (unmapped, extra)


def _is_empty_item(item: dict[str, Any]) -> bool:
    """全空条目判据：描述/正文/说明皆空——没有可交付内容（v2 跳过并审计）。"""
    body = clarify_display_text(item, "software_requirement_text") or item.get("requirement") or ""
    return not str(item.get("description") or "").strip() and not str(body).strip() \
        and not str(_notes_text(item)).strip()


def _next_seq(ws: Any) -> tuple[int, int]:
    """返回 (下一序号, 追加起始行)。序号接着表内最大数字序号继续。"""
    max_seq = 0
    last_row = 1
    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if row and any(c not in (None, "") for c in row):
            last_row = row_idx
        try:
            max_seq = max(max_seq, int(str(row[_COL_SEQ - 1]).strip()))
        except (TypeError, ValueError, IndexError):
            pass
    return max_seq + 1, last_row + 1


def build_row_values(item: dict[str, Any], seq: int,
                     columns: dict[str, int] | None = None) -> dict[int, Any]:
    """分析条目 → 模板行（列号→值）。内容全部来自 analyze 轨产物，此处零生成。

    ``columns`` 是按表头名解析的列位（v2）；缺省/None 回退固定列位常量（v1 契约，
    计量需求拆分列场景）。列语义键：seq/submodule/question/answer/notes/
    is_customer/section/hw。
    v3（partial export，2026-09-01）：待核前缀由 ``_notes_text`` 单源渲染
    （``conservation_pending.classes`` → ``pending_class_label``）；此处不再二次加前缀。
    不打 draft 水印（那是 stub 语义）。
    """
    hw = "是" if item.get("ownership") == OWNERSHIP_CO_DESIGN else ""
    resolved = columns or {}
    # 正文兜底链（v2）：分析轨 refinement → 原始 requirement → objective 前缀化
    # ——全是真实分析产物，杜绝「需求」列空行（门禁按空正文行 fail-closed）。
    body = (
        clarify_display_text(item, "software_requirement_text")
        or str(item.get("requirement") or "").strip()
    )
    if not body:
        objective = str(item.get("objective") or "").strip()
        if objective:
            body = f"目标：{objective}"
    notes = _notes_text(item)
    return {
        resolved.get("seq", _COL_SEQ): seq,
        resolved.get("submodule", _COL_SUBMODULE): item.get("submodule") or item.get("module") or "",
        resolved.get("question", _COL_QUESTION): item.get("description") or "",
        resolved.get("answer", _COL_ANSWER): body,
        resolved.get("notes", _COL_NOTES): notes,
        resolved.get("is_customer", _COL_IS_CUSTOMER): "是",
        resolved.get("section", _COL_SECTION): item.get("source_section") or "",
        resolved.get("hw", _COL_HW): hw,
    }


# 表头名 → 列语义键（v2 按名解析；需求模版列在场与否不再影响列位）。
_HEADER_ALIASES: dict[tuple[str, ...], str] = {
    ("序号",): "seq",
    ("子模块",): "submodule",
    ("描述",): "question",
    ("需求模版", "需求模板"): "template",
    ("需求",): "answer",
    ("说明、示例、注意事项", "说明、示例和注意事项"): "notes",
    ("是否客户需求",): "is_customer",
    ("客户需求章节",): "section",
    ("驱动/硬件相关", "驱动／硬件相关"): "hw",
}


def resolve_sheet_columns(ws: Any) -> dict[str, int] | None:
    """按第一行表头名解析需求 sheet 列位；关键列不齐 → None（回退固定契约）。

    门禁 FAIL 根因修复（template_writer/v2）：事件需求/状态字需求 sheet 是
    8 列布局（无「需求模版」列），固定列位会把正文写进「说明」列、「需求」列
    空着。关键列 = seq + submodule + answer + notes（缺一即回退）。
    """
    header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None) or ()
    resolved: dict[str, int] = {}
    for index, cell in enumerate(header_row, start=1):
        text = str(cell or "").strip()
        if not text:
            continue
        for aliases, semantic in _HEADER_ALIASES.items():
            if text in aliases and semantic not in resolved:
                resolved[semantic] = index
                break
    if all(key in resolved for key in ("seq", "submodule", "answer", "notes")):
        return resolved
    return None


def append_analysis_to_template(template_path: Path, items: list[dict[str, Any]],
                                out_path: Path,
                                gap_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """把分析条目按模块追加进模板副本。硬件独占项不进软件需求列表（走 hardware_items.md，
    与 analyze 轨一致）；协同项进列表并标「驱动/硬件相关=是」。

    v3（partial export）：``conservation_pending.classes`` 非空的追加行，序号/
    需求/说明三格标红；工作簿内另建「守恒待核」清单 sheet（FRE 行 + 零 FRE 缺口
    行 ``gap_rows``——缺口只进清单，不造需求占位行）。守恒闭合且无降级无缺口
    时零漂移（无 sheet、无前缀、无红字）。
    """
    from openpyxl import load_workbook
    from openpyxl.styles import Font

    wb = load_workbook(template_path)
    appended: dict[str, int] = {}
    column_resolution: dict[str, str] = {}
    skipped_hardware = 0
    skipped_compliance = 0
    skipped_empty = 0
    pending_rows = 0
    pending_classes: dict[str, int] = {}
    pending_item_rows: list[tuple[str, list[str], str]] = []

    software_items = []
    for item in items:
        # ``source_requirement_type`` is emitted by requirements_analysis, not by the narrative
        # LLM. Trust it only at this final defensive boundary so a stale analysis file cannot put
        # a known compliance row back into the software workbook.
        source_type = str(item.get("source_requirement_type") or "").casefold()
        if source_type == "compliance" or is_compliance_requirement(item):
            skipped_compliance += 1
            continue
        if item.get("ownership") == OWNERSHIP_HARDWARE:
            skipped_hardware += 1
            continue
        software_items.append(item)

    # 分组后逐 sheet 追加（保证同 sheet 序号连续）
    by_sheet: dict[str, list[dict[str, Any]]] = {}
    for item in software_items:
        by_sheet.setdefault(target_sheet(item, wb.sheetnames), []).append(item)

    red_font = Font(color="FFFF0000")
    for sheet, sheet_items in by_sheet.items():
        if sheet == FALLBACK_SHEET and sheet not in wb.sheetnames:
            ws = wb.create_sheet(FALLBACK_SHEET)
            ws.append(["关闭", "序号", "子模块", "描述", "需求模版", "需求",
                       "说明、示例、注意事项", "是否客户需求", "客户需求章节", "驱动/硬件相关"])
        ws = wb[sheet]
        # v2：按表头名解析列位（8 列窄布局 sheet 不再错位）；解析失败回退固定契约
        columns = resolve_sheet_columns(ws)
        column_resolution[sheet] = "header" if columns else "contract"
        seq, row_idx = _next_seq(ws)
        written_here = 0
        for item in sheet_items:
            if _is_empty_item(item):
                # 全空条目（描述/正文/说明皆空）没有可交付内容——跳过并审计，
                # 不再产生只有序号的空行（门禁按空正文行 fail-closed）。
                skipped_empty += 1
                continue
            for col, value in build_row_values(item, seq, columns).items():
                ws.cell(row=row_idx, column=col, value=_safe_cell(value))
            pending = item.get("conservation_pending") if isinstance(
                item.get("conservation_pending"), dict) else None
            if pending and pending.get("classes"):
                pending_rows += 1
                for cls in pending["classes"]:
                    pending_classes[str(cls)] = pending_classes.get(str(cls), 0) + 1
                # v3：待核行的序号/需求/说明标红——只染本趟追加行，模板样例行不动
                resolved = columns or {}
                for key, fallback in (
                    ("seq", _COL_SEQ), ("answer", _COL_ANSWER), ("notes", _COL_NOTES),
                ):
                    ws.cell(row=row_idx, column=resolved.get(key, fallback)).font = red_font
                pending_item_rows.append((
                    str(item.get("functional_requirement_id") or ""),
                    [str(c) for c in pending["classes"]],
                    str(item.get("source_section") or ""),
                ))
            seq += 1
            row_idx += 1
            written_here += 1
        if written_here:
            appended[sheet] = written_here

    # v3：「守恒待核」清单 sheet（已存在则清空重写——续跑不叠行）
    pending_sheet_rows = _write_pending_sheet(wb, pending_item_rows, gap_rows or [])
    from xlsx_io import safe_save_workbook
    out_path = safe_save_workbook(wb, out_path)
    return {"appended_by_sheet": dict(sorted(appended.items(), key=lambda x: -x[1])),
            "appended_total": sum(appended.values()),
            "skipped_hardware": skipped_hardware,
            "skipped_compliance": skipped_compliance,
            "skipped_empty_items": skipped_empty,
            "column_resolution": column_resolution,
            # partial export（v3）：待核行级标记审计（template_write_task 据此
            # 自报 unclosed_basis → 阶段记 partial；类计数供报告/UI）。
            # pending_sheet_rows/gap_rows：清单 sheet 数据行与其中的零 FRE 缺口行
            # （守恒闭合且无降级无缺口 = None，与 v2 干净工作簿同形）。
            "conservation_pending_export": {
                "marked_rows": pending_rows,
                "classes": dict(sorted(pending_classes.items())),
                **({"pending_sheet_rows": pending_sheet_rows,
                    "gap_rows": len(gap_rows or [])} if pending_sheet_rows else {}),
            } if (pending_rows or pending_sheet_rows) else None,
            "workbook": out_path.name}


# 「守恒待核」sheet：类别 | 原因 | 功能需求ID | 章节 | token | 说明
_PENDING_SHEET_NAME = "守恒待核"
_PENDING_SHEET_HEADER = ["类别", "原因", "功能需求ID", "章节", "token", "说明"]


def _write_pending_sheet(
    wb: Any,
    item_rows: list[tuple[str, list[str], str]],
    gap_rows: list[dict[str, Any]],
) -> int:
    """写「守恒待核」清单 sheet，返回数据行数（不含总述/表头）。

    FRE 行来自已挂 ``conservation_pending`` 的分析条目（每 class 一行）；
    缺口行来自 ``functional_extract.conservation_pending_gaps``（零 FRE 可挂，
    只进清单不进需求 sheet）。无任何行时不建 sheet（干净工作簿零漂移）。
    """
    if not item_rows and not gap_rows:
        return 0
    from openpyxl.styles import Font

    from functional_extract import pending_class_label, pending_gap_label

    if _PENDING_SHEET_NAME in wb.sheetnames:
        del wb[_PENDING_SHEET_NAME]
    ws = wb.create_sheet(_PENDING_SHEET_NAME)
    ws.merge_cells("A1:F1")
    ws["A1"] = "本工作簿为待核导出。不得作为已验收交付。"
    ws["A1"].font = Font(color="FFFF0000", bold=True)
    ws.append(_PENDING_SHEET_HEADER)
    data_rows = 0
    for fre_id, classes, section in item_rows:
        for cls in classes:
            # 类别=人读标签（与需求 sheet 说明列前缀同措辞）；原因=类键（机器可归并）；
            # 说明列留空——类别已表达该行信息，不再重复一遍人读标签（2026-09-05 review P3）
            ws.append([pending_class_label([cls]), cls,
                       fre_id, section, "", ""])
            data_rows += 1
    for gap in gap_rows:
        category = str(gap.get("category") or "")
        # 与 FRE 行同形：类别=人读，原因=机键；原 reason 句子进说明
        ws.append([
            pending_gap_label(category),
            category,
            str(gap.get("functional_requirement_id") or ""),
            str(gap.get("section_id") or ""),
            str(gap.get("token") or ""),
            str(gap.get("reason") or gap.get("detail") or ""),
        ])
        data_rows += 1
    return data_rows


def run_writer(out_dir: Path, template_path: Path) -> dict[str, Any]:
    out_dir = Path(out_dir).expanduser().resolve()
    analysis_path = out_dir / "engineering_analysis.json"
    if not analysis_path.exists():
        raise FileNotFoundError(
            f"engineering_analysis.json not found in {out_dir} — 先跑「软件需求分析」（分析在前，成文在后）")
    payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    items = payload.get("items") or []
    out_path = out_dir / WRITTEN_WORKBOOK
    # v3（Task4）：守恒缺口行——governed 双路径读 FR（package_v1 下裸读读不到），
    # 只为「守恒待核」清单 sheet 算零 FRE 缺口（条目上的 class 已由分析挂好）。
    gap_rows: list[dict[str, Any]] = []
    from requirements_analysis_rules import _read_functional_requirements_payload

    fr = _read_functional_requirements_payload(out_dir)
    if isinstance(fr, dict) and isinstance(fr.get("conservation"), dict):
        if not fr["conservation"].get("ok", True):
            from functional_extract import (
                conservation_pending_gaps,
                load_conservation_baseline,
            )

            sections = load_conservation_baseline(out_dir)
            gap_rows = conservation_pending_gaps(
                fr["conservation"],
                fr.get("items") if isinstance(fr.get("items"), list) else [],
                sections,
            )
    report = append_analysis_to_template(template_path, items, out_path, gap_rows=gap_rows)
    from requirement_record import provenance as _prov
    report["provenance"] = _prov("template_writer", "template_writer/v3")
    unmapped, extra = module_mapping_drift()
    if unmapped or extra:
        report["module_mapping_drift"] = {"unmapped_vocab": unmapped, "extra_keys": extra}
        LOGGER.warning("模块→sheet 映射与抽取词表漂移：未映射=%s 多余=%s（缺失项将落兜底 sheet）",
                       unmapped, extra)
    report.update({"items": len(items), "analysis_route": payload.get("route"),
                   "written": [report.get("workbook") or WRITTEN_WORKBOOK, WRITER_REPORT]})
    from input_completeness import attach_input_completeness

    attach_input_completeness(report, out_dir)
    (out_dir / WRITER_REPORT).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write analyzed requirements into the company template workbook.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run_writer(args.out, args.template)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
