"""Deck insight: turn the measured numbers into a deck-SPECIFIC narrative.

The Power Profile is a set of scores; on its own it reads generic. This layer answers the
questions a player actually asks -- *what is my deck, how does it win, which cards drive each
axis, and why is each score what it is* -- by reading the same rung-1 effect vectors and the
computed analysis, no new simulation. Pure and deterministic (a function of the deck + the
analysis), shared by the CLI report and the /analyze API so both tell the same story.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mythgauntlet.model.card import Card
from mythgauntlet.model.deck import ResolvedDeck
from mythgauntlet.semantics import tags
from mythgauntlet.semantics.model import EffectVector

_MAX_NAMES = 6  # cards to name per role before "+N more"


@dataclass
class KeyCards:
    role: str            # e.g. "Interaction", "Ramp", "Card advantage", "Win conditions"
    names: list[str]     # representative cards (most-played first)
    more: int = 0        # additional cards of this role beyond `names`


@dataclass
class DeckInsight:
    archetype: str                 # e.g. "Go-wide / tokens", "Spellslinger / storm"
    gameplan: str                  # one/two lines: what it does + how it wins
    pod_read: str = ""             # plain-English "which pod does this belong in?" placement
    key_cards: list[KeyCards] = field(default_factory=list)
    axis_why: dict[str, str] = field(default_factory=dict)  # axis -> one-line "why the score"
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)


# --- helpers -----------------------------------------------------------------------------


def _rank(card: Card) -> int:
    return card.edhrec_rank if card.edhrec_rank is not None else 10**9


def _named(cards: list[tuple[Card, int, EffectVector]], keep) -> list[Card]:
    """The cards matching `keep(fx, card)`, most-played (lowest EDHREC rank) first. Empty if
    none match. The caller (`add`) wraps a non-empty result into a KeyCards with its role."""
    hits = [c for c, _n, fx in cards if keep(fx, c)]
    hits.sort(key=_rank)
    return hits


def _turn(t: float | None) -> str:
    return f"T{t:.0f}" if t is not None else "n/a"


# --- the build ---------------------------------------------------------------------------


def build_insight(resolved: ResolvedDeck, a) -> DeckInsight:
    """`a` is a DeckAnalysis (duck-typed to avoid a circular import)."""
    commander = resolved.commanders[0] if resolved.commanders else None
    cmd = commander.name if commander else "no commander"

    nonland = [(c, n, tags.analyze(c)) for c, n in resolved.cards if not c.is_land]
    creatures = sum(n for c, n, _ in nonland if c.is_creature)

    def count(keep) -> int:
        return sum(n for c, n, fx in nonland if keep(fx, c))

    removal = count(lambda fx, c: fx.removal > 0 and not fx.board_wipe)
    wipes = count(lambda fx, c: fx.board_wipe)
    counters = count(lambda fx, c: fx.counterspell)
    ramp = count(lambda fx, c: fx.ramp_sources > 0 or fx.fetches_land)
    tutors = count(lambda fx, c: fx.tutor)

    has_combo = bool(getattr(a.ceiling, "has_game_ending_combo", False)) or bool(
        a.combo_profile and getattr(a.combo_profile, "terminal_count", 0)
    )
    storm = a.go_off.goes_off
    gowide = a.overrun.can_alpha_strike

    # --- archetype + gameplan ---
    if has_combo:
        archetype = "Combo"
    elif storm:
        archetype = "Spellslinger / storm"
    elif gowide:
        archetype = "Go-wide / tokens"
    elif (counters + wipes) >= 6 and creatures <= 22:
        archetype = "Control"
    elif creatures >= 30:
        archetype = "Creature aggro"
    elif ramp >= 12:
        archetype = "Ramp / midrange"
    else:
        archetype = "Midrange goodstuff"

    kill = a.report.avg_kill_turn
    fast = a.ceiling.fast_kill_turn
    if has_combo:
        wins = "assembles a game-ending combo to win outright"
    elif storm:
        go = _turn(a.go_off.earliest_turn)
        wins = f"chains cheap spells into a storm/magecraft burn finish (~{go})"
    elif gowide:
        wins = f"floods the board and closes with a team-pump alpha strike (~{_turn(fast)})"
    elif creatures >= 26:
        wins = f"races with creature combat (goldfish kill ~{_turn(kill)})"
    elif (counters + removal + wipes) >= 12:
        wins = "answers threats, then grinds out a slow win"
    else:
        wins = f"grinds value into a midrange finish (goldfish kill ~{_turn(kill)})"
    gameplan = (
        f"{cmd}: {archetype.lower()} deck with {creatures} creatures, {ramp} ramp, "
        f"{removal + wipes + counters} interaction pieces. It {wins}."
    )

    # --- named cards per role ---
    key_cards: list[KeyCards] = []

    def add(role: str, hits: list[Card] | None) -> None:
        if hits:
            key_cards.append(KeyCards(role, [c.name for c in hits[:_MAX_NAMES]],
                                      max(0, len(hits) - _MAX_NAMES)))

    add("Interaction",
        _named(nonland, lambda fx, c: fx.removal or fx.board_wipe or fx.counterspell))
    add("Ramp", _named(nonland, lambda fx, c: fx.ramp_sources > 0 or fx.fetches_land))
    add("Card advantage", _named(nonland, lambda fx, c: fx.draw_cards >= 2 or fx.engine_draw))
    add("Tutors", _named(nonland, lambda fx, c: fx.tutor))
    # win conditions: combo pieces if known, else finisher-shaped cards + biggest creatures
    combo_names: list[str] = []
    if a.combo_profile is not None:
        for g in getattr(a.combo_profile, "grades", [])[:3]:
            combo_names.extend(getattr(g.combo, "cards", []))
    finishers = _named(nonland, lambda fx, c: (
        fx.overrun_pump > 0 or fx.scaling_burn or fx.grants_storm or fx.cheats_creatures
        or (c.is_creature and c.mana_value >= 5 and _stat(c.power) >= 6)
    ))
    win_names = list(dict.fromkeys(combo_names))[:_MAX_NAMES]
    if win_names:
        key_cards.append(KeyCards("Win conditions (combo)", win_names,
                                  max(0, len(set(combo_names)) - len(win_names))))
    elif finishers:
        add("Win conditions", finishers)

    # --- why per axis ---
    r = a.report
    cmd_t = _turn(r.avg_commander_turn)
    why: dict[str, str] = {
        "Consistency": (
            f"commander online ~{cmd_t} in {r.commander_cast_rate:.0%} of games, curve "
            f"{r.curve_efficiency:.0%} efficient, keeps {r.keep_rate:.0%} of opening sevens"
        ),
        "Speed": (
            f"goldfish kill ~{_turn(kill)} in {r.goldfish_kill_rate:.0%} of games"
            if r.goldfish_kill_rate else "no reliable unopposed kill within the horizon (grindy)"
        ),
        "Interaction": (
            f"{a.interaction.effective_answers:g} castable answers -- "
            f"{removal} removal, {counters} counters, {wipes} wipes "
            f"(breadth {a.interaction.breadth}/3)"
        ),
        "Ceiling": _ceiling_why(a, fast, has_combo, storm, gowide),
        "Pod (multiplayer)": _pod_why(a),
    }
    if a.resilience is not None:
        why["Resilience"] = (
            f"retains {a.resilience.resilience_score:.0f}/100 through a T{a.wipe_turn} board wipe "
            + ("(non-creature ramp/engines survive)" if a.resilience.resilience_score >= 65
               else "(creature-reliant -- a wipe sets it back hard)")
        )

    # --- strengths / weaknesses ---
    strengths, weaknesses = _verdict(
        a, removal, counters, wipes, ramp, tutors, creatures, has_combo)

    return DeckInsight(
        archetype=archetype, gameplan=gameplan, pod_read=_pod_read(a),
        key_cards=key_cards, axis_why=why, strengths=strengths, weaknesses=weaknesses,
    )


def _pod_read(a) -> str:
    """Plain-English placement for the casual question 'which pod does this belong in?'.

    Reads the bracket estimate (and its `plays_up` boundary flag) into pod-fit advice. This is
    the deck's headline casual takeaway; the bracket number + gate reasons print separately.
    """
    b = a.bracket
    if b.bracket == 1:
        return ("Exhibition (Bracket 1) -- casual and unoptimized; ideal for relaxed or "
                "new-player tables.")
    if b.bracket == 2:
        if b.plays_up:
            return ("Core leaning Upgraded (Bracket 2-3) -- a tuned, above-precon build. It "
                    "holds its own in a Bracket 3 pod and may feel a step ahead of a precon "
                    "table; the Core/Upgraded line is a judgment call (see the axes).")
        return ("Core (Bracket 2) -- roughly precon-level power; a fair fit for a casual "
                "Bracket 2 pod.")
    if b.bracket == 3:
        return ("Upgraded (Bracket 3) -- beyond precon power. Belongs in a Bracket 3 pod and "
                "can pubstomp casual Bracket 2 tables.")
    if b.bracket == 4:
        return ("Optimized (Bracket 4) -- high-power. Bring it to a Bracket 4 pod; it will "
                "overwhelm casual tables.")
    return ("cEDH (Bracket 5) -- built to win fast and disrupt. cEDH tables only.")


def _stat(v) -> int:
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return 0


def _ceiling_why(a, fast, has_combo, storm, gowide) -> str:
    if has_combo:
        return "a game-ending combo can win outright -- the nut draw isn't the combat clock"
    if storm:
        return f"a storm/magecraft go-off can win ~{_turn(a.go_off.earliest_turn)} off the clock"
    if gowide:
        return "a wide board + a one-shot team pump can alpha-strike for lethal"
    if a.ceiling.score <= 0:
        return f"no combo and no fast finisher -- the best draw still wins by combat ~{_turn(fast)}"
    return f"best draws kill ~{_turn(fast)}; no combo/finisher to go over the top"


def _pod_why(a) -> str:
    p = a.pod
    if p.pod_close_turn is None:
        return ("can't generate table-lethal pressure unopposed -- "
                "struggles to close a 4-player game")
    tail = ("; a game-ending combo can close the whole table" if p.via_finisher
            else "; no combo to close faster than combat")
    return (f"reaches table-lethal capacity ~T{p.pod_close_turn:.0f} in {p.pod_close_rate:.0%} of "
            f"games (vs {p.duel_close_rate:.0%} for a single opponent){tail}")


def _verdict(a, removal, counters, wipes, ramp, tutors, creatures, has_combo):
    strengths: list[str] = []
    weaknesses: list[str] = []
    r, cons = a.report, a.report.consistency_score

    if cons >= 70:
        t = _turn(r.avg_commander_turn)
        strengths.append(f"Consistent engine ({cons:.0f}/100) -- commander lands ~{t}")
    elif cons < 50:
        weaknesses.append(f"Shaky consistency ({cons:.0f}/100) -- mulligans/curve stumble")

    answers = removal + counters + wipes
    if a.interaction.score >= 55:
        strengths.append(f"Deep interaction ({answers} answers, {a.interaction.breadth}/3 types)")
    elif a.interaction.score < 30:
        weaknesses.append(f"Thin interaction (only {answers} answers) -- light on removal/counters")

    if a.ceiling.score >= 45 or has_combo:
        strengths.append("High ceiling -- a real fast/combo finish" if has_combo
                         else f"High ceiling ({a.ceiling.score:.0f}/100)")
    elif a.ceiling.score <= 5:
        weaknesses.append("Low ceiling -- no fast finish; wins slowly by combat")

    if a.resilience is not None and a.resilience.resilience_score >= 65:
        strengths.append(f"Resilient to wipes ({a.resilience.resilience_score:.0f}/100)")
    elif a.resilience is not None and a.resilience.resilience_score < 40:
        weaknesses.append(f"Folds to board wipes ({a.resilience.resilience_score:.0f}/100)")

    if a.pod.pod_close_turn is None:
        weaknesses.append("No multiplayer closing power -- can't pressure a full table")
    elif a.pod.score >= 55:
        strengths.append(f"Strong multiplayer closing power ({a.pod.score:.0f}/100)")

    if ramp >= 12 and creatures < 20 and not has_combo:
        weaknesses.append("Lots of ramp but few payoffs -- may ramp into nothing")

    return strengths[:4], weaknesses[:4]
