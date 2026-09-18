import json
import tempfile
import unittest
from pathlib import Path

from api_server import (
    _functional_translation_index,
    _functional_translation_projection,
)


class FunctionalTranslationProjectionTests(unittest.TestCase):
    def test_table_cells_project_to_chinese_without_changing_source_fields(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            row = {
                "schema_version": "document-translation/v3",
                "record_kind": "table",
                "block_id": "BLK-000295",
                "status": "translated",
                "table": {
                    "rows": [{
                        "source_cells": [
                            "6.43",
                            "GPS Capability",
                            "The meter shall be equipped with a built-in GPS module. The meter shall push GPS coordinates.",
                        ],
                        "translation": "6.43 | GPS 功能 | 电表应配备内置 GPS 模块。电表应推送 GPS 坐标。",
                    }]
                },
            }
            (root / "document_translations.jsonl").write_text(
                json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            item = {
                "source_block_ids": ["BLK-000295"],
                "objective": "The meter shall be equipped with a built-in GPS module.",
                "behaviors": [
                    "equip a built-in GPS module",
                    "push GPS coordinates",
                ],
                "data_constraints": [],
            }
            projected = _functional_translation_projection(
                item, _functional_translation_index(root)
            )
            self.assertEqual(projected["functional_objective_zh"], "电表应配备内置 GPS 模块。电表应推送 GPS 坐标。")
            self.assertEqual(projected["functional_behaviors_zh"], [
                "电表应配备内置 GPS 模块。",
                "电表应推送 GPS 坐标。",
            ])
            self.assertEqual(item["objective"], "The meter shall be equipped with a built-in GPS module.")


if __name__ == "__main__":
    unittest.main()
