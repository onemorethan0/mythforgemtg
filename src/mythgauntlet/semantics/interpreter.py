"""CCM effect interpreter — the executable core of the future full interpreter (Phase 6).

Today the semantics->engine bridge (`profile.py`) *flattens* a CCM into a fixed PlayProfile
at build time, which loses per-effect structure: "X" collapses to 1, conditions/optionality
are ignored, and only a handful of trigger events execute. This module is the first step
toward replacing that flattening with a real interpreter: it walks a CCM ability's effects
and resolves them **against a game context**, so the same ability can be interpreted
differently depending on live state (real X, whether a condition holds), instead of being
pre-baked.

It is intentionally *pure of game mutation*: `interpret_ability` turns a CCM ability into a
list of `ResolvedEffect`s (op + numeric-resolved params), and the caller (the T2 engine, or
a test) applies them. That separation — interpret vs. mutate — is what makes the interpreter
testable in isolation and safe to wire into the engine incrementally.

Scope: faithful traversal of the closed effect vocabulary (`ccm.OP_SPECS`) with a pluggable
`Resolver` for amounts (real X) and conditions. **Wired into `sim/tier2.py`** as of 2026-07-13:
CCM cards execute their on-resolution effects (spell_effect + ETB) through `interpret_ability`
+ `_apply_resolved`, per-effect rather than aggregated — and, as of 2026-07-15, their EVENT
triggers too (cast/attack/upkeep/landfall/combat-damage/end-step, fired at the event; see
docs/SIMULATION.md "Event-trigger execution"). The remaining fidelity work is retiring the
PlayProfile's on-resolution fields entirely and an X-basis CCM schema field so "X" can resolve
against what it actually counts (docs/ROADMAP.md Phase 6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from mythgauntlet.semantics.ccm import OP_SPECS

# int-typed params the interpreter resolves to concrete numbers (everything else — targets,
# colours, durations — is passed through untouched for the engine to act on).
_NUMERIC_TAGS = {"int", "int_or_x", "int_signed"}


@runtime_checkable
class Resolver(Protocol):
    """Supplies the live-state answers the interpreter can't know from the CCM alone."""

    def amount(self, raw: object, op: str, param: str, effect: dict | None = None) -> int:
        """Resolve a numeric param (a concrete int, or a variable like 'X'/'all'/'each').

        `effect` is the full effect dict — a resolver may consult its `x_basis` (what an
        "X" counts, prompt v8+) or other context keys when resolving a variable.
        """
        ...

    def condition_holds(self, condition: str, effect: dict) -> bool:
        """Whether a conditional/optional effect actually happens this time."""
        ...


@dataclass
class DefaultResolver:
    """Reproduces the flattening's conventions: 'X' and friends -> a small default; every
    optional/conditional effect assumed to happen. A strict generalization of profile.py."""

    x: int = 1  # magnitude used for X / variable quantities (matches profile.py's "X -> 1")

    def amount(self, raw: object, op: str, param: str, effect: dict | None = None) -> int:
        if isinstance(raw, bool):  # guard: bool is an int subclass
            return self.x
        if isinstance(raw, int):
            return raw  # kept as-is (incl. negatives for pump's int_signed params)
        if isinstance(raw, str) and raw.strip().upper() == "-X":
            return -self.x
        return self.x  # 'X'/'all'/'each'/'half'/... or missing -> default magnitude

    def condition_holds(self, condition: str, effect: dict) -> bool:
        # "otherwise" is the ELSE branch of a preceding if/otherwise pair in the SAME
        # ability -- e.g. Approach of the Second Sun: "if [X], you win the game.
        # Otherwise, put it seventh from the top and gain 7 life." Both effects are
        # separate CCM entries, each carrying its own `condition`, and the flattening's
        # "assume every condition holds" convention -- correct for an ordinary if-branch
        # -- makes both mutually exclusive outcomes fire together if applied uniformly:
        # measured live 2026-08-25, this credited every cast of Approach of the Second
        # Sun as an outright win. Since the resolver already assumes the IF branch is
        # satisfied, consistency requires assuming the paired OTHERWISE branch is not --
        # crediting both is not an optimistic assumption, it's two contradictory outcomes
        # at once. Affects 24 cards store-wide (measured), several high-profile (Approach
        # of the Second Sun, Oko the Ringleader, Jace the Perfected Mind).
        if condition.strip().lower() == "otherwise":
            return False
        return True  # flattening convention: assume optional/conditional effects happen


@dataclass(frozen=True)
class ResolvedEffect:
    """One CCM effect with its numeric params resolved for the current game state."""

    op: str
    params: dict = field(default_factory=dict)


def _resolve_params(op: str, effect: dict, resolver: Resolver) -> dict:
    required, optional = OP_SPECS[op]
    out: dict = {}
    for name, tag in {**required, **optional}.items():
        if name not in effect:
            continue
        raw = effect[name]
        out[name] = resolver.amount(raw, op, name, effect) if tag in _NUMERIC_TAGS else raw
    return out


def interpret_ability(ability: dict, resolver: Resolver | None = None) -> list[ResolvedEffect]:
    """Walk one CCM ability's effects into resolved, executable effects.

    - Unknown ops (outside the closed `OP_SPECS` vocabulary) are skipped, matching the
      tolerant compiler: an ability with a novel op still contributes its known effects.
    - `optional` effects and effects carrying a `condition` fire only when the resolver says
      they hold (DefaultResolver: always).
    - Numeric params (amount/count/power/toughness) are resolved to ints — this is where real
      X will come from once the engine's resolver is wired in.
    """
    resolver = resolver or DefaultResolver()
    out: list[ResolvedEffect] = []
    for effect in ability.get("effects") or []:
        if not isinstance(effect, dict):
            continue
        op = effect.get("op")
        if op not in OP_SPECS:
            continue
        condition = effect.get("condition")
        if (effect.get("optional") or condition) and not resolver.condition_holds(
            condition or "", effect
        ):
            continue
        out.append(ResolvedEffect(op=op, params=_resolve_params(op, effect, resolver)))
    return out


def interpret_ccm(ccm: dict, resolver: Resolver | None = None) -> list[list[ResolvedEffect]]:
    """Interpret every ability of a CCM (one resolved-effect list per ability)."""
    return [
        interpret_ability(a, resolver)
        for a in ccm.get("abilities") or []
        if isinstance(a, dict)
    ]
