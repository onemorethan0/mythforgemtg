"""D6 (docs/DESIGN_table_brackets.md): does a High-Denial deck win more than its seat share at
a casual table?

Takes the labelled Bracket 1-3 corpus decks whose D3 Denial dial reads High AND that run
counterspells, plus an equal-sized control of Denial-Low decks from the same brackets, and runs
each in 4-player pods (`ratings.pod.pod_winrate`: the deck rotated through every seat, opponents
drawn from a Bracket 2 field). Seeds are fixed, so two runs on two engines differ only by the
engine. Writes one JSON per run.

    python scripts/denial_pod_study.py --out after.json
    python scripts/denial_pod_study.py --out before.json   # on the pre-D5 sim/game.py

NOT CI-SAFE: needs the card store and the compiled semantics store (~35 s cold).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src", ROOT / "scripts"):
    sys.path.insert(0, str(p))

from bracket_accuracy import labelled_decks  # noqa: E402
from mythgauntlet.data.scryfall import load_card_db  # noqa: E402
from mythgauntlet.model.deck import Deck, resolve  # noqa: E402
from mythgauntlet.ratings import denial, dials  # noqa: E402
from mythgauntlet.ratings.pod import pod_winrate, prepare_seat  # noqa: E402
from mythgauntlet.semantics.store import load_store  # noqa: E402
from mythgauntlet.sim.tier2 import DuelConfig  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--per-group", type=int, default=12)
    ap.add_argument("--games", type=int, default=60)
    ap.add_argument("--field", type=int, default=60, help="Bracket 2 decks in the field")
    args = ap.parse_args()

    db = load_card_db()
    store = load_store()
    rng = random.Random(11)
    high, low, field_paths = [], [], []
    for path, label in labelled_decks():
        r = resolve(Deck.parse_text(path.read_text(encoding="utf-8")), db)
        if label == 2:
            field_paths.append((path, r))
        if label > 3 or not r.cards:
            continue
        d = denial.deck_denial(list(r.cards), list(r.commanders))
        band = dials.denial_dial(d).band
        if band == "High" and d.counterspells >= 4:
            high.append((path, label, r, d))
        elif band == "Low":
            low.append((path, label, r, d))
    rng.shuffle(high)
    rng.shuffle(low)
    rng.shuffle(field_paths)
    groups = {"high_denial": high[:args.per_group], "low_denial": low[:args.per_group]}
    chosen = {p.name for g in groups.values() for p, *_ in g}
    field = [prepare_seat(r.cards, r.commanders[0] if r.commanders else None, store)
             for p, r in field_paths if p.name not in chosen][:args.field]
    print(f"high-denial decks available {len(high)}, low {len(low)}; field {len(field)}",
          flush=True)

    cfg = DuelConfig(max_turns=30, start_life=40)
    rows = []
    for group, members in groups.items():
        for path, label, r, d in members:
            seat = prepare_seat(r.cards, r.commanders[0] if r.commanders else None, store)
            t = time.time()
            rating = pod_winrate(seat, field, cfg, games=args.games, seed=42)
            rows.append({"group": group, "deck": path.name, "label": label,
                         "commander": r.commanders[0].name if r.commanders else "",
                         "counterspells": d.counterspells, "locks": len(d.locks),
                         "wins": rating.wins, "games": rating.games,
                         "winrate": rating.winrate})
            print(f"  {group:11} {path.name:28} B{label} counters {d.counterspells:2} "
                  f"win {rating.winrate:5.1%} ({time.time() - t:.0f}s)", flush=True)
    for group in groups:
        rs = [r for r in rows if r["group"] == group]
        w, g = sum(r["wins"] for r in rs), sum(r["games"] for r in rs)
        print(f"{group}: {w}/{g} = {w / g:.1%} (seat share 25%)")
    args.out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
