"""Combine the T0 combat clock with non-combat kill detection into one honest kill_turn per
run (docs/PLAN_CLOCK.md Phase 1a).

`RunStats.kill_turn` (tier0.py) is set from cumulative COMBAT damage alone, so every speed
metric derived from it — avg_kill_turn, the Ceiling axis's fast_kill_turn/nut_kill_rate — is
blind to a storm deck going off turn 4 or a go-wide deck alpha-striking turn 6; both still
report the combat-only ~turn-8.5 nut draw. sim/storm.py and sim/overrun.py already detect
both kill shapes; this applies them PER RUN, using that run's own mana/board trajectory
(RunStats.mana_available_by_turn / board_power_by_turn / board_creatures_by_turn) rather than
a single deck-level average, so a run's own draw quality decides how early its own engine
could plausibly come online — the same T0 nut-draw philosophy `estimate_go_off` and
`estimate_overrun` already use, just resolved per run instead of once for the whole deck.

This does not touch `damage_by_turn` — a non-combat kill is a different EVENT the combat
damage curve was never modeling, and rewriting it retroactively would be inventing combat
damage that didn't happen. Consumers of damage_by_turn (e.g. compute_pod's table-lethal
read) are unaffected by this pass; only kill_turn moves.
"""

from __future__ import annotations

from mythgauntlet.model.card import Card
from mythgauntlet.sim.overrun import earliest_alpha_strike_turn
from mythgauntlet.sim.storm import estimate_go_off
from mythgauntlet.sim.tier0 import RunStats


def apply_nut_kills(
    runs: list[RunStats], cards: list[tuple[Card, int]], turns: int,
    commanders: list[Card] | tuple[Card, ...] = (),
) -> None:
    """Mutates `runs` in place: lowers a run's kill_turn to a non-combat kill whenever the
    storm go-off or overrun alpha-strike detectors fire earlier than combat would have, on
    that SAME run's own mana/board curve. A run with no combat kill (kill_turn is None) gets
    one if either detector fires at all within the horizon.

    The overrun detector also reads the run's own DRAWS (`seen_turn`): an alpha strike needs
    a finisher this game has actually drawn and can cast. `commanders` never need drawing;
    pass them, or a commander that is itself the team pump is never available.
    """
    always = frozenset(c.name for c in commanders)
    for run in runs:
        # (turn, method). The damage kill keeps the method tier0 attributed (B34); a detector
        # wins only when STRICTLY earlier, so a tie stays the damage kill it already was.
        candidates = [(run.kill_turn, run.kill_method)] if run.kill_turn is not None else []

        go_off = estimate_go_off(cards, run.mana_available_by_turn, turns)
        if go_off.earliest_turn is not None:
            candidates.append((go_off.earliest_turn, "storm"))

        alpha_turn = earliest_alpha_strike_turn(
            cards, run.board_power_by_turn, run.board_creatures_by_turn,
            # A simulated game always records its opening hand, so an EMPTY map means no
            # draw telemetry (a hand-built RunStats), not "drew nothing": keep the old read.
            seen_turn=run.seen_turn or None, mana_by_turn=run.mana_available_by_turn,
            always_available=always,
        )
        if alpha_turn is not None:
            candidates.append((alpha_turn, "overrun"))

        if candidates:
            best = min(candidates, key=lambda c: c[0])   # stable: the damage kill wins ties
            run.kill_turn, run.kill_method = best
