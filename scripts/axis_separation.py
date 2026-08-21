"""Which measured signals actually separate the labeled brackets?

Calibration discipline: before any axis is allowed to influence a bracket verdict, it has to
demonstrate separation on the labeled anchor set. This script is that test. Run it whenever
the anchor corpus grows or an axis changes.

It reports two things per signal:
  * Spearman rho against the bracket label  — is it monotone across the whole ladder?
  * Cohen's d for each adjacent pair        — can it actually tell B1 from B2, B2 from B3?

rho answers "does this trend with power"; d answers "is the gap big enough to act on". A
signal can trend beautifully overall and still be useless at the boundary you care about,
which is exactly what happened with Game Changers at B1-vs-B2.

Usage:
  .venv\\Scripts\\python scripts\\axis_separation.py [--runs 200] [--seed 42]
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mythgauntlet import cli  # noqa: E402
from mythgauntlet.model.deck import Deck, resolve  # noqa: E402
from mythgauntlet.ratings import metrics  # noqa: E402
from mythgauntlet.ratings.axes import compute_ceiling, compute_interaction  # noqa: E402
from mythgauntlet.ratings.manabase import analyze as manabase_analyze  # noqa: E402
from mythgauntlet.semantics import tags  # noqa: E402
from mythgauntlet.sim.tier0 import SimConfig, simulate  # noqa: E402

CORPUS = REPO / "corpus" / "decks"


def _spearman(pairs: list[tuple[float, float]]) -> float:
    """Rank correlation with TIE AVERAGING — bracket labels are full of ties, and naive
    ordinal ranking would manufacture a spread that isn't in the data."""
    def rank(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            avg = (i + j) / 2
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    x, y = rank([p[0] for p in pairs]), rank([p[1] for p in pairs])
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    den = (sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y)) ** 0.5
    return num / den if den else 0.0


def _cohen_d(a: list[float], b: list[float]) -> float:
    if len(a) < 2 or len(b) < 2:
        return 0.0
    pooled = (
        ((len(a) - 1) * statistics.variance(a) + (len(b) - 1) * statistics.variance(b))
        / (len(a) + len(b) - 2)
    ) ** 0.5
    return (statistics.mean(b) - statistics.mean(a)) / pooled if pooled else 0.0


def _verdict(d: float) -> str:
    a = abs(d)
    return "STRONG" if a >= 0.8 else "moderate" if a >= 0.5 else "weak" if a >= 0.2 else "none"


def _card_quality(resolved) -> dict[str, float]:
    """Composition/card-quality signals — the last untried angle on the B2/B3 boundary.

    Measured 2026-07-28 on the 120 zero-Game-Changer B2/B3 anchors: EVERY one of these came
    back "none" (|d| <= 0.19), including `edhrec_log_rank`, the popularity proxy that should
    most obviously track card quality. Kept in the harness so they are re-measured for free
    as the corpus grows — if a real effect exists, it will surface here first.
    """
    cards = list(resolved.cards) + [(resolved.commanders[0], 1)]
    nonland = [(c, q) for c, q in cards if not c.is_land]
    lands = [(c, q) for c, q in cards if c.is_land]
    total = sum(q for _, q in nonland) or 1
    fx = {c.name: tags.analyze(c) for c, _ in cards}

    def count(pred) -> float:
        return float(sum(q for c, q in nonland if pred(c, fx[c.name])))

    ranks = [math.log(c.edhrec_rank) for c, _ in nonland if c.edhrec_rank]
    tapped = sum(q for c, q in lands if fx[c.name].enters_tapped)
    return {
        "cheap_interaction": count(
            lambda c, f: (f.removal or f.counterspell) and c.mana_value <= 2
        ),
        "fast_mana": count(lambda c, f: (f.ramp_sources or f.ritual_mana) and c.mana_value <= 2),
        "tutor_density": count(lambda c, f: f.tutor),
        "engine_density": count(lambda c, f: f.engine_draw),
        "low_curve_share": count(lambda c, _f: c.mana_value <= 2) / total,
        "untapped_land_share": 1 - (tapped / (sum(q for _, q in lands) or 1)),
        # Popularity proxy. Invariant 4 (popularity is a prior, never a verdict) means this
        # may inform research but must not drive a verdict — it is measured here precisely so
        # the question "would popularity have helped?" has a recorded answer.
        #
        # CORRECTED 2026-08-21: the recorded answer used to read "It doesn't", and that is
        # measurably wrong. Re-measured over 159 zero-Game-Changer decks at the B1/B2
        # boundary (scripts/bracket_boundary.py), a single threshold on this signal scores
        # **76.1%** against **64.8%** for `manabase_P`, which is what actually ships — an
        # 11-point gap, on a broad smooth plateau (>=70% across 7.51..8.08), with far better
        # balance (B1 65% / B2 84% vs 30% / 91%). Cohen's d is -1.02 here and -0.54 at B2/B3,
        # the strongest non-Game-Changer signal at both casual boundaries.
        #
        # IT IS STILL BARRED, and the correction matters precisely because of that: invariant
        # 4 rests on the argument that a popularity-driven verdict recreates the
        # static-calculator failure mode this engine exists to replace, NOT on popularity
        # being weak. Leaving a false empirical claim inside the rule's justification made the
        # rule look like it was defending a measurement instead of a principle. It is a
        # principle, and it holds against a signal that works.
        #
        # The concrete failure it prevents: EDHREC rank measures how MAINSTREAM a deck is. A
        # budget pile of staples would rate up and an expensive brew of obscure bombs would
        # rate down, and every card from a new set carries a poor rank regardless of power —
        # the same "an absent card is unmeasured, not rejected" trap `edhrec_lift` documents.
        # It may also be reading the ANNOTATOR rather than the deck: people who build from
        # published lists label differently from people who brew.
        "edhrec_log_rank": statistics.mean(ranks) if ranks else 0.0,
    }


def collect(runs: int, seed: int) -> list[tuple[int, dict[str, float]]]:
    db = cli._load_db()
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    labels = {e["file"]: e.get("bracket") for e in manifest.get("decks", [])}
    cfg = SimConfig(turns=14, runs=runs, seed=seed)

    rows: list[tuple[int, dict[str, float]]] = []
    for path in sorted(CORPUS.glob("*.txt")):
        bracket = labels.get(path.name)
        if not bracket:
            continue
        resolved = resolve(Deck.parse_text(path.read_text(encoding="utf-8"), name=path.stem), db)
        if not resolved.cards or not resolved.commanders:
            continue
        commander = resolved.commanders[0]
        sim_runs = simulate(resolved.cards, commander, cfg)
        report = metrics.compute(sim_runs, cfg)
        interaction = compute_interaction(resolved.cards, commander)
        ceiling = compute_ceiling(sim_runs, cfg)
        every = list(resolved.cards) + [(commander, 1)]
        nonland = [c.mana_value for c, _ in resolved.cards if not c.is_land]
        rows.append((bracket, {
            "game_changers": float(sum(q for c, q in every if c.game_changer)),
            "manabase_P": manabase_analyze(resolved.cards, resolved.commanders).consistency,
            **_card_quality(resolved),
            "interaction": interaction.score,
            "effective_answers": interaction.effective_answers,
            "ceiling": ceiling.score,
            "nut_kill_rate": ceiling.nut_kill_rate,
            "consistency": report.consistency_score,
            "cmdr_turn": report.avg_commander_turn or 0.0,
            "avg_mv": statistics.mean(nonland) if nonland else 0.0,
            "kill_turn": report.avg_kill_turn or 0.0,
        }))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rows = collect(args.runs, args.seed)
    if not rows:
        print("No labeled decks in the corpus — run fetch-decks --bracket N first.")
        return 2
    keys = list(rows[0][1])

    print(f"n = {len(rows)} labeled decks (runs={args.runs}, seed={args.seed})\n")
    print(f"{'signal':>18} |" + "".join(f"   B{b}   " for b in (1, 2, 3, 4, 5)) + "|    rho")
    print("-" * 80)
    ranked = []
    for key in keys:
        by = defaultdict(list)
        for bracket, data in rows:
            by[bracket].append(data[key])
        cells = "".join(
            f"{statistics.mean(by[b]):>7.2f} " if by[b] else "    --  " for b in (1, 2, 3, 4, 5)
        )
        rho = _spearman([(float(b), d[key]) for b, d in rows])
        ranked.append((abs(rho), key, cells, rho))
    for _, key, cells, rho in sorted(ranked, reverse=True):
        print(f"{key:>18} |{cells}| {rho:+.3f}" + ("  <-- signal" if abs(rho) > 0.3 else ""))

    for lo, hi in ((1, 2), (2, 3), (3, 4), (4, 5)):
        a = [d for b, d in rows if b == lo]
        b_ = [d for b, d in rows if b == hi]
        if len(a) < 2 or len(b_) < 2:
            continue
        print(f"\n=== B{lo} (n={len(a)}) vs B{hi} (n={len(b_)}) ===")
        pairs = sorted(
            ((abs(_cohen_d([r[k] for r in a], [r[k] for r in b_])), k) for k in keys), reverse=True
        )
        for _, key in pairs[:4]:
            d = _cohen_d([r[key] for r in a], [r[key] for r in b_])
            print(f"  {key:>18}  d = {d:+.2f}   {_verdict(d)}")

    # Label hygiene: B1/B2 are defined as zero Game Changers, so any is an author error.
    for bracket in (1, 2):
        counts = [d["game_changers"] for b, d in rows if b == bracket]
        if counts:
            bad = sum(1 for c in counts if c > 0)
            print(f"\nlabel noise: B{bracket} decks with >=1 Game Changer (rules say 0): "
                  f"{bad}/{len(counts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
