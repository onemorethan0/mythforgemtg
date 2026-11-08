"""What a tutor can actually fetch, read from its own search text (B33).

The combo clock (ratings/combo_clock.py) counts a tutor as an extra out for a missing combo
piece. That is only true when the tutor's search names an object the piece IS: Mystical Tutor
cannot find Thassa's Oracle, Stoneforge Mystic finds only Equipment, Imperial Recruiter only a
creature with power 2 or less. So the OBJECT is gated, the COST is subtracted, and where the
card goes decides when it can be used:

- object: "a card", "an instant or sorcery card", "a green creature card", "a Goblin permanent
  card", "a noncreature, nonland card", with a postfix the parser understands ("with mana value
  3", "with mana value X or less", "with power 2 or less", "named ..."). Any word or postfix it
  does not understand makes the card NOT a counted tutor: an honest under-count, never a guess.
- destination: the most conservative one named after the search on its line (on top <
  into your hand < onto the battlefield). Archdruid's Charm puts a creature into the hand and
  only a land onto the battlefield; reading the first destination would give it the better one.
- timing: a spell or a cast/enters trigger tutors the turn it is cast; a planeswalker loyalty
  ability the turn it lands (if the cost is reachable, `tags._reachable_text`); an activated
  ability from the turn AFTER the permanent lands (conservative: it covers summoning sickness
  for {T} creatures and the second payment). Any other trigger (exploit, dies, upkeep) is not
  counted: its condition is not something this clock models.
- excluded outright: an opponent chooses (Intuition, Gifts Ungiven), the result is random
  (Gamble, Signal the Clans), "activate only if" conditions, a spell with no mana cost (Profane
  Tutor is suspend-only), additional costs other than sacrificing a creature, paying life or
  discarding, and tutors whose reach depends on another object ("where X is", "equal to",
  "same mana value as"). Transmute and other reminder-text searches are not read at all.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from mythgauntlet.model.card import Card

_SEARCH_RE = re.compile(
    r"search your library (?:and/or graveyard )?for "
    r"(?P<qty>a|an|one|two|three|four|five|any number of|up to (?:one|two|three|four|five)) "
    r"(?P<desc>.*?)\bcards?\b(?P<post>[^,.]*)")
_QTY = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
_REMINDER_RE = re.compile(r"\([^)]*\)")
_LOYALTY_RE = re.compile(r"^\s*[+−–-]?(\d+|x)\s*:")
_EXCLUDE_RE = re.compile(r"opponent chooses|at random|activate only if|where x is|equal to|"
                         r"same mana value as|different names")
_COLOURS = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
_CARD_TYPES = frozenset({"artifact", "creature", "enchantment", "instant", "sorcery", "land",
                         "planeswalker", "battle", "kindred", "tribal"})
_PERMANENT_TYPES = frozenset({"artifact", "creature", "enchantment", "land", "planeswalker",
                              "battle"})
_SUPERTYPES = frozenset({"basic", "legendary", "snow"})
# Destinations, most conservative first: a tutor naming several is credited with the worst.
_DESTINATIONS = (("top", re.compile(r"\bon top\b")),
                 ("hand", re.compile(r"into your hand")),
                 ("battlefield", re.compile(r"onto the battlefield")))
_BAD_DESTINATION_RE = re.compile(r"into your graveyard|\bexile (?:it|that card|them)\b")


def _type_tokens(card: Card) -> set[str]:
    front = (card.type_line or "").split(" // ")[0]
    return {t for t in re.split(r"[\s—-]+", front.casefold()) if t}


def _number(s: str | None) -> int | None:
    try:
        return int(str(s).strip())
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class TutorReach:
    name: str
    timing: str            # "spell" | "trigger" | "loyalty" | "activated"
    destination: str       # "top" | "hand" | "battlefield"
    cast_cost: int         # mana to put the tutor itself on the stack / battlefield
    use_cost: int          # extra mana per use (activated abilities); 0 otherwise
    x_cost: bool           # "mana value X or less": the fetched card's mana value is paid as X
    needs_creature: bool   # sacrifices a creature as a cost
    repeatable: bool       # an activated ability on a permanent that survives using it
    per_use: float         # how many cards one use fetches (math.inf for "any number of")
    _alts: tuple = field(default=(), repr=False)     # ((positive words), (negated words))
    _post: tuple = field(default=(), repr=False)     # parsed postfix constraint
    loyalty: int | None = None

    def can_fetch(self, piece: Card) -> bool:
        if piece.name == self.name:
            return False
        if not any(_alt_matches(pos, neg, piece) for pos, neg in self._alts):
            return False
        return _post_matches(self._post, piece, self)


def _alt_matches(pos: tuple[str, ...], neg: tuple[str, ...], card: Card) -> bool:
    tokens = _type_tokens(card)
    colours = set(card.colors)
    for w in pos:
        if w in _COLOURS:
            if _COLOURS[w] not in colours:
                return False
        elif w == "colorless":
            if colours:
                return False
        elif w == "multicolored":
            if len(colours) < 2:
                return False
        elif w == "permanent":
            if not tokens & _PERMANENT_TYPES:
                return False
        elif w not in tokens:          # card type, supertype or subtype, as printed
            return False
    for w in neg:
        if w == "permanent":
            if tokens & _PERMANENT_TYPES:
                return False
        elif w in tokens:
            return False
    return True


def _post_matches(post: tuple, card: Card, reach: TutorReach) -> bool:
    if not post:
        return True
    kind = post[0]
    if kind == "mv":
        _, n, cmp = post
        mv = card.mana_value
        if n == "x":
            # Tezzeret's -X: X is bounded by the walker's loyalty, not by mana.
            return reach.loyalty is None or mv <= reach.loyalty
        n = int(n)
        return mv == n if cmp is None else (mv <= n if cmp == "less" else mv >= n)
    if kind in ("power", "toughness"):
        _, n, cmp = post
        v = _number(card.power if kind == "power" else card.toughness)
        if v is None:
            return False
        return v <= n if cmp == "less" else v >= n
    if kind == "named":
        return post[1] in card.name.casefold()
    return False


_NOUN_HINT = _CARD_TYPES | {"permanent"}


def _parse_desc(desc: str) -> tuple | None:
    """'red or green creature' -> ((('red','creature'),()), (('green','creature'),()))."""
    desc = desc.replace("and/or", "or").strip()
    if not desc:
        return (((), ()),)
    alts_raw = [a.strip() for a in re.split(r"\bor\b", desc) if a.strip()]
    parsed = []
    for alt in alts_raw:
        words = [w for w in re.split(r"[\s,]+", alt) if w and w != "and"]
        pos, neg = [], []
        for w in words:
            if w.startswith("non") and len(w) > 3:
                base = w[3:].lstrip("-")
                neg.append(base)
            else:
                pos.append(w)
        parsed.append((pos, neg))
    # An adjective-only alternative ("red" in "red or green creature") takes the nouns of the
    # last alternative; a noun is a card type, "permanent", or anything not an adjective.
    def nouns(pos):
        return [w for w in pos if w not in _COLOURS and w not in _SUPERTYPES
                and w not in ("colorless", "multicolored")]
    last_nouns = nouns(parsed[-1][0]) if parsed else []
    out = []
    for pos, neg in parsed:
        if not nouns(pos) and not neg:
            pos = pos + last_nouns
        out.append((tuple(pos), tuple(neg)))
    return tuple(out)


def _parse_post(post: str) -> tuple | None:
    post = re.split(r"\s+and\s+", " " + post.strip() + " ", maxsplit=1)[0].strip()
    if not post or post.startswith("from "):
        return ()
    m = re.fullmatch(r"with mana value (\d+|x)(?: or (less|greater))?", post)
    if m:
        return ("mv", m.group(1), m.group(2))
    m = re.fullmatch(r"with (power|toughness) (\d+) or (less|greater)", post)
    if m:
        return (m.group(1), int(m.group(2)), m.group(3))
    m = re.fullmatch(r"named (.+)", post)
    if m:
        return ("named", m.group(1).strip())
    return None


def _destination(text: str, start: int) -> str | None:
    # The rest of the line, not "up to the shuffle": Vampiric Tutor puts the card on top
    # AFTER it shuffles.
    span = text[start:]
    if _BAD_DESTINATION_RE.search(span) and not any(rx.search(span) for _, rx in _DESTINATIONS):
        return None
    for name, rx in _DESTINATIONS:
        if rx.search(span):
            return name
    return None


def _activation_mana(head: str) -> int:
    total = 0
    for sym in re.findall(r"\{([^}]*)\}", head):
        s = sym.strip().lower()
        if s in ("t", "q", "e", "") or "/p" in s:
            continue                      # tap/untap/energy, and Phyrexian paid with life
        total += int(s) if s.isdigit() else 1
    return total


def tutor_reach(card: Card) -> TutorReach | None:
    """The card's counted tutor, or None (not a tutor, or one this clock cannot verify)."""
    from mythgauntlet.semantics.tags import _reachable_text

    raw = _REMINDER_RE.sub("", _reachable_text(card)).casefold()
    lines = [ln.strip().lstrip("•").strip() for ln in raw.splitlines() if ln.strip()]
    is_spell = card.has_type("Instant") or card.has_type("Sorcery")
    additional_creature = False
    for ln in lines:
        if ln.startswith("as an additional cost to cast"):
            if re.search(r"sacrifice an? (?:creature|another creature)", ln):
                additional_creature = True
            elif not re.search(r"pay \d+ life|discard a card", ln):
                return None
    for ln in lines:
        m = _SEARCH_RE.search(ln)
        if m is None:
            continue
        if _EXCLUDE_RE.search(ln):
            return None
        alts = _parse_desc(m.group("desc"))
        post = _parse_post(m.group("post"))
        if alts is None or post is None:
            return None
        dest = _destination(ln, m.start("post"))
        if dest is None:
            return None
        qty_word = m.group("qty").replace("up to ", "")
        per_use = math.inf if qty_word == "any number of" else _QTY.get(qty_word, 1)
        head = ln[:m.start()]
        loyalty = None
        repeatable = False
        use_cost = 0
        needs_creature = additional_creature
        lm = _LOYALTY_RE.match(ln)
        if lm and card.has_type("Planeswalker"):
            timing = "loyalty"
            loyalty = _number(card.loyalty)
            if loyalty is None:
                return None
        elif ":" in head and not head.startswith(("when", "whenever", "at ")):
            cost = head.split(":", 1)[0]
            if len(cost) > 80:
                return None
            timing = "activated"
            use_cost = _activation_mana(cost)
            if re.search(r"sacrifice (?:another|a) creature", cost):
                needs_creature = True
            elif "sacrifice" in cost and not re.search(r"sacrifice (?:this|~|it\b)", cost):
                return None                # sacrifices something this clock does not track
            # Sacrificing the tutor itself, or spending a counter, ends it; sacrificing
            # ANOTHER creature (Razaketh) does not.
            repeatable = not re.search(r"sacrifice (?:this|~|it\b)|\bremove\b", cost)
        elif head.startswith(("when", "whenever")):
            cond = head.split(",", 1)[0]
            if not re.search(r"\benters\b|cast this spell", cond):
                return None
            timing = "trigger"
        elif is_spell and not head.strip():
            timing = "spell"
        else:
            return None
        if not card.mana_cost_str and not card.is_land:
            return None                    # no mana cost: cannot be hard-cast (suspend-only)
        x_cost = bool(post) and post[0] == "mv" and post[1] == "x" and timing != "loyalty"
        return TutorReach(
            name=card.name, timing=timing, destination=dest, cast_cost=card.mana_value,
            use_cost=use_cost, x_cost=x_cost, needs_creature=needs_creature,
            repeatable=repeatable, per_use=per_use, _alts=alts, _post=post, loyalty=loyalty)
    return None
