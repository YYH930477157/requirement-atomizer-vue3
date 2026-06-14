from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import yaml

from gui import llm_settings


SAMPLE_YAML = {
    "schema_version": "0.2",
    "model_routes": {
        "default": "stub",
        "openai_compatible": {
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen2.5:14b",
            "api_key_env": "RATOMIZER_LLM_API_KEY",
            "temperature": 0.0,
            "max_tokens": 1024,
            "timeout_s": 60.0,
            "max_retries": 3,
            "concurrency": 4,
        },
    },
    "review_scope": {"mode": "targeted", "confidence_below": 0.75},
    "risk_policy": {"high_risk_types": ["security_policy_bit"]},
}


class LlmSettingsTests(unittest.TestCase):
    def _write_sample(self, tmp: str) -> Path:
        path = Path(tmp) / "review_pipeline.yaml"
        path.write_text(yaml.safe_dump(SAMPLE_YAML, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return path

    def test_load_reflects_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = llm_settings.load_llm_settings(self._write_sample(tmp))
            self.assertFalse(settings.enabled)  # default == stub
            self.assertEqual(settings.model, "qwen2.5:14b")
            self.assertEqual(settings.review_mode, "targeted")
            self.assertEqual(settings.max_tokens, 1024)
            self.assertEqual(settings.api_key_env, "RATOMIZER_LLM_API_KEY")

    def test_save_roundtrip_preserves_keys_and_never_writes_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_sample(tmp)
            settings = llm_settings.load_llm_settings(path)
            settings.enabled = True
            settings.model = "glm-4"
            settings.review_mode = "all"
            llm_settings.save_llm_settings(settings, path)

            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(data["model_routes"]["default"], "openai_compatible")
            self.assertEqual(data["model_routes"]["openai_compatible"]["model"], "glm-4")
            self.assertEqual(data["review_scope"]["mode"], "all")
            # 未触及的键保留
            self.assertEqual(data["model_routes"]["openai_compatible"]["concurrency"], 4)
            self.assertIn("risk_policy", data)
            # 永不写入密钥本体
            self.assertNotIn("api_key", data["model_routes"]["openai_compatible"])
            self.assertNotIn("sk-", path.read_text(encoding="utf-8"))

    def test_session_key_goes_to_env_only_and_is_masked(self) -> None:
        env_name = "RATOMIZER_TEST_KEY_X"
        os.environ.pop(env_name, None)
        self.assertFalse(llm_settings.api_key_is_set(env_name))
        llm_settings.set_session_api_key(env_name, "sk-secret-1234567890")
        try:
            self.assertTrue(llm_settings.api_key_is_set(env_name))
            masked = llm_settings.masked_api_key(env_name)
            self.assertNotIn("sk-secret-1234567890", masked)
            self.assertTrue(masked)
        finally:
            os.environ.pop(env_name, None)

    def test_dialog_constructs_and_collects(self) -> None:
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            self.skipTest("PySide6 not installed")
        from gui.settings_dialog import SettingsDialog

        QApplication.instance() or QApplication([])
        dialog = SettingsDialog()
        collected = dialog.collect()
        self.assertIn(collected.review_mode, ("targeted", "all"))
        self.assertIsInstance(collected.max_tokens, int)
        self.assertTrue(collected.api_key_env)

    def test_test_chat_handles_unreachable_endpoint(self) -> None:
        env = "RATOMIZER_TEST_NOKEY"
        os.environ.pop(env, None)
        ok, message = llm_settings.test_chat("http://127.0.0.1:1/v1", "demo", env, timeout_s=2.0)
        self.assertFalse(ok)
        self.assertIn("连接失败", message)

    def test_dialog_has_functional_test(self) -> None:
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            self.skipTest("PySide6 not installed")
        from gui.settings_dialog import SettingsDialog

        QApplication.instance() or QApplication([])
        dialog = SettingsDialog()
        self.assertTrue(callable(getattr(dialog, "run_test", None)))


if __name__ == "__main__":
    unittest.main()
