"""Adjudicate family labels where two sweeps disagree (scripts/unmodeled_label.py run with two
models), with a third, larger model; writes the final labels and the family weight table.

    python scripts/unmodeled_adjudicate.py --a unmodeled_labels_14b.jsonl --b unmodeled_labels.jsonl

NOT CI-SAFE: needs llama-swap on :8010.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str) -> dict[str, str]:
    out = {}
    for ln in (ROOT / ".cache" / name).read_text(encoding="utf-8").splitlines():
        if ln.strip():
            row = json.loads(ln)
            out[row["shape"]] = row["family"]
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="unmodeled_labels_14b.jsonl")
    ap.add_argument("--b", default="unmodeled_labels.jsonl")
    ap.add_argument("--judge", default="qwen3:32b")
    ap.add_argument("--out", default="unmodeled_labels_final.json")
    args = ap.parse_args()
    os.environ["UNMODELED_MODEL"] = args.judge
    import unmodeled_label as ul
    ul.MODEL = args.judge
    a, b = _load(args.a), _load(args.b)
    shapes = [s for s in a if s in b]
    final = {s: a[s] for s in shapes if a[s] == b[s]}
    split = [s for s in shapes if a[s] != b[s]]
    print(f"{len(shapes)} shapes, agree {len(final)}, adjudicating {len(split)} with {args.judge}")
    for i in range(0, len(split), ul.BATCH):
        chunk = split[i:i + ul.BATCH]
        for s, fam in zip(chunk, ul.label(chunk)):
            final[s] = fam
    inv = {e["shape"]: e for e in json.loads(
        (ROOT / ".cache" / "unmodeled_inventory.json").read_text(encoding="utf-8"))["shapes"]}
    weight = Counter()
    for s, fam in final.items():
        weight[fam] += inv[s]["weight"] if s in inv else 0
    tot = sum(weight.values()) or 1
    table = {fam: round(w / tot, 4) for fam, w in weight.most_common()}
    (ROOT / ".cache" / args.out).write_text(json.dumps({"labels": final, "weight_share": table},
                                                       indent=1, ensure_ascii=False),
                                            encoding="utf-8")
    for fam, share in table.items():
        print(f"{fam:20} {share:6.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
