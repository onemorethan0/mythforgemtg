"""Verdict vocabulary for the Deck Mentor's open-ended ("tell me about my deck") answers.

The doctrine is "tools assert, the model narrates, the gate checks". For a holistic
question the engine already holds the STRUCTURED answer (a resilience score, an archetype
string, a goldfish clock) -- what the model adds is a sentence, and a sentence can invert
the verdict ("somewhat vulnerable" for a deck the engine measures at 93/100 resilience)
without naming a card, a number or a rule, which is everything the claim-budget gate
(`mentor.gate`) can see. This module is the single home of:

  * the BANDS that turn a measured score into a verdict word (resilient / vulnerable /
    moderate, fast / slow, ...), so the tool (`get_power_profile`'s `verdicts`), the bench
    (`scripts/mentor_holistic_bench.py`) and -- later -- the gate read ONE definition;
  * the PHRASE MAPS that recognise a verdict in prose.

Bias: UNDER-flag. A phrase map that misses a paraphrase lets a wrong verdict through once;
one that over-fires rejects honest prose, which is the failure mode this repo's gate
history (docs/MENTOR_HANDOFF.md, rounds 1-7) is full of. Patterns are therefore narrow,
negation-aware ("not vulnerable"), and hedge-aware ("somewhat vulnerable" reads as a
MODERATE claim, not a vulnerable one).

Thresholds mirror `ratings/insight.py`'s own strength/weakness cut-offs (resilience >= 65
"Resilient to wipes", < 40 "Folds to board wipes"; consistency >= 70 / < 50; interaction
>= 55 / < 30) so the prose the engine itself writes and the verdicts derived here cannot
disagree.
"""

from __future__ import annotations

import re

# ── bands ───────────────────────────────────────────────────────────────────────────

RESILIENT_MIN = 65.0     # insight._verdict: "Resilient to wipes"
VULNERABLE_MAX = 40.0    # insight._verdict: "Folds to board wipes" (strictly below)

FAST_KILL_TURN = 6.0     # goldfish kill at or before this turn: a fast clock
SLOW_KILL_TURN = 9.0     # after this turn: a slow clock
MIN_KILL_RATE = 0.2      # below this share of games killing at all: no reliable clock

CONSISTENT_MIN = 70.0    # insight._verdict
SHAKY_MAX = 50.0
DEEP_INTERACTION_MIN = 55.0
THIN_INTERACTION_MAX = 30.0


def resilience_band(score: float | None) -> str:
    """>= 65 resilient, < 40 vulnerable, else moderate; "unknown" when not measured."""
    if score is None:
        return "unknown"
    if score >= RESILIENT_MIN:
        return "resilient"
    if score < VULNERABLE_MAX:
        return "vulnerable"
    return "moderate"


def speed_band(avg_kill_turn: float | None, kill_rate: float | None) -> str:
    """The goldfish clock as a word. "none" = no reliable unopposed kill inside the
    horizon (insight writes "grindy" for the same condition)."""
    if avg_kill_turn is None or not kill_rate or kill_rate < MIN_KILL_RATE:
        return "none"
    if avg_kill_turn <= FAST_KILL_TURN:
        return "fast"
    if avg_kill_turn <= SLOW_KILL_TURN:
        return "moderate"
    return "slow"


def consistency_band(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= CONSISTENT_MIN:
        return "consistent"
    if score < SHAKY_MAX:
        return "shaky"
    return "moderate"


def interaction_band(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= DEEP_INTERACTION_MIN:
        return "deep"
    if score < THIN_INTERACTION_MAX:
        return "thin"
    return "moderate"


# Archetype strings exactly as `insight.build_insight` spells them -> family.
ARCHETYPE_FAMILIES: dict[str, str] = {
    "Combo": "combo",
    "Spellslinger / storm": "spellslinger",
    "Go-wide / tokens": "go_wide",
    "Control": "control",
    "Creature aggro": "aggro",
    "Ramp / midrange": "midrange",
    "Midrange goodstuff": "midrange",
}

# Families that win the same way (by creatures in combat) and so are interchangeable in
# casual prose: calling a "Midrange goodstuff" deck "creature-based" or "aggressive" is
# not a contradiction. control / combo / spellslinger each stand alone.
_COMPAT_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"aggro", "go_wide", "midrange"}),
)


def archetype_family(archetype: str | None) -> str:
    """Family of an `insight.archetype` string; "unknown" if it isn't one we know."""
    return ARCHETYPE_FAMILIES.get(archetype or "", "unknown")


def compatible_families(family: str) -> frozenset[str]:
    for group in _COMPAT_GROUPS:
        if family in group:
            return group
    return frozenset({family})


def classify_profile(a) -> dict[str, str]:
    """Verdict words for one `DeckAnalysis` (duck-typed, like `insight.build_insight`).

    Keys: resilience, speed, consistency, interaction, archetype (family). Every value is
    derived from a measured field; "unknown" means the field was not measured."""
    res = getattr(a, "resilience", None)
    report = a.report
    insight = getattr(a, "insight", None)
    return {
        "resilience": resilience_band(res.resilience_score if res is not None else None),
        "speed": speed_band(report.avg_kill_turn, report.goldfish_kill_rate),
        "consistency": consistency_band(report.consistency_score),
        "interaction": interaction_band(a.interaction.score),
        "archetype": archetype_family(insight.archetype if insight is not None else None),
    }


# ── phrase maps ─────────────────────────────────────────────────────────────────────

# Sentence splitter shared by every detector below.
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")

# A negator within a few words BEFORE a phrase flips it ("not vulnerable", "isn't fragile",
# "no real weakness to wipes"). Flipped mentions are dropped, not inverted: under-flag.
_NEGATOR_RE = re.compile(
    r"\b(?:not|no|never|isn'?t|aren'?t|doesn'?t|don'?t|without|hardly|barely|cannot|can'?t)\b"
    r"(?:\W+\w+){0,3}\W*$",
    re.IGNORECASE,
)
# A hedge within two words BEFORE a phrase demotes it to a MODERATE claim.
_HEDGE_RE = re.compile(
    r"\b(?:somewhat|slightly|a\s+bit|a\s+little|fairly|moderately|relatively|kind\s+of|"
    r"sort\s+of|partly|mildly|reasonably|rather|pretty)\W+(?:\w+\W+){0,1}$",
    re.IGNORECASE,
)

# Resilience topic words: a sentence must be ABOUT wipes/resilience for a verdict phrase
# in it to count ("vulnerable to flyers" is not a wipe-resilience claim).
RESILIENCE_TOPIC_RE = re.compile(
    r"\b(?:wipes?|wiped|sweepers?|wraths?|resilien\w*|mass removal|board wipes?|"
    r"reset(?:s|ting)?)\b",
    re.IGNORECASE,
)

_RESILIENCE_WORD_RE = re.compile(r"\bresilien\w*", re.IGNORECASE)
_OTHER_AXIS_RE = re.compile(
    r"\b(?:interact\w*|answers?|removal|counterspells?|counters|consisten\w*|ceiling|speed)\b",
    re.IGNORECASE,
)

PHRASES: dict[str, dict[str, re.Pattern]] = {
    "resilience": {
        "moderate": re.compile(
            r"\b(?:moderate(?:ly)?|middling|average|decent|okay|so[\s-]so|mixed)\b",
            re.IGNORECASE,
        ),
        "resilient": re.compile(
            r"\b(?:resilient|shrugs?\s+(?:it\s+)?off|bounces?\s+back|recovers?\s+(?:well|quickly|easily|fast)|"
            r"survives?\s+(?:a\s+)?(?:board\s+)?(?:wipes?|sweepers?)|holds?\s+up\s+(?:well|to|against|after)"
            r"|well[\s-]protected\s+(?:against|from)|resilience\s+(?:is|of)\s+(?:high|strong|excellent|great))\b",
            re.IGNORECASE,
        ),
        # "vulnerable/weak/exposed/folds" only count when their OBJECT is a wipe: "vulnerable
        # to decks with strong interaction" (live, Tymna) is not a wipe-resilience claim even
        # though "board wipes" sat a few words earlier in the sentence.
        "vulnerable": re.compile(
            r"\b(?:(?:vulnerable|susceptible|exposed|weak|folds?|falls?)\s+(?:to|against)\s+"
            r"(?:(?:an?|the|any|mass|board|single|one)\s+)*(?:wipes?|sweepers?|wraths?|mass\s+removal|resets?)"
            r"|fragile|falls?\s+apart|crumbles?|devastated|(?:set|sets)\s+(?:it\s+)?back\s+hard|"
            r"struggles?\s+to\s+recover|hurts?\s+(?:a\s+lot|badly)|creature[\s-]reliant)\b",
            re.IGNORECASE,
        ),
    },
    "speed": {
        # Narrow on purpose: "fast mana" and "quickly" are everywhere in deck chat.
        "fast": re.compile(
            # "a fast/quick" only as a frame for the DECK ("a quick source of mana" -- live, an
            # Isshin key-cards list of mana rocks -- is not a clock claim), and "fast win
            # conditions" is what opposing decks have.
            r"\b(?:a\s+(?:very\s+)?(?:fast|quick)(?=\s+(?:deck|clock|kill|win|start|game|finish|pace|"
            r"build|strategy|list|aggro|plan|but)\b)|very\s+fast(?!\s+(?:mana|lands?|rocks?|ramp))|"
            r"fast\s+(?:deck|clock|kill|start)|fast\s+win(?!\s+conditions?)|"
            r"quick\s+(?:clock|kill|win)|kills?\s+(?:very\s+)?(?:early|quickly|fast))\b",
            re.IGNORECASE,
        ),
        "slow": re.compile(
            r"\b(?:a\s+slow(?=\s+(?:deck|clock|kill|win|start|game|finish|pace|build|strategy|list|plan|but)\b)|"
            r"slow\s+(?:deck|clock|kill|start|win)|sluggish|grindy|grinds?|"
            r"takes?\s+a\s+long\s+time|wins?\s+slowly)\b",
            re.IGNORECASE,
        ),
    },
}

# Label phrasing per archetype family: the word must be used AS A LABEL for the deck
# ("a control deck", "control strategy", "plays like a combo build") -- a bare "control" or
# "combo" appears in ordinary prose about individual cards.
_LABEL_TAIL = r"(?:\s+\w+){0,1}\s+(?:deck|build|strategy|archetype|plan|style|shell|list)\b"
ARCHETYPE_PHRASES: dict[str, re.Pattern] = {
    "combo": re.compile(r"\bcombo" + _LABEL_TAIL, re.IGNORECASE),
    "spellslinger": re.compile(
        r"\b(?:spellslinger|storm|spells?[\s-]matter|magecraft)" + _LABEL_TAIL, re.IGNORECASE),
    "control": re.compile(r"\bcontrol" + _LABEL_TAIL, re.IGNORECASE),
    "aggro": re.compile(r"\b(?:aggro|aggressive|voltron)" + _LABEL_TAIL, re.IGNORECASE),
    "go_wide": re.compile(
        r"\b(?:go[\s-]wide|tokens?|swarm|wide)" + _LABEL_TAIL, re.IGNORECASE),
    "midrange": re.compile(
        r"\b(?:midrange|goodstuff|good[\s-]stuff|value|ramp)" + _LABEL_TAIL, re.IGNORECASE),
}

# Words that describe a combat/creature win route without labelling the deck -- accepted
# as "states how it wins" for a combat-family archetype.
COMBAT_ROUTE_RE = re.compile(
    r"\b(?:combat|attack(?:s|ing)?|creatures?|beats?|races?|racing|damage|swing(?:s|ing)?)\b",
    re.IGNORECASE,
)

# How a family WINS, in the words the engine's own `insight.gameplan` uses ("grinds value
# into a midrange finish", "floods the board and closes with a team-pump alpha strike",
# "chains cheap spells into a storm/magecraft burn finish") -- a reply that restates the win
# route without ever writing "<family> deck" still says how the deck wins.
ROUTE_PHRASES: dict[str, re.Pattern] = {
    "midrange": re.compile(
        r"\b(?:grind\w*|midrange|outlast\w*|value|goodstuff|good[\s-]stuff|ramp\w*)\b", re.IGNORECASE),
    "go_wide": re.compile(
        r"\b(?:go(?:es|ing)?\s+wide|wide\s+board|tokens?|alpha[\s-]strike|team[\s-]pump|swarm\w*|"
        r"overwhelm\w*)\b", re.IGNORECASE),
    "aggro": re.compile(r"\b(?:aggress\w*|pressure|fast\s+damage|voltron|attack\w*)\b", re.IGNORECASE),
    "spellslinger": re.compile(
        r"\b(?:storm|magecraft|spells?|burn|go[\s-]off|chains?)\b", re.IGNORECASE),
    "combo": re.compile(r"\b(?:combo\w*|infinite|assembl\w*)\b", re.IGNORECASE),
    "control": re.compile(r"\b(?:answers?|counter\w*|grind\w*|control\w*|removal)\b", re.IGNORECASE),
}

# `insight.strengths` strings begin with a fixed lead ("Consistent engine ...", "Resilient
# to wipes ...", "Deep interaction ...", "High ceiling ...", "Strong multiplayer closing
# power ..."). The topic of each -> a regex a reply must hit to count as "mentions it".
STRENGTH_TOPICS: dict[str, re.Pattern] = {
    "consistency": re.compile(r"\b(?:consisten\w*|reliab\w*|smooth\w*|commander (?:lands|online))\b", re.IGNORECASE),
    "resilience": re.compile(r"\b(?:resilien\w*|wipes?|sweepers?|wraths?)\b", re.IGNORECASE),
    "interaction": re.compile(r"\b(?:interaction|removal|answers?|counterspells?)\b", re.IGNORECASE),
    "ceiling": re.compile(r"\b(?:ceiling|combo|explosive|fast finish)\b", re.IGNORECASE),
    "pod": re.compile(r"\b(?:multiplayer|pod|table|closing power)\b", re.IGNORECASE),
}
_STRENGTH_LEADS: tuple[tuple[str, str], ...] = (
    ("consistent engine", "consistency"),
    ("resilient to wipes", "resilience"),
    ("deep interaction", "interaction"),
    ("high ceiling", "ceiling"),
    ("strong multiplayer", "pod"),
)


def strength_topic(strength: str) -> str | None:
    """Topic key of one `insight.strengths` line, or None if it isn't a known lead."""
    low = strength.strip().lower()
    for lead, topic in _STRENGTH_LEADS:
        if low.startswith(lead):
            return topic
    return None


# ── detectors ───────────────────────────────────────────────────────────────────────


_MARKDOWN_EMPHASIS_RE = re.compile(r"[*_`#]+")


def plain(text: str) -> str:
    """Reply text with markdown emphasis stripped. The model writes "**midrange goodstuff**
    build" despite the no-markdown rule, and the asterisks sit between the words a label
    pattern needs to see adjacent."""
    return _MARKDOWN_EMPHASIS_RE.sub("", text or "")


def split_sentences(text: str) -> list[str]:
    return [s for s in SENTENCE_SPLIT_RE.split(plain(text)) if s.strip()]


_TOPIC_WINDOW_WORDS = 6


def _topic_near(sentence: str, m: re.Match, topic: re.Pattern,
                window: int = _TOPIC_WINDOW_WORDS) -> bool:
    """The topic appears inside the phrase or within a few words of it. A sentence-wide
    topic test lets "moderate interaction ... (4 removal, 0 counters, 1 wipes)" read as a
    moderate WIPE-RESILIENCE claim because the list ends in "wipes" -- found on the first
    live Shelob run after A2."""
    before = " ".join(sentence[:m.start()].split()[-window:])
    after = " ".join(sentence[m.end():].split()[:window])
    return bool(topic.search(f"{before} {m.group(0)} {after}"))


def _phrase_hits(sentence: str, pattern: re.Pattern, topic: re.Pattern | None = None,
                 window: int = _TOPIC_WINDOW_WORDS) -> list[str]:
    """Phrase matches in `sentence` that are neither negated nor hedged -> "plain";
    hedged -> "hedged"; negated -> dropped. With `topic`, the phrase must sit within
    `window` words of it."""
    out: list[str] = []
    for m in pattern.finditer(sentence):
        if topic is not None and not _topic_near(sentence, m, topic, window):
            continue
        before = sentence[:m.start()]
        if _NEGATOR_RE.search(before):
            continue
        out.append("hedged" if _HEDGE_RE.search(before) else "plain")
    return out


# Every axis's own topic words. A verdict phrase belongs to the axis whose topic word is NEAREST
# to it in the sentence ("resilient to wipes and moderately interactive": "moderately" binds to
# "interactive", not to the "wipes" two words back) -- the false positive the orchestrator found
# on the Shelob overview. Equidistant topics of different axes bind to nothing (under-flag).
AXIS_TOPICS: dict[str, re.Pattern] = {
    "resilience": RESILIENCE_TOPIC_RE,
    "interaction": re.compile(
        r"\b(?:interact\w*|removal|answers?|counterspells?|counters|spot\s+removal)\b", re.IGNORECASE),
    "consistency": re.compile(
        r"\b(?:consisten\w*|reliab\w*|mana\s*base|manabase|mulligans?|smooth\w*)\b", re.IGNORECASE),
    "ceiling": re.compile(r"\b(?:ceiling|combos?|finish\w*|explosive)\b", re.IGNORECASE),
    "speed": re.compile(r"\b(?:speed|fast|quick\w*|clock|slow\w*|pace)\b", re.IGNORECASE),
}
_WORD_RE = re.compile(r"[\w'-]+")


def bound_axis(sentence: str, m: re.Match) -> str | None:
    """The axis a phrase match `m` in `sentence` is ABOUT: the one whose topic word is nearest
    (fewest words between; a topic word inside the phrase itself is nearest of all). None when
    no topic word is in the sentence or two different axes tie."""
    words = [(w.start(), w.end()) for w in _WORD_RE.finditer(sentence)]
    if not words:
        return None
    first = next((i for i, (a, _b) in enumerate(words) if a >= m.start()), len(words))
    last = max((i for i, (_a, b) in enumerate(words) if b <= m.end()), default=first)
    best: dict[str, int] = {}
    for axis, pat in AXIS_TOPICS.items():
        for t in pat.finditer(sentence):
            ti = next((i for i, (a, b) in enumerate(words) if a <= t.start() < b), None)
            if ti is None:
                continue
            if first <= ti <= last:
                gap = -1
            elif ti > last:
                gap = ti - last - 1
            else:
                gap = first - ti - 1
            if axis not in best or gap < best[axis]:
                best[axis] = gap
    if not best:
        return None
    low = min(best.values())
    winners = [a for a, g in best.items() if g == low]
    return winners[0] if len(winners) == 1 else None


def resilience_claims(text: str) -> list[tuple[str, str]]:
    """(band, kind) for every resilience claim in the reply: band is "resilient" / "vulnerable"
    / "moderate", kind is "plain" or "hedged" ("somewhat vulnerable"). Only sentences about
    wipes/resilience count, and each phrase must be BOUND to the resilience axis (see
    `bound_axis`)."""
    claims: list[tuple[str, str]] = []
    for sentence in split_sentences(text):
        if not RESILIENCE_TOPIC_RE.search(sentence):
            continue
        about_resilience = bool(_RESILIENCE_WORD_RE.search(sentence))
        for band, pat in PHRASES["resilience"].items():
            matches = list(pat.finditer(sentence))
            if band == "moderate":
                # A bare "moderate/decent/average" is the loosest word in this map: it only
                # counts right next to the topic, and not in a sentence about another axis
                # ("a moderate interaction score ... 1 wipe"), unless it says "resilience".
                if _OTHER_AXIS_RE.search(sentence) and not about_resilience:
                    continue
            for m in matches:
                if bound_axis(sentence, m) != "resilience":
                    continue
                window = 3 if band == "moderate" else _TOPIC_WINDOW_WORDS
                if not _topic_near(sentence, m, RESILIENCE_TOPIC_RE, window):
                    continue
                before = sentence[:m.start()]
                if _NEGATOR_RE.search(before):
                    continue
                claims.append((band, "hedged" if _HEDGE_RE.search(before) else "plain"))
    return claims


def claimed_resilience(text: str) -> set[str]:
    """Resilience bands the reply CLAIMS: "resilient" / "vulnerable" for plain statements,
    "moderate" for hedged ones. Only sentences about wipes/resilience count."""
    return {band if kind == "plain" else "moderate" for band, kind in resilience_claims(text)}


# "your deck is already quite fast" / "it's very slow": an intensified bare adjective with no
# "a fast deck" frame (the Phase A agent's note: the model said this about decks measured
# `slow`, and no phrase caught it). Counts only in a sentence about the deck's clock, never
# before "mana"/"lands"/"ramp" ("fast mana" is everywhere in deck chat).
_GENERIC_SPEED_RE = re.compile(
    r"\b(?P<lead>already|quite|really|very|extremely|incredibly|pretty|fairly|rather)\s+"
    r"(?:\w+\s+)?(?P<word>fast|quick|slow|sluggish)\b(?!\s+(?:mana|lands?|rocks?|ramp|draws?|starts?))",
    re.IGNORECASE,
)
_GENERIC_HEDGES = frozenset({"pretty", "fairly", "rather"})
SPEED_TOPIC_RE = re.compile(
    r"\b(?:deck|clock|kills?|win(?:s|ning)?|goldfish|pace|speed|game|build|strategy|list)\b",
    re.IGNORECASE,
)


# "... may struggle against decks with strong interaction or fast win conditions": a speed word
# about the OPPONENT is not a claim about this deck's clock.
_OPPONENT_BEFORE_RE = re.compile(
    r"\b(?:against|versus|vs\.?|opponents?|opposing|decks?\s+(?:with|that|like)|faster\s+than)\b"
    r"(?:\W+\w+){0,6}\W*$",
    re.IGNORECASE,
)


def speed_claims(text: str) -> list[tuple[str, str]]:
    """(band, kind) for every speed claim: band "fast" / "slow", kind "plain" / "hedged"."""
    claims: list[tuple[str, str]] = []
    for sentence in split_sentences(text):
        for band, pat in PHRASES["speed"].items():
            for m in pat.finditer(sentence):
                before = sentence[:m.start()]
                if _NEGATOR_RE.search(before) or _OPPONENT_BEFORE_RE.search(before):
                    continue
                claims.append((band, "hedged" if _HEDGE_RE.search(before) else "plain"))
        if not SPEED_TOPIC_RE.search(sentence):
            continue
        for m in _GENERIC_SPEED_RE.finditer(sentence):
            if _NEGATOR_RE.search(sentence[:m.start()]):
                continue
            band = "fast" if m.group("word").lower() in ("fast", "quick") else "slow"
            hedged = (m.group("lead").lower() in _GENERIC_HEDGES
                      or bool(_HEDGE_RE.search(sentence[:m.start()])))
            claims.append((band, "hedged" if hedged else "plain"))
    return claims


def claimed_speed(text: str) -> set[str]:
    """Speed bands the reply claims: "fast" / "slow" (hedged -> "moderate")."""
    return {band if kind == "plain" else "moderate" for band, kind in speed_claims(text)}


# ── consistency / interaction: narrow, in-phrase-topic claims ───────────────────────────

_CONSISTENCY_PHRASES: dict[str, re.Pattern] = {
    "consistent": re.compile(
        r"\b(?:(?:highly|very|quite|really|extremely|incredibly)\s+consistent|"
        r"consistent\s+(?:deck|engine|draws?|mana|manabase|mana\s+base)|"
        r"consistency\s+(?:is|looks?|seems?)\s+(?:high|great|strong|excellent|solid|good))\b",
        re.IGNORECASE),
    "shaky": re.compile(
        r"\b(?:inconsistent(?!\s+with)|(?:unreliable|clunky)\s+(?:deck|engine|draws?|hands?|mana(?:\s*base)?)|"
        r"consistency\s+(?:is|looks?|seems?)\s+(?:low|poor|weak|shaky|bad))\b", re.IGNORECASE),
}
# "deep/strong interaction" vs "thin/little interaction". The thin forms must not be followed
# by an object ("lacks interaction for planeswalkers" is a specific gap, not a verdict).
_INTERACTION_PHRASES: dict[str, re.Pattern] = {
    "deep": re.compile(
        r"\b(?:(?:deep|strong|robust|excellent|great|plenty\s+of|lots\s+of)\s+interaction)\b",
        re.IGNORECASE),
    "thin": re.compile(
        r"\b(?:(?:thin|weak|light|little|limited|poor|minimal)\s+interaction|"
        r"(?:lacks?|short\s+on|low\s+on|light\s+on)\s+interaction)\b"
        r"(?!\s+(?:for|against|to|vs|when|with|in))", re.IGNORECASE),
}


def _claims(text: str, phrases: dict[str, re.Pattern]) -> list[tuple[str, str]]:
    claims: list[tuple[str, str]] = []
    for sentence in split_sentences(text):
        for band, pat in phrases.items():
            for m in pat.finditer(sentence):
                before = sentence[:m.start()]
                # "needs more answers against decks with strong interaction": the opponent's
                if _NEGATOR_RE.search(before) or _OPPONENT_BEFORE_RE.search(before):
                    continue
                claims.append((band, "hedged" if _HEDGE_RE.search(before) else "plain"))
    return claims


def consistency_claims(text: str) -> list[tuple[str, str]]:
    return _claims(text, _CONSISTENCY_PHRASES)


def interaction_claims(text: str) -> list[tuple[str, str]]:
    return _claims(text, _INTERACTION_PHRASES)


# ── the gate's verdict check (PLAN_MENTOR_ADHOC F1) ─────────────────────────────────────

# measured band -> the claimed bands that CONTRADICT it. UNDER-flag by design: only the
# opposite end contradicts; a neutral/"moderate" claim never does, and a measured "moderate"
# band is contradicted by nothing (the bench's resilience rubric is stricter; the gate is not).
_OPPOSITE: dict[str, dict[str, frozenset[str]]] = {
    "resilience": {"resilient": frozenset({"vulnerable"}), "vulnerable": frozenset({"resilient"})},
    "speed": {"slow": frozenset({"fast"}), "none": frozenset({"fast"}), "fast": frozenset({"slow"})},
    "consistency": {"consistent": frozenset({"shaky"}), "shaky": frozenset({"consistent"})},
    "interaction": {"deep": frozenset({"thin"}), "thin": frozenset({"deep"})},
}
_AXIS_WORDS = {
    "resilience": "resilience to board wipes", "speed": "speed", "consistency": "consistency",
    "interaction": "interaction",
}


# A sentence that places the deck AMONG a bracket's decks ("already quite fast for its bracket",
# "consistency is below average for bracket 3 decks") is a RELATIVE claim, licensed by
# get_power_profile's `vs_bracket` standings -- it can be true while the absolute verdict is
# "slow" (an avg kill turn of ~9 is the top quarter of bracket 1-4 decks, whose median is ~10).
# The gate exempts such sentences; the absolute verdict is still enforced everywhere else.
RELATIVE_FRAME_RE = re.compile(
    r"\bfor\s+(?:its|an?|the|your|their)\s+(?:\w+\s+){0,2}bracket\b|\bbracket\s*[1-5]\b|\bB[1-5]\b|"
    r"\bamong\b|\bcompared\s+(?:to|with)\b|\bthan\s+(?:most|many|other|typical|average)\b|"
    r"\b(?:top|bottom)\s+(?:quarter|half)\b|\b(?:above|below)\s+(?:average|median|typical)\b|"
    r"\btypical\b|\bmedian\b",
    re.IGNORECASE,
)


def absolute_claims_text(text: str) -> str:
    """`text` without its relative-to-bracket sentences (see RELATIVE_FRAME_RE)."""
    return " ".join(s for s in split_sentences(text) if not RELATIVE_FRAME_RE.search(s))


def profile_contradictions(text: str, measured: dict[str, str]) -> list[str]:
    """Reasons a reply contradicts the verdicts `get_power_profile` measured, one per axis
    (resilience, speed, consistency, interaction) plus the archetype family. Each phrase is
    bound to its own axis topic in its own sentence; hedged claims of the SAME direction as
    the measurement never contradict ("fairly resilient" for a resilient deck), hedged
    opposite claims do ("somewhat vulnerable" for a resilient deck -- the original
    inversion). `measured` holds the profile's `verdicts` object; absent or "unknown"
    entries are skipped."""
    reasons: list[str] = []
    text = absolute_claims_text(text)
    claim_fns = {
        "resilience": resilience_claims, "speed": speed_claims,
        "consistency": consistency_claims, "interaction": interaction_claims,
    }
    for axis, fn in claim_fns.items():
        verdict = measured.get(axis)
        opposite = _OPPOSITE[axis].get(verdict or "")
        if not opposite:
            continue
        hit = next((band for band, _kind in fn(text) if band in opposite), None)
        if hit:
            reasons.append(
                f"says the deck's {_AXIS_WORDS[axis]} is {hit}, contradicting the measured "
                f"verdict ({verdict}) from get_power_profile")
    family = measured.get("archetype")
    if family and family != "unknown":
        ok = compatible_families(family)
        wrong = sorted(claimed_archetype_families(text) - ok)
        if wrong:
            reasons.append(
                f"labels the deck {'/'.join(wrong)}, contradicting the measured archetype "
                f"family ({family}) from get_power_profile")
    return reasons


def speed_agrees(band: str, claimed: set[str]) -> bool:
    """A "moderate" measured clock contradicts neither a hedged nor... only a PLAIN
    opposite claim: fast vs slow. Measured "none" counts as slow."""
    if not claimed:
        return True
    measured = "slow" if band == "none" else band
    for c in claimed:
        if c == "moderate":
            continue
        if measured == "moderate":
            continue
        if c != measured:
            return False
    return True


def claimed_archetype_families(text: str) -> set[str]:
    """Families the reply LABELS the deck with ("a control deck", "a tokens strategy")."""
    body = plain(text)
    return {fam for fam, pat in ARCHETYPE_PHRASES.items() if pat.search(body)}


def archetype_contradictions(text: str, archetype: str | None) -> list[str]:
    """Families the reply labels the deck as that are NOT compatible with the measured
    archetype. Empty when the archetype is unknown (nothing to contradict)."""
    fam = archetype_family(archetype)
    if fam == "unknown":
        return []
    ok = compatible_families(fam)
    return sorted(claimed_archetype_families(text) - ok)


def states_archetype_or_route(text: str, archetype: str | None) -> bool:
    """True when the reply labels the deck with a compatible family word, or (for a
    combat-family archetype) describes a combat/creature win route."""
    fam = archetype_family(archetype)
    ok = compatible_families(fam)
    if claimed_archetype_families(text) & ok:
        return True
    body = plain(text)
    if any(ROUTE_PHRASES[f].search(body) for f in ok if f in ROUTE_PHRASES):
        return True
    return fam in _COMPAT_GROUPS[0] and bool(COMBAT_ROUTE_RE.search(body))


# ── unmeasured side claims on a measured swap (Round 8 residual, 2026-10-01) ─────────────
#
# A swap search measures ONE axis (a clock swap re-simulates the clock; a resilience swap, the
# wipe score). Narrating it is licensed for that axis only, yet a live reply for a measured
# clock swap (add Solemn Simulacrum, cut Ultimate Magic: Meteor, clock 20.1 -> 21.4) added
# "cutting it doesn't hurt your deck's interaction or resilience" and "maintaining its
# consistency and interaction". Neither was simulated, and the sentence names no card or number,
# so gate checks 1-6 cannot see it. The gate (check 7) and the bench (`faster`/`weakest`/`dual`
# rubrics) both read THIS vocabulary.
#
# Narrow on purpose (under-flag, same bias as the rest of this module): a sentence must hold
# BOTH a "this leaves X unharmed" phrase AND a topic word of an axis that was NOT measured this
# turn, in the phrase's object position. "This keeps your mana base intact" names no axis topic
# word and never fires; a sentence about the measured axis itself never fires.

# Swap-tool axis names -> the claim family a topic word belongs to. `clock` is the speed lens.
_SWAP_AXIS_FAMILY = {"clock": "speed", "speed": "speed", "resilience": "resilience",
                     "interaction": "interaction", "consistency": "consistency",
                     "ceiling": "ceiling"}


def swap_axis_family(axis: str | None) -> str | None:
    return _SWAP_AXIS_FAMILY.get(axis or "")


# Topic words per family, deliberately tighter than AXIS_TOPICS: no bare "fast"/"slow"/"quick",
# no "mana base" (a manabase is not an axis a swap search measures).
SIDE_CLAIM_TOPICS: dict[str, re.Pattern] = {
    "speed": re.compile(r"\b(?:speed|clock|kill\s+turn|pace)\b", re.IGNORECASE),
    "resilience": re.compile(
        r"\b(?:resilien\w*|wipes?|sweepers?|wraths?|mass\s+removal|board\s+wipes?)\b", re.IGNORECASE),
    "interaction": re.compile(
        r"\b(?:interact\w*|removal|counterspells?|spot\s+removal)\b", re.IGNORECASE),
    "consistency": re.compile(r"\bconsisten\w*\b", re.IGNORECASE),
    "ceiling": re.compile(r"\bceiling\b", re.IGNORECASE),
}

# "this leaves X unharmed" with X AFTER the phrase. Two strengths: a NEGATED harm verb ("doesn't
# hurt your interaction") is a claim anywhere in its clause; the bare "maintain/keep/preserve"
# family is ordinary English ("maintaining a good curve matters") so its object must be right
# next to it.
_SIDE_VERB_RE = re.compile(
    r"\b(?:(?:doesn'?t|does\s+not|won'?t|will\s+not|wouldn'?t|would\s+not|shouldn'?t|"
    r"should\s+not|isn'?t\s+going\s+to|not\s+going\s+to)\s+(?:\w+\s+){0,1}?"
    r"(?:hurt|harm|affect|weaken|reduce|compromise|damage|impact|undermine|diminish|lower|"
    r"sacrifice|slow|cost\s+you|lose|touch)"
    r"|without\s+(?:\w+\s+){0,1}?(?:sacrificing|hurting|harming|losing|compromising|weakening|"
    r"giving\s+up|affecting|reducing|undermining|lowering|slowing)"
    r"|no\s+(?:negative\s+|real\s+|significant\s+|noticeable\s+)?(?:impact|effect|downside)\s+"
    r"(?:on|to))\b",
    re.IGNORECASE,
)
_SIDE_KEEP_RE = re.compile(
    r"\b(?:(?:maintain|maintains|maintaining|maintained|preserve|preserves|preserving|retain|"
    r"retains|retaining)|(?:keeps?|keeping)\s+(?:its|your|the|their))\b",
    re.IGNORECASE,
)
# "X stays unharmed" with X BEFORE the phrase ("your interaction is unaffected").
_SIDE_STATE_RE = re.compile(
    r"\b(?:unaffected|unharmed|untouched|unchanged|intact|(?:isn'?t|is\s+not|aren'?t|are\s+not|"
    r"remains?|stays?)\s+(?:\w+\s+){0,1}?(?:affected|hurt|harmed|weakened|compromised)|"
    r"(?:is|are|remains?|stays?)\s+(?:\w+\s+){0,1}?(?:maintained|preserved|retained))\b",
    re.IGNORECASE,
)
# A sentence that says the other axis was NOT measured is the honest disclosure the prompt asks for.
# The verb must follow the negator directly ("haven't measured", "didn't actually test"): "didn't
# find a measured improvement" is a swap result, not a disclosure.
_DISCLOSURE_RE = re.compile(
    r"\b(?:not\s+(?:been\s+)?(?:measured|tested|simulated)|unmeasured|"
    r"(?:did\s*n[o']t|haven'?t|hasn'?t|wasn'?t|weren'?t|can'?t|cannot|couldn'?t|don'?t)\s+"
    r"(?:(?:actually|really|yet|also)\s+)?(?:measure|test|simulat|check|verif|say|promise|"
    r"guarantee|know|tell)\w*|"
    r"only\s+(?:measured|tested|simulated))",
    re.IGNORECASE,
)
_SIDE_WINDOW_WORDS = 8
_SIDE_KEEP_WINDOW_WORDS = 4
# The phrase's object ends where the clause turns ("..., but removal is the real gap").
_CLAUSE_END_RE = re.compile(r"[;:]|\b(?:but|however|although|though)\b", re.IGNORECASE)


def _topic_after(sentence: str, m: re.Match, topic: re.Pattern,
                 window: int = _SIDE_WINDOW_WORDS) -> bool:
    tail = _CLAUSE_END_RE.split(sentence[m.end():], maxsplit=1)[0]
    return bool(topic.search(" ".join(tail.split()[:window])))


def _topic_before(sentence: str, m: re.Match, topic: re.Pattern,
                  window: int = _SIDE_WINDOW_WORDS) -> bool:
    return bool(topic.search(" ".join(sentence[:m.start()].split()[-window:])))


def unmeasured_side_claims(text: str, measured_axes) -> list[tuple[str, str]]:
    """(family, sentence) for each sentence that claims a swap leaves an axis unharmed or
    "maintained" although that axis was not measured. `measured_axes` are the swap tools'
    axis names this turn (`clock`/`speed`, `resilience`, ...); empty means nothing was measured
    and nothing is checked (the gate only runs this when a swap result named an axis)."""
    measured = {f for f in (swap_axis_family(a) for a in measured_axes) if f}
    if not measured:
        return []
    unmeasured = {f: p for f, p in SIDE_CLAIM_TOPICS.items() if f not in measured}
    out: list[tuple[str, str]] = []
    for sentence in split_sentences(text):
        if _DISCLOSURE_RE.search(sentence):
            continue
        hit: str | None = None
        for m in _SIDE_VERB_RE.finditer(sentence):
            hit = next((f for f, p in unmeasured.items() if _topic_after(sentence, m, p)), None)
            if hit:
                break
        if hit is None:
            for m in _SIDE_KEEP_RE.finditer(sentence):
                hit = next((f for f, p in unmeasured.items()
                            if _topic_after(sentence, m, p, _SIDE_KEEP_WINDOW_WORDS)), None)
                if hit:
                    break
        if hit is None:
            for m in _SIDE_STATE_RE.finditer(sentence):
                hit = next((f for f, p in unmeasured.items() if _topic_before(sentence, m, p)), None)
                if hit:
                    break
        if hit:
            out.append((hit, sentence.strip()))
    return out


def side_claim_reasons(text: str, measured_axes) -> list[str]:
    """Gate/bench reasons: one per family claimed unharmed without being measured."""
    measured = sorted({f for f in (swap_axis_family(a) for a in measured_axes) if f})
    seen: set[str] = set()
    reasons: list[str] = []
    for family, _sentence in unmeasured_side_claims(text, measured_axes):
        if family in seen:
            continue
        seen.add(family)
        reasons.append(
            f"claims the swap leaves the deck's {family} unharmed or maintained, but this turn "
            f"only measured {'/'.join(measured)}: describe the swap's effect only on the axis "
            f"it was measured on and offer to measure {family} instead")
    return reasons
