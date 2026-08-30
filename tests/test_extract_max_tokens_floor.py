"""抽取用途 max_tokens floor 抬升（6144→24576）+ B 轨功能直抽接线。

SBD 付费运行实证（docs/outline-authority-validation-2026-08-29.md 成本账）：
deepseek-v4-flash 是推理模型，max_tokens 记**思考+答案**（241 调用 completion
分布被 4096/8192/16384 三档帽子整齐压住、p95=8191、无一超过 16384）——输出
token 88% 是隐藏思考。62/241 次调用因思考吃光预算触发"烧完-重来"倍升重试，
重复付费 ≈¥2/运行。且功能直抽（B 轨）从未接 apply_min_tokens（A 轨 ai_extract
与 claim_artifacts 都接了），一直用全局默认 4096 起步。

修复：PURPOSE_MIN_TOKENS["extract"] 抬到 24576（上限不是目标、按实际生成计费，
只省重试重复付费），functional_extract 路由解析处接 apply_min_tokens——单一
权威 PURPOSE_MIN_TOKENS，不在直抽里另写数字。
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import functional_extract as fe


class ExtractMaxTokensFloorTests(unittest.TestCase):
    def test_extract_floor_is_24576(self) -> None:
        from llm_client import PURPOSE_MIN_TOKENS

        self.assertEqual(PURPOSE_MIN_TOKENS["extract"], 24576)

    def test_floor_raises_low_config_without_lowering_high(self) -> None:
        from dataclasses import replace

        from llm_client import LLMClientConfig, apply_min_tokens

        base = LLMClientConfig(
            base_url="https://example.invalid", model="m",
            temperature=0.0, max_tokens=4096,
        )
        self.assertEqual(apply_min_tokens(base, "extract").max_tokens, 24576)
        high = replace(base, max_tokens=32768)
        self.assertEqual(apply_min_tokens(high, "extract").max_tokens, 32768)

    def test_functional_extract_chat_uses_extract_floor(self) -> None:
        """B 轨直抽的 chat 配置必须过 apply_min_tokens——不再 4096 裸奔。"""
        from dataclasses import replace

        from llm_client import LLMClientConfig

        fake_config = LLMClientConfig(
            base_url="https://api.example.invalid", model="m",
            temperature=0.0, max_tokens=4096,
        )
        captured: dict = {}

        def fake_config_for_route(route, pipeline_path, **kwargs):
            return replace(fake_config)

        def fake_chat_json(config, system, user, **kwargs):
            captured["max_tokens"] = config.max_tokens
            return {"items": []}

        with patch("ai_extract.config_for_route", side_effect=fake_config_for_route), \
                patch("llm_client.chat_json", side_effect=fake_chat_json), \
                patch.dict("os.environ", {"RATOMIZER_LLM_API_KEY": "test-key"}):
            invoke, _label = fe._resolve_extract_chat("openai_compatible", None)
            self.assertIsNotNone(invoke)
            invoke("sys", "user")
        self.assertEqual(captured["max_tokens"], 24576)


if __name__ == "__main__":
    unittest.main()
