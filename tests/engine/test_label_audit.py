"""Corpus label audit: a bracket label the official hard gates forbid is demoted, never guessed."""
from __future__ import annotations

from types import SimpleNamespace

from mythgauntlet.data import label_audit as la
from mythgauntlet.data.spellbook import Combo, ComboReport


def _combo(cards, *produces):
    return Combo(id="x", cards=tuple(cards), produces=tuple(produces), bracket_tag=None,
                 mana_needed="", popularity=None)


def test_game_changer_limits_per_bracket():
    assert la.audit(2, {"Rhystic Study"}, []).reasons == [
        "1 Game Changers (Rhystic Study); Bracket 2 allows 0"]
    assert la.audit(3, {"A", "B", "C"}, []).ok
    assert not la.audit(3, {"A", "B", "C", "D"}, []).ok
    assert la.audit(4, {"A", "B", "C", "D", "E", "F"}, []).ok      # no limit to violate
    assert la.audit(5, set(), []).ok                               # a judgement, never dropped


def test_only_brackets_1_and_2_forbid_two_card_infinites():
    pair = [("Heliod, Sun-Crowned", "Walking Ballista")]
    assert not la.audit(1, set(), pair).ok and not la.audit(2, set(), pair).ok
    assert la.audit(3, set(), pair).ok


def test_near_infinite_and_non_looping_wins_are_not_infinite_combos():
    report = ComboReport(identity="WBR", included=[
        _combo(["Blasphemous Act", "Repercussion"], "Near-infinite damage to all players"),
        _combo(["Approach of the Second Sun", "Windfall"], "Win the game"),
        _combo(["Thassa's Oracle", "Demonic Consultation", "Island"], "Infinite whatever"),
        _combo(["Basalt Monolith", "Rings of Brighthearth"], "Infinite colorless mana"),
    ], almost_included=[])
    assert la.two_card_infinite(report) == [("Basalt Monolith", "Rings of Brighthearth")]
    assert la.two_card_infinite(None) == []          # a failed lookup is never dirty


def test_audit_resolved_counts_commanders_and_skips_a_failed_lookup(make_card):
    cradle = make_card("Gaea's Cradle", type_line="Legendary Land")
    cradle.game_changer = True
    elf = make_card("Elf", mana_cost="{G}", type_line="Creature — Elf")
    deck = SimpleNamespace(cards=[(elf, 1)], commanders=[cradle])
    assert la.audit_resolved(deck, 2, None).reasons == [
        "1 Game Changers (Gaea's Cradle); Bracket 2 allows 0"]


def test_mark_and_unmark_round_trip_keeps_the_layout():
    text = "# Deck\n# source: archidekt:1\n# bracket: 2\n\nCommander:\n1 X\n"
    result = la.audit(2, {"Rhystic Study"}, [])
    marked = la.mark(text, result)
    assert marked.startswith("# Deck\n# source: archidekt:1\n# bracket_claimed: 2\n"
                             "# label_audit: fails the official Bracket 2 gates: 1 Game Changers")
    assert "allows 0\n\nCommander:" in marked       # the blank line under the header survives
    assert la.LABEL_RE.search(marked) is None       # out of every `# bracket:` reader
    assert la.unmark(marked) == text
    assert la.mark(text, la.audit(2, set(), [])) == text
