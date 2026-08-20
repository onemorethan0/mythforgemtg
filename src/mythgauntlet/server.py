"""Local HTTP strength API.

Serves MythGauntlet's measurements over HTTP to any client — /analyze, /advise, /duel, /pod.
Local-only by default; the card store and semantics store load once at startup. Every response
carries engine_version — a rating is a measurement BY an instrument.

Requires the [serve] extra: pip install -e .[serve]
"""

from __future__ import annotations

import dataclasses

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from mythgauntlet import __version__
from mythgauntlet.config import corpus_dir, suite_collection_path
from mythgauntlet.data import scryfall, spellbook
from mythgauntlet.model.collection import Collection
from mythgauntlet.model.deck import Deck, ResolvedDeck, resolve
from mythgauntlet.ratings import advisor, card_impact, metrics
from mythgauntlet.ratings.analysis import analyze_deck
from mythgauntlet.semantics.store import SemanticsStore, load_store
from mythgauntlet.sim.tier0 import DEFAULT_ANALYZE_TURNS, SimConfig
from mythgauntlet.sim.tier2 import DuelConfig, duel

# Host/port live in config.STRENGTH_API_HOST/PORT; the `mythgauntlet serve` CLI reads them there.


class AnalyzeRequest(BaseModel):
    deck: str = Field(description="decklist text (plain/Moxfield-ish, Commander: section)")
    name: str = "deck"
    runs: int = Field(default=1000, ge=1, le=50_000)
    seed: int = 42
    turns: int = Field(default=DEFAULT_ANALYZE_TURNS, ge=1, le=30)
    collection: str | None = Field(
        default=None, description="optional collection text (CSV or decklist) for ownership"
    )
    use_suite_collection: bool = Field(
        default=True,
        description="when no collection text is given, fall back to the default collection file "
        "(~/Documents/MythSuite/collection.csv) if present",
    )
    resilience: bool = Field(
        default=True, description="also run the Tier-1 board-wipe resilience pass"
    )
    combos: bool = Field(
        default=False,
        description="also run the Commander Spellbook combo gate (a cached network lookup): "
        "grades in-deck game-ending combos and feeds the bracket. Off by default so the "
        "endpoint stays network-free unless the caller opts in.",
    )


class CardImpactRequest(BaseModel):
    deck: str = Field(description="decklist text (plain/Moxfield-ish, Commander: section)")
    card: str = Field(description="the single card name to evaluate against this deck")
    name: str = "deck"
    runs: int = Field(default=200, ge=1, le=5_000)
    seed: int = 42
    turns: int = Field(default=DEFAULT_ANALYZE_TURNS, ge=1, le=30)
    cut_pool: int = Field(
        default=3, ge=1, le=10,
        description=(
            "cut candidates the addition is tested against; the best pairing wins. Chosen "
            "by REDUNDANCY (what the deck over-supplies), not by what is least played."
        ),
    )
    themes: list[str] = Field(
        default_factory=list,
        description=(
            "the deck's OWN detected archetypes (Forge's deck_themes.detect_deck_themes). "
            "Same contract as /advise: raises the redundancy targets for roles that "
            "archetype really plays, so the card is not tested against the deck's own plan. "
            "Unknown names are ignored."
        ),
    )


class AdviseRequest(BaseModel):
    deck: str = Field(description="decklist text (plain/Moxfield-ish, Commander: section)")
    name: str = "deck"
    axis: str | None = Field(
        default=None, description="target Power Profile axis; None = the deck's weakest"
    )
    runs: int = Field(default=300, ge=1, le=5_000)
    seed: int = 42
    turns: int = Field(default=DEFAULT_ANALYZE_TURNS, ge=1, le=30)
    top: int = Field(default=5, ge=1, le=20)
    max_eval: int = Field(default=8, ge=1, le=40)
    min_delta: float = Field(
        default=1.0, ge=0.0, le=50.0,
        description=(
            "minimum measured axis gain for a swap to be reported. Raised automatically to "
            "the target axis's own seed-to-seed spread when that is higher (speed 1.7, "
            "ceiling 2.3), so a request can tighten this bar but never drop it below the "
            "noise. The floor actually applied comes back as the report's min_delta."
        ),
    )
    cut_pool: int = Field(
        default=3, ge=1, le=10,
        description=(
            "cut candidates each add is tested against (1 = single global cut). Quality "
            "rises monotonically with this and cost is linear, so it is a latency dial, "
            "not an optimum: measured 7/20 decks helped at 1, 9/20 at 3, 13/20 at 8. "
            "See advisor.advise for the full sweep."
        ),
    )
    collection: str | None = Field(
        default=None,
        description="optional collection text (CSV or decklist); default = the collection file",
    )
    use_suite_collection: bool = True
    themes: list[str] = Field(
        default_factory=list,
        description=(
            "the deck's OWN detected archetypes (Forge's deck_themes.detect_deck_themes), "
            "as plain strings - e.g. ['spellslinger']. Raises the redundancy targets for "
            "roles that archetype really plays, so the deck is not offered its own plan as "
            "the cut pool: a spellslinger deck is judged against the 12 counterspells such "
            "decks run, not the population's 3. Unknown names are ignored; omitting the "
            "field judges against the population, which is correct but blunter. Ignored "
            "when the cut strategy is 'popularity'."
        ),
    )


class DuelRequest(BaseModel):
    deck_a: str
    deck_b: str
    name_a: str = "deck_a"
    name_b: str = "deck_b"
    games: int = Field(default=200, ge=1, le=10_000)
    seed: int = 42
    turns: int = Field(default=30, ge=5, le=100)
    life: int = Field(default=40, ge=1)


class PodRequest(BaseModel):
    deck: str
    name: str = "deck"
    games: int = Field(default=40, ge=1, le=2_000)
    seed: int = 42
    turns: int = Field(default=30, ge=5, le=100)
    life: int = Field(default=40, ge=1)
    players: int = Field(default=4, ge=2, le=6)


def _combos_block(
    report: spellbook.ComboReport | None,
    profile,  # ComboAssessment | None
    checked: bool,
) -> dict:
    """Serialise the graded combo assessment for API clients (the combos block)."""
    if not checked or report is None or profile is None:
        return {"checked": checked, "total": 0, "items": []}
    items = []
    for g in profile.grades:
        det = g.determinism
        items.append({
            "cards": list(g.combo.cards),
            "produces": list(g.combo.produces),
            "pieces": g.pieces,
            "mana_value": g.mana_value,
            "terminal": g.terminal,
            "needs_commander": g.needs_commander,
            "reliability": g.reliability,
            "spellbook_tag": g.spellbook_tag,
            "deterministic": None if det is None else det.deterministic,
            "determinism_reason": None if det is None else det.reason,
            "determinism_rule": None if det is None else det.rule,
            "note": g.note,
        })
    return {
        "checked": True,
        "total": profile.total,
        "two_card": report.two_card_count,
        "terminal": profile.terminal_count,
        "advantage": profile.advantage_count,
        "nondeterministic": profile.nondeterministic_count,
        "fast_terminal_two_card": profile.fast_terminal_two_card,
        "almost_included": len(report.almost_included),
        "items": items,
    }


def _insight_block(insight) -> dict | None:
    """Serialise the deck-specific narrative (archetype/gameplan/why/cards/verdict) for the UI."""
    if insight is None:
        return None
    return {
        "archetype": insight.archetype,
        "gameplan": insight.gameplan,
        "pod_read": insight.pod_read,
        "strengths": insight.strengths,
        "weaknesses": insight.weaknesses,
        "why": insight.axis_why,
        "key_cards": [
            {"role": kc.role, "names": kc.names, "more": kc.more} for kc in insight.key_cards
        ],
    }


def _resolve_or_400(text: str, name: str, db: scryfall.CardDb) -> ResolvedDeck:
    resolved = resolve(Deck.parse_text(text, name=name), db)
    if not resolved.cards:
        raise HTTPException(status_code=400, detail=f"{name}: no cards resolved")
    return resolved


def create_app(
    db: scryfall.CardDb | None = None, store: SemanticsStore | None = None
) -> FastAPI:
    app = FastAPI(title="MythGauntlet strength API", version=__version__)
    db = db if db is not None else scryfall.load_card_db()
    store = store if store is not None else load_store()  # cached; ~35s cold, else instant

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "engine_version": __version__,
            "cards_in_store": len(db),
            "semantics_entries": len(store),
            "semantics_load_warnings": len(store.skipped),
        }

    @app.post("/analyze")
    def analyze(req: AnalyzeRequest) -> dict:
        resolved = _resolve_or_400(req.deck, req.name, db)
        commander = resolved.commanders[0] if resolved.commanders else None
        cfg = SimConfig(turns=req.turns, runs=req.runs, seed=req.seed)
        # Combos are an opt-in network lookup (cached by decklist hash). When requested we
        # fetch + grade them so the bracket gate and the panel reflect them; a Spellbook
        # outage degrades gracefully to the combo-free analysis rather than 500-ing.
        combo_report = None
        combos_checked = False
        if req.combos:
            names = [(c.name, n) for c, n in resolved.cards]
            try:
                combo_report = spellbook.find_combos(
                    names, [c.name for c in resolved.commanders]
                )
                combos_checked = True
            except requests.RequestException:
                combo_report = None  # network down -> analyze without the combo gate
        a = analyze_deck(
            resolved, cfg, store, combo_report=combo_report,
            combos_checked=combos_checked, run_resilience=req.resilience,
        )
        report, coverage, interaction, ceiling = a.report, a.coverage, a.interaction, a.ceiling
        game_changers = a.game_changers

        resilience = None
        if a.resilience is not None:
            resilience = {
                "score": a.resilience.resilience_score,
                "wipe_turn": a.wipe_turn,
                "clean_kill_rate": a.resilience.clean_kill_rate,
                "wiped_kill_rate": a.resilience.wiped_kill_rate,
                "kill_delay_turns": a.resilience.kill_delay_turns,
            }

        # A compact, frontend-friendly Power Profile (the measured differentiators).
        power_profile = {
            "consistency": round(report.consistency_score, 1),
            "speed_kill_rate": report.goldfish_kill_rate,
            "speed_avg_kill_turn": report.avg_kill_turn,
            "resilience": round(resilience["score"], 1) if resilience else None,
            "interaction": round(interaction.score, 1),
            "interaction_answers": interaction.answers,
            "interaction_effective_answers": interaction.effective_answers,
            "ceiling": round(ceiling.score, 1),
            "pod": round(a.pod.score, 1),
            "pod_opponents": a.pod.opponents,
            "pod_close_turn": a.pod.pod_close_turn,
            "pod_close_rate": a.pod.pod_close_rate,
            "pod_duel_close_rate": a.pod.duel_close_rate,
            "pod_via_finisher": a.pod.via_finisher,
            "go_off": a.go_off.goes_off,
            "go_off_turn": a.go_off.earliest_turn,
            "overrun_alpha": a.overrun.can_alpha_strike,
            "semantics_coverage": coverage.executable_share,
            "game_changers": len(game_changers),
            "bracket_hint": metrics.game_changer_bracket_hint(len(game_changers)),
            "bracket_estimate": a.bracket.bracket,
            "bracket_label": a.bracket.label,
            "bracket_confidence": round(a.bracket.confidence, 2),
            "bracket_plays_up": a.bracket.plays_up,  # Core-capped but at the B2/B3 boundary
            "bracket_reasons": a.bracket.reasons,  # why this bracket (gates that fired)
            "combos_checked": combos_checked,
        }

        ownership = None
        col = None
        source = None
        if req.collection:
            col = Collection.parse(req.collection)
            source = "request"
        elif req.use_suite_collection and suite_collection_path().exists():
            try:
                col = Collection.load(suite_collection_path())  # contract C1 default
                source = "suite"
            except (OSError, UnicodeDecodeError):
                col = None  # sibling file locked/corrupt -> skip ownership, don't 500
        if col is not None:
            owned = 0
            missing = []
            for card, count in resolved.cards + [(c, 1) for c in resolved.commanders]:
                have = min(count, col.owned(card.name))
                owned += have
                if have < count:
                    missing.append({"name": card.name, "need": count - have})
            ownership = {
                "owned": owned,
                "total": resolved.card_count,
                "missing": missing,
                "source": source,
            }

        return {
            "engine_version": __version__,
            "tier": "T0",
            "deck": {
                "name": req.name,
                "cards": resolved.card_count,
                "commander": commander.name if commander else None,
                "unresolved": resolved.missing,
            },
            "report": dataclasses.asdict(report),
            "resilience": resilience,
            "power_profile": power_profile,
            "semantics_coverage": {
                "executable_share": coverage.executable_share,
                "rung3": coverage.rung3,
                "rung2": coverage.rung2,
                "rung1": coverage.rung1,
            },
            "game_changers": game_changers,
            "bracket_hint": metrics.game_changer_bracket_hint(len(game_changers)),
            "ownership": ownership,
            "insight": _insight_block(a.insight),  # deck-specific narrative for the UI
            "combos": _combos_block(combo_report, a.combo_profile, combos_checked),
        }

    @app.post("/card-impact")
    def run_card_impact(req: CardImpactRequest) -> dict:
        """Would ONE named card help or hurt this deck, and why.

        The inverse of /advise: instead of proposing cards from a pool, it answers the
        question a player actually asks — "is <card> good in my deck?". Legality is checked
        first and is disqualifying (an off-colour or banned card is a hard no, whatever its
        power), then the card is swapped in for each of a small pool of REDUNDANT slots -
        the roles the deck over-supplies - and the whole Power Profile is re-measured. Any
        axis move smaller than that axis's own seed-to-seed spread is reported as NO effect
        rather than as an improvement.

        Pass `themes` for the same reason /advise takes them: without the deck's archetypes
        the cut pool is judged against one population baseline and can offer the deck its
        own plan as the slot to displace.
        """
        resolved = _resolve_or_400(req.deck, req.name, db)
        card = db.get(req.card)
        if card is None:
            raise HTTPException(
                status_code=404,
                detail=f"No card named '{req.card}' in the card store. Check the spelling, "
                       "or run `mythgauntlet fetch-data` if it is a very recent printing.",
            )
        cfg = SimConfig(turns=req.turns, runs=req.runs, seed=req.seed)
        imp = card_impact.assess_card(resolved, card, cfg, store,
                                      cut_pool=req.cut_pool, themes=req.themes)
        return {
            "engine_version": __version__,
            "card": imp.card,
            "verdict": imp.verdict,
            "headline": imp.headline,
            "reasons": imp.reasons,
            "legal": imp.legal,
            "already_in_deck": imp.already_in_deck,
            "cut": imp.cut,
            "axes": [
                {
                    "axis": m.axis,
                    "label": m.label,
                    "before": round(m.before, 1),
                    "after": round(m.after, 1),
                    "delta": round(m.delta, 1),
                    "meaningful": m.meaningful,
                    "noise_floor": m.floor,
                }
                for m in imp.axes
            ],
        }

    @app.post("/advise")
    def run_advise(req: AdviseRequest) -> dict:
        """Owned-card swaps that measurably improve an axis (upgrade advisor, ablation).

        Mirrors the `advise` CLI verb: candidates are cards the user OWNS (request text or
        the default collection file), nonland, inside the deck's colour identity, not already
        in the deck — each is tested against a `cut_pool` of the deck's most REDUNDANT
        nonland cards (the roles it over-supplies, weakest contributor first) and keeps the
        cut it improves the axis most from, so every suggestion is a measured delta, never
        popularity. `cut_strategy` in the response names the rule that chose those cuts.

        Pass `themes` when the caller knows the deck's archetypes - without them a deck is
        judged against one population baseline and reads as over-supplied in exactly what it
        is trying to do. The engine cannot detect them itself: the detector lives in Forge.
        """
        if req.axis is not None and req.axis not in advisor.AXES:
            raise HTTPException(
                status_code=400,
                detail=f"unknown axis '{req.axis}'; choose one of: {', '.join(advisor.AXES)}",
            )
        resolved = _resolve_or_400(req.deck, req.name, db)

        col = None
        source = None
        if req.collection:
            col = Collection.parse(req.collection)
            source = "request"
        elif req.use_suite_collection and suite_collection_path().exists():
            try:
                col = Collection.load(suite_collection_path())  # contract C1 default
                source = "suite"
            except (OSError, UnicodeDecodeError):
                col = None
        if col is None:
            raise HTTPException(
                status_code=400,
                detail="The advisor suggests from cards you OWN - provide 'collection' "
                "text, or place a collection file at ~/Documents/MythSuite/collection.csv.",
            )

        ci_source = resolved.commanders or [c for c, _ in resolved.cards]
        deck_ci = (
            set().union(*[set(c.color_identity) for c in ci_source]) if ci_source else set()
        )
        in_deck = {c.name for c, _ in resolved.cards} | {c.name for c in resolved.commanders}
        candidates = []
        for owned_name in col.counts:
            card = db.get(owned_name)
            if card is None or card.name in in_deck or card.is_land:
                continue
            if set(card.color_identity) - deck_ci:
                continue
            candidates.append(card)
        candidates.sort(key=lambda c: (c.edhrec_rank or 10**9))  # best owned cards first

        cfg = SimConfig(turns=req.turns, runs=req.runs, seed=req.seed)
        report = advisor.advise(
            resolved, cfg, store, candidates,
            axis=req.axis, top=req.top, max_eval=req.max_eval, cut_pool=req.cut_pool,
            min_delta=req.min_delta, themes=req.themes,
        )
        return {
            "engine_version": __version__,
            "axis": report.axis,
            "axis_label": report.axis_label,
            "baseline": round(report.baseline, 1),
            "cut": report.cut,
            "evaluated": report.evaluated,
            "analyses": report.analyses,
            "cut_pool": report.cut_pool,
            "cut_strategy": report.cut_strategy,
            "min_delta": report.min_delta,
            "candidates_that_fit": len(candidates),
            "collection_source": source,
            "suggestions": [
                {
                    "add": s.add,
                    "cut": s.cut,
                    "before": round(s.before, 1),
                    "after": round(s.after, 1),
                    "delta": round(s.delta, 1),
                    "reason": s.reason,
                }
                for s in report.suggestions
            ],
        }

    @app.post("/duel")
    def run_duel(req: DuelRequest) -> dict:
        res_a = _resolve_or_400(req.deck_a, req.name_a, db)
        res_b = _resolve_or_400(req.deck_b, req.name_b, db)
        cfg = DuelConfig(
            games=req.games, seed=req.seed, max_turns=req.turns, start_life=req.life
        )
        result = duel(
            res_a.cards, res_a.commanders[0] if res_a.commanders else None,
            res_b.cards, res_b.commanders[0] if res_b.commanders else None,
            cfg, store=store,
        )
        return {
            "engine_version": __version__,
            "tier": "T2-mvp",
            "names": [req.name_a, req.name_b],
            "result": dataclasses.asdict(result),
            "winrate_a": result.winrate_a,
        }

    # The pod opponent field (the corpus) is static per server -> prepare it once, lazily.
    # Combo win-conditions are skipped for the field (offline/fast); the deck too, for parity.
    _pod_field: list = []

    def _pod_opponents():
        from mythgauntlet.ratings.pod import prepare_seat
        if _pod_field:
            return _pod_field
        for path in sorted(corpus_dir().glob("*.txt")):
            try:
                res = resolve(Deck.parse_text(path.read_text(encoding="utf-8"), name=path.stem), db)
            except OSError:
                continue
            if res.cards:
                _pod_field.append((
                    path.stem,
                    prepare_seat(res.cards, res.commanders[0] if res.commanders else None, store),
                ))
        return _pod_field

    @app.post("/pod")
    def run_pod(req: PodRequest) -> dict:
        from mythgauntlet.ratings.pod import pod_winrate, prepare_seat
        res = _resolve_or_400(req.deck, req.name, db)
        opponents = [seat for name, seat in _pod_opponents() if name != req.name]
        if not opponents:
            raise HTTPException(status_code=422, detail="no corpus opponents available for a pod")
        deck_seat = prepare_seat(
            res.cards, res.commanders[0] if res.commanders else None, store
        )
        cfg = DuelConfig(max_turns=req.turns, start_life=req.life)
        rating = pod_winrate(
            deck_seat, opponents, cfg, games=req.games, seed=req.seed, pod_size=req.players,
        )
        return {
            "engine_version": __version__,
            "tier": "T2-multiplayer",
            "name": req.name,
            "opponents": len(opponents),
            "rating": dataclasses.asdict(rating),
        }

    return app
