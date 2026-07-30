from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
import os
import sys
import time
import uuid
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

import ai_extract
from agent_policy import AGENT_POLICY_VERSION
from assemble_spec import assemble
from atomize import run_atomizer_pipeline
from claim_artifacts import ClaimArtifactError
from engineering_composer import compose_engineering_requirements, write_engineering_requirements
from functional_synthesis import FUNCTIONAL_REQUIREMENTS, FUNCTIONAL_SYNTHESIS_VERSION, run_functional_synthesis
from export_requirements import export_requirements
from llm_pipeline import DEFAULT_DOMAIN_PACK_PATH, DEFAULT_PIPELINE_PATH, read_jsonl, run_review_pipeline
from requirement_kb.cli import default_kb_paths, package_root
from requirements_analysis import requirements_analysis_enrichment_enabled, run_requirements_analysis
from requirements_analysis_schema import normalize_ownership
from spec_export import export_spec


LOGGER = logging.getLogger("requirement_atomizer")
ASSEMBLED_JSON = "dlms_cosem_spec_requirements.json"
PROGRESS_PREFIX = "__RATOMIZER_PROGRESS__"
BLUE_BOOK_INDEX_ENV = "RATOMIZER_BLUE_BOOK_INDEX"
REQUIREMENTS_ANALYSIS_OUTPUTS = [
    "engineering_analysis.json",
    "hardware_items.md",
    "co_design_items.md",
    "compliance_items.json",
    "compliance_items.md",
    "software_requirements.xlsx",
]


def _leased_pipeline_stage(stage: str):
    """Keep targeted extraction out while a downstream stage consumes AI requirements."""
    def decorate(func):
        @wraps(func)
        def wrapped(out_dir: Path, *args, **kwargs):
            from omission_actions import extraction_operation_lock

            root = Path(out_dir).expanduser().resolve()
            with extraction_operation_lock(root, operation=f"stage:{stage}"):
                if "ai_requirements.jsonl" in STAGE_INPUTS.get(stage, []):
                    from api_server import final_ai_requirements_are_stale

                    if final_ai_requirements_are_stale(root):
                        raise RuntimeError(
                            "AI extraction belongs to an older parsed document; rerun ai-extract first"
                        )
                before = stage_input_files_fingerprint(root, stage)
                payload = func(root, *args, **kwargs)
                after = stage_input_files_fingerprint(root, stage)
                if before != after:
                    raise RuntimeError(f"{stage} inputs changed while the stage was running")
                if isinstance(payload, dict):
                    payload["_input_files_fingerprint"] = after
                return payload
        return wrapped
    return decorate


def resolve_bundled_path(path: Path | None) -> Path | None:
    """把前端预设送来的相对资源路径解析成可用的绝对路径。

    前端预设送相对名（KB 用 "knowledge_bases/…json"、domain pack 用 "domain_packs/dlms_cosem"），
    dev 下 cwd=仓库根能命中，但打包后后端 cwd=resources/backend 命中不到。这里：绝对路径或 cwd 下
    已存在的相对路径原样保留（兼容 CLI 习惯）；否则按 package_root() 解析（dev=仓库根 /
    Electron=resources/，捆绑资源真正所在）。
    """
    if path is None:
        return None
    path = Path(path)
    if path.is_absolute() or path.exists():
        return path
    return package_root() / path


def resolve_kb_paths(kb_paths: list[Path] | None) -> list[Path]:
    """把显式 --kb 路径列表逐个解析（见 resolve_bundled_path）；None 时用 default_kb_paths()。"""
    if kb_paths is None:
        return default_kb_paths()
    return [resolve_bundled_path(path) for path in kb_paths]


def run_pipeline_task(
    input_path: Path,
    out_dir: Path,
    *,
    skip_review: bool = False,
    llm_route: str | None = None,
    review_scope: str | None = None,
    llm_review_limit: int = 0,
    chunk_chars: int = 3500,
    kb_paths: list[Path] | None = None,
    domain_pack_dir: Path | None = None,
) -> dict[str, Any]:
    input_path = input_path.expanduser().resolve()
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    atomize_config = {
        "chunk_chars": chunk_chars,
        "kb_paths": [str(path) for path in resolve_kb_paths(kb_paths)],
        "domain_pack_dir": str(resolve_bundled_path(domain_pack_dir) or ""),
    }
    atomize_reused = stage_is_reusable(
        out_dir, "atomize", input_path=input_path, config=atomize_config)
    if atomize_reused:
        manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        manifest["resume_action"] = "skipped"
        update_run_manifest(out_dir, "atomize", "ok", outputs=STAGE_REQUIRED_OUTPUTS["atomize"],
                            action="skipped", input_path=input_path, config=atomize_config)
        emit_progress({"stage": "pipeline_stage", "step": "atomize", "status": "skipped", "percent": 100})
    else:
        update_run_manifest(out_dir, "atomize", "running")
        emit_progress({"stage": "pipeline_stage", "step": "atomize", "status": "running", "percent": 10})
        try:
            manifest = run_atomizer_pipeline(
                input_path,
                out_dir,
                chunk_chars=chunk_chars,
                kb_paths=resolve_kb_paths(kb_paths),
                domain_pack_dir=resolve_bundled_path(domain_pack_dir),
            )
        except Exception as exc:
            update_run_manifest(out_dir, "atomize", "failed", error=str(exc))
            raise
        update_run_manifest(out_dir, "atomize", "ok", outputs=STAGE_REQUIRED_OUTPUTS["atomize"],
                            action="ran", input_path=input_path, config=atomize_config)
        emit_progress({"stage": "pipeline_stage", "step": "atomize", "status": "ok", "percent": 100})

    # 审计 P1-d：用户 --kb 必须贯通到审查阶段——此前 atomize 按客户 KB 匹配、审查工具
    # 却落回默认 KB 复核（KB 双轨错配）。None（未显式传 kb）保持旧默认行为；显式传入时
    # 同一份解析结果进 run_review_pipeline 与阶段指纹，两侧文件集合严格一致。
    review_kb_paths = resolve_kb_paths(kb_paths) if kb_paths is not None else None
    review_config: dict[str, Any] = {
        # 审计 R2-H2：scope/limit 改变审查覆盖面，必须进阶段指纹——否则先 targeted 后
        # all、或先限量后全量时指纹不变，阶段被整体跳过。
        "review_scope": review_scope,
        "llm_review_limit": llm_review_limit,
    }
    if review_kb_paths is not None:
        review_config["kb_paths"] = [str(path) for path in review_kb_paths]
    # 审计 R2-H2/H3：--domain-pack 同时喂审查（review_policy 合并）与阶段指纹，与
    # atomize 同轨取解析后的包目录；未传时保持 review 默认捆绑包行为不变（显式 None
    # 会关掉 merge_review_policy 的默认包合并）。
    review_domain_pack_path: Path | None = None
    resolved_domain_pack_dir = resolve_bundled_path(domain_pack_dir)
    if resolved_domain_pack_dir is not None:
        review_config["domain_pack_dir"] = str(resolved_domain_pack_dir)
        review_domain_pack_path = resolved_domain_pack_dir / "pack.yaml"
    if skip_review:
        review = None
    elif atomize_reused and stage_is_reusable(out_dir, "llm-review", route=llm_route, config=review_config):
        review = skipped_stage_payload(out_dir, "llm-review")
        update_run_manifest(out_dir, "llm-review", "ok", route=llm_route, outputs=STAGE_REQUIRED_OUTPUTS["llm-review"], action="skipped", config=review_config)
        emit_progress({"stage": "pipeline_stage", "step": "llm-review", "status": "skipped", "percent": 100})
    else:
        update_run_manifest(out_dir, "llm-review", "running", config=review_config)
        emit_progress({"stage": "pipeline_stage", "step": "llm-review", "status": "running", "percent": 0})
        try:
            review = run_review_pipeline(
                out_dir,
                route=llm_route,
                scope=review_scope,
                llm_review_limit=llm_review_limit,
                progress_callback=emit_progress,
                kb_paths=review_kb_paths,
                domain_pack_path=review_domain_pack_path or DEFAULT_DOMAIN_PACK_PATH,
            )
        except Exception as exc:
            update_run_manifest(out_dir, "llm-review", "failed", error=str(exc), config=review_config)
            raise
        update_run_manifest(out_dir, "llm-review", "ok", route=llm_route, outputs=STAGE_REQUIRED_OUTPUTS["llm-review"], action="ran", config=review_config)
    return {
        "kind": "pipeline",
        "out_dir": str(out_dir),
        "input": str(input_path),
        "manifest": manifest,
        "review": review,
        "summary": _stage_summary(out_dir),
    }


def export_task(out_dir: Path, formats: list[str]) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    written = export_requirements(out_dir, formats=formats)
    return {
        "kind": "export",
        "out_dir": str(out_dir),
        "written": written,
        "summary": _stage_summary(out_dir),
    }


def resolve_blue_book_index(explicit: Path | None, out_dir: Path) -> Path | None:
    """蓝皮书索引路径：显式参数 > 环境变量 > 约定位置自动探测；都没有 → None（与无索引一致）。

    桌面「运行」链没有索引输入口（GUI 面板本期不做）——自动探测让桌面用户零配置享受 P2 行为
    富化：把编译好的 blue_book_index.json 放在输出目录（或 dev 仓库 out/bluebook/）即可。
    """
    if explicit is not None:
        return explicit
    env_value = os.environ.get(BLUE_BOOK_INDEX_ENV, "").strip()
    if env_value:
        return Path(env_value)
    candidates = (
        out_dir / "blue_book_index.json",
        out_dir / "bluebook" / "blue_book_index.json",
        package_root() / "out" / "bluebook" / "blue_book_index.json",  # dev 仓库编译位置
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


@_leased_pipeline_stage("assemble")
def assemble_task(
    out_dir: Path,
    *,
    formats: list[str] | None = None,
    enrich_route: str | None = None,
    blue_book_index_path: Path | None = None,
) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    reviews = out_dir / "llm_review_results.jsonl"
    reviews_path = reviews if reviews.exists() else None
    blue_book_index_path = resolve_blue_book_index(blue_book_index_path, out_dir)
    doc, breakdown = assemble(
        out_dir,
        reviews_path,
        source=out_dir.name,
        extracted_at=datetime.datetime.now().isoformat(timespec="seconds"),
        enrich_route=enrich_route,
        blue_book_index_path=blue_book_index_path,
    )
    target = out_dir / ASSEMBLED_JSON
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    written = [str(target)]
    if formats:
        written.extend(str(out_dir / name) for name in export_spec(out_dir, formats=formats, reviews_path=reviews_path))
    return {
        "kind": "assemble",
        "out_dir": str(out_dir),
        "count": len(doc.get("requirements", [])),
        "analysis": doc.get("analysis", {}),
        "breakdown": breakdown,
        # 出处追溯：本次装配用了哪个蓝皮书索引（None=未注入，行为与 P2 之前一致）
        "blue_book_index": str(blue_book_index_path) if blue_book_index_path else None,
        "written": written,
        "summary": _stage_summary(out_dir),
    }


@_leased_pipeline_stage("functional-synthesis")
def functional_synthesis_task(out_dir: Path, *, route: str = "stub") -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    return run_functional_synthesis(out_dir, route=route)


@_leased_pipeline_stage("compose")
def compose_task(out_dir: Path) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    model = compose_engineering_requirements(out_dir)
    written = write_engineering_requirements(out_dir, model)
    analysis = model.get("analysis", {})
    return {
        "kind": "compose",
        "out_dir": str(out_dir),
        "count": int(analysis.get("requirement_functions") or len(model.get("requirement_functions", []))),
        "analysis": analysis,
        "written": written,
        "summary": _stage_summary(out_dir),
    }


@_leased_pipeline_stage("requirements-analysis")
def requirements_analysis_task(
    out_dir: Path,
    *,
    route: str = "stub",
    template_path: Path | None = None,
) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    analysis = run_requirements_analysis(
        out_dir,
        route=route,
        template_path=resolve_template_path(template_path),
        progress_callback=emit_progress,  # 富化逐条上报（GUI n/total，并发度走 RATOMIZER_LLM_CONCURRENCY）
    )
    # 只上报真实存在的产物（此前无条件列出 4 个文件，失败时载荷撒谎）
    names = analysis.get("written") or REQUIREMENTS_ANALYSIS_OUTPUTS
    written = [str(out_dir / name) for name in names if (out_dir / name).exists()]
    return {
        "kind": "requirements_analysis",
        "out_dir": str(out_dir),
        "analysis": analysis,
        "written": written,
        "summary": _stage_summary(out_dir),
    }


def resolve_template_path(template_path: Path | None) -> Path | None:
    if template_path is None:
        return None
    path = Path(template_path).expanduser()
    if not path.is_absolute() and not path.exists():
        path = resolve_bundled_path(path) or path
    if not path.exists():
        raise FileNotFoundError(f"Template file does not exist: {path}")
    return path.resolve()


@_leased_pipeline_stage("clarification-report")
def clarification_report_task(out_dir: Path) -> dict[str, Any]:
    """澄清问题清单 + 就绪判定（确定性零 LLM）：全链疑问信号聚合成评审会可用的问客户清单。"""
    from clarification_report import run_report

    out_dir = out_dir.expanduser().resolve()
    report = run_report(out_dir)
    return {
        "kind": "clarification_report",
        "out_dir": str(out_dir),
        "questions": report["questions"],
        "by_category": report["by_category"],
        "readiness": report["readiness"],
        "written": [str(out_dir / name) for name in report.get("written") or []
                    if (out_dir / name).exists()],
        "summary": _stage_summary(out_dir),
    }


def import_clarification_workbook_task(
    out_dir: Path,
    workbook_path: Path,
    *,
    actor: str = "desktop-import",
) -> dict[str, Any]:
    """Import customer answers and internal acknowledgements from one report workbook."""
    from openpyxl import load_workbook
    from clarification_report import import_answers, import_internal_checks, run_report

    out_dir = out_dir.expanduser().resolve()
    workbook_path = workbook_path.expanduser().resolve()
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        has_internal_sheet = "必答-内部核对" in workbook.sheetnames
        internal_headers = (
            [str(cell.value or "").strip() for cell in workbook["必答-内部核对"][1]]
            if has_internal_sheet else []
        )
    finally:
        workbook.close()
    if not has_internal_sheet:
        raise ValueError("工作簿缺少「必答-内部核对」sheet，请重新生成澄清清单")
    required = {"澄清ID", "证据指纹", "阻塞级", "模块", "信号", "来源需求", "核对人", "备注"}
    missing = sorted(required.difference(internal_headers))
    if not any(value.startswith("新处置") for value in internal_headers):
        missing.append("新处置(确认无误/确认有问题/暂缓)")
    if missing:
        raise ValueError(f"「必答-内部核对」sheet 缺少列：{', '.join(missing)}")
    answers = import_answers(out_dir, workbook_path)
    checks = import_internal_checks(out_dir, workbook_path, actor=actor)
    report = run_report(out_dir)
    return {
        "kind": "clarification_answers",
        "out_dir": str(out_dir),
        "imported": int(answers.get("imported") or 0),
        "internal_imported": int(checks.get("imported") or 0),
        "readiness": report.get("readiness") or {},
        "questions": int(report.get("questions") or 0),
        "written": list(dict.fromkeys([
            *(str(value) for value in (answers.get("written") or [])),
            *(str(value) for value in (checks.get("written") or [])),
            *(str(value) for value in (report.get("written") or [])),
        ])),
    }


@_leased_pipeline_stage("template-write")
def template_write_task(out_dir: Path, template_path: Path) -> dict[str, Any]:
    """成文：analyze 结果按公司标准化需求列表 V2.3.x 格式追加进对应模块 sheet（确定性零 LLM）。"""
    from template_writer import run_writer

    out_dir = out_dir.expanduser().resolve()
    report = run_writer(out_dir, template_path.expanduser().resolve())
    return {
        "kind": "template_write",
        "out_dir": str(out_dir),
        "report": report,
        "written": [str(out_dir / name) for name in report.get("written") or []
                    if (out_dir / name).exists()],
        "summary": _stage_summary(out_dir),
    }


def ai_extract_task(out_dir: Path, *, route: str | None, limit_sections: int | None = None,
                    sample_ratio: float | None = None) -> dict[str, Any]:
    """AI 主抽 + 双引擎合并：AI 行为需求 + 确定性结构需求 → merged_spec.xlsx/json。

    试抽模式（「测试运行」用）：sample_ratio 按比例抽样（0.2=全文 1/5，随文档自适应）；
    limit_sections 固定 N 章（CLI 用）。"""
    out_dir = out_dir.expanduser().resolve()
    result = ai_extract.run_ai_extract(out_dir, route=route, merge_deterministic=True,
                                       progress_callback=emit_progress,
                                       limit_sections=limit_sections,
                                       sample_ratio=sample_ratio)
    return {
        "kind": "ai_extract",
        "out_dir": str(out_dir),
        "route": result.get("route"),
        "count": result.get("requirements", 0),
        "merged": result.get("merged", {}),
        "sections": result.get("sections", 0),
        "failed_sections": result.get("failed_sections", 0),
        "code_drift_flagged": result.get("code_drift_flagged", 0),
        "int_drift_flagged": result.get("int_drift_flagged", 0),
        "note": result.get("note", ""),
        "quality": result.get("quality", {}),
        "sampled": result.get("sampled"),
        "consistency": result.get("consistency", {}),
        "claim_shadow": result.get("claim_shadow", {}),
        "written": [str(out_dir / name) for name in result.get("written", [])],
        "summary": _stage_summary(out_dir),
    }


RUN_MANIFEST = "run_manifest.json"
STAGES_DIR = "_stages"
_MANIFEST_LOCKS: dict[Path, RLock] = {}
_MANIFEST_LOCKS_GUARD = RLock()
_MANIFEST_LOCK_TIMEOUT_S = 10.0
_MANIFEST_LOCK_STALE_AFTER_S = 300.0
_REPLACE_ATTEMPTS = 5
_REPLACE_RETRY_DELAY_S = 0.02

# 阶段名 == 子命令名（manifest 键与 CLI 一致，GUI 单步按钮与 chain 写同一本账）
CHAIN_ORDER = ["ai-extract", "functional-synthesis", "assemble", "requirements-analysis", "template-write",
               "clarification-report", "compose", "export-annotation-html"]
STAGE_INPUTS: dict[str, list[str]] = {
    "atomize": [],
    "llm-review": ["atomic_requirements.jsonl", "llm_tasks.jsonl"],
    "ai-extract": ["blocks.jsonl", "table_items.jsonl", "llm_review_results.jsonl", "review_states.jsonl",
                   "ai_supplements.jsonl"],
    "assemble": ["table_items.jsonl", "atomic_requirements.jsonl", "llm_review_results.jsonl",
                 "ai_supplements.jsonl"],
    "functional-synthesis": ["ai_requirements.jsonl", "ai_requirements.meta.json", "blocks.jsonl",
                             "ai_review_states.jsonl", "ai_supplements.jsonl"],
    "requirements-analysis": [FUNCTIONAL_REQUIREMENTS, "ai_requirements.jsonl", "ai_review_states.jsonl",
                              "clarification_answers.jsonl", "blocks.jsonl", "term_map.json",
                              "ai_requirements.meta.json", "ai_supplements.jsonl"],
    "template-write": ["engineering_analysis.json", "ai_requirements.meta.json",
                       "ai_supplements.jsonl"],
    "clarification-report": [FUNCTIONAL_REQUIREMENTS, "ai_requirements.jsonl", "engineering_analysis.json",
                             "consistency_report.json", "blocks.jsonl", "ai_review_states.jsonl",
                             "clarification_answers.jsonl", "clarification_check_states.jsonl",
                             "omission_states.jsonl", "ai_requirements.meta.json", "ai_supplements.jsonl",
                             "claim_effective_ledger.jsonl", "claim_effective.meta.json",
                             "claim_queue_proposals.jsonl", "claim_effective_health.json"],
    "compose": ["atomic_requirements.jsonl", "table_items.jsonl", "ai_requirements.meta.json",
                "ai_supplements.jsonl"],
    "export-annotation-html": ["blocks.jsonl", "table_items.jsonl", "ai_requirements.jsonl",
                               "engineering_analysis.json", "ai_review_states.jsonl",
                               "annotation_translations.json", "ai_requirements.meta.json",
                               "ai_supplements.jsonl", "claim_catalog.jsonl",
                               "claim_catalog.meta.json", "claim_coverage_groups.jsonl",
                               "claim_ledger.jsonl", "claim_shadow_metrics.json",
                               "claim_verifier_attempts.jsonl", "claim_generation.meta.json",
                               "claim_effective_ledger.jsonl", "claim_effective.meta.json",
                               "claim_queue_proposals.jsonl", "claim_structural_overrides.jsonl",
                               ".claim_publication.journal.json",
                               ".claim_effective_publication.journal.json"],
}


STAGE_REQUIRED_OUTPUTS: dict[str, list[str]] = {
    "atomize": [
        "manifest.json",
        "blocks.jsonl",
        "chunks.jsonl",
        "table_items.jsonl",
        "atomic_requirements.jsonl",
        "llm_tasks.jsonl",
        "quality_report.json",
        "summary.md",
    ],
    "llm-review": ["llm_review_results.jsonl", "review_states.jsonl"],
    "ai-extract": [
        "ai_requirements.jsonl",
        "ai_requirements.meta.json",
        "compliance_requirements.json",
        "merged_spec_requirements.json",
        "claim_catalog.jsonl",
        "claim_catalog.meta.json",
        "claim_coverage_groups.jsonl",
        "claim_ledger.jsonl",
        "claim_shadow_metrics.json",
        "claim_verifier_attempts.jsonl",
        "claim_generation.meta.json",
    ],
    "functional-synthesis": [FUNCTIONAL_REQUIREMENTS],
    "assemble": [ASSEMBLED_JSON],
    "requirements-analysis": REQUIREMENTS_ANALYSIS_OUTPUTS,
    "template-write": ["软件需求列表-成文.xlsx", "template_writer_report.json"],
    "clarification-report": ["clarification_questions.md", "clarification_questions.xlsx", "clarification_report.json"],
    "compose": ["engineering_requirements/engineering_requirements.json"],
    "export-annotation-html": ["document_annotation.html"],
}


STAGE_IMPLEMENTATION_REVISIONS = {
    # v7：render_table_text 取消 20 行截断（大参数表 21 行起内容进不了管线,STO 实证）
    # v6：表格块扁平文本取消 [:5000] 截断（初始提交遗留）——大参数表 88% 内容此前
    # 进不了抽取管线（STO/俄标实证）；blocks 内容变化,docx 输入须重解析
    # v5：PDF 清单段合并（名词式清单项并整段，微块可锚定）——块结构变化，PDF 输入须重解析
    "atomize": "v7",
    "ai-extract": "v4",
    "assemble": "v2",
    "functional-synthesis": "v3",
    # v6：hardware_dependency 落交付物渲染（xlsx 说明列/co_design_items.md）——
    # 纯渲染变更不动 analyze 缓存版本，靠 impl 戳让阶段重跑重渲染（审计 P1-b）
    "requirements-analysis": "v6",
    # v5：完整性元数据进入阶段输入，旧缓存不得缺 incomplete_inputs。
    "template-write": "v5",
    "clarification-report": "v6",
    # v1.5：compose 首次绑定完整性元数据，显式升级阶段实现戳。
    "compose": "v2",
}

_STAGE_BASE_PRODUCERS = {
    "atomize": "atomize",
    "assemble": "assemble_spec/v1",
    "template-write": "template_writer/v1",
    "clarification-report": "clarification/v7-claim-ledger-info",
    "compose": "engineering_composer/v1",
    # v13-claim-focus：每个已提交 claim 经 claim_focus 确定性映射；文本/清单输出精确
    # span，表格输出行几何与 claim 卡。optimized/pdf_original 嵌入同一状态集合。
    "export-annotation-html": "doc_annotation_export/v13-claim-focus",
    "run": "pipeline/v1",
    "llm-review": "review/v1",
}


def stage_producer(stage: str, *, out_dir: Path | None = None,
                   kb_paths: list[Any] | None = None) -> str:
    """阶段 → 生产者版本戳（产物血统：今天拿 v9 数据当新结果看的事故，靠它绝迹）。

    llm-review 额外拼入审查代码版本（prompt/cache/tools，审计 R2-H2）与工具证据
    内容指纹（KB/blocks/原子需求/蓝皮书索引，审计 P1-d）——审查代码升级或实际
    读取的证据变了，旧审查产物不得继续复用；out_dir 缺席时保持基础戳+代码版本
    （无目录语境兼容）。"""
    producer = _STAGE_BASE_PRODUCERS.get(stage, stage)
    # Phase 0 reserves policy lineage for future agent stages without invalidating any
    # current pipeline cache. There is intentionally no agent stage in CHAIN_ORDER yet.
    if stage.startswith("agent-"):
        producer = f"{producer}+{AGENT_POLICY_VERSION}"
    try:
        if stage == "ai-extract":
            # 版本戳必须覆盖全部影响产物的代码层；否则 guards/verify 升级后
            # chain 续跑仍可能复用旧结果。
            from ai_extract import (
                AI_EXTRACT_PROMPT_VERSION,
                AI_NORMATIVE_FRAMING_VERSION,
                AI_VERIFY_PROMPT_VERSION,
                EXTRACT_GUARDS_VERSION,
            )
            from merged_consistency import MERGED_CONSISTENCY_VERSION
            producer = (f"{AI_EXTRACT_PROMPT_VERSION}+{EXTRACT_GUARDS_VERSION}"
                        f"+{AI_VERIFY_PROMPT_VERSION}+{AI_NORMATIVE_FRAMING_VERSION}"
                        f"+{MERGED_CONSISTENCY_VERSION}")
        elif stage == "atomize":
            # PDF text repair changes blocks consumed by every downstream stage. Include both
            # the algorithm version and the bundled vocabulary content in the producer so a
            # repaired parser cannot silently reuse an old atomize run. Source alignment is a
            # separate parser-output contract used by the claim catalog conservation audit.
            from parsers.pdf_parser import PDF_TEXT_REPAIR_VERSION, text_repair_vocabulary_fingerprint
            from source_spans import (
                SOURCE_ALIGNMENT_VERSION,
                SOURCE_TRANSFORMATION_POLICY_VERSION,
                SOURCE_TRANSFORMATION_RULESET_VERSION,
            )
            producer = (
                f"{producer}+{PDF_TEXT_REPAIR_VERSION}"
                f"+repair-vocab-{text_repair_vocabulary_fingerprint()}"
                f"+{SOURCE_ALIGNMENT_VERSION}"
                f"+{SOURCE_TRANSFORMATION_POLICY_VERSION}"
                f"+{SOURCE_TRANSFORMATION_RULESET_VERSION}"
            )
        elif stage == "llm-review":
            # 代码版本必须进戳（审计 R2-H2）：prompt/cache/tools 任一 bump 后旧阶段
            # 产物不得复用——此前 llm-review 是唯一不拼代码版本的阶段。
            from llm_pipeline import LLM_REVIEW_CACHE_VERSION, PROMPT_VERSION
            from review_tools import REVIEW_TOOLS_VERSION
            producer = (f"{producer}+{PROMPT_VERSION}+{LLM_REVIEW_CACHE_VERSION}"
                        f"+{REVIEW_TOOLS_VERSION}")
            if out_dir is not None:
                from review_tools import evidence_fingerprint
                producer = f"{producer}+evidence-{evidence_fingerprint(out_dir, kb_paths)}"
        elif stage == "assemble":
            # assemble 会运行 spec_enrich；富化 prompt/护栏升级必须让阶段续跑失效，
            # 否则旧 run_manifest 会在富化缓存检查之前跳过整个阶段。
            from spec_enrich import ENRICH_GUARDS_VERSION, ENRICH_PROMPT_VERSION
            producer = (f"{producer}+{ENRICH_PROMPT_VERSION}"
                        f"+{ENRICH_GUARDS_VERSION}")
        elif stage == "requirements-analysis":
            from requirements_analysis import ANALYZE_PROMPT_VERSION, UNFOUNDED_RULE_VERSION
            producer = f"{ANALYZE_PROMPT_VERSION}+{UNFOUNDED_RULE_VERSION}"
        elif stage == "functional-synthesis":
            producer = FUNCTIONAL_SYNTHESIS_VERSION
        elif stage == "export-annotation-html":
            from claim_focus import CLAIM_FOCUS_ADAPTER_VERSION
            from doc_annotation_export import (ANNOTATION_TRANSLATION_GUARDS_VERSION,
                                                ANNOTATION_TRANSLATION_STRATEGY_VERSION,
                                                CLAIM_ANNOTATION_VERSION)
            from doc_facsimile import DOC_FACSIMILE_VERSION
            # docx/xlsx 影印支路（WP-A）进戳：转换层版本变化 → 旧影印产物不得复用
            producer = (f"{producer}+{CLAIM_ANNOTATION_VERSION}"
                        f"+{CLAIM_FOCUS_ADAPTER_VERSION}"
                        f"+{ANNOTATION_TRANSLATION_STRATEGY_VERSION}"
                        f"+{ANNOTATION_TRANSLATION_GUARDS_VERSION}+{DOC_FACSIMILE_VERSION}")
        if stage in {
            "ai-extract", "functional-synthesis", "assemble", "requirements-analysis", "template-write",
            "clarification-report", "compose", "export-annotation-html",
        }:
            from omission_actions import AI_SUPPLEMENT_VERSION
            producer = f"{producer}+{AI_SUPPLEMENT_VERSION}"
    except Exception:  # pragma: no cover - 版本戳失败不阻断任务
        pass
    revision = STAGE_IMPLEMENTATION_REVISIONS.get(stage)
    return f"{producer}+impl-{revision}" if revision else producer


def read_run_manifest(out_dir: Path) -> dict[str, Any]:
    path = Path(out_dir).expanduser().resolve() / RUN_MANIFEST
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (json.JSONDecodeError, OSError):
        data = {}
    return data if isinstance(data, dict) else {}


def _relative_outputs(out_dir: Path, outputs: list[str | Path]) -> list[str]:
    root = Path(out_dir).expanduser().resolve()
    result: list[str] = []
    for item in outputs:
        path = Path(item)
        if path.is_absolute():
            try:
                path = path.resolve().relative_to(root)
            except ValueError:
                pass
        result.append(path.as_posix())
    return result


def _stage_outputs(stage: str, entry: dict[str, Any] | None = None) -> list[str]:
    outputs = (entry or {}).get("outputs") if isinstance(entry, dict) else None
    if isinstance(outputs, list) and outputs:
        return [str(item) for item in outputs]
    return list(STAGE_REQUIRED_OUTPUTS.get(stage, []))


def _outputs_exist(out_dir: Path, outputs: list[str]) -> bool:
    if not outputs:
        return False
    root = Path(out_dir).expanduser().resolve()
    for name in outputs:
        path = root / name
        if not path.exists() or path.is_dir():
            return False
        try:
            if path.stat().st_size <= 0 and name not in {
                "ai_requirements.jsonl",
                "claim_catalog.jsonl",
                "claim_coverage_groups.jsonl",
                "claim_ledger.jsonl",
                "claim_effective_ledger.jsonl",
            }:
                return False
        except OSError:
            return False
    return True


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_STAGE_MUTABLE_INPUTS = {
    "export-annotation-html": {"annotation_translations.json"},
}

_CLAIM_STAGE_OUTPUTS = {
    "claim_catalog.jsonl",
    "claim_catalog.meta.json",
    "claim_coverage_groups.jsonl",
    "claim_ledger.jsonl",
    "claim_effective_ledger.jsonl",
    "claim_shadow_metrics.json",
    "claim_verifier_attempts.jsonl",
    "claim_generation.meta.json",
    "claim_effective.meta.json",
}

_CLAIM_EFFECTIVE_RUNTIME_OUTPUTS = {
    "claim_effective_ledger.jsonl",
    "claim_effective.meta.json",
    "claim_review_events.jsonl",
    "claim_queue_proposals.jsonl",
    "claim_effective_health.json",
}


def stage_input_files_fingerprint(out_dir: Path, stage: str) -> str:
    """Hash immutable stage inputs for the duration of a downstream read lease."""
    root = Path(out_dir).expanduser().resolve()
    ignored = _STAGE_MUTABLE_INPUTS.get(stage, set())
    payload = [
        {
            "path": name,
            "sha256": _hash_file(root / name) if (root / name).is_file() else None,
        }
        for name in STAGE_INPUTS.get(stage, [])
        if name not in ignored
    ]
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _resource_content_fingerprint(path: Path | None) -> str | None:
    """Hash a KB file or a deterministic directory tree for atomize reuse checks."""
    if path is None:
        return None
    path = Path(path).expanduser().resolve()
    if path.is_file():
        return _hash_file(path)
    if not path.is_dir():
        return None
    entries = []
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        entries.append({
            "path": str(child.relative_to(path)).replace("\\", "/"),
            "sha256": _hash_file(child),
        })
    return hashlib.sha256(json.dumps(
        entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def stage_input_fingerprint(out_dir: Path, stage: str, *, route: str | None = None,
                            template_path: Path | None = None,
                            input_path: Path | None = None,
                            config: dict[str, Any] | None = None) -> str:
    root = Path(out_dir).expanduser().resolve()
    inputs: list[dict[str, Any]] = []
    for name in STAGE_INPUTS.get(stage, []):
        path = root / name
        inputs.append({
            "path": name,
            "sha256": _hash_file(path) if path.exists() and path.is_file() else None,
        })
    template = Path(template_path).expanduser().resolve() if template_path else None
    payload = {
        "stage": stage,
        "producer": stage_producer(
            stage,
            out_dir=root,
            kb_paths=(config or {}).get("kb_paths") if stage == "llm-review" else None,
        ),
        "route": route or "",
        "inputs": inputs,
        "atomize_resources": (
            {
                "knowledge_bases": [
                    {
                        "path": str(Path(path).expanduser().resolve()),
                        "sha256": _resource_content_fingerprint(Path(path)),
                    }
                    for path in (config or {}).get("kb_paths") or []
                ],
                "domain_pack": (
                    {
                        "path": str(Path((config or {}).get("domain_pack_dir")).expanduser().resolve()),
                        "sha256": _resource_content_fingerprint(
                            Path((config or {}).get("domain_pack_dir"))
                        ),
                    }
                    if (config or {}).get("domain_pack_dir") else None
                ),
            }
            if stage == "atomize" else None
        ),
        # 审计 R2-H2：llm-review 合并 domain-pack 的 review_policy，包内容变必须令阶段
        # 失效（仅当实际传入 domain pack 时；atomize 的包内容走上方 atomize_resources）。
        "domain_pack": (
            {
                "path": str(Path((config or {}).get("domain_pack_dir")).expanduser().resolve()),
                "sha256": _resource_content_fingerprint(
                    Path((config or {}).get("domain_pack_dir"))
                ),
            }
            if stage == "llm-review" and (config or {}).get("domain_pack_dir") else None
        ),
        "template": ({"path": str(template), "sha256": _hash_file(template)}
                     if template and template.exists() and template.is_file() else None),
        "source_input": ({"path": str(Path(input_path).expanduser().resolve()),
                          "sha256": _hash_file(Path(input_path).expanduser().resolve())}
                         if input_path and Path(input_path).expanduser().resolve().is_file() else None),
        "config": config or {},
        "llm_pipeline": ({"path": str(DEFAULT_PIPELINE_PATH), "sha256": _hash_file(DEFAULT_PIPELINE_PATH)}
                         if stage in {"llm-review", "ai-extract", "functional-synthesis", "assemble", "requirements-analysis"}
                         and DEFAULT_PIPELINE_PATH.exists() else None),
        "llm": {key: os.environ.get(key, "") for key in (
            "RATOMIZER_LLM_BASE_URL", "RATOMIZER_LLM_MODEL", "RATOMIZER_LLM_MAX_TOKENS",
            "RATOMIZER_LLM_TEMPERATURE", "RATOMIZER_AI_UNIT_MODE", "RATOMIZER_AI_SELFCHECK",
            "RATOMIZER_AI_SELFCHECK_ROUNDS",
            # 二遍复核开关/轮数改变产物 → 指纹必须失效（专家审核 0715:缺席使复核
            # 变更后 chain 续跑直接跳过 ai-extract,新设置静默零生效）
            "RATOMIZER_AI_VERIFY", "RATOMIZER_AI_VERIFY_ROUNDS",
            # 合批条数改变 prompt 形状 → 产物可能不同 → 指纹必须失效（0714 批次二）
            "RATOMIZER_ANALYZE_BATCH", "RATOMIZER_ENRICH_BATCH",
        )},
        "requirements_analysis_enrich": (
            requirements_analysis_enrichment_enabled()
            if stage == "requirements-analysis" else None
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _stage_manifest_path(out_dir: Path, stage: str) -> Path:
    return Path(out_dir).expanduser().resolve() / STAGES_DIR / stage / "stage_manifest.json"


@contextmanager
def _run_manifest_lock(
    out_dir: Path,
    *,
    timeout_s: float = _MANIFEST_LOCK_TIMEOUT_S,
    stale_after_s: float = _MANIFEST_LOCK_STALE_AFTER_S,
) -> Iterator[None]:
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    with _manifest_process_lock_for(root):
        lock_path = root / "run_manifest.lock"
        deadline = time.monotonic() + timeout_s
        fd: int | None = None
        while fd is None:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if _remove_stale_manifest_lock(lock_path, stale_after_s):
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for run manifest lock: {lock_path}")
                time.sleep(0.01)
        try:
            os.write(fd, str(os.getpid()).encode("ascii"))
            yield
        finally:
            os.close(fd)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


def _manifest_process_lock_for(out_dir: Path) -> RLock:
    with _MANIFEST_LOCKS_GUARD:
        return _MANIFEST_LOCKS.setdefault(out_dir, RLock())


def _remove_stale_manifest_lock(lock_path: Path, stale_after_s: float) -> bool:
    if stale_after_s < 0:
        return False
    try:
        age_s = time.time() - lock_path.stat().st_mtime
    except FileNotFoundError:
        return True
    if age_s < stale_after_s:
        return False
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return True
    return True


def _replace_with_retry(source: Path, target: Path) -> None:
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt + 1 >= _REPLACE_ATTEMPTS:
                raise
            time.sleep(_REPLACE_RETRY_DELAY_S)


def _atomic_write_json(path: Path, text: str) -> None:
    """原子写：临时文件 + os.replace。崩溃中途不会留下半截 JSON（旧 write_text 会，
    read_run_manifest 吞 JSONDecodeError 后静默丢弃所有阶段记录 → 强制全量重跑）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _write_stage_manifest(out_dir: Path, stage: str, entry: dict[str, Any]) -> None:
    path = _stage_manifest_path(out_dir, stage)
    _atomic_write_json(path, json.dumps({"stage": stage, **entry}, ensure_ascii=False, indent=2) + "\n")


def _stage_is_reusable(out_dir: Path, stage: str, *,
                       route: str | None = None,
                       input_path: Path | None = None,
                       template_path: Path | None = None,
                       config: dict[str, Any] | None = None,
                       require_claim_generation: bool = True) -> bool:
    data = read_run_manifest(out_dir)
    stages = data.get("stages") if isinstance(data.get("stages"), dict) else {}
    entry = stages.get(stage) if isinstance(stages.get(stage), dict) else None
    # 出处方向性守卫（评审修正 2026-07-09）：请求真 LLM 时，复用 stub/来历不明的产物有害
    # （空行为需求被标"已完成"）——必须有带 route 的台账条目佐证；请求 stub/确定性阶段时，
    # 复用任何现成产物无害（最坏反而复用了更好的），保留遗留目录续跑价值（文件存在即可）。
    if not entry:
        return False
    if route == "openai_compatible" and entry.get("route") != route:
        return False
    if entry:
        if entry.get("status") != "ok":
            return False
        if entry.get("producer") and entry.get("producer") != stage_producer(
                stage, out_dir=out_dir, kb_paths=(config or {}).get("kb_paths")):
            return False
        recorded_fingerprint = str(entry.get("input_fingerprint") or "")
        recorded_route = str(entry.get("route") or "")
        fingerprint_route = recorded_route if route == "stub" and recorded_route == "openai_compatible" else route
        current_fingerprint = stage_input_fingerprint(
            out_dir, stage, route=fingerprint_route, template_path=template_path,
            input_path=input_path, config=config)
        if recorded_fingerprint != current_fingerprint:
            return False
        recorded_files = str(entry.get("input_files_fingerprint") or "")
        if recorded_files and recorded_files != stage_input_files_fingerprint(out_dir, stage):
            return False
    outputs = _stage_outputs(stage, entry)
    if stage == "ai-extract":
        # Runtime effective sidecars are independently recoverable. Legacy
        # manifests may list them, but their absence/staleness never reruns extraction.
        outputs = [
            name
            for name in outputs
            if Path(name).name not in _CLAIM_EFFECTIVE_RUNTIME_OUTPUTS
        ]
    if stage == "ai-extract" and not require_claim_generation:
        outputs = [name for name in outputs if Path(name).name not in _CLAIM_STAGE_OUTPUTS]
    if not _outputs_exist(out_dir, outputs):
        return False
    if stage == "ai-extract" and require_claim_generation:
        try:
            from claim_artifacts import (
                committed_base_versions_are_current,
                load_committed_claim_base,
            )

            snapshot = load_committed_claim_base(out_dir)
            if not committed_base_versions_are_current(snapshot):
                return False
            from ai_extract import (
                resolve_claim_shadow_verify,
                resolve_claim_shadow_verify_max_calls,
                resolve_claim_shadow_verify_max_total_tokens,
            )

            shadow_meta = dict(snapshot.get("generation_meta", {}).get("shadow_meta") or {})
            expected_verifier = bool(
                route not in {None, "stub"}
                and resolve_claim_shadow_verify()
                and resolve_claim_shadow_verify_max_calls() > 0
                and resolve_claim_shadow_verify_max_total_tokens() > 0
            )
            if shadow_meta.get("semantic_verifier_enabled") is not expected_verifier:
                return False
        except ClaimArtifactError:
            return False
    if stage == "atomize" and input_path is not None:
        try:
            manifest = json.loads((Path(out_dir) / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if Path(str(manifest.get("input") or "")).expanduser().resolve() != Path(input_path).expanduser().resolve():
            return False
    return True


def stage_is_reusable(out_dir: Path, stage: str, *,
                      route: str | None = None,
                      input_path: Path | None = None,
                      template_path: Path | None = None,
                      config: dict[str, Any] | None = None) -> bool:
    return _stage_is_reusable(
        out_dir,
        stage,
        route=route,
        input_path=input_path,
        template_path=template_path,
        config=config,
        require_claim_generation=True,
    )


def ai_requirements_are_reusable(
    out_dir: Path,
    *,
    route: str | None,
    config: dict[str, Any] | None = None,
) -> bool:
    """Validate the extraction layer while deliberately ignoring claim artifacts."""
    if not _stage_is_reusable(
        out_dir,
        "ai-extract",
        route=route,
        config=config,
        require_claim_generation=False,
    ):
        return False
    root = Path(out_dir).expanduser().resolve()
    requirements_path = root / "ai_requirements.jsonl"
    metadata_path = root / "ai_requirements.meta.json"
    if not requirements_path.is_file() or not metadata_path.is_file():
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        from ai_extract import extraction_input_fingerprint

        return (
            isinstance(metadata, dict)
            and metadata.get("schema") == "ai-requirements-final/v1"
            and str(metadata.get("input_fingerprint") or "")
            == extraction_input_fingerprint(root)
            and int(metadata.get("failed_sections") or 0) == 0
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return False


# 链内跳过各阶段 summary（0714 批次二 S7）：8 个阶段各算一遍 build_output_summary
# （三份 jsonl 全量读+遍历）然后被 chain 逐个 pop 丢弃,链尾统一算一份即可。
# chain 单线程顺序跑,module 级布尔够用（desktop 任务本就每命令独立进程）。
_CHAIN_ACTIVE = False


def _stage_summary(out_dir: Path) -> dict[str, Any]:
    if _CHAIN_ACTIVE:
        return {}
    return build_output_summary(out_dir)


def _claim_effective_summary(out_dir: Path) -> dict[str, Any]:
    try:
        from claim_views import build_claim_view

        view = build_claim_view(out_dir, "metrics")
        effective_metrics = dict(view.get("effective_metrics") or {})
        return {
            "document_ready": view.get("document_ready"),
            "effective_fresh": bool(view.get("effective_fresh")),
            "open_claim_count": effective_metrics.get("uncertain_count"),
        }
    except Exception as exc:
        return {
            "document_ready": None,
            "effective_fresh": False,
            "open_claim_count": None,
            "effective_error": str(exc)[:300],
        }


def _claim_component_manifest(out_dir: Path) -> dict[str, Any]:
    try:
        from claim_artifacts import load_committed_effective_snapshot_readonly

        snapshot = load_committed_effective_snapshot_readonly(out_dir)
        generation = dict(snapshot["generation_meta"])
        shadow_meta = dict(generation.get("shadow_meta") or {})
        effective = dict(snapshot["effective_meta"])
        return {
            "base_generation_id": effective.get("base_generation_id"),
            "document_effective_revision": effective.get(
                "document_effective_revision"
            ),
            "event_prefix_sha256": effective.get("event_prefix_sha256"),
            "last_event_seq": effective.get("last_event_seq"),
            "catalog": dict(snapshot.get("catalog_meta") or {}).get(
                "catalog_version"
            ),
            "coverage": dict(shadow_meta.get("versions") or {}).get(
                "coverage_validator"
            ),
            "effective": effective.get("effective_ledger_schema"),
            "bridge": effective.get("bridge_version"),
            "reducer": effective.get("reducer_version"),
            "queue": effective.get("queue_version"),
            "versions": dict(effective.get("versions") or {}),
        }
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)[:300]}


def skipped_stage_payload(out_dir: Path, stage: str) -> dict[str, Any]:
    data = read_run_manifest(out_dir)
    stages = data.get("stages") if isinstance(data.get("stages"), dict) else {}
    entry = stages.get(stage) if isinstance(stages.get(stage), dict) else {}
    outputs = _stage_outputs(stage, entry)
    root = Path(out_dir).expanduser().resolve()
    payload = {
        "kind": stage.replace("-", "_"),
        "out_dir": str(root),
        "resume_action": "skipped",
        "written": [str(root / name) for name in outputs],
    }
    if stage == "ai-extract":
        try:
            from claim_artifacts import load_committed_shadow

            snapshot = load_committed_shadow(root)
            shadow_meta = dict(snapshot.get("generation_meta", {}).get("shadow_meta") or {})
            payload["claim_shadow"] = {
                "status": "published",
                "accounting_status": shadow_meta.get("accounting_status"),
                "resolution_status": shadow_meta.get("resolution_status"),
                "termination_reason": shadow_meta.get("termination_reason"),
                "metrics": snapshot.get("metrics") or {},
                **_claim_effective_summary(root),
            }
        except Exception as exc:
            payload["claim_shadow"] = {"status": "stale", "error": str(exc)[:300]}
    return payload


def update_run_manifest(out_dir: Path, stage: str, status: str, *,
                        error: str | None = None, route: str | None = None,
                        outputs: list[str | Path] | None = None,
                        action: str | None = None,
                        input_fingerprint: str | None = None,
                        input_files_fingerprint: str | None = None,
                        template_path: Path | None = None,
                        input_path: Path | None = None,
                        config: dict[str, Any] | None = None) -> None:
    """run_manifest.json：out_dir 的显式状态账本（阶段/状态/版本/时间）。写失败不阻断任务。"""
    import datetime as _dt
    root = Path(out_dir).expanduser().resolve()
    path = root / RUN_MANIFEST
    now = _dt.datetime.now().isoformat(timespec="seconds")
    try:
        with _run_manifest_lock(root):
            data = read_run_manifest(root)
            stages = data.get("stages")
            if not isinstance(stages, dict):
                stages = {}
            entry = stages.get(stage) if isinstance(stages.get(stage), dict) else {}
            producer = stage_producer(stage, out_dir=root, kb_paths=(config or {}).get("kb_paths"))
            if status == "running":
                entry = {"status": "running", "started": now, "producer": producer}
            else:
                entry.update({"status": status, "finished": now, "producer": producer})
                if route:
                    entry["route"] = route   # stub 降级 ≠ 真 LLM：账本必须可区分（2026-07-08 审计）
                if outputs is not None:
                    entry["outputs"] = _relative_outputs(root, outputs)
                elif status == "ok" and "outputs" not in entry and stage in STAGE_REQUIRED_OUTPUTS:
                    entry["outputs"] = list(STAGE_REQUIRED_OUTPUTS[stage])
                if status == "ok":
                    entry["input_fingerprint"] = input_fingerprint or stage_input_fingerprint(
                        root, stage, route=route, template_path=template_path,
                        input_path=input_path, config=config)
                    if input_files_fingerprint:
                        entry["input_files_fingerprint"] = input_files_fingerprint
                if action:
                    entry["last_action"] = action
                if error:
                    entry["error"] = str(error)[:300]
                else:
                    entry.pop("error", None)
                if stage == "ai-extract" and status in {"ok", "partial"}:
                    entry["claim_components"] = _claim_component_manifest(root)
            stages[stage] = entry
            data.update({"manifest_version": 2, "stages": stages, "updated": now})
            _atomic_write_json(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            _write_stage_manifest(root, stage, entry)
    except OSError:  # pragma: no cover - manifest 写失败不阻断任务本体
        LOGGER.warning("run_manifest 写入失败（忽略）：%s", path)


def _stage_completion_status(stage: str, payload: Any) -> str:
    """Return a non-reusable terminal status when a stage produced incomplete output."""
    if stage == "ai-extract" and isinstance(payload, dict):
        quality = payload.get("quality") if isinstance(payload.get("quality"), dict) else {}
        failed_sections = int(payload.get("failed_sections") or quality.get("failed_sections") or 0)
        if failed_sections > 0:
            return "partial"
    if stage == "export-annotation-html" and isinstance(payload, dict):
        translations = payload.get("translations")
        if isinstance(translations, dict):
            unresolved = int(translations.get("unresolved") or 0)
            failed_calls = int(translations.get("failed_calls") or 0)
            if unresolved > 0 or failed_calls > 0:
                return "partial"
    return "ok"


def chain_task(out_dir: Path, *, stages: list[str], route: str = "stub",
               template_path: Path | None = None,
               sample_ratio: float | None = None,
               limit_sections: int | None = None,
               annotation_layout_mode: str = "pdf_original") -> dict[str, Any]:
    """交付物链的后端单命令编排（F1：编排从 App.vue 搬回后端——headless/批量/CI 的地基）。

    阶段按 CHAIN_ORDER 归一排序去重；template-write 无模板路径时前置报错（不跑一半才死）；
    逐阶段发进度事件并记 run_manifest；任一阶段失败 → 记账后整链响亮失败。
    """
    out_dir = out_dir.expanduser().resolve()
    unknown = [s for s in stages if s not in CHAIN_ORDER]
    if unknown:
        raise ValueError(f"未知阶段：{', '.join(unknown)}（可用：{', '.join(CHAIN_ORDER)}）")
    ordered = [s for s in CHAIN_ORDER if s in set(stages)]
    if not ordered:
        raise ValueError("阶段清单为空")
    if "template-write" in ordered and template_path is None:
        raise ValueError("template-write 阶段需要 --template（公司需求列表模板路径）")

    # 归一化与单命令落账一致（R8，0710 评审）：显式 0/0.0 与 None 指纹必须同形
    sample_ratio = sample_ratio or None
    limit_sections = limit_sections or None
    ai_config = {"sample_ratio": sample_ratio, "limit_sections": limit_sections}
    ai_dependent = {"functional-synthesis", "requirements-analysis", "template-write",
                    "clarification-report"}
    if route == "stub" and ai_dependent.intersection(ordered) and not stage_is_reusable(
            out_dir, "ai-extract", route="stub", config=ai_config):
        raise ValueError(
            "当前链包含功能重组/需求分析等 AI 依赖阶段，但没有可复用的 AI 抽取产物；"
            "请使用 openai_compatible 完成 AI 抽取后再继续。"
        )

    runners: dict[str, Any] = {
        "ai-extract": lambda: ai_extract_task(out_dir, route=route,
                                              limit_sections=limit_sections,
                                              sample_ratio=sample_ratio),
        "functional-synthesis": lambda: functional_synthesis_task(out_dir, route=route),
        "assemble": lambda: assemble_task(out_dir, enrich_route=route if route != "stub" else None),
        "requirements-analysis": lambda: requirements_analysis_task(
            out_dir, route=route, template_path=template_path),
        "template-write": lambda: template_write_task(out_dir, template_path),
        "clarification-report": lambda: clarification_report_task(out_dir),
        "compose": lambda: compose_task(out_dir),
        "export-annotation-html": lambda: export_annotation_html_task(
            out_dir, route=route, layout_mode=annotation_layout_mode),
    }

    results: dict[str, Any] = {}
    skipped_stages: list[str] = []
    payload: dict[str, Any] = {"kind": "chain", "out_dir": str(out_dir), "stages": ordered}
    global _CHAIN_ACTIVE
    _CHAIN_ACTIVE = True   # 链内各阶段跳过 summary;finally 复位,失败路径不污染后续任务
    try:
        llm_stages = {"ai-extract", "functional-synthesis", "assemble", "requirements-analysis",
                      "export-annotation-html"}
        for index, stage in enumerate(ordered, start=1):
            emit_progress({"stage": "chain", "step": stage, "completed": index - 1,
                           "total": len(ordered), "percent": int((index - 1) * 100 / len(ordered))})
            stage_route = route if stage in llm_stages else None
            stage_template = template_path if stage in {"requirements-analysis", "template-write"} else None
            if stage == "ai-extract":
                stage_config = {"sample_ratio": sample_ratio, "limit_sections": limit_sections}
            elif stage == "export-annotation-html":
                stage_config = {"layout_mode": annotation_layout_mode}
            else:
                stage_config = None
            reusable = stage_is_reusable(
                out_dir,
                stage,
                route=stage_route,
                template_path=stage_template,
                config=stage_config,
            )
            if (stage == "ai-extract" and not reusable
                    and ai_requirements_are_reusable(
                        out_dir,
                        route=stage_route,
                        config=stage_config,
                    )):
                scope = "sample" if sample_ratio or limit_sections else "full"
                try:
                    refresh = ai_extract.refresh_claim_shadow(
                        out_dir,
                        route=stage_route,
                        scope=scope,
                    )
                except Exception as exc:
                    error = f"ai-extract claim shadow refresh failed: {exc}"
                    update_run_manifest(
                        out_dir,
                        stage,
                        "failed",
                        route=stage_route,
                        error=error,
                        action="ledger_refresh_failed",
                        template_path=stage_template,
                        config=stage_config,
                    )
                    raise RuntimeError(error) from exc
                existing_stages = read_run_manifest(out_dir).get("stages", {})
                existing_entry = (
                    existing_stages.get(stage, {}) if isinstance(existing_stages, dict) else {}
                )
                outputs = list(dict.fromkeys([
                    *_stage_outputs(stage, existing_entry),
                    *(refresh.get("written") or []),
                ]))
                refresh["written"] = [str(out_dir / name) for name in outputs]
                refresh["resume_action"] = "ledger_refreshed"
                update_run_manifest(
                    out_dir,
                    stage,
                    "ok",
                    route=str(existing_entry.get("route") or stage_route or "") or None,
                    outputs=outputs,
                    action="ledger_refreshed",
                    template_path=stage_template,
                    config=stage_config,
                )
                results[stage] = refresh
                emit_progress({
                    "stage": "chain",
                    "step": stage,
                    "status": "ledger_refreshed",
                    "completed": index,
                    "total": len(ordered),
                    "percent": int(index * 100 / len(ordered)),
                })
                continue
            if reusable:
                stage_payload = skipped_stage_payload(out_dir, stage)
                skipped_stages.append(stage)
                existing_stages = read_run_manifest(out_dir).get("stages", {})
                existing_entry = existing_stages.get(stage, {}) if isinstance(existing_stages, dict) else {}
                preserved_route = str(existing_entry.get("route") or stage_route or "") or None
                update_run_manifest(out_dir, stage, "ok", route=preserved_route,
                                    outputs=stage_payload.get("written") or _stage_outputs(stage), action="skipped",
                                    input_fingerprint=str(existing_entry.get("input_fingerprint") or "") or None,
                                    template_path=stage_template, config=stage_config)
                emit_progress({"stage": "chain", "step": stage, "status": "skipped",
                               "completed": index, "total": len(ordered),
                               "percent": int(index * 100 / len(ordered))})
            else:
                update_run_manifest(out_dir, stage, "running")
                try:
                    stage_payload = runners[stage]()
                except Exception as exc:
                    update_run_manifest(out_dir, stage, "failed", error=str(exc))
                    raise RuntimeError(f"{stage} 阶段失败：{exc}") from exc
                stage_outputs = stage_payload.get("written") if isinstance(stage_payload, dict) else None
                actual_route = (str(stage_payload.get("route") or "").strip()
                                if isinstance(stage_payload, dict) else "") or stage_route
                leased_input_files = (str(stage_payload.get("_input_files_fingerprint") or "")
                                      if isinstance(stage_payload, dict) else "") or None
                completion_status = _stage_completion_status(stage, stage_payload)
                update_run_manifest(out_dir, stage, completion_status, route=actual_route,
                                    outputs=stage_outputs or _stage_outputs(stage), action="ran",
                                    template_path=stage_template, config=stage_config,
                                    input_files_fingerprint=leased_input_files)
            stage_payload = dict(stage_payload or {})
            stage_payload.pop("_input_files_fingerprint", None)
            stage_payload.pop("summary", None)   # 各阶段的 summary 体积大且重复，链尾统一给一份
            results[stage] = stage_payload
            # 顶层聚合：GUI 消息只看这几个键，不必翻 results
            if stage == "ai-extract":
                for key in ("consistency", "sampled", "quality", "count", "claim_shadow"):
                    if stage_payload.get(key) is not None:
                        payload[key] = stage_payload[key]
            elif stage == "requirements-analysis":
                payload["analysis"] = stage_payload.get("analysis")
            elif stage == "template-write":
                payload["template"] = stage_payload.get("report")
            elif stage == "clarification-report":
                payload["readiness"] = stage_payload.get("readiness")
                payload["questions"] = stage_payload.get("questions")
            # 阶段降级/告警上提（2026-07-08 审计 2-C）：此前 note 埋在 results 里，
            # stub 降级/部分章节失败时 GUI 一律显示「运行完成」全绿
            note = stage_payload.get("note")
            analysis = stage_payload.get("analysis")
            if not note and isinstance(analysis, dict):
                note = analysis.get("note")
            if note:
                payload.setdefault("stage_notes", []).append(f"{stage}: {note}")
            if stage not in skipped_stages:
                emit_progress({"stage": "chain", "step": stage, "completed": index,
                               "total": len(ordered), "percent": int(index * 100 / len(ordered))})

        from adjudication_bank import resolve_bank_path, update_bank
        bank_path = resolve_bank_path()
        if bank_path and "requirements-analysis" in ordered:
            try:   # 收割失败不影响链结果
                payload["adjudication_bank"] = update_bank(bank_path, out_dir)
            except Exception as exc:  # pragma: no cover
                LOGGER.warning("裁决样本库收割失败（忽略）：%s", exc)
        payload["results"] = results
        payload["skipped_stages"] = skipped_stages
    finally:
        _CHAIN_ACTIVE = False
    payload["summary"] = build_output_summary(out_dir)
    return payload


@_leased_pipeline_stage("export-annotation-html")
def export_annotation_html_task(out_dir: Path, route: str | None = None,
                                layout_mode: str = "pdf_original") -> dict[str, Any]:
    """生成可分享的文档批注 HTML bundle（内含 localStorage 裁决 + 导出 JSON）。

    route=openai_compatible 时补齐块级"说明"标记的原文中文翻译（内容哈希缓存
    annotation_translations.json，重导出零调用）；渲染本体保持确定性。"""
    import doc_annotation_export
    out_dir = out_dir.expanduser().resolve()
    path, translations = doc_annotation_export.export_annotation_bundle(
        out_dir, route=route, layout_mode=layout_mode)
    written = [str(path)]
    if translations.get("source_pdf"):
        written.append(str(translations["source_pdf"]))
    written.extend(str(item) for item in (translations.get("page_files") or []))
    payload = {"kind": "annotation_html", "out_dir": str(out_dir),
               "path": str(path), "route": str(translations.get("route") or "stub"),
               "layout_mode_requested": translations.get("layout_mode_requested"),
               "layout_mode": translations.get("layout_mode"),
               "source_pdf": translations.get("source_pdf"),
               "annotation_overlay": bool(translations.get("annotation_overlay")),
               "translations": translations, "written": written}
    notes: list[str] = []
    if route and route != "stub" and payload["route"] != "openai_compatible":
        notes.append("LLM 不可用，块级说明未翻译（原文照排，开启后重导出自动补齐）")
    if translations.get("rejected"):
        notes.append(f"{translations['rejected']} 条翻译含无据编码/数字被拒（保留原文）")
    if translations.get("failed_calls"):
        notes.append(f"{translations['failed_calls']} 批翻译调用失败（重新导出自动补齐）")
    if translations.get("pdf_render_error"):
        notes.append("PDF 批注覆盖层生成失败，已回退浏览器原版查看器")
    if str(translations.get("layout_mode") or "") == "pdf_original":
        # 数据处置提醒（0714 评审）：原版影印 bundle 内含完整原始 PDF + 整页影印图,
        # 数据面与优化模式（仅抽取片段）完全不同——分享文件夹=分享整份客户文档
        notes.append("原版影印导出为文件夹（含完整原始 PDF 与整页影印图），对外分享前请确认可提供整份文档")
    if notes:
        payload["note"] = "；".join(notes)
    return payload


def import_ai_decisions_task(out_dir: Path, decisions_file: Path) -> dict[str, Any]:
    """把 HTML 导出的裁决 JSON 回灌到 ai_review_states.jsonl（合进交付物）。"""
    import ai_review_actions
    out_dir = out_dir.expanduser().resolve()
    data = json.loads(Path(decisions_file).expanduser().read_text(encoding="utf-8"))
    decisions = data.get("decisions") if isinstance(data, dict) else data
    applied = 0
    skipped = 0
    needs_reconfirmation = 0
    conflicts = 0
    ownership_skipped = 0
    for d in (decisions or []):
        rid = str((d or {}).get("ai_req_id") or "").strip()
        status = str((d or {}).get("status") or "").strip()
        if not rid or not status:
            skipped += 1
            continue
        submitted_source = str(d.get("source_fingerprint") or "").strip()
        submitted_subject = str(d.get("review_subject_fingerprint") or "").strip()
        expected_target_fingerprint = str(
            d.get("expected_target_fingerprint") or ""
        ).strip()
        expected_target_publication_revision = str(
            d.get("expected_target_publication_revision") or ""
        ).strip()
        expected_target_authority_write_revision = str(
            d.get("expected_target_authority_write_revision") or ""
        ).strip()
        if not all((
            submitted_source,
            submitted_subject,
            expected_target_fingerprint,
            expected_target_publication_revision,
            expected_target_authority_write_revision,
        )):
            skipped += 1
            needs_reconfirmation += 1
            continue
        # 归属值单独校验：仅归属非法时丢归属、保留整行裁决（status/模块/意见不陪葬）
        ownership = str(d.get("ownership_override") or "").strip() or None
        if ownership:
            try:
                normalize_ownership(ownership)
            except ValueError:
                ownership = None
                ownership_skipped += 1
        try:
            from api_server import find_current_ai_requirement
            from omission_actions import extraction_operation_lock

            with extraction_operation_lock(out_dir, operation="import-ai-decision"):
                current = find_current_ai_requirement(out_dir, rid)
                if current is None:
                    raise ai_review_actions.AIReviewAuthorityConflict(
                        "AI requirement is not present in the current run",
                        current_revision="",
                    )
                current_cas = (
                    str(current.get("source_fingerprint") or ""),
                    str(current.get("review_subject_fingerprint") or ""),
                    str(current.get("target_fingerprint") or ""),
                    str(current.get("target_publication_revision") or ""),
                    str(current.get("target_authority_write_revision") or ""),
                )
                submitted_cas = (
                    submitted_source,
                    submitted_subject,
                    expected_target_fingerprint,
                    expected_target_publication_revision,
                    expected_target_authority_write_revision,
                )
                if submitted_cas != current_cas:
                    raise ai_review_actions.AIReviewAuthorityConflict(
                        "AI requirement or review authority changed",
                        current_revision=current_cas[-1],
                    )
                ai_review_actions.apply_ai_review_action(
                    out_dir,
                    rid,
                    status,
                    module_override=(d.get("module_override") or None),
                    ownership_override=ownership,
                    reason=(d.get("reason") or ""),
                    actor="html-import",
                    source_fingerprint_value=current_cas[0],
                    review_subject_fingerprint_value=current_cas[1],
                    review_anchor_fingerprint_value=(
                        ai_review_actions.review_anchor_fingerprint(current)
                    ),
                    expected_target_authority_write_revision=current_cas[-1],
                )
            applied += 1
        except ai_review_actions.AIReviewAuthorityConflict:
            skipped += 1
            conflicts += 1
        except ValueError:
            skipped += 1
    payload: dict[str, Any] = {"kind": "ai_decisions_import", "out_dir": str(out_dir),
                               "applied": applied, "skipped": skipped}
    if needs_reconfirmation:
        payload["needs_reconfirmation"] = needs_reconfirmation
    if conflicts:
        payload["conflicts"] = conflicts
    if ownership_skipped:
        payload["ownership_skipped"] = ownership_skipped
    # 裁决回流交付物：导入后立即重建 merged_spec（免 LLM）
    if applied and (out_dir / "ai_requirements.jsonl").exists():
        rebuilt = ai_extract.rebuild_merged_spec(out_dir)
        payload["rebuilt"] = rebuilt
        try:
            from adjudication_bank import resolve_bank_path, update_bank

            bank_path = resolve_bank_path()
            if bank_path is not None:
                payload["adjudication_bank"] = update_bank(bank_path, out_dir)
        except Exception as exc:  # 导入/重建已成功；学习资产失败只留告警
            LOGGER.warning("HTML 裁决导入后样本库收割失败（忽略）：%s", exc)
    return payload


def build_output_summary(out_dir: Path) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    requirements = read_jsonl(out_dir / "atomic_requirements.jsonl")
    reviews = read_jsonl(out_dir / "llm_review_results.jsonl")
    states = read_jsonl(out_dir / "review_states.jsonl")
    status_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    confidence_counts = {"high": 0, "medium": 0, "low": 0}
    for row in requirements:
        requirement_type = str(row.get("requirement_type") or row.get("type") or "unknown")
        type_counts[requirement_type] = type_counts.get(requirement_type, 0) + 1
        confidence = row.get("confidence")
        if isinstance(confidence, (int, float)):
            if confidence >= 0.9:
                confidence_counts["high"] += 1
            elif confidence >= 0.7:
                confidence_counts["medium"] += 1
            else:
                confidence_counts["low"] += 1
    for state in states:
        status = str(state.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "counts": {
            "requirements": len(requirements),
            "reviews": len(reviews),
            "review_states": len(states),
        },
        "status_counts": status_counts,
        "type_counts": type_counts,
        "confidence_counts": confidence_counts,
        "run_manifest": read_run_manifest(out_dir),
    }


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

    summary_parser = subparsers.add_parser("summary")
    summary_parser.add_argument("--out", type=Path, required=True)

    anno_parser = subparsers.add_parser("export-annotation-html")
    anno_parser.add_argument("--out", type=Path, required=True)
    anno_parser.add_argument("--route", choices=["stub", "openai_compatible"], default=None,
                             help="openai_compatible 时补齐块级说明标记的中文翻译（缓存复用）")
    anno_parser.add_argument("--layout-mode", choices=["optimized", "pdf_original"],
                             default="pdf_original")

    import_parser = subparsers.add_parser("import-ai-decisions")
    import_parser.add_argument("--out", type=Path, required=True)
    import_parser.add_argument("--file", type=Path, required=True, help="HTML 导出的裁决 JSON")

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
    return parser.parse_args(argv)


def _manifest_context_from_args(args: argparse.Namespace) -> dict[str, Any]:
    command = str(getattr(args, "command", "") or "")
    context: dict[str, Any] = {}
    if command in {"llm-review", "ai-extract", "requirements-analysis"}:
        context["route"] = getattr(args, "llm_route", None)
    elif command == "assemble":
        context["route"] = getattr(args, "enrich_route", None) or None
    elif command == "export-annotation-html":
        context["route"] = getattr(args, "route", None) or None
        context["config"] = {"layout_mode": getattr(args, "layout_mode", "pdf_original")}
    if command in {"requirements-analysis", "template-write"}:
        context["template_path"] = getattr(args, "template", None)
    if command == "ai-extract":
        context["config"] = {
            "sample_ratio": getattr(args, "sample_ratio", 0.0) or None,
            "limit_sections": getattr(args, "limit_sections", 0) or None,
        }
    return context


def setup_run_logging(out_dir: Path | None) -> None:
    """后端任务日志：stderr（Electron 收集持久化）+ <输出目录>/run.log（跟着交付物走）。

    此前 GUI 路径全链路零日志：LOGGER.info（LLM 调用时长/自检轮次/富化被拒原因/降级）被
    Python 兜底 handler 丢弃，Electron 只在任务失败时把 stderr 拼进弹窗。排查"为什么慢/
    为什么产物长这样"无从下手——本函数让每次运行在输出目录留下完整可追溯日志。幂等可重入。
    """
    logger = logging.getLogger("requirement_atomizer")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    have = {getattr(h, "_ratomizer_tag", None) for h in logger.handlers}
    if "stderr" not in have:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(fmt)
        handler._ratomizer_tag = "stderr"  # type: ignore[attr-defined]
        logger.addHandler(handler)
    if out_dir is not None and "runlog" not in have:
        try:
            out_dir = Path(out_dir).expanduser().resolve()
            out_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(out_dir / "run.log", encoding="utf-8")
            file_handler.setFormatter(fmt)
            file_handler._ratomizer_tag = "runlog"  # type: ignore[attr-defined]
            logger.addHandler(file_handler)
        except OSError:  # 日志落盘失败不阻断任务
            pass
    # LLM 消息级追踪：完整收发落 <out>/llm_trace.jsonl（含 prompt/响应全文/token 用量）。
    # 默认开（体量 ~几 MB/次运行，与 blocks.jsonl 同量级）；设 RATOMIZER_LLM_TRACE=0 可关。
    if out_dir is not None and os.environ.get("RATOMIZER_LLM_TRACE", "").strip() != "0":
        import llm_client
        llm_client.set_trace_path(Path(out_dir) / "llm_trace.jsonl")


def teardown_run_logging() -> None:
    """关闭并摘除 run.log 的 FileHandler（任务进程一次性；不关会锁住输出目录文件句柄）。"""
    logger = logging.getLogger("requirement_atomizer")
    for handler in list(logger.handlers):
        if getattr(handler, "_ratomizer_tag", None) == "runlog":
            handler.close()
            logger.removeHandler(handler)
    import llm_client
    llm_client.set_trace_path(None)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "claim-shadow-acceptance":
        from claim_acceptance import main as claim_acceptance_main
        forwarded = ["--input", str(args.input)]
        if args.output is not None:
            forwarded.extend(["--output", str(args.output)])
        return claim_acceptance_main(forwarded)
    if args.command == "claim-shadow-review-packet":
        from claim_review_packet import main as claim_review_packet_main
        return claim_review_packet_main([
            "--input", str(args.input),
            "--output-dir", str(args.output_dir),
        ])
    if args.command == "claim-shadow-review-import":
        from claim_review_import import main as claim_review_import_main
        return claim_review_import_main([
            "--input", str(args.input),
            "--decisions", str(args.decisions),
            "--output", str(args.output),
            "--golden-manifest", str(args.golden_manifest),
        ])
    setup_run_logging(getattr(args, "out", None))
    logging.getLogger("requirement_atomizer").info("desktop task 开始：%s", args.command)
    try:
        if args.command == "run":
            payload = run_pipeline_task(
                args.input,
                args.out,
                skip_review=args.skip_review,
                llm_route=args.llm_route,
                review_scope=args.review_scope,
                llm_review_limit=args.llm_review_limit,
                chunk_chars=args.chunk_chars,
                kb_paths=args.kb,
                domain_pack_dir=args.domain_pack,
            )
        elif args.command == "export":
            payload = export_task(args.out, split_formats(args.formats))
        elif args.command == "assemble":
            payload = assemble_task(
                args.out,
                formats=split_formats(args.formats),
                enrich_route=args.enrich_route or None,
                blue_book_index_path=args.blue_book_index,
            )
        elif args.command == "functional-synthesis":
            payload = functional_synthesis_task(args.out, route=args.llm_route)
        elif args.command == "compose":
            payload = compose_task(args.out)
        elif args.command == "adjudication-bank":
            from adjudication_bank import update_bank
            payload = {"kind": "adjudication_bank", **update_bank(args.bank, args.out)}
        elif args.command == "import-clarification-answers":
            payload = import_clarification_workbook_task(args.out, args.file)
        elif args.command == "chain":
            payload = chain_task(args.out, stages=[x.strip() for x in args.stages.split(",") if x.strip()],
                                 route=args.llm_route, template_path=args.template,
                                 sample_ratio=args.sample_ratio or None,
                                 limit_sections=args.limit_sections or None,
                                 annotation_layout_mode=args.annotation_layout_mode)
        elif args.command == "clarification-report":
            payload = clarification_report_task(args.out)
        elif args.command == "template-write":
            payload = template_write_task(args.out, args.template)
        elif args.command == "requirements-analysis":
            payload = requirements_analysis_task(args.out, route=args.llm_route, template_path=args.template)
        elif args.command == "ai-extract":
            payload = ai_extract_task(args.out, route=args.llm_route,
                                      limit_sections=args.limit_sections or None,
                                      sample_ratio=args.sample_ratio or None)
        elif args.command == "export-annotation-html":
            payload = export_annotation_html_task(
                args.out,
                route=getattr(args, "route", None),
                layout_mode=args.layout_mode,
            )
        elif args.command == "import-ai-decisions":
            payload = import_ai_decisions_task(args.out, args.file)
        elif args.command == "claim-ledger-fold":
            from claim_review_actions import fold_effective_ledger

            payload = {
                "kind": "claim_ledger_fold",
                **fold_effective_ledger(
                    args.out,
                    actor_trigger="desktop-claim-ledger-fold",
                ),
            }
        else:
            payload = {"kind": "summary", "out_dir": str(args.out.expanduser().resolve()), "summary": build_output_summary(args.out)}
    except Exception as exc:
        logging.getLogger("requirement_atomizer").exception("desktop task 失败：%s", args.command)
        # 单步命令也记账（chain 内部已逐阶段记，不重复）
        if args.command in CHAIN_ORDER and getattr(args, "out", None):
            update_run_manifest(args.out, args.command, "failed", error=str(exc),
                                **_manifest_context_from_args(args))
        print(json.dumps({"error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
    finally:
        teardown_run_logging()
    if args.command in CHAIN_ORDER and getattr(args, "out", None):
        manifest_context = _manifest_context_from_args(args)
        actual_route = str(payload.get("route") or "").strip() if isinstance(payload, dict) else ""
        if actual_route:
            manifest_context["route"] = actual_route
        if args.command == "export-annotation-html" and isinstance(payload, dict):
            manifest_context["outputs"] = payload.get("written") or None
        leased_input_files = (str(payload.pop("_input_files_fingerprint", "") or "")
                              if isinstance(payload, dict) else "") or None
        if leased_input_files:
            manifest_context["input_files_fingerprint"] = leased_input_files
        update_run_manifest(
            args.out,
            args.command,
            _stage_completion_status(args.command, payload),
            **manifest_context,
        )
    print_json_payload(payload)
    return 0


def split_formats(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def emit_progress(event: dict[str, Any]) -> None:
    print(f"{PROGRESS_PREFIX}{json.dumps(event, ensure_ascii=True)}", flush=True)


def print_json_payload(payload: dict[str, Any]) -> None:
    """Write IPC JSON safely even when packaged Windows stdout is GBK."""
    print(json.dumps(payload, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
