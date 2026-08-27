"""Sweep the B4-vs-B5 combo gate against the labelled corpus, with real Spellbook data.

`ratings.bracket.estimate_bracket`'s only path to Bracket 5 without a gauntlet meta_rating is

    fast_terminal_two_card(combo_profile) and ceiling >= 40 and speed_kill_rate >= 0.4

`docs/PLAN_CLOCK.md` Sec 1.3 hand-sampled 11 real B5-labelled decks that `bracket_accuracy.py
--real-combos` still calls Bracket 4 and found two candidate miscalibrations: three had the
right combo signal but a ceiling well under 40 (14-20), and four had a real 2-card terminal
combo graded "strong" rather than "fast-win" by `classify_combo`. That sample explicitly was
NOT a sweep and said not to act on it. This is that sweep.

WHAT THIS MEASURES, against every B3/B4/B5-labelled deck with a REAL per-deck Commander
Spellbook lookup (not a declared count):
  1. Among decks holding a fast-win 2-card terminal combo, where does a ceiling threshold
     actually separate B4 from B5 -- and does 40 look right, high, or low?
  2. What changes if the gate accepts ANY 2-card terminal combo regardless of reliability
     grade, not just "fast-win"?
  3. The false-positive cost of loosening either knob: how many B3/B4-labelled decks ALREADY
     carry the qualifying combo signal, and would a looser gate misclassify them upward?

DISCIPLINE, same as `bracket_boundary.py`: report the baseline, sweep both directions, print
the whole curve's plateau not just the peak, and do not fit past what one- or two-threshold
rules can honestly support on this few labels.

NOT CI-SAFE: needs data/cards_slim.json, a semantics store, and the network (Commander
Spellbook `find-my-combos`, cached by decklist hash -- a re-run costs nothing once warm).

    python scripts/bracket_b5_gate.py                  # all labelled B3/B4/B5 decks
    python scripts/bracket_b5_gate.py --runs 150 --json out.json
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from bracket_boundary import plateau, sweep  # noqa: E402 - reused, not reimplemented
# `_ensure_utf8_stdout` and `real_combo_lookup` (the per-deck resolve -> real Spellbook
# lookup -> analyze_deck step, throttled but cache-aware) are shared with
# bracket_accuracy.py rather than re-typed here -- this script used to duplicate that
# loop with no throttle at all, silently hammering the Spellbook API across 252 decks.
from bracket_accuracy import (  # noqa: E402
    _ensure_utf8_stdout, labelled_decks, real_combo_lookup,
)

_ensure_utf8_stdout()


def collect(runs: int, seed: int, limit: int | None = None) -> list[tuple[int, dict]]:
    """One row per B3/B4/B5-labelled deck: real combo data + ceiling/speed. B1/B2 are
    irrelevant to this specific gate and skipped to keep the network+sim cost bounded."""
    from mythgauntlet.data.scryfall import load_card_db
    from mythgauntlet.model.deck import Deck, resolve
    from mythgauntlet.ratings.analysis import analyze_deck
    from mythgauntlet.semantics.store import SemanticsStore
    from mythgauntlet.sim.tier0 import SimConfig

    db = load_card_db()
    store = SemanticsStore()
    cfg = SimConfig(turns=12, runs=runs, seed=seed)

    rows: list[tuple[int, dict]] = []
    decks = [(p, b) for p, b in labelled_decks(None) if b in (3, 4, 5)]
    if limit:
        decks = decks[:limit]
    started = time.time()
    for i, (path, label) in enumerate(decks, 1):
        resolved = resolve(Deck.parse_text(path.read_text(encoding="utf-8")), db)
        if resolved.card_count < 90:
            continue
        try:
            # `real_combo_lookup` only catches `requests.RequestException` internally --
            # a malformed Spellbook response body or a cache-dir permissions error would
            # otherwise propagate out of this loop and kill the whole 252-deck sweep, the
            # same "one deck is not fatal" guard `analyze_deck` already gets below.
            combo_report, _failed = real_combo_lookup(
                resolved, f"[{i}/{len(decks)}] {path.name}")
            a = analyze_deck(resolved, cfg, store, combo_report=combo_report,
                             combos_checked=combo_report is not None)
        except Exception as exc:                      # noqa: BLE001 - one deck is not fatal
            print(f"  [{i}/{len(decks)}] {path.name}: FAILED {exc}", flush=True)
            continue
        cp = a.combo_profile
        grades = list(cp.grades) if cp else []
        two_card_terminal = [g for g in grades if g.terminal and g.pieces <= 2]
        fast_two_card_terminal = [g for g in two_card_terminal if g.reliability == "fast-win"]
        rows.append((label, {
            "ceiling": a.ceiling.score,
            "speed_kill_rate": a.report.goldfish_kill_rate,
            "fast_terminal_two_card": bool(fast_two_card_terminal),
            "any_terminal_two_card": bool(two_card_terminal),
            "n_game_ending_combos": len(grades),
            "deck": path.name,
        }))
        if i % 25 == 0:
            print(f"  {i}/{len(decks)} ({int(time.time()-started)}s)", flush=True)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=150)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--limit", type=int, help="cap the deck count, for a fast smoke test")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    rows = collect(args.runs, args.seed, args.limit)
    print(f"\n{len(rows)} B3/B4/B5-labelled decks scored\n")

    if args.json:
        args.json.write_text(
            json.dumps([{"label": b, **d} for b, d in rows], indent=1), encoding="utf-8")
        print(f"wrote {args.json}\n")

    for gate_name, gate_key in (
        ("fast-win only (the SHIPPED gate)", "fast_terminal_two_card"),
        ("any reliability, 2-card, terminal", "any_terminal_two_card"),
    ):
        qualifying = [(b, d) for b, d in rows if d[gate_key]]
        counts = collections.Counter(b for b, _d in qualifying)
        print(f"=== {gate_name} ===")
        print(f"  qualifying decks: {len(qualifying)}  "
              f"(B3 {counts.get(3,0)}, B4 {counts.get(4,0)}, B5 {counts.get(5,0)})")
        if counts.get(3, 0) or counts.get(4, 0):
            print(f"  FALSE-POSITIVE RISK: {counts.get(3,0)+counts.get(4,0)} of those are "
                  f"B3/B4-labelled -- loosening ceiling/speed alone would newly promote some "
                  f"of them if their ceiling/speed already clear 40/0.4.")

        pair = [(b, d) for b, d in qualifying if b in (4, 5)]
        if len(pair) < 8:
            print("  too few B4/B5 decks with this signal to sweep a threshold\n")
            continue
        counts45 = collections.Counter(b for b, _d in pair)
        majority = max(counts45.values()) / len(pair)
        print(f"  B4 vs B5 among qualifying decks (n={len(pair)}: "
              f"{counts45.get(4,0)}/{counts45.get(5,0)}), "
              f"baseline 'always say B4' {100*majority:.1f}%")
        for key in ("ceiling", "speed_kill_rate"):
            curve = sweep(pair, key, (4, 5))
            found = plateau(curve)
            if not found:
                continue
            (threshold, acc, r4, r5, ascending), width, best = found
            arrow = ">=" if ascending else "<="
            flag = "  <-- beats baseline" if acc > majority + 0.02 else ""
            print(f"    {key:>16}  {arrow}{threshold:8.2f} -> B5   acc {100*acc:5.1f}%  "
                  f"(peak {100*best:5.1f}%, plateau {width})  "
                  f"B4 {100*r4:4.0f}% / B5 {100*r5:4.0f}%{flag}")
        # Where does the CURRENT shipped threshold (ceiling>=40, speed>=0.4) actually land?
        shipped = sum(1 for b, d in pair if d["ceiling"] >= 40 and d["speed_kill_rate"] >= 0.4)
        shipped_b5 = sum(1 for b, d in pair
                         if b == 5 and d["ceiling"] >= 40 and d["speed_kill_rate"] >= 0.4)
        print(f"    shipped (ceiling>=40 AND speed>=0.4): {shipped}/{len(pair)} qualify, "
              f"{shipped_b5}/{counts45.get(5,0)} of the real B5s among them\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
