"""V3 WS-A A1：整篇地图 doc_map 机制测试。

纪律：单测禁止真实 LLM 调用——所有 LLM 路径经注入 chat 回调或走 stub/unavailable 路由。
验收面：确定性 scaffold（章节骨架/条款→块映射/表格族分布/需求密度热区）、LLM 注释层
封闭校验、幻觉编码硬拦、内容指纹缓存二次调用零 LLM、预算耗尽如实降级 unavailable。
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import doc_map
import llm_client
from llm_budget import LLMBudgetLedger


def _section(section_id: str, block_ids: list[str], text: str, heading: str = "") -> dict:
    return {
        "section_id": section_id,
        "section_path": section_id.split(" / ") if section_id else [],
        "heading": heading or section_id,
        "text": text,
        "block_ids": block_ids,
    }


def _block(block_id: str, text: str, **extra) -> dict:
    row = {
        "block_id": block_id,
        "text": text,
        "order": int(block_id[1:]) if block_id[1:].isdigit() else 0,
        "type": "paragraph",
        "section_path": ["4", "4.1"],
        "requirement_like": False,
        "doc_region": "body",
    }
    row.update(extra)
    return row


def _valid_llm_payload() -> dict:
    return {
        "document_type": "metering profile",
        "domains": [
            {"name": "metrology", "section_ids": ["4.1"], "summary": "电压采集与计量"}
        ],
        "hotspot_rationale": [
            {"chapter": "4", "rationale": "需求密度高，含参数表"}
        ],
        "notes": "整体结构清晰",
    }


class SwitchTests(unittest.TestCase):
    def test_default_off(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RATOMIZER_DOC_MAP", None)
            self.assertFalse(doc_map.doc_map_enabled())
            self.assertFalse(doc_map.doc_map_enabled("0"))

    def test_on(self) -> None:
        self.assertTrue(doc_map.doc_map_enabled("1"))
        self.assertTrue(doc_map.doc_map_enabled("true"))


class ScaffoldTests(unittest.TestCase):
    def _inputs(self):
        sections = [
            _section("4 / 4.1", ["B1", "B2"], "The meter shall collect voltage.", "4.1 Voltage"),
            _section("4 / 4.2", ["B3"], "The meter shall log events.", "4.2 Events"),
        ]
        blocks = [
            _block("B1", "The meter shall collect voltage.", requirement_like=True),
            _block("B2", "The meter shall collect voltage.", requirement_like=True),
            _block("B3", "Intro text."),
            _block("B4", "", type="table", headers=["OBIS", "Description"],
                   data_rows=[["1-1:32.7.0", "Voltage"]]),
        ]
        return sections, blocks

    def test_scaffold_deterministic_and_complete(self) -> None:
        sections, blocks = self._inputs()
        first = doc_map.build_scaffold(sections, blocks)
        second = doc_map.build_scaffold(sections, blocks)
        self.assertEqual(first, second)
        # 章节骨架：两个条款都在
        skeleton_ids = [row["section_id"] for row in first["skeleton"]]
        self.assertEqual(skeleton_ids, ["4 / 4.1", "4 / 4.2"])
        # 条款→块映射逐字节来自输入
        mapping = {row["section_id"]: row["block_ids"] for row in first["clause_block_map"]}
        self.assertEqual(mapping["4 / 4.1"], ["B1", "B2"])
        # 需求密度热区：chapter "4" 有 2 个 requirement_like 块
        hotspots = {row["chapter"]: row for row in first["density_hotspots"]}
        self.assertIn("4", hotspots)
        self.assertEqual(hotspots["4"]["requirement_like_blocks"], 2)
        # 表格族分布：B4 表块被分配到某个族（含 unmatched 也算分布记录）
        table_rows = [row for row in first["table_families"] if row["block_id"] == "B4"]
        self.assertEqual(len(table_rows), 1)
        self.assertTrue(table_rows[0]["family_id"])


class LLMRouteTests(unittest.TestCase):
    def _run(self, tmp: str, chat, **kwargs):
        sections = [
            _section("4 / 4.1", ["B1"], "The meter shall collect voltage at 230 V. OBIS 1-1:32.7.0."),
        ]
        blocks = [_block("B1", "The meter shall collect voltage at 230 V. OBIS 1-1:32.7.0.")]
        return doc_map.run_doc_map(
            tmp, sections=sections, blocks=blocks, chat=chat, route="openai_compatible", **kwargs
        )

    def test_ok_path_writes_doc_map_and_validates_schema(self) -> None:
        with TemporaryDirectory() as tmp:
            result = self._run(tmp, lambda system, user: _valid_llm_payload())
            self.assertEqual(result["status"], "ok")
            artifact = Path(tmp) / doc_map.DOC_MAP_FILENAME
            self.assertTrue(artifact.is_file())
            payload = json.loads(artifact.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], doc_map.DOC_MAP_SCHEMA)
            self.assertEqual(payload["llm_annotations"]["document_type"], "metering profile")
            # 封闭 schema 校验（jsonschema 为运行依赖）
            import jsonschema
            schema = json.loads(
                (Path(doc_map.__file__).parent / "schemas" / "doc_map.schema.json")
                .read_text(encoding="utf-8")
            )
            jsonschema.validate(payload, schema)

    def test_llm_hallucinated_code_hard_blocked(self) -> None:
        def chat(system: str, user: str) -> dict:
            payload = _valid_llm_payload()
            payload["notes"] = "参见 OBIS 0-0:10.0.0 的寄存器定义"  # 来源没有的编码
            return payload

        with TemporaryDirectory() as tmp:
            result = self._run(tmp, chat)
            self.assertEqual(result["status"], "ok")
            artifact = json.loads(
                (Path(tmp) / doc_map.DOC_MAP_FILENAME).read_text(encoding="utf-8")
            )
            annotations = artifact["llm_annotations"]
            self.assertNotIn("0-0:10.0.0", annotations["notes"])
            self.assertTrue(any("0-0:10.0.0" in c for c in annotations["rejected_codes"]))

    def test_invalid_llm_payload_honest_unavailable(self) -> None:
        with TemporaryDirectory() as tmp:
            result = self._run(tmp, lambda system, user: {"unexpected": True})
            self.assertTrue(result["status"].startswith("unavailable:"))
            self.assertFalse((Path(tmp) / doc_map.DOC_MAP_FILENAME).exists())


def _valid_doc_map_payload() -> dict:
    return {
        "schema_version": doc_map.DOC_MAP_SCHEMA,
        "producer": doc_map.DOC_MAP_VERSION,
        "prompt_version": doc_map.DOC_MAP_PROMPT_VERSION,
        "provenance": {},
        "status": "ok",
        "route_requested": "stub",
        "route": "stub",
        "fingerprint": "fp",
        "content_fingerprint": "cfp",
        "clause_count": 0,
        "scaffold": {"skeleton": [], "clause_block_map": [], "table_families": [], "density_hotspots": []},
        "llm_annotations": {
            "document_type": "metering profile",
            "domains": [],
            "hotspot_rationale": [],
            "notes": "",
            "rejected_codes": [],
        },
    }


class RuntimeSchemaValidationTests(unittest.TestCase):
    """A-4：写盘前封闭 schema 运行时校验落地（docstring 不再是空承诺）。"""

    def test_validator_accepts_well_formed_payload(self) -> None:
        # 不抛即通过
        doc_map._validate_payload_schema(
            _valid_doc_map_payload(), "doc_map.schema.json", label="doc_map.json"
        )

    def test_validator_rejects_closed_schema_violation(self) -> None:
        payload = _valid_doc_map_payload()
        payload["unexpected_disallowed_field"] = True  # additionalProperties: false
        with self.assertRaises(ValueError):
            doc_map._validate_payload_schema(
                payload, "doc_map.schema.json", label="doc_map.json"
            )

    def test_result_summary_does_not_write_invalid_payload(self) -> None:
        """写边界校验：畸形产物在落盘前被拦下（fail-loud，不写半成品）。"""
        bad_payload = _valid_doc_map_payload()
        bad_payload["status"] = "something_else"  # status const="ok" 违例
        with TemporaryDirectory() as tmp:
            with patch("input_completeness.attach_input_completeness", lambda p, o: None):
                with self.assertRaises(ValueError):
                    doc_map._result_summary(bad_payload, tmp, route="stub", written=True)
            self.assertFalse((Path(tmp) / doc_map.DOC_MAP_FILENAME).exists())

    def test_stub_route_honest_unavailable(self) -> None:
        with TemporaryDirectory() as tmp:
            result = doc_map.run_doc_map(
                tmp,
                sections=[_section("4 / 4.1", ["B1"], "The meter shall log events.")],
                blocks=[_block("B1", "The meter shall log events.")],
                route="stub",
            )
            self.assertEqual(result["status"], "unavailable:llm_unavailable")
            self.assertEqual(result["route"], "stub")
            self.assertFalse((Path(tmp) / doc_map.DOC_MAP_FILENAME).exists())


class CacheTests(unittest.TestCase):
    def test_second_run_cache_hit_zero_llm(self) -> None:
        calls = {"n": 0}

        def chat(system: str, user: str) -> dict:
            calls["n"] += 1
            return _valid_llm_payload()

        sections = [_section("4 / 4.1", ["B1"], "The meter shall collect voltage.")]
        blocks = [_block("B1", "The meter shall collect voltage.")]
        with TemporaryDirectory() as tmp:
            first = doc_map.run_doc_map(tmp, sections=sections, blocks=blocks, chat=chat)
            self.assertEqual(first["status"], "ok")
            self.assertEqual(calls["n"], 1)
            second = doc_map.run_doc_map(tmp, sections=sections, blocks=blocks, chat=chat)
            self.assertEqual(second["status"], "ok")
            self.assertEqual(calls["n"], 1, "缓存命中不得再发起 LLM 调用")
            self.assertEqual(first["fingerprint"], second["fingerprint"])

    def test_fingerprint_route_dimension(self) -> None:
        sections = [_section("4 / 4.1", ["B1"], "x" * 40)]
        blocks = [_block("B1", "x" * 40)]
        fp_stub = doc_map.doc_map_fingerprint(sections, blocks, route_key="stub")
        fp_llm = doc_map.doc_map_fingerprint(sections, blocks, route_key="llm:model-a")
        self.assertNotEqual(fp_stub, fp_llm)
        # 内容变化 → 指纹失配
        sections2 = [_section("4 / 4.1", ["B1"], "y" * 40)]
        fp_changed = doc_map.doc_map_fingerprint(sections2, blocks, route_key="stub")
        self.assertNotEqual(fp_stub, fp_changed)

    def test_content_change_cache_miss(self) -> None:
        calls = {"n": 0}

        def chat(system: str, user: str) -> dict:
            calls["n"] += 1
            return _valid_llm_payload()

        with TemporaryDirectory() as tmp:
            doc_map.run_doc_map(
                tmp,
                sections=[_section("4 / 4.1", ["B1"], "The meter shall collect voltage.")],
                blocks=[_block("B1", "The meter shall collect voltage.")],
                chat=chat,
            )
            doc_map.run_doc_map(
                tmp,
                sections=[_section("4 / 4.1", ["B1"], "The meter shall log all events.")],
                blocks=[_block("B1", "The meter shall log all events.")],
                chat=chat,
            )
            self.assertEqual(calls["n"], 2, "内容变化必须缓存失配重算")


class BudgetDegradationTests(unittest.TestCase):
    def test_budget_exhausted_honest_unavailable(self) -> None:
        def chat(system: str, user: str) -> dict:
            raise llm_client.LLMBudgetExceeded("structure_hypothesis budget exhausted")

        with TemporaryDirectory() as tmp:
            result = doc_map.run_doc_map(
                tmp,
                sections=[_section("4 / 4.1", ["B1"], "The meter shall log events.")],
                blocks=[_block("B1", "The meter shall log events.")],
                chat=chat,
                route="openai_compatible",
            )
            self.assertEqual(result["status"], "unavailable:budget_exhausted")
            self.assertFalse((Path(tmp) / doc_map.DOC_MAP_FILENAME).exists())

    def test_budget_ledger_stage_and_degraded_marking(self) -> None:
        """挂了真实预算单时：调用在 structure_hypothesis 子预算环节记账；
        耗尽降级时预算单记 mark_degraded（document_needs_work=True）。"""
        ledger = LLMBudgetLedger(
            "doc-test",
            {"default": {"max_calls": 10, "max_tokens": 100000},
             "structure_hypothesis": {"max_calls": 10, "max_tokens": 100000}},
        )
        ledger.attach()
        seen_stage: list[str] = []
        try:
            def chat(system: str, user: str) -> dict:
                seen_stage.append(ledger.current_stage())
                raise llm_client.LLMBudgetExceeded("exhausted")

            with TemporaryDirectory() as tmp:
                result = doc_map.run_doc_map(
                    tmp,
                    sections=[_section("4 / 4.1", ["B1"], "The meter shall log events.")],
                    blocks=[_block("B1", "The meter shall log events.")],
                    chat=chat,
                    route="openai_compatible",
                )
            self.assertEqual(result["status"], "unavailable:budget_exhausted")
            self.assertEqual(seen_stage, ["structure_hypothesis"])
            # mark_degraded 只对核心交付物（functional_extract）强制 document_needs_work；
            # doc_map 是辅助层，如实记 degraded_stages 即可（llm_budget 既有语义，不得夸大）。
            snapshot = ledger.snapshot()
            self.assertIn("structure_hypothesis", snapshot["degraded_stages"])
        finally:
            ledger.detach()


if __name__ == "__main__":
    unittest.main()
