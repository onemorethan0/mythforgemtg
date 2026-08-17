"""QLoRA fine-tune of a small model on the compiled CCM corpus.

Why a SMALL model and not the biggest one that fits: this is a narrow, closed,
temperature-0 extraction task with ~30k verified in-domain examples, and it runs as a
sweep over the whole 32k-card universe. Throughput is the binding constraint, not
breadth of world knowledge. A 30B dense model at Q4 on a 3090 runs roughly half the
tokens/sec of an 8B and would push a full compile sweep into multiple days.

What it is expected to buy, measured against the ledger's own numbers for qwen3:14b:

    first-attempt pass   86.1%   (27,546 of 31,982)
    pass after 1 retry   97.0%
    never compiled        3.0%   (956 cards)

Every card that needs a second attempt costs a full extra inference, so 13.9% of the
sweep's GPU time is spent on retries. The fine-tune targets that directly, and the 956
permanent failures are the real prize — they are holes in the corpus, and the engine
under-counts every deck that plays one.

This is the half of the problem grammar-constrained decoding CANNOT reach. The grammar
makes malformed output impossible; it cannot make the model know that `search_library`
takes a `count`, or that "whenever another creature dies" is `creature_dies` and not
`death`. Those are the 80 missing-required-param and 558 cross_check errors, and they
are learned from data.

Prerequisites (see docs/engine/CARD_SEMANTICS.md):
    E:\\ccm-train\\.venv  with torch+cu126, unsloth, trl, peft, bitsandbytes
    python scripts/build_ccm_sft.py --out <data> --system short

Usage:
    E:\\ccm-train\\.venv\\Scripts\\python.exe scripts/train_ccm_lora.py \\
        --data C:\\Users\\rvn92\\Documents\\mythgauntlet\\sft_short \\
        --out  E:\\ccm-train\\qwen3-8b-ccm
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# Unsloth patches transformers/trl on import and warns loudly if it is not first.
from unsloth import FastLanguageModel, is_bfloat16_supported  # noqa: I001
from unsloth.chat_templates import train_on_responses_only
from datasets import Dataset
from trl import SFTConfig, SFTTrainer

# Pre-quantized 4-bit base: ~6 GB to fetch instead of ~16 GB of bf16 safetensors, and it
# is the exact quantization QLoRA trains against, so nothing is quantized twice.
DEFAULT_BASE = "unsloth/Qwen3-8B-unsloth-bnb-4bit"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True, type=Path,
                    help="directory holding train.jsonl / eval.jsonl")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--base", default=DEFAULT_BASE)
    # p99.9 of the short-prompt set is ~535 tokens and the longest card ~1,805, so 2048
    # truncates nothing. Raise to 3584 for a --system full dataset (p99.9 ~2,119).
    ap.add_argument("--max-seq", type=int, default=2048)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--rank", type=int, default=32,
                    help="LoRA rank. 32 (not 16) because this rewrites an output FORMAT "
                         "across ~30k examples rather than nudging a style.")
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--accum", type=int, default=8)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--gguf", default="q8_0",
                    help="GGUF quantization to export, or 'none' to skip. q8_0 (~8.5 GB) "
                         "is deliberate: the compile path is precision-sensitive and the "
                         "3090 has the headroom.")
    ap.add_argument("--resume", action="store_true",
                    help="Resume from the newest checkpoint in --out (after a crash).")
    ap.add_argument("--max-steps", type=int, default=0,
                    help="Stop after N optimizer steps instead of --epochs. For a smoke "
                         "test of the whole pipeline (load -> pack -> mask -> step -> "
                         "save) before committing hours of GPU to it.")
    args = ap.parse_args()

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base,
        max_seq_length=args.max_seq,
        load_in_4bit=True,
        dtype=None,  # auto: bf16 on Ampere
    )

    model = FastLanguageModel.get_peft_model(
        model,
        r=args.rank,
        lora_alpha=args.rank,
        lora_dropout=0.0,
        bias="none",
        # Every linear projection, including the MLP. A format rewrite touches how the
        # model composes tokens, not just what it attends to.
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth",
        random_state=20260811,
    )

    # Built in plain Python rather than load_dataset(...).map(...) on purpose.
    # `Dataset.map` fingerprints the mapping function with `dill`, and on Python 3.14
    # dill's pickler still uses the pre-3.14 `_batch_setitems(self, items)` signature —
    # CPython added a third argument, so any .map() dies with
    #   TypeError: Pickler._batch_setitems() takes 2 positional arguments but 3 were given
    # 30k short records cost nothing to materialize, so the caching machinery buys us
    # nothing here and only adds a version-fragile dependency.
    def load_split(path: Path):
        rows = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                messages = json.loads(line)["messages"]
                rows.append({"text": tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=False)})
        return Dataset.from_list(rows)

    ds = {"train": load_split(args.data / "train.jsonl")}
    eval_path = args.data / "eval.jsonl"
    if eval_path.exists():
        ds["eval"] = load_split(eval_path)
    print(f"train={len(ds['train'])}  eval={len(ds.get('eval', []))}")

    cfg = SFTConfig(
        output_dir=str(args.out),
        per_device_train_batch_size=args.batch,
        gradient_accumulation_steps=args.accum,
        max_steps=args.max_steps if args.max_steps else -1,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        warmup_ratio=0.03,
        lr_scheduler_type="cosine",
        logging_steps=25,
        optim="adamw_8bit",
        weight_decay=0.01,
        seed=20260811,
        bf16=is_bfloat16_supported(),
        fp16=not is_bfloat16_supported(),
        max_seq_length=args.max_seq,
        dataset_text_field="text",
        # Packing concatenates short examples into full-length sequences. The median
        # record is ~213 tokens against a 2,048 window, so without it roughly 90% of
        # every forward pass would be padding.
        packing=True,
        report_to="none",
        # Checkpoint every ~40 minutes rather than every ~3-hour epoch. This box took 14
        # unexpected shutdowns in the 30 days to 2026-08-11 (see the crash notes in
        # docs/), so an epoch-granularity checkpoint means a crash at hour 2:55 costs the
        # whole epoch. keep 3 to bound disk - each adapter checkpoint is small, but the
        # optimizer state is not.
        save_strategy="steps",
        save_steps=50,
        save_total_limit=3,
        eval_strategy="epoch" if "eval" in ds else "no",
        per_device_eval_batch_size=args.batch,
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=ds["train"],
        eval_dataset=ds.get("eval"),
        args=cfg,
    )

    # Loss on the ASSISTANT turn only. Without this the model spends most of its gradient
    # learning to reproduce the card block it was given, which it already receives at
    # inference — the only thing worth learning here is the CCM.
    trainer = train_on_responses_only(
        trainer,
        instruction_part="<|im_start|>user\n",
        response_part="<|im_start|>assistant\n",
    )

    # `--resume` picks up the newest checkpoint in --out. Pass it after a crash; the
    # optimizer state, LR schedule and step count all restore, so the run continues
    # rather than restarting.
    resume = args.resume and any(args.out.glob("checkpoint-*"))
    if args.resume and not resume:
        print(f"--resume given but no checkpoint-* under {args.out}; starting fresh")
    stats = trainer.train(resume_from_checkpoint=resume or None)
    print(json.dumps(stats.metrics, indent=1, default=str))

    args.out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(args.out / "adapter"))
    tokenizer.save_pretrained(str(args.out / "adapter"))
    print(f"adapter -> {args.out / 'adapter'}")

    if args.gguf.lower() != "none":
        # Merges the adapter into the base and converts, so llama.cpp loads one file and
        # llama-swap needs only a new model entry.
        model.save_pretrained_gguf(str(args.out / "gguf"), tokenizer,
                                   quantization_method=args.gguf)
        print(f"gguf ({args.gguf}) -> {args.out / 'gguf'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
