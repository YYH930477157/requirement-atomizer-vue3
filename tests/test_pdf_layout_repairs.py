"""PDF 版式修复（W8：D1 下标归位 / D2 断行连字符 / D3 两栏定义表）专项测试。

纪律：全部合成夹具，不依赖真实 SBD 文档；开关全部 OFF 时钉住旧版调用与拼接语义
（字节一致、extra_attrs 不启用）；审计事件走 text_repairs 通道，layout 事件与
defrag 事件共存且 source alignment 仍可重放。
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from config import ENV_REGISTRY
from output_writer import build_quality_report
from parsers.pdf_parser import (
    PDF_HYPHEN_JOIN_VERSION,
    PDF_SUBSCRIPT_REATTACH_VERSION,
    PDF_TEXT_REPAIR_VERSION,
    PDF_TWOCOL_DEF_VERSION,
    _append_text_block,
    _build_pdf_table_artifacts,
    _detect_repeated_margin_lines,
    _detect_text_tables,
    _detect_twocol_definition_tables,
    _extract_page_words,
    _fragmentation_signal_count,
    _join_lines_text,
    _merge_continuation_blocks,
    _merge_lines,
    _merge_list_item_blocks,
    _merge_words,
    _reattach_subscripts,
    _starts_new_paragraph,
    pdf_hyphen_fix_enabled,
    pdf_layout_switch_fingerprint,
    pdf_subscript_fix_enabled,
    pdf_twocol_def_enabled,
    text_repair_vocabulary_fingerprint,
)
from atomize import DEFAULT_DOCUMENT_PROFILE, SectionState
from requirement_kb.repository import KnowledgeRepository
from source_spans import (
    source_alignment_fields,
    source_alignment_is_approved,
    validate_source_alignment,
)
from parsers.pdf_parser import _source_repair_provenance


KB = KnowledgeRepository(entries=[], infos=[])
REPO_ROOT = Path(__file__).resolve().parent.parent

_SWITCH_ENV = (
    "RATOMIZER_PDF_SUBSCRIPT_FIX",
    "RATOMIZER_PDF_HYPHEN_FIX",
    "RATOMIZER_PDF_TWOCOL_DEF",
)


class _EnvGuard:
    """临时设置/清除开关环境变量，退出时恢复原状。"""

    def __init__(self, **values: str | None) -> None:
        self._values = values
        self._saved: dict[str, str | None] = {}

    def __enter__(self) -> None:
        for name, value in self._values.items():
            self._saved[name] = os.environ.get(name)
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def __exit__(self, *exc: object) -> None:
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _word(
    text: str,
    x0: float,
    x1: float,
    top: float,
    bottom: float,
    *,
    size: float | None = 12.0,
    fontname: str | None = None,
    upright: bool = True,
) -> dict:
    word = {
        "text": text,
        "x0": float(x0),
        "x1": float(x1),
        "top": float(top),
        "bottom": float(bottom),
        "upright": upright,
    }
    if size is not None:
        word["size"] = float(size)
    if fontname is not None:
        word["fontname"] = fontname
    return word


def _subscript_page(main_specs: list[tuple[str, float, float]], cand: dict) -> list[dict]:
    """5+ 个 size 12 主词锚定中位数 + 1 个 size 9 候选。"""
    words = [_word(text, x0, x1, 100, 112) for text, x0, x1 in main_specs]
    words.append(cand)
    return words


def _cand(text: str, x0: float, x1: float, top: float = 103.5, *, size: float = 9.0) -> dict:
    return _word(text, x0, x1, top, top + 7.5, size=size)


def _line(text: str, top: float, *, bottom: float | None = None, x0: float = 50.0,
          x1: float = 400.0, words: list[dict] | None = None, **extra: object) -> dict:
    line = {
        "text": text,
        "top": float(top),
        "bottom": float(bottom if bottom is not None else top + 12),
        "x0": float(x0),
        "x1": float(x1),
        "words": words if words is not None else [],
    }
    line.update(extra)
    return line


class SubscriptReattachTests(unittest.TestCase):
    def test_latin_n_attaches_to_open_paren_word(self) -> None:
        words = _subscript_page(
            [("Nominal", 50, 100), ("current", 105, 150), ("(I", 155, 168),
             ("value", 178, 220), ("of", 225, 240)],
            _cand("n", 169, 173),
        )
        result, events = _reattach_subscripts(words, page_number=23)
        texts = [w["text"] for w in result]
        self.assertIn("(In", texts)
        self.assertNotIn("n", texts)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["rule"], "subscript_reattach")
        self.assertEqual(event["rule_version"], PDF_SUBSCRIPT_REATTACH_VERSION)
        self.assertEqual(event["before"], "(I n")
        self.assertEqual(event["after"], "(In")
        self.assertEqual(event["page_number"], 23)
        self.assertEqual(event["position_basis"], "word_geometry")

    def test_latin_b_and_max_attach(self) -> None:
        words_b = _subscript_page(
            [("Basic", 50, 95), ("current", 100, 150), ("(I", 155, 168),
             ("value", 178, 220), ("of", 225, 240)],
            _cand("b", 169, 173),
        )
        result_b, events_b = _reattach_subscripts(words_b)
        self.assertIn("(Ib", [w["text"] for w in result_b])
        self.assertEqual(events_b[0]["after"], "(Ib")

        words_max = _subscript_page(
            [("Maximum", 50, 110), ("current", 115, 165), ("I", 170, 176),
             ("highest", 185, 235), ("value", 240, 280)],
            _cand("max", 177, 190),
        )
        result_max, events_max = _reattach_subscripts(words_max)
        self.assertIn("Imax", [w["text"] for w in result_max])
        self.assertEqual(events_max[0]["after"], "Imax")

    def test_nearest_main_word_wins(self) -> None:
        words = _subscript_page(
            [("alpha", 50, 100), ("beta", 105, 155), ("gamma", 158, 190),
             ("delta", 195, 240), ("epsilon", 245, 300)],
            _cand("n", 192, 196),
        )
        # gamma x1=190（间隙 2）与 beta x1=155（间隙 37>6）——只有 gamma 合法
        result, events = _reattach_subscripts(words)
        texts = [w["text"] for w in result]
        self.assertIn("gamman", texts)
        self.assertEqual(events[0]["after"], "gamman")

    def test_gap_beyond_6pt_does_not_attach(self) -> None:
        words = _subscript_page(
            [("Nominal", 50, 100), ("current", 105, 150), ("(I", 155, 160),
             ("value", 178, 220), ("of", 225, 240)],
            _cand("n", 167, 171),   # 间隙 7pt > 6pt
        )
        result, events = _reattach_subscripts(words)
        self.assertEqual(events, [])
        self.assertIn("n", [w["text"] for w in result])
        self.assertIn("(I", [w["text"] for w in result])

    def test_superscript_direction_does_not_attach(self) -> None:
        words = _subscript_page(
            [("Nominal", 50, 100), ("current", 105, 150), ("(I", 155, 168),
             ("value", 178, 220), ("of", 225, 240)],
            _cand("n", 169, 173, top=96.0),   # 明显位于主词上方 = 上标/引文
        )
        result, events = _reattach_subscripts(words)
        self.assertEqual(events, [])
        self.assertIn("n", [w["text"] for w in result])

    def test_long_small_text_is_not_a_candidate(self) -> None:
        words = _subscript_page(
            [("Nominal", 50, 100), ("current", 105, 150), ("(I", 155, 168),
             ("value", 178, 220), ("of", 225, 240)],
            _cand("iation", 169, 200),   # 6 字符小字号正文，禁止当候选
        )
        result, events = _reattach_subscripts(words)
        self.assertEqual(events, [])
        self.assertIn("iation", [w["text"] for w in result])

    def test_g1_digit_after_punctuation_is_footnote(self) -> None:
        words = _subscript_page(
            [("commercial", 50, 110), ("operation.", 115, 175), ("shall", 180, 220),
             ("begin", 225, 265), ("soon", 270, 310)],
            _cand("2", 176, 180),
        )
        result, events = _reattach_subscripts(words)
        self.assertEqual(events, [])
        self.assertIn("operation.", [w["text"] for w in result])
        self.assertIn("2", [w["text"] for w in result])

    def test_g2_all_cjk_page_skipped(self) -> None:
        words = [
            _word("电表", 50, 80, 100, 112),
            _word("应当", 85, 115, 100, 112),
            _word("支持", 120, 150, 100, 112),
            _word("记录", 155, 185, 100, 112),
            _word("事件", 190, 220, 100, 112),
            _cand("项", 186, 190),   # CJK 小字号词
        ]
        result, events = _reattach_subscripts(words)
        self.assertEqual(events, [])
        self.assertEqual(len(result), 6)

    def test_mixed_cjk_latin_page_not_skipped(self) -> None:
        words = [
            _word("电表", 50, 80, 100, 112),
            _word("Nominal", 85, 135, 100, 112),
            _word("current", 140, 190, 100, 112),
            _word("(I", 195, 208, 100, 112),
            _word("value", 218, 260, 100, 112),
            _cand("n", 209, 213),
        ]
        result, events = _reattach_subscripts(words)
        self.assertEqual(len(events), 1)
        self.assertIn("(In", [w["text"] for w in result])

    def test_g2_vertical_page_skipped(self) -> None:
        words = [
            _word("Nominal", 50, 100, 100, 112, upright=False),
            _word("current", 105, 150, 100, 112, upright=False),
            _word("(I", 155, 168, 100, 112),
            _word("value", 178, 220, 100, 112),
            _word("of", 225, 240, 100, 112),
            _cand("n", 169, 173),
        ]
        result, events = _reattach_subscripts(words)   # 竖排占比 2/6 ≈ 0.33 ≥ 0.3
        self.assertEqual(events, [])
        self.assertIn("n", [w["text"] for w in result])

    def test_missing_size_leaves_words_untouched(self) -> None:
        words = [
            _word("Nominal", 50, 100, 100, 112, size=None),
            _word("(I", 105, 118, 100, 112, size=None),
            _word("n", 119, 123, 103.5, 111, size=None),
        ]
        result, events = _reattach_subscripts(words)
        self.assertEqual(events, [])
        self.assertEqual([w["text"] for w in result], ["Nominal", "(I", "n"])

    def test_input_words_are_not_mutated(self) -> None:
        words = _subscript_page(
            [("Nominal", 50, 100), ("current", 105, 150), ("(I", 155, 168),
             ("value", 178, 220), ("of", 225, 240)],
            _cand("n", 169, 173),
        )
        before = json.dumps(words, sort_keys=True)
        _reattach_subscripts(words)
        self.assertEqual(json.dumps(words, sort_keys=True), before)

    def test_long_small_word_is_not_a_main_target(self) -> None:
        # 长小字号正文（不满足短候选规则）必须原样保留，但不得接收下标候选
        words = _subscript_page(
            [("Nominal", 50, 100), ("current", 105, 150), ("value", 178, 220),
             ("of", 225, 240), ("rating", 245, 290)],
            _cand("n", 172, 176),
        )
        small_long = _word("appendix", 152, 170, 103.5, 111, size=9.0)
        words.insert(5, small_long)
        result, events = _reattach_subscripts(words)
        self.assertEqual(events, [])
        texts = [w["text"] for w in result]
        self.assertIn("appendix", texts)   # 原样保留
        self.assertIn("n", texts)          # 候选未粘附、未被吞掉

    def test_missing_size_word_is_not_a_main_target(self) -> None:
        # 缺 size 的词同样不得成为粘附目标（无字号证据不满足主词门槛）
        words = _subscript_page(
            [("Nominal", 50, 100), ("current", 105, 150), ("value", 178, 220),
             ("of", 225, 240), ("rating", 245, 290)],
            _cand("n", 172, 176),
        )
        no_size = _word("note", 152, 170, 100, 112, size=None)
        words.insert(5, no_size)
        result, events = _reattach_subscripts(words)
        self.assertEqual(events, [])
        texts = [w["text"] for w in result]
        self.assertIn("note", texts)
        self.assertIn("n", texts)

    def test_existing_layout_events_list_is_not_shared_with_caller(self) -> None:
        # 输入词已有 _layout_events 列表时，拼接新事件不得反向污染调用方持有的列表
        words = _subscript_page(
            [("Nominal", 50, 100), ("current", 105, 150), ("(I", 155, 168),
             ("value", 178, 220), ("of", 225, 240)],
            _cand("n", 169, 173),
        )
        sentinel = {"rule": "prior_layout_event"}
        caller_events = [sentinel]
        words[2]["_layout_events"] = caller_events
        result, events = _reattach_subscripts(words)
        self.assertEqual(len(events), 1)
        self.assertEqual(caller_events, [sentinel])   # 调用方列表未被 append
        attached = next(w for w in result if w["text"] == "(In")
        self.assertEqual(len(attached["_layout_events"]), 2)
        self.assertIs(attached["_layout_events"][0], sentinel)


class HyphenLineJoinTests(unittest.TestCase):
    def test_lowercase_continuation_drops_hyphen(self) -> None:
        joined, event = _join_lines_text("require-", "ments", hyphen_fix=True)
        self.assertEqual(joined, "requirements")
        self.assertIsNotNone(event)
        self.assertEqual(event["rule"], "hyphen_line_join")
        self.assertEqual(event["rule_version"], PDF_HYPHEN_JOIN_VERSION)
        self.assertEqual(event["before"], "require- ments")
        self.assertEqual(event["after"], "requirements")

    def test_digit_continuation_keeps_hyphen(self) -> None:
        joined, event = _join_lines_text("5685-", "1", hyphen_fix=True)
        self.assertEqual(joined, "5685-1")
        self.assertIsNotNone(event)
        joined2, event2 = _join_lines_text("IEC-", "62056", hyphen_fix=True)
        self.assertEqual(joined2, "IEC-62056")
        self.assertIsNotNone(event2)

    def test_g4_dash_after_space_does_not_join(self) -> None:
        joined, event = _join_lines_text("said -", "the", hyphen_fix=True)
        self.assertEqual(joined, "said - the")
        self.assertIsNone(event)

    def test_direct_connected_word_unchanged(self) -> None:
        joined, event = _join_lines_text("direct-connected", "mode", hyphen_fix=True)
        self.assertEqual(joined, "direct-connected mode")
        self.assertIsNone(event)

    def test_uppercase_start_does_not_join(self) -> None:
        joined, event = _join_lines_text("end-", "Next", hyphen_fix=True)
        self.assertEqual(joined, "end- Next")
        self.assertIsNone(event)

    def test_legacy_off_semantics_byte_identical(self) -> None:
        # OFF：旧版只认小写续行去连字符，且不产事件；数字续行不拼
        joined, event = _join_lines_text("require-", "ments", hyphen_fix=False)
        self.assertEqual((joined, event), ("requirements", None))
        joined2, event2 = _join_lines_text("5685-", "1", hyphen_fix=False)
        self.assertEqual((joined2, event2), ("5685- 1", None))

    def test_merge_lines_records_event_once_and_marks_checked(self) -> None:
        lines = [
            _line("require-", 100),
            _line("ments shall apply.", 115),
        ]
        merged = _merge_lines(lines, hyphen_fix=True)
        self.assertEqual(merged["text"], "requirements shall apply.")
        self.assertTrue(merged["text_repair_checked"])
        repairs = merged["text_repairs"]
        self.assertEqual([e["rule"] for e in repairs], ["hyphen_line_join"])
        self.assertEqual(repairs[0]["line_index"], 1)
        # 无 defrag 时 raw 与 text 同通道拼接，对齐为 identity
        self.assertEqual(merged["raw_text"], merged["text"])

    def test_merge_lines_digit_continuation(self) -> None:
        lines = [
            _line("British Standard BS 5685-", 100),
            _line("1 and commonly used.", 115),
        ]
        merged = _merge_lines(lines, hyphen_fix=True)
        self.assertEqual(merged["text"], "British Standard BS 5685-1 and commonly used.")
        self.assertEqual([e["rule"] for e in merged["text_repairs"]], ["hyphen_line_join"])

    def test_merge_lines_off_has_no_repair_fields(self) -> None:
        lines = [
            _line("British Standard BS 5685-", 100),
            _line("1 and commonly used.", 115),
        ]
        merged = _merge_lines(lines, hyphen_fix=False)
        self.assertEqual(merged["text"], "British Standard BS 5685- 1 and commonly used.")
        self.assertNotIn("text_repair_checked", merged)
        self.assertNotIn("text_repairs", merged)

    def test_large_gap_digit_continuation_stays_one_paragraph(self) -> None:
        previous = _line("British Standard BS 5685-", 200, bottom=210)
        line = _line("1 and commonly used in practice.", 230)   # gap = 20（>=12 切段带）
        self.assertFalse(_starts_new_paragraph(
            previous, line,
            page_height=800.0, document_profile=DEFAULT_DOCUMENT_PROFILE,
            hyphen_fix=True,
        ))
        # OFF 时维持旧版切段
        self.assertTrue(_starts_new_paragraph(
            previous, line,
            page_height=800.0, document_profile=DEFAULT_DOCUMENT_PROFILE,
            hyphen_fix=False,
        ))

    def test_g4_dash_digit_still_splits_paragraph(self) -> None:
        previous = _line("as said -", 200, bottom=210)
        line = _line("1 more item follows here.", 230)
        self.assertTrue(_starts_new_paragraph(
            previous, line,
            page_height=800.0, document_profile=DEFAULT_DOCUMENT_PROFILE,
            hyphen_fix=True,
        ))

    def test_cross_page_digit_continuation_merges_with_audit(self) -> None:
        first = {
            "block_id": "BLK-000001", "type": "paragraph",
            "text": "British Standard BS 5685-",
            "raw_text": "British Standard BS 5685-",
            "section_path": ["3 Definitions"], "page_number": 6,
            "noise": False, "pdf_regions": [{"page": 6, "id": "BLK-000001"}],
        }
        second = {
            "block_id": "BLK-000002", "type": "paragraph",
            "text": "1 and commonly used in practice.",
            "raw_text": "1 and commonly used in practice.",
            "section_path": ["3 Definitions"], "page_number": 7,
            "noise": False, "pdf_regions": [{"page": 7, "id": "BLK-000002"}],
        }
        merged = _merge_continuation_blocks([first, second], KB, hyphen_fix=True)
        self.assertEqual(len(merged), 1)
        target = merged[0]
        self.assertEqual(
            target["text"], "British Standard BS 5685-1 and commonly used in practice.")
        events = [e for e in target["text_repairs"] if e["rule"] == "hyphen_line_join"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["page_number"], 6)
        self.assertEqual(events[0]["next_page_number"], 7)
        self.assertEqual(events[0]["rule_version"], PDF_HYPHEN_JOIN_VERSION)
        self.assertTrue(target["text_repair_checked"])
        self.assertTrue(target["text_repaired"])
        # 跨页合并后重算现有字段
        self.assertIn("requirement_like", target)
        self.assertIn("kb_matches", target)
        self.assertIn("domain_tags", target)
        # raw 通道同 layout join → identity 对齐
        validate_source_alignment(
            target["raw_text"], target["text"], target["source_alignment"])

    def test_cross_page_lowercase_join_records_event(self) -> None:
        first = {
            "block_id": "BLK-000001", "type": "paragraph",
            "text": "The meter require-", "raw_text": "The meter require-",
            "section_path": ["4"], "page_number": 6, "noise": False,
            "pdf_regions": [{"page": 6, "id": "BLK-000001"}],
        }
        second = {
            "block_id": "BLK-000002", "type": "paragraph",
            "text": "ments shall apply.", "raw_text": "ments shall apply.",
            "section_path": ["4"], "page_number": 7, "noise": False,
            "pdf_regions": [{"page": 7, "id": "BLK-000002"}],
        }
        merged = _merge_continuation_blocks([first, second], KB, hyphen_fix=True)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["text"], "The meter requirements shall apply.")
        events = [e for e in merged[0]["text_repairs"] if e["rule"] == "hyphen_line_join"]
        self.assertEqual(len(events), 1)

    def test_cross_page_off_digit_does_not_merge(self) -> None:
        first = {
            "block_id": "BLK-000001", "type": "paragraph",
            "text": "British Standard BS 5685-",
            "section_path": ["3"], "page_number": 6, "noise": False,
            "pdf_regions": [{"page": 6, "id": "BLK-000001"}],
        }
        second = {
            "block_id": "BLK-000002", "type": "paragraph",
            "text": "1 and commonly used.",
            "section_path": ["3"], "page_number": 7, "noise": False,
            "pdf_regions": [{"page": 7, "id": "BLK-000002"}],
        }
        merged = _merge_continuation_blocks([first, second], KB, hyphen_fix=False)
        self.assertEqual(len(merged), 2)

    def test_outdented_digit_heading_still_splits(self) -> None:
        # "Scope-" + 明显左凸（>=8pt）的 "1 Introduction" 是强新段边界，不得用数字续行豁免
        previous = _line("The document Scope-", 200, bottom=210, x0=100.0)
        outdented = _line("1 Introduction", 230, x0=50.0)
        self.assertTrue(_starts_new_paragraph(
            previous, outdented,
            page_height=800.0, document_profile=DEFAULT_DOCUMENT_PROFILE,
            hyphen_fix=True,
        ))
        # 同列（未左凸）的合法数字续行仍然合并
        same_column = _line("1 Introduction", 230, x0=100.0)
        self.assertFalse(_starts_new_paragraph(
            previous, same_column,
            page_height=800.0, document_profile=DEFAULT_DOCUMENT_PROFILE,
            hyphen_fix=True,
        ))

    def test_cross_page_digit_non_adjacent_pages_rejected(self) -> None:
        # 数字续行只允许相邻页：页 6→8 不得合并
        first = {
            "block_id": "BLK-000001", "type": "paragraph",
            "text": "British Standard BS 5685-",
            "section_path": ["3"], "page_number": 6, "noise": False,
            "pdf_regions": [{"page": 6, "id": "BLK-000001"}],
        }
        second = {
            "block_id": "BLK-000002", "type": "paragraph",
            "text": "1 and commonly used.",
            "section_path": ["3"], "page_number": 8, "noise": False,
            "pdf_regions": [{"page": 8, "id": "BLK-000002"}],
        }
        merged = _merge_continuation_blocks([first, second], KB, hyphen_fix=True)
        self.assertEqual(len(merged), 2)

    def test_cross_page_digit_section_mismatch_rejected(self) -> None:
        # 数字续行要求 section_path 一致：section A→B 不得合并
        first = {
            "block_id": "BLK-000001", "type": "paragraph",
            "text": "British Standard BS 5685-",
            "section_path": ["3 Definitions"], "page_number": 6, "noise": False,
            "pdf_regions": [{"page": 6, "id": "BLK-000001"}],
        }
        second = {
            "block_id": "BLK-000002", "type": "paragraph",
            "text": "1 and commonly used.",
            "section_path": ["4 Requirements"], "page_number": 7, "noise": False,
            "pdf_regions": [{"page": 7, "id": "BLK-000002"}],
        }
        merged = _merge_continuation_blocks([first, second], KB, hyphen_fix=True)
        self.assertEqual(len(merged), 2)

    def test_three_page_chain_records_actual_break_pages(self) -> None:
        # page1 普通小写续到 page2，page2 末尾 "IEC-" 再接 page3 "62056…"——
        # 第二次 D2 事件必须记录真实断点 2→3，而不是 target 最初页 1
        first = {
            "block_id": "BLK-000001", "type": "paragraph",
            "text": "First part of the",
            "section_path": ["4"], "page_number": 1, "noise": False,
            "pdf_regions": [{"page": 1, "id": "BLK-000001"}],
        }
        second = {
            "block_id": "BLK-000002", "type": "paragraph",
            "text": "second part ends with IEC-",
            "section_path": ["4"], "page_number": 2, "noise": False,
            "pdf_regions": [{"page": 2, "id": "BLK-000002"}],
        }
        third = {
            "block_id": "BLK-000003", "type": "paragraph",
            "text": "62056 series applies here.",
            "section_path": ["4"], "page_number": 3, "noise": False,
            "pdf_regions": [{"page": 3, "id": "BLK-000003"}],
        }
        merged = _merge_continuation_blocks([first, second, third], KB, hyphen_fix=True)
        self.assertEqual(len(merged), 1)
        target = merged[0]
        self.assertEqual(
            target["text"],
            "First part of the second part ends with IEC-62056 series applies here.")
        events = [e for e in target["text_repairs"] if e["rule"] == "hyphen_line_join"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["page_number"], 2)
        self.assertEqual(events[0]["next_page_number"], 3)

    def test_same_page_event_carries_page_number(self) -> None:
        # 同页 D2 事件与跨页同字段语义：生产路径传入实际页码时必须写入 page_number
        lines = [
            _line("British Standard BS 5685-", 100),
            _line("1 and commonly used.", 115),
        ]
        merged = _merge_lines(lines, hyphen_fix=True, page_number=9)
        events = [e for e in merged["text_repairs"] if e["rule"] == "hyphen_line_join"]
        self.assertEqual(len(events), 1)   # event-once 行为不变（raw 通道不重复记）
        self.assertEqual(events[0]["page_number"], 9)
        self.assertNotIn("next_page_number", events[0])   # 同页无跨页字段
        self.assertEqual(events[0]["line_index"], 1)
        # 直接调用不传 page_number 保持兼容：事件可缺 page_number
        merged_compat = _merge_lines(lines, hyphen_fix=True)
        events_compat = [
            e for e in merged_compat["text_repairs"] if e["rule"] == "hyphen_line_join"
        ]
        self.assertEqual(len(events_compat), 1)
        self.assertNotIn("page_number", events_compat[0])


class AuditDecouplingTests(unittest.TestCase):
    def test_defrag_and_layout_events_coexist_and_replay_matches(self) -> None:
        # defrag 行（raw 含碎词）+ D2 断行连字符：最终 text_repairs 必须同时含
        # hyphen_line_join 事件与段落级 defrag 事件，且 defrag 从 merged_raw_text
        # 重放结果等于最终 text（source_spans 可重放性不变）。
        lines = [
            _line("The meter i s require-", 100,
                  raw_text="The meter i s require-", text_repair_checked=True),
            _line("ments shall apply.", 115,
                  raw_text="ments shall apply.", text_repair_checked=True),
        ]
        merged = _merge_lines(lines, hyphen_fix=True)
        rules = [e["rule"] for e in merged["text_repairs"]]
        self.assertIn("hyphen_line_join", rules)
        self.assertTrue(any(rule != "hyphen_line_join" for rule in rules))
        self.assertEqual(merged["text"], "The meter is requirements shall apply.")
        # 用最终 raw/text 重建对齐并重放验证
        fields = source_alignment_fields(
            merged["raw_text"], merged["text"],
            repair_provenance=_source_repair_provenance(),
        )
        validate_source_alignment(
            merged["raw_text"], merged["text"], fields["source_alignment"])
        self.assertTrue(source_alignment_is_approved(
            merged["raw_text"], merged["text"], fields["source_alignment"]))

    def test_layout_event_survives_defrag_replay(self) -> None:
        # D1 版式事件（layout_events 随词入行）在 defrag 重放下不得丢失
        d1_event = {
            "rule": "subscript_reattach",
            "rule_version": PDF_SUBSCRIPT_REATTACH_VERSION,
            "before": "(I n", "after": "(In",
            "position_basis": "word_geometry",
        }
        lines = [
            _line("(In value i s fixed.", 100,
                  raw_text="(In value i s fixed.",
                  text_repair_checked=True, layout_events=[d1_event]),
        ]
        merged = _merge_lines(lines, hyphen_fix=True)
        rules = [e["rule"] for e in merged["text_repairs"]]
        self.assertIn("subscript_reattach", rules)
        self.assertEqual(merged["text"], "(In value is fixed.")

    def test_layout_only_event_enters_quality_report_rules(self) -> None:
        lines = [_line("require-", 100), _line("ments shall apply.", 115)]
        merged = _merge_lines(lines, hyphen_fix=True)
        block = {
            "block_id": "BLK-000001", "type": "paragraph", "text": merged["text"],
            "text_repair_checked": True, "text_repaired": True,
            "text_repair_version": PDF_TEXT_REPAIR_VERSION,
            "text_repairs": merged["text_repairs"],
            "text_repair_words_before": merged["text_repair_words_before"],
            "text_repair_words_after": merged["text_repair_words_after"],
            "text_repair_candidates_before": merged["text_repair_candidates_before"],
            "text_repair_candidates_after": merged["text_repair_candidates_after"],
        }
        report = build_quality_report([block], [], [], [])
        self.assertEqual(
            report["text_hygiene"]["repair_rules"], {"hyphen_line_join": 1})
        self.assertEqual(report["text_hygiene"]["checked_blocks"], 1)
        self.assertEqual(report["text_hygiene"]["repaired_blocks"], 1)

    def test_merge_words_carries_layout_events(self) -> None:
        words = [
            _word("(In", 50, 70, 100, 112),
            _word("applies", 75, 130, 100, 112),
        ]
        words[0]["_layout_events"] = [{
            "rule": "subscript_reattach",
            "rule_version": PDF_SUBSCRIPT_REATTACH_VERSION,
            "before": "(I n", "after": "(In",
            "position_basis": "word_geometry",
        }]
        line = _merge_words(words)
        self.assertEqual(line["text"], "(In applies")
        self.assertEqual(len(line["layout_events"]), 1)

    def test_d2_only_alignment_provenance_is_none(self) -> None:
        # D2-only 跨页合并：raw==text 的 identity 对齐不得伪挂 defrag provenance
        first = {
            "block_id": "BLK-000001", "type": "paragraph",
            "text": "British Standard BS 5685-",
            "raw_text": "British Standard BS 5685-",
            "section_path": ["3"], "page_number": 6, "noise": False,
            "pdf_regions": [{"page": 6, "id": "BLK-000001"}],
        }
        second = {
            "block_id": "BLK-000002", "type": "paragraph",
            "text": "1 and commonly used.",
            "raw_text": "1 and commonly used.",
            "section_path": ["3"], "page_number": 7, "noise": False,
            "pdf_regions": [{"page": 7, "id": "BLK-000002"}],
        }
        merged = _merge_continuation_blocks([first, second], KB, hyphen_fix=True)
        self.assertEqual(len(merged), 1)
        target = merged[0]
        self.assertTrue(target["text_repair_checked"])
        self.assertEqual(target["raw_text"], target["text"])
        self.assertIsNone(target["source_alignment"]["repair_provenance"])
        validate_source_alignment(
            target["raw_text"], target["text"], target["source_alignment"])

    def test_d2_plus_defrag_keeps_defrag_provenance_and_replays(self) -> None:
        # defrag 实跑（raw!=text）+ D2 拼接：provenance 必须保留且 replay 仍通过
        first = {
            "block_id": "BLK-000001", "type": "paragraph",
            "text": "The meter is require-", "raw_text": "The meter i s require-",
            "section_path": ["4"], "page_number": 6, "noise": False,
            "text_repair_checked": True,
            "text_repair_version": PDF_TEXT_REPAIR_VERSION,
            "text_repairs": [{"rule": "wordlist_fragment_repair"}],
            "pdf_regions": [{"page": 6, "id": "BLK-000001"}],
        }
        second = {
            "block_id": "BLK-000002", "type": "paragraph",
            "text": "ments apply here.", "raw_text": "ments apply here.",
            "section_path": ["4"], "page_number": 7, "noise": False,
            "pdf_regions": [{"page": 7, "id": "BLK-000002"}],
        }
        merged = _merge_continuation_blocks([first, second], KB, hyphen_fix=True)
        self.assertEqual(len(merged), 1)
        target = merged[0]
        self.assertNotEqual(target["raw_text"], target["text"])
        self.assertIsNotNone(target["source_alignment"]["repair_provenance"])
        validate_source_alignment(
            target["raw_text"], target["text"], target["source_alignment"])
        self.assertTrue(source_alignment_is_approved(
            target["raw_text"], target["text"], target["source_alignment"]))

    def test_list_merge_layout_only_provenance_is_none(self) -> None:
        # 清单合并：成员仅带 layout 事件（raw==text）时 target 与成员对齐均不挂 provenance
        layout_event = {
            "rule": "subscript_reattach",
            "rule_version": PDF_SUBSCRIPT_REATTACH_VERSION,
            "before": "(I n", "after": "(In",
            "position_basis": "word_geometry",
        }
        blocks = []
        for bid, text in (("BLK-000001", "- Alpha terminal"),
                          ("BLK-000002", "- Beta terminal")):
            blocks.append({
                "block_id": bid, "type": "paragraph", "text": text, "raw_text": text,
                "section_path": ["3.4.4 Marking"], "page_number": 6, "noise": False,
                "requirement_like": False,
                "text_repair_checked": True,
                "text_repair_version": PDF_TEXT_REPAIR_VERSION,
                "text_repairs": [dict(layout_event)],
                "pdf_regions": [{"page": 6, "id": bid}],
            })
        merged = _merge_list_item_blocks(blocks, KB)
        self.assertEqual(len(merged), 1)
        target = merged[0]
        self.assertTrue(target["text_repair_checked"])
        self.assertEqual(target["raw_text"], target["text"])
        self.assertIsNone(target["source_alignment"]["repair_provenance"])
        for member in target["list_items"]:
            self.assertIsNone(member["source_alignment"]["repair_provenance"])

    def test_identity_defrag_keeps_provenance_through_merge_lines_and_append(self) -> None:
        # defrag 实跑但零事件/零净变化（干净文本，text_repair_checked=True）：
        # raw==text 的 identity 对齐仍必须挂当前 provenance（stale producer/vocabulary
        # 检查依赖它，见 source_spans 的 test_stale_pdf_provenance_is_rejected_
        # even_when_text_is_identity），不得靠 raw!=text/事件猜而误判未运行；
        # 且 _merge_lines 的内部 _defrag_ran 标志不得泄漏进最终 block
        lines = [
            _line("The meter shall record events.", 100, text_repair_checked=True),
            _line("It shall also store the load profiles.", 115, text_repair_checked=True),
        ]
        paragraph = _merge_lines(lines, hyphen_fix=True)
        defrag_ran = paragraph.pop("_defrag_ran", None)
        self.assertTrue(defrag_ran)   # _merge_lines 显式传播 defrag 实跑真相
        blocks: list[dict] = []
        _append_text_block(
            blocks,
            paragraph["text"],
            order=0,
            page_number=6,
            sections=SectionState(),
            knowledge_bases=KB,
            repeated_noise=set(),
            last_caption=None,
            profile=DEFAULT_DOCUMENT_PROFILE,
            raw_text=paragraph.get("raw_text"),
            text_repairs=paragraph.get("text_repairs") or [],
            text_repair_checked=bool(paragraph.get("text_repair_checked")),
            defrag_ran=defrag_ran,
        )
        self.assertEqual(len(blocks), 1)
        block = blocks[0]
        self.assertEqual(block["raw_text"], block["text"])   # identity 对齐
        self.assertIsNotNone(block["source_alignment"]["repair_provenance"])
        validate_source_alignment(
            block["raw_text"], block["text"], block["source_alignment"])
        self.assertTrue(source_alignment_is_approved(
            block["raw_text"], block["text"], block["source_alignment"]))
        self.assertNotIn("_defrag_ran", block)   # 内部标志不泄漏为最终字段

    def test_list_merge_preserves_identity_defrag_provenance(self) -> None:
        # 输入成员是 identity defrag 块（raw==text、零事件，既有对齐已挂真实
        # provenance）：合并后 target 与 member 条目都必须保留 defrag provenance
        blocks = []
        for bid, text in (("BLK-000001", "- Alpha terminal"),
                          ("BLK-000002", "- Beta terminal")):
            alignment = source_alignment_fields(
                text, text, repair_provenance=_source_repair_provenance())
            blocks.append({
                "block_id": bid, "type": "paragraph", "text": text, "raw_text": text,
                "section_path": ["3.4.4 Marking"], "page_number": 6, "noise": False,
                "requirement_like": False,
                "text_repair_checked": True,
                "text_repair_version": PDF_TEXT_REPAIR_VERSION,
                "text_repairs": [],
                "pdf_regions": [{"page": 6, "id": bid}],
                "source_alignment": alignment["source_alignment"],
            })
        merged = _merge_list_item_blocks(blocks, KB)
        self.assertEqual(len(merged), 1)
        target = merged[0]
        self.assertEqual(target["raw_text"], target["text"])   # identity 合并
        self.assertIsNotNone(target["source_alignment"]["repair_provenance"])
        validate_source_alignment(
            target["raw_text"], target["text"], target["source_alignment"])
        for member in target["list_items"]:
            self.assertIsNotNone(member["source_alignment"]["repair_provenance"])

    def test_continuation_merge_preserves_identity_defrag_provenance(self) -> None:
        # 跨页续行合并：前段是 identity defrag 块（对齐已挂 provenance）时，
        # 合并 target 仍必须携带 defrag provenance（修改 target 前捕获的证据）
        first_alignment = source_alignment_fields(
            "First part of the", "First part of the",
            repair_provenance=_source_repair_provenance())
        first = {
            "block_id": "BLK-000001", "type": "paragraph",
            "text": "First part of the", "raw_text": "First part of the",
            "section_path": ["4"], "page_number": 6, "noise": False,
            "text_repair_checked": True,
            "text_repair_version": PDF_TEXT_REPAIR_VERSION,
            "text_repairs": [],
            "pdf_regions": [{"page": 6, "id": "BLK-000001"}],
            "source_alignment": first_alignment["source_alignment"],
        }
        second = {
            "block_id": "BLK-000002", "type": "paragraph",
            "text": "second part follows here.", "raw_text": "second part follows here.",
            "section_path": ["4"], "page_number": 7, "noise": False,
            "pdf_regions": [{"page": 7, "id": "BLK-000002"}],
        }
        merged = _merge_continuation_blocks([first, second], KB, hyphen_fix=True)
        self.assertEqual(len(merged), 1)
        target = merged[0]
        self.assertEqual(target["raw_text"], target["text"])
        self.assertIsNotNone(target["source_alignment"]["repair_provenance"])
        validate_source_alignment(
            target["raw_text"], target["text"], target["source_alignment"])
        self.assertTrue(source_alignment_is_approved(
            target["raw_text"], target["text"], target["source_alignment"]))


class HeadingSplitAuditPartitionTests(unittest.TestCase):
    """P2：粘连标题拆分（标题块 + 正文块）的审计事件划分、侧级 checked 与指标重算。

    侧级语义（2026-08-09 三轮）：defrag 实跑的拆分两侧恒 checked（即使侧级零事件）；
    layout-only 拆分只有拥有事件的一侧 checked——未 checked 一侧不写任何
    text_repair_* 键，质量报告只聚合 checked 侧。
    """

    _GLUED = ("4.2.7 Service: Software Update The service must allow remote updates "
              "and record every attempt")
    _HEADING = "4.2.7 Service: Software Update"
    _BODY = "The service must allow remote updates and record every attempt"

    def _append(self, text_repairs: list[dict]) -> list[dict]:
        blocks: list[dict] = []
        _append_text_block(
            blocks,
            self._GLUED,
            order=0,
            page_number=6,
            sections=SectionState(),
            knowledge_bases=KB,
            repeated_noise=set(),
            last_caption=None,
            profile=DEFAULT_DOCUMENT_PROFILE,
            text_repairs=text_repairs,
            text_repair_checked=True,
            # 模拟生产通道（_merge_lines 段落级聚合指标）——拆分后 checked 侧必须按
            # 自身 raw/repaired 重算，不得继承这组整段聚合值造成双计
            text_repair_words_before=999,
            text_repair_words_after=998,
            text_repair_candidates_before=7,
            text_repair_candidates_after=3,
            defrag_ran=False,   # layout-only：identity 对齐 provenance=None 行为不变
        )
        return blocks

    def test_split_partitions_layout_event_to_body_side(self) -> None:
        # D2 事件证据唯一落在正文侧 → 只归正文块；layout-only 拆分中无事件的
        # 标题侧不 checked（一个 text_repair_* 键都不写），质量报告只聚合正文侧
        d2_event = {
            "rule": "hyphen_line_join",
            "rule_version": PDF_HYPHEN_JOIN_VERSION,
            "before": "remote upd- ates",
            "after": "remote updates",
            "position_basis": "line_layout",
        }
        blocks = self._append([dict(d2_event)])
        self.assertEqual(len(blocks), 2)
        heading_block, body_block = blocks
        self.assertEqual(heading_block["text"], self._HEADING)
        self.assertNotIn("text_repair_checked", heading_block)
        self.assertNotIn("text_repairs", heading_block)
        self.assertNotIn("text_repaired", heading_block)
        self.assertEqual(
            [e["rule"] for e in body_block["text_repairs"]], ["hyphen_line_join"])
        self.assertIn("remote updates", body_block["text"])
        self.assertTrue(body_block["text_repaired"])
        # 指标按正文自身 raw/repaired 重算，整段聚合值（999/998/7/3）不双计
        self.assertEqual(
            body_block["text_repair_words_after"], len(self._BODY.split()))
        self.assertEqual(
            body_block["text_repair_words_before"],
            len(body_block["raw_text"].split()))
        self.assertEqual(
            body_block["text_repair_candidates_after"],
            _fragmentation_signal_count(self._BODY))
        report = build_quality_report([heading_block, body_block], [], [], [])
        hygiene = report["text_hygiene"]
        self.assertEqual(hygiene["checked_blocks"], 1)
        self.assertEqual(hygiene["repaired_blocks"], 1)
        self.assertEqual(hygiene["repairs"], 1)
        self.assertEqual(hygiene["repair_rules"], {"hyphen_line_join": 1})
        self.assertEqual(hygiene["suspected_fragments_before"], 0)
        self.assertEqual(hygiene["suspected_fragments_after"], 0)

    def test_split_partitions_layout_event_to_heading_side(self) -> None:
        # 证据唯一命中标题侧时归标题块——证明归属判定不是永远给正文；
        # 无事件的正文侧不 checked
        d1_event = {
            "rule": "subscript_reattach",
            "rule_version": PDF_SUBSCRIPT_REATTACH_VERSION,
            "before": "Software Updat e",
            "after": "Software Update",
            "position_basis": "word_geometry",
        }
        blocks = self._append([dict(d1_event)])
        self.assertEqual(len(blocks), 2)
        heading_block, body_block = blocks
        self.assertEqual(
            [e["rule"] for e in heading_block["text_repairs"]], ["subscript_reattach"])
        self.assertTrue(heading_block["text_repaired"])
        self.assertIn("Software Update", heading_block["text"])
        self.assertEqual(
            heading_block["text_repair_words_before"],
            len(heading_block["raw_text"].split()))
        self.assertEqual(
            heading_block["text_repair_words_after"],
            len(self._HEADING.split()))
        self.assertNotIn("text_repair_checked", body_block)
        self.assertNotIn("text_repairs", body_block)
        report = build_quality_report([heading_block, body_block], [], [], [])
        hygiene = report["text_hygiene"]
        self.assertEqual(hygiene["checked_blocks"], 1)
        self.assertEqual(hygiene["repaired_blocks"], 1)
        self.assertEqual(hygiene["repairs"], 1)
        self.assertEqual(hygiene["repair_rules"], {"subscript_reattach": 1})

    def test_split_ambiguous_event_gets_single_conservative_owner(self) -> None:
        # 无位点事件证据双侧落空（跨缝拼接视图）→ 保守归正文一侧，绝不两块各一份
        spanning_event = {
            "rule": "hyphen_line_join",
            "rule_version": PDF_HYPHEN_JOIN_VERSION,
            "before": "Update The- service",
            "after": "Update The- service joined across the split",
            "position_basis": "line_layout",
        }
        blocks = self._append([dict(spanning_event)])
        self.assertEqual(len(blocks), 2)
        heading_block, body_block = blocks
        self.assertNotIn("text_repairs", heading_block)
        self.assertEqual(body_block["text_repairs"], [spanning_event])
        report = build_quality_report([heading_block, body_block], [], [], [])
        hygiene = report["text_hygiene"]
        self.assertEqual(hygiene["checked_blocks"], 1)
        self.assertEqual(hygiene["repairs"], 1)
        self.assertEqual(hygiene["repair_rules"], {"hyphen_line_join": 1})

    def _append_merged(self, lines: list[dict]) -> list[dict]:
        """生产形态：_merge_lines 段落产物（含内部位点）直接进 _append_text_block。"""
        merged = _merge_lines(lines, hyphen_fix=True, page_number=6)
        blocks: list[dict] = []
        _append_text_block(
            blocks,
            merged["text"],
            order=0,
            page_number=6,
            sections=SectionState(),
            knowledge_bases=KB,
            repeated_noise=set(),
            last_caption=None,
            profile=DEFAULT_DOCUMENT_PROFILE,
            raw_text=merged["raw_text"],
            text_repairs=merged["text_repairs"],
            text_repair_checked=True,
            text_repair_words_before=merged["text_repair_words_before"],
            text_repair_words_after=merged["text_repair_words_after"],
            text_repair_candidates_before=merged["text_repair_candidates_before"],
            text_repair_candidates_after=merged["text_repair_candidates_after"],
            defrag_ran=merged.pop("_defrag_ran"),
        )
        return blocks

    def test_split_d2_event_inside_heading_belongs_to_heading(self) -> None:
        # 生产形态 D2：拼接点在标题内部（"Upd-"+"ate"），但事件 before/after 是
        # 跨未来标题/正文缝的累计快照——子串证据双侧落空会错归正文，内部位点
        # （raw 通道快照最长公共前缀）必须把事件钉在标题侧
        lines = [
            _line("4.2.7 Service: Software Upd-", 100),
            _line("ate The service must allow remote updates", 115),
            _line("and record every attempt", 130),
        ]
        blocks = self._append_merged(lines)
        self.assertEqual(len(blocks), 2)
        heading_block, body_block = blocks
        self.assertEqual(heading_block["text"], self._HEADING)
        self.assertEqual(body_block["text"], self._BODY)
        events = heading_block["text_repairs"]
        self.assertEqual([e["rule"] for e in events], ["hyphen_line_join"])
        event = events[0]
        # 累计快照确实跨缝（含正文词），子串归属必然失败——位点归属的唯一证据
        self.assertIn("remote updates", event["after"])
        self.assertNotIn(event["after"], self._HEADING)
        self.assertEqual(event["page_number"], 6)
        # 内部位点元数据不得泄漏进持久化事件
        self.assertNotIn("_raw_offset", event)
        self.assertTrue(all(not str(k).startswith("_") for e in events for k in e))
        self.assertTrue(heading_block["text_repaired"])
        self.assertNotIn("text_repair_checked", body_block)
        report = build_quality_report([heading_block, body_block], [], [], [])
        hygiene = report["text_hygiene"]
        self.assertEqual(hygiene["checked_blocks"], 1)
        self.assertEqual(hygiene["repaired_blocks"], 1)
        self.assertEqual(hygiene["repairs"], 1)
        self.assertEqual(hygiene["repair_rules"], {"hyphen_line_join": 1})

    def test_split_d1_duplicate_token_owned_by_locus_not_substring(self) -> None:
        # 重复 token：after="Service" 在标题与正文两侧都逐字出现——子串证据歧义
        # 会保守错归正文；行内位点（该行 raw_part 内的出现次序）归标题侧
        d1_event = {
            "rule": "subscript_reattach",
            "rule_version": PDF_SUBSCRIPT_REATTACH_VERSION,
            "before": "Servic e",
            "after": "Service",
            "position_basis": "word_geometry",
        }
        body = ("The service must allow Service continuity checks "
                "and record every attempt")
        lines = [
            _line("4.2.7 Service: Software Update", 100,
                  layout_events=[dict(d1_event)]),
            _line(body, 115),
        ]
        blocks = self._append_merged(lines)
        self.assertEqual(len(blocks), 2)
        heading_block, body_block = blocks
        self.assertIn("Service", body_block["text"])   # 正文确实也含该 token
        events = heading_block["text_repairs"]
        self.assertEqual([e["rule"] for e in events], ["subscript_reattach"])
        self.assertNotIn("_raw_offset", events[0])
        self.assertNotIn("text_repair_checked", body_block)
        report = build_quality_report([heading_block, body_block], [], [], [])
        hygiene = report["text_hygiene"]
        self.assertEqual(hygiene["checked_blocks"], 1)
        self.assertEqual(hygiene["repairs"], 1)
        self.assertEqual(hygiene["repair_rules"], {"subscript_reattach": 1})

    @staticmethod
    def _words_for_line(text: str, event_word_index: int, event: dict) -> list[dict]:
        """把一行文本造成递增 x 的词序列，事件挂在第 event_word_index 个词上。"""
        words: list[dict] = []
        x = 50.0
        for index, token in enumerate(text.split()):
            width = 6.0 * len(token)
            word = _word(token, x, x + width, 100, 112)
            if index == event_word_index:
                word["_layout_events"] = [dict(event)]
            words.append(word)
            x += width + 3.0
        return words

    def test_one_visual_line_d1_event_on_second_duplicate_token(self) -> None:
        # 已确认的生产形态 D1 位点缺陷：同一视觉行内，标题侧 "Service:" 是普通词，
        # 正文侧第二个 "Service" 词才持有事件——raw_part.find 从 0 起搜会命中首次
        # 出现（位点 6，标题内）把事件错归标题、正文失 checked。_merge_words 逐词
        # 顺序定位写下行内精确位点 _line_raw_offset，事件必须归正文侧
        d1_event = {
            "rule": "subscript_reattach",
            "rule_version": PDF_SUBSCRIPT_REATTACH_VERSION,
            "before": "Servic e",
            "after": "Service",
            "position_basis": "word_geometry",
        }
        text = ("4.2.7 Service: Software Update The service must allow Service "
                "continuity checks and record every attempt")
        words = self._words_for_line(text, 8, d1_event)   # 第二个 Service（正文侧）
        line = _merge_words(words, defrag=False)
        # 原词字典不被修改（D1 纪律：输入词对象保持原样）
        self.assertNotIn("_line_raw_offset", words[8]["_layout_events"][0])
        blocks = self._append_merged([line])
        self.assertEqual(len(blocks), 2)
        heading_block, body_block = blocks
        self.assertEqual(heading_block["text"], self._HEADING)
        # 标题侧无任何修复字段
        self.assertNotIn("text_repair_checked", heading_block)
        self.assertNotIn("text_repairs", heading_block)
        # 正文侧独占事件、checked 且 repaired
        self.assertTrue(body_block["text_repair_checked"])
        self.assertTrue(body_block["text_repaired"])
        events = body_block["text_repairs"]
        self.assertEqual([e["rule"] for e in events], ["subscript_reattach"])
        self.assertEqual(events[0]["after"], "Service")
        # 私有定位键不得持久化
        self.assertTrue(all(not str(k).startswith("_") for e in events for k in e))
        report = build_quality_report([heading_block, body_block], [], [], [])
        hygiene = report["text_hygiene"]
        self.assertEqual(hygiene["checked_blocks"], 1)
        self.assertEqual(hygiene["repaired_blocks"], 1)
        self.assertEqual(hygiene["repairs"], 1)
        self.assertEqual(hygiene["repair_rules"], {"subscript_reattach": 1})

    def test_one_visual_line_d1_short_token_not_matched_inside_earlier_word(self) -> None:
        # 短 token 陷阱："In" 是更早普通词 "Input" 的子串——字串搜索会把位点钉进
        # "Input" 内部（标题侧）；逐词定位只认独立词，事件归正文侧
        d1_event = {
            "rule": "subscript_reattach",
            "rule_version": PDF_SUBSCRIPT_REATTACH_VERSION,
            "before": "I n",
            "after": "In",
            "position_basis": "word_geometry",
        }
        text = ("4.2.7 Input configuration The device shall operate In standby "
                "mode and record every attempt event")
        words = self._words_for_line(text, 7, d1_event)   # 独立词 "In"（正文侧）
        line = _merge_words(words, defrag=False)
        blocks = self._append_merged([line])
        self.assertEqual(len(blocks), 2)
        heading_block, body_block = blocks
        self.assertEqual(heading_block["text"], "4.2.7 Input configuration")
        self.assertNotIn("text_repair_checked", heading_block)
        self.assertTrue(body_block["text_repair_checked"])
        self.assertTrue(body_block["text_repaired"])
        self.assertEqual(
            [e["rule"] for e in body_block["text_repairs"]], ["subscript_reattach"])
        report = build_quality_report([heading_block, body_block], [], [], [])
        hygiene = report["text_hygiene"]
        self.assertEqual(hygiene["checked_blocks"], 1)
        self.assertEqual(hygiene["repaired_blocks"], 1)
        self.assertEqual(hygiene["repairs"], 1)
        self.assertEqual(hygiene["repair_rules"], {"subscript_reattach": 1})

    def test_split_d1_event_with_legacy_hyphen_join_goes_to_heading(self) -> None:
        # C-1：D1 开 + D2 关的混合开关下，旧版连字符拼接（去连字符、无空格、无事件）会让
        # _merge_lines 误把 follow 行在段落 raw 中的起点算成 len(old_raw)+1，导致 D1 事件
        # _raw_offset 漂移 +2；真实修复位点在标题侧却被错归正文侧。
        d1_event = {
            "rule": "subscript_reattach",
            "rule_version": PDF_SUBSCRIPT_REATTACH_VERSION,
            "before": "n b",
            "after": "nb",
            "position_basis": "word_geometry",
        }
        body_text = (
            "nb The service must allow remote updates and record every attempt event "
            "for audit trail purposes so that operations can be reviewed"
        )
        line2 = _merge_words(self._words_for_line(body_text, 0, d1_event), defrag=False)
        lines = [
            _line("4.2.7 require-", 100),
            line2,
        ]
        merged = _merge_lines(lines, hyphen_fix=False, page_number=6)
        self.assertEqual(
            merged["raw_text"],
            "4.2.7 requirenb The service must allow remote updates and record every "
            "attempt event for audit trail purposes so that operations can be reviewed",
        )
        event = [e for e in merged["text_repairs"]
                 if e["rule"] == "subscript_reattach"][0]
        # "4.2.7 require-" 长度 14，旧连字符拼接下行真实起点 = 14 - 1 = 13；
        # 旧实现按空格拼接记成 15，位点会越过分割边界。
        self.assertEqual(event["_raw_offset"], 13)

        blocks: list[dict] = []
        _append_text_block(
            blocks,
            merged["text"],
            order=0,
            page_number=6,
            sections=SectionState(),
            knowledge_bases=KB,
            repeated_noise=set(),
            last_caption=None,
            profile=DEFAULT_DOCUMENT_PROFILE,
            raw_text=merged["raw_text"],
            text_repairs=merged["text_repairs"],
            text_repair_checked=True,
            text_repair_words_before=merged["text_repair_words_before"],
            text_repair_words_after=merged["text_repair_words_after"],
            text_repair_candidates_before=merged["text_repair_candidates_before"],
            text_repair_candidates_after=merged["text_repair_candidates_after"],
            defrag_ran=merged.pop("_defrag_ran"),
        )
        self.assertEqual(len(blocks), 2)
        heading_block, body_block = blocks
        self.assertEqual(heading_block["text"], "4.2.7 requirenb")
        self.assertEqual(
            [e["rule"] for e in heading_block["text_repairs"]], ["subscript_reattach"])
        self.assertNotIn("text_repairs", body_block)

    def test_split_dedouble_event_owned_by_heading_side_local_replay(self) -> None:
        # 已确认的 dedouble 复现案例：段落级 defrag transcript 不整体归属任一侧——
        # 两侧各自从 raw 独立重放：标题侧重放出侧级 dedouble 事件且 text_repaired=True；
        # 未变化的正文侧零事件、text_repaired=False；defrag 实跑 → 两侧都 checked
        raw = ("4.2.7 Service: SSooffttwwaarree UUppddaattee "
               "The service must allow remote updates and record every attempt")
        aggregate_event = {
            "rule": "dedouble",
            "start": 0,
            "end": len(raw),
            "before": raw,
            "after": self._GLUED,
            "position_basis": "original_text",
        }
        blocks: list[dict] = []
        _append_text_block(
            blocks,
            self._GLUED,
            order=0,
            page_number=6,
            sections=SectionState(),
            knowledge_bases=KB,
            repeated_noise=set(),
            last_caption=None,
            profile=DEFAULT_DOCUMENT_PROFILE,
            raw_text=raw,
            text_repairs=[dict(aggregate_event)],
            text_repair_checked=True,
            text_repair_words_before=999,
            text_repair_words_after=998,
            text_repair_candidates_before=7,
            text_repair_candidates_after=3,
            defrag_ran=True,
        )
        self.assertEqual(len(blocks), 2)
        heading_block, body_block = blocks
        self.assertEqual(heading_block["text"], self._HEADING)
        self.assertEqual(body_block["text"], self._BODY)
        # 标题侧：侧级重放的 dedouble 事件（before 是标题侧 raw，不是整段聚合视图）
        heading_events = heading_block["text_repairs"]
        self.assertEqual([e["rule"] for e in heading_events], ["dedouble"])
        self.assertIn("SSooffttwwaarree", heading_events[0]["before"])
        self.assertNotIn("record every attempt", heading_events[0]["before"])
        self.assertTrue(heading_block["text_repaired"])
        self.assertTrue(heading_block["text_repair_checked"])
        # 正文侧：raw==text、零事件、未修复——但 defrag 实跑过所以仍 checked
        self.assertEqual(body_block["raw_text"], self._BODY)
        self.assertEqual(body_block["text_repairs"], [])
        self.assertFalse(body_block["text_repaired"])
        self.assertTrue(body_block["text_repair_checked"])
        # 两侧指标按自身 raw/repaired 重算
        self.assertEqual(
            heading_block["text_repair_words_before"],
            len(heading_block["raw_text"].split()))
        self.assertEqual(
            body_block["text_repair_words_after"], len(self._BODY.split()))
        # defrag 实跑两侧都挂 provenance；两侧对齐各自可重放
        for block in (heading_block, body_block):
            alignment = block["source_alignment"]
            self.assertIsNotNone(alignment.get("repair_provenance"))
            validate_source_alignment(block["raw_text"], block["text"], alignment)
        report = build_quality_report([heading_block, body_block], [], [], [])
        hygiene = report["text_hygiene"]
        self.assertEqual(hygiene["checked_blocks"], 2)
        self.assertEqual(hygiene["repaired_blocks"], 1)
        self.assertEqual(hygiene["repairs"], 1)
        self.assertEqual(hygiene["repair_rules"], {"dedouble": 1})

    def test_split_fail_closed_retains_full_paragraph_without_loss(self) -> None:
        # fail-closed：侧级 defrag 重放不能复现该侧 repaired 文本时放弃拆分——
        # 完整保留修复后全文与整段 raw（零丢失），降级为普通段落，
        # 整段聚合事件/指标/checked 维持段落级口径
        raw = ("4.2.7 Service: Software Update The service must allow remote "
               "updates and record every attempt")
        # 正文侧 repaired 与 raw 的差异（EVERY 大写化）不是 defrag 能重放的变换
        repaired = ("4.2.7 Service: Software Update The service must allow remote "
                    "updates and record EVERY attempt")
        aggregate_event = {
            "rule": "dedouble",
            "start": 0,
            "end": len(raw),
            "before": raw,
            "after": repaired,
            "position_basis": "original_text",
        }
        sections = SectionState()
        blocks: list[dict] = []
        _append_text_block(
            blocks,
            repaired,
            order=0,
            page_number=6,
            sections=sections,
            knowledge_bases=KB,
            repeated_noise=set(),
            last_caption=None,
            profile=DEFAULT_DOCUMENT_PROFILE,
            raw_text=raw,
            text_repairs=[dict(aggregate_event)],
            text_repair_checked=True,
            text_repair_words_before=999,
            text_repair_words_after=998,
            text_repair_candidates_before=7,
            text_repair_candidates_after=3,
            defrag_ran=True,
        )
        self.assertEqual(len(blocks), 1)
        block = blocks[0]
        self.assertEqual(block["type"], "paragraph")   # 粘连标题语义不可分→降级
        self.assertEqual(sections.path(), [])   # 未拆出标题，不得推进节树
        self.assertEqual(block["text"], repaired)
        self.assertEqual(block["raw_text"], raw)
        self.assertTrue(block["text_repair_checked"])
        self.assertTrue(block["text_repaired"])
        self.assertEqual(block["text_repairs"], [aggregate_event])
        # 未拆分维持整段聚合指标（调用方段落级口径）
        self.assertEqual(block["text_repair_words_before"], 999)
        self.assertEqual(block["text_repair_candidates_before"], 7)
        report = build_quality_report([block], [], [], [])
        hygiene = report["text_hygiene"]
        self.assertEqual(hygiene["checked_blocks"], 1)
        self.assertEqual(hygiene["repaired_blocks"], 1)
        self.assertEqual(hygiene["repairs"], 1)
        self.assertEqual(hygiene["repair_rules"], {"dedouble": 1})
        self.assertEqual(hygiene["suspected_fragments_before"], 7)
        self.assertEqual(hygiene["suspected_fragments_after"], 3)


class FakePage:
    def __init__(self, words: list[dict]) -> None:
        self._words = words
        self.calls: list[dict] = []

    def extract_words(self, **kwargs: object) -> list[dict]:
        self.calls.append(kwargs)
        return self._words


class ConditionalExtraAttrsTests(unittest.TestCase):
    def test_all_off_calls_plain_extract_words(self) -> None:
        page = FakePage([{"text": "alpha", "x0": 0, "x1": 10, "top": 0, "bottom": 10}])
        words = _extract_page_words(page)
        self.assertEqual(page.calls, [{}])
        self.assertEqual([w["text"] for w in words], ["alpha"])

    def test_subscript_on_requests_size_only(self) -> None:
        page = FakePage([])
        _extract_page_words(page, subscript=True)
        self.assertEqual(page.calls, [{"extra_attrs": ["size"]}])

    def test_twocol_on_requests_size_and_fontname(self) -> None:
        page = FakePage([])
        _extract_page_words(page, twocol=True)
        self.assertEqual(page.calls, [{"extra_attrs": ["size", "fontname"]}])

    def test_returned_words_are_copies(self) -> None:
        original = {"text": "alpha", "x0": 0, "x1": 10, "top": 0, "bottom": 10}
        page = FakePage([original])
        words = _extract_page_words(page, subscript=True)
        words[0]["text"] = "polluted"
        self.assertEqual(original["text"], "alpha")


def _def_row(
    term: str,
    definition: str,
    top: float,
    *,
    bold: bool = True,
    fontname: str | None = "Arial-Bold",
    left_x0: float = 50.0,
    right_x0: float = 200.0,
    extra_gap: float = 0.0,
) -> dict:
    """合成两栏定义行：左栏单词 + 右栏 >=7 词（词间距 3pt，栏间隙 >=8pt）。"""
    words: list[dict] = []
    left_font = fontname if fontname is not None else None
    words.append(_word(term, left_x0, left_x0 + 45, top, top + 12,
                       fontname=("Arial-Bold" if bold else "Arial") if left_font else None))
    x = right_x0 + extra_gap
    for token in definition.split():
        width = max(12.0, 6.0 * len(token))
        words.append(_word(token, x, x + width, top, top + 12, fontname="Arial"))
        x += width + 3.0
    text = " ".join(w["text"] for w in words)
    return _line(text, top, x0=left_x0, x1=x, words=words)


_DEF1 = "value of the alpha quantity used throughout this specification"
_DEF2 = "value of the beta quantity defined by the manufacturer for testing"
_DEF3 = "highest value of the gamma quantity permitted under normal conditions"


class TwocolDefinitionTableTests(unittest.TestCase):
    def _detect(self, lines: list[dict]) -> tuple[list[dict], list[dict]]:
        return _detect_twocol_definition_tables(
            lines, page_height=800.0, document_profile=DEFAULT_DOCUMENT_PROFILE,
            page_number=3)

    def test_three_anchor_rows_trigger_table(self) -> None:
        lines = [
            _def_row("Alpha", _DEF1, 200),
            _def_row("Beta", _DEF2, 220),
            _def_row("Gamma", _DEF3, 240),
        ]
        tables, remaining = self._detect(lines)
        self.assertEqual(len(tables), 1)
        self.assertEqual(remaining, [])
        table = tables[0]
        self.assertEqual(table["layout_table_kind"], "twocol_definition")
        self.assertEqual(
            table["matrix"],
            [["Alpha", _DEF1], ["Beta", _DEF2], ["Gamma", _DEF3]],
        )
        events = [e for e in table["text_repair_meta"]["text_repairs"]
                  if e["rule"] == "twocol_definition_rebuild"]
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["rule_version"], PDF_TWOCOL_DEF_VERSION)
        self.assertEqual(event["page_number"], 3)
        self.assertEqual(event["position_basis"], "line_layout")
        self.assertIn("Alpha", event["before"])
        self.assertIn("Alpha | " + _DEF1, event["after"])

    def test_two_rows_do_not_trigger(self) -> None:
        lines = [
            _def_row("Alpha", _DEF1, 200),
            _def_row("Beta", _DEF2, 220),
        ]
        tables, remaining = self._detect(lines)
        self.assertEqual(tables, [])
        self.assertEqual(len(remaining), 2)

    def test_three_column_variant_rejected(self) -> None:
        rows = []
        for index, (term, definition) in enumerate(
                [("Alpha", _DEF1), ("Beta", _DEF2), ("Gamma", _DEF3)]):
            row = _def_row(term, definition, 200 + index * 20)
            # 右栏内再制造一个 >=8pt 间隙 → 三栏
            right = row["words"][1:]
            mid = len(right) // 2
            for word in right[mid:]:
                word["x0"] += 20.0
                word["x1"] += 20.0
            rows.append(row)
        tables, remaining = self._detect(rows)
        self.assertEqual(tables, [])
        self.assertEqual(len(remaining), 3)

    def test_ordinary_two_column_prose_rejected(self) -> None:
        # 左栏非粗体 → 零触发
        plain = [
            _def_row("Alpha", _DEF1, 200, bold=False),
            _def_row("Beta", _DEF2, 220, bold=False),
            _def_row("Gamma", _DEF3, 240, bold=False),
        ]
        tables, remaining = self._detect(plain)
        self.assertEqual(tables, [])
        self.assertEqual(len(remaining), 3)

    def test_missing_fontname_never_triggers(self) -> None:
        lines = [
            _def_row("Alpha", _DEF1, 200, fontname=None),
            _def_row("Beta", _DEF2, 220, fontname=None),
            _def_row("Gamma", _DEF3, 240, fontname=None),
        ]
        # 缺 fontname 时 _def_row 左栏不写 fontname 键 → 宁可不触发
        for line in lines:
            for word in line["words"]:
                word.pop("fontname", None)
        tables, remaining = self._detect(lines)
        self.assertEqual(tables, [])
        self.assertEqual(len(remaining), 3)

    def test_misaligned_left_column_rejected(self) -> None:
        lines = [
            _def_row("Alpha", _DEF1, 200, left_x0=50.0),
            _def_row("Beta", _DEF2, 220, left_x0=56.0),   # 超 ±2pt 容差
            _def_row("Gamma", _DEF3, 240, left_x0=50.0),
        ]
        tables, remaining = self._detect(lines)
        self.assertEqual(tables, [])
        self.assertEqual(len(remaining), 3)

    def test_mixed_page_consumes_only_region(self) -> None:
        prose_before = _line(
            "This section defines the terms used in the following clauses.",
            150, words=[_word(t, 50 + i * 40, 80 + i * 40, 150, 162)
                        for i, t in enumerate(
                            "This section defines the terms used in the following clauses.".split())])
        prose_after = _line(
            "The following clauses apply to all meter types described above.",
            280, words=[_word(t, 50 + i * 40, 80 + i * 40, 280, 292)
                        for i, t in enumerate(
                            "The following clauses apply to all meter types described above.".split())])
        lines = [
            prose_before,
            _def_row("Alpha", _DEF1, 200),
            _def_row("Beta", _DEF2, 220),
            _def_row("Gamma", _DEF3, 240),
            prose_after,
        ]
        tables, remaining = self._detect(lines)
        self.assertEqual(len(tables), 1)
        self.assertEqual([line["text"] for line in remaining],
                         [prose_before["text"], prose_after["text"]])

    def test_default_switch_is_off(self) -> None:
        with _EnvGuard(RATOMIZER_PDF_TWOCOL_DEF=None):
            self.assertFalse(pdf_twocol_def_enabled())
        with _EnvGuard(RATOMIZER_PDF_TWOCOL_DEF="1"):
            self.assertTrue(pdf_twocol_def_enabled())

    def test_anchor_window_allows_4pt_total_span(self) -> None:
        # 共同锚点语义：48/50/52 每行距锚点 50 均 <=2pt（总跨度 4pt），必须命中
        lines = [
            _def_row("Alpha", _DEF1, 200, left_x0=48.0),
            _def_row("Beta", _DEF2, 220, left_x0=50.0),
            _def_row("Gamma", _DEF3, 240, left_x0=52.0),
        ]
        tables, remaining = self._detect(lines)
        self.assertEqual(len(tables), 1)
        self.assertEqual(remaining, [])
        self.assertEqual(
            tables[0]["matrix"],
            [["Alpha", _DEF1], ["Beta", _DEF2], ["Gamma", _DEF3]],
        )

    def test_outlier_row_does_not_poison_following_aligned_run(self) -> None:
        # x0 [56,50,50,50]：首行异常只使自身落空，后三行合法子区域必须检出，
        # 不重叠消费、不重复建表
        lines = [
            _def_row("Alpha", _DEF1, 180, left_x0=56.0),
            _def_row("Beta", _DEF2, 200, left_x0=50.0),
            _def_row("Gamma", _DEF3, 220, left_x0=50.0),
            _def_row("Delta", _DEF1, 240, left_x0=50.0),
        ]
        tables, remaining = self._detect(lines)
        self.assertEqual(len(tables), 1)
        self.assertEqual(
            tables[0]["matrix"],
            [["Beta", _DEF2], ["Gamma", _DEF3], ["Delta", _DEF1]],
        )
        self.assertEqual([line["text"] for line in remaining], [lines[0]["text"]])

    def test_d3_headerless_materializes_all_rows_as_data_items(self) -> None:
        # P1：D3 payload 显式携带 [] 哨兵，经生产调用点同一 seam（_build_pdf_table_artifacts）
        # 原样传递（不得 or-None 吞掉）——三条定义（含首行 Alpha）全部成为数据
        # table_items，首行不作表头/上下文；也不得注入合成 Term/Definition 表头
        lines = [
            _def_row("Alpha", _DEF1, 200),
            _def_row("Beta", _DEF2, 220),
            _def_row("Gamma", _DEF3, 240),
        ]
        tables, remaining = self._detect(lines)
        self.assertEqual(len(tables), 1)
        payload = tables[0]
        self.assertEqual(payload["explicit_header_rows"], [])
        block, items, _cells = _build_pdf_table_artifacts(
            payload,
            payload["matrix"],
            raw_matrix=payload["text_repair_meta"]["raw_matrix"],
            table_id="TBL-000001",
            block_id="BLK-000001",
            order=1,
            table_title="Definitions",
            section_path=["3 Definitions"],
            knowledge_bases=KB,
            source_format="pdf",
        )
        self.assertEqual(block["header_row_indexes"], [])
        self.assertEqual(block["header_row_count"], 0)
        self.assertEqual(block["header_detection_status"], "explicit")
        # 首行定义进数据区（row_index 1 不被表头推断吃掉）
        self.assertEqual([item["row_index"] for item in items], [1, 2, 3])
        self.assertEqual(items[0]["fields"].get("column_1"), "Alpha")
        # 首行定义值（右栏）完整保留——不得随"表头化"丢失
        self.assertEqual(items[0]["fields"].get("column_2"), _DEF1)
        self.assertEqual(items[1]["fields"].get("column_1"), "Beta")
        self.assertEqual(items[2]["fields"].get("column_1"), "Gamma")
        # 无合成 Term/Definition 表头行——headers 只能是 column_N 回退
        self.assertNotIn("Term", block["headers"])
        self.assertNotIn("Definition", block["headers"])


class GenericTextTableLayoutAuditTests(unittest.TestCase):
    def test_generic_text_table_preserves_subscript_layout_event(self) -> None:
        # 3 行三栏普通无画线表（被 _detect_text_tables 消费），一个 word 带
        # subscript_reattach 版式事件：表 repair meta 必须保留事件且 checked=true
        d1_event = {
            "rule": "subscript_reattach",
            "rule_version": PDF_SUBSCRIPT_REATTACH_VERSION,
            "before": "23 0", "after": "230",
            "position_basis": "word_geometry",
        }

        def _row(term: str, volts: str, mode: str, top: float,
                 *, with_event: bool = False) -> dict:
            v1, v2 = volts.split()
            words = [
                _word(term, 50, 95, top, top + 12),
                _word(v1, 200, 225, top, top + 12),
                _word(v2, 230, 240, top, top + 12),
                _word(mode, 350, 395, top, top + 12),
            ]
            if with_event:
                words[1]["_layout_events"] = [dict(d1_event)]
            return _line(" ".join([term, volts, mode]), top, words=words)

        lines = [
            _row("Alpha", "230 V", "required", 200, with_event=True),
            _row("Beta", "110 V", "optional", 220),
            _row("Gamma", "400 V", "required", 240),
        ]
        tables, remaining = _detect_text_tables(
            lines, page_height=800.0, document_profile=DEFAULT_DOCUMENT_PROFILE,
            defrag=False)
        self.assertEqual(len(tables), 1)
        self.assertEqual(remaining, [])
        meta = tables[0]["text_repair_meta"]
        self.assertTrue(meta["text_repair_checked"])
        events = [e for e in meta["text_repairs"] if e["rule"] == "subscript_reattach"]
        self.assertEqual(len(events), 1)   # 事件只出现一次
        self.assertEqual(events[0]["rule_version"], PDF_SUBSCRIPT_REATTACH_VERSION)
        self.assertIn("row_index", events[0])
        self.assertIn("column_index", events[0])

    def test_ordinary_text_table_keeps_header_inference(self) -> None:
        # P1 反向保护：普通无画线表 payload 无 explicit_header_rows 键 → seam 分流
        # 为 None → 保留既有表头推断（非规范性首行判表头），D3 的显式 headerless
        # 哨兵不得波及
        def _row(a: str, b: str, c: str, top: float) -> dict:
            words = [
                _word(a, 50, 95, top, top + 12),
                _word(b, 200, 245, top, top + 12),
                _word(c, 350, 395, top, top + 12),
            ]
            return _line(" ".join([a, b, c]), top, words=words)
        lines = [
            _row("Parameter", "Value", "Mode", 200),
            _row("Alpha", "230", "required", 220),
            _row("Beta", "110", "optional", 240),
        ]
        tables, _remaining = _detect_text_tables(
            lines, page_height=800.0, document_profile=DEFAULT_DOCUMENT_PROFILE,
            defrag=False)
        self.assertEqual(len(tables), 1)
        payload = tables[0]
        self.assertNotIn("explicit_header_rows", payload)
        block, items, _cells = _build_pdf_table_artifacts(
            payload,
            payload["matrix"],
            table_id="TBL-000002",
            block_id="BLK-000002",
            order=2,
            table_title="Parameters",
            section_path=["4 Requirements"],
            knowledge_bases=KB,
            source_format="pdf",
        )
        # 推断生效：非规范性首行判为表头（inferred），不进数据 items
        self.assertEqual(block["header_detection_status"], "inferred")
        self.assertEqual(block["header_row_indexes"], [1])
        self.assertEqual([item["row_index"] for item in items], [2, 3])

    def test_shared_seam_routes_explicit_header_tri_state(self) -> None:
        # D3 seam 加固：生产调用点唯一入口 _build_pdf_table_artifacts 的显式表头
        # 三态分流钉死在真实 seam 上——D3 dict → []；普通文本表 dict 无键 → None；
        # 画线表元组 → None；调用方误传的 explicit_header_rows 被 pop 不得覆盖分流
        matrix = [["Alpha", _DEF1], ["Beta", _DEF2]]
        with mock.patch("parsers.pdf_parser.build_table_artifacts") as mocked:
            mocked.return_value = ({}, [], [])
            _build_pdf_table_artifacts(
                {"explicit_header_rows": []}, matrix, table_id="T")
            self.assertEqual(
                mocked.call_args.kwargs["explicit_header_rows"], [])
            _build_pdf_table_artifacts(
                {"matrix": matrix}, matrix, table_id="T")
            self.assertIsNone(mocked.call_args.kwargs["explicit_header_rows"])
            _build_pdf_table_artifacts(
                (object(), matrix, {}), matrix, table_id="T")
            self.assertIsNone(mocked.call_args.kwargs["explicit_header_rows"])
            # 调用方显式误传被 pop——分流只能来自 payload
            _build_pdf_table_artifacts(
                {"explicit_header_rows": []}, matrix, table_id="T",
                explicit_header_rows=[1])
            self.assertEqual(
                mocked.call_args.kwargs["explicit_header_rows"], [])


class RepeatedMarginNoiseTests(unittest.TestCase):
    def test_mixed_size_margin_line_uses_same_tokenization_as_main_path(self) -> None:
        # C-2：页眉噪声检测用裸 page.extract_words()，D1 开后主路径用 extra_attrs=["size"]，
        # 两种分词下同一页眉文本不同，repeated_noise 漏判。应使用同一 _extract_page_words。
        def make_page(plain_words: list[dict], extra_words: list[dict]) -> mock.MagicMock:
            page = mock.MagicMock()
            page.height = 1000
            def fake_extract_words(**kwargs: object) -> list[dict]:
                if kwargs.get("extra_attrs"):
                    return extra_words
                return plain_words
            page.extract_words.side_effect = fake_extract_words
            return page

        plain = [{"text": "Nominal-Current", "x0": 50, "x1": 200,
                  "top": 50, "bottom": 60}]
        extra = [
            {"text": "Nominal", "x0": 50, "x1": 110,
             "top": 50, "bottom": 60, "size": 12},
            {"text": "-", "x0": 112, "x1": 116,
             "top": 50, "bottom": 60, "size": 12},
            {"text": "Current", "x0": 118, "x1": 190,
             "top": 50, "bottom": 60, "size": 9},
        ]
        pdf = mock.MagicMock()
        pdf.pages = [make_page(plain, extra) for _ in range(3)]
        result = _detect_repeated_margin_lines(
            pdf, defrag=False, subscript=True, twocol=False)
        # 检测必须与主路径口径一致：extra_attrs 分词得到 "Nominal - Current"
        self.assertIn("nominal - current", result)
        self.assertNotIn("nominal-current", result)


class SwitchAndVersionTests(unittest.TestCase):
    def test_env_registry_registers_three_switches(self) -> None:
        defaults = {v.name: v.default for v in ENV_REGISTRY}
        self.assertEqual(defaults.get("RATOMIZER_PDF_SUBSCRIPT_FIX"), "1")
        self.assertEqual(defaults.get("RATOMIZER_PDF_HYPHEN_FIX"), "1")
        self.assertEqual(defaults.get("RATOMIZER_PDF_TWOCOL_DEF"), "0")

    def test_switch_defaults_and_fingerprint(self) -> None:
        with _EnvGuard(RATOMIZER_PDF_SUBSCRIPT_FIX=None,
                       RATOMIZER_PDF_HYPHEN_FIX=None,
                       RATOMIZER_PDF_TWOCOL_DEF=None):
            self.assertTrue(pdf_subscript_fix_enabled())
            self.assertTrue(pdf_hyphen_fix_enabled())
            self.assertFalse(pdf_twocol_def_enabled())
            self.assertEqual(
                pdf_layout_switch_fingerprint(),
                "pdf-layout-switches-sub1-hyp1-2col0",
            )

    def test_atomize_producer_changes_with_each_switch(self) -> None:
        import desktop_tasks

        def producer() -> str:
            return desktop_tasks.stage_producer("atomize")

        with _EnvGuard(RATOMIZER_PDF_SUBSCRIPT_FIX=None,
                       RATOMIZER_PDF_HYPHEN_FIX=None,
                       RATOMIZER_PDF_TWOCOL_DEF=None):
            baseline = producer()
            self.assertIn("pdf-layout-switches-sub1-hyp1-2col0", baseline)
        for name, fragment in (
            ("RATOMIZER_PDF_SUBSCRIPT_FIX", "sub0"),
            ("RATOMIZER_PDF_HYPHEN_FIX", "hyp0"),
            ("RATOMIZER_PDF_TWOCOL_DEF", "2col1"),
        ):
            others = {key: None for key in _SWITCH_ENV}
            others[name] = "0" if fragment.endswith("0") else "1"
            with _EnvGuard(**others):
                changed = producer()
            self.assertNotEqual(changed, baseline)
            self.assertIn(fragment, changed)

    def test_schema_consts_match_computed_fingerprint(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "schemas" / "claim_catalog.schema.json").read_text(encoding="utf-8"))
        blob = json.dumps(schema)
        vocab = text_repair_vocabulary_fingerprint()
        self.assertIn(f'"const": "pdf-text-repair-v5"', blob)
        self.assertIn(
            f"source-pdf-text-repair-{PDF_TEXT_REPAIR_VERSION}-{vocab}", blob)
        self.assertNotIn("pdf-text-repair-v4", blob)


if __name__ == "__main__":
    unittest.main()
