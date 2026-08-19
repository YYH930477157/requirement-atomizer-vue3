"""desktop_tasks 的 CLI 参数解析（M9 第 2 刀，2026-08-17d 自 desktop_tasks 机械抽取）。

逐字搬运 parse_args（252 行纯 argparse 构造，零模块内依赖——AST 实证）；
desktop_tasks 原名重导出，调用路径与 patch 语义不变。
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path



def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Requirement Atomizer desktop tasks.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--input", type=Path, required=True)
    run_parser.add_argument("--out", type=Path, required=True)
    run_parser.add_argument("--skip-review", action="store_true")
    run_parser.add_argument("--llm-route", choices=["stub", "openai_compatible"], default=None)
    run_parser.add_argument("--review-scope", choices=["targeted", "all"], default=None)
    run_parser.add_argument("--llm-review-limit", type=int, default=0)
    run_parser.add_argument("--chunk-chars", type=int, default=3500)
    run_parser.add_argument("--kb", type=Path, action="append", default=[])
    run_parser.add_argument("--domain-pack", type=Path, default=None)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--out", type=Path, required=True)
    export_parser.add_argument("--formats", default="csv,md")

    assemble_parser = subparsers.add_parser("assemble")
    assemble_parser.add_argument("--out", type=Path, required=True)
    assemble_parser.add_argument("--formats", default="xlsx,docx,md")
    assemble_parser.add_argument("--enrich-route", default="")
    assemble_parser.add_argument("--blue-book-index", type=Path, default=None)

    synthesis_parser = subparsers.add_parser("functional-synthesis")
    synthesis_parser.add_argument("--out", type=Path, required=True)
    synthesis_parser.add_argument("--llm-route", choices=["stub", "openai_compatible"], default="stub")

    compose_parser = subparsers.add_parser("compose")
    compose_parser.add_argument("--out", type=Path, required=True)

    bank_parser = subparsers.add_parser("adjudication-bank")
    bank_parser.add_argument("--out", type=Path, required=True)
    bank_parser.add_argument("--bank", type=Path, required=True)

    answers_parser = subparsers.add_parser("import-clarification-answers")
    answers_parser.add_argument("--out", type=Path, required=True)
    answers_parser.add_argument("--file", type=Path, required=True)

    chain_parser = subparsers.add_parser("chain")
    chain_parser.add_argument("--out", type=Path, required=True)
    chain_parser.add_argument("--stages", required=True, help="逗号分隔的阶段清单（按依赖自动排序）")
    # 默认与独立子命令一致（openai_compatible）：headless 忘带路由时"没配 key 响亮失败"
    # 优于"静默 stub 产空行为需求且 manifest 全 ok"（2026-07-08 审计 A4）
    chain_parser.add_argument("--llm-route", default="openai_compatible", choices=["stub", "openai_compatible"])
    chain_parser.add_argument("--template", type=Path, default=None)
    chain_parser.add_argument("--sample-ratio", type=float, default=None)
    chain_parser.add_argument("--limit-sections", type=int, default=None)
    chain_parser.add_argument("--annotation-layout-mode", choices=["optimized", "pdf_original"],
                              default="pdf_original")
    chain_parser.add_argument("--translation-mode", choices=["off", "markers", "full"],
                              default=None,
                              help="翻译交付模式（off=零翻译调用；默认不传=既有行为）")

    clarification_parser = subparsers.add_parser("clarification-report")
    clarification_parser.add_argument("--out", type=Path, required=True)

    template_write_parser = subparsers.add_parser("template-write")
    template_write_parser.add_argument("--out", type=Path, required=True)
    template_write_parser.add_argument("--template", type=Path, required=True)

    requirements_analysis_parser = subparsers.add_parser("requirements-analysis")
    requirements_analysis_parser.add_argument("--out", type=Path, required=True)
    requirements_analysis_parser.add_argument("--template", type=Path, default=None)
    requirements_analysis_parser.add_argument("--llm-route", choices=["stub", "openai_compatible"], default="stub")

    ai_extract_parser = subparsers.add_parser("ai-extract")
    ai_extract_parser.add_argument("--out", type=Path, required=True)
    ai_extract_parser.add_argument("--llm-route", choices=["stub", "openai_compatible"], default="openai_compatible")
    ai_extract_parser.add_argument("--limit-sections", type=int, default=0)
    ai_extract_parser.add_argument("--sample-ratio", type=float, default=0.0)

    functional_extract_parser = subparsers.add_parser("functional-extract")
    functional_extract_parser.add_argument("--out", type=Path, required=True)
    # 默认 openai_compatible（与 ai-extract 同款审计 A4 纪律）：没配 key 响亮失败
    functional_extract_parser.add_argument("--llm-route", choices=["stub", "openai_compatible"],
                                           default="openai_compatible")

    summary_parser = subparsers.add_parser("summary")
    summary_parser.add_argument("--out", type=Path, required=True)

    anno_parser = subparsers.add_parser("export-annotation-html")
    anno_parser.add_argument("--out", type=Path, required=True)
    anno_parser.add_argument("--route", choices=["stub", "openai_compatible"], default=None,
                             help="openai_compatible 时补齐块级说明标记的中文翻译（缓存复用）")
    anno_parser.add_argument("--layout-mode", choices=["optimized", "pdf_original"],
                             default="pdf_original")

    full_translation_parser = subparsers.add_parser("full-translation")
    full_translation_parser.add_argument("--out", type=Path, required=True)
    full_translation_parser.add_argument(
        "--route", choices=["stub", "openai_compatible"], default="openai_compatible"
    )

    import_parser = subparsers.add_parser("import-ai-decisions")
    import_parser.add_argument("--out", type=Path, required=True)
    import_parser.add_argument("--file", type=Path, required=True, help="HTML 导出的裁决 JSON")

    # --- WS4 能力补齐子命令（全程零 LLM 调用）---
    verify_import_parser = subparsers.add_parser(
        "import-verification",
        help="回灌线下改过的 software_requirements.xlsx 六列 → verification_states.jsonl")
    verify_import_parser.add_argument("--out", type=Path, required=True)
    verify_import_parser.add_argument("--file", type=Path, required=True)
    verify_import_parser.add_argument("--actor", default="desktop-verification")

    verify_set_parser = subparsers.add_parser(
        "set-verification", help="直接写入一条需求 verification 覆盖（状态机前进迁移）")
    verify_set_parser.add_argument("--out", type=Path, required=True)
    verify_set_parser.add_argument("--requirement-id", required=True)
    verify_set_parser.add_argument("--implemented", default=None,
                                   choices=["not_started", "in_progress", "done"])
    verify_set_parser.add_argument("--test-completed", default=None, choices=["true", "false"])
    verify_set_parser.add_argument("--test-case-ids", default=None, help="分号/逗号分隔的测试用例号")
    verify_set_parser.add_argument("--confirm-pm", default=None, choices=["true", "false"])
    verify_set_parser.add_argument("--confirm-tl", default=None, choices=["true", "false"])
    verify_set_parser.add_argument("--confirm-dt", default=None, choices=["true", "false"])
    verify_set_parser.add_argument("--actor", default="desktop-verification")

    rollback_parser = subparsers.add_parser(
        "rollback-requirement", help="人工回退需求生命周期（回退事件 append-only 留痕）")
    rollback_parser.add_argument("--out", type=Path, required=True)
    rollback_parser.add_argument("--requirement-id", required=True)
    rollback_parser.add_argument("--target", required=True,
                                 choices=["draft", "confirmed", "implemented", "verified"])
    rollback_parser.add_argument("--actor", required=True)
    rollback_parser.add_argument("--reason", required=True)

    manual_parser = subparsers.add_parser(
        "add-manual-requirement", help="手工建需求（provenance=manual，追溯列留空不伪引）")
    manual_parser.add_argument("--out", type=Path, required=True)
    manual_parser.add_argument("--objective", required=True)
    manual_parser.add_argument("--behaviors", default=None, help="逗号分隔的行为列表")
    manual_parser.add_argument("--module", default="")
    manual_parser.add_argument("--ownership", default="", choices=["", "software", "hardware", "co_design"])
    manual_parser.add_argument("--priority", default="P1")
    manual_parser.add_argument("--notes", default="")
    manual_parser.add_argument("--actor", default="desktop-manual")

    lib_build_parser = subparsers.add_parser(
        "build-requirement-library", help="汇总各项目 functional_requirements 为 JSONL 检索库")
    lib_build_parser.add_argument("--projects", type=Path, nargs="+", required=True)
    lib_build_parser.add_argument("--library", type=Path, required=True, help="输出的检索库 JSONL 路径")
    lib_build_parser.add_argument(
        "--include-unconfirmed", action="store_true",
        help="默认仅收录 lifecycle>=confirmed 的条目；此开关显式收录 draft（未确认）条目")

    lib_search_parser = subparsers.add_parser(
        "search-requirements", help="词面集合重叠度召回历史相似需求")
    lib_search_parser.add_argument("--library", type=Path, required=True)
    lib_search_parser.add_argument("--query", required=True)
    lib_search_parser.add_argument("--limit", type=int, default=20)

    dep_rec_parser = subparsers.add_parser(
        "recommend-dependencies", help="确定性依赖/父子候选推荐（只生产值，不动 schema）")
    dep_rec_parser.add_argument("--out", type=Path, required=True)

    dep_dec_parser = subparsers.add_parser(
        "decide-dependency", help="依赖候选裁决（接受才写库，拒绝不落库）")
    dep_dec_parser.add_argument("--out", type=Path, required=True)
    dep_dec_parser.add_argument("--from", dest="from_id", required=True)
    dep_dec_parser.add_argument("--to", required=True)
    dep_dec_parser.add_argument("--kind", required=True, choices=["depend", "exclude", "refine"])
    dep_dec_parser.add_argument("--accept", choices=["true", "false"], default="true")
    dep_dec_parser.add_argument("--actor", default="desktop-dependency")
    dep_dec_parser.add_argument("--reason", default="")

    claim_acceptance_parser = subparsers.add_parser("claim-shadow-acceptance")
    claim_acceptance_parser.add_argument("--input", type=Path, required=True)
    claim_acceptance_parser.add_argument("--output", type=Path)

    claim_packet_parser = subparsers.add_parser("claim-shadow-review-packet")
    claim_packet_parser.add_argument("--input", type=Path, required=True)
    claim_packet_parser.add_argument("--output-dir", type=Path, required=True)

    claim_import_parser = subparsers.add_parser("claim-shadow-review-import")
    claim_import_parser.add_argument("--input", type=Path, required=True)
    claim_import_parser.add_argument("--decisions", type=Path, required=True)
    claim_import_parser.add_argument("--output", type=Path, required=True)
    claim_import_parser.add_argument("--golden-manifest", type=Path, required=True)

    claim_fold_parser = subparsers.add_parser("claim-ledger-fold")
    claim_fold_parser.add_argument(
        "--out-dir",
        "--out",
        dest="out",
        type=Path,
        required=True,
    )

    # T2 编排环（agent_loop 升格）：缺口驱动的再规划，裁决仍在专家面板。
    orchestrate_parser = subparsers.add_parser(
        "orchestrate",
        help="编排环：读缺口→授权补抽→写 trace，直到收敛或达上限（NEEDS WORK 交人）")
    orchestrate_parser.add_argument("--out-dir", "--out", dest="out", type=Path, required=True)
    orchestrate_parser.add_argument(
        "--max-rounds", type=int, default=None,
        help=f"每文档最大编排轮次（默认 8，上限 50；env RATOMIZER_ORCHESTRATION_MAX_ROUNDS）")
    orchestrate_parser.add_argument(
        "--allow-llm", action="store_true",
        help="授权编排环发起 spot_extract/targeted_reextract（默认关闭=只读缺口转人工；"
             "env RATOMIZER_ORCHESTRATION_ALLOW_LLM=1 等效）")
    orchestrate_parser.add_argument("--actor", default="orchestration-loop")

    # V3 WS-A A3：整篇对账 sidecar（CHAIN_ORDER 之外，同 orchestrate 纪律）。
    reconcile_parser = subparsers.add_parser(
        "reconcile",
        help="整篇对账：规则筛疑+LLM 裁定两段，写 reconcile_report.json 并并入 quality_report")
    reconcile_parser.add_argument("--out-dir", "--out", dest="out", type=Path, required=True)
    reconcile_parser.add_argument(
        "--llm-route", choices=["stub", "openai_compatible"], default="stub",
        help="裁定投票路由（默认 stub=仅规则筛疑 rules_only）")

    # WS-H：知识沉淀闭环（成文导出后自动/手动 harvest）
    harvest_parser = subparsers.add_parser(
        "harvest",
        help="执行 WS-H 知识沉淀闭环：收割裁决样本、confirmed 需求、方案、领域知识、语言资产、校准资产",
    )
    harvest_parser.add_argument("--out", type=Path, required=True)
    harvest_parser.add_argument("--actor", default="desktop-harvest")

    cost_report_parser = subparsers.add_parser("cost-report")
    cost_report_parser.add_argument(
        "--out-dir", "--out", dest="out", type=Path, required=True,
        help="结果目录（读 governed state/llm_budget.json）",
    )

    package_start_parser = subparsers.add_parser("result-package-start")
    package_start_parser.add_argument("--out", type=Path, required=True)
    package_start_parser.add_argument("--input", type=Path, required=True)
    package_start_parser.add_argument("--stages", required=True)

    package_complete_parser = subparsers.add_parser("result-package-complete")
    package_complete_parser.add_argument("--out", type=Path, required=True)
    package_complete_parser.add_argument("--run-id", required=True)
    package_complete_parser.add_argument("--completed-stages", required=True)

    package_fail_parser = subparsers.add_parser("result-package-fail")
    package_fail_parser.add_argument("--out", type=Path, required=True)
    package_fail_parser.add_argument("--run-id", required=True)
    package_fail_parser.add_argument("--error", required=True)

    package_status_parser = subparsers.add_parser("result-package-status")
    package_status_parser.add_argument("--out", type=Path, required=True)
    package_status_parser.add_argument(
        "--verify",
        action="store_true",
        # S5：显式完整校验（「打开已有结果」）——重算交付物/完成证据 SHA
        help="recompute deliverable and completion-evidence hashes (fail on mismatch)",
    )
    return parser.parse_args(argv)


def build_requirement_library_task(
    project_dirs: list[Path],
    output_path: Path,
    *,
    include_unconfirmed: bool = False,
) -> dict[str, Any]:
    """汇总各项目 functional_requirements 为带项目元数据的 JSONL 检索库（不引入数据库）。

    S1-10d 需求库入库质量门：默认仅收录 lifecycle>=confirmed 的条目（draft 视为未确认，不入库）；
    ``include_unconfirmed=True`` 显式收录 draft 条目。每条 entry 携带 ``lifecycle_state``，供
    采纳 UI 默认隐藏未确认条目。functional_requirements 经 governed 双路径探测读取
    （package_v1 下在 .ratomizer/pipeline/，裸根拼会落空——B1 类寻址失守）。
    """
    import json as _json
    from requirement_schema import (
        LIFECYCLE_CONFIRMED, library_entry_from_requirement, lifecycle_rank, requirement_identity,
    )
    from requirements_analysis_rules import _read_functional_requirements_payload
    from review_state import read_verification_states

    output_path = output_path.expanduser().resolve()
    entries: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    total_skipped_unconfirmed = 0
    confirmed_floor = lifecycle_rank(LIFECYCLE_CONFIRMED)
    for project_dir in project_dirs:
        root = Path(project_dir).expanduser().resolve()
        payload = _read_functional_requirements_payload(root)
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list) or not items:
            sources.append({"project_dir": str(root), "imported": 0,
                            "reason": "functional_requirements.json 缺失"})
            continue
        # 生命周期来自 verification_states.jsonl（governed state 路径，for_write=False 不建目录）
        lifecycle_by_rid = {
            str(row.get("requirement_id") or "").strip(): str(row.get("lifecycle_state") or "draft")
            for row in read_verification_states(root).values()
        }
        project_name = str(payload.get("source") or root.name) if isinstance(payload, dict) else root.name
        created_at = ""
        prov = payload.get("provenance") if isinstance(payload, dict) else None
        if isinstance(prov, dict):
            created_at = str(prov.get("generated_at") or "")
        count = 0
        skipped_unconfirmed = 0
        for item in items or []:
            if not isinstance(item, dict):
                continue
            rid = requirement_identity(item)
            lifecycle_state = lifecycle_by_rid.get(rid) or "draft"
            # 质量门：默认仅收录 lifecycle>=confirmed；draft 不入库（视为未确认）
            if not include_unconfirmed and lifecycle_rank(lifecycle_state) < confirmed_floor:
                skipped_unconfirmed += 1
                continue
            entry = library_entry_from_requirement(
                item, project=project_name, doc_source=str(root), created_at=created_at)
            entry["lifecycle_state"] = lifecycle_state
            entries.append(entry)
            count += 1
        total_skipped_unconfirmed += skipped_unconfirmed
        sources.append({"project_dir": str(root), "project": project_name, "imported": count,
                        "skipped_unconfirmed": skipped_unconfirmed})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        for entry in entries:
            handle.write(_json.dumps(entry, ensure_ascii=False) + "\n")
    os.replace(tmp, output_path)
    return {
        "kind": "requirement_library",
        "library": str(output_path),
        "entries": len(entries),
        "skipped_unconfirmed": total_skipped_unconfirmed,
        "include_unconfirmed": bool(include_unconfirmed),
        "sources": sources,
    }
