from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from atomize import (
    AtomizerInputError,
    DEFAULT_ACCESS_RIGHT_CLIENTS,
    build_atomic_candidates,
    build_table_artifacts,
    build_quality_report,
    extract_matrix_facts,
    interpret_table_matrix,
    parse_access_rights,
    run_atomizer_pipeline,
)


class AtomizeTableTests(unittest.TestCase):
    def test_interpret_table_matrix_combines_repeated_header_rows(self) -> None:
        matrix = [
            ["Customer application process", "xDLMS Service", "xDLMS Service"],
            ["Customer application process", '"GET"', '"ACTION"'],
            ["Public customer", "X", ""],
        ]

        model = interpret_table_matrix(matrix)

        self.assertEqual(model["header_row_count"], 2)
        self.assertEqual(model["headers"][0], "Customer application process")
        self.assertEqual(model["headers"][1], 'xDLMS Service / "GET"')

        facts = extract_matrix_facts(model["headers"], model["data_rows"][0])

        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["subject"], "Public customer")
        self.assertEqual(facts[0]["predicate_header"], 'xDLMS Service / "GET"')

    def test_build_atomic_candidates_creates_matrix_requirement(self) -> None:
        table_items = [
            {
                "item_id": "TBL-000001-R000003",
                "table_block_id": "BLK-000010",
                "table_title": "Table 1 - Services xDLMS",
                "row_index": 3,
                "section_path": ["Terms and Definitions", "Customers"],
                "doc_region": "body",
                "fields": {"Customer application process": "Public customer", 'xDLMS Service / "GET"': "X"},
                "matrix_facts": [
                    {
                        "subject_header": "Customer application process",
                        "subject": "Public customer",
                        "predicate_header": 'xDLMS Service / "GET"',
                        "marker": "X",
                        "value": True,
                        "relation": "allowed",
                    }
                ],
                "domain_tags": ["association", "dlms_cosem"],
                "kb_matches": [],
            }
        ]

        candidates = build_atomic_candidates([], table_items, include_regions={"body"})

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["requirement_type"], "capability_matrix")
        self.assertEqual(candidates[0]["requirement"], 'Public customer shall support xDLMS Service: "GET".')

    def test_build_table_artifacts_creates_block_items_matrix_facts_and_cosem_context(self) -> None:
        matrix = [
            ["Object/attribute name", "CL", "Value", "Access rights RC/PC/SC/LC", "xDLMS Service", "xDLMS Service"],
            ["Object/attribute name", "CL", "Value", "Access rights RC/PC/SC/LC", '"GET"', '"ACTION"'],
            ["SAP Assignment", "17", "0-0:41.0.0.255", ""],
            ["logical_name", "", "0000290000FF", "R-/--/R-/RW"],
            ["Public customer", "", "", "", "X", ""],
        ]

        block, items = build_table_artifacts(
            matrix,
            table_id="TBL-000001",
            block_id="BLK-000010",
            order=10,
            table_title="Table 22 - SAP assignment",
            section_path=["COSEM objects"],
            knowledge_bases=[],
        )

        self.assertEqual(block["type"], "table")
        self.assertEqual(block["rows"], 5)
        self.assertEqual(block["table_title"], "Table 22 - SAP assignment")
        self.assertEqual(items[0]["item_id"], "TBL-000001-R000003")
        self.assertEqual(items[0]["cosem_object_context"]["object_name"], "SAP Assignment")
        self.assertEqual(items[0]["cosem_object_context"]["class_id"], 17)
        self.assertTrue(any(item["matrix_facts"] for item in items))

    def test_stable_req_id_does_not_depend_on_candidate_order(self) -> None:
        first_block = {
            "block_id": "BLK-000010",
            "type": "paragraph",
            "text": "The meter shall support xDLMS GET service.",
            "section_path": ["Scope"],
            "domain_tags": ["dlms_cosem"],
            "kb_matches": [],
            "doc_region": "body",
            "noise": False,
        }
        second_block = {
            "block_id": "BLK-000011",
            "type": "paragraph",
            "text": "The meter shall support push notification service.",
            "section_path": ["Scope"],
            "domain_tags": ["communication_profile"],
            "kb_matches": [],
            "doc_region": "body",
            "noise": False,
        }

        original_order = build_atomic_candidates([first_block, second_block], [], include_regions={"body"})
        reversed_order = build_atomic_candidates([second_block, first_block], [], include_regions={"body"})

        original_by_source = {row["source_id"]: row for row in original_order}
        reversed_by_source = {row["source_id"]: row for row in reversed_order}

        self.assertEqual(original_by_source["BLK-000010"]["req_id"], "AREQ-000001")
        self.assertEqual(reversed_by_source["BLK-000010"]["req_id"], "AREQ-000002")
        self.assertEqual(
            original_by_source["BLK-000010"]["stable_req_id"],
            reversed_by_source["BLK-000010"]["stable_req_id"],
        )
        self.assertRegex(original_by_source["BLK-000010"]["stable_req_id"], r"^SREQ-[0-9A-F]{16}$")

    def test_paragraph_candidate_keeps_source_context_and_condition(self) -> None:
        blocks = [
            {
                "block_id": "BLK-000010",
                "type": "paragraph",
                "text": "When the meter is in test mode. The display shall show all segments.",
                "section_path": ["Display"],
                "domain_tags": ["meter_function"],
                "kb_matches": [],
                "doc_region": "body",
                "noise": False,
            }
        ]

        candidates = build_atomic_candidates(blocks, [], include_regions={"body"})

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["condition"], "When the meter is in test mode.")
        self.assertEqual(candidates[0]["source_context"]["prev_sentence"], "When the meter is in test mode.")
        self.assertEqual(
            candidates[0]["source_context"]["paragraph_text"],
            "When the meter is in test mode. The display shall show all segments.",
        )

    def test_plain_paragraph_candidate_keeps_context_without_condition(self) -> None:
        blocks = [
            {
                "block_id": "BLK-000010",
                "type": "paragraph",
                "text": "The meter shall support xDLMS GET service.",
                "section_path": ["Scope"],
                "domain_tags": ["dlms_cosem"],
                "kb_matches": [],
                "doc_region": "body",
                "noise": False,
            }
        ]

        candidates = build_atomic_candidates(blocks, [], include_regions={"body"})

        self.assertEqual(candidates[0]["condition"], None)
        self.assertEqual(candidates[0]["source_context"]["paragraph_text"], "The meter shall support xDLMS GET service.")
        self.assertEqual(candidates[0]["source_context"]["prev_sentence"], None)

    def test_requirement_like_previous_sentence_is_not_condition(self) -> None:
        blocks = [
            {
                "block_id": "BLK-000010",
                "type": "paragraph",
                "text": "When the relay shall disconnect the load. The display shall show all segments.",
                "section_path": ["Display"],
                "domain_tags": ["meter_function"],
                "kb_matches": [],
                "doc_region": "body",
                "noise": False,
            }
        ]

        candidates = build_atomic_candidates(blocks, [], include_regions={"body"})
        by_requirement = {row["requirement"]: row for row in candidates}

        self.assertIsNone(by_requirement["The display shall show all segments."]["condition"])

    def test_cosem_attribute_candidate_uses_object_context_and_access_rights(self) -> None:
        table_items = [
            {
                "item_id": "TBL-000031-R000003",
                "table_block_id": "BLK-000608",
                "table_title": "Table 22 - SAP assignment",
                "row_index": 3,
                "section_path": ["COSEM objects"],
                "doc_region": "body",
                "fields": {
                    "#": "1",
                    "Object/attribute name": "logical_name",
                    "Type": "octet-string[6]",
                    "Value": "0000290000FF",
                    "Access rights RC/PC/SC/LC": "R-/--/R-/RW",
                },
                "matrix_facts": [],
                "cosem_object_context": {
                    "source_item_id": "TBL-000031-R000002",
                    "row_index": 2,
                    "object_name": "SAP Assignment",
                    "class_id": 17,
                    "obis": "0-0:41.0.0.255",
                },
                "domain_tags": ["cosem_object", "access_control"],
                "kb_matches": [],
            }
        ]

        candidates = build_atomic_candidates([], table_items, include_regions={"body"})

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["object"], "SAP Assignment.logical_name")
        self.assertIn("CL 17", candidate["requirement"])
        self.assertIn("OBIS 0-0:41.0.0.255", candidate["requirement"])
        access = candidate["parameters"]["access_rights_by_client"]
        self.assertFalse(access["clients"][1]["allowed"])
        self.assertTrue(access["clients"][3]["write"])

    def test_parse_access_rights_splits_client_columns(self) -> None:
        parsed = parse_access_rights("R-/--/R-/RW")

        self.assertEqual(parsed["clients"][0]["client"], "RC")
        self.assertTrue(parsed["clients"][0]["read"])
        self.assertFalse(parsed["clients"][1]["allowed"])
        self.assertTrue(parsed["clients"][3]["write"])

    def test_default_access_right_clients_match_knowledge_base(self) -> None:
        kb_path = Path(__file__).resolve().parents[1] / "knowledge_bases" / "energy_metering_protocol_layer.json"
        payload = json.loads(kb_path.read_text(encoding="utf-8"))
        access_model = next(entry for entry in payload["entries"] if entry["id"] == "KB-L2-ACCESS-RIGHTS-MODEL")
        kb_clients = {row["code"]: row["meaning"] for row in access_model["client_columns"]}

        self.assertEqual(set(DEFAULT_ACCESS_RIGHT_CLIENTS), {"RC", "PC", "SC", "LC"})
        for code, name in DEFAULT_ACCESS_RIGHT_CLIENTS.items():
            self.assertEqual(name.lower(), kb_clients[code].lower())

    def test_build_atomic_candidates_creates_cosem_object_instance(self) -> None:
        table_items = [
            {
                "item_id": "TBL-000031-R000002",
                "table_block_id": "BLK-000608",
                "table_title": "Table 22 - SAP assignment",
                "row_index": 2,
                "section_path": ["COSEM objects"],
                "doc_region": "body",
                "fields": {
                    "Object/attribute name": "SAP Assignment",
                    "CL": "17",
                    "Value": "0-0:41.0.0.255",
                },
                "matrix_facts": [],
                "cosem_object_context": {
                    "source_item_id": "TBL-000031-R000002",
                    "row_index": 2,
                    "object_name": "SAP Assignment",
                    "class_id": 17,
                    "obis": "0-0:41.0.0.255",
                },
                "domain_tags": ["cosem_object"],
                "kb_matches": [],
            }
        ]

        candidates = build_atomic_candidates([], table_items, include_regions={"body"})

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["requirement_type"], "cosem_object_instance")
        self.assertIn("CL 17", candidates[0]["requirement"])
        self.assertEqual(candidates[0]["parameters"]["cosem_object"]["obis"], "0-0:41.0.0.255")

    def test_build_atomic_candidates_creates_event_definition(self) -> None:
        table_items = [
            {
                "item_id": "TBL-000007-R000003",
                "table_block_id": "BLK-000250",
                "table_title": "Table 7 - Events",
                "row_index": 3,
                "section_path": ["Events"],
                "doc_region": "body",
                "fields": {
                    "Group number": "1",
                    "Subgroup number": "10",
                    "Event subgroup description": "Standard",
                    "Event number": "1",
                    "Description of the event": "Reboot with data loss",
                },
                "matrix_facts": [],
                "domain_tags": ["event"],
                "kb_matches": [],
            }
        ]

        candidates = build_atomic_candidates([], table_items, include_regions={"body"})

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["requirement_type"], "event_definition")
        self.assertEqual(candidates[0]["object"], "Event G1-SG10-E1")
        self.assertEqual(candidates[0]["parameters"]["event_number"], 1)

    def test_build_atomic_candidates_creates_valued_matrix_requirement(self) -> None:
        table_items = [
            {
                "item_id": "TBL-000002-R000003",
                "table_block_id": "BLK-000220",
                "table_title": "Table 2 - Local associations and remote",
                "row_index": 3,
                "section_path": ["Associations"],
                "doc_region": "body",
                "fields": {
                    "Customer application process": "Public customer",
                    "Server application process / Management Logical Device": "Without security",
                    "Server application process / Measuring logic devices": "",
                },
                "matrix_facts": [],
                "domain_tags": ["association", "security_policy"],
                "kb_matches": [],
            }
        ]

        candidates = build_atomic_candidates([], table_items, include_regions={"body"})

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["requirement_type"], "association_security_matrix")
        self.assertIn("Without security", candidates[0]["requirement"])

    def test_build_atomic_candidates_creates_security_suite_definition(self) -> None:
        table_items = [
            {
                "item_id": "TBL-000003-R000002",
                "table_block_id": "BLK-000230",
                "table_title": "Table 3 - Set of security",
                "row_index": 2,
                "section_path": ["Security"],
                "doc_region": "body",
                "fields": {
                    "ID": "1",
                    "Name": "ECDH-ECDSA-AES-GCM-128-SHA-256",
                    "Authenticated encryption": "AES-GCM-128",
                    "Digital signature": "ECDSA with P-256",
                    "Key Agreement": "ECDH with P-256",
                    "\"Hash\"": "SHA-256",
                    "Transport key": "AES-128 key wrap",
                    "Compression": "V.44",
                },
                "matrix_facts": [],
                "domain_tags": ["security_policy"],
                "kb_matches": [],
            }
        ]

        candidates = build_atomic_candidates([], table_items, include_regions={"body"})

        self.assertEqual(candidates[0]["requirement_type"], "security_suite_definition")
        self.assertEqual(candidates[0]["parameters"]["hash"], "SHA-256")

    def test_build_atomic_candidates_creates_security_policy_and_measurement_rows(self) -> None:
        table_items = [
            {
                "item_id": "TBL-000004-R000002",
                "table_block_id": "BLK-000240",
                "table_title": "Table 4 - Security policy",
                "row_index": 2,
                "section_path": ["Security"],
                "doc_region": "body",
                "fields": {"bit": "0", "Security Policy - Security States": "Not used, must be set to \"0\""},
                "matrix_facts": [],
                "domain_tags": ["security_policy"],
                "kb_matches": [],
            },
            {
                "item_id": "TBL-000010-R000002",
                "table_block_id": "BLK-000300",
                "table_title": "Table 10 - Measurement quantities",
                "row_index": 2,
                "section_path": ["Measurement"],
                "doc_region": "body",
                "fields": {
                    "Greatness": "Incremental active energy",
                    "Greatness_2": "Total incremental direct active energy",
                    "Unit": "Wh",
                },
                "matrix_facts": [],
                "domain_tags": ["measurement_quantity"],
                "kb_matches": [],
            },
        ]

        candidates = build_atomic_candidates([], table_items, include_regions={"body"})
        types = {candidate["requirement_type"] for candidate in candidates}

        self.assertIn("security_policy_bit", types)
        self.assertIn("measurement_quantity_unit", types)

    def test_build_quality_report_counts_types_and_review_queues(self) -> None:
        candidates = [
            {
                "req_id": "AREQ-1",
                "requirement_type": "functional",
                "source_type": "paragraph",
                "source_refs": ["BLK-1"],
                "domain": "meter_function",
                "verification_method": "inspection",
                "confidence": 0.7,
                "ambiguity": True,
                "requirement": "Ambiguous requirement",
            }
        ]

        report = build_quality_report([], [], candidates, [])

        self.assertEqual(report["requirement_type_counts"]["functional"], 1)
        self.assertEqual(report["counts"]["ambiguous_atomic_requirements"], 1)
        self.assertEqual(report["counts"]["low_confidence_atomic_requirements"], 1)

    def test_run_atomizer_pipeline_raises_input_error_for_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AtomizerInputError) as caught:
                run_atomizer_pipeline(Path(tmp) / "missing.docx", Path(tmp) / "out")

        self.assertIsInstance(caught.exception, ValueError)

    def test_atomize_cli_returns_2_for_bad_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad_input = Path(tmp) / "bad.txt"
            bad_input.write_text("not a docx", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "atomize.py", str(bad_input), "--out", str(Path(tmp) / "out")],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("Supported formats: .docx, .xlsx, .pdf", result.stderr)


if __name__ == "__main__":
    unittest.main()
