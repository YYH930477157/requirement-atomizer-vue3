"""Audited omission triage and targeted AI extraction supplements.

The extraction cache is deliberately not a read API. Completed targeted fixes live in a
separate append-only patch log and are replayed only while both source and strategy match.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from io_utils import read_jsonl, read_jsonl_recover_torn_tail


OMISSION_STATES = "omission_states.jsonl"
AI_SUPPLEMENTS = "ai_supplements.jsonl"
AI_SUPPLEMENT_VERSION = "ai-supplement-v3-identity-preconditions"
VALID_OMISSION_STATUS = {
    "non_requirement",
    "needs_extraction",
    "issue_confirmed",
    "resolved",
}

_LOCKS: dict[tuple[Path, str], RLock] = {}
_LOCKS_GUARD = RLock()
_LOCK_TIMEOUT_S = 10.0
_LOCK_STALE_AFTER_S = 300.0
_OPERATION_STALE_AFTER_S = 6 * 60 * 60
_OPERATION_INITIALIZATION_GRACE_S = 2.0
_EXTRACTION_OPERATION_LOCK = "ai_extraction_operation.lock"
LOGGER = logging.getLogger("requirement_atomizer")


class OmissionConflictError(ValueError):
    pass


class OmissionNoResultError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def omission_source_fingerprint(block_id: str, text: str) -> str:
    return _canonical_hash({"block_id": str(block_id), "text": str(text)})


def make_omission_id(block_id: str, text: str) -> str:
    basis = f"{block_id}|{omission_source_fingerprint(block_id, text)}"
    return "OMI-" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def _process_lock_for(root: Path, name: str) -> RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault((root, name), RLock())


def _remove_stale_lock(path: Path, stale_after_s: float) -> bool:
    try:
        age = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return True
    if age < stale_after_s:
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return True


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            # Access denied means the process exists but cannot be queried.
            return int(kernel32.GetLastError()) == 5
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return int(exit_code.value) == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _remove_abandoned_operation_lock(path: Path) -> bool:
    try:
        age = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return True
    if age < _OPERATION_INITIALIZATION_GRACE_S:
        return False
    try:
        lease = json.loads(path.read_text(encoding="utf-8"))
        pid = int(lease.get("pid") or 0) if isinstance(lease, dict) else 0
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        pid = 0
    if pid and _pid_is_alive(pid):
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return True


@contextmanager
def _file_lock(
    out_dir: Path,
    name: str,
    *,
    timeout_s: float = _LOCK_TIMEOUT_S,
    stale_after_s: float = _LOCK_STALE_AFTER_S,
) -> Iterator[None]:
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    with _process_lock_for(root, name):
        lock_path = root / name
        deadline = time.monotonic() + timeout_s
        fd: int | None = None
        while fd is None:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if _remove_stale_lock(lock_path, stale_after_s):
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for omission lock: {lock_path}")
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


@contextmanager
def extraction_operation_lock(out_dir: Path, *, operation: str) -> Iterator[None]:
    """Serialize full and targeted extraction across threads and processes."""
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    process_lock = _process_lock_for(root, _EXTRACTION_OPERATION_LOCK)
    if not process_lock.acquire(blocking=False):
        raise OmissionConflictError("another full or targeted AI extraction is running")
    lock_path = root / _EXTRACTION_OPERATION_LOCK
    fd: int | None = None
    try:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if _remove_abandoned_operation_lock(lock_path):
                try:
                    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError as exc:
                    raise OmissionConflictError(
                        "another full or targeted AI extraction is running"
                    ) from exc
            else:
                raise OmissionConflictError("another full or targeted AI extraction is running")
        lease = json.dumps({
            "pid": os.getpid(),
            "operation": str(operation or "unknown"),
            "started_at": _utc_now(),
        }, separators=(",", ":"))
        os.write(fd, lease.encode("utf-8"))
        yield
    finally:
        if fd is not None:
            os.close(fd)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
        process_lock.release()


@contextmanager
def _targeted_operation_lock(out_dir: Path) -> Iterator[None]:
    with extraction_operation_lock(out_dir, operation="targeted"):
        yield


def _read_append_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        return read_jsonl_recover_torn_tail(path)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        rows: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    LOGGER.warning("skipping corrupt %s record at line %d", path.name, line_number)
                    continue
                if isinstance(row, dict):
                    rows.append(row)
        return rows


def _append_fsynced(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _block_by_id(out_dir: Path, block_id: str) -> dict[str, Any]:
    for block in read_jsonl(Path(out_dir) / "blocks.jsonl"):
        if str(block.get("block_id") or "") == block_id:
            return block
    raise ValueError(f"unknown block_id: {block_id}")


def read_omission_states(out_dir: Path) -> dict[str, dict[str, Any]]:
    root = Path(out_dir).expanduser().resolve()
    latest: dict[str, dict[str, Any]] = {}
    with _file_lock(root, "omission_states.lock"):
        for row in _read_append_log(root / OMISSION_STATES):
            omission_id = str(row.get("omission_id") or "")
            if omission_id:
                latest[omission_id] = row
    return latest


def read_current_omission_states(out_dir: Path) -> dict[str, dict[str, Any]]:
    """Return only states whose omission identity still matches the current source block."""
    root = Path(out_dir).expanduser().resolve()
    latest = read_omission_states(root)
    current: dict[str, dict[str, Any]] = {}
    for block in read_jsonl(root / "blocks.jsonl"):
        block_id = str(block.get("block_id") or "")
        if not block_id:
            continue
        omission_id = make_omission_id(block_id, str(block.get("text") or ""))
        state = latest.get(omission_id)
        if state is not None:
            current[omission_id] = state
    return current


def _read_jsonl_bytes_readonly(
    path: Path,
    raw: bytes | None,
    *,
    label: str,
) -> list[dict[str, Any]]:
    if raw is None:
        return []
    rows: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(raw.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"invalid {label} row {line_number} during read-only read"
            ) from exc
        if not isinstance(row, dict):
            raise ValueError(
                f"invalid {label} row {line_number} during read-only read"
            )
        rows.append(row)
    return rows


def read_current_omission_states_readonly(out_dir: Path) -> dict[str, dict[str, Any]]:
    """Read compatibility omissions without a lock, recovery, or sidecar writes."""
    root = Path(out_dir).expanduser().resolve()
    states_path = root / OMISSION_STATES
    blocks_path = root / "blocks.jsonl"
    states_before = states_path.read_bytes() if states_path.is_file() else None
    blocks_before = blocks_path.read_bytes() if blocks_path.is_file() else None
    latest: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl_bytes_readonly(
        states_path,
        states_before,
        label=OMISSION_STATES,
    ):
        omission_id = str(row.get("omission_id") or "")
        if omission_id:
            latest[omission_id] = row
    current: dict[str, dict[str, Any]] = {}
    for block in _read_jsonl_bytes_readonly(
        blocks_path,
        blocks_before,
        label="blocks.jsonl",
    ):
        block_id = str(block.get("block_id") or "")
        if not block_id:
            continue
        omission_id = make_omission_id(block_id, str(block.get("text") or ""))
        state = latest.get(omission_id)
        if state is not None:
            current[omission_id] = state
    states_after = states_path.read_bytes() if states_path.is_file() else None
    blocks_after = blocks_path.read_bytes() if blocks_path.is_file() else None
    if states_after != states_before or blocks_after != blocks_before:
        raise ValueError("omission authority changed during read-only read")
    return current


def current_non_requirement_block_ids(out_dir: Path) -> set[str]:
    """Return source-current blocks explicitly triaged as non-requirements."""
    return {
        str(state.get("block_id") or "")
        for state in read_current_omission_states(out_dir).values()
        if state.get("status") == "non_requirement" and str(state.get("block_id") or "")
    }


def _failed_section_block_ids(root: Path) -> set[str]:
    """Failed-section blocks recorded by the last extraction quality report.

    Same source the agent queue scope aggregates (agent_state); a missing or
    corrupt quality report degrades to the uncovered-only candidate scope.
    """
    try:
        quality = json.loads((root / "ai_extract_quality.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(quality, dict):
        return set()
    values = quality.get("failed_section_block_ids")
    if not isinstance(values, list):
        return set()
    return {str(value) for value in values if str(value)}


def current_omission_candidate_ids(out_dir: Path) -> set[str]:
    """Recompute the current uncovered denominator instead of trusting stale UI/report state.

    The candidate scope is uncovered blocks union failed-section blocks: leftover
    requirements or cross-section quotes can keep a failed block out of the
    recomputed uncovered set, yet a registered failed block must still be
    extractable via targeted_reextract (agent queue scope parity).
    """
    root = Path(out_dir).expanduser().resolve()
    blocks = read_jsonl(root / "blocks.jsonl")
    requirements_path = root / "ai_requirements.jsonl"
    requirements = read_jsonl(requirements_path) if requirements_path.exists() else []
    from merged_consistency import coverage_denominator_blocks, layered_coverage

    denominator = coverage_denominator_blocks(blocks)
    coverage = layered_coverage(
        requirements,
        denominator,
        source_blocks=blocks,
        expert_excluded_block_ids=current_non_requirement_block_ids(root),
    )
    uncovered = list(coverage.get("uncovered_block_ids") or [])
    uncovered.extend((coverage.get("compliance") or {}).get("uncovered_block_ids") or [])
    candidates = {str(value) for value in uncovered if str(value)}
    known_block_ids = {str(block.get("block_id") or "") for block in blocks}
    candidates |= _failed_section_block_ids(root) & known_block_ids
    return candidates


def apply_omission_action(
    out_dir: Path,
    *,
    block_id: str,
    status: str,
    omission_id: str | None = None,
    reason: str = "",
    actor: str | None = None,
    expected_source_fingerprint: str = "",
) -> dict[str, Any]:
    root = Path(out_dir).expanduser().resolve()
    block_id = str(block_id or "").strip()
    if not block_id:
        raise ValueError("block_id is required")
    status = str(status or "").strip()
    if status not in VALID_OMISSION_STATUS:
        raise ValueError(f"invalid omission status: {status}")
    with _file_lock(root, "omission_states.lock"):
        block = _block_by_id(root, block_id)
        text = str(block.get("text") or "")
        source_fp = omission_source_fingerprint(block_id, text)
        if expected_source_fingerprint and expected_source_fingerprint != source_fp:
            raise OmissionConflictError("omission source changed; refresh before adjudicating")
        expected_id = make_omission_id(block_id, text)
        resolved_id = str(omission_id or "").strip() or expected_id
        if resolved_id != expected_id:
            raise OmissionConflictError("omission identity changed; refresh before adjudicating")
        state = {
            "omission_id": resolved_id,
            "status": status,
            "block_id": block_id,
            "source_fingerprint": source_fp,
            "reason": str(reason or ""),
            "actor": actor,
            "recorded_at": _utc_now(),
        }
        _append_fsynced(root / OMISSION_STATES, state)
    return state


def read_supplement_patches(out_dir: Path) -> list[dict[str, Any]]:
    root = Path(out_dir).expanduser().resolve()
    with _file_lock(root, "ai_supplements.lock"):
        return _read_append_log(root / AI_SUPPLEMENTS)


def supplement_strategy_fingerprint(model: str) -> str:
    from ai_extract import (
        AI_EXTRACT_PROMPT_VERSION,
        AI_VERIFY_PROMPT_VERSION,
        EXTRACT_GUARDS_VERSION,
    )

    return _canonical_hash({
        "version": AI_SUPPLEMENT_VERSION,
        "extract_prompt": AI_EXTRACT_PROMPT_VERSION,
        "verify_prompt": AI_VERIFY_PROMPT_VERSION,
        "guards": EXTRACT_GUARDS_VERSION,
        "model": str(model),
        "strategy": "critique_section.focus_lines",
    })


def _patch_is_current(patch: dict[str, Any], blocks: dict[str, dict[str, Any]]) -> bool:
    if patch.get("strategy_version") != AI_SUPPLEMENT_VERSION:
        return False
    model = str(patch.get("model") or "")
    if str(patch.get("strategy_fingerprint") or "") != supplement_strategy_fingerprint(model):
        return False
    block_id = str(patch.get("block_id") or "")
    block = blocks.get(block_id)
    if not block:
        return False
    current_source = omission_source_fingerprint(block_id, str(block.get("text") or ""))
    return current_source == str(patch.get("source_fingerprint") or "")


def apply_supplement_patches(
    out_dir: Path, base_requirements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Replay valid upserts in log order while preserving base ordering."""
    from ai_review_actions import (
        ensure_requirement_identity,
        review_anchor_fingerprint,
        review_subject_fingerprint,
        source_ai_requirement_id,
        source_fingerprint,
    )

    root = Path(out_dir).expanduser().resolve()
    rows = [copy.deepcopy(row) for row in base_requirements if isinstance(row, dict)]
    index = {source_ai_requirement_id(row): position for position, row in enumerate(rows)}
    blocks = {
        str(block.get("block_id") or ""): block
        for block in read_jsonl(root / "blocks.jsonl")
        if block.get("block_id")
    }
    for patch in read_supplement_patches(root):
        if not _patch_is_current(patch, blocks):
            continue
        preconditions = patch.get("preconditions")
        if not isinstance(preconditions, dict):
            continue
        extraction_fp = f"supplement:{str(patch.get('strategy_fingerprint') or '')[:24]}"
        for raw in patch.get("upserts") or []:
            if not isinstance(raw, dict):
                continue
            row = copy.deepcopy(raw)
            ensure_requirement_identity(row, extraction_fingerprint=extraction_fp)
            rid = source_ai_requirement_id(row)
            position = index.get(rid)
            precondition = preconditions.get(rid)
            if not isinstance(precondition, dict):
                continue
            source_blocks = precondition.get("source_blocks")
            if not isinstance(source_blocks, dict):
                continue
            if any(
                block_id not in blocks
                or expected != omission_source_fingerprint(
                    block_id, str(blocks[block_id].get("text") or "")
                )
                for block_id, expected in source_blocks.items()
            ):
                continue
            if precondition.get("base_absent"):
                if position is not None:
                    # A later full extraction now owns this logical row. Never replace it with
                    # an older supplement; identical content needs no patch replay.
                    continue
                row_source = source_fingerprint(row)
                if any(source_fingerprint(current) == row_source for current in rows):
                    continue
                source_block_ids = [
                    str(value) for value in (row.get("source_block_ids") or []) if str(value)
                ]
                if source_block_ids:
                    row_anchor = review_anchor_fingerprint(row)
                    anchor_matches = [
                        current for current in rows
                        if review_anchor_fingerprint(current) == row_anchor
                    ]
                    if len(anchor_matches) == 1:
                        # A fresh full extraction produced one logical row on the same source
                        # anchor under a new title/quote/id. Prefer that current row.
                        continue
                index[rid] = len(rows)
                rows.append(row)
                continue
            if position is None:
                continue
            current = rows[position]
            if str(precondition.get("source_fingerprint") or "") != source_fingerprint(current):
                continue
            if (str(precondition.get("review_subject_fingerprint") or "")
                    != review_subject_fingerprint(current)):
                continue
            rows[position] = row
    return rows


def extraction_in_progress(out_dir: Path) -> bool:
    root = Path(out_dir).expanduser().resolve()
    manifest_path = root / "run_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        manifest = {}
    stages = manifest.get("stages") if isinstance(manifest, dict) else None
    entry = stages.get("ai-extract") if isinstance(stages, dict) else None
    if isinstance(entry, dict) and entry.get("status") == "running":
        return True

    from ai_extract import AI_REQUIREMENTS_PARTIAL, read_partial_snapshot

    partial_path = root / AI_REQUIREMENTS_PARTIAL
    partial = read_partial_snapshot(partial_path)
    if partial and not partial.get("complete") and not partial.get("failed"):
        try:
            return time.time() - partial_path.stat().st_mtime < _OPERATION_STALE_AFTER_S
        except OSError:
            return True
    return False


def _find_target_section(out_dir: Path, block_id: str) -> tuple[
    list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]
]:
    import ai_extract

    blocks = ai_extract.body_blocks(read_jsonl(Path(out_dir) / "blocks.jsonl"))
    mode = (os.environ.get(ai_extract.UNIT_MODE_ENV) or "clause").strip().lower()
    if mode not in ("clause", "chapter"):
        mode = "clause"
    sections = ai_extract.merge_sections(
        ai_extract.assemble_sections(blocks),
        target_chars=ai_extract.DEFAULT_MERGE_CHARS,
        unit_mode=mode,
    )
    ai_extract.resolve_section_refs(sections)
    ai_extract.attach_term_definitions(sections, ai_extract.collect_term_entries(sections))
    ai_extract._annotate_annex_scopes(sections)
    for section in sections:
        if block_id in {str(value) for value in (section.get("block_ids") or [])}:
            return blocks, section, sections
    raise ValueError(f"block is outside extractable document body: {block_id}")


def _validated_focus_lines(section: dict[str, Any], requested: list[str], fallback: str) -> list[str]:
    section_text = " ".join(str(section.get("text") or "").split()).lower()
    accepted: list[str] = []
    for value in requested:
        line = str(value or "").strip()
        if line and " ".join(line.split()).lower() in section_text:
            accepted.append(line)
    if accepted:
        return accepted[:12]
    if any(str(value or "").strip() for value in requested):
        return []
    fallback = str(fallback or "").strip()
    return [fallback] if fallback else []


def _append_patch_once(out_dir: Path, patch: dict[str, Any]) -> dict[str, Any]:
    root = Path(out_dir).expanduser().resolve()
    with _file_lock(root, "ai_supplements.lock"):
        existing = _read_append_log(root / AI_SUPPLEMENTS)
        for row in existing:
            if row.get("supplement_id") == patch.get("supplement_id"):
                return row
        _append_fsynced(root / AI_SUPPLEMENTS, patch)
    return patch


def targeted_reextract(
    out_dir: Path,
    *,
    block_id: str,
    omission_id: str | None = None,
    focus_lines: list[str] | None = None,
    actor: str | None = None,
    reason: str = "",
    route: str = "openai_compatible",
    expected_source_fingerprint: str = "",
) -> dict[str, Any]:
    """Run one guarded critique pass for an omitted source block and persist upserts."""
    import ai_extract
    from ai_review_actions import (
        ensure_requirement_identity,
        review_subject_fingerprint,
        source_ai_requirement_id,
        source_fingerprint,
    )
    from llm_client import apply_min_tokens, chat_json

    root = Path(out_dir).expanduser().resolve()
    block_id = str(block_id or "").strip()
    if not block_id:
        raise ValueError("block_id is required")
    if route != "openai_compatible":
        raise ValueError("targeted omission extraction requires openai_compatible route")
    with _targeted_operation_lock(root):
        from api_server import final_ai_requirements_are_stale

        if final_ai_requirements_are_stale(root):
            raise OmissionConflictError(
                "AI extraction belongs to an older parsed document; rerun full extraction first"
            )
        if not ai_extract.ai_requirements_producer_is_current(root):
            raise OmissionConflictError(
                "AI extraction belongs to an older producer version; rerun full extraction first"
            )
        if block_id not in current_omission_candidate_ids(root):
            raise OmissionConflictError(
                "block is no longer an uncovered requirement candidate; refresh before extracting"
            )
        block = _block_by_id(root, block_id)
        block_text = str(block.get("text") or "")
        current_omission_fingerprint = omission_source_fingerprint(block_id, block_text)
        if (expected_source_fingerprint
                and expected_source_fingerprint != current_omission_fingerprint):
            raise OmissionConflictError("omission source changed; refresh before targeted extraction")
        resolved_omission_id = str(omission_id or "").strip() or make_omission_id(block_id, block_text)
        apply_omission_action(
            root,
            block_id=block_id,
            omission_id=resolved_omission_id,
            status="issue_confirmed",
            reason=reason,
            actor=actor,
            expected_source_fingerprint=current_omission_fingerprint,
        )

        blocks, section, _sections = _find_target_section(root, block_id)
        current = read_jsonl(root / ai_extract.AI_REQUIREMENTS)
        section_block_ids = {str(value) for value in (section.get("block_ids") or [])}
        existing_original = [
            row for row in current
            if section_block_ids.intersection(
                str(value) for value in (row.get("source_block_ids") or [])
            )
        ]
        existing = copy.deepcopy(existing_original)
        requested = [str(value) for value in (focus_lines or [])]
        focused = _validated_focus_lines(section, requested, block_text)
        if not focused:
            raise ValueError("omission block has no extractable text")

        config = ai_extract.config_for_route(route)
        if config is None:
            raise ValueError("openai_compatible route is not configured")
        config = apply_min_tokens(config, "extract")

        def chat(system: str, user: str) -> dict[str, Any]:
            return chat_json(config, system, user)

        doc_context = ai_extract.build_doc_context(root, blocks)
        context_ints = frozenset(ai_extract.extract_ints(doc_context)) if doc_context else frozenset()
        extra, _supplements = ai_extract.critique_section(
            section,
            existing,
            chat,
            doc_context,
            context_ints,
            focus_lines=focused,
        )

        strategy_fp = supplement_strategy_fingerprint(config.model)
        before_by_id = {source_ai_requirement_id(row): row for row in existing_original}
        upserts: list[dict[str, Any]] = []
        for row in existing:
            rid = source_ai_requirement_id(row)
            before = before_by_id.get(rid)
            if before is not None and review_subject_fingerprint(before) == review_subject_fingerprint(row):
                continue
            ensure_requirement_identity(row, extraction_fingerprint=f"supplement:{strategy_fp[:24]}")
            upserts.append(row)
        prepared_extra = ai_extract._prepare_requirement_rows(extra, f"supplement:{strategy_fp[:24]}")
        upserts.extend(prepared_extra)
        if not upserts:
            raise OmissionNoResultError("targeted extraction produced no guarded requirement changes")

        source_fp = current_omission_fingerprint
        current_blocks = {str(item.get("block_id") or ""): item for item in blocks}
        preconditions: dict[str, dict[str, Any]] = {}
        for row in upserts:
            rid = source_ai_requirement_id(row)
            before = before_by_id.get(rid)
            evidence_row = before if before is not None else row
            source_blocks = {
                source_block_id: omission_source_fingerprint(
                    source_block_id, str(current_blocks[source_block_id].get("text") or "")
                )
                for source_block_id in (
                    str(value) for value in (evidence_row.get("source_block_ids") or [])
                )
                if source_block_id in current_blocks
            }
            if before is None:
                preconditions[rid] = {
                    "base_absent": True,
                    "source_blocks": source_blocks,
                }
                continue
            preconditions[rid] = {
                "base_absent": False,
                "source_fingerprint": source_fingerprint(before),
                "review_subject_fingerprint": review_subject_fingerprint(before),
                "source_blocks": source_blocks,
            }
        content_key = [
            (source_ai_requirement_id(row), review_subject_fingerprint(row))
            for row in upserts
        ]
        supplement_id = "SUP-" + hashlib.sha1(
            json.dumps(
                [resolved_omission_id, source_fp, strategy_fp, content_key, preconditions],
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:12]
        patch = {
            "schema": "ai-supplement/v2",
            "supplement_id": supplement_id,
            "omission_id": resolved_omission_id,
            "block_id": block_id,
            "source_fingerprint": source_fp,
            "strategy_version": AI_SUPPLEMENT_VERSION,
            "strategy_fingerprint": strategy_fp,
            "model": config.model,
            "focus_lines": focused,
            "upserts": upserts,
            "preconditions": preconditions,
            "actor": actor,
            "reason": str(reason or ""),
            "recorded_at": _utc_now(),
        }
        patch = _append_patch_once(root, patch)
        effective = apply_supplement_patches(root, current)
        effective_by_id = {source_ai_requirement_id(row): row for row in effective}
        unapplied = [
            source_ai_requirement_id(row)
            for row in upserts
            if source_ai_requirement_id(row) not in effective_by_id
            or review_subject_fingerprint(effective_by_id[source_ai_requirement_id(row)])
            != review_subject_fingerprint(row)
        ]
        if unapplied:
            raise OmissionConflictError(
                "targeted extraction inputs changed before publish; refresh and retry"
            )
        ai_extract.atomic_write_jsonl(root / ai_extract.AI_REQUIREMENTS, effective)
        ai_extract.write_compliance_requirements(root, effective)

        partial = ai_extract.read_partial_snapshot(root / ai_extract.AI_REQUIREMENTS_PARTIAL)
        quality = ai_extract.refresh_ai_extract_quality(root, effective)
        ai_extract.write_ai_requirements_metadata(
            root,
            input_fingerprint=ai_extract.extraction_input_fingerprint(root),
            run_id=str((partial or {}).get("run_id") or "targeted"),
            failed_sections=int(quality.get("failed_sections") or 0),
            failed_section_ids=list(quality.get("failed_section_ids") or []),
        )
        if partial and partial.get("complete"):
            ai_extract.write_partial_snapshot(
                root / ai_extract.AI_REQUIREMENTS_PARTIAL,
                run_id=str(partial["run_id"]),
                completed=int(partial.get("completed") or 0),
                total=int(partial.get("total") or 0),
                complete=True,
                failed=bool(partial.get("failed")),
                error=str(partial.get("error") or ""),
                rows=effective,
                input_fingerprint=str(partial.get("input_fingerprint") or ""),
            )
        elif partial:
            # A stale abandoned/incomplete generation must not keep shadowing the newly
            # published effective file after a successful targeted repair.
            (root / ai_extract.AI_REQUIREMENTS_PARTIAL).unlink(missing_ok=True)
        rebuilt = ai_extract.rebuild_merged_spec(root)
        omission = apply_omission_action(
            root,
            block_id=block_id,
            omission_id=resolved_omission_id,
            status="resolved",
            reason=reason,
            actor=actor,
            expected_source_fingerprint=current_omission_fingerprint,
        )
        written = [
            ai_extract.AI_REQUIREMENTS,
            ai_extract.AI_REQUIREMENTS_META,
            ai_extract.COMPLIANCE_REQUIREMENTS,
            "ai_extract_quality.json",
            AI_SUPPLEMENTS,
        ]
        written.extend(str(value) for value in (rebuilt.get("written") or []))
        return {
            "schema": "omission-reextract/v1",
            "omission": omission,
            "supplement": patch,
            "requirements": len(upserts),
            "effective_count": len(effective),
            "written": list(dict.fromkeys(written)),
        }
