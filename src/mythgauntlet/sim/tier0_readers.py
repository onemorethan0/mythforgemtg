"""Strict rules-text readers for the goldfish sim's second unmodeled-mechanics sweep (tier0).

Each reader reads ONE printed shape from the card's own text and returns None / 0 / () for
anything it cannot read exactly: a variable it does not track, a condition, an activated cost
it cannot pay. That is the honest under-count the first sweep used (tier0 docstring). The
gold sets are in tests/engine/test_tier0_sweep2.py, taken from the real cards' printed text.

No card names appear here (invariant #2): "~" stands for the card's own name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _lines(name: str, oracle_text: str) -> list[str]:
    """Own lines, reminder text stripped, lower-cased, the card's name (and its short name
    before a comma) replaced by "~"."""
    out = []
    names = sorted({n for n in (name.lower(), name.lower().split(",")[0],
                                *name.lower().split(" // ")) if n}, key=len, reverse=True)
    for ln in (oracle_text or "").splitlines():
        ln = re.sub(r"\([^)]*\)", "", ln).strip().lower()
        for n in names:
            ln = ln.replace(n, "~")
        out.append(ln)
    return out


def _keyword_line(lines: list[str], kw: str) -> int:
    """How many keyword lines print `kw` (a comma list of plain keywords: "flying, prowess")."""
    pat = re.compile(r"(?:[a-z' ]+, )*" + kw + r"(?:, [a-z' ]+)*")
    return sum(1 for ln in lines if pat.fullmatch(ln))


_SELF = r"(?:~|this creature)"
_COUNT_KINDS = {
    "lands you control": "land", "creatures you control": "creature",
    "artifacts you control": "artifact", "cards in your hand": "hand",
    "other creatures you control": "other_creature",
}


@dataclass(frozen=True)
class VarPower:
    """Power that grows with a count tier0 tracks: base + per * count(kind)."""
    kind: str       # land | creature | other_creature | artifact | hand
    per: int


@lru_cache(maxsize=8192)
def var_power(name: str, type_line: str, oracle_text: str) -> VarPower | None:
    """"~'s power (and toughness are each|is) equal to the number of <X>" (a '*' creature) or
    "~ gets +N/+M for each <X>" on a line of its own. <X> is one of the counts above; anything
    else (a graveyard, a basic land type, devotion, an opponent's board) is not read."""
    if "creature" not in (type_line or "").lower():
        return None
    for ln in _lines(name, oracle_text):
        m = re.fullmatch(_SELF + r"'s power (?:and toughness are each|is) equal to the number of "
                         r"([a-z ]+?)\.", ln)
        if m and m.group(1) in _COUNT_KINDS:
            return VarPower(_COUNT_KINDS[m.group(1)], 1)
        m = re.fullmatch(_SELF + r" gets \+(\d+)/\+\d+ for each (?:other )?([a-z ]+?)\.", ln)
        if m:
            what = m.group(2)
            other = " for each other " in ln
            key = ("other " if other else "") + what
            if key in _COUNT_KINDS:
                return VarPower(_COUNT_KINDS[key], int(m.group(1)))
            if what == "creature you control":
                return VarPower("other_creature" if other else "creature", int(m.group(1)))
            if what == "artifact you control":
                return VarPower("artifact", int(m.group(1)))
            if what == "land you control":
                return VarPower("land", int(m.group(1)))
    return None


@lru_cache(maxsize=8192)
def enters_counters(name: str, oracle_text: str) -> tuple[int, int]:
    """(fixed, per X) +1/+1 counters the card enters with (CR 122.6): "~ enters with two +1/+1
    counters on it", "... with X +1/+1 counters", "... with twice X ...". Conditional ("if",
    "for each") lines are not read."""
    fixed = per_x = 0
    for ln in _lines(name, oracle_text):
        m = re.fullmatch(r"(?:~|this [a-z]+) enters with (a|an|one|two|three|four|five|six|x"
                         r"|twice x) \+1/\+1 counters? on it\.", ln)
        if not m:
            continue
        w = m.group(1)
        if w == "x":
            per_x += 1
        elif w == "twice x":
            per_x += 2
        else:
            fixed += _NUM[w]
    return fixed, per_x


@dataclass(frozen=True)
class Sink:
    """A mana-only activated pump on the creature itself."""
    cost: str           # "{R}", "{1}{G}" ...
    bonus: int          # +N power
    counter: bool       # a +1/+1 counter (stays) rather than until end of turn
    once: bool = False  # monstrosity / adapt: N counters, once


@lru_cache(maxsize=8192)
def sinks(name: str, oracle_text: str) -> tuple[Sink, ...]:
    """"{cost}: ~ gets +N/+M until end of turn." (firebreathing) and "{cost}: put a +1/+1
    counter on ~." with a cost of mana symbols only -- no {T}, {Q}, {X}, sacrifice, discard or
    "activate only" restriction (a once-per-turn limit would be misread as unlimited).
    "{cost}: Monstrosity N." (CR 701.37) and "{cost}: Adapt N." (CR 701.46) read as N counters
    once."""
    out = []
    for ln in _lines(name, oracle_text):
        m = re.fullmatch(r"((?:\{(?:\d+|[wubrgc]|[wubrg]/[wubrg])\})+): (.+)", ln)
        if not m:
            continue
        cost, eff = m.groups()
        m3 = re.fullmatch(r"(?:monstrosity|adapt) (\d+)\.", eff)
        if m3:
            out.append(Sink(cost, int(m3.group(1)), True, True))
            continue
        m2 = re.fullmatch(_SELF + r" gets \+(\d+)/[+-]\d+ until end of turn\.", eff)
        if m2 and int(m2.group(1)) > 0:
            out.append(Sink(cost, int(m2.group(1)), False))
            continue
        if re.fullmatch(r"put a \+1/\+1 counter on " + _SELF + r"\.", eff):
            out.append(Sink(cost, 1, True))
    return tuple(out)


def prowess(name: str, oracle_text: str) -> int:
    return _keyword_line(_lines(name, oracle_text), "prowess")


def exalted(name: str, oracle_text: str) -> int:
    return _keyword_line(_lines(name, oracle_text), "exalted")


def lifelink(name: str, oracle_text: str) -> bool:
    return _keyword_line(_lines(name, oracle_text), "lifelink") > 0


def extort(name: str, oracle_text: str) -> int:
    return _keyword_line(_lines(name, oracle_text), "extort")


def convoke(name: str, oracle_text: str) -> bool:
    return _keyword_line(_lines(name, oracle_text), "convoke") > 0


def cascade(name: str, oracle_text: str) -> int:
    return _keyword_line(_lines(name, oracle_text), "cascade")


@lru_cache(maxsize=8192)
def token_doubler(name: str, oracle_text: str) -> str | None:
    """A replacement that doubles tokens you create (CR 614.1a): "all" for any token,
    "creature" for creature tokens only. "Plus an additional" / "instead create one of each"
    variants are not read."""
    for ln in _lines(name, oracle_text):
        m = re.fullmatch(r"if (?:one or more|an effect would create one or more) (creature )?"
                         r"tokens would be created(?: under your control)?, twice that many of "
                         r"those tokens are created instead\.", ln) or re.fullmatch(
            r"if an effect would create one or more (creature )?tokens under your control, it "
            r"creates twice that many of those tokens instead\.", ln)
        if m:
            return "creature" if m.group(1) else "all"
    return None


@lru_cache(maxsize=8192)
def counter_mod(name: str, oracle_text: str) -> str | None:
    """+1/+1 counter replacements on your creatures: "plus" (that many plus one -- Hardened
    Scales) or "twice" (Corpsejack / Doubling Season / Branching Evolution wording)."""
    for ln in _lines(name, oracle_text):
        m = re.fullmatch(
            r"if (?:one or more (?:\+1/\+1 )?counters would be put on|an effect would put one or "
            r"more counters on|you would put one or more counters on) (?:a creature|a permanent|"
            r"a creature or planeswalker|a creature, spacecraft, or planet|a permanent or player|"
            r"an artifact or creature)(?: you control)?"
            r"(?: or on yourself| or player)?, (?:it puts |put )?(that many plus one|twice that "
            r"many)\b.*", ln)
        if m:
            return "plus" if m.group(1) == "that many plus one" else "twice"
    return None


@lru_cache(maxsize=8192)
def extra_combat(name: str, type_line: str, oracle_text: str) -> str | None:
    """An additional combat phase (CR 505.1a): "spell" for an instant/sorcery that grants one
    after this phase, "attack" for a creature whose first-combat attack trigger untaps your
    creatures and adds one (once a turn by its own "first combat phase" clause). Anything with
    a cost, a condition or a different timing is not read."""
    tl = (type_line or "").lower()
    text = " ".join(_lines(name, oracle_text))
    spell_like = ("instant" in tl or "sorcery" in tl
                  or re.search(r"when (?:~|this [a-z]+) enters, untap", text))
    if spell_like and re.search(
            r"untap (?:all|each) creatures? (?:you control|that attacked this turn)(?: that "
            r"attacked this turn)?\. (?:if it's your main phase, )?(?:after this (?:main )?phase, )?"
            r"there is an additional combat phase", text):
        return "spell"
    if "creature" in tl and re.search(
            r"whenever ~ attacks(?: for the first time each turn)?, (?:if it's the first combat "
            r"phase of the turn, )?untap all creatures you control\. after this phase, there is "
            r"an additional combat phase\.", text):
        return "attack"
    if "creature" in tl and re.search(
            r"whenever you attack, if it's the first combat phase of the turn, untap all "
            r"attacking creatures\.[^.]*\. after this phase, there is an additional combat "
            r"phase\.", text):
        return "attack_any"
    return None


@lru_cache(maxsize=8192)
def gain_drain(name: str, oracle_text: str) -> int | None:
    """"Whenever you gain life, <opponent> loses that much life" -> 0 (that much), or a fixed
    "... loses N life" -> N. None when the card has neither."""
    for ln in _lines(name, oracle_text):
        m = re.fullmatch(r"whenever you gain life, (?:each opponent|target opponent|target player)"
                         r" loses (that much|\d+) life\.", ln)
        if m:
            return 0 if m.group(1) == "that much" else int(m.group(1))
    return None


@lru_cache(maxsize=8192)
def death_drain(name: str, oracle_text: str) -> int:
    """"Whenever this creature or another creature (you control) dies / a creature you control
    dies, <opponent(s)> lose N life" (Blood Artist / Zulaport class): N per creature death."""
    for ln in _lines(name, oracle_text):
        m = re.fullmatch(r"whenever (?:" + _SELF + r" or another creature(?: you control)?|"
                         r"(?:a|another) creature(?: you control)?) dies, (?:each opponent|"
                         r"target opponent|target player) loses (\d+) life(?: and you gain \d+ "
                         r"life)?\.", ln)
        if m:
            return int(m.group(1))
    return 0


@lru_cache(maxsize=8192)
def free_sac_outlet(name: str, oracle_text: str) -> bool:
    """"Sacrifice a/another creature: <effect>." with no other cost (Viscera Seer, Ashnod's
    Altar, Carrion Feeder class)."""
    return any(re.fullmatch(r"sacrifice (?:a|another) creature: [^:]+", ln)
               for ln in _lines(name, oracle_text))


@lru_cache(maxsize=8192)
def is_clone(name: str, type_line: str, oracle_text: str) -> bool:
    """"You may have ~ enter as a copy of any creature on the battlefield" (Clone class),
    including copies "of a creature you control"; "except ..." riders are ignored."""
    if "creature" not in (type_line or "").lower():
        return False
    return any(re.match(r"you may have (?:~|this creature) enter as a copy of (?:any|a) "
                        r"creature(?: on the battlefield| you control)", ln)
               for ln in _lines(name, oracle_text))


@lru_cache(maxsize=8192)
def one_shot_mana(name: str, oracle_text: str) -> int:
    """"{T}, Sacrifice ~: Add one mana of any color." (Lotus Petal class): one any-colour mana,
    once, usable the turn it arrives."""
    return sum(1 for ln in _lines(name, oracle_text)
               if re.fullmatch(r"\{t\}, sacrifice (?:~|this artifact): add one mana of any "
                               r"color\.", ln))


@lru_cache(maxsize=8192)
def aura_ramp(name: str, type_line: str, oracle_text: str) -> tuple[int, frozenset[str]]:
    """A land Aura that adds mana whenever the land is tapped (Wild Growth, Utopia Sprawl,
    Overgrowth): (extra mana, colours). Colours are the printed symbols, or WUBRG for "any"."""
    if "aura" not in (type_line or "").lower():
        return 0, frozenset()
    for ln in _lines(name, oracle_text):
        m = re.fullmatch(r"whenever enchanted (?:land|forest|plains|island|swamp|mountain) is "
                         r"tapped for mana, its controller adds an additional (.+?)(?: \(in "
                         r"addition to the mana the land produces\))?\.", ln)
        if not m:
            continue
        what = m.group(1)
        syms = re.findall(r"\{([wubrgc])\}", what)
        if syms and re.fullmatch(r"(?:\{[wubrgc]\})+", what):
            return len(syms), frozenset(s.upper() for s in syms)
        if what in ("one mana of any color", "one mana of the chosen color",
                    "one mana of any type that land produced"):
            return 1, frozenset("WUBRG")
        if what == "two mana in any combination of colors":
            return 2, frozenset("WUBRG")
    return 0, frozenset()


@lru_cache(maxsize=8192)
def var_draw(name: str, type_line: str, oracle_text: str) -> str | None:
    """A one-shot draw sized by the board, on a spell or an enters trigger: "draw a card for
    each creature you control" / "draw cards equal to the number of creatures you control" ->
    "creature"; "... equal to the greatest power among creatures you control" -> "power"."""
    tl = (type_line or "").lower()
    spell = "instant" in tl or "sorcery" in tl
    for ln in _lines(name, oracle_text):
        m = re.fullmatch(r"(when (?:~|this [a-z]+) enters, )?draw (?:a card for each creature "
                         r"you control|cards equal to the (number of creatures you control|"
                         r"greatest power among creatures you control))\.", ln)
        if not m or (not m.group(1) and not spell):
            continue
        return "power" if m.group(2) and "greatest power" in m.group(2) else "creature"
    return None


@lru_cache(maxsize=8192)
def affinity_artifacts(name: str, oracle_text: str) -> bool:
    """Affinity for artifacts (CR 702.41) or its spelled-out form."""
    lines = _lines(name, oracle_text)
    return (_keyword_line(lines, "affinity for artifacts") > 0
            or any(re.fullmatch(r"this spell costs \{1\} less to cast for each artifact you "
                                r"control\.", ln) for ln in lines))


@lru_cache(maxsize=8192)
def flashback_cost(name: str, type_line: str, oracle_text: str) -> str | None:
    """A mana-only flashback cost (CR 702.34) on an instant or sorcery; a flashback that also
    asks for life, a sacrifice or a discard is not read."""
    tl = (type_line or "").lower()
    if not ("instant" in tl or "sorcery" in tl):
        return None
    for ln in _lines(name, oracle_text):
        m = re.fullmatch(r"flashback ((?:\{(?:\d+|[wubrgc])\})+)", ln)
        if m:
            return m.group(1)
    return None


# --- typed lords (2026-11-09 mentor review) ---------------------------------------------------

@dataclass(frozen=True)
class TypedAnthem:
    """"<Type> creatures you control get +N/+M" / "Other <Types> you control get +N/+M": +power
    to your attackers of that type. `kind` is "artifact" (the card type) or "subtype"."""
    kind: str
    word: str           # "artifact", or the subtype as printed, lower-case ("elves", "goblin")
    power: int
    others: bool        # "Other ..." -- the source itself is not buffed


_NOT_A_TYPE = frozenset({"creatures", "creature", "tokens", "creature tokens", "nontoken",
                         "nontoken creatures", "attacking", "blocking", "tapped", "untapped",
                         "legendary", "white", "blue", "black", "red", "green", "colorless",
                         "multicolored", "monocolored", "modified", "equipped", "enchanted"})


@lru_cache(maxsize=8192)
def typed_anthems(name: str, oracle_text: str) -> tuple[TypedAnthem, ...]:
    """Type-restricted power anthems on a line of their own, read strictly: one type word, a
    fixed +N, nothing after but an optional keyword grant. "Artifact creatures you control get
    +2/+2" (Tempered Steel), "Other Elves you control get +1/+1", "Goblin creatures you control
    get +1/+1". Two types ("Elves and Goblins"), colours, "for each", conditions and grants with
    no power are not read. Generic "creatures you control" is parse_anthem's, not this."""
    out = []
    for ln in _lines(name, oracle_text):
        m = re.fullmatch(r"(other )?([a-z'-]+)(?: creatures)? you control get \+(\d+)/[+-]\d+"
                         r"(?: and have [a-z ,]+)?\.", ln)
        if not m:
            continue
        word = m.group(2)
        if word in _NOT_A_TYPE or int(m.group(3)) <= 0:
            continue
        if not ln.split(" you control")[0].endswith("creatures") and not word.endswith("s"):
            continue                            # "Other Elf you control" is not a printed form
        kind = "artifact" if word == "artifact" else "subtype"
        out.append(TypedAnthem(kind, word, int(m.group(3)), bool(m.group(1))))
    return tuple(out)


def type_matches(anthem: TypedAnthem, type_line: str, keywords=()) -> bool:
    """Whether a creature with this type line gets the typed anthem (changeling: every type)."""
    tl = (type_line or "").lower()
    main, _, subs = tl.partition("—")
    if anthem.kind == "artifact":
        return "artifact" in main
    if any(k.lower() == "changeling" for k in (keywords or ())):
        return True
    w = anthem.word
    negated = w.startswith("non-")              # Mikaeus: "Other non-Human creatures ..."
    w = w[4:] if negated else w
    cands = {w, w[:-1], w[:-2], w[:-3] + "f", w[:-3] + "fe"}   # goblins, foxes?, elves, knives
    has = bool(cands & set(subs.split()))
    return not has if negated else has


# --- third sweep ------------------------------------------------------------------------------

@lru_cache(maxsize=8192)
def haste_gear(name: str, type_line: str, oracle_text: str) -> str | None:
    """An Equipment that grants haste and no power (Lightning Greaves, Swiftfoot Boots class):
    its plain "Equip {cost}". A pump Equipment is tier0's _attachment and is not read here."""
    if "equipment" not in (type_line or "").lower():
        return None
    lines = _lines(name, oracle_text)
    if not any(re.fullmatch(r"equipped creature has (?:[a-z ,]+(?:,| and) )?haste(?:(?:,| and) "
                            r"[a-z ,]+)?\.", ln) for ln in lines):
        return None
    if any(re.match(r"equipped creature gets [+-]", ln) for ln in lines):
        return None
    for ln in lines:
        m = re.fullmatch(r"equip ((?:\{(?:\d+|[wubrgc])\})+)", ln)
        if m:
            return m.group(1)
    return None


@lru_cache(maxsize=8192)
def team_haste(name: str, oracle_text: str) -> str | None:
    """A static haste grant to your team (CR 702.10): "all" -- "creatures you control have
    haste", "all creatures have haste", "other creatures you control have haste"; "tokens" --
    "creature tokens you control have haste". A typed grant ("other Goblins") is not read."""
    for ln in _lines(name, oracle_text):
        if re.fullmatch(r"creatures you control have haste\.|all creatures have haste\.", ln):
            return "all"
        if re.fullmatch(r"other creatures you control have haste\.", ln):
            return "other"
        if re.fullmatch(r"creature tokens you control have haste\.", ln):
            return "tokens"
    return None


def storm(name: str, oracle_text: str) -> int:
    return _keyword_line(_lines(name, oracle_text), "storm")


@lru_cache(maxsize=8192)
def storm_damage(name: str, oracle_text: str) -> int:
    """A storm spell's own "~ deals N damage to any target" (Grapeshot): with storm the copies
    go at the face; tier0's effect reader leaves a lone spell's "any target" for creatures."""
    if not storm(name, oracle_text):
        return 0
    for ln in _lines(name, oracle_text):
        m = re.fullmatch(r"~ deals (\d+) damage to any target\.", ln)
        if m:
            return int(m.group(1))
    return 0


@lru_cache(maxsize=8192)
def pump_spell(name: str, type_line: str, oracle_text: str) -> int:
    """An instant/sorcery whose whole first line is "Target creature (you control) gets +N/+M
    until end of turn." (a following "It gains ..." keyword clause allowed): +N to an attacker
    this turn. A modal, an X or a "for each" pump is not read."""
    tl = (type_line or "").lower()
    if not ("instant" in tl or "sorcery" in tl):
        return 0
    lines = [ln for ln in _lines(name, oracle_text) if ln]
    if not lines:
        return 0
    m = re.fullmatch(r"target creature(?: you control)? gets \+(\d+)/\+\d+(?: and gains "
                     r"[a-z ,]+)? until end of turn\.(?: (?:it|that creature) gains [a-z ,]+ "
                     r"until end of turn\.| untap (?:it|that creature)\.)?", lines[0])
    return int(m.group(1)) if m else 0


@lru_cache(maxsize=8192)
def fabricate(name: str, oracle_text: str) -> int:
    """Fabricate N (CR 702.123): read as N +1/+1 counters on the creature (the choice of
    Servo tokens instead is not modeled)."""
    for ln in _lines(name, oracle_text):
        m = re.fullmatch(r"fabricate (\d+)", ln)
        if m:
            return int(m.group(1))
    return 0


def living_weapon(name: str, oracle_text: str) -> bool:
    """Living weapon (CR 702.92): a 0/0 Germ token enters and the Equipment attaches to it."""
    return _keyword_line(_lines(name, oracle_text), "living weapon") > 0


@lru_cache(maxsize=8192)
def combat_counter(name: str, oracle_text: str) -> int:
    """"At the beginning of combat on your turn, put a/N +1/+1 counter(s) on target creature you
    control." -> N, once a turn on your best attacker."""
    for ln in _lines(name, oracle_text):
        m = re.fullmatch(r"at the beginning of combat on your turn, put (a|one|two|three) \+1/\+1 "
                         r"counters? on (?:(?:up to one )?(?:another )?target creature you "
                         r"control|this creature|~)\.(?: it gains [a-z ,]+ until end of turn\.)?", ln)
        if m:
            return _NUM[m.group(1)]
    return 0
