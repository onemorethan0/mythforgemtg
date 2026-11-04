"""Split a long CLAUDE.md into one file per `## ` section, losslessly.

    python scripts/split_claude_md.py CLAUDE.md docs/engineering

Writes docs/engineering/NN-<slug>.md (each section verbatim, `###` subsections included) and
prints an index (file, size, heading) you can paste into a slim CLAUDE.md. Deterministic: no
model involved, and `--check` re-joins the pieces to prove nothing was dropped.

Why: CLAUDE.md is loaded into every session. At 275 KB, one 81 KB section ("Services /
ports") and one 69 KB subsection dominated it, so the file that is meant to orient an agent
was the least readable thing in the repo.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def split(text: str) -> list[tuple[str, str]]:
    """[(heading, body)] where the first entry is the preamble (heading '')."""
    parts: list[tuple[str, list[str]]] = [("", [])]
    for line in text.split("\n"):
        if line.startswith("## "):
            parts.append((line[3:].strip(), [line]))
        else:
            parts[-1][1].append(line)
    return [(h, "\n".join(b)) for h, b in parts]


def slug(heading: str) -> str:
    s = re.sub(r"`[^`]*`", "", heading)
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return (s[:48].rstrip("-")) or "section"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("out", type=Path)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    text = args.src.read_text(encoding="utf-8")
    sections = split(text)
    args.out.mkdir(parents=True, exist_ok=True)
    written: list[tuple[str, str, int, str]] = []
    n = 0
    for heading, body in sections:
        if not heading:
            continue
        n += 1
        name = f"{n:02d}-{slug(heading)}.md"
        (args.out / name).write_text(body.rstrip("\n") + "\n", encoding="utf-8", newline="\n")
        written.append((name, heading, len(body.encode("utf-8")), body))

    # lossless check: preamble + every section body, rejoined, equals the source
    rejoined = "\n".join([sections[0][1]] + [b for _, b in sections[1:]])
    assert rejoined == text, "split is not lossless"
    for name, heading, size, _ in written:
        print(f"{name}\t{size}\t{heading}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
