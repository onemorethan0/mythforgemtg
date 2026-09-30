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
    r"\b(?:interaction|answers?|removal|counterspells?|counters|consisten\w*|ceiling|speed)\b",
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
            r"\b(?:a\s+fast|a\s+quick|very\s+fast|fast\s+(?:deck|clock|kill|start|win)|"
            r"quick\s+(?:clock|kill|win)|kills?\s+(?:very\s+)?(?:early|quickly|fast))\b",
            re.IGNORECASE,
        ),
        "slow": re.compile(
            r"\b(?:a\s+slow|slow\s+(?:deck|clock|kill|start|win)|sluggish|grindy|grinds?|"
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


def claimed_resilience(text: str) -> set[str]:
    """Resilience bands the reply CLAIMS: "resilient" / "vulnerable" for plain statements,
    "moderate" for hedged ones. Only sentences about wipes/resilience count."""
    claimed: set[str] = set()
    for sentence in split_sentences(text):
        if not RESILIENCE_TOPIC_RE.search(sentence):
            continue
        about_resilience = bool(_RESILIENCE_WORD_RE.search(sentence))
        for band, pat in PHRASES["resilience"].items():
            if band == "moderate":
                # A bare "moderate/decent/average" is the loosest word in this map: it only
                # counts right next to the topic, and not in a sentence about another axis
                # ("a moderate interaction score ... 1 wipe"), unless it says "resilience".
                if _OTHER_AXIS_RE.search(sentence) and not about_resilience:
                    continue
                hits = _phrase_hits(sentence, pat, RESILIENCE_TOPIC_RE, window=3)
            else:
                hits = _phrase_hits(sentence, pat, RESILIENCE_TOPIC_RE)
            for kind in hits:
                claimed.add(band if kind == "plain" else "moderate")
    return claimed


def claimed_speed(text: str) -> set[str]:
    """Speed bands the reply claims: "fast" / "slow" (hedged -> "moderate")."""
    claimed: set[str] = set()
    for sentence in split_sentences(text):
        for band, pat in PHRASES["speed"].items():
            for kind in _phrase_hits(sentence, pat):
                claimed.add(band if kind == "plain" else "moderate")
    return claimed


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
