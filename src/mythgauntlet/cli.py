"""Command-line interface and toolbox front door.

argparse wiring for the ~17 commands; the navigation surfaces they route to (home
dashboard, interactive menu, doctor, decks browser) live in `nav.py`. A bare
`mythgauntlet` invocation opens the menu (or prints the dashboard when not a TTY) rather
than erroring, and `--help` lists commands grouped by workflow (see `nav.COMMAND_GROUPS`).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import date
from pathlib import Path

import requests
from rich.console import Console
from rich.table import Table

from mythgauntlet import __version__, completion, nav
from mythgauntlet.config import (
    STRENGTH_API_HOST,
    STRENGTH_API_PORT,
    corpus_dir,
    data_dir,
    suite_collection_path,
)
from mythgauntlet.data import decksources, edhrec, printings, scryfall, spellbook
from mythgauntlet.edhplay import artselect, artsource
from mythgauntlet.edhplay import export as edh_export
from mythgauntlet.edhplay import userscript as edh_userscript
from mythgauntlet.model.card import normalize_name
from mythgauntlet.model.collection import Collection
from mythgauntlet.model.deck import Deck, resolve
from mythgauntlet.ratings import advisor, manabase, metrics
from mythgauntlet.ratings.analysis import analyze_deck, make_determinism_fn
from mythgauntlet.semantics import compiler, tags
from mythgauntlet.semantics.store import SemanticsStore, load_store
from mythgauntlet.sim.tier0 import DEFAULT_ANALYZE_TURNS, SimConfig, simulate
from mythgauntlet.sim.tier2 import DuelConfig, duel
from mythgauntlet.state import get_last_deck, set_last_deck

console = Console()
err = Console(stderr=True)  # warnings/errors -> stderr so --json stdout stays clean JSON


def _apply_plain() -> None:
    """Switch all output to uncoloured, unhighlighted plain text (the --plain / NO_COLOR mode).

    Reassigns the module consoles in place; every command reads these globals at call time,
    so this takes effect for the whole process (and stays sticky across menu re-dispatch).
    """
    # force_terminal=False makes Rich behave as if piped: no colour AND no bold/dim SGR codes,
    # i.e. clean copy-pasteable text even on an interactive terminal.
    global console, err
    console = Console(no_color=True, highlight=False, emoji=False, force_terminal=False)
    err = Console(stderr=True, no_color=True, highlight=False, emoji=False, force_terminal=False)


def _extract_global_flags(argv: list[str]) -> tuple[bool, list[str]]:
    """Pull position-independent global flags out of argv before argparse sees them.

    Returns (plain, remaining_argv). Keeping --plain/--no-color out of the subparsers lets
    them appear anywhere ('analyze deck.txt --plain' as well as '--plain analyze deck.txt').
    """
    plain = False
    rest: list[str] = []
    for tok in argv:
        if tok in ("--plain", "--no-color"):
            plain = True
        else:
            rest.append(tok)
    return plain, rest


def _die(msg: str, code: int = 2):
    err.print(f"[red]{msg}[/red]")
    raise SystemExit(code)


def _nudge(msg: str) -> None:
    """A 'try next' hint. Goes to stderr so --json stdout stays pure JSON."""
    err.print(f"[dim]{msg}[/dim]")


def _deck_path_or_last(deck: str | None) -> str:
    """Resolve an optional deck argument, falling back to the last-analyzed deck."""
    if deck:
        return deck
    last = get_last_deck()
    if last:
        err.print(f"[dim]No deck given; using your last deck: {last}[/dim]")
        return last
    _die(
        "No decklist given and no previous deck remembered.\n"
        "  Try: mythgauntlet analyze my_deck.txt   "
        "(or 'mythgauntlet decks' to browse the corpus)"
    )


def _read_text(path: str) -> str:
    """Read a decklist/collection file, failing with a clean message not a traceback."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        _die(f"Cannot read {path}: {exc}")


def _require_positive(**vals: int) -> None:
    for name, v in vals.items():
        if v is not None and v < 1:
            _die(f"--{name} must be at least 1 (got {v})")


def _semantics_store() -> SemanticsStore:
    """Cached store; surfaces any skipped (malformed) CCM files (invariant #3)."""
    store = load_store()
    if store.skipped:
        err.print(
            f"[yellow]Warning: {len(store.skipped)} CCM file(s) failed to load, skipped "
            f"(semantics coverage understated). First: {store.skipped[0]}[/yellow]"
        )
    return store


def _cmd_fetch_data(args: argparse.Namespace) -> int:
    console.print("[bold]Fetching Scryfall oracle-cards bulk data...[/bold]")
    before = scryfall.bulk_age_days()
    try:
        path = scryfall.fetch_bulk(force=args.force, max_age_days=args.max_age_days)
    except requests.RequestException as exc:
        # Offline is not fatal when we already have a store — the night's remaining
        # phases all read it. It IS worth shouting about, because a silently stale
        # universe is what froze this data for 26 days.
        if scryfall.slim_path().exists():
            console.print(f"[yellow]Bulk refresh failed ({exc}); using the cached store "
                          f"({before:.1f} days old).[/yellow]")
            path = scryfall.slim_path()
        else:
            _die(f"No cached card store and the bulk download failed: {exc}")
    db = scryfall.load_card_db(path)
    age = scryfall.bulk_age_days() or 0.0
    console.print(f"Card store ready: [green]{path}[/green] ({len(db):,} unique cards, "
                  f"{age:.1f} days old)")
    if age > scryfall.MAX_AGE_DAYS:
        console.print(f"[yellow]Card universe is {age:.0f} days stale — cards printed "
                      "since then don't exist to the engine.[/yellow]")
    _nudge("Next: mythgauntlet analyze my_deck.txt   (or 'mythgauntlet menu' to explore)")
    return 0


def _load_db() -> scryfall.CardDb:
    try:
        return scryfall.load_card_db()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(2) from exc


def _cmd_analyze(args: argparse.Namespace) -> int:
    _require_positive(turns=args.turns, runs=args.runs)
    deck_path = _deck_path_or_last(args.deck)
    db = _load_db()
    text = _read_text(deck_path)
    deck = Deck.parse_text(text, name=Path(deck_path).stem)
    resolved = resolve(deck, db)

    if resolved.missing:  # to stderr so --json stdout is pure JSON
        err.print(f"[yellow]Unresolved names ({len(resolved.missing)}):[/yellow]")
        for name in resolved.missing:
            err.print(f"  [yellow]?[/yellow] {name}")
    if not resolved.cards:
        _die("No cards resolved - is this a decklist?")
    set_last_deck(deck_path)  # remembered so a bare 'analyze' re-runs it

    commander = resolved.commanders[0] if resolved.commanders else None
    cfg = SimConfig(turns=args.turns, runs=args.runs, seed=args.seed)

    if args.json:  # lightweight: just the T0 report (no axes/resilience)
        report = metrics.compute(simulate(resolved.cards, commander, cfg), cfg)
        print(json.dumps(dataclasses.asdict(report), indent=2))
        return 0

    # Combos (optional network) feed the bracket's 2-card gate, so fetch before analysis.
    combo_report = None
    two_card = game_ending = 0
    if args.combos:
        names = [(c.name, n) for c, n in resolved.cards]
        try:
            combo_report = spellbook.find_combos(
                names, [c.name for c in resolved.commanders]
            )
            two_card = combo_report.two_card_count
            game_ending = len(spellbook.winning_combos(combo_report))  # any size (incl. 3-card)
        except requests.RequestException as exc:
            err.print(f"[yellow]Commander Spellbook unavailable, skipping combos: {exc}[/yellow]")

    # One shared pipeline (also used by the API) so the surfaces can't drift.
    a = analyze_deck(
        resolved, cfg, _semantics_store(),
        two_card_combos=two_card, game_ending_combos=game_ending,
        combo_report=combo_report,
        combos_checked=args.combos, run_resilience=not args.no_resilience,
    )
    report = a.report
    coverage = a.coverage
    interaction = a.interaction
    ceiling = a.ceiling

    title = deck.name or "deck"
    cmd_label = f" - commander: {commander.name}" if commander else ""
    console.print(
        f"\n[bold]{title}[/bold]{cmd_label}  "
        f"({resolved.card_count} cards, {report.runs:,} games, seed {cfg.seed})"
    )
    console.print(
        "[dim]Tier-0 goldfish measurement at semantics rung 1 - "
        "consistency & curve only; no opponent.[/dim]\n"
    )

    ins = a.insight
    if ins is not None:
        console.print(f"[bold cyan]Deck identity:[/bold cyan] {ins.archetype}")
        console.print(f"[dim]{ins.gameplan}[/dim]")
        if ins.pod_read:
            console.print(f"[bold]Pod fit:[/bold] {ins.pod_read}")
        if ins.strengths:
            body = "; ".join(f"[green]{s}[/green]" for s in ins.strengths)
            console.print(f"[bold]Strengths:[/bold] {body}")
        if ins.weaknesses:
            body = "; ".join(f"[yellow]{w}[/yellow]" for w in ins.weaknesses)
            console.print(f"[bold]Weaknesses:[/bold] {body}")
        console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Consistency score (0-100, provisional)", f"{report.consistency_score:.1f}")
    table.add_row("Kept first 7", f"{report.keep_rate:.1%}")
    table.add_row("Avg mulligans", f"{report.avg_mulligans:.2f}")
    early = min(4, report.turns)
    hits = " ".join(f"T{t + 1}:{v:.0%}" for t, v in enumerate(report.land_hit_by_turn[:early]))
    table.add_row("Land drops hit", hits)
    table.add_row("Curve efficiency (spent/available)", f"{report.curve_efficiency:.1%}")
    if report.avg_commander_turn is not None:
        table.add_row(
            "Commander cast",
            f"turn {report.avg_commander_turn:.1f} avg ({report.commander_cast_rate:.0%} of games)",
        )
    table.add_row("Avg spells cast", f"{report.avg_spells_cast:.1f}")
    table.add_row("Avg cards drawn", f"{report.avg_cards_drawn:.1f}")
    table.add_row(f"Dead cards in hand @T{report.turns}", f"{report.avg_dead_cards:.1f}")
    clock_label = f"Goldfish clock (combat dmg vs {cfg.goldfish_life} life)"
    if report.goldfish_kill_rate > 0 and report.avg_kill_turn is not None:
        table.add_row(
            clock_label,
            f"turn {report.avg_kill_turn:.1f} avg ({report.goldfish_kill_rate:.0%} of games)",
        )
    else:
        table.add_row(
            clock_label,
            f"not reached by T{report.turns} (avg dmg {report.avg_damage_by_turn[-1]:.0f})",
        )
    console.print(table)

    if a.resilience is not None:
        res = a.resilience
        delay = (
            f", +{res.kill_delay_turns:.1f} turns to kill"
            if res.kill_delay_turns is not None else ""
        )
        console.print(
            f"\n[bold]Resilience (T1):[/bold] {res.resilience_score:.0f}/100 "
            f"vs a turn-{a.wipe_turn} board wipe "
            f"(kill rate {res.clean_kill_rate:.0%} -> {res.wiped_kill_rate:.0%}{delay})"
        )

    console.print(
        f"[bold]Interaction:[/bold] {interaction.score:.0f}/100 "
        f"({interaction.answers} answers = {interaction.effective_answers:g} castable-weighted - "
        f"{interaction.spot_removal} removal, "
        f"{interaction.counterspells} counters, {interaction.board_wipes} wipes; "
        f"breadth {interaction.breadth}/3)"
    )
    # Mana base: the one CLOSED-FORM answer in the report (ratings/manabase.py). Reported
    # as a diagnostic, never as a bracket input — the headline is the probability the deck's
    # real source count achieves, not a pass/fail against the no-mulligan floor.
    mb = manabase.analyze(resolved.cards, resolved.commanders)
    if mb.requirements:
        console.print(
            f"[bold]Mana base:[/bold] {mb.consistency:.0%} mean colour consistency "
            f"({', '.join(f'{c}{n}' for c, n in sorted(mb.sources.items()) if n)} sources)"
        )
        for req in mb.worst[:3]:
            if req.probability >= 0.85:
                # Only surface what is ACTUALLY thin. The floor is a no-mulligan bound, so
                # a colour sitting at 0.85-0.90 plays fine once mulligans exist — flagging
                # it would cry wolf on a mana base that needs no work.
                continue
            console.print(
                f"  {req.color}x{req.pips} by T{req.turn}: {req.have} sources -> "
                f"{req.probability:.0%} (e.g. {req.example}); "
                f"{req.need} would reach 90% without mulligans"
            )

    ceiling_kill = (
        f"best games kill T{ceiling.fast_kill_turn:.0f}"
        if ceiling.fast_kill_turn is not None else "no goldfish kill"
    )
    console.print(
        f"[bold]Ceiling:[/bold] {ceiling.score:.0f}/100 "
        f"({ceiling_kill}, {ceiling.nut_kill_rate:.0%} kill by T{ceiling.nut_turn})"
    )
    if a.go_off.goes_off:
        console.print(
            f"  storm/spellslinger go-off: nut draw reaches lethal ~T{a.go_off.earliest_turn} "
            f"(peak {a.go_off.peak_damage} dmg) -- commander-as-engine, off the combat clock"
        )
    if a.overrun.can_alpha_strike:
        console.print(
            f"  go-wide overrun: nut board of {a.overrun.nut_creatures} attackers swings for "
            f"~{a.overrun.alpha_damage} with a one-shot pump -- lethal alpha strike"
        )
    if ins is not None and not a.go_off.goes_off and not a.overrun.can_alpha_strike:
        console.print(f"  [dim]why: {ins.axis_why.get('Ceiling', '')}[/dim]")

    pod = a.pod
    pod_close = (
        f"closes a {pod.opponents + 1}-player pod ~T{pod.pod_close_turn:.0f} "
        f"({pod.pod_close_rate:.0%} of games)"
        if pod.pod_close_turn is not None
        else f"can't reach table-lethal in {pod.opponents + 1}-player (no combat close)"
    )
    console.print(
        f"[bold]Pod (multiplayer):[/bold] {pod.score:.0f}/100 -- {pod_close}; "
        f"duel-close {pod.duel_close_rate:.0%}"
        + ("; game-ending combo closes the table" if pod.via_finisher else "")
    )
    console.print(
        "  [dim]unopposed capacity proxy: can it generate table-lethal pressure at all[/dim]"
    )

    if ins is not None and ins.key_cards:
        console.print("\n[bold]Key cards[/bold] (what drives each role):")
        for kc in ins.key_cards:
            more = f" [dim](+{kc.more} more)[/dim]" if kc.more else ""
            console.print(f"  [bold]{kc.role}:[/bold] " + ", ".join(kc.names) + more)

    game_changers = a.game_changers
    plays_up = " -> plays up toward 3 (Upgraded)" if a.bracket.plays_up else ""
    console.print(
        f"\n[bold]Bracket estimate:[/bold] "
        f"[bold]{a.bracket.bracket}. {a.bracket.label}{plays_up}[/bold] "
        f"(confidence {a.bracket.confidence:.0%})"
    )
    for reason in a.bracket.reasons:
        console.print(f"  - {reason}")

    console.print(
        f"\n[bold]Semantics coverage:[/bold] {coverage.executable_share:.0%} of cards at "
        f"rung >=2 ({coverage.rung3} authored, {coverage.rung2} compiled, "
        f"{coverage.rung1} heuristic) - T0 numbers above use rung-1 heuristics"
    )
    if game_changers:
        console.print(
            f"[bold]Game Changers ({len(game_changers)}):[/bold] "
            + ", ".join(sorted(game_changers))
        )
    if combo_report is not None:
        det_fn = make_determinism_fn(resolved.cards, resolved.commanders)
        _print_combo_summary(
            combo_report, [c.name for c in resolved.commanders], determinism_fn=det_fn
        )

    # When no collection is given, default to the collection file at the standard path
    # (config.suite_collection_path) if it exists. --no-collection opts out.
    collection_path = args.collection
    if not collection_path and not args.no_collection and suite_collection_path().exists():
        collection_path = str(suite_collection_path())
        console.print(f"\n[dim]Using collection: {collection_path}[/dim]")

    if collection_path:
        try:
            col = Collection.load(collection_path)
        except OSError as exc:
            _die(f"Cannot read collection {collection_path}: {exc}")
        owned = 0
        missing: list[tuple[str, int]] = []
        for card, count in resolved.cards + [(c, 1) for c in resolved.commanders]:
            have = min(count, col.owned(card.name))
            owned += have
            if have < count:
                missing.append((card.name, count - have))
        total = resolved.card_count
        console.print(
            f"\n[bold]Collection:[/bold] you own {owned}/{total} cards "
            f"({owned / total:.0%}) - {len(missing)} to acquire"
        )
        for name, need in missing[:15]:
            console.print(f"  [yellow]-[/yellow] {need}x {name}")
        if len(missing) > 15:
            console.print(f"  ... and {len(missing) - 15} more")

    if args.pod:
        deck_name = deck.name or Path(deck_path).stem
        pod_result = _pod_rating_vs_corpus(
            resolved, deck_name, _semantics_store(), db,
            games=args.pod_games, turns=30, life=40, players=4,
            seed=args.seed, no_combos=not args.combos,
        )
        if pod_result is None:
            err.print("[yellow]--pod: no corpus opponents found; skipped.[/yellow]")
        else:
            rating, n_opp = pod_result
            _print_pod_rating(rating, n_opp, deck_name, args.seed, coverage.executable_share)

    mana = Table(show_header=True, header_style="bold", title="Mana development")
    mana.add_column("Turn", justify="right")
    mana.add_column("Sources", justify="right")
    mana.add_column("Available", justify="right")
    mana.add_column("Spent", justify="right")
    for t in range(report.turns):
        mana.add_row(
            str(t + 1),
            f"{report.avg_sources_by_turn[t]:.1f}",
            f"{report.avg_mana_available_by_turn[t]:.1f}",
            f"{report.avg_mana_spent_by_turn[t]:.1f}",
        )
    console.print(mana)
    if not args.combos:
        _nudge("Tip: add --combos to gate the bracket, or 'duel A.txt B.txt' for a matchup.")
    return 0


def _cmd_advise(args: argparse.Namespace) -> int:
    """Owned-card swap suggestions that improve a Power Profile axis (measured, Phase 8)."""
    _require_positive(runs=args.runs, turns=args.turns, top=args.top, max_eval=args.max_eval)
    deck_path = _deck_path_or_last(args.deck)
    db = _load_db()
    resolved = _load_resolved(deck_path, db)
    if not resolved.cards:
        _die("No cards resolved - is this a decklist?")
    set_last_deck(deck_path)

    # Deck colour identity (commander defines it in Commander; else the cards' union).
    ci_source = resolved.commanders or [c for c, _ in resolved.cards]
    deck_ci = set().union(*[set(c.color_identity) for c in ci_source]) if ci_source else set()

    collection_path = args.collection
    if not collection_path and suite_collection_path().exists():
        collection_path = str(suite_collection_path())
    if not collection_path:
        _die(
            "The advisor suggests from cards you OWN, so it needs a collection.\n"
            "  Provide --collection FILE (a CSV or a plain decklist)."
        )
    try:
        col = Collection.load(collection_path)
    except OSError as exc:
        _die(f"Cannot read collection {collection_path}: {exc}")

    in_deck = {c.name for c, _ in resolved.cards} | {c.name for c in resolved.commanders}
    candidates = []
    for owned_name in col.counts:  # normalized names; db.get normalizes on lookup
        card = db.get(owned_name)
        if card is None or card.name in in_deck or card.is_land:
            continue
        if set(card.color_identity) - deck_ci:  # outside the deck's identity
            continue
        candidates.append(card)
    candidates.sort(key=lambda c: (c.edhrec_rank or 10**9))  # try the best owned cards first
    if not candidates:
        _die("No owned cards fit this deck's colours (or they're all already in the deck).")

    cfg = SimConfig(turns=args.turns, runs=args.runs, seed=args.seed)
    console.print(
        f"[dim]Advisor: testing {min(len(candidates), args.max_eval)} owned cards by "
        f"re-simulation (of {len(candidates)} that fit)...[/dim]"
    )
    report = advisor.advise(
        resolved, cfg, _semantics_store(), candidates,
        axis=args.axis, top=args.top, max_eval=args.max_eval, cut_pool=args.cut_pool,
    )
    console.print(
        f"\n[bold]Upgrade advisor[/bold] - target axis: [bold]{report.axis_label}[/bold] "
        f"(deck baseline {report.baseline:.0f}/100)"
    )
    if report.cut:
        console.print(f"[dim]Each swap replaces your weakest card: {report.cut}[/dim]")
    elif report.cut_pool > 1:
        console.print(
            f"[dim]Best cut chosen per card from your {report.cut_pool} weakest "
            f"({report.analyses} re-sims).[/dim]"
        )
    if not report.suggestions:
        console.print(
            f"[yellow]No owned card improved {report.axis_label} "
            f"(evaluated {report.evaluated}).[/yellow]"
        )
        return 0
    table = Table(show_header=True, header_style="bold", title="Owned cards that improve it")
    table.add_column("Add (from your collection)")
    table.add_column("Cut")
    table.add_column(report.axis_label, justify="right")
    table.add_column("Gain", justify="right")
    for s in report.suggestions:
        table.add_row(s.add, s.cut, f"{s.before:.0f} -> {s.after:.0f}", f"+{s.delta:.1f}")
    console.print(table)
    _nudge(
        "Measured by re-simulation (ablation), not popularity. "
        "Use --axis {consistency,speed,resilience,interaction,ceiling} to target one."
    )
    return 0


def _cmd_info(args: argparse.Namespace) -> int:
    db = _load_db()
    card = db.get(args.name)
    if card is None:
        console.print(f"[red]Not found:[/red] {args.name}")
        return 2
    fx = tags.analyze(card)
    console.print(f"[bold]{card.name}[/bold]  {card.mana_cost_str}  (MV {card.mana_value})")
    console.print(f"{card.type_line}")
    if card.oracle_text:
        console.print(f"[dim]{card.oracle_text}[/dim]")
    console.print(f"EDHREC rank: {card.edhrec_rank}")
    if card.game_changer:
        console.print("[bold red]On the WotC Game Changers list[/bold red]")
    console.print(f"Rung-1 effect vector: {fx}")
    return 0


def _print_combo_summary(
    report: spellbook.ComboReport,
    commander_names: list[str] | None = None,
    determinism_fn=None,
) -> None:
    n = len(report.included)
    two = report.two_card_count
    console.print(
        f"\n[bold]Combos (Commander Spellbook):[/bold] {n} in deck"
        f" ({two} two-card), {len(report.almost_included)} one card away"
    )
    if two:
        console.print(
            "[yellow]Two-card combos present - Brackets 1-2 disallow intentional "
            "infinite combos; Bracket 3 allows only late-game ones.[/yellow]"
        )
    # Grade the WINNING combos so the panel says why each matters (terminal vs needs-outlet,
    # pieces, mana, commander-dependent) instead of just listing produced features.
    cmd = frozenset(commander_names or [])
    graded = {
        id(c): spellbook.classify_combo(
            c, cmd, determinism=determinism_fn(c) if determinism_fn is not None else None
        )
        for c in report.included if spellbook.is_winning_combo(c)
    }
    for combo in report.included[:8]:
        line = f"  - {' + '.join(combo.cards)} -> {'; '.join(combo.produces)}"
        console.print(line)
        g = graded.get(id(combo))
        if g is not None:
            console.print(f"      {g.note}")
    if n > 8:
        console.print(f"  ... and {n - 8} more")


def _cmd_combos(args: argparse.Namespace) -> int:
    text = _read_text(args.deck)
    deck = Deck.parse_text(text, name=Path(args.deck).stem)
    cards = [(e.name, e.count) for e in deck.entries]
    commanders = list(deck.commanders)
    db = None
    try:  # canonicalize names when the card store is available (Spellbook wants exact names)
        db = scryfall.load_card_db()
        cards = [(db.get(n).name if db.get(n) else n, c) for n, c in cards]
        commanders = [db.get(n).name if db.get(n) else n for n in commanders]
    except (FileNotFoundError, RuntimeError):
        pass
    try:
        report = spellbook.find_combos(cards, commanders, force=args.force)
    except requests.RequestException as exc:
        _die(f"Commander Spellbook unavailable: {exc}")
    deck_names = {normalize_name(n) for n, _ in cards} | {normalize_name(n) for n in commanders}
    det_fn = None
    if db is not None:  # determinism needs Oracle text; only available with the card store
        card_objs = [(db.get(n), c) for n, c in cards if db.get(n)]
        cmd_objs = [db.get(n) for n in commanders if db.get(n)]
        det_fn = make_determinism_fn(card_objs, cmd_objs)
    _print_combo_summary(report, commanders, determinism_fn=det_fn)
    if report.almost_included:
        table = Table(title="One card away", show_header=True, header_style="bold")
        table.add_column("Add")
        table.add_column("With")
        table.add_column("Result")
        for combo in report.almost_included[: args.top]:
            missing = combo.missing_from(deck_names)
            have = [c for c in combo.cards if c not in missing]
            table.add_row(
                ", ".join(missing) or "-", " + ".join(have), "; ".join(combo.produces)
            )
        console.print(table)
    return 0


def _cmd_edhplay(args: argparse.Namespace) -> int:
    if args.fetch_printings:
        console.print("[bold]Fetching Scryfall default-cards (all printings)...[/bold]")
        path = printings.fetch_bulk(force=args.force)
        db = printings.load_printing_db(path)
        console.print(f"Printings store ready: [green]{path}[/green] "
                      f"({len(db):,} named cards)")
        _nudge("Next: mythgauntlet edhplay my_deck.txt --policy borderless")
        return 0

    deck_path = _deck_path_or_last(args.deck)
    text = _read_text(deck_path)
    deck = Deck.parse_text(text, name=Path(deck_path).stem)
    if not deck.entries and not deck.commanders:
        _die("No cards resolved - is this a decklist?")

    # Canonicalize names against the card store so printing lookups hit (deck files use
    # nicknames / front-face names); fall back to the raw name if the store isn't present.
    try:
        cdb = scryfall.load_card_db()
    except (FileNotFoundError, RuntimeError):
        cdb = None

    def canon(name: str) -> str:
        if cdb is not None:
            c = cdb.get(name)
            if c is not None:
                return c.name
        return name

    try:
        pdb = printings.load_printing_db()
    except FileNotFoundError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        _nudge("Run: mythgauntlet edhplay --fetch-printings   (one-time ~450 MB download)")
        raise SystemExit(2) from exc
    except RuntimeError as exc:
        _die(str(exc))

    overrides = artselect.Overrides()
    if args.art:
        overrides = artselect.parse_overrides(_read_text(args.art))
        for oe in overrides.errors:
            err.print(f"[yellow]art file line {oe.line_no}: {oe.reason}[/yellow] "
                      f"[dim]{oe.text}[/dim]")

    main_entries = [(canon(e.name), e.count) for e in deck.entries]
    cmd_entries = [(canon(n), 1) for n in deck.commanders]
    kw = dict(policy=args.policy, overrides=overrides, seed=args.seed,
              paper_only=not args.include_digital, lang=args.lang)
    main_choices = artselect.select_arts(main_entries, pdb, **kw)
    cmd_choices = artselect.select_arts(cmd_entries, pdb, **kw)

    if args.json:
        body = edh_export.to_api_body(main_choices, cmd_choices)
        payload = json.dumps(body, ensure_ascii=False, indent=2)
    else:
        payload = edh_export.to_bulk_text(
            main_choices, cmd_choices, deck_name=deck.name, annotate=not args.no_notes
        )

    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        console.print(f"Wrote [green]{args.out}[/green]")
    else:
        # Pure payload to stdout (pasteable / pipeable); summary goes to stderr.
        print(payload)

    # Optional: generate a Tampermonkey userscript that shows custom card art on EDHPlay.
    art_spec = args.art_source or (f"mythforge:{args.myth_job}" if args.myth_job else None)
    if art_spec:
        if not args.userscript:
            _die("--art-source/--myth-job needs --userscript FILE to write the userscript to.")
        try:
            art = artsource.resolve(art_spec, base_url=args.myth_url, embed=args.embed)
        except requests.RequestException as exc:
            _die(f"Could not reach the art source ({art_spec}): {exc}")
        except (ValueError, OSError) as exc:
            _die(str(exc))
        deck_names = [n for n, _ in cmd_entries] + [n for n, _ in main_entries]
        result = edh_userscript.build_userscript(
            deck_names, art, pdb, title=f"MythForge art: {deck.name or 'deck'}"
        )
        Path(args.userscript).write_text(result.text, encoding="utf-8")
        console.print(f"Wrote userscript [green]{args.userscript}[/green] "
                      f"({len(result.matched)} cards, {result.uuid_count} printings mapped)")
        if art.missing_render:
            err.print(f"[yellow]MythForge has {len(art.missing_render)} card(s) not yet "
                      f"rendered (no custom art): {', '.join(art.missing_render[:5])}"
                      f"{'...' if len(art.missing_render) > 5 else ''}[/yellow]")
        if result.no_art:
            err.print(f"[dim]{len(result.no_art)} deck card(s) have no custom art "
                      f"(shown as their normal printing).[/dim]")
        if result.unmatched_art:
            err.print(f"[yellow]{len(result.unmatched_art)} art image(s) didn't match any "
                      f"deck card by name (check naming): "
                      f"{', '.join(result.unmatched_art[:5])}"
                      f"{'...' if len(result.unmatched_art) > 5 else ''}[/yellow]")
        _nudge("Install the .user.js in Tampermonkey, then open EDHPlay. Keep MythForge "
               "running at " + args.myth_url + " (unless you used --embed).")

    summary = edh_export.summarize(main_choices, cmd_choices)
    err.print(
        f"[dim]{summary.pinned}/{summary.total} cards art-pinned; "
        f"{summary.default} left to EDHPlay default; {summary.unknown} unknown.[/dim]"
    )
    for c in summary.fallbacks:
        err.print(f"[yellow]![/yellow] {c.name}: {c.note}")
    for c in summary.unknowns:
        err.print(f"[yellow]?[/yellow] {c.name}: not in printings store (imported by name)")
    if not args.out:
        _nudge("Paste the above into EDHPlay: Create Deck -> Bulk Import "
               "(commander is chosen at deck creation).")
    return 0


def _cmd_fetch_decks(args: argparse.Namespace) -> int:
    out_dir = Path(args.out) if args.out else corpus_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    fetched: list[decksources.FetchedDeck] = []

    try:
        if args.commander:
            db = _load_db()
            card = db.get(args.commander)
            name = card.name if card else args.commander
            fetched.append(decksources.fetch_edhrec_average(name))
        elif args.source == "archidekt":
            metas = decksources.archidekt_top(
                page_size=args.top, order=args.order, bracket=args.bracket
            )
            for meta in metas:
                # Wild deck names carry emoji; the legacy console is cp1252 (ASCII-only
                # invariant) — sanitize the PRINT, never the stored decklist.
                safe_name = meta.name.encode("ascii", "replace").decode("ascii")
                console.print(
                    f"[dim]fetching[/dim] {safe_name} (id {meta.id}, {meta.view_count:,} views"
                    + (f", bracket {meta.edh_bracket}" if meta.edh_bracket else "")
                    + ")"
                )
                fetched.append(decksources.fetch_archidekt_deck(meta.id))
        else:
            _die("Specify --commander NAME (EDHREC) or --source archidekt.")
    except requests.RequestException as exc:
        _die(f"Deck source unavailable: {exc}")

    manifest_path = out_dir / "manifest.json"
    manifest = {"decks": []}
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    by_file = {entry["file"]: entry for entry in manifest.get("decks", [])}

    for deck in fetched:
        parsed = Deck.parse_text(deck.text)
        if not parsed.commanders or not (95 <= parsed.total_cards <= 102):
            console.print(
                f"[yellow]skipped[/yellow] {deck.name.encode('ascii', 'replace').decode('ascii')}: "
                f"{len(parsed.commanders)} commander(s), {parsed.total_cards} cards "
                "(not a standard Commander list)"
            )
            continue
        filename = f"{deck.slug}.txt"
        (out_dir / filename).write_text(deck.text, encoding="utf-8", newline="\n")
        by_file[filename] = {
            "file": filename,
            "name": deck.name,
            "source": deck.source,
            "bracket": deck.bracket,
            "fetched": date.today().isoformat(),
        }
        console.print(f"[green]wrote[/green] {out_dir / filename}")

    manifest["decks"] = sorted(by_file.values(), key=lambda e: e["file"])
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    console.print(f"manifest: {manifest_path} ({len(manifest['decks'])} decks)")
    return 0


def _llm_client() -> compiler.LlamaSwapClient:
    client = compiler.LlamaSwapClient()
    if not client.available():
        console.print(
            f"[red]LLM gateway not reachable at {client.base_url}.[/red] "
            "Start llama-swap (E:\\llama\\start-llama-swap.bat) and retry."
        )
        raise SystemExit(2)
    return client


def _compile_cards(cards: list, keep_on_failure: bool = False) -> int:
    """Compile each card, recording status in the ledger and writing accepted CCMs.

    keep_on_failure guards the REFRESH path (recompiling cards that are already
    accepted at an older prompt version). A refresh must never be a downgrade: if
    the new attempt fails the gates, the existing accepted entry is restored, so a
    card that works today can't be demoted to quarantined by a worse roll. Without
    it, `ledger.record` overwrites unconditionally while `save_compiled` is skipped
    — leaving the ledger saying "quarantined" with a stale accepted CCM still on
    disk (a desync, not just a loss).
    """
    client = _llm_client()
    exemplars = compiler.load_exemplars()
    ledger = compiler.Ledger()
    accepted = quarantined = kept = 0
    for i, card in enumerate(cards, 1):
        prior = ledger.get(card.name) if keep_on_failure else None
        result = compiler.compile_card(card, client.complete, exemplars)
        ledger.record(result, client.model)
        if result.status == "accepted" and result.doc is not None:
            compiler.save_compiled(card, result.doc)
            ledger.save()
            accepted += 1
            console.print(
                f"[green]accepted[/green] ({i}/{len(cards)}) {card.name} "
                f"[dim]ops: {', '.join(result.ops) or 'none'} "
                f"(attempt {result.attempts})[/dim]"
            )
        elif prior is not None and prior["status"] == "accepted":
            # Refresh miss: keep the older-but-working CCM and its ledger entry.
            ledger.entries[normalize_name(card.name)] = prior
            ledger.save()
            kept += 1
            console.print(
                f"[dim]kept v{prior.get('prompt_version')} ({i}/{len(cards)}) "
                f"{card.name} — refresh failed gates, prior CCM retained[/dim]"
            )
        else:
            ledger.save()
            quarantined += 1
            console.print(f"[yellow]quarantined[/yellow] ({i}/{len(cards)}) {card.name}")
            for err in result.errors[:3]:
                console.print(f"    [dim]{err}[/dim]")
    tail = f", {kept} kept at prior version" if kept else ""
    console.print(
        f"\n[bold]Done:[/bold] {accepted} accepted, {quarantined} quarantined{tail}. "
        f"Ledger: {compiler.ledger_path()}"
    )
    return 0


def _cmd_compile_card(args: argparse.Namespace) -> int:
    db = _load_db()
    card = db.get(args.name)
    if card is None:
        console.print(f"[red]Not found:[/red] {args.name}")
        return 2
    existing = compiler.Ledger().get(card.name)
    if existing and existing["status"] == "accepted" and not args.force:
        console.print(f"{card.name} already accepted in ledger (use --force to recompile).")
        return 0
    return _compile_cards([card])


def _cmd_compile_top(args: argparse.Namespace) -> int:
    db = _load_db()
    ledger = compiler.Ledger()
    ranked = sorted(
        (
            c
            for c in {id(x): x for x in db._by_name.values()}.values()
            if c.edhrec_rank is not None and not c.has_type("Basic")
        ),
        key=lambda c: c.edhrec_rank,
    )
    authored = compiler.authored_names()
    targets = []
    for card in ranked:
        if len(targets) >= args.count:
            break
        if normalize_name(card.name) in authored:
            continue  # already rung 3
        entry = ledger.get(card.name)
        if entry and not args.force:
            # accepted cards stand; quarantined cards get retried once the prompt/schema
            # has moved forward (that's the whole point of the quarantine loop)
            if entry["status"] == "accepted":
                continue
            if entry.get("prompt_version") == compiler.PROMPT_VERSION:
                continue
        targets.append(card)

    if not targets and args.refresh_stale:
        # The new-card pool is exhausted (as of 2026-07-28 the ledger covers every
        # EDHREC-ranked non-basic card except the 17 hand-authored ones), so the
        # remaining work is UPGRADING cards accepted under an older prompt. The
        # normal loop above can't see them: `status == "accepted"` short-circuits
        # regardless of prompt_version, so a card compiled at v5 stays at v5
        # forever even though the compiler has improved seven revisions since.
        # Oldest prompt version first, then EDHREC rank — the weakest CCMs on the
        # most-played cards get fixed first.
        stale = []
        for card in ranked:
            if normalize_name(card.name) in authored:
                continue
            entry = ledger.get(card.name)
            if not entry or entry["status"] != "accepted":
                continue
            version = entry.get("prompt_version") or 0
            if version < compiler.PROMPT_VERSION:
                stale.append((version, card))
        stale.sort(key=lambda vc: (vc[0], vc[1].edhrec_rank))
        targets = [card for _, card in stale[: args.count]]
        if targets:
            spread = sorted({v for v, _ in stale[: args.count]})
            console.print(
                f"New-card pool empty; refreshing {len(targets)} of {len(stale)} cards "
                f"accepted at prompt v{spread} (current v{compiler.PROMPT_VERSION}). "
                "A failed refresh keeps the existing CCM."
            )
            return _compile_cards(targets, keep_on_failure=True)

    if not targets:
        console.print("Nothing to compile (all top cards already in ledger).")
        return 0
    console.print(
        f"Compiling {len(targets)} cards (top of EDHREC rank, not yet accepted)..."
    )
    return _compile_cards(targets)


def _cmd_ccm_status(args: argparse.Namespace) -> int:
    ledger = compiler.Ledger()
    stats = ledger.stats()
    total = sum(stats.values())
    console.print(f"[bold]CCM ledger:[/bold] {total} cards")
    for status, count in sorted(stats.items()):
        console.print(f"  {status}: {count}")
    authored = len(list(compiler.authored_dir().glob("*.json")))
    compiled = len(list(compiler.compiled_dir().glob("*.json")))
    console.print(f"  rung-3 authored exemplars: {authored}")
    console.print(f"  rung-2 compiled store: {compiled}")
    op_counts: dict[str, int] = {}
    for entry in ledger.entries.values():
        for op in entry.get("ops", []):
            op_counts[op] = op_counts.get(op, 0) + 1
    if op_counts:
        top_ops = sorted(op_counts.items(), key=lambda kv: -kv[1])[:12]
        console.print("  top ops: " + ", ".join(f"{op}({n})" for op, n in top_ops))
    authored_set = compiler.authored_names()
    quarantined = [
        e["name"] for e in ledger.entries.values()
        if e["status"] == "quarantined" and normalize_name(e["name"]) not in authored_set
    ]
    if quarantined:
        console.print(
            f"  hand-authoring worklist: {', '.join(quarantined[:10])}"
            + (" ..." if len(quarantined) > 10 else "")
        )
    return 0


def _cmd_benchmark(args: argparse.Namespace) -> int:
    """Run Tier-0 analysis over every corpus deck; check axis separation by bracket."""
    db = _load_db()
    deck_dir = Path(args.dir) if args.dir else corpus_dir()
    manifest_path = deck_dir / "manifest.json"
    labels: dict[str, int | None] = {}
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as fh:
            for entry in json.load(fh).get("decks", []):
                labels[entry["file"]] = entry.get("bracket")

    deck_files = sorted(deck_dir.glob("*.txt"))
    if not deck_files:
        console.print(f"[red]No decklists (*.txt) found in {deck_dir}[/red]")
        return 2

    cfg = SimConfig(turns=args.turns, runs=args.runs, seed=args.seed)
    rows = []
    for path in deck_files:
        deck = Deck.parse_text(path.read_text(encoding="utf-8"), name=path.stem)
        resolved = resolve(deck, db)
        if not resolved.cards or not resolved.commanders:
            console.print(f"[yellow]skipped[/yellow] {path.name}")
            continue
        runs = simulate(resolved.cards, resolved.commanders[0], cfg)
        report = metrics.compute(runs, cfg)
        gc = sum(1 for c, _ in resolved.cards if c.game_changer) + sum(
            1 for c in resolved.commanders if c.game_changer
        )
        rows.append(
            {
                "file": path.name,
                "commander": resolved.commanders[0].name,
                "bracket": labels.get(path.name),
                "consistency": round(report.consistency_score, 1),
                "kill_rate": round(report.goldfish_kill_rate, 3),
                "avg_kill_turn": (
                    round(report.avg_kill_turn, 2) if report.avg_kill_turn else None
                ),
                "game_changers": gc,
                "avg_spells_cast": round(report.avg_spells_cast, 1),
                "avg_cards_drawn": round(report.avg_cards_drawn, 1),
            }
        )

    out_path = data_dir() / f"benchmark_{date.today().isoformat()}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"config": dataclasses.asdict(cfg), "rows": rows}, fh, indent=2)

    rows.sort(key=lambda r: (-(r["bracket"] or 0), -r["consistency"]))
    table = Table(title=f"Corpus benchmark ({len(rows)} decks, T0)", header_style="bold")
    for col, justify in [
        ("Deck", "left"), ("Bracket", "right"), ("Consist.", "right"),
        ("Kill %", "right"), ("Kill turn", "right"), ("GCs", "right"), ("Drawn", "right"),
    ]:
        table.add_column(col, justify=justify)
    for r in rows[: args.show]:
        table.add_row(
            r["commander"][:32],
            str(r["bracket"] or "-"),
            f"{r['consistency']:.1f}",
            f"{r['kill_rate']:.0%}",
            f"{r['avg_kill_turn'] or '-'}",
            str(r["game_changers"]),
            f"{r['avg_cards_drawn']:.1f}",
        )
    console.print(table)

    labeled = [r for r in rows if r["bracket"]]
    if labeled:
        console.print("\n[bold]Axis means by bracket label:[/bold]")
        for bracket in sorted({r["bracket"] for r in labeled}):
            grp = [r for r in labeled if r["bracket"] == bracket]
            console.print(
                f"  Bracket {bracket} (n={len(grp)}): "
                f"consistency {sum(r['consistency'] for r in grp) / len(grp):.1f}, "
                f"kill rate {sum(r['kill_rate'] for r in grp) / len(grp):.0%}, "
                f"GCs {sum(r['game_changers'] for r in grp) / len(grp):.1f}"
            )
    console.print(f"\nfull results: {out_path}")
    return 0


def _load_resolved(path: str, db: scryfall.CardDb):
    text = _read_text(path)
    deck = Deck.parse_text(text, name=Path(path).stem)
    resolved = resolve(deck, db)
    if resolved.missing:
        console.print(
            f"[yellow]{Path(path).name}: {len(resolved.missing)} unresolved names "
            f"(first: {resolved.missing[0]})[/yellow]"
        )
    return resolved


def _winning_combos(resolved) -> tuple[frozenset[str], ...]:
    """Best-effort game-ending combos for a deck (network; empty if offline/absent)."""
    try:
        report = spellbook.find_combos(
            [(c.name, n) for c, n in resolved.cards],
            [c.name for c in resolved.commanders],
        )
    except Exception:  # noqa: BLE001 - offline / API hiccup degrades to no combos
        return ()
    return tuple(spellbook.winning_combos(report))


def _cmd_duel(args: argparse.Namespace) -> int:
    _require_positive(games=args.games, turns=args.turns)
    db = _load_db()
    res_a = _load_resolved(args.deck_a, db)
    res_b = _load_resolved(args.deck_b, db)
    if not res_a.cards or not res_b.cards:
        _die("Both decks must resolve to cards.")
    store = _semantics_store()
    combos_a = () if args.no_combos else _winning_combos(res_a)
    combos_b = () if args.no_combos else _winning_combos(res_b)
    cfg = DuelConfig(
        games=args.games, seed=args.seed, max_turns=args.turns, start_life=args.life,
        agent_a=args.agent_a, agent_b=args.agent_b, mcts_iterations=args.mcts_iters,
    )
    result = duel(
        res_a.cards, res_a.commanders[0] if res_a.commanders else None,
        res_b.cards, res_b.commanders[0] if res_b.commanders else None,
        cfg, store=store, combos_a=combos_a, combos_b=combos_b,
    )
    name_a, name_b = Path(args.deck_a).stem, Path(args.deck_b).stem
    cov_a = store.coverage(res_a.cards, res_a.commanders)
    cov_b = store.coverage(res_b.cards, res_b.commanders)
    console.print(
        f"\n[bold]Duel (Tier-2 MVP):[/bold] {name_a} vs {name_b} - "
        f"{result.games} games, seed {cfg.seed}, {cfg.start_life} life, "
        f"cap {cfg.max_turns} turns"
    )
    if cfg.agent_a != "greedy" or cfg.agent_b != "greedy":
        console.print(f"[dim]Agents: {name_a}={cfg.agent_a}, {name_b}={cfg.agent_b}[/dim]")
    console.print(
        "[dim]Battlecruiser fidelity: reactive counters + instant removal modeled; "
        "profiles at semantics "
        f"coverage {cov_a.executable_share:.0%} / {cov_b.executable_share:.0%}.[/dim]"
    )
    table = Table(show_header=True, header_style="bold")
    table.add_column("Deck")
    table.add_column("Wins", justify="right")
    table.add_column("Win rate", justify="right")
    table.add_row(name_a, str(result.wins_a), f"{result.winrate_a:.1%}")
    table.add_row(name_b, str(result.wins_b), f"{result.wins_b / result.games:.1%}")
    if result.draws:
        table.add_row("(draws/adjudicated ties)", str(result.draws), "")
    console.print(table)
    combo_note = ""
    if combos_a or combos_b:
        combo_note = (
            f"; {result.combo_wins} by assembled combo "
            f"({len(combos_a)}/{len(combos_b)} game-ending combos detected)"
        )
    console.print(
        f"avg game length {result.avg_turns:.1f} turns; {result.decked_losses} games "
        f"ended by decking{combo_note}"
    )
    return 0


def _pod_rating_vs_corpus(
    resolved, deck_name, store, db, *,
    games: int, turns: int, life: int, players: int, seed: int, no_combos: bool,
    deck_dir: str | None = None,
):
    """Run the pod meta-rating for `resolved` against the corpus field. Returns
    (PodRating, opponent_count) or None if no opponent decks resolve. Shared by `pod` and
    `analyze --pod` so the two surfaces can't drift."""
    from mythgauntlet.ratings.pod import pod_winrate, prepare_seat

    field_dir = Path(deck_dir) if deck_dir else corpus_dir()
    field_files = [p for p in sorted(field_dir.glob("*.txt")) if p.stem != deck_name]
    if not field_files:
        return None

    def _seat(res):
        combos = () if no_combos else _winning_combos(res)
        cmdr = res.commanders[0] if res.commanders else None
        return prepare_seat(res.cards, cmdr, store, combos)

    opponents = []
    for path in field_files:
        res = _load_resolved(str(path), db)
        if res.cards:
            opponents.append(_seat(res))
    if not opponents:
        return None
    cfg = DuelConfig(max_turns=turns, start_life=life)
    rating = pod_winrate(
        _seat(resolved), opponents, cfg, games=games, seed=seed, pod_size=players,
    )
    return rating, len(opponents)


def _print_pod_rating(rating, n_opponents, deck_name, seed, coverage_share) -> None:
    verdict = (
        "above pod-average" if rating.lift > 0.02
        else "below pod-average" if rating.lift < -0.02
        else "about pod-average"
    )
    console.print(
        f"\n[bold]Pod rating (Tier-2 multiplayer):[/bold] {deck_name} in "
        f"{rating.pod_size}-player games vs {n_opponents} corpus decks - "
        f"{rating.games} pods, seed {seed}"
    )
    console.print(
        f"[bold]Win rate {rating.winrate:.1%}[/bold] "
        f"({rating.wins}/{rating.games}) vs a {rating.baseline:.0%} even-pod baseline "
        f"-> {rating.lift:+.1%} = [bold]{verdict}[/bold]"
    )
    console.print(
        "[dim]Greedy agents; multiplayer engine (threat-focus combat, each-opponent effect "
        f"scaling). Semantics coverage {coverage_share:.0%}. Death-trigger drains, pod "
        "reactions + politics are not yet modeled (docs/SIMULATION.md).[/dim]"
    )


def _cmd_pod(args: argparse.Namespace) -> int:
    """Rate a deck by its WIN SHARE in N-player pods vs the corpus field (Tier-2 multiplayer)."""
    _require_positive(games=args.games, turns=args.turns, players=args.players)
    if args.players < 2:
        _die("A pod needs at least 2 players.")
    db = _load_db()
    store = _semantics_store()
    resolved = _load_resolved(args.deck, db)
    if not resolved.cards:
        _die("The deck must resolve to cards.")
    deck_name = Path(args.deck).stem
    result = _pod_rating_vs_corpus(
        resolved, deck_name, store, db,
        games=args.games, turns=args.turns, life=args.life, players=args.players,
        seed=args.seed, no_combos=args.no_combos, deck_dir=args.dir,
    )
    if result is None:
        _die(f"No opponent decklists resolved in {args.dir or corpus_dir()} (need at least one).")
    rating, n_opponents = result
    cov = store.coverage(resolved.cards, resolved.commanders)
    _print_pod_rating(rating, n_opponents, deck_name, args.seed, cov.executable_share)
    return 0


def _cmd_ladder(args: argparse.Namespace) -> int:
    """Agent strength ladder: pit search levels head-to-head to confirm more search wins."""
    from mythgauntlet.ratings.ladder import is_monotone, run_ladder
    from mythgauntlet.sim.tier2 import prepare_deck

    _require_positive(games=args.games, turns=args.turns)
    levels = [s.strip() for s in args.levels.split(",") if s.strip()]
    if len(levels) < 2:
        _die("--levels needs at least two agent levels, e.g. greedy,mcts:100,mcts:1000")
    db = _load_db()
    store = _semantics_store()
    res_a = _load_resolved(args.deck_a, db)
    res_b = _load_resolved(args.deck_b, db) if args.deck_b else res_a  # mirror by default
    if not res_a.cards or not res_b.cards:
        _die("Deck(s) must resolve to cards.")
    combos_a = () if args.no_combos else _winning_combos(res_a)
    combos_b = () if args.no_combos else _winning_combos(res_b)
    a = prepare_deck("a", res_a.cards, res_a.commanders[0] if res_a.commanders else None,
                     store, combos_a)
    b = prepare_deck("b", res_b.cards, res_b.commanders[0] if res_b.commanders else None,
                     store, combos_b)

    mirror = args.deck_b is None
    matchup = (
        f"mirror of {Path(args.deck_a).stem}" if mirror
        else f"{Path(args.deck_a).stem} vs {Path(args.deck_b).stem}"
    )
    console.print(
        f"[bold]Strength ladder:[/bold] {' < '.join(levels)} - {matchup}, "
        f"{args.games} games/pair, seed {args.seed}"
    )
    matches = run_ladder(a, b, levels, games=args.games, seed=args.seed,
                         max_turns=args.turns, rollout_depth=args.rollout_depth)
    table = Table(show_header=True, header_style="bold")
    table.add_column("Stronger")
    table.add_column("Weaker")
    table.add_column("Record", justify="right")
    table.add_column("Win rate", justify="right")
    for m in matches:
        rate = m.strong_winrate
        tag = "[green]" if rate >= 0.55 else "[yellow]"
        table.add_row(m.strong, m.weak, f"{m.strong_wins}-{m.weak_wins}"
                      + (f"-{m.draws}" if m.draws else ""), f"{tag}{rate:.0%}[/]")
    console.print(table)
    ok = is_monotone(matches)
    verdict = "[green]MONOTONE[/green] (every stronger level won >=55%)" if ok else (
        "[yellow]NOT monotone[/yellow] (some pairing fell below 55%)")
    console.print(f"Ladder: {verdict}")
    return 0 if ok else 1


def _cmd_gauntlet(args: argparse.Namespace) -> int:
    """Sparse round-robin over a deck corpus -> Bradley-Terry ratings (Meta-strength v0)."""
    from mythgauntlet.ratings.gauntlet import fit_bradley_terry, sample_pairs
    from mythgauntlet.sim.tier2 import prepare_deck

    _require_positive(games=args.games, turns=args.turns, opponents=args.opponents)
    db = _load_db()
    store = _semantics_store()
    deck_dir = Path(args.dir) if args.dir else corpus_dir()
    deck_files = sorted(deck_dir.glob("*.txt"))
    if len(deck_files) < 2:
        _die(f"Need at least 2 decklists in {deck_dir}")

    labels: dict[str, int | None] = {}
    commanders: dict[str, str] = {}
    manifest_path = deck_dir / "manifest.json"
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as fh:
            for entry in json.load(fh).get("decks", []):
                labels[Path(entry["file"]).stem] = entry.get("bracket")

    prepared = {}
    combo_deck_count = 0
    for path in deck_files:
        resolved = _load_resolved(str(path), db)
        if not resolved.cards or not resolved.commanders:
            console.print(f"[yellow]skipped[/yellow] {path.name} (no commander or cards)")
            continue
        combos = () if args.no_combos else _winning_combos(resolved)
        combo_deck_count += 1 if combos else 0
        prepared[path.stem] = prepare_deck(
            path.stem, resolved.cards, resolved.commanders[0], store, combos
        )
        commanders[path.stem] = resolved.commanders[0].name
    if not args.no_combos:
        console.print(
            f"[dim]{combo_deck_count} decks have a detected game-ending combo[/dim]"
        )

    names = sorted(prepared)
    pairs = sample_pairs(names, opponents_each=args.opponents, seed=args.seed)
    total_games = len(pairs) * args.games
    agent = getattr(args, "agent", "greedy")
    console.print(
        f"[bold]Gauntlet:[/bold] {len(names)} decks, {len(pairs)} matchups x "
        f"{args.games} games = {total_games:,} games (T2 MVP, seed {args.seed}, agent {agent})"
    )

    from mythgauntlet.ratings.orchestrator import Job, JobCache, run_jobs

    jobs = [
        Job(a, b, DuelConfig(
            games=args.games, seed=(args.seed * 1_000_003 + idx) & 0xFFFF_FFFF,
            max_turns=args.turns, start_life=args.life,
            agent_a=agent, agent_b=agent, mcts_iterations=getattr(args, "mcts_iters", 0),
        ))
        for idx, (a, b) in enumerate(pairs, 1)
    ]
    workers = getattr(args, "jobs", 1)
    cache = None
    if getattr(args, "cache", False):
        # engine_tag = executable-semantics count so recompiling invalidates the resume cache
        cache = JobCache(
            data_dir() / f"gauntlet_cache_{agent.replace(':', '-')}.json",
            engine_tag=f"{len(store)}sem",
        )
    if workers and workers > 1:
        console.print(f"[dim]  running {len(jobs)} matchups across {workers} processes"
                      f"{' (cached/resumable)' if cache else ''}[/dim]")

    def _progress(done: int, total: int) -> None:
        if done % 25 == 0 or done == total:
            console.print(f"[dim]  {done}/{total} matchups done[/dim]")

    results = run_jobs(prepared, jobs, workers=workers, cache=cache, on_done=_progress)
    ratings = fit_bradley_terry(results)
    out_path = data_dir() / f"gauntlet_{date.today().isoformat()}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "engine": "tier2-mvp", "agent": agent, "seed": args.seed,
                "games_per_pair": args.games, "ratings": ratings,
                "pairs": [dataclasses.asdict(r) for r in results],
            },
            fh, indent=2, ensure_ascii=False,
        )

    table = Table(
        title=f"Gauntlet ratings (Bradley-Terry over {total_games:,} T2 games, agent {agent})",
        header_style="bold",
    )
    table.add_column("Rating", justify="right")
    table.add_column("Bracket", justify="right")
    table.add_column("Commander")
    table.add_column("Deck")
    ranked = sorted(ratings.items(), key=lambda kv: -kv[1])
    for name, rating in ranked[: args.show]:
        table.add_row(
            f"{rating:.0f}", str(labels.get(name) or "-"),
            commanders.get(name, "?")[:32], name[:40],
        )
    console.print(table)

    by_bracket: dict[int, list[float]] = {}
    for name, rating in ratings.items():
        bracket = labels.get(name)
        if bracket:
            by_bracket.setdefault(bracket, []).append(rating)
    if by_bracket:
        summary = "  ".join(
            f"B{b}: {sum(v) / len(v):.0f} (n={len(v)})" for b, v in sorted(by_bracket.items())
        )
        console.print(f"\nMean rating by labeled bracket: {summary}")
    console.print(f"[dim]Saved {out_path}[/dim]")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn

        from mythgauntlet.server import create_app
    except ImportError:
        _die("The strength API needs the serve extra: pip install -e .[serve]")
    _load_db()  # fail fast with the friendly 'run fetch-data' message, not a startup traceback
    app = create_app()  # loads the card + semantics stores once
    console.print(
        f"MythGauntlet strength API -> http://{args.host}:{args.port} "
        "(HTTP; /analyze /advise /duel /pod; Ctrl+C to stop)"
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _cmd_edhrec(args: argparse.Namespace) -> int:
    try:
        payload = edhrec.fetch_commander(args.commander, force=args.force)
    except requests.RequestException as exc:
        _die(f"EDHREC unavailable: {exc}")
    cards = edhrec.parse_commander_page(payload)
    if not cards:
        console.print("[red]No card data found on that commander page.[/red]")
        return 2
    synergistic = sorted(
        (c for c in cards if c.synergy is not None), key=lambda c: c.synergy, reverse=True
    )
    table = Table(
        title=f"EDHREC - {args.commander} (top synergy)", show_header=True, header_style="bold"
    )
    table.add_column("Card")
    table.add_column("Synergy", justify="right")
    table.add_column("Inclusion", justify="right")
    table.add_column("Category")
    for c in synergistic[: args.top]:
        incl = f"{c.inclusion_rate:.0%}" if c.inclusion_rate is not None else "-"
        table.add_row(c.name, f"{c.synergy:+.2f}", incl, c.category)
    console.print(table)
    console.print(f"[dim]{len(cards)} cards across all lists (cached under data/edhrec/)[/dim]")
    return 0


# --- Navigation commands (front door) ---------------------------------------------------


def _cmd_home(args: argparse.Namespace) -> int:
    nav.render_dashboard(console)
    return 0


def _cmd_menu(args: argparse.Namespace) -> int:
    return nav.run_menu(dispatch=main, console=console)


def _cmd_doctor(args: argparse.Namespace) -> int:
    return nav.render_doctor(console)


def _cmd_decks(args: argparse.Namespace) -> int:
    return nav.render_decks(console)


def _cmd_completion(args: argparse.Namespace) -> int:
    # Command names come from the live grouping so completions never drift from reality.
    commands = [(name, help_text) for _, cmds in nav.COMMAND_GROUPS for name, help_text in cmds]
    try:
        script = completion.render(args.shell, commands)
    except ValueError as exc:
        _die(str(exc))
    print(script)  # stdout so it can be piped/sourced directly
    return 0


def _help_epilog() -> str:
    """Grouped command listing + common workflows (RawDescription epilog, ASCII-only)."""
    lines = ["commands by workflow:"]
    for group, commands in nav.COMMAND_GROUPS:
        lines.append(f"  {group}:")
        for name, help_text in commands:
            lines.append(f"    {name:<13} {help_text}")
        lines.append("")
    lines += [
        "common workflows:",
        "  Prove a deck's bracket:   mythgauntlet analyze my_deck.txt --combos",
        "  ...against your cards:    mythgauntlet analyze my_deck.txt --collection coll.csv",
        "  Head-to-head matchup:     mythgauntlet duel deck_a.txt deck_b.txt --games 300",
        "  Rank the whole corpus:    mythgauntlet gauntlet",
        "  First-time setup:         mythgauntlet fetch-data   then   mythgauntlet doctor",
        "  Enable tab-completion:    mythgauntlet completion powershell   (or bash/zsh/fish)",
        "",
        "global options (accepted anywhere): --plain / --no-color for uncoloured output",
        "  (the NO_COLOR environment variable is honoured too).",
        "Run 'mythgauntlet' with no arguments for the interactive menu + status dashboard.",
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mythgauntlet",
        description="Simulation-grounded MTG Commander deck strength engine.",
        epilog=_help_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"mythgauntlet {__version__}")
    # required=False so a bare 'mythgauntlet' opens the menu/dashboard instead of erroring.
    # Commands are hidden from the flat auto-list (help=SUPPRESS) because _help_epilog()
    # presents them grouped by workflow; each subparser keeps a description for '<cmd> -h'.
    sub = parser.add_subparsers(dest="command", required=False, metavar="<command>")

    p_fetch = sub.add_parser(
        "fetch-data", description="Download Scryfall bulk card data."
    )
    p_fetch.add_argument("--force", action="store_true", help="re-download even if cached")
    p_fetch.add_argument(
        "--max-age-days", type=float, default=scryfall.MAX_AGE_DAYS,
        help=f"refetch when the cached store is older than this (default {scryfall.MAX_AGE_DAYS})",
    )
    p_fetch.set_defaults(func=_cmd_fetch_data)

    p_analyze = sub.add_parser(
        "analyze",
        description="Run a Tier-0 consistency analysis + bracket estimate on a decklist. "
        "With no path, re-runs your last analyzed deck.",
    )
    p_analyze.add_argument(
        "deck", nargs="?", help="path to a decklist text file (default: your last deck)"
    )
    p_analyze.add_argument("--runs", type=int, default=1000)
    p_analyze.add_argument("--turns", type=int, default=DEFAULT_ANALYZE_TURNS)
    p_analyze.add_argument("--seed", type=int, default=42)
    p_analyze.add_argument("--json", action="store_true", help="emit the report as JSON")
    p_analyze.add_argument(
        "--collection",
        help="collection file (CSV or decklist) for ownership reporting "
             "(default: ~/Documents/MythSuite/collection.csv when it exists)",
    )
    p_analyze.add_argument(
        "--no-collection", action="store_true",
        help="skip ownership reporting even if a default collection file exists",
    )
    p_analyze.add_argument(
        "--combos", action="store_true",
        help="also query Commander Spellbook for combos (network)",
    )
    p_analyze.add_argument(
        "--no-resilience", action="store_true",
        help="skip the Tier-1 board-wipe resilience pass",
    )
    p_analyze.add_argument(
        "--pod", action="store_true",
        help="also rate the deck's 4-player pod WIN SHARE vs the corpus (Tier-2 multiplayer)",
    )
    p_analyze.add_argument(
        "--pod-games", type=int, default=40, help="pods to play for --pod (default 40)",
    )
    p_analyze.set_defaults(func=_cmd_analyze)

    p_advise = sub.add_parser(
        "advise",
        description="Suggest owned-card swaps that improve a Power Profile axis, measured by "
        "re-simulation (ablation). Uses your default collection file unless --collection is given.",
    )
    p_advise.add_argument("deck", nargs="?", help="path to a decklist (default: your last deck)")
    p_advise.add_argument(
        "--axis", choices=sorted(advisor.AXES),
        help="axis to improve (default: the deck's weakest)",
    )
    p_advise.add_argument(
        "--collection",
        help="collection file (default: ~/Documents/MythSuite/collection.csv when it exists)",
    )
    p_advise.add_argument("--top", type=int, default=5, help="suggestions to show")
    p_advise.add_argument(
        "--max-eval", dest="max_eval", type=int, default=12,
        help="owned candidates to test by re-simulation",
    )
    p_advise.add_argument(
        "--cut-pool", type=int, default=3, dest="cut_pool",
        help="weakest cards each candidate is tested against (1 = single global cut)",
    )
    p_advise.add_argument("--runs", type=int, default=400, help="sim games per evaluation")
    p_advise.add_argument("--turns", type=int, default=DEFAULT_ANALYZE_TURNS)
    p_advise.add_argument("--seed", type=int, default=42)
    p_advise.set_defaults(func=_cmd_advise)

    p_info = sub.add_parser(
        "info", description="Show a card and its rung-1 effect vector."
    )
    p_info.add_argument("name")
    p_info.set_defaults(func=_cmd_info)

    p_serve = sub.add_parser(
        "serve",
        description="Run the local HTTP strength API (needs the [serve] extra).",
    )
    p_serve.add_argument("--host", default=STRENGTH_API_HOST)
    p_serve.add_argument("--port", type=int, default=STRENGTH_API_PORT)
    p_serve.set_defaults(func=_cmd_serve)

    p_gauntlet = sub.add_parser(
        "gauntlet",
        description="Round-robin the corpus -> Bradley-Terry ratings (Tier-2).",
    )
    p_gauntlet.add_argument("--dir", help="deck directory (default: corpus/decks)")
    p_gauntlet.add_argument("--opponents", type=int, default=6, help="matchups per deck")
    p_gauntlet.add_argument("--games", type=int, default=60, help="games per matchup")
    p_gauntlet.add_argument("--seed", type=int, default=42)
    p_gauntlet.add_argument("--turns", type=int, default=30)
    p_gauntlet.add_argument("--life", type=int, default=40)
    p_gauntlet.add_argument("--show", type=int, default=25, help="rows to display")
    p_gauntlet.add_argument(
        "--agent", default="greedy",
        help="agent level for BOTH sides: greedy (default) or mcts[:iterations]. "
        "Ratings are tagged with the agent and must not be mixed across levels.",
    )
    p_gauntlet.add_argument("--mcts-iters", type=int, default=0,
                            help="ISMCTS iterations when --agent mcts (0 => agent default)")
    p_gauntlet.add_argument("--jobs", type=int, default=1,
                            help="parallel worker processes (matchups are independent; "
                            "essential for an --agent mcts run). 1 = serial.")
    p_gauntlet.add_argument("--cache", action="store_true",
                            help="cache matchup results to data/ (resume an interrupted run; "
                            "keyed by semantics version so recompiling invalidates it)")
    p_gauntlet.add_argument(
        "--no-combos", action="store_true",
        help="skip Commander Spellbook combo win-conditions (offline / faster)",
    )
    p_gauntlet.set_defaults(func=_cmd_gauntlet)

    p_ladder = sub.add_parser(
        "ladder",
        description="Agent strength ladder: pit search levels head-to-head (Phase 7).",
    )
    p_ladder.add_argument("deck_a", help="path to a decklist (mirror unless deck_b given)")
    p_ladder.add_argument("deck_b", nargs="?", help="optional second decklist")
    p_ladder.add_argument(
        "--levels", default="greedy,mcts:100,mcts:1000",
        help="comma-separated agent levels, weakest->strongest (e.g. greedy,mcts:100,mcts:1000)",
    )
    p_ladder.add_argument("--games", type=int, default=40, help="games per pairing")
    p_ladder.add_argument("--seed", type=int, default=42)
    p_ladder.add_argument("--turns", type=int, default=25, help="turn cap before adjudication")
    p_ladder.add_argument("--rollout-depth", type=int, default=14,
                          help="ISMCTS truncated-rollout ply cap")
    p_ladder.add_argument("--no-combos", action="store_true", help="skip combo win-conditions")
    p_ladder.set_defaults(func=_cmd_ladder)

    p_duel = sub.add_parser(
        "duel",
        description="Simulate 1v1 games between two decks (Tier-2 MVP).",
    )
    p_duel.add_argument("deck_a", help="path to first decklist")
    p_duel.add_argument("deck_b", help="path to second decklist")
    p_duel.add_argument("--games", type=int, default=200)
    p_duel.add_argument("--seed", type=int, default=42)
    p_duel.add_argument("--turns", type=int, default=30, help="turn cap before adjudication")
    p_duel.add_argument("--life", type=int, default=40)
    p_duel.add_argument("--agent-a", default="greedy",
                        help="agent for deck A: greedy (default) or mcts[:iterations]")
    p_duel.add_argument("--agent-b", default="greedy",
                        help="agent for deck B: greedy (default) or mcts[:iterations]")
    p_duel.add_argument("--mcts-iters", type=int, default=0,
                        help="ISMCTS iterations for bare 'mcts' agents (0 => agent default)")
    p_duel.add_argument(
        "--no-combos", action="store_true",
        help="skip Commander Spellbook combo win-conditions (offline / faster)",
    )
    p_duel.set_defaults(func=_cmd_duel)

    p_pod = sub.add_parser(
        "pod",
        description="Pod meta-rating: a deck's win share in 4-player games vs the corpus field.",
    )
    p_pod.add_argument("deck", help="path to the decklist to rate")
    p_pod.add_argument("--dir", help="opponent field directory (default: corpus/decks)")
    p_pod.add_argument("--games", type=int, default=60, help="pods to play")
    p_pod.add_argument("--seed", type=int, default=42)
    p_pod.add_argument("--turns", type=int, default=30, help="turn cap before adjudication")
    p_pod.add_argument("--players", type=int, default=4, help="pod size (default 4)")
    p_pod.add_argument("--life", type=int, default=40)
    p_pod.add_argument("--no-combos", action="store_true", help="skip combo win-conditions")
    p_pod.set_defaults(func=_cmd_pod)

    p_edhrec = sub.add_parser(
        "edhrec", description="Show EDHREC synergy data for a commander."
    )
    p_edhrec.add_argument("commander")
    p_edhrec.add_argument("--top", type=int, default=15)
    p_edhrec.add_argument("--force", action="store_true", help="bypass the local cache")
    p_edhrec.set_defaults(func=_cmd_edhrec)

    p_combos = sub.add_parser(
        "combos",
        description="Find combos in a deck + near-misses (Commander Spellbook).",
    )
    p_combos.add_argument("deck", help="path to a decklist text file")
    p_combos.add_argument("--top", type=int, default=10, help="near-misses to show")
    p_combos.add_argument("--force", action="store_true", help="bypass the local cache")
    p_combos.set_defaults(func=_cmd_combos)

    p_edhplay = sub.add_parser(
        "edhplay",
        description="Export a deck to EDHPlay (edhplay.com) with a chosen art per card. "
        "Prints a Bulk-Import list you paste into Create Deck.",
    )
    p_edhplay.add_argument("deck", nargs="?", help="path to a decklist text file")
    p_edhplay.add_argument(
        "--policy", choices=artselect.POLICIES, default="default",
        help="art to prefer deck-wide (default: leave EDHPlay's default printing)",
    )
    p_edhplay.add_argument(
        "--art", metavar="FILE",
        help="per-card art override file ('Name = SET CN' | set | scryfall:<id> | keyword)",
    )
    p_edhplay.add_argument("--out", help="write the decklist to FILE instead of stdout")
    p_edhplay.add_argument(
        "--json", action="store_true",
        help="emit the bulk-import API body instead of paste text",
    )
    p_edhplay.add_argument(
        "--myth-job", metavar="JOB_ID",
        help="use a MythForge build's custom art (shortcut for --art-source mythforge:JOB_ID)",
    )
    p_edhplay.add_argument(
        "--art-source", metavar="SPEC",
        help="custom-art source: mythforge:<job> | dir:<path> | manifest:<file>",
    )
    p_edhplay.add_argument(
        "--myth-url", default=artsource.DEFAULT_MYTHFORGE_BASE,
        help=f"MythForge base URL (default: {artsource.DEFAULT_MYTHFORGE_BASE})",
    )
    p_edhplay.add_argument(
        "--userscript", metavar="FILE",
        help="write a Tampermonkey .user.js that shows the custom art on EDHPlay",
    )
    p_edhplay.add_argument(
        "--embed", action="store_true",
        help="embed art as data URIs (portable, no server needed at play time; larger file)",
    )
    p_edhplay.add_argument("--seed", type=int, default=42, help="seed for --policy random")
    p_edhplay.add_argument("--lang", default="en", help="printing language (default: en)")
    p_edhplay.add_argument(
        "--include-digital", action="store_true",
        help="allow MTGO/Arena-only printings (default: paper only)",
    )
    p_edhplay.add_argument(
        "--no-notes", action="store_true", help="omit inline '# ...' fallback notes"
    )
    p_edhplay.add_argument(
        "--fetch-printings", action="store_true",
        help="download/refresh the printings store (~450 MB), then exit",
    )
    p_edhplay.add_argument("--force", action="store_true", help="with --fetch-printings")
    p_edhplay.set_defaults(func=_cmd_edhplay)

    p_fetch_decks = sub.add_parser(
        "fetch-decks",
        description="Poll deck sources (EDHREC average / Archidekt top) into the corpus.",
    )
    p_fetch_decks.add_argument(
        "--commander", help="fetch the EDHREC average deck for this commander"
    )
    p_fetch_decks.add_argument(
        "--source", choices=["archidekt"], help="poll a deck site instead"
    )
    p_fetch_decks.add_argument("--top", type=int, default=5, help="decks to pull (archidekt)")
    p_fetch_decks.add_argument(
        "--order", default="-viewCount",
        help="archidekt sort: -viewCount, -createdAt, -updatedAt",
    )
    p_fetch_decks.add_argument(
        "--bracket", type=int, choices=[1, 2, 3, 4, 5], default=None,
        help="archidekt: only decks the author labeled with this bracket "
        "(labeled calibration anchors; 5 = cEDH)",
    )
    p_fetch_decks.add_argument("--out", help="output dir (default: corpus/decks)")
    p_fetch_decks.set_defaults(func=_cmd_fetch_decks)

    p_bench = sub.add_parser(
        "benchmark",
        description="Tier-0 analysis over the whole deck corpus.",
    )
    p_bench.add_argument("--dir", help="deck directory (default: corpus/decks)")
    p_bench.add_argument("--runs", type=int, default=500)
    p_bench.add_argument("--turns", type=int, default=8)
    p_bench.add_argument("--seed", type=int, default=42)
    p_bench.add_argument("--show", type=int, default=20, help="rows to print")
    p_bench.set_defaults(func=_cmd_benchmark)

    p_cc = sub.add_parser(
        "compile-card",
        description="Compile one card to a CCM via the local LLM.",
    )
    p_cc.add_argument("name")
    p_cc.add_argument("--force", action="store_true", help="recompile even if in ledger")
    p_cc.set_defaults(func=_cmd_compile_card)

    p_ct = sub.add_parser(
        "compile-top",
        description="Compile the top-N EDHREC-ranked cards not yet in the ledger.",
    )
    p_ct.add_argument("count", type=int)
    p_ct.add_argument("--force", action="store_true")
    p_ct.add_argument(
        "--refresh-stale", action="store_true",
        help="when no uncompiled cards remain, recompile cards accepted at an older "
             "prompt version (oldest first); a failed refresh keeps the existing CCM",
    )
    p_ct.set_defaults(func=_cmd_compile_top)

    p_cs = sub.add_parser(
        "ccm-status", description="CCM ledger coverage stats."
    )
    p_cs.set_defaults(func=_cmd_ccm_status)

    # Navigation / creature comforts.
    p_decks = sub.add_parser(
        "decks",
        description="Browse the decklists available to analyze/duel/gauntlet.",
    )
    p_decks.set_defaults(func=_cmd_decks)

    p_doctor = sub.add_parser(
        "doctor",
        description="Check your setup: card data, gateways, collection, corpus.",
    )
    p_doctor.set_defaults(func=_cmd_doctor)

    p_home = sub.add_parser(
        "home", description="Show the status dashboard."
    )
    p_home.set_defaults(func=_cmd_home)

    p_menu = sub.add_parser(
        "menu", description="Interactive menu to navigate the toolbox."
    )
    p_menu.set_defaults(func=_cmd_menu)

    p_completion = sub.add_parser(
        "completion",
        description="Print a shell-completion script to source from your shell profile.",
    )
    p_completion.add_argument("shell", choices=completion.SHELLS, help="target shell")
    p_completion.set_defaults(func=_cmd_completion)

    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    plain, cleaned = _extract_global_flags(raw)
    if plain:
        _apply_plain()
    args = build_parser().parse_args(cleaned)
    if getattr(args, "func", None) is None:
        # Bare 'mythgauntlet': open the interactive menu (or the dashboard when not a TTY)
        # instead of argparse's "command is required" error.
        return nav.run_menu(dispatch=main, console=console)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
