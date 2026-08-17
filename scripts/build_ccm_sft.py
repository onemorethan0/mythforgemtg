"""Turn the compiled CCM store into a supervised fine-tuning set.

The store is not just training data, it is *verified* training data: every document in
`ccm/compiled/` passed all three gates, so the labels were produced and checked by the
same validator the engine trusts at run time. That makes this a rejection-sampled corpus
of ~31k card -> CCM pairs with no human annotation anywhere in the loop.

Three filters run over it, and each one is a correctness requirement rather than a
tidiness preference:

1. **Re-validate against TODAY's gates.** A document was accepted under the prompt and
   gates of its day; 1,118 of them predate prompt v10's trigger-event check. Training on
   a CCM that would fail now teaches exactly the wrong thing, so the gates are re-run
   with the live card facts and failures are dropped. This is the same reasoning
   `compiler.stored_ccm_passes_gates` applies on the read path.
2. **Require the target to be grammar-emittable.** The compiler constrains decoding with
   `ccm_grammar.CCM_GRAMMAR`. A target the grammar forbids could never be produced at
   inference, so training on it wastes capacity and teaches a format the sampler will
   block. `violations()` is the check.
3. **Strip the compiler's own keys.** `rung`, `provenance` and `unsupported_ops` are
   written by `compile_card` AFTER the model responds. Leaving them in the target trains
   the model to author them — which is how 1,897 cards came to self-declare rung 3, the
   tier reserved for hand-authored exemplars.

The prompt shape deliberately DROPS the 14 few-shot exemplars that `build_messages`
sends: teaching the format is what the fine-tune is for. That is the bulk of the
inference win — the current call spends roughly 5,100 prompt tokens, ~3,500 of which are
exemplars.

Usage:
    python scripts/build_ccm_sft.py --out data/ccm_sft
    python scripts/build_ccm_sft.py --out data/ccm_sft --system short   # faster to train
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mythgauntlet.model.card import normalize_name  # noqa: E402
from mythgauntlet.semantics import ccm, compiler  # noqa: E402
from mythgauntlet.semantics.ccm_grammar import violations  # noqa: E402

# Keys compile_card writes after the fact — never part of what the model should emit.
COMPILER_KEYS = ("rung", "provenance", "unsupported_ops")

SHORT_SYSTEM = (
    "You are a compiler that converts Magic: The Gathering Oracle text into a JSON Card "
    "Capability Model (CCM). Output ONLY one JSON object. No prose, no markdown fences."
)


def split_of(name: str, eval_frac: float) -> str:
    """Deterministic per-card split, so re-running never leaks a card across the boundary.

    Hashing the NAME (not the index) means the split survives the store growing: a card
    compiled next month lands in the same side it would have landed in today, so an eval
    score stays comparable across dataset rebuilds.
    """
    digest = hashlib.sha256(normalize_name(name).encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
    return "eval" if bucket < eval_frac else "train"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, type=Path, help="output directory")
    ap.add_argument("--eval-frac", type=float, default=0.02)
    ap.add_argument("--system", choices=("full", "short"), default="full",
                    help="'full' keeps compiler.SYSTEM_PROMPT so the tuned model stays "
                         "steerable by prompt revisions and drops into the existing "
                         "compiler unchanged; 'short' trains ~4x faster per epoch.")
    args = ap.parse_args()

    system = compiler.SYSTEM_PROMPT if args.system == "full" else SHORT_SYSTEM

    files = sorted(compiler.compiled_dir().glob("*.json"))
    if not files:
        print(f"no compiled CCMs under {compiler.compiled_dir()} — set MYTHGAUNTLET_STORE",
              file=sys.stderr)
        return 1

    # The gates read Scryfall facts the envelope does not carry (produced_mana above all),
    # so re-validation needs the live card store, not a Card rebuilt from the envelope.
    from mythgauntlet.cli import _load_db
    db = _load_db()
    by_name = {normalize_name(c.name): c for c in db._by_name.values()}

    dropped: collections.Counter[str] = collections.Counter()
    gate_detail: collections.Counter[str] = collections.Counter()
    kept = {"train": 0, "eval": 0}
    args.out.mkdir(parents=True, exist_ok=True)
    handles = {s: open(args.out / f"{s}.jsonl", "w", encoding="utf-8") for s in kept}

    try:
        for path in files:
            try:
                envelope = compiler.read_envelope(path)
            except ValueError:
                dropped["unreadable envelope"] += 1
                continue

            name = envelope["card"]["name"]
            card = by_name.get(normalize_name(name))
            if card is None:
                # Not in the current universe (renamed, or a card the bulk no longer
                # lists). Its CCM cannot be re-validated, so it cannot be trusted.
                dropped["card not in current store"] += 1
                continue

            doc = {k: v for k, v in envelope["ccm"].items() if k not in COMPILER_KEYS}

            gates = ccm.validate(doc, card)
            failing = [g for g, msgs in gates.items() if msgs]
            if failing:
                dropped["fails today's gates"] += 1
                for gate in failing:
                    gate_detail[gate] += 1
                continue

            bad = violations(doc)
            if bad:
                dropped["not grammar-emittable"] += 1
                continue

            split = split_of(name, args.eval_frac)
            record = {"messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": compiler.card_block(card)},
                {"role": "assistant", "content": json.dumps(doc, ensure_ascii=False)},
            ]}
            handles[split].write(json.dumps(record, ensure_ascii=False) + "\n")
            kept[split] += 1
    finally:
        for fh in handles.values():
            fh.close()

    total = len(files)
    print(f"compiled store:        {total}")
    print(f"kept  train:           {kept['train']}")
    print(f"kept  eval:            {kept['eval']}")
    print(f"dropped:               {sum(dropped.values())}")
    for reason, n in dropped.most_common():
        print(f"    {n:6d}  {reason}")
    if gate_detail:
        print("  gate failures among the re-validated drops "
              "(a card can fail more than one):")
        for gate, n in gate_detail.most_common():
            print(f"    {n:6d}  {gate}")
    print(f"\nwrote {args.out / 'train.jsonl'} and {args.out / 'eval.jsonl'} "
          f"(system prompt: {args.system})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
