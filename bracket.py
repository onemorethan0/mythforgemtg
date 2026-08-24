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
import re
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
#
# FALLBACK ONLY as of 2026-08-24 — do not treat this as the source of truth. Scryfall
# ships a live `game_changer` boolean on every card object (confirmed present on both
# /cards/named and /cards/search, i.e. every card `_add_card` ever sees), refreshed by
# WotC updates with no redeploy needed here — the same field the engine's own
# `data/scryfall.py` already reads as authoritative, with a hard schema-version error so
# it can never go silently stale (see CLAUDE.md). `BracketFilter.allows()` below prefers
# that live field and only falls back to this frozenset when a card dict lacks the key
# entirely (synthetic/offline card data). This set existed as the SOLE mechanism until
# then, with no staleness check — exactly the two-authorities-drift problem the engine
# merge was supposed to end (root bracket.py vs `ratings/bracket.py` computing the same
# official quota two different ways). It also already carried a real bug from being a
# bare name string: some printings of Tergrid report as
# "Tergrid, God of Fright // Tergrid's Lantern" from Scryfall, which this frozenset (front
# face only) would silently miss — the live boolean has no such failure mode.
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

# Oracle text patterns — catches reprints and new cards with the same effects.
#
# Ported from `mythgauntlet/ratings/bracket.py`'s `_MLD_RES` (Forge cannot import the
# engine package — separate process, see CLAUDE.md — so this is a deliberate duplicate,
# kept byte-for-byte identical on purpose). That version was validated 2026-08-07 against
# all 34,179 cards in the engine's card store after the naive version (a plain substring
# check, which is what this file had until 2026-08-24) proved wrong in both directions:
# it fabricated mass-land-denial on ordinary wraths whose text merely contained "nonland"
# or a single-land sacrifice ("each player destroys all" with no object gate matches
# "each player destroys all artifacts" just as readily as "...all lands"), and it MISSED
# real mass-land-denial cards that don't use the literal string "destroy all lands"
# (Jokulhaups, Obliterate, Devastation, ...). The two guards below are load-bearing:
# \b around land/lands stops "nonland" matching, and (?!except) stops a sweeper that
# explicitly SPARES lands (Scourglass: "destroy all permanents except ... and lands").
_EXTRA_TURN_RE = re.compile(r"take an extra turn|extra turn after this one", re.IGNORECASE)
_MLD_RES = (
    re.compile(r"\b(?:destroy|exile) all\b(?:(?!except)[^.])*?\blands\b", re.IGNORECASE),
    re.compile(r"\beach (?:player|opponent)\b[^.]*?\bsacrifices?\b[^.]*?\blands\b", re.IGNORECASE),
    re.compile(r"\beach (?:player|opponent)\b[^.]*?\bsacrifices?\b[^.]*?\bland\b[^.]*?\bfor each\b", re.IGNORECASE),
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
        oracle = card.get("oracle_text") or ""

        # Game Changers quota. Prefer Scryfall's own live `game_changer` field (present
        # on every card this method has ever been called with in practice — both
        # /cards/named and /cards/search return it) and fall back to the frozenset only
        # when a card dict genuinely lacks the key (synthetic/offline data). `.get()`
        # returning None means "absent", not "false" — a card actually flagged False
        # must not fall through to a stale name-list lookup.
        gc_field = card.get("game_changer")
        is_game_changer = gc_field if gc_field is not None else (name in GAME_CHANGERS)
        if is_game_changer:
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
            if _EXTRA_TURN_RE.search(oracle):
                return False

        # Mass land destruction restriction (Brackets 1–3)
        if not self.rules.allow_mld:
            if name in MASS_LAND_DESTRUCTION_CARDS:
                return False
            if any(r.search(oracle) for r in _MLD_RES):
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
