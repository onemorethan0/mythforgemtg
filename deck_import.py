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

from app_paths import app_path

_CACHE_DIR = app_path("cache", "imported_decks")
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
    # Names in the decklist's FIRST paragraph, set only when nothing tagged a
    # commander and the shape encodes one positionally (Moxfield's plain text export
    # writes the commander(s), a blank line, then the maindeck). A hint, not a claim:
    # `_resolve` promotes these only if Scryfall says they're legendary — otherwise
    # they stay ordinary maindeck cards. See _promote_leading_commander.
    leading_names: list[str] = field(default_factory=list)


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
    return _parse_archidekt(_http_json(f"https://archidekt.com/api/decks/{deck_id}/"))


def _parse_archidekt(data: dict) -> RawDeck:
    """Archidekt API payload → RawDeck. Pure, so it can be tested without network."""
    # Archidekt decks carry their OWN answer to "is this category in the deck?" —
    # a deck-level `categories` list where each entry has `includedInDeck`. Judging
    # by category NAME instead got it wrong in both directions: a user category
    # marked not-in-deck ("Cuts", "Considering", "Sideboard ideas") was imported as
    # real cards, and a category literally named "Sideboard" that the user had
    # INCLUDED was thrown away. Measured over 40 real corpus decks: the two rules
    # disagree on 7 of them. Worst case (deck 11428593) the name rule imported a
    # 166-card "deck" — 66 cards the user had filed under "cut", "Too sauced",
    # "Other maybeboard stuff" and four more excluded piles; deck 11796422 goes the
    # other way, with 2 real cards in a category named "Sideboard" that the user had
    # includedInDeck=true. Most divergent decks land exactly on 100 under this rule.
    excluded = {str(c.get("name", "")).lower()
                for c in (data.get("categories") or [])
                if isinstance(c, dict) and c.get("includedInDeck") is False}
    # Fallback for responses with no category metadata at all: the old name test.
    _DEFAULT_EXCLUDED = {"maybeboard", "sideboard"}
    known = {str(c.get("name", "")).lower()
             for c in (data.get("categories") or []) if isinstance(c, dict)}

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
        if any(k in excluded or (k not in known and k in _DEFAULT_EXCLUDED) for k in low):
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
_QTY_RE = re.compile(r"^\s*(?P<qty>\d+)\s*[xX]?\s+(?P<rest>\S.*)$")

# Trailing metadata a decklist line can carry AFTER the card name. Every real
# export appends some combination of these, and a single mega-regex could not
# cover them all — so they're peeled off one at a time, right to left, until the
# remainder is just the name:
#   "(C21) 263"        set code + collector number  (Moxfield / MTGA / Archidekt)
#   "[Ramp{noPrice}]"  Archidekt category tag       ("[Commander{top}]" names the commander!)
#   "[M11] 149"        bracketed set + number       (MTGO / Deckbox style)
#   "*CMDR* *F*"       Moxfield flags
#   "#263"             bare collector-number comment
# Before this, the lazy name group swallowed the whole tail, so
# "1x Sol Ring (c21) 263 [Ramp{noPrice}]" resolved as a card literally named
# "Sol Ring (c21) 263 [Ramp{noPrice}]" — i.e. it silently vanished from the
# user's deck into `unresolved`. Archidekt's own text export takes that path, and
# its "[Commander{top}]" tag was lost with it, so the commander was dropped too
# and _apply_auto_face then elected some other card into the face slot.
_TRAIL_FLAG  = re.compile(r"\s*\*(?P<tag>[^*]*)\*\s*$")
_TRAIL_BRACK = re.compile(r"\s*\[(?P<tag>[^\[\]]*)\]\s*$")
_TRAIL_SET   = re.compile(r"\s*\((?P<tag>[A-Za-z0-9]{2,6})\)(?:\s+[A-Za-z0-9★*\-]{1,8})?\s*$")
_TRAIL_HASH  = re.compile(r"\s+#\S*\s*$")
# Bare trailing collector number. Digits-only (plus an optional variant letter or
# ★) and only applied once the line has shown a printing token, so a card whose
# name merely ends in a word is never truncated.
_TRAIL_CN    = re.compile(r"\s+\d{1,5}[a-z★]?\s*$")
# "SB: 1 Sol Ring" — Apprentice/MWS sideboard prefix.
_SB_PREFIX   = re.compile(r"^\s*SB:\s*", re.I)


def _strip_line_metadata(rest: str) -> tuple[str, list[str]]:
    """Peel trailing printing/category metadata off a decklist line.

    Returns ``(card_name, tags)`` where tags are the lower-cased contents of any
    ``*flag*`` / ``[category]`` groups found — the caller reads those to spot a
    commander or a sideboard entry. Set codes and collector numbers are dropped.
    """
    tags: list[str] = []
    saw_printing = False
    for _ in range(12):          # bounded: a line has a handful of trailing groups
        m = _TRAIL_FLAG.search(rest)
        if m:
            tags.append((m.group("tag") or "").strip().lower())
            rest = rest[:m.start()].rstrip()
            continue
        m = _TRAIL_BRACK.search(rest)
        if m:
            tags.append((m.group("tag") or "").strip().lower())
            rest = rest[:m.start()].rstrip()
            saw_printing = True
            continue
        m = _TRAIL_SET.search(rest)
        if m:
            rest = rest[:m.start()].rstrip()
            saw_printing = True
            continue
        m = _TRAIL_HASH.search(rest)
        if m:
            rest = rest[:m.start()].rstrip()
            continue
        # Only strip a bare number once the line has shown (or still shows) a
        # printing token — otherwise a legitimate name could lose its last word.
        if saw_printing or "[" in rest or "(" in rest:
            m = _TRAIL_CN.search(rest)
            if m and rest[:m.start()].strip():
                rest = rest[:m.start()].rstrip()
                continue
        break
    return rest.strip(), [t for t in tags if t]

# Zone headers. Every real export decorates them differently, and all three
# decorations below used to miss — which is worse than dropping a card, because a
# missed "Sideboard (15)" folds fifteen cards the user never wanted INTO their
# maindeck, and a missed "Commander (1)" leaves the commander in the maindeck for
# _apply_auto_face to replace with whatever card happened to cost the most.
#   "Commander"      MTGA / paper
#   "Commander:"     paper (and Myth Forge's own export)
#   "Commander (1)"  Archidekt / TappedOut / Moxfield category exports
#   "//Commander"    Deckstats
_ZONE_HEADER = re.compile(
    r"""^\s*(?://\s*)?
        (?P<zone>commanders?|companions?|deck|mainboard|maindeck
                |sideboard|maybeboard|tokens?)
        \s*(?:\(\s*\d+\s*\))?\s*:?\s*$
    """, re.I | re.VERBOSE)
# INLINE form: "Commander: Krenko, Mob Boss" — the single most common way a paper
# decklist names its commander (and the format Myth Forge's own export writes). The
# header regex above is end-anchored, so this line used to match NOTHING: no quantity,
# no section, so it was silently DISCARDED. With the commander gone, _apply_auto_face
# then elected a face out of the maindeck and pulled that card into the commander slot —
# i.e. importing a paper deck silently changed which cards were in it.
_COMMANDER_INLINE = re.compile(r"^\s*commanders?\s*:\s*(?P<name>\S.*?)\s*$", re.I)
# A NON-zone category header: "Creatures (30)", "//Artifacts", "Ramp (12):". These
# must reset the section to the maindeck — a Deckstats list goes "//Commander" then
# "//Creatures", and treating the second as a plain comment left the section stuck on
# `commander`, so every creature in the deck was read as a commander.
_CATEGORY_HEADER = re.compile(
    r"^\s*(?://\s*)?[A-Za-z][A-Za-z0-9 '&/\-]*\s*\(\s*\d+\s*\)\s*:?\s*$")
_COMMENT_CATEGORY = re.compile(r"^\s*//\s*\S")
_IGNORE_SECTIONS = {"sideboard", "maybeboard", "token", "tokens"}


def _parse_text(text: str) -> RawDeck:
    commander_names: list[str] = []
    card_entries: list[tuple[str, int]] = []
    section = "deck"            # current section
    tagged_commander = False    # a header/tag named the commander explicitly
    # Entries in the first paragraph, recorded for the header-less Moxfield form
    # (see RawDeck.leading_names).
    leading: list[str] = []
    paragraph = 0
    blank_run = False

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            if not blank_run:
                paragraph += 1
                blank_run = True
            continue
        blank_run = False

        m_zone = _ZONE_HEADER.match(line)
        if m_zone:
            zone = m_zone.group("zone").lower()
            section = "commander" if zone.startswith("commander") else zone
            if section == "commander":
                tagged_commander = True
            continue
        m_inline = _COMMANDER_INLINE.match(line)
        if m_inline:
            # "Commander: <name>" names the commander on the same line — record it and
            # stay in the deck section (the following lines are the maindeck).
            name, _ = _strip_line_metadata(m_inline.group("name").strip())
            if name:
                commander_names.append(name)
                tagged_commander = True
            continue
        # A non-zone category header ("Creatures (30)", "//Artifacts") returns the
        # reader to the maindeck. Without this a Deckstats list that opens
        # "//Commander" then "//Creatures" stayed stuck in the commander section and
        # read every creature in the deck as a commander.
        if _CATEGORY_HEADER.match(line) or _COMMENT_CATEGORY.match(line):
            section = "deck"
            continue
        if line.startswith("#"):
            continue
        sb_line = bool(_SB_PREFIX.match(line))
        if sb_line:
            line = _SB_PREFIX.sub("", line, count=1)
        m = _QTY_RE.match(line)
        if not m:
            # A bare "Commander Name" line with no quantity right under the header
            if section == "commander":
                name, _ = _strip_line_metadata(line)
                if name:
                    commander_names.append(name)
            continue
        qty  = int(m.group("qty"))
        name, tags = _strip_line_metadata(m.group("rest"))
        if not name:
            continue
        if sb_line or section in _IGNORE_SECTIONS:
            continue
        # A per-line tag overrides the current section: Moxfield writes "*CMDR*",
        # Archidekt's text export writes "[Commander{top}]" / "[Sideboard]" with no
        # section headers at all.
        if any(t.startswith(("sideboard", "maybeboard", "token")) for t in tags):
            continue
        if (section == "commander"
                or any(t.startswith(("cmdr", "commander")) for t in tags)):
            commander_names.append(name)
            tagged_commander = True
        else:
            card_entries.append((name, qty))
            if paragraph == 0 and qty == 1:
                leading.append(name)

    if not commander_names and not card_entries:
        raise DeckImportError(
            "Couldn't find any cards in that text. Use lines like '1 Sol Ring', "
            "and put your commander under a 'Commander' header (or tag it *CMDR*)."
        )
    # Only meaningful when nothing named a commander, and only for the shape that
    # actually encodes one positionally: a short opening paragraph, more cards after.
    hint = ([] if (tagged_commander or not leading or len(leading) > 2
                   or len(card_entries) <= len(leading)) else list(leading))
    return RawDeck(name="Imported deck", source="text",
                   commander_names=commander_names, card_entries=card_entries,
                   leading_names=hint)


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
    imported = ImportedDeck(name=raw.name, source=raw.source, commander=commander,
                            deck=deck, partners=partners, unresolved=unresolved)
    if commander is None:
        _promote_leading_commander(imported, raw.leading_names)
    return imported


def _is_legendary_creature(card: dict) -> bool:
    tl = (card.get("type_line") or "").lower()
    # Read the FRONT face: a legendary creature that transforms into something else
    # is still a legal commander.
    front = tl.split("//", 1)[0]
    return "legendary" in front and ("creature" in front
                                     or "can be your commander" in (card.get("oracle_text") or "").lower())


def _promote_leading_commander(imp: "ImportedDeck", leading_names: list[str]) -> None:
    """Promote a positionally-encoded commander out of the maindeck.

    Moxfield's plain text export writes the commander(s), a blank line, then the
    maindeck — with no header and no tag. Every such deck therefore arrived with no
    commander zone, and `_apply_auto_face` then elected whichever legendary creature
    cost the MOST mana into the face slot. On a 100-card list that is usually the
    wrong card, and the real commander stayed buried in the 99.

    This only fires on that exact shape (`RawDeck.leading_names`, which `_parse_text`
    populates only for a short opening paragraph followed by more cards) and only for
    cards Scryfall confirms are legendary. A non-legendary opener is left alone and
    falls through to the ordinary election, so the guess can't invent a commander.
    """
    if imp.commander is not None or not leading_names:
        return
    by_name = {(c.get("name") or "").lower(): c for c in imp.deck}
    picks = [by_name.get(n.lower()) for n in leading_names]
    if not picks or any(c is None or not _is_legendary_creature(c) for c in picks):
        return
    promoted: list[dict] = []
    for entry in picks:
        one = dict(entry)
        one.pop("quantity", None)
        promoted.append(one)
        if int(entry.get("quantity", 1) or 1) > 1:
            entry["quantity"] = int(entry["quantity"]) - 1
        else:
            imp.deck = [c for c in imp.deck if c is not entry]
    imp.commander = promoted[0]
    imp.partners = promoted[1:] + list(imp.partners)


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
