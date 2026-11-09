"""Exposure to hate (B36, docs/SPEC_deck_scouting_report.md): what a deck leans on that a
common answer punishes, and how hard.

Deterministic, no new simulation except one goldfish batch with the commander answered twice
(`tier0.simulate(commander_removals=2)`). Each row measures RELIANCE; a sentence is emitted only
past that row's threshold, and every threshold is a percentile over the labelled corpus decks
(or, for wipes and speed, over the deck's bracket peers -- `ratings.reference`), never a constant
picked by feel. Rows:

  graveyard   cards whose own text uses the graveyard as a resource (return/cast from it, or
              scale with it) -- weak to Rest in Peace-style hate
  commander   kill turn lost when the commander is answered twice (the goldfish option)
  wipes       wipe resilience in the bottom quarter of the bracket's peers
  artifacts   artifact share of the ramp -- weak to Vandalblast-style sweepers
  enchantments enchantment share of the nonland cards -- weak to Back to Nature-style sweepers
  flyers      no / few own creatures with flying or reach to block evasive attackers
  single_combo one card shared by every game-ending combo -- one answer stops them all
  mana_base   nonbasic lands in a multicolour deck -- weak to Blood Moon effects
  speed       kill turn slower than three quarters of the bracket's peers -- weak to fast tables

Under-count rather than fabricate: a card no pattern reads is not counted as a dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mythgauntlet.model.card import Card

# --- card-level reads ------------------------------------------------------------------------

_GY_RES = (
    # return / put a card FROM YOUR graveyard (reanimation, recursion)
    re.compile(r"\bfrom your graveyard (?:to|onto) (?:the battlefield|your hand)\b", re.IGNORECASE),
    re.compile(r"\breturn [^.]*?\bfrom your graveyard\b", re.IGNORECASE),
    # cast / play from your graveyard
    re.compile(r"\b(?:cast|play) [^.]*?\bfrom your graveyard\b", re.IGNORECASE),
    # graveyard-keyword mechanics, read as a keyword line
    re.compile(r"^(?:flashback|escape|unearth|disturb|embalm|eternalize|jump-start|retrace|"
               r"scavenge|encore|dredge|delve)\b", re.IGNORECASE | re.MULTILINE),
    # scales with the graveyard's contents -- a COUNT of it, not a mention (Guardian Project's
    # "a creature card in your graveyard" is a name check, not reliance)
    re.compile(r"\b(?:for each|the number of)\b[^.]*?\bcards? in your graveyard\b", re.IGNORECASE),
    re.compile(r"\b(?:\w+) or more (?:\w+ )?cards? in your graveyard\b", re.IGNORECASE),
    # grants graveyard cards an ability (Underworld Breach: "...card in your graveyard has escape")
    re.compile(r"\bcards? in your graveyard (?:has|have|gains?)\b", re.IGNORECASE),
    re.compile(r"^(?:threshold|delirium)\b", re.IGNORECASE | re.MULTILINE),
)
# graveyard HATE and self-exile-as-cost are not reliance on the graveyard
_GY_HATE_RE = re.compile(r"\bexile (?:target player's|each opponent's|all cards from all|all "
                         r"graveyards|each player's) graveyard", re.IGNORECASE)

# A keyword line as Oracle prints it: "Flying", "Reach, deathtouch", "First strike, lifelink"
# -- the first keyword capitalised, the rest lowercase, no full stop.
_KEYWORD_LINE_RE = re.compile(r"^[A-Z][a-z]+(?: [a-z]+)*(?:, [a-z]+(?: [a-z]+)*)*$", re.MULTILINE)


def _text(card: Card) -> str:
    return re.sub(r"\([^)]*\)", "", card.oracle_text or "")   # reminder text says nothing


def uses_graveyard(card: Card) -> bool:
    text = _text(card)
    if _GY_HATE_RE.search(text) and not any(rx.search(text) for rx in _GY_RES[:3]):
        return False
    return any(rx.search(text) for rx in _GY_RES)


def blocks_flyers(card: Card) -> bool:
    """A creature with flying or reach as a keyword of its own (a keyword line)."""
    if not card.is_creature:
        return False
    for line in _KEYWORD_LINE_RE.findall(_text(card)):
        words = {w.strip().lower() for w in line.split(",")}
        if words & {"flying", "reach"}:
            return True
    return False


def is_basic(card: Card) -> bool:
    return "Basic" in (card.type_line or "")


# --- deck metrics ----------------------------------------------------------------------------


@dataclass
class DeckReliance:
    graveyard: list[str] = field(default_factory=list)
    ramp: int = 0
    artifact_ramp: list[str] = field(default_factory=list)
    nonland: int = 0
    enchantments: list[str] = field(default_factory=list)
    flyer_blockers: list[str] = field(default_factory=list)
    nonbasic_lands: int = 0
    colours: int = 0


def deck_reliance(cards: list[tuple[Card, int]], commanders: list[Card]) -> DeckReliance:
    from mythgauntlet.semantics import tags

    out = DeckReliance()
    colours = set()
    for c in commanders:
        colours |= set(c.color_identity or ())
    out.colours = len(colours)
    for card, n in list(cards) + [(c, 1) for c in commanders]:
        if card.is_land:
            if not is_basic(card):
                out.nonbasic_lands += n
            continue
        out.nonland += n
        if uses_graveyard(card):
            out.graveyard.append(card.name)
        fx = tags.analyze(card)
        if fx.ramp_sources or fx.fetches_land:
            out.ramp += n
            if card.has_type("Artifact"):
                out.artifact_ramp.append(card.name)
        if card.has_type("Enchantment"):
            out.enchantments.extend([card.name] * n)
        if blocks_flyers(card):
            out.flyer_blockers.append(card.name)
    return out


# --- thresholds (percentiles over the labelled corpus) ----------------------------------------
# Measured 2026-11-08 over the 2,112 audited labelled corpus decks (commander removal: a random
# 300 with a commander, 120 runs each). A row speaks only past its threshold: roughly the top
# fifth of the corpus for a reliance, the bottom tenth for flyer blockers. Wipes and speed are
# ranked against the deck's bracket peers instead (`ratings.reference`, bottom quarter).
GRAVEYARD_MIN = 6            # p80 of graveyard-resource cards
ARTIFACT_RAMP_MIN = 8        # p80 of artifact ramp pieces
ENCHANTMENT_SHARE_MIN = 0.15  # p80 of the enchantment share of nonland cards
FLYER_BLOCKERS_MAX = 0       # none at all (rarer than p10, which is 1): no flying or reach creature
NONBASIC_MIN = 27            # p80 of nonbasic lands among multicolour decks
COMMANDER_LOSS_MIN = 1.9     # p80 of kill turns lost with the commander answered twice
PEER_BOTTOM = 25.0           # wipes / speed: worse than 75% of the bracket's peers
COMBO_FIRST_MIN = 0.25       # single combo: the combo wins first in a quarter of games


@dataclass
class Exposure:
    key: str
    text: str
    evidence: list[str] = field(default_factory=list)


def _names(names: list[str], n: int = 4) -> list[str]:
    seen = list(dict.fromkeys(names))
    return seen[:n] + ([f"+{len(seen) - n} more"] if len(seen) > n else [])


def commander_loss(clean_runs, removed_runs, horizon: int) -> float:
    """Mean kill turn lost (never killing counts as horizon + 1)."""
    def mean(runs):
        t = [r.kill_turn if r.kill_turn is not None else horizon + 1 for r in runs]
        return sum(t) / len(t) if t else 0.0
    return mean(removed_runs) - mean(clean_runs)


def compute(resolved, analysis, removed_runs, clean_runs, horizon: int) -> list[Exposure]:
    """Every row past its threshold, as a sentence with its evidence. `removed_runs` is the
    goldfish with the commander answered twice (None when the deck has no commander)."""
    from mythgauntlet.ratings import reference

    out: list[Exposure] = []
    rel = deck_reliance(list(resolved.cards), list(resolved.commanders))
    peer = getattr(getattr(analysis, "bracket", None), "bracket", None)

    if len(rel.graveyard) >= GRAVEYARD_MIN:
        out.append(Exposure("graveyard", f"leans on the graveyard ({len(rel.graveyard)} cards): "
                            "weak to Rest in Peace-style hate", _names(rel.graveyard)))

    if removed_runs is not None and resolved.commanders:
        loss = commander_loss(clean_runs, removed_runs, horizon)
        if loss >= COMMANDER_LOSS_MIN:
            name = resolved.commanders[0].name
            out.append(Exposure("commander", f"loses {loss:.1f} turns of speed if {name} is "
                                "answered twice: keep protection for it, or a plan without it",
                                [name]))

    res = getattr(analysis, "resilience", None)
    if res is not None and peer is not None:
        rk = reference.percentile_rank(peer, "resilience", res.resilience_score)
        if rk is not None and rk["better_than"] < PEER_BOTTOM:
            out.append(Exposure("wipes", f"a board wipe sets it back further than "
                                f"{100 - rk['better_than']:.0f}% of Bracket {peer} decks "
                                f"(resilience {res.resilience_score:.0f}/100)"))

    if len(rel.artifact_ramp) >= ARTIFACT_RAMP_MIN:
        out.append(Exposure("artifacts", f"{len(rel.artifact_ramp)} of its {rel.ramp} ramp pieces "
                            "are artifacts: weak to Vandalblast-style sweepers",
                            _names(rel.artifact_ramp)))
    share = len(rel.enchantments) / rel.nonland if rel.nonland else 0.0
    if share >= ENCHANTMENT_SHARE_MIN:
        out.append(Exposure("enchantments", f"{len(rel.enchantments)} of its {rel.nonland} "
                            "nonland cards are enchantments: weak to Back to Nature-style "
                            "sweepers", _names(rel.enchantments)))

    if len(rel.flyer_blockers) <= FLYER_BLOCKERS_MAX:
        out.append(Exposure("flyers", "no creature with flying or reach: evasive attackers "
                            "go unblocked"))

    profile = getattr(analysis, "combo_profile", None)
    clock = getattr(analysis, "combo_clock", None)
    terminal = [g for g in getattr(profile, "grades", ()) if getattr(g, "terminal", False)]
    if terminal:
        shared = set(terminal[0].combo.cards)
        for g in terminal[1:]:
            shared &= set(g.combo.cards)
        first = (clock.combo_first_games / clock.games) if clock is not None and clock.games else 0.0
        if shared and (len(terminal) >= 2 or first >= COMBO_FIRST_MIN):
            key = min(shared)
            what = (f"all {len(terminal)} of its game-ending combos use {key}" if len(terminal) >= 2
                    else f"its combo ({' + '.join(terminal[0].combo.cards)}) wins first in "
                         f"{first:.0%} of games")
            out.append(Exposure("single_combo", f"{what}: one answer to {key} stops it",
                                [key]))

    if rel.colours >= 2 and rel.nonbasic_lands >= NONBASIC_MIN:
        out.append(Exposure("mana_base", f"{rel.nonbasic_lands} nonbasic lands in a "
                            f"{rel.colours}-colour deck: weak to Blood Moon effects"))

    kill = getattr(getattr(analysis, "report", None), "avg_kill_turn", None)
    # A combo that wins first ends the game too: with the combo clock, the deck's kill turn is
    # the combined damage-or-combo median (an Oloro Thassa's Oracle deck read "slower than 88%
    # of Bracket 5 decks" off its damage clock alone). Peers are damage-only, so this can only
    # make a combo deck read faster, never slower.
    if clock is not None and clock.median is not None and clock.combo_first_games:
        kill = clock.median if kill is None else min(kill, clock.median)
    if peer is not None and kill is not None:
        rk = reference.percentile_rank(peer, "avg_kill_turn", kill)
        if rk is not None and rk["better_than"] < PEER_BOTTOM:
            out.append(Exposure("speed", f"slower than {100 - rk['better_than']:.0f}% of Bracket "
                                f"{peer} decks (kills around T{kill:.0f} unopposed): weak to "
                                "fast tables"))
    return out
