"""Standing diagnostic over what the SIMULATOR does with the store, mirroring
`semantics/health.py` on the other side of the same boundary.

`ccm-health` answers "why do cards fail to COMPILE". Nothing answered "what happens to
the ones that succeed", and the asymmetry was itself the defect: as of 2026-09-08 the
text->CCM boundary carried three gates, a GBNF grammar, a ledger, `refresh_errors`,
eleven prompt versions and a nightly report, while the CCM->simulation boundary carried
NOTHING — and measurement showed it was silently discarding **49% of every effect the
store had just spent months learning to record**.

The specific shape of the loss, measured over the 31.7k-card store the day this module
was written:

  * `sim/tier2._apply_resolved` dispatched ~11 ops. Every other op in `ccm.OP_SPECS`
    parses, passes all three gates, is stored, is loaded, is interpreted — and then
    falls off the end of an if/elif chain. 27,748 of 56,583 stored effects.
  * The single largest one was **`pump` (4,295 effects)** — arguably the second most
    common effect in Magic, executing as nothing, while combat reads `.power` in eight
    places. An omission, not a design choice. Dispatching it needed a cleanup step
    built first (92.1% of stored pumps are "until end of turn" and nothing expired),
    which is the shape of the real finding: the top row of this report is usually a
    MISSING LAYER, not a missing branch.
  * `semantics/profile._activated_from` is a SECOND, older path with a THIRD vocabulary
    (4 ops into 6 fixed fields). Only 11.1% of 9,108 activated abilities survive it.

None of that was visible anywhere. A deck rating is a point estimate, and the median
corpus deck had **64.9%** of its recorded behaviour executed (range 0%-94.1%) with no
figure attached saying so. Fixing one op (`add_counter`) moved a real hydra deck **+691
rating** — which is the argument for this module: those were never independent bugs,
they were samples from a population nobody could see the size of.

**The executed vocabularies are read from the SOURCE, never restated here.**
`_dispatched_ops` walks the actual `ast` of `_apply_resolved` and `_activated_from` and
collects the `op == "..."` / `op in (...)` literals its branches test. Restating them as
a constant is the exact failure class this repo keeps re-learning (a theme in
`THEME_PATTERNS` but not `theme_match.THEMES`; a quality key missing from
`_QUALITY_KEYS`): the two copies drift, and the drift is SILENT — a newly-executed op
would keep being reported as inert, so the gauge would argue against the fix that had
already landed. Add a branch to `_apply_resolved` and this module learns it on the next
run, with no edit here.

`analyze_store(envelopes)` returns per-op counts ranked by CARDS AFFECTED (not raw
effect count — the same choice `health._bucket` makes, because "how many cards does
this change" is the prioritisation question and one card with nine pump effects is not
nine cards' worth of value). Three buckets, deliberately never merged:

  * `inert_ops`    — in `ccm.OP_SPECS`, dispatched by no branch. A simulator gap.
  * `partial_ops`  — a branch exists but GUARDS what it acts on. See `_guarded_ops`.
  * `unknown_ops`  — outside `OP_SPECS` entirely. A vocabulary gap, tolerated by the
    schema gate on purpose (`ccm.unsupported_ops`), which is why it needs its own row:
    the pre-existing `unsupported_ops` marker measures ONLY this bucket and is
    structurally blind to `inert_ops`, the one that turned out to be five times larger.

**The headline is a RANGE, not a point estimate**, and that is the whole lesson of the
module. The first version reported a single "45% executed"; dispatching `pump` for
self-target only moved it to 49.9% while actually executing 418 of 4,295 pump effects,
because "a branch exists" had been silently equated with "the effect happens". Reporting
`executed_share` (floor: only unguarded branches) alongside `executed_share_ceiling`
(every guarded branch assumed to fire) makes the gauge unable to flatter itself — and a
gauge that can be gamed by a token branch is worse than no gauge, because it argues
against the fix that is still needed.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections import Counter, defaultdict

from ..semantics import ccm, profile
from . import tier2

# Effects the interpreter drops BEFORE dispatch: the trigger-event vocabulary
# deliberately names events the engine cannot execute (see tier2._EVENT_TRIGGERS and
# docs/engine/CARD_SEMANTICS.md). Those are an honest under-count by design, not a gap
# this module should file against the dispatch table — so ability KINDS are counted
# separately from ops.
_ABILITY_KIND_KEY = "kind"


def _dispatched_ops(func) -> frozenset[str]:
    """The op literals `func`'s body actually branches on, read from its own AST.

    Handles both shapes `_apply_resolved` uses: `op == "draw"` and `op in ("destroy",
    "exile")`. A branch this cannot read is simply not counted as executed, which errs
    toward reporting MORE loss than there is — the safe direction for a gauge whose
    whole purpose is to stop an over-confident rating.
    """
    try:
        src = inspect.getsource(func)
    except (OSError, TypeError):  # pragma: no cover - source always available in-tree
        return frozenset()
    tree = ast.parse(textwrap.dedent(src))
    ops: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1:
            continue
        if not (isinstance(node.left, ast.Name) and node.left.id == "op"):
            continue
        cmp_op, comparator = node.ops[0], node.comparators[0]
        if isinstance(cmp_op, ast.Eq) and isinstance(comparator, ast.Constant):
            if isinstance(comparator.value, str):
                ops.add(comparator.value)
        elif isinstance(cmp_op, ast.In) and isinstance(comparator, (ast.Tuple, ast.List, ast.Set)):
            for elt in comparator.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    ops.add(elt.value)
    return frozenset(ops)


def op_consumers() -> dict[str, list[str]]:
    """Every simulation-side reader of an op, as `op -> ["module.function", ...]`.

    Added after the dispatch-only version of this gauge reported `counter_spell` (484
    cards) as inert. It is not: `_apply_resolved` has no branch for it because counters
    are resolved in a different subsystem entirely — `semantics/profile._has_counter_spell`
    feeds the reactive counter-war model in `sim/game.py`. Reporting that as a simulator
    gap would have sent a session to "fix" something already working.

    So "inert" cannot mean "absent from the dispatch chain"; it has to mean **no consumer
    anywhere**. This scans whole modules rather than two named functions, and reports WHO
    reads each op, which also distinguishes a genuinely executed op from one that only
    feeds an aggregate (`search_library` is read by profile's ramp counting whether or not
    the game loop ever executes a tutor).

    Scans the simulation side only. `semantics/ccm.py` also compares ops, but that is the
    COMPILER validating its own vocabulary — counting it as a consumer would make every
    op look consumed and the gauge would read 100% forever.
    """
    consumers: defaultdict[str, list[str]] = defaultdict(list)
    for module in (tier2, profile):
        try:
            src = inspect.getsource(module)
        except (OSError, TypeError):  # pragma: no cover
            continue
        tree = ast.parse(textwrap.dedent(src))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for op in _ops_compared_within(node):
                label = f"{module.__name__.rsplit('.', 1)[-1]}.{node.name}"
                if label not in consumers[op]:
                    consumers[op].append(label)
    return {op: sorted(fns) for op, fns in consumers.items()}


def _ops_compared_within(node: ast.AST) -> set[str]:
    """Op literals compared against an `op`-ish local anywhere inside `node`."""
    ops: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Compare):
            ops |= _ops_tested_by(sub)
    return ops


def _guarded_ops(func) -> frozenset[str]:
    """Ops whose branch EXISTS but declines some of what reaches it.

    Without this the gauge lies in the flattering direction, and it did: dispatching
    `pump` for self-target only moved its reported card count 3,925 -> 1,405, when the
    branch actually executes 418 of 4,295 effects. "A branch exists" is not "the effect
    happens" — `add_counter` is self-target only, `grant_ability` is haste only, `pump`
    is self-target and literal-amount only. Every one of those is a deliberate,
    documented refusal to fabricate a choice the engine cannot make, and every one
    leaves a real remaining gap this module exists to keep visible.

    Detected structurally: a branch is guarded when a mutation-covering `if` in it has no
    `else`, which is the shape every one of those refusals takes (a branch that genuinely
    handles all cases — `draw`'s `who == "each_opponent"` — carries an `else`). It is a
    heuristic and is reported as one: `partial_ops` is a SEPARATE bucket, never folded
    into either side, because how much of a guarded op gets declined cannot be known
    without running the simulation.
    """
    try:
        src = inspect.getsource(func)
    except (OSError, TypeError):  # pragma: no cover
        return frozenset()
    guarded: set[str] = set()
    for node in ast.walk(ast.parse(textwrap.dedent(src))):
        if not isinstance(node, ast.If):
            continue
        ops = _ops_tested_by(node.test)
        if ops and any(_has_unelsed_if(s) for s in node.body):
            guarded |= ops
    return frozenset(guarded)


def _is_op_expr(node: ast.expr) -> bool:
    """Is this expression the effect's op? Either a local named `op`/`o`, or an inline
    `effect.get("op")` — profile.py uses both spellings, and reading only the first
    missed `_has_counter_spell`, which is exactly the consumer whose absence made the
    gauge accuse a working subsystem."""
    if isinstance(node, ast.Name):
        return node.id in ("op", "o")
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "get" and len(node.args) >= 1:
            arg = node.args[0]
            return isinstance(arg, ast.Constant) and arg.value == "op"
    return False


def _ops_tested_by(test: ast.expr) -> set[str]:
    """The op literals a single comparison tests the effect's op against."""
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return set()
    if not _is_op_expr(test.left):
        return set()
    cmp_op, comparator = test.ops[0], test.comparators[0]
    if isinstance(cmp_op, ast.Eq) and isinstance(comparator, ast.Constant):
        return {comparator.value} if isinstance(comparator.value, str) else set()
    if isinstance(cmp_op, ast.In) and isinstance(comparator, (ast.Tuple, ast.List, ast.Set)):
        return {e.value for e in comparator.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return set()


def _has_unelsed_if(stmt: ast.stmt) -> bool:
    """Does this statement contain an if/elif chain that can fall through doing NOTHING?

    Walks the whole `elif` chain rather than looking at one `if`. The first version only
    recognised a bare `if` with no `else`, and the moment branches were written as
    `if self-target ... elif mass ...` — with a chosen target deliberately falling off the
    end — those read as fully handled. The gauge jumped ~10 points on ops that decline
    the majority of what reaches them, which is the exact self-flattery `partial_ops`
    exists to prevent. An `elif` is just an `If` nested in the previous `orelse`, so the
    question is only ever whether the chain TERMINATES in a real `else`.

    A real `else:` still isn't automatically "every path does something" — its own body can
    contain a FURTHER guarded if/elif (docs/PLAN_FIDELITY.md Phase C, 2026-09-09:
    `return_to_hand`'s new chosen-target picker is exactly this shape, `else: <setup> if
    controller=="you": ... elif controller=="opponent": ...` with any/absent controller
    still falling off the end one level deeper). Recursing into the else body's own
    statements is the same "walk deeper before declaring fully handled" principle the
    elif-chain fix already established, one level further in. A real else with a FLAT body
    (`draw`'s `(opp if who=="opponent" else me).draw(n)` is an expression, not a nested `If`
    statement at all) still correctly reads as fully handled, since recursing into a
    non-if/for/while/with statement falls through to the base case below.
    """
    if isinstance(stmt, ast.If):
        node = stmt
        while True:
            if not node.orelse:
                return True  # the chain can end with nothing done
            if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                node = node.orelse[0]  # an elif; keep walking
                continue
            return any(_has_unelsed_if(s) for s in node.orelse)  # a real else -- look deeper
    if isinstance(stmt, (ast.For, ast.While, ast.With)):
        return any(_has_unelsed_if(s) for s in stmt.body)
    return False


def executed_ops() -> dict[str, frozenset[str]]:
    """The two live dispatch vocabularies, by the path that owns each.

    They are genuinely different sets, not one set read twice: `resolved` is the newer
    interpreter path (spell_effect / ETB / triggered), `activated` is the older
    flattening in `semantics/profile` that turns an activated ability into six fixed
    `ActivatedEffect` fields. An op in one and not the other means the SAME printed
    effect is executed or dropped depending on which kind of ability prints it.
    """
    return {
        "resolved": _dispatched_ops(tier2._apply_resolved),
        "activated": _dispatched_ops(profile._activated_from),
    }


def _known_ops() -> frozenset[str]:
    specs = getattr(ccm, "OP_SPECS", None)
    return frozenset(specs) if isinstance(specs, dict) else frozenset()


def analyze_store(envelopes, top_n: int = 20, samples_per_op: int = 4) -> dict:
    """Rank what the simulator throws away, by cards affected.

    `envelopes` is an iterable of stored CCM envelopes (`{"card": {...}, "ccm": {...}}`)
    — the caller supplies them so this stays pure and testable with no store on disk,
    the same contract `health.analyze_failures` has with the ledger.
    """
    vocab = executed_ops()
    guarded = {
        "resolved": _guarded_ops(tier2._apply_resolved),
        "activated": _guarded_ops(profile._activated_from),
        "dropped": frozenset(),
    }
    vocab = dict(vocab, dropped=frozenset())  # an ability nothing runs executes no op
    known = _known_ops()

    consumers = op_consumers()
    # Read by SOME simulation-side subsystem but never executed in the game loop --
    # `counter_spell` is resolved by profile._has_counter_spell feeding game.py's
    # reactive counter-war, so calling it a simulator gap would send a session to fix
    # something that already works. Its own bucket, not silently on either side.
    elsewhere = frozenset(consumers) - vocab["resolved"] - vocab["activated"]

    effect_counts: Counter[str] = Counter()
    card_counts: Counter[str] = Counter()
    partial_effect_counts: Counter[str] = Counter()
    partial_card_counts: Counter[str] = Counter()
    elsewhere_effect_counts: Counter[str] = Counter()
    elsewhere_card_counts: Counter[str] = Counter()
    samples: defaultdict[str, list[str]] = defaultdict(list)
    executed_effects = inert_effects = partial_effects = elsewhere_effects = 0
    activated_total = activated_kept = 0
    cards_total = cards_fully_executed = cards_fully_inert = 0

    for env in envelopes:
        if not isinstance(env, dict):
            continue
        doc = env.get("ccm")
        if not isinstance(doc, dict):
            continue
        name = str((env.get("card") or {}).get("name") or "")
        cards_total += 1
        seen_here: set[str] = set()
        card_exec = card_inert = 0

        for ability in doc.get("abilities") or []:
            if not isinstance(ability, dict):
                continue
            kind = ability.get(_ABILITY_KIND_KEY)
            is_activated = kind == "activated"
            path = "activated" if is_activated else "resolved"
            if is_activated:
                # WHICH vocabulary an activated ability's effects are judged against is
                # not fixed any more. `_activated_from` either flattens it into six
                # numeric fields (the narrow four-op vocabulary), routes it WHOLE to the
                # interpreter (the full resolved vocabulary), or drops it outright -- and
                # asking the real function is the only way to know which. Judging every
                # activated effect against the narrow set, as this did at first, reported
                # `pump`/`add_counter`/`exile` as inert on hundreds of cards whose
                # abilities had just been wired to run them.
                activated_total += 1
                kept = _activated_effect(ability)
                if kept is None:
                    path = "dropped"  # nothing runs; every effect below is inert
                else:
                    activated_kept += 1
                    if getattr(kept, "ability", None) is not None:
                        path = "resolved"  # interpreter-routed: full vocabulary

            for eff in ability.get("effects") or []:
                if not isinstance(eff, dict):
                    continue
                op = eff.get("op")
                op = op if isinstance(op, str) else str(op)
                if op in vocab[path]:
                    card_exec += 1
                    if op in guarded[path]:
                        # A branch exists but may decline this instance; it is neither
                        # honestly "executed" nor honestly "inert", so it is counted as
                        # neither and reported on its own.
                        partial_effects += 1
                        partial_effect_counts[op] += 1
                        if op not in seen_here:
                            seen_here.add(op)
                            partial_card_counts[op] += 1
                            if name and len(samples[op]) < samples_per_op:
                                samples[op].append(name)
                    else:
                        executed_effects += 1
                    continue
                if op in elsewhere:
                    elsewhere_effects += 1
                    elsewhere_effect_counts[op] += 1
                    if op not in seen_here:
                        seen_here.add(op)
                        elsewhere_card_counts[op] += 1
                        if name and len(samples[op]) < samples_per_op:
                            samples[op].append(name)
                    continue
                inert_effects += 1
                card_inert += 1
                effect_counts[op] += 1
                if op not in seen_here:
                    seen_here.add(op)
                    card_counts[op] += 1
                    if name and len(samples[op]) < samples_per_op:
                        samples[op].append(name)

        if card_exec or card_inert:
            if not card_inert:
                cards_fully_executed += 1
            elif not card_exec:
                cards_fully_inert += 1

    total_effects = executed_effects + partial_effects + elsewhere_effects + inert_effects
    ranked = [
        {
            "op": op,
            "cards": card_counts[op],
            "effects": effect_counts[op],
            "in_vocabulary": op in known,
            "examples": samples.get(op, []),
        }
        for op, _ in sorted(card_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    def _rank(cards: Counter[str], effects: Counter[str], extra=None) -> list[dict]:
        return [
            dict(
                {
                    "op": op,
                    "cards": cards[op],
                    "effects": effects[op],
                    "in_vocabulary": op in known,
                    "examples": samples.get(op, []),
                },
                **({"consumers": consumers.get(op, [])} if extra else {}),
            )
            for op, _ in sorted(cards.items(), key=lambda kv: (-kv[1], kv[0]))
        ]

    partial_ranked = _rank(partial_card_counts, partial_effect_counts)
    elsewhere_ranked = _rank(elsewhere_card_counts, elsewhere_effect_counts, extra=True)

    def _share(n: int) -> float:
        return n / total_effects if total_effects else 0.0

    return {
        "cards_scanned": cards_total,
        "executed_effects": executed_effects,
        "partial_effects": partial_effects,
        "elsewhere_effects": elsewhere_effects,
        "inert_effects": inert_effects,
        "total_effects": total_effects,
        # A RANGE, not a point estimate. The floor counts only ops whose branch handles
        # whatever reaches it; the ceiling additionally assumes every guarded op fired.
        # The truth is between, and which end it sits nearer cannot be known without
        # running the simulation — so the gauge reports both rather than picking one.
        "executed_share": _share(executed_effects),
        "executed_share_ceiling": _share(executed_effects + partial_effects),
        "cards_fully_executed": cards_fully_executed,
        "cards_fully_inert": cards_fully_inert,
        "activated_total": activated_total,
        "activated_kept": activated_kept,
        "activated_share": activated_kept / activated_total if activated_total else 0.0,
        "executed_ops": {k: sorted(v) for k, v in vocab.items()},
        "guarded_ops": {k: sorted(v) for k, v in guarded.items()},
        "op_consumers": consumers,
        "inert_ops": [r for r in ranked if r["in_vocabulary"]][:top_n],
        "unknown_ops": [r for r in ranked if not r["in_vocabulary"]][:top_n],
        "partial_ops": partial_ranked[:top_n],
        "elsewhere_ops": elsewhere_ranked[:top_n],
    }


def _activated_effect(ability: dict):
    """What `_activated_from` actually makes of this ability: an ActivatedEffect or None.

    ASKS THE REAL FUNCTION rather than re-deriving its gates. An earlier version of this
    module reimplemented them, reasoning that `_activated_from` returns an already
    aggregated result and so answers "what value did this become" rather than "was
    anything lost". That was a mistake of exactly the kind this file warns about
    everywhere else: when `_activated_from` gained the interpreter path and started
    keeping 2,175 abilities it used to drop, the copy here would have kept reporting the
    old 11.7% survival and argued for a fix that had already shipped.

    The returned object also says HOW it survived -- a non-None `.ability` means the whole
    ability was routed to the interpreter, so its effects run against the full resolved
    vocabulary rather than the flattening's four ops.
    """
    effects = [e for e in (ability.get("effects") or []) if isinstance(e, dict)]
    try:
        return profile._activated_from(ability, effects)
    except Exception:  # a malformed stored ability must not kill the gauge
        return None
