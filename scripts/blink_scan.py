"""Size the 'blink' mislabelling in the compiled CCM store (deterministic, no GPU, no writes).

A blink/flicker card says "exile <thing>, then return it to the battlefield". The compiler has
no dedicated op and scatters these across `exile`, `return_to_hand`, `gain_control`, `reanimate`
and invented names. Because the sim EXECUTES `exile` and `return_to_hand`, a flicker of your own
creature can run as a removal of it.

    PYTHONPATH=src python scripts/blink_scan.py [--examples 8] [--names-out worklist.txt]

Reports, over cards whose oracle text carries the blink signature:
  * how many, and the op-combination they were compiled to (top rows);
  * how many contain an op the sim executes destructively against its own side
    (`exile`, `return_to_hand`, `gain_control`, `sacrifice`) with controller `you` or `any`;
  * `--names-out` writes the cards for `mythgauntlet compile-names` (GPU) to recompile.

The signature is deliberately narrow (same sentence, return-to-battlefield after exile) so a
card that merely exiles AND separately returns something else is not swept in. It is a
worklist generator, not a verdict: read the examples before acting.
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mythgauntlet.data.scryfall import load_card_db  # noqa: E402
from mythgauntlet.semantics.store import SemanticsStore  # noqa: E402

# "Exile target creature you control, then return it to the battlefield ..." and the
# end-step variant "exile ... Return it/that card to the battlefield under its owner's control".
BLINK_RE = re.compile(
    r"\bexile\b[^.]{0,160}?(?:,|\.|;)?\s*(?:then\s+)?return\s+(?:it|that card|them|those cards|that creature|"
    r"each of those cards|the exiled card)\s+to\s+the\s+battlefield",
    re.I,
)
# Not blink: the card exiles ITSELF/another thing and returns it only "if" / "when" a separate
# trigger resolves is still blink; but "exile ... from a graveyard" + "return" is recursion.
RECURSION_RE = re.compile(r"graveyard", re.I)
DESTRUCTIVE = {"exile", "return_to_hand", "gain_control", "sacrifice"}


def ops_of(ccm: dict) -> list[tuple[str, str]]:
    out = []
    for ab in ccm.get("abilities") or []:
        for ef in ab.get("effects") or []:
            tgt = ef.get("target") or {}
            out.append((ef.get("op", "?"), tgt.get("controller") or "-"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", type=int, default=8)
    ap.add_argument("--names-out", type=Path)
    args = ap.parse_args()

    store = SemanticsStore()
    db = load_card_db()
    combos: collections.Counter = collections.Counter()
    hits: list[tuple[str, list[tuple[str, str]], str]] = []
    seen: set[int] = set()
    for card in db._by_name.values():
        if id(card) in seen:
            continue
        seen.add(id(card))
        text = getattr(card, "oracle_text", "") or ""
        if not text or not BLINK_RE.search(text):
            continue
        sem = store.lookup(card.name)
        if sem.ccm is None:
            continue
        # a recursion card ("exile target creature card from your graveyard ... return") is a
        # different mechanic; drop it only when graveyard is the exile source
        m = BLINK_RE.search(text)
        if RECURSION_RE.search(text[max(0, m.start() - 10): m.end()]):
            continue
        ops = ops_of(sem.ccm)
        hits.append((card.name, ops, text))
        combos[tuple(sorted({o for o, _ in ops}))] += 1

    destructive = [h for h in hits if any(o in DESTRUCTIVE and c in ("you", "any", "-") for o, c in h[1])]
    print(f"blink-signature cards with a compiled CCM: {len(hits)}")
    print(f"  carrying a destructive-to-own-side op (exile/return_to_hand/gain_control/sacrifice): {len(destructive)}")
    print("\ntop op combinations:")
    for combo, n in combos.most_common(10):
        print(f"  {n:4d}  {', '.join(combo)}")
    print(f"\nexamples ({args.examples}):")
    for name, ops, text in destructive[: args.examples]:
        print(f"- {name}: {text[:120]!r}\n    ops: {ops}")
    if args.names_out:
        args.names_out.write_text("\n".join(sorted(h[0] for h in destructive)) + "\n", encoding="utf-8")
        print(f"\nwrote {len(destructive)} names to {args.names_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
