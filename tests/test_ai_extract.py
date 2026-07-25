from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ai_extract


class TocAndReferenceNoiseTests(unittest.TestCase):
    """test7 实测的两类噪声：目录点线行被当需求抽出（16 条堆一个锚点、与正文成对重复）；
    纯标准引用/范围声明混进交付物（用户裁定当前阶段忽略）。"""

    def test_toc_dot_leader_lines_stripped_from_sections(self) -> None:
        blocks = [
            {"block_id": "B1", "section_path": [], "text":
                "Foreword ........................................ 5\n"
                "4.15 Resistance to storage temperature ......... 23\n"
                "4.16 Ageing test ................................ 24"},
            {"block_id": "B2", "section_path": ["4.15"], "text": "The meter shall resist storage temperature."},
        ]
        sections = ai_extract.assemble_sections(blocks)
        # 纯目录块清空后不成节；正文照常
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["section_id"], "4.15")
        self.assertNotIn("....", sections[0]["text"])

    def test_mixed_block_keeps_prose_drops_toc_lines(self) -> None:
        block = {"text": "Real requirement text here.\n7.9 Time interval accuracy .......... 31"}
        cleaned = ai_extract.clean_block_text(block)
        self.assertEqual(cleaned, "Real requirement text here.")

    def test_citation_only_and_scope_requirements_dropped(self) -> None:
        section = {"section_id": "1", "heading": "1 Scope", "block_ids": ["B1"],
                   "text": "EN 16314:2013 (E)\nThis European Standard specifies additional requirements. "
                           "The meter shall log events."}

        def chat(system: str, user: str) -> dict:
            return {"requirements": [
                {"title": "符合EN 16314:2013标准", "description": "符合标准",
                 "type": "functional", "priority": "P1", "labels": ["测试合规"],
                 "source_quote": "EN 16314:2013 (E)"},                             # 纯引用 → 剔
                {"title": "标准适用范围", "description": "本标准适用于……",
                 "type": "functional", "priority": "P2", "labels": ["其它"],
                 "source_quote": "This European Standard specifies additional requirements."},  # 范围声明 → 剔
                {"title": "事件记录", "description": "电表须记录事件。",
                 "type": "functional", "priority": "P1", "labels": ["事件记录"],
                 "source_quote": "The meter shall log events."},                   # 真需求 → 留
            ]}

        reqs = ai_extract.extract_section(section, chat)
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0]["title"], "事件记录")

    def test_behavior_mentioning_standard_is_kept(self) -> None:
        """提及标准号但带设备行为的不受影响（"按 EN 1359 方法测试后应…"是真需求）。"""
        req = {"source_quote": "After the test according to EN 1359 the meter shall remain within limits.",
               "description": "按 EN 1359 测试后仍须在限值内。"}
        self.assertFalse(ai_extract._is_reference_stub(req))


class ClauseFamilyGroupingTests(unittest.TestCase):
    """真实反馈"分段乱乱的"：4.6 是一个需求整体（4.6.1 要求 + 4.6.2 测试，a↔a 对应）——
    切分须跟条款结构走：同族同单元、异族绝不合并；无编号沿用旧贪心（散文/乱码文档兼容）。"""

    def _sec(self, heading: str, text: str) -> dict:
        return {"section_id": heading, "heading": heading, "text": text, "block_ids": [heading]}

    def test_requirements_and_test_subclauses_stay_together(self) -> None:
        # 两节各 ~120 字，target=150 时纯贪心会拆开（120+120>150）；
        # 条款族上限放宽到 2×target=300 → 保持同单元
        sections = [
            self._sec("4.6.1 Requirements", "a) The XDEV shall have no influence." * 3),
            self._sec("4.6.2 Test", "a) Fit the XDEV and undertake tests." * 3),
        ]
        units = ai_extract.merge_sections(sections, target_chars=150)
        self.assertEqual(len(units), 1)                                # 同族合一
        self.assertIn("4.6.1", units[0]["text"])
        self.assertIn("4.6.2", units[0]["text"])

    def test_complete_families_may_share_unit_but_never_split(self) -> None:
        # 0715 目录子树打包:意图升级——旧规则"异族不拼"针对的是族中间切一刀;
        # 新规则:**完整**小族可同箱(整子树优先,省调用),族本体绝不被切开
        sections = [self._sec("4.5 XDEV1", "short a."), self._sec("4.6 XDEV2", "short b.")]
        units = ai_extract.merge_sections(sections, target_chars=2800)
        self.assertEqual(len(units), 1)                                # 完整小族同箱
        big = [self._sec("4.5 XDEV1", "a" * 3000), self._sec("4.6 XDEV2", "b" * 3000)]
        units = ai_extract.merge_sections(big, target_chars=2800)     # 6000 > 2×2800
        self.assertEqual(len(units), 2)                                # 装不下则各自成箱,不腰斩

    def test_numberless_sections_use_legacy_greedy_merge(self) -> None:
        sections = [self._sec("Alpha", "x" * 40), self._sec("Beta", "y" * 40)]
        units = ai_extract.merge_sections(sections, target_chars=2800)
        self.assertEqual(len(units), 1)                                # 无编号沿用贪心

    def test_oversize_family_splits_at_member_boundary(self) -> None:
        sections = [
            self._sec("7.13.1 Req", "r" * 300),
            self._sec("7.13.2 Test", "t" * 300),
        ]
        units = ai_extract.merge_sections(sections, target_chars=200)  # 族上限 400 < 600
        self.assertEqual(len(units), 2)                                # 在成员边界拆，不腰斩
        self.assertTrue(units[0]["text"].startswith("## 7.13.1"))
        self.assertTrue(units[1]["text"].startswith("## 7.13.2"))

    def test_sub_items_normalized(self) -> None:
        sec = {"section_id": "4.6", "heading": "4.6", "text": "t", "block_ids": []}
        r = ai_extract.normalize_requirement(
            {"title": "X", "description": "d", "source_quote": "t",
             "sub_items": [{"label": "a", "text": "子项甲"}, {"label": "b", "text": "  "},
                            "garbage", {"text": "无标签也保留"}]}, sec)
        self.assertEqual(r["sub_items"], [{"label": "a", "text": "子项甲"},
                                          {"label": "", "text": "无标签也保留"}])


class VagueAcceptanceTests(unittest.TestCase):
    """模糊验收检测（BMAD Done-ness clarity）：空话验收标"验收不可测"，有判据则豁免。"""

    def _extract(self, acceptance: list[str]) -> dict:
        section = {"section_id": "S", "heading": "S", "block_ids": [],
                   "text": "The meter shall record events."}

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "事件记录", "description": "d", "type": "functional",
                "priority": "P1", "labels": ["事件记录"],
                "source_quote": "The meter shall record events.",
                "acceptance_criteria": acceptance}]}

        return ai_extract.extract_section(section, chat)[0]

    def test_vague_phrase_without_criteria_flagged(self) -> None:
        req = self._extract(["事件记录功能符合要求", "断电后恢复正常工作"])
        self.assertIn("验收不可测", req.get("suspicion_reasons") or [])
        self.assertIn("验收不可测", req["notes"])

    def test_numeric_or_comparison_criteria_exempt(self) -> None:
        req = self._extract(["连续记录 100 条事件后最早记录仍可读出",
                             "恢复时间不超过 5 s，工作正常"])
        self.assertNotIn("验收不可测", req.get("suspicion_reasons") or [])

    def test_clean_acceptance_not_flagged(self) -> None:
        req = self._extract(["断电事件出现在事件日志中且带时间戳"])
        self.assertNotIn("验收不可测", req.get("suspicion_reasons") or [])


class ChapterUnitModeTests(unittest.TestCase):
    """整章阅读模式（架构 A/B）：按顶层章号分组，同章条款全同单元；默认 clause 行为不变。"""

    def _sec(self, heading: str, text: str) -> dict:
        return {"section_id": heading, "heading": heading, "text": text, "block_ids": [heading]}

    def test_chapter_mode_groups_whole_chapter(self) -> None:
        sections = [
            self._sec("4.6.1 Requirements", "a) req." * 40),
            self._sec("4.6.2 Test", "a) test." * 40),
            self._sec("4.14.1 Requirement", "The XDEV shall withstand." * 20),
            self._sec("5.1 Marking", "Marking text." * 10),
        ]
        units = ai_extract.merge_sections(sections, unit_mode="chapter")
        self.assertEqual(len(units), 2)                          # 第4章合一、第5章独立
        self.assertIn("4.6.1", units[0]["text"])
        self.assertIn("4.14.1", units[0]["text"])                # 跨条款族同章合并
        self.assertIn("5.1", units[1]["text"])

    def test_clause_mode_respects_double_target_cap(self) -> None:
        # 0715 后默认(clause)=目录子树打包:上限 2×target,与整章模式(24k 帽)判然有别
        sections = [self._sec("4.6.1 R", "x" * 3000), self._sec("4.14.1 R", "y" * 3000),
                    self._sec("4.15.1 R", "z" * 3000)]
        default_units = ai_extract.merge_sections(sections, target_chars=2800)
        self.assertGreater(len(default_units), 1)                # clause 不整章吞
        for u in default_units:
            self.assertLessEqual(len(u["text"]), 2800 * 2 + 100)
        chapter_units = ai_extract.merge_sections(sections, unit_mode="chapter")
        self.assertEqual(len(chapter_units), 1)                  # chapter 模式仍整章

    def test_oversize_chapter_splits_at_member_boundary(self) -> None:
        big = ai_extract.CHAPTER_MAX_CHARS // 2 + 100
        sections = [self._sec("7.1 A", "a" * big), self._sec("7.2 B", "b" * big),
                    self._sec("7.3 C", "c" * big)]
        units = ai_extract.merge_sections(sections, unit_mode="chapter")
        self.assertGreater(len(units), 1)                        # 超帽在成员边界拆
        for u in units:
            self.assertLessEqual(len(u["text"]), ai_extract.CHAPTER_MAX_CHARS + 200)

    def test_chapter_prompt_keeps_tail_beyond_12000_chars(self) -> None:
        tail = "TAIL_REQUIREMENT_MARKER"
        units = ai_extract.merge_sections(
            [self._sec("7.1 Long chapter", "a" * 13000 + tail)], unit_mode="chapter")
        self.assertEqual(len(units), 1)
        self.assertGreater(len(units[0]["text"]), 12000)

        payload = json.loads(ai_extract.build_section_prompt(units[0]))
        self.assertEqual(payload["text"], units[0]["text"])
        self.assertIn(tail, payload["text"])


class SelfCheckClauseAlignmentTests(unittest.TestCase):
    """真实案例（EN 16314 §4.14）：初抽按条款族正确合成一条（子项 a-e），自检只见标题→
    把 a-e 判遗漏又拆回 4 条碎片（含引句为前缀子串的重复），一个条款 18 个批注点。
    修复三处：自检看结构摘要、引句包含式去重、行覆盖记账认 sub_items 标签。"""

    def _existing(self) -> list[dict]:
        return [{
            "title": "XDEV抗不当处理（跌落）测试要求",
            "description": "d", "source_quote":
                "The XDEV shall withstand the handling required during its transport and installation. "
                "Before testing in accordance with 4.14.2, the meter under test shall conform.",
            "sub_items": [{"label": c, "text": f"子项{c}"} for c in "abcde"],
            "acceptance_criteria": ["按 4.14.2 跌落后功能正常"],
        }]

    def test_critique_prompt_shows_structure_and_coverage_rule(self) -> None:
        captured: list[str] = []

        def chat(system: str, user: str) -> dict:
            captured.append(user)
            return {"requirements": []}

        section = {"section_id": "4.14", "heading": "4.14", "block_ids": [],
                   "text": "The XDEV shall withstand the handling required."}
        ai_extract.critique_section(section, self._existing(), chat)
        self.assertIn("子项:a,b,c,d,e", captured[0])            # 结构摘要可见
        self.assertIn("验收 1 条", captured[0])
        self.assertIn("不要**把它们拆成新需求".replace("**", ""),
                      captured[0].replace("**", ""))            # 覆盖判定规则在场

    def test_prefix_substring_duplicate_dropped(self) -> None:
        """自检补的"新"条目引句是已抽引句前缀（真实 #2）→ 包含式去重拦下。"""
        section = {"section_id": "4.14", "heading": "4.14", "block_ids": [],
                   "text": ("The XDEV shall withstand the handling required during its transport "
                            "and installation. Before testing in accordance with 4.14.2, "
                            "the meter under test shall conform.")}

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "XDEV应能承受运输和安装中的正常处理", "description": "重复碎片",
                "type": "functional", "priority": "P1", "labels": ["附加功能"],
                "source_quote": "The XDEV shall withstand the handling required during "
                                "its transport and installation."}]}

        extra, _sup = ai_extract.critique_section(section, self._existing(), chat)
        self.assertEqual(extra, [])                              # 同源重复被弃

    def test_genuinely_new_requirement_still_accepted(self) -> None:
        section = {"section_id": "4.14", "heading": "4.14", "block_ids": [],
                   "text": ("The XDEV shall withstand handling. "
                            "The display shall remain readable after the drop test.")}

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "跌落后显示仍可读", "description": "d",
                "type": "functional", "priority": "P1", "labels": ["显示"],
                "source_quote": "The display shall remain readable after the drop test."}]}

        extra, _sup = ai_extract.critique_section(section, self._existing(), chat)
        self.assertEqual(len(extra), 1)                          # 真遗漏不受影响

    def test_uncovered_lines_credit_sub_item_labels(self) -> None:
        """a)/b) 枚举行已在某需求 sub_items 里 → 不再进"未覆盖"清单（定向自检不再追打）。"""
        blocks = {
            "B1": {"block_id": "B1", "requirement_like": True, "noise": False,
                   "text": "a) the XDEV shall function as specified by the manufacturer;"},
            "B2": {"block_id": "B2", "requirement_like": True, "noise": False,
                   "text": "f) some other uncovered requirement line entirely."},
        }
        section = {"section_id": "4.14", "heading": "4.14", "block_ids": ["B1", "B2"],
                   "text": blocks["B1"]["text"] + "\n" + blocks["B2"]["text"]}
        uncovered = ai_extract._uncovered_requirement_lines(section, self._existing(), blocks)
        self.assertEqual(len(uncovered), 1)
        self.assertTrue(uncovered[0].startswith("f)"))           # a) 已被子项覆盖，f) 才是真未覆盖

    def test_uncovered_lines_do_not_credit_whole_section_fallback_span(self) -> None:
        blocks = {
            "B1": {"block_id": "B1", "order": 1, "requirement_like": True, "noise": False,
                   "text": "The meter shall log events."},
            "B2": {"block_id": "B2", "order": 2, "requirement_like": True, "noise": False,
                   "text": "The meter shall expose alarms."},
        }
        section = {
            "section_id": "4",
            "heading": "4",
            "block_ids": ["B1", "B2"],
            "text": blocks["B1"]["text"] + "\n" + blocks["B2"]["text"],
        }
        existing = [{
            "source_quote": blocks["B1"]["text"],
            "source_block_ids": ["B1", "B2"],
            "source_mapping": "section_fallback",
        }]

        uncovered = ai_extract._uncovered_requirement_lines(section, existing, blocks)

        self.assertEqual(uncovered, [blocks["B2"]["text"]])


class AnnexRefAndTermDefsTests(unittest.TestCase):
    """v11：Annex 引用解析（EN 系测试程序全在附录，此前是瞎的）+ 术语定向注入。"""

    def test_annex_reference_resolved(self) -> None:
        sections = [
            {"section_id": "A", "heading": "Annex A", "block_ids": ["B1"],
             "text": "Annex A\nA.1.4.6 Test mixture\nUse 30 % toluene and 70 % iso-octane."},
            {"section_id": "B", "heading": "7.1", "block_ids": ["B2"],
             "text": "Condition the meter in accordance with Annex A before testing."},
            {"section_id": "C", "heading": "7.2", "block_ids": ["B3"],
             "text": "Prepare the mixture, see A.1.4.6 for composition."},
        ]
        ai_extract.resolve_section_refs(sections)
        self.assertEqual(sections[1]["ref_texts"][0]["clause"], "A")        # Annex A → 键 A
        self.assertIn("toluene", sections[1]["drift_source"])
        self.assertEqual(sections[2]["ref_texts"][0]["clause"], "A.1.4.6")  # 附录小节
        self.assertIn("iso-octane", sections[2]["ref_texts"][0]["text"])

    def test_term_definitions_attached_and_in_prompt(self) -> None:
        sections = [
            {"section_id": "T", "heading": "3.1.4 additional functionality device Type 1",
             "section_path": ["3 Terms, definitions and abbreviated terms"],
             "block_ids": ["B1"],
             "text": "3.1.4 additional functionality device Type 1\nfactory fitted device attached to the meter"},
            {"section_id": "R", "heading": "4.4", "section_path": ["4 General requirements"],
             "block_ids": ["B2"],
             "text": "The additional functionality device Type 1 shall not affect metrology."},
            {"section_id": "S", "heading": "4.5", "section_path": ["4 General requirements"],
             "block_ids": ["B3"], "text": "Unrelated clause about marking."},
        ]
        entries = ai_extract.collect_term_entries(sections)
        self.assertEqual(len(entries), 1)
        # 术语章自身的结构标题不是术语（真实产物：曾把 "Terms and definitions" 收进对照表）
        junk = {"section_id": "TJ", "heading": "3.1 Terms and definitions",
                "section_path": ["3 Terms, definitions and abbreviated terms"],
                "block_ids": ["B9"], "text": "3.1 Terms and definitions"}
        self.assertEqual(ai_extract.collect_term_entries([junk]), [])
        ai_extract.attach_term_definitions(sections, entries)
        self.assertIn("term_defs", sections[1])                             # 用到术语的单元
        self.assertNotIn("term_defs", sections[2])                          # 没用到不注入
        self.assertIn("factory fitted", sections[1]["drift_source"])        # 定义并入漂移基线
        prompt = ai_extract.build_section_prompt(sections[1])
        self.assertIn("术语定义", prompt)
        fp_with = ai_extract.section_fingerprint(sections[1], "m")
        del sections[1]["term_defs"]
        self.assertNotEqual(fp_with, ai_extract.section_fingerprint(sections[1], "m"))  # 指纹折入


class CrossRefAndValueGuardTests(unittest.TestCase):
    """真实反馈两案：①"limits given in 7.13.4.5.1"——限值在别的单元，抽取看不见；
    ②粉尘粒径/成分清单被"规定的范围"指代吞掉（threshold_table=None，数值没落地）。"""

    def _sections(self) -> list[dict]:
        return [
            {"section_id": "A", "heading": "A", "block_ids": ["B1"],
             "text": "7.13.4.5.1 Leakage limits\nThe leak rate shall not exceed 25 cm3/h at 500 mbar."},
            {"section_id": "B", "heading": "B", "block_ids": ["B2"],
             "text": "Close the valve and confirm that the leak rate does not exceed the values given in 7.13.4.5.1."},
        ]

    def test_cross_section_ref_injected_and_drift_extended(self) -> None:
        sections = ai_extract.resolve_section_refs(self._sections())
        ref_sec = sections[1]
        self.assertEqual(len(ref_sec["ref_texts"]), 1)
        self.assertEqual(ref_sec["ref_texts"][0]["clause"], "7.13.4.5.1")
        self.assertIn("25 cm3/h", ref_sec["ref_texts"][0]["text"])          # 被引限值进摘录
        self.assertIn("25 cm3/h", ref_sec["drift_source"])                  # 引用其数值=有据
        prompt = ai_extract.build_section_prompt(ref_sec)
        self.assertIn("被引用条款 7.13.4.5.1", prompt)                       # 注入 prompt
        self.assertNotIn("ref_texts", sections[0])                          # 被引方自身不受影响

    def test_ref_to_clause_in_same_unit_not_injected(self) -> None:
        sections = [{"section_id": "A", "heading": "A", "block_ids": ["B1"],
                     "text": "7.9 Accuracy\nSee 7.9 for details. The limit is 5."}]
        ai_extract.resolve_section_refs(sections)
        self.assertNotIn("ref_texts", sections[0])

    def test_ref_changes_fingerprint(self) -> None:
        sections = self._sections()
        before = ai_extract.section_fingerprint(sections[1], "m")
        ai_extract.resolve_section_refs(sections)
        after = ai_extract.section_fingerprint(sections[1], "m")
        self.assertNotEqual(before, after)                                  # 注入条款变 → 缓存失效

    def test_values_left_behind_flagged(self) -> None:
        """粉尘案：引句后紧跟的粒径/成分数值清单没进需求 → 可疑度标记（只标不拦）。"""
        section = {"section_id": "D", "heading": "D", "block_ids": ["B1"],
                   "text": ("Four separate batches of dust shall be used with 95 % of the particles. "
                            "1) 0 um to 100 um Average size (50 ± 10) um; 2) 100 um to 200 um Average "
                            "size (150 ± 10) um. Composition: Black iron oxide 79 %, Red iron oxide 12 %, "
                            "silica flour 8 %, paint flake 1 %.")}

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "尘埃测试用尘规格", "description": "必须使用四批规定粒径与成分的尘埃。",
                "type": "constraint", "priority": "P1", "labels": ["环境可靠性"],
                "source_quote": "Four separate batches of dust shall be used with 95 % of the particles."}]}

        reqs = ai_extract.extract_section(section, chat)
        self.assertIn("原文数值未带全", reqs[0].get("suspicion_reasons") or [])
        self.assertIn("原文数值未带全", reqs[0]["notes"])

    def test_values_captured_not_flagged(self) -> None:
        section = {"section_id": "D", "heading": "D", "block_ids": ["B1"],
                   "text": "The meter shall store at least 12 monthly records within 30 days."}

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "存储", "description": "存储不少于 12 个月记录，30 天内。",
                "type": "non_functional", "priority": "P1", "labels": ["数据存储"],
                "source_quote": "The meter shall store at least 12 monthly records within 30 days."}]}

        reqs = ai_extract.extract_section(section, chat)
        self.assertNotIn("原文数值未带全", reqs[0].get("suspicion_reasons") or [])


class SampleSectionsTests(unittest.TestCase):
    """试抽模式：均匀抽样 N 章（「测试运行」分钟级质量样本）。"""

    def _secs(self, n: int) -> list[dict]:
        return [{"section_id": f"S{i}", "heading": f"S{i}", "text": f"body {i}", "block_ids": [f"B{i}"]}
                for i in range(n)]

    def test_uniform_stride_sampling_deterministic(self) -> None:
        picked, sampled = ai_extract.sample_sections(self._secs(20), 4)
        self.assertTrue(sampled)
        self.assertEqual([s["section_id"] for s in picked], ["S0", "S5", "S10", "S15"])  # 均匀非前 N
        picked2, _ = ai_extract.sample_sections(self._secs(20), 4)
        self.assertEqual(picked, picked2)                                                # 确定性

    def test_no_limit_or_oversized_returns_all(self) -> None:
        secs = self._secs(5)
        self.assertEqual(ai_extract.sample_sections(secs, None), (secs, False))
        self.assertEqual(ai_extract.sample_sections(secs, 0), (secs, False))
        self.assertEqual(ai_extract.sample_sections(secs, 9), (secs, False))

    def test_sample_ratio_scales_with_document(self) -> None:
        """测试运行按 1/5 比例抽样——随文档规模自适应，不写死条数（用户裁定）。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            lines = [{"block_id": f"B{i}", "section_path": [f"{i} Sec"],
                      "text": f"The meter shall do thing {i}."} for i in range(10)]
            with (out / "blocks.jsonl").open("w", encoding="utf-8") as f:
                for row in lines:
                    f.write(json.dumps(row) + "\n")
            total = len(ai_extract.merge_sections(ai_extract.assemble_sections(lines), target_chars=30))
            result = ai_extract.run_ai_extract(out, route="stub", sample_ratio=0.2, merge_chars=30)
        expected = max(1, round(total * 0.2))
        self.assertEqual(result["sampled"], {"sections": expected, "total_sections": total})

    def test_run_ai_extract_limit_reports_sampled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            lines = [{"block_id": f"B{i}", "section_path": [f"{i} Sec"],
                      "text": f"The meter shall do thing {i}."} for i in range(8)]
            with (out / "blocks.jsonl").open("w", encoding="utf-8") as f:
                for row in lines:
                    f.write(json.dumps(row) + "\n")
            expected_total = len(ai_extract.merge_sections(
                ai_extract.assemble_sections(lines), target_chars=30))
            result = ai_extract.run_ai_extract(out, route="stub", limit_sections=3, merge_chars=30)
        self.assertGreater(expected_total, 3)               # 前提：单元数确实超过样本数
        self.assertEqual(result["sampled"], {"sections": 3, "total_sections": expected_total})
        self.assertEqual(result["sections"], 3)


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
            after_first = calls["n"]   # 二遍复核默认开:首跑调用数=抽取+复核,不锁死具体值
            second = ai_extract.extract_all(sections, chat, model="m", cache_path=cache)
            self.assertEqual(calls["n"], after_first)  # 第二次命中缓存，未再调 LLM
            self.assertEqual(first, second)   # 同输入同输出（稳定）

    def test_cache_reader_repairs_only_unterminated_final_record(self) -> None:
        valid_row = {"fingerprint": "good", "requirements": [{"title": "cached"}]}
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "c.jsonl"
            valid_line = json.dumps(valid_row, ensure_ascii=False) + "\n"
            cache.write_text(valid_line + '{"fingerprint":"torn"', encoding="utf-8")

            with self.assertLogs("requirement_atomizer", level="WARNING") as captured:
                rows = ai_extract.read_cache(cache)

            self.assertEqual(rows, {"good": [{"title": "cached"}]})
            self.assertEqual(cache.read_text(encoding="utf-8"), valid_line)
            self.assertIn("repaired interrupted final JSONL cache record", captured.output[0])

    def test_cache_reader_rejects_malformed_middle_record(self) -> None:
        valid_row = json.dumps({"fingerprint": "good", "requirements": []})
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "c.jsonl"
            original = valid_row + "\n" + '{"fingerprint":}\n' + valid_row + "\n"
            cache.write_text(original, encoding="utf-8")

            with self.assertRaises(json.JSONDecodeError):
                ai_extract.read_cache(cache)

            self.assertEqual(cache.read_text(encoding="utf-8"), original)


class ExtractAllProgressTests(unittest.TestCase):
    def test_progress_events_and_failure_count(self) -> None:
        """每章节回调进度 + 失败章节计入 stats 不崩 —— 回归：AI 抽取零进度时界面像卡死。"""
        from llm_client import LLMConnectionError
        sections = [
            {"section_id": "S1", "heading": "S1", "text": "The meter shall do A.", "block_ids": ["B1"]},
            {"section_id": "S2", "heading": "S2", "text": "The meter shall do B.", "block_ids": ["B2"]},
        ]

        def chat(system: str, user: str) -> dict:
            if "do B" in user:  # 模拟某章节 LLM 调用失败（如 401/超时）
                raise LLMConnectionError("HTTP 401")
            return {"requirements": [{"title": "Do A", "description": "做 A", "type": "functional",
                                      "priority": "P1", "labels": ["计量"],
                                      "source_quote": "The meter shall do A."}]}

        events: list[dict] = []
        stats: dict = {}
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "c.jsonl"
            flat = ai_extract.extract_all(sections, chat, model="m", cache_path=cache,
                                          progress_callback=events.append, stats=stats)
        # 初始 1 次 + 每章节完成各 1 次 = 至少 3 次回调，末次满 100%
        self.assertGreaterEqual(len(events), 3)
        self.assertEqual(events[-1]["stage"], "ai_extract")
        self.assertEqual(events[-1]["completed"], 2)
        self.assertEqual(events[-1]["total"], 2)
        self.assertEqual(events[-1]["percent"], 100)
        # 失败章节计入 stats、不抛；成功章节仍产 1 条需求
        self.assertEqual(stats["failed_sections"], 1)
        self.assertEqual(stats["failed_section_ids"], ["S2"])
        self.assertEqual(stats["failed_section_block_ids"], ["B2"])
        self.assertEqual(stats["total_sections"], 2)
        self.assertEqual(len(flat), 1)


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

    def test_run_ai_extract_floors_max_tokens_for_reasoning_models(self) -> None:
        """推理模型 max_tokens 太小会截断 JSON → 整章节失败；run_ai_extract 须把预算抬到下限。"""
        from llm_client import LLMClientConfig
        captured: dict = {}

        def fake_chat_json(config, system, user):
            captured["max_tokens"] = config.max_tokens
            return {"requirements": []}

        low = LLMClientConfig(base_url="http://x", model="m", max_tokens=1024)
        orig_cfg = ai_extract.config_for_route
        orig_chat = ai_extract.chat_json
        ai_extract.config_for_route = lambda route, pipeline_path=None: low
        ai_extract.chat_json = fake_chat_json
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                (out / "blocks.jsonl").write_text(
                    '{"block_id":"B1","section_path":["4"],"text":"The meter shall do A."}\n',
                    encoding="utf-8")
                ai_extract.run_ai_extract(out, route="openai_compatible", merge_deterministic=False)
            self.assertEqual(captured["max_tokens"], ai_extract.AI_EXTRACT_MIN_MAX_TOKENS)
        finally:
            ai_extract.config_for_route = orig_cfg
            ai_extract.chat_json = orig_chat

    def test_resolve_concurrency_explicit_env_default_and_clamp(self) -> None:
        import os
        # 显式参数优先并夹取
        self.assertEqual(ai_extract.resolve_concurrency(2), 2)
        self.assertEqual(ai_extract.resolve_concurrency(99), ai_extract.MAX_CONCURRENCY)
        self.assertEqual(ai_extract.resolve_concurrency(0), 1)
        prior = os.environ.get(ai_extract.CONCURRENCY_ENV)
        try:
            os.environ[ai_extract.CONCURRENCY_ENV] = "3"
            self.assertEqual(ai_extract.resolve_concurrency(None), 3)  # 取环境变量
            os.environ[ai_extract.CONCURRENCY_ENV] = "bogus"
            self.assertEqual(ai_extract.resolve_concurrency(None), ai_extract.DEFAULT_CONCURRENCY)
            os.environ.pop(ai_extract.CONCURRENCY_ENV, None)
            self.assertEqual(ai_extract.resolve_concurrency(None), ai_extract.DEFAULT_CONCURRENCY)
        finally:
            if prior is None:
                os.environ.pop(ai_extract.CONCURRENCY_ENV, None)
            else:
                os.environ[ai_extract.CONCURRENCY_ENV] = prior

    def test_stub_route_still_produces_deterministic_merged_spec(self) -> None:
        """stub（LLM 关）下确定性引擎仍须照常产出 merged_spec —— 回归：早期 early-return 让 GUI 双引擎按钮零产出。"""
        original = ai_extract.load_or_build_deterministic
        # 确定性结构需求须带 threshold_table.rows，否则 merge_requirements 视为散文模板丢弃
        ai_extract.load_or_build_deterministic = lambda out_dir, *, source, extracted_at: [
            {"id": "DET-1", "title": "Register value", "description": "OBIS 1-0:1.8.0.255",
             "type": "数据需求", "priority": "P1", "labels": ["计量"],
             "source_section": "4 Data model", "source_quote": "", "notes": "",
             "acceptance_criteria": [], "status": "draft",
             "dependencies": [], "parent": None, "children": [],
             "threshold_table": {"columns": ["OBIS", "class_id"],
                                 "rows": [["1-0:1.8.0.255", "3"]]}},
        ]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                (out / "blocks.jsonl").write_text(
                    '{"block_id":"B1","section_path":["4"],"text":"The meter shall do A."}\n',
                    encoding="utf-8")
                result = ai_extract.run_ai_extract(out, route="stub", merge_deterministic=True)
                self.assertEqual(result["route"], "stub")
                self.assertEqual(result["requirements"], 0)  # AI 行为引擎为空
                # 确定性引擎照常落盘
                self.assertIn("merged_spec_requirements.json", result["written"])
                self.assertIn("merged_spec.xlsx", result["written"])
                self.assertTrue((out / "merged_spec_requirements.json").exists())
                self.assertTrue((out / "merged_spec.xlsx").exists())
                self.assertEqual(result["merged"]["deterministic_structural"], 1)
                self.assertEqual(result["merged"]["ai_behavioral"], 0)
        finally:
            ai_extract.load_or_build_deterministic = original


class MergeSectionsTests(unittest.TestCase):
    def test_small_sections_merged_to_target(self) -> None:
        sections = [
            {"section_id": "A", "heading": "A", "text": "x" * 100, "block_ids": ["b1"]},
            {"section_id": "B", "heading": "B", "text": "y" * 100, "block_ids": ["b2"]},
            {"section_id": "C", "heading": "C", "text": "z" * 100, "block_ids": ["b3"]},
        ]
        merged = ai_extract.merge_sections(sections, target_chars=260)
        # 100+标题 累加，260 上限 → 前两段并一个，第三段单独 → 2 个单元
        self.assertEqual(len(merged), 2)
        # block 溯源不丢
        all_ids = [bid for m in merged for bid in m["block_ids"]]
        self.assertEqual(sorted(all_ids), ["b1", "b2", "b3"])
        # 合并文本含各小节标题
        self.assertIn("## A", merged[0]["text"])
        self.assertIn("## B", merged[0]["text"])

    def test_oversized_section_is_split_under_target(self) -> None:
        """超大源章节须被拆成 ≤target 的多块（防 LLM 输出 JSON 截断）——回归：8987 字整块导致 40/48 失败。"""
        paras = "\n".join(f"段落{i} " + "字" * 200 for i in range(20))  # ~4200 字，单章节
        sections = [{"section_id": "S1", "heading": "H", "text": paras, "block_ids": ["b1", "b2"]}]
        merged = ai_extract.merge_sections(sections, target_chars=2800)
        self.assertGreater(len(merged), 1)  # 被拆开
        for m in merged:
            self.assertLessEqual(len(m["text"]), 2800)  # 每块有界
            self.assertEqual(m["block_ids"], ["b1", "b2"])  # 同段 block 溯源保留

    def test_split_text_bounds_and_is_lossless(self) -> None:
        text = "\n".join(f"line{i} " + "a" * 100 for i in range(60))  # ~6500 字
        chunks = ai_extract._split_text(text, 2800)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 2800 for c in chunks))
        # 去掉拆分边界换行后内容无损
        self.assertEqual("".join(c.replace("\n", "") for c in chunks), text.replace("\n", ""))

    def test_split_handles_single_overlong_line(self) -> None:
        chunks = ai_extract._split_text("x" * 9000, 2800)  # 无换行长行须硬切
        self.assertTrue(all(len(c) <= 2800 for c in chunks))
        self.assertEqual("".join(chunks), "x" * 9000)

    def test_split_carries_full_drift_source(self) -> None:
        """拆分后漂移 baseline 须用整章原文：同章另一片段里的 OBIS 不算漂移（假阳性误伤）。"""
        # 前 4000 字无码，末尾段落含真实 OBIS 码 → 被拆到靠后的片段
        text = ("安全描述文字。" * 600) + "\n该对象对应 OBIS 0-0:96.7.16.255。"
        merged = ai_extract.merge_sections(
            [{"section_id": "S", "heading": "安全", "text": text, "block_ids": ["b1"]}],
            target_chars=2800)
        self.assertGreater(len(merged), 1)  # 确实被拆分
        # 早期片段 text 不含该码，但 drift_source 须是整章原文 → 含码
        early = merged[0]
        self.assertNotIn("0-0:96.7.16.255", early["text"])
        self.assertIn("0-0:96.7.16.255", early["drift_source"])

    def test_fingerprint_tracks_full_drift_source(self) -> None:
        section = {
            "section_id": "S", "heading": "安全", "text": "unchanged split fragment",
            "drift_source": "unchanged split fragment\nOBIS 0-0:96.7.16.255",
        }
        before = ai_extract.section_fingerprint(section, "model")
        section["drift_source"] = "unchanged split fragment\nOBIS 0-0:96.7.17.255"
        self.assertNotEqual(before, ai_extract.section_fingerprint(section, "model"))

    def test_cross_ref_keeps_full_split_drift_source(self) -> None:
        """拆分片段注入跨节引用时，不得丢掉整章基线中的其它片段编码。"""
        obis = "0-0:96.7.16.255"
        source = (
            "Confirm the limit specified in 9.1 before activation.\n"
            + "Long chapter context. " * 300
            + f"\nThe event object uses OBIS {obis}."
        )
        target = "9.1 Reference limit\nThe activation limit shall be 25 units. " + "detail " * 120
        units = ai_extract.merge_sections([
            {"section_id": "S", "heading": "Long chapter", "text": source, "block_ids": ["b1"]},
            {"section_id": "R", "heading": "Reference", "text": target, "block_ids": ["b2"]},
        ], target_chars=2800)
        referring = next(unit for unit in units if "specified in 9.1" in unit["text"])
        self.assertNotIn(obis, referring["text"])
        self.assertIn(obis, referring["drift_source"])

        ai_extract.resolve_section_refs(units)

        self.assertEqual(referring["ref_texts"][0]["clause"], "9.1")
        self.assertIn("25 units", referring["drift_source"])
        self.assertIn(obis, referring["drift_source"])

    def test_cross_fragment_code_not_falsely_flagged_as_drift(self) -> None:
        """回归：LLM 在不含码的片段里引用同章另一片段的 OBIS 码，不得被判结构漂移。"""
        # 构造一个超大章节：前半段无码，后半段含真实 OBIS，拆分后早期片段不含码
        real_text = ("安全章节描述文字。" * 400) + "\n事件对象 OBIS 0-0:96.7.16.255。"
        merged = ai_extract.merge_sections(
            [{"section_id": "S", "heading": "安全", "text": real_text, "block_ids": ["b1"]}],
            target_chars=2800)
        early = merged[0]
        self.assertNotIn("0-0:96.7.16.255", early["text"])  # 早期片段确不含码

        # LLM 对早期片段抽取时引用了同章另一片段里的真实码 → 不应判漂移
        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "事件上报", "description": "采用 OBIS 0-0:96.7.16.255 上报安全事件。",
                "type": "functional", "priority": "P1", "labels": ["事件记录"],
                "source_quote": "security event"}]}

        reqs = ai_extract.extract_section(early, chat)
        self.assertEqual(len(reqs), 1)
        self.assertNotIn("结构漂移已拦截", reqs[0]["notes"])  # 同章真实码不算漂移

    def test_cross_fragment_fabricated_code_still_flagged(self) -> None:
        """护栏仍须拦住真正的无中生有：LLM 凭空编的码（整章都没有）仍判结构漂移。"""
        real_text = ("安全章节描述文字。" * 400)  # 整章不含任何 OBIS 码
        merged = ai_extract.merge_sections(
            [{"section_id": "S", "heading": "安全", "text": real_text, "block_ids": ["b1"]}],
            target_chars=2800)

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "伪造", "description": "走 OBIS 0-0:96.99.99.255（原文并无此码）。",
                "type": "functional", "priority": "P1", "labels": ["事件记录"],
                "source_quote": ""}]}

        reqs = ai_extract.extract_section(merged[0], chat)
        self.assertEqual(len(reqs), 1)
        self.assertIn("结构漂移已拦截", reqs[0]["notes"])
        self.assertEqual(reqs[0]["status"], "draft")


class DriftSeverityTests(unittest.TestCase):
    def _section(self) -> dict:
        return {"section_id": "S", "heading": "S",
                "text": "The device shall support a serial interface for data export.",
                "block_ids": ["b1"]}

    def test_fabricated_int_is_soft_flagged_and_kept(self) -> None:
        def chat(system: str, user: str) -> dict:
            return {"requirements": [{"title": "Serial", "description": "支持 RS-485 串行接口导出数据。",
                                       "type": "functional", "priority": "P1", "labels": ["通信协议"],
                                       "source_quote": "shall support a serial interface for data export"}]}

        reqs = ai_extract.extract_section(self._section(), chat)
        self.assertEqual(len(reqs), 1)  # 软标不丢弃
        self.assertIn("数字漂移", reqs[0]["notes"])
        self.assertNotIn("结构漂移已拦截", reqs[0]["notes"])  # 485 不是受保护编码

    def test_fabricated_obis_is_hard_flagged(self) -> None:
        def chat(system: str, user: str) -> dict:
            return {"requirements": [{"title": "Bogus", "description": "走 OBIS 0-0:96.7.16.255 上报。",
                                       "type": "functional", "priority": "P1", "labels": ["事件记录"],
                                       "source_quote": "data export"}]}

        reqs = ai_extract.extract_section(self._section(), chat)
        self.assertEqual(reqs[0]["status"], "draft")
        self.assertIn("结构漂移已拦截（编码", reqs[0]["notes"])

    def test_fabricated_capacity_numbers_removed_from_delivery_fields(self) -> None:
        section = {
            "section_id": "3.8",
            "heading": "3.8 measurement data",
            "text": "Data that the MGW must collect, record locally and transmit remotely.",
            "block_ids": ["B1"],
        }

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{
                "title": "MGW测量数据采集、本地记录与远程传输",
                "description": "MGW必须采集、记录并远程传输测量数据。",
                "type": "functional",
                "priority": "P1",
                "labels": ["计量"],
                "source_quote": "Data that the MGW must collect, record locally and transmit remotely.",
                "acceptance_criteria": [
                    "本地存储中至少可查询最近24小时/30天的原始测量数据",
                    "中心系统可远程读取已记录的测量数据",
                ],
                "dev_guidance": [
                    "实现本地数据存储协议：使用循环缓冲区或FIFO队列，存储至少最近N条记录（N由设计容量决定，建议≥1万条）",
                    "使用FIFO队列缓存待传数据",
                    "提供远程读取接口",
                ],
            }]}

        req = ai_extract.extract_section(section, chat)[0]

        self.assertEqual(req["acceptance_criteria"], ["中心系统可远程读取已记录的测量数据"])
        self.assertEqual(req["dev_guidance"], ["提供远程读取接口"])
        self.assertIn("数字漂移", req.get("suspicion_reasons") or [])
        self.assertIn("无依据条目已移入备注", req["notes"])
        self.assertIn("建议≥1万条", req["notes"])
        self.assertIn("FIFO", req["notes"])


class EnsureDomainLabelsTests(unittest.TestCase):
    def test_free_labels_get_a_metering_domain_prepended(self) -> None:
        from spec_excel import METERING_DOMAINS
        reqs = [{"title": "固件升级安全", "description": "固件升级须认证并保证安全。",
                 "source_quote": "firmware upgrade authentication", "labels": ["XDEV", "firmware"]}]
        ai_extract.ensure_domain_labels(reqs)
        self.assertTrue(any(l in set(METERING_DOMAINS) for l in reqs[0]["labels"]))
        # 原自由标签保留
        self.assertIn("XDEV", reqs[0]["labels"])

    def test_existing_domain_label_untouched(self) -> None:
        reqs = [{"title": "x", "description": "y", "source_quote": "z", "labels": ["计量", "XDEV"]}]
        ai_extract.ensure_domain_labels(reqs)
        self.assertEqual(reqs[0]["labels"], ["计量", "XDEV"])


class MergeRequirementsTests(unittest.TestCase):
    def test_keeps_structural_drops_template_adds_ai(self) -> None:
        det = [
            {"title": "对象X", "threshold_table": {"description": "属性访问表", "columns": ["#"], "rows": [["1"]]}},
            {"title": "确定性模板行为", "threshold_table": None},  # 纯散文模板 → 丢
        ]
        ai = [{"title": "AI行为需求", "threshold_table": None, "extracted_by": "ai_extract"}]
        merged = ai_extract.merge_requirements(det, ai)
        titles = [r["title"] for r in merged]
        self.assertIn("对象X", titles)        # 确定性结构（OBIS 权威）保留
        self.assertIn("AI行为需求", titles)    # AI 行为加入
        self.assertNotIn("确定性模板行为", titles)  # 确定性散文模板丢弃（AI 替代）
        self.assertEqual(merged[0]["extracted_by"], "deterministic")


class BuildSkillDocTests(unittest.TestCase):
    def test_builds_skill_format_doc(self) -> None:
        reqs = [
            {"title": "A", "description": "desc A", "type": "functional", "priority": "P1",
             "status": "draft", "source_section": "1", "source_quote": "q", "threshold_table": None,
             "acceptance_criteria": [], "dependencies": [], "parent": None, "children": [],
             "labels": ["计量"], "notes": ""},
        ]
        doc = ai_extract.build_skill_doc(reqs, source="doc.pdf", extracted_at="2026-01-01T00:00:00")
        self.assertIn("meta", doc)
        self.assertIn("requirements", doc)
        self.assertIn("analysis", doc)
        self.assertEqual(doc["requirements"][0]["id"], "REQ-001")
        self.assertEqual(doc["analysis"]["total_count"], 1)


class ModuleClassificationTests(unittest.TestCase):
    """LLM 受控模块分类（按域分组的首要领域来源）。"""

    def _section(self) -> dict:
        return {"section_id": "S", "heading": "S", "text": "t", "block_ids": []}

    def test_normalize_captures_module(self) -> None:
        r = ai_extract.normalize_requirement(
            {"title": "X", "description": "d", "module": "计量", "source_quote": "d"}, self._section())
        self.assertEqual(r["module"], "计量")

    def test_module_vocab_superset_and_prompt(self) -> None:
        for m in ("附加功能", "机械结构", "计量精度", "数据存储", "测试合规", "其它"):
            self.assertIn(m, ai_extract.MODULE_VOCAB)
        self.assertIn("module", ai_extract.SYSTEM_PROMPT)
        self.assertIn("附加功能", ai_extract.SYSTEM_PROMPT)

    def test_valid_llm_module_becomes_primary_domain(self) -> None:
        reqs = [{"module": "计量", "labels": ["gas meter", "measurement"],
                 "title": "", "description": "", "source_quote": ""}]
        ai_extract.ensure_domain_labels(reqs)
        self.assertEqual(reqs[0]["labels"][0], "计量")        # LLM 模块作首要领域
        self.assertIn("gas meter", reqs[0]["labels"])          # 自由标签保留为补充

    def test_other_module_respected_not_remapped(self) -> None:
        reqs = [{"module": "其它", "labels": ["XDEV"],
                 "title": "mechanical connector", "description": "", "source_quote": ""}]
        ai_extract.ensure_domain_labels(reqs)
        self.assertEqual(reqs[0]["labels"][0], "其它")         # 尊重 LLM "无贴切"，不塞通信协议

    def test_invalid_or_missing_module_falls_back_to_map_labels(self) -> None:
        reqs = [
            {"module": "乱填XX", "labels": [], "title": "voltage sag threshold",
             "description": "", "source_quote": ""},
            {"module": "", "labels": [], "title": "firmware upgrade image",
             "description": "", "source_quote": ""},
        ]
        ai_extract.ensure_domain_labels(reqs)
        self.assertEqual(reqs[0]["labels"][0], "门限范围")     # map_labels 关键词兜底
        self.assertEqual(reqs[1]["labels"][0], "升级")


class ContextEngineeringTests(unittest.TestCase):
    """上下文工程：文档全局背景（画像/大纲/术语表）注入每次抽取。"""

    def _blocks(self) -> list:
        return [
            {"block_id": "B1", "section_path": ["1 Scope"], "text": "The scope."},
            {"block_id": "B2", "section_path": ["3 Terms and definitions"],
             "text": "XDEV additional functionality device"},
            {"block_id": "B3", "section_path": ["4 Requirements"],
             "text": "The meter shall measure gas volume."},
        ]

    def test_build_doc_context_has_profile_outline_glossary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "manifest.json").write_text(
                '{"input": "EN 16314 Gas meter.pdf"}', encoding="utf-8")
            ctx = ai_extract.build_doc_context(out, self._blocks())
            self.assertIn("gas", ctx)                              # 表计类型（meter_profile）
            self.assertIn("EN 16314", ctx)                         # 目标标准
            self.assertIn("Scope", ctx)                            # 章节大纲
            self.assertIn("additional functionality device", ctx)  # 术语表（Terms 节文本）

    def test_outline_cleans_pdf_framing_garbage(self) -> None:
        outline = ai_extract._outline_from_blocks(
            [{"block_id": "B", "section_path": ["2 --`,``,```,`,,---"], "text": "x"}])
        self.assertNotIn("```", outline)  # 框线乱码被清（该条降为空、不入大纲）

    def test_fingerprint_changes_with_context_key(self) -> None:
        sec = {"text": "same section text"}
        a = ai_extract.section_fingerprint(sec, "m", "ctxA")
        b = ai_extract.section_fingerprint(sec, "m", "ctxB")
        self.assertNotEqual(a, b)                                  # 背景变 → 指纹变（缓存失效重抽）
        self.assertEqual(a, ai_extract.section_fingerprint(sec, "m", "ctxA"))  # 同背景稳定

    def test_extract_section_injects_context_into_user_prompt(self) -> None:
        captured: dict = {}

        def chat(system: str, user: str) -> dict:
            captured["user"] = user
            return {"requirements": []}

        sec = {"section_id": "S", "heading": "S", "text": "The meter shall do A.", "block_ids": []}
        ai_extract.extract_section(sec, chat, doc_context="【文档背景】表计类型：gas。")
        self.assertIn("表计类型：gas", captured["user"])           # 背景注入
        self.assertIn("当前章节", captured["user"])                # 分隔标记，防搬运背景

    def test_extract_all_with_context_reproducible(self) -> None:
        sections = [{"section_id": "S1", "heading": "S1", "text": "The meter shall do A.", "block_ids": ["B1"]}]
        calls = {"n": 0}

        def chat(system: str, user: str) -> dict:
            calls["n"] += 1
            return {"requirements": [{"title": "A", "description": "做 A", "type": "functional",
                                      "priority": "P1", "labels": ["计量"], "source_quote": "The meter shall do A."}]}

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "c.jsonl"
            first = ai_extract.extract_all(sections, chat, model="m", cache_path=cache, doc_context="CTX")
            after_first = calls["n"]   # 二遍复核默认开:不锁死首跑调用数
            second = ai_extract.extract_all(sections, chat, model="m", cache_path=cache, doc_context="CTX")
            self.assertEqual(calls["n"], after_first)   # 含背景仍逐字缓存、第二次命中
            self.assertEqual(first, second)


class SelfCheckTests(unittest.TestCase):
    """完整性自检 pass：抽完再查漏补缺。"""

    def _section(self) -> dict:
        return {"section_id": "S", "heading": "S",
                "text": "The meter shall do A. It shall also do B.", "block_ids": []}

    def _req(self, title: str, quote: str) -> dict:
        return {"title": title, "description": title + " desc", "type": "functional",
                "priority": "P1", "labels": ["计量"], "source_quote": quote}

    def test_resolve_self_check_env_and_explicit(self) -> None:
        import os
        prior = os.environ.get(ai_extract.SELF_CHECK_ENV)
        try:
            os.environ.pop(ai_extract.SELF_CHECK_ENV, None)
            self.assertTrue(ai_extract.resolve_self_check(None))        # 默认开
            os.environ[ai_extract.SELF_CHECK_ENV] = "0"
            self.assertFalse(ai_extract.resolve_self_check(None))
            os.environ[ai_extract.SELF_CHECK_ENV] = "off"
            self.assertFalse(ai_extract.resolve_self_check(None))
            os.environ[ai_extract.SELF_CHECK_ENV] = ""
            self.assertTrue(ai_extract.resolve_self_check(None))        # 空串≠关闭，回落默认
            self.assertTrue(ai_extract.resolve_self_check(True))        # 显式优先
            self.assertFalse(ai_extract.resolve_self_check(False))
        finally:
            if prior is None:
                os.environ.pop(ai_extract.SELF_CHECK_ENV, None)
            else:
                os.environ[ai_extract.SELF_CHECK_ENV] = prior

    def test_self_check_appends_missing_deduped(self) -> None:
        calls = {"n": 0}

        def chat(system: str, user: str) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:  # 初抽：只给 A
                return {"requirements": [self._req("Do A", "The meter shall do A.")]}
            return {"requirements": [                       # 自检：A(重复) + B(新)
                self._req("Do A", "The meter shall do A."),
                self._req("Do B", "It shall also do B.")]}

        reqs = ai_extract.extract_section(self._section(), chat, self_check=True)
        self.assertEqual(calls["n"], 2)                     # 抽取 + 自检各一次
        self.assertEqual(len(reqs), 2)                      # A + B（重复 A 去重）
        self.assertIn("It shall also do B.", [r["source_quote"] for r in reqs])

    def test_self_check_off_is_single_call(self) -> None:
        calls = {"n": 0}

        def chat(system: str, user: str) -> dict:
            calls["n"] += 1
            return {"requirements": [self._req("A", "The meter shall do A.")]}

        ai_extract.extract_section(self._section(), chat, self_check=False)
        self.assertEqual(calls["n"], 1)                     # 关闭 → 仅一次

    def test_self_check_failure_keeps_initial(self) -> None:
        from llm_client import LLMConnectionError
        calls = {"n": 0}

        def chat(system: str, user: str) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                return {"requirements": [self._req("A", "The meter shall do A.")]}
            raise LLMConnectionError("critique failed")

        reqs = ai_extract.extract_section(self._section(), chat, self_check=True)
        self.assertEqual(len(reqs), 1)                      # 自检失败不致命，保留初抽
        self.assertEqual(reqs[0]["title"], "A")

    def test_self_check_keeps_description_only_item(self) -> None:
        """自检补充项无引用无标题但有描述 → 键回退到描述，不再被静默丢弃。"""
        calls = {"n": 0}

        def chat(system: str, user: str) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                return {"requirements": []}
            return {"requirements": [{"title": "", "description": "仅描述的补充项",
                                      "type": "functional", "priority": "P2",
                                      "labels": ["计量"], "source_quote": ""}]}

        reqs = ai_extract.extract_section(self._section(), chat, self_check=True)
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0]["description"], "仅描述的补充项")


class ContextIntExemptionTests(unittest.TestCase):
    """背景里的普通整数（如标准号）不软标为数字漂移；受保护编码不豁免。"""

    def _section(self) -> dict:
        return {"section_id": "S", "heading": "S",
                "text": "The meter shall do A.", "block_ids": []}

    def _chat_with(self, description: str):
        def chat(system: str, user: str) -> dict:
            return {"requirements": [{"title": "T", "description": description,
                                      "type": "functional", "priority": "P1",
                                      "labels": ["计量"], "source_quote": "The meter shall do A."}]}
        return chat

    def test_standard_number_from_context_not_flagged(self) -> None:
        ctx = "【文档背景】表计类型：gas；目标标准：EN 16314。"
        reqs = ai_extract.extract_section(self._section(), self._chat_with("依据 EN 16314 做 A"),
                                          doc_context=ctx)
        self.assertNotIn("数字漂移", reqs[0]["notes"])       # 背景数字豁免
        # 对照：无背景时同一数字仍软标
        reqs2 = ai_extract.extract_section(self._section(), self._chat_with("依据 EN 16314 做 A"))
        self.assertIn("数字漂移", reqs2[0]["notes"])

    def test_context_number_not_in_context_still_flagged(self) -> None:
        ctx = "【文档背景】表计类型：gas；目标标准：EN 16314。"
        reqs = ai_extract.extract_section(self._section(), self._chat_with("保存 12345 条记录"),
                                          doc_context=ctx)
        self.assertIn("数字漂移", reqs[0]["notes"])          # 背景没有的数字照常软标

    def test_protected_codes_not_exempted_by_context(self) -> None:
        ctx = "【术语/定义】total register OBIS 1-0:1.8.0.255"   # 背景里出现的 OBIS
        reqs = ai_extract.extract_section(self._section(),
                                          self._chat_with("读取 OBIS 1-0:1.8.0.255"),
                                          doc_context=ctx)
        self.assertIn("结构漂移已拦截", reqs[0]["notes"])     # 编码严格：仍只认章节原文
        self.assertEqual(reqs[0]["status"], "draft")


class DecisionBackflowTests(unittest.TestCase):
    """P0：专家裁决（ai_review_states）回流交付物。"""

    def _req(self, title: str, quote: str) -> dict:
        return {"title": title, "description": f"{title} 描述", "type": "functional",
                "priority": "P1", "module": "计量", "labels": ["计量", "gas"],
                "source_section": "4", "source_quote": quote, "notes": "",
                "acceptance_criteria": [], "status": "draft",
                "dependencies": [], "parent": None, "children": []}

    def test_rejected_dropped_override_and_confirm_applied(self) -> None:
        import ai_review_actions
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            reqs = [self._req("A", "quote A"), self._req("B", "quote B"), self._req("C", "quote C")]
            rid_a = ai_review_actions.ai_req_id(reqs[0])
            rid_b = ai_review_actions.ai_req_id(reqs[1])
            ai_review_actions.apply_ai_review_action(out, rid_a, "rejected", reason="不是需求")
            ai_review_actions.apply_ai_review_action(out, rid_b, "accepted",
                                                     module_override="计量精度", reason="归精度")
            stats: dict = {}
            kept = ai_extract.apply_ai_decisions(out, reqs, stats)
            self.assertEqual([r["title"] for r in kept], ["B", "C"])   # rejected 剔除
            self.assertEqual(kept[0]["status"], "confirmed")            # accepted → confirmed
            self.assertEqual(kept[0]["labels"][0], "计量精度")          # override 定首要领域
            self.assertIn("gas", kept[0]["labels"])                     # 自由标签保留
            self.assertIn("专家意见：归精度", kept[0]["notes"])
            self.assertEqual(kept[1]["status"], "draft")                # 未裁决原样
            self.assertEqual(stats["decisions_applied"], 2)
            self.assertEqual(stats["rejected_dropped"], 1)

    def test_rebuild_merged_spec_applies_latest_decisions(self) -> None:
        import ai_review_actions
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            reqs = [self._req("A", "quote A"), self._req("B", "quote B")]
            with (out / "ai_requirements.jsonl").open("w", encoding="utf-8") as f:
                for r in reqs:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            (out / "dlms_cosem_spec_requirements.json").write_text('{"requirements": []}', encoding="utf-8")
            ai_review_actions.apply_ai_review_action(out, ai_review_actions.ai_req_id(reqs[0]), "rejected")
            result = ai_extract.rebuild_merged_spec(out)
            self.assertEqual(result["total"], 1)                       # A 被剔除
            self.assertEqual(result["rejected_dropped"], 1)
            self.assertIn("merged_spec_requirements.json", result["written"])
            merged = json.loads((out / "merged_spec_requirements.json").read_text(encoding="utf-8"))
            self.assertEqual([r["title"] for r in merged["requirements"]], ["B"])

    def test_rebuild_merged_spec_applies_decision_for_explicit_ai_req_id(self) -> None:
        import ai_review_actions
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            reqs = [{**self._req("A", "quote A"), "ai_req_id": "AI-1"}, self._req("B", "quote B")]
            with (out / "ai_requirements.jsonl").open("w", encoding="utf-8") as f:
                for r in reqs:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            (out / "dlms_cosem_spec_requirements.json").write_text('{"requirements": []}', encoding="utf-8")
            ai_review_actions.apply_ai_review_action(out, "AI-1", "rejected")

            result = ai_extract.rebuild_merged_spec(out)

            self.assertEqual(result["total"], 1)
            self.assertEqual(result["rejected_dropped"], 1)
            merged = json.loads((out / "merged_spec_requirements.json").read_text(encoding="utf-8"))
            self.assertEqual([r["title"] for r in merged["requirements"]], ["B"])


class TargetedSelfCheckTests(unittest.TestCase):
    """P1：自检定向查漏——未覆盖 requirement_like 语句作焦点；全覆盖则跳过省调用。"""

    def _section(self) -> dict:
        return {"section_id": "S", "heading": "S",
                "text": "The meter shall do A.\nThe meter shall also do B.",
                "block_ids": ["B1", "B2"]}

    def _block_info(self) -> dict:
        return {
            "B1": {"block_id": "B1", "text": "The meter shall do A.", "requirement_like": True, "noise": False},
            "B2": {"block_id": "B2", "text": "The meter shall also do B.", "requirement_like": True, "noise": False},
        }

    def _req_a(self) -> dict:
        return {"title": "Do A", "description": "做 A", "type": "functional", "priority": "P1",
                "labels": ["计量"], "source_quote": "The meter shall do A."}

    def test_skips_critique_when_all_requirement_like_covered(self) -> None:
        calls = {"n": 0}
        block_info = self._block_info()
        block_info["B2"]["requirement_like"] = False  # 只有 B1 是需求语句，且被覆盖

        def chat(system: str, user: str) -> dict:
            calls["n"] += 1
            return {"requirements": [self._req_a()]}

        reqs = ai_extract.extract_section(self._section(), chat, self_check=True, block_info=block_info)
        self.assertEqual(calls["n"], 1)     # 全覆盖 → 自检跳过，只调 1 次
        self.assertEqual(len(reqs), 1)

    def test_uncovered_line_becomes_critique_focus(self) -> None:
        calls = {"n": 0}
        captured: dict = {}

        def chat(system: str, user: str) -> dict:
            calls["n"] += 1
            if calls["n"] == 2:
                captured["user"] = user
                return {"requirements": []}
            return {"requirements": [self._req_a()]}

        ai_extract.extract_section(self._section(), chat, self_check=True, block_info=self._block_info())
        self.assertEqual(calls["n"], 2)                                # B2 未覆盖 → 自检执行
        self.assertIn("重点核查", captured["user"])                    # 定向焦点注入
        self.assertIn("The meter shall also do B.", captured["user"])
        self.assertNotIn("- The meter shall do A.", captured["user"].split("重点核查")[-1])  # 已覆盖不在焦点

    def test_self_check_added_items_carry_flag_and_suspicion(self) -> None:
        calls = {"n": 0}

        def chat(system: str, user: str) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                return {"requirements": [self._req_a()]}
            return {"requirements": [{"title": "Do B", "description": "做 B", "type": "functional",
                                      "priority": "P1", "labels": ["计量"],
                                      "source_quote": "The meter shall also do B."}]}

        reqs = ai_extract.extract_section(self._section(), chat, self_check=True, block_info=self._block_info())
        added = [r for r in reqs if r.get("self_check_added")]
        self.assertEqual(len(added), 1)
        self.assertIn("自检补充（初抽遗漏）", added[0]["suspicion_reasons"])

    def test_definition_constraint_is_recovered_by_targeted_self_check(self) -> None:
        definition = (
            "A period of time that always begins on the first day of a month "
            "and ends on the first day of one or more subsequent months; "
            "it can be valid for 1, 2, 3, 4, 6, 12 months."
        )
        section = {"section_id": "3.24", "heading": "3.24 billing period",
                   "text": f"3.24 billing period\n{definition}", "block_ids": ["B1", "B2"]}
        block_info = {
            "B1": {"block_id": "B1", "text": "3.24 billing period",
                   "requirement_like": False, "noise": False, "type": "heading"},
            "B2": {"block_id": "B2", "text": definition,
                   "requirement_like": True, "noise": False, "type": "paragraph"},
        }
        calls = {"n": 0}
        captured: dict[str, str] = {}

        def chat(system: str, user: str) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                return {"requirements": []}
            captured["user"] = user
            return {"requirements": [{
                "title": "限定结算周期有效月份",
                "description": "结算周期从一个月的第一天开始，到后续一个或多个自然月的第一天结束；有效期只能为1、2、3、4、6或12个月。",
                "type": "constraint",
                "priority": "P1",
                "module": "结算",
                "labels": ["结算周期"],
                "source_quote": definition,
                "acceptance_criteria": ["配置结算周期时，只允许选择1、2、3、4、6或12个月。"],
            }]}

        reqs = ai_extract.extract_section(section, chat, self_check=True, block_info=block_info)

        self.assertEqual(calls["n"], 2)
        self.assertIn(definition, captured["user"])
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0]["type"], "constraint")
        self.assertIn("1, 2, 3, 4, 6, 12 months", reqs[0]["source_quote"])
        self.assertTrue(reqs[0]["self_check_added"])

    # --- P1 自检收敛循环：多轮直到覆盖清单穷尽 ---
    def _section3(self) -> dict:
        return {"section_id": "S3", "heading": "S3",
                "text": "The meter shall do A.\nThe meter shall do B.\nThe meter shall do C.",
                "block_ids": ["B1", "B2", "B3"]}

    def _block_info3(self) -> dict:
        return {
            "B1": {"block_id": "B1", "text": "The meter shall do A.", "requirement_like": True, "noise": False},
            "B2": {"block_id": "B2", "text": "The meter shall do B.", "requirement_like": True, "noise": False},
            "B3": {"block_id": "B3", "text": "The meter shall do C.", "requirement_like": True, "noise": False},
        }

    def _r(self, title: str, quote: str) -> dict:
        return {"title": title, "description": title, "type": "functional", "priority": "P1",
                "labels": ["计量"], "source_quote": quote}

    def test_convergence_catches_cascading_omission(self) -> None:
        """收敛循环的价值：C 只有在 A、B 补进去、未覆盖清单缩小后才被查漏抓到——单趟拿不到。"""
        calls = {"n": 0}

        def chat(system: str, user: str) -> dict:
            calls["n"] += 1
            n = calls["n"]
            if n == 1:
                return {"requirements": [self._r("Do A", "The meter shall do A.")]}
            if n == 2:                                   # 第 1 轮查漏：只补 B
                return {"requirements": [self._r("Do B", "The meter shall do B.")]}
            if n == 3:                                   # 第 2 轮查漏：清单缩到 C，才补 C
                return {"requirements": [self._r("Do C", "The meter shall do C.")]}
            return {"requirements": []}

        reqs = ai_extract.extract_section(self._section3(), chat, self_check=True,
                                          block_info=self._block_info3())
        quotes = {r["source_quote"] for r in reqs}
        self.assertEqual(len(reqs), 3)                   # A + B + C 全抓到
        self.assertIn("The meter shall do C.", quotes)   # 级联遗漏被收敛循环补回
        self.assertEqual(calls["n"], 3)                  # 抽取 + 2 轮查漏（第 3 轮全覆盖，提前停）

    def test_round_cap_bounds_iterations(self) -> None:
        """轮数上限守住：rounds=1 只查漏一轮，级联的 C 不会被抓（防发散优先于穷尽）。"""
        calls = {"n": 0}

        def chat(system: str, user: str) -> dict:
            calls["n"] += 1
            n = calls["n"]
            if n == 1:
                return {"requirements": [self._r("Do A", "The meter shall do A.")]}
            if n == 2:
                return {"requirements": [self._r("Do B", "The meter shall do B.")]}
            return {"requirements": [self._r("Do C", "The meter shall do C.")]}

        reqs = ai_extract.extract_section(self._section3(), chat, self_check=True,
                                          block_info=self._block_info3(), self_check_rounds=1)
        quotes = {r["source_quote"] for r in reqs}
        self.assertEqual(calls["n"], 2)                  # 抽取 + 仅 1 轮查漏
        self.assertNotIn("The meter shall do C.", quotes)  # 触顶即停，C 未补

    def test_resolve_self_check_rounds_env_and_bounds(self) -> None:
        import os
        prior = os.environ.get(ai_extract.SELF_CHECK_ROUNDS_ENV)
        try:
            self.assertEqual(ai_extract.resolve_self_check_rounds(None), 3)     # 默认
            self.assertEqual(ai_extract.resolve_self_check_rounds(2), 2)        # 显式优先
            self.assertEqual(ai_extract.resolve_self_check_rounds(99),
                             ai_extract.MAX_SELF_CHECK_ROUNDS)                  # 夹到硬上限
            self.assertEqual(ai_extract.resolve_self_check_rounds(0), 1)        # 夹到 ≥1
            os.environ[ai_extract.SELF_CHECK_ROUNDS_ENV] = "4"
            self.assertEqual(ai_extract.resolve_self_check_rounds(None), 4)     # env 生效
        finally:
            if prior is None:
                os.environ.pop(ai_extract.SELF_CHECK_ROUNDS_ENV, None)
            else:
                os.environ[ai_extract.SELF_CHECK_ROUNDS_ENV] = prior


class PromptV5Tests(unittest.TestCase):
    def test_prompt_has_threshold_table_quality_rules_and_example(self) -> None:
        self.assertIn("threshold_table", ai_extract.SYSTEM_PROMPT)
        self.assertIn("质量准则", ai_extract.SYSTEM_PROMPT)
        self.assertIn("示例", ai_extract.SYSTEM_PROMPT)
        self.assertIn("dev_guidance", ai_extract.SYSTEM_PROMPT)      # 研发落地指引
        self.assertIn("不要输出", ai_extract.SYSTEM_PROMPT)               # v7：目录/引用/范围声明剔除规则
        self.assertIn("数值必须落地", ai_extract.SYSTEM_PROMPT)            # v8：数值清单完整落地 + 被引条款整合
        self.assertIn("条款族=一条需求", ai_extract.SYSTEM_PROMPT)          # v9：条款族 + sub_items + Test→验收
        self.assertIn("sub_items", ai_extract.SYSTEM_PROMPT)
        self.assertIn("不得给默认建议值", ai_extract.SYSTEM_PROMPT)          # v12：无来源数字不得进入交付字段
        self.assertIn("术语定义中的固定起止规则", ai_extract.SYSTEM_PROMPT)
        self.assertIn("1, 2, 3, 4, 6, 12 months", ai_extract.SYSTEM_PROMPT)
        # v16（0714 批次三 E7）：functional_key 构造规则（跨章合并连接键含糊→错并/漏并）
        # + priority 判级基准（此前无 rubric,逐章漂移打分）
        self.assertIn("跨章节合并的连接键", ai_extract.SYSTEM_PROMPT)
        self.assertIn("阀门关闭控制", ai_extract.SYSTEM_PROMPT)          # 正例
        self.assertIn("判级基准", ai_extract.SYSTEM_PROMPT)
        self.assertIn("P0=安全/计量准确性/法规强制项", ai_extract.SYSTEM_PROMPT)
        # v17（0715 重构）:忠实性判据(内容审计 29 处误读)+测试装置排除(附录噪声)
        self.assertIn("忠实性", ai_extract.SYSTEM_PROMPT)
        self.assertIn("不得升格约束强度", ai_extract.SYSTEM_PROMPT)
        self.assertIn("测试装置/夹具/图例说明", ai_extract.SYSTEM_PROMPT)
        self.assertEqual(ai_extract.AI_EXTRACT_PROMPT_VERSION, "ai-extract-v21")

    def test_normalize_captures_dev_guidance(self) -> None:
        sec = {"section_id": "S", "heading": "S", "text": "t", "block_ids": []}
        r = ai_extract.normalize_requirement(
            {"title": "X", "description": "d", "source_quote": "t",
             "dev_guidance": ["实现环形存储", "  ", "提供读取接口"]}, sec)
        self.assertEqual(r["dev_guidance"], ["实现环形存储", "提供读取接口"])  # 去空白项

    def test_quote_not_verbatim_flags_suspicion(self) -> None:
        sec = {"section_id": "S", "heading": "S", "text": "The meter shall do A.", "block_ids": []}

        def chat(system: str, user: str) -> dict:
            return {"requirements": [{"title": "X", "description": "做 X", "type": "functional",
                                      "priority": "P1", "labels": ["计量"],
                                      "source_quote": "a paraphrased quote not in source"}]}

        reqs = ai_extract.extract_section(sec, chat)
        self.assertIn("引用非逐字", reqs[0].get("suspicion_reasons") or [])


class SourceMappingTests(unittest.TestCase):
    def test_fragmented_multi_block_quote_ignores_tiny_page_number_block(self) -> None:
        section = {
            "block_ids": ["B14", "B15", "B21"],
            "source_blocks": [
                {"block_id": "B14", "text": "The meter must meet the conditions set forth i nthe standards."},
                {"block_id": "B15", "text": "It must comply a ccording t o Act 157/2018 C oll."},
                {"block_id": "B21", "text": "2"},
            ],
        }
        req = {
            "source_quote": (
                "The meter must meet the conditions set forth in the standards. "
                "It must comply according to Act 157/2018 Coll."
            )
        }

        ai_extract._map_requirement_source(req, section)

        self.assertEqual(req["source_block_ids"], ["B14", "B15"])
        self.assertEqual(req["anchor_block_id"], "B14")
        self.assertEqual(req["source_mapping"], "multi_block")

    def test_section_fallback_narrows_span_to_requirement_section(self) -> None:
        """跨小节单元的 fallback 只留所属小节块（test5 实证：24 块跨 3.4.4/3.4.5/3.4.6，
        无关清单段 "- DAY1" 被误标分析范围）。"""
        section = {
            "block_ids": ["B1", "B2", "B3", "B4", "B5"],
            "source_blocks": [
                {"block_id": "B1", "text": "3.4.4 Marking of terminals",
                 "section_path": ["3", "3.4.4 Marking of terminals"]},
                {"block_id": "B2", "text": "- DAY1",
                 "section_path": ["3", "3.4.4 Marking of terminals"]},
                {"block_id": "B3", "text": "3.4.5 Screws",
                 "section_path": ["3", "3.4.5 Screws"]},
                {"block_id": "B4", "text": "The terminal box must be supplied with crosshead combi screws.",
                 "section_path": ["3", "3.4.5 Screws"]},
                {"block_id": "B5", "text": "3.4.6 Packaging",
                 "section_path": ["3", "3.4.6 Packaging"]},
            ],
        }
        req = {"source_quote": "a paraphrased quote not in source",
               "source_section": "3.4.5 Screws", "notes": ""}

        ai_extract._map_requirement_source(req, section)

        self.assertEqual(req["source_block_ids"], ["B3", "B4"])
        self.assertEqual(req["anchor_block_id"], "B3")
        self.assertEqual(req["source_mapping"], "section_fallback")
        self.assertIn("收窄", str(req.get("notes") or ""))

    def test_section_fallback_keeps_full_span_when_section_unmatched(self) -> None:
        """所属小节一个块都匹配不上时退回整单元（如实保留"定位不精"原口径，不猜）。"""
        section = {
            "block_ids": ["B1", "B2"],
            "source_blocks": [
                {"block_id": "B1", "text": "3.4.4 Marking of terminals",
                 "section_path": ["3", "3.4.4 Marking of terminals"]},
                {"block_id": "B2", "text": "- DAY1",
                 "section_path": ["3", "3.4.4 Marking of terminals"]},
            ],
        }
        req = {"source_quote": "a paraphrased quote not in source",
               "source_section": "9.9 Nowhere", "notes": ""}

        ai_extract._map_requirement_source(req, section)

        self.assertEqual(req["source_block_ids"], ["B1", "B2"])
        self.assertEqual(req["source_mapping"], "section_fallback")

    def test_section_fallback_keeps_full_span_without_source_section(self) -> None:
        section = {
            "block_ids": ["B1"],
            "source_blocks": [
                {"block_id": "B1", "text": "- DAY1",
                 "section_path": ["3", "3.4.4 Marking of terminals"]},
            ],
        }
        req = {"source_quote": "a paraphrased quote not in source", "notes": ""}

        ai_extract._map_requirement_source(req, section)

        self.assertEqual(req["source_block_ids"], ["B1"])
        self.assertEqual(req["source_mapping"], "section_fallback")


class ComplianceExtractionTests(unittest.TestCase):
    def test_legal_certificate_is_deterministically_retyped_and_source_backed(self) -> None:
        quote = "Valid Certificate according to the standard STN EN 62053-22."
        row = ai_extract.normalize_requirement({
            "title": "Certificate",
            "description": "Provide the certificate.",
            "type": "functional",
            "source_quote": quote,
            "instrument": "IEC 99999",
        }, {"section_id": "2.1", "block_ids": ["B1"]})

        self.assertEqual(row["type"], "compliance")
        self.assertEqual(row["priority"], "P0")
        self.assertEqual(row["module"], "测试合规")
        self.assertEqual(row["compliance_instrument"], "")
        self.assertIn("IEC 99999", row["notes"])
        payload = ai_extract.build_compliance_payload([row])
        self.assertEqual(payload["items"][0]["instrument"], "")
        self.assertIn("IEC 99999", payload["items"][0]["notes"])

    def test_model_umbrella_flag_is_recomputed_from_obligation_count(self) -> None:
        row = ai_extract.normalize_requirement({
            "title": "Declaration",
            "description": "Provide the declaration.",
            "type": "compliance",
            "source_quote": "The declaration of conformity shall be supplied.",
            "compliance_umbrella": True,
            "compliance_obligations": [{"text": "Provide the declaration of conformity."}],
        }, {"section_id": "2.1", "block_ids": ["B1"]})

        self.assertFalse(row["compliance_umbrella"])

    def test_dlms_behavior_reference_stays_functional(self) -> None:
        row = ai_extract.normalize_requirement({
            "title": "Bidirectional communication",
            "description": "The meter communicates over IP.",
            "type": "functional",
            "source_quote": "Communication must use DLMS/COSEM standards based on IP.",
        }, {"section_id": "2", "block_ids": ["B1"]})

        self.assertEqual(row["type"], "functional")

    def test_regulatory_citation_does_not_remove_a_technical_constraint_from_core(self) -> None:
        row = ai_extract.normalize_requirement({
            "title": "Mechanical environmental class",
            "description": "The enclosure shall meet mechanical environmental class M1.",
            "type": "functional",
            "source_quote": (
                "The meter must meet mechanical environmental class M1 in accordance with "
                "Regulation of the Government No. 145/2016."
            ),
        }, {"section_id": "3.3", "block_ids": ["B1"]})

        self.assertEqual(row["type"], "functional")

    def test_unsupported_model_compliance_label_cannot_change_delivery_scope(self) -> None:
        row = ai_extract.normalize_requirement({
            "title": "Bidirectional communication",
            "description": "The meter communicates over IP.",
            "type": "compliance",
            "source_quote": "The meter shall communicate bidirectionally over DLMS/COSEM.",
            "instrument": "IEC 99999",
        }, {"section_id": "2", "block_ids": ["B1"]})

        self.assertEqual(row["type"], "functional")
        self.assertEqual(row["compliance_instrument"], "")

    def test_mixed_emc_and_certificate_source_stays_a_technical_requirement(self) -> None:
        row = ai_extract.normalize_requirement({
            "title": "EMC requirements",
            "description": "The meter shall withstand EMC disturbances.",
            "type": "compliance",
            "source_quote": (
                "Electricity meters must show resistance to electrostatic discharges according "
                "to STN EN 61000-4-2. We require a certificate of conformity to be supplied."
            ),
        }, {"section_id": "3.5", "block_ids": ["B1"]})

        self.assertEqual(row["type"], "functional")
        self.assertEqual(row["compliance_obligations"], [])

    def test_compliance_obligations_are_covered_by_delivery_field_drift_guard(self) -> None:
        quote = "Valid Certificate according to the standard STN EN 62053-22."
        row = ai_extract.normalize_requirement({
            "title": "Certificate",
            "description": "Provide the required certificate.",
            "type": "compliance",
            "source_quote": quote,
            "compliance_obligations": [
                {"label": "a", "text": "Supply a certificate according to IEC 99999."},
            ],
        }, {"section_id": "2.1", "block_ids": ["B1"]})

        ai_extract._move_unsupported_delivery_items(row, quote)

        self.assertEqual(row["compliance_obligations"], [])
        self.assertIn("compliance_obligations", row["notes"])
        self.assertIn("IEC 99999", row["notes"])


class QualityReportTests(unittest.TestCase):
    def test_section_failure_publishes_terminal_non_reusable_snapshot(self) -> None:
        from llm_client import LLMClientConfig, LLMConnectionError

        config = LLMClientConfig(base_url="http://x", model="m", max_tokens=8192)

        def failed_chat(*_args, **_kwargs):
            raise LLMConnectionError("endpoint unavailable")

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(ai_extract, "config_for_route", return_value=config), \
                patch.object(ai_extract, "chat_json", side_effect=failed_chat):
            out = Path(tmp)
            (out / "blocks.jsonl").write_text(json.dumps({
                "block_id": "B1", "section_path": ["4"],
                "text": "The meter shall do A.", "requirement_like": True,
                "noise": False,
            }) + "\n", encoding="utf-8")

            result = ai_extract.run_ai_extract(
                out, route="openai_compatible", self_check=False
            )
            partial = ai_extract.read_partial_snapshot(out / ai_extract.AI_REQUIREMENTS_PARTIAL)
            metadata = json.loads(
                (out / ai_extract.AI_REQUIREMENTS_META).read_text(encoding="utf-8")
            )

        self.assertEqual(result["failed_sections"], 1)
        self.assertEqual(result["failed_section_ids"], ["4"])
        self.assertTrue(partial["complete"])
        self.assertTrue(partial["failed"])
        self.assertEqual(metadata["failed_sections"], 1)
        self.assertEqual(metadata["failed_section_ids"], ["4"])

    def test_run_ai_extract_writes_quality_report_with_coverage(self) -> None:
        from llm_client import LLMClientConfig
        cfg = LLMClientConfig(base_url="http://x", model="m", max_tokens=8192)

        def fake_chat_json(config, system, user):
            return {"requirements": [{"title": "Do A", "description": "做 A", "type": "functional",
                                      "priority": "P1", "labels": ["计量"],
                                      "source_quote": "The meter shall do A."}]}

        orig_cfg = ai_extract.config_for_route
        orig_chat = ai_extract.chat_json
        ai_extract.config_for_route = lambda route, pipeline_path=None: cfg
        ai_extract.chat_json = fake_chat_json
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                (out / "blocks.jsonl").write_text(
                    json.dumps({"block_id": "B1", "section_path": ["4"],
                                "text": "The meter shall do A.", "requirement_like": True,
                                "noise": False}) + "\n" +
                    json.dumps({"block_id": "B2", "section_path": ["4"],
                                "text": "Uncovered requirement line.", "requirement_like": True,
                                "noise": False}) + "\n",
                    encoding="utf-8")
                result = ai_extract.run_ai_extract(out, route="openai_compatible", self_check=False)
                quality = json.loads((out / "ai_extract_quality.json").read_text(encoding="utf-8"))
                self.assertEqual(quality["requirement_like_blocks"], 2)
                self.assertEqual(quality["covered_blocks"], 1)          # B1 被引用覆盖，B2 未覆盖
                self.assertEqual(quality["coverage_pct"], 50.0)
                self.assertIn("计量", quality["by_module"])
                self.assertEqual(result["quality"]["requirements"], 1)
                self.assertIn("ai_extract_quality.json", result["written"])
        finally:
            ai_extract.config_for_route = orig_cfg
            ai_extract.chat_json = orig_chat



class FunctionalKeyNormalizationTests(unittest.TestCase):
    def test_missing_functional_key_stays_empty_for_catalog_inference(self) -> None:
        import ai_extract

        row = ai_extract.normalize_requirement(
            {"title": "上报计量事件", "description": "设备应上报计量事件。"},
            {"heading": "Events", "block_ids": ["B-1"]},
        )

        self.assertEqual(row["functional_key"], "")

    def test_explicit_functional_key_is_preserved(self) -> None:
        import ai_extract

        row = ai_extract.normalize_requirement(
            {"title": "上报计量事件", "functional_key": "计量事件管理", "description": "设备应上报计量事件。"},
            {"heading": "Events", "block_ids": ["B-1"]},
        )

        self.assertEqual(row["functional_key"], "计量事件管理")

if __name__ == "__main__":
    unittest.main()
