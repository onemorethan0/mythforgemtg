"""Upgrade advisor: measured card swaps, not popularity (roadmap Phase 8).

Given a deck and a candidate pool (e.g. the cards you OWN — Myth Suite C4), find the swaps
that most improve a chosen Power Profile axis, VERIFIED by re-running the analysis (ablation),
not by inclusion rates. This is deterministic: `analyze_deck` is a pure function of (deck,
cfg), so a swap's delta is a clean measured difference, never simulation noise.

v2 scope (2026-07-21): single-card swaps, one target axis at a time, but the cut is now
chosen PER candidate — each add is tested against a small pool of the deck's weakest nonland
cards and keeps whichever cut it improves the axis most from (an add that wants to displace a
weak ramp piece no longer has to fight the one globally-weakest creature). `cut_pool=1`
reproduces the MVP's single-global-cut behaviour exactly.

Cross-axis (2026-11-08): a swap must also leave the WHOLE deck better — every measured axis
is netted in units of its spread among real decks (card_impact's rule), and swaps rank by
that net. Before, only the target axis was read, so the advisor would cut another axis's best
card to prop up the weakest one and report the deck as improved.

Honest limits still open: multi-card packages and general (non-owned) candidate pools.
"""

from __future__ import annotations

import dataclasses
import math
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from mythgauntlet.data.scryfall import CardDb
from mythgauntlet.model.card import Card
from mythgauntlet.model.collection import Collection
from mythgauntlet.model.deck import ResolvedDeck
from mythgauntlet.ratings import redundancy, swap_brief
from mythgauntlet.ratings.analysis import DeckAnalysis, analyze_deck
from mythgauntlet.semantics import tags
from mythgauntlet.semantics.commander_lens import CommanderLens, build_lens
from mythgauntlet.semantics.model import EffectVector
from mythgauntlet.semantics.store import SemanticsStore
from mythgauntlet.sim.tier0 import SimConfig

# How the cut pool is chosen. `redundant` is the default and the only one worth using;
# `popularity` is the original rule, kept because the golden-master tests pin its exact
# ordering and re-analysis counts, and because it is the honest fallback for a deck whose
# cards the semantics layer cannot read at all. Defined here, above AdviceReport, because
# a dataclass field default is evaluated at class-definition time.
CUT_REDUNDANT = "redundant"
CUT_POPULARITY = "popularity"
CUT_STRATEGIES = (CUT_REDUNDANT, CUT_POPULARITY)


def owned_candidates(card_db: CardDb, resolved: ResolvedDeck, collection: Collection) -> list[Card]:
    """The owned, in-identity, non-land, not-already-in-deck pool `advise()` tests as
    adds — factored out of the `/advise` HTTP route (2026-09-15) so a second caller (the
    Deck Mentor's `suggest_swap` tool) can't quietly drift from this exact selection rule,
    this repo's own most-repeated bug class (see CLAUDE.md's running list of "two opinions
    on one screen" incidents). Behaviour-preserving extraction — the route's own inline
    loop moved here unchanged, byte-for-byte, not reinvented.

    EDHREC-rank sorted (unranked last), matching `_gauntlet_advise`'s "best owned cards
    first" comment.
    """
    ci_source = resolved.commanders or [c for c, _ in resolved.cards]
    deck_ci = set().union(*[set(c.color_identity) for c in ci_source]) if ci_source else set()
    in_deck = {c.name for c, _ in resolved.cards} | {c.name for c in resolved.commanders}
    candidates = []
    for owned_name in collection.counts:
        card = card_db.get(owned_name)
        if card is None or card.name in in_deck or card.is_land:
            continue
        if set(card.color_identity) - deck_ci:
            continue
        candidates.append(card)
    candidates.sort(key=lambda c: (c.edhrec_rank or 10**9))
    return candidates


def _speed_score(a: DeckAnalysis) -> float:
    return a.report.goldfish_kill_rate * 100.0


def _resilience_score(a: DeckAnalysis) -> float:
    return a.resilience.resilience_score if a.resilience is not None else 0.0


def _clock_score(a: DeckAnalysis) -> float:
    """EARLINESS of the goldfish kill, 0-100, higher = earlier.

    `speed` is the SHARE of games that kill within the horizon -- not how early: Shelob reads
    speed 96.7 with a turn-9 clock, so no swap can ever raise it and "make it faster" had no
    axis to target (a ceiling swap whose own brief showed kill_turn 9.32 -> 9.45, i.e. SLOWER,
    was reported for it). This is the missing measure:

        clock = 100 * (horizon - avg_kill_turn) / horizon      clamped to [0, 100]

    `horizon` is the analysis horizon (`report.turns`, 12 by default) and `avg_kill_turn` the
    mean kill turn OVER THE GAMES THAT KILL; no kill at all scores 0. A turn-1 average is ~92,
    turn 6 is 50, the horizon is 0. It is deliberately a LENS for "faster", not a profile axis
    that competes with the others (see `PROFILE_AXES` / `weakest_axis`): on this scale the
    median corpus deck (avg kill ~10.1 of 12) scores ~16, so it would be "the weakest axis"
    of nearly every deck and say nothing about it.
    """
    turn = a.report.avg_kill_turn
    horizon = a.report.turns
    if turn is None or horizon <= 0:
        return 0.0
    return max(0.0, min(100.0, 100.0 * (horizon - turn) / horizon))


# axis name -> (extractor, label). Every score is ~0-100, higher = better, so they compare.
AXES: dict[str, tuple[Callable[[DeckAnalysis], float], str]] = {
    "consistency": (lambda a: a.report.consistency_score, "Consistency"),
    "speed":       (_speed_score, "Speed"),
    "resilience":  (_resilience_score, "Resilience"),
    "interaction": (lambda a: a.interaction.score, "Interaction"),
    "ceiling":     (lambda a: a.ceiling.score, "Ceiling"),
    "clock":       (_clock_score, "Clock"),
}

# The axes that describe the deck's PROFILE and compete for "weakest": everything except the
# `clock` lens. `weakest_axis`, `card_impact`'s per-axis movement sweep and the corpus
# reference all use this, so adding `clock` to AXES (so `advise`/`suggest_swap` can target it)
# changes none of their behaviour.
PROFILE_AXES: tuple[str, ...] = tuple(ax for ax in AXES if ax != "clock")


def axis_score(analysis: DeckAnalysis, axis: str) -> float:
    return AXES[axis][0](analysis)


def weakest_axis(analysis: DeckAnalysis) -> str:
    """The lowest-scoring measurable PROFILE axis (skips resilience if it wasn't computed).

    Never returns `clock`: it is a lens for "make it faster", on a scale where nearly every
    deck scores low (see `_clock_score`), so letting it compete would make it the weakest
    axis of almost every deck. A caller who wants it asks for it by name."""
    candidates = [
        ax for ax in PROFILE_AXES if ax != "resilience" or analysis.resilience is not None
    ]
    return min(candidates, key=lambda ax: axis_score(analysis, ax))


def _axis_relevance(ev: EffectVector, axis: str) -> float:
    """A cheap PRIOR for how likely a card is to move `axis`, from its rung-1 EffectVector.

    This only decides WHICH candidates are worth the expensive ablation sim — it is never
    the verdict (the measured delta is). Without it the advisor tested the most *popular*
    owned cards, so a Ceiling target kept re-simulating staples (ramp/removal) that can't
    raise a combo/finisher ceiling, and reported "no owned card improved Ceiling" after
    evaluating 8 irrelevant cards. Ranking by axis-relevant signals puts the finishers /
    interaction / tutors that could actually move the axis at the front of the eval budget."""
    if axis == "ceiling":
        return (
            2.0 * ev.overrun_pump + (3.0 if ev.overrun_scales else 0.0)
            + (3.0 if ev.grants_storm else 0.0)
            + ev.mana_on_cast + ev.magecraft_damage + ev.cast_damage
            + (2.0 if ev.scaling_burn else 0.0)
            + float(ev.ritual_mana) + float(ev.spell_cost_reduction)
            + (2.0 if ev.cheats_creatures else 0.0)
            + (1.5 if ev.tutor else 0.0)
        )
    if axis == "interaction":
        return (
            2.0 * ev.removal + (3.0 if ev.board_wipe else 0.0)
            + (3.0 if ev.counterspell else 0.0)
        )
    if axis == "consistency":
        return (
            (2.0 if ev.tutor else 0.0) + 1.5 * ev.engine_draw
            + ev.draw_cards + 0.5 * ev.ramp_sources
        )
    if axis == "speed":
        return (
            1.5 * ev.ramp_sources + (2.0 if ev.fetches_land else 0.0)
            + ev.mana_on_cast + (2.0 if ev.cheats_creatures else 0.0)
        )
    if axis == "resilience":
        return (
            1.5 * ev.removal + (2.0 if ev.counterspell else 0.0)
            + 1.5 * ev.engine_draw + (1.0 if ev.tutor else 0.0)
        )
    return ev.impact


def _creature_subtypes(card: Card) -> set[str]:
    """The creature subtypes on a card's type line (the words after the em-dash)."""
    tl = card.type_line or ""
    for dash in ("—", "-"):
        if dash in tl:
            return {w for w in tl.split(dash, 1)[1].split() if w[:1].isalpha()}
    return set()


@dataclass
class CommanderWants:
    """What the commander's mechanic steers the deck toward — a candidate-selection prior.

    So a Kaalia deck tests big Angels/Demons/Dragons it can actually cheat out, not a
    ceiling-irrelevant staple it will hard-cast on turn nine."""

    cheats_creatures: bool = False      # puts creatures onto the battlefield from hand/yard
    cheat_types: set[str] = field(default_factory=set)  # the types it can cheat (empty = any)
    wants_big: bool = False             # rewards high-mana-value creatures (cheat/reanimate)
    tribes: set[str] = field(default_factory=set)       # tribal payoff types it buffs/cares about

    @property
    def active(self) -> bool:
        return self.cheats_creatures or bool(self.tribes)


# "put an Angel, Demon, or Dragon creature card ... onto the battlefield" (Kaalia),
# "put a creature card ... onto the battlefield" (any), reanimator return-to-battlefield.
_CHEAT_RE = re.compile(
    r"put (?:an?|up to \w+|target)?\s*(?P<types>[A-Za-z,\s]*?)\s*creature cards?\b"
    r"[^.]*?onto the battlefield",
    re.I,
)
_REANIMATE_RE = re.compile(
    r"return (?:target |[A-Za-z,\s]*?)creature cards?[^.]*?from[^.]*?graveyard[^.]*?"
    r"to the battlefield",
    re.I,
)
# Tribal payoffs: "other Goblins you control", "Dragon creatures you control get".
_TRIBAL_RES = (
    re.compile(r"other ([A-Z][a-z]+)s? (?:you control|creatures)"),
    re.compile(r"([A-Z][a-z]+) creatures you control"),
)


def commander_wants(commanders: Iterable[Card]) -> CommanderWants:
    """Extract the commander's mechanical direction as a candidate-selection prior."""
    w = CommanderWants()
    for cmd in commanders:
        text = cmd.oracle_text or ""
        m = _CHEAT_RE.search(text)
        if m or _REANIMATE_RE.search(text):
            w.cheats_creatures = True
            w.wants_big = True
            if m:
                # Capitalized words in the matched span are the cheatable creature types.
                w.cheat_types |= {t for t in re.findall(r"[A-Z][a-z]{2,}", m.group("types"))}
        for rx in _TRIBAL_RES:
            w.tribes |= set(rx.findall(text))
    # A tribal commander's OWN subtypes count too (e.g. an Elf lord that says "Elves").
    return w


def _commander_affinity(card: Card, w: CommanderWants) -> float:
    """How well a candidate fits the commander's direction (0 = neutral)."""
    if not w.active or not card.is_creature:
        return 0.0
    subs = _creature_subtypes(card)
    score = 0.0
    if w.cheats_creatures:
        if w.cheat_types:
            if subs & w.cheat_types:
                # On-type AND big is the whole point of a cheat commander (Kaalia).
                score += 4.0 + 0.6 * max(0, card.mana_value - 3)
        else:
            # Cheats/reanimates ANY creature — reward the fatties worth cheating.
            score += (2.0 + 0.6 * max(0, card.mana_value - 4)) if card.mana_value >= 5 else 0.5
    if w.tribes and (subs & w.tribes):
        score += 3.0
    return score


def _prioritize(cands: list[Card], axis: str, wants: CommanderWants | None = None) -> list[Card]:
    """Order candidates by combined axis-relevance + commander-affinity (most first),
    popularity as tie-break.

    Two priors steer WHICH candidates are worth the expensive ablation sim: relevance to
    the TARGET axis, and fit with the COMMANDER's mechanic (so a Kaalia deck tests the big
    Angels/Demons/Dragons it can cheat, not a card it can't). The measured delta remains
    the only verdict. If nothing scores on either prior, the incoming (popularity) order is
    preserved so the advisor still tests the caller's best-guess cards."""
    wants = wants or CommanderWants()
    scored = [
        (c, _axis_relevance(tags.analyze(c), axis) + _commander_affinity(c, wants))
        for c in cands
    ]
    if not any(s > 0 for _, s in scored):
        return cands
    scored.sort(key=lambda cs: (-cs[1], cs[0].edhrec_rank or 10**9, cs[0].name))
    return [c for c, _ in scored]


def _explain(card: Card, axis: str, wants: CommanderWants) -> str:
    """A short, honest rationale for WHY an add helps the target axis.

    Describes the card's FUNCTION (from its rung-1 EffectVector) + how it fits the
    commander — the mechanism behind the measured gain. The verdict is still the
    measured delta; this explains the likely why, it doesn't assert the number."""
    ev = tags.analyze(card)
    subs = _creature_subtypes(card)
    bits: list[str] = []

    # Commander fit first (most salient — answers "can I even use this?").
    if wants.cheats_creatures and card.is_creature and (
        not wants.cheat_types or (subs & wants.cheat_types)
    ):
        typ = next(iter(subs & wants.cheat_types), "creature") if wants.cheat_types else "creature"
        big = "big " if card.mana_value >= 6 else ""
        bits.append(f"a {big}{typ.lower()} your commander can cheat into play")
    elif wants.tribes and (subs & wants.tribes):
        bits.append(f"on-tribe ({next(iter(subs & wants.tribes))}) for your commander")

    # Axis mechanism.
    if axis == "ceiling":
        if ev.overrun_pump or ev.overrun_scales:
            bits.append("a one-shot team finisher")
        elif ev.grants_storm or ev.mana_on_cast or ev.magecraft_damage:
            bits.append("fuel for an explosive spell chain")
        elif ev.scaling_burn:
            bits.append("a scalable X-damage kill")
        elif ev.tutor:
            bits.append("tutors toward your finisher")
    elif axis == "interaction":
        if ev.board_wipe:
            bits.append("a board wipe")
        elif ev.removal:
            bits.append("targeted removal your deck was short on")
        elif ev.counterspell:
            bits.append("a counterspell")
    elif axis == "consistency":
        if ev.tutor:
            bits.append("a tutor that finds your key pieces")
        elif ev.engine_draw:
            bits.append("a repeatable draw engine")
        elif ev.draw_cards:
            bits.append("extra card draw to smooth your draws")
        elif ev.ramp_sources:
            bits.append("mana consistency")
    elif axis == "speed":
        if ev.ramp_sources or ev.fetches_land:
            bits.append("mana acceleration to deploy earlier")
        elif ev.cheats_creatures:
            bits.append("puts threats down ahead of curve")
    elif axis == "resilience":
        if ev.counterspell or ev.removal:
            bits.append("interaction that protects your plan")
        elif ev.engine_draw:
            bits.append("card flow to rebuild after a wipe")

    if not bits:
        return f"Measured to raise {axis}."
    txt = "; ".join(bits)
    return txt[0].upper() + txt[1:] + "."


def _measured_phrase(base: DeckAnalysis, swap: DeckAnalysis) -> str:
    """The concrete sim change behind a swap: how the measured headline metrics moved
    (kill speed, share of games that close on the clock). Tier-2 causal 'why' — cites
    what the re-simulation actually did, not the card's general role."""
    bits: list[str] = []
    b, s = base.report.avg_kill_turn, swap.report.avg_kill_turn
    if b is not None and s is not None and abs(b - s) >= 0.3:
        d = b - s  # positive = fewer turns = faster
        bits.append(f"kills ~{abs(d):.1f} turns {'sooner' if d > 0 else 'later'}")
    dr = (swap.report.goldfish_kill_rate - base.report.goldfish_kill_rate) * 100
    if abs(dr) >= 3:
        bits.append(f"{dr:+.0f}% of games close on the clock")
    return "; ".join(bits)


@dataclass
class SwapSuggestion:
    add: str
    cut: str
    before: float
    after: float
    reason: str = ""
    # The structured facts behind `reason` — everything this swap is entitled to claim.
    # `reason` stays the deterministic template string and remains the fallback; the brief is
    # what a generated narrative is written FROM and gated AGAINST. See
    # `mythgauntlet.ratings.swap_brief`.
    brief: "swap_brief.SwapBrief | None" = None
    # The target-axis delta split against an empty slot (EMPTY_SLOT), same seeds:
    # add_value - cut_value == delta. None when not measured.
    add_value: float | None = None
    cut_value: float | None = None
    # Every measured profile axis's move for this swap ({axis: after - before}), target
    # included. Resilience is present only when it was simulated for this swap.
    axis_deltas: dict[str, float] = field(default_factory=dict)
    # The fresh-seed re-measurement behind `after` (see `_confirm_swap`): {"seeds", "mean", "se",
    # "search_delta"}. None when confirmation was off or the axis is closed-form (interaction).
    confirmation: dict | None = None
    # The whole-deck verdict: meaningful moves summed in units of each axis's spread among
    # real decks (card_impact._score). Always > 0 for a reported swap.
    net: float | None = None
    # Off-target axes this swap MEANINGFULLY lowers ({axis: delta < 0}), past each axis's
    # noise floor — what the user gives up elsewhere to buy the target gain.
    costs: dict[str, float] = field(default_factory=dict)
    # The axis THIS swap improves (before/after are on it). The report's target unless an auto
    # search fell back to another weak axis (`advise(fallback_axes=...)`).
    axis: str | None = None
    axis_label: str | None = None

    @property
    def delta(self) -> float:
        return self.after - self.before


@dataclass
class AdviceReport:
    axis: str
    axis_label: str
    baseline: float
    cut: str | None            # the single global cut (cut_pool==1); None when per-swap
    suggestions: list[SwapSuggestion]
    evaluated: int             # add candidates considered (backward-compatible meaning)
    analyses: int = 0          # total re-simulations run (candidates x cut options)
    cut_pool: int = 1          # how many cut candidates each add was tested against
    min_delta: float = 0.0     # gain floor a swap had to clear to be reported
    cut_strategy: str = CUT_REDUNDANT   # how that cut pool was chosen
    # Every axis the search accepted a swap on, weakest first ([axis] unless fallback_axes).
    searched_axes: list[str] = field(default_factory=list)


def _cut_candidates(
    resolved: ResolvedDeck,
    k: int,
    strategy: str,
    themes: Sequence[str] = (),
    lift: dict[str, float] | None = None,
    lens: CommanderLens | None = None,
    protect: frozenset[str] = frozenset(),
) -> list[Card]:
    """The `k` cards to offer as cuts, per `strategy`, never one named in `protect`.

    `redundant` asks what the deck has too MUCH of; `popularity` asks what is least played.
    They disagree exactly where it matters: a brew's unpopular pet card is `popularity`'s
    first cut and `redundant`'s last.

    `themes` are the deck's own detected archetypes, and they only reach `redundant` -
    `popularity` has no notion of a role to be over-supplied in. Empty means "judge against
    the population", which is the honest default when the caller cannot detect archetypes.

    `lift` is a `{card name: EDHREC synergy}` map, also `redundant`-only — see
    `redundancy.rank_redundant`. It only ever refines a tie (most usefully S12's degenerate
    case, where nothing is over-supplied and every card ties at score 0.0); omitting it keeps
    the pre-existing least-played tiebreak exactly as it was.
    """
    if strategy == CUT_POPULARITY:
        return [c for c in _weakest_cuts(resolved, k + len(protect))
                if c.name not in protect][:k]
    return [c for c in redundancy.rank_redundant(
        resolved, k + len(protect), targets=redundancy.targets_for(themes), lift=lift,
        lens=lens,
    ) if c.name not in protect][:k]


def _weakest_cuts(resolved: ResolvedDeck, k: int) -> list[Card]:
    """The deck's `k` least-played nonland spells: highest EDHREC rank (unknown = weakest).

    Kept for the `popularity` cut strategy and its golden-master tests. As a way to pick
    cuts it is actively wrong — the least-played cards in a deck are its pet cards and
    silver bullets, which are the ones the pilot put there on purpose. See
    `mythgauntlet.ratings.redundancy` for the rule that replaced it as the default.

    Deterministic: ranks tie-break by name so the same deck always yields the same cut pool.
    """
    nonland = [c for c, _ in resolved.cards if not c.is_land]
    nonland.sort(key=lambda c: (-(c.edhrec_rank or 10**9), c.name))  # weakest first
    return nonland[: max(1, k)]


def _weakest_cut(resolved: ResolvedDeck) -> Card | None:
    """The single most droppable nonland spell (kept for callers/tests of the MVP behaviour)."""
    cuts = _weakest_cuts(resolved, 1)
    return cuts[0] if cuts else None


# A slot that does nothing: cast for free, no effect, no tags, absent from the semantics store.
# Swapping it in for the cut measures what the CUT was doing; swapping the add against it
# measures what the ADD does on its own. A swap's delta is exactly (add - empty) - (cut - empty),
# all at the same seeds. Added 2026-10-23: four different adds into one deck measured
# identically, because the swap delta was mostly the cut and nothing said so.
EMPTY_SLOT = Card(name="(empty slot)", type_line="")


def _swap_variant(resolved: ResolvedDeck, cut: Card, add: Card) -> ResolvedDeck:
    """A copy of the deck with one copy of `cut` replaced by one `add` (size preserved)."""
    new_cards: list[tuple[Card, int]] = []
    for card, count in resolved.cards:
        if card.name == cut.name:
            if count > 1:
                new_cards.append((card, count - 1))
        else:
            new_cards.append((card, count))
    new_cards.append((add, 1))
    return dataclasses.replace(resolved, cards=new_cards)


# Seed-to-seed standard deviation of each axis, MEASURED: the same deck re-analysed at 8
# seeds (runs=150) across corpus decks, which is the run-to-run spread you get from doing
# nothing at all.
#
#   speed        1.73  (max 2.32)      ceiling      2.31  (max 8.30)
#   consistency  0.94  (max 1.17)      resilience   0.00      interaction  0.00
#
# The old flat `min_delta=1.0` default was documented as filtering sim noise but had never
# been checked against it, and it sits BELOW the noise on the two axes that carry it. So the
# advisor was reporting swaps whose measured "gain" is smaller than the variation from
# re-rolling the RNG on an unchanged deck — noise, ranked and presented as advice.
#
# This is a floor, not a significance test: clearing one sigma is not proof, it just stops
# the list filling with results a re-run would reverse. Resilience and interaction are
# computed deterministically, so they keep the caller's floor untouched.
# Run count the values below were measured at. The floor is SCALED to the caller's actual
# `cfg.runs`, because simulation noise falls roughly as 1/sqrt(runs) and a flat constant is
# therefore correct at exactly one run count. It was measured at 150 while every caller uses
# 60 — about 1.6x too low, admitting precisely the noise it exists to exclude.
NOISE_REFERENCE_RUNS = 150

_AXIS_NOISE_FLOOR = {
    # Re-measured after `compute_ceiling` stopped reading a single integer order statistic.
    # The old metric moved only in whole-turn steps, so its seed-to-seed spread was really
    # measuring how often that step flipped; averaging the fastest decile is both finer AND
    # steadier — ceiling 2.98 -> 2.27, speed 2.41 -> 1.88.
    "speed": 1.88,
    "ceiling": 2.27,
    # Re-measured 2026-10-18 after both models changed (`scripts/axis_noise.py --turns 12`,
    # runs=150): consistency is now a smooth-game RATE and resilience a pressure window, both
    # read at the default 12-turn horizon where they are actually targeted. Was 0.92 / 1.06.
    "consistency": 2.83,
    # NOT 0.0. The original sweep called `analyze_deck` WITHOUT `run_resilience`, so
    # resilience was never simulated and its spread read as a clean zero. It is only ever
    # simulated when it IS the target axis — exactly when this floor is consulted — and its
    # real spread there is ~1.24 at runs=150 (~1.91 at runs=60). A floor of zero meant every
    # positive resilience delta passed, so resilience advice was unfiltered noise.
    "resilience": 2.22,
    "interaction": 0.0,
    # `clock` is horizon-relative (100 * (turns - avg_kill_turn) / turns), so its spread depends
    # on the horizon it is read at: measured 2026-09-30 with `scripts/axis_noise.py --turns N`
    # (8 corpus decks x 8 seeds, runs=150): 0.71 at turns=12 (the mentor / analyze / advise
    # default, DEFAULT_ANALYZE_TURNS) and 1.10 at turns=8. 0.71 is baked because the clock is
    # only ever targeted at the default horizon; 0.71 points is ~0.09 of a turn, so in practice
    # the caller's own `min_delta` (default 1.0, ~0.12 turn) is the binding floor. The other
    # floors above were measured at turns=8.
    "clock": 0.71,
}


def _noise_floor(axis: str, runs: int) -> float:
    """The axis's seed-to-seed spread at THIS run count.

    Regenerate the constants with `python scripts/axis_noise.py`; `--check` diffs them.
    """
    base = _AXIS_NOISE_FLOOR.get(axis, 0.0)
    if not base or runs <= 0:
        return base
    return base * math.sqrt(NOISE_REFERENCE_RUNS / runs)


# Interaction is a COUNT of the answers a deck holds (closed-form), so the same number comes back on
# every seed and fresh-seed confirmation proves nothing. A four-player pod test of a package of four
# such swaps on a real Bracket 3 deck (scripts/swap_podcheck.py, 9,600 paired games, 2026-11-11)
# measured no win-rate change (-0.4pp, se 0.6). So the swap is honest about what it is.
INTERACTION_NOTE = ("Interaction is a count of the answers the deck holds, not a simulated result: "
                    "this swap adds an answer, and a pod test of such swaps found no measured "
                    "change in how often the deck wins.")

BASELINE_SEED_STEP = 104729      # extra baseline seeds: cfg.seed + step * (i + 1)
CONFIRM_SEED_STEP = 7919        # fresh seeds: cfg.seed + step * (i + 1), never the search seed
CONFIRM_MIN_FRACTION = 1.0      # a confirmed gain must reach the axis noise floor, as the search's
                                # own bar always did (0.5 let a +1.8 swap through that pooled to +1.0)
CONFIRM_SCREEN_Z = 1.28         # cheap screen on `confirm_seeds` seeds: 90% lower bound > 0
CONFIRM_FINAL_SEEDS = 8         # survivors of the screen are re-measured on this many in all
CONFIRM_FINAL_Z = 1.64          # ...and must clear a 95% lower bound > 0 (a screen alone let
                                # chance through: ~15 candidates are tried, and one consistency
                                # swap that passed 3 seeds at +2.4 re-measured at -0.1)


def _confirm_diffs(resolved: ResolvedDeck, cut: Card, add: Card, axis: str, cfg: SimConfig,
                   store: SemanticsStore, start: int, count: int, base_cache: dict, *,
                   two_card_combos: int = 0, combos_checked: bool = False) -> list[float]:
    """The swap's gain on FRESH seeds number `start` .. `start + count - 1`, paired (the same seed
    for the unswapped and the swapped deck).

    The search tries ~16 adds x ~6 cuts on ONE seed and keeps the best, so its reported gain is a
    maximum over many noisy measurements -- a winner's curse. Measured 2026-11-11 on real decks
    (scripts/advise_holdout.py): consistency swaps reported +7.3/+7.0/+4.7 re-measured at
    +1.1/+0.6/+0.1; a ceiling swap reported +2.6 re-measured at -0.4. Games the choice never saw
    give an unbiased estimate, so THAT is what a suggestion is allowed to claim.

    `base_cache` holds the unswapped deck's score per (seed, axis) so it is paid for once."""
    res = axis == "resilience"
    diffs = []
    swapped = _swap_variant(resolved, cut, add)
    for i in range(start, start + count):
        c2 = SimConfig(turns=cfg.turns, runs=cfg.runs, seed=cfg.seed + CONFIRM_SEED_STEP * (i + 1))
        key = (c2.seed, axis)
        if key not in base_cache:
            base_cache[key] = axis_score(analyze_deck(
                resolved, c2, store, two_card_combos=two_card_combos,
                combos_checked=combos_checked, run_resilience=res), axis)
        a = analyze_deck(swapped, c2, store, two_card_combos=two_card_combos,
                         combos_checked=combos_checked, run_resilience=res)
        diffs.append(axis_score(a, axis) - base_cache[key])
    return diffs


def _mean_se(diffs: list[float]) -> tuple[float, float]:
    mean = sum(diffs) / len(diffs)
    var = sum((d - mean) ** 2 for d in diffs) / (len(diffs) - 1) if len(diffs) > 1 else 0.0
    return mean, math.sqrt(var / len(diffs))


def _passes(diffs: list[float], floor: float, z: float) -> bool:
    mean, se = _mean_se(diffs)
    return mean >= CONFIRM_MIN_FRACTION * floor and mean - z * se > 0


def _commander_identity(resolved: ResolvedDeck) -> frozenset[str]:
    """The deck's legal colour identity: the union across its commander(s)."""
    identity: set[str] = set()
    for commander in resolved.commanders:
        identity.update(getattr(commander, "color_identity", ()) or ())
    return frozenset(identity)


def _is_legal_candidate(card: Card, identity: frozenset[str]) -> bool:
    """Whether `card` may legally go in this deck: format-legal AND in colour identity.

    The advisor had no legality notion at all, so with a collection-shaped candidate pool
    (its documented use: "the cards you OWN") it would tell a mono-green deck to add a blue
    card, or hand back a Commander-BANNED card the user happens to own — swaps that cannot
    be made, ranked alongside real ones, and the better the illegal card the higher it rose.

    Two checks:
      - `commander_legal` is Scryfall's legalities.commander == "legal", so it rejects both
        the ban list (Mana Crypt, Jeweled Lotus, Dockside Extortionist) and cards never in
        the format (acorn/Un-cards, Conspiracy). Carried by slim schema v3.
      - Colour identity per CR 903.4. Colourless cards carry an empty identity and are
        legal in every deck.
    """
    if not getattr(card, "commander_legal", True):
        return False
    if not set(getattr(card, "color_identity", ()) or ()) <= identity:
        return False
    return _land_is_live(card, identity)


_BASIC_FOR_COLOUR = {"W": "plains", "U": "island", "B": "swamp",
                     "R": "mountain", "G": "forest"}
_ALL_BASIC_TYPES = frozenset(_BASIC_FOR_COLOUR.values()) | {"wastes"}


def _land_is_live(card, identity: set[str]) -> bool:
    """Can this land actually find or make mana in THIS deck?

    A fetchland's colour identity is EMPTY and it produces no mana itself, so the identity
    check above admits **every fetchland in Magic into every deck**. Measured on a real pod,
    the advisor offered *Bloodstained Mire* (Swamp/Mountain) to a Simic deck — a card that
    finds nothing there and costs a life for the privilege.

    `deck_builder._land_is_castable` already fixed exactly this for the BUILDER; the advisor
    never got the guard, which is the two-structures-that-must-agree shape this repo keeps
    finding. Same conservative rule: reject only when the card NAMES basic types and none are
    playable here, so a land that names none (Command Tower, Evolving Wilds' "basic land
    card", Myriad Landscape) is kept — it can drop a provably dead land, never one it merely
    fails to understand.
    """
    if "Land" not in (getattr(card, "type_line", "") or ""):
        return True
    produced = getattr(card, "produced_mana", None) or ()
    if any(c in produced for c in identity):
        return True                       # makes on-colour mana directly
    text = (getattr(card, "oracle_text", "") or "").lower()
    named = {t for t in _ALL_BASIC_TYPES if t in text}
    if not named:
        return True                       # says nothing about land types -> keep
    return bool(named & {_BASIC_FOR_COLOUR[c] for c in identity if c in _BASIC_FOR_COLOUR})


def _whole_deck_moves(
    baseline: DeckAnalysis, after: DeckAnalysis, target: str, runs: int,
) -> list:
    """Every measurable axis's move for one swap, as card_impact.AxisMove rows.

    The advisor used to read ONLY the target axis, and picked each add's cut by the biggest
    target gain. That makes it actively drawn to the cut that contributes LEAST to the target,
    which is very often the deck's best card on a different axis: a measured case cut The One
    Ring (consistency) for Kaldra Compleat to raise Ceiling. card_impact already netted the
    axes after the same failure (Chaos Warp, 2026-10-23); the advisor never got that fix.

    Resilience is included only when BOTH analyses simulated it — an unmeasured axis is left
    out, never read as zero. Floors are the run-scaled noise floors the target gate uses.
    """
    from mythgauntlet.ratings.card_impact import AxisMove  # card_impact imports this module

    axes = [ax for ax in PROFILE_AXES
            if ax != "resilience" or (baseline.resilience is not None
                                      and after.resilience is not None)]
    if target not in axes:
        axes.append(target)              # the `clock` lens, when it is what was asked for
    return [
        AxisMove(axis=ax, label=AXES[ax][1],
                 before=axis_score(baseline, ax), after=axis_score(after, ax),
                 floor=_noise_floor(ax, runs))
        for ax in axes
    ]


def _net(moves: list) -> float:
    from mythgauntlet.ratings.card_impact import _score
    return _score(moves)


def advise(
    resolved: ResolvedDeck,
    cfg: SimConfig,
    store: SemanticsStore,
    candidates: Iterable[Card],
    *,
    axis: str | None = None,
    top: int = 5,
    max_eval: int = 12,
    cut_pool: int = 3,
    min_delta: float = 1.0,
    two_card_combos: int = 0,
    combos_checked: bool = False,
    cut_strategy: str = CUT_REDUNDANT,
    themes: Sequence[str] = (),
    lift: dict[str, float] | None = None,
    lens: CommanderLens | None = None,
    fallback_axes: int = 0,
    protect: frozenset[str] = frozenset(),
    ablate_cuts: bool = False,
    confirm_seeds: int = 0,
    baseline_seeds: int = 0,
) -> AdviceReport:
    """Rank candidate swaps by their measured improvement to the target axis.

    axis=None picks the deck's weakest axis. Each candidate is tested against a small pool
    of cut candidates; the analysis is re-run for every (add, cut) pairing and the add keeps
    whichever cut improves the axis most. Only positive swaps are returned, best first.
    `max_eval` bounds the number of add candidates; each spends up to `cut_pool` re-analyses,
    so the total re-sim count is reported as `analyses`.

    `cut_strategy` picks HOW the cut pool is chosen (see `CUT_STRATEGIES`). The default,
    `redundant`, offers the cards the deck has too MANY of. `popularity` is the original
    least-played rule, kept because the golden-master tests pin it — it is not a good rule
    (see `_weakest_cuts`).

    CHOOSING `cut_pool`. Quality rises MONOTONICALLY with it — there is no quality knee, so
    the choice is purely quality against latency. Swept over 20 corpus decks (max_eval=10,
    runs=60, owned-card candidates):

        cut_pool   decks helped   total gain   analyses   gain/analysis   secs
               1           7/20       106.88        200          0.534      21
               2           7/20       160.42        400          0.401      40
               3           9/20       185.83        600          0.310      57
               5          11/20       227.71       1000          0.228      95
               8          13/20       283.33       1600          0.177     149

    "Decks helped" is the figure that matters to a user: more slots to displace means
    fewer "no suggestion found" answers, 7/20 at cut_pool=1 versus 13/20 at 8. Cost is
    linear (analyses = max_eval x cut_pool) and gain/analysis falls throughout, so a
    latency budget is what should pick this, not a search for an optimum.

    The default of 3 is deliberately conservative for an unknown library caller. The Forge
    app's /advise route overrides it to 6 (with max_eval=16, ~60s warm against a 150s
    timeout) and its interactive card-impact route pins 3 explicitly.

    `themes` are the deck's OWN detected archetypes, as plain strings (see
    `redundancy.targets_for`). Supplying them stops the deck being offered its own plan as
    the cut pool: a spellslinger deck is judged against what spellslinger decks really run,
    not against a population whose median deck plays zero counterspells. Omitting them is
    the population baseline - correct, and merely blunter, for a caller that cannot detect
    archetypes.

    `lift` is a `{card name: EDHREC synergy}` map for THIS commander (see
    `redundancy.rank_redundant`/`_lift_key`), `redundant`-only. It refines the cut ORDER
    within a tied score bucket and matters most on the ~9% of decks that over-supply nothing
    (S12 in `docs/ROADMAP.md`), where every candidate ties at score 0.0 and the pool would
    otherwise fall straight through to least-played. Omit it for the pre-existing ordering;
    like `themes`, this function does not fetch it - a caller builds it from
    `mythgauntlet.data.edhrec` and passes it in.

    `fallback_axes` (auto mode only, axis=None): also accept swaps on the next-weakest
    profile axes, up to this many axes in all. Every re-simulation measures EVERY axis, so it
    costs no extra sims; the candidate budget is shared round-robin across the axes' priors.
    Found 2026-11-09 on the owner's Y'shtola deck: its weakest axis (ceiling) is set by the
    commander + Aura plan and no owned card moves it past the noise floor, so a 6-minute
    search returned nothing while resilience swaps measured +5 against a 1.6 floor. Each
    suggestion names its own axis; the same noise floor and whole-deck net gate apply. 0 (the
    default) is the original single-axis search, byte-identical.
    """
    if axis is not None and axis not in AXES:
        raise ValueError(f"unknown axis '{axis}'; choose one of: {', '.join(AXES)}")
    if cut_strategy not in CUT_STRATEGIES:
        raise ValueError(
            f"unknown cut_strategy '{cut_strategy}'; "
            f"choose one of: {', '.join(CUT_STRATEGIES)}"
        )
    cut_pool = max(1, cut_pool)

    # Resilience is a second (paired) sim pass. The baseline always runs it: it is needed to
    # pick the weakest axis AND to check the final picks don't buy the target with it.
    baseline = analyze_deck(
        resolved, cfg, store, two_card_combos=two_card_combos,
        combos_checked=combos_checked, run_resilience=True,
    )
    # The baseline is ONE seed's games, and every candidate is measured against it, so its luck is
    # a bias shared by all of them: the Mycotyrant's seed-42 consistency read 4.6 points below its
    # average over other seeds (2.7 sd), which is most of the +5..+7 every consistency swap
    # claimed there (2026-11-11). `baseline_seeds` extra seeds give the average the swaps are
    # compared against and the axis ranking is read from. (Paired seeds do NOT cancel it: the
    # paired difference is as noisy as two independent games.)
    base_avg = {ax: axis_score(baseline, ax) for ax in AXES if ax != "resilience" or baseline.resilience is not None}
    if baseline_seeds > 0:
        extra = [analyze_deck(
            resolved, SimConfig(turns=cfg.turns, runs=cfg.runs,
                                seed=cfg.seed + BASELINE_SEED_STEP * (i + 1)), store,
            two_card_combos=two_card_combos, combos_checked=combos_checked, run_resilience=True,
        ) for i in range(baseline_seeds)]
        base_avg = {ax: (base_avg[ax] + sum(axis_score(e, ax) for e in extra))
                    / (1 + len(extra)) for ax in base_avg}
    target = axis or min((ax for ax in PROFILE_AXES if ax != "resilience"
                          or baseline.resilience is not None), key=lambda ax: base_avg[ax])
    # Never report a gain smaller than the axis's own run-to-run spread, whatever the
    # caller asked for. A caller may raise the bar, not lower it below the noise.
    effective_delta = max(min_delta, _noise_floor(target, cfg.runs))
    searched = [target]
    if axis is None and fallback_axes > 1:
        # Resilience is never a FALLBACK: reading it needs the paired wipe pass on every
        # re-simulation, which doubled a Forge search (Borg Queen 287 s -> 682 s; Y'shtola past
        # the 900 s route timeout, 2026-11-09). It is still searched when it IS the weakest.
        weak_first = sorted((ax for ax in PROFILE_AXES if ax != "resilience"),
                            key=lambda ax: base_avg[ax])
        searched += [ax for ax in weak_first if ax != target][:fallback_axes - 1]
    floors = {ax: max(min_delta, _noise_floor(ax, cfg.runs)) for ax in searched}
    base_scores = {ax: base_avg[ax] for ax in searched}
    need_res = "resilience" in searched
    base_score = base_avg[target]

    if lens is None:
        # The baseline analysis's lens carries the sim context (X credit), so this agrees
        # with list_deck_cards / Deck Breakdown; the no-context lens is only a fallback.
        lens = getattr(baseline, "lens", None) or build_lens(resolved.commanders)
    # `protect`: cards never offered as a cut. `ablate_cuts`: of the top 2 x cut_pool, the cards
    # the paired drawn-games ablation (ratings/card_ablation) shows the deck killing measurably
    # sooner with go to the BACK of the pool -- a role count may call such a card spare, the
    # measurement says it is doing work (2026-11-10: Ambulatory Reactor +0.25 turns, offered as
    # "spare ramp"). Demoted, not barred: each swap is still judged on its own measured net, so a
    # load-bearing card can be the right cut for a bigger add, but only when idle cards ran out.
    # Off (the default) is the original pool.
    if ablate_cuts:
        # The shared cut ranking (ratings/cut_ranking): the same ordered list the weak-card
        # verdicts and the mentor's role swaps use. When it offers fewer than cut_pool cards
        # the old pool tops it up, LAST: each swap is still judged on its own measured net, so
        # a card the ranking keeps may be the right cut for a bigger add, but only after every
        # card it calls a cut, and Advise never comes back empty for want of one.
        from mythgauntlet.ratings.cut_ranking import rank_cuts
        ranking = rank_cuts(resolved, cfg, lens=lens, themes=themes)
        by_name = {c.name: c for c, _ in resolved.cards}
        cuts = [by_name[n] for n in ranking.names() if n not in protect][:cut_pool]
        if len(cuts) < cut_pool:
            have = {c.name for c in cuts}
            extra = _cut_candidates(resolved, 3 * cut_pool, cut_strategy, themes, lift, lens,
                                    protect)
            cuts += [c for c in extra if c.name not in have][:cut_pool - len(cuts)]
    else:
        cuts = _cut_candidates(resolved, cut_pool, cut_strategy, themes, lift, lens, protect)
    suggestions: list[SwapSuggestion] = []
    evaluated = 0
    analyses = 0
    if cuts:
        in_deck = {c.name for c, _ in resolved.cards} | {c.name for c in resolved.commanders}
        identity = _commander_identity(resolved)
        eligible = [
            c for c in candidates
            if c.name not in in_deck and _is_legal_candidate(c, identity)
        ]
        # Rank by TARGET-axis relevance AND the commander's mechanical direction before
        # spending the eval budget, so we re-simulate the cards most likely to move the
        # axis that also fit the deck's plan (e.g. Kaalia's cheatable Angels/Demons/Dragons).
        wants = commander_wants(resolved.commanders)
        if len(searched) == 1:
            pool = _prioritize(eligible, target, wants)[:max_eval]
        else:                           # round-robin over each searched axis's prior
            ranked = [_prioritize(eligible, ax, wants) for ax in searched]
            pool, seen_add = [], set()
            for i in range(len(eligible)):
                for lst in ranked:
                    if i < len(lst) and lst[i].name not in seen_add and len(pool) < max_eval:
                        seen_add.add(lst[i].name)
                        pool.append(lst[i])
                if len(pool) >= max_eval:
                    break
        # Evaluate every (add, cut) pairing, then choose a NON-OVERLAPPING package:
        # distinct adds AND distinct cuts. Without this, many adds independently pick the
        # same single weakest card as their best cut, so the list becomes "8 different
        # replacements for one slot" — false choice, since you can only swap that slot
        # once. A greedy highest-gain-first assignment yields a set of swaps you could
        # actually make together.
        reasons: dict[tuple[str, str], str] = {}
        evals: list[tuple[float, float, Card, Card, float, DeckAnalysis, str]] = []
        for add in pool:
            evaluated += 1
            for cut in cuts:
                a = analyze_deck(
                    _swap_variant(resolved, cut, add), cfg, store,
                    two_card_combos=two_card_combos, combos_checked=combos_checked,
                    run_resilience=need_res,
                )
                analyses += 1
                # Require a MEANINGFUL gain, not just a positive one: on a 0-100 axis a
                # +0.1 swap is sim noise, and padding the list with noise is what made the
                # advisor feel useless ("5 suggestions, 4 of them +0.1"). Each floor
                # additionally refuses to go below that axis's own measured seed-to-seed
                # spread — see _AXIS_NOISE_FLOOR. The target axis wins when it qualifies;
                # otherwise the fallback axis it beats by the most floors.
                gains = {ax: axis_score(a, ax) - base_scores[ax] for ax in searched}
                ok = [ax for ax in searched if gains[ax] >= floors[ax]]
                if not ok:
                    continue
                ax = target if target in ok else max(ok, key=lambda x: gains[x] / floors[x])
                # ...AND it must leave the deck better OVERALL. A target gain bought with a
                # bigger loss elsewhere (in units of each axis's spread among real decks) is
                # a worse deck, not an upgrade.
                net = _net(_whole_deck_moves(baseline, a, ax, cfg.runs))
                if net > 0:
                    evals.append((net, gains[ax], add, cut, axis_score(a, ax), a, ax))
        # Greedy non-overlapping selection: best gain first, each add + each cut used once.
        #
        # TIES ARE THE NORM HERE, so the tiebreak is load-bearing. The Ceiling axis is
        # quantised: `speed_component` is `(turns - fast_kill_turn) / turns * 55` over an
        # INTEGER kill turn, so at the default 8 turns every improvement is a whole-turn step
        # worth exactly 55/8 = 6.875. Measured over a real 7-deck pod, 21 of 24 suggestions
        # scored an identical +6.88 and the other 3 an identical +6.67.
        #
        # Breaking those ties by NAME sorted them alphabetically, which is why the advice came
        # back led by Ancient Brass Dragon / Arcane Signet / Arid Mesa / Bloodstained Mire —
        # an artefact of the alphabet presented as a ranking. Prefer the card the axis prior
        # says is most likely to move this axis, then the more-played card, then the name for
        # determinism. The measured delta is still the verdict; this only orders equals.
        #
        # The primary key is the WHOLE-DECK net, not the raw target delta: ranking by target
        # alone let a +8 Ceiling swap that cost -7 Consistency outrank a clean +6, and chose
        # each add's cut as the one hurting the target least — i.e. the best card of some
        # other axis. Target delta is the next key, so equal nets still favour the asked-for
        # axis, then the existing prior/popularity/name tiebreak.
        _prior = {(e[2].name, e[6]): _axis_relevance(tags.analyze(e[2]), e[6])
                  + _commander_affinity(e[2], wants) for e in evals}
        evals.sort(key=lambda e: (-round(e[0], 6), -e[1], -_prior.get((e[2].name, e[6]), 0.0),
                                  e[2].edhrec_rank or 10**9, e[2].name, e[3].name))
        used_add: set[str] = set()
        used_cut: set[str] = set()
        confirm_base: dict = {}
        confirm_tried = 0
        for _net_score, _delta, add, cut, after, a, ax in evals:
            if add.name in used_add or cut.name in used_cut:
                continue
            if a.resilience is None:
                # Resilience was not simulated for the sweep (it doubles each run), so a swap
                # could still be buying the target with it. Check the picks only: one paired
                # run each, at most `top` survivors plus the few it rejects.
                a = analyze_deck(
                    _swap_variant(resolved, cut, add), cfg, store,
                    two_card_combos=two_card_combos, combos_checked=combos_checked,
                    run_resilience=True,
                )
                analyses += 1
                after = axis_score(a, ax)
            moves = _whole_deck_moves(baseline, a, ax, cfg.runs)
            net = _net(moves)
            if net <= 0 or after - base_scores[ax] < floors[ax]:
                continue
            confirmation = None
            if confirm_seeds > 0 and ax != "interaction":     # interaction is closed-form
                if confirm_tried >= 3 * top:
                    break                   # budget spent: report what survived, no more tries
                confirm_tried += 1
                search_delta = after - base_scores[ax]
                kw = dict(two_card_combos=two_card_combos, combos_checked=combos_checked)
                diffs = _confirm_diffs(resolved, cut, add, ax, cfg, store, 0, confirm_seeds,
                                       confirm_base, **kw)
                if not _passes(diffs, floors[ax], CONFIRM_SCREEN_Z):
                    continue                # the search-seed gain did not repeat: luck
                final = max(CONFIRM_FINAL_SEEDS, confirm_seeds)
                diffs += _confirm_diffs(resolved, cut, add, ax, cfg, store, confirm_seeds,
                                        final - confirm_seeds, confirm_base, **kw)
                if not _passes(diffs, floors[ax], CONFIRM_FINAL_Z):
                    continue                # passed the screen by chance
                mean, se = _mean_se(diffs)
                after = base_scores[ax] + mean      # claim the unbiased estimate, not the max
                confirmation = {"seeds": len(diffs), "mean": round(mean, 2),
                                "se": round(se, 2), "search_delta": round(search_delta, 2)}
            if ax == "interaction":
                confirmation = {"closed_form": True, "note": INTERACTION_NOTE}
            used_add.add(add.name)
            used_cut.add(cut.name)
            reason = reasons.setdefault((add.name, ax), _explain(add, ax, wants))
            if ax == "interaction":
                reason = f"{reason} {INTERACTION_NOTE}"
            # the kill-turn phrase reads the SEARCH seed's games, the very numbers that did not
            # repeat -- never state it for a swap whose gain was re-measured
            measured = "" if (confirmation and not confirmation.get("closed_form")) else _measured_phrase(baseline, a)
            if measured:
                reason = f"{reason} Measured: {measured}."
            suggestions.append(SwapSuggestion(
                add=add.name, cut=cut.name, before=base_scores[ax], after=after, reason=reason,
                brief=swap_brief.build_swap_brief(
                    resolved, add, cut,
                    axis=ax, axis_label=AXES[ax][1],
                    before=base_scores[ax], after=after, noise_floor=floors[ax],
                    themes=themes, wants=wants,
                    # search-seed kill turns are the numbers that did not repeat: not cited
                    baseline_report=None if (confirmation and not confirmation.get("closed_form")) else baseline.report,
                    swap_report=None if (confirmation and not confirmation.get("closed_form")) else a.report,
                ),
                axis_deltas={m.axis: m.delta for m in moves},
                net=net, confirmation=confirmation,
                costs={m.axis: m.delta for m in moves
                       if m.axis != ax and m.meaningful and m.delta < 0},
                axis=ax, axis_label=AXES[ax][1],
            ))
            if len(suggestions) >= top:
                break
        # One empty-slot run per DISTINCT cut that made the list (at most `top`), to split
        # each swap into what the add does and what the cut was doing on the target axis.
        empty_runs: dict[str, DeckAnalysis] = {}
        cut_cards = {c.name: c for c in cuts}
        for s in suggestions:
            if s.cut not in empty_runs:
                empty_runs[s.cut] = analyze_deck(
                    _swap_variant(resolved, cut_cards[s.cut], EMPTY_SLOT), cfg, store,
                    two_card_combos=two_card_combos, combos_checked=combos_checked,
                    run_resilience=need_res,
                )
                analyses += 1
            empty = axis_score(empty_runs[s.cut], s.axis or target)
            s.add_value = s.after - empty
            s.cut_value = s.before - empty

    return AdviceReport(
        axis=target, axis_label=AXES[target][1], baseline=base_score,
        cut=cuts[0].name if (cuts and cut_pool == 1) else None,
        suggestions=suggestions[:top], evaluated=evaluated,
        analyses=analyses, cut_pool=cut_pool, min_delta=effective_delta,
        cut_strategy=cut_strategy, searched_axes=list(searched),
    )
