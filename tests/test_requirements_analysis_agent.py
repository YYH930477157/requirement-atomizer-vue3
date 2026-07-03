"""requirements_analysis_agent 回归（unittest 风格——pytest 未装，模块级函数不会被 discover 收集）。"""
from __future__ import annotations

import unittest

from requirements_analysis_agent import build_analysis_prompt, validate_llm_item


class BuildAnalysisPromptTests(unittest.TestCase):
    def test_prompt_mentions_template_and_no_translation_only_rule(self) -> None:
        req = {"ai_req_id": "AI-1", "description": "支持夏令时", "source_quote": "shall support daylight saving"}
        vocab = {"modules": ["时钟需求"], "submodules_by_module": {"时钟需求": ["时钟"]}}

        prompt = build_analysis_prompt([req], vocab)

        assert "电表软件需求分析工程师" in prompt["system"]
        assert "不能只翻译" in prompt["user"]
        assert "时钟需求" in prompt["user"]


class ValidateLlmItemTests(unittest.TestCase):
    def test_rejects_number_drift(self) -> None:
        source = {"source_quote": "capture period shall be 900 seconds"}
        item = {
            "ownership": "software",
            "software_requirement_text": "系统应支持 600 seconds 捕获周期。",
            "source_requirement_ids": ["AI-1"],
        }

        issues = validate_llm_item(item, source)

        assert "source number 900 missing from analysis text" in issues
        # 600 是分析文本里源文没有的数字 → 编造硬伤（方向：产物 ⊆ 源）
        assert "fabricated number not in source: 600" in issues

    def test_uses_source_quote_before_description_for_missing_check(self) -> None:
        source = {
            "source_quote": "capture period shall be 900 seconds",
            "description": "fallback text mentions 600 seconds",
        }
        item = {"software_requirement_text": "系统应支持 900 seconds 捕获周期。"}

        issues = validate_llm_item(item, source)

        assert issues == []

    def test_compares_numbers_as_tokens(self) -> None:
        source = {"source_quote": "capture period shall be 90 seconds"}
        item = {"software_requirement_text": "系统应支持 900 seconds 捕获周期。"}

        issues = validate_llm_item(item, source)

        assert "source number 90 missing from analysis text" in issues

    def test_fabricated_number_is_hard_issue(self) -> None:
        """防幻觉主方向：分析文本冒出源文没有的数字必须被抓（此前护栏方向反了抓不到）。"""
        source = {"source_quote": "The meter shall do A."}
        item = {"software_requirement_text": "保存 99999 条记录。"}

        issues = validate_llm_item(item, source)

        assert any("fabricated number not in source: 99999" in issue for issue in issues)

    def test_transposed_obis_is_caught_atomically(self) -> None:
        """OBIS 错一位即严重：换位 OBIS 的数字片段集合相同，逐数字比对抓不到——须原子匹配整码。"""
        source = {"source_quote": "total energy at OBIS 1-0:1.8.0.255"}
        item = {"software_requirement_text": "读取 OBIS 0-1:1.8.0.255 的总电能。"}

        issues = validate_llm_item(item, source)

        assert any("fabricated code" in issue and "0-1:1.8.0.255" in issue for issue in issues)

    def test_description_numbers_are_legitimate_basis_for_fabrication(self) -> None:
        # description 里出现过的数字被分析引用不算编造（编造基线取并集）
        source = {"source_quote": "shall log events", "description": "keep 600 entries"}
        item = {"software_requirement_text": "事件记录保存 600 条。"}

        issues = validate_llm_item(item, source)

        assert not any("fabricated" in issue for issue in issues)


if __name__ == "__main__":
    unittest.main()
