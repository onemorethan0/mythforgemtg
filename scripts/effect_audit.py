"""Audit: which stored effects change the OPPONENT although their own target says they should not?

Two real sim defects (a blink executing as removal, 'exile this'/'exile the top cards of your library'
killing the opponent's best creature) had one shape: an effect aimed at the caster's own side, the
source itself, or a non-battlefield zone, executed against the opponent. This runs EVERY stored
effect through the real executor on a fixed synthetic board and reports the ones that alter the
opponent while their target says they concern something else.

    PYTHONPATH=src python scripts/effect_audit.py [--examples 4]

"Should not touch the opponent" = the target says `self`, controller `you`, `who: you`, or a
non-battlefield zone. Findings are a worklist: read the examples before changing the executor.
"""
from __future__ import annotations

import argparse
import collections
import copy
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mythgauntlet.semantics.interpreter import interpret_ability  # noqa: E402
from mythgauntlet.semantics.store import SemanticsStore  # noqa: E402
from mythgauntlet.sim.tier2 import _apply_resolved, _Permanent, _Player  # noqa: E402

OFF = {"graveyard", "hand", "library", "exile", "stack", "command"}


def _dummy_card():
    return SimpleNamespace(profile=SimpleNamespace(impact=1.0), card=SimpleNamespace(is_land=False),
                           sim=SimpleNamespace(attack_power=2))


def _board(prefix: str, n: int) -> list:
    return [_Permanent(name=f"{prefix}{i}", power=2 + i, toughness=2 + i, is_creature=True,
                       sick=False, source=_dummy_card()) for i in range(n)]


def _fresh():
    me = _Player(name="me", library=[_dummy_card() for _ in range(15)],
                 hand=[_dummy_card() for _ in range(4)], battlefield=_board("m", 2))
    opp = _Player(name="opp", library=[_dummy_card() for _ in range(15)],
                  hand=[_dummy_card() for _ in range(4)], battlefield=_board("o", 3))
    return me, opp


def _snap(p) -> tuple:
    return (p.life, len(p.battlefield), tuple((c.power, c.toughness, c.tapped, c.counters) for c in p.battlefield),
            len(p.hand), len(p.library))


def _says_not_opponent(effect: dict) -> str | None:
    t = effect.get("target") if isinstance(effect.get("target"), dict) else {}
    if t.get("self"):
        return "self"
    if t.get("controller") == "you":
        return "controller=you"
    if effect.get("who") == "you" or t.get("who") == "you":
        return "who=you"
    if t.get("zone") in OFF:
        return f"zone={t.get('zone')}"
    return None


def _says_opponent(effect: dict) -> str | None:
    t = effect.get("target") if isinstance(effect.get("target"), dict) else {}
    if effect.get("who") in ("opponent", "each_opponent", "target_player"):
        return f"who={effect.get('who')}"
    if t.get("type") in ("player", "opponent") and t.get("controller") in ("opponent", "each_opponent"):
        return "target=opponent player"
    return None


def _mine_better(before: tuple, after: tuple) -> bool:
    """My life, board size, hand or library moved in my favour (life up, more permanents/cards)."""
    return after[0] > before[0] or after[1] > before[1] or after[3] > before[3]


def mirror(args) -> int:
    """Effects that say OPPONENT but improve the CASTER's life, board or hand."""
    store = SemanticsStore()
    found: collections.Counter = collections.Counter()
    ex: dict = collections.defaultdict(list)
    total = 0
    for name, sem in store._by_name.items():
        ccm = sem.ccm
        if not ccm:
            continue
        for ab in ccm.get("abilities") or []:
            for effect in ab.get("effects") or []:
                if not isinstance(effect, dict) or effect.get("op") in ("deal_damage", "lose_life"):
                    continue
                why = _says_opponent(effect)
                if why is None:
                    continue
                total += 1
                try:
                    resolved = interpret_ability({"kind": ab.get("kind"), "effects": [copy.deepcopy(effect)]})
                    me, opp = _fresh()
                    before = _snap(me)
                    for r in resolved:
                        _apply_resolved(r, me, opp, None, ())
                    better = _mine_better(before, _snap(me))
                except Exception:  # noqa: BLE001
                    continue
                if better:
                    key = (effect.get("op"), why)
                    found[key] += 1
                    if len(ex[key]) < args.examples:
                        ex[key].append(ccm.get("name", name))
    print(f"effects whose who/target says OPPONENT (non-damage): {total}")
    print(f"that nevertheless improve the CASTER's life / board / hand: {sum(found.values())}")
    for key, n in found.most_common():
        print(f"  {n:5d}  {key[0]:<16} {key[1]:<24} e.g. {ex[key]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", type=int, default=4)
    ap.add_argument("--mirror", action="store_true",
                    help="the other direction: opponent-aimed effects that improve the CASTER")
    args = ap.parse_args()
    if args.mirror:
        return mirror(args)
    store = SemanticsStore()
    found: collections.Counter = collections.Counter()
    ex: dict = collections.defaultdict(list)
    errors: collections.Counter = collections.Counter()
    total = 0
    for name, sem in store._by_name.items():
        ccm = sem.ccm
        if not ccm:
            continue
        for ab in ccm.get("abilities") or []:
            for effect in ab.get("effects") or []:
                if not isinstance(effect, dict):
                    continue
                why = _says_not_opponent(effect)
                if why is None:
                    continue
                total += 1
                try:
                    resolved = interpret_ability({"kind": ab.get("kind"), "effects": [copy.deepcopy(effect)]})
                    me, opp = _fresh()
                    before = _snap(opp)
                    for r in resolved:
                        _apply_resolved(r, me, opp, None, ())
                    changed = _snap(opp) != before
                except Exception as exc:  # noqa: BLE001 - the audit must survive a bad effect
                    errors[type(exc).__name__] += 1
                    continue
                if changed:
                    key = (effect.get("op"), why)
                    found[key] += 1
                    if len(ex[key]) < args.examples:
                        ex[key].append(ccm.get("name", name))
    print(f"effects whose target says self / own side / off-battlefield: {total}")
    print(f"that nevertheless CHANGE the opponent's state: {sum(found.values())}")
    for key, n in found.most_common():
        print(f"  {n:5d}  {key[0]:<16} {key[1]:<18} e.g. {ex[key]}")
    if errors:
        print(f"(executor errors on synthetic state, skipped: {dict(errors)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
