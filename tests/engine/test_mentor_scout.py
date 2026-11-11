"""Mentor B38 follow-up: `get_scouting_report` reads Forge's cached scouting report, never runs
the measurement, and a scouting / weak-against question gets it before the model writes."""

from types import SimpleNamespace

import pytest

from mythgauntlet.mentor import chat
from mythgauntlet.mentor.tools import TOOL_SCHEMAS, MentorContext, call_tool
from mythgauntlet.data.scryfall import CardDb
from mythgauntlet.model.deck import Deck, ResolvedDeck
from mythgauntlet.sim.tier0 import SimConfig
from tests.engine.test_mentor_measured_swaps import _fake_cr

REPORT = {
    "gameplan": "Test Commander: a midrange deck.",
    "weak_against": [{"text": "Wipes: 2 of 10 games recover", "source": "exposure"}],
    "caveats": ["Matchups against the reference field were not run."],
}


def _ctx(make_card, empty_store, scout=None) -> MentorContext:
    commander = make_card("Test Commander", type_line="Legendary Creature — Human",
                          mana_cost="{2}{G}", color_identity=("G",))
    forest = make_card("Forest", type_line="Basic Land — Forest", produced_mana=("G",),
                       color_identity=("G",))
    resolved = ResolvedDeck(deck=Deck(name="t"), commanders=[commander],
                            cards=[(forest, 35)], missing=[])
    return MentorContext(card_db=CardDb([commander, forest]), cr=_fake_cr(), rulings_db={},
                         resolved=resolved, cfg=SimConfig(turns=5, runs=10, seed=1),
                         store=empty_store, scout=scout)


def test_tool_is_registered():
    assert "get_scouting_report" in {s["function"]["name"] for s in TOOL_SCHEMAS}


def test_unavailable_without_a_cached_report(make_card, empty_store):
    data = call_tool(_ctx(make_card, empty_store), "get_scouting_report", {}).data
    assert data["available"] is False
    assert "Scout" in data["message"]


def test_available_report_licenses_its_numbers_and_names(make_card, empty_store):
    ctx = _ctx(make_card, empty_store, scout={"report": REPORT, "text": "Test Commander ..."})
    res = call_tool(ctx, "get_scouting_report", {})
    assert res.data["available"] is True and res.data["report"] == REPORT
    assert 10.0 in res.numbers and 2.0 in res.numbers
    assert "Test Commander" in res.card_names


@pytest.mark.parametrize("q", ["Give me a scouting report", "what is my deck weak against?",
                               "how does my deck stack up", "scout it"])
def test_scout_questions_match(q):
    assert chat._SCOUT_Q_RE.search(q)


def test_unrelated_question_does_not_match():
    assert not chat._SCOUT_Q_RE.search("What does Rhystic Study do?")


def test_prefetch_only_when_a_report_is_cached(make_card, empty_store):
    q = "what is my deck weak against?"
    for scout, expect in ((None, False), ({"report": REPORT, "text": ""}, True)):
        ctx = _ctx(make_card, empty_store, scout=scout)
        trace, results, msgs = [], [], []
        assert chat._prefetch_scouting_report(ctx, q, trace, results, msgs) is expect
        assert bool(trace) is expect
