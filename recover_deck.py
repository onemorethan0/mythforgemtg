"""
One-shot recovery script: reconstructs a deck.json for a completed build
whose deck.json was never written (e.g. server reloaded mid-finish).

Usage:
    python recover_deck.py <job_id>

It reads the rendered PNG filenames, reverses the safe-name encoding via
fuzzy Scryfall lookup, and writes a minimal deck.json so the History tab
can find and display the deck.
"""
import json
import re
import sys
import time
from pathlib import Path

BASE = Path(__file__).parent
RENDER_DIR = BASE / "renders"

# ── helpers ──────────────────────────────────────────────────────────────────

def safe_to_query(safe: str) -> str:
    """Best-effort reverse of: ''.join(ch if ch.isalnum() else '_' for ch in name)
    Replace runs of underscores with a space so Scryfall fuzzy can find it."""
    # double underscore is almost always comma+space or apostrophe+char
    q = re.sub(r'_+', ' ', safe).strip()
    return q


def scryfall_lookup(query: str) -> dict | None:
    import requests
    url = "https://api.scryfall.com/cards/named"
    for fuzzy in (True, False):
        try:
            r = requests.get(url, params={"fuzzy" if fuzzy else "exact": query},
                             headers={"User-Agent": "DeckRecovery/1.0"}, timeout=10)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(0.15)
    return None


def normalize_card(card: dict) -> dict:
    """Promote front-face fields for double-faced cards (same as scryfall_client)."""
    if card.get("image_uris"):
        return card
    faces = card.get("card_faces")
    if not faces:
        return card
    front = faces[0]
    merged = dict(card)
    for field in ("mana_cost", "oracle_text", "type_line", "power", "toughness",
                  "loyalty", "image_uris", "colors"):
        if field not in merged or not merged[field]:
            if field in front:
                merged[field] = front[field]
    merged["_front_name"] = front.get("name", card["name"])
    return merged


def tc_to_dict(card: dict, safe_name: str) -> dict:
    name = card.get("_front_name") or card["name"]
    return {
        "original_name": name,
        "themed_name":   name,   # we lost theming data; use original
        "art_prompt":    "",
        "flavor_text":   "",
        "mana_cost":     card.get("mana_cost", ""),
        "type_line":     card.get("type_line", "").split(" // ")[0],
        "oracle_text":   card.get("oracle_text", ""),
        "cmc":           card.get("cmc", 0),
        "colors":        card.get("color_identity", []),
        "power":         card.get("power"),
        "toughness":     card.get("toughness"),
        "scryfall_img":  (card.get("image_uris") or {}).get("normal", ""),
        "has_render":    True,
        "render_key":    safe_name,
    }


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        # Auto-find newest job without deck.json
        jobs = sorted(RENDER_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        candidates = [j for j in jobs if j.is_dir() and (j / "cards").exists()
                      and not (j / "deck.json").exists()]
        if not candidates:
            print("No jobs found that are missing deck.json")
            sys.exit(0)
        job_id = candidates[0].name
        print(f"Auto-selected newest incomplete job: {job_id}")
    else:
        job_id = sys.argv[1]

    job_dir = RENDER_DIR / job_id
    cards_dir = job_dir / "cards"

    if not cards_dir.exists():
        print(f"No cards directory found at {cards_dir}")
        sys.exit(1)

    pngs = sorted(cards_dir.glob("*.png"))
    print(f"Found {len(pngs)} rendered cards in {job_id}")

    # Identify commander: it'll be the card whose name contains the commander.
    # We'll detect it as the first alphabetically or ask user — for now just
    # put all cards in deck and flag the one that looks like a legendary creature.

    commander_dict = None
    deck_list = []
    failed = []

    for i, png in enumerate(pngs):
        safe_name = png.stem
        query = safe_to_query(safe_name)
        print(f"  [{i+1}/{len(pngs)}] {safe_name!r} -> querying '{query}'...", end=" ", flush=True)
        card = scryfall_lookup(query)
        if card:
            card = normalize_card(card)
            d = tc_to_dict(card, safe_name)
            # Detect commander: legendary creature or planeswalker
            type_line = card.get("type_line", "")
            if "Legendary" in type_line and ("Creature" in type_line or "Planeswalker" in type_line):
                if commander_dict is None:
                    commander_dict = d
                    print(f"✓ COMMANDER")
                else:
                    deck_list.append(d)
                    print(f"✓ (legendary)")
            else:
                deck_list.append(d)
                print("✓")
        else:
            failed.append(safe_name)
            print("✗ NOT FOUND")
        time.sleep(0.15)

    if failed:
        print(f"\n⚠  {len(failed)} cards not found on Scryfall:")
        for f in failed:
            print(f"   - {f}")

    if commander_dict is None:
        if deck_list:
            # Fallback: use first card
            commander_dict = deck_list.pop(0)
            print(f"\nWarning: could not auto-detect commander — using {commander_dict['original_name']}")
        else:
            print("ERROR: no cards recovered")
            sys.exit(1)

    result = {
        "status":           "done",
        "commander":        commander_dict,
        "deck":             deck_list,
        "stats":            {"total_cards": 1 + len(deck_list)},
        "theme":            "(recovered — theme data unavailable)",
        "commander_prompt": "",
        "playstyle":        "recovered",
        "bracket":          3,
        "bracket_label":    "Upgraded",
        "built_at":         (job_dir / "set_symbol.png").stat().st_mtime
                            if (job_dir / "set_symbol.png").exists()
                            else time.time(),
        "_recovered":       True,
    }

    out_path = job_dir / "deck.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\n✅ Wrote {out_path}")
    print(f"   Commander : {commander_dict['original_name']}")
    print(f"   Deck size : {1 + len(deck_list)} cards")
    print(f"   Failed    : {len(failed)} cards")


if __name__ == "__main__":
    main()
