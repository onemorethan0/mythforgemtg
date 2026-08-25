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

# ── Uncited rules-paraphrase heuristic (check 4 below) ──────────────────────────────
# A reply can define a Comprehensive Rules concept -- "a state-based action is when the
# game checks something automatically" -- with NO rule number and no digits at all, so
# checks 1-3 have zero visibility into it: correctness rests entirely on trusting the
# model actually called search_rules/get_rule and paraphrased faithfully. This is a
# BOUNDED, CONSERVATIVE heuristic for that gap, not a full NLP solution -- a definition
# phrased without one of these specific patterns still slips through, and that residual
# gap is a known, accepted limitation (same shape as `_looks_like_a_name`'s bias above:
# missing a real violation is the safe direction, flooding false positives on ordinary
# deck chat is not).
#
# Definitional phrasing a small model reaches for when explaining a rule in prose.
_DEFINITIONAL_PHRASE_RE = re.compile(
    r"\b(?:is defined as|means that|refers to|is when|the rule (?:is|states))\b",
    re.IGNORECASE,
)
# A short, hand-picked subset of core rules-vocabulary nouns -- verified as literal
# entries in the live Comprehensive Rules glossary (data/rulings.py's
# `ComprehensiveRules.glossary`, checked 2026-08-25: "state-based actions", "stack",
# "priority", "triggered ability", "replacement effect", "static ability" and "layer"
# are all real glossary headwords). Deliberately NOT the whole ~1,000-term glossary --
# this module is a pure text+budget check with no `MentorContext`/`ComprehensiveRules`
# to pull from, and hardcoding a handful of the terms a casual player is most likely to
# ask the mentor to define keeps this dependency-free and fast rather than loading the
# CR corpus from disk inside a string check.
_RULES_VOCAB_RE = re.compile(
    r"\b(?:state-based actions?|the stack|priority|triggered abilit(?:y|ies)|"
    r"replacement effects?|static abilit(?:y|ies)|layers?)\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# Markdown ordered-list markers ("1. **Point one**...") read as bare numbers to the
# NUMBERS check below -- found live 2026-08-25: a correct 3-point rulings explanation
# was gate-rejected for "citing" 2 and 3, which were never facts, just list positions.
# Stripped only for the numbers scan (not from the name/rule-citation checks, and never
# from the text actually shown to the user) since a list marker asserts nothing about
# the number 2 or 3 itself -- it's formatting, not a claim. Two shapes, both observed
# live: a marker at the START of its own line ("2)\n" or "2.\n"), and -- despite the
# system prompt explicitly asking for plain prose, which a 14B model doesn't always
# follow -- a marker INLINE mid-paragraph immediately before a bold-markdown heading
# ("...unchanged. 2. **No Targeting**: ..."), which the line-start pattern alone missed
# on the first fix attempt.
_LIST_MARKER_RE = re.compile(r"(?m)^\s*\d+[.)]\s+|\d+\.\s+(?=\*\*)")

# A handful of real MTG card names that are also ordinary English words/notation, found
# live 2026-08-25 causing false "unverified card" flags on completely innocent prose:
# "X" is the game's own variable-cost notation (Craterhoof's "+X/+X"), and "Wizards"/
# "Overload" are common English/rules-jargon words that also happen to name real (mostly
# joke-set) cards. The cost of ever catching a genuine reference to one of these obscure
# cards in casual chat is far lower than the cost of blocking every X-cost explanation.
# Single-character names are excluded categorically (verified: "x" is the only one in
# the whole card index); multi-character ones are an explicit, evolving list -- add here
# when live data (mentor_bench.py or a real transcript) surfaces the next one, the same
# way EXTRA_TURN_CARDS/MASS_LAND_DESTRUCTION_CARDS grow in root bracket.py. "spells"
# added 2026-08-25 (fifth bench run, same session): an explanation of how "instant
# spells, sorcery spells" work on the stack triggered the same false flag on the plain
# word "Spells" -- a real (joke-set) card name, same as X/Wizards/Overload above.
# "ramp" and "counterspell" added 2026-08-25 (round 3 of a live mentor campaign): both
# are ALSO two of the deck-building role-classification names this whole app uses
# constantly (collection_pool.ROLES / get_deck_stats' "roles" block reports "ramp" and
# "counterspell" as category names, not card names) -- a much higher-frequency collision
# than the others here, since discussing role supply/targets is one of the mentor's most
# common conversation types. Note this does NOT stop the gate from catching a genuinely
# fabricated SPECIFIC card recommendation naming an unlooked-up counterspell like "Mana
# Drain" -- that's a different card name, still fully scanned.
_COMMON_WORD_CARD_NAMES = frozenset({"wizards", "overload", "spells", "exile", "ramp", "counterspell"})
# "same sentence, or within ~15 words" -- generous enough to catch a definitional clause
# and its vocabulary term separated by a hedge phrase, tight enough that two unrelated
# rules terms in a long paragraph don't pair up across sentences.
_DEFINITION_PROXIMITY_WORDS = 15


def _words_between(s: str, m1: re.Match, m2: re.Match) -> int:
    """Rough word count strictly between two (non-overlapping) regex matches in `s`."""
    lo, hi = sorted((m1.span(), m2.span()))
    return len(s[lo[1]:hi[0]].split())


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
    # Full string values (oracle text, rulings text, ...) this turn's tool calls actually
    # returned -- licensed for VERBATIM quotation regardless of what card-name-shaped
    # words they happen to contain. See `_strings_in`'s docstring in tools.py: a real
    # card's real oracle text saying "Exile target nonland permanent" was gate-rejected
    # because "Exile" is ALSO a real card name, even though the model was faithfully
    # quoting the tool result, not making an independent claim. A paraphrase (not a
    # verbatim substring) still gets scanned normally -- this only exempts an exact echo.
    source_texts: frozenset[str] = frozenset()

    @classmethod
    def from_tool_results(
        cls, results: list[ToolResult], known_card_names: frozenset[str] = frozenset()
    ) -> "ClaimBudget":
        names: set[str] = set()
        nums: set[float] = set()
        rules: set[str] = set()
        texts: set[str] = set()
        for r in results:
            names |= r.card_names
            nums |= r.numbers
            rules |= r.all_rule_numbers
            texts |= r.source_texts
        return cls(frozenset(names), frozenset(nums), frozenset(rules), known_card_names,
                    frozenset(texts))


def _looks_like_a_name(text: str, match: re.Match) -> bool:
    """Same crude, deliberately name-favouring heuristic as swap_narrative: capitalised
    and not sentence-initial. Biased toward under-flagging -- missing a real mention is a
    mild under-count, rejecting honest prose about an unrelated capitalised word is worse."""
    word = text[match.start():match.end()]
    if not word[:1].isupper():
        return False
    before = text[:match.start()].rstrip()
    return bool(before) and before[-1] not in ".!?"


def check(text: str, budget: ClaimBudget, question: str = "") -> list[str]:
    """Every way `text` over-claims against `budget`. Empty means faithful.

    `question` (optional, the player's OWN message this turn) exempts a bare card-name
    mention the player already introduced -- found live 2026-08-25: "I'll check what
    Utvara Hellkite has to offer" (zero claims about the card, just echoing the name
    back from the player's own question while announcing intent to look it up) was
    gate-rejected as an unlooked-up card. The player naming a card in their own message
    isn't a claim the model needs to verify; it's already common ground. This does NOT
    exempt anything the model goes on to ASSERT about that card -- a fabricated oracle
    text or number naming the same card is still caught by the other checks below."""
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
    # A possessive reference to a card already verified this turn ("Urza's ability",
    # meaning Urza the commander's own ability) is an ordinary, safe construction, not a
    # fresh claim -- but the model shortens a multi-word name to its FIRST word before
    # the possessive ("Urza's", not "Urza, Lord High Artificer's"). Found live
    # 2026-08-25: "Urza's" is ALSO a real (joke-set) card name in the index, same class
    # as X/Wizards/Overload/Spells/Exile above, but this one recurs structurally for ANY
    # multi-word commander name, since a short possessive back-reference to the card
    # already being discussed is extremely common. Masked BEFORE the full-name pass
    # below (not after), since the full name's own regex wouldn't match the short form
    # at all and doing this second would be a no-op, not merely redundant.
    for name in sorted(allowed, key=len, reverse=True):
        short = name.split(",")[0].strip()
        if short and short.lower() != name.lower():
            masked = re.sub(re.escape(short) + r"[''`]s\b", " ", masked, flags=re.IGNORECASE)
    for name in sorted(allowed, key=len, reverse=True):
        masked = re.sub(re.escape(name), " ", masked, flags=re.IGNORECASE)
    # A verbatim quotation of something this turn's tools actually returned (oracle
    # text, rulings text) is licensed as a whole -- mask it out before scanning for
    # embedded card-name-shaped words, same rationale as masking `allowed` names above.
    # Longest first, same as `allowed`, so a shorter source text nested inside a longer
    # one doesn't get masked piecemeal and leave a stray fragment behind.
    for text in sorted(budget.source_texts, key=len, reverse=True):
        if text.lower() in masked.lower():
            masked = re.sub(re.escape(text), " ", masked, flags=re.IGNORECASE)
    masked_lower = masked.lower()
    question_lower = question.lower()
    for name in budget.known_card_names - allowed:
        if len(name.strip()) <= 1 or name.lower() in _COMMON_WORD_CARD_NAMES:
            continue
        if question_lower and name.lower() in question_lower:
            continue
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
    #    List markers are stripped first (see `_LIST_MARKER_RE` above) so a "2." bullet
    #    isn't read as citing the number 2.
    for value in extract_numbers(_LIST_MARKER_RE.sub("", body)):
        if value in _FREE_NUMBERS:
            continue
        if not any(abs(value - ok) <= _NUMBER_TOLERANCE for ok in budget.numbers):
            reasons.append(f"cites {value:g}, which is not in this turn's tool results")

    # 4. UNCITED RULES PARAPHRASE (HEURISTIC -- see the block above this function; this
    #    is a bounded improvement, not a complete fix). `budget.rule_numbers` is
    #    populated ONLY by search_rules/get_rule succeeding this turn (see tools.py), so
    #    an empty set here means neither ran, or ran and found nothing -- in that case, a
    #    sentence pairing a definitional phrase with a core rules-vocabulary term, with no
    #    rule-number citation nearby, is flagged as an unverified paraphrase rather than
    #    let through on trust alone. A citation anywhere in the sentence (checked with the
    #    same RULE_NUM_RE used above) or any rule number already in the budget both clear
    #    it, since either means the claim has something backing it besides the model's own
    #    say-so.
    if not budget.rule_numbers:
        for sentence in _SENTENCE_SPLIT_RE.split(body):
            if RULE_NUM_RE.search(sentence):
                continue
            def_matches = list(_DEFINITIONAL_PHRASE_RE.finditer(sentence))
            vocab_matches = list(_RULES_VOCAB_RE.finditer(sentence))
            if not def_matches or not vocab_matches:
                continue
            if any(_words_between(sentence, d, v) <= _DEFINITION_PROXIMITY_WORDS
                   for d in def_matches for v in vocab_matches):
                term = vocab_matches[0].group(0)
                reasons.append(
                    f"defines {term!r} with rules-sounding phrasing but no rule citation "
                    "and no evidence search_rules/get_rule ran this turn"
                )
                break

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
