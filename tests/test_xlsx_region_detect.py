"""Tests for xlsx_region_detect (WS1 wk7).

Pure-function coverage of the deterministic region boundary gate and the
multi-sheet OBIS linkage gate, plus the stub-first LLM hook. No real LLM is
called; the LLM test injects a fake ``chat`` callable.
"""
from __future__ import annotations

import unittest

from xlsx_region_detect import (
    CODE_REGION_OVERLAP,
    CODE_REGION_SPLITS_MERGE,
    LINK_KEY_CONFLICT,
    LINK_KEY_MISSING,
    LINK_LINKED,
    LINK_SINGLE_SHEET,
    XLSX_REGION_DETECT_VERSION,
    SheetTableFingerprint,
    boundary_conflicts_to_audit,
    extract_obis_keys_from_matrix,
    link_multi_sheet_tables,
    link_result_to_audit,
    propose_regions_llm,
    validate_region_boundaries,
)


class RegionBoundaryTests(unittest.TestCase):
    def test_ok_when_disjoint_regions_contain_merges(self) -> None:
        check = validate_region_boundaries(
            [(1, 1, 3, 3), (5, 1, 7, 3)],
            [(2, 2, 2, 3)],  # merge fully inside region 1
        )
        self.assertTrue(check.is_ok)
        self.assertEqual(check.conflicts, ())

    def test_overlap_detected(self) -> None:
        check = validate_region_boundaries([(1, 1, 3, 3), (2, 2, 5, 5)], [])
        self.assertEqual(check.status, "conflict")
        self.assertEqual(len(check.conflicts), 1)
        self.assertEqual(check.conflicts[0].code, CODE_REGION_OVERLAP)
        self.assertEqual(len(check.conflicts[0].regions), 2)

    def test_split_merge_detected(self) -> None:
        # Merge (2,2)-(3,3) straddles the boundary between region1 (cols 1-2)
        # and region2 (cols 3-5): one physical merged cell is cut.
        check = validate_region_boundaries(
            [(1, 1, 4, 2), (1, 3, 4, 5)],
            [(2, 2, 3, 3)],
        )
        self.assertEqual(check.status, "conflict")
        codes = {c.code for c in check.conflicts}
        self.assertIn(CODE_REGION_SPLITS_MERGE, codes)
        split = next(c for c in check.conflicts if c.code == CODE_REGION_SPLITS_MERGE)
        self.assertEqual(split.merge_range, (2, 2, 3, 3))

    def test_merge_outside_regions_is_not_flagged(self) -> None:
        check = validate_region_boundaries([(1, 1, 2, 2)], [(5, 5, 6, 6)])
        self.assertTrue(check.is_ok)

    def test_audit_payload_only_on_conflict(self) -> None:
        ok = validate_region_boundaries([(1, 1, 2, 2)], [])
        self.assertIsNone(boundary_conflicts_to_audit(ok, sheet_name="s"))
        bad = validate_region_boundaries([(1, 1, 2, 2), (2, 2, 3, 3)], [])
        payload = boundary_conflicts_to_audit(bad, sheet_name="s")
        self.assertIsNotNone(payload)
        self.assertEqual(payload["code"], "xlsx_region_boundary_conflict")
        self.assertEqual(payload["sheet_name"], "s")


class ObisExtractionTests(unittest.TestCase):
    def test_extracts_obis_and_g_form_and_hex(self) -> None:
        keys = extract_obis_keys_from_matrix(
            [["0-0:96.1.0", "desc"], ["1-1:32.0.0", "see 0x1F"]]
        )
        self.assertIn("0-0:96.1.0", keys)
        self.assertIn("1-1:32.0.0", keys)

    def test_empty_for_non_obis_table(self) -> None:
        self.assertEqual(extract_obis_keys_from_matrix([["name", "value"], ["foo", "1"]]), set())


class MultiSheetLinkTests(unittest.TestCase):
    def test_single_sheet_when_fewer_than_two_keyed_tables(self) -> None:
        fps = [SheetTableFingerprint("s1", "T1", frozenset({"0-0:96.1.0"}))]
        result = link_multi_sheet_tables(fps)
        self.assertEqual(result.status, LINK_SINGLE_SHEET)
        self.assertFalse(result.mergeable)

    def test_single_sheet_when_keyed_tables_on_one_sheet_only(self) -> None:
        fps = [
            SheetTableFingerprint("s1", "T1", frozenset({"0-0:96.1.0"})),
            SheetTableFingerprint("s1", "T2", frozenset({"1-1:32.0.0"})),
        ]
        result = link_multi_sheet_tables(fps)
        self.assertEqual(result.status, LINK_SINGLE_SHEET)

    def test_linked_when_shared_keys_across_sheets(self) -> None:
        fps = [
            SheetTableFingerprint("s1", "T1", frozenset({"0-0:96.1.0", "1-1:32.0.0"})),
            SheetTableFingerprint("s2", "T2", frozenset({"0-0:96.1.0"})),
        ]
        result = link_multi_sheet_tables(fps)
        self.assertEqual(result.status, LINK_LINKED)
        self.assertTrue(result.mergeable)
        self.assertEqual(result.conflicts, ())

    def test_key_missing_when_no_shared_keys(self) -> None:
        fps = [
            SheetTableFingerprint("s1", "T1", frozenset({"0-0:96.1.0"})),
            SheetTableFingerprint("s2", "T2", frozenset({"9-9:99.9.9"})),
        ]
        result = link_multi_sheet_tables(fps)
        self.assertEqual(result.status, LINK_KEY_MISSING)
        self.assertFalse(result.mergeable)
        self.assertTrue(result.conflicts)

    def test_key_conflict_on_intra_sheet_duplicate(self) -> None:
        # Same OBIS key in two tables on the SAME sheet = ambiguous data.
        fps = [
            SheetTableFingerprint("s1", "T1", frozenset({"0-0:96.1.0"})),
            SheetTableFingerprint("s1", "T2", frozenset({"0-0:96.1.0"})),
            SheetTableFingerprint("s2", "T3", frozenset({"0-0:96.1.0"})),
        ]
        result = link_multi_sheet_tables(fps)
        self.assertEqual(result.status, LINK_KEY_CONFLICT)
        self.assertFalse(result.mergeable)
        self.assertEqual(result.conflicts[0]["code"], "obis_key_intra_sheet_duplicate")
        self.assertEqual(result.conflicts[0]["sheet_name"], "s1")

    def test_link_audit_only_when_blocked(self) -> None:
        linked = link_multi_sheet_tables([
            SheetTableFingerprint("s1", "T1", frozenset({"0-0:96.1.0"})),
            SheetTableFingerprint("s2", "T2", frozenset({"0-0:96.1.0"})),
        ])
        self.assertIsNone(link_result_to_audit(linked))
        single = link_multi_sheet_tables([
            SheetTableFingerprint("s1", "T1", frozenset({"0-0:96.1.0"})),
        ])
        self.assertIsNone(link_result_to_audit(single))
        missing = link_multi_sheet_tables([
            SheetTableFingerprint("s1", "T1", frozenset({"0-0:96.1.0"})),
            SheetTableFingerprint("s2", "T2", frozenset({"9-9:9.9.9"})),
        ])
        audit = link_result_to_audit(missing)
        self.assertIsNotNone(audit)
        self.assertEqual(audit["code"], "xlsx_multi_sheet_link_blocked")  # type: ignore[index]


class LlmRegionHookTests(unittest.TestCase):
    def test_unavailable_without_chat(self) -> None:
        result = propose_regions_llm([["a", "b"]])
        self.assertTrue(result.is_unavailable)
        self.assertEqual(result.reason, "no_chat_supplied")

    def test_proposed_with_fake_chat_then_must_be_revalidated(self) -> None:
        fake = lambda matrix: {"regions": [[1, 1, 2, 2], [4, 1, 5, 2]]}  # noqa: E731
        result = propose_regions_llm([["a"]], chat=fake)
        self.assertTrue(result.is_proposed)
        # A proposal is still subject to the deterministic gate:
        check = validate_region_boundaries(result.regions, [])
        self.assertTrue(check.is_ok)

    def test_malformed_chat_response_is_unavailable(self) -> None:
        fake = lambda matrix: {"regions": "not-a-list"}  # noqa: E731
        result = propose_regions_llm([["a"]], chat=fake)
        self.assertTrue(result.is_unavailable)


class VersionTests(unittest.TestCase):
    def test_version_constant_exposed(self) -> None:
        self.assertEqual(XLSX_REGION_DETECT_VERSION, "xlsx-region-detect-v1")


if __name__ == "__main__":
    unittest.main()
