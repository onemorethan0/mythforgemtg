"""Does the engine's own embedded rules knowledge still match the real Comprehensive Rules?

The simulation/bracket engine (`sim/`, `ratings/`, `semantics/`, `model/`, root `deck_quality.py`)
never reads a rules corpus at runtime -- every rule it needs (mana value, combat, loops, color
identity, ...) is hand-encoded as Python by whoever wrote that feature, with the real CR checked
by hand at the time and cited in a comment. That's fine at the moment it's written. It rots
silently, because WotC renumbers the Comprehensive Rules as new mechanics are added (a rule
number is not a stable identity -- CR 720 was "infinite loops" and is now "Omen Cards"; CR 202.3b
was hybrid mana value and is now double-faced-card mana value), and nothing has ever re-checked
an old citation against a current corpus. Found 2026-08-24 auditing this way: two citations had
drifted, and the engine's own `model/card.py::ManaCost` had never implemented CR 202.3f (hybrid
mana value takes the LARGER half) at all -- it silently undercounted a monocolored hybrid symbol
as 1 instead of its true value. See docs/engine/RULES_AUDIT.md for the full writeup.

This script is the cheap, repeatable half of that process: it finds every "CR ###" citation in
the source tree and reports whether that rule number still EXISTS in the currently-fetched
Comprehensive Rules corpus (`data/rulings.py`; run `mythgauntlet fetch-rules` first). A citation
to a number that no longer exists is a certain sign of drift. A citation that DOES exist is not
proof the code's claim about it is still correct -- that judgment call is not automatable and
stays a human/model review step -- but printing the citing comment next to the rule's current
text makes that review fast instead of requiring a fresh corpus search each time.

Usage:
    .venv\\Scripts\\python scripts\\rules_audit.py            # every citation, grouped by file
    .venv\\Scripts\\python scripts\\rules_audit.py --missing  # only citations that no longer exist
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mythgauntlet.data import rulings  # noqa: E402

# Matches "CR 720", "CR 104.4b", "CR 202.3f", "rule 720", "rule 104.4b" -- case-insensitive,
# the two spellings this codebase actually uses (grep confirmed both appear) -- AND the
# shorthand "CR 506.3/508.1" (a second+ rule number sharing one CR/rule prefix, slash-joined;
# this codebase uses that shape, e.g. sim/game.py's "CR 506.3/508.1").
_NUM = r"\d{3}(?:\.\d+[a-z]?)?"
_CITATION_RE = re.compile(rf"\b(?:CR|[Rr]ule)\s+({_NUM}(?:/{_NUM})*)\b")

# Where the hand-written engine logic actually lives. Deliberately excludes tests/ (a test
# asserting a citation STRING is downstream of the source citation, not a second source of
# truth) and the mentor/ package (its citations are numbers the MODEL retrieved live via
# get_rule/search_rules this turn, not hand-encoded claims that can go stale the same way).
SCAN_ROOTS = [
    REPO / "src" / "mythgauntlet",
    REPO / "deck_quality.py",
    REPO / "server.py",
]
EXCLUDE_DIRS = {"mentor", "__pycache__", "data"}


def _iter_py_files() -> list[Path]:
    out: list[Path] = []
    for root in SCAN_ROOTS:
        if root.is_file():
            out.append(root)
            continue
        for path in root.rglob("*.py"):
            if any(part in EXCLUDE_DIRS for part in path.relative_to(root).parts[:-1]):
                continue
            out.append(path)
    return sorted(set(out))


class Citation:
    def __init__(self, path: Path, lineno: int, number: str, line: str) -> None:
        self.path = path
        self.lineno = lineno
        self.number = number
        self.line = line.strip()


def find_citations() -> list[Citation]:
    out: list[Citation] = []
    for path in _iter_py_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for m in _CITATION_RE.finditer(line):
                for number in m.group(1).split("/"):
                    out.append(Citation(path, lineno, number, line))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--missing", action="store_true", help="only print citations that no longer resolve")
    args = ap.parse_args()

    try:
        cr = rulings.load_comprehensive_rules()
    except FileNotFoundError as exc:
        print(f"{exc}\nRun: .venv\\Scripts\\python -m mythgauntlet fetch-rules", file=sys.stderr)
        return 2

    citations = find_citations()
    if not citations:
        print("No CR/rule citations found under the scanned paths.")
        return 0

    print(f"Comprehensive Rules effective {cr.effective_date} -- {len(citations)} citation(s) "
          f"found across {len({c.path for c in citations})} file(s).\n")

    missing = 0
    for c in citations:
        text = cr.get_rule(c.number)
        rel = c.path.relative_to(REPO)
        if text is None:
            missing += 1
            print(f"[MISSING] {rel}:{c.lineno}  CR {c.number} does not exist in the current corpus")
            print(f"    code says: {c.line}")
            print("    -> likely renumbered by a WotC rules update; re-search the corpus for "
                  "the real current number (rulings.search_rules) before trusting this code.\n")
        elif not args.missing:
            print(f"[ok]      {rel}:{c.lineno}  CR {c.number}")
            print(f"    code says:  {c.line}")
            print(f"    rule text:  {text[:220]}{'...' if len(text) > 220 else ''}\n")

    print(f"{len(citations)} citation(s), {missing} missing / possibly renumbered, "
          f"{len(citations) - missing} resolve.")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
