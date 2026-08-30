"""队列投影一致性审计工具（任务 C，next-steps-plan-2026-08-29 §3；零 LLM、零写入）。

兼容期体检：统一事件链 ``review_queue_events.jsonl``（队列收敛第 2/3 步的记录源）
按各主体投影语义重放出「期望的旧文件内容」，与四个旧兼容投影逐主体比对——
设计文档 ``docs/review-queue-convergence-design-2026-08-27.md`` §6 承诺投影
保持 ≥ 两个桌面发布周期，本工具让"投影正确性"在真实结果包上可随时对账，
而不只靠单元测试钉着。

对账语义（单一权威，绝不复制实现）：
  * omission / clarification_internal / ai_review —— append-only 序：复用
    ``review_queue.missing_projection_payloads`` 的行前缀对账（第 2 步/第 3 步
    B 轨语义）。匹配前缀之外的事件 = 缺投影（崩溃窗口残片）；匹配前缀之外的
    旧文件行 = 队列出现前的历史行或自动化行（``non_queue_rows``，不算 drift），
    但身份键命中链上主体的行是篡改/孤儿行（drift，定位到行号）。
  * atom_expert —— merge+单行替换语义：调用
    ``review_state._project_missing_expert_rows``（身份键索引的权威实现）在
    **临时副本**上得到「补投影后应有形态」，与磁盘行做逐位比对——真实文件
    零写入。追加位 = 缺投影；内容不一致位 = 行偏离最后事件 payload（带字段
    差异摘要）。``review_states.jsonl`` 上 llm_pipeline 批量 merge 写入的非
    expert 行不在链上（设计 §5.3：自动化路径刻意不入链），不计 drift，计入
    ``non_queue_rows`` 上报。

只读红线（计划 §3.5）：打开文件一律只读；**不修复、不补投影**——队列撕裂尾、
    中部损坏与旧文件不可解析一律 fail-closed（exit 3）。因此本工具不复用
    ``scan_review_queue_unlocked``（它会在撕裂尾时原子重写修复，恰好抹掉审计
    要发现的证据），而是复用其逐行验链核心 ``_validate_event_row`` +
    canonical 字节检查，在只读循环里重放。也不取 ``review_queue_lock``（取锁
    会创建锁文件/目录）；``os.replace`` 的原子性使无锁读到撕裂中间态的概率
    极低，读到了就如实报损坏。

CLI 契约（对齐 docs/cli-contract.md 同族）：stdout 恰一行 JSON envelope；
exit 0=全一致 / 2=发现 drift / 3=输入损坏（out-dir 缺失、队列链损坏、旧文件
不可解析）/ 1=内部错误（stderr 带 traceback）。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

# Make the repo root importable when run as ``python tools/audit_review_queue_projection.py``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import review_queue  # noqa: E402
import review_state  # noqa: E402
from result_package import governed_artifact_path  # noqa: E402

AUDIT_TOOL = "audit-review-queue-projection"
AUDIT_VERSION = "audit-review-queue-projection-v1"

# append-only 投影族：subject_kind → (旧文件名, 行身份键)。行身份键只用于
# drift 归因（把可疑行定位到主体 id），对账本身走 missing_projection_payloads。
APPEND_ONLY_STORES: dict[str, tuple[str, str]] = {
    review_queue.SUBJECT_KIND_OMISSION: (
        review_queue.SUBJECT_KIND_LEGACY_STORES[review_queue.SUBJECT_KIND_OMISSION],
        "omission_id",
    ),
    review_queue.SUBJECT_KIND_CLARIFICATION_INTERNAL: (
        review_queue.SUBJECT_KIND_LEGACY_STORES[review_queue.SUBJECT_KIND_CLARIFICATION_INTERNAL],
        "clarification_id",
    ),
    review_queue.SUBJECT_KIND_AI_REVIEW: (
        review_queue.SUBJECT_KIND_LEGACY_STORES[review_queue.SUBJECT_KIND_AI_REVIEW],
        "ai_req_id",
    ),
}
ATOM_EXPERT_FILE = review_queue.SUBJECT_KIND_LEGACY_STORES[review_queue.SUBJECT_KIND_ATOM_EXPERT]


class AuditInputDamaged(RuntimeError):
    """输入损坏（out-dir 缺失 / 队列链损坏 / 旧文件不可解析）——exit 3。"""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


def _scan_chain_readonly(root: Path) -> list[dict[str, Any]]:
    """Read-only chain validation（复用 review_queue 的逐行验链，绝不修复）。

    与 ``scan_review_queue_unlocked`` 的唯一差异：撕裂尾/损坏不恢复、不重写，
    直接作为输入损坏上报——修复是写路径的职责（计划 §3.5 红线）。
    """
    path = governed_artifact_path(
        root, review_queue.REVIEW_QUEUE_EVENTS, category="state", for_write=False
    )
    if not path.exists():
        return []
    raw = path.read_bytes()
    rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    previous_hash = review_queue._GENESIS_PREV_EVENT_HASH  # noqa: SLF001 - 复用创世哈希常量
    offset = 0
    while offset < len(raw):
        newline = raw.find(b"\n", offset)
        if newline < 0:
            raise AuditInputDamaged(
                "input_damaged",
                f"{review_queue.REVIEW_QUEUE_EVENTS} has a torn tail at byte {offset}; "
                "read-only audit does not repair",
            )
        line = raw[offset : newline + 1]
        try:
            if line.endswith(b"\r\n") or line == b"\n":
                raise review_queue.ReviewQueueError("event log is not canonical JSONL")
            row = json.loads(line[:-1].decode("utf-8"))
            if review_queue._canonical_bytes(row) + b"\n" != line:  # noqa: SLF001 - 复用canonical检查
                raise review_queue.ReviewQueueError("event line is not canonical")
            row = review_queue._validate_event_row(  # noqa: SLF001 - 复用验链权威
                row, len(rows) + 1, previous_hash
            )
            key = str(row["idempotency_key"])
            if key in seen_keys:
                raise review_queue.ReviewQueueError("idempotency key is duplicated")
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
            review_queue.ReviewQueueError,
        ) as exc:
            raise AuditInputDamaged(
                "input_damaged",
                f"{review_queue.REVIEW_QUEUE_EVENTS} is damaged at byte {offset}: {exc}",
            ) from exc
        rows.append(row)
        seen_keys.add(key)
        previous_hash = str(row["event_hash"])
        offset = newline + 1
    return rows


def _read_legacy_rows(root: Path, filename: str) -> list[dict[str, Any]] | None:
    """Read legacy projection rows; ``None`` = 文件不存在（合法：从未有过该主体写入）。"""
    path = governed_artifact_path(root, filename, category="state", for_write=False)
    if not path.exists():
        return None
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AuditInputDamaged(
            "input_damaged", f"{filename} is not valid UTF-8: {exc}"
        ) from exc
    if text and not text.endswith("\n"):
        raise AuditInputDamaged(
            "input_damaged", f"{filename} has a torn tail; read-only audit does not repair"
        )
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.split("\n")[:-1] if text else [], start=1):
        if not line.strip():
            raise AuditInputDamaged(
                "input_damaged", f"{filename} line {line_no} is empty"
            )
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AuditInputDamaged(
                "input_damaged", f"{filename} line {line_no} is not JSON: {exc}"
            ) from exc
        if not isinstance(row, dict):
            raise AuditInputDamaged(
                "input_damaged", f"{filename} line {line_no} is not an object"
            )
        rows.append(row)
    return rows


def _audit_append_only_store(
    filename: str,
    identity_key: str,
    events: list[dict[str, Any]],
    legacy_rows: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    rows = legacy_rows or []
    missing = review_queue.missing_projection_payloads(events, rows)
    matched = len(events) - len(missing)
    subject_ids = {str(event["subject_id"]) for event in events}
    history = rows[: len(rows) - matched] if matched else rows
    drift_items: list[dict[str, Any]] = []
    non_queue_rows = 0
    # missing_projection_payloads 返回 payload 列表；对应事件 = events[matched:]。
    for event in events[matched:]:
        drift_items.append({
            "issue": "missing_projection",
            "subject_id": str(event["subject_id"]),
            "event_seq": int(event["event_seq"]),
        })
    for line_no, row in enumerate(history, start=1):
        subject = str(row.get(identity_key) or "")
        if subject and subject in subject_ids:
            drift_items.append({
                "issue": "orphan_or_tampered_row",
                "subject_id": subject,
                "line": line_no,
            })
        else:
            non_queue_rows += 1
    return {
        "legacy_file": filename,
        "exists": legacy_rows is not None,
        "rows": len(rows),
        "events": len(events),
        "matched_projection_prefix": matched,
        "non_queue_rows": non_queue_rows,
        "drift_items": drift_items,
        "status": "drift" if drift_items else "consistent",
    }


def _subject_of_row(row: dict[str, Any], payload_index: dict[str, str]) -> str:
    key = json.dumps(row, ensure_ascii=False, sort_keys=True)
    return payload_index.get(key, "")


def _audit_atom_expert_store(
    root: Path,
    all_rows: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """merge+单行替换族：权威实现跑在临时副本上，真实文件零写入。"""
    path = governed_artifact_path(root, ATOM_EXPERT_FILE, category="state", for_write=False)
    disk_rows = _read_legacy_rows(root, ATOM_EXPERT_FILE) or []
    last_by_subject: dict[str, dict[str, Any]] = {}
    for event in events:
        last_by_subject[str(event["subject_id"])] = event
    payload_index = {
        json.dumps(dict(event["payload"]), ensure_ascii=False, sort_keys=True): subject_id
        for subject_id, event in last_by_subject.items()
    }

    expected_rows = disk_rows
    if events:
        snapshot = review_queue.ReviewQueueSnapshot(
            rows=[dict(row) for row in all_rows],
            last_event_seq=len(all_rows),
            last_event_hash=(
                str(all_rows[-1]["event_hash"])
                if all_rows
                else review_queue._GENESIS_PREV_EVENT_HASH  # noqa: SLF001 - 创世哈希常量
            ),
            idempotency_keys=frozenset(
                str(row["idempotency_key"]) for row in all_rows
            ),
        )
        with tempfile.TemporaryDirectory() as td:
            temp_path = Path(td) / ATOM_EXPERT_FILE
            if path.exists():
                shutil.copyfile(path, temp_path)
            expected_rows = review_state._project_missing_expert_rows(  # noqa: SLF001 - 单一权威
                temp_path, snapshot
            )

    drift_items: list[dict[str, Any]] = []
    for index in range(min(len(disk_rows), len(expected_rows))):
        if disk_rows[index] == expected_rows[index]:
            continue
        subject_id = _subject_of_row(expected_rows[index], payload_index)
        fields = sorted(
            key
            for key in set(disk_rows[index]) | set(expected_rows[index])
            if disk_rows[index].get(key) != expected_rows[index].get(key)
        )
        drift_items.append({
            "issue": "row_differs_from_last_event_payload",
            "subject_id": subject_id,
            "line": index + 1,
            "fields": fields[:8],
        })
    for index in range(len(disk_rows), len(expected_rows)):
        drift_items.append({
            "issue": "missing_projection",
            "subject_id": _subject_of_row(expected_rows[index], payload_index),
            "line": index + 1,
        })

    non_queue_rows = 0
    for row in disk_rows:
        keys = set(review_state.requirement_identity_keys(row))
        if not keys & set(last_by_subject):
            non_queue_rows += 1
    return {
        "legacy_file": ATOM_EXPERT_FILE,
        "exists": path.exists(),
        "rows": len(disk_rows),
        "events": len(events),
        "non_queue_rows": non_queue_rows,
        "drift_items": drift_items,
        "status": "drift" if drift_items else "consistent",
    }


def run_audit(out_dir: Path) -> dict[str, Any]:
    root = Path(out_dir).expanduser().resolve()
    if not root.is_dir():
        raise AuditInputDamaged(
            "input_error", f"out dir does not exist: {out_dir}"
        )
    rows = _scan_chain_readonly(root)
    stores: dict[str, Any] = {}
    for kind, (filename, identity_key) in APPEND_ONLY_STORES.items():
        events = [row for row in rows if row["subject_kind"] == kind]
        stores[kind] = _audit_append_only_store(
            filename, identity_key, events, _read_legacy_rows(root, filename)
        )
    atom_events = [
        row for row in rows
        if row["subject_kind"] == review_queue.SUBJECT_KIND_ATOM_EXPERT
    ]
    stores[review_queue.SUBJECT_KIND_ATOM_EXPERT] = _audit_atom_expert_store(
        root, rows, atom_events
    )
    drift_count = sum(len(store["drift_items"]) for store in stores.values())
    return {
        "kind": "audit_review_queue_projection",
        "tool": AUDIT_TOOL,
        "version": AUDIT_VERSION,
        "ok": drift_count == 0,
        "status": "drift" if drift_count else "consistent",
        "out_dir": str(root),
        "chain": {
            "events": len(rows),
            "last_event_seq": int(rows[-1]["event_seq"]) if rows else 0,
            "by_subject": {
                kind: int(store["events"]) for kind, store in stores.items()
            },
        },
        "stores": stores,
        "drift_count": drift_count,
    }


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=AUDIT_TOOL,
        description="只读审计：统一评审事件链 ↔ 四个旧投影文件的一致性对账",
    )
    parser.add_argument(
        "--out-dir", type=Path, required=True, help="结果包根目录（只读，绝不写入）"
    )
    args = parser.parse_args(argv)
    try:
        payload = run_audit(args.out_dir)
    except AuditInputDamaged as exc:
        _emit({
            "kind": "audit_review_queue_projection",
            "tool": AUDIT_TOOL,
            "version": AUDIT_VERSION,
            "ok": False,
            "error": {"type": exc.error_type, "message": str(exc)},
        })
        return 3
    except Exception as exc:  # noqa: BLE001 - envelope契约：内部错误也要一行JSON
        _emit({
            "kind": "audit_review_queue_projection",
            "tool": AUDIT_TOOL,
            "version": AUDIT_VERSION,
            "ok": False,
            "error": {"type": "internal_error", "message": f"{type(exc).__name__}: {exc}"},
        })
        return 1
    _emit(payload)
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
