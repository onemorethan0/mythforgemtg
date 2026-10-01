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
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field, fields, is_dataclass

from mythgauntlet.config import suite_collection_path
from mythgauntlet.mentor import deckview, diagnose as diagnose_mod, removal, verdicts
from mythgauntlet.data import rulings as rulings_data
from mythgauntlet.data.scryfall import CardDb
from mythgauntlet.model.collection import Collection
from mythgauntlet.model.deck import ResolvedDeck
from mythgauntlet.ratings import advisor, card_impact, manabase, redundancy, reference
from mythgauntlet.ratings.analysis import DeckAnalysis, analyze_deck
from mythgauntlet.semantics.store import SemanticsStore
from mythgauntlet.semantics import tags
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


# A minimum length so this doesn't bother masking trivial values ("Instant", "W") that
# couldn't meaningfully contain a false-positive card-name match anyway.
_SOURCE_TEXT_MIN_LEN = 12


def _strings_in(value) -> set[str]:
    """Every string value of meaningful length appearing in `value`, walked recursively
    -- these are licensed for VERBATIM quotation by the gate's card-name check (see
    `mentor.gate.check`'s masking step), independent of whether the quoted text happens
    to contain a word that is also a real card name. Found live 2026-08-25 (a real
    mentor campaign, not the synthetic bench): `lookup_card` correctly returned
    Anguished Unmaking's real oracle text ("Exile target nonland permanent. You lose 3
    life."), the model quoted it VERBATIM, and it was gate-rejected anyway because
    "Exile" is also a real (if unrelated) card name. This generalizes badly -- any
    fetch-effect or colour-fixing card's oracle text naming a basic land type ("search
    your library for a Forest") would hit the identical wall, since every basic land
    name is also a real card name. A card-name-shaped word inside a string the model is
    directly echoing back isn't an independent claim; it's the tool result itself."""
    found: set[str] = set()
    if isinstance(value, str):
        if len(value) >= _SOURCE_TEXT_MIN_LEN:
            found.add(value)
    elif isinstance(value, dict):
        for v in value.values():
            found |= _strings_in(v)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for v in value:
            found |= _strings_in(v)
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

    @property
    def source_texts(self) -> frozenset[str]:
        return frozenset(_strings_in(self.data))


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
    # {"synergy":..., "synergy_range":..., "staples_pct":..., "verdict":..., ...} from
    # Forge's own `lift_stats.stats_block` (root, EDHREC-backed) -- computed OUTSIDE this
    # process (the engine has no EDHREC cache/network path of its own) and threaded
    # through by Forge's `/api/deck/{job_id}/mentor` proxy, same handoff `themes` already
    # gets. None when Forge has none cached (an older deck predates `lift_stats`, or the
    # deck was never analysed) -- `get_deck_stats` reports that honestly rather than
    # fabricating a reading.
    offmeta: dict | None = None

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


# ── the per-process analysis cache (PLAN_MENTOR_ADHOC A1) ───────────────────────────
# Every tool that needs the engine's own read of the deck (`get_bracket_estimate`,
# `get_power_profile`, ...) used to run its own fresh `analyze_deck` -- the same ~seconds-long
# simulation, repeated per tool call and per chat turn, because the route is stateless and
# builds a new MentorContext each request. The analysis is a pure function of (deck, cfg), so
# a small bounded cache keyed on exactly that makes a follow-up question free. An
# OrderedDict rather than `functools.lru_cache`: `ctx` is not hashable (it holds a card DB
# and a store), and the key is a value-derived tuple anyway. Always computed with
# `run_resilience=True` so ONE entry serves every consumer -- a second, cheaper variant would
# split the cache and re-simulate.
_ANALYSIS_CACHE_MAX = 8
_ANALYSIS_CACHE: "OrderedDict[tuple, DeckAnalysis]" = OrderedDict()
# Held across the compute so two simultaneous requests for the same deck run ONE simulation
# (single-flight) instead of racing two -- the engine serves the mentor route from threads.
_ANALYSIS_LOCK = threading.RLock()


def _analysis_key(ctx: "MentorContext") -> tuple:
    cards = tuple(sorted((c.name, int(q)) for c, q in ctx.resolved.cards))
    commanders = tuple(sorted(c.name for c in ctx.resolved.commanders))
    cfg = ctx.cfg
    return ((cards, commanders), cfg.runs, cfg.turns, cfg.seed, tuple(ctx.themes))


def _analysis_for(ctx: "MentorContext") -> DeckAnalysis:
    """The deck's full `DeckAnalysis` (resilience included), memoised per process. Callers
    must treat the result as read-only -- it is shared across turns."""
    key = _analysis_key(ctx)
    with _ANALYSIS_LOCK:
        hit = _ANALYSIS_CACHE.get(key)
        if hit is not None:
            _ANALYSIS_CACHE.move_to_end(key)
            return hit
        analysis = analyze_deck(ctx.resolved, ctx.cfg, ctx.store, run_resilience=True)
        _ANALYSIS_CACHE[key] = analysis
        while len(_ANALYSIS_CACHE) > _ANALYSIS_CACHE_MAX:
            _ANALYSIS_CACHE.popitem(last=False)
        return analysis


def _analysis_cache_clear() -> None:
    with _ANALYSIS_LOCK:
        _ANALYSIS_CACHE.clear()


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
        # Found live 2026-08-25 (round 4 of a real mentor campaign): with no
        # color_identity field returned, a reply describing Heroic Intervention (real
        # mana cost {1}{G}, mono-green) as "a green-white card" went unchecked -- likely
        # because the model conflated "fits the green-white deck it's being added to"
        # with "is green-white itself". The mana cost was already enough to derive this
        # correctly, but giving the field explicitly removes the need to derive it at
        # all, and is a prerequisite for ever gate-checking a colour claim later.
        "color_identity": sorted(card.color_identity),
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


_COMBAT_ARCHETYPES = frozenset({"Creature aggro", "Go-wide / tokens", "Midrange goodstuff"})
_COMBAT_KILL_RATE = 0.5


def _wins_through_combat(a: DeckAnalysis) -> bool:
    """The engine measured this deck as a combat deck: a combat-based archetype AND the
    goldfish actually kills in at least half of games. Both halves are needed -- the archetype
    alone is a label, the kill rate alone could be a combo deck's."""
    return (a.insight.archetype in _COMBAT_ARCHETYPES
            and (a.report.goldfish_kill_rate or 0.0) >= _COMBAT_KILL_RATE)


def tool_get_deck_stats(ctx: MentorContext) -> ToolResult:
    """Curve, colour sources, and role supply-vs-target -- every one a closed-form or
    counting measurement (no simulation), matching `manabase.py`'s own "deterministic
    and offline" contract. This is the tool that answers "why does my curve feel bad" /
    "what's over-supplied" without the mentor ever computing a number itself."""
    resolved = ctx.resolved
    buckets: dict[int, int] = {}
    total_mv, total_n, land_n = 0.0, 0, 0
    for card, qty in resolved.cards:
        if "Land" in card.type_line:
            land_n += qty
            continue
        b = min(max(card.mana_value, 1), 7)
        buckets[b] = buckets.get(b, 0) + qty
        total_mv += card.mana_value * qty
        total_n += qty
    curve = {
        "buckets": {str(k): v for k, v in sorted(buckets.items())},
        "average_mana_value": round(total_mv / total_n, 2) if total_n else 0.0,
        "nonland_count": total_n,
        # Found live 2026-09-15 (mentor bench, real deck): asked "how many lands am I
        # running", the model had no licensed total to cite -- `nonland_count` is the
        # only count this tool ever reported -- and either fabricated one by summing
        # per-colour manabase sources itself (correctly gate-rejected: a sum is not a
        # literal number in any tool result) or refused outright. A land count is
        # exactly the kind of already-known fact this tool exists to hand over rather
        # than let the model derive.
        "land_count": land_n,
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
    # Colour-aware (PLAN_MENTOR_ADHOC C1): the colour-blind population target told every
    # non-blue deck it "lacks counterspells". An empty identity (unresolved commander) is
    # unknown, not colourless -- `role_applicable` leaves every role applicable then.
    identity = sorted({ch for c in resolved.commanders for ch in c.color_identity})
    targets = redundancy.targets_for(ctx.themes, color_identity=identity)
    role_cards = redundancy.role_card_counts(resolved)
    # `supply` and `target` are STRENGTH scores (redundancy.card_roles: a board wipe counts
    # 3.0, a counterspell 3.0, a tutor 2.0), NOT card counts -- the unit-less pair read as
    # "wipes 3/3" and was narrated as three board wipes for a deck with one (found on the
    # 2026-09-30 Shelob probe). `cards` is the real card count; compare supply with target
    # only as over/under target.
    roles = {
        role: {"supply": round(supply.get(role, 0.0), 1), "target": targets.get(role, 0),
               "cards": role_cards.get(role, 0), "unit": "strength",
               "applicable": redundancy.role_applicable(role, identity)}
        for role in sorted(set(supply) | set(targets))
    }
    colour_word = "/".join(identity)
    for role, entry in roles.items():
        if not entry["applicable"]:
            entry["note"] = (
                f"not applicable: no colour in this deck's identity ({colour_word}) usually "
                "supplies this role, so it is not a gap")
    # C2 (PLAN_MENTOR_ADHOC): `finisher` counts overrun/storm/burn/cheat payoffs, none of which a
    # deck that simply wins by attacking needs -- "finisher 0/2" on a measured combat deck was
    # narrated as a gap (Shelob: Midrange goodstuff, 27 creatures, goldfish kill ~T9). The plan
    # comes from the engine's own read, so this needs the (cached) analysis; only paid when the
    # role is still applicable after the colour rule.
    fin = roles.get("finisher")
    if fin is not None and fin["applicable"]:
        a = _analysis_for(ctx)
        if a.insight is not None and _wins_through_combat(a):
            fin["applicable"] = False
            fin["target"] = 0
            fin["note"] = "wins through combat (measured)"

    # No other tool surfaces WHO the commander(s) are -- a mentor with only lookup_card
    # (which needs a name the player already supplied) had no path to "who is my
    # commander" / "what's my full colour identity" at all, and answered a flat "I don't
    # have access to your decklist," which is itself a fabrication (the deck IS loaded,
    # it just had nowhere to surface). Found live 2026-08-25 on a Tymna the Weaver +
    # Thrasios, Triton Hero partner build.
    commanders = [
        {"name": c.name, "color_identity": list(c.color_identity)}
        for c in resolved.commanders
    ]
    data = {"curve": curve, "manabase": manabase_report, "roles": roles,
            "detected_themes": list(ctx.themes), "commanders": commanders}
    # "How off-meta is this deck" (lift_stats.stats_block) is computed OUTSIDE this
    # process -- see MentorContext.offmeta's own docstring for why -- so this is a
    # pass-through, not a measurement: whatever Forge already persisted for this deck,
    # narrated honestly rather than recomputed or guessed at. `offmeta` is None for a
    # deck Forge never analysed with it (an old build, or lift_stats itself returning {}
    # for insufficient EDHREC coverage) -- reported as unavailable rather than omitted
    # silently, so the model can say "I don't have an off-meta reading for this deck"
    # instead of staying quiet in a way indistinguishable from not having asked.
    data["offmeta"] = ctx.offmeta if ctx.offmeta else {"available": False}
    # Licenses stating the commander's name(s): without card_names= here, the gate would
    # flag "Your commander is Tymna the Weaver" as an unverified claim even though this
    # tool call is exactly what verified it (gate.py checks budget.card_names, not `data`).
    return ToolResult(data=data, card_names=frozenset(c.name for c in resolved.commanders))


def tool_get_bracket_estimate(ctx: MentorContext) -> ToolResult:
    """The official-rules Commander Bracket estimate (1-5, WotC Feb 2026 system) -- the
    SAME pipeline `mythgauntlet analyze` and Forge's Analyze panel already show
    (`ratings.analysis.analyze_deck` -> `ratings.bracket.estimate_bracket`), run here
    in-process rather than re-derived, matching the domain-A doctrine this whole tool
    module follows: never let the mentor compute a rating itself.

    This is the headline "is this deck too strong/weak for my pod" question, and until
    this tool existed the mentor had no path to it at all -- `get_deck_stats` covers
    curve/colours/roles, none of which is what a bracket number actually gates on
    (Game Changers, in-deck combos, mass land denial, measured speed/consistency).

    Runs a real (bounded) goldfish simulation, so this is priced like `assess_card` (a
    few seconds) on the FIRST call for a deck, not free like `get_deck_stats` -- its own
    tool rather than folded in. The analysis is shared through `_analysis_for`'s cache
    (resilience pass included, since `get_power_profile` needs it and one cache entry must
    serve both), so later calls for the same deck cost nothing. Deliberately skips a live
    Spellbook combo lookup (a real network call, cached by decklist hash elsewhere in this
    app but not worth paying for on every mentor turn). The reply's own
    `combos_checked: false` discloses that scope honestly -- exactly the field
    `estimate_bracket` exists to report -- rather than silently answering as if a full
    `/analyze` had run.
    """
    analysis = _analysis_for(ctx)
    data = _to_jsonable(analysis.bracket)
    data["found"] = True
    data["game_changer_cards"] = list(analysis.game_changers)
    # `BracketEstimate` itself doesn't carry this flag (it's a parameter to
    # `estimate_bracket`, not a stored field) -- the HTTP `/analyze` route surfaces it as
    # its own top-level response key for exactly this reason, and this tool mirrors that
    # convention rather than letting the model infer scope from what's absent.
    data["combos_checked"] = False
    return ToolResult(data=data, card_names=frozenset(analysis.game_changers))


def _pct(x):
    """A 0-1 rate as a whole percent. A model narrating `goldfish_kill_rate: 0.5` says
    "50%" -- a number no tool result contains, so the gate rejected the honest conversion
    (found live on Kess: "cites 50"). Reporting the percent alongside the fraction licenses
    the form the prose will use, without loosening the gate itself."""
    return None if x is None else int(round(float(x) * 100))


def _r1(x):
    """Round a score/turn to one decimal; None passes through (a turn that never happened)."""
    return None if x is None else round(float(x), 1)


# E2: how a raw percentile band reads in words. `percentile_band` describes the RAW value, so
# for a LOWER_IS_BETTER metric (kill turn, commander turn) "below_p25" is the FAST end -- the
# model is handed the already-oriented word rather than asked to flip it.
_STANDING = {"below_p25": "bottom_quarter", "p25_p50": "below_median",
             "p50_p75": "above_median", "above_p75": "top_quarter"}
_STANDING_LOWER_IS_BETTER = {"below_p25": "top_quarter", "p25_p50": "above_median",
                             "p50_p75": "below_median", "above_p75": "bottom_quarter"}


def _vs_bracket(bracket: int, metric: str, value) -> dict | None:
    """`reference.percentile_band` plus an oriented `standing` and the metric's direction;
    None when there is no usable reference cell (missing value, thin cell) -- omitted, not
    guessed."""
    band = reference.percentile_band(bracket, metric, value)
    if band is None:
        return None
    lower = metric in reference.LOWER_IS_BETTER
    band["direction"] = "lower_is_better" if lower else "higher_is_better"
    band["standing"] = (_STANDING_LOWER_IS_BETTER if lower else _STANDING)[band["percentile_band"]]
    return band


# C-residual: `insight` writes "N removal, 0 counters, M wipes (breadth b/3)" and "light on
# removal/counters" for EVERY deck, so a green or black deck's profile listed "0 counters" as a
# weakness (Shelob, Tymna, Ghired) although `role_applicable("counterspell", identity)` says
# no colour in its identity supplies counterspells. `insight.py` is shared with other surfaces
# and left alone; the mentor layer rewrites the sentences it hands the model.
_COUNT_COUNTERS_RE = re.compile(r",?\s*\d+ counters?\b")
_BREADTH_RE = re.compile(r"\b(\d+)/3(\s+types)?")
_LIGHT_ON_COUNTERS_RE = re.compile(r"removal/counters")


def _without_counterspells(text: str) -> str:
    """`text` with counterspells removed from an interaction sentence: the counter count is
    dropped and breadth (of three possible types) becomes breadth of the two the deck's
    colours can play."""
    text = _COUNT_COUNTERS_RE.sub("", text)
    text = _LIGHT_ON_COUNTERS_RE.sub("removal", text)
    return _BREADTH_RE.sub(lambda m: f"{m.group(1)} of 2 playable types", text)


def tool_get_power_profile(ctx: MentorContext, compare_bracket: int | None = None) -> ToolResult:
    """The deck's MEASURED Power Profile -- the structured answer the engine already holds
    for "what does this deck do well and poorly / how does it win / how fast / how resilient
    to a wipe". `get_bracket_estimate` ran the same `analyze_deck` and kept only the bracket;
    every other field here (six axis scores and their one-line whys, archetype, gameplan,
    pod placement, strengths/weaknesses, key cards per role, clock, resilience, interaction
    card COUNTS, win-condition redundancy) was computed and thrown away, which is why the
    mentor answered these questions from `get_deck_stats`' role numbers alone and inverted
    verdicts the engine had already measured (docs/PLAN_MENTOR_ADHOC.md, section 1).

    Everything comes from `_analysis_for(ctx)` (one cached simulation, resilience included);
    nothing is computed here, and `verdicts` is `mentor.verdicts.classify_profile` -- the
    same bands the holistic bench grades against -- so the model is handed the verdict word
    rather than asked to derive it from a score."""
    if compare_bracket is not None and compare_bracket not in range(1, 6):
        return ToolResult(data={"found": False, "message":
                                f"compare_bracket must be 1-5, got {compare_bracket!r}."})
    a = _analysis_for(ctx)
    ins = a.insight
    if ins is None or a.resilience is None:
        return ToolResult(data={"found": False,
                                "message": "The deck's power profile could not be computed."})
    r, res, ceil, pod, inter, b = a.report, a.resilience, a.ceiling, a.pod, a.interaction, a.bracket
    why = ins.axis_why
    # `clock` is a lens for "faster" (see advisor.PROFILE_AXES), not a profile axis: its numbers
    # are the `clock` block below, so it stays out of `axes` (and out of vs_bracket's axes).
    axes = {
        ax: {"score": _r1(advisor.axis_score(a, ax)), "why": why.get(advisor.AXES[ax][1], "")}
        for ax in advisor.PROFILE_AXES
    }
    axes["pod"] = {"score": _r1(pod.score), "why": why.get("Pod (multiplayer)", "")}
    identity = sorted({ch for c in ctx.resolved.commanders for ch in c.color_identity})
    counters_apply = redundancy.role_applicable("counterspell", identity)
    strengths, weaknesses = list(ins.strengths), list(ins.weaknesses)
    if not counters_apply:
        axes["interaction"]["why"] = _without_counterspells(axes["interaction"]["why"])
        strengths = [_without_counterspells(t) if t.startswith("Deep interaction") else t
                     for t in strengths]
        weaknesses = [_without_counterspells(t) if t.startswith("Thin interaction") else t
                      for t in weaknesses]
    # E2: where the deck sits among corpus decks LABELLED with a bracket (the deck builder's
    # own `# bracket: N`) -- the deck's estimated bracket, or the one the player asked about.
    ref_bracket = compare_bracket if compare_bracket is not None else b.bracket
    for ax, entry in axes.items():
        vs = _vs_bracket(ref_bracket, ax, entry["score"])
        if vs is not None:
            entry["vs_bracket"] = vs
    kill_vs = _vs_bracket(ref_bracket, "avg_kill_turn", r.avg_kill_turn)
    cmdr_vs = _vs_bracket(ref_bracket, "avg_commander_turn", r.avg_commander_turn)
    wincon = _to_jsonable(a.wincon_redundancy)
    names: set[str] = {c.name for c in ctx.resolved.commanders}
    key_cards = []
    for k in ins.key_cards:
        key_cards.append({"role": k.role, "cards": list(k.names), "more": k.more})
        names.update(k.names)
    for role in wincon.get("roles", []):
        names.update(role.get("contributing_cards", []))
    data = {
        "found": True,
        "archetype": ins.archetype,
        "gameplan": ins.gameplan,
        "pod_read": ins.pod_read,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "axes": axes,
        "weakest_axis": advisor.weakest_axis(a),
        "clock": {
            "avg_kill_turn": _r1(r.avg_kill_turn),
            "goldfish_kill_rate": _r1(r.goldfish_kill_rate),
            "avg_commander_turn": _r1(r.avg_commander_turn),
            "commander_cast_rate": _r1(r.commander_cast_rate),
            "keep_rate": _r1(r.keep_rate),
            "curve_efficiency": _r1(r.curve_efficiency),
            "fast_kill_turn": _r1(ceil.fast_kill_turn),
            "pod_close_turn": _r1(pod.pod_close_turn),
            # the same rates as whole percents (see _pct)
            "goldfish_kill_rate_pct": _pct(r.goldfish_kill_rate),
            "commander_cast_rate_pct": _pct(r.commander_cast_rate),
            "keep_rate_pct": _pct(r.keep_rate),
            "curve_efficiency_pct": _pct(r.curve_efficiency),
            "pod_close_rate_pct": _pct(pod.pod_close_rate),
            **({"avg_kill_turn_vs_bracket": kill_vs} if kill_vs else {}),
            **({"avg_commander_turn_vs_bracket": cmdr_vs} if cmdr_vs else {}),
        },
        "bracket_reference": {
            "bracket": ref_bracket,
            "basis": ("the bracket the player asked about" if compare_bracket is not None
                      else "this deck's own estimated bracket"),
            "note": ("vs_bracket places a score among decks that players LABELLED this "
                     "bracket: above / below typical for them. It is NOT evidence about which "
                     "bracket the deck belongs in -- most axes barely differ between "
                     "brackets."),
        },
        "resilience": {
            "score": _r1(res.resilience_score),
            "wipe_turn": a.wipe_turn,
            "kill_delay_turns": _r1(res.kill_delay_turns),
        },
        # CARD COUNTS (copies), unlike get_deck_stats' role `supply`, which is a strength score.
        "interaction_counts": {
            "spot_removal": inter.spot_removal,
            # not a gap when no colour in the identity supplies counterspells (C1)
            "counterspells": (inter.counterspells if counters_apply
                              else "n/a (no blue in this deck's colour identity)"),
            "counterspells_applicable": counters_apply,
            "board_wipes": inter.board_wipes, "breadth": inter.breadth,
            "breadth_max": 3 if counters_apply else 2,   # types (removal / counters / wipes) in play
        },
        "key_cards": key_cards,
        "wincon_redundancy": wincon,
        "bracket": {"bracket": b.bracket, "label": b.label, "plays_up": b.plays_up},
        "verdicts": verdicts.classify_profile(a),
    }
    return ToolResult(data=data, card_names=frozenset(names))


def tool_list_deck_cards(ctx: MentorContext, role: str | None = None) -> ToolResult:
    """The deck's actual card list with the functional roles each card fills -- the
    card-level view no other tool gave (PLAN_MENTOR_ADHOC G2). `role` filters to one role;
    role names are `redundancy.card_roles`' own plus "land" (one taxonomy, never a new one).
    An unknown role is `found: False` listing the valid ones. Every returned name is
    licensed, so the model may name any card it was shown here."""
    rows = deckview.deck_card_rows(ctx.resolved)
    valid = sorted(set(redundancy.ROLE_TARGETS) | {"land"})
    if role is not None:
        role = str(role).strip().lower()
        if role not in valid:
            return ToolResult(data={
                "found": False, "valid_roles": valid,
                "message": f"No role named {role!r}; valid roles are {', '.join(valid)}.",
            })
        rows = [r for r in rows if role in r["roles"]]
    data = {
        "found": True, "role": role, "valid_roles": valid,
        "count": len(rows), "copies": sum(r["qty"] for r in rows),
        "cards": rows,
    }
    return ToolResult(data=data, card_names=frozenset(r["name"] for r in rows))


def tool_removal_coverage(ctx: MentorContext) -> ToolResult:
    """What the deck's interaction can actually ANSWER, read clause by clause from each card's
    oracle text (`mentor.removal.coverage`) -- the answer to "is my removal good enough / what
    can't it answer" that no other tool could give (the mentor used to speculate "might
    struggle vs flyers"). Deterministic and offline. `answers_by_type` lists every card that
    can hit a type; `unrestricted_answers_by_type` keeps only those with no target-limiting
    restriction ("with flying", "nonblack", "power 3 or less" ...), so a deck whose creature
    answers are mostly "with flying" does not read as well covered. `counts_by_type` carries
    the counts so the model never counts list items itself. Licenses every card name."""
    cov = removal.coverage(ctx.resolved)
    not_applicable: dict[str, str] = {}
    identity = sorted({ch for c in ctx.resolved.commanders for ch in c.color_identity})
    if not redundancy.role_applicable("counterspell", identity):
        # Only counterspells answer a SPELL, and no colour in this identity plays them: the
        # empty "spell" entry read as a coverage gap and three of the bench's non-blue decks
        # were told to "consider adding counterspells" (C-residual colour 6/9).
        cov = {**cov, "answers_by_type": {k: v for k, v in cov["answers_by_type"].items() if k != "spell"},
               "unrestricted_answers_by_type": {k: v for k, v in
                                                cov["unrestricted_answers_by_type"].items() if k != "spell"},
               "no_answer_for": [t for t in cov["no_answer_for"] if t != "spell"],
               "no_unrestricted_answer_for": [t for t in cov["no_unrestricted_answer_for"]
                                              if t != "spell"]}
        not_applicable["spell"] = ("only counterspells answer spells, and no blue in this deck's "
                                   "colour identity plays them -- not a gap, never recommend them")
    counts = {
        typ: {"answers": len(cov["answers_by_type"][typ]),
              "unrestricted": len(cov["unrestricted_answers_by_type"][typ])}
        for typ in cov["answers_by_type"]
    }
    data = {
        "found": True,
        **cov,
        "not_applicable_types": not_applicable,
        "counts_by_type": counts,
        "reading_guide": (
            "answers_by_type lists every card that can hit that type, including ones limited "
            "by a restriction; unrestricted_answers_by_type keeps only answers with no "
            "target-limiting restriction. no_answer_for = types with no answer at all; "
            "no_unrestricted_answer_for = types with no unrestricted answer (includes "
            "no_answer_for). Restrictions are quoted from the card text."
        ),
    }
    return ToolResult(data=data, card_names=frozenset(r["name"] for r in cov["cards"]))


_AXIS_BAND = {"resilience": verdicts.resilience_band, "consistency": verdicts.consistency_band,
              "interaction": verdicts.interaction_band}


def _axis_current(report) -> dict:
    """Where the deck stands on the axis a swap search targeted, so the answer can open with it
    even when the model skipped `get_power_profile` (C-residual: Shelob and Tymna answered "how
    resilient is it to a wipe" with only a swap, no verdict). `verdict` is the same band the
    profile's `verdicts` object uses, where one exists for the axis."""
    current: dict = {"axis": report.axis, "score": _r1(report.baseline)}
    band = _AXIS_BAND.get(report.axis)
    if band is not None:
        current["verdict"] = band(report.baseline)
        current["instruction"] = (
            f"State the deck's {report.axis} verdict ({current['verdict']}) and score "
            f"({current['score']}) first, then the swap result.")
    return current


def tool_suggest_swap(ctx: MentorContext, axis: str | None = None) -> ToolResult:
    """What to add/cut, measured by re-simulation -- `ratings.advisor.advise`'s full
    ablation sweep, deferred out of Phase 1 (see this module's own docstring) until the
    tool loop was proven live. It has been: six campaign rounds, the gate hardened
    against real failures found driving it, `check_legality` shipped from the same
    process. This is the single most natural mentor question ("what should I cut for a
    wrath effect") and until now had no tool backing it at all.

    Suggests ONLY from the player's own Myth Suite collection (`collection.csv`) --
    same contract as Forge's `/advise` panel and the SAME selection rule
    (`advisor.owned_candidates`, factored out for exactly this reuse) -- never from all
    of Magic. `found: False` with an explanatory message when there is no collection
    file to read from; the model is expected to report that honestly rather than
    inventing a suggestion from general card knowledge, which the system prompt and the
    gate's card-name check both already forbid.

    Bounded well below Forge's own patient `/advise` panel (max_eval=16, cut_pool=6,
    runs=300, measured ~583s off the request thread) since this runs synchronously
    inside a chat turn, itself inside Forge's own 120s proxy timeout alongside whatever
    other tool calls the same turn makes: max_eval=4, cut_pool=1 (4 re-simulations,
    each roughly `assess_card`-priced) and `ctx.cfg.runs` (the same run count already
    used for `assess_card` this session). `advisor.advise`'s own docstring sweep table
    shows quality rises with these knobs but there is no knee, so this is a latency
    choice, not an accuracy ceiling -- a single global cut (cut_pool=1) still measures a
    real swap, just without per-candidate cut tailoring.
    """
    path = suite_collection_path()
    if not path.exists():
        return ToolResult(data={
            "found": False,
            "message": "No Myth Suite collection file found, so there's nothing owned "
                       "to suggest a swap from.",
        })
    try:
        collection = Collection.load(path)
    except (OSError, UnicodeDecodeError):
        return ToolResult(data={"found": False, "message": "Could not read the collection file."})
    candidates = advisor.owned_candidates(ctx.card_db, ctx.resolved, collection)
    if not candidates:
        return ToolResult(data={
            "found": True, "improving_swap_found": False, "suggestions": [],
            "message": "No owned, in-colour cards outside the deck to test as adds.",
        })
    report = advisor.advise(
        ctx.resolved, ctx.cfg, ctx.store, candidates,
        axis=axis, top=3, max_eval=4, cut_pool=1, themes=ctx.themes,
    )
    if not report.suggestions:
        # `AdviceReport.cut` is the head of the cut POOL, not a verdict -- with no swap
        # clearing the noise floor it reads exactly like advice ("cut X to be faster") and
        # was narrated as such: the plan's Shelob probe had the mentor recommend cutting the
        # deck's own theme card from an empty result. So an empty search returns no card
        # name at all and licenses none; the message is the whole finding.
        return ToolResult(data={
            "found": True, "improving_swap_found": False,
            "axis": report.axis, "baseline": report.baseline, "evaluated": report.evaluated,
            "current": _axis_current(report),
            "message": (
                f"Tested {report.evaluated} owned cards as adds on {report.axis_label}; none "
                f"beat the noise floor (min gain {report.min_delta:g}). No measured swap to "
                "recommend."
            ),
        })
    data = _to_jsonable(report)
    data.pop("cut", None)   # the pool head is not advice; each suggestion carries its own cut
    data["found"] = True
    data["improving_swap_found"] = True
    data["current"] = _axis_current(report)
    # D0b: a cut whose brief says `redundancy_backed: false` was the pool's DEFAULT (the deck
    # over-supplies no role, so `rank_redundant` fell through to least-played), not evidence
    # the card is weak -- Shelob's own theme card, Gloomwidow's Feast, kept surfacing this way
    # and was narrated as "the weak card". Say so in the data, next to the cut itself.
    for raw, sug in zip(report.suggestions, data.get("suggestions", [])):
        backed = bool(raw.brief.cut.redundancy_backed) if raw.brief is not None else False
        sug["cut_is_redundant"] = backed
        if not backed:
            sug["cut_note"] = (
                f"{raw.cut} was offered only because a cut had to be picked: the deck "
                "over-supplies no role, so this is not evidence that the card is weak "
                "(it may be a theme card). Say so rather than calling it a weak or "
                "redundant card."
            )
    names: set[str] = set()
    for s in report.suggestions:
        names.add(s.add)
        names.add(s.cut)
        # SwapBrief.allowed_card_names is the FULL claim budget for this one swap's own
        # reasoning (see swap_brief.py) -- e.g. a synergy card the brief cites without
        # that card being the add or the cut itself. Licensing only add/cut would gate-
        # reject an honest narration of a well-measured reason the brief already vouches
        # for, the same class of gap `source_texts` exists to close for verbatim quotes.
        if s.brief is not None:
            names.update(s.brief.allowed_card_names)
    return ToolResult(data=data, card_names=frozenset(names))


# D1: facts the `diagnose` table reads, all from the cached analysis plus closed-form counts
# (no new simulation). Rates are carried as fractions AND whole percents (the gate rejects a
# "77%" that no tool result contains -- same reason `get_power_profile` carries `*_pct`).
_RATE_FACTS = frozenset({"goldfish_kill_rate", "keep_rate", "curve_efficiency",
                         "commander_cast_rate", "manabase_consistency", "creature_share",
                         "nut_kill_rate"})
DIAGNOSE_AXES = tuple(diagnose_mod.DRIVER_TABLE)


def _diagnose_facts(ctx: MentorContext, a: DeckAnalysis) -> dict:
    r, res, ceil, inter = a.report, a.resilience, a.ceiling, a.interaction
    resolved = ctx.resolved
    identity = sorted({ch for c in resolved.commanders for ch in c.color_identity})
    nonland = [(c, q) for c, q in resolved.cards if not c.is_land]
    nonland_n = sum(q for _c, q in nonland)
    creatures = sum(q for c, q in nonland if "Creature" in c.type_line)
    engines = 0
    for c, q in nonland:
        if "Creature" in c.type_line:
            continue
        roles = redundancy.card_roles(tags.analyze(c))
        if "ramp" in roles or "draw" in roles:
            engines += q
    role_cards = redundancy.role_card_counts(resolved)
    try:
        no_answer = list(removal.coverage(resolved).get("no_answer_for", []))
    except Exception:  # advisory: an unreadable card must not sink the whole diagnosis
        no_answer = None
    return {
        "avg_kill_turn": r.avg_kill_turn, "goldfish_kill_rate": r.goldfish_kill_rate,
        "avg_commander_turn": r.avg_commander_turn, "curve_efficiency": r.curve_efficiency,
        "keep_rate": r.keep_rate, "avg_mulligans": r.avg_mulligans,
        "commander_cast_rate": r.commander_cast_rate,
        "average_mana_value": (sum(c.mana_value * q for c, q in nonland) / nonland_n
                               if nonland_n else None),
        "land_count": sum(q for c, q in resolved.cards if c.is_land),
        "ramp_cards": role_cards.get("ramp", 0), "creature_count": creatures,
        "creature_share": creatures / nonland_n if nonland_n else None,
        "noncreature_engine_count": engines,
        "manabase_consistency": manabase.analyze(list(resolved.cards),
                                                 resolved.commanders).consistency,
        "resilience_score": res.resilience_score if res is not None else None,
        "kill_delay_turns": res.kill_delay_turns if res is not None else None,
        "spot_removal": inter.spot_removal, "counterspells": inter.counterspells,
        "board_wipes": inter.board_wipes, "breadth": inter.breadth,
        "no_answer_for": no_answer,
        "counterspell_applicable": redundancy.role_applicable("counterspell", identity),
        "wipe_applicable": redundancy.role_applicable("wipe", identity),
        "fast_kill_turn": ceil.fast_kill_turn, "nut_kill_rate": ceil.nut_kill_rate,
        "has_game_ending_combo": bool(ceil.has_game_ending_combo),
        # a deck that never goes off is a known "no", not an unmeasured fact
        "go_off_turn": ceil.go_off_turn or False, "overrun_alpha": bool(ceil.overrun_alpha),
    }


def tool_diagnose_axis(ctx: MentorContext, axis: str) -> ToolResult:
    """WHY an axis scores what it does, and what moves it: the axis's measured drivers (value,
    direction, and a strong/typical/weak reading against the deck's bracket where the reference
    table has the metric, fixed documented thresholds otherwise) plus fixed lever sentences keyed
    off the weak drivers. Deterministic and cache-backed (`_analysis_for`): no new simulation,
    so it is cheap to call before `suggest_swap`, which names the actual cards."""
    if axis not in diagnose_mod.DRIVER_TABLE:
        return ToolResult(data={"found": False, "message":
                                f"unknown axis {axis!r}; choose one of: {', '.join(DIAGNOSE_AXES)}."})
    a = _analysis_for(ctx)
    if a.insight is None:
        return ToolResult(data={"found": False,
                                "message": "The deck's power profile could not be computed."})
    facts = _diagnose_facts(ctx, a)
    label = "Speed" if axis == "clock" else advisor.AXES[axis][1]
    why = a.insight.axis_why.get(label, "")
    if axis == "interaction" and not facts["counterspell_applicable"]:
        why = _without_counterspells(why)
    out = diagnose_mod.diagnose(axis, _r1(advisor.axis_score(a, axis)), why, facts,
                                a.bracket.bracket)
    for row in out["drivers"]:
        value = row["value"]
        if row["name"] == "counterspells" and not facts["counterspell_applicable"]:
            row["value"] = "n/a (no blue in this deck's colour identity)"
            row["reading"] = "not_applicable"
        elif row["name"] == "board_wipes" and not facts["wipe_applicable"]:
            row["value"] = "n/a (no colour in this deck's identity plays wipes)"
            row["reading"] = "not_applicable"
        elif row["name"] in _RATE_FACTS and isinstance(value, (int, float)) \
                and not isinstance(value, bool):
            row["value_pct"] = _pct(value)
            row["value"] = round(float(value), 2)
        elif isinstance(value, float):
            row["value"] = round(value, 2)
    data = {
        "found": True, **out,
        "bracket_basis": a.bracket.bracket,
        "reading_guide": (
            "Each driver is a measured fact about the deck; reading says how it compares with "
            "typical decks (basis bracket_percentile = decks labelled with the deck's own "
            "bracket, fixed_threshold = documented cut-offs). A 'not_applicable' driver is "
            "never a gap. levers are the fixed fixes for the weak drivers; they name no "
            "cards -- call suggest_swap for those."
            + (" The clock score is how EARLY the average kill comes (higher = earlier)."
               if axis == "clock" else "")),
    }
    return ToolResult(data=data)


def tool_check_legality(ctx: MentorContext, name: str) -> ToolResult:
    """Deterministic colour-identity subset check -- this arithmetic must never be done
    by the model itself.

    `lookup_card` exposing `color_identity` was meant to be enough (its own docstring:
    "a prerequisite for ever gate-checking a colour claim later"), but that only gives
    the model the two sets -- it still has to conclude whether one is a subset of the
    other, and a live campaign caught it failing that step even after CORRECTLY stating
    both sets: asked about Chaos Warp against a Tymna the Weaver + Thrasios, Triton Hero
    (WBUG) deck, it wrote "its color identity (red) is covered by your deck's color
    identity (black, white, green, and blue)" -- red is plainly not in that list, and it
    said so itself one clause earlier. Doing the subset check in Python removes the
    failure mode instead of hoping a bigger prompt fixes a small model's arithmetic.
    """
    card = ctx.card_db.get(name)
    if card is None:
        return ToolResult(data={"found": False, "message": f"No card named {name!r} found."})
    deck_identity: set[str] = set()
    for c in ctx.resolved.commanders:
        deck_identity |= set(c.color_identity)
    card_identity = set(card.color_identity)
    missing = sorted(card_identity - deck_identity)
    data = {
        "found": True,
        "card": card.name,
        "card_color_identity": sorted(card_identity),
        "deck_color_identity": sorted(deck_identity),
        "legal": not missing,
        "colors_not_in_deck_identity": missing,
    }
    return ToolResult(data=data, card_names=frozenset({card.name}))


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
            "description": "Get this deck's commander(s) and full colour identity, measured "
                            "mana curve, colour-source consistency, and role supply vs. target "
                            "(ramp/draw/removal/wipe/etc). Use this for any question about who "
                            "the commander is, colour identity, curve, or what's "
                            "over/under-supplied.",
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
    {
        "type": "function",
        "function": {
            "name": "check_legality",
            "description": "Deterministically check whether a card's colour identity is a "
                            "legal SUBSET of this deck's commander(s) colour identity. Call "
                            "this for ANY question of the form 'can/could/would I add X' or "
                            "'is X legal in this deck' -- do NOT work out the subset "
                            "relationship yourself even if you already have both colour "
                            "identities from other tool calls; use this tool's verdict.",
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
            "name": "get_bracket_estimate",
            "description": "Get the official-rules Commander Bracket estimate (1-5) for "
                            "this deck, via a real (bounded) simulation -- WotC's Feb 2026 "
                            "bracket system (Game Changers, in-deck combos, mass land denial, "
                            "measured speed/consistency). Use this for ANY question of the "
                            "form 'what bracket is this', 'is this deck too strong/weak for "
                            "my pod', or 'is this deck fun/on-level for casual play'. Slower "
                            "than get_deck_stats -- a real simulation, priced like "
                            "assess_card.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_power_profile",
            "description": "The deck's measured Power Profile -- what it does well and poorly, "
                            "how it wins, speed, resilience to wipes, interaction, key cards "
                            "per role, and where each axis sits among typical decks of a "
                            "bracket (vs_bracket). Call FIRST for any strengths/weaknesses/"
                            "observations/'how does it win'/'how fast'/'how resilient' "
                            "question. Pass compare_bracket when the player names a bracket "
                            "('against a bracket 3 pod') to compare against that bracket "
                            "instead of the deck's own.",
            "parameters": {
                "type": "object",
                "properties": {
                    "compare_bracket": {
                        "type": "integer", "enum": [1, 2, 3, 4, 5],
                        "description": "optional: the bracket (1-5) to compare the deck's "
                                       "axes against; omit for the deck's own estimated one",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_deck_cards",
            "description": "List the deck's actual cards (commander first) with quantity, "
                            "mana value, type line and the functional roles each fills "
                            "(ramp/draw/removal/wipe/counterspell/tutor/finisher/land). Pass "
                            "role to see only one role's cards. Use this for 'which cards are "
                            "my ramp/removal/draw', 'what is in my deck' or any question "
                            "about which specific cards fill a role.",
            "parameters": {
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "description": "optional role filter: ramp, draw, removal, wipe, "
                                       "counterspell, tutor, finisher or land",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "removal_coverage",
            "description": "What the deck's removal, board wipes and counterspells can "
                            "actually answer (creatures, artifacts, enchantments, "
                            "planeswalkers, spells), read from each card's oracle text, with "
                            "each card's restrictions (e.g. 'with flying', 'nonblack') and "
                            "the types with no answer or no UNRESTRICTED answer. Call this "
                            "for 'is my removal good enough', 'what can't my removal answer' "
                            "or 'what am I weak against' questions.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "diagnose_axis",
            "description": "Why one Power Profile axis scores what it does: its measured "
                            "drivers (each with its value and a strong/typical/weak reading "
                            "against decks of the deck's bracket) and the fixed levers that "
                            "move it. Cheap (no new simulation). Call it for 'why is my X "
                            "low', 'what is holding my speed back' or 'how do I improve X' "
                            "BEFORE suggest_swap, which then names the actual cards. Use "
                            "clock for how EARLY the deck kills.",
            "parameters": {
                "type": "object",
                "properties": {
                    "axis": {
                        "type": "string",
                        "enum": list(DIAGNOSE_AXES),
                        "description": "the axis to explain",
                    },
                },
                "required": ["axis"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_swap",
            "description": "Suggest a measured add/cut swap from the player's OWN Myth "
                            "Suite collection (never from outside it), verified by "
                            "re-simulating the deck with the swap applied. Use this for "
                            "'what should I cut', 'what should I add', 'what are my weakest "
                            "cards' or 'how can I improve / make it faster' questions -- call "
                            "it even after get_power_profile, with the axis the question is "
                            "about (clock for 'faster' / 'speed up' / 'quicker'); only its result can name a card to "
                            "change. Slower than the other tools -- several re-simulations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "axis": {
                        "type": "string",
                        "enum": ["consistency", "speed", "resilience", "interaction", "ceiling",
                                 "clock"],
                        "description": "which Power Profile axis to improve; omit to target "
                                       "the deck's own weakest axis. clock = how EARLY the "
                                       "deck kills (use it for 'faster' / 'speed up' / "
                                       "'quicker'); speed = how often it kills at all",
                    },
                },
                "required": [],
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
    "get_bracket_estimate": tool_get_bracket_estimate,
    "get_power_profile": tool_get_power_profile,
    "list_deck_cards": tool_list_deck_cards,
    "removal_coverage": tool_removal_coverage,
    "diagnose_axis": tool_diagnose_axis,
    "suggest_swap": tool_suggest_swap,
    "check_legality": tool_check_legality,
}


def call_tool(ctx: MentorContext, name: str, args: dict) -> ToolResult:
    fn = _TOOL_FUNCS.get(name)
    if fn is None:
        return ToolResult(data={"found": False, "message": f"Unknown tool {name!r}."})
    try:
        return fn(ctx, **args)
    except TypeError as exc:
        return ToolResult(data={"found": False, "message": f"Bad arguments for {name!r}: {exc}"})
    except ValueError as exc:
        # A model-supplied enum-shaped argument (suggest_swap's `axis`) can still arrive
        # malformed despite the schema's enum hint -- advisor.advise raises ValueError for
        # an unknown axis rather than silently falling back, which is correct for a real
        # caller but must not surface as an unhandled 500 from inside the tool loop.
        return ToolResult(data={"found": False, "message": f"Bad arguments for {name!r}: {exc}"})
