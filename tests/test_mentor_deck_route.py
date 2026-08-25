"""`_gauntlet_mentor_chat` -- the Forge-side proxy helper for `/api/deck/{job_id}/mentor`
(docs/SPEC_deck_mentor.md Phase 2). Same test depth as its siblings `_gauntlet_advise` /
`_gauntlet_card_impact`, which have no dedicated route-level tests either -- this covers
the actual new logic (the helper) via a mocked `requests.post`, matching how this repo
tests everything else that reaches the MythGauntlet strength API.
"""
from unittest.mock import MagicMock, patch

import server


def _resp(status_code, json_body):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_body
    return r


def test_success_returns_the_engine_json():
    with patch("server.requests.post", return_value=_resp(200, {"reply": "hi", "gated": True})) as m:
        result = server._gauntlet_mentor_chat(
            {"name": "Test Commander"}, [{"name": "Sol Ring", "quantity": 1}], "how's my curve?"
        )
    assert result == {"reply": "hi", "gated": True}
    payload = m.call_args.kwargs["json"]
    assert payload["question"] == "how's my curve?"
    assert "1 Sol Ring" in payload["deck"]
    assert "Test Commander" in payload["deck"]


def test_400_becomes_error_dict():
    with patch("server.requests.post", return_value=_resp(400, {"detail": "no cards resolved"})):
        result = server._gauntlet_mentor_chat({"name": "X"}, [], "q")
    assert result == {"error": "no cards resolved"}


def test_503_from_engine_becomes_error_dict_not_none():
    """A 503 FROM the engine (rulings corpus not fetched) is a real, actionable detail
    message -- distinct from the engine process being unreachable at all (see the
    helper's own docstring), so it must surface as {"error": ...}, not None."""
    with patch("server.requests.post",
               return_value=_resp(503, {"detail": "Run mythgauntlet fetch-rules"})):
        result = server._gauntlet_mentor_chat({"name": "X"}, [], "q")
    assert result == {"error": "Run mythgauntlet fetch-rules"}


def test_connection_failure_returns_none():
    with patch("server.requests.post", side_effect=ConnectionError("refused")):
        result = server._gauntlet_mentor_chat({"name": "X"}, [], "q")
    assert result is None


def test_history_and_themes_and_model_are_threaded_through():
    history = [{"role": "user", "content": "hi"}]
    with patch("server.requests.post", return_value=_resp(200, {})) as m:
        server._gauntlet_mentor_chat(
            {"name": "X"}, [], "q", history=history, model="qwen3:8b", themes=["spellslinger"],
        )
    payload = m.call_args.kwargs["json"]
    assert payload["history"] == history
    assert payload["model"] == "qwen3:8b"
    assert payload["themes"] == ["spellslinger"]


def test_omitted_model_and_themes_are_not_sent():
    """The engine defaults model to qwen3:14b itself; sending None would override that
    default with a literal null instead of letting the engine's own default apply."""
    with patch("server.requests.post", return_value=_resp(200, {})) as m:
        server._gauntlet_mentor_chat({"name": "X"}, [], "q")
    payload = m.call_args.kwargs["json"]
    assert "model" not in payload
    assert "themes" not in payload
