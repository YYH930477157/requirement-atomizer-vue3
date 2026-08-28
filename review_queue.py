"""评审队列统一事件链账本（队列收敛第 2 步，设计 §4.1/§4.3）。

一条 append-only、文件级哈希链的评审事件账本 ``review_queue_events.jsonl``
（governed state 路径）。本步接入的两个主体：

- ``subject_kind=omission`` —— ``omission_actions.apply_omission_action``；
- ``subject_kind=clarification_internal`` —— ``clarification_check_states``
  的单条/批量内部核对动作。

写路径纪律（设计 §4.3 第 2 步）：单一跨进程锁内 → 先 append 队列事件 → 再按
与旧 writer **逐字节相同**的行形状把 ``payload`` 投影回旧 JSONL
（``omission_states.jsonl`` / ``clarification_check_states.jsonl``）。队列是
记录源，旧文件是兼容投影——所有既有读者（API GET、``clarification_report``
就绪门、``agent_state``、xlsx 导入回读）零改动继续工作。崩溃窗口（队列事件
已落、投影未落）由下一次同 root 写入时的投影补齐闭合：按事件序对账旧文件
尾部，缺失的投影行按序补写，绝不出现队列有事件而旧文件永久缺行。

与 claim 事件链的边界：链协议形状（seq/幂等键/prev_event_hash/event_hash）
参照 ``claim_review_events``，但**不接进 claim generation/fold**——omission
与内部核对不参与 claim 代际（设计 §4.3 第 2 步的明确边界）。

统一的是机械，不是语义（设计 §4.1/§5.3）：``subject_kind`` 分派 CAS 与生命
周期；``omission.issue_confirmed`` 与内部核对 ``issue_confirmed`` 是两个主体
下的同名不同义动作，事件行靠 ``subject_kind`` 区分，绝不引入统一状态枚举。
``authority_write_revision`` 对这两类没有既有物理写修订公式的主体，记录的是
队列推导的该主体事件序号（审计用），**不是** CAS 代币——各主体自己的 CAS
（``omission_source_fingerprint`` / ``expected_evidence_fingerprint``）仍在
各自 writer 里分派比对。

锁与写入机械照抄 ``review_state.py`` 同族：``process_file_lock`` 跨进程锁 +
同卷 tmp + fsync + ``os.replace`` 原子替换 + ``PermissionError`` 8 次线性退避。
本模块不进任何抽取缓存指纹（``REVIEW_QUEUE_EVENT_SCHEMA`` 只是行契约常量）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from process_file_lock import process_file_lock
from result_package import governed_artifact_path


REVIEW_QUEUE_EVENTS = "review_queue_events.jsonl"
REVIEW_QUEUE_LOCK = "review_queue.lock"
REVIEW_QUEUE_EVENT_SCHEMA = "review-queue-event/v1"

SUBJECT_KIND_OMISSION = "omission"
SUBJECT_KIND_CLARIFICATION_INTERNAL = "clarification_internal"
# 设计 §4.2：过渡期事件行携带旧文件名（legacy_source_store），主体与投影落点一一对应。
SUBJECT_KIND_LEGACY_STORES = {
    SUBJECT_KIND_OMISSION: "omission_states.jsonl",
    SUBJECT_KIND_CLARIFICATION_INTERNAL: "clarification_check_states.jsonl",
}
# 设计 §4.1 的 event_kind 枚举全集（本步只用 decided/deferred/queued）。
VALID_EVENT_KINDS = {"decided", "invalidated", "restored", "deferred", "queued"}

_LOCK_TIMEOUT_S = 10.0
_REPLACE_ATTEMPTS = 8
_REPLACE_RETRY_DELAY_S = 0.02
_PROCESS_LOCKS: dict[tuple[Path, str], RLock] = {}
_PROCESS_LOCKS_GUARD = RLock()
LOGGER = logging.getLogger("requirement_atomizer")

_GENESIS_PREV_EVENT_HASH = "sha256:" + hashlib.sha256(b"").hexdigest()


class ReviewQueueError(RuntimeError):
    """事件链结构性损坏（中部损坏/链断裂/非法行）——fail-closed，响亮抛错。"""


def _canonical_bytes(payload: Any) -> bytes:
    """Canonical JSON bytes（与 claim_artifacts.canonical_json_value_bytes 同式）。"""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def compute_event_hash(event_without_hash: dict[str, Any]) -> str:
    """``event_hash`` = sha256(canonical({domain, payload=event 去掉 event_hash}))。"""
    body = {key: value for key, value in event_without_hash.items() if key != "event_hash"}
    digest = hashlib.sha256(
        _canonical_bytes({"domain": REVIEW_QUEUE_EVENT_SCHEMA, "payload": body})
    ).hexdigest()
    return "sha256:" + digest


def build_event_id(event_seq: int, idempotency_key: str) -> str:
    digest = hashlib.sha256(str(idempotency_key).encode("utf-8")).hexdigest()
    return f"RQE-{event_seq}-{digest[:12]}"


def _process_lock_for(root: Path, name: str) -> RLock:
    """Per-(root, lock family) in-process serializer（review_state 同构）。"""
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault((root, name), RLock())


@contextmanager
def review_queue_lock(
    out_dir: Path,
    *,
    timeout_s: float = _LOCK_TIMEOUT_S,
) -> Iterator[None]:
    """Serialize queue writers/readers across threads and processes.

    照抄 ``review_state.review_state_lock`` 模式：进程内 RLock（按 root+锁族键控）
    + ``process_file_lock`` 跨进程文件锁（稳定 inode、不猜存活、锁文件常驻）。
    """
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    process_lock = _process_lock_for(root, "review_queue")
    with process_lock:
        lock_path = governed_artifact_path(root, REVIEW_QUEUE_LOCK, category="state")
        with process_file_lock(
            lock_path,
            timeout_s=timeout_s,
            label="review queue lock",
        ):
            yield


@dataclass
class ReviewQueueSnapshot:
    """一次锁内扫描得到的已验证链前缀。

    ``rows`` 是链上全部已验证事件（按 event_seq 升序）。append 会原地把新事件
    追加进同一 snapshot 并整文件原子重写——snapshot 只在持有
    ``review_queue_lock`` 的同一临界区内使用。
    """

    rows: list[dict[str, Any]] = field(default_factory=list)
    last_event_seq: int = 0
    last_event_hash: str = _GENESIS_PREV_EVENT_HASH
    idempotency_keys: frozenset[str] = frozenset()
    _idempotency_keys_mut: set[str] = field(default_factory=set)
    torn_tail_recovered: bool = False

    def has_idempotency_key(self, key: str) -> bool:
        return key in self._idempotency_keys_mut


def _validate_event_row(row: Any, expected_seq: int, previous_hash: str) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ReviewQueueError("review queue event is not an object")
    if row.get("schema") != REVIEW_QUEUE_EVENT_SCHEMA:
        raise ReviewQueueError(f"unsupported review queue event schema: {row.get('schema')!r}")
    # 必填且非空：主体身份/链身份/落点/时间戳。actor/reason 按设计 §4.1 必填但
    # 允许空串（omission 旧行 actor=None、reason="" 是合法形态，投影保真）。
    for key in (
        "subject_kind", "subject_id", "subject_fingerprint", "idempotency_key",
        "event_kind", "recorded_at", "legacy_source_store",
    ):
        if not isinstance(row.get(key), str) or not str(row[key]):
            raise ReviewQueueError(f"review queue event field {key!r} must be a non-empty string")
    for key in ("actor", "reason"):
        if not isinstance(row.get(key), str):
            raise ReviewQueueError(f"review queue event field {key!r} must be a string")
    if row["subject_kind"] not in SUBJECT_KIND_LEGACY_STORES:
        raise ReviewQueueError(f"unsupported review queue subject kind: {row['subject_kind']!r}")
    if row["legacy_source_store"] != SUBJECT_KIND_LEGACY_STORES[row["subject_kind"]]:
        raise ReviewQueueError("review queue event legacy store does not match its subject kind")
    if row["event_kind"] not in VALID_EVENT_KINDS:
        raise ReviewQueueError(f"invalid review queue event kind: {row['event_kind']!r}")
    revision = row.get("authority_write_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ReviewQueueError("review queue event authority_write_revision must be a positive int")
    payload = row.get("payload")
    if not isinstance(payload, dict) or not payload:
        raise ReviewQueueError("review queue event payload must be a non-empty object")
    if row.get("event_seq") != expected_seq:
        raise ReviewQueueError("review queue event sequence is not contiguous")
    if row.get("event_id") != build_event_id(expected_seq, row["idempotency_key"]):
        raise ReviewQueueError("review queue event id is invalid")
    if row.get("prev_event_hash") != previous_hash:
        raise ReviewQueueError("review queue event hash chain is broken")
    if row.get("event_hash") != compute_event_hash(row):
        raise ReviewQueueError("review queue event hash is invalid")
    return row


def _atomic_write_events(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = b"".join(_canonical_bytes(row) + b"\n" for row in rows)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp_path.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        replace_with_retry(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def replace_with_retry(source: Path, target: Path) -> None:
    """os.replace + PermissionError 8 次线性退避（review_state.py 同款）。

    队列收敛后的单源退避（设计 §5.2：各模块退避次数不一致会让偶发替换失败
    被误读成 CAS 失败）——投影写路径（如 clarification 整历史替换）共用本实现。
    """
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt + 1 >= _REPLACE_ATTEMPTS:
                raise
            time.sleep(_REPLACE_RETRY_DELAY_S * (attempt + 1))


def scan_review_queue_unlocked(root: Path) -> ReviewQueueSnapshot:
    """Validate the whole chain under the caller-held ``review_queue_lock``.

    撕裂尾（最后一行无行终止符——原子替换写路径不该产生，出现即中断写残片）：
    截断到最近一条完整行并原子落盘恢复（io_utils 纪律）。中部损坏、行非法、
    序号断裂、链哈希对不上：``ReviewQueueError`` 响亮抛错 fail-closed，绝不
    静默跳过。
    """
    root = Path(root).expanduser().resolve()
    path = governed_artifact_path(root, REVIEW_QUEUE_EVENTS, category="state")
    snapshot = ReviewQueueSnapshot()
    if not path.exists():
        return snapshot
    raw = path.read_bytes()
    rows: list[dict[str, Any]] = []
    idempotency_keys: set[str] = set()
    previous_hash = _GENESIS_PREV_EVENT_HASH
    offset = 0
    valid_end = 0
    torn_tail = False
    while offset < len(raw):
        newline = raw.find(b"\n", offset)
        if newline < 0:
            torn_tail = True
            break
        line_end = newline + 1
        line = raw[offset:line_end]
        try:
            if line.endswith(b"\r\n") or line == b"\n":
                raise ReviewQueueError("review queue event log is not canonical JSONL")
            row = json.loads(line[:-1].decode("utf-8"))
            if _canonical_bytes(row) + b"\n" != line:
                raise ReviewQueueError("review queue event line is not canonical")
            row = _validate_event_row(row, len(rows) + 1, previous_hash)
            key = row["idempotency_key"]
            if key in idempotency_keys:
                raise ReviewQueueError("review queue event idempotency key is duplicated")
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ReviewQueueError(
                f"review queue event log is damaged at byte {offset}: {exc}"
            ) from exc
        rows.append(row)
        idempotency_keys.add(key)
        previous_hash = str(row["event_hash"])
        valid_end = line_end
        offset = line_end

    if torn_tail:
        # 只恢复"最后一行未终止"的写残片；已终止的坏行在上面已经 fail-closed。
        _atomic_write_events(path, rows)
        LOGGER.warning(
            "recovered torn review queue event tail at byte %d (%d rows kept)", valid_end, len(rows)
        )
    snapshot.rows = rows
    snapshot.last_event_seq = len(rows)
    snapshot.last_event_hash = previous_hash if rows else _GENESIS_PREV_EVENT_HASH
    snapshot.idempotency_keys = frozenset(idempotency_keys)
    snapshot._idempotency_keys_mut = idempotency_keys  # noqa: SLF001 - same-module dataclass
    snapshot.torn_tail_recovered = torn_tail
    return snapshot


def read_review_queue_events(out_dir: Path) -> list[dict[str, Any]]:
    """Read the validated chain（锁内；撕裂尾可恢复，中部损坏 fail-closed）。"""
    root = Path(out_dir).expanduser().resolve()
    with review_queue_lock(root):
        return scan_review_queue_unlocked(root).rows


def _validated_draft(draft: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(draft, dict):
        raise ReviewQueueError("review queue event draft must be an object")
    kind = str(draft.get("subject_kind") or "")
    if kind not in SUBJECT_KIND_LEGACY_STORES:
        raise ReviewQueueError(f"unsupported review queue subject kind: {kind!r}")
    for key in ("subject_id", "subject_fingerprint", "idempotency_key", "recorded_at"):
        if not isinstance(draft.get(key), str) or not str(draft[key]):
            raise ReviewQueueError(f"review queue event draft field {key!r} is required")
    if str(draft.get("event_kind") or "") not in VALID_EVENT_KINDS:
        raise ReviewQueueError(f"invalid review queue event kind: {draft.get('event_kind')!r}")
    payload = draft.get("payload")
    if not isinstance(payload, dict) or not payload:
        raise ReviewQueueError("review queue event draft payload must be a non-empty object")
    return draft


def append_review_queue_events_unlocked(
    root: Path,
    snapshot: ReviewQueueSnapshot,
    drafts: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], bool]]:
    """Append drafts onto ``snapshot``'s chain under the caller-held queue lock.

    幂等键重放：draft 的 ``idempotency_key`` 已在链上时返回既有事件并标记
    ``replayed=True``，不追加新行、不重写文件（其投影由崩溃窗口补齐保证在场）。
    """
    root = Path(root).expanduser().resolve()
    path = governed_artifact_path(root, REVIEW_QUEUE_EVENTS, category="state")
    results: list[tuple[dict[str, Any], bool]] = []
    appended = False
    for draft in drafts:
        _validated_draft(draft)
        kind = str(draft["subject_kind"])
        subject_id = str(draft["subject_id"])
        key = str(draft["idempotency_key"])
        existing = next(
            (row for row in snapshot.rows if row["idempotency_key"] == key), None
        )
        if existing is not None:
            results.append((dict(existing), True))
            continue
        seq = snapshot.last_event_seq + 1
        write_revision = 1 + sum(
            1
            for row in snapshot.rows
            if row["subject_kind"] == kind and row["subject_id"] == subject_id
        )
        event: dict[str, Any] = {
            "schema": REVIEW_QUEUE_EVENT_SCHEMA,
            "event_seq": seq,
            "event_id": build_event_id(seq, key),
            "subject_kind": kind,
            "subject_id": subject_id,
            "subject_fingerprint": str(draft["subject_fingerprint"]),
            "authority_write_revision": write_revision,
            "idempotency_key": key,
            "event_kind": str(draft["event_kind"]),
            "actor": str(draft.get("actor") or ""),
            "recorded_at": str(draft["recorded_at"]),
            "reason": str(draft.get("reason") or ""),
            "legacy_source_store": SUBJECT_KIND_LEGACY_STORES[kind],
            "payload": draft["payload"],
            "prev_event_hash": snapshot.last_event_hash,
        }
        event["event_hash"] = compute_event_hash(event)
        snapshot.rows.append(event)
        snapshot.last_event_seq = seq
        snapshot.last_event_hash = str(event["event_hash"])
        snapshot._idempotency_keys_mut.add(key)
        snapshot.idempotency_keys = frozenset(snapshot._idempotency_keys_mut)
        results.append((dict(event), False))
        appended = True
    if appended:
        _atomic_write_events(path, snapshot.rows)
    return results


def append_review_queue_event(out_dir: Path, draft: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """锁内扫描 + 追加单个事件（测试/直连用；生产写路径走 *_unlocked 组合）。"""
    root = Path(out_dir).expanduser().resolve()
    with review_queue_lock(root):
        snapshot = scan_review_queue_unlocked(root)
        return append_review_queue_events_unlocked(root, snapshot, [draft])[0]


def missing_projection_payloads(
    store_events: list[dict[str, Any]],
    legacy_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Reconcile queue events against the legacy file; return unprojected payloads.

    投影在锁内按事件序逐条补写，因此旧文件 = [队列出现前的历史行...] +
    [某段事件前缀的 payload]。取最大的 p 使旧文件**末 p 行** == **前 p 个事件**
    的 payload，p 之后的事件即缺投影（崩溃窗口残片），按序返回待补写。旧文件
    含队列出现前的历史行是合法形态（本步不做历史回填，设计 §4.3）。
    """
    payloads = [event["payload"] for event in store_events]
    p = min(len(payloads), len(legacy_rows))
    while p > 0 and legacy_rows[-p:] != payloads[:p]:
        p -= 1
    return payloads[p:]
