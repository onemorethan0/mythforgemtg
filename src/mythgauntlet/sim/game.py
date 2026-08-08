"""Action-based Tier-2 state machine (docs/SIMULATION.md, Phase 7).

The imperative turn loop (`tier2._play_game` and its greedy `while` loops) is re-expressed here
as an explicit, clonable state machine an **Agent** drives one decision at a time. This is what
MCTS needs: a state you can clone + determinize, legal actions to branch on, and an `apply` that
advances to the next decision.

Decision points (an agent's `decide` is queried at each):
  - MAIN            active player: PlayLand / CastSpell / CastCommander / Pass
  - ACTIVATION      active player: Activate / Pass   (after casts, mirrors _activation_phase)
  - COUNTER_WINDOW  reactor:       CounterSpell / PassReaction   (a spell is on the stack)
  - COMBAT_ATTACK   active player: DeclareAttackers
  - COMBAT_BLOCK    defender:      DeclareBlocks
  - INSTANT_WINDOW  reactor:       CastRemoval / PassReaction    (pre-combat, active has a threat)

Reactions are SEARCHED decisions (2026-07-21): when a spell is cast it goes on the stack and
each player in turn gets a COUNTER_WINDOW decision (LIFO counter-war); before combat the non-
active player gets INSTANT_WINDOW decisions to remove threats. Previously these resolved
automatically greedy inside `apply`; now an Agent chooses, so ISMCTS can counter a spell the
greedy value gate would let resolve, or hold a counter greedy would spend. A window only
becomes a decision when the reactor actually has a payable answer (else `advance` resolves it),
so search never branches on a non-choice. Everything else runs deterministically in `advance()`:
untap, upkeep/draw triggers, the draw step, state-based win checks, the combo check.

Behavior preservation: driven by the GreedyAgent (agents/greedy.py), this reproduces the old
engine's mutations bit-for-bit — the greedy reaction handlers reproduce `_counter_chain` /
`_instant_window` exactly (same value gate, same cheapest-counter / first-payable-removal
choice, same LIFO parity). RNG is consumed only at deck shuffle + per-game spawn, and greedy
decisions consume none. The golden master (tests/test_tier2_golden.py) is the guard.
Determinism: invariant #1 — all RNG via SeededRng.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from mythgauntlet.sim.rng import SeededRng
from mythgauntlet.sim.tier0 import _Source
from mythgauntlet.sim.tier2 import (
    GameCard,
    _apply_instant_removal,
    _commander_cost,
    _find_counter,
    _find_instant_removal,
    _fire_attack_triggers,
    _fire_perm_triggers,
    _fire_triggers,
    _instant_target,
    _kill,
    _Permanent,
    _Player,
    _resolve,
)

# --- actions -----------------------------------------------------------------------------

MAIN = "main"
ACTIVATION = "activation"
COUNTER_WINDOW = "counter_window"
COMBAT_ATTACK = "combat_attack"
COMBAT_BLOCK = "combat_block"
INSTANT_WINDOW = "instant_window"


@dataclass(frozen=True)
class PlayLand:
    card: GameCard


@dataclass(frozen=True)
class CastSpell:
    card: GameCard


@dataclass(frozen=True)
class CastCommander:
    pass


@dataclass(frozen=True)
class Activate:
    perm: _Permanent
    effect: object  # ActivatedEffect


@dataclass(frozen=True)
class Pass:
    pass


@dataclass(frozen=True)
class CounterSpell:
    """Reactor counters the spell currently on the stack with `card` (a counterspell)."""

    card: GameCard


@dataclass(frozen=True)
class CastRemoval:
    """Reactor casts instant removal `card` at the active player's biggest creature."""

    card: GameCard


@dataclass(frozen=True)
class PassReaction:
    """Reactor declines to react in the current window (counter or instant removal)."""

    pass


@dataclass(frozen=True)
class DeclareAttackers:
    attackers: tuple[_Permanent, ...]


@dataclass(frozen=True)
class DeclareBlocks:
    # attacker-index (into state.combat_attackers) -> blocking permanent
    assignment: tuple[tuple[int, _Permanent], ...] = ()

    def as_dict(self) -> dict[int, _Permanent]:
        return dict(self.assignment)


@dataclass(frozen=True)
class Decision:
    player: str  # key of the player who must choose
    kind: str    # MAIN/ACTIVATION/COUNTER_WINDOW/COMBAT_ATTACK/COMBAT_BLOCK/INSTANT_WINDOW


# --- state -------------------------------------------------------------------------------


@dataclass
class GameState:
    players: dict[str, _Player]
    order: list[str]
    cfg: object  # DuelConfig
    turn: int = 1
    pos: int = 0
    active: str = "a"
    phase: str = "turn_start"
    # per-turn / per-phase bookkeeping (mirrors the old imperative loops)
    land_played: bool = False
    casts_this_main: int = 0
    combat_begun: bool = False
    activation_reserve: int = 0
    activations_done: int = 0
    combat_attackers: list[_Permanent] = field(default_factory=list)
    # Who the attack was declared against, LOCKED for the whole combat.
    #
    # `other` is a computed property — the highest-scoring living opponent — and combat read
    # it afresh at every step: to fire attack triggers, to pick who declares blocks, and
    # again to assign combat damage. An attack trigger that drains or kills in between (an
    # ordinary pod occurrence) re-ranks the threats, so blocks were declared by one seat and
    # the damage landed on another, which never had a chance to block. CR 506.3/508.1: an
    # attacker is declared as attacking a specific player and that does not change.
    # None outside combat. In 1v1 there is only ever one opponent, so this is a no-op there
    # and the golden master is unaffected.
    combat_defender: str | None = None
    # a spell on the stack awaiting counter/resolution: (card, is_commander, value, caster_key)
    pending_spell: tuple[GameCard, bool, float, str] | None = None
    counters_on_stack: int = 0  # counters played over the pending spell (LIFO parity)
    reaction_actor: str | None = None  # whose reaction priority it is (COUNTER/INSTANT window)
    eliminated: set[str] = field(default_factory=set)  # dead players (N-player; empty in 1v1)
    pending: Decision | None = None
    terminal: bool = False
    result: tuple[str, int, str] | None = None  # (winner, turns, reason)

    @property
    def multiplayer(self) -> bool:
        return len(self.order) > 2

    def living(self) -> list[str]:
        return [k for k in self.order if k not in self.eliminated]

    def opponents_of(self, key: str) -> list[_Player]:
        return [self.players[k] for k in self.living() if k != key]

    @property
    def other(self) -> str:
        """The active player's PRIMARY opponent: the sole other seat in 1v1, else the biggest
        threat (highest board+life score) among the living — the seat combat/single-target
        effects focus. Reduces to the old positional `other` at N=2 (one opponent)."""
        opps = [k for k in self.living() if k != self.active]
        if len(opps) == 1:
            return opps[0]
        if not opps:
            return self.active  # degenerate (game should have ended); avoid crashing
        return max(opps, key=lambda k: (self.players[k].score(), -self.order.index(k)))

    def me_opp(self) -> tuple[_Player, _Player]:
        return self.players[self.active], self.players[self.other]

    @property
    def combat_defender_key(self) -> str:
        """Seat KEY of the player combat was declared against (not `_Player.name`, which is
        a display name and does not always match the key). Falls back to `other` outside a
        declared combat, or if that seat has since been eliminated."""
        key = self.combat_defender
        if key is None or key in self.eliminated or key not in self.players:
            return self.other
        return key

    def combat_me_opp(self) -> tuple[_Player, _Player]:
        """(attacker, DEFENDER) — the seat combat was declared against, not the current
        biggest threat."""
        return self.players[self.active], self.players[self.combat_defender_key]


_ACTIVATION_BUDGET = 8  # cap per turn (was _activation_phase's `budget`), also bounds rollouts


# --- clone (for MCTS) --------------------------------------------------------------------


def _clone_player(p: _Player) -> _Player:
    """Independent copy: new mutable containers + permanents/sources, shared frozen GameCards."""
    return _Player(
        name=p.name,
        library=list(p.library),
        hand=list(p.hand),
        battlefield=[replace(perm) for perm in p.battlefield],
        sources=[replace(s) for s in p.sources],
        life=p.life,
        commander=p.commander,
        commander_in_zone=p.commander_in_zone,
        commander_casts=p.commander_casts,
        decked=p.decked,
        combos=p.combos,
        combo_pieces=p.combo_pieces,
    )


def clone(state: GameState) -> GameState:
    new = GameState(
        players={k: _clone_player(v) for k, v in state.players.items()},
        order=list(state.order),
        cfg=state.cfg,
        turn=state.turn,
        pos=state.pos,
        active=state.active,
        phase=state.phase,
        land_played=state.land_played,
        casts_this_main=state.casts_this_main,
        combat_begun=state.combat_begun,
        activation_reserve=state.activation_reserve,
        activations_done=state.activations_done,
        pending_spell=state.pending_spell,
        counters_on_stack=state.counters_on_stack,
        reaction_actor=state.reaction_actor,
        eliminated=set(state.eliminated),
        pending=state.pending,
        terminal=state.terminal,
        result=state.result,
        combat_defender=state.combat_defender,
    )
    # combat_attackers references permanents; remap to the cloned battlefield by identity->index
    if state.combat_attackers:
        src = state.players[state.active].battlefield
        idx = {id(p): i for i, p in enumerate(src)}
        dst = new.players[new.active].battlefield
        new.combat_attackers = [dst[idx[id(p)]] for p in state.combat_attackers if id(p) in idx]
    return new


# --- determinization + search hooks (for ISMCTS) -----------------------------------------


def _other_key(players: dict[str, _Player], key: str) -> str:
    return next(k for k in players if k != key)


def determinize(state: GameState, observer: str, rng: SeededRng) -> GameState:
    """A clone with the hidden information re-sampled to one concrete world consistent with what
    `observer` can see. Observer's own library ORDER is unknown -> reshuffle it (hand/board are
    known). The opponent's hand + library are hidden -> pool them, reshuffle, and re-deal the
    (public) hand size. In a known-deck gauntlet the card multiset of each deck is known; only
    the hidden zones' identities/order are sampled. Battlefield, sources, life, commander zone,
    and hand SIZES are public and preserved by clone().
    """
    d = clone(state)
    obs = d.players[observer]
    opp = d.players[_other_key(d.players, observer)]
    rng.shuffle(obs.library)
    hidden = opp.hand + opp.library
    rng.shuffle(hidden)
    n = len(opp.hand)
    opp.hand = hidden[:n]
    opp.library = hidden[n:]
    return d


def action_key(action: object) -> tuple:
    """A hashable, determinization-stable identity for an action. Two actions share a key iff
    search should treat them as the same choice (e.g. casting any copy of a card). Actions carry
    unhashable GameCard/Card refs, so the tree keys on this, not the action object."""
    if isinstance(action, Pass):
        return ("pass",)
    if isinstance(action, PlayLand):
        return ("land", action.card.name)
    if isinstance(action, CastSpell):
        return ("cast", action.card.name)
    if isinstance(action, CastCommander):
        return ("commander",)
    if isinstance(action, Activate):
        return ("activate", action.perm.name)
    if isinstance(action, DeclareAttackers):
        return ("attack", tuple(sorted(p.name for p in action.attackers)))
    if isinstance(action, DeclareBlocks):
        return ("block", tuple(sorted((i, b.name) for i, b in action.assignment)))
    if isinstance(action, PassReaction):
        return ("pass_reaction",)
    if isinstance(action, CounterSpell):
        return ("counter", action.card.name)
    if isinstance(action, CastRemoval):
        return ("removal", action.card.name)
    raise AssertionError(f"no key for action {action!r}")  # pragma: no cover


def terminal_reward(state: GameState, player: str) -> float:
    """+1 if `player` won, -1 if it lost, 0 for a draw. Only valid when state.terminal."""
    winner = state.result[0] if state.result else "draw"
    if winner == "draw":
        return 0.0
    return 1.0 if winner == player else -1.0


def score_reward(state: GameState, player: str) -> float:
    """Leaf evaluation for a truncated (non-terminal) rollout: the adjudication-score
    differential from `player`'s view, squashed into [-1, 1]. Reuses _Player.score()."""
    other = _other_key(state.players, player)
    diff = state.players[player].score() - state.players[other].score()
    return math.tanh(diff / float(state.cfg.start_life))


# --- deterministic turn structure --------------------------------------------------------


def _finish(state: GameState, winner: str, reason: str) -> None:
    state.terminal = True
    state.result = (winner, state.turn, reason)
    state.phase = "terminal"
    state.pending = None


def _adjudicate(state: GameState) -> None:
    """Turn-cap adjudication: the highest-scoring LIVING player wins; a tie for the top is a
    draw. Reduces to _play_game's exact 1v1 rule at N=2 (a>b -> a, equal -> draw)."""
    ranked = sorted(
        state.living(), key=lambda k: (state.players[k].score(), -state.order.index(k)),
        reverse=True,
    )
    top = ranked[0]
    tie = len(ranked) >= 2 and abs(
        state.players[top].score() - state.players[ranked[1]].score()
    ) < 1e-9
    state.terminal = True
    state.result = (
        ("draw", state.cfg.max_turns, "draw") if tie
        else (top, state.cfg.max_turns, "adjudicated")
    )
    state.phase = "terminal"


def _register_deaths(state: GameState) -> bool:
    """N-player elimination: any living player at <=0 life or decked is out; the game ends when
    one (or zero) remains. Returns True if the game finished. 1v1 keeps its exact win-checks."""
    for k in state.living():
        p = state.players[k]
        if p.decked or p.life <= 0:
            state.eliminated.add(k)
    living = state.living()
    if len(living) <= 1:
        _finish(state, living[0] if living else "draw", "eliminated")
        return True
    return False


def _to_next_halfturn(state: GameState) -> None:
    if not state.multiplayer:
        if state.pos == 0:  # 1v1 path: unchanged (golden master byte-identical)
            state.pos = 1
        else:
            state.pos = 0
            state.turn += 1
        if state.turn > state.cfg.max_turns:
            _adjudicate(state)
            return
        state.active = state.order[state.pos]
        state.phase = "turn_start"
        return
    # N-player: rotate to the next LIVING seat, bumping the turn each time seat 0 comes up.
    n = len(state.order)
    for _ in range(n):
        state.pos = (state.pos + 1) % n
        if state.pos == 0:
            state.turn += 1
        if state.order[state.pos] not in state.eliminated:
            break
    if state.turn > state.cfg.max_turns:
        _adjudicate(state)
        return
    state.active = state.order[state.pos]
    state.phase = "turn_start"


def _do_turn_start(state: GameState) -> None:
    me, opp = state.me_opp()
    me.sources = [s for s in me.sources if not s.temp]  # ritual mana expires
    for s in me.sources:
        s.ready = True
    for c in me.battlefield:
        c.sick = False
        c.tapped = False
    # CR 103.8a: "In a two-player game, the player who plays first skips the draw step of
    # their first turn." CR 103.8c: "In all other multiplayer games, no player skips the
    # draw step of their first turn." The skip is a TWO-PLAYER rule; applying it in a pod
    # docked the starting seat a card in every 4-player game the format's brackets are
    # actually defined for.
    skips_first_draw = state.turn == 1 and state.pos == 0 and not state.multiplayer
    if not skips_first_draw:
        me.draw(1)
    me.draw(me.engine_draws())
    others = _others(state)
    _fire_triggers(me, opp, "upkeep", others)
    _fire_triggers(me, opp, "draw_step", others)
    if state.multiplayer:
        if _register_deaths(state):
            return
    else:
        if me.decked:
            _finish(state, state.other, "decked")
            return
        if opp.life <= 0:
            _finish(state, state.active, "life")
            return
    state.land_played = False
    state.casts_this_main = 0
    state.combat_begun = False
    state.phase = MAIN


def _do_post_main(state: GameState) -> None:
    me, opp = state.me_opp()
    if state.multiplayer:
        if _register_deaths(state):
            return
        if me.combo_ready():  # a game-ending combo wins the whole table
            _finish(state, state.active, "combo")
            return
        # reactions (the instant window) are a 1v1-only feature for now -> straight to combat
        state.phase = COMBAT_ATTACK
        return
    if me.decked:
        _finish(state, state.other, "decked")
    elif opp.life <= 0:
        _finish(state, state.active, "life")
    elif me.combo_ready():
        _finish(state, state.active, "combo")
    else:
        state.phase = INSTANT_WINDOW


def _resolve_pending_spell(state: GameState) -> None:
    """Take the spell off the stack: countered iff an odd number of counters landed (LIFO),
    else it resolves. Then hand priority back to the caster's main phase."""
    gc, is_commander, _value, caster_key = state.pending_spell
    caster = state.players[caster_key]
    opp = state.players[_other_key(state.players, caster_key)]
    if state.counters_on_stack % 2 == 1:  # countered
        if is_commander:
            caster.commander_in_zone = True  # returns to the command zone (tax already counted)
    else:
        _resolve(gc, caster, opp, is_commander)
    state.pending_spell = None
    state.counters_on_stack = 0
    state.reaction_actor = None
    state.phase = MAIN  # the caster keeps casting (the window opened from its MAIN)


def _reactor_can_counter(state: GameState) -> bool:
    return _find_counter(state.players[state.reaction_actor]) is not None


def _others(state: GameState) -> tuple[_Player, ...]:
    """The active player's pod opponents BEYOND its primary threat (empty in 1v1). Passed to
    the effect layer so an "each opponent" effect the active player generates scales across the
    whole table, while single-target effects still hit the primary (`state.other`)."""
    if not state.multiplayer:
        return ()
    primary = state.other
    return tuple(
        state.players[k] for k in state.living() if k != state.active and k != primary
    )


def _do_end_step(state: GameState) -> None:
    me, opp = state.me_opp()
    _fire_triggers(me, opp, "end_step", _others(state))
    if state.multiplayer:
        if _register_deaths(state):
            return
        state.phase = "next"
        return
    if opp.life <= 0:
        _finish(state, state.active, "life")
    elif me.life <= 0:
        _finish(state, state.other, "life")
    else:
        state.phase = "next"


def advance(state: GameState) -> None:
    """Run deterministic phases until a decision is needed (sets `pending`) or the game ends."""
    while not state.terminal:
        ph = state.phase
        if ph == "terminal":
            return
        if ph == "turn_start":
            _do_turn_start(state)
        elif ph == MAIN:
            state.pending = Decision(state.active, MAIN)
            return
        elif ph == ACTIVATION:
            state.pending = Decision(state.active, ACTIVATION)
            return
        elif ph == COUNTER_WINDOW:
            # a spell is on the stack; the reactor decides only if it CAN counter, else resolve
            if _reactor_can_counter(state):
                state.pending = Decision(state.reaction_actor, COUNTER_WINDOW)
                return
            _resolve_pending_spell(state)
        elif ph == "post_main":
            _do_post_main(state)
        elif ph == INSTANT_WINDOW:
            state.reaction_actor = state.other  # the non-active player removes threats
            reactor, active = state.players[state.other], state.players[state.active]
            biggest = _instant_target(active)
            if biggest is not None and _find_instant_removal(reactor, biggest) is not None:
                state.pending = Decision(state.other, INSTANT_WINDOW)
                return
            state.reaction_actor = None
            state.phase = COMBAT_ATTACK
        elif ph == COMBAT_ATTACK:
            if not state.combat_begun:
                # The beginning-of-combat step happens whether or not anyone can attack,
                # so this fires BEFORE the eligible-attackers check. Guarded by a
                # per-turn flag because two phase transitions lead here (1v1 goes through
                # the instant window, multiplayer straight from post-main) and an ISMCTS
                # clone can re-enter the branch.
                state.combat_begun = True
                _fire_triggers(state.players[state.active], state.players[state.other],
                               "begin_combat", _others(state))
            if not _eligible_attackers(state.players[state.active]):
                state.phase = "end_step"
                continue
            state.pending = Decision(state.active, COMBAT_ATTACK)
            return
        elif ph == COMBAT_BLOCK:
            # the seat that was attacked declares the blocks, not whoever is biggest now
            state.pending = Decision(state.combat_defender_key, COMBAT_BLOCK)
            return
        elif ph == "end_step":
            _do_end_step(state)
        elif ph == "next":
            _to_next_halfturn(state)
        else:  # pragma: no cover - guard
            raise AssertionError(f"unknown phase {ph!r}")


# --- legal actions (for search) ----------------------------------------------------------


def _eligible_attackers(me: _Player) -> list[_Permanent]:
    atk = [c for c in me.creatures() if not c.sick and not c.tapped and c.power > 0]
    atk.sort(key=lambda c: c.power, reverse=True)
    return atk


def _payable_casts(state: GameState) -> list[GameCard]:
    from mythgauntlet.sim.tier0 import _can_pay

    me, _ = state.me_opp()
    seen: set[int] = set()
    out: list[GameCard] = []
    for gc in me.hand:
        if gc.sim.is_land or id(gc) in seen:
            continue
        seen.add(id(gc))
        if _can_pay(me.sources, gc.card.cost) is not None:
            out.append(gc)
    return out


def legal_actions(state: GameState) -> list[object]:
    """Legal actions for the pending decision. Used by search; GreedyAgent re-derives its own
    choice directly (so its ordering/tie-breaks stay bit-identical to the old loops)."""
    from mythgauntlet.sim.tier0 import _can_pay

    if state.pending is None:
        return []
    me, _ = state.me_opp()
    kind = state.pending.kind
    if kind == MAIN:
        actions: list[object] = [Pass()]
        if not state.land_played:
            lands = {id(c): c for c in me.hand if c.sim.is_land}
            actions.extend(PlayLand(c) for c in lands.values())
        actions.extend(CastSpell(gc) for gc in _payable_casts(state))
        if me.commander_in_zone and me.commander is not None and _can_pay(
            me.sources, _commander_cost(me.commander, me.commander_casts)
        ) is not None:
            actions.append(CastCommander())
        return actions
    if kind == ACTIVATION:
        actions = [Pass()]
        if state.activations_done < _ACTIVATION_BUDGET:
            ready = sum(1 for s in me.sources if s.ready)
            for perm in me.battlefield:
                for eff in perm.activated:
                    if eff.cost_mana > ready - state.activation_reserve:
                        continue
                    if eff.needs_tap and (perm.tapped or (perm.sick and perm.is_creature)):
                        continue
                    actions.append(Activate(perm, eff))
        return actions
    if kind == COUNTER_WINDOW:
        actor = state.players[state.pending.player]
        actions = [PassReaction()]
        seen_ctr: set[int] = set()
        for gc in actor.hand:
            p = gc.profile
            if not (p.counter and p.is_instant) or id(gc) in seen_ctr:
                continue
            seen_ctr.add(id(gc))
            if _can_pay(actor.sources, gc.card.cost) is not None:
                actions.append(CounterSpell(gc))
        return actions
    if kind == INSTANT_WINDOW:
        reactor = state.players[state.pending.player]
        active = state.players[state.active]
        actions = [PassReaction()]
        biggest = _instant_target(active)
        if biggest is not None:
            seen_rm: set[int] = set()
            for gc in reactor.hand:
                p = gc.profile
                if id(gc) in seen_rm or not p.is_instant:
                    continue
                if not (p.removal > 0 or (p.damage_any > 0 and biggest.toughness <= p.damage_any)):
                    continue
                seen_rm.add(id(gc))
                if _can_pay(reactor.sources, gc.card.cost) is not None:
                    actions.append(CastRemoval(gc))
        return actions
    if kind == COMBAT_ATTACK:
        eligible = _eligible_attackers(me)
        # bounded candidate sets: all-out, none, and all-but-one (hold a blocker back)
        cands = [tuple(eligible), ()]
        for i in range(len(eligible)):
            cands.append(tuple(eligible[:i] + eligible[i + 1:]))
        seen_c: set[tuple[int, ...]] = set()
        out = []
        for c in cands:
            key = tuple(id(p) for p in c)
            if key not in seen_c:
                seen_c.add(key)
                out.append(DeclareAttackers(c))
        return out
    if kind == COMBAT_BLOCK:
        defender = state.players[state.pending.player]
        attacker = state.players[state.active]
        return _block_candidates(state.combat_attackers, defender, attacker)
    return []


def _block_candidates(
    attackers: list[_Permanent], defender: _Player, attacker: _Player
) -> list[object]:
    """A bounded set of block plans for search: no blocks, the greedy plan, and all-chump."""
    from mythgauntlet.agents.greedy import greedy_block_assignment

    plans: list[tuple[tuple[int, _Permanent], ...]] = [()]
    greedy = tuple(sorted(greedy_block_assignment(attackers, defender).items()))
    if greedy:
        plans.append(greedy)
    seen: set[tuple] = set()
    out: list[object] = []
    for p in plans:
        key = tuple((i, id(b)) for i, b in p)
        if key not in seen:
            seen.add(key)
            out.append(DeclareBlocks(p))
    return out


# --- apply -------------------------------------------------------------------------------


def apply(state: GameState, action: object) -> None:
    """Apply the chosen action, then set the phase cursor to the next decision/deterministic
    step. `advance()` resumes from there. Mutations mirror the old imperative engine op-for-op.
    """
    from mythgauntlet.sim.tier0 import _can_pay
    from mythgauntlet.sim.tier2 import _card_value, _reactive_reserve

    state.pending = None
    me, opp = state.me_opp()
    kind_phase = state.phase

    if isinstance(action, PlayLand):
        land = action.card
        me.hand.remove(land)
        me.sources.append(
            _Source(land.sim.produced_colors(), ready=not land.sim.fx.enters_tapped)
        )
        _fire_triggers(me, opp, "landfall", _others(state))
        state.land_played = True
        # stay in MAIN
        return

    if isinstance(action, (CastSpell, CastCommander)):
        is_commander = isinstance(action, CastCommander)
        gc = me.commander if is_commander else action.card
        cost = _commander_cost(me.commander, me.commander_casts) if is_commander else gc.card.cost
        payment = _can_pay(me.sources, cost)
        assert payment is not None, "apply() got an unpayable cast"
        value = _card_value(gc, me, opp, state.turn, state.cfg) + (1.0 if is_commander else 0.0)
        for idx in payment:
            me.sources[idx].ready = False
        if is_commander:
            me.commander_in_zone = False
            me.commander_casts += 1
        else:
            me.hand.remove(gc)
        # cast triggers fire on the cast itself, before the counter-war (a countered spell was
        # still cast)
        others = _others(state)
        _fire_triggers(me, opp, "cast_spell", others)
        if gc.card.is_creature:
            _fire_triggers(me, opp, "cast_creature", others)
        if state.multiplayer:  # every opponent's taxer punishes the caster
            for foe in state.opponents_of(state.active):
                _fire_triggers(foe, me, "opponent_casts_spell")
        else:
            _fire_triggers(opp, me, "opponent_casts_spell")
        state.casts_this_main += 1
        if state.multiplayer:
            _resolve(gc, me, opp, is_commander, others)  # reactions 1v1-only -> resolve now
            return
        # 1v1: the spell goes on the stack and the non-active player gets the first
        # COUNTER_WINDOW decision (the counter-war is a searched decision).
        state.pending_spell = (gc, is_commander, value, state.active)
        state.counters_on_stack = 0
        state.reaction_actor = state.other
        state.phase = COUNTER_WINDOW
        return

    if isinstance(action, (CounterSpell, PassReaction, CastRemoval)):
        _apply_reaction(state, action)
        return

    if isinstance(action, Pass):
        if kind_phase == MAIN:
            state.activation_reserve = _reactive_reserve(me)
            state.activations_done = 0
            state.phase = ACTIVATION
        elif kind_phase == ACTIVATION:
            state.phase = "post_main"
        return

    if isinstance(action, Activate):
        _apply_activation(me, opp, action.perm, action.effect)
        state.activations_done += 1
        return

    if isinstance(action, DeclareAttackers):
        _apply_declare_attackers(state, action.attackers)
        return

    if isinstance(action, DeclareBlocks):
        _apply_declare_blocks(state, action.as_dict())
        return

    raise AssertionError(f"unknown action {action!r}")  # pragma: no cover


def _apply_reaction(state: GameState, action: object) -> None:
    """Apply one reaction decision. COUNTER_WINDOW: CounterSpell adds to the LIFO chain and
    passes priority to the other player; PassReaction ends the war and resolves the spell.
    INSTANT_WINDOW: CastRemoval kills the biggest threat and offers another; PassReaction moves
    to combat."""
    from mythgauntlet.sim.tier0 import _can_pay

    if state.phase == COUNTER_WINDOW:
        if isinstance(action, CounterSpell):
            actor = state.players[state.reaction_actor]
            payment = _can_pay(actor.sources, action.card.card.cost)
            assert payment is not None, "apply() got an unpayable counter"
            actor.hand.remove(action.card)
            for idx in payment:
                actor.sources[idx].ready = False
            state.counters_on_stack += 1
            state.reaction_actor = _other_key(state.players, state.reaction_actor)
            # stay in COUNTER_WINDOW: advance queries the next reactor (or resolves)
        else:  # PassReaction
            _resolve_pending_spell(state)
        return

    # INSTANT_WINDOW
    if isinstance(action, CastRemoval):
        reactor, active = state.players[state.reaction_actor], state.players[state.active]
        payment = _can_pay(reactor.sources, action.card.card.cost)
        assert payment is not None, "apply() got an unpayable removal"
        _apply_instant_removal(reactor, active, action.card, payment)
        # stay in INSTANT_WINDOW: advance offers another removal or moves to combat
    else:  # PassReaction
        state.reaction_actor = None
        state.phase = COMBAT_ATTACK


def _apply_activation(me: _Player, opp: _Player, perm: _Permanent, eff: object) -> None:
    """Reproduces one iteration of the old _activation_phase body."""
    from mythgauntlet.sim.tier2 import _spawn_tokens

    paid = 0
    for source in me.sources:
        if paid == eff.cost_mana:
            break
        if source.ready:
            source.ready = False
            paid += 1
    if eff.needs_tap:
        perm.tapped = True
    me.draw(eff.draw)
    if eff.damage_any:
        killable = [c for c in opp.creatures() if c.toughness <= eff.damage_any]
        if killable:
            _kill(opp, max(killable, key=lambda c: c.power), me)
        else:
            opp.life -= eff.damage_any
    opp.life -= eff.damage_face
    me.life += eff.gain_life
    if eff.tokens:
        _spawn_tokens(me, eff.tokens)


def _apply_declare_attackers(state: GameState, declared: tuple[_Permanent, ...]) -> None:
    """Fire attack triggers (subject-scope aware), drop attackers that died, queue blocks.

    Three subject scopes fan out differently (see tier2._attack_subject_scope):
      - ``self``        -- each attacking creature fires its own "whenever this attacks".
      - ``global_each`` -- every permanent's "whenever a creature you control attacks" fires
                           once PER attacking creature (go-wide payoffs scale with the swing).
      - ``global_once`` -- fires once if >=1 attacker (one-or-more / a non-creature's trigger).
    ``n`` is fixed at the declared-attacker count so a self-trigger that kills an attacker
    can't retroactively shrink the global fan-out.
    """
    # Lock the defender BEFORE any attack trigger fires, so the triggers, the block
    # decision and the damage assignment all address the seat that was actually attacked.
    state.combat_defender = state.other
    me, opp = state.combat_me_opp()
    others = _others(state)
    attackers = [a for a in declared if a in me.battlefield]
    attackers = sorted(attackers, key=lambda c: c.power, reverse=True)
    n = len(attackers)
    for atk in attackers:
        _fire_attack_triggers(atk, me, opp, "self", 1, others)
    if n:
        for perm in list(me.battlefield):  # any permanent may hold a global attack trigger
            _fire_attack_triggers(perm, me, opp, "global_each", n, others)
            _fire_attack_triggers(perm, me, opp, "global_once", 1, others)
    attackers = [c for c in attackers if c in me.battlefield]
    state.combat_attackers = attackers
    if attackers:
        state.phase = COMBAT_BLOCK
    else:  # every attacker died to its own trigger; combat is over, release the lock
        state.phase = "end_step"
        state.combat_defender = None


def _apply_declare_blocks(state: GameState, assignment: dict[int, _Permanent]) -> None:
    """Resolve combat damage exactly as the old _combat second half did."""
    me, opp = state.combat_me_opp()  # me = attacker, opp = the seat that WAS attacked
    others = _others(state)  # scales a dying creature's "each opponent" death drain across the pod
    attackers = state.combat_attackers
    unblocked_hitters: list[_Permanent] = []
    for i, atk in enumerate(attackers):
        atk.tapped = True  # attacking taps (no vigilance) -> can't block next turn
        blk = assignment.get(i)
        if blk is None or blk not in opp.battlefield:
            opp.life -= atk.power
            if atk.triggers:
                unblocked_hitters.append(atk)
        else:
            if atk.power >= blk.toughness:
                _kill(opp, blk, me, others)
            if blk.power >= atk.toughness:
                _kill(me, atk, opp, others)
    for atk in unblocked_hitters:
        _fire_perm_triggers(atk, me, opp, "combat_damage_to_player")
    state.combat_attackers = []
    state.combat_defender = None
    state.phase = "end_step"


# --- drivers -----------------------------------------------------------------------------


def _decide_and_apply(state: GameState, agents: dict[str, object]) -> None:
    action = agents[state.pending.player].decide(state)
    apply(state, action)


def play_out(
    deck_a: list[GameCard], cmdr_a: GameCard | None,
    deck_b: list[GameCard], cmdr_b: GameCard | None,
    cfg: object, rng: SeededRng, a_first: bool, agents: dict[str, object],
    combos_a: tuple[frozenset[str], ...] = (),
    combos_b: tuple[frozenset[str], ...] = (),
) -> tuple[str, int, str]:
    """One full game under `agents` (keyed 'a'/'b'). Reproduces _play_game's setup + structure."""
    players: dict[str, _Player] = {}
    for key, deck, cmdr, combos in (
        ("a", deck_a, cmdr_a, combos_a), ("b", deck_b, cmdr_b, combos_b)
    ):
        library = deck[:]
        rng.shuffle(library)
        player = _Player(
            name=key, library=library, life=cfg.start_life, commander=cmdr,
            combos=combos, combo_pieces=frozenset().union(*combos) if combos else frozenset(),
        )
        player.draw(7)
        players[key] = player
    order = ["a", "b"] if a_first else ["b", "a"]
    state = GameState(players=players, order=order, cfg=cfg, active=order[0])

    while not state.terminal:
        advance(state)
        if state.terminal:
            break
        _decide_and_apply(state, agents)
    return state.result


# seat keys for an N-player table ("a".."z"); a pod is 4 (order matters — seat play order).
def _seat_keys(n: int) -> list[str]:
    return [chr(ord("a") + i) for i in range(n)]


def play_table(
    seats: list[tuple[list[GameCard], GameCard | None, tuple[frozenset[str], ...]]],
    cfg: object, rng: SeededRng, agents: dict[str, object],
) -> tuple[str, int, str]:
    """One full N-player (pod) game. `seats` is a list of (deck, commander, combos) in PLAY
    ORDER; seats[0] takes the first turn. Returns (winner_key, turns, reason) — winner is the
    last player standing, or the turn-cap adjudication winner. Reactions/instant windows are
    1v1-only for now; multiplayer combat focus-fires the biggest-threat opponent and effects
    hit that primary opponent (multi-opponent "each" scaling is the next increment).
    """
    keys = _seat_keys(len(seats))
    players: dict[str, _Player] = {}
    for key, (deck, cmdr, combos) in zip(keys, seats, strict=True):
        library = deck[:]
        rng.shuffle(library)
        player = _Player(
            name=key, library=library, life=cfg.start_life, commander=cmdr,
            combos=combos, combo_pieces=frozenset().union(*combos) if combos else frozenset(),
        )
        player.draw(7)
        players[key] = player
    state = GameState(players=players, order=keys, cfg=cfg, active=keys[0])

    while not state.terminal:
        advance(state)
        if state.terminal:
            break
        _decide_and_apply(state, agents)
    return state.result


def _scoped_state(active: _Player, other: _Player, cfg: object, turn: int, phase: str) -> GameState:
    """A GameState scoped to two live players for the in-place compat drivers (main/combat)."""
    return GameState(
        players={"a": active, "b": other}, order=["a", "b"], cfg=cfg,
        turn=turn, pos=(0 if turn > 1 else 1), active="a", phase=phase,
    )


def run_greedy_main_phase(me: _Player, opp: _Player, turn: int, cfg: object) -> None:
    """Drive MAIN + ACTIVATION under the GreedyAgent, mutating me/opp in place (the old
    _main_phase's exact scope: land, casts + counter-war, activations — no combat)."""
    from mythgauntlet.agents.greedy import GreedyAgent

    state = _scoped_state(me, opp, cfg, turn, MAIN)
    state.pos = 0  # first-player position: draws already happened before _main_phase in old code
    agent = GreedyAgent()
    while state.phase in (MAIN, ACTIVATION, COUNTER_WINDOW):  # a MAIN cast opens a counter window
        advance(state)
        if state.pending is None:
            break
        apply(state, agent.decide(state))


def run_greedy_combat(attacker: _Player, defender: _Player, cfg: object | None = None) -> None:
    """Drive COMBAT_ATTACK + COMBAT_BLOCK under the GreedyAgent, in place (old _combat's scope)."""
    from mythgauntlet.agents.greedy import GreedyAgent
    from mythgauntlet.sim.tier2 import DuelConfig

    state = _scoped_state(attacker, defender, cfg or DuelConfig(), 1, COMBAT_ATTACK)
    agent = GreedyAgent()
    while state.phase in (COMBAT_ATTACK, COMBAT_BLOCK):
        advance(state)
        if state.pending is None:
            break
        apply(state, agent.decide(state))
