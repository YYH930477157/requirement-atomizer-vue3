from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import cosem_object_model as com


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def write_fixture(out_dir: Path) -> None:
    write_jsonl(out_dir / "atomic_requirements.jsonl", [
        {"stable_req_id": "O-CLOCK", "requirement_type": "cosem_object_instance",
         "object": "Clock", "domain": "time", "source_refs": ["BLK-1", "TBL-1-R1"], "confidence": 0.9},
        {"stable_req_id": "O-REG", "requirement_type": "cosem_object_instance",
         "object": "Register", "domain": "metering", "source_refs": ["TBL-1-R2"], "confidence": 0.9},
        # 同名对象、不同 OBIS → 合法的两个 COSEM 实例，都要保留
        {"stable_req_id": "O-CLOCK2", "requirement_type": "cosem_object_instance",
         "object": "Clock", "domain": "time", "source_refs": ["TBL-1-R3"], "confidence": 0.7},
        {"stable_req_id": "A-CLOCK-TIME", "requirement_type": "cosem_attribute_access",
          "object": "Clock.time", "verification_method": "configuration_check",
         "source_refs": ["BLK-1", "TBL-2-R1"], "confidence": 0.9, "ambiguity": False},
        {"stable_req_id": "A-REG-VALUE", "requirement_type": "cosem_attribute_access",
         "object": "Register.value", "source_refs": ["TBL-2-R2"], "confidence": 0.9},
        # 父对象 Ghost 不存在 → 孤立
        {"stable_req_id": "A-GHOST", "requirement_type": "cosem_attribute_access",
         "object": "Ghost.x", "source_refs": ["TBL-2-R3"], "confidence": 0.5},
        {"stable_req_id": "U-1", "requirement_type": "measurement_quantity_unit",
         "object": "Active energy", "source_refs": ["TBL-3-R1"]},
    ])
    write_jsonl(out_dir / "table_items.jsonl", [
        {"item_id": "TBL-1-R1", "fields": {"Object/attribute name": "Clock", "CL": "8", "Value": "0-0:1.0.0.255"}},
        {"item_id": "TBL-1-R2", "fields": {"Object/attribute name": "Register", "CL": "3", "Value": "1-0:1.8.0.255"}},
        {"item_id": "TBL-1-R3", "fields": {"Object/attribute name": "Clock", "CL": "8", "Value": "0-0:1.0.0.111"}},
        {"item_id": "TBL-2-R1", "fields": {"#": "2", "Object/attribute name": "time", "Type": "octet-string",
                                            "Value": "00", "Access rights RC/PC/SC/LC": "R-/RW/--/R-"}},
        {"item_id": "TBL-2-R2", "fields": {"#": "2", "Object/attribute name": "value", "Type": "double-long-unsigned",
                                            "Value": "0", "Access rights RC/PC/SC/LC": "R-/R-/R-/R-"}},
        {"item_id": "TBL-2-R3", "fields": {"#": "2", "Object/attribute name": "x", "Type": "integer",
                                            "Access rights RC/PC/SC/LC": "--/--/--/--"}},
        {"item_id": "TBL-3-R1", "fields": {"Greatness": "Energy", "Greatness_2": "Active energy", "Unit": "Wh"}},
    ])
    write_jsonl(out_dir / "review_states.jsonl", [
        {"requirement_id": "O-CLOCK", "status": "accepted"},
    ])


class CosemObjectModelTests(unittest.TestCase):
    def test_join_counts_and_invariant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            model = com.build_object_model(out)
            counts = model["counts"]
            self.assertEqual(counts["objects"], 3)            # Clock x2, Register
            self.assertEqual(counts["attributes"], 3)          # time + value + x(orphan)
            self.assertEqual(counts["attributes_attached"], 2)
            self.assertEqual(counts["orphan_attributes"], 1)
            self.assertEqual(counts["units"], 1)
            self.assertEqual(counts["conflicts"], 0)
            # 不变量：总属性 == 挂载 + 孤立
            attached = sum(len(o["attributes"]) for o in model["objects"])
            self.assertEqual(counts["attributes"], attached + counts["orphan_attributes"])

    def test_object_obis_class_and_access_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            model = com.build_object_model(out)
            clock = next(o for o in model["objects"] if o["object"] == "Clock")
            self.assertEqual(clock["obis"], "0-0:1.0.0.255")
            self.assertEqual(clock["class_id"], "8")
            self.assertEqual(clock["review_status"], "accepted")
            self.assertEqual(len(clock["attributes"]), 1)
            time_attr = clock["attributes"][0]
            self.assertEqual(time_attr["name"], "time")
            self.assertEqual(time_attr["access"], {"RC": "R-", "PC": "RW", "SC": "--", "LC": "R-"})
            self.assertEqual(time_attr["verification_method"], "configuration_check")

    def test_orphan_surfaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            model = com.build_object_model(out)
            self.assertEqual([a["parent"] for a in model["orphan_attributes"]], ["Ghost"])

    def test_same_name_different_obis_instances_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            model = com.build_object_model(out)

            clocks = [o for o in model["objects"] if o["object"] == "Clock"]

        self.assertEqual([o["obis"] for o in clocks], ["0-0:1.0.0.255", "0-0:1.0.0.111"])
        self.assertEqual(clocks[0]["source_atomic_requirements"], ["O-CLOCK", "A-CLOCK-TIME"])
        self.assertEqual(clocks[1]["source_atomic_requirements"], ["O-CLOCK2"])

    def test_continuation_table_attributes_attach_to_previous_instance_until_next_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_jsonl(out / "atomic_requirements.jsonl", [
                {"stable_req_id": "O-ASSOC-0", "requirement_type": "cosem_object_instance",
                 "object": "Association LN", "source_refs": ["TBL-1-R5"]},
                {"stable_req_id": "A-ASSOC-0-LN", "requirement_type": "cosem_attribute_access",
                 "object": "Association LN.logical_name", "source_refs": ["TBL-1-R6"]},
                {"stable_req_id": "O-ASSOC-1", "requirement_type": "cosem_object_instance",
                 "object": "Association LN", "source_refs": ["TBL-1-R18"]},
                {"stable_req_id": "A-ASSOC-1-LN", "requirement_type": "cosem_attribute_access",
                 "object": "Association LN.logical_name", "source_refs": ["TBL-1-R19"]},
                {"stable_req_id": "A-ASSOC-1-OBJLIST", "requirement_type": "cosem_attribute_access",
                 "object": "Association LN.object_list", "source_refs": ["TBL-2-R2"]},
                {"stable_req_id": "O-ASSOC-2", "requirement_type": "cosem_object_instance",
                 "object": "Association LN", "source_refs": ["TBL-2-R13"]},
                {"stable_req_id": "A-ASSOC-2-LN", "requirement_type": "cosem_attribute_access",
                 "object": "Association LN.logical_name", "source_refs": ["TBL-2-R14"]},
            ])
            write_jsonl(out / "table_items.jsonl", [
                {"item_id": "TBL-1-R5", "table_id": "TBL-1", "row_index": 5,
                 "fields": {"Object/attribute name": "Association LN", "CL": "15", "Value": "0-0:40.0.0.255"}},
                {"item_id": "TBL-1-R6", "table_id": "TBL-1", "row_index": 6,
                 "fields": {"#": "1", "Object/attribute name": "logical_name", "Access rights RC/PC/SC/LC": "R-/--/R-/R-"}},
                {"item_id": "TBL-1-R18", "table_id": "TBL-1", "row_index": 18,
                 "fields": {"Object/attribute name": "Association LN", "CL": "15", "Value": "0-0:40.0.1.255"}},
                {"item_id": "TBL-1-R19", "table_id": "TBL-1", "row_index": 19,
                 "fields": {"#": "1", "Object/attribute name": "logical_name", "Access rights RC/PC/SC/LC": "R-/--/R-/R-"}},
                {"item_id": "TBL-2-R2", "table_id": "TBL-2", "row_index": 2,
                 "fields": {"#": "2", "Object/attribute name": "object_list", "Access rights RC/PC/SC/LC": "R-/--/R-/R-"}},
                {"item_id": "TBL-2-R13", "table_id": "TBL-2", "row_index": 13,
                 "fields": {"Object/attribute name": "Association LN", "CL": "15", "Value": "0-0:40.0.2.255"}},
                {"item_id": "TBL-2-R14", "table_id": "TBL-2", "row_index": 14,
                 "fields": {"#": "1", "Object/attribute name": "logical_name", "Access rights RC/PC/SC/LC": "R-/--/R-/R-"}},
            ])

            model = com.build_object_model(out)
            associations = [o for o in model["objects"] if o["object"] == "Association LN"]

        self.assertEqual([o["obis"] for o in associations], ["0-0:40.0.0.255", "0-0:40.0.1.255", "0-0:40.0.2.255"])
        self.assertEqual([a["name"] for a in associations[0]["attributes"]], ["logical_name"])
        self.assertEqual([a["name"] for a in associations[1]["attributes"]], ["logical_name", "object_list"])
        self.assertEqual([a["name"] for a in associations[2]["attributes"]], ["logical_name"])

    def test_class_level_attributes_attach_to_matching_class_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_jsonl(out / "atomic_requirements.jsonl", [
                {"stable_req_id": "O-BILLING-PROFILE", "requirement_type": "cosem_object_instance",
                 "object": "Stored Billing Values Profile", "source_refs": ["TBL-OBJ-R1"]},
                {"stable_req_id": "A-PROFILE-CAPTURE", "requirement_type": "cosem_attribute_access",
                 "object": "Profile Generic.capture_objects", "source_refs": ["TBL-CLASS-R3"]},
            ])
            write_jsonl(out / "table_items.jsonl", [
                {"item_id": "TBL-OBJ-R1", "table_id": "TBL-OBJ", "row_index": 1,
                 "fields": {"Object/attribute name": "Stored Billing Values Profile", "CL": "7", "Value": "1-0:98.1.0.255"}},
                {"item_id": "TBL-CLASS-R3", "table_id": "TBL-CLASS", "row_index": 3,
                 "fields": {"#": "3", "Object/attribute name": "capture_objects", "Type": "array",
                            "Access rights RC/PC/SC/LC": "R-/--/R-/R-"}},
            ])

            model = com.build_object_model(out)

        profile = model["objects"][0]
        self.assertEqual(model["counts"]["orphan_attributes"], 0)
        self.assertEqual([a["name"] for a in profile["attributes"]], ["capture_objects"])
        self.assertEqual(profile["attributes"][0]["scope"], "class_template")
        self.assertEqual(profile["attributes"][0]["template_parent"], "Profile Generic")
        self.assertEqual(model["counts"]["source_attribute_requirements"], 1)
        self.assertEqual(model["counts"]["projected_class_attributes"], 1)
        self.assertEqual(profile["source_atomic_requirements"], ["O-BILLING-PROFILE", "A-PROFILE-CAPTURE"])

    def test_class_level_attribute_names_match_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_jsonl(out / "atomic_requirements.jsonl", [
                {"stable_req_id": "O-DATA", "requirement_type": "cosem_object_instance",
                 "object": "Event filter", "source_refs": ["TBL-DATA-R1"]},
                {"stable_req_id": "A-DATA-VALUE", "requirement_type": "cosem_attribute_access",
                 "object": "Data.Value", "source_refs": ["TBL-DATA-R2"]},
            ])
            write_jsonl(out / "table_items.jsonl", [
                {"item_id": "TBL-DATA-R1", "table_id": "TBL-DATA", "row_index": 1,
                 "fields": {"Object/attribute name": "Event filter", "CL": "1", "Value": "0-1:94.55.116.255"}},
                {"item_id": "TBL-DATA-R2", "table_id": "TBL-CLASS", "row_index": 2,
                 "fields": {"#": "2", "Object/attribute name": "Value", "Type": "array",
                            "Access rights RC/PC/SC/LC": "R-/--/RW/RW"}},
            ])

            model = com.build_object_model(out)

        data_object = model["objects"][0]
        self.assertEqual(model["counts"]["orphan_attributes"], 0)
        self.assertEqual([a["name"] for a in data_object["attributes"]], ["value"])
        self.assertEqual(data_object["attributes"][0]["scope"], "class_template")
        self.assertEqual(data_object["attributes"][0]["template_parent"], "Data")

    def test_class_level_attributes_do_not_broadcast_to_unrelated_same_class_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_jsonl(out / "atomic_requirements.jsonl", [
                {"stable_req_id": "O-DATA-A", "requirement_type": "cosem_object_instance",
                 "object": "Event filter", "source_refs": ["TBL-DATA-R1"]},
                {"stable_req_id": "O-DATA-B", "requirement_type": "cosem_object_instance",
                 "object": "Security invocation counter", "source_refs": ["TBL-SEC-R1"]},
                {"stable_req_id": "A-DATA-VALUE", "requirement_type": "cosem_attribute_access",
                 "object": "Data.Value", "source_refs": ["TBL-DATA-R2"]},
            ])
            write_jsonl(out / "table_items.jsonl", [
                {"item_id": "TBL-DATA-R1", "table_id": "TBL-DATA", "row_index": 1,
                 "fields": {"Object/attribute name": "Event filter", "CL": "1", "Value": "0-1:94.55.116.255"}},
                {"item_id": "TBL-SEC-R1", "table_id": "TBL-SEC", "row_index": 1,
                 "fields": {"Object/attribute name": "Security invocation counter", "CL": "1", "Value": "0-0:43.1.0.255"}},
                {"item_id": "TBL-DATA-R2", "table_id": "TBL-DATA", "row_index": 2,
                 "fields": {"#": "2", "Object/attribute name": "Value", "Type": "array",
                            "Access rights RC/PC/SC/LC": "R-/--/RW/RW"}},
            ])

            model = com.build_object_model(out)

        objects = {item["object"]: item for item in model["objects"]}
        self.assertEqual([a["name"] for a in objects["Event filter"]["attributes"]], ["value"])
        self.assertEqual(objects["Security invocation counter"]["attributes"], [])
        self.assertEqual(model["counts"]["orphan_attributes"], 0)
        self.assertEqual(model["counts"]["projected_class_attributes"], 1)

    def test_extended_register_reset_method_projects_to_class_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_jsonl(out / "atomic_requirements.jsonl", [
                {"stable_req_id": "O-EXT-REG", "requirement_type": "cosem_object_instance",
                 "object": "Maximum Active Demand Register import", "source_refs": ["TBL-REG-R1"]},
                {"stable_req_id": "A-EXT-RESET", "requirement_type": "cosem_attribute_access",
                 "object": "Extended Register.reset", "source_refs": ["TBL-CLASS-R1"]},
            ])
            write_jsonl(out / "table_items.jsonl", [
                {"item_id": "TBL-REG-R1", "table_id": "TBL-REG", "row_index": 1,
                 "fields": {"Object/attribute name": "Maximum Active Demand Register import", "CL": "4", "Value": "1-0:1.6.0.255"}},
                {"item_id": "TBL-CLASS-R1", "table_id": "TBL-CLASS", "row_index": 2,
                 "fields": {"#": "1", "Object/attribute name": "reset", "Access rights RC/PC/SC/LC": "A/-/A/A"}},
            ])

            model = com.build_object_model(out)

        register = model["objects"][0]
        self.assertEqual(model["counts"]["orphan_attributes"], 0)
        self.assertEqual([a["name"] for a in register["attributes"]], ["reset"])
        self.assertEqual(register["attributes"][0]["scope"], "class_template")
        self.assertEqual(register["attributes"][0]["template_parent"], "Extended Register")

    def test_single_action_schedule_template_attributes_project_to_class_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_jsonl(out / "atomic_requirements.jsonl", [
                {"stable_req_id": "O-SAS", "requirement_type": "cosem_object_instance",
                 "object": "Key expiration Single action schedule", "source_refs": ["TBL-SAS-R1"]},
                {"stable_req_id": "A-SAS-SCRIPT", "requirement_type": "cosem_attribute_access",
                 "object": "Single Action Schedule.executed_script", "source_refs": ["TBL-CLASS-R2"]},
                {"stable_req_id": "A-SAS-TYPE", "requirement_type": "cosem_attribute_access",
                 "object": "Single Action Schedule.Type", "source_refs": ["TBL-CLASS-R3"]},
                {"stable_req_id": "A-SAS-TIME", "requirement_type": "cosem_attribute_access",
                 "object": "Single Action Schedule.execution_time", "source_refs": ["TBL-CLASS-R4"]},
            ])
            write_jsonl(out / "table_items.jsonl", [
                {"item_id": "TBL-SAS-R1", "table_id": "TBL-SAS", "row_index": 1,
                 "fields": {"Object/attribute name": "Key expiration Single action schedule", "CL": "22", "Value": "0-0:15.0.7.255"}},
                {"item_id": "TBL-CLASS-R2", "table_id": "TBL-CLASS", "row_index": 2,
                 "fields": {"#": "2", "Object/attribute name": "executed_script", "Access rights RC/PC/SC/LC": "R-/--/RW/RW"}},
                {"item_id": "TBL-CLASS-R3", "table_id": "TBL-CLASS", "row_index": 3,
                 "fields": {"#": "3", "Object/attribute name": "Type", "Access rights RC/PC/SC/LC": "R-/--/R-/R-"}},
                {"item_id": "TBL-CLASS-R4", "table_id": "TBL-CLASS", "row_index": 4,
                 "fields": {"#": "4", "Object/attribute name": "execution_time", "Access rights RC/PC/SC/LC": "R-/--/RW/RW"}},
            ])

            model = com.build_object_model(out)

        schedule = model["objects"][0]
        self.assertEqual(model["counts"]["orphan_attributes"], 0)
        self.assertEqual([a["name"] for a in schedule["attributes"]], ["executed_script", "type", "execution_time"])
        self.assertEqual([a["template_parent"] for a in schedule["attributes"]], ["Single Action Schedule", "Single Action Schedule", "Single Action Schedule"])

    def test_truncated_parent_name_attaches_to_same_table_class_instance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_jsonl(out / "atomic_requirements.jsonl", [
                {"stable_req_id": "O-DISCONNECT-AUX", "requirement_type": "cosem_object_instance",
                 "object": "Disconnect Control for Aux. relay", "source_refs": ["TBL-DISC-R1"]},
                {"stable_req_id": "A-DISCONNECT-AUX-LN", "requirement_type": "cosem_attribute_access",
                 "object": "Disconnect Control for Aux.logical_name", "source_refs": ["TBL-DISC-R2"]},
                {"stable_req_id": "A-DISCONNECT-AUX-STATE", "requirement_type": "cosem_attribute_access",
                 "object": "Disconnect Control for Aux.output_state", "source_refs": ["TBL-DISC-R3"]},
            ])
            write_jsonl(out / "table_items.jsonl", [
                {"item_id": "TBL-DISC-R1", "table_id": "TBL-DISC", "row_index": 1,
                 "fields": {"Object/attribute name": "Disconnect Control for Aux. relay", "CL": "70", "Value": "0-0:96.3.129.255"}},
                {"item_id": "TBL-DISC-R2", "table_id": "TBL-DISC", "row_index": 2,
                 "fields": {"#": "1", "Object/attribute name": "logical_name", "Type": "octet-string[6]",
                            "Access rights RC/PC/SC/LC": "R-/--/R-/R-"}},
                {"item_id": "TBL-DISC-R3", "table_id": "TBL-DISC", "row_index": 3,
                 "fields": {"#": "2", "Object/attribute name": "output_state", "Type": "boolean",
                            "Access rights RC/PC/SC/LC": "R-/--/R-/R-"}},
            ])

            model = com.build_object_model(out)

        disconnect = model["objects"][0]
        self.assertEqual(model["counts"]["orphan_attributes"], 0)
        self.assertEqual(disconnect["object"], "Disconnect Control for Aux. relay")
        self.assertEqual([a["name"] for a in disconnect["attributes"]], ["logical_name", "output_state"])
        self.assertEqual(
            disconnect["source_atomic_requirements"],
            ["O-DISCONNECT-AUX", "A-DISCONNECT-AUX-LN", "A-DISCONNECT-AUX-STATE"],
        )

    def test_attribute_name_parent_recovers_same_table_previous_class_instance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_jsonl(out / "atomic_requirements.jsonl", [
                {"stable_req_id": "O-PROFILE", "requirement_type": "cosem_object_instance",
                 "object": "Correct security operations event log", "source_refs": ["TBL-PROFILE-R1"]},
                {"stable_req_id": "A-PROFILE-SORT", "requirement_type": "cosem_attribute_access",
                 "object": "sort_object.sort_object", "source_refs": ["TBL-PROFILE-R6"]},
            ])
            write_jsonl(out / "table_items.jsonl", [
                {"item_id": "TBL-PROFILE-R1", "table_id": "TBL-PROFILE", "row_index": 1,
                 "fields": {"Object/attribute name": "Correct security operations event log", "CL": "7", "Value": "0-0:99.98.11.255"}},
                {"item_id": "TBL-PROFILE-R6", "table_id": "TBL-PROFILE", "row_index": 6,
                 "fields": {"#": "6", "Object/attribute name": "sort_object", "Type": "object definition",
                            "Access rights RC/PC/SC/LC": "R-/--/R-/R-"}},
            ])

            model = com.build_object_model(out)

        profile = model["objects"][0]
        self.assertEqual(model["counts"]["orphan_attributes"], 0)
        self.assertEqual([a["name"] for a in profile["attributes"]], ["sort_object"])
        self.assertEqual(profile["source_atomic_requirements"], ["O-PROFILE", "A-PROFILE-SORT"])

    def test_write_emits_three_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            model = com.build_object_model(out)
            written = com.write_object_model(out, model)
            self.assertEqual(set(written), {"cosem_object_model.json", "cosem_object_model.md", "cosem_attribute_matrix.csv"})
            for name in written:
                self.assertTrue((out / name).exists())
            md = (out / "cosem_object_model.md").read_text(encoding="utf-8")
            self.assertIn("OBIS `0-0:1.0.0.255`", md)
            self.assertIn("Ghost", md)  # 孤立分组出现


if __name__ == "__main__":
    unittest.main()
