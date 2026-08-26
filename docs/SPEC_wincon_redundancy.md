# SPEC — `src/mythgauntlet/sim/wincon_redundancy.py`

PLAN_CLOCK.md Phase 2: "how many pieces of interaction must the table spend to stop the
win?" A deck that folds to a single counterspell is not the deck that needs three.

## Why this exists, and why it is a NEW module rather than an extension of `tier1.py`

`sim/tier1.compute_resilience` already answers a version of this question — one board
wipe at one fixed turn — but a wipe only ever models ONE disruption class (destroy all
creatures), and it is blind to anything that doesn't attack: a storm engine's spells and
mana are untouched by a wipe (verified live, PLAN_CLOCK Phase 2's own resilience fix,
2026-08-25 — `kill_delay_turns: 0.0` on a synthetic storm deck).

What the player actually asks is closer to *targeted* interaction: "how many counterspells/
removal spells does it take to fully take this plan apart?" That is a question about
**which specific cards the deck's fast kill depends on**, not about wiping the board — a
structurally different measurement, so it gets its own module rather than a new mode on
`compute_resilience`.

## Scope boundary — read this before extending it

**This measures ONLY the four non-combat kill mechanisms `sim/clock.apply_nut_kills`
already reads: the storm granter, magecraft/cast-damage burn payoffs, the overrun finisher,
and a scaling-burn (Fireball-class) finisher.** A deck with none of these — the majority of
the corpus, per PLAN_CLOCK §1b's own measurement ("only a minority of the zero-Game-Changer
B2/B3 population runs a storm or overrun engine at all") — has no single removable "piece"
this method can name. Its win is diffuse (the whole board), and `compute_resilience`'s
wipe-based measure already covers that case. `WinconRedundancyReport.applicable = False`
says so plainly rather than inventing a number for a deck this method cannot see.

**This is an INFORMATIONAL axis, like `resilience_score`, not a bracket-placement input.**
It does not need to clear `axis_separation.py`'s Cohen's-d gate before shipping, because it
is not proposed to influence `estimate_bracket` — Phase 1's acceptance gate exists to keep
an unproven signal out of a VERDICT, and this doesn't touch one. It is surfaced to the
player the same way Resilience already is.

## The four roles, and how each one actually breaks

Each role is identified from `EffectVector` fields already used by `sim/storm.py` /
`sim/overrun.py` — this module adds no new card-reading logic, only asks "which SPECIFIC
cards" instead of "what's the deck-level total."

| role | `EffectVector` field(s) | how the mechanism combines cards | what "removing one" does |
|---|---|---|---|
| `storm_granter` | `grants_storm` | **OR** across the deck (`_engine`'s `grants_storm = grants_storm or fx.grants_storm`) | Removing fewer than ALL granters is a **complete no-op** — one remaining "spells you cast have storm" card keeps the plan at full power. A deck running two granters needs both found and answered; that is real, occasionally-missed redundancy. |
| `burn_payoff` | `magecraft_damage`, `cast_damage` | **SUM, then capped** (`_DMG_ENGINE_CAP = 4`) | Removing a payoff only matters once the remaining sum drops below the cap — a 3rd Guttersnipe-class card can be pure overkill the deck never needed, and removing it changes nothing. |
| `overrun_finisher` | `overrun_pump`, `overrun_scales` | **MAX** (`_best_finisher` takes the single strongest flat pump; `scales` is an OR) | Removing the single best pump exposes the next-best one underneath, which may still be lethal on the same board — a deck running Overrun AND Craterhoof needs both removed, not one. |
| `scaling_burn_finisher` | `scaling_burn` | `_run_chain` casts the **cheapest** affordable one as the finisher | Removing the cheapest exposes the next-cheapest, which needs strictly more mana to close — a real (if partial) form of redundancy: the deck's clock gets SLOWER, not necessarily dead. |

**The combination rule is not uniform, and treating it as if it were (e.g. "remove the
biggest card in each role, report 1") would misreport three of the four roles.** This is
the central design fact this module exists to get right — a naive per-card importance
ranking cannot substitute for actually re-running the estimator after each removal, because
whether removing card N matters depends on the OTHER cards still present (the OR/cap/max
combination rules above), not on card N in isolation.

## Method — ablate against the ALREADY-COMPUTED nut-draw ceiling, not a fresh simulation

`ratings.analysis.analyze_deck` already computes, once per deck, exactly the two inputs
this needs:

- `mana_by_turn = _mean_mana_curve(runs, cfg.turns)` — feeds `estimate_go_off`
  (storm/burn) and is reused here **unmodified** across every removal step.
- `nut_power, nut_creatures = _nut_board(runs)` — feeds `estimate_overrun` and is likewise
  reused unmodified.

Both `estimate_go_off` and `estimate_overrun` are **pure, deterministic, no-RNG functions of
a card list plus these fixed inputs** (docs/SIMULATION.md's own contract). That means
ablation never needs a fresh `tier0.simulate()` run: call the same estimator again on a
card list with N role-members removed and read whether it still reaches lethal. Cheap (no
RNG, no re-simulation) and exactly consistent with the Ceiling axis's own go_off/overrun
numbers, which are computed from these same two inputs.

**Why holding the mana curve and nut board FIXED across removals is valid for these four
roles specifically, and would NOT be valid in general:** none of `grants_storm`,
`magecraft_damage`, `cast_damage`, `overrun_pump`, `overrun_scales`, or `scaling_burn` cards
produce mana or board development themselves — a Guttersnipe deals damage, it doesn't ramp;
Craterhoof pumps a board that was already built. Removing one from the card list does not
change what a real game's land drops or creature count would have looked like, so reusing
the cached mana curve / nut board is a correct, not merely convenient, simplification.

**This does NOT generalize to a `ritual_mana` role (Dark Ritual class) — deliberately out
of scope.** A ritual DOES produce mana (`ritual_mana` feeds `_run_chain`'s own mana pool
directly), so ablating a ritual card while holding `mana_by_turn` fixed would be wrong: the
cached curve was computed assuming that mana existed. Modeling ritual redundancy correctly
needs a fresh `tier0.simulate()` per candidate removal (the curve itself must change), which
is real, separate future work — not attempted here, and not silently approximated wrong.

## Removal order within a role

Candidates within a role are tried **most-damaging-first** (a caller with real interaction
would sensibly target the biggest piece), computed from each candidate's OWN individual
contribution:

- `storm_granter`: order is irrelevant (OR-combination — the *count* to disable is always
  every granter present, never fewer, regardless of order tried).
- `burn_payoff`: sorted by `magecraft_damage + cast_damage` descending.
- `overrun_finisher`: sorted by `(overrun_scales, overrun_pump)` descending — a scaling pump
  outranks a flat one, since it is the more dangerous piece on a wide board.
- `scaling_burn_finisher`: sorted by mana value ASCENDING (the engine always reaches for the
  cheapest first, so the cheapest is the piece actually doing the work today).

The loop tries removing the first 1, then 2, then 3, ... candidates (cumulative), re-running
the relevant estimator each time, and reports the smallest `k` where the mechanism stops
reaching lethal. `pieces_to_disable = None` means removing every identified candidate for
THIS role still didn't stop the kill — most commonly because a DIFFERENT role is
independently sufficient on its own (verified live: a granter + 14 cantrips + a scaling
Fireball-class finisher and NO magecraft/cast-damage payoff at all still goes off on the
scaling burn alone, `earliest_turn=10`, `peak_damage=52` — so a deck's `burn_payoff` role
can legitimately report `None` while its `scaling_burn_finisher` role reports a real count).
It can also mean this module's candidate identification missed a contributing card; the
report cannot cheaply distinguish the two, so it says "not disabled by this role alone"
rather than fabricating a number. Either way, a caller should read `None` as "removing this
role's cards is not sufficient by itself — check whether other reported roles must ALSO be
answered," not as a defect to be silently rounded away.

## A role is reported only if it is ALREADY part of this deck's demonstrated kill

`RoleRedundancy` is only added to the report when the FULL, unablated card list already
reaches lethal via that mechanism (`estimate_go_off(...).goes_off` /
`estimate_overrun(...).can_alpha_strike`). A deck that happens to run one off-theme
Guttersnipe that never actually closes a game is not reported as having "burn payoff
redundancy" — that would be measuring a card that exists, not a plan the deck executes.

## Pitfall — a commander cannot be truly "removed" by interaction

If the sole or best card in a role IS one of the deck's commanders, targeted removal in a
real game sends it to the command zone, not away — it can be recast (at an increasing tax).
Reporting "1 piece of interaction stops this" when that piece is the commander overstates
how final an answer actually is. `analyze_wincon_redundancy` is told `commander_names` and
sets `RoleRedundancy.involves_commander = True` whenever any contributing card is a
commander name, so a consumer can caveat this rather than present it as equivalent to
answering a library card. **Not modeled further than the flag** — simulating command-zone
recursion and its mana tax is a real, separate piece of complexity, not attempted here.

## Pitfall — a role's "removal" set overlapping another role's cards

A single card can carry more than one relevant `EffectVector` field (a creature that both
`grants_storm` and has `cast_damage`, for instance — rare but not disallowed by the model).
Ablating it for the `storm_granter` role's purposes also silently changes the `burn_payoff`
role's arithmetic, and vice versa. This is handled correctly BY CONSTRUCTION, not by special
casing: each role's loop re-runs the *real* `estimate_go_off`/`estimate_overrun` function on
the actually-reduced card list every step, so a cross-role side effect is naturally captured
by the estimator itself rather than needing to be reasoned about by this module's candidate
bookkeeping. The one thing this means for a caller: **the roles are not independent
recommendations that sum** — "remove 1 granter and 2 payoffs" are not four DIFFERENT cards
if any of them coincide; report the roles distinctly (matching how a player would ask "what
stops the storm plan" and "what stops the burn plan" as separate questions) rather than
merging into one flattened card list.

## Pitfall — a symmetric role has no real "most important" card, only order-of-discovery

For `storm_granter` specifically, ranking within the role is a non-question (removal order
literally cannot change the answer, per the OR-combination table above) — do not add a
sort key there hoping for a more informative report; there is no card-level signal that
would be meaningful, because the mechanism itself does not distinguish between granters.

## Pitfall — do not read this as "how many turns does the wipe or interaction buy"

Unlike `compute_resilience`'s `kill_delay_turns`, this module reports a **count of cards**,
not a **turn delay**. A deck whose burn-payoff role needs 3 pieces removed before it stops
closing on turn 6 might still close on turn 9 via ordinary combat after those 3 removals —
"3 pieces of interaction" answers "how many targeted answers does the FAST plan need," not
"how many turns does the table buy." Reporting a turn delta here would need re-running
`estimate_go_off` at every intermediate removal count AND translating "goes_off flips to
False" into "the deck's real clock is now the fallback combat clock," which requires
knowing what that fallback actually is — a real extension, not attempted in this pass
(`RoleRedundancy` has no turn-delay field; do not add one without doing this properly).

## Public API

```python
@dataclass(frozen=True)
class RoleRedundancy:
    role: str                          # "storm_granter" | "burn_payoff" | "overrun_finisher"
                                        # | "scaling_burn_finisher"
    contributing_cards: tuple[str, ...]  # names, in the ORDER this module tried removing them
    pieces_to_disable: int | None       # smallest k that stops the mechanism; None = removing
                                         # every identified candidate still didn't (see above)
    involves_commander: bool            # True if a commander name is among contributing_cards

@dataclass(frozen=True)
class WinconRedundancyReport:
    applicable: bool                    # False: no non-combat engine reaches lethal at all
    roles: tuple[RoleRedundancy, ...]   # only roles that are ALREADY part of a demonstrated kill

def analyze_wincon_redundancy(
    all_cards: list[tuple[Card, int]],
    mana_by_turn: list[int],
    nut_power: int,
    nut_creatures: int,
    turns: int,
    commander_names: frozenset[str] = frozenset(),
) -> WinconRedundancyReport
```

## Gold set (measured, not guessed — `tests/engine/test_wincon_redundancy.py` pins these exactly)

Every row below is the module's REAL, verified output on the stated synthetic deck (14
cantrips + the named pieces, test_storm.py/test_overrun.py's own proven fixture shapes).
The point of listing verified numbers rather than a hand-derived table is the same reason
`SPEC_redundancy.md` does it: several of these are non-obvious even having read the
combination-rule table above, and two were caught wrong on the first attempt at writing
this very spec (see the `burn_payoff: None` cases below).

| deck | role | `pieces_to_disable` | why |
|---|---|---|---|
| granter A + granter B + 1 cast-damage payoff + Big Burn | `storm_granter` | **2** | OR-combination — a lone remaining granter keeps the plan at full power |
| granter (×1) + 1 cast-damage payoff + cantrips, no finisher | *(no roles reported)* | — | `peak_damage=24 < 40` — never reaches lethal at all, so nothing here is a "demonstrated kill" |
| granter (×1) + cantrips + Big Burn, no cast/magecraft payoff at all | `storm_granter` | **1** | the storm-COPY multiplier is what makes Big Burn's own X-damage lethal (`peak_damage=52` with the granter, `peak_damage=8` without) — here the granter genuinely IS the whole plan |
| granter A + granter B + 1 cast-damage payoff + Big Burn | `burn_payoff` | **None** | cast_damage is NOT copied by storm (unlike magecraft) — the granters + Big Burn alone already clear lethal with the payoff removed, so this role isn't what's gating the kill |
| granter + 2 cast-damage payoffs (dmg 3 and 2) + cantrips, no finisher | `burn_payoff` | **1** (removes the dmg-3 card first) | with no scaling finisher to fall back on, the payoffs ARE what's gating it, and removing the bigger one first is enough |
| Craterhoof (scales) + Team Charge (+3/+3 flat), board 10 power / 10 creatures | `overrun_finisher` | **2**, order `(Craterhoof, Team Charge)` | Team Charge ALONE reaches exactly `10 + 10*3 = 40` — still lethal after Craterhoof is removed, so both are needed |
| Craterhoof alone, board 5 power / 2 creatures | *(role not reported)* | — | 2 creatures is under `_MIN_WIDTH` (3) — never a real alpha strike regardless of the finisher |

## Consumer

`ratings.analysis.analyze_deck` gains an optional `wincon_redundancy` field (parallel to
`resilience`, gated the same way — computed only when requested, since it costs a handful
of extra deterministic calls, not a new simulation pass). Surfaced by the CLI/API the same
way Resilience already is. **Not consumed by `estimate_bracket` or `compute_ceiling`** —
informational only (see Scope boundary above).
