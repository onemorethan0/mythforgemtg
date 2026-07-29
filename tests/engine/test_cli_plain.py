"""The global --plain / --no-color output mode. Offline."""

from __future__ import annotations

from mythgauntlet import cli


def test_extract_global_flags_is_position_independent():
    assert cli._extract_global_flags(["--plain", "analyze", "d"]) == (True, ["analyze", "d"])
    assert cli._extract_global_flags(["analyze", "d", "--no-color"]) == (True, ["analyze", "d"])
    assert cli._extract_global_flags(["home"]) == (False, ["home"])


def test_apply_plain_makes_output_uncoloured():
    orig_console, orig_err = cli.console, cli.err
    try:
        cli._apply_plain()
        assert cli.console.no_color is True
        assert cli.err.no_color is True
        assert cli.console.is_terminal is False  # behaves like a pipe: no ANSI at all
    finally:
        cli.console, cli.err = orig_console, orig_err  # don't leak into other tests
