"""
Core EDH deck builder.

Slot allocation (99 cards, commander is separate):
  Lands          36-38  (scales with commander mana value)
  Ramp           10
  Card Draw      10
  Removal         7     (single-target: exile, destroy, bounce, counter)
  Board Wipes     4
  Protection      3     (counterspells, hexproof/indestructible grants, boots)
  Theme Synergy  20     (cards that specifically support detected themes)
  Goodstuff       7     (format staples, flexible value)
  ─────────────  ──
  Total          99

All queries are run against the Scryfall /cards/search endpoint sorted by
EDHREC popularity so we get the most-played (i.e. community-vetted) options.
"""
from __future__ import annotations

from commander_analysis import CommanderProfile, THEME_SYNERGY_QUERIES
from scryfall_client import ScryfallClient
from bracket import BracketFilter, BRACKET_RULES, BRACKET_LABELS

# ── Color → basic land name ───────────────────────────────────────────────────
BASIC_LAND: dict[str, str] = {
    "W": "Plains",
    "U": "Island",
    "B": "Swamp",
    "R": "Mountain",
    "G": "Forest",
}

# Basic land Scryfall IDs (avoid re-searching for them repeatedly)
_BASIC_LAND_CACHE: dict[str, dict] = {}

# ── Functional role queries ───────────────────────────────────────────────────
# otag: (Oracle Tag) is a Scryfall community tagging system — great signal for
# role identification. We fall back to oracle text patterns when tags miss.

ROLE_QUERIES: dict[str, str] = {
    "ramp": (
        "(otag:ramp OR otag:land-ramp OR otag:mana-rock OR otag:mana-dork "
        "OR (o:\"add\" o:\"mana\" -type:land))"
    ),
    "card_draw": (
        "(otag:card-draw OR otag:draw OR o:\"draw a card\" "
        "OR o:\"draw two cards\" OR o:\"draw three cards\")"
    ),
    "removal": (
        "(otag:removal OR otag:targeted-removal "
        "OR (o:\"destroy target\" -type:land) "
        "OR (o:\"exile target\" -type:land) "
        "OR o:\"return target\" o:\"to its owner's hand\")"
    ),
    "board_wipe": (
        "(otag:board-wipe OR o:\"destroy all creatures\" "
        "OR o:\"exile all creatures\" OR o:\"all creatures get -\" "
        "OR o:\"deals damage to each creature\")"
    ),
    "protection": (
        "(o:\"hexproof\" OR o:\"indestructible\" OR o:\"ward\" "
        "OR otag:counterspell OR o:\"can't be countered\")"
    ),
}

# Non-basic land queries (sorted by power level / popularity tier)
NONBASIC_LAND_TIERS: list[tuple[str, str]] = [
    ("Command Tower",    '!"Command Tower"'),
    ("fetch",           "otag:fetchland"),
    ("shock",           "otag:shockland"),
    ("reveal_dual",     "otag:check-land"),        # Glacial Fortress etc.
    ("pain",            "otag:pain-land"),
    ("filter",          "otag:filter-land"),
    ("tri_cycle",       "otag:tri-land"),
    ("utility",         "otag:utility-land -type:basic"),
]

# Which land tiers are available at each bracket land_power level
# (Game-Changer lands like Ancient Tomb are handled by BracketFilter separately)
_LAND_TIERS_BY_POWER: dict[int, set[str]] = {
    1: {"Command Tower"},                                                           # basics + Command Tower only
    2: {"Command Tower", "reveal_dual", "tri_cycle"},                               # + check/tri lands
    3: {"Command Tower", "fetch", "shock", "reveal_dual", "pain", "filter", "tri_cycle"},  # standard
    4: {"Command Tower", "fetch", "shock", "reveal_dual", "pain", "filter", "tri_cycle", "utility"},  # full
}


class DeckBuilder:
    def __init__(self, client: ScryfallClient):
        self.client = client
        self._deck: list[dict] = []
        self._names: set[str] = set()
        self._commander_name: str = ""
        self._bracket_filter: BracketFilter = BracketFilter(3)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _ci_filter(self, profile: CommanderProfile) -> str:
        """Returns a Scryfall color-identity restriction fragment."""
        if profile.is_colorless:
            return "id:c"
        return f"id<={profile.color_id_str}"

    def _add(self, card: dict) -> bool:
        """Add a card if not already in deck, not the commander, and passes bracket rules."""
        name = card.get("name", "")
        if name and name not in self._names and name != self._commander_name:
            if not self._bracket_filter.allows(card):
                return False
            self._deck.append(card)
            self._names.add(name)
            return True
        return False

    def _fetch_role(self, profile: CommanderProfile, role: str, want: int) -> int:
        query = (
            f"{ROLE_QUERIES[role]} "
            f"{self._ci_filter(profile)} "
            f"legal:commander -type:land"
        )
        buf = self._bracket_filter.candidate_buffer(want)
        candidates = self.client.search_cards_paged(query, max_results=buf)
        added = 0
        for card in candidates:
            if added >= want:
                break
            if self._add(card):
                added += 1
        return added

    def _fetch_theme_synergy(self, profile: CommanderProfile, want: int) -> int:
        return self._fetch_theme_synergy_list(profile, profile.themes, want)

    def _fetch_theme_synergy_list(
        self, profile: CommanderProfile, themes: list[str], want: int
    ) -> int:
        """
        Pull synergy cards for the given theme list (up to 3 active themes).
        Distributes `want` slots proportionally across themes.
        """
        active = [t for t in themes if THEME_SYNERGY_QUERIES.get(t)][:3]
        if not active:
            return 0

        added = 0
        per_theme = max(1, want // len(active))
        remainder = want - (per_theme * len(active))

        for i, theme in enumerate(active):
            if added >= want:
                break
            synergy_q = THEME_SYNERGY_QUERIES[theme]
            slot = per_theme + (1 if i == 0 else 0) * remainder
            query = (
                f"{synergy_q} "
                f"{self._ci_filter(profile)} "
                f"legal:commander -type:land"
            )
            candidates = self.client.search_cards_paged(query, max_results=self._bracket_filter.candidate_buffer(slot))
            for card in candidates:
                if added >= want:
                    break
                if self._add(card):
                    added += 1
        return added

    def _fetch_goodstuff(self, profile: CommanderProfile, want: int) -> int:
        """
        EDHREC-sorted cards in color identity as a catch-all filler.
        Fetches enough candidates to go past whatever is already in the deck.
        """
        query = (
            f"{self._ci_filter(profile)} "
            f"legal:commander -type:land"
        )
        # Already-picked cards live at the top of the EDHREC ranking, so we
        # need to fetch past them. Buffer = current deck size + generous margin.
        candidates_needed = len(self._names) + self._bracket_filter.candidate_buffer(want)
        candidates = self.client.search_cards_paged(query, max_results=candidates_needed)
        added = 0
        for card in candidates:
            if added >= want:
                break
            if self._add(card):
                added += 1
        return added

    def _build_lands(self, profile: CommanderProfile, want: int) -> int:
        """
        Build a land base:
        1. Include Command Tower first (works in any multi-color deck).
        2. Pull non-basic duals/utility fitting color identity.
        3. Fill remainder with appropriately-distributed basic lands.
        """
        added = 0
        colors = profile.color_identity

        # ── Non-basics ────────────────────────────────────────────────────────
        # Leave a HEALTHY basic-land base. The old cap (want - len(colors)) let
        # duals/utility fill nearly every land slot, leaving only ~1 basic per
        # colour. Real manabases run plenty of basics, so cap nonbasics by colour
        # count (more colours need more fixing) and let basics fill the rest:
        #   1c≈9 · 2c≈14 · 3c≈19 · 4c≈24 · 5c≈29 nonbasics.
        nonbasic_target = 4 + len(colors) * 5
        nonbasic_cap = max(0, min(want - len(colors), nonbasic_target))
        allowed_tiers = _LAND_TIERS_BY_POWER.get(self._bracket_filter.rules.land_power, _LAND_TIERS_BY_POWER[4])

        for _label, land_q in NONBASIC_LAND_TIERS:
            if added >= nonbasic_cap:
                break
            if _label not in allowed_tiers:
                continue
            query = f"{land_q} {self._ci_filter(profile)} legal:commander"
            candidates = self.client.search_cards_paged(query, max_results=15)
            for card in candidates:
                if added >= nonbasic_cap:
                    break
                if self._add(card):
                    added += 1

        # ── Basics ────────────────────────────────────────────────────────────
        basic_slots = want - added
        if not colors:
            # Colorless commanders use Wastes
            wastes_q = '!"Wastes" type:basic'
            result = self.client.search_cards(wastes_q)
            wastes = result.get("data", [])
            if wastes:
                for _ in range(basic_slots):
                    self._deck.append(wastes[0])
                    added += 1
            return added

        per_color = basic_slots // len(colors)
        extra = basic_slots % len(colors)

        for idx, color in enumerate(colors):
            land_name = BASIC_LAND.get(color)
            if not land_name:
                continue

            if land_name not in _BASIC_LAND_CACHE:
                result = self.client.search_cards(f'!"{land_name}"')
                data = result.get("data", [])
                if data:
                    _BASIC_LAND_CACHE[land_name] = data[0]

            basic = _BASIC_LAND_CACHE.get(land_name)
            if not basic:
                continue

            count = per_color + (1 if idx < extra else 0)
            for _ in range(count):
                self._deck.append(basic)
                added += 1

        return added

    # ── Public API ────────────────────────────────────────────────────────────

    def build(
        self,
        profile: CommanderProfile,
        theme_override: list[str] | None = None,
        slot_overrides: dict[str, int] | None = None,
        playstyle_label: str = "Auto",
        bracket: int = 3,
    ) -> list[dict]:
        """
        Build the 99-card deck.

        Args:
            profile:          Commander profile from commander_analysis.
            theme_override:   If provided, replaces profile.themes for
                              synergy card selection (from playstyle.resolve_themes).
            slot_overrides:   Per-role slot count overrides from playstyle
                              (e.g. control bumps removal to 10).
            playstyle_label:  Display name for the chosen playstyle.
        """
        self._deck = []
        self._names = set()
        self._commander_name = profile.name
        self._bracket_filter = BracketFilter(bracket)

        # Use overridden themes for synergy fetching, fall back to auto-detected
        active_themes = theme_override if theme_override is not None else profile.themes

        # ── Slot plan ─────────────────────────────────────────────────────────
        if profile.mana_value <= 3:
            land_count = 36
        elif profile.mana_value <= 5:
            land_count = 37
        else:
            land_count = 38

        # Green elf/landfall decks can shave a land
        if "G" in profile.color_identity and any(
            t in active_themes for t in ("tribal_elves", "landfall")
        ):
            land_count = max(land_count - 1, 35)

        # Landfall playstyle explicitly bumps land count
        if slot_overrides and "lands" in slot_overrides:
            land_count = slot_overrides["lands"]

        plan: dict[str, int] = {
            "lands":      land_count,
            "ramp":       (slot_overrides or {}).get("ramp", 10),
            "card_draw":  (slot_overrides or {}).get("card_draw", 10),
            "removal":    (slot_overrides or {}).get("removal", 7),
            "board_wipe": (slot_overrides or {}).get("board_wipe", 4),
            "protection": (slot_overrides or {}).get("protection", 3),
            "theme":      20,
        }
        used = sum(plan.values())
        plan["goodstuff"] = 99 - used

        # Snapshot active_themes into the lambda closures correctly
        _active = active_themes

        steps: list[tuple[str, object]] = [
            ("Lands",          lambda: self._build_lands(profile, plan["lands"])),
            ("Ramp",           lambda: self._fetch_role(profile, "ramp", plan["ramp"])),
            ("Card draw",      lambda: self._fetch_role(profile, "card_draw", plan["card_draw"])),
            ("Removal",        lambda: self._fetch_role(profile, "removal", plan["removal"])),
            ("Board wipes",    lambda: self._fetch_role(profile, "board_wipe", plan["board_wipe"])),
            ("Protection",     lambda: self._fetch_role(profile, "protection", plan["protection"])),
            ("Theme synergy",  lambda: self._fetch_theme_synergy_list(profile, _active, plan["theme"])),
            ("Goodstuff fill", lambda: self._fetch_goodstuff(profile, plan["goodstuff"])),
        ]

        # Bracket 5 (cEDH): lean heavier on draw/interaction, lighter on theme
        if bracket == 5:
            plan["card_draw"]  = plan.get("card_draw", 10) + 4
            plan["protection"] = plan.get("protection", 3) + 3
            plan["theme"]      = max(8, plan.get("theme", 20) - 7)
            used = sum(v for k, v in plan.items() if k != "goodstuff")
            plan["goodstuff"] = 99 - used

        # Bracket 1 (Exhibition): more theme, less raw goodstuff
        if bracket == 1:
            plan["theme"]     = plan.get("theme", 20) + 5
            used = sum(v for k, v in plan.items() if k != "goodstuff")
            plan["goodstuff"] = max(2, 99 - used)

        from commander_analysis import THEME_LABELS
        active_labels = [THEME_LABELS.get(t, t) for t in active_themes] or ["Goodstuff / Midrange"]
        bracket_label = BRACKET_LABELS.get(bracket, str(bracket))
        gc_limit_str  = str(self._bracket_filter.gc_limit) if self._bracket_filter.gc_limit >= 0 else "unlimited"

        print(f"\n  Building 99-card deck for {profile.name}")
        print(f"  Color identity : {profile.color_id_str or 'Colorless'}")
        print(f"  Playstyle      : {playstyle_label}")
        print(f"  Bracket        : {bracket} — {bracket_label}  (Game Changers: {gc_limit_str})")
        print(f"  Active themes  : {', '.join(active_labels)}")
        print(f"  Commander MV   : {int(profile.mana_value)}")
        print(f"  Land target    : {plan['lands']}\n")

        for label, fn in steps:
            n = fn()
            print(f"  [{label:<18}] {n:>2} cards   (running total: {len(self._deck)})")

        # Pad if Scryfall returned fewer results than planned
        shortfall = 99 - len(self._deck)
        if shortfall > 0:
            print(f"\n  Padding {shortfall} missing slots with goodstuff...")
            self._fetch_goodstuff(profile, shortfall)

        return self._deck[:99]


# ── Deck stats ────────────────────────────────────────────────────────────────

def aggregate_duplicates(deck: list[dict]) -> list[dict]:
    """Collapse same-name cards into one entry carrying a 'quantity' (basic lands
    are added as repeated copies). The pipeline then themes/renders each unique
    card once; the exporter replicates by quantity. Preserves first-seen order."""
    agg: dict[str, dict] = {}
    order: list[str] = []
    for c in deck:
        name = c.get("name") or c.get("original_name") or ""
        if name not in agg:
            entry = dict(c)
            entry["quantity"] = 0
            agg[name] = entry
            order.append(name)
        agg[name]["quantity"] += int(c.get("quantity", 1) or 1)
    return [agg[n] for n in order]


def compute_stats(commander: dict, deck: list[dict]) -> dict:
    non_lands = [c for c in deck if "land" not in c.get("type_line", "").lower()]
    avg_cmc = (
        sum(c.get("cmc", 0) for c in non_lands) / len(non_lands) if non_lands else 0
    )

    color_pips: dict[str, int] = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    for card in deck + [commander]:
        mc = card.get("mana_cost") or ""
        for pip, letter in [("{W}", "W"), ("{U}", "U"), ("{B}", "B"),
                             ("{R}", "R"), ("{G}", "G"), ("{C}", "C")]:
            color_pips[letter] += mc.count(pip)

    type_counts: dict[str, int] = {}
    for card in deck:
        tl = card.get("type_line", "")
        qty = int(card.get("quantity", 1) or 1)   # imported decks aggregate basics
        for t in ["Land", "Creature", "Artifact", "Enchantment",
                  "Instant", "Sorcery", "Planeswalker", "Battle"]:
            if t in tl:
                type_counts[t] = type_counts.get(t, 0) + qty
                break

    cmc_curve: dict[int, int] = {}
    for card in non_lands:
        mv = int(card.get("cmc", 0))
        cmc_curve[mv] = cmc_curve.get(mv, 0) + 1

    # total counts every physical copy (quantity>1 for imported duplicate basics)
    deck_total = sum(int(c.get("quantity", 1) or 1) for c in deck)
    return {
        "average_cmc": round(avg_cmc, 2),
        "color_pips": {k: v for k, v in color_pips.items() if v},
        "type_counts": type_counts,
        "cmc_curve": dict(sorted(cmc_curve.items())),
        "land_count": type_counts.get("Land", 0),
        "total_cards": deck_total + 1,  # +1 for commander
    }
