from __future__ import annotations

import unittest

from atomize import (
    build_atomic_candidates,
    build_quality_report,
    extract_matrix_facts,
    interpret_table_matrix,
    parse_access_rights,
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


if __name__ == "__main__":
    unittest.main()
