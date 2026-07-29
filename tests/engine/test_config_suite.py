"""Suite contract constants: single source of truth, env overrides (offline)."""

from pathlib import Path

from mythgauntlet.cli import build_parser
from mythgauntlet.config import (
    STRENGTH_API_HOST,
    STRENGTH_API_PORT,
    suite_collection_path,
    suite_dir,
)


def test_suite_dir_default_and_override(monkeypatch):
    monkeypatch.delenv("MYTHSUITE_DIR", raising=False)
    assert suite_dir() == Path.home() / "Documents" / "MythSuite"
    assert suite_collection_path().name == "collection.csv"
    monkeypatch.setenv("MYTHSUITE_DIR", r"C:\elsewhere\Suite")
    assert suite_dir() == Path(r"C:\elsewhere\Suite")
    assert suite_collection_path() == Path(r"C:\elsewhere\Suite") / "collection.csv"


def test_serve_parser_defaults_track_config():
    """The CLI's serve defaults must come from the one registry in config.py."""
    args = build_parser().parse_args(["serve"])
    assert args.port == STRENGTH_API_PORT == 8020
    assert args.host == STRENGTH_API_HOST


def test_analyze_parser_has_collection_optout():
    args = build_parser().parse_args(["analyze", "deck.txt", "--no-collection"])
    assert args.no_collection is True
    assert args.collection is None
