"""Rules questions get the rules searched before the model answers (`chat._presearch_question_rules`,
2026-10-05). Pinned against every question the benches ask: the generated rules sets must fire,
the deck/card questions must not -- so a regex edit is judged on 691 questions, not one."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from mythgauntlet.mentor import chat
from mythgauntlet.mentor.tools import ToolResult

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mb, hb = _load("mentor_bench"), _load("mentor_holistic_bench")
RULES_CATS = {"rules", "trap_rule", "trap_rule_number", "trap_unaddressed_nuance"}
NOT_RULES = {"assess_card", "deck_stats", "bracket", "suggest_swap", "card_lookup", "trap_card",
             "trap_misspelled_card", "trap_false_premise", "check_legality", "rulings"}
GENERATED = [it["q"] for f in ("rules_questions.json", "rules_questions_holdout.json")
             for it in json.loads((SCRIPTS / "data" / f).read_text(encoding="utf-8"))]


def test_every_bench_category_is_classified_here():
    assert {c for c, _, _ in mb.GOLD_SET} <= RULES_CATS | NOT_RULES


def test_deck_and_card_questions_never_presearch():
    asked = [q for _, q, _ in hb.QUESTIONS] + [q for c, q, _ in mb.GOLD_SET if c in NOT_RULES]
    fired = [q for q in asked if chat._is_rules_question(q)]
    assert not fired, fired


def test_the_bench_rules_questions_all_presearch():
    asked = [q for c, q, _ in mb.GOLD_SET if c in RULES_CATS]
    assert [q for q in asked if not chat._is_rules_question(q)] == []


def test_generated_rules_questions_presearch_at_least_95_percent():
    # 2026-10-05: 629/629-ish; misses are capitalised mechanic names ("Monster Role",
    # "Alternating Teams") the card-name guard reads as a card. A drop below 95% is a regression.
    fired = sum(chat._is_rules_question(q) for q in GENERATED)
    assert fired / len(GENERATED) >= 0.95, fired


def test_presearch_runs_search_rules_with_the_question_and_records_it():
    calls = []

    def fake(_ctx, name, args):
        calls.append((name, dict(args)))
        return ToolResult(data={"results": [{"kind": "rule", "ref": "402.2", "text": "x"}]},
                          rule_numbers=frozenset({"402.2"}))

    orig, chat.call_tool = chat.call_tool, fake
    trace, results, messages = [], [], []
    try:
        q = "What happens if I have more than seven cards at the end of my turn?"
        assert chat._presearch_question_rules(SimpleNamespace(cr=object()), q, trace, results,
                                              messages)
        assert not chat._presearch_question_rules(
            SimpleNamespace(cr=object()), "How could I make this deck faster?", trace, results,
            messages)
    finally:
        chat.call_tool = orig
    assert calls == [("search_rules", {"query": q, "k": chat._PRESEARCH_K})]
    assert trace[0].name == "search_rules" and results[0].rule_numbers == {"402.2"}
    assert messages[0]["tool_calls"][0]["id"] == "auto-q-search"


def test_no_rules_corpus_means_no_presearch():
    assert not chat._presearch_question_rules(SimpleNamespace(cr=None),
                                              "Can I respond to a trigger?", [], [], [])
