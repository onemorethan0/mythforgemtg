"""Commander lens: how the deck's commander changes what a card does.

Pure and offline. A commander can make a card mean something it does not mean in a vacuum
(Smaug the Impenetrable is indestructible, so Wrath of God is a one-sided wipe for his deck).
Each *kind* of interaction contributes facts for a card; `facts_for` merges them into one
`LensFacts`. A commander matching no kind yields an empty lens and byte-identical output.

Honest under-count: when a matcher cannot be sure (an unknown qualifier, an ambiguous face)
it claims nothing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from mythgauntlet.model.card import Card
from mythgauntlet.semantics import tags

KIND_SURVIVES_WIPE = "survives_wipe"

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
        if m.group(1) in type_words:
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
        if (mode in _INDESTRUCTIBLE_SURVIVES and tags._hits_creature(obj)
                and admits(obj, lead) is True):
            return LensFacts(
                wipe_one_sided=True,
                reason=f"{lead.name} survives this (indestructible)",
            )
    return LensFacts()


_FACT_FUNCS = {KIND_SURVIVES_WIPE: _survives_wipe_facts}


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
    return CommanderLens(cmds, tuple(kinds), ctx)
