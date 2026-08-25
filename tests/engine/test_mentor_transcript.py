"""mentor.transcript -- offline, uses a tmp_path store rather than the real data dir."""

import json
from pathlib import Path

import pytest

from mythgauntlet.mentor import transcript
from mythgauntlet.mentor.chat import MentorReply, ToolCallRecord


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "mentor_transcripts.jsonl"
    monkeypatch.setattr(transcript, "transcript_path", lambda: path)
    return path


def test_record_turn_writes_one_json_line_and_returns_a_turn_id(store):
    reply = MentorReply(
        text="Sol Ring taps for 2.", gated=True,
        tool_trace=[ToolCallRecord(name="lookup_card", args={"name": "Sol Ring"},
                                    result_data={"found": True, "name": "Sol Ring"})],
    )
    turn_id = transcript.record_turn(
        question="What does Sol Ring do?", history=[], reply=reply, model="qwen3:14b",
        deck_name="test", deck_commander="Test Commander", deck_card_count=100,
    )
    assert turn_id
    lines = store.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["event"] == "turn"
    assert rec["turn_id"] == turn_id
    assert rec["gated"] is True
    assert rec["reply"] == "Sol Ring taps for 2."
    assert rec["tool_trace"][0]["tool"] == "lookup_card"
    assert rec["deck_commander"] == "Test Commander"


def test_gate_rejections_are_logged_even_though_the_http_response_never_showed_them(store):
    """The whole point: gate_rejections are the training signal the HTTP layer discarded
    (see the module docstring) -- this is where they now actually go."""
    reply = MentorReply(
        text="honest fallback", gated=False, tool_trace=[],
        gate_rejections=[("a bad draft", ["cites 27, which is not in this turn's tool results"])],
    )
    turn_id = transcript.record_turn(question="q", history=None, reply=reply, model="qwen3:14b")
    rec = json.loads(store.read_text(encoding="utf-8").splitlines()[0])
    assert rec["gated"] is False
    assert rec["gate_rejections"] == [
        {"draft": "a bad draft", "reasons": ["cites 27, which is not in this turn's tool results"]}
    ]
    assert turn_id == rec["turn_id"]


def test_record_feedback_appends_a_separate_event_joined_by_turn_id(store):
    reply = MentorReply(text="x", gated=True, tool_trace=[])
    turn_id = transcript.record_turn(question="q", history=[], reply=reply, model="m")
    transcript.record_feedback(turn_id, "up", note="that helped")
    records = transcript.load_transcript(store)
    assert len(records) == 2
    assert records[1]["event"] == "feedback"
    assert records[1]["turn_id"] == turn_id
    assert records[1]["rating"] == "up"
    assert records[1]["note"] == "that helped"


def test_record_feedback_rejects_invalid_rating(store):
    with pytest.raises(ValueError):
        transcript.record_feedback("some-turn-id", "sideways")


def test_load_transcript_skips_a_corrupt_trailing_line(store):
    store.write_text('{"event": "turn", "turn_id": "a"}\nnot valid json\n', encoding="utf-8")
    records = transcript.load_transcript(store)
    assert records == [{"event": "turn", "turn_id": "a"}]


def test_load_transcript_on_missing_file_returns_empty():
    assert transcript.load_transcript(Path("/no/such/file.jsonl")) == []


def test_a_disk_write_failure_never_raises(store, monkeypatch):
    """Logging is telemetry, not the feature -- a failed write must not break the turn."""
    def boom(*a, **kw):
        raise OSError("disk full")
    monkeypatch.setattr("builtins.open", boom)
    reply = MentorReply(text="x", gated=True, tool_trace=[])
    turn_id = transcript.record_turn(question="q", history=[], reply=reply, model="m")
    assert turn_id  # still returns an id even though nothing was written
