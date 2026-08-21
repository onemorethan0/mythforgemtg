"""Build a supervised fine-tuning set for swap explanations, by rejection sampling.

The CCM corpus works because it is VERIFIED training data: every document passed the same
gates the engine trusts at run time, so ~30k card->CCM pairs exist with no human annotation
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
    python scripts/build_reason_sft.py --draft --out data/reason_sft -k 3
    python scripts/build_reason_sft.py --bench --out data/reason_sft   # is training needed?
    E:\\ccm-train\\.venv\\Scripts\\python.exe scripts/train_ccm_lora.py \\
        --data data/reason_sft --out E:\\ccm-train\\qwen3-8b-reasons

WHAT --bench FOUND, AND IT ARGUES AGAINST TRAINING THE RUNTIME MODEL. Over 44 briefs, k=3:

    arm                brief yield   gate pass   s/brief
    qwen3:32b/full           90.9%       63.5%       3.8
    qwen3:14b/full           93.2%       71.9%       1.4      <- the runtime, as it ships
    qwen3:8b/full            75.0%       43.4%       1.1
    qwen3:14b/short          81.8%       52.9%       1.5
    qwen3:8b/short           81.8%       52.9%       0.9

Three things fall out. **The 14b runtime already beats the 32b teacher**, so a fine-tune has
no quality gap to close on the path a user actually hits. **The rule preamble is worth ~19
points of gate pass** on 14b (71.9 -> 52.9), which is precisely the job a fine-tune would
have. And **dropping the preamble saves no measurable time** (1.4s vs 1.5s per brief) - so
the throughput argument, which was the only argument left, is not supported.

The case that survives is narrower and worth stating: **8b/full is 43.4%**, so if the runtime
ever has to drop to 8b for VRAM, a fine-tune that lifts 8b toward 14b is the way to do it.
That is what this corpus is for. Until then it earns its keep as the gate's regression set.

NOT CI-SAFE: --harvest needs data/cards_slim.json and a semantics store; --draft needs
llama-swap on :8010. The candidate pool is the user's own collection (contract C1), because
that is what the live /advise route actually feeds the advisor — so a corpus rebuilt on
another machine will differ, and that is a property of the input, not a bug here.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import io
import json
import os
import sys
import time
from pathlib import Path


def _ensure_utf8_stdout() -> None:
    """Console output must not be able to kill a seven-hour harvest.

    Windows hands this process a cp1252 stdout, and Magic prints card names it cannot encode -
    AEther Vial, Lim-Dul the Necromancer, Jotun Grunt, Marton Stromgald. This script prints
    the add and cut of every brief, so one such card mid-sweep raises UnicodeEncodeError and
    loses the whole run. `--help` was already failing on a single arrow in the docstring.

    Same wrapper `image_gen` and `model3d` install, for the same reason; `errors="replace"` so
    output degrades to a `?` rather than ever raising.
    """
    for attr in ("stdout", "stderr"):
        stream = getattr(sys, attr, None)
        if stream is None or not hasattr(stream, "buffer"):
            continue
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if encoding != "utf8" or getattr(stream, "errors", "") != "replace":
            setattr(sys, attr,
                    io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"))


_ensure_utf8_stdout()

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


# ── bench: is the fine-tune worth doing at all? ──────────────────────────────────

def bench(out: Path, arms: list, k: int, temperature: float, limit: int) -> int:
    """Run the same briefs through several (model, prompt) arms and report the gate.

    THIS IS THE DECISION, not a diagnostic. Three arms answer it:

      32b / full    the TEACHER. Upper bound on what rejection sampling can harvest.
      14b / full    the RUNTIME as it ships today. If this is already good, the interactive
                    path needs no model work at all.
      14b / short   the runtime served the TERSE prompt - i.e. what a fine-tuned model would
                    be given, minus the training. The gap between this and 14b/full is the
                    job the fine-tune has to do, and if there is no gap there is no job.

    Latency is reported too, because the honest argument for training was always throughput
    rather than quality: the full prompt is ~1,900 characters of rules on every request.
    """
    briefs_path = out / BRIEFS_FILE
    if not briefs_path.exists():
        print(f"No {briefs_path}. Run --harvest first.")
        return 1
    rows = json.loads(briefs_path.read_text(encoding="utf-8"))[:limit]
    print(f"{len(rows)} briefs x {len(arms)} arms, {k} attempts each\n", flush=True)

    results = []
    for model, prompt in arms:
        system = TRAINED_SYSTEM if prompt == "short" else None
        kept = samples = 0
        rejects: collections.Counter[str] = collections.Counter()
        started = time.time()
        for index, row in enumerate(rows, 1):
            collected: list = []
            text = swap_narrative.narrate(
                row["brief"], model=model, temperature=temperature, attempts=k,
                deck_card_names=set(row.get("deck_card_names") or []),
                collect=collected, system=system,
            )
            samples += len(collected)
            kept += text is not None
            for _text, reasons in collected:
                for reason in reasons:
                    rejects[_bucket(reason)] += 1
            if index % 10 == 0:
                print(f"    {model}/{prompt}: {index}/{len(rows)} "
                      f"({int(time.time()-started)}s)", flush=True)
        elapsed = time.time() - started
        results.append({
            "arm": f"{model}/{prompt}",
            "yield": 100 * kept / len(rows) if rows else 0.0,
            "pass": 100 * kept / samples if samples else 0.0,
            "secs_per_brief": elapsed / len(rows) if rows else 0.0,
            "rejects": rejects,
        })
        print(f"  {model}/{prompt}: kept {kept}/{len(rows)} "
              f"({elapsed/max(1,len(rows)):.1f}s per brief)\n", flush=True)

    print(f"{'arm':<20}{'brief yield':>13}{'gate pass':>11}{'s/brief':>10}")
    for r in results:
        print(f"{r['arm']:<20}{r['yield']:>12.1f}%{r['pass']:>10.1f}%{r['secs_per_brief']:>10.1f}")
    print("\ntop rejection per arm:")
    for r in results:
        top = r["rejects"].most_common(2)
        detail = "; ".join(f"{label} x{n}" for label, n in top) or "none"
        print(f"  {r['arm']:<20} {detail}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--harvest", action="store_true", help="collect briefs (sim-bound)")
    ap.add_argument("--draft", action="store_true", help="draft + gate (LLM-bound)")
    ap.add_argument("--out", type=Path, default=Path("data/reason_sft"))
    ap.add_argument("--decks", type=int, default=60)
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--max-eval", type=int, default=10)
    ap.add_argument("--cut-pool", type=int, default=4)
    ap.add_argument("--model", default="qwen3:14b",
                    help="the TEACHER. 14b, and that was measured rather than assumed - see "
                         "--bench. A bigger model writes more elaborately, which on a "
                         "constrained phrasing task is more chances to over-claim, not "
                         "fewer: 32b scored WORSE than 14b through the gate and took 2.7x "
                         "as long.")
    ap.add_argument("-k", "--samples", type=int, default=3,
                    help="attempts per brief; the first gated survivor is kept")
    ap.add_argument("--temp", type=float, default=0.6,
                    help="higher than the runtime default on purpose - variety is what makes "
                         "a corpus worth curating, and the gate is what makes it safe")
    ap.add_argument("--eval-frac", type=float, default=0.05)
    ap.add_argument("--bench", action="store_true",
                    help="A/B the gate across (model, prompt) arms - see bench()")
    ap.add_argument("--arms", default="qwen3:32b/full,qwen3:14b/full,qwen3:14b/short",
                    help="comma-separated model/prompt pairs; prompt is 'full' or 'short'")
    ap.add_argument("--limit", type=int, default=25, help="briefs per arm for --bench")
    ap.add_argument("--axes", default="all", choices=("all", "weakest"),
                    help="'all' targets each of the five axes per deck; 'weakest' does what "
                         "the live route does. ALL is the default for two reasons, and "
                         "volume is the lesser one: targeting only the weakest axis makes a "
                         "corpus dominated by whichever axes are usually weakest, and the "
                         "model has to write about all five.")
    args = ap.parse_args()

    if not (args.harvest or args.draft or args.bench):
        ap.error("choose --harvest, --draft and/or --bench")
    if args.bench:
        arms = []
        for spec in args.arms.split(","):
            model, _, prompt = spec.strip().partition("/")
            arms.append((model, prompt or "full"))
        return bench(args.out, arms, args.samples, args.temp, args.limit)
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
