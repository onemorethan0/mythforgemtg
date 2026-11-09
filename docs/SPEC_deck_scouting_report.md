# SPEC: the deck scouting report (B30-B38)

**Ask (owner, 2026-11-07):** when a deck is rated, give a description that says what it is good
at, what it will be weak against, the specific strong and weak cards, its combos, the average
speed at which it kills one player and the whole table, and the methods it relies on to do so.

**Bar:** every sentence in the report is backed by a number the engine measured on THIS deck and
shows it. No measured fact, no sentence ("prefer an honest under-count to a confident
fabrication"). Judgements are relative to decks of the same bracket, because a casual pod asks
"is this good *for a Bracket 2 table*", not "is this good in the abstract".

Folded into [`DEVELOPMENT_PLAN.md`](DEVELOPMENT_PLAN.md) as Phase 2b.

---

## 1. What exists today (verified against the live engine, 2026-11-07)

Measured by calling `POST :8020/analyze` (runs=150, combos on) and `POST :8020/breakdown` on a
saved Krenko, Mob Boss deck. Field names below are the real response keys.

| Report element | Already measured | Where |
|---|---|---|
| Good at | `insight.strengths` (4 lines), `insight.why` per axis, power axes 0-100 | `ratings/insight.py` `_verdict` |
| Weak against | `insight.weaknesses`; wipe resilience (`resilience.wiped_kill_rate`, `kill_delay_turns`); removal gaps (`breakdown.removal.no_answer_for`); role shortfalls (`breakdown.roles.under_target`) | insight, breakdown |
| Strong cards | `insight.key_cards` (by role, popularity-ranked) | insight |
| Weak cards | advisor cut ranking (`redundancy.rank_redundant`), `/card-impact` for one named card | advisor, card_impact |
| Combos | `combos.items[]`: cards, produces, pieces, terminal, needs_commander, reliability, deterministic, note; plus `almost_included` | spellbook + grading |
| Kill speed, 1 player | `report.avg_kill_turn` 9.5, `report.goldfish_kill_rate` 0.99 (40 life, no opposition) | tier0 goldfish |
| Kill speed, table | `pod_close_turn` 13.0, `pod_close_rate` 0.61 (3 opponents, table-lethal capacity) | pod axis |
| Kill method | `go_off` / `go_off_turn` (storm), `overrun_alpha`, `pod_via_finisher`, `wincon_redundancy.roles`; T2 game end reason `life` / `commander_damage` / `combo` / `decked` | tier0, sim/storm, sim/overrun, sim/game.py `_finish` |
| Head-to-head | `/duel` (T2, two-player), `/pod` (four-seat win rate) | tier2, ratings/pod |

The Krenko deck's live insight read: *"Consistent engine (95/100)", "Deep interaction (13 answers)",
"High ceiling -- a real fast/combo finish", "Strong multiplayer closing power (63/100)"*, weaknesses
empty, kill ~T9.

## 2. Gaps, one per element of the ask

**G1. "Good at" is judged against fixed bars, not against peers.** `_verdict` uses absolute
thresholds (consistency >= `CONSISTENT_MIN`, interaction >= 55...). Consistency and Resilience are
known to be compressed (memory: every bracket's p25 is ~76-85), so "Consistent engine" fires for
nearly every deck and says nothing. A per-bracket percentile table already exists
(`ratings/reference.py`, `percentile_band`, 619 labelled decks) and is not used here.

**G2. "Weak against" has no matchup evidence and no hate model.** Weaknesses today are
self-measurements (thin interaction, folds to wipes). Nothing says what kind of OPPONENT or what
kind of ANSWER beats this deck. Two missing measurements:
- *Exposure*: what the deck depends on (graveyard, artifacts, enchantments, the commander, a
  single combo, flying/evasion, a creature board) crossed with how many answers to that
  dependency a typical table runs and whether the deck can protect it.
- *Matchups*: win rate against a fixed field of reference archetypes at the deck's bracket.

**G3. No per-card evidence.** `key_cards` is a role list ordered by global popularity; nothing
measures how a card performs in THIS deck. The goldfish runs already draw and cast every card
hundreds of times and throw that information away. The Krenko deck holds 0.57 dead cards per
game on average (`report.avg_dead_cards`) and the report cannot say which.

**G4. Combos are not on the clock.** Combos are found and graded, but the kill turn comes from a
goldfish that does not execute them: the Krenko deck holds Krenko + Skirk Prospector + Goblin
Warchief (infinite hasty tokens) and still reads "kill ~T9". There is no "how soon can it
assemble this" figure.

**G5. Kill speed is a mean against nobody.** `avg_kill_turn` is a mean over goldfish games
against 40 life and no interaction; no spread (p25/median/p75), no contested figure, and the
table figure is a capacity ("could have killed everyone") not a measured pod result.

**G6. Kill method is not attributed.** tier0 does not record HOW damage was dealt (combat, drain,
burn, commander damage, alternate win, combo), and T2's end reason folds every damage type into
`life`. So "the methods it relies on" can only be guessed from flags.

**G7. No report.** The pieces are spread over three panels (Measure, Breakdown, Mentor) and none
of them writes the scouting-report paragraph the ask describes.

---

## 3. Work items

IDs continue DEVELOPMENT_PLAN.md. Owner C (all are engine- or rules-facing) except where noted.
Every item ships behind the same bar: tests that pin the measurement, a before/after over the
labelled corpus where a judgement changes, and the existing guards (bracket accuracy within-one,
mentor bench, builder bench) unchanged.

### B30. Per-card telemetry from the goldfish (G3, also feeds G5/G6)
**What:** while tier0 runs its N games, record per card name: games drawn, turn first drawn, cast
(yes/turn), stranded (drawn and never cast), and the game's kill turn. Derive, in the style of
17lands' "games in hand" figures:
- `cast_rate` = cast / drawn; `avg_cast_turn`
- `stranded_rate` = drawn-and-never-cast / drawn (the "dead card" the report names)
- `kill_turn_when_seen_early` vs `kill_turn_when_not_seen` (seen early = in the opening hand or
  first 3 draws), and their difference `early_uplift` with a bootstrap 90% interval

**Shape:** `report.card_stats: [{name, drawn, cast_rate, avg_cast_turn, stranded_rate,
early_uplift, uplift_ci: [lo, hi], n_early, n_late}]`, sorted by `early_uplift`.

**Accept:** zero extra simulation (same games); runtime increase < 10% at runs=300; a seeded test
with a planted "always stranded" card and a planted "wins the game when drawn" card ranks them
last and first; measure the per-card noise (same deck, 8 seeds) and set the minimum sample /
interval width below which a card is not named. **Cards are only named when their interval
excludes zero.**

### B31. Strong and weak cards (G3), built on B30
**Strong:** cards with a significant positive `early_uplift`, plus combo pieces (B33) and
commander-synergy cards the lens already proves (`commander_lens`). Each named with its number:
"Skullclamp: when seen by turn 3 the deck kills 1.4 turns sooner (n=212)".
**Weak:** high `stranded_rate` (with the reason: colour, cost, or no target, which the sim
knows), significant negative uplift, and the advisor's redundancy surplus where `oversupply > 0`
(the existing `redundancy_backed` rule: never call a card redundant without it).
**Optional confirm:** `/card-impact` ablation on the top 3 / bottom 3 only (expensive; on demand).
**Accept:** on the 6-commander bracket roster, a hand review of every named card (owner-visible
table in the spec's results section); no card named on a sample below B30's floor.

### B32. Kill speed as a distribution, one opponent and the table (G5)
- From tier0: `kill_turn_p25 / median / p75` and the share of games that kill by turn 6, 8, 10.
- Table: replace "capacity" as the headline with the measured four-seat result from `/pod`
  (`ratings/pod.py`, already exists): median turn the deck wins a pod it wins, and its pod win rate
  against the reference field (B35). Keep capacity as the secondary "if unopposed" figure.
- Wording rule: always say against what ("unopposed", "against a Bracket 3 field").
**Accept:** percentiles reproduce `avg_kill_turn` to within rounding on the mean; pod figures
carry their game count; a test pins that a deck with no kill in N games reports "no kill in N
games", never a turn.

### B33. Combos on the clock (G4)
For each graded combo the deck holds: probability of having every piece available by turn T
(T = 3..10), from the deck's own cards-seen-by-turn (tier0 already tracks draws) with tutors
that can fetch a piece counted as extra outs (the tutor's own search text says what it finds:
gate the object, as everywhere else), plus the mana to execute (the combo's `mana_value` against
`avg_mana_available_by_turn`). Report the turn at which assembly reaches 25% / 50%.
Then the **combined clock** = per game, the earlier of the goldfish kill and a sampled combo
assembly, so "kills ~T9 by combat, or ~T7 in 30% of games via Krenko + Skirk Prospector +
Goblin Warchief".
**Accept:** the assembly probability is validated against a direct Monte-Carlo draw over the
same deck (no executor needed: draws only) within 2 points; commander-dependent combos treat the
commander as always available from the command zone after its cast turn; a non-deterministic
combo is labelled as such, never counted as a guaranteed kill.

### B34. Kill-method attribution (G6)
- tier0: tag every point of opponent life loss with its source class: `combat` (and whether by the
  commander), `noncombat_damage` (burn, drain triggers), `life_loss` (Gray Merchant style),
  `alt_win`, `combo`. Per game, the method that delivered the last 50% of damage is the kill
  method; aggregate to shares and to the top 5 damage-dealing cards.
- T2: split the `life` end reason the same way (the damage step already knows whether it is
  combat), so duel/pod results say how games were won too.
**Shape:** `report.kill_methods: {combat: 0.62, commander_damage: 0.05, noncombat: 0.25,
combo: 0.08, alt_win: 0}` and `report.top_damage_cards: [{name, share}]`.
**Accept:** shares sum to 1 over killing games; a Voltron fixture reads mostly
`commander_damage`; a Gray Merchant / drain fixture reads `noncombat`; a test pins that a
Thassa's-Oracle-style alt-win is `alt_win`, not `combo`.

### B35. Reference field and matchups (G2, the "weak against" half that needs games)
**Field:** per bracket 1-4, 6-8 reference decks drawn from `corpus/decks` (labelled), one per
archetype that a casual pod actually meets: go-wide tokens, Voltron/commander damage, big
creature midrange, spellslinger, graveyard/reanimator, artifact/combo, control/stax-light.
Archetype by `deck_themes.detect_deck_themes`; pick the deck closest to its archetype's median
strength at that bracket. Committed as data (`src/mythgauntlet/data/reference_field.json`) so results are
comparable over time.
**Run:** `/duel` (two-player, fast) against each, 120 games, seats alternated; `/pod` against a
sampled three of them for the table figure (B32).
**Output:** win rate per archetype with interval; "weak against" = archetypes below 40% whose
interval excludes 50%, "favoured against" = above 60% likewise; plus WHY from B34 (how it lost:
"loses to go-wide by combat around T8 before its wipes come online").
**Cost:** ~5-10 s per deck (measured duel cost ~0.4 s / 60 games); an explicit "Scout matchups"
button, cached per decklist hash like advice.
**Accept:** the field is stable across seeds (each archetype's own win rate vs the field within
noise); the matchup verdicts on the 6-commander roster are reviewed by hand; T2's documented
fidelity limit ("directional, battlecruiser fidelity") is printed beside every matchup number.

### B36. Exposure to hate (G2, the static half)
Deterministic, no sims. For each dependency, measure reliance and the deck's own protection:

| Dependency | Reliance measured as | Protection measured as | Example sentence |
|---|---|---|---|
| Graveyard | recursion/reanimation share of key cards + B30 uplift of GY cards | none needed; report | "leans on the graveyard (9 cards): weak to Rest in Peace-style hate" |
| Commander | combos `needs_commander`, lens synergy, goldfish with the commander removed twice (new tier0 option) | protection role count | "loses 2.1 turns of speed if Krenko is killed twice" |
| Board wipes | `resilience` (exists) | indestructible/phase/recursion | exists, re-worded relative to peers |
| Artifacts / enchantments | share of mana and key cards that are artifacts/enchantments | | "11 of 15 ramp pieces are artifacts: weak to Vandalblast" |
| Flyers | count of own flying/reach blockers vs the field's evasive share | | "no flying blockers" |
| Single combo | wincon redundancy (`wincon_redundancy.pieces_to_disable`) | counters/protection | "one Krenko answer stops both combos" |
| Mana base | nonbasic count, colour consistency (`breakdown.manabase`) | basics | "38 nonbasics: weak to Blood Moon effects" |
| Speed | median kill turn vs the bracket's p25 | | "slower than 75% of Bracket 3 decks: weak to fast tables" |

**Accept:** each row has a test fixture; thresholds are percentiles over the labelled corpus, not
constants; a sentence is emitted only past its threshold; the commander-removal goldfish option
is pinned by a test that a commander-less deck shows no change.

### B37. Peer-relative strengths and weaknesses (G1)
Re-key `_verdict` on `reference.percentile_band(bracket, axis, value)`: "better than 80% of
Bracket 3 decks at closing a table" instead of "63/100". Keep the absolute score beside it.
**Accept:** across the labelled corpus, each strength line fires for 15-35% of decks in a bracket
(today some fire for most); mentor bench unchanged or better (the mentor quotes these lines).

### B38. The scouting report (G7)
**Engine:** `POST :8020/scout` = analyze + breakdown + B30-B36, assembled into a `ScoutReport`:

```
{gameplan, bracket, strengths[{text, evidence}], weak_against[{text, evidence, source:
"matchup"|"exposure"}], strong_cards[{name, why, evidence}], weak_cards[...],
combos[{cards, produces, assembly_turn_50, needs_commander, deterministic}],
clock{one_opponent{p25, median, p75, kill_rate, n}, table{median, win_rate, n, field},
combined{...}}, kill_methods{...}, top_damage_cards[...], caveats[...]}
```

**Prose:** a deterministic template renders every field (always available, offline). An optional
LLM paragraph (qwen3:14b) may summarise, gated exactly like `swap_narrative`: every card it names
must be in the deck, every number must appear in the report, no adjective without a measured
basis; a failed gate falls back to the template, never to unchecked text.
**Forge:** `POST /api/deck/{id}/scout` (proxy, cached on decklist hash + engine fingerprint,
persisted like `last_measure`), and a `ScoutingReport` panel replacing nothing: it links to
Measure, Breakdown and Mentor for the detail.
**Accept:** on the 6-commander roster every sentence traces to a field (a test walks the
rendered text and fails on an unbacked number or card name); the mentor can cite the report;
runtime under 30 s without matchups, matchups on demand.

---

## 4. Order, cost, and what to measure first

1. **B30** first: it is free data from games already played, and B31, B33, B34 and B36 all read it.
2. **B34** next (same tier0 pass), then **B32** and **B33** (the clock the ask names explicitly).
3. **B37** (cheap, fixes today's least informative lines), **B36** (no sims).
4. **B35** (needs a curated field; most effort; on demand).
5. **B38** last, assembling the rest.

Rough effort: B30 1-2 days, B34 1 day, B32 0.5, B33 1-2, B37 0.5, B36 2, B35 2-3, B38 2.

**Measure first (before B30 ships):** the per-card noise floor. If at runs=300 the bootstrap
interval for a typical card is wider than ~1 turn, B31 must either raise runs for the scout call
or name only the extreme few. That number decides how many cards the report can honestly name.

## 5. Risks

- **Goldfish blind spots** (no opposing interaction) make per-card uplift favour proactive cards
  and undervalue removal. Mitigation: removal is judged by B36/B35 (what it answers, matchups),
  never by goldfish uplift; the report says which instrument backs each line.
- **T2 fidelity** for matchups is directional. Every matchup line prints its game count and the
  fidelity note; matchup lines never move the bracket.
- **Spellbook dependence** for combos: offline it degrades to "combos not checked", and the
  report says so instead of implying there are none.
- **Text that outruns the numbers** is the failure this project has hit most often (mentor gate
  history). The template-first, gated-LLM-second rule in B38 is the defence; do not ship prose
  that skips it.

---

## 6. Results

### B30 (2026-11-07): per-card telemetry shipped, noise floor measured

`RunStats.seen_turn` / `played_turn` (tier0, recorded only), `ratings/card_stats.py`, and
`POST /analyze {"card_stats": true}` -> `card_stats: {runs, early_turn, min_group, note, cards[]}`.
Opt-in: it runs its own 2,000-game pass (~3 s), so the advisor's many internal analyses are not
charged for it.

**Cost of the telemetry itself:** none measurable. 1,500 games, best of 3: 2.09 s before, 2.08 s
after, with an identical kill-turn sum and spell count (byte-identical play, as designed).

**Noise floor** (`scratchpad/noise.py`: same deck, 8 seeds; Krenko and Tymna decks):

| games | cards with an uplift figure | median 90% half-width | calibration (seed sd vs reported se) |
|---|---|---|---|
| 300 | 4 / 72 | 0.33 turns | 0.21 vs 0.20 |
| 2,000 | all (>= 30 early and late) | 0.14-0.16 turns | intervals stable; top/bottom cards significant in 8/8 seeds |

At 300 games (Forge's measure default) a card is "seen by turn 3" in only ~30 games, the sample
floor, so nothing can be named; hence the dedicated pass. The reported interval is honest: the
standard error matches the seed-to-seed spread.

**What the figure says, and a rule it forces on B31.** Top of the Krenko list: Skirk Prospector
+0.86 turns (the combo's sac outlet), Sol Ring +0.83, Roaming Throne +0.51. Bottom: Blasphemous
Act, Chaos Warp, Jeska's Will, The One Ring, Mithril Coat at about -0.45; Tymna's bottom is
Austere Command, Return of the Wildspeaker, Doubling Season. A goldfish has no opponent, so
removal, wipes and slow value engines can only cost it tempo there. **B31 rule: a card in an
interaction role (removal, counter, wipe, protection) is never called weak on goldfish uplift;
it is judged by B35/B36.** Stranded rate is the honest "weak" signal from this instrument
(Tymna: Wrath of God stranded in 66% of games it is drawn, Overwhelming Stampede 65%, mostly
expensive cards still uncast at turn 12).

### B31 (2026-11-07): strong and weak cards shipped (`ratings/card_verdicts.py`)

`/analyze {"card_stats": true}` now also returns `card_verdicts: {strong[], weak[], instrument}`;
each item is `{name, kind, text, evidence}`. Kinds: strong = `speeds_kill` (significant, >= 0.30
turns), `combo_piece`, `commander_synergy`; weak = `stranded` (with reason `colour` / `cost` /
`outranked`), `slows_kill`, `redundant` (stated in card counts). A card named strong is never
also named weak; commanders are never named.

Hand review on 8 real decks (Krenko, Tymna, Marchesa, Kaalia, Urza, Syr Gwyn, Lathril, Doran)
changed four rules before anything shipped, all for the same reason: a sentence the numbers did
not support.

1. "Stranded" first said Wrath of God "costs 4 and the deck rarely gets there" in a deck that
   reaches 4 mana easily. tier0 now records, at game end, whether a stuck card was blocked by
   COLOUR (enough mana, wrong pips) or COST (not enough mana); otherwise it was OUTRANKED
   (castable, a better play every turn). Outranked is never said of interaction (an unopposed
   game has nothing to answer) or of a card the goldfish cannot fully read.
2. Solemn Simulacrum and Great Forest Druid were named "speeds the kill" AND "redundant". Strong
   now excludes weak, and redundancy is named only when the role is over-supplied in CARDS and
   is stated in cards ("16 draw cards against a typical 11"), not in role-strength units.
3. "Slows the kill" fired on Phyrexian Arena, Fruit of the First Tree and protection: draw pays
   off after a 12-turn unopposed race, and tier0 executes Fruit's death trigger as an immediate
   draw. It is now limited to clock roles (ramp, finisher, plain bodies) AND `goldfish_legible`
   cards (every ability is one tier0 executes). What remains: Cultivate / Harvest Season in a
   one-drop elf deck, Planar Engineering in Doran.
4. Ugin, the Spirit Dragon read "speeds the kill +0.6" in Urza. **Engine defect, fixed in the
   tagger:** rung 1 read planeswalker ULTIMATES as on-cast effects (Ugin's -10 as draw 7 + a
   Kaalia-style cheat, Jace Wielder's -8, Liliana of the Dark Realms' -6 as 3 ramp sources). An
   ability costing more loyalty than the walker starts with can't be activated on entry
   (CR 606.6), so `tags._reachable_text` drops it. 114 -> 102 of 311 commander-legal walkers keep
   tier0 effects, all from abilities they can use. Guard (`scripts/bracket_accuracy.py`, 624
   labelled decks): exact 58.7% -> 58.5%, within-one 91.8% -> 91.8%, bias -0.08 -> -0.08; exactly
   one deck moved (a 20-planeswalker superfriends list, label B2, estimate 2 -> 1: its ultimates
   had been read as a wipe and card draw). A correct model costing one self-label match.
   Known under-count left as is: a repeatable "+1: draw a card" is tagged as one draw.

While fixing (4) a new module-level regex reused the name `_LOYALTY_COST_RE`, which already
existed in tags.py, and silently broke loyalty-ability classification for every planeswalker;
the suite caught it (3 tests). Renamed; the invalid guard run was discarded and redone.

### B34 (2026-11-07): kill-method attribution shipped

**Goldfish (tier0).** Every point of damage is credited to the card that dealt it and to a source
class: `combat` (creatures, and anthems by their share of the bonus), `commander`, `burn`
(scaling burn, magecraft / cast-damage engines). The bookkeeping mirrors every change to the
sim's damage pools, wipes included, and a test pins that it sums to exactly the damage the game
counted. `apply_nut_kills` now records its detector (`storm`, `overrun`; a tie stays the damage
kill). Cost: 2.13 s -> 2.21 s per 1,500 games (+4%), identical play.
`/analyze` returns `kill_methods: {games, killing_games, method_share, median_kill_turn_by_method,
damage_share, top_damage_cards}`, always on (it reads the analysis's existing games).

**Engine fix it forced: commander damage (CR 704.5a) in the goldfish.** tier0 counted only
life, so a commander-centric deck's kill came late whenever its commander alone had dealt 21
first. Measured before fixing, on 8 real decks: 21% of Marchesa's games, 15% of Syr Gwyn's, 10%
of Doran's, 6% of Krenko's. tier0 now ends the game at 21 commander combat damage
(`kill_method: commander_damage`, the same name as T2's end reason). Marchesa now kills in
251/300 games (was 213), 26% by commander damage. Guard (624 labelled decks): exact 58.5% ->
58.2%, within-one 91.8% -> 91.8%, bias -0.08 unchanged; two decks moved up one bracket, both
sitting on a strength cut line, one of them literally "Kenrith Voltron". Follow-up: the strength
model's cut lines were fitted on the old clock; re-fit after this and B31
(`scripts/bracket_strength_fit.py --collect`, then `--bake`).

**Duels (T2).** Each player now counts combat vs noncombat life loss; a `life` loss is split by
which dealt more, the end reason itself is unchanged. `DuelResult` gains `win_methods_a/_b`
(combat / noncombat / commander_damage / combo / decked / adjudicated), so `/duel` says how
games were won. Golden master regenerated after verifying every pre-existing field identical in
all 16 scenarios.

**Real decks, how they kill unopposed:** Lathril 62% alpha-strike (median T7); Syr Gwyn 39%
through its commander; Kaalia 100% combat from cheated-in dragons. Fidelity limit to state in
the report: tier0 attacks with every commander and does not model token makers, so Krenko reads
as his own top damage dealer.

### B32 (2026-11-08): kill speed as a range, one player and the table

`ratings/kill_speed.py`. **One player, unopposed** (always on, from the same goldfish runs as
`avg_kill_turn`): `kill_speed: {games, horizon, killing_games, kill_rate, mean, p25, median, p75,
by_turn{6,8,10}, text}`. `by_turn` is a share of ALL games, so a deck that often never kills
cannot look fast; `mean` equals `report.avg_kill_turn` exactly (pinned by a test, and on all 7
real decks checked). No kill reads "Unopposed: no kill in N games (12-turn horizon).", never a
turn.

**The table, measured** (opt-in, `/analyze {"table_speed": true}`; ~2 s per 100 four-seat games
plus a one-off ~7 s field load): pods against corpus decks labelled `# bracket: N` with the
deck's estimated bracket (or `table_bracket`), so the wording is "against a field of 176
Bracket 3 corpus decks". Reports wins of games with a 90% Wilson interval against the 25% even
seat, then the round it wins when it is last player standing (p25/median/p75). Turn-cap
adjudications are a win but not a kill, so they are counted apart. The goldfish capacity
(`pod_close_turn`) follows as the "unopposed" line. `/pod` gains `field_bracket` and returns
the field's name; `PodRating` gains `kill_wins`, `adjudicated_wins` and `win_rounds`. The field
is a stand-in until B35 curates one deck per archetype.

**Real decks** (300 goldfish games, 100 pods each):

| Deck | Unopposed median kill (middle half) | Killed by T8 | Pod wins (90% interval) | Median winning round |
|---|---|---|---|---|
| Doran (B3) | T8.5 (8-9) | 48% | 51% (43-59%) | 14 |
| Lathril (B3) | T8 (7-9) | 60% | 32% (25-40%) | 14.5 |
| Kaalia (B5 field) | T9 (8-10) | 43% | 32% (25-40%) | 17 |
| Krenko (B3) | T10 (9-10) | 14% | 22% (16-30%) | 14 |
| Syr Gwyn (B3) | T10 (9-11) | 9% | 22% (16-30%) | 21.5 |
| Urza (B3) | T11 (10-11) | 1% | 20% (14-27%) | 16 |
| Tymna (B3) | T11 (10-11) | 2% | 14% (9-21%) | 19.5 |
| Marchesa (B3) | T11 (10-11) | 1% | 11% (7-17%) | 16 |

Goldfish speed and pod results agree on the ends (Doran and Lathril fast and winning, Tymna and
Marchesa slow and losing) but not in between. Krenko kills unopposed in 99% of games yet wins
below an even seat: a goldfish has nobody blocking a go-wide board. That gap is why the table
headline is the measured pod, not capacity. Pod rounds run 4-10 later than the goldfish kill:
three opponents, blockers and a 120 life total.

Limits: pod reactions are 1v1-only (`ratings/pod.py`), so counterspells and instant-speed
removal do nothing at the table. The corpus field mixes archetypes in whatever proportion the
corpus holds, until B35.

### B33 (2026-11-08): combos on the clock

`ratings/combo_clock.py`, `semantics/tutor_reach.py`; `POST /analyze {"combos": true}` ->
`combo_clock: {combos[], killing_games, p25, median, p75, by_turn, combo_first_games,
combo_first_median, lead_combo, text}`. About 1 s per deck.

**Method.** Each graded combo is replayed over the goldfish games already played (tier0 records
the turn each card was first seen and the mana available each turn), by a pilot who
prioritises the combo: fire it if possible, else tutor a missing piece, else deploy a piece,
cheapest first, within that turn's mana. It runs per combo and takes no mana from the goldfish's
own plays. What each piece needs comes from Spellbook's own per-piece data, now kept by the
parser (`Combo.zones/needs_untapped/other_state/quantities/templates`):

- battlefield pieces are paid for on their own turn;
- "without summoning sickness" means the creature landed on an earlier turn (CR 302.6);
- hand pieces only need to be in hand, because their cost is already in `manaValueNeeded`;
- the commander needs no draw (CR 903.6).

**Prerequisites** (54% of winning combos carry one) are read, not ignored:

- "X does not have summoning sickness" is applied as a timing rule.
- "You control at least N <type>s" is counted from the deck's cast cards. Tokens are not
  tracked, so this is an under-count.
- "Your life total is at least N" passes only at N ≤ 40.
- Anything else is kept verbatim as an assumption. The combo is still timed, but it is not
  counted as a kill.

**Not timed, and said why:** graveyard, exile and library-only pieces, other required states,
multiple copies, and Spellbook template cards. A non-deterministic combo is never a kill. An
advantage combo needs an outlet. Infinite tokens without haste kill the turn after.

**Tutors** count only for what their own search text can find: the object is gated, the cost
paid, and the destination taken as the most conservative one named. Of 50 real tutors
hand-checked, all read correctly. Mystical Tutor finds only the instants, Imperial Recruiter
honours power 2 or less, Tezzeret's −X is bounded by his loyalty, and Gamble, Intuition, Gifts,
Birthing Pod, Eldritch Evolution and transmute cards are not counted.

**Accept, pinned by tests.** On a draw-only deck the assembly share is within 2 points of the
exact hypergeometric value and of a direct Monte-Carlo shuffle at every turn from T3 to T10. The
commander needs no draw. A non-deterministic or assumption-carrying combo never enters the
combined clock.

**Real decks.**

- Krenko: "kills by damage around T10; a combo kills first in 16% of games (median T8), most
  often Krenko + Skirk Prospector + Goblin Warchief". The six-Goblin prerequisite cuts its T6
  assembly rate from 6% to 1%. Brash Taunter + Aetherflux Reservoir is timed but not counted:
  it needs lifelink and 51 life.
- Corpus B4/B5 sample (20 decks with combos, 65 combos): 54 timed, 32 of those with a stated
  assumption, 11 not timed. Examples: Marneus Calgar, combo first in 39% (median T6, Demonic
  Consultation + Thassa's Oracle); Heartless Hidetsugu + Fiendish Duo, first in 50% (median T6).

**Limits.** Mana colour is not checked, since tier0 tracks a count of available mana. The pilot
is unopposed. Summoning sickness is taken from Spellbook's own flags; it flags the creatures
whose tap the combo uses, not ones like Krenko, whose haste comes from Goblin Warchief.

### B37 (2026-11-08): strengths and weaknesses against bracket peers

A strength is the top quarter of the deck's bracket peers, a weakness the bottom quarter, ranked
with `reference.percentile_rank` on a p0..p100 grid (5-point steps, ties take the plateau's
middle) baked per bracket and metric by `scripts/bracket_axis_reference.py`. Peers are the
labelled corpus decks of the bracket the deck is ESTIMATED at -- the same population as the
mentor's `vs_bracket`. Each line leads with the ABSOLUTE verdict word and then the peer rank:
"Wipe resilience: moderate (51/100), lower than 77% of Bracket 2 decks". The absolute word comes
from `insight.absolute_band`, the one definition `mentor.verdicts` grades against (interaction's
55/30 bands moved there from the mentor). "No multiplayer closing power" stays a measured fact.

**The corpus it ranks against grew first** (`scripts/grow_labelled_corpus.py`, `data/label_audit.py`):
624 -> 2,122 labelled decks. 178 distinct WotC precon lists from MTGJSON (Wizards places precons
at Bracket 2) and 1,508 more Archidekt self-labelled decks, most-viewed first. Every label is
audited against the two gates the rules state objectively: Game Changers (0 at B1-2, 3 at B3) and
two-card INFINITE combos at B1-2 (Spellbook's "Near-infinite" is finite and does not count). 188
labels failed and were demoted to `# bracket_claimed:`; 11% of the original 624 broke their own
bracket's rules, B1 worst. Mass land denial and extra turns are not audited: the engine's `_scan`
also fires on Pox, Tectonic Hellion, Magosi and planeswalker ultimates (a live-gate defect,
open).

**Accept: each strength fires for 15-35% of a bracket's decks.** 2,118 decks, by estimated
bracket: 22 of 25 strength cells in range (old fixed bars: 12 of 25, worst 56%). Misses: B2
closing power 40%, B2 consistency 34-38% depending on run, B1 closing power 8% and B1 ceiling 14%.
The cause is that decks the engine RATES Bracket 2 close tables better than decks builders LABEL
Bracket 2. Ranking against estimated peers puts every cell at 25% by construction; rejected, so
the peer population stays the one the mentor quotes and does not move with every model refit.

**Mentor bench** (overview question, 9 decks): first wording (peer rank only) 7/9 then 6/9 and
6/9 -- the bare "worse than 77% of Bracket 2 decks" read to the model as "vulnerable to board
wipes" at an absolute "moderate". With the absolute word leading: 7/9 and 8/9. Same-day baseline
on the pre-B37 lines: 8/9 and 7/9, failing on the same two decks. Unchanged.

**Strength model on the grown corpus** (owed since B31/B34). The live model, fitted on 619 decks,
scores exact 60.1%, within-one 95.2%, B1-3 exact 59.6% on all 2,116; a refit cross-validates at
60.8% / 96.2% / 59.8% but trades B1 recall 55% -> 38% for B2 55% -> 70%. Not baked. Finding: the
live model places 50 of the 140 gate-clean precons at Bracket 1 -- it under-rates precon-level
decks at the 1/2 boundary.

### B36 (2026-11-08): exposure to hate

`ratings/exposure.py`, `/analyze` `exposure`, a "Weak against" section in the strength panel.
Nine rows, each emitted only past a corpus percentile (2,112 audited labelled decks) or, for wipes
and speed, the bottom quarter of the deck's bracket peers: graveyard (6+ cards whose own text uses
the graveyard as a resource, p80), commander (1.9+ kill turns lost with it answered twice, p80 of a
300-deck sample), wipes, artifacts (8+ artifact ramp pieces, p80), enchantments (15%+ of nonland
cards, p80), flyers (no flying or reach creature), single combo (one card shared by every
game-ending combo), mana base (27+ nonbasics in a multicolour deck, p80) and speed (slower than
three quarters of the bracket; the combined damage-or-combo clock when a combo wins first).

The commander row is the one new simulation: `tier0.simulate(commander_removals=N)` answers the
commander at the start of the turn after it lands, takes back exactly what it added, and recasts it
with tax; 0 is byte-identical and a commander-less deck is unchanged (both pinned). Reading checks:
Guardian Project's "a creature card in your graveyard" is a name check, not reliance (dropped);
Underworld Breach ("...in your graveyard has escape") kept; keyword lines are "Reach, deathtouch"
form (fixed a capitalisation miss). Live: Greasefang reads graveyard (10-12 cards), commander
(-2.5 to -2.7 turns) and wipes; a Goblins deck wipes and flyers; Oloro enchantments and flyers, its
speed row correctly silent once the combo clock counts.

### B35 (2026-11-08): reference field and matchups

**Field** (`scripts/build_reference_field.py` -> `src/mythgauntlet/data/reference_field.json`): 1,667 audited labelled
decks of Brackets 1-4 analyzed once and given one archetype -- voltron (half or more of goldfish
kills from the commander: its own damage, or 21 commander damage), graveyard, spellslinger,
artifact/combo, go-wide, control, midrange -- from the engine's archetype, Forge's theme detector
and B34's kill methods. Per (bracket, archetype) cell the deck nearest the cell's median strength
score is the pick: all 7 archetypes at every bracket (cells of 6-213 decks). A first sweep found no
Voltron at all: B34 splits "commander" from "commander_damage" and only one was read.

**Matchups** (`ratings/matchups.py`, engine `/matchups`, Forge `/api/deck/{id}/matchups` cached per
decklist hash, a "Scout matchups" panel on the deck page): 120 Tier-2 duels per field deck, seats
alternated, Spellbook combos for both sides; weak below 40% with the 90% interval under 50%,
favoured above 60% with it over 50%; WHY from the field deck's win methods; the fidelity note
printed with every result. ~5-8 s per deck.

**Accept.** Stability: each field deck's win rate against the rest of its field at seeds 42 and 7
-- largest difference z = 2.5 over 28 cells, under the ~3.0 multiple-comparison bar (three cells
above 2). Two defects found on the way: partner decks lost their second commander in duels (the
duel takes one; partners now ride as cards, `/duel` fixed too), and matchup duels ran without the
decks' combos (an Oloro Thassa's Oracle list read weak against three archetypes; with its combos,
favoured against two and even against the rest). Hand review: a fast Goblins deck favoured against
the whole Bracket 2 field by combat; Greasefang mostly even. Open: `/duel` still runs combat-only
(no combos), as `/pod` does by design.

