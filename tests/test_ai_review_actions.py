from ai_review_actions import apply_ai_review_action, read_ai_review_states


def test_ai_review_action_persists_ownership_override(tmp_path):
    state = apply_ai_review_action(
        tmp_path,
        "AI-1",
        "accepted",
        module_override="时钟需求",
        ownership_override="co_design",
        reason="硬件 RTC 依赖需要确认",
        actor="tester",
    )

    assert state["ownership_override"] == "co_design"
    states = read_ai_review_states(tmp_path)
    assert states["AI-1"]["ownership_override"] == "co_design"
