"""Role-targeted swaps (2026-10-18): add an owned card for the under-supplied role, cut a card
whose every role is over its card target, measure every axis. Cards carry real oracle text so the
roles come out of the live `tags.analyze`; the simulation is stubbed where a test is about the
CHOICE, not the numbers (the numbers were measured on the Vraska repro deck, see the module)."""

import dataclasses
from types import SimpleNamespace

import pytest

from mythgauntlet.mentor import chat, gate, tools
from mythgauntlet.mentor.tools import ToolResult, role_summary
from mythgauntlet.model.deck import Deck, ResolvedDeck
from mythgauntlet.ratings import advisor, redundancy, role_swap

ROCK = ("{T}: Add {C}{C}.", "Artifact")
KILL = ("Exile target creature. Its controller gains life equal to its power.", "Instant")
DRAW = ("Draw two cards.", "Sorcery")
ROCK_AND_DRAW = ("{T}: Add {C}{C}.\n{2}, {T}: Draw a card.", "Artifact")
PET = ("Whenever a face-down creature you control is turned face up, scry 1.", "Enchantment")


def _card(make_card, name, spec, mv=2, rank=None):
    oracle, type_line = spec
    return make_card(name, type_line=type_line, oracle_text=oracle, edhrec_rank=rank,
                     mana_cost="{%d}" % mv)


def _deck(cards):
    return ResolvedDeck(deck=Deck(commanders=[], entries=[]), commanders=[],
                        cards=[(c, 1) for c in cards], missing=[])


@pytest.fixture
def deck(make_card):
    """ramp 3 (target 2: over), draw 1 (target 1: at), removal 0 (target 2: under)."""
    rocks = [_card(make_card, f"Rock {i}", ROCK, mv=i + 1) for i in range(2)]
    hybrid = _card(make_card, "Rock Engine", ROCK_AND_DRAW)
    pet = _card(make_card, "Pet Card", PET)
    return _deck([*rocks, hybrid, pet])


TARGETS = {"ramp": 2, "draw": 1, "removal": 2}
APPLICABLE = set(TARGETS)


def test_the_cut_pool_holds_only_cards_whose_every_role_is_over_target(deck):
    counts = redundancy.role_card_counts(deck)
    assert counts == {"ramp": 3, "draw": 1}
    pool = role_swap.role_cut_pool(deck, "removal", counts, TARGETS, APPLICABLE)
    names = [c.card.name for c in pool]
    # Rock Engine also fills draw, which is AT target: cutting it would open a draw gap.
    # Pet Card has no role: the role counts say nothing about it, so it is never offered.
    assert sorted(names) == ["Rock 0", "Rock 1"]
    assert all(c.role == "ramp" and c.cards == 3 and c.card_target == 2 for c in pool)


def test_no_over_target_role_means_no_cut(deck):
    counts = redundancy.role_card_counts(deck)
    assert role_swap.role_cut_pool(deck, "removal", counts, {**TARGETS, "ramp": 3},
                                   APPLICABLE) == []


def test_a_card_filling_the_target_role_is_never_cut(make_card):
    kills = [_card(make_card, f"Kill {i}", KILL) for i in range(3)]
    d = _deck(kills)
    counts = redundancy.role_card_counts(d)
    # removal is over a target of 1 here, but it is the role being added: never trade it away
    assert role_swap.role_cut_pool(d, "removal", counts, {"removal": 1}, {"removal"}) == []


def test_the_add_pool_is_owned_legal_role_fillers_outside_the_deck(deck, make_card):
    swords = _card(make_card, "Swords", KILL, mv=1)
    illegal = dataclasses.replace(_card(make_card, "Banned Kill", KILL), commander_legal=False)
    divination = _card(make_card, "Divination", DRAW)
    in_deck = deck.cards[0][0]
    adds = role_swap.role_add_pool(deck, "removal", [swords, illegal, divination, in_deck])
    assert [c.name for c in adds] == ["Swords"]


def _patch_sim(monkeypatch, scores_by_cut):
    """analyze_deck stub: axis scores keyed by which card the variant lacks."""
    base_scores = {ax: 50.0 for ax in advisor.AXES}

    def fake_analyze(resolved, cfg, store, **kw):
        names = {c.name for c, _ in resolved.cards}
        for cut, scores in scores_by_cut.items():
            if cut not in names:
                return SimpleNamespace(scores={**base_scores, **scores})
        return SimpleNamespace(scores=base_scores)

    monkeypatch.setattr(role_swap, "analyze_deck", fake_analyze)
    monkeypatch.setattr(advisor, "axis_score", lambda a, ax: a.scores[ax])


def _run(deck, make_card, **kw):
    swords = _card(make_card, "Swords", KILL, mv=1)
    return role_swap.role_swap(deck, SimpleNamespace(runs=150), None, [swords], role="removal",
                               card_targets=TARGETS, applicable=APPLICABLE, cut_pool=2, **kw)


def test_a_cut_with_a_measured_cost_loses_to_a_free_one(monkeypatch, deck, make_card):
    # The Vraska shape: same interaction gain either way, one cut tanks ceiling.
    _patch_sim(monkeypatch, {"Rock 0": {"interaction": 58.0, "ceiling": 23.0},
                             "Rock 1": {"interaction": 58.0}})
    report = _run(deck, make_card)
    assert report.pairs_measured == 2
    assert report.swap.add == "Swords" and report.swap.cut == "Rock 1"
    assert report.swap.costs == []
    assert report.swap.gain.axis == "interaction" and report.swap.gain.delta == 8.0
    assert (report.swap.role_cards_before, report.swap.role_cards_after) == (0, 1)
    assert [s.cut for s in report.rejected] == ["Rock 0"]


def test_when_every_cut_costs_something_the_cost_is_reported_not_hidden(monkeypatch, deck,
                                                                        make_card):
    _patch_sim(monkeypatch, {"Rock 0": {"interaction": 58.0, "ceiling": 23.0},
                             "Rock 1": {"interaction": 58.0, "speed": 40.0}})
    swap = _run(deck, make_card).swap
    assert swap.cut == "Rock 1" and swap.costs == ["speed"]   # the smaller loss, flagged


def test_no_gain_on_the_role_axis_means_no_swap(monkeypatch, deck, make_card):
    _patch_sim(monkeypatch, {"Rock 0": {"interaction": 50.5}, "Rock 1": {"interaction": 50.0}})
    report = _run(deck, make_card)
    assert report.swap is None and "interaction" in report.reason
    assert len(report.rejected) == 2


def test_every_role_has_an_axis_entry_and_every_axis_is_real():
    assert set(role_swap.ROLE_AXIS) == set(redundancy.ROLE_CARD_TARGETS)
    assert {a for a in role_swap.ROLE_AXIS.values() if a} <= set(advisor.AXES)
    assert role_swap.ROLE_AXIS["noncreature_removal"] is None   # interaction ignores it


# ── the mentor tool ──────────────────────────────────────────────────────────────────

def _stats(roles):
    return ToolResult(data={"roles": roles, "role_summary": role_summary(roles)})


def _roles(**kw):
    return {r: {"cards": c, "card_target": t, "applicable": a} for r, (c, t, a) in kw.items()}


def test_the_tool_declines_a_role_at_target(monkeypatch):
    monkeypatch.setattr(tools, "tool_get_deck_stats",
                        lambda ctx: _stats(_roles(removal=(7, 7, True), ramp=(13, 12, True))))
    data = tools.tool_suggest_role_swap(SimpleNamespace(), role="removal").data
    assert data["role_swap_found"] is False and "not under target" in data["message"]


def test_the_tool_reports_axis_cost_check_and_licenses_both_cards(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "tool_get_deck_stats",
                        lambda ctx: _stats(_roles(removal=(2, 7, True), ramp=(13, 12, True))))
    coll = tmp_path / "collection.csv"
    coll.write_text("Count,Name\n1,Swords\n", encoding="utf-8")
    monkeypatch.setattr(tools, "suite_collection_path", lambda: coll)
    monkeypatch.setattr(tools, "_analysis_for", lambda ctx: None)
    monkeypatch.setattr(tools.advisor, "owned_candidates", lambda *a: [])
    move = role_swap.AxisMove("interaction", 62.0, 70.9, 8.9, 1.0, True)
    cost = role_swap.AxisMove("ceiling", 46.2, 18.9, -27.3, 2.27, True)
    report = role_swap.RoleSwapReport(
        role="removal", axis="interaction", role_cards=2, card_target=7, adds_available=44,
        cuts_available=17, pairs_measured=2,
        swap=role_swap.RoleSwap("Swords to Plowshares", "Craterclaw Colossus", "finisher", 4, 2,
                                2, 3, move, [cost], ["ceiling"]))
    monkeypatch.setattr(tools.role_swap_mod, "role_swap", lambda *a, **k: report)
    ctx = SimpleNamespace(resolved=SimpleNamespace(commanders=[]), cfg=None, store=None,
                          card_db=None, themes=())
    result = tools.tool_suggest_role_swap(ctx)        # defaults to most_under_supplied
    d = result.data
    assert d["role"] == "removal" and d["role_swap_found"] is True and d["axis"] == "interaction"
    assert d["swap"]["costs"] == ["ceiling"]
    assert "ceiling 46.2 to 18.9" in d["instruction"] and "say so plainly" in d["instruction"]
    assert "measured on interaction: 62.0 to 70.9" in d["instruction"]
    assert result.card_names == {"Swords to Plowshares", "Craterclaw Colossus"}
    # the gate treats every cost-check axis as measured this turn
    budget = gate.ClaimBudget.from_tool_results([result], frozenset())
    assert budget.swap_axes == frozenset(role_swap.COST_AXES)


# ── chat routing ─────────────────────────────────────────────────────────────────────

SUMMARY = role_summary(_roles(ramp=(13, 12, True), draw=(7, 11, True), removal=(2, 7, True),
                              wipe=(2, 2, True)))
Q_BROAD_CUT = ("For each role, how many cards do I run versus the target? Which role is most "
               "under-supplied, and which cards should I cut?")


@pytest.mark.parametrize("question,role", [
    (Q_BROAD_CUT, "removal"),                                            # most_under_supplied
    ("How many draw spells do I run, and what should I cut to add more?", "draw"),
    ("How many wipes do I run, and what should I cut?", None),          # at target: no role swap
])
def test_the_swap_role_follows_the_question(question, role):
    assert chat._swap_role(question, SUMMARY) == role


def _ask(monkeypatch, question, role_swap_data):
    calls = []

    def fake_tool(ctx, name, args):
        calls.append((name, args))
        if name == "get_deck_stats":
            return ToolResult(data={"roles": {}, "role_summary": SUMMARY})
        if name == "suggest_role_swap":
            return ToolResult(data=role_swap_data)
        return ToolResult(data={"found": True})

    seen = []

    def fake_post(messages, **kw):
        seen.append(messages)
        return {"role": "assistant", "content": "Removal: 2 cards vs a target of 7."}

    monkeypatch.setattr(chat, "call_tool", fake_tool)
    monkeypatch.setattr(chat, "_post_chat", fake_post)
    chat.ask(SimpleNamespace(all_card_names=frozenset()), question)
    return calls, seen


def test_a_role_question_with_a_cut_half_prefetches_the_role_swap(monkeypatch):
    calls, seen = _ask(monkeypatch, Q_BROAD_CUT, {"found": True, "role_swap_found": True})
    assert calls[:2] == [("get_deck_stats", {}), ("suggest_role_swap", {"role": "removal"})]
    assert seen[0][-1]["content"] == chat._ROLE_SWAP_NUDGE
    # the found role swap IS the swap answer: no swap nudge, no forced suggest_swap
    assert [n for n, _ in calls].count("suggest_swap") == 0
    assert all(m.get("content") != chat._SWAP_NUDGE for m in seen[-1])


def test_a_pure_count_question_runs_no_swap(monkeypatch):
    calls, _ = _ask(monkeypatch, "What does this deck need the most of?",
                    {"found": True, "role_swap_found": True})
    assert [n for n, _ in calls] == ["get_deck_stats"]


def test_no_role_swap_found_leaves_the_usual_swap_path_open(monkeypatch):
    calls, seen = _ask(monkeypatch, Q_BROAD_CUT, {"found": True, "role_swap_found": False})
    assert seen[0][-1]["content"] != chat._ROLE_SWAP_NUDGE
    assert any(m.get("content") == chat._SWAP_NUDGE for m in seen[-1])
