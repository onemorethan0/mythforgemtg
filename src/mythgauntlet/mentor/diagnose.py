"""Why an axis scores what it does: its measured drivers and the fixed levers that move it
(PLAN_MENTOR_ADHOC D1).

Pure and deterministic: `diagnose` reads a flat dict of already-measured facts (built by
`mentor.tools._diagnose_facts` from the cached analysis -- no new simulation) and imports only
the per-bracket reference table. Drivers come from measured facts only. A driver's reading is
"strong" / "typical" / "weak": from the deck's bracket percentile band
(`ratings.reference.percentile_band`, p25/p75 are the edges) where the metric is in that table,
and from the fixed thresholds below otherwise (the corpus 25th/75th percentiles of the same
fact, measured 2026-09-30 over 866 decks, or 30 sampled for the simulated ones; the kill-turn,
kill-rate and resilience fallbacks are `mentor.verdicts`' own bands; docs/specs/mentor_adhoc/D1.md). Levers are fixed
template sentences keyed off weak drivers -- never generated, never naming a card.

Worked examples (the gold set, pinned in tests/engine/test_mentor_diagnose.py):

| call                                                                   | result                         |
|------------------------------------------------------------------------|--------------------------------|
| avg_kill_turn driver (6.0 / 9.0, lower is better), 5.5, no bracket      | ("strong", "fixed_threshold")  |
| same driver, 9.0, no bracket                                            | ("weak", "fixed_threshold")    |
| same driver, 7.0, no bracket                                            | ("typical", "fixed_threshold") |
| same driver + reference metric, 8.0, bracket 3 (p25 ~9.4)              | ("strong", "bracket_percentile") |
| same, 11.5, bracket 3                                                   | ("weak", "bracket_percentile") |
| same driver, none_reading="weak", None                                  | ("weak", "none")               |
| an empty_list driver, [] / ["land"]                                     | strong / weak                  |
| diagnose("interaction", ..., counterspells 0, counterspell_applicable False) | weak driver, NO counterspell lever |
"""

from __future__ import annotations

from dataclasses import dataclass

from mythgauntlet.ratings import reference



@dataclass(frozen=True)
class Driver:
    name: str
    fact: str
    direction: str
    strong_at: float | None
    weak_at: float | None
    ref_metric: str | None = None
    ref_scale: float = 1.0
    kind: str = "number"
    none_reading: str = "unknown"


@dataclass(frozen=True)
class Lever:
    axes: tuple[str, ...]
    driver: str
    text: str
    requires: str | None = None


def reading(driver: Driver, value, bracket: int | None) -> tuple[str, str]:
    if value is None:
        return driver.none_reading, "none"
    if driver.kind == "bool":
        return ("strong" if bool(value) else "typical", "fixed_threshold")
    if driver.kind == "empty_list":
        is_empty = isinstance(value, list) and len(value) == 0
        return ("strong" if is_empty else "weak", "fixed_threshold")
    # number
    if driver.kind == "number":
        if driver.ref_metric and bracket is not None:
            result = reference.percentile_band(bracket, driver.ref_metric, value * driver.ref_scale)
            if isinstance(result, dict):
                band = result.get("percentile_band")
                if driver.direction == "higher_is_better":
                    if band == "above_p75":
                        return "strong", "bracket_percentile"
                    if band == "below_p25":
                        return "weak", "bracket_percentile"
                    return "typical", "bracket_percentile"
                else:
                    if band == "below_p25":
                        return "strong", "bracket_percentile"
                    if band == "above_p75":
                        return "weak", "bracket_percentile"
                    return "typical", "bracket_percentile"
        # fixed thresholds
        if driver.direction == "higher_is_better":
            if driver.strong_at is not None and value >= driver.strong_at:
                return "strong", "fixed_threshold"
            if driver.weak_at is not None and value < driver.weak_at:
                return "weak", "fixed_threshold"
            return "typical", "fixed_threshold"
        else:
            if driver.strong_at is not None and value <= driver.strong_at:
                return "strong", "fixed_threshold"
            if driver.weak_at is not None and value >= driver.weak_at:
                return "weak", "fixed_threshold"
            return "typical", "fixed_threshold"
    return driver.none_reading, "none"


# drivers
avg_kill_turn = Driver(
    name="avg_kill_turn",
    fact="avg_kill_turn",
    direction="lower_is_better",
    strong_at=6.0,
    weak_at=9.0,
    ref_metric="avg_kill_turn",
    ref_scale=1.0,
    kind="number",
    none_reading="weak",
)

goldfish_kill_rate = Driver(
    name="goldfish_kill_rate",
    fact="goldfish_kill_rate",
    direction="higher_is_better",
    strong_at=0.9,
    weak_at=0.5,
    ref_metric="speed",
    ref_scale=100.0,
    kind="number",
)

avg_commander_turn = Driver(
    name="avg_commander_turn",
    fact="avg_commander_turn",
    direction="lower_is_better",
    strong_at=4.0,
    weak_at=6.0,
    ref_metric="avg_commander_turn",
    ref_scale=1.0,
    kind="number",
    none_reading="weak",
)

curve_efficiency = Driver(
    name="curve_efficiency",
    fact="curve_efficiency",
    direction="higher_is_better",
    strong_at=0.70,
    weak_at=0.55,
    kind="number",
)

average_mana_value = Driver(
    name="average_mana_value",
    fact="average_mana_value",
    direction="lower_is_better",
    strong_at=2.7,
    weak_at=3.4,
    kind="number",
)

ramp_cards = Driver(
    name="ramp_cards",
    fact="ramp_cards",
    direction="higher_is_better",
    strong_at=11,
    weak_at=6,
    kind="number",
)

creature_count = Driver(
    name="creature_count",
    fact="creature_count",
    direction="higher_is_better",
    strong_at=32,
    weak_at=19,
    kind="number",
)

speed_clock_drivers = (
    avg_kill_turn,
    goldfish_kill_rate,
    avg_commander_turn,
    curve_efficiency,
    average_mana_value,
    ramp_cards,
    creature_count,
)

keep_rate = Driver(
    name="keep_rate",
    fact="keep_rate",
    direction="higher_is_better",
    strong_at=0.81,
    weak_at=0.72,
    kind="number",
)

avg_mulligans = Driver(
    name="avg_mulligans",
    fact="avg_mulligans",
    direction="lower_is_better",
    strong_at=0.23,
    weak_at=0.355,
    kind="number",
)

commander_cast_rate = Driver(
    name="commander_cast_rate",
    fact="commander_cast_rate",
    direction="higher_is_better",
    strong_at=0.99,
    weak_at=0.9,
    kind="number",
)

manabase_consistency = Driver(
    name="manabase_consistency",
    fact="manabase_consistency",
    direction="higher_is_better",
    strong_at=0.88,
    weak_at=0.76,
    kind="number",
)

land_count = Driver(
    name="land_count",
    fact="land_count",
    direction="higher_is_better",
    strong_at=36,
    weak_at=33,
    kind="number",
)

resilience_score = Driver(
    name="resilience_score",
    fact="resilience_score",
    direction="higher_is_better",
    strong_at=65.0,
    weak_at=40.0,
    ref_metric="resilience",
    ref_scale=1.0,
    kind="number",
)

kill_delay_turns = Driver(
    name="kill_delay_turns",
    fact="kill_delay_turns",
    direction="lower_is_better",
    strong_at=0.64,
    weak_at=1.22,
    kind="number",
)

creature_share = Driver(
    name="creature_share",
    fact="creature_share",
    direction="lower_is_better",
    strong_at=0.30,
    weak_at=0.51,
    kind="number",
)

noncreature_engine_count = Driver(
    name="noncreature_engine_count",
    fact="noncreature_engine_count",
    direction="higher_is_better",
    strong_at=14,
    weak_at=8,
    kind="number",
)

spot_removal = Driver(
    name="spot_removal",
    fact="spot_removal",
    direction="higher_is_better",
    strong_at=5,
    weak_at=2,
    kind="number",
)

counterspells = Driver(
    name="counterspells",
    fact="counterspells",
    direction="higher_is_better",
    strong_at=3,
    weak_at=1,
    kind="number",
)

board_wipes = Driver(
    name="board_wipes",
    fact="board_wipes",
    direction="higher_is_better",
    strong_at=2,
    weak_at=1,
    kind="number",
)

breadth = Driver(
    name="breadth",
    fact="breadth",
    direction="higher_is_better",
    strong_at=3,
    weak_at=2,
    kind="number",
)

no_answer_for = Driver(
    name="no_answer_for",
    fact="no_answer_for",
    direction="higher_is_better",
    strong_at=None,
    weak_at=None,
    kind="empty_list",
)

fast_kill_turn = Driver(
    name="fast_kill_turn",
    fact="fast_kill_turn",
    direction="lower_is_better",
    strong_at=7.7,
    weak_at=8.7,
    kind="number",
    none_reading="weak",
)

nut_kill_rate = Driver(
    name="nut_kill_rate",
    fact="nut_kill_rate",
    direction="higher_is_better",
    strong_at=0.05,
    weak_at=0.0,
    kind="number",
)

has_game_ending_combo = Driver(
    name="has_game_ending_combo",
    fact="has_game_ending_combo",
    direction="higher_is_better",
    strong_at=None,
    weak_at=None,
    kind="bool",
)

go_off_turn = Driver(
    name="go_off_turn",
    fact="go_off_turn",
    direction="lower_is_better",
    strong_at=None,
    weak_at=None,
    kind="bool",
)

overrun_alpha = Driver(
    name="overrun_alpha",
    fact="overrun_alpha",
    direction="higher_is_better",
    strong_at=None,
    weak_at=None,
    kind="bool",
)

DRIVER_TABLE: dict[str, tuple[Driver, ...]] = {
    "speed": speed_clock_drivers,
    "clock": speed_clock_drivers,
    "consistency": (
        keep_rate,
        avg_mulligans,
        curve_efficiency,
        commander_cast_rate,
        manabase_consistency,
        land_count,
    ),
    "resilience": (
        resilience_score,
        kill_delay_turns,
        creature_share,
        noncreature_engine_count,
    ),
    "interaction": (
        spot_removal,
        counterspells,
        board_wipes,
        breadth,
        no_answer_for,
    ),
    "ceiling": (
        fast_kill_turn,
        nut_kill_rate,
        has_game_ending_combo,
        go_off_turn,
        overrun_alpha,
    ),
}

LEVERS: tuple[Lever, ...] = (
    Lever(axes=("speed", "clock"), driver="avg_commander_turn", text="Cheaper ramp in the one- and two-mana slots gets the commander out sooner."),
    Lever(axes=("speed", "clock"), driver="ramp_cards", text="More mana ramp lets the deck cast its expensive cards earlier."),
    Lever(axes=("speed", "clock"), driver="average_mana_value", text="Swapping a few expensive cards for cheaper ones lowers the curve and speeds up the clock."),
    Lever(axes=("speed", "clock"), driver="curve_efficiency", text="Mana goes unspent in the early turns; more plays at one, two and three mana use it."),
    Lever(axes=("speed", "clock"), driver="creature_count", text="Few creatures means little early pressure; more cheap creatures put the clock on sooner."),
    Lever(axes=("speed",), driver="goldfish_kill_rate", text="Many games never kill within the horizon; a lower curve or more ways to deal damage raise the share that do."),
    Lever(axes=("clock",), driver="avg_kill_turn", text="The kill comes late on average; the commander, ramp and curve drivers above show what delays it."),
    Lever(axes=("consistency",), driver="keep_rate", text="Opening hands are often mulliganed; check the land count and the colour sources."),
    Lever(axes=("consistency",), driver="avg_mulligans", text="The deck mulligans more than most; a steadier land count and cheaper early plays make opening hands keepable."),
    Lever(axes=("consistency",), driver="manabase_consistency", text="Colour sources are short for some colours; more dual or fixing lands for the short colour help."),
    Lever(axes=("consistency",), driver="land_count", text="The land count is on the low side; an extra land or mana rock smooths draws."),
    Lever(axes=("consistency",), driver="commander_cast_rate", text="The commander is not cast in some games; ramp or cheaper support helps it arrive."),
    Lever(axes=("consistency",), driver="curve_efficiency", text="Early mana goes unused; lower-cost plays use it."),
    Lever(axes=("resilience",), driver="resilience_score", text="A board wipe sets the deck back a lot; holding some threats in hand and keeping non-creature value engines blunts it."),
    Lever(axes=("resilience",), driver="kill_delay_turns", text="After a wipe the deck needs many extra turns to kill; cheap rebuild creatures or haste threats shorten that."),
    Lever(axes=("resilience",), driver="creature_share", text="The deck leans heavily on creatures; non-creature threats and engines survive a wipe."),
    Lever(axes=("resilience",), driver="noncreature_engine_count", text="Few non-creature ramp or draw pieces; artifacts and enchantments that keep producing value survive a wipe."),
    Lever(axes=("interaction",), driver="spot_removal", text="Few spot-removal spells; more cheap targeted removal answers a single threat."),
    Lever(axes=("interaction",), driver="counterspells", requires="counterspell_applicable", text="Few counterspells; they answer threats that removal cannot reach."),
    Lever(axes=("interaction",), driver="board_wipes", requires="wipe_applicable", text="No sweeper for a runaway board; one wipe is a safety valve."),
    Lever(axes=("interaction",), driver="breadth", text="Interaction covers only some of the answer types this deck's colours can play; widening the mix covers more situations."),
    Lever(axes=("interaction",), driver="no_answer_for", text="Some permanent types have no answer in the deck at all; the removal coverage tool lists which."),
    Lever(axes=("ceiling",), driver="fast_kill_turn", text="The best games still kill late; haste, extra combats or burst damage raise the ceiling."),
    Lever(axes=("ceiling",), driver="nut_kill_rate", text="Few games reach a fast kill; ramping into the strongest threats raises the ceiling."),
)


def diagnose(axis: str, score: float, why: str, facts: dict, bracket: int | None) -> dict:
    if axis not in DRIVER_TABLE:
        raise ValueError(f"unknown axis {axis!r}")
    drivers_out = []
    driver_readings = {}
    for d in DRIVER_TABLE[axis]:
        val = facts.get(d.fact)
        r, basis = reading(d, val, bracket)
        drivers_out.append({
            "name": d.name,
            "value": val,
            "direction": d.direction,
            "reading": r,
            "basis": basis,
        })
        driver_readings[d.name] = r
    levers_out = []
    seen = set()
    for lev in LEVERS:
        if axis not in lev.axes:
            continue
        if lev.driver not in driver_readings:
            continue
        if driver_readings[lev.driver] != "weak":
            continue
        if lev.requires is not None and not facts.get(lev.requires):
            continue
        if lev.text in seen:
            continue
        levers_out.append(lev.text)
        seen.add(lev.text)
    return {
        "axis": axis,
        "score": score,
        "why": why,
        "drivers": drivers_out,
        "levers": levers_out,
    }
