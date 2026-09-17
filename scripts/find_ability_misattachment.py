"""Find CCMs where an effect leaked from one ability into an unrelated one.

Session finding (2026-09-17): Emrakul, the Exigent Doom compiled with its exile-ability's
`add_mana` duplicated onto an unrelated "when you cast this spell" trigger, so every cast
fabricated free mana the card doesn't grant on cast. It passed `cross_check` because that
gate asks "does the CCM have this op *somewhere*, matching an oracle mention *somewhere*" --
document-wide, not per-ability. It does not notice an op sitting on the WRONG ability.

That shape generalizes past `add_mana`. The signal that catches it without re-deriving
oracle-text parsing: the same effect signature (op + amount/colors/counter_type/power/
toughness/count, deliberately excluding `target`/`condition`/`note`, which legitimately
differ between a real ability and a leaked copy of it) showing up in BOTH a `triggered`
ability and an `activated`/`mana_ability` ability of the same card. That combination is
rare enough to be a strong prior (most of a card's abilities are independent), and it is
exactly the shape a stray "{T}: Add ..." or "Equip {cost}"-flavoured clause takes when the
compiler merges it into a trigger instead of keeping it as its own ability.

`attach` and `gain_control` are excluded from the scan: `attach` legitimately double-fires
on real Equipment (an ETB-attach clause AND a separate Equip activated ability both really
do attach), and `gain_control` is a fully DECLINED op (see profile.py) so a duplicate there
can't currently corrupt a simulated game regardless of whether it's a real miscompile.

Of 137 raw candidates the 2026-09-17 session found this way (after those two exclusions),
roughly a third were manually checked against real oracle text: 16 were confirmed bugs and
hand-fixed (see ccm/compiled/*.json `provenance.hand_corrected`), a similar number were
confirmed to be real cards that legitimately do the same kind of thing twice (kept as-is),
and a few were confirmed real bugs but left alone because the op they touch is currently
undispatched by the simulator (lower priority, still worth fixing for corpus honesty).
That adjudication is tracked in ccm_review_state.json next to this script so re-running
only surfaces names nobody has looked at yet.

Usage:
    python scripts/find_ability_misattachment.py                 # list unreviewed candidates
    python scripts/find_ability_misattachment.py --stats          # counts only
    python scripts/find_ability_misattachment.py --mark-legit "Card Name"
    python scripts/find_ability_misattachment.py --mark-deferred "Card Name" --reason "..."
    python scripts/find_ability_misattachment.py --all            # ignore review state entirely
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

from mythgauntlet.model.card import normalize_name
from mythgauntlet.semantics import compiler

STATE_PATH = Path(__file__).with_name("ccm_review_state.json")

# Confirmed fully declined -- a duplicate here cannot corrupt simulation, so it is not
# worth the manual-review budget. `note` is not a real effect at all.
EXCLUDE_OPS = {"attach", "gain_control", "note"}

# The live-dispatched vocabulary (mirrors profile.INTERPRETER_EXECUTABLE_OPS) -- a
# duplicate on an op outside this set can't move a simulated game either way today,
# but is still flagged (lower down the list) since it's still corpus-quality garbage
# and may matter the day that op gets a dispatch branch.
EXECUTABLE_OPS = {
    "add_counter", "add_mana", "attach", "create_token", "deal_damage", "destroy",
    "discard", "draw", "exile", "extra_turn", "gain_life", "grant_ability",
    "look_and_select", "lose_life", "mill", "proliferate", "pump", "return_to_hand",
    "sacrifice", "scry", "search_library", "surveil", "tap", "untap",
}

SIG_KEYS = ("op", "amount", "colors", "counter_type", "power", "toughness", "count")


def _normv(v):
    return tuple(v) if isinstance(v, list) else v


def _sig(effect: dict) -> tuple | None:
    op = effect.get("op")
    if op is None or op in EXCLUDE_OPS:
        return None
    return tuple((k, _normv(effect.get(k))) for k in SIG_KEYS if k in effect)


def find_candidates() -> list[dict]:
    """One entry per (card, effect signature) duplicated across a triggered ability and
    an activated/mana_ability ability. Includes oracle text so a reviewer never has to
    open the file just to triage."""
    candidates = []
    for path in sorted(compiler.compiled_dir().glob("*.json")):
        try:
            envelope = compiler.read_envelope(path)
        except ValueError:
            continue
        abilities = envelope.get("ccm", {}).get("abilities", []) or []
        sigmap: dict[tuple, list[str]] = collections.defaultdict(list)
        for ab in abilities:
            kind = ab.get("kind")
            for eff in ab.get("effects", []) or []:
                if not isinstance(eff, dict):
                    continue
                sig = _sig(eff)
                if sig is None:
                    continue
                sigmap[sig].append(kind)
        for sig, kinds in sigmap.items():
            if "triggered" not in kinds:
                continue
            if "activated" not in kinds and "mana_ability" not in kinds:
                continue
            op = sig[0][1]
            candidates.append({
                "name": envelope["card"]["name"],
                "file": path.name,
                "op": op,
                "signature": sig,
                "live": op in EXECUTABLE_OPS,
                "oracle_text": envelope["card"].get("oracle_text", ""),
            })
    return candidates


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(
        json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stats", action="store_true", help="print counts only")
    parser.add_argument("--all", action="store_true", help="ignore review state, list everything")
    parser.add_argument("--mark-legit", metavar="NAME", help="record NAME as reviewed, not a bug")
    parser.add_argument("--mark-fixed", metavar="NAME", help="record NAME as reviewed, fixed")
    parser.add_argument("--mark-deferred", metavar="NAME", help="record NAME as reviewed, real bug, deferred")
    parser.add_argument("--reason", default="", help="note for --mark-deferred")
    parser.add_argument("--limit", type=int, default=30, help="max unreviewed candidates to print")
    args = parser.parse_args()

    state = load_state()

    if args.mark_legit or args.mark_fixed or args.mark_deferred:
        name = args.mark_legit or args.mark_fixed or args.mark_deferred
        key = normalize_name(name)
        if args.mark_legit:
            state[key] = {"name": name, "status": "legit"}
        elif args.mark_fixed:
            state[key] = {"name": name, "status": "fixed"}
        else:
            state[key] = {"name": name, "status": "deferred", "reason": args.reason}
        save_state(state)
        print(f"recorded {key!r} as {state[key]['status']}")
        return 0

    candidates = find_candidates()
    unreviewed = [c for c in candidates if args.all or normalize_name(c["name"]) not in state]
    # live-dispatched ops first -- those are the ones that can actually corrupt a game today
    unreviewed.sort(key=lambda c: (not c["live"], c["name"]))

    if args.stats:
        by_status = collections.Counter(state[normalize_name(c["name"])]["status"] for c in candidates if normalize_name(c["name"]) in state)
        print(f"total candidates: {len(candidates)}")
        print(f"reviewed:         {len(candidates) - len(unreviewed)}  {dict(by_status)}")
        print(f"unreviewed:       {len(unreviewed)}")
        return 0

    for c in unreviewed[: args.limit]:
        tag = "LIVE" if c["live"] else "inert"
        print(f"\n=== {c['name']} [{c['op']}, {tag}] ({c['file']}) ===")
        print(c["oracle_text"])
    if len(unreviewed) > args.limit:
        print(f"\n... and {len(unreviewed) - args.limit} more (--limit to see more, --stats for counts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
