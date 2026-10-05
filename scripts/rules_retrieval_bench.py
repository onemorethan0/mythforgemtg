"""Rules retrieval bench: can `search_rules` find the rule a player's question is about?

Every rules answer the Deck Mentor gives starts with retrieval -- a rule the search never returns
is a rule the mentor cannot cite, so it either guesses or falls back. This bench samples rules
across all nine CR sections, has qwen3:14b (llama-swap :8010) write the question a PLAYER would
ask whose answer is that rule (no rule number, no copied wording), and measures recall@k of the
rules search over those questions.

    python scripts/rules_retrieval_bench.py --generate      # ~20 min GPU, writes the question set
    python scripts/rules_retrieval_bench.py                 # recall@1/3/5/10, offline, seconds
    python scripts/rules_retrieval_bench.py --misses 30     # show missed questions

A hit is the target rule itself OR its parent/sibling sub-rule that carries the same topic
(`family`): the mentor is told to read a hit's siblings, and `get_rule` on the parent number
returns them. Exact-rule recall is reported beside it.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from mythgauntlet.data import rulings  # noqa: E402

DATA = ROOT / "scripts" / "data" / "rules_questions.json"
# Held out: written by a DIFFERENT model family (muse-glimmer, Meta 30B) for rules not in DATA, so a change tuned on the
# qwen3:14b set is checked against a phrasing style it never saw.
HOLDOUT = ROOT / "scripts" / "data" / "rules_questions_holdout.json"
LLM = "http://127.0.0.1:8010/v1/chat/completions"
PER_SECTION = 50
BATCH = 10
_FAMILY_RE = re.compile(r"^(\d{3}\.\d+)")

PROMPT = """You write test questions for a Magic: The Gathering rules assistant.
For EACH rule below, write ONE question that a player at the table would actually ask, whose
answer is exactly what that rule says. Rules:
- Never mention a rule number.
- Do not copy the rule's wording; use everyday player language ("my creature dies", "can I
  respond", "what happens if"), the way someone who has NOT read the rulebook would ask.
- The question must be answerable from that rule alone.

{rules}

Output ONLY a JSON array: [{{"rule": "<number>", "q": "<question>"}}, ...] with one entry per rule,
in the same order. /no_think"""


def _family(number: str) -> str:
    m = _FAMILY_RE.match(number)
    return m.group(1) if m else number


def sample_rules(cr, seed: int = 7, per_section: int = PER_SECTION,
                 exclude: frozenset = frozenset()) -> list[str]:
    rng = random.Random(seed)
    by_section: dict[str, list[str]] = {}
    for number, text in cr.rules.items():
        if ("." not in number or len(text) < 60 or text.lower().startswith("see rule")
                or number in exclude):
            continue
        by_section.setdefault(number[0], []).append(number)
    picked = []
    for section in sorted(by_section):
        pool = sorted(by_section[section])
        picked += rng.sample(pool, min(per_section, len(pool)))
    return picked


def _ask(prompt: str, model: str = "qwen3:14b") -> list[dict]:
    reasoning = model.startswith("muse")  # splits reasoning/content: a small budget returns ""
    payload = {"model": model, "temperature": 1.0 if reasoning else 0.4,
               "max_tokens": 16000 if reasoning else 3000,
               "chat_template_kwargs": {"enable_thinking": False},
               "messages": [{"role": "user", "content": prompt}]}
    for attempt in range(4):
        try:
            r = requests.post(LLM, json=payload, timeout=600)
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
            m = re.search(r"\[.*\]", text, re.S)
            return json.loads(m.group(0)) if m else []
        except (requests.RequestException, json.JSONDecodeError) as exc:
            print(f"  retry {attempt + 1}: {exc}", file=sys.stderr)
            time.sleep(20 * (attempt + 1))
    return []


def generate(cr, out_path: Path = DATA, model: str = "qwen3:14b", seed: int = 7,
             per_section: int = PER_SECTION, exclude: frozenset = frozenset()) -> None:
    numbers = sample_rules(cr, seed, per_section, exclude)
    out = []
    for i in range(0, len(numbers), BATCH):
        chunk = numbers[i:i + BATCH]
        block = "\n".join(f"[{n}] {cr.rules[n][:600]}" for n in chunk)
        got = {str(e.get("rule")): e.get("q") for e in _ask(PROMPT.format(rules=block), model)
               if isinstance(e, dict)}
        for n in chunk:
            q = got.get(n)
            if isinstance(q, str) and q.strip() and not re.search(r"\b\d{3}\.\d", q):
                out.append({"rule": n, "q": q.strip()})
        print(f"{min(i + BATCH, len(numbers))}/{len(numbers)} rules, {len(out)} questions",
              file=sys.stderr)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def evaluate(cr, items: list[dict], show_misses: int = 0, k_max: int = 10,
             dense: bool = True) -> dict:
    index = rulings.RulesSearchIndex(cr, dense=dense)
    if dense and index.dense_enabled:
        index.warm(wait=True)  # the shipped ranking is the fused one; build it if missing
    exact = Counter()
    family = Counter()
    by_section_hits = Counter()
    by_section_n = Counter()
    misses = []
    for it in items:
        target = it["rule"]
        refs = [r.ref for r in index.search(it["q"], k=k_max) if r.kind == "rule"]
        sec = target[0]
        by_section_n[sec] += 1
        e_rank = refs.index(target) + 1 if target in refs else None
        f_rank = next((i + 1 for i, r in enumerate(refs) if _family(r) == _family(target)), None)
        for k in (1, 3, 5, 10):
            exact[k] += bool(e_rank and e_rank <= k)
            family[k] += bool(f_rank and f_rank <= k)
        by_section_hits[sec] += bool(f_rank and f_rank <= 5)
        if not (f_rank and f_rank <= 5):
            misses.append((it, refs[:5]))
    n = len(items)
    report = {
        "n": n,
        "exact": {k: round(exact[k] / n, 3) for k in (1, 3, 5, 10)},
        "family": {k: round(family[k] / n, 3) for k in (1, 3, 5, 10)},
        "family@5_by_section": {s: round(by_section_hits[s] / by_section_n[s], 2)
                                for s in sorted(by_section_n)},
    }
    print(json.dumps(report, indent=1))
    for it, refs in misses[:show_misses]:
        print(f"\n[{it['rule']}] {it['q']}\n   got {refs}\n   rule: {cr.rules[it['rule']][:160]}")
    return report


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--generate", action="store_true")
    p.add_argument("--generate-holdout", action="store_true",
                   help="write the muse-glimmer held-out set (20 rules/section, none from the main set)")
    p.add_argument("--holdout", action="store_true", help="evaluate the held-out set")
    p.add_argument("--misses", type=int, default=0)
    p.add_argument("--bm25", action="store_true", help="BM25 alone (the pre-2026-10-05 search)")
    args = p.parse_args()
    cr = rulings.load_comprehensive_rules()
    if args.generate:
        generate(cr)
    if args.generate_holdout:
        main_rules = frozenset(it["rule"] for it in json.loads(DATA.read_text(encoding="utf-8")))
        generate(cr, HOLDOUT, model="muse-glimmer", seed=11, per_section=20, exclude=main_rules)
    path = HOLDOUT if (args.holdout or args.generate_holdout) else DATA
    items = json.loads(path.read_text(encoding="utf-8"))
    evaluate(cr, items, args.misses, dense=not args.bm25)
    return 0


if __name__ == "__main__":
    sys.exit(main())
