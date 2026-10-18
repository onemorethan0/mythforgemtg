"""Fit the bracket strength model (ratings/strength_model.py) to player-labelled decks.

    python scripts/bracket_strength_fit.py --collect          # sweep labelled decks -> cache
    python scripts/bracket_strength_fit.py                    # CV report from the cache
    python scripts/bracket_strength_fit.py --bake             # fit on all rows, write the block
    python scripts/bracket_strength_fit.py --check            # exit 1 if the baked model drifted

COLLECT runs the live pipeline -- `analyze_deck` with the FULL compiled semantics store,
resilience on, and the real Commander Spellbook combo lookup (cached by decklist hash) -- so
the model is fitted on exactly the numbers the engine produces at runtime. Each row keeps the
model's input features, the player label, and the gate inputs `_place_by_strength` needs
(official floor, cEDH combo signal, combat kill rate), so the CV report scores the REAL
placement rule, not a re-implementation of it.

FIT is ridge regression of the label on the standardised features (closed form, numpy only),
then four cut points chosen on the training fold by coordinate ascent to maximise BALANCED
recall (mean per-bracket recall), so the small B1 class is not swallowed by B2/B3. CV is stratified 5-fold. The label is the builder's own Archidekt bracket:
self-reported consensus, not ground truth (see scripts/bracket_accuracy.py).

NOT CI-SAFE: needs the card store, the compiled CCM store and (first run) network for
Spellbook. ~25 min with 12 workers.
"""

from __future__ import annotations

import argparse
import json
import pprint
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src", ROOT / "scripts"):
    sys.path.insert(0, str(p))

from mythgauntlet.ratings import strength_model  # noqa: E402

CACHE = ROOT / ".cache" / "bracket_strength_rows.jsonl"
TARGET = ROOT / "src" / "mythgauntlet" / "ratings" / "strength_model.py"
_BLOCK = re.compile(r"(# === BEGIN GENERATED: STRENGTH_MODEL ===\n)(.*?)(# === END GENERATED: STRENGTH_MODEL ===)", re.S)
RUNS = 120
RIDGE_ALPHA = 5.0
FEATURES = strength_model.FEATURES

_DB = _STORE = None


def _init() -> None:
    global _DB, _STORE
    from mythgauntlet.data.scryfall import load_card_db
    from mythgauntlet.semantics.store import load_store
    _DB = load_card_db()
    _STORE = load_store()


def _row(item: tuple[str, int]) -> dict | None:
    from bracket_accuracy import real_combo_lookup
    from mythgauntlet.model.deck import Deck, resolve
    from mythgauntlet.ratings import manabase
    from mythgauntlet.ratings.analysis import analyze_deck
    from mythgauntlet.ratings.bracket import _fast_two_card_combo
    from mythgauntlet.sim.tier0 import DEFAULT_ANALYZE_TURNS, SimConfig
    path, label = Path(item[0]), item[1]
    try:
        resolved = resolve(Deck.parse_text(path.read_text(encoding="utf-8")), _DB)
        if resolved.card_count < 90 or not resolved.commanders:
            return None
        combo_report, failed = real_combo_lookup(resolved, path.name)
        cfg = SimConfig(turns=DEFAULT_ANALYZE_TURNS, runs=RUNS, seed=42)
        a = analyze_deck(resolved, cfg, _STORE, combo_report=combo_report,
                         combos_checked=combo_report is not None, run_resilience=True)
        r = a.report
        feats = strength_model.features(
            cards=resolved.cards, commanders=resolved.commanders, horizon=cfg.turns,
            consistency=r.consistency_score, kill_rate=r.goldfish_kill_rate,
            avg_kill_turn=r.avg_kill_turn, avg_commander_turn=r.avg_commander_turn,
            resilience=a.resilience.resilience_score if a.resilience else None,
            interaction=a.interaction.score, ceiling=a.ceiling.score, pod=a.pod.score,
            manabase=manabase.analyze(resolved.cards, resolved.commanders).consistency,
        )
        return {"deck": path.name, "label": label, "features": feats,
                "floor": a.bracket.floor, "speed_kill_rate": r.goldfish_kill_rate,
                "cedh_combo": _fast_two_card_combo(0, a.combo_profile),
                "combos_checked": combo_report is not None and not failed,
                "shipped_bracket": a.bracket.bracket}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{path.name}: {exc}"}


def collect(workers: int) -> None:
    from bracket_accuracy import labelled_decks
    items = [(str(p), lab) for p, lab in labelled_decks()]
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with ProcessPoolExecutor(max_workers=workers, initializer=_init) as ex, \
            CACHE.open("w", encoding="utf-8") as fh:
        for row in ex.map(_row, items, chunksize=4):
            n += 1
            if row is None:
                continue
            if "error" in row:
                print("FAILED", row["error"], flush=True)
                continue
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            if n % 50 == 0:
                print(f"{n}/{len(items)}", flush=True)
    print(f"collected -> {CACHE}")


def load_rows() -> list[dict]:
    return [json.loads(line) for line in CACHE.read_text(encoding="utf-8").splitlines() if line]


def _matrix(rows: list[dict], means=None, scales=None) -> tuple[np.ndarray, dict, dict]:
    raw = np.array([[np.nan if r["features"].get(f) is None else r["features"][f]
                     for f in FEATURES] for r in rows], dtype=float)
    if means is None:
        means = {f: float(np.nanmean(raw[:, i])) for i, f in enumerate(FEATURES)}
        scales = {f: float(np.nanstd(raw[:, i]) or 1.0) for i, f in enumerate(FEATURES)}
    z = np.array([[0.0 if np.isnan(v) else (v - means[f]) / scales[f]
                   for v, f in zip(row, FEATURES)] for row in raw])
    return z, means, scales


def _place(rows: list[dict], scores: np.ndarray, cuts: list[float]) -> np.ndarray:
    """The live rule: max(floor, cut bracket) + the bracket-4 cEDH escalation."""
    from mythgauntlet.ratings.bracket import _CEDH_MAX_COMBAT_RELIANCE
    out = []
    for r, s in zip(rows, scores):
        b = max(r["floor"], 1 + int(np.searchsorted(cuts, s, side="right")))
        if b == 4 and r["cedh_combo"] and r["speed_kill_rate"] <= _CEDH_MAX_COMBAT_RELIANCE:
            b = 5
        out.append(b)
    return np.array(out)


def _ridge(z: np.ndarray, y: np.ndarray, keep: list[int]) -> np.ndarray:
    """Ridge on the kept columns; dropped columns get weight 0. beta[0] is the intercept."""
    X = np.hstack([np.ones((len(z), 1)), z[:, keep]])
    reg = RIDGE_ALPHA * np.eye(X.shape[1])
    reg[0, 0] = 0.0
    b = np.linalg.solve(X.T @ X + reg, X.T @ y)
    beta = np.zeros(len(FEATURES) + 1)
    beta[0] = b[0]
    beta[[k + 1 for k in keep]] = b[1:]
    return beta


def fit(rows: list[dict]) -> dict:
    z, means, scales = _matrix(rows)
    y = np.array([r["label"] for r in rows], dtype=float)
    # SIGN-CONSTRAINED: a signal may only push the bracket the way Magic says it does
    # (strength_model.SIGNS). The free fit gave kill rate, kill speed and resilience small
    # NEGATIVE weights (collinear signals traded against each other), which the reasons line
    # would have printed as "a faster deck lowers the bracket" -- a near-miss is a defect.
    # The weakest wrong-signed feature is dropped and the rest refitted until none remain;
    # measured cost ~0.5 pt of CV exact accuracy, with every casual bracket's recall still at
    # or above the gate-banded estimator's.
    keep = list(range(len(FEATURES)))
    while True:
        beta = _ridge(z, y, keep)
        wrong = [i for i in keep if beta[i + 1] * strength_model.SIGNS[FEATURES[i]] < 0]
        if not wrong:
            break
        keep.remove(min(wrong, key=lambda i: abs(beta[i + 1])))
    X = np.hstack([np.ones((len(z), 1)), z])
    scores = X @ beta
    cuts = [1.5, 2.5, 3.5, 4.5]
    grid = np.quantile(scores, np.linspace(0.01, 0.99, 80))
    for _ in range(4):
        for i in range(4):
            lo = cuts[i - 1] if i else -np.inf
            hi = cuts[i + 1] if i < 3 else np.inf
            best, bv = cuts[i], -1.0
            for c in grid:
                if lo < c < hi:
                    trial = cuts[:i] + [float(c)] + cuts[i + 1:]
                    p = _place(rows, scores, trial)
                    # BALANCED recall: plain accuracy let the big B2/B3 classes swallow
                    # B1 (CV recall 29% vs today's 37%); balancing kept every casual
                    # bracket at or above today's recall for -0.8 pt of exact accuracy
                    v = float(np.mean([(p[y == b] == b).mean() for b in range(1, 6)]))
                    if v > bv:
                        best, bv = float(c), v
            cuts[i] = best
    return {"means": means, "scales": scales, "intercept": float(beta[0]),
            "weights": {f: float(w) for f, w in zip(FEATURES, beta[1:])}, "cuts": cuts}


def _score(rows: list[dict], m: dict) -> np.ndarray:
    z, _, _ = _matrix(rows, m["means"], m["scales"])
    return m["intercept"] + z @ np.array([m["weights"][f] for f in FEATURES])


def summarize(y: np.ndarray, pred: np.ndarray) -> dict:
    cas = y <= 3
    return {
        "exact": float((pred == y).mean()), "within_one": float((abs(pred - y) <= 1).mean()),
        "casual_exact": float((pred[cas] == y[cas]).mean()), "bias": float((pred - y).mean()),
        "recall": {int(b): float((pred[y == b] == b).mean()) for b in range(1, 6)},
    }


def cross_validate(rows: list[dict], k: int = 5) -> dict:
    y = np.array([r["label"] for r in rows])
    rng = np.random.default_rng(0)
    fold = np.zeros(len(rows), dtype=int)
    for b in range(1, 6):  # stratified
        idx = np.where(y == b)[0]
        rng.shuffle(idx)
        fold[idx] = np.arange(len(idx)) % k
    pred = np.zeros(len(rows), dtype=int)
    for f in range(k):
        tr = [r for r, g in zip(rows, fold) if g != f]
        te_idx = np.where(fold == f)[0]
        te = [rows[i] for i in te_idx]
        m = fit(tr)
        pred[te_idx] = _place(te, _score(te, m), m["cuts"])
    return summarize(y, pred)


def _fmt(s: dict) -> str:
    return (f"exact {s['exact']:.1%}, within-one {s['within_one']:.1%}, B1-3 exact "
            f"{s['casual_exact']:.1%}, bias {s['bias']:+.2f}, recall "
            + " ".join(f"B{b} {v:.0%}" for b, v in s["recall"].items()))


def bake(rows: list[dict]) -> None:
    m = fit(rows)
    cv = cross_validate(rows)
    y = np.array([r["label"] for r in rows])
    shipped = summarize(y, np.array([r["shipped_bracket"] for r in rows]))
    note = (f"fitted {time.strftime('%Y-%m-%d')} on {len(rows)} player-labelled decks (full CCM "
            f"store, real Spellbook combos, runs={RUNS}). 5-fold CV of the live rule: "
            f"{_fmt(cv)}. Gate-banded estimator on the same decks: {_fmt(shipped)}.")
    r4 = lambda d: {k: round(v, 4) for k, v in d.items()}
    body = (
        "# Generated by scripts/bracket_strength_fit.py. Do not edit by hand; re-run with --bake.\n"
        f"MEANS: dict[str, float] = {pprint.pformat(r4(m['means']), width=96, sort_dicts=False)}\n"
        f"SCALES: dict[str, float] = {pprint.pformat(r4(m['scales']), width=96, sort_dicts=False)}\n"
        f"WEIGHTS: dict[str, float] = {pprint.pformat(r4(m['weights']), width=96, sort_dicts=False)}\n"
        f"INTERCEPT = {m['intercept']:.4f}\n"
        f"CUTS: tuple[float, ...] = {tuple(round(c, 4) for c in m['cuts'])!r}\n"
        f"MODEL_NOTE = {note!r}\n"
    )
    src = TARGET.read_text(encoding="utf-8")
    new, n = _BLOCK.subn(lambda mm: mm.group(1) + body + mm.group(3), src)
    if n != 1:
        sys.exit("generated block not found")
    TARGET.write_text(new, encoding="utf-8")
    print(note)


def check(rows: list[dict]) -> int:
    m = fit(rows)
    drift = [f for f in FEATURES if abs(m["weights"][f] - strength_model.WEIGHTS.get(f, 99)) > 0.02]
    drift += [f"cut{i}" for i, (a, b) in enumerate(zip(m["cuts"], strength_model.CUTS)) if abs(a - b) > 0.05]
    if drift:
        print("DRIFT:", drift)
        return 1
    print("strength model is current")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--bake", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.collect:
        collect(args.workers)
    rows = load_rows()
    if args.check:
        return check(rows)
    if args.bake:
        bake(rows)
        return 0
    y = np.array([r["label"] for r in rows])
    print(f"{len(rows)} rows")
    print("gate-banded (shipped):", _fmt(summarize(y, np.array([r["shipped_bracket"] for r in rows]))))
    print("strength model, CV:   ", _fmt(cross_validate(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
