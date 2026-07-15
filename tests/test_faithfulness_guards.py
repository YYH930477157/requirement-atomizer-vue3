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
        req = {"source_quote": "The module should be mounted according to the manual.",
               "title": "安装方式", "description": "设备模块必须按手册安装。"}
        self.assertTrue(_modal_inflation(req))

    def test_shall_source_not_flagged(self) -> None:
        req = {"source_quote": "The module shall be mounted according to the manual.",
               "description": "设备模块必须按手册安装。"}
        self.assertFalse(_modal_inflation(req))

    def test_should_kept_advisory_not_flagged(self) -> None:
        req = {"source_quote": "The module should be mounted according to the manual.",
               "description": "宜按手册安装设备模块。"}
        self.assertFalse(_modal_inflation(req))

    def test_mixed_modal_source_not_flagged(self) -> None:
        # 引句同时含 shall 与 should:强制表述可能对应 shall 部分,不误标
        req = {"source_quote": "The unit shall close the valve. The display should refresh.",
               "description": "必须关闭阀门。"}
        self.assertFalse(_modal_inflation(req))

    def test_pipeline_appends_suspicion(self) -> None:
        section = {"section_id": "S", "heading": "4.5 Module A", "block_ids": [],
                   "text": "The module should be mounted according to the manual."}

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "安装方式", "description": "设备模块必须按手册安装。",
                "source_quote": "The module should be mounted according to the manual.",
                "type": "functional", "priority": "P2", "labels": ["机械结构"]}]}

        req = ai_extract.extract_section(section, chat)[0]
        self.assertIn("情态升格待核", req.get("suspicion_reasons") or [])
        self.assertIn("情态升格待核", req["notes"])


class ForeignStandardRefTests(unittest.TestCase):
    BASE = "Conformity shall be declared according to EN 54321 and EN 60529."

    def test_reference_absent_from_section_flagged(self) -> None:
        req = {"title": "符合性声明", "description": "制造商须声明符合 EN 99999 的要求。",
               "source_quote": "Conformity shall be declared."}
        foreign = _foreign_standard_refs(req, self.BASE)
        self.assertEqual([f.replace(" ", "") for f in foreign], ["EN99999"])

    def test_reference_present_in_section_clean(self) -> None:
        req = {"title": "符合性声明", "description": "符合 EN 54321 与 EN 60529 的要求。",
               "source_quote": "Conformity shall be declared."}
        self.assertEqual(_foreign_standard_refs(req, self.BASE), [])

    def test_spacing_variants_normalized(self) -> None:
        req = {"description": "依据 EN54321。", "title": "", "source_quote": ""}
        self.assertEqual(_foreign_standard_refs(req, self.BASE), [])   # EN 54321 同号

    def test_pipeline_appends_suspicion(self) -> None:
        section = {"section_id": "S", "heading": "9.1 General", "block_ids": [],
                   "text": self.BASE}

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "符合性声明", "description": "制造商须声明符合 EN 99999。",
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
        section = {"section_id": "4.5 Module A", "heading": "4.5 Module A", "text": "..."}
        req = {"title": "无数字的描述", "description": "设备的一般说明。", "source_quote": "text"}
        self.assertFalse(_is_definition_stub(req, section))

    def test_bare_digits_do_not_rescue_definition(self) -> None:
        # v4 实测:术语章条目靠型号枚举/条款号里的裸数字混过桩判定——数字必须带
        # 单位或比较语境才算约束证据
        req = {"title": "定义设备类型",
               "description": "标准定义了三种设备类型:XDEV1 为出厂集成,XDEV2 为直接附着,XDEV3 为现场连接。",
               "source_quote": "3.1.4 additional device Type 1 factory fitted"}
        self.assertTrue(_is_definition_stub(req, self.TERMS_SECTION))

    def test_digits_with_unit_kept(self) -> None:
        req = {"title": "标称流量定义",
               "description": "标称流量为 1,6 m3/h 的固定取值。",
               "source_quote": "nominal flow equal to 1,6 m3/h"}
        self.assertFalse(_is_definition_stub(req, self.TERMS_SECTION))

    def test_digits_with_comparator_kept(self) -> None:
        req = {"title": "分级阈值定义",
               "description": "该等级要求参数 ≥3 档配置。",
               "source_quote": "class with parameter ≥3 levels"}
        self.assertFalse(_is_definition_stub(req, self.TERMS_SECTION))

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

    SECTION = {"section_id": "4.6", "heading": "4.6 Module B", "block_ids": [],
               "text": ("The device module shall have no influence on measurement. "
                        "c) a protective seal shall be possible between the module and the unit. "
                        "After test the readings shall be identical.")}

    def _existing(self) -> list[dict]:
        return [{"title": "设备模块要求族", "description": "设备模块相关要求。",
                 "source_quote": "The device module shall have no influence on measurement.",
                 "sub_items": [{"label": "a", "text": "无计量影响"}],
                 "acceptance_criteria": ["测试后读数一致"], "notes": ""}]

    def test_supplement_merges_into_existing(self) -> None:
        existing = self._existing()

        def chat(system: str, user: str) -> dict:
            return {"requirements": [], "supplements": [{
                "target_title": "设备模块要求族",
                "sub_items": [{"label": "c", "text": "模块与主机间可加保护铅封"}],
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
                "target_title": "设备模块要求族",
                "sub_items": [{"label": "c", "text": "写入对象 0-0:96.3.10.255"}]}]}

        extra, applied = ai_extract.critique_section(self.SECTION, existing, chat)
        self.assertEqual(applied, 0)                             # 编码漂移 → 整条补充拒绝
        self.assertEqual(len(existing[0]["sub_items"]), 1)

    def test_duplicate_supplement_idempotent(self) -> None:
        existing = self._existing()

        def chat(system: str, user: str) -> dict:
            return {"requirements": [], "supplements": [{
                "target_title": "设备模块要求族",
                "sub_items": [{"label": "a", "text": "无计量影响"}],
                "acceptance_criteria": ["测试后读数一致"]}]}

        extra, applied = ai_extract.critique_section(self.SECTION, existing, chat)
        self.assertEqual(applied, 0)                             # 全重复 → 无变化不计进度
        self.assertEqual(len(existing[0]["sub_items"]), 1)
        self.assertEqual(len(existing[0]["acceptance_criteria"]), 1)

    def test_faithfulness_note_flags_target(self) -> None:
        # 契约升级(v2 审计:空泛复核 5 处全误报):note 必须含可在原文/引句锚定的片段
        existing = self._existing()

        def chat(system: str, user: str) -> dict:
            return {"requirements": [], "supplements": [{
                "target_title": "设备模块要求族",
                "faithfulness_note": '引句为 "shall have no influence on measurement" 而描述反向表述'}]}

        extra, applied = ai_extract.critique_section(self.SECTION, existing, chat)
        self.assertEqual(applied, 1)
        self.assertIn("自检复核:描述与引句疑似矛盾", existing[0]["suspicion_reasons"])
        self.assertIn("自检复核", existing[0]["notes"])

    def test_supplement_covering_uncovered_line_converges_without_extra_call(self) -> None:
        """并入的带标签子项直接消掉未覆盖行 → 下一轮覆盖检查免调用收敛(最优路径)。"""
        calls = {"n": 0}
        block_info = {
            "B1": {"block_id": "B1", "requirement_like": True, "noise": False,
                   "text": "c) a protective seal shall be possible between the module and the unit."}}
        section = dict(self.SECTION, block_ids=["B1"])

        def chat(system: str, user: str) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                return {"requirements": [{
                    "title": "设备模块要求族", "description": "设备模块相关要求。",
                    "type": "functional", "priority": "P1", "labels": ["附加功能"],
                    "source_quote": "The device module shall have no influence on measurement.",
                    "sub_items": [{"label": "a", "text": "无计量影响"}]}]}
            return {"requirements": [], "supplements": [{
                "target_title": "设备模块要求族",
                "sub_items": [{"label": "c",
                                "text": "a protective seal shall be possible between the module and the unit."}]}]}

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
                    "title": "设备模块要求族", "description": "设备模块相关要求。",
                    "type": "functional", "priority": "P1", "labels": ["附加功能"],
                    "source_quote": "The device module shall have no influence on measurement."}]}
            if calls["n"] == 2:      # 第 1 轮:只有并入(短文本,盖不住未覆盖行)→ 算进度
                return {"requirements": [], "supplements": [{
                    "target_title": "设备模块要求族",
                    "acceptance_criteria": ["跌落后显示可读"]}]}
            return {"requirements": [], "supplements": []}       # 第 2 轮:零进度 → 收敛

        results = ai_extract.extract_section(section, chat, self_check=True,
                                             block_info=block_info, self_check_rounds=3)
        self.assertEqual(len(results), 1)
        self.assertEqual(calls["n"], 3)                          # 并入算进度:又查了一轮才停


class SpelledNumberBaselineTests(unittest.TestCase):
    """0715 v2 审计:原文 "three times" → 正文 "3 倍" 被当无据数字剥掉验收——误伤修复。"""

    def test_spelled_numbers_join_baseline(self) -> None:
        from extract_guards import source_int_baseline
        ints = source_int_baseline("the error shall not exceed three times the MPE, one third applies")
        self.assertIn("3", ints)
        self.assertIn("1", ints)

    def test_acceptance_with_spelled_source_number_not_stripped(self) -> None:
        source = "When tested, the error shall not exceed three times the maximum permissible error."
        req = {"title": "误差限值", "description": "误差不得超过最大允许误差的 3 倍。",
               "source_quote": source,
               "acceptance_criteria": ["测试后误差 ≤ 3 倍最大允许误差"], "dev_guidance": []}
        removed_ints, _codes = ai_extract._move_unsupported_delivery_items(req, source)
        self.assertEqual(removed_ints, set())
        self.assertEqual(req["acceptance_criteria"], ["测试后误差 ≤ 3 倍最大允许误差"])   # 有据验收保留

    def test_int_drift_respects_spelled_numbers(self) -> None:
        req = {"title": "", "description": "重复 3 次测试。", "source_quote": ""}
        self.assertEqual(ai_extract.int_drift(req, "repeat the test three times"), [])


class ThousandSeparatorBaselineTests(unittest.TestCase):
    """0715 v2 审计:原文 "3,200 cycles"/"1 008 h" 千分位写法被拆碎,有据验收被剥空。"""

    def test_grouped_numbers_join_baseline(self) -> None:
        from extract_guards import source_int_baseline
        ints = source_int_baseline("endurance of 3,200 cycles and 1 008 h exposure")
        self.assertIn("3200", ints)
        self.assertIn("1008", ints)

    def test_acceptance_with_grouped_source_number_kept(self) -> None:
        source = "The valve shall withstand 3,200 operating cycles."
        req = {"title": "耐久", "description": "阀门须承受 3200 次操作循环。",
               "source_quote": source,
               "acceptance_criteria": ["完成 3200 次循环后阀门功能正常,泄漏达标"],
               "dev_guidance": []}
        removed_ints, _ = ai_extract._move_unsupported_delivery_items(req, source)
        self.assertEqual(removed_ints, set())
        self.assertEqual(len(req["acceptance_criteria"]), 1)     # 有据验收不被剥

    def test_produced_grouped_form_also_normalized(self) -> None:
        req = {"title": "", "description": "承受 3,200 次循环。", "source_quote": ""}
        self.assertEqual(ai_extract.int_drift(req, "withstand 3200 cycles"), [])


class InformativeSourceFlagTests(unittest.TestCase):
    """0715 v2 审计:informative 附录内容被升格为 P0/P1 强制需求(9 处)——软标待核。"""

    def _extract(self, priority: str, heading: str = "Annex B (informative) Functions") -> dict:
        section = {"section_id": heading, "heading": heading, "block_ids": [],
                   "text": "Peak consumption recording may be provided."}

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "峰值用量记录", "description": "记录峰值用量。",
                "source_quote": "Peak consumption recording may be provided.",
                "type": "functional", "priority": priority, "labels": ["数据存储"]}]}

        return ai_extract.extract_section(section, chat)[0]

    def test_informative_annex_p1_flagged(self) -> None:
        req = self._extract("P1")
        self.assertIn("资料性来源待核", req.get("suspicion_reasons") or [])

    def test_informative_annex_p2_clean(self) -> None:
        req = self._extract("P2")
        self.assertNotIn("资料性来源待核", req.get("suspicion_reasons") or [])

    def test_normative_section_not_flagged(self) -> None:
        req = self._extract("P1", heading="7.8 Data storage")
        self.assertNotIn("资料性来源待核", req.get("suspicion_reasons") or [])


class StandardRefRootTests(unittest.TestCase):
    def test_prefix_variants_not_flagged(self) -> None:
        # "ISO 6270" vs 基线 "EN ISO 6270-1":同一主号,机构前缀写法差异不定罪
        req = {"title": "", "description": "依据 ISO 6270 进行冷凝试验。", "source_quote": ""}
        self.assertEqual(_foreign_standard_refs(req, "tested per EN ISO 6270-1 procedures"), [])

    def test_truly_foreign_root_still_flagged(self) -> None:
        req = {"title": "", "description": "依据 EN 99999。", "source_quote": ""}
        foreign = _foreign_standard_refs(req, "tested per EN ISO 6270-1")
        self.assertEqual(len(foreign), 1)


class SupplementHardeningTests(unittest.TestCase):
    """0715 v2 审计的并入副作用修复:同标签复读/同义堆叠/跨条款越界/空泛复核。"""

    SECTION = {"section_id": "7", "heading": "7 Functions",
               "text": ("## 7.4 Metrological influence\n"
                        "7.4 The module shall not influence measurement.\n"
                        "## 7.6 Input to module\n"
                        "7.6 The input shall accept pulse signals from the unit.")}

    def _existing(self) -> list[dict]:
        return [{"title": "计量无影响", "description": "模块不得影响计量。",
                 "source_section": "7.4",
                 "source_quote": "The module shall not influence measurement.",
                 "sub_items": [{"label": "a", "text": "运行中不影响计量精度"}],
                 "acceptance_criteria": ["测试前后计量误差一致"], "notes": ""}]

    def test_same_label_resend_skipped(self) -> None:
        existing = self._existing()

        def chat(system: str, user: str) -> dict:
            return {"requirements": [], "supplements": [{
                "target_title": "计量无影响",
                "sub_items": [{"label": "a", "text": "换一种说法的同一子项内容表述"}]}]}

        _extra, applied = ai_extract.critique_section(self.SECTION, existing, chat)
        self.assertEqual(applied, 0)
        self.assertEqual(len(existing[0]["sub_items"]), 1)       # 同标签复读不并

    def test_near_duplicate_acceptance_skipped(self) -> None:
        existing = self._existing()

        def chat(system: str, user: str) -> dict:
            return {"requirements": [], "supplements": [{
                "target_title": "计量无影响",
                "acceptance_criteria": ["测试前后计量误差一致（复述）"]}]}

        _extra, applied = ai_extract.critique_section(self.SECTION, existing, chat)
        self.assertEqual(applied, 0)                             # 互含近重复不并
        self.assertEqual(len(existing[0]["acceptance_criteria"]), 1)

    def test_cross_clause_supplement_dropped(self) -> None:
        existing = self._existing()   # target 属 7.4

        def chat(system: str, user: str) -> dict:
            return {"requirements": [], "supplements": [{
                "target_title": "计量无影响",
                "sub_items": [{"label": "b",
                                "text": "The input shall accept pulse signals from the unit."}]}]}

        _extra, applied = ai_extract.critique_section(self.SECTION, existing, chat)
        self.assertEqual(applied, 0)                             # 7.6 的义务不并进 7.4
        self.assertEqual(len(existing[0]["sub_items"]), 1)

    def test_unanchored_faithfulness_note_not_flagged(self) -> None:
        existing = self._existing()

        def chat(system: str, user: str) -> dict:
            return {"requirements": [], "supplements": [{
                "target_title": "计量无影响",
                "faithfulness_note": "感觉描述可能有点问题需要人再看看确认一下"}]}

        _extra, applied = ai_extract.critique_section(self.SECTION, existing, chat)
        self.assertEqual(applied, 0)                             # 空泛怀疑不挂标记
        self.assertNotIn("自检复核:描述与引句疑似矛盾",
                         existing[0].get("suspicion_reasons") or [])

    def test_anchored_faithfulness_note_still_flags(self) -> None:
        existing = self._existing()

        def chat(system: str, user: str) -> dict:
            return {"requirements": [], "supplements": [{
                "target_title": "计量无影响",
                "faithfulness_note": '引句为 "shall not influence measurement" 而描述写成了允许影响'}]}

        _extra, applied = ai_extract.critique_section(self.SECTION, existing, chat)
        self.assertEqual(applied, 1)
        self.assertIn("自检复核:描述与引句疑似矛盾", existing[0]["suspicion_reasons"])


class SupplementConversionTests(unittest.TestCase):
    """v3 召回修正(五刀):未匹配的补充若能在原文逐字定位 → 转独立需求(同护栏同去重),
    不再直接丢弃——自检契约偏并入曾把真新需求塞错目标而流失(v3 漏抽 4→8 的根因)。"""

    SECTION = {"section_id": "7", "heading": "7 Functions",
               "text": ("## 7.4 Metrological influence\n"
                        "7.4 The module shall not influence measurement.\n"
                        "## 7.9 Display readability\n"
                        "The display shall remain readable without tools at arm distance.")}

    def _existing(self) -> list[dict]:
        return [{"title": "计量无影响", "description": "模块不得影响计量。",
                 "source_section": "7.4",
                 "source_quote": "The module shall not influence measurement.",
                 "sub_items": [], "acceptance_criteria": [], "notes": ""}]

    def test_unmatched_supplement_with_locatable_text_converted(self) -> None:
        existing = self._existing()

        def chat(system: str, user: str) -> dict:
            return {"requirements": [], "supplements": [{
                "target_title": "显示可读性",     # 不存在的目标
                "description_append": "显示应在臂距内免工具清晰可读。",
                "sub_items": [{"label": "",
                                "text": "The display shall remain readable without tools at arm distance."}]}]}

        extra, _applied = ai_extract.critique_section(self.SECTION, existing, chat)
        self.assertEqual(len(extra), 1)                          # 转成独立需求,不丢
        self.assertEqual(extra[0]["title"], "显示可读性")
        self.assertIn("readable without tools", extra[0]["source_quote"])   # 逐字引句已定位
        self.assertIn("自检补充转独立（原目标未匹配,请核归属）",
                      extra[0]["suspicion_reasons"])             # 可见可核

    def test_unlocatable_unmatched_supplement_still_dropped(self) -> None:
        existing = self._existing()

        def chat(system: str, user: str) -> dict:
            return {"requirements": [], "supplements": [{
                "target_title": "不存在的目标",
                "description_append": "一段原文里根本找不到对应的凭空内容描述。"}]}

        extra, applied = ai_extract.critique_section(self.SECTION, existing, chat)
        self.assertEqual((extra, applied), ([], 0))              # 定位不到→仍丢弃(宁缺勿错)


class ValuePairingRiskTests(unittest.TestCase):
    """五刀:调包类误读(两个数字都在原文,漂移拦不住)——多档同单位软标路由注意力。"""

    SOURCE = ("For Type 1 at 75 mbar the leakage shall not exceed 1 l/h. "
              "For Type 2 at 20 mbar the leakage shall not exceed 5 l/h.")

    def test_multi_value_same_unit_flagged(self) -> None:
        from extract_guards import _multi_value_pairing_risk
        req = {"title": "泄漏限值", "description": "Type 1 泄漏不超过 5 l/h,Type 2 不超过 1 l/h。",
               "source_quote": self.SOURCE}
        self.assertIn("l/h", _multi_value_pairing_risk(req, self.SOURCE))

    def test_threshold_table_exempt(self) -> None:
        from extract_guards import _multi_value_pairing_risk
        req = {"title": "泄漏限值", "description": "限值见参数表。", "source_quote": self.SOURCE,
               "threshold_table": {"columns": ["型号", "限值"], "rows": [["Type 1", "1 l/h"], ["Type 2", "5 l/h"]]}}
        self.assertEqual(_multi_value_pairing_risk(req, self.SOURCE), [])

    def test_single_value_not_flagged(self) -> None:
        from extract_guards import _multi_value_pairing_risk
        req = {"title": "泄漏限值", "description": "泄漏不超过 1 l/h。",
               "source_quote": "the leakage shall not exceed 1 l/h"}
        self.assertEqual(_multi_value_pairing_risk(req, "the leakage shall not exceed 1 l/h"), [])

    def test_pipeline_appends_suspicion(self) -> None:
        section = {"section_id": "S", "heading": "7.13 Valve", "block_ids": [], "text": self.SOURCE}

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "泄漏限值", "description": "Type 1 不超过 1 l/h,Type 2 不超过 5 l/h。",
                "source_quote": self.SOURCE,
                "type": "functional", "priority": "P1", "labels": ["阀门控制"]}]}

        req = ai_extract.extract_section(section, chat)[0]
        self.assertIn("数值配对待核", req.get("suspicion_reasons") or [])


class GuardVersionCacheTests(unittest.TestCase):
    """缓存指纹必须随护栏版本变化——缓存存终处理结果,指纹不含护栏版本时
    护栏升级被旧缓存整体绕过(v5 实测 wall=0s 新护栏零生效)。"""

    def test_fingerprint_sensitive_to_guards_version(self) -> None:
        from unittest import mock
        section = {"text": "some section text"}
        fp1 = ai_extract.section_fingerprint(section, "model-x")
        with mock.patch.object(ai_extract, "EXTRACT_GUARDS_VERSION", "guards-vNEXT"):
            fp2 = ai_extract.section_fingerprint(section, "model-x")
        self.assertNotEqual(fp1, fp2)


class FoldTestSiblingTests(unittest.TestCase):
    """条款族=一条需求的确定性兜底:`X.Y.2 Test` 独立条并回 Requirement 条验收。
    (v4 实测 3 处拆条,prompt 约束挡不住采样方差 → 结构判据零词面兜底)"""

    def _req(self, sec: str, title: str, **kw) -> dict:
        base = {"title": title, "description": f"{title}的内容。", "source_section": sec,
                "source_quote": "quote", "sub_items": [], "acceptance_criteria": [], "notes": ""}
        base.update(kw)
        return base

    def test_test_entry_folds_into_requirement_sibling(self) -> None:
        reqs = [self._req("7.13.4.6.1 Requirement", "阀门开启要求",
                          acceptance_criteria=["入口压力下应能开启。"]),
                self._req("7.13.4.6.2 Test", "阀门开启测试程序",
                          acceptance_criteria=["按规定压力测试三次。", "全部循环均应开启。"])]
        out = ai_extract._fold_test_siblings(reqs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "阀门开启要求")
        self.assertIn("按规定压力测试三次。", out[0]["acceptance_criteria"])
        self.assertIn("同族 Test 条款已并入验收：7.13.4.6.2", out[0]["notes"])

    def test_test_entry_folds_into_parent_when_no_sibling(self) -> None:
        reqs = [self._req("7.13.4.5 Valve closing", "阀门关闭泄漏限值",
                          acceptance_criteria=["泄漏不超过限值。"]),
                self._req("7.13.4.5.2 Test", "泄漏测试",
                          acceptance_criteria=["按测试程序执行。"])]
        out = ai_extract._fold_test_siblings(reqs)
        self.assertEqual(len(out), 1)
        self.assertIn("按测试程序执行。", out[0]["acceptance_criteria"])

    def test_ambiguous_siblings_resolved_by_requirement_tail(self) -> None:
        # 多兄弟平票:恰有一个纯"Requirement"尾 → 折进它(X.Y.1 Requirement + X.Y.2 Test 惯例)
        reqs = [self._req("4.6.1 Requirement", "要求甲"),
                self._req("4.6.3 Marking", "标识乙"),
                self._req("4.6.2 Test", "测试丙", acceptance_criteria=["测试步骤。"])]
        out = ai_extract._fold_test_siblings(reqs)
        self.assertEqual(len(out), 2)
        self.assertIn("测试步骤。", out[0]["acceptance_criteria"])

    def test_ambiguous_siblings_without_requirement_tail_left_alone(self) -> None:
        reqs = [self._req("4.6.1 Design", "设计甲"),
                self._req("4.6.3 Marking", "标识乙"),
                self._req("4.6.2 Test", "测试丙")]
        out = ai_extract._fold_test_siblings(reqs)
        self.assertEqual(len(out), 3)   # 无"Requirement"尾可裁 → 歧义,宁缺勿错不折

    def test_entity_named_test_section_not_folded(self) -> None:
        reqs = [self._req("7.9.1 Requirement", "接口要求"),
                self._req("7.9.2 Test interface", "测试接口功能")]   # 实体名非纯测试尾
        out = ai_extract._fold_test_siblings(reqs)
        self.assertEqual(len(out), 2)

    def test_suspicions_and_threshold_table_carried(self) -> None:
        tt = {"columns": ["项", "值"], "rows": [["压力", "75 mbar"]]}
        reqs = [self._req("5.2.1 Requirement", "要求"),
                self._req("5.2.2 Test", "测试", threshold_table=tt,
                          suspicion_reasons=["数值配对待核"])]
        out = ai_extract._fold_test_siblings(reqs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["threshold_table"], tt)
        self.assertIn("数值配对待核", out[0]["suspicion_reasons"])


if __name__ == "__main__":
    unittest.main()
