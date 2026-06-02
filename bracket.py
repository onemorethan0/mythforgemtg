"""
Official WotC Commander Bracket system (February 2026 rules).

Brackets define power level and restrict specific categories of cards:
  1 — Exhibition : 0 Game Changers, no extra turns, no MLD, no infinite combos
  2 — Core       : 0 Game Changers, no extra turns, no MLD, no infinite combos
  3 — Upgraded   : ≤3 Game Changers, no MLD (most common casual bracket)
  4 — Optimized  : Unlimited Game Changers, MLD/combos allowed
  5 — cEDH       : No restrictions beyond the official ban list
"""
from __future__ import annotations
from dataclasses import dataclass

# ── Bracket metadata ──────────────────────────────────────────────────────────

BRACKET_LABELS = {
    1: "Exhibition",
    2: "Core",
    3: "Upgraded",
    4: "Optimized",
    5: "cEDH",
}

BRACKET_DESCRIPTIONS = {
    1: "Theme-focused, precon power. No staples, no combos. Pure creativity.",
    2: "Casual play. Solid synergies, no format-warping effects or fast mana.",
    3: "Most popular bracket. Strong synergies and up to 3 Game Changers — a well-rounded, competitive casual deck.",
    4: "High-powered: fast mana, tutors, and combos are allowed. The engine builds a strong goodstuff/value list; add your own combo lines to fully optimize.",
    5: "Maximum power, no restrictions. The engine builds a high-power goodstuff list with extra draw + interaction — a tuned tournament cEDH combo deck still needs hand-crafting.",
}

# ── Official Game Changers list (February 9, 2026 — 53 cards) ─────────────────
# These cards are legal but count toward each bracket's quota.
GAME_CHANGERS: frozenset[str] = frozenset({
    # White
    "Drannith Magistrate", "Enlightened Tutor", "Farewell", "Humility",
    "Serra's Sanctum", "Smothering Tithe", "Teferi's Protection",
    # Blue
    "Consecrated Sphinx", "Cyclonic Rift", "Force of Will", "Fierce Guardianship",
    "Gifts Ungiven", "Intuition", "Mystical Tutor", "Narset, Parter of Veils",
    "Rhystic Study",
    # Black
    "Ad Nauseam", "Bolas's Citadel", "Braids, Cabal Minion", "Demonic Tutor",
    "Imperial Seal", "Necropotence", "Opposition Agent", "Orcish Bowmasters",
    "Tergrid, God of Fright", "Vampiric Tutor",
    # Red
    "Gamble", "Jeska's Will", "Underworld Breach",
    # Green
    "Biorhythm", "Crop Rotation", "Natural Order", "Seedborn Muse",
    "Survival of the Fittest", "Worldly Tutor",
    # Multicolor
    "Aura Shards", "Coalition Victory", "Grand Arbiter Augustin IV", "Notion Thief",
    # Colorless / Lands
    "Ancient Tomb", "Chrome Mox", "Field of the Dead", "Gaea's Cradle",
    "Glacial Chasm", "Grim Monolith", "Lion's Eye Diamond", "Mana Vault",
    "Mishra's Workshop", "Mox Diamond", "Panoptic Mirror", "The One Ring",
    "The Tabernacle at Pendrell Vale", "Thassa's Oracle",
})

# ── Extra turn cards (banned at Brackets 1–2) ─────────────────────────────────
EXTRA_TURN_CARDS: frozenset[str] = frozenset({
    "Time Walk", "Temporal Manipulation", "Time Warp", "Temporal Mastery",
    "Capture of Jingzhou", "Savor the Moment", "Walk the Aeons",
    "Part the Waterveil", "Alrund's Epiphany", "Nexus of Fate",
    "Karn's Temporal Sundering", "Beacon of Tomorrows", "Expropriate",
    "Notorious Throng", "Magistrate's Scepter", "Medomai the Ageless",
    "Lighthouse Chronologist", "Emrakul, the Promised End",
})

# ── Mass land destruction (banned at Brackets 1–3) ────────────────────────────
MASS_LAND_DESTRUCTION_CARDS: frozenset[str] = frozenset({
    "Armageddon", "Ravages of War", "Decree of Annihilation", "Catastrophe",
    "Cataclysm", "Fall of the Thran", "Jokulhaups", "Obliterate", "Wildfire",
    "Devastation", "Keldon Firebombers", "Sunder", "Impending Disaster",
    "Ruination", "Bend or Break",
})

# Oracle text patterns — catches reprints and new cards with the same effects
_EXTRA_TURN_PATTERNS  = ("take an extra turn", "takes an extra turn")
_MLD_PATTERNS         = (
    "destroy all lands",
    "each player sacrifices all lands",
    "destroy all nonbasic lands",
    "each player destroys all",
)


# ── Bracket rules ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BracketRules:
    bracket:               int
    label:                 str
    description:           str
    max_game_changers:     int    # -1 = unlimited
    allow_extra_turns:     bool
    allow_mld:             bool
    # Land tier index: controls which non-basic land types are included
    # 1=basics+Command Tower only, 2=+check lands, 3=standard, 4=full power
    land_power:            int
    # Candidate buffer multiplier for Scryfall searches
    # Lower brackets need bigger buffers because top-ranked cards are often filtered
    search_buffer:         int


BRACKET_RULES: dict[int, BracketRules] = {
    1: BracketRules(
        bracket=1, label="Exhibition", description=BRACKET_DESCRIPTIONS[1],
        max_game_changers=0, allow_extra_turns=False, allow_mld=False,
        land_power=1, search_buffer=12,
    ),
    2: BracketRules(
        bracket=2, label="Core", description=BRACKET_DESCRIPTIONS[2],
        max_game_changers=0, allow_extra_turns=False, allow_mld=False,
        land_power=2, search_buffer=8,
    ),
    3: BracketRules(
        bracket=3, label="Upgraded", description=BRACKET_DESCRIPTIONS[3],
        max_game_changers=3, allow_extra_turns=True, allow_mld=False,
        land_power=3, search_buffer=6,
    ),
    4: BracketRules(
        bracket=4, label="Optimized", description=BRACKET_DESCRIPTIONS[4],
        max_game_changers=-1, allow_extra_turns=True, allow_mld=True,
        land_power=4, search_buffer=4,
    ),
    5: BracketRules(
        bracket=5, label="cEDH", description=BRACKET_DESCRIPTIONS[5],
        max_game_changers=-1, allow_extra_turns=True, allow_mld=True,
        land_power=4, search_buffer=4,
    ),
}


# ── Stateful filter ───────────────────────────────────────────────────────────

class BracketFilter:
    """
    Enforces bracket rules on individual cards.
    Stateful: tracks how many Game Changers have been accepted so far.
    """

    def __init__(self, bracket: int = 3):
        self.rules = BRACKET_RULES.get(bracket, BRACKET_RULES[3])
        self._gc_used = 0

    # ── Public ────────────────────────────────────────────────────────────────

    def allows(self, card: dict) -> bool:
        """Return True if this card is permitted under the current bracket."""
        name   = card.get("name", "")
        oracle = (card.get("oracle_text") or "").lower()

        # Game Changers quota
        if name in GAME_CHANGERS:
            if self.rules.max_game_changers == -1:
                self._gc_used += 1
                return True
            if self._gc_used < self.rules.max_game_changers:
                self._gc_used += 1
                return True
            return False  # quota full

        # Extra turn restriction (Brackets 1–2)
        if not self.rules.allow_extra_turns:
            if name in EXTRA_TURN_CARDS:
                return False
            if any(p in oracle for p in _EXTRA_TURN_PATTERNS):
                return False

        # Mass land destruction restriction (Brackets 1–3)
        if not self.rules.allow_mld:
            if name in MASS_LAND_DESTRUCTION_CARDS:
                return False
            if any(p in oracle for p in _MLD_PATTERNS):
                return False

        return True

    def candidate_buffer(self, want: int) -> int:
        return want * self.rules.search_buffer

    @property
    def gc_used(self) -> int:
        return self._gc_used

    @property
    def gc_limit(self) -> int:
        return self.rules.max_game_changers
