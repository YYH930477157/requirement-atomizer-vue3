from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from atomize import build_table_artifacts
from extraction_units import (
    EXTRACTION_UNIT_PLANNER_VERSION,
    EXTRACTION_UNIT_SCHEMA,
    build_extraction_units,
    load_extraction_units,
    plan_extraction_units,
)
from requirement_kb import KnowledgeRepository
from table_dispositions import build_table_cell_dispositions

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schemas" / "extraction_unit.schema.json"

KB = KnowledgeRepository.from_paths([])

VALIDATOR = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def _prose_block(block_id: str, order: int, *, text: str, section: list[str],
                 type_: str = "paragraph", is_list_item: bool = False) -> dict:
    return {
        "block_id": block_id, "order": order, "type": type_, "text": text,
        "raw_text": text, "section_path": section, "noise": False,
        "doc_region": "body", "is_list_item": is_list_item,
    }


def _corpus() -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    blocks: list[dict] = [
        _prose_block("BLK-000001", 1, text="4 Requirements", section=["4 Requirements"], type_="heading"),
        # 信号句 ×2 + 非信号句（非信号句不单独成单元，也不影响信号句）
        _prose_block("BLK-000002", 2,
                     text="The meter shall log events. Logging shall be tamper-proof. This clause sets the scope.",
                     section=["4 Requirements"]),
        # 无信号叙事块 → 整块 narrative context 单元
        _prose_block("BLK-000003", 3,
                     text="This document describes the architecture of the metering module.",
                     section=["4 Requirements"]),
        # 列表项 + shall
        _prose_block("BLK-000004", 4, text="The meter shall provide a local display.",
                     section=["4 Requirements"], is_list_item=True),
        # 引用源条款（供 ref_texts 解析）
        _prose_block("BLK-000005", 5, text="4.2 Environmental conditions",
                     section=["4.2 Environmental conditions"], type_="heading"),
        _prose_block("BLK-000006", 6, text="The device shall operate between -25 and +70 degrees Celsius.",
                     section=["4.2 Environmental conditions"]),
        # 引用句（含术语 event record——同节应挂上定义 context_refs）
        _prose_block("BLK-000007", 7, text="The requirements given in 4.2 shall apply to the event record handling.",
                     section=["4 Requirements"]),
        # 术语节
        _prose_block("BLK-000008", 8, text="3 Terms and definitions",
                     section=["3 Terms and definitions"], type_="heading"),
        _prose_block("BLK-000009", 9, text="3.1 event record",
                     section=["3 Terms and definitions", "3.1 event record"], type_="heading"),
        _prose_block("BLK-000010", 10, text="A record of a metering event stored in the meter.",
                     section=["3 Terms and definitions", "3.1 event record"]),
    ]
    # 参数表（row leaf 模式）+ 规范单元格表（cell leaf 模式）
    table_block, table_items, cell_items = build_table_artifacts(
        [["No.", "Parameter", "Value", "Unit"],
         ["1", "Rated voltage", "230", "V"],
         ["2", "Frequency", "50", "Hz"]],
        table_id="TBL-000001", block_id="BLK-000020", order=20,
        table_title="Rated values", section_path=["4 Requirements"],
        knowledge_bases=KB,
    )
    norm_block, norm_items, norm_cells = build_table_artifacts(
        [["Requirement", "Evidence"],
         ["The device shall retain audit records.", "Log module"]],
        table_id="TBL-000002", block_id="BLK-000021", order=21,
        table_title="Audit requirements", section_path=["4 Requirements"],
        knowledge_bases=KB,
    )
    blocks.extend([table_block, norm_block])
    table_items = list(table_items) + list(norm_items)
    cell_items = list(cell_items) + list(norm_cells)
    # 第三张表：数据行按 mapping/prose_grid 的真实规划口径置为 cell leaf
    # （build_table_artifacts 的参数表默认 row leaf；cell 模式由 plan_table_leaves
    # 对 mapping/prose_grid 产生，这里在产物层模拟同一结果）
    access_block, access_items, access_cells = build_table_artifacts(
        [["Access", "Evidence"],
         ["The attribute shall be read-only.", "Maybe applicable."]],
        table_id="TBL-000003", block_id="BLK-000022", order=22,
        table_title="Access control", section_path=["4 Requirements"],
        knowledge_bases=KB,
    )
    for cell in access_cells:
        if int(cell["row_index"]) >= 2:
            cell["leaf_kind"] = "cell"
    # cell 模式下数据行只是容器（其单元格各自成 leaf）——与 plan_table_leaves 的
    # cell/mixed 模式产物形态一致
    for item in access_items:
        if int(item.get("row_index") or 0) >= 2:
            item["leaf_role"] = "container"
    blocks.append(access_block)
    table_items = table_items + list(access_items)
    cell_items = cell_items + list(access_cells)
    dispositions = build_table_cell_dispositions(
        [table_block, norm_block, access_block], cell_items)
    return blocks, table_items, cell_items, dispositions


class ExtractionUnitPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.blocks, self.table_items, self.cell_items, self.dispositions = _corpus()
        self.units, self.summary = build_extraction_units(
            self.blocks, self.table_items, self.cell_items, self.dispositions)
        self.by_id = {unit["unit_id"]: unit for unit in self.units}

    def test_all_units_validate_against_schema(self) -> None:
        errors = []
        for unit in self.units:
            for error in VALIDATOR.iter_errors(unit):
                errors.append(f"{unit['unit_id']}: {error.message}")
        self.assertEqual(errors, [])

    def test_planner_version_stamped_on_every_unit(self) -> None:
        self.assertTrue(self.units)
        self.assertTrue(all(unit["planner_version"] == EXTRACTION_UNIT_PLANNER_VERSION
                            for unit in self.units))
        self.assertEqual(self.summary["planner_version"], EXTRACTION_UNIT_PLANNER_VERSION)

    def test_signal_sentences_become_clause_segment_units(self) -> None:
        # BLK-000002 两句 shall 各自成单元；非信号句不成单元
        segment_ids = {uid for uid in self.by_id if uid.startswith("UNIT-BLK-000002-S")}
        self.assertEqual(len(segment_ids), 2)
        first = self.by_id["UNIT-BLK-000002-S000"]
        self.assertEqual(first["unit_kind"], "clause_segment")
        self.assertEqual(first["source_text"], "The meter shall log events.")
        self.assertIn("requirement_candidate", first["roles"])
        self.assertEqual(first["locator"]["source_type"], "block_sentence")
        self.assertEqual(first["locator"]["source_id"], "BLK-000002#0")
        self.assertEqual(first["sentence_index"], 0)

    def test_unsignal_block_collapses_to_narrative_context_unit(self) -> None:
        narrative = self.by_id["UNIT-BLK-000003"]
        self.assertEqual(narrative["unit_kind"], "narrative")
        self.assertEqual(narrative["roles"], ["context"])

    def test_list_item_role_attached(self) -> None:
        unit = self.by_id["UNIT-BLK-000004-S000"]
        self.assertIn("list_item", unit["roles"])
        self.assertIn("requirement_candidate", unit["roles"])

    def test_row_leaf_covers_its_cells_cell_leaf_gets_own_unit(self) -> None:
        row_units = [u for u in self.units if u["unit_kind"] == "table_row"]
        cell_units = [u for u in self.units if u["unit_kind"] == "table_cell"]
        self.assertTrue(row_units)   # 参数表/规范表 row leaf
        self.assertTrue(cell_units)  # 手造 mapping/prose_grid cell leaf
        # 行单元 covers_cell_ids 覆盖该行全部 canonical cell
        row = next(u for u in row_units if u["locator"]["source_id"] == "TBL-000001-R000002")
        self.assertIn("TBL-000001-R000002-C000002", row["covers_cell_ids"])
        # cell leaf 单元带 disposition 角色与表格上下文
        target_cell = next(u for u in cell_units
                           if u["locator"]["source_id"] == "TBL-000003-R000002-C000001")
        self.assertIn("requirement_candidate", target_cell["roles"])
        self.assertEqual(target_cell["table_context"]["table_id"], "TBL-000003")
        self.assertEqual(target_cell["table_context"]["disposition"], "target")
        self.assertEqual(target_cell["locator"]["source_type"], "table_cell")
        composite_cell = next(u for u in cell_units
                              if u["locator"]["source_id"] == "TBL-000003-R000002-C000002")
        self.assertEqual(composite_cell["table_context"]["disposition"], "composite")
        self.assertIn("requirement_candidate", composite_cell["roles"])

    def test_every_nonempty_cell_traceable_exactly_once(self) -> None:
        conservation = self.summary["cell_conservation"]
        self.assertTrue(conservation["ok"])
        all_cells = {cell["cell_id"] for cell in self.cell_items}
        own = {u["table_context"]["cell_id"] for u in self.units
               if u["unit_kind"] == "table_cell"}
        covered: set[str] = set()
        for unit in self.units:
            covered.update(unit.get("covers_cell_ids") or [])
        self.assertEqual(all_cells, own | covered)
        self.assertFalse(own & covered)
        self.assertEqual(conservation["cells_total"], len(all_cells))

    def test_definitions_and_references_become_context_units(self) -> None:
        defs = [u for u in self.units if u["unit_kind"] == "definition"]
        refs = [u for u in self.units if u["unit_kind"] == "reference"]
        self.assertEqual(len(defs), 1)
        # 定义文本与权威 collect_term_entries 同口径（section 文本含子节标题行）
        self.assertEqual(
            defs[0]["source_text"],
            "event record: 3.1 event record\nA record of a metering event stored in the meter.")
        self.assertEqual(defs[0]["roles"], ["context"])
        self.assertEqual(len(refs), 1)
        self.assertIn("4.2", refs[0]["source_text"])
        self.assertEqual(refs[0]["roles"], ["context"])
        # 用到术语的正文单元挂上定义 context_refs
        self.assertIn(defs[0]["unit_id"],
                      self.by_id["UNIT-BLK-000002-S000"]["context_refs"])

    def test_source_text_hash_is_sha256_of_text(self) -> None:
        import hashlib

        for unit in self.units[:10]:
            expected = "sha256:" + hashlib.sha256(
                unit["source_text"].encode("utf-8")).hexdigest()
            self.assertEqual(unit["source_text_hash"], expected)

    def test_deterministic_rebuild_is_identical(self) -> None:
        again, _ = build_extraction_units(self.blocks, self.table_items,
                                          self.cell_items, self.dispositions)
        self.assertEqual(again, self.units)

    def test_plan_writes_and_loads_governed_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            (out_dir / "blocks.jsonl").write_text(
                "\n".join(json.dumps(b, ensure_ascii=False) for b in self.blocks) + "\n",
                encoding="utf-8")
            (out_dir / "table_items.jsonl").write_text(
                "\n".join(json.dumps(i, ensure_ascii=False) for i in self.table_items) + "\n",
                encoding="utf-8")
            (out_dir / "table_cell_items.jsonl").write_text(
                "\n".join(json.dumps(c, ensure_ascii=False) for c in self.cell_items) + "\n",
                encoding="utf-8")
            (out_dir / "table_cell_dispositions.jsonl").write_text(
                "\n".join(json.dumps(d, ensure_ascii=False) for d in self.dispositions) + "\n",
                encoding="utf-8")
            summary = plan_extraction_units(out_dir)
            self.assertEqual(summary["schema"], "extraction-unit-plan/v1")
            self.assertTrue((out_dir / "extraction_units.jsonl").is_file())
            loaded = load_extraction_units(out_dir)
            self.assertEqual(loaded, self.units)
            self.assertTrue(all(u["schema"] == EXTRACTION_UNIT_SCHEMA for u in loaded))
