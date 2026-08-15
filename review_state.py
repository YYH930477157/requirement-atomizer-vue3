from __future__ import annotations

import json
import hashlib
import logging
import os
import time
from contextlib import contextmanager
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Condition, RLock
from typing import Any, Iterator, Sequence

from process_file_lock import process_file_lock
from result_package import governed_artifact_path


# 仅约束自动化路径（llm_pipeline 的 transition()）。专家入口 apply_expert_decision
# 是覆盖式裁决，不受此表约束——见其 docstring。
VALID_TRANSITIONS = {
    "candidate": {"llm_reviewed", "rejected"},
    "llm_reviewed": {"expert_pending", "accepted", "flagged", "rejected"},
    "expert_pending": {"accepted", "rejected", "needs_discussion", "needs_rework"},
    "needs_discussion": {"expert_pending", "rejected"},
    "needs_rework": {"candidate", "llm_reviewed"},
    "flagged": {"expert_pending", "rejected"},
    "accepted": {"frozen"},
    "rejected": set(),
    "frozen": set(),
}

EXPERT_DECISION_STATUSES = {"accepted", "rejected", "needs_discussion", "expert_pending"}
EXPERT_ACTORS = {"expert", "vue3-test", "gui", "vue3-ui"}
_PROCESS_LOCKS: dict[tuple[Path, str], RLock] = {}
_PROCESS_LOCKS_GUARD = RLock()
# 8 次 × 线性退避（0.02..0.14s，共约 0.56s）：Windows AV/索引器对被读文件的目标句柄
# 常常超过旧 5×0.02（80ms）预算，把用户刚点保存的操作顶成 PermissionError。
# 与 claim_artifacts._replace_with_retry / ai_review_actions._replace_ai_review_bytes 同口径。
_REPLACE_ATTEMPTS = 8
_REPLACE_RETRY_DELAY_S = 0.02
CLAIM_AUTHORITY_WRITE_PROTOCOL_VERSION = "claim-authority-write-v1"
ATOMIC_TARGET_AUTHORITY_WRITE_REVISION_VERSION = "atomic-target-authority-write-revision-v1"
TARGET_PUBLICATION_REVISION_VERSION = "target-publication-revision-v1"
# WS2 §4.3 review_state level 字段：评审对象的粒度（functional=功能需求级 / atomic=原子级）。
# 旧文件无 level → 解释为 atomic（legacy 默认）；零迁移：缺字段不惊扰、不强制重写。
REVIEW_LEVELS = ("functional", "atomic")
DEFAULT_REVIEW_LEVEL = "atomic"


class ReviewAuthorityConflict(ValueError):
    """The displayed A-track authority row is stale and must be refreshed."""

    def __init__(self, message: str, *, current_revision: str) -> None:
        super().__init__(message)
        self.current_revision = str(current_revision)


def review_level(state: dict[str, Any] | None) -> str:
    """WS2 §4.3：解析评审状态行的粒度 level（functional/atomic）。

    旧文件无 level 字段 → 解释为 atomic（legacy 评审对象即原子需求）。零迁移：不强制重写
    旧文件，缺字段即默认值。非法值同样回退 atomic，绝不抛穿读路径。
    """
    if not isinstance(state, dict):
        return DEFAULT_REVIEW_LEVEL
    level = str(state.get("level") or "").strip().lower()
    return level if level in REVIEW_LEVELS else DEFAULT_REVIEW_LEVEL


def normalize_review_level(value: str | None) -> str:
    """写路径用：把 level 规范化为合法枚举值（非法/空 → 默认 atomic）。"""
    level = str(value or "").strip().lower()
    return level if level in REVIEW_LEVELS else DEFAULT_REVIEW_LEVEL


def target_publication_revision(path: Path) -> str:
    """Bind an authority write to the exact target publication bytes."""
    from claim_artifacts import hash_json, sha256_bytes

    target = Path(path)
    present = target.is_file()
    raw = target.read_bytes() if present else b""
    return hash_json(
        TARGET_PUBLICATION_REVISION_VERSION,
        {
            "source_store": target.name,
            "source_present": present,
            "source_file_sha256": sha256_bytes(raw),
        },
    )


@dataclass
class ReviewEvent:
    from_status: str
    to_status: str
    actor: str
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class RequirementReviewState:
    requirement_id: str
    status: str = "candidate"
    history: list[ReviewEvent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    # WS2 §4.3：评审对象粒度。旧文件读路径缺该字段时经 review_level() 解释为 atomic。
    level: str = DEFAULT_REVIEW_LEVEL

    def transition(self, to_status: str, *, actor: str, reason: str) -> None:
        allowed = VALID_TRANSITIONS.get(self.status, set())
        if to_status not in allowed:
            raise ValueError(f"Invalid transition: {self.status} -> {to_status}")
        event = ReviewEvent(from_status=self.status, to_status=to_status, actor=actor, reason=reason)
        self.history.append(event)
        self.status = to_status

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "status": self.status,
            "history": [event.__dict__ for event in self.history],
            "metadata": self.metadata,
            "level": self.level,
        }


def apply_expert_decision(
    out_dir: Path,
    requirement_id: str,
    status: str,
    *,
    actor: str,
    reason: str = "",
    expected_target_fingerprint: str | None = None,
    expected_target_authority_write_revision: str | None = None,
    level: str | None = None,
) -> dict[str, Any]:
    """专家覆盖式裁决：决策状态间可自由改判（含 accepted→rejected、rejected→
    expert_pending 重审），这是有意语义——专家是权威裁决方，VALID_TRANSITIONS
    只约束自动化 LLM 路径。唯一禁止的跳转是从 frozen 改出（须显式解冻流程，
    不属于本入口）。每次改判都追加 history（actor/reason/timestamp），审计链完整。

    WS2 §4.3 ``level``（functional/atomic）：显式标注评审对象粒度，缺省/旧文件 → atomic。
    """
    if status not in EXPERT_DECISION_STATUSES:
        raise ValueError(f"Unknown review status: {status}")
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    states_path = governed_artifact_path(out_dir, "review_states.jsonl", category="state")
    events_path = governed_artifact_path(out_dir, "review_state_events.jsonl", category="state")

    with review_state_lock(out_dir):
        states = _read_jsonl(states_path)
        current_write_revision = atomic_target_authority_write_revision(
            requirement_id,
            states,
        )
        if (
            expected_target_authority_write_revision is not None
            and str(expected_target_authority_write_revision)
            != current_write_revision
        ):
            raise ReviewAuthorityConflict(
                "review authority changed; refresh before adjudicating",
                current_revision=current_write_revision,
            )
        if expected_target_fingerprint is not None:
            binding = _current_atomic_review_binding(out_dir, requirement_id)
            current_target_fingerprint = (
                str(binding.get("review_subject_fingerprint") or "")
                if binding is not None
                else ""
            )
            if current_target_fingerprint != str(expected_target_fingerprint):
                raise ReviewAuthorityConflict(
                    "atomic requirement changed; refresh before adjudicating",
                    current_revision=current_write_revision,
                )
        state_index = _find_state_index(states, requirement_id)
        if state_index is None:
            state = RequirementReviewState(
                requirement_id,
                level=normalize_review_level(level),
            )
            states.append(state.to_dict())
            state_index = len(states) - 1
        else:
            state = _state_from_dict(states[state_index])
            # 显式传入 level 时覆盖（否则保留既有 row 的 level，旧文件即 atomic）
            if level is not None:
                state.level = normalize_review_level(level)

        if state.status == "frozen" and status != "frozen":
            raise ValueError("Cannot override frozen review state")

        event: dict[str, Any] | None = None
        if state.status != status:
            binding = _current_atomic_review_binding(out_dir, requirement_id)
            if binding is None:
                state.metadata["needs_reconfirmation"] = True
            else:
                state.metadata.update({
                    "source_fingerprint": binding["source_fingerprint"],
                    "review_subject_fingerprint": binding[
                        "review_subject_fingerprint"
                    ],
                    "needs_reconfirmation": False,
                })
            review_event = ReviewEvent(from_status=state.status, to_status=status, actor=actor, reason=reason)
            state.history.append(review_event)
            state.status = status
            event = review_event.__dict__
        states[state_index] = state.to_dict()

        _atomic_write_jsonl(states_path, states)
        result = dict(states[state_index])
        result["target_authority_write_revision"] = atomic_target_authority_write_revision(
            requirement_id,
            states,
        )
        if expected_target_fingerprint is not None:
            result["target_fingerprint"] = str(expected_target_fingerprint)
        if event is not None:
            try:
                _append_review_state_event(events_path, result, event)
            except OSError as exc:
                # state.history 已原子提交，是权威审计记录；事件 JSONL 只是投影。
                # 此时返回 503 会诱导同状态重试，而重试不会产生新 transition。
                logging.getLogger("requirement_atomizer").warning(
                    "裁决状态已保存，但事件日志追加失败：%s", exc)
                result = dict(result)
                result["audit_warning"] = "裁决已保存，但独立事件日志写入失败；完整历史仍保存在状态文件中"
    # package_v1 下该文件在 .ratomizer/state/，裸路径闸门会静默吞掉 fold 钩子（审查 B1 同族）
    if governed_artifact_path(
        out_dir, "claim_generation.meta.json", category="state"
    ).is_file():
        cover_effective_fold_after_decision(
            out_dir,
            actor_trigger="requirement-review-action",
            authority_hook_track="A",
        )
    return result


def _current_atomic_review_binding(
    out_dir: Path,
    requirement_id: str,
) -> dict[str, str] | None:
    path = out_dir / "atomic_requirements.jsonl"
    if not path.is_file():
        return None
    matches = [
        row for row in _read_jsonl(path)
        if requirement_id in requirement_identity_keys(row)
    ]
    if len(matches) != 1:
        return None
    from claim_ledger import (
        atomic_target_fingerprint,
        atomic_target_source_fingerprint,
    )

    return {
        "source_fingerprint": atomic_target_source_fingerprint(matches[0]),
        "review_subject_fingerprint": atomic_target_fingerprint(matches[0]),
    }


def merge_review_states(
    existing_states: list[dict[str, Any]],
    generated_states: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = [dict(state) for state in generated_states]
    for existing in existing_states:
        existing_state = _state_from_dict(existing).to_dict()
        index = _find_matching_state_index(merged, existing_state)
        if index is None:
            merged.append(existing_state)
            continue
        if is_expert_controlled(existing_state) or str(existing_state.get("status") or "") == "frozen":
            merged[index] = _merge_state_payload(merged[index], existing_state)
        else:
            merged[index] = _merge_history(merged[index], existing_state)
    return merged


def is_expert_controlled(state: dict[str, Any]) -> bool:
    for event in state.get("history", []) or []:
        if not isinstance(event, dict):
            continue
        actor = str(event.get("actor") or "")
        if actor in EXPERT_ACTORS or actor.startswith("expert") or actor.startswith("user:") or actor.endswith("-ui"):
            return True
    return False


def _find_matching_state_index(states: list[dict[str, Any]], needle: dict[str, Any]) -> int | None:
    for key in requirement_identity_keys(needle):
        index = _find_state_index(states, key)
        if index is not None:
            return index
    return None


def _merge_state_payload(generated: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    metadata = dict(generated.get("metadata") or {})
    metadata.update(dict(existing.get("metadata") or {}))
    merged["metadata"] = metadata
    merged["history"] = _dedupe_history(existing.get("history") or [])
    return merged


def _merge_history(generated: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    merged = dict(generated)
    metadata = dict(existing.get("metadata") or {})
    metadata.update(dict(generated.get("metadata") or {}))
    merged["metadata"] = metadata
    merged["history"] = _dedupe_history([
        *(existing.get("history") or []),
        *(generated.get("history") or []),
    ])
    return merged


def _dedupe_history(events: list[Any]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        payload = dict(event)
        key = review_event_key(payload)
        if key in seen:
            continue
        seen.add(key)
        result.append(payload)
    return result


def requirement_identity_keys(row: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    # T3-1：``requirement_uid`` 是跨再生成稳定 ID（功能需求级），纳入身份键解析——RTM 边/
    # 生命周期事件可用它寻址；旧 content-hash（functional_requirement_id/stable_req_id）仍为别名。
    for name in ("requirement_id", "requirement_uid", "stable_req_id", "req_id"):
        value = row.get(name)
        if value:
            text = str(value)
            if text not in keys:
                keys.append(text)
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    for name in ("requirement_uid", "stable_req_id", "req_id"):
        value = metadata.get(name)
        if value:
            text = str(value)
            if text not in keys:
                keys.append(text)
    return keys


def _empty_review_authority_snapshot(path: Path) -> dict[str, Any]:
    empty_hash = "sha256:" + hashlib.sha256(b"").hexdigest()
    return {
        "source_store": path.name,
        "states": [],
        "source_records": {},
        "ordered_records": [],
        "audit_gaps": [],
        "torn_tail_recovered": False,
        "authority_file_sha256": empty_hash,
    }


def _review_authority_snapshot_from_bytes(path: Path, raw: bytes) -> dict[str, Any]:
    from claim_artifacts import hash_json

    # The A-track state file is atomically replaced, but historical/manual
    # files can still contain a complete corrupt record.  Match the B-track
    # authority contract: preserve every later valid record and make the gap
    # visible to the fold health projection.  An unterminated final record is
    # different: it can be an in-flight write, so callers must retry rather
    # than folding an unstable authority snapshot.
    body = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
    state_records: list[tuple[int, int, dict[str, Any]]] = []
    audit_gaps: list[dict[str, Any]] = []
    state_ordinal = 0
    lines = body.splitlines(keepends=True)
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not stripped:
            continue
        state_ordinal += 1
        try:
            row = json.loads(stripped.decode("utf-8"))
            if not isinstance(row, dict):
                raise ValueError("record is not an object")
            if not requirement_identity_keys(row):
                raise ValueError("record has no requirement identity")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            is_unterminated_tail = (
                index == len(lines) - 1
                and not raw_line.endswith((b"\n", b"\r"))
            )
            if is_unterminated_tail:
                raise ValueError("review authority has a torn tail") from exc
            audit_gaps.append({
                "physical_line_number": index + 1,
                "state_ordinal": state_ordinal,
                "reason": type(exc).__name__,
                "line_sha256": "sha256:" + hashlib.sha256(raw_line).hexdigest(),
            })
            logging.getLogger("requirement_atomizer").warning(
                "preserving audit gap in review_states.jsonl at physical line %d "
                "(state %d)",
                index + 1,
                state_ordinal,
            )
            continue
        state_records.append((state_ordinal, index + 1, row))

    ordered_records: list[dict[str, Any]] = []
    source_record_candidates: dict[str, list[dict[str, Any]]] = {}
    for state_ordinal, physical_line_number, state in state_records:
        identities = requirement_identity_keys(state)
        requirement_id = str(state.get("requirement_id") or identities[0])
        history = state.get("history")
        if not isinstance(history, list):
            audit_gaps.append({
                "physical_line_number": physical_line_number,
                "state_ordinal": state_ordinal,
                "requirement_id": requirement_id,
                "reason": "history_not_array",
            })
            continue
        if not history and str(state.get("status") or "candidate") != "candidate":
            audit_gaps.append({
                "physical_line_number": physical_line_number,
                "state_ordinal": state_ordinal,
                "requirement_id": requirement_id,
                "reason": "state_without_history",
            })
        for history_index, raw_event in enumerate(history):
            if not isinstance(raw_event, dict) or not str(
                raw_event.get("to_status") or ""
            ):
                audit_gaps.append({
                    "physical_line_number": physical_line_number,
                    "state_ordinal": state_ordinal,
                    "requirement_id": requirement_id,
                    "history_index": history_index,
                    "reason": "invalid_history_event",
                })
                continue
            history_event = dict(raw_event)
            source_event_revision = hash_json(
                "claim-source-event-revision/v1",
                {
                    "source_store": path.name,
                    "requirement_id": requirement_id,
                    "history_index": history_index,
                    "history_event": history_event,
                },
            )
            record = {
                "physical_line_number": physical_line_number,
                "state_ordinal": state_ordinal,
                "requirement_id": requirement_id,
                "identity_keys": identities,
                "history_index": history_index,
                "history_event": history_event,
                "source_event_revision": source_event_revision,
                "state": state,
            }
            ordered_records.append(record)
            for identity in identities:
                source_record_candidates.setdefault(identity, []).append(record)
    source_records = {
        identity: records[-1]
        for identity, records in source_record_candidates.items()
        if records
    }
    return {
        "source_store": path.name,
        "states": [state for _ordinal, _line, state in state_records],
        "source_records": source_records,
        "ordered_records": ordered_records,
        "audit_gaps": audit_gaps,
        "torn_tail_recovered": False,
        "authority_file_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
    }


def read_review_authority_snapshot(out_dir: Path) -> dict[str, Any]:
    """Read A-track state and every embedded history event under its authority lock."""
    root = out_dir.expanduser().resolve()
    path = governed_artifact_path(root, "review_states.jsonl", category="state")
    with review_state_lock(root):
        if not path.is_file():
            return _empty_review_authority_snapshot(path)
        return _review_authority_snapshot_from_bytes(path, path.read_bytes())


def read_review_authority_snapshot_readonly(out_dir: Path) -> dict[str, Any]:
    """Read A-track authority without creating or changing a lock sidecar."""
    root = out_dir.expanduser().resolve()
    path = governed_artifact_path(root, "review_states.jsonl", category="state")
    before = path.read_bytes() if path.is_file() else None
    snapshot = (
        _empty_review_authority_snapshot(path)
        if before is None
        else _review_authority_snapshot_from_bytes(path, before)
    )
    after = path.read_bytes() if path.is_file() else None
    if after != before:
        raise ValueError("review authority changed during read-only read")
    return snapshot


def _hash_state_row_and_history(raw_state: dict[str, Any]) -> tuple[str, str]:
    """(row hash, history prefix hash) for one authority state row."""
    from claim_artifacts import hash_json

    history = raw_state.get("history")
    history = history if isinstance(history, list) else []
    return (
        hash_json(
            f"{ATOMIC_TARGET_AUTHORITY_WRITE_REVISION_VERSION}:row",
            raw_state,
        ),
        hash_json(
            f"{ATOMIC_TARGET_AUTHORITY_WRITE_REVISION_VERSION}:history",
            history,
        ),
    )


# GET /requirements 富集（api_server.enrich_requirements）对同一份
# review_states 快照逐行调用 atomic_target_authority_write_revision，旧行为每次
# 重新 hash_json 整行 + 全部 history，O(行数×状态数)/请求。这里按快照内容签名
# （source_store + authority_file_sha256，比 stat 签名更强——绑定精确字节）缓存
# 逐 ordinal 的行哈希：同一未变化快照内重复富集不再重算。快照字节一变（任何
# 裁决写入都会原子替换文件）→ 新 sha → 新键，旧条目被淘汰，不存在陈旧命中。
_AUTHORITY_REVISION_HASH_CACHE_MAX_SNAPSHOTS = 8
_AUTHORITY_REVISION_HASH_CACHE: OrderedDict[tuple[str, str], dict[int, tuple[str, str]]] = OrderedDict()
_AUTHORITY_REVISION_HASH_CACHE_GUARD = RLock()


def _authority_revision_row_hashes(
    snapshot_or_states: dict[str, Any] | list[dict[str, Any]],
) -> dict[int, tuple[str, str]] | None:
    """Return a fillable per-ordinal hash cache for a content-addressed snapshot.

    Only the snapshot (dict) form is cacheable: its ``authority_file_sha256``
    binds the exact bytes the ``states`` list was parsed from, and production
    callers treat the snapshot as read-only after load. The bare-list form
    (apply_expert_decision / llm_pipeline pass the in-memory list they are
    mutating) is never cached.
    """
    if not isinstance(snapshot_or_states, dict):
        return None
    store = str(snapshot_or_states.get("source_store") or "")
    file_sha = str(snapshot_or_states.get("authority_file_sha256") or "")
    if not store or not file_sha:
        return None
    key = (store, file_sha)
    with _AUTHORITY_REVISION_HASH_CACHE_GUARD:
        cached = _AUTHORITY_REVISION_HASH_CACHE.get(key)
        if cached is not None:
            _AUTHORITY_REVISION_HASH_CACHE.move_to_end(key)
            return cached
        fresh: dict[int, tuple[str, str]] = {}
        _AUTHORITY_REVISION_HASH_CACHE[key] = fresh
        while len(_AUTHORITY_REVISION_HASH_CACHE) > _AUTHORITY_REVISION_HASH_CACHE_MAX_SNAPSHOTS:
            _AUTHORITY_REVISION_HASH_CACHE.popitem(last=False)
        return fresh


def atomic_target_authority_write_revision(
    requirement_id: str,
    snapshot_or_states: dict[str, Any] | list[dict[str, Any]],
) -> str:
    """Return the physical per-target A-track write revision.

    ``target_review_revision`` is a semantic projection and intentionally ignores
    timestamps/reasons.  This CAS token instead binds every matching state row,
    its physical ordinal, the complete current row hash, and the full history
    prefix hash.  Consequently an ABA sequence (accepted -> rejected -> accepted)
    cannot reuse the original token.
    """
    from claim_artifacts import hash_json

    if isinstance(snapshot_or_states, dict):
        states = snapshot_or_states.get("states") or []
    else:
        states = snapshot_or_states
    row_hashes = _authority_revision_row_hashes(snapshot_or_states)
    wanted = str(requirement_id or "").strip()
    bindings: list[dict[str, Any]] = []
    for ordinal, raw_state in enumerate(states, start=1):
        if not isinstance(raw_state, dict):
            continue
        if wanted not in requirement_identity_keys(raw_state):
            continue
        if row_hashes is not None:
            hashes = row_hashes.get(ordinal)
            if hashes is None:
                hashes = _hash_state_row_and_history(raw_state)
                row_hashes[ordinal] = hashes
        else:
            hashes = _hash_state_row_and_history(raw_state)
        bindings.append({
            "state_ordinal": ordinal,
            "state_row_hash": hashes[0],
            "history_prefix_hash": hashes[1],
        })
    return hash_json(
        ATOMIC_TARGET_AUTHORITY_WRITE_REVISION_VERSION,
        {
            "source_store": "review_states.jsonl",
            "target_kind": "atomic_requirement",
            "target_requirement_id": wanted,
            "bindings": bindings,
        },
    )


def _find_state_index(states: list[dict[str, Any]], requirement_id: str) -> int | None:
    for index, state in enumerate(states):
        if str(state.get("requirement_id") or "") == requirement_id:
            return index
        metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
        if requirement_id in {str(metadata.get("stable_req_id") or ""), str(metadata.get("req_id") or "")}:
            return index
    return None


def _state_from_dict(payload: dict[str, Any]) -> RequirementReviewState:
    state = RequirementReviewState(
        str(payload.get("requirement_id") or ""),
        status=str(payload.get("status") or "candidate"),
        metadata=dict(payload.get("metadata") or {}),
        level=normalize_review_level(payload.get("level") if "level" in payload else None),
    )
    state.history = [
        ReviewEvent(
            from_status=str(event.get("from_status") or ""),
            to_status=str(event.get("to_status") or ""),
            actor=str(event.get("actor") or ""),
            reason=str(event.get("reason") or ""),
            timestamp=str(event.get("timestamp") or ""),
        )
        for event in payload.get("history", [])
        if isinstance(event, dict)
    ]
    return state


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@contextmanager
def review_state_lock(out_dir: Path, *, timeout_s: float = 10.0, stale_after_s: float = 300.0) -> Iterator[None]:
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    process_lock = _process_lock_for(out_dir, "review_states")
    with process_lock:
        lock_path = governed_artifact_path(out_dir, "review_states.lock", category="state")
        del stale_after_s
        with process_file_lock(
            lock_path,
            timeout_s=timeout_s,
            label="review state lock",
        ):
            yield


def _process_lock_for(out_dir: Path, name: str) -> RLock:
    """Per-(root, lock family) in-process serializer.

    Keyed by the lock name as well as the root（与 omission_actions._process_lock_for
    同构）：review_states 与 verification_states 是两把不同的跨进程文件锁，若共享
    同一把进程内 RLock，线程化 GET 的大快照扫描会无谓阻塞另一家族的 POST。
    """
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault((out_dir, name), RLock())


# ===========================================================================
# 裁决后 effective fold 合并（2026-08-14 性能修复）
# ---------------------------------------------------------------------------
# 此前每次专家裁决 POST 都在请求内同步跑一次 fold_effective_ledger（claim_
# publication_lock + 全量 committed base 加载 + effective/queue 重发布），评审员
# 连续点击时每一下都卡。本合并器不引入后台线程/定时器/延迟语义：并发突发的 K
# 次裁决合并为 1-2 个 fold pass，且每个裁决线程仍等待一个「在其裁决写入之后
# 启动」的同步 fold pass 完成才返回——读后写可见性契约与旧实现完全一致
# （claim_views / claim_queue_execution / 桌面导出闸门在裁决返回后立即读
# committed effective 快照；这些消费方不在本模块可改范围，异步延迟会让
# document_ready 间歇闪断）。fold 失败保持 logged-and-continue：权威裁决行已
# 落盘，effective 追平由 assess_effective_freshness 如实标记，下一次裁决 /
# 队列执行 / api 启动维护恢复。
# ===========================================================================
_EFFECTIVE_FOLD_DRAIN_PASSES = 3
# P2 活性修复（2026-08-15）：单槽被两轨共享且让位无公平时，持续同轨突发可让
# 异轨等待者零进展饿死（实测 10s+），且 cover() 无超时会让 HTTP 工作线程无限
# 挂起。等待因此有界：超时是诚实失败（TimeoutError 子类 → 调用方既有
# except (TimeoutError, OSError) 分支映射 retryable 503），裁决本身在 cover()
# 之前已原子提交、绝不回滚；fold 落后由 assess_effective_freshness 如实标记，
# 下一次裁决 / 队列执行 / 启动维护追平。
EFFECTIVE_FOLD_COVER_TIMEOUT_S = 30.0
_EFFECTIVE_FOLD_COORDINATORS: dict[Path, "_EffectiveFoldCoordinator"] = {}
_EFFECTIVE_FOLD_COORDINATORS_GUARD = RLock()


class EffectiveFoldCoverTimeout(TimeoutError):
    """cover() 等待覆盖性 fold pass 超过 ``EFFECTIVE_FOLD_COVER_TIMEOUT_S``。

    语义：调用方的权威裁决在注册等待之前已经持久提交，本异常只表示「在其
    之后编号的覆盖性 pass」在时限内没有完成——派生 effective 快照暂时落后，
    由 assess_effective_freshness 标记并由下一次裁决 / 队列执行 / 启动维护
    追平。继承 TimeoutError 使 api_server 既有 except (TimeoutError, OSError)
    分支直接把它映射为 retryable 503，无需调用方逐点改造。
    """


class _EffectiveFoldCoordinator:
    """Per-root single-flight fold cover with per-track pass accounting.

    Invariant: ``cover(track, run_pass)`` returns only after at least one fold
    pass of ``track`` that was *numbered after* the caller registered has
    completed (or honestly raised — the pass still counts, matching the old
    catch-and-continue hook).  Pass numbers are allocated under the condition
    lock immediately before a pass runs, and every caller's authority write is
    durably committed *before* it registers, so any pass numbered at or above
    the caller's target necessarily folds that caller's write.  The pass owner
    drains re-queued same-track decisions (bounded by ``_EFFECTIVE_FOLD_DRAIN_
    PASSES``), which is what collapses a burst of K racing decisions into one
    or two folds instead of K serialized in-request folds.

    Fairness + bounded wait (2026-08-15): the slot handoff prefers a DIFFERENT
    track than the one that just ran whenever cross-track waiters exist (both
    tracks waiting → alternation); a same-track re-acquire stays allowed when
    no other-track waiter exists, preserving steady-state burst coalescing.
    Waiting is bounded by ``EFFECTIVE_FOLD_COVER_TIMEOUT_S`` — on expiry the
    waiter deregisters and raises ``EffectiveFoldCoverTimeout`` (the authority
    write it already made is never rolled back).
    """

    def __init__(self) -> None:
        self._cond = Condition()
        self._in_flight: str | None = None
        self._dirty: set[str] = set()
        self._waiting: dict[str, int] = {}
        self._preferred: str | None = None
        self._last_allocated = 0
        self._completed: dict[str, int] = {}

    def _handoff_allows(self, track: str) -> bool:
        preferred = self._preferred
        if preferred is None or preferred == track:
            return True
        # 首选轨已无等待者（被覆盖/超时离场）时不让旧偏好卡住空槽。
        return self._waiting.get(preferred, 0) <= 0

    def _next_preferred(self, owner_track: str) -> str | None:
        others = sorted(
            track for track, count in self._waiting.items()
            if count > 0 and track != owner_track
        )
        return others[0] if others else None

    def cover(self, track: str, run_pass) -> None:
        timed_out = False
        with self._cond:
            target = self._last_allocated + 1
            self._dirty.add(track)
            self._waiting[track] = self._waiting.get(track, 0) + 1
            try:
                deadline = time.monotonic() + EFFECTIVE_FOLD_COVER_TIMEOUT_S
                while self._completed.get(track, 0) < target:
                    if self._in_flight is None and self._handoff_allows(track):
                        self._in_flight = track
                        self._preferred = None
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        timed_out = True
                        break
                    self._cond.wait(remaining)
                else:
                    return
            finally:
                self._waiting[track] -= 1
                if self._waiting.get(track, 0) <= 0:
                    self._waiting.pop(track, None)
                    if self._preferred == track:
                        self._preferred = None
                        self._cond.notify_all()
        if timed_out:
            raise EffectiveFoldCoverTimeout(
                f"effective fold cover timed out on track {track!r} after "
                f"{EFFECTIVE_FOLD_COVER_TIMEOUT_S}s waiting for a covering "
                "pass; the decision was already committed and the fold lag "
                "will be flagged by freshness assessment and re-folded on "
                "the next decision/queue execution/startup maintenance"
            )
        try:
            for _ in range(_EFFECTIVE_FOLD_DRAIN_PASSES):
                with self._cond:
                    self._last_allocated += 1
                    number = self._last_allocated
                    self._dirty.discard(track)
                run_pass()
                with self._cond:
                    if self._completed.get(track, 0) < number:
                        self._completed[track] = number
                    if track not in self._dirty:
                        return
        finally:
            with self._cond:
                self._in_flight = None
                self._preferred = self._next_preferred(track)
                self._cond.notify_all()


def _effective_fold_coordinator_for(out_dir: Path) -> _EffectiveFoldCoordinator:
    with _EFFECTIVE_FOLD_COORDINATORS_GUARD:
        coordinator = _EFFECTIVE_FOLD_COORDINATORS.get(out_dir)
        if coordinator is None:
            coordinator = _EffectiveFoldCoordinator()
            _EFFECTIVE_FOLD_COORDINATORS[out_dir] = coordinator
        return coordinator


def cover_effective_fold_after_decision(
    out_dir: Path,
    *,
    actor_trigger: str,
    authority_hook_track: str,
    fold_lag_log_template: str = "expert decision saved; claim effective fold lagged: %s",
) -> None:
    """Coalesced replacement for the per-decision synchronous fold hook.

    Both review_state (A-track) and ai_review_actions (B-track) decisions funneled
    through the same per-root coordinator, so a mixed burst still folds once per
    track at most per drain window.  The decision itself is already durable
    before this runs; a fold failure only lags the derived effective snapshot,
    which freshness assessment surfaces and the next decision re-triggers.
    """
    from claim_review_actions import fold_effective_ledger

    def _run_pass() -> None:
        try:
            fold_effective_ledger(
                out_dir,
                actor_trigger=actor_trigger,
                authority_hook_track=authority_hook_track,
            )
        except Exception as exc:
            # The requirement-level authority is already atomically committed.
            # Effective materialization is derived and may catch up later.
            logging.getLogger("requirement_atomizer").warning(
                fold_lag_log_template, exc)

    try:
        _effective_fold_coordinator_for(out_dir).cover(
            authority_hook_track, _run_pass
        )
    except EffectiveFoldCoverTimeout as exc:
        # 裁决已原子提交；只诚实记录 fold 覆盖等待超时（落后事实），超时异常
        # 向上抛给调用方映射 retryable 503——绝不把已提交的裁决伪装成失败回滚。
        logging.getLogger("requirement_atomizer").warning(
            "decision saved; claim effective fold cover timed out "
            "(actor_trigger=%s, track=%s, waited %ss): fold lag will be "
            "flagged by freshness assessment and re-folded on the next "
            "decision/queue execution/startup maintenance: %s",
            actor_trigger,
            authority_hook_track,
            EFFECTIVE_FOLD_COVER_TIMEOUT_S,
            exc,
        )
        raise


def _atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        _replace_with_retry(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _replace_with_retry(source: Path, target: Path) -> None:
    """Retry short-lived Windows sharing violations without weakening atomic replacement."""
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt + 1 >= _REPLACE_ATTEMPTS:
                raise
            time.sleep(_REPLACE_RETRY_DELAY_S * (attempt + 1))


def _append_review_state_event(path: Path, state: dict[str, Any], event: dict[str, Any]) -> None:
    metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
    row = {
        "requirement_id": state.get("requirement_id"),
        "req_id": metadata.get("req_id"),
        "stable_req_id": metadata.get("stable_req_id"),
        "status_after": event.get("to_status"),
        "current_status": state.get("status"),
        **event,
    }
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def review_event_key(event: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(event.get("timestamp") or ""),
        str(event.get("from_status") or ""),
        str(event.get("to_status") or ""),
        str(event.get("actor") or ""),
        str(event.get("reason") or ""),
    )


# ===========================================================================
# WS4 共享状态 I/O：verification_states / requirement_lifecycle_events /
# manual_requirements / dependency_decisions。
# ---------------------------------------------------------------------------
# 全部走 governed state 路径 + 跨进程锁（process_file_lock）+ 原子替换（带
# PermissionError 重试），与既有 review_states.jsonl / clarification_answers 同纪律。
# 读路径容错（坏行跳过），写路径锁内整文件原子替换或 append-only。
# ===========================================================================
VERIFICATION_STATES_FILE = "verification_states.jsonl"
VERIFICATION_STATES_LOCK = "verification_states.lock"
REQUIREMENT_LIFECYCLE_EVENTS_FILE = "requirement_lifecycle_events.jsonl"
MANUAL_REQUIREMENTS_FILE = "manual_requirements.jsonl"
DEPENDENCY_DECISIONS_FILE = "dependency_decisions.jsonl"


class VerificationStateConflict(ValueError):
    """verification 回写 CAS 失配：需求内容已变化，拒绝自动合入转人工。"""

    def __init__(self, message: str, *, requirement_id: str, current_fingerprint: str) -> None:
        super().__init__(message)
        self.requirement_id = str(requirement_id)
        self.current_fingerprint = str(current_fingerprint)


@contextmanager
def verification_state_lock(out_dir: Path, *, timeout_s: float = 10.0) -> Iterator[None]:
    """verification/手工/依赖状态文件的跨进程锁（独立锁文件，避免与 review_states 抢锁）。"""
    root = out_dir.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    process_lock = _process_lock_for(root, "verification_states")
    with process_lock:
        lock_path = governed_artifact_path(root, VERIFICATION_STATES_LOCK, category="state")
        with process_file_lock(lock_path, timeout_s=timeout_s, label="verification state lock"):
            yield


def _read_jsonl_tolerant(path: Path) -> list[dict[str, Any]]:
    """容错读 JSONL：坏行跳过而非整文件崩（与 clarification answers 同纪律）。"""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _verification_states_path(out_dir: Path) -> Path:
    return governed_artifact_path(out_dir, VERIFICATION_STATES_FILE, category="state")


def read_verification_states(out_dir: Path) -> dict[str, dict[str, Any]]:
    """读全部 verification 覆盖记录，按 requirement_id 索引（只读路径，for_write=False）。"""
    path = governed_artifact_path(Path(out_dir).expanduser().resolve(),
                                  VERIFICATION_STATES_FILE, category="state", for_write=False)
    states: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl_tolerant(path):
        rid = str(row.get("requirement_id") or "").strip()
        if rid:
            states[rid] = row
    return states


def _write_verification_states_unlocked(path: Path, states: dict[str, dict[str, Any]]) -> None:
    rows = sorted(states.values(), key=lambda row: str(row.get("requirement_id") or ""))
    _atomic_write_jsonl(path, rows)


def upsert_verification_state(
    out_dir: Path,
    requirement_id: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    """锁内读-合并-原子写一条 verification 记录。返回落盘后的完整记录。"""
    root = Path(out_dir).expanduser().resolve()
    rid = str(requirement_id or "").strip()
    if not rid:
        raise ValueError("requirement_id is required for verification state")
    with verification_state_lock(root):
        path = _verification_states_path(root)
        states = {row.get("requirement_id"): row for row in _read_jsonl_tolerant(path)}
        merged = dict(states.get(rid) or {})
        merged.update(record)
        merged["requirement_id"] = rid
        states[rid] = merged
        _write_verification_states_unlocked(path, states)
    return merged


def read_lifecycle_events(out_dir: Path) -> list[dict[str, Any]]:
    path = governed_artifact_path(Path(out_dir).expanduser().resolve(),
                                  REQUIREMENT_LIFECYCLE_EVENTS_FILE, category="state", for_write=False)
    return _read_jsonl_tolerant(path)


def append_lifecycle_event(out_dir: Path, event: dict[str, Any]) -> None:
    """append-only 生命周期事件（前进/回退均留痕）。锁内追加。"""
    root = Path(out_dir).expanduser().resolve()
    with verification_state_lock(root):
        path = governed_artifact_path(root, REQUIREMENT_LIFECYCLE_EVENTS_FILE, category="state")
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_manual_requirements(out_dir: Path) -> list[dict[str, Any]]:
    path = governed_artifact_path(Path(out_dir).expanduser().resolve(),
                                  MANUAL_REQUIREMENTS_FILE, category="state", for_write=False)
    return _read_jsonl_tolerant(path)


def append_manual_requirement(out_dir: Path, record: dict[str, Any]) -> None:
    """锁内追加一条手工需求记录（append-only，去重由调用方保证幂等键）。"""
    root = Path(out_dir).expanduser().resolve()
    with verification_state_lock(root):
        path = governed_artifact_path(root, MANUAL_REQUIREMENTS_FILE, category="state")
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_dependency_decisions(out_dir: Path) -> list[dict[str, Any]]:
    path = governed_artifact_path(Path(out_dir).expanduser().resolve(),
                                  DEPENDENCY_DECISIONS_FILE, category="state", for_write=False)
    return _read_jsonl_tolerant(path)


def upsert_dependency_decision(out_dir: Path, decision: dict[str, Any]) -> dict[str, Any]:
    """锁内读-合并-原子写一条依赖裁决（接受才写库，拒绝不落库由调用方控制）。"""
    root = Path(out_dir).expanduser().resolve()
    key_fields = (
        str(decision.get("from") or ""),
        str(decision.get("to") or ""),
        str(decision.get("kind") or ""),
    )
    if not all(key_fields):
        raise ValueError("dependency decision requires from/to/kind")
    with verification_state_lock(root):
        path = governed_artifact_path(root, DEPENDENCY_DECISIONS_FILE, category="state")
        rows = _read_jsonl_tolerant(path)
        index = {
            (str(row.get("from") or ""), str(row.get("to") or ""), str(row.get("kind") or "")): row
            for row in rows
        }
        existing = dict(index.get(key_fields) or {})
        existing.update(decision)
        index[key_fields] = existing
        _atomic_write_jsonl(path, list(index.values()))
    return index[key_fields]


# ===========================================================================
# T3-1 RTM 边持久化：append-only 事件流（与生命周期事件同构）
# ---------------------------------------------------------------------------
# ``dependencies/parent/children`` 从候选推荐升格为持久化 RTM 边。事件流与
# ``append_lifecycle_event`` 同型（append-only + 跨进程锁 + governed state 路径）。每条事件
# 带 ``edge_id/kind/from/to/decision/actor/reason/recorded_at``。**accept 落边**（materialized
# 进 ``dependency_decisions.jsonl``，保留既有物化视图），**reject 留记录**（只在事件流，不落库）。
# ``replay_rtm_edges`` 确定性回放事件流重建当前边态——同一 edge 的 accept→reject→accept
# 序列按「最后决策胜出」回放。
# ===========================================================================
RTM_EDGE_EVENTS_FILE = "requirement_rtm_edges.jsonl"
RTM_EDGE_SCHEMA = "requirement-rtm-edge/v1"


def rtm_edge_id(frm: Any, to: Any, kind: Any) -> str:
    """确定性边身份：``(from, to, kind)`` 的稳定哈希。同一边的多次裁决（accept/reject）共 ID。"""
    basis = "\x1f".join(str(x or "") for x in (frm, to, kind))
    return "RTM-" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def read_rtm_edge_events(out_dir: Path) -> list[dict[str, Any]]:
    """只读 RTM 边事件流（tolerant：坏行跳过）。"""
    path = governed_artifact_path(
        Path(out_dir).expanduser().resolve(),
        RTM_EDGE_EVENTS_FILE, category="state", for_write=False,
    )
    return _read_jsonl_tolerant(path)


def append_rtm_edge_event(out_dir: Path, event: dict[str, Any]) -> None:
    """append-only RTM 边事件（与 ``append_lifecycle_event`` 同锁同流纪律）。

    ``event`` 至少含 ``kind/from/to/decision``；本函数补全 ``edge_id/recorded_at/schema``。
    accept 与 reject 都追加（reject 也留记录），由 ``replay_rtm_edges`` 重建终态。
    """
    root = Path(out_dir).expanduser().resolve()
    frm = str(event.get("from") or "")
    to = str(event.get("to") or "")
    kind = str(event.get("kind") or "")
    if not frm or not to or not kind:
        raise ValueError("rtm edge event requires from/to/kind")
    row = dict(event)
    row.update({
        "edge_id": rtm_edge_id(frm, to, kind),
        "from": frm,
        "to": to,
        "kind": kind,
        "decision": str(event.get("decision") or ""),
        "actor": str(event.get("actor") or ""),
        "reason": str(event.get("reason") or ""),
        "recorded_at": str(event.get("recorded_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")),
        "schema": RTM_EDGE_SCHEMA,
    })
    with verification_state_lock(root):
        path = governed_artifact_path(root, RTM_EDGE_EVENTS_FILE, category="state")
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def replay_rtm_edges(events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """确定性回放 RTM 边事件流 → ``{edges, accepted_count, rejected_count, event_count, skipped}``。

    * ``edges``：``{edge_id: {...decision...}}``，最后决策胜出（accept→reject→accept 取末尾）。
    * accept 的边即「落边」；reject 的边留在 ``edges`` 但 ``decision="reject"``（不进物化库）。
    回放幂等：同事件流两次回放结果逐字节一致。坏事件（缺 decision/edge_id）跳过并计入 ``skipped``。
    """
    edges: dict[str, dict[str, Any]] = {}
    skipped = 0
    for event in events:
        if not isinstance(event, dict):
            skipped += 1
            continue
        edge_id = str(event.get("edge_id") or "")
        decision = str(event.get("decision") or "").strip().lower()
        if not edge_id or decision not in {"accept", "reject"}:
            skipped += 1
            continue
        edges[edge_id] = {
            "edge_id": edge_id,
            "kind": str(event.get("kind") or ""),
            "from": str(event.get("from") or ""),
            "to": str(event.get("to") or ""),
            "decision": decision,
            "actor": str(event.get("actor") or ""),
            "reason": str(event.get("reason") or ""),
            "recorded_at": str(event.get("recorded_at") or ""),
        }
    accepted = sum(1 for e in edges.values() if e["decision"] == "accept")
    rejected = sum(1 for e in edges.values() if e["decision"] == "reject")
    return {
        "schema": RTM_EDGE_SCHEMA,
        "edges": edges,
        "accepted_count": accepted,
        "rejected_count": rejected,
        "event_count": len(events),
        "skipped": skipped,
    }
