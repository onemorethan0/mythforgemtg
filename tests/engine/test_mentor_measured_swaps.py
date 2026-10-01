"""Mentor adhoc D2: `get_measured_swaps` (cached full swap search), its chat-loop wiring and the
`/mentor/chat` `advice` pass-through. Offline: synthetic cached /advise JSON, scripted LLM."""

from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from mythgauntlet import server as server_mod  # noqa: E402
from mythgauntlet.data.rulings import ComprehensiveRules  # noqa: E402
from mythgauntlet.data.scryfall import CardDb  # noqa: E402
from mythgauntlet.mentor import chat  # noqa: E402
from mythgauntlet.mentor.chat import MentorReply, ToolCallRecord  # noqa: E402
from mythgauntlet.mentor.tools import (  # noqa: E402
    TOOL_SCHEMAS, MentorContext, ToolResult, call_tool,
)
from mythgauntlet.model.deck import Deck, ResolvedDeck  # noqa: E402
from mythgauntlet.ratings import advisor  # noqa: E402
from mythgauntlet.semantics.store import SemanticsStore  # noqa: E402
from mythgauntlet.sim.tier0 import SimConfig  # noqa: E402


def _fake_cr() -> ComprehensiveRules:
    return ComprehensiveRules(effective_date="x", source_url="https://example.invalid",
                              rules={}, glossary={})


def _ctx(make_card, empty_store, advice=None) -> MentorContext:
    commander = make_card("Test Commander", type_line="Legendary Creature — Human",
                          mana_cost="{2}{G}", color_identity=("G",))
    forest = make_card("Forest", type_line="Basic Land — Forest",
                       produced_mana=("G",), color_identity=("G",))
    resolved = ResolvedDeck(deck=Deck(name="t"), commanders=[commander],
                            cards=[(forest, 35)], missing=[])
    return MentorContext(
        card_db=CardDb([commander, forest]), cr=_fake_cr(), rulings_db={}, resolved=resolved,
        cfg=SimConfig(turns=5, runs=10, seed=1), store=empty_store, advice=advice,
    )


def _advise_json(axis="clock", backed=True, suggestions=True):
    """The shape Forge's `/advise` route returns (server.run_advise), brief as `as_dict()`."""
    sugs = []
    if suggestions:
        sugs.append({
            "add": "Owned Removal", "cut": "Obscure Bear", "before": 40.0, "after": 47.2,
            "delta": 7.2, "reason": "template",
            "brief": {
                "axis": axis, "axis_label": "Clock", "before": 40.0, "after": 47.2, "delta": 7.2,
                "noise_floor": 1.0, "commander": "Test Commander", "archetypes": [],
                "add": {}, "cut": {"redundancy_backed": backed},
                "kill_turn_before": 9.3, "kill_turn_after": 8.8,
                "allowed_card_names": ["Owned Removal", "Obscure Bear", "Synergy Pal"],
            },
        })
    return {
        "engine_version": "x", "axis": axis, "axis_label": "Clock", "baseline": 40.04,
        "cut": "Obscure Bear", "evaluated": 12, "analyses": 70, "cut_pool": 6,
        "cut_strategy": "redundant", "min_delta": 1.0, "candidates_that_fit": 30,
        "collection_source": "suite", "suggestions": sugs,
    }


# ── the tool ─────────────────────────────────────────────────────────────────────────

def test_unavailable_without_a_cached_search(make_card, empty_store):
    data = call_tool(_ctx(make_card, empty_store), "get_measured_swaps", {"axis": "clock"}).data
    assert data["available"] is False and data["axis"] == "clock"
    assert data["message"] == (
        "No full swap search has been run for clock yet -- run Advise (clock) on the deck "
        "page; it takes a few minutes.")
    # a cached search for a DIFFERENT axis does not answer this one
    ctx = _ctx(make_card, empty_store, {"ceiling": {"result": _advise_json("ceiling")}})
    assert call_tool(ctx, "get_measured_swaps", {"axis": "clock"}).data["available"] is False


def test_returns_cached_suggestions_with_suggest_swap_licensing(make_card, empty_store):
    ctx = _ctx(make_card, empty_store, {"clock": {
        "result": _advise_json("clock", backed=False), "computed_at": "2026-09-30T12:00:00"}})
    res = call_tool(ctx, "get_measured_swaps", {"axis": "clock"})
    d = res.data
    assert d["available"] is True and d["found"] is True and d["improving_swap_found"] is True
    assert d["source"] == "full_search" and d["computed_at"] == "2026-09-30T12:00:00"
    assert "cut" not in d                       # the pool head is not advice
    assert d["current"]["axis"] == "clock" and d["current"]["score"] == 40.0
    sug = d["suggestions"][0]
    assert sug["add"] == "Owned Removal" and sug["cut_is_redundant"] is False
    assert "cut_note" in sug                    # D0b disclosure, same as suggest_swap
    assert {"Owned Removal", "Obscure Bear", "Synergy Pal"} <= res.card_names
    # the cached dict is not mutated
    assert "cut_is_redundant" not in ctx.advice["clock"]["result"]["suggestions"][0]


def test_a_backed_cut_carries_no_note(make_card, empty_store):
    ctx = _ctx(make_card, empty_store, {"clock": {"result": _advise_json("clock", backed=True)}})
    sug = call_tool(ctx, "get_measured_swaps", {"axis": "clock"}).data["suggestions"][0]
    assert sug["cut_is_redundant"] is True and "cut_note" not in sug


def test_an_auto_search_answers_for_the_axis_it_resolved_to(make_card, empty_store):
    ctx = _ctx(make_card, empty_store, {"auto": {"result": _advise_json("consistency")}})
    assert call_tool(ctx, "get_measured_swaps", {"axis": "consistency"}).data["available"] is True
    assert call_tool(ctx, "get_measured_swaps", {"axis": "clock"}).data["available"] is False


def test_an_empty_search_licenses_no_card(make_card, empty_store):
    ctx = _ctx(make_card, empty_store,
               {"clock": {"result": _advise_json("clock", suggestions=False)}})
    res = call_tool(ctx, "get_measured_swaps", {"axis": "clock"})
    assert res.data["available"] is True and res.data["improving_swap_found"] is False
    assert "suggestions" not in res.data and not res.card_names
    assert "No measured swap" in res.data["message"]


def test_bad_axis_is_graceful(make_card, empty_store):
    data = call_tool(_ctx(make_card, empty_store), "get_measured_swaps", {"axis": "nope"}).data
    assert data["found"] is False and "Bad arguments" in data["message"]


def test_schema_lists_every_advisor_axis():
    fn = next(t["function"] for t in TOOL_SCHEMAS if t["function"]["name"] == "get_measured_swaps")
    assert fn["parameters"]["required"] == ["axis"]
    assert set(fn["parameters"]["properties"]["axis"]["enum"]) == set(advisor.AXES)


# ── chat loop ────────────────────────────────────────────────────────────────────────

def _call(name, args="{}"):
    return {"role": "assistant", "content": "",
            "tool_calls": [{"id": "1", "function": {"name": name, "arguments": args}}]}


def _drive(monkeypatch, script, tool_data):
    seen, ran = [], []

    def fake_post(messages, *, model, temperature, max_tokens, timeout=120):
        seen.append(messages[-1].get("content"))
        return script[min(len(seen) - 1, len(script) - 1)]

    def fake_call(ctx, name, args):
        ran.append((name, args))
        return ToolResult(data=tool_data(name))

    monkeypatch.setattr(chat, "_post_chat", fake_post)
    monkeypatch.setattr(chat, "call_tool", fake_call)
    return seen, ran


def test_system_prompt_prefers_get_measured_swaps_and_keeps_the_fallback():
    p = chat.SYSTEM_PROMPT
    assert "get_measured_swaps FIRST" in p
    assert "available false, call suggest_swap" in p and "shallow" in p
    assert 'axis clock for "faster" (never ceiling' in p      # existing routing rule kept


def test_faster_question_routes_get_measured_swaps_to_clock(monkeypatch):
    seen, ran = _drive(
        monkeypatch,
        [_call("get_measured_swaps", '{"axis": "ceiling"}'),
         {"role": "assistant", "content": "I didn't find a measured improvement from your collection."}],
        lambda name: {"available": True, "improving_swap_found": False})
    chat.ask(SimpleNamespace(all_card_names=frozenset()), "How could I make this deck faster?")
    assert ran == [("get_measured_swaps", {"axis": "clock"})]
    assert len(seen) == 2                       # an available result is an answer: no nudge


def test_unavailable_measured_swaps_runs_the_suggest_swap_fallback_itself(monkeypatch):
    """qwen3:14b stops at "run Advise" after an unavailable lookup and ignores a nudge (resilience
    1/9 on the holistic bench), so the quick search the prompt promises is run deterministically."""
    seen, ran = _drive(
        monkeypatch,
        [_call("get_measured_swaps", '{"axis": "clock"}'),
         {"role": "assistant", "content": "No full search has been run yet; run Advise."},
         {"role": "assistant", "content": "I didn't find a measured improvement from your collection."}],
        lambda name: {"available": False} if name == "get_measured_swaps" else {"found": True})
    reply = chat.ask(SimpleNamespace(all_card_names=frozenset()), "How could I make this deck faster?")
    assert [t.name for t in reply.tool_trace] == ["get_measured_swaps", "suggest_swap"]
    assert ran == [("get_measured_swaps", {"axis": "clock"}), ("suggest_swap", {"axis": "clock"})]
    assert chat._SWAP_NUDGE not in "".join(s or "" for s in seen)      # no nudge needed
    assert "shallow" in reply.tool_trace[1].result_data["search_depth"]


def test_the_forced_tool_call_message_is_shaped_like_a_real_one(monkeypatch):
    """A synthetic assistant tool_calls message without `"type": "function"` made llama-server
    answer HTTP 500 (live, 2026-10-01), so the shape is pinned."""
    sent = []

    def fake_post(messages, *, model, temperature, max_tokens, timeout=120):
        sent.append(list(messages))
        return [_call("get_measured_swaps", '{"axis": "clock"}'),
                {"role": "assistant", "content": "Run Advise."},
                {"role": "assistant", "content": "I didn't find a measured improvement."}][len(sent) - 1]

    monkeypatch.setattr(chat, "_post_chat", fake_post)
    monkeypatch.setattr(chat, "call_tool", lambda ctx, name, args: ToolResult(
        data={"available": False} if name == "get_measured_swaps" else {"found": True}))
    chat.ask(SimpleNamespace(all_card_names=frozenset()), "How could I make this deck faster?")
    forced = next(m for m in sent[-1] if m.get("tool_calls") and m["tool_calls"][0]["id"].startswith("auto-"))
    tc = forced["tool_calls"][0]
    assert tc["type"] == "function" and tc["function"]["name"] == "suggest_swap"
    assert tc["function"]["arguments"] == '{"axis": "clock"}'


def test_fallback_is_not_forced_for_a_non_swap_question(monkeypatch):
    seen, ran = _drive(
        monkeypatch,
        [_call("get_measured_swaps", '{"axis": "clock"}'),
         {"role": "assistant", "content": "Nothing cached."}],
        lambda name: {"available": False})
    chat.ask(SimpleNamespace(all_card_names=frozenset()), "Tell me about this deck.")
    assert ran == [("get_measured_swaps", {"axis": "clock"})]


def test_fallback_is_forced_once_per_turn_per_axis(monkeypatch):
    seen, ran = _drive(
        monkeypatch,
        [_call("get_measured_swaps", '{"axis": "clock"}'),
         {"role": "assistant", "content": "Run Advise."},
         {"role": "assistant", "content": "Run Advise."}],
        lambda name: {"available": False} if name == "get_measured_swaps" else {"found": True})
    chat.ask(SimpleNamespace(all_card_names=frozenset()), "How could I make this deck faster?")
    assert [r[0] for r in ran].count("suggest_swap") == 1


def test_suggest_swap_is_answered_from_a_cached_full_search_without_running_it(monkeypatch):
    """qwen3 keeps calling suggest_swap; with a cached search for that axis the loop answers
    from it (get_measured_swaps in the trace) and never runs the 4-simulation quick search."""
    seen, ran = _drive(
        monkeypatch,
        [_call("suggest_swap", '{"axis": "ceiling"}'),
         {"role": "assistant", "content": "I didn't find a measured improvement from your collection."}],
        lambda name: {"available": True, "axis": "clock", "improving_swap_found": True})
    reply = chat.ask(SimpleNamespace(all_card_names=frozenset(), advice={"clock": {}}),
                     "How could I make this deck faster?")
    assert ran == [("get_measured_swaps", {"axis": "clock"})]      # routed to clock, quick search skipped
    assert [t.name for t in reply.tool_trace] == ["get_measured_swaps"]
    assert len(seen) == 2


def test_quick_search_fallback_is_flagged_shallow_and_the_miss_is_traced(monkeypatch):
    seen, ran = _drive(
        monkeypatch,
        [_call("suggest_swap", '{"axis": "clock"}'),
         {"role": "assistant", "content": "I didn't find a measured improvement from your collection."}],
        lambda name: ({"available": False, "axis": "clock"} if name == "get_measured_swaps"
                      else {"found": True, "improving_swap_found": False}))

    reply = chat.ask(SimpleNamespace(all_card_names=frozenset()), "How could I make this deck faster?")
    assert ran == [("get_measured_swaps", {"axis": "clock"}), ("suggest_swap", {"axis": "clock"})]
    assert [t.name for t in reply.tool_trace] == ["get_measured_swaps", "suggest_swap"]
    assert reply.tool_trace[0].result_data["available"] is False        # the UI's button trigger
    assert "shallow" in reply.tool_trace[1].result_data["search_depth"]


def test_no_measured_lookup_when_the_swap_has_no_axis_and_no_auto_search(monkeypatch):
    seen, ran = _drive(
        monkeypatch,
        [_call("suggest_swap", "{}"),
         {"role": "assistant", "content": "I didn't find a measured improvement from your collection."}],
        lambda name: {"found": True})
    chat.ask(SimpleNamespace(all_card_names=frozenset()), "What should I cut?")
    assert ran == [("suggest_swap", {})]


# ── /mentor/chat route ───────────────────────────────────────────────────────────────

DECK = "Commander:\n1 Test Commander\n\nDeck:\n30 Forest\n20 Grizzly Bears\n"


@pytest.fixture
def app(tmp_path, make_card, forest, bear, monkeypatch):
    monkeypatch.setenv("MYTHSUITE_DIR", str(tmp_path / "suite"))
    monkeypatch.setattr(server_mod.transcript, "transcript_path", lambda: tmp_path / "t.jsonl")
    commander = make_card("Test Commander", mana_cost="{2}{G}",
                          type_line="Legendary Creature — Beast", color_identity=("G",))
    store = SemanticsStore(authored=tmp_path / "a", compiled=tmp_path / "c")
    return server_mod.create_app(db=CardDb([forest, bear, commander]), store=store,
                                 mentor_cr=_fake_cr(), mentor_rulings_db={})


def test_route_threads_advice_into_the_context(app, monkeypatch):
    captured = {}

    def fake_ask(ctx, question, history=None, **kw):
        captured["advice"] = ctx.advice
        return MentorReply(text="x", gated=True, tool_trace=[])

    monkeypatch.setattr(server_mod.mentor_chat, "ask", fake_ask)
    advice = {"clock": {"result": {"axis": "clock", "suggestions": []}, "computed_at": "t"}}
    resp = TestClient(app).post("/mentor/chat", json={"deck": DECK, "question": "q", "advice": advice})
    assert resp.status_code == 200 and captured["advice"] == advice


def test_route_advice_defaults_to_none(app, monkeypatch):
    captured = {}

    def fake_ask(ctx, question, history=None, **kw):
        captured["advice"] = ctx.advice
        return MentorReply(text="x", gated=True, tool_trace=[])

    monkeypatch.setattr(server_mod.mentor_chat, "ask", fake_ask)
    assert TestClient(app).post("/mentor/chat", json={"deck": DECK, "question": "q"}).status_code == 200
    assert captured["advice"] is None


def test_route_trace_exposes_measured_swaps_availability_only(app, monkeypatch):
    """The UI offers 'Run full swap search' off this flag."""
    trace = [ToolCallRecord("get_measured_swaps", {"axis": "clock"}, {"available": False, "x": 1}),
             ToolCallRecord("suggest_swap", {"axis": "clock"}, {"available": True})]
    monkeypatch.setattr(server_mod.mentor_chat, "ask",
                        lambda ctx, q, history=None, **kw: MentorReply(text="x", gated=True, tool_trace=trace))
    body = TestClient(app).post("/mentor/chat", json={"deck": DECK, "question": "q"}).json()
    assert body["tool_trace"] == [
        {"tool": "get_measured_swaps", "args": {"axis": "clock"}, "available": False},
        {"tool": "suggest_swap", "args": {"axis": "clock"}},
    ]
