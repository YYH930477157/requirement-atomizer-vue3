from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import engineering_composer
from engineering_composer import compose_engineering_requirements, write_engineering_requirements


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def write_fixture(out_dir: Path) -> None:
    write_jsonl(out_dir / "atomic_requirements.jsonl", [
        {
            "stable_req_id": "OBJ-CLOCK",
            "requirement_type": "cosem_object_instance",
            "requirement": "Clock object shall be available.",
            "object": "Clock",
            "source_refs": ["TBL-OBJ"],
            "section_path": ["Object model"],
        },
        {
            "stable_req_id": "ATTR-CLOCK-TIME",
            "requirement_type": "cosem_attribute_access",
            "requirement": "Clock time shall be readable and writable.",
            "object": "Clock.time",
            "source_refs": ["TBL-ATTR"],
            "section_path": ["Object model"],
        },
        {
            "stable_req_id": "FUNC-SYNC",
            "requirement_type": "functional",
            "requirement": "The meter shall synchronize clock time through DLMS SET service.",
            "object": "Clock",
            "domain": "time",
            "source_refs": ["BLK-SYNC"],
            "section_path": ["Time synchronization"],
        },
        {
            "stable_req_id": "EVENT-POWER",
            "requirement_type": "event_definition",
            "requirement": "The meter shall record power failure events.",
            "object": "Power failure event log",
            "domain": "event",
            "source_refs": ["BLK-EVT"],
            "section_path": ["Events"],
        },
    ])
    write_jsonl(out_dir / "table_items.jsonl", [
        {
            "item_id": "TBL-OBJ",
            "fields": {
                "Object/attribute name": "Clock",
                "CL": "8",
                "Value": "0-0:1.0.0.255",
            },
        },
        {
            "item_id": "TBL-ATTR",
            "fields": {
                "#": "2",
                "Object/attribute name": "time",
                "Type": "octet-string",
                "Access rights RC/PC/SC/LC": "R-/RW/RW/R-",
            },
        },
    ])


class EngineeringComposerTests(unittest.TestCase):
    def test_composes_function_requirements_and_dlms_objects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_fixture(out_dir)

            model = compose_engineering_requirements(out_dir)

            functions = model["requirement_functions"]
            objects = model["dlms_objects"]
            self.assertGreaterEqual(len(functions), 2)
            self.assertGreaterEqual(len(objects), 1)

            sync = next(item for item in functions if item["domain"] == "时钟")
            self.assertEqual(sync["id"], "FUNC-001")
            self.assertIn("Clock", sync["related_dlms_objects"])
            self.assertIn("FUNC-SYNC", sync["source_atomic_requirements"])
            self.assertIn("BLK-SYNC", sync["source_refs"])
            self.assertIn("Covers 1 source atomic requirement.", sync["acceptance_criteria"])
            self.assertIn("Configure DLMS object: Clock.", sync["implementation_tasks"])

            clock = next(item for item in objects if item["object_name"] == "Clock")
            self.assertEqual(clock["id"], "DLMS-001")
            self.assertEqual(clock["class_id"], "8")
            self.assertEqual(clock["obis"], "0-0:1.0.0.255")
            self.assertEqual(clock["attributes"][0]["name"], "time")
            self.assertEqual(clock["attributes"][0]["access_rights"], "R-/RW/RW/R-")
            self.assertEqual(clock["implementation_summary"], "Implement Clock with OBIS 0-0:1.0.0.255 and interface class 8; cover 1 attribute.")
            self.assertEqual(clock["access_summary"], "time: R-/RW/RW/R-")
            self.assertIn("OBJ-CLOCK", clock["source_atomic_requirements"])
            self.assertIn("ATTR-CLOCK-TIME", clock["source_atomic_requirements"])
            self.assertIn("FUNC-001", clock["related_functions"])

    def test_writes_json_and_markdown_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_fixture(out_dir)
            model = compose_engineering_requirements(out_dir)

            written = write_engineering_requirements(out_dir, model)

            self.assertEqual(
                written,
                [
                    "engineering_requirements/engineering_requirements.json",
                    "engineering_requirements/requirement_functions.md",
                    "engineering_requirements/dlms_objects.md",
                ],
            )
            target = out_dir / "engineering_requirements" / "engineering_requirements.json"
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertIn("requirement_functions", payload)
            self.assertIn("dlms_objects", payload)
            self.assertIn("## 时钟", (out_dir / "engineering_requirements" / "requirement_functions.md").read_text(encoding="utf-8"))
            objects_md = (out_dir / "engineering_requirements" / "dlms_objects.md").read_text(encoding="utf-8")
            self.assertIn("0-0:1.0.0.255", objects_md)
            self.assertIn("Implementation summary: Implement Clock with OBIS 0-0:1.0.0.255", objects_md)

    def test_attribute_atoms_without_object_instance_do_not_create_fake_dlms_objects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "ATTR-ORPHAN",
                    "requirement_type": "cosem_attribute_access",
                    "requirement": "The current_user attribute shall be readable.",
                    "object": "current_user.current_user",
                    "source_refs": ["TBL-ORPHAN"],
                    "section_path": ["Security attributes"],
                }
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-ORPHAN",
                    "fields": {
                        "#": "11",
                        "Object/attribute name": "current_user",
                        "Type": "structure",
                        "Access rights RC/PC/SC/LC": "--/R-/R-/R-",
                    },
                }
            ])

            model = compose_engineering_requirements(out_dir)

            self.assertEqual(model["dlms_objects"], [])
            self.assertEqual(model["analysis"]["orphan_dlms_attributes"], 1)

    def test_context_groups_short_atoms_into_engineering_function(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "BILLING-RECORDS",
                    "requirement_type": "functional",
                    "requirement": "There must be at least 12 billing records at the end of the period.",
                    "object": "period",
                    "source_refs": ["BLK-BILLING-1"],
                    "section_path": ["20 Control of billing period"],
                    "verification_method": "inspection",
                },
                {
                    "stable_req_id": "BILLING-DATE",
                    "requirement_type": "functional",
                    "requirement": "For the information of invoicing at the final of period, the object Date of billing Period 1 must be used.",
                    "object": "period",
                    "source_refs": ["BLK-BILLING-2"],
                    "section_path": ["20 Control of billing period"],
                    "verification_method": "inspection",
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

            self.assertEqual(len(model["requirement_functions"]), 1)
            function = model["requirement_functions"][0]
            self.assertEqual(function["domain"], "结算")
            self.assertEqual(function["title"], "Control of billing period")
            self.assertEqual(function["source_atomic_requirements"], ["BILLING-RECORDS", "BILLING-DATE"])
            self.assertEqual(function["source_refs"], ["BLK-BILLING-1", "BLK-BILLING-2"])
            self.assertEqual(len(function["functional_details"]), 2)
            self.assertIn("Verification method: inspection.", function["acceptance_criteria"])
            self.assertIn("Covers 2 source atomic requirements.", function["acceptance_criteria"])
            self.assertNotIn("Covers 1 source atomic requirement.", function["acceptance_criteria"])
            self.assertEqual(function["module"], "billing")

    def test_billing_requirements_emit_structured_developer_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "BILLING-RECORDS",
                    "requirement_type": "functional",
                    "requirement": "There must be at least 12 billing records at the end of the period.",
                    "object": "billing period",
                    "domain": "billing",
                    "source_refs": ["BLK-BILLING-1"],
                    "section_path": ["Control of billing period"],
                },
                {
                    "stable_req_id": "BILLING-DATE",
                    "requirement_type": "functional",
                    "requirement": "For the information of invoicing at the final of period, the object Date of billing Period 1 must be used.",
                    "object": "Date of billing Period 1",
                    "domain": "billing",
                    "source_refs": ["BLK-BILLING-2"],
                    "section_path": ["Control of billing period"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

        spec = model["requirement_functions"][0]["implementation_spec"]
        self.assertEqual(
            spec["billing_period"],
            {
                "trigger": "At billing period close, finalize the period data set.",
                "minimum_records": "Keep at least 12 billing period records.",
                "required_objects": ["Date of billing Period 1"],
            },
        )
        self.assertIn("Keep at least 12 billing period records.", spec["processing_rules"])
        write_engineering_requirements(out_dir, model)
        markdown = (out_dir / "engineering_requirements" / "requirement_functions.md").read_text(encoding="utf-8")
        self.assertIn("Billing period:", markdown)
        self.assertIn("Minimum records: Keep at least 12 billing period records.", markdown)

    def test_low_confidence_ambiguous_function_outputs_review_acceptance_criteria(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "AMBIG-1",
                    "requirement_type": "functional",
                    "requirement": "The meter shall provide billing behavior.",
                    "object": "Billing",
                    "source_refs": ["BLK-AMBIG"],
                    "section_path": ["Billing"],
                    "verification_method": "expert_review",
                    "ambiguity": True,
                    "confidence": 0.42,
                }
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

            function = model["requirement_functions"][0]
            self.assertIn("Verification method: expert_review.", function["acceptance_criteria"])
            self.assertIn("Resolve ambiguity before implementation baseline.", function["acceptance_criteria"])
            self.assertIn("Review original context because extraction confidence is below 0.6.", function["acceptance_criteria"])

    def test_short_or_truncated_section_title_is_rewritten_from_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "LOAD-PROFILE-1",
                    "requirement_type": "functional",
                    "requirement": "Collection must be carried out at programmable intervals of 5 min to 60 min.",
                    "object": "",
                    "source_refs": ["BLK-LP-1"],
                    "section_path": ["20 Control of"],
                },
                {
                    "stable_req_id": "LOAD-PROFILE-2",
                    "requirement_type": "functional",
                    "requirement": "The mass memory storage capacity must be at least 37 days.",
                    "object": "",
                    "source_refs": ["BLK-LP-2"],
                    "section_path": ["20 Control of"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

            function = model["requirement_functions"][0]
            self.assertEqual(function["title"], "Load profile collection and storage")
            self.assertEqual(
                function["implementation_spec"]["load_profile"],
                {
                    "collection_interval": "Support programmable collection intervals from 5 min to 60 min.",
                    "storage_capacity": "Maintain mass memory storage for at least 37 days.",
                },
            )
            self.assertEqual(function["domain"], "曲线")

    def test_capability_matrix_emits_actor_service_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "CAP-PUBLIC-GET",
                    "requirement_type": "capability_matrix",
                    "requirement": 'Public client shall support xDLMS Service: "GET".',
                    "object": "Public client.GET",
                    "domain": "communication",
                    "source_refs": ["TBL-CAP-R1"],
                    "section_path": ["xDLMS services"],
                },
                {
                    "stable_req_id": "CAP-READING-BLOCK-GET",
                    "requirement_type": "capability_matrix",
                    "requirement": 'Reading client shall support xDLMS Service: Block transfer with "GET".',
                    "object": "Reading client.Block transfer GET",
                    "domain": "communication",
                    "source_refs": ["TBL-CAP-R2"],
                    "section_path": ["xDLMS services"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

        spec = model["requirement_functions"][0]["implementation_spec"]
        self.assertEqual(
            spec["capability_matrix"],
            {
                "actors": {
                    "Public client": ['"GET"'],
                    "Reading client": ['Block transfer with "GET"'],
                }
            },
        )
        self.assertIn('Allow Public client to use "GET".', spec["processing_rules"])
        self.assertIn('Allow Reading client to use Block transfer with "GET".', spec["processing_rules"])
        write_engineering_requirements(out_dir, model)
        markdown = (out_dir / "engineering_requirements" / "requirement_functions.md").read_text(encoding="utf-8")
        self.assertIn("Capability matrix:", markdown)
        self.assertIn('Public client: "GET"', markdown)

    def test_capability_matrix_cleans_actor_label_translation_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "CAP-MGMT-GET",
                    "requirement_type": "capability_matrix",
                    "requirement": 'Local and remote management clients It is measurement shall support xDLMS Service: "GET".',
                    "object": "Local and remote management clients It is measurement",
                    "domain": "communication",
                    "source_refs": ["TBL-CAP-R4"],
                    "section_path": ["xDLMS services"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

        spec = model["requirement_functions"][0]["implementation_spec"]
        self.assertEqual(
            spec["capability_matrix"],
            {"actors": {"Local and remote management clients": ['"GET"']}},
        )
        self.assertNotIn(
            "It is measurement",
            json.dumps(model["requirement_functions"][0], ensure_ascii=False),
        )

    def test_association_security_matrix_emits_structured_access_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "SEC-MGMT-HLS",
                    "requirement_type": "association_security_matrix",
                    "requirement": "Management client shall have Server application process: Management Logical Device set to High Level of Security (HLS).",
                    "object": "Management client",
                    "domain": "security",
                    "source_refs": ["TBL-SEC-R1"],
                    "section_path": ["Terms and Definitions"],
                },
                {
                    "stable_req_id": "SEC-READ-LLS",
                    "requirement_type": "association_security_matrix",
                    "requirement": "Reading client shall have Server application process: Measuring logic devices set to Low Level Security (LLS).",
                    "object": "Reading client",
                    "domain": "security",
                    "source_refs": ["TBL-SEC-R2"],
                    "section_path": ["Terms and Definitions"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

        spec = model["requirement_functions"][0]["implementation_spec"]
        self.assertEqual(
            spec["access_control_matrix"],
            {
                "actors": {
                    "Management client": [
                        {
                            "target": "Management Logical Device",
                            "security_level": "High Level of Security (HLS)",
                        }
                    ],
                    "Reading client": [
                        {
                            "target": "Measuring logic devices",
                            "security_level": "Low Level Security (LLS)",
                        }
                    ],
                }
            },
        )
        self.assertIn(
            "Require Management client to access Management Logical Device with High Level of Security (HLS).",
            spec["processing_rules"],
        )
        write_engineering_requirements(out_dir, model)
        markdown = (out_dir / "engineering_requirements" / "requirement_functions.md").read_text(encoding="utf-8")
        self.assertIn("Access control matrix:", markdown)
        self.assertIn("Management client -> Management Logical Device: High Level of Security (HLS)", markdown)

    def test_security_policy_requirements_emit_structured_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "SEC-SUITE",
                    "requirement_type": "functional",
                    "requirement": "The security suite determines the cryptographic algorithms and key sizes that must be available.",
                    "object": "security suite",
                    "domain": "security",
                    "source_refs": ["BLK-SEC-SUITE"],
                    "section_path": ["Security"],
                },
                {
                    "stable_req_id": "SEC-UNPROTECTED",
                    "requirement_type": "functional",
                    "requirement": 'When a client implementation does not need protection, the security policy must remain "0" in the corresponding security policy object.',
                    "object": "security policy",
                    "domain": "security",
                    "source_refs": ["BLK-SEC-POLICY"],
                    "section_path": ["Security"],
                },
                {
                    "stable_req_id": "SEC-KEYS",
                    "requirement_type": "functional",
                    "requirement": "The meter must support the following keys:",
                    "object": "keys",
                    "domain": "security",
                    "source_refs": ["BLK-SEC-KEYS"],
                    "section_path": ["Security"],
                },
                {
                    "stable_req_id": "SEC-KEY-EXPIRATION",
                    "requirement_type": "functional",
                    "requirement": "Secure keys can expire according to a programmed time and must then be re-established.",
                    "object": "keys",
                    "domain": "security",
                    "source_refs": ["BLK-SEC-KEY-EXP"],
                    "section_path": ["Security"],
                },
                {
                    "stable_req_id": "SEC-COUNTERS",
                    "requirement_type": "functional",
                    "requirement": "The meter must implement an independent unicast communication invocation counter for each secure client.",
                    "object": "invocation counter",
                    "domain": "security",
                    "source_refs": ["BLK-SEC-COUNTER"],
                    "section_path": ["Security"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

        spec = model["requirement_functions"][0]["implementation_spec"]
        self.assertEqual(
            spec["security_policy"],
            {
                "security_suite": "Define the cryptographic algorithms and key sizes that must be available for each supported security suite.",
                "unprotected_clients": 'Keep the corresponding security policy object at "0" when a client implementation does not require protection.',
                "supported_keys": "Support the security keys required by the standard and expose them through the configured key management flow.",
                "key_expiration": "Expire secure keys at the programmed time and require them to be re-established before protected communication continues.",
                "invocation_counters": "Maintain an independent unicast communication invocation counter for each secure client.",
            },
        )
        self.assertIn(
            "Maintain an independent unicast communication invocation counter for each secure client.",
            spec["processing_rules"],
        )

    def test_abnt_security_translation_residue_is_summarized_and_linked_to_security_objects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "OBJ-SEC-SETUP",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "Security Setup object shall be available.",
                    "object": "Security Setup",
                    "source_refs": ["TBL-SEC-OBJ-R1"],
                    "section_path": ["Security"],
                },
                {
                    "stable_req_id": "OBJ-SEC-COUNTER",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "Security-Invocation counter object shall be available.",
                    "object": "Security-Invocation counter",
                    "source_refs": ["TBL-SEC-OBJ-R2"],
                    "section_path": ["Security"],
                },
                {
                    "stable_req_id": "SEC-SUITE-RAW",
                    "requirement_type": "functional",
                    "requirement": "O set in security determines O set in algorithms cryptographic what must be available It is you sizes of keys.",
                    "object": "security suite",
                    "domain": "security",
                    "source_refs": ["BLK-SEC-SUITE"],
                    "section_path": ["Security"],
                },
                {
                    "stable_req_id": "SEC-UNPROTECTED-RAW",
                    "requirement_type": "functional",
                    "requirement": 'At the case in what one Implementation of client no need to be protected, The policy in security must remain "0" in the corresponding security policy object.',
                    "object": "security policy",
                    "domain": "security",
                    "source_refs": ["BLK-SEC-POLICY"],
                    "section_path": ["Security"],
                },
                {
                    "stable_req_id": "SEC-COUNTER-RAW",
                    "requirement_type": "communication",
                    "requirement": "The meter must implement an independent \" unicast \" communication invocation counter for each secure customer.",
                    "object": "",
                    "domain": "security",
                    "source_refs": ["BLK-SEC-COUNTER"],
                    "section_path": ["Security"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-SEC-OBJ-R1",
                    "table_id": "TBL-SEC-OBJ",
                    "row_index": 1,
                    "fields": {
                        "Object/attribute name": "Security Setup",
                        "CL": "64",
                        "Value": "0-0:43.0.3.255",
                    },
                },
                {
                    "item_id": "TBL-SEC-OBJ-R2",
                    "table_id": "TBL-SEC-OBJ",
                    "row_index": 2,
                    "fields": {
                        "Object/attribute name": "Security-Invocation counter",
                        "CL": "1",
                        "Value": "0-0:43.1.3.255",
                    },
                },
            ])

            model = compose_engineering_requirements(out_dir)

        function = model["requirement_functions"][0]
        self.assertIn("Security Setup", function["related_dlms_objects"])
        self.assertIn("Security-Invocation counter", function["related_dlms_objects"])
        self.assertIn("安全策略", function["description"])
        self.assertNotIn("O set in security", function["description"])
        self.assertNotIn("It is you", json.dumps(function, ensure_ascii=False))
        self.assertIn(
            "Define the cryptographic algorithms and key sizes that must be available for each supported security suite.",
            function["implementation_spec"]["processing_rules"],
        )
        self.assertIn(
            "Maintain an independent unicast communication invocation counter for each secure client.",
            function["implementation_spec"]["processing_rules"],
        )

    def test_key_management_requirements_emit_integrity_and_counter_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "SEC-KEY-INTEGRITY",
                    "requirement_type": "functional",
                    "requirement": "During the key unwrapping process for loading a new master key and global key, the integrity of the new key must be checked.",
                    "object": "key loading",
                    "domain": "security",
                    "source_refs": ["BLK-SEC-KEY-INTEGRITY"],
                    "section_path": ["Security"],
                },
                {
                    "stable_req_id": "SEC-COUNTER-RESET",
                    "requirement_type": "functional",
                    "requirement": 'Invocation counters must be incremented for each protected message and reset to "0" when the corresponding key is replaced or reset.',
                    "object": "invocation counter",
                    "domain": "security",
                    "source_refs": ["BLK-SEC-COUNTER-RESET"],
                    "section_path": ["Security"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

        spec = model["requirement_functions"][0]["implementation_spec"]
        self.assertEqual(
            spec["key_management"],
            {
                "key_loading_integrity": "During key unwrapping and loading, verify the integrity of each new master key and global key before accepting it.",
                "protected_message_counters": 'Increment invocation counters for each protected message and reset the corresponding counter to "0" when its key is replaced or reset.',
            },
        )
        self.assertIn(
            "During key unwrapping and loading, verify the integrity of each new master key and global key before accepting it.",
            spec["processing_rules"],
        )

    def test_security_section_overrides_clock_keyword_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "SEC-CLOCKLIKE",
                    "requirement_type": "functional",
                    "requirement": "The secure mechanism shall protect time synchronization keys.",
                    "object": "Secure",
                    "source_refs": ["BLK-SEC"],
                    "section_path": ["Security"],
                }
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

            function = model["requirement_functions"][0]
            self.assertEqual(function["domain"], "安全")
            self.assertEqual(function["title"], "Security and key management")
            self.assertEqual(function["module"], "security")

    def test_reserved_not_used_bit_rows_are_not_promoted_to_functions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "SEC-BIT-0",
                    "requirement_type": "functional",
                    "requirement": '0 | Not used, must be set to "0"',
                    "object": "security policy bit 0",
                    "domain": "security",
                    "source_refs": ["TBL-SEC-BIT-0"],
                    "section_path": ["Security policy bits"],
                },
                {
                    "stable_req_id": "SEC-BIT-1",
                    "requirement_type": "functional",
                    "requirement": '1 | Not used, must be set to "0"',
                    "object": "security policy bit 1",
                    "domain": "security",
                    "source_refs": ["TBL-SEC-BIT-1"],
                    "section_path": ["Security policy bits"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

        self.assertEqual(model["requirement_functions"], [])

    def test_translated_load_profile_sentence_is_normalized_for_developer_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "LOAD-PROFILE-QTY",
                    "requirement_type": "functional",
                    "requirement": (
                        "To the magnitudes whose objects they were defined in this Standard they are presented in the "
                        "Tables 13 The 17, however to the magnitudes to be effectively captured must to be defined at "
                        "technical specification of the meter by the concessionaire, according to its operational needs, "
                        "and can be organized into two lists, with programmable capture periods."
                    ),
                    "object": "load profile quantities",
                    "domain": "load_profile",
                    "source_refs": ["BLK-LP-QTY"],
                    "section_path": ["20 Control of"],
                },
                {
                    "stable_req_id": "LOAD-PROFILE-TS",
                    "requirement_type": "functional",
                    "requirement": 'The timestamp of the end of the capture period and the meter profile " status " code must be recorded in the list of catch.',
                    "object": "load profile capture",
                    "domain": "load_profile",
                    "source_refs": ["BLK-LP-TS"],
                    "section_path": ["20 Control of"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

        details = [
            detail
            for function in model["requirement_functions"]
            for detail in function["functional_details"]
        ]
        self.assertIn(
            (
                "The quantities whose objects are defined in this Standard are listed in Tables 13 to 17; "
                "the concessionaire must define the quantities that are effectively captured in the meter "
                "technical specification according to operational needs, and may organize them into two lists "
                "with programmable capture periods."
            ),
            details,
        )
        self.assertIn(
            "The timestamp at the end of the capture period and the meter profile status code must be recorded in the capture list.",
            details,
        )
        self.assertNotIn("must to be", json.dumps(model, ensure_ascii=False))
        self.assertNotIn("list of catch", json.dumps(model, ensure_ascii=False))

    def test_security_event_definition_stays_in_event_recording_domain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "SEC-EVENT-1",
                    "requirement_type": "event_definition",
                    "requirement": "Event G7-SG71-E5 shall be defined as: Secure client password changed - Remote Client.",
                    "object": "G7-SG71-E5",
                    "source_refs": ["TBL-EVENT-1"],
                    "section_path": ["20 Control of"],
                    "verification_method": "document_review",
                },
                {
                    "stable_req_id": "SEC-EVENT-2",
                    "requirement_type": "event_definition",
                    "requirement": "Event G7-SG71-E18 shall be defined as: Secure client password changed - Local Client.",
                    "object": "G7-SG71-E18",
                    "source_refs": ["TBL-EVENT-2"],
                    "section_path": ["20 Control of"],
                    "verification_method": "document_review",
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

            self.assertEqual(len(model["requirement_functions"]), 1)
            function = model["requirement_functions"][0]
            self.assertEqual(function["domain"], "事件记录")
            self.assertEqual(function["title"], "Security event definitions")
            self.assertEqual(function["source_atomic_requirements"], ["SEC-EVENT-1", "SEC-EVENT-2"])

    def test_function_links_to_dlms_object_by_obis_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "OBJ-ACTIVE-IMPORT",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "Active energy import total shall be available.",
                    "object": "Active Energy Import Total",
                    "source_refs": ["TBL-OBJ"],
                    "section_path": ["Object model"],
                },
                {
                    "stable_req_id": "FUNC-ACTIVE-IMPORT",
                    "requirement_type": "functional",
                    "requirement": "The meter shall expose OBIS 1-0:1.8.0.255 for cumulative active import energy.",
                    "object": "",
                    "domain": "metering",
                    "source_refs": ["BLK-FUNC"],
                    "section_path": ["Metering objects"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-OBJ",
                    "fields": {
                        "Object/attribute name": "Active Energy Import Total",
                        "CL": "3",
                        "Value": "1-0:1.8.0.255",
                    },
                }
            ])

            model = compose_engineering_requirements(out_dir)

            function = model["requirement_functions"][0]
            dlms_object = model["dlms_objects"][0]
            self.assertEqual(function["related_dlms_objects"], ["Active Energy Import Total"])
            self.assertEqual(function["module"], "metering")
            self.assertEqual(dlms_object["related_functions"], [function["id"]])

    def test_function_includes_kb_implementation_hints_from_cosem_class_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "SMTP-FUNC-1",
                    "requirement_type": "functional",
                    "requirement": "The meter shall send alarms to configured SMTP recipient addresses.",
                    "object": "SMTP setup",
                    "domain": "communication",
                    "source_refs": ["BLK-SMTP"],
                    "section_path": ["E-mail notification"],
                    "kb_matches": [
                        {
                            "entry_id": "KB-L3-IC-46-SMTP-SETUP",
                            "name": "SMTP setup",
                            "type": "cosem_interface_class",
                            "class_id": 46,
                            "definition": "COSEM interface class for configuring SMTP setup parameters in DLMS/COSEM devices.",
                            "access_semantics": [
                                "Recipient configuration changes can redirect alarms or reports and should be audited."
                            ],
                            "behavior_notes": [
                                "Use this class when requirements mention SMTP, e-mail alarm delivery, sender address, recipient list, or mail server configuration."
                            ],
                        }
                    ],
                }
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

            function = model["requirement_functions"][0]
            self.assertEqual(function["class_hints"], [
                {
                    "entry_id": "KB-L3-IC-46-SMTP-SETUP",
                    "name": "SMTP setup",
                    "class_id": "46",
                    "definition": "COSEM interface class for configuring SMTP setup parameters in DLMS/COSEM devices.",
                    "behavior_notes": [
                        "Use this class when requirements mention SMTP, e-mail alarm delivery, sender address, recipient list, or mail server configuration."
                    ],
                    "access_semantics": [
                        "Recipient configuration changes can redirect alarms or reports and should be audited."
                    ],
                }
            ])
            self.assertIn(
                "COSEM class hint: SMTP setup (class 46).",
                function["acceptance_criteria"],
            )
            written = write_engineering_requirements(out_dir, model)
            self.assertIn("engineering_requirements/requirement_functions.md", written)
            functions_md = (out_dir / "engineering_requirements" / "requirement_functions.md").read_text(encoding="utf-8")
            self.assertIn("COSEM class hints", functions_md)
            self.assertIn("SMTP setup (class 46)", functions_md)
            self.assertIn("Recipient configuration changes can redirect alarms", functions_md)
            self.assertIn("Implementation tasks", functions_md)
            self.assertIn("Apply COSEM class semantics: SMTP setup (class 46).", functions_md)

    def test_function_expands_compact_kb_match_from_runtime_kb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "SMTP-FUNC-COMPACT",
                    "requirement_type": "functional",
                    "requirement": "The meter shall support SMTP setup for e-mail alarm delivery.",
                    "object": "SMTP setup",
                    "domain": "communication",
                    "source_refs": ["BLK-SMTP-COMPACT"],
                    "section_path": ["E-mail notification"],
                    "kb_matches": [
                        {
                            "entry_id": "KB-L3-IC-46-SMTP-SETUP",
                            "name": "SMTP setup",
                            "type": "cosem_interface_class",
                            "class_id": 46,
                        }
                    ],
                }
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

            hint = model["requirement_functions"][0]["class_hints"][0]
            self.assertEqual(hint["entry_id"], "KB-L3-IC-46-SMTP-SETUP")
            self.assertIn("Authentication values are security-sensitive", " ".join(hint["behavior_notes"] + hint["access_semantics"]))
            self.assertIn("SMTP setup", hint["definition"])

    def test_requirement_functions_markdown_groups_by_engineering_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "BILLING-1",
                    "requirement_type": "functional",
                    "requirement": "There must be at least 12 billing records.",
                    "object": "billing period",
                    "domain": "billing",
                    "source_refs": ["BLK-BILL"],
                    "section_path": ["Billing"],
                },
                {
                    "stable_req_id": "SEC-1",
                    "requirement_type": "functional",
                    "requirement": "The secure mechanism shall protect authentication keys.",
                    "object": "Security",
                    "domain": "security",
                    "source_refs": ["BLK-SEC"],
                    "section_path": ["Security"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)
            write_engineering_requirements(out_dir, model)

            markdown = (out_dir / "engineering_requirements" / "requirement_functions.md").read_text(encoding="utf-8")
            self.assertIn("## Module: billing", markdown)
            self.assertIn("## Module: security", markdown)
            self.assertIn("### 结算", markdown)
            self.assertIn("### 安全", markdown)

    def test_implementation_tasks_combine_sources_objects_and_class_hints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "OBJ-SMTP",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "SMTP setup object shall be available.",
                    "object": "SMTP setup",
                    "source_refs": ["TBL-SMTP-OBJ"],
                    "section_path": ["Object model"],
                },
                {
                    "stable_req_id": "SMTP-FUNC-TASK",
                    "requirement_type": "functional",
                    "requirement": "The meter shall send alarm notifications through SMTP.",
                    "object": "SMTP setup",
                    "domain": "communication",
                    "source_refs": ["BLK-SMTP-TASK"],
                    "section_path": ["E-mail notification"],
                    "verification_method": "integration_test",
                    "kb_matches": [
                        {
                            "entry_id": "KB-L3-IC-46-SMTP-SETUP",
                            "name": "SMTP setup",
                            "type": "cosem_interface_class",
                            "class_id": 46,
                        }
                    ],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-SMTP-OBJ",
                    "fields": {
                        "Object/attribute name": "SMTP setup",
                        "CL": "46",
                        "Value": "0-0:25.9.0.255",
                    },
                }
            ])

            model = compose_engineering_requirements(out_dir)

            function = model["requirement_functions"][0]
            self.assertEqual(function["module"], "communication")
            self.assertEqual(function["implementation_tasks"], [
                "Implement normative behavior from atomic requirements: SMTP-FUNC-TASK.",
                "Configure DLMS object: SMTP setup.",
                "Apply COSEM class semantics: SMTP setup (class 46).",
                "Verify with integration_test.",
            ])
            self.assertEqual(
                function["implementation_spec"],
                {
                    "trigger_or_input": "Requirements from E-mail notification.",
                    "processing_rules": [
                        "The meter shall send alarm notifications through SMTP.",
                        "Apply COSEM class semantics: SMTP setup (class 46).",
                    ],
                    "dlms_object_impact": [
                        "Configure SMTP setup.",
                    ],
                    "error_and_boundary_behavior": [],
                    "acceptance_checks": [
                        "Covers 1 source atomic requirement.",
                        "Verification method: integration_test.",
                        "COSEM class hint: SMTP setup (class 46).",
                    ],
                },
            )

            written = write_engineering_requirements(out_dir, model)
            self.assertIn("engineering_requirements/requirement_functions.md", written)
            markdown = (out_dir / "engineering_requirements" / "requirement_functions.md").read_text(encoding="utf-8")
            self.assertIn("Implementation spec", markdown)
            self.assertIn("Trigger/Input: Requirements from E-mail notification.", markdown)
            self.assertIn("Processing rules:", markdown)
            self.assertIn("DLMS object impact:", markdown)
            self.assertIn("Acceptance checks:", markdown)

    def test_class_hint_without_explicit_object_keeps_semantics_but_does_not_link_objects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "OBJ-BILLING-PROFILE",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "Stored billing values profile shall be available.",
                    "object": "Stored Billing Values Profile",
                    "source_refs": ["TBL-OBJ-PROFILE"],
                    "section_path": ["Object model"],
                    "domain": "billing_profile",
                },
                {
                    "stable_req_id": "FUNC-BILLING-PROFILE",
                    "requirement_type": "functional",
                    "requirement": "The meter shall retain billing records in a profile object.",
                    "object": "",
                    "domain": "billing",
                    "source_refs": ["BLK-BILLING"],
                    "section_path": ["Control of billing period"],
                    "kb_matches": [
                        {
                            "entry_id": "KB-L3-IC-7-PROFILE-GENERIC",
                            "name": "Profile Generic",
                            "type": "cosem_interface_class",
                            "class_id": 7,
                        }
                    ],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-OBJ-PROFILE",
                    "fields": {
                        "Object/attribute name": "Stored Billing Values Profile",
                        "CL": "7",
                        "Value": "1-0:98.1.0.255",
                    },
                }
            ])

            model = compose_engineering_requirements(out_dir)

            function = model["requirement_functions"][0]
            dlms_object = model["dlms_objects"][0]
            self.assertEqual(function["class_hints"][0]["class_id"], "7")
            self.assertEqual(function["related_dlms_objects"], [])
            self.assertIn("Apply COSEM class semantics: Profile Generic (class 7).", function["implementation_tasks"])
            self.assertNotIn("Configure DLMS object: Stored Billing Values Profile.", function["implementation_tasks"])
            self.assertEqual(dlms_object["related_functions"], [])

    def test_load_profile_requirements_link_to_profile_and_status_objects_by_domain_phrase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "OBJ-LP-STATUS-1",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "AMR profile status for Load profile and quality with period 1 shall be available.",
                    "object": "AMR profile status for Load profile and quality with period 1",
                    "source_refs": ["TBL-LP-R1"],
                    "section_path": ["Load profile objects"],
                },
                {
                    "stable_req_id": "OBJ-LP-1",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "Load profile and quality with period 1 shall be available.",
                    "object": "Load profile and quality with period 1",
                    "source_refs": ["TBL-LP-R2"],
                    "section_path": ["Load profile objects"],
                },
                {
                    "stable_req_id": "FUNC-LP",
                    "requirement_type": "functional",
                    "requirement": "Collection must be carried out at programmable intervals of 5 min to 60 min, and the mass memory storage capacity must be at least 37 days.",
                    "object": "load profile",
                    "domain": "load_profile",
                    "source_refs": ["BLK-LP"],
                    "section_path": ["Control of"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-LP-R1",
                    "table_id": "TBL-LP",
                    "row_index": 1,
                    "fields": {
                        "Object/attribute name": "AMR profile status for Load profile and quality with period 1",
                        "CL": "1",
                        "Value": "0-0:96.10.7.255",
                    },
                },
                {
                    "item_id": "TBL-LP-R2",
                    "table_id": "TBL-LP",
                    "row_index": 2,
                    "fields": {
                        "Object/attribute name": "Load profile and quality with period 1",
                        "CL": "7",
                        "Value": "1-0:99.1.0.255",
                    },
                },
            ])

            model = compose_engineering_requirements(out_dir)

        function = model["requirement_functions"][0]
        self.assertEqual(
            function["related_dlms_objects"],
            [
                "AMR profile status for Load profile and quality with period 1",
                "Load profile and quality with period 1",
            ],
        )
        self.assertIn("负荷曲线", function["description"])
        self.assertNotIn("Collection must be carried out", function["description"])

    def test_large_explicit_related_object_sets_are_summarized_in_implementation_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            atomic_rows = [
                {
                    "stable_req_id": f"OBJ-REG-{index}",
                    "requirement_type": "cosem_object_instance",
                    "requirement": f"Register object {index} shall be available.",
                    "object": f"Register Object {index}",
                    "source_refs": [f"TBL-REG-{index}"],
                    "section_path": ["Register objects"],
                }
                for index in range(1, 11)
            ]
            explicit_names = ", ".join(f"Register Object {index}" for index in range(1, 11))
            atomic_rows.append(
                {
                    "stable_req_id": "FUNC-REG-SET",
                    "requirement_type": "functional",
                    "requirement": f"{explicit_names} shall expose metering values.",
                    "object": explicit_names,
                    "domain": "metering",
                    "source_refs": ["BLK-REG"],
                    "section_path": ["Register behavior"],
                    "kb_matches": [
                        {
                            "entry_id": "KB-L3-IC-3-REGISTER",
                            "name": "Register",
                            "type": "cosem_interface_class",
                            "class_id": 3,
                        }
                    ],
                }
            )
            write_jsonl(out_dir / "atomic_requirements.jsonl", atomic_rows)
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": f"TBL-REG-{index}",
                    "fields": {
                        "Object/attribute name": f"Register Object {index}",
                        "CL": "3",
                        "Value": f"1-0:{index}.8.0.255",
                    },
                }
                for index in range(1, 11)
            ])

            model = compose_engineering_requirements(out_dir)

        function = model["requirement_functions"][0]
        self.assertEqual(len(function["related_dlms_objects"]), 10)
        self.assertIn("Configure 10 related DLMS objects; see DLMS object impact list.", function["implementation_tasks"])
        self.assertNotIn("Configure DLMS object: Register Object 1.", function["implementation_tasks"])
        self.assertEqual(len(function["implementation_spec"]["dlms_object_impact"]), 10)

    def test_function_links_to_object_from_same_table_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "OBJ-BILLING-PROFILE",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "Current billing values profile shall be available.",
                    "object": "Current billing values",
                    "domain": "billing_profile",
                    "source_refs": ["TBL-BILL-R2"],
                    "section_path": ["Billing profile objects"],
                },
                {
                    "stable_req_id": "FUNC-BILLING-RETENTION",
                    "requirement_type": "functional",
                    "requirement": "There must be at least 12 billing records at the end of the period.",
                    "object": "billing records",
                    "domain": "billing",
                    "source_refs": ["TBL-BILL-R3"],
                    "section_path": ["Billing profile objects"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-BILL-R2",
                    "table_id": "TBL-BILL",
                    "row_index": 2,
                    "fields": {
                        "Object/attribute name": "Current billing values",
                        "CL": "7",
                        "Value": "0-0:21.0.5.255",
                    },
                },
                {
                    "item_id": "TBL-BILL-R3",
                    "table_id": "TBL-BILL",
                    "row_index": 3,
                    "fields": {"Requirement": "There must be at least 12 billing records."},
                },
            ])

            model = compose_engineering_requirements(out_dir)

        function = model["requirement_functions"][0]
        dlms_object = model["dlms_objects"][0]
        self.assertEqual(function["related_dlms_objects"], ["Current billing values"])
        self.assertEqual(dlms_object["related_functions"], [function["id"]])

    def test_function_links_to_dlms_object_by_required_object_phrase_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "OBJ-BILLING-P1",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "Date of billing period 1 Stored Billing Values Profile shall be available.",
                    "object": "Date of billing period 1 Stored Billing Values Profile",
                    "domain": "billing_profile",
                    "source_refs": ["TBL-BILLING-P1"],
                    "section_path": ["Billing profile objects"],
                },
                {
                    "stable_req_id": "FUNC-BILLING-P1",
                    "requirement_type": "cosem_object",
                    "requirement": "For the information of invoicing at the final of period, the object Date of billing Period 1 must be used.",
                    "object": "period",
                    "domain": "billing",
                    "source_refs": ["BLK-BILLING-P1"],
                    "section_path": ["Control of billing period"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-BILLING-P1",
                    "fields": {
                        "Object/attribute name": "Date of billing period 1 Stored Billing Values Profile",
                        "CL": "7",
                        "Value": "1-0:98.1.0.255",
                    },
                }
            ])

            model = compose_engineering_requirements(out_dir)

        function = model["requirement_functions"][0]
        dlms_object = model["dlms_objects"][0]
        self.assertEqual(function["related_dlms_objects"], ["Date of billing period 1 Stored Billing Values Profile"])
        self.assertEqual(dlms_object["related_functions"], [function["id"]])
        self.assertIn(
            "Configure Date of billing period 1 Stored Billing Values Profile.",
            function["implementation_spec"]["dlms_object_impact"],
        )

    def test_function_links_to_dlms_object_from_translated_must_be_used_phrase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "OBJ-BILLING-P1",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "Date of billing period 1 Stored Billing Values Profile shall be available.",
                    "object": "Date of billing period 1 Stored Billing Values Profile",
                    "domain": "billing_profile",
                    "source_refs": ["TBL-BILLING-P1"],
                    "section_path": ["Billing profile objects"],
                },
                {
                    "stable_req_id": "FUNC-BILLING-P1",
                    "requirement_type": "cosem_object",
                    "requirement": 'For to the information of invoicing at the Final of period, he must to be used O object "Date of billing Period 1".',
                    "object": "",
                    "domain": "billing",
                    "source_refs": ["BLK-BILLING-P1"],
                    "section_path": ["Control of billing period"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-BILLING-P1",
                    "fields": {
                        "Object/attribute name": "Date of billing period 1 Stored Billing Values Profile",
                        "CL": "7",
                        "Value": "1-0:98.1.0.255",
                    },
                }
            ])

            model = compose_engineering_requirements(out_dir)

        function = model["requirement_functions"][0]
        self.assertEqual(function["related_dlms_objects"], ["Date of billing period 1 Stored Billing Values Profile"])

    def test_function_links_to_dlms_object_from_translated_smart_quote_phrase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "OBJ-BILLING-P1",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "Date of billing period 1 Stored Billing Values Profile shall be available.",
                    "object": "Date of billing period 1 Stored Billing Values Profile",
                    "domain": "billing_profile",
                    "source_refs": ["TBL-BILLING-P1"],
                    "section_path": ["Billing profile objects"],
                },
                {
                    "stable_req_id": "FUNC-BILLING-P1",
                    "requirement_type": "cosem_object",
                    "requirement": "For to the information of invoicing at the Final of period, he must to be used O object \u201cDate of billing Period 1\u201d.",
                    "object": "",
                    "domain": "billing",
                    "source_refs": ["BLK-BILLING-P1"],
                    "section_path": ["Control of billing period"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-BILLING-P1",
                    "fields": {
                        "Object/attribute name": "Date of billing period 1 Stored Billing Values Profile",
                        "CL": "7",
                        "Value": "1-0:98.1.0.255",
                    },
                }
            ])

            model = compose_engineering_requirements(out_dir)

        function = model["requirement_functions"][0]
        self.assertEqual(function["related_dlms_objects"], ["Date of billing period 1 Stored Billing Values Profile"])
        self.assertNotIn("\u0401", json.dumps(model["requirement_functions"], ensure_ascii=False))

    def test_required_object_phrase_handles_smart_quotes_without_source_mojibake(self) -> None:
        self.assertEqual(
            engineering_composer._required_object_phrases(
                "For invoicing, he must to be used O object \u201cDate of billing Period 1\u201d."
            ),
            ["Date of billing Period 1"],
        )

        source = Path(engineering_composer.__file__).read_text(encoding="utf-8")
        self.assertNotIn("\u0401", source)
        self.assertNotIn("\u0410", source)
        self.assertNotIn("\u0411", source)

    def test_function_links_to_billing_object_despite_data_date_translation_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "OBJ-BILLING-P2",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "Date of billing period 2 Stored Billing Values Profile shall be available.",
                    "object": "Date of billing period 2 Stored Billing Values Profile",
                    "domain": "billing_profile",
                    "source_refs": ["TBL-BILLING-P2"],
                    "section_path": ["Billing profile objects"],
                },
                {
                    "stable_req_id": "FUNC-BILLING-P2",
                    "requirement_type": "cosem_object",
                    "requirement": 'For information daily rates, the "Data of billing period 2" object must be used.',
                    "object": "Data",
                    "domain": "billing",
                    "source_refs": ["BLK-BILLING-P2"],
                    "section_path": ["Control of billing period"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-BILLING-P2",
                    "fields": {
                        "Object/attribute name": "Date of billing period 2 Stored Billing Values Profile",
                        "CL": "7",
                        "Value": "1-0:98.2.0.255",
                    },
                }
            ])

            model = compose_engineering_requirements(out_dir)

        function = model["requirement_functions"][0]
        self.assertEqual(function["related_dlms_objects"], ["Date of billing period 2 Stored Billing Values Profile"])
        self.assertIn(
            'For information daily rates, the "Date of billing period 2" object must be used.',
            function["functional_details"],
        )
        self.assertNotIn("Data of billing period 2", json.dumps(function, ensure_ascii=False))

    def test_known_translation_noise_is_cleaned_in_engineering_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "FUNC-NOISE-1",
                    "requirement_type": "functional",
                    "requirement": "A collect he must to be carried out in breaks programmable in 5 min to 60 min.",
                    "object": "",
                    "domain": "load_profile",
                    "source_refs": ["BLK-NOISE-1"],
                    "section_path": ["Load profile"],
                },
                {
                    "stable_req_id": "FUNC-NOISE-2",
                    "requirement_type": "functional",
                    "requirement": "The energy quantities should be collected all you days to the 00:00:00, It is The capacity in record he must to be in at the Minimum three months.",
                    "object": "",
                    "domain": "metering",
                    "source_refs": ["BLK-NOISE-2"],
                    "section_path": ["Load profile"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

        blob = json.dumps(model["requirement_functions"], ensure_ascii=False)
        self.assertIn("Collection must be carried out at programmable intervals of 5 min to 60 min.", blob)
        self.assertIn("should be collected every day at 00:00:00", blob)
        self.assertIn("record capacity must be at least three months", blob)
        self.assertNotIn("he must", blob)
        self.assertNotIn("all you days", blob)
        self.assertNotIn("It is The capacity", blob)

    def test_support_object_placeholder_row_is_not_promoted_to_function(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "FUNC-PLACEHOLDER-SUPPORT",
                    "requirement_type": "functional",
                    "requirement": "If The functionality you are gift, you objects in support must to be implemented as defined",
                    "object": "",
                    "domain": "communication",
                    "source_refs": ["BLK-SUPPORT"],
                    "section_path": ["Protocol support"],
                },
                {
                    "stable_req_id": "FUNC-REAL-SUPPORT",
                    "requirement_type": "functional",
                    "requirement": "DLMS/COSEM application layer pull and push mechanisms must be available.",
                    "object": "",
                    "domain": "communication",
                    "source_refs": ["BLK-SUPPORT"],
                    "section_path": ["Protocol support"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

        blob = json.dumps(model["requirement_functions"], ensure_ascii=False)
        self.assertIn("pull and push mechanisms must be available", blob)
        self.assertNotIn("If The functionality you are gift", blob)

    def test_event_and_billing_translation_noise_are_cleaned_in_engineering_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "EVENT-NOISE-1",
                    "requirement_type": "communication",
                    "requirement": 'O record in one event at the log in events corresponding and/or O shipping in one event in communication " push " must) to be carried out in agreement with O programmed at the object "Filter of event logs." If the bit corresponding to the event register is set, the event must be registered at the log in events corresponding.',
                    "object": "Data",
                    "domain": "event",
                    "source_refs": ["BLK-EVENT-NOISE"],
                    "section_path": ["Event handling"],
                },
                {
                    "stable_req_id": "BILLING-NOISE-1",
                    "requirement_type": "cosem_object",
                    "requirement": 'For to the information of invoicing at the Final of period, he must to be used O object "Date of billing Period 1".',
                    "object": "",
                    "domain": "billing",
                    "source_refs": ["BLK-BILLING-NOISE"],
                    "section_path": ["Control of billing period"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

        details = [
            detail
            for function in model["requirement_functions"]
            for detail in function["functional_details"]
        ]
        blob = json.dumps(model["requirement_functions"], ensure_ascii=False)
        self.assertIn(
            'Event recording and push notification must follow the configured "Filter of event logs"; when the event register bit is set, persist the event in the corresponding event log.',
            details,
        )
        self.assertIn(
            'For final-period invoicing information, the "Date of billing Period 1" object must be used.',
            details,
        )
        self.assertNotIn("O record", blob)
        self.assertNotIn("must)", blob)
        self.assertNotIn("O object", blob)

    def test_implementation_spec_structures_functional_text_into_developer_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "EVENT-PUSH-1",
                    "requirement_type": "event_definition",
                    "requirement": "If the bit corresponding to the event register is set, the event must be registered in the corresponding event log.",
                    "object": "Event filter",
                    "domain": "event",
                    "source_refs": ["BLK-EVENT"],
                    "section_path": ["Event handling"],
                },
                {
                    "stable_req_id": "EVENT-PUSH-2",
                    "requirement_type": "event_definition",
                    "requirement": "If the bit corresponding to the shipping of event is set, the event must be sent via push communication.",
                    "object": "Event filter",
                    "domain": "event",
                    "source_refs": ["BLK-EVENT"],
                    "section_path": ["Event handling"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

        spec = model["requirement_functions"][0]["implementation_spec"]
        self.assertIn("event_handling", spec)
        self.assertEqual(
            spec["event_handling"],
            {
                "condition": "Evaluate the configured event register and event shipping bits for each detected event.",
                "recording_action": "When the register bit is enabled, persist the event in the corresponding event log.",
                "notification_action": "When the shipping bit is enabled, send the event through push communication.",
            },
        )
        self.assertIn(
            "Evaluate the configured event register and event shipping bits for each detected event.",
            spec["processing_rules"],
        )
        written = write_engineering_requirements(out_dir, model)
        self.assertIn("engineering_requirements/requirement_functions.md", written)
        markdown = (out_dir / "engineering_requirements" / "requirement_functions.md").read_text(encoding="utf-8")
        self.assertIn("Event handling:", markdown)
        self.assertIn("Recording: When the register bit is enabled", markdown)

    def test_event_retention_rows_emit_structured_developer_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "EVENT-RETENTION-1",
                    "requirement_type": "event_group_retention",
                    "requirement": "Event subgroup G1-SG10 shall keep at least 100 records for Non-special events.",
                    "object": "G1-SG10",
                    "domain": "event",
                    "source_refs": ["TBL-EVENT-RETENTION-R1"],
                    "section_path": ["Event retention"],
                },
                {
                    "stable_req_id": "EVENT-RETENTION-2",
                    "requirement_type": "event_group_retention",
                    "requirement": "Event subgroup Gtwo-SG20 shall keep at least 30 records for Connection related.",
                    "object": "Gtwo-SG20",
                    "domain": "event",
                    "source_refs": ["TBL-EVENT-RETENTION-R2"],
                    "section_path": ["Event retention"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)
            written = write_engineering_requirements(out_dir, model)

            spec = model["requirement_functions"][0]["implementation_spec"]
            self.assertEqual(
                spec["event_retention"]["subgroups"],
                [
                    {"subgroup": "G1-SG10", "minimum_records": 100, "event_scope": "Non-special events"},
                    {"subgroup": "G2-SG20", "minimum_records": 30, "event_scope": "Connection related"},
                ],
            )
            self.assertIn(
                "Keep at least 100 records for event subgroup G1-SG10 (Non-special events).",
                spec["processing_rules"],
            )
            self.assertIn("engineering_requirements/requirement_functions.md", written)
            markdown = (out_dir / "engineering_requirements" / "requirement_functions.md").read_text(encoding="utf-8")
        self.assertIn("Event retention:", markdown)
        self.assertIn("G1-SG10: keep at least 100 records", markdown)

    def test_event_retention_detail_normalizes_spelled_group_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "EVENT-RET-G2",
                    "requirement_type": "event_group_retention",
                    "requirement": "Event subgroup Gtwo-SG20 shall keep at least 20 records for Connection related.",
                    "object": "Gtwo-SG20",
                    "domain": "event",
                    "source_refs": ["TBL-EVENT-G2"],
                    "section_path": ["Event retention"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

        function = model["requirement_functions"][0]
        self.assertEqual(
            function["functional_details"],
            ["Event subgroup G2-SG20 shall keep at least 20 records for Connection related."],
        )
        self.assertEqual(function["implementation_spec"]["event_retention"]["subgroups"][0]["subgroup"], "G2-SG20")
        self.assertNotIn("Gtwo", json.dumps(model, ensure_ascii=False))

    def test_event_definition_rows_emit_structured_developer_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "EVENT-DEF-1",
                    "requirement_type": "event_definition",
                    "requirement": "Event G1-SG10-E1 shall be defined as: \" Reboot \" with data loss.",
                    "object": "G1-SG10-E1",
                    "domain": "event",
                    "source_refs": ["TBL-EVENT-DEFINITION-R1"],
                    "section_path": ["Event definitions"],
                },
                {
                    "stable_req_id": "EVENT-DEF-2",
                    "requirement_type": "event_definition",
                    "requirement": "Event G3-SG31-E1 shall be defined as: voltage between phases below the limit.",
                    "object": "G3-SG31-E1",
                    "domain": "event",
                    "source_refs": ["TBL-EVENT-DEFINITION-R2"],
                    "section_path": ["Event definitions"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)
            written = write_engineering_requirements(out_dir, model)

            spec = model["requirement_functions"][0]["implementation_spec"]
            self.assertEqual(
                spec["event_definitions"]["events"],
                [
                    {
                        "event_code": "G1-SG10-E1",
                        "group": "G1",
                        "subgroup": "SG10",
                        "event_number": 1,
                        "description": '" Reboot " with data loss',
                    },
                    {
                        "event_code": "G3-SG31-E1",
                        "group": "G3",
                        "subgroup": "SG31",
                        "event_number": 1,
                        "description": "voltage between phases below the limit",
                    },
                ],
            )
            self.assertIn(
                "Map event G1-SG10-E1 to description: \" Reboot \" with data loss.",
                spec["processing_rules"],
            )
            self.assertIn("engineering_requirements/requirement_functions.md", written)
            markdown = (out_dir / "engineering_requirements" / "requirement_functions.md").read_text(encoding="utf-8")
            self.assertIn("Event definitions:", markdown)
            self.assertIn("G3-SG31-E1: voltage between phases below the limit", markdown)

    def test_short_object_name_does_not_match_inside_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "OBJ-FIC",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "FIC object shall be available.",
                    "object": "FIC",
                    "source_refs": ["TBL-FIC-OBJ"],
                    "section_path": ["Object model"],
                },
                {
                    "stable_req_id": "FUNC-FUNCTIONALITY",
                    "requirement_type": "functional",
                    "requirement": "If specific communication behavior is present, supported objects shall be implemented.",
                    "object": "",
                    "domain": "communication",
                    "source_refs": ["BLK-FUNC"],
                    "section_path": ["Communication"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-FIC-OBJ",
                    "table_id": "TBL-FIC",
                    "fields": {
                        "Object/attribute name": "FIC",
                        "CL": "1",
                        "Value": "0-0:96.1.0.255",
                    },
                }
            ])

            model = compose_engineering_requirements(out_dir)

            function = model["requirement_functions"][0]
            self.assertEqual(function["related_dlms_objects"], [])

    def test_low_information_table_value_row_is_not_promoted_to_function(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "OBJ-LONG-FAILURE",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "Threshold for long power failure shall be available.",
                    "object": "Threshold for long power failure",
                    "source_refs": ["TBL-LONG-FAILURE-R1"],
                    "section_path": ["Power quality objects"],
                },
                {
                    "stable_req_id": "FUNC-LOW-INFO",
                    "requirement_type": "capability_matrix",
                    "requirement": "two shall support Value.",
                    "object": "two",
                    "domain": "metering",
                    "source_refs": ["TBL-LONG-FAILURE-R2"],
                    "section_path": ["Power quality objects"],
                    "parameters": {
                        "subject_header": "#",
                        "predicate_header": "Value",
                        "marker": "x",
                    },
                },
                {
                    "stable_req_id": "FUNC-ACTIONABLE",
                    "requirement_type": "functional",
                    "requirement": "Power failure events shall be recorded when the threshold is exceeded.",
                    "object": "Power failure event",
                    "domain": "event",
                    "source_refs": ["BLK-LONG-FAILURE"],
                    "section_path": ["Power quality objects"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-LONG-FAILURE-R1",
                    "table_id": "TBL-LONG-FAILURE",
                    "row_index": 1,
                    "fields": {
                        "Object/attribute name": "Threshold for long power failure",
                        "CL": "3",
                        "Value": "1-0:0.9.1.255",
                    },
                },
                {
                    "item_id": "TBL-LONG-FAILURE-R2",
                    "table_id": "TBL-LONG-FAILURE",
                    "row_index": 2,
                    "fields": {"#": "2", "Object/attribute name": "Value"},
                },
            ])

            model = compose_engineering_requirements(out_dir)

        details = [
            detail
            for function in model["requirement_functions"]
            for detail in function["functional_details"]
        ]
        self.assertIn("Power failure events shall be recorded when the threshold is exceeded.", details)
        self.assertNotIn("two shall support Value.", details)

    def test_cosem_object_attribute_table_row_is_not_promoted_to_function(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "FUNC-EVENT-PUSH",
                    "requirement_type": "communication",
                    "requirement": "If the event shipping bit is set, the event must be sent via push communication.",
                    "object": "Data",
                    "domain": "event",
                    "source_refs": ["BLK-EVENT"],
                    "section_path": ["Control of"],
                },
                {
                    "stable_req_id": "OBJ-DATA",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "Meter serial object shall be available.",
                    "object": "Meter serial",
                    "source_refs": ["TBL-OBJECT-R1"],
                    "section_path": ["Control of"],
                },
                {
                    "stable_req_id": "ATTR-DATA-VALUE",
                    "requirement_type": "cosem_object",
                    "requirement": "two | Value | octet-string[13] | meter serial | electronic [10] must be | R-/R-/R-/R-",
                    "object": "Data",
                    "domain": "meter_function",
                    "source_refs": ["TBL-OBJECT-R2"],
                    "section_path": ["Control of"],
                    "parameters": {
                        "fields": {
                            "#": "two",
                            "Object/attribute name": "Value",
                            "Type": "octet-string[13]",
                            "Meaning": "meter serial",
                            "Access rights RC/PC/SC/LC": "R-/R-/R-/R-",
                        }
                    },
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-OBJECT-R1",
                    "table_id": "TBL-OBJECT",
                    "row_index": 1,
                    "fields": {
                        "Object/attribute name": "Meter serial",
                        "CL": "1",
                        "Value": "0-0:96.1.0.255",
                    },
                },
                {
                    "item_id": "TBL-OBJECT-R2",
                    "table_id": "TBL-OBJECT",
                    "row_index": 2,
                    "fields": {
                        "#": "two",
                        "Object/attribute name": "Value",
                        "Type": "octet-string[13]",
                        "Meaning": "meter serial",
                        "Access rights RC/PC/SC/LC": "R-/R-/R-/R-",
                    },
                },
            ])

            model = compose_engineering_requirements(out_dir)

        details = [
            detail
            for function in model["requirement_functions"]
            for detail in function["functional_details"]
        ]
        self.assertIn("If the event shipping bit is set, the event must be sent via push communication.", details)
        self.assertNotIn("two | Value | octet-string[13] | meter serial | electronic [10] must be | R-/R-/R-/R-", details)

    def test_structured_event_handling_suppresses_duplicate_raw_translation_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "OBJ-EVENT-FILTER",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "COSEM object Standard Event Log Filter shall be defined by the profile.",
                    "object": "Standard Event Log Filter",
                    "source_refs": ["TBL-FILTER-R1"],
                    "section_path": ["Event filters"],
                },
                {
                    "stable_req_id": "EVENT-RECORD",
                    "requirement_type": "communication",
                    "requirement": 'O record in one event at the log in events corresponding and/or O shipping in one event in communication " push " must) to be carried out in agreement with O programmed at the object "Filter of event logs." If the bit corresponding to the event register is set, the event must be registered at the log in events corresponding.',
                    "object": "Data",
                    "domain": "event",
                    "source_refs": ["BLK-EVENT"],
                    "section_path": ["Control of"],
                },
                {
                    "stable_req_id": "EVENT-PUSH",
                    "requirement_type": "communication",
                    "requirement": 'Case O bit corresponding to the shipping of event is set, the event must be sent via " push " communication , creating an APDU EVENT- NOTIFICATION-REQUEST and sending to inform the customer about your value.',
                    "object": "Data",
                    "domain": "event",
                    "source_refs": ["BLK-EVENT"],
                    "section_path": ["Control of"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-FILTER-R1",
                    "table_id": "TBL-FILTER",
                    "row_index": 1,
                    "fields": {
                        "Object/attribute name": "Standard Event Log Filter",
                        "CL": "1",
                        "Value": "0-1:94.55.105.255",
                    },
                },
            ])

            model = compose_engineering_requirements(out_dir)

        self.assertEqual(len(model["requirement_functions"]), 1)
        function = model["requirement_functions"][0]
        self.assertEqual(function["related_dlms_objects"], ["Standard Event Log Filter"])
        spec = function["implementation_spec"]
        self.assertEqual(spec["event_handling"]["recording_action"], "When the register bit is enabled, persist the event in the corresponding event log.")
        self.assertEqual(spec["event_handling"]["notification_action"], "When the shipping bit is enabled, send the event through push communication.")
        self.assertEqual(
            function["description"],
            "研发实现应覆盖事件记录与事件推送控制：按事件寄存器位记录事件，按事件推送位发送 push notification。",
        )
        rules = " ".join(spec["processing_rules"])
        self.assertNotIn("Case O bit corresponding", rules)
        self.assertNotIn("Event recording and push notification must follow", rules)

    def test_event_definitions_keep_event_grouping_when_security_objects_are_linked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "OBJ-SECURITY-SETUP",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "Security Setup object shall be available.",
                    "object": "Security Setup",
                    "source_refs": ["TBL-SECURITY-SETUP-R1"],
                    "section_path": ["Security objects"],
                },
                {
                    "stable_req_id": "EVENT-SECURITY-KEY",
                    "requirement_type": "event_definition",
                    "requirement": "Event G7-SG71-E3 shall be defined as: unicast encryption key changed - Remote Client.",
                    "object": "G7-SG71-E3",
                    "domain": "event",
                    "source_refs": ["TBL-EVENTS-R1"],
                    "section_path": ["Control of"],
                },
                {
                    "stable_req_id": "EVENT-SECURITY-AUTH",
                    "requirement_type": "event_definition",
                    "requirement": "Event G7-SG71-E4 shall be defined as: Changed authentication key - Remote Client.",
                    "object": "G7-SG71-E4",
                    "domain": "event",
                    "source_refs": ["TBL-EVENTS-R2"],
                    "section_path": ["Control of"],
                },
                {
                    "stable_req_id": "EVENT-POWER-KEY-OFF",
                    "requirement_type": "event_definition",
                    "requirement": "Event G1-SG10-E3 shall be defined as: Lack of power (key off).",
                    "object": "G1-SG10-E3",
                    "domain": "event",
                    "source_refs": ["TBL-EVENTS-R3"],
                    "section_path": ["Control of"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-SECURITY-SETUP-R1",
                    "table_id": "TBL-SECURITY-SETUP",
                    "row_index": 1,
                    "fields": {
                        "Object/attribute name": "Security Setup",
                        "CL": "64",
                        "Value": "0-0:43.0.0.255",
                    },
                },
            ])

            model = compose_engineering_requirements(out_dir)

        titles = [function["title"] for function in model["requirement_functions"]]
        self.assertNotIn("Security and key management", titles)
        security_events = next(function for function in model["requirement_functions"] if function["title"] == "Security event definitions")
        self.assertEqual(
            security_events["source_atomic_requirements"],
            ["EVENT-SECURITY-KEY", "EVENT-SECURITY-AUTH"],
        )
        self.assertEqual(security_events["related_dlms_objects"], ["Security Setup"])
        general_events = next(function for function in model["requirement_functions"] if function["title"] == "Event recording behavior")
        self.assertEqual(general_events["source_atomic_requirements"], ["EVENT-POWER-KEY-OFF"])
        self.assertEqual(general_events["related_dlms_objects"], [])

    def test_event_definition_translation_residue_is_normalized_in_details_and_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "EVENT-TWO",
                    "requirement_type": "event_definition",
                    "requirement": "Event G1-SG10-Etwo shall be defined as: Start of communication at the door PLC.",
                    "object": "G1-SG10-Etwo",
                    "domain": "event",
                    "source_refs": ["TBL-EVENTS-R1"],
                    "section_path": ["Control of"],
                },
                {
                    "stable_req_id": "EVENT-OPTICAL",
                    "requirement_type": "event_definition",
                    "requirement": "Event G6-SG60-E3 shall be defined as: Start of communication at the door optics.",
                    "object": "G6-SG60-E3",
                    "domain": "event",
                    "source_refs": ["TBL-EVENTS-R2"],
                    "section_path": ["Control of"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [])

            model = compose_engineering_requirements(out_dir)

        blob = json.dumps(model["requirement_functions"], ensure_ascii=False)
        self.assertIn("Event G1-SG10-E2 shall be defined as: Start of communication on the PLC port.", blob)
        self.assertIn("Event G6-SG60-E3 shall be defined as: Start of communication on the optical port.", blob)
        self.assertNotIn("Etwo", blob)
        self.assertNotIn("door PLC", blob)
        self.assertNotIn("door optics", blob)

    def test_event_retention_scope_mentions_do_not_create_dlms_object_impact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "OBJ-CLOCK",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "Clock object shall be available.",
                    "object": "Clock",
                    "source_refs": ["TBL-CLOCK-R1"],
                    "section_path": ["Clock objects"],
                },
                {
                    "stable_req_id": "EVENT-RETENTION-CLOCK",
                    "requirement_type": "event_group_retention",
                    "requirement": "Event subgroup G1-SG13 shall keep at least 15 records for Synchronized clock, recording old and new values date and time.",
                    "object": "G1-SG13",
                    "domain": "event",
                    "source_refs": ["TBL-EVENTS-R1"],
                    "section_path": ["Control of"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-CLOCK-R1",
                    "table_id": "TBL-CLOCK",
                    "row_index": 1,
                    "fields": {
                        "Object/attribute name": "Clock",
                        "CL": "8",
                        "Value": "0-0:1.0.0.255",
                    },
                },
            ])

            model = compose_engineering_requirements(out_dir)

        function = model["requirement_functions"][0]
        self.assertEqual(function["title"], "Event retention requirements")
        self.assertEqual(function["related_dlms_objects"], [])

    def test_absolute_load_curve_requirement_uses_load_profile_module_and_links_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "OBJ-LOAD-STATUS",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "AMR profile status for Load profile and quality with period 1 shall be available.",
                    "object": "AMR profile status for Load profile and quality with period 1",
                    "source_refs": ["TBL-LOAD-R1"],
                    "section_path": ["Load profile objects"],
                },
                {
                    "stable_req_id": "OBJ-LOAD-PROFILE",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "Load profile and quality with period 1 shall be available.",
                    "object": "Load profile and quality with period 1",
                    "source_refs": ["TBL-LOAD-R2"],
                    "section_path": ["Load profile objects"],
                },
                {
                    "stable_req_id": "FUNC-ABSOLUTE-LOAD-CURVE",
                    "requirement_type": "functional",
                    "requirement": "The energy quantities related to the absolute load curve should be collected all you days to the 00:00:00, It is The capacity in record he must to be in at the Minimum three months.",
                    "object": "Register Table",
                    "domain": "load_profile",
                    "source_refs": ["BLK-LOAD-CURVE"],
                    "section_path": ["Control of"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-LOAD-R1",
                    "table_id": "TBL-LOAD",
                    "row_index": 1,
                    "fields": {
                        "Object/attribute name": "AMR profile status for Load profile and quality with period 1",
                        "CL": "7",
                        "Value": "1-0:99.97.1.255",
                    },
                },
                {
                    "item_id": "TBL-LOAD-R2",
                    "table_id": "TBL-LOAD",
                    "row_index": 2,
                    "fields": {
                        "Object/attribute name": "Load profile and quality with period 1",
                        "CL": "7",
                        "Value": "1-0:99.1.0.255",
                    },
                },
            ])

            model = compose_engineering_requirements(out_dir)

        function = model["requirement_functions"][0]
        self.assertEqual(function["module"], "load_profile")
        self.assertEqual(function["title"], "Load profile collection and storage")
        self.assertEqual(
            function["related_dlms_objects"],
            [
                "AMR profile status for Load profile and quality with period 1",
                "Load profile and quality with period 1",
            ],
        )

    def test_context_attribute_from_different_table_is_not_attached_to_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "OBJ-CLOCK-TABLE",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "Clock object shall be available.",
                    "object": "Clock",
                    "source_refs": ["TBL-CLOCK-R1"],
                    "section_path": ["Clock objects"],
                },
                {
                    "stable_req_id": "ATTR-CLOCK-LOGICAL",
                    "requirement_type": "cosem_attribute_access",
                    "requirement": "Clock logical_name shall be readable.",
                    "object": "Clock.logical_name",
                    "source_refs": ["TBL-CLOCK-R2"],
                    "section_path": ["Clock objects"],
                },
                {
                    "stable_req_id": "ATTR-PROFILE-CAPTURE-CLOCK",
                    "requirement_type": "cosem_attribute_access",
                    "requirement": "Profile capture object entry references Clock.",
                    "object": "Clock.capture_objects",
                    "source_refs": ["TBL-PROFILE-R3"],
                    "section_path": ["Profile objects"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-CLOCK-R1",
                    "table_id": "TBL-CLOCK",
                    "fields": {
                        "Object/attribute name": "Clock",
                        "CL": "8",
                        "Value": "0-0:1.0.0.255",
                    },
                },
                {
                    "item_id": "TBL-CLOCK-R2",
                    "table_id": "TBL-CLOCK",
                    "fields": {
                        "#": "1",
                        "Object/attribute name": "logical_name",
                        "Type": "octet-string[6]",
                        "Access rights RC/PC/SC/LC": "R-/R-/R-/R-",
                    },
                },
                {
                    "item_id": "TBL-PROFILE-R3",
                    "table_id": "TBL-PROFILE",
                    "fields": {
                        "#": "3",
                        "Object/attribute name": "capture_objects",
                        "Type": "array",
                        "Access rights RC/PC/SC/LC": "R-/--/R-/R-",
                    },
                },
            ])

            model = compose_engineering_requirements(out_dir)

            clock = model["dlms_objects"][0]
            self.assertEqual([attr["name"] for attr in clock["attributes"]], ["logical_name"])
            self.assertEqual(clock["source_atomic_requirements"], ["OBJ-CLOCK-TABLE", "ATTR-CLOCK-LOGICAL"])
            self.assertEqual(model["analysis"]["orphan_dlms_attributes"], 1)

    def test_repeated_object_attributes_are_collapsed_with_observed_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "OBJ-PROFILE",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "Profile object shall be available.",
                    "object": "DRP Log",
                    "source_refs": ["TBL-PROFILE-R1"],
                    "section_path": ["Profile objects"],
                },
                {
                    "stable_req_id": "ATTR-CAPTURE-CLOCK",
                    "requirement_type": "cosem_attribute_access",
                    "requirement": "DRP Log capture_objects shall include Clock.",
                    "object": "DRP Log.capture_objects",
                    "source_refs": ["TBL-PROFILE-R2"],
                    "section_path": ["Profile objects"],
                },
                {
                    "stable_req_id": "ATTR-CAPTURE-REGISTER",
                    "requirement_type": "cosem_attribute_access",
                    "requirement": "DRP Log capture_objects shall include Register.",
                    "object": "DRP Log.capture_objects",
                    "source_refs": ["TBL-PROFILE-R3"],
                    "section_path": ["Profile objects"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-PROFILE-R1",
                    "table_id": "TBL-PROFILE",
                    "row_index": 1,
                    "fields": {
                        "Object/attribute name": "DRP Log",
                        "CL": "7",
                        "Value": "1-0:94.55.178.255",
                    },
                },
                {
                    "item_id": "TBL-PROFILE-R2",
                    "table_id": "TBL-PROFILE",
                    "row_index": 2,
                    "fields": {
                        "#": "3",
                        "Object/attribute name": "capture_objects",
                        "Type": "array",
                        "Value": "{8,0-0:1.0.0.255,2,0}",
                        "Access rights RC/PC/SC/LC": "R-/--/R-/R-",
                    },
                },
                {
                    "item_id": "TBL-PROFILE-R3",
                    "table_id": "TBL-PROFILE",
                    "row_index": 3,
                    "fields": {
                        "#": "3",
                        "Object/attribute name": "capture_objects",
                        "Type": "array",
                        "Value": "{3,1-0:1.8.0.255,2,0}",
                        "Access rights RC/PC/SC/LC": "R-/--/R-/R-",
                    },
                },
            ])

            model = compose_engineering_requirements(out_dir)
            write_engineering_requirements(out_dir, model)

            profile = model["dlms_objects"][0]
            markdown = (out_dir / "engineering_requirements" / "dlms_objects.md").read_text(encoding="utf-8")

        self.assertEqual(len(profile["attributes"]), 1)
        self.assertEqual(profile["attributes"][0]["name"], "capture_objects")
        self.assertEqual(
            profile["attributes"][0]["observed_values"],
            ["{8,0-0:1.0.0.255,2,0}", "{3,1-0:1.8.0.255,2,0}"],
        )
        self.assertEqual(markdown.count("capture_objects"), 2)  # access summary + table row
        self.assertIn("{8,0-0:1.0.0.255,2,0}; {3,1-0:1.8.0.255,2,0}", markdown)

    def test_action_rows_are_rendered_as_methods_not_attributes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "OBJ-SCRIPT",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "Script table shall be available.",
                    "object": "Global Meter Reset",
                    "source_refs": ["TBL-SCRIPT-R1"],
                    "section_path": ["Scripts"],
                },
                {
                    "stable_req_id": "ATTR-SCRIPT-LN",
                    "requirement_type": "cosem_attribute_access",
                    "requirement": "Script table logical name shall be readable.",
                    "object": "Global Meter Reset.logical_name",
                    "source_refs": ["TBL-SCRIPT-R2"],
                    "section_path": ["Scripts"],
                },
                {
                    "stable_req_id": "METHOD-SCRIPT-EXECUTE",
                    "requirement_type": "cosem_attribute_access",
                    "requirement": "Script table execute method shall be actionable.",
                    "object": "Global Meter Reset.execute",
                    "source_refs": ["TBL-SCRIPT-R3"],
                    "section_path": ["Scripts"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-SCRIPT-R1",
                    "table_id": "TBL-SCRIPT",
                    "row_index": 1,
                    "fields": {
                        "Object/attribute name": "Global Meter Reset",
                        "CL": "9",
                        "Value": "0-0:10.0.0.255",
                    },
                },
                {
                    "item_id": "TBL-SCRIPT-R2",
                    "table_id": "TBL-SCRIPT",
                    "row_index": 2,
                    "fields": {
                        "#": "1",
                        "Object/attribute name": "logical_name",
                        "Type": "octet-string[6]",
                        "Access rights RC/PC/SC/LC": "R-/--/R-/R-",
                    },
                },
                {
                    "item_id": "TBL-SCRIPT-R3",
                    "table_id": "TBL-SCRIPT",
                    "row_index": 3,
                    "fields": {
                        "#": "1",
                        "Object/attribute name": "execute",
                        "Access rights RC/PC/SC/LC": "-/-/A/A",
                    },
                },
            ])

            model = compose_engineering_requirements(out_dir)
            write_engineering_requirements(out_dir, model)
            script = model["dlms_objects"][0]
            markdown = (out_dir / "engineering_requirements" / "dlms_objects.md").read_text(encoding="utf-8")

        self.assertEqual([attr["name"] for attr in script["attributes"]], ["logical_name"])
        self.assertEqual([method["name"] for method in script["methods"]], ["execute"])
        self.assertIn("execute", script["method_summary"])
        self.assertIn("| # | Method | Access rights |", markdown)
        self.assertNotIn("| 1 | execute |  | -/-/A/A |", markdown)

    def test_write_only_action_style_rows_are_rendered_as_methods(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(out_dir / "atomic_requirements.jsonl", [
                {
                    "stable_req_id": "OBJ-SCRIPT",
                    "requirement_type": "cosem_object_instance",
                    "requirement": "Script table shall be available.",
                    "object": "Disconnect Script Table",
                    "source_refs": ["TBL-SCRIPT-R1"],
                    "section_path": ["Script objects"],
                },
                {
                    "stable_req_id": "METHOD-SCRIPT-EXECUTE",
                    "requirement_type": "cosem_attribute_access",
                    "requirement": "Execute shall be writable through secure clients.",
                    "object": "Disconnect Script Table.execute",
                    "source_refs": ["TBL-SCRIPT-R2"],
                    "section_path": ["Script objects"],
                },
            ])
            write_jsonl(out_dir / "table_items.jsonl", [
                {
                    "item_id": "TBL-SCRIPT-R1",
                    "table_id": "TBL-SCRIPT",
                    "row_index": 1,
                    "fields": {
                        "Object/attribute name": "Disconnect Script Table",
                        "CL": "9",
                        "Value": "0-0:10.0.106.255",
                    },
                },
                {
                    "item_id": "TBL-SCRIPT-R2",
                    "table_id": "TBL-SCRIPT",
                    "row_index": 2,
                    "fields": {
                        "#": "1",
                        "Object/attribute name": "execute",
                        "Type": "method",
                        "Access rights RC/PC/SC/LC": "--/--/-W/-W",
                    },
                },
            ])

            model = compose_engineering_requirements(out_dir)

        script = model["dlms_objects"][0]
        self.assertEqual(script["attributes"], [])
        self.assertEqual(script["methods"], [{"index": "1", "name": "execute", "access_rights": "--/--/-W/-W"}])


if __name__ == "__main__":
    unittest.main()
