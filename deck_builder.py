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

import commander_analysis
from commander_analysis import CommanderProfile, THEME_SYNERGY_QUERIES
from scryfall_client import ScryfallClient
from bracket import BracketFilter, BRACKET_RULES, BRACKET_LABELS
from collection import owned_key
import collection_pool
import edhrec_lift
import lift_stats
import deck_themes
import deck_quality
import theme_match

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
    # Any-colour fixing (Exotic Orchard, City of Brass, Mana Confluence, Reflecting Pool,
    # Path of Ancestry...). Every other tier here is a TWO- or three-colour land, which is
    # why 4-5 colour decks could not be made castable: the builder benchmark had Atraxa,
    # Tom Bombadil, Karona, Jegantha and Ur-Dragon all short, and no redistribution of
    # their ~8 basics fixes five colours. A rainbow land counts as a source for EVERY
    # colour, which is the only lever that scales with colour count.
    # DRAFTED ONLY AT 3+ COLOURS (see _build_lands): in a two-colour deck City of Brass
    # pings you for what a shockland does better, so this tier must not displace them.
    ("rainbow",         "otag:rainbow-land"),
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
    2: {"Command Tower", "rainbow", "reveal_dual", "tri_cycle"},                    # + check/tri lands
    3: {"Command Tower", "rainbow", "fetch", "shock", "reveal_dual", "pain", "filter", "tri_cycle"},  # standard
    4: {"Command Tower", "rainbow", "fetch", "shock", "reveal_dual", "pain", "filter", "tri_cycle", "utility"},  # full
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


LEAD_THEME_SHARE = 0.7


def _theme_slot_split(want: int, n_themes: int) -> list[int]:
    """Divide the theme package across the active themes, LEAD THEME WEIGHTED.

    Not an even split, and that is measured rather than assumed. The Scryfall branch
    used to give the whole package to the first theme (`slot` was computed and never
    used), so themes 2 and 3 were unreachable. Fixing that to an even split was
    correct in principle and WORSE in practice: over the builder benchmark it cost
    multi-theme commanders 1.65 mean synergy and broke colour castability for Edgar
    Markov and Shelob, while single-theme decks moved by exactly 0.00.

    The reason is real rather than metric-gaming: the lead theme is the one the
    commander was actually detected as, and EDHREC lift measures how much a deck looks
    like other decks with that commander — which concentrate. Secondary themes still
    deserve representation, so the lead takes `LEAD_THEME_SHARE` and the rest split the
    remainder evenly. Every theme is guaranteed at least one slot when the package is
    big enough to give one.
    """
    if want <= 0 or n_themes <= 0:
        return []
    if n_themes == 1:
        return [want]
    if want <= n_themes:
        # Too small to weight: one each, lead first, rather than starving a theme.
        return [1] * want + [0] * (n_themes - want)
    lead = max(1, min(want - (n_themes - 1), round(want * LEAD_THEME_SHARE)))
    rest, others = want - lead, n_themes - 1
    base, extra = divmod(rest, others)
    return [lead] + [base + (1 if i < extra else 0) for i in range(others)]


# Basic land type each colour actually plays. A fetchland is only live if it can find one
# of these.
_BASIC_TYPE = {"W": "plains", "U": "island", "B": "swamp", "R": "mountain", "G": "forest"}
_ALL_BASIC_TYPES = frozenset(_BASIC_TYPE.values())


def _land_is_castable(card: dict, colors: list[str]) -> bool:
    """Can this nonbasic land actually produce mana in THIS deck?

    A fetchland's `color_identity` is EMPTY and its `produced_mana` is None — it makes no
    mana itself — so `id<=WB` admits every fetchland in Magic. A measured Tymna (WB) build
    drew twelve fetches, including Misty Rainforest (Forest/Island), Wooded Foothills
    (Mountain/Forest) and Scalding Tarn (Island/Mountain): lands that can find NOTHING in a
    WB deck and are strictly worse than a Wastes, since they also cost a life. The deck had
    36 lands producing only 16 white and 17 black sources and was reported short on black.

    Deliberately conservative — reject only when the card NAMES specific basic types and
    none of them are ones this deck plays. A land that names no type at all (Command Tower,
    Evolving Wilds' "basic land card", Myriad Landscape) is kept, so the filter can drop a
    provably dead land but never a card it merely fails to understand.
    """
    if any(c in (card.get("produced_mana") or []) for c in colors):
        return True                       # makes on-colour mana directly
    named = {t for t in _ALL_BASIC_TYPES
             if t in (card.get("oracle_text") or "").lower()}
    if not named:
        return True                       # says nothing about land types -> keep
    return bool(named & {_BASIC_TYPE[c] for c in colors if c in _BASIC_TYPE})


def _score_first(candidates: list[dict], theme: str) -> list[dict]:
    """Stable-sort Scryfall theme results so the tribe's PAYOFFS lead its bodies.

    The Scryfall theme queries are ordered purely by EDHREC popularity, which has no
    opinion about whether a card rewards the theme or merely belongs to it. For a Dragon
    commander that put generically-good Dragons ahead of the actual tribal shell:
    Goldspan Dragon and Old Gnawbone above Scourge of Valkas and Utvara Hellkite.

    Applied ONLY to theme_match.SCORE_ORDERED — the tribes. Where the WEAK tier is a whole
    card TYPE the same reordering is destructive: `artifacts` has 5 STRONG cards against
    3909 WEAK in the 34k store, so score-first would demote Sol Ring, Arcane Signet and
    Lightning Greaves for five obscure artifact-ETB triggers. Those themes keep the
    EDHREC order. See theme_match.SCORE_ORDERED for the measured numbers.

    Stable, so within each tier the EDHREC ordering (and _prefer_owned's owned-first
    grouping, which runs before this) is preserved exactly.
    """
    if theme not in theme_match.SCORE_ORDERED:
        return candidates
    return sorted(candidates, key=lambda c: -theme_match.theme_score(c, theme))


def _normalize_plan(plan: dict[str, int], target: int = 99) -> dict[str, int]:
    """Force the slot plan to sum to exactly `target` (99 minus any partner commanders —
    see `build`'s `partner_count`), trimming the most flexible slots first.

    The plan is adjusted in several independent passes (bracket 1, bracket 5, the aggro
    bump, the collection redirect) and each recomputes goodstuff as `target - used` with a
    max(2, ...) floor. That floor means an over-allocated plan cannot be absorbed: the
    aggro bump adds 6 to theme, goodstuff clamps at 2, and the plan silently sums over
    target. Every consumer then had to defend itself — the theme step and creature floor
    each grew their own `min(..., target - len(deck))` cap, and before those existed the
    tail just truncated the deck to `target`, throwing away whatever was drafted last.

    Normalising once, after every adjustment, means the plan is a promise the steps can
    trust. Trim order is deliberate: goodstuff is generic filler, theme is the next most
    elastic, and the essential roles and land count are never touched.
    """
    # Clamp first. sum() over a plan carrying a NEGATIVE goodstuff can land on target
    # while the spendable slots still over-allocate, so the function returned "correct"
    # plans that the per-step caps were quietly rescuing. A slot count below zero is
    # never meaningful.
    for key in plan:
        if plan[key] < 0:
            plan[key] = 0
    total = sum(plan.values())
    if total == target:
        return plan
    if total < target:
        plan["goodstuff"] = plan.get("goodstuff", 0) + (target - total)
        return plan
    for key, floor in (("goodstuff", 0), ("theme", 4)):
        if total <= target:
            break
        room = plan.get(key, 0) - floor
        if room > 0:
            cut = min(room, total - target)
            plan[key] -= cut
            total -= cut
    return plan


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
        self._curve_target: dict[int, int] = {}   # MV histogram the fills aim at
        self.source_fallback: str = ""   # set when strict mode reverts to Scryfall
        self._lifts: dict[str, float] = {}   # commander EDHREC lift; {} = hint unavailable

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
        # The shared ordering, not a third variant. The old key was
        # `c.get("edhrec_rank") or 10**9`, which both raised on a non-int rank and — via
        # `or` — treated rank 0 as unranked.
        out.sort(key=collection_pool.rank_key)
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

    def _lift_sorted(self, candidates: list[dict]) -> list[dict]:
        """Reorder a Scryfall candidate window by this COMMANDER's EDHREC lift.

        Every role window arrives sorted by global `edhrec_rank` — popularity, with no
        opinion about who is commanding the deck. That is why two decks in the same colours
        draft so similarly: the ordering never asks whether this commander actually wants
        the card. Lift does (see `edhrec_lift`), so the handful of role candidates EDHREC
        says this commander plays get drafted first and the rest keep their popularity
        order untouched.

        Composes with `_prefer_owned` rather than competing with it: apply lift FIRST, then
        the owned partition on top, and because both are stable the result is owned-cards-
        in-lift-order followed by unowned-in-lift-order — the C4 contract is unchanged.

        No-op when the commander has no EDHREC page or the fetch failed (`_lifts` empty),
        so a build is byte-for-byte unchanged whenever the hint is unavailable. Applies to
        the Scryfall paths only; strict collection mode drafts from an owned pool small
        enough that its own ordering already dominates.
        """
        if not self._lifts:
            return candidates
        return edhrec_lift.lift_order(candidates, self._lifts)

    def _lift_sort_pool(self) -> None:
        """Re-order the STRICT pool by this commander's EDHREC lift, in place.

        `collection_pool.build_pool` sorts every list by `rank_key` — global EDHREC
        popularity, which is precisely the commander-blind ordering `_lift_sorted` replaced
        on every Scryfall path. Strict mode returns early in each `_strict()` branch, so it
        never reached that code and kept drafting by popularity.

        This module previously claimed the owned pool was "small enough that its own
        ordering already dominates". That was an assumption, and measuring it says
        otherwise: over the benchmark's synthetic collection (2,231 cards), strict builds
        averaged 5.1 synergy against a 13.7 ceiling achievable from the SAME collection —
        8.6 points of headroom left on the table.

        Done ONCE here rather than at each draft site so every strict branch — roles,
        theme, creature floor, goodstuff — gets it from one place and cannot drift. The
        lists are views over a shared pool (a three-role card appears in three of them), so
        each is sorted independently; `_lift_sorted` is a stable partition, which means
        `rank_key` order survives inside every lift tier.
        """
        if not self._pool or not self._lifts:
            return
        self._pool.lands = self._lift_sorted(self._pool.lands)
        self._pool.creatures = self._lift_sorted(self._pool.creatures)
        self._pool.flex = self._lift_sorted(self._pool.flex)
        self._pool.roles = {r: self._lift_sorted(cards)
                            for r, cards in self._pool.roles.items()}

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

    def _draft_curve_aware(self, candidates: list[dict], want: int) -> int:
        """Draft `want` cards, at each step taking the best-ranked candidate whose mana
        value bucket is still short of target; when every bucket is met, take the best
        remaining card outright.

        The builder drafts every slot EDHREC-best-first, which is a popularity ordering
        with no opinion about mana cost — so a commander whose colours are rich in
        expensive staples reliably came out top-heavy. Within a bucket the EDHREC order
        is untouched, so the deck still prefers good cards; it just reaches for a good
        three-drop before a good six-drop while the three-slot is short.

        Re-evaluated per card ON PURPOSE. A one-shot partition (prefer everything in an
        under-full bucket, then draft in that order) measured WORSE on the same build:
        it drafted 20+ cards all preferring the same short bucket and overshot it by
        more than the gap it closed.

        Applied only to the FLEXIBLE fills — goodstuff and the creature floor. Role
        fetches are left alone: a board wipe is a board wipe, and biasing those by cost
        would trade a functional slot for a curve slot.
        """
        if want <= 0:
            return 0
        if not self._curve_target:
            added = 0
            for card in candidates:
                if added >= want:
                    break
                if self._add(card):
                    added += 1
            return added

        # Incremental histogram: recomputing the curve per pick would be O(n^2) over
        # the whole deck for no benefit.
        have: dict[int, int] = {}
        for card in self._deck:
            if not deck_quality.is_land(card):
                b = deck_quality.bucket(card)
                have[b] = have.get(b, 0) + 1

        remaining = list(candidates)
        added = 0
        while added < want and remaining:
            under = {mv for mv in range(1, 8)
                     if have.get(mv, 0) < self._curve_target.get(mv, 0)}
            idx = 0
            if under:
                for i, card in enumerate(remaining):
                    if deck_quality.bucket(card) in under:
                        idx = i
                        break
            card = remaining.pop(idx)
            if self._add(card):
                added += 1
                b = deck_quality.bucket(card)
                have[b] = have.get(b, 0) + 1
        return added

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
            pool_role = _POOL_ROLE.get(role)
            if pool_role is None:
                # A role added to ROLE_QUERIES without a _POOL_ROLE entry: skip the slot
                # and report it, rather than raising KeyError inside the build thread.
                self.shortfall[role] = self.shortfall.get(role, 0) + want
                return 0
            added = 0
            for card in self._pool.roles.get(pool_role, []):
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
        candidates = self._prefer_owned(
            self._lift_sorted(self.client.search_cards_paged(query, max_results=buf)))
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
        # Strict mode has no Scryfall search, so theme_match reproduces the same queries
        # locally over the owned pool. Before this, the whole theme package was skipped
        # and its ~20 slots fell through to the generic goodstuff fill — a strict Dragon
        # deck got no Dragon payoffs beyond whatever happened to rank well.
        if self._strict():
            # A theme name the local matcher does not know is dropped here. Record it:
            # otherwise ["tribal_dragons", "typo_theme"] silently yields an all-dragons
            # package with nothing telling the caller the second theme never applied.
            # Latent today (the key sets match exactly, pinned by a test) but silent by
            # construction, which is how it would stay wrong after a rename.
            unknown = [t for t in themes if t not in theme_match.THEMES]
            if unknown:
                self.shortfall["unrecognised_themes"] = (
                    self.shortfall.get("unrecognised_themes", 0) + len(unknown))
            active = [t for t in themes if t in theme_match.THEMES][:3]
            if not active:
                # NOT a collection shortfall. `shortfall` is surfaced to the user as
                # "Collection couldn't cover: theme (-20)", and with no detected theme
                # there was nothing to cover — the gap is a property of the COMMANDER,
                # not of what they own. Six of the twenty benchmark commanders detect no
                # theme at all (Progenitus, Tymna, Jegantha, Karona, Nin, Kozilek), and
                # they accounted for 120 of the 143 reported shortfall slots — a false
                # accusation against the collection in every case. The Scryfall path
                # returns 0 here silently; the two branches now agree, and goodstuff
                # (sized `99 - len(deck)`) absorbs the slots either way. A commander that
                # HAS themes the collection cannot cover is still reported below.
                return 0
            # Match over flex (nonland) — the Scryfall theme queries carry -type:land.
            matched = theme_match.match_themes(self._pool.flex, active)
            added = 0
            # Lead-weighted, not even — see `_theme_slot_split`. This branch used to do a
            # flat `want // len(active)` split with the remainder to theme 1, which the
            # Scryfall branch also did until it was measured against `builder_bench` and
            # found worse on every axis (synergy 15.63 vs 16.01, curve deviation 16.40 vs
            # 15.70). Strict mode never got that fix, so "build only from what I own"
            # disagreed with the ordinary path on the step's central promise.
            splits = _theme_slot_split(want, len(active))
            for i, theme in enumerate(active):
                if added >= want:
                    break
                slot = min(splits[i], want - added)
                # Curve-aware: every candidate here is equally on-theme (match_themes
                # already ranked payoffs above vanilla bodies), so preferring the one
                # that fills a short bucket costs nothing thematic. Without this the
                # theme block took every flexible slot and curve deviation went 2 -> 24.
                added += self._draft_curve_aware(matched.get(theme, []), slot)
            # A theme that ran dry would otherwise waste its slots. The Scryfall path
            # can afford not to care (its pool is the whole format); an owned pool is
            # small enough that one thin theme routinely leaves slots unfilled.
            if added < want:
                for theme in active:
                    if added >= want:
                        break
                    added += self._draft_curve_aware(matched.get(theme, []), want - added)
            if added < want:
                self.shortfall["theme"] = self.shortfall.get("theme", 0) + (want - added)
            return added

        active = [t for t in themes if THEME_SYNERGY_QUERIES.get(t)][:3]
        if not active:
            return 0

        added = 0
        splits = _theme_slot_split(want, len(active))

        for i, theme in enumerate(active):
            if added >= want:
                break
            synergy_q = THEME_SYNERGY_QUERIES[theme]
            slot = splits[i]
            query = (
                f"{synergy_q} "
                f"{self._ci_filter(profile)} "
                f"legal:commander -type:land"
            )
            # Ordering precedence, innermost first: LIFT (does this commander play it?),
            # then OWNED (C4), then THEME SCORE. Both outer passes are stable sorts, so
            # each one only reorders across the previous grouping and lift survives as the
            # tie-break inside every theme-score tier. Score has to stay outermost: a
            # vanilla Dragon must not beat a Dragon lord just because it has more lift.
            #
            # This is the largest single block in the plan (~20 slots) and it was the last
            # to get lift. A generated Kadena deck measured `off-plan` on the off-meta read
            # (synergy 7.2 against a baseline of 11.7) while the role windows were already
            # lift-ordered, which pointed straight here.
            candidates = self._prefer_owned(self._lift_sorted(self.client.search_cards_paged(
                query, max_results=self._bracket_filter.candidate_buffer(slot))))
            candidates = _score_first(candidates, theme)
            # Bounded by THIS theme's `slot`, not by the whole `want`. The inner loop used
            # to break on `added >= want`, so `slot` was computed and never used and the
            # FIRST theme consumed the entire package: a Krenko build (tribal_goblins +
            # tokens) drafted 20 goblin cards and zero token cards, and a third theme was
            # unreachable no matter what resolve_themes produced. Pinned by
            # test_theme_slots_are_split_across_active_themes.
            added += self._draft_slot(candidates, min(slot, want - added))

        # A theme that ran dry leaves its slots unspent, so sweep the remainder across all
        # active themes rather than shipping a short package. Mirrors the strict path.
        if added < want:
            for theme in active:
                if added >= want:
                    break
                query = (
                    f"{THEME_SYNERGY_QUERIES[theme]} "
                    f"{self._ci_filter(profile)} "
                    f"legal:commander -type:land"
                )
                candidates = self._prefer_owned(self._lift_sorted(
                    self.client.search_cards_paged(
                        query,
                        max_results=self._bracket_filter.candidate_buffer(want - added))))
                added += self._draft_slot(_score_first(candidates, theme), want - added)
        return added

    def _draft_slot(self, candidates: list[dict], want: int) -> int:
        """Take up to `want` cards from `candidates`, in order.

        Deliberately NOT curve-aware, unlike the flexible fills. `_score_first` has already
        put the theme's payoffs ahead of its vanilla bodies and `_lift_sorted` has put the
        cards this commander actually plays ahead of both; reordering by mana value would
        trade that for a curve slot, which is the same reason the role fetches opted out.
        """
        added = 0
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
            return self._draft_curve_aware(self._pool.creatures, want)
        query = (
            f"type:creature "
            f"{self._ci_filter(profile)} "
            f"legal:commander -type:land"
        )
        # Most popular creatures already sit at the top of EDHREC ranking and may
        # be in the deck; fetch past them like _fetch_goodstuff does.
        candidates_needed = len(self._names) + self._bracket_filter.candidate_buffer(want)
        # Seed with owned creatures first (C4), then EDHREC bodies fill the rest.
        # Same two-group draft as _fetch_goodstuff: owned bodies first, then EDHREC.
        added = self._draft_curve_aware(self._owned_candidates(creatures_only=True), want)
        if added < want:
            added += self._draft_curve_aware(
                self._prefer_owned(self._lift_sorted(self.client.search_cards_paged(
                    query, max_results=candidates_needed))), want - added)
        return added

    def _fetch_goodstuff(self, profile: CommanderProfile, want: int) -> int:
        """
        EDHREC-sorted cards in color identity as a catch-all filler.
        Fetches enough candidates to go past whatever is already in the deck.
        """
        if self._strict():
            return self._draft_curve_aware(self._pool.flex, want)
        query = (
            f"{self._ci_filter(profile)} "
            f"legal:commander -type:land"
        )
        # Already-picked cards live at the top of the EDHREC ranking, so we
        # need to fetch past them. Buffer = current deck size + generous margin.
        candidates_needed = len(self._names) + self._bracket_filter.candidate_buffer(want)
        # Owned cards get first claim on the flexible goodstuff slots (C4) — this is where
        # "build from my collection" actually spends the deck on what you own.
        # Owned cards are drafted as their OWN group, exhausted before the Scryfall
        # pool is touched. Handing one merged list to _draft_curve_aware let the curve
        # bias reorder across the boundary — an unowned staple in a short bucket beat an
        # owned card, silently defeating the C4 contract this comment claims to keep.
        # Curve awareness still applies WITHIN each group.
        added = self._draft_curve_aware(self._owned_candidates(), want)
        if added < want:
            added += self._draft_curve_aware(
                self._prefer_owned(self._lift_sorted(self.client.search_cards_paged(
                    query, max_results=candidates_needed))), want - added)
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
            # The bracket land-power cap applies here exactly as it does to a Scryfall
            # build: without it a Bracket 1 strict deck kept every fetch/shock the user
            # owned, so the same bracket meant different things per source.
            # collection_pool.land_tier returns None when it cannot confidently classify,
            # and None is ALLOWED — mislabelling an ordinary owned dual would gut the
            # manabase, while admitting one extra good land merely softens the cap.
            for card in self._pool.lands:
                if added >= nonbasic_cap:
                    break
                tier = collection_pool.land_tier(card)
                if tier is not None and tier not in allowed_tiers:
                    continue
                if self._add(card):
                    added += 1
        else:
            for _label, land_q in NONBASIC_LAND_TIERS:
                if added >= nonbasic_cap:
                    break
                if _label not in allowed_tiers:
                    continue
                # Rainbow lands are the answer to MANY colours, not to two: City of
                # Brass pings you for what a shockland does better in Boros.
                if _label == "rainbow" and len(colors) < 3:
                    continue
                query = f"{land_q} {self._ci_filter(profile)} legal:commander"
                # A fetchland has an EMPTY colour identity, so the CI filter cannot see
                # that it fetches types this deck does not play. See _land_is_castable.
                candidates = self._prefer_owned([
                    c for c in self.client.search_cards_paged(query, max_results=15)
                    if _land_is_castable(c, colors)
                ])
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

    def _rebalance_basics(self, profile: CommanderProfile) -> dict[str, int]:
        """Re-split the BASIC lands to match the pips the drafted deck actually demands.

        `_build_lands` runs FIRST, before a single spell exists, and splits basics evenly
        across the colour identity (`basic_slots // len(colors)`). It cannot do better —
        at that point there is nothing to measure. So a deck that goes on to draft mostly
        black spells still gets a 50/50 Plains/Swamp base.

        That was survivable while every slot was drafted in EDHREC-rank order, because
        popularity roughly tracks "generically castable". Ordering by commander lift
        (`_lift_sorted`) deliberately breaks that: it prefers the cards THIS commander
        wants, which are often more colour-intensive. The builder benchmark caught the
        cost — colour-castable decks went 10/20 to 8/20 across the roster.

        Basics are fungible, which makes this the cheapest possible correction: swapping a
        Plains for a Swamp changes nothing structurally. Only basics move; nonbasics were
        chosen for fixing quality and are left exactly as they are. The total land count
        is preserved, so the curve and slot plan are untouched.

        Every colour in the identity keeps at least one basic even if nothing demands it —
        a splash you cannot cast at all is worse than one you cast late, and `pip_counts`
        cannot see activated abilities or a colour only referenced by a nonbasic.

        Returns the new distribution for reporting; `{}` when there is nothing to do.
        """
        colors = list(profile.color_identity)
        if len(colors) < 2:
            return {}                      # mono / colourless: nothing to re-split

        by_name = {BASIC_LAND[c]: c for c in colors if c in BASIC_LAND}
        held = [c for c in self._deck if c.get("name") in by_name]
        total = len(held)
        if total < len(colors):
            return {}                      # too few basics for a split to mean anything

        pips: dict[str, int] = {}
        for card in self._deck + [profile.card]:
            if deck_quality.is_land(card):
                continue
            for color, n in deck_quality.pip_counts(card).items():
                if color in by_name.values():
                    pips[color] = pips.get(color, 0) + n
        if not pips:
            return {}

        # Largest-remainder apportionment, then a floor of 1, so the counts always sum to
        # exactly `total` and no colour is left uncastable.
        demand = sum(pips.values())
        exact = {c: total * pips.get(c, 0) / demand for c in colors}
        alloc = {c: max(1, int(exact[c])) for c in colors}
        while sum(alloc.values()) > total:               # floors overshot a tiny split
            worst = max((c for c in colors if alloc[c] > 1),
                        key=lambda c: alloc[c] - exact[c], default=None)
            if worst is None:
                return {}                                # cannot satisfy the floor; leave it
            alloc[worst] -= 1
        for color in sorted(colors, key=lambda c: -(exact[c] - int(exact[c]))):
            if sum(alloc.values()) >= total:
                break
            alloc[color] += 1

        current = {c: 0 for c in colors}
        for card in held:
            current[by_name[card["name"]]] += 1
        if alloc == current:
            return {}

        # Resolve every basic BEFORE removing anything. Otherwise a Scryfall miss on one
        # colour would drop those slots and leave an illegal sub-99 deck — the swap has to
        # be all-or-nothing.
        cards = {c: self._basic_card(BASIC_LAND.get(c)) for c in colors}
        if any(cards[c] is None for c in colors):
            return {}

        self._deck = [c for c in self._deck if c.get("name") not in by_name]
        for color in colors:
            for _ in range(alloc[color]):
                self._deck.append(cards[color])
        return alloc

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
        partner_count: int = 0,
    ) -> list[dict]:
        """
        Build the 99-card deck (98 when `partner_count` is 1, 97 if — hypothetically — 2:
        a legal Commander deck is always 100 cards, library + command zone, and a second
        or third commander occupies a command-zone slot, not a library one).

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
            partner_count:    How many OTHER commanders share the command zone (0 for a
                              normal single-commander deck). Shrinks the drafted library
                              by that many cards so the caller can add the partner
                              card(s) themselves and still land on a legal 100-card deck
                              — this method never drafts or returns the partner(s)
                              itself, same as it never drafts the lead commander.
        """
        self._deck = []
        self._names = set()
        self._commander_name = profile.name
        # See partner_count's docstring above: a legal command zone always totals 100
        # cards with the library, so each extra commander shrinks what THIS method drafts.
        library_size = 99 - max(0, partner_count)
        # This commander's EDHREC lift, fetched once per build and cached on disk. Fails
        # soft to {} (no page, no network, unofficial API changed shape), which makes
        # `_lift_sorted` a no-op — a build must never depend on EDHREC being reachable.
        self._lifts = edhrec_lift.lift_map(profile.name)
        self._bracket_filter = BracketFilter(bracket)
        self._owned = owned or set()   # collection-aware building (C4); empty = off
        self._owned_cards = self._resolve_owned_cards(profile)
        self._card_source = card_source if card_source in CARD_SOURCES else SOURCE_SCRYFALL
        self._pool = None
        self.shortfall = {}
        self.source_fallback = ""

        if self._card_source == SOURCE_COLLECTION:
            if self._owned_cards:
                self._pool = collection_pool.build_pool(
                    {"name": profile.name, "color_identity": list(profile.color_identity)},
                    self._owned_cards,
                )
                self._lift_sort_pool()
            else:
                # No usable owned pool — a strict build would be 99 basic lands. Fall
                # back to Scryfall and say so in words. A sentinel count in `shortfall`
                # rendered as the meaningless "Collection couldn't cover: collection (-99)".
                self._card_source = SOURCE_SCRYFALL
                self.source_fallback = (
                    "No owned cards match this commander's colour identity — "
                    "built from Scryfall instead."
                )

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
        plan["goodstuff"] = library_size - used

        # The curve the flexible fills aim at. Derived from the LAND plan, so a
        # landfall build that shaves a land automatically budgets one more spell.
        self._curve_target = deck_quality.curve_target(
            library_size - plan["lands"], int(profile.mana_value))

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
            plan["goodstuff"] = max(2, library_size - used)

        steps: list[tuple[str, object]] = [
            ("Lands",          lambda: self._build_lands(profile, plan["lands"])),
            ("Ramp",           lambda: self._fetch_role(profile, "ramp", plan["ramp"])),
            ("Card draw",      lambda: self._fetch_role(profile, "card_draw", plan["card_draw"])),
            ("Removal",        lambda: self._fetch_role(profile, "removal", plan["removal"])),
            ("Board wipes",    lambda: self._fetch_role(profile, "board_wipe", plan["board_wipe"])),
            ("Protection",     lambda: self._fetch_role(profile, "protection", plan["protection"])),
            ("Finishers",      lambda: self._fetch_role(profile, "finisher", plan["finisher"])),
            # Capped at the space actually left, like the creature floor below. The
            # aggro bump can push the plan over library_size (goodstuff has a max(2,...)
            # floor that stops it absorbing the overflow); before theme could fill its
            # whole allocation that never showed, and now the tail silently truncated.
            ("Theme synergy",  lambda: self._fetch_theme_synergy_list(
                profile, _active, min(plan["theme"], library_size - len(self._deck)))),
            # Top up bodies to the floor, but never overshoot library_size (leaves
            # goodstuff whatever slots remain). A no-op (want<=0) for creature-centric decks.
            ("Creature floor", lambda: self._fetch_creatures(
                profile, min(creature_floor - self._count_creatures(),
                             library_size - len(self._deck)))),
            ("Goodstuff fill", lambda: self._fetch_goodstuff(profile, max(0, library_size - len(self._deck)))),
        ]

        # Bracket 5 (cEDH): lean heavier on draw/interaction, lighter on theme
        if bracket == 5:
            plan["card_draw"]  = plan.get("card_draw", 10) + 4
            plan["protection"] = plan.get("protection", 3) + 3
            plan["theme"]      = max(8, plan.get("theme", 20) - 7)
            used = sum(v for k, v in plan.items() if k != "goodstuff")
            plan["goodstuff"] = library_size - used

        # Bracket 1 (Exhibition): more theme, less raw goodstuff
        if bracket == 1:
            plan["theme"]     = plan.get("theme", 20) + 5
            used = sum(v for k, v in plan.items() if k != "goodstuff")
            plan["goodstuff"] = max(2, library_size - used)

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
            plan["goodstuff"] = max(2, library_size - used)

        # Collection-aware building (Myth Suite C4): make room for the user's OWNED cards.
        # Owned cards are drafted first into the goodstuff slots (_fetch_goodstuff prepends
        # _owned_candidates), so trim the auto-theme package by just enough to seat the
        # eligible owned cards there. A small collection barely touches theme; a large one
        # shifts more of the flexible budget onto what the user actually owns.
        # NOT in strict mode. The redirect buys goodstuff slots for owned cards because
        # under prefer_collection goodstuff is the ONLY place they get seated. Strict
        # mode draws every slot from the collection already, so the trade buys nothing
        # and costs the theme package: with a 400-card pool it drove theme to its floor
        # of 4, so a strict Dragon deck got 4 theme cards instead of 26.
        if self._owned_cards and not self._strict():
            want_owned = min(len(self._owned_cards), 25)
            deficit = want_owned - plan["goodstuff"]
            if deficit > 0:
                plan["theme"] = max(4, plan["theme"] - deficit)
                used = sum(v for k, v in plan.items() if k != "goodstuff")
                plan["goodstuff"] = max(2, library_size - used)

        # Every adjustment above is done; make the plan sum to library_size exactly so
        # the steps can trust it instead of each capping itself against the running deck.
        plan = _normalize_plan(plan, library_size)

        from commander_analysis import THEME_LABELS
        active_labels = [THEME_LABELS.get(t, t) for t in active_themes] or ["Goodstuff / Midrange"]
        bracket_label = BRACKET_LABELS.get(bracket, str(bracket))
        gc_limit_str  = str(self._bracket_filter.gc_limit) if self._bracket_filter.gc_limit >= 0 else "unlimited"

        print(f"\n  Building {library_size}-card library for {profile.name}"
              + (f" (+ {partner_count} partner commander(s))" if partner_count else ""))
        print(f"  Color identity : {profile.color_id_str or 'Colorless'}")
        print(f"  Playstyle      : {playstyle_label}")
        print(f"  Bracket        : {bracket} — {bracket_label}  (Game Changers: {gc_limit_str})")
        print(f"  Active themes  : {', '.join(active_labels)}")
        print(f"  Commander MV   : {int(profile.mana_value)}")
        print(f"  Land target    : {plan['lands']}\n")

        for label, fn in steps:
            n = fn()
            print(f"  [{label:<18}] {n:>2} cards   (running total: {len(self._deck)})")

        # ── Guarantee exactly library_size cards ─────────────────────────────
        # Scryfall can under-deliver — a transient rate-limit beyond the client's
        # own 4-try backoff, or an exhausted on-color pool — which would otherwise
        # leave an ILLEGAL sub-100 deck. Pad with goodstuff first (prefers real
        # spells); retry a couple times since each pass can pull fresh cards, but
        # stop the moment a pass adds nothing (pool dry / Scryfall down). Then
        # guarantee the count with on-color basics, which are always legal and
        # served from the local cache even if Scryfall is unreachable.
        for _ in range(3):
            shortfall = library_size - len(self._deck)
            if shortfall <= 0:
                break
            print(f"\n  Padding {shortfall} missing slots with goodstuff...")
            if self._fetch_goodstuff(profile, shortfall) == 0:
                break
        shortfall = library_size - len(self._deck)
        if shortfall > 0:
            print(f"\n  Guaranteeing {library_size} with {shortfall} basic land(s) (Scryfall came up short)...")
            if self._strict():
                # An exhausted owned pool used to pad SILENTLY: a small collection got a
                # deck that was mostly Mountains, and shortfall named only the roles — so
                # build()'s promise to report what the collection couldn't cover was only
                # half kept. Goodstuff/creature fill have no want-vs-got to record, but
                # the padding count is the honest total.
                self.shortfall["padded_with_basics"] = shortfall
            self._pad_with_basics(profile, shortfall)

        # LAST, after every spell (and any padding) is in: only now is there a real pip
        # demand to measure. See _rebalance_basics for why the even split it replaces
        # could not have been better at land-drafting time.
        try:
            alloc = self._rebalance_basics(profile)
            if alloc:
                print("  Basics rebalanced to the deck's pips: "
                      + ", ".join(f"{BASIC_LAND[c]} x{n}" for c, n in alloc.items()))
        except Exception as exc:      # noqa: BLE001 - a cosmetic land swap must never
            print(f"  [basics] rebalance skipped: {exc}")   # cost anyone a built deck

        return self._deck[:library_size]


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


def _command_zone_card(commander: dict, partners: list[dict] | None) -> dict:
    """A copy of `commander` carrying the WHOLE command zone's colour identity.

    A copy, never a mutation: the caller's card dict is shared with the render and
    export paths, and widening its identity in place would silently change what those
    consider on-colour.
    """
    if not partners or not commander:
        return commander
    return dict(commander,
                color_identity=commander_analysis.command_zone_identity(commander, partners))


def compute_stats(commander: dict, deck: list[dict],
                  partners: list[dict] | None = None) -> dict:
    """Deck statistics. `partners` is the rest of the COMMAND ZONE, if any.

    Partner cards are already folded into `deck` by the import path (so their pips and
    types count), but the commander dict alone carries only HALF a partner pair's
    colour identity — and `deck_quality.assess_colors` filters sources by it. An
    imported Sam + Frodo deck was reported short 15 black sources while holding 32,
    because black sat outside the half-identity. Passing the zone fixes that.
    """
    commander = _command_zone_card(commander, partners)
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
    # Computed once, ahead of `offmeta`, so its theme-sub-page coverage widening can use the
    # DECK's own detected themes (S4, 2026-08-26) — the same "deck's plan, not the
    # commander's unsupported claims" contract `redundancy.targets_for` already documents.
    # Both `theme_counts` and its derived `detect_deck_themes` are passed straight into
    # `deck_themes.stats_block` below for `archetypes` too, so the O(cards x themes)
    # oracle-text scan runs exactly ONCE per build/rebuild/retheme/import request instead
    # of once per call site that wants the same answer.
    try:
        deck_theme_counts = deck_themes.theme_counts(deck) if deck else {}
        detected_themes = (
            deck_themes.detect_deck_themes(deck, counts=deck_theme_counts) if deck else []
        )
        themes_detected_ok = True
    except Exception:      # noqa: BLE001 - advisory measurement, never fails a build
        deck_theme_counts = {}
        detected_themes = []
        # NOT reused below on this path: `deck_themes.stats_block` must get the chance
        # to run its own (identically-failing) computation and fall back to `{}` via its
        # own try/except, rather than being handed a bare `[]`/`{}` that reads as
        # "genuinely zero themes detected" instead of "detection failed".
        themes_detected_ok = False
    return {
        "average_cmc": round(avg_cmc, 2),
        "color_pips": {k: v for k, v in color_pips.items() if v},
        "type_counts": type_counts,
        "cmc_curve": dict(sorted(cmc_curve.items())),
        "land_count": type_counts.get("Land", 0),
        "total_cards": deck_total + 1,  # +1 for commander
        "quality": deck_quality_block(commander, deck),
        # "How off-meta is this deck" — a different axis from bracket/strength, and the one
        # a casual pod asks first. Same one-place contract as `quality`: every path (build,
        # rebuild, retheme, import/Analyze) gets it here. `{}` whenever EDHREC has nothing
        # to say, which StepDeck's `stats.offmeta &&` guard hides.
        "offmeta": lift_stats.stats_block(commander, deck, themes=detected_themes),
        # What archetypes the DECK actually plays, vs what the commander's text
        # claims. Pure/offline, so it costs nothing on any path.
        "archetypes": deck_themes.stats_block(
            commander, deck, partners,
            detected=detected_themes if themes_detected_ok else None,
            counts=deck_theme_counts if themes_detected_ok else None),
    }


def deck_quality_block(commander: dict, deck: list[dict]) -> dict:
    """Curve and colour-source health for a finished list, as plain JSON.

    Lives on compute_stats so EVERY path gets it from one place — generate, rebuild,
    retheme, and imported decks (so "Analyze a Deck" reports whether a list the user
    already owns can actually cast itself). Deliberately advisory: nothing here changes
    which cards are in the deck, it only measures the one that was built.

    Unlike the sibling `average_cmc`/`cmc_curve` keys above, these figures are
    quantity-weighted, so an imported deck's aggregated basics don't skew them."""
    # A "deck of one" (mode:single_card) carries deck == [], and compute_stats is also
    # called with an empty list mid-build. There is no curve and no manabase to judge,
    # and measuring anyway reported "short on sources" for a single custom card.
    # An empty block is the honest answer; StepDeck's `stats.quality &&` guard hides it.
    if not any(not deck_quality.is_land(c) for c in deck):
        return {}
    try:
        curve = deck_quality.assess_curve(deck, int(deck_quality.mana_value(commander)))
        colors = deck_quality.assess_colors(deck, commander)
        mana = deck_quality.assess_mana_base(deck)
    except Exception:      # noqa: BLE001 — advisory only; never fail a build over stats
        return {}
    return {
        "curve": {
            "average": curve.average, "verdict": curve.verdict,
            "buckets": curve.buckets, "target": curve.target,
            "over": curve.over, "under": curve.under, "notes": curve.notes,
        },
        "colors": {
            "ok": colors.ok, "pips": colors.pips, "sources": colors.sources,
            "required": colors.required, "short": colors.short, "notes": colors.notes,
        },
        # Whether there is enough mana AT ALL — a different question from `colors`,
        # which only asks whether the mana is the right COLOURS. A 27-land deck with
        # no ramp and a 27-land deck with eleven both passed `colors` identically.
        "mana": {
            "ok": mana.ok, "verdict": mana.verdict, "lands": mana.lands,
            "ramp": mana.ramp, "sources": mana.sources, "notes": mana.notes,
        },
    }
