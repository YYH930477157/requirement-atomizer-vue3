"""待核成文（partial export）标记权威：conservation_pending_marks 的类与连带口径
+ extract_degraded_marks（v2）。

方案 docs/pending-export-plan-2026-08-31.md v2（grok 审核三条）：
- binding/evidence 直接点名 FRE；uncovered/preservation 连带「声明在该条款块上的
  FRE」（source_block_ids ∩ 条款 block_ids，与检查 5 叙述并集同口径）；
- 定位键 = 条款 block_ids，禁 section_id 字符串定位（SBD 撞名病理）——finding 只
  带 section_id 时按 id + 内容证据（义务句包含/保留 token 在场）确定性还原；
- duplicates 只标组内成员（组自带 FRE id 清单）；零 FRE 条款不造占位行；
- 直抽 partial（mixed）行加 extract_degraded（2026-09-01b 修正：v1 实现曾以
  「stub 条款不产 FRE」为由不做——该理由与 _stub_item 事实不符，stub 路径每条款
  产一条占位 FRE 且会无标注流进成文；现按方案 grok 审核第 3 条以标记侧确定性
  形状比对补全，仅 route=mixed 载荷启用）。
"""
from __future__ import annotations

import unittest

import functional_extract as fe


def _section(sid: str, text: str, blocks: list[str]) -> dict:
    return {"section_id": sid, "section_path": [sid], "heading": sid,
            "text": text, "block_ids": blocks}


def _item(fre_id: str, blocks: list[str], quote: str = "shall do things") -> dict:
    return {"functional_requirement_id": fre_id, "source_block_ids": blocks,
            "source_quote": quote, "objective": "obj", "description": "desc"}


def _report(*, binding=(), uncovered=(), preservation=(), duplicates=(), ok=False):
    return {
        "ok": ok,
        "checks": {
            "obligation_coverage": {"ok": not uncovered,
                                    "uncovered_obligations": list(uncovered)},
            "evidence_presence": {"ok": not binding,
                                  "binding_mismatches": list(binding),
                                  "evidence_mismatches": []},
            "duplicates": {"ok": not duplicates, "groups": list(duplicates)},
            "preservation": {"ok": not preservation,
                             "blocking_losses": list(preservation)},
        },
    }


class ConservationPendingMarksTests(unittest.TestCase):
    def test_binding_names_fres_directly(self) -> None:
        report = _report(binding=[{"functional_requirement_id": "F1",
                                   "reason": "narrative_covers_other_clauses_not_declared"}])
        marks = fe.conservation_pending_marks(
            report, [_item("F1", ["B1"]), _item("F2", ["B2"])],
            [_section("4.1", "text", ["B1"]), _section("4.2", "text", ["B2"])])
        self.assertEqual(marks["F1"], ["binding"])
        self.assertNotIn("F2", marks)

    def test_uncovered_connects_declared_fres_not_just_named(self) -> None:
        """义务未覆盖没有 FRE id——必须连带该条款块上声明的 FRE（零行=干净假象）。"""
        report = _report(uncovered=[{"section_id": "4.2", "sentence": "shall archive logs",
                                     "sentence_index": 0, "unit_index": 0}])
        sections = [
            _section("4.1", "The meter shall log events.", ["B1"]),
            _section("4.2", "The logger shall archive logs.", ["B2", "B3"]),
        ]
        items = [_item("F1", ["B1"]), _item("F2", ["B2"]), _item("F3", ["B3"])]
        marks = fe.conservation_pending_marks(report, items, sections)
        self.assertEqual(sorted(marks), ["F2", "F3"])
        self.assertTrue(all(marks[f] == ["uncovered"] for f in ("F2", "F3")))

    def test_section_id_collision_disambiguated_by_content(self) -> None:
        """SBD 撞名病理：同 id 两条款，按义务句内容证据定位到块集，不整名连带。"""
        report = _report(uncovered=[{"section_id": "X", "sentence": "shall archive logs",
                                     "sentence_index": 0, "unit_index": 0}])
        sections = [
            _section("X", "The meter shall log events.", ["B1"]),
            _section("X", "The logger shall archive logs nightly.", ["B2"]),
        ]
        items = [_item("F1", ["B1"]), _item("F2", ["B2"])]
        marks = fe.conservation_pending_marks(report, items, sections)
        self.assertEqual(sorted(marks), ["F2"])

    def test_preservation_connects_by_token_evidence(self) -> None:
        report = _report(preservation=[{"section_id": "6 TABLE", "kind": "number",
                                        "token": "230", "severity": "blocking"}])
        sections = [
            _section("6 TABLE", "Voltage 230 V limit.", ["T1"]),
            _section("6 TABLE", "Current 100 A.", ["T2"]),  # 同 id 撞名，无该 token
        ]
        items = [_item("F1", ["T1"]), _item("F2", ["T2"])]
        marks = fe.conservation_pending_marks(report, items, sections)
        self.assertEqual(sorted(marks), ["F1"])
        self.assertEqual(marks["F1"], ["preservation"])

    def test_duplicates_mark_group_members_only(self) -> None:
        report = _report(duplicates=[{
            "section_id": "4.1", "unit_index": 0,
            "functional_requirement_ids": ["F1", "F2"], "block_ids": ["B1"]}])
        sections = [_section("4.1", "shall log events", ["B1"]), _section("4.2", "x", ["B2"])]
        items = [_item("F1", ["B1"]), _item("F2", ["B1"]), _item("F3", ["B2"])]
        marks = fe.conservation_pending_marks(report, items, sections)
        self.assertEqual(sorted(marks), ["F1", "F2"])
        self.assertTrue(all(marks[f] == ["duplicate"] for f in ("F1", "F2")))

    def test_zero_fre_clause_marks_nothing_no_placeholder(self) -> None:
        report = _report(uncovered=[{"section_id": "4.9", "sentence": "shall be sealed",
                                     "sentence_index": 0, "unit_index": 0}])
        sections = [_section("4.9", "shall be sealed", ["B9"])]
        marks = fe.conservation_pending_marks(report, [], sections)
        self.assertEqual(marks, {})

    def test_classes_merge_when_fre_fails_multiple_checks(self) -> None:
        report = _report(
            binding=[{"functional_requirement_id": "F1", "reason": "r"}],
            uncovered=[{"section_id": "4.1", "sentence": "shall archive",
                        "sentence_index": 0, "unit_index": 0}])
        sections = [_section("4.1", "The logger shall archive logs.", ["B1"])]
        marks = fe.conservation_pending_marks(report, [_item("F1", ["B1"])], sections)
        self.assertEqual(sorted(marks["F1"]), ["binding", "uncovered"])

    def test_ok_report_marks_nothing(self) -> None:
        marks = fe.conservation_pending_marks(
            _report(ok=True), [_item("F1", ["B1"])], [_section("4.1", "x", ["B1"])])
        self.assertEqual(marks, {})


class AllowUnclosedTests(unittest.TestCase):
    def test_raise_if_unconserved_default_raises_and_allow_returns_summary(self) -> None:
        report = _report(binding=[{"functional_requirement_id": "F1", "reason": "r"}])
        with self.assertRaises(fe.FunctionalConservationError):
            fe.raise_if_unconserved(report)
        summary = fe.raise_if_unconserved(report, allow_unclosed=True)
        self.assertFalse(summary["ok"])
        self.assertEqual(summary["pending_fre_ids"], ["F1"])


class ExtractDegradedMarksTests(unittest.TestCase):
    """v2（2026-09-01b）：mixed 载荷的 stub 占位条目识别——方案 grok 审核第 3 条。

    事实基线：_stub_item 每条款产一条占位 FRE（objective=「实现{heading}，并满足
    来源条款。」、behaviors=[全文回显]），mixed 运行中这些行会无标注流进成文。
    """

    def _payload(self, route: str, items: list[dict]) -> dict:
        return {"route": route, "items": items}

    def _stub_shaped_item(self, fre_id: str, section: dict) -> dict:
        objective, behaviors = fe._stub_shape(section)
        return {
            "functional_requirement_id": fre_id,
            "source_block_ids": list(section["block_ids"]),
            "source_quote": section.get("text") or "",
            "objective": objective,
            "behaviors": behaviors,
            "description": "占位",
        }

    def test_mixed_payload_marks_stub_shaped_items(self) -> None:
        section = _section("4.1", "The meter shall log events.", ["B1"])
        clean = _item("F-LLM", ["B2"])
        clean.update({"objective": "记录事件", "behaviors": ["log events"]})
        sections = [section, _section("4.2", "The meter shall tariff switch.", ["B2"])]
        payload = self._payload(
            "mixed", [self._stub_shaped_item("F-STUB", section), clean])
        marks = fe.extract_degraded_marks(payload, sections)
        self.assertEqual(marks, {"F-STUB": ["extract_degraded"]})

    def test_non_mixed_payload_never_marks(self) -> None:
        # 纯 LLM 载荷没有 stub 条目；即使条目形状恰似占位（LLM 逐字复刻模板）也不标
        section = _section("4.1", "The meter shall log events.", ["B1"])
        payload = self._payload("llm:deepseek-v4-flash",
                                [self._stub_shaped_item("F1", section)])
        self.assertEqual(fe.extract_degraded_marks(payload, [section]), {})

    def test_llm_narrative_not_marked_in_mixed(self) -> None:
        # mixed 载荷里的真 LLM 叙述条目（形状≠占位模板）不标
        section = _section("4.1", "The meter shall log events.", ["B1"])
        item = self._stub_shaped_item("F1", section)
        item["objective"] = "电表记录事件日志"
        payload = self._payload("mixed", [item])
        self.assertEqual(fe.extract_degraded_marks(payload, [section]), {})

    def test_label_single_source(self) -> None:
        self.assertEqual(
            fe.pending_class_label(["extract_degraded"]), "抽取降级")
        self.assertEqual(
            fe.pending_class_label(["binding", "extract_degraded"]),
            "绑定失配、抽取降级")

    def test_stub_shape_matches_stub_item(self) -> None:
        # 与构造侧同源：_stub_shape 必须还原 _stub_item 的 objective/behaviors
        section = _section("4.1", "The meter shall log events.", ["B1"])
        item = fe._stub_item(section, 1)
        self.assertEqual(
            (item["objective"], item["behaviors"]), fe._stub_shape(section))


if __name__ == "__main__":
    unittest.main()
