"""Combo determinism (combo-quality Layer 2): is an assembled combo a GUARANTEED win?

Layer 1 (data/spellbook.py) grades a combo's *shape* from Spellbook metadata (pieces, mana,
terminal-vs-outlet). This layer answers the rules question the metadata can't: once the loop
is assembled, does it deterministically win, or does the outcome hinge on chance or an
opponent's decision? That is exactly the qualifier the Comprehensive Rules draw a line at.

Grounding (Comprehensive Rules, handling of loops -- numbers verified against the live
corpus 2026-08-24, `data/rulings.py`; the rule NUMBER a prior version of this docstring
cited, CR 720, has since been reused by WotC for an unrelated mechanic (Omen Cards) --
the loop-shortcut content itself moved to CR 732, cross-referencing CR 104.4b):
  * CR 732 ("Loops") governs the shortcut rules for a repeating action sequence. CR 732.4:
    "If a loop contains only mandatory actions, the game is a draw." CR 732.5/732.6: no
    player can be forced to perform an action that would BREAK the loop (an "unless"
    escape clause is optional, not mandatory) -- so a loop built from OPTIONAL actions can
    be stopped by its controller at the iteration that wins, a deterministic win (you
    simply choose the number).
  * A loop whose continuation or result depends on a RANDOM outcome (coin flip, dice, "at
    random") or on an OPPONENT'S choice cannot be shortcut to a guaranteed result -- the win
    is not deterministic. A purely mandatory loop with no way to end and no win is a draw
    (CR 104.4b: "If a game... enters a 'loop' of mandatory actions... the game is a draw.
    Loops that contain an optional action don't result in a draw."), not a win.

Scope + honesty: this is a deliberately conservative TEXT heuristic over the pieces' Oracle
text (Scryfall Oracle = current errata) and the Spellbook loop description. It flags the
crisp, defensible non-deterministic markers; it does NOT prove determinism (absence of a
marker => "no non-deterministic qualifier found", not a theorem). Pure and offline -- no card
names hard-coded, no network, no LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The rule the verdict cites, in plain ASCII (legacy-console safe).
_RULE_OPTIONAL_LOOP = "CR 732.5/732.6 (an optional loop can be stopped at the iteration that wins)"
_RULE_RANDOM_OR_CHOICE = (
    "CR 104.4b (a loop whose outcome depends on chance or an opponent's choice "
    "cannot be forced to a win)"
)

# Non-deterministic qualifiers: chance, or a decision the COMBO'S CONTROLLER does not own.
# Kept tight to avoid false positives -- "you choose"/"you may" are deterministic (you pick
# the winning line), so only opponent/each-player choices and true randomness are flagged.
#
# Widened 2026-08-25 after spot-checking real oracle text (not the Spellbook API -- no
# network needed, just cards already known to have chance/opponent-choice elements): the
# original vocabulary missed a real card outright.
#   - Fact or Fiction: "An opponent SEPARATES those cards into two piles" -- a genuine
#     opponent-choice, but the verb is "separates", not "chooses"/"choose". MTG templates
#     this family of split-and-pick effects with several verbs, not just one.
# A SECOND candidate widening was tried and REVERTED: matching "in a random order" (to
# catch Possibility Storm) also flagged Thassa's Oracle -- one of the most iconic, fully
# DETERMINISTIC cEDH win conditions -- because "put the rest on the bottom in a random
# order" is common, benign anti-stacking templating for the cards you did NOT keep,
# unrelated to whether the effect's actual outcome (here, a pure count comparison) is
# deterministic. Reverted rather than shipped, since it broke a far more common, more
# iconic real combo than the one it was meant to fix. Possibility Storm's own randomness
# (which specific card gets cast) remains uncaught, alongside Chaos Warp's ("shuffles...
# then reveals the top card", random in effect but never says the word "random" at all) --
# both documented as known residual gaps rather than guessed at with an unproven pattern.
_NONDET_MARKERS: list[tuple[str, re.Pattern[str]]] = [
    ("at random", re.compile(r"\bat random\b", re.IGNORECASE)),
    ("chosen at random", re.compile(r"\bchosen at random\b", re.IGNORECASE)),
    ("coin flip", re.compile(r"\bflips?\s+a\s+coin\b", re.IGNORECASE)),
    ("dice roll", re.compile(r"\brolls?\s+(?:a\s+|one or more\s+|any number of\s+)?"
                             r"(?:six-sided\s+)?(?:dice|die)\b", re.IGNORECASE)),
    ("planar die", re.compile(r"\bplanar die\b", re.IGNORECASE)),
    ("opponent's choice", re.compile(
        r"\b(?:an?|target|each)\s+opponent\s+(?:chooses?|separates?|picks?|selects?)\b",
        re.IGNORECASE)),
    ("opponents choose", re.compile(
        r"\bopponents?\s+(?:chooses?|choose|separates?|picks?|selects?)\b", re.IGNORECASE)),
    ("each player chooses", re.compile(
        r"\beach player\s+(?:chooses?|separates?|picks?|selects?)\b", re.IGNORECASE)),
    ("vote", re.compile(r"\bvotes?\b", re.IGNORECASE)),
]


@dataclass(frozen=True)
class DeterminismVerdict:
    """Whether an assembled combo is a guaranteed win, with the rule it turns on."""

    deterministic: bool
    reason: str  # plain-English explanation (ASCII)
    rule: str  # the CR citation the call rests on
    markers: tuple[str, ...] = ()  # the non-deterministic phrases found (empty if clean)


def classify_determinism(
    piece_texts: list[str], description: str = ""
) -> DeterminismVerdict:
    """Judge a combo's determinism from its pieces' Oracle text + the Spellbook loop steps.

    `piece_texts` are the Oracle texts of the combo's cards (order irrelevant); `description`
    is Spellbook's step-by-step loop, if available. Returns non-deterministic if ANY crisp
    chance/opponent-choice marker appears, else deterministic (no such qualifier found).
    """
    haystack = "\n".join([*(piece_texts or []), description or ""])
    found: list[str] = []
    for label, pattern in _NONDET_MARKERS:
        if pattern.search(haystack):
            found.append(label)
    if found:
        return DeterminismVerdict(
            deterministic=False,
            reason="non-deterministic: outcome depends on " + ", ".join(found),
            rule=_RULE_RANDOM_OR_CHOICE,
            markers=tuple(found),
        )
    return DeterminismVerdict(
        deterministic=True,
        reason="deterministic: no chance/opponent-choice qualifier found",
        rule=_RULE_OPTIONAL_LOOP,
    )
