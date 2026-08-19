"""WP-B 点解析（spot_extract）：参数表行确定性产出 / 非参数行 LLM 路径 / draft+suspicion+provenance /
id 冲突序号化 / LLM 缺失响亮报错 / 澄清策略映射 / API 端点（全部 mock LLM）。"""
from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import ai_extract
from atomize import render_table_text
from io_utils import read_jsonl
from spot_extract import (
    SPOT_EXTRACT_VERSION,
    SPOT_SOURCE_MAPPING,
    SPOT_SUSPICION,
    SpotExtractUnavailableError,
    _assign_spot_ids,
    spot_extract,
)
from table_structure import TABLE_STRUCTURE_VERSION


def _structure_fields(rows: int, columns: int) -> dict:
    """当前 table-structure 证据：row 入口的结构版本门只接受当前版本块。"""
    return {
        "rows": rows,
        "columns": columns,
        "header_row_count": 1,
        "title_row_indexes": [],
        "header_row_indexes": [1],
        "table_structure_version": TABLE_STRUCTURE_VERSION,
    }


def _param_block() -> dict:
    headers = ["No.", "Parameter Name", "Technical requirements"]
    data_rows = [
        ["1.", "Rated voltage", "The meter shall operate at 230 V."],
        ["2.", "Rated frequency", "The meter shall operate at 50 Hz."],
        ["3.", "Backup power", "The meter shall include a reserve power supply."],
    ]
    return {
        "block_id": "BLK-000098",
        "order": 2,
        "type": "table",
        "headers": headers,
        "data_rows": data_rows,
        "text": render_table_text(headers, data_rows),
        "section_path": ["5. General Technical Requirements", "5.1. Single-phase IPUE"],
        "requirement_like": True,
        "noise": False,
        **_structure_fields(rows=4, columns=3),
    }


def _terms_block() -> dict:
    headers = ["No.", "Term", "Definition"]
    data_rows = [
        ["1.", "Overvoltage magnitude", "The maximum voltage value recorded."],
        ["2.", "Firmware", "Software that processes information."],
        ["3.", "Data", "Information from measuring instruments."],
    ]
    return {
        "block_id": "BLK-000061",
        "order": 1,
        "type": "table",
        "headers": headers,
        "data_rows": data_rows,
        "text": render_table_text(headers, data_rows),
        "section_path": ["3. Terms and Definitions"],
        "requirement_like": True,
        "noise": False,
        **_structure_fields(rows=4, columns=3),
    }


def _paragraph_block() -> dict:
    return {
        "block_id": "BLK-000200",
        "order": 3,
        "type": "paragraph",
        "text": "The enclosure shall provide IP54 protection against dust and water ingress.",
        "section_path": ["5. General Technical Requirements"],
        "requirement_like": True,
        "noise": False,
    }


def _seed_out(out: Path, blocks: list[dict], requirements: list[dict] | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "blocks.jsonl").write_text(
        "".join(json.dumps(block, ensure_ascii=False) + "\n" for block in blocks),
        encoding="utf-8",
    )
    (out / ai_extract.AI_REQUIREMENTS).write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in (requirements or [])),
        encoding="utf-8",
    )
    ai_extract.write_ai_requirements_metadata(
        out, input_fingerprint=ai_extract.extraction_input_fingerprint(out), run_id="test")


def _fake_llm_row(block_id: str) -> dict:
    return {
        "title": "外壳防护等级",
        "description": "外壳应提供 IP54 防尘防水防护。",
        "type": "non_functional",
        "priority": "P1",
        "module": "机械结构",
        "labels": ["环境可靠性"],
        "source_section": "5.1. Single-phase IPUE",
        "source_quote": "The enclosure shall provide IP54 protection against dust and water ingress.",
        "source_block_ids": [block_id],
        "anchor_block_id": block_id,
        "source_mapping": "quote",
        "status": "draft",
        "self_check_added": True,
        "suspicion_reasons": ["自检补充（初抽遗漏）"],
    }


def _llm_patches(row: dict):
    """mock LLM：config_for_route 返回伪配置；critique_section 返回单行；chat_json 不得真调。"""
    config = mock.Mock()
    config.model = "fake-model"
    return (
        mock.patch.object(ai_extract, "config_for_route", return_value=config),
        mock.patch.object(ai_extract, "critique_section", return_value=([row], [])),
        mock.patch("llm_client.apply_min_tokens", side_effect=lambda cfg, _kind: cfg),
        mock.patch("llm_client.chat_json",
                   side_effect=AssertionError("测试内不得发起真实 LLM 调用")),
    )


class DeterministicParamRowTests(unittest.TestCase):
    def test_param_row_produces_draft_with_spot_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            block = _param_block()
            _seed_out(out, [block])

            result = spot_extract(out, block_id="BLK-000098", row_index=1)

            self.assertEqual(result["strategy"], "deterministic_param_row")
            self.assertEqual(result["drafts"], 1)
            self.assertFalse(result["already_covered"])
            rows = read_jsonl(out / ai_extract.AI_REQUIREMENTS)
            self.assertEqual(len(rows), 1)
            draft = rows[0]
            self.assertEqual(draft["ai_req_id"], "SPOT-BLK-000098-R1")
            self.assertEqual(draft["status"], "draft")
            self.assertEqual(draft["source_mapping"], SPOT_SOURCE_MAPPING)
            self.assertEqual(draft["suspicion_reasons"], [SPOT_SUSPICION])
            self.assertEqual(draft["source_block_ids"], ["BLK-000098"])
            self.assertEqual(draft["source_quote"],
                             "1. | Rated voltage | The meter shall operate at 230 V.")
            self.assertIn(draft["source_quote"], block["text"])   # 引句逐字来自渲染行
            self.assertEqual(draft["title"], "Rated voltage")
            self.assertEqual(draft["spot_extract"]["version"], SPOT_EXTRACT_VERSION)
            self.assertEqual(draft["spot_extract"]["strategy"], "deterministic_param_row")
            # 交付物同步刷新（同 targeted_reextract 纪律）
            self.assertIn(ai_extract.AI_REQUIREMENTS, result["written"])
            self.assertTrue((out / ai_extract.COMPLIANCE_REQUIREMENTS).exists())
            self.assertTrue((out / "ai_extract_quality.json").exists())

    def test_covered_row_reports_already_covered_without_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            block = _param_block()
            existing = {
                "ai_req_id": "AIR-existing",
                "title": "电气参数",
                "description": "The meter shall operate at 230 V.",
                "source_quote": "The meter shall operate at 230 V.",
                "source_block_ids": ["BLK-000098"],
            }
            _seed_out(out, [block], [existing])
            before = (out / ai_extract.AI_REQUIREMENTS).read_text(encoding="utf-8")

            result = spot_extract(out, block_id="BLK-000098", row_index=1)

            self.assertTrue(result["already_covered"])
            self.assertEqual(result["drafts"], 0)
            self.assertEqual((out / ai_extract.AI_REQUIREMENTS).read_text(encoding="utf-8"), before)

    def test_id_conflict_gets_serial_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            block = _param_block()
            existing = {
                "ai_req_id": "SPOT-BLK-000098-R1",
                "title": "既有点解析条目",
                "description": "already here",
                "source_quote": "something else entirely",
                "source_block_ids": ["BLK-000098"],
            }
            _seed_out(out, [block], [existing])

            result = spot_extract(out, block_id="BLK-000098", row_index=1)

            self.assertEqual(result["draft_ids"], ["SPOT-BLK-000098-R1-2"])
            ids = [row["ai_req_id"] for row in read_jsonl(out / ai_extract.AI_REQUIREMENTS)]
            self.assertEqual(ids, ["SPOT-BLK-000098-R1", "SPOT-BLK-000098-R1-2"])

    def test_assign_spot_ids_sequence_for_multi_rows(self) -> None:
        rows = [{"ai_req_id": ""} for _ in range(3)]
        _assign_spot_ids(rows, block_id="B1", row_index=None, existing_ids={"SPOT-B1"})
        self.assertEqual([row["ai_req_id"] for row in rows],
                         ["SPOT-B1-2", "SPOT-B1-3", "SPOT-B1-4"])

    def test_row_index_out_of_range_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, [_param_block()])
            with self.assertRaises(ValueError):
                spot_extract(out, block_id="BLK-000098", row_index=99)

    def test_row_index_on_paragraph_block_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, [_paragraph_block()])
            with self.assertRaises(ValueError):
                spot_extract(out, block_id="BLK-000200", row_index=1)

    def test_unknown_block_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, [_param_block()])
            with self.assertRaises(ValueError):
                spot_extract(out, block_id="BLK-NOPE")

    def test_row_entry_on_legacy_block_requires_base_migration(self) -> None:
        """S12：row 入口与 cell 入口统一 fail-closed——旧产物（无当前
        table_structure 证据）的行点解析返回 base_migration_required，
        不得按连续偏移假设猜物理行号。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            block = _param_block()
            for key in (
                "table_structure_version",
                "title_row_indexes",
                "header_row_indexes",
                "header_row_count",
            ):
                block.pop(key, None)
            _seed_out(out, [block])
            before = (out / ai_extract.AI_REQUIREMENTS).read_text(encoding="utf-8")
            with self.assertRaises(ValueError) as raised:
                spot_extract(out, block_id="BLK-000098", row_index=1)
            self.assertIn("base_migration_required", str(raised.exception))
            self.assertEqual(
                (out / ai_extract.AI_REQUIREMENTS).read_text(encoding="utf-8"), before
            )

    def test_row_entry_on_stale_structure_version_requires_base_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            block = _param_block()
            block["table_structure_version"] = "table-structure-v5"
            _seed_out(out, [block])
            with self.assertRaises(ValueError) as raised:
                spot_extract(out, block_id="BLK-000098", row_index=1)
            self.assertIn("base_migration_required", str(raised.exception))


class LlmSpotPathTests(unittest.TestCase):
    def test_llm_path_writes_attempt_ledger_via_job_runner(self) -> None:
        """M8 迁移：spot 的每轮 LLM 调用经 LLMJobRunner——账本在案且归属正确。"""
        from llm_job_runner import LLM_JOB_ATTEMPTS_FILENAME

        def critique(section, existing, chat, doc_context, context_ints,
                     focus_lines=None):
            payload = chat("system-marker", "user-marker")   # 经 runner 的闭包
            self.assertEqual(payload, {"touched": True})
            return ([_fake_llm_row(str(section["block_ids"][0]))], [])

        config = mock.Mock()
        config.model = "fake-model"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            block = _paragraph_block()
            _seed_out(out, [block])
            with mock.patch.object(ai_extract, "config_for_route",
                                   return_value=config),                     mock.patch.object(ai_extract, "critique_section",
                                      side_effect=critique),                     mock.patch("llm_client.apply_min_tokens",
                               side_effect=lambda cfg, _kind: cfg),                     mock.patch("llm_client.chat_json_with_meta",
                               return_value=({"touched": True},
                                             {"usage": {"total_tokens": 7},
                                              "call_count": 1})):
                result = spot_extract(out, block_id="BLK-000200")
            self.assertEqual(result["strategy"], "llm")
            ledger = out / LLM_JOB_ATTEMPTS_FILENAME
            self.assertTrue(ledger.is_file())
            rows = [json.loads(line) for line in
                    ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(rows[0]["stage"], "spot-extract")
            self.assertEqual(rows[0]["processor"], "critique_section")
            self.assertEqual(rows[0]["unit_id"], "spot:BLK-000200")
            self.assertEqual(rows[0]["outcome"], "initial")
            self.assertEqual(rows[0]["execution_status"], "ok")

    def test_paragraph_block_llm_path_appends_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            block = _paragraph_block()
            _seed_out(out, [block])
            config_patch, critique_patch, min_tokens_patch, chat_patch = _llm_patches(
                _fake_llm_row("BLK-000200"))
            with config_patch, critique_patch as critique, min_tokens_patch, chat_patch:
                result = spot_extract(out, block_id="BLK-000200")

            self.assertEqual(result["strategy"], "llm")
            self.assertEqual(result["drafts"], 1)
            # 合成 section 只含本段文本——prompt 范围限定单段（targeted_reextract 调用方式）
            section = critique.call_args.args[0]
            self.assertEqual(section["text"], block["text"])
            self.assertEqual(section["block_ids"], ["BLK-000200"])
            self.assertEqual(critique.call_args.kwargs["focus_lines"], [block["text"]])
            rows = read_jsonl(out / ai_extract.AI_REQUIREMENTS)
            draft = rows[0]
            self.assertEqual(draft["ai_req_id"], "SPOT-BLK-000200")
            self.assertEqual(draft["source_mapping"], SPOT_SOURCE_MAPPING)
            self.assertEqual(draft["status"], "draft")
            self.assertEqual(draft["source_block_ids"], ["BLK-000200"])
            self.assertIn(SPOT_SUSPICION, draft["suspicion_reasons"])
            self.assertNotIn("自检补充（初抽遗漏）", draft["suspicion_reasons"])
            self.assertNotIn("self_check_added", draft)

    def test_terms_table_row_uses_llm_path_not_deterministic(self) -> None:
        """术语表行不是需求型参数表行（用户裁定：术语行不是需求）→ 走 LLM 单段路径。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            block = _terms_block()
            _seed_out(out, [block])
            config_patch, critique_patch, min_tokens_patch, chat_patch = _llm_patches(
                _fake_llm_row("BLK-000061"))
            with config_patch, critique_patch as critique, min_tokens_patch, chat_patch:
                result = spot_extract(out, block_id="BLK-000061", row_index=2)

            self.assertEqual(result["strategy"], "llm")
            section = critique.call_args.args[0]
            self.assertEqual(section["text"],
                             "2. | Firmware | Software that processes information.")
            self.assertEqual(result["draft_ids"], ["SPOT-BLK-000061-R2"])

    def test_llm_empty_result_reports_covered_without_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, [_paragraph_block()])
            config = mock.Mock()
            before = (out / ai_extract.AI_REQUIREMENTS).read_text(encoding="utf-8")
            with mock.patch.object(ai_extract, "config_for_route", return_value=config), \
                    mock.patch.object(ai_extract, "critique_section", return_value=([], [])), \
                    mock.patch("llm_client.apply_min_tokens", side_effect=lambda cfg, _kind: cfg):
                result = spot_extract(out, block_id="BLK-000200")

            self.assertEqual(result["drafts"], 0)
            self.assertTrue(result["already_covered"])
            self.assertEqual((out / ai_extract.AI_REQUIREMENTS).read_text(encoding="utf-8"), before)

    def test_llm_unavailable_fails_loudly_without_stub_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, [_paragraph_block()])
            before = (out / ai_extract.AI_REQUIREMENTS).read_text(encoding="utf-8")
            with mock.patch.object(ai_extract, "config_for_route", return_value=None):
                with self.assertRaises(SpotExtractUnavailableError):
                    spot_extract(out, block_id="BLK-000200")
            # 不伪造 stub 抽取结果：产物逐字节未动
            self.assertEqual((out / ai_extract.AI_REQUIREMENTS).read_text(encoding="utf-8"), before)

    def test_non_openai_route_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, [_paragraph_block()])
            with self.assertRaises(SpotExtractUnavailableError):
                spot_extract(out, block_id="BLK-000200", route="stub")


class ClarificationPolicyTests(unittest.TestCase):
    def test_spot_suspicion_policy_mapping(self) -> None:
        from clarification_report import (
            AUDIENCE_INTERNAL,
            BLOCKER_IMPORTANT,
            CAT_AMBIGUOUS,
            TIER_HARD,
            suspicion_policy,
        )

        self.assertEqual(
            suspicion_policy(SPOT_SUSPICION),
            ("suspicion:spot_extract", CAT_AMBIGUOUS, AUDIENCE_INTERNAL, BLOCKER_IMPORTANT, TIER_HARD),
        )

    def test_clarification_report_lists_spot_entry(self) -> None:
        from clarification_report import collect_questions

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, [_param_block()])
            spot_extract(out, block_id="BLK-000098", row_index=1)

            entries = collect_questions(out)

            spot_entries = [entry for entry in entries
                            if entry.get("signal") == "suspicion:spot_extract"]
            self.assertEqual(len(spot_entries), 1)
            entry = spot_entries[0]
            self.assertEqual(entry["audience"], "内部核对")
            self.assertEqual(entry["tier"], "必答")
            self.assertEqual(entry["blocker_level"], "important")
            self.assertEqual(entry["category"], "模糊")
            self.assertEqual(entry["source_id"], "SPOT-BLK-000098-R1")
            self.assertIn("Rated voltage", entry["quote"] or entry["question"])


class SpotExtractApiTests(unittest.TestCase):
    _TOKEN = "spot-test-token"

    def _start_server(self, out_dir: Path) -> tuple[ThreadingHTTPServer, threading.Thread, int]:
        from api_server import RequirementAPIHandler

        class TestHandler(RequirementAPIHandler):
            pass

        TestHandler.output_dir = out_dir.resolve()
        TestHandler.allowed_origins = {"http://127.0.0.1:5173", "http://127.0.0.1:8770", "null"}
        TestHandler.local_token = self._TOKEN
        server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread, int(server.server_port)

    def _post(self, port: int, path: str, payload: dict) -> tuple[int, dict]:
        body = json.dumps(payload).encode("utf-8")
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request("POST", path, body=body,
                               headers={"Content-Type": "application/json",
                                        "X-Requirement-Atomizer-Token": self._TOKEN})
            response = connection.getresponse()
            raw = response.read()
            return response.status, json.loads(raw.decode("utf-8")) if raw else {}
        finally:
            connection.close()

    def test_endpoint_success_and_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, [_param_block()])
            server, thread, port = self._start_server(out)
            try:
                status, payload = self._post(port, "/spot-extract",
                                             {"block_id": "BLK-000098", "row_index": 2})
                self.assertEqual(status, 200)
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["drafts"], 1)
                self.assertEqual(payload["draft_ids"], ["SPOT-BLK-000098-R2"])

                # 冻结规格字面别名 /api/spot-extract 同一处理器
                status, payload = self._post(port, "/api/spot-extract",
                                             {"block_id": "BLK-000098", "row_index": 3})
                self.assertEqual(status, 200)
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["draft_ids"], ["SPOT-BLK-000098-R3"])
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_endpoint_llm_unavailable_returns_ok_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, [_paragraph_block()])
            server, thread, port = self._start_server(out)
            try:
                with mock.patch.object(ai_extract, "config_for_route", return_value=None):
                    status, payload = self._post(port, "/spot-extract",
                                                 {"block_id": "BLK-000200"})
                self.assertEqual(status, 503)
                self.assertFalse(payload["ok"])
                self.assertIn("not configured", payload["error"])
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_endpoint_validation_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, [_param_block()])
            server, thread, port = self._start_server(out)
            try:
                status, payload = self._post(port, "/spot-extract", {"row_index": 1})
                self.assertEqual(status, 400)
                self.assertFalse(payload["ok"])
                status, payload = self._post(port, "/spot-extract",
                                             {"block_id": "BLK-000098", "row_index": "abc"})
                self.assertEqual(status, 400)
                self.assertFalse(payload["ok"])
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()


if __name__ == "__main__":
    unittest.main()
