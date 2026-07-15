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


class SelfCheckSupplementTests(unittest.TestCase):
    """自检降碎(0715 第三刀):补漏并入已有需求而非新开碎条;护栏不放宽;并入算收敛进度。"""

    SECTION = {"section_id": "4.6", "heading": "4.6 AFD2", "block_ids": [],
               "text": ("The AFD2 shall have no influence on metrology. "
                        "c) a protective seal shall be possible between AFD2 and meter. "
                        "After test the readings shall be identical.")}

    def _existing(self) -> list[dict]:
        return [{"title": "AFD2 要求族", "description": "AFD2 相关要求。",
                 "source_quote": "The AFD2 shall have no influence on metrology.",
                 "sub_items": [{"label": "a", "text": "无计量影响"}],
                 "acceptance_criteria": ["测试后读数一致"], "notes": ""}]

    def test_supplement_merges_into_existing(self) -> None:
        existing = self._existing()

        def chat(system: str, user: str) -> dict:
            return {"requirements": [], "supplements": [{
                "target_title": "AFD2 要求族",
                "sub_items": [{"label": "c", "text": "AFD2 与表计间可加保护铅封"}],
                "acceptance_criteria": ["铅封施加后不影响读数"],
            }]}

        extra, applied = ai_extract.critique_section(self.SECTION, existing, chat)
        self.assertEqual(extra, [])
        self.assertEqual(applied, 1)
        labels = [s["label"] for s in existing[0]["sub_items"]]
        self.assertEqual(labels, ["a", "c"])                     # 并入子项
        self.assertIn("铅封施加后不影响读数", existing[0]["acceptance_criteria"])
        self.assertIn("自检并入", existing[0]["notes"])           # 并入留痕可见

    def test_unmatched_target_dropped(self) -> None:
        existing = self._existing()

        def chat(system: str, user: str) -> dict:
            return {"requirements": [], "supplements": [{
                "target_title": "不存在的需求标题",
                "sub_items": [{"label": "z", "text": "内容"}]}]}

        extra, applied = ai_extract.critique_section(self.SECTION, existing, chat)
        self.assertEqual((extra, applied), ([], 0))
        self.assertEqual(len(existing[0]["sub_items"]), 1)       # 原需求不受污染

    def test_supplement_code_drift_rejected(self) -> None:
        existing = self._existing()

        def chat(system: str, user: str) -> dict:
            return {"requirements": [], "supplements": [{
                "target_title": "AFD2 要求族",
                "sub_items": [{"label": "c", "text": "写入对象 0-0:96.3.10.255"}]}]}

        extra, applied = ai_extract.critique_section(self.SECTION, existing, chat)
        self.assertEqual(applied, 0)                             # 编码漂移 → 整条补充拒绝
        self.assertEqual(len(existing[0]["sub_items"]), 1)

    def test_duplicate_supplement_idempotent(self) -> None:
        existing = self._existing()

        def chat(system: str, user: str) -> dict:
            return {"requirements": [], "supplements": [{
                "target_title": "AFD2 要求族",
                "sub_items": [{"label": "a", "text": "无计量影响"}],
                "acceptance_criteria": ["测试后读数一致"]}]}

        extra, applied = ai_extract.critique_section(self.SECTION, existing, chat)
        self.assertEqual(applied, 0)                             # 全重复 → 无变化不计进度
        self.assertEqual(len(existing[0]["sub_items"]), 1)
        self.assertEqual(len(existing[0]["acceptance_criteria"]), 1)

    def test_faithfulness_note_flags_target(self) -> None:
        existing = self._existing()

        def chat(system: str, user: str) -> dict:
            return {"requirements": [], "supplements": [{
                "target_title": "AFD2 要求族",
                "faithfulness_note": "引句为 should,描述用了必须"}]}

        extra, applied = ai_extract.critique_section(self.SECTION, existing, chat)
        self.assertEqual(applied, 1)
        self.assertIn("自检复核:描述与引句疑似矛盾", existing[0]["suspicion_reasons"])
        self.assertIn("引句为 should", existing[0]["notes"])

    def test_supplement_covering_uncovered_line_converges_without_extra_call(self) -> None:
        """并入的带标签子项直接消掉未覆盖行 → 下一轮覆盖检查免调用收敛(最优路径)。"""
        calls = {"n": 0}
        block_info = {
            "B1": {"block_id": "B1", "requirement_like": True, "noise": False,
                   "text": "c) a protective seal shall be possible between AFD2 and meter."}}
        section = dict(self.SECTION, block_ids=["B1"])

        def chat(system: str, user: str) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                return {"requirements": [{
                    "title": "AFD2 要求族", "description": "AFD2 相关要求。",
                    "type": "functional", "priority": "P1", "labels": ["附加功能"],
                    "source_quote": "The AFD2 shall have no influence on metrology.",
                    "sub_items": [{"label": "a", "text": "无计量影响"}]}]}
            return {"requirements": [], "supplements": [{
                "target_title": "AFD2 要求族",
                "sub_items": [{"label": "c",
                                "text": "a protective seal shall be possible between AFD2 and meter."}]}]}

        results = ai_extract.extract_section(section, chat, self_check=True,
                                             block_info=block_info, self_check_rounds=3)
        self.assertEqual(len(results), 1)                        # 始终一条,没碎
        self.assertEqual([s["label"] for s in results[0]["sub_items"]], ["a", "c"])
        self.assertEqual(calls["n"], 2)                          # 并入后覆盖达成,零额外调用

    def test_supplement_counts_as_convergence_progress(self) -> None:
        """只有并入、无新增的一轮不算收敛终点——覆盖未达成时下一轮继续查。"""
        calls = {"n": 0}
        block_info = {
            "B1": {"block_id": "B1", "requirement_like": True, "noise": False,
                   "text": "The display shall remain readable after the drop test."}}
        section = dict(self.SECTION, block_ids=["B1"],
                       text=self.SECTION["text"] + " The display shall remain readable after the drop test.")

        def chat(system: str, user: str) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                return {"requirements": [{
                    "title": "AFD2 要求族", "description": "AFD2 相关要求。",
                    "type": "functional", "priority": "P1", "labels": ["附加功能"],
                    "source_quote": "The AFD2 shall have no influence on metrology."}]}
            if calls["n"] == 2:      # 第 1 轮:只有并入(短文本,盖不住未覆盖行)→ 算进度
                return {"requirements": [], "supplements": [{
                    "target_title": "AFD2 要求族",
                    "acceptance_criteria": ["跌落后显示可读"]}]}
            return {"requirements": [], "supplements": []}       # 第 2 轮:零进度 → 收敛

        results = ai_extract.extract_section(section, chat, self_check=True,
                                             block_info=block_info, self_check_rounds=3)
        self.assertEqual(len(results), 1)
        self.assertEqual(calls["n"], 3)                          # 并入算进度:又查了一轮才停


if __name__ == "__main__":
    unittest.main()
