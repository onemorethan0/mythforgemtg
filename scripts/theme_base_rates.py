"""Regenerate `deck_themes.BASE_RATE` — the share of ALL cards that score STRONG per theme.

Why this table has to exist: `theme_match`'s themes are wildly different sizes. Measured
over the 34,846-card store, `voltron_combat` scores STRONG on 19.35% of every card in
Magic, so an absolute "3 STRONG cards = this deck has the theme" rule fires on a pile of
randomly chosen cards 100% of the time. `tokens` (11.8%), `counters` (9.9%) and
`graveyard` (6.5%) are nearly as bad; every other theme is under 1%.

So a theme only counts when a deck plays it MORE than a random pile of that size would —
theme lift. This script measures the denominator.

    python scripts/theme_base_rates.py            # print the table
    python scripts/theme_base_rates.py --check     # compare against the baked-in constant

Takes ~90s: 34.8k cards x 40 themes. Re-run it after editing `theme_match` rules or after
a card-data refresh that materially changes the pool.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import theme_match  # noqa: E402
from mythgauntlet.config import data_dir  # noqa: E402


def measure() -> dict[str, float]:
    """STRONG-hit rate per theme over every non-basic card in the slim store."""
    store = Path(data_dir()) / "cards_slim.json"
    rows = json.loads(store.read_text(encoding="utf-8"))["cards"]
    pool = [
        r for r in rows
        if not (r.get("type_line") or "").lower().startswith("basic land")
    ]
    counts = {t: 0 for t in theme_match.THEMES}
    for row in pool:
        card = {
            "name": row.get("name", ""),
            "type_line": row.get("type_line", ""),
            "oracle_text": row.get("oracle_text", ""),
        }
        for theme in theme_match.THEMES:
            if theme_match.theme_score(card, theme) == theme_match.STRONG:
                counts[theme] += 1
    return {t: c / len(pool) for t, c in counts.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="diff against deck_themes.BASE_RATE instead of printing it")
    args = ap.parse_args()
    rates = measure()

    if args.check:
        import deck_themes
        drift = {
            t: (deck_themes.BASE_RATE.get(t), r)
            for t, r in sorted(rates.items())
            if abs(deck_themes.BASE_RATE.get(t, -1) - r) > 0.002
        }
        missing = set(rates) - set(deck_themes.BASE_RATE)
        stale = set(deck_themes.BASE_RATE) - set(rates)
        for t, (was, now) in drift.items():
            print(f"DRIFT {t}: baked {was} measured {now:.5f}")
        for t in sorted(missing):
            print(f"MISSING from BASE_RATE: {t} ({rates[t]:.5f})")
        for t in sorted(stale):
            print(f"STALE in BASE_RATE (no such theme): {t}")
        ok = not (drift or missing or stale)
        print("BASE_RATE is current." if ok else "BASE_RATE needs regenerating.")
        return 0 if ok else 1

    print("BASE_RATE: dict[str, float] = {")
    for theme, rate in sorted(rates.items()):
        print(f'    "{theme}": {rate:.5f},')
    print("}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
