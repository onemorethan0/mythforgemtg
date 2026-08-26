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

Honest limits still open: multi-card packages, general (non-owned) candidate pools, and
cross-axis trade-offs.
"""

from __future__ import annotations

import dataclasses
import math
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from mythgauntlet.model.card import Card
from mythgauntlet.model.deck import ResolvedDeck
from mythgauntlet.ratings import redundancy, swap_brief
from mythgauntlet.ratings.analysis import DeckAnalysis, analyze_deck
from mythgauntlet.semantics import tags
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


def _speed_score(a: DeckAnalysis) -> float:
    return a.report.goldfish_kill_rate * 100.0


def _resilience_score(a: DeckAnalysis) -> float:
    return a.resilience.resilience_score if a.resilience is not None else 0.0


# axis name -> (extractor, label). Every score is ~0-100, higher = better, so they compare.
AXES: dict[str, tuple[Callable[[DeckAnalysis], float], str]] = {
    "consistency": (lambda a: a.report.consistency_score, "Consistency"),
    "speed":       (_speed_score, "Speed"),
    "resilience":  (_resilience_score, "Resilience"),
    "interaction": (lambda a: a.interaction.score, "Interaction"),
    "ceiling":     (lambda a: a.ceiling.score, "Ceiling"),
}


def axis_score(analysis: DeckAnalysis, axis: str) -> float:
    return AXES[axis][0](analysis)


def weakest_axis(analysis: DeckAnalysis) -> str:
    """The lowest-scoring measurable axis (skips resilience if it wasn't computed)."""
    candidates = [
        ax for ax in AXES if ax != "resilience" or analysis.resilience is not None
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


def _cut_candidates(
    resolved: ResolvedDeck,
    k: int,
    strategy: str,
    themes: Sequence[str] = (),
    lift: dict[str, float] | None = None,
) -> list[Card]:
    """The `k` cards to offer as cuts, per `strategy`.

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
        return _weakest_cuts(resolved, k)
    return redundancy.rank_redundant(
        resolved, k, targets=redundancy.targets_for(themes), lift=lift
    )


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
    "consistency": 0.92,
    # NOT 0.0. The original sweep called `analyze_deck` WITHOUT `run_resilience`, so
    # resilience was never simulated and its spread read as a clean zero. It is only ever
    # simulated when it IS the target axis — exactly when this floor is consulted — and its
    # real spread there is ~1.24 at runs=150 (~1.91 at runs=60). A floor of zero meant every
    # positive resilience delta passed, so resilience advice was unfiltered noise.
    "resilience": 1.06,
    "interaction": 0.0,
}


def _noise_floor(axis: str, runs: int) -> float:
    """The axis's seed-to-seed spread at THIS run count.

    Regenerate the constants with `python scripts/axis_noise.py`; `--check` diffs them.
    """
    base = _AXIS_NOISE_FLOOR.get(axis, 0.0)
    if not base or runs <= 0:
        return base
    return base * math.sqrt(NOISE_REFERENCE_RUNS / runs)


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
    """
    if axis is not None and axis not in AXES:
        raise ValueError(f"unknown axis '{axis}'; choose one of: {', '.join(AXES)}")
    if cut_strategy not in CUT_STRATEGIES:
        raise ValueError(
            f"unknown cut_strategy '{cut_strategy}'; "
            f"choose one of: {', '.join(CUT_STRATEGIES)}"
        )
    cut_pool = max(1, cut_pool)

    # Resilience is a second (paired) sim pass — only run it when it's the target.
    baseline = analyze_deck(
        resolved, cfg, store, two_card_combos=two_card_combos,
        combos_checked=combos_checked, run_resilience=axis in (None, "resilience"),
    )
    target = axis or weakest_axis(baseline)
    # Never report a gain smaller than the axis's own run-to-run spread, whatever the
    # caller asked for. A caller may raise the bar, not lower it below the noise.
    effective_delta = max(min_delta, _noise_floor(target, cfg.runs))
    need_res = target == "resilience"
    base_score = axis_score(baseline, target)

    cuts = _cut_candidates(resolved, cut_pool, cut_strategy, themes, lift)
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
        pool = _prioritize(eligible, target, wants)[:max_eval]
        # Evaluate every (add, cut) pairing, then choose a NON-OVERLAPPING package:
        # distinct adds AND distinct cuts. Without this, many adds independently pick the
        # same single weakest card as their best cut, so the list becomes "8 different
        # replacements for one slot" — false choice, since you can only swap that slot
        # once. A greedy highest-gain-first assignment yields a set of swaps you could
        # actually make together.
        reasons: dict[str, str] = {}
        evals: list[tuple[float, Card, Card, float, DeckAnalysis]] = []
        for add in pool:
            evaluated += 1
            reasons[add.name] = _explain(add, target, wants)
            for cut in cuts:
                a = analyze_deck(
                    _swap_variant(resolved, cut, add), cfg, store,
                    two_card_combos=two_card_combos, combos_checked=combos_checked,
                    run_resilience=need_res,
                )
                analyses += 1
                after = axis_score(a, target)
                # Require a MEANINGFUL gain, not just a positive one: on a 0-100 axis a
                # +0.1 swap is sim noise, and padding the list with noise is what made the
                # advisor feel useless ("5 suggestions, 4 of them +0.1"). `effective_delta`
                # additionally refuses to go below the target axis's own measured
                # seed-to-seed spread — see _AXIS_NOISE_FLOOR.
                if after - base_score >= effective_delta:
                    evals.append((after - base_score, add, cut, after, a))
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
        _prior = {c.name: _axis_relevance(tags.analyze(c), target) + _commander_affinity(c, wants)
                  for c in {e[1].name: e[1] for e in evals}.values()}
        evals.sort(key=lambda e: (-e[0], -_prior.get(e[1].name, 0.0),
                                  e[1].edhrec_rank or 10**9, e[1].name, e[2].name))
        used_add: set[str] = set()
        used_cut: set[str] = set()
        for _delta, add, cut, after, a in evals:
            if add.name in used_add or cut.name in used_cut:
                continue
            used_add.add(add.name)
            used_cut.add(cut.name)
            reason = reasons[add.name]
            measured = _measured_phrase(baseline, a)
            if measured:
                reason = f"{reason} Measured: {measured}."
            suggestions.append(SwapSuggestion(
                add=add.name, cut=cut.name, before=base_score, after=after, reason=reason,
                brief=swap_brief.build_swap_brief(
                    resolved, add, cut,
                    axis=target, axis_label=AXES[target][1],
                    before=base_score, after=after, noise_floor=effective_delta,
                    themes=themes, wants=wants,
                    baseline_report=baseline.report, swap_report=a.report,
                ),
            ))
            if len(suggestions) >= top:
                break

    return AdviceReport(
        axis=target, axis_label=AXES[target][1], baseline=base_score,
        cut=cuts[0].name if (cuts and cut_pool == 1) else None,
        suggestions=suggestions[:top], evaluated=evaluated,
        analyses=analyses, cut_pool=cut_pool, min_delta=effective_delta,
        cut_strategy=cut_strategy,
    )
