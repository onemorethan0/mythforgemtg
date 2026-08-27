"""The single deck-analysis pipeline shared by the CLI and the HTTP API.

Both `mythgauntlet analyze` and the server's POST /analyze must produce the SAME numbers
for the same deck — Power Profile axes, resilience, coverage, Game Changers, and the
bracket estimate. Keeping the computation in one place (each surface only formats the
result) stops the two from silently drifting.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from mythgauntlet.data.spellbook import Combo, ComboAssessment, ComboReport, assess_combos
from mythgauntlet.model.card import Card, normalize_name
from mythgauntlet.model.deck import ResolvedDeck
from mythgauntlet.ratings import manabase, metrics
from mythgauntlet.ratings.axes import (
    CeilingReport,
    InteractionReport,
    PodReport,
    compute_ceiling,
    compute_interaction,
    compute_pod,
)
from mythgauntlet.ratings.bracket import BracketEstimate, estimate_bracket
from mythgauntlet.ratings.insight import DeckInsight, build_insight
from mythgauntlet.ratings.metrics import ConsistencyReport
from mythgauntlet.semantics.combo_rules import DeterminismVerdict, classify_determinism
from mythgauntlet.semantics.store import CoverageReport, SemanticsStore
from mythgauntlet.sim.clock import apply_nut_kills
from mythgauntlet.sim.overrun import OverrunReport, estimate_overrun
from mythgauntlet.sim.storm import GoOffReport, estimate_go_off
from mythgauntlet.sim.tier0 import SimConfig, simulate
from mythgauntlet.sim.tier1 import ResilienceReport, compute_resilience, default_wipe_turn
from mythgauntlet.sim.wincon_redundancy import WinconRedundancyReport, analyze_wincon_redundancy

# A pod goes long: the single-opponent goldfish horizon (default 8) is far too short to reach
# TABLE-lethal damage (3x40), so the Pod clock reads a longer goldfish. Shares the early turns
# with the main run by seed; adds only the tail.
_POD_HORIZON = 14


@dataclass
class DeckAnalysis:
    report: ConsistencyReport
    coverage: CoverageReport
    interaction: InteractionReport
    ceiling: CeilingReport
    pod: PodReport
    resilience: ResilienceReport | None
    bracket: BracketEstimate
    game_changers: list[str]
    wipe_turn: int | None
    go_off: GoOffReport
    overrun: OverrunReport
    wincon_redundancy: WinconRedundancyReport
    combo_profile: ComboAssessment | None = None  # graded combos (None if no report supplied)
    insight: DeckInsight | None = None  # deck-specific narrative (archetype/why/cards/verdict)


def analyze_deck(
    resolved: ResolvedDeck,
    cfg: SimConfig,
    store: SemanticsStore,
    *,
    two_card_combos: int = 0,
    game_ending_combos: int = 0,  # in-deck game-ending combos of any size (>= two_card_combos)
    combo_report: ComboReport | None = None,  # full Spellbook report -> graded combo gate
    combos_checked: bool = False,
    run_resilience: bool = True,
) -> DeckAnalysis:
    """Run the full single-deck analysis. Deterministic for a given (deck, cfg)."""
    commander: Card | None = resolved.commanders[0] if resolved.commanders else None
    # Partner/background commanders beyond the lead were previously invisible to every
    # simulation-based axis: `simulate`/`compute_interaction`/`compute_resilience` (tier0,
    # tier1, axes.py) each take a single `commander: Card | None`, because T0 models "the
    # commander" as ONE physical card that starts in the command zone with a dedicated
    # cast-priority slot -- extending that to a real second command-zone card is a
    # simulator restructure out of scope for this fix (those modules aren't in-scope here).
    #
    # What *is* fixed: a second (or third, background) commander is no longer dropped from
    # these axes outright. It is folded into the ordinary card pool (`sim_cards`) that feeds
    # `simulate`/`compute_interaction`/`compute_resilience`/`compute_pod`/Ceiling/go_off/
    # overrun, so its own stats, oracle-text tags (removal/wipe/counterspell/combo pieces)
    # and color identity are counted wherever those axes already look at "the cards" rather
    # than "the commander". The trade-off, and the part that remains a documented gap: it
    # is simulated as a NORMAL library card the deck must draw and cast, not a guaranteed
    # early command-zone cast like the lead commander gets -- so a partner's presence is
    # under-counted relative to how reliably a real pilot has it available turn 1, but it is
    # no longer a hard zero. `coverage`/`bracket`/`manabase.analyze`/game_changers/combo
    # detection below already took the FULL `resolved.commanders` list independently of this
    # change and are unaffected.
    extra_commanders = resolved.commanders[1:]
    sim_cards = resolved.cards + [(c, 1) for c in extra_commanders]
    all_cards = list(sim_cards) + ([(commander, 1)] if commander else [])
    runs = simulate(sim_cards, commander, cfg)
    # Teach the clock to see a non-combat win (docs/PLAN_CLOCK.md Phase 1a): kill_turn is
    # otherwise combat-damage-only, so a storm deck that goes off turn 4 or a go-wide deck
    # that alpha-strikes turn 6 reported the same ~turn-8.5 nut draw as a deck with neither.
    # Mutates kill_turn on the runs where either detector fires, per that run's own
    # mana/board curve — must run BEFORE metrics.compute so avg_kill_turn/goldfish_kill_rate
    # see it, and before compute_ceiling so fast_kill_turn/nut_kill_rate do too.
    apply_nut_kills(runs, all_cards, cfg.turns)
    report = metrics.compute(runs, cfg)
    coverage = store.coverage(resolved.cards, resolved.commanders)
    interaction = compute_interaction(sim_cards, commander)

    # storm/spellslinger go-off: judge the commander-as-engine against the whole spell base,
    # grounded in the deck's real (nut-draw) mana curve (docs/SIMULATION.md; feeds Ceiling+bracket).
    # Deck-level (mean curve / nut-percentile board), unlike apply_nut_kills above which reads
    # each run's OWN curve — kept for compute_ceiling's separate go_off/overrun score bonus and
    # for the bracket gate's can_go_off, both of which pre-date and are independent of Phase 1a.
    mana_by_turn = _mean_mana_curve(runs, cfg.turns)
    go_off = estimate_go_off(all_cards, mana_by_turn, cfg.turns)
    # go-wide overrun: read the NUT board (a high percentile of the go-wide distribution).
    nut_power, nut_creatures = _nut_board(runs)
    overrun = estimate_overrun(all_cards, nut_power, nut_creatures)
    # PLAN_CLOCK Phase 2 / docs/SPEC_wincon_redundancy.md: "how many pieces of interaction
    # does it take to stop the win", for the four non-combat mechanisms go_off/overrun
    # already read. Reuses the SAME mana_by_turn/nut_power/nut_creatures computed above --
    # no extra simulation, just a handful more deterministic estimator calls -- so unlike
    # `resilience` this is not gated behind a flag. Informational only: not consumed by
    # estimate_bracket or compute_ceiling (see the spec's Scope boundary).
    wincon_redundancy = analyze_wincon_redundancy(
        all_cards, mana_by_turn, nut_power, nut_creatures, cfg.turns,
        commander_names=frozenset(c.name for c in resolved.commanders),
    )
    ceiling = compute_ceiling(
        runs, cfg, go_off_turn=go_off.earliest_turn, overrun_alpha=overrun.can_alpha_strike
    )
    # Grade the combos (metadata) + judge determinism (rules/errata) so the bracket gate and
    # explanation can tell a fast terminal wincon from a slow durdle or a chance-based loop,
    # instead of "any combo -> min Bracket 3".
    #
    # Graded BEFORE the pod score, because the pod score needs it. The two callers supply
    # combo evidence in different shapes: the CLI counts combos itself and passes
    # `game_ending_combos`, while the API passes the whole `combo_report` and leaves the
    # counts at 0. `estimate_bracket` already reconciles the two (it takes
    # `max(combo_count, two_card_combos, combo_profile.total)`), but `has_finisher` below
    # read the raw count only — so over HTTP it was ALWAYS False and the app's pod score
    # never reflected a combo finisher, while the CLI's did. Same deck, two answers, from
    # the pipeline whose comment says the surfaces "can't drift".
    combo_profile = None
    if combo_report is not None:
        commander_names = frozenset(c.name for c in resolved.commanders)
        det_fn = make_determinism_fn(resolved.cards, resolved.commanders)
        combo_profile = assess_combos(combo_report, commander_names, determinism_fn=det_fn)
    has_finisher = game_ending_combos > 0 or (combo_profile is not None and combo_profile.total > 0)

    # Pod (multiplayer) closing power: a longer goldfish (a pod runs long) tells whether the deck
    # can generate TABLE-lethal unopposed damage; a game-ending combo closes the table combat
    # can't. A capacity proxy — the duel-vs-pod gap shows how much a pod raises the bar.
    if cfg.turns >= _POD_HORIZON:
        pod_runs, pod_cfg = runs, cfg
    else:
        pod_cfg = replace(cfg, turns=_POD_HORIZON)
        pod_runs = simulate(sim_cards, commander, pod_cfg)
        apply_nut_kills(pod_runs, all_cards, pod_cfg.turns)
    pod = compute_pod(pod_runs, pod_cfg, has_finisher=has_finisher)

    resilience = None
    wipe_turn = None
    if run_resilience:
        wipe_turn = default_wipe_turn(cfg.turns)
        resilience = compute_resilience(sim_cards, commander, cfg, wipe_turn, all_cards=all_cards)

    game_changers = sorted(
        [c.name for c in resolved.commanders if c.game_changer]
        + [c.name for c, _ in resolved.cards if c.game_changer]
    )
    bracket = estimate_bracket(
        resolved.cards, resolved.commanders,
        speed_kill_rate=report.goldfish_kill_rate,
        consistency=report.consistency_score, interaction=interaction.score,
        avg_kill_turn=report.avg_kill_turn,
        # Mana-base consistency decides B1 vs B2 (measured; see bracket.estimate_bracket).
        manabase_consistency=manabase.analyze(resolved.cards, resolved.commanders).consistency,
        two_card_combos=two_card_combos, combo_count=game_ending_combos,
        combo_profile=combo_profile,
        can_go_off=go_off.goes_off,
        combos_checked=combos_checked, coverage_share=coverage.executable_share,
    )
    analysis = DeckAnalysis(
        report=report, coverage=coverage, interaction=interaction, ceiling=ceiling, pod=pod,
        resilience=resilience, bracket=bracket, game_changers=game_changers,
        wipe_turn=wipe_turn, go_off=go_off, overrun=overrun, combo_profile=combo_profile,
        wincon_redundancy=wincon_redundancy,
    )
    analysis.insight = build_insight(resolved, analysis)  # deck-specific narrative from the above
    return analysis


def make_determinism_fn(
    cards: list[tuple[Card, int]], commanders: list[Card]
) -> Callable[[Combo], DeterminismVerdict]:
    """Build the injected determinism judge: maps a combo to a verdict from its pieces' Oracle
    text (= Scryfall errata) + the Spellbook loop description. Shared by the API pipeline and
    the CLI combo panels so both surfaces judge determinism identically.
    """
    text_by_name = {normalize_name(c.name): (c.oracle_text or "") for c, _ in cards}
    for cm in commanders:
        text_by_name.setdefault(normalize_name(cm.name), cm.oracle_text or "")

    def judge(combo: Combo) -> DeterminismVerdict:
        piece_texts = [text_by_name.get(normalize_name(n), "") for n in combo.cards]
        return classify_determinism(piece_texts, combo.description)

    return judge


def _nut_board(runs: list) -> tuple[int, int]:
    """The nut go-wide board = a high percentile (P75) of the goldfish board distribution, so the
    overrun ceiling reflects the BEST draws, not the average (docs/SIMULATION.md)."""
    if not runs:
        return 0, 0
    powers = sorted(r.final_board_power for r in runs)
    creatures = sorted(r.final_board_creatures for r in runs)
    i = min(len(runs) - 1, int(0.75 * len(runs)))
    return powers[i], creatures[i]


def _mean_mana_curve(runs: list, turns: int) -> list[int]:
    """Per-turn mean of the T0 mana-available curve (rounded) — the deck's honest mana, the
    go-off sim reads it instead of inventing mana (docs/SIMULATION.md)."""
    if not runs:
        return []
    curve = []
    for i in range(turns):
        vals = [r.mana_available_by_turn[i] for r in runs if i < len(r.mana_available_by_turn)]
        curve.append(round(sum(vals) / len(vals)) if vals else 0)
    return curve
