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


def test_a_card_name_cannot_crash_the_output(monkeypatch):
    """Printing a card name must never raise, whatever the stdout codec is.

    Windows gives a non-console stdout the locale codepage (cp1252 here), and Magic
    prints names it cannot encode. Compiling one raised UnicodeEncodeError from inside
    console.print AFTER the CCM was saved and the ledger stamped, so the work survived
    but the process died: on 2026-08-05 that killed compile chunk 3/4 at card 219/1400
    on `Hamato Ninpo` (U+014D), and `Bespoke Bo` almost certainly did the same on
    2026-08-02. `Ratonhnhake:ton` (U+A789) was still queued in the stale pool.

    The names below are the real three from the ledger — keep them.
    """
    import io
    import sys

    names = ["Hamato Ninpō", "Bespoke Bō", "Ratonhnhaké꞉ton"]

    raw = io.BytesIO()
    cp1252_stdout = io.TextIOWrapper(raw, encoding="cp1252", newline="")
    monkeypatch.setattr(sys, "stdout", cp1252_stdout)
    monkeypatch.setattr(sys, "stderr", cp1252_stdout)

    # Precondition: this is genuinely the failing configuration, not a no-op test.
    for name in names:
        try:
            cp1252_stdout.write(name)
            raise AssertionError(f"{name!r} was expected to be unencodable in cp1252")
        except UnicodeEncodeError:
            pass

    cli._make_output_lossy()

    for name in names:
        cp1252_stdout.write(f"accepted (219/1400) {name} ops: none\n")  # must not raise
    cp1252_stdout.flush()

    written = raw.getvalue().decode("cp1252")
    assert "accepted (219/1400)" in written
    assert written.count("\n") == len(names), "every line made it out"
