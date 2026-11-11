"""Does a swap (or a package of swaps) win more four-player pods, not just score on an axis?

Interaction swaps are scored by a formula (how many answers the deck holds), so they repeat
exactly on any seed -- which proves nothing about whether the deck plays better. This plays the
deck against a field of corpus decks of its own bracket, once as-is and once with the swaps,
with the SAME seeds, and reports the win-rate difference with its interval.

    python scripts/swap_podcheck.py --deck "Syr Konrad" --games 600 --chunks 4 \\
        --swap "The Echoverse Fulcrum|Beastmaster Ascension" --swap "Swift Demise|Shamanic Revelation"

Not CI-safe (needs the semantics store and the corpus). Slow: a pod game is a full 4-player sim.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", required=True, help="substring of the commander's name")
    ap.add_argument("--swap", action="append", default=[], help='"Add Name|Cut Name"')
    ap.add_argument("--games", type=int, default=400, help="games per chunk")
    ap.add_argument("--chunks", type=int, default=4, help="independent paired chunks")
    ap.add_argument("--bracket", type=int, default=None, help="field bracket (default: deck's)")
    ap.add_argument("--each", action="store_true", help="also test every swap alone")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT / "scripts"))
    from advise_holdout import deck_text
    from mythgauntlet.config import corpus_dir
    from mythgauntlet.data import scryfall
    from mythgauntlet.model.deck import Deck, resolve
    from mythgauntlet.ratings import advisor
    from mythgauntlet.ratings.analysis import analyze_deck
    from mythgauntlet.ratings.pod import pod_winrate, prepare_seat
    from mythgauntlet.semantics.store import load_store
    from mythgauntlet.server import _corpus_bracket_label
    from mythgauntlet.sim.tier0 import SimConfig
    from mythgauntlet.sim.tier2 import DuelConfig

    db, store = scryfall.load_card_db(), load_store()
    resolved = None
    for p in sorted(ROOT.glob("renders/*/deck.json"), key=lambda p: -p.stat().st_mtime):
        name, text = deck_text(p)
        if args.deck.lower() in name.lower():
            resolved = resolve(Deck.parse_text(text, name=name), db)
            break
    assert resolved is not None, "deck not found in renders/"
    bracket = args.bracket or analyze_deck(
        resolved, SimConfig(turns=12, runs=60, seed=1), store, run_resilience=False).bracket.bracket
    bracket = min(bracket, 4)

    field = []
    for path in sorted(corpus_dir().glob("*.txt")):
        if _corpus_bracket_label(path) != bracket or args.deck.lower() in path.stem.lower():
            continue
        try:
            r = resolve(Deck.parse_text(path.read_text(encoding="utf-8"), name=path.stem), db)
        except OSError:
            continue
        if r.cards:
            field.append(prepare_seat(r.cards, r.commanders[0] if r.commanders else None, store))
    print(f"{resolved.deck.name}: Bracket {bracket} field of {len(field)} decks", flush=True)

    by_name = {c.name: c for c, _ in resolved.cards}

    def variant(pairs):
        d = resolved
        for add_n, cut_n in pairs:
            add = db.get(add_n)
            assert add is not None, add_n
            d = advisor._swap_variant(d, by_name[cut_n], add)
        return d

    def seat(d):
        return prepare_seat(d.cards, d.commanders[0] if d.commanders else None, store)

    pairs = [tuple(s.split("|", 1)) for s in args.swap]
    arms = {"PACKAGE": pairs} if pairs else {}
    if args.each:
        arms.update({f"{a} -/- {c}": [(a, c)] for a, c in pairs})
    cfg = DuelConfig(max_turns=30, start_life=40)
    base_seat = seat(resolved)
    seats = {k: seat(variant(v)) for k, v in arms.items()}

    base_rates, diffs = [], {k: [] for k in arms}
    for ch in range(args.chunks):
        seed = 5000 + ch
        t = time.time()
        b = pod_winrate(base_seat, field, cfg, games=args.games, seed=seed, pod_size=4).winrate
        base_rates.append(b)
        line = f"chunk {ch}: base {100*b:.1f}%"
        for k, s in seats.items():
            w = pod_winrate(s, field, cfg, games=args.games, seed=seed, pod_size=4).winrate
            diffs[k].append(w - b)
            line += f" | {k[:28]} {100*(w-b):+.1f}pp"
        print(line + f"  ({time.time()-t:.0f}s)", flush=True)

    n = args.games * args.chunks
    print(f"\nbase win rate {100*statistics.mean(base_rates):.1f}% over {n} games "
          f"(even pod = 25.0%)")
    for k, d in diffs.items():
        m = statistics.mean(d)
        se = statistics.stdev(d) / math.sqrt(len(d)) if len(d) > 1 else float("nan")
        print(f"{k}: {100*m:+.2f}pp  (se {100*se:.2f}pp, {args.chunks} chunks x {args.games} games)")
    print(json.dumps({k: [round(x, 4) for x in d] for k, d in diffs.items()}))


if __name__ == "__main__":
    main()
