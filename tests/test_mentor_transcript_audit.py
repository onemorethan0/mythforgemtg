"""Tests for scripts/mentor_transcript_audit.py's pure analysis core."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from mentor_transcript_audit import HIGH_TOOL_CALL_THRESHOLD, analyze  # noqa: E402


def _turn(turn_id, *, gated=True, gate_rejections=None, tool_calls=1):
    return {
        "event": "turn",
        "turn_id": turn_id,
        "question": f"question for {turn_id}",
        "reply": f"reply for {turn_id}",
        "deck_commander": "Test Commander",
        "deck_card_count": 100,
        "gated": gated,
        "gate_rejections": gate_rejections or [],
        "tool_trace": [{"tool": "lookup_card", "args": {}, "result": {}}] * tool_calls,
    }


def _feedback(turn_id, rating):
    return {"event": "feedback", "turn_id": turn_id, "rating": rating, "note": None}


def test_no_records_gives_empty_result():
    result = analyze([])
    assert result["turns"] == {}
    assert result["false_negatives"] == []
    assert result["caught_attempts"] == []
    assert result["high_tool_use"] == []


def test_gated_and_down_rated_is_a_false_negative():
    records = [_turn("t1", gated=True), _feedback("t1", "down")]
    result = analyze(records)
    assert [t["turn_id"] for t in result["false_negatives"]] == ["t1"]


def test_gated_and_up_rated_is_not_a_false_negative():
    records = [_turn("t1", gated=True), _feedback("t1", "up")]
    result = analyze(records)
    assert result["false_negatives"] == []


def test_ungated_and_down_rated_is_not_a_false_negative():
    # The gate already caught something (gated=False means a rejection happened this
    # turn's final answer still came from an honest-uncertainty fallback) -- a down
    # rating there isn't a gate MISS, it's the gate correctly degrading. Only a turn the
    # gate marked fully verified (gated=True) that a human still rejects is the signal
    # a synthetic bench structurally cannot produce.
    records = [_turn("t1", gated=False), _feedback("t1", "down")]
    result = analyze(records)
    assert result["false_negatives"] == []


def test_turn_with_gate_rejections_is_a_caught_attempt():
    rejections = [{"draft": "a fabricated draft", "reasons": ["unverified card: Fake Card"]}]
    records = [_turn("t1", gate_rejections=rejections)]
    result = analyze(records)
    assert [t["turn_id"] for t in result["caught_attempts"]] == ["t1"]


def test_turn_with_no_gate_rejections_is_not_a_caught_attempt():
    result = analyze([_turn("t1", gate_rejections=[])])
    assert result["caught_attempts"] == []


def test_high_tool_call_count_is_flagged():
    result = analyze([_turn("t1", tool_calls=HIGH_TOOL_CALL_THRESHOLD)])
    assert [t["turn_id"] for t in result["high_tool_use"]] == ["t1"]


def test_low_tool_call_count_is_not_flagged():
    result = analyze([_turn("t1", tool_calls=HIGH_TOOL_CALL_THRESHOLD - 1)])
    assert result["high_tool_use"] == []


def test_turn_without_feedback_is_unrated():
    result = analyze([_turn("t1")])
    assert result["unrated"] == ["t1"]
    assert result["rating_counts"] == {}


def test_last_feedback_event_wins_for_a_turn():
    # A person changing their mind, or a UI double-fire -- the final rating is what
    # matters, not the first one.
    records = [_turn("t1", gated=True), _feedback("t1", "up"), _feedback("t1", "down")]
    result = analyze(records)
    assert result["feedback"]["t1"]["rating"] == "down"
    assert [t["turn_id"] for t in result["false_negatives"]] == ["t1"]
