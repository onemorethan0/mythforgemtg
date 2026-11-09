"""Tier-0 goldfish consistency simulator (docs/SIMULATION.md).

One player, no opponent. Measures the statistical skeleton of a deck: mulligans, land
drops, color access, mana development, and how efficiently the curve deploys.

Documented simplifications (T0 is built to be fast, deterministic, and honest — not complete):
  - Haste and activated abilities are ignored. Commander tax only arises after a Tier-1
    board wipe sends the commander back to the command zone (the clean goldfish casts it once).
  - Rocks/dorks/fetched lands come in "asleep" and produce from the next untap onward.
  - Land-fetch spells pull a land out of the library (thinning) and add a source next turn.
  - One-shot draws resolve immediately; triggered engines draw a flat engine_draw per turn
    starting the turn after they resolve (trigger conditions not evaluated).
  - X spells are cast for X=0. Every source produces exactly one mana.
  - Casting order is a fixed greedy policy: ramp early, then commander, then draw,
    then highest-impact castable spell.
  - The goldfish clock: creatures attack a single non-blocking opponent (goldfish_life,
    default 40) starting the turn after they resolve; kill_turn is when cumulative combat
    damage crosses that threshold. Noncombat damage comes only from scaling burn and the
    magecraft / cast-damage payoffs, each counting the casts its own trigger names.
  - Poison (CR 704.5c): a creature that prints infect, or the commander while an infect Aura
    is on it, deals its damage as poison counters; toxic adds poison on top. Ten kill.
    Proliferate, equipment that grants infect and one-shot "gains infect" are not modeled.
  - Self-referential cost reduction (`fx.self_reduction_per_creature`, "this spell costs
    {N} less for each creature on the battlefield/you control" — Blasphemous Act, Affinity
    for creatures) IS modeled against T0's own live creature count (`_effective_cost`),
    since leaving it unmodeled means gating castability on the full printed cost, which
    silently turns a card a real pilot casts for 2-4 mana into one T0 almost never casts at
    all. Only THIS one board-state signal (creatures) is wired, because T0 tracks it
    already; a reduction keyed on artifacts, graveyard contents, or anything else T0 does
    not track stays unmodeled and the card is judged by its full printed cost, honestly.

All randomness flows through SeededRng (invariant #1). No card names appear here
(invariant #2): behavior comes exclusively from the semantics layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from functools import lru_cache

from mythgauntlet.model.card import Card
from mythgauntlet.semantics import tags
from mythgauntlet.sim import combat_rules
from mythgauntlet.semantics.model import EffectVector
from mythgauntlet.sim.rng import SeededRng

# User-facing default goldfish horizon for `analyze`/`advise`. Casual (Bracket 1-3) decks
# routinely land their clock turns 10-14; an 8-turn goldfish can't see it, so Speed and
# Ceiling read ~0 and the deck is mislabeled toward Exhibition (measured on the labeled corpus
# 2026-07-22: 8->12 turns lifted B1-3 bracket agreement 5/10 -> 8/10). 12 matches typical
# casual game length; the SimConfig dataclass default stays 8 for unit tests / internal callers.
DEFAULT_ANALYZE_TURNS = 12


# CR 704.5a: combat damage from one commander that loses the game.
COMMANDER_DAMAGE_LETHAL = 21
# CR 704.5c: ten or more poison counters lose the game.
POISON_LETHAL = 10


def _rules_lines(oracle_text: str) -> list[str]:
    """The card's own lines, reminder text stripped, lower-cased."""
    return [re.sub(r"\([^)]*\)", "", ln).strip().lower() for ln in (oracle_text or "").splitlines()]


_KEYWORD_LINE_INFECT = re.compile(r"(?:[a-z' ]+, )*infect(?:, [a-z' ]+)*")
_TOXIC = re.compile(r"(?:^|, )toxic (\d+)(?:,|$)")


@lru_cache(maxsize=4096)
def _has_own_infect(oracle_text: str) -> bool:
    """Infect PRINTED on a keyword line of the card's own ("Flying, infect"). Scryfall's
    `keywords` lists every keyword the text MENTIONS, so it is not used: Vector Asp gains
    infect only for {B}, Viridian Betrayers only while an opponent is poisoned."""
    return any(_KEYWORD_LINE_INFECT.fullmatch(ln) for ln in _rules_lines(oracle_text))


@lru_cache(maxsize=4096)
def _toxic_amount(oracle_text: str) -> int:
    """Toxic N on a keyword line (CR 702.180: combat damage to a player also gives N poison)."""
    total = 0
    for ln in _rules_lines(oracle_text):
        for m in _TOXIC.finditer(ln):
            total += int(m.group(1))
    return total


@lru_cache(maxsize=4096)
def _cast_filter(oracle_text: str) -> tuple[bool, int]:
    """Which casts a cast-damage payoff counts: (noncreature, min_mana_value). Magecraft and
    "whenever you cast an instant or sorcery spell" (Guttersnipe) count instants and sorceries
    -- the default; "whenever you cast a noncreature spell" (Firebrand Archer) counts every
    noncreature spell, artifacts and enchantments too, and "with mana value 3 or greater"
    (Y'shtola, Night's Blessed) drops the cheap ones. Reading every payoff as instant/sorcery
    missed a third of a Y'shtola deck's triggers and counted cheap instants she ignores."""
    for sentence in re.split(r"[.\n]", (oracle_text or "").lower()):
        m = re.search(r"whenever you cast ([^.]{0,60}?)spells?", sentence)
        if not m or "damage" not in sentence:
            continue
        clause = m.group(1)
        if "noncreature" not in clause:
            break
        mv = re.search(r"mana value (\d+) or greater", sentence)
        return True, int(mv.group(1)) if mv else 0
    return False, 0


def _counts_for(sc: "SimCard", flt: tuple[bool, int]) -> bool:
    noncreature, min_mv = flt
    if noncreature:
        return not sc.card.is_creature and not sc.is_land and sc.mana_value >= min_mv
    return sc.card.has_type("Instant") or sc.card.has_type("Sorcery")


_CARD_TYPE_WORDS = frozenset({"artifact", "creature", "enchantment", "instant", "sorcery",
                              "planeswalker", "battle", "aura", "equipment"})
_TUTOR_RE = re.compile(
    r"search your library for (?:a|an) ((?:[a-z]+ )*?)card(?P<rest> with [^,.]*?)?(?=,|\.| and |$)")
_TUTOR_MV_RE = re.compile(r" with mana value (\d+)(?: or (less|greater))?")


@dataclass(frozen=True)
class _TutorSpec:
    types: tuple[str, ...]      # OR-ed card types / Aura / Equipment; () = any nonland card
    max_mv: int | None
    min_mv: int | None
    dest: str                   # "hand" | "top" | "battlefield"

    def matches(self, sc: "SimCard") -> bool:
        if sc.is_land:
            return False
        if self.types and not any(sc.card.has_type(t) for t in self.types):
            return False
        if self.max_mv is not None and sc.mana_value > self.max_mv:
            return False
        return self.min_mv is None or sc.mana_value >= self.min_mv


@lru_cache(maxsize=4096)
def _tutor_spec(type_line: str, oracle_text: str) -> _TutorSpec | None:
    """What a tutor fetches and where it puts it, read strictly from its own text; anything
    this cannot read exactly fetches NOTHING (the honest under-count, as before tutors ran):
      - a spell's own effect, or a permanent's "when ... enters" trigger. An activated ability
        (Planar Bridge) or a repeating trigger is not a one-shot the goldfish can time, and
        transmute's search lives in reminder text, which is stripped;
      - ONE card ("a"/"an"), filtered by card types (OR-ed: "artifact or enchantment") and a
        "with mana value N or less/greater"; a colour, a name, "the same name", X, or two
        cards (Intuition, Gifts) is not read;
      - no additional cost (Diabolic Intent's sacrifice), no random discard (Gamble);
      - lands are never fetched here (land tutors are ramp, read elsewhere)."""
    is_spell = "instant" in (type_line or "").lower() or "sorcery" in (type_line or "").lower()
    text_all = " ".join(_rules_lines(oracle_text))
    if "as an additional cost" in text_all or "at random" in text_all:
        return None
    for line in _rules_lines(oracle_text):
        idx = line.find("search your library for ")
        if idx < 0:
            continue
        prefix = line[:idx]
        if ":" in prefix:
            continue                                    # an activated ability
        if is_spell:
            if re.search(r"\b(?:whenever|when|at the beginning)\b", prefix):
                continue
        elif not re.match(r"when [^,]*\benters\b", prefix):
            continue                                    # permanents: ETB only
        m = _TUTOR_RE.match(line, idx)
        if m is None:
            return None
        words = m.group(1).split()
        types = tuple(w for w in words if w not in ("or", "and"))
        if any(w not in _CARD_TYPE_WORDS for w in types):
            return None                                 # a colour, "basic land", a subtype ...
        max_mv = min_mv = None
        if m.group("rest"):
            mv = _TUTOR_MV_RE.fullmatch(m.group("rest"))
            if mv is None:
                return None
            n = int(mv.group(1))
            if mv.group(2) != "greater":
                max_mv = n
            if mv.group(2) != "less":
                min_mv = n
        after = line[m.end():]
        if "into your hand" in after:
            dest = "hand"
        elif "onto the battlefield" in after:
            dest = "battlefield"
        elif "on top" in after:
            dest = "top"
        else:
            return None
        return _TutorSpec(types, max_mv, min_mv, dest)
    return None


@dataclass(frozen=True)
class _InfectAura:
    upkeep_counter: bool    # Glistening Oil: a -1/-1 counter on the creature every upkeep
    returns_to_hand: bool   # ... and it comes back to hand when it goes to the graveyard


@lru_cache(maxsize=4096)
def _infect_aura(type_line: str, oracle_text: str) -> _InfectAura | None:
    """An Aura whose whole effect on its creature is "Enchanted creature has infect."
    (Phyresis, Glistening Oil). tier0 attaches it only to the COMMANDER -- the creature the deck
    is built to make infect -- so a control-stealing one (Corrupted Conscience: it enchants an
    opponent's creature) is excluded. Equipment that grants infect (Grafted Exoskeleton) also
    needs its equip cost paid and is not modeled: the honest under-count."""
    if "aura" not in (type_line or "").lower():
        return None
    lines = _rules_lines(oracle_text)
    if "enchanted creature has infect." not in lines or "you control enchanted creature." in lines:
        return None
    text = " ".join(lines)
    return _InfectAura(
        upkeep_counter=bool(re.search(
            r"at the beginning of your upkeep, put a -1/-1 counter on enchanted creature", text)),
        returns_to_hand=bool(re.search(
            r"when (?:this aura|[^.]+) is put into a graveyard from the battlefield, return "
            r"(?:it|this aura|[^.]+) to its owner's hand", text)),
    )


@dataclass(frozen=True)
class SimConfig:
    turns: int = 8
    runs: int = 1000
    seed: int = 42
    draw_on_first_turn: bool = True  # multiplayer rule (Commander); False for 1v1 on the play
    free_first_mulligan: bool = True  # Commander house rule / official multiplayer rule
    ramp_priority_turns: int = 4  # cast ramp before other spells through this turn
    goldfish_life: int = 40  # single-opponent goldfish clock
    mulligan_min_lands: int = 2  # keep a 7/6-card hand only with lands in [min, max]
    mulligan_max_lands: int = 5


@lru_cache(maxsize=4096)
def _anthems_in_text(oracle_text: str) -> tuple[tuple[int, bool], ...]:
    """Flat POWER anthems an oracle text prints on a line of their own: ((power, others), ...).

    Rung-1 and CCM-free like the rest of tier0, so it reads the card's own lines with the same
    strict, unconditional parser the tier-2 sim uses (`compiler.parse_anthem`). Only a bonus to
    YOUR creatures counts: goldfish has no opposing board to shrink, tokens are not tracked apart
    from other creatures here so a 'nontoken' anthem is skipped (the honest under-count), and a
    modal bullet or ability-word line never matches because the parser anchors on the subject."""
    from mythgauntlet.semantics.compiler import parse_anthem

    out: list[tuple[int, bool]] = []
    for line in (oracle_text or "").splitlines():
        line = re.sub(r"\([^)]*\)", "", line).strip()
        a = parse_anthem(line)
        if a and a["affects"] == "you" and not a["nontoken"] and a["power"] > 0:
            out.append((a["power"], a["others"]))
    return tuple(out)


@dataclass(frozen=True)
class SimCard:
    """Engine-facing view of a card: data + rung-1 semantics, precomputed once per deck."""

    card: Card
    fx: EffectVector

    @property
    def is_land(self) -> bool:
        return self.card.is_land

    @property
    def mana_value(self) -> int:
        return self.card.mana_value

    def produced_colors(self) -> frozenset[str]:
        produced = frozenset(p for p in self.card.produced_mana if p in "WUBRGC")
        if produced:
            return produced
        if self.card.color_identity:
            return frozenset(self.card.color_identity)
        return frozenset(("C",))

    @property
    def attack_power(self) -> int:
        """Damage this creature deals attacking an empty board. A printed double striker
        deals its power twice (CR 702.4b) -- the tier-2 combat already does (Phase B6), and
        the goldfish clock under-counted it as single damage. A creature with defender deals
        none (CR 702.3b): tier0 used to swing with it."""
        return combat_rules.attack_power(self.card, None)

    @property
    def anthems(self) -> tuple[tuple[int, bool], ...]:
        """Static power anthems this PERMANENT provides (never an instant or sorcery)."""
        if self.card.has_type("Instant") or self.card.has_type("Sorcery"):
            return ()
        return _anthems_in_text(self.card.oracle_text or "")

    def attack_power_under(self, rule: combat_rules.CombatRule | None) -> int:
        """`attack_power` while the commander's combat rule applies (see combat_rules)."""
        return combat_rules.attack_power(self.card, rule)

    @property
    def toughness_value(self) -> int:
        return _stat_value(self.card.toughness)


def _stat_value(stat: str | int | None) -> int:
    """Numeric power/toughness; '*', '1+*' etc. count 0 at rung 1."""
    try:
        return max(0, int(stat or 0))
    except ValueError:
        return 0


@dataclass
class _Source:
    colors: frozenset[str]
    ready: bool = True
    from_creature: bool = False  # mana dork — dies to a board wipe (Tier-1 disruption)
    temp: bool = False  # ritual mana (T2): expires at the controller's next untap step
    from_commander: bool = False  # the commander's own mana ability (survives with it)


@dataclass
class RunStats:
    mulligans: int = 0
    kept_hand_size: int = 7
    land_drops: list[bool] = field(default_factory=list)  # index 0 = turn 1
    sources_by_turn: list[int] = field(default_factory=list)
    mana_available_by_turn: list[int] = field(default_factory=list)
    mana_spent_by_turn: list[int] = field(default_factory=list)
    spells_cast: int = 0
    commander_turn: int | None = None
    dead_cards: int = 0  # nonland cards still in hand at horizon
    cards_drawn: int = 0
    damage_by_turn: list[int] = field(default_factory=list)  # cumulative goldfish damage
    kill_turn: int | None = None  # turn cumulative damage reached cfg.goldfish_life
    final_board_power: int = 0  # attacking power on board at the horizon
    final_board_creatures: int = 0  # able-to-attack creatures at the horizon (go-wide proxy)
    # established (not-summoning-sick) board just before this turn's combat, one entry per
    # turn — feeds sim/clock.py's per-run overrun detection (final_board_* is just the last
    # entry of these, kept for callers that only want the horizon snapshot).
    board_power_by_turn: list[int] = field(default_factory=list)
    board_creatures_by_turn: list[int] = field(default_factory=list)
    # Per-card telemetry (B30, docs/SPEC_deck_scouting_report.md): card name -> the turn it was
    # FIRST seen in hand (0 = the kept opening hand) / first left the hand to be played (a land
    # drop, a cast, or a creature cheated in). Recorded only; nothing in the game reads it, and
    # it draws no randomness, so every other figure is byte-identical with or without it.
    seen_turn: dict[str, int] = field(default_factory=dict)
    played_turn: dict[str, int] = field(default_factory=dict)
    # Nonland cards still in hand at the horizon that the deck's FULL final mana could have
    # paid by amount but not by colour (B31): "stuck because of its pips", not "too costly".
    stranded_by_colour: set[str] = field(default_factory=set)
    # ... and those the final mana could not pay even by AMOUNT ("too costly"). A stranded card
    # in neither set was castable at the end: the greedy policy always had something it ranked
    # higher, which in an unopposed game is where removal and wipes end up.
    stranded_by_cost: set[str] = field(default_factory=set)
    # Kill-method attribution (B34): every point of goldfish damage credited to the card that
    # dealt it and to a source class -- "combat" (creatures and the anthems pumping them),
    # "commander" (the commander's own combat damage), "burn" (scaling burn, magecraft and
    # cast-damage engines). Recorded only; the parallel bookkeeping is pinned by a test to sum
    # to the same damage the game counted. `kill_sources` is the class split AT the kill turn;
    # `kill_method` is set here for a damage kill and overwritten by apply_nut_kills for a
    # storm or alpha-strike kill.
    damage_by_card: dict[str, int] = field(default_factory=dict)
    damage_by_source: dict[str, int] = field(default_factory=dict)
    kill_sources: dict[str, int] = field(default_factory=dict)
    kill_method: str | None = None
    # First turn the commander's own cumulative combat damage reached 21 (CR 704.5a lethal in
    # a real game). tier0 does not apply that rule; this records how often it would matter.
    commander_lethal_turn: int | None = None
    # Poison (CR 704.5c): damage from a source with infect gives poison counters INSTEAD of
    # life loss (CR 702.90b), toxic adds them on top. Kept apart from the life damage above so
    # those sums stay exact; a poison kill sets kill_method "poison". Cumulative, per turn.
    poison_by_turn: list[int] = field(default_factory=list)
    poison_by_card: dict[str, int] = field(default_factory=dict)


def build_sim_cards(cards: list[tuple[Card, int]]) -> list[SimCard]:
    out: list[SimCard] = []
    for card, count in cards:
        sc = SimCard(card=card, fx=tags.analyze(card))
        out.extend([sc] * count)
    return out


def _can_pay(sources: list[_Source], cost) -> list[int] | None:
    """Exact pip assignment via Kuhn's augmenting-path bipartite matching.

    Returns indices of sources to tap, or None if unpayable. Optimal for pip
    satisfiability (a greedy assignment can strand a flexible source on the wrong pip);
    generic mana is paid from whatever ready sources remain.
    """
    ready = [i for i, s in enumerate(sources) if s.ready]
    if len(ready) < cost.mana_value:
        return None
    adjacency = [[i for i in ready if sources[i].colors & pip] for pip in cost.pips]
    source_to_pip: dict[int, int] = {}

    def try_assign(pip_idx: int, visited: set[int]) -> bool:
        for src_idx in adjacency[pip_idx]:
            if src_idx in visited:
                continue
            visited.add(src_idx)
            if src_idx not in source_to_pip or try_assign(source_to_pip[src_idx], visited):
                source_to_pip[src_idx] = pip_idx
                return True
        return False

    for pip_idx in range(len(cost.pips)):
        if not try_assign(pip_idx, set()):
            return None

    used = list(source_to_pip.keys())
    remaining = [i for i in ready if i not in source_to_pip]
    if len(remaining) < cost.generic:
        return None
    used.extend(remaining[: cost.generic])
    return used


def _effective_cost(sc: SimCard, board_creatures: int, extra_discount: int = 0):
    """SC's cost for a `_can_pay` check, discounted for a self-referential board-state
    reduction (Blasphemous Act / Affinity-for-creatures class, `fx.self_reduction_per_creature`)
    tier0 would otherwise ignore entirely -- gating castability on the full PRINTED cost turns
    a spell routinely cast for 2-4 mana in a real game (Blasphemous Act is {8}{R}, MV 9) into
    one that almost never gets cast in a 12-turn goldfish run, which is a wrong model of the
    card, not a judgement that it is bad or the deck holds too many of its kind.

    Only the GENERIC portion is discounted, capped so it never goes negative -- a cost
    reduction never lowers what COLOUR you need to pay, only how much untyped mana. `pips`
    (and `mana_value`, which tracks `generic` in lockstep per symbol in `ManaCost.from_string`)
    both stay internally consistent because both drop by the identical, capped amount.

    `board_creatures` is tier0's own live count of creatures established as of the START of
    this turn (before this turn's own casts) -- a real reading, not a guess. tier0 has no
    modeled opponent (`sim/tier0.py`'s own docstring: "One player, no opponent"), so for
    "on the battlefield" wording (Vanquish the Horde class) this undercounts a real pod, where
    every player's creatures would also count -- a conservative direction, never a fabrication.
    """
    discount = sc.fx.self_reduction_per_creature * board_creatures + extra_discount
    if discount <= 0:
        return sc.card.cost
    cost = sc.card.cost
    discount = min(discount, cost.generic)  # never discount past the coloured-pip minimum
    return replace(cost, generic=cost.generic - discount, mana_value=cost.mana_value - discount)


def _keepable(hand: list[SimCard], size: int, cfg: SimConfig) -> bool:
    lands = sum(1 for c in hand if c.is_land)
    if size <= 5:
        return 1 <= lands <= size - 1
    return cfg.mulligan_min_lands <= lands <= min(cfg.mulligan_max_lands, size - 1)


def _mulligan(
    deck: list[SimCard], rng: SeededRng, cfg: SimConfig
) -> tuple[list[SimCard], list[SimCard], int]:
    """London-lite: redraw whole hands at decreasing size. Returns (hand, library, mulls)."""
    sizes = [7, 7, 6, 5] if cfg.free_first_mulligan else [7, 6, 5]
    hand: list[SimCard] = []
    library: list[SimCard] = []
    mulls = 0
    for attempt, size in enumerate(sizes):
        library = deck[:]
        rng.shuffle(library)
        hand = [library.pop() for _ in range(min(size, len(library)))]
        if _keepable(hand, size, cfg) or attempt == len(sizes) - 1:
            mulls = attempt
            break
    return hand, library, mulls


def _needed_colors(hand: list[SimCard], commander: SimCard | None) -> set[str]:
    needed: set[str] = set()
    pool = [c for c in hand if not c.is_land]
    if commander is not None:
        pool.append(commander)
    for c in pool:
        for pip in c.card.cost.pips:
            needed |= pip
    return needed


def _choose_land(hand: list[SimCard], needed: set[str]) -> SimCard | None:
    lands = [c for c in hand if c.is_land]
    if not lands:
        return None

    def score(land: SimCard) -> tuple[int, int]:
        colors = land.produced_colors()
        return (0 if land.fx.enters_tapped else 1, len(colors & needed))

    return max(lands, key=score)


def _cast_priority(sc: SimCard, turn: int, cfg: SimConfig) -> tuple:
    """Lower sorts first. Fixed greedy policy — see module docstring."""
    is_ramp = sc.fx.ramp_sources > 0
    if is_ramp and turn <= cfg.ramp_priority_turns:
        return (0, sc.mana_value)
    if sc.fx.draw_cards > 0:
        return (2, -sc.fx.impact, sc.mana_value)
    return (3, -sc.fx.impact, -sc.mana_value)


def _run_one(
    deck: list[SimCard], commander: SimCard | None, cfg: SimConfig, rng: SeededRng,
    board_wipe_turn: int | None = None,
    commander_survives_wipe: bool = False,
    rule: combat_rules.CombatRule | None = None,
    commander_removals: int = 0,
) -> RunStats:
    stats = RunStats()
    hand, library, stats.mulligans = _mulligan(deck, rng, cfg)
    stats.kept_hand_size = len(hand)
    cur_turn = 0                       # telemetry clock only (see RunStats.seen_turn)
    for c in hand:
        stats.seen_turn.setdefault(c.card.name, 0)

    def played(sc: SimCard) -> None:
        stats.played_turn.setdefault(sc.card.name, cur_turn)

    sources: list[_Source] = []
    commander_in_zone = commander is not None
    commander_tax = 0  # CR 903.8: {2} more per earlier cast from the command zone
    # B36: the commander is answered `commander_removals` times -- each time at the start of
    # the turn after it lands, before it can attack or untap -- and goes back to the command
    # zone (CR 903.9a) to be recast with {2} more tax. 0 (the default) never reads it.
    removals_left = commander_removals
    commander_cast_turn: int | None = None
    board_power = 0  # creatures able to attack (resolved on a previous turn)
    pending_power = 0  # creatures that came down this turn (summoning-sick)
    # The same two pools priced under the commander's combat rule (combat_rules; Doran's
    # toughness-for-power). Combat reads them only on turns the commander is on the
    # battlefield, so a game where it never lands is byte-identical to no rule at all.
    board_power_rule = 0
    pending_power_rule = 0
    board_creatures = 0  # count of able-to-attack creatures (mirrors board_power, for go-wide)
    pending_creatures = 0
    # Static anthems (docs/BACKLOG.md B3). The per-creature power bonus applies the moment its
    # source resolves; a CREATURE source dies in a wipe, a noncreature one does not. A lord
    # ("Other creatures ...") never buffs itself, so once it is able to attack its own bonus is
    # taken back out (`lord_self_active`, folded in with board_creatures at untap).
    anthem_noncreature = 0
    anthem_creature = 0
    lord_self_pending = 0
    lord_self_active = 0
    engine_active = 0  # extra draws per turn from resolved engines
    engine_pending = 0
    enabler_active = False  # a cheat-into-play enabler (Kaalia class) is online + can attack
    enabler_pending = False
    # non-combat damage engines (magecraft/cast-damage payoffs — Storm-Kiln/Guttersnipe class):
    # same one-turn-delay policy as engine_active above (a payoff that resolves this turn fires
    # starting NEXT turn, not on spells cast later this same turn — trigger conditions aren't
    # evaluated at rung 1, so this mirrors the existing engine_draw simplification rather than
    # inventing a new precision standard for burn specifically).
    dmg_engine_active = 0
    dmg_engine_pending = 0
    # The share of the two engine counters above that a CREATURE supplies (a Guttersnipe, a
    # creature with an engine-draw trigger): a board wipe destroys those, not the rest.
    creature_engine = 0
    creature_dmg_engine = 0
    damage = 0
    # B34 attribution, mirroring every change to the pools above (telemetry only).
    atk_pending: list[tuple[str, int, int, bool]] = []   # (name, power, power_rule, is_cmdr)
    atk_board: list[tuple[str, int, int, bool]] = []
    anthem_src: list[tuple[str, int, bool]] = []          # (name, bonus, source_is_creature)
    burn_pending: list[tuple[str, int, bool]] = []        # (name, per_spell, is_creature)
    burn_active: list[tuple[str, int, bool]] = []
    cmd_name = commander.card.name if commander is not None else None
    # Infect and toxic (CR 702.90, 702.180). `own_infect`/`toxic_of` are the creatures that
    # print it; the commander also gains infect while an infect Aura is on it (`cmd_auras`).
    # A deck with none of these never touches `poison`: every other figure is unchanged.
    everyone = deck + ([commander] if commander is not None else [])
    own_infect = {sc.card.name for sc in everyone
                  if sc.card.is_creature and _has_own_infect(sc.card.oracle_text or "")}
    toxic_of = {sc.card.name: n for sc in everyone if sc.card.is_creature
                and (n := _toxic_amount(sc.card.oracle_text or ""))}
    cast_filter_of = {sc.card.name: _cast_filter(sc.card.oracle_text or "") for sc in everyone
                      if sc.fx.magecraft_damage + sc.fx.cast_damage}
    cmd_auras: list[tuple[SimCard, _InfectAura]] = []   # infect Auras attached to the commander
    cmd_counters = 0                                    # -1/-1 counters on it (Glistening Oil)
    poison = 0

    def credit(name: str, source: str, amount: int) -> None:
        if amount:
            stats.damage_by_card[name] = stats.damage_by_card.get(name, 0) + amount
            stats.damage_by_source[source] = stats.damage_by_source.get(source, 0) + amount

    def credit_poison(name: str, amount: int) -> None:
        nonlocal poison
        if amount > 0:
            poison += amount
            stats.poison_by_card[name] = stats.poison_by_card.get(name, 0) + amount

    def has_infect(name: str, is_cmd: bool) -> bool:
        return name in own_infect or (is_cmd and bool(cmd_auras))

    def commander_on_board() -> bool:
        return commander is not None and commander.card.is_creature and not commander_in_zone

    def auras_fall_off() -> None:
        """The commander left the battlefield: its Auras go to the graveyard (CR 704.5m),
        one that says so comes back to hand (Glistening Oil), and its counters are gone."""
        nonlocal cmd_counters
        for aura, info in cmd_auras:
            if info.returns_to_hand:
                hand.append(aura)
        cmd_auras.clear()
        cmd_counters = 0

    def draw(n: int) -> None:
        for _ in range(n):
            if library:
                hand.append(library.pop())
                stats.cards_drawn += 1
                stats.seen_turn.setdefault(hand[-1].card.name, cur_turn)

    def apply_effects(sc: SimCard, is_commander: bool = False) -> None:
        nonlocal pending_power, pending_creatures, engine_pending, enabler_pending, dmg_engine_pending
        nonlocal creature_engine, creature_dmg_engine, pending_power_rule
        nonlocal anthem_noncreature, anthem_creature, lord_self_pending
        aura = _infect_aura(sc.card.type_line or "", sc.card.oracle_text or "")
        if aura is not None and commander_on_board():
            cmd_auras.append((sc, aura))
        for bonus, others in sc.anthems:
            anthem_src.append((sc.card.name, bonus, sc.card.is_creature))
            if sc.card.is_creature:
                anthem_creature += bonus
                if others:
                    lord_self_pending += bonus
            else:
                anthem_noncreature += bonus
        if sc.card.is_creature:
            pending_power += sc.attack_power
            pending_power_rule += sc.attack_power_under(rule)
            pending_creatures += 1
            atk_pending.append((sc.card.name, sc.attack_power, sc.attack_power_under(rule),
                                is_commander))
        if sc.fx.magecraft_damage + sc.fx.cast_damage:
            burn_pending.append((sc.card.name, sc.fx.magecraft_damage + sc.fx.cast_damage,
                                 sc.card.is_creature))
        if sc.fx.cheats_creatures:  # active next turn (a creature enabler must untap + attack)
            enabler_pending = True
        engine_pending += sc.fx.engine_draw
        dmg_engine_pending += sc.fx.magecraft_damage + sc.fx.cast_damage
        if sc.card.is_creature:
            creature_engine += sc.fx.engine_draw
            creature_dmg_engine += sc.fx.magecraft_damage + sc.fx.cast_damage
        if sc.fx.ritual_mana > 0:  # Dark Ritual class: a one-shot burst, spendable THIS turn
            sources.extend(
                _Source(sc.produced_colors(), ready=True, temp=True)
                for _ in range(sc.fx.ritual_mana)
            )
        if sc.fx.fetches_land:
            fetched = next((c for c in library if c.is_land), None)
            if fetched is not None:
                library.remove(fetched)
                sources.append(_Source(fetched.produced_colors(), ready=False))
        elif sc.fx.ramp_sources > 0:
            for _ in range(sc.fx.ramp_sources):
                sources.append(
                    _Source(sc.produced_colors(), ready=False,
                            from_creature=sc.card.is_creature, from_commander=is_commander)
                )
        draw(sc.fx.draw_cards)
        if sc.fx.tutor:
            spec = _tutor_spec(sc.card.type_line or "", sc.card.oracle_text or "")
            if spec is not None:
                fetch(spec)

    def plan_missing() -> bool:
        """The commander has no infect Aura on it or in hand, and one is still in the library."""
        return (commander is not None and commander.card.is_creature and not cmd_auras
                and not any(_infect_aura(c.card.type_line or "", c.card.oracle_text or "")
                            for c in hand)
                and any(_infect_aura(c.card.type_line or "", c.card.oracle_text or "")
                        for c in library))

    def _tutor_finds_plan(sc: SimCard) -> bool:
        spec = _tutor_spec(sc.card.type_line or "", sc.card.oracle_text or "")
        return spec is not None and any(
            spec.matches(c) and _infect_aura(c.card.type_line or "", c.card.oracle_text or "")
            for c in library)

    def fetch(spec: _TutorSpec) -> None:
        """A tutor resolves: the deck's plan piece if it is missing (an infect Aura for a
        commander that has none on it or in hand), else the highest-impact card the tutor may
        take -- the same value prior Tier-2's `_tutor_pick` falls back to. The real shuffle
        is not modeled (it draws no randomness, so the rest of the game is unchanged)."""
        cands = [c for c in library if spec.matches(c)]
        if not cands:
            return
        pick = None
        if plan_missing():
            pick = next((c for c in cands
                         if _infect_aura(c.card.type_line or "", c.card.oracle_text or "")), None)
        if pick is None:
            pick = max(cands, key=lambda c: c.fx.impact)
        library.remove(pick)
        if spec.dest == "top":
            library.append(pick)                    # drawn at the next draw (draw pops the end)
            return
        stats.seen_turn.setdefault(pick.card.name, cur_turn)
        if spec.dest == "hand":
            hand.append(pick)
        else:                                       # onto the battlefield, uncast
            played(pick)
            apply_effects(pick)

    for turn in range(1, cfg.turns + 1):
        cur_turn = turn
        sources = [s for s in sources if not s.temp]  # ritual mana expires at untap
        for s in sources:
            s.ready = True
        board_power += pending_power
        pending_power = 0
        board_power_rule += pending_power_rule
        pending_power_rule = 0
        board_creatures += pending_creatures
        pending_creatures = 0
        lord_self_active += lord_self_pending
        lord_self_pending = 0
        engine_active += engine_pending
        engine_pending = 0
        dmg_engine_active += dmg_engine_pending
        dmg_engine_pending = 0
        atk_board.extend(atk_pending)
        atk_pending.clear()
        burn_active.extend(burn_pending)
        burn_pending.clear()
        enabler_active = enabler_active or enabler_pending
        enabler_pending = False

        # Tier-1 disruption: a board wipe at the start of this turn destroys creatures.
        # In T0 that resets the creature clock, kills mana dorks, and kills the draw/damage
        # engines that were creatures; lands, rocks, and noncreature engines survive.
        # (Creature engines used to be left intact as "never over-counting the hit" — but on
        # a RESILIENCE axis that is the inflating direction: a Guttersnipe kept pinging after
        # the wrath that killed it, and the deck read as shrugging the wipe off. Pending
        # pools are always empty here, having been folded into the active ones above.)
        # A creature commander on the battlefield goes back to the command zone (CR 903.9a --
        # a pilot always takes that option) and can be recast for {2} more (CR 903.8). Without
        # this, a deck whose pressure IS its commander read as never recovering from a wipe.
        # Only ever reached in a wiped run, so clean runs -- every other axis -- are unchanged.
        #
        # `commander_survives_wipe` (the commander lens: an indestructible lead commander
        # survives a "destroy" wipe) keeps an on-board creature commander where it is -- no
        # return to the zone, no tax -- and re-adds its OWN contributions after the clear.
        # Ordering: pending pools were folded in just above and casts happen below, so a
        # commander on the battlefield here was cast on an EARLIER turn and every one of its
        # contributions already sits in the active pools; a commander cast this turn is cast
        # after the wipe and is untouched by it either way.
        # Glistening Oil: a -1/-1 counter on the commander every upkeep. At 0 toughness it dies
        # (CR 704.5f) and goes to the command zone like any other answer -- for a 2/4 that is
        # the fourth upkeep -- and the Oil returns to hand to go on the recast commander.
        if cmd_auras and commander_on_board():
            cmd_counters += sum(1 for _, a in cmd_auras if a.upkeep_counter)
        counters_kill = (cmd_counters > 0 and commander_on_board()
                         and 0 < commander.toughness_value <= cmd_counters)
        if counters_kill or (removals_left > 0 and commander is not None and not commander_in_zone
                             and commander_cast_turn is not None and commander_cast_turn < turn):
            # take back exactly what apply_effects(commander) put on the board (see there)
            if not counters_kill:
                removals_left -= 1
            auras_fall_off()
            commander_in_zone = True
            commander_tax += 2
            cfx, cname = commander.fx, commander.card.name
            if commander.card.is_creature:
                board_power -= commander.attack_power
                board_power_rule -= commander.attack_power_under(rule)
                board_creatures -= 1
                atk_board[:] = [a for a in atk_board if not (a[0] == cname and a[3])]
                creature_engine -= cfx.engine_draw
                creature_dmg_engine -= cfx.magecraft_damage + cfx.cast_damage
            for bonus, others in commander.anthems:
                if commander.card.is_creature:
                    anthem_creature -= bonus
                    if others:
                        lord_self_active -= bonus
                else:
                    anthem_noncreature -= bonus
            anthem_src[:] = [a for a in anthem_src if a[0] != cname]
            burn_active[:] = [b for b in burn_active if b[0] != cname]
            engine_active -= cfx.engine_draw
            dmg_engine_active -= cfx.magecraft_damage + cfx.cast_damage
            if cfx.cheats_creatures:
                enabler_active = False  # the commander was the enabler (an honest under-count
                #                         if another enabler is also out)
            sources = [src for src in sources if not src.from_commander]

        if board_wipe_turn is not None and turn == board_wipe_turn:
            commander_stays = False
            if (commander is not None and not commander_in_zone
                    and commander.card.is_creature):
                if commander_survives_wipe:
                    commander_stays = True
                else:
                    commander_in_zone = True
                    commander_tax += 2
                    auras_fall_off()
            board_power = 0
            pending_power = 0
            board_power_rule = 0
            pending_power_rule = 0
            board_creatures = 0
            pending_creatures = 0
            anthem_creature = 0  # creature-sourced anthems die with their source
            atk_board.clear()
            atk_pending.clear()
            anthem_src[:] = [a for a in anthem_src if not a[2]]
            burn_active[:] = [b for b in burn_active if not b[2]]
            lord_self_active = lord_self_pending = 0
            sources = [s for s in sources
                       if not s.from_creature or (commander_stays and s.from_commander)]
            enabler_active = enabler_pending = False  # the enabler died too
            engine_active -= creature_engine
            dmg_engine_active -= creature_dmg_engine
            creature_engine = creature_dmg_engine = 0
            if commander_stays:
                # exactly what apply_effects(commander) put on the board (see there)
                board_power = commander.attack_power
                board_power_rule = commander.attack_power_under(rule)
                atk_board.append((commander.card.name, commander.attack_power,
                                  commander.attack_power_under(rule), True))
                anthem_src.extend((commander.card.name, b, True) for b, _ in commander.anthems)
                if commander.fx.magecraft_damage + commander.fx.cast_damage:
                    burn_active.append((commander.card.name, commander.fx.magecraft_damage
                                        + commander.fx.cast_damage, True))
                board_creatures = 1
                for bonus, others in commander.anthems:  # a surviving commander keeps its anthem
                    anthem_creature += bonus
                    if others:
                        lord_self_active += bonus
                enabler_active = commander.fx.cheats_creatures
                creature_engine = commander.fx.engine_draw
                creature_dmg_engine = commander.fx.magecraft_damage + commander.fx.cast_damage
                engine_active += creature_engine
                dmg_engine_active += creature_dmg_engine

        if turn > 1 or cfg.draw_on_first_turn:
            draw(1)
        draw(engine_active)

        land = _choose_land(hand, _needed_colors(hand, commander if commander_in_zone else None))
        if land is not None:
            hand.remove(land)
            played(land)
            sources.append(_Source(land.produced_colors(), ready=not land.fx.enters_tapped))
        stats.land_drops.append(land is not None)

        mana_available = sum(1 for s in sources if s.ready)
        stats.sources_by_turn.append(len(sources))
        stats.mana_available_by_turn.append(mana_available)

        spent = 0
        cast_this_turn: list[SimCard] = []  # feeds the magecraft/cast-damage payoffs below
        while True:
            castable: list[tuple[tuple, SimCard, list[int], bool]] = []
            for sc in hand:
                # Scaling-burn (Fireball class) is held back from the greedy loop: cast at its
                # printed X=0 the moment it's affordable, it would fire early for no damage and
                # never get another look. It gets its own pass below, once every OTHER spell
                # this turn has had first claim on the mana.
                if sc.is_land or sc.fx.scaling_burn:
                    continue
                # An infect Aura is held for the commander (see _infect_aura): cast with no
                # commander out it would enchant nothing the deck is built around. Once the
                # commander is out, it goes on first -- it IS the plan, ranked with the
                # commander itself -- unless one is already on.
                plan_piece = _infect_aura(sc.card.type_line or "", sc.card.oracle_text or "")
                if plan_piece and not commander_on_board():
                    continue
                rule_discount = (rule.creature_discount(sc.card)
                                 if rule is not None and commander is not None and not commander_in_zone
                                 else 0)
                payment = _can_pay(sources, _effective_cost(sc, board_creatures, rule_discount))
                if payment is not None:
                    prio = ((1, sc.mana_value) if (plan_piece and not cmd_auras)
                            or (sc.fx.tutor and plan_missing() and _tutor_finds_plan(sc))
                            else _cast_priority(sc, turn, cfg))
                    castable.append((prio, sc, payment, False))
            if commander_in_zone and commander is not None:
                cmd_cost = _effective_cost(commander, board_creatures)
                if commander_tax:
                    cmd_cost = replace(cmd_cost, generic=cmd_cost.generic + commander_tax,
                                       mana_value=cmd_cost.mana_value + commander_tax)
                payment = _can_pay(sources, cmd_cost)
                if payment is not None:
                    castable.append(((1, commander.mana_value), commander, payment, True))
            if not castable:
                break

            _, sc, payment, is_commander = min(castable, key=lambda t: t[0])
            for idx in payment:
                sources[idx].ready = False
            spent += len(payment)  # actual sources tapped -- correct even under a discount
            stats.spells_cast += 1
            cast_this_turn.append(sc)

            if is_commander:
                commander_in_zone = False
                commander_cast_turn = turn
                if stats.commander_turn is None:  # first cast only; a recast is not "on time"
                    stats.commander_turn = turn
            else:
                hand.remove(sc)
                played(sc)
            apply_effects(sc, is_commander)

        # Scaling-burn finisher: whatever mana is left over this turn is spent as X (mirrors
        # how a player actually plays a Fireball — as a mana sink, not for X=0). Cheapest
        # candidate first so a second one still gets a turn if the first didn't need everything.
        burn_candidates = sorted(
            (sc for sc in hand if sc.fx.scaling_burn), key=lambda c: c.mana_value
        )
        for sc in burn_candidates:
            payment = _can_pay(sources, sc.card.cost)
            if payment is None:
                continue
            for idx in payment:
                sources[idx].ready = False
            x = sum(1 for s in sources if s.ready)
            for s in sources:
                if s.ready:
                    s.ready = False
            spent += sc.mana_value + x
            stats.spells_cast += 1
            cast_this_turn.append(sc)
            hand.remove(sc)
            played(sc)
            apply_effects(sc)
            damage += x
            credit(sc.card.name, "burn", x)

        stats.mana_spent_by_turn.append(spent)

        # combat: everything that was already down swings at the goldfish opponent
        rule_live = rule is not None and commander is not None and not commander_in_zone
        swing = board_power_rule if rule_live else board_power
        swing += max(0, (anthem_noncreature + anthem_creature) * board_creatures - lord_self_active)
        stats.board_power_by_turn.append(swing)
        stats.board_creatures_by_turn.append(board_creatures)
        # Infect (CR 702.90b): an infect attacker's damage is poison, not life; toxic (CR
        # 702.180) adds its poison on top of the damage. The commander's -1/-1 counters
        # (Glistening Oil) shrink its power. A deck with no infect, toxic or counters takes
        # none of these branches and deals exactly `swing`.
        per_creature = anthem_noncreature + anthem_creature
        extra = max(0, per_creature * board_creatures - lord_self_active)
        infect_attackers = 0
        for name, pw, pw_rule, is_cmd in atk_board:
            p = pw_rule if rule_live else pw
            if is_cmd and cmd_counters:
                cut = min(cmd_counters, p)
                p -= cut
                swing -= cut
            if has_infect(name, is_cmd):
                infect_attackers += 1
                swing -= p
                credit_poison(name, p)
            else:
                credit(name, "commander" if is_cmd else "combat", p)
            if toxic_of.get(name) and p + per_creature > 0:
                credit_poison(name, toxic_of[name])
        infect_bonus = min(extra, per_creature * infect_attackers)
        swing -= infect_bonus
        damage += swing
        total_bonus = sum(a[1] for a in anthem_src)
        for amount, to_poison in ((extra - infect_bonus, False), (infect_bonus, True)):
            if amount and total_bonus:
                given = 0
                for i, (name, bonus, _) in enumerate(anthem_src):
                    share = (amount - given if i == len(anthem_src) - 1
                             else amount * bonus // total_bonus)
                    if to_poison:
                        credit_poison(name, share)
                    else:
                        credit(name, "combat", share)
                    given += share
        # magecraft / cast-damage payoffs: each counts the casts its own trigger names
        for name, per_spell, _ in burn_active:
            flt = cast_filter_of.get(name, (False, 0))
            hit = per_spell * sum(1 for c in cast_this_turn if _counts_for(c, flt))
            if has_infect(name, name == cmd_name):
                credit_poison(name, hit)
            else:
                damage += hit
                credit(name, "burn", hit)
        if enabler_active:  # Kaalia class: cheat the biggest STRANDED creature in, attacking now
            stranded = [c for c in hand if c.card.is_creature]
            if stranded:
                cheated = max(stranded, key=lambda c: c.attack_power)
                hand.remove(cheated)
                played(cheated)
                hit = cheated.attack_power_under(rule) if rule_live else cheated.attack_power
                if has_infect(cheated.card.name, False):
                    credit_poison(cheated.card.name, hit)
                else:
                    damage += hit
                    credit(cheated.card.name, "combat", hit)
                if toxic_of.get(cheated.card.name) and hit > 0:
                    credit_poison(cheated.card.name, toxic_of[cheated.card.name])
                atk_pending.append((cheated.card.name, cheated.attack_power,
                                    cheated.attack_power_under(rule), False))
                pending_power += cheated.attack_power  # ... and stays on board thereafter
                pending_power_rule += cheated.attack_power_under(rule)
                pending_creatures += 1
        stats.damage_by_turn.append(damage)
        stats.poison_by_turn.append(poison)
        if (stats.commander_lethal_turn is None and cmd_name is not None
                and stats.damage_by_source.get("commander", 0) >= COMMANDER_DAMAGE_LETHAL):
            stats.commander_lethal_turn = turn
        if stats.kill_turn is None and damage >= cfg.goldfish_life:
            stats.kill_turn = turn
            stats.kill_sources = dict(stats.damage_by_source)
            stats.kill_method = max(stats.kill_sources, key=lambda k: (stats.kill_sources[k], k))
        elif stats.kill_turn is None and stats.commander_lethal_turn == turn:
            # CR 704.5a: 21 or more combat damage from a single commander loses the game,
            # whatever the life total. tier0 counted only life, so a Voltron/commander-beats
            # deck's goldfish kill came late in the games where its commander got there first
            # (measured 2026-11-07: Marchesa 21% of games, Syr Gwyn 15%, Doran 10%, Krenko 6%).
            stats.kill_turn = turn
            stats.kill_sources = dict(stats.damage_by_source)
            stats.kill_method = "commander_damage"   # same name as T2's end reason
        elif stats.kill_turn is None and poison >= POISON_LETHAL:
            # CR 704.5c. kill_sources reads the poison in life terms (one counter = a tenth of
            # the way, as goldfish_life / 10 is of life) so the damage-share split stays a split
            # of "how the deck got there".
            stats.kill_turn = turn
            stats.kill_sources = dict(stats.damage_by_source)
            stats.kill_sources["poison"] = poison * cfg.goldfish_life // POISON_LETHAL
            stats.kill_method = "poison"

    rule_live = rule is not None and commander is not None and not commander_in_zone
    stats.final_board_power = (board_power_rule if rule_live else board_power) + max(
        0, (anthem_noncreature + anthem_creature) * board_creatures - lord_self_active)
    stats.final_board_creatures = board_creatures
    stats.dead_cards = sum(1 for c in hand if not c.is_land)
    # Telemetry only (read nowhere in play): every permanent source untapped, could the stuck
    # card be paid? Enough sources but no assignment = the colours were the blocker.
    full = [_Source(s.colors) for s in sources if not s.temp]
    for c in hand:
        if c.is_land:
            continue
        if len(full) < c.mana_value:
            stats.stranded_by_cost.add(c.card.name)
        elif _can_pay(full, c.card.cost) is None:
            stats.stranded_by_colour.add(c.card.name)
    return stats


def simulate(
    cards: list[tuple[Card, int]], commander: Card | None, cfg: SimConfig,
    board_wipe_turn: int | None = None,
    commander_survives_wipe: bool = False,
    commander_removals: int = 0,
) -> list[RunStats]:
    """Run cfg.runs seeded goldfish games. Deterministic for a given (deck, cfg).

    board_wipe_turn injects a Tier-1 disruption (see _run_one). Because run i always
    draws from the same seeded stream, a clean run and a wiped run at the same seed are
    a matched pair — variance cancels when their outcomes are differenced (resilience).

    commander_survives_wipe: the lead commander survives that wipe (commander lens,
    `CommanderLens.survives_mode("destroy")`); False -- the default -- is byte-identical
    to the pre-lens behaviour, and clean runs (no wipe) never read it.

    commander_removals (B36): the commander is answered that many times, each at the start of
    the turn after it lands, and recast with tax. 0 -- the default -- is byte-identical; a deck
    without a commander is unaffected by any value.
    """
    deck = build_sim_cards(cards)
    sim_commander = SimCard(card=commander, fx=tags.analyze(commander)) if commander else None
    rule = combat_rules.from_commanders([commander])
    root = SeededRng(cfg.seed)
    return [
        _run_one(deck, sim_commander, cfg, root.spawn(i), board_wipe_turn,
                 commander_survives_wipe, rule, commander_removals)
        for i in range(cfg.runs)
    ]
