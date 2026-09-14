import difflib
import json
import re
import threading
import time
from pathlib import Path
from typing import Optional
import requests

from app_paths import app_path

BASE_URL = "https://api.scryfall.com"

# Persistent on-disk cache of resolved cards (name -> normalized card). Cuts
# Scryfall API calls for every deck — generated or imported — and makes
# re-importing a decklist nearly free. Card data is effectively immutable, so
# the cache never needs invalidation for normal use.
_CACHE_DIR       = app_path("cache")
_CARD_CACHE_FILE = _CACHE_DIR / "scryfall_cards.json"
# A SEPARATE cache from _CARD_CACHE_FILE, deliberately: that one is keyed by name alone
# and is read by every other Scryfall lookup in the app (deck generation, theming, ...),
# which want the ordinary representative printing. Writing an imported deck's specific
# printing (a promo, a Secret Lair, a foil alt-art) into that shared cache would leak a
# one-off cosmetic choice into unrelated decks the next time the same name is looked up.
_PRINTING_CACHE_FILE = _CACHE_DIR / "scryfall_printings.json"

# Fields that vary BY PRINTING and are safe to overlay onto the generic card resolved by
# name — never oracle_text/mana_cost/type_line/power/toughness/colors/legalities, which
# describe the CARD and must keep coming from the name-based resolution everyone else
# shares, so an exact-printing lookup can never accidentally drift game-rules data.
PRINTING_FIELDS = (
    "id", "set", "set_name", "collector_number", "rarity", "artist",
    "released_at", "prices", "image_uris", "card_faces", "frame",
    "border_color", "full_art", "promo", "finishes", "foil", "nonfoil", "lang",
)


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


def price_key(name: str, set_code: str = "", cn: str = "") -> str:
    """Stable key for a priced collection row (matches collection.printing_key)."""
    return f"{(name or '').strip().lower()}|{(set_code or '').strip().upper()}|{(cn or '').strip()}"


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
        # Set by get_cards_collection when a batch request could not be completed, so a
        # caller that persists the result can tell a real "no such card" from a network
        # failure and refuse to cache the latter.
        self.last_lookup_incomplete = False
        self._cache_lock = threading.Lock()
        self._card_cache: dict[str, dict] = self._load_cache()
        self._printing_cache: dict[str, dict] = self._load_printing_cache()

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

    # ── Printing-specific cache (separate namespace — see PRINTING_FIELDS above) ────
    @staticmethod
    def _printing_cache_key(name: str, printing: Optional[dict]) -> Optional[str]:
        if not printing:
            return None
        if printing.get("id"):
            return f"id:{printing['id']}"
        if printing.get("set") and printing.get("collector_number"):
            return f"setcn:{printing['set'].strip().lower()}:{str(printing['collector_number']).strip().lower()}"
        if printing.get("set"):
            return f"setname:{printing['set'].strip().lower()}:{ScryfallClient._cache_key(name)}"
        return None

    def _load_printing_cache(self) -> dict[str, dict]:
        try:
            if _PRINTING_CACHE_FILE.exists():
                return json.loads(_PRINTING_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [scryfall] printing cache load failed ({e}); starting empty")
        return {}

    def _save_printing_cache(self) -> None:
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = _PRINTING_CACHE_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._printing_cache), encoding="utf-8")
            tmp.replace(_PRINTING_CACHE_FILE)
        except Exception as e:
            print(f"  [scryfall] printing cache save failed ({e})")

    def get_printing_overrides(self, entries: list[tuple[str, Optional[dict]]]) -> dict[str, dict]:
        """Resolve the EXACT printing named by each (name, printing_ref) pair.

        `printing_ref` is `{"id": scryfall_id}` (the strongest signal — Moxfield's
        `card.scryfall_id` and Archidekt's `card.uid` are both real Scryfall printing
        UUIDs, verified live against the API) or `{"set": code, "collector_number": n}`
        (a pasted decklist's "(SET) 123") or `{"set": code}` alone (set with no number).
        Entries with no printing_ref are skipped (return nothing for that name).

        Returns `{name_lower -> {field: value, ...}}` — only the PRINTING_FIELDS subset,
        meant to be overlaid onto a card already resolved by `get_cards_collection`, never
        used standalone (it carries no oracle_text/type_line/etc). A printing that fails
        to resolve (a stale id, a typo'd set code) is simply absent from the result — the
        caller keeps the generic card, which is exactly the pre-fix behavior, so this can
        never make an import worse, only more precise when it succeeds.
        """
        out: dict[str, dict] = {}
        by_id_idents: list[tuple[str, str, dict]] = []     # (name_key, cache_key, identifier)
        by_setcn_idents: list[tuple[str, str, dict]] = []
        by_setname_idents: list[tuple[str, str, dict]] = []
        seen: set[str] = set()

        for name, printing in entries:
            name_key = self._cache_key(name)
            if not name_key or name_key in seen:
                continue
            pkey = self._printing_cache_key(name, printing)
            if pkey is None:
                continue
            seen.add(name_key)
            cached = self._printing_cache.get(pkey)
            if cached is not None:
                out[name_key] = cached
                continue
            if printing.get("id"):
                by_id_idents.append((name_key, pkey, {"id": printing["id"]}))
            elif printing.get("set") and printing.get("collector_number"):
                by_setcn_idents.append((name_key, pkey, {
                    "set": printing["set"].strip().lower(),
                    "collector_number": str(printing["collector_number"]).strip(),
                }))
            else:
                by_setname_idents.append((name_key, pkey, {
                    "name": name.split("//")[0].strip(),
                    "set": printing["set"].strip().lower(),
                }))

        misses = by_id_idents + by_setcn_idents + by_setname_idents
        for i in range(0, len(misses), 75):
            chunk = misses[i:i + 75]
            data = self._post_collection([ident for _, _, ident in chunk])
            if data is None:
                continue
            found = [_normalize_card(c) for c in data.get("data", [])]
            by_id = {c.get("id"): c for c in found if c.get("id")}
            by_setcn = {((c.get("set") or "").lower(), str(c.get("collector_number") or "")): c
                        for c in found}
            for name_key, pkey, ident in chunk:
                card = None
                if "id" in ident:
                    card = by_id.get(ident["id"])
                elif "collector_number" in ident:
                    card = by_setcn.get((ident["set"], ident["collector_number"]))
                else:
                    card = next(
                        (c for c in found
                         if (c.get("set") or "").lower() == ident["set"]
                         and self._cache_key(c.get("name", "")) == self._cache_key(ident["name"])),
                        None)
                if card is None:
                    continue
                fields = {k: card[k] for k in PRINTING_FIELDS if k in card}
                out[name_key] = fields
                with self._cache_lock:
                    self._printing_cache[pkey] = fields
        if misses:
            self._save_printing_cache()
        return out

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

    def _post_collection(self, identifiers: list[dict]) -> Optional[dict]:
        """POST /cards/collection with the same retry discipline `_get` has.

        This used to be a bare POST whose only error handling was `continue`, so ONE
        429 or dropped connection silently discarded up to 75 cards — and the caller
        cannot tell that from "Scryfall says these aren't cards". A real import lost 7
        cards to this (Prismari, the Inspiration: Goldspan Dragon, Mental Misstep,
        Twinflame, ... all perfectly ordinary cards that resolve on request). They were
        exactly the names not already in the local cache, i.e. the one chunk that went
        to the network — and `deck_import` then froze that outcome in its deck cache, so
        every later import replayed the failure with no network call at all.

        Returns the parsed body, or None if the request could not be completed.
        """
        backoff = 1.0
        for _ in range(4):
            self._rate_limit()
            try:
                resp = self.session.post(
                    f"{BASE_URL}/cards/collection",
                    json={"identifiers": identifiers},
                    timeout=20,
                )
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code in (429, 503):
                    print(f"\n  [rate limit] waiting {backoff:.1f}s...", end=" ", flush=True)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 16.0)
                    self._last_request_time = time.monotonic()
                    continue
                return None   # 400/422 etc. — a retry sends the same bad body
            except requests.RequestException:
                time.sleep(backoff)
                backoff = min(backoff * 2, 16.0)
        return None

    def get_cards_collection(self, names: list[str]) -> dict[str, dict]:
        """
        Resolve many card names at once. Returns {requested_name_lower -> card}.

        Checks the persistent cache first, then asks Scryfall's /cards/collection
        endpoint (POST, up to 75 identifiers per request) only for the misses —
        so a 100-card import is ~2 API calls cold, and 0 once cached.
        Names that can't be resolved are simply absent from the result.
        """
        self.last_lookup_incomplete = False
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
            data = self._post_collection([{"name": n} for n in chunk])
            if data is None:
                # The REQUEST failed — that is not the same as Scryfall saying the cards
                # don't exist, and the difference matters because the caller writes this
                # result to a durable cache. Recorded so it can refuse to.
                self.last_lookup_incomplete = True
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

    def fetch_prices(self, rows: list[dict]) -> dict[str, Optional[float]]:
        """Current market price (USD) for collection rows, batched.

        `rows` are {name, set, cn}. A row with a known printing is priced as THAT
        printing (set + collector number identifier); a row without one is priced by
        name, which Scryfall answers with a representative printing. Scryfall's `usd`
        is an aggregated market price (it falls back to the foil price when a printing
        is foil-only), so this is an average-style valuation, not a vendor quote.

        Returns {price_key -> usd or None}; unpriced/unresolved rows map to None.
        Never raises — a Scryfall hiccup just yields fewer prices.
        """
        out: dict[str, Optional[float]] = {}
        ident_for: list[tuple[str, dict]] = []
        for r in rows:
            name = (r.get("name") or "").strip()
            if not name:
                continue
            st, cn = (r.get("set") or "").strip(), (r.get("cn") or "").strip()
            key = price_key(name, st, cn)
            if key in out:
                continue
            out[key] = None
            if st and cn:
                ident_for.append((key, {"set": st.lower(), "collector_number": cn}))
            else:
                ident_for.append((key, {"name": name.split("//")[0].strip()}))

        for i in range(0, len(ident_for), 75):
            chunk = ident_for[i:i + 75]
            try:
                self._rate_limit()
                resp = self.session.post(
                    f"{BASE_URL}/cards/collection",
                    json={"identifiers": [ident for _, ident in chunk]}, timeout=20,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json().get("data", []) or []
            except (requests.RequestException, ValueError):
                continue
            # Index the returned cards both by set+cn and by name so either identifier
            # style maps back to its row.
            by_setcn, by_name = {}, {}
            for c in data:
                prices = c.get("prices") or {}
                usd = prices.get("usd") or prices.get("usd_foil") or prices.get("usd_etched")
                try:
                    val = float(usd) if usd else None
                except (TypeError, ValueError):
                    val = None
                by_setcn[((c.get("set") or "").upper(), str(c.get("collector_number") or ""))] = val
                by_name.setdefault(self._cache_key(c.get("name", "")), val)
                front = (c.get("name") or "").split("//")[0].strip()
                by_name.setdefault(self._cache_key(front), val)
            for key, ident in chunk:
                if "set" in ident:
                    out[key] = by_setcn.get((ident["set"].upper(), str(ident["collector_number"])))
                else:
                    out[key] = by_name.get(self._cache_key(ident["name"]))
        return out

    def get_printings(self, name: str) -> list[dict]:
        """Every printing of a card: [{set, set_name, collector_number, usd, ...}].

        Uses an exact-name search with unique=prints so alt-art/showcase printings each
        appear. Sorted cheapest-first (printings with no price sink to the end)."""
        result = self._get("/cards/search", params={
            "q": f'!"{name}"', "unique": "prints", "order": "usd", "dir": "asc",
        })
        out: list[dict] = []
        for c in (result or {}).get("data", []) or []:
            prices = c.get("prices") or {}
            usd = prices.get("usd") or prices.get("usd_foil")
            try:
                usd_f = float(usd) if usd else None
            except (TypeError, ValueError):
                usd_f = None
            out.append({
                "name": c.get("name", name),
                "set": (c.get("set") or "").upper(),
                "set_name": c.get("set_name", ""),
                "collector_number": c.get("collector_number", ""),
                "usd": usd_f,
                "image": ((c.get("image_uris") or {}).get("normal")
                          or ((c.get("card_faces") or [{}])[0].get("image_uris") or {}).get("normal", "")),
            })
        out.sort(key=lambda p: (p["usd"] is None, p["usd"] if p["usd"] is not None else 0.0))
        return out

    def cheapest_printing(self, name: str) -> Optional[dict]:
        """The cheapest printing of a card — the sensible default when an import
        doesn't say which set a copy is from."""
        prints = self.get_printings(name)
        return prints[0] if prints else None

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
