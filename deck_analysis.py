"""
Estimate an imported deck's Commander **bracket** and suggest how to scale it
up (more competitive) or down (more casual), using the same WotC bracket signals
the builder enforces (bracket.py): Game Changers, extra turns, mass land
destruction — plus fast-mana and tutor density and the mana curve.

This is a heuristic, not a verdict: 2-card infinite combos can't be detected
generically, so a deck flagged Bracket 3 here could be higher if it hides a
combo. The summary says so.
"""
from __future__ import annotations

from statistics import mean

from bracket import (
    GAME_CHANGERS, EXTRA_TURN_CARDS, MASS_LAND_DESTRUCTION_CARDS,
    BRACKET_LABELS, _EXTRA_TURN_PATTERNS, _MLD_PATTERNS,
)

# ── Extra signal sets ─────────────────────────────────────────────────────────
# "Fast mana" in the bracket sense — accelerants that produce mana above curve.
# (Signets/Talismans are ramp but NOT fast mana, so they're deliberately absent.)
FAST_MANA: frozenset[str] = frozenset({
    "Sol Ring", "Mana Crypt", "Mana Vault", "Grim Monolith", "Basalt Monolith",
    "Chrome Mox", "Mox Diamond", "Mox Opal", "Mox Amber", "Mox Tantalite",
    "Lotus Petal", "Lion's Eye Diamond", "Jeweled Lotus", "Lotus Field",
    "Dark Ritual", "Cabal Ritual", "Ancient Tomb", "City of Traitors",
    "Jeska's Will", "Black Lotus",
})

# Strong (non-land) tutors — detected by oracle pattern. Land tutors are ramp.
_TUTOR_PATTERNS = (
    "search your library for a card",
    "search your library for a creature card",
    "search your library for an instant or sorcery card",
    "search your library for an artifact card",
    "search your library for an enchantment card",
    "search your library for a planeswalker card",
    "search your library for up to",
)
_TUTOR_EXCLUDE = ("land card", "basic land", "for a forest", "for a plains",
                  "for an island", "for a swamp", "for a mountain")


def _name(c: dict) -> str:
    return c.get("name", "") or ""


def _oracle(c: dict) -> str:
    return (c.get("oracle_text") or "").lower()


def _is_land(c: dict) -> bool:
    return "land" in (c.get("type_line") or "").lower()


def _is_tutor(c: dict) -> bool:
    """True for a non-land 'power' tutor (Demonic Tutor, Mystical Tutor, …).
    Land tutors / land ramp (Cultivate, Rampant Growth) are excluded."""
    o = _oracle(c)
    if not any(p in o for p in _TUTOR_PATTERNS):
        return False
    # "search your library for up to two basic land cards" etc. is ramp, not a tutor.
    if any(x in o for x in _TUTOR_EXCLUDE) and "search your library for a card" not in o:
        return False
    return True


def _names_in(cards: list[dict], names: frozenset[str]) -> list[str]:
    out, seen = [], set()
    for c in cards:
        n = _name(c)
        if n in names and n not in seen:
            out.append(n); seen.add(n)
    return out


def analyze_deck(commander: dict | None, deck: list[dict]) -> dict:
    """Return a bracket estimate + signal breakdown + scale up/down suggestions."""
    cards = ([commander] if commander else []) + list(deck or [])
    nonland = [c for c in cards if not _is_land(c)]

    game_changers = _names_in(cards, GAME_CHANGERS)
    extra_turns = sorted({_name(c) for c in cards
                          if _name(c) in EXTRA_TURN_CARDS
                          or any(p in _oracle(c) for p in _EXTRA_TURN_PATTERNS)})
    mld = sorted({_name(c) for c in cards
                  if _name(c) in MASS_LAND_DESTRUCTION_CARDS
                  or any(p in _oracle(c) for p in _MLD_PATTERNS)})
    fast_mana = _names_in(cards, FAST_MANA)
    tutors = sorted({_name(c) for c in cards if _is_tutor(c)})

    mvs = [float(c.get("cmc") or 0) for c in nonland]
    avg_mv = round(mean(mvs), 2) if mvs else 0.0
    land_count = sum(int(c.get("quantity", 1) or 1) for c in cards if _is_land(c))

    gcn = len(game_changers)

    # ── Estimate the bracket ──────────────────────────────────────────────────
    # Game Changers are the primary lever (WotC's own quota): 0→1-2, 1-3→3, 4-6→4, 7+→5.
    if gcn == 0:
        est = 2
    elif gcn <= 3:
        est = 3
    elif gcn <= 6:
        est = 4
    else:
        est = 5
    # Category presence raises the floor (these are gated at low brackets).
    if extra_turns:
        est = max(est, 3)
    if mld:
        est = max(est, 4)
    # cEDH fingerprint: heavy fast mana + tutors + a very low curve.
    if est >= 4 and len(fast_mana) >= 3 and len(tutors) >= 4 and avg_mv <= 2.8:
        est = 5
    # Precon-level floor: nothing pushing power at all.
    low_end = (gcn == 0 and not extra_turns and not mld
               and len(fast_mana) <= 1 and len(tutors) == 0)
    est = max(1, min(5, est))

    label = BRACKET_LABELS.get(est, str(est))

    # ── Summary ───────────────────────────────────────────────────────────────
    bits = [f"{gcn} Game Changer{'s' if gcn != 1 else ''}"]
    if extra_turns: bits.append(f"{len(extra_turns)} extra-turn card(s)")
    if mld:         bits.append(f"{len(mld)} mass land destruction")
    bits.append(f"{len(fast_mana)} fast-mana, {len(tutors)} tutor(s)")
    bits.append(f"avg MV {avg_mv}")
    summary = (f"Estimated **Bracket {est} — {label}**: " + ", ".join(bits) + ". "
               + ("This looks like a precon-level casual deck. " if low_end and est <= 2 else "")
               + "Note: two-card infinite combos can't be auto-detected, so a hidden "
                 "combo could place this higher than shown.")

    # ── Suggestions ───────────────────────────────────────────────────────────
    up: list[str] = []
    if len(fast_mana) < 3:
        up.append("Add fast mana — e.g. Sol Ring, Mana Crypt, Mana Vault, Jeweled Lotus — to power out the commander earlier.")
    if len(tutors) < 3:
        up.append("Add tutors (Demonic Tutor, Vampiric Tutor, Mystical Tutor, Worldly Tutor) for consistency.")
    if gcn < 3:
        up.append("Add high-impact Game Changers in-color (Rhystic Study, Smothering Tithe, Cyclonic Rift, Fierce Guardianship).")
    if land_count and land_count >= 35:
        up.append("Upgrade the mana base — fetchlands + dual/shock lands and a few fast lands tighten the curve.")
    up.append("Add a compact, protected win condition (a 2-card combo or a resilient game-ender) so you can close before turn 8.")

    down: list[str] = []
    if game_changers:
        down.append("Game Changers cap your floor — cutting these lets you sit lower: "
                    + ", ".join(game_changers[:8]) + (" …" if len(game_changers) > 8 else "")
                    + " (0 allowed at Brackets 1–2, max 3 at Bracket 3).")
    if mld:
        down.append("Remove mass land destruction (allowed only at Bracket 4+): " + ", ".join(mld) + ".")
    if extra_turns:
        down.append("Remove extra-turn cards (banned at Brackets 1–2): " + ", ".join(extra_turns) + ".")
    if len(fast_mana) >= 2:
        down.append("Trim fast mana (" + ", ".join(fast_mana[:6]) + ") to slow the deck toward a more casual table.")
    if not down:
        down.append("Nothing is forcing the bracket up — this deck is already friendly for casual tables.")

    return {
        "estimated_bracket": est,
        "bracket_label": label,
        "summary": summary,
        "signals": {
            "game_changers": game_changers,
            "extra_turns": extra_turns,
            "mass_land_destruction": mld,
            "fast_mana": fast_mana,
            "tutors": tutors,
            "avg_mana_value": avg_mv,
            "land_count": land_count,
        },
        "scale_up": up,
        "scale_down": down,
    }
