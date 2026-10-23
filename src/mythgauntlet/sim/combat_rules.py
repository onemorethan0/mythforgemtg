"""Combat-damage rules a COMMANDER imposes on its controller's attackers (toughness matters).

tier0 summed printed power, so the whole "toughness matters" class was simulated as the deck it
is NOT: a Doran, Besieged by Time list whose attackers hit for 129 read as 54, and the panel
called it a deck with no finisher (found 2026-10-23). This module turns a command zone's ORACLE
TEXT into one `CombatRule`, which tier0 applies only on turns the commander is on the
battlefield.

Only unconditional STATIC rules are modelled, each pinned by `tests/engine/test_combat_rules.py`
to the verbatim text it reads:

    damage = toughness           Doran, the Siege Tower; Felothar; Rasaad; Baldin (on your turn)
    toughness where t > p        Ghalta the Immovable
    defenders only               Arcades, the Strategist
    +|p - t| when attacking      Doran, Besieged by Time (+ creature spells with t > p cost {1} less)

Declined, as an honest under-count: a rule behind a payment or an activation (The Kingpin of
Crime's "you may pay 2 life", Plagon's "{W/U}: target creature ... this turn"), and the same
rules printed in the 99 (High Alert, Belligerent Brontodon) - tier0 does not track which
noncommander permanents are on the battlefield.

Defender (CR 702.3b) applies with or without a rule: a creature with defender cannot attack
unless something says it can. tier0 used to swing with it.

tier2 (duels) seeds a creature's power from `SimCard.attack_power` at materialisation and is NOT
covered here: there the rule must also follow the commander on and off the battlefield and apply
to blocks. Analyze, the advisor, card impact and the mentor all read tier0.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from mythgauntlet.model.card import Card

POWER, TOUGHNESS, TOUGHNESS_IF_GREATER, GAP_PUMP = "power", "toughness", "toughness_if_greater", "gap_pump"

_ASSIGNS_RE = re.compile(
    r"\beach creature(?P<yours> you control)?(?P<defender> with defender)?"
    r"(?P<greater> with toughness greater than its power)?"
    r" assigns combat damage equal to its toughness rather than its power",
    re.IGNORECASE,
)
_DEFENDERS_ATTACK_RE = re.compile(r"can attack as though (?:it|they) didn't have defender", re.IGNORECASE)
_GAP_PUMP_RE = re.compile(
    r"^whenever a creature you control attacks(?: or blocks)?, it gets \+x/\+x until end of turn, "
    r"where x is the difference between its power and toughness", re.IGNORECASE)
_DISCOUNT_RE = re.compile(
    r"^each creature spell you cast with toughness greater than its power costs \{1\} less", re.IGNORECASE)
# A sentence carrying any of these is conditional, temporary or activated - not a static rule.
_NOT_STATIC_RE = re.compile(r"until end of turn|this turn|\bif you do\b|\byou may\b|^\{|^.{0,40}:\s", re.IGNORECASE)


@dataclass(frozen=True)
class CombatRule:
    damage: str = POWER
    defenders_only: bool = False
    defenders_attack: bool = False
    discount_toughness_over_power: int = 0

    def attack_power(self, card: Card) -> int:
        return attack_power(card, self)

    def creature_discount(self, card: Card) -> int:
        if not self.discount_toughness_over_power or not card.is_creature:
            return 0
        p, t = _stat(card.power), _stat(card.toughness)
        return self.discount_toughness_over_power if t > p else 0


def _stat(v) -> int:
    try:
        return max(0, int(v or 0))
    except ValueError:
        return 0  # '*' and friends count 0 at rung 1, as in tier0


def attack_power(card: Card, rule: CombatRule | None) -> int:
    """Damage `card` deals attacking an empty board, under `rule` (None = printed power)."""
    keywords = card.keywords or ()
    defender = "defender" in keywords
    if defender and not (rule and rule.defenders_attack):
        return 0
    p, t = _stat(card.power), _stat(card.toughness)
    dmg = p
    if rule is not None and (defender or not rule.defenders_only):
        if rule.damage == TOUGHNESS:
            dmg = t
        elif rule.damage == TOUGHNESS_IF_GREATER:
            dmg = t if t > p else p
        elif rule.damage == GAP_PUMP:
            dmg = p + abs(p - t)
    return dmg * 2 if "double strike" in keywords else dmg


def from_commanders(commanders: list[Card | None]) -> CombatRule | None:
    """The combined rule printed on the command zone, or None when nothing applies."""
    damage, defenders_only, defenders_attack, discount = POWER, False, False, 0
    for cmd in commanders:
        if cmd is None:
            continue
        for line in (cmd.oracle_text or "").splitlines():
            for sentence in re.split(r"(?<=\.)\s+", line.strip()):
                s = sentence.strip()
                if not s:
                    continue
                if _GAP_PUMP_RE.search(s):
                    damage = GAP_PUMP
                    continue
                if _DISCOUNT_RE.search(s):
                    discount = 1
                    continue
                if _NOT_STATIC_RE.search(s):
                    continue
                m = _ASSIGNS_RE.search(s)
                if m:
                    damage = TOUGHNESS_IF_GREATER if m.group("greater") else TOUGHNESS
                    defenders_only = bool(m.group("defender"))
                if _DEFENDERS_ATTACK_RE.search(s):
                    defenders_attack = True
    if damage == POWER and not defenders_attack and not discount:
        return None
    return CombatRule(damage, defenders_only, defenders_attack, discount)
