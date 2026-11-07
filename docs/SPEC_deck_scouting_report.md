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
strength at that bracket. Committed as data (`data/reference_field.json`) so results are
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
