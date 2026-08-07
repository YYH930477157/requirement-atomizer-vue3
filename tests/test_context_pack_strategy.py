"""V3 WS-A A2：functional_extract 上下文包策略（按条款自然边界）测试。

纪律：单测禁止真实 LLM 调用——LLM 路径经注入 chat 回调。
验收面：新策略下条款不被截断（旧 4000 字符切片只留在 legacy）；同族相邻条款整文进包；
包大小上限受控且目标条款永不被丢/截；doc_map 热区摘要注入；默认 legacy 行为逐字节不变
（含缓存指纹）；部分包 LLM 失败按条款诚实 stub 退化且路由标 mixed。
"""
from __future__ import annotations

import json
import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

import functional_extract as fe


def _clause(section_id: str, block_ids: list[str], text: str, heading: str = "") -> dict:
    return {
        "section_id": section_id,
        "section_path": section_id.split(" / ") if section_id else [],
        "heading": heading or section_id,
        "text": text,
        "block_ids": block_ids,
    }


LONG_TEXT = "The meter shall record the voltage profile. " * 160  # ~7200 字符 > 4000 切片


class StrategySwitchTests(unittest.TestCase):
    def test_default_legacy(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RATOMIZER_CONTEXT_PACK_STRATEGY", None)
            self.assertEqual(fe.context_pack_strategy(), "legacy")

    def test_clause_family_opt_in(self) -> None:
        self.assertEqual(fe.context_pack_strategy("clause_family"), "clause_family")
        # 未知值回退 legacy（不误启新行为）
        self.assertEqual(fe.context_pack_strategy("something-else"), "legacy")

    def test_max_chars_config(self) -> None:
        self.assertEqual(fe.context_pack_max_chars("12000"), 12000)
        self.assertGreater(fe.context_pack_max_chars("bogus"), 0)


class LegacyUnchangedTests(unittest.TestCase):
    def test_legacy_prompt_still_slices(self) -> None:
        """默认旧逻辑：长条款仍按遗留 4000 字符切片（行为面不动）。"""
        sections = [_clause("4 / 4.1", ["B1"], LONG_TEXT)]
        prompt = fe._build_user_prompt(sections)
        payload = json.loads(prompt)
        self.assertEqual(len(payload["clauses"][0]["text"]), 4000)

    def test_legacy_fingerprint_unchanged_by_strategy_feature(self) -> None:
        """legacy 策略下缓存指纹与特性引入前逐字节一致（strategy 维度不进键）。"""
        sections = [_clause("4 / 4.1", ["B1"], "The meter shall log events.")]
        before = fe.extraction_fingerprint(sections, route_key="stub")
        after = fe.extraction_fingerprint(sections, route_key="stub", context_strategy="legacy")
        self.assertEqual(before, after)

    def test_strategy_changes_fingerprint(self) -> None:
        sections = [_clause("4 / 4.1", ["B1"], "The meter shall log events.")]
        legacy = fe.extraction_fingerprint(sections, route_key="stub")
        packed = fe.extraction_fingerprint(
            sections, route_key="stub", context_strategy="clause_family"
        )
        self.assertNotEqual(legacy, packed)


class ContextPackageTests(unittest.TestCase):
    def test_target_clause_never_truncated(self) -> None:
        """新策略核心验收：条款按自然边界整文进包，不再被 4000 字符切片截断。"""
        target = _clause("4 / 4.6", ["B10"], LONG_TEXT, "4.6 Profile")
        packages = fe.build_context_packages([target], max_chars=24000)
        self.assertEqual(len(packages), 1)
        prompt = fe._build_package_prompt(packages[0])
        self.assertIn(LONG_TEXT, prompt, "目标条款必须整文进入 prompt，不得截断")

    def test_same_family_neighbors_whole_and_cross_family_excluded(self) -> None:
        req = _clause("4 / 4.6 / 4.6.1", ["B1"], "The meter shall store profiles.", "4.6.1 Requirements")
        test = _clause("4 / 4.6 / 4.6.2", ["B2"], "The test shall verify storage.", "4.6.2 Test")
        other = _clause("5 / 5.1", ["B3"], "Unrelated communication clause.", "5.1 Comm")
        packages = fe.build_context_packages([req, test, other], max_chars=24000)
        by_target = {p["target"]["heading"]: p for p in packages}
        # 4.6.1 的包：同族 4.6.2 整文进 neighbors；5.1 不进
        neighbor_heads = [n["heading"] for n in by_target["4.6.1 Requirements"]["neighbors"]]
        self.assertEqual(neighbor_heads, ["4.6.2 Test"])
        prompt = fe._build_package_prompt(by_target["4.6.1 Requirements"])
        self.assertIn("The test shall verify storage.", prompt)
        self.assertNotIn("Unrelated communication clause.", prompt)

    def test_package_cap_drops_neighbors_not_target(self) -> None:
        big_target = _clause("4 / 4.6", ["B1"], "T" * 9000, "4.6 Main")
        neighbor = _clause("4 / 4.6 / 4.6.1", ["B2"], "N" * 9000, "4.6.1 Sub")
        packages = fe.build_context_packages([big_target, neighbor], max_chars=10000)
        for package in packages:
            if package["target"]["heading"] == "4.6 Main":
                # 目标 9000 + 邻居 9000 超 10000 上限 → 邻居被舍弃，目标整文保留
                self.assertEqual(package["neighbors"], [])
                self.assertIn("T" * 9000, fe._build_package_prompt(package))

    def test_oversized_single_clause_stays_whole(self) -> None:
        """单条款自身超上限也不截断（条款是自然原子，上限只约束拼包）。"""
        huge = _clause("4 / 4.9", ["B9"], "H" * 30000, "4.9 Huge")
        packages = fe.build_context_packages([huge], max_chars=10000)
        self.assertIn("H" * 30000, fe._build_package_prompt(packages[0]))

    def test_doc_map_summary_injected_when_available(self) -> None:
        target = _clause("4 / 4.6", ["B1"], "The meter shall store profiles.", "4.6 Profile")
        fake_map = {
            "status": "ok",
            "scaffold": {
                "density_hotspots": [
                    {"chapter": "4", "requirement_like_blocks": 9, "total_blocks": 10, "density": 0.9}
                ],
            },
            "llm_annotations": {
                "document_type": "metering profile",
                "domains": [{"name": "metrology", "section_ids": ["4 / 4.6"], "summary": "计量域"}],
                "hotspot_rationale": [{"chapter": "4", "rationale": "密度高"}],
            },
        }
        packages = fe.build_context_packages([target], doc_map=fake_map)
        prompt = fe._build_package_prompt(packages[0])
        self.assertIn("密度高", prompt)
        self.assertIn("计量域", prompt)


class PackagedExtractionTests(unittest.TestCase):
    def _sections(self):
        return [
            _clause("4 / 4.6 / 4.6.1", ["B1"], "The meter shall store load profiles.", "4.6.1 Requirements"),
            _clause("4 / 4.6 / 4.6.2", ["B2"], "The test shall verify profile storage.", "4.6.2 Test"),
        ]

    def test_per_package_calls_and_attribution(self) -> None:
        seen_prompts: list[str] = []

        def chat(system: str, user: str) -> dict:
            seen_prompts.append(user)
            if "store load profiles" in user.split("[CONTEXT]")[0]:
                return {"items": [{
                    "objective": "存储负荷曲线",
                    "behaviors": ["按周期存储曲线"],
                    "source_block_ids": ["B1"],
                    "source_quote": "The meter shall store load profiles.",
                }]}
            return {"items": [{
                "objective": "验证曲线存储",
                "behaviors": ["执行存储验证"],
                "source_block_ids": ["B2"],
                "source_quote": "The test shall verify profile storage.",
            }]}

        items, route = fe.extract_functional_requirements(
            self._sections(), chat=chat, strategy="clause_family",
        )
        self.assertEqual(len(seen_prompts), 2, "每个条款包一次调用")
        self.assertTrue(route.startswith("injected"))
        self.assertEqual(len(items), 2)
        by_blocks = {tuple(i["source_block_ids"]): i for i in items}
        self.assertIn(("B1",), by_blocks)
        self.assertIn(("B2",), by_blocks)
        # 守恒：恰好消费条款集合
        report = fe.conservation_report(self._sections(), items)
        self.assertTrue(report["ok"])

    def test_partial_llm_failure_honest_mixed_route(self) -> None:
        def chat(system: str, user: str) -> dict:
            if "store load profiles" in user.split("[CONTEXT]")[0]:
                return {"items": [{
                    "objective": "存储负荷曲线",
                    "behaviors": ["按周期存储曲线"],
                    "source_block_ids": ["B1"],
                }]}
            return {"garbage": True}  # 第二包返回非法 → 该条款诚实 stub

        items, route = fe.extract_functional_requirements(
            self._sections(), chat=chat, strategy="clause_family",
        )
        self.assertEqual(route, "mixed", "部分包退化不得夸大为纯 LLM 路由")
        self.assertEqual(len(items), 2)

    def test_run_functional_extract_strategy_via_env(self) -> None:
        with TemporaryDirectory() as tmp:
            sections = self._sections()
            calls = {"n": 0}

            def chat(system: str, user: str) -> dict:
                calls["n"] += 1
                marker = "B1" if "store load profiles" in user.split("[CONTEXT]")[0] else "B2"
                return {"items": [{
                    "objective": f"目标{marker}",
                    "behaviors": ["行为"],
                    "source_block_ids": [marker],
                }]}

            with patch.dict(os.environ, {"RATOMIZER_CONTEXT_PACK_STRATEGY": "clause_family"}):
                result = fe.run_functional_extract(tmp, sections=sections, chat=chat)
            self.assertEqual(calls["n"], 2)
            self.assertEqual(result["functional_requirements"], 2)
            self.assertEqual(result["conservation"]["ok"] if isinstance(result["conservation"], dict) else None, True)


if __name__ == "__main__":
    unittest.main()
