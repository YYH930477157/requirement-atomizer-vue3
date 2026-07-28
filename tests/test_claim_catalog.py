from __future__ import annotations

import copy
import json
import statistics
import time
import unittest
from unittest.mock import patch

import claim_catalog
import claim_ledger
from source_spans import source_alignment_fields


def _block(
    block_id: str,
    text: str,
    *,
    order: int = 1,
    block_type: str = "paragraph",
    **extra: object,
) -> dict:
    row = {
        "block_id": block_id,
        "order": order,
        "type": block_type,
        "text": text,
        "raw_text": text,
        "text_repair_checked": True,
        "text_repair_version": "identity-v1",
        "raw_to_repaired_spans": [{
            "raw_start": 0,
            "raw_end": len(text),
            "repaired_start": 0,
            "repaired_end": len(text),
            "operation": "equal",
        }],
        "section_path": ["4 Functions"],
        "noise": False,
    }
    row.update(extra)
    return row


class ClaimCatalogIdentityTests(unittest.TestCase):
    def test_same_inputs_have_same_generations_and_table_change_invalidates_both(self) -> None:
        blocks = [_block("B1", "The device records data.")]
        items = [{
            "item_id": "T1-R1",
            "table_block_id": "T1",
            "row_index": 1,
            "fields": {"Name": "A", "Value": "10 V"},
            "section_path": ["4 Functions"],
        }]
        first = claim_catalog.build_claim_catalog(blocks, items)
        second = claim_catalog.build_claim_catalog(copy.deepcopy(blocks), copy.deepcopy(items))
        self.assertEqual(first["meta"]["document_generation_id"], second["meta"]["document_generation_id"])
        self.assertEqual(first["meta"]["catalog_generation_id"], second["meta"]["catalog_generation_id"])

        changed = copy.deepcopy(items)
        changed[0]["fields"]["Value"] = "11 V"
        third = claim_catalog.build_claim_catalog(blocks, changed)
        self.assertNotEqual(first["meta"]["document_generation_id"], third["meta"]["document_generation_id"])
        self.assertNotEqual(first["meta"]["catalog_generation_id"], third["meta"]["catalog_generation_id"])

    def test_source_ruleset_change_invalidates_document_and_catalog_generations(self) -> None:
        blocks = [_block("B1", "The device records data.")]
        first = claim_catalog.build_claim_catalog(blocks, [])
        with patch.object(
            claim_catalog,
            "SOURCE_TRANSFORMATION_RULESET_VERSION",
            "source-transform-rules-vNEXT-deadbeef0000",
        ):
            changed = claim_catalog.build_claim_catalog(blocks, [])

        self.assertNotEqual(
            first["meta"]["document_generation_id"],
            changed["meta"]["document_generation_id"],
        )
        self.assertNotEqual(
            first["meta"]["catalog_generation_id"],
            changed["meta"]["catalog_generation_id"],
        )

    def test_scope_is_part_of_meta_but_not_document_generation(self) -> None:
        blocks = [_block("B1", "A complete source sentence.")]
        full = claim_catalog.build_claim_catalog(blocks, [], scope="full")
        sample = claim_catalog.build_claim_catalog(blocks, [], scope="sample")
        self.assertEqual(full["meta"]["document_generation_id"], sample["meta"]["document_generation_id"])
        self.assertEqual(sample["meta"]["scope"], "sample")
        self.assertFalse(sample["meta"]["document_closure_claimed"])


class ClaimLeafTests(unittest.TestCase):
    def test_sentence_spans_are_exact_disjoint_and_conserve_whitespace(self) -> None:
        text = "First requirement.  Second requirement; third condition.\nLast one."
        build = claim_catalog.build_claim_catalog([_block("B1", text)], [])
        rows = [row for row in build["catalog"] if row["locator"]["block_id"] == "B1"]
        self.assertGreaterEqual(len(rows), 3)
        rebuilt = "".join(text[row["locator"]["start"]:row["locator"]["end"]] for row in rows)
        self.assertEqual(rebuilt, text)
        for left, right in zip(rows, rows[1:]):
            self.assertEqual(left["locator"]["end"], right["locator"]["start"])
        self.assertEqual(build["meta"]["audit"]["unmapped_source_span_count"], 0)
        self.assertEqual(build["meta"]["audit"]["overlapping_leaf_span_count"], 0)

    def test_abbreviation_and_decimal_do_not_create_false_sentence_boundaries(self) -> None:
        text = "Use e.g. channel A at 0.2 S accuracy. Record the result."
        build = claim_catalog.build_claim_catalog([_block("B1", text)], [])
        rows = [row for row in build["catalog"] if row["eligibility"] == "claim"]
        self.assertEqual(len(rows), 2)
        self.assertIn("0.2 S", rows[0]["text"])

    def test_mixed_alphanumeric_dotted_identifier_stays_in_one_sentence(self) -> None:
        text = "Registers 1.8.x and 2.8.x shall be supported. Record the result."

        build = claim_catalog.build_claim_catalog([_block("B1", text)], [])

        rows = [row for row in build["catalog"] if row["eligibility"] == "claim"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["text"], "Registers 1.8.x and 2.8.x shall be supported. ")
        self.assertNotIn("x", {row["text"].strip() for row in rows})

    def test_punctuation_fragments_are_conserved_without_becoming_claims(self) -> None:
        text = "The meter shall operate... It shall record data."

        build = claim_catalog.build_claim_catalog([_block("B1", text)], [])

        rows = build["catalog"]
        self.assertEqual("".join(row["text"] for row in rows), text)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(any(char.isalnum() for char in row["text"]) for row in rows))

    def test_separator_only_leaf_is_structurally_excluded(self) -> None:
        build = claim_catalog.build_claim_catalog([_block("B1", "...")], [])

        row = build["catalog"][0]
        self.assertEqual(row["eligibility"], "excluded")
        self.assertIsNone(row["owner_unit_id"])
        self.assertEqual(row["exclusion"]["reason"], "separator_only")
        self.assertEqual(row["exclusion"]["rule_id"], "catalog-separator-only")
        self.assertEqual(build["meta"]["accounting_status"], "complete")

    def test_merged_list_has_intro_and_one_leaf_per_item(self) -> None:
        text = "Available outputs:\na) relay output\nb) optical indication"
        build = claim_catalog.build_claim_catalog([_block("B1", text, list_coalesced=True)], [])
        rows = build["catalog"]
        self.assertEqual([row.get("list_role") for row in rows], ["intro", "item", "item"])
        self.assertEqual("".join(row["text"] for row in rows), text)
        self.assertEqual(build["meta"]["audit"]["parent_child_duplicate_count"], 0)
        mapping = build["meta"]["container_mappings"][0]
        self.assertEqual(mapping["kind"], "list")
        self.assertEqual(mapping["leaf_ids"], [row["claim_id"] for row in rows])

    def test_list_without_intro_keeps_first_line_once(self) -> None:
        text = "- local output\n- remote output"
        build = claim_catalog.build_claim_catalog([_block("B1", text, is_list_item=True)], [])
        rows = build["catalog"]
        self.assertEqual(len(rows), 2)
        self.assertEqual([row.get("list_role") for row in rows], ["item", "item"])
        self.assertEqual(sum("local output" in row["text"] for row in rows), 1)
        self.assertEqual("".join(row["text"] for row in rows), text)

    def test_list_container_mapping_preserves_member_ids_and_raw_locators(self) -> None:
        text = "- local output\n- remote output"
        raw = "- local  output\n- remote output"
        block = _block("B1", text, is_list_container=True)
        block["raw_text"] = raw
        block.update(source_alignment_fields(raw, text))
        block["list_items"] = [
            {
                "block_id": "B1-M1",
                "role": "item",
                "locator": {"block_id": "B1", "line": 1, "start": 0, "end": 14,
                            "position_basis": "repaired_text"},
                "raw_locator": {"block_id": "B1", "line": 1, "start": 0, "end": 15,
                                "position_basis": "raw_text"},
            },
            {
                "block_id": "B1-M2",
                "role": "item",
                "locator": {"block_id": "B1", "line": 2, "start": 15, "end": 30,
                            "position_basis": "repaired_text"},
                "raw_locator": {"block_id": "B1", "line": 2, "start": 16, "end": 31,
                                "position_basis": "raw_text"},
            },
        ]

        build = claim_catalog.build_claim_catalog([block], [])

        self.assertEqual([row["list_role"] for row in build["catalog"]], ["item", "item"])
        mapping = build["meta"]["container_mappings"][0]
        self.assertEqual(mapping["kind"], "list")
        self.assertEqual([member["block_id"] for member in mapping["members"]],
                         ["B1-M1", "B1-M2"])
        self.assertEqual(mapping["members"][0]["raw_locator"],
                         block["list_items"][0]["raw_locator"])

    def test_heading_and_unproven_noise_remain_eligible(self) -> None:
        blocks = [
            _block("H1", "4 Auxiliary outputs", block_type="heading", order=1),
            _block("N1", "Informative-looking line", order=2, noise=True),
        ]
        build = claim_catalog.build_claim_catalog(blocks, [])
        self.assertTrue(all(row["eligibility"] == "claim" for row in build["catalog"]))

    def test_legacy_non_identity_mapping_without_envelope_is_rejected(self) -> None:
        block = _block("B1", "A  repaired sentence.")
        block.pop("text_repair_checked")
        block["raw_text"] = "A repaired sentence."
        block.pop("source_alignment", None)
        block["raw_to_repaired_spans"] = [{
            "raw_start": 0,
            "raw_end": len(block["raw_text"]),
            "repaired_start": 0,
            "repaired_end": len(block["text"]),
            "operation": "replace",
        }]
        build = claim_catalog.build_claim_catalog([block], [])
        self.assertEqual(build["meta"]["audit"]["unmapped_raw_span_count"], 1)
        self.assertEqual(build["meta"]["accounting_status"], "incomplete")

    def test_unapproved_semantic_replacement_blocks_accounting(self) -> None:
        raw = "The meter shall expose the output."
        repaired = "The meter may expose the output."
        block = _block("B1", repaired)
        block["raw_text"] = raw
        block.update(source_alignment_fields(raw, repaired))

        build = claim_catalog.build_claim_catalog([block], [])

        self.assertEqual(build["meta"]["audit"]["unmapped_raw_span_count"], 1)
        self.assertEqual(build["meta"]["accounting_status"], "incomplete")

    def test_envelope_and_flat_projection_must_match_exactly(self) -> None:
        raw = "me ter"
        repaired = "meter"
        block = _block("B1", repaired)
        block["raw_text"] = raw
        block.update(source_alignment_fields(raw, repaired))
        block["raw_to_repaired_spans"] = [{
            "raw_start": 0,
            "raw_end": len(raw),
            "repaired_start": 0,
            "repaired_end": len(repaired),
            "operation": "replace",
        }]

        build = claim_catalog.build_claim_catalog([block], [])

        self.assertEqual(build["meta"]["accounting_status"], "incomplete")

    def test_identity_shortcut_does_not_bypass_corrupt_envelope(self) -> None:
        block = _block("B1", "same text")
        block.update(source_alignment_fields(block["raw_text"], block["text"]))
        block["source_alignment"]["raw_sha256"] = "sha256:" + "0" * 64

        build = claim_catalog.build_claim_catalog([block], [])

        self.assertEqual(build["meta"]["accounting_status"], "incomplete")

    def test_legacy_flat_coordinates_reject_bool_and_numeric_strings(self) -> None:
        for coordinate in (True, "0", 0.0):
            with self.subTest(coordinate=coordinate):
                block = _block("B1", "same")
                block.pop("source_alignment", None)
                block["raw_to_repaired_spans"] = [{
                    "raw_start": coordinate,
                    "raw_end": 4,
                    "repaired_start": 0,
                    "repaired_end": 4,
                    "operation": "equal",
                }]
                build = claim_catalog.build_claim_catalog([block], [])
                self.assertEqual(build["meta"]["accounting_status"], "incomplete")

    def test_equal_mapping_must_really_preserve_text(self) -> None:
        block = _block("B1", "ABC")
        block["raw_text"] = "XYZ"
        block["raw_to_repaired_spans"] = [{
            "raw_start": 0,
            "raw_end": 3,
            "repaired_start": 0,
            "repaired_end": 3,
            "operation": "equal",
        }]
        build = claim_catalog.build_claim_catalog([block], [])
        self.assertEqual(build["meta"]["audit"]["unmapped_raw_span_count"], 1)
        self.assertEqual(build["meta"]["accounting_status"], "incomplete")

    def test_claim_raw_spans_reassemble_parent_without_overlap(self) -> None:
        raw = "First  sentence. Second sentence."
        repaired = "First sentence. Second sentence."
        block = _block("B1", repaired)
        block["raw_text"] = raw
        block.update(source_alignment_fields(raw, repaired))
        build = claim_catalog.build_claim_catalog([block], [])
        rows = build["catalog"]
        self.assertEqual("".join(row["raw_text"] for row in rows), raw)
        self.assertEqual(rows[0]["raw_locator"]["start"], 0)
        self.assertEqual(rows[-1]["raw_locator"]["end"], len(raw))
        for left, right in zip(rows, rows[1:]):
            self.assertEqual(left["raw_locator"]["end"], right["raw_locator"]["start"])
        self.assertTrue(all(row["raw_mapping_status"] == "mapped" for row in rows))
        self.assertEqual(build["meta"]["audit"]["overlapping_raw_span_count"], 0)
        repaired_leaf = next(row for row in rows if "First sentence" in row["text"])
        lineage = repaired_leaf["source_alignment_lineage"]
        self.assertEqual(lineage["kind"], "parent_alignment")
        self.assertEqual(
            lineage["parent_alignment_version"],
            block["source_alignment"]["version"],
        )
        parent_rules = {
            opcode["transformation"]["rule_id"]
            for opcode in block["source_alignment"]["opcodes"]
            if opcode["tag"] != "equal"
        }
        leaf_parent_rules = {
            opcode["transformation"]["rule_id"]
            for opcode in lineage["parent_opcode_refs"]
            if opcode["tag"] != "equal"
        }
        self.assertEqual(leaf_parent_rules, parent_rules)
        self.assertNotEqual(repaired_leaf["text_repair_version"], "identity-v1")

    def test_pdf_repair_provenance_keeps_replayed_word_repair_mapped(self) -> None:
        from parsers.pdf_parser import (
            PDF_TEXT_REPAIR_VERSION,
            defragment_text_with_audit,
            text_repair_vocabulary_fingerprint,
        )
        from source_spans import pdf_text_repair_provenance

        raw = "The m eter shall record data."
        repaired, events = defragment_text_with_audit(raw)
        block = _block("B1", repaired)
        block["raw_text"] = raw
        block["text_repair_version"] = PDF_TEXT_REPAIR_VERSION
        block["text_repairs"] = events
        block.update(source_alignment_fields(
            raw,
            repaired,
            repair_provenance=pdf_text_repair_provenance(
                PDF_TEXT_REPAIR_VERSION,
                text_repair_vocabulary_fingerprint(),
            ),
        ))

        build = claim_catalog.build_claim_catalog([block], [])

        self.assertEqual(build["meta"]["accounting_status"], "complete")
        self.assertEqual(build["catalog"][0]["raw_mapping_status"], "mapped")
        self.assertEqual(
            build["catalog"][0]["text_repair_version"],
            PDF_TEXT_REPAIR_VERSION,
        )

    def test_legacy_flat_mapping_rejects_conflicting_operation_alias(self) -> None:
        block = _block("B1", "same")
        block.pop("source_alignment", None)
        block["raw_to_repaired_spans"][0]["tag"] = "replace"

        build = claim_catalog.build_claim_catalog([block], [])

        self.assertEqual(build["meta"]["accounting_status"], "incomplete")

    def test_crossing_flat_mapping_is_rejected(self) -> None:
        block = _block("B1", "BAA")
        block["raw_text"] = "ABA"
        block.pop("source_alignment", None)
        block["raw_to_repaired_spans"] = [
            {"raw_start": 0, "raw_end": 1, "repaired_start": 2, "repaired_end": 3,
             "operation": "equal"},
            {"raw_start": 1, "raw_end": 3, "repaired_start": 0, "repaired_end": 2,
             "operation": "equal"},
        ]
        build = claim_catalog.build_claim_catalog([block], [])
        self.assertEqual(build["meta"]["audit"]["unmapped_raw_span_count"], 1)
        self.assertEqual(build["meta"]["accounting_status"], "incomplete")

    def test_pdf_region_is_preserved_on_claim(self) -> None:
        region = {"page_number": 7, "bbox": [10, 20, 100, 40],
                  "page_width": 600, "page_height": 800}
        block = _block("B1", "A source sentence.", page_number=7, pdf_regions=[region])
        row = claim_catalog.build_claim_catalog([block], [])["catalog"][0]
        self.assertEqual(row["region_evidence"]["source_format"], "pdf")
        self.assertEqual(row["region_evidence"]["pdf_regions"], [region])

    def test_proven_repeated_page_furniture_is_structurally_excluded(self) -> None:
        blocks = [
            _block(
                f"F{page}", "CONFIDENTIAL", order=page, noise=True, page_number=page,
                pdf_regions=[{"page_number": page, "bbox": [10, 10, 100, 25],
                              "page_width": 600, "page_height": 800}],
            )
            for page in range(1, 4)
        ]
        build = claim_catalog.build_claim_catalog(blocks, [])
        self.assertTrue(all(row["eligibility"] == "excluded" for row in build["catalog"]))
        self.assertTrue(all(row["exclusion"]["reason"] == "repeated_page_furniture"
                            for row in build["catalog"]))


class ClaimTableTests(unittest.TestCase):
    def test_table_items_are_leaves_and_parent_is_only_a_container_mapping(self) -> None:
        table = _block(
            "TB1", "Name | Value\nA | 10 V\nB | 20 V", block_type="table",
            headers=["Name", "Value"], data_rows=[["A", "10 V"], ["B", "20 V"]],
        )
        items = [
            {"item_id": "T1-R2", "table_block_id": "TB1", "row_index": 2,
             "fields": {"Name": "A", "Value": "10 V"}, "section_path": ["4 Functions"]},
            {"item_id": "T1-R3", "table_block_id": "TB1", "row_index": 3,
             "fields": {"Name": "B", "Value": "20 V"}, "section_path": ["4 Functions"]},
        ]
        build = claim_catalog.build_claim_catalog([table], items)
        self.assertEqual([row["source_kind"] for row in build["catalog"]], ["table_row", "table_row"])
        self.assertEqual([row["locator"]["table_item_id"] for row in build["catalog"]],
                         ["T1-R2", "T1-R3"])
        mapping = build["meta"]["container_mappings"][0]
        self.assertEqual(mapping["container_block_id"], "TB1")
        self.assertEqual(mapping["leaf_ids"], [row["claim_id"] for row in build["catalog"]])

    def test_table_fallback_is_bounded_by_rows_and_characters(self) -> None:
        rows = [[f"row-{index}", "x" * 110] for index in range(45)]
        table = _block(
            "TB1", "truncated display", block_type="table", headers=["Name", "Value"],
            data_rows=rows, rows=46, text_truncated=True,
        )
        build = claim_catalog.build_claim_catalog([table], [])
        leaves = build["catalog"]
        self.assertGreaterEqual(len(leaves), 3)
        self.assertTrue(all(row["source_kind"] == "table_fallback" for row in leaves))
        self.assertTrue(all(row["locator"]["row_end"] - row["locator"]["row_start"] <= 20
                            for row in leaves))
        self.assertTrue(all(len(row["text"]) <= claim_catalog.TABLE_FALLBACK_MAX_CHARS
                            for row in leaves))
        self.assertEqual(build["meta"]["audit"]["parse_incomplete_count"], 0)

    def test_overlong_table_fallback_splits_cells_then_sentences_then_windows(self) -> None:
        sentence_cell = ("A" * 1100) + ". " + ("B" * 1100) + "."
        window_cell = "C" * 4500
        table = _block(
            "TB1",
            "fallback display",
            block_type="table",
            headers=["First", "Second"],
            header_row_count=1,
            data_rows=[["X" * 1200, "Y" * 1200], [sentence_cell, window_cell]],
        )

        fragments = claim_catalog._fallback_fragments(table)

        self.assertTrue(all(len(fragment["text"]) <= claim_catalog.TABLE_FALLBACK_MAX_CHARS
                            for fragment in fragments))
        methods = {fragment["split_method"] for fragment in fragments}
        self.assertTrue({"cell", "sentence", "window"}.issubset(methods))
        for row_index, column_index, original in (
            (1, 0, "X" * 1200),
            (1, 1, "Y" * 1200),
            (2, 0, sentence_cell),
            (2, 1, window_cell),
        ):
            rebuilt = "".join(
                fragment["text"] for fragment in fragments
                if fragment["row_index"] == row_index
                and fragment["column_index"] == column_index
            )
            self.assertEqual(rebuilt, original)

    def test_table_without_full_rows_is_accounting_incomplete(self) -> None:
        table = _block(
            "TB1", "x" * 5000, block_type="table", headers=["Name"], rows=100,
            text_truncated=True,
        )
        build = claim_catalog.build_claim_catalog([table], [])
        self.assertEqual(build["meta"]["accounting_status"], "incomplete")
        self.assertEqual(build["meta"]["audit"]["parse_incomplete_count"], 1)
        self.assertEqual(len(build["catalog"]), 0)

    def test_empty_data_rows_with_unaccounted_text_is_incomplete(self) -> None:
        table = _block(
            "TB1",
            "Name | Requirement\nR1 | The device shall record status.",
            block_type="table",
            headers=["Name", "Requirement"],
            header_row_count=1,
            data_rows=[],
        )

        build = claim_catalog.build_claim_catalog([table], [])

        self.assertEqual(build["catalog"], [])
        self.assertEqual(build["meta"]["audit"]["parse_incomplete_count"], 1)
        self.assertEqual(build["meta"]["accounting_status"], "incomplete")

    def test_declared_table_rows_must_match_structured_data_rows(self) -> None:
        table = _block(
            "TB1",
            "Name | Requirement\nR1 | GET",
            block_type="table",
            headers=["Name", "Requirement"],
            header_row_count=1,
            rows=3,
            data_rows=[["R1", "GET"]],
        )

        build = claim_catalog.build_claim_catalog([table], [])

        self.assertEqual(build["catalog"], [])
        self.assertEqual(build["meta"]["audit"]["parse_incomplete_count"], 1)
        self.assertEqual(build["meta"]["accounting_status"], "incomplete")

    def test_header_only_table_is_not_a_false_incomplete(self) -> None:
        table = _block(
            "TB1",
            "Name | Requirement",
            block_type="table",
            headers=["Name", "Requirement"],
            header_row_count=1,
            rows=1,
            data_rows=[],
        )

        build = claim_catalog.build_claim_catalog([table], [])

        self.assertEqual(build["catalog"], [])
        self.assertEqual(build["meta"]["audit"]["parse_incomplete_count"], 0)
        self.assertEqual(build["meta"]["accounting_status"], "complete")

    def test_partial_table_items_do_not_hide_parser_incomplete_state(self) -> None:
        table = _block(
            "TB1", "ID | Requirement\nR1 | GET", block_type="table",
            headers=["ID", "Requirement"], data_rows=[["R1", "GET"]],
            parse_incomplete=True,
            parse_incomplete_reason={"code": "xlsx_row_limit"},
        )
        item = {
            "item_id": "T1-R2", "table_block_id": "TB1", "row_index": 2,
            "fields": {"ID": "R1", "Requirement": "GET"},
            "text": "ID=R1 | Requirement=GET",
            "raw_text": "ID=R1 | Requirement=GET",
            "section_path": ["4 Functions"],
        }
        build = claim_catalog.build_claim_catalog([table], [item])
        self.assertEqual(len(build["catalog"]), 1)
        self.assertEqual(build["meta"]["audit"]["parse_incomplete_count"], 1)
        self.assertEqual(build["meta"]["accounting_status"], "incomplete")
        self.assertTrue(build["meta"]["container_mappings"][0]["parse_incomplete"])


class ClaimOwnerTests(unittest.TestCase):
    def test_every_eligible_claim_has_exactly_one_owner_and_prompt_contains_full_text(self) -> None:
        blocks = [
            _block("B1", "First capability. Second capability.", order=1),
            _block("B2", "Third capability.", order=2),
        ]
        build = claim_catalog.build_claim_catalog(blocks, [], target_chars=30)
        owners = {unit["unit_id"]: unit for unit in build["units"]}
        for row in build["catalog"]:
            self.assertIn(row["owner_unit_id"], owners)
            self.assertIn(row["claim_id"], owners[row["owner_unit_id"]]["claim_ids"])
            self.assertIn(row["text"], owners[row["owner_unit_id"]]["prompt"])
        audit = build["meta"]["audit"]
        self.assertEqual(audit["orphan_claim_count"], 0)
        self.assertEqual(audit["multi_owner_count"], 0)

    def test_generation_payload_is_json_serializable(self) -> None:
        build = claim_catalog.build_claim_catalog([_block("B1", "One sentence.")], [])
        json.dumps(build, ensure_ascii=False)


class ClaimCatalogScaleTests(unittest.TestCase):
    def test_500_block_catalog_p50_and_snapshot_size_stay_bounded(self) -> None:
        blocks = [
            _block(
                f"B{index:04d}",
                f"Clause {index}. The device shall retain channel {index} configuration.",
                order=index,
            )
            for index in range(1, 501)
        ]

        claim_catalog.build_claim_catalog(blocks, [])  # Warm imports and regex caches.
        elapsed: list[float] = []
        build: dict = {}
        for _ in range(5):
            started = time.perf_counter()
            build = claim_catalog.build_claim_catalog(blocks, [])
            elapsed.append(time.perf_counter() - started)

        shadow = claim_ledger.build_shadow_ledger(build, [], route_mode="stub")
        snapshot_bytes = sum(
            len((json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
            for row in [*build["catalog"], *shadow["ledger"]]
        )

        self.assertLessEqual(statistics.median(elapsed), 1.0)
        self.assertLessEqual(snapshot_bytes, 10 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()


class ParentChildDuplicateTests(unittest.TestCase):
    def test_containment_pair_counts_once(self) -> None:
        from claim_catalog import _parent_child_duplicate_count
        rows = [
            {"locator": {"block_id": "B1", "start": 0, "end": 50}},
            {"locator": {"block_id": "B1", "start": 10, "end": 20}},
            {"locator": {"block_id": "B1", "start": 60, "end": 80}},
        ]
        self.assertEqual(_parent_child_duplicate_count(rows), 1)

    def test_disjoint_and_cross_block_do_not_count(self) -> None:
        from claim_catalog import _parent_child_duplicate_count
        rows = [
            {"locator": {"block_id": "B1", "start": 0, "end": 50}},
            {"locator": {"block_id": "B1", "start": 60, "end": 80}},
            {"locator": {"block_id": "B2", "start": 10, "end": 20}},
        ]
        self.assertEqual(_parent_child_duplicate_count(rows), 0)

    def test_equal_span_is_not_containment(self) -> None:
        from claim_catalog import _parent_child_duplicate_count
        rows = [
            {"locator": {"block_id": "B1", "start": 0, "end": 50}},
            {"locator": {"block_id": "B1", "start": 0, "end": 50}},
        ]
        self.assertEqual(_parent_child_duplicate_count(rows), 0)
