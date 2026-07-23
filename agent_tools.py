"""Thin, provenance-preserving wrappers for Phase 1 agent actions."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

import clarification_report
import omission_actions
from agent_policy import AGENT_POLICY_VERSION
from agent_state import PENDING_OMISSION_STATUSES
from ai_review_actions import source_ai_requirement_id
from io_utils import read_jsonl

if TYPE_CHECKING:
    from agent_state import AnalysisState


def _pending_omission_block_ids(root: Path) -> set[str]:
    """Blocks whose current omission state is already in the extraction pipeline."""
    return {
        str(state.get("block_id") or "")
        for state in omission_actions.read_current_omission_states(root).values()
        if str(state.get("status") or "") in PENDING_OMISSION_STATUSES
        and str(state.get("block_id") or "")
    }


def resample_section(
    out_dir: Path,
    block_id: str,
    *,
    allow_llm: bool = False,
) -> dict[str, Any]:
    """Queue a gap in zero-LLM mode or delegate to the existing targeted extractor."""
    root = Path(out_dir).expanduser().resolve()
    block_id = str(block_id or "").strip()
    if not block_id:
        raise ValueError("block_id is required")
    if not allow_llm:
        with omission_actions.extraction_operation_lock(root, operation="agent-queue"):
            block, omission_id, source_fingerprint = _current_omission(root, block_id)
            if block_id in _pending_omission_block_ids(root):
                return {
                    "status": "skipped",
                    "summary": (
                        f"{block_id} is already queued for extraction; "
                        "no duplicate omission row was appended."
                    ),
                    "details": {"already_queued": True},
                }
            queued = omission_actions.apply_omission_action(
                root,
                block_id=block_id,
                omission_id=omission_id,
                status="needs_extraction",
                reason=f"Queued by {AGENT_POLICY_VERSION}; semantic extraction requires an LLM-capable worker.",
                actor="agent-loop",
                expected_source_fingerprint=source_fingerprint,
            )
        return {
            "status": "skipped",
            "summary": (
                f"Queued {block_id} for extraction; Phase 1 zero-LLM mode did not execute "
                "semantic resampling."
            ),
            "details": {"omission": queued},
        }
    _block, omission_id, source_fingerprint = _current_omission(root, block_id)
    payload = omission_actions.targeted_reextract(
        root,
        block_id=block_id,
        omission_id=omission_id,
        actor="agent-loop",
        reason=f"Selected by {AGENT_POLICY_VERSION}.",
        route="openai_compatible",
        expected_source_fingerprint=source_fingerprint,
    )
    return {
        "status": "ok",
        "summary": f"Targeted extraction completed for {block_id}.",
        "details": payload,
    }


def queue_all_gaps(out_dir: Path, block_ids: Iterable[str] | None = None) -> dict[str, Any]:
    """Queue every currently uncovered, not-yet-queued block in one locked batch.

    Per-block queueing exhausted the iteration budget on real documents (test3: 26 gaps
    vs 10 iterations); the batch keeps one iteration for clarification and stop.

    block_ids（可选）：调用方的状态快照候选——决策循环经 execute_action 把
    ``AnalysisState.unqueued_gap_block_ids``（覆盖缺口 ∪ 失败章节块）传入；不再
    uncovered 的失败块（残存需求/跨章引句/denominator 规则所致）因此仍能登记，
    否则重算路径永远排不上它们、failed_sections 无人处理。None（外部直接调用）
    保持旧行为：锁内重算当前 uncovered 集合。无论哪条路径，锁内逐块重新验证
    （存在于 blocks.jsonl、当前 omission 不在 pending、源指纹与当前文本一致），
    未过验证的块记入 details 的 skipped_block_ids（带原因），不报错中断。
    """
    root = Path(out_dir).expanduser().resolve()
    with omission_actions.extraction_operation_lock(root, operation="agent-queue"):
        if block_ids is None:
            candidates = sorted(
                omission_actions.current_omission_candidate_ids(root) - _pending_omission_block_ids(root)
            )
        else:
            candidates = sorted({str(value).strip() for value in block_ids if str(value).strip()})
        pending = _pending_omission_block_ids(root)
        queued_ids: list[str] = []
        skipped: list[dict[str, str]] = []
        for block_id in candidates:
            try:
                block = _block_by_id(root, block_id)
            except ValueError:
                skipped.append({"block_id": block_id, "reason": "block 不存在于 blocks.jsonl"})
                continue
            if block_id in pending:
                skipped.append({
                    "block_id": block_id,
                    "reason": "omission 已登记（needs_extraction/issue_confirmed），不重复排队",
                })
                continue
            text = str(block.get("text") or "")
            try:
                omission_actions.apply_omission_action(
                    root,
                    block_id=block_id,
                    omission_id=omission_actions.make_omission_id(block_id, text),
                    status="needs_extraction",
                    reason=f"Queued by {AGENT_POLICY_VERSION} (batch); semantic extraction requires an LLM-capable worker.",
                    actor="agent-loop",
                    expected_source_fingerprint=omission_actions.omission_source_fingerprint(block_id, text),
                )
            except (ValueError, omission_actions.OmissionConflictError) as exc:
                # 快照 → 登记的窗口内文本/身份被改写：如实记 skipped，不中断整批
                skipped.append({"block_id": block_id, "reason": str(exc)})
                continue
            queued_ids.append(block_id)
    details: dict[str, Any] = {"queued_block_ids": queued_ids, "skipped_block_ids": skipped}
    if not queued_ids:
        if skipped:
            return {
                "status": "skipped",
                "summary": (
                    f"No blocks were queued; {len(skipped)} candidate(s) failed "
                    "revalidation (see skipped_block_ids)."
                ),
                "details": details,
            }
        return {
            "status": "skipped",
            "summary": "No unqueued coverage gaps remain; nothing was appended.",
            "details": details,
        }
    summary = (
        f"Queued {len(queued_ids)} blocks for extraction; "
        "zero-LLM mode did not execute semantic resampling."
    )
    if skipped:
        summary += (
            f" Skipped {len(skipped)} candidate(s) that failed revalidation "
            "(see skipped_block_ids)."
        )
    return {"status": "ok", "summary": summary, "details": details}


def recheck(out_dir: Path, req_id: str) -> dict[str, Any]:
    """Validate a recheck target without inventing a new partial semantic-review path."""
    root = Path(out_dir).expanduser().resolve()
    req_id = str(req_id or "").strip()
    if not req_id:
        raise ValueError("req_id is required")
    requirements = read_jsonl(root / "ai_requirements.jsonl")
    if not any(source_ai_requirement_id(row) == req_id for row in requirements):
        raise ValueError(f"unknown requirement id: {req_id}")
    return {
        "status": "skipped",
        "summary": (
            f"Recheck {req_id} was not executed: the existing semantic recheck has no safe "
            "standalone zero-LLM entry point."
        ),
    }


def ask_clarification(out_dir: Path) -> dict[str, Any]:
    root = Path(out_dir).expanduser().resolve()
    report = clarification_report.run_report(root)
    questions = int(report.get("questions") or 0)
    return {
        "status": "ok",
        "summary": f"Wrote the clarification report with {questions} unresolved hard questions.",
        "details": report,
    }


def stop(state: "AnalysisState") -> dict[str, str]:
    if state.readiness.get("verdict") == "READY":
        summary = "READY gate passed; no further Phase 1 action is needed."
    else:
        reasons = [str(value) for value in (state.readiness.get("reasons") or []) if str(value)]
        detail = "; ".join(reasons) if reasons else "no eligible deterministic action remains"
        summary = f"Stopped with NEEDS WORK: {detail}."
    return {"status": "ok", "summary": summary}


def execute_action(out_dir: Path, action: str, state: "AnalysisState") -> dict[str, Any]:
    action = str(action or "").strip()
    if action.startswith("resample_section:"):
        return resample_section(out_dir, action.split(":", 1)[1], allow_llm=False)
    if action == "queue_all_gaps":
        # 决策循环路径消费状态快照候选（覆盖缺口 ∪ 失败章节块）——不再 uncovered 的
        # 失败块也必须能登记；快照外的块绝不入队（与候选生成口径严格一致）
        return queue_all_gaps(out_dir, block_ids=state.unqueued_gap_block_ids)
    if action.startswith("recheck:"):
        return recheck(out_dir, action.split(":", 1)[1])
    if action == "ask_clarification":
        return ask_clarification(out_dir)
    if action == "stop":
        return stop(state)
    raise ValueError(f"unsupported agent action: {action}")


def _block_by_id(out_dir: Path, block_id: str) -> dict[str, Any]:
    for block in read_jsonl(out_dir / "blocks.jsonl"):
        if str(block.get("block_id") or "") == block_id:
            return block
    raise ValueError(f"unknown block_id: {block_id}")


def _current_omission(out_dir: Path, block_id: str) -> tuple[dict[str, Any], str, str]:
    if block_id not in omission_actions.current_omission_candidate_ids(out_dir):
        raise ValueError(f"block is not a current omission candidate: {block_id}")
    block = _block_by_id(out_dir, block_id)
    text = str(block.get("text") or "")
    return (
        block,
        omission_actions.make_omission_id(block_id, text),
        omission_actions.omission_source_fingerprint(block_id, text),
    )
