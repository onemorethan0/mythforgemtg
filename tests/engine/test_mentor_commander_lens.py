"""The Deck Mentor reads the commander lens: list_deck_cards shows each card's commander synergy,
diagnose suppresses the wipe lever for a commander that survives the wipe, and gate check 16
rejects a "synergises with your commander" claim no lens fact backs (offline, synthetic cards;
oracle texts verbatim from the card store via tests/engine/test_commander_lens.py)."""

from dataclasses import replace

import pytest

from mythgauntlet.data.scryfall import CardDb
from mythgauntlet.mentor import chat, gate, tools as tools_mod, verdicts
from mythgauntlet.mentor.gate import ClaimBudget
from mythgauntlet.mentor.tools import (
    MentorContext, ToolResult, tool_diagnose_axis, tool_get_deck_stats, tool_list_deck_cards,
)
from mythgauntlet.model.deck import Deck, ResolvedDeck
from mythgauntlet.ratings import redundancy
from mythgauntlet.sim.tier0 import SimConfig

from tests.engine.test_commander_lens import BLASPHEMOUS, SMAUG, WRATH

WIPE_LEVER = "A board wipe sets the deck back a lot"


@pytest.fixture(autouse=True)
def _fresh_analysis_cache():
    tools_mod._analysis_cache_clear()
    yield
    tools_mod._analysis_cache_clear()


def _ctx(make_card, empty_store, commander):
    act = make_card(**BLASPHEMOUS, colors=("R",), color_identity=("R",))
    wrath = make_card(**WRATH, colors=("W",), color_identity=("W",))
    rock = make_card("Mana Ring", mana_cost="{1}", type_line="Artifact",
                     oracle_text="{T}: Add {C}{C}.", produced_mana=("C",))
    mountain = make_card("Mountain", type_line="Basic Land — Mountain", produced_mana=("R",),
                         color_identity=("R",))
    swamp = make_card("Swamp", type_line="Basic Land — Swamp", produced_mana=("B",),
                      color_identity=("B",))
    resolved = ResolvedDeck(
        deck=Deck(name="t"), commanders=[commander],
        cards=[(act, 1), (wrath, 1), (rock, 8), (mountain, 20), (swamp, 18)], missing=[])
    return MentorContext(
        card_db=CardDb([commander, act, wrath, rock, mountain, swamp]), cr=None, rulings_db={},
        resolved=resolved, cfg=SimConfig(turns=6, runs=8, seed=1), store=empty_store)


def _smaug(make_card):
    return make_card(**SMAUG, colors=("B", "R"), color_identity=("B", "R"))


def _vanilla(make_card):
    return make_card("Plain Legend", mana_cost="{2}{B}{R}",
                     type_line="Legendary Creature — Human", power="4", toughness="4",
                     colors=("B", "R"), color_identity=("B", "R"))


def test_list_cards_shows_synergy(make_card, empty_store):
    ctx = _ctx(make_card, empty_store, _smaug(make_card))
    data = tool_list_deck_cards(ctx).data
    rows = {r["name"]: r for r in data["cards"]}
    assert rows["Blasphemous Act"]["commander_synergy"] is not None
    assert rows["Blasphemous Act"]["commander_synergy"]["kind"] == "damage_to_self_payoff"
    assert "damage_to_self_payoff" in data["commander_lens_kinds"]
    assert "survives_wipe" in data["commander_lens_kinds"]


def test_list_cards_vanilla_legend_has_no_lens(make_card, empty_store):
    data = tool_list_deck_cards(_ctx(make_card, empty_store, _vanilla(make_card))).data
    assert data["commander_lens_kinds"] == []
    assert all(r["commander_synergy"] is None for r in data["cards"])


def test_deck_stats_role_table_reads_the_lens(make_card, empty_store):
    ctx = _ctx(make_card, empty_store, _smaug(make_card))
    stats = tool_get_deck_stats(ctx).data
    lens = tools_mod._lens_for(ctx)
    assert stats["roles"]["ramp"]["cards"] == redundancy.role_card_counts(
        ctx.resolved, lens).get("ramp", 0)
    # Blasphemous Act is ramp only through the lens (one-shot Treasure)
    assert stats["roles"]["ramp"]["cards"] == redundancy.role_card_counts(
        ctx.resolved).get("ramp", 0) + 1


def _weak_resilience(monkeypatch):
    """Force the resilience score into the weak band so the lever's ONLY gate is `requires`."""
    real = tools_mod._analysis_for

    def fake(ctx):
        a = real(ctx)
        return replace(a, resilience=replace(a.resilience, resilience_score=5.0))
    monkeypatch.setattr(tools_mod, "_analysis_for", fake)


def test_resilience_wipe_lever_suppressed_for_indestructible(make_card, empty_store, monkeypatch):
    _weak_resilience(monkeypatch)
    smaug = tool_diagnose_axis(_ctx(make_card, empty_store, _smaug(make_card)), "resilience").data
    assert smaug["found"] is True
    assert not any(t.startswith(WIPE_LEVER) for t in smaug["levers"])
    tools_mod._analysis_cache_clear()
    plain = tool_diagnose_axis(_ctx(make_card, empty_store, _vanilla(make_card)),
                               "resilience").data
    assert any(t.startswith(WIPE_LEVER) for t in plain["levers"])


def test_diagnose_facts_carry_folds_to_wipe(make_card, empty_store):
    ctx = _ctx(make_card, empty_store, _smaug(make_card))
    assert tools_mod._diagnose_facts(ctx, tools_mod._analysis_for(ctx))[
        "commander_folds_to_wipe"] is False
    ctx2 = _ctx(make_card, empty_store, _vanilla(make_card))
    assert tools_mod._diagnose_facts(ctx2, tools_mod._analysis_for(ctx2))[
        "commander_folds_to_wipe"] is True


# -- gate check 16 --------------------------------------------------------------------------

BODY = "Wrath of God has great synergy with your commander."


def _check16(reasons):
    return [r for r in reasons if "no lens fact" in r]


def test_gate_rejects_unbacked_synergy_claim():
    budget = ClaimBudget(card_names=frozenset({"Wrath of God"}),
                         synergy_cards=frozenset({"Blasphemous Act"}))
    reasons = _check16(gate.check(BODY, budget))
    assert reasons == ["claims 'Wrath of God' synergises with the commander; no lens fact backs it"]


def test_gate_accepts_backed_synergy_claim():
    budget = ClaimBudget(card_names=frozenset({"Wrath of God", "Blasphemous Act"}),
                         synergy_cards=frozenset({"Blasphemous Act"}))
    body = BODY.replace("Wrath of God", "Blasphemous Act")
    assert _check16(gate.check(body, budget)) == []


def test_budget_collects_synergy_cards_and_commanders_from_rows():
    rows = [{"name": "Smaug the Impenetrable", "qty": 1, "commander": True,
             "commander_synergy": None},
            {"name": "Blasphemous Act", "qty": 1, "commander_synergy": {
                "kind": "damage_to_self_payoff", "reason": "r", "one_sided": False,
                "treasure": 13}},
            {"name": "Wrath of God", "qty": 1, "commander_synergy": None}]
    budget = ClaimBudget.from_tool_results([ToolResult(data={"found": True, "cards": rows})])
    assert budget.synergy_cards == frozenset({"Blasphemous Act"})
    assert "Smaug the Impenetrable" in budget.commander_names
    # the commander named by its short name is a commander reference
    reasons = _check16(gate.check("Wrath of God triggers Smaug every time.", budget))
    assert reasons and "Wrath of God" in reasons[0]


def test_synergy_claims_vocabulary():
    names = ("Smaug the Impenetrable",)
    f = verdicts.commander_synergy_claims
    assert f("Blasphemous Act triggers Smaug for a pile of Treasure.", names) == ["Blasphemous Act"]
    assert f("Wrath of God works well with your commander.", names) == ["Wrath of God"]
    assert f("Sol Ring combos with Smaug the Impenetrable.", names) == ["Sol Ring"]
    assert f("Command Tower works with your mana base.", names) == []
    assert f("It has real synergy with your commander.", names) == []
    assert f("Wrath of God does not synergize with your commander.", names) == []
    # only the synergy verb's own clause is claimed; a bare list subject claims every card
    assert f("Lightning Bolt handles blockers, and Blasphemous Act triggers Smaug.",
             names) == ["Blasphemous Act"]
    assert f("Your best wipe is Damnation, which synergizes with the commander.",
             names) == ["Damnation"]
    assert f("Blasphemous Act and Wrath of God both trigger Smaug.",
             names) == ["Blasphemous Act", "Wrath of God"]


def test_gate_does_not_reject_a_card_in_another_clause():
    budget = ClaimBudget(card_names=frozenset({"Lightning Bolt", "Blasphemous Act"}),
                         synergy_cards=frozenset({"Blasphemous Act"}))
    body = "Lightning Bolt handles blockers, and Blasphemous Act triggers Smaug."
    assert _check16(gate.check(body, replace(budget, commander_names=frozenset(
        {"Smaug the Impenetrable"})))) == []


# -- the lens fact reaches a cut question deterministically (Task 8 review, CRITICAL 1) ---------
# Live 2026-10-19 "should I cut Blasphemous Act?" on a Smaug deck: the model called lookup_card,
# check_legality and suggest_swap -- none carried the lens fact -- and answered with a swap-search
# template. qwen3:14b ignores prompt-only rules, so the fact is put in front of it in code.

CUT_Q = "should I cut Blasphemous Act?"


def test_lookup_card_carries_synergy_for_a_deck_card(make_card, empty_store):
    ctx = _ctx(make_card, empty_store, _smaug(make_card))
    data = tools_mod.tool_lookup_card(ctx, "Blasphemous Act").data
    assert data["commander_synergy"]["kind"] == "damage_to_self_payoff"
    assert data["commander_synergy"]["treasure"] >= 0
    assert "Smaug the Impenetrable" in data["commander_synergy"]["reason"]
    assert data["commanders"] == [{"name": "Smaug the Impenetrable"}]


def test_lookup_card_has_no_synergy_off_deck_or_without_a_lens(make_card, empty_store):
    ctx = _ctx(make_card, empty_store, _smaug(make_card))
    bolt = make_card("Lightning Bolt", mana_cost="{R}", type_line="Instant",
                     oracle_text="Lightning Bolt deals 3 damage to any target.",
                     colors=("R",), color_identity=("R",))
    ctx = replace(ctx, card_db=CardDb(list(ctx.card_db._by_name.values()) + [bolt]))
    assert "commander_synergy" not in tools_mod.tool_lookup_card(ctx, "Lightning Bolt").data
    plain = _ctx(make_card, empty_store, _vanilla(make_card))
    assert "commander_synergy" not in tools_mod.tool_lookup_card(plain, "Blasphemous Act").data


def _prefetched(ctx, question):
    tool_trace, all_results, messages = [], [], []
    chat._prelookup_question_cards(ctx, question, ctx.all_card_names, tool_trace, all_results,
                                   messages)
    facts = chat._prefetch_commander_synergy(ctx, question, tool_trace, all_results, messages)
    return facts, all_results, messages


def test_cut_question_prefetches_the_lens_fact_and_licenses_the_claim(make_card, empty_store):
    ctx = _ctx(make_card, empty_store, _smaug(make_card))
    facts, results, messages = _prefetched(ctx, CUT_Q)
    assert [f["card"] for f in facts] == ["Blasphemous Act"]
    assert facts[0]["kind"] == "damage_to_self_payoff"
    nudge = messages[-1]
    assert nudge["role"] == "user"
    assert "Blasphemous Act" in nudge["content"] and "Smaug the Impenetrable" in nudge["content"]
    budget = ClaimBudget.from_tool_results(results)
    assert "Blasphemous Act" in budget.synergy_cards
    assert "Smaug the Impenetrable" in budget.commander_names
    body = "No, keep it: Blasphemous Act triggers Smaug for a pile of Treasure."
    assert verdicts.commander_synergy_claims(body, sorted(budget.commander_names)) == [
        "Blasphemous Act"]
    assert gate.commander_synergy_reasons(body, budget) == []


def test_no_prefetch_nudge_without_a_lens_fact(make_card, empty_store):
    ctx = _ctx(make_card, empty_store, _vanilla(make_card))
    facts, _results, messages = _prefetched(ctx, CUT_Q)
    assert facts == []
    assert all("Commander lens" not in (m.get("content") or "") for m in messages)


def test_ask_puts_the_lens_fact_before_the_first_draft(make_card, empty_store, monkeypatch):
    ctx = _ctx(make_card, empty_store, _smaug(make_card))
    seen = []

    def fake_post(messages, **kw):
        seen.append([dict(m) for m in messages])
        return {"role": "assistant",
                "content": "No. Blasphemous Act triggers Smaug for a pile of Treasure."}

    monkeypatch.setattr(chat, "_post_chat", fake_post)
    chat.ask(ctx, CUT_Q)
    first = seen[0]
    assert any(m["role"] == "user" and "Commander lens" in (m.get("content") or "")
               and "Blasphemous Act" in m["content"] for m in first)
