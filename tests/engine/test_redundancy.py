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


# ── within-role quality: the module's central promise, previously unimplemented ──

def test_within_role_can_actually_discriminate(make_card):
    """`card_roles` returns a FIXED strength per role, so four of seven roles tied.

    Measured over 40 corpus decks: counterspell 3.0 on all 54 cards, removal 1.0 on all 167,
    tutor 2.0 on all 51, wipe 3.0 on all 49. For those roles `oversupply / (1 + within_role)`
    was a per-role CONSTANT, so "you cut the worst ramp spell, not the best one" was not
    implemented at all — every card tied and ordering fell to the least-played tiebreak. That
    is how a Prismari spellslinger deck was told to cut Flusterstorm and Mental Misstep.
    """
    from mythgauntlet.ratings.redundancy import _efficiency

    cheap = make_card("Flusterstorm", mana_cost="{U}")
    mid = make_card("Mana Sculpt", mana_cost="{2}{U}")
    dear = make_card("Ponderous Counter", mana_cost="{5}{U}{U}")

    # cheaper card earns MORE within-role credit, which LOWERS its cut score
    assert _efficiency(cheap) > _efficiency(mid) > _efficiency(dear)
    assert _efficiency(dear) == 0.0, "at/above the cap there is no credit to earn"


def test_the_expensive_member_of_an_over_served_role_is_offered_first(make_card):
    """The ordering consequence, stated as the behaviour a user sees."""
    from mythgauntlet.ratings.redundancy import _efficiency

    supply_over = 6.0
    base_within = 3.0          # what card_roles gives every counterspell

    def score(card):
        return supply_over / (1.0 + base_within + _efficiency(card))

    cheap = make_card("Flusterstorm", mana_cost="{U}")
    dear = make_card("Mana Sculpt", mana_cost="{2}{U}")
    assert score(dear) > score(cheap), (
        "the pricier card in an over-served role must rank as the more cuttable one")


def test_efficiency_refines_order_without_swamping_oversupply(make_card):
    """It must reorder WITHIN a role, never outrank a genuinely more over-served one.

    `oversupply` is the signal; cost is a tiebreak with teeth. If the credit grew large enough
    to invert that, a deck's single most over-supplied role would stop leading the pool.
    """
    from mythgauntlet.ratings.redundancy import _efficiency

    cheap = make_card("Cheap", mana_cost="{U}")
    # role A is barely over (1.0), role B is heavily over (8.0)
    barely = 1.0 / (1.0 + 1.0 + _efficiency(cheap))
    heavily = 8.0 / (1.0 + 3.0 + 0.0)
    assert heavily > barely


# ── Archetype-conditioned targets (S10) ──────────────────────────────────────────
# `ROLE_TARGETS` judges every deck against ONE population baseline, so a deck that plays to a
# role as its PLAN reads as over-supplied in exactly the thing it is trying to do. The
# spellslinger case is the measured one: the population target for `counterspell` is 3 supply
# units — the weight of a single card, because the median corpus deck runs zero — while the
# corpus decks that ARE spellslinger decks supply a p60 of 12.

# A deck whose PLAN is counterspells. Four of them is 12.0 supply: against the population
# target of 3 that is 9.0 over, and against what spellslinger decks really run (12) it is
# not over at all. Its ramp is genuinely over-served (18.0 against 14) so the pool has
# somewhere honest to go - without that every card scores 0.0 and the order degenerates to
# the name tiebreak, which would prove nothing.
_BASIC_TWO = (
    "Search your library for up to two basic land cards, reveal those cards, put one onto "
    "the battlefield tapped and the other into your hand, then shuffle."
)
_BASIC_ONE = (
    "Search your library for a basic land card, put it onto the battlefield tapped, "
    "then shuffle."
)
SPELLSLINGER_DECK = [
    ("Flusterstorm", "Instant",
     "Counter target instant or sorcery spell unless its controller pays {1}.", "{U}"),
    ("Mental Misstep", "Instant", "Counter target spell with mana value 1.", "{U}"),
    ("Arcane Denial", "Instant",
     "Counter target spell. Its controller may draw up to two cards at the beginning of "
     "the next turn's upkeep.", "{1}{U}"),
    ("Ponderous Denial", "Instant",
     "Counter target spell unless its controller pays {3}.", "{4}{U}"),
    ("Cultivate", "Sorcery", _BASIC_TWO, "{2}{G}"),
    ("Kodama's Reach", "Sorcery", _BASIC_TWO, "{2}{G}"),
    ("Rampant Growth", "Sorcery", _BASIC_ONE, "{1}{G}"),
    ("Nature's Lore", "Sorcery", _BASIC_ONE, "{1}{G}"),
    ("Verdant Errand", "Sorcery", _BASIC_ONE, "{2}{G}"),
    ("Ponderous Cultivation", "Sorcery", _BASIC_ONE, "{4}{G}"),
    ("Swords to Plowshares", "Instant",
     "Exile target creature. Its controller gains life equal to its power.", "{W}"),
    ("Whisper of the Unseen", "Enchantment",
     "Whenever a face-down creature you control is turned face up, scry 1.", "{2}{U}"),
]
COUNTERSPELLS = {"Flusterstorm", "Mental Misstep", "Arcane Denial", "Ponderous Denial"}


@pytest.fixture
def spellslinger(make_card):
    """The deck above, resolved — cards carry mana costs so `_efficiency` is live."""
    cards = [
        (make_card(n, type_line=tl, oracle_text=ot, mana_cost=mc), 1)
        for n, tl, ot, mc in SPELLSLINGER_DECK
    ]
    return ResolvedDeck(
        deck=Deck(commanders=[], entries=[]), commanders=[], cards=cards, missing=[]
    )


def test_targets_for_only_ever_raises_a_target():
    """The table has no lowering half, and that asymmetry is deliberate.

    The defect being fixed is false-positive cut suggestions — telling a deck to cut its own
    plan — and a LOWER target manufactures more of them. An archetype can earn a higher
    allowance; it cannot earn a tighter one.
    """
    base = redundancy.ROLE_TARGETS
    for theme in redundancy.ARCHETYPE_ROLE_TARGETS:
        got = redundancy.targets_for([theme])
        assert set(got) == set(base), "no role may appear or vanish"
        for role, value in got.items():
            assert value >= base[role], f"{theme}.{role} lowered {base[role]} -> {value}"
        assert got != base, f"{theme} is in the table but changes nothing"


def test_targets_for_merges_several_archetypes_by_max():
    """A deck with two plans is judged against the most permissive target either earns."""
    both = redundancy.targets_for(["spellslinger", "landfall"])
    assert both["counterspell"] == redundancy.targets_for(["spellslinger"])["counterspell"]
    assert both["ramp"] == redundancy.targets_for(["landfall"])["ramp"]


def test_targets_for_ignores_an_unknown_archetype():
    """Forge owns the taxonomy and may learn a new archetype at any time.

    An unknown name must degrade to the population baseline, not raise — the two live in
    separate processes and cannot be released together.
    """
    assert redundancy.targets_for(["not_a_real_theme"]) == redundancy.ROLE_TARGETS
    assert redundancy.targets_for([]) == redundancy.ROLE_TARGETS
    assert redundancy.targets_for(None) == redundancy.ROLE_TARGETS


def test_targets_for_does_not_mutate_the_baseline():
    """It returns a new dict; ROLE_TARGETS is module state shared by every caller."""
    before = dict(redundancy.ROLE_TARGETS)
    redundancy.targets_for(["spellslinger"])["counterspell"] = 999
    assert redundancy.ROLE_TARGETS == before


def test_a_spellslinger_deck_is_not_offered_its_own_counterspells(spellslinger):
    """The defect, stated as the behaviour a user saw.

    `counterspell`'s population target is 3 supply units — the weight of a SINGLE card,
    because the median corpus deck runs zero. A deck playing four of them is scored 3x over
    and its entire plan becomes the cut pool: the top three cuts offered were all
    counterspells, Flusterstorm and Mental Misstep among them. Told what the deck is, the
    role stops being targeted and the genuinely over-served one (ramp, 18.0 against 14)
    takes over.
    """
    supply = redundancy.role_supply(spellslinger)
    assert supply["counterspell"] == 12.0 and supply["ramp"] == 18.0, "fixture drifted"

    blind = [c.name for c in redundancy.rank_redundant(spellslinger, 3)]
    assert set(blind) <= COUNTERSPELLS, (
        f"precondition: the population baseline offers only counterspells, got {blind}")

    aware = [c.name for c in redundancy.rank_redundant(
        spellslinger, 3, targets=redundancy.targets_for(["spellslinger"]))]
    assert not (set(aware) & COUNTERSPELLS), (
        f"a spellslinger deck must not be offered its counterspells, got {aware}")


def test_an_archetype_target_still_flags_a_genuine_oversupply(spellslinger):
    """It raises the bar, it does not remove it — and that limit is the honest half.

    A deck really can over-serve its own plan. The archetype target is what spellslinger
    decks TYPICALLY run, so a deck well past it is still told so; driving the plan role out
    of the pool unconditionally would be a different bug in the same place.
    """
    generous = redundancy.targets_for(["spellslinger"])
    stuffed = dict(generous, counterspell=4)   # as if the deck ran far past the archetype p60
    pool = [c.name for c in redundancy.rank_redundant(spellslinger, 3, targets=stuffed)]
    assert set(pool) & COUNTERSPELLS, (
        "a deck past even its archetype's supply must still be able to flag that role")


def test_advise_threads_themes_into_the_redundant_pool_only(spellslinger):
    """`popularity` has no notion of a role, so themes must not change it."""
    pop_blind = advisor._cut_candidates(spellslinger, 3, advisor.CUT_POPULARITY, ())
    pop_aware = advisor._cut_candidates(
        spellslinger, 3, advisor.CUT_POPULARITY, ("spellslinger",))
    assert [c.name for c in pop_blind] == [c.name for c in pop_aware]

    red_blind = advisor._cut_candidates(spellslinger, 3, advisor.CUT_REDUNDANT, ())
    red_aware = advisor._cut_candidates(
        spellslinger, 3, advisor.CUT_REDUNDANT, ("spellslinger",))
    assert [c.name for c in red_blind] != [c.name for c in red_aware]


# ── EDHREC lift as the degenerate-case tiebreak (S12) ────────────────────────────
# When nothing is over-supplied every roled card scores 0.0 and ordering fell straight
# through to least-played — which is the SAME rule this module was built to replace, just
# reached by a side door. Two prior fixes (un-clamped headroom; inverted tiebreak) were
# measured and rejected (see the module docstring history in docs/ROADMAP.md, S12); `lift`
# is a third, independent signal from EDHREC synergy rather than from role/oversupply.

STAPLE_REMOVAL = (
    "Staple Removal", "Instant",
    "Exile target creature. Its controller gains life equal to its power.",
)
SIGNATURE_REMOVAL = (
    "Signature Removal", "Instant",
    "Exile target creature. Its controller gains life equal to its power.",
)


def test_lift_omitted_reproduces_the_prior_ordering(build_deck):
    """No `lift` argument at all must be byte-identical to every caller before this change."""
    resolved = build_deck(
        [STAPLE_REMOVAL, SIGNATURE_REMOVAL],
        ranks={"Staple Removal": 50, "Signature Removal": 50000},
    )
    assert redundancy.rank_redundant(resolved, 2) == redundancy.rank_redundant(
        resolved, 2, lift=None
    )


def test_degenerate_tie_falls_to_least_played_without_lift(build_deck):
    """Precondition: both removal spells tie at score 0.0 (removal target is 4, supply 2.0),
    so today's ordering is purely the least-played tiebreak — the obscure, thematically
    precious card is offered FIRST. This is the exact S12 failure mode."""
    resolved = build_deck(
        [STAPLE_REMOVAL, SIGNATURE_REMOVAL],
        ranks={"Staple Removal": 50, "Signature Removal": 50000},
    )
    supply = redundancy.role_supply(resolved)
    assert supply["removal"] == 2.0, "fixture drifted off the degenerate case"
    blind = [c.name for c in redundancy.rank_redundant(resolved, 2)]
    assert blind[0] == "Signature Removal", "precondition: least-played sorts first today"


def test_lift_prefers_cutting_the_generic_staple_over_the_signature_card(build_deck):
    """Told which card is a generic staple (negative lift) and which concentrates on this
    commander's own decks (positive lift), the tiebreak should offer the staple first —
    the opposite of the least-played rule's pick in the same fixture above."""
    resolved = build_deck(
        [STAPLE_REMOVAL, SIGNATURE_REMOVAL],
        ranks={"Staple Removal": 50, "Signature Removal": 50000},
    )
    # Keys are normalized (front face, casefolded) — the contract `_normalize_lift_name`
    # shares with Forge's `edhrec_lift.normalize_name`, since Forge is the realistic
    # producer of this dict and the two sides must agree on a lookup key.
    lift = {"staple removal": -0.15, "signature removal": 0.25}
    aware = [c.name for c in redundancy.rank_redundant(resolved, 2, lift=lift)]
    assert aware[0] == "Staple Removal", (
        "a confirmed generic staple must be offered ahead of a card that concentrates on "
        "this commander's own decks, even though it is the more popular card overall"
    )


def test_lift_unmeasured_card_is_neutral_not_treated_as_safe_to_cut(build_deck):
    """A card absent from `lift` (EDHREC's page covers only ~250 cards) must NOT be treated
    as a confirmed staple — that would be exactly the confident-fabrication failure this
    repo avoids elsewhere. It falls through to the existing least-played tiebreak."""
    resolved = build_deck(
        [STAPLE_REMOVAL, SIGNATURE_REMOVAL],
        ranks={"Staple Removal": 50, "Signature Removal": 50000},
    )
    lift = {"signature removal": 0.25}      # Staple Removal is simply not on the page
    aware = [c.name for c in redundancy.rank_redundant(resolved, 2, lift=lift)]
    # Staple Removal (unmeasured, key 0.0) still sorts ahead of a KNOWN positive-lift card,
    # but for a different, still-honest reason: 0.0 < 0.25, not "confirmed safe to cut".
    assert aware[0] == "Staple Removal"


def test_lift_key_normalizes_case_and_dfc_front_face(build_deck):
    """A `lift` dict is realistically built by Forge (`edhrec_lift`, casefolded/front-face
    keys) or the engine's own `data.edhrec.lift_map` (same convention) — never by hand with
    exact display casing, so the lookup must tolerate both."""
    resolved = build_deck(
        [STAPLE_REMOVAL, SIGNATURE_REMOVAL],
        ranks={"Staple Removal": 50, "Signature Removal": 50000},
    )
    exact_case_lift = {"Staple Removal": -0.15}   # display-cased, as if hand-authored
    aware = [c.name for c in redundancy.rank_redundant(resolved, 2, lift=exact_case_lift)]
    assert aware[0] == "Signature Removal", (
        "an exact-cased key must NOT match — it would silently look like it worked while "
        "the real Forge/engine handoff (always lowercase) matched nothing at all"
    )


def test_lift_map_omits_unmeasured_cards():
    from mythgauntlet.data.edhrec import EdhrecCard, lift_map

    cards = [
        EdhrecCard("Sol Ring", "topcards", 0.4, 900, 1000),
        EdhrecCard("Unmeasured Card", "topcards", None, None, None),
    ]
    assert lift_map(cards) == {"sol ring": 0.4}


def test_lift_map_normalizes_dfc_front_face():
    from mythgauntlet.data.edhrec import EdhrecCard, lift_map

    cards = [EdhrecCard("Birgi, God of Storytelling // Harnfel, Horn of Bounty",
                         "topcards", 0.2, 400, 1000)]
    assert lift_map(cards) == {"birgi, god of storytelling": 0.2}


def test_every_archetype_role_is_a_role_the_module_scores():
    """A typo'd role name would sit in the table doing nothing, silently.

    Same lock-step class as the theme taxonomy: the table and `ROLE_TARGETS` are edited by
    different hands (a calibration script regenerates one) and a key present in one and
    absent from the other fails without any symptom.
    """
    for theme, roles in redundancy.ARCHETYPE_ROLE_TARGETS.items():
        unknown = set(roles) - set(redundancy.ROLE_TARGETS)
        assert not unknown, f"{theme} targets roles that do not exist: {sorted(unknown)}"
