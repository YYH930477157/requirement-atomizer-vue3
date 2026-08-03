from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import tempfile
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Any, Iterable

from process_file_lock import process_file_lock
from version import __version__


RESULT_PACKAGE_SCHEMA = "ratomizer-result-package/v1"
OUTPUT_LAYOUT_VERSION = "result-layout-v1"
RESULT_PACKAGE_FILE = "result-package.json"
INTERNAL_ROOT = ".ratomizer"
RUN_MANIFEST_SNAPSHOT = "run_manifest.json"

_REPLACE_ATTEMPTS = 8
_REPLACE_RETRY_DELAY_S = 0.025
_PACKAGE_LOCK_FILE = ".result-package.lock"
_PUBLICATION_JOURNAL_FILE = ".result-package-publication.json"
_PUBLICATION_TRANSACTIONS_DIR = "result-package-publications"
_PACKAGE_LOCK_DEPTH: ContextVar[int] = ContextVar("result_package_lock_depth", default=0)
_MARKER_CONTRACT_CACHE: dict[Path, tuple[int, int, int, dict[str, Any]]] = {}
_MARKER_CONTRACT_CACHE_LOCK = RLock()
# marker warnings[] 只追加不膨胀：保留最近 N 条，完整细节始终落在 run.log。
_PACKAGE_WARNING_LIMIT = 50

# schemas/result_package.schema.json additionalProperties=false 的代码侧镜像；
# 两处必须同步演进（S4）
_MARKER_TOP_LEVEL_KEYS = frozenset({
    "schema", "layout_version", "package_id", "analysis_status",
    "active_attempt", "last_attempt", "input", "analysis", "workspace",
    "deliverables", "tool", "warnings",
})


class ResultPackageError(RuntimeError):
    pass


class ResultPackageCorrupt(ResultPackageError):
    pass


class ResultPackageVersionUnsupported(ResultPackageError):
    pass


class ResultPackagePartialError(ResultPackageError):
    """请求阶段未全部成功（降级/缺失）——完成提交被拒绝的稳定错误面。

    CLI 映射为 envelope ``error.type == "requested_stage_partial"``（exit 2），
    桌面端据此显示"分析未完成（部分阶段降级）"而非"运行失败"；语义仍是
    fail-closed（active_attempt 保持 running，不冒充 completed）。"""


@contextmanager
def _package_write_lock(root: Path):
    depth = _PACKAGE_LOCK_DEPTH.get()
    if depth:
        token = _PACKAGE_LOCK_DEPTH.set(depth + 1)
        try:
            yield
        finally:
            _PACKAGE_LOCK_DEPTH.reset(token)
        return
    lock_path = root / INTERNAL_ROOT / "state" / _PACKAGE_LOCK_FILE
    with process_file_lock(lock_path, timeout_s=15.0, label="result package marker lock"):
        token = _PACKAGE_LOCK_DEPTH.set(1)
        try:
            yield
        finally:
            _PACKAGE_LOCK_DEPTH.reset(token)


@dataclass(frozen=True)
class ArtifactRegistration:
    artifact_id: str
    package_path: str
    legacy_path: str
    deliverable_path: str | None = None
    media_type: str | None = None


def _artifact(
    artifact_id: str,
    package_path: str,
    *,
    legacy_path: str | None = None,
    deliverable_path: str | None = None,
    media_type: str | None = None,
) -> ArtifactRegistration:
    return ArtifactRegistration(
        artifact_id=artifact_id,
        package_path=package_path,
        legacy_path=legacy_path or Path(package_path).name,
        deliverable_path=deliverable_path,
        media_type=media_type,
    )


# This is intentionally an allowlist. New root deliverables and governed
# internal files must be registered here before producers can publish them.
_ARTIFACTS = {
    item.artifact_id: item
    for item in (
        _artifact("blocks", "pipeline/blocks.jsonl", legacy_path="blocks.jsonl"),
        _artifact("chunks", "pipeline/chunks.jsonl", legacy_path="chunks.jsonl"),
        _artifact("table_items", "pipeline/table_items.jsonl", legacy_path="table_items.jsonl"),
        _artifact("table_cell_items", "pipeline/table_cell_items.jsonl", legacy_path="table_cell_items.jsonl"),
        _artifact("atomic_requirements", "pipeline/atomic_requirements.jsonl", legacy_path="atomic_requirements.jsonl"),
        _artifact("ai_requirements", "pipeline/ai_requirements.jsonl", legacy_path="ai_requirements.jsonl"),
        _artifact("requirements_analysis", "pipeline/requirements_analysis.json", legacy_path="requirements_analysis.json"),
        _artifact("run_manifest", "stages/run_manifest.json", legacy_path="run_manifest.json"),
        _artifact("run_manifest_lock", "stages/run_manifest.lock", legacy_path="run_manifest.lock"),
        _artifact("stage_state", "stages/_stages", legacy_path="_stages"),
        _artifact("run_log", "logs/run.log", legacy_path="run.log"),
        _artifact("llm_trace", "logs/llm_trace.jsonl", legacy_path="llm_trace.jsonl"),
        _artifact("review_states", "state/review_states.jsonl", legacy_path="review_states.jsonl"),
        _artifact("review_state_events", "state/review_state_events.jsonl", legacy_path="review_state_events.jsonl"),
        _artifact("ai_review_states", "state/ai_review_states.jsonl", legacy_path="ai_review_states.jsonl"),
        _artifact("extract_cache", "cache/ai_extract_cache.jsonl", legacy_path="ai_extract_cache.jsonl"),
        _artifact(
            "summary_md",
            "pipeline/summary.md",
            legacy_path="summary.md",
            deliverable_path="summary.md",
            media_type="text/markdown",
        ),
        _artifact(
            "document_annotation",
            "pipeline/document_annotation.html",
            legacy_path="document_annotation.html",
            deliverable_path="document_annotation.html",
            media_type="text/html",
        ),
        _artifact(
            "document_facsimile",
            "pipeline/document_facsimile.pdf",
            legacy_path="document_facsimile.pdf",
            deliverable_path="document_facsimile.pdf",
            media_type="application/pdf",
        ),
        _artifact(
            "merged_spec",
            "pipeline/merged_spec.xlsx",
            legacy_path="merged_spec.xlsx",
            deliverable_path="merged_spec.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        _artifact(
            "software_requirements",
            "pipeline/software_requirements.xlsx",
            legacy_path="software_requirements.xlsx",
            deliverable_path="software_requirements.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        _artifact(
            "template_requirements",
            "pipeline/软件需求列表-成文.xlsx",
            legacy_path="软件需求列表-成文.xlsx",
            deliverable_path="软件需求列表-成文.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        _artifact(
            "clarification_questions",
            "pipeline/clarification_questions.xlsx",
            legacy_path="clarification_questions.xlsx",
            deliverable_path="clarification_questions.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        _artifact(
            "engineering_requirements",
            "pipeline/engineering_requirements",
            legacy_path="engineering_requirements",
            deliverable_path="engineering_requirements",
            media_type="inode/directory",
        ),
    )
}

_LEGACY_SENTINELS = {
    registration.legacy_path
    for registration in _ARTIFACTS.values()
    if registration.deliverable_path is None
}
_LEGACY_SENTINELS.add("manifest.json")
# 日志/锁类偶发文件不能单独把目录定性为旧版扁平产物：桌面端每次任务都会初始化
# run.log/llm_trace.jsonl，历史上只读探测（summary）也会在被预览目录的根留下
# run.log——若计入哨兵，任何被界面"看过一眼"的新目录都会被 initialize_result_package
# 误判为 legacy_flat 而拒绝开工（2026-08-03 实测复现：选新目录 → summary 留 run.log
# → result-package-start 抛 "legacy flat output requires explicit migration"）。
_LEGACY_SENTINELS -= {"run.log", "run_manifest.lock", "llm_trace.jsonl"}

_STATE_FILENAMES = {
    "review_states.jsonl", "review_state_events.jsonl", "review_states.lock",
    "ai_review_states.jsonl", "ai_review_states.lock", "ai_supplements.jsonl",
    "clarification_answers.jsonl", "clarification_answers.lock",
    "clarification_check_states.jsonl", "clarification_check_states.lock",
    "omission_states.jsonl", "omission_actions.lock",
    "claim_catalog.jsonl", "claim_catalog.meta.json", "claim_coverage_groups.jsonl",
    "claim_ledger.jsonl", "claim_effective_ledger.jsonl", "claim_shadow_metrics.json",
    "claim_generation.meta.json", "claim_effective.meta.json",
    "claim_review_events.jsonl", "claim_queue_proposals.jsonl",
    "claim_effective_health.json", "claim_verifier_attempts.jsonl",
    "claim_reextract_attempts.jsonl", "claim_structural_overrides.jsonl",
    "claim_structural_operations.jsonl", "claim_structural_candidate_decisions.jsonl",
    "claim_structural_decisions",
    ".claim_verifier_attempt.checkpoint.json", ".claim_budget_checkpoint.outbox.json",
    ".claim_publication.journal.json", ".claim_effective_publication.journal.json",
    "claim_artifacts.lock",
}

_CACHE_FILENAMES = {
    "ai_extract_cache.jsonl", "llm_review_cache.jsonl", "spec_enrich_cache.jsonl",
    "analyze_enrich_cache.json", "annotation_translations.json",
    "annotation_translations.lock",
}

_LOG_FILENAMES = {"run.log", "llm_trace.jsonl"}


def governed_artifact_path(
    root: Path | str,
    filename: str,
    *,
    category: str | None = None,
    for_write: bool = True,
) -> Path:
    """Resolve the governed location of a state/cache/log/pipeline artifact.

    S6（2026-08-03 清单）：for_write=False 时纯解析不落盘——只读 GET/快照
    读取不得自称"无副作用"却在盘上创建 .ratomizer/<category> 空目录；
    只有显式 for_write=True（默认，兼容既有写路径）才创建父目录。
    """
    base = Path(root).expanduser().resolve()
    package_root = package_root_for_analysis_root(base)
    if package_root is None:
        marker = base / RESULT_PACKAGE_FILE
        if marker.exists():
            _load_marker_contract(base)
            package_root = base
    if package_root is None:
        return base / filename
    selected = category
    if selected is None:
        name = Path(filename).name
        if name in _STATE_FILENAMES or name.startswith(".claim-"):
            selected = "state"
        elif name in _CACHE_FILENAMES or name.endswith("_cache.jsonl"):
            selected = "cache"
        elif name in _LOG_FILENAMES:
            selected = "logs"
        else:
            selected = "pipeline"
    if selected not in {"pipeline", "state", "cache", "logs", "stages"}:
        raise ResultPackageError(f"invalid internal artifact category: {selected}")
    target = package_root / INTERNAL_ROOT / selected / filename
    if for_write:
        target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _sha256_directory(path: Path) -> str:
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with child.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _replace_with_retry(source: Path, target: Path) -> None:
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt + 1 >= _REPLACE_ATTEMPTS:
                raise
            time.sleep(_REPLACE_RETRY_DELAY_S * (attempt + 1))


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=".tmp.",
            suffix=".json",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(_json_payload_text(payload))
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _json_payload_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _publication_journal_path(root: Path) -> Path:
    return root / INTERNAL_ROOT / "stages" / _PUBLICATION_JOURNAL_FILE


def _publication_transaction_root(root: Path, transaction_id: str) -> Path:
    if not transaction_id or any(character not in "0123456789abcdef" for character in transaction_id):
        raise ResultPackageCorrupt("invalid result publication transaction id")
    return (
        root / INTERNAL_ROOT / "stages" / _PUBLICATION_TRANSACTIONS_DIR / transaction_id
    )


def _safe_relative_path(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ResultPackageCorrupt(f"invalid {label}")
    normalized = value.replace("\\", "/")
    candidate = PurePosixPath(normalized)
    parts = candidate.parts
    # S3（2026-08-03 清单）："." / "./" 的 parts 为空——此前 parts[0] 抛裸
    # IndexError 绕过 ResultPackageCorrupt；首段任何含 ":" 的形态（含 "C:foo"
    # 盘符相对路径）一律拒绝，这是路径穿越防线的唯一关口
    if (
        not parts
        or candidate.is_absolute()
        or ".." in parts
        or ":" in parts[0]
    ):
        raise ResultPackageCorrupt(f"unsafe {label}: {value}")
    return candidate.as_posix()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _resolve_registered_path(root: Path, relative: str) -> Path:
    safe = _safe_relative_path(relative, label="artifact path")
    target = (root / Path(*PurePosixPath(safe).parts)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ResultPackageCorrupt(f"artifact path escapes result root: {relative}") from exc
    return target


def _validate_package(package: Any) -> dict[str, Any]:
    if not isinstance(package, dict):
        raise ResultPackageCorrupt("result package marker must be a JSON object")
    schema = package.get("schema")
    if schema != RESULT_PACKAGE_SCHEMA:
        if isinstance(schema, str):
            raise ResultPackageVersionUnsupported(f"unsupported result package schema: {schema}")
        raise ResultPackageCorrupt("missing result package schema")
    if package.get("layout_version") != OUTPUT_LAYOUT_VERSION:
        raise ResultPackageVersionUnsupported(
            f"unsupported output layout: {package.get('layout_version')!r}"
        )
    # S4（2026-08-03 清单）：与 schemas/result_package.schema.json 对齐——
    # 顶层白名单（additionalProperties: false）、package_id 模式、tool 记录、
    # warnings 全字符串。代码写出的 marker 永远合规，这里拒的是手工/外来 marker。
    unknown_fields = sorted(set(package) - _MARKER_TOP_LEVEL_KEYS)
    if unknown_fields:
        raise ResultPackageCorrupt(
            f"unknown result package fields: {', '.join(unknown_fields)}"
        )
    package_id = package.get("package_id")
    if (
        not isinstance(package_id, str)
        or not package_id.startswith("RPK-")
        or len(package_id) <= 4
        or any(character not in "0123456789abcdef" for character in package_id[4:])
    ):
        raise ResultPackageCorrupt("invalid result package id")
    tool = package.get("tool")
    if (
        not isinstance(tool, dict)
        or not isinstance(tool.get("version"), str)
        or not tool["version"]
    ):
        raise ResultPackageCorrupt("invalid result package tool record")
    if tool.get("output_layout_version") != OUTPUT_LAYOUT_VERSION:
        raise ResultPackageCorrupt("invalid tool output layout version")
    warnings = package.get("warnings")
    if not isinstance(warnings, list) or not all(
        isinstance(item, str) for item in warnings
    ):
        raise ResultPackageCorrupt("invalid result package warnings")
    if package.get("analysis_status") not in {"running", "incomplete", "completed"}:
        raise ResultPackageCorrupt("invalid analysis_status")
    if package.get("workspace") != INTERNAL_ROOT:
        raise ResultPackageCorrupt("invalid workspace path")
    _safe_relative_path(package["workspace"], label="workspace")
    _validate_input_record(package.get("input"), label="input")
    for key in ("active_attempt", "last_attempt", "analysis"):
        if package.get(key) is not None and not isinstance(package.get(key), dict):
            raise ResultPackageCorrupt(f"invalid {key}")
    active_attempt = package.get("active_attempt")
    if isinstance(active_attempt, dict):
        if active_attempt.get("status") != "running":
            raise ResultPackageCorrupt("invalid active attempt status")
        requested = active_attempt.get("requested_stages")
        if not isinstance(requested, list) or not requested or not all(
            isinstance(stage, str) and stage for stage in requested
        ):
            raise ResultPackageCorrupt("invalid active attempt stages")
        _validate_input_record(active_attempt.get("input"), label="active attempt input")
    deliverables = package.get("deliverables")
    if not isinstance(deliverables, list):
        raise ResultPackageCorrupt("invalid deliverables")
    seen: set[str] = set()
    for item in deliverables:
        if not isinstance(item, dict):
            raise ResultPackageCorrupt("invalid deliverable entry")
        artifact_id = item.get("artifact_id")
        registration = _ARTIFACTS.get(artifact_id)
        if registration is None or registration.deliverable_path is None:
            raise ResultPackageCorrupt(f"unregistered deliverable: {artifact_id!r}")
        if artifact_id in seen:
            raise ResultPackageCorrupt(f"duplicate deliverable: {artifact_id}")
        seen.add(artifact_id)
        path = _safe_relative_path(item.get("path"), label="deliverable path")
        if path != registration.deliverable_path:
            raise ResultPackageCorrupt(f"unexpected path for deliverable {artifact_id}")
        if not isinstance(item.get("bytes"), int) or item["bytes"] < 0:
            raise ResultPackageCorrupt(f"invalid size for deliverable {artifact_id}")
        digest = item.get("sha256")
        if not _is_sha256(digest):
            raise ResultPackageCorrupt(f"invalid digest for deliverable {artifact_id}")
    analysis = package.get("analysis")
    if package["analysis_status"] == "completed" and not isinstance(analysis, dict):
        raise ResultPackageCorrupt("completed package has no analysis record")
    if isinstance(analysis, dict):
        run_id = analysis.get("run_id")
        requested = analysis.get("requested_stages")
        completed = analysis.get("completed_stages")
        if not isinstance(run_id, str) or not run_id.startswith("RUN-"):
            raise ResultPackageCorrupt("invalid analysis run id")
        if not isinstance(requested, list) or not requested:
            raise ResultPackageCorrupt("invalid analysis requested stages")
        if not isinstance(completed, list) or any(stage not in completed for stage in requested):
            raise ResultPackageCorrupt("invalid analysis completed stages")
        evidence = analysis.get("completion_evidence")
        if not isinstance(evidence, list):
            raise ResultPackageCorrupt("invalid completion evidence")
        for item in evidence:
            if not isinstance(item, dict):
                raise ResultPackageCorrupt("invalid completion evidence entry")
            if item.get("artifact_id") != "run_manifest_snapshot":
                raise ResultPackageCorrupt("invalid completion evidence artifact")
            evidence_path = _safe_relative_path(
                item.get("path"), label="completion evidence path"
            )
            expected_path = (
                f"{INTERNAL_ROOT}/stages/completions/{run_id}/{RUN_MANIFEST_SNAPSHOT}"
            )
            if evidence_path != expected_path:
                raise ResultPackageCorrupt("invalid completion evidence location")
            if not _is_sha256(item.get("sha256")):
                raise ResultPackageCorrupt("invalid completion evidence digest")
    return package


def _validate_input_record(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ResultPackageCorrupt(f"invalid {label} record")
    if not isinstance(value.get("display_name"), str) or not value["display_name"]:
        raise ResultPackageCorrupt(f"invalid {label} display name")
    if not isinstance(value.get("media_type"), str) or not value["media_type"]:
        raise ResultPackageCorrupt(f"invalid {label} media type")
    digest = value.get("sha256")
    if not _is_sha256(digest):
        raise ResultPackageCorrupt(f"invalid {label} digest")
    return value


def _marker_path(root: Path | str) -> Path:
    return Path(root).expanduser().resolve() / RESULT_PACKAGE_FILE


def _load_marker_contract(root: Path | str) -> dict[str, Any]:
    result_root = Path(root).expanduser().resolve()
    marker = result_root / RESULT_PACKAGE_FILE
    try:
        stat = marker.stat()
    except FileNotFoundError as exc:
        raise ResultPackageError(f"result package marker does not exist: {marker}") from exc
    except OSError as exc:
        raise ResultPackageCorrupt(f"cannot stat result package marker: {exc}") from exc
    with _MARKER_CONTRACT_CACHE_LOCK:
        cached = _MARKER_CONTRACT_CACHE.get(result_root)
        signature = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        if cached is not None and cached[:3] == signature:
            return dict(cached[3])
    try:
        package = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ResultPackageCorrupt(f"invalid result package marker: {exc}") from exc
    package = _validate_package(package)
    with _MARKER_CONTRACT_CACHE_LOCK:
        _MARKER_CONTRACT_CACHE[result_root] = (
            stat.st_mtime_ns,
            stat.st_ctime_ns,
            stat.st_size,
            dict(package),
        )
    return package


def detect_result_layout(root: Path | str) -> str:
    result_root = Path(root).expanduser().resolve()
    marker = result_root / RESULT_PACKAGE_FILE
    if marker.exists():
        load_result_package(result_root)
        return "package_v1"
    if any((result_root / name).exists() for name in _LEGACY_SENTINELS):
        return "legacy_flat"
    return "empty"


def resolve_analysis_root(root: Path | str) -> Path:
    result_root = Path(root).expanduser().resolve()
    if detect_result_layout(result_root) == "package_v1":
        return result_root / INTERNAL_ROOT / "pipeline"
    return result_root


def package_root_for_analysis_root(root: Path | str) -> Path | None:
    analysis_root = Path(root).expanduser().resolve()
    if analysis_root.name != "pipeline" or analysis_root.parent.name != INTERNAL_ROOT:
        return None
    package_root = analysis_root.parent.parent
    marker = package_root / RESULT_PACKAGE_FILE
    if not marker.exists():
        return None
    _load_marker_contract(package_root)
    return package_root


def load_result_package(root: Path | str, *, verify: bool = False) -> dict[str, Any]:
    result_root = Path(root).expanduser().resolve()
    if _publication_journal_path(result_root).exists():
        raise ResultPackageCorrupt(
            "result package has an interrupted deliverable publication"
        )
    marker = result_root / RESULT_PACKAGE_FILE
    try:
        raw = marker.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ResultPackageError(f"result package marker does not exist: {marker}") from exc
    except OSError as exc:
        raise ResultPackageCorrupt(f"cannot read result package marker: {exc}") from exc
    try:
        package = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ResultPackageCorrupt(f"invalid result package marker: {exc}") from exc
    package = _validate_package(package)
    analysis = package.get("analysis")
    if isinstance(analysis, dict):
        for evidence in analysis["completion_evidence"]:
            target = _resolve_registered_path(result_root, evidence["path"])
            if not target.is_file():
                raise ResultPackageCorrupt(
                    f"completion evidence missing: {evidence['path']}"
                )
            if verify and _sha256_file(target) != evidence.get("sha256"):
                raise ResultPackageCorrupt(
                    f"completion evidence changed: {evidence['path']}"
                )
    for deliverable in package["deliverables"]:
        target = _resolve_registered_path(result_root, deliverable["path"])
        if not target.exists():
            raise ResultPackageCorrupt(f"deliverable missing: {deliverable['path']}")
        if verify:
            digest = _sha256_directory(target) if target.is_dir() else _sha256_file(target)
            if digest != deliverable["sha256"]:
                raise ResultPackageCorrupt(f"deliverable changed: {deliverable['path']}")
    return package


def _initialize_result_package_unlocked(
    root: Path | str,
    *,
    input_path: Path | str,
    requested_stages: Iterable[str],
) -> dict[str, Any]:
    result_root = Path(root).expanduser().resolve()
    source = Path(input_path).expanduser().resolve()
    result_root.mkdir(parents=True, exist_ok=True)
    for name in ("pipeline", "state", "cache", "logs", "stages"):
        (result_root / INTERNAL_ROOT / name).mkdir(parents=True, exist_ok=True)

    marker = result_root / RESULT_PACKAGE_FILE
    previous: dict[str, Any] | None = None
    if marker.exists():
        previous = load_result_package(result_root)
    elif detect_result_layout(result_root) == "legacy_flat":
        raise ResultPackageError("legacy flat output requires explicit migration")

    now = _utc_now()
    run_id = "RUN-" + uuid.uuid4().hex
    requested = list(dict.fromkeys(str(stage).strip() for stage in requested_stages if str(stage).strip()))
    if not requested:
        raise ResultPackageError("result package requires at least one analysis stage")
    attempt_input = {
        "display_name": source.name,
        "media_type": mimetypes.guess_type(source.name)[0] or "application/octet-stream",
        "sha256": _sha256_file(source),
    }
    active_attempt = {
        "run_id": run_id,
        "status": "running",
        "started_at": now,
        "requested_stages": requested,
        "input": attempt_input,
    }
    package = {
        "schema": RESULT_PACKAGE_SCHEMA,
        "layout_version": OUTPUT_LAYOUT_VERSION,
        "package_id": previous.get("package_id") if previous else "RPK-" + uuid.uuid4().hex,
        "analysis_status": (
            "completed" if previous and previous.get("analysis_status") == "completed" else "running"
        ),
        "active_attempt": active_attempt,
        "last_attempt": previous.get("last_attempt") if previous else None,
        "input": (
            dict(previous["input"])
            if previous and previous.get("analysis") is not None
            else attempt_input
        ),
        "analysis": previous.get("analysis") if previous else None,
        "workspace": INTERNAL_ROOT,
        "deliverables": list(previous.get("deliverables", [])) if previous else [],
        "tool": {
            "version": __version__,
            "output_layout_version": OUTPUT_LAYOUT_VERSION,
        },
        "warnings": list(previous.get("warnings", [])) if previous else [],
    }
    _validate_package(package)
    _atomic_write_json(marker, package)
    return package


def package_artifact_path(
    root: Path | str,
    artifact_id: str,
    *,
    for_write: bool = False,
) -> Path:
    # S6：for_write 不再是死参——默认纯解析，只有写路径显式 for_write=True 才建父目录
    result_root = Path(root).expanduser().resolve()
    registration = _ARTIFACTS.get(artifact_id)
    if registration is None:
        raise ResultPackageError(f"unknown result artifact: {artifact_id}")
    layout = detect_result_layout(result_root)
    if layout == "package_v1":
        target = result_root / INTERNAL_ROOT / registration.package_path
    else:
        target = result_root / registration.legacy_path
    if for_write:
        target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _copy_file_atomic(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, prefix=".tmp.", suffix=target.suffix, delete=False
        ) as handle:
            temporary = Path(handle.name)
            with source.open("rb") as source_handle:
                shutil.copyfileobj(source_handle, handle)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _copy_directory_atomic(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    backup = target.parent / f".{target.name}.{uuid.uuid4().hex}.bak"
    shutil.copytree(source, temporary)
    try:
        if target.exists():
            _replace_with_retry(target, backup)
        try:
            _replace_with_retry(temporary, target)
        except BaseException:
            if backup.exists() and not target.exists():
                _replace_with_retry(backup, target)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _copy_path_snapshot(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target)
        return
    shutil.copy2(source, target)
    with target.open("r+b") as handle:
        os.fsync(handle.fileno())


def _copy_path_atomic(source: Path, target: Path) -> None:
    if source.is_dir():
        if target.exists() and not target.is_dir():
            _remove_path(target)
        _copy_directory_atomic(source, target)
        return
    if target.exists() and target.is_dir():
        _remove_path(target)
    _copy_file_atomic(source, target)


def _install_staged_path(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        if target.exists():
            _remove_path(target)
        _replace_with_retry(source, target)
        return
    if target.exists() and target.is_dir():
        _remove_path(target)
    _replace_with_retry(source, target)


def _path_digest_and_size(path: Path) -> tuple[str, int]:
    if path.is_dir():
        return (
            _sha256_directory(path),
            sum(item.stat().st_size for item in path.rglob("*") if item.is_file()),
        )
    return _sha256_file(path), path.stat().st_size


def _cleanup_publication_transaction(root: Path, journal: dict[str, Any]) -> None:
    transaction_id = str(journal.get("transaction_id") or "")
    transaction_root = _publication_transaction_root(root, transaction_id)
    if transaction_root.exists():
        shutil.rmtree(transaction_root)
    _publication_journal_path(root).unlink(missing_ok=True)


def _restore_publication_transaction(root: Path, journal: dict[str, Any]) -> None:
    entries = journal.get("entries")
    if not isinstance(entries, list):
        raise ResultPackageCorrupt("invalid result publication journal entries")
    for item in reversed(entries):
        if not isinstance(item, dict):
            raise ResultPackageCorrupt("invalid result publication journal entry")
        target = _resolve_registered_path(root, item.get("path"))
        if item.get("had_target") is True:
            backup = _resolve_registered_path(root, item.get("backup_path"))
            if not backup.exists():
                raise ResultPackageCorrupt(
                    f"result publication backup missing: {item.get('backup_path')}"
                )
            _copy_path_atomic(backup, target)
        else:
            _remove_path(target)


def _read_publication_journal(root: Path) -> dict[str, Any] | None:
    path = _publication_journal_path(root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResultPackageCorrupt(f"invalid result publication journal: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != "result-package-publication/v1":
        raise ResultPackageCorrupt("invalid result publication journal contract")
    _publication_transaction_root(root, str(payload.get("transaction_id") or ""))
    if not _is_sha256(payload.get("base_marker_sha256")):
        raise ResultPackageCorrupt("invalid result publication base marker digest")
    if not _is_sha256(payload.get("target_marker_sha256")):
        raise ResultPackageCorrupt("invalid result publication target marker digest")
    return payload


def _recover_publication_unlocked(root: Path) -> None:
    journal = _read_publication_journal(root)
    if journal is None:
        return
    marker = root / RESULT_PACKAGE_FILE
    current_marker_sha = _sha256_file(marker) if marker.is_file() else None
    if current_marker_sha == journal["target_marker_sha256"]:
        _cleanup_publication_transaction(root, journal)
        return
    if current_marker_sha != journal["base_marker_sha256"]:
        raise ResultPackageCorrupt(
            "result publication marker changed outside the interrupted transaction"
        )
    _restore_publication_transaction(root, journal)
    _cleanup_publication_transaction(root, journal)


def _publish_package_unlocked(root: Path, package: dict[str, Any]) -> dict[str, Any]:
    marker = root / RESULT_PACKAGE_FILE
    if not marker.is_file():
        raise ResultPackageError("cannot publish deliverables without a result package marker")
    base_marker_sha = _sha256_file(marker)
    transaction_id = uuid.uuid4().hex
    transaction_root = _publication_transaction_root(root, transaction_id)
    new_root = transaction_root / "new"
    backup_root = transaction_root / "backup"
    published_by_id = {
        str(item["artifact_id"]): dict(item)
        for item in package.get("deliverables", [])
    }
    entries: list[dict[str, Any]] = []
    try:
        for registration in _ARTIFACTS.values():
            if registration.deliverable_path is None:
                continue
            source = root / INTERNAL_ROOT / registration.package_path
            if not source.exists():
                continue
            staged = new_root / registration.artifact_id
            _copy_path_snapshot(source, staged)
            digest, size = _path_digest_and_size(staged)
            target = _resolve_registered_path(root, registration.deliverable_path)
            target_digest = None
            if target.exists() and target.is_dir() == staged.is_dir():
                target_digest, _ = _path_digest_and_size(target)
            if target_digest != digest:
                entry: dict[str, Any] = {
                    "artifact_id": registration.artifact_id,
                    "path": registration.deliverable_path,
                    "staged_path": staged.relative_to(root).as_posix(),
                    "had_target": target.exists(),
                }
                if target.exists():
                    backup = backup_root / registration.artifact_id
                    _copy_path_snapshot(target, backup)
                    entry["backup_path"] = backup.relative_to(root).as_posix()
                entries.append(entry)
            published_by_id[registration.artifact_id] = {
                "artifact_id": registration.artifact_id,
                "path": registration.deliverable_path,
                "media_type": registration.media_type or "application/octet-stream",
                "bytes": size,
                "sha256": digest,
            }
        target_package = dict(package)
        target_package["deliverables"] = sorted(
            published_by_id.values(), key=lambda item: item["artifact_id"]
        )
        _validate_package(target_package)
        target_marker_sha = _sha256_bytes(_json_payload_text(target_package).encode("utf-8"))
        journal = {
            "schema": "result-package-publication/v1",
            "transaction_id": transaction_id,
            "base_marker_sha256": base_marker_sha,
            "target_marker_sha256": target_marker_sha,
            "entries": entries,
        }
        if entries:
            _atomic_write_json(_publication_journal_path(root), journal)
            for item in entries:
                staged = _resolve_registered_path(root, item["staged_path"])
                target = _resolve_registered_path(root, item["path"])
                _install_staged_path(staged, target)
        _atomic_write_json(marker, target_package)
    except BaseException:
        journal_path = _publication_journal_path(root)
        if journal_path.exists():
            recovery = _read_publication_journal(root)
            if recovery is not None:
                current_marker_sha = _sha256_file(marker) if marker.is_file() else None
                if current_marker_sha != recovery["target_marker_sha256"]:
                    _restore_publication_transaction(root, recovery)
                _cleanup_publication_transaction(root, recovery)
        elif transaction_root.exists():
            shutil.rmtree(transaction_root)
        raise
    if entries:
        try:
            _cleanup_publication_transaction(root, journal)
        except OSError:
            # The committed marker is authoritative. A later mutating command
            # will recognize its target digest and finish cleanup idempotently.
            pass
    elif transaction_root.exists():
        shutil.rmtree(transaction_root)
    return target_package


def _publish_registered_deliverables_unlocked(
    root: Path | str,
    *,
    update_marker: bool = True,
) -> list[dict[str, Any]]:
    result_root = Path(root).expanduser().resolve()
    if detect_result_layout(result_root) != "package_v1":
        return []
    if not update_marker:
        raise ResultPackageError(
            "transactional deliverable publication requires an atomic marker update"
        )
    package = load_result_package(result_root)
    return list(_publish_package_unlocked(result_root, package)["deliverables"])


def _completion_evidence(
    root: Path,
    requested_stages: Iterable[str],
    *,
    run_id: str,
) -> list[dict[str, Any]]:
    run_manifest = package_artifact_path(root, "run_manifest")
    if not run_manifest.is_file():
        raise ResultPackageError("cannot complete analysis without run manifest")
    try:
        manifest = json.loads(run_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ResultPackageError(f"invalid completion run manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ResultPackageError("invalid completion run manifest")
    stages = manifest.get("stages")
    if not isinstance(stages, dict):
        raise ResultPackageError("completion run manifest has no stage ledger")
    for stage in requested_stages:
        entry = stages.get(stage)
        if not isinstance(entry, dict) or entry.get("status") != "ok":
            actual = entry.get("status") if isinstance(entry, dict) else "missing"
            raise ResultPackagePartialError(
                f"requested stage is not complete: {stage} ({actual})"
            )
        if entry.get("attempt_run_id") != run_id:
            raise ResultPackageError(
                f"requested stage does not belong to the active attempt: {stage}"
            )
    snapshot_path = (
        root / INTERNAL_ROOT / "stages" / "completions" / run_id / RUN_MANIFEST_SNAPSHOT
    )
    _atomic_write_json(snapshot_path, manifest)
    return [{
        "artifact_id": "run_manifest_snapshot",
        "path": snapshot_path.relative_to(root).as_posix(),
        "sha256": _sha256_file(snapshot_path),
    }]


def _commit_analysis_completion_unlocked(
    root: Path | str,
    *,
    run_id: str,
    completed_stages: Iterable[str],
) -> dict[str, Any]:
    result_root = Path(root).expanduser().resolve()
    package = load_result_package(result_root)
    active = package.get("active_attempt")
    if not isinstance(active, dict) or active.get("run_id") != run_id:
        raise ResultPackageError("completion run_id does not match the active attempt")
    completed = list(completed_stages)
    requested = list(active.get("requested_stages", []))
    if any(stage not in completed for stage in requested):
        raise ResultPackagePartialError("not all requested stages completed")
    evidence = _completion_evidence(result_root, requested, run_id=run_id)
    finished_at = _utc_now()
    package["analysis_status"] = "completed"
    package["input"] = dict(active["input"])
    package["analysis"] = {
        "run_id": run_id,
        "started_at": active["started_at"],
        "completed_at": finished_at,
        "requested_stages": requested,
        "completed_stages": completed,
        "completion_evidence": evidence,
    }
    package["last_attempt"] = {
        "run_id": run_id,
        "status": "completed",
        "finished_at": finished_at,
    }
    package["active_attempt"] = None
    return _publish_package_unlocked(result_root, package)


def _record_analysis_failure_unlocked(
    root: Path | str,
    *,
    run_id: str,
    error: str,
) -> dict[str, Any]:
    result_root = Path(root).expanduser().resolve()
    package = load_result_package(result_root)
    active = package.get("active_attempt")
    if not isinstance(active, dict) or active.get("run_id") != run_id:
        raise ResultPackageError("failure run_id does not match the active attempt")
    package["active_attempt"] = None
    package["last_attempt"] = {
        "run_id": run_id,
        "status": "failed",
        "finished_at": _utc_now(),
        "error": str(error)[:2000],
    }
    if package.get("analysis") is None:
        package["analysis_status"] = "incomplete"
    _validate_package(package)
    _atomic_write_json(result_root / RESULT_PACKAGE_FILE, package)
    return package


def initialize_result_package(
    root: Path | str,
    *,
    input_path: Path | str,
    requested_stages: Iterable[str],
) -> dict[str, Any]:
    result_root = Path(root).expanduser().resolve()
    result_root.mkdir(parents=True, exist_ok=True)
    if not (result_root / RESULT_PACKAGE_FILE).exists() and any(
        (result_root / name).exists() for name in _LEGACY_SENTINELS
    ):
        raise ResultPackageError("legacy flat output requires explicit migration")
    with _package_write_lock(result_root):
        _recover_publication_unlocked(result_root)
        if detect_result_layout(result_root) == "legacy_flat":
            raise ResultPackageError("legacy flat output requires explicit migration")
        return _initialize_result_package_unlocked(
            result_root,
            input_path=input_path,
            requested_stages=requested_stages,
        )


def publish_registered_deliverables(
    root: Path | str,
    *,
    update_marker: bool = True,
) -> list[dict[str, Any]]:
    result_root = Path(root).expanduser().resolve()
    with _package_write_lock(result_root):
        _recover_publication_unlocked(result_root)
        return _publish_registered_deliverables_unlocked(
            result_root,
            update_marker=update_marker,
        )


def commit_analysis_completion(
    root: Path | str,
    *,
    run_id: str,
    completed_stages: Iterable[str],
) -> dict[str, Any]:
    result_root = Path(root).expanduser().resolve()
    with _package_write_lock(result_root):
        _recover_publication_unlocked(result_root)
        return _commit_analysis_completion_unlocked(
            result_root,
            run_id=run_id,
            completed_stages=completed_stages,
        )


def record_analysis_failure(
    root: Path | str,
    *,
    run_id: str,
    error: str,
) -> dict[str, Any]:
    result_root = Path(root).expanduser().resolve()
    with _package_write_lock(result_root):
        _recover_publication_unlocked(result_root)
        return _record_analysis_failure_unlocked(
            result_root,
            run_id=run_id,
            error=error,
        )


def record_package_warning(root: Path | str, message: str) -> dict[str, Any]:
    """Append a human-readable warning to the marker（spec §11 降级留痕写入点）。

    用于"阶段已成功但交付物发布失败"这类不得改写阶段结果的降级场景；
    只追加不膨胀（保留最近 _PACKAGE_WARNING_LIMIT 条），完整细节落 run.log。
    """
    result_root = Path(root).expanduser().resolve()
    with _package_write_lock(result_root):
        _recover_publication_unlocked(result_root)
        package = load_result_package(result_root)
        warnings = list(package.get("warnings") or [])
        warnings.append(f"{_utc_now()} {str(message)[:500]}")
        package["warnings"] = warnings[-_PACKAGE_WARNING_LIMIT:]
        _validate_package(package)
        _atomic_write_json(result_root / RESULT_PACKAGE_FILE, package)
        return package
