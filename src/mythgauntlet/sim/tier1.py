"""Tier-1 scripted pressure: the Resilience axis (docs/SIMULATION.md).

The vision's flagship differentiator — "does the deck fold to a board wipe?" — which no
static calculator can answer because it is an emergent property of playing the deck.

Method: paired simulation. Run the T0 goldfish sim twice at the SAME seeds, once clean and
once with a board wipe injected at turn W. Because run i draws from the same stream in both
passes, the two are a matched pair and per-run differencing cancels shuffle variance. The
Resilience score is how much of the deck's PRESSURE (goldfish damage, combat and non-combat)
survives the wipe over the wipe turn and the three turns after it.

WHY PRESSURE OVER A WINDOW, not development at the horizon (re-modelled 2026-10-18). The
score used to be wiped/clean (board power + mana available) at the LAST turn. Measured over
the 619 labelled corpus decks that gave p10/p50/p90 = 82/89/94 and 99.5% of decks >= 65
("resilient"), for two compounding reasons:
  * mana sat in the ratio: lands and rocks are untouched by a wipe (mana retained 94-100% on
    every deck) and were ~11 of ~26 output units at the horizon, so roughly half of every
    deck's score was a constant;
  * the horizon outgrew the wipe: `DEFAULT_ANALYZE_TURNS` went 8 -> 12 (2026-07-22) while
    the wipe stayed at turn 5. Measured, the clean board at turn 5 is only ~2.5 power (p50)
    against ~15 at turn 12, and seven quiet goldfish turns rebuild almost anything -- even
    board power ALONE retained 63/80/89.
The question the axis asks is "does the deck fold to a board wipe?", which is about the turns
right after it, so the score is now per-run retained damage dealt in turns W..W+3 (for the
default T5 wipe that is turns 5-8, exactly the geometry of the original 8-turn horizon),
capped at 1 and averaged. Same corpus, with the commander recast below: p10/p50/p90 =
43/56/71 (spread 29 points vs 13); by label B1 58 / B2 56 / B3 56 / B4 58 / B5 50 (resilience
is not a power axis, so a flat B1-B4 is the expected shape; B5's cheap creatures and mana
dorks die). Seed-to-seed noise 2.22 at runs=150 (`advisor._AXIS_NOISE_FLOOR`), so the spread
is ~13x the noise, up from ~12x. Bands (ratings/insight.py) re-cut to resilient >= 60
(36.3% of decks) / vulnerable < 42 (9.2%); the old bands put 99.5% of decks at "resilient".

A run whose clean pass deals no damage in the window has nothing a wipe can take and is
skipped; if EVERY run is skipped (a creatureless combo or durdle deck) the score falls back
to the old development ratio (board + mana at the horizon), so a rocks-and-spells deck still
reads as untouched rather than as a fabricated zero. `basis` on the report says which.

Two sim fixes landed with the re-model (sim/tier0._run_one), one in each direction:
  * creature draw/damage engines now die to the wipe -- they used to survive it, which
    inflated this axis (a Guttersnipe kept pinging after the wrath that killed it);
  * a creature commander now returns to the command zone and can be recast with {2} tax
    (CR 903.8/903.9a). The pressure window exposed its absence: decks whose pressure IS the
    commander (Hellcat, Undying Vigilante; Ashling the Pilgrim) scored 0 -- "folds to wipes"
    -- for a 2-drop any pilot simply recasts.
Still an honest under-count: recursion, indestructible and protection are invisible at rung 1,
and auras/equipment are not modelled falling off. These make a deck look LESS resilient,
never more.

MVP scope (documented, honest): one disruption class (board wipe). Targeted removal and
counter pressure are the next disruption classes (SIMULATION.md). The wipe models
"destroy all creatures" — see sim/tier0._run_one for exactly what it resets.
"""

from __future__ import annotations

from dataclasses import dataclass

from mythgauntlet.model.card import Card
from mythgauntlet.sim.clock import apply_nut_kills
from mythgauntlet.sim.tier0 import RunStats, SimConfig, simulate


def default_wipe_turn(turns: int) -> int:
    """A representative board-wipe turn (2-5), clamped to the horizon so it always fires.

    Shared by the CLI and API so both surfaces test the same wipe; without the horizon
    clamp a turns=1 sim would 'wipe' at turn 2 (never reached) and report a false 100.
    """
    return min(turns, min(5, max(2, turns - 1)))


@dataclass
class ResilienceReport:
    runs: int
    wipe_turn: int
    clean_kill_rate: float
    wiped_kill_rate: float
    clean_avg_kill_turn: float | None
    wiped_avg_kill_turn: float | None
    # per-run retained pressure = wiped / clean damage dealt in turns W..W+3, capped 1
    resilience_score: float  # 0-100: 100 = shrugs the wipe off, 0 = no pressure after it
    kill_delay_turns: float | None  # extra turns to kill after a wipe (None if no clean kills)
    window_end_turn: int = 0  # last turn of the pressure window (W + 3, clamped to horizon)
    # "pressure" normally; "development" when the deck never deals damage in the window and
    # the score fell back to board+mana retained at the horizon (see module docstring)
    basis: str = "pressure"


# Turns after the wipe turn that the pressure window covers (window = W..W+3).
PRESSURE_WINDOW_AFTER = 3


def _final_output(run: RunStats) -> float:
    mana = run.mana_available_by_turn[-1] if run.mana_available_by_turn else 0
    return float(run.final_board_power + mana)


def _window_damage(run: RunStats, first: int, last: int) -> float:
    """Goldfish damage dealt in turns first..last inclusive (damage_by_turn is cumulative)."""
    dmg = run.damage_by_turn
    if len(dmg) < last:
        return 0.0
    before = dmg[first - 2] if first >= 2 else 0
    return float(dmg[last - 1] - before)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def compute_resilience(
    cards: list[tuple[Card, int]], commander: Card | None, cfg: SimConfig, wipe_turn: int,
    all_cards: list[tuple[Card, int]] | None = None,
) -> ResilienceReport:
    """`all_cards` is `cards` plus the LEAD commander (mirrors `ratings.analysis.analyze_deck`'s
    own `all_cards` — the commander is simulated specially and isn't in `cards`), passed
    through to `apply_nut_kills` so a non-combat kill counts here too (PLAN_CLOCK Phase 2:
    this axis called `sim.tier0.simulate` directly and never got the Phase 1a/1b fix that
    the main `runs`/`pod_runs` batches did, so a storm/burn/overrun deck's resilience was
    still measured against a combat-only kill_turn that doesn't reflect how it actually
    wins). Defaults to `cards` when the caller has no lead commander to add (a strict
    subset of the real fix, still correct, just missing the commander's own contribution).
    """
    clean = simulate(cards, commander, cfg)
    wiped = simulate(cards, commander, cfg, board_wipe_turn=wipe_turn)
    nut_kill_cards = all_cards if all_cards is not None else cards
    # A board wipe clears creatures, not mana or hand -- so a storm kill_turn (mana-curve
    # driven) is UNCHANGED by the wipe, correctly: a counterspell-free wipe doesn't stop a
    # combo. An overrun kill_turn CAN move later post-wipe, because it reads the run's own
    # rebuilt board_power_by_turn/board_creatures_by_turn, which the wipe actually reset.
    apply_nut_kills(clean, nut_kill_cards, cfg.turns)
    apply_nut_kills(wiped, nut_kill_cards, cfg.turns)

    window_end = min(cfg.turns, wipe_turn + PRESSURE_WINDOW_AFTER)
    retained = []
    for c, w in zip(clean, wiped, strict=True):
        base = _window_damage(c, wipe_turn, window_end)
        if base <= 0:  # no pressure in the window even unopposed -- nothing to lose
            continue
        retained.append(min(1.0, _window_damage(w, wipe_turn, window_end) / base))
    basis = "pressure"
    if not retained:
        basis = "development"
        for c, w in zip(clean, wiped, strict=True):
            base = _final_output(c)
            if base <= 0:  # deck presents nothing even unopposed — resilience is undefined
                continue
            retained.append(min(1.0, _final_output(w) / base))
    score = 100.0 * _mean(retained) if retained else 0.0

    clean_kills = [r.kill_turn for r in clean if r.kill_turn is not None]
    wiped_kills = [r.kill_turn for r in wiped if r.kill_turn is not None]
    clean_avg = _mean([float(t) for t in clean_kills]) if clean_kills else None
    wiped_avg = _mean([float(t) for t in wiped_kills]) if wiped_kills else None
    delay = (wiped_avg - clean_avg) if (clean_avg is not None and wiped_avg is not None) else None

    n = len(clean)
    return ResilienceReport(
        runs=n,
        wipe_turn=wipe_turn,
        clean_kill_rate=len(clean_kills) / n if n else 0.0,
        wiped_kill_rate=len(wiped_kills) / n if n else 0.0,
        clean_avg_kill_turn=clean_avg,
        wiped_avg_kill_turn=wiped_avg,
        resilience_score=score,
        kill_delay_turns=delay,
        window_end_turn=window_end,
        basis=basis,
    )
