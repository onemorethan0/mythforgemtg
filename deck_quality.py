"""Mana-curve and colour-source measurement over a Commander decklist.

`DeckBuilder` fills 99 slots by functional role, each drafted EDHREC-best-first. It has no
notion of curve and no notion of whether the manabase can cast what it drafted, so it can
draft twelve six-drops because they rank well, or land a {B}{B}{B} card in a deck with
nine black sources. These are the two missing measurements, as pure functions over a
finished or partial decklist. This module decides nothing — it measures and recommends.

Worked examples (SPEC section 4):

    mana_value {2/W}{2/W}   -> 4     hybrid takes its HIGHER half (CR 202.3f), twice
    mana_value {X}{R}{R}    -> 2     X is 0
    mana_value {R/P}        -> 1     phyrexian
    pip_counts {5}{B}{R}    -> {B:1, R:1}
    pip_counts {B/R}{B}     -> {B:2, R:1}   hybrid is payable by EITHER, so it counts
                                            toward both colours' source requirement
    curve of a MV-9 card    -> bucket 7      (7+ is one bucket)
    curve_target(63, 7)     -> sums to exactly 63; buckets 6 and 7 each 3 lower than
                               curve_target(63, 4), buckets 2 and 3 each 3 higher
    color_sources of 14 aggregated Mountains -> {R: 14}, not {R: 1}
    color_sources of Command Tower           -> +1 for all five colours

`quantity` is load-bearing throughout: basics are aggregated into ONE dict carrying
`quantity: 14`, so every count sums qty() and never uses len().
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import collection_pool

WUBRG: str = "WUBRG"

_COLOR_SYM = re.compile(r"\{([^}]+)\}")


# ── Card field readers ───────────────────────────────────────────────────────────

def qty(card: dict) -> int:
    """Physical copies. 14 aggregated Mountains are 14 sources, not 1."""
    try:
        q = int(card.get("quantity", 1) or 1)
    except (TypeError, ValueError):
        return 1
    return max(1, q)


def _mana_cost(card: dict) -> str:
    cost = card.get("mana_cost")
    if cost:
        return cost
    for face in card.get("card_faces") or []:
        if face.get("mana_cost"):
            return face["mana_cost"]
    return ""


def _type_line(card: dict) -> str:
    tl = card.get("type_line")
    if tl:
        return tl
    return " // ".join(f.get("type_line", "") for f in (card.get("card_faces") or []))


def _oracle(card: dict) -> str:
    parts = [card.get("oracle_text") or ""]
    parts += [f.get("oracle_text") or "" for f in (card.get("card_faces") or [])]
    return "\n".join(p for p in parts if p)


def is_land(card: dict) -> bool:
    return "land" in _type_line(card).lower()


def mana_value(card: dict) -> int:
    """cmc when present, else parsed from the mana cost."""
    cmc = card.get("cmc")
    if cmc is not None:
        try:
            return int(float(cmc))
        except (TypeError, ValueError):
            pass
    total = 0
    for tok in _COLOR_SYM.findall(_mana_cost(card)):
        t = tok.upper()
        if t == "X":
            continue                       # X is 0 on the stack for curve purposes
        if "/" in t:
            # CR 202.3f: a hybrid's mana value is its HIGHEST possible half. (Verified
            # against the live Comprehensive Rules corpus 2026-08-24 -- a prior version
            # of this comment cited 202.3b, which has since become the DFC mana-value
            # rule as WotC inserted new subrules around it; the content is unchanged,
            # only the letter moved.)
            halves = [int(p) if p.isdigit() else 1 for p in t.split("/") if p != "P"]
            total += max(halves) if halves else 1
        elif t.isdigit():
            total += int(t)
        else:
            total += 1
    return total


def pip_counts(card: dict) -> dict[str, int]:
    """Coloured pips demanded. A hybrid {B/R} adds 1 to BOTH B and R — either colour
    can pay it, so both colours' source counts must be able to satisfy it."""
    counts: dict[str, int] = {}
    for tok in _COLOR_SYM.findall(_mana_cost(card)):
        for part in tok.upper().split("/"):
            if part in WUBRG:
                counts[part] = counts.get(part, 0) + 1
    return counts


# ── Curve ────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CurveVerdict:
    average: float
    buckets: dict[int, int]
    target: dict[int, int]
    over: dict[int, int]
    under: dict[int, int]
    verdict: str
    notes: list[str]


def curve(deck: list[dict]) -> dict[int, int]:
    """Quantity-weighted MV histogram of NONLAND cards; 7+ collapses into key 7."""
    hist: dict[int, int] = {}
    for card in deck:
        if is_land(card):
            continue
        hist[bucket(card)] = hist.get(bucket(card), 0) + qty(card)
    return hist


def bucket(card: dict) -> int:
    """The curve bucket a card belongs to: 1..7, where 7 is "7 or more".

    MV 0 counts as a one-drop. curve_target has no bucket 0, so leaving zero-cost
    cards in their own bucket made them unable to satisfy ANY shortfall — Mox Amber
    and Ornithopter were drafted only after every other bucket was full, which sorts
    some of the format's strongest cards last."""
    return max(1, min(mana_value(card), 7))


_BASE_CURVE = {1: 0.08, 2: 0.19, 3: 0.21, 4: 0.17, 5: 0.13, 6: 0.10, 7: 0.12}


def curve_target(nonland_count: int, commander_mv: int) -> dict[int, int]:
    """The reference curve, guaranteed to sum EXACTLY to nonland_count.

    A seven-drop commander needs a CHEAPER deck under it, not a heavier one, so每
    point of commander_mv above 4 moves one slot out of bucket 6 into 2, and one out
    of 7 into 3."""
    tgt = {mv: int(round(nonland_count * pct)) for mv, pct in _BASE_CURVE.items()}
    tgt[3] += nonland_count - sum(tgt.values())      # rounding remainder, deterministic

    for _ in range(max(0, commander_mv - 4)):
        # The two moves are INDEPENDENT, not atomic. _BASE_CURVE weights bucket 7 above
        # bucket 6, so 6 empties first and further points shift only 7->3; that is the
        # intended direction (a very expensive commander wants an even cheaper deck) and
        # the sum guarantee holds regardless, because every move is -1 here and +1 there.
        if tgt[6] > 0:
            tgt[6] -= 1
            tgt[2] += 1
        if tgt[7] > 0:
            tgt[7] -= 1
            tgt[3] += 1

    for mv in tgt:
        tgt[mv] = max(0, tgt[mv])
    tgt[3] += nonland_count - sum(tgt.values())
    return tgt


def assess_curve(deck: list[dict], commander_mv: int) -> CurveVerdict:
    # One pass, one definition of MV. The average must use the TRUE mana value, not the
    # bucketing value: clamping at 7 reported a deck of three 9-drops as average 7.0,
    # understating exactly the top-heavy decks this function exists to detect. Bucketing
    # still clamps, because bucket 7 IS the "7+" bucket.
    buckets: dict[int, int] = {}
    nonland = 0
    total_mv = 0
    for card in deck:
        if is_land(card):
            continue
        n = qty(card)
        b = bucket(card)
        buckets[b] = buckets.get(b, 0) + n
        nonland += n
        total_mv += mana_value(card) * n
    average = round(total_mv / nonland, 2) if nonland else 0.0
    target = curve_target(nonland, commander_mv)

    over = {mv: buckets.get(mv, 0) - target.get(mv, 0)
            for mv in range(1, 8) if buckets.get(mv, 0) > target.get(mv, 0)}
    under = {mv: target.get(mv, 0) - buckets.get(mv, 0)
             for mv in range(1, 8) if buckets.get(mv, 0) < target.get(mv, 0)}

    tol = 0.15 * nonland
    top = sum(buckets.get(m, 0) for m in (5, 6, 7)) - sum(target.get(m, 0) for m in (5, 6, 7))
    early = sum(target.get(m, 0) for m in (1, 2)) - sum(buckets.get(m, 0) for m in (1, 2))

    notes: list[str] = []
    if top > tol:
        verdict = "top-heavy"
        notes.append(f"{int(top)} too many cards at MV 5+ — the deck will stall on a "
                     f"slow draw.")
    elif early > tol:
        verdict = "too-flat"
        notes.append(f"{int(early)} too few cards at MV 1-2 — nothing to do on the "
                     f"early turns.")
    else:
        verdict = "ok"
    if over:
        notes.append("Heaviest overshoot: MV " + str(max(over, key=over.get)))
    if under:
        notes.append("Thinnest slot: MV " + str(max(under, key=under.get)))

    return CurveVerdict(average, buckets, target, over, under, verdict, notes[:3])


# ── Colour sources ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ColorVerdict:
    pips: dict[str, int]
    sources: dict[str, int]
    required: dict[str, int]
    short: dict[str, int]
    ok: bool
    notes: list[str]


_ADD_CLAUSE = re.compile(r"\badd\b([^.;\n]*)", re.I)


def _produces(card: dict) -> set[str]:
    """Colours this card can actually PRODUCE.

    Scryfall's produced_mana is authoritative when non-empty. When it is empty or
    absent we fall back to Add clauses ONLY — never to bare colour words. Nim
    Deathmantle's "is a black Zombie" is not a black mana source, and its
    produced_mana is [] (falsy), so a naive fallback counts it as one."""
    produced = card.get("produced_mana")
    if produced:
        return {c for c in produced if c in WUBRG}
    cols: set[str] = set()
    for m in _ADD_CLAUSE.finditer(_oracle(card)):
        clause = m.group(1)
        if re.search(r"\bany colou?r\b", clause, re.I):
            return set(WUBRG)
        for tok in _COLOR_SYM.findall(clause):
            for part in tok.upper().split("/"):
                if part in WUBRG:
                    cols.add(part)
    return cols


# Basic land type -> the colour it taps for. A fetchland finds one of these.
_FETCH_TYPE_COLOR = {"plains": "W", "island": "U", "swamp": "B",
                     "mountain": "R", "forest": "G"}
_FETCH_RE = re.compile(r"search your library for an? ([^.]*?) card", re.I)


def _fetches(card: dict) -> set[str]:
    """Colours a fetchland effectively provides by finding a basic of that type.

    A fetchland produces NO mana of its own — `produced_mana` is empty — so counting only
    what a card produces scored Marsh Flats as zero white and zero black sources. In play it
    is plainly both: it finds the Plains or the Swamp. A measured Tymna (WB) build had 36
    lands and was reported short on black while running eight fetches that could each find
    a Swamp.

    Only fires for a card that says "search your library for a ... card" AND produces
    nothing itself, so a dual land is still counted by `_produces` and never twice here.
    An unqualified "basic land card" (Evolving Wilds, Fabled Passage) finds ANY basic, so
    it counts for every colour the deck could want — the caller filters to the commander's
    identity anyway.
    """
    if card.get("produced_mana"):
        return set()
    text = _oracle(card)
    m = _FETCH_RE.search(text)
    if not m:
        return set()
    clause = m.group(1).lower()
    named = {c for t, c in _FETCH_TYPE_COLOR.items() if t in clause}
    if named:
        return named
    return set(WUBRG) if "basic land" in clause else set()


def color_sources(deck: list[dict]) -> dict[str, int]:
    """Quantity-weighted count of permanents providing each colour. Lands and rocks
    alike — a Signet fixes colour just as a dual does. Counted once per colour.

    A FETCHLAND counts for the colours it can find (see `_fetches`): it makes no mana of
    its own, but scoring Marsh Flats as neither a white nor a black source is wrong about
    the game."""
    sources: dict[str, int] = {}
    for card in deck:
        n = qty(card)
        # A fetchland produces nothing itself but IS a source for whatever it finds.
        for col in (_produces(card) or _fetches(card)):
            sources[col] = sources.get(col, 0) + n
    return sources


def required_sources(pips: dict[str, int], nonland_count: int) -> dict[str, int]:
    """Sources needed per colour, a simplified Karsten shape.

    Only totals are available here, so 'heavy' is approximated as a colour carrying
    a disproportionate share of the deck's pips. The mean is taken over all five
    colours, NOT over the colours in use: a two-colour deck's mean over two colours
    caps the ratio at 2x, which no colour could ever exceed."""
    if not pips:
        return {}
    mean = sum(pips.values()) / len(WUBRG)
    scale = nonland_count / 63 if nonland_count else 1.0
    return {col: int(round((20 if total >= 2.5 * mean else 15) * scale))
            for col, total in pips.items() if total > 0}


def assess_colors(deck: list[dict], commander: dict) -> ColorVerdict:
    """Commander pips COUNT — you have to be able to cast it."""
    pips: dict[str, int] = {}
    nonland = 0
    for card in deck:
        if is_land(card):
            continue
        n = qty(card)
        nonland += n
        for col, cnt in pip_counts(card).items():
            pips[col] = pips.get(col, 0) + cnt * n
    for col, cnt in pip_counts(commander).items():
        pips[col] = pips.get(col, 0) + cnt

    sources = color_sources(deck)
    # Command Tower and Spire of Industry list all five colours in produced_mana, but
    # they only ever make mana in YOUR commander's identity. Reporting W/U/G sources
    # for a Rakdos deck is noise at best and misleading at worst.
    #
    # An IMPORTED deck can carry commander={"name": None, "color_identity": None} — a
    # 60-card list, or one whose commander zone never resolved. Falling back to the
    # colours the deck's own pips demand keeps the filter working there: without it an
    # Izzet import reported B/G/W sources off its five-colour lands.
    ci = {c for c in (commander.get("color_identity") or []) if c in WUBRG}
    if not ci:
        ci = set(pips)
    if ci:
        sources = {col: n for col, n in sources.items() if col in ci}

    required = required_sources(pips, nonland)
    short = {col: req - sources.get(col, 0)
             for col, req in required.items() if sources.get(col, 0) < req}

    notes = [f"{col}: {sources.get(col, 0)} sources, wants {required[col]}"
             for col in sorted(short, key=lambda c: -short[c])][:3]
    return ColorVerdict(pips, sources, required, short, not short, notes)


@dataclass
class ManaBaseVerdict:
    lands: int
    ramp: int
    sources: int
    verdict: str
    ok: bool
    notes: list[str]


# Calibrated over 459 corpus decks (95-101 cards, >=95% of names resolved, and excluding
# 4 rows the corpus fetched WITHOUT their manabase — a landless 102-card "deck" is a bad
# scrape, not a bad deck, and leaving those in dragged the low tail). Percentiles:
#   lands    p05 30  p10 32  median 36  p95 40
#   sources  p05 38  p10 40  median 47  p95 61
LOW_LANDS = 32          # p10 — below this the deck is leaning on something else
MIN_SOURCES = 38        # p05 — below this it is short by the standard of real decks

MANA_OK = "ok"
MANA_RAMP_DEPENDENT = "ramp-dependent"
MANA_SHORT = "short"


def ramp_count(deck: list[dict]) -> int:
    """Quantity-weighted count of NONLAND cards that produce or fetch mana.

    Delegates to `collection_pool.classify` rather than re-deriving "what is ramp".
    This repo has been bitten repeatedly by two structures that must agree and only
    one of which is tested (`tags.py` vs `profile.py`, the two theme branches), and a
    second ramp definition drifting from the first is the same bug waiting to happen.
    That classifier is net-positive-aware, so a `{1},{T}: Add {B}` filter — which nets
    zero — is correctly not counted.
    """
    return sum(qty(c) for c in deck
               if not is_land(c) and "ramp" in collection_pool.classify(c))


def assess_mana_base(deck: list[dict]) -> ManaBaseVerdict:
    """Whether the deck has enough mana, counting RAMP as well as lands.

    A land count alone cannot answer this, and saying otherwise would be the worst kind
    of wrong — confidently flagging a deliberate build. Measured over the corpus,
    **10.9% of real decks run under 33 lands and 68% of those clear 40 total sources**:
    a low land count is usually a choice that ramp pays for, not a mistake. So a deck is
    only called SHORT when both halves fail; a low land count with the ramp to support it
    is reported as `ramp-dependent`, which is a description of how it plays (it needs to
    hit its ramp) and not a fault.

    `sources` is deliberately a coarse figure — a ritual and a Signet are not the same
    thing, and the notes say "lands + ramp" rather than implying a mana count.
    """
    lands = sum(qty(c) for c in deck if is_land(c))
    ramp = ramp_count(deck)
    sources = lands + ramp

    # BOTH halves must fail. Testing `sources` alone looks equivalent and is not: it
    # called a 35-land deck with 2 ramp "short", and 35 lands is the 25th percentile of
    # real decks — an ordinary manabase attached to a deck that simply does not ramp.
    # Not ramping is a playstyle (a low-curve aristocrats list wants spells, not rocks),
    # so the land count is what decides whether the deck is actually missing mana.
    if lands < LOW_LANDS and sources < MIN_SOURCES:
        verdict = MANA_SHORT
    elif lands < LOW_LANDS:
        verdict = MANA_RAMP_DEPENDENT
    else:
        verdict = MANA_OK

    notes: list[str] = []
    if verdict == MANA_SHORT:
        notes.append(f"{lands} lands + {ramp} ramp = {sources} sources; "
                     f"95% of decks run {MIN_SOURCES} or more")
    elif verdict == MANA_RAMP_DEPENDENT:
        notes.append(f"{lands} lands is low, but {ramp} ramp brings it to {sources} "
                     f"— the deck needs to hit its ramp")
    return ManaBaseVerdict(lands, ramp, sources, verdict, verdict != MANA_SHORT, notes)


def suggest_cuts(deck: list[dict], verdict: CurveVerdict, limit: int = 8) -> list[dict]:
    """Nonland cards worth cutting from the OVER-full buckets, least-played first.

    A missing or None edhrec_rank sorts FIRST (most cuttable) — it means the card is
    played rarely enough that EDHREC has no rank for it. Defaulting it to 0 would
    make it look like the best card in the deck and it would never be cut, and
    comparing None against int raises TypeError mid-sort."""
    if verdict.verdict != "top-heavy":
        return []
    over = set(verdict.over)
    cands = [c for c in deck if not is_land(c) and bucket(c) in over]

    def _cuttable(card: dict) -> tuple:
        r = card.get("edhrec_rank")
        return (0, 0, card.get("name", "")) if not isinstance(r, int) else (1, -r, card.get("name", ""))

    cands.sort(key=_cuttable)
    return cands[:limit]
