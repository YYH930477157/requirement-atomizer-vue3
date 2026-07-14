"""批次一（0714 整体 review 落地）回归：

- E2 冻结归属注入：富化 prompt 携带上游冻结 ownership,模型只写不判;归属变化令缓存 key 变化。
- E1a 部分降级上屏：enrich_degraded>0 时 note 必须出现（此前只有全灭才提示）。
（S1 合批 / S2 自适应限流 / E1b 遗漏候选 的回归在各自实现后追加于此文件。）
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from requirements_analysis_agent import build_analysis_prompt, slim_vocabulary


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")


class OwnershipInjectionPromptTests(unittest.TestCase):
    def test_prompt_instructs_frozen_ownership(self) -> None:
        prompt = build_analysis_prompt(
            [{"ai_req_id": "AI-1", "module": "时钟", "ownership": "software"}],
            slim_vocabulary({"modules": ["时钟"]}, "时钟"))
        user = prompt["user"]
        self.assertIn("冻结", user)
        self.assertIn("绝不改判", user)
        self.assertIn("给定归属", user)          # ownership_reason 字段说明改为解释给定归属
        self.assertIn('"ownership": "software"', user)   # 冻结值随需求 JSON 注入


class OwnershipInjectionEnrichTests(unittest.TestCase):
    SOURCE = {"ai_req_id": "AI-1", "module": "计量",
              "title": "数据存储",
              "description": "The meter shall store data.",
              "source_quote": "The meter shall store data."}
    VOCAB = {"modules": ["计量"], "submodules_by_module": {"计量": []}}

    def _item(self, ownership: str) -> dict:
        return {"analysis_id": "SRA-001", "ownership": ownership,
                "ownership_reason": "Matched software rule term: store",
                "ownership_source": "rule"}

    def test_prompt_req_carries_frozen_ownership(self) -> None:
        from requirements_analysis import _llm_enrich_item
        captured: list[str] = []

        def chat(system: str, user: str) -> dict:
            captured.append(user)
            return {"items": [{"software_requirement_text": "存储数据的软件逻辑。",
                               "ownership": "software"}]}

        ok, _ = _llm_enrich_item(self._item("software"), self.SOURCE, self.VOCAB,
                                 chat, {}, "m")
        self.assertTrue(ok)
        self.assertIn('"ownership": "software"', captured[0])

    def test_ownership_change_invalidates_cache_key(self) -> None:
        from requirements_analysis import _llm_enrich_item
        calls: list[str] = []
        cache: dict = {}

        def chat(system: str, user: str) -> dict:
            calls.append(user)
            return {"items": [{"software_requirement_text": "存储数据的软件逻辑。"}]}

        _llm_enrich_item(self._item("software"), self.SOURCE, self.VOCAB, chat, cache, "m")
        _llm_enrich_item(self._item("co_design"), self.SOURCE, self.VOCAB, chat, cache, "m")
        self.assertEqual(len(calls), 2)          # 归属不同 → key 不同 → 各自真调
        _llm_enrich_item(self._item("software"), self.SOURCE, self.VOCAB, chat, cache, "m")
        self.assertEqual(len(calls), 2)          # 归属相同 → 命中缓存零调用

    def test_echoed_frozen_ownership_reason_adopted(self) -> None:
        from requirements_analysis import _llm_enrich_item

        def chat(system: str, user: str) -> dict:
            return {"items": [{"software_requirement_text": "存储数据的软件逻辑。",
                               "ownership": "software",
                               "ownership_reason": "存储与协议逻辑属软件职责"}]}

        item = self._item("software")
        ok, _ = _llm_enrich_item(item, self.SOURCE, self.VOCAB, chat, {}, "m")
        self.assertTrue(ok)
        self.assertEqual(item["ownership_reason"], "存储与协议逻辑属软件职责")
        self.assertEqual(item["ownership_reason_source"], "llm")


class PartialDegradeNoteTests(unittest.TestCase):
    def _seed(self, out: Path) -> None:
        _write_jsonl(out / "ai_requirements.jsonl", [
            {"ai_req_id": "AI-1", "title": "数据存储", "module": "数据存储",
             "description": "The meter shall store data.",
             "source_quote": "The meter shall store data."},
            {"ai_req_id": "AI-2", "title": "时钟同步", "module": "时钟",
             "description": "The meter shall sync clock.",
             "source_quote": "The meter shall sync clock."},
        ])

    def test_partial_degrade_sets_note(self) -> None:
        from requirements_analysis import run_requirements_analysis

        def chat(system: str, user: str) -> dict:
            if "store data" in user:
                return {"items": [{"software_requirement_text": "存储数据的软件逻辑。"}]}
            raise RuntimeError("boom")   # 第二条调用失败 → 单条降级

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out)
            result = run_requirements_analysis(out, route="openai_compatible", chat=chat)
            self.assertEqual(result["enriched"], 1)
            self.assertEqual(result["enrich_degraded"], 1)
            self.assertIn("部分降级", result.get("note", ""))
            self.assertIn("1/2", result["note"])

    def test_full_success_has_no_note(self) -> None:
        from requirements_analysis import run_requirements_analysis

        def chat(system: str, user: str) -> dict:
            return {"items": [{"software_requirement_text": "对应软件逻辑成文。"}]}

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self._seed(out)
            result = run_requirements_analysis(out, route="openai_compatible", chat=chat)
            self.assertEqual(result["enrich_degraded"], 0)
            self.assertNotIn("note", result)


if __name__ == "__main__":
    unittest.main()
