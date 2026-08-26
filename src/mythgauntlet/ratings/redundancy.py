"""Redundancy-based cut candidates: what the deck has too MUCH of.

The advisor needs a pool of cards worth cutting. The obvious heuristic — cut the
least-played card — is a trap. What sits at the bottom of a popularity ranking is pet
cards, silver bullets and utility the deck chose on purpose; those are the cards you
least want to lose. The cards actually worth cutting are the *redundant* ones: the
eleventh ramp piece in a deck that wanted ten.

So redundancy here is a property of the DECK, not of the card. A card is a cut candidate
when the functional role it fills is over-supplied relative to that role's target, and it
is a weak contributor to that role. A card with no recognised functional role is
`protected`: it can never be redundant, and it sorts to the back of the pool.

Gold set (spec: docs/SPEC_redundancy.md; role strengths and scores are measured against the
real `tags.analyze` and the live ROLE_TARGETS, not assumed). Deck context: ramp supply 18.0
(target 14 -> oversupply 4.0), removal supply 3.0 (target 4 -> oversupply 0.0).

| card (abridged oracle text)                            | role    | over | within | score |
|--------------------------------------------------------|---------|------|--------|-------|
| Llanowar Elves "{T}: Add {G}."                           | ramp    | 4.0  | 1.0    | 2.00  |
| Worn Powerstone "enters tapped. {T}: Add {C}{C}."        | ramp    | 4.0  | 2.0    | 1.33  |
| Cultivate "Search ... two basic land cards ... tapped"   | ramp    | 4.0  | 3.0    | 1.00  |
| Swords to Plowshares "Exile target creature."            | removal | 0.0  | 1.0    | 0.00  |
| pet card "Whenever a face-down creature ... scry 1."     | None    | 0.0  | 0.0    | 0.00  |

Cut order: Llanowar Elves, Worn Powerstone, Cultivate, Swords to Plowshares, pet card —
monotone in within-role strength across the three ramp spells. The last two rows are the
point: under the old popularity rule the pet card was the FIRST cut.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from mythgauntlet.model.card import Card
from mythgauntlet.model.deck import ResolvedDeck
from mythgauntlet.semantics import tags
from mythgauntlet.semantics.model import EffectVector

# What "too much of this role" means, CALIBRATED against real decks — the 60th percentile
# of what 120 corpus decks actually supply. Regenerate with `python scripts/role_targets.py`
# (`--check` diffs against this table).
#
# These used to be the BUILDER's slot plan (playstyle.DEFAULT_SLOTS), i.e. the app's opinion
# of a deck it is about to construct. That is the wrong baseline for judging a deck someone
# already owns, and measuring showed why: the plan sits BELOW the population median for ramp
# and draw and ABOVE it for removal and wipe —
#
#     role          plan   median supply
#     ramp            10            12.0
#     draw            10            14.5
#     removal          7             4.0
#     wipe             4             3.0
#     counterspell     3             0.0
#
# — so nearly every deck read as draw/ramp-oversupplied and essentially none ever read as
# removal-oversupplied. The cut pool came out systematically lopsided: draw 48.7% and ramp
# 34.5% of all suggestions against removal 1.5% and wipe 1.0%. That is an artifact of the
# baseline, not a judgement about any deck.
#
# p60 (not p50) so a role must clear a modest evidential bar before counting as over-served;
# swept against cut-pool balance, where p60 is the knee and p75 barely improves on it while
# pushing targets so high that little would ever flag. After: top role 32.8%, draw+ramp
# 57.8%, removal+wipe 17.1%.
#
# `counterspell` = 3 is now DERIVED rather than borrowed from the protection slot, which
# closes the calibration gap this module shipped with. A floor of 2 applies because the
# median deck runs ZERO counterspells and "any counterspell is redundant" is obviously wrong.
#
# `tutor` = 4, was 2. That p60 was measured under a `DECKS = 120` cap in the generator while
# the corpus has since reached 499; re-measured over all of them tutor is 4.0 and every other
# role is unchanged, so the cap looked harmless right up until it wasn't. Tutors were judged
# against HALF their real population target and the module over-flagged them accordingly:
# 13.8% of every cut suggestion before, 10.6% after, with the pool changing on 16% of decks.
# `--check` could not catch it because it re-measured under the same cap the constant came
# from — see the note on `DECKS` in `scripts/role_targets.py`.
ROLE_TARGETS: dict[str, int] = {
    "ramp": 14,
    "draw": 16,
    "removal": 4,
    "wipe": 3,
    "counterspell": 3,
    "finisher": 2,
    "tutor": 4,
}


# What "too much of this role" means FOR A DECK PLAYING TO IT, where that differs from the
# population. Measured the same way as ROLE_TARGETS - the p60 of real supply - but over only
# the corpus decks detected as each archetype. Regenerate with
# `python scripts/archetype_role_targets.py` (`--check` diffs, `--audit` shows every
# candidate cell and the gate that rejected it).
#
# THE TABLE EXISTS BECAUSE ONE BASELINE CANNOT JUDGE EVERY DECK. `counterspell`'s population
# target is 3 supply units - the weight of a SINGLE card, because the median corpus deck runs
# zero - while the 24 corpus decks that are actually spellslinger decks supply a p60 of 12.
# Each was therefore scored 3x-to-9x over in counterspells and its interaction became the cut
# pool: the module told a Prismari deck to cut Flusterstorm and Mental Misstep, its two best
# counterspells. Same shape as "cut Eaten by Spiders from the spider deck", one level up -
# the earlier fix chose WHICH counterspell to offer, and could not stop the role being
# targeted at all.
#
# IT ONLY EVER RAISES A TARGET. A cell is baked only where the archetype supplies MORE than
# the population; there is no lowering half. The defect being fixed is false-positive cut
# suggestions, and a lower target manufactures more of them.
#
# Three gates, all measured over 499 corpus decks (full derivation in the script): at least
# 20 decks carry the theme; both halves of those decks independently exceed the population
# target; and the archetype wants at least 3 more supply units than the population. Five
# cells survive out of every candidate, and each is Magic-plausible on its face.
ARCHETYPE_ROLE_TARGETS: dict[str, dict[str, int]] = {
    "chaos": {"draw": 28},
    "draw_matters": {"counterspell": 9},
    "landfall": {"ramp": 23},
    "spellslinger": {"counterspell": 12, "draw": 26},
}


def targets_for(
    themes: Iterable[str] | None,
    base: dict[str, int] | None = None,
) -> dict[str, int]:
    """Role targets for a deck known to be playing `themes`.

    THIS IS THE CONTRACT, and its shape is the point. Archetype names arrive as PLAIN
    STRINGS. Detecting them is `deck_themes.detect_deck_themes`, which lives in Forge - a
    different process, whose modules are not on this engine's path - so the engine cannot
    import it and does not try. The caller detects; the engine is told. An unknown name is
    ignored rather than raising, so a Forge that learns a new archetype tomorrow degrades to
    the population baseline instead of breaking the advisor.

    Pass the deck's OWN detected themes, not `merge_themes`' output. The merged list
    deliberately retains commander themes the deck does NOT support (its tier 3), and raising
    a target for a plan the deck is not actually executing would re-open this bug from the
    other side - the deck would be allowed an oversupply it never had. It is also the signal
    the table was calibrated against, so anything else applies the numbers to a different
    measurement than produced them.

    Merges by MAX: with several archetypes, a role is judged against the most permissive
    target any of them earns. Under-flagging is the safe direction here, and a deck holding
    two archetypes has two plans to feed.
    """
    targets = dict(ROLE_TARGETS if base is None else base)   # never mutate the caller's dict
    for theme in themes or ():
        for role, target in ARCHETYPE_ROLE_TARGETS.get(theme, {}).items():
            targets[role] = max(targets.get(role, 0), target)
    return targets


def card_roles(ev: EffectVector) -> dict[str, float]:
    """The functional roles a card fills, and how strongly it fills each.

    An empty dict means the card has no role this module recognises — a pet card, a
    silver bullet, or something the rung-1 EffectVector simply can't see. That is treated
    as "never redundant", not as "worthless": the honest under-count, not a confident
    guess (see `score_card`).
    """
    roles = {
        "ramp": float(ev.ramp_sources) + (2.0 if ev.fetches_land else 0.0),
        "draw": float(ev.draw_cards) + 1.5 * ev.engine_draw,
        "removal": float(ev.removal),
        "wipe": 3.0 if ev.board_wipe else 0.0,
        "counterspell": 3.0 if ev.counterspell else 0.0,
        "tutor": 2.0 if ev.tutor else 0.0,
        "finisher": (
            2.0 * ev.overrun_pump
            + (3.0 if ev.overrun_scales else 0.0)
            + (3.0 if ev.grants_storm else 0.0)
            + (2.0 if ev.scaling_burn else 0.0)
            + (2.0 if ev.cheats_creatures else 0.0)
        ),
    }
    return {role: strength for role, strength in roles.items() if strength > 0.0}


def role_supply(resolved: ResolvedDeck) -> dict[str, float]:
    """How much of each role the deck's nonland spells supply, counts included.

    Commanders are excluded on purpose: the commander is never a cut candidate, and
    counting it would inflate the very role it defines, making the deck look over-supplied
    in its own strategy.
    """
    supply: dict[str, float] = {}
    for card, count in resolved.cards:
        if card.is_land:
            continue
        for role, strength in card_roles(tags.analyze(card)).items():
            supply[role] = supply.get(role, 0.0) + strength * count
    return supply


@dataclass(frozen=True)
class RedundancyScore:
    """Why one card is (or isn't) a cut candidate."""

    card: Card
    role: str | None       # the role it is most over-supplied in; None when roleless
    oversupply: float      # supply[role] - target[role], clamped at 0.0
    within_role: float     # this card's own strength in that role
    score: float           # higher = better cut candidate
    protected: bool        # roleless: never redundant, sorts last


def score_card(
    card: Card,
    supply: dict[str, float],
    targets: dict[str, int] | None = None,
) -> RedundancyScore:
    """Score one card's redundancy against the deck's role supply.

    The card is judged on the role it is MOST over-supplied in. The score combines two
    ideas that pull in opposite directions:

      score = oversupply / (1 + within_role)

    Oversupply raises it — a role the deck has ten too many of is where cuts should come
    from. Within-role strength LOWERS it, because once you've decided ramp is over-served
    you cut the worst ramp spell, not the best one.

    THE SHAPE IS A DESIGN CHOICE THAT MEASUREMENT CANNOT SETTLE, and an earlier version of
    this docstring was too confident about it. `oversupply * within_role` — the inverse —
    was called "a defect, not an approximation" here. Measured over 20 corpus decks it is
    indistinguishable: mean total advisor gain 164.38 against this shape's 165.42 across
    four sim seeds, with the per-seed spread (79 to 231) an order of magnitude larger than
    the difference. A single seed favoured the inverse by 11%, which is noise.

    Nor is the Magic argument one-sided. `within_role` measures DEDICATION to the role, not
    card quality: a high score means a pure ramp spell, a low one a hybrid doing other work
    too. On Atraxa the inverse cuts Crop Rotation / Rampant Growth / Farseek and keeps
    Crystalline Crawler and Biophagus, which also serve the counters plan — a defensible
    answer. Only 1 of 5 sampled decks produced a different pool at all.

    Kept as-is because nothing measured argues for changing it, not because it is proven.

    A card whose roles are all at or under target scores 0.0 — correctly, it is not
    redundant at all.
    """
    if targets is None:            # `or` would silently ignore a deliberate empty dict
        targets = ROLE_TARGETS
    roles = card_roles(tags.analyze(card))
    if not roles:
        return RedundancyScore(card, None, 0.0, 0.0, 0.0, protected=True)

    # Highest oversupply wins; ties break on role name so the choice is deterministic.
    best_role, best_over, best_within = None, -1.0, 0.0
    for role in sorted(roles):
        over = max(0.0, supply.get(role, 0.0) - float(targets.get(role, 0)))
        if over > best_over:
            best_role, best_over, best_within = role, over, roles[role]

    best_within += _efficiency(card)
    return RedundancyScore(
        card=card,
        role=best_role,
        oversupply=best_over,
        within_role=best_within,
        score=best_over / (1.0 + best_within),
        protected=False,
    )


# Mana value at or above which a card earns no efficiency credit, and the credit a free
# spell earns. Deliberately small — this refines an ORDER, it must not swamp `oversupply`.
_EFFICIENCY_CAP = 4
_EFFICIENCY_WEIGHT = 0.5


def _efficiency(card: Card) -> float:
    """Within-role quality from mana cost, because the role tag alone supplies none.

    `card_roles` returns a FIXED strength per role, so `within_role` is constant for four of
    the seven roles — measured over 40 corpus decks: counterspell 3.0 on all 54 cards,
    removal 1.0 on all 167, tutor 2.0 on all 51, wipe 3.0 on all 49. For those roles
    `oversupply / (1 + within_role)` is a per-role constant, so the module's central promise
    — "you cut the worst ramp spell, not the best one" — was simply not implemented: every
    card in the role tied and the ordering fell through to the least-played tiebreak.

    That is how a Prismari spellslinger deck came to be told to cut **Flusterstorm** and
    **Mental Misstep**, its two best counterspells, ahead of a 3-mana Mana Sculpt.

    Cost is the honest signal available at rung 1: within one role, the cheaper card is the
    better one (Swords to Plowshares over a five-mana removal spell; Flusterstorm over Mana
    Sculpt). Cheap cards earn a higher `within_role`, which LOWERS their cut score, so the
    expensive member of an over-served role is offered first. It is a refinement, not a
    quality model — it cannot tell a good three-drop from a bad one.
    """
    mv = getattr(card, "mana_value", None)
    if mv is None:
        return 0.0
    return max(0, _EFFICIENCY_CAP - mv) * _EFFICIENCY_WEIGHT


def _rank_key(card: Card) -> int:
    """EDHREC rank for tie-breaking, with unknown treated as least-played.

    `card.edhrec_rank or 10**9` reads the same and is wrong: it maps rank 0 to unknown.
    Same bug the collection pool already fixed once.
    """
    return card.edhrec_rank if card.edhrec_rank is not None else 10**9


def _normalize_lift_name(name: str) -> str:
    """Lookup key for matching `lift` across the Forge/engine process boundary.

    Forge's `edhrec_lift.normalize_name` (front face, casefolded, whitespace collapsed) is
    the convention a caller's `lift` dict is built under — Forge is the only realistic
    producer of this data (see `rank_redundant`'s docstring). `card.name` here is the
    engine's own exact-cased display name, so the lookup must apply the SAME rule or a
    `lift` dict built by Forge would silently match nothing and this whole tiebreak would
    be a permanent, undetectable no-op — exactly the kind of quiet failure this repo's
    process-boundary contracts (e.g. `commander_slug`, pinned by
    `test_slug_matches_the_engine_implementation`) exist to prevent.
    """
    return " ".join(name.split(" // ")[0].casefold().split())


def _lift_key(card: Card, lift: dict[str, float] | None) -> float:
    """EDHREC synergy for tie-breaking, most-generic-staple first (KNOWN OPEN S12).

    `lift` is a commander-relative signed fraction from `mythgauntlet.data.edhrec` — negative
    means "this card is played more OUTSIDE this commander's decks than in them" (a generic
    staple, safe to cut), positive means it concentrates on decks with this commander (this
    deck's own plan). Ascending sort puts the most negative first, i.e. offered as a cut
    before a positive-lift card at the same redundancy score.

    A missing `lift` (caller didn't supply one) or a card absent from it (EDHREC's page lists
    only ~250 cards, see `lift_stats.py`'s measured 16-76% coverage) both return 0.0 — NEUTRAL,
    not "safe to cut". Treating an unmeasured card as a known staple would be exactly the
    confident-fabrication failure this repo avoids elsewhere (`edhrec_lift.py`'s "unknown
    outranks measured-negative" rule is the same judgment call in the opposite direction).
    A 0.0 tie falls through to the existing `_rank_key` least-played tiebreak unchanged, so
    supplying no `lift` (every caller before this) reproduces the prior ordering byte-for-byte.

    This is the tiebreak S12 (`docs/ROADMAP.md`) flagged as undecided when nothing is
    over-supplied: `oversupply` is 0.0 for every roled card, so `score` ties across the whole
    pool and ordering fell through entirely to least-played — the rule this module replaced.
    Two PRIOR fixes (un-clamped headroom; inverted tiebreak) were measured and rejected; this
    is a third, independent signal (EDHREC lift, not role/oversupply) tried specifically
    because it comes from data neither prior attempt touched.

    IT ALSO CLOSES S13'S CANARY, UNMODIFIED — measured 2026-08-26, not designed for it. S13
    is a DIFFERENT tie: `card_roles` gives counterspell/wipe a fixed per-card strength, so two
    same-cost counterspells score identically once the role is genuinely over target (not the
    0.0 case above). `_lift_key` sits in the sort key for EVERY tie in `rank_redundant`, not
    only the degenerate one, so it resolves this shape too, for free. Swept over the 255
    corpus decks with a cached commander page: the top redundant pick changes for 66, and on
    the 40 numerically-comparable cases (both old and new picks measured), the new pick's
    lift is lower every time — 0 regressions, same class of result S12 measured for its own
    case. Reproduces the real S13 canary (`archidekt-13708248`, Omo/landfall): without lift,
    Flusterstorm — unmeasured on Omo's own EDHREC page — is offered over An Offer You Can't
    Refuse (measured there at lift -0.07) purely because it is the less-played of the two on
    the trailing tiebreak; with lift wired (the live `/advise` route has passed it since S12
    shipped), the generic staple is offered first instead. Coverage is still the honest
    partial figure `lift_stats.py` already documents (16-76%) — a deck whose commander has no
    cached EDHREC page gets none of this, and the underlying fixed-strength scoring in
    `card_roles` is untouched. See ROADMAP.md S13 for the full write-up.
    """
    if not lift:
        return 0.0
    return lift.get(_normalize_lift_name(card.name), 0.0)


def rank_redundant(
    resolved: ResolvedDeck,
    k: int,
    *,
    targets: dict[str, int] | None = None,
    lift: dict[str, float] | None = None,
) -> list[Card]:
    """The deck's `k` best cut candidates, most redundant first.

    Ordering: redundant cards by score (descending), then by EDHREC lift ascending (see
    `_lift_key` — most generic-staple first, a no-op when `lift` is None or a card is
    unmeasured), then — among cards still tied — the least-played one first, since that is
    the safest of a set of interchangeable pieces. Protected (roleless) cards always sort
    last and are only returned when there aren't enough scored cards to fill `k`, so a deck
    of pure pet cards still yields a pool rather than nothing.

    `lift` is a plain `{card name: synergy}` dict, exactly the contract `targets_for(themes)`
    already uses for archetype names: this module is pure and offline, so it does not fetch
    EDHREC itself (mirrors why `targets_for` is *told* archetypes rather than detecting them).
    Build one from `mythgauntlet.data.edhrec.fetch_commander`/`parse_commander_page` and pass
    it in; omit it for the pre-existing, network-free ordering.

    Deterministic: equal scores, equal lift and equal ranks fall through to card name.
    """
    k = max(1, k)
    supply = role_supply(resolved)

    scored: list[RedundancyScore] = []
    seen: set[str] = set()             # Card is a mutable dataclass -> unhashable; key by name
    for card, _count in resolved.cards:
        if card.is_land or card.name in seen:
            continue
        seen.add(card.name)
        scored.append(score_card(card, supply, targets))

    candidates = [s for s in scored if not s.protected]
    protected = [s for s in scored if s.protected]
    candidates.sort(
        key=lambda s: (-s.score, _lift_key(s.card, lift), -_rank_key(s.card), s.card.name)
    )
    protected.sort(key=lambda s: s.card.name)

    return [s.card for s in (candidates + protected)[:k]]
