"""claim_review_actions 事件日志底层（M9 第 5 刀，2026-08-17）。

从 ``claim_review_actions.py`` 逐字搬运的事件日志 journal 簇：规范 JSONL 扫描
（哈希链/序号/幂等键/模式校验/撕裂尾与隔离修复）、事件 id/哈希域原语、
``ClaimReviewActionError`` 与 ``EventLogSnapshot``。``claim_review_actions``
原名重导出，调用面（含 claim_artifacts 对 ``_scan_event_log_unlocked`` 的消费）
零变化。

选族纪律（M9 蓝图红线）：本簇不含任何测试 patch 目标
（``out/m9-patch-targets.json`` claim_review_actions 7 个全部留守
``claim_review_actions.py``）；依赖只有 claim_artifacts（常量/哈希/原子写/模式
校验）——不反向依赖 claim_review_actions，无环。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claim_artifacts import (
    CLAIM_REVIEW_EVENTS,
    ClaimArtifactError,
    _atomic_write_bytes,
    _validate_schema,
    canonical_json_value_bytes,
    claim_artifact_path,
    digest_hex,
    hash_json,
    sha256_bytes,
)
from claim_ledger import (
    CLAIM_REVIEW_EVENT_SCHEMA,
    LEGACY_CLAIM_REVIEW_EVENT_SCHEMA,
)

LOGGER = logging.getLogger("requirement_atomizer")
_EMPTY_SHA256 = sha256_bytes(b"")
_EVENT_QUARANTINE_PREFIX = ".claim-review-events-quarantine-"


class ClaimReviewActionError(ClaimArtifactError):
    pass


@dataclass(frozen=True)
class EventLogSnapshot:
    rows: list[dict[str, Any]]
    prefix_bytes: bytes
    event_prefix_sha256: str
    last_event_seq: int
    last_event_hash: str
    idempotency_keys: frozenset[str]
    torn_tail_recovered: bool = False
    quarantine_file: str | None = None


def _event_without_hash(event: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if key != "event_hash"}


def _event_schema_file(event: dict[str, Any]) -> str:
    schema = str(event.get("schema") or "")
    if schema == LEGACY_CLAIM_REVIEW_EVENT_SCHEMA:
        return "claim_review_event.schema.json"
    if schema == CLAIM_REVIEW_EVENT_SCHEMA:
        return "claim_review_event_v2.schema.json"
    raise ClaimReviewActionError(f"unsupported claim review event schema: {schema!r}")


def _event_hash_domain(event: dict[str, Any]) -> str:
    schema = str(event.get("schema") or "")
    if schema in {LEGACY_CLAIM_REVIEW_EVENT_SCHEMA, CLAIM_REVIEW_EVENT_SCHEMA}:
        return schema
    raise ClaimReviewActionError(f"unsupported claim review event schema: {schema!r}")


def _event_id(event_seq: int, idempotency_key: str) -> str:
    return f"CRE-{event_seq}-{digest_hex(idempotency_key)[:12]}"


def _quarantine_suffix(root: Path, suffix: bytes) -> str:
    digest = digest_hex(sha256_bytes(suffix))
    name = f"{_EVENT_QUARANTINE_PREFIX}{digest}.bin"
    path = claim_artifact_path(root, name)
    if path.is_file():
        if path.read_bytes() != suffix:
            raise ClaimReviewActionError("claim event quarantine digest collision")
        return name
    _atomic_write_bytes(path, suffix)
    return name


def _repair_event_suffix(
    root: Path,
    raw: bytes,
    valid_end: int,
    *,
    torn_tail: bool,
) -> tuple[bytes, str | None]:
    suffix = raw[valid_end:]
    quarantine_file = None
    if suffix and not torn_tail:
        quarantine_file = _quarantine_suffix(root, suffix)
    _atomic_write_bytes(claim_artifact_path(root, CLAIM_REVIEW_EVENTS), raw[:valid_end])
    return raw[:valid_end], quarantine_file


def _scan_event_log_unlocked(
    root: Path,
    *,
    repair: bool,
    raw: bytes | None = None,
) -> EventLogSnapshot:
    path = claim_artifact_path(root, CLAIM_REVIEW_EVENTS)
    if raw is None and not path.exists():
        return EventLogSnapshot(
            rows=[],
            prefix_bytes=b"",
            event_prefix_sha256=_EMPTY_SHA256,
            last_event_seq=0,
            last_event_hash=_EMPTY_SHA256,
            idempotency_keys=frozenset(),
        )

    if raw is None:
        raw = path.read_bytes()
    rows: list[dict[str, Any]] = []
    idempotency_keys: set[str] = set()
    previous_hash = _EMPTY_SHA256
    offset = 0
    valid_end = 0
    torn_tail = False
    failure: Exception | None = None

    while offset < len(raw):
        newline = raw.find(b"\n", offset)
        if newline < 0:
            torn_tail = True
            failure = ClaimReviewActionError("claim review event log has a torn tail")
            break
        line_end = newline + 1
        line = raw[offset:line_end]
        try:
            if line in {b"\n", b"\r\n"} or line.endswith(b"\r\n"):
                raise ClaimReviewActionError("claim review event log is not canonical JSONL")
            row = json.loads(line[:-1].decode("utf-8"))
            if not isinstance(row, dict):
                raise ClaimReviewActionError("claim review event is not an object")
            if canonical_json_value_bytes(row) + b"\n" != line:
                raise ClaimReviewActionError("claim review event line is not canonical")
            _validate_schema(
                row,
                _event_schema_file(row),
                label="claim review event",
            )
            expected_seq = len(rows) + 1
            if row.get("event_seq") != expected_seq:
                raise ClaimReviewActionError("claim review event sequence is not contiguous")
            if row.get("event_id") != _event_id(expected_seq, str(row["idempotency_key"])):
                raise ClaimReviewActionError("claim review event id is invalid")
            if row.get("prev_event_hash") != previous_hash:
                raise ClaimReviewActionError("claim review event hash chain is broken")
            expected_hash = hash_json(
                _event_hash_domain(row),
                _event_without_hash(row),
            )
            if row.get("event_hash") != expected_hash:
                raise ClaimReviewActionError("claim review event hash is invalid")
            idempotency_key = str(row.get("idempotency_key") or "")
            if idempotency_key in idempotency_keys:
                raise ClaimReviewActionError("claim review event idempotency key is duplicated")
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
            ClaimArtifactError,
        ) as exc:
            failure = exc
            break
        rows.append(row)
        idempotency_keys.add(idempotency_key)
        previous_hash = str(row["event_hash"])
        valid_end = line_end
        offset = line_end

    recovered = False
    quarantine_file = None
    if failure is not None:
        if not repair:
            raise ClaimReviewActionError(str(failure)) from failure
        raw, quarantine_file = _repair_event_suffix(
            root,
            raw,
            valid_end,
            torn_tail=torn_tail,
        )
        recovered = torn_tail
        LOGGER.warning(
            "recovered claim review event suffix at byte %d (%s)",
            valid_end,
            "torn tail" if torn_tail else f"quarantine={quarantine_file}",
        )
    prefix = raw[:valid_end] if failure is not None else raw
    return EventLogSnapshot(
        rows=rows,
        prefix_bytes=prefix,
        event_prefix_sha256=sha256_bytes(prefix),
        last_event_seq=len(rows),
        last_event_hash=previous_hash,
        idempotency_keys=frozenset(idempotency_keys),
        torn_tail_recovered=recovered,
        quarantine_file=quarantine_file,
    )
