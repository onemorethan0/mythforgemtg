"""Build a supervised fine-tuning set for swap explanations, by rejection sampling.

The CCM corpus works because it is VERIFIED training data: every document passed the same
gates the engine trusts at run time, so ~30k card→CCM pairs exist with no human annotation
anywhere in the loop. Swap explanations have no such validator — nothing can mechanically say
"this paragraph is good advice."

What CAN be checked is FAITHFULNESS, and on this project that is the property that matters:
every number traced to a measurement, every card name inside the swap, every function claim
agreeing with the rung-1 vector, no redundancy asserted on a deck that over-supplies nothing.
`swap_narrative.check` is that gate. So the same pipeline shape applies —

    teacher drafts  ->  deterministic gates  ->  keep what survives  ->  QLoRA a small model

— and this script is the middle two steps. It is the direct analogue of
`scripts/build_ccm_sft.py`, and it deliberately writes the same `{"messages": [...]}` JSONL so
`scripts/train_ccm_lora.py` can consume it unchanged.

TWO PHASES, because they are bound by different resources and fail differently.

  --harvest   Runs the real advisor over corpus decks to collect SwapBriefs. Sim-bound and
              slow (~40 analyses per deck), needs the semantics store, and is the part worth
              caching. Writes briefs.json.
  --draft     Reads briefs.json, samples the teacher k times per brief, gates each sample,
              keeps the survivors. LLM-bound. Cheap to re-run after a gate or prompt change,
              which is exactly what you want, because tightening the gate is the normal way
              this corpus improves.

THE SPLIT IS BY DECK, NOT BY SWAP. Two swaps from one deck share its commander, archetype and
role supply, so splitting per suggestion would put near-duplicate context on both sides of the
boundary and flatter the eval. Hashing the deck name (not its index) also means the split
survives the corpus growing, the same reasoning `build_ccm_sft.split_of` documents.

THE TRAINED SYSTEM PROMPT IS SHORTER THAN THE TEACHER'S. The teacher is handed every rule the
gate enforces, because a rule it is never told is a guaranteed rejection. The fine-tune is
supposed to LEARN those rules, so its records carry a terse prompt — same trade
`build_ccm_sft.py` makes when it drops the 14 few-shot exemplars, and the same inference win.

    python scripts/build_reason_sft.py --harvest --decks 60 --out data/reason_sft
    python scripts/build_reason_sft.py --draft --out data/reason_sft --model qwen3:32b -k 3
    E:\\ccm-train\\.venv\\Scripts\\python.exe scripts/train_ccm_lora.py \\
        --data data/reason_sft --out E:\\ccm-train\\qwen3-8b-reasons

NOT CI-SAFE: --harvest needs data/cards_slim.json and a semantics store; --draft needs
llama-swap on :8010. The candidate pool is the user's own collection (contract C1), because
that is what the live /advise route actually feeds the advisor — so a corpus rebuilt on
another machine will differ, and that is a property of the input, not a bug here.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)
os.environ.setdefault("MYTHFORGE_EDHREC_LIFT", "off")   # harvesting must not hit the network

import deck_themes                                       # noqa: E402
import swap_narrative                                    # noqa: E402

BRIEFS_FILE = "briefs.json"

# Terse. Every rule the teacher needed spelled out is what the fine-tune is FOR.
TRAINED_SYSTEM = (
    "Explain one card swap in a Magic: The Gathering Commander deck. Two or three sentences "
    "of plain prose for a casual player: why the added card helps, and why that particular "
    "card is the one to cut. Use only the facts given."
)


def advisor_axes() -> tuple:
    """The five Power Profile axes, read from the engine rather than restated.

    A list copied here would drift the first time an axis is added, and the corpus would
    silently stop covering it.
    """
    from mythgauntlet.ratings.advisor import AXES
    return tuple(AXES)


def split_of(deck: str, eval_frac: float) -> str:
    """Deterministic per-DECK split. Two swaps from one deck share almost all their context."""
    digest = hashlib.sha256(deck.encode("utf-8")).digest()
    return "eval" if int.from_bytes(digest[:4], "big") / 0xFFFFFFFF < eval_frac else "train"


# ── phase 1: harvest ─────────────────────────────────────────────────────────────

def harvest(out: Path, decks: int, runs: int, max_eval: int, cut_pool: int,
            axes: list) -> int:
    import collection
    from mythgauntlet.data.scryfall import load_card_db
    from mythgauntlet.model.deck import Deck, resolve
    from mythgauntlet.ratings import advisor
    from mythgauntlet.semantics.store import SemanticsStore
    from mythgauntlet.sim.tier0 import SimConfig

    started = time.time()
    db = load_card_db()
    store = SemanticsStore()
    print(f"store: {len(store._by_name)} cards ({time.time()-started:.0f}s)", flush=True)

    candidates = [c for c in (db.get(n) for n in sorted(collection.load_owned_names())) if c]
    print(f"candidate pool (your collection): {len(candidates)}", flush=True)
    if not candidates:
        print("No owned cards resolved — the advisor suggests from cards you OWN.")
        return 1

    rows: list[dict] = []
    paths = sorted((ROOT / "corpus" / "decks").glob("*.txt"))
    seen = 0
    for path in paths:
        if seen >= decks:
            break
        resolved = resolve(Deck.parse_text(path.read_text(encoding="utf-8")), db)
        if resolved.card_count < 90:
            continue
        seen += 1
        themes = deck_themes.detect_deck_themes([
            {"name": c.name, "type_line": c.type_line, "oracle_text": c.oracle_text}
            for c, _n in resolved.cards
        ])
        cfg = SimConfig(turns=8, runs=runs, seed=42)
        deck_names = ({c.name for c, _n in resolved.cards}
                      | {c.name for c in resolved.commanders})
        found = 0
        for axis in axes:
            try:
                report = advisor.advise(resolved, cfg, store, candidates, top=5,
                                        max_eval=max_eval, cut_pool=cut_pool,
                                        themes=themes, axis=axis)
            except Exception as exc:                 # noqa: BLE001 - one axis is not fatal
                print(f"  [{seen}] {path.name} {axis or 'weakest'}: FAILED {exc}", flush=True)
                continue
            for suggestion in report.suggestions:
                if suggestion.brief is None:
                    continue
                rows.append({"deck": path.name,
                             "brief": suggestion.brief.as_dict(),
                             "template": suggestion.reason,
                             "deck_card_names": sorted(deck_names)})
                found += 1
        print(f"  [{seen}/{decks}] {path.name}: {found} briefs "
              f"({int(time.time()-started)}s elapsed)", flush=True)

    out.mkdir(parents=True, exist_ok=True)
    (out / BRIEFS_FILE).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"\nharvested {len(rows)} briefs from {seen} decks -> {out / BRIEFS_FILE}")
    return 0


# ── phase 2: draft + gate ────────────────────────────────────────────────────────

def draft(out: Path, model: str, k: int, temperature: float, eval_frac: float) -> int:
    briefs_path = out / BRIEFS_FILE
    if not briefs_path.exists():
        print(f"No {briefs_path}. Run --harvest first.")
        return 1
    rows = json.loads(briefs_path.read_text(encoding="utf-8"))
    print(f"{len(rows)} briefs; sampling {k}x on {model} at temp {temperature}\n", flush=True)

    handles = {s: (out / f"{s}.jsonl").open("w", encoding="utf-8") for s in ("train", "eval")}
    kept = collections.Counter()
    # Which CHECK rejected a sample. This is the number that says whether the gate or the
    # model is the bottleneck, and it is why `check` returns reasons instead of a boolean.
    rejects: collections.Counter[str] = collections.Counter()
    samples = 0
    started = time.time()
    try:
        for index, row in enumerate(rows, 1):
            brief = row["brief"]
            deck_names = set(row.get("deck_card_names") or [])
            collected: list = []
            text = swap_narrative.narrate(
                brief, model=model, temperature=temperature, attempts=k,
                deck_card_names=deck_names, collect=collected,
            )
            samples += len(collected)
            for _draft_text, reasons in collected:
                for reason in reasons:
                    rejects[_bucket(reason)] += 1
            if text:
                split = split_of(row["deck"], eval_frac)
                record = {"messages": [
                    {"role": "system", "content": TRAINED_SYSTEM},
                    {"role": "user", "content": swap_narrative._facts_block(brief)},
                    {"role": "assistant", "content": text},
                ]}
                handles[split].write(json.dumps(record, ensure_ascii=False) + "\n")
                kept[split] += 1
            status = "kept" if text else "REJECTED"
            print(f"  [{index}/{len(rows)}] {brief['add']['name']} -> "
                  f"{brief['cut']['name']}: {status} "
                  f"({len(collected)} attempt(s), {int(time.time()-started)}s)", flush=True)
    finally:
        for handle in handles.values():
            handle.close()

    total = kept["train"] + kept["eval"]
    print(f"\nbriefs:      {len(rows)}")
    print(f"samples:     {samples}")
    print(f"kept:        {total}  (train {kept['train']} / eval {kept['eval']})")
    if len(rows):
        print(f"brief yield: {100*total/len(rows):.1f}% of briefs produced a usable row")
    if samples:
        print(f"gate pass:   {100*total/samples:.1f}% of samples survived")
    if rejects:
        print("\nwhat the gate rejected (a sample can fail several checks):")
        for bucket, n in rejects.most_common():
            print(f"    {n:5d}  {bucket}")
    print(f"\nwrote {out / 'train.jsonl'} and {out / 'eval.jsonl'}")
    return 0


def _bucket(reason: str) -> str:
    """Collapse a reason to the CHECK that produced it, so the tally is readable."""
    for needle, label in (
        ("names a card outside", "named a card outside the swap"),
        ("is not in the brief", "cited a number not in the brief"),
        ("which its vector does not show", "claimed a function the vector denies"),
        ("did not measure", "claimed an unmeasured axis"),
        ("overstates", "overstated a marginal gap"),
        ("over-supplies no role", "claimed redundancy on a deck with none"),
        ("measured delta", "contradicted the measured direction"),
        ("outside", "wrong length"),
        ("backend error", "backend error"),
    ):
        if needle in reason:
            return label
    return reason[:60]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--harvest", action="store_true", help="collect briefs (sim-bound)")
    ap.add_argument("--draft", action="store_true", help="draft + gate (LLM-bound)")
    ap.add_argument("--out", type=Path, default=Path("data/reason_sft"))
    ap.add_argument("--decks", type=int, default=60)
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--max-eval", type=int, default=10)
    ap.add_argument("--cut-pool", type=int, default=4)
    ap.add_argument("--model", default="qwen3:32b",
                    help="the TEACHER. 32b, not the 14b runtime default: the gate filters "
                         "quality, so a better teacher raises yield per GPU-hour.")
    ap.add_argument("-k", "--samples", type=int, default=3,
                    help="attempts per brief; the first gated survivor is kept")
    ap.add_argument("--temp", type=float, default=0.6,
                    help="higher than the runtime default on purpose - variety is what makes "
                         "a corpus worth curating, and the gate is what makes it safe")
    ap.add_argument("--eval-frac", type=float, default=0.05)
    ap.add_argument("--axes", default="all", choices=("all", "weakest"),
                    help="'all' targets each of the five axes per deck; 'weakest' does what "
                         "the live route does. ALL is the default for two reasons, and "
                         "volume is the lesser one: targeting only the weakest axis makes a "
                         "corpus dominated by whichever axes are usually weakest, and the "
                         "model has to write about all five.")
    args = ap.parse_args()

    if not (args.harvest or args.draft):
        ap.error("choose --harvest and/or --draft")
    if args.harvest:
        # `None` is "the deck's weakest axis" to `advise`, which is what the live route asks
        # for; the named axes are the coverage sweep.
        axes = list(advisor_axes()) if args.axes == "all" else [None]
        code = harvest(args.out, args.decks, args.runs, args.max_eval, args.cut_pool, axes)
        if code or not args.draft:
            return code
    return draft(args.out, args.model, args.samples, args.temp, args.eval_frac)


if __name__ == "__main__":
    raise SystemExit(main())
