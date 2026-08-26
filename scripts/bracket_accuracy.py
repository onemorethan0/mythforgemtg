"""Does the bracket estimate match what the deck's own builder called it?

THE APP'S CENTRAL CLAIM IS A NUMBER, AND IT HAS NEVER BEEN SCORED. `docs/engine/ROADMAP.md`
Phase 5 sets the accept criteria — **>=60% bracket-exact, >=95% within-one, leave-one-out on
corpus** — and leaves the box unticked with the note "still too few labels to fit without
overfitting". That is true of *fitting* a learned model. It is not true of *measuring* the
rule-based estimator that actually ships: 297 of the 499 corpus decks carry a `# bracket: N`
line, and 269 of those sit in brackets 1-3, which is the range this project exists to serve.

So the measurement was available the whole time and the accept criteria were never applied to
the estimator that ships.

WHAT THE LABEL IS, AND WHAT IT IS NOT. It is the bracket the deck's own builder chose on
Archidekt. That makes it self-reported, unaudited, and prone to two known biases: builders
under-rate their own decks ("mine is just a 2"), and the bracket system is recent enough that
many labels predate people internalising the gates. It is NOT ground truth in the sense a
compiled CCM is.

It is still the right thing to measure against, for one reason: the product question is "is
this deck on-level for my pod", and the pod is made of people who label their decks exactly
this way. A systematic disagreement with the players is a real defect even if the players are
the ones who are wrong, because the number has to mean the same thing to both sides.

READ THE CONFUSION MATRIX, NOT THE HEADLINE. Exact-match hides the two failures that matter
differently: calling a bracket-2 deck a 4 sends someone to the wrong table, while calling a
4 a 3 is a rounding error inside the casual band. The per-bracket recall and the signed bias
are what say which one is happening.

    python scripts/bracket_accuracy.py                 # all labelled decks
    python scripts/bracket_accuracy.py --limit 40      # a fast slice
    python scripts/bracket_accuracy.py --json out.json

THE COMBO GATE IS AN INPUT, NOT A DETECTOR. `analyze_deck(two_card_combos=N)` is told how many
game-ending combos a deck holds by an external Spellbook lookup; it does not go and find them.
The first version of this script passed 2, which declared two combos on every deck, promoted
all of them past the "min Bracket 3" gate, and produced a confusion matrix in which the engine
never emitted 1 or 2 at all. That was the harness lying to the engine. The default here is 0 -
"not checked" - which is what the engine can honestly know offline, and it means these numbers
are the estimate WITHOUT the combo gate.

NOT CI-SAFE: needs data/cards_slim.json and a semantics store. No network, no LLM, no GPU.
"""

from __future__ import annotations

import argparse
import collections
import io
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def _ensure_utf8_stdout() -> None:
    """A card or deck name must not be able to kill a long run (see build_reason_sft)."""
    for attr in ("stdout", "stderr"):
        stream = getattr(sys, attr, None)
        if stream is None or not hasattr(stream, "buffer"):
            continue
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if encoding != "utf8" or getattr(stream, "errors", "") != "replace":
            setattr(sys, attr,
                    io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"))


_ensure_utf8_stdout()

# The app's horizon, so --turns defaults to what a user actually gets.
sys.path.insert(0, str(ROOT / "src"))
from mythgauntlet.sim.tier0 import DEFAULT_ANALYZE_TURNS  # noqa: E402

_LABEL_RE = re.compile(r"^#\s*bracket:\s*([1-5])\s*$", re.MULTILINE)


def labelled_decks(limit: int | None = None) -> list[tuple[Path, int]]:
    """Every corpus deck carrying a `# bracket: N` line, with its label."""
    out: list[tuple[Path, int]] = []
    for path in sorted((ROOT / "corpus" / "decks").glob("*.txt")):
        match = _LABEL_RE.search(path.read_text(encoding="utf-8"))
        if match:
            out.append((path, int(match.group(1))))
        if limit and len(out) >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--runs", type=int, default=120,
                    help="sim runs per deck. The bracket GATES are rule-based; the axes only "
                         "place a deck within its band, so this is cheaper than /analyze.")
    ap.add_argument("--turns", type=int, default=DEFAULT_ANALYZE_TURNS,
                    help="sim horizon. Defaults to the APP's value. The first version of this "
                         "script hard-coded 8 while /analyze runs 12, so it scored a "
                         "configuration no user ever gets - and the difference is not "
                         "cosmetic: the Ceiling axis scales by cfg.turns and the nut-turn "
                         "threshold is max(4, turns*0.6), i.e. turn 4 at a horizon of 8 and "
                         "turn 7 at 12.")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--combos", type=int, default=0,
                    help="two-card combos to DECLARE per deck. This is an input from an "
                         "external Spellbook lookup, not a detector - the offline default "
                         "of 0 means 'not checked', which is what the engine can honestly "
                         "know without the network.")
    args = ap.parse_args()
    combos = args.combos

    from mythgauntlet.data.scryfall import load_card_db
    from mythgauntlet.model.deck import Deck, resolve
    from mythgauntlet.ratings.analysis import analyze_deck
    from mythgauntlet.semantics.store import SemanticsStore
    from mythgauntlet.sim.tier0 import SimConfig  # noqa: F811

    started = time.time()
    db = load_card_db()
    store = SemanticsStore()
    decks = labelled_decks(args.limit)
    print(f"store {len(store._by_name)} cards; {len(decks)} labelled decks "
          f"({time.time()-started:.0f}s)", flush=True)

    cfg = SimConfig(turns=args.turns, runs=args.runs, seed=42)
    rows = []
    for index, (path, label) in enumerate(decks, 1):
        resolved = resolve(Deck.parse_text(path.read_text(encoding="utf-8")), db)
        if resolved.card_count < 90:
            continue
        try:
            # two_card_combos is an INPUT count from an external Spellbook lookup, not a
            # request to go and detect them. Passing 2 here (which the first version of this
            # script did) tells the engine every deck holds two game-ending combos, and the
            # gate promotes all of them to "min Bracket 3" - producing a confusion matrix
            # where the engine never emits 1 or 2 and looks catastrophically miscalibrated.
            # It was the harness lying to the engine. Leave it at the honest default.
            analysis = analyze_deck(resolved, cfg, store,
                                    two_card_combos=combos, combos_checked=bool(combos))
        except Exception as exc:                     # noqa: BLE001 - one deck is not fatal
            print(f"  [{index}] {path.name}: FAILED {exc}", flush=True)
            continue
        estimate = analysis.bracket
        rows.append({"deck": path.name, "label": label,
                     "predicted": estimate.bracket,
                     "confidence": round(getattr(estimate, "confidence", 0.0) or 0.0, 2),
                     "game_changers": getattr(estimate, "game_changers", 0),
                     "reasons": list(getattr(estimate, "reasons", []) or [])})
        if index % 25 == 0:
            print(f"  {index}/{len(decks)} ({int(time.time()-started)}s)", flush=True)

    if not rows:
        print("no decks scored")
        return 1

    exact = sum(r["label"] == r["predicted"] for r in rows)
    within = sum(abs(r["label"] - r["predicted"]) <= 1 for r in rows)
    bias = sum(r["predicted"] - r["label"] for r in rows) / len(rows)
    n = len(rows)

    print(f"\n{'='*62}\nscored {n} labelled decks "
          f"(runs={args.runs}, turns={args.turns})\n{'='*62}")
    print(f"  bracket-exact   {exact:4d}/{n}  {100*exact/n:5.1f}%   (accept: >=60%)")
    print(f"  within-one      {within:4d}/{n}  {100*within/n:5.1f}%   (accept: >=95%)")
    print(f"  signed bias     {bias:+.2f} brackets  (positive = the engine rates HIGHER "
          f"than the builder)")

    print("\nconfusion — rows are the builder's label, columns the engine's estimate")
    header = "        " + "".join(f"{p:>6}" for p in range(1, 6)) + "     n   recall"
    print(header)
    for label in range(1, 6):
        sub = [r for r in rows if r["label"] == label]
        if not sub:
            continue
        counts = collections.Counter(r["predicted"] for r in sub)
        cells = "".join(f"{counts.get(p, 0):>6}" for p in range(1, 6))
        hit = counts.get(label, 0)
        print(f"  B{label}   {cells}{len(sub):>6}{100*hit/len(sub):>8.1f}%")

    casual = [r for r in rows if r["label"] <= 3]
    if casual:
        c_exact = sum(r["label"] == r["predicted"] for r in casual)
        c_within = sum(abs(r["label"] - r["predicted"]) <= 1 for r in casual)
        print(f"\nbrackets 1-3 only — the range this project exists to serve ({len(casual)} decks)")
        print(f"  exact {100*c_exact/len(casual):.1f}%   within-one {100*c_within/len(casual):.1f}%")

    # A B1/B2 label holding >=1 real Game Changer is not an engine disagreement to
    # measure against — it is IMPOSSIBLE under the bracket system's own rules (a Game
    # Changer present at all rules out Brackets 1-2, independent of anything the engine
    # thinks). This is the same "author labels are ~6% noisy" defect docs/engine/STATUS.md
    # already found on a smaller anchor set, now connected to this harness directly
    # (PLAN_CLOCK.md, 2026-08-26): filtering these 13 self-contradictory labels out of the
    # 297 moves within-one from 91.6% (below the 95% accept bar) to 95.1% (clears it) with
    # ZERO engine changes — the filter never references what the engine predicted, only
    # whether the label is even possible under the rules it claims.
    rule_valid = [r for r in rows if not (r["label"] in (1, 2) and r["game_changers"] > 0)]
    rule_noise = len(rows) - len(rule_valid)
    if rule_noise:
        v_exact = sum(r["label"] == r["predicted"] for r in rule_valid)
        v_within = sum(abs(r["label"] - r["predicted"]) <= 1 for r in rule_valid)
        print(f"\nexcluding {rule_noise} label(s) impossible under the rules — a B1/B2 self-"
              f"label holding >=1 real Game Changer ({len(rule_valid)} decks)")
        print(f"  exact {100*v_exact/len(rule_valid):.1f}%   "
              f"within-one {100*v_within/len(rule_valid):.1f}%")

    print("\nmost common estimate per label (what the engine actually says):")
    for label in range(1, 6):
        sub = [r["predicted"] for r in rows if r["label"] == label]
        if sub:
            mode, count = collections.Counter(sub).most_common(1)[0]
            print(f"  builder said B{label}  ->  engine usually says B{mode} "
                  f"({100*count/len(sub):.0f}% of them)")

    if args.json:
        args.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
