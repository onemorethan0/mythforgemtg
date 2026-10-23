"""The mentor gets measured castability odds before answering a casting question.

Live 2026-10-23, Doran deck: "Can I reliably cast Sign in Blood on turn 2?" -> "Yes, ... if
you have access to two black mana" (1.4 s, lookup_card only). With 17 black sources in 99
cards, {B}{B} by turn 2 is 41% with no mulligan - the manabase tool knew; the model never asked.
"""
from types import SimpleNamespace

from mythgauntlet.mentor import chat
from mythgauntlet.model.card import Card
from mythgauntlet.ratings import manabase


def _ctx(black_sources: int):
    sign = Card(name="Sign in Blood", mana_cost_str="{B}{B}", type_line="Sorcery",
                oracle_text="Target player draws two cards and loses 2 life.")
    swamp = Card(name="Swamp", type_line="Basic Land — Swamp", produced_mana=("B",))
    forest = Card(name="Forest", type_line="Basic Land — Forest", produced_mana=("G",))
    filler = Card(name="Grizzly Bears", mana_cost_str="{1}{G}", type_line="Creature — Bear",
                  power="2", toughness="2")
    cards = [(sign, 1), (swamp, black_sources), (forest, 20), (filler, 98 - 20 - black_sources)]
    resolved = SimpleNamespace(cards=cards, commanders=[])
    return SimpleNamespace(resolved=resolved, all_card_names={"Sign in Blood", "Swamp", "Forest",
                                                              "Grizzly Bears"})


def test_castability_question_runs_the_tool_before_the_model_writes():
    ctx, messages, trace = _ctx(17), [], []
    facts = chat._prefetch_castability(ctx, "Can I reliably cast Sign in Blood on turn 2?",
                                       trace, [], messages)
    want = manabase.hypergeom_at_least(99, 17, manabase.cards_seen(2), 2)
    assert facts and facts[0]["card"] == "Sign in Blood" and facts[0]["turn"] == 2
    assert facts[0]["probability"] == round(want, 2)
    assert facts[0]["verdict"] == "unreliable on this turn"     # 41% is not "reasonably likely"
    # A real tool round-trip, which the model and the gate both treat as measured data.
    assert messages[-2]["tool_calls"][0]["function"]["name"] == "card_castability"
    assert messages[-1]["role"] == "tool" and trace[-1].name == "card_castability"


def test_unrelated_question_fetches_nothing():
    ctx, messages = _ctx(17), []
    assert chat._prefetch_castability(ctx, "Should I cut Sign in Blood?", [], [], messages) == []
    assert messages == []
