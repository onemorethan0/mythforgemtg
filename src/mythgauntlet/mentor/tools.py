"""The Deck Mentor's tool contract (docs/SPEC_deck_mentor.md): the model's ONLY way to
assert anything. No tool call, no claim -- the gate (`mentor.gate`) enforces that every
card name, number and rule citation in a reply traces back to a `ToolResult` from this
turn, so this module's job is to make each result carry an honest claim budget alongside
whatever it hands the model to read.

Numbers are licensed GENEROUSLY and automatically: `_numbers_in` walks a result's data
recursively and extracts every literal number, including ones embedded in a string (an
oracle-text cost, a rule's own cross-reference to another rule) -- same bias as
`swap_narrative.allowed_numbers`, "an anti-fabrication check, not a style rule." Card
names and rule citations are NOT auto-derived (a name is just a string; guessing which
strings are card names would either miss real ones or false-positive on prose) -- each
tool states explicitly which names/rule-numbers its own result licenses.

Five tools are deterministic/offline (no simulation): `lookup_card`, `lookup_rulings`,
`search_rules`, `get_rule`, `get_deck_stats`. One, `assess_card`, runs a real simulation
(`ratings.card_impact.assess_card`) and is measurably slower (a few seconds, bounded by
`cut_pool`) -- documented, not hidden, same as `advisor.advise`'s own latency notes.

Deferred out of Phase 1 on purpose: `suggest_swap` (`advisor.advise`'s full sweep,
`max_eval x cut_pool` re-simulations, tens of seconds even conservatively bounded) adds
mostly the same tool-loop/gate integration `assess_card` already proves, for a much
higher latency cost per call. Worth adding once the loop is proven, not before.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, fields, is_dataclass

from mythgauntlet.data import rulings as rulings_data
from mythgauntlet.data.scryfall import CardDb
from mythgauntlet.model.deck import ResolvedDeck
from mythgauntlet.ratings import card_impact, manabase, redundancy
from mythgauntlet.semantics.store import SemanticsStore
from mythgauntlet.sim.tier0 import SimConfig

## `(?<![\d.])` guards the leading `-?`: without it, a mana-curve range like "2-4" scans
## as TWO tokens, "2" and "-4", because the hyphen is a range separator, not a minus sign
## -- found live 2026-08-25 (mentor_bench.py against a real deck), where a correct "2-4
## mana range" answer was gate-rejected three times over for citing a nonexistent "-4".
## A genuine negative number ("lost 3 life, down to -4") still matches fine, since its
## preceding character is a space/letter, not a digit or dot.
NUM_RE = re.compile(r"(?<![\d.])-?\d+(?:\.\d+)?")
RULE_NUM_RE = re.compile(r"\b\d{3}\.\d+[a-z]?\b")

# Spelled-out numbers a model reaches for just as often as digits ("about thirty ramp
# sources", "a dozen creatures") -- without this, the numeric leg of the gate (mentor.gate
# checks every number `extract_numbers` finds against the tool-result budget) is trivially
# bypassed by writing the number as a word instead of a digit. Deliberately small (zero
# through twenty, plus dozen/hundred): this is a word-lookup, not a number parser, and the
# module docstring's "deliberately generous" bias means missing "thirty-seven" is an
# acceptable under-count, not a hole worth a full text-to-number grammar for.
_WORD_NUMBERS: dict[str, float] = {
    "zero": 0.0, "one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0,
    "six": 6.0, "seven": 7.0, "eight": 8.0, "nine": 9.0, "ten": 10.0,
    "eleven": 11.0, "twelve": 12.0, "thirteen": 13.0, "fourteen": 14.0,
    "fifteen": 15.0, "sixteen": 16.0, "seventeen": 17.0, "eighteen": 18.0,
    "nineteen": 19.0, "twenty": 20.0, "dozen": 12.0, "hundred": 100.0,
}
WORD_NUM_RE = re.compile(
    r"\b(" + "|".join(sorted(_WORD_NUMBERS, key=len, reverse=True)) + r")\b", re.IGNORECASE
)


# A repeated mana symbol in oracle text ("{C}{C}") is a count the model may honestly
# translate to English ("two colorless mana") even though no literal digit "2" appears
# anywhere in the raw tool data -- found live 2026-08-25: Sol Ring's real oracle_text
# ("{T}: Add {C}{C}.") licensed only 1.0 (from its {1} cost), so "two colorless mana"
# was gate-rejected as an uncited number despite being a direct, correct reading of the
# card's own text. `_mana_symbol_counts` licenses the repetition count of each distinct
# symbol so this generalizes to any card, not just Sol Ring (a triple-green cost like
# "{G}{G}{G}" licenses 3.0 the same way).
_MANA_SYMBOL_RE = re.compile(r"\{[0-9WUBRGCXYZS/]{1,4}\}")


def _mana_symbol_counts(text: str) -> set[float]:
    counts: dict[str, int] = {}
    for sym in _MANA_SYMBOL_RE.findall(text):
        counts[sym] = counts.get(sym, 0) + 1
    return {float(n) for n in counts.values() if n > 1}


def extract_numbers(text: str) -> set[float]:
    """Every number in `text`, digit ("27") or spelled-out ("twenty-seven" -> catches
    "twenty" and "seven" as separate tokens, "a dozen" -> "dozen"). Used both by
    `_numbers_in` (licensing a tool result's own numbers) and by `mentor.gate.check`
    (extracting what the REPLY claims) -- one extraction rule for both sides of the
    budget check, so a spelled-out number licensed from tool data and a spelled-out
    number claimed in a reply are recognized the same way."""
    found = {round(float(m.group()), 1) for m in NUM_RE.finditer(text)}
    found.update(_WORD_NUMBERS[m.group().lower()] for m in WORD_NUM_RE.finditer(text))
    return found


def _numbers_in(value) -> set[float]:
    """Every number literally present in `value`, walked recursively -- including numbers
    embedded in a string. Deliberately generous; see the module docstring."""
    found: set[float] = set()
    if isinstance(value, bool):
        return found
    if isinstance(value, (int, float)):
        found.add(round(float(value), 1))
    elif isinstance(value, str):
        found.update(extract_numbers(value))
        found.update(_mana_symbol_counts(value))
    elif isinstance(value, dict):
        for v in value.values():
            found |= _numbers_in(v)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for v in value:
            found |= _numbers_in(v)
    return found


def _rule_numbers_in(value) -> set[str]:
    """Every CR-shaped rule number appearing in `value`'s text -- e.g. a rule's own
    cross-reference to another rule ("see rule 704.5f") licenses that citation too,
    because the model genuinely saw it in retrieved text."""
    found: set[str] = set()
    if isinstance(value, str):
        found.update(RULE_NUM_RE.findall(value))
    elif isinstance(value, dict):
        for v in value.values():
            found |= _rule_numbers_in(v)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for v in value:
            found |= _rule_numbers_in(v)
    return found


def _to_jsonable(value):
    """Dataclasses (CardImpact, AxisMove, ...) and sets -> plain JSON-safe structures."""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _to_jsonable(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    return value


@dataclass(frozen=True)
class ToolResult:
    """What one tool call hands back: `data` for the model to read, plus the claim
    budget that result licenses. `numbers`/`rule_numbers_from_text` are populated
    automatically from `data`; `card_names` and explicit `rule_numbers` are set by the
    tool function itself, since only it knows what its own fields mean."""

    data: dict
    card_names: frozenset[str] = frozenset()
    rule_numbers: frozenset[str] = frozenset()

    @property
    def numbers(self) -> frozenset[float]:
        return frozenset(_numbers_in(self.data))

    @property
    def all_rule_numbers(self) -> frozenset[str]:
        return frozenset(self.rule_numbers) | frozenset(_rule_numbers_in(self.data))


@dataclass
class MentorContext:
    """Everything a tool call needs, loaded once per CLI session (the semantics store
    alone is a ~50s cold load -- see cli.py's `_semantics_store`)."""

    card_db: CardDb
    cr: rulings_data.ComprehensiveRules
    rulings_db: dict[str, list[dict]]
    resolved: ResolvedDeck
    cfg: SimConfig
    store: SemanticsStore
    themes: Sequence[str] = field(default_factory=tuple)

    @property
    def deck_card_names(self) -> frozenset[str]:
        """The deck's own card list -- names a model can plausibly reach for without
        having looked them up, because they're sitting right there in the conversation's
        own context. NOTE: this is NOT the gate's card-name risk pool any more (that was
        a real fabrication gap -- a claim about a card outside the deck was invisible to
        the old check entirely; see `all_card_names` below and gate.py's module
        docstring, fixed 2026-08-24). Kept as a general "is this one of my own cards"
        helper; existing callers/tests still read it directly."""
        names = {c.name for c, _ in self.resolved.cards}
        names.update(c.name for c in self.resolved.commanders)
        return frozenset(names)

    @property
    def all_card_names(self) -> frozenset[str]:
        """Every real MTG card name `card_db` knows about -- the SAME index
        `tool_lookup_card` resolves names against. This is what feeds
        `mentor.gate.ClaimBudget.known_card_names`: the gate's name check must be able to
        flag a fabricated claim about ANY real card, not just one already in the deck.
        `CardDb` has no public enumeration (it only exposes point lookups via `.get`), so
        this reaches into its `_by_name` index directly; a double-faced card's front-face
        alias maps to the same `Card`, and collecting by `.name` naturally dedups it."""
        return frozenset(card.name for card in self.card_db._by_name.values())


def tool_lookup_card(ctx: MentorContext, name: str) -> ToolResult:
    card = ctx.card_db.get(name)
    if card is None:
        return ToolResult(data={"found": False, "message": f"No card named {name!r} found."})
    data = {
        "found": True,
        "name": card.name,
        "mana_cost": card.mana_cost_str,
        "mana_value": card.mana_value,
        "type_line": card.type_line,
        "oracle_text": card.oracle_text,
        "commander_legal": card.commander_legal,
        "game_changer": card.game_changer,
        "edhrec_rank": card.edhrec_rank,
    }
    return ToolResult(data=data, card_names=frozenset({card.name}))


def tool_lookup_rulings(ctx: MentorContext, name: str) -> ToolResult:
    card = ctx.card_db.get(name)
    if card is None or not card.oracle_id:
        return ToolResult(data={"found": False, "message": f"No card named {name!r} found."})
    entries = rulings_data.rulings_for_oracle_id(card.oracle_id, ctx.rulings_db)
    data = {"found": True, "card": card.name, "rulings": entries}
    return ToolResult(data=data, card_names=frozenset({card.name}))


def tool_search_rules(ctx: MentorContext, query: str, k: int = 5) -> ToolResult:
    # Measured 2026-08-24: building a fresh RulesSearchIndex over the ~4,000-document
    # corpus is 66ms, search itself 2ms -- negligible next to an LLM round-trip (seconds)
    # or assess_card's simulation (seconds), so this is NOT cached. Building it from
    # `ctx.cr` directly (rather than `rulings_data.search_rules`'s file-path-keyed cache)
    # is also what keeps this tool testable against a small in-memory ComprehensiveRules
    # fixture instead of coupling it to whatever's on disk.
    index = rulings_data.RulesSearchIndex(ctx.cr)
    results = index.search(query, k=k)
    data = {
        "results": [
            {"kind": r.kind, "ref": r.ref, "text": r.text, "score": round(r.score, 2)}
            for r in results
        ]
    }
    rule_nums = frozenset(r.ref for r in results if r.kind == "rule")
    return ToolResult(data=data, rule_numbers=rule_nums)


def tool_get_rule(ctx: MentorContext, number: str) -> ToolResult:
    text = ctx.cr.get_rule(number)
    if text is None:
        return ToolResult(data={"found": False, "message": f"No rule numbered {number!r}."})
    return ToolResult(data={"found": True, "number": number, "text": text},
                       rule_numbers=frozenset({number}))


def tool_get_deck_stats(ctx: MentorContext) -> ToolResult:
    """Curve, colour sources, and role supply-vs-target -- every one a closed-form or
    counting measurement (no simulation), matching `manabase.py`'s own "deterministic
    and offline" contract. This is the tool that answers "why does my curve feel bad" /
    "what's over-supplied" without the mentor ever computing a number itself."""
    resolved = ctx.resolved
    buckets: dict[int, int] = {}
    total_mv, total_n = 0.0, 0
    for card, qty in resolved.cards:
        if "Land" in card.type_line:
            continue
        b = min(max(card.mana_value, 1), 7)
        buckets[b] = buckets.get(b, 0) + qty
        total_mv += card.mana_value * qty
        total_n += qty
    curve = {
        "buckets": {str(k): v for k, v in sorted(buckets.items())},
        "average_mana_value": round(total_mv / total_n, 2) if total_n else 0.0,
        "nonland_count": total_n,
    }

    mb = manabase.analyze(list(resolved.cards), resolved.commanders)
    manabase_report = {
        "sources": mb.sources,
        "consistency": round(mb.consistency, 2),
        "worst_colors": [
            {"color": r.color, "turn": r.turn, "have": r.have, "need": r.need,
             "probability": round(r.probability, 2), "example": r.example}
            for r in mb.worst[:3]
        ],
    }

    supply = redundancy.role_supply(resolved)
    targets = redundancy.targets_for(ctx.themes)
    roles = {
        role: {"supply": round(supply.get(role, 0.0), 1), "target": targets.get(role, 0)}
        for role in sorted(set(supply) | set(targets))
    }

    data = {"curve": curve, "manabase": manabase_report, "roles": roles,
            "detected_themes": list(ctx.themes)}
    return ToolResult(data=data)


def tool_assess_card(ctx: MentorContext, name: str, cut_pool: int = 2) -> ToolResult:
    """Measures adding `card` to the deck via a real simulation re-run -- slower than the
    other tools (a few seconds; bounded by `cut_pool`, see the module docstring)."""
    card = ctx.card_db.get(name)
    if card is None:
        return ToolResult(data={"found": False, "message": f"No card named {name!r} found."})
    impact = card_impact.assess_card(
        ctx.resolved, card, ctx.cfg, ctx.store, cut_pool=cut_pool, themes=ctx.themes
    )
    data = _to_jsonable(impact)
    data["found"] = True
    names = {card.name}
    if impact.cut:
        names.add(impact.cut)
    return ToolResult(data=data, card_names=frozenset(names))


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "lookup_card",
            "description": "Look up a Magic: The Gathering card's real oracle text, mana "
                            "cost, type line and legality by EXACT name only (case and "
                            "whitespace insensitive, but it does NOT fuzzy-correct a "
                            "misspelled or approximate name -- a close-but-wrong name "
                            "returns not-found, so get the spelling right or the deck's "
                            "own decklist/get_deck_stats).",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_rulings",
            "description": "Get the official WotC/Scryfall rulings for a specific card by name.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_rules",
            "description": "Search the Magic: The Gathering Comprehensive Rules and glossary "
                            "by keyword; returns matching rule numbers/glossary terms and text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "k": {"type": "integer", "description": "max results, default 5"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_rule",
            "description": "Get the exact text of one Comprehensive Rules number, e.g. '704.5f'.",
            "parameters": {
                "type": "object",
                "properties": {"number": {"type": "string"}},
                "required": ["number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_deck_stats",
            "description": "Get this deck's measured mana curve, colour-source consistency, "
                            "and role supply vs. target (ramp/draw/removal/wipe/etc). Use this "
                            "for any question about curve, colours, or what's over/under-supplied.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assess_card",
            "description": "Measure what adding a specific card to this deck would actually "
                            "do, via simulation. Slower than the other tools. Use this for "
                            "'is X good in my deck' / 'should I add X' questions.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
]

_TOOL_FUNCS = {
    "lookup_card": tool_lookup_card,
    "lookup_rulings": tool_lookup_rulings,
    "search_rules": tool_search_rules,
    "get_rule": tool_get_rule,
    "get_deck_stats": tool_get_deck_stats,
    "assess_card": tool_assess_card,
}


def call_tool(ctx: MentorContext, name: str, args: dict) -> ToolResult:
    fn = _TOOL_FUNCS.get(name)
    if fn is None:
        return ToolResult(data={"found": False, "message": f"Unknown tool {name!r}."})
    try:
        return fn(ctx, **args)
    except TypeError as exc:
        return ToolResult(data={"found": False, "message": f"Bad arguments for {name!r}: {exc}"})
