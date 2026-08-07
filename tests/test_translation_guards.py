"""Tests for translation guardrails (WS-C4)."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from api_server import (
    TRANSLATION_PROMPT_VERSION,
    translate_requirement_text,
)
from llm_client import LLMResponseError


class TranslationGuardTests(unittest.TestCase):
    def test_prompt_version_constant_registered(self):
        from prompt_registry import is_registered
        self.assertTrue(is_registered(TRANSLATION_PROMPT_VERSION))

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
    def test_translation_drift_raises(self, mock_cfg, mock_load, mock_chat):
        """C4：译文丢失受保护编码时必须报错（硬拦漂移）。"""
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


if __name__ == "__main__":
    unittest.main()
