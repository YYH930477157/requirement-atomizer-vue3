"""AI 抽取需求的审核裁决存储（独立于确定性 atomic 的状态机）。

文档批注视图里，专家直接在批注上裁决 AI 抽取出的需求。AI 需求没有 atomic 那套
review_states 状态机，这里给它一套轻量的覆盖式裁决：

- 内容稳定 ID（ai_req_id）：从 source_section + source_quote + title 取指纹，跨复跑稳定
  （merged_spec 里的 REQ-NNN 是位置号，会随抽取结果漂移，不能用作持久裁决主键）。
- ai_review_states.jsonl 追加写、读时取每个 ai_req_id 的最新一行（最近裁决覆盖）。
- 裁决含 status + 可选 module_override（专家改模块）+ reason；纯本地单用户工具，不做状态机约束。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from requirements_analysis_schema import normalize_ownership
from process_file_lock import process_file_lock
from result_package import governed_artifact_path

AI_REVIEW_STATES = "ai_review_states.jsonl"
AI_TARGET_AUTHORITY_WRITE_REVISION_VERSION = "ai-target-authority-write-revision-v1"
VALID_AI_STATUS = {"accepted", "rejected", "needs_discussion", "expert_pending", "draft"}
MODULE_OVERRIDE_MAX_LENGTH = 20
_AI_REVIEW_LOCKS: dict[Path, RLock] = {}
_AI_REVIEW_LOCKS_GUARD = RLock()
_AI_REVIEW_LOCK_TIMEOUT_S = 10.0
_AI_REVIEW_LOCK_STALE_AFTER_S = 300.0
LOGGER = logging.getLogger("requirement_atomizer")


class AIReviewAuthorityConflict(ValueError):
    """The displayed B-track authority row is no longer the writable row."""

    def __init__(self, message: str, *, current_revision: str) -> None:
        super().__init__(message)
        self.current_revision = str(current_revision)


_REVIEW_SUBJECT_FIELDS = (
    "title",
    "functional_key",
    "description",
    "type",
    "priority",
    "module",
    "ownership",
    "threshold_table",
    "sub_items",
    "acceptance_criteria",
    "dev_guidance",
    "design_options",
    "dependencies",
)

# 功能级评审对象的核心叙述字段（审查 2026-08-15 P1）：objective/behaviors 等变了而
# subject 指纹不变，会让专家在旧叙述上的裁决被静默沿用。行内存在任一功能字段时并入
# 指纹——原子行不含这些键，指纹不变（存量裁决零失效）。
_FUNCTIONAL_REVIEW_SUBJECT_FIELDS = (
    "objective",
    "behaviors",
    "preconditions",
    "data_constraints",
    "variants",
    "exceptions",
    "related_dlms_objects",
)


def normalize_module_override(value: str | None) -> str | None:
    if value is None:
        return None
    module = str(value).strip()
    if not module:
        raise ValueError("module_override must not be empty")
    if len(module) > MODULE_OVERRIDE_MAX_LENGTH:
        raise ValueError(f"module_override must not exceed {MODULE_OVERRIDE_MAX_LENGTH} characters")
    return module


def _fingerprint_payload(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def source_fingerprint(req: dict[str, Any]) -> str:
    """Hash only source evidence, never model/prompt/guard configuration."""
    return _fingerprint_payload({
        "source_section": str(req.get("source_section") or ""),
        "source_quote": str(req.get("source_quote") or ""),
        "source_block_ids": [str(value) for value in (req.get("source_block_ids") or [])],
    })


def review_anchor_fingerprint(req: dict[str, Any]) -> str:
    """Best-effort logical anchor that survives title/quote edits within the same source blocks."""
    return _fingerprint_payload({
        "source_section": str(req.get("source_section") or ""),
        "source_block_ids": [str(value) for value in (req.get("source_block_ids") or [])],
    })


def review_subject_fingerprint(req: dict[str, Any]) -> str:
    """Hash the requirement fields an expert is actually adjudicating.

    功能级条目（行内存在功能叙述字段）把 objective/behaviors/… 一并纳入——专家裁决
    的对象是这些叙述本身；原子行不含这些键，指纹与旧实现逐字节一致。
    """
    payload = {key: req.get(key) for key in _REVIEW_SUBJECT_FIELDS}
    if any(req.get(key) is not None for key in _FUNCTIONAL_REVIEW_SUBJECT_FIELDS):
        payload.update(
            {key: req.get(key) for key in _FUNCTIONAL_REVIEW_SUBJECT_FIELDS}
        )
    return _fingerprint_payload(payload)


def ensure_requirement_identity(
    req: dict[str, Any],
    *,
    extraction_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Persist the stable logical id and the three distinct fingerprint roles."""
    req["ai_req_id"] = source_ai_requirement_id(req)
    req["source_fingerprint"] = source_fingerprint(req)
    req["review_anchor_fingerprint"] = review_anchor_fingerprint(req)
    req["review_subject_fingerprint"] = review_subject_fingerprint(req)
    if extraction_fingerprint is not None:
        req["extraction_fingerprint"] = str(extraction_fingerprint)
    return req


def review_state_needs_reconfirmation(
    req: dict[str, Any], state: dict[str, Any] | None,
) -> bool:
    """Legacy states remain valid; fingerprinted states must match current content."""
    if not state:
        return False
    expected_source = str(state.get("source_fingerprint") or "")
    expected_subject = str(state.get("review_subject_fingerprint") or "")
    # Recompute from the current fields. Persisted fingerprints are provenance metadata,
    # not authority: a manually migrated/stale row must not conceal content drift.
    current_source = source_fingerprint(req)
    current_subject = review_subject_fingerprint(req)
    if expected_source and expected_source != current_source:
        return True
    if expected_subject and expected_subject != current_subject:
        return True
    return False


def review_state_for_requirement(
    req: dict[str, Any], states: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Resolve exact identity first, then one unambiguous fingerprinted legacy state."""
    exact = states.get(source_ai_requirement_id(req))
    if exact is not None:
        return exact
    current_source = source_fingerprint(req)
    matches = [
        state for state in states.values()
        if str(state.get("source_fingerprint") or "") == current_source
    ]
    if len(matches) == 1:
        return matches[0]
    current_anchor = review_anchor_fingerprint(req)
    anchor_matches = [
        state for state in states.values()
        if str(state.get("review_anchor_fingerprint") or "") == current_anchor
    ]
    return anchor_matches[0] if len(anchor_matches) == 1 else None


def ai_req_id(req: dict[str, Any]) -> str:
    """内容稳定 ID：source_section + source_quote + title 的 sha1 指纹（防 REQ-NNN 位置漂移）。"""
    basis = "|".join([
        str(req.get("source_section") or ""),
        str(req.get("source_quote") or ""),
        str(req.get("title") or ""),
    ])
    return "AIR-" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def source_ai_requirement_id(req: dict[str, Any]) -> str:
    """裁决/批注/分析统一的需求主键：行内显式 id 优先，否则内容指纹 ai_req_id。

    唯一权威实现——api_server / ai_extract / requirements_analysis 都用它，三份复制迟早分叉。
    警告：绝不能把位置型编号（make_doc 的 REQ-NNN）写进这些字段，否则复跑后裁决静默失配。
    显式 id 优先级：原子链 ai_req_id/stable_req_id/req_id 在前；功能级
    functional_requirement_id（FRE-）/requirement_uid（FR-）随后（§3.3/§3.4：直抽条目
    以稳定功能主键进评审与 claim，原子行不含这两个键，互不干扰）。
    """
    for key in (
        "ai_req_id", "stable_req_id", "req_id",
        "functional_requirement_id", "requirement_uid",
    ):
        explicit = str(req.get(key) or "").strip()
        if explicit:
            return explicit
    return ai_req_id(req)


def read_ai_review_states(out_dir: Path) -> dict[str, dict[str, Any]]:
    """取每个 ai_req_id 的最新裁决，并与追加写使用同一进程锁。"""
    return dict(read_ai_review_authority_snapshot(out_dir)["states"])


def _empty_ai_review_authority_snapshot() -> dict[str, Any]:
    empty_hash = "sha256:" + hashlib.sha256(b"").hexdigest()
    return {
        "source_store": AI_REVIEW_STATES,
        "states": {},
        "source_records": {},
        "ordered_records": [],
        "audit_gaps": [],
        "torn_tail_recovered": False,
        "authority_file_sha256": empty_hash,
    }


def _authority_snapshot_from_scan(scan: dict[str, Any]) -> dict[str, Any]:
    states: dict[str, dict[str, Any]] = {}
    source_records: dict[str, dict[str, Any]] = {}
    ordered_records: list[dict[str, Any]] = []
    for record in scan["ordered_records"]:
        row = dict(record["state"])
        ordinal = int(record["append_ordinal"])
        rid = str(row.get("ai_req_id") or "")
        states[rid] = row
        source_record = {
            "append_ordinal": ordinal,
            "source_event_revision": record["source_event_revision"],
            "state": row,
        }
        source_records[rid] = source_record
        ordered_records.append(source_record)
    return {
        "source_store": AI_REVIEW_STATES,
        "states": states,
        "source_records": source_records,
        "ordered_records": ordered_records,
        "audit_gaps": list(scan["audit_gaps"]),
        "torn_tail_recovered": bool(scan["torn_tail_recovered"]),
        "authority_file_sha256": scan["authority_file_sha256"],
    }


def read_ai_review_authority_snapshot(out_dir: Path) -> dict[str, Any]:
    """Return current authority plus every ordered source row and visible audit gap."""
    root = Path(out_dir).expanduser().resolve()
    path = governed_artifact_path(root, AI_REVIEW_STATES, category="state")
    with _ai_review_state_lock(root):
        if not path.exists():
            return _empty_ai_review_authority_snapshot()
        return _authority_snapshot_from_scan(_scan_ai_review_rows_unlocked(path))


def read_ai_review_authority_snapshot_readonly(out_dir: Path) -> dict[str, Any]:
    """Read a stable authority snapshot without locks or torn-tail recovery."""
    root = Path(out_dir).expanduser().resolve()
    path = governed_artifact_path(root, AI_REVIEW_STATES, category="state")
    before = path.read_bytes() if path.is_file() else None
    snapshot = (
        _empty_ai_review_authority_snapshot()
        if before is None
        else _authority_snapshot_from_scan(
            _scan_ai_review_rows_unlocked(
                path,
                raw=before,
                repair_torn_tail=False,
            )
        )
    )
    after = path.read_bytes() if path.is_file() else None
    if after != before:
        raise ValueError("AI review authority changed during read-only read")
    return snapshot


def ai_target_authority_write_revision(
    ai_req_id_value: str,
    snapshot: dict[str, Any],
) -> str:
    """Return the per-target physical authority revision used by B-track CAS.

    This is deliberately different from the semantic ``target_review_revision``
    projected by :mod:`claim_ledger`: append ordinal and source event revision
    make a rejected->restored (ABA) sequence observable even when the effective
    status returns to the same value.  Unrelated target rows do not advance this
    target's token.
    """
    from claim_artifacts import hash_json

    target_id = str(ai_req_id_value or "").strip()
    source_record = (snapshot.get("source_records") or {}).get(target_id)
    if isinstance(source_record, dict):
        state = source_record.get("state")
        state_hash = hash_json(
            f"{AI_TARGET_AUTHORITY_WRITE_REVISION_VERSION}:row",
            state if isinstance(state, dict) else {},
        )
        binding = {
            "append_ordinal": source_record.get("append_ordinal"),
            "source_event_revision": str(source_record.get("source_event_revision") or ""),
            "state_hash": state_hash,
        }
    else:
        binding = {
            "append_ordinal": None,
            "source_event_revision": None,
            "state_hash": None,
        }
    return hash_json(
        AI_TARGET_AUTHORITY_WRITE_REVISION_VERSION,
        {
            "source_store": str(snapshot.get("source_store") or AI_REVIEW_STATES),
            "target_kind": "ai_requirement",
            "target_requirement_id": target_id,
            "binding": binding,
        },
    )


def _replace_ai_review_bytes(path: Path, payload: bytes) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.{os.getpid()}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(8):
            try:
                os.replace(temporary, path)
                temporary = None
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _scan_ai_review_rows_unlocked(
    path: Path,
    *,
    raw: bytes | None = None,
    repair_torn_tail: bool = True,
) -> dict[str, Any]:
    """Scan physical records without renumbering valid rows across complete gaps."""
    from claim_artifacts import hash_json

    if raw is None:
        raw = path.read_bytes()
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    body = raw[len(bom):]
    lines = body.splitlines(keepends=True)
    records: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    append_ordinal = 0
    torn_tail_recovered = False
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not stripped:
            continue
        append_ordinal += 1
        try:
            row = json.loads(stripped.decode("utf-8"))
            if not isinstance(row, dict):
                raise ValueError("record is not an object")
            if not str(row.get("ai_req_id") or ""):
                raise ValueError("record has no ai_req_id")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            is_unterminated_tail = (
                index == len(lines) - 1
                and not raw_line.endswith((b"\n", b"\r"))
            )
            if is_unterminated_tail:
                if not repair_torn_tail:
                    raise ValueError("AI review authority has a torn tail") from exc
                recovered = bom + b"".join(lines[:index])
                _replace_ai_review_bytes(path, recovered)
                raw = recovered
                torn_tail_recovered = True
                LOGGER.warning("repaired interrupted final AI review record: %s", path)
                break
            gaps.append({
                "physical_line_number": index + 1,
                "append_ordinal": append_ordinal,
                "reason": type(exc).__name__,
                "line_sha256": "sha256:" + hashlib.sha256(raw_line).hexdigest(),
            })
            LOGGER.warning(
                "preserving audit gap in %s at physical line %d (record %d)",
                AI_REVIEW_STATES,
                index + 1,
                append_ordinal,
            )
            continue
        source_revision = hash_json(
            "claim-source-event-revision/v1",
            {
                "source_store": AI_REVIEW_STATES,
                "append_ordinal": append_ordinal,
                "source_row": row,
            },
        )
        records.append({
            "append_ordinal": append_ordinal,
            "source_event_revision": source_revision,
            "state": row,
        })
    return {
        "ordered_records": records,
        "audit_gaps": gaps,
        "torn_tail_recovered": torn_tail_recovered,
        "authority_file_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
    }


def _read_ai_review_rows_unlocked(path: Path) -> list[dict[str, Any]]:
    return [
        dict(record["state"])
        for record in _scan_ai_review_rows_unlocked(path)["ordered_records"]
    ]


@contextmanager
def _ai_review_state_lock(
    out_dir: Path,
    *,
    timeout_s: float = _AI_REVIEW_LOCK_TIMEOUT_S,
    stale_after_s: float = _AI_REVIEW_LOCK_STALE_AFTER_S,
) -> Iterator[None]:
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    with _ai_process_lock_for(root):
        lock_path = governed_artifact_path(root, "ai_review_states.lock", category="state")
        # Kept as a compatibility argument for callers; OS ownership, not mtime,
        # determines whether a lock is live.
        del stale_after_s
        with process_file_lock(
            lock_path,
            timeout_s=timeout_s,
            label="AI review state lock",
        ):
            yield


def _ai_process_lock_for(out_dir: Path) -> RLock:
    with _AI_REVIEW_LOCKS_GUARD:
        return _AI_REVIEW_LOCKS.setdefault(out_dir, RLock())


def apply_ai_review_action(
    out_dir: Path,
    ai_req_id_value: str,
    status: str,
    *,
    module_override: str | None = None,
    ownership_override: str | None = None,
    reason: str = "",
    actor: str | None = None,
    source_fingerprint_value: str | None = None,
    review_subject_fingerprint_value: str | None = None,
    review_anchor_fingerprint_value: str | None = None,
    expected_target_authority_write_revision: str | None = None,
    level: str | None = None,
) -> dict[str, Any]:
    """追加一条 AI 需求裁决，返回写入的 state。

    WS2 §4.3 ``level``（functional/atomic）：显式标注评审对象粒度。缺省时不写该键——
    旧 ai_review_states 文件无 level，读路径经 review_state.review_level() 解释为 atomic，
    零迁移打开。
    """
    ai_req_id_value = str(ai_req_id_value or "").strip()
    if not ai_req_id_value:
        raise ValueError("ai_req_id is required")
    status = str(status or "").strip()
    if status not in VALID_AI_STATUS:
        raise ValueError(f"invalid status: {status}")
    module = normalize_module_override(module_override)
    ownership_text = str(ownership_override or "").strip()
    ownership = normalize_ownership(ownership_text) if ownership_text else None
    state = {
        "ai_req_id": ai_req_id_value,
        "status": status,
        "module_override": module,
        "ownership_override": ownership,
        "reason": str(reason or ""),
        "actor": actor,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if level is not None:
        from review_state import normalize_review_level
        state["level"] = normalize_review_level(level)
    if source_fingerprint_value:
        state["source_fingerprint"] = str(source_fingerprint_value)
    if review_subject_fingerprint_value:
        state["review_subject_fingerprint"] = str(review_subject_fingerprint_value)
    if review_anchor_fingerprint_value:
        state["review_anchor_fingerprint"] = str(review_anchor_fingerprint_value)
    out_dir = Path(out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    with _ai_review_state_lock(out_dir):
        states_path = governed_artifact_path(out_dir, AI_REVIEW_STATES, category="state")
        if states_path.is_file():
            authority_snapshot = _authority_snapshot_from_scan(
                _scan_ai_review_rows_unlocked(states_path)
            )
        else:
            authority_snapshot = _empty_ai_review_authority_snapshot()
        current_write_revision = ai_target_authority_write_revision(
            ai_req_id_value,
            authority_snapshot,
        )
        if (
            expected_target_authority_write_revision is not None
            and str(expected_target_authority_write_revision)
            != current_write_revision
        ):
            raise AIReviewAuthorityConflict(
                "AI review authority changed; refresh before adjudicating",
                current_revision=current_write_revision,
            )
        with governed_artifact_path(
            out_dir, AI_REVIEW_STATES, category="state"
        ).open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(state, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        # Re-scan after the append so the returned token is the exact physical
        # prefix the next request must bind to.
        updated_snapshot = _authority_snapshot_from_scan(
            _scan_ai_review_rows_unlocked(states_path)
        )
        state["target_authority_write_revision"] = ai_target_authority_write_revision(
            ai_req_id_value,
            updated_snapshot,
        )
    # package_v1 下该文件在 .ratomizer/state/，裸路径闸门会静默吞掉 fold 钩子（审查 B1 同族）
    if governed_artifact_path(
        out_dir, "claim_generation.meta.json", category="state"
    ).is_file():
        # 与 review_state 共享同一 per-root 合并器：A/B 混合突发也只折叠成最少的
        # fold pass（fold 幂等，caught-up 时 publication_skipped 近似 no-op）。
        from review_state import cover_effective_fold_after_decision

        cover_effective_fold_after_decision(
            out_dir,
            actor_trigger="ai-review-action",
            authority_hook_track="B",
            fold_lag_log_template="AI review saved; claim effective fold lagged: %s",
        )
    return state
