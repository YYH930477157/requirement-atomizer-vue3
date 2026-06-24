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
            "KB-OBIS-0-0-13-0-0-255-ACTIVITY-CALENDAR": ("0-0:13.0.0.255", "Activity Calendar", 20, "general", 8),
            "KB-OBIS-0-0-14-0-0-255-REGISTER-ACTIVATION": ("0-0:14.0.0.255", "Register activation", 6, "general", 8),
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
            "KB-OBIS-1-0-9-8-0-255-APPARENT-ENERGY-IMPORT": ("1-0:9.8.0.255", "Apparent energy import total", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-11-7-0-255-CURRENT-INSTANTANEOUS": ("1-0:11.7.0.255", "Current any phase instantaneous", 3, "ac_electricity", 13),
            "KB-OBIS-1-0-14-7-0-255-SUPPLY-FREQUENCY": ("1-0:14.7.0.255", "Supply frequency instantaneous", 3, "ac_electricity", 13),
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
