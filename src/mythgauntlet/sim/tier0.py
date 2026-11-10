"""Tier-0 goldfish consistency simulator (docs/SIMULATION.md).

One player, no opponent. Measures the statistical skeleton of a deck: mulligans, land
drops, color access, mana development, and how efficiently the curve deploys.

Documented simplifications (T0 is built to be fast, deterministic, and honest — not complete):
  - Activated abilities are ignored unless a reader below names them; haste is read when
    printed, granted to the team, or given by a haste Equipment.
    Commander tax only arises after a Tier-1 board wipe sends the commander back to the
    command zone (the clean goldfish casts it once).
  - The unmodeled-mechanics sweep (2026-11-09; scripts/unmodeled_inventory.py) added, each
    read strictly from the card's own text: Station / Spacecraft, crewed Vehicles, creature
    tokens, pump Equipment and Auras, proliferate, fixed drains, direct poison, Treasure and
    extra land drops. Anything a reader cannot read exactly does nothing (the honest
    under-count): variable counts, death triggers, modal choices, activated abilities.
  - Second and third sweeps (sim/tier0_readers.py, same strictness): '*' and "for each"
    power over lands / creatures / artifacts / hand, +1/+1 counters on entry (fixed, X,
    fabricate) and their replacements (Hardened Scales, Doubling Season), Hydra-class X
    creatures cast from spare mana, mana-only pump and counter sinks incl. monstrosity /
    adapt, prowess, exalted, extort, lifelink into "whenever you gain life" drains, the
    aristocrats finisher (free outlet + death drains, only when lethal), token doublers,
    additional combat phases, clones, Lotus Petal, land-Aura ramp, board-sized draws,
    affinity for artifacts, convoke, mana flashback, cascade, native storm copies, haste
    Equipment and team haste, pump spells, living weapon, beginning-of-combat counters.
  - Rocks/dorks/fetched lands come in "asleep" and produce from the next untap onward.
  - Land-fetch spells pull a land out of the library (thinning) and add a source next turn.
  - One-shot draws resolve immediately; triggered engines draw a flat engine_draw per turn
    starting the turn after they resolve (trigger conditions not evaluated).
  - X spells are cast for X=0, except scaling burn and X creatures (cast from spare mana).
    Every source produces exactly one mana.
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

from mythgauntlet.model.card import Card, ManaCost
from mythgauntlet.semantics import tags
from mythgauntlet.sim import combat_rules
from mythgauntlet.sim import tier0_readers as R0
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
_KEYWORD_LINE_HASTE = re.compile(r"(?:[a-z' ]+, )*haste(?:, [a-z' ]+)*")


@lru_cache(maxsize=4096)
def _has_own_haste(oracle_text: str) -> bool:
    """Haste PRINTED on a keyword line of the card's own (CR 702.10). A creature that gains it
    from elsewhere (a Lightning Greaves, a lord) is not read: the honest under-count."""
    return any(_KEYWORD_LINE_HASTE.fullmatch(ln) for ln in _rules_lines(oracle_text))


_NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
_TOKEN_RE = re.compile(
    r"\bcreate (a|an|one|two|three|four|five|six) (tapped )?(\d+)/(\d+) ([^.]*?)creature "
    r"tokens?([^.]*)")


@dataclass(frozen=True)
class _TokenMaker:
    trigger: str        # now | upkeep | end | cast | attack | attack_any | land | pw
    count: int
    power: int
    haste: bool
    attacking: bool     # "tapped and attacking": in this combat already
    cast_kind: str = "any"      # cast trigger: any | noncreature | instant_sorcery
    cast_min_mv: int = 0
    infect: bool = False        # "... creature token with infect"


def _token_trigger(prefix: str, is_spell: bool) -> tuple[str, str, int] | None:
    """(trigger, cast_kind, min_mv) for the text in front of "create", or None when it is a
    trigger tier0 cannot time (a death, another creature attacking, a condition, a cost)."""
    p = prefix.strip()
    if re.fullmatch(r"\+\d+:", p):
        return ("pw", "any", 0)                     # a loyalty ability: once a turn
    if ":" in p or p.startswith("•") or re.search(r"\bif\b|\bunless\b", p):
        return None
    if re.fullmatch(r"i(?:, ii)? —", p):
        return ("now", "any", 0)                    # a Saga's chapter I fires as it enters
    if re.fullmatch(r"whenever you attack,(?: for each opponent,)?", p) or re.fullmatch(
            r"whenever one or more (?:other )?creatures you control deal combat damage to "
            r"(?:a player|an opponent|one or more players),", p):
        return ("attack_any", "any", 0)
    if not p:
        return ("now", "any", 0) if is_spell else None
    if re.fullmatch(r"when(?:ever)? (?:~|this [a-z]+)(?: enters| enters or attacks)?,", p) and \
            "enters" in p:
        return ("now", "any", 0)
    if re.fullmatch(r"whenever (?:~|this [a-z]+) (?:attacks|deals combat damage to a player"
                    r"|deals combat damage to an opponent),", p):
        return ("attack", "any", 0)                 # an unblocked goldfish attack connects
    if re.fullmatch(r"at the beginning of (?:your upkeep|each upkeep|combat on your turn),"
                    r"(?: you lose \d+ life and)?", p):
        return ("upkeep", "any", 0)                 # "each upkeep": counted on ours only
    if re.fullmatch(r"at the beginning of your end step,", p):
        return ("end", "any", 0)
    if re.fullmatch(r"(?:landfall — )?whenever a land(?: you control)? enters(?: the battlefield)?"
                    r"(?: under your control)?,", p):
        return ("land", "any", 0)
    m = re.fullmatch(r"whenever you cast (?:a|an) ([a-z ]*?)spell( with mana value (\d+) or "
                     r"greater)?,", p)
    if m:
        what = m.group(1).strip()
        mv = int(m.group(3)) if m.group(3) else 0
        if what == "":
            return ("cast", "any", mv)
        if what == "noncreature":
            return ("cast", "noncreature", mv)
        if what in ("instant or sorcery", "instant and sorcery"):
            return ("cast", "instant_sorcery", mv)
        if what in ("creature", "artifact", "enchantment", "legendary"):
            return ("cast", what, mv)
    return None


@lru_cache(maxsize=4096)
def _token_makers(name: str, type_line: str, oracle_text: str) -> tuple[_TokenMaker, ...]:
    """Creature tokens this card makes, read strictly (see _token_trigger). Only a fixed count
    of fixed-size tokens is read: "for each", X, copies ("a token that's a copy"), a second
    token type in the same sentence and anything after a cost is not. Others' tokens ("each
    opponent creates", "its controller creates") never match: the verb is "create"."""
    is_spell = any(t in (type_line or "").lower() for t in ("instant", "sorcery"))
    out: list[_TokenMaker] = []
    names = sorted({name.lower(), name.lower().split(",")[0]}, key=len, reverse=True)
    for line in _rules_lines(oracle_text):
        for n in names:
            line = line.replace(n, "~")
        for sentence in re.split(r"(?<=\.)\s+", line):
            m = _TOKEN_RE.search(sentence)
            if not m:
                continue
            rest = m.group(6)
            if re.search(r"for each|where x|equal to|copy", rest + m.group(5)):
                continue
            trig = _token_trigger(sentence[:m.start()], is_spell)
            if trig is None:
                continue
            out.append(_TokenMaker(
                trigger=trig[0], count=_NUM_WORDS[m.group(1)], power=int(m.group(3)),
                haste="haste" in rest, attacking="tapped and attacking" in rest,
                cast_kind=trig[1], cast_min_mv=trig[2], infect="infect" in rest))
            if trig[0] == "now" and "enters or attacks" in sentence[:m.start()]:
                out.append(_TokenMaker("attack", _NUM_WORDS[m.group(1)], int(m.group(3)),
                                       "haste" in rest, "tapped and attacking" in rest))
    return tuple(out)


@dataclass(frozen=True)
class _EffectMaker:
    """A non-token repeatable or one-shot effect, timed like a _TokenMaker."""
    kind: str           # proliferate | drain | treasure | poison
    trigger: str
    amount: int
    cast_kind: str = "any"
    cast_min_mv: int = 0


_DRAIN_RE = re.compile(
    r"\b(?:each opponent|target opponent|target player|each player) loses (\d+) life"
    r"|\bdeals? (\d+) damage to (each opponent|target opponent|target player|any target"
    r"|each player)")
_POISON_RE = re.compile(
    r"\b(?:each opponent|target opponent|target player)\b[^.]*?\bgets? (a|an|one|two|three) "
    r"poison counters?")
_TREASURE_RE = re.compile(r"\bcreate (a|an|one|two|three|four|five|six) (?:tapped )?treasure tokens?")
_GAIN_RE = re.compile(r"\byou gain (\d+) life\b")


@lru_cache(maxsize=4096)
def _effect_makers(name: str, type_line: str, oracle_text: str) -> tuple[_EffectMaker, ...]:
    """Proliferate, fixed drains and Treasure, read strictly with the token makers' trigger
    timing (_token_trigger). A drain on a cast trigger that deals DAMAGE is already read by
    `tags` (cast_damage / magecraft) and is skipped here, never counted twice; a spell's own
    "N damage to any target" is not read as face damage (casual pilots point it at creatures);
    "X", "for each" and "equal to" amounts are not read."""
    is_spell = any(t in (type_line or "").lower() for t in ("instant", "sorcery"))
    out: list[_EffectMaker] = []
    names = sorted({name.lower(), name.lower().split(",")[0]}, key=len, reverse=True)
    for line in _rules_lines(oracle_text):
        for n in names:
            line = line.replace(n, "~")
        for sentence in re.split(r"(?<=\.)\s+", line):
            found: list[tuple[str, int, int]] = []          # (kind, amount, start)
            m = re.search(r"\bproliferate\b", sentence)
            if m:
                found.append(("proliferate", 1, m.start()))
            m = _DRAIN_RE.search(sentence)
            if m and not re.search(r"for each|equal to|where x", sentence[m.start():]):
                amt = int(m.group(1) or m.group(2))
                found.append(("drain", amt, m.start()))
            m = _POISON_RE.search(sentence)
            if m:
                found.append(("poison", _NUM_WORDS[m.group(1)], m.start()))
            m = _TREASURE_RE.search(sentence)
            if m and not re.search(r"for each|equal to|where x", sentence):
                found.append(("treasure", _NUM_WORDS[m.group(1)], m.start()))
            # life gain: only matters to a "whenever you gain life, ..." payoff (R0.gain_drain)
            m = _GAIN_RE.search(sentence)
            if m and not re.search(r"for each|equal to|where x", sentence[m.start():]):
                found.append(("gain", int(m.group(1)), m.start()))
            for kind, amt, start in found:
                head = sentence[:start]
                # A trigger opens the sentence ("When ~ enters, ...", "+1: ..."): its clause runs
                # to the first comma (the colon for a loyalty ability). Anything else in front
                # of the effect is the spell's own earlier effect ("Draw two cards, then ...").
                if re.match(r"(?:when|whenever|at the beginning|landfall|i(?:, ii)? —|\+\d+:)",
                            head):
                    cut = head.find(":") + 1 if re.match(r"\+\d+:", head) else head.find(",") + 1
                    if cut <= 0:
                        continue
                    prefix = head[:cut]
                else:
                    prefix = ""
                trig = _token_trigger(prefix, is_spell)
                if trig is None:
                    continue
                if kind == "drain":
                    if trig[0] == "cast" and "damage" in sentence[start:]:
                        continue                    # tags reads it (cast_damage / magecraft)
                    if trig[0] == "now" and is_spell and "any target" in sentence[start:]:
                        continue
                out.append(_EffectMaker(kind, trig[0], amt, trig[1], trig[2]))
    return tuple(out)


def _cast_matches(sc: "SimCard", kind: str, min_mv: int) -> bool:
    if sc.mana_value < min_mv:
        return False
    if kind == "noncreature":
        return not sc.card.is_creature
    if kind == "instant_sorcery":
        return sc.card.has_type("Instant") or sc.card.has_type("Sorcery")
    if kind != "any":
        return sc.card.has_type(kind.capitalize())
    return True


@dataclass(frozen=True)
class _Attachment:
    kind: str               # "equip" | "aura"
    bonus: int              # +N power to the creature it is on
    double_strike: bool     # "... has double strike"
    infect: bool            # "... has infect" (Grafted Exoskeleton)
    equip_cost: str         # the plain "Equip {..}" cost; "" for an Aura
    returns_to_hand: bool   # Rancor class


@lru_cache(maxsize=4096)
def _attachment(type_line: str, oracle_text: str) -> _Attachment | None:
    """A pump Equipment or Aura read strictly: "Equipped/Enchanted creature gets +N/+M" and/or
    "... has double strike / infect", on a line of its own with FIXED numbers ("for each" never
    reads). An Equipment needs a plain "Equip {cost}" (a "legendary creature" or other
    restricted equip is not read). An Aura that steals ("You control enchanted creature"), a
    negative one, and an infect-only Aura (`_infect_aura`, which goes on the commander) are
    not attachments here."""
    tl = (type_line or "").lower()
    lines = _rules_lines(oracle_text)
    if "equipment" in tl:
        kind, subj = "equip", "equipped creature"
    elif ("aura" in tl and "enchant creature" in lines
          and "you control enchanted creature." not in lines):
        kind, subj = "aura", "enchanted creature"
    else:
        return None
    bonus, ds, inf = 0, False, False
    for ln in lines:
        m = re.fullmatch(subj + r" gets \+(\d+)/[+-]\d+(?: and has ([a-z ,]+))?\.", ln)
        if m:
            bonus += int(m.group(1))
            kws = m.group(2) or ""
        else:
            m2 = re.fullmatch(subj + r" has ([a-z ,]+)\.", ln)
            kws = m2.group(1) if m2 else ""
        ds = ds or "double strike" in kws
        inf = inf or "infect" in kws
    cost = ""
    if kind == "equip":
        for ln in lines:
            m = re.fullmatch(r"equip ((?:\{[^}]+\})+)", ln)
            if m:
                cost = m.group(1)
                break
        if not cost:
            return None
    if kind == "aura":
        inf = False                                 # infect Auras: see _infect_aura
    if not (bonus or ds or inf):
        return None
    text = " ".join(lines)
    back = bool(re.search(r"is put into a graveyard from the battlefield, return [^.]* to its "
                          r"owner's hand", text))
    return _Attachment(kind, bonus, ds, inf, cost, back)


_EXTRA_LAND_RE = re.compile(
    r"you may play (an|one|two|three) additional lands? (on each of your turns|this turn)\.")


@lru_cache(maxsize=4096)
def _extra_land_drops(oracle_text: str) -> tuple[int, int]:
    """(each turn, this turn only) extra land drops printed as a line of their own (CR 305.2):
    Azusa / Exploration / Oracle of Mul Daya, and Explore-class spells. A conditional or
    activated grant is not read."""
    static = once = 0
    for ln in _rules_lines(oracle_text):
        m = _EXTRA_LAND_RE.fullmatch(ln) or _EXTRA_LAND_RE.match(ln)
        if m and m.start() == 0:
            n = _NUM_WORDS[m.group(1)]
            if m.group(2) == "this turn":
                once += n
            else:
                static += n
    return static, once


@lru_cache(maxsize=4096)
def _crew_cost(type_line: str, oracle_text: str) -> int | None:
    """Crew N of a Vehicle (CR 702.122): tap untapped creatures with total power N or more and it
    becomes an artifact creature until end of turn."""
    if "vehicle" not in (type_line or "").lower():
        return None
    for ln in _rules_lines(oracle_text):
        m = re.match(r"crew (\d+)\b", ln)
        if m:
            return int(m.group(1))
    return None


@lru_cache(maxsize=4096)
def _station_threshold(type_line: str, oracle_text: str) -> int | None:
    """The charge-counter count at which a Spacecraft becomes an artifact creature (CR 702.184:
    station taps another creature and adds counters equal to its power). Read from the card's
    own station reminder, "It's an artifact creature at N+"; a Spacecraft without one (The
    Eternity Elevator) never becomes a creature, nor does a Planet."""
    if "spacecraft" not in (type_line or "").lower():
        return None
    m = re.search(r"it's an artifact creature at (\d+)\+", (oracle_text or "").lower())
    return int(m.group(1)) if m else None
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
    treasure: bool = False  # a Treasure token: any colour, gone once it has been used


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
    # Vehicles and Spacecraft (CR 702.122, 702.184). Crew and station TAP creatures as a cost
    # (no {T} symbol), so summoning-sick creatures may pay it -- those are used first, since
    # they cannot attack anyway. A Vehicle attacks only once on the battlefield since the start
    # of the turn (CR 302.6); a stationed Spacecraft is an artifact creature for good.
    power_of = {sc.card.name: _stat_value(sc.card.power) for sc in everyone if sc.card.is_creature}
    # Second sweep (sim/tier0_readers.py). Per-creature properties, by card name:
    varp_of = {sc.card.name: v for sc in everyone
               if (v := R0.var_power(sc.card.name, sc.card.type_line or "", sc.card.oracle_text or ""))}
    prowess_of = {sc.card.name: n for sc in everyone if sc.card.is_creature
                  and (n := R0.prowess(sc.card.name, sc.card.oracle_text or ""))}
    lifelink_of = {sc.card.name for sc in everyone if sc.card.is_creature
                   and R0.lifelink(sc.card.name, sc.card.oracle_text or "")}
    sinks_of = {sc.card.name: s for sc in everyone if sc.card.is_creature
                and (s := R0.sinks(sc.card.name, sc.card.oracle_text or ""))}
    xcombat_of = {sc.card.name: k for sc in everyone
                  if (k := R0.extra_combat(sc.card.name, sc.card.type_line or "",
                                           sc.card.oracle_text or ""))}
    # ... and board-wide statics of permanents on the battlefield: (kind, source name, source
    # is a creature, value). kinds: artifact, exalted, doubler, counter_mod, gain_drain,
    # death_drain, outlet, extort. A wipe / an answered commander takes its own entries out.
    statics: list[tuple[str, str, bool, object]] = []
    lands_count = 0                 # lands on the battlefield (a '*' creature's count)
    convoke_used = 0                # summoning-sick creatures tapped for convoke this turn
    extort_due = 0                  # extort triggers this turn, paid from spare mana
    cmd_extra = 0                   # +1/+1 counter / copy power on the commander's entry
    graveyard_fb: list[SimCard] = []   # instants / sorceries with a mana flashback cost
    pumps_today: list[tuple[str, int]] = []   # pump spells resolved this turn (R0.pump_spell)
    once_done: set[str] = set()     # creatures that used their monstrosity / adapt

    def counters(n: int) -> int:
        """n +1/+1 counters after the battlefield's replacements: "plus one" first, then
        each "twice" (CR 616.1: the affected player orders them; this is the larger order)."""
        if n <= 0:
            return 0
        mods = [e[3] for e in statics if e[0] == "counter_mod"]
        n += sum(1 for m in mods if m == "plus")
        return n * 2 ** sum(1 for m in mods if m == "twice")

    def grow(pool: list, i: int, k: int) -> None:
        """+k +1/+1 counters on pool[i] (atk_board or atk_pending), double strike counted."""
        nonlocal board_power, board_power_rule, pending_power, pending_power_rule, cmd_extra
        name, pw, pwr, is_cmd = pool[i]
        k *= 2 if name in printed_ds else 1
        pool[i] = (name, pw + k, pwr + k, is_cmd)
        if pool is atk_board:
            board_power += k
            board_power_rule += k
        else:
            pending_power += k
            pending_power_rule += k
        if is_cmd:
            cmd_extra += k

    def n_artifacts() -> int:
        return (sum(1 for e in statics if e[0] == "artifact")
                + sum(1 for s in sources if s.treasure and s.ready))

    def pay_spare(cost) -> bool:
        """Pay a sink from untapped sources, never a Treasure (it keeps for a later turn)."""
        held = [s for s in sources if s.treasure and s.ready]
        for s in held:
            s.ready = False
        idx = _can_pay(sources, cost)
        for s in held:
            s.ready = True
        if idx is None:
            return False
        for i in idx:
            sources[i].ready = False
        return True

    vehicles_pending: list[SimCard] = []
    vehicles_board: list[SimCard] = []
    ships: list[dict] = []                              # unbuilt Spacecraft: sc, need, counters, turn
    # Creature tokens (_token_makers): (source name, maker, source is a creature). "now" makers
    # fire as the card resolves; upkeep / loyalty makers fire each turn from the next one (a
    # loyalty maker also on arrival); cast, attack, landfall and end-step makers on their event.
    token_engines: list[tuple[str, _TokenMaker, bool]] = []
    turn_engines: list[tuple[str, _TokenMaker, bool]] = []
    turn_engines_pending: list[tuple[str, _TokenMaker, bool]] = []

    def fire(src: str, mk, attacking: bool = False) -> None:
        """One maker fires: tokens, or a proliferate / drain / Treasure effect."""
        nonlocal damage
        if isinstance(mk, _TokenMaker):
            make_tokens(src, mk, attacking)
        elif mk.kind == "proliferate":
            if poison > 0:                          # the opponent's poison counters grow
                credit_poison(src, 1)
        elif mk.kind == "poison":
            credit_poison(src, mk.amount)
        elif mk.kind == "drain":
            damage += mk.amount
            credit(src, "burn", mk.amount)
        elif mk.kind == "treasure":
            n = mk.amount * 2 ** sum(1 for e in statics if e[0] == "doubler" and e[3] == "all")
            sources.extend(_Source(frozenset("WUBRG"), ready=True, treasure=True)
                           for _ in range(n))
        elif mk.kind == "gain":
            gain_life(mk.amount)

    def gain_life(amount: int) -> None:
        """You gain life: each "whenever you gain life, <opponent> loses ..." payoff on the
        battlefield drains (that much, or its fixed amount). Nothing else reads life gain."""
        nonlocal damage
        if amount <= 0:
            return
        for kind, name, _, v in list(statics):
            if kind == "gain_drain":
                hit = amount if v == 0 else v
                damage += hit
                credit(name, "burn", hit)

    def make_tokens(src: str, mk: _TokenMaker, attacking: bool = False) -> None:
        """Creature tokens join the board summoning-sick (they attack next turn); with haste
        or "tapped and attacking" they are in this combat. Credited to the card that made them.
        A token doubler on the battlefield (R0.token_doubler) doubles the count, each one."""
        nonlocal pending_power, pending_power_rule, pending_creatures
        nonlocal board_power, board_power_rule, board_creatures
        name = f"{src} token"
        power_of[name] = mk.power
        if mk.infect:
            own_infect.add(name)
        hasty = mk.haste or any(e[0] == "team_haste" for e in statics)
        for _ in range(mk.count * 2 ** sum(1 for e in statics if e[0] == "doubler")):
            entry = (name, mk.power, mk.power, False)
            if hasty or attacking:
                board_power += mk.power
                board_power_rule += mk.power
                board_creatures += 1
                atk_board.append(entry)
            else:
                pending_power += mk.power
                pending_power_rule += mk.power
                pending_creatures += 1
                atk_pending.append(entry)

    # Pump Equipment / Auras (_attachment): [sc, info, target name or None].
    attachments: list[list] = []
    # Extra land drops: (source name, n, source is a creature) for each-turn grants.
    extra_lands: list[tuple[str, int, bool]] = []

    def play_land() -> bool:
        nonlocal lands_count
        land = _choose_land(hand, _needed_colors(hand, commander if commander_in_zone else None))
        if land is None:
            return False
        lands_count += 1
        hand.remove(land)
        played(land)
        sources.append(_Source(land.produced_colors(), ready=not land.fx.enters_tapped))
        for src, mk, _ in list(token_engines):
            if mk.trigger == "land":
                fire(src, mk)
        return True
    printed_ds = {sc.card.name for sc in everyone if "double strike" in (sc.card.keywords or ())}

    def best_target() -> str | None:
        """The commander if it is out (Voltron), else the strongest creature able to attack,
        else the strongest summoning-sick one."""
        for pool in (atk_board, atk_pending):
            if pool:
                cmd = [a for a in pool if a[3]]
                return (cmd or [max(pool, key=lambda a: a[1])])[0][0]
        return None

    def creature_left(dead) -> None:
        """Creatures named by `dead(name)` left the battlefield: their Equipment stays,
        unattached; their Auras go to the graveyard (one that says so returns to hand)."""
        for att in list(attachments):
            if att[2] is not None and dead(att[2]):
                if att[1].kind == "equip":
                    att[2] = None
                else:
                    attachments.remove(att)
                    if att[1].returns_to_hand:
                        hand.append(att[0])

    def fire_cast(cast: SimCard) -> None:
        for src, mk, _ in list(token_engines):
            if mk.trigger == "cast" and _cast_matches(cast, mk.cast_kind, mk.cast_min_mv):
                fire(src, mk)

    def drop_engines(keep) -> None:
        for lst in (token_engines, turn_engines, turn_engines_pending):
            lst[:] = [e for e in lst if keep(e)]

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

    def apply_effects(sc: SimCard, is_commander: bool = False, x: int = 0) -> None:
        nonlocal pending_power, pending_creatures, engine_pending, enabler_pending, dmg_engine_pending
        nonlocal creature_engine, creature_dmg_engine, pending_power_rule
        nonlocal anthem_noncreature, anthem_creature, lord_self_pending
        nonlocal board_power, board_power_rule, board_creatures, cmd_extra, lands_count
        name, tl, text = sc.card.name, sc.card.type_line or "", sc.card.oracle_text or ""
        permanent = not (sc.card.has_type("Instant") or sc.card.has_type("Sorcery"))
        # Second sweep: what the permanent puts on the board (see tier0_readers).
        bonus = 0                   # +1/+1 counters it enters with, or the power it copies
        alive = True
        if sc.card.is_creature:
            fixed, per_x = R0.enters_counters(name, text)
            n = fixed + per_x * x + R0.fabricate(name, text)
            if n:
                bonus += counters(n) * (2 if name in printed_ds else 1)
            elif per_x and sc.toughness_value == 0:
                alive = False       # a 0/0 cast for X=0 dies at once (CR 704.5f)
            if R0.is_clone(name, tl, text):
                pool = [a for a in atk_board + atk_pending]
                if pool:            # the strongest creature you control (its printed power)
                    bonus += max(power_of.get(a[0], 0) for a in pool)
                else:
                    alive = False   # nothing to copy: a 0/0
            if is_commander:
                cmd_extra = bonus
        if permanent:
            if sc.card.has_type("Artifact"):
                statics.append(("artifact", name, sc.card.is_creature, 1))
            for kind, v in (("exalted", R0.exalted(name, text)),
                            ("doubler", R0.token_doubler(name, text)),
                            ("counter_mod", R0.counter_mod(name, text)),
                            ("gain_drain", R0.gain_drain(name, text)),
                            ("death_drain", R0.death_drain(name, text)),
                            ("outlet", R0.free_sac_outlet(name, text)),
                            ("extort", R0.extort(name, text)),
                            ("xcombat", xcombat_of.get(name) == "attack_any"),
                            ("haste_gear", R0.haste_gear(name, tl, text)),
                            ("team_haste", R0.team_haste(name, text)),
                            ("combat_counter", R0.combat_counter(name, text))):
                if v or (kind == "gain_drain" and v == 0):
                    statics.append((kind, name, sc.card.is_creature, v))
            sources.extend(_Source(frozenset("WUBRG"), ready=True, treasure=True)
                           for _ in range(R0.one_shot_mana(name, text)))
            n_ramp, cols = R0.aura_ramp(name, tl, text)
            sources.extend(_Source(cols, ready=False) for _ in range(n_ramp))
        if R0.pump_spell(name, tl, text):
            pumps_today.append((name, R0.pump_spell(name, tl, text)))
        vd = R0.var_draw(name, tl, text)
        if vd == "creature":
            draw(board_creatures + pending_creatures)
        elif vd == "power":
            pool = atk_board + atk_pending
            draw(max((power_of.get(a[0], 0) for a in pool), default=0))
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
        team_hasty = any(e[0] == "team_haste" and (e[3] == "all" or (e[3] == "other"
                                                                    and e[1] != name))
                         for e in statics)
        if not alive:
            pass
        elif sc.card.is_creature and (_has_own_haste(sc.card.oracle_text or "") or team_hasty):
            # haste (CR 702.10): able to attack the turn it arrives
            board_power += sc.attack_power + bonus
            board_power_rule += sc.attack_power_under(rule) + bonus
            board_creatures += 1
            atk_board.append((sc.card.name, sc.attack_power + bonus,
                              sc.attack_power_under(rule) + bonus, is_commander))
        elif sc.card.is_creature:
            pending_power += sc.attack_power + bonus
            pending_power_rule += sc.attack_power_under(rule) + bonus
            pending_creatures += 1
            atk_pending.append((sc.card.name, sc.attack_power + bonus,
                                sc.attack_power_under(rule) + bonus, is_commander))
        if _crew_cost(sc.card.type_line or "", sc.card.oracle_text or "") and sc.attack_power:
            vehicles_pending.append(sc)
        need = _station_threshold(sc.card.type_line or "", sc.card.oracle_text or "")
        if need and sc.attack_power:
            ships.append({"sc": sc, "need": need, "counters": 0, "turn": cur_turn})
        static_lands, once_lands = _extra_land_drops(sc.card.oracle_text or "")
        if static_lands and not (sc.card.has_type("Instant") or sc.card.has_type("Sorcery")):
            extra_lands.append((sc.card.name, static_lands, sc.card.is_creature))
            once_lands += static_lands              # the grant works the turn it arrives
        for _ in range(once_lands):                 # played at once, mid main phase
            if not play_land():
                break
        att = _attachment(sc.card.type_line or "", sc.card.oracle_text or "")
        if att is not None:
            target = best_target() if att.kind == "aura" else None
            if att.kind == "equip" and R0.living_weapon(name, text):
                # living weapon (CR 702.92): a 0/0 Germ enters and this attaches to it
                germ = f"{name} germ"
                power_of[germ] = 0
                pending_creatures += 1
                atk_pending.append((germ, 0, 0, False))
                target = germ
            attachments.append([sc, att, target])
        makers = (_token_makers(sc.card.name, sc.card.type_line or "", sc.card.oracle_text or "")
                  + _effect_makers(sc.card.name, sc.card.type_line or "", sc.card.oracle_text or ""))
        for mk in makers:
            eng = (sc.card.name, mk, sc.card.is_creature)
            if mk.trigger == "now":
                fire(sc.card.name, mk)
            elif mk.trigger in ("upkeep", "pw"):
                if mk.trigger == "pw":
                    fire(sc.card.name, mk)
                turn_engines_pending.append(eng)
            else:
                token_engines.append(eng)
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
                lands_count += 1
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

    def cast_one(sc: SimCard, is_commander: bool = False, x: int = 0,
                 flashback: bool = False) -> None:
        """A spell resolves (after its mana is paid): extort and cast triggers see it, then
        its effects, then cascade (CR 702.85) and the graveyard for a flashback card (one cast
        with flashback is exiled instead, CR 702.34a)."""
        nonlocal extort_due, damage
        stats.spells_cast += 1
        storm_count = len(cast_this_turn)           # spells cast before it this turn
        cast_this_turn.append(sc)
        extort_due += sum(e[3] for e in statics if e[0] == "extort")
        fire_cast(sc)
        apply_effects(sc, is_commander, x)
        if storm_count and R0.storm(sc.card.name, sc.card.oracle_text or ""):
            # Storm (CR 702.40): a copy per earlier spell. Each copy does what the reader reads
            # of the spell: its "now" tokens / drains / poison, and its own "N damage to any
            # target" at the face (R0.storm_damage). Copies are not cast: no cast triggers.
            nm, tl_, tx = sc.card.name, sc.card.type_line or "", sc.card.oracle_text or ""
            now = [mk for mk in _token_makers(nm, tl_, tx) + _effect_makers(nm, tl_, tx)
                   if mk.trigger == "now"]
            per = R0.storm_damage(nm, tx)
            for _ in range(storm_count):
                for mk in now:
                    fire(nm, mk)
                if per:
                    damage += per
                    credit(nm, "burn", per)
        if not flashback and R0.flashback_cost(sc.card.name, sc.card.type_line or "",
                                               sc.card.oracle_text or ""):
            graveyard_fb.append(sc)
        for _ in range(R0.cascade(sc.card.name, sc.card.oracle_text or "")):
            exiled: list[SimCard] = []
            hit = None
            while library:
                c = library.pop()
                if not c.is_land and c.mana_value < sc.mana_value:
                    hit = c
                    break
                exiled.append(c)
            library[0:0] = exiled                   # to the bottom (draw pops the end)
            if hit is not None:
                stats.seen_turn.setdefault(hit.card.name, cur_turn)
                played(hit)
                cast_one(hit)

    cast_this_turn: list[SimCard] = []
    for turn in range(1, cfg.turns + 1):
        cur_turn = turn
        convoke_used = 0
        extort_due = 0
        pumps_today.clear()
        # ritual mana expires at untap; a Treasure that was used was sacrificed
        sources = [s for s in sources if not s.temp and not (s.treasure and not s.ready)]
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
        vehicles_board.extend(vehicles_pending)
        vehicles_pending.clear()
        turn_engines.extend(turn_engines_pending)
        turn_engines_pending.clear()
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
                board_power -= commander.attack_power + cmd_extra
                board_power_rule -= commander.attack_power_under(rule) + cmd_extra
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
            drop_engines(lambda e: e[0] != cname)
            creature_left(lambda n: n == cname)
            extra_lands[:] = [e for e in extra_lands if e[0] != cname]
            statics[:] = [e for e in statics if e[1] != cname]
            cmd_extra = 0

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
            drop_engines(lambda e: not e[2] or (commander_stays and e[0] == cmd_name))
            creature_left(lambda n: not (commander_stays and n == cmd_name))
            extra_lands[:] = [e for e in extra_lands
                              if not e[2] or (commander_stays and e[0] == cmd_name)]
            statics[:] = [e for e in statics
                          if not e[2] or (commander_stays and e[1] == cmd_name)]
            if not commander_stays:
                cmd_extra = 0
            if commander_stays:
                # exactly what apply_effects(commander) put on the board (see there), plus
                # the +1/+1 counters it has gained since (they stay with it)
                board_power = commander.attack_power + cmd_extra
                board_power_rule = commander.attack_power_under(rule) + cmd_extra
                atk_board.append((commander.card.name, commander.attack_power + cmd_extra,
                                  commander.attack_power_under(rule) + cmd_extra, True))
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

        for src, mk, _ in turn_engines:
            fire(src, mk)

        if turn > 1 or cfg.draw_on_first_turn:
            draw(1)
        draw(engine_active)

        land_played = play_land()
        for _ in range(sum(n for _, n, _ in extra_lands) if land_played else 0):
            if not play_land():
                break
        stats.land_drops.append(land_played)

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
                pump_aura = _attachment(sc.card.type_line or "", sc.card.oracle_text or "")
                if (pump_aura is not None and pump_aura.kind == "aura"
                        and not (atk_board or atk_pending)):
                    continue
                # An X creature that enters with X counters waits for the X pass below (cast
                # here for X=0 it would be a 0/0); a clone with nothing to copy is not cast.
                if sc.card.is_creature and R0.enters_counters(
                        sc.card.name, sc.card.oracle_text or "")[1]:
                    continue
                if (R0.is_clone(sc.card.name, sc.card.type_line or "", sc.card.oracle_text or "")
                        and not (atk_board or atk_pending)):
                    continue
                # a pump spell is held until something can attack with it
                if (R0.pump_spell(sc.card.name, sc.card.type_line or "", sc.card.oracle_text or "")
                        and not atk_board):
                    continue
                rule_discount = (rule.creature_discount(sc.card)
                                 if rule is not None and commander is not None and not commander_in_zone
                                 else 0)
                # Affinity for artifacts (CR 702.41) and convoke (CR 702.51, generic mana only,
                # tapping creatures that are summoning-sick -- they cannot attack this turn).
                if R0.affinity_artifacts(sc.card.name, sc.card.oracle_text or ""):
                    rule_discount += n_artifacts()
                conv = 0
                if R0.convoke(sc.card.name, sc.card.oracle_text or ""):
                    left = (sc.card.cost.generic - rule_discount
                            - sc.fx.self_reduction_per_creature * board_creatures)
                    conv = max(0, min(pending_creatures - convoke_used, left))
                payment = _can_pay(sources, _effective_cost(sc, board_creatures,
                                                            rule_discount + conv))
                if payment is not None:
                    prio = ((1, sc.mana_value) if (plan_piece and not cmd_auras)
                            or (sc.fx.tutor and plan_missing() and _tutor_finds_plan(sc))
                            else _cast_priority(sc, turn, cfg))
                    castable.append((prio, sc, payment, "hand", conv))
            for sc in graveyard_fb:
                payment = _can_pay(sources, ManaCost.parse(R0.flashback_cost(
                    sc.card.name, sc.card.type_line or "", sc.card.oracle_text or "")))
                if payment is not None:
                    castable.append((_cast_priority(sc, turn, cfg), sc, payment, "fb", 0))
            if commander_in_zone and commander is not None:
                cmd_cost = _effective_cost(commander, board_creatures)
                if commander_tax:
                    cmd_cost = replace(cmd_cost, generic=cmd_cost.generic + commander_tax,
                                       mana_value=cmd_cost.mana_value + commander_tax)
                payment = _can_pay(sources, cmd_cost)
                if payment is not None:
                    castable.append(((1, commander.mana_value), commander, payment, "cmd", 0))
            if not castable:
                break

            _, sc, payment, origin, conv = min(castable, key=lambda t: t[0])
            for idx in payment:
                sources[idx].ready = False
            spent += len(payment)  # actual sources tapped -- correct even under a discount
            convoke_used += conv

            if origin == "cmd":
                commander_in_zone = False
                commander_cast_turn = turn
                if stats.commander_turn is None:  # first cast only; a recast is not "on time"
                    stats.commander_turn = turn
            elif origin == "fb":
                graveyard_fb.remove(sc)
            else:
                hand.remove(sc)
                played(sc)
            cast_one(sc, origin == "cmd", flashback=origin == "fb")

        for att in sorted(attachments, key=lambda a: ManaCost.parse(a[1].equip_cost).mana_value):
            if att[1].kind != "equip" or att[2] is not None:
                continue
            target = best_target()
            if target is None:
                break
            payment = _can_pay(sources, ManaCost.parse(att[1].equip_cost))
            if payment is None:
                continue
            for idx in payment:
                sources[idx].ready = False
            spent += len(payment)
            att[2] = target

        # X creatures that enter with X +1/+1 counters (Hydra class, R0.enters_counters): the
        # mana left after every other spell is X, cast once X is at least 2 (a 0/0 or a 1/1
        # for the cost is what a pilot holds it back from). {X}{X} halves it.
        for sc in sorted((c for c in hand if c.card.is_creature and R0.enters_counters(
                c.card.name, c.card.oracle_text or "")[1]), key=lambda c: c.mana_value):
            payment = _can_pay(sources, sc.card.cost)
            if payment is None:
                continue
            left = sum(1 for s in sources if s.ready) - len(payment)
            x = left // max(1, sc.card.cost.x_count)
            if x < 2:
                continue
            for idx in payment:
                sources[idx].ready = False
            paid = 0
            for s in sources:
                if s.ready and paid < x * max(1, sc.card.cost.x_count):
                    s.ready = False
                    paid += 1
            spent += len(payment) + paid
            hand.remove(sc)
            played(sc)
            cast_one(sc, x=x)

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
            hand.remove(sc)
            played(sc)
            cast_one(sc)
            damage += x
            credit(sc.card.name, "burn", x)

        # +1/+1-counter mana sinks ("{2}{G}: put a +1/+1 counter on ~", R0.sinks): spare mana,
        # never a Treasure, goes into the creature it grows -- the counter stays, so this comes
        # before the until-end-of-turn pumps below. Biggest payoff per mana first.
        growers = [(pool, i, s) for pool in (atk_board, atk_pending)
                   for i, a in enumerate(pool) for s in sinks_of.get(a[0], ()) if s.counter]
        growers.sort(key=lambda g: ManaCost.parse(g[2].cost).mana_value)
        for pool, i, s in growers:
            cost = ManaCost.parse(s.cost)
            if s.once:                              # monstrosity / adapt: once per creature
                if pool[i][0] not in once_done and cost.mana_value > 0 and pay_spare(cost):
                    spent += cost.mana_value
                    once_done.add(pool[i][0])
                    grow(pool, i, counters(s.bonus))
                continue
            while cost.mana_value > 0 and pay_spare(cost):
                spent += cost.mana_value
                grow(pool, i, counters(1))

        stats.mana_spent_by_turn.append(spent)

        # "At the beginning of combat on your turn, put N +1/+1 counters on target creature you
        # control" (R0.combat_counter): the commander if it can attack, else the strongest
        # able attacker, else the strongest summoning-sick creature.
        for kind, _src, _, v in list(statics):
            if kind != "combat_counter":
                continue
            for pool in (atk_board, atk_pending):
                if pool:
                    i = next((k for k, a in enumerate(pool) if a[3]),
                             max(range(len(pool)), key=lambda k: pool[k][1]))
                    grow(pool, i, counters(v))
                    break

        # combat: everything that was already down swings at the goldfish opponent
        rule_live = rule is not None and commander is not None and not commander_in_zone
        per_creature = anthem_noncreature + anthem_creature
        # Station (sorcery speed, so before combat) and crew: tap creatures for their power.
        # Summoning-sick creatures first (free -- they cannot attack); able attackers only when
        # what they would have dealt is less than what the Vehicle / Spacecraft adds.
        tapped: set[int] = set()
        crewed: list[tuple[str, int, int, bool]] = []
        if vehicles_board or ships:
            sick = sorted((power_of.get(a[0], 0) + per_creature for a in atk_pending),
                          reverse=True)
            sick = [p for p in sick if p > 0]
            if convoke_used:                        # tapped for convoke: weakest ones
                sick = sick[:max(0, len(sick) - convoke_used)]
            n_sick0 = len(sick)

            def tap_for(need: int, gain: int) -> bool:
                got = 0
                use_sick = 0
                while got < need and use_sick < len(sick):
                    got += sick[use_sick]
                    use_sick += 1
                use_able: list[int] = []
                lost = 0
                if got < need:
                    able = sorted(
                        ((a[2] if rule_live else a[1]) + per_creature,
                         power_of.get(a[0], 0) + per_creature, i)
                        for i, a in enumerate(atk_board)
                        if i not in tapped and not a[3] and power_of.get(a[0], 0) + per_creature > 0)
                    for dmg, pw, i in able:
                        if got >= need:
                            break
                        use_able.append(i)
                        got += pw
                        lost += dmg
                    if got < need or lost >= gain:
                        return False
                del sick[:use_sick]
                tapped.update(use_able)
                return True

            for ship in sorted(ships, key=lambda s: s["need"] - s["counters"]):
                sc = ship["sc"]
                ready_now = ship["turn"] < turn         # on the battlefield since the turn began
                gain = (sc.attack_power + per_creature) if ready_now else 0
                if tap_for(ship["need"] - ship["counters"], gain):
                    ship["counters"] = ship["need"]
                else:                                   # progress with the free (sick) ones
                    ship["counters"] += sum(sick)
                    sick.clear()
                if ship["counters"] >= ship["need"]:
                    ships.remove(ship)                  # an artifact creature from now on
                    entry = (sc.card.name, sc.attack_power, sc.attack_power_under(rule), False)
                    if ready_now:
                        board_power += sc.attack_power
                        board_power_rule += sc.attack_power_under(rule)
                        board_creatures += 1
                        atk_board.append(entry)
                    else:
                        pending_power += sc.attack_power
                        pending_power_rule += sc.attack_power_under(rule)
                        pending_creatures += 1
                        atk_pending.append(entry)
            for v in sorted(vehicles_board, key=lambda v: -v.attack_power):
                if tap_for(_crew_cost(v.card.type_line or "", v.card.oracle_text or ""),
                           v.attack_power + per_creature):
                    crewed.append((v.card.name, v.attack_power, v.attack_power_under(rule), False))
            crew_sick = n_sick0 - len(sick)         # summoning-sick creatures tapped above
        else:
            crew_sick = 0
        if any(mk.trigger in ("attack", "attack_any") for _, mk, _ in token_engines):
            attacking = {a[0] for i, a in enumerate(atk_board) if i not in tapped}
            attacking |= {c[0] for c in crewed}
            for src, mk, _ in list(token_engines):
                if (mk.trigger == "attack" and src in attacking) or (
                        mk.trigger == "attack_any" and attacking):
                    fire(src, mk, attacking=getattr(mk, "attacking", False))
        swing = board_power_rule if rule_live else board_power
        swing += max(0, per_creature * board_creatures - lord_self_active)
        stats.board_power_by_turn.append(swing)
        stats.board_creatures_by_turn.append(board_creatures)
        attackers = atk_board
        if tapped or crewed:
            attackers = [a for i, a in enumerate(atk_board) if i not in tapped] + crewed
            swing = sum(a[2] if rule_live else a[1] for a in attackers)
            swing += max(0, per_creature * len(attackers) - lord_self_active)
        # Haste from elsewhere (R0.team_haste / R0.haste_gear): a team grant lets every
        # summoning-sick creature attack (a "tokens" grant, the tokens); each haste Equipment
        # moves, for its equip cost from spare mana, onto the best summoning-sick creature (the
        # commander first). Creatures tapped for convoke or crew stay home.
        scope = {e[3] for e in statics if e[0] == "team_haste"}
        gear = [e[3] for e in statics if e[0] == "haste_gear"]
        if (scope or gear) and atk_pending:
            free_sick = list(atk_pending)
            busy = convoke_used + crew_sick
            if busy > 0:                            # the weakest were tapped
                free_sick = sorted(free_sick, key=lambda a: a[1])[busy:]
            joining = []
            if scope & {"all", "other"}:
                joining = free_sick
            elif "tokens" in scope:
                joining = [a for a in free_sick if a[0].endswith(" token")]
            rest = [a for a in free_sick if a not in joining]
            for cost in sorted(gear, key=lambda c: ManaCost.parse(c).mana_value):
                if not rest:
                    break
                pick = next((a for a in rest if a[3]), max(rest, key=lambda a: a[1]))
                if ManaCost.parse(cost).mana_value and not pay_spare(ManaCost.parse(cost)):
                    continue
                stats.mana_spent_by_turn[-1] += ManaCost.parse(cost).mana_value
                rest.remove(pick)
                joining.append(pick)
            if joining:
                attackers = list(attackers) + joining
                swing = sum(a[2] if rule_live else a[1] for a in attackers)
                swing += max(0, per_creature * len(attackers) - lord_self_active)
        # Second sweep (tier0_readers). Extort (CR 702.101): each trigger this turn paid {W/B}
        # from spare mana drains one and gains one -- noncombat, so before the combat snapshot.
        payers = [e[1] for e in statics if e[0] == "extort"]
        paid_ext = 0
        if extort_due and payers:
            wb = ManaCost.parse("{W/B}")
            while paid_ext < extort_due and pay_spare(wb):
                stats.mana_spent_by_turn[-1] += 1
                damage += 1
                credit(payers[paid_ext % len(payers)], "burn", 1)
                paid_ext += 1
                gain_life(1)
        # The combat below is measured from here, so an additional combat phase (R0.extra_combat)
        # can repeat exactly what it dealt.
        snap = (damage, dict(stats.damage_by_card), dict(stats.damage_by_source),
                dict(stats.poison_by_card))
        # Per-attacker power this combat beyond its entry: prowess (CR 702.108, noncreature
        # spells cast this turn -- all precombat in tier0), exalted (CR 702.83, an attacker
        # alone), '*' / "for each" power (R0.var_power), and spare mana into firebreathing.
        n_noncreature = sum(1 for c in cast_this_turn if not c.card.is_creature)
        exalt = (sum(e[3] for e in statics if e[0] == "exalted") if len(attackers) == 1 else 0)
        n_bodies = board_creatures + pending_creatures

        def var_count(kind: str) -> int:
            return {"land": lands_count, "creature": n_bodies, "other_creature": n_bodies - 1,
                    "artifact": n_artifacts(), "hand": len(hand)}[kind]

        dyn = []
        for a in attackers:
            b = prowess_of.get(a[0], 0) * n_noncreature + exalt
            v = varp_of.get(a[0])
            if v is not None:
                b += v.per * max(0, var_count(v.kind))
            dyn.append(b)
        if pumps_today and attackers:               # pump spells: on the commander, else the
            best = next((j for j, a in enumerate(attackers) if a[3]),   # strongest attacker
                        max(range(len(attackers)), key=lambda j: attackers[j][1]))
            dyn[best] += sum(n for _, n in pumps_today)
        pumps = sorted(((j, s) for j, a in enumerate(attackers)
                        for s in sinks_of.get(a[0], ()) if not s.counter),
                       key=lambda t: ManaCost.parse(t[1].cost).mana_value / t[1].bonus)
        for j, s in pumps:
            cost = ManaCost.parse(s.cost)
            while cost.mana_value > 0 and pay_spare(cost):
                stats.mana_spent_by_turn[-1] += cost.mana_value
                dyn[j] += s.bonus
        dyn = [b * (2 if attackers[j][0] in printed_ds else 1) for j, b in enumerate(dyn)]
        life_gained = 0
        # Infect (CR 702.90b): an infect attacker's damage is poison, not life; toxic (CR
        # 702.180) adds its poison on top of the damage. The commander's -1/-1 counters
        # (Glistening Oil) shrink its power. A deck with no infect, toxic or counters takes
        # none of these branches and deals exactly `swing`.
        n_attacking = board_creatures if attackers is atk_board else len(attackers)
        extra = max(0, per_creature * n_attacking - lord_self_active)
        infect_attackers = 0
        on: dict[str, list] = {}
        for att in attachments:
            if att[2] is not None:
                on.setdefault(att[2], []).append(att)
        for j, (name, pw, pw_rule, is_cmd) in enumerate(attackers):
            p = pw_rule if rule_live else pw
            if is_cmd and cmd_counters:
                cut = min(cmd_counters, p)
                p -= cut
                swing -= cut
            p += dyn[j]
            swing += dyn[j]
            gear = on.pop(name, [])                 # one creature of that name carries it
            shares: list[tuple[str, int]] = []
            granted_infect = any(a[1].infect for a in gear)
            if gear:
                gains_ds = any(a[1].double_strike for a in gear) and name not in printed_ds
                mult = 2 if (gains_ds or name in printed_ds) else 1
                shares = [(a[0].card.name, a[1].bonus * mult) for a in gear]
                if gains_ds:                        # the creature's own power hits twice too
                    first_ds = next(a for a in gear if a[1].double_strike)
                    shares.append((first_ds[0].card.name, p))
                swing += sum(x for _, x in shares)
            if has_infect(name, is_cmd) or granted_infect:
                infect_attackers += 1
                swing -= p + sum(x for _, x in shares)
                credit_poison(name, p)
                for src, x in shares:
                    credit_poison(src, x)
            else:
                credit(name, "commander" if is_cmd else "combat", p)
                for src, x in shares:
                    credit(src, "commander" if is_cmd else "combat", x)
                if name in lifelink_of:             # CR 702.15b (anthem share not counted)
                    life_gained += p + sum(x for _, x in shares)
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
        gain_life(life_gained)
        # Additional combat phases (CR 505.1a, R0.extra_combat): an extra-combat spell cast this
        # turn, or an attack trigger whose source is attacking, untaps the team and it all
        # happens again -- the same damage, poison and credits as the combat just measured
        # (pumps last until end of turn). Attack triggers do not fire again: an under-count.
        attacking_names = {a[0] for a in attackers}
        extra_combats = sum(1 for c in cast_this_turn if xcombat_of.get(c.card.name) == "spell")
        extra_combats += sum(1 for n, k in xcombat_of.items()
                             if (k == "attack" and n in attacking_names)
                             or (k == "attack_any" and attackers
                                 and any(e[1] == n for e in statics if e[0] == "xcombat")))
        if extra_combats and attackers:
            d_dmg = damage - snap[0]
            d_card = {k: v - snap[1].get(k, 0) for k, v in stats.damage_by_card.items()
                      if v != snap[1].get(k, 0)}
            d_src = {k: v - snap[2].get(k, 0) for k, v in stats.damage_by_source.items()
                     if v != snap[2].get(k, 0)}
            d_poison = {k: v - snap[3].get(k, 0) for k, v in stats.poison_by_card.items()
                        if v != snap[3].get(k, 0)}
            for _ in range(extra_combats):
                damage += d_dmg
                for k, v in d_card.items():
                    stats.damage_by_card[k] += v
                for k, v in d_src.items():
                    stats.damage_by_source[k] += v
                for k, v in d_poison.items():
                    credit_poison(k, v)
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
        # Aristocrats finisher: with a free sacrifice outlet (R0.free_sac_outlet) and death
        # drains (R0.death_drain) out, sacrificing every creature drains per_death each. Done
        # only when it is lethal -- before that a body is worth more attacking every turn. A
        # creature outlet is left standing (some only sacrifice "another"): an under-count.
        per_death = sum(e[3] for e in statics if e[0] == "death_drain")
        outlets = [e for e in statics if e[0] == "outlet"]
        if per_death and outlets and stats.kill_turn is None:
            bodies = board_creatures + pending_creatures - (1 if any(e[2] for e in outlets) else 0)
            if bodies > 0 and damage + per_death * bodies >= cfg.goldfish_life:
                for kind, src, _, v in list(statics):
                    if kind == "death_drain":
                        damage += v * bodies
                        credit(src, "burn", v * bodies)
        for src, mk, _ in list(token_engines):
            if mk.trigger == "end":
                fire(src, mk)
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
