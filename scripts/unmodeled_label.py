"""Label unread rules-text shapes (scripts/unmodeled_inventory.py) into mechanic FAMILIES with a
local model on llama-swap. Closed question, fixed family list, batches of 4; the model never
writes rules code. A gold set is scored first and the sweep refuses to run under GOLD_MIN.

    python scripts/unmodeled_label.py --gold            # score the model on the gold set only
    python scripts/unmodeled_label.py --top 2000        # label (resumable cache)

NOT CI-SAFE: needs llama-swap on :8010.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
INV = ROOT / ".cache" / os.environ.get("UNMODELED_INV", "unmodeled_inventory.json")
CACHE = ROOT / ".cache" / os.environ.get("UNMODELED_CACHE", "unmodeled_labels.jsonl")
URL = os.environ.get("UNMODELED_URL", "http://127.0.0.1:8010/v1/chat/completions")
MODEL = os.environ.get("UNMODELED_MODEL", "qwen3:14b")
BATCH = 4
GOLD_MIN = 0.85

FAMILIES = {
    "evasion": "flying, menace, trample, reach, shadow, can't be blocked, other blocking/evasion rules",
    "haste": "the creature has or gains haste",
    "combat_keyword": "first strike, double strike, deathtouch, lifelink, vigilance",
    "protection": "indestructible, hexproof, shroud, ward, protection, regenerate",
    "equipment": "equip costs and 'equipped creature gets/has ...'",
    "aura_buff": "'enchant creature' and 'enchanted creature gets/has ...' on your own creature",
    "vehicle": "crew N and vehicles becoming creatures",
    "station": "station, spacecraft/planet charge-counter thresholds ('N+ | ...')",
    "counters": "+1/+1 counters put on creatures, proliferate, counters that grow creatures",
    "tokens": "creates creature tokens (any trigger or spell)",
    "noncreature_tokens": "creates Treasure, Clue, Food, Blood or other noncreature tokens",
    "drain": "opponents lose life or are dealt damage (not via a creature's combat damage)",
    "lifegain": "you gain life",
    "removal": "destroy/exile/bounce/damage/fight a creature or permanent, -N/-N to a creature",
    "counterspell": "counter target spell or ability",
    "wipe": "destroy/exile/damage all creatures or permanents",
    "recursion": "return cards from a graveyard, reanimate, flashback, escape, mill yourself",
    "alt_cost": "free or alternative costs, cost reduction, convoke, kicker, affinity, overload",
    "extra_land": "play additional lands, put lands onto the battlefield",
    "mana": "adds mana (mana abilities, rituals), untap lands",
    "card_advantage": "draw, scry, look at top, impulse/exile-to-play, no maximum hand size",
    "pump_temp": "creatures get +N/+N until end of turn",
    "anthem": "static +N/+N to your creatures",
    "sacrifice": "sacrifice outlets and payoffs (whenever a creature dies, sacrifice a ...)",
    "copy": "copy a spell or permanent, clones",
    "extra_turn_combat": "extra turns or additional combat phases",
    "stax": "doesn't untap, can't cast/attack, taxes, symmetrical locks",
    "structure": "modal headers (choose one), partner, cycling, flash, split/adventure, level up, "
                 "changeling, can't be countered, other card-structure keywords",
    "other": "none of the above",
}

GOLD = {
    "flying": "evasion", "haste": "haste", "equip {M}": "equipment", "crew N": "vehicle",
    "equipped creature gets +N/+N.": "equipment", "flash": "structure",
    "counter target spell.": "counterspell", "trample": "evasion",
    "create a N/N white soldier creature token.": "tokens",
    "create a treasure token.": "noncreature_tokens",
    "each opponent loses N life.": "drain", "you gain N life.": "lifegain",
    "destroy all creatures.": "wipe", "exile target creature. its controller gains life equal to "
    "its power.": "removal", "you may play an additional land on each of your turns.": "extra_land",
    "enchant creature": "aura_buff", "enchanted creature gets +N/+N.": "aura_buff",
    "put a +N/+N counter on target creature.": "counters", "proliferate.": "counters",
    "creatures you control get +N/+N until end of turn.": "pump_temp",
    "double strike": "combat_keyword", "indestructible": "protection",
    "return target creature card from your graveyard to the battlefield.": "recursion",
    "convoke": "alt_cost", "{t}: add {M}.": "mana", "draw a card.": "card_advantage",
    "whenever another creature you control dies, each opponent loses N life.": "drain",
    "take an extra turn after this one.": "extra_turn_combat",
    "this artifact doesn't untap during your untap step.": "stax",
    "choose one —": "structure",
    "station": "station", "N+ | flying": "station",
    "whenever a creature you control dies, create a N/N black zombie creature token.": "tokens",
    "copy target instant or sorcery spell.": "copy", "sacrifice a creature: scry N.": "sacrifice",
    "creatures you control get +N/+N.": "anthem", "deathtouch": "combat_keyword",
    "ward {M}": "protection", "menace": "evasion",
}


def _prompt(shapes: list[str]) -> list[dict]:
    fam = "\n".join(f"- {k}: {v}" for k, v in FAMILIES.items())
    items = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(shapes))
    return [
        {"role": "system", "content": "You classify Magic: The Gathering rules text. '~' is the "
                                      "card's own name, N a number, {M} a mana or tap symbol."},
        {"role": "user", "content": f"Families:\n{fam}\n\nFor each numbered rules line, give the ONE "
                                    f"family that best describes what it does. Answer with a JSON "
                                    f"array of {len(shapes)} family keys in order, nothing else.\n\n"
                                    f"{items}\n/no_think"},
    ]


def label(shapes: list[str]) -> list[str]:
    for _attempt in range(3):
        r = requests.post(URL, json={"model": MODEL, "messages": _prompt(shapes),
                                     "temperature": 0.1, "max_tokens": 200,
                                     "chat_template_kwargs": {"enable_thinking": False},
                                     # Ollama (node 2) ignores the kwarg and /no_think
                                     "reasoning_effort": "none"},
                          timeout=600)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\[.*\]", text, re.S)
        try:
            out = json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            out = None
        if isinstance(out, list) and len(out) == len(shapes):
            return [x if x in FAMILIES else "other" for x in map(str, out)]
    return ["other"] * len(shapes)


def gold() -> float:
    keys = list(GOLD)
    got = []
    for i in range(0, len(keys), BATCH):
        got += label(keys[i:i + BATCH])
    hits = 0
    for k, g in zip(keys, got):
        ok = g == GOLD[k]
        hits += ok
        if not ok:
            print(f"  MISS {k!r}: model {g}, gold {GOLD[k]}")
    score = hits / len(keys)
    print(f"gold {hits}/{len(keys)} = {score:.2f}")
    return score


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", action="store_true")
    ap.add_argument("--top", type=int, default=2000)
    ap.add_argument("--start", type=int, default=0, help="slice start, to split a sweep across nodes")
    args = ap.parse_args()
    if gold() < GOLD_MIN:
        print("gold set below threshold; not sweeping")
        return 1
    if args.gold:
        return 0
    shapes = json.loads(INV.read_text(encoding="utf-8"))["shapes"][args.start:args.top]
    done = {}
    if CACHE.exists():
        for ln in CACHE.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                row = json.loads(ln)
                done[row["shape"]] = row["family"]
    todo = [e for e in shapes if e["shape"] not in done]
    t0 = time.time()
    with CACHE.open("a", encoding="utf-8") as fh:
        for i in range(0, len(todo), BATCH):
            chunk = todo[i:i + BATCH]
            for e, fam in zip(chunk, label([e["shape"] for e in chunk])):
                done[e["shape"]] = fam
                fh.write(json.dumps({"shape": e["shape"], "family": fam}, ensure_ascii=False) + "\n")
            fh.flush()
            if (i // BATCH) % 50 == 0:
                print(f"  {i + len(chunk)}/{len(todo)} ({time.time() - t0:.0f}s)", flush=True)
    weight = Counter()
    for e in shapes:
        weight[done[e["shape"]]] += e["weight"]
    tot = sum(weight.values())
    for fam, w in weight.most_common():
        print(f"{fam:20} {w / tot:6.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
