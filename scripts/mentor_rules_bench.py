"""End-to-end rules bench: does the Deck Mentor ANSWER a player's rules question with the rule
that actually governs it?

`rules_retrieval_bench.py` measures the search alone, on the player's raw question. The mentor
writes its own search queries, reads the results and may still cite the wrong sibling or fall
back -- this asks the mentor itself (qwen3:14b on llama-swap :8010) and grades the reply:

- `family`: the reply cites the target rule or a rule sharing its parent number (603.3 for
  603.3d) -- the rule that governs the question is in the answer.
- `exact`: the reply cites the target rule itself.
- `fallback`: the gate refused every draft and the honest "I couldn't verify" reply went out.

Questions come from the HELD-OUT set (written by muse-glimmer, a different model family from
both the mentor and the question set the search was tuned on), N per CR section, seeded.

    python scripts/mentor_rules_bench.py --per-section 5 --json out.json
    MYTHGAUNTLET_RULES_DENSE=off python scripts/mentor_rules_bench.py ...   # BM25-only arm
    python scripts/mentor_rules_bench.py --regrade out.json                  # offline re-score
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

RULE_RE = re.compile(r"\b\d{3}\.\d+[a-z]?\b")
_FAMILY_RE = re.compile(r"^(\d{3}\.\d+)")
DECK = ROOT / "corpus" / "decks" / "archidekt-1010839.txt"


def family(number: str) -> str:
    m = _FAMILY_RE.match(number)
    return m.group(1) if m else number


def grade(target: str, text: str, gated: bool) -> dict:
    cited = sorted(set(RULE_RE.findall(text)))
    return {"cited": cited, "exact": target in cited,
            "family": any(family(c) == family(target) for c in cited),
            "fallback": not gated}


def summarize(rows: list[dict]) -> None:
    n = len(rows)
    by_sec: dict[str, list[dict]] = {}
    for r in rows:
        by_sec.setdefault(r["rule"][0], []).append(r)
    print(f"\nn={n}  family {sum(r['family'] for r in rows)/n:.3f}  "
          f"exact {sum(r['exact'] for r in rows)/n:.3f}  "
          f"fallback {sum(r['fallback'] for r in rows)/n:.3f}  "
          f"cites-nothing {sum(not r['cited'] and not r['fallback'] for r in rows)/n:.3f}")
    print("family by section:", {s: f"{sum(r['family'] for r in v)}/{len(v)}"
                                 for s, v in sorted(by_sec.items())})


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--per-section", type=int, default=5)
    p.add_argument("--seed", type=int, default=3)
    p.add_argument("--json", type=Path)
    p.add_argument("--regrade", type=Path)
    p.add_argument("--model", default="qwen3:14b")
    args = p.parse_args()

    if args.regrade:
        rows = json.loads(args.regrade.read_text(encoding="utf-8"))
        for r in rows:
            r.update(grade(r["rule"], r["reply"], not r["fallback"]))
        summarize(rows)
        return 0

    import rules_retrieval_bench as rb
    from mythgauntlet.data import rulings
    from mythgauntlet.data.scryfall import load_card_db
    from mythgauntlet.mentor import chat
    from mythgauntlet.mentor.tools import MentorContext
    from mythgauntlet.model.deck import Deck, resolve
    from mythgauntlet.semantics.store import load_store
    from mythgauntlet.sim.tier0 import DEFAULT_ANALYZE_TURNS, SimConfig

    items = json.loads(rb.HOLDOUT.read_text(encoding="utf-8"))
    rng = random.Random(args.seed)
    by_sec: dict[str, list[dict]] = {}
    for it in items:
        by_sec.setdefault(it["rule"][0], []).append(it)
    chosen = [x for s in sorted(by_sec) for x in rng.sample(by_sec[s], min(args.per_section, len(by_sec[s])))]

    cr = rulings.load_comprehensive_rules()
    index = rulings.RulesSearchIndex(cr)
    arm = "hybrid" if index.warm(wait=True) else "bm25"
    db = load_card_db()
    resolved = resolve(Deck.parse_text(DECK.read_text(encoding="utf-8"), name=DECK.stem), db)
    ctx = MentorContext(card_db=db, cr=cr, rulings_db=rulings.load_rulings_db(), resolved=resolved,
                        cfg=SimConfig(turns=DEFAULT_ANALYZE_TURNS, runs=50, seed=42),
                        store=load_store())
    print(f"arm: {arm}, {len(chosen)} questions", file=sys.stderr)
    rows = []
    for i, it in enumerate(chosen):
        t = time.time()
        reply = chat.ask(ctx, it["q"], model=args.model)
        row = {"rule": it["rule"], "q": it["q"], "reply": reply.text, "arm": arm,
               "searches": [t_.args.get("query") for t_ in reply.tool_trace if t_.name == "search_rules"],
               **grade(it["rule"], reply.text, reply.gated)}
        rows.append(row)
        mark = "FAM " if row["family"] else ("FALL" if row["fallback"] else "miss")
        print(f"[{mark}] {i + 1}/{len(chosen)} {it['rule']:8s} cited={row['cited']} "
              f"({time.time() - t:.0f}s)", file=sys.stderr)
    summarize(rows)
    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
