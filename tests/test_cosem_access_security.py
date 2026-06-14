from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import cosem_access_security as cas


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def write_fixture(out_dir: Path) -> None:
    write_jsonl(out_dir / "atomic_requirements.jsonl", [
        {"requirement_type": "association_security_matrix", "object": "ClientA", "source_refs": ["TBL-A1"]},
        {"requirement_type": "capability_matrix", "object": "ClientA", "source_refs": ["TBL-C1"]},
        # 污染：来源行没有 IDENTITY_KEY（是属性表行）→ 必须被过滤
        {"requirement_type": "capability_matrix", "object": "Bad", "source_refs": ["TBL-ATTR"]},
        {"requirement_type": "security_suite_definition", "object": "Security suite 0", "source_refs": ["TBL-S0"]},
        {"requirement_type": "security_policy_state", "object": "Security policy state 0", "source_refs": ["TBL-PS0"]},
        {"requirement_type": "security_policy_bit", "object": "Security policy bit 0", "source_refs": ["TBL-PB0"]},
        {"requirement_type": "access_control", "object": "Public Client",
         "requirement": "Management LD (SAP = 0x01) is mandatory."},
    ])
    write_jsonl(out_dir / "table_items.jsonl", [
        {"item_id": "TBL-A1", "fields": {
            "Customer application process": "ClientA",
            "Server application process / Management Logical Device": "High Level of Security (HLS)",
            "Server application process / Measuring logic devices": "Low Level Security (LLS)"}},
        {"item_id": "TBL-C1", "fields": {
            "Customer application process": "ClientA",
            'xDLMS Service / "GET"': "X",
            'xDLMS Service / "SET"': ""}},
        {"item_id": "TBL-ATTR", "fields": {"#": "two", "Type": "integer", "Value": "0"}},
        {"item_id": "TBL-S0", "fields": {
            "ID": "0", "Name": "AES-GCM-128", "Authenticated encryption": "AES-GCM-128",
            "Digital signature": "-", "Key Agreement": "-", '"Hash"': "-",
            "Transport key": "AES-128 key wrap", "Compression": "-"}},
        {"item_id": "TBL-PS0", "fields": {"State": "0", "Security policy": "Anything"}},
        {"item_id": "TBL-PB0", "fields": {"bit": "0", "Security Policy - Security States": "Not used"}},
    ])
    write_jsonl(out_dir / "review_states.jsonl", [])


class AccessSecurityTests(unittest.TestCase):
    def _build(self, tmp: str) -> dict:
        out = Path(tmp)
        write_fixture(out)
        return cas.build_access_security(out)

    def test_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            counts = self._build(tmp)["counts"]
            self.assertEqual(counts["association_clients"], 1)
            self.assertEqual(counts["capability_clients"], 1)  # Bad 被过滤
            self.assertEqual(counts["security_suites"], 1)
            self.assertEqual(counts["security_policy_states"], 1)
            self.assertEqual(counts["security_policy_bits"], 1)
            self.assertEqual(counts["access_control_clients"], 1)

    def test_association_matrix_pivot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            assoc = self._build(tmp)["association_security"]
            self.assertEqual(assoc["clients"], ["ClientA"])
            self.assertIn("Management Logical Device", assoc["columns"])
            self.assertEqual(assoc["matrix"]["ClientA"]["Management Logical Device"], "High Level of Security (HLS)")
            self.assertEqual(assoc["matrix"]["ClientA"]["Measuring logic devices"], "Low Level Security (LLS)")

    def test_capability_pivot_clean_and_no_pollution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cap = self._build(tmp)["capability"]
            self.assertEqual(cap["clients"], ["ClientA"])  # 没有 "Bad"
            self.assertEqual(set(cap["columns"]), {"GET", "SET"})  # 列名去前缀去引号；无 #/Type/Value
            self.assertEqual(cap["matrix"]["ClientA"]["GET"], "X")

    def test_security_suite_hash_key_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            suite = self._build(tmp)["security_suites"][0]
            self.assertEqual(suite["id"], "0")
            self.assertEqual(suite["name"], "AES-GCM-128")
            self.assertEqual(suite["hash"], "-")  # 来自 '"Hash"' 键
            self.assertEqual(suite["transport_key"], "AES-128 key wrap")

    def test_render_markdown_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            model = cas.build_access_security(out)
            written = cas.write_access_security(out, model)
            self.assertEqual(set(written), {"cosem_access_security.json", "cosem_access_security.md"})
            md = (out / "cosem_access_security.md").read_text(encoding="utf-8")
            self.assertIn("关联安全矩阵", md)
            self.assertIn("High Level of Security (HLS)", md)
            self.assertIn("✓", md)  # 能力矩阵 X→✓


if __name__ == "__main__":
    unittest.main()
