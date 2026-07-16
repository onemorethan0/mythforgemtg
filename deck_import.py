"""
Import an existing decklist from a URL (Moxfield, Archidekt, ManaBox) or pasted
text, and resolve it into the (commander, deck) card-dict shape the rest of the
build pipeline already consumes (themer → image_gen → renderer → exporter).

This lets a user RETHEME a deck they already own instead of generating a new
99-card list from a commander.

Design notes / concessions:
  • Card data comes from Scryfall via ScryfallClient.get_cards_collection (batch,
    cached) — a 100-card import is ~2 API calls cold and 0 once cached.
  • Resolved decks are cached to cache/imported_decks/ keyed by source+id (or a
    hash of pasted text), so re-importing the same deck costs zero network calls
    (pass force_refresh=True to re-pull).
  • Duplicate cards (basic lands especially) are aggregated into ONE entry with a
    "quantity" field. The pipeline themes/generates art once per unique card; the
    exporter replicates by quantity so every physical proxy is still produced.
  • Moxfield's API is Cloudflare/rate-limit guarded, so it is best-effort. The
    pasted-decklist path always works and covers ManaBox (export as text) and any
    other site.
  • Partner/companion commanders: the first commander is the deck's "face"; the
    rest are kept in `partners` and folded into the maindeck for theming/render.
  • ANY decklist is importable, not just Commander decks. When a deck has no
    commander zone (a 60-card constructed list, an un-tagged singleton, etc.) a
    display "face" is auto-elected from the maindeck (`_apply_auto_face`) — a
    legendary creature if present, else the splashiest card — and one copy is
    pulled into the face slot, so the rest of the pipeline (which expects a face
    card) works unchanged. The user can still override the face by name.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

_CACHE_DIR = Path("cache") / "imported_decks"
_HTTP_HEADERS = {
    "User-Agent": "MythForgeDeckImporter/1.0 (personal MTG proxy tool)",
    "Accept": "application/json",
}
_HTTP_TIMEOUT = 20

# Basic land names never need a Scryfall round trip to identify as "duplicatable".
_BASICS = {"plains", "island", "swamp", "mountain", "forest", "wastes",
           "snow-covered plains", "snow-covered island", "snow-covered swamp",
           "snow-covered mountain", "snow-covered forest"}


class DeckImportError(Exception):
    """Raised when a deck URL can't be fetched/parsed. Message is user-facing."""


@dataclass
class RawDeck:
    """Source-agnostic intermediate: just names + quantities + which are commanders."""
    name: str
    source: str
    commander_names: list[str]
    card_entries: list[tuple[str, int]]   # (name, quantity), maindeck only


@dataclass
class ImportedDeck:
    name: str
    source: str
    commander: Optional[dict]             # scryfall card dict (the "face")
    deck: list[dict]                      # unique maindeck cards, each with "quantity"
    partners: list[dict] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    auto_face: bool = False               # commander was auto-elected (no commander zone)

    def total_cards(self) -> int:
        return (1 if self.commander else 0) + len(self.partners) + \
            sum(c.get("quantity", 1) for c in self.deck)

    def to_json(self) -> dict:
        return {
            "name": self.name, "source": self.source,
            "commander": self.commander, "partners": self.partners,
            "deck": self.deck, "unresolved": self.unresolved,
            "auto_face": self.auto_face,
        }

    @classmethod
    def from_json(cls, d: dict) -> "ImportedDeck":
        return cls(name=d.get("name", ""), source=d.get("source", ""),
                   commander=d.get("commander"), deck=d.get("deck", []),
                   partners=d.get("partners", []), unresolved=d.get("unresolved", []),
                   auto_face=bool(d.get("auto_face", False)))


# ── Source detection ───────────────────────────────────────────────────────────

def detect_source(text: str) -> str:
    """Return 'moxfield' | 'archidekt' | 'manabox' | 'text'."""
    t = (text or "").strip()
    if t.lower().startswith(("http://", "https://")):
        host = (urlparse(t).hostname or "").lower()
        if "moxfield" in host:
            return "moxfield"
        if "archidekt" in host:
            return "archidekt"
        if "manabox" in host:
            return "manabox"
        raise DeckImportError(
            f"Unsupported deck site: {host or t}. Supported: Moxfield, Archidekt. "
            "For any other site (incl. ManaBox), paste the decklist text instead."
        )
    return "text"


# ── Site fetchers → RawDeck ─────────────────────────────────────────────────────

def _http_json(url: str) -> dict:
    try:
        resp = requests.get(url, headers=_HTTP_HEADERS, timeout=_HTTP_TIMEOUT)
    except requests.RequestException as e:
        raise DeckImportError(f"Could not reach {url}: {e}")
    if resp.status_code == 404:
        raise DeckImportError("Deck not found (404). Is the deck public, and the URL correct?")
    if resp.status_code in (401, 403):
        raise DeckImportError(
            "The deck site refused the request (it may be private or blocking "
            "automated access). Make the deck public, or paste its decklist text instead."
        )
    if resp.status_code != 200:
        raise DeckImportError(f"Deck site returned HTTP {resp.status_code}.")
    try:
        return resp.json()
    except ValueError:
        raise DeckImportError("Deck site did not return valid JSON.")


def _fetch_moxfield(url: str) -> RawDeck:
    # publicId is the last non-empty path segment of /decks/<publicId>
    parts = [p for p in urlparse(url).path.split("/") if p]
    public_id = parts[-1] if parts else ""
    if not public_id:
        raise DeckImportError("Could not read the Moxfield deck id from that URL.")
    data = _http_json(f"https://api2.moxfield.com/v2/decks/all/{public_id}")

    def _entries(board) -> list[tuple[str, int]]:
        # v2 boards are dicts: {cardName: {quantity, card:{name}}}
        out = []
        if isinstance(board, dict):
            for entry in board.values():
                card = entry.get("card") or {}
                name = card.get("name") or entry.get("name")
                if name:
                    out.append((name, int(entry.get("quantity", 1) or 1)))
        return out

    commander_names = [n for n, _ in _entries(data.get("commanders"))]
    commander_names += [n for n, _ in _entries(data.get("companions"))]
    card_entries = _entries(data.get("mainboard"))
    return RawDeck(name=data.get("name", "Imported deck"), source="moxfield",
                   commander_names=commander_names, card_entries=card_entries)


def _fetch_archidekt(url: str) -> RawDeck:
    m = re.search(r"/decks/(\d+)", urlparse(url).path)
    if not m:
        raise DeckImportError("Could not read the Archidekt deck id from that URL.")
    deck_id = m.group(1)
    data = _http_json(f"https://archidekt.com/api/decks/{deck_id}/")

    commander_names: list[str] = []
    card_entries: list[tuple[str, int]] = []
    for c in data.get("cards", []):
        qty = int(c.get("quantity", 1) or 1)
        cats = [str(x) for x in (c.get("categories") or [])]
        name = (((c.get("card") or {}).get("oracleCard") or {}).get("name")
                or (c.get("card") or {}).get("name"))
        if not name:
            continue
        low = [x.lower() for x in cats]
        if "maybeboard" in low or "sideboard" in low:
            continue
        if "commander" in low:
            commander_names.append(name)
        else:
            card_entries.append((name, qty))
    return RawDeck(name=data.get("name", "Imported deck"), source="archidekt",
                   commander_names=commander_names, card_entries=card_entries)


def _fetch_manabox(url: str) -> RawDeck:
    # ManaBox is a mobile app with no documented public web-deck API. Share links
    # open the app, not a JSON endpoint. The reliable path is exporting the list
    # from the app and pasting it — direct the user there.
    raise DeckImportError(
        "ManaBox doesn't expose a public web API for deck links. In the ManaBox "
        "app, open your deck → Share/Export → copy as text, then paste the "
        "decklist here instead of the link."
    )


# ── Pasted decklist text → RawDeck ──────────────────────────────────────────────

# "1 Sol Ring", "1x Sol Ring", "1 Sol Ring (C21) 263", "1 Sol Ring *CMDR*"
_LINE_RE = re.compile(
    r"""^\s*(?P<qty>\d+)\s*[xX]?\s+          # quantity
        (?P<name>.+?)                         # card name (lazy)
        (?:\s*\((?P<set>[A-Za-z0-9]{2,6})\)\s*[A-Za-z0-9\-]*)?   # optional (SET) num
        (?P<flags>(?:\s*\*[^*]+\*)*)\s*$       # optional *CMDR* / *F* flags
    """, re.VERBOSE)

_COMMANDER_HEADER = re.compile(r"^\s*(commander|commanders)\s*:?\s*$", re.I)
_SECTION_HEADER = re.compile(
    r"^\s*(deck|mainboard|maindeck|companion|sideboard|maybeboard|tokens?)\s*:?\s*$", re.I)
_IGNORE_SECTIONS = {"sideboard", "maybeboard", "token", "tokens"}


def _parse_text(text: str) -> RawDeck:
    commander_names: list[str] = []
    card_entries: list[tuple[str, int]] = []
    section = "deck"            # current section
    saw_commander_header = False

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "//")):
            continue
        if _COMMANDER_HEADER.match(line):
            section = "commander"; saw_commander_header = True
            continue
        m_sec = _SECTION_HEADER.match(line)
        if m_sec:
            section = m_sec.group(1).lower()
            continue
        m = _LINE_RE.match(line)
        if not m:
            # A bare "Commander Name" line with no quantity right under the header
            if section == "commander":
                commander_names.append(line)
            continue
        qty = int(m.group("qty"))
        name = m.group("name").strip()
        flags = (m.group("flags") or "").lower()
        if section in _IGNORE_SECTIONS:
            continue
        if section == "commander" or "*cmdr*" in flags or "*commander*" in flags:
            commander_names.append(name)
        else:
            card_entries.append((name, qty))

    if not commander_names and not card_entries:
        raise DeckImportError(
            "Couldn't find any cards in that text. Use lines like '1 Sol Ring', "
            "and put your commander under a 'Commander' header (or tag it *CMDR*)."
        )
    return RawDeck(name="Imported deck", source="text",
                   commander_names=commander_names, card_entries=card_entries)


# ── Resolve names → cards ───────────────────────────────────────────────────────

def _resolve(raw: RawDeck, scryfall) -> ImportedDeck:
    all_names = list(raw.commander_names) + [n for n, _ in raw.card_entries]
    resolved = scryfall.get_cards_collection(all_names)   # name_lower -> card

    def look(n: str) -> Optional[dict]:
        return resolved.get((n or "").strip().lower())

    unresolved: list[str] = []

    commanders: list[dict] = []
    for n in raw.commander_names:
        c = look(n)
        (commanders.append(c) if c else unresolved.append(n))
    commander = commanders[0] if commanders else None
    partners = commanders[1:]

    # Aggregate maindeck by canonical name → one entry with summed quantity.
    agg: dict[str, dict] = {}
    order: list[str] = []
    for name, qty in raw.card_entries:
        c = look(name)
        if not c:
            unresolved.append(name)
            continue
        key = c.get("name", name)
        if key not in agg:
            entry = dict(c)
            entry["quantity"] = 0
            agg[key] = entry
            order.append(key)
        agg[key]["quantity"] += max(1, qty)

    deck = [agg[k] for k in order]
    return ImportedDeck(name=raw.name, source=raw.source, commander=commander,
                        deck=deck, partners=partners, unresolved=unresolved)


# ── Auto-elect a face for commanderless decks ────────────────────────────────────

def _elect_face(deck: list[dict]) -> Optional[dict]:
    """Pick a display "face" for a deck that has no commander zone — a pasted
    60-card constructed list, a singleton list with the commander un-tagged, etc.
    Prefers the most natural hero: a legendary creature, then a 'can be your
    commander' card / legendary planeswalker, then the splashiest creature, then
    the highest-mana-value card. Returns a dict that is an element of `deck` (the
    caller pulls one physical copy out into the face slot)."""
    if not deck:
        return None

    def mv(c) -> float:
        try:
            return float(c.get("cmc", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    def tl(c) -> str:
        return (c.get("type_line") or "").lower()

    def otext(c) -> str:
        return (c.get("oracle_text") or "").lower()

    tiers = [
        lambda c: "legendary" in tl(c) and "creature" in tl(c),
        lambda c: "can be your commander" in otext(c),
        lambda c: "legendary" in tl(c) and "planeswalker" in tl(c),
        lambda c: "creature" in tl(c),
        lambda c: True,
    ]
    for pred in tiers:
        cands = [c for c in deck if pred(c)]
        if cands:
            return max(cands, key=mv)
    return None


def _apply_auto_face(imp: ImportedDeck) -> None:
    """If an imported deck has no commander, elect a display face from the
    maindeck and pull ONE physical copy into the commander slot, so the rest of
    the build/theme/render/export pipeline (which everywhere expects a face card)
    works for ANY imported decklist, not just Commander decks. Idempotent: a
    no-op when a commander is already present. Applied on every import_deck
    return (fresh OR cached) so it also upgrades pre-existing cache entries."""
    if imp.commander is not None or not imp.deck:
        return
    face = _elect_face(imp.deck)
    if face is None:
        return
    commander = dict(face)
    commander.pop("quantity", None)
    if int(face.get("quantity", 1) or 1) > 1:
        face["quantity"] = int(face["quantity"]) - 1
    else:
        imp.deck = [c for c in imp.deck if c is not face]
    imp.commander = commander
    imp.auto_face = True


# ── Public API ──────────────────────────────────────────────────────────────────

_FETCHERS = {
    "moxfield":  _fetch_moxfield,
    "archidekt": _fetch_archidekt,
    "manabox":   _fetch_manabox,
}


def _cache_id(source: str, source_input: str) -> str:
    if source == "text":
        h = hashlib.sha1(source_input.strip().encode("utf-8")).hexdigest()[:16]
        return f"text_{h}"
    # URL: use host + last id-ish path segment
    p = urlparse(source_input)
    seg = [s for s in p.path.split("/") if s]
    ident = seg[-1] if seg else "deck"
    ident = re.sub(r"[^A-Za-z0-9_\-]", "", ident)[:40]
    return f"{source}_{ident}"


def import_deck(source_input: str, scryfall, force_refresh: bool = False) -> ImportedDeck:
    """
    Import a deck from a URL or pasted decklist text. Results are cached to disk;
    re-importing the same source returns the cached deck with no network calls
    unless force_refresh=True.
    """
    source_input = (source_input or "").strip()
    if not source_input:
        raise DeckImportError("No deck URL or decklist provided.")
    source = detect_source(source_input)
    cache_id = _cache_id(source, source_input)
    cache_file = _CACHE_DIR / f"{cache_id}.json"

    if not force_refresh and cache_file.exists():
        try:
            imported = ImportedDeck.from_json(json.loads(cache_file.read_text(encoding="utf-8")))
            _apply_auto_face(imported)   # also upgrades older commanderless caches
            return imported
        except Exception:
            pass   # corrupt cache → re-fetch

    if source == "text":
        raw = _parse_text(source_input)
    else:
        raw = _FETCHERS[source](source_input)

    imported = _resolve(raw, scryfall)

    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(imported.to_json()), encoding="utf-8")
    except Exception as e:
        print(f"  [deck_import] cache write failed ({e})")

    # Elect a face AFTER caching the raw resolution, so the cache stays a faithful
    # mirror of the source and election (deterministic) re-runs on each load.
    _apply_auto_face(imported)
    return imported
