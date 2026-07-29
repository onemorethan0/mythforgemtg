"""Navigation & creature comforts for the CLI toolbox.

This module owns the *front door*: the home dashboard, the interactive menu, the doctor
health check, and the decklist browser. The engine and data layers stay untouched; this is
purely how a human finds their way around the 13 commands.

Design notes
------------
- ASCII-only literal text (legacy Windows console is cp1252). Rich auto-downgrades its box
  drawing on legacy terminals, so Panels/Tables are fine; our strings must not be.
- Snappy: the dashboard uses os.stat + single-file reads (ledger, state), never a full
  card-DB parse or a 9k-file glob. `doctor` may take a beat (it loads the DB for an exact
  count) because it is an explicit "check my setup" command.
- The command grouping (COMMAND_GROUPS) is the single source of truth shared by both the
  dashboard command map and the grouped `--help` epilog, so they can never drift.
- The menu dispatches through an injected callable (the real argparse `main`), so an action
  chosen from the menu behaves identically to typing the command.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from mythgauntlet import __version__
from mythgauntlet.config import (
    STRENGTH_API_HOST,
    STRENGTH_API_PORT,
    corpus_dir,
    suite_collection_path,
)
from mythgauntlet.data import scryfall
from mythgauntlet.semantics import compiler
from mythgauntlet.state import get_last_deck

# --- Command grouping: single source of truth for navigation ---------------------------
# (group title, [(command, one-line help)]). Every dispatchable command appears exactly
# once; build_parser() and the dashboard both read this list.
COMMAND_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Evaluate a deck",
        [
            ("analyze", "Power Profile + bracket estimate for a decklist (the headline)"),
            ("advise", "Owned-card swaps that improve an axis, measured (upgrade advisor)"),
            ("combos", "Find combos + one-card-away near-misses (Commander Spellbook)"),
            ("duel", "Simulate 1v1 games between two decks (Tier-2)"),
            ("pod", "Win share in 4-player games vs the corpus (Tier-2 multiplayer)"),
            ("edhplay", "Export to EDHPlay with a chosen art per card (Bulk Import)"),
        ],
    ),
    (
        "Cards & synergy",
        [
            ("info", "Show a card and its rung-1 effect vector"),
            ("edhrec", "EDHREC synergy/inclusion data for a commander"),
        ],
    ),
    (
        "Ratings & corpus",
        [
            ("gauntlet", "Round-robin the corpus -> Bradley-Terry ratings (Tier-2)"),
            ("ladder", "Agent strength ladder: pit search levels head-to-head (Phase 7)"),
            ("benchmark", "Tier-0 analysis across the whole deck corpus"),
            ("decks", "Browse the decklists available to analyze/duel/gauntlet"),
            ("fetch-decks", "Pull reference decks (EDHREC average / Archidekt top)"),
        ],
    ),
    (
        "Data & semantics",
        [
            ("fetch-data", "Download Scryfall bulk card data (one-time, ~150MB)"),
            ("compile-card", "Compile one card to a CCM via the local LLM"),
            ("compile-top", "Compile the top-N EDHREC cards not yet in the ledger"),
            ("ccm-status", "CCM ledger coverage stats"),
        ],
    ),
    (
        "Server & navigation",
        [
            ("serve", "Run the local HTTP strength API (:8020)"),
            ("doctor", "Check your setup (card data, gateways, collection, corpus)"),
            ("home", "Show the status dashboard"),
            ("menu", "Interactive menu to navigate the toolbox"),
            ("completion", "Print a shell-completion script (powershell/bash/zsh/fish)"),
        ],
    ),
]

# Commands the interactive menu omits: itself, and one-off setup that needs a shell arg.
_MENU_EXCLUDE = {"menu", "completion"}

# Commands that take a required positional the interactive menu must prompt for.
_MENU_PROMPTS: dict[str, list[tuple[str, str]]] = {
    # command -> [(prompt label, kind)]; kind "deck" offers the last-deck default
    "analyze": [("Decklist path", "deck")],
    "advise": [("Decklist path", "deck")],
    "combos": [("Decklist path", "deck")],
    "edhplay": [("Decklist path", "deck")],
    "duel": [("First decklist path", "path"), ("Second decklist path", "path")],
    "info": [("Card name", "text")],
    "edhrec": [("Commander name", "text")],
    "compile-card": [("Card name", "text")],
}


# --- Status collection ------------------------------------------------------------------


@dataclass
class SuiteStatus:
    card_data_present: bool = False
    card_data_age_days: float | None = None
    card_data_size_mb: float | None = None
    ccm_authored: int = 0
    ccm_accepted: int = 0
    ccm_quarantined: int = 0
    corpus_decks: int = 0
    collection_present: bool = False
    collection_path: str = ""
    api_up: bool = False
    llm_up: bool = False
    last_deck: str | None = None


def _ping(url: str, timeout: float = 1.2) -> bool:
    try:
        return requests.get(url, timeout=timeout).status_code < 500
    except requests.RequestException:
        return False


def collect_status(*, probe_network: bool = True) -> SuiteStatus:
    """Gather the facts the dashboard/doctor report. Never raises; degrades to defaults.

    probe_network=False skips the API/LLM pings (used by tests to stay offline).
    """
    st = SuiteStatus()

    slim = scryfall.slim_path()
    if slim.exists():
        stat = slim.stat()
        st.card_data_present = True
        st.card_data_age_days = max(0.0, (time.time() - stat.st_mtime) / 86400)
        st.card_data_size_mb = stat.st_size / (1024 * 1024)

    try:
        st.ccm_authored = len(list(compiler.authored_dir().glob("*.json")))
    except OSError:
        pass
    try:
        stats = compiler.Ledger().stats()
        st.ccm_accepted = stats.get("accepted", 0)
        st.ccm_quarantined = stats.get("quarantined", 0)
    except (OSError, ValueError):
        pass

    try:
        st.corpus_decks = len(list(corpus_dir().glob("*.txt")))
    except OSError:
        pass

    coll = suite_collection_path()
    st.collection_path = str(coll)
    st.collection_present = coll.exists()

    st.last_deck = get_last_deck()

    if probe_network:
        st.api_up = _ping(f"http://{STRENGTH_API_HOST}:{STRENGTH_API_PORT}/health")
        st.llm_up = _ping(f"{compiler.DEFAULT_LLM_URL}/v1/models")

    return st


def _age_str(days: float | None) -> str:
    if days is None:
        return "unknown"
    if days < 1:
        return "today"
    if days < 2:
        return "1 day ago"
    return f"{days:.0f} days ago"


def _next_step(st: SuiteStatus) -> str:
    """One actionable suggestion based on detected state."""
    if not st.card_data_present:
        return "Start here: 'mythgauntlet fetch-data' downloads card data (one-time)."
    if st.last_deck:
        return f"Re-run your last analysis: 'mythgauntlet analyze' ({Path(st.last_deck).name})."
    if st.corpus_decks:
        return "Analyze a deck: 'mythgauntlet analyze my_deck.txt' ('decks' to browse the corpus)."
    return "Analyze a deck: 'mythgauntlet analyze my_deck.txt'."


# --- Dashboard --------------------------------------------------------------------------


def render_dashboard(console: Console, *, status: SuiteStatus | None = None) -> None:
    st = status or collect_status()

    def flag(ok: bool, yes: str = "ready", no: str = "missing") -> str:
        return f"[green]{yes}[/green]" if ok else f"[yellow]{no}[/yellow]"

    status_tbl = Table.grid(padding=(0, 2))
    status_tbl.add_column(justify="left", style="bold")
    status_tbl.add_column(justify="left")

    if st.card_data_present:
        age = _age_str(st.card_data_age_days)
        size = f"{st.card_data_size_mb:.0f} MB" if st.card_data_size_mb is not None else "cached"
        card_val = f"{flag(True)}  ({size}, updated {age})"
        if st.card_data_age_days and st.card_data_age_days > 30:
            card_val += "  [yellow]consider fetch-data --force[/yellow]"
    else:
        card_val = flag(False) + "  run 'fetch-data'"
    status_tbl.add_row("Card data", card_val)

    status_tbl.add_row(
        "Semantics (CCM)",
        f"{st.ccm_authored} authored + {st.ccm_accepted} compiled"
        + (f", {st.ccm_quarantined} quarantined" if st.ccm_quarantined else ""),
    )
    corpus_val = f"{st.corpus_decks} decklists" if st.corpus_decks else flag(False, no="empty")
    status_tbl.add_row("Deck corpus", corpus_val)
    coll_flag = flag(st.collection_present, yes="linked", no="none found")
    status_tbl.add_row("Collection", f"{coll_flag}  ({st.collection_path})")
    status_tbl.add_row(
        "Strength API", flag(st.api_up, yes=f"up on :{STRENGTH_API_PORT}", no="not running")
    )
    status_tbl.add_row("LLM gateway", flag(st.llm_up, yes="up", no="not running (compile only)"))
    if st.last_deck:
        status_tbl.add_row("Last deck", Path(st.last_deck).name)

    console.print(
        Panel(
            status_tbl,
            title=f"[bold]MythGauntlet[/bold] {__version__} - deck strength by simulation",
            subtitle="'menu' for interactive - 'doctor' to check setup - '<command> -h' for help",
            border_style="cyan",
        )
    )

    # Command map, grouped by workflow.
    cmd_tbl = Table(
        show_header=True, header_style="bold", title="What you can do", title_justify="left"
    )
    cmd_tbl.add_column("Command")
    cmd_tbl.add_column("Does")
    for group, commands in COMMAND_GROUPS:
        cmd_tbl.add_row(f"[bold cyan]{group}[/bold cyan]", "")
        for name, help_text in commands:
            cmd_tbl.add_row(f"  {name}", help_text)
    console.print(cmd_tbl)

    console.print(f"\n[bold]Next step:[/bold] {_next_step(st)}")


# --- Doctor -----------------------------------------------------------------------------


@dataclass
class Check:
    name: str
    status: str  # "OK" | "WARN" | "FAIL"
    detail: str
    fix: str = ""


def run_checks() -> list[Check]:
    """Environment health checks with actionable fixes. Ordered most-blocking first."""
    checks: list[Check] = []
    st = collect_status(probe_network=True)

    # Card data (blocking for analyze/duel/gauntlet/info).
    if st.card_data_present:
        detail = f"{st.card_data_size_mb:.0f} MB, updated {_age_str(st.card_data_age_days)}"
        try:
            n = len(scryfall.load_card_db())
            detail = f"{n:,} cards, " + detail
        except (FileNotFoundError, RuntimeError):
            pass
        stale = st.card_data_age_days is not None and st.card_data_age_days > 45
        checks.append(
            Check(
                "Card data",
                "WARN" if stale else "OK",
                detail,
                "mythgauntlet fetch-data --force" if stale else "",
            )
        )
    else:
        checks.append(
            Check("Card data", "FAIL", "no Scryfall store", "mythgauntlet fetch-data")
        )

    # serve extra (optional).
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401

        serve_ok, serve_detail, serve_fix = True, "fastapi + uvicorn installed", ""
    except ImportError:
        serve_ok, serve_detail, serve_fix = False, "not installed", 'pip install -e ".[serve]"'
    checks.append(Check("Strength API deps", "OK" if serve_ok else "WARN", serve_detail, serve_fix))

    # Strength API running (optional; any HTTP client can use it).
    checks.append(
        Check(
            f"Strength API (:{STRENGTH_API_PORT})",
            "OK" if st.api_up else "WARN",
            "reachable" if st.api_up else "not running",
            "" if st.api_up else "mythgauntlet serve",
        )
    )

    # LLM gateway (only needed to compile CCMs).
    checks.append(
        Check(
            "LLM gateway",
            "OK" if st.llm_up else "WARN",
            f"reachable at {compiler.DEFAULT_LLM_URL}" if st.llm_up else "not running",
            "" if st.llm_up else r"start E:\llama\start-llama-swap.bat (only needed to compile)",
        )
    )

    # Collection (optional; enables ownership reports).
    checks.append(
        Check(
            "Collection",
            "OK" if st.collection_present else "WARN",
            st.collection_path if st.collection_present else "no collection file found",
            "" if st.collection_present else f"drop a CSV/decklist at {st.collection_path}, "
            "or pass --collection",
        )
    )

    # Corpus (optional; needed by gauntlet/benchmark).
    checks.append(
        Check(
            "Deck corpus",
            "OK" if st.corpus_decks >= 2 else "WARN",
            f"{st.corpus_decks} decklists",
            "" if st.corpus_decks >= 2 else 'mythgauntlet fetch-decks --source archidekt --top 20',
        )
    )

    return checks


def render_doctor(console: Console) -> int:
    checks = run_checks()
    color = {"OK": "green", "WARN": "yellow", "FAIL": "red"}
    tbl = Table(show_header=True, header_style="bold", title="MythGauntlet doctor")
    tbl.add_column("Check")
    tbl.add_column("Status")
    tbl.add_column("Detail", overflow="fold")  # wrap long paths rather than unicode-ellipsis
    for c in checks:
        tbl.add_row(c.name, f"[{color[c.status]}]{c.status}[/{color[c.status]}]", c.detail)
    console.print(tbl)

    fixes = [c for c in checks if c.fix]
    if fixes:
        console.print("\n[bold]Suggested fixes:[/bold]")
        for c in fixes:
            console.print(f"  [{color[c.status]}]{c.status}[/{color[c.status]}] {c.name}: {c.fix}")
    else:
        console.print("\n[green]All set.[/green]")

    return 1 if any(c.status == "FAIL" for c in checks) else 0


# --- Decklist browser -------------------------------------------------------------------


@dataclass
class DeckEntry:
    file: str
    path: str
    name: str = ""
    commander: str = ""
    bracket: int | None = None
    source: str = ""


def list_corpus_decks() -> list[DeckEntry]:
    """Decklists in the corpus, enriched with manifest labels when present."""
    import json

    directory = corpus_dir()
    labels: dict[str, dict] = {}
    manifest = directory / "manifest.json"
    if manifest.exists():
        try:
            with open(manifest, encoding="utf-8") as fh:
                for entry in json.load(fh).get("decks", []):
                    labels[entry["file"]] = entry
        except (OSError, json.JSONDecodeError, KeyError):
            pass

    entries: list[DeckEntry] = []
    for path in sorted(directory.glob("*.txt")):
        meta = labels.get(path.name, {})
        entries.append(
            DeckEntry(
                file=path.name,
                path=str(path),
                name=meta.get("name", ""),
                bracket=meta.get("bracket"),
                source=meta.get("source", ""),
            )
        )
    return entries


def render_decks(console: Console) -> int:
    entries = list_corpus_decks()
    if not entries:
        console.print(
            f"[yellow]No decklists in {corpus_dir()}.[/yellow]\n"
            "Add some with: mythgauntlet fetch-decks --source archidekt --top 20"
        )
        return 0
    tbl = Table(
        show_header=True, header_style="bold", title=f"Decklists in corpus ({len(entries)})"
    )
    tbl.add_column("#", justify="right")
    tbl.add_column("File")
    tbl.add_column("Name / commander")
    tbl.add_column("Bracket", justify="right")
    for i, e in enumerate(entries, 1):
        tbl.add_row(str(i), e.file, (e.name or e.commander or "-")[:44], str(e.bracket or "-"))
    console.print(tbl)
    console.print(
        "\n[dim]Use a path with any deck command, e.g. "
        "'mythgauntlet analyze corpus/decks/<file>'.[/dim]"
    )
    return 0


# --- Interactive menu -------------------------------------------------------------------


@dataclass
class MenuItem:
    number: int
    command: str
    label: str
    group: str


def build_menu() -> list[MenuItem]:
    """Flatten COMMAND_GROUPS into a numbered menu (skips the meta/setup commands)."""
    items: list[MenuItem] = []
    n = 1
    for group, commands in COMMAND_GROUPS:
        for name, help_text in commands:
            if name in _MENU_EXCLUDE:
                continue
            items.append(MenuItem(number=n, command=name, label=help_text, group=group))
            n += 1
    return items


def build_argv(command: str, answers: list[str]) -> list[str]:
    """Assemble the argv for a menu selection. Pure (no IO) so it is unit-testable."""
    argv = [command]
    for a in answers:
        if a:
            argv.append(a)
    return argv


def _prompt(console: Console, label: str, kind: str) -> str | None:
    default = get_last_deck() if kind == "deck" else None
    suffix = f" [{Path(default).name}]" if default else ""
    try:
        raw = console.input(f"  {label}{suffix}: ").strip().strip('"')
    except (EOFError, KeyboardInterrupt):
        return None
    if not raw and default:
        return default
    return raw or None


def run_menu(dispatch: Callable[[list[str]], int], console: Console | None = None) -> int:
    """Interactive loop. `dispatch(argv)` runs a command (inject cli.main).

    Non-interactive stdin (pipe/redirect) falls back to a single dashboard render so the
    call can't hang in CI or when piped.
    """
    console = console or Console()
    if not sys.stdin.isatty():
        render_dashboard(console)
        return 0

    items = build_menu()
    while True:
        render_dashboard(console)
        console.print("\n[bold]Menu[/bold] - type a number, or 'q' to quit:")
        current_group = ""
        for item in items:
            if item.group != current_group:
                current_group = item.group
                console.print(f"  [bold cyan]{current_group}[/bold cyan]")
            console.print(f"    [bold]{item.number:>2}[/bold]  {item.command} - {item.label}")

        try:
            choice = console.input("\n> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return 0
        if choice in ("q", "quit", "exit", "0"):
            return 0
        if not choice.isdigit():
            console.print("[yellow]Enter a number from the list, or 'q'.[/yellow]")
            continue

        selected = next((it for it in items if it.number == int(choice)), None)
        if selected is None:
            console.print("[yellow]No such option.[/yellow]")
            continue

        answers: list[str] = []
        aborted = False
        for label, kind in _MENU_PROMPTS.get(selected.command, []):
            value = _prompt(console, label, kind)
            if value is None:
                console.print("[yellow]Cancelled.[/yellow]")
                aborted = True
                break
            answers.append(value)
        if aborted:
            continue

        if selected.command in ("home", "menu"):
            continue  # already showing the dashboard each loop

        argv = build_argv(selected.command, answers)
        console.print(f"[dim]$ mythgauntlet {' '.join(argv)}[/dim]\n")
        try:
            dispatch(argv)
        except SystemExit as exc:  # commands call _die -> SystemExit; keep the menu alive
            if exc.code:
                console.print(f"[red]Command exited with code {exc.code}.[/red]")
        except Exception as exc:  # noqa: BLE001 - a bad command must not kill the menu
            console.print(f"[red]Error: {exc}[/red]")

        try:
            console.input("\n[dim]Press Enter to return to the menu...[/dim]")
        except (EOFError, KeyboardInterrupt):
            return 0
