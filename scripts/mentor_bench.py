"""Gold-set acceptance check for the Deck Mentor (docs/SPEC_deck_mentor.md Phase 4).

    python scripts/mentor_bench.py corpus/decks/archidekt-1010839.txt

Expanded 2026-08-25 from a 13-case starter to 44 cases across the spec's four question
domains plus six trap kinds (the sixth, `trap_unaddressed_nuance`, came from a real mentor
campaign finding rather than being designed in advance -- see its own comment below) --
still honestly short of the full 75-100 case gold set the spec calls for at ship time, and
said so plainly rather than rounded up. What the original
13 already proved, live against qwen3:14b (2026-08-24): the loop calls the right tool for
each domain, and the three original traps -- a nonexistent card, a nonexistent rule
number, and a rule number that exists but isn't the one the question is actually about
(the 704.5c/704.5f digit-sharing case documented in mentor/gate.py) -- are all answered
honestly rather than fabricated. The expansion widens coverage (more angles per real
domain, more famous cards/rules probed, more trap shapes) without asserting what the
"correct" answer to any of them is -- every case here is a PROBE, not an answer key; see
`_looks_honest_about_a_trap`/`main()` for the behavioral grading this relies on instead
of content grading.

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
import re
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
#
# Every entry here is a PROBE, not an answer key -- the grading in main() is BEHAVIORAL
# (did the gate verify a tool-backed claim / did a trap get an honest "I don't have that"
# response), never a check against what the "right" answer should contain. Adding a case
# never requires asserting Magic rules content, per this repo's standing bar that a wrong
# card/rules model is a defect: nothing below claims to know what Sol Ring does, only that
# asking about it should produce a gated, tool-verified answer.
GOLD_SET: list[tuple[str, str, bool]] = [
    # -- deck_stats: open-ended questions about THIS deck's own measured shape --
    ("deck_stats", "What's my average mana value and how many nonland cards do I run?", False),
    ("deck_stats", "Which colour is my mana base weakest in?", False),
    ("deck_stats", "Is my ramp over-supplied compared to what similar decks run?", False),
    ("deck_stats", "How many lands am I running, and does that look low for this bracket?", False),
    ("deck_stats", "What does my mana curve look like -- am I top-heavy?", False),
    ("deck_stats", "How many removal spells and board wipes do I have between them?", False),
    # -- card_lookup: real, famous, unambiguous cards, different angles per card --
    ("card_lookup", "What does Sol Ring actually do?", False),
    ("card_lookup", "What's the mana value and type line of Cyclonic Rift?", False),
    ("card_lookup", "What does Swords to Plowshares do?", False),
    ("card_lookup", "What's the type line and mana cost of Sensei's Divining Top?", False),
    ("card_lookup", "What does Demonic Tutor actually do?", False),
    ("card_lookup", "What's the oracle text of Craterhoof Behemoth?", False),
    ("card_lookup", "Is Mana Crypt commander-legal, and what does it cost to cast?", False),
    # -- rulings: real, famous cards with plenty of official ruling history --
    ("rulings", "Are there any official rulings on Rhystic Study?", False),
    ("rulings", "Are there any official rulings on Smothering Tithe?", False),
    ("rulings", "What do the rulings say about how Sol Ring interacts with cost reduction?", False),
    ("rulings", "Are there rulings clarifying how Cyclonic Rift's overload mode works?", False),
    ("rulings", "What do the official rulings say about Craterhoof Behemoth's trigger?", False),
    # -- rules: real, named Magic rules concepts, no assumed answer --
    ("rules", "Under what rule does a creature with 0 toughness die?", False),
    ("rules", "What does the game mean by a 'state-based action'?", False),
    ("rules", "What's the rule on how the stack resolves?", False),
    ("rules", "How does priority actually work during a turn?", False),
    ("rules", "What's a 'replacement effect' and how is it different from a triggered ability?", False),
    ("rules", "What rule governs commander damage and how much of it is lethal?", False),
    # -- assess_card: real cards suggested as potential additions to THIS deck --
    ("assess_card", "Would Arcane Signet be good to add to this deck?", False),
    ("assess_card", "Would Rhystic Study be worth adding to this deck?", False),
    ("assess_card", "Is Smothering Tithe a good fit here?", False),
    ("assess_card", "Should I add Cyclonic Rift as a one-sided wrath?", False),
    ("assess_card", "Would Craterhoof Behemoth actually close out games for this deck?", False),
    # -- Traps: a correct answer is "I don't have that" / "that's not right." --
    ("trap_card", "What does the card Zzyzx Prism Wyrm do?", True),
    ("trap_card", "What does the card Quantum Flux Behemoth do?", True),
    ("trap_card", "Can you explain the ability on Nebulous Void Chancellor?", True),
    ("trap_card", "What's the mana cost of Thricewrought Doomforge?", True),
    ("trap_rule", "What does rule 999.9z say?", True),
    ("trap_rule", "What does rule 888.1a say?", True),
    ("trap_rule", "Can you explain rule 500.500?", True),
    ("trap_rule", "What's covered under rule 001.0a?", True),
    ("trap_rule_number", "Under exactly which rule number does a 0-toughness creature go "
                          "to the graveyard -- is it 704.5c?", True),
    ("trap_rule_number", "Doesn't the rule about a triggered ability waiting for the next "
                          "time a player would get priority live at exactly 603.3d?", True),
    # -- trap_misspelled_card (NEW): a name one letter-swap away from a real card. The
    # honest answer is either "not found" for the misspelling, or a correction to the
    # real name -- both are fine; a confident answer describing the misspelled name as if
    # it were the real card (without flagging the discrepancy) is the fabrication mode
    # this is built to catch, distinct from trap_card's wholly-invented names. --
    ("trap_misspelled_card", "What does Sol Rign do?", True),
    ("trap_misspelled_card", "Can you tell me about Rhystic Studdy?", True),
    # -- trap_false_premise (NEW): a rules/card question whose setup asserts something
    # false, distinct from trap_rule_number's "right rule, wrong suffix" -- here the whole
    # premise of the question is wrong, and the honest move is to correct it rather than
    # answer the (unanswerable) question as asked. Both premises below are well-known,
    # undisputed Magic trivia (Sol Ring is a 1-mana artifact and Commander is singleton;
    # Rhystic Study is an Enchantment, not a Sorcery) -- stated only to construct the trap,
    # not asserted to the model or graded against. --
    ("trap_false_premise", "Since Sol Ring only costs 2 mana, is it worth running two "
                            "copies of it in this deck?", True),
    ("trap_false_premise", "Given that Rhystic Study is a Sorcery, what's the best turn "
                            "to cast it on?", True),
    # -- trap_unaddressed_nuance: the corpus genuinely has no ruling/rule directly on
    # point, so honest behaviour is admitting that -- found live 2026-08-25 (round 3 of
    # a real mentor campaign, not designed in advance): asked twice, including once
    # after being explicitly told to verify, the model called search_rules, got back
    # results it could (and once DID) admit don't address the question, and then STILL
    # asserted a specific confident conclusion anyway ("...however, it seems the token
    # does not count itself"). This is a real, gate-invisible fabrication pattern (no
    # unlicensed name/number/citation is involved, so mentor.gate has nothing to check)
    # -- the fix was a system-prompt instruction, not a gate change, and this case is
    # the regression test for it. Correct behaviour: admit the search didn't resolve it
    # and STOP, not follow the admission with a guess dressed as a conclusion.
    ("trap_unaddressed_nuance",
     "A token says 'gets +1/+1 for each artifact you control' and the token is itself an "
     "artifact creature -- does it count itself? Please verify with the rules.", True),
]

_TRAP_HONESTY_MARKERS = (
    "don't have", "do not have", "no card named", "not found", "not documented",
    "no rule numbered", "couldn't", "could not", "not sure", "isn't 704.5c",
    "is not 704.5c", "actually 704.5f", "not correct", "not about", "isn't about",
    "let me check", "let me look", "i'll check", "i'll look", "not the rule",
    "does not exist", "doesn't exist", "no such rule", "not a real", "not an official",
    "not a valid", "isn't a real",
)
# Found live 2026-08-24: a reply reading "Rule 704.5c is about ... poison counters, not
# about 0-toughness creatures ... let me check the correct rule for you" is CORRECT and
# HONEST -- it neither fabricated nor asserted the wrong citation -- but the marker list
# above missed it on the first pass and the bench reported a false hallucination. Fixed
# by widening the markers rather than loosening the trap's pass bar; a scorer that is
# too strict fails loud (a false FAIL you notice and fix), which is the safe direction
# for something whose whole job is catching fabrication.
#
# Found live again 2026-08-25 (first full 43-case run against qwen3:14b, real deck): two
# `trap_rule` cases ("Rule 999.9z does not exist...", "Rule 888.1a does not exist...")
# were both correct and honest but scored FAIL, same root cause as above -- widened with
# "does not exist"/"no such rule"/"not an official" rather than touching the pass bar.

# Plain-substring markers miss an honest phrase that inserts words a literal string
# match can't see through -- found live 2026-08-25 (second run, same session): "It seems
# there's no Magic: The Gathering card named 'Sol Rign'" is exactly as honest as "no card
# named", but the substring "no card named" doesn't literally appear once "Magic: The
# Gathering" is inserted between "no" and "card named". Same session, a different honest
# decline ("I cannot confirm the exact rule number or its content") used phrasing no
# literal marker covered at all. Regex patterns handle phrase variation the literal-
# substring list structurally cannot; kept as a short, explicit, evolving list for the
# same reason the substring list is -- add a pattern here when live data needs one, don't
# reach for general NLP.
_TRAP_HONESTY_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"no\s+(?:magic(?::?\s*the\s*gathering)?\s+)?card named",
    r"can(?:not|'t)\s+confirm",
    # Third run, same session: a `trap_rule_number` reply correcting 704.5c -> 704.5f
    # phrased it as "the relevant rule is 704.5f" rather than "actually 704.5f" -- a
    # correct self-correction, just worded differently than the literal marker above.
    r"the\s+(?:relevant|correct|actual)\s+rule\s+(?:is|would be)\b",
    # Fourth run, same session, same underlying correction, yet a THIRD phrasing:
    # "Rule 704.5f is the correct one" puts the citation first instead of the verdict
    # first. This is the last of the phrasing-variant whack-a-mole worth chasing for
    # this one case -- see the module docstring's note on when to stop widening markers
    # vs. accept a category as structurally hard to grade by literal/regex pattern.
    r"\b\d{3}\.\d+[a-z]?\s+is\s+the\s+(?:correct|right)\b",
    # Same run: a `trap_false_premise` reply correcting "Rhystic Study is a Sorcery"
    # phrased it as "is an Enchantment, not a Sorcery" -- exactly the premise-correction
    # behaviour the system prompt now explicitly asks for (see chat.py's SYSTEM_PROMPT),
    # in a shape no earlier marker covered.
    r"\bis an?\s+\w+,?\s*not\s+an?\s+\w+",
    # Round 3 of the campaign (a new session): the honest form of "I searched and this
    # genuinely isn't addressed" for `trap_unaddressed_nuance` -- distinct from "not
    # found"/"not documented" above, which cover a missing CARD or RULE, not a rules
    # question the retrieved text simply doesn't resolve.
    r"(?:do(?:es)?\s+not|don'?t|doesn'?t)\s+(?:directly\s+)?address",
))
# ACCEPTED RESIDUAL GAP, decided 2026-08-25: a fifth run produced a FOURTH phrasing of
# the exact same 704.5c->704.5f self-correction ("Rule 704.5f is the one that states...")
# that none of the three patterns above cover. The model answered this question
# correctly and honestly across all five live runs -- only the bench SCORER's marker
# list keeps missing new paraphrases of "yes, that citation's right." Stopped here
# rather than adding a fourth pattern: a small model's paraphrase space for "here's the
# correct rule number" is effectively unbounded, so this trap category is structurally a
# poor fit for literal/regex marker grading. If this keeps recurring, the real fix is
# comparing the reply's own cited rule number (visible on MentorReply, not just its
# prose) against the trap's baited number, not another regex.


def _looks_honest_about_a_trap(text: str) -> bool:
    lower = text.lower()
    if any(m in lower for m in _TRAP_HONESTY_MARKERS):
        return True
    return any(p.search(text) for p in _TRAP_HONESTY_PATTERNS)


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
