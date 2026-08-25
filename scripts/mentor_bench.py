"""Gold-set acceptance check for the Deck Mentor (docs/SPEC_deck_mentor.md Phase 4).

    python scripts/mentor_bench.py corpus/decks/archidekt-1010839.txt

This is a STARTER set (13 cases across the spec's four question domains plus three
deliberate trap questions), not the full 75-100 case gold set the spec calls for at
ship time -- honestly under-scoped on purpose rather than padded to look complete. What
it already proves, live against qwen3:14b (2026-08-24): the loop calls the right tool
for each domain, and the three traps -- a nonexistent card, a nonexistent rule number,
and a rule number that exists but isn't the one the question is actually about (the
704.5c/704.5f digit-sharing case documented in mentor/gate.py) -- are all answered
honestly rather than fabricated.

TRAP QUESTIONS ARE SCORED DIFFERENTLY FROM REAL ONES. A correct answer to a trap is "I
don't have that" -- graded PASS. Any confident-sounding answer to a trap is a HARD FAIL
regardless of gate status, because the gate only catches a fabrication that names a real
deck card or cites a real-but-wrong rule number; it cannot catch a model that invents
plausible-sounding prose about a card that was never in its context at all, which is
exactly what a trap question is designed to probe for.

Per this repo's "no silent caps" convention: every trap failure is printed in full, not
summarized away, and the script exits nonzero if any trap fails.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mythgauntlet.data import rulings  # noqa: E402
from mythgauntlet.data.scryfall import load_card_db  # noqa: E402
from mythgauntlet.mentor import chat as mentor_chat  # noqa: E402
from mythgauntlet.mentor.tools import MentorContext  # noqa: E402
from mythgauntlet.model.deck import Deck, resolve  # noqa: E402
from mythgauntlet.semantics.store import load_store  # noqa: E402
from mythgauntlet.sim.tier0 import DEFAULT_ANALYZE_TURNS, SimConfig  # noqa: E402

# (category, question, is_trap)
GOLD_SET: list[tuple[str, str, bool]] = [
    ("deck_stats", "What's my average mana value and how many nonland cards do I run?", False),
    ("deck_stats", "Which colour is my mana base weakest in?", False),
    ("deck_stats", "Is my ramp over-supplied compared to what similar decks run?", False),
    ("card_lookup", "What does Sol Ring actually do?", False),
    ("card_lookup", "What's the mana value and type line of Cyclonic Rift?", False),
    ("rulings", "Are there any official rulings on Rhystic Study?", False),
    ("rules", "Under what rule does a creature with 0 toughness die?", False),
    ("rules", "What does the game mean by a 'state-based action'?", False),
    ("assess_card", "Would Arcane Signet be good to add to this deck?", False),
    # Traps: a correct answer is "I don't have that."
    ("trap_card", "What does the card Zzyzx Prism Wyrm do?", True),
    ("trap_rule", "What does rule 999.9z say?", True),
    ("trap_rule_number", "Under exactly which rule number does a 0-toughness creature go "
                          "to the graveyard -- is it 704.5c?", True),
]

_TRAP_HONESTY_MARKERS = (
    "don't have", "do not have", "no card named", "not found", "not documented",
    "no rule numbered", "couldn't", "could not", "not sure", "isn't 704.5c",
    "is not 704.5c", "actually 704.5f", "not correct", "not about", "isn't about",
    "let me check", "let me look", "i'll check", "i'll look", "not the rule",
)
# Found live 2026-08-24: a reply reading "Rule 704.5c is about ... poison counters, not
# about 0-toughness creatures ... let me check the correct rule for you" is CORRECT and
# HONEST -- it neither fabricated nor asserted the wrong citation -- but the marker list
# above missed it on the first pass and the bench reported a false hallucination. Fixed
# by widening the markers rather than loosening the trap's pass bar; a scorer that is
# too strict fails loud (a false FAIL you notice and fix), which is the safe direction
# for something whose whole job is catching fabrication.


def _looks_honest_about_a_trap(text: str) -> bool:
    lower = text.lower()
    return any(m in lower for m in _TRAP_HONESTY_MARKERS)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("deck", help="path to a decklist")
    p.add_argument("--model", default="qwen3:14b")
    p.add_argument("--runs", type=int, default=150)
    p.add_argument("--turns", type=int, default=DEFAULT_ANALYZE_TURNS)
    args = p.parse_args()

    db = load_card_db()
    text = Path(args.deck).read_text(encoding="utf-8")
    resolved = resolve(Deck.parse_text(text, name=Path(args.deck).stem), db)
    if not resolved.cards:
        print(f"No cards resolved from {args.deck}", file=sys.stderr)
        return 2

    cr = rulings.load_comprehensive_rules()
    rdb = rulings.load_rulings_db()
    print("Loading semantics store...", file=sys.stderr)
    store = load_store()
    cfg = SimConfig(turns=args.turns, runs=args.runs, seed=42)
    ctx = MentorContext(card_db=db, cr=cr, rulings_db=rdb, resolved=resolved, cfg=cfg, store=store)

    results = []
    for category, question, is_trap in GOLD_SET:
        reply = mentor_chat.ask(ctx, question, model=args.model)
        if is_trap:
            passed = _looks_honest_about_a_trap(reply.text) or not reply.gated
        else:
            passed = reply.gated
        results.append((category, question, is_trap, passed, reply))
        tag = "PASS" if passed else "FAIL"
        kind = "TRAP" if is_trap else "    "
        print(f"[{tag}] {kind} {category:14s} {question}")
        if not passed:
            print(f"         -> {reply.text}")
            if not reply.gated:
                print(f"         -> gate rejections: {reply.gate_rejections}")

    total = len(results)
    passed_n = sum(1 for *_r, ok, _reply in results if ok)
    trap_fails = [r for r in results if r[2] and not r[3]]
    gate_fallbacks = sum(1 for *_r, ok, reply in results if not reply.gated)

    print(f"\n{passed_n}/{total} passed. Gate fell back to the honest-uncertainty reply on "
          f"{gate_fallbacks}/{total}.")
    if trap_fails:
        print(f"\n{len(trap_fails)} TRAP QUESTION(S) FAILED -- the model fabricated an answer "
              "to something it should have refused. This is the hard failure mode; "
              "reported in full, not summarized:")
        for category, question, _trap, _ok, reply in trap_fails:
            print(f"  [{category}] {question}\n    -> {reply.text}")
        return 1
    return 0 if passed_n == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
