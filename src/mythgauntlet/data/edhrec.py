"""EDHREC popularity & synergy client (docs/DATA_SOURCES.md).

Reads the open JSON endpoints at json.edhrec.com (no key). This is an unofficial API — all
parsing is defensive and isolated here so upstream changes are contained. Responses are
cached under data/edhrec/ and refreshed only on --force; per-commander pages change slowly.

Per invariant #4 (docs/ARCHITECTURE.md): this data seeds priors and builds gauntlets. It must
never directly move a measured strength score.
"""

from __future__ import annotations

import json
import re
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


def fetch_commander(name: str, force: bool = False) -> dict:
    """Fetch (or read cached) EDHREC page payload for a commander."""
    slug = commander_slug(name)
    path = _cache_path(slug)
    if path.exists() and not force:
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
