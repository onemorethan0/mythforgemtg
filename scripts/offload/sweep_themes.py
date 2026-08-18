"""Two-model ensemble over the zero-theme commanders. Agreement is trusted; disagreement queues.

Measured on an 8-card gold set: qwen3:14b is 4/4 when the right answer is "no theme fits" and
1/4 at assigning a label; qwen3:32b is the mirror — 4/4 on positives, but it over-labels two of
the four none-cases even against explicit negative wording. They fail in OPPOSITE directions,
so their agreement is high-precision (3/3 correct on gold) and their disagreement is exactly
the set worth a human read.
"""
import json, sys, time
sys.path.insert(0, str(Path(__file__).resolve().parent))
import theme_shortlist
import client as offload
from pathlib import Path

SRC = Path(r"C:\Users\rvn92\Documents\mtg_deck_builder\docs\data\zero_theme_commanders.json")
OUT = Path(r"C:\Users\rvn92\Documents\mtg_deck_builder\docs\data\zero_theme_triage.json")

cards = json.loads(SRC.read_text(encoding="utf-8"))

# ONE MODEL PER PASS. llama-swap keeps a single model resident, so alternating 32b/14b per
# card forced a full unload+reload EVERY item — the interleaved version did not finish 80
# cards in ten minutes. Two passes cost two model loads instead of a hundred and sixty.
shortlists = {c["name"]: theme_shortlist.shortlist(c) for c in cards}
by_name = {c["name"]: c for c in cards}


def pass_over(model: str) -> dict[str, str]:
    got, t0 = {}, time.time()
    todo = [n for n, sl in shortlists.items() if sl]
    for i, name in enumerate(todo, 1):
        try:
            got[name] = offload.choose(by_name[name], shortlists[name], model=model) or "none"
        except Exception as e:
            got[name] = f"ERROR:{type(e).__name__}"
        if i % 20 == 0:
            print(f"  {model} {i}/{len(todo)}  ({time.time()-t0:.0f}s)", flush=True)
    print(f"  {model} done in {time.time()-t0:.0f}s", flush=True)
    return got


t0 = time.time()
big_all = pass_over("qwen3:32b")
small_all = pass_over("qwen3:14b")

rows = []
for c in cards:
    n = c["name"]; sl = shortlists[n]
    rec = {"name": n, "shortlist": sl,
           "type_line": c.get("type_line"), "oracle_text": c.get("oracle_text")}
    if not sl:
        # No candidate at all, so no model call: nothing in the 43-theme vocabulary is even
        # plausible. That IS the answer, and it makes this a NEW-archetype case.
        rec.update(big="none", small="none", agree=True, verdict="none")
    else:
        b, s = big_all.get(n, "none"), small_all.get(n, "none")
        rec.update(big=b, small=s, agree=(b == s), verdict=(b if b == s else None))
    rows.append(rec)

OUT.write_text(json.dumps(rows, indent=2), encoding="utf-8")
agree = [r for r in rows if r["agree"]]
themed = [r for r in agree if r["verdict"] != "none"]
print()
print(f"{len(rows)} swept in {time.time()-t0:.0f}s")
print(f"  agreed           : {len(agree)} ({100*len(agree)/len(rows):.0f}%)")
print(f"  agreed on a THEME: {len(themed)}")
print(f"  agreed on none   : {len(agree)-len(themed)}")
print(f"  disagreed (queue): {len(rows)-len(agree)}")
print(f"wrote {OUT.name}")
