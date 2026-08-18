import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import theme_shortlist
import client as offload

GOLD = {
    "Baral, Chief of Compliance":   "spellslinger",
    "Baba Lysaga, Night Witch":     "aristocrats",
    "Agent of the Iron Throne":     "aristocrats",
    "Alibou, Ancient Witness":      "artifacts",
    "Arcades, the Strategist":      None,      # defenders — not in the vocabulary
    "Belbe, Corrupted Observer":    None,
    "Athreos, Shroud-Veiled":       "aristocrats",
    "Arixmethes, Slumbering Isle":  None,
}
src = json.load(open(r"C:\Users\rvn92\Documents\mtg_deck_builder\docs\data\zero_theme_commanders.json", encoding="utf-8"))
by = {c["name"]: c for c in src}
model = sys.argv[1] if len(sys.argv) > 1 else "qwen3:14b"

ok = 0
t0 = time.time()
for name, want in GOLD.items():
    card = by[name]
    sl = theme_shortlist.shortlist(card)
    got = offload.choose(card, sl, model=model)
    hit = got == want
    ok += hit
    print(f"{'PASS' if hit else 'FAIL'}  {name[:30]:<32} want={str(want):<14} got={str(got):<14} "
          f"shortlist={sl}")
print(f"\n{model}: {ok}/{len(GOLD)} exact   ({time.time()-t0:.0f}s)")
