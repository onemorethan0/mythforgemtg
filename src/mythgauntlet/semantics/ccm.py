"""Card Capability Model schema v1 + validation gates (docs/CARD_SEMANTICS.md).

A CCM is a JSON document describing a card as costs, types, and abilities over a closed
effect-primitive vocabulary. Gate 1 validates structure, gate 2 lints against Scryfall
facts, gate 3 cross-checks against the independent rung-1 heuristics — the LLM proposes,
these gates dispose.
"""

from __future__ import annotations

import re

from mythgauntlet.model.card import Card
from mythgauntlet.semantics import tags

CCM_VERSION = 1

ABILITY_KINDS = {"spell_effect", "activated", "triggered", "static", "mana_ability"}
# Events the ENGINE executes (sim/tier2._EVENT_TRIGGERS is the authority).
_EXECUTED_EVENTS = {
    "etb", "death", "upkeep", "draw_step", "end_step", "attack", "cast_creature",
    "cast_spell", "opponent_casts_spell", "landfall", "combat_damage_to_player",
    # begin_combat was being EMITTED by the compiler (244 cards) but was outside the
    # vocabulary, so the schema tolerated it and sim/tier2._EVENT_TRIGGERS dropped every
    # one. "At the beginning of combat on your turn" is a common, high-impact trigger.
    "begin_combat",
}
# Events the engine does NOT execute but cards genuinely have. Naming them is not
# cosmetic: an unexecuted event is DROPPED by _event_triggers and under-counts honestly,
# while a wrong executable event FABRICATES value. Smaug the Impenetrable ("whenever
# Smaug is dealt noncombat damage, create that many Treasures") was compiled as
# combat_damage_to_player — so the engine minted Treasures every time he connected in
# combat, an ability the card does not have. Before this vocabulary existed the model had
# no correct answer available and reached for the nearest executable one; 1,572 of 15,765
# triggered abilities (10%) declared an event their oracle text does not support.
_UNEXECUTED_EVENTS = {
    "self_cast",        # "When you cast this spell" — fires ONCE, not on every creature
    "blocks", "becomes_blocked", "end_of_combat",
    "dealt_damage",     # "whenever this is dealt damage" (incl. noncombat)
    "saga_chapter",     # I/II/III — not the draw step
    "leaves_battlefield", "creature_dies", "becomes_target", "tap_for_mana",
    "gain_life", "lose_life", "counter_added", "activate_ability",
}
TRIGGER_EVENTS = _EXECUTED_EVENTS | _UNEXECUTED_EVENTS | {"other"}

# Spellings the compiler emits for events the vocabulary ALREADY names. Adding
# `begin_combat` in the block above fixed one instance of this; it did not fix the class,
# because the validator tolerates any event string (see `validate`) and `_event_triggers`
# then drops whatever it doesn't recognise. So a synonym is silently inert, and the model
# keeps minting them: at prompt v10 the store held 611 out-of-vocabulary triggers across
# 117 spellings.
#
# Only an EXACT-semantic re-spelling belongs here, checked against the oracle text of
# every card that uses it — a near-miss that reads like a vocabulary word is the failure
# this map is supposed to fix, not repeat. Three candidates were rejected on that check:
#
#   * `begin_end_step` (9 cards) is NOT `end_step`. Every one is a delayed one-shot
#     cleanup — "sacrifice it at the beginning of the NEXT end step" (Urabrask's Forge,
#     Valduk, Determined Iteration). Firing it as the recurring end-step trigger would
#     sacrifice a token every turn, fabricating a downside the card does not have. The
#     model uses plain `end_step` for genuine recurring triggers, so the two spellings
#     are carrying a real distinction.
#   * `enters_battlefield` (3 cards) is NOT `etb`. Brainstealer Dragon's entry is
#     `{"event": "enters_battlefield", "controller": "opponent"}` — an opponent's
#     permanent entering, not its own ETB. Firing it as ETB mints a drain on cast.
#   * `graveyard_from_battlefield` / `dealt_damage_to_player` read as `death` /
#     `combat_damage_to_player` but do not have to mean them.
#
# Anything genuinely absent from the vocabulary (`sacrifice`, `discard`, `cycle`,
# `mutate`, the main-phase steps, ...) likewise stays unmapped and stays inert: naming it
# would invent an event the engine cannot execute, and an honest under-count beats a
# confident fabrication.
_EVENT_SYNONYMS = {
    # -> executable (verified against the oracle text of every card that carries them)
    "beginning_of_combat": "begin_combat",
    "beginning_of_upkeep": "upkeep",
    "begin_upkeep": "upkeep",
    "beginning_of_draw_step": "draw_step",
    # -> unexecuted (no simulation change; keeps the honest under-count countable
    #    instead of scattering it across anonymous spellings)
    "leave_battlefield": "leaves_battlefield",
    "leave_the_battlefield": "leaves_battlefield",
    "targeted": "becomes_target",
    "targeted_by_spell": "becomes_target",
    "targeted_by_spell_or_ability": "becomes_target",
    "block": "blocks",
    "blocked": "becomes_blocked",
    "end_combat": "end_of_combat",
    "chapter_I": "saga_chapter",
    "chapter_II": "saga_chapter",
    "chapter_III": "saga_chapter",
}


def canonical_event(event: object) -> object:
    """Map a known re-spelling onto its vocabulary word; pass anything else through."""
    return _EVENT_SYNONYMS.get(event, event) if isinstance(event, str) else event


TARGET_KEYS = {"type", "subtype", "controller", "count", "zone"}
TARGET_CONTROLLERS = {"you", "opponent", "any", "each"}
EFFECT_COMMON_KEYS = {"op", "optional", "condition", "note", "x_basis"}

# What an "X" quantity counts, carried on the effect as "x_basis" (prompt v8+). This is a
# DESCRIPTIVE vocabulary: unknown values are tolerated (treated like "other"), only the
# type is enforced. The engine resolves board-derived bases from live state; cost-side
# bases (mana_paid, life_paid) and player choices stay at the modest default — resolving
# them from live state would be a guess, not a measurement (see tier2._EngineResolver).
X_BASES = frozenset({
    "mana_paid", "chosen", "creatures_you_control", "lands_you_control",
    "artifacts_you_control", "permanents_you_control", "cards_in_hand", "life_paid",
    "counters_on_this", "target_power", "other",
})

# Param type tags
_INT = "int"
_INT_SIGNED = "int_signed"
_INT_OR_X = "int_or_x"
_STR = "str"
_STR_OR_LIST = "str_or_list"
_BOOL = "bool"
_TARGET = "target"

# The closed effect vocabulary: op -> (required params, optional params)
OP_SPECS: dict[str, tuple[dict[str, str], dict[str, str]]] = {
    "add_mana": ({"amount": _INT_OR_X}, {"colors": _STR}),
    "draw": ({"count": _INT_OR_X}, {"who": _STR}),
    "discard": ({"count": _INT_OR_X}, {"who": _STR}),
    "mill": ({"count": _INT_OR_X}, {"who": _STR}),
    "scry": ({"count": _INT_OR_X}, {}),
    "surveil": ({"count": _INT_OR_X}, {}),
    "search_library": (
        {"what": _TARGET, "count": _INT},
        {"to": _STR, "tapped": _BOOL, "shuffle": _BOOL},
    ),
    "shuffle": ({}, {}),
    "destroy": ({"target": _TARGET}, {}),
    "exile": ({"target": _TARGET}, {}),
    "return_to_hand": ({"target": _TARGET}, {}),
    "gain_control": ({"target": _TARGET}, {}),
    "attach": ({"target": _TARGET}, {}),
    "counter_spell": ({}, {"unless_pays": _STR, "target": _TARGET}),
    "deal_damage": ({"amount": _INT_OR_X, "target": _TARGET}, {}),
    "gain_life": ({"amount": _INT_OR_X}, {"who": _STR}),
    "lose_life": ({"amount": _INT_OR_X}, {"who": _STR}),
    "create_token": (
        {"count": _INT_OR_X},
        {"power": _INT_OR_X, "toughness": _INT_OR_X, "types": _STR_OR_LIST, "tapped": _BOOL},
    ),
    "pump": (
        {"power": _INT_SIGNED, "toughness": _INT_SIGNED},
        {"target": _TARGET, "duration": _STR},
    ),
    "add_counter": (
        {"count": _INT_OR_X},
        {"counter_type": _STR, "target": _TARGET, "duration": _STR},
    ),
    "tap": ({"target": _TARGET}, {}),
    "untap": ({"target": _TARGET}, {}),
    "sacrifice": ({"target": _TARGET}, {"who": _STR}),
    "reanimate": ({"target": _TARGET}, {}),
    "extra_turn": ({}, {}),
    "cost_reduction": ({"amount": _INT}, {"applies_to": _STR}),
    "win_game": ({}, {"condition": _STR}),
}

# Gate-2 numeric sanity ceilings per (op, param)
_SANITY_MAX = {
    ("draw", "count"): 20, ("discard", "count"): 20, ("mill", "count"): 60,
    ("deal_damage", "amount"): 40, ("create_token", "count"): 20,
    ("add_mana", "amount"): 20, ("gain_life", "amount"): 99, ("lose_life", "amount"): 99,
}

_ACTIVATED_COST_KEYS = {"mana", "tap", "sacrifice_self", "pay_life", "other"}

# Natural-language variable quantities the LLM uses where a number would go. Accepted as a
# CLOSED set (genuine garbage still rejects); the profile resolves them to a small default,
# matching the existing "X -> 1" convention (an approximate magnitude, documented).
_VARIABLE_QUANTITIES = frozenset({
    "x", "y", "all", "each", "any", "half", "double", "twice", "difference", "that many",
})


def _is_variable_qty(value) -> bool:
    return isinstance(value, str) and value.strip().lower() in _VARIABLE_QUANTITIES


def _check_value(tag: str, value, where: str, errors: list[str]) -> None:
    if tag == _INT:
        if not (isinstance(value, int) and not isinstance(value, bool) and value >= 0):
            errors.append(f"{where}: expected non-negative int, got {value!r}")
    elif tag == _INT_SIGNED:
        ok = (isinstance(value, int) and not isinstance(value, bool)) or (
            isinstance(value, str) and value.upper() in ("X", "-X")
        )
        if not ok:
            errors.append(f"{where}: expected int or 'X'/'-X', got {value!r}")
    elif tag == _INT_OR_X:
        ok = (
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
        ) or _is_variable_qty(value)
        if not ok:
            errors.append(
                f"{where}: expected a non-negative int or a variable (X/all/each/…), "
                f"got {value!r}"
            )
    elif tag == _STR:
        if not isinstance(value, str):
            errors.append(f"{where}: expected string, got {value!r}")
    elif tag == _STR_OR_LIST:
        ok = isinstance(value, str) or (
            isinstance(value, list) and all(isinstance(v, str) for v in value)
        )
        if not ok:
            errors.append(f"{where}: expected string or list of strings, got {value!r}")
    elif tag == _BOOL:
        if not isinstance(value, bool):
            errors.append(f"{where}: expected bool, got {value!r}")
    elif tag == _TARGET:
        if not isinstance(value, dict):
            errors.append(f"{where}: expected target object, got {value!r}")
            return
        # Extra descriptive keys (condition, note, name, exclude, ...) are tolerated —
        # the engine reads only controller/count/type. We validate those, ignore the rest.
        controller = value.get("controller")
        if controller is not None and controller not in TARGET_CONTROLLERS:
            errors.append(f"{where}: bad controller {controller!r}")
        count = value.get("count")
        count_ok = (
            count is None
            or count == "all"
            or (isinstance(count, int) and not isinstance(count, bool) and count >= 1)
            or _is_variable_qty(count)
        )
        if not count_ok:
            errors.append(f"{where}: count must be a positive int, 'all', or a variable")


def unsupported_ops(doc: dict) -> list[str]:
    """Ops present in the CCM that are outside the engine vocabulary (inert, tolerated)."""
    seen: set[str] = set()
    for _ability, effect in _iter_effects(doc):
        op = effect.get("op")
        if op is not None and op not in OP_SPECS:
            seen.add(str(op))
    return sorted(seen)


def validate_schema(doc: dict) -> list[str]:
    """Gate 1: structural validation against schema v1. Returns error strings.

    Tolerance (docs/CARD_SEMANTICS.md): ops, trigger events, and target keys outside the
    vocabulary are KEPT and flagged (unsupported_ops), not rejected — the profile models
    the effects it understands and ignores the rest. Known ops are still validated strictly.
    """
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["document is not a JSON object"]
    if not isinstance(doc.get("name"), str) or not doc.get("name"):
        errors.append("missing/invalid 'name'")
    if doc.get("ccm_version") != CCM_VERSION:
        errors.append(f"ccm_version must be {CCM_VERSION}")
    types = doc.get("types")
    if not (isinstance(types, list) and types and all(isinstance(t, str) for t in types)):
        errors.append("'types' must be a non-empty list of strings")
    cost = doc.get("cost")
    if cost is not None and not (
        isinstance(cost, dict) and isinstance(cost.get("mana", ""), str)
    ):
        errors.append("'cost' must be an object with a string 'mana'")
    if "enters_tapped" in doc and not isinstance(doc["enters_tapped"], bool):
        errors.append("'enters_tapped' must be bool")

    abilities = doc.get("abilities")
    if not isinstance(abilities, list):
        return errors + ["'abilities' must be a list"]

    for i, ability in enumerate(abilities):
        where = f"abilities[{i}]"
        if not isinstance(ability, dict):
            errors.append(f"{where}: not an object")
            continue
        kind = ability.get("kind")
        if kind not in ABILITY_KINDS:
            errors.append(f"{where}: unknown kind {kind!r}")
            continue
        if kind == "triggered":
            trigger = ability.get("trigger")
            event = trigger.get("event") if isinstance(trigger, dict) else None
            if not isinstance(event, str) or not event:
                errors.append(f"{where}: triggered ability needs a trigger.event string")
            # Events outside TRIGGER_EVENTS are tolerated — the profile only executes
            # etb/death/periodic triggers; an unknown event is simply inert.
        if kind == "activated":
            acost = ability.get("cost")
            if not isinstance(acost, dict) or set(acost) - _ACTIVATED_COST_KEYS:
                errors.append(f"{where}: activated cost must use keys {_ACTIVATED_COST_KEYS}")
        if kind == "static":
            if not isinstance(ability.get("note", ""), str):
                errors.append(f"{where}: static note must be a string")
            continue

        effects = ability.get("effects")
        if not (isinstance(effects, list) and effects):
            errors.append(f"{where}: needs a non-empty effects list")
            continue
        for j, effect in enumerate(effects):
            ewhere = f"{where}.effects[{j}]"
            if not isinstance(effect, dict):
                errors.append(f"{ewhere}: not an object")
                continue
            op = effect.get("op")
            if op not in OP_SPECS:
                # Tolerated: an op outside the vocabulary (or a bare note/static effect) is
                # kept and flagged as unsupported (see unsupported_ops); the profile ignores
                # it. Per docs/CARD_SEMANTICS.md — model what we can, don't reject the card.
                continue
            required, optional = OP_SPECS[op]
            # Extra params on a known op are tolerated (descriptive qualifiers the engine
            # ignores); missing REQUIRED params and bad-typed known params still error.
            for param, tag in required.items():
                if param not in effect:
                    errors.append(f"{ewhere}: op {op} missing required param {param}")
                else:
                    _check_value(tag, effect[param], f"{ewhere}.{param}", errors)
            for param, tag in optional.items():
                if param in effect:
                    _check_value(tag, effect[param], f"{ewhere}.{param}", errors)
            if "x_basis" in effect and not isinstance(effect["x_basis"], str):
                errors.append(f"{ewhere}.x_basis: expected string, got {effect['x_basis']!r}")
        if kind == "mana_ability" and isinstance(effects, list):
            ops = {e.get("op") for e in effects if isinstance(e, dict)}
            if not ops <= {"add_mana"}:
                errors.append(f"{where}: mana_ability may only contain add_mana effects")
    return errors


def _norm_mana(text: str) -> str:
    return re.sub(r"\s", "", (text or "")).upper()


def _iter_effects(doc: dict):
    for ability in doc.get("abilities") or []:
        if not isinstance(ability, dict):
            continue
        for effect in ability.get("effects") or []:
            if isinstance(effect, dict):
                yield ability, effect


def lint_against_card(doc: dict, card: Card) -> list[str]:
    """Gate 2: static lint against Scryfall facts. Returns error strings."""
    errors: list[str] = []
    declared = _norm_mana((doc.get("cost") or {}).get("mana", ""))
    actual = _norm_mana(card.mana_cost_str)
    if declared != actual:
        errors.append(f"cost.mana {declared!r} != printed cost {actual!r}")

    type_line = card.type_line.casefold()
    for t in doc.get("types") or []:
        if t.casefold() not in type_line:
            errors.append(f"declared type {t!r} not in type line {card.type_line!r}")

    # Instants/sorceries are one-shot spells: they cannot carry mana/activated/triggered
    # abilities on the battlefield (they never sit there).
    is_pure_spell = ("instant" in type_line or "sorcery" in type_line) and not any(
        t in type_line for t in ("creature", "artifact", "enchantment", "land", "planeswalker")
    )
    if is_pure_spell:
        for ability in doc.get("abilities") or []:
            kind = ability.get("kind") if isinstance(ability, dict) else None
            if kind not in (None, "spell_effect", "static"):
                errors.append(
                    f"instant/sorcery cannot have a {kind!r} ability — use spell_effect"
                )

    for _ability, effect in _iter_effects(doc):
        op = effect.get("op")
        for (sop, param), ceiling in _SANITY_MAX.items():
            if op == sop:
                value = effect.get(param)
                if isinstance(value, int) and value > ceiling:
                    errors.append(f"{op}.{param}={value} exceeds sanity ceiling {ceiling}")

    if card.produced_mana:
        produced = set(card.produced_mana) | {"C"}
        for ability, effect in _iter_effects(doc):
            if ability.get("kind") == "mana_ability" and effect.get("op") == "add_mana":
                colors = effect.get("colors", "")
                letters = normalize_colors(colors)
                if colors and colors != "any" and not letters <= produced:
                    errors.append(
                        f"add_mana colors {colors!r} not within produced_mana "
                        f"{card.produced_mana}"
                    )
    return errors


def normalize_colors(colors: str) -> set[str]:
    """Extract WUBRGC letters from a colors string ('UB', 'U or B', 'u, b' all work).

    Connector words are stripped BEFORE letter extraction — the R in 'or' is not red mana.
    """
    if not isinstance(colors, str) or colors == "any":
        return set()
    cleaned = re.sub(r"\b(?:or|and|mana|of|a|an)\b", " ", colors, flags=re.IGNORECASE)
    return {ch for ch in cleaned.upper() if ch in "WUBRGC"}


_ADD_TEXT_RE = re.compile(r"\badd [^.]*\{")

# Keyword abilities whose EFFECT lives entirely in reminder text. The hallucination half
# of gate 3 reads oracle text with parentheticals stripped, so "Cycling {2} ({2}, Discard
# this card: Draw a card.)" becomes "Cycling {2}" — the word "draw" disappears and a CCM
# that correctly models cycling gets failed for declaring an effect "the text never says".
# That class was 155 of the 240 hallucination quarantines (cycling 113, ward 21,
# landcycling 19, transmute 2) — the compiler was right and the gate was wrong.
#
# Matched against the RAW oracle text; licenses an op for the hallucination check ONLY.
# The omission half is untouched, so a CCM that MISSES an effect still fails. Being
# permissive here is the safe direction: the cost of a false license is one unverified
# op, the cost of a false positive is discarding a correct CCM.
_KEYWORD_IMPLIED_OPS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bcycling\b", re.I), "draw"),               # Cycling N: discard, draw a card
    (re.compile(r"\b\w+cycling\b", re.I), "search_library"),  # land/basic land/typecycling
    (re.compile(r"\bward\b", re.I), "counter_spell"),         # counter it unless they pay
    (re.compile(r"\btransmute\b", re.I), "search_library"),
)


def _keyword_licensed_ops(oracle_text: str) -> set[str]:
    """Ops justified by a keyword whose definition is reminder text (see above)."""
    raw = oracle_text or ""
    return {op for pattern, op in _KEYWORD_IMPLIED_OPS if pattern.search(raw)}


# Textual evidence a declared trigger event must have. Magic is exact: a trigger that
# fires on the wrong event is a DIFFERENT CARD, not an approximation, and the engine
# executes it at full value. These patterns are deliberately anchored against the
# near-misses that were actually being accepted:
#   - "noncombat damage" CONTAINS the substring "combat damage" (Smaug), so the combat
#     pattern uses a negative lookbehind for "non".
#   - Blocking is the OTHER side of combat: "blocks"/"becomes blocked" must not satisfy
#     "attack" (155 cards did).
#   - "When you cast THIS spell" fires once; "whenever you cast A creature spell" fires
#     every time. cast_creature therefore requires an article, not "this" (112 cards).
#   - A land going to the GRAVEYARD is not landfall (42 cards).
_TRIGGER_EVIDENCE: dict[str, re.Pattern[str]] = {
    "etb": re.compile(r"\benters?\b|\bentering\b", re.I),
    "death": re.compile(r"\bdies\b|\bdie\b|\bput into a graveyard from the battlefield\b"
                        r"|\bis put into a graveyard\b", re.I),
    "creature_dies": re.compile(r"\bdies\b|\bdie\b", re.I),
    "upkeep": re.compile(r"\bupkeep\b", re.I),
    "draw_step": re.compile(r"\bdraw step\b", re.I),
    "end_step": re.compile(r"\bend step\b|\bbeginning of the end\b", re.I),
    "end_of_combat": re.compile(r"\bend of combat\b", re.I),
    "begin_combat": re.compile(r"\bbeginning of combat\b|\bbeginning of each combat\b", re.I),
    "attack": re.compile(r"\battacks?\b|\battacking\b|\bdeclare attackers\b", re.I),
    "blocks": re.compile(r"\bblocks\b|\bblocking\b", re.I),
    "becomes_blocked": re.compile(r"\bbecomes blocked\b|\bbecome blocked\b", re.I),
    # Deliberately "a ... spell", not "a creature spell": tribal payoffs say "Whenever you
    # cast a Dog spell" and a Dog spell IS a creature spell (Rin and Seri). Requiring the
    # literal word would discard correct CCMs. The article is what carries the weight —
    # it still rejects "casts THIS spell", which is the self_cast confusion.
    "cast_creature": re.compile(r"\bcasts? (?:a|an|another|your)\b[^.]*\bspell\b", re.I),
    "self_cast": re.compile(r"\bcasts? this (?:spell|card)\b", re.I),
    "cast_spell": re.compile(r"\bcasts?\b", re.I),
    "opponent_casts_spell": re.compile(r"\bopponents? casts?\b", re.I),
    "landfall": re.compile(r"\blandfall\b|\blands? enters?\b|\bland entering\b"
                           r"|\bplays? (?:a|an|another) land\b", re.I),
    "combat_damage_to_player": re.compile(
        r"(?<!non)combat damage to|deals damage to (?:a |target |an )?(?:player|opponent)",
        re.I),
    "dealt_damage": re.compile(r"\bis dealt\b|\bdealt damage\b", re.I),
    "saga_chapter": re.compile(r"\bsaga\b|\bchapter\b|^\s*(?:I{1,3}|IV|V)\s*(?:,|—|-)", re.I | re.M),
    "leaves_battlefield": re.compile(r"\bleaves? the battlefield\b|\bleave the battlefield\b", re.I),
    "becomes_target": re.compile(r"\bbecomes the target\b", re.I),
    "tap_for_mana": re.compile(r"\btaps? [^.]*for mana\b", re.I),
    "gain_life": re.compile(r"\bgains? life\b|\bgain \d+ life\b", re.I),
    "lose_life": re.compile(r"\bloses? life\b|\blose \d+ life\b", re.I),
    "counter_added": re.compile(r"\bcounter is put\b|\bcounters? (?:is|are) put\b", re.I),
    "activate_ability": re.compile(r"\bactivates?\b", re.I),
}

# Keyword abilities whose TRIGGER lives entirely in reminder text — the same problem
# _KEYWORD_IMPLIED_OPS solves for ops. Cascade really is a cast trigger, modular really
# is a death trigger, but the parenthetical saying so is stripped before the check.
_KEYWORD_IMPLIED_EVENTS: tuple[tuple[re.Pattern[str], frozenset[str]], ...] = (
    (re.compile(r"\bcascade\b|\bstorm\b|\bmagecraft\b|\bprowess\b|\bextort\b", re.I),
     frozenset({"cast_spell", "self_cast"})),
    (re.compile(r"\bmodular\b|\bsoulshift\b|\bpersist\b|\bundying\b|\bafterlife\b"
                r"|\bhaunt\b|\bvengeance\b", re.I), frozenset({"death"})),
    (re.compile(r"\bexalted\b|\bbattle cry\b|\bmentor\b|\bmelee\b|\bafflict\b"
                r"|\bdethrone\b|\bmyriad\b|\bannihilator\b|\braid\b|\bboast\b"
                r"|\btraining\b|\bmobilize\b", re.I), frozenset({"attack"})),
    # Squad and living weapon are ENTERS triggers, not combat ones ("When this creature
    # enters, create that many tokens that are copies of it").
    (re.compile(r"\bsquad\b|\bliving weapon\b", re.I), frozenset({"etb"})),
    # A Saga's reminder text is "As this Saga enters AND AFTER YOUR DRAW STEP, add a lore
    # counter" — so etb and draw_step are both literally supported, they just live inside
    # the parenthetical the check strips. saga_chapter is the preferred answer (the prompt
    # says so) but the other two are not hallucinations and must not be discarded.
    (re.compile(r"\bsaga\b|\blore counter\b|\bread ahead\b", re.I),
     frozenset({"saga_chapter", "etb", "draw_step", "upkeep"})),
    (re.compile(r"\bbushido\b|\bflanking\b|\brampage\b|\bprovoke\b", re.I),
     frozenset({"blocks", "becomes_blocked", "attack"})),
    (re.compile(r"\brenown\b|\bbloodthirst\b|\bingest\b|\bpoisonous\b|\bbushido\b", re.I),
     frozenset({"combat_damage_to_player", "attack"})),
    (re.compile(r"\bevolve\b|\bfabricate\b|\bexploit\b|\bdevour\b|\briot\b|\bamass\b"
                r"|\bunearth\b|\bembalm\b|\beternalize\b|\bdisturb\b|\bbackup\b"
                r"|\bfor mirrodin\b|\bsoulbond\b", re.I), frozenset({"etb"})),
    # Champion's reminder text is BOTH halves: "When this enters, sacrifice it unless you
    # exile another creature... When this leaves the battlefield, that card returns."
    (re.compile(r"\bchampion\b", re.I), frozenset({"etb", "leaves_battlefield"})),
    (re.compile(r"\becho\b|\bcumulative upkeep\b|\bsuspend\b|\bvanishing\b|\bfading\b",
                re.I), frozenset({"upkeep"})),
    (re.compile(r"\bward\b|\bmiracle\b|\bsplice\b|\bcasualty\b|\bblitz\b|\bemerge\b"
                r"|\bmorph\b|\bdisguise\b|\bflashback\b|\bescape\b|\bdredge\b", re.I),
     frozenset({"cast_spell", "self_cast", "etb"})),
    (re.compile(r"\bstart your engines\b|\bmax speed\b", re.I),
     frozenset({"attack", "end_step", "etb"})),
)


def _keyword_licensed_events(oracle_text: str) -> set[str]:
    """Trigger events justified by a keyword whose definition is reminder text."""
    raw = oracle_text or ""
    out: set[str] = set()
    for pattern, events in _KEYWORD_IMPLIED_EVENTS:
        if pattern.search(raw):
            out |= events
    return out


def _check_trigger_events(doc: dict, card: Card, text: str) -> list[str]:
    """Every declared trigger event must have textual support.

    Permissive in the same direction as the rest of gate 3: "other" always passes, an
    event outside the vocabulary passes (the engine drops it anyway), and reminder-text
    keywords license their event. What does NOT pass is a vocabulary event whose text
    isn't there — that is a card doing something it cannot do.
    """
    errors: list[str] = []
    licensed = _keyword_licensed_events(card.oracle_text)
    for ability in doc.get("abilities") or []:
        if not isinstance(ability, dict) or ability.get("kind") != "triggered":
            continue
        trigger = ability.get("trigger")
        event = trigger.get("event") if isinstance(trigger, dict) else None
        if not isinstance(event, str) or event == "other" or event in licensed:
            continue
        pattern = _TRIGGER_EVIDENCE.get(event)
        if pattern is None or pattern.search(text):
            continue
        errors.append(
            f"trigger event '{event}' has no support in the oracle text "
            f"(use a matching event or 'other')"
        )
    return errors


def cross_check(doc: dict, card: Card) -> list[str]:
    """Gate 3: bidirectional cross-check against the independent rung-1 heuristics.

    Catches both omissions (heuristics see draw, CCM has none) and hallucinations
    (CCM declares draw, text never says draw). Presence checks only — counts and
    conditions are the compiler's job to get right, ours to spot-audit.
    """
    errors: list[str] = []
    fx = tags.analyze(card)
    text = re.sub(r"\([^)]*\)", "", card.oracle_text or "").casefold()
    licensed = _keyword_licensed_ops(card.oracle_text)

    ops_present: set[str] = set()
    triggered_ops: set[str] = set()
    for ability, effect in _iter_effects(doc):
        op = effect.get("op")
        ops_present.add(op)
        if ability.get("kind") == "triggered":
            triggered_ops.add(op)
    has_mana_ability = any(
        a.get("kind") == "mana_ability" for a in doc.get("abilities") or []
        if isinstance(a, dict)
    )

    if (fx.draw_cards > 0 or fx.engine_draw > 0) and "draw" not in ops_present:
        errors.append("oracle text draws cards but CCM has no draw effect")
    if "draw" in ops_present and "draw" not in text and "draw" not in licensed:
        errors.append("CCM declares draw but oracle text never says draw")
    if fx.counterspell and "counter_spell" not in ops_present:
        errors.append("oracle text counters a spell but CCM has no counter_spell")
    if ("counter_spell" in ops_present and "counter" not in text
            and "counter_spell" not in licensed):
        errors.append("CCM declares counter_spell but text never says counter")
    if (fx.fetches_land or fx.tutor) and "search_library" not in ops_present:
        errors.append("oracle text searches the library but CCM has no search_library")
    if ("search_library" in ops_present and "search" not in text
            and "search_library" not in licensed):
        errors.append("CCM declares search_library but text never says search")
    if not card.is_land and _ADD_TEXT_RE.search(text) and "add_mana" not in ops_present:
        errors.append("oracle text adds mana but CCM has no add_mana")
    # Typed lands (shocks/duals) carry their mana ability as reminder text or via land
    # types, so "add" may be absent from stripped text; produced_mana is the referee.
    intrinsic_mana = card.is_land and bool(card.produced_mana)
    if (
        (has_mana_ability or "add_mana" in ops_present)
        and "add" not in text
        and not intrinsic_mana
    ):
        errors.append("CCM adds mana but text never says add")
    if fx.removal > 0 and not ops_present & {"destroy", "exile", "deal_damage"}:
        errors.append("oracle text is targeted removal but CCM has no removal effect")
    if fx.board_wipe:
        wipes = [
            e for _a, e in _iter_effects(doc)
            if e.get("op") in {"destroy", "exile", "deal_damage"}
            and (
                (e.get("target") or {}).get("count") == "all"
                or (e.get("target") or {}).get("controller") == "each"
            )
        ]
        if not wipes:
            errors.append("oracle text is a board wipe but CCM has no all/each removal")
    if "extra_turn" in ops_present and "extra turn" not in text:
        errors.append("CCM declares extra_turn but text never says extra turn")
    if "win_game" in ops_present and "win" not in text:
        errors.append("CCM declares win_game but text never says win")
    if card.is_land and fx.enters_tapped and not doc.get("enters_tapped"):
        errors.append("land enters tapped per oracle text; CCM must set enters_tapped")
    errors += _check_trigger_events(doc, card, text)
    return errors


def validate(doc: dict, card: Card) -> dict[str, list[str]]:
    """Run all gates. Gate 2/3 only run when gate 1 passes (structure is trustworthy)."""
    gate1 = validate_schema(doc)
    if gate1:
        return {"schema": gate1, "lint": [], "cross_check": []}
    return {
        "schema": [],
        "lint": lint_against_card(doc, card),
        "cross_check": cross_check(doc, card),
    }
