"""Local role classification over an OWNED card pool (strict collection-aware building).

`DeckBuilder` normally fills each functional slot with a Scryfall `otag:` search sorted by
EDHREC rank. In strict "build only from cards I own" mode there is no search — there is
only a flat list of card dicts. This module classifies those cards into deck roles from
their own oracle text, and partitions them for one commander. Pure, offline, no network.

Gold set — `classify()` must derive exactly these (verified against live oracle text):

    Sol Ring              {ramp}            {T}: Add {C}{C}                  net +2
    Arcane Signet         {ramp}            {T}: Add one mana of any color
    Springleaf Drum       {ramp}            {T}, Tap a creature: Add one mana
    Mind Stone            {ramp, draw}      mana ability + sac-to-draw
    Blasphemous Act       {wipe}            13 damage to EACH CREATURE (singular!)
    Vandalblast           {removal}         destroy target artifact  — NOT a wipe
    Rest in Peace         {}                exile all GRAVEYARDS     — NOT a wipe
    Toxic Deluge          {wipe}            all creatures get -X/-X
    Lightning Bolt        {removal}         3 damage to ANY TARGET
    Chaos Warp            {removal}         owner SHUFFLES IT into their library
    Phyrexian Arena       {draw}
    Seize the Spoils      {draw, ramp}      "Draw TWO cards" + Treasure
    Laughing Mad          {draw}            discard 1 -> draw two = net +1
    Dangerous Wager       {draw}
    Darksteel Plate       {protection}      grants indestructible to another
    Smaug the Impenetrable {}               HAS indestructible — protects only itself
    Lightning Greaves     {protection}
    Berserkers' Onslaught {finisher}        attacking creatures gain double strike
    Hellkite Tyrant       {finisher}        "you win the game"
    Mana Geyser           {ramp}
    Wayfarer's Bauble     {ramp}            land search — NOT draw
    Solemn Simulacrum     {ramp, draw}      "you MAY draw a card"
    Command Tower         {ramp}            a land; build_pool routes it to .lands
    {1},{T}: Add {B}      {}                net ZERO — not ramp
    {1},{T}: Add {W}{W}   {ramp}            net +1 — is ramp
"""
from __future__ import annotations

import re
from dataclasses import dataclass

ROLES: tuple[str, ...] = ("ramp", "draw", "removal", "wipe", "protection", "finisher")

# Oracle text spells CARD COUNTS as words ("Draw two cards") but DAMAGE as digits
# ("deals 3 damage"). Accept both everywhere rather than guessing per-effect.
_NUM = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|x)"
_NUM_WORD = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
             "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


@dataclass(frozen=True)
class PoolStats:
    total_owned: int
    eligible: int
    by_role: dict[str, int]
    lands: int
    creatures: int


@dataclass
class CardPool:
    commander: dict
    roles: dict[str, list[dict]]
    lands: list[dict]
    creatures: list[dict]
    flex: list[dict]
    stats: PoolStats


def _rank_key(card: dict) -> tuple:
    """EDHREC-best first, unranked last, name as a deterministic tiebreak.

    One helper for every sort in the module — the builder must be reproducible."""
    r = card.get("edhrec_rank")
    name = card.get("name", "")
    return (0, r, name) if isinstance(r, int) else (1, 0, name)


def _count_word(tok: str) -> int:
    tok = tok.lower()
    return int(tok) if tok.isdigit() else _NUM_WORD.get(tok, 0)


# ── Card field readers (multi-face safe) ─────────────────────────────────────────

def card_text(card: dict) -> str:
    """All oracle text, front + every face. A DFC/split may carry text ONLY in faces."""
    parts = []
    if card.get("oracle_text"):
        parts.append(card["oracle_text"])
    for face in card.get("card_faces") or []:
        if face.get("oracle_text"):
            parts.append(face["oracle_text"])
    return "\n".join(parts)


def type_line(card: dict) -> str:
    tl = card.get("type_line")
    if tl:
        return tl
    faces = [f.get("type_line") for f in (card.get("card_faces") or []) if f.get("type_line")]
    return " // ".join(faces)


def is_basic_land(card: dict) -> bool:
    """Token-matched, not substring: 'Basic Snow Land — Forest' must still count."""
    tl = type_line(card).lower()
    return bool(re.search(r"\bbasic\b", tl) and re.search(r"\bland\b", tl))


def is_land(card: dict) -> bool:
    return "land" in type_line(card).lower()


def is_creature(card: dict) -> bool:
    tl = type_line(card).lower()
    return "creature" in tl and "land" not in tl


def is_commander_legal(card: dict) -> bool:
    """A MISSING legalities dict returns True — slim card dicts omit it entirely."""
    leg = card.get("legalities")
    if not isinstance(leg, dict) or "commander" not in leg:
        return True
    return leg["commander"] == "legal"


def in_identity(card: dict, ci: set[str]) -> bool:
    """An EMPTY ci is a colourless commander: only colourless cards qualify."""
    card_ci = set(card.get("color_identity") or [])
    return not card_ci if not ci else card_ci <= ci


def is_commander_eligible(card: dict) -> bool:
    tl = type_line(card).lower()
    if "legendary" in tl and "creature" in tl:
        return True
    return "can be your commander" in card_text(card).lower()


def owned_commanders(cards: list[dict]) -> list[dict]:
    """Does NOT filter by legality — a banned commander is still surfaced so the
    caller can explain why it is unavailable rather than silently hiding it."""
    return sorted((c for c in cards if is_commander_eligible(c)), key=_rank_key)


# ── Role gates ───────────────────────────────────────────────────────────────────

_ADD_RE = re.compile(r"\badd\b", re.I)


def _mana_produced(chunk: str) -> int:
    """Mana produced by an 'Add …' clause. `chunk` is the text after the word Add."""
    clause = re.split(r"[.;\n]", chunk, 1)[0]
    syms = [s for s in re.findall(r"\{([^}]+)\}", clause) if s.lower() not in ("t", "q")]
    if syms:
        return len(syms)
    # "Add one mana of any color" / "Add two mana of any one color"
    m = re.search(rf"^\s*({_NUM})\s+mana", clause, re.I)
    if m:
        return _count_word(m.group(1)) or 1
    return 1 if re.search(r"^\s*mana\b", clause, re.I) else 0


def _activation_generic(text: str, add_pos: int) -> int:
    """Generic mana in the activation cost preceding this Add, e.g. 2 for '{2}, {T}:'.

    Bug this prevents (failure mode B): '{1}, {T}: Add {B}' nets ZERO and is not ramp,
    but a naive '{T}: Add {' pattern matches the substring inside it."""
    line_start = text.rfind("\n", 0, add_pos) + 1
    seg = text[line_start:add_pos]
    colon = seg.rfind(":")
    if colon == -1:
        return 0                      # a ritual / triggered Add has no activation cost
    cost = seg[seg.rfind(". ", 0, colon) + 1:colon]
    return sum(int(d) for d in re.findall(r"\{(\d+)\}", cost))


def _net_mana_positive(text: str) -> bool:
    """True when some Add ability produces MORE mana than its activation cost.

    Sol Ring ({T}: Add {C}{C}) nets +2. A filter rock ({1},{T}: Add {W}{W}) nets +1 and
    IS ramp. A mana-negative filter ({1},{T}: Add {B}) nets 0 and is NOT."""
    if re.search(r"\badd\b[^.\n]*\bfor each\b", text, re.I):
        return True                   # Mana Geyser: scales, always worth counting
    for m in _ADD_RE.finditer(text):
        after = text[m.end():]
        if _mana_produced(after) - _activation_generic(text, m.start()) > 0:
            return True
    return False


def _is_net_draw(text: str) -> bool:
    """Net card advantage. A discard COST paired with a single draw replaces rather
    than draws (looting); 'discard a card. Draw two cards' is +1 and counts."""
    low = text.lower()
    # Symmetric/opponent draw is not card advantage for us unless we also draw.
    if re.search(r"(each|target) opponent draws", low) and not re.search(r"you draw", low):
        return False
    has_discard = "discard" in low
    m = re.search(rf"draws?\s+({_NUM})\s+cards?", low)
    if m:
        # Painful Truths: "you draw X cards". X is unknown but positive by design —
        # counting it as 0 silently dropped every X-draw spell from the pool.
        if m.group(1) == "x":
            return True
        n = _count_word(m.group(1))
        return n > 1 if has_discard else n > 0
    if re.search(r"draws?\s+a\s+card", low):
        return not has_discard
    if re.search(r"look at the top.*put.*into your hand", low, re.S):
        return True
    return bool(re.search(r"exile the top.*you may play", low, re.S))


def _grants_protection_to_other(card: dict, text: str) -> bool:
    """A creature that merely HAS indestructible/hexproof protects only itself.

    Smaug the Impenetrable ('Flying, indestructible, haste') must NOT be tagged
    protection; Darksteel Plate ('Equipped creature has indestructible') must be."""
    if not is_creature(card):
        return True                   # Equipment / Aura / instant / sorcery grants
    return bool(re.search(r"\btarget\b|\byou control\b|\banother\b", text, re.I))


_REMOVAL_PATTERNS = [
    r"destroy target (?:creature|permanent|artifact|enchantment|planeswalker|land|nonland)",
    r"exile target",
    r"return target .{0,40} to its owner['’]s hand",
    rf"deals? {_NUM} damage to (?:target|any target)",
    r"target creature (?:gets? -|phases out)",
    r"each opponent sacrifices",
    r"counter target spell",
    # Chaos Warp never says destroy/exile/return — it shuffles the permanent away.
    r"owner of target permanent shuffles",
]

_WIPE_PATTERNS = [
    r"destroy all creatures",
    r"exile all creatures",
    r"all creatures get -",
    r"each creature gets -",
    # "each creature" is SINGULAR in real templating — do not gate this on "creatures".
    rf"deals? {_NUM} damage to each creature",
    r"each player sacrifices .{0,40}creature",
    r"destroy all nonland permanents",
    r"destroy all creatures and",
]

_PROTECTION_KEYWORDS = [
    r"\bhexproof\b", r"\bshroud\b", r"\bindestructible\b",
    r"protection from\b", r"\bward\b",           # \b: 'ward' must not match 'Warden'
    r"\bregenerate\b", r"phases? out\b",
]

_FINISHER_PATTERNS = [
    r"you win the game",
    r"(?:target |each )?opponent loses the game",
    r"(?:an? )?additional combat phase",
    # Mass pump alone is an anthem; the trample half is what makes it a finisher.
    r"deals damage equal to .{0,60} to each opponent",
    rf"each opponent loses {_NUM} life",
]


def classify(card: dict) -> set[str]:
    """Zero or more of ROLES. A card may legitimately fill several."""
    text = card_text(card)
    low = text.lower()
    roles: set[str] = set()

    if (_net_mana_positive(text)
            or re.search(r"search your library for .{0,60}land.{0,60}(?:onto|into) the battlefield",
                         low, re.S)
            or re.search(r"play an additional land", low)
            or re.search(r"creates? (?:a|two|three) treasure token", low)
            or re.search(r"spells you cast cost \{[^}]+\} less", low)):
        roles.add("ramp")

    if _is_net_draw(text):
        roles.add("draw")

    if any(re.search(p, low) for p in _REMOVAL_PATTERNS):
        roles.add("removal")

    if any(re.search(p, low) for p in _WIPE_PATTERNS):
        roles.add("wipe")

    if any(re.search(p, low) for p in _PROTECTION_KEYWORDS) and _grants_protection_to_other(card, text):
        roles.add("protection")
    if re.search(r"can't be countered", low) or re.search(r"counter target spell that targets", low):
        roles.add("protection")

    if any(re.search(p, low) for p in _FINISHER_PATTERNS):
        roles.add("finisher")
    if re.search(r"creatures you control get \+\d+/\+\d+", low) and "trample" in low:
        roles.add("finisher")
    # Granted double strike is a finisher; a lone creature that HAS it is not.
    if re.search(r"creatures you control (?:have|gain) double strike", low):
        roles.add("finisher")

    return roles


# ── Pool construction ────────────────────────────────────────────────────────────

def build_pool(commander: dict, cards: list[dict]) -> CardPool:
    """Partition the owned cards for this commander, every list EDHREC-best-first.

    The role lists are VIEWS, not a partition: a card filling three roles appears in
    all three, and every eligible nonland card also appears in `flex`."""
    ci = set(commander.get("color_identity") or [])
    cmd_name = commander.get("name", "")

    eligible = [c for c in cards
                if c.get("name") != cmd_name
                and not is_basic_land(c)
                and is_commander_legal(c)
                and in_identity(c, ci)]

    lands = sorted((c for c in eligible if is_land(c)), key=_rank_key)
    creatures = sorted((c for c in eligible if is_creature(c)), key=_rank_key)
    flex = sorted((c for c in eligible if not is_land(c)), key=_rank_key)

    roles: dict[str, list[dict]] = {r: [] for r in ROLES}
    for card in eligible:
        for role in classify(card):
            roles[role].append(card)
    for role in ROLES:
        roles[role].sort(key=_rank_key)

    return CardPool(
        commander=commander,
        roles=roles,
        lands=lands,
        creatures=creatures,
        flex=flex,
        stats=PoolStats(
            total_owned=len(cards),
            eligible=len(eligible),
            by_role={r: len(roles[r]) for r in ROLES},
            lands=len(lands),
            creatures=len(creatures),
        ),
    )


def shortfall(pool: CardPool, plan: dict[str, int]) -> dict[str, int]:
    """Per-role deficit. Covered roles are OMITTED, so {} means the collection can
    fill this plan. 'lands' and 'creatures' are honoured; other keys are ignored."""
    out: dict[str, int] = {}
    for key, wanted in plan.items():
        if key in ROLES:
            have = len(pool.roles.get(key, []))
        elif key == "lands":
            have = len(pool.lands)
        elif key == "creatures":
            have = len(pool.creatures)
        else:
            continue
        if wanted > have:
            out[key] = wanted - have
    return out
