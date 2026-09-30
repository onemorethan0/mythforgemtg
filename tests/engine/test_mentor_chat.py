"""mentor.chat -- prompt routing (A3) and output shape (A6). No live model: `_post_chat` is
stubbed where a loop is exercised."""

from mythgauntlet.mentor import chat


def test_system_prompt_routes_holistic_questions_to_the_power_profile():
    p = chat.SYSTEM_PROMPT
    assert "get_power_profile FIRST" in p
    # the verdict object is the thing the model must not argue against
    assert '"verdicts"' in p and "never argue against one" in p
    # the unit trap: role `supply` is a strength score, not a card count
    assert "strength score, not a card count" in p


def test_system_prompt_keeps_the_existing_rules():
    p = chat.SYSTEM_PROMPT
    for needle in ("check_legality", "suggest_swap", "get_bracket_estimate",
                   "NEVER state a card's oracle text", "SUBSET relationship"):
        assert needle in p
