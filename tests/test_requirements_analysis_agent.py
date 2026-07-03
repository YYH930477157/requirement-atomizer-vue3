from requirements_analysis_agent import build_analysis_prompt, validate_llm_item


def test_prompt_mentions_template_and_no_translation_only_rule():
    req = {"ai_req_id": "AI-1", "description": "支持夏令时", "source_quote": "shall support daylight saving"}
    vocab = {"modules": ["时钟需求"], "submodules_by_module": {"时钟需求": ["时钟"]}}

    prompt = build_analysis_prompt([req], vocab)

    assert "电表软件需求分析工程师" in prompt["system"]
    assert "不能只翻译" in prompt["user"]
    assert "时钟需求" in prompt["user"]


def test_validate_llm_item_rejects_number_drift():
    source = {"source_quote": "capture period shall be 900 seconds"}
    item = {
        "ownership": "software",
        "software_requirement_text": "系统应支持 600 seconds 捕获周期。",
        "source_requirement_ids": ["AI-1"],
    }

    issues = validate_llm_item(item, source)

    assert "source number 900 missing from analysis text" in issues
