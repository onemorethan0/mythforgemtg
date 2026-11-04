"""Static cost reducers for the DUEL simulator ("Instant and sorcery spells you cast cost {1} less").

One definition of the rule, used by every place the duel sim reads a card's cost, so legality (can I
cast it?) and payment (what do I tap?) can never disagree. Tier 0 deliberately does NOT use this: wiring
it into the goldfish clock moved the bracket estimate the wrong way (docs/BACKLOG.md B3), and the
bracket is the one number whose accuracy is measured against labelled decks.

Only what `compiler.parse_cost_reducer` accepts counts: a whole oracle line, generic mana only, a closed
subject list, "you cast". Everything else (coloured reductions, "for each", conditionals, increases,
all-player reductions like Helm of Awakening) is declined, the honest under-count.
"""
from __future__ import annotations

import re
from dataclasses import replace
from functools import lru_cache

_COLOR_WORDS = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}


@lru_cache(maxsize=4096)
def reducers_in_text(oracle_text: str) -> tuple[tuple[str, int], ...]:
    """((subject, generic amount), ...) for each qualifying line of `oracle_text`."""
    from mythgauntlet.semantics.compiler import parse_cost_reducer

    out: list[tuple[str, int]] = []
    for line in (oracle_text or "").splitlines():
        r = parse_cost_reducer(re.sub(r"\([^)]*\)", "", line).strip())
        if r:
            out.append((r["subject"], r["amount"]))
    return tuple(out)


def reducers_for_card(card) -> tuple[tuple[str, int], ...]:
    """The reducers a PERMANENT provides (an instant or sorcery never has a static one)."""
    if card.has_type("Instant") or card.has_type("Sorcery"):
        return ()
    return reducers_in_text(card.oracle_text or "")


def matches(subject: str, card) -> bool:
    """Does a reducer for `subject` ('creature spells', 'white spells', ...) apply to `card`?"""
    if subject == "spells":
        return True
    if subject == "creature spells":
        return card.is_creature
    if subject == "noncreature spells":
        return not card.is_creature
    if subject == "instant and sorcery spells":
        return card.has_type("Instant") or card.has_type("Sorcery")
    if subject == "colorless spells":
        return not card.colors
    word = subject.split(" ", 1)[0]
    if word in _COLOR_WORDS:
        return _COLOR_WORDS[word] in card.colors
    return card.has_type(word.capitalize())      # artifact / enchantment / planeswalker


def discounted(cost, amount: int):
    """`cost` with `amount` generic mana taken off, never below the coloured requirement
    (a reduction never lowers the colour you need, only the untyped part)."""
    amount = min(max(0, amount), cost.generic)
    if amount <= 0:
        return cost
    return replace(cost, generic=cost.generic - amount, mana_value=cost.mana_value - amount)


def total_discount(permanents, card) -> int:
    """Sum of every matching reducer among `permanents` (a player's battlefield)."""
    return sum(amount for perm in permanents for subject, amount in perm.cost_reducers
               if matches(subject, card))
