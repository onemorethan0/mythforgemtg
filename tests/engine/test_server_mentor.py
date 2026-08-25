"""`/mentor/chat` (docs/SPEC_deck_mentor.md Phase 2) — offline via injected synthetic
stores AND a stubbed chat loop (mentor.chat.ask talks to a live LLM gateway, which is
not part of what this route itself is responsible for getting right)."""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from mythgauntlet.data.rulings import ComprehensiveRules  # noqa: E402
from mythgauntlet.data.scryfall import CardDb  # noqa: E402
from mythgauntlet.mentor.chat import MentorReply  # noqa: E402
from mythgauntlet.semantics.store import SemanticsStore  # noqa: E402
from mythgauntlet import server as server_mod  # noqa: E402

DECK = """
Commander:
1 Test Commander

Deck:
30 Forest
20 Grizzly Bears
"""


def _fake_cr() -> ComprehensiveRules:
    return ComprehensiveRules(
        effective_date="August 7, 2026", source_url="https://example.invalid",
        rules={"704.5f": "If a creature has toughness 0 or less, it's put into its owner's graveyard."},
        glossary={},
    )


@pytest.fixture
def app_and_db(tmp_path, make_card, forest, bear, monkeypatch):
    monkeypatch.setenv("MYTHSUITE_DIR", str(tmp_path / "suite"))
    commander = make_card(
        "Test Commander", mana_cost="{2}{G}", type_line="Legendary Creature — Beast",
        color_identity=("G",),
    )
    db = CardDb([forest, bear, commander])
    store = SemanticsStore(authored=tmp_path / "a", compiled=tmp_path / "c")
    return db, store


def test_health_reports_mentor_rules_loaded(app_and_db):
    db, store = app_and_db
    app = server_mod.create_app(db=db, store=store, mentor_cr=_fake_cr(), mentor_rulings_db={})
    body = TestClient(app).get("/health").json()
    assert body["mentor_rules_loaded"] is True


def test_health_reports_mentor_rules_not_loaded_when_explicitly_unavailable(app_and_db):
    db, store = app_and_db
    app = server_mod.create_app(db=db, store=store, mentor_cr=None, mentor_rulings_db=None)
    body = TestClient(app).get("/health").json()
    assert body["mentor_rules_loaded"] is False


def test_mentor_chat_503_when_rules_corpus_unavailable(app_and_db):
    db, store = app_and_db
    app = server_mod.create_app(db=db, store=store, mentor_cr=None, mentor_rulings_db=None)
    resp = TestClient(app).post("/mentor/chat", json={"deck": DECK, "question": "hi"})
    assert resp.status_code == 503
    assert "fetch-rules" in resp.json()["detail"]


def test_mentor_chat_400_on_unresolvable_deck(app_and_db):
    db, store = app_and_db
    app = server_mod.create_app(db=db, store=store, mentor_cr=_fake_cr(), mentor_rulings_db={})
    resp = TestClient(app).post(
        "/mentor/chat", json={"deck": "Commander:\n1 Nothing Resolves Here\n", "question": "hi"}
    )
    assert resp.status_code == 400


def test_mentor_chat_happy_path_wraps_the_gated_reply(app_and_db, monkeypatch):
    """The route is a thin wrapper -- it must resolve the deck, build a MentorContext, and
    hand back exactly what mentor.chat.ask returns, unchanged. The LLM call itself is
    stubbed; testing that loop live belongs to the mentor_bench.py smoke test, not here."""
    db, store = app_and_db
    app = server_mod.create_app(db=db, store=store, mentor_cr=_fake_cr(), mentor_rulings_db={})

    captured = {}

    def fake_ask(ctx, question, history=None, *, model="qwen3:14b", **kw):
        captured["question"] = question
        captured["history"] = history
        captured["model"] = model
        captured["deck_card_names"] = ctx.deck_card_names
        return MentorReply(text="Your curve looks fine.", gated=True, tool_trace=[])

    monkeypatch.setattr(server_mod.mentor_chat, "ask", fake_ask)

    resp = TestClient(app).post("/mentor/chat", json={
        "deck": DECK, "question": "How's my curve?", "model": "qwen3:14b",
        "history": [{"role": "user", "content": "hi"}],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["reply"] == "Your curve looks fine."
    assert body["gated"] is True
    assert body["tool_trace"] == []
    assert captured["question"] == "How's my curve?"
    assert captured["model"] == "qwen3:14b"
    assert "Test Commander" in captured["deck_card_names"]


def test_mentor_chat_reports_ungated_fallback(app_and_db, monkeypatch):
    db, store = app_and_db
    app = server_mod.create_app(db=db, store=store, mentor_cr=_fake_cr(), mentor_rulings_db={})

    def fake_ask(ctx, question, history=None, **kw):
        return MentorReply(text="I'm not confident enough to answer that precisely.",
                            gated=False, tool_trace=[], gate_rejections=[("draft", ["reason"])])

    monkeypatch.setattr(server_mod.mentor_chat, "ask", fake_ask)
    resp = TestClient(app).post("/mentor/chat", json={"deck": DECK, "question": "??"})
    assert resp.status_code == 200
    assert resp.json()["gated"] is False
