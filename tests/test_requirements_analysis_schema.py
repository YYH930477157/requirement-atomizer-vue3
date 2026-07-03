from requirements_analysis_schema import (
    apply_ownership_override,
    build_analysis_id,
    normalize_ownership,
    validate_analysis_item,
)


def test_normalize_ownership_accepts_supported_values():
    assert normalize_ownership("software") == "software"
    assert normalize_ownership("hardware") == "hardware"
    assert normalize_ownership("co_design") == "co_design"


def test_normalize_ownership_rejects_unknown_value():
    try:
        normalize_ownership("firmware")
    except ValueError as exc:
        assert "unknown ownership" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_apply_ownership_override_wins_over_existing_decision():
    item = {
        "ai_req_id": "AI-1",
        "ownership": "hardware",
        "ownership_source": "rule",
        "notes": [],
    }
    state = {"ownership_override": "software", "reason": "软件需要实现协议处理"}

    updated = apply_ownership_override(item, state)

    assert updated["ownership"] == "software"
    assert updated["ownership_source"] == "reviewer_override"
    assert "规则或 LLM 判断被人工归属覆盖" in updated["notes"][0]


def test_build_analysis_id_is_stable_and_prefixed():
    assert build_analysis_id(1) == "ANREQ-000001"
    assert build_analysis_id(42) == "ANREQ-000042"


def test_validate_analysis_item_requires_source_ids():
    item = {
        "analysis_id": "ANREQ-000001",
        "ownership": "software",
        "source_requirement_ids": [],
        "source_block_ids": ["B-1"],
    }

    issues = validate_analysis_item(item)

    assert issues == ["source_requirement_ids is required"]
