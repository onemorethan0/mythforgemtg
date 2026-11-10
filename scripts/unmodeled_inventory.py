"""Inventory of rules text the goldfish simulator (tier0) never reads -- the unmodeled-mechanics
sweep (docs/DEVELOPMENT_PLAN.md, "Next run").

For every card in the labelled corpus decks, each reminder-stripped rules line is tested ALONE:
a copy of the card carrying only that line goes through `tags.analyze` and tier0's own text
parsers. A line is READ when any field the goldfish spends comes out non-zero, or a tier0 parser
fires (anthems, infect, toxic, infect Auras, tutors). Every other line is UNREAD.

Unread lines are grouped by a SHAPE (the card's own name -> "~", numbers -> "N", mana symbols ->
"{M}") so a family is labelled once, and ranked by how many decks play a card with that shape,
Brackets 1-3 weighted double (the owner's casual pod is the target).

    python scripts/unmodeled_inventory.py --out .cache/unmodeled_inventory.json

NOT CI-SAFE: needs the card store. Read-only; changes nothing.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src", ROOT / "scripts"):
    sys.path.insert(0, str(p))

# EffectVector fields the goldfish (tier0 + the clock's storm/overrun detectors) spends.
READ_FIELDS = ("ramp_sources", "fetches_land", "draw_cards", "engine_draw", "tutor",
               "enters_tapped", "cheats_creatures", "grants_storm", "mana_on_cast",
               "magecraft_damage", "cast_damage", "scaling_burn", "spell_cost_reduction",
               "self_reduction_per_creature", "ritual_mana", "overrun_pump", "overrun_scales")


def shape(line: str, card_name: str) -> str:
    s = line
    for n in sorted({card_name, card_name.split(",")[0], *card_name.split(" // ")}, key=len,
                    reverse=True):
        if n:
            s = s.replace(n.lower(), "~")
    s = re.sub(r"\{[^}]+\}", "{M}", s)
    s = re.sub(r"\b\d+\b", "N", s)
    s = re.sub(r"(\{M\})+", "{M}", s)
    return re.sub(r"\s+", " ", s).strip()


def line_is_read(card, line: str) -> bool:
    from mythgauntlet.semantics import tags
    from mythgauntlet.sim import tier0
    one = dataclasses.replace(card, oracle_text=line)
    fx = tags.analyze(one)
    if any(getattr(fx, f) for f in READ_FIELDS):
        return True
    if tier0._anthems_in_text(line) or tier0._has_own_infect(line) or tier0._toxic_amount(line):
        return True
    tl = card.type_line or ""
    if tier0._infect_aura(tl, line) or (fx.tutor and tier0._tutor_spec(tl, line)):
        return True
    if (tier0._has_own_haste(line) or tier0._token_makers(card.name, tl, line)
            or tier0._effect_makers(card.name, tl, line)):
        return True
    from mythgauntlet.sim import tier0_readers as R0
    n = card.name
    if (R0.var_power(n, tl, line) or R0.enters_counters(n, line) != (0, 0) or R0.sinks(n, line)
            or R0.prowess(n, line) or R0.exalted(n, line) or R0.extort(n, line)
            or R0.convoke(n, line) or R0.cascade(n, line) or R0.token_doubler(n, line)
            or R0.counter_mod(n, line) or R0.gain_drain(n, line) is not None
            or R0.death_drain(n, line) or R0.free_sac_outlet(n, line)
            or R0.is_clone(n, tl, line) or R0.one_shot_mana(n, line)
            or R0.aura_ramp(n, tl, line)[0] or R0.var_draw(n, tl, line)
            or R0.affinity_artifacts(n, line) or R0.flashback_cost(n, tl, line)
            or (R0.lifelink(n, line) and "creature" in tl.lower())
            or R0.team_haste(n, line) or R0.storm(n, line) or R0.pump_spell(n, tl, line)
            or R0.fabricate(n, line) or R0.living_weapon(n, line)
            or R0.combat_counter(n, line)):
        return True
    gear = R0.haste_gear(n, tl, card.oracle_text or "")
    if gear and (line.startswith("equip ") or "haste" in line):
        return True
    # whole-card readers: a line that only matters with the rest of the card
    full = card.oracle_text or ""
    if R0.extra_combat(n, tl, full) and "additional combat phase" in line:
        return True
    if tier0._crew_cost(tl, full) and line.startswith("crew"):
        return True
    if tier0._station_threshold(tl, full) and (line.startswith("station")
                                               or re.match(r"\d+\+ \|", line)):
        return True
    att = tier0._attachment(tl, full)
    if att and (line.startswith(("equip", "enchant creature"))
                or line.startswith(("equipped creature", "enchanted creature"))):
        return True
    return False


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / ".cache" / "unmodeled_inventory.json")
    args = ap.parse_args()

    from bracket_accuracy import labelled_decks

    from mythgauntlet.data.scryfall import load_card_db
    from mythgauntlet.model.deck import Deck, resolve
    from mythgauntlet.sim.tier0 import _rules_lines

    db = load_card_db()
    card_decks: dict[str, set[str]] = defaultdict(set)
    card_weight: dict[str, float] = defaultdict(float)
    cards = {}
    for path, label in labelled_decks():
        r = resolve(Deck.parse_text(path.read_text(encoding="utf-8")), db)
        for c in [c for c, _ in r.cards] + list(r.commanders):
            if c.is_land:
                continue
            if path.name not in card_decks[c.name]:
                card_decks[c.name].add(path.name)
                card_weight[c.name] += 2.0 if label <= 3 else 1.0
            cards[c.name] = c

    shapes: dict[str, dict] = {}
    read_lines = unread_lines = 0
    for name, c in cards.items():
        for line in _rules_lines(c.oracle_text or ""):
            if not line:
                continue
            if line_is_read(c, line):
                read_lines += 1
                continue
            unread_lines += 1
            key = shape(line, name.lower())
            e = shapes.setdefault(key, {"shape": key, "weight": 0.0, "decks": set(),
                                        "cards": [], "example": line})
            e["weight"] += card_weight[name]
            e["decks"] |= card_decks[name]
            if len(e["cards"]) < 8:
                e["cards"].append(name)
    ranked = sorted(shapes.values(), key=lambda e: -e["weight"])
    for e in ranked:
        e["decks"] = len(e["decks"])
        e["weight"] = round(e["weight"], 1)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"cards": len(cards), "read_lines": read_lines,
                                    "unread_lines": unread_lines, "shapes": ranked},
                                   indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(cards)} cards, {read_lines} read lines, {unread_lines} unread, "
          f"{len(ranked)} unread shapes -> {args.out}")
    for e in ranked[:40]:
        print(f"{e['weight']:7.1f} {e['decks']:5d}  {e['shape'][:110]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
