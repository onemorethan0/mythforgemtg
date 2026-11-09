"""GreedyAgent — the hand-tuned baseline, and the MCTS rollout policy.

Each `decide` reproduces one iteration of the OLD imperative loops (tier2._main_phase /
_activation_phase / _combat) so that, driven by this agent, sim/game.py mutates state
bit-for-bit as the pre-Phase-7 engine did. The golden master (tests/test_tier2_golden.py) is
the guard on that invariant. This agent consumes NO randomness.

The mana pilot (2026-11-08, golden master re-captured on purpose): the land played is the one
that leaves the most spells in hand castable -- colours counted -- instead of the first untapped
land; and a player holding an instant answer keeps the COLOURS for its cheapest one open from the
first cast of the turn, not only after one. Measured first (D6): a seat holding a counterspell
could pay for it in about 1-5% of the moments a spell worth countering was cast; the causes were
colour screw, too few lands, and tapping out on the first spell.
"""

from __future__ import annotations

from dataclasses import replace

from mythgauntlet.sim.game import (
    _ACTIVATION_BUDGET,
    ACTIVATION,
    COMBAT_ATTACK,
    COMBAT_BLOCK,
    COUNTER_WINDOW,
    EOT_WINDOW,
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
    _held_answer_cost,
    _primary_of,
    eot_castable,
    instant_speed,
    pay_keeping,
    walker_attack_plan,
)
from mythgauntlet.sim.tier0 import _can_pay, _Source
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
    cast_cost,
    loyalty_ready,
)


def _keeps_answer_up(me: _Player, cost, exclude=None) -> bool:
    """Can `cost` be paid while the cheapest held instant answer stays castable -- colours
    counted, using the same joint payment `sim.game.apply` makes (`pay_keeping`)? No held
    answer: nothing to keep up."""
    keep = _held_answer_cost(me, exclude=exclude)
    return keep is None or pay_keeping(me.sources, cost, keep) is not None


def _hits_the_table(gc) -> bool:
    """A spell that affects every opponent: a board wipe, or an effect the interpreter applies
    to `each_opponent` (drains, group discard, each-opponent damage)."""
    if gc.profile.wipe:
        return True
    return "each_opponent" in repr(gc.resolve_abilities or ())


def _worth_my_counter(state, me_key: str) -> bool:
    """Should THIS seat spend a counter on the spell on the stack? (pods; 1v1 always fights)

    A counter is a 1-for-1 with one player; at a 4-player table the two seats that didn't spend
    a card gain from it for free. So a seat fights only when the spell is its problem:
      - it is the caster (protecting its own spell -- the counter-back);
      - it is the caster's primary opponent, the seat combat and single-target effects focus on;
      - the spell hits the whole table (a wipe, an each-opponent effect);
      - the caster is the archenemy (the biggest threat at the table already); or
      - the spell is near-lethal or completes a combo (value >= the tap-out bar).
    Otherwise it passes, and priority moves on to the seat the spell is aimed at."""
    gc, _is_cmdr, value, caster = state.pending_spell
    if me_key == caster:
        return True
    if value >= _TAP_OUT_VALUE:
        return True
    if me_key == state.other:          # the caster is the active player
        return True
    if _hits_the_table(gc):
        return True
    living = state.living()
    top = max(living, key=lambda k: (state.players[k].score(), -state.order.index(k)))
    return top == caster


def _best_land(me: _Player, lands: list) -> object:
    """The land that leaves the most nonland cards in hand castable once everything untaps --
    colours counted, the cheapest held instant answer counted twice (it is what the player is
    holding mana for). Ties: an untapped land, then the one producing more colours, then hand
    order (deterministic)."""
    spells = [gc for gc in me.hand if not gc.sim.is_land]
    base = [replace(src, ready=True) for src in me.sources if not src.temp]
    answers = [gc for gc in spells if _instant_answer(gc)]
    key_answer = min(answers, key=lambda gc: gc.card.mana_value) if answers else None

    def score(land):
        pool = base + [_Source(land.sim.produced_colors(), ready=True)]
        castable = sum(1 for gc in spells if _can_pay(pool, cast_cost(me, gc)) is not None)
        if key_answer is not None and _can_pay(pool, cast_cost(me, key_answer)) is not None:
            castable += 1
        return (castable, not land.sim.fx.enters_tapped, len(land.sim.produced_colors()))

    best, best_score = None, None
    for land in lands:
        sc = score(land)
        if best_score is None or sc > best_score:
            best, best_score = land, sc
    return best


def _can_block(atk: _Permanent, blockers: list[_Permanent]) -> list[_Permanent]:
    """CR 702.9b: a flying attacker can only be blocked by a creature with flying or reach.

    A non-flying attacker is unaffected by this filter -- a flier can still block it.
    """
    if not atk.has_keyword("flying"):
        return blockers
    return [b for b in blockers if b.has_keyword("flying") or b.has_keyword("reach")]


def _legal_blockers(atk: _Permanent, blockers: list[_Permanent]) -> list[_Permanent]:
    """Creatures that may block `atk` ALONE. A menace attacker can't be blocked except by two
    or more creatures (CR 702.110b), so no single blocker is legal; `_menace_pair` decides a
    double block."""
    if atk.has_keyword("menace"):
        return []
    return _can_block(atk, blockers)


def _duel(atk: _Permanent, blk: _Permanent) -> tuple[bool, bool]:
    """(attacker dies, blocker dies) for a one-on-one block, honouring first/double strike and
    deathtouch the way `game._resolve_combat_steps` resolves it -- so the defender's "is this a
    winning block" read matches what combat will actually do (a 2/2 double striker kills a 3/3)."""
    def strikes(p, step):
        fs, ds = p.has_keyword("first strike"), p.has_keyword("double strike")
        return (fs or ds) if step == "first" else (ds or not fs)

    dmg = {"a": 0, "b": 0}
    dead = {"a": False, "b": False}
    for step in ("first", "regular"):
        if not dead["a"] and strikes(atk, step) and atk.combat_power > 0:
            dmg["b"] += atk.combat_power
            if atk.has_keyword("deathtouch"):
                dead["b"] = True
        if not dead["b"] and strikes(blk, step) and blk.combat_power > 0:
            dmg["a"] += blk.combat_power
            if blk.has_keyword("deathtouch"):
                dead["a"] = True
        dead["a"] = dead["a"] or dmg["a"] >= atk.toughness
        dead["b"] = dead["b"] or dmg["b"] >= blk.toughness
    return dead["a"], dead["b"]


def _pair_kills(atk: _Permanent, pair) -> bool:
    return (sum(b.combat_power for b in pair) >= atk.toughness
            or any(b.has_keyword("deathtouch") and b.combat_power > 0 for b in pair))


def _menace_pair(atk: _Permanent, blockers: list[_Permanent], *, winning: bool):
    """Two blockers for a menace attacker, or None. `winning`: the pair kills it and it can
    kill neither (the cheapest such pair). Otherwise (a chump against lethal): the two
    cheapest legal bodies. Deliberately conservative -- no three-way blocks, no trades."""
    legal = sorted(_can_block(atk, blockers), key=lambda b: b.power + b.toughness)
    if len(legal) < 2:
        return None
    if not winning:
        return (legal[0], legal[1])
    if atk.has_keyword("first strike") or atk.has_keyword("double strike"):
        return None  # it kills a blocker before the pair strikes back; never a clean win
    best = None
    for x in range(len(legal)):
        for y in range(x + 1, len(legal)):
            pair = (legal[x], legal[y])
            if _pair_kills(atk, pair) and not any(atk.deals_lethal_to(b) for b in pair):
                cost = sum(b.power + b.toughness for b in pair)
                if best is None or cost < best[0]:
                    best = (cost, pair)
    return best[1] if best else None


def greedy_block_assignment(
    attackers: list[_Permanent], defender: _Player,
    on_walker: dict[int, _Permanent] | None = None,
) -> dict[int, object]:
    """The old _combat block logic: winning trades first, then chump-block only lethal damage.

    Keyed by attacker index into `attackers` (whose order the engine fixed at declaration).
    """
    blockers = [c for c in defender.creatures() if not c.tapped]
    assignments: dict[int, object] = {}
    for i, atk in enumerate(attackers):  # winning trades
        if atk.has_keyword("menace"):
            pair = _menace_pair(atk, blockers, winning=True)
            if pair is not None:
                assignments[i] = pair
                for b in pair:
                    blockers.remove(b)
            continue
        legal = _legal_blockers(atk, blockers)
        # _duel accounts for deathtouch (CR 702.2b) and first/double strike: a low-power,
        # high-toughness deathtouch blocker can profitably trade with a much bigger attacker,
        # and a first striker can kill its blocker before it is ever hit back.
        pick = next(
            (b for b in legal if _duel(atk, b) == (True, False)),
            None,
        )
        if pick is not None:
            assignments[i] = pick
            blockers.remove(pick)
    on_walker = on_walker or {}
    # PROTECT a walker that would die: block the attackers aimed at it with the cheapest legal
    # bodies until the loyalty survives. A planeswalker is a whole card that keeps paying
    # (a token maker costs far more than the 1/1 that chumps for it); without this the
    # attack-the-walker plan alone overcorrected and walkers simply died (Elspeth, Sun's
    # Champion went 24 -> 3 wins of 60 against a bear deck that had three chump tokens).
    for walker in {id(w): w for w in on_walker.values()}.values():
        idxs = sorted((i for i, w in on_walker.items() if w is walker and i not in assignments),
                      key=lambda i: attackers[i].combat_power, reverse=True)
        incoming = sum(attackers[i].combat_power for i in idxs)
        for i in idxs:
            if incoming < walker.loyalty:
                break
            if attackers[i].has_keyword("menace"):
                pair = _menace_pair(attackers[i], blockers, winning=False)
                if pair is None:
                    continue
                assignments[i] = pair
                for b in pair:
                    blockers.remove(b)
                incoming -= attackers[i].combat_power
                continue
            legal = _legal_blockers(attackers[i], blockers)
            if not legal:
                continue
            pick = min(legal, key=lambda b: b.power + b.toughness)
            assignments[i] = pick
            blockers.remove(pick)
            incoming -= attackers[i].combat_power
    # attackers declared against a planeswalker threaten its loyalty, not the life total
    unblocked = sum(a.combat_power for i, a in enumerate(attackers)
                    if i not in assignments and i not in on_walker)
    if unblocked >= defender.life:  # chump-block the biggest threats with what's left
        for i, atk in enumerate(attackers):
            if i in assignments or i in on_walker or not blockers:
                continue
            if atk.has_keyword("menace"):
                pair = _menace_pair(atk, blockers, winning=False)
                if pair is not None:
                    assignments[i] = pair
                    for b in pair:
                        blockers.remove(b)
                continue
            legal = _legal_blockers(atk, blockers)
            if not legal:
                continue
            pick = min(legal, key=lambda b: b.power)
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
        if kind == EOT_WINDOW:
            return self._end_of_turn(state)
        if kind == INSTANT_WINDOW:
            return self._instant_window(state)
        if kind == COMBAT_ATTACK:
            return self._attack(state)
        if kind == COMBAT_BLOCK:
            return self._block(state)
        raise AssertionError(f"greedy: unknown decision {kind!r}")  # pragma: no cover

    def _end_of_turn(self, state) -> object:
        """Draw-go: spend the mana held up through this turn on the best instant-speed spell
        (draw, a flash creature, instant removal) before untapping; Pass when none is worth it."""
        key = state.pending.player
        me = state.players[key]
        opp = state.players[_primary_of(state, key)]
        best: tuple[float, object] | None = None
        for gc in eot_castable(me):
            value = _card_value(gc, me, opp, state.turn, state.cfg)
            if value > 0 and (best is None or value > best[0]):
                best = (value, CastSpell(gc))
        return best[1] if best is not None else Pass()

    def _counter_window(self, state) -> object:
        """Reproduce _counter_chain's greedy step: fight only over a spell worth >= the
        threshold, and then counter with the cheapest payable counterspell in hand."""
        actor = state.players[state.pending.player]
        spell_value = state.pending_spell[2]
        if spell_value < _COUNTER_MIN_VALUE:
            return PassReaction()
        if state.multiplayer and not _worth_my_counter(state, state.pending.player):
            return PassReaction()   # aimed at someone else: let them spend the card
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
        if not state.land_played:  # land first, the one that best fixes the hand's colours
            lands = [c for c in me.hand if c.sim.is_land]
            if lands:
                return PlayLand(_best_land(me, lands))

        best: tuple[float, object] | None = None
        for gc in me.hand:
            if gc.sim.is_land:
                continue
            if gc.profile.counter:
                # a counterspell needs a spell on the stack to target (CR 115.1 / 601.2c): in a
                # main phase with an empty stack it can't legally be cast, and casting it threw
                # the counter away -- it waits for a COUNTER_WINDOW
                continue
            if (instant_speed(gc) and not _instant_answer(gc)
                    and "add_mana" not in repr(gc.resolve_abilities or ())):  # rituals: now
                # draw-go: an instant-speed spell that isn't an answer waits for the end of the
                # turn before ours (sim.game EOT_WINDOW) -- the mana stays up for a counter
                # meanwhile, and a flash creature cast then still attacks on our turn
                continue
            payment = _can_pay(me.sources, cast_cost(me, gc))
            if payment is None:
                continue
            value = _card_value(gc, me, opp, turn, cfg)
            if value <= 0:  # do-nothing right now -> keep it in hand
                continue
            if (not _instant_answer(gc) and value < _TAP_OUT_VALUE
                    and not _keeps_answer_up(me, cast_cost(me, gc), exclude=gc)):
                continue  # keep the colours for the held answer open rather than tap out
            if best is None or value > best[0]:
                best = (value, CastSpell(gc))
        if me.commander_in_zone and me.commander is not None:
            payment = _can_pay(me.sources, _commander_cost(me.commander, me.commander_casts, me))
            if payment is not None:
                value = _card_value(me.commander, me, opp, turn, cfg) + 1.0
                held = value < _TAP_OUT_VALUE and not _keeps_answer_up(
                    me, _commander_cost(me.commander, me.commander_casts, me))
                if not held and (best is None or value > best[0]):
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
                if not loyalty_ready(perm, eff):
                    continue
                value = _activation_value(eff, opp)
                if value > 0 and (best is None or value > best[0]):
                    best = (value, perm, eff)
        if best is None:
            return Pass()
        return Activate(best[1], best[2])

    def _attack(self, state) -> object:
        me, _ = state.me_opp()
        _, opp = state.me_opp()
        eligible = _eligible_attackers(me)  # every eligible creature attacks
        return DeclareAttackers(tuple(eligible), walker_attack_plan(eligible, opp))

    def _block(self, state) -> object:
        defender = state.players[state.pending.player]
        assignment = greedy_block_assignment(
            state.combat_attackers, defender, state.combat_walkers)
        return DeclareBlocks(tuple(sorted(assignment.items())))
