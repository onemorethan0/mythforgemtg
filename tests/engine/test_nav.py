"""Navigation surfaces: grouping integrity, status, dashboard, doctor, menu. Offline."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from mythgauntlet import nav
from mythgauntlet.cli import build_parser


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Empty data + suite dirs so card data / collection read as absent, deterministically."""
    monkeypatch.setenv("MYTHGAUNTLET_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("MYTHSUITE_DIR", str(tmp_path / "suite"))
    return tmp_path


def _capture() -> Console:
    return Console(file=StringIO(), width=100)


# --- Grouping is the single source of truth: it must not drift from the parser -----------


def _grouped_commands() -> set[str]:
    return {name for _, cmds in nav.COMMAND_GROUPS for name, _ in cmds}


def _parser_commands() -> set[str]:
    sub = next(
        a for a in build_parser()._actions if a.__class__.__name__ == "_SubParsersAction"
    )
    return set(sub.choices)


def test_every_command_is_grouped_exactly_once():
    flat = [name for _, cmds in nav.COMMAND_GROUPS for name, _ in cmds]
    assert len(flat) == len(set(flat)), "a command appears in more than one group"
    assert _grouped_commands() == _parser_commands(), "grouped help drifted from the parser"


# --- Status collection -------------------------------------------------------------------


def test_collect_status_offline_defaults(isolated):
    st = nav.collect_status(probe_network=False)
    assert st.card_data_present is False  # tmp data dir has no slim store
    assert st.collection_present is False  # tmp suite dir has no collection.csv
    assert st.api_up is False and st.llm_up is False  # network skipped
    assert isinstance(st.corpus_decks, int)


def test_collect_status_sees_a_collection(isolated):
    coll = isolated / "suite"
    coll.mkdir(parents=True)
    (coll / "collection.csv").write_text("Count,Name\n1,Sol Ring\n", encoding="utf-8")
    st = nav.collect_status(probe_network=False)
    assert st.collection_present is True


# --- Dashboard ---------------------------------------------------------------------------


def test_render_dashboard_shows_status_and_commands():
    console = _capture()
    status = nav.SuiteStatus(card_data_present=True, corpus_decks=5, last_deck=None)
    nav.render_dashboard(console, status=status)
    out = console.file.getvalue()
    assert "Card data" in out
    assert "What you can do" in out
    assert "analyze" in out
    assert "Next step" in out


# --- Doctor ------------------------------------------------------------------------------


def test_doctor_fails_without_card_data(isolated, monkeypatch):
    monkeypatch.setattr(nav, "_ping", lambda *a, **k: False)  # no sockets in tests
    console = _capture()
    code = nav.render_doctor(console)
    out = console.file.getvalue()
    assert "Card data" in out and "FAIL" in out
    assert code == 1  # a FAIL check makes doctor return nonzero


# --- Interactive menu (pure parts) -------------------------------------------------------


def test_build_menu_is_contiguous_and_excludes_meta():
    items = nav.build_menu()
    commands = {it.command for it in items}
    assert [it.number for it in items] == list(range(1, len(items) + 1))
    assert "menu" not in commands  # excluded: it's the menu itself
    assert "completion" not in commands  # excluded: one-off setup needing a shell arg
    assert "analyze" in commands


def test_build_argv_skips_blank_answers():
    assert nav.build_argv("analyze", ["deck.txt"]) == ["analyze", "deck.txt"]
    assert nav.build_argv("gauntlet", []) == ["gauntlet"]
    assert nav.build_argv("duel", ["a.txt", "", "b.txt"]) == ["duel", "a.txt", "b.txt"]


def test_run_menu_non_tty_renders_dashboard_without_dispatch(monkeypatch):
    monkeypatch.setattr(nav.sys.stdin, "isatty", lambda: False)
    calls: list = []
    console = _capture()
    code = nav.run_menu(dispatch=lambda argv: calls.append(argv) or 0, console=console)
    assert code == 0
    assert calls == []  # non-interactive: must not run anything, just show the dashboard
    assert "MythGauntlet" in console.file.getvalue()


def test_run_menu_dispatches_selection_then_quits(isolated, monkeypatch):
    monkeypatch.setattr(nav.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(nav, "_ping", lambda *a, **k: False)  # keep the dashboard offline
    console = _capture()
    doctor_num = next(it.number for it in nav.build_menu() if it.command == "doctor")
    # select doctor -> (no prompts) -> press Enter to continue -> quit
    scripted = iter([str(doctor_num), "", "q"])
    monkeypatch.setattr(console, "input", lambda *a, **k: next(scripted))
    calls: list = []
    code = nav.run_menu(dispatch=lambda argv: calls.append(argv) or 0, console=console)
    assert code == 0
    assert ["doctor"] in calls  # the chosen command was dispatched verbatim


# ── the quarantine retry gate ───────────────────────────────────────────────────

def test_retry_quarantined_opens_the_gate_only_for_quarantined_cards():
    """A SCHEMA change cannot move PROMPT_VERSION, so the gate sealed quarantined cards in.

    The quarantine loop is documented as retrying "once the prompt/schema has moved forward",
    but it keys on `prompt_version` alone — so widening the validator left every quarantined
    card permanently unreachable: the fix that would let them pass could never reach them.
    Measured on the live ledger, selection returned **0** targets without the flag and **952**
    with it, all quarantined and none accepted.
    """
    from mythgauntlet.cli import _ledger_entry_blocks
    from mythgauntlet.semantics import compiler

    current = compiler.PROMPT_VERSION
    accepted = {"status": "accepted", "prompt_version": current}
    quarantined = {"status": "quarantined", "prompt_version": current}
    old_quarantine = {"status": "quarantined", "prompt_version": current - 1}

    # an accepted CCM is never re-done, flag or not — that is what keeps this off the 31k
    assert _ledger_entry_blocks(accepted, False) is True
    assert _ledger_entry_blocks(accepted, True) is True
    # a quarantined card at the current version is normally sealed in...
    assert _ledger_entry_blocks(quarantined, False) is True
    # ...and the flag is the only thing that opens it
    assert _ledger_entry_blocks(quarantined, True) is False
    # a quarantined card from an older prompt was always retryable
    assert _ledger_entry_blocks(old_quarantine, False) is False
