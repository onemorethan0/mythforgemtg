"""Tier-2 adversarial engine, 1v1 MVP (docs/SIMULATION.md).

Two decks, full zones, combat, and greedy agents — the first tier that produces WIN RATES.
Rung-1 cards (no CCM) run off the flattened EffectVector PlayProfile; CCM cards (rung 2/3)
execute their on-resolution effects through the **interpreter** (`semantics/interpreter.py`)
at resolve time — per effect, not aggregated — so every deck is playable and fidelity rises
with compiler coverage. Structural facts (creature stats, mana abilities, engine draw,
activated/death triggers) still come from the PlayProfile.

Documented simplifications ("battlecruiser fidelity" — each is a future upgrade point):
  - Reactive interaction (stack MVP, 2026-07-13): instant-speed answers now matter. After
    making its primary play a player holds up surplus mana (rather than jamming a second
    spell) for the cheapest instant answer in hand; the non-active player may then counter a
    cast spell (a LIFO counter-war chain; a countered spell is discarded) and may cast that
    held-up instant removal on the active player's board before combat. Sorcery-speed removal
    stays main-phase-only. Because the greedy agent won't durdle its whole turn to hold mana,
    reactions fire opportunistically (when the controller has spare mana). Not modeled:
    deliberate tap-out-avoidance, reactive burn to face, responses to activated
    abilities/combat, split-second, Flash permanents. See docs/SIMULATION.md.
  - Combat: every non-sick creature attacks; the defender makes winning trades and
    chump-blocks only lethal damage. No evasion/keywords (invisible at rung 1-2).
  - Activated abilities ARE executed: after casting, leftover mana is spent greedily on
    repeatable outlets (generic-only payment; tap abilities once/turn, summoning-sick
    creatures can't tap; tapped creatures can't attack or block). Death triggers fire on
    the permanent's own death. Sacrifice-cost abilities and other PlayProfile limits
    still apply (see semantics/profile.py).
  - Event triggers EXECUTE (2026-07-15, docs/SIMULATION.md): CCM permanents' triggered
    abilities fire at their event via the interpreter — cast_spell/cast_creature (on the
    cast itself, before the counter-war, so countered spells still trigger them),
    opponent_casts_spell, attack (an attacking creature fires its own; a non-creature
    permanent's fires once per combat with >=1 attacker), combat_damage_to_player
    (unblocked attackers), landfall, upkeep/draw_step (controller's turn only), end_step.
    A CCM permanent's engine_draw is zeroed here (those draws now fire at the event — no
    double-count); rung-1 cards keep the flat per-turn engine_draw approximation.
  - Commander: command zone, +2 tax per prior cast, returns on death. No commander damage.
  - Wins: life <= 0, drawing from an empty library, or ASSEMBLING A GAME-ENDING COMBO
    (combo piece-sets are data, fetched offline at prep time; see
    data/spellbook.winning_combos): every piece on the battlefield past summoning
    sickness, OR — the cEDH fidelity increment (2026-07-17, docs/SIMULATION.md) — the
    missing pieces IN HAND with their combined mana value within the ready mana at the
    post-main check (instant/sorcery combos like Thoracle/Consultation now fire). At the
    turn cap the higher (life + board power + hand) score is adjudicated.
  - cEDH fidelity increment (2026-07-17): resolved add_mana grants READY TEMPORARY
    sources (spent by further casts the same turn, gone at the controller's next untap);
    search_library tutors a real card (missing combo piece first, else highest impact),
    honoring the CCM what.type/subtype filter. to:hand fetches to hand; to:top/library
    (Vampiric/Mystical/Imperial-Seal class -- previously IGNORED, the dominant cEDH tutor
    kind) fetches to the top of library, drawn next turn. MEASURED LIMIT: this raises combo
    ASSEMBLY but not cEDH win rate -- combos still fire ~turn 13 (draw/mana-limited), too late
    to convert early-race losses; firing them EARLY needs fast-mana density (a later
    increment). See docs/SIMULATION.md for the honest limits of each.

Determinism: one SeededRng stream per game (invariant #1). First player alternates
game-by-game so matchups are fair.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from mythgauntlet.model.card import Card, normalize_name
from mythgauntlet.semantics import tags
from mythgauntlet.semantics.ccm import normalize_colors
from mythgauntlet.semantics.interpreter import ResolvedEffect, interpret_ability
from mythgauntlet.semantics.profile import (
    ActivatedEffect,
    DeathEffect,
    PlayProfile,
    profile_for,
)
from mythgauntlet.semantics.store import SemanticsStore
from mythgauntlet.sim.rng import SeededRng
from mythgauntlet.sim.tier0 import SimCard, _can_pay, _Source

# Target types the engine treats as "a creature-ish thing" for removal.
_REMOVAL_TYPES = {"creature", "permanent", "artifact", "enchantment", "any", "planeswalker"}
_EACH_CAP = 6  # cap on a "for each creature you control" board-scaled amount


@dataclass(frozen=True)
class DuelConfig:
    games: int = 200
    seed: int = 42
    max_turns: int = 30
    start_life: int = 40
    ramp_priority_turns: int = 4
    # Agent level per side (Phase 7). "greedy" (default) reproduces the pre-Phase-7 engine;
    # "mcts" selects the ISMCTS agent. The strength ladder pits different levels head to head.
    agent_a: str = "greedy"
    agent_b: str = "greedy"
    mcts_iterations: int = 0          # search iterations per decision (0 => agent default)
    mcts_determinizations: int = 1    # hidden-info worlds sampled per iteration
    rollout_depth: int = 40           # truncated-rollout ply cap before score() evaluation


@dataclass(frozen=True)
class GameCard:
    """Engine view: card data + rung-1 vector + executable profile."""

    sim: SimCard
    profile: PlayProfile
    # On-resolution CCM abilities (spell_effect + ETB), executed by the interpreter at
    # resolve time. None = rung-1 card (no CCM) -> the flattened-profile path. An empty
    # tuple = a CCM with no resolution effects (e.g. a vanilla creature).
    resolve_abilities: tuple[dict, ...] | None = None
    # Event-triggered CCM abilities as (event, ability) pairs, fired by the engine at the
    # event via the interpreter (see _EVENT_TRIGGERS). None = rung-1 card: the flattened
    # engine_draw approximation applies instead. An empty tuple = a CCM with none.
    trigger_abilities: tuple[tuple[str, dict], ...] | None = None

    @property
    def card(self) -> Card:
        return self.sim.card

    @property
    def name(self) -> str:
        return self.sim.card.name


@dataclass
class _Permanent:
    name: str
    power: int
    toughness: int
    is_creature: bool
    sick: bool = True
    tapped: bool = False
    engine_draw: int = 0
    is_commander: bool = False
    activated: tuple[ActivatedEffect, ...] = ()
    death: DeathEffect | None = None
    triggers: tuple[tuple[str, dict], ...] = ()  # (event, CCM ability) pairs


@dataclass
class _Player:
    name: str
    library: list[GameCard]
    hand: list[GameCard] = field(default_factory=list)
    battlefield: list[_Permanent] = field(default_factory=list)
    sources: list[_Source] = field(default_factory=list)
    life: int = 40
    commander: GameCard | None = None
    commander_in_zone: bool = True
    commander_casts: int = 0
    decked: bool = False
    combos: tuple[frozenset[str], ...] = ()  # game-ending combos (normalized piece names)
    combo_pieces: frozenset[str] = frozenset()  # union, for the agent's assemble nudge

    def draw(self, n: int) -> None:
        for _ in range(n):
            if not self.library:
                self.decked = True
                return
            self.hand.append(self.library.pop())

    def creatures(self) -> list[_Permanent]:
        return [p for p in self.battlefield if p.is_creature]

    def board_power(self) -> int:
        return sum(p.power for p in self.creatures())

    def engine_draws(self) -> int:
        return sum(p.engine_draw for p in self.battlefield)

    def online_names(self) -> set[str]:
        """Normalized names of permanents past summoning sickness (combo-ready)."""
        return {normalize_name(p.name) for p in self.battlefield if not p.sick}

    def combo_ready(self) -> bool:
        """A game-ending combo assembles when every piece is online, or the missing
        pieces are IN HAND and their combined mana value fits the ready mana right now
        (instant/sorcery pieces — the cEDH fidelity increment). Under-counts: the greedy
        agent may have tapped out before this check; a land piece passes at MV 0."""
        if not self.combos:
            return False
        online = self.online_names()
        ready = sum(1 for s in self.sources if s.ready)
        by_name = {normalize_name(gc.name): gc for gc in self.hand}
        for pieces in self.combos:
            need = 0
            assembled = True
            for piece in pieces:
                if piece in online:
                    continue
                gc = by_name.get(piece)
                if gc is None:
                    assembled = False
                    break
                need += gc.card.mana_value
            if assembled and need <= ready:
                return True
        return False

    def score(self) -> float:
        """Adjudication score at the turn cap."""
        return self.life + self.board_power() + 0.5 * len(self.hand)


@dataclass
class DuelResult:
    games: int
    wins_a: int
    wins_b: int
    draws: int
    avg_turns: float
    decked_losses: int
    combo_wins: int = 0  # games decided by an assembled game-ending combo

    @property
    def winrate_a(self) -> float:
        return self.wins_a / self.games if self.games else 0.0


def _resolution_abilities(ccm: dict) -> tuple[dict, ...]:
    """The CCM abilities that fire on resolution (one-shot spell effects + ETB triggers)."""
    out = []
    for ability in ccm.get("abilities") or []:
        if not isinstance(ability, dict):
            continue
        kind = ability.get("kind")
        if kind == "spell_effect":
            out.append(ability)
        elif kind == "triggered":
            trig = ability.get("trigger")
            if isinstance(trig, dict) and trig.get("event") == "etb":
                out.append(ability)
    return tuple(out)


# Trigger events the engine fires at a concrete moment (etb/death are handled elsewhere;
# "other" has no moment to fire at). See docs/SIMULATION.md "Event-trigger execution".
_EVENT_TRIGGERS = frozenset({
    "upkeep", "draw_step", "end_step", "landfall", "cast_creature", "cast_spell",
    "opponent_casts_spell", "attack", "combat_damage_to_player",
})


def _attack_subject_scope(card: Card) -> str:
    """Classify an `attack` trigger's SUBJECT so the engine can fan it out correctly.

    An `{"event": "attack"}` CCM trigger doesn't record WHO attacking fires it, but the
    Comprehensive Rules distinguish three cases with very different game impact. We recover
    the subject from the card's Oracle text + type (a whole-card heuristic — a card with
    several attack triggers shares one verdict; documented in docs/SIMULATION.md):
      - ``self``        -- "Whenever this creature attacks" (fires once, for itself).
      - ``global_each`` -- "Whenever a creature you control attacks" (once PER attacker).
      - ``global_once`` -- "one or more creatures you control attack" / "whenever you attack"
                            / a non-creature's attack trigger (no attack of its own) /
                            "attacks alone" (fires once per combat).
    """
    txt = (card.oracle_text or "").lower()
    if "attacks alone" in txt:
        return "global_once"  # only legal with one attacker; never multiply it
    if "creature you control attacks" in txt:  # "a/another creature you control attacks"
        return "global_each"
    if (
        "creatures you control attack" in txt  # plural: "one or more ... attack"
        or "whenever you attack" in txt
        or "you control attack" in txt
    ):
        return "global_once"
    if not card.is_creature:
        return "global_once"  # a non-creature permanent has no attack of its own
    return "self"


def _event_triggers(ccm: dict, card: Card) -> tuple[tuple[str, dict], ...]:
    """(event, ability) pairs the engine fires while the permanent is on the battlefield.

    Attack abilities are copied with an added ``_attack_scope`` key (self/global_each/
    global_once) so the declare-attackers fan-out knows how many times to fire them; the
    copy leaves the store's shared CCM dict untouched and the extra key is inert to the
    interpreter.
    """
    if card.has_type("Instant") or card.has_type("Sorcery"):
        return ()  # never a permanent -> its triggers have no battlefield to fire from
    out = []
    for ability in ccm.get("abilities") or []:
        if not isinstance(ability, dict) or ability.get("kind") != "triggered":
            continue
        trig = ability.get("trigger")
        event = trig.get("event") if isinstance(trig, dict) else None
        if event not in _EVENT_TRIGGERS:
            continue
        if event == "attack":
            ability = {**ability, "_attack_scope": _attack_subject_scope(card)}
        out.append((event, ability))
    return tuple(out)


def make_game_card(card: Card, store: SemanticsStore | None) -> GameCard:
    ccm = store.lookup(card.name).ccm if store else None
    fx = tags.analyze(card)
    return GameCard(
        sim=SimCard(card=card, fx=fx),
        profile=profile_for(card, ccm, fx=fx),
        resolve_abilities=_resolution_abilities(ccm) if ccm else None,
        trigger_abilities=_event_triggers(ccm, card) if ccm else None,
    )


def build_game_cards(
    cards: list[tuple[Card, int]], store: SemanticsStore | None
) -> list[GameCard]:
    out: list[GameCard] = []
    for card, count in cards:
        out.extend([make_game_card(card, store)] * count)
    return out


def _commander_cost(gc: GameCard, casts: int):
    cost = gc.card.cost
    return replace(cost, generic=cost.generic + 2 * casts) if casts else cost


def _spawn_tokens(player: _Player, tokens: tuple[int, int, int]) -> None:
    count, power, tough = tokens
    for _ in range(count):
        player.battlefield.append(
            _Permanent(name="token", power=power, toughness=max(1, tough), is_creature=True)
        )


def _kill(
    owner: _Player, permanent: _Permanent, opponent: _Player,
    others: tuple[_Player, ...] = (),
) -> None:
    owner.battlefield.remove(permanent)
    if permanent.is_commander:
        owner.commander_in_zone = True  # returns to the command zone (tax already counted)
    death = permanent.death
    if death is not None:  # self-death triggers (aristocrat class)
        owner.draw(death.draw)
        # death.drain models "each opponent loses N"; in a pod it hits ALL of the owner's
        # opponents. `others` are the owner's opponents beyond `opponent`; at the combat /
        # single-target-removal call sites (opponent, *others) == every seat but the owner.
        # Empty in 1v1 -> byte-identical.
        for foe in (opponent, *others):
            foe.life -= death.drain
        owner.life += death.gain_life
        if death.tokens:
            _spawn_tokens(owner, death.tokens)


def _card_value(gc: GameCard, me: _Player, opp: _Player, turn: int, cfg: DuelConfig) -> float:
    """Greedy agent's cast-priority heuristic. Hand-tuned; replaced by learning at L5."""
    p = gc.profile
    value = 2.0 * p.impact
    if gc.card.is_creature:
        value += gc.sim.attack_power + _toughness(gc) / 2
    if p.tokens:
        count, power, tough = p.tokens
        value += count * (power + tough / 2)
    value += 1.0 * len(p.activated) + (1.0 if p.death else 0.0)
    value += 0.8 * len(gc.trigger_abilities or ())  # event-trigger payoffs (cast/attack/...)
    if p.removal and opp.creatures():
        value += max(c.power for c in opp.creatures()) + 1
    if p.wipe:
        value += max(0.0, opp.board_power() - me.board_power())
    if p.damage_face or p.damage_any:
        dmg = p.damage_face + p.damage_any
        value += 100.0 if dmg >= opp.life else dmg * 0.8
    value += 1.2 * p.draw + 0.6 * p.engine_draw * max(0, 10 - turn)
    value += 0.3 * p.gain_life
    if p.ramp_sources or p.fetches_land:
        value += max(0.5, 6.0 - turn) if turn <= cfg.ramp_priority_turns else 0.5
    # Binning a combo piece for nothing is worse than doing nothing at all. Tested BEFORE
    # the combo bonus is added, and against the value the card earns on its own merits
    # (the popularity prior excluded) — so a piece that is also genuine removal or lethal
    # burn can still be cast, while a dedicated piece is kept in hand. The agent reads
    # value <= 0 as "hold it".
    if _combo_piece_hold(gc, me) and (value - 2.0 * p.impact) < _PIECE_HOLD_MAX_INTRINSIC:
        return 0.0
    value += _combo_bonus(gc, me)  # prioritize assembling a game-ending combo
    value += _tutor_bonus(gc, me)  # ... and a tutor that FINISHES one (fetches the last piece)
    return value


def _combo_bonus(gc: GameCard, me: _Player) -> float:
    """Nudge the agent to complete combos: the closer to assembled, the higher."""
    if not me.combo_pieces:
        return 0.0
    name = normalize_name(gc.name)
    if name not in me.combo_pieces:
        return 0.0
    online = me.online_names()
    best = 0.0
    for pieces in me.combos:
        if name in pieces:
            have = len(pieces & online)  # other pieces already down
            best = max(best, 2.5 + 4.0 * have)
    return best


# How much independent, executable value a card must have before the agent is willing to
# BIN a combo piece by casting it. The popularity prior is excluded from this test on
# purpose: a dedicated piece like Demonic Consultation scores ~2.0 from popularity alone
# while doing nothing the engine can execute, and that was enough to get it cast.
_PIECE_HOLD_MAX_INTRINSIC = 3.0


def _combo_piece_hold(gc: GameCard, me: _Player) -> bool:
    """True when casting this card now would throw a combo piece away for nothing.

    A competent player never casts Demonic Consultation without Thassa's Oracle — it is
    card disadvantage that exiles your library. The greedy agent did exactly that, because
    _combo_bonus paid it to cast ANY piece whether or not the combo could finish. Measured
    on cEDH Blue Farm: Demonic Consultation 0.85 casts/game, Tainted Pact 0.82, Brain
    Freeze 0.88 — each deck runs ONE copy, so the first cast removed the wincon from the
    game permanently. 98% of failed combo checks were a missing piece, and the deck could
    not assemble in THIRTY unpressured turns 70% of the time.

    Only instants and sorceries are held. A permanent piece stays on the battlefield and
    counts as assembled, so casting it is real progress.

    There is deliberately NO "unless this cast finishes the combo" exception, because
    `combo_ready` resolves a combo from pieces HELD (online or in hand) plus the mana to
    cast the rest — it is a state, not a sequence of casts. So casting the last piece is
    the one thing that stops the win: the card leaves hand for the graveyard and the
    post-main check then sees it missing. Holding it is both correct Magic and the only
    way the engine can register the kill.
    """
    if not me.combo_pieces:
        return False
    name = normalize_name(gc.name)
    if name not in me.combo_pieces:
        return False
    return gc.card.has_type("Instant") or gc.card.has_type("Sorcery")


def _tutor_bonus(gc: GameCard, me: _Player) -> float:
    """Nudge the agent to cast a TUTOR only when it FINISHES a game-ending combo — i.e. exactly
    one piece is missing, so the fetch completes the win. Tutoring from scratch is a tempo trap
    (measured net-negative), so it earns nothing here. Gated on `tutor` + an incomplete combo, so
    non-combo decks (incl. every golden-master deck) get zero change."""
    if not gc.profile.tutor or not me.combo_pieces:
        return 0.0
    accessible = me.online_names() | {normalize_name(g.name) for g in me.hand}
    for pieces in me.combos:
        if len(pieces) - len(pieces & accessible) == 1:  # one tutor away from lethal
            return 8.0
    return 0.0


def _toughness(gc: GameCard) -> int:
    return gc.sim.toughness_value


def _wipe_all(me: _Player, opp: _Player, exclude: _Permanent | None) -> None:
    for player, other in ((me, opp), (opp, me)):
        for creature in list(player.creatures()):
            if creature is not exclude:
                _kill(player, creature, other)


def _fetch_land(me: _Player) -> None:
    fetched = next((c for c in me.library if c.sim.is_land), None)
    if fetched is not None:
        me.library.remove(fetched)
        me.sources.append(_Source(fetched.sim.produced_colors(), ready=False))


_ANY_COLOR = frozenset("WUBRGC")


def _ritual_mana(me: _Player, amount: int, colors: str | None) -> None:
    """One-shot spell mana (Dark Ritual class): ready TEMPORARY sources, gone at untap.

    An unspecified/"any" color is permissive (WUBRGC) — a documented slight over-count;
    the alternative (colorless) would wrongly fail every colored cost.
    """
    letters = normalize_colors(colors or "")
    produced = frozenset(letters) if letters else _ANY_COLOR
    me.sources.extend(
        _Source(produced, ready=True, temp=True) for _ in range(max(0, amount))
    )


_CARD_TYPES = frozenset({
    "artifact", "creature", "enchantment", "instant", "land", "planeswalker",
    "sorcery", "battle", "kindred", "tribal",
})


def _tutor_matcher(what: dict):
    """A predicate for what a tutor may fetch, honoring the CCM `what.type`/`what.subtype` filter
    (e.g. Mystical -> 'instant or sorcery', Enlightened -> 'artifact or enchantment').

    A disjunction of two card TYPES must be OR-ed, not AND-ed. The schema has one `type`
    slot, so "an instant or sorcery card" compiles as type=instant + subtype=sorcery, and
    AND-ing those asks for a card that is both — which no card in Magic is. Mystical Tutor
    therefore fetched NOTHING, ever. A real subtype (Equipment, Aura, Human) is never also
    a card type, so "the subtype slot holds a card type" is an unambiguous signal that the
    compiler flattened a disjunction; a genuine subtype filter (artifact + Equipment) still
    AND-s correctly. `type` may also arrive as a literal "creature or land".
    """
    wtype = str((what or {}).get("type") or "card").casefold()
    wsub = str((what or {}).get("subtype") or "").casefold()
    type_words = [w.strip() for w in wtype.split(" or ") if w.strip()]
    sub_words = [
        w for w in wsub.replace(",", " ").replace(" or ", " ").split()
        if len(w) > 2 and w not in ("and", "the", "card")
    ]
    # A card type sitting in the subtype slot is a flattened disjunction — move it up.
    disjunct = [w for w in sub_words if w in _CARD_TYPES]
    if disjunct:
        type_words += disjunct
        sub_words = [w for w in sub_words if w not in _CARD_TYPES]
    type_words = [w for w in type_words if w not in ("card", "any", "permanent")]

    def matches(gc: GameCard) -> bool:
        if type_words and not any(gc.card.has_type(w) for w in type_words):
            return False
        if sub_words and not any(gc.card.has_type(w) for w in sub_words):
            return False
        return True

    return matches


def _tutor_pick(me: _Player, what: dict) -> GameCard | None:
    """Choose the library card a tutor fetches: a MISSING combo piece first (matching the filter),
    else the highest-impact matching card. Deterministic; does not mutate. None if nothing fits."""
    if not me.library:
        return None
    matches = _tutor_matcher(what)
    online = me.online_names()
    in_hand = {normalize_name(g.name) for g in me.hand}
    for gc in me.library:  # a piece any combo still needs, not already held
        n = normalize_name(gc.name)
        if n in me.combo_pieces and n not in online and n not in in_hand and matches(gc):
            return gc
    return max((gc for gc in me.library if matches(gc)),
               key=lambda g: g.profile.impact, default=None)


def _tutor_to_hand(me: _Player, what: dict) -> None:
    """Demonic-Tutor class: fetch straight to hand (castable this turn)."""
    gc = _tutor_pick(me, what)
    if gc is not None:
        me.library.remove(gc)
        me.hand.append(gc)


def _tutor_to_top(me: _Player, what: dict) -> None:
    """Vampiric/Mystical/Imperial-Seal class: the fetched card goes on TOP of the library (drawn
    next untap — a one-turn delay vs a to-hand tutor). Same missing-combo-piece-first selection.
    The engine draws from the end of the list, so 'top' = append."""
    gc = _tutor_pick(me, what)
    if gc is not None:
        me.library.remove(gc)
        me.library.append(gc)


def _apply_resolved(
    eff: ResolvedEffect, me: _Player, opp: _Player, just_cast: _Permanent | None,
    others: tuple[_Player, ...] = (),
) -> None:
    """Apply one interpreted CCM resolution effect to the game (battlecruiser fidelity).

    Mirrors the flattened-profile mutations op-for-op, but executed per effect (so every
    token spawns, every removal resolves) instead of aggregated. Ops the engine doesn't model
    (counter_spell -> stack, add_counter/scry/mill/discard) are skipped, matching the
    flattening. Resolved `add_mana` (ritual class) and `search_library to:hand` (tutors)
    ARE executed — the cEDH fidelity increment (docs/SIMULATION.md).

    `opp` is `me`'s PRIMARY opponent; `others` are `me`'s remaining opponents in a pod. Single-
    target effects hit `opp`; **"each opponent"** effects (drains, group-slug, each-creature
    sweeps) scale across `(opp, *others)`. `others` is empty in 1v1 -> byte-identical.
    """
    op, pr = eff.op, eff.params
    each_opp = (opp, *others)

    def _tgt(key: str) -> dict:  # a CCM occasionally emits target/what as a bare string
        v = pr.get(key)
        return v if isinstance(v, dict) else {}
    if op == "draw":
        who = pr.get("who")
        n = max(0, pr.get("count", 1))
        if who == "each_opponent":
            for p in each_opp:
                p.draw(n)
        else:
            (opp if who == "opponent" else me).draw(n)
    elif op in ("destroy", "exile"):
        target = _tgt("target")
        if target.get("controller") == "you":
            return
        if (target.get("type") or "creature") not in _REMOVAL_TYPES:
            return
        if target.get("count") == "all" or target.get("controller") == "each":
            _wipe_all(me, opp, just_cast)
            for other in others:  # a board wipe clears every pod opponent's creatures
                _wipe_all(other, me, None)
        elif opp.creatures():
            _kill(opp, max(opp.creatures(), key=lambda c: c.power), me, others)
    elif op == "deal_damage":
        target = _tgt("target")
        amt = max(0, pr.get("amount", 1))
        if not amt:
            return
        each = target.get("count") == "all" or target.get("controller") == "each"
        to_player = target.get("type") in ("player", "opponent")
        if each and to_player:  # "deals N to each opponent"
            for p in each_opp:
                p.life -= amt
        elif each:  # "deals N to each creature" — every pod player's board
            for player, killer in ((me, opp), *((o, me) for o in each_opp)):
                for c in list(player.creatures()):
                    if c is not just_cast and c.toughness <= amt:
                        _kill(player, c, killer)
        elif to_player:
            opp.life -= amt
        else:
            killable = [c for c in opp.creatures() if c.toughness <= amt]
            if killable:
                _kill(opp, max(killable, key=lambda c: c.power), me, others)
            else:
                opp.life -= amt
    elif op == "create_token":
        _spawn_tokens(me, (max(0, pr.get("count", 1)), pr.get("power", 1), pr.get("toughness", 1)))
    elif op == "gain_life":
        me.life += max(0, pr.get("amount", 1))
    elif op == "lose_life":
        who = pr.get("who", "opponent")
        amt = max(0, pr.get("amount", 1))
        if who in ("each_opponent", "each"):
            for p in each_opp:
                p.life -= amt
        elif who == "opponent":
            opp.life -= amt
    elif op == "search_library":
        what = _tgt("what")
        to = str(pr.get("to", "hand")).lower()
        if what.get("type") == "land" and to == "battlefield":
            _fetch_land(me)
        elif to in ("hand", "your_hand"):  # Demonic Tutor class
            _tutor_to_hand(me, what)
        elif to in ("top", "library", "library_top", "top_of_library", "top_of_your_library"):
            # Vampiric/Mystical/Imperial-Seal class: fetch to top, drawn next turn. Previously a
            # silent no-op -- the dominant cEDH tutor kind, so combos never assembled.
            _tutor_to_top(me, what)
    elif op == "add_mana":
        _ritual_mana(me, pr.get("amount", 1), pr.get("colors"))


class _EngineResolver:
    """Board-aware resolver for the interpreter: resolves CCM amounts against live state.

    "each" (as in "for each creature you control") scales to the caster's creature count,
    capped. "X" resolves from live state ONLY when the effect carries an `x_basis` (CCM
    prompt v8+) naming a board-derived count the engine actually tracks; cost-side bases
    (mana_paid, life_paid) and player choices stay at the modest default (1) — resolving
    those from live state would be a guess, not a measurement. Without a basis, X stays
    at the default: the CCM store shows bare X is overwhelmingly a COST or CHOSEN amount.
    """

    def __init__(self, me: _Player):
        self._me = me

    def amount(self, raw: object, op: str, param: str, effect: dict | None = None) -> int:
        if isinstance(raw, bool):
            return 1
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str):
            v = raw.strip().lower()
            if v == "-x":
                return -1
            if v == "each":
                return max(1, min(len(self._me.creatures()), _EACH_CAP))
            if v in ("x", "y") and isinstance(effect, dict):
                basis = str(effect.get("x_basis") or "").strip().lower()
                live = self._x_from_basis(basis)
                if live is not None:
                    return max(1, min(live, _EACH_CAP))
        return 1  # bare X/'all'/'half'/... — chosen/cost/ambiguous, keep the modest default

    def _x_from_basis(self, basis: str) -> int | None:
        """Live-state X for the board-derived bases the engine tracks; None otherwise.

        lands_you_control maps to the player's mana sources (lands + rocks/dorks merged at
        this fidelity — a documented over-count, still far closer than the default 1).
        """
        me = self._me
        if basis == "creatures_you_control":
            return len(me.creatures())
        if basis == "permanents_you_control":
            return len(me.battlefield)
        if basis == "cards_in_hand":
            return len(me.hand)
        if basis == "lands_you_control":
            return len(me.sources)
        return None

    def condition_holds(self, condition: str, effect: dict) -> bool:
        return True  # conditions are free-text; assume they hold (as the flattening did)


def _fire_perm_triggers(
    perm: _Permanent, controller: _Player, opp: _Player, event: str,
    others: tuple[_Player, ...] = (),
) -> None:
    """Fire one permanent's triggers matching `event` through the interpreter.

    Fires even if the permanent has left the battlefield since the event (a triggered
    ability resolves regardless of its source dying — and _apply_resolved's kill paths only
    ever act on live battlefield state, so this is safe). `others` = the controller's extra
    pod opponents, so an "each opponent" trigger payoff scales (empty in 1v1).
    """
    if not perm.triggers:
        return
    resolver = _EngineResolver(controller)
    for ev, ability in perm.triggers:
        if ev != event:
            continue
        for eff in interpret_ability(ability, resolver):
            _apply_resolved(eff, controller, opp, perm, others)


def _fire_attack_triggers(
    perm: _Permanent, controller: _Player, opp: _Player, scope: str, times: int,
    others: tuple[_Player, ...] = (),
) -> None:
    """Fire `perm`'s attack triggers whose subject-scope matches `scope`, `times` times.

    The declare-attackers step routes here so a "whenever a creature you control attacks"
    payoff (scope ``global_each``) fans out once per attacking creature, while a self- or
    once-scope trigger fires a single time (see `_attack_subject_scope`). Missing tag ->
    ``self`` (rung-1/hand-built perms never carry attack CCM triggers anyway). `others` scales
    an "each opponent" attack payoff across the pod (empty in 1v1).
    """
    if not perm.triggers:
        return
    resolver = _EngineResolver(controller)
    for ev, ability in perm.triggers:
        if ev != "attack" or ability.get("_attack_scope", "self") != scope:
            continue
        for _ in range(times):
            for eff in interpret_ability(ability, resolver):
                _apply_resolved(eff, controller, opp, perm, others)


def _fire_triggers(
    controller: _Player, opp: _Player, event: str, others: tuple[_Player, ...] = (),
) -> None:
    """Fire every battlefield trigger of `controller` matching `event` (snapshot order)."""
    for perm in list(controller.battlefield):
        _fire_perm_triggers(perm, controller, opp, event, others)


def _resolve(
    gc: GameCard, me: _Player, opp: _Player, is_commander: bool,
    others: tuple[_Player, ...] = (),
) -> None:
    p = gc.profile
    card = gc.card
    is_permanent_type = not (card.has_type("Instant") or card.has_type("Sorcery"))

    # A CCM permanent's engine_draw came entirely from the periodic triggers the engine now
    # EXECUTES at their event — zero it here so draw triggers don't count twice. Rung-1
    # cards (trigger_abilities is None) keep the flat per-turn approximation.
    triggers = gc.trigger_abilities or ()
    engine_draw = p.engine_draw if gc.trigger_abilities is None else 0

    just_cast: _Permanent | None = None
    if card.is_creature:
        just_cast = _Permanent(
            name=card.name, power=gc.sim.attack_power, toughness=max(1, _toughness(gc)),
            is_creature=True, engine_draw=engine_draw, is_commander=is_commander,
            activated=p.activated, death=p.death, triggers=triggers,
        )
        me.battlefield.append(just_cast)
    elif is_permanent_type:
        me.battlefield.append(
            _Permanent(
                name=card.name, power=0, toughness=0, is_creature=False,
                sick=False, engine_draw=engine_draw, is_commander=is_commander,
                activated=p.activated, death=p.death, triggers=triggers,
            )
        )

    for _ in range(p.ramp_sources):  # persistent mana (from mana abilities) — structural
        me.sources.append(_Source(gc.sim.produced_colors(), ready=False))

    if gc.resolve_abilities is not None:
        # CCM path: execute each resolution effect through the interpreter, with a board-aware
        # resolver ("for each creature" scales to the caster's board; X stays default — see
        # _EngineResolver). Effects fire per-effect, not aggregated.
        resolver = _EngineResolver(me)
        for ability in gc.resolve_abilities:
            for eff in interpret_ability(ability, resolver):
                _apply_resolved(eff, me, opp, just_cast, others)
        return

    # Rung-1 (no CCM) path: the flattened EffectVector profile, unchanged.
    if p.fetches_land:
        _fetch_land(me)
    if p.wipe:
        # an ETB-wipe creature doesn't destroy itself (it resolves, then the wipe fires)
        _wipe_all(me, opp, just_cast)
    for _ in range(p.removal):
        targets = opp.creatures()
        if not targets:
            break
        _kill(opp, max(targets, key=lambda c: c.power), me)

    dmg = p.damage_any
    if dmg:
        killable = [c for c in opp.creatures() if c.toughness <= dmg]
        if killable:
            _kill(opp, max(killable, key=lambda c: c.power), me)
        else:
            opp.life -= dmg
    opp.life -= p.damage_face
    me.life += p.gain_life

    if p.tokens:
        _spawn_tokens(me, p.tokens)

    me.draw(p.draw)


# --- Reactive interaction (stack MVP; see docs/SIMULATION.md) ---------------------------

_COUNTER_MIN_VALUE = 5.0  # only spells at least this valuable are worth a counter
_MAX_RESERVE = 4  # cap on mana a player holds up for instant-speed answers
_TAP_OUT_VALUE = 50.0  # a play this good (near-lethal) is worth spending reserved mana on


def _instant_answer(gc: GameCard) -> bool:
    """Holds up / reacts: an instant that counters or removes."""
    p = gc.profile
    return p.is_instant and (p.counter or p.removal > 0 or p.damage_any > 0)


def _reactive_reserve(player: _Player) -> int:
    """Mana the greedy agent keeps untapped to react: the cheapest instant answer it holds."""
    costs = [gc.card.mana_value for gc in player.hand if _instant_answer(gc)]
    return min(min(costs), _MAX_RESERVE) if costs else 0


def _ready_count(player: _Player) -> int:
    return sum(1 for s in player.sources if s.ready)


def _find_counter(player: _Player) -> tuple[GameCard, list[int]] | None:
    """Cheapest counterspell in hand this player can pay for from ready sources."""
    best: tuple[GameCard, list[int], int] | None = None
    for gc in player.hand:
        if not (gc.profile.counter and gc.profile.is_instant):
            continue
        payment = _can_pay(player.sources, gc.card.cost)
        if payment is None:
            continue
        mv = gc.card.mana_value
        if best is None or mv < best[2]:
            best = (gc, payment, mv)
    return (best[0], best[1]) if best else None


def _counter_chain(
    caster: _Player, responder: _Player, spell_value: float
) -> bool:
    """Resolve a counter-war over a just-cast spell. Returns True if the spell is countered.

    Both sides may keep countering (alternating priority) while the original spell is worth
    fighting over and they have a payable counter. Resolves LIFO: the spell is countered iff
    an odd number of counters end up on the chain (each counter negates the one below it).
    """
    if spell_value < _COUNTER_MIN_VALUE:
        return False
    counters = 0
    actor = responder  # the non-active player gets priority first
    while True:
        found = _find_counter(actor)
        if found is None:
            break
        gc, payment = found
        actor.hand.remove(gc)
        for idx in payment:
            actor.sources[idx].ready = False
        counters += 1
        actor = caster if actor is responder else responder
    return counters % 2 == 1


def _instant_target(active: _Player) -> _Permanent | None:
    """The creature a reactive removal spell would answer: the active player's biggest, if it's
    worth an answer (power >= 1). Shared by the automated window and the searched decision."""
    targets = active.creatures()
    if not targets:
        return None
    biggest = max(targets, key=lambda c: c.power)
    return biggest if biggest.power >= 1 else None


def _find_instant_removal(
    reactor: _Player, biggest: _Permanent
) -> tuple[GameCard, list[int]] | None:
    """The first payable instant in `reactor`'s hand that would kill `biggest` (hand order;
    the old window's `biggest.power > best` tie-break kept the first, since the target is
    fixed). Shared by `_instant_window` and the searched instant-removal decision."""
    for gc in reactor.hand:
        p = gc.profile
        if not p.is_instant:
            continue
        if not (p.removal > 0 or (p.damage_any > 0 and biggest.toughness <= p.damage_any)):
            continue
        payment = _can_pay(reactor.sources, gc.card.cost)
        if payment is not None:
            return gc, payment
    return None


def _apply_instant_removal(
    reactor: _Player, active: _Player, gc: GameCard, payment: list[int]
) -> None:
    """Cast one instant-removal spell: pay, then kill the biggest creature(s) it hits."""
    reactor.hand.remove(gc)
    for idx in payment:
        reactor.sources[idx].ready = False
    hits = gc.profile.removal or 1
    for _ in range(hits):
        live = active.creatures()
        if not live:
            break
        _kill(active, max(live, key=lambda c: c.power), reactor)


def _instant_window(reactor: _Player, active: _Player) -> None:
    """The non-active player casts held-up instant removal on the active player's board."""
    while True:
        biggest = _instant_target(active)
        if biggest is None:
            return
        found = _find_instant_removal(reactor, biggest)
        if found is None:
            return
        _apply_instant_removal(reactor, active, found[0], found[1])


def _main_phase(me: _Player, opp: _Player, turn: int, cfg: DuelConfig) -> None:
    """Compat shim: run the greedy main phase (land + casts + counter-war + activations) through
    the action-based engine, in place. The engine (sim/game.py) is the single implementation of
    the rules now; this preserves the old call surface for the white-box tests."""
    from mythgauntlet.sim.game import run_greedy_main_phase

    run_greedy_main_phase(me, opp, turn, cfg)


def _activation_value(eff: ActivatedEffect, opp: _Player) -> float:
    value = 1.4 * eff.draw + 0.3 * eff.gain_life
    if eff.tokens:
        count, power, tough = eff.tokens
        value += count * (power + tough / 2)
    dmg = eff.damage_face + eff.damage_any
    if dmg:
        value += 100.0 if dmg >= opp.life else dmg * 0.9
    return value


def _combat(attacker: _Player, defender: _Player) -> None:
    """Compat shim: run one greedy combat (declare attackers + blocks + damage) through the
    action-based engine, in place. The engine (sim/game.py) owns the combat rules now."""
    from mythgauntlet.sim.game import run_greedy_combat

    run_greedy_combat(attacker, defender)


@dataclass(frozen=True)
class PreparedDeck:
    """A deck converted to GameCards once, reusable across many duels (matrix runs)."""

    name: str
    cards: list[GameCard]
    commander: GameCard | None
    combos: tuple[frozenset[str], ...] = ()  # game-ending combos (see spellbook.winning_combos)


def prepare_deck(
    name: str, cards: list[tuple[Card, int]], commander: Card | None,
    store: SemanticsStore | None,
    combos: tuple[frozenset[str], ...] = (),
) -> PreparedDeck:
    return PreparedDeck(
        name=name,
        cards=build_game_cards(cards, store),
        commander=make_game_card(commander, store) if commander else None,
        combos=tuple(combos),
    )


def duel_prepared(a: PreparedDeck, b: PreparedDeck, cfg: DuelConfig) -> DuelResult:
    from mythgauntlet.agents import make_agent
    from mythgauntlet.sim.game import play_out

    root = SeededRng(cfg.seed)
    wins = {"a": 0, "b": 0, "draw": 0}
    turns_total = 0
    decked = combo_wins = 0
    for i in range(cfg.games):
        game_rng = root.spawn(i)  # drives the deck shuffle (spawn() below can't disturb it)
        agents = {
            "a": make_agent(cfg.agent_a, cfg, "a", game_rng.spawn(1)),
            "b": make_agent(cfg.agent_b, cfg, "b", game_rng.spawn(2)),
        }
        winner, turns, reason = play_out(
            a.cards, a.commander, b.cards, b.commander, cfg, game_rng,
            a_first=(i % 2 == 0), agents=agents, combos_a=a.combos, combos_b=b.combos,
        )
        wins[winner] += 1
        turns_total += turns
        decked += 1 if reason == "decked" else 0
        combo_wins += 1 if reason == "combo" else 0
    return DuelResult(
        games=cfg.games, wins_a=wins["a"], wins_b=wins["b"], draws=wins["draw"],
        avg_turns=turns_total / cfg.games if cfg.games else 0.0, decked_losses=decked,
        combo_wins=combo_wins,
    )


def duel(
    cards_a: list[tuple[Card, int]], commander_a: Card | None,
    cards_b: list[tuple[Card, int]], commander_b: Card | None,
    cfg: DuelConfig, store: SemanticsStore | None = None,
    combos_a: tuple[frozenset[str], ...] = (),
    combos_b: tuple[frozenset[str], ...] = (),
) -> DuelResult:
    return duel_prepared(
        prepare_deck("a", cards_a, commander_a, store, combos_a),
        prepare_deck("b", cards_b, commander_b, store, combos_b),
        cfg,
    )
