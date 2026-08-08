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
from mythgauntlet.sim.overrun import OverrunReport, estimate_overrun
from mythgauntlet.sim.storm import GoOffReport, estimate_go_off
from mythgauntlet.sim.tier0 import SimConfig, simulate
from mythgauntlet.sim.tier1 import ResilienceReport, compute_resilience, default_wipe_turn

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
    runs = simulate(resolved.cards, commander, cfg)
    report = metrics.compute(runs, cfg)
    coverage = store.coverage(resolved.cards, resolved.commanders)
    interaction = compute_interaction(resolved.cards, commander)

    # storm/spellslinger go-off: judge the commander-as-engine against the whole spell base,
    # grounded in the deck's real (nut-draw) mana curve (docs/SIMULATION.md; feeds Ceiling+bracket).
    all_cards = list(resolved.cards) + ([(commander, 1)] if commander else [])
    mana_by_turn = _mean_mana_curve(runs, cfg.turns)
    go_off = estimate_go_off(all_cards, mana_by_turn, cfg.turns)
    # go-wide overrun: read the NUT board (a high percentile of the go-wide distribution).
    nut_power, nut_creatures = _nut_board(runs)
    overrun = estimate_overrun(all_cards, nut_power, nut_creatures)
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
        pod_runs = simulate(resolved.cards, commander, pod_cfg)
    pod = compute_pod(pod_runs, pod_cfg, has_finisher=has_finisher)

    resilience = None
    wipe_turn = None
    if run_resilience:
        wipe_turn = default_wipe_turn(cfg.turns)
        resilience = compute_resilience(resolved.cards, commander, cfg, wipe_turn)

    game_changers = sorted(
        [c.name for c in resolved.commanders if c.game_changer]
        + [c.name for c, _ in resolved.cards if c.game_changer]
    )
    bracket = estimate_bracket(
        resolved.cards, resolved.commanders,
        ceiling=ceiling.score, speed_kill_rate=report.goldfish_kill_rate,
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
