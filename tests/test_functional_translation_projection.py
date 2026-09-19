import json
import tempfile
import unittest
from pathlib import Path

from api_server import (
    _functional_title_translation,
    _functional_translation_index,
    _functional_translation_projection,
    _translated_sentence,
)


class FunctionalTranslationProjectionTests(unittest.TestCase):
    def test_packaged_translations_resolve_from_root_and_analysis_directory(self):
        from result_package import initialize_result_package, governed_artifact_path

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source.pdf"
            source.write_bytes(b"fixture")
            initialize_result_package(root, input_path=source, requested_stages=["atomize"])
            governed_artifact_path(root, "document_translations.jsonl", category="pipeline").write_text(
                json.dumps({"block_id": "B1", "status": "translated",
                            "source_text": "Send GPS coordinates.",
                            "translation": "发送 GPS 坐标。"}) + "\n", encoding="utf-8")
            governed_artifact_path(root, "annotation_translations.json", category="cache").write_text(
                json.dumps({"items": {"heading": {"status": "accepted",
                            "source_head": "Technical requirements",
                            "translation": "技术要求"}}}), encoding="utf-8")
            for directory in (root, root / ".ratomizer" / "pipeline"):
                with self.subTest(directory=directory):
                    self.assertEqual(_functional_translation_index(directory)["B1"][0]["translation"],
                                     "发送 GPS 坐标。")
                    self.assertEqual(_functional_title_translation(directory, "Technical requirements"),
                                     "技术要求")

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
            self.assertEqual(projected["functional_objective_zh"], "电表应配备内置 GPS 模块。")
            self.assertEqual(projected["functional_behaviors_zh"], [
                "电表应配备内置 GPS 模块。",
                "电表应推送 GPS 坐标。",
            ])
            self.assertEqual(item["objective"], "The meter shall be equipped with a built-in GPS module.")

    def test_decimal_and_distinct_sealing_fields_survive_projection(self):
        sentences = [
            "Provide sealing to prevent tampering.",
            "The terminal cover shall have seals.",
            "All seals shall be on the front side only.",
            "Rear side seals shall not be accepted.",
            "Sealing holes shall fit sealing wire not less than 2.5mm diameter.",
        ]
        translations = [
            "应提供密封措施以防篡改。", "端子盖应设有封印。",
            "所有封印应仅设在正面。", "不接受背面封印。",
            "铅封孔应能容纳直径不小于 2.5 mm 的密封线。",
        ]
        item = {
            "source_block_ids": ["B1"], "objective": sentences[0],
            "behaviors": sentences[1:],
            "data_constraints": [
                "Sealing wire diameter: not less than 2.5mm.",
                "Sealing location: front side only.",
            ],
        }
        before = json.dumps(item)
        projection = _functional_translation_projection(item, {"B1": [{
            "source": " ".join(sentences), "translation": "".join(translations),
        }]})
        self.assertEqual(projection["functional_objective_zh"], translations[0])
        self.assertEqual(projection["functional_behaviors_zh"], translations[1:])
        self.assertEqual(projection["functional_data_constraints_zh"], [translations[4], translations[2]])
        self.assertEqual(json.dumps(item), before)

    def test_unmatched_and_duplicate_entries_are_never_dropped(self):
        item = {"source_block_ids": ["B1"], "behaviors": [
            "Send GPS coordinates.", "Log failures to permanent storage.", "Send GPS coordinates.",
        ]}
        projection = _functional_translation_projection(item, {"B1": [{
            "source": "Send GPS coordinates.", "translation": "发送 GPS 坐标。",
        }]})
        self.assertEqual(projection["functional_behaviors_zh"], [
            "发送 GPS 坐标。", "Log failures to permanent storage.", "发送 GPS 坐标。",
        ])

    def test_merged_sentences_do_not_become_whole_paragraph_fallback(self):
        self.assertEqual(_translated_sentence(
            "Send GPS coordinates. Store failures.", "发送 GPS 坐标并存储故障。", "Store failures.",
        ), "")

    def test_missing_numeric_constraint_is_rejected(self):
        self.assertEqual(_translated_sentence(
            "Wire diameter shall be 2.5 mm.", "线径应为毫米。", "Wire diameter shall be 2.5 mm.",
        ), "")

    def test_ambiguous_match_is_rejected(self):
        self.assertEqual(_translated_sentence(
            "Send GPS coordinates daily. Send GPS coordinates hourly.",
            "每天发送 GPS 坐标。每小时发送 GPS 坐标。", "Send GPS coordinates",
        ), "")

    def test_real_numbered_list_preserves_decimals(self):
        self.assertEqual(_translated_sentence(
            "1. Send GPS coordinates. 2. Use a 2.5 mm wire.",
            "1. 发送 GPS 坐标。2. 使用 2.5 mm 密封线。", "Use a 2.5 mm wire.",
        ), "2. 使用 2.5 mm 密封线。")


if __name__ == "__main__":
    unittest.main()
