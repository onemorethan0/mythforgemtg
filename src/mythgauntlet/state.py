"""Tiny per-user CLI state (last deck analyzed, etc.).

A creature comfort, not engine state: stored as JSON in the gitignored data dir so it
never gets committed and honors the same MYTHGAUNTLET_DATA override tests use. Corrupt or
unreadable state degrades to "no state" — it must never break a command.
"""

from __future__ import annotations

import json
from pathlib import Path

from mythgauntlet.config import data_dir

_STATE_FILENAME = "cli_state.json"


def state_path() -> Path:
    return data_dir() / _STATE_FILENAME


def load_state() -> dict:
    """Read the state dict; return {} on any problem (missing/corrupt/unreadable)."""
    try:
        with open(state_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(**updates: object) -> None:
    """Merge updates into the state file, best-effort (never raises to the caller)."""
    state = load_state()
    state.update(updates)
    try:
        path = state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, ensure_ascii=False, sort_keys=True)
    except OSError:
        pass


def get_last_deck() -> str | None:
    """Path to the most recently analyzed deck, if it still exists on disk."""
    path = load_state().get("last_deck")
    if isinstance(path, str) and path and Path(path).exists():
        return path
    return None


def set_last_deck(path: str) -> None:
    save_state(last_deck=str(Path(path).resolve()))
