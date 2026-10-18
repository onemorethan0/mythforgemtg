"""Role-count questions in the Deck Mentor (2026-10-18).

Live, on a real Vraska, Soul of Stone deck: "For each role, how many cards do I run versus the
target? Which role is most under-supplied?" was answered with a resilience swap and not one role
count, though get_deck_stats had returned the table. Underneath sat a units defect: the table
printed card COUNTS beside STRENGTH targets (a wipe weighs 3.0), so "2 wipes vs target 6" read as
a gap for a deck at the typical 2. Pinned here: the card-unit targets, the role_summary the tool
returns, the routing (get_deck_stats is fetched before the model writes), and gate check 15.
"""

from types import SimpleNamespace

import pytest

from mythgauntlet.mentor import chat, gate, verdicts as v
from mythgauntlet.mentor.tools import ToolResult, role_summary
from mythgauntlet.ratings import redundancy


# ── card-unit targets ────────────────────────────────────────────────────────────────

def test_card_targets_cover_every_role_and_are_counts_not_strengths():
    assert set(redundancy.ROLE_CARD_TARGETS) == set(redundancy.ROLE_TARGETS)
    # a wipe / counterspell / tutor is ONE card, whatever its strength weight
    assert redundancy.ROLE_CARD_TARGETS["wipe"] < redundancy.ROLE_TARGETS["wipe"]
    assert redundancy.ROLE_CARD_TARGETS["counterspell"] < redundancy.ROLE_TARGETS["counterspell"]
    assert all(t >= 1 for t in redundancy.ROLE_CARD_TARGETS.values())


def test_archetype_card_cells_are_exactly_the_strength_tables_cells():
    strength = {(t, r) for t, cells in redundancy.ARCHETYPE_ROLE_TARGETS.items() for r in cells}
    cards = {(t, r) for t, cells in redundancy.ARCHETYPE_ROLE_CARD_TARGETS.items() for r in cells}
    assert cards == strength


def test_card_targets_for_merges_archetypes_by_max_and_zeroes_unplayable_colours():
    base = redundancy.card_targets_for(None)
    assert base == redundancy.ROLE_CARD_TARGETS
    spells = redundancy.card_targets_for(["spellslinger"])
    assert spells["counterspell"] == max(base["counterspell"],
                                         redundancy.ARCHETYPE_ROLE_CARD_TARGETS["spellslinger"]["counterspell"])
    golgari = redundancy.card_targets_for(["spellslinger"], color_identity=["B", "G"])
    assert golgari["counterspell"] == 0          # colour rule beats the archetype raise
    assert golgari["wipe"] == base["wipe"]       # B can wipe
    assert redundancy.card_targets_for(None, color_identity=[]) == base   # empty = unknown


# ── role_summary ─────────────────────────────────────────────────────────────────────

def _roles(**kw):
    out = {}
    for role, (cards, target, applicable) in kw.items():
        out[role] = {"cards": cards, "card_target": target, "applicable": applicable}
    return out


def test_role_summary_ranks_by_cards_short_then_share_filled():
    s = role_summary(_roles(ramp=(13, 12, True), draw=(7, 11, True), removal=(2, 7, True),
                            tutor=(0, 1, True), wipe=(2, 2, True)))
    assert s["unit"] == "cards"
    assert s["under_target"] == ["removal", "draw", "tutor"]
    assert s["most_under_supplied"] == "removal"
    assert {r["role"]: r["short_by"] for r in s["rows"]}["ramp"] == 0


def test_role_summary_never_names_a_not_applicable_role():
    s = role_summary(_roles(counterspell=(0, 0, False), removal=(6, 7, True)))
    assert s["most_under_supplied"] == "removal"
    assert [r["role"] for r in s["rows"]] == ["removal"]
    assert [r["role"] for r in s["not_applicable"]] == ["counterspell"]


def test_role_summary_with_nothing_under_target():
    s = role_summary(_roles(ramp=(13, 12, True)))
    assert s["most_under_supplied"] is None and s["under_target"] == []


# ── question detection ───────────────────────────────────────────────────────────────

LIVE_Q1 = ("For each role (ramp, card draw, removal, board wipes, counterspells, finishers), how "
           "many cards do I run versus the target? Which role is most under-supplied, and which "
           "cards should I cut?")
LIVE_Q2 = "What does this deck need the most of, in terms of ramp/draw/finishers/etc.?"


@pytest.mark.parametrize("q", [LIVE_Q1, LIVE_Q2])
def test_the_live_questions_are_broad_role_questions(q):
    assert v.is_role_question(q) and v.is_broad_role_question(q)


def test_a_one_role_count_question_owes_only_that_role():
    rows = role_summary(_roles(ramp=(13, 12, True), removal=(2, 7, True)))["rows"]
    assert v.roles_owed("How many removal spells do I run vs the target?", rows) == ["removal"]
    assert not v.is_broad_role_question("How many removal spells do I run vs the target?")


def test_a_broad_question_owes_every_core_role_the_deck_can_play():
    rows = role_summary(_roles(ramp=(13, 12, True), removal=(2, 7, True), tutor=(0, 1, True),
                               counterspell=(0, 0, False)))["rows"]
    assert v.roles_owed(LIVE_Q2, rows) == ["ramp", "removal"]   # tutor not core, cs n/a


def test_a_one_role_supply_question_is_narrow():
    """mentor_bench's own case: it asks about ramp only, so it owes the ramp row (with its
    target), not the whole table."""
    q = "Is my ramp over-supplied compared to what similar decks run?"
    assert v.is_role_question(q) and not v.is_broad_role_question(q) and v.targets_owed(q)
    assert v.is_broad_role_question("Is my deck under-supplied anywhere?")


def test_a_plain_count_question_owes_counts_not_targets():
    """mentor_bench: "How many removal spells and board wipes do I have between them?" is
    answered by the two counts; demanding targets would reject an honest reply."""
    q = "How many removal spells and board wipes do I have between them?"
    assert v.is_role_question(q) and not v.is_broad_role_question(q) and not v.targets_owed(q)
    rows = role_summary(_roles(removal=(2, 7, True), wipe=(2, 2, True)))["rows"]
    assert v.roles_owed(q, rows) == ["removal", "wipe"]
    summary = role_summary(_roles(removal=(2, 7, True), wipe=(2, 2, True)))
    assert gate.role_report_reasons("You run 2 removal spells and 2 board wipes.", q, summary) == []
    assert gate.role_report_reasons("You run 2 removal spells.", q, summary)


def test_need_question_naming_one_role_is_narrow():
    q = "What is my deck missing in terms of finishers?"
    assert v.is_role_question(q) and not v.is_broad_role_question(q)


def test_noncreature_removal_is_not_read_as_removal():
    assert [r for _, _, r in v.role_mentions("noncreature removal: 1")] == ["noncreature_removal"]


# ── gate check 15 ────────────────────────────────────────────────────────────────────

SUMMARY = role_summary(_roles(ramp=(13, 12, True), draw=(7, 11, True), removal=(2, 7, True),
                              wipe=(2, 2, True), counterspell=(1, 1, True)))
GOOD = ("Ramp: 13 cards vs a target of 12. Card draw: 7 vs 11. Removal: 2 vs 7. Board wipes: 2 vs "
        "2. Counterspells: 1 vs 1. Removal is the role your deck needs most.")


def _budget(summary=SUMMARY):
    return gate.ClaimBudget.from_tool_results(
        [ToolResult(data={"roles": {}, "role_summary": summary})])


def test_budget_picks_up_the_role_summary_structurally():
    assert _budget().role_summary == SUMMARY
    assert gate.ClaimBudget.from_tool_results([ToolResult(data={"found": True})]).role_summary == {}


def test_check_15_passes_a_complete_report():
    assert gate.role_report_reasons(GOOD, LIVE_Q2, SUMMARY) == []


def test_check_15_rejects_the_live_axis_only_answer():
    bad = "Your deck is moderately resilient to board wipes (52/100); a swap measured +6 points."
    reasons = gate.role_report_reasons(bad, LIVE_Q1, SUMMARY)
    assert len(reasons) == 2 and all(gate.is_role_report_reason(r) for r in reasons)


def test_check_15_rejects_counts_paired_with_the_strength_targets():
    strength = GOOD.replace("Board wipes: 2 vs 2", "Board wipes: 2 vs 6")
    assert any("board wipes" in r for r in gate.role_report_reasons(strength, LIVE_Q2, SUMMARY))


def test_check_15_rejects_the_wrong_role_singled_out():
    wrong = GOOD.replace("Removal is the role your deck needs most.", "Draw is your biggest gap.")
    reasons = gate.role_report_reasons(wrong, LIVE_Q2, SUMMARY)
    assert reasons and "most under-supplied" in reasons[0]


def test_check_15_is_silent_off_topic_and_without_a_summary():
    assert gate.role_report_reasons("The deck is resilient.", "How does this deck win?", SUMMARY) == []
    assert gate.check("The deck is resilient to wipes, honestly.", gate.ClaimBudget(),
                      question=LIVE_Q2) == []


def test_role_table_paragraph_passes_its_own_check():
    para = gate.role_table_paragraph(SUMMARY)
    assert gate.role_report_reasons(para, LIVE_Q1, SUMMARY) == []
    assert gate.check(para, _budget(), question=LIVE_Q1, max_chars=gate.MAX_CHARS) == []


# ── chat routing ─────────────────────────────────────────────────────────────────────

def _stats_data():
    return {"roles": {"removal": {"cards": 2, "card_target": 7, "applicable": True}},
            "role_summary": SUMMARY}


def _run(monkeypatch, question, replies):
    calls, seen = [], []

    def fake_post(messages, *, model, temperature, max_tokens, timeout=120):
        seen.append(messages)
        return {"role": "assistant", "content": replies[min(len(seen) - 1, len(replies) - 1)]}

    def fake_tool(ctx, name, args):
        calls.append(name)
        return ToolResult(data=_stats_data() if name == "get_deck_stats" else {"found": True})

    monkeypatch.setattr(chat, "_post_chat", fake_post)
    monkeypatch.setattr(chat, "call_tool", fake_tool)
    reply = chat.ask(SimpleNamespace(all_card_names=frozenset()), question)
    return reply, calls, seen


def test_a_role_question_fetches_the_table_before_the_model_answers(monkeypatch):
    reply, calls, seen = _run(monkeypatch, LIVE_Q2, [GOOD])
    assert calls[0] == "get_deck_stats"
    first = seen[0]
    assert any(m.get("tool_call_id") == "auto-role-stats" for m in first)
    assert "removal 2 cards vs a target of 7" in first[-1]["content"]
    assert reply.gated and reply.text == GOOD


def test_other_questions_do_not_prefetch_the_table(monkeypatch):
    _reply, calls, _seen = _run(monkeypatch, "How does this deck win?", ["It wins by attacking."])
    assert "get_deck_stats" not in calls


def test_a_retry_is_told_to_keep_the_rest_of_the_answer(monkeypatch):
    swap_only = "The deck is resilient to wipes and I found no measured improvement."
    _reply, _calls, seen = _run(monkeypatch, LIVE_Q2, [swap_only, GOOD])
    retry = seen[1][-1]["content"]
    assert "removal 2 cards vs a target of 7" in retry and "do not drop it" in retry


def test_the_last_draft_gets_the_licensed_table_rather_than_the_fallback(monkeypatch):
    swap_only = "The deck is resilient to wipes and I found no measured improvement."
    reply, _calls, _seen = _run(monkeypatch, LIVE_Q2, [swap_only])
    assert reply.gated is True
    assert reply.text.startswith(gate.role_table_paragraph(SUMMARY))
    assert reply.text.endswith(swap_only)
    assert len(reply.gate_rejections) == chat.MAX_GATE_ATTEMPTS
