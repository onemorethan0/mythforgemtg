"""One-off backfill: populate attach's new grant_power/grant_toughness/grant_keywords
fields on already-accepted CCMs, deterministically, with no LLM call.

docs/PLAN_FIDELITY.md Phase C (2026-09-09): `attach` never dispatched an equipped/enchanted
creature's actual bonus, because the bonus lived only in a free-text `note` on a paired
static ability. `semantics.compiler.parse_attach_grant`/`_populate_attach_grants` read the
FIXED, unconditional subset of that note deterministically (a plain P/T delta and/or a
closed set of boolean keyword grants) and already run automatically on every NEW compile
(`compile_card`) -- this script applies the exact same function retroactively to the store's
existing ~31k compiled CCMs, so cards compiled before this shipped don't have to wait for a
prompt-version bump + nightly recompile to get the new field. Rewrites a file only when the
parser actually found something to add; every other file is left byte-identical.

Usage: python scripts/backfill_attach_grants.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mythgauntlet.semantics import compiler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report counts, write nothing")
    args = parser.parse_args()

    changed_cards: list[str] = []
    for path in sorted(compiler.compiled_dir().glob("*.json")):
        try:
            envelope = compiler.read_envelope(path)
        except ValueError as exc:
            print(f"skip {path.name}: {exc}")
            continue
        doc = envelope.get("ccm")
        if not isinstance(doc, dict):
            continue
        before = json.dumps(doc, sort_keys=True)
        compiler._populate_attach_grants(doc)
        if json.dumps(doc, sort_keys=True) == before:
            continue
        changed_cards.append(str(envelope.get("card", {}).get("name") or path.stem))
        if not args.dry_run:
            tmp = path.with_suffix(".json.part")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(envelope, fh, indent=2, ensure_ascii=False)
            tmp.replace(path)

    verb = "would update" if args.dry_run else "updated"
    print(f"{verb} {len(changed_cards)} cards")
    for name in changed_cards[:20]:
        print(" ", name)
    if len(changed_cards) > 20:
        print(f"  ... and {len(changed_cards) - 20} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
