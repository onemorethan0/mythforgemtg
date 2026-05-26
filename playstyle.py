"""
Playstyle selection and injection.

Maps user-facing playstyle labels to the internal theme keys used by
commander_analysis.py. When a user picks a playstyle it either overrides
or supplements what was auto-detected from the commander's oracle text.
"""
from commander_analysis import THEME_LABELS

# ── Available playstyles ──────────────────────────────────────────────────────

PLAYSTYLES: dict[str, dict] = {
    "auto": {
        "label": "Auto (let the commander decide)",
        "themes": [],        # no override — use commander_analysis output
        "description": "Deck strategy is derived entirely from the commander's abilities.",
    },
    "lifegain": {
        "label": "Lifegain",
        "themes": ["lifegain"],
        "description": "Gain massive life totals and leverage them as a resource.",
    },
    "spellslinger": {
        "label": "Spellslinger",
        "themes": ["spellslinger"],
        "description": "Cast instants and sorceries for value, triggers, and win conditions.",
    },
    "recursion": {
        "label": "Recursion / Graveyard",
        "themes": ["reanimator", "graveyard"],
        "description": "Fill the graveyard and recycle threats repeatedly.",
    },
    "tokens": {
        "label": "Tokens / Go-Wide",
        "themes": ["tokens"],
        "description": "Flood the board with tokens and overwhelm through sheer numbers.",
    },
    "counters": {
        "label": "Counters / Proliferate",
        "themes": ["counters"],
        "description": "Stack +1/+1 counters, loyalty counters, and proliferate everything.",
    },
    "voltron": {
        "label": "Voltron / Equipment",
        "themes": ["voltron", "voltron_combat"],
        "description": "Suit up one massive creature and kill with commander damage.",
    },
    "aristocrats": {
        "label": "Aristocrats / Sacrifice",
        "themes": ["aristocrats", "tokens"],
        "description": "Sacrifice creatures for triggers, drain opponents, and loop resources.",
    },
    "control": {
        "label": "Control",
        "themes": [],
        "role_adjustments": {"removal": 10, "board_wipe": 6, "card_draw": 12, "protection": 5},
        "description": "Answer every threat, draw into win conditions, grind opponents out.",
    },
    "combo": {
        "label": "Combo",
        "themes": [],
        "role_adjustments": {"card_draw": 12, "protection": 6, "ramp": 12},
        "description": "Find and assemble a two- or three-card infinite combo to win.",
    },
    "aggro": {
        "label": "Aggro / Combat",
        "themes": ["voltron_combat", "tokens"],
        "role_adjustments": {"removal": 9, "ramp": 8},
        "description": "Attack early, attack often, close games before opponents stabilize.",
    },
    "midrange": {
        "label": "Midrange / Goodstuff",
        "themes": [],
        "description": "Efficient threats and answers, no single synergy dependency.",
    },
    "etb": {
        "label": "ETB / Flicker",
        "themes": ["etb"],
        "description": "Blink and recur creatures with enter-the-battlefield triggers.",
    },
    "landfall": {
        "label": "Landfall",
        "themes": ["landfall"],
        "role_adjustments": {"ramp": 14, "lands": 40},
        "description": "Play extra lands each turn and trigger landfall payoffs repeatedly.",
    },
    "tribal": {
        "label": "Tribal (auto-detect from commander)",
        "themes": [],   # tribal theme detected from commander type line
        "description": "Fill the deck with creatures sharing a creature type for synergy lords.",
    },
}

# Canonical display order
PLAYSTYLE_ORDER = [
    "auto", "aggro", "midrange", "control", "combo",
    "lifegain", "spellslinger", "recursion", "tokens",
    "counters", "voltron", "aristocrats", "etb", "landfall", "tribal",
]


# ── Slot plan adjustments ─────────────────────────────────────────────────────

DEFAULT_SLOTS = {
    "ramp":       10,
    "card_draw":  10,
    "removal":     7,
    "board_wipe":  4,
    "protection":  3,
    "theme":      20,
}

def get_slot_adjustments(playstyle_key: str) -> dict[str, int]:
    """Return per-slot overrides for a given playstyle, merged with defaults."""
    ps = PLAYSTYLES.get(playstyle_key, PLAYSTYLES["auto"])
    overrides = ps.get("role_adjustments", {})
    result = dict(DEFAULT_SLOTS)
    result.update(overrides)
    return result


# ── Theme resolution ──────────────────────────────────────────────────────────

def resolve_themes(
    playstyle_key: str,
    commander_themes: list[str],
) -> list[str]:
    """
    Merge playstyle-forced themes with auto-detected commander themes.
    Playstyle themes take priority (placed first) but commander themes
    that don't conflict are kept for synergy card selection.
    """
    # Tribal: strip to only creature-type themes from the commander
    if playstyle_key == "tribal":
        tribal_themes = [t for t in commander_themes if t.startswith("tribal_")]
        return tribal_themes if tribal_themes else commander_themes

    ps = PLAYSTYLES.get(playstyle_key, PLAYSTYLES["auto"])
    forced = ps.get("themes", [])

    if not forced:
        # "auto", "control", "combo", "midrange" — keep commander themes unchanged
        return commander_themes

    # Merge: forced themes first, then non-conflicting commander themes
    merged = list(forced)
    for t in commander_themes:
        if t not in merged:
            merged.append(t)
    return merged


# ── CLI prompt ────────────────────────────────────────────────────────────────

def prompt_playstyle() -> str:
    """Interactive playstyle picker. Returns a playstyle key."""
    print("\n  Playstyle (optional — press Enter to auto-detect from commander):")
    for i, key in enumerate(PLAYSTYLE_ORDER, 1):
        ps = PLAYSTYLES[key]
        print(f"    {i:>2}. {ps['label']}")

    raw = input("\n  Select [1-15] or Enter to skip: ").strip()
    if not raw:
        return "auto"
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(PLAYSTYLE_ORDER):
            chosen = PLAYSTYLE_ORDER[idx]
            print(f"  → {PLAYSTYLES[chosen]['label']}: {PLAYSTYLES[chosen]['description']}")
            return chosen
    except ValueError:
        pass
    print("  Invalid selection, defaulting to Auto.")
    return "auto"
