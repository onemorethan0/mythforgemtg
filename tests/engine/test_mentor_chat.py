"""mentor.chat -- prompt routing (A3) and output shape (A6). No live model: `_post_chat` is
stubbed where a loop is exercised."""

from mythgauntlet.mentor import chat


def test_system_prompt_routes_holistic_questions_to_the_power_profile():
    p = chat.SYSTEM_PROMPT
    assert "get_power_profile FIRST" in p
    # the verdict object is the thing the model must not argue against
    assert '"verdicts"' in p and "never argue against one" in p
    # the unit trap: role `supply` is a strength score, not a card count
    assert "strength score, not a card count" in p


def test_system_prompt_keeps_the_existing_rules():
    p = chat.SYSTEM_PROMPT
    for needle in ("check_legality", "suggest_swap", "get_bracket_estimate",
                   "NEVER state a card's oracle text", "SUBSET relationship"):
        assert needle in p


# ── A6: output shape ─────────────────────────────────────────────────────────────────

import json
from types import SimpleNamespace

from mythgauntlet.mentor import gate
from mythgauntlet.mentor.tools import ToolResult


def test_strip_keeps_paragraph_breaks_and_collapses_the_rest():
    raw = "<think>hmm</think>Answer:  First   paragraph.\t\n\n\n\nSecond  paragraph. \n  tail line  "
    assert chat._strip(raw) == "First paragraph.\n\nSecond paragraph.\ntail line"


def test_strip_still_removes_fences_and_labels():
    assert chat._strip("```\nSome text here.\n```") == "Some text here."
    assert chat._strip("Reply: hello there") == "hello there"
    assert chat._strip(None) == ""


def test_strip_normalises_crlf():
    assert chat._strip("one.\r\n\r\n\r\n\r\ntwo.") == "one.\n\ntwo."


def test_gate_max_chars_default_is_unchanged_and_overridable():
    budget = gate.ClaimBudget()
    long_text = "word " * 400            # ~2000 chars
    assert any("length" in r for r in gate.check(long_text, budget))
    assert gate.check(long_text, budget, max_chars=gate.MAX_CHARS_PROFILE) == []
    assert gate.MAX_CHARS == 1400 and gate.MAX_CHARS_PROFILE == 2400


def _scripted_ask(monkeypatch, tool_name, final_text):
    """Run `ask` against a scripted model: first reply calls `tool_name`, second is the
    final answer. Returns (reply, list of max_tokens seen per model call)."""
    seen = []
    script = [
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "1", "function": {"name": tool_name, "arguments": "{}"}}]},
        {"role": "assistant", "content": final_text},
    ]

    def fake_post(messages, *, model, temperature, max_tokens, timeout=120):
        seen.append(max_tokens)
        return script[min(len(seen) - 1, 1)]   # gate retries re-get the final answer

    monkeypatch.setattr(chat, "_post_chat", fake_post)
    monkeypatch.setattr(chat, "call_tool",
                        lambda ctx, name, args: ToolResult(data={"found": True}))
    ctx = SimpleNamespace(all_card_names=frozenset())
    return chat.ask(ctx, "tell me about my deck"), seen


def test_profile_turn_widens_token_budget_and_gate_length(monkeypatch):
    long_answer = ("The deck is resilient to wipes. " * 50).strip()   # ~1600 chars
    reply, seen = _scripted_ask(monkeypatch, "get_power_profile", long_answer)
    assert seen == [chat.DEFAULT_MAX_TOKENS, chat.PROFILE_MAX_TOKENS]   # tool call, then the answer
    assert reply.gated is True, reply.gate_rejections


def test_non_profile_turn_keeps_the_tight_limits(monkeypatch):
    long_answer = ("The deck is resilient to wipes. " * 50).strip()
    reply, seen = _scripted_ask(monkeypatch, "get_deck_stats", long_answer)
    assert set(seen) == {chat.DEFAULT_MAX_TOKENS}
    # 1600 chars is over the default ceiling, so the gate rejects it.
    assert any("length" in r for _d, rs in reply.gate_rejections for r in rs)


# ── announce-then-stop nudge ─────────────────────────────────────────────────────────

import pytest


@pytest.mark.parametrize("text,expect", [
    ("I'll look into your collection to find a card that could help.", True),
    ("Let me check the rules for that.", True),
    ("I will now search for a suitable swap.", True),
    ("Let me know if you'd like me to check anything else.", False),
    ("The deck looks into the graveyard for value.", False),
    ("", False),
])
def test_announces_a_lookup(text, expect):
    assert chat._announces_a_lookup(text) is expect


def test_ask_nudges_once_when_the_model_announces_a_lookup_and_stops(monkeypatch):
    seen_messages = []
    script = [
        {"role": "assistant", "content": "I'll look into your collection to find a card."},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "1", "function": {"name": "suggest_swap", "arguments": "{}"}}]},
        {"role": "assistant", "content": "I didn't find a measured improvement from your collection."},
    ]

    def fake_post(messages, *, model, temperature, max_tokens, timeout=120):
        seen_messages.append([m.get("content") for m in messages[-2:]])
        return script[len(seen_messages) - 1]

    monkeypatch.setattr(chat, "_post_chat", fake_post)
    monkeypatch.setattr(chat, "call_tool", lambda ctx, name, args: ToolResult(data={"found": True}))
    reply = chat.ask(SimpleNamespace(all_card_names=frozenset()), "how could I make it faster?")
    assert [t.name for t in reply.tool_trace] == ["suggest_swap"]
    assert chat._LOOKUP_NUDGE in seen_messages[1][-1]
    assert reply.gated is True
    assert "measured improvement" in reply.text


def test_ask_nudges_at_most_once(monkeypatch):
    calls = []

    def fake_post(messages, *, model, temperature, max_tokens, timeout=120):
        calls.append(1)
        return {"role": "assistant", "content": "I'll look into that for you, one moment here."}

    monkeypatch.setattr(chat, "_post_chat", fake_post)
    reply = chat.ask(SimpleNamespace(all_card_names=frozenset()), "anything")
    # one draft + one nudge + (gate attempts reuse the last draft; retries re-ask)
    assert calls[:2] == [1, 1]
    assert reply.tool_trace == []


def test_system_prompt_routes_which_cards_questions_to_list_deck_cards():
    assert "list_deck_cards" in chat.SYSTEM_PROMPT
    assert any(t["function"]["name"] == "list_deck_cards" for t in chat.TOOL_SCHEMAS)


# ── improvement questions must reach suggest_swap (diagnose_axis must not end the turn) ──

@pytest.mark.parametrize("question,expect", [
    ("How could I make this deck faster?", True),
    ("how can I speed up my deck", True),
    ("How resilient is this deck to a board wipe, and how could I improve that?", True),
    ("What are the weakest cards in this deck?", True),
    ("What should I cut for a wrath effect?", True),
    ("How does this deck win?", False),
    ("What does this deck do well and poorly?", False),
    ("How resilient is this deck to a board wipe?", False),
    ("", False),
])
def test_wants_a_swap(question, expect):
    assert chat._wants_a_swap(question) is expect


def _scripted_turns(monkeypatch, script):
    seen = []

    def fake_post(messages, *, model, temperature, max_tokens, timeout=120):
        seen.append([m.get("content") for m in messages[-1:]])
        return script[min(len(seen) - 1, len(script) - 1)]

    monkeypatch.setattr(chat, "_post_chat", fake_post)
    monkeypatch.setattr(chat, "call_tool", lambda ctx, name, args: ToolResult(data={"found": True}))
    return seen


def _call(name, args="{}"):
    return {"role": "assistant", "content": "",
            "tool_calls": [{"id": "1", "function": {"name": name, "arguments": args}}]}


def test_ask_nudges_to_suggest_swap_when_diagnose_axis_ends_an_improvement_turn(monkeypatch):
    seen = _scripted_turns(monkeypatch, [
        _call("diagnose_axis", '{"axis": "clock"}'),
        {"role": "assistant", "content": "The main issue is a lack of mana ramp in the deck."},
        _call("suggest_swap", '{"axis": "clock"}'),
        {"role": "assistant", "content": "I didn't find a measured improvement from your collection."},
    ])
    reply = chat.ask(SimpleNamespace(all_card_names=frozenset()), "How could I make this deck faster?")
    assert [t.name for t in reply.tool_trace] == ["diagnose_axis", "suggest_swap"]
    assert chat._SWAP_NUDGE in seen[2][-1]
    assert "measured improvement" in reply.text


def test_no_swap_nudge_when_suggest_swap_already_ran_or_the_question_is_not_an_improvement(monkeypatch):
    seen = _scripted_turns(monkeypatch, [
        _call("suggest_swap", '{"axis": "clock"}'),
        {"role": "assistant", "content": "I didn't find a measured improvement from your collection."},
    ])
    chat.ask(SimpleNamespace(all_card_names=frozenset()), "How could I make this deck faster?")
    assert all(chat._SWAP_NUDGE not in " ".join(map(str, s)) for s in seen)
    seen = _scripted_turns(monkeypatch, [
        {"role": "assistant", "content": "The deck wins through combat with its creatures."},
    ])
    reply = chat.ask(SimpleNamespace(all_card_names=frozenset()), "How does this deck win?")
    assert reply.tool_trace == [] and len(seen) == 1


def test_swap_nudge_fires_at_most_once(monkeypatch):
    seen = _scripted_turns(monkeypatch, [
        {"role": "assistant", "content": "Adding more ramp would make it faster in general terms."},
    ])
    reply = chat.ask(SimpleNamespace(all_card_names=frozenset()), "How could I improve this deck?")
    assert sum(chat._SWAP_NUDGE in " ".join(map(str, s)) for s in seen) == 1
    assert reply.tool_trace == []


def test_system_prompt_says_diagnose_axis_never_replaces_suggest_swap():
    p = chat.SYSTEM_PROMPT
    assert "diagnose_axis NEVER replaces suggest_swap" in p
    assert 'axis clock for "faster" (never ceiling' in p


def test_a_faster_question_is_routed_to_the_clock_axis():
    f = chat._route_swap_axis
    assert f("How could I make this deck faster?", {"axis": "ceiling"}) == {"axis": "clock"}
    assert f("how do i speed up my deck", {"axis": "speed"}) == {"axis": "clock"}
    # not for other questions, other axes, or an already-correct / absent axis
    assert f("how do I improve my interaction", {"axis": "ceiling"}) == {"axis": "ceiling"}
    assert f("make it faster", {"axis": "consistency"}) == {"axis": "consistency"}
    assert f("make it faster", {"axis": "clock"}) == {"axis": "clock"}
    assert f("make it faster", {}) == {}


def test_ask_runs_suggest_swap_on_clock_for_a_faster_question(monkeypatch):
    ran = []

    def fake_call(ctx, name, args):
        ran.append((name, args))
        return ToolResult(data={"found": True})

    script = [_call("suggest_swap", '{"axis": "ceiling"}'),
              {"role": "assistant", "content": "I didn't find a measured improvement from your collection."}]
    seen = []

    def fake_post(messages, *, model, temperature, max_tokens, timeout=120):
        seen.append(1)
        return script[min(len(seen) - 1, 1)]

    monkeypatch.setattr(chat, "_post_chat", fake_post)
    monkeypatch.setattr(chat, "call_tool", fake_call)
    reply = chat.ask(SimpleNamespace(all_card_names=frozenset()), "How could I make this deck faster?")
    assert ran == [("suggest_swap", {"axis": "clock"})]
    assert reply.tool_trace[0].args == {"axis": "clock"}
