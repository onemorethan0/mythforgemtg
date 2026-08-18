"""Score candidate `voltron_combat` pattern sets against a HAND-LABELLED gold set.

The 879-card model audit is a candidate list, not ground truth — and only its "no" side had
been checked. This is a 28-card sample drawn from BOTH sides (fixed seed 11), labelled by hand
from oracle text before scoring anything.

The question each label answers: **is COMBAT this card's PLAN** — does it pay you for attacking
or for dealing combat damage, or grant the evasion that makes attacking the route to winning?
A creature that merely HAS trample on its own body is not a trample deck; that is the rule
`collection_pool` already states and `THEME_PATTERNS` violates.

    python scripts/voltron_gold.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("MYTHFORGE_EDHREC_LIFT", "off")
import commander_analysis as ca

# True = combat IS the plan. Hand-labelled; agreement with the model was 24/28 (86%), and every
# disagreement is noted because a marginal card is exactly where a pattern set gets decided.
GOLD = {
    # --- combat is the plan ---
    "Reyav, Master Smith": True,             # grants double strike to the equipped attacker
    "Arni Metalbrow": True,                  # attack trigger cheats creatures in attacking
    "Oroku Saki, Shredder Rising": True,     # combat-damage trigger
    "Ojer Kaslem, Deepest Growth": True,     # combat-damage trigger
    "Kevin, Questing Dragon": True,          # combat-damage trigger
    "Trostani, Three Whispers": True,        # repeatable granting of combat keywords
    "The Fearsome Flock": True,              # combat-damage trigger
    "Kutzil, Malamet Exemplar": True,        # combat-damage trigger
    "Ghired, Conclave Exile": True,          # attack trigger (populate)
    "The Herald of Numot": True,             # combat-damage trigger
    "A-Raiyuu, Storm's Edge": True,          # attacks-alone payoff + extra combat
    "Ezio Auditore da Firenze": True,        # combat-damage trigger + freerunning
    "Akiri, Line-Slinger": True,             # MODEL SAID NO — a textbook equipment-voltron
    "Rhonas the Indomitable": True,          # MODEL SAID NO — pumps and grants trample to attack
    # --- combat is NOT the plan ---
    "Spider-Man, Hometown Hero": False,      # MODEL SAID YES — one-shot unblockable on a 2-power
    "Stegron the Dinosaur Man": False,       # MODEL SAID YES — menace body + a discard pump
    "Ascendant Evincar": False,              # flying body + anthem
    "Razaketh, the Foulblooded": False,      # tutor engine; trample is incidental
    "Zalto, Fire Giant Duke": False,         # dungeon venture
    "Horde of Notions": False,               # Elemental recursion
    "Sami, Wildcat Captain": False,          # affinity/artifacts
    "Sab-Sunen, Luxa Embodied": False,       # counters
    "The Warring Triad": False,              # graveyard
    "Vela the Night-Clad": False,            # drain-on-death; evasion is a means, not the plan
    "June, Bounty Hunter": False,            # clues/draw
    "Maha, Its Feathers Night": False,       # opponent toughness hoser
    "Black Panther, Wakandan King": False,   # counters on lands
    "Gosta Dirk": False,                     # a rules footnote about islandwalk
}

BARE = {"first strike", "double strike", "trample", "unblockable", "can't be blocked"}

# The list as it stood BEFORE the fix, pinned. Deriving it from the live module made all three
# rows identical the moment the fix landed, which quietly turned the comparison into a no-op.
ORIGINAL = ["first strike", "double strike", "trample", "unblockable",
            "can't be blocked", "whenever a creature attacks",
            "whenever a creature you control attacks", "attacking causes",
            "deals combat damage to a player", "additional combat phase",
            "whenever one or more creatures you control attack"]
LIVE = list(ca.THEME_PATTERNS["voltron_combat"])
KEPT = [p for p in ORIGINAL if p not in BARE]
GRANTED = [f"{v} {kw}"
           for kw in ("trample", "first strike", "double strike", "flying", "menace")
           for v in ("gains", "gain", "have", "with")]


def main() -> int:
    cards = {c["name"]: c for c in
             json.loads((ROOT / "data" / "cards_slim.json").read_text(encoding="utf-8"))["cards"]}
    # Gold names come from the audit, which used front-face names; resolve either way.
    resolved = {}
    for name in GOLD:
        c = cards.get(name) or next(
            (v for k, v in cards.items() if k.split(" // ")[0] == name), None)
        if c is None:
            print(f"  !! not in pool: {name}")
            continue
        resolved[name] = c

    def score(pats, label):
        tp = fp = tn = fn = 0
        for name, want in GOLD.items():
            c = resolved.get(name)
            if c is None:
                continue
            o = ca._oracle_without_self_name(c)
            pred = any(p in o for p in pats)
            tp += pred and want
            fp += pred and not want
            tn += (not pred) and (not want)
            fn += (not pred) and want
        acc = (tp + tn) / max(1, tp + fp + tn + fn)
        prec = tp / max(1, tp + fp)
        rec = tp / max(1, tp + fn)
        print(f"{label:<30}{acc*100:>8.0f}%{prec*100:>11.0f}%{rec*100:>9.0f}%"
              f"{fp:>7}{fn:>7}")
        return acc

    print(f"gold set: {sum(GOLD.values())} combat-plan, "
          f"{len(GOLD)-sum(GOLD.values())} not\n")
    print(f"{'pattern set':<30}{'accuracy':>9}{'precision':>11}{'recall':>9}"
          f"{'FP':>7}{'FN':>7}")
    print("-" * 73)
    score(ORIGINAL, "original (bare keywords)")
    score(KEPT, "drop bare keywords")
    score(KEPT + GRANTED, "drop bare + require grant")
    score(LIVE, "LIVE (what ships today)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
