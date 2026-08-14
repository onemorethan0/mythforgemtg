"""Redundancy-based cut candidates. Written from docs/SPEC_redundancy.md.

Offline, synthetic, no network — cards are built from real oracle text so the roles come
out of the live `tags.analyze`, not out of a hand-stubbed EffectVector.
"""

from __future__ import annotations

import pytest

from mythgauntlet.model.deck import Deck, ResolvedDeck
from mythgauntlet.ratings import advisor, redundancy

# Oracle text verbatim enough for tags.analyze to read the intended role.
POWERSTONE = ("Worn Powerstone", "Artifact", "This artifact enters tapped. {T}: Add {C}{C}.")
CULTIVATE = (
    "Cultivate", "Sorcery",
    "Search your library for up to two basic land cards, reveal those cards, put one onto "
    "the battlefield tapped and the other into your hand, then shuffle.",
)
SWORDS = (
    "Swords to Plowshares", "Instant",
    "Exile target creature. Its controller gains life equal to its power.",
)
PET = (
    "Whisper of the Unseen", "Enchantment",
    "Whenever a face-down creature you control is turned face up, scry 1.",
)


@pytest.fixture
def build_deck(make_card):
    """Resolve a deck from (name, type_line, oracle_text) triples."""
    def _build(specs, ranks=None):
        ranks = ranks or {}
        cards = [
            (make_card(n, type_line=tl, oracle_text=ot, edhrec_rank=ranks.get(n)), 1)
            for n, tl, ot in specs
        ]
        return ResolvedDeck(
            deck=Deck(commanders=[], entries=[]), commanders=[], cards=cards, missing=[]
        )
    return _build


def test_card_roles_empty_for_an_unreadable_card(make_card):
    """No recognised role means 'never redundant', not 'worthless'."""
    from mythgauntlet.semantics import tags

    def roles(spec):
        name, type_line, oracle = spec
        return redundancy.card_roles(
            tags.analyze(make_card(name, type_line=type_line, oracle_text=oracle))
        )

    assert roles(PET) == {}
    assert roles(SWORDS) == {"removal": 1.0}


def test_role_supply_skips_lands_and_commanders(make_card, forest):
    """A land that taps for mana is not deck ramp for this purpose, and the commander is
    never a cut candidate — counting it inflates the role it defines."""
    rock = make_card("Rock", type_line="Artifact", oracle_text="{T}: Add {C}{C}.")
    cmdr = make_card(
        "Ramp Lord", type_line="Legendary Creature — Druid", oracle_text="{T}: Add {G}{G}."
    )
    resolved = ResolvedDeck(
        deck=Deck(commanders=[], entries=[]),
        commanders=[cmdr],
        cards=[(rock, 1), (forest, 10)],
        missing=[],
    )
    supply = redundancy.role_supply(resolved)
    assert supply.get("ramp") == 2.0        # the rock only: no land, no commander


def test_counterspells_are_not_scored_against_the_protection_slot(make_card):
    """The role is `counterspell`, not `protection`, and ward/hexproof is UNMEASURED.

    The builder's protection slot also buys ward/hexproof/indestructible, but the rung-1
    EffectVector has no field for those, so naming the role `protection` would claim a
    measurement that isn't happening. This pins the naming and the gap — the target
    number (3) is still the protection slot's and is a known open calibration.
    """
    from mythgauntlet.semantics import tags

    counter = make_card(
        "Counterspell", type_line="Instant", oracle_text="Counter target spell."
    )
    warded = make_card(
        "Warded Bear", type_line="Creature — Bear",
        oracle_text="Ward {2}. This creature has hexproof and indestructible.",
    )
    assert redundancy.card_roles(tags.analyze(counter)) == {"counterspell": 3.0}
    assert "protection" not in redundancy.ROLE_TARGETS
    # Ward/hexproof contributes NO protection supply — under-counted on purpose.
    assert "counterspell" not in redundancy.card_roles(tags.analyze(warded))


def test_role_supply_multiplies_by_count(make_card):
    rock = make_card("Rock", type_line="Artifact", oracle_text="{T}: Add {C}{C}.")
    resolved = ResolvedDeck(
        deck=Deck(commanders=[], entries=[]), commanders=[], cards=[(rock, 3)], missing=[]
    )
    assert redundancy.role_supply(resolved)["ramp"] == 6.0


def test_gold_set_cut_order(build_deck, make_card):
    """The spec's worked example, end to end.

    Ramp is over-supplied and removal is not, so: weakest ramp first, better ramp second,
    the not-over-served removal spell third, and the roleless pet card LAST.
    """
    # 6 rocks (2.0 each) + a dork (1.0) + Powerstone (2.0) + Cultivate (3.0) = 18.0 ramp
    # supply against a target of 10, so oversupply is the spec's 8.0.
    filler = [(f"Rock {i}", "Artifact", "{T}: Add {C}{C}.") for i in range(6)]
    dork = ("Llanowar Elves", "Creature — Elf Druid", "{T}: Add {G}.")
    resolved = build_deck([POWERSTONE, CULTIVATE, SWORDS, PET, dork, *filler])

    supply = redundancy.role_supply(resolved)
    assert supply["ramp"] == 18.0

    # Assert the spec's RELATIVE order. The filler rocks tie with Worn Powerstone on
    # strength (both 2.0), so absolute positions depend on the name tie-break — the claim
    # the spec actually makes is about these five cards relative to each other.
    ordered = [c.name for c in redundancy.rank_redundant(resolved, 99)]
    rank = {name: ordered.index(name) for name in ordered}
    assert rank["Llanowar Elves"] < rank["Worn Powerstone"] < rank["Cultivate"]
    assert rank["Cultivate"] < rank["Swords to Plowshares"]
    assert ordered[-1] == "Whisper of the Unseen"       # protected, always last


def test_pet_card_is_protected_not_first(build_deck):
    """The regression this module exists for: the least-played card led the old cut pool."""
    resolved = build_deck(
        [POWERSTONE, CULTIVATE, PET],
        ranks={"Worn Powerstone": 300, "Cultivate": 120, "Whisper of the Unseen": 99999},
    )
    scores = {
        s.card.name: s
        for s in (
            redundancy.score_card(c, redundancy.role_supply(resolved))
            for c, _ in resolved.cards
        )
    }
    assert scores["Whisper of the Unseen"].protected is True
    assert scores["Whisper of the Unseen"].role is None
    # Popularity would put the pet card first; redundancy puts it last.
    assert advisor._weakest_cuts(resolved, 1)[0].name == "Whisper of the Unseen"
    assert redundancy.rank_redundant(resolved, 3)[-1].name == "Whisper of the Unseen"


def test_weaker_contributor_in_an_oversupplied_role_is_cut_first(build_deck):
    """score = oversupply / (1 + within_role): once ramp is over-served you cut the WORST
    ramp spell. The obvious `oversupply * within_role` inverts this."""
    filler = [(f"Rock {i}", "Artifact", "{T}: Add {C}{C}.") for i in range(8)]
    resolved = build_deck([POWERSTONE, CULTIVATE, *filler])
    supply = redundancy.role_supply(resolved)
    weak = redundancy.score_card(resolved.cards[0][0], supply)     # Worn Powerstone, 2.0
    strong = redundancy.score_card(resolved.cards[1][0], supply)   # Cultivate, 3.0
    assert weak.within_role < strong.within_role
    assert weak.score > strong.score


def test_a_role_at_target_scores_zero(build_deck):
    """Not over-supplied means not redundant."""
    resolved = build_deck([SWORDS])
    score = redundancy.score_card(resolved.cards[0][0], redundancy.role_supply(resolved))
    assert score.role == "removal"
    assert score.oversupply == 0.0
    assert score.score == 0.0
    assert score.protected is False


def test_explicit_empty_targets_is_honoured(build_deck):
    """`targets={}` means 'every role has target 0', not 'fall back to ROLE_TARGETS'.

    `targets or ROLE_TARGETS` silently ignores a deliberate empty dict.
    """
    resolved = build_deck([SWORDS])
    card = resolved.cards[0][0]
    supply = redundancy.role_supply(resolved)
    assert redundancy.score_card(card, supply, targets={}).oversupply == 1.0
    assert redundancy.score_card(card, supply).oversupply == 0.0


def test_rank_redundant_is_deterministic_and_clamps_k(build_deck):
    resolved = build_deck([POWERSTONE, CULTIVATE, SWORDS, PET])
    assert redundancy.rank_redundant(resolved, 3) == redundancy.rank_redundant(resolved, 3)
    assert len(redundancy.rank_redundant(resolved, 0)) == 1        # k clamped to >= 1
    assert len(redundancy.rank_redundant(resolved, 99)) == 4       # only 4 cards exist


def test_duplicate_names_are_deduped_without_hashing_a_card(build_deck, make_card):
    """Card is a MUTABLE dataclass and therefore unhashable — dedupe must key on name."""
    rock = make_card("Rock", type_line="Artifact", oracle_text="{T}: Add {C}{C}.")
    resolved = ResolvedDeck(
        deck=Deck(commanders=[], entries=[]),
        commanders=[],
        cards=[(rock, 1), (rock, 1)],
        missing=[],
    )
    with pytest.raises(TypeError):
        {rock}                                    # documents WHY dedupe is by name
    assert len(redundancy.rank_redundant(resolved, 5)) == 1


def test_advisor_cut_strategy_selects_the_pool(build_deck):
    """`advise` dispatches through `_cut_candidates`; the two strategies disagree here."""
    resolved = build_deck(
        [POWERSTONE, CULTIVATE, PET],
        ranks={"Worn Powerstone": 300, "Cultivate": 120, "Whisper of the Unseen": 99999},
    )
    redundant = advisor._cut_candidates(resolved, 1, advisor.CUT_REDUNDANT)
    popular = advisor._cut_candidates(resolved, 1, advisor.CUT_POPULARITY)
    assert redundant[0].name == "Worn Powerstone"
    assert popular[0].name == "Whisper of the Unseen"


def test_advise_rejects_an_unknown_cut_strategy(build_deck):
    resolved = build_deck([SWORDS])
    with pytest.raises(ValueError, match="cut_strategy"):
        advisor.advise(resolved, None, None, [], cut_strategy="nonsense")
