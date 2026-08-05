"""End-to-end tests for xlsx_parser region-detection wiring (WS1 wk7).

Uses openpyxl to synthesize real .xlsx workbooks (no real LLM, no real
external dependency beyond openpyxl which is already installed). Verifies:
  * multi-sheet OBIS key_missing => honest parse_incomplete on the keyed
    table blocks (never a silent merge);
  * cross-sheet shared keys => linked, no audit signal;
  * single sheet without OBIS => legacy behaviour unchanged (no new audit).
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from parsers.xlsx_parser import extract_xlsx


def _write_workbook(path: Path, sheets: dict[str, list[list[str]]]) -> None:
    wb = Workbook()
    first = True
    for name, rows in sheets.items():
        ws = wb.active if first else wb.create_sheet(title=name)
        first = False
        ws.title = name
        for row_index, row in enumerate(rows, start=1):
            for column_index, value in enumerate(row, start=1):
                ws.cell(row=row_index, column=column_index, value=value)
    wb.save(path)


class MultiSheetObisLinkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(_cleanup, self.tmp)

    def _table_blocks(self, blocks):
        return [b for b in blocks if b.get("type") == "table"]

    def test_key_missing_blocks_silently_marked(self) -> None:
        # Two keyed tables across two sheets with ZERO shared keys.
        path = self.tmp / "no_shared.xlsx"
        _write_workbook(path, {
            "s1": [["OBIS", "Desc"], ["0-0:96.1.0", "clock"]],
            "s2": [["OBIS", "Desc"], ["1-1:32.0.0", "assoc"]],
        })
        blocks, _items, _cells = extract_xlsx(path)
        tables = self._table_blocks(blocks)
        self.assertEqual(len(tables), 2)
        # Both keyed tables must honestly carry the link-block audit.
        for block in tables:
            self.assertTrue(block["parse_incomplete"], block["table_id"])
            reason = block["parse_incomplete_reason"]
            self.assertIsNotNone(reason)
            # Either as the main reason or as an additional_reasons entry.
            payloads = []
            if isinstance(reason, dict) and reason.get("code") == "xlsx_multi_sheet_link_blocked":
                payloads.append(reason)
            for extra in (reason.get("additional_reasons") or []) if isinstance(reason, dict) else []:
                if isinstance(extra, dict) and extra.get("code") == "xlsx_multi_sheet_link_blocked":
                    payloads.append(extra)
            self.assertTrue(payloads, f"no link-block audit on {block['table_id']}")
            self.assertEqual(payloads[0]["status"], "key_missing")

    def test_shared_keys_linked_no_audit(self) -> None:
        path = self.tmp / "shared.xlsx"
        _write_workbook(path, {
            "s1": [["OBIS", "Desc"], ["0-0:96.1.0", "clock"]],
            "s2": [["OBIS", "Ref"], ["0-0:96.1.0", "see s1"]],
        })
        blocks, _items, _cells = extract_xlsx(path)
        tables = self._table_blocks(blocks)
        for block in tables:
            # Linked => no link-block audit: parse_incomplete stays at whatever
            # the sheet-level parse produced (False for this clean workbook).
            reason = block.get("parse_incomplete_reason")
            codes = []
            if isinstance(reason, dict):
                codes.append(reason.get("code"))
                codes.extend(
                    e.get("code") for e in (reason.get("additional_reasons") or [])
                    if isinstance(e, dict)
                )
            self.assertNotIn("xlsx_multi_sheet_link_blocked", codes)

    def test_single_sheet_legacy_behaviour_unchanged(self) -> None:
        path = self.tmp / "single.xlsx"
        _write_workbook(path, {"only": [["Name", "Value"], ["foo", "1"], ["bar", "2"]]})
        blocks, items, cells = extract_xlsx(path)
        tables = self._table_blocks(blocks)
        self.assertEqual(len(tables), 1)
        self.assertFalse(tables[0]["parse_incomplete"])
        # parse_incomplete_reason absent or None — legacy default.
        self.assertFalse(tables[0].get("parse_incomplete_reason"))


def _cleanup(path: Path) -> None:
    import shutil
    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
