from __future__ import annotations

import unittest

import claim_catalog
from claim_focus import ClaimFocusError, build_claim_focus_adapter
from tests.test_claim_catalog import _block


class ClaimFocusAdapterTests(unittest.TestCase):
    def test_text_and_list_claims_use_exact_source_spans(self) -> None:
        block = _block("B1", "The product shall work.\n- It shall log events.")
        claims = claim_catalog.build_claim_catalog([block], [])["catalog"]

        adapters = [build_claim_focus_adapter(row, [block], []) for row in claims]

        self.assertTrue(all(row["kind"] in {"text_span", "list_item"} for row in adapters))
        for claim, adapter in zip(claims, adapters, strict=True):
            self.assertEqual(block["text"][adapter["start"]:adapter["end"]], claim["text"])

    def test_stale_text_locator_fails_before_execution(self) -> None:
        block = _block("B1", "The product shall work.")
        claim = claim_catalog.build_claim_catalog([block], [])["catalog"][0]
        changed = {**block, "text": "Changed source."}

        with self.assertRaisesRegex(ClaimFocusError, "no longer matches"):
            build_claim_focus_adapter(claim, [changed], [])

    def test_table_item_uses_field_identity_without_prose_substring_assumption(self) -> None:
        table = _block(
            "TB1",
            "rendered summary does not contain the canonical row",
            block_type="table",
            headers=["Name", "Value"],
            data_rows=[["A", "10 V"]],
        )
        item = {
            "item_id": "T1-R2",
            "table_block_id": "TB1",
            "row_index": 2,
            "fields": {"Name": "A", "Value": "10 V"},
            "section_path": ["4 Functions"],
        }
        claim = claim_catalog.build_claim_catalog([table], [item])["catalog"][0]

        adapter = build_claim_focus_adapter(claim, [table], [item])

        self.assertEqual(adapter["kind"], "table_item")
        self.assertEqual(adapter["table_item_id"], "T1-R2")
        self.assertEqual(adapter["row_index"], 2)
        self.assertTrue(adapter["field_identity_hash"].startswith("sha256:"))

    def test_stale_table_item_field_identity_fails(self) -> None:
        table = _block(
            "TB1", "rendered", block_type="table",
            headers=["Name", "Value"], data_rows=[["A", "10 V"]],
        )
        item = {
            "item_id": "T1-R2", "table_block_id": "TB1", "row_index": 2,
            "fields": {"Name": "A", "Value": "10 V"},
            "section_path": ["4 Functions"],
        }
        claim = claim_catalog.build_claim_catalog([table], [item])["catalog"][0]
        changed = {**item, "fields": {"Name": "A", "Value": "20 V"}}

        with self.assertRaisesRegex(ClaimFocusError, "field identity changed"):
            build_claim_focus_adapter(claim, [table], [changed])

    def test_table_fallback_uses_bounded_row_window(self) -> None:
        rows = [[f"row-{index}", "x" * 110] for index in range(45)]
        table = _block(
            "TB1",
            "truncated display",
            block_type="table",
            headers=["Name", "Value"],
            data_rows=rows,
            rows=46,
            text_truncated=True,
        )
        claim = claim_catalog.build_claim_catalog([table], [])["catalog"][0]

        adapter = build_claim_focus_adapter(claim, [table], [])

        self.assertEqual(adapter["kind"], "table_data_rows")
        self.assertEqual(
            len(adapter["row_hashes"]),
            adapter["row_end"] - adapter["row_start"],
        )
        self.assertLessEqual(adapter["row_end"] - adapter["row_start"], 20)

    def test_table_fallback_translates_absolute_rows_past_headers(self) -> None:
        table = _block(
            "TB1",
            "truncated display",
            block_type="table",
            headers=["Name", "Value"],
            header_row_count=1,
            data_rows=[["A", "10 V"], ["B", "20 V"]],
        )
        claim = claim_catalog.build_claim_catalog([table], [])["catalog"][0]

        adapter = build_claim_focus_adapter(claim, [table], [])

        self.assertEqual((adapter["row_start"], adapter["row_end"]), (1, 3))
        self.assertEqual(len(adapter["row_hashes"]), 2)


if __name__ == "__main__":
    unittest.main()
