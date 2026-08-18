"""False-positive audit of the most over-firing theme.

Every sweep so far asked "what is this card's theme". This asks the opposite and more
dangerous question: **of the cards a theme ALREADY claims, how many does it not deserve?**

`voltron_combat` is the case to audit. `theme_match` scores it STRONG on 19.35% of every card
in Magic — the documented base-rate trap — and `THEME_PATTERNS` detects it on more legends
than any theme except `counters`. A false positive there is not cosmetic: the commander's ~20
theme slots get spent on a plan the deck cannot execute.

One narrow yes/no per card, definition supplied, `/no_think`. Same discipline as the other
sweeps: a gold set first, and the model's answer is a CANDIDATE for human review, never a
direct edit.

    python scripts/offload/audit_voltron.py 32b
"""
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

MODELS = {"32b": "qwen3:32b", "14b": "qwen3:14b"}
THEME = "voltron_combat"

QUESTION = """A Magic commander is called a "{theme}" commander when COMBAT is the deck's PLAN:
one creature suited up and swinging, or attacking/combat damage being the payoff the card pays
you for, or granted evasion as the route to winning.

It is NOT a {theme} commander when the card merely HAS a combat keyword (flying, trample, first
strike) on its own body, or mentions attacking only in passing while its real payoff is
something else.

Card:
{name} — {type_line}
{oracle}

Is COMBAT this card's PLAN? Answer exactly one word: yes or no."""


def ask(card, model):
    prompt = QUESTION.format(theme=THEME, name=card["name"],
                             type_line=card.get("type_line") or "",
                             oracle=card.get("oracle_text") or "")
    out = offload.chat(prompt + offload.NO_THINK, model=model, max_tokens=200).strip().casefold()
    if not out:
        raise offload.EmptyReply(card["name"])
    # Last yes/no token wins; a reply that restates the question ends on its answer.
    yes, no = out.rfind("yes"), out.rfind("no")
    if yes < 0 and no < 0:
        raise offload.EmptyReply(f"off-menu: {out[:60]!r}")
    return yes > no


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "32b"
    model = MODELS[tag]
    cards = json.load(open("data/cards_slim.json", encoding="utf-8"))["cards"]
    claimed = [c for c in cards
               if "Legendary" in (c.get("type_line") or "")
               and "Creature" in (c.get("type_line") or "")
               and THEME in ca._detect_themes(c)]
    path = ROOT / "docs" / "data" / f"audit_{THEME}_{tag}.json"
    done = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    todo = [c for c in claimed if c["name"] not in done]
    print(f"{model}: {THEME} is claimed on {len(claimed)} legends · {len(todo)} to audit",
          flush=True)

    t0 = time.time()
    for i, card in enumerate(todo, 1):
        try:
            done[card["name"]] = ask(card, model)
        except Exception as e:                  # noqa: BLE001 — one bad card must not end it
            done[card["name"]] = f"ERROR:{type(e).__name__}"
        if i % 50 == 0 or i == len(todo):
            path.write_text(json.dumps(done, indent=1), encoding="utf-8")
            r = i / max(time.time() - t0, 1e-9)
            print(f"  {i}/{len(todo)}  {r*60:.0f}/min  eta {(len(todo)-i)/max(r,1e-9)/60:.0f}m",
                  flush=True)
    path.write_text(json.dumps(done, indent=1), encoding="utf-8")
    bad = [n for n, v in done.items() if v is False]
    print(f"\nclaimed {len(done)} · model says NOT combat-plan on {len(bad)} "
          f"({100*len(bad)/max(1,len(done)):.0f}%)", flush=True)
    for n in bad[:25]:
        print("   ", n)


if __name__ == "__main__":
    main()
