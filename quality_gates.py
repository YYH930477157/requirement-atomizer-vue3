"""质量门禁（quality-first 方案 §10，M3 shadow）。

效果优先由可执行门禁体现。本模块把**既有权威**（功能直抽守恒、table-cell 处置
状态、routing review 候选、结果包完成证据）投影为统一的 gate 报告：

- PASS           可交付（全部 gate 通过）
- RETRY_LOCAL    存在可局部升级的缺口（review/弱信号/待重抽）
- NEEDS_REVIEW   需要专家确认（结构性 review/澄清挂起）
- NEEDS_WORK     预算/模型/守恒/来源问题阻断（不得降质冒充完成）

红线：PASS 只由质量证据决定，绝不以"全量双轨是否运行过"为条件（§10.3）；
缺产物 = 该 gate NEEDS_WORK（诚实暴露，不是静默跳过）；本模块不重实现任何
领域判定——守恒看 functional 产品、closure 看 dispositions/claim authority、
完成证据看 result_package。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from io_utils import read_jsonl

QUALITY_GATES_VERSION = "quality-gates-v1"
QUALITY_GATE_REPORT_SCHEMA = "quality-gate-report/v1"

GATE_PASS = "pass"
GATE_RETRY_LOCAL = "retry_local"
GATE_NEEDS_REVIEW = "needs_review"
GATE_NEEDS_WORK = "needs_work"

# overall 取最差：needs_work > needs_review > retry_local > pass
_SEVERITY = {GATE_PASS: 0, GATE_RETRY_LOCAL: 1, GATE_NEEDS_REVIEW: 2, GATE_NEEDS_WORK: 3}


def _read_json(path) -> object | None:
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _governed(out_dir, filename: str, *, category: str = "pipeline"):
    from result_package import governed_artifact_path

    return governed_artifact_path(out_dir, filename, category=category, for_write=False)


def _gate(status: str, detail: str, **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"status": status, "detail": detail}
    result.update(extra)
    return result


def evaluate_document_gates(out_dir, *,
                            completion_scope_stages: list[str] | None = None,
                            ) -> dict[str, Any]:
    """只读评估文档级门禁，返回统一报告（不写任何文件）。

    ``completion_scope_stages``（结果包完成路径专用，§22）：把 gate 作用域收到
    本次运行声明的阶段——不含功能直抽的运行不评守恒/执行状态（产物缺席是合法
    形态，不是失败）；结果包完成 gate 在完成时自指（完成证据尚未写入），跳过。
    None = 全量评估（诊断/路由摘要口径）。
    """
    out_dir = Path(out_dir)
    gates: dict[str, dict[str, Any]] = {}
    completion_scope = list(completion_scope_stages or [])
    functional_in_scope = (not completion_scope
                           or "functional-extract" in completion_scope)

    # 1) 功能直抽执行状态 + 守恒（既有权威：functional_requirements.json）。
    # 完成作用域里不含直抽的运行（A 轨/模板/解析类）不评这两项——产物缺席合法
    if not functional_in_scope:
        gates["execution_status"] = _gate(
            GATE_PASS, "本次运行不含功能直抽（不适用）")
        gates["obligation_conservation"] = _gate(
            GATE_PASS, "本次运行不含功能直抽（不适用）")
    else:
        product = _read_json(_governed(out_dir, "functional_requirements.json"))
        if not isinstance(product, dict):
            gates["execution_status"] = _gate(
                GATE_NEEDS_WORK, "functional_requirements.json 缺失（直抽未运行或未落盘）")
            gates["obligation_conservation"] = _gate(
                GATE_NEEDS_WORK, "无功能直抽产物，守恒状态未知")
        else:
            status = str(product.get("execution_status") or "")
            if status == "ok":
                gates["execution_status"] = _gate(GATE_PASS, "execution_status=ok")
            elif status == "partial":
                gates["execution_status"] = _gate(
                    GATE_NEEDS_WORK, "execution_status=partial——直抽不完整不得交付",
                    execution_status=status)
            else:
                gates["execution_status"] = _gate(
                    GATE_NEEDS_WORK, f"execution_status={status or 'missing'}",
                    execution_status=status)
            conservation = product.get("conservation")
            checks = conservation.get("checks") if isinstance(conservation, dict) else None
            conservation_ok = bool(conservation.get("ok")) if isinstance(conservation, dict) else False
            if conservation_ok:
                gates["obligation_conservation"] = _gate(
                    GATE_PASS, "义务守恒闭合（既有权威判定）")
            elif isinstance(checks, dict):
                failed = sorted(name for name, item in checks.items()
                                if isinstance(item, dict) and not item.get("ok"))
                gates["obligation_conservation"] = _gate(
                    GATE_NEEDS_WORK,
                    f"守恒未闭合：{', '.join(failed) or 'ok=false'}（复用既有 blocking 语义）",
                    failed_checks=failed)
            else:
                gates["obligation_conservation"] = _gate(
                    GATE_NEEDS_WORK, "守恒报告缺失或不可读")

    # 2) table-cell closure（既有权威：dispositions 的 structure_review_status）。
    # 无表格内容（cell items 缺席或零行——atomize 会写空文件）= 不适用；有表格
    # 但缺 dispositions = 旧产物缺基础迁移，needs_work（不可静默放行）
    from result_package import governed_artifact_path as _gap

    cell_items = read_jsonl(_gap(out_dir, "table_cell_items.jsonl",
                                 category="pipeline", for_write=False))
    dispositions = read_jsonl(_gap(out_dir, "table_cell_dispositions.jsonl"))
    if not cell_items and not dispositions:
        gates["table_cell_closure"] = _gate(
            GATE_PASS, "无表格内容（table-cell closure 不适用）")
    elif not dispositions:
        gates["table_cell_closure"] = _gate(
            GATE_NEEDS_WORK, "有表格产物但 table_cell_dispositions.jsonl 缺失")
    else:
        pending = sum(1 for row in dispositions
                      if str(row.get("structure_review_status") or "") == "pending")
        if pending:
            gates["table_cell_closure"] = _gate(
                GATE_NEEDS_REVIEW, f"{pending} 个 cell 处置待审（review 候选阻断 Ledger Ready）",
                pending_count=pending)
        else:
            gates["table_cell_closure"] = _gate(
                GATE_PASS, f"{len(dispositions)} 个 canonical cell 处置就绪")

    # 3) routing review 候选（M2 shadow 产物；缺产物 = 未路由，不阻塞 legacy 执行）
    decisions = read_jsonl(_governed(out_dir, "unit_routing_decisions.jsonl"))
    if decisions:
        review_count = sum(1 for row in decisions if row.get("route") == "review")
        gates["routing_review_pending"] = _gate(
            GATE_RETRY_LOCAL if review_count else GATE_PASS,
            (f"{review_count} 个 review 单元待专家判定（已物化，未静默丢弃）"
             if review_count else "无 review 单元"),
            review_count=review_count)
    else:
        gates["routing_review_pending"] = _gate(
            GATE_PASS, "未运行单元路由（legacy 执行，无 review 候选）")

    # 4) 结果包完成证据：完成路径自指（完成证据此刻尚未写入）——完成作用域下跳过；
    #    全量诊断口径仍评估
    if completion_scope:
        gates["result_package_completion"] = _gate(
            GATE_PASS, "完成时自指，不适用（发布后由 result-package --verify 把关）")
    else:
        marker_dict = _read_json(out_dir / "result-package.json")
        if isinstance(marker_dict, dict):
            completion = marker_dict.get("completion_evidence")
            if isinstance(completion, dict) and completion.get("complete"):
                gates["result_package_completion"] = _gate(
                    GATE_PASS, "结果包完成证据在场（既有校验由 result-package --verify 承担）")
            else:
                gates["result_package_completion"] = _gate(
                    GATE_NEEDS_WORK, "结果包 marker 在场但完成证据缺失/未完成")
        else:
            gates["result_package_completion"] = _gate(
                GATE_PASS, "legacy 平铺布局（无结果包 marker，不适用）")

    overall = max((str(gate.get("status") or GATE_NEEDS_WORK) for gate in gates.values()),
                  key=lambda status: _SEVERITY.get(status, _SEVERITY[GATE_NEEDS_WORK]))
    return {
        "schema": QUALITY_GATE_REPORT_SCHEMA,
        "version": QUALITY_GATES_VERSION,
        "gates": gates,
        "overall": overall,
        "gate_count": len(gates),
    }
