from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import ai_extract


class AssembleSectionsTests(unittest.TestCase):
    def test_groups_blocks_by_section_path(self) -> None:
        blocks = [
            {"block_id": "B1", "section_path": ["4 Requirements"], "text": "The meter shall do A."},
            {"block_id": "B2", "section_path": ["4 Requirements"], "text": "It shall also do B."},
            {"block_id": "B3", "section_path": ["5 Security"], "text": "Authentication is required."},
            {"block_id": "B4", "section_path": ["5 Security"], "text": ""},  # 空文本不计内容
        ]
        sections = ai_extract.assemble_sections(blocks)
        self.assertEqual(len(sections), 2)
        s0 = sections[0]
        self.assertEqual(s0["heading"], "4 Requirements")
        self.assertIn("do A", s0["text"])
        self.assertIn("do B", s0["text"])
        self.assertEqual(s0["block_ids"], ["B1", "B2"])

    def test_section_with_only_empty_text_dropped(self) -> None:
        blocks = [{"block_id": "B1", "section_path": ["Empty"], "text": "   "}]
        self.assertEqual(ai_extract.assemble_sections(blocks), [])


class ExtractDriftTests(unittest.TestCase):
    def test_obis_present_in_source_no_drift(self) -> None:
        req = {"description": "实现 OBIS 1-0:1.8.0.255 的有功电能", "source_quote": "active energy 1-0:1.8.0.255"}
        source = "The meter shall expose active energy import at OBIS 1-0:1.8.0.255."
        self.assertEqual(ai_extract.extract_drift(req, source), [])

    def test_fabricated_obis_is_drift(self) -> None:
        req = {"description": "实现 OBIS 0-0:96.99.99.255（原文没有）", "source_quote": ""}
        source = "The meter shall expose active energy import at OBIS 1-0:1.8.0.255."
        drift = ai_extract.extract_drift(req, source)
        self.assertIn("0-0:96.99.99.255", drift)


class ExtractSectionTests(unittest.TestCase):
    def _section(self) -> dict:
        return {"section_id": "5.3 Firmware upgrade", "heading": "5.3 Firmware upgrade",
                "text": "Firmware download shall only be carried out after authentication. "
                        "The new software shall be activated at a fixed date and time.",
                "block_ids": ["B10", "B11"]}

    def test_normalizes_and_keeps_clean_requirement(self) -> None:
        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "Firmware upgrade", "description": "固件升级须先认证再下载，按预定时间激活。",
                "type": "functional", "priority": "P1", "labels": ["升级", "安全"],
                "source_quote": "Firmware download shall only be carried out after authentication.",
                "acceptance_criteria": ["认证通过后才允许下载"]}]}

        reqs = ai_extract.extract_section(self._section(), chat)
        self.assertEqual(len(reqs), 1)
        r = reqs[0]
        self.assertEqual(r["type"], "functional")
        self.assertEqual(r["priority"], "P1")
        self.assertEqual(r["labels"], ["升级", "安全"])
        self.assertEqual(r["extracted_by"], "ai_extract")
        self.assertEqual(r["source_block_ids"], ["B10", "B11"])
        self.assertNotIn("结构漂移", r["notes"])

    def test_fabricated_code_is_flagged_not_dropped(self) -> None:
        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "Bogus", "description": "固件升级走 OBIS 0-0:44.1.0.255（原文并无此码）。",
                "type": "functional", "priority": "P1", "labels": ["升级"], "source_quote": ""}]}

        reqs = ai_extract.extract_section(self._section(), chat)
        self.assertEqual(len(reqs), 1)
        self.assertIn("结构漂移已拦截", reqs[0]["notes"])
        self.assertEqual(reqs[0]["status"], "draft")

    def test_invalid_type_priority_normalized(self) -> None:
        def chat(system: str, user: str) -> dict:
            return {"requirements": [{"title": "X", "description": "desc",
                                       "type": "bogus", "priority": "P9", "source_quote": "desc"}]}

        r = ai_extract.extract_section(self._section(), chat)[0]
        self.assertEqual(r["type"], "functional")
        self.assertEqual(r["priority"], "P2")


class CacheReproducibilityTests(unittest.TestCase):
    def test_rerun_hits_cache_and_is_stable(self) -> None:
        sections = [{"section_id": "S1", "heading": "S1", "text": "The meter shall do A.", "block_ids": ["B1"]}]
        calls = {"n": 0}

        def chat(system: str, user: str) -> dict:
            calls["n"] += 1
            return {"requirements": [{"title": "Do A", "description": "做 A", "type": "functional",
                                       "priority": "P1", "labels": ["计量"], "source_quote": "The meter shall do A."}]}

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "c.jsonl"
            first = ai_extract.extract_all(sections, chat, model="m", cache_path=cache)
            second = ai_extract.extract_all(sections, chat, model="m", cache_path=cache)
            self.assertEqual(calls["n"], 1)  # 第二次命中缓存，未再调 LLM
            self.assertEqual(first, second)   # 同输入同输出（稳定）


class RouteTests(unittest.TestCase):
    def test_stub_route_produces_no_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "blocks.jsonl").write_text(
                '{"block_id":"B1","section_path":["4"],"text":"The meter shall do A."}\n', encoding="utf-8")
            result = ai_extract.run_ai_extract(out, route="stub")
        self.assertEqual(result["route"], "stub")
        self.assertEqual(result["requirements"], 0)
        self.assertGreaterEqual(result["sections"], 1)

    def test_config_for_route_stub_is_none(self) -> None:
        self.assertIsNone(ai_extract.config_for_route("stub"))
        self.assertIsNone(ai_extract.config_for_route(None))


if __name__ == "__main__":
    unittest.main()
