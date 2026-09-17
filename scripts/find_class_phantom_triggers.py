"""Find "Class" enchantments with a free duplicate of a paid level-up effect.

Session finding (2026-09-17): Cleric Class and Wizard Class both compiled a real paid
level-up ability correctly (e.g. `{2}{U}: Level 2` -> an `activated` ability whose effects
draw two cards) AND a second, separate `triggered` ability with `trigger.event: "other"`
carrying an IDENTICAL copy of the same effects -- a phantom free version of the level-up
with no cost. Root cause read from the two real cases: a Class's rules text prints
"When this Class becomes level N, <effect>" as its OWN clause, textually separate from the
"{cost}: Level N" line above it -- but for many Classes the "becomes level N" clause's
effect and the paid activation's effect ARE the same thing (Wizard Class: "{2}{U}: Level 2"
followed by "When this Class becomes level 2, draw two cards" -- two ways of printing one
fact), and the compiler emitted both a correct activated ability AND a second triggered
ability for the "becomes level N" clause, without recognizing they describe the same event.

`event: "other"` is not in sim/tier2._EVENT_TRIGGERS, so today this duplication is INERT --
it can't currently double a level-up's effect in a simulated game. It is still corpus
garbage (and would stop being harmless the moment "class level-up" ever became a real,
dispatched trigger event), so it is worth a cheap, cheap-to-apply fix: drop the phantom
triggered ability, keep the activated one.

This is deliberately a NARROWER, more specific detector than
find_ability_misattachment.py's general activated+triggered signature scan -- restricted
to cards whose type_line contains "Class", and to an EXACT effects-list match (not just a
shared op signature), so it should have a much lower false-positive rate. Only two cards
were confirmed and fixed this session (both hand_corrected already); this script exists so
a future pass can check the rest of the Class cycle without re-deriving the pattern.

Usage:
    python scripts/find_class_phantom_triggers.py
    python scripts/find_class_phantom_triggers.py --apply   # drop confirmed phantom triggers
"""

from __future__ import annotations

import argparse
import json

from mythgauntlet.semantics import compiler


def _effects_key(effects: list) -> str:
    return json.dumps(effects, sort_keys=True)


def find_candidates() -> list[dict]:
    hits = []
    for path in sorted(compiler.compiled_dir().glob("*.json")):
        try:
            envelope = compiler.read_envelope(path)
        except ValueError:
            continue
        if "class" not in (envelope["card"].get("type_line") or "").lower():
            continue
        abilities = envelope.get("ccm", {}).get("abilities", []) or []
        activated_effects = {
            _effects_key(ab["effects"])
            for ab in abilities
            if ab.get("kind") == "activated" and ab.get("effects")
        }
        for i, ab in enumerate(abilities):
            if ab.get("kind") != "triggered":
                continue
            if ab.get("trigger", {}).get("event") != "other":
                continue
            key = _effects_key(ab.get("effects") or [])
            if key in activated_effects:
                hits.append({
                    "name": envelope["card"]["name"],
                    "file": path.name,
                    "path": path,
                    "ability_index": i,
                    "oracle_text": envelope["card"].get("oracle_text", ""),
                })
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="drop the phantom triggered ability from each match")
    args = parser.parse_args()

    hits = find_candidates()
    print(f"{len(hits)} phantom-trigger candidate(s)")
    for h in hits:
        print(f"\n=== {h['name']} ({h['file']}, ability index {h['ability_index']}) ===")
        print(h["oracle_text"])
        if args.apply:
            envelope = compiler.read_envelope(h["path"])
            abilities = envelope["ccm"]["abilities"]
            del abilities[h["ability_index"]]
            envelope["ccm"].setdefault("provenance", {})["hand_corrected"] = True
            tmp = h["path"].with_suffix(".json.part")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(envelope, fh, indent=2, ensure_ascii=False)
            tmp.replace(h["path"])
            print("  -> dropped phantom triggered ability")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
