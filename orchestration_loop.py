"""T2-2/T2-3 编排环：把"文档→需求→澄清→答复→再分析"从人工接力变成 agent 闭环。

每轮：读缺口（``orchestration_gaps``）→ 选最高严重度的 *可自动处置* 缺口 → 经既有
``allow_llm`` 授权通道发起 spot_extract/targeted_reextract（复用现有授权与预算扣减机制；
预算耗尽或授权缺失则转人工并如实记录）→ 写 ``orchestration_trace.jsonl`` → 重算缺口，
直到收敛或达上限。

纪律（与 Phase 1 一致）：
- 编排环只决定"该看哪里"，裁决仍在专家面板——spot_extract/targeted_reextract 的产物是
  **draft/补充**，进澄清待确认或既有审计流，绝不自动转正。
- 失败/未授权/不可执行的缺口如实记 skipped 或转人工，**绝不报成 completed**。
- 收敛保证：每个 target_id 在一次运行内只被处置一次（``addressed`` 集合），无论该缺口在
  重算后是否仍在产物里（conservation/sampling 这类要靠各自 publisher 重算才能在产物里真正
  消失，编排环不等它）。trace 的 ``extract_working`` 因此单调不增直至 0（收敛）或达上限。
- 每文档最大编排轮次上限默认 8（``RATOMIZER_ORCHESTRATION_MAX_ROUNDS``），达上限未收敛 →
  文档 NEEDS WORK 交人，不无限循环。

T2-3：verification 反哺候选（test_completed=否 / 实现偏差）由缺口层读取，本 loop 写入
``orchestration_revision_candidates.jsonl``（人工确认队列，provenance 标 orchestration，
绝不自动改需求）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterator
from contextlib import contextmanager

from jsonschema import Draft202012Validator, FormatChecker

from orchestration_gaps import (
    ACTION_HUMAN_REVIEW,
    ACTION_SPOT_EXTRACT,
    ACTION_TARGETED_REEXTRACT,
    ORCHESTRATION_GAP_VERSION,
    ORCHESTRATION_POLICY_VERSION,
    ROUTE_EXTRACT,
    Gap,
    GapReport,
    VerificationCandidate,
    gap_report_summary,
    read_gaps,
)
from result_package import governed_artifact_path


DEFAULT_MAX_ROUNDS = 8
MAX_ROUNDS_HARD_LIMIT = 50

ORCHESTRATION_TRACE_VERSION = "orchestration-trace-v1"
ORCHESTRATION_SUMMARY_SCHEMA = "orchestration-summary/v1"
ORCHESTRATION_TRACE_FILE = "orchestration_trace.jsonl"
ORCHESTRATION_SUMMARY_FILE = "orchestration_summary.json"
ORCHESTRATION_CANDIDATES_FILE = "orchestration_revision_candidates.jsonl"
ORCHESTRATION_CANDIDATES_VERSION = "orchestration-revision-candidates-v1"
TRACE_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "orchestration_trace.schema.json"

ENVELOPE_SCHEMA_VERSION = "1.0"

_REPLACE_ATTEMPTS = 5
_REPLACE_RETRY_DELAY_S = 0.02
_APPEND_ATTEMPTS = 5
_APPEND_RETRY_DELAY_S = 0.02
_LOCK_TIMEOUT_S = 10.0
_LOCK_STALE_AFTER_S = 300.0

_PROCESS_LOCKS: dict[Path, RLock] = {}
_PROCESS_LOCKS_GUARD = RLock()
_VALIDATOR: Draft202012Validator | None = None


class OrchestrationLoopInputError(ValueError):
    """编排环入参越界（轮次、目录等）。"""


class OrchestrationGapReadError(RuntimeError):
    """缺口读取层在最小产物齐备时仍失败（包装底层异常，CLI 退 3）。"""


StateReader = Callable[[Path], GapReport]
ActionRunner = Callable[[Path, Gap, str, str, str], dict[str, Any]]


def run_orchestration_loop(
    out_dir: Path,
    *,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    allow_llm: bool = False,
    actor: str = "orchestration-loop",
    state_reader: StateReader = read_gaps,
    action_runner: ActionRunner | None = None,
) -> dict[str, Any]:
    """运行一次缺口驱动的编排环，返回 summary（并写 trace/summary/candidates 产物）。

    ``allow_llm`` 关闭或 openai_compatible 路由未配置/无 key 时，所有 extract-route 缺口
    一次性转人工（一条 trace 如实记录），outcome="unauthorized"。``action_runner`` 注入用
    于测试（默认走真实 spot_extract/targeted_reextract）。
    """
    if not 1 <= int(max_rounds) <= MAX_ROUNDS_HARD_LIMIT:
        raise OrchestrationLoopInputError(
            f"max_rounds must be between 1 and {MAX_ROUNDS_HARD_LIMIT}"
        )
    root = Path(out_dir).expanduser().resolve()
    authorized = bool(allow_llm) and _llm_authorized()
    runner = action_runner or _default_action_runner
    run_id = _resolve_run_id(root)

    # 首轮缺口快照（也用于 unauthorized 分支的一次性记录）。
    try:
        first_report = state_reader(root)
    except OrchestrationGapReadError:
        raise
    except Exception as exc:  # noqa: BLE001 — 包装底层读取异常供 CLI 分类
        raise OrchestrationGapReadError(str(exc)) from exc

    # T2-3：把 verification 反哺候选写入人工确认队列（幂等；每运行一次刷新一次）。
    candidate_write = _write_revision_candidates(root, first_report.verification_candidates, actor)

    addressed: set[str] = set()
    rounds_used = 0
    termination = "converged"
    last_action = ""
    action_counts: dict[str, int] = {}
    failed_actions: list[dict[str, Any]] = []
    extract_total_seen = len(first_report.extract_gaps)
    human_gaps_total = len(first_report.human_gaps)
    verification_total = len(first_report.verification_candidates)

    # 未授权 + 存在 extract 缺口：一次性如实转人工（不逐轮浪费预算），outcome=unauthorized。
    if extract_total_seen > 0 and not authorized:
        rounds_used = 1
        digest = _state_digest(first_report, working=first_report.extract_gaps,
                                addressed=addressed, authorized=authorized)
        summary_text = (
            f"LLM 未授权（allow_llm={allow_llm}, openai_compatible 路由/key 缺失），"
            f"{extract_total_seen} 个可补抽缺口全部转人工处置"
        )
        _append_trace(root, {
            "trace_version": ORCHESTRATION_TRACE_VERSION,
            "policy_version": ORCHESTRATION_POLICY_VERSION,
            "run_id": run_id,
            "round": 1,
            "ts": _utc_now(),
            "state_digest": digest,
            "candidates": [ACTION_HUMAN_REVIEW, "stop"],
            "action": ACTION_HUMAN_REVIEW,
            "decider": "rule",
            "reason": summary_text,
            "gap": None,
            "budget": {"rounds_used": 1, "rounds_max": int(max_rounds), "llm_authorized": False},
            "result": {"status": "skipped", "summary": summary_text},
        })
        termination = "unauthorized"
        last_action = ACTION_HUMAN_REVIEW
        action_counts[ACTION_HUMAN_REVIEW] = extract_total_seen
    else:
        converged = False
        for round_index in range(1, int(max_rounds) + 1):
            rounds_used = round_index
            try:
                report = state_reader(root)
            except Exception as exc:  # noqa: BLE001
                raise OrchestrationGapReadError(str(exc)) from exc

            # working = 本轮 extract-route 缺口 − 已处置目标。收敛保证：每个 target_id 在
            # 一次运行内只处置一次（``addressed``），故 extract_working 单调不增。spot_extract/
            # targeted_reextract 写 ai_requirements/supplements，不写 functional_requirements /
            # claim_sampling_summary，因此 extract 缺口（守恒/抽检）不会因补抽新增——working
            # 只会随处置收缩，直至 0（收敛）或达上限。
            working = tuple(
                gap for gap in report.extract_gaps
                if gap.target_id not in addressed
            )
            digest = _state_digest(report, working=working, addressed=addressed,
                                    authorized=authorized)

            if not working:
                _append_trace(root, {
                    "trace_version": ORCHESTRATION_TRACE_VERSION,
                    "policy_version": ORCHESTRATION_POLICY_VERSION,
                    "run_id": run_id,
                    "round": round_index,
                    "ts": _utc_now(),
                    "state_digest": digest,
                    "candidates": ["stop"],
                    "action": "stop",
                    "decider": "rule",
                    "reason": _stop_reason(report, addressed),
                    "gap": None,
                    "budget": {"rounds_used": round_index, "rounds_max": int(max_rounds),
                               "llm_authorized": authorized},
                    "result": {"status": "ok", "summary": _stop_summary(report, addressed)},
                })
                termination = "converged" if addressed else "no_extract_gaps"
                last_action = "stop"
                action_counts["stop"] = action_counts.get("stop", 0) + 1
                converged = True
                break

            gap = working[0]
            concrete_action = _resolve_concrete_action(root, gap)
            candidates = [concrete_action, "stop"] if concrete_action != "stop" else ["stop"]
            try:
                result = runner(root, gap, concrete_action, actor, run_id)
                _validate_action_result(result)
            except Exception as exc:  # noqa: BLE001 — 任何执行异常如实落 trace，不报 completed
                result = {"status": "error",
                          "summary": f"{type(exc).__name__}: {exc}"}
                failed_actions.append({
                    "round": round_index,
                    "target_id": gap.target_id,
                    "action": concrete_action,
                    "error": str(exc),
                })

            status = str(result.get("status") or "error")
            action_counts[concrete_action] = action_counts.get(concrete_action, 0) + 1
            addressed.add(gap.target_id)
            last_action = concrete_action

            _append_trace(root, {
                "trace_version": ORCHESTRATION_TRACE_VERSION,
                "policy_version": ORCHESTRATION_POLICY_VERSION,
                "run_id": run_id,
                "round": round_index,
                "ts": _utc_now(),
                "state_digest": digest,
                "candidates": candidates,
                "action": concrete_action,
                "decider": "rule",
                "reason": _action_reason(gap, concrete_action, authorized),
                "gap": _gap_to_trace(gap),
                "budget": {"rounds_used": round_index, "rounds_max": int(max_rounds),
                           "llm_authorized": authorized},
                "result": {"status": status, "summary": str(result.get("summary") or "")},
            })

            budget_exhausted = (
                round_index == int(max_rounds)
                and concrete_action != "stop"
            )
            if budget_exhausted:
                termination = "rounds_exhausted"
                break

        if not converged:
            # 用尽轮次后做一次终态判定：若此时 extract 缺口已全部处置（working 空），如实
            # 记 converged；仅当仍有未处置缺口才记 rounds_exhausted（避免"刚好处置完却报
            # 超限"的过度告警）。读取失败则保守保持 rounds_exhausted。
            termination = "rounds_exhausted"
            try:
                final_report = state_reader(root)
                final_working = tuple(
                    gap for gap in final_report.extract_gaps
                    if gap.target_id not in addressed
                )
                if not final_working:
                    termination = "converged"
            except OrchestrationGapReadError:
                pass

    needs_work = (
        termination in {"rounds_exhausted", "unauthorized"}
        or human_gaps_total > 0
        or verification_total > 0
        # 收敛后仍可能残留未被处置的 extract 缺口（本轮未触达，理论上 working 已空则无）
    )
    summary = _build_summary(
        root=root,
        run_id=run_id,
        rounds_used=rounds_used,
        rounds_max=int(max_rounds),
        authorized=authorized,
        termination=termination,
        last_action=last_action,
        action_counts=action_counts,
        failed_actions=failed_actions,
        extract_total=extract_total_seen,
        extract_addressed=len(addressed),
        human_gaps=human_gaps_total,
        verification_candidates=verification_total,
        needs_work=bool(needs_work),
        candidate_write=candidate_write,
    )
    _write_summary(root, summary)
    return summary


# ---------------------------------------------------------------------------
# 缺口 → 动作执行（既有 allow_llm 授权通道：spot_extract / targeted_reextract）
# ---------------------------------------------------------------------------


def _default_action_runner(
    root: Path, gap: Gap, action: str, actor: str, run_id: str
) -> dict[str, Any]:
    """生产执行器：经 openai_compatible 路由复用既有 spot_extract / targeted_reextract。

    omission 候选块走 targeted_reextract（正式补抽、关 omission、过护栏）；其余 extract 缺口
    走 spot_extract（产 draft 进澄清待确认，裁决仍归专家）。资格不符（targeted_reextract 抛
    OmissionConflictError）自动降级 spot_extract——绝不静默放弃或伪造完成。
    """
    block_id = str(gap.block_id or "")
    if action == ACTION_TARGETED_REEXTRACT and block_id:
        try:
            return _run_targeted_reextract(root, block_id, actor, run_id, gap)
        except _OmissionIneligible:
            return _run_spot_extract(root, block_id, actor, gap)
    if action == ACTION_SPOT_EXTRACT and block_id:
        return _run_spot_extract(root, block_id, actor, gap)
    # 兜底：没有可用 block_id 的 extract 缺口（异常形态）如实转人工，不伪造。
    return {
        "status": "skipped",
        "summary": (
            f"缺口 {gap.target_id}（{gap.kind}）无可定位 block_id，转人工处置"
        ),
    }


class _OmissionIneligible(Exception):
    """块不是当前 omission 候选——targeted_reextract 不适用，降级 spot_extract。"""


def _run_targeted_reextract(
    root: Path, block_id: str, actor: str, run_id: str, gap: Gap
) -> dict[str, Any]:
    import omission_actions

    if block_id not in omission_actions.current_omission_candidate_ids(root):
        raise _OmissionIneligible(block_id)
    block = _block_text(root, block_id)
    payload = omission_actions.targeted_reextract(
        root,
        block_id=block_id,
        actor=actor,
        reason=f"orchestration:{gap.kind}:{gap.target_id} (run {run_id})",
        route="openai_compatible",
        expected_source_fingerprint=omission_actions.omission_source_fingerprint(block_id, block),
    )
    return {
        "status": "ok",
        "summary": f"targeted_reextract 完成：{block_id}（{gap.kind}）",
        "details": payload,
    }


def _run_spot_extract(root: Path, block_id: str, actor: str, gap: Gap) -> dict[str, Any]:
    import spot_extract

    payload = spot_extract.spot_extract(
        root,
        block_id=block_id,
        route="openai_compatible",
        actor=actor,
        reason=f"orchestration:{gap.kind}:{gap.target_id}",
    )
    drafts = int(payload.get("drafts") or 0)
    return {
        "status": "ok",
        "summary": (
            f"spot_extract 完成：{block_id}（{gap.kind}）→ {drafts} 条 draft 进澄清待确认"
            + ("（该段已被现有需求覆盖）" if payload.get("already_covered") else "")
        ),
        "details": payload,
    }


def _resolve_concrete_action(root: Path, gap: Gap) -> str:
    """读取层推荐动作 → 本轮可执行动作（资格核验在 runner 内做降级）。"""
    if gap.route != ROUTE_EXTRACT:
        return ACTION_HUMAN_REVIEW
    if gap.action == ACTION_TARGETED_REEXTRACT and gap.block_id:
        return ACTION_TARGETED_REEXTRACT
    return ACTION_SPOT_EXTRACT


def _llm_authorized() -> bool:
    """openai_compatible 路由是否已配置且 key 在位（与 agent_loop._llm_config_for_decider 同口径）。"""
    try:
        from ai_extract import config_for_route
    except Exception:  # noqa: BLE001
        return False
    try:
        config = config_for_route("openai_compatible")
    except Exception:  # noqa: BLE001
        return False
    if config is None:
        return False
    key_env = str(getattr(config, "api_key_env", "") or "")
    return bool(key_env and os.environ.get(key_env, "").strip())


# ---------------------------------------------------------------------------
# T2-3：verification 反哺候选 → 人工确认队列（governed state，幂等）
# ---------------------------------------------------------------------------


def _write_revision_candidates(
    root: Path, candidates: tuple[VerificationCandidate, ...], actor: str
) -> dict[str, Any]:
    """把 verification 反哺候选写入 ``orchestration_revision_candidates.jsonl``。

    幂等：候选 id = sha1(requirement_id + reason)。已存在的 id 不重复写。绝不修改需求
    本体——这只是给专家面板的"建议复核"队列，provenance 标 orchestration。空候选不写空文件。
    """
    if not candidates:
        return {"written": False, "count": 0, "new": 0}
    target = governed_artifact_path(
        root, ORCHESTRATION_CANDIDATES_FILE, category="state", for_write=True
    )
    with _orchestration_lock(root, ORCHESTRATION_CANDIDATES_FILE):
        existing = _read_jsonl_tolerant(target)
        existing_ids = {str(row.get("candidate_id") or "") for row in existing}
        new_rows: list[dict[str, Any]] = []
        for candidate in candidates:
            cid = _candidate_id(candidate)
            if cid in existing_ids:
                continue
            new_rows.append({
                "schema": ORCHESTRATION_CANDIDATES_VERSION,
                "candidate_id": cid,
                "requirement_id": candidate.requirement_id,
                "reason": candidate.reason,
                "detail": candidate.detail,
                "evidence": candidate.evidence,
                "provenance": f"orchestration:{ORCHESTRATION_POLICY_VERSION}",
                "actor": actor,
                "ts": _utc_now(),
            })
            existing_ids.add(cid)
        if new_rows:
            _append_jsonl(target, new_rows)
    return {"written": bool(new_rows), "count": len(candidates), "new": len(new_rows),
            "path": target.name}


def _candidate_id(candidate: VerificationCandidate) -> str:
    raw = f"{candidate.requirement_id}|{candidate.reason}"
    return "ORC-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# trace / summary 落盘（复用 decide_trace.py 的锁+原子替换+PermissionError 重试纪律）
# ---------------------------------------------------------------------------


def _append_trace(root: Path, trace: dict[str, Any]) -> None:
    validated = _validate_trace(trace)
    path = governed_artifact_path(root, ORCHESTRATION_TRACE_FILE, category="state", for_write=True)
    line = json.dumps(validated, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _orchestration_lock(root, ORCHESTRATION_TRACE_FILE):
        _append_text_with_retry(path, line)


def _validate_trace(trace: dict[str, Any]) -> dict[str, Any]:
    global _VALIDATOR
    if _VALIDATOR is None:
        schema = json.loads(TRACE_SCHEMA_PATH.read_text(encoding="utf-8"))
        _VALIDATOR = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(_VALIDATOR.iter_errors(trace), key=lambda e: list(e.absolute_path))
    if errors:
        error = errors[0]
        location = ".".join(str(v) for v in error.absolute_path) or "$"
        raise OrchestrationLoopInputError(f"orchestration trace invalid at {location}: {error.message}")
    if trace["action"] not in trace["candidates"]:
        raise OrchestrationLoopInputError("orchestration trace action must be one of candidates")
    return trace


def _write_summary(root: Path, payload: dict[str, Any]) -> None:
    path = governed_artifact_path(root, ORCHESTRATION_SUMMARY_FILE, category="state", for_write=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with _orchestration_lock(root, ORCHESTRATION_SUMMARY_FILE):
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            _replace_with_retry(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def _build_summary(
    *, root: Path, run_id: str, rounds_used: int, rounds_max: int, authorized: bool,
    termination: str, last_action: str, action_counts: dict[str, int],
    failed_actions: list[dict[str, Any]], extract_total: int, extract_addressed: int,
    human_gaps: int, verification_candidates: int, needs_work: bool,
    candidate_write: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": ORCHESTRATION_SUMMARY_SCHEMA,
        "policy_version": ORCHESTRATION_POLICY_VERSION,
        "gap_version": ORCHESTRATION_GAP_VERSION,
        "run_id": run_id,
        "output_dir": str(root),
        "rounds": rounds_used,
        "rounds_max": rounds_max,
        "llm_authorized": authorized,
        "termination": termination,
        "needs_work": needs_work,
        "readiness": "NEEDS WORK" if needs_work else "READY",
        "extract_gaps_total": extract_total,
        "extract_gaps_addressed": extract_addressed,
        "extract_gaps_remaining": max(0, extract_total - extract_addressed),
        "human_gaps_total": human_gaps,
        "verification_candidates": verification_candidates,
        "verification_candidates_written": candidate_write,
        "actions": dict(action_counts),
        "failed_actions": failed_actions,
        "last_action": last_action,
        "trace_file": ORCHESTRATION_TRACE_FILE,
        "candidates_file": ORCHESTRATION_CANDIDATES_FILE,
        "completed_at": _utc_now(),
    }


# ---------------------------------------------------------------------------
# 摘要/原因文案
# ---------------------------------------------------------------------------


def _state_digest(
    report: GapReport, *, working: tuple[Gap, ...], addressed: set[str], authorized: bool
) -> dict[str, Any]:
    summary = gap_report_summary(report)
    return {
        "counts_by_kind": {
            kind: int(report.counts_by_kind.get(kind, 0))
            for kind in ("clarification_blocking", "conservation_open",
                         "sampling_escalate", "weakness")
        },
        "extract_working": len(working),     # 单调不增的收敛信号
        "extract_total": summary["extract_count"],
        "human_count": summary["human_count"],
        "verification_candidate_count": summary["verification_candidate_count"],
        "addressed_count": len(addressed),
        "ready_gate": summary["ready_gate"],
    }


def _stop_reason(report: GapReport, addressed: set[str]) -> str:
    if addressed:
        return (
            f"全部 {len(addressed)} 个可补抽缺口已处置，编排环收敛"
        )
    return "当前无可自动补抽的缺口（extract-route 为空），编排环无需动作"


def _stop_summary(report: GapReport, addressed: set[str]) -> str:
    if addressed:
        return f"收敛：{len(addressed)} 个 extract 缺口已处置；人工轨缺口 {len(report.human_gaps)} 个待处置。"
    return "无 extract 缺口需处置；人工轨缺口见 summary。"


def _action_reason(gap: Gap, action: str, authorized: bool) -> str:
    if not authorized:
        return f"LLM 未授权，缺口 {gap.target_id}（{gap.kind}）转人工"
    return (
        f"处置 {gap.kind} 缺口 {gap.target_id}：{action}（severity={gap.severity}，"
        f"block={gap.block_id or 'N/A'}）"
    )


def _gap_to_trace(gap: Gap) -> dict[str, Any]:
    return {
        "kind": gap.kind,
        "target_id": gap.target_id,
        "severity": gap.severity,
        "route": gap.route,
        "action": gap.action,
        "block_id": gap.block_id,
    }


def _validate_action_result(result: Any) -> None:
    if not isinstance(result, dict):
        raise ValueError("orchestration action result must be an object")
    if result.get("status") not in {"ok", "error", "skipped"}:
        raise ValueError("orchestration action result has an invalid status")
    if not str(result.get("summary") or "").strip():
        raise ValueError("orchestration action result summary is required")


# ---------------------------------------------------------------------------
# 锁 / 原子读写辅助（镜像 decide_trace.py + review_state.py 纪律）
# ---------------------------------------------------------------------------


@contextmanager
def _orchestration_lock(root: Path, filename: str) -> Iterator[None]:
    """跨进程 OS 排他锁 + 进程内 RLock（与 decide_trace_lock 同构，独立 lock 文件）。"""
    base = Path(root).expanduser().resolve()
    process_lock = _process_lock_for(base)
    lock_path = governed_artifact_path(base, f".{filename}.lock", category="state", for_write=True)
    with process_lock:
        deadline = time.monotonic() + _LOCK_TIMEOUT_S
        fd: int | None = None
        while fd is None:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if _remove_stale_lock(lock_path):
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for orchestration lock: {lock_path}")
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


def _process_lock_for(root: Path) -> RLock:
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(root, RLock())


def _remove_stale_lock(lock_path: Path) -> bool:
    try:
        age = time.time() - lock_path.stat().st_mtime
    except FileNotFoundError:
        return True
    if age < _LOCK_STALE_AFTER_S:
        return False
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return True
    return True


def _append_text_with_retry(path: Path, line: str) -> None:
    for attempt in range(_APPEND_ATTEMPTS):
        try:
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
            return
        except PermissionError:
            if attempt + 1 >= _APPEND_ATTEMPTS:
                raise
            time.sleep(_APPEND_RETRY_DELAY_S)


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows)
    for attempt in range(_APPEND_ATTEMPTS):
        try:
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            return
        except PermissionError:
            if attempt + 1 >= _APPEND_ATTEMPTS:
                raise
            time.sleep(_APPEND_RETRY_DELAY_S)


def _replace_with_retry(source: Path, target: Path) -> None:
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt + 1 >= _REPLACE_ATTEMPTS:
                raise
            time.sleep(_REPLACE_RETRY_DELAY_S)


def _read_jsonl_tolerant(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _block_text(root: Path, block_id: str) -> str:
    from io_utils import read_jsonl
    for block in read_jsonl(root / "blocks.jsonl"):
        if str(block.get("block_id") or "") == block_id:
            return str(block.get("text") or "")
    raise ValueError(f"unknown block_id: {block_id}")


def _resolve_run_id(root: Path) -> str:
    try:
        from desktop_tasks import read_run_manifest
        manifest = read_run_manifest(root)
    except Exception:  # noqa: BLE001
        manifest = {}
    run_id = str(manifest.get("run_id") or "").strip()
    if run_id:
        return run_id
    for name in ("ai_requirements.meta.json", "ai_requirements.partial.json"):
        path = root / name
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and str(payload.get("run_id") or "").strip():
            return str(payload["run_id"]).strip()
    return root.name or "orchestration-run"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the gap-driven orchestration loop.")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS)
    parser.add_argument(
        "--allow-llm", action="store_true",
        help="授权编排环经 openai_compatible 路由发起 spot_extract/targeted_reextract（默认关闭）",
    )
    parser.add_argument("--actor", default="orchestration-loop")
    return parser


def resolve_max_rounds(cli_value: int | None) -> int:
    """ENV 覆盖优先于代码默认；CLI 显式传值优先于 ENV（与既有 env 覆盖惯例一致）。"""
    env_raw = os.environ.get("RATOMIZER_ORCHESTRATION_MAX_ROUNDS", "").strip()
    value = int(cli_value) if cli_value is not None else (
        int(env_raw) if env_raw else DEFAULT_MAX_ROUNDS
    )
    if not 1 <= value <= MAX_ROUNDS_HARD_LIMIT:
        raise OrchestrationLoopInputError(
            f"max_rounds must be between 1 and {MAX_ROUNDS_HARD_LIMIT} (got {value})"
        )
    return value


def resolve_allow_llm(cli_flag: bool) -> bool:
    if cli_flag:
        return True
    env_raw = os.environ.get("RATOMIZER_ORCHESTRATION_ALLOW_LLM", "").strip().lower()
    return env_raw in {"1", "true", "yes", "on"}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    out_dir = args.out_dir.expanduser().resolve()
    try:
        max_rounds = resolve_max_rounds(args.max_rounds)
        summary = run_orchestration_loop(
            out_dir,
            max_rounds=max_rounds,
            allow_llm=resolve_allow_llm(args.allow_llm),
            actor=args.actor,
        )
        envelope = {
            "tool": "requirement-atomizer",
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "command": "orchestrate",
            "ok": True,
            "output_dir": str(out_dir),
            "summary": summary,
        }
        code = 0
    except OrchestrationLoopInputError as exc:
        envelope = _error_envelope(out_dir, "input_error", str(exc))
        code = 2
    except OrchestrationGapReadError as exc:
        envelope = _error_envelope(out_dir, "gap_read_error", str(exc))
        code = 3
    except (OSError, TimeoutError, ValueError) as exc:
        envelope = _error_envelope(out_dir, "validation_error", str(exc))
        code = 3
    except Exception as exc:  # pragma: no cover - final CLI safety net
        envelope = _error_envelope(out_dir, "pipeline_error", str(exc))
        code = 3
    print(json.dumps(envelope, ensure_ascii=False))
    return code


def _error_envelope(out_dir: Path, error_type: str, message: str) -> dict[str, Any]:
    return {
        "tool": "requirement-atomizer",
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "command": "orchestrate",
        "ok": False,
        "output_dir": str(out_dir),
        "error": {"type": error_type, "message": message},
    }


if __name__ == "__main__":
    sys.exit(main())
