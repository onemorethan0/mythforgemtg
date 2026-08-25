"""Mentor conversation transcript logging (docs/SPEC_deck_mentor.md, Phase 3 prerequisite).

Phase 3 distills a smaller model from "gated, human-approved transcripts." Phase 1/2
already PRODUCE exactly that data per turn -- `chat.ask()` returns the full tool trace,
the gate's verdict, and every rejected draft with its reasons -- but until this module
existed, nothing on the serving path persisted any of it. The HTTP response didn't even
forward `gate_rejections` to the caller (see `mythgauntlet.server`, pre-2026-08-24). Every
conversation evaporated the moment the response was sent.

This closes that gap: append-only JSONL under `data_dir()` (gitignored, same convention as
every other `data/` module), one record per conversation turn, keyed by a `turn_id` a
later feedback call can reference. Two event types share ONE file rather than living in
two that could drift out of sync:

    "turn"     -- everything chat.ask() produced for one question, INCLUDING
                  gate_rejections. The rejected drafts and why they failed are arguably
                  the single most useful signal here: they show the model's failure
                  modes directly, which a corpus of only-accepted answers never shows.
    "feedback" -- a human rating on a turn_id, recorded separately (a thumbs up/down from
                  the UI, arriving after the turn already happened).

A transcript is not "approved" by the gate alone -- `gated=True` means no fabrication was
CAUGHT, not that the answer was good. Phase 3's actual training corpus is turns where BOTH
`gated=True` and a later `feedback rating=="up"` exist for the same `turn_id`; building
that corpus by joining the two event types is a future `scripts/build_mentor_sft.py`'s
job, once there is enough real usage logged to build from -- not this module's.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from mythgauntlet.config import data_dir
from mythgauntlet.mentor.chat import MentorReply

TRANSCRIPT_FILENAME = "mentor_transcripts.jsonl"


def transcript_path() -> Path:
    return data_dir() / TRANSCRIPT_FILENAME


def _append(record: dict) -> None:
    # A logging failure must never break a chat turn -- this is telemetry, not the
    # feature. Best-effort: if the disk write fails, the turn still returns to the user.
    try:
        with open(transcript_path(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def record_turn(
    *,
    question: str,
    history: list[dict] | None,
    reply: MentorReply,
    model: str,
    deck_name: str | None = None,
    deck_commander: str | None = None,
    deck_card_count: int | None = None,
) -> str:
    """Log one conversation turn. Returns the `turn_id` a later `record_feedback` call
    (or a future SFT-corpus builder) uses to reference it."""
    turn_id = uuid.uuid4().hex
    _append({
        "event": "turn",
        "turn_id": turn_id,
        "timestamp": time.time(),
        "model": model,
        "deck_name": deck_name,
        "deck_commander": deck_commander,
        "deck_card_count": deck_card_count,
        "question": question,
        "history_len": len(history or []),
        "reply": reply.text,
        "gated": reply.gated,
        "tool_trace": [
            {"tool": rec.name, "args": rec.args, "result": rec.result_data}
            for rec in reply.tool_trace
        ],
        "gate_rejections": [
            {"draft": draft, "reasons": reasons} for draft, reasons in reply.gate_rejections
        ],
    })
    return turn_id


VALID_RATINGS = {"up", "down"}


def record_feedback(turn_id: str, rating: str, note: str | None = None) -> None:
    if rating not in VALID_RATINGS:
        raise ValueError(f"rating must be one of {sorted(VALID_RATINGS)}, got {rating!r}")
    _append({
        "event": "feedback",
        "turn_id": turn_id,
        "timestamp": time.time(),
        "rating": rating,
        "note": note,
    })


def load_transcript(path: Path | None = None) -> list[dict]:
    """Every logged record, in order. Tolerates a corrupt trailing line (e.g. a write
    interrupted mid-flush) by skipping it rather than failing the whole read."""
    store = path or transcript_path()
    if not store.exists():
        return []
    records = []
    with open(store, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records
