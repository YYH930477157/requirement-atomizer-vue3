"""WS2 功能需求直抽（functional_extract）机制测试。

纪律：单测禁止真实 LLM 调用——所有 LLM 路径经注入 chat 回调或走 stub 路由。
验收面：结构字段冻结、编码漂移硬拦、数字漂移软标、stub provenance 如实、守恒核对
exactly-once + 未闭合阻塞导出、缓存指纹命中放行。
"""
from __future__ import annotations

import json
import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

import functional_extract as fe


def _clause(section_id: str, block_ids: list[str], text: str, heading: str = "H") -> dict:
    return {
        "section_id": section_id,
        "section_path": section_id.split(" / ") if section_id else [],
        "heading": heading,
        "text": text,
        "block_ids": block_ids,
    }


class EntrySwitchTests(unittest.TestCase):
    def test_default_off(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RATOMIZER_FUNCTIONAL_EXTRACT", None)
            self.assertFalse(fe.functional_extract_enabled())
            self.assertFalse(fe.functional_extract_enabled("0"))
            self.assertFalse(fe.functional_extract_enabled("false"))

    def test_on(self) -> None:
        self.assertTrue(fe.functional_extract_enabled("1"))
        self.assertTrue(fe.functional_extract_enabled("true"))


class StubRouteTests(unittest.TestCase):
    def test_stub_route_produces_one_item_per_clause_with_honest_provenance(self) -> None:
        sections = [_clause("4.1", ["B1"], "The meter shall log events.")]
        items, route = fe.extract_functional_requirements(sections, route="stub")
        self.assertEqual(route, "stub")
        self.assertEqual(len(items), 1)
        item = items[0]
        # 结构字段冻结：id/section/block_ids 来自条款，非 LLM
        self.assertEqual(item["source_block_ids"], ["B1"])
        self.assertTrue(item["functional_requirement_id"].startswith("FRE-"))
        self.assertEqual(item["merge_method"], "functional_extract")
        # 叙述字段非空
        self.assertTrue(item["objective"])
        self.assertTrue(item["behaviors"])

    def test_no_sections_returns_empty_stub(self) -> None:
        items, route = fe.extract_functional_requirements([], route="openai_compatible")
        self.assertEqual(items, [])
        self.assertEqual(route, "stub")


class LLMRouteTests(unittest.TestCase):
    def test_injected_chat_items_coerced_structure_frozen(self) -> None:
        sections = [
            _clause("4.2", ["B2"], "The meter shall collect voltage at 230 V. OBIS 1-1:32.7.0."),
        ]

        def chat(system: str, user: str) -> dict:
            return {"items": [{
                "objective": "采集电压",
                "behaviors": ["采集 230 V 电压"],
                "data_constraints": ["230 V"],
                "related_dlms_objects": ["OBIS 1-1:32.7.0"],
                "source_block_ids": ["B2"],
                "source_quote": "The meter shall collect voltage at 230 V.",
            }]}

        items, route = fe.extract_functional_requirements(sections, chat=chat, route="openai_compatible")
        self.assertTrue(route.startswith("injected") or route.startswith("llm:"))
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["source_block_ids"], ["B2"])
        self.assertEqual(item["module"], "4.2")
        # 受保护编码来源里有 → 保留
        self.assertIn("OBIS 1-1:32.7.0", item["related_dlms_objects"])
        self.assertEqual(item["rejected_codes"], [])

    def test_llm_code_drift_hard_blocked(self) -> None:
        # 来源条款没有 OBIS 0-0:10.0.0，LLM 臆造 → 必须硬拦剔除
        sections = [_clause("4.3", ["B3"], "The meter shall log events.")]

        def chat(system: str, user: str) -> dict:
            return {"items": [{
                "objective": "记录 OBIS 0-0:10.0.0 事件",
                "behaviors": ["log"],
                "source_block_ids": ["B3"],
            }]}

        items, _ = fe.extract_functional_requirements(sections, chat=chat, route="openai_compatible")
        self.assertEqual(len(items), 1)
        # 臆造编码被剔除（rejected_codes 非空，related 不含该编码）
        self.assertTrue(any("0-0:10.0.0" in c for c in items[0]["rejected_codes"]))

    def test_llm_numeric_drift_soft_flagged(self) -> None:
        # 来源没有 999，LLM 写 999 → 软标（保留 + flag），不硬拦
        sections = [_clause("4.4", ["B4"], "The meter shall report energy.")]

        def chat(system: str, user: str) -> dict:
            return {"items": [{
                "objective": "上报 999 kWh",
                "behaviors": ["report"],
                "source_block_ids": ["B4"],
            }]}

        items, _ = fe.extract_functional_requirements(sections, chat=chat, route="openai_compatible")
        self.assertTrue(items[0]["numeric_drift_flag"])
        self.assertIn("999", items[0]["numeric_drift_values"])

    def test_llm_failure_falls_back_to_stub_honestly(self) -> None:
        sections = [_clause("4.5", ["B5"], "shall do X.")]

        def chat(system: str, user: str) -> dict:
            raise RuntimeError("endpoint down")

        items, route = fe.extract_functional_requirements(sections, chat=chat, route="openai_compatible")
        # 调用失败 → stub 退化，route 如实 stub
        self.assertEqual(route, "stub")
        self.assertEqual(len(items), 1)

    def test_llm_illegal_payload_falls_back_to_stub(self) -> None:
        sections = [_clause("4.6", ["B6"], "shall do Y.")]
        items, route = fe.extract_functional_requirements(
            sections, chat=lambda s, u: {"not_items": []}, route="openai_compatible",
        )
        self.assertEqual(route, "stub")
        self.assertEqual(len(items), 1)


class ConservationTests(unittest.TestCase):
    def test_exactly_once_closes(self) -> None:
        sections = [_clause("5.1", ["B1", "B2"], "t1"), _clause("5.2", ["B3"], "t2")]
        items = [
            {"source_block_ids": ["B1", "B2"], "source_quote": "t1", "functional_requirement_id": "F1"},
            {"source_block_ids": ["B3"], "source_quote": "t2", "functional_requirement_id": "F2"},
        ]
        report = fe.conservation_report(sections, items)
        self.assertTrue(report["ok"])
        self.assertFalse(report["block_export"])

    def test_missing_clause_blocks_export(self) -> None:
        sections = [_clause("5.1", ["B1"], "t1"), _clause("5.2", ["B2"], "t2")]
        items = [{"source_block_ids": ["B1"], "source_quote": "t1"}]  # B2 未覆盖
        report = fe.conservation_report(sections, items)
        self.assertFalse(report["ok"])
        self.assertTrue(report["block_export"])
        self.assertIn("B2", report["missing_block_ids"])
        # 阻塞导出闸门
        with self.assertRaises(fe.FunctionalConservationError):
            fe.raise_if_unconserved(report)

    def test_duplicate_assignment_blocks(self) -> None:
        sections = [_clause("5.1", ["B1"], "t1")]
        items = [
            {"source_block_ids": ["B1"], "source_quote": "t1"},
            {"source_block_ids": ["B1"], "source_quote": "t1"},  # 重复归属
        ]
        report = fe.conservation_report(sections, items)
        self.assertFalse(report["ok"])
        self.assertIn("B1", report["duplicate_assignments"])

    def test_drilldown_subatoms_must_consume_parent(self) -> None:
        sections = [_clause("6.1", ["B1", "B2"], "t")]
        items = [{
            "source_block_ids": ["B1", "B2"], "source_quote": "t",
            "drilled_subatoms": [
                {"source_block_ids": ["B1"]},  # 缺 B2 → 子原子未完全消费父条款
            ],
        }]
        report = fe.conservation_report(sections, items)
        self.assertFalse(report["ok"])
        self.assertTrue(report["evidence_mismatches"])

    def test_conserved_drilldown_passes(self) -> None:
        sections = [_clause("6.1", ["B1", "B2"], "t")]
        items = [{
            "source_block_ids": ["B1", "B2"], "source_quote": "t",
            "drilled_subatoms": [
                {"source_block_ids": ["B1"]},
                {"source_block_ids": ["B2"]},
            ],
        }]
        report = fe.conservation_report(sections, items)
        self.assertTrue(report["ok"])


class RunAndCacheTests(unittest.TestCase):
    def test_run_writes_governed_artifact_and_conservation(self) -> None:
        with TemporaryDirectory() as tmp:
            sections = [_clause("7.1", ["B1"], "The meter shall log.")]
            result = fe.run_functional_extract(tmp, sections=sections, route="stub")
            self.assertEqual(result["route"], "stub")
            self.assertEqual(result["functional_requirements"], 1)
            self.assertTrue(result["conservation"]["ok"])
            self.assertEqual(result["written"], ["functional_requirements.json"])
            # 产物落盘（governed 路径：package 无 marker → 裸根）
            with open(os.path.join(tmp, "functional_requirements.json"), encoding="utf-8") as f:
                payload = json.load(f)
            self.assertEqual(payload["producer"], fe.FUNCTIONAL_EXTRACT_VERSION)
            self.assertIn("provenance", payload)

    def test_cache_hit_does_not_rewrite_and_preserves_route(self) -> None:
        with TemporaryDirectory() as tmp:
            sections = [_clause("7.2", ["B1"], "shall X.")]
            first = fe.run_functional_extract(tmp, sections=sections, route="stub")
            self.assertEqual(first["written"], ["functional_requirements.json"])
            # 第二次同指纹 → 命中缓存，不再写盘
            second = fe.run_functional_extract(tmp, sections=sections, route="stub")
            self.assertEqual(second["written"], [])
            self.assertEqual(second["functional_requirements"], 1)

    def test_fingerprint_changes_with_clause_text(self) -> None:
        s1 = [_clause("7.3", ["B1"], "alpha")]
        s2 = [_clause("7.3", ["B1"], "beta")]
        self.assertNotEqual(fe.extraction_fingerprint(s1), fe.extraction_fingerprint(s2))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
