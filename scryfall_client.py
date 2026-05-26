import time
from typing import Optional
import requests

BASE_URL = "https://api.scryfall.com"


def _normalize_card(card: dict) -> dict:
    """Promote front-face fields to the top level for double-faced cards."""
    if card.get("image_uris"):
        return card  # single-faced — nothing to do
    faces = card.get("card_faces")
    if not faces:
        return card
    front = faces[0]
    merged = dict(card)
    # Promote fields that live only on card_faces for DFCs
    for field in ("mana_cost", "oracle_text", "type_line", "power", "toughness",
                  "loyalty", "image_uris", "colors"):
        if field not in merged or not merged[field]:
            if field in front:
                merged[field] = front[field]
    # Use front-face name only (not "Front // Back")
    merged["_front_name"] = front.get("name", card["name"])
    return merged
# Scryfall asks for at least 50-100ms between requests. 150ms gives us headroom.
# TODO: replace live search calls with Scryfall bulk-data cache once we add
#       the local SQLite/JSON card store — that drops API calls from ~25 to ~3 per build.
RATE_LIMIT_DELAY = 0.15


class ScryfallClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "CommanderDeckBuilder/1.0 (personal project)",
            "Accept": "application/json",
        })
        self._last_request_time = 0.0

    def _rate_limit(self):
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = time.monotonic()

    def _get(self, path: str, params: dict = None) -> Optional[dict]:
        self._rate_limit()
        backoff = 1.0
        for attempt in range(4):
            try:
                resp = self.session.get(f"{BASE_URL}{path}", params=params, timeout=15)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 404:
                    return None
                if resp.status_code in (429, 503):
                    # Rate-limited or temporarily unavailable — exponential backoff
                    print(f"\n  [rate limit] waiting {backoff:.1f}s...", end=" ", flush=True)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 16.0)
                    self._last_request_time = time.monotonic()
                    continue
                # Other HTTP errors (400 bad query, 422, etc.)
                return None
            except requests.RequestException:
                time.sleep(backoff)
                backoff = min(backoff * 2, 16.0)
        return None

    def get_card_by_name(self, name: str, fuzzy: bool = False) -> Optional[dict]:
        param_key = "fuzzy" if fuzzy else "exact"
        card = self._get("/cards/named", params={param_key: name})
        if card is not None:
            return _normalize_card(card)
        if not fuzzy:
            return None
        # Fuzzy named endpoint failed (ambiguous or no match) — fall back to search
        results = self.search_cards_paged(f'name:"{name}"', max_results=1)
        if not results:
            # Last resort: broad search
            results = self.search_cards_paged(name, max_results=1)
        return _normalize_card(results[0]) if results else None

    def search_cards(self, query: str, page: int = 1) -> dict:
        result = self._get("/cards/search", params={
            "q": query,
            "page": page,
            "order": "edhrec",   # sort by EDHREC popularity — best synergy signal
            "unique": "cards",
        })
        return result if result else {"data": [], "has_more": False, "total_cards": 0}

    def search_cards_paged(self, query: str, max_results: int = 60) -> list[dict]:
        """Collect cards across pages up to max_results."""
        collected: list[dict] = []
        page = 1
        while len(collected) < max_results:
            data = self.search_cards(query, page)
            batch = data.get("data", [])
            if not batch:
                break
            collected.extend(_normalize_card(c) for c in batch)
            if not data.get("has_more"):
                break
            page += 1
        return collected[:max_results]
