"""Power Profile axes computed from card semantics + T0 stats: Interaction, Ceiling, and the
multiplayer Pod clock (docs/VISION.md).

- Interaction: can the deck stop opponents? Castability-weighted answer density x breadth of
  coverage, read from card semantics (removal / counters / wipes). A control shell scores
  high; a durdle pile of unconnected value scores low. Each answer is weighted by how reliably
  the deck can actually deploy it as interaction (2026-07-21): cheaper answers count more (you
  can hold them up and cast more per turn), instant-speed answers count more than sorcery-speed
  (reactive), and an answer whose colored pips the mana base barely supports is down-weighted.
  Raw piece counts stay in the report; the score uses the weighted "effective" answer count.
  (Provisional weights, like the consistency composite.)
- Ceiling: what does the nut draw look like? The top-percentile of the goldfish
  distribution (how fast the BEST games go) plus game-ending combo potential. A glass
  cannon has a high ceiling; a grindy fair deck a low one.
- Pod (multiplayer closing power): can the deck actually WIN a 4-player game, or only a duel?
  1v1 sims measure a single-opponent clock; a pod has ~3x the life to get through. Read from a
  longer goldfish: does the deck's cumulative unopposed damage reach TABLE-lethal (opponents x
  40), and does it have a game-ending combo that closes the whole table at once. Honest limit:
  it's an unopposed CAPACITY proxy (necessary, not sufficient) — a deck that can't generate
  table-lethal pressure with no blockers certainly can't through three defenders.

All read data the analyzer already produces (rung-1 effect vectors + T0 RunStats + Commander
Spellbook combos); Pod adds one longer goldfish pass, the rest need no new simulation.
"""

from __future__ import annotations

from dataclasses import dataclass

from mythgauntlet.model.card import Card
from mythgauntlet.semantics import tags
from mythgauntlet.sim.tier0 import RunStats, SimConfig

# --- Interaction ------------------------------------------------------------------------

_HEALTHY_ANSWER_COUNT = 10.0  # ~10 pieces of interaction reads as solidly interactive


@dataclass
class InteractionReport:
    score: float  # 0-100 (provisional weights)
    answers: int  # total interaction pieces (copies)
    effective_answers: float  # castability-weighted answer count (drives the score)
    spot_removal: int
    counterspells: int
    board_wipes: int
    breadth: int  # how many of {spot, counter, wipe} are present (0-3)


def _color_sources(entries: list[tuple[Card, int]]) -> dict[str, int]:
    """Colored mana the deck can produce, by color (WUBRG), counting every mana producer's
    `produced_mana` (lands, rocks, dorks, rainbow lands) x its copy count. A proxy for color
    ACCESS -- rocks/dorks can be removed, but what colors a deck reaches is what castability
    depends on."""
    sources: dict[str, int] = {}
    for card, count in entries:
        for color in card.produced_mana:
            if color in "WUBRG":
                sources[color] = sources.get(color, 0) + count
    return sources


def _color_support(card: Card, sources: dict[str, int]) -> float:
    """How well the mana base supports an answer's colored pips: ~2 sources per pip of a color
    reads as reliable; scarcer colors down-weight the answer (floored at 0.5 -- a legal deck can
    usually splash off a rainbow land). Hybrid pips (>1 option) are flexible, so ignored."""
    demand: dict[str, int] = {}
    for pip in card.cost.pips:
        if len(pip) == 1:  # a strict single-color pip
            color = next(iter(pip))
            if color in "WUBRG":
                demand[color] = demand.get(color, 0) + 1
    if not demand:
        return 1.0  # colorless / fully hybrid answer: no color strain
    return min(
        max(0.5, min(1.0, sources.get(color, 0) / (2.0 * need)))
        for color, need in demand.items()
    )


def _castability_weight(card: Card, sources: dict[str, int]) -> float:
    """How reliably this answer can be deployed as interaction: cheaper is better (hold it up,
    cast more per turn), instant-speed beats sorcery-speed (reactive), color-strained pips
    down-weight. Provisional weights; ~[0.4, 1.3]."""
    cost = max(0.4, min(1.1, 1.2 - 0.1 * card.mana_value))  # mv1->1.1 .. mv8+->0.4
    speed = 1.15 if card.has_type("Instant") else 1.0
    return cost * speed * _color_support(card, sources)


def compute_interaction(
    cards: list[tuple[Card, int]], commander: Card | None = None
) -> InteractionReport:
    entries = list(cards) + ([(commander, 1)] if commander else [])
    sources = _color_sources(entries)
    spot = counters = wipes = 0
    effective = 0.0
    for card, count in entries:
        if card.is_land:
            continue
        fx = tags.analyze(card)
        is_answer = fx.board_wipe or fx.removal > 0 or fx.counterspell
        if fx.board_wipe:
            wipes += count
        elif fx.removal > 0:
            spot += count
        if fx.counterspell:
            counters += count
        if is_answer:
            effective += _castability_weight(card, sources) * count
    answers = spot + counters + wipes
    breadth = (1 if spot else 0) + (1 if counters else 0) + (1 if wipes else 0)
    density_score = min(70.0, (effective / _HEALTHY_ANSWER_COUNT) * 70.0)
    breadth_score = (breadth / 3.0) * 30.0
    return InteractionReport(
        score=min(100.0, density_score + breadth_score),
        answers=answers,
        effective_answers=round(effective, 1),
        spot_removal=spot,
        counterspells=counters,
        board_wipes=wipes,
        breadth=breadth,
    )


# --- Ceiling ----------------------------------------------------------------------------


@dataclass
class CeilingReport:
    score: float  # 0-100 (provisional weights)
    fast_kill_turn: float | None  # ~10th-percentile (fastest) goldfish kill turn
    nut_kill_rate: float  # fraction of games that kill by the "nut" turn
    nut_turn: int
    has_game_ending_combo: bool
    go_off_turn: int | None = None  # earliest storm/spellslinger go-off turn (sim/storm.py)
    overrun_alpha: bool = False  # a wide board + one-shot pump kills in one swing (sim/overrun.py)


def compute_ceiling(
    runs: list[RunStats], cfg: SimConfig, has_game_ending_combo: bool = False,
    go_off_turn: int | None = None, overrun_alpha: bool = False,
) -> CeilingReport:
    n = len(runs)
    kills = sorted(r.kill_turn for r in runs if r.kill_turn is not None)
    # The deck's *best* games: the MEAN of the fastest decile, not the single order statistic
    # that used to sit at that rank.
    #
    # Kill turns are whole numbers, so reading one of them made this metric — and therefore
    # the whole Ceiling axis — move only in WHOLE-TURN steps. `speed_component` scales it by
    # 55/turns, so at the default 8 turns every possible change was exactly 6.875, and a swap
    # that genuinely improved the deck's best draws by less than a full turn measured as zero.
    # Over a real 7-deck pod that quantisation collapsed 24 upgrade suggestions onto TWO
    # distinct values (21 at +6.88, 3 at +6.67), leaving the advisor's ranking to a tiebreak.
    #
    # A mean over the decile is continuous: moving any one of the best games earlier moves it.
    # Same idiom as `lift_stats._quartile_spread` ("mean of the top quarter"), which this repo
    # already prefers over a single extreme for the same reason.
    if kills:
        decile = max(1, round(0.1 * len(kills)))
        fast_kill = sum(kills[:decile]) / decile
    else:
        fast_kill = None
    nut_turn = max(4, int(cfg.turns * 0.6))
    nut_kill_rate = (sum(1 for k in kills if k <= nut_turn) / n) if n else 0.0

    speed_component = (
        0.0 if fast_kill is None
        else max(0.0, min(55.0, (cfg.turns - fast_kill) / cfg.turns * 55.0))
    )
    nut_component = nut_kill_rate * 30.0
    combo_component = 15.0 if has_game_ending_combo else 0.0
    # a storm/spellslinger go-off is a nut-draw kind of kill the combat clock can't see; the
    # earlier it lands the higher the ceiling (docs/SIMULATION.md).
    go_off_component = (
        0.0 if go_off_turn is None
        else max(0.0, min(50.0, (cfg.turns + 1 - go_off_turn) / cfg.turns * 55.0))
    )
    # a wide board + a one-shot overrun is a nut-draw kill the combat clock can't see (overrun.py).
    # A fair wincon (unlike a storm combo) -> it lifts the Ceiling but does NOT gate the bracket.
    overrun_component = 25.0 if overrun_alpha else 0.0
    return CeilingReport(
        score=min(100.0, speed_component + nut_component + combo_component + go_off_component
                  + overrun_component),
        fast_kill_turn=fast_kill,
        nut_kill_rate=nut_kill_rate,
        nut_turn=nut_turn,
        has_game_ending_combo=has_game_ending_combo,
        go_off_turn=go_off_turn,
        overrun_alpha=overrun_alpha,
    )


# --- Pod (multiplayer closing power) ----------------------------------------------------

_DEFAULT_POD_OPPONENTS = 3  # a 4-player Commander pod = you + 3 opponents


@dataclass
class PodReport:
    score: float  # 0-100: capacity to actually close a 4-player game (unopposed proxy)
    opponents: int
    pod_close_turn: float | None  # median turn cumulative goldfish damage reaches table-lethal
    pod_close_rate: float  # fraction of goldfish runs reaching table-lethal by the horizon
    duel_close_rate: float  # fraction reaching single-opponent lethal (the duel-vs-pod gap)
    via_finisher: bool  # a game-ending combo can close the whole table at once (not just combat)


def _median(xs: list[int]) -> float:
    s = sorted(xs)
    m = len(s) // 2
    return float(s[m]) if len(s) % 2 else (s[m - 1] + s[m]) / 2.0


def _threshold_turn(cumulative: list[int], threshold: int) -> int | None:
    """First turn (1-indexed) at which the cumulative-damage curve reaches `threshold`."""
    for i, dmg in enumerate(cumulative):
        if dmg >= threshold:
            return i + 1
    return None


def compute_pod(
    runs: list[RunStats], cfg: SimConfig, *,
    opponents: int = _DEFAULT_POD_OPPONENTS, has_finisher: bool = False,
) -> PodReport:
    """Can the deck close a 4-player game? Reads a (longer) goldfish for whether cumulative
    UNOPPOSED damage reaches table-lethal (`opponents` x goldfish_life), plus whether a
    game-ending combo can close the table at once. It is a capacity proxy — unopposed, so
    necessary-not-sufficient — and the duel-vs-pod close-rate gap shows how much harder the deck
    finds a pod than a duel. `runs` should come from a pod-length horizon (analysis._POD_HORIZON).
    """
    n = len(runs)
    pod_life = opponents * cfg.goldfish_life
    close_turns = [
        t for r in runs
        if (t := _threshold_turn(r.damage_by_turn, pod_life)) is not None
    ]
    pod_close_rate = len(close_turns) / n if n else 0.0
    duel_close_rate = (sum(1 for r in runs if r.kill_turn is not None) / n) if n else 0.0
    pod_close_turn = _median(close_turns) if close_turns else None

    close_component = pod_close_rate * 55.0  # how often it can generate table-lethal pressure
    early_component = (  # ... and how early it gets there (relative to the pod horizon)
        0.0 if pod_close_turn is None
        else max(0.0, min(20.0, (cfg.turns - pod_close_turn) / cfg.turns * 20.0))
    )
    finisher_component = 25.0 if has_finisher else 0.0  # a combo closes the table combat can't
    return PodReport(
        score=min(100.0, close_component + early_component + finisher_component),
        opponents=opponents,
        pod_close_turn=pod_close_turn,
        pod_close_rate=pod_close_rate,
        duel_close_rate=duel_close_rate,
        via_finisher=has_finisher,
    )
