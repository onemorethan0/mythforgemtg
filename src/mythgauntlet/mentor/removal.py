"""Interaction coverage for the Deck Mentor: WHAT can this deck's removal actually answer?

`coverage(resolved)` reads each interaction card's oracle text CLAUSE BY CLAUSE and gates on
the OBJECT noun, never the verb (the repeated lesson of `semantics/tags.py`: "destroy target"
swept Naturalize and Vandalblast into creature removal). Anything not confidently parsed is
reported as `mode: "unknown"` / empty `hits` -- an honest unknown beats a confident wrong answer.

Row shape (one per distinct interaction card, commanders included):

    {"name", "kind": spot|wipe|counter, "hits": [creature|artifact|enchantment|planeswalker|land|
     nonland_permanent|spell|any_permanent], "mode": destroy|exile|bounce|damage|minus|sacrifice|
     counter|unknown, "speed": instant|sorcery, "restrictions": [verbatim lowercase clause text]}

Aggregate: `answers_by_type` (creature/artifact/enchantment/planeswalker/land/spell -> names;
`nonland_permanent` and `any_permanent` count toward the four permanent types, `any_permanent`
also toward land; `spell` (counterspells) never answers a permanent type), `no_answer_for`
(of creature/artifact/enchantment/planeswalker), `unrestricted_answers_by_type` /
`no_unrestricted_answer_for` (below), `exile_count`, `instant_speed_count`, `cards`.

Unrestricted coverage (PLAN_MENTOR_ADHOC B2-wiring)
---------------------------------------------------
`answers_by_type` alone flatters a deck: Shelob's creature answers are mostly "with flying",
yet every one of them lands in `answers_by_type["creature"]`. `unrestricted_answers_by_type`
keeps, per type, only answers with NO restriction limiting WHICH permanents of that type they
can hit; `no_unrestricted_answer_for` lists the permanent types left empty (a superset of
`no_answer_for`: a type answered ONLY by restricted cards is in it too). The rule is
`restriction_limits_targets(text)` and it is a WHITELIST of non-limiting phrases -- anything
not recognised is limiting, so the failure direction is an under-count, never a flattering
over-count.

NOT limiting (the answer still reaches any permanent of the type):
- Who controls it: "an opponent controls", "you don't control", "your opponents control",
  "each opponent controls", "target opponent controls", "that player controls", "that
  opponent controls", "defending player controls". Removal is aimed at opposing permanents
  anyway, so this costs nothing in practice.
- Additional or alternative COSTS: "sacrifice ...", "pay ...", "discard ...", "exile a card
  from your graveyard", "overload {..}" / "cleave {..}". A cost taxes the caster; it does not
  shrink the target pool.
- Durability caveats: "until this <permanent> leaves the battlefield" and the Fiend Hunter
  "when this creature leaves the battlefield, return ..." clause. The answer is temporary, but
  it still reaches anything of the type. (The caveat stays visible in `restrictions`.)
- A caster-chosen X magnitude: "x damage", "get -x/-x" (a scalable sweep), and any literal
  damage / -N/-N of 10 or more ("13 damage", Blasphemous Act), which kills essentially every
  creature.
LIMITING (everything else), notably: evasion/state words ("with flying", "tapped",
"attacking"), "nonblack"/"nonartifact"/"nontoken"/colour words, "power 3 or less", "with mana
value ...", "noncreature", "unless its controller pays {N}" (a soft counter the opponent can
pay), "instant or sorcery", small fixed magnitudes ("3 damage", "get -2/-2": a 3-damage bolt is
not a Doom Blade), conditional upgrades ("if it was kicked"), and parser residue we cannot
interpret.
A hit-prefixed restriction ("creature: with flying") applies only to the hits named in its
prefix; an unprefixed restriction applies to every hit of the card. EDICTS (mode "sacrifice":
the opponent chooses what to lose) never count as unrestricted -- they cannot answer a
SPECIFIC permanent.

Selection
---------
A card gets a row when `tags.analyze` flags removal/board_wipe/counterspell OR this module
confidently parses at least one interaction clause. The second arm exists on purpose: tags is
creature-only by design (Naturalize is not "removal" there), but "what can't my removal answer"
needs the artifact/enchantment/land answers. The disagreements are listed in the task report.
A card tags flags that parses to nothing still gets a row, `mode: "unknown"`.

Conventions worth knowing
-------------------------
- `mode` is one mode when every parsed clause agrees, else `"unknown"` (Abrade: damage +
  destroy). `exile_count` is computed from the internal per-clause modes, so a mixed card that
  can exile still counts. Library tuck / shuffle (Chaos Warp, Condemn) is `"unknown"` mode with
  real hits: the enum has no tuck.
- `kind`: "counter" if every clause counters; else "spot" if any clause is single-target (or an
  edict); else "wipe". An overload card stays "spot" and carries `"overload {cost}"` as a
  restriction so the overloaded sweep is visible. (Cyclonic Rift, Vandalblast.)
- Restrictions on a MULTI-CLAUSE card whose clauses hit different things are prefixed with
  their own hits ("creature: with flying", "planeswalker: 3 damage" -- Thunderbolt) so a
  modal union never reads as if a restriction applied to every hit. Whole-card costs
  ("pay x life", "sacrifice a creature") are never prefixed. Damage/-N/-N magnitudes
  ("3 damage", "get -2/-2") are restrictions too: a 1-damage pinger is not a Doom Blade.
- Restrictions are verbatim substrings of the (lowercased, reminder-text-stripped) oracle text:
  `nonblack`, `power 3 or less`, `with mana value 3 or less`, `an opponent controls`,
  `you don't control`, `until this enchantment leaves the battlefield`, `unless its controller
  pays {3}`, and pre-noun modifiers (`attacking`, `artifact` in "artifact creature", ...).
- Skipped as NOT removal: clauses that only touch your own permanents ("you control"), flicker
  ("exile target creature you control, then return it"), anything naming a card / graveyard /
  attached-to object, and quoted (granted) abilities.
- Speed: instant type, Flash, or a non-loyalty activated ability on a permanent -> "instant";
  planeswalker loyalty abilities and "activate only as a sorcery" -> "sorcery" (rules: they are
  sorcery-speed, which the plan's blanket "activated ability" rule glosses over); ETB/triggered
  removal on a permanent is "sorcery".

Known limitations (also in the task report)
-------------------------------------------
- The card DB keeps ONLY the front face's oracle text and type line (Brazen Borrower's Petty
  Theft, Consign // Oblivion's second half, Wear // Tear's Tear are invisible to it). `"//"`
  separated text is handled if it ever appears, but today a multi-face card is read as face 1.
- Not modelled: control-stealing, fights, "-1/-1 counters", tap effects, Aura-based "enchanted
  creature gets -X/-X", subtype-only targets ("destroy target Dragon"), counter-target-ability
  (Stifle), "destroy target creature or ... with flying" where the OR binds loosely.

Gold set (verified against the live card DB 2026-09-30; pinned in
tests/engine/test_removal_coverage.py)
------------------------------------------------------------------------------------------
| card                  | kind    | hits                              | mode    | speed   | restrictions |
|-----------------------|---------|-----------------------------------|---------|---------|--------------|
| Swords to Plowshares  | spot    | creature                          | exile   | instant |              |
| Path to Exile         | spot    | creature                          | exile   | instant |              |
| Beast Within          | spot    | any_permanent                     | destroy | instant |              |
| Chaos Warp            | spot    | any_permanent                     | unknown | instant |              |
| Cyclonic Rift         | spot    | nonland_permanent                 | bounce  | instant | you don't control, overload {6}{u} |
| Damnation             | wipe    | creature                          | destroy | sorcery |              |
| Blasphemous Act       | wipe    | creature                          | damage  | sorcery | 13 damage    |
| Vandalblast           | spot    | artifact                          | destroy | sorcery | you don't control, overload {4}{r} |
| Naturalize            | spot    | artifact, enchantment             | destroy | instant |              |
| Counterspell          | counter | spell                             | counter | instant |              |
| Negate                | counter | spell                             | counter | instant | noncreature  |
| Pongify               | spot    | creature                          | destroy | instant |              |
| Doom Blade            | spot    | creature                          | destroy | instant | nonblack     |
| Culling Sun           | wipe    | creature                          | destroy | sorcery | with mana value 3 or less |
| Eaten by Spiders      | spot    | creature                          | destroy | instant | with flying  |
| Skyfisher Spider      | spot    | nonland_permanent                 | destroy | sorcery | sacrifice another creature |
| Assassin's Trophy     | spot    | any_permanent                     | destroy | instant | an opponent controls |
| Anguished Unmaking    | spot    | nonland_permanent                 | exile   | instant |              |
| Generous Gift         | spot    | any_permanent                     | destroy | instant |              |
| Toxic Deluge          | wipe    | creature                          | minus   | sorcery | get -x/-x, pay x life |
| Heroic Intervention   | (absent: protection, not removal)                                               |
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mythgauntlet.semantics import tags

_HIT_ORDER = (
    "creature", "artifact", "enchantment", "planeswalker", "land",
    "nonland_permanent", "spell", "any_permanent",
)
_PERMANENT_TYPES = ("creature", "artifact", "enchantment", "planeswalker")

_REMINDER_RE = re.compile(r"\([^)]*\)")
_QUOTED_RE = re.compile(r'"[^"]*"')

_TYPE_NOUNS = {
    "creature": "creature", "artifact": "artifact", "enchantment": "enchantment",
    "planeswalker": "planeswalker", "land": "land", "permanent": "permanent",
    "spell": "spell",
}
# subtype nouns that still name exactly one card type (the subtype stays as a restriction)
_SUBTYPE_NOUNS = {
    "aura": "enchantment", "equipment": "artifact", "vehicle": "artifact",
    "saga": "enchantment", "treasure": "artifact", "food": "artifact", "clue": "artifact",
    "spacecraft": "artifact",
}
_ADJECTIVES = {
    "white", "blue", "black", "red", "green", "colorless", "monocolored", "multicolored",
    "legendary", "attacking", "blocking", "tapped", "untapped", "basic", "nontoken", "token",
}
# alternatives that are not permanents we track ("target creature, planeswalker, or battle")
_PLAYER_WORDS = {"player", "opponent", "you", "yourself", "players", "opponents", "battle", "battles"}
_STOPWORDS = {"a", "an", "the", "each", "all", "target", "any", "targets"}

_OWN_PHRASES = ("you control", "you own or control", "you own")
_CONTROL_PHRASES = (
    "you don't control", "an opponent controls", "your opponents control",
    "each opponent controls", "target opponent controls", "that player controls",
    "defending player controls", "you own or control", "you control", "you own",
)
# a control phrase inside one of these expressions is part of a count, not a restriction
# ("mana value less than or equal to the number of Plains you control", Lay Down Arms)
_COUNT_EXPR_RE = re.compile(r"number of|equal to|among|less than|or less|or greater|or more")
_CONTROL_RE = re.compile("|".join(re.escape(p) for p in _CONTROL_PHRASES))

_LEAD_RE = re.compile(
    r"^(?:(?:up to|exactly)\s+\w+\s+|any number of\s+|one or two\s+|one, two, or three\s+"
    r"|(?:one|two|three|four|x|\d+)\s+)?(?:(?:another|other)\s+)?"
    r"(any target|targets?|each|all)\b\s*"
)
# Where the object phrase ends (continuation of the sentence about something else).
_STOP_RE = re.compile(
    r"(?:,\s*(?:then|and|where|except|if)\b|\s+and\s+(?:all|its|it|that|you|each|gains?|loses?"
    r"|exile|destroy|deals?|put|return|create|they|those)\b|\s+then\b|\s+except\b|\s+instead\b"
    r"|\s+and\s+\d+\s+damage)"
)
# Where the head noun phrase ends and trailing restrictions begin.
_TAILMARK_RE = re.compile(
    r"\s+(?:you don't control|you control|an opponent controls|your opponents control"
    r"|each opponent controls|target opponent controls|that player controls"
    r"|defending player controls|you own or control|you own|with|without|that|which|whose|of|named|in|on|from|attached|equal"
    r"|until|unless|if)\b"
)
_RESTRICT_START_RE = re.compile(
    r"(?:with|without|that|which|whose|until|unless|if|named|(?<!or )(?<!than )equal to)\b.*?"
    r"(?=\s+(?:with|without|that|which|whose|until|unless|if|named|(?<!or )(?<!than )equal to)\b|$)"
)

_ACTIVATED_RE = re.compile(r"^[^:]{1,160}:\s")
_LOYALTY_RE = re.compile(r"^(?:[+-]?\d+|\+?x|-x|0)\s*:")
_FLASH_RE = re.compile(r"^(?:[a-z]+(?: \d+)?,\s*)*flash(?:,|$)")
_REFLEXIVE_RE = re.compile(r"^(?:when|if) you do\b")
_OPTIONAL_COST_RE = re.compile(r"\byou may (sacrifice|discard|pay|exile|tap|return)\b[^.]*")
_FLICKER_RE = re.compile(
    r"\breturn (?:it|that card|that creature|them|those cards|the exiled cards?|that permanent)\b"
    r"[^.]*\bto the battlefield"
)
_CLAUSE_WORD_RE = re.compile(r"\b(?:with|without|that|which|whose|until|unless|if|named)\b")
_LEAVES_RETURN_RE = re.compile(
    r"when (?:this|it)[^,.]*leaves the battlefield, return the exiled cards?[^.]*"
)
_OVERLOAD_RE = re.compile(r"^(overload|cleave)\s+((?:\{[^}]+\})+)")

_STRENGTH = {"spot": 0, "wipe": 1, "counter": 2}


@dataclass
class _Clause:
    kind: str  # spot | wipe | counter
    mode: str
    hits: set[str]
    restrictions: list[str]
    para: str
    paragraph_no: int
    shared: list[str] = field(default_factory=list)  # whole-card costs, never bound to a hit


@dataclass
class _Obj:
    quant: str  # target | each | all | any
    hits: set[str] = field(default_factory=set)
    restrictions: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- text prep


def _prep(text: str) -> str:
    text = (text or "").replace("’", "'").replace("−", "-").replace("–", "-")
    text = _REMINDER_RE.sub("", text)
    text = _QUOTED_RE.sub("", text)
    text = text.replace("[", "").replace("]", "")
    return text.lower()


def _faces(card) -> list[tuple[str, str]]:
    """[(type_line, oracle_text)] per face. The card DB keeps only face 1 today."""
    texts = re.split(r"\n?\s*//\s*\n?", card.oracle_text or "")
    types = (card.type_line or "").split(" // ")
    out = []
    for i, t in enumerate(texts):
        out.append((types[i] if i < len(types) else types[0], t))
    return out


def _sentences(paragraph: str) -> list[str]:
    paragraph = re.sub(r"^[•\s]+", "", paragraph)
    parts = re.split(r"\.\s+|\.$|;\s*", paragraph)
    return [p.strip() for p in parts if p.strip()]


def _singular(tok: str) -> str:
    if tok.endswith("s") and tok[:-1] in {*_TYPE_NOUNS, *_SUBTYPE_NOUNS}:
        return tok[:-1]
    if tok == "equipment":
        return tok
    return tok


# --------------------------------------------------------------------------- object parsing


def _parse_head(head: str) -> tuple[set[str], list[str], str, int] | None:
    """Noun phrase -> (hits, restrictions, last alternative text, alternative count).

    None when any alternative is unparseable."""
    head = head.strip().replace("attacking or blocking", "attacking/blocking")
    head = head.replace(" and/or ", " or ")
    alts = [a for a in re.split(r",\s*(?:or |and )?|\s+(?:or|and)\s+", head) if a.strip()]
    hits: set[str] = set()
    restrictions: list[str] = []
    parsed_any = False
    last_alt = ""
    n_alts = 0
    pending: list[str] = []
    for alt in alts:
        alt = re.sub(r"^(?:up to|exactly)\s+\w+\s+|^(?:another|other)\s+", "", alt.strip())
        toks = [t for t in alt.split() if t not in _STOPWORDS]
        if not toks:
            continue
        idx = None
        for i in range(len(toks) - 1, -1, -1):
            if _singular(toks[i]) in _TYPE_NOUNS or _singular(toks[i]) in _SUBTYPE_NOUNS:
                idx = i
                break
        if idx is None:
            if set(toks) <= _PLAYER_WORDS:
                continue  # "each player" / "each opponent" -- not a permanent, ignore
            if all(t in _ADJECTIVES or t.startswith("non") for t in toks):
                # "nonartifact, nonblack creature": a comma-separated modifier list that
                # belongs to the noun after it
                pending.extend(toks)
                continue
            return None
        noun = _singular(toks[idx])
        pre, post = pending + toks[:idx], toks[idx + 1:]
        pending = []
        if noun in _SUBTYPE_NOUNS:
            hits.add(_SUBTYPE_NOUNS[noun])
            restrictions.append(noun)
        elif noun == "permanent":
            if "nonland" in pre:
                hits.add("nonland_permanent")
                pre = [t for t in pre if t != "nonland"]
            elif "noncreature" in pre:
                hits.update({"artifact", "enchantment", "planeswalker", "land"})
                pre = [t for t in pre if t != "noncreature"]
            else:
                hits.add("any_permanent")
        else:
            hits.add(noun)
        restrictions.extend(pre)
        restrictions.extend(post)
        parsed_any = True
        last_alt = alt.strip()
        n_alts += 1
    if pending or (not parsed_any and not hits):
        return None
    return hits, restrictions, last_alt, n_alts


def _tail_restrictions(tail: str, bind_to: str = "") -> list[str]:
    out: list[str] = []
    tail = tail.strip()
    if not tail:
        return out
    m = _CONTROL_RE.search(tail)
    if (
        m
        and not _COUNT_EXPR_RE.search(tail[:m.start()])
        # "you control" INSIDE a with/that clause belongs to that clause (Soul Snare: "that's
        # attacking you or a planeswalker you control"), not to the target.
        and not (m.group(0) in _OWN_PHRASES and _CLAUSE_WORD_RE.search(tail[:m.start()]))
    ):
        out.append(m.group(0))
        tail = (tail[:m.start()] + " " + tail[m.end():]).strip()
    for r in _RESTRICT_START_RE.finditer(tail):
        piece = r.group(0).strip()
        if piece:
            # "artifact, enchantment, or creature with flying": English binds the modifier
            # to the LAST alternative (Spider Food) -- say so instead of restricting all of them.
            out.append(f"{bind_to} {piece}" if bind_to else piece)
    return out


_OWN = _Obj("own")  # sentinel: the clause only touches the caster's own permanents


def _parse_object(phrase: str, *, noun_lead: bool = False) -> _Obj | None:
    """Parse "<lead> <head> <tail>" (lead = target/each/all/any target, or an article when
    `noun_lead`, used for sacrifice objects). None = not confidently a battlefield object."""
    phrase = phrase.strip()
    if noun_lead:
        m = re.match(
            r"^(?:(?:a|an|one|two|three|four|x|\d+|that many|all|half(?: of)?(?: the)?)\s+)", phrase
        )
        quant = "all" if m and m.group(0).strip().startswith(("all", "half")) else "target"
        rest = re.sub(r"\b(?:they|it) controls?\b", "", phrase[m.end():] if m else phrase)
    else:
        m = _LEAD_RE.match(phrase)
        if not m:
            return None
        lead = m.group(1)
        quant = {"each": "each", "all": "all", "any target": "any"}.get(lead, "target")
        rest = phrase[m.end():]
    stop = _STOP_RE.search(" " + rest)
    if stop:
        rest = (" " + rest)[:stop.start()]
    rest = rest.strip()
    if "graveyard" in rest or "attached to" in rest or " library" in rest or "hand" in rest.split():
        return None
    if (quant == "any" or lead_is_bare_targets(phrase)) and (
        not rest or _RESTRICT_START_RE.match(rest)
    ):
        return _Obj("any", {"creature", "planeswalker"}, _tail_restrictions(rest))
    mark = _TAILMARK_RE.search(rest)
    head, tail = (rest[:mark.start()], rest[mark.start():]) if mark else (rest, "")
    if re.search(r"\bcards?\b", head):
        return None
    parsed = _parse_head(head)
    if parsed is None:
        return None
    hits, restrictions, last_alt, n_alts = parsed
    if "attached" in tail:
        return None
    tail_r = _tail_restrictions(tail, last_alt if n_alts > 1 else "")
    # own-permanents-only is not removal
    if any(r in _OWN_PHRASES for r in tail_r):
        return _OWN
    restrictions = restrictions + tail_r
    return _Obj(quant, hits, _dedup(restrictions))


def lead_is_bare_targets(phrase: str) -> bool:
    return bool(re.match(r"^(?:one or two|one, two, or three|up to \w+)\s+targets\b", phrase))


def _dedup(items: list[str]) -> list[str]:
    seen: list[str] = []
    for i in items:
        if i and i not in seen:
            seen.append(i)
    return seen


# --------------------------------------------------------------------------- clause extraction

# lookahead so a second verb in the same sentence ("Exile this creature: Exile target
# creature", Hanged Executioner) is not swallowed by the first match
_DESTROY_EXILE_RE = re.compile(r"\b(destroy|exile)\s+(?=(.+))")
_DAMAGE_RE = re.compile(
    r"\bdamage\b(?:\s+equal to [^.;]*?)?\s+to\s+(.+)"
    r"|\bdamage divided as you choose\s+among\s+(.+)"
)
_MINUS_RE = re.compile(
    r"\b((?:(?:up to \w+ |any number of |(?:one|two|three|x|\d+) )?(?:other |another )?"
    r"(?:target|all|each)\b|creatures\b)[^.;]*?)\s+gets?\s+[+-]?[\dx]+/-([\dx]+)"
)
_BOUNCE_RE = re.compile(r"\breturn\s+(.+?)\s+to\s+(?:its|their)\s+owners?'?s?\s+hands?\b")
_TUCK_RE = re.compile(
    r"\bput\s+(.+?)\s+(?:on top of|on the top of|on the bottom of|into)\s+"
    r"(?:its|their|that player's)\s+owners?'?s?\s+librar(?:y|ies)"
)
_SHUFFLE_RE = re.compile(
    r"\b(?:the owner of\s+)?(.+?)\s+shuffles?\s+(?:it|them)\s+into\s+(?:their|its owner's)\s+library"
)
_EDICT_RE = re.compile(
    r"\b(target player|target opponent|each opponent|each other player|each player"
    r"|that player|defending player)\s+sacrifices\s+(.+)"
)
_COUNTER_RE = re.compile(r"\bcounter\s+(?:up to \w+\s+)?(?:target\s+)(.*?)\bspells?\b(.*)")


_DAMAGE_AMOUNT_RE = re.compile(r"\b(\d+ damage|damage equal to [^.;]*?)(?=\s+(?:divided as you choose\s+)?(?:to|among)\b)")


def _wrap(quant: str, mode: str, obj: _Obj, para: str, pno: int, extra=()) -> _Clause:
    kind = "wipe" if quant in ("each", "all") else "spot"
    return _Clause(kind, mode, set(obj.hits), _dedup(list(obj.restrictions) + list(extra)), para, pno)


def _clauses_in_sentence(s: str, para: str, pno: int) -> tuple[list[_Clause], bool]:
    """-> (clauses, rejected_as_own): the flag is True when a destroy/exile/damage/bounce/minus
    clause was seen and rejected because it only touches the caster's own permanents (or
    flickers them) -- i.e. confidently NOT removal, as opposed to merely unparsed."""
    out: list[_Clause] = []
    own = False

    for m in _DESTROY_EXILE_RE.finditer(s):
        verb = m.group(1)
        if s[max(0, m.start() - 6):m.start()].endswith(("can't ", "not ")):
            continue
        obj = _parse_object(m.group(2))
        if obj is None:
            continue
        extra: list[str] = []
        if obj is _OWN:
            own = True
            continue
        if verb == "exile":
            returns = [x for x in _sentences(para) if _FLICKER_RE.search(x)]
            if returns:
                # An UNCONDITIONAL return is a flicker/tempo play, not removal. A conditional
                # one (Parting Gust: "if the gift wasn't promised, return ...") is removal on
                # the other branch -- keep it and say what the catch is, verbatim.
                cond = [x for x in returns if re.search(r"\b(?:if|unless)\b", x)]
                if not cond:
                    own = True
                    continue
                extra.append(cond[0])
        out.append(_wrap(obj.quant, verb, obj, para, pno, extra))

    m = _DAMAGE_RE.search(s)
    if m:
        obj = _parse_object(m.group(1) or m.group(2))
        if obj is _OWN:
            own = True
        elif obj is not None:
            am = _DAMAGE_AMOUNT_RE.search(s)
            out.append(_wrap(obj.quant, "damage", obj, para, pno, [am.group(1)] if am else []))

    m = _MINUS_RE.search(s)
    if m and m.group(2) not in ("0",):
        subj = m.group(1)
        if subj.startswith("creatures"):
            subj = "all " + subj
        obj = _parse_object(subj)
        if obj is _OWN:
            own = True
        elif obj is not None:
            pt = re.search(r"gets?\s+([+-]?[\dx]+/-[\dx]+)", s)
            out.append(_wrap(obj.quant, "minus", obj, para, pno,
                             [f"get {pt.group(1)}"] if pt else []))

    for m in _BOUNCE_RE.finditer(s):
        obj = _parse_object(m.group(1))
        if obj is _OWN:
            own = True
        elif obj is not None:
            out.append(_wrap(obj.quant, "bounce", obj, para, pno))

    for rx in (_TUCK_RE, _SHUFFLE_RE):
        m = rx.search(s)
        if m:
            obj = _parse_object(m.group(1))
            if obj is not None and obj is not _OWN and "card" not in m.group(1):
                out.append(_wrap(obj.quant, "unknown", obj, para, pno))

    m = _EDICT_RE.search(s)
    if m:
        obj = _parse_object(m.group(2), noun_lead=True)
        if obj is not None and obj is not _OWN:
            extra = ["each player"] if m.group(1) == "each player" else []
            if m.group(2).startswith("half"):
                extra.append("half")
                obj.quant = "target"  # one targeted player loses half; not a board sweep
            c = _wrap(obj.quant, "sacrifice", obj, para, pno, extra)
            out.append(c)

    m = _COUNTER_RE.search(s)
    if m and "ability" not in m.group(1):
        restr: list[str] = []
        pre = m.group(1).strip()
        if pre:
            restr.append(pre)
        tail = m.group(2).split(",")[0].strip()
        restr.extend(_tail_restrictions(tail))
        out.append(_Clause("counter", "counter", {"spell"}, _dedup(restr), para, pno))

    return out, own


def _speed_of(face_type: str, has_flash: bool, clause: _Clause) -> str:
    t = face_type.lower()
    if "instant" in t or has_flash:
        return "instant"
    if "planeswalker" in t:
        return "sorcery"
    para = clause.para
    if (
        _ACTIVATED_RE.match(para)
        and not para.startswith(("when ", "whenever ", "at the beginning"))
        and not _LOYALTY_RE.match(para)
        and "activate only as a sorcery" not in para
    ):
        return "instant"
    return "sorcery"


def _analyze_face(face_type: str, text: str) -> tuple[list[_Clause], list[str], list[str], bool]:
    """-> (clauses, per-clause speeds, overload restrictions, rejected_as_own)."""
    prepped = _prep(text)
    paras = [p.strip() for p in prepped.split("\n") if p.strip()]
    has_flash = any(_FLASH_RE.match(p) for p in paras)
    costs = []
    for p in paras:
        cm = re.match(r"as an additional cost to cast this (?:spell|card), (.+?)\.?$", p)
        if cm:
            costs.append(cm.group(1).strip())
    leaves_m = _LEAVES_RETURN_RE.search(prepped)
    leaves_return = leaves_m.group(0).strip() if leaves_m else ""
    clauses: list[_Clause] = []
    speeds: list[str] = []
    overload: list[str] = []
    own = False
    for pno, para in enumerate(paras):
        om = _OVERLOAD_RE.match(para)
        if om:
            overload.append(f"{om.group(1)} {om.group(2)}")
        sentences = _sentences(para)
        for si, s in enumerate(sentences):
            found, was_own = _clauses_in_sentence(s, para, pno)
            own = own or was_own
            if found and _REFLEXIVE_RE.match(s) and si > 0:
                gate = _OPTIONAL_COST_RE.search(sentences[si - 1])
                if gate:
                    for c in found:
                        c.restrictions = _dedup(c.restrictions + [gate.group(0).replace("you may ", "")])
            # a condition on the removal itself: "if it was kicked, destroy target artifact"
            lead_if = re.search(r"(?:^|,\s+)(if [^,]+),\s", s)
            if found and lead_if and not _REFLEXIVE_RE.match(lead_if.group(1)):
                for c in found:
                    c.restrictions = _dedup(c.restrictions + [lead_if.group(1)])
            for c in found:
                c.shared = list(costs)
                if c.mode == "exile" and leaves_return:
                    # Journey to Nowhere / Oblivion Ring: the exile ends when the source leaves
                    c.restrictions = _dedup(c.restrictions + [leaves_return])
                clauses.append(c)
                speeds.append(_speed_of(face_type, has_flash, c))
    return clauses, speeds, overload, own


def _tag_flags(card) -> tuple[bool, bool, bool]:
    fx = tags.analyze(card)
    return bool(fx.removal), bool(fx.board_wipe), bool(fx.counterspell)


def _row_for(card) -> tuple[dict, set[str]] | None:
    """(row, internal per-clause modes) or None when the card is not interaction."""
    clauses: list[_Clause] = []
    speeds: list[str] = []
    overload: list[str] = []
    own = False
    for ftype, ftext in _faces(card):
        c, s, o, w = _analyze_face(ftype, ftext)
        clauses += c
        speeds += s
        overload += o
        own = own or w
    rm, wipe, ctr = _tag_flags(card)
    if not clauses and not (rm or wipe or ctr):
        return None
    if not clauses and own:
        return None  # flicker / own-permanent effects (Ephemerate): tags false positive

    if not clauses:
        t = (card.type_line or "").lower()
        paras = [p for p in _prep(card.oracle_text).split("\n") if p.strip()]
        instant = "instant" in t or any(_FLASH_RE.match(p.strip()) for p in paras)
        kind = "spot" if rm else "wipe" if wipe else "counter"
        return (
            {"name": card.name, "kind": kind, "hits": [], "mode": "unknown",
             "speed": "instant" if instant else "sorcery", "restrictions": []},
            set(),
        )

    hits: set[str] = set()
    restrictions: list[str] = []
    modes: set[str] = set()
    kinds: set[str] = set()
    # A multi-clause card whose clauses hit DIFFERENT things (Thunderbolt: 3 damage to a
    # planeswalker / 4 damage to a creature with flying) would otherwise present "with
    # flying" as if it restricted every hit. Bind each clause's restrictions to its own hits.
    bind = len({frozenset(c.hits) for c in clauses}) > 1
    for c in clauses:
        hits |= c.hits
        if bind:
            label = "/".join(h for h in _HIT_ORDER if h in c.hits)
            restrictions += [f"{label}: {r}" for r in c.restrictions]
        else:
            restrictions += c.restrictions
        restrictions += c.shared
        modes.add(c.mode)
        kinds.add(c.kind)
    if kinds == {"counter"} or hits == {"spell"}:
        kind = "counter"
    elif "spot" in kinds:
        kind = "spot"
    else:
        kind = "wipe"
    mode = next(iter(modes)) if len(modes) == 1 else "unknown"
    # Restrictions that belong to only SOME modes are still listed (verbatim, deduped);
    # the mentor reads them alongside `hits`.
    restrictions = _dedup(restrictions + overload)
    speed = "instant" if "instant" in speeds else "sorcery"
    row = {
        "name": card.name,
        "kind": kind,
        "hits": [h for h in _HIT_ORDER if h in hits],
        "mode": mode,
        "speed": speed,
        "restrictions": restrictions,
    }
    return row, modes


# --------------------------------------------------------------------------- public API


_CONTROL_NON_LIMITING = {
    "an opponent controls", "you don't control", "your opponents control",
    "each opponent controls", "target opponent controls", "that player controls",
    "that opponent controls", "defending player controls",
}
_NON_LIMITING_RES = tuple(re.compile(p) for p in (
    r"^sacrifice\b", r"^pay\b", r"^discard\b", r"^exile an? .+ from your graveyard$",
    r"^(?:overload|cleave)\b",
    r"^until this [a-z]+ leaves the battlefield$",
    r"^when this [a-z]+ leaves the battlefield, return\b",
    r"^x damage$", r"^gets? -x/-x$",
))
_MAGNITUDE_RE = re.compile(r"^(?:(\d+) damage|gets? -(\d+)/-(\d+))$")
_SWEEP_MAGNITUDE = 10  # damage / -N/-N at least this large kills essentially every creature
_PREFIX_RE = re.compile(r"^([a-z_]+(?:/[a-z_]+)*): (.*)$")


def restriction_limits_targets(text: str) -> bool:
    """True when `text` (one `restrictions` entry, prefix already removed) limits WHICH
    permanents of a type the card can answer. A whitelist of non-limiting phrases; anything
    unrecognised is limiting (an honest under-count). See the module docstring."""
    t = (text or "").strip().lower()
    if t in _CONTROL_NON_LIMITING:
        return False
    if any(rx.match(t) for rx in _NON_LIMITING_RES):
        return False
    m = _MAGNITUDE_RE.match(t)
    if m:
        nums = [int(g) for g in m.groups() if g is not None]
        return not (nums and min(nums) >= _SWEEP_MAGNITUDE)
    return True


def _split_prefix(restriction: str) -> tuple[set[str] | None, str]:
    m = _PREFIX_RE.match(restriction)
    if m and all(p in _HIT_ORDER for p in m.group(1).split("/")):
        return set(m.group(1).split("/")), m.group(2)
    return None, restriction


def _covers(label_hits: set[str], typ: str) -> bool:
    if typ in label_hits:
        return True
    if typ in _PERMANENT_TYPES and ({"nonland_permanent", "any_permanent"} & label_hits):
        return True
    return typ == "land" and "any_permanent" in label_hits


def _unrestricted_types(row: dict, modes: set[str]) -> set[str]:
    """The answer types (keys of `answers_by_type`) this row answers with no limiting
    restriction that applies to that type. Edicts answer nothing specific."""
    if "sacrifice" in modes:
        return set()
    types: set[str] = set()
    for h in row["hits"]:
        if h in ("nonland_permanent", "any_permanent"):
            types.update(_PERMANENT_TYPES)
            if h == "any_permanent":
                types.add("land")
        elif h in _ANSWER_TYPES:
            types.add(h)
    out = set()
    for typ in types:
        limited = False
        for r in row["restrictions"]:
            labels, body = _split_prefix(r)
            if labels is not None and not _covers(labels, typ):
                continue
            if restriction_limits_targets(body):
                limited = True
                break
        if not limited:
            out.add(typ)
    return out


_ANSWER_TYPES = ("creature", "artifact", "enchantment", "planeswalker", "land", "spell")


def coverage_for_cards(cards) -> dict:
    """Same as `coverage` for an iterable of Card objects (commanders first, duplicates ok)."""
    rows: list[dict] = []
    all_modes: dict[str, set[str]] = {}
    seen: set[str] = set()
    for card in cards:
        if card.name in seen:
            continue
        seen.add(card.name)
        res = _row_for(card)
        if res is None:
            continue
        rows.append(res[0])
        all_modes[card.name] = res[1]

    answers: dict[str, list[str]] = {
        "creature": [], "artifact": [], "enchantment": [], "planeswalker": [],
        "land": [], "spell": [],
    }

    def add(typ: str, name: str) -> None:
        if name not in answers[typ]:
            answers[typ].append(name)

    unrestricted: dict[str, list[str]] = {t: [] for t in answers}
    for r in rows:
        for typ in _ANSWER_TYPES:
            if typ in _unrestricted_types(r, all_modes[r["name"]]) and r["name"] not in unrestricted[typ]:
                unrestricted[typ].append(r["name"])
    for r in rows:
        for h in r["hits"]:
            if h in ("nonland_permanent", "any_permanent"):
                for t in _PERMANENT_TYPES:
                    add(t, r["name"])
                if h == "any_permanent":
                    add("land", r["name"])
            elif h in answers:
                add(h, r["name"])
    return {
        "answers_by_type": answers,
        "no_answer_for": [t for t in _PERMANENT_TYPES if not answers[t]],
        "unrestricted_answers_by_type": unrestricted,
        "no_unrestricted_answer_for": [t for t in _PERMANENT_TYPES if not unrestricted[t]],
        "exile_count": sum(1 for r in rows if "exile" in all_modes[r["name"]]),
        "instant_speed_count": sum(1 for r in rows if r["speed"] == "instant"),
        "cards": rows,
    }


def coverage(resolved) -> dict:
    """Interaction coverage of a ResolvedDeck (commanders included)."""
    cards = list(resolved.commanders) + [c for c, _ in resolved.cards]
    return coverage_for_cards(cards)
