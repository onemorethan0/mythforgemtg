"""CLI state store (last-deck memory). Offline; isolated via MYTHGAUNTLET_DATA."""

from __future__ import annotations

import pytest

from mythgauntlet import state


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    """Point the data dir (where state lives) at a tmp dir so tests don't touch real state."""
    monkeypatch.setenv("MYTHGAUNTLET_DATA", str(tmp_path))
    return tmp_path


def test_missing_state_is_empty(isolated_data):
    assert state.load_state() == {}
    assert state.get_last_deck() is None


def test_save_and_load_round_trip(isolated_data):
    state.save_state(foo="bar", n=3)
    loaded = state.load_state()
    assert loaded["foo"] == "bar"
    assert loaded["n"] == 3


def test_corrupt_state_degrades_to_empty(isolated_data):
    state.state_path().write_text("{not valid json", encoding="utf-8")
    assert state.load_state() == {}  # never raises


def test_last_deck_round_trip_when_file_exists(isolated_data, tmp_path):
    deck = tmp_path / "my_deck.txt"
    deck.write_text("1 Sol Ring\n", encoding="utf-8")
    state.set_last_deck(str(deck))
    assert state.get_last_deck() == str(deck.resolve())


def test_last_deck_ignored_when_path_gone(isolated_data, tmp_path):
    deck = tmp_path / "gone.txt"
    deck.write_text("x", encoding="utf-8")
    state.set_last_deck(str(deck))
    deck.unlink()
    assert state.get_last_deck() is None  # stale path is not offered
