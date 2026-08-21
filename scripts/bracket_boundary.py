"""Fit the placement rule for decks with ZERO Game Changers, against the corpus labels.

WHAT THIS SET OUT TO DO, AND WHY IT DID NOT DO IT. `bracket.estimate_bracket` reads the
official Game Changer gate as `gc == 0 -> floor 1, cap 2` ("0 Game Changers -> Brackets 1-2").
That IS a misreading of the rules — Bracket 3 (Upgraded) permits **up to** 3 Game Changers, it
does not require any, so the gate turns a ceiling into a floor. Of the 97 decks their builders
called Bracket 3, **40 hold zero Game Changers** and are capped at 2, which is the entire
B3->B2 (30) + B3->B1 (10) error mass.

**Lifting the cap does not fix it, and shipping the lift alone would make things worse.**
Placement inside the band is what decides the answer, and there is no rule to decide it:

    B2 vs B3, zero Game Changers, n=130 (90 / 40)
      baseline "always say B2"            69.2%
      best single-threshold rule          70.0%   with B3 recall 2-5%
      best two-signal rule                70.8%

Every candidate is "always say B2" wearing a threshold. And the placement code branches on
`floor == 1 and cap == 2` exactly, so widening the cap to 3 makes that branch stop matching
and every zero-GC deck falls through to `bracket = floor` — **Bracket 1 for everything.** The
cap is not the binding constraint; the missing discriminator is.

This confirms rather than supersedes the 2026-07-28 finding in `docs/engine/STATUS.md`, which
reached the same conclusion at n=87/33 and named the honest `plays_up` banner as the correct
FINAL answer for the band. Two independent measurements now agree: the B2/B3 boundary is not
resolvable from the 99 cards, and the label there is recording the author's intent and pod
context rather than a property of the deck.

WHAT IT DID FIND, AND WHY IT IS STILL NOT SHIPPED. At the **B1/B2** boundary a single
threshold on `edhrec_log_rank` scores **76.1%** against **64.8%** for the `manabase_P` rule
that ships — 11 points, on a broad smooth plateau (>=70% across 7.51..8.08), far better
balanced (B1 65% / B2 84% vs 30% / 91%). **Invariant 4 bars it**: popularity is a prior, never
a verdict, because a popularity-driven verdict recreates the static-calculator failure mode
this engine exists to replace. The correction that DID land is documentary — the recorded
answer to "would popularity have helped?" used to read "It doesn't", and that was false. The
rule defends a principle, not a measurement.

DISCIPLINE, because 297 labels is not many:
  * Only one- and two-threshold rules. A fitted model on this much noisy self-reported data
    would learn the annotators, not the game.
  * BOTH sweep directions are tried per signal — see `sweep`. Hard-coding one direction made
    every rising signal look like a degenerate always-say-the-majority rule.
  * Accuracy is printed across the sweep, not just at the best point. A spike is overfitting;
    a plateau is a real effect.
  * The baseline row is always shown. A rule that cannot beat "always say the majority" is
    not a rule — which is exactly what B2-vs-B3 turned out to be.

    python scripts/bracket_boundary.py                 # fit on 0-GC decks
    python scripts/bracket_boundary.py --runs 200

NOT CI-SAFE: needs data/cards_slim.json and a semantics store. Offline, no LLM, no GPU.
"""

from __future__ import annotations

import argparse
import collections
import io
import itertools
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))


def _ensure_utf8_stdout() -> None:
    for attr in ("stdout", "stderr"):
        stream = getattr(sys, attr, None)
        if stream is None or not hasattr(stream, "buffer"):
            continue
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if encoding != "utf8" or getattr(stream, "errors", "") != "replace":
            setattr(sys, attr,
                    io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"))


_ensure_utf8_stdout()

# Candidates for the 2-vs-3 split, in the order `axis_separation` ranks them at that boundary.
# `edhrec_log_rank` is the mean log EDHREC rank of the deck's cards: LOWER means the deck is
# built out of staples, HIGHER means obscure/pet cards. It is the strongest non-Game-Changer
# signal at both casual boundaries (d = -1.02 at B1/B2, -0.54 at B2/B3) and it is not
# circular - EDHREC popularity is measured independently of anyone's bracket label.
CANDIDATES = ("edhrec_log_rank", "tutor_density", "fast_mana", "manabase_P",
              "engine_density", "consistency", "cheap_interaction", "low_curve_share")


def sweep(rows, key: str, labels: tuple[int, int], steps: int = 40):
    """Accuracy of a single-threshold rule across the observed range of `key`.

    BOTH DIRECTIONS ARE TRIED, and getting this wrong once is why it is spelled out. The
    signals do not share a sign: `edhrec_log_rank` FALLS as power rises (a staple-heavy deck
    has a low mean rank), while `manabase_P`, `tutor_density` and `fast_mana` all RISE. A
    sweep hard-coded to `value <= t -> higher bracket` therefore drove every rising signal to
    an extreme threshold and reported it as "always say the majority" wearing a threshold -
    3% recall on one class and 100% on the other, which is the signature of a direction
    error rather than a weak signal.

    Returns [(threshold, accuracy, recall_lo, recall_hi, ascending)], where `ascending` is
    True when a HIGH value means the higher bracket.
    """
    lo, hi = labels
    values = sorted(r[1][key] for r in rows)
    if not values:
        return []
    span = values[-1] - values[0]
    if span <= 0:
        return []
    out = []
    for i in range(steps + 1):
        threshold = values[0] + span * i / steps
        for ascending in (False, True):
            correct = lo_hit = lo_n = hi_hit = hi_n = 0
            for label, data in rows:
                above = data[key] >= threshold
                predicted = hi if (above if ascending else not above) else lo
                correct += predicted == label
                if label == lo:
                    lo_n += 1
                    lo_hit += predicted == lo
                else:
                    hi_n += 1
                    hi_hit += predicted == hi
            out.append((threshold, correct / len(rows),
                        lo_hit / lo_n if lo_n else 0.0,
                        hi_hit / hi_n if hi_n else 0.0,
                        ascending))
    return out


def plateau(curve):
    """The midpoint of the widest run of thresholds within 1 point of the best accuracy.

    Taking the argmax fits the noise; the previous calibration at B1-vs-B2 noted accuracy was
    flat across 0.70-0.78 and chose for recall balance rather than a peak. This does the same
    thing mechanically.
    """
    if not curve:
        return None
    # A plateau only means anything within ONE direction, so keep the better one and
    # measure flatness along it.
    best_dir = max((True, False), key=lambda d: max(
        (a for _t, a, _l, _h, asc in curve if asc is d), default=0.0))
    curve = [c for c in curve if c[4] is best_dir]
    best = max(a for _t, a, _l, _h, _d in curve)
    band = [i for i, (_t, a, _l, _h, _d) in enumerate(curve) if a >= best - 0.01]
    runs, run = [], [band[0]]
    for i in band[1:]:
        if i == run[-1] + 1:
            run.append(i)
        else:
            runs.append(run)
            run = [i]
    runs.append(run)
    widest = max(runs, key=len)
    mid = widest[len(widest) // 2]
    return curve[mid], len(widest), best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=int, default=150)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    import axis_separation

    rows = axis_separation.collect(args.runs, args.seed)
    zero = [(b, d) for b, d in rows if d["game_changers"] == 0]
    print(f"{len(rows)} labelled decks; {len(zero)} hold ZERO Game Changers\n")

    spread = collections.Counter(b for b, _d in zero)
    print("what the builders called those 0-GC decks:")
    for bracket in sorted(spread):
        print(f"  B{bracket}: {spread[bracket]:3d}")
    b3 = spread.get(3, 0)
    print(f"\n  -> {b3} of them are Bracket 3, and the shipped cap of 2 makes every one "
          f"of them unreachable.\n")

    for lo, hi in ((1, 2), (2, 3)):
        pair = [(b, d) for b, d in zero if b in (lo, hi)]
        if len(pair) < 20:
            continue
        counts = collections.Counter(b for b, _d in pair)
        majority = max(counts.values()) / len(pair)
        print(f"=== B{lo} vs B{hi}, zero Game Changers "
              f"(n={len(pair)}: {counts[lo]} / {counts[hi]}) ===")
        print(f"    baseline, always say the majority: {100*majority:.1f}%")
        scored = []
        for key in CANDIDATES:
            curve = sweep(pair, key, (lo, hi))
            found = plateau(curve)
            if not found:
                continue
            (threshold, acc, r_lo, r_hi, ascending), width, best = found
            scored.append((acc, key, threshold, r_lo, r_hi, width, best, ascending))
        for acc, key, threshold, r_lo, r_hi, width, best, asc in sorted(
                scored, reverse=True)[:5]:
            flag = "  <-- beats baseline" if acc > majority + 0.02 else ""
            arrow = ">=" if asc else "<="
            print(f"  {key:>18}  {arrow}{threshold:8.3f} -> B{hi}   acc {100*acc:5.1f}%  "
                  f"(peak {100*best:5.1f}%, plateau {width})  "
                  f"B{lo} {100*r_lo:4.0f}% / B{hi} {100*r_hi:4.0f}%{flag}")
        print()

    # Two signals at once, only for the boundary that needs it most.
    pair = [(b, d) for b, d in zero if b in (2, 3)]
    if len(pair) >= 20:
        print("=== B2 vs B3, two-signal rules (both must agree to say B3) ===")
        counts = collections.Counter(b for b, _d in pair)
        majority = max(counts.values()) / len(pair)
        best_pairs = []
        for k1, k2 in itertools.combinations(CANDIDATES[:5], 2):
            c1 = sweep(pair, k1, (2, 3))
            c2 = sweep(pair, k2, (2, 3))
            for t1, _a1, _l1, _h1, asc1 in c1[::8]:
                for t2, _a2, _l2, _h2, asc2 in c2[::8]:
                    def says3(d, k=k1, t=t1, a=asc1):
                        return (d[k] >= t) if a else (d[k] <= t)

                    def says3b(d, k=k2, t=t2, a=asc2):
                        return (d[k] >= t) if a else (d[k] <= t)
                    correct = sum(
                        (3 if (says3(d) and says3b(d)) else 2) == b for b, d in pair)
                    best_pairs.append((correct / len(pair), k1, t1, asc1, k2, t2, asc2))
        for acc, k1, t1, a1, k2, t2, a2 in sorted(best_pairs, reverse=True)[:4]:
            print(f"  {100*acc:5.1f}%   {k1} {'>=' if a1 else '<='} {t1:.3f}  AND  "
                  f"{k2} {'>=' if a2 else '<='} {t2:.3f}")
        print(f"  (baseline {100*majority:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
