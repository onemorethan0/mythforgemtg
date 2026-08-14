"""EDHREC popularity & synergy client (docs/DATA_SOURCES.md).

Reads the open JSON endpoints at json.edhrec.com (no key). This is an unofficial API — all
parsing is defensive and isolated here so upstream changes are contained. Responses are
cached under data/edhrec/ with a CACHE_MAX_AGE_DAYS staleness check (and --force).

Per invariant #4 (docs/ARCHITECTURE.md): this data seeds priors and builds gauntlets. It must
never directly move a measured strength score.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from mythgauntlet import __version__
from mythgauntlet.config import data_dir

BASE_URL = "https://json.edhrec.com/pages/commanders/{slug}.json"
HEADERS = {
    "User-Agent": f"MythGauntlet/{__version__} (github.com/onemorethan0/mythgauntlet)",
    "Accept": "application/json",
}

# Per-commander pages change slowly, but "slowly" is not "never" — a new set can add
# cards to a commander's lists. Two weeks keeps the corpus current without hammering
# an unofficial endpoint.
CACHE_MAX_AGE_DAYS = 14

_SLUG_STRIP_RE = re.compile(r"[^a-z0-9 -]")


def commander_slug(name: str) -> str:
    """EDHREC URL slug: lowercase, punctuation dropped, spaces to dashes.

    Partner pairs should be passed as a single 'A + B'-style name only if EDHREC lists them
    that way; multi-face names take the front face.
    """
    front = name.split(" // ")[0].casefold()
    cleaned = _SLUG_STRIP_RE.sub("", front)
    return "-".join(cleaned.split())


@dataclass(frozen=True)
class EdhrecCard:
    name: str
    category: str  # EDHREC cardlist tag, e.g. 'highsynergycards', 'topcards'
    synergy: float | None  # inclusion% for commander minus inclusion% for color identity
    num_decks: int | None
    potential_decks: int | None

    @property
    def inclusion_rate(self) -> float | None:
        if self.num_decks is None or not self.potential_decks:
            return None
        return self.num_decks / self.potential_decks


def parse_commander_page(payload: dict) -> list[EdhrecCard]:
    """Flatten all cardlists on a commander page. Tolerates missing keys."""
    cards: list[EdhrecCard] = []
    container = payload.get("container", {})
    json_dict = container.get("json_dict", {})
    for cardlist in json_dict.get("cardlists") or []:
        tag = cardlist.get("tag", "")
        for view in cardlist.get("cardviews") or []:
            name = view.get("name")
            if not name:
                continue
            cards.append(
                EdhrecCard(
                    name=name,
                    category=tag,
                    synergy=view.get("synergy"),
                    num_decks=view.get("num_decks"),
                    potential_decks=view.get("potential_decks"),
                )
            )
    return cards


def _cache_path(slug: str) -> Path:
    cache = data_dir() / "edhrec"
    cache.mkdir(parents=True, exist_ok=True)
    return cache / f"{slug}.json"


def _cache_is_fresh(path: Path, max_age_days: int) -> bool:
    """True when the cache file is younger than `max_age_days`.

    An unreadable mtime counts as stale: refetching costs one request, while trusting a
    file we cannot date risks pinning the corpus forever.
    """
    if max_age_days <= 0:
        return False
    try:
        return (time.time() - path.stat().st_mtime) < max_age_days * 86400
    except OSError:
        return False


def fetch_commander(name: str, force: bool = False, max_age_days: int | None = None) -> dict:
    """Fetch (or read cached) EDHREC page payload for a commander.

    A cache entry older than `max_age_days` (default `CACHE_MAX_AGE_DAYS`) is refetched.
    Before that check this cache refreshed ONLY on --force, so a page fetched once stayed
    forever: new printings never appear in its cardlists, and a corpus that only ever sees
    old cards can only ever recommend old cards. This repo has already shipped that failure
    once, with a 26-day-frozen Scryfall bulk that faked an exhausted candidate pool. Pass
    `max_age_days=0` to force a refetch, or a large value to pin the cache.
    """
    slug = commander_slug(name)
    path = _cache_path(slug)
    age_limit = CACHE_MAX_AGE_DAYS if max_age_days is None else max_age_days
    if path.exists() and not force and _cache_is_fresh(path, age_limit):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            pass  # truncated/corrupt cache -> refetch below
    resp = requests.get(BASE_URL.format(slug=slug), headers=HEADERS, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    tmp = path.with_suffix(".json.part")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    tmp.replace(path)  # atomic: an interrupted write can't corrupt the cache
    return payload
