"""大纲权威接线 Phase 2b（第一片）——条款装配层重切的 flag 门控测试。

钉三件事：
1. flag 关（默认）逐字节零变化：装配输出、条款加载、抽取缓存指纹、
   chain 阶段 producer、阶段指纹配置、ai-extract 付费缓存/发布 lineage；
2. flag 开的重切语义：demoted 并入前条款、被吞并 confirmed heading 切开、
   toc 出正文基线、suspect 只审计不动（宁漏勿错）；
3. 诚实边界：报告不可得如实回退 + unavailable 标注；块守恒硬校验正反例；
   两个消费点（assemble_sections / load_clauses）口径一致。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "portfolio"

FLAG_ENV = "RATOMIZER_OUTLINE_AUTHORITY"

OEM_TEXT = (
    "26 There shall be no change of original equipment manufacturer "
    "for this lot."
)


def _heading(block_id: str, text: str, path: list[str], order: int) -> dict:
    return {
        "block_id": block_id, "order": order, "type": "heading",
        "text": text, "section_path": list(path),
        "noise": False, "doc_region": "body",
    }


def _paragraph(block_id: str, text: str, path: list[str], order: int) -> dict:
    return {
        "block_id": block_id, "order": order, "type": "paragraph",
        "text": text, "section_path": list(path),
        "noise": False, "doc_region": "body",
    }


def _synthetic_blocks() -> list[dict]:
    """四种裁决各就各位的合成语料（无客户词面）。

    - b1/b2 "1 Scope"（confirmed）；
    - b3/b4 "26 There shall be..."（demoted——升格正文句，自成条款领起）；
    - b5-b9 "2.2 Delivery Schedule"：b7 "2.3 STATEMENT OF REQUIREMENTS
      (TECHNICAL)"（全大写 confirmed，非首位→吞并）；b9 目录行（toc）；
    - b11/b12 "9 Site"：b12 "5 Drawings"（编号断裂→suspect，非首位→吞并，
      宁漏勿错不切）。
    """
    return [
        _heading("b1", "1 Scope", ["1 Scope"], 1),
        _paragraph("b2", "The meter shall measure energy.", ["1 Scope"], 2),
        _heading("b3", OEM_TEXT, [OEM_TEXT], 3),
        _paragraph("b4", "The supplier remains the OEM.", [OEM_TEXT], 4),
        _heading("b5", "2.2 Delivery Schedule", ["2.2 Delivery Schedule"], 5),
        _paragraph("b6", "Delivery is two months.", ["2.2 Delivery Schedule"], 6),
        _heading(
            "b7", "2.3 STATEMENT OF REQUIREMENTS (TECHNICAL)",
            ["2.2 Delivery Schedule"], 7),
        _paragraph(
            "b8", "The meter shall record voltage.",
            ["2.2 Delivery Schedule"], 8),
        _heading(
            "b9", "References ........ 14", ["2.2 Delivery Schedule"], 9),
        _paragraph("b11", "Site requirements apply.", ["9 Site"], 10),
        _heading("b12", "5 Drawings", ["9 Site"], 11),
    ]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _seed_out(out: Path, blocks: list[dict], chunks: list[dict] | None = None) -> None:
    _write_jsonl(out / "blocks.jsonl", blocks)
    if chunks is not None:
        _write_jsonl(out / "chunks.jsonl", chunks)


def _chunks_from_sections(sections: list[dict]) -> list[dict]:
    """按 assemble 条款逐条镜像出 chunks.jsonl（load_clauses 可读的最小形态）。"""
    return [
        {
            "chunk_id": f"CH-{index + 1:06d}",
            "section_path": list(section.get("section_path") or []),
            "heading": str(section.get("heading") or ""),
            "text": str(section.get("text") or ""),
            "source_block_ids": list(section.get("block_ids") or []),
        }
        for index, section in enumerate(sections)
    ]


def _load_portfolio_spec() -> dict:
    return json.loads(
        (FIXTURE_DIR / "tender_pdf_pathology.json").read_text(encoding="utf-8"))


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k != FLAG_ENV}


class FlagOffByteIdentityTests(unittest.TestCase):
    """flag 关：一切指纹、producer 戳、装配输出与现状逐字节一致。"""

    def test_registry_default_is_off(self) -> None:
        from config import ENV_REGISTRY

        entry = next(
            item for item in ENV_REGISTRY if item.name == FLAG_ENV)
        self.assertEqual(entry.default, "0")

    def test_assemble_sections_unset_equals_explicit_zero(self) -> None:
        from extract_units import assemble_sections

        blocks = _synthetic_blocks()
        base = _clean_env()
        with mock.patch.dict(os.environ, base, clear=True):
            unset = assemble_sections(blocks)
        with mock.patch.dict(os.environ, {**base, FLAG_ENV: "0"}, clear=True):
            off = assemble_sections(blocks)
        self.assertEqual(
            json.dumps(unset, ensure_ascii=False, sort_keys=True),
            json.dumps(off, ensure_ascii=False, sort_keys=True))

    def test_load_clauses_unset_equals_explicit_zero(self) -> None:
        import functional_extract as fe

        base = _clean_env()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, _synthetic_blocks())
            with mock.patch.dict(os.environ, base, clear=True):
                unset = fe.load_clauses(out)
            with mock.patch.dict(os.environ, {**base, FLAG_ENV: "0"}, clear=True):
                off = fe.load_clauses(out)
            self.assertEqual(
                json.dumps(unset, ensure_ascii=False, sort_keys=True),
                json.dumps(off, ensure_ascii=False, sort_keys=True))

    def test_extraction_fingerprint_off_is_byte_identical_on_differs(self) -> None:
        import functional_extract as fe

        sections = [{"section_id": "x", "section_path": ["x"], "heading": "x",
                     "text": "t", "block_ids": ["B"]}]
        base = _clean_env()
        with mock.patch.dict(os.environ, base, clear=True):
            unset = fe.extraction_fingerprint(sections, route_key="stub")
            unset_family = fe.extraction_fingerprint(
                sections, route_key="stub", context_strategy="clause_family")
        with mock.patch.dict(os.environ, {**base, FLAG_ENV: "0"}, clear=True):
            off = fe.extraction_fingerprint(sections, route_key="stub")
            off_family = fe.extraction_fingerprint(
                sections, route_key="stub", context_strategy="clause_family")
        with mock.patch.dict(os.environ, {**base, FLAG_ENV: "1"}, clear=True):
            on = fe.extraction_fingerprint(sections, route_key="stub")
            on_family = fe.extraction_fingerprint(
                sections, route_key="stub", context_strategy="clause_family")
        self.assertEqual(unset, off)
        self.assertEqual(unset_family, off_family)
        self.assertNotEqual(unset, on)
        self.assertNotEqual(unset_family, on_family)

    def test_stage_producer_off_pins_current_literal_join(self) -> None:
        """flag 关时 functional-extract producer 与现行常量逐字节相等（防误加无条件键）。"""
        import desktop_tasks
        import functional_extract as fe

        expected = "+".join((
            "functional_extract/v1",
            fe.FUNCTIONAL_EXTRACT_VERSION,
            fe.FUNCTIONAL_EXTRACT_PROMPT_VERSION,
            fe.FUNCTIONAL_EXTRACT_GUARDS_VERSION,
            fe.FUNCTIONAL_CONSERVATION_MODEL_VERSION,
            # bed36f8：语义装载器（noise 剔除/恰好一次判重）钉进 producer——
            # 与 desktop_tasks.stage_producer 的拼接顺序保持一致。
            fe.SEMANTIC_SECTION_LOADER_VERSION,
            *fe.routing_lineage_versions().values(),
        )) + "+impl-v1"
        base = _clean_env()
        with mock.patch.dict(os.environ, base, clear=True):
            unset = desktop_tasks.stage_producer("functional-extract")
        with mock.patch.dict(os.environ, {**base, FLAG_ENV: "0"}, clear=True):
            off = desktop_tasks.stage_producer("functional-extract")
        with mock.patch.dict(os.environ, {**base, FLAG_ENV: "1"}, clear=True):
            on = desktop_tasks.stage_producer("functional-extract")
        self.assertEqual(unset, expected)
        self.assertEqual(off, expected)
        self.assertNotEqual(on, expected)
        self.assertIn("outline-authority-v1", on)

    def test_stage_config_gains_outline_key_only_when_on(self) -> None:
        import desktop_tasks

        base = _clean_env()
        with mock.patch.dict(os.environ, base, clear=True):
            off = desktop_tasks._functional_extract_stage_config()
        self.assertEqual(
            set(off), {"strategy", "strategy_env_raw", "negative_k"})
        with mock.patch.dict(os.environ, {**base, FLAG_ENV: "1"}, clear=True):
            on = desktop_tasks._functional_extract_stage_config()
        self.assertEqual(on["outline_authority"], "outline-authority-v1")

    def test_ai_extract_versions_gain_outline_key_only_when_on(self) -> None:
        import ai_extract
        from document_outline import OUTLINE_AUTHORITY_VERSION

        base = _clean_env()
        with mock.patch.dict(os.environ, base, clear=True):
            cache_off = ai_extract.section_cache_versions()
            lineage_off = ai_extract.producer_lineage_versions()
        self.assertNotIn("outline_authority", cache_off)
        self.assertNotIn("outline_authority", lineage_off)
        with mock.patch.dict(os.environ, {**base, FLAG_ENV: "1"}, clear=True):
            cache_on = ai_extract.section_cache_versions()
            lineage_on = ai_extract.producer_lineage_versions()
        self.assertEqual(cache_on["outline_authority"], OUTLINE_AUTHORITY_VERSION)
        self.assertEqual(lineage_on["outline_authority"], OUTLINE_AUTHORITY_VERSION)

    def test_stage_input_fingerprint_off_equals_explicit_zero(self) -> None:
        import desktop_tasks

        base = _clean_env()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, _synthetic_blocks())
            with mock.patch.dict(os.environ, base, clear=True):
                unset = desktop_tasks.stage_input_fingerprint(out, "functional-extract")
            with mock.patch.dict(os.environ, {**base, FLAG_ENV: "0"}, clear=True):
                off = desktop_tasks.stage_input_fingerprint(out, "functional-extract")
            with mock.patch.dict(os.environ, {**base, FLAG_ENV: "1"}, clear=True):
                on = desktop_tasks.stage_input_fingerprint(out, "functional-extract")
        self.assertEqual(unset, off)
        self.assertNotEqual(unset, on)


class FlagOnFourVerdictsTests(unittest.TestCase):
    """flag 开：四种裁决的重切语义（合成夹具，assemble 形态）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name)
        _seed_out(cls.out, _synthetic_blocks())
        base = {k: v for k, v in os.environ.items() if k != FLAG_ENV}
        with mock.patch.dict(os.environ, {**base, FLAG_ENV: "1"}, clear=True):
            from extract_units import assemble_sections_detailed

            cls.sections, cls.audit = assemble_sections_detailed(_synthetic_blocks())

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_boundaries_match_verdict_semantics(self) -> None:
        boundaries = [
            (section["section_id"], list(section["block_ids"]))
            for section in self.sections
        ]
        self.assertEqual(boundaries, [
            # demoted b3 领起的条款并入前一条款 "1 Scope"（作为正文块）
            ("1 Scope", ["b1", "b2", "b3", "b4"]),
            ("2.2 Delivery Schedule", ["b5", "b6"]),
            # 被吞并 confirmed heading b7 切开成新条款，身份从 heading 文本派生
            ("2.3 STATEMENT OF REQUIREMENTS (TECHNICAL)", ["b7", "b8"]),
            # suspect b12（编号断裂 + 非首位）宁漏勿错：不切
            ("9 Site", ["b11", "b12"]),
        ])

    def test_toc_block_leaves_body_baseline_but_not_blocks_file(self) -> None:
        covered = {
            block_id for section in self.sections
            for block_id in section["block_ids"]
        }
        self.assertNotIn("b9", covered)
        self.assertEqual(self.audit["toc_excluded_block_ids"], ["b9"])
        self.assertEqual(self.audit["status"], "applied")
        self.assertEqual(self.audit["demoted_merged_block_ids"], ["b3"])
        self.assertEqual(self.audit["swallowed_cut_block_ids"], ["b7"])
        self.assertEqual(self.audit["input_clause_count"], 4)
        self.assertEqual(self.audit["output_clause_count"], 4)

    def test_merged_clause_text_carries_demoted_body_sentence(self) -> None:
        merged = self.sections[0]
        self.assertIn("1 Scope", merged["text"])
        self.assertIn("The meter shall measure energy.", merged["text"])
        self.assertIn(OEM_TEXT, merged["text"])
        self.assertIn("The supplier remains the OEM.", merged["text"])

    def test_new_clause_identity_derives_from_heading_text(self) -> None:
        new_clause = self.sections[2]
        self.assertEqual(
            new_clause["section_path"], ["2.3 STATEMENT OF REQUIREMENTS (TECHNICAL)"])
        self.assertEqual(
            new_clause["heading"], "2.3 STATEMENT OF REQUIREMENTS (TECHNICAL)")
        self.assertIn("2.3 STATEMENT OF REQUIREMENTS (TECHNICAL)", new_clause["text"])

    def test_demoted_leading_first_clause_is_kept_with_audit(self) -> None:
        """首条款无前者：demoted 领起也如实保留（不凭空丢条款），并记审计。"""
        blocks = [
            _heading("h1", OEM_TEXT, [OEM_TEXT], 1),
            _paragraph("p1", "Body.", [OEM_TEXT], 2),
        ]
        from document_outline import apply_outline_authority

        sections, audit = apply_outline_authority(blocks, _assemble(blocks), enabled=True)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["block_ids"], ["h1", "p1"])
        self.assertEqual(
            audit["demoted_leading_without_predecessor_block_ids"], ["h1"])


def _assemble(blocks: list[dict]) -> list[dict]:
    from extract_units import assemble_sections_detailed

    return assemble_sections_detailed(blocks, outline_authority=False)[0]


class ChunksShapeRecutTests(unittest.TestCase):
    """chunks 形态（load_clauses 主路径）：同一重切权威、build_chunks 文本配方。"""

    def test_chunks_shape_cut_and_recipe_text(self) -> None:
        import functional_extract as fe

        blocks = _synthetic_blocks()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            raw = _assemble(blocks)
            _seed_out(out, blocks, _chunks_from_sections(raw))
            base = _clean_env()
            with mock.patch.dict(os.environ, {**base, FLAG_ENV: "1"}, clear=True):
                sections, audit = fe.load_clauses_detailed(out)
        boundaries = [
            (section["section_id"], list(section["block_ids"]))
            for section in sections
        ]
        self.assertEqual(boundaries, [
            ("1 Scope", ["b1", "b2", "b3", "b4"]),
            ("2.2 Delivery Schedule", ["b5", "b6"]),
            ("2.3 STATEMENT OF REQUIREMENTS (TECHNICAL)", ["b7", "b8"]),
            ("9 Site", ["b11", "b12"]),
        ])
        self.assertEqual(audit["swallowed_cut_block_ids"], ["b7"])
        self.assertEqual(audit["demoted_merged_block_ids"], ["b3"])
        self.assertEqual(audit["toc_excluded_block_ids"], ["b9"])
        # 切开分片文本按 build_chunks 配方重建（heading → "# " 前缀）
        self.assertEqual(
            sections[1]["text"], "# 2.2 Delivery Schedule\n\nDelivery is two months.")
        self.assertEqual(
            sections[2]["text"],
            "# 2.3 STATEMENT OF REQUIREMENTS (TECHNICAL)\n\n"
            "The meter shall record voltage.")

    def test_raw_load_param_returns_legacy_boundaries_under_flag_on(self) -> None:
        """outline_authority=False 强制原始边界（document_outline 报告构建依赖）。"""
        import functional_extract as fe

        blocks = _synthetic_blocks()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, blocks, _chunks_from_sections(_assemble(blocks)))
            base = _clean_env()
            with mock.patch.dict(os.environ, {**base, FLAG_ENV: "1"}, clear=True):
                raw = fe.load_clauses(out, outline_authority=False)
                recut = fe.load_clauses(out)
        self.assertEqual(
            [len(section["block_ids"]) for section in raw], [2, 2, 5, 2])
        self.assertNotEqual(
            json.dumps(raw, ensure_ascii=False, sort_keys=True),
            json.dumps(recut, ensure_ascii=False, sort_keys=True))

    def test_shadow_report_still_detects_swallow_under_flag_on(self) -> None:
        """flag 开时 outline 报告仍按原始边界检测吞并（不被重切致盲）。"""
        spec = _load_portfolio_spec()
        blocks = list(spec["blocks"])
        base = _clean_env()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, blocks, list(spec["chunks"]))
            with mock.patch.dict(os.environ, {**base, FLAG_ENV: "1"}, clear=True):
                from document_outline import write_outline_report

                report = write_outline_report(out)
        self.assertGreaterEqual(report["summary"]["swallowed_heading_count"], 1)
        self.assertIn(
            "BLK-SWALLOW-H",
            {item["block_id"] for item in report["swallowed_headings"]})

    def test_shadow_report_blocks_only_fallback_also_stays_raw(self) -> None:
        """chunks 缺席（assemble 兜底路径）时报告同样取原始边界。"""
        spec = _load_portfolio_spec()
        blocks = list(spec["blocks"])
        base = _clean_env()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, blocks)  # 不写 chunks → load_clauses 走 assemble 兜底
            with mock.patch.dict(os.environ, {**base, FLAG_ENV: "1"}, clear=True):
                from document_outline import write_outline_report

                report = write_outline_report(out)
        self.assertGreaterEqual(report["summary"]["swallowed_heading_count"], 1)
        self.assertIn(
            "BLK-SWALLOW-H",
            {item["block_id"] for item in report["swallowed_headings"]})


class ConservationTests(unittest.TestCase):
    """块守恒硬校验：所有输入块恰好归属一个条款或登记 toc 排除。"""

    def test_conservation_holds_end_to_end(self) -> None:
        from document_outline import _verify_block_conservation

        blocks = _synthetic_blocks()
        sections, audit = _apply(blocks)
        covered = [
            block_id for section in sections for block_id in section["block_ids"]
        ]
        _verify_block_conservation(sections_input(blocks), sections, audit["toc_excluded_block_ids"])
        self.assertEqual(len(covered) + len(audit["toc_excluded_block_ids"]), len(blocks))

    def test_conservation_violation_raises_loudly(self) -> None:
        from document_outline import (
            OutlineAuthorityError,
            _verify_block_conservation,
        )

        sections = [
            {"section_id": "a", "block_ids": ["B1", "B2"]},
            {"section_id": "b", "block_ids": ["B3"]},
        ]
        # 丢失块
        with self.assertRaises(OutlineAuthorityError):
            _verify_block_conservation(sections, [{"block_ids": ["B1", "B2"]}], [])
        # 重复归属（同一块进两个条款）
        with self.assertRaises(OutlineAuthorityError):
            _verify_block_conservation(
                sections,
                [{"block_ids": ["B1", "B2"]}, {"block_ids": ["B3", "B3"]}],
                [],
            )
        # 未登记排除的块被剔除
        with self.assertRaises(OutlineAuthorityError):
            _verify_block_conservation(sections, [{"block_ids": ["B1"]}], [])


def sections_input(blocks: list[dict]) -> list[dict]:
    return _assemble(blocks)


def _apply(blocks: list[dict]):
    from document_outline import apply_outline_authority

    return apply_outline_authority(blocks, _assemble(blocks), enabled=True)


class UnavailableFallbackTests(unittest.TestCase):
    """报告不可得：flag 开也如实回退全量旧切分 + unavailable 标注。"""

    def test_missing_blocks_falls_back_with_reason(self) -> None:
        import functional_extract as fe

        blocks = _synthetic_blocks()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_jsonl(
                out / "chunks.jsonl",
                _chunks_from_sections(_assemble(blocks)))
            base = _clean_env()
            with mock.patch.dict(os.environ, {**base, FLAG_ENV: "1"}, clear=True):
                sections, audit = fe.load_clauses_detailed(out)
            with mock.patch.dict(os.environ, {**base, FLAG_ENV: "0"}, clear=True):
                legacy = fe.load_clauses(out)
        self.assertEqual(
            json.dumps(sections, ensure_ascii=False, sort_keys=True),
            json.dumps(legacy, ensure_ascii=False, sort_keys=True))
        self.assertEqual(audit["status"], "unavailable:blocks_missing")

    def test_no_block_sequences_falls_back_with_reason(self) -> None:
        import functional_extract as fe

        blocks = _synthetic_blocks()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, blocks, [{
                "chunk_id": "CH-000001",
                "section_path": ["1 Scope"],
                "heading": "1 Scope",
                "text": "no block sequence",
            }])
            base = _clean_env()
            with mock.patch.dict(os.environ, {**base, FLAG_ENV: "1"}, clear=True):
                sections, audit = fe.load_clauses_detailed(out)
        self.assertEqual(len(sections), 1)
        self.assertEqual(audit["status"], "unavailable:no_block_sequences")

    def test_stub_run_payload_records_authority_only_when_flag_on(self) -> None:
        import functional_extract as fe
        from result_package import governed_artifact_path

        def _run() -> tuple[dict, dict]:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                _seed_out(out, _synthetic_blocks(),
                          _chunks_from_sections(_assemble(_synthetic_blocks())))
                result = fe.run_functional_extract(out, route="stub", strategy="legacy")
                payload = json.loads(
                    governed_artifact_path(
                        out, "functional_requirements.json",
                        category="pipeline", for_write=False,
                    ).read_text(encoding="utf-8"))
            return result, payload

        base = _clean_env()
        with mock.patch.dict(os.environ, {**base, FLAG_ENV: "1"}, clear=True):
            on_result, on_payload = _run()
        self.assertEqual(on_payload["outline_authority"]["status"], "applied")
        self.assertEqual(on_result["outline_authority"], {"status": "applied"})
        self.assertEqual(on_payload["clause_count"], 4)
        with mock.patch.dict(os.environ, {**base, FLAG_ENV: "0"}, clear=True):
            off_result, off_payload = _run()
        self.assertNotIn("outline_authority", off_payload)
        self.assertNotIn("outline_authority", off_result)


class ConsumerConsistencyTests(unittest.TestCase):
    """两个消费点共用同一重切权威：同夹具条款边界一致。"""

    def test_chunks_mirroring_assemble_recuts_identically(self) -> None:
        """chunks.jsonl 逐条镜像 assemble 条款时，两消费点边界逐字节一致。"""
        import functional_extract as fe
        from extract_units import assemble_sections_detailed

        blocks = _synthetic_blocks()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, blocks, _chunks_from_sections(_assemble(blocks)))
            base = _clean_env()
            with mock.patch.dict(os.environ, {**base, FLAG_ENV: "1"}, clear=True):
                via_load, load_audit = fe.load_clauses_detailed(out)
                via_assemble, assemble_audit = assemble_sections_detailed(blocks)
        boundaries_load = [
            (section["section_id"], list(section["block_ids"]))
            for section in via_load
        ]
        boundaries_assemble = [
            (section["section_id"], list(section["block_ids"]))
            for section in via_assemble
        ]
        self.assertEqual(boundaries_load, boundaries_assemble)
        self.assertEqual(
            load_audit["swallowed_cut_block_ids"],
            assemble_audit["swallowed_cut_block_ids"])
        self.assertEqual(
            load_audit["demoted_merged_block_ids"],
            assemble_audit["demoted_merged_block_ids"])

    def test_no_chunks_fallback_shares_the_same_path(self) -> None:
        import functional_extract as fe
        from extract_units import assemble_sections_detailed

        blocks = _synthetic_blocks()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, blocks)
            base = _clean_env()
            with mock.patch.dict(os.environ, {**base, FLAG_ENV: "1"}, clear=True):
                via_load, _ = fe.load_clauses_detailed(out)
                via_assemble, _ = assemble_sections_detailed(blocks)
        self.assertEqual(
            json.dumps(via_load, ensure_ascii=False, sort_keys=True),
            json.dumps(via_assemble, ensure_ascii=False, sort_keys=True))

    def test_portfolio_cut_decisions_agree_across_consumers(self) -> None:
        """底层 chunker 不同（chunks vs section_path 分组）时，切点裁决仍同口径。"""
        import functional_extract as fe
        from extract_units import assemble_sections_detailed

        spec = _load_portfolio_spec()
        blocks = list(spec["blocks"])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_out(out, blocks, list(spec["chunks"]))
            base = _clean_env()
            with mock.patch.dict(os.environ, {**base, FLAG_ENV: "1"}, clear=True):
                _, chunks_audit = fe.load_clauses_detailed(out)
                _, assemble_audit = assemble_sections_detailed(blocks)
        self.assertIn("BLK-SWALLOW-H", chunks_audit["swallowed_cut_block_ids"])
        self.assertIn("BLK-SWALLOW-H", assemble_audit["swallowed_cut_block_ids"])
        # 两消费点对同一病理块都判 demoted（OEM 升格句）：chunks 侧并前条、
        # assemble 侧首条款保留——裁决一致，处置按各自位置语义。
        self.assertEqual(chunks_audit["demoted_merged_block_ids"], [])
        self.assertEqual(
            assemble_audit["demoted_leading_without_predecessor_block_ids"],
            ["BLK-OEM-H"])


if __name__ == "__main__":
    unittest.main()
