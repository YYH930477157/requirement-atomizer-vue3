from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import doc_annotation_export as dae
from full_translation import full_translation_enabled

QUOTE = "The manufacturer shall place its trademark on the device."


def _seed_marker_block(out: Path, quote: str) -> None:
    (out / "blocks.jsonl").write_text(
        json.dumps({"block_id": "B1", "order": 1, "type": "paragraph", "text": quote,
                    "section_path": ["3 TERMS"], "requirement_like": False, "noise": False,
                    "doc_region": "body"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (out / "ai_requirements.jsonl").write_text("", encoding="utf-8")


@patch.dict(os.environ, {"RATOMIZER_TRANSLATE_BATCH": "0"})
class TranslationModeTests(unittest.TestCase):
    def _counting_chat(self, calls: list[str]):
        def chat(system: str, user: str) -> dict:
            calls.append(user)
            return {"items": [{"id": 1, "translation": "制造商应在设备上标注其商标。"}]}
        return chat

    def test_off_mode_makes_zero_provider_calls_even_with_real_route(self) -> None:
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, QUOTE)
            summary = dae.generate_annotation_translations(
                out, route="openai_compatible", chat=self._counting_chat(calls),
                translation_mode="off")
            self.assertEqual(calls, [])           # provider call counter 证明（§13）
            self.assertEqual(summary["translation_mode"], "off")
            self.assertEqual(summary["skipped_by_mode"], 1)
            self.assertEqual(summary["translated"], 0)
            # 未翻译不得虚标：sidecar 无采纳译文
            sidecar = dae._read_translation_sidecar(out)
            self.assertFalse(any(str(e.get("translation") or "").strip()
                                 for e in sidecar.values()))

    def test_markers_mode_keeps_existing_behavior(self) -> None:
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, QUOTE)
            summary = dae.generate_annotation_translations(
                out, route="openai_compatible", chat=self._counting_chat(calls),
                translation_mode="markers")
            self.assertEqual(len(calls), 1)
            self.assertEqual(summary["translated"], 1)
            self.assertNotEqual(summary["translation_mode"], "off")

    def test_full_mode_adopts_sidecar_with_zero_calls(self) -> None:
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, QUOTE)
            key = dae._translation_key(QUOTE)
            (out / "document_translations.jsonl").write_text(json.dumps({
                "translation_key": key,
                "translation": "制造商应在设备上标注其商标。",
                "rejected": False,
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            summary = dae.generate_annotation_translations(
                out, route="openai_compatible", chat=self._counting_chat(calls),
                translation_mode="full")
            self.assertEqual(calls, [])
            self.assertEqual(summary.get("adopted_from_full_sidecar"), 1)
            self.assertEqual(summary["translation_mode"], "full")
            sidecar = dae._read_translation_sidecar(out)
            self.assertEqual(sidecar[key]["provenance"], "full_translation_sidecar")
            self.assertEqual(sidecar[key]["translation"], "制造商应在设备上标注其商标。")

    def test_full_mode_does_not_adopt_guard_violating_translation(self) -> None:
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, QUOTE)
            key = dae._translation_key(QUOTE)
            # 译文引入原文没有的编码——护栏拦下，不采纳（宁漏勿错）
            (out / "document_translations.jsonl").write_text(json.dumps({
                "translation_key": key,
                "translation": "制造商应在设备上标注商标，编码 0-0:96.1.0.255。",
                "rejected": False,
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            summary = dae.generate_annotation_translations(
                out, route="openai_compatible", chat=self._counting_chat(calls),
                translation_mode="full")
            self.assertEqual(summary.get("adopted_from_full_sidecar", 0), 0)
            self.assertEqual(len(calls), 1)  # 回落 marker 路径

    def test_unknown_mode_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _seed_marker_block(out, QUOTE)
            with self.assertRaises(ValueError):
                dae.generate_annotation_translations(
                    out, route="stub", translation_mode="sometimes")

    def test_export_mode_env_default_maps_to_markers_compat(self) -> None:
        effective, requested = dae._resolve_export_translation_mode(None)
        self.assertEqual(effective, "markers")   # env 默认 full → 兼容既有行为
        self.assertEqual(requested, "full")
        with patch.dict(os.environ, {"RATOMIZER_TRANSLATION_MODE": "off"}):
            self.assertEqual(dae._resolve_export_translation_mode(None), ("off", "off"))
        self.assertEqual(dae._resolve_export_translation_mode("full"), ("full", "full"))

    def test_full_translation_disabled_under_off_and_markers_modes(self) -> None:
        with patch.dict(os.environ, {"RATOMIZER_TRANSLATION_MODE": "off"}):
            self.assertFalse(full_translation_enabled())
        with patch.dict(os.environ, {"RATOMIZER_TRANSLATION_MODE": "markers"}):
            self.assertFalse(full_translation_enabled())
        with patch.dict(os.environ, {"RATOMIZER_TRANSLATION_MODE": "full"}):
            self.assertTrue(full_translation_enabled())
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RATOMIZER_TRANSLATION_MODE", None)
            self.assertTrue(full_translation_enabled())   # 未设置=既有默认开


if __name__ == "__main__":
    unittest.main()
