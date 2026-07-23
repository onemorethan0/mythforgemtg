import difflib
import json
import re
import threading
import time
from pathlib import Path
from typing import Optional
import requests

BASE_URL = "https://api.scryfall.com"

# Persistent on-disk cache of resolved cards (name -> normalized card). Cuts
# Scryfall API calls for every deck — generated or imported — and makes
# re-importing a decklist nearly free. Card data is effectively immutable, so
# the cache never needs invalidation for normal use.
_CACHE_DIR       = Path("cache")
_CARD_CACHE_FILE = _CACHE_DIR / "scryfall_cards.json"


def _fuzzy_name_key(name: str) -> str:
    """Lowercase, strip punctuation/accents-ish noise, collapse space — for comparing a
    requested decklist name against the card Scryfall's fuzzy search returned."""
    import unicodedata
    n = unicodedata.normalize("NFKD", (name or "")).encode("ascii", "ignore").decode()
    n = n.split("//", 1)[0]                       # compare on the front face
    n = re.sub(r"[^a-z0-9 ]+", " ", n.lower())
    return re.sub(r"\s+", " ", n).strip()


def _fuzzy_is_plausible(requested: str, canonical: str, threshold: float = 0.72) -> bool:
    """True when a fuzzy match plausibly IS the requested card.

    Guards against Scryfall's fuzzy endpoint silently substituting an unrelated card for
    a typo — which would change an imported paper decklist. Accepts near-misses
    (punctuation/accents, "Krenko Mob Boss" -> "Krenko, Mob Boss") and front-face/prefix
    matches; rejects "sol rng" -> "Oathsworn Giant".
    """
    a, b = _fuzzy_name_key(requested), _fuzzy_name_key(canonical)
    if not a or not b:
        return False
    if a == b or b.startswith(a) or a.startswith(b):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= threshold


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
        self._cache_lock = threading.Lock()
        self._card_cache: dict[str, dict] = self._load_cache()

    # ── Persistent card cache ──────────────────────────────────────────────────
    @staticmethod
    def _cache_key(name: str) -> str:
        return (name or "").strip().lower()

    def _load_cache(self) -> dict[str, dict]:
        try:
            if _CARD_CACHE_FILE.exists():
                return json.loads(_CARD_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [scryfall] cache load failed ({e}); starting empty")
        return {}

    def _save_cache(self) -> None:
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = _CARD_CACHE_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._card_cache), encoding="utf-8")
            tmp.replace(_CARD_CACHE_FILE)
        except Exception as e:
            print(f"  [scryfall] cache save failed ({e})")

    def _cache_get(self, name: str) -> Optional[dict]:
        with self._cache_lock:
            return self._card_cache.get(self._cache_key(name))

    def _cache_put(self, names, card: dict, save: bool = True) -> None:
        """Store a card under one or more lookup names (input + canonical)."""
        if not card:
            return
        if isinstance(names, str):
            names = [names]
        with self._cache_lock:
            for n in names:
                key = self._cache_key(n)
                if key:
                    self._card_cache[key] = card
        if save:
            self._save_cache()

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
        cached = self._cache_get(name)
        if cached is not None:
            return cached

        param_key = "fuzzy" if fuzzy else "exact"
        card = self._get("/cards/named", params={param_key: name})
        if card is not None:
            norm = _normalize_card(card)
            self._cache_put([name, norm.get("name", "")], norm)
            return norm
        if not fuzzy:
            return None
        # Fuzzy named endpoint failed (ambiguous or no match) — fall back to search
        results = self.search_cards_paged(f'name:"{name}"', max_results=1)
        if not results:
            # Last resort: broad search
            results = self.search_cards_paged(name, max_results=1)
        if results:
            norm = _normalize_card(results[0])
            self._cache_put([name, norm.get("name", "")], norm)
            return norm
        return None

    def get_cards_collection(self, names: list[str]) -> dict[str, dict]:
        """
        Resolve many card names at once. Returns {requested_name_lower -> card}.

        Checks the persistent cache first, then asks Scryfall's /cards/collection
        endpoint (POST, up to 75 identifiers per request) only for the misses —
        so a 100-card import is ~2 API calls cold, and 0 once cached.
        Names that can't be resolved are simply absent from the result.
        """
        out: dict[str, dict] = {}
        misses: list[str] = []
        seen: set[str] = set()
        for n in names:
            key = self._cache_key(n)
            if not key or key in seen:
                continue
            seen.add(key)
            c = self._cache_get(n)
            if c is not None:
                out[key] = c
            else:
                misses.append(n)

        for i in range(0, len(misses), 75):
            chunk = misses[i:i + 75]
            self._rate_limit()
            try:
                resp = self.session.post(
                    f"{BASE_URL}/cards/collection",
                    json={"identifiers": [{"name": n} for n in chunk]},
                    timeout=20,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
            except requests.RequestException:
                continue
            # Map each returned card back to the requested name(s). Scryfall may
            # normalise casing/spelling, so match by the card's own name too.
            found = [_normalize_card(c) for c in data.get("data", [])]
            by_canon = {self._cache_key(c.get("name", "")): c for c in found}
            for req in chunk:
                key = self._cache_key(req)
                card = by_canon.get(key)
                if card is None and "//" in req:
                    # Double-faced / MDFC cards (e.g. "Avatar Aang // Aang, Master
                    # of Elements") are NOT matched by the collection endpoint on
                    # their full "Front // Back" name — only the front face resolves.
                    # Split/aftermath cards ("Fire // Ice") already matched above by
                    # their full name, so this only fires for genuine DFC misses.
                    front = req.split("//", 1)[0].strip()
                    if front:
                        card = self.get_card_by_name(front, fuzzy=False)
                if card is None:
                    # Exact canonical miss — a fuzzy lookup is a convenience for near
                    # misses (missing comma/accent, DFC front face), but Scryfall's fuzzy
                    # will happily return a COMPLETELY different card for a typo
                    # ("sol rng" -> "Oathsworn Giant"). Silently swapping that into an
                    # imported paper decklist changes the user's deck, so only accept a
                    # fuzzy hit that actually resembles what was asked for; otherwise
                    # leave it unresolved and let the caller surface it.
                    cand = self.get_card_by_name(req, fuzzy=True)
                    card = cand if _fuzzy_is_plausible(req, (cand or {}).get("name", "")) else None
                if card is not None:
                    out[key] = card
                    self._cache_put([req, card.get("name", "")], card, save=False)
        self._save_cache()
        return out

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
