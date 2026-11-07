"""Is this a legal Commander deck? Deck-level rules check, pure and offline.

Every mainstream deck site (Moxfield, Archidekt, Deckstats, TappedOut) tells you on the
deck page whether the list can be registered. Myth Forge could tell you its bracket, its
strength axes and its mana health, but not that an imported list held 101 cards, a second
Sol Ring, a banned card or a card outside the commander's colours. The Deck Mentor could
check ONE card when asked; nothing checked the deck.

What is checked (the Commander deck-construction rules, CR 903):

  size       exactly 100 cards, command zone included                      (903.5a)
  singleton  one copy of each English name, except basic lands and cards     (903.5b)
             whose own text overrides it ("A deck can have any number of
             cards named ...", "up to seven cards named Seven Dwarves")
  identity   every card's colour identity inside the command zone's          (903.5c)
  legality   Scryfall `legalities.commander` is "banned" or "not_legal"
  commander  the face card may be a commander (legendary creature, or        (903.3)
             "can be your commander"), and every pairing is a legal one

Honest under-count, never a guess: a card that carries no `legalities` (an old stored
deck.json) is counted in `unverified`, not reported legal or banned. A card with no
colour-identity field is skipped by the identity check for the same reason.

Not checked: companion deck-building conditions and sideboards (Myth Forge stores no
sideboard), and the Rule 0 conversation a pod may have about any of this.
"""
from __future__ import annotations

import re

import commander_analysis

DECK_SIZE = 100

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
_ANY_NUMBER_RE = re.compile(r"a deck can have any number of cards named", re.I)
_UP_TO_RE = re.compile(r"a deck can have up to (\w+) cards named", re.I)


def _name(card: dict) -> str:
    return (card.get("name") or card.get("original_name") or "").strip()


def _qty(card: dict) -> int:
    try:
        return max(1, int(card.get("quantity", 1) or 1))
    except (TypeError, ValueError):
        return 1


def _text(card: dict) -> str:
    parts = [card.get("oracle_text") or ""]
    parts += [f.get("oracle_text") or "" for f in (card.get("card_faces") or [])]
    return "\n".join(parts)


def _identity(card: dict) -> set[str] | None:
    """Colour identity, or None when the card does not say (never guessed)."""
    for key in ("color_identity", "colors_identity"):
        if key in card and card[key] is not None:
            return set(card[key])
    return None


def copy_limit(card: dict) -> int | None:
    """How many copies the singleton rule allows: 1, an exact cap, or None for unlimited."""
    tl = (card.get("original_type_line") or card.get("type_line") or "")
    if "basic" in tl.lower().split(" // ")[0].replace("—", " ").split():
        return None
    text = _text(card)
    if _ANY_NUMBER_RE.search(text):
        return None
    m = _UP_TO_RE.search(text)
    if m:
        word = m.group(1).lower()
        if word.isdigit():
            return int(word)
        if word in _WORD_NUMBERS:
            return _WORD_NUMBERS[word]
    return 1


def _commander_status(card: dict) -> str | None:
    """Scryfall's commander legality string, or None when the card doesn't carry one."""
    leg = card.get("legalities")
    if isinstance(leg, dict) and leg.get("commander"):
        return str(leg["commander"])
    if card.get("commander_legality"):          # stored deck.json shape
        return str(card["commander_legality"])
    return None


def check(commander: dict | None, deck: list[dict],
          partners: list[dict] | None = None) -> dict:
    """Legality report for a Commander deck. `{}` for an empty deck (a single card build).

    `deck` may or may not already contain the partner cards (every build/import path
    appends them so they render); command-zone names are taken out of the library either
    way, so the result is the same.
    """
    if not deck or not commander:
        return {}
    partners = [p for p in (partners or []) if _name(p)]
    zone_cards = [commander] + partners
    zone_names = {_name(c).casefold() for c in zone_cards}
    # A partner that arrived only as a name (stored jobs keep names): use the full card
    # from the deck if it is there, so its identity and legality are known.
    by_name = {_name(c).casefold(): c for c in deck if _name(c)}
    zone_cards = [commander] + [by_name.get(_name(p).casefold(), p) for p in partners]

    library: dict[str, dict] = {}
    copies: dict[str, int] = {}
    for card in deck:
        key = _name(card).casefold()
        if not key or key in zone_names:
            continue
        library.setdefault(key, card)
        copies[key] = copies.get(key, 0) + _qty(card)

    issues: list[dict] = []
    total = len(zone_cards) + sum(copies.values())
    if total != DECK_SIZE:
        over = total - DECK_SIZE
        issues.append({
            "kind": "size",
            "message": (f"{total} cards: a Commander deck is exactly {DECK_SIZE} including "
                        f"the command zone ({abs(over)} {'too many' if over > 0 else 'short'})."),
            "cards": [],
        })

    dupes = []
    for key, n in copies.items():
        limit = copy_limit(library[key])
        if limit is not None and n > limit:
            dupes.append(f"{_name(library[key])} x{n}")
    if dupes:
        issues.append({"kind": "singleton",
                       "message": "More copies than the singleton rule allows: "
                                  + ", ".join(sorted(dupes)) + ".",
                       "cards": sorted(d.rsplit(" x", 1)[0] for d in dupes)})

    zone_ids = [_identity(c) for c in zone_cards]
    if all(i is not None for i in zone_ids):
        allowed = set().union(*zone_ids)
        off = sorted(_name(c) for c in library.values()
                     if (_identity(c) or set()) - allowed and _identity(c) is not None)
        if off:
            where = "/".join(sorted(allowed)) or "colourless"
            issues.append({"kind": "identity",
                           "message": f"Outside the command zone's colour identity ({where}): "
                                      + ", ".join(off) + ".",
                           "cards": off})

    banned, unverified = [], 0
    for card in zone_cards + list(library.values()):
        status = _commander_status(card)
        if status is None:
            unverified += 1
        elif status in ("banned", "not_legal"):
            banned.append(f"{_name(card)} ({'banned' if status == 'banned' else 'not legal'})")
    if banned:
        issues.append({"kind": "legality",
                       "message": "Not legal in Commander: " + ", ".join(sorted(banned)) + ".",
                       "cards": sorted(b.rsplit(" (", 1)[0] for b in banned)})

    lead = zone_cards[0]
    # A Background is never a commander on its own, but it is a legal SECOND card beside a
    # Choose-a-Background commander, so only the lead must pass the eligibility test.
    if (lead.get("type_line") or lead.get("card_faces")) and \
            not commander_analysis.is_commander_eligible(lead):
        issues.append({"kind": "commander",
                       "message": f"{_name(lead)} can't be a commander: it is not a "
                                  "legendary creature and doesn't say it can be.",
                       "cards": [_name(lead)]})
    for other in zone_cards[1:]:
        if not (other.get("oracle_text") or other.get("type_line")):
            continue                        # name only: nothing to judge the pairing on
        ok, why = commander_analysis.can_pair(lead, other)
        if not ok:
            issues.append({"kind": "pairing", "message": why, "cards": [_name(other)]})

    return {
        "legal": not issues,
        "total": total,
        "issues": issues,
        # Cards whose ban status could not be read. Not a verdict either way.
        "unverified": unverified,
    }
