"""Which of a card's rules lines the goldfish (tier0 + the clock's storm/overrun detectors) reads.

One definition, shared by the unmodeled-mechanics inventory (scripts/unmodeled_inventory.py) and
the cut ranking (ratings/cut_ranking.py): a card's MEASURED goldfish value may only be used to
call it weak when the goldfish reads everything it does. A card with an unread line -- removal,
protection, an engine nobody models yet -- would read as dead weight for the wrong reason
(2026-11-10: Toxic Deluge, Darksteel Plate and Door of Destinies all "slowed" the Borg deck's kill).
"""

from __future__ import annotations

import dataclasses
import re

from mythgauntlet.model.card import Card

# EffectVector fields the goldfish spends.
READ_FIELDS = ("ramp_sources", "fetches_land", "draw_cards", "engine_draw", "tutor",
               "enters_tapped", "cheats_creatures", "grants_storm", "mana_on_cast",
               "magecraft_damage", "cast_damage", "scaling_burn", "spell_cost_reduction",
               "self_reduction_per_creature", "ritual_mana", "overrun_pump", "overrun_scales")
# EffectVector fields that mean "this card acts against an opponent": never goldfish-legible.
INTERACTION_FIELDS = ("removal", "board_wipe", "counterspell", "noncreature_removal")


def line_is_read(card: Card, line: str) -> bool:
    """Does some goldfish reader act on this single rules line of `card`?"""
    from mythgauntlet.semantics import tags
    from mythgauntlet.sim import tier0
    from mythgauntlet.sim import tier0_readers as R0
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
            or R0.combat_counter(n, line) or R0.typed_anthems(n, line)
            or R0.creature_mana(n, line) or R0.replicate_grant(n, line)):
        return True
    full = card.oracle_text or ""
    gear = R0.haste_gear(n, tl, full)
    if gear and (line.startswith("equip ") or "haste" in line):
        return True
    # whole-card readers: a line that only matters with the rest of the card
    if R0.charge_engine(n, full) and ("charge counter" in line):
        return True
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


_REMINDER = re.compile(r"\([^)]*\)")


def ability_lines(card: Card) -> list[str]:
    """Lower-cased rules lines that are not bare keyword lines ("flying, haste", "ward {2}")."""
    kws = {k.lower() for k in card.keywords or ()}
    out = []
    for raw in _REMINDER.sub("", card.oracle_text or "").splitlines():
        line = raw.strip().lower()
        if not line:
            continue
        parts = [p.strip() for p in re.split(r"[,;]", line.rstrip(".")) if p.strip()]
        if parts and all(any(p == k or p.startswith(k + " ") for k in kws) for p in parts):
            continue
        out.append(line)
    return out


def fully_read(card: Card) -> bool:
    """Does the goldfish read everything this card does? A body with only keywords is read
    (its power is what it does here); interaction never is (no opponent to aim it at)."""
    from mythgauntlet.semantics import tags
    fx = tags.analyze(card)
    if any(getattr(fx, f) for f in INTERACTION_FIELDS):
        return False
    return all(line_is_read(card, ln) for ln in ability_lines(card))
