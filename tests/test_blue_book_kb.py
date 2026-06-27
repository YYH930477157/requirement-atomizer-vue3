from __future__ import annotations

import json
import unittest
from pathlib import Path

from requirement_kb import KnowledgeRepository
from requirement_kb.cli import default_kb_paths
from requirement_kb.obsidian import compile_vault_to_json
from requirement_kb.schema import validate_kb_file
from requirement_kb.vault import validate_vault


ROOT = Path(__file__).resolve().parents[1]


BLUE_BOOK_PART2_CURRENT_CLASSES = [
    (1, 0, "Data"),
    (3, 0, "Register"),
    (4, 0, "Extended register"),
    (5, 0, "Demand register"),
    (6, 0, "Register activation"),
    (7, 1, "Profile generic"),
    (26, 0, "Utility tables"),
    (61, 0, "Register table"),
    (63, 0, "Status mapping"),
    (62, 1, "Compact data"),
    (66, 0, "Measurement data monitoring objects"),
    (12, 4, "Association SN"),
    (15, 3, "Association LN"),
    (17, 0, "SAP assignment"),
    (18, 0, "Image transfer"),
    (64, 1, "Security setup"),
    (30, 0, "COSEM data protection"),
    (123, 0, "Array manager"),
    (124, 0, "Communication port protection"),
    (8, 0, "Clock"),
    (9, 0, "Script table"),
    (10, 0, "Schedule"),
    (11, 0, "Special days table"),
    (20, 0, "Activity calendar"),
    (21, 0, "Register monitor"),
    (22, 0, "Single action schedule"),
    (70, 1, "Disconnect control"),
    (71, 0, "Limiter"),
    (65, 1, "Parameter monitor"),
    (67, 0, "Sensor manager"),
    (68, 0, "Arbitrator"),
    (111, 0, "Account"),
    (112, 0, "Credit"),
    (113, 0, "Charge"),
    (115, 0, "Token gateway"),
    (116, 0, "IEC 62055-41 attributes"),
    (19, 1, "IEC local port setup"),
    (23, 1, "IEC HDLC setup"),
    (24, 1, "IEC twisted pair (1) setup"),
    (27, 1, "Modem configuration"),
    (28, 2, "Auto answer"),
    (29, 2, "Auto connect"),
    (45, 0, "GPRS modem setup"),
    (25, 0, "M-Bus slave port setup"),
    (72, 2, "M-Bus client"),
    (73, 1, "Wireless Mode Q channel"),
    (74, 0, "M-Bus master port setup"),
    (76, 0, "DLMS server M-Bus port setup"),
    (77, 0, "M-Bus diagnostic"),
    (41, 0, "TCP-UDP setup"),
    (42, 0, "IPv4 setup"),
    (48, 0, "IPv6 setup"),
    (43, 0, "MAC address setup"),
    (44, 0, "PPP setup"),
    (46, 0, "SMTP setup"),
    (100, 0, "NTP setup"),
    (153, 0, "CoAP diagnostic"),
    (50, 1, "S-FSK Phy&MAC set-up"),
    (51, 0, "S-FSK Active initiator"),
    (52, 0, "S-FSK MAC synchronization timeouts"),
    (53, 0, "S-FSK MAC counters"),
    (55, 1, "IEC 61334-4-32 LLC setup"),
    (56, 0, "S-FSK Reporting system list"),
    (57, 0, "ISO/IEC 8802-2 LLC Type 1 setup"),
    (58, 0, "ISO/IEC 8802-2 LLC Type 2 setup"),
    (59, 0, "ISO/IEC 8802-2 LLC Type 3 setup"),
    (80, 0, "61334-4-32 LLC SSCS setup"),
    (82, 0, "PRIME NB OFDM PLC MAC setup"),
    (84, 0, "PRIME NB OFDM PLC MAC counters"),
    (90, 1, "G3-PLC MAC layer counters"),
    (91, 4, "G3-PLC MAC setup"),
    (92, 4, "G3-PLC 6LoWPAN adaptation layer setup"),
    (160, 0, "G3-PLC Hybrid RF MAC layer counters"),
    (161, 1, "G3-PLC Hybrid RF MAC setup"),
    (140, 0, "HS-PLC ISO/IEC 12139-1 MAC setup"),
    (141, 0, "HS-PLC ISO/IEC 12139-1 CPAS setup"),
    (142, 0, "HS-PLC ISO/IEC 12139-1 IP SSAS setup"),
    (101, 0, "ZigBee SAS startup"),
    (102, 0, "ZigBee SAS join"),
    (103, 0, "ZigBee SAS APS fragmentation"),
    (104, 0, "ZigBee network control"),
    (105, 0, "ZigBee tunnel setup"),
    (130, 0, "ISO/IEC 14908 identification"),
    (131, 0, "ISO/IEC 14908 protocol setup"),
    (132, 0, "ISO/IEC 14908 protocol status"),
    (133, 0, "ISO/IEC 14908 diagnostic"),
]

BLUE_BOOK_PART1_OBIS_TABLES = [
    (1, "OBIS code structure and use of value groups"),
    (2, "Rules for manufacturer, utility, consortia and country specific codes"),
    (3, "Value group A codes"),
    (4, "Value group B codes"),
    (5, "Value group C codes - Abstract objects"),
    (6, "Value group D codes - Consortia specific identifiers"),
    (7, "Value group D codes - Country specific identifiers"),
    (8, "OBIS codes for general and service entry objects"),
    (9, "OBIS codes for error registers, alarm registers and alarm filters - Abstract"),
    (10, "OBIS codes for list objects - Abstract"),
    (11, "OBIS codes for Register table objects - Abstract"),
    (12, "OBIS codes for data profile objects - Abstract"),
    (13, "Value group C codes - AC Electricity"),
    (14, "Value group D codes - AC electricity"),
    (15, "Value group E codes - AC electricity - Tariff rates"),
    (16, "Value group E codes - AC electricity - Harmonics"),
    (17, "Value group E codes - AC electricity - Extended phase angle measurement"),
    (18, "Value group E codes - AC electricity - Transformer and line losses"),
    (19, "Value group E codes - AC electricity - UNIPEDE voltage dips"),
    (20, "Value group E codes for distortion power and energy"),
    (21, "OBIS codes for general and service entry objects - AC electricity"),
    (22, "OBIS codes for error register objects - AC electricity"),
    (23, "OBIS codes for list objects - AC electricity"),
    (24, "OBIS codes for data profile objects - AC electricity"),
    (25, "OBIS codes for register table objects - AC electricity"),
    (26, "Value group C codes - DC electricity"),
    (27, "Value group D codes - DC electricity"),
    (28, "Value group E codes - DC electricity - Tariff rates"),
    (29, "OBIS codes for general and service entry objects - DC electricity"),
    (30, "OBIS codes for error register objects - DC electricity"),
    (31, "OBIS codes for list objects - DC electricity"),
    (32, "OBIS codes for data profile objects - DC electricity"),
    (33, "OBIS codes for Register table objects - DC electricity"),
    (34, "Value group C codes - HCA"),
    (35, "Value group D codes - HCA"),
    (36, "Value group E codes - HCA"),
    (37, "OBIS codes for general and service entry objects - HCA"),
    (38, "OBIS codes for error register objects - HCA"),
    (39, "OBIS codes for list objects - HCA"),
    (40, "OBIS codes for data profile objects - HCA"),
    (41, "OBIS codes for HCA related objects (examples)"),
    (42, "Value group C codes - Thermal energy"),
    (43, "Value group D codes - Thermal energy"),
    (44, "Value group E codes - Thermal Energy - Tariff rates"),
    (45, "OBIS codes for general and service entry objects - Thermal energy"),
    (46, "OBIS codes for error register objects - Thermal energy"),
    (47, "OBIS codes for list objects - Thermal Energy Meters"),
    (48, "OBIS codes for data profile objects - Thermal energy"),
    (49, "OBIS codes for Thermal energy related objects (examples)"),
    (50, "OBIS codes of the main objects in the gas conversion process data flow"),
    (51, "Value group C codes - Gas"),
    (52, "Value group D codes - Gas - Indexes and index differences"),
    (53, "Value group D codes - Gas - Flow rate"),
    (54, "Value group D codes - Gas - Process values"),
    (55, "Value group D codes - Gas - Conversion related factors and coefficients"),
    (56, "Value group D codes - Gas - Natural gas analysis values"),
    (57, "Value group E codes - Gas - Indexes and index differences - Tariff rates"),
    (58, "Value group E codes - Gas - Conversion related factors and coefficients"),
    (59, "Value group E codes - Gas - Calculation methods"),
    (60, "Value group E codes - Gas - Natural gas analysis values - Averages"),
    (61, "OBIS codes for general and service entry objects - Gas"),
    (62, "OBIS codes for error register objects - Gas"),
    (63, "OBIS codes for list objects - Gas"),
    (64, "OBIS codes for data profile objects - Gas"),
    (65, "Value group C codes - Water"),
    (66, "Value group D codes - Water"),
    (67, "Value group E codes - Water"),
    (68, "OBIS codes for general and service entry objects - Water"),
    (69, "OBIS codes for error register objects - Water"),
    (70, "OBIS codes for list objects - Water Meters"),
    (71, "OBIS codes for data profile objects - Water"),
    (72, "OBIS codes for water related objects (examples)"),
    (73, "Value group C codes - Other media"),
]


class BlueBookKnowledgeBaseTests(unittest.TestCase):
    def test_default_kb_paths_include_compiled_obsidian_blue_book_entries(self) -> None:
        paths = default_kb_paths()

        self.assertIn(ROOT / "knowledge_bases" / "compiled_from_obsidian.json", paths)

    def test_compiled_obsidian_kb_matches_blue_book_obis_and_interface_class_terms(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "DLMS UA 1000-1 Ed. 16 Part 1 defines the OBIS value groups A-B:C.D.E.F. "
            "Part 2 defines COSEM interface classes such as Compact data class_id 62, "
            "Register table class_id 61, Limiter class_id 71, Push setup class_id 40, "
            "and IPv6 setup class_id 48."
        )
        matches = repo.match_text(text, limit=20)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-BLUE-BOOK-PART-1-OBIS", matched_ids)
        self.assertIn("KB-BLUE-BOOK-PART-2-IC", matched_ids)
        self.assertIn("KB-BLUE-BOOK-OBIS-VALUE-GROUPS", matched_ids)
        self.assertIn("KB-L3-IC-62-COMPACT-DATA", matched_ids)
        self.assertIn("KB-L3-IC-61-REGISTER-TABLE", matched_ids)
        self.assertIn("KB-L3-IC-71-LIMITER", matched_ids)
        self.assertIn("KB-L3-IC-40-PUSH-SETUP", matched_ids)
        self.assertIn("KB-L3-IC-48-IPV6-SETUP", matched_ids)

    def test_obsidian_vault_compiles_to_schema_valid_blue_book_runtime_kb(self) -> None:
        report = validate_vault(ROOT / "obsidian-vault")
        self.assertEqual(report.errors, 0, report.to_dict())

        payload = compile_vault_to_json(
            ROOT / "obsidian-vault",
            ROOT / "out" / "test_compiled_blue_book.json",
            kb_id="obsidian_energy_metering",
        )
        blue_book_ids = {entry["id"] for entry in payload["entries"] if str(entry["id"]).startswith("KB-BLUE-BOOK")}

        self.assertGreaterEqual(len(blue_book_ids), 4)
        self.assertEqual(validate_kb_file(ROOT / "out" / "test_compiled_blue_book.json"), [])

    def test_gui_abnt_preset_passes_compiled_obsidian_kb_to_backend(self) -> None:
        app_vue = (ROOT / "ui" / "src" / "App.vue").read_text(encoding="utf-8")

        self.assertIn('"knowledge_bases/compiled_from_obsidian.json"', app_vue)

    def test_electron_run_helper_includes_compiled_obsidian_kb_in_preset_expectation(self) -> None:
        helper_spec = (ROOT / "ui" / "electron" / "__tests__" / "main.helpers.spec.ts").read_text(encoding="utf-8")

        self.assertIn('"knowledge_bases/compiled_from_obsidian.json"', helper_spec)

    def test_compiled_obsidian_json_on_disk_contains_blue_book_entries(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        ids = {entry["id"] for entry in payload["entries"]}

        self.assertIn("KB-BLUE-BOOK-PART-1-OBIS", ids)
        self.assertIn("KB-BLUE-BOOK-PART-2-IC", ids)

    def test_seed_cosem_class_ids_follow_blue_book_part_2_catalogue(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "energy_metering_cosem_classes.json").read_text(encoding="utf-8"))
        by_name = {entry["name"]: entry for entry in payload["entries"]}

        self.assertEqual(by_name["TCP-UDP Setup"]["class_id"], 41)
        self.assertEqual(by_name["IPv4 Setup"]["class_id"], 42)

    def test_obsidian_cosem_class_notes_are_grouped_by_class_id_family(self) -> None:
        class_root = ROOT / "obsidian-vault" / "03_cosem_classes"
        flat_notes = sorted(path.name for path in class_root.glob("*.md"))
        self.assertEqual(flat_notes, [])

        expected_dirs = {
            "001-Data",
            "003-Register",
            "007-Profile Generic",
            "015-Association LN",
            "023-IEC HDLC Setup",
            "041-TCP-UDP Setup",
            "042-IPv4 Setup",
            "061-Register Table",
            "064-Security Setup",
        }
        actual_dirs = {path.name for path in class_root.iterdir() if path.is_dir()}
        self.assertTrue(expected_dirs.issubset(actual_dirs))

        for note_path in sorted(class_root.rglob("*.md")):
            text = note_path.read_text(encoding="utf-8")
            marker = '"class_id": '
            self.assertIn(marker, text, note_path)
            class_id = int(text.split(marker, 1)[1].split(",", 1)[0])
            self.assertTrue(note_path.parent.name.startswith(f"{class_id:03d}-"), note_path)

    def test_obsidian_object_instance_notes_are_grouped_by_class_id_family(self) -> None:
        instance_root = ROOT / "obsidian-vault" / "04_object_instances"
        flat_notes = sorted(path.name for path in instance_root.glob("*.md"))
        self.assertEqual(flat_notes, [])

        expected_dirs = {
            "001-Data",
            "003-Register",
            "006-Register Activation",
            "007-Profile Generic",
            "015-Association LN",
            "017-SAP Assignment",
            "020-Activity Calendar",
            "061-Register Table",
        }
        actual_dirs = {path.name for path in instance_root.iterdir() if path.is_dir()}
        self.assertTrue(expected_dirs.issubset(actual_dirs))

        for note_path in sorted(instance_root.rglob("*.md")):
            text = note_path.read_text(encoding="utf-8")
            marker = '"likely_interface_class_id": '
            self.assertIn(marker, text, note_path)
            class_id = int(text.split(marker, 1)[1].split(",", 1)[0])
            self.assertTrue(note_path.parent.name.startswith(f"{class_id:03d}-"), note_path)

    def test_compiled_obsidian_covers_blue_book_part_2_current_interface_classes(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        actual = {
            int(entry.get("class_id")): entry
            for entry in payload["entries"]
            if entry.get("type") == "cosem_interface_class" and entry.get("class_id") is not None
        }

        missing: list[str] = []
        wrong_version: list[str] = []
        for class_id, version, name in BLUE_BOOK_PART2_CURRENT_CLASSES:
            entry = actual.get(class_id)
            if not entry:
                missing.append(f"{class_id} {name}")
                continue
            if str(entry.get("version", version)) != str(version):
                wrong_version.append(f"{class_id} {name}: expected v{version}, got {entry.get('version')}")

        self.assertEqual(missing, [])
        self.assertEqual(wrong_version, [])

    def test_compiled_obsidian_covers_blue_book_part_1_obis_table_catalogue(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        actual = {
            int(entry.get("table_no")): entry
            for entry in payload["entries"]
            if entry.get("type") == "obis_table" and entry.get("table_no") is not None
        }

        missing = []
        wrong_titles = []
        for table_no, title in BLUE_BOOK_PART1_OBIS_TABLES:
            entry = actual.get(table_no)
            if not entry:
                missing.append(f"Table {table_no}: {title}")
                continue
            if entry.get("name") != f"Table {table_no} - {title}":
                wrong_titles.append(f"Table {table_no}: {entry.get('name')}")

        self.assertEqual(missing, [])
        self.assertEqual(wrong_titles, [])

    def test_compiled_obsidian_matches_blue_book_part_1_obis_table_families(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "OBIS codes for gas data profile objects, water list objects, AC electricity tariff rates, "
            "DC electricity register table objects, and manufacturer specific value group ranges shall be interpreted."
        )
        matches = repo.match_text(text, limit=30)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-BLUE-BOOK-OBIS-TABLE-64", matched_ids)
        self.assertIn("KB-BLUE-BOOK-OBIS-TABLE-70", matched_ids)
        self.assertIn("KB-BLUE-BOOK-OBIS-TABLE-15", matched_ids)
        self.assertIn("KB-BLUE-BOOK-OBIS-TABLE-33", matched_ids)
        self.assertIn("KB-BLUE-BOOK-OBIS-TABLE-2", matched_ids)

    def test_high_value_cosem_classes_include_blue_book_operational_semantics(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in payload["entries"]}

        data = by_id["KB-L3-IC-1-DATA"]
        data_attrs = {attr["name"]: attr for attr in data["attributes"]}
        self.assertEqual(data_attrs["value"]["type"], "CHOICE")
        self.assertEqual(data_attrs["logical_name"]["storage"], "static")

        register = by_id["KB-L3-IC-3-REGISTER"]
        register_attrs = {attr["name"]: attr for attr in register["attributes"]}
        self.assertEqual(register_attrs["logical_name"]["storage"], "static")
        self.assertEqual(register_attrs["scaler_unit"]["storage"], "static")
        self.assertEqual(register_attrs["value"]["type"], "CHOICE")
        self.assertEqual(register["methods"][0]["parameter_type"], "integer(0)")

        register_table = by_id["KB-L3-IC-61-REGISTER-TABLE"]
        register_table_methods = {method["name"] for method in register_table["methods"]}
        self.assertEqual(register_table_methods, {"reset", "capture"})
        self.assertTrue(any("table_cell_definition" in item for item in register_table.get("behavior_notes", [])))

        security_setup = by_id["KB-L3-IC-64-SECURITY-SETUP"]
        security_methods = {method["name"] for method in security_setup["methods"]}
        self.assertIn("key_transfer", security_methods)
        self.assertNotIn("global_key_transfer", security_methods)
        self.assertTrue(any("client and server" in item for item in security_setup.get("access_semantics", [])))

    def test_runtime_matching_uses_blue_book_operational_terms(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The implementation shall populate the Compact data compact_buffer with the first capture object "
            "set to template_id. The Register table table_cell_definition shall use group_E_values. "
            "The Security setup object shall support key_transfer for symmetric keys."
        )
        matches = repo.match_text(text, limit=20)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-L3-IC-62-COMPACT-DATA", matched_ids)
        self.assertIn("KB-L3-IC-61-REGISTER-TABLE", matched_ids)
        self.assertIn("KB-L3-IC-64-SECURITY-SETUP", matched_ids)

    def test_high_value_cosem_classes_are_traceable_and_actionable(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        required_ids = [
            "KB-L3-IC-1-DATA",
            "KB-L3-IC-3-REGISTER",
            "KB-L3-IC-4-EXTENDED-REGISTER",
            "KB-L3-IC-5-DEMAND-REGISTER",
            "KB-L3-IC-7-PROFILE-GENERIC",
            "KB-L3-IC-15-ASSOCIATION-LN",
            "KB-L3-IC-18-IMAGE-TRANSFER",
            "KB-L3-IC-40-PUSH-SETUP",
            "KB-L3-IC-48-IPV6-SETUP",
            "KB-L3-IC-61-REGISTER-TABLE",
            "KB-L3-IC-62-COMPACT-DATA",
            "KB-L3-IC-64-SECURITY-SETUP",
            "KB-L3-IC-70-DISCONNECT-CONTROL",
            "KB-L3-IC-71-LIMITER",
        ]
        by_id = {entry["id"]: entry for entry in payload["entries"]}
        missing_source_refs = []
        missing_operational_semantics = []
        for entry_id in required_ids:
            entry = by_id[entry_id]
            if not entry.get("source_refs"):
                missing_source_refs.append(entry_id)
            if not any(entry.get(key) for key in ["behavior_notes", "access_semantics", "state_model", "common_instances"]):
                missing_operational_semantics.append(entry_id)

        self.assertEqual(missing_source_refs, [])
        self.assertEqual(missing_operational_semantics, [])

    def test_high_value_cosem_class_details_track_blue_book_tables(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in payload["entries"]}

        demand_methods = {method["name"] for method in by_id["KB-L3-IC-5-DEMAND-REGISTER"]["methods"]}
        self.assertEqual(demand_methods, {"reset", "next_period"})

        association_ln = by_id["KB-L3-IC-15-ASSOCIATION-LN"]
        association_attrs = {attr["name"] for attr in association_ln["attributes"]}
        association_methods = {method["name"] for method in association_ln["methods"]}
        self.assertIn("user_list", association_attrs)
        self.assertIn("current_user", association_attrs)
        self.assertIn("add_user", association_methods)
        self.assertIn("remove_user", association_methods)

        push_setup = by_id["KB-L3-IC-40-PUSH-SETUP"]
        push_attrs = {attr["name"] for attr in push_setup["attributes"]}
        push_methods = {method["name"] for method in push_setup["methods"]}
        self.assertEqual(len(push_attrs), 13)
        self.assertIn("push_protection_parameters", push_attrs)
        self.assertIn("last_confirmation_date_time", push_attrs)
        self.assertEqual(push_methods, {"push", "reset"})

        compact_data_attrs = {attr["name"] for attr in by_id["KB-L3-IC-62-COMPACT-DATA"]["attributes"]}
        self.assertIn("compact_buffer", compact_data_attrs)
        self.assertNotIn("buffer", compact_data_attrs)

        disconnect = by_id["KB-L3-IC-70-DISCONNECT-CONTROL"]
        states = {state["name"] for state in disconnect["state_model"]["states"]}
        self.assertEqual(states, {"Disconnected", "Connected", "Ready_for_reconnection"})

    def test_compiled_obsidian_materializes_representative_obis_object_instances(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in payload["entries"]}

        expected = {
            "KB-OBIS-0-0-41-0-0-255-SAP-ASSIGNMENT": ("0-0:41.0.0.255", "SAP Assignment", 17, "general", 8),
            "KB-OBIS-0-0-40-0-0-255-ASSOCIATION-LN-CURRENT": ("0-0:40.0.0.255", "Association LN - current membership", 15, "general", 8),
            "KB-OBIS-0-0-40-0-1-255-ASSOCIATION-LN-PUBLIC-CLIENT": ("0-0:40.0.1.255", "Association LN - public client association", 15, "general", 8),
            "KB-OBIS-0-0-40-0-2-255-ASSOCIATION-LN-READING-CLIENT": ("0-0:40.0.2.255", "Association LN - reading client association", 15, "general", 8),
            "KB-OBIS-0-0-40-0-3-255-ASSOCIATION-LN-LOCAL-CLIENT": ("0-0:40.0.3.255", "Association LN - local client association", 15, "general", 8),
            "KB-OBIS-0-0-40-0-5-255-ASSOCIATION-LN-REMOTE-CLIENT": ("0-0:40.0.5.255", "Association LN - remote client association", 15, "general", 8),
            "KB-OBIS-0-0-43-0-5-255-SECURITY-SETUP-REMOTE-CLIENT": ("0-0:43.0.5.255", "Security Setup - remote client association", 64, "general", 8),
            "KB-OBIS-0-0-43-0-3-255-SECURITY-SETUP-LOCAL-CLIENT": ("0-0:43.0.3.255", "Security Setup - local client association", 64, "general", 8),
            "KB-OBIS-0-0-13-0-0-255-ACTIVITY-CALENDAR": ("0-0:13.0.0.255", "Activity Calendar", 20, "general", 8),
            "KB-OBIS-0-0-14-0-0-255-REGISTER-ACTIVATION": ("0-0:14.0.0.255", "Register activation", 6, "general", 8),
            "KB-OBIS-0-0-99-98-11-255-CORRECT-SECURITY-OPERATIONS-EVENT-LOG": ("0-0:99.98.11.255", "Correct security operations event log", 7, "general", 12),
            "KB-OBIS-0-0-99-98-12-255-FAILED-SECURITY-OPERATIONS-EVENT-LOG": ("0-0:99.98.12.255", "Failed security operations event log", 7, "general", 12),
            "KB-OBIS-0-0-96-11-11-255-EVENT-OBJECT-CORRECT-SECURITY-OPERATIONS": ("0-0:96.11.11.255", "Event Object - Correct security operations event log", 1, "general", 9),
            "KB-OBIS-0-0-96-11-12-255-EVENT-OBJECT-FAILED-SECURITY-OPERATIONS": ("0-0:96.11.12.255", "Event Object - Failed security operations event log", 1, "general", 9),
            "KB-OBIS-0-1-94-55-116-255-CORRECT-SECURITY-OPERATIONS-EVENT-LOG-FILTER": ("0-1:94.55.116.255", "Correct security operations event log filter", 1, "general", 9),
            "KB-OBIS-0-1-94-55-117-255-FAILED-SECURITY-OPERATIONS-EVENT-LOG-FILTER": ("0-1:94.55.117.255", "Failed security operations event log filter", 1, "general", 9),
            "KB-OBIS-0-0-99-98-4-255-FIRMWARE-EVENT-LOG": ("0-0:99.98.4.255", "Firmware Event Log", 7, "general", 12),
            "KB-OBIS-0-0-96-11-4-255-EVENT-OBJECT-FIRMWARE-EVENT-LOG": ("0-0:96.11.4.255", "Event Object - Firmware Event Log", 1, "general", 9),
            "KB-OBIS-0-1-94-55-112-255-FIRMWARE-EVENT-LOG-FILTER": ("0-1:94.55.112.255", "Firmware Event Log Filter", 1, "general", 9),
            "KB-OBIS-0-0-99-98-0-255-STANDARD-EVENT-LOG": ("0-0:99.98.0.255", "Standard Event Log", 7, "general", 12),
            "KB-OBIS-0-0-96-11-0-255-EVENT-OBJECT-STANDARD-EVENT-LOG": ("0-0:96.11.0.255", "Event Object - Standard Event Log", 1, "general", 9),
            "KB-OBIS-0-1-94-55-105-255-STANDARD-EVENT-LOG-FILTER": ("0-1:94.55.105.255", "Standard Event Log Filter", 1, "general", 9),
            "KB-OBIS-0-0-99-98-7-255-COMMON-EVENT-LOG": ("0-0:99.98.7.255", "Common Event Log", 7, "general", 12),
            "KB-OBIS-0-0-96-11-7-255-EVENT-OBJECT-COMMON-EVENT-LOG": ("0-0:96.11.7.255", "Event Object - Common Event Log", 1, "general", 9),
            "KB-OBIS-0-1-94-55-110-255-COMMON-EVENT-LOG-FILTER": ("0-1:94.55.110.255", "Common Event Log Filter", 1, "general", 9),
            "KB-OBIS-0-0-99-98-8-255-SYNCHRONIZATION-EVENT-LOG": ("0-0:99.98.8.255", "Synchronization Event Log", 7, "general", 12),
            "KB-OBIS-0-0-96-11-8-255-EVENT-OBJECT-SYNCHRONIZATION-EVENT-LOG": ("0-0:96.11.8.255", "Event Object - Synchronization Event Log", 1, "general", 9),
            "KB-OBIS-0-1-94-55-113-255-SYNCHRONIZATION-EVENT-LOG-FILTER": ("0-1:94.55.113.255", "Synchronization Event Log Filter", 1, "general", 9),
            "KB-OBIS-0-0-99-98-1-255-FRAUD-DETECTION-LOG": ("0-0:99.98.1.255", "Fraud Detection Log", 7, "general", 12),
            "KB-OBIS-0-0-96-11-1-255-EVENT-OBJECT-FRAUD-DETECTION-LOG": ("0-0:96.11.1.255", "Event Object - Fraud Detection Log", 1, "general", 9),
            "KB-OBIS-0-1-94-55-106-255-FRAUD-DETECTION-LOG-FILTER": ("0-1:94.55.106.255", "Fraud Detection Log Filter", 1, "general", 9),
            "KB-OBIS-0-0-99-98-2-255-DISCONNECT-CONTROL-LOG": ("0-0:99.98.2.255", "Disconnect Control log", 7, "general", 12),
            "KB-OBIS-0-0-96-11-2-255-EVENT-OBJECT-DISCONNECT-CONTROL-LOG": ("0-0:96.11.2.255", "Event Object - Disconnect Control log", 1, "general", 9),
            "KB-OBIS-0-1-94-55-114-255-DISCONNECT-CONTROL-LOG-FILTER": ("0-1:94.55.114.255", "Disconnect Control log Filter", 1, "general", 9),
            "KB-OBIS-0-0-99-98-5-255-POWER-QUALITY-EVENT-LOG": ("0-0:99.98.5.255", "Power Quality Event Log", 7, "general", 12),
            "KB-OBIS-0-0-96-11-5-255-EVENT-OBJECT-POWER-QUALITY-LOG": ("0-0:96.11.5.255", "Event Object - Power Quality Log", 1, "general", 9),
            "KB-OBIS-0-1-94-55-107-255-POWER-QUALITY-NON-FINISHED-EVENT-LOG-FILTER": ("0-1:94.55.107.255", "Power Quality Non-finished Event Log Filter", 1, "general", 9),
            "KB-OBIS-0-1-94-55-108-255-POWER-QUALITY-FINISHED-EVENT-LOG-FILTER": ("0-1:94.55.108.255", "Power Quality finished Event Log Filter", 1, "general", 9),
            "KB-OBIS-1-0-1-8-0-255-ACTIVE-ENERGY-IMPORT": ("1-0:1.8.0.255", "Active energy import total", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-2-8-0-255-ACTIVE-ENERGY-EXPORT": ("1-0:2.8.0.255", "Active energy export total", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-32-7-0-255-L1-VOLTAGE-INSTANTANEOUS": ("1-0:32.7.0.255", "L1 voltage instantaneous", 3, "ac_electricity", 13),
            "KB-OBIS-2-0-12-7-0-255-DC-VOLTAGE-INSTANTANEOUS": ("2-0:12.7.0.255", "DC voltage instantaneous", 3, "dc_electricity", 26),
            "KB-OBIS-0-B-99-98-E-ABSTRACT-EVENT-LOG": ("0-b:99.98.e", "Abstract event log profile", 7, "general", 12),
            "KB-OBIS-1-B-99-1-E-AC-LOAD-PROFILE-1": ("1-b:99.1.e", "AC load profile recording period 1", 7, "ac_electricity", 24),
            "KB-OBIS-1-B-98-10-E-AC-REGISTER-TABLE-GENERAL": ("1-b:98.10.e", "AC general register table", 61, "ac_electricity", 25),
            "KB-OBIS-2-B-98-1-E-255-DC-BILLING-LIST-1": ("2-b:98.1.e.255", "DC billing period list 1", 1, "dc_electricity", 31),
            "KB-OBIS-2-B-99-98-E-DC-EVENT-LOG": ("2-b:99.98.e", "DC event log profile", 7, "dc_electricity", 32),
            "KB-OBIS-2-B-98-10-E-DC-REGISTER-TABLE-GENERAL": ("2-b:98.10.e", "DC general register table", 61, "dc_electricity", 33),
            "KB-OBIS-0-B-98-1-E-255-ABSTRACT-BILLING-LIST-1": ("0-b:98.1.e.255", "Abstract billing period list 1", 1, "general", 10),
            "KB-OBIS-0-B-98-10-E-ABSTRACT-REGISTER-TABLE-GENERAL": ("0-b:98.10.e", "Abstract general register table", 61, "general", 11),
            "KB-OBIS-1-B-97-97-E-AC-ERROR-REGISTER": ("1-b:97.97.e", "AC error register", 3, "ac_electricity", 22),
            "KB-OBIS-1-B-98-1-E-255-AC-BILLING-LIST-1": ("1-b:98.1.e.255", "AC billing period list 1", 1, "ac_electricity", 23),
            "KB-OBIS-1-B-0-8-4-VZ-AC-RECORDING-INTERVAL-1": ("1-b:0.8.4.VZ", "AC recording interval 1", 3, "ac_electricity", 21),
            "KB-OBIS-2-0-11-7-0-255-DC-CURRENT-INSTANTANEOUS": ("2-0:11.7.0.255", "DC current instantaneous", 3, "dc_electricity", 26),
            "KB-OBIS-2-0-1-8-0-255-DC-POWER-IMPORT-INTEGRAL": ("2-0:1.8.0.255", "DC power plus time integral 1 total", 3, "dc_electricity", 26),
            "KB-OBIS-2-B-97-97-E-DC-ERROR-REGISTER": ("2-b:97.97.e", "DC error register", 3, "dc_electricity", 30),
            "KB-OBIS-2-B-0-8-4-VZ-DC-RECORDING-INTERVAL-1": ("2-b:0.8.4.VZ", "DC recording interval 1", 3, "dc_electricity", 29),
            "KB-OBIS-0-B-0-9-1-LOCAL-TIME": ("0-b:0.9.1", "Local time", 1, "general", 8),
            "KB-OBIS-0-B-96-1-0-DEVICE-ID-1": ("0-b:96.1.0", "Device ID 1", 1, "general", 8),
            "KB-OBIS-1-0-3-8-0-255-REACTIVE-ENERGY-IMPORT": ("1-0:3.8.0.255", "Reactive energy import total", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-4-8-0-255-REACTIVE-ENERGY-EXPORT": ("1-0:4.8.0.255", "Reactive energy export total", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-9-8-0-255-APPARENT-ENERGY-IMPORT": ("1-0:9.8.0.255", "Apparent energy import total", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-10-8-0-255-APPARENT-ENERGY-EXPORT": ("1-0:10.8.0.255", "Apparent energy export total", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-11-7-0-255-CURRENT-INSTANTANEOUS": ("1-0:11.7.0.255", "Current any phase instantaneous", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-14-7-0-255-SUPPLY-FREQUENCY": ("1-0:14.7.0.255", "Supply frequency instantaneous", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-1-7-0-255-INSTANTANEOUS-ACTIVE-IMPORT-POWER": ("1-0:1.7.0.255", "Instantaneous active import power (+P)", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-3-7-0-255-INSTANTANEOUS-REACTIVE-IMPORT-POWER": ("1-0:3.7.0.255", "Instantaneous reactive import power (+Q)", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-4-7-0-255-INSTANTANEOUS-REACTIVE-EXPORT-POWER": ("1-0:4.7.0.255", "Instantaneous reactive export power (-Q)", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-9-7-0-255-INSTANTANEOUS-APPARENT-IMPORT-POWER": ("1-0:9.7.0.255", "Instantaneous apparent import power (+S)", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-10-7-0-255-INSTANTANEOUS-APPARENT-EXPORT-POWER": ("1-0:10.7.0.255", "Instantaneous apparent export power (-S)", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-12-7-0-255-VOLTAGE-ANY-PHASE-INSTANTANEOUS": ("1-0:12.7.0.255", "Voltage any phase instantaneous", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-31-7-0-255-L1-CURRENT-INSTANTANEOUS": ("1-0:31.7.0.255", "L1 current instantaneous", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-51-7-0-255-L2-CURRENT-INSTANTANEOUS": ("1-0:51.7.0.255", "L2 current instantaneous", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-71-7-0-255-L3-CURRENT-INSTANTANEOUS": ("1-0:71.7.0.255", "L3 current instantaneous", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-52-7-0-255-L2-VOLTAGE-INSTANTANEOUS": ("1-0:52.7.0.255", "L2 voltage instantaneous", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-72-7-0-255-L3-VOLTAGE-INSTANTANEOUS": ("1-0:72.7.0.255", "L3 voltage instantaneous", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-13-7-0-255-POWER-FACTOR-INSTANTANEOUS": ("1-0:13.7.0.255", "Power factor instantaneous", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-1-9-0-255-INCREMENTAL-ACTIVE-ENERGY-IMPORT": ("1-0:1.9.0.255", "Incremental active energy import (+A) - Total", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-1-24-0-255-AVERAGE-ACTIVE-IMPORT-POWER-CURRENT": ("1-0:1.24.0.255", "Average active import power (+A) - Current", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-1-25-0-255-AVERAGE-ACTIVE-IMPORT-POWER-LAST": ("1-0:1.25.0.255", "Average active import power (+A) - Last", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-2-7-0-255-INSTANTANEOUS-ACTIVE-EXPORT-POWER": ("1-0:2.7.0.255", "Instantaneous active export power (-P)", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-2-9-0-255-INCREMENTAL-ACTIVE-ENERGY-EXPORT": ("1-0:2.9.0.255", "Incremental active energy export (-A) - Total", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-2-24-0-255-AVERAGE-ACTIVE-EXPORT-POWER-CURRENT": ("1-0:2.24.0.255", "Average active export power (-A) - Current", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-2-25-0-255-AVERAGE-ACTIVE-EXPORT-POWER-LAST": ("1-0:2.25.0.255", "Average active export power (-A) - Last", 3, "ac_electricity", 13),
            "KB-OBIS-2-0-2-8-0-255-DC-POWER-EXPORT-INTEGRAL": ("2-0:2.8.0.255", "DC power minus time integral 1 total", 3, "dc_electricity", 26),
            "KB-OBIS-2-0-92-7-0-255-DC-VOLTAGE-LOW-TO-GROUND": ("2-0:92.7.0.255", "DC voltage low to ground instantaneous", 3, "dc_electricity", 26),
        }

        missing = [entry_id for entry_id in expected if entry_id not in by_id]
        self.assertEqual(missing, [])
        for entry_id, (obis, name, class_id, medium, table_no) in expected.items():
            entry = by_id[entry_id]
            self.assertEqual(entry["type"], "cosem_object_instance")
            self.assertEqual(entry["obis_pattern"], obis)
            self.assertEqual(entry["name"], name)
            self.assertEqual(entry["likely_interface_class_id"], class_id)
            self.assertEqual(entry["medium"], medium)
            self.assertEqual(entry["blue_book_table_ref"]["table_no"], table_no)
            self.assertTrue(entry.get("value_group_mapping"))
            self.assertTrue(entry.get("applicable_notes"))

    def test_runtime_matching_finds_specific_obis_rows_without_generic_noise(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The profile shall expose Active energy import total at OBIS 1-0:1.8.0.255, "
            "the SAP Assignment at 0-0:41.0.0.255, and the Activity Calendar at 0-0:13.0.0.255."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=20)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-1-0-1-8-0-255-ACTIVE-ENERGY-IMPORT", matched_ids)
        self.assertIn("KB-OBIS-0-0-41-0-0-255-SAP-ASSIGNMENT", matched_ids)
        self.assertIn("KB-OBIS-0-0-13-0-0-255-ACTIVITY-CALENDAR", matched_ids)

        noisy_matches = repo.match_text(
            "The blue book interface class object shall be supported.",
            entry_type="cosem_object_instance",
            limit=20,
        )
        self.assertEqual(noisy_matches, [])

    def test_runtime_matching_finds_association_ln_client_rows(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The logical device shall expose the public client association at OBIS 0-0:40.0.1.255, "
            "the reading client association at OBIS 0-0:40.0.2.255, the local client association "
            "at OBIS 0-0:40.0.3.255, and the remote client association at OBIS 0-0:40.0.5.255."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=20)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-0-0-40-0-1-255-ASSOCIATION-LN-PUBLIC-CLIENT", matched_ids)
        self.assertIn("KB-OBIS-0-0-40-0-2-255-ASSOCIATION-LN-READING-CLIENT", matched_ids)
        self.assertIn("KB-OBIS-0-0-40-0-3-255-ASSOCIATION-LN-LOCAL-CLIENT", matched_ids)
        self.assertIn("KB-OBIS-0-0-40-0-5-255-ASSOCIATION-LN-REMOTE-CLIENT", matched_ids)

    def test_runtime_matching_finds_security_setup_client_rows(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The remote client Security Setup object shall use OBIS 0-0:43.0.5.255, and the "
            "local client Security Setup object shall use OBIS 0-0:43.0.3.255 for key management."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=20)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-0-0-43-0-5-255-SECURITY-SETUP-REMOTE-CLIENT", matched_ids)
        self.assertIn("KB-OBIS-0-0-43-0-3-255-SECURITY-SETUP-LOCAL-CLIENT", matched_ids)

    def test_runtime_matching_finds_security_operations_event_logs(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The meter shall keep the correct security operations event log at OBIS 0-0:99.98.11.255 "
            "and the failed security operations event log at OBIS 0-0:99.98.12.255."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=20)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-0-0-99-98-11-255-CORRECT-SECURITY-OPERATIONS-EVENT-LOG", matched_ids)
        self.assertIn("KB-OBIS-0-0-99-98-12-255-FAILED-SECURITY-OPERATIONS-EVENT-LOG", matched_ids)

    def test_runtime_matching_finds_security_event_objects_and_filters(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The correct security operations event object shall be exposed at OBIS 0-0:96.11.11.255 "
            "and filtered by 0-1:94.55.116.255. The failed security operations event object shall "
            "be exposed at OBIS 0-0:96.11.12.255 and filtered by 0-1:94.55.117.255."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=20)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-0-0-96-11-11-255-EVENT-OBJECT-CORRECT-SECURITY-OPERATIONS", matched_ids)
        self.assertIn("KB-OBIS-0-0-96-11-12-255-EVENT-OBJECT-FAILED-SECURITY-OPERATIONS", matched_ids)
        self.assertIn("KB-OBIS-0-1-94-55-116-255-CORRECT-SECURITY-OPERATIONS-EVENT-LOG-FILTER", matched_ids)
        self.assertIn("KB-OBIS-0-1-94-55-117-255-FAILED-SECURITY-OPERATIONS-EVENT-LOG-FILTER", matched_ids)

    def test_runtime_matching_finds_firmware_event_log_rows(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The firmware event log shall be exposed at OBIS 0-0:99.98.4.255, capture the "
            "firmware event object at OBIS 0-0:96.11.4.255, and use the firmware event log "
            "filter at OBIS 0-1:94.55.112.255."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=20)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-0-0-99-98-4-255-FIRMWARE-EVENT-LOG", matched_ids)
        self.assertIn("KB-OBIS-0-0-96-11-4-255-EVENT-OBJECT-FIRMWARE-EVENT-LOG", matched_ids)
        self.assertIn("KB-OBIS-0-1-94-55-112-255-FIRMWARE-EVENT-LOG-FILTER", matched_ids)

    def test_runtime_matching_finds_standard_common_and_synchronization_event_logs(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The standard event log at OBIS 0-0:99.98.0.255 shall capture event object "
            "0-0:96.11.0.255 and use filter 0-1:94.55.105.255. The common event log at "
            "0-0:99.98.7.255 shall capture event object 0-0:96.11.7.255 and use filter "
            "0-1:94.55.110.255. The synchronization event log at 0-0:99.98.8.255 shall "
            "capture event object 0-0:96.11.8.255 and use filter 0-1:94.55.113.255."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=30)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-0-0-99-98-0-255-STANDARD-EVENT-LOG", matched_ids)
        self.assertIn("KB-OBIS-0-0-96-11-0-255-EVENT-OBJECT-STANDARD-EVENT-LOG", matched_ids)
        self.assertIn("KB-OBIS-0-1-94-55-105-255-STANDARD-EVENT-LOG-FILTER", matched_ids)
        self.assertIn("KB-OBIS-0-0-99-98-7-255-COMMON-EVENT-LOG", matched_ids)
        self.assertIn("KB-OBIS-0-0-96-11-7-255-EVENT-OBJECT-COMMON-EVENT-LOG", matched_ids)
        self.assertIn("KB-OBIS-0-1-94-55-110-255-COMMON-EVENT-LOG-FILTER", matched_ids)
        self.assertIn("KB-OBIS-0-0-99-98-8-255-SYNCHRONIZATION-EVENT-LOG", matched_ids)
        self.assertIn("KB-OBIS-0-0-96-11-8-255-EVENT-OBJECT-SYNCHRONIZATION-EVENT-LOG", matched_ids)
        self.assertIn("KB-OBIS-0-1-94-55-113-255-SYNCHRONIZATION-EVENT-LOG-FILTER", matched_ids)

    def test_runtime_matching_finds_fraud_and_disconnect_event_logs(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The fraud detection log at OBIS 0-0:99.98.1.255 shall capture event object "
            "0-0:96.11.1.255 and use filter 0-1:94.55.106.255. The disconnect control log "
            "at 0-0:99.98.2.255 shall capture event object 0-0:96.11.2.255 and use filter "
            "0-1:94.55.114.255."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=30)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-0-0-99-98-1-255-FRAUD-DETECTION-LOG", matched_ids)
        self.assertIn("KB-OBIS-0-0-96-11-1-255-EVENT-OBJECT-FRAUD-DETECTION-LOG", matched_ids)
        self.assertIn("KB-OBIS-0-1-94-55-106-255-FRAUD-DETECTION-LOG-FILTER", matched_ids)
        self.assertIn("KB-OBIS-0-0-99-98-2-255-DISCONNECT-CONTROL-LOG", matched_ids)
        self.assertIn("KB-OBIS-0-0-96-11-2-255-EVENT-OBJECT-DISCONNECT-CONTROL-LOG", matched_ids)
        self.assertIn("KB-OBIS-0-1-94-55-114-255-DISCONNECT-CONTROL-LOG-FILTER", matched_ids)

    def test_runtime_matching_finds_power_quality_event_log_rows(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The power quality event log at OBIS 0-0:99.98.5.255 shall capture power quality "
            "event object 0-0:96.11.5.255 and apply non-finished filter 0-1:94.55.107.255 "
            "and finished filter 0-1:94.55.108.255."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=30)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-0-0-99-98-5-255-POWER-QUALITY-EVENT-LOG", matched_ids)
        self.assertIn("KB-OBIS-0-0-96-11-5-255-EVENT-OBJECT-POWER-QUALITY-LOG", matched_ids)
        self.assertIn("KB-OBIS-0-1-94-55-107-255-POWER-QUALITY-NON-FINISHED-EVENT-LOG-FILTER", matched_ids)
        self.assertIn("KB-OBIS-0-1-94-55-108-255-POWER-QUALITY-FINISHED-EVENT-LOG-FILTER", matched_ids)

    def test_runtime_matching_finds_ac_power_and_average_rows(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The meter shall expose instantaneous active import power at OBIS 1-0:1.7.0.255, "
            "incremental active energy export at OBIS 1-0:2.9.0.255, and last average active "
            "export power at OBIS 1-0:2.25.0.255."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=20)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-1-0-1-7-0-255-INSTANTANEOUS-ACTIVE-IMPORT-POWER", matched_ids)
        self.assertIn("KB-OBIS-1-0-2-9-0-255-INCREMENTAL-ACTIVE-ENERGY-EXPORT", matched_ids)
        self.assertIn("KB-OBIS-1-0-2-25-0-255-AVERAGE-ACTIVE-EXPORT-POWER-LAST", matched_ids)

    def test_runtime_matching_finds_ac_phase_and_power_quality_rows(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The meter shall expose L2 voltage at OBIS 1-0:52.7.0.255, L3 current at "
            "OBIS 1-0:71.7.0.255, reactive energy export at OBIS 1-0:4.8.0.255, "
            "and power factor at OBIS 1-0:13.7.0.255."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=20)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-1-0-52-7-0-255-L2-VOLTAGE-INSTANTANEOUS", matched_ids)
        self.assertIn("KB-OBIS-1-0-71-7-0-255-L3-CURRENT-INSTANTANEOUS", matched_ids)
        self.assertIn("KB-OBIS-1-0-4-8-0-255-REACTIVE-ENERGY-EXPORT", matched_ids)
        self.assertIn("KB-OBIS-1-0-13-7-0-255-POWER-FACTOR-INSTANTANEOUS", matched_ids)

    def test_compiled_obsidian_materializes_abnt_instant_current_rows(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in payload["entries"]}

        expected = {
            "KB-OBIS-1-0-90-7-0-255-INSTANT-CURRENT-TOTAL": (
                "1-0:90.7.0.255",
                "Instant current (sum over all phases)",
                "90 current sum over all phases",
                "ABNT Appendix 9 extracted table TBL-000112",
            ),
            "KB-OBIS-1-0-91-7-0-255-INSTANTANEOUS-NEUTRAL-CURRENT-MEASURED": (
                "1-0:91.7.0.255",
                "Instantaneous neutral current (measured)",
                "91 neutral current",
                "ABNT Appendix 9 extracted table TBL-000112",
            ),
            "KB-OBIS-1-1-91-7-0-255-INSTANTANEOUS-NEUTRAL-CURRENT-CALCULATED": (
                "1-1:91.7.0.255",
                "Instantaneous neutral current (calculated)",
                "91 neutral current",
                "ABNT Appendix 9 extracted table TBL-000112",
            ),
        }

        missing = [entry_id for entry_id in expected if entry_id not in by_id]
        self.assertEqual(missing, [])
        for entry_id, (obis, name, c_mapping, source_ref) in expected.items():
            entry = by_id[entry_id]
            self.assertEqual(entry["type"], "cosem_object_instance")
            self.assertEqual(entry["obis_pattern"], obis)
            self.assertEqual(entry["name"], name)
            self.assertEqual(entry["likely_interface_class_id"], 3)
            self.assertEqual(entry["medium"], "ac_electricity")
            self.assertEqual(entry["blue_book_table_ref"]["table_no"], 13)
            self.assertEqual(entry["value_group_mapping"]["C"], c_mapping)
            self.assertEqual(entry["value_group_mapping"]["D"], "7 instantaneous value")
            self.assertTrue(entry.get("applicable_notes"))
            self.assertIn(source_ref, json.dumps(entry.get("source_refs", []), ensure_ascii=False))

    def test_runtime_matching_finds_abnt_instant_current_rows(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The meter shall expose Instant current (sum over all phases) at OBIS 1-0:90.7.0.255, "
            "Instantaneous neutral current (measured) at OBIS 1-0:91.7.0.255, and "
            "Instantaneous neutral current (calculated) at OBIS 1-1:91.7.0.255."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=20)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-1-0-90-7-0-255-INSTANT-CURRENT-TOTAL", matched_ids)
        self.assertIn("KB-OBIS-1-0-91-7-0-255-INSTANTANEOUS-NEUTRAL-CURRENT-MEASURED", matched_ids)
        self.assertIn("KB-OBIS-1-1-91-7-0-255-INSTANTANEOUS-NEUTRAL-CURRENT-CALCULATED", matched_ids)

    def test_compiled_obsidian_has_exact_obis_for_current_abnt_object_model(self) -> None:
        model_path = ROOT / "out" / "abnt_current_kb_smoke" / "cosem_object_model.json"
        if not model_path.exists():
            self.skipTest("ABNT object-model smoke output is not present")

        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        model = json.loads(model_path.read_text(encoding="utf-8"))
        kb_obis = {
            str(entry.get("obis_pattern") or "").strip()
            for entry in payload["entries"]
            if entry.get("type") == "cosem_object_instance"
        }

        missing = []
        for obj in model.get("objects", []):
            obis = str(obj.get("obis") or "").strip()
            if obis and obis not in kb_obis:
                missing.append(
                    {
                        "obis": obis,
                        "class_id": obj.get("class_id"),
                        "object": obj.get("object"),
                        "source_item_id": obj.get("source_item_id"),
                        "source_table_ids": obj.get("source_table_ids"),
                    }
                )

        self.assertEqual(missing, [])

    def test_compiled_obsidian_materializes_hca_and_thermal_obis_rows(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in payload["entries"]}

        expected = {
            "KB-OBIS-4-B-98-1-E-255-HCA-BILLING-LIST-1": ("4-b:98.1.e.255", "HCA billing period list 1", 1, "hca", 39),
            "KB-OBIS-6-0-1-8-0-255-THERMAL-ENERGY-TOTAL": ("6-0:1.8.0.255", "Thermal energy total", 3, "thermal_energy", 42),
            "KB-OBIS-6-0-3-7-0-255-VOLUME-FLOW-INSTANTANEOUS": ("6-0:3.7.0.255", "Thermal volume flow instantaneous", 3, "thermal_energy", 42),
            "KB-OBIS-6-0-5-7-0-255-FLOW-TEMPERATURE": ("6-0:5.7.0.255", "Thermal flow temperature instantaneous", 3, "thermal_energy", 42),
        }

        missing = [entry_id for entry_id in expected if entry_id not in by_id]
        self.assertEqual(missing, [])
        for entry_id, (obis, name, class_id, medium, table_no) in expected.items():
            entry = by_id[entry_id]
            self.assertEqual(entry["type"], "cosem_object_instance")
            self.assertEqual(entry["obis_pattern"], obis)
            self.assertEqual(entry["name"], name)
            self.assertEqual(entry["likely_interface_class_id"], class_id)
            self.assertEqual(entry["medium"], medium)
            self.assertEqual(entry["blue_book_table_ref"]["table_no"], table_no)
            self.assertTrue(entry.get("value_group_mapping"))
            self.assertTrue(entry.get("applicable_notes"))

    def test_runtime_matching_finds_hca_and_thermal_obis_rows(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The device shall expose HCA billing period list 1 at OBIS 4-b:98.1.e.255, "
            "thermal energy total at OBIS 6-0:1.8.0.255, volume flow at OBIS 6-0:3.7.0.255, "
            "and flow temperature at OBIS 6-0:5.7.0.255."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=20)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-4-B-98-1-E-255-HCA-BILLING-LIST-1", matched_ids)
        self.assertIn("KB-OBIS-6-0-1-8-0-255-THERMAL-ENERGY-TOTAL", matched_ids)
        self.assertIn("KB-OBIS-6-0-3-7-0-255-VOLUME-FLOW-INSTANTANEOUS", matched_ids)
        self.assertIn("KB-OBIS-6-0-5-7-0-255-FLOW-TEMPERATURE", matched_ids)

    def test_compiled_obsidian_materializes_media_family_service_list_profile_rows(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in payload["entries"]}

        expected = {
            "KB-OBIS-4-B-0-8-4-VZ-HCA-RECORDING-INTERVAL-1": ("4-b:0.8.4.VZ", "HCA recording interval 1", 3, "hca", 37),
            "KB-OBIS-4-B-97-97-E-HCA-ERROR-REGISTER": ("4-b:97.97.e", "HCA error register", 3, "hca", 38),
            "KB-OBIS-4-B-99-1-E-HCA-PROFILE-1": ("4-b:99.1.e", "HCA profile recording period 1", 7, "hca", 40),
            "KB-OBIS-6-B-0-8-4-VZ-THERMAL-RECORDING-INTERVAL-1": ("6-b:0.8.4.VZ", "Thermal recording interval 1", 3, "thermal_energy", 45),
            "KB-OBIS-6-B-97-97-E-THERMAL-ERROR-REGISTER": ("6-b:97.97.e", "Thermal error register", 3, "thermal_energy", 46),
            "KB-OBIS-6-B-98-1-E-255-THERMAL-BILLING-LIST-1": ("6-b:98.1.e.255", "Thermal billing period list 1", 1, "thermal_energy", 47),
            "KB-OBIS-6-B-99-1-E-THERMAL-LOAD-PROFILE-1": ("6-b:99.1.e", "Thermal load profile recording period 1", 7, "thermal_energy", 48),
            "KB-OBIS-7-B-0-8-4-VZ-GAS-RECORDING-INTERVAL-1": ("7-b:0.8.4.VZ", "Gas recording interval 1", 3, "gas", 61),
            "KB-OBIS-7-B-97-97-E-GAS-ERROR-REGISTER": ("7-b:97.97.e", "Gas error register", 3, "gas", 62),
            "KB-OBIS-7-B-98-1-E-255-GAS-BILLING-LIST-1": ("7-b:98.1.e.255", "Gas billing period list 1", 1, "gas", 63),
            "KB-OBIS-7-B-99-1-E-GAS-LOAD-PROFILE-1": ("7-b:99.1.e", "Gas load profile recording period 1", 7, "gas", 64),
            "KB-OBIS-8-B-0-8-4-VZ-WATER-RECORDING-INTERVAL-1": ("8-b:0.8.4.VZ", "Water recording interval 1", 3, "water", 68),
            "KB-OBIS-8-B-97-97-E-WATER-ERROR-REGISTER": ("8-b:97.97.e", "Water error register", 3, "water", 69),
            "KB-OBIS-8-B-98-1-E-255-WATER-BILLING-LIST-1": ("8-b:98.1.e.255", "Water billing period list 1", 1, "water", 70),
            "KB-OBIS-8-B-99-1-E-WATER-LOAD-PROFILE-1": ("8-b:99.1.e", "Water load profile recording period 1", 7, "water", 71),
        }

        missing = [entry_id for entry_id in expected if entry_id not in by_id]
        self.assertEqual(missing, [])
        for entry_id, (obis, name, class_id, medium, table_no) in expected.items():
            entry = by_id[entry_id]
            self.assertEqual(entry["type"], "cosem_object_instance")
            self.assertEqual(entry["obis_pattern"], obis)
            self.assertEqual(entry["name"], name)
            self.assertEqual(entry["likely_interface_class_id"], class_id)
            self.assertEqual(entry["medium"], medium)
            self.assertEqual(entry["blue_book_table_ref"]["table_no"], table_no)
            self.assertTrue(entry.get("value_group_mapping"))
            self.assertTrue(entry.get("applicable_notes"))

    def test_runtime_matching_finds_media_family_service_list_profile_rows(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The HCA shall expose recording interval at OBIS 4-b:0.8.4.VZ, HCA error register "
            "at OBIS 4-b:97.97.e, and HCA profile at OBIS 4-b:99.1.e. The thermal meter shall "
            "expose thermal billing list at OBIS 6-b:98.1.e.255 and thermal load profile at "
            "OBIS 6-b:99.1.e. Gas shall expose gas billing list at OBIS 7-b:98.1.e.255 and "
            "water shall expose water load profile at OBIS 8-b:99.1.e."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=30)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-4-B-0-8-4-VZ-HCA-RECORDING-INTERVAL-1", matched_ids)
        self.assertIn("KB-OBIS-4-B-97-97-E-HCA-ERROR-REGISTER", matched_ids)
        self.assertIn("KB-OBIS-4-B-99-1-E-HCA-PROFILE-1", matched_ids)
        self.assertIn("KB-OBIS-6-B-98-1-E-255-THERMAL-BILLING-LIST-1", matched_ids)
        self.assertIn("KB-OBIS-6-B-99-1-E-THERMAL-LOAD-PROFILE-1", matched_ids)
        self.assertIn("KB-OBIS-7-B-98-1-E-255-GAS-BILLING-LIST-1", matched_ids)
        self.assertIn("KB-OBIS-8-B-99-1-E-WATER-LOAD-PROFILE-1", matched_ids)

    def test_compiled_obsidian_materializes_gas_and_water_obis_rows(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in payload["entries"]}

        expected = {
            "KB-OBIS-7-0-1-8-0-255-GAS-VOLUME-TOTAL": ("7-0:1.8.0.255", "Gas volume total", 3, "gas", 51),
            "KB-OBIS-7-0-3-7-0-255-GAS-FLOW-RATE": ("7-0:3.7.0.255", "Gas flow rate instantaneous", 3, "gas", 51),
            "KB-OBIS-8-0-1-8-0-255-WATER-VOLUME-TOTAL": ("8-0:1.8.0.255", "Cold water volume total", 3, "water", 65),
            "KB-OBIS-8-0-3-7-0-255-WATER-FLOW-RATE": ("8-0:3.7.0.255", "Cold water flow rate instantaneous", 3, "water", 65),
        }

        missing = [entry_id for entry_id in expected if entry_id not in by_id]
        self.assertEqual(missing, [])
        for entry_id, (obis, name, class_id, medium, table_no) in expected.items():
            entry = by_id[entry_id]
            self.assertEqual(entry["type"], "cosem_object_instance")
            self.assertEqual(entry["obis_pattern"], obis)
            self.assertEqual(entry["name"], name)
            self.assertEqual(entry["likely_interface_class_id"], class_id)
            self.assertEqual(entry["medium"], medium)
            self.assertEqual(entry["blue_book_table_ref"]["table_no"], table_no)
            self.assertTrue(entry.get("value_group_mapping"))
            self.assertTrue(entry.get("applicable_notes"))

    def test_runtime_matching_finds_gas_and_water_obis_rows(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The gas meter shall expose gas volume total at OBIS 7-0:1.8.0.255 and gas flow rate at "
            "OBIS 7-0:3.7.0.255. The water meter shall expose cold water volume total at OBIS "
            "8-0:1.8.0.255 and cold water flow rate at OBIS 8-0:3.7.0.255."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=20)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-7-0-1-8-0-255-GAS-VOLUME-TOTAL", matched_ids)
        self.assertIn("KB-OBIS-7-0-3-7-0-255-GAS-FLOW-RATE", matched_ids)
        self.assertIn("KB-OBIS-8-0-1-8-0-255-WATER-VOLUME-TOTAL", matched_ids)
        self.assertIn("KB-OBIS-8-0-3-7-0-255-WATER-FLOW-RATE", matched_ids)

    def test_compiled_obsidian_materializes_hot_water_obis_rows(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in payload["entries"]}

        expected = {
            "KB-OBIS-9-0-1-8-0-255-HOT-WATER-VOLUME-TOTAL": ("9-0:1.8.0.255", "Hot water volume total", 3, "hot_water", 65),
            "KB-OBIS-9-0-3-7-0-255-HOT-WATER-FLOW-RATE": ("9-0:3.7.0.255", "Hot water flow rate instantaneous", 3, "hot_water", 65),
        }

        missing = [entry_id for entry_id in expected if entry_id not in by_id]
        self.assertEqual(missing, [])
        for entry_id, (obis, name, class_id, medium, table_no) in expected.items():
            entry = by_id[entry_id]
            self.assertEqual(entry["type"], "cosem_object_instance")
            self.assertEqual(entry["obis_pattern"], obis)
            self.assertEqual(entry["name"], name)
            self.assertEqual(entry["likely_interface_class_id"], class_id)
            self.assertEqual(entry["medium"], medium)
            self.assertEqual(entry["blue_book_table_ref"]["table_no"], table_no)
            self.assertTrue(entry.get("value_group_mapping"))
            self.assertTrue(entry.get("applicable_notes"))

    def test_runtime_matching_finds_hot_water_obis_rows(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The hot water meter shall expose hot water volume total at OBIS 9-0:1.8.0.255 "
            "and hot water flow rate at OBIS 9-0:3.7.0.255."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=20)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-9-0-1-8-0-255-HOT-WATER-VOLUME-TOTAL", matched_ids)
        self.assertIn("KB-OBIS-9-0-3-7-0-255-HOT-WATER-FLOW-RATE", matched_ids)

    def test_compiled_obsidian_materializes_water_temperature_obis_rows(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in payload["entries"]}

        expected = {
            "KB-OBIS-8-0-5-7-0-255-WATER-TEMPERATURE": ("8-0:5.7.0.255", "Cold water temperature instantaneous", 3, "water", 65),
            "KB-OBIS-8-0-5-4-0-255-WATER-TEMPERATURE-AVERAGE": ("8-0:5.4.0.255", "Cold water temperature average", 3, "water", 65),
            "KB-OBIS-9-0-5-7-0-255-HOT-WATER-TEMPERATURE": ("9-0:5.7.0.255", "Hot water temperature instantaneous", 3, "hot_water", 65),
            "KB-OBIS-9-0-5-4-0-255-HOT-WATER-TEMPERATURE-AVERAGE": ("9-0:5.4.0.255", "Hot water temperature average", 3, "hot_water", 65),
        }

        missing = [entry_id for entry_id in expected if entry_id not in by_id]
        self.assertEqual(missing, [])
        for entry_id, (obis, name, class_id, medium, table_no) in expected.items():
            entry = by_id[entry_id]
            self.assertEqual(entry["type"], "cosem_object_instance")
            self.assertEqual(entry["obis_pattern"], obis)
            self.assertEqual(entry["name"], name)
            self.assertEqual(entry["likely_interface_class_id"], class_id)
            self.assertEqual(entry["medium"], medium)
            self.assertEqual(entry["blue_book_table_ref"]["table_no"], table_no)
            self.assertTrue(entry.get("value_group_mapping"))
            self.assertTrue(entry.get("applicable_notes"))

    def test_runtime_matching_finds_water_temperature_obis_rows(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The cold water meter shall expose water temperature at OBIS 8-0:5.7.0.255 and "
            "average water temperature at OBIS 8-0:5.4.0.255. The hot water meter shall expose "
            "hot water temperature at OBIS 9-0:5.7.0.255 and average hot water temperature at "
            "OBIS 9-0:5.4.0.255."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=20)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-8-0-5-7-0-255-WATER-TEMPERATURE", matched_ids)
        self.assertIn("KB-OBIS-8-0-5-4-0-255-WATER-TEMPERATURE-AVERAGE", matched_ids)
        self.assertIn("KB-OBIS-9-0-5-7-0-255-HOT-WATER-TEMPERATURE", matched_ids)
        self.assertIn("KB-OBIS-9-0-5-4-0-255-HOT-WATER-TEMPERATURE-AVERAGE", matched_ids)

    def test_compiled_obsidian_materializes_gas_process_measurement_obis_rows(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in payload["entries"]}

        expected = {
            "KB-OBIS-7-0-5-7-0-255-GAS-TEMPERATURE": ("7-0:5.7.0.255", "Gas temperature instantaneous", 3, "gas", 51),
            "KB-OBIS-7-0-5-4-0-255-GAS-TEMPERATURE-AVERAGE": ("7-0:5.4.0.255", "Gas temperature average", 3, "gas", 51),
            "KB-OBIS-7-0-7-7-0-255-GAS-PRESSURE": ("7-0:7.7.0.255", "Gas pressure instantaneous", 3, "gas", 51),
            "KB-OBIS-7-0-7-4-0-255-GAS-PRESSURE-AVERAGE": ("7-0:7.4.0.255", "Gas pressure average", 3, "gas", 51),
        }

        missing = [entry_id for entry_id in expected if entry_id not in by_id]
        self.assertEqual(missing, [])
        for entry_id, (obis, name, class_id, medium, table_no) in expected.items():
            entry = by_id[entry_id]
            self.assertEqual(entry["type"], "cosem_object_instance")
            self.assertEqual(entry["obis_pattern"], obis)
            self.assertEqual(entry["name"], name)
            self.assertEqual(entry["likely_interface_class_id"], class_id)
            self.assertEqual(entry["medium"], medium)
            self.assertEqual(entry["blue_book_table_ref"]["table_no"], table_no)
            self.assertTrue(entry.get("value_group_mapping"))
            self.assertTrue(entry.get("applicable_notes"))

    def test_runtime_matching_finds_gas_process_measurement_obis_rows(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The gas meter shall expose gas temperature at OBIS 7-0:5.7.0.255, average gas "
            "temperature at OBIS 7-0:5.4.0.255, gas pressure at OBIS 7-0:7.7.0.255, and "
            "average gas pressure at OBIS 7-0:7.4.0.255."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=20)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-7-0-5-7-0-255-GAS-TEMPERATURE", matched_ids)
        self.assertIn("KB-OBIS-7-0-5-4-0-255-GAS-TEMPERATURE-AVERAGE", matched_ids)
        self.assertIn("KB-OBIS-7-0-7-7-0-255-GAS-PRESSURE", matched_ids)
        self.assertIn("KB-OBIS-7-0-7-4-0-255-GAS-PRESSURE-AVERAGE", matched_ids)

    def test_compiled_obsidian_materializes_high_frequency_general_obis_rows_from_real_smoke(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in payload["entries"]}

        expected = {
            "KB-OBIS-0-0-1-0-0-255-CLOCK": ("0-0:1.0.0.255", "Clock", 8, "general", 8),
            "KB-OBIS-0-0-96-1-0-255-DEVICE-ID-1": ("0-0:96.1.0.255", "Device ID 1", 1, "general", 8),
            "KB-OBIS-0-0-96-1-4-255-DEVICE-ID-5": ("0-0:96.1.4.255", "Device ID 5", 1, "general", 8),
        }

        missing = [entry_id for entry_id in expected if entry_id not in by_id]
        self.assertEqual(missing, [])
        for entry_id, (obis, name, class_id, medium, table_no) in expected.items():
            entry = by_id[entry_id]
            self.assertEqual(entry["type"], "cosem_object_instance")
            self.assertEqual(entry["obis_pattern"], obis)
            self.assertEqual(entry["name"], name)
            self.assertEqual(entry["likely_interface_class_id"], class_id)
            self.assertEqual(entry["medium"], medium)
            self.assertEqual(entry["blue_book_table_ref"]["table_no"], table_no)
            self.assertTrue(entry.get("value_group_mapping"))
            self.assertTrue(entry.get("applicable_notes"))

    def test_runtime_matching_finds_high_frequency_general_obis_rows_from_real_smoke(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The meter shall expose the Clock object at OBIS 0-0:1.0.0.255 with interface class 8. "
            "The meter serial shall be exposed as Device ID 1 at OBIS 0-0:96.1.0.255 and Device ID 5 "
            "at OBIS 0-0:96.1.4.255."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=10)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-0-0-1-0-0-255-CLOCK", matched_ids)
        self.assertIn("KB-OBIS-0-0-96-1-0-255-DEVICE-ID-1", matched_ids)
        self.assertIn("KB-OBIS-0-0-96-1-4-255-DEVICE-ID-5", matched_ids)

    def test_compiled_obsidian_materializes_abnt_high_attribute_profile_rows(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in payload["entries"]}

        expected = {
            "KB-OBIS-1-0-98-1-0-255-BILLING-PERIOD-1-STORED-VALUES-PROFILE": (
                "1-0:98.1.0.255",
                "Date of billing period 1 Stored Billing Values Profile",
                24,
            ),
            "KB-OBIS-1-0-98-2-0-255-BILLING-PERIOD-2-STORED-VALUES-PROFILE": (
                "1-0:98.2.0.255",
                "Date of billing period 2 Stored Billing Values Profile",
                24,
            ),
            "KB-OBIS-0-0-21-0-5-255-CURRENT-BILLING-VALUES": (
                "0-0:21.0.5.255",
                "Current billing values",
                12,
            ),
            "KB-OBIS-0-0-21-0-6-255-INSTANT-VALUES": (
                "0-0:21.0.6.255",
                "Instant Values",
                12,
            ),
            "KB-OBIS-1-0-99-1-0-255-LOAD-PROFILE-PERIOD-1": (
                "1-0:99.1.0.255",
                "Load profile and quality with period 1",
                24,
            ),
            "KB-OBIS-1-0-99-2-0-255-LOAD-PROFILE-PERIOD-2": (
                "1-0:99.2.0.255",
                "Load profile and quality with period 2",
                24,
            ),
            "KB-OBIS-1-0-94-55-178-255-DRP-LOG": (
                "1-0:94.55.178.255",
                "DRP Log",
                24,
            ),
            "KB-OBIS-1-0-94-55-183-255-DRC-LOG": (
                "1-0:94.55.183.255",
                "DRC Log",
                24,
            ),
            "KB-OBIS-1-0-94-55-189-255-MONTHLY-DRP-LOG": (
                "1-0:94.55.189.255",
                "Monthly DRP Log",
                24,
            ),
            "KB-OBIS-1-0-94-55-194-255-MONTHLY-DRC-LOG": (
                "1-0:94.55.194.255",
                "Monthly DRC Log",
                24,
            ),
        }

        missing = [entry_id for entry_id in expected if entry_id not in by_id]
        self.assertEqual(missing, [])
        for entry_id, (obis, name, table_no) in expected.items():
            entry = by_id[entry_id]
            self.assertEqual(entry["type"], "cosem_object_instance")
            self.assertEqual(entry["obis_pattern"], obis)
            self.assertEqual(entry["name"], name)
            self.assertEqual(entry["likely_interface_class_id"], 7)
            self.assertEqual(entry["medium"], "ac_electricity" if obis.startswith("1-0:") else "general")
            self.assertEqual(entry["blue_book_table_ref"]["table_no"], table_no)
            self.assertTrue(entry.get("value_group_mapping"))
            self.assertTrue(entry.get("applicable_notes"))

    def test_compiled_obsidian_materializes_abnt_average_demand_register_rows(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in payload["entries"]}

        expected = {
            "KB-OBIS-1-0-1-4-0-255-AVERAGE-ACTIVE-DEMAND-IMPORT": (
                "1-0:1.4.0.255",
                "Average Active Demand Register import (+A)",
                "1 active power+ / active energy import direction",
            ),
            "KB-OBIS-1-0-2-4-0-255-AVERAGE-ACTIVE-DEMAND-EXPORT": (
                "1-0:2.4.0.255",
                "Average Active Demand Register export (-A)",
                "2 active power- / active energy export direction",
            ),
            "KB-OBIS-1-0-3-4-0-255-AVERAGE-REACTIVE-DEMAND-IMPORT": (
                "1-0:3.4.0.255",
                "Average Reactive Demand Register import (+A)",
                "3 reactive power+ / reactive energy import direction",
            ),
            "KB-OBIS-1-0-4-4-0-255-AVERAGE-REACTIVE-DEMAND-EXPORT": (
                "1-0:4.4.0.255",
                "Average Reactive Demand Register export (-A)",
                "4 reactive power- / reactive energy export direction",
            ),
            "KB-OBIS-1-0-5-4-0-255-AVERAGE-REACTIVE-DEMAND-Q1": (
                "1-0:5.4.0.255",
                "Average Reactive Demand Register import (Q1)",
                "5 reactive quadrant Q1",
            ),
            "KB-OBIS-1-0-6-4-0-255-AVERAGE-REACTIVE-DEMAND-Q2": (
                "1-0:6.4.0.255",
                "Average Reactive Demand Register import (Q2)",
                "6 reactive quadrant Q2",
            ),
            "KB-OBIS-1-0-7-4-0-255-AVERAGE-REACTIVE-DEMAND-Q3": (
                "1-0:7.4.0.255",
                "Average Reactive Demand Register import (Q3)",
                "7 reactive quadrant Q3",
            ),
            "KB-OBIS-1-0-8-4-0-255-AVERAGE-REACTIVE-DEMAND-Q4": (
                "1-0:8.4.0.255",
                "Average Reactive Demand Register import (Q4)",
                "8 reactive quadrant Q4",
            ),
        }

        missing = [entry_id for entry_id in expected if entry_id not in by_id]
        self.assertEqual(missing, [])
        for entry_id, (obis, name, c_mapping) in expected.items():
            entry = by_id[entry_id]
            self.assertEqual(entry["type"], "cosem_object_instance")
            self.assertEqual(entry["obis_pattern"], obis)
            self.assertEqual(entry["name"], name)
            self.assertEqual(entry["likely_interface_class_id"], 5)
            self.assertEqual(entry["medium"], "ac_electricity")
            self.assertEqual(entry["blue_book_table_ref"]["table_no"], 14)
            self.assertEqual(entry["value_group_mapping"]["C"], c_mapping)
            self.assertEqual(entry["value_group_mapping"]["D"], "4 average value for current demand period")
            self.assertTrue(entry.get("applicable_notes"))

    def test_compiled_obsidian_materializes_abnt_maximum_demand_extended_register_rows(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in payload["entries"]}

        expected = {
            "KB-OBIS-1-0-1-6-X-255-MAXIMUM-ACTIVE-DEMAND-IMPORT": (
                "1-0:1.6.x.255",
                "Maximum Active Demand Register import (+A)",
                "1 active power+ / active energy import direction",
            ),
            "KB-OBIS-1-0-2-6-X-255-MAXIMUM-ACTIVE-DEMAND-EXPORT": (
                "1-0:2.6.x.255",
                "Maximum Active Demand Register export (-A)",
                "2 active power- / active energy export direction",
            ),
            "KB-OBIS-1-0-3-6-X-255-MAXIMUM-REACTIVE-DEMAND-IMPORT": (
                "1-0:3.6.x.255",
                "Maximum Reactive Demand Register import (+A)",
                "3 reactive power+ / reactive energy import direction",
            ),
            "KB-OBIS-1-0-4-6-X-255-MAXIMUM-REACTIVE-DEMAND-EXPORT": (
                "1-0:4.6.x.255",
                "Maximum Reactive Demand Register export (-A)",
                "4 reactive power- / reactive energy export direction",
            ),
            "KB-OBIS-1-0-5-6-X-255-MAXIMUM-REACTIVE-DEMAND-Q1": (
                "1-0:5.6.x.255",
                "Maximum Reactive Demand Register import (Q1)",
                "5 reactive quadrant Q1",
            ),
            "KB-OBIS-1-0-6-6-X-255-MAXIMUM-REACTIVE-DEMAND-Q2": (
                "1-0:6.6.x.255",
                "Maximum Reactive Demand Register import (Q2)",
                "6 reactive quadrant Q2",
            ),
            "KB-OBIS-1-0-7-6-X-255-MAXIMUM-REACTIVE-DEMAND-Q3": (
                "1-0:7.6.x.255",
                "Maximum Reactive Demand Register import (Q3)",
                "7 reactive quadrant Q3",
            ),
            "KB-OBIS-1-0-8-6-X-255-MAXIMUM-REACTIVE-DEMAND-Q4": (
                "1-0:8.6.x.255",
                "Maximum Reactive Demand Register import (Q4)",
                "8 reactive quadrant Q4",
            ),
        }

        missing = [entry_id for entry_id in expected if entry_id not in by_id]
        self.assertEqual(missing, [])
        for entry_id, (obis, name, c_mapping) in expected.items():
            entry = by_id[entry_id]
            self.assertEqual(entry["type"], "cosem_object_instance")
            self.assertEqual(entry["obis_pattern"], obis)
            self.assertEqual(entry["name"], name)
            self.assertEqual(entry["likely_interface_class_id"], 4)
            self.assertEqual(entry["medium"], "ac_electricity")
            self.assertEqual(entry["blue_book_table_ref"]["table_no"], 14)
            self.assertEqual(entry["value_group_mapping"]["C"], c_mapping)
            self.assertEqual(entry["value_group_mapping"]["D"], "6 maximum demand value for billing period")
            self.assertTrue(entry.get("applicable_notes"))

    def test_runtime_matching_finds_abnt_maximum_demand_extended_register_rows(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The meter shall expose maximum active demand import at OBIS 1-0:1.6.x.255, "
            "maximum active demand export at OBIS 1-0:2.6.x.255, and reactive maximum demand "
            "quadrants Q1, Q2, Q3, and Q4 at OBIS 1-0:5.6.x.255, 1-0:6.6.x.255, "
            "1-0:7.6.x.255, and 1-0:8.6.x.255."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=30)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-1-0-1-6-X-255-MAXIMUM-ACTIVE-DEMAND-IMPORT", matched_ids)
        self.assertIn("KB-OBIS-1-0-2-6-X-255-MAXIMUM-ACTIVE-DEMAND-EXPORT", matched_ids)
        self.assertIn("KB-OBIS-1-0-5-6-X-255-MAXIMUM-REACTIVE-DEMAND-Q1", matched_ids)
        self.assertIn("KB-OBIS-1-0-6-6-X-255-MAXIMUM-REACTIVE-DEMAND-Q2", matched_ids)
        self.assertIn("KB-OBIS-1-0-7-6-X-255-MAXIMUM-REACTIVE-DEMAND-Q3", matched_ids)
        self.assertIn("KB-OBIS-1-0-8-6-X-255-MAXIMUM-REACTIVE-DEMAND-Q4", matched_ids)

    def test_compiled_obsidian_materializes_abnt_cumulative_demand_extended_register_rows(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in payload["entries"]}

        expected = {
            "KB-OBIS-1-0-1-2-X-255-CUMULATIVE-ACTIVE-DEMAND-IMPORT": (
                "1-0:1.2.x.255",
                "Cumulative Active Demand Register import (+A)",
                "1 active power+ / active energy import direction",
            ),
            "KB-OBIS-1-0-2-2-X-255-CUMULATIVE-ACTIVE-DEMAND-EXPORT": (
                "1-0:2.2.x.255",
                "Cumulative Active Demand Register export (-A)",
                "2 active power- / active energy export direction",
            ),
            "KB-OBIS-1-0-3-2-X-255-CUMULATIVE-REACTIVE-DEMAND-IMPORT": (
                "1-0:3.2.x.255",
                "Cumulative Reactive Demand Register import (+A)",
                "3 reactive power+ / reactive energy import direction",
            ),
            "KB-OBIS-1-0-4-2-X-255-CUMULATIVE-REACTIVE-DEMAND-EXPORT": (
                "1-0:4.2.x.255",
                "Cumulative Reactive Demand Register export (-A)",
                "4 reactive power- / reactive energy export direction",
            ),
            "KB-OBIS-1-0-5-2-X-255-CUMULATIVE-REACTIVE-DEMAND-Q1": (
                "1-0:5.2.x.255",
                "Cumulative Reactive Demand Register import (Q1)",
                "5 reactive quadrant Q1",
            ),
            "KB-OBIS-1-0-6-2-X-255-CUMULATIVE-REACTIVE-DEMAND-Q2": (
                "1-0:6.2.x.255",
                "Cumulative Reactive Demand Register import (Q2)",
                "6 reactive quadrant Q2",
            ),
            "KB-OBIS-1-0-7-2-X-255-CUMULATIVE-REACTIVE-DEMAND-Q3": (
                "1-0:7.2.x.255",
                "Cumulative Reactive Demand Register import (Q3)",
                "7 reactive quadrant Q3",
            ),
            "KB-OBIS-1-0-8-2-X-255-CUMULATIVE-REACTIVE-DEMAND-Q4": (
                "1-0:8.2.x.255",
                "Cumulative Reactive Demand Register import (Q4)",
                "8 reactive quadrant Q4",
            ),
        }

        missing = [entry_id for entry_id in expected if entry_id not in by_id]
        self.assertEqual(missing, [])
        for entry_id, (obis, name, c_mapping) in expected.items():
            entry = by_id[entry_id]
            self.assertEqual(entry["type"], "cosem_object_instance")
            self.assertEqual(entry["obis_pattern"], obis)
            self.assertEqual(entry["name"], name)
            self.assertEqual(entry["likely_interface_class_id"], 4)
            self.assertEqual(entry["medium"], "ac_electricity")
            self.assertEqual(entry["blue_book_table_ref"]["table_no"], 14)
            self.assertEqual(entry["value_group_mapping"]["C"], c_mapping)
            self.assertEqual(entry["value_group_mapping"]["D"], "2 cumulative maximum demand value")
            self.assertTrue(entry.get("applicable_notes"))

    def test_runtime_matching_finds_abnt_cumulative_demand_extended_register_rows(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The meter shall expose cumulative active demand import at OBIS 1-0:1.2.x.255, "
            "cumulative active demand export at OBIS 1-0:2.2.x.255, and cumulative reactive "
            "demand quadrants Q1, Q2, Q3, and Q4 at OBIS 1-0:5.2.x.255, 1-0:6.2.x.255, "
            "1-0:7.2.x.255, and 1-0:8.2.x.255."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=30)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-1-0-1-2-X-255-CUMULATIVE-ACTIVE-DEMAND-IMPORT", matched_ids)
        self.assertIn("KB-OBIS-1-0-2-2-X-255-CUMULATIVE-ACTIVE-DEMAND-EXPORT", matched_ids)
        self.assertIn("KB-OBIS-1-0-5-2-X-255-CUMULATIVE-REACTIVE-DEMAND-Q1", matched_ids)
        self.assertIn("KB-OBIS-1-0-6-2-X-255-CUMULATIVE-REACTIVE-DEMAND-Q2", matched_ids)
        self.assertIn("KB-OBIS-1-0-7-2-X-255-CUMULATIVE-REACTIVE-DEMAND-Q3", matched_ids)
        self.assertIn("KB-OBIS-1-0-8-2-X-255-CUMULATIVE-REACTIVE-DEMAND-Q4", matched_ids)

    def test_compiled_obsidian_materializes_abnt_control_and_comms_rows(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in payload["entries"]}

        expected = {
            "KB-OBIS-0-0-44-0-0-255-IMAGE-TRANSFER": (
                "0-0:44.0.0.255",
                "Image Transfer",
                18,
                "general",
                8,
            ),
            "KB-OBIS-0-1-22-0-0-255-IEC-HDLC-SETUP-SERIAL-PORT": (
                "0-1:22.0.0.255",
                "IEC HDLC setup - Serial port",
                23,
                "general",
                8,
            ),
            "KB-OBIS-0-2-22-0-0-255-IEC-HDLC-SETUP-OPTICAL-PORT": (
                "0-2:22.0.0.255",
                "IEC HDLC setup - Optical port",
                23,
                "general",
                8,
            ),
            "KB-OBIS-0-0-96-3-10-255-DISCONNECT-CONTROL": (
                "0-0:96.3.10.255",
                "Disconnect Control",
                70,
                "general",
                8,
            ),
            "KB-OBIS-0-1-96-3-10-255-DISCONNECT-CONTROL-AUX-RELAY": (
                "0-1:96.3.10.255",
                "Disconnect Control for Aux. relay",
                70,
                "general",
                8,
            ),
            "KB-OBIS-0-1-94-55-118-255-USER-OUTPUT-CONFIGURATION": (
                "0-1:94.55.118.255",
                "User output configuration",
                1,
                "general",
                9,
            ),
        }

        missing = [entry_id for entry_id in expected if entry_id not in by_id]
        self.assertEqual(missing, [])
        for entry_id, (obis, name, class_id, medium, table_no) in expected.items():
            entry = by_id[entry_id]
            self.assertEqual(entry["type"], "cosem_object_instance")
            self.assertEqual(entry["obis_pattern"], obis)
            self.assertEqual(entry["name"], name)
            self.assertEqual(entry["likely_interface_class_id"], class_id)
            self.assertEqual(entry["medium"], medium)
            self.assertEqual(entry["blue_book_table_ref"]["table_no"], table_no)
            self.assertTrue(entry.get("value_group_mapping"))
            self.assertTrue(entry.get("applicable_notes"))

    def test_compiled_obsidian_materializes_abnt_control_flow_script_rows(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in payload["entries"]}

        expected = {
            "KB-OBIS-0-0-10-0-0-255-GLOBAL-METER-RESET": (
                "0-0:10.0.0.255",
                "Global Meter Reset",
                9,
                "general",
                8,
            ),
            "KB-OBIS-0-0-10-0-1-255-MDI-RESET-END-BILLING-PERIOD": (
                "0-0:10.0.1.255",
                "Predefined Scripts - MDI reset / end of billing period",
                9,
                "general",
                8,
            ),
            "KB-OBIS-0-0-10-0-100-255-TARIFFICATION-SCRIPT-TABLE": (
                "0-0:10.0.100.255",
                "Tariffication script table",
                9,
                "general",
                8,
            ),
            "KB-OBIS-0-0-10-0-107-255-IMAGE-ACTIVATION-SCRIPT-TABLE": (
                "0-0:10.0.107.255",
                "Predefined Scripts - Image Activation",
                9,
                "general",
                8,
            ),
            "KB-OBIS-0-0-15-0-2-255-IMAGE-ACTIVATION-SCHEDULER": (
                "0-0:15.0.2.255",
                "Image Activation Scheduler",
                22,
                "general",
                8,
            ),
            "KB-OBIS-0-1-94-55-20-255-PREVIOUS-DISCONNECT-CONTROL": (
                "0-1:94.55.20.255",
                "Previous Disconnect Control",
                70,
                "general",
                8,
            ),
        }

        missing = [entry_id for entry_id in expected if entry_id not in by_id]
        self.assertEqual(missing, [])
        for entry_id, (obis, name, class_id, medium, table_no) in expected.items():
            entry = by_id[entry_id]
            self.assertEqual(entry["type"], "cosem_object_instance")
            self.assertEqual(entry["obis_pattern"], obis)
            self.assertEqual(entry["name"], name)
            self.assertEqual(entry["likely_interface_class_id"], class_id)
            self.assertEqual(entry["medium"], medium)
            self.assertEqual(entry["blue_book_table_ref"]["table_no"], table_no)
            self.assertTrue(entry.get("value_group_mapping"))
            self.assertTrue(entry.get("applicable_notes"))

    def test_compiled_obsidian_materializes_abnt_billing_disconnect_key_schedule_rows(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in payload["entries"]}

        expected = {
            "KB-OBIS-0-0-15-0-0-255-ACTIVE-END-BILLING-PERIOD-1": (
                "0-0:15.0.0.255",
                "Active end of billing period 1",
                22,
                "general",
                8,
            ),
            "KB-OBIS-0-0-15-1-0-255-END-BILLING-PERIOD-2": (
                "0-0:15.1.0.255",
                "End of billing period 2",
                22,
                "general",
                8,
            ),
            "KB-OBIS-0-0-15-0-1-255-DISCONNECT-CONTROL-SCHEDULER": (
                "0-0:15.0.1.255",
                "Disconnect control Scheduler",
                22,
                "general",
                8,
            ),
            "KB-OBIS-0-0-10-0-106-255-DISCONNECT-SCRIPT-TABLE": (
                "0-0:10.0.106.255",
                "Disconnect Script Table",
                9,
                "general",
                8,
            ),
            "KB-OBIS-0-0-15-X-7-255-KEY-EXPIRATION-SINGLE-ACTION-SCHEDULE": (
                "0-0:15.x.7.255",
                "Key expiration Single action schedule",
                22,
                "general",
                8,
            ),
            "KB-OBIS-0-0-10-0-111-255-KEY-EXPIRATION-SCRIPT-TABLE": (
                "0-0:10.0.111.255",
                "Key expiration Script table",
                9,
                "general",
                8,
            ),
        }

        missing = [entry_id for entry_id in expected if entry_id not in by_id]
        self.assertEqual(missing, [])
        for entry_id, (obis, name, class_id, medium, table_no) in expected.items():
            entry = by_id[entry_id]
            self.assertEqual(entry["type"], "cosem_object_instance")
            self.assertEqual(entry["obis_pattern"], obis)
            self.assertEqual(entry["name"], name)
            self.assertEqual(entry["likely_interface_class_id"], class_id)
            self.assertEqual(entry["medium"], medium)
            self.assertEqual(entry["blue_book_table_ref"]["table_no"], table_no)
            self.assertTrue(entry.get("value_group_mapping"))
            self.assertTrue(entry.get("applicable_notes"))

    def test_compiled_obsidian_materializes_remaining_example_obis_tables(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in payload["entries"]}

        expected = {
            "KB-OBIS-4-0-1-8-0-255-HCA-HEAT-COST-ALLOCATOR-VALUE": (
                "4-0:1.8.0.255",
                "HCA heat cost allocator value",
                3,
                "hca",
                41,
            ),
            "KB-OBIS-4-0-1-7-0-255-HCA-HEAT-COST-ALLOCATOR-INSTANTANEOUS": (
                "4-0:1.7.0.255",
                "HCA heat cost allocator instantaneous value",
                3,
                "hca",
                41,
            ),
            "KB-OBIS-4-0-1-6-0-255-HCA-HEAT-COST-ALLOCATOR-MAXIMUM": (
                "4-0:1.6.0.255",
                "HCA heat cost allocator maximum value",
                3,
                "hca",
                41,
            ),
            "KB-OBIS-6-0-6-8-0-255-THERMAL-COOLING-ENERGY-TOTAL": (
                "6-0:6.8.0.255",
                "Thermal cooling energy total",
                3,
                "thermal_energy",
                49,
            ),
            "KB-OBIS-6-0-6-7-0-255-THERMAL-COOLING-POWER-INSTANTANEOUS": (
                "6-0:6.7.0.255",
                "Thermal cooling power instantaneous",
                3,
                "thermal_energy",
                49,
            ),
            "KB-OBIS-6-0-6-6-0-255-THERMAL-COOLING-POWER-MAXIMUM": (
                "6-0:6.6.0.255",
                "Thermal cooling power maximum",
                3,
                "thermal_energy",
                49,
            ),
            "KB-OBIS-7-0-13-7-0-255-GAS-CONVERSION-FACTOR": (
                "7-0:13.7.0.255",
                "Gas conversion factor",
                3,
                "gas",
                50,
            ),
            "KB-OBIS-7-0-13-4-0-255-GAS-CONVERSION-FACTOR-AVERAGE": (
                "7-0:13.4.0.255",
                "Gas conversion factor average",
                3,
                "gas",
                50,
            ),
            "KB-OBIS-7-0-13-6-0-255-GAS-CONVERSION-FACTOR-MAXIMUM": (
                "7-0:13.6.0.255",
                "Gas conversion factor maximum",
                3,
                "gas",
                50,
            ),
            "KB-OBIS-8-0-13-7-0-255-WATER-CONVERSION-FACTOR": (
                "8-0:13.7.0.255",
                "Water conversion factor",
                3,
                "water",
                72,
            ),
            "KB-OBIS-8-0-13-4-0-255-WATER-CONVERSION-FACTOR-AVERAGE": (
                "8-0:13.4.0.255",
                "Water conversion factor average",
                3,
                "water",
                72,
            ),
            "KB-OBIS-8-0-13-6-0-255-WATER-CONVERSION-FACTOR-MAXIMUM": (
                "8-0:13.6.0.255",
                "Water conversion factor maximum",
                3,
                "water",
                72,
            ),
        }

        missing = [entry_id for entry_id in expected if entry_id not in by_id]
        self.assertEqual(missing, [])
        for entry_id, (obis, name, class_id, medium, table_no) in expected.items():
            entry = by_id[entry_id]
            self.assertEqual(entry["type"], "cosem_object_instance")
            self.assertEqual(entry["obis_pattern"], obis)
            self.assertEqual(entry["name"], name)
            self.assertEqual(entry["likely_interface_class_id"], class_id)
            self.assertEqual(entry["medium"], medium)
            self.assertEqual(entry["blue_book_table_ref"]["table_no"], table_no)
            self.assertTrue(entry.get("value_group_mapping"))
            self.assertTrue(entry.get("applicable_notes"))

    def test_runtime_matching_finds_remaining_example_obis_tables(self) -> None:
        repo = KnowledgeRepository.from_paths([ROOT / "knowledge_bases" / "compiled_from_obsidian.json"])

        text = (
            "The heat cost allocator shall expose HCA heat cost allocator value at OBIS 4-0:1.8.0.255. "
            "It shall also expose HCA instantaneous value at OBIS 4-0:1.7.0.255 and HCA maximum value "
            "at OBIS 4-0:1.6.0.255. "
            "The thermal meter shall expose cooling energy total at OBIS 6-0:6.8.0.255. "
            "It shall also expose instantaneous cooling power at OBIS 6-0:6.7.0.255 and maximum "
            "cooling power at OBIS 6-0:6.6.0.255. "
            "The gas conversion process shall expose gas conversion factor at OBIS 7-0:13.7.0.255, "
            "average gas conversion factor at OBIS 7-0:13.4.0.255, and maximum gas conversion "
            "factor at OBIS 7-0:13.6.0.255. The water meter shall expose water conversion factor "
            "at OBIS 8-0:13.7.0.255, average water conversion factor at OBIS 8-0:13.4.0.255, "
            "and maximum water conversion factor at OBIS 8-0:13.6.0.255."
        )
        matches = repo.match_text(text, entry_type="cosem_object_instance", limit=30)
        matched_ids = {match["entry_id"] for match in matches}

        self.assertIn("KB-OBIS-4-0-1-8-0-255-HCA-HEAT-COST-ALLOCATOR-VALUE", matched_ids)
        self.assertIn("KB-OBIS-4-0-1-7-0-255-HCA-HEAT-COST-ALLOCATOR-INSTANTANEOUS", matched_ids)
        self.assertIn("KB-OBIS-4-0-1-6-0-255-HCA-HEAT-COST-ALLOCATOR-MAXIMUM", matched_ids)
        self.assertIn("KB-OBIS-6-0-6-8-0-255-THERMAL-COOLING-ENERGY-TOTAL", matched_ids)
        self.assertIn("KB-OBIS-6-0-6-7-0-255-THERMAL-COOLING-POWER-INSTANTANEOUS", matched_ids)
        self.assertIn("KB-OBIS-6-0-6-6-0-255-THERMAL-COOLING-POWER-MAXIMUM", matched_ids)
        self.assertIn("KB-OBIS-7-0-13-7-0-255-GAS-CONVERSION-FACTOR", matched_ids)
        self.assertIn("KB-OBIS-7-0-13-4-0-255-GAS-CONVERSION-FACTOR-AVERAGE", matched_ids)
        self.assertIn("KB-OBIS-7-0-13-6-0-255-GAS-CONVERSION-FACTOR-MAXIMUM", matched_ids)
        self.assertIn("KB-OBIS-8-0-13-7-0-255-WATER-CONVERSION-FACTOR", matched_ids)
        self.assertIn("KB-OBIS-8-0-13-4-0-255-WATER-CONVERSION-FACTOR-AVERAGE", matched_ids)
        self.assertIn("KB-OBIS-8-0-13-6-0-255-WATER-CONVERSION-FACTOR-MAXIMUM", matched_ids)

    def test_next_high_value_cosem_classes_are_traceable_and_actionable(self) -> None:
        payload = json.loads((ROOT / "knowledge_bases" / "compiled_from_obsidian.json").read_text(encoding="utf-8"))
        by_id = {entry["id"]: entry for entry in payload["entries"]}
        required_ids = [
            "KB-L3-IC-6-REGISTER-ACTIVATION",
            "KB-L3-IC-10-SCHEDULE",
            "KB-L3-IC-22-SINGLE-ACTION-SCHEDULE",
            "KB-L3-IC-20-ACTIVITY-CALENDAR",
            "KB-L3-IC-21-REGISTER-MONITOR",
            "KB-L3-IC-65-PARAMETER-MONITOR",
            "KB-L3-IC-17-SAP-ASSIGNMENT",
            "KB-L3-IC-23-IEC-HDLC-SETUP",
            "KB-L3-IC-41-TCP-UDP-SETUP",
            "KB-L3-IC-42-IPV4-SETUP",
        ]

        missing_source_refs = []
        missing_details = []
        for entry_id in required_ids:
            entry = by_id[entry_id]
            if not entry.get("source_refs"):
                missing_source_refs.append(entry_id)
            for key in ["attributes", "methods", "access_semantics", "behavior_notes", "common_instances"]:
                if key not in entry:
                    missing_details.append(f"{entry_id}.{key}")

        self.assertEqual(missing_source_refs, [])
        self.assertEqual(missing_details, [])


if __name__ == "__main__":
    unittest.main()
