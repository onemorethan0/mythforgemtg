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
from collection import owned_key

# ── Color → basic land name ───────────────────────────────────────────────────
BASIC_LAND: dict[str, str] = {
    "W": "Plains",
    "U": "Island",
    "B": "Swamp",
    "R": "Mountain",
    "G": "Forest",
}

# Resolved basic-land card objects, cached to avoid re-searching them.
_BASIC_LAND_CACHE: dict[str, dict] = {}

# Color symbol each basic taps for (for the offline synthetic fallback).
_BASIC_MANA: dict[str, str] = {
    "Plains": "W", "Island": "U", "Swamp": "B", "Mountain": "R", "Forest": "G",
}


def _synthetic_basic(land_name: str) -> dict:
    """A minimal, network-free basic-land card. Used ONLY as the absolute last
    resort in DeckBuilder._pad_with_basics when Scryfall can't be reached at all,
    so a build can still produce a legal 99-card deck. Carries just enough for
    stats / render / export to treat it as an ordinary basic (no art — the image
    pipeline degrades gracefully when Scryfall is unavailable anyway)."""
    sym = _BASIC_MANA.get(land_name, "C")
    subtype = "" if land_name == "Wastes" else f" — {land_name}"
    return {
        "name": land_name,
        "type_line": f"Basic Land{subtype}",
        "mana_cost": "",
        "cmc": 0.0,
        "oracle_text": f"({{T}}: Add {{{sym}}}.)",
        "colors": [],
        "color_identity": [] if sym == "C" else [sym],
        "produced_mana": [sym],
        "rarity": "common",
        "_synthetic": True,
    }

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
    # Game-closers so every deck has a reliable way to actually WIN, rather than
    # relying on goodstuff to happen to include one: mass pump/overrun, extra
    # combats, alt-win-cons, and group-drain payoffs.
    "finisher": (
        "(o:\"win the game\" OR o:\"wins the game\" OR o:\"loses the game\" "
        "OR o:\"additional combat phase\" OR o:\"an additional combat\" "
        "OR (o:\"creatures you control get +\" o:\"trample\") "
        "OR o:\"creatures you control gain trample\" "
        "OR o:\"deals that much damage to each opponent\")"
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


# ── Card source modes ─────────────────────────────────────────────────────────
# Which pool the builder may draft from. `prefer_collection` is the original
# use_collection=True behaviour, kept under its own name so the flag's meaning never
# silently changed under existing callers.
SOURCE_SCRYFALL   = "scryfall"           # ignore the collection entirely (default)
SOURCE_PREFER     = "prefer_collection"  # owned first, Scryfall staples fill the gaps
SOURCE_COLLECTION = "collection"         # STRICT: owned cards + basics, nothing else
CARD_SOURCES = (SOURCE_SCRYFALL, SOURCE_PREFER, SOURCE_COLLECTION)

# deck_builder's slot names -> collection_pool's role names. The two vocabularies
# differ ("card_draw" vs "draw"); mapping in one place keeps them from drifting.
_POOL_ROLE = {
    "ramp": "ramp", "card_draw": "draw", "removal": "removal",
    "board_wipe": "wipe", "protection": "protection", "finisher": "finisher",
}


class DeckBuilder:
    def __init__(self, client: ScryfallClient):
        self.client = client
        self._deck: list[dict] = []
        self._names: set[str] = set()
        self._commander_name: str = ""
        self._bracket_filter: BracketFilter = BracketFilter(3)
        self._owned: set[str] = set()   # normalized owned names; empty = collection off
        self._owned_cards: list[dict] = []  # resolved, CI/legal-eligible owned cards (C4)
        self._card_source: str = SOURCE_SCRYFALL
        self._pool = None               # collection_pool.CardPool in strict mode
        self.shortfall: dict[str, int] = {}   # strict mode: roles the collection can't fill

    # ── Internal helpers ──────────────────────────────────────────────────────
    # Note: collection-aware building draws owned cards from an EXPLICIT resolve
    # (_resolve_owned_cards) seeded into the flexible slots, not by widening every
    # role window — that keeps a "build from my collection" run as fast as a normal one.

    def _resolve_owned_cards(self, profile: CommanderProfile) -> list[dict]:
        """Resolve owned names to card data and keep the ones that fit this deck.

        Eligible = in the commander's colour identity, Commander-legal, not a basic land.
        Sorted by EDHREC rank so the best owned cards fill the flexible slots first. This is
        what makes "build from my collection" pull in owned cards the EDHREC-ranked role
        windows would never surface (a niche card ranked past the candidate buffer)."""
        if not self._owned:
            return []
        try:
            resolved = self.client.get_cards_collection(sorted(self._owned))
        except Exception:      # noqa: BLE001 - a Scryfall hiccup just disables the explicit fill
            return []
        ci = set(profile.color_identity)
        out: list[dict] = []
        for card in resolved.values():
            tl = (card.get("type_line", "") or "").lower()
            if "basic" in tl and "land" in tl:
                continue                                   # basics aren't "collection" cards
            card_ci = set(card.get("color_identity", []))
            if profile.is_colorless:
                if card_ci:
                    continue                               # colorless commander: colorless only
            elif not card_ci <= ci:
                continue                                   # outside the commander's identity
            if (card.get("legalities", {}) or {}).get("commander") != "legal":
                continue
            out.append(card)
        out.sort(key=lambda c: c.get("edhrec_rank") or 10**9)
        return out

    def _owned_candidates(self, creatures_only: bool = False) -> list[dict]:
        """Eligible owned cards to seed a flexible slot (optionally only creatures)."""
        if not creatures_only:
            return list(self._owned_cards)
        return [
            c for c in self._owned_cards
            if "creature" in (c.get("type_line", "") or "").lower()
            and "land" not in (c.get("type_line", "") or "").lower()
        ]

    def _prefer_owned(self, candidates: list[dict]) -> list[dict]:
        """Reorder EDHREC-ranked candidates so cards the user OWNS come first.

        Collection-aware building (Myth Suite C4): a stable partition keeps each group in
        its original EDHREC order, so owned cards are drafted first and unowned high-value
        cards still fill the gaps when the collection can't cover a slot. No-op when the
        collection is off/empty, so a normal build is byte-for-byte unchanged.
        """
        if not self._owned:
            return candidates
        owned, rest = [], []
        for card in candidates:
            (owned if owned_key(card.get("name", "")) in self._owned else rest).append(card)
        return owned + rest

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

    def _strict(self) -> bool:
        """Strict collection mode: no Scryfall SEARCH is available, only the owned pool.

        Name RESOLUTION still goes to Scryfall (and is cached) — that turns owned names
        into card data, it doesn't discover new cards."""
        return self._card_source == SOURCE_COLLECTION and self._pool is not None

    def _fetch_role(self, profile: CommanderProfile, role: str, want: int) -> int:
        if self._strict():
            # collection_pool has already classified and EDHREC-ordered the owned pool.
            added = 0
            for card in self._pool.roles.get(_POOL_ROLE[role], []):
                if added >= want:
                    break
                if self._add(card):
                    added += 1
            if added < want:
                self.shortfall[role] = self.shortfall.get(role, 0) + (want - added)
            return added

        query = (
            f"{ROLE_QUERIES[role]} "
            f"{self._ci_filter(profile)} "
            f"legal:commander -type:land"
        )
        buf = self._bracket_filter.candidate_buffer(want)
        candidates = self._prefer_owned(self.client.search_cards_paged(query, max_results=buf))
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
        # Theme synergy is a Scryfall SEARCH by construction, so strict mode has no way
        # to run it. Returning 0 hands those slots to the goodstuff fill, which draws
        # from the same owned pool — the deck stays 99 cards, it just isn't theme-tuned.
        if self._strict():
            self.shortfall["theme"] = self.shortfall.get("theme", 0) + want
            return 0

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
            candidates = self._prefer_owned(self.client.search_cards_paged(
                query, max_results=self._bracket_filter.candidate_buffer(slot)))
            for card in candidates:
                if added >= want:
                    break
                if self._add(card):
                    added += 1
        return added

    # Lead archetypes that need a creature base but whose synergy query isn't
    # creature-centric → (theme-package cap, creature floor). See build().
    _FLOOR_PLAN: dict[str, tuple[int, int]] = {
        "voltron":     (10, 20), "auras":       (10, 20),
        "artifacts":   (10, 20), "enchantress": (10, 20),
        "aristocrats": (15, 22), "reanimator":  (15, 18),
    }

    @staticmethod
    def _is_aggro_theme(t: str | None) -> bool:
        """A theme that already fields a wide board via the aggro bias (so it
        never wants a creature floor): any tribe, tokens, or combat/evasion."""
        return bool(t) and (t.startswith("tribal_") or t in {"tokens", "voltron_combat"})

    @classmethod
    def _creature_floor_plan(cls, active_themes: list[str]) -> tuple[int | None, int]:
        """Decide (theme_cap, creature_floor) for a build from its themes.

        theme_cap is None → leave the theme slot count as planned; an int → trim
        the theme package to that many cards to make room. creature_floor is the
        minimum number of on-color bodies the "Creature floor" step tops up to
        (0 → no floor). Pure + deterministic so it can be regression-tested.

        - A floor archetype (voltron/auras/artifacts/enchantress/aristocrats/
          reanimator) that LEADS gets full treatment from _FLOOR_PLAN.
        - aristocrats/reanimator riding shotgun under a NON-aggro lead (e.g.
          Korvold counters+aristocrats) still wants bodies, but keeps most of the
          lead theme: a modest trim + a 20-body floor.
        - Everything else (incl. tribal/tokens/combat leads, vanilla goodstuff)
          gets no floor.
        """
        lead = active_themes[0] if active_themes else None
        if lead in cls._FLOOR_PLAN:
            return cls._FLOOR_PLAN[lead]
        if ({"aristocrats", "reanimator"} & set(active_themes)) and not cls._is_aggro_theme(lead):
            return (15, 20)
        return (None, 0)

    def _count_creatures(self) -> int:
        """Number of true creature cards currently in the deck (excludes lands,
        e.g. creature-lands, and the like)."""
        return sum(
            1 for c in self._deck
            if "creature" in (c.get("type_line", "") or "").lower()
            and "land" not in (c.get("type_line", "") or "").lower()
        )

    def _fetch_creatures(self, profile: CommanderProfile, want: int) -> int:
        """Top up the deck with EDHREC-sorted on-color creatures (goodstuff bodies).

        Used by the creature floor: support archetypes whose theme query is
        non-creature-centric (Equipment/Auras/Artifacts) otherwise build decks
        with too few bodies to actually carry the payload."""
        if want <= 0:
            return 0
        if self._strict():
            added = 0
            for card in self._pool.creatures:
                if added >= want:
                    break
                if self._add(card):
                    added += 1
            return added
        query = (
            f"type:creature "
            f"{self._ci_filter(profile)} "
            f"legal:commander -type:land"
        )
        # Most popular creatures already sit at the top of EDHREC ranking and may
        # be in the deck; fetch past them like _fetch_goodstuff does.
        candidates_needed = len(self._names) + self._bracket_filter.candidate_buffer(want)
        # Seed with owned creatures first (C4), then EDHREC bodies fill the rest.
        candidates = self._owned_candidates(creatures_only=True) + self._prefer_owned(
            self.client.search_cards_paged(query, max_results=candidates_needed))
        added = 0
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
        if self._strict():
            added = 0
            for card in self._pool.flex:
                if added >= want:
                    break
                if self._add(card):
                    added += 1
            return added
        query = (
            f"{self._ci_filter(profile)} "
            f"legal:commander -type:land"
        )
        # Already-picked cards live at the top of the EDHREC ranking, so we
        # need to fetch past them. Buffer = current deck size + generous margin.
        candidates_needed = len(self._names) + self._bracket_filter.candidate_buffer(want)
        # Owned cards get first claim on the flexible goodstuff slots (C4) — this is where
        # "build from my collection" actually spends the deck on what you own.
        candidates = self._owned_candidates() + self._prefer_owned(
            self.client.search_cards_paged(query, max_results=candidates_needed))
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

        if self._strict():
            # Owned nonbasics only. Basics below are still fetched from Scryfall's local
            # cache — every deck may play unlimited basics regardless of what you own.
            for card in self._pool.lands:
                if added >= nonbasic_cap:
                    break
                if self._add(card):
                    added += 1
        else:
            for _label, land_q in NONBASIC_LAND_TIERS:
                if added >= nonbasic_cap:
                    break
                if _label not in allowed_tiers:
                    continue
                query = f"{land_q} {self._ci_filter(profile)} legal:commander"
                candidates = self._prefer_owned(
                    self.client.search_cards_paged(query, max_results=15))
                for card in candidates:
                    if added >= nonbasic_cap:
                        break
                    if self._add(card):
                        added += 1

        # ── Basics ────────────────────────────────────────────────────────────
        basic_slots = want - added
        if not colors:
            # Colorless commanders use Wastes
            wastes = self._basic_card("Wastes")
            if wastes:
                for _ in range(basic_slots):
                    self._deck.append(wastes)
                    added += 1
            return added

        per_color = basic_slots // len(colors)
        extra = basic_slots % len(colors)

        for idx, color in enumerate(colors):
            basic = self._basic_card(BASIC_LAND.get(color))
            if not basic:
                continue
            count = per_color + (1 if idx < extra else 0)
            for _ in range(count):
                self._deck.append(basic)
                added += 1

        return added

    def _basic_card(self, land_name: str | None) -> dict | None:
        """Fetch (and cache) the Scryfall card for a basic land by name. Basics
        are appended to the deck directly (they bypass _add's name dedup), so
        repeated copies are fine — aggregate_duplicates collapses them later."""
        if not land_name:
            return None
        if land_name not in _BASIC_LAND_CACHE:
            result = self.client.search_cards(f'!"{land_name}"')
            data = (result or {}).get("data", [])
            if data:
                _BASIC_LAND_CACHE[land_name] = data[0]
        return _BASIC_LAND_CACHE.get(land_name)

    def _pad_with_basics(self, profile: CommanderProfile, want: int) -> int:
        """Last-resort guarantee that the deck reaches 99: cycle on-color basic
        lands (always legal, locally cached) so a Scryfall shortfall — a transient
        rate-limit beyond the client's own backoff, or an exhausted on-color
        pool — can't leave an ILLEGAL sub-100 deck."""
        if want <= 0:
            return 0
        names = [BASIC_LAND[c] for c in profile.color_identity if c in BASIC_LAND] or ["Wastes"]
        # Prefer the real Scryfall card; fall back to a synthetic so we ALWAYS
        # reach the count even if Scryfall is fully unreachable.
        basics = [self._basic_card(n) or _synthetic_basic(n) for n in names]
        for i in range(want):
            self._deck.append(basics[i % len(basics)])
        return want

    # ── Public API ────────────────────────────────────────────────────────────

    def build(
        self,
        profile: CommanderProfile,
        theme_override: list[str] | None = None,
        slot_overrides: dict[str, int] | None = None,
        playstyle_label: str = "Auto",
        bracket: int = 3,
        owned: set[str] | None = None,
        card_source: str = SOURCE_SCRYFALL,
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
            owned:            Normalized owned-card names (Myth Suite collection). When
                              given, every slot prefers cards the user owns, falling back
                              to unowned EDHREC picks when the collection can't cover it.
            card_source:      One of CARD_SOURCES. "scryfall" ignores the collection;
                              "prefer_collection" is the historic owned-first behaviour;
                              "collection" is STRICT — only owned cards (plus basics,
                              which every deck may play freely). After a strict build,
                              `self.shortfall` reports the roles the collection could not
                              cover, so the caller can say so honestly rather than
                              quietly shipping a worse deck.
        """
        self._deck = []
        self._names = set()
        self._commander_name = profile.name
        self._bracket_filter = BracketFilter(bracket)
        self._owned = owned or set()   # collection-aware building (C4); empty = off
        self._owned_cards = self._resolve_owned_cards(profile)
        self._card_source = card_source if card_source in CARD_SOURCES else SOURCE_SCRYFALL
        self._pool = None
        self.shortfall = {}

        if self._card_source == SOURCE_COLLECTION:
            if self._owned_cards:
                import collection_pool
                self._pool = collection_pool.build_pool(
                    {"name": profile.name, "color_identity": list(profile.color_identity)},
                    self._owned_cards,
                )
            else:
                # No usable owned pool — a strict build would be 99 basic lands. Fall
                # back to Scryfall and let the caller see it in shortfall.
                self._card_source = SOURCE_SCRYFALL
                self.shortfall["collection"] = 99

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
            "finisher":   (slot_overrides or {}).get("finisher", 3),
            "theme":      20,
        }
        used = sum(plan.values())
        plan["goodstuff"] = 99 - used

        # Snapshot active_themes into the lambda closures correctly
        _active = active_themes

        # ── Creature floor ────────────────────────────────────────────────────
        # Some archetypes need a real creature base but LEAD with a non-creature
        # synergy query, so left alone they under-field bodies. Each maps to
        # (theme_cap, creature_floor); the "Creature floor" step then tops up
        # on-color EDHREC bodies to the floor (capped so it never overshoots 99):
        #
        #   • "Support" leads — voltron / auras / artifacts / enchantress: the
        #     PAYLOAD itself isn't creatures (Equipment/Auras), so left alone they
        #     came out with ~5 bodies (the Syr Gwyn / Sram bug). Trim the theme
        #     package hard (→10) and reserve ~20 bodies to carry it.
        #   • "Creature-hungry" leads — aristocrats / reanimator: the deck IS made
        #     of creatures (sac fodder, recursion, reanimation targets), but its
        #     theme payoffs are partly non-creatures and EDHREC goodstuff fill
        #     skews non-creature, so without a floor it came out ~14 (Meren).
        #     Keep most of the theme package (its payoffs are creatures too) and
        #     reserve a high floor.
        #
        # Creature-centric themes (tribal / tokens / combat) get NO floor — they
        # already field a wide board via the aggro bias below, so no regression.
        # The decision is a pure function (unit-tested in tests/test_smoke.py).
        theme_cap, creature_floor = self._creature_floor_plan(active_themes)
        _support_lead = creature_floor > 0        # reserved a floor → skip aggro bump
        if theme_cap is not None:
            plan["theme"]     = theme_cap
            used = sum(v for k, v in plan.items() if k != "goodstuff")
            plan["goodstuff"] = max(2, 99 - used)

        steps: list[tuple[str, object]] = [
            ("Lands",          lambda: self._build_lands(profile, plan["lands"])),
            ("Ramp",           lambda: self._fetch_role(profile, "ramp", plan["ramp"])),
            ("Card draw",      lambda: self._fetch_role(profile, "card_draw", plan["card_draw"])),
            ("Removal",        lambda: self._fetch_role(profile, "removal", plan["removal"])),
            ("Board wipes",    lambda: self._fetch_role(profile, "board_wipe", plan["board_wipe"])),
            ("Protection",     lambda: self._fetch_role(profile, "protection", plan["protection"])),
            ("Finishers",      lambda: self._fetch_role(profile, "finisher", plan["finisher"])),
            ("Theme synergy",  lambda: self._fetch_theme_synergy_list(profile, _active, plan["theme"])),
            # Top up bodies to the floor, but never overshoot 99 (leaves goodstuff
            # whatever slots remain). A no-op (want<=0) for creature-centric decks.
            ("Creature floor", lambda: self._fetch_creatures(
                profile, min(creature_floor - self._count_creatures(),
                             99 - len(self._deck)))),
            ("Goodstuff fill", lambda: self._fetch_goodstuff(profile, max(0, 99 - len(self._deck)))),
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

        # Aggressive go-wide archetypes (any tribe / tokens / combat) want a wider
        # creature base than balanced goodstuff gives. Theme-synergy picks are mostly
        # creatures + their payoffs, so bias slots there (except cEDH, which keeps its
        # interaction-heavy mix). This lifts the effective creature count ~25 -> ~31.
        # Skip when a non-creature theme LEADS (support_lead): there the equipment/
        # aura package is deliberately trimmed and bodies come from the creature
        # floor instead — bumping theme would refill it with non-creatures (the
        # Syr Gwyn "lots of Equipment, ~5 creatures" bug, since Knights ride along).
        _aggro = (any(t.startswith("tribal_") for t in active_themes) or
                  bool({"tokens", "voltron_combat"} & set(active_themes))) and not _support_lead
        if _aggro and bracket != 5:
            plan["theme"]     = plan.get("theme", 20) + 6
            used = sum(v for k, v in plan.items() if k != "goodstuff")
            plan["goodstuff"] = max(2, 99 - used)

        # Collection-aware building (Myth Suite C4): make room for the user's OWNED cards.
        # Owned cards are drafted first into the goodstuff slots (_fetch_goodstuff prepends
        # _owned_candidates), so trim the auto-theme package by just enough to seat the
        # eligible owned cards there. A small collection barely touches theme; a large one
        # shifts more of the flexible budget onto what the user actually owns.
        if self._owned_cards:
            want_owned = min(len(self._owned_cards), 25)
            deficit = want_owned - plan["goodstuff"]
            if deficit > 0:
                plan["theme"] = max(4, plan["theme"] - deficit)
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

        # ── Guarantee exactly 99 cards ────────────────────────────────────────
        # Scryfall can under-deliver — a transient rate-limit beyond the client's
        # own 4-try backoff, or an exhausted on-color pool — which would otherwise
        # leave an ILLEGAL sub-100 deck. Pad with goodstuff first (prefers real
        # spells); retry a couple times since each pass can pull fresh cards, but
        # stop the moment a pass adds nothing (pool dry / Scryfall down). Then
        # guarantee the count with on-color basics, which are always legal and
        # served from the local cache even if Scryfall is unreachable.
        for _ in range(3):
            shortfall = 99 - len(self._deck)
            if shortfall <= 0:
                break
            print(f"\n  Padding {shortfall} missing slots with goodstuff...")
            if self._fetch_goodstuff(profile, shortfall) == 0:
                break
        shortfall = 99 - len(self._deck)
        if shortfall > 0:
            print(f"\n  Guaranteeing 99 with {shortfall} basic land(s) (Scryfall came up short)...")
            self._pad_with_basics(profile, shortfall)

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
