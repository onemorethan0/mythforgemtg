"""GreedyAgent — the hand-tuned baseline, and the MCTS rollout policy.

Each `decide` reproduces one iteration of the OLD imperative loops (tier2._main_phase /
_activation_phase / _combat) so that, driven by this agent, sim/game.py mutates state
bit-for-bit as the pre-Phase-7 engine did. The golden master (tests/test_tier2_golden.py) is
the guard on that invariant. This agent consumes NO randomness.
"""

from __future__ import annotations

from mythgauntlet.sim.game import (
    _ACTIVATION_BUDGET,
    ACTIVATION,
    COMBAT_ATTACK,
    COMBAT_BLOCK,
    COUNTER_WINDOW,
    INSTANT_WINDOW,
    MAIN,
    Activate,
    CastCommander,
    CastRemoval,
    CastSpell,
    CounterSpell,
    DeclareAttackers,
    DeclareBlocks,
    Pass,
    PassReaction,
    PlayLand,
    _eligible_attackers,
)
from mythgauntlet.sim.tier0 import _can_pay
from mythgauntlet.sim.tier2 import (
    _COUNTER_MIN_VALUE,
    _TAP_OUT_VALUE,
    _activation_value,
    _card_value,
    _commander_cost,
    _find_counter,
    _find_instant_removal,
    _instant_answer,
    _instant_target,
    _Permanent,
    _Player,
    _reactive_reserve,
    _ready_count,
)


def greedy_block_assignment(
    attackers: list[_Permanent], defender: _Player
) -> dict[int, _Permanent]:
    """The old _combat block logic: winning trades first, then chump-block only lethal damage.

    Keyed by attacker index into `attackers` (whose order the engine fixed at declaration).
    """
    blockers = [c for c in defender.creatures() if not c.tapped]
    assignments: dict[int, _Permanent] = {}
    for i, atk in enumerate(attackers):  # winning trades
        pick = next(
            (b for b in blockers if b.power >= atk.toughness and b.toughness > atk.power),
            None,
        )
        if pick is not None:
            assignments[i] = pick
            blockers.remove(pick)
    unblocked = sum(a.power for i, a in enumerate(attackers) if i not in assignments)
    if unblocked >= defender.life:  # chump-block the biggest threats with what's left
        for i, _atk in enumerate(attackers):
            if i in assignments or not blockers:
                continue
            pick = min(blockers, key=lambda b: b.power)
            assignments[i] = pick
            blockers.remove(pick)
    return assignments


class GreedyAgent:
    name = "greedy"

    def decide(self, state) -> object:
        kind = state.pending.kind
        if kind == MAIN:
            return self._main(state)
        if kind == ACTIVATION:
            return self._activation(state)
        if kind == COUNTER_WINDOW:
            return self._counter_window(state)
        if kind == INSTANT_WINDOW:
            return self._instant_window(state)
        if kind == COMBAT_ATTACK:
            return self._attack(state)
        if kind == COMBAT_BLOCK:
            return self._block(state)
        raise AssertionError(f"greedy: unknown decision {kind!r}")  # pragma: no cover

    def _counter_window(self, state) -> object:
        """Reproduce _counter_chain's greedy step: fight only over a spell worth >= the
        threshold, and then counter with the cheapest payable counterspell in hand."""
        actor = state.players[state.pending.player]
        spell_value = state.pending_spell[2]
        if spell_value < _COUNTER_MIN_VALUE:
            return PassReaction()
        found = _find_counter(actor)
        return CounterSpell(found[0]) if found is not None else PassReaction()

    def _instant_window(self, state) -> object:
        """Reproduce _instant_window's greedy step: kill the active player's biggest threat with
        the first payable instant removal in hand."""
        reactor = state.players[state.pending.player]
        active = state.players[state.active]
        biggest = _instant_target(active)
        if biggest is None:
            return PassReaction()
        found = _find_instant_removal(reactor, biggest)
        return CastRemoval(found[0]) if found is not None else PassReaction()

    def _main(self, state) -> object:
        me, opp = state.me_opp()
        turn, cfg = state.turn, state.cfg
        if not state.land_played:  # land first (as _main_phase did), untapped preferred
            land = next(
                (c for c in me.hand if c.sim.is_land and not c.sim.fx.enters_tapped),
                next((c for c in me.hand if c.sim.is_land), None),
            )
            if land is not None:
                return PlayLand(land)

        reserve = _reactive_reserve(me) if state.casts_this_main else 0
        ready = _ready_count(me)
        best: tuple[float, object] | None = None
        for gc in me.hand:
            if gc.sim.is_land:
                continue
            payment = _can_pay(me.sources, gc.card.cost)
            if payment is None:
                continue
            value = _card_value(gc, me, opp, turn, cfg)
            if value <= 0:  # do-nothing right now -> keep it in hand
                continue
            if (
                not _instant_answer(gc)
                and ready - len(payment) < reserve
                and value < _TAP_OUT_VALUE
            ):
                continue  # hold up mana for a reaction rather than tapping out
            if best is None or value > best[0]:
                best = (value, CastSpell(gc))
        if me.commander_in_zone and me.commander is not None:
            payment = _can_pay(me.sources, _commander_cost(me.commander, me.commander_casts))
            if payment is not None:
                value = _card_value(me.commander, me, opp, turn, cfg) + 1.0
                if not (ready - len(payment) < reserve and value < _TAP_OUT_VALUE) and (
                    best is None or value > best[0]
                ):
                    best = (value, CastCommander())
        return best[1] if best is not None else Pass()

    def _activation(self, state) -> object:
        me, opp = state.me_opp()
        if state.activations_done >= _ACTIVATION_BUDGET:
            return Pass()
        ready = sum(1 for s in me.sources if s.ready)
        reserve = state.activation_reserve
        best: tuple[float, _Permanent, object] | None = None
        for perm in me.battlefield:
            for eff in perm.activated:
                if eff.cost_mana > ready - reserve:
                    continue
                if eff.needs_tap and (perm.tapped or (perm.sick and perm.is_creature)):
                    continue
                value = _activation_value(eff, opp)
                if value > 0 and (best is None or value > best[0]):
                    best = (value, perm, eff)
        if best is None:
            return Pass()
        return Activate(best[1], best[2])

    def _attack(self, state) -> object:
        me, _ = state.me_opp()
        return DeclareAttackers(tuple(_eligible_attackers(me)))  # every eligible creature attacks

    def _block(self, state) -> object:
        defender = state.players[state.pending.player]
        assignment = greedy_block_assignment(state.combat_attackers, defender)
        return DeclareBlocks(tuple(sorted(assignment.items())))
