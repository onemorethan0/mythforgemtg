"""Commander-conditioned card ordering from EDHREC lift (spec: docs/SPEC_edhrec_lift.md).

`DeckBuilder` fills every role slot from a Scryfall query sorted by global `edhrec_rank` —
a popularity ordering with no opinion about the commander. That is why two decks under the
same colours draft so similarly: the ordering never asks whether THIS commander wants the
card. EDHREC publishes exactly that number — lift, how much more often a card appears in a
commander's decks than in decks of its colour identity generally.

Verified against the live endpoint (json.edhrec.com), not assumed. `synergy` is a SIGNED
FRACTION: 0.908 means +90.8 points.

| commander                 | rows | min    | max   | median | negatives |
|---------------------------|------|--------|-------|--------|-----------|
| Kadena, Slinking Sorcerer  | 244  | -0.149 | 0.908 | 0.114  | 54        |
| Atraxa, Praetors' Voice    | 292  | -0.164 | 0.273 | 0.032  | 59        |

The scale is COMMANDER-RELATIVE and that is load-bearing. Kadena is a focused commander
(max 0.908); Atraxa is a goodstuff pile (max 0.273). Any absolute cutoff would call almost
every Atraxa card unsynergistic while calling half the Kadena page synergistic. The
zero-crossing is scale-free and means exactly what we want: played more here than baseline.

Negative-lift cards are the generic staples, which is signal rather than noise — Kadena's
most negative are Swiftfoot Boots, An Offer You Can't Refuse and Counterspell; Atraxa's are
Mystic Remora, Force of Will and Swan Song.

This is an APP-ROOT module. `deck_builder` cannot import `mythgauntlet.*` (the engine is a
separate process on :8020 and the Forge server runs without `src/` on the path), so the
small amount of EDHREC parsing here is deliberately duplicated rather than shared.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import requests

from app_paths import app_path

BASE_URL = "https://json.edhrec.com/pages/commanders/{slug}.json"
THEME_URL = "https://json.edhrec.com/pages/commanders/{slug}/{tag}.json"
HEADERS = {
    "User-Agent": "MythForge/1.0 (+https://github.com/onemorethan0/mythforgemtg)",
    "Accept": "application/json",
}
TIMEOUT = 15

# A cache older than this is refetched. Without an age check a cached corpus only ever
# recommends old cards: this repo already shipped that exact bug once with a 26-day-frozen
# Scryfall bulk, which faked an exhausted candidate pool.
CACHE_MAX_AGE_DAYS = 14

# Kill switch: MYTHFORGE_EDHREC_LIFT=off makes `lift_map` return {} without touching the
# network or the disk, which turns `_lift_sorted` into a no-op and restores the exact
# pre-lift build ordering. The test suite sets it (invariant: tests are offline — a build
# test must not depend on an unofficial third-party endpoint being up), and it is the
# escape hatch if EDHREC's ordering is ever unwanted or the endpoint misbehaves.
_OFF_VALUES = {"0", "off", "false", "no"}


def enabled() -> bool:
    """Whether lift lookups may touch the network. Read per call, not cached at import,
    so a test or a running process can flip it without a reload."""
    return os.environ.get("MYTHFORGE_EDHREC_LIFT", "on").strip().casefold() not in _OFF_VALUES


_SLUG_STRIP_RE = re.compile(r"[^a-z0-9 -]")


def commander_slug(name: str) -> str:
    """EDHREC URL slug. Mirrors `mythgauntlet.data.edhrec.commander_slug` exactly.

    Front face, casefolded, punctuation dropped, whitespace runs joined with '-'. Built
    with `"-".join(cleaned.split())` rather than a whitespace regex so a leading or
    trailing space cannot produce a dangling dash.
    """
    front = name.split(" // ")[0].casefold()
    return "-".join(_SLUG_STRIP_RE.sub("", front).split())


def normalize_name(name: str) -> str:
    """Lookup key for a card name: front face, casefolded, whitespace collapsed."""
    return " ".join(name.split(" // ")[0].casefold().split())


def _cache_path(slug: str) -> Path:
    return app_path("cache", "edhrec", f"{slug}.json")


def _theme_cache_path(slug: str, tag: str) -> Path:
    return app_path("cache", "edhrec", f"{slug}__{tag}.json")


def _parse_lifts(payload: dict) -> dict[str, float]:
    """Flatten an EDHREC commander page to {normalized name: synergy}.

    Defensive throughout — this is an unofficial API and a shape change must degrade to
    "no ordering hint", never to a failed build. A name appearing in several cardlists
    keeps the FIRST synergy seen.
    """
    lifts: dict[str, float] = {}
    try:
        cardlists = payload["container"]["json_dict"]["cardlists"] or []
    except (KeyError, TypeError):
        return {}
    for cardlist in cardlists:
        if not isinstance(cardlist, dict):
            continue
        for view in cardlist.get("cardviews") or []:
            if not isinstance(view, dict):
                continue
            name = view.get("name")
            synergy = view.get("synergy")
            if not name or not isinstance(synergy, (int, float)):
                continue
            key = normalize_name(name)
            if key not in lifts:
                lifts[key] = float(synergy)
    return lifts


def _read_cache(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None       # truncated / corrupt / missing -> treat as no cache


def _write_cache(path: Path, payload: dict) -> None:
    """Atomic write. Failure to cache is not failure to fetch, so this never raises."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)   # cache/edhrec/ may not exist yet
        tmp = path.with_name(path.name + ".part")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        tmp.replace(path)      # replace(), NOT rename(): on Windows rename fails if the
                               # target exists, so every refresh after the first would
                               # raise and the cache would silently never update.
    except OSError:
        pass


def _fetch_lifts(
    url: str,
    path: Path,
    *,
    max_age_days: int | None,
    force: bool,
) -> dict[str, float]:
    """Shared cache-then-fetch-then-degrade logic for a main OR a theme sub-page.

    Every error path returns a dict — empty if there is nothing better. A refetch that
    fails falls back to the stale cache: out-of-date lift still beats no lift.
    """
    # `or` would turn an explicit max_age_days=0 ("always refetch") back into the default.
    age_limit = CACHE_MAX_AGE_DAYS if max_age_days is None else max_age_days

    if not force and path.exists():
        try:
            fresh = (time.time() - path.stat().st_mtime) < age_limit * 86400
        except OSError:
            fresh = False
        if fresh:
            cached = _read_cache(path)
            if cached is not None:
                return _parse_lifts(cached)

    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:      # noqa: BLE001 - network/JSON/anything: degrade, never raise
        stale = _read_cache(path)
        return _parse_lifts(stale) if stale is not None else {}

    if not isinstance(payload, dict):
        return {}
    _write_cache(path, payload)
    return _parse_lifts(payload)


def lift_map(
    commander_name: str,
    *,
    max_age_days: int | None = None,
    force: bool = False,
) -> dict[str, float]:
    """`{normalized card name: lift}` for one commander's MAIN page; `{}` on any failure.

    This is an ordering HINT. A build must never fail because EDHREC is unreachable, so
    every error path returns a dict — empty if there is nothing better.
    """
    if not commander_name or not enabled():
        return {}
    slug = commander_slug(commander_name)
    if not slug:
        return {}
    return _fetch_lifts(
        BASE_URL.format(slug=slug), _cache_path(slug),
        max_age_days=max_age_days, force=force,
    )


# Deck-context archetype key (commander_analysis.THEME_PATTERNS / deck_themes) -> the real
# EDHREC tag slug that page fetches under `/commanders/{slug}/{tag}.json`. VERIFIED against
# four live commander pages spanning different colour identities (Omo, Edgar Markov, Kaalia,
# Krenko) rather than assumed from the name — a tag not seen on any of those pages is left
# OUT rather than guessed, because a wrong slug degrades silently to a 404 -> empty dict,
# indistinguishable from "this deck has no theme to widen". See docs/SPEC_edhrec_lift.md.
#
# `draw_matters` is DELIBERATELY OMITTED. Its `commander_analysis` pattern is a PAYOFF
# ("whenever you draw a card"), but EDHREC's `card-draw` tag is a shopping list of cards that
# PRODUCE draw — the exact sources-vs-payoffs conflation this repo already caught once for
# `lifegain` (lifelink/"you gain N life" vs `extort`/"life you gained") and rejected outright
# for `big_mana`. Mapping it would spend the coverage widening on the wrong half of the card.
#
# `face_down` maps to `morph` ONLY — EDHREC has no combined morph/manifest/disguise tag, so
# this under-covers manifest/disguise decks rather than over-claiming. `impulse` maps to the
# real tag `impulse-draw` (a naming mismatch, not a semantic one — EDHREC's own copy calls the
# mechanic "Impulsive Draw"). `voltron` and `voltron_combat` are two `commander_analysis`
# archetypes for one EDHREC tag (aura/equipment voltron vs evasive-combat voltron); EDHREC
# does not split them, so both funnel into the same sub-page — safe, since this only ever
# WIDENS coverage, never overwrites a value.
ARCHETYPE_EDHREC_TAGS: dict[str, str] = {
    "aristocrats": "aristocrats",
    "artifacts": "artifacts",
    "auras": "auras",
    "chaos": "chaos",
    "counters": "counters-matter",
    "enchantress": "enchantress",
    "energy": "energy",
    "etb": "etb",
    "face_down": "morph",
    "graveyard": "graveyard",
    "group_hug": "group-hug",
    "impulse": "impulse-draw",
    "landfall": "landfall",
    "lifegain": "lifegain",
    "reanimator": "reanimator",
    "sagas": "sagas",
    "spellslinger": "spellslinger",
    "theft": "theft",
    "tokens": "tokens",
    "voltron": "voltron",
    "voltron_combat": "voltron",
    "tribal_angels": "angels",
    "tribal_beasts": "beasts",
    "tribal_cats": "cats",
    "tribal_demons": "demons",
    "tribal_dinosaurs": "dinosaurs",
    "tribal_dragons": "dragons",
    "tribal_elves": "elves",
    "tribal_goblins": "goblins",
    "tribal_humans": "humans",
    "tribal_knights": "knights",
    "tribal_merfolk": "merfolk",
    "tribal_ninjas": "ninjas",
    "tribal_slivers": "slivers",
    "tribal_soldiers": "soldiers",
    "tribal_spirits": "spirits",
    "tribal_vampires": "vampires",
    "tribal_warriors": "warriors",
    "tribal_werewolves": "werewolves",
    "tribal_wizards": "wizards",
    "tribal_wolves": "wolves",
    "tribal_zombies": "zombies",
}


def theme_lift_map(
    commander_name: str,
    tag: str,
    *,
    max_age_days: int | None = None,
    force: bool = False,
) -> dict[str, float]:
    """`{normalized card name: lift}` for one THEME sub-page; `{}` on any failure.

    This is a DIFFERENT statistic from `lift_map`'s, not more data on the same one —
    measured, not assumed (docs/SPEC_edhrec_lift.md "sub-page synergy is scale-mismatched").
    A sub-page's `potential_decks` is the count of decks tagged with THIS theme, not every
    deck running the commander, so its synergy is "played more than baseline WITHIN this
    theme's decks" rather than "...within all of this commander's decks". Sign agreement
    with the main page was measured at 225/230 (97.8%) on Omo/landfall — the 5 disagreements
    all sit within ±0.04 of zero on both sides, i.e. noise at the boundary, not a real
    reversal — but MAGNITUDES differ by up to ~50% relative on a narrow sub-theme (Atraxa's
    infect page, a ~10%-of-decks niche, showed bigger main-vs-sub gaps than Omo's landfall
    page, which covers a much larger share of Omo's own decks). Never merge this dict's
    VALUES into a `lift_map` result for the same commander and treat the union as one
    population — `lift_stats.stats_block` uses this only to WIDEN coverage (a card absent
    from the main page becomes measured, informationally), never to touch the main page's
    own baseline/synergy figures.
    """
    if not commander_name or not tag or not enabled():
        return {}
    slug = commander_slug(commander_name)
    if not slug:
        return {}
    return _fetch_lifts(
        THEME_URL.format(slug=slug, tag=tag), _theme_cache_path(slug, tag),
        max_age_days=max_age_days, force=force,
    )


def tag_for_themes(themes: "list[str] | None") -> str | None:
    """The first `themes` entry with a known EDHREC tag, in the caller's own priority order.

    Callers should pass the DECK's own detected themes (`deck_themes.detect_deck_themes`),
    the same "deck's own plan, not the commander's unsupported claims" contract
    `redundancy.targets_for` already documents — using `merge_themes`' output here would
    widen coverage toward a theme the deck isn't actually playing.
    """
    for theme in themes or ():
        tag = ARCHETYPE_EDHREC_TAGS.get(theme)
        if tag:
            return tag
    return None


def lift_order(candidates: list[dict], lifts: dict[str, float]) -> list[dict]:
    """Reorder Scryfall card dicts so the commander's preferred cards come first.

    A stable three-tier partition, mirroring `deck_builder._prefer_owned`:

      1. lift > 0   - played more than baseline here; sorted by lift descending
      2. unknown    - not on the commander's page; ORIGINAL (EDHREC-rank) order kept
      3. lift <= 0  - played less than baseline here; original order kept

    Unknown outranks measured-negative on purpose: an absent card is unmeasured, not
    rejected. A card printed last week has no EDHREC history at all, and demoting it below
    a known-negative staple would penalise every new release — the precise failure this
    change exists to avoid.

    Returns a NEW list and never mutates the input. An empty `lifts` returns the input
    order unchanged, so a missing or failed EDHREC page is a no-op.
    """
    if not lifts:
        return list(candidates)

    positive: list[tuple[float, int, dict]] = []
    unknown: list[dict] = []
    negative: list[dict] = []
    for i, card in enumerate(candidates):
        lift = lifts.get(normalize_name(card.get("name", "")))
        if lift is None:
            unknown.append(card)
        elif lift > 0:
            positive.append((lift, i, card))
        else:
            negative.append(card)

    # Index breaks ties so equal lifts keep their incoming EDHREC-rank order, and the sort
    # never has to compare two card dicts (which are not orderable).
    positive.sort(key=lambda t: (-t[0], t[1]))
    return [card for _lift, _i, card in positive] + unknown + negative
