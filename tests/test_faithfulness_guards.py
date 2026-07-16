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
        # 七刀合同升级:只挂"待核"→确定性软化+留痕(v6 审计 should→必须反复出现,prompt 挡不住)
        self.assertIn("情态已按引句校正", req["notes"])
        self.assertNotIn("必须", req["description"])


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


class SupplementDeliveryGuardTests(unittest.TestCase):
    """并入路径复用交付字段护栏(专家审核 0715:此前只软注 int 漂移——无据数字
    可经自检并入直进 target 验收标准,绕过第一类通道的整移护栏)。"""

    SECTION = {"section_id": "7.4", "heading": "7.4 Battery", "block_ids": [],
               "text": ("## 7.4 Battery\n"
                        "The battery shall support all functions for the declared lifetime. "
                        "The lifetime shall be greater than 5 years.")}

    def _existing(self) -> list[dict]:
        return [{"title": "电池寿命", "description": "电池寿命须大于 5 年。",
                 "source_section": "7.4",
                 "source_quote": "The lifetime shall be greater than 5 years.",
                 "sub_items": [], "acceptance_criteria": [], "notes": ""}]

    def test_fabricated_number_in_supplement_acceptance_blocked(self) -> None:
        existing = self._existing()

        def chat(system: str, user: str) -> dict:
            return {"requirements": [], "supplements": [{
                "target_title": "电池寿命",
                "acceptance_criteria": ["电池容量不低于 3600 mAh 方可判定合格",   # 3600 无据
                                        "按声明的温度曲线测试后寿命大于 5 年"]}]}   # 5 有据

        extra, applied = ai_extract.critique_section(self.SECTION, existing, chat)
        acc = existing[0]["acceptance_criteria"]
        self.assertNotIn("电池容量不低于 3600 mAh 方可判定合格", acc)   # 无据行被拦
        self.assertIn("按声明的温度曲线测试后寿命大于 5 年", acc)        # 有据行照并
        self.assertIn("3600", existing[0]["notes"])                     # 审计留痕
        self.assertIn("无依据数字", existing[0]["notes"])

    def test_supplement_with_only_clean_lines_merges_without_guard_note(self) -> None:
        existing = self._existing()

        def chat(system: str, user: str) -> dict:
            return {"requirements": [], "supplements": [{
                "target_title": "电池寿命",
                "acceptance_criteria": ["按声明的温度曲线测试后寿命大于 5 年"]}]}

        extra, applied = ai_extract.critique_section(self.SECTION, existing, chat)
        self.assertEqual(applied, 1)
        self.assertNotIn("交付护栏筛除", existing[0]["notes"])


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


class AnnexScopeTests(unittest.TestCase):
    """资料性附录区段(v5 审计最大病灶:informative 对照表升格成 9 条强制需求)。
    状态机跨单元携带——续表单元无标记,标记在上一单元。"""

    def _sections(self) -> list[dict]:
        return [
            {"section_id": "A", "heading": "10 Env",
             "text": "Annex A (informative)\nGuidance text.\nAnnex B (informative)\nTable rows 1-2."},
            {"section_id": "B", "heading": "10 Env",
             "text": "Table rows 3-6 continued here.\nAnnex C (normative)\nC.1 The device shall X."},
        ]

    def test_scopes_carry_across_units(self) -> None:
        secs = self._sections()
        ai_extract._annotate_annex_scopes(secs)
        self.assertEqual(secs[0]["informative_ranges"], [(0, len(secs[0]["text"]))])
        (s, e), = secs[1]["informative_ranges"]
        self.assertEqual(s, 0)
        self.assertLess(e, len(secs[1]["text"]))
        self.assertIn("Table rows 3-6", secs[1]["text"][s:e])
        self.assertNotIn("shall X", secs[1]["text"][s:e])

    def test_mention_in_prose_does_not_transition(self) -> None:
        secs = [{"section_id": "5", "heading": "5 Security",
                 "text": "A typical routine is given in Annex A.\nThe device shall log events."}]
        ai_extract._annotate_annex_scopes(secs)
        self.assertEqual(secs[0]["informative_ranges"], [])

    def test_informative_entry_demoted_and_flagged(self) -> None:
        secs = self._sections()
        ai_extract._annotate_annex_scopes(secs)

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "续表功能项", "description": "设备须支持续表所列功能配置能力。",
                "source_quote": "Table rows 3-6 continued here.",
                "type": "functional", "priority": "P1", "labels": []}]}

        req = ai_extract.extract_section(secs[1], chat, self_check=False)[0]
        self.assertEqual(req["priority"], "P2")
        self.assertIn("资料性附录来源", req.get("suspicion_reasons") or [])

    def test_normative_entry_untouched(self) -> None:
        secs = self._sections()
        ai_extract._annotate_annex_scopes(secs)

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "设备行为X", "description": "设备必须执行 X 行为并可验证。",
                "source_quote": "C.1 The device shall X.",
                "type": "functional", "priority": "P1", "labels": []}]}

        req = ai_extract.extract_section(secs[1], chat, self_check=False)[0]
        self.assertEqual(req["priority"], "P1")
        self.assertNotIn("资料性附录来源", req.get("suspicion_reasons") or [])


class SourceSectionCorrectionTests(unittest.TestCase):
    """溯源节号确定性回填(v5 审计:一个单元 5 条全被标成邻近章节号,quote 却逐字正确)。"""

    SECTION = {"section_id": "7.6", "heading": "7.6 Input to AFD", "block_ids": [],
               "text": ("## 7.6 Input to AFD\n## 7.6.1 General\nIntro words here.\n"
                        "## 7.6.2 Requirement\nThe input shall be volume pulses or data streams.")}

    def _extract(self, source_section: str) -> dict:
        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "输入形式", "description": "输入须为体积脉冲或数据流。",
                "source_section": source_section,
                "source_quote": "The input shall be volume pulses or data streams.",
                "type": "functional", "priority": "P1", "labels": []}]}
        return ai_extract.extract_section(self.SECTION, chat, self_check=False)[0]

    def test_wrong_clause_number_corrected(self) -> None:
        req = self._extract("7.4 Metrological influence")
        self.assertTrue(req["source_section"].startswith("7.6.2"))
        self.assertIn("溯源节号按原文校正", req["notes"])

    def test_prefix_relation_left_alone(self) -> None:
        req = self._extract("7.6 Input to AFD")   # 粗粒度前缀:不动
        self.assertEqual(req["source_section"], "7.6 Input to AFD")


class MetaDiscourseTests(unittest.TestCase):
    """自检元话语剥除(v5 审计:自检旁白整段泄漏进交付正文,6+ 处)。"""

    def test_strip_meta_sentences_keeps_normal_text(self) -> None:
        text = ("表计须耐受 200 mT 永久磁场。本条已抽需求聚焦永久磁场,4.12.1 可作为背景或扩展。"
                "当前条款为概括性要求,故不单独成需求。制造商声明的功能必须保持可操作。")
        out = ai_extract._strip_meta_text(text)
        self.assertIn("200 mT", out)
        self.assertIn("保持可操作", out)
        self.assertNotIn("已抽需求", out)
        self.assertNotIn("不单独成需求", out)

    def test_domain_words_not_stripped(self) -> None:
        text = "表计应支持自检功能并在检测到泄漏时报警。测试已覆盖全部流量点。"
        self.assertEqual(ai_extract._strip_meta_text(text), text)

    def test_supplement_meta_append_filtered(self) -> None:
        section = {"section_id": "4", "heading": "4.12 EMC", "block_ids": [],
                   "text": "The meter shall withstand a magnetic field of 200 mT."}
        existing = [{"title": "磁场耐受", "description": "表计须耐受 200 mT 磁场。",
                     "source_section": "4.12", "source_quote": "withstand a magnetic field of 200 mT",
                     "sub_items": [], "acceptance_criteria": [], "notes": ""}]

        def chat(system: str, user: str) -> dict:
            return {"requirements": [], "supplements": [{
                "target_title": "磁场耐受",
                "description_append": "本条已抽需求聚焦磁场,故不单独成需求。"}]}

        extra, applied = ai_extract.critique_section(section, existing, chat)
        self.assertEqual((extra, applied), ([], 0))          # 纯元话语 append 被剥空,不并入
        self.assertNotIn("不单独成需求", existing[0]["description"])


class NearDupUpgradeTests(unittest.TestCase):
    """去重加固校准(v5 实测:互含拦不住换词复述;纯相似度阈值会误杀 1型/2型 两档判据)。"""

    def test_paraphrase_with_same_numbers_is_dup(self) -> None:
        a = "根据制造商声明,使用声明的温度曲线和所有频率输入的最大值进行测试,确认电池寿命支持所有功能"
        b = "根据制造商声明,使用其声明的温度曲线和所有频率输入的最大值进行测试,确认可更换电池支持所有功能的寿命"
        self.assertTrue(ai_extract._near_dup(a, [b]))

    def test_different_type_values_not_dup(self) -> None:
        a = "对于1型阀门,在20 mbar、75 mbar及150 mbar测试压力下的最大泄漏率均不超限"
        b = "对于2型阀门,在20 mbar、75 mbar及150 mbar测试压力下的最大泄漏率均不超限"
        self.assertFalse(ai_extract._near_dup(a, [b]))


class ThresholdTableConsistencyTests(unittest.TestCase):
    """表文一致性(v5 差评:表写对 Type 1=1 l/h,正文写成 5 l/h,因"有表豁免"漏标)。"""

    TT = {"columns": ["阀门类型", "20 mbar 最大泄漏率 (l/h)", "75 mbar 最大泄漏率 (l/h)"],
          "rows": [["Type 1", "1", "1"], ["Type 2", "5", "5"]]}

    def test_mismatched_value_flagged(self) -> None:
        from extract_guards import _threshold_desc_mismatch
        req = {"description": "对于1型阀门,在20 mbar测试压力下最大泄漏率为5 l/h。",
               "acceptance_criteria": [], "threshold_table": self.TT}
        self.assertTrue(_threshold_desc_mismatch(req))

    def test_consistent_value_clean(self) -> None:
        from extract_guards import _threshold_desc_mismatch
        req = {"description": "对于1型阀门,在20 mbar测试压力下最大泄漏率为1 l/h。",
               "acceptance_criteria": [], "threshold_table": self.TT}
        self.assertEqual(_threshold_desc_mismatch(req), [])

    def test_no_numbers_no_flag(self) -> None:
        from extract_guards import _threshold_desc_mismatch
        req = {"description": "对于1型阀门,泄漏限值见阈值表。",
               "acceptance_criteria": [], "threshold_table": self.TT}
        self.assertEqual(_threshold_desc_mismatch(req), [])


class AnchorQualityTests(unittest.TestCase):
    """溯源锚点质量门(v6 回归教训:正文编号行被 PDF 标成标题块,"## 3 % by gaseous
    volume…"当成"第 3 章"覆盖了正确的 D.3.3)。"""

    def test_bare_integer_heading_not_used_as_override(self) -> None:
        section = {"section_id": "D", "heading": "Annex D", "block_ids": [],
                   "text": ("## 3 % by gaseous volume of a toluene mixture for 42 days\n"
                            "After the exposure the valve shall pass the leakage test.")}

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "暴露后泄漏测试", "description": "化学暴露后阀门必须通过泄漏测试。",
                "source_section": "D.3.3 Test 2",
                "source_quote": "After the exposure the valve shall pass the leakage test.",
                "type": "functional", "priority": "P1", "labels": []}]}

        req = ai_extract.extract_section(section, chat, self_check=False)[0]
        self.assertEqual(req["source_section"], "D.3.3 Test 2")   # 裸整数锚点不覆盖
        self.assertNotIn("溯源节号按原文校正", req["notes"])

    def test_letter_clause_heading_supported(self) -> None:
        section = {"section_id": "D", "heading": "Annex D", "block_ids": [],
                   "text": ("## D.3.3 Test 2\n"
                            "After the exposure the valve shall pass the leakage test.")}

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "暴露后泄漏测试", "description": "化学暴露后阀门必须通过泄漏测试。",
                "source_section": "7.4 Metrological influence",
                "source_quote": "After the exposure the valve shall pass the leakage test.",
                "type": "functional", "priority": "P1", "labels": []}]}

        req = ai_extract.extract_section(section, chat, self_check=False)[0]
        self.assertTrue(req["source_section"].startswith("D.3.3"))

    def test_letter_clause_claim_kept_under_same_annex(self) -> None:
        # claimed=D.3.3(细) vs derived=Annex D(粗):同附录,保留更细的 claimed
        self.assertEqual(ai_extract._sec_anchor_key("D.3.3 Test 2"), ("clause", "D.3.3"))
        self.assertEqual(ai_extract._sec_anchor_key("Annex D (normative)"), ("annex", "D"))


class ModalSofteningTests(unittest.TestCase):
    """情态升格确定性软化(v6 差评 u36:should→必须,prompt 约束挡不住)。"""

    def test_should_quote_softens_produced_must(self) -> None:
        section = {"section_id": "7", "heading": "7.13 Firmware", "block_ids": [],
                   "text": "Special consideration should be made for the control of the valve."}

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "固件升级阀门控制考虑", "description": "固件升级过程必须对阀门控制给予特殊考虑。",
                "source_quote": "Special consideration should be made for the control of the valve.",
                "type": "constraint", "priority": "P1", "labels": []}]}

        req = ai_extract.extract_section(section, chat, self_check=False)[0]
        self.assertNotIn("必须", req["description"])
        self.assertIn("宜", req["description"])
        self.assertIn("情态已按引句校正", req["notes"])

    def test_shall_quote_untouched(self) -> None:
        section = {"section_id": "7", "heading": "7.13 Valve", "block_ids": [],
                   "text": "The valve shall close within 5 s."}

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "阀门关闭时限", "description": "阀门必须在 5 s 内关闭。",
                "source_quote": "The valve shall close within 5 s.",
                "type": "functional", "priority": "P0", "labels": []}]}

        req = ai_extract.extract_section(section, chat, self_check=False)[0]
        self.assertIn("必须", req["description"])   # shall 引句:强制措辞合法,不动


class DesignatorExemptionTests(unittest.TestCase):
    """型号指代符豁免(v6 实测:验收因枚举 RS232 被"无依据数字"整行误杀清空)。"""

    def test_rs232_in_acceptance_not_moved(self) -> None:
        section = {"section_id": "5", "heading": "5.2 Sealing", "block_ids": [],
                   "text": "All ports shall be protected by a physical seal."}

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "端口封印保护", "description": "所有端口必须有物理封印保护。",
                "source_quote": "All ports shall be protected by a physical seal.",
                "acceptance_criteria": ["检查 USB、RS232、JTAG 等全部物理接口均被封印覆盖"],
                "type": "functional", "priority": "P1", "labels": []}]}

        req = ai_extract.extract_section(section, chat, self_check=False)[0]
        self.assertEqual(len(req["acceptance_criteria"]), 1)
        self.assertIn("RS232", req["acceptance_criteria"][0])

    def test_fabricated_value_still_moved(self) -> None:
        section = {"section_id": "5", "heading": "5.2 Sealing", "block_ids": [],
                   "text": "All ports shall be protected by a physical seal."}

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "端口封印保护", "description": "所有端口必须有物理封印保护。",
                "source_quote": "All ports shall be protected by a physical seal.",
                "acceptance_criteria": ["封印耐受 500 N 拉力不脱落"],   # 500 N 无据
                "type": "functional", "priority": "P1", "labels": []}]}

        req = ai_extract.extract_section(section, chat, self_check=False)[0]
        self.assertEqual(req["acceptance_criteria"], [])   # 编造数值仍整移
        self.assertIn("500", req["notes"])


class MetaDiscourseBroadeningTests(unittest.TestCase):
    """元话语词表扩充(v6 泄漏实句:整合进/整合至/需求应明确/描述已覆盖…无补充)。"""

    def test_v6_leak_sentences_stripped(self) -> None:
        for leak in ("需将表3中的具体测试条件与性能准则整合进该需求的描述和验收中。",
                     "子项b的适用范围条件需整合至需求描述中。",
                     "需求应明确累计器的功能逻辑必须考虑预测的能量使用。",
                     "描述已覆盖要求，无补充。"):
            out = ai_extract._strip_meta_text("表计须在 5 s 内关阀。" + leak)
            self.assertEqual(out, "表计须在 5 s 内关阀。", leak)


class MoveExemptionTests(unittest.TestCase):
    """整移判定剥引用编号(v5 审计:验收行带 EN 标准号示例被整行误移,核心阈值一起丢)。"""

    def test_standard_ref_in_acceptance_not_moved(self) -> None:
        section = {"section_id": "4", "heading": "4.12 ESD", "block_ids": [],
                   "text": "The error shall not exceed 1/3 MPE during the discharge test."}

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "静电放电误差限值", "description": "放电试验中误差不得超过 1/3 MPE。",
                "source_quote": "The error shall not exceed 1/3 MPE during the discharge test.",
                "acceptance_criteria": ["放电试验后误差不超过 1/3 MPE（对应仪表标准如 EN 12405 的方法）"],
                "type": "functional", "priority": "P1", "labels": []}]}

        req = ai_extract.extract_section(section, chat, self_check=False)[0]
        self.assertEqual(len(req["acceptance_criteria"]), 1)   # 标准号是地址不是数值,不整移
        self.assertIn("1/3 MPE", req["acceptance_criteria"][0])


if __name__ == "__main__":
    unittest.main()
