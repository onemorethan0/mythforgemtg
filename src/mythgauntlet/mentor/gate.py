"""The claim-budget gate: mechanically checks a drafted reply against what this turn's
tool calls actually returned, before it ever reaches a user. Generalizes
`swap_narrative.check` (one swap, a closed 2-3 card vocabulary) to an open-ended
conversation backed by an arbitrary set of `ToolResult`s -- same doctrine, wider net:

    card names   -> only names a tool call this turn actually returned may be mentioned;
                    checked against the FULL known-card index (2026-08-24: widened from
                    the deck's own card list -- see below), the same index
                    `tools.tool_lookup_card`/`CardDb` draw from.
    numbers      -> every number in the reply must trace to a tool result, within
                    rounding tolerance -- same generous bias as
                    `swap_narrative.allowed_numbers`.
    rule numbers -> the check plain-number matching CANNOT do alone, and the reason it
                    exists as its OWN check: "rule 704.5c" and "rule 704.5f" share the
                    digits "704.5", so a numeric-only check would wave through a citation
                    to the WRONG rule as long as the right one had ever been retrieved.
                    This is not a hypothetical -- it is the exact mistake made earlier in
                    the same session that motivated Phase 0 (see DATA_SOURCES.md).

**The name check used to be scoped to `deck_card_names` only (fixed 2026-08-24) --
that was a real gap, not a deliberate narrowing.** A fabricated claim about a card NOT
in the deck ("X is even better than your Y, run that instead") named a card outside
`deck_card_names - allowed` and so was invisible to the mask entirely: zero reasons,
a confident-looking fabrication shipped unchecked. `known_card_names` is now the FULL
card index (every real MTG card name the app knows, via `MentorContext.all_card_names`
-> `CardDb`), so ANY recognized card name mentioned in the reply -- deck card or not --
must have been returned by a tool call THIS turn (`budget.card_names`) or it is flagged,
exactly as a deck card always was. A name that isn't a real card at all (pure invention,
e.g. "Zzyzx Prism Wyrm") is still not this check's job -- `lookup_card` returning
`found: False` is what catches that, and the model is expected to report it honestly.

On failure the caller regenerates with the reasons named, same pattern as
`swap_narrative.narrate`; this module only checks, it does not call a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mythgauntlet.mentor.tools import ToolResult, RULE_NUM_RE, extract_numbers

# A mentor answer can legitimately be longer than one swap's 2-3 sentences (explaining a
# curve, walking through several role gaps), so these are looser than swap_narrative's
# 40-420 -- but a model that keeps writing well past this has run out of retrieved facts
# and started composing, same logic, wider ceiling.
MIN_CHARS = 15
MAX_CHARS = 1400

# Shrunk from {0.0, 1.0, 2.0} to {0.0, 1.0} on 2026-08-24. 0 and 1 as ordinary English
# ("a second copy", "one of your two commanders") still don't need licensing. 2 was
# dropped: it is exactly the magnitude a small model reaches for when composing a
# quantitative deck-shape claim it hasn't actually measured ("about two counterspells",
# a common mana cost, a small P/T) -- and unlike a card-attached claim, a bare deck-shape
# number has no other leg of the gate backing it up. The widened card-name check above
# (see `known_card_names`) already forces ANY claim naming a specific card to be verified
# regardless of what number rides along with it, so this exemption only needs to stay
# honest about numbers that are NOT attached to a verified card -- which is exactly the
# case a generously-sized free set defeats. Kept conservative rather than guessed: swept
# against this module's own test suite, not against the model's real output distribution.
_FREE_NUMBERS = {0.0, 1.0}
_NUMBER_TOLERANCE = 0.6


@dataclass(frozen=True)
class ClaimBudget:
    card_names: frozenset[str] = frozenset()
    numbers: frozenset[float] = frozenset()
    rule_numbers: frozenset[str] = frozenset()
    # Every real MTG card name the app knows about (the SAME index `lookup_card` /
    # `MentorContext.card_db` draw from) -- the risk pool the name check scans for a
    # mention that slipped in without a tool call backing it THIS turn. Deliberately NOT
    # limited to the current deck (see the module docstring for why that used to be a
    # fabrication gap): a claim about a card the user doesn't own is exactly as much a
    # fabrication as one about a card in their deck.
    known_card_names: frozenset[str] = frozenset()

    @classmethod
    def from_tool_results(
        cls, results: list[ToolResult], known_card_names: frozenset[str] = frozenset()
    ) -> "ClaimBudget":
        names: set[str] = set()
        nums: set[float] = set()
        rules: set[str] = set()
        for r in results:
            names |= r.card_names
            nums |= r.numbers
            rules |= r.all_rule_numbers
        return cls(frozenset(names), frozenset(nums), frozenset(rules), known_card_names)


def _looks_like_a_name(text: str, match: re.Match) -> bool:
    """Same crude, deliberately name-favouring heuristic as swap_narrative: capitalised
    and not sentence-initial. Biased toward under-flagging -- missing a real mention is a
    mild under-count, rejecting honest prose about an unrelated capitalised word is worse."""
    word = text[match.start():match.end()]
    if not word[:1].isupper():
        return False
    before = text[:match.start()].rstrip()
    return bool(before) and before[-1] not in ".!?"


def check(text: str, budget: ClaimBudget) -> list[str]:
    """Every way `text` over-claims against `budget`. Empty means faithful."""
    reasons: list[str] = []
    body = text.strip()

    if not MIN_CHARS <= len(body) <= MAX_CHARS:
        reasons.append(f"length {len(body)} outside {MIN_CHARS}-{MAX_CHARS}")

    # 1. CARD NAMES. Mask the allowed names out first (longest first: nested names --
    #    "Vesuva" sitting inside "Omo, Queen of Vesuva" is the exact case swap_narrative
    #    documents), then scan the FULL known-card index (not just the deck -- see the
    #    module docstring) for a mention that snuck in without a tool call backing it.
    #    The `name.lower() not in masked_lower` pre-filter is a cheap substring test
    #    (fast even against tens of thousands of candidate names) that skips the regex
    #    entirely for the overwhelming majority that don't appear at all; only a name
    #    that DOES appear pays for the word-boundary regex + position check.
    allowed = budget.card_names
    masked = body
    for name in sorted(allowed, key=len, reverse=True):
        masked = re.sub(re.escape(name), " ", masked, flags=re.IGNORECASE)
    masked_lower = masked.lower()
    for name in budget.known_card_names - allowed:
        if name.lower() not in masked_lower:
            continue
        for match in re.finditer(rf"\b{re.escape(name)}\b", masked, re.IGNORECASE):
            if _looks_like_a_name(masked, match):
                reasons.append(f"names a card that was never looked up this turn: {name!r}")
                break

    # 2. RULE CITATIONS. Checked as the FULL string (number + letter suffix), separately
    #    from plain numbers -- see the module docstring for why a numeric-only check
    #    cannot catch "704.5c" standing in for a retrieved "704.5f".
    for cited in set(RULE_NUM_RE.findall(body)):
        if cited not in budget.rule_numbers:
            reasons.append(f"cites rule {cited!r}, which was never looked up this turn")

    # 3. NUMBERS. Anything cited must trace to a tool result, within rounding tolerance.
    #    `extract_numbers` catches spelled-out numbers ("about thirty ramp sources") the
    #    same way it catches digits -- see tools.py's own docstring for why that matters.
    for value in extract_numbers(body):
        if value in _FREE_NUMBERS:
            continue
        if not any(abs(value - ok) <= _NUMBER_TOLERANCE for ok in budget.numbers):
            reasons.append(f"cites {value:g}, which is not in this turn's tool results")

    return reasons


class GateFailure(Exception):
    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("; ".join(reasons))


def gate(text: str, budget: ClaimBudget) -> str:
    reasons = check(text, budget)
    if reasons:
        raise GateFailure(reasons)
    return text.strip()
