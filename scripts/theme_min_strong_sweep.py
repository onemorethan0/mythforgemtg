"""Sweep `deck_themes.MIN_STRONG` against real corpus recall vs random-pile false positives —
the same methodology that originally calibrated `LIFT_FACTOR` (CLAUDE.md's own documented
89-corpus-decks-vs-40-random-piles sweep), extended to the OTHER half of the gate.

Motivation: investigating S1's "42% of themeless-commander decks are not rescued by
deck_themes" figure surfaced several real corpus decks with a genuine, high-lift archetype
signal (lift 2.5-6x base rate) that fails ONLY because `strong == 2` sits one card under the
absolute `MIN_STRONG = 3` floor -- e.g. Jegantha's `chaos` (strong=2, lift=2.49), Nin's
`sagas` (strong=2, lift=2.92), Thrasios's `draw_matters` (strong=2, lift=5.79). All three are
RARE themes (BASE_RATE well under 1%), where 2 cards already represents a large multiple of
chance.

    python scripts/theme_min_strong_sweep.py
"""

from __future__ import annotations

import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import deck_themes  # noqa: E402
import theme_match  # noqa: E402
from mythgauntlet.config import data_dir  # noqa: E402
import json  # noqa: E402

_QTY_RE = re.compile(r"^(\d+)x?\s+(.+)$")
_MIN_STRONG_CANDIDATES = (1, 2, 3)
N_RANDOM_PILES = 60
RANDOM_PILE_SIZE = 60
SEED = 7


def _load_store() -> dict[str, dict]:
    rows = json.loads((Path(data_dir()) / "cards_slim.json").read_text(encoding="utf-8"))["cards"]
    return {r["name"]: r for r in rows}


def _parse_corpus_deck(path: Path) -> tuple[str | None, list[str]]:
    commander = None
    names: list[str] = []
    section = "main"
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        header = line.rstrip(":").strip().lower()
        if header == "commander":
            section = "commander"
            continue
        if header == "deck":
            section = "main"
            continue
        m = _QTY_RE.match(line)
        name = m.group(2) if m else line
        if section == "commander":
            commander = name
        else:
            names.append(name)
    return commander, names


def _themeless_commander_decks(store: dict[str, dict]) -> list[list[dict]]:
    import commander_analysis

    out = []
    for p in sorted(Path("corpus/decks").glob("*.txt")):
        cmdr_name, names = _parse_corpus_deck(p)
        if not cmdr_name:
            continue
        cmdr = store.get(cmdr_name)
        if not cmdr or commander_analysis._detect_themes(cmdr):
            continue
        cards = [store[n] for n in names if n in store]
        if len(cards) >= 50:
            out.append(cards)
    return out


def _random_piles(store: dict[str, dict], n: int, size: int, seed: int) -> list[list[dict]]:
    pool = [
        r for r in store.values()
        if not (r.get("type_line") or "").lower().startswith("basic land")
    ]
    rng = random.Random(seed)
    return [rng.sample(pool, size) for _ in range(n)]


def main() -> int:
    store = _load_store()
    print("Loading themeless-commander corpus decks...")
    real_decks = _themeless_commander_decks(store)
    print(f"  {len(real_decks)} decks with a themeless commander and >=50 resolved cards")

    print(f"Generating {N_RANDOM_PILES} random {RANDOM_PILE_SIZE}-card piles...")
    piles = _random_piles(store, N_RANDOM_PILES, RANDOM_PILE_SIZE, SEED)

    print(f"\n{'min_strong':>10} {'real recall':>14} {'random false-pos':>18}")
    for min_strong in _MIN_STRONG_CANDIDATES:
        real_hits = sum(
            1 for d in real_decks if deck_themes.detect_deck_themes(d, min_strong=min_strong)
        )
        pile_hits = sum(
            1 for p in piles if deck_themes.detect_deck_themes(p, min_strong=min_strong)
        )
        real_pct = real_hits / len(real_decks) if real_decks else 0.0
        pile_pct = pile_hits / len(piles) if piles else 0.0
        print(f"{min_strong:>10} {real_pct:>13.1%} {pile_pct:>17.1%}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
