"""Strong and weak cards, each with the number that backs it (B31, SPEC_deck_scouting_report.md).

Built on the per-card goldfish evidence (`card_stats`, B30), the graded combos, the commander
lens and the redundancy model. The rules below are not tuning: each one follows from what the
instruments can and cannot see, measured and hand-reviewed on 8 real decks (2026-11-07; spec
section 6).

STRONG
  speeds_kill        significant early_uplift >= SPEEDS_MIN turns, "in unopposed games".
  combo_piece        a card in a graded game-ending combo the deck holds.
  commander_synergy  the commander lens proves the commander changes what this card does.

WEAK (a card named strong is never also named weak)
  stranded           still in hand at the horizon in >= STRANDED_MIN of the games it is drawn,
                     with the reason tier0 recorded: the COLOURS (enough mana, wrong pips), the
                     COST (never that much mana), or OUTRANKED (castable, but the goldfish always
                     had a better play). Outranked is only said of a card the goldfish can fully
                     read and that is not interaction: an unopposed game has nothing to answer.
  slows_kill         significant early_uplift <= -SLOWS_MIN, only for a card whose job is the clock
                     (ramp, finisher, or a plain body) AND that the goldfish can fully read. The
                     bottom of the uplift list on real decks was protection, wipes, Smothering
                     Tithe, token doublers and draw engines: blind spots, not weak cards.
  redundant          its role is over-supplied in CARDS (role_card_counts vs card targets), and the
                     redundancy model ranks it the most replaceable there.

Commander and partner cards are never named as weak.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mythgauntlet.model.card import Card
from mythgauntlet.model.deck import ResolvedDeck
from mythgauntlet.ratings import redundancy
from mythgauntlet.ratings.card_stats import CardStat, significant
from mythgauntlet.semantics import tags
from mythgauntlet.sim.tier0 import _anthems_in_text

SPEEDS_MIN = 0.30      # turns; below this a significant effect is real but not worth a sentence
SLOWS_MIN = 0.25
STRANDED_MIN = 0.25    # calibration: deck p90 0.04-0.44, so this names 0-4 cards per deck
STRANDED_MIN_DRAWN = 200
MAJORITY = 0.5         # a stranded reason is stated when it covers most stranded games
MAX_SPEEDS = 5
MAX_STRANDED = 4
MAX_SLOWS = 3
MAX_REDUNDANT = 3

# Roles whose value an unopposed race cannot show (B30 finding).
_INTERACTION = frozenset({"removal", "noncreature_removal", "wipe", "counterspell"})
# Roles whose job IS the clock: the only ones "slows the kill" may be said of. Draw and tutors
# pay off later than a 12-turn unopposed race (Phyrexian Arena read -0.4 there).
_CLOCK_ROLES = frozenset({"ramp", "finisher"})

# EffectVector fields tier0 executes (sim/tier0.py apply_effects / _effective_cost).
_MODELLED = ("ramp_sources", "fetches_land", "draw_cards", "engine_draw", "cheats_creatures",
             "magecraft_damage", "cast_damage", "scaling_burn", "ritual_mana",
             "self_reduction_per_creature")
# Fields the tagger sets that tier0 ignores (or uses only in the separate nut-kill pass).
_INVISIBLE = ("tutor", "removal", "board_wipe", "counterspell", "noncreature_removal",
              "mana_on_cast", "spell_cost_reduction", "treasure_ramp", "cost_reduction",
              "top_of_library", "impulse_draw", "impulse_engine", "alt_win", "extra_combat",
              "overrun_pump", "overrun_scales", "grants_storm", "team_anthem")
_REMINDER = re.compile(r"\([^)]*\)")


def _ability_lines(card: Card) -> list[str]:
    """Rules-text lines that are not bare keyword lines ("Flying, haste", "Ward {2}")."""
    kws = {k.lower() for k in card.keywords}
    out = []
    for raw in _REMINDER.sub("", card.oracle_text or "").splitlines():
        line = raw.strip().rstrip(".").strip()
        if not line:
            continue
        parts = [p.strip().lower() for p in re.split(r"[,;]", line) if p.strip()]
        if parts and all(any(p == k or p.startswith(k + " ") for k in kws) for p in parts):
            continue
        out.append(line)
    return out


def goldfish_legible(card: Card) -> bool:
    """Does the goldfish model everything this card does? Only then may it be called weak on a
    goldfish figure. No effect the sim ignores, and either nothing beyond keywords (a body) or
    a single ability the sim executes (a mana rock, a cantrip, a flat anthem)."""
    fx = tags.analyze(card)
    if any(getattr(fx, f) for f in _INVISIBLE):
        return False
    lines = _ability_lines(card)
    if not lines:
        return True
    modelled = any(getattr(fx, f) for f in _MODELLED) or bool(_anthems_in_text(card.oracle_text))
    return len(lines) == 1 and modelled


@dataclass(frozen=True)
class Verdict:
    name: str
    kind: str
    text: str
    evidence: dict = field(default_factory=dict)


def _fmt_turns(x: float) -> str:
    return f"{abs(x):.1f} turn{'s' if abs(x) >= 1.05 else ''}"


def build(resolved: ResolvedDeck, stats: list[CardStat], *, lens=None, combo_profile=None,
          targets: dict[str, int] | None = None, card_targets: dict[str, int] | None = None,
          turns: int = 12, ranking=None) -> dict:
    """{"strong": [Verdict...], "weak": [Verdict...], "instrument": str}.

    `ranking` (ratings/cut_ranking.CutRanking, 2026-11-10): when given, "speeds the kill" is the
    paired drawn-games measurement (not the early-window uplift, which favoured cheap cards) and
    the weak list after "stranded" is the SAME ordered cut list Advise and the mentor's role
    swaps use -- one answer to "what should I cut?" everywhere."""
    cards, commanders = resolved.cards, resolved.commanders
    by_name = {c.name: c for c, _ in cards}
    zone = {c.name for c in commanders}
    roles = {c.name: set(redundancy.roles_for(c, lens)) for c, _ in cards if not c.is_land}
    strong: list[Verdict] = []
    weak: list[Verdict] = []

    # ── strong ───────────────────────────────────────────────────────────────────────────
    if ranking is not None:
        helps = sorted((v for v in ranking.values.values() if v.load_bearing),
                       key=lambda v: (-v.turns_sooner, v.name))
        for v in helps[:MAX_SPEEDS]:
            strong.append(Verdict(v.name, "speeds_kill",
                                  f"{v.name}: the deck kills {_fmt_turns(v.turns_sooner)} sooner "
                                  f"with it in the {v.games} games it is drawn (paired "
                                  f"simulation, unopposed)",
                                  {"turns_sooner": v.turns_sooner, "ci90": list(v.ci90),
                                   "games_drawn": v.games}))
    speeds = [] if ranking is not None else [
        s for s in stats if not s.is_land and s.name not in zone and significant(s)
        and s.early_uplift >= SPEEDS_MIN]
    for s in sorted(speeds, key=lambda s: -s.early_uplift)[:MAX_SPEEDS]:
        strong.append(Verdict(s.name, "speeds_kill",
                              f"{s.name}: when it shows up by turn 3 the deck kills "
                              f"{_fmt_turns(s.early_uplift)} sooner in unopposed games",
                              {"early_uplift": s.early_uplift, "ci90": list(s.uplift_ci),
                               "games_early": s.n_early}))

    if combo_profile is not None:
        seen: set[str] = set()
        for g in combo_profile.grades:
            for n in g.combo.cards:
                if n in zone or n in seen or n not in by_name:
                    continue
                seen.add(n)
                others = ", ".join(x for x in g.combo.cards if x != n)
                strong.append(Verdict(n, "combo_piece",
                                      f"{n}: piece of a game-ending combo with {others} "
                                      f"({g.note})",
                                      {"combo": list(g.combo.cards), "terminal": g.terminal,
                                       "needs_commander": g.needs_commander,
                                       "reliability": g.reliability}))

    if lens is not None:
        for card, _ in cards:
            if card.is_land or card.name in zone:
                continue
            facts = lens.facts_for(card)
            if not facts.empty and facts.reason:
                strong.append(Verdict(card.name, "commander_synergy",
                                      f"{card.name}: {facts.reason}",
                                      {"kind": facts.payoff_kind}))
    strong_names = {v.name for v in strong}

    # ── weak: stranded ───────────────────────────────────────────────────────────────────
    # A card the shared cut ranking protects (the deck measurably kills sooner with it, or it is
    # a plan card) is never named weak: the scouting report listed Ambulatory Reactor as
    # "stranded, always a better play" beside a ranking that keeps it (2026-11-10).
    kept = set(ranking.protected) if ranking is not None else set()
    stranded = [s for s in stats if not s.is_land and s.name not in zone
                and s.name not in strong_names and s.name not in kept and s.name in by_name
                and s.drawn >= STRANDED_MIN_DRAWN and s.stranded_rate >= STRANDED_MIN]
    for s in sorted(stranded, key=lambda s: -s.stranded_rate):
        if sum(v.kind == "stranded" for v in weak) >= MAX_STRANDED:
            break
        card = by_name[s.name]
        if s.stranded_colour_share >= MAJORITY:
            reason = "colour"
            why = (f"usually the colours, not the amount: there was enough mana for its cost "
                   f"but not the pips in {card.mana_cost_str}")
        elif s.stranded_cost_share >= MAJORITY:
            reason = "cost"
            why = f"it costs {card.mana_value} and the deck often never has that much mana"
        else:
            # Castable at the end, but the goldfish always ranked another play higher. For an
            # answer that is the no-opponent blind spot (nothing to answer): not said.
            if roles.get(s.name, set()) & _INTERACTION or not goldfish_legible(card):
                continue
            reason = "outranked"
            why = "it was castable, but there was always a better play to make first"
        weak.append(Verdict(s.name, "stranded",
                            f"{s.name}: still in hand at turn {turns} in "
                            f"{round(100 * s.stranded_rate)}% of the games it is drawn; {why}",
                            {"stranded_rate": s.stranded_rate, "reason": reason,
                             "colour_share": s.stranded_colour_share,
                             "cost_share": s.stranded_cost_share, "drawn": s.drawn}))

    if ranking is not None:
        named = {v.name for v in weak} | strong_names
        for c in [c for c in ranking.cuts if c.name not in named][:MAX_REDUNDANT]:
            ev = {"kind": c.kind}
            if c.value is not None:
                ev.update(turns_sooner=c.value.turns_sooner, ci90=list(c.value.ci90),
                          games_drawn=c.value.games)
            if c.role:
                ev.update(role=c.role, cards=c.role_cards, card_target=c.card_target)
            weak.append(Verdict(c.name, {"drag": "slows_kill", "surplus": "redundant",
                                         "idle": "idle"}[c.kind], f"{c.name}: {c.why}", ev))
        return {"strong": strong, "weak": weak,
                "instrument": "paired goldfish simulation (no opponent) for speeds/slows/idle; "
                              "Commander Spellbook for combos; commander lens for synergy; "
                              "role counts for surplus; interaction is only ever judged by "
                              "role count"}

    # ── weak: slows the kill ─────────────────────────────────────────────────────────────
    named = {v.name for v in weak} | strong_names
    slows = [s for s in stats if not s.is_land and s.name not in zone and s.name not in named
             and significant(s) and s.early_uplift <= -SLOWS_MIN and s.name in by_name
             and roles.get(s.name, set()) <= _CLOCK_ROLES
             and goldfish_legible(by_name[s.name])]
    for s in sorted(slows, key=lambda s: s.early_uplift)[:MAX_SLOWS]:
        weak.append(Verdict(s.name, "slows_kill",
                            f"{s.name}: the deck kills {_fmt_turns(s.early_uplift)} later "
                            "when it shows up early, in unopposed games",
                            {"early_uplift": s.early_uplift, "ci90": list(s.uplift_ci),
                             "games_early": s.n_early}))

    # ── weak: redundant ──────────────────────────────────────────────────────────────────
    # Ranked by the redundancy model (its own units) but only NAMED when the role is over-
    # supplied in CARDS, and stated in cards. The first cut said "24 against a target of 18"
    # in role-strength units, which read as a card count.
    named |= {v.name for v in weak}
    supply = redundancy.role_supply(resolved, lens)
    counts = redundancy.role_card_counts(resolved, lens)
    card_targets = card_targets or redundancy.card_targets_for(None)
    scored = []
    lords = redundancy.plan_lords(resolved)      # on-plan typed lords are never "redundant"
    for card, _ in cards:
        if card.is_land or card.name in zone or card.name in named or card.name in lords:
            continue
        sc = redundancy.score_card(card, supply, targets, lens)
        if (sc.oversupply > 0 and not sc.protected and sc.role
                and counts.get(sc.role, 0) > card_targets.get(sc.role, 10**6)):
            scored.append(sc)
    for rank, sc in enumerate(sorted(scored, key=lambda x: (-x.score, x.card.name))[:MAX_REDUNDANT]):
        have, want = counts[sc.role], card_targets[sc.role]
        which = "the most replaceable" if rank == 0 else f"#{rank + 1} most replaceable"
        weak.append(Verdict(sc.card.name, "redundant",
                            f"{sc.card.name}: the deck runs {have} {sc.role} cards against a "
                            f"typical {want}; the role model ranks this {which} of them",
                            {"role": sc.role, "cards": have, "card_target": want,
                             "oversupply": round(sc.oversupply, 2)}))

    return {"strong": strong, "weak": weak,
            "instrument": "goldfish (no opponent) for speeds/slows/stranded; Commander "
                          "Spellbook for combos; commander lens for synergy; role model for "
                          "redundancy"}
