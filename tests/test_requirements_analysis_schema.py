from types import SimpleNamespace

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


def test_apply_ownership_override_accepts_attribute_state():
    item = {"ownership": "hardware", "ownership_source": "rule", "notes": []}
    state = SimpleNamespace(ownership_override="software", reason="软件侧实现")

    updated = apply_ownership_override(item, state)

    assert updated["ownership"] == "software"
    assert updated["ownership_source"] == "reviewer_override"
    assert updated["ownership_confidence"] == 1.0


def test_apply_ownership_override_without_previous_ownership_does_not_add_override_note():
    item = {"notes": []}
    state = {"ownership_override": "software", "reason": "人工补充归属"}

    updated = apply_ownership_override(item, state)

    assert updated["ownership"] == "software"
    assert updated["notes"] == []


def test_apply_ownership_override_normalizes_existing_notes_before_append():
    item = {"ownership": "hardware", "notes": None}
    state = {"ownership_override": "software"}

    updated = apply_ownership_override(item, state)

    assert updated["notes"] == ["规则或 LLM 判断被人工归属覆盖"]


def test_apply_ownership_override_compares_normalized_previous_ownership():
    item = {"ownership": "软件", "notes": []}
    state = {"ownership_override": "software"}

    updated = apply_ownership_override(item, state)

    assert updated["ownership"] == "software"
    assert updated["notes"] == []


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


def test_validate_analysis_item_rejects_malformed_shapes():
    item = {
        "analysis_id": "ANREQ-x",
        "ownership": "software",
        "source_requirement_ids": "AI-1",
        "source_block_ids": 123,
    }

    issues = validate_analysis_item(item)

    assert "analysis_id must match ANREQ-000000" in issues
    assert "source_requirement_ids must be a list" in issues
    assert "source_block_ids must be a list" in issues
