"""Mechanical grading rubrics for `scripts/mentor_holistic_bench.py` (PLAN_MENTOR_ADHOC A0).

Every rubric reads the ENGINE'S OWN ground truth for the deck (`truth`, built by the bench)
and the reply text/tool trace -- never an LLM judge (docs/MENTOR_HANDOFF.md round 7: a second
model checking the first is another chance to hallucinate). Verdict phrase maps and bands are
imported from `mythgauntlet.mentor.verdicts` so the bench and the (later) gate cannot drift.

Each grader returns `(passed, reason)`; `passed` is True / False / None (None = not
applicable, excluded from pass rates). The reason string always says WHY, so a FAIL can be
diagnosed from the table without re-reading the transcript.

`truth` keys: key, ctx (MentorContext), analysis (DeckAnalysis, resilience computed), stats
(`tool_get_deck_stats(ctx).data`), identity (frozenset of colour letters), deck_names
(frozenset of card names incl. commanders).

Bias matches the gate's: UNDER-flag. A rubric that false-fails honest prose is a worse
instrument than one that misses a paraphrase, because the point of this bench is to show
movement caused by real fixes.
"""

from __future__ import annotations

import re

from mythgauntlet.mentor import gate as gate_mod
from mythgauntlet.mentor import verdicts
from mythgauntlet.mentor.tools import tool_suggest_swap

QUESTION_IDS = ("overview", "cards", "faster", "resilience", "wincon", "weakest", "vs_b3", "removal")

# ── shared helpers ──────────────────────────────────────────────────────────────────

_NEG_BEFORE_RE = re.compile(
    r"\b(?:not|no|never|isn'?t|aren'?t|doesn'?t|don'?t|didn'?t|wouldn'?t|shouldn'?t|won'?t|"
    r"without|cannot|can'?t|nothing|lack\w*|missing|absent|short\s+on|shy\s+of)\b"
    r"(?:\W+\w+){0,4}\W*$",
    re.IGNORECASE,
)


def _name_re(name: str) -> re.Pattern:
    return re.compile(r"(?<![\w'])" + re.escape(name) + r"(?![\w])", re.IGNORECASE)


def names_in(text: str, names) -> list[str]:
    """Which of `names` the text mentions (case-insensitive, word-bounded). Sorted."""
    low = text.lower()
    out = []
    for n in names:
        if len(n) < 3 or n.lower() not in low:
            continue
        if _name_re(n).search(text):
            out.append(n)
    return sorted(out)


def _strings_in(value) -> set[str]:
    out: set[str] = set()
    if isinstance(value, str):
        out.add(value)
    elif isinstance(value, dict):
        for v in value.values():
            out |= _strings_in(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            out |= _strings_in(v)
    return out


def _trace_strings(reply) -> set[str]:
    out: set[str] = set()
    for t in reply.tool_trace:
        out |= _strings_in(t.result_data)
    return out


def _foreign_card_names(reply, truth) -> list[str]:
    """Real card names in the reply that are neither in the deck nor returned by a tool
    this turn. (A measured add from the player's collection is legitimately outside the
    deck, but it arrives in a tool result, which licenses it.)"""
    text = reply.text
    allowed = set(truth["deck_names"]) | _trace_strings(reply)
    # Mask every allowed card name first (longest first): the model shortens "Gloomwidow's
    # Feast" to "Gloomwidow", which is ALSO a real card name, and that truncation of a deck
    # card is not a reference to a foreign card.
    known = truth["ctx"].all_card_names
    for n in sorted((a for a in allowed if a in known), key=len, reverse=True):
        text = re.sub(re.escape(n) + r"(?:'s)?", " ", text, flags=re.IGNORECASE)
    for n in sorted(truth["deck_names"], key=len, reverse=True):
        head = n.split(",")[0].split(" // ")[0].strip()
        for frag in {head, head.split("'s ")[0].strip()}:
            if len(frag) <= 3:
                continue
            text = re.sub(r"(?<![\w])" + re.escape(frag) + r"(?:'s)?(?![\w])", " ", text,
                          flags=re.IGNORECASE)
    low = text.lower()
    out = []
    for n in truth["ctx"].all_card_names:
        if len(n.strip()) <= 2 or n.lower() in gate_mod._COMMON_WORD_CARD_NAMES:
            continue
        if n in allowed or n.lower() not in low:
            continue
        for m in re.finditer(r"\b" + re.escape(n) + r"\b", text, re.IGNORECASE):
            if gate_mod._looks_like_a_name(text, m):
                out.append(n)
                break
    return sorted(out)


# ── the swap rubric shared by `faster` and `weakest` ────────────────────────────────

_NO_IMPROVEMENT_RE = re.compile(
    r"(?:no\s+(?:measured|improving|clear|real)\s+(?:improvement|swap|upgrade|gain)|"
    r"(?:did\s*n[o']t|didn'?t|could\s*n[o']t|couldn'?t|did\s+not|could\s+not)\s+(?:find|see|identify|turn\s+up)\b[^.]{0,60}"
    r"(?:improv\w*|swap\w*|upgrade\w*|gain\w*)|"
    r"none\s+(?:of\s+[^.]{0,40})?(?:beat|improv\w*|cleared|passed)|"
    r"no\s+(?:owned\s+)?(?:card|swap|add)s?\s+(?:that\s+)?(?:beat|improv\w*|clear\w*)|"
    r"nothing\s+(?:in\s+your\s+collection\s+)?(?:measurably\s+)?(?:improv\w*|beat|cleared)|"
    r"no\s+measured\s+swap|noise\s+floor|"
    r"no\s+(?:collection\s+file|owned\s+cards)|"
    r"(?:did\s*n[o']t|didn'?t|did\s+not)\s+find\s+any|"
    # phrasings seen live: "no immediate way to ... improve", "there aren't any obvious
    # swaps", "no clear improvement to be made ... based on the cards you own"
    r"no\s+(?:immediate|obvious|clear|significant|easy)\s+(?:way|swaps?|improvements?|upgrades?)|"
    r"(?:aren'?t|are\s+not|isn'?t|is\s+not)\s+any\s+(?:[\w,]+\s+){0,3}(?:swaps?|improvements?|upgrades?)|"
    r"no\s+(?:\w+\s+){0,2}swaps?\s+(?:to|that|i\s+can)\b|"
    # the honest-decline space is wide ("no measurable way to make it faster", "no
    # significant measured gain", "none of the cards I evaluated provided a significant
    # enough boost", "wasn't a clear improvement"): a negator and an improvement word in
    # one clause. Lenient by design -- it is only consulted when the tool found NO swap,
    # and the separate no-cut-recommendation check still applies.
    r"(?:\bno\b|\bnot\b|n't|\bnone\b|\bnothing\b)[^.]{0,60}"
    r"\b(?:measur\w*|improv\w*|gains?|boosts?|swaps?|upgrades?)\b)",
    re.IGNORECASE,
)
_CUT_VERB_RE = re.compile(
    r"\b(?:cut|cutting|remove|removing|swap\s+out|swapping\s+out|drop|dropping|replace|replacing|"
    r"trim|trimming|take\s+out|taking\s+out|get\s+rid\s+of|ditch|ditching)\b",
    re.IGNORECASE,
)


def _swap_calls(reply) -> list[dict]:
    return [t.result_data for t in reply.tool_trace if t.name == "suggest_swap"]


def _measured_suggestions(data: dict) -> list[dict]:
    sugg = data.get("suggestions") or []
    return [s for s in sugg if isinstance(s, dict) and s.get("add") and s.get("cut")]


def _cut_recommendations(text: str, deck_names) -> list[str]:
    """Sentences that recommend cutting a deck card: a cut verb and a deck card name in
    the same sentence, the verb not negated ("I wouldn't cut ...")."""
    found = []
    for sentence in verdicts.split_sentences(text):
        for vm in _CUT_VERB_RE.finditer(sentence):
            if _NEG_BEFORE_RE.search(sentence[:vm.start()]):
                continue
            hit = names_in(sentence, deck_names)
            if hit:
                found.append(f"'{vm.group(0)}' + {hit[0]}")
                break
    return found


def _grade_swap_answer(reply, truth, axis_for_fallback: str | None, cache_key: str):
    calls = _swap_calls(reply)
    note = ""
    if calls:
        measured = [s for d in calls for s in _measured_suggestions(d)]
    else:
        # The reply never asked the tool. Grade against what the tool WOULD have said, so
        # a confident invented recommendation still fails.
        cache = truth.setdefault("_swap_cache", {})
        if cache_key not in cache:
            cache[cache_key] = tool_suggest_swap(truth["ctx"], axis_for_fallback).data
        measured = _measured_suggestions(cache[cache_key])
        note = " (suggest_swap not called; graded against the tool's own result)"
    text = reply.text
    if measured:
        top = measured[0]
        add_ok = bool(names_in(text, [top["add"]]))
        cut_ok = bool(names_in(text, [top["cut"]]))
        if add_ok and cut_ok:
            return True, f"names the measured add {top['add']!r} and cut {top['cut']!r}{note}"
        return False, (f"a measured swap exists ({top['add']!r} for {top['cut']!r}) but the reply "
                       f"does not name both{note}")
    problems = []
    if not _NO_IMPROVEMENT_RE.search(text):
        problems.append("no 'no measured improvement' statement")
    cuts = _cut_recommendations(text, truth["deck_names"])
    if cuts:
        problems.append("recommends cutting a card although no swap was measured: " + "; ".join(cuts[:2]))
    if problems:
        return False, "tool found no improving swap" + note + " -- " + "; ".join(problems)
    return True, "says no measured improvement and recommends no cut" + note


# ── graders ─────────────────────────────────────────────────────────────────────────


def _g_overview(reply, truth):
    a = truth["analysis"]
    prof = verdicts.classify_profile(a)
    text = reply.text
    problems = []
    claimed = verdicts.claimed_resilience(text)
    if claimed and claimed != {prof["resilience"]}:
        problems.append(f"resilience claimed {sorted(claimed)} vs measured {prof['resilience']}")
    if not verdicts.speed_agrees(prof["speed"], verdicts.claimed_speed(text)):
        problems.append(f"speed claimed {sorted(verdicts.claimed_speed(text))} vs measured {prof['speed']}")
    contra = verdicts.archetype_contradictions(text, a.insight.archetype)
    if contra:
        problems.append(f"labels the deck {contra} vs measured {a.insight.archetype!r}")
    topics = {t for t in (verdicts.strength_topic(s) for s in a.insight.strengths) if t}
    if topics and not any(verdicts.STRENGTH_TOPICS[t].search(text) for t in topics):
        problems.append(f"mentions none of the measured strengths {sorted(topics)}")
    if problems:
        return False, "; ".join(problems)
    return True, "verdict phrases agree with the profile" + (
        f"; touches strength topics {sorted(topics)}" if topics else "")


def _g_cards(reply, truth):
    key_names = [n for k in truth["analysis"].insight.key_cards for n in k.names]
    if not key_names:
        return None, "insight.key_cards is empty for this deck"
    hit = names_in(reply.text, key_names)
    if hit:
        return True, f"names key card(s): {', '.join(hit[:3])}"
    return False, f"names none of insight.key_cards ({', '.join(key_names[:4])}...)"


def _g_faster(reply, truth):
    return _grade_swap_answer(reply, truth, "speed", "speed")


def _g_weakest(reply, truth):
    passed, reason = _grade_swap_answer(reply, truth, None, "weakest")
    foreign = _foreign_card_names(reply, truth)
    if foreign:
        return False, f"names card(s) not in the deck or any tool result: {foreign[:3]}; " + reason
    return passed, reason


def _g_resilience(reply, truth):
    res = truth["analysis"].resilience
    if res is None:
        return None, "resilience not measured"
    band = verdicts.resilience_band(res.resilience_score)
    claimed = verdicts.claimed_resilience(reply.text)
    if not claimed:
        return False, f"states no resilience verdict (measured {res.resilience_score:.0f}/100 = {band})"
    if claimed != {band}:
        return False, f"claims {sorted(claimed)} vs measured {res.resilience_score:.0f}/100 = {band}"
    return True, f"verdict {band} matches {res.resilience_score:.0f}/100"


_UNMEASURED_COMBO_RE = re.compile(
    r"\b(?:win(?:s|ning)?\s+(?:via|with|through|by)\s+(?:a\s+|an\s+)?(?:infinite\s+)?combos?|"
    r"infinite\s+combos?|combo\s+(?:finish|win|kill)s?|(?:two|2)[\s-]card\s+combos?)\b",
    re.IGNORECASE,
)


def _g_wincon(reply, truth):
    a = truth["analysis"]
    text = reply.text
    problems = []
    contra = verdicts.archetype_contradictions(text, a.insight.archetype)
    if contra:
        problems.append(f"labels the deck {contra} vs measured {a.insight.archetype!r}")
    if not verdicts.states_archetype_or_route(text, a.insight.archetype) and not contra:
        problems.append(f"states neither a matching archetype label nor a win route "
                        f"(measured {a.insight.archetype!r})")
    finisher_supply = (truth["stats"].get("roles", {}).get("finisher") or {}).get("supply", 0) or 0
    if finisher_supply == 0:
        for sentence in verdicts.split_sentences(text):
            for m in re.finditer(r"\bfinishers?\b", sentence, re.IGNORECASE):
                if not _NEG_BEFORE_RE.search(sentence[:m.start()]):
                    problems.append("names 'finishers' as a win route though finisher supply is 0")
                    break
            else:
                continue
            break
    if a.insight.archetype != "Combo":
        for sentence in verdicts.split_sentences(text):
            m = _UNMEASURED_COMBO_RE.search(sentence)
            if m and not _NEG_BEFORE_RE.search(sentence[:m.start()]):
                problems.append(f"claims a combo win ({m.group(0)!r}) for a non-combo deck")
                break
    if problems:
        return False, "; ".join(problems)
    return True, f"win route consistent with {a.insight.archetype!r}"


def _g_vs_b3(reply, truth):
    if reply.gated and not reply.gate_rejections:
        return True, "gated on the first attempt"
    if not reply.gated:
        reasons = [r for _d, rs in reply.gate_rejections for r in rs]
        return False, "gate fell back: " + "; ".join(reasons[:2])
    reasons = [r for _d, rs in reply.gate_rejections for r in rs]
    return False, "needed a regeneration -- first draft rejected: " + "; ".join(reasons[:2])


# -- removal (Phase B2-wiring): every "can't answer X" claim must be backed by removal_coverage.
#
# A claim = a clause with a deficit cue ("can't answer", "struggles against", "no answer for",
# "weak to", "vulnerable to", "lacks ways to deal with") that names a permanent type or a
# qualifier. Backing, from the tool's own data:
#   - a bare type (creature/artifact/enchantment/planeswalker/land/spell) is backed when it is in
#     `no_answer_for` / `no_unrestricted_answer_for`, or (land/spell, which those lists do not
#     cover) when `answers_by_type` / `unrestricted_answers_by_type` for it is empty;
#   - a qualifier ("flyers", "tokens", "black creatures", "big creatures") is backed when some
#     card's quoted restriction names it. When a qualifier is present the type word is just its
#     noun, not a second claim ("can't answer big creatures" is about "big", not "creatures");
#   - a qualifier the tool cannot speak to (hexproof, indestructible, ...) is never backed.
# Bias: UNDER-flag -- a clause with a cue but no recognised target is ignored.

_REMOVAL_TYPE_WORDS = {
    "creature": "creature", "creatures": "creature",
    "artifact": "artifact", "artifacts": "artifact",
    "enchantment": "enchantment", "enchantments": "enchantment",
    "planeswalker": "planeswalker", "planeswalkers": "planeswalker",
    "land": "land", "lands": "land",
    "spell": "spell", "spells": "spell", "counterspell": "spell", "counterspells": "spell",
}
_TYPE_WORD_RE = re.compile(r"\b(" + "|".join(sorted(_REMOVAL_TYPE_WORDS, key=len, reverse=True)) + r")\b",
                           re.IGNORECASE)
# qualifier -> (recognising regex on the clause, regex a card restriction must match to back it)
_QUALIFIERS = {
    "flying": (re.compile(r"\b(?:fl(?:y|ies|yers?|iers?|ying))\b", re.I), re.compile(r"flying")),
    "token": (re.compile(r"\btokens?\b", re.I), re.compile(r"token")),
    "colour": (re.compile(r"\b(?:white|blue|black|red|green|colou?rless|multicolou?red|monocolou?red)\b", re.I),
               re.compile(r"\b(?:white|blue|black|red|green|colou?rless|multicolou?red|monocolou?red|"
                          r"non(?:white|blue|black|red|green))\b")),
    "size": (re.compile(r"\b(?:big|large|huge|massive|high[- ](?:power|toughness)|high\s+mana\s+value|"
                        r"expensive|powerful)\b", re.I),
             re.compile(r"power|toughness|mana value|damage|-\d|-x")),
    "legendary": (re.compile(r"\blegendary\b", re.I), re.compile(r"legendary")),
    "attacking": (re.compile(r"\b(?:attacking|blocking|untapped)\b", re.I), re.compile(r"attacking|blocking|tapped")),
    # no quoted restriction can ever back these: the tool knows nothing about them
    "protection": (re.compile(r"\b(?:hexproof|shroud|ward|indestructible|protection|regenerat\w*|"
                              r"recursion|reanimat\w*|graveyard|lifelink|trample)\b", re.I), None),
}
_CUE_RE = re.compile(
    r"\b(?:can'?t|cannot|can\s+not|unable\s+to|couldn'?t|struggl\w+|no\s+(?:real\s+|good\s+|clean\s+)?"
    r"(?:answers?|ways?|outs?|removal)|lacks?|lacking|weak(?:ness(?:es)?)?\s+(?:to|against|vs)|"
    r"vulnerab\w+\s+(?:to|against)|trouble|difficult\w*|gaps?|doesn'?t\s+(?:handle|answer|deal|cover|hit)|"
    r"not\s+(?:able|great|good)\s+(?:at|against|with|to))\b",
    re.IGNORECASE,
)
_CLAUSE_SPLIT_RE = re.compile(r"\s+(?:but|while|although|though|whereas|however)\s+|;|,\s+and\s+(?=\w+\s+(?:can|could|does))", re.I)
_RESTRICTION_MENTION_RE = re.compile(
    r"\b(?:restrict\w*|limited|limits?|conditional|narrow\w*|situational|only\s+(?:hit|hits|answer|answers|"
    r"work|works|kill|kills|deal|deals|handle|handles|target|targets|affect|affects)|"
    r"certain\s+(?:types|kinds|creatures|permanents)|specific\s+(?:types|kinds|creatures))\b",
    re.IGNORECASE,
)


def _removal_truth(truth) -> dict:
    cov = truth.get("removal")
    if cov is None:
        from mythgauntlet.mentor import removal as removal_mod
        cov = removal_mod.coverage(truth["ctx"].resolved)
    return cov


def _g_removal(reply, truth):
    cov = _removal_truth(truth)
    called = [t for t in reply.tool_trace if t.name == "removal_coverage"
              and isinstance(t.result_data, dict) and t.result_data.get("found")]
    if not called:
        return False, "never called removal_coverage"
    none_at_all = set(cov["no_answer_for"])
    none_unrestricted = set(cov["no_unrestricted_answer_for"])
    restriction_text = " ".join(r.lower() for row in cov["cards"] for r in row["restrictions"])
    by_type = cov["answers_by_type"]
    unr_by_type = cov["unrestricted_answers_by_type"]

    def type_backed(typ: str) -> bool:
        if typ in none_at_all or typ in none_unrestricted:
            return True
        return typ in ("land", "spell") and (not by_type.get(typ) or not unr_by_type.get(typ))

    problems: list[str] = []
    claims = 0
    for sentence in verdicts.split_sentences(reply.text):
        for clause in _CLAUSE_SPLIT_RE.split(sentence):
            cue = _CUE_RE.search(clause)
            if not cue:
                continue
            # a cue that is itself negated ("no gaps", "not a gap") is praise, not a claim
            if re.search(r"\b(?:no|not\s+a|without\s+any|few)\s+(?:real\s+)?gaps?\b", clause, re.I):
                continue
            quals = [(name, rx_back) for name, (rx_find, rx_back) in _QUALIFIERS.items()
                     if rx_find.search(clause)]
            if quals:
                for name, rx_back in quals:
                    claims += 1
                    if rx_back is None or not rx_back.search(restriction_text):
                        problems.append(f"claims a gap for {name!r} with no backing restriction: "
                                        f"{clause.strip()[:90]!r}")
                continue
            types = {_REMOVAL_TYPE_WORDS[m.group(1).lower()] for m in _TYPE_WORD_RE.finditer(clause)}
            for typ in sorted(types):
                claims += 1
                if not type_backed(typ):
                    problems.append(f"claims it can't answer {typ} but the tool shows unrestricted "
                                    f"answers ({', '.join(unr_by_type.get(typ, [])[:2]) or 'restricted ones'}): "
                                    f"{clause.strip()[:90]!r}")
    if problems:
        return False, "; ".join(problems[:3])
    if none_unrestricted:
        low = reply.text.lower()
        named_restriction = any(len(r) >= 6 and r.lower() in low
                                for row in cov["cards"] for r in row["restrictions"]
                                if ": " not in r)
        if not (_RESTRICTION_MENTION_RE.search(reply.text) or named_restriction):
            return False, (f"no_unrestricted_answer_for={sorted(none_unrestricted)} but the reply never "
                           "mentions restriction-limited coverage")
    return True, f"{claims} gap claim(s), all backed by removal_coverage"


GRADERS = {
    "overview": _g_overview, "cards": _g_cards, "faster": _g_faster,
    "resilience": _g_resilience, "wincon": _g_wincon, "weakest": _g_weakest,
    "vs_b3": _g_vs_b3, "removal": _g_removal,
}


def grade(qid: str, reply, truth: dict) -> tuple[bool | None, str]:
    fn = GRADERS.get(qid)
    if fn is None:
        return None, f"no rubric for {qid!r}"
    return fn(reply, truth)


# ── colour rubric ───────────────────────────────────────────────────────────────────

_COLOUR_WORD = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}
_COUNTER_RE = re.compile(r"\bcounter[\s-]?spells?\b|\bcounter\s+magic\b|\bcountering\s+spells\b", re.IGNORECASE)
_DEFICIT_RE = re.compile(
    r"\b(?:lack\w*|gap|missing|need\w*|more|add|include|consider|few|fewer|without|short|none|"
    r"under\w*|thin|run|play|no|zero|absence)\b",
    re.IGNORECASE,
)
_IDENTITY_ACK_RE = re.compile(
    r"(?:not\s+in\s+(?:your|the)\s+(?:deck'?s?\s+)?(?:colou?r|commander)|outside\s+(?:your|the)|"
    r"isn'?t\s+in\s+(?:your|the)|aren'?t\s+in\s+(?:your|the)|(?:doesn'?t|does\s+not|don'?t|do\s+not)\s+play\s+blue|"
    r"(?:no|without)\s+blue|blue\s+(?:isn'?t|is\s+not)|can'?t\s+(?:run|play|cast|add)|cannot\s+(?:run|play|cast|add)|"
    r"doesn'?t\s+need|don'?t\s+need|no\s+need|not\s+needed|not\s+a\s+(?:concern|gap|problem))",
    re.IGNORECASE,
)


def grade_colour(replies: list, truth: dict) -> tuple[bool | None, str]:
    identity = set(truth["identity"])
    outside = [c for c in "WUBRG" if c not in identity]
    problems: list[str] = []
    for i, reply in enumerate(replies):
        for sentence in verdicts.split_sentences(reply.text):
            if "U" not in identity and _COUNTER_RE.search(sentence):
                if _DEFICIT_RE.search(sentence) and not _IDENTITY_ACK_RE.search(sentence):
                    problems.append(f"reply {i}: counterspell advice without blue identity: {sentence.strip()[:90]!r}")
            for c in outside:
                word = _COLOUR_WORD[c]
                pat = re.compile(
                    r"\b(?:add|include|run|play|get|more|consider|pick\s+up)\b[^.]{0,30}\b" + word +
                    r"\b[^.]{0,20}\b(?:cards?|spells?|sources?|permanents?|creatures?|mana)\b",
                    re.IGNORECASE)
                m = pat.search(sentence)
                if m and not _NEG_BEFORE_RE.search(sentence[:m.start()]) and not _IDENTITY_ACK_RE.search(sentence):
                    problems.append(f"reply {i}: recommends {word} ({c} not in identity): {sentence.strip()[:90]!r}")
    if problems:
        return False, "; ".join(problems[:3])
    return True, f"no advice outside identity {''.join(sorted(identity)) or '(none)'}"
