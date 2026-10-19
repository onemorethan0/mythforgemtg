"""Commander lens: how the deck's commander changes what a card does.

Pure and offline. A commander can make a card mean something it does not mean in a vacuum
(Smaug the Impenetrable is indestructible, so Wrath of God is a one-sided wipe for his deck).
Each *kind* of interaction contributes facts for a card; `facts_for` merges them into one
`LensFacts`. A commander matching no kind yields an empty lens and byte-identical output.

Honest under-count: when a matcher cannot be sure (an unknown qualifier, an ambiguous face)
it claims nothing.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from mythgauntlet.model.card import Card, ManaCost
from mythgauntlet.semantics import tags

KIND_SURVIVES_WIPE = "survives_wipe"
KIND_DAMAGE_TO_SELF = "damage_to_self_payoff"
KIND_DEATH_PAYOFF = "death_payoff"

# Wipe modes an indestructible commander survives.
_INDESTRUCTIBLE_SURVIVES = frozenset({"destroy", "damage"})

_ALLOWED_WORDS = frozenset({
    "each", "all", "other", "creature", "creatures", "permanent", "permanents",
    "nonland", "nontoken",
})
_NON_RE = re.compile(r"\bnon-?([a-z]+)")
_WITHOUT_RE = re.compile(r"\bwithout ([a-z]+)")
_HEAD_CUT_RE = re.compile(r" and each |,|\.")


@dataclass(frozen=True)
class LensFacts:
    wipe_one_sided: bool = False
    payoff_kind: str | None = None
    payoff_treasure: int = 0
    reason: str = ""

    @property
    def empty(self) -> bool:
        return self == LensFacts()


@dataclass(frozen=True)
class LensDeckContext:
    mana_by_turn: tuple[int, ...]
    avg_commander_turn: float | None
    counter_reserve: int


_COLOUR_WORDS = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}


def _is_own_colour(word: str, commander: Card) -> bool:
    """"nonred" / "that isn't red" excludes a commander that is red (Strafe cannot target
    Smaug; Kaervek's Hex's "each nonblack creature" misses him). Card colours, not identity."""
    letter = _COLOUR_WORDS.get(word)
    return letter is not None and letter in (commander.colors or ())


def admits(obj: str, commander: Card) -> bool | None:
    """Does a wipe's object phrase include this commander? True/False only when certain;
    None means unknown (treated as no claim)."""
    head = _HEAD_CUT_RE.split(obj.casefold(), maxsplit=1)[0]
    if "opponent" in head or "you don't control" in head:
        return False
    type_words = set(re.findall(r"[a-z]+", (commander.type_line or "").casefold()))
    for m in _WITHOUT_RE.finditer(head):
        if m.group(1) in commander.keywords:
            return False
    for m in _NON_RE.finditer(head):
        if m.group(1) in type_words or _is_own_colour(m.group(1), commander):
            return False
    rest = _WITHOUT_RE.sub(" ", head)
    rest = _NON_RE.sub(lambda m: " nonland " if m.group(1) == "land" else " ", rest)
    # "nontoken"/"nonland" were consumed above; re-admit them as allowed qualifiers.
    for word in re.findall(r"[a-z']+", rest):
        if word not in _ALLOWED_WORDS:
            return None
    return True


def _wipe_clauses(text: str):
    """Yield (mode, object) for each mass destroy/exile/damage clause over cleaned text."""
    for m in tags._WIPE_ALL_RE.finditer(text):
        verb = "exile" if text.startswith("exile", m.start()) else "destroy"
        if verb == "exile" and tags._flickers(text, m.start()):
            continue
        yield verb, m.group(1)
    for m in tags._DAMAGE_EACH_RE.finditer(text):
        yield "damage", m.group(1)


def _survives_wipe_facts(lens: CommanderLens, card: Card) -> LensFacts:
    lead = lens.commanders[0]
    text = tags._clean_text(card)
    for mode, obj in _wipe_clauses(text):
        if (lens.survives_mode(mode) and tags._hits_creature(obj)
                and admits(obj, lead) is True):
            return LensFacts(
                wipe_one_sided=True,
                reason=f"{lead.name} survives this (indestructible)",
            )
    return LensFacts()


_DAMAGE_TO_SELF_RE = re.compile(
    r"whenever (?P<subj>[^.]+?) is dealt (?P<nc>noncombat )?damage"
)
_DEALS_AMOUNT_RE = re.compile(r"\bdeals? (\d+|x) damage")
_NO_ARTICLE = frozenset({"the", "a", "an"})


def lens_self_names(card: Card) -> tuple[str, ...]:
    """Every way the card's own text names it: `tags._self_names`, a legendary's first word
    ("smaug" for "Smaug the Impenetrable") and "this creature"."""
    names = set(tags._self_names(card))
    if "legendary" in (card.type_line or "").casefold():
        words = (card.name or "").split(" // ")[0].split()
        if words:
            first = words[0].strip(",").casefold()
            if first and first not in _NO_ARTICLE:
                names.add(first)
    names.add("this creature")
    return tuple(sorted(names, key=len, reverse=True))


def _damage_to_self(card: Card) -> tuple[bool, bool] | None:
    """(noncombat_only, makes_treasure) if the card says 'whenever <itself> is dealt damage',
    else None. The subject must be the card itself (Kazarov's 'a creature an opponent
    controls' is not)."""
    names = lens_self_names(card)
    for line in tags._clean_text(card).split("\n"):
        for m in _DAMAGE_TO_SELF_RE.finditer(line):
            if m.group("subj").strip() not in names:
                continue
            rest = line[m.end():].split(".")[0]
            return bool(m.group("nc")), "treasure" in rest
    return None


def x_budget(card: Card, ctx: LensDeckContext | None) -> int:
    """X the deck can pay when the commander is expected to be out: floor(mana that turn)
    minus the card's mana value minus the counter reserve, clamped at 0. No context, or a
    commander never cast in the sim, gives 0."""
    if ctx is None or ctx.avg_commander_turn is None or not ctx.mana_by_turn:
        return 0
    t = min(math.ceil(ctx.avg_commander_turn) + 1, len(ctx.mana_by_turn))
    if t < 1:
        return 0
    return max(0, math.floor(ctx.mana_by_turn[t - 1]) - card.mana_value - ctx.counter_reserve)


def _mana_x(card: Card, text: str, ctx: LensDeckContext | None) -> int:
    """X credit for a mass-damage clause: the mana budget only when X is paid as mana on
    casting ({X} in the cost). "Where X is the number of creatures" (Chain Reaction) is not
    a mana X and its value is unknown here, so it credits 0."""
    if "{x}" not in (card.mana_cost_str or "").casefold() or "where x is" in text:
        return 0
    return x_budget(card, ctx)


_COST_SYMBOL_RE = re.compile(r"\{([^}]+)\}")


def _net_of_activation(text: str, pos: int, amount: int) -> int:
    """Treasure net of the mana an activated ability pays for it. Pestilence's
    "{B}: ... 1 damage to each creature" turns {B} into one Treasure (no ramp); Mjolnir's
    "{2}{R}, Discard this card: ... 2 damage" loses mana. An {X} activation is unknown: 0."""
    line_start = text.rfind("\n", 0, pos) + 1
    prefix = text[line_start:pos]
    if ":" not in prefix:
        return amount
    cost = prefix.split(":", 1)[0]
    syms = [s for s in _COST_SYMBOL_RE.findall(cost) if s not in ("t", "q", "e")]
    if not syms:
        return amount
    if "x" in syms:
        return 0
    mv = ManaCost.parse("".join("{%s}" % s.upper() for s in syms)).mana_value
    return max(0, amount - int(mv))


_TARGET_HEAD_CUT_RE = re.compile(r" and |,|\.|\n")
_EXCLUDED_TYPE_RE = re.compile(r"(?:isn't|is not) an? ([a-z]+)|\bnon-?([a-z]+)")


def _target_excludes(text: str, start: int, commander: Card) -> bool:
    """Does the targeted object's own clause rule this commander out? "any target that
    isn't a Dragon" cannot hit Smaug; "target creature an opponent controls" cannot hit the
    pilot's own commander."""
    head = _TARGET_HEAD_CUT_RE.split(text[start:], maxsplit=1)[0]
    if "opponent" in head or "you don't control" in head:
        return True
    type_words = set(re.findall(r"[a-z]+", (commander.type_line or "").casefold()))
    for m in _EXCLUDED_TYPE_RE.finditer(head):
        word = m.group(1) or m.group(2)
        if (word in type_words or word.rstrip("s") in type_words
                or _is_own_colour(word, commander)):
            return True
    return False


def _damage_payoff_facts(lens: CommanderLens, card: Card) -> LensFacts:
    text = tags._clean_text(card)
    parts: list[LensFacts] = []
    for cmd in lens.commanders:
        info = _damage_to_self(cmd)
        if info is None:
            continue
        _noncombat_only, makes_treasure = info
        # Nothing on a card's text is combat damage, so noncombat_only never filters here.
        label = f"{cmd.name} is dealt this damage"
        hit = False
        treasure = 0
        for m in tags._DAMAGE_EACH_RE.finditer(text):
            if admits(m.group(1), cmd) is not True:
                continue
            hit = True
            if makes_treasure:
                # The match starts at "deals ... damage"; "equal to ..." has no number -> 0.
                amt = _DEALS_AMOUNT_RE.match(text, m.start())
                if amt is not None:
                    n = amt.group(1)
                    amount = _mana_x(card, text, lens.ctx) if n == "x" else int(n)
                    treasure = max(treasure, _net_of_activation(text, m.start(), amount))
        if not hit:
            for m in tags._DAMAGE_TARGET_RE.finditer(text):
                obj = m.group(1)
                if not (obj in ("any target", "targets") or tags._hits_creature(obj)):
                    continue
                if _target_excludes(text, m.start(1), cmd):
                    continue
                hit = True
            for m in tags._FIGHT_RE.finditer(text):
                if tags._hits_creature(m.group(1)):
                    hit = True
        if hit:
            parts.append(LensFacts(
                wipe_one_sided=False,
                payoff_kind=KIND_DAMAGE_TO_SELF,
                payoff_treasure=treasure,
                reason=label,
            ))
    return _merge(parts)


_DEATH_TRIGGER_RE = re.compile(
    r"whenever (?:a|another|one or more)(?: other)?(?: nontoken)? creatures?"
    r"(?: or planeswalkers?)? you control (?:dies|die)"
    r"|whenever (?:this creature or )?another creature dies"
)
_SELF_DEATH_TMPL = r"whenever (?:{names}) or another creature(?: you control)? dies"
_SAC_OUTLET_RE = re.compile(r"sacrifice (?:a|another) creature:")
# Wipe modes that make creatures DIE. Bounce and exile move them without a death.
_DEATH_MODES = frozenset({"destroy", "damage", "minus", "static_minus", "edict"})


def _death_trigger_line(card: Card) -> str | None:
    """Per line over cleaned text: the line holding an own-creature (or any-creature) death
    trigger, or None. A line naming "an opponent controls" is rejected."""
    names = "|".join(re.escape(n) for n in lens_self_names(card))
    self_re = re.compile(_SELF_DEATH_TMPL.format(names=names))
    for line in tags._clean_text(card).split("\n"):
        if "an opponent controls" in line:
            continue
        if _DEATH_TRIGGER_RE.search(line) or self_re.search(line):
            return line
    return None


def _death_trigger(card: Card) -> bool:
    return _death_trigger_line(card) is not None


def _needs_counters(trigger_line: str) -> bool:
    """Reyhan's "if it had one or more +1/+1 counters on it": only countered creatures pay
    off, so a wipe of creatures "with no counters" triggers nothing."""
    return re.search(r"if it had [^.]*counters?", trigger_line) is not None


def _opponent_only(obj: str) -> bool:
    head = _HEAD_CUT_RE.split(obj.casefold(), maxsplit=1)[0]
    return "opponent" in head or "you don't control" in head


def _scope_known(obj: str, needs_counters: bool) -> bool:
    """A "chosen" back-reference (Druid of Purification's "each permanent chosen this way",
    Season of Gathering's "permanents of the chosen type") sets its scope elsewhere, so the
    pilot's creatures are not known to die: no claim. A counter-conditioned trigger is not
    paid off by a wipe of creatures "with no counters"."""
    head = _HEAD_CUT_RE.split(obj.casefold(), maxsplit=1)[0]
    if "chosen" in head:
        return False
    return not (needs_counters and "no counters" in head)


def _kills_own_creatures(text: str, modes: frozenset[str], needs_counters: bool = False) -> bool:
    """Some death-causing wipe clause reaches the pilot's own creatures. `interaction_modes`
    does not carry the object, so each mode's clause is re-found and an opponent-only object
    ("destroy all nonland permanents your opponents control") is rejected. Unknown qualifiers
    still count: the pilot's creatures die in the clause's own scope."""
    for mode, obj in _wipe_clauses(text):
        if (mode in modes and mode in _DEATH_MODES and tags._hits_creature(obj)
                and not _opponent_only(obj) and _scope_known(obj, needs_counters)):
            return True
    for m in tags._MINUS_ALL_RE.finditer(text):
        obj = next(g for g in m.groups() if g)
        if ({"minus", "static_minus"} & modes and tags._hits_creature(obj)
                and not _opponent_only(obj) and _scope_known(obj, needs_counters)):
            return True
    for m in tags._EDICT_RE.finditer(text):
        # Only a symmetrical "each player sacrifices all ..." makes the pilot sacrifice too.
        if ("edict" in modes and m.group(0).startswith("each player")
                and m.group(1).startswith("all ") and tags._hits_creature(m.group(1))
                and _scope_known(m.group(1), needs_counters)):
            return True
    return False


def _death_payoff_facts(lens: CommanderLens, card: Card) -> LensFacts:
    cmds = [(c, line) for c in lens.commanders
            if (line := _death_trigger_line(c)) is not None]
    if not cmds:
        return LensFacts()
    text = tags._clean_text(card)
    modes = tags.interaction_modes(text).wipe & _DEATH_MODES
    sac_outlet = _SAC_OUTLET_RE.search(text) is not None
    for cmd, line in cmds:
        if sac_outlet or (modes and _kills_own_creatures(text, modes, _needs_counters(line))):
            return LensFacts(
                payoff_kind=KIND_DEATH_PAYOFF,
                reason=f"{cmd.name} pays off your creatures dying",
            )
    return LensFacts()


_FACT_FUNCS = {
    KIND_SURVIVES_WIPE: _survives_wipe_facts,
    KIND_DAMAGE_TO_SELF: _damage_payoff_facts,
    KIND_DEATH_PAYOFF: _death_payoff_facts,
}


def _merge(parts: Iterable[LensFacts]) -> LensFacts:
    one_sided = False
    payoff_kind: str | None = None
    treasure = 0
    reasons: list[str] = []
    for f in parts:
        if f.empty:
            continue
        one_sided = one_sided or f.wipe_one_sided
        payoff_kind = payoff_kind or f.payoff_kind
        treasure = max(treasure, f.payoff_treasure)
        if f.reason:
            reasons.append(f.reason)
    return LensFacts(one_sided, payoff_kind, treasure, "; ".join(reasons))


@dataclass(frozen=True)
class CommanderLens:
    commanders: tuple[Card, ...]
    kinds: tuple[str, ...]
    ctx: LensDeckContext | None

    def facts_for(self, card: Card) -> LensFacts:
        if not self.kinds:
            return LensFacts()
        return _merge(_FACT_FUNCS[k](self, card) for k in self.kinds if k in _FACT_FUNCS)

    def survives_mode(self, mode: str) -> bool:
        """Does the LEAD commander survive a wipe of this mode? (Partner is not on the table
        for a wipe the lead is the one fielded against.)"""
        if not self.commanders:
            return False
        return ("indestructible" in self.commanders[0].keywords
                and mode in _INDESTRUCTIBLE_SURVIVES)

    def flagged(self, cards: Iterable[Card]) -> set[str]:
        return {c.name for c in cards if not self.facts_for(c).empty}


def build_lens(commanders: Sequence[Card], ctx: LensDeckContext | None = None) -> CommanderLens:
    cmds = tuple(commanders)
    kinds: list[str] = []
    if any("indestructible" in c.keywords for c in cmds):
        kinds.append(KIND_SURVIVES_WIPE)
    if any(_damage_to_self(c) is not None for c in cmds):
        kinds.append(KIND_DAMAGE_TO_SELF)
    if any(_death_trigger(c) for c in cmds):
        kinds.append(KIND_DEATH_PAYOFF)
    return CommanderLens(cmds, tuple(kinds), ctx)
