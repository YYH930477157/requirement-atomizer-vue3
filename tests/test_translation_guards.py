"""Tests for translation guardrails (WS-C4)."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from api_server import (
    TRANSLATION_LANGUAGE_REQUIREMENTS,
    TRANSLATION_PROMPT_VERSION,
    TRANSLATION_SYSTEM_PROMPT,
    translate_requirement_text,
)
from llm_client import LLMResponseError


class TranslationGuardTests(unittest.TestCase):
    def test_prompt_version_constant_registered(self):
        from prompt_registry import is_registered
        self.assertEqual(TRANSLATION_PROMPT_VERSION, "translation-prompt-v3")
        self.assertTrue(is_registered(TRANSLATION_PROMPT_VERSION))

    def test_system_prompt_includes_shared_language_requirements(self):
        self.assertIn(TRANSLATION_LANGUAGE_REQUIREMENTS, TRANSLATION_SYSTEM_PROMPT)
        self.assertIn("使用规范中文书面语", TRANSLATION_SYSTEM_PROMPT)
        self.assertIn("meter 译「电表」", TRANSLATION_SYSTEM_PROMPT)

    @patch("api_server.chat_json")
    @patch("api_server.load_review_pipeline")
    @patch("api_server.llm_config_from_route")
    def test_translation_preserves_obis_code(self, mock_cfg, mock_load, mock_chat):
        """C4：受保护编码（OBIS）必须在译文中逐字保留。"""
        mock_cfg.return_value = {}
        mock_load.return_value.model_routes = {"openai_compatible": {}}
        mock_chat.return_value = {
            "translation": "电表应支持 0-0:96.1.0 对象。",
            "protected_codes": "0-0:96.1.0",
        }
        result = translate_requirement_text(
            "The meter shall support the 0-0:96.1.0 object.", requirement_id="R1"
        )
        self.assertIn("0-0:96.1.0", result)

    @patch("api_server.chat_json")
    @patch("api_server.load_review_pipeline")
    @patch("api_server.llm_config_from_route")
    def test_translation_obis_drift_raises(self, mock_cfg, mock_load, mock_chat):
        """C4：译文丢失受保护 OBIS 编码时必须报错（硬拦漂移）。"""
        mock_cfg.return_value = {}
        mock_load.return_value.model_routes = {"openai_compatible": {}}
        mock_chat.return_value = {
            "translation": "电表应支持该对象。",  # OBIS code dropped
            "protected_codes": "0-0:96.1.0",
        }
        with self.assertRaises(LLMResponseError) as ctx:
            translate_requirement_text(
                "The meter shall support the 0-0:96.1.0 object.", requirement_id="R1"
            )
        self.assertIn("drift", str(ctx.exception).lower())

    @patch("api_server.chat_json")
    @patch("api_server.load_review_pipeline")
    @patch("api_server.llm_config_from_route")
    def test_translation_preserves_numeric_value(self, mock_cfg, mock_load, mock_chat):
        """P0-7：受保护数值必须在译文中逐字保留。"""
        mock_cfg.return_value = {}
        mock_load.return_value.model_routes = {"openai_compatible": {}}
        mock_chat.return_value = {
            "translation": "超时时间为 900 s。",
            "protected_codes": "900 s",
        }
        result = translate_requirement_text(
            "The timeout shall be 900 s.", requirement_id="R1"
        )
        self.assertIn("900", result)

    @patch("api_server.chat_json")
    @patch("api_server.load_review_pipeline")
    @patch("api_server.llm_config_from_route")
    def test_translation_numeric_drift_raises(self, mock_cfg, mock_load, mock_chat):
        """P0-7：译文丢失受保护数值时必须报错（硬拦漂移）。"""
        mock_cfg.return_value = {}
        mock_load.return_value.model_routes = {"openai_compatible": {}}
        mock_chat.return_value = {
            "translation": "超时时间为 60 s。",
            "protected_codes": "900 s",
        }
        with self.assertRaises(LLMResponseError) as ctx:
            translate_requirement_text(
                "The timeout shall be 900 s.", requirement_id="R1"
            )
        self.assertIn("drift", str(ctx.exception).lower())

    @patch("api_server.chat_json")
    @patch("api_server.load_review_pipeline")
    @patch("api_server.llm_config_from_route")
    def test_translation_preserves_physical_unit(self, mock_cfg, mock_load, mock_chat):
        """P0-7：受保护物理单位符号必须在译文中逐字保留。"""
        mock_cfg.return_value = {}
        mock_load.return_value.model_routes = {"openai_compatible": {}}
        mock_chat.return_value = {
            "translation": "额定电压为 230 V。",
            "protected_codes": "230 V",
        }
        result = translate_requirement_text(
            "The rated voltage shall be 230 V.", requirement_id="R1"
        )
        self.assertIn("V", result)

    @patch("api_server.chat_json")
    @patch("api_server.load_review_pipeline")
    @patch("api_server.llm_config_from_route")
    def test_translation_unit_drift_raises(self, mock_cfg, mock_load, mock_chat):
        """P0-7：译文丢失受保护单位时必须报错（硬拦漂移）。"""
        mock_cfg.return_value = {}
        mock_load.return_value.model_routes = {"openai_compatible": {}}
        mock_chat.return_value = {
            "translation": "额定电压为 230。",
            "protected_codes": "230 V",
        }
        with self.assertRaises(LLMResponseError) as ctx:
            translate_requirement_text(
                "The rated voltage shall be 230 V.", requirement_id="R1"
            )
        self.assertIn("drift", str(ctx.exception).lower())

    @patch("api_server.chat_json")
    @patch("api_server.load_review_pipeline")
    @patch("api_server.llm_config_from_route")
    def test_translation_response_includes_protected_codes(self, mock_cfg, mock_load, mock_chat):
        """P0-7：API 响应携带 protected_codes，中英对照可见。"""
        mock_cfg.return_value = {}
        mock_load.return_value.model_routes = {"openai_compatible": {}}
        mock_chat.return_value = {
            "translation": "电表应支持 0-0:96.1.0 对象，电压为 230 V。",
            "protected_codes": "0-0:96.1.0 230 V",
        }
        from api_server import _protected_codes
        protected = _protected_codes("The meter shall support the 0-0:96.1.0 object at 230 V.")
        self.assertIn("0-0:96.1.0", protected)
        self.assertIn("230", protected)
        self.assertIn("V", protected)


if __name__ == "__main__":
    unittest.main()
