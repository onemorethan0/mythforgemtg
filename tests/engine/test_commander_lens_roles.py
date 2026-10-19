"""Roles read the commander lens (offline, synthetic cards)."""

from mythgauntlet.mentor.deckview import deck_card_rows
from mythgauntlet.model.deck import Deck, ResolvedDeck
from mythgauntlet.ratings import redundancy
from mythgauntlet.ratings.redundancy import card_roles, roles_for, score_card
from mythgauntlet.semantics import tags
from mythgauntlet.semantics.commander_lens import build_lens

from tests.engine.test_commander_lens import (
    BLASPHEMOUS, DELUGE, FAREWELL, RUINOUS, SMAUG, WRATH,
)


def _deck(commander, cards):
    return ResolvedDeck(deck=Deck(name="t"), commanders=[commander],
                        cards=[(c, 1) for c in cards], missing=[])


def test_blasphemous_counts_as_ramp_and_wipe_under_smaug(make_card):
    lens = build_lens([make_card(**SMAUG)])
    roles = roles_for(make_card(**BLASPHEMOUS), lens)
    assert "wipe" in roles
    assert roles["ramp"] == 2.0


def test_no_lens_roles_unchanged(make_card):
    act = make_card(**BLASPHEMOUS)
    assert roles_for(act, None) == card_roles(tags.analyze(act))
    assert "ramp" not in roles_for(act, None)


def test_role_card_counts_identical_for_unmatched_commander(make_card):
    legend = make_card("Plain Legend", mana_cost="{2}{G}", type_line="Legendary Creature — Elf")
    deck = _deck(legend, [make_card(**WRATH), make_card(**BLASPHEMOUS), make_card(**FAREWELL)])
    lens = build_lens([legend])
    assert lens.kinds == ()
    assert redundancy.role_card_counts(deck, lens) == redundancy.role_card_counts(deck)
    assert redundancy.role_supply(deck, lens) == redundancy.role_supply(deck)


def test_flagged_card_is_never_a_redundant_cut(make_card):
    smaug = make_card(**SMAUG)
    act = make_card(**BLASPHEMOUS)
    others = [make_card(**WRATH), make_card(**FAREWELL), make_card(**DELUGE), make_card(**RUINOUS)]
    deck = _deck(smaug, [act] + others)
    lens = build_lens([smaug])
    targets = {"wipe": 1}
    supply = redundancy.role_supply(deck, lens)
    assert score_card(act, supply, targets, lens).protected is True
    unflagged_wipe = next(c for c in others if lens.facts_for(c).empty
                          and "wipe" in roles_for(c, lens))
    assert score_card(unflagged_wipe, supply, targets, lens).protected is False
    cuts = redundancy.rank_redundant(deck, len(deck.cards), targets=targets, lens=lens)
    names = [c.name for c in cuts]
    assert names.index(act.name) > names.index(unflagged_wipe.name)
    flagged = lens.flagged(deck.cards[i][0] for i in range(len(deck.cards)))
    first_flagged = min(names.index(n) for n in flagged)
    assert all(names.index(c.name) < first_flagged for c in cuts if c.name not in flagged)


def test_deck_card_rows_carry_synergy(make_card):
    smaug = make_card(**SMAUG)
    deck = _deck(smaug, [make_card(**BLASPHEMOUS), make_card(**WRATH)])
    rows = {r["name"]: r for r in deck_card_rows(deck, build_lens([smaug]))}
    assert rows["Blasphemous Act"]["commander_synergy"]["kind"] == "damage_to_self_payoff"
    assert rows["Blasphemous Act"]["commander_synergy"]["treasure"] > 0
    assert rows["Wrath of God"]["commander_synergy"]["kind"] == "one_sided_wipe"
    assert rows["Smaug the Impenetrable"]["commander_synergy"] is None

    legend = make_card("Plain Legend", mana_cost="{2}{G}", type_line="Legendary Creature — Elf")
    plain = _deck(legend, [make_card(**WRATH)])
    assert deck_card_rows(plain, build_lens([legend]))[1]["commander_synergy"] is None
    assert deck_card_rows(plain)[1]["commander_synergy"] is None
