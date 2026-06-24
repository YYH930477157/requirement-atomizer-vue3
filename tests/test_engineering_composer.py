from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

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
            self.assertEqual(sync["acceptance_criteria"], [])

            clock = next(item for item in objects if item["object_name"] == "Clock")
            self.assertEqual(clock["id"], "DLMS-001")
            self.assertEqual(clock["class_id"], "8")
            self.assertEqual(clock["obis"], "0-0:1.0.0.255")
            self.assertEqual(clock["attributes"][0]["name"], "time")
            self.assertEqual(clock["attributes"][0]["access_rights"], "R-/RW/RW/R-")
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
            self.assertIn("0-0:1.0.0.255", (out_dir / "engineering_requirements" / "dlms_objects.md").read_text(encoding="utf-8"))

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
            self.assertEqual(function["domain"], "曲线")

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


if __name__ == "__main__":
    unittest.main()
