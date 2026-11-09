"""Exposure to hate (B36): one fixture per row, each speaking only past its threshold."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from mythgauntlet.ratings import exposure as ex
from mythgauntlet.ratings import reference


def _card(make_card, name, type_line="Sorcery", text="", cost="{1}", **kw):
    return make_card(name, mana_cost=cost, type_line=type_line, oracle_text=text, **kw)


def _resolved(cards, commanders=()):
    return NS(cards=list(cards), commanders=list(commanders))


def _analysis(**kw):
    base = dict(bracket=NS(bracket=2), resilience=None, combo_profile=None, combo_clock=None,
                report=NS(avg_kill_turn=None))
    base.update(kw)
    return NS(**base)


def _keys(rows):
    return {r.key for r in rows}


# --- card-level reads -----------------------------------------------------------------------

@pytest.mark.parametrize("name,text,uses", [
    ("Eternal Witness", "When this creature enters, return target card from your graveyard to "
     "your hand.", True),
    ("Underworld Breach", "Each nonland card in your graveyard has escape.", True),
    ("Faithless Looting", "Draw two cards, then discard two cards.\nFlashback {2}{R}", True),
    ("Tarmogoyf", "Tarmogoyf's power is equal to the number of card types among cards in all "
     "graveyards", False),
    ("Guardian Project", "Whenever a nontoken creature you control enters, if it doesn't have the "
     "same name as another creature you control or a creature card in your graveyard, draw a "
     "card.", False),
    ("Bojuka Bog", "Exile target player's graveyard.", False),
    ("Cabal Ritual", "Add {B}{B}{B}.\nThreshold — Add {B}{B}{B}{B}{B} instead if seven or more "
     "cards are in your graveyard.", True),
])
def test_graveyard_reliance(make_card, name, text, uses):
    assert ex.uses_graveyard(_card(make_card, name, text=text)) is uses, name


def test_flyer_blockers_need_the_keyword_line(make_card):
    bird = _card(make_card, "Bird", "Creature - Bird", "Flying")
    spider = _card(make_card, "Spider", "Creature - Spider", "Reach, deathtouch")
    lord = _card(make_card, "Lord", "Creature - Bird", "Other creatures you control have flying.")
    assert ex.blocks_flyers(bird) and ex.blocks_flyers(spider) and not ex.blocks_flyers(lord)


# --- rows -----------------------------------------------------------------------------------

def test_graveyard_row(make_card, forest):
    recur = [(_card(make_card, f"Recur {i}", text="Return target card from your graveyard to "
                    "your hand."), 1) for i in range(ex.GRAVEYARD_MIN)]
    rows = ex.compute(_resolved([(forest, 30)] + recur), _analysis(), None, [], 12)
    assert "graveyard" in _keys(rows)
    rows = ex.compute(_resolved([(forest, 30)] + recur[:-1]), _analysis(), None, [], 12)
    assert "graveyard" not in _keys(rows)


def test_commander_row_reads_the_goldfish_loss(make_card, forest):
    boss = _card(make_card, "Boss", "Legendary Creature - Beast")
    clean = [NS(kill_turn=8)] * 10
    slow = [NS(kill_turn=10)] * 10           # 2 turns lost
    rows = ex.compute(_resolved([(forest, 30)], [boss]), _analysis(), slow, clean, 12)
    row = next(r for r in rows if r.key == "commander")
    assert row.text.startswith("loses 2.0 turns of speed if Boss is answered twice")
    rows = ex.compute(_resolved([(forest, 30)], [boss]), _analysis(), clean, clean, 12)
    assert "commander" not in _keys(rows)


def test_artifact_and_enchantment_rows(make_card, forest):
    rocks = [(_card(make_card, f"Rock {i}", "Artifact", "{T}: Add {C}."), 1)
             for i in range(ex.ARTIFACT_RAMP_MIN)]
    rows = ex.compute(_resolved([(forest, 30)] + rocks), _analysis(), None, [], 12)
    assert any(r.key == "artifacts" and r.text.startswith(f"{ex.ARTIFACT_RAMP_MIN} of its")
               for r in rows)
    auras = [(_card(make_card, f"Aura {i}", "Enchantment"), 1) for i in range(3)]
    spells = [(_card(make_card, f"Spell {i}"), 1) for i in range(10)]
    rows = ex.compute(_resolved([(forest, 30)] + auras + spells), _analysis(), None, [], 12)
    assert "enchantments" in _keys(rows)          # 3/13 = 23% >= 15%


def test_flyer_row_only_with_no_blocker(make_card, forest):
    bird = _card(make_card, "Bird", "Creature - Bird", "Flying")
    assert "flyers" in _keys(ex.compute(_resolved([(forest, 30)]), _analysis(), None, [], 12))
    assert "flyers" not in _keys(ex.compute(_resolved([(forest, 30), (bird, 1)]), _analysis(),
                                            None, [], 12))


def test_single_combo_row(make_card, forest):
    def grade(*cards):
        return NS(terminal=True, combo=NS(cards=cards))
    two = NS(grades=(grade("Krenko", "Prospector"), grade("Krenko", "Altar")), total=2)
    rows = ex.compute(_resolved([(forest, 30)]), _analysis(combo_profile=two), None, [], 12)
    row = next(r for r in rows if r.key == "single_combo")
    assert row.text == "all 2 of its game-ending combos use Krenko: one answer to Krenko stops it"
    apart = NS(grades=(grade("A", "B"), grade("C", "D")), total=2)
    assert "single_combo" not in _keys(ex.compute(_resolved([(forest, 30)]),
                                                  _analysis(combo_profile=apart), None, [], 12))


def test_mana_base_row_needs_colours_and_nonbasics(make_card, forest):
    dual = _card(make_card, "Dual", "Land", "{T}: Add {U} or {R}.")
    boss = _card(make_card, "Boss", "Legendary Creature - Wizard", color_identity=("U", "R"))
    rows = ex.compute(_resolved([(dual, ex.NONBASIC_MIN)], [boss]), _analysis(), None, [], 12)
    assert any(r.key == "mana_base" and r.text.startswith(f"{ex.NONBASIC_MIN} nonbasic") for r in rows)
    mono = _card(make_card, "Mono", "Legendary Creature - Elf", color_identity=("G",))
    assert "mana_base" not in _keys(ex.compute(_resolved([(dual, 30)], [mono]), _analysis(),
                                               None, [], 12))


def test_wipes_and_speed_rows_rank_against_bracket_peers(make_card, forest, monkeypatch):
    def cell(lo, hi):
        q = [lo + (hi - lo) * k / 20 for k in range(21)]
        return {"p25": q[5], "p50": q[10], "p75": q[15], "n": 100, "thin": False, "q": q}
    monkeypatch.setattr(reference, "BRACKET_AXIS_REFERENCE",
                        {2: {"resilience": cell(0, 100), "avg_kill_turn": cell(6, 14)}})
    a = _analysis(resilience=NS(resilience_score=10.0), report=NS(avg_kill_turn=13.0))
    rows = {r.key: r.text for r in ex.compute(_resolved([(forest, 30)]), a, None, [], 12)}
    assert rows["wipes"].startswith("a board wipe sets it back further than 90% of Bracket 2")
    assert rows["speed"].startswith("slower than 88% of Bracket 2 decks (kills around T13")
    fine = _analysis(resilience=NS(resilience_score=60.0), report=NS(avg_kill_turn=9.0))
    keys = _keys(ex.compute(_resolved([(forest, 30)]), fine, None, [], 12))
    assert not keys & {"wipes", "speed"}


def test_speed_row_counts_a_combo_that_wins_first(make_card, forest, monkeypatch):
    q = [6 + 8 * k / 20 for k in range(21)]
    monkeypatch.setattr(reference, "BRACKET_AXIS_REFERENCE", {5: {"avg_kill_turn": {
        "p25": q[5], "p50": q[10], "p75": q[15], "n": 100, "thin": False, "q": q}}})
    clock = NS(median=7.0, combo_first_games=75, games=100, combos=[])
    a = _analysis(bracket=NS(bracket=5), report=NS(avg_kill_turn=13.5), combo_clock=clock)
    assert "speed" not in _keys(ex.compute(_resolved([(forest, 30)]), a, None, [], 12))
    a.combo_clock = None
    assert "speed" in _keys(ex.compute(_resolved([(forest, 30)]), a, None, [], 12))
