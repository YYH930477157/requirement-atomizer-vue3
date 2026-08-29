"""队列投影一致性审计工具回归（任务 C，next-steps-plan-2026-08-29 §3.3）。

``tools/audit_review_queue_projection.py`` 是兼容期的只读体检工具：把统一事件链
``review_queue_events.jsonl`` 按各主体投影语义重放出「期望的旧文件内容」，与磁盘上
的四个旧文件（omission/clarification_check/review_states/ai_review_states）比对。

覆盖：
- 四主体各一条正例：真实 writer 写入 → 审计一致（exit 0）；
- 人为篡改旧文件一行 → drift 检出并定位到主体 id；
- 崩溃窗口（队列有事件、旧文件缺行）→ drift 检出——append-only 前缀对账族与
  A 轨 merge+单行替换族各验一条；
- llm_pipeline 批量 merge 写入的非 expert 行不在链上 → 不算 drift、计入
  ``non_queue_rows``；
- 队列文件损坏（撕裂尾）→ exit 3 fail-closed，绝不修复；
- 只读纪律：对 drift 包审计后，目录清单与全部文件字节不变（不补投影、不建锁）；
- 旧包（无队列文件）→ 一致（链上无事件即无可对账项）。
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import audit_review_queue_projection as audit  # noqa: E402

import ai_review_actions  # noqa: E402
import clarification_check_states as check_states  # noqa: E402
import omission_actions  # noqa: E402
import review_queue  # noqa: E402
import review_state  # noqa: E402


def _write_blocks(out: Path, *blocks: dict) -> None:
    with (out / "blocks.jsonl").open("w", encoding="utf-8") as handle:
        for block in blocks:
            handle.write(json.dumps(block, ensure_ascii=False) + "\n")


def _run_audit(out_dir: Path) -> tuple[int, dict]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = audit.main(["--out-dir", str(out_dir)])
    return code, json.loads(buffer.getvalue())


def _rewrite_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _snapshot_tree(out_dir: Path) -> dict[str, bytes]:
    return {
        str(item.relative_to(out_dir)): item.read_bytes()
        for item in sorted(out_dir.rglob("*"))
        if item.is_file()
    }


class AuditEnvelopeContractTests(unittest.TestCase):
    """CLI 契约：stdout 单 JSON envelope，exit 0=一致 / 2=drift / 3=输入损坏。"""

    def test_missing_out_dir_is_input_damage(self) -> None:
        code, payload = _run_audit(Path("Z:/definitely-not-here"))
        self.assertEqual(code, 3)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["type"], "input_error")

    def test_pre_queue_legacy_package_is_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _rewrite_jsonl(out / "review_states.jsonl", [
                {"requirement_id": "SREQ-OLD-1", "status": "accepted", "history": [], "metadata": {}},
                {"requirement_id": "SREQ-OLD-2", "status": "rejected", "history": [], "metadata": {}},
            ])
            code, payload = _run_audit(out)

        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "consistent")
        self.assertEqual(payload["chain"]["events"], 0)
        self.assertEqual(payload["stores"]["atom_expert"]["non_queue_rows"], 2)


class ConsistentProjectionTests(unittest.TestCase):
    """四主体各一条正例：真实 writer 写入 → 审计一致。"""

    def test_omission_write_then_audit_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(out, {"block_id": "B1", "text": "The meter shall log events."})
            omission_actions.apply_omission_action(
                out, block_id="B1", status="non_requirement", reason="标题",
                actor="reviewer",
            )
            code, payload = _run_audit(out)

        self.assertEqual(code, 0)
        self.assertEqual(payload["stores"]["omission"]["status"], "consistent")
        self.assertEqual(payload["stores"]["omission"]["events"], 1)
        self.assertEqual(payload["stores"]["omission"]["rows"], 1)
        self.assertEqual(payload["drift_count"], 0)

    def test_clarification_internal_write_then_audit_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            check_states.apply_clarification_check_actions_batch(out, [
                {"clarification_id": "CLR-1", "action": "verified_ok",
                 "evidence_fingerprint": "e1", "actor": "A"},
            ])
            code, payload = _run_audit(out)

        self.assertEqual(code, 0)
        self.assertEqual(payload["stores"]["clarification_internal"]["status"], "consistent")
        self.assertEqual(payload["drift_count"], 0)

    def test_atom_expert_write_then_audit_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            review_state.apply_expert_decision(
                out, "SREQ-1", "accepted", actor="expert", reason="通过",
            )
            review_state.apply_expert_decision(
                out, "SREQ-1", "needs_discussion", actor="expert", reason="再看",
            )
            code, payload = _run_audit(out)

        self.assertEqual(code, 0)
        self.assertEqual(payload["stores"]["atom_expert"]["status"], "consistent")
        self.assertEqual(payload["stores"]["atom_expert"]["events"], 2)
        self.assertEqual(payload["stores"]["atom_expert"]["rows"], 1)
        self.assertEqual(payload["drift_count"], 0)

    def test_ai_review_write_then_audit_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            ai_review_actions.apply_ai_review_action(
                out, "AIR-1", "accepted", actor="expert", reason="通过",
                module_override="计量",
            )
            code, payload = _run_audit(out)

        self.assertEqual(code, 0)
        self.assertEqual(payload["stores"]["ai_review"]["status"], "consistent")
        self.assertEqual(payload["drift_count"], 0)


class DriftDetectionTests(unittest.TestCase):
    """篡改与崩溃窗口：drift 检出 + 定位到主体 id。"""

    def test_tampered_ai_review_row_reports_drift_with_subject(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            ai_review_actions.apply_ai_review_action(
                out, "AIR-1", "accepted", actor="expert",
            )
            states_path = out / "ai_review_states.jsonl"
            rows = [json.loads(line) for line in states_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            rows[0]["status"] = "rejected"  # 人为篡改投影行
            _rewrite_jsonl(states_path, rows)
            code, payload = _run_audit(out)

        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "drift")
        store = payload["stores"]["ai_review"]
        self.assertEqual(store["status"], "drift")
        subjects = {item["subject_id"] for item in store["drift_items"]}
        self.assertIn("AIR-1", subjects)

    def test_crash_window_missing_projection_omission(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(out, {"block_id": "B1", "text": "The meter shall log events."})
            omission_actions.apply_omission_action(
                out, block_id="B1", status="non_requirement", actor="reviewer",
            )
            # 崩溃窗口：队列事件已落、旧文件投影未落。
            (out / omission_actions.OMISSION_STATES).write_text("", encoding="utf-8")
            code, payload = _run_audit(out)

        self.assertEqual(code, 2)
        store = payload["stores"]["omission"]
        missing = [item for item in store["drift_items"] if item["issue"] == "missing_projection"]
        self.assertEqual(len(missing), 1)
        self.assertTrue(missing[0]["subject_id"].startswith("OMI-"))

    def test_crash_window_missing_projection_atom_expert(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            review_state.apply_expert_decision(
                out, "SREQ-1", "accepted", actor="expert",
            )
            (out / "review_states.jsonl").write_text("", encoding="utf-8")
            code, payload = _run_audit(out)

        self.assertEqual(code, 2)
        store = payload["stores"]["atom_expert"]
        missing = [item for item in store["drift_items"] if item["issue"] == "missing_projection"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["subject_id"], "SREQ-1")

    def test_non_expert_automated_rows_are_not_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            review_state.apply_expert_decision(
                out, "SREQ-1", "accepted", actor="expert",
            )
            # llm_pipeline 批量 merge 写入的自动化行（无链事件、非 expert 主体）。
            # SREQ-1 行保持 writer 原样（只追加自动化行，不重写专家行）。
            states_path = out / "review_states.jsonl"
            rows = [
                json.loads(line)
                for line in states_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            rows.append({
                "requirement_id": "SREQ-AUTO", "status": "accepted",
                "history": [{"from_status": "draft", "to_status": "accepted",
                             "actor": "llm-reviewer", "reason": "", "timestamp": "t"}],
                "metadata": {}, "level": "atomic",
            })
            _rewrite_jsonl(states_path, rows)
            code, payload = _run_audit(out)

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "consistent")
        self.assertEqual(payload["stores"]["atom_expert"]["non_queue_rows"], 1)

    def test_corrupt_queue_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(out, {"block_id": "B1", "text": "The meter shall log events."})
            omission_actions.apply_omission_action(
                out, block_id="B1", status="non_requirement", actor="reviewer",
            )
            queue_path = out / review_queue.REVIEW_QUEUE_EVENTS
            raw = queue_path.read_bytes()
            queue_path.write_bytes(raw[:-6])  # 撕裂尾：截断最后一行
            code, payload = _run_audit(out)

        self.assertEqual(code, 3)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["type"], "input_damaged")


class ReadOnlyDisciplineTests(unittest.TestCase):
    """红线：绝对只读——不修复撕裂尾、不补投影、不创建任何文件。"""

    def test_drifted_package_bytes_unchanged_after_audit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_blocks(out, {"block_id": "B1", "text": "The meter shall log events."})
            omission_actions.apply_omission_action(
                out, block_id="B1", status="non_requirement", actor="reviewer",
            )
            (out / omission_actions.OMISSION_STATES).write_text("", encoding="utf-8")
            before = _snapshot_tree(out)
            code, _payload = _run_audit(out)
            after = _snapshot_tree(out)

        self.assertEqual(code, 2)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
