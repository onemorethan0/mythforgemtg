"""'Buildable from my collection' — which commanders can the user assemble from
owned cards, and how complete would each B1–3 deck be.

This is the front door that turns the collection from a *filter* (collection-aware
building) / *upgrade source* (advise) into a *recommender*: "here are the decks you
can sleeve up tonight." It's a fast, local scan — no simulation — over the owned
cards resolved through Scryfall. "Build this" then goes through the normal generate
flow (collection-aware) where the deck can be measured for a real bracket.

Scoring is deliberately honest and simple:
  • buildable_pct = how much of the ~63 nonland slots the owned on-color pool covers.
  • role coverage = lightweight oracle-text heuristics (ramp/draw/removal/wipe/
    finisher) so we can say "you're thin on removal" without a full build.
Lands aren't a gating constraint (basics fill freely), so they don't lower the score.
"""
from __future__ import annotations

import re

# A Commander deck is 100 cards: ~37 lands (mostly basics, effectively free) + ~63
# nonland. So the nonland pool is what gates "can I build this".
TARGET_NONLAND = 63

# Minimum owned on-color count per essential role before we stop flagging it as a gap.
_ROLE_FLOORS = {"ramp": 8, "draw": 8, "removal": 5, "wipe": 2, "finisher": 1}

_ROLE_LABELS = {
    "ramp": "ramp", "draw": "card draw", "removal": "removal",
    "wipe": "board wipes", "finisher": "finishers",
}

# Oracle-text heuristics. Rough but useful — good enough to surface "thin on X".
_ROLE_PATTERNS: dict[str, list[re.Pattern]] = {
    "ramp": [re.compile(p, re.I) for p in (
        r"\badd\s+\{[wubrgc0-9]", r"\badd\s+(one|two|three)\b.*\bmana\b",
        r"search your library for (a|up to \w+)\b.*\bland", r"\bcreate a treasure",
        r"\bmana of any color", r"\buntap target (land|permanent)",
    )],
    "draw": [re.compile(p, re.I) for p in (
        r"\bdraw (a card|two cards|three cards|\w+ cards|cards equal)",
        r"\bdraw that many cards", r"\binvestigate\b",
    )],
    "removal": [re.compile(p, re.I) for p in (
        r"\bdestroy target\b", r"\bexile target\b",
        r"\bdeals? \d+ damage to (target|any)", r"\btarget (creature|player|permanent) gets? -",
        r"\bfight(s)? target", r"\breturn target .* to (its|their) owner",
        r"\btarget (creature|permanent) .*can't", r"\bcounter target",
    )],
    "wipe": [re.compile(p, re.I) for p in (
        r"\bdestroy all\b", r"\bexile all\b", r"\ball creatures get -",
        r"\beach (creature|player) sacrifices", r"\bdestroy each\b",
        r"\bdeals? \d+ damage to each (creature|player|opponent)",
    )],
    "finisher": [re.compile(p, re.I) for p in (
        r"\bwins? the game\b", r"\bloses? the game\b", r"\bextra (turn|combat)",
        r"\bcreatures you control get \+\d+/\+\d+ and gain (trample|haste)",
        r"\bdouble\b.*\bdamage\b", r"\binfinite\b", r"\bcan't be blocked\b.*\bdeals",
    )],
}


def _card_text(card: dict) -> str:
    """All oracle text for a card, including both faces of a DFC/split."""
    parts = [card.get("oracle_text", "") or ""]
    for face in card.get("card_faces", []) or []:
        parts.append(face.get("oracle_text", "") or "")
    return "\n".join(parts)


def _type_line(card: dict) -> str:
    tl = card.get("type_line", "") or ""
    if not tl:
        tl = " ".join((f.get("type_line", "") or "") for f in card.get("card_faces", []) or [])
    return tl


def classify_roles(card: dict) -> set[str]:
    """The essential roles a card plausibly fills (may be several, or none)."""
    text = _card_text(card)
    tl = _type_line(card).lower()
    roles = {role for role, pats in _ROLE_PATTERNS.items()
             if any(p.search(text) for p in pats)}
    # A mana rock/dork is ramp even if the regex missed it.
    if "artifact" in tl and re.search(r"\{t\}.*add \{", text, re.I):
        roles.add("ramp")
    return roles


def is_commander_eligible(card: dict) -> bool:
    """Can this owned card head a Commander deck?"""
    tl = _type_line(card).lower()
    if "legendary" in tl and "creature" in tl:
        return True
    # Some planeswalkers / other cards explicitly say so.
    return "can be your commander" in (_card_text(card).lower())


def _is_basic_land(card: dict) -> bool:
    tl = _type_line(card).lower()
    return "basic" in tl and "land" in tl


def _in_identity(card: dict, ci: set[str], colorless: bool) -> bool:
    card_ci = set(card.get("color_identity", []) or [])
    if colorless:
        return not card_ci
    return card_ci <= ci


def _legal(card: dict) -> bool:
    return (card.get("legalities", {}) or {}).get("commander") == "legal"


def score_commander(commander: dict, cards: list[dict]) -> dict:
    """Buildability + role coverage for one candidate commander over the owned pool."""
    ci = set(commander.get("color_identity", []) or [])
    colorless = not ci
    pool = [c for c in cards
            if c.get("id") != commander.get("id")
            and not _is_basic_land(c)
            and _legal(c)
            and _in_identity(c, ci, colorless)]
    nonland = [c for c in pool if "land" not in _type_line(c).lower()]
    lands = [c for c in pool if "land" in _type_line(c).lower()]

    role_counts = {r: 0 for r in _ROLE_FLOORS}
    for c in nonland:
        for r in classify_roles(c):
            if r in role_counts:
                role_counts[r] += 1

    buildable_pct = min(100, round(100 * len(nonland) / TARGET_NONLAND))
    gaps = [_ROLE_LABELS[r] for r, floor in _ROLE_FLOORS.items()
            if role_counts[r] < floor]

    ci_str = "".join(sorted(ci, key="WUBRG".index)) if ci else "C"
    return {
        "commander": commander.get("name", ""),
        "color_identity": sorted(ci, key="WUBRG".index),
        "ci": ci_str,
        "buildable_pct": buildable_pct,
        "owned_nonland": len(nonland),
        "owned_lands": len(lands),
        "roles": role_counts,
        "gaps": gaps,
        "edhrec_rank": commander.get("edhrec_rank"),
        "image": (commander.get("image_uris") or {}).get("small")
                 or (commander.get("image_uris") or {}).get("normal") or "",
    }


def find_buildable(owned_names, client, limit: int = 8, min_pct: int = 25) -> dict:
    """Rank owned commanders by how completely a deck could be built from the
    collection. Returns {"commanders": [...], "scanned": n, "candidates": m}.

    `client` is a ScryfallClient (batch-resolves names). Local + fast; no simulation.
    """
    names = sorted(owned_names)
    if not names:
        return {"commanders": [], "scanned": 0, "candidates": 0}
    resolved = client.get_cards_collection(names)
    cards = [c for c in resolved.values() if c]
    candidates = [c for c in cards if is_commander_eligible(c)]

    scored = [score_commander(cmd, cards) for cmd in candidates]
    # Ranking for CASUAL B1–3 "fun, on-level decks you can build":
    #   1. complete decks first (enough cards + essential roles covered),
    #   2. then by commander POPULARITY (edhrec_rank) — a well-known commander is a
    #      coherent, pod-appropriate deck, unlike a 5-colour goodpile that trivially
    #      "fits" every owned card,
    #   3. then FOCUS (fewer colours) as a tiebreak toward tighter casual decks.
    # buildable_pct saturates at 100 for wide identities, so it's a gate, not the sort.
    def _complete(s):
        return s["buildable_pct"] >= 100 and not s["gaps"]
    scored.sort(key=lambda s: (
        0 if _complete(s) else 1,
        s["edhrec_rank"] or 10**9,
        len(s["color_identity"]),
        -s["owned_nonland"],
    ))
    top = [s for s in scored if s["buildable_pct"] >= min_pct][:limit]
    # Always return at least the single best candidate so the panel isn't empty when a
    # small collection is below the threshold.
    if not top and scored:
        top = scored[:1]
    return {"commanders": top, "scanned": len(cards), "candidates": len(candidates)}
