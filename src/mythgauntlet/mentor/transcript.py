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

# This is a log, not a database -- kept simple on purpose. Every turn (including the full
# tool trace and every rejected draft, per the module docstring above) is appended
# forever with no cap, so left alone this file grows without bound. Size-based rotation
# only, no time-based rotation and no compaction: when the CURRENT file would exceed
# MAX_TRANSCRIPT_BYTES, it's renamed aside with a timestamp and a fresh file is started;
# only the newest MAX_ROTATED_FILES rotated files are kept, older ones deleted.
MAX_TRANSCRIPT_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_ROTATED_FILES = 5


def transcript_path() -> Path:
    return data_dir() / TRANSCRIPT_FILENAME


def _rotate_if_needed(path: Path) -> None:
    """Best-effort, like `_append` itself -- a rotation failure must not break a chat
    turn. NOTE: rotation happens at append time, so a turn logged in the last instant
    before a rotation fires moves into the just-rotated file; `turn_exists`/
    `load_transcript` only ever read the CURRENT file. In practice this only matters if
    feedback arrives for a turn exactly as the file crosses 50 MB, which is rare enough
    for a log file that it's an accepted limitation rather than something worth a real
    index over."""
    try:
        if not path.exists() or path.stat().st_size < MAX_TRANSCRIPT_BYTES:
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        rotated = path.with_name(f"{path.stem}.{stamp}{path.suffix}")
        path.rename(rotated)
        siblings = sorted(
            path.parent.glob(f"{path.stem}.*{path.suffix}"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        for old in siblings[MAX_ROTATED_FILES:]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


def _append(record: dict) -> None:
    # A logging failure must never break a chat turn -- this is telemetry, not the
    # feature. Best-effort: if the disk write fails, the turn still returns to the user.
    try:
        path = transcript_path()
        _rotate_if_needed(path)
        with open(path, "a", encoding="utf-8") as fh:
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


def turn_exists(turn_id: str, path: Path | None = None) -> bool:
    """Whether `turn_id` names a turn THIS engine actually logged (an `event: "turn"`
    record) -- the narrow, local check `run_mentor_feedback` makes before recording
    feedback, so a stray/garbled/made-up `turn_id` is rejected rather than silently
    accepted. See that route's own docstring for what this does and does NOT protect
    against (it has no notion of a Forge `job_id`, so it cannot scope a turn_id to a
    particular session -- only confirm the turn was really logged at all)."""
    return any(
        rec.get("event") == "turn" and rec.get("turn_id") == turn_id
        for rec in load_transcript(path)
    )
