"""Ensemble sweep over EVERY themeless legendary creature, not just the corpus slice.

The corpus sweep covered 80 commanders and yielded 4 pattern-widening candidates. This runs
the same harness over all ~960 themeless legends in `data/cards_slim.json`, because a pattern
gap that shows up once in the corpus may show up thirty times across the whole card pool —
and it is the SIZE of a cluster that decides whether a pattern is worth landing.

Two passes, never interleaved (llama-swap keeps one model resident). Resumable: results are
written incrementally, so a killed run continues where it stopped.

    python scripts/offload/sweep_all_legends.py 32b     # proposer  (slow, strong on labels)
    python scripts/offload/sweep_all_legends.py 14b     # confirmer (fast, strong on "none")
    python scripts/offload/sweep_all_legends.py report  # agreement + candidate clusters
"""
import collections
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("MYTHFORGE_EDHREC_LIFT", "off")

import client as offload
import commander_analysis as ca
import theme_shortlist

OUT = ROOT / "docs" / "data"
MODELS = {"32b": "qwen3:32b", "14b": "qwen3:14b"}


def targets():
    """Themeless legends that have at least one plausible candidate.

    A card with an EMPTY shortlist needs no model call — nothing in the 43-theme vocabulary
    is even a candidate, which is already the answer and makes it a new-archetype case.
    """
    cards = json.load(open("data/cards_slim.json", encoding="utf-8"))["cards"]
    out = []
    for c in cards:
        tl = c.get("type_line") or ""
        if "Legendary" not in tl or "Creature" not in tl:
            continue
        if ca._detect_themes(c):
            continue
        sl = theme_shortlist.shortlist(c)
        if sl:
            out.append((c, sl))
    return out


def run(tag: str):
    model = MODELS[tag]
    path = OUT / f"legend_sweep_{tag}.json"
    done = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    todo = [(c, sl) for c, sl in targets() if c["name"] not in done]
    print(f"{model}: {len(done)} already done, {len(todo)} to go", flush=True)

    t0 = time.time()
    for i, (card, sl) in enumerate(todo, 1):
        try:
            done[card["name"]] = offload.choose(card, sl, model=model) or "none"
        except Exception as e:                      # noqa: BLE001 — a bad card must not end the sweep
            done[card["name"]] = f"ERROR:{type(e).__name__}"
        if i % 25 == 0 or i == len(todo):
            path.write_text(json.dumps(done, indent=1), encoding="utf-8")
            rate = i / max(time.time() - t0, 1e-9)
            print(f"  {i}/{len(todo)}  {rate*60:.1f}/min  "
                  f"eta {(len(todo)-i)/max(rate,1e-9)/60:.0f}m", flush=True)
    path.write_text(json.dumps(done, indent=1), encoding="utf-8")
    print(f"wrote {path.name} ({len(done)})", flush=True)


def report():
    big = json.loads((OUT / "legend_sweep_32b.json").read_text(encoding="utf-8"))
    small_path = OUT / "legend_sweep_14b.json"
    small = json.loads(small_path.read_text(encoding="utf-8")) if small_path.exists() else {}
    shared = [n for n in big if n in small]
    agree = [n for n in shared if big[n] == small[n]]
    themed = [n for n in agree if big[n] != "none"]
    print(f"scored by 32b {len(big)} · by both {len(shared)} · agreed {len(agree)} "
          f"({100*len(agree)/max(1,len(shared)):.0f}%) · agreed on a THEME {len(themed)}\n")

    by_theme = collections.Counter(big[n] for n in themed)
    print("clusters both models agree on (these size the pattern work):")
    for theme, n in by_theme.most_common():
        print(f"  {n:>4}  {theme}")
        for name in [x for x in themed if big[x] == theme][:6]:
            print(f"        {name}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "report"
    (report if arg == "report" else lambda: run(arg))()
