"""二遍语义复核回归（0715:v6 审计残余差评全是语义理解错误,确定性护栏无法核验）。

契约:复核绝不新增或自动改写需求正文;发现须双侧逐字锚定(原文侧+产出侧),锚不上整条丢弃;
correction 只作为复核建议留痕;
失败非致命;开关走 env RATOMIZER_AI_VERIFY 且计入缓存指纹上下文。
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

import ai_extract


SECTION = {"section_id": "21", "heading": "4.9.4 Ambient temperature", "block_ids": [],
           "text": ("## 4.9.4 Ambient temperature\n"
                    "For an AFD3 the manufacturer shall specify the ambient temperature range "
                    "with a minimum temperature of at least +5 C to +30 C.")}


def _entry(**kw) -> dict:
    base = {"title": "AFD3环境温度范围要求",
            "description": "制造商声明的工作温度范围的下限不低于+5°C,上限不低于+30°C。",
            "source_section": "4.9.4",
            "source_quote": ("For an AFD3 the manufacturer shall specify the ambient temperature "
                             "range with a minimum temperature of at least +5 C to +30 C."),
            "sub_items": [], "acceptance_criteria": [], "notes": "", "suspicion_reasons": []}
    base.update(kw)
    return base


def _finding(**kw) -> dict:
    base = {"title": "AFD3环境温度范围要求", "kind": "direction",
            "evidence_source": "a minimum temperature of at least +5 C to +30 C",
            "evidence_produced": "下限不低于+5°C"}
    base.update(kw)
    return base


class VerifySectionTests(unittest.TestCase):
    def test_anchored_finding_flagged_with_evidence(self) -> None:
        results = [_entry()]

        def chat(system: str, user: str) -> dict:
            self.assertIn("语义复核员", system)
            self.assertIn("章节原文", user)
            return {"findings": [_finding()]}

        applied = ai_extract._verify_section(SECTION, results, chat)
        self.assertEqual(applied, 1)
        self.assertIn("二遍复核:方向或上下限反转", results[0]["suspicion_reasons"])
        self.assertIn("下限不低于+5°C", results[0]["notes"])

    def test_unanchored_source_evidence_dropped(self) -> None:
        results = [_entry()]

        def chat(system: str, user: str) -> dict:
            return {"findings": [_finding(evidence_source="原文里根本不存在的一句凭空引文内容")]}

        self.assertEqual(ai_extract._verify_section(SECTION, results, chat), 0)
        self.assertEqual(results[0]["suspicion_reasons"], [])

    def test_unanchored_produced_evidence_dropped(self) -> None:
        results = [_entry()]

        def chat(system: str, user: str) -> dict:
            return {"findings": [_finding(evidence_produced="产出里不存在的一段话语内容")]}

        self.assertEqual(ai_extract._verify_section(SECTION, results, chat), 0)

    def test_unknown_title_or_kind_ignored(self) -> None:
        results = [_entry()]

        def chat(system: str, user: str) -> dict:
            return {"findings": [_finding(title="不存在的条目"),
                                 _finding(kind="made_up_kind")]}

        self.assertEqual(ai_extract._verify_section(SECTION, results, chat), 0)

    def test_clean_correction_recorded_without_rewriting_requirement(self) -> None:
        results = [_entry()]

        def chat(system: str, user: str) -> dict:
            return {"findings": [_finding(correction="下限不高于+5°C")]}

        applied = ai_extract._verify_section(SECTION, results, chat)
        self.assertEqual(applied, 1)
        self.assertIn("下限不低于+5°C", results[0]["description"])
        self.assertNotIn("下限不高于+5°C", results[0]["description"])
        self.assertIn("复核建议（未自动改写）：下限不高于+5°C", results[0]["notes"])
        self.assertNotIn("二遍复核改写", results[0]["notes"])

    def test_correction_with_fabricated_number_flag_only(self) -> None:
        results = [_entry()]

        def chat(system: str, user: str) -> dict:
            return {"findings": [_finding(correction="下限不高于+7°C")]}   # 7 无据

        applied = ai_extract._verify_section(SECTION, results, chat)
        self.assertEqual(applied, 1)                                # 标记仍采纳
        self.assertIn("下限不低于+5°C", results[0]["description"])   # 但拒改
        self.assertIn("复核建议（未自动改写）：下限不高于+7°C", results[0]["notes"])
        self.assertNotIn("二遍复核改写", results[0]["notes"])

    def test_correction_not_substring_flag_only(self) -> None:
        results = [_entry()]

        def chat(system: str, user: str) -> dict:
            return {"findings": [_finding(evidence_produced="上限 不低于 +30°C",  # 锚定可过(空白弹性)
                                          correction="上限不低于+30°C即可")]}

        # evidence_produced 内部空白与 description 不符,非精确子串 → 只标不改
        applied = ai_extract._verify_section(SECTION, results, chat)
        self.assertEqual(applied, 1)
        self.assertNotIn("二遍复核改写", results[0]["notes"])

    def test_verify_never_adds_entries(self) -> None:
        results = [_entry()]

        def chat(system: str, user: str) -> dict:
            return {"findings": [], "requirements": [{"title": "偷塞的新需求"}]}

        ai_extract._verify_section(SECTION, results, chat)
        self.assertEqual(len(results), 1)

    def test_duplicate_titles_are_aligned_by_verify_slot(self) -> None:
        results = [
            _entry(title="同名温度要求", description="制造商声明的下限不低于+5°C。"),
            _entry(title="同名温度要求", description="制造商声明的上限不低于+30°C。"),
        ]

        def chat(system: str, user: str) -> dict:
            self.assertIn("verify_slot", system)
            self.assertIn("verify_slot: 1", user)
            return {"findings": [
                _finding(title="同名温度要求", verify_slot=1,
                         evidence_produced="下限不低于+5°C"),
                _finding(title="同名温度要求", verify_slot=2,
                         evidence_produced="上限不低于+30°C"),
            ]}

        self.assertEqual(ai_extract._verify_section(SECTION, results, chat), 2)
        self.assertIn("二遍复核:方向或上下限反转", results[0]["suspicion_reasons"])
        self.assertIn("二遍复核:方向或上下限反转", results[1]["suspicion_reasons"])

    def test_duplicate_title_without_slot_is_ignored(self) -> None:
        results = [
            _entry(title="同名温度要求", description="制造商声明的下限不低于+5°C。"),
            _entry(title="同名温度要求", description="制造商声明的上限不低于+30°C。"),
        ]

        def chat(system: str, user: str) -> dict:
            return {"findings": [_finding(title="同名温度要求",
                                           evidence_produced="上限不低于+30°C")]}

        self.assertEqual(ai_extract._verify_section(SECTION, results, chat), 0)
        self.assertEqual(results[0]["suspicion_reasons"], [])
        self.assertEqual(results[1]["suspicion_reasons"], [])


class FinalizeAndToggleTests(unittest.TestCase):
    def test_extract_section_verify_calls_second_pass(self) -> None:
        calls = []

        def chat(system: str, user: str) -> dict:
            calls.append(system[:12])
            if len(calls) == 1:
                return {"requirements": [{
                    "title": "温度范围", "description": "范围下限不低于+5°C。",
                    "source_quote": SECTION["text"].splitlines()[-1],
                    "type": "functional", "priority": "P1", "labels": []}]}
            return {"findings": []}

        reqs = ai_extract.extract_section(SECTION, chat, self_check=False, verify=True,
                                          verify_rounds=1)
        self.assertEqual(len(calls), 2)          # 抽取 1 + 复核 1(轮数=1 显式)
        self.assertEqual(len(reqs), 1)

    def test_extract_section_verify_off_single_call(self) -> None:
        calls = []

        def chat(system: str, user: str) -> dict:
            calls.append(1)
            return {"requirements": []}

        ai_extract.extract_section(SECTION, chat, self_check=False, verify=False)
        self.assertEqual(len(calls), 1)

    def test_verify_failure_non_fatal(self) -> None:
        def chat(system: str, user: str) -> dict:
            if "语义复核员" in system:
                raise ai_extract.LLMError("verify boom")
            return {"requirements": [{
                "title": "温度范围", "description": "范围覆盖+5到+30°C。",
                "source_quote": SECTION["text"].splitlines()[-1],
                "type": "functional", "priority": "P1", "labels": []}]}

        reqs = ai_extract.extract_section(SECTION, chat, self_check=False, verify=True)
        self.assertEqual(len(reqs), 1)           # 复核崩了,抽取产出保留

    def test_multi_round_union_of_findings(self) -> None:
        # 单轮命中率 ~1/3(实测):多轮并集是机制性提召回。两轮各报不同发现 → 都采纳
        results = [_entry()]
        rounds_seen = []

        def chat(system: str, user: str) -> dict:
            rounds_seen.append(1)
            if len(rounds_seen) == 1:
                return {"findings": []}                       # 第一轮空手
            return {"findings": [_finding()]}                 # 第二轮命中

        applied = ai_extract._verify_section(SECTION, results, chat, rounds=2)
        self.assertEqual(len(rounds_seen), 2)
        self.assertEqual(applied, 1)
        self.assertIn("二遍复核:方向或上下限反转", results[0]["suspicion_reasons"])

    def test_multi_round_dedup_same_kind(self) -> None:
        results = [_entry()]

        def chat(system: str, user: str) -> dict:
            return {"findings": [_finding()]}                 # 每轮都报同一发现

        applied = ai_extract._verify_section(SECTION, results, chat, rounds=3)
        self.assertEqual(applied, 1)                          # (title,kind) 跨轮去重
        self.assertEqual(results[0]["notes"].count("二遍复核（方向或上下限反转）"), 1)

    def test_first_round_failure_does_not_kill_later_rounds(self) -> None:
        results = [_entry()]
        calls = []

        def chat(system: str, user: str) -> dict:
            calls.append(1)
            if len(calls) == 1:
                raise ai_extract.LLMError("round1 boom")
            return {"findings": [_finding()]}

        applied = ai_extract._verify_section(SECTION, results, chat, rounds=2)
        self.assertEqual(applied, 1)                          # 首轮失败,次轮照常

    def test_resolve_verify_rounds(self) -> None:
        with mock.patch.dict(os.environ, {"RATOMIZER_AI_VERIFY_ROUNDS": ""}):
            self.assertEqual(ai_extract.resolve_verify_rounds(), 2)
        with mock.patch.dict(os.environ, {"RATOMIZER_AI_VERIFY_ROUNDS": "9"}):
            self.assertEqual(ai_extract.resolve_verify_rounds(), 4)   # 夹逼上限
        self.assertEqual(ai_extract.resolve_verify_rounds(1), 1)

    def test_resolve_verify_enabled_env(self) -> None:
        with mock.patch.dict(os.environ, {"RATOMIZER_AI_VERIFY": ""}):
            self.assertTrue(ai_extract.resolve_verify_enabled())
        with mock.patch.dict(os.environ, {"RATOMIZER_AI_VERIFY": "0"}):
            self.assertFalse(ai_extract.resolve_verify_enabled())
        with mock.patch.dict(os.environ, {"RATOMIZER_AI_VERIFY": "off"}):
            self.assertFalse(ai_extract.resolve_verify_enabled())
        self.assertTrue(ai_extract.resolve_verify_enabled(True))
        self.assertFalse(ai_extract.resolve_verify_enabled(False))


if __name__ == "__main__":
    unittest.main()
