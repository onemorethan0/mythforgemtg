"""GBNF grammar for CCM output — makes gate-1 failures structurally impossible.

llama.cpp constrains sampling to a grammar, so a token that would break the schema is
never emitted. This closes the two failure classes the retry loop was paying for:

  * **unparseable JSON** — 1,148 of 31,028 accepted CCMs needed `json_repair`, and 22
    more were unrepairable. Under a grammar the model cannot emit a trailing comma, a
    Python literal, or an unterminated string in the first place.
  * **gate-1 schema rejections** — 557 of the 1,168 recorded gate errors. Measured over
    the ledger, the buckets are: param type mismatch (219), empty/missing effects (97),
    op missing a required param (80), mana_ability impurity (71), bad target
    controller/count (~70), invented activated-cost key (9).

Of those, everything except "op missing a required param" is expressible here, so the
grammar is aimed at ~460 of the 557. The remaining 80 need the model to know which
params an op takes — that is a *training* problem, not a decoding one, and is what the
fine-tuned compiler model addresses.

MEASURED (2026-08-11, qwen3:14b at temperature 0, 25 cards drawn from the schema-
quarantined set — cards that had NEVER compiled). Same prompt, same exemplars, same
model, same retry budget; only the `grammar` field differed:

    accepted, free sampling      2 / 25   ( 8%)
    accepted, grammar-bound     17 / 25   (68%)     <- 15 cards rescued
    gate-1 failures             23 -> 4
    mean attempts             1.96 -> 1.36
    median seconds/card        4.3 -> 3.1

The 8 that still fail are exactly the two classes this cannot reach, which is the
prediction holding rather than a surprise:

  * 3x `search_library missing required param count` and 1x `cost_reduction.amount`
    wanting a strict int. GBNF is context-free, so the rule for a param cannot depend on
    which `op` the enclosing object declared — the open-op branch stays live and permits
    both omitting a required param and using the looser shared `quantity` rule. Making
    it bind would mean closing the op vocabulary, which costs far more than it buys.
  * 3x cross_check and 1x lint — semantic errors (a mana ability the text does not
    support, a trigger event with no textual evidence). No decoding constraint can fix a
    CCM that is well-formed and wrong. That is the fine-tune's half of the problem.

WHAT THIS DELIBERATELY DOES NOT CLOSE
-------------------------------------
`validate_schema` is tolerant on purpose (docs/engine/CARD_SEMANTICS.md): an op outside
`OP_SPECS`, a trigger event outside `TRIGGER_EVENTS`, and extra params on a known op are
all KEPT and flagged rather than rejected, because the profile models what it understands
and ignores the rest. That tolerance is load-bearing — 5,531 of 31,028 stored cards
(17.8%) carry an unsupported op, across 404 distinct op names. Closing the vocabulary
would force the model to pick a wrong-but-legal op instead of an honest unsupported one,
which is exactly the near-miss the project treats as a defect. So:

  * `op` stays an OPEN string. Any op name is emittable.
  * `trigger.event` stays an OPEN string. Any event is emittable.
  * abilities, effects, targets and triggers all accept descriptive extra keys.

WHAT IT NARROWS, AND WHAT THAT COSTS
------------------------------------
Replayed against the whole store, the grammar would have blocked **901 of 31,028
gate-passing documents (2.90%)**, and every one is accounted for:

* **481 — deliberate narrowings on inert ops.** Quantity params
  (`count`/`amount`/`power`/`toughness`) accept an integer or a word from
  `_VARIABLE_QUANTITIES` (plus `X`/`-X`), and `target.controller` is closed to
  `TARGET_CONTROLLERS`. That blocks prose quantities ("remaining", "up to two", "number
  of creatures in your party") and stray controllers (`owner`, `defending`). **364 of
  the 380 prose quantities and all 51 stray controllers sit on ops outside `OP_SPECS`**,
  which the engine never executes — so nothing the simulation reads changes, and the
  effect's `note`/`condition` keys still carry the prose verbatim. Param type mismatch
  is the single biggest gate-1 bucket (219), so this is where most of the win is.
* **420 — nested-ability leakage, which the grammar SHOULD block.** These put a whole
  ability inside an effects list (`{"kind": "static", "note": ...}`) or a bare ability at
  the document root. That content belongs in a sibling ability; the grammar pushes it
  there.

Key names are closed sets — that is what makes the quantity and target constraints bind
at all — but they are the COMPLETE sets observed across the store, not a popularity cut.
An earlier >=20-uses cut blocked 6.41%: the tail is thin per key but wide.

`rung` is NOT emittable. The compiler owns the tier (compiler.compile_card sets it), and
letting the model self-declare one is how 1,897 cards ended up claiming rung 3.

The grammar is GENERATED from the constants in `ccm.py` rather than hand-written, so a
change to `ABILITY_KINDS`, `_ACTIVATED_COST_KEYS`, `TARGET_CONTROLLERS` or
`_VARIABLE_QUANTITIES` cannot leave the grammar behind. `test_ccm_grammar.py` pins that.
"""

from __future__ import annotations

from mythgauntlet.semantics.ccm import (
    ABILITY_KINDS,
    EFFECT_COMMON_KEYS,
    OP_SPECS,
    TARGET_CONTROLLERS,
    TARGET_KEYS,
    _ACTIVATED_COST_KEYS,
    _VARIABLE_QUANTITIES,
)

# Descriptive keys the model emits that no schema constant names.
#
# These are the COMPLETE sets observed across the 31,028-card store, not a popularity
# cut. A first pass took only the keys used >=20 times and the conformance check
# (tests/engine/test_ccm_grammar.py::test_grammar_accepts_the_whole_store) put the
# blocked share at 6.41% — the long tail is thin per-key but wide, so trimming it
# rejected 1,988 documents the gates had accepted. Taking every observed key keeps the
# sets CLOSED (which is what makes the quantity and target constraints bind at all)
# while costing essentially nothing.
#
# Structural leakage is the deliberate exception, and it is identified by `kind`, not by
# shape. An effect carrying `kind` is a whole ability nested inside an effects list
# (`{"kind": "static", "note": ...}` 279 cards, `{"kind": "triggered", "trigger": {...},
# "effects": [...]}` 102) — that content belongs in a sibling ability, so `kind` and
# `trigger` are excluded and the grammar pushes it there.
#
# `effects` and `cost` are NOT excluded, because on their own they are legitimate
# sub-structure on an unsupported op: `{"op": "roll_dice", "effects": [...]}` and
# `{"op": "pay_mana", "cost": {"mana": "{1}{R}"}}` (208 and 182 cards respectively).
# Every leakage case also carries `kind`, so excluding `kind` alone catches all of it
# without costing these.
_EFFECT_KEYS = frozenset({
    'abilities', 'ability', 'action', 'add_counter', 'add_greatest_power', 'add_type',
    'additional', 'additional_counters', 'additional_dice', 'after', 'amount', 'any_order',
    'any_player', 'applies_to', 'apply_to', 'as', 'as_sorcery', 'attach', 'attached_to',
    'attacking', 'bottom', 'by', 'can_block', 'choose', 'choose_color',
    'choose_new_targets', 'color', 'colors', 'condition', 'controller', 'copies',
    'copies_become_tokens', 'cost', 'count', 'count_put', 'counter', 'counter_type',
    'counters',
    'dice', 'die', 'discard', 'divided', 'duration', 'each', 'each_player', 'effect',
    'effect_if_win', 'effects', 'effects_if_lose', 'effects_if_win', 'escape_cost',
    'even_result',
    'event', 'exclude', 'exile', 'exile_rest', 'face_down', 'face_up', 'finality_counter',
    'flashback_cost', 'followed_by', 'from', 'greater_than', 'ignore_rolls', 'instead_of',
    'into', 'land_type', 'land_types', 'level', 'location', 'mana', 'mana_cost',
    'mana_value', 'max', 'max_mana_value', 'may_choose_new_targets', 'may_play_exiled_card',
    'name', 'new_target', 'new_targets', 'no_mana_cost', 'note', 'note2', 'odd_result',
    'op', 'op2', 'opponent', 'opponent_target', 'option', 'option1', 'option2', 'optional',
    'options', 'order', 'other', 'other_target', 'owner', 'permanents_you_control', 'phase',
    'plus', 'position', 'power', 'property', 'protection', 'protection_from',
    'protection_type', 'put', 'put_back', 'put_into', 'put_into_graveyard', 'put_into_hand',
    'put_rest', 'put_rest_on_bottom', 'random', 'random_order', 'reorder', 'repeat',
    'repeated', 'rest', 'rest_to', 'reveal', 'rounded_up', 'same_name', 'search_zones',
    'second_target', 'secret', 'separate_into', 'shared_card_type', 'shuffle',
    'shuffle_rest', 'sides', 'source', 'source_colors', 'spell_type', 'step', 'subtype',
    'subtypes', 'suspended_card', 'tap', 'tapped', 'target', 'target1', 'target2',
    'target_opponent', 'targets', 'text', 'then', 'this_turn', 'timing', 'to', 'token',
    'token_type', 'top', 'top_or_bottom', 'toughness', 'transform', 'type', 'types',
    'under_control', 'unless', 'unless_pays', 'until', 'until_end_of_turn', 'vs', 'what',
    'when', 'where', 'who', 'with', 'without_cost', 'without_mana_cost',
    'without_paying_mana_cost', 'x', 'x_basis', 'y_basis', 'zone', 'zones',
})

_ABILITY_EXTRA_KEYS = frozenset({'abilities', 'condition', 'note', 'optional'})

# Trigger-object keys beyond `event`. `unverified_event` (400 uses) is the compiler's own
# audit marker and must survive.
_TRIGGER_EXTRA_KEYS = frozenset({
    'chapter', 'color', 'condition', 'controller', 'count', 'counter_type', 'exclude_self',
    'for_mana', 'note', 'other', 'subtype', 'target', 'token', 'type', 'unverified_event',
    'zone',
})

# Target-object keys. TARGET_KEYS is what the engine reads; the rest are descriptive
# qualifiers `_check_value` already tolerates.
_TARGET_EXTRA_KEYS = frozenset({
    'action', 'amount', 'any', 'attached_to', 'attacking', 'bottom', 'can_enchant',
    'card_type', 'choice', 'color', 'colors', 'condition', 'controller', 'controller_type',
    'cost', 'count', 'counter', 'counter_type', 'duration', 'event', 'exclude',
    'exclude_self', 'exiled', 'exiled_with', 'face_down', 'face_up', 'from', 'from_single',
    'from_top', 'is_enchantment', 'is_land', 'is_noncreature', 'is_token', 'land_subtype',
    'location', 'mana_cost', 'mana_value', 'max', 'max_count', 'name', 'nonland',
    'not_cast', 'note', 'optional', 'or', 'order', 'other', 'owner', 'permanent',
    'permanent_type', 'position', 'power', 'random', 'repeat', 'same', 'self', 'shuffle',
    'source', 'source_controller', 'state', 'status', 'step', 'subtype', 'subtypes',
    'symbols', 'tapped', 'this_turn', 'to', 'top', 'toughness', 'transformed', 'type',
    'until', 'who', 'x_basis', 'zone',
})

_QUANTITY_PARAMS = frozenset({"count", "amount", "power", "toughness"})
_TARGET_PARAMS = frozenset({"target", "what"})


def _op_param_keys() -> frozenset[str]:
    """Every param name any op in the closed vocabulary declares."""
    keys: set[str] = set()
    for required, optional in OP_SPECS.values():
        keys |= set(required) | set(optional)
    return frozenset(keys)


def effect_keys() -> frozenset[str]:
    """The closed key set for an effect object (narrowing 3 in the module docstring)."""
    return _op_param_keys() | frozenset(EFFECT_COMMON_KEYS) | _EFFECT_KEYS


def target_keys() -> frozenset[str]:
    return frozenset(TARGET_KEYS) | _TARGET_EXTRA_KEYS


def _lit(text: str) -> str:
    """A GBNF string literal matching exactly `text`."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _json_key(name: str) -> str:
    """A GBNF literal matching the JSON-quoted key `name` — i.e. the six characters
    `"count"` including its quotes, which in GBNF source reads `"\\"count\\""`."""
    return _lit(f'"{name}"')


def _json_str(value: str) -> str:
    """A GBNF literal matching the JSON string `value` (quotes included)."""
    return _lit(f'"{value}"')


def _alt(options) -> str:
    return " | ".join(options)


def _key_alt(names) -> str:
    """Alternation over JSON-quoted key names, sorted for a stable grammar."""
    return _alt(_json_key(n) for n in sorted(names))


def _quoted_word_alt(words) -> str:
    """Alternation over JSON string literals, sorted for a stable grammar."""
    return _alt(_json_str(w) for w in sorted(words))


def _variable_quantity_words() -> list[str]:
    """Quantity words the validator accepts, in every casing it accepts them in.

    `_is_variable_qty` lowercases before comparing and `_INT_SIGNED` separately allows
    `X`/`-X` in upper case, so the grammar has to offer both — the store's 4,430 `"X"`
    values would otherwise be unreachable.
    """
    words: set[str] = set()
    for word in _VARIABLE_QUANTITIES:
        words.add(word)
        words.add(word.upper())
        words.add(word.capitalize())
    words |= {"X", "-X", "x", "-x"}
    return sorted(words)


def build_grammar() -> str:
    """Return the GBNF grammar for a CCM document."""
    kinds = sorted(ABILITY_KINDS)
    assert set(kinds) == {
        "spell_effect", "activated", "triggered", "static", "mana_ability"
    }, f"ABILITY_KINDS changed ({kinds}) — the per-kind rules below must change with it"

    lines: list[str] = [
        "# GENERATED by mythgauntlet.semantics.ccm_grammar.build_grammar().",
        "# Do not edit by hand — edit the constants in ccm.py.",
        "",
        "root ::= ccm",
        "",
        "# --- document ------------------------------------------------------------",
        "# Key order is fixed (GBNF cannot express an unordered object); it matches the",
        "# order the prompt's exemplars use, so the model is never steered off its habit.",
        'ccm ::= "{" ws k-name ws "," ws k-version'
        ' ws ("," ws k-cost)? ws "," ws k-types'
        ' ws ("," ws k-tapped)? ws "," ws k-abilities ws "}"',
        "",
        f"k-name ::= {_json_key('name')} ws \":\" ws nonempty-string",
        f"k-version ::= {_json_key('ccm_version')} ws \":\" ws \"1\"",
        f"k-cost ::= {_json_key('cost')} ws \":\" ws cost-obj",
        f"k-types ::= {_json_key('types')} ws \":\" ws string-list",
        f"k-tapped ::= {_json_key('enters_tapped')} ws \":\" ws boolean",
        f"k-abilities ::= {_json_key('abilities')} ws \":\" ws abilities",
        "",
        "# cost.mana must be a string (gate 2 then checks it equals the printed cost).",
        f"cost-obj ::= \"{{\" ws {_json_key('mana')} ws \":\" ws string"
        " (ws \",\" ws generic-pair)* ws \"}\"",
        "",
        "# A vanilla creature has no abilities, so the list may be empty.",
        'abilities ::= "[" ws (ability (ws "," ws ability)*)? ws "]"',
        f"ability ::= {_alt('ab-' + k.replace('_', '-') for k in kinds)}",
        "",
        "# --- abilities, dispatched on kind ---------------------------------------",
        "# Every kind except static REQUIRES a non-empty effects list (97 gate errors).",
    ]

    def kind_pair(kind: str) -> str:
        return f"{_json_key('kind')} ws \":\" ws {_json_str(kind)}"

    lines += [
        f"ab-spell-effect ::= \"{{\" ws {kind_pair('spell_effect')}"
        " ab-opts ws \",\" ws k-effects ab-opts ws \"}\"",
        "",
        "# A mana ability may contain ONLY add_mana effects (71 gate errors).",
        f"ab-mana-ability ::= \"{{\" ws {kind_pair('mana_ability')}"
        " ab-opts (ws \",\" ws k-acost)? ab-opts ws \",\" ws k-mana-effects"
        " ab-opts ws \"}\"",
        "",
        "# An activated cost may use ONLY the five closed keys (9 gate errors); anything",
        "# else — discarding, exiling, sacrificing another permanent — goes in \"other\".",
        f"ab-activated ::= \"{{\" ws {kind_pair('activated')}"
        " ab-opts ws \",\" ws k-acost ab-opts ws \",\" ws k-effects ab-opts ws \"}\"",
        "",
        "# trigger.event stays an OPEN string — see the module docstring.",
        f"ab-triggered ::= \"{{\" ws {kind_pair('triggered')}"
        " ab-opts ws \",\" ws k-trigger ab-opts ws \",\" ws k-effects ab-opts ws \"}\"",
        "",
        "# static is the escape hatch: a note, no effects required.",
        f"ab-static ::= \"{{\" ws {kind_pair('static')} ab-opts ws \"}}\"",
        "",
        f"k-effects ::= {_json_key('effects')} ws \":\" ws effects",
        f"k-mana-effects ::= {_json_key('effects')} ws \":\" ws mana-effects",
        f"k-acost ::= {_json_key('cost')} ws \":\" ws activated-cost",
        f"k-trigger ::= {_json_key('trigger')} ws \":\" ws trigger-obj",
        "",
        "ab-opts ::= (ws \",\" ws ab-opt)*",
        f"ab-opt ::= ({_key_alt(_ABILITY_EXTRA_KEYS)}) ws \":\" ws value",
        "",
        "# --- activated cost (closed key set) -------------------------------------",
        'activated-cost ::= "{" ws (acost-pair (ws "," ws acost-pair)*)? ws "}"',
        f"acost-pair ::= {_alt([
            f'{_json_key("mana")} ws ":" ws string',
            f'{_json_key("tap")} ws ":" ws boolean',
            f'{_json_key("sacrifice_self")} ws ":" ws boolean',
            f'{_json_key("pay_life")} ws ":" ws integer',
            f'{_json_key("other")} ws ":" ws string',
        ])}",
        "",
        "# --- trigger -------------------------------------------------------------",
        f"trigger-obj ::= \"{{\" ws {_json_key('event')} ws \":\" ws string"
        " (ws \",\" ws trigger-opt)* ws \"}\"",
        f"trigger-opt ::= ({_key_alt(_TRIGGER_EXTRA_KEYS)}) ws \":\" ws value",
        "",
        "# --- effects -------------------------------------------------------------",
        'effects ::= "[" ws effect (ws "," ws effect)* ws "]"',
        'mana-effects ::= "[" ws mana-effect (ws "," ws mana-effect)* ws "]"',
        "",
        "# `op` is an OPEN string: the vocabulary is deliberately not closed here. It is",
        "# also OPTIONAL — `validate_schema` reads `effect.get(\"op\")` and skips an effect",
        "# whose op is absent, so a bare {\"note\": \"...\"} effect is legal and 33 stored",
        "# cards use one. (The 276 cards that put a whole ABILITY in an effects list are a",
        "# different thing and stay blocked: `kind` is not an effect key.)",
        f"effect ::= \"{{\" ws effect-pair (ws \",\" ws effect-pair)* ws \"}}\"",
        f"mana-effect ::= \"{{\" ws {_json_key('op')} ws \":\" ws {_json_str('add_mana')}"
        " (ws \",\" ws effect-pair)* ws \"}\"",
        "",
        "# Quantity and target params are type-constrained; every other key takes any",
        "# JSON value, which is what keeps descriptive extras expressible.",
        f"effect-pair ::= {_alt([
            f'{_json_key("op")} ws ":" ws string',
            f'({_key_alt(_QUANTITY_PARAMS)}) ws ":" ws quantity',
            f'({_key_alt(_TARGET_PARAMS)}) ws ":" ws target-obj',
            f'{_json_key("x_basis")} ws ":" ws string',
            f'({_key_alt(effect_keys() - _QUANTITY_PARAMS - _TARGET_PARAMS - {"op", "x_basis"})}) ws ":" ws value',
        ])}",
        "",
        "# --- target --------------------------------------------------------------",
        'target-obj ::= "{" ws (target-pair (ws "," ws target-pair)*)? ws "}"',
        f"target-pair ::= {_alt([
            f'{_json_key("controller")} ws ":" ws ({_quoted_word_alt(TARGET_CONTROLLERS)})',
            f'{_json_key("count")} ws ":" ws target-count',
            f'({_key_alt(target_keys() - {"controller", "count"})}) ws ":" ws value',
        ])}",
        "target-count ::= pos-integer | quantity-word",
        "",
        "# --- scalars -------------------------------------------------------------",
        "quantity ::= integer | quantity-word",
        f"quantity-word ::= {_quoted_word_alt(_variable_quantity_words())}",
        'integer ::= "-"? ("0" | [1-9] [0-9]*)',
        'pos-integer ::= [1-9] [0-9]*',
        'boolean ::= "true" | "false"',
        "",
        'string-list ::= "[" ws string (ws "," ws string)* ws "]"',
        'string ::= "\\"" char* "\\""',
        'nonempty-string ::= "\\"" char+ "\\""',
        # A JSON string body: anything but a raw quote, backslash or control char.
        'char ::= [^"\\\\\\x00-\\x1F] | "\\\\" (["\\\\bfnrt/] | "u" hex hex hex hex)',
        "hex ::= [0-9a-fA-F]",
        "",
        "# Generic JSON value, for the descriptive keys the schema tolerates.",
        "value ::= string | integer | boolean | \"null\" | array | object",
        'array ::= "[" ws (value (ws "," ws value)*)? ws "]"',
        'object ::= "{" ws (generic-pair (ws "," ws generic-pair)*)? ws "}"',
        'generic-pair ::= string ws ":" ws value',
        "",
        # Newlines are allowed so a model that pretty-prints is not fought; the compiler
        # parses either shape.
        'ws ::= [ \\t\\n\\r]*',
        "",
    ]
    return "\n".join(lines)


#: The grammar, built once at import. `compiler.LlamaSwapClient` sends this to
#: llama-server as the `grammar` field on /v1/chat/completions.
CCM_GRAMMAR = build_grammar()


# Structural keys the compiler adds AFTER the model responds (compile_card), so they are
# never part of what the grammar has to accept.
_COMPILER_ADDED_KEYS = frozenset({"rung", "provenance", "unsupported_ops"})
_TOP_LEVEL_KEYS = frozenset({
    "name", "ccm_version", "cost", "types", "enters_tapped", "abilities",
})
_ABILITY_KEYS = frozenset({"kind", "effects", "trigger", "cost"}) | _ABILITY_EXTRA_KEYS


def violations(doc: dict) -> list[str]:
    """Constraints the grammar would have prevented, as human-readable strings.

    A PARALLEL implementation of `build_grammar()`'s restrictions, in Python. It exists
    because there is no GBNF engine in-process: this is how the grammar is regression-
    tested against the real store (`test_ccm_grammar.py`) and how an audit can ask "would
    a constrained model have produced this?" without a llama.cpp round trip.

    Being a second implementation, it can drift from the grammar it mirrors. Both are
    driven by the same constants in `ccm.py`, so the drift surface is the hand-written
    structure — which `test_ccm_grammar.py` pins case by case.

    An empty list does NOT mean the document is valid: `ccm.validate` is the authority on
    that, and the grammar is deliberately a superset of it (see the module docstring).
    """
    out: list[str] = []
    qwords = set(_variable_quantity_words())
    eff_keys = effect_keys()
    tgt_keys = target_keys()

    def quantity(where: str, value) -> None:
        ok = (isinstance(value, int) and not isinstance(value, bool)) or (
            isinstance(value, str) and value in qwords)
        if not ok:
            out.append(f"{where}: quantity {value!r} is neither an integer nor a variable")

    def target(where: str, value) -> None:
        if not isinstance(value, dict):
            out.append(f"{where}: target must be an object, got {value!r}")
            return
        for key in value:
            if key not in tgt_keys:
                out.append(f"{where}: unknown target key {key!r}")
        controller = value.get("controller")
        if controller is not None and controller not in TARGET_CONTROLLERS:
            out.append(f"{where}: controller {controller!r} outside {sorted(TARGET_CONTROLLERS)}")
        count = value.get("count")
        if count is not None:
            ok = (isinstance(count, int) and not isinstance(count, bool) and count >= 1) or (
                isinstance(count, str) and count in qwords)
            if not ok:
                out.append(f"{where}: target count {count!r} is neither a positive int nor a variable")

    for key in doc:
        if key not in _TOP_LEVEL_KEYS and key not in _COMPILER_ADDED_KEYS:
            out.append(f"top level: unknown key {key!r}")
    if doc.get("ccm_version") != 1:
        out.append(f"top level: ccm_version must be 1, got {doc.get('ccm_version')!r}")
    cost = doc.get("cost")
    if isinstance(cost, dict) and not isinstance(cost.get("mana", ""), str):
        out.append(f"cost.mana must be a string, got {cost.get('mana')!r}")

    for i, ability in enumerate(doc.get("abilities") or []):
        where = f"abilities[{i}]"
        if not isinstance(ability, dict):
            out.append(f"{where}: not an object")
            continue
        for key in ability:
            if key not in _ABILITY_KEYS:
                out.append(f"{where}: unknown ability key {key!r}")
        kind = ability.get("kind")
        if kind not in ABILITY_KINDS:
            out.append(f"{where}: kind {kind!r} outside {sorted(ABILITY_KINDS)}")
            continue
        effects = ability.get("effects")
        if kind != "static" and not (isinstance(effects, list) and effects):
            out.append(f"{where}: {kind} requires a non-empty effects list")
        if kind == "activated":
            acost = ability.get("cost")
            if isinstance(acost, dict):
                for key in acost:
                    if key not in _ACTIVATED_COST_KEYS:
                        out.append(f"{where}: activated cost key {key!r} is not one of "
                                   f"{sorted(_ACTIVATED_COST_KEYS)}")
        if kind == "triggered":
            trigger = ability.get("trigger")
            if not isinstance(trigger, dict) or not isinstance(trigger.get("event"), str):
                out.append(f"{where}: triggered needs a trigger object with a string event")
            else:
                for key in trigger:
                    if key != "event" and key not in _TRIGGER_EXTRA_KEYS:
                        out.append(f"{where}: unknown trigger key {key!r}")
        for j, effect in enumerate(effects or []):
            ewhere = f"{where}.effects[{j}]"
            if not isinstance(effect, dict):
                out.append(f"{ewhere}: not an object")
                continue
            if kind == "mana_ability" and effect.get("op") != "add_mana":
                out.append(f"{ewhere}: mana_ability may only contain add_mana, got "
                           f"{effect.get('op')!r}")
            if "op" in effect and not isinstance(effect["op"], str):
                out.append(f"{ewhere}: op must be a string, got {effect['op']!r}")
            for key, value in effect.items():
                if key not in eff_keys:
                    out.append(f"{ewhere}: unknown effect key {key!r}")
                elif key in _QUANTITY_PARAMS:
                    quantity(f"{ewhere}.{key}", value)
                elif key in _TARGET_PARAMS:
                    target(f"{ewhere}.{key}", value)
                elif key == "x_basis" and not isinstance(value, str):
                    out.append(f"{ewhere}.x_basis must be a string, got {value!r}")
    return out
