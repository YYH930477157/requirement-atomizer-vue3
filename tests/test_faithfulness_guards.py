"""忠实性守恒 + 定义后筛 + 空话验收扩面回归(0715 抽取质量重构第二刀,通用规则)。

双线内容审计实证:186 条全量审出 29 处误读(情态升格/方向反转/条件绑错/标准号
张冠李戴)——旧护栏只看编码/数字,语义方向全盲;14 条纯术语定义是单一最大噪声源;
10 处空话验收漏网。本套锁确定性可拦的部分。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ai_extract
from extract_guards import (
    _foreign_standard_refs,
    _is_definition_stub,
    _modal_inflation,
    _vague_acceptance,
)


class ModalInflationTests(unittest.TestCase):
    def test_should_upgraded_to_mandatory_flagged(self) -> None:
        req = {"source_quote": "The AFD should be mounted according to the manual.",
               "title": "安装方式", "description": "附加功能设备必须按手册安装。"}
        self.assertTrue(_modal_inflation(req))

    def test_shall_source_not_flagged(self) -> None:
        req = {"source_quote": "The AFD shall be mounted according to the manual.",
               "description": "附加功能设备必须按手册安装。"}
        self.assertFalse(_modal_inflation(req))

    def test_should_kept_advisory_not_flagged(self) -> None:
        req = {"source_quote": "The AFD should be mounted according to the manual.",
               "description": "宜按手册安装附加功能设备。"}
        self.assertFalse(_modal_inflation(req))

    def test_mixed_modal_source_not_flagged(self) -> None:
        # 引句同时含 shall 与 should:强制表述可能对应 shall 部分,不误标
        req = {"source_quote": "The AFD shall close. The display should refresh.",
               "description": "必须关闭阀门。"}
        self.assertFalse(_modal_inflation(req))

    def test_pipeline_appends_suspicion(self) -> None:
        section = {"section_id": "S", "heading": "4.5 AFD1", "block_ids": [],
                   "text": "The AFD should be mounted according to the manual."}

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "安装方式", "description": "附加功能设备必须按手册安装。",
                "source_quote": "The AFD should be mounted according to the manual.",
                "type": "functional", "priority": "P2", "labels": ["机械结构"]}]}

        req = ai_extract.extract_section(section, chat)[0]
        self.assertIn("情态升格待核", req.get("suspicion_reasons") or [])
        self.assertIn("情态升格待核", req["notes"])


class ForeignStandardRefTests(unittest.TestCase):
    BASE = "Conformity shall be declared according to EN 16314 and EN 60529."

    def test_reference_absent_from_section_flagged(self) -> None:
        req = {"title": "符合性声明", "description": "制造商须声明符合 EN 14236 的要求。",
               "source_quote": "Conformity shall be declared."}
        foreign = _foreign_standard_refs(req, self.BASE)
        self.assertEqual([f.replace(" ", "") for f in foreign], ["EN14236"])

    def test_reference_present_in_section_clean(self) -> None:
        req = {"title": "符合性声明", "description": "符合 EN 16314 与 EN 60529 的要求。",
               "source_quote": "Conformity shall be declared."}
        self.assertEqual(_foreign_standard_refs(req, self.BASE), [])

    def test_spacing_variants_normalized(self) -> None:
        req = {"description": "依据 EN16314。", "title": "", "source_quote": ""}
        self.assertEqual(_foreign_standard_refs(req, self.BASE), [])   # EN 16314 同号

    def test_pipeline_appends_suspicion(self) -> None:
        section = {"section_id": "S", "heading": "9.1 General", "block_ids": [],
                   "text": self.BASE}

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "符合性声明", "description": "制造商须声明符合 EN 14236。",
                "source_quote": "Conformity shall be declared.",
                "type": "constraint", "priority": "P1", "labels": ["法规合规"]}]}

        req = ai_extract.extract_section(section, chat)[0]
        self.assertIn("标准号待核", req.get("suspicion_reasons") or [])


class DefinitionStubTests(unittest.TestCase):
    TERMS_SECTION = {"section_id": "3.1 Terms and definitions",
                     "heading": "3.1 Terms and definitions", "block_ids": [],
                     "text": "function process which automatically executes ..."}

    def test_pure_definition_in_terms_section_is_stub(self) -> None:
        req = {"title": "定义功能术语",
               "description": "功能是指自动执行的过程。",
               "source_quote": "function process which automatically executes"}
        self.assertTrue(_is_definition_stub(req, self.TERMS_SECTION))

    def test_definition_with_fixed_values_kept(self) -> None:
        req = {"title": "结算周期取值约束",
               "description": "结算周期有效期只能为 1、2、3、4、6 或 12 个月。",
               "source_quote": "can be valid for 1, 2, 3, 4, 6, 12 months"}
        self.assertFalse(_is_definition_stub(req, self.TERMS_SECTION))

    def test_non_terms_section_never_stub(self) -> None:
        section = {"section_id": "4.5 AFD1", "heading": "4.5 AFD1", "text": "..."}
        req = {"title": "无数字的描述", "description": "设备的一般说明。", "source_quote": "text"}
        self.assertFalse(_is_definition_stub(req, section))

    def test_pipeline_drops_definition_stub(self) -> None:
        def chat(system: str, user: str) -> dict:
            return {"requirements": [
                {"title": "定义功能术语", "description": "功能是指自动执行的过程。",
                 "source_quote": "function process which automatically executes",
                 "type": "business_rule", "priority": "P2", "labels": ["法规合规"]},
                {"title": "结算周期取值约束",
                 "description": "结算周期只能为 1、2、3、4、6 或 12 个月。",
                 "source_quote": "always begins can be valid for 1, 2, 3, 4, 6, 12 months",
                 "type": "business_rule", "priority": "P1", "labels": ["结算"]},
            ]}

        section = dict(self.TERMS_SECTION,
                       text="function process which automatically executes\n"
                            "billing period always begins can be valid for 1, 2, 3, 4, 6, 12 months")
        reqs = ai_extract.extract_section(section, chat, self_check=False)
        titles = [r.get("title") for r in reqs]
        self.assertNotIn("定义功能术语", titles)          # 纯定义被筛
        self.assertIn("结算周期取值约束", titles)          # 带取值规则的保留


class VagueAcceptanceExpansionTests(unittest.TestCase):
    def test_new_phrases_flagged(self) -> None:
        for phrase in ("功能符合规定", "设备无异常", "系统正确运行", "device works as intended"):
            req = {"acceptance_criteria": [phrase]}
            self.assertTrue(_vague_acceptance(req), phrase)

    def test_testable_criteria_still_exempt(self) -> None:
        req = {"acceptance_criteria": ["恢复时间不超过 5 s,运行正常"]}
        self.assertEqual(_vague_acceptance(req), [])


if __name__ == "__main__":
    unittest.main()
