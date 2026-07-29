"""Deck polling: pull fresh decklists from public sources (docs/DATA_SOURCES.md).

Implemented sources:
  - EDHREC average decks (json.edhrec.com/pages/average-decks/<slug>.json) — the
    crowd-consensus list for a commander; natural Bracket-3-ish corpus anchors.
  - Archidekt public API (/api/decks/v3/ search + /api/decks/<id>/ detail) — popular
    user decks; carries a user-declared `edhBracket` label when the author set one,
    which makes these free calibration data.

Not implemented (documented): Moxfield requires a pre-approved User-Agent for API access;
cEDH Decklist Database links out to Moxfield. Both revisit later.

Every fetched decklist is emitted in our standard text format with provenance comments,
so files are self-describing and parse with model/deck.py.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date

import requests

from mythgauntlet.config import USER_AGENT
from mythgauntlet.data.edhrec import commander_slug

HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}
EDHREC_AVG_URL = "https://json.edhrec.com/pages/average-decks/{slug}.json"
ARCHIDEKT_SEARCH_URL = "https://archidekt.com/api/decks/v3/"
ARCHIDEKT_DECK_URL = "https://archidekt.com/api/decks/{deck_id}/"
ARCHIDEKT_EDH_FORMAT = 3
_THROTTLE_S = 0.25  # politeness delay before each unauthenticated Archidekt request


@dataclass(frozen=True)
class FetchedDeck:
    name: str  # human label
    slug: str  # filesystem-safe key
    source: str  # e.g. 'edhrec_average', 'archidekt:123456'
    text: str  # decklist in our standard format (with provenance comments)
    bracket: int | None = None  # user/source-declared bracket label, if any


def _decklist_text(
    title: str,
    source: str,
    commanders: list[str],
    entries: list[tuple[str, int]],
    bracket: int | None = None,
) -> str:
    lines = [f"# {title}", f"# source: {source}", f"# fetched: {date.today().isoformat()}"]
    if bracket is not None:
        lines.append(f"# bracket: {bracket}")
    lines.append("")
    if commanders:
        lines.append("Commander:")
        lines.extend(f"1 {name}" for name in commanders)
        lines.append("")
    lines.append("Deck:")
    lines.extend(f"{count} {name}" for name, count in entries)
    lines.append("")
    return "\n".join(lines)


# --- EDHREC average decks ---------------------------------------------------------------


def parse_edhrec_average(payload: dict, commander: str) -> FetchedDeck:
    """Build a decklist from an average-decks payload.

    The payload's `deck` is the complete 100-card list (commander first, basics included
    with their counts, e.g. "25 Forest"); the `basic`/`nonbasic` fields are informational
    counts, NOT cards to add.
    """
    deck_lines: list[str] = payload.get("deck") or []
    entries: list[tuple[str, int]] = []
    commanders: list[str] = []
    cmd_norm = commander.casefold()
    for line in deck_lines:
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[0].isdigit():
            count, name = int(parts[0]), parts[1]
        else:
            count, name = 1, line
        if name.casefold() == cmd_norm and not commanders:
            commanders.append(name)
        else:
            entries.append((name, count))

    slug = commander_slug(commander)
    return FetchedDeck(
        name=f"EDHREC average — {commander}",
        slug=f"edhrec-avg-{slug}",
        source="edhrec_average",
        text=_decklist_text(
            f"EDHREC average deck — {commander}", f"edhrec_average:{slug}", commanders, entries
        ),
    )


def fetch_edhrec_average(commander: str) -> FetchedDeck:
    url = EDHREC_AVG_URL.format(slug=commander_slug(commander))
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return parse_edhrec_average(resp.json(), commander)


# --- Archidekt --------------------------------------------------------------------------


@dataclass(frozen=True)
class ArchidektDeckMeta:
    id: int
    name: str
    view_count: int
    edh_bracket: int | None
    owner: str


def archidekt_top(
    page_size: int = 10,
    order: str = "-viewCount",
    format_id: int = ARCHIDEKT_EDH_FORMAT,
    bracket: int | None = None,
) -> list[ArchidektDeckMeta]:
    """Search popular Commander decks. order: -viewCount, -createdAt, -updatedAt...

    Archidekt enforces a minimum page size upstream, so results are truncated
    client-side to honor page_size. `bracket` filters server-side on the author-declared
    `edhBracket` label (verified live 2026-07-17) — the direct route to labeled
    calibration anchors (B5 = cEDH lists), no Moxfield needed.
    """
    time.sleep(_THROTTLE_S)
    params: dict = {"orderBy": order, "formats": format_id, "pageSize": page_size}
    if bracket is not None:
        params["edhBracket"] = bracket
    resp = requests.get(
        ARCHIDEKT_SEARCH_URL,
        params=params,
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    out = []
    for row in (resp.json().get("results") or [])[:page_size]:
        deck_id = row.get("id")
        if deck_id is None:  # tolerate a malformed/placeholder row rather than aborting all
            continue
        out.append(
            ArchidektDeckMeta(
                id=int(deck_id),
                name=row.get("name") or f"deck-{deck_id}",
                view_count=int(row.get("viewCount") or 0),
                edh_bracket=row.get("edhBracket"),
                owner=(row.get("owner") or {}).get("username", ""),
            )
        )
    return out


def parse_archidekt_deck(payload: dict) -> FetchedDeck:
    """Convert an Archidekt deck-detail payload to our decklist format.

    Cards whose category is marked includedInDeck=False (Maybeboard, Sideboard, ...) are
    skipped; the 'Commander' category defines the command zone. Known limitation: decks
    whose owner renamed every category have no detectable commander — callers should
    sanity-gate (the fetch-decks corpus gate skips them).
    """
    excluded = {
        (cat.get("name") or "")
        for cat in payload.get("categories") or []
        if cat.get("includedInDeck") is False
    }
    commanders: list[str] = []
    entries: list[tuple[str, int]] = []
    for row in payload.get("cards") or []:
        name = ((row.get("card") or {}).get("oracleCard") or {}).get("name")
        if not name:
            continue
        categories = row.get("categories") or []
        if any(cat in excluded for cat in categories):
            continue
        quantity = int(row.get("quantity") or 1)
        if "Commander" in categories:
            commanders.append(name)
        else:
            entries.append((name, quantity))

    deck_id = payload.get("id", 0)
    deck_name = payload.get("name") or f"deck-{deck_id}"
    bracket = payload.get("edhBracket")
    return FetchedDeck(
        name=deck_name,
        slug=f"archidekt-{deck_id}",
        source=f"archidekt:{deck_id}",
        text=_decklist_text(
            f"Archidekt — {deck_name}", f"archidekt:{deck_id}", commanders, entries, bracket
        ),
        bracket=bracket,
    )


def fetch_archidekt_deck(deck_id: int) -> FetchedDeck:
    time.sleep(_THROTTLE_S)
    resp = requests.get(ARCHIDEKT_DECK_URL.format(deck_id=deck_id), headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return parse_archidekt_deck(resp.json())
