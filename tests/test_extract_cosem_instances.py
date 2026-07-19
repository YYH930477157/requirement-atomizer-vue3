from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from extract_cosem_instances import extract_instances


def write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


class ExtractCosemInstancesTests(unittest.TestCase):
    def object_row(self) -> dict:
        return {
            "item_id": "T1-R1",
            "table_id": "T1",
            "table_title": "Table 1 - Clock",
            "section_path": ["Object model"],
            "row_index": 1,
            "fields": {
                "Object/attribute name": "Clock",
                "CL": "8",
                "Value": "0-0:1.0.0.255",
            },
        }

    def attribute_row(self, table_id: str, title: str) -> dict:
        return {
            "item_id": f"{table_id}-R2",
            "table_id": table_id,
            "table_title": title,
            "section_path": ["Object model"],
            "row_index": 2,
            "fields": {
                "#": "2",
                "Object/attribute name": "time",
                "Type": "octet-string",
            },
        }

    def extract(self, rows: list[dict]) -> list[dict]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "table_items.jsonl"
            write_rows(path, rows)
            return extract_instances(path)

    def test_attribute_from_unrelated_table_is_not_attached(self) -> None:
        rows = [
            self.object_row(),
            self.attribute_row("T2", "Table 2 - Unrelated settings"),
        ]

        instances = self.extract(rows)

        self.assertEqual(instances[0]["attributes"], [])

    def test_attribute_in_same_table_is_attached(self) -> None:
        rows = [
            self.object_row(),
            self.attribute_row("T1", "Table 1 - Clock"),
        ]

        instances = self.extract(rows)

        self.assertEqual([row["name"] for row in instances[0]["attributes"]], ["time"])

    def test_explicit_continuation_table_preserves_context(self) -> None:
        rows = [
            self.object_row(),
            self.attribute_row("T2", "Table 1 - Clock (continued)"),
        ]

        instances = self.extract(rows)

        self.assertEqual([row["name"] for row in instances[0]["attributes"]], ["time"])
        self.assertEqual(instances[0]["source"]["table_ids"], ["T1", "T2"])


if __name__ == "__main__":
    unittest.main()
