"""Size the static-ability gap: how many note-only statics a deterministic parser could cover.

The CCM stores every `kind: "static"` ability as free text in `note` (17,438 of them, none with an
op), so the simulator cannot see anthems, cost reducers, characteristic-defining P/T, or
restrictions. `semantics.compiler.parse_attach_grant` already shows the safe precedent: a
deterministic regex parser, no LLM, rejecting the WHOLE note on any token it does not recognise.

    PYTHONPATH=src python scripts/static_scan.py [--examples 5]

Buckets (first match wins; each is a CLOSED template, not a heuristic):
  keyword_only   the note is a bare printed keyword list (Flying, Haste ...) already covered by
                 Card.keywords, so nothing to add
  anthem_pt      "<Other> <subject> you control get +N/+N [and have K]"  -> flat P/T anthem
  anthem_kw      "<subject> you control have K"                          -> keyword anthem
  cost_reduction "<Spells> you cast cost {N} less to cast"
  cda_pt         "<name>'s power/toughness is equal to ..."
  restriction    "can't attack/block/be blocked/..." or "enters tapped" families
  other          everything else (reported, never guessed at)

Read the examples: this sizes a worklist, it does not decide semantics.
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

KEYWORDS = (
    "flying|first strike|double strike|deathtouch|haste|hexproof|indestructible|lifelink|menace|"
    "reach|trample|vigilance|defender|flash|prowess|ward|shroud|fear|intimidate|skulk|changeling|"
    "infect|wither|undying|persist|cascade|convoke|delve|affinity|storm|cycling|kicker|flashback"
)
KW_LIST = re.compile(rf"^\s*(?:(?:{KEYWORDS})(?:\s+[\w{{}}/]+)?\s*(?:,|and|;)?\s*)+\.?\s*$", re.I)
SUBJECT = r"(?:other\s+)?(?:[\w'-]+\s+){0,3}?creatures?(?:\s+you\s+control|\s+your\s+opponents?\s+control)?"
ANTHEM_PT = re.compile(rf"^\s*{SUBJECT}\s+get\s+[+-]\d+/[+-]\d+(?:\s+(?:and\s+have|and\s+has)\s+[\w ,]+)?\.?\s*$", re.I)
ANTHEM_KW = re.compile(rf"^\s*{SUBJECT}\s+(?:have|has)\s+[\w ,]+\.?\s*$", re.I)
COST_RED = re.compile(r"\bcosts?\s+(?:\{\w+\})+\s+less\s+to\s+cast\b|\bcost\s+(?:\{\w+\})+\s+less\b", re.I)
CDA = re.compile(r"\b(?:power|toughness)\b.{0,40}\bequal\s+to\b", re.I)
RESTRICT = re.compile(r"\bcan'?t\s+(?:attack|block|be blocked|be countered|be the target)|\benters?\s+(?:the battlefield\s+)?tapped\b", re.I)


def bucket(note: str) -> str:
    if KW_LIST.match(note):
        return "keyword_only"
    if ANTHEM_PT.match(note):
        return "anthem_pt"
    if COST_RED.search(note):
        return "cost_reduction"
    if CDA.search(note):
        return "cda_pt"
    if RESTRICT.search(note):
        return "restriction"
    if ANTHEM_KW.match(note):
        return "anthem_kw"
    return "other"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", type=int, default=5)
    args = ap.parse_args()
    store = SemanticsStore()
    counts: collections.Counter = collections.Counter()
    ex: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    total = 0
    for name, sem in store._by_name.items():
        for ab in (sem.ccm or {}).get("abilities") or []:
            if ab.get("kind") != "static":
                continue
            note = (ab.get("note") or "").strip()
            if not note or ab.get("effects"):
                continue
            total += 1
            b = bucket(note)
            counts[b] += 1
            if len(ex[b]) < args.examples:
                ex[b].append(((sem.ccm or {}).get("name", name), note[:110]))
    print(f"note-only static abilities: {total}")
    for b, n in counts.most_common():
        print(f"  {b:<15}{n:>6}  {100 * n / total:5.1f}%")
    for b in ("anthem_pt", "cost_reduction", "cda_pt", "restriction", "anthem_kw", "other"):
        print(f"\n{b}:")
        for nm, note in ex[b]:
            print(f"  - {nm}: {note!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
