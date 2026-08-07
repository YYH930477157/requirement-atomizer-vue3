from __future__ import annotations

import argparse
import config
import desktop_tasks
import hmac
import json
import math
import os
import re
from functools import wraps
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping
from urllib.parse import parse_qs, urlparse

from review_actions import apply_review_action
from ai_review_actions import (
    AIReviewAuthorityConflict,
    apply_ai_review_action,
    ai_target_authority_write_revision,
    ensure_requirement_identity,
    normalize_module_override,
    review_anchor_fingerprint,
    review_state_for_requirement,
    review_state_needs_reconfirmation,
    review_subject_fingerprint,
    source_ai_requirement_id,
    source_fingerprint,
)
from cosem_behavior_spec import extract_codes
from extract_guards import produced_ints
from review_state import (
    ReviewAuthorityConflict,
    atomic_target_authority_write_revision,
    target_publication_revision,
)
from adjudicate import AdjudicationUnavailableError
from io_utils import read_jsonl
from llm_client import LLMConnectionError, LLMResponseError, chat_json
from llm_pipeline import DEFAULT_PIPELINE_PATH, llm_config_from_route, load_review_pipeline
from requirement_kb.matching import clean_text as normalize_text
from result_package import (
    ResultPackageCorrupt,
    ResultPackageError,
    detect_result_layout,
    governed_artifact_path,
    load_result_package,
    resolve_analysis_root,
)
from table_review_state import (
    TableReviewConflict,
    apply_table_review_decision,
    build_table_review_payload,
    run_table_review_recompute_recovery,
)


DEFAULT_OUTPUT = Path("out/abnt_nbr_16968_atomizer_v5")
DEFAULT_ALLOWED_ORIGINS = {"http://127.0.0.1:8770", "http://localhost:8770"}
TOKEN_HEADER = "X-Requirement-Atomizer-Token"
# 裁决重建防抖（0714 批次二 S4）：此前每次裁决 POST 同步全量重建 merged_spec
# （openpyxl 逐格 xlsx + 一致性报表 O(块×需求) 双向子串扫描）——评审员连续点
# 接受/拒绝时每点一下卡一次。改为标脏 + 合并延迟重建：窗口内多次裁决只重建一次。
# 批注视图读 ai_requirements.jsonl + 裁决状态（不读 merged），视图一致性不受影响；
# CLI 导入裁决路径（desktop_tasks）仍同步重建。=0 恢复同步（测试/严格场景）。
REBUILD_DEBOUNCE_ENV = "RATOMIZER_REBUILD_DEBOUNCE_S"
DEFAULT_REBUILD_DEBOUNCE_S = 1.5


def _resolve_rebuild_debounce() -> float:
    import os
    raw = os.environ.get(REBUILD_DEBOUNCE_ENV)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = DEFAULT_REBUILD_DEBOUNCE_S
    return max(0.0, min(30.0, value))


class DeliverableRebuilder:
    """裁决后交付物重建合并器：schedule() 标脏并（重）启动延迟定时器，窗口内的
    连续裁决合并为一次 rebuild_merged_spec；delay<=0 时退化为同步重建（旧语义）。
    重建失败仅记日志（与原实现一致——裁决状态本身已落盘，绝不因重建失败丢裁决）。"""

    def __init__(self, delay_s: float | None = None):
        import threading
        self._delay = _resolve_rebuild_debounce() if delay_s is None else max(0.0, delay_s)
        self._lock = threading.Lock()
        self._rebuild_lock = threading.Lock()
        self._timer: "threading.Timer | None" = None
        self._pending: Path | None = None

    def schedule(self, out_dir: Path) -> None:
        if self._delay <= 0:
            self._rebuild(out_dir)
            return
        import threading
        with self._lock:
            self._pending = out_dir
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._delay, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def flush(self) -> None:
        """立即排空待重建（测试/退出前用）。"""
        with self._lock:
            timer = self._timer
        if timer is not None:
            timer.cancel()
        self._fire()

    def _fire(self) -> None:
        with self._lock:
            out_dir = self._pending
            self._pending = None
            self._timer = None
        if out_dir is not None:
            self._rebuild(out_dir)

    def _rebuild(self, out_dir: Path) -> None:
        with self._rebuild_lock:
            self._perform_rebuild(out_dir)

    @staticmethod
    def _perform_rebuild(out_dir: Path) -> None:
        try:
            from ai_extract import rebuild_merged_spec
            rebuild_merged_spec(out_dir)
        except Exception as exc:  # pragma: no cover - 重建失败仅记日志
            import logging
            logging.getLogger("requirement_atomizer").warning("裁决后重建交付物失败：%s", exc)


_REBUILDER: DeliverableRebuilder | None = None


def _rebuilder() -> DeliverableRebuilder:
    global _REBUILDER
    if _REBUILDER is None:
        _REBUILDER = DeliverableRebuilder()
    return _REBUILDER


def _result_package_get_boundary(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except ResultPackageError as exc:
            modified = isinstance(exc, ResultPackageCorrupt) and "changed" in str(exc)
            self.send_json({
                "error": "result_package_modified" if modified else "result_package_unavailable",
                "detail": str(exc),
                "retryable": not modified,
            }, status=503)
            return None

    return wrapped


class RequirementAPIHandler(BaseHTTPRequestHandler):
    output_dir: Path = DEFAULT_OUTPUT
    package_root: Path = DEFAULT_OUTPUT
    allowed_origins: set[str] = set(DEFAULT_ALLOWED_ORIGINS)
    local_token: str = ""

    def _refresh_analysis_root(self) -> None:
        current = Path(self.output_dir).expanduser().resolve()
        configured = Path(self.package_root).expanduser().resolve()
        try:
            current.relative_to(configured)
        except ValueError:
            configured = current
        self.package_root = configured
        self.output_dir = resolve_analysis_root(configured)

    def do_OPTIONS(self) -> None:
        origin = self.headers.get("Origin", "")
        if not is_allowed_origin(origin, self.allowed_origins):
            self.send_error(403, "Origin not allowed")
            return
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    @_result_package_get_boundary
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        origin = self.headers.get("Origin", "")
        if not is_allowed_origin(origin, self.allowed_origins):
            self.send_error(403, "Origin not allowed")
            return
        if parsed.path == "/health":
            self.send_json({
                "ok": True,
                "service": "requirement-atomizer-api",
                "text_mode": config.text_mode_enabled(),
            })
            return
        if not token_is_valid(self.local_token, self.headers, params):
            self.send_json({"error": "unauthorized"}, status=401)
            return
        self._refresh_analysis_root()
        if parsed.path == "/result-package":
            try:
                layout = detect_result_layout(self.package_root)
                # S5：显式完整校验（「打开已有结果」）——verify=1 时重算交付物与
                # 完成证据 SHA，不一致如实 503 result_package_modified
                verify = one(params, "verify") in {"1", "true"}
                package = (
                    load_result_package(self.package_root, verify=verify)
                    if layout == "package_v1"
                    else None
                )
            except ResultPackageError as exc:
                # marker 损坏/残留发布 journal：结构化 503，不掐断连接（2026-08-03 审查 S1）
                modified = isinstance(exc, ResultPackageCorrupt) and "changed" in str(exc)
                self.send_json({
                    "error": "result_package_modified" if modified else "result_package_unavailable",
                    "detail": (
                        f"结果文件已被修改：{exc}" if modified else str(exc)
                    ),
                    "retryable": not modified,
                }, status=503)
                return
            self.send_json({
                "layout": layout,
                "package_root": str(self.package_root),
                "analysis_root": str(self.output_dir),
                "package": package,
                "review": build_review_summary(self.output_dir),
            })
            return
        if parsed.path == "/document/pdf":
            # 惰性反向导入（同 _clean_block_text 先例）：影印批注数据的唯一权威实现在导出侧,
            # 应用内视图与分享 HTML 共用同一份几何/换算——双渲染器等价靠同源,不靠各写一份
            from doc_annotation_export import build_pdf_annotation_payload
            try:
                extraction = build_ai_extraction_status(self.output_dir)
                partial_requirements = (
                    list(extraction.get("rows") or []) if extraction.get("run_id") else None
                )
                if partial_requirements is None and final_ai_requirements_are_stale(self.output_dir):
                    partial_requirements = []
                self.send_json(build_pdf_annotation_payload(
                    self.output_dir,
                    requirements=partial_requirements,
                ))
            except (TimeoutError, OSError, ValueError) as exc:
                # 抽取轮询路径：文件被活跃 writer 替换/撕裂是瞬态，契约同 /review-actions
                self.send_json({"error": str(exc), "retryable": True}, status=503)
            return
        if parsed.path.startswith("/document/pages/"):
            filename = parsed.path.rsplit("/", 1)[-1]
            # 文件名白名单（防路径穿越）：只放行导出侧生成的 page-NNNN.png
            if not re.fullmatch(r"page-\d{4}\.png", filename):
                self.send_json({"error": "invalid page name"}, status=403)
                return
            target = self.output_dir / "document_pages" / filename
            if not target.is_file():
                self.send_json({"error": "page not found"}, status=404)
                return
            raw = target.read_bytes()
            self.send_response(200)
            self.send_cors_headers()
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "max-age=3600")
            self.end_headers()
            self.wfile.write(raw)
            return
        if parsed.path == "/manifest":
            self.send_file_json("manifest.json")
            return
        if parsed.path == "/quality":
            self.send_file_json("quality_report.json")
            return
        if parsed.path == "/requirements":
            limit = parse_int(one(params, "limit"), default=50)
            requirement_type = one(params, "type")
            rows = read_jsonl(self.output_dir / "atomic_requirements.jsonl")
            if requirement_type:
                rows = [row for row in rows if row.get("requirement_type") == requirement_type]
            self.send_json(enrich_requirements(rows, self.output_dir)[:limit])
            return
        if parsed.path == "/reviews":
            limit = parse_int(one(params, "limit"), default=50)
            self.send_json(read_jsonl(self.output_dir / "llm_review_results.jsonl")[:limit])
            return
        if parsed.path == "/review-states":
            limit = parse_int(one(params, "limit"), default=50)
            status = one(params, "status")
            rows = read_jsonl(governed_artifact_path(
                self.output_dir, "review_states.jsonl", category="state", for_write=False,
            ))
            if status:
                rows = [row for row in rows if row.get("status") == status]
            self.send_json(rows[:limit])
            return
        if parsed.path == "/review-summary":
            self.send_json(build_review_summary(self.output_dir))
            return
        if parsed.path == "/table-reviews":
            from claim_artifacts import ClaimArtifactError, ClaimBaseMigrationRequired
            try:
                self.send_json(build_table_review_payload(self.output_dir))
            except ClaimBaseMigrationRequired as exc:
                # Kimi 高危 #4：GET 同样要接住 Claim 异常族（project_table_dispositions
                # 经 _current_claim_projection 读 claim 产物，stale/torn 会抛），否则断连。
                self.send_json({
                    "error": "base_migration_required",
                    "detail": str(exc),
                    "retryable": False,
                }, status=503)
            except ClaimArtifactError as exc:
                self.send_json({"error": str(exc), "retryable": True}, status=503)
            except (OSError, TimeoutError, ValueError) as exc:
                self.send_json({"error": str(exc), "retryable": True}, status=503)
            return
        if parsed.path == "/document":
            try:
                self.send_json(build_document_blocks(self.output_dir))
            except (TimeoutError, OSError, ValueError) as exc:
                self.send_json({"error": str(exc), "retryable": True}, status=503)
            return
        if parsed.path == "/ai-requirements":
            self.send_json(build_ai_requirements(self.output_dir))
            return
        if parsed.path == "/ai-extraction-status":
            try:
                self.send_json(build_ai_extraction_status(self.output_dir))
            except (TimeoutError, OSError, ValueError) as exc:
                self.send_json({"error": str(exc), "retryable": True}, status=503)
            return
        if parsed.path == "/omission-actions":
            from omission_actions import read_current_omission_states
            try:
                states = read_current_omission_states(self.output_dir)
            except (TimeoutError, OSError, ValueError) as exc:
                self.send_json({"error": str(exc), "retryable": True}, status=503)
                return
            self.send_json({
                "schema": "omission-actions/v1",
                "states": [states[key] for key in sorted(states)],
            })
            return
        if parsed.path == "/review-insights":
            self.send_json(load_review_insights(self.output_dir))
            return
        if parsed.path == "/closure-status":
            try:
                self.send_json(desktop_tasks.evaluate_full_closure(self.output_dir))
            except (TimeoutError, OSError, ValueError) as exc:
                self.send_json({"error": str(exc), "retryable": True}, status=503)
            return
        if parsed.path == "/changeset-report":
            self.handle_changeset_report(params)
            return
        if parsed.path == "/clarification-internal-checks":
            from clarification_report import current_internal_checks
            try:
                self.send_json(current_internal_checks(self.output_dir))
            except (TimeoutError, OSError, ValueError) as exc:
                self.send_json({"error": str(exc), "retryable": True}, status=503)
            return
        claim_views = {
            "/claim-catalog": "catalog",
            "/claim-ledger": "ledger",
            "/claim-coverage-groups": "coverage_groups",
            "/claim-metrics": "metrics",
            "/claim-review-events": "review_events",
            "/claim-queue": "queue",
        }
        if parsed.path in claim_views:
            from claim_artifacts import (
                ClaimArtifactError,
                ClaimBaseMigrationRequired,
                ClaimEffectiveRecoveryPending,
            )
            from claim_views import ClaimViewMigrationRequired, build_claim_view

            resolution = one(params, "resolution")
            if resolution and resolution not in {"covered", "excluded", "uncertain"}:
                self.send_json({"error": "invalid claim resolution filter"}, status=400)
                return
            try:
                limit = parse_claim_page_value(
                    one(params, "limit"), name="limit", kind="limit", default=100
                )
                offset = parse_claim_page_value(
                    one(params, "offset"), name="offset", kind="offset", default=0
                )
                compat_limit = (
                    parse_claim_page_value(
                        one(params, "compat_limit"),
                        name="compat_limit",
                        kind="limit",
                        default=100,
                    )
                    if one(params, "compat_limit")
                    else None
                )
                compat_offset = parse_claim_page_value(
                    one(params, "compat_offset"),
                    name="compat_offset",
                    kind="offset",
                    default=0,
                )
            except ValueError as exc:
                self.send_json({"error": str(exc), "retryable": False}, status=400)
                return
            try:
                payload = build_claim_view(
                    self.output_dir,
                    claim_views[parsed.path],
                    resolution=resolution,
                    owner_unit_id=one(params, "owner_unit_id"),
                    claim_id=one(params, "claim_id"),
                    limit=limit,
                    offset=offset,
                    compat_limit=compat_limit,
                    compat_offset=compat_offset,
                )
            except ClaimViewMigrationRequired as exc:
                self.send_json({
                    "error": "effective_migration_required",
                    "detail": str(exc),
                    "retryable": True,
                }, status=503)
                return
            except ClaimBaseMigrationRequired as exc:
                # S11：陈旧 claim 产物协议 = 迁移门语义（唯一恢复是重跑 atomize），
                # 不冒充通用 artifact 故障；与 /claim-maintenance 的 503 同步
                self.send_json({
                    "error": "base_migration_required",
                    "detail": str(exc),
                    "retryable": False,
                }, status=503)
                return
            except ClaimEffectiveRecoveryPending as exc:
                self.send_json({
                    "error": "effective_recovery_pending",
                    "detail": str(exc),
                    "retryable": True,
                }, status=503)
                return
            except (
                ClaimArtifactError,
                TimeoutError,
                OSError,
                json.JSONDecodeError,
                UnicodeDecodeError,
            ) as exc:
                self.send_json({
                    "error": "claim_artifact_unavailable",
                    "detail": str(exc),
                    "retryable": True,
                }, status=503)
                return
            self.send_json(payload)
            return
        if parsed.path == "/verification-states":
            self.handle_verification_states_get()
            return
        if parsed.path == "/functional-requirements":
            self.handle_functional_requirements_get()
            return
        if parsed.path == "/manual-requirements":
            self.handle_manual_requirements_get()
            return
        if parsed.path == "/lifecycle-events":
            self.handle_lifecycle_events_get()
            return
        if parsed.path == "/dependency-candidates":
            self.handle_dependency_candidates_get()
            return
        if parsed.path == "/rtm-edges":
            self.handle_rtm_edges_get()
            return
        if parsed.path == "/requirement-library/search":
            self.handle_requirement_library_search(params)
            return
        if parsed.path == "/adjudications":
            self.handle_adjudications_get()
            return
        if parsed.path == "/adjudication-summary":
            self.handle_adjudication_summary_get()
            return
        self.send_error(404, "Unknown endpoint")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        origin = self.headers.get("Origin", "")
        if not is_allowed_origin(origin, self.allowed_origins):
            self.send_error(403, "Origin not allowed")
            return
        if not self.local_token or not token_is_valid(self.local_token, self.headers, params):
            self.send_json({"error": "unauthorized"}, status=401)
            return
        self._refresh_analysis_root()
        if parsed.path == "/translations":
            self.handle_translation()
            return
        if parsed.path == "/ai-review-actions":
            self.handle_ai_review_action()
            return
        if parsed.path == "/table-review-actions":
            self.handle_table_review_action()
            return
        if parsed.path == "/omission-actions":
            self.handle_omission_action()
            return
        if parsed.path == "/omission-reextract":
            self.handle_omission_reextract()
            return
        if parsed.path == "/claim-adjudications":
            self.handle_claim_adjudication()
            return
        if parsed.path == "/claim-queue/execute":
            self.handle_claim_queue_execute()
            return
        if parsed.path == "/claim-structural-overrides":
            self.handle_claim_structural_override()
            return
        if parsed.path == "/claim-maintenance":
            self.handle_claim_maintenance()
            return
        if parsed.path in ("/spot-extract", "/api/spot-extract"):
            # 点解析（WP-B）：/spot-extract 为现有无前缀约定的正规路径，
            # /api/spot-extract 为冻结规格字面别名——同一处理器，无行为分叉
            self.handle_spot_extract()
            return
        if parsed.path == "/clarification-check-actions/batch":
            self.handle_clarification_check_batch()
            return
        if parsed.path == "/verification-actions":
            self.handle_verification_action()
            return
        if parsed.path == "/requirement-rollback":
            self.handle_requirement_rollback()
            return
        if parsed.path == "/manual-requirement":
            self.handle_manual_requirement()
            return
        if parsed.path == "/dependency-decisions":
            self.handle_dependency_decision()
            return
        if parsed.path == "/requirement-library/adopt":
            self.handle_requirement_library_adopt()
            return
        if parsed.path == "/adjudications/run":
            self.handle_adjudication_run()
            return
        if parsed.path == "/adjudications/overturn":
            self.handle_adjudication_overturn()
            return
        if parsed.path != "/review-actions":
            self.send_error(404, "Unknown endpoint")
            return

        payload = self.read_json_body()
        if payload is None:
            return
        requirement_id = str(payload.get("requirement_id") or "").strip()
        status = str(payload.get("status") or "").strip()
        actor = str(payload.get("actor") or "").strip() or None
        reason = str(payload.get("reason") or "").strip()
        expected_target_fingerprint = str(
            payload.get("expected_target_fingerprint") or ""
        ).strip()
        expected_target_publication_revision = str(
            payload.get("expected_target_publication_revision") or ""
        ).strip()
        expected_target_authority_write_revision = str(
            payload.get("expected_target_authority_write_revision") or ""
        ).strip()
        if not requirement_id or not status:
            self.send_json({"error": "requirement_id and status are required"}, status=400)
            return
        if (
            not expected_target_fingerprint
            or not expected_target_publication_revision
            or not expected_target_authority_write_revision
        ):
            self.send_json({
                "error": (
                    "expected_target_fingerprint, expected_target_publication_revision, and "
                    "expected_target_authority_write_revision are required"
                ),
                "needs_reconfirmation": True,
            }, status=400)
            return
        current_cas: dict[str, str] = {}
        try:
            from omission_actions import OmissionConflictError, extraction_operation_lock

            with extraction_operation_lock(self.output_dir, operation="review-action"):
                current_requirements = read_jsonl(
                    self.output_dir / "atomic_requirements.jsonl"
                )
                current_rows = enrich_requirements(
                    current_requirements,
                    self.output_dir,
                )
                matches = [
                    row for row in current_rows
                    if requirement_id in requirement_identity_keys(row)
                ]
                if len(matches) != 1:
                    self.send_json({
                        "error": "atomic requirement is not uniquely present in the current run",
                        "needs_reconfirmation": True,
                    }, status=409)
                    return
                current = matches[0]
                current_cas = {
                    "target_fingerprint": str(current.get("target_fingerprint") or ""),
                    "target_publication_revision": str(
                        current.get("target_publication_revision") or ""
                    ),
                    "target_authority_write_revision": str(
                        current.get("target_authority_write_revision") or ""
                    ),
                }
                if (
                    expected_target_fingerprint != current_cas["target_fingerprint"]
                    or expected_target_publication_revision
                    != current_cas["target_publication_revision"]
                    or expected_target_authority_write_revision
                    != current_cas["target_authority_write_revision"]
                ):
                    self.send_json({
                        "error": "atomic requirement or review authority changed; refresh before adjudicating",
                        "needs_reconfirmation": True,
                        **current_cas,
                    }, status=409)
                    return
                state = apply_review_action(
                    self.output_dir,
                    requirement_id,
                    status,
                    actor=actor,
                    reason=reason,
                    expected_target_fingerprint=expected_target_fingerprint,
                    expected_target_authority_write_revision=(
                        expected_target_authority_write_revision
                    ),
                )
                state["target_fingerprint"] = current_cas["target_fingerprint"]
                state["target_publication_revision"] = current_cas[
                    "target_publication_revision"
                ]
        except OmissionConflictError as exc:
            self.send_json({"error": str(exc), "retryable": True}, status=409)
            return
        except ReviewAuthorityConflict as exc:
            self.send_json({
                "error": str(exc),
                "needs_reconfirmation": True,
                **current_cas,
                "target_authority_write_revision": exc.current_revision,
            }, status=409)
            return
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=409)
            return
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": str(exc), "retryable": True}, status=503)
            return
        self.send_json(state)

    def handle_table_review_action(self) -> None:
        payload = self.read_json_body()
        if payload is None:
            return
        table_id = str(payload.get("table_id") or "").strip()
        expected_fingerprint = str(
            payload.get("expected_evidence_fingerprint") or ""
        ).strip()
        role_mapping = payload.get("role_mapping")
        if not table_id or not expected_fingerprint or not isinstance(role_mapping, dict):
            self.send_json({
                "error": (
                    "table_id, expected_evidence_fingerprint, and role_mapping are required"
                )
            }, status=400)
            return
        from claim_artifacts import ClaimArtifactError, ClaimBaseMigrationRequired

        try:
            result = apply_table_review_decision(
                self.output_dir,
                table_id=table_id,
                expected_evidence_fingerprint=expected_fingerprint,
                role_mapping=role_mapping,
                actor=str(payload.get("actor") or "").strip() or None,
                reason=str(payload.get("reason") or "").strip(),
            )
        except TableReviewConflict as exc:
            self.send_json({
                "error": str(exc),
                "needs_reconfirmation": True,
                "evidence_fingerprint": exc.current_fingerprint,
            }, status=409)
            return
        except ClaimBaseMigrationRequired as exc:
            # Kimi 高危 #4：Claim 异常族继承 RuntimeError，旧 catch（ValueError/
            # OSError/TimeoutError）接不住 → 连接断、无 JSON 错误包。与 /claim-maintenance
            # 同口径映射结构化 503，提示重跑 atomize。
            self.send_json({
                "error": "base_migration_required",
                "detail": str(exc),
                "retryable": False,
            }, status=503)
            return
        except ClaimArtifactError as exc:
            self.send_json({"error": str(exc), "retryable": True}, status=503)
            return
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
            return
        except (OSError, TimeoutError) as exc:
            self.send_json({"error": str(exc), "retryable": True}, status=503)
            return
        self.send_json(result)

    def handle_translation(self) -> None:
        payload = self.read_json_body()
        if payload is None:
            return
        requirement_id = str(payload.get("requirement_id") or "").strip()
        text = str(payload.get("text") or "").strip()
        if not text:
            self.send_json({"error": "text is required"}, status=400)
            return
        try:
            translation = translate_requirement_text(text, requirement_id=requirement_id, output_dir=self.output_dir)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
            return
        except (LLMConnectionError, LLMResponseError) as exc:
            self.send_json({"error": str(exc)}, status=502)
            return
        self.send_json({
            "requirement_id": requirement_id,
            "translation": translation,
            "protected_codes": sorted(_protected_codes(text)),
        })

    def handle_changeset_report(self, params: dict[str, list[str]]) -> None:
        """WS-E E2: produce an added/obsolete/retained changeset from two outputs."""
        old_out_dir = one(params, "old_out_dir") or ""
        new_out_dir = one(params, "new_out_dir") or ""
        if not old_out_dir or not new_out_dir:
            self.send_json({"error": "old_out_dir and new_out_dir are required"}, status=400)
            return
        old_root = Path(old_out_dir).expanduser().resolve()
        new_root = Path(new_out_dir).expanduser().resolve()
        if not old_root.is_dir() or not new_root.is_dir():
            self.send_json({"error": "old_out_dir and new_out_dir must be existing directories"}, status=400)
            return
        try:
            old_blocks = read_jsonl(governed_artifact_path(old_root, "blocks.jsonl", for_write=False))
            new_blocks = read_jsonl(governed_artifact_path(new_root, "blocks.jsonl", for_write=False))
            old_requirements = read_jsonl(governed_artifact_path(old_root, "ai_requirements.jsonl", for_write=False))
            new_requirements = read_jsonl(governed_artifact_path(new_root, "ai_requirements.jsonl", for_write=False))
        except (OSError, ValueError) as exc:
            self.send_json({"error": f"Cannot read artifacts: {exc}", "retryable": False}, status=400)
            return

        def block_to_candidate(block: dict[str, Any]) -> dict[str, Any]:
            return {
                "section_id": str(block.get("block_id") or ""),
                "section_path": [str(s) for s in (block.get("section_path") or [])],
                "heading": str(block.get("section_path")[-1]) if block.get("section_path") else "",
                "text": str(block.get("text") or ""),
                "block_ids": [str(block.get("block_id") or "")],
            }

        old_chunks = [block_to_candidate(b) for b in old_blocks if b.get("text")]
        new_chunks = [block_to_candidate(b) for b in new_blocks if b.get("text")]
        report = desktop_tasks.build_requirement_changeset(
            old_requirements, new_requirements, old_chunks, new_chunks,
        )
        self.send_json(report)

    def handle_ai_review_action(self) -> None:
        payload = self.read_json_body()
        if payload is None:
            return
        req_id = str(payload.get("ai_req_id") or "").strip()
        status = str(payload.get("status") or "").strip()
        clear_module_override = payload.get("clear_module_override", False)
        if not isinstance(clear_module_override, bool):
            self.send_json({"error": "clear_module_override must be boolean"}, status=400)
            return
        module_override_supplied = "module_override" in payload
        if clear_module_override and module_override_supplied:
            self.send_json({"error": "module_override and clear_module_override are mutually exclusive"}, status=400)
            return
        submitted_module_override: str | None = None
        if module_override_supplied:
            try:
                submitted_module_override = normalize_module_override(payload.get("module_override"))
            except ValueError as exc:
                self.send_json({"error": str(exc)}, status=400)
                return
        ownership_override = str(payload.get("ownership_override") or "").strip() or None
        reason = str(payload.get("reason") or "").strip()
        actor = str(payload.get("actor") or "").strip() or None
        if not req_id or not status:
            self.send_json({"error": "ai_req_id and status are required"}, status=400)
            return
        expected_target_fingerprint = str(
            payload.get("expected_target_fingerprint") or ""
        ).strip()
        expected_target_publication_revision = str(
            payload.get("expected_target_publication_revision") or ""
        ).strip()
        expected_target_authority_write_revision = str(
            payload.get("expected_target_authority_write_revision") or ""
        ).strip()
        if (
            not expected_target_fingerprint
            or not expected_target_publication_revision
            or not expected_target_authority_write_revision
        ):
            self.send_json({
                "error": (
                    "expected_target_fingerprint, expected_target_publication_revision, and "
                    "expected_target_authority_write_revision are required"
                ),
                "needs_reconfirmation": True,
            }, status=400)
            return
        submitted_source = str(payload.get("source_fingerprint") or "").strip()
        submitted_subject = str(payload.get("review_subject_fingerprint") or "").strip()
        if not submitted_source or not submitted_subject:
            self.send_json({
                "error": "source and review subject fingerprints are required",
                "needs_reconfirmation": True,
            }, status=400)
            return
        current_cas: dict[str, str] = {}
        try:
            from omission_actions import OmissionConflictError, extraction_operation_lock

            # Target publication and authority append share this outer lease. All
            # target-dependent values are recomputed while the lease is held.
            with extraction_operation_lock(self.output_dir, operation="ai-review-action"):
                current = find_current_ai_requirement(self.output_dir, req_id)
                if current is None:
                    self.send_json({
                        "error": "AI requirement is not present in the current run"
                    }, status=409)
                    return
                current_cas = {
                    "target_fingerprint": str(current.get("target_fingerprint") or ""),
                    "target_publication_revision": str(
                        current.get("target_publication_revision") or ""
                    ),
                    "target_authority_write_revision": str(
                        current.get("target_authority_write_revision") or ""
                    ),
                }
                current_review_state = current.get("review_state")
                if not isinstance(current_review_state, dict) or current.get("needs_reconfirmation"):
                    current_review_state = {}
                if clear_module_override:
                    module_override = None
                elif module_override_supplied:
                    module_override = submitted_module_override
                else:
                    existing_module = current_review_state.get("module_override")
                    module_override = normalize_module_override(existing_module) if existing_module else None
                current_source_fingerprint = (
                    str(current.get("source_fingerprint") or "") or source_fingerprint(current)
                )
                current_subject_fingerprint = (
                    str(current.get("review_subject_fingerprint") or "")
                    or review_subject_fingerprint(current)
                )
                if (
                    submitted_source != current_source_fingerprint
                    or submitted_subject != current_subject_fingerprint
                    or expected_target_fingerprint
                    != current_cas["target_fingerprint"]
                    or expected_target_publication_revision
                    != current_cas["target_publication_revision"]
                    or expected_target_authority_write_revision
                    != current_cas["target_authority_write_revision"]
                ):
                    self.send_json({
                        "error": "AI requirement changed; refresh before adjudicating",
                        "needs_reconfirmation": True,
                        "source_fingerprint": current_source_fingerprint,
                        "review_subject_fingerprint": current_subject_fingerprint,
                        **current_cas,
                    }, status=409)
                    return
                state = apply_ai_review_action(
                    self.output_dir,
                    req_id,
                    status,
                    module_override=module_override,
                    ownership_override=ownership_override,
                    reason=reason,
                    actor=actor,
                    source_fingerprint_value=current_source_fingerprint,
                    review_subject_fingerprint_value=current_subject_fingerprint,
                    review_anchor_fingerprint_value=review_anchor_fingerprint(current),
                    expected_target_authority_write_revision=(
                        expected_target_authority_write_revision
                    ),
                )
                next_authority_write_revision = str(
                    state.get("target_authority_write_revision") or ""
                )
                state.update(current_cas)
                state["target_authority_write_revision"] = (
                    next_authority_write_revision
                )
        except OmissionConflictError as exc:
            self.send_json({"error": str(exc), "retryable": True}, status=409)
            return
        except AIReviewAuthorityConflict as exc:
            self.send_json({
                "error": str(exc),
                "needs_reconfirmation": True,
                **current_cas,
                "target_authority_write_revision": exc.current_revision,
            }, status=409)
            return
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=409)
            return
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": str(exc), "retryable": True}, status=503)
            return
        # 裁决回流交付物：防抖合并重建（0714 批次二 S4）——连续裁决只重建一次,
        # POST 即刻返回;批注视图不读 merged,不受延迟影响。失败不影响裁决本身。
        if (self.output_dir / "ai_requirements.jsonl").exists():
            _rebuilder().schedule(self.output_dir)
            try:
                from adjudication_bank import resolve_bank_path, update_bank

                bank_path = resolve_bank_path()
                if bank_path is not None:
                    update_bank(bank_path, self.output_dir)
            except Exception as exc:  # 裁决已持久化；学习资产刷新失败不能把主操作报成失败
                LOGGER.warning("裁决样本库即时收割失败（忽略）：%s", exc)
        self.send_json(state)

    def handle_omission_action(self) -> None:
        payload = self.read_json_body()
        if payload is None:
            return
        from omission_actions import (
            OmissionConflictError,
            apply_omission_action,
            current_omission_candidate_ids,
            extraction_operation_lock,
        )
        omission_id = str(payload.get("omission_id") or "").strip()
        source_fingerprint_value = str(payload.get("source_fingerprint") or "").strip()
        block_id = str(payload.get("block_id") or "").strip()
        if not omission_id or not source_fingerprint_value:
            self.send_json({
                "error": "omission identity and source fingerprint are required",
                "needs_reconfirmation": True,
            }, status=409)
            return
        try:
            with extraction_operation_lock(self.output_dir, operation="omission-action"):
                if block_id not in current_omission_candidate_ids(self.output_dir):
                    raise OmissionConflictError(
                        "block is no longer an uncovered requirement candidate; refresh before adjudicating"
                    )
                state = apply_omission_action(
                    self.output_dir,
                    block_id=block_id,
                    omission_id=omission_id,
                    status=str(payload.get("status") or ""),
                    reason=str(payload.get("reason") or ""),
                    actor=str(payload.get("actor") or "").strip() or None,
                    expected_source_fingerprint=source_fingerprint_value,
                )
                requirements_path = self.output_dir / "ai_requirements.jsonl"
                if requirements_path.exists():
                    try:
                        from ai_extract import refresh_ai_extract_quality, refresh_consistency_report

                        requirements = read_jsonl(requirements_path)
                        refresh_ai_extract_quality(self.output_dir, requirements)
                        refresh_consistency_report(self.output_dir, requirements)
                    except (OSError, TimeoutError, ValueError) as exc:
                        LOGGER.warning("遗漏裁决已保存，但覆盖质量刷新失败：%s", exc)
        except OmissionConflictError as exc:
            self.send_json({"error": str(exc), "needs_reconfirmation": True}, status=409)
            return
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
            return
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": str(exc), "retryable": True}, status=503)
            return
        self.send_json(state)

    def handle_claim_adjudication(self) -> None:
        payload = self.read_json_body()
        if payload is None:
            return
        required_text = {
            name: str(payload.get(name) or "").strip()
            for name in (
                "claim_id",
                "claim_hash",
                "adjudication",
                "reason",
                "actor",
                "expected_claim_effective_revision",
            )
        }
        evidence = payload.get("evidence")
        supersedes = payload.get("supersedes_fact_hashes", [])
        if not all(required_text.values()):
            self.send_json({
                "error": "claim identity, adjudication, reason, actor, and expected revision are required"
            }, status=400)
            return
        if not isinstance(evidence, dict):
            self.send_json({"error": "evidence must be an object"}, status=400)
            return
        if not isinstance(supersedes, list) or not all(
            isinstance(value, str) for value in supersedes
        ):
            self.send_json({
                "error": "supersedes_fact_hashes must be an array of strings"
            }, status=400)
            return
        try:
            from claim_review_actions import (
                ClaimAdjudicationCasMismatch,
                ClaimReviewActionError,
                apply_claim_adjudication,
            )

            result = apply_claim_adjudication(
                self.output_dir,
                claim_id=required_text["claim_id"],
                claim_hash=required_text["claim_hash"],
                adjudication=required_text["adjudication"],
                reason=required_text["reason"],
                evidence=evidence,
                actor=required_text["actor"],
                expected_claim_effective_revision=required_text[
                    "expected_claim_effective_revision"
                ],
                supersedes_fact_hashes=supersedes,
                request_idempotency_key=str(
                    payload.get("request_idempotency_key") or ""
                ).strip() or None,
            )
        except ClaimAdjudicationCasMismatch as exc:
            current_revision = None
            try:
                from claim_artifacts import load_committed_effective_snapshot

                snapshot = load_committed_effective_snapshot(self.output_dir)
                current_revision = next(
                    (
                        row.get("claim_effective_revision")
                        for row in snapshot.get("effective_ledger") or []
                        if row.get("claim_id") == required_text["claim_id"]
                    ),
                    None,
                )
            except (OSError, ValueError):
                pass
            self.send_json({
                "error": str(exc),
                "needs_reconfirmation": True,
                "claim_effective_revision": current_revision,
            }, status=409)
            return
        except ClaimReviewActionError as exc:
            self.send_json({"error": str(exc)}, status=400)
            return
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": str(exc), "retryable": True}, status=503)
            return
        self.send_json(result)

    def handle_omission_reextract(self) -> None:
        payload = self.read_json_body()
        if payload is None:
            return
        from omission_actions import (
            OmissionConflictError,
            OmissionNoResultError,
            current_omission_candidate_ids,
            targeted_reextract,
        )
        focus_lines = payload.get("focus_lines")
        if focus_lines is not None and not isinstance(focus_lines, list):
            self.send_json({"error": "focus_lines must be an array"}, status=400)
            return
        omission_id = str(payload.get("omission_id") or "").strip()
        source_fingerprint_value = str(payload.get("source_fingerprint") or "").strip()
        block_id = str(payload.get("block_id") or "").strip()
        if not omission_id or not source_fingerprint_value:
            self.send_json({
                "error": "omission identity and source fingerprint are required",
                "needs_reconfirmation": True,
            }, status=409)
            return
        try:
            # Fast feedback before entering the targeted operation lease. targeted_reextract
            # repeats this check under the lease to close the extraction-generation race.
            if block_id not in current_omission_candidate_ids(self.output_dir):
                raise OmissionConflictError(
                    "block is no longer an uncovered requirement candidate; refresh before extracting"
                )
            result = targeted_reextract(
                self.output_dir,
                block_id=block_id,
                omission_id=omission_id,
                focus_lines=[str(value) for value in (focus_lines or [])],
                actor=str(payload.get("actor") or "").strip() or None,
                reason=str(payload.get("reason") or ""),
                route=str(payload.get("route") or "openai_compatible"),
                expected_source_fingerprint=source_fingerprint_value,
            )
        except OmissionConflictError as exc:
            self.send_json({
                "error": str(exc),
                "retryable": True,
                "needs_reconfirmation": True,
            }, status=409)
            return
        except OmissionNoResultError as exc:
            self.send_json({"error": str(exc), "retryable": False}, status=422)
            return
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
            return
        except (LLMConnectionError, LLMResponseError) as exc:
            self.send_json({"error": str(exc), "retryable": True}, status=502)
            return
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": str(exc), "retryable": True}, status=503)
            return
        self.send_json(result)

    def handle_claim_queue_execute(self) -> None:
        payload = self.read_json_body()
        if payload is None:
            return
        try:
            from claim_queue_execution import (
                ClaimQueueExecutionConflict,
                ClaimQueueExecutionRemoteError,
                ClaimQueueExecutionUnavailable,
                ClaimQueueExecutionUnprocessable,
                execute_claim_queue_proposal,
            )
            from claim_reextract_attempts import ClaimReextractAttemptError
            from omission_actions import OmissionConflictError

            result = execute_claim_queue_proposal(
                self.output_dir,
                proposal_id=str(payload.get("proposal_id") or "").strip(),
                expected_claim_effective_revision=str(
                    payload.get("expected_claim_effective_revision") or ""
                ).strip(),
                expected_ledger_state=str(
                    payload.get("expected_ledger_state") or ""
                ).strip(),
                actor=str(payload.get("actor") or "").strip(),
                allow_llm=payload.get("allow_llm") is True,
                route=str(payload.get("route") or "").strip(),
                maximum_calls=payload.get(
                    "maximum_calls", payload.get("max_calls", 0)
                ),
                total_token_budget=payload.get(
                    "total_token_budget", payload.get("max_total_tokens", 0)
                ),
                request_idempotency_key=str(
                    payload.get("request_idempotency_key") or ""
                ).strip(),
                expected_route_config_revision=(
                    str(
                        payload.get("expected_route_config_revision") or ""
                    ).strip()
                    or None
                ),
            )
        except ClaimQueueExecutionConflict as exc:
            self.send_json({
                "error": str(exc),
                "needs_reconfirmation": True,
                "retryable": False,
            }, status=409)
            return
        except ClaimQueueExecutionUnprocessable as exc:
            self.send_json({"error": str(exc), "retryable": False}, status=422)
            return
        except ClaimQueueExecutionRemoteError as exc:
            self.send_json({"error": str(exc), "retryable": True}, status=502)
            return
        except ClaimQueueExecutionUnavailable as exc:
            self.send_json({
                "error": str(exc),
                "retryable": True,
                **exc.result,
            }, status=503)
            return
        except ClaimReextractAttemptError as exc:
            self.send_json({
                "error": "claim_reextract_attempt_recovery_required",
                "detail": str(exc)[:1000],
                "retryable": True,
            }, status=503)
            return
        except OmissionConflictError as exc:
            # An omission CAS race is a conflict, never a malformed request:
            # it must not fall through to the ValueError -> 400 mapping.
            self.send_json({
                "error": str(exc),
                "needs_reconfirmation": True,
                "retryable": True,
            }, status=409)
            return
        except (TypeError, ValueError) as exc:
            self.send_json({"error": str(exc), "retryable": False}, status=400)
            return
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": str(exc), "retryable": True}, status=503)
            return
        self.send_json(result)

    def handle_claim_structural_override(self) -> None:
        from claim_artifacts import ClaimArtifactError
        from claim_review_actions import ClaimReviewActionError
        from claim_structural_operations import ClaimStructuralOperationError

        payload = self.read_json_body()
        if payload is None:
            return
        try:
            from claim_structural_overrides import (
                ClaimStructuralOverrideError,
                ClaimStructuralOverrideStale,
                confirm_structural_exclusion,
                confirm_structural_override,
            )

            common = {
                "claim_id": str(payload.get("claim_id") or "").strip(),
                "claim_hash": str(payload.get("claim_hash") or "").strip(),
                "expected_catalog_generation_id": str(
                    payload.get("expected_catalog_generation_id") or ""
                ).strip(),
                "expected_claim_effective_revision": str(
                    payload.get("expected_claim_effective_revision") or ""
                ).strip(),
                "prior_structural_reason": str(
                    payload.get("prior_structural_reason") or ""
                ).strip(),
                "actor": str(payload.get("actor") or "").strip(),
                "reason": str(payload.get("reason") or "").strip(),
                "request_idempotency_key": str(
                    payload.get("request_idempotency_key") or ""
                ).strip(),
            }
            decision = str(
                payload.get("decision") or "promote_to_claim"
            ).strip()
            if decision == "confirm_exclusion":
                if payload.get("operation_id") or payload.get("allow_llm") is True:
                    raise ClaimStructuralOverrideError(
                        "exclusion confirmation cannot resume or authorize LLM work"
                    )
                result = confirm_structural_exclusion(
                    self.output_dir,
                    **common,
                )
            elif decision == "promote_to_claim":
                result = confirm_structural_override(
                    self.output_dir,
                    **common,
                    allow_llm=payload.get("allow_llm"),
                    route=str(payload.get("route") or "").strip(),
                    verifier_max_calls=payload.get("verifier_max_calls", -1),
                    verifier_max_total_tokens=payload.get(
                        "verifier_max_total_tokens", -1
                    ),
                    operation_id=(
                        str(payload.get("operation_id") or "").strip() or None
                    ),
                    reconfirm_paid_work=payload.get(
                        "reconfirm_paid_work", False,
                    ),
                )
            else:
                raise ClaimStructuralOverrideError(
                    "unknown structural candidate decision"
                )
        except ClaimStructuralOverrideStale as exc:
            self.send_json({
                "error": str(exc),
                "needs_reconfirmation": True,
                "retryable": False,
            }, status=409)
            return
        except ClaimStructuralOverrideError as exc:
            self.send_json({"error": str(exc), "retryable": False}, status=400)
            return
        except ClaimStructuralOperationError as exc:
            self.send_json({
                "error": "claim_structural_operation_recovery_required",
                "detail": str(exc)[:1000],
                "retryable": True,
            }, status=503)
            return
        except ClaimReviewActionError as exc:
            # A torn or broken claim review-event log must surface as a structured
            # retryable 503. This endpoint never truncates or repairs event bytes;
            # explicit claim maintenance performs quarantining recovery.
            self.send_json({
                "error": "claim_review_event_recovery_required",
                "detail": str(exc)[:1000],
                "retryable": True,
            }, status=503)
            return
        except ClaimArtifactError as exc:
            self.send_json({
                "error": "claim_artifact_recovery_required",
                "detail": str(exc)[:1000],
                "retryable": True,
            }, status=503)
            return
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": str(exc), "retryable": True}, status=503)
            return
        if not result.get("ok") and result.get("status") == "rebuild_pending":
            self.send_json(result, status=503)
            return
        if not result.get("ok") and result.get("status") == "needs_reconfirmation":
            self.send_json(result, status=409)
            return
        self.send_json(result)

    def handle_claim_maintenance(self) -> None:
        from claim_artifacts import ClaimBaseMigrationRequired

        try:
            result = run_claim_startup_maintenance(self.output_dir)
        except ClaimBaseMigrationRequired as exc:
            # S11：陈旧 claim 产物协议——与 GET 视图同步的结构化 503
            self.send_json({
                "error": "base_migration_required",
                "detail": str(exc),
                "retryable": False,
            }, status=503)
            return
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": str(exc), "retryable": True}, status=503)
            return
        except Exception as exc:
            self.send_json({
                "error": f"claim maintenance failed: {exc}",
                "retryable": True,
            }, status=503)
            return
        if result.get("ok") is False and result.get("error") == "base_migration_required":
            self.send_json({
                **result,
                "detail": "base_migration_required：claim 基底版本陈旧，请重跑 atomize",
                "retryable": False,
            }, status=503)
            return
        # Kimi #3 跟进：claim 维护成功后顺带重试 ready+recompute_error 的表（与启动同口径）。
        try:
            recovery = run_table_review_recompute_recovery(self.output_dir)
        except Exception:
            recovery = {"ok": False}
        if result.get("ok") and recovery.get("ok") and (
            recovery.get("recovered") or recovery.get("still_failing")
        ):
            result["table_recompute_recovery"] = recovery
        self.send_json(result)

    def handle_spot_extract(self) -> None:
        """点解析（WP-B）：批注视图单行/单块定向解析，draft 进澄清待确认。

        LLM 不可用响亮报错（ok:false + 503），绝不伪造 stub 抽取结果；
        无 LLM 配置时按钮不隐藏、点击返回真实错误（冻结口径）。"""
        payload = self.read_json_body()
        if payload is None:
            return
        from omission_actions import OmissionConflictError
        from spot_extract import SpotExtractUnavailableError, spot_extract
        block_id = str(payload.get("block_id") or "").strip()
        if not block_id:
            self.send_json({"ok": False, "error": "block_id is required"}, status=400)
            return
        row_index = payload.get("row_index")
        if row_index is not None:
            try:
                row_index = int(row_index)
            except (TypeError, ValueError):
                self.send_json({"ok": False, "error": "row_index must be an integer"}, status=400)
                return
        cell_id = str(payload.get("cell_id") or "").strip() or None
        try:
            result = spot_extract(
                self.output_dir,
                block_id=block_id,
                row_index=row_index,
                cell_id=cell_id,
                route=str(payload.get("route") or "openai_compatible"),
                actor=str(payload.get("actor") or "").strip() or None,
                reason=str(payload.get("reason") or ""),
            )
        except OmissionConflictError as exc:
            self.send_json({"ok": False, "error": str(exc), "retryable": True,
                            "needs_reconfirmation": True}, status=409)
            return
        except SpotExtractUnavailableError as exc:
            self.send_json({"ok": False, "error": str(exc), "retryable": False}, status=503)
            return
        except ValueError as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)
            return
        except (LLMConnectionError, LLMResponseError) as exc:
            self.send_json({"ok": False, "error": str(exc), "retryable": True}, status=502)
            return
        except (TimeoutError, OSError) as exc:
            self.send_json({"ok": False, "error": str(exc), "retryable": True}, status=503)
            return
        self.send_json({"ok": True, **result})

    def handle_clarification_check_batch(self) -> None:
        payload = self.read_json_body()
        if payload is None:
            return
        checks = payload.get("checks")
        if not isinstance(checks, list):
            self.send_json({"error": "checks must be an array"}, status=400)
            return
        from clarification_report import batch_apply_internal_checks
        from omission_actions import OmissionConflictError
        try:
            result = batch_apply_internal_checks(
                self.output_dir,
                [row for row in checks if isinstance(row, dict)],
                action=str(payload.get("action") or "verified_ok"),
                actor=str(payload.get("actor") or "").strip() or None,
                note=str(payload.get("note") or ""),
            )
        except OmissionConflictError as exc:
            self.send_json({
                "error": str(exc),
                "retryable": True,
                "needs_reconfirmation": True,
            }, status=409)
            return
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
            return
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": str(exc), "retryable": True}, status=503)
            return
        self.send_json(result)

    def handle_verification_states_get(self) -> None:
        """WS4：读全部 verification 覆盖记录（含四态生命周期）。只读，不发布。

        T3-2 CAS 分桶：每条 state 经当前需求索引重绑 ``evidence_fingerprint`` 为**结构指纹**
        （客户端 round-trip 它，避免旧记录残留的组合指纹造成首次保存假 409），并附
        ``narrative_drift_hint``（叙述变化、状态未吊销的复核提示）——UI 各归各类报告。
        """
        from requirements_analysis_rules import load_requirement_index
        from review_state import read_verification_states
        try:
            states = read_verification_states(self.output_dir)
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": "verification_state_unavailable", "detail": str(exc),
                            "retryable": True}, status=503)
            return
        try:
            index = load_requirement_index(self.output_dir)
        except (TimeoutError, OSError):
            index = {}
        served = []
        for rid, record in states.items():
            entry = index.get(rid)
            view = dict(record)
            if entry is not None:
                # 重绑为当前结构指纹（CAS 闸 token）；保留落盘值于 evidence_fingerprint_stored 供审计
                view["evidence_fingerprint_stored"] = view.get("evidence_fingerprint")
                view["evidence_fingerprint"] = str(entry.get("fingerprint") or view.get("evidence_fingerprint") or "")
                current_narrative = str(entry.get("narrative_fingerprint") or "")
                prior_narrative = str(record.get("narrative_fingerprint") or "")
                view["narrative_drift_hint"] = bool(
                    current_narrative and prior_narrative and current_narrative != prior_narrative
                )
            else:
                view["narrative_drift_hint"] = bool(view.get("narrative_drift_hint"))
            served.append(view)
        self.send_json({"schema": "verification-states/v1", "states": served,
                        "total": len(served)})

    def handle_functional_requirements_get(self) -> None:
        """WS-F：读 functional_requirements.json items（governed 双路径探测）。只读。

        envelope 与既有 GET 端点同构（schema/数据/total/错误面）。前端 HTTP 优先、
        无此端点的旧后端经 Electron readArtifact IPC 降级兜底。
        """
        from requirements_analysis_rules import read_functional_requirements
        try:
            items = read_functional_requirements(self.output_dir)
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": "functional_requirements_unavailable", "detail": str(exc),
                            "retryable": True}, status=503)
            return
        self.send_json({"schema": "functional-requirements/v1", "items": items,
                        "total": len(items)})

    def handle_manual_requirements_get(self) -> None:
        """WS-F：读 manual_requirements.jsonl（手工建需求记录）。只读。"""
        from review_state import read_manual_requirements
        try:
            items = read_manual_requirements(self.output_dir)
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": "manual_requirements_unavailable", "detail": str(exc),
                            "retryable": True}, status=503)
            return
        self.send_json({"schema": "manual-requirements/v1", "items": items,
                        "total": len(items)})

    def handle_lifecycle_events_get(self) -> None:
        """WS-F：读 requirement_lifecycle_events.jsonl（append-only 生命周期事件流）。只读。"""
        from review_state import read_lifecycle_events
        try:
            events = read_lifecycle_events(self.output_dir)
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": "lifecycle_events_unavailable", "detail": str(exc),
                            "retryable": True}, status=503)
            return
        self.send_json({"schema": "requirement-lifecycle-events/v1", "events": events,
                        "total": len(events)})

    def handle_dependency_candidates_get(self) -> None:
        """WS4：确定性依赖/父子候选推荐（含已裁决状态）。只读。"""
        try:
            from desktop_tasks import recommend_dependencies_task
            result = recommend_dependencies_task(self.output_dir)
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": "dependency_candidates_unavailable", "detail": str(exc),
                            "retryable": True}, status=503)
            return
        self.send_json(result)

    def handle_rtm_edges_get(self) -> None:
        """T3-1：回放 RTM 边事件流 → 当前边态（accept 落边 / reject 留记录）。只读。"""
        from review_state import read_rtm_edge_events, replay_rtm_edges
        try:
            replay = replay_rtm_edges(read_rtm_edge_events(self.output_dir))
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": "rtm_edges_unavailable", "detail": str(exc),
                            "retryable": True}, status=503)
            return
        self.send_json(replay)

    def handle_requirement_library_search(self, params: dict) -> None:
        """WS4/WS-C3：历史相似需求召回。配置三库任一即走统一检索；仅配 requirement_library 走旧单库路径。"""
        query = (params.get("q") or params.get("query") or [""])[0]
        limit_raw = (params.get("limit") or ["20"])[0]
        try:
            limit = max(1, min(100, int(limit_raw)))
        except ValueError:
            limit = 20
        req_lib = os.environ.get("RATOMIZER_REQUIREMENT_LIBRARY", "").strip()
        base_lib = os.environ.get("RATOMIZER_BASE_LIBRARY", "").strip()
        sol_lib = os.environ.get("RATOMIZER_SOLUTION_LIBRARY", "").strip()
        if not req_lib and not base_lib and not sol_lib:
            self.send_json({"schema": "requirement-search/v1", "query": query,
                            "matches": 0, "results": [],
                            "note": "未配置任何需求库（REQUIREMENT_LIBRARY / BASE_LIBRARY / SOLUTION_LIBRARY）"})
            return
        try:
            from desktop_tasks import search_requirements_task, unified_search_requirements_task
            if req_lib and not base_lib and not sol_lib:
                # 仅配旧库：保持原契约
                result = search_requirements_task(Path(req_lib), query, limit=limit)
            else:
                result = unified_search_requirements_task(query, limit=limit)
        except FileNotFoundError as exc:
            self.send_json({"error": "requirement_library_missing", "detail": str(exc)}, status=404)
            return
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": "requirement_search_unavailable", "detail": str(exc),
                            "retryable": True}, status=503)
            return
        self.send_json(result)

    def handle_verification_action(self) -> None:
        """WS4：写入 verification 覆盖（reviewer_override 通道 + CAS + 状态机前进迁移）。"""
        from requirement_schema import normalize_verification
        from requirements_analysis_rules import apply_verification_override
        from review_state import VerificationStateConflict
        payload = self.read_json_body()
        if payload is None:
            return
        requirement_id = str(payload.get("requirement_id") or "").strip()
        if not requirement_id:
            self.send_json({"error": "requirement_id is required"}, status=400)
            return
        verification = normalize_verification(payload.get("verification") or payload)
        actor = str(payload.get("actor") or "").strip() or "api-verification"
        expected = payload.get("expected_evidence_fingerprint")
        try:
            record = apply_verification_override(
                self.output_dir, requirement_id, verification, actor=actor,
                expected_evidence_fingerprint=str(expected) if expected is not None else None)
        except VerificationStateConflict as exc:
            self.send_json({"error": "verification_conflict", "detail": str(exc),
                            "requirement_id": exc.requirement_id,
                            "current_evidence_fingerprint": exc.current_fingerprint,
                            "needs_reconfirmation": True}, status=409)
            return
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
            return
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": "verification_state_unavailable", "detail": str(exc),
                            "retryable": True}, status=503)
            return
        self.send_json({"requirement_id": requirement_id,
                        "verification": record.get("verification"),
                        "lifecycle_state": record.get("lifecycle_state"),
                        # S1-6：回传最新 evidence_fingerprint（与 GET /verification-states 行内字段同名），
                        # 让前端保存成功后同步本地行指纹——否则第二次保存必携旧（空）指纹→假 409。
                        "evidence_fingerprint": record.get("evidence_fingerprint"),
                        "written": ["verification_states.jsonl"]})

    def handle_requirement_rollback(self) -> None:
        """WS4：人工回退需求生命周期（唯一使状态下落的路径；回退事件 append-only 留痕）。"""
        from requirements_analysis_rules import rollback_requirement_lifecycle
        payload = self.read_json_body()
        if payload is None:
            return
        requirement_id = str(payload.get("requirement_id") or "").strip()
        target = str(payload.get("target") or payload.get("target_state") or "").strip()
        actor = str(payload.get("actor") or "").strip()
        reason = str(payload.get("reason") or "").strip()
        if not requirement_id or not target or not actor or not reason:
            self.send_json({"error": "requirement_id/target/actor/reason 均必填"}, status=400)
            return
        try:
            record = rollback_requirement_lifecycle(self.output_dir, requirement_id, target,
                                                    actor=actor, reason=reason)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
            return
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": "verification_state_unavailable", "detail": str(exc),
                            "retryable": True}, status=503)
            return
        self.send_json({"requirement_id": requirement_id,
                        "lifecycle_state": record.get("lifecycle_state"),
                        "written": ["verification_states.jsonl", "requirement_lifecycle_events.jsonl"]})

    def handle_manual_requirement(self) -> None:
        """WS4：手工建需求入口（provenance=manual，追溯列留空不伪引）。"""
        from requirements_analysis_rules import record_manual_requirement
        payload = self.read_json_body()
        if payload is None:
            return
        objective = str(payload.get("objective") or "").strip()
        if not objective:
            self.send_json({"error": "objective is required"}, status=400)
            return
        behaviors = payload.get("behaviors") or []
        if not isinstance(behaviors, list):
            behaviors = [behaviors]
        try:
            record = record_manual_requirement(
                self.output_dir, objective=objective,
                behaviors=[str(b).strip() for b in behaviors if str(b).strip()],
                module=str(payload.get("module") or "").strip(),
                ownership=str(payload.get("ownership") or "").strip(),
                priority=str(payload.get("priority") or "P1").strip(),
                notes=str(payload.get("notes") or "").strip(),
                actor=str(payload.get("actor") or "api-manual").strip())
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": "manual_requirement_unavailable", "detail": str(exc),
                            "retryable": True}, status=503)
            return
        self.send_json({"functional_requirement_id": record.get("functional_requirement_id"),
                        "written": ["manual_requirements.jsonl"]})

    def handle_dependency_decision(self) -> None:
        """WS4：依赖候选裁决（接受才写库，拒绝不落库）。"""
        from requirement_schema import DEPENDENCY_KINDS
        from requirements_analysis_rules import apply_dependency_decision
        payload = self.read_json_body()
        if payload is None:
            return
        frm = str(payload.get("from") or "").strip()
        to = str(payload.get("to") or "").strip()
        kind = str(payload.get("kind") or "").strip()
        if not frm or not to or kind not in DEPENDENCY_KINDS:
            self.send_json({"error": f"from/to 必填，kind 必须为 {DEPENDENCY_KINDS}"}, status=400)
            return
        accepted = bool(payload.get("accept", payload.get("accepted", True)))
        try:
            result = apply_dependency_decision(
                self.output_dir, {"from": frm, "to": to, "kind": kind}, accepted=accepted,
                actor=str(payload.get("actor") or "api-dependency").strip(),
                reason=str(payload.get("reason") or "").strip())
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": "dependency_decision_unavailable", "detail": str(exc),
                            "retryable": True}, status=503)
            return
        self.send_json(result)

    def handle_requirement_library_adopt(self) -> None:
        """WS-F：需求库「采纳」——历史条目归属/模块套用到目标功能需求。

        经既有 reviewer_override 通道（verification_states.jsonl）留痕，actor/reason 必填。
        不新造写路径（复用 apply_requirement_library_adoption → upsert_verification_state）。
        """
        from requirements_analysis_rules import apply_requirement_library_adoption
        payload = self.read_json_body()
        if payload is None:
            return
        requirement_id = str(
            payload.get("requirement_id") or payload.get("functional_requirement_id") or ""
        ).strip()
        actor = str(payload.get("actor") or "").strip()
        reason = str(payload.get("reason") or "").strip()
        if not requirement_id:
            self.send_json({"error": "requirement_id is required"}, status=400)
            return
        if not actor or not reason:
            self.send_json({"error": "actor and reason are required (reviewer_override 留痕)"},
                           status=400)
            return
        try:
            record = apply_requirement_library_adoption(
                self.output_dir, requirement_id,
                ownership=str(payload.get("ownership") or "").strip(),
                module=str(payload.get("module") or "").strip(),
                actor=actor, reason=reason)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
            return
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": "requirement_library_adopt_unavailable", "detail": str(exc),
                            "retryable": True}, status=503)
            return
        self.send_json({
            "requirement_id": requirement_id,
            "ownership_override": record.get("ownership_override", ""),
            "module_override": record.get("module_override", ""),
            "written": ["verification_states.jsonl"],
        })

    def handle_adjudications_get(self) -> None:
        """WS-B：读取功能需求级 AI 裁决结果。"""
        from adjudicate import read_adjudication_results
        try:
            rows = read_adjudication_results(self.output_dir)
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": "adjudication_unavailable", "detail": str(exc),
                            "retryable": True}, status=503)
            return
        self.send_json({"schema": "adjudications/v1", "items": rows, "total": len(rows)})

    def handle_adjudication_summary_get(self) -> None:
        """WS-B：读取裁决摘要（开关状态、计数、校准状态）。"""
        from adjudicate import adjudication_summary
        try:
            summary = adjudication_summary(self.output_dir)
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": "adjudication_unavailable", "detail": str(exc),
                            "retryable": True}, status=503)
            return
        self.send_json(summary)

    def handle_adjudication_run(self) -> None:
        """WS-B：运行 AI 裁决（默认关；LLM 不可用时全部进 review）。"""
        from adjudicate import adjudicate_all
        payload = self.read_json_body() or {}
        route = str(payload.get("route") or "").strip() or None
        actor = str(payload.get("actor") or "api-adjudicator").strip()
        try:
            summary = adjudicate_all(self.output_dir, route=route, actor=actor)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
            return
        except AdjudicationUnavailableError as exc:
            self.send_json({"error": "adjudication_unavailable", "detail": str(exc),
                            "ok": False}, status=503)
            return
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": "adjudication_unavailable", "detail": str(exc),
                            "retryable": True}, status=503)
            return
        self.send_json({"ok": True, **summary})

    def handle_adjudication_overturn(self) -> None:
        """WS-B：人工推翻自动裁决结果（actor/reason 必填，append-only 留痕）。"""
        from adjudicate import overturn_adjudication
        payload = self.read_json_body()
        if payload is None:
            return
        rid = str(payload.get("functional_requirement_id") or "").strip()
        new_decision = str(payload.get("new_decision") or "").strip()
        actor = str(payload.get("actor") or "").strip()
        reason = str(payload.get("reason") or "").strip()
        if not rid or not new_decision or not actor or not reason:
            self.send_json({"error": "functional_requirement_id/new_decision/actor/reason 均必填"}, status=400)
            return
        try:
            record = overturn_adjudication(
                self.output_dir, rid, new_decision=new_decision, actor=actor, reason=reason)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
            return
        except (TimeoutError, OSError) as exc:
            self.send_json({"error": "adjudication_unavailable", "detail": str(exc),
                            "retryable": True}, status=503)
            return
        self.send_json({"ok": True, "record": record, "written": ["adjudication_results.jsonl"]})

    def read_json_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json({"error": "invalid content length"}, status=400)
            return None
        try:
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json({"error": "invalid json body"}, status=400)
            return None
        if not isinstance(payload, dict):
            self.send_json({"error": "json body must be an object"}, status=400)
            return None
        return payload

    def send_file_json(self, filename: str) -> None:
        path = self.output_dir / filename
        if not path.exists():
            self.send_error(404, f"Missing file: {filename}")
            return
        self.send_json(json.loads(path.read_text(encoding="utf-8")))

    def send_json(self, payload, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_cors_headers(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin and is_allowed_origin(origin, self.allowed_origins):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        elif "null" in self.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", "null")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", f"Content-Type, {TOKEN_HEADER}")

    def log_message(self, format: str, *args) -> None:
        return


def one(params: dict[str, list[str]], name: str) -> str:
    values = params.get(name) or [""]
    return values[0]


def parse_int(value: str, *, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def parse_claim_page_value(
    value: str,
    *,
    name: str,
    kind: str,
    default: int,
) -> int:
    """Parse the strict pagination contract used by all Claim Ledger GETs.

    ``kind`` ("limit" | "offset") drives validation; ``name`` is only the
    query field echoed in error messages.
    """
    if not value:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid claim {name}") from exc
    if kind == "limit":
        if not 1 <= parsed <= 500:
            raise ValueError(f"claim {name} must be between 1 and 500")
    elif kind == "offset":
        if parsed < 0:
            raise ValueError(f"claim {name} must be non-negative")
    else:  # pragma: no cover - internal programming error
        raise ValueError(f"unknown claim pagination kind: {kind}")
    return parsed


def is_allowed_origin(origin: str, allowed_origins: set[str]) -> bool:
    if not origin:
        return True
    if origin == "file://" or origin.startswith("file://"):
        return True
    return origin in allowed_origins


def token_is_valid(expected_token: str, headers: Mapping[str, str], params: dict[str, list[str]]) -> bool:
    if not expected_token:
        return True
    header_token = headers.get(TOKEN_HEADER, "")
    # 常量时间比较，避免字符串 == 短路造成的时序侧信道（token 是 server-wide 长期令牌）。
    # compare_digest 仅接受 ASCII/bytes，统一按 UTF-8 编码。
    try:
        return hmac.compare_digest(header_token.encode("utf-8"), expected_token.encode("utf-8"))
    except (UnicodeEncodeError, TypeError):
        return False


def enrich_requirements(requirements: list[dict], output_dir: Path) -> list[dict]:
    reviews_by_requirement = index_by_requirement_identity(read_jsonl(output_dir / "llm_review_results.jsonl"))
    from review_state import read_review_authority_snapshot
    from claim_ledger import a_track_effective_authority

    review_snapshot = read_review_authority_snapshot(output_dir)
    states = list(review_snapshot.get("states") or [])
    states_by_requirement = index_by_requirement_identity(states)
    projection = a_track_effective_authority(requirements, states)
    projection_by_id = {
        (
            str(record.get("target_requirement_id") or ""),
            str(record.get("target_fingerprint") or ""),
        ): record
        for record in projection.get("records") or []
    }
    publication_revision = target_publication_revision(
        output_dir / "atomic_requirements.jsonl"
    )
    enriched: list[dict] = []
    for requirement in requirements:
        row = dict(requirement)
        for key in requirement_identity_keys(row):
            if key in reviews_by_requirement:
                row["review"] = reviews_by_requirement[key]
                break
        for key in requirement_identity_keys(row):
            if key in states_by_requirement:
                row["review_state"] = states_by_requirement[key]
                break
        from claim_ledger import atomic_requirement_id, atomic_target_fingerprint

        target_id = atomic_requirement_id(row)
        target_fingerprint = atomic_target_fingerprint(row)
        projected = projection_by_id.get((target_id, target_fingerprint))
        if projected is not None:
            row["target_fingerprint"] = target_fingerprint
            row["target_publication_revision"] = publication_revision
            row["target_review_revision"] = (
                projected.get("review", {}).get("target_review_revision")
            )
            row["target_authority_write_revision"] = atomic_target_authority_write_revision(
                target_id,
                review_snapshot,
            )
        enriched.append(row)
    return enriched


_BLOCK_FIELDS = ("block_id", "order", "type", "text", "section_path",
                 "page_number", "requirement_like", "noise", "doc_region",
                 "raw_text", "text_repaired", "text_repair_checked", "text_repair_version",
                 "text_repairs", "text_repair_words_before", "text_repair_words_after",
                 "text_repair_candidates_before", "text_repair_candidates_after",
                 # 表格块渲染真表格所需（旧 blocks.jsonl 无这些字段 → None，前端回退扁平文字）
                 "table_title", "table_source", "header_rows", "data_rows",
                 # 物理行坐标（v15）：thead/title 行 cell 按钮与合并跨度 DOM 渲染的
                 # 物理定位（cell_context 是物理 R×C，data_rows 是数据区序号）
                 "title_row_indexes", "header_row_indexes",
                 # 行级渲染的表头（v12 行热区/行卡/v13 行区切片都要 _row_render_line(headers)——
                 # 缺它时行文本为空,行几何与行卡静默全灭,STO 实证）
                 "headers")

# 块级中文翻译缓存（内容哈希键,仅由真 LLM 写入;详见 doc_annotation_export 的生成侧）。
# 键函数与加载器放这里作为唯一实现——批注导出与本 API 两个渲染面共用,防分叉。
ANNOTATION_TRANSLATIONS = "annotation_translations.json"
ANNOTATION_TRANSLATION_GUARDS_VERSION = "annotation-translation-guards-v1"


def translation_key(text: object) -> str:
    import hashlib
    return hashlib.sha1(" ".join(str(text or "").split()).encode("utf-8")).hexdigest()


def load_annotation_translations(output_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Load only translations already validated by the current anti-drift guards."""
    try:
        path = governed_artifact_path(
            output_dir, ANNOTATION_TRANSLATIONS, category="cache"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, {}
    items = data.get("items") if isinstance(data, dict) else None
    translations: dict[str, str] = {}
    notes: dict[str, str] = {}
    if isinstance(items, dict):
        for key, entry in items.items():
            if not isinstance(entry, dict):
                continue
            if entry.get("guards_version") != ANNOTATION_TRANSLATION_GUARDS_VERSION:
                continue
            translation = str(entry.get("translation") or "").strip()
            if translation and not entry.get("rejected"):
                translations[str(key)] = translation
            elif entry.get("rejected"):
                notes[str(key)] = str(entry.get("reason") or "翻译未通过防幻觉校验")
    return translations, notes


def build_document_blocks(output_dir: Path) -> dict:
    """供文档批注视图（源文件签名 memo,见 _memoized）。"""
    resolved = Path(output_dir).expanduser().resolve()
    payload = _memoized("document", resolved, _DOC_MEMO_SOURCES,
                        lambda: _build_document_blocks_impl(resolved))
    payload["module_vocabulary"] = _review_module_vocabulary()
    return payload


def _review_module_vocabulary() -> list[str]:
    from ai_extract import MODULE_VOCAB
    from adjudication_bank import load_bank, module_vocabulary, resolve_bank_path

    custom = module_vocabulary(load_bank(resolve_bank_path()))
    return list(dict.fromkeys([str(value) for value in MODULE_VOCAB] + custom))


def _build_document_blocks_impl(output_dir: Path) -> dict:
    """blocks 按 order 排序、只留渲染需要的字段（去掉 kb_matches 等重负载）。

    附带块级中文翻译（内容哈希查缓存）：未覆盖段/说明标记的三段式卡片（原因/翻译/引用）
    在应用内视图与导出 HTML 同语义。"""
    blocks = read_jsonl(output_dir / "blocks.jsonl")
    from merged_consistency import is_coverage_candidate
    from omission_actions import make_omission_id, omission_source_fingerprint
    from merged_consistency import covered_block_ids
    requirements = build_ai_requirements(output_dir)
    covered_ids = covered_block_ids(requirements, blocks)
    try:
        extract_quality = json.loads(
            (output_dir / "ai_extract_quality.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        extract_quality = {}
    if not isinstance(extract_quality, dict):
        raise ValueError("ai_extract_quality.json must contain a JSON object")
    failed_section_ids = [
        str(value) for value in (extract_quality.get("failed_section_ids") or [])
        if str(value)
    ]
    failed_block_ids = {
        str(value) for value in (extract_quality.get("failed_section_block_ids") or [])
        if str(value)
    }
    trimmed = []
    for b in blocks:
        row = {k: b.get(k) for k in _BLOCK_FIELDS}
        block_id = str(b.get("block_id") or "")
        block_text = str(b.get("text") or "")
        if block_id:
            row["omission_id"] = make_omission_id(block_id, block_text)
            row["omission_source_fingerprint"] = omission_source_fingerprint(block_id, block_text)
        # 覆盖/遗漏统一口径（E3b）：服务端算好,双渲染器与澄清清单同源消费
        row["coverage_candidate"] = is_coverage_candidate(b)
        row["covered_by_requirement"] = block_id in covered_ids
        row["extraction_failed"] = block_id in failed_block_ids
        trimmed.append(row)
    translations, notes = load_annotation_translations(output_dir)
    clean_block_text = None
    if translations or notes:
        # 键同源（0714 评审跟进）：导出侧写缓存的键 = 渲染清洗后文本的哈希;此前 API 只按
        # 原始文本取键,含 leader-dots/私用字形的块在应用内查不到译文（两评审面译文有无不一致）。
        # 惰性反向导入写侧的唯一权威实现（doc_annotation_export 顶层 import 本模块,函数级
        # 导入在运行期无环）;先按原始键查（旧缓存兼容）,未命中再按清洗键查。
        from doc_annotation_export import _clean_block_text as clean_block_text
    for block in trimmed:
        original_text = block.get("text")
        if translations or notes:
            keys = [translation_key(original_text)]
            if clean_block_text is not None:
                cleaned_key = translation_key(clean_block_text(str(original_text or "")))
                if cleaned_key != keys[0]:
                    keys.append(cleaned_key)
            for key in keys:
                if key in translations:
                    block["translation"] = translations[key]
                    break
                if key in notes:
                    block["translation_note"] = notes[key]
                    break
        block["text"] = normalize_text(original_text)
    trimmed.sort(key=lambda b: b.get("order") or 0)
    return {
        "blocks": trimmed,
        "count": len(trimmed),
        "failed_section_ids": failed_section_ids,
        "failed_section_block_ids": sorted(failed_block_ids),
    }


# 请求级重算备忘（0714 批次三 S7b）：GUI 每次刷新都全量重读+重 join（2000 块翻译匹配、
# 300 需求锚点/一致性/富化合并）,无任何进程内缓存。按源文件 (mtime_ns, size) 签名 memo：
# 裁决/翻译写入改动源文件 → 签名变化自然失效,无需显式失效钩子。命中返回 deepcopy
# （消费方可能原地改行——缓存本体绝不外借,防跨请求串改）。
import copy as _copy
import threading as _threading

_MEMO_LOCK = _threading.Lock()
_MEMO: dict[tuple[str, str], tuple[tuple, object]] = {}

_DOC_MEMO_SOURCES = ("blocks.jsonl", "annotation_translations.json", "ai_requirements.jsonl",
                     "merged_spec_requirements.json", "ai_requirements.meta.json",
                     "ai_review_states.jsonl", "functional_requirements.json",
                     "engineering_analysis.json", "consistency_report.json",
                     "ai_extract_quality.json")
_REQ_MEMO_SOURCES = ("merged_spec_requirements.json", "ai_requirements_doc.json",
                     "ai_requirements.jsonl", "ai_review_states.jsonl",
                     "functional_requirements.json", "engineering_analysis.json",
                     "consistency_report.json", "blocks.jsonl",
                     "ai_requirements.meta.json", "ai_requirements.partial.json")


def _source_signature(output_dir: Path, names: tuple[str, ...]) -> tuple:
    signature = []
    for name in names:
        path = governed_artifact_path(output_dir, name)
        try:
            st = path.stat()
            signature.append((name, st.st_mtime_ns, st.st_size))
        except OSError:
            signature.append((name, None, None))
    return tuple(signature)


def _memoized(kind: str, output_dir: Path, names: tuple[str, ...], builder):
    key = (kind, str(output_dir))
    signature = _source_signature(output_dir, names)
    with _MEMO_LOCK:
        hit = _MEMO.get(key)
        if hit is not None and hit[0] == signature:
            return _copy.deepcopy(hit[1])
    value = builder()
    with _MEMO_LOCK:
        _MEMO[key] = (signature, _copy.deepcopy(value))
    return value


def _reset_payload_memo() -> None:
    """仅测试用。"""
    with _MEMO_LOCK:
        _MEMO.clear()


_WS_RE = re.compile(r"\s+")


def _norm_text(s: object) -> str:
    return _WS_RE.sub(" ", str(s or "")).strip().lower()


def compute_echo_block_ids(req: dict, blocks: list[dict]) -> list[str]:
    """同文重复出现的回声锚点(视图层专用字段,**不进** source_block_ids 溯源数据)。

    真实案例(0715 电表招标):同一段产品描述在 Scope 与 3.1 各出现一次,条目锚在
    首次出现,批注视图里第二次出现无任何标注 → 用户以为整段没解析出。
    两条匹配路:① 引句互含(全剥空白底座——PDF 碎词两次出现拆点不同,保留空白的
    归一化对不上;引句 ≥30 字);② 锚点原文对原文近重复(原文两次出现本身就有措辞
    微差:"measurement of"↔"measuring",且 LLM 引句尾部意译时路①失效)——剥空白
    相等,或 J≥0.8+数字多重集守卫(真实文档全对探针:目标对 0.97/真重复 0.84 保住,
    0.72 的跨章节相似句排除)。防噪:参照块与候选块剥空白后均 ≥60 字;跳过噪声块
    与已在 source_block_ids/anchor 里的块。"""
    from merged_consistency import reliable_echo_block_ids

    return reliable_echo_block_ids(req, blocks)


def quote_matched_block_ids(
    req: dict,
    text_by_block: dict[str, str],
    *,
    noise_block_ids: set[str] | None = None,
) -> list[str]:
    """原句匹配块集：source_quote 在来源块上的确定性匹配全集（锚点只是首块）。

    视图层证据区应覆盖原句实际跨越的全部块——多段引句只亮首块会丢后半段
    （test5 实证：引句跨 097+098 两块，蓝区只亮 097，与原句左右不一致）。
    噪声块 id 随行：页码/水印夹缝不再掐死窗口匹配（test7 实证）。
    """
    noise = noise_block_ids or set()
    span = [str(b) for b in (req.get("source_block_ids") or [])]
    from merged_consistency import compact_source_text, match_source_quote_blocks

    source_blocks = [
        {"block_id": block_id, "order": order,
         "text": text_by_block.get(block_id, ""), "noise": block_id in noise}
        for order, block_id in enumerate(span)
    ]
    matched, _mapping = match_source_quote_blocks(req.get("source_quote"), source_blocks)
    return [str(b) for b in matched]


def anchor_block_id(
    req: dict,
    text_by_block: dict[str, str],
    *,
    noise_block_ids: set[str] | None = None,
) -> str:
    """需求精确锚点：含其 source_quote 原句的那一小段（段落级），否则回退 source_block_ids 首块。

    批注挂在需求实际所在的小段上（而非整章节段首），符合"一小段一个需求点"。
    """
    span = [str(b) for b in (req.get("source_block_ids") or [])]
    matched = quote_matched_block_ids(req, text_by_block, noise_block_ids=noise_block_ids)
    if matched:
        return matched[0]
    from merged_consistency import compact_source_text

    quote = compact_source_text(req.get("source_quote"))
    if quote:
        # LLM 引用偶有尾部偏差。保留旧的“含空格前 40 字”兜底，并额外支持 PDF
        # 词内空格漂移；两者都只决定锚点，不扩大覆盖判定。
        normalized_prefix = _norm_text(req.get("source_quote"))[:40]
        compact_prefix = quote[:30]
        if normalized_prefix or compact_prefix:
            for bid in span:
                block_text = text_by_block.get(bid, "")
                if (
                    normalized_prefix and normalized_prefix in _norm_text(block_text)
                ) or (
                    compact_prefix and compact_prefix in compact_source_text(block_text)
                ):
                    return bid
    return span[0] if span else ""


def _functional_membership(output_dir: Path) -> dict[str, dict]:
    path = output_dir / "functional_requirements.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return {}
    mapping: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        projected = {
            "functional_requirement_id": item.get("functional_requirement_id"),
            "functional_title": item.get("title"),
            "functional_objective": item.get("objective"),
            "functional_behaviors": item.get("behaviors") or [],
            "functional_preconditions": item.get("preconditions") or [],
            "functional_data_constraints": item.get("data_constraints") or [],
            "functional_variants": item.get("variants") or [],
            "functional_exceptions": item.get("exceptions") or [],
            "functional_related_dlms_objects": item.get("related_dlms_objects") or [],
            "functional_merge_method": item.get("merge_method"),
            "functional_merge_confidence": item.get("merge_confidence"),
            # 合并规模（0714 批次一）：单源"合并"显示置信是噪声,徽章只在 ≥2 源时出现
            "functional_source_count": len(item.get("source_ai_requirement_ids") or []),
            "functional_conflict_flags": item.get("conflict_flags") or [],
        }
        for source_id in item.get("source_ai_requirement_ids") or []:
            mapping[str(source_id)] = projected
    return mapping


def _analysis_enrichment(output_dir: Path) -> dict[str, dict]:
    """engineering_analysis.json → AIR id 一对多兼容投影（analysis_ 前缀）。

    当前批注视图不展示 LLM 叙述富化，但保留字段供既有 API 消费方和未来方案库接回。
    缺失/坏 JSON/异源 producer → 空 merge，裁决回流无需重建语义。"""
    path = output_dir / "engineering_analysis.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    producer = str((payload.get("provenance") or {}).get("producer") or payload.get("producer") or "")
    if producer and not producer.startswith(("requirements_analysis", "analyze")):
        import logging
        logging.getLogger("requirement_atomizer").warning(
            "engineering_analysis.json producer 异源（%s），批注视图不合并其内容", producer)
        return {}
    items = payload.get("items")
    if not isinstance(items, list):
        return {}
    mapping: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        projected: dict = {
            "analysis_id": item.get("analysis_id"),
            "analysis_source": item.get("analysis_source"),
            "analysis_software_requirement_text": str(item.get("software_requirement_text") or ""),
            "analysis_dev_guidance": [str(v) for v in item.get("developer_guidance") or []],
            "analysis_design_options": [str(v) for v in item.get("design_options") or []],
            "analysis_acceptance_criteria": [str(v) for v in item.get("acceptance_criteria") or []],
            "analysis_open_questions": [str(v) for v in item.get("open_questions") or []],
            "analysis_assumptions": [str(v) for v in item.get("assumptions") or []],
            "analysis_enrichment_warnings": [str(v) for v in item.get("enrichment_warnings") or []],
            "analysis_ownership": item.get("ownership"),
            "analysis_ownership_reason": str(item.get("ownership_reason") or ""),
            "analysis_ownership_source": item.get("ownership_source"),
            "analysis_ownership_reason_source": item.get("ownership_reason_source"),
        }
        if str(item.get("hardware_translation") or "").strip():
            projected["hardware_translation"] = item.get("hardware_translation")
            projected["hardware_summary"] = item.get("hardware_summary")
        # 一对多展开：functional 合并后一个分析 item 携带 N 条 AIR id,N 张批注卡
        # 共享同一份分析;重复 sid 首见者胜(items 按 analysis_id 有序,确定性)
        for source_id in item.get("source_requirement_ids") or []:
            mapping.setdefault(str(source_id), projected)
    return mapping


def build_ai_requirements(output_dir: Path) -> list[dict]:
    """供文档批注视图（源文件签名 memo,见 _memoized）。"""
    resolved = Path(output_dir).expanduser().resolve()
    return _memoized("ai-requirements", resolved, _REQ_MEMO_SOURCES,
                     lambda: _build_ai_requirements_impl(resolved))


def _build_ai_requirements_impl(output_dir: Path) -> list[dict]:
    """merged_spec 需求 + 内容稳定 ai_req_id + 精确锚点 + 当前裁决态。

    优先读 merged_spec_requirements.json（双引擎交付物），回退 ai_requirements_doc.json /
    ai_requirements.jsonl。anchor_block_id = 含 source_quote 的具体段落（段落级精确）。
    """
    if final_ai_requirements_are_stale(output_dir):
        return []
    source_path = next(
        (output_dir / name for name in (
            "ai_requirements.jsonl",
            "merged_spec_requirements.json",
            "ai_requirements_doc.json",
        ) if (output_dir / name).exists()),
        None,
    )
    return _enrich_ai_requirement_rows(
        output_dir, _load_ai_requirements(output_dir), freshness_reference=source_path,
    )


def _enrich_ai_requirement_rows(
    output_dir: Path,
    requirements: list[dict],
    *,
    freshness_reference: Path | None = None,
) -> list[dict]:
    """Apply the regular review-workspace projection to final or partial rows."""
    def artifact_is_current(name: str) -> bool:
        if freshness_reference is None:
            return True
        try:
            return (output_dir / name).stat().st_mtime_ns >= freshness_reference.stat().st_mtime_ns
        except OSError:
            return False

    from claim_ledger import b_track_effective_authority

    from ai_review_actions import read_ai_review_authority_snapshot

    review_snapshot = read_ai_review_authority_snapshot(output_dir)
    states = dict(review_snapshot.get("states") or {})
    authority_projection = b_track_effective_authority(requirements, states)
    projection_by_id = {
        (
            str(record.get("target_requirement_id") or ""),
            str(record.get("target_fingerprint") or ""),
        ): record
        for record in authority_projection.get("records") or []
    }
    publication_path = freshness_reference or (output_dir / "ai_requirements.jsonl")
    publication_revision = target_publication_revision(publication_path)
    membership = _functional_membership(output_dir) if artifact_is_current("functional_requirements.json") else {}
    analysis_map = _analysis_enrichment(output_dir) if artifact_is_current("engineering_analysis.json") else {}
    block_rows = read_jsonl(output_dir / "blocks.jsonl")
    text_by_block = {str(b.get("block_id")): (b.get("text") or "") for b in block_rows}
    # 噪声块 id 随行进锚点/原句匹配——页码/水印夹缝不再掐死窗口（test7 实证）
    noise_block_ids = {str(b.get("block_id")) for b in block_rows if b.get("noise")}
    from requirements_analysis_rules import classify_ownership  # 规则初判（确定性、零 LLM）
    dup_quotes, differ_codes = _consistency_markers(output_dir)

    enriched: list[dict] = []
    for req in requirements:
        row = dict(req)
        ensure_requirement_identity(row)
        rid = source_ai_requirement_id(req)
        state = review_state_for_requirement(row, states)
        row["ai_req_id"] = rid
        needs_reconfirmation = review_state_needs_reconfirmation(row, state)
        effective_state = None if needs_reconfirmation else state
        row.update(membership.get(rid, {}))
        row.update(analysis_map.get(rid, {}))   # 兼容保留；当前视图不消费富化叙述字段
        row["anchor_block_id"] = anchor_block_id(req, text_by_block, noise_block_ids=noise_block_ids)
        # 原句匹配块集（证据区应覆盖原句实际跨越的全部块，多段引句不只亮首块）；
        # 匹配不到时如实回退锚点单块。
        quote_block_ids = quote_matched_block_ids(
            req, text_by_block, noise_block_ids=noise_block_ids)
        row["quote_block_ids"] = (
            quote_block_ids or ([row["anchor_block_id"]] if row["anchor_block_id"] else [])
        )
        # 回声锚点(0715 电表招标实证:同文重复出现的第二处显示"未覆盖",用户误判整段没解析)
        row["echo_block_ids"] = compute_echo_block_ids(row, block_rows)
        row["review_state"] = state
        row["needs_reconfirmation"] = needs_reconfirmation
        # 专家改过模块则以 override 为准（module 字段保持原值供追溯）
        if effective_state and effective_state.get("module_override"):
            row["module_effective"] = effective_state["module_override"]
        else:
            row["module_effective"] = req.get("module") or (req.get("labels") or [None])[0]
        # 归属单源化（真实反馈 2026-07-12,test18）：视图层与分析层各判一次会分叉——
        # 视图规则判 hardware、分析层判 software 时,硬件卡拿不到翻译、理由却是软件论证。
        # 优先采用分析层判定（含 override 生效后的值,与 analysis_ownership_reason 同源）,
        # 无分析产物才回退规则兜底;review_state 的 override 仍是最终权威（effective 逻辑不动）。
        if not row.get("ownership") and str(row.get("analysis_ownership") or "").strip():
            row["ownership"] = str(row["analysis_ownership"])
            row.setdefault("ownership_reason", str(row.get("analysis_ownership_reason") or ""))
            row.setdefault("ownership_source", row.get("analysis_ownership_source"))
        if not row.get("ownership"):
            verdict = classify_ownership(req)
            row["ownership"] = verdict["ownership"]
            for key in ("ownership_reason", "ownership_source", "ownership_confidence"):
                row.setdefault(key, verdict.get(key))
        if effective_state and effective_state.get("ownership_override"):
            row["ownership_effective"] = effective_state["ownership_override"]
        else:
            row["ownership_effective"] = row["ownership"]
        row["status"] = (effective_state or {}).get("status") or "draft"
        from claim_artifacts import canonical_target_fingerprint

        target_fingerprint = canonical_target_fingerprint(
            row.get("review_subject_fingerprint")
            or review_subject_fingerprint(req)
        )
        projected = projection_by_id.get((rid, target_fingerprint))
        if projected is not None:
            row["target_fingerprint"] = target_fingerprint
            row["target_publication_revision"] = publication_revision
            row["target_review_revision"] = (
                projected.get("review", {}).get("target_review_revision")
            )
            row["target_authority_write_revision"] = ai_target_authority_write_revision(
                rid,
                review_snapshot,
            )
        flags = _row_consistency_flags(row, dup_quotes, differ_codes)
        if flags:
            row["consistency_flags"] = flags
        enriched.append(row)
    return enriched


def _read_ai_extraction_quality(output_dir: Path) -> dict | None:
    """Read the two legacy coverage metrics exposed by the status endpoint."""
    path = Path(output_dir) / "ai_extract_quality.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid ai_extract_quality.json: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("ai_extract_quality.json must contain a JSON object")

    quality: dict[str, float | int | None] = {}
    for field in ("coverage_pct", "core_coverage_pct"):
        value = payload.get(field)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError(f"ai_extract_quality.json {field} must be a finite number or null")
        quality[field] = value
    return quality


def build_ai_extraction_status(output_dir: Path) -> dict:
    """Return only the run-aware partial generation; never merge an older final file."""
    from ai_extract import (
        AI_PARTIAL_SCHEMA,
        AI_REQUIREMENTS_PARTIAL,
        extraction_input_fingerprint,
        read_partial_snapshot,
    )

    root = Path(output_dir).expanduser().resolve()
    quality = _read_ai_extraction_quality(root)
    partial_path = root / AI_REQUIREMENTS_PARTIAL
    partial = read_partial_snapshot(partial_path)
    current_input = extraction_input_fingerprint(root)
    if (partial is None
            or not current_input
            or str(partial.get("input_fingerprint") or "") != current_input):
        status = {
            "schema": AI_PARTIAL_SCHEMA,
            "run_id": None,
            "completed": 0,
            "total": 0,
            "complete": False,
            "failed": False,
            "rows": [],
        }
        if quality is not None:
            status["quality"] = quality
        return status
    status = {
        "schema": AI_PARTIAL_SCHEMA,
        "run_id": str(partial["run_id"]),
        "completed": int(partial.get("completed") or 0),
        "total": int(partial.get("total") or 0),
        "complete": bool(partial.get("complete")),
        "failed": bool(partial.get("failed")),
        "error": str(partial.get("error") or ""),
        "rows": _enrich_ai_requirement_rows(
            root,
            list(partial.get("rows") or []),
            freshness_reference=partial_path,
        ),
    }
    if quality is not None:
        status["quality"] = quality
    return status


def final_ai_requirements_are_stale(output_dir: Path) -> bool:
    """Reject a final result that belongs to an older ``blocks.jsonl`` generation."""
    from ai_extract import (
        AI_REQUIREMENTS,
        AI_REQUIREMENTS_META,
        AI_REQUIREMENTS_PARTIAL,
        extraction_input_fingerprint,
        read_partial_snapshot,
    )

    root = Path(output_dir).expanduser().resolve()
    current_input = extraction_input_fingerprint(root)
    meta_path = root / AI_REQUIREMENTS_META
    if meta_path.exists():
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return True
        return (
            not isinstance(metadata, dict)
            or metadata.get("schema") != "ai-requirements-final/v1"
            or not current_input
            or str(metadata.get("input_fingerprint") or "") != current_input
        )

    partial_path = root / AI_REQUIREMENTS_PARTIAL
    if partial_path.exists():
        partial = read_partial_snapshot(partial_path)
        return (
            partial is None
            or not current_input
            or str(partial.get("input_fingerprint") or "") != current_input
        )

    # Legacy output directories predate generation metadata. The final file was produced
    # after parsing, so a newer blocks file is a conservative, deterministic stale signal.
    blocks_path = root / "blocks.jsonl"
    final_path = next(
        (root / name for name in (
            AI_REQUIREMENTS,
            "merged_spec_requirements.json",
            "ai_requirements_doc.json",
        ) if (root / name).exists()),
        None,
    )
    if final_path is None or not blocks_path.exists():
        return False
    try:
        blocks_are_newer = blocks_path.stat().st_mtime_ns > final_path.stat().st_mtime_ns
    except OSError:
        return True
    if not blocks_are_newer:
        return False
    if final_path.name == AI_REQUIREMENTS:
        blocks = {
            str(block.get("block_id") or ""): _norm_text(block.get("text"))
            for block in read_jsonl(blocks_path)
            if block.get("block_id")
        }
        for row in read_jsonl(final_path):
            quote = _norm_text(row.get("source_quote"))
            source_text = " ".join(
                blocks.get(str(block_id), "")
                for block_id in (row.get("source_block_ids") or [])
            ).strip()
            if quote and source_text and (quote in source_text or source_text in quote):
                # Some legacy fixtures/tools rewrite blocks after the final JSONL. A verbatim
                # source anchor proves this row still belongs to the current document.
                return False
    return True


def find_current_ai_requirement(output_dir: Path, req_id: str) -> dict | None:
    """Find the adjudication subject in the current partial generation, then final output."""
    root = Path(output_dir).expanduser().resolve()
    status = build_ai_extraction_status(root)
    candidates = status.get("rows") or []
    if status.get("run_id") is None:
        if final_ai_requirements_are_stale(root):
            return None
        candidates = build_ai_requirements(root)
    for row in candidates:
        if source_ai_requirement_id(row) == req_id:
            return row
    return None


def load_review_insights(output_dir: Path) -> dict:
    """裁决复盘建议（review_insights.json,裁决回流自动刷新）——0714 批次二 E5。

    此前该产物全链零消费者:专家改判提炼的规则改进建议(≥3 次同模式)永远躺磁盘,
    裁决学习回路事实断开。缺失/损坏 → available=false（老输出目录/未裁决时的正常态）。"""
    path = output_dir / "review_insights.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False, "suggestions": []}
    if not isinstance(payload, dict):
        return {"available": False, "suggestions": []}
    return {
        "available": True,
        "suggestions": [str(s) for s in payload.get("suggestions") or []],
        "decided_states": payload.get("decided_states"),
        "module_transitions": payload.get("module_transitions") or [],
        "ownership_transitions": payload.get("ownership_transitions") or [],
    }


def _consistency_markers(output_dir: Path) -> tuple[dict[str, int], set[str]]:
    """一致性闭环：读 consistency_report.json（P1b critic 产物），供批注视图标记。

    返回 (归一 source_quote → 重复组大小, 数值待核的 OBIS 集合)。报表缺失/损坏 → 空标记
    （视图与此前完全一致）。按 quote/OBIS 内容连接——报表成员是 merged REQ-id、视图行是
    AIR-id，内容键是两者天然共有的。
    """
    import re as _re
    path = output_dir / "consistency_report.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, set()
    if not isinstance(report, dict):
        return {}, set()

    def norm(s: object) -> str:
        return _re.sub(r"\s+", " ", str(s or "")).strip().lower()

    dup_quotes = {norm(g.get("source_quote")): int(g.get("count") or 0)
                  for g in report.get("duplicate_groups") or [] if g.get("source_quote")}
    differ_codes = {str(g.get("obis") or "") for g in report.get("obis_coreference") or []
                    if g.get("values_differ") and g.get("obis")}
    return dup_quotes, differ_codes


def _row_consistency_flags(row: dict, dup_quotes: dict[str, int], differ_codes: set[str]) -> list[str]:
    import re as _re
    flags: list[str] = []
    quote = _re.sub(r"\s+", " ", str(row.get("source_quote") or "")).strip().lower()
    if quote and quote in dup_quotes:
        flags.append(f"跨章重复×{dup_quotes[quote]}")
    if differ_codes:
        text = " ".join(str(row.get(k) or "") for k in ("title", "description", "source_quote"))
        hits = sorted(code for code in differ_codes if code in text)
        if hits:
            flags.append(f"OBIS 数值待核：{'、'.join(hits[:3])}")
    return flags


def _load_ai_requirements(output_dir: Path) -> list[dict]:
    # 批注视图优先读**原始** ai_requirements.jsonl：merged_spec 现在会剔除 rejected
    # （裁决回流交付物），若视图读 merged，被拒条目会从视图消失、无法反悔。
    raw = read_jsonl(output_dir / "ai_requirements.jsonl")
    if raw:
        return raw
    doc_path = output_dir / "merged_spec_requirements.json"
    if doc_path.exists():
        data = json.loads(doc_path.read_text(encoding="utf-8"))
        return list(data.get("requirements") or [])
    alt = output_dir / "ai_requirements_doc.json"
    if alt.exists():
        data = json.loads(alt.read_text(encoding="utf-8"))
        return list(data.get("requirements") or [])
    return []


def index_by_requirement_identity(rows: list[dict]) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for row in rows:
        for key in requirement_identity_keys(row):
            indexed[key] = row
    return indexed


def requirement_identity_keys(row: dict) -> list[str]:
    keys: list[str] = []
    for name in ("stable_req_id", "requirement_id", "req_id"):
        value = row.get(name)
        if value:
            text = str(value)
            if text not in keys:
                keys.append(text)
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    for name in ("stable_req_id", "req_id"):
        value = metadata.get(name)
        if value:
            text = str(value)
            if text not in keys:
                keys.append(text)
    return keys


def build_review_summary(output_dir: Path) -> dict:
    reviews = read_jsonl(output_dir / "llm_review_results.jsonl")
    states = read_jsonl(governed_artifact_path(
        output_dir, "review_states.jsonl", category="state", for_write=False,
    ))
    decision_counts: dict[str, int] = {}
    risk_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for review in reviews:
        decision = str(review.get("decision") or "unknown")
        risk = str(review.get("risk") or "unknown")
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
        risk_counts[risk] = risk_counts.get(risk, 0) + 1
    for state in states:
        status = str(state.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "counts": {
            "reviews": len(reviews),
            "review_states": len(states),
        },
        "decision_counts": decision_counts,
        "risk_counts": risk_counts,
        "status_counts": status_counts,
        "files": {
            "llm_review_results": "llm_review_results.jsonl",
            "review_states": "review_states.jsonl",
        },
    }


TRANSLATION_PROMPT_VERSION = "translation-prompt-v2"

TRANSLATION_SYSTEM_PROMPT = """You are a technical translator for DLMS/COSEM requirements.
Translate English requirement text into concise Simplified Chinese.
Preserve identifiers, quoted service names, OBIS codes, class names, attribute names, protocol acronyms, numeric values, and physical units (unit symbols such as V, A, Hz, s, %, °C, bar, etc. should be kept verbatim).
Return only JSON with two string fields: translation and protected_codes (the exact, space-separated list of protected codes/acronyms/identifiers/units found in the source)."""


# P0-7：物理单位符号集合——与 extract_guards._VALUE_UNIT_RE 同源口径，
# 覆盖电表领域常见量纲（电压/电流/频率/时间/压力/温度/百分比等）。
_TRANSLATION_UNIT_RE = re.compile(
    r"(?<![A-Za-z0-9])(\d+(?:[.,]\d+)?)\s*"
    r"(l/h|m3/h|m³/h|mbar|bar|kPa|Pa|MHz|kHz|Hz|mm|cm|kg|g|ms|min|%|°C|℃|V|mA|A|mT|h|s)"
    r"(?![A-Za-z])",
    re.IGNORECASE,
)


def _protected_units(text: str) -> set[str]:
    """受保护单位符号集合：物理量单位在译文中必须逐字保留。"""
    return {unit for _value, unit in _TRANSLATION_UNIT_RE.findall(str(text or ""))}


def _protected_codes(text: str) -> set[str]:
    """受保护编码集合：OBIS 码、class_id、整数、协议缩写、物理单位等翻译中必须逐字保留的 token。"""
    return set(extract_codes(text)) | set(produced_ints(text)) | _protected_units(text)


def translate_requirement_text(text: str, *, requirement_id: str = "", output_dir: Path | None = None) -> str:
    pipeline = load_review_pipeline(DEFAULT_PIPELINE_PATH)
    route_payload = dict(pipeline.model_routes.get("openai_compatible") or {})
    config = llm_config_from_route(route_payload)
    protected = _protected_codes(text)
    payload = chat_json(
        config,
        TRANSLATION_SYSTEM_PROMPT,
        json.dumps(
            {
                "requirement_id": requirement_id,
                "text": text,
                "protected_codes": sorted(protected),
                "prompt_version": TRANSLATION_PROMPT_VERSION,
            },
            ensure_ascii=False,
        ),
    )
    translation = str(payload.get("translation") or "").strip()
    if not translation:
        raise LLMResponseError("LLM translation response missing translation")
    # WS-C4 漂移护栏：受保护编码必须在译文中逐字回指。
    missing = protected - _protected_codes(translation)
    if missing:
        raise LLMResponseError(
            f"translation drift detected: protected codes missing in translation: {sorted(missing)}"
        )
    return translation


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve requirement atomizer output over a local HTTP API.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument(
        "--allow-origin",
        action="append",
        default=[],
        help="Allowed browser Origin. Can be provided multiple times.",
    )
    parser.add_argument("--token", default="", help="Optional local API token required for data endpoints.")
    return parser.parse_args(argv)


def _claim_generation_present(root: Path) -> bool:
    """package_v1 / legacy 两布局统一的 claim generation 存在性闸门（纯读）。

    package_v1 下该文件落在 .ratomizer/state/（governed_artifact_path 寻址）；
    裸拼接 root / 文件名在 package_v1 下永远为 False，会把启动维护整体静默跳过
    （2026-08-03 审查 B1）。
    """
    return governed_artifact_path(
        root, "claim_generation.meta.json", category="state"
    ).is_file()


def run_claim_startup_maintenance(out_dir: Path) -> dict:
    """Recover or refresh claim state before listening, with a read-only fast path."""
    root = Path(out_dir).expanduser().resolve()
    if not _claim_generation_present(root):
        return {
            "ok": True,
            "publication_skipped": True,
            "reason": "claim_generation_unavailable",
        }

    from claim_artifacts import (
        ClaimArtifactError,
        load_committed_effective_snapshot_readonly,
    )
    from claim_reextract_attempts import recover_interrupted_attempts
    from claim_review_actions import assess_effective_freshness, fold_effective_ledger

    # Attempt recovery is a write-side duty of startup/explicit maintenance
    # and queue execute; GET handlers stay read-only.
    recover_interrupted_attempts(root)

    try:
        snapshot = load_committed_effective_snapshot_readonly(root)
        freshness = assess_effective_freshness(root, snapshot, readonly=True)
    except (ClaimArtifactError, OSError, UnicodeError, json.JSONDecodeError):
        # Migration, WAL recovery, and damaged derived state belong to the
        # maintenance fold. The request-serving path remains read-only.
        return fold_effective_ledger(root, actor_trigger="api-startup-maintenance")

    if freshness["effective_fresh"]:
        return {
            "ok": True,
            "publication_skipped": True,
            "reason": "already_fresh",
            "effective_meta": dict(snapshot["effective_meta"]),
            "effective_metrics": dict(
                snapshot["effective_meta"].get("effective_metrics") or {}
            ),
            "queue_count": len(snapshot.get("queue_proposals") or []),
            "event_append_count": 0,
        }
    return fold_effective_ledger(root, actor_trigger="api-startup-maintenance")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    from desktop_tasks import setup_run_logging
    setup_run_logging(args.out)  # 长驻 API 的裁决回流/重建告警同样落 run.log + stderr
    RequirementAPIHandler.package_root = args.out.expanduser().resolve()
    RequirementAPIHandler.output_dir = resolve_analysis_root(RequirementAPIHandler.package_root)
    RequirementAPIHandler.allowed_origins = build_allowed_origins(args.host, args.port, args.allow_origin)
    RequirementAPIHandler.local_token = args.token
    if _claim_generation_present(RequirementAPIHandler.output_dir):
        try:
            run_claim_startup_maintenance(RequirementAPIHandler.output_dir)
        except Exception as exc:
            import logging

            logging.getLogger("requirement_atomizer").warning(
                "claim effective startup maintenance lagged: %s",
                exc,
            )
    # Kimi #3 跟进：重试此前 ready+recompute_error 的表（recompute 失败遗留），启动时自愈。
    try:
        run_table_review_recompute_recovery(RequirementAPIHandler.output_dir)
    except Exception as exc:
        import logging

        logging.getLogger("requirement_atomizer").warning(
            "table review recompute recovery lagged: %s", exc,
        )
    server = ThreadingHTTPServer((args.host, args.port), RequirementAPIHandler)
    print(
        json.dumps(
            {
                "host": args.host,
                "port": args.port,
                "output_dir": str(RequirementAPIHandler.output_dir),
                "package_root": str(RequirementAPIHandler.package_root),
                "allowed_origins": sorted(RequirementAPIHandler.allowed_origins),
                "token_required": bool(RequirementAPIHandler.local_token),
            },
            indent=2,
        ),
        flush=True,
    )
    server.serve_forever()
    return 0


def build_allowed_origins(host: str, port: int, extra_origins: list[str]) -> set[str]:
    """"null" origin（file:///沙箱 iframe）不再无条件放行（2026-07-08 审计 6-A）：
    裸跑无 token 时 GET 端点吐客户文档全文，任何网页的沙箱 iframe 都能跨源读取。
    需要 file:// 场景（本地批注 HTML 本身自包含、不调 API）可显式 --allow-origin null。"""
    origins = {f"http://{host}:{port}", f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    origins.update(origin for origin in extra_origins if origin)
    return origins


if __name__ == "__main__":
    raise SystemExit(main())
