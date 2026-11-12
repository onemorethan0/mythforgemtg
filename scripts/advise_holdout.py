"""Does an Advise swap keep its gain on games the search never saw?

`advisor.advise` tries ~16 adds x ~6 cuts on ONE seed and reports the best pairings, so the
reported gain is a maximum over many noisy measurements (the winner's curse): some of it is luck
that fresh games will not repeat. This re-measures every reported swap on FRESH seeds, paired
(same seed for base and swapped deck), and compares to what Advise reported.

    python scripts/advise_holdout.py --decks 6 --out holdout.json

Reads decks from renders/<id>/deck.json and the suite collection; needs the semantics store
(MYTHGAUNTLET_STORE) like the engine. Not CI-safe, slow (minutes per deck).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

FRESH_SEEDS = (1001, 1002, 1003, 1004, 1005)


def deck_text(path: Path) -> tuple[str, str]:
    from api.routes_strength import _deck_to_lines
    d = json.loads(path.read_text(encoding="utf-8"))
    nm = lambda c: dict(c, name=c.get("original_name") or c.get("name"))   # noqa: E731
    partners = [nm(p) if isinstance(p, dict) else {"name": p} for p in (d.get("partners") or [])]
    cmd = nm(d["commander"])
    deck = [nm(c) for c in d["deck"]]
    return cmd["name"], _deck_to_lines(cmd, deck, partners)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", type=int, default=6)
    ap.add_argument("--runs", type=int, default=300)
    ap.add_argument("--out", default="advise_holdout.json")
    ap.add_argument("--confirm", type=int, default=0, help="advise(confirm_seeds=...); 0 = the original search-seed gains")
    ap.add_argument("--baseline", type=int, default=0, help="advise(baseline_seeds=...)")
    ap.add_argument("--workers", type=int, default=0, help="advise(workers=...): processes for the sweep")
    ap.add_argument("--only", default="", help="substring of the deck name to run (skips others)")
    args = ap.parse_args()

    from mythgauntlet.data import scryfall
    from mythgauntlet.model.collection import Collection
    from mythgauntlet.model.deck import Deck, resolve
    from mythgauntlet.ratings import advisor
    from mythgauntlet.ratings.analysis import analyze_deck
    from mythgauntlet.semantics.store import load_store as _ls
    from mythgauntlet.server import suite_collection_path
    from mythgauntlet.sim.tier0 import SimConfig

    db = scryfall.load_card_db()
    store = _ls()
    col = Collection.load(suite_collection_path())

    paths = sorted(ROOT.glob("renders/*/deck.json"), key=lambda p: -p.stat().st_mtime)
    rows, used = [], 0
    for p in paths:
        if used >= args.decks:
            break
        try:
            name, text = deck_text(p)
            resolved = resolve(Deck.parse_text(text, name=name), db)
        except Exception as e:           # noqa: BLE001
            continue
        if len(resolved.cards) < 60 or not resolved.commanders:
            continue
        if args.only and args.only.lower() not in name.lower():
            continue
        used += 1
        t0 = time.time()
        cfg = SimConfig(turns=12, runs=args.runs, seed=42)
        cands = advisor.owned_candidates(db, resolved, col)
        rep = advisor.advise(resolved, cfg, store, cands, axis=None, top=5, max_eval=16,
                             cut_pool=6, fallback_axes=3, ablate_cuts=True,
                             confirm_seeds=args.confirm, baseline_seeds=args.baseline, workers=args.workers)
        print(f"[{used}] {name}: {len(rep.suggestions)} suggestions ({time.time()-t0:.0f}s)", flush=True)
        for s in rep.suggestions:
            ax = s.axis or rep.axis
            cut = next(c for c, _ in resolved.cards if c.name == s.cut)
            add = next(c for c in cands if c.name == s.add)
            swapped = advisor._swap_variant(resolved, cut, add)
            res = ax == "resilience"
            ds = []
            for seed in FRESH_SEEDS:
                c2 = SimConfig(turns=12, runs=args.runs, seed=seed)
                b = analyze_deck(resolved, c2, store, run_resilience=res)
                a = analyze_deck(swapped, c2, store, run_resilience=res)
                ds.append(advisor.axis_score(a, ax) - advisor.axis_score(b, ax))
            rows.append({"deck": name, "axis": ax, "add": s.add, "cut": s.cut,
                         "reported": round(s.delta, 2), "held_out": round(statistics.mean(ds), 2),
                         "held_out_sd": round(statistics.pstdev(ds), 2),
                         "floor": advisor._noise_floor(ax, args.runs)})
            print("   ", rows[-1], flush=True)
        Path(args.out).write_text(json.dumps(rows, indent=1), encoding="utf-8")

    if rows:
        rep_m = statistics.mean(r["reported"] for r in rows)
        ho_m = statistics.mean(r["held_out"] for r in rows)
        keep = sum(r["held_out"] > r["floor"] for r in rows)
        pos = sum(r["held_out"] > 0 for r in rows)
        print(f"\n{len(rows)} swaps: reported mean {rep_m:.2f}, held-out mean {ho_m:.2f} "
              f"(keeps {100*ho_m/rep_m:.0f}%); held-out > noise floor {keep}/{len(rows)}, "
              f"> 0 {pos}/{len(rows)}")


if __name__ == "__main__":
    main()
