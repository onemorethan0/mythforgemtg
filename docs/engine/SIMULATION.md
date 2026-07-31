# Simulation — engine tiers, agents, orchestration

## Tier 0 — Goldfish consistency engine (built, MVP)

One player, no opponent. Simulates the parts of Magic that are *statistics in disguise*:
opening hands, mulligans, land drops, mana development, and how efficiently the deck deploys
its curve. This alone already measures more than any existing power calculator, because it
plays the actual list rather than pattern-matching it.

**Per game:** shuffle → draw 7 → London-lite mulligan policy (Commander free first mulligan;
keep 2–5 lands, scaled for smaller hands) → for each of N turns: draw, choose and play a land
(untapped preferred, color needs considered), compute available mana (lands + rocks/dorks cast
on earlier turns), greedily cast from hand (ramp prioritized early, then draw, then
biggest-impact castable), apply rung-1 effects (ramp adds future mana sources; draw adds
cards; taplands enter tapped).

**Per-game record:** mulligans taken, land drops hit per turn, cumulative mana spent vs. mana
available, commander cast turn, cards left dead in hand at horizon.

**Aggregated (over ~1k–10k seeded games) into the Consistency & Speed axes:**
keepable-hand rate, land-drop reliability T1–T5, color access rate, curve efficiency
(mana spent ÷ mana available), commander-cast-turn distribution, dead-card rate.

Simplifications are documented in `sim/tier0.py` docstrings and are *by design* — T0 exists to
be fast (≈10⁴ games/sec), deterministic, and CI-runnable, not to be complete.

### Commander cheat-into-play engines (2026-07-18)

Many casual decks live or die on the commander's engine, not their curve — Kaalia of the Vast
"puts an Angel/Demon/Dragon from your hand onto the battlefield attacking", so a hand full of
7-drops is a fast clock, not dead weight. T0 previously hard-cast everything by cost, so those
threats stranded in hand (high `dead_cards`, near-zero ceiling) and the deck rated **Exhibition
(B1) when it plays like B3** — a systematic under-read of engine-commander decks (measured on a
real Kaalia list). This models the pattern honestly at rung-1:

- **Detect** (rung-1 heuristic, `tags.analyze`): a card whose Oracle text says "put ... from
  your hand onto the battlefield" flags `EffectVector.cheats_creatures`. Catches Kaalia, Sneak
  Attack, Elvish Piper, Quicksilver Amulet — and does NOT depend on the CCM (Kaalia's is
  miscompiled), so it's robust.
- **Model** (`sim/tier0.py`): while an enabler is online and able to attack (a creature enabler
  like Kaalia is active the turn after it resolves), each combat the deck cheats its single
  biggest STRANDED creature (one it couldn't cast) into play tapped-and-attacking — its power
  hits this turn and it stays on board after. One per turn.
- **Documented over-counts:** the tribe restriction is ignored (cheats the biggest creature, not
  only Angels/Demons/Dragons — close for a Kaalia deck); one cheat/turn (Sneak Attack could do
  more); noncreature enablers get a one-turn delay they don't strictly need. Never over-counts
  a deck WITHOUT the enabler (no text → no change), so it can't inflate a normal list.

### Storm / spellslinger go-off — the commander-as-engine ceiling (2026-07-18)

A spellslinger commander is a PERMANENT engine judged against the whole spell base: Prismari, the
Inspiration gives *every* instant/sorcery storm (copy for each spell cast before it). The goldfish
clock measures COMBAT, and the combo axis reads a fixed database, so this emergent engine (storm +
magecraft payoffs + rituals + burn finishers) was invisible and the deck's Ceiling read 0. This
adds a bounded **go-off estimator** for the Ceiling axis (the nut-draw measure — "how good is the
BEST draw", so a best-case model is correct here, not a fantasy about the average game):

- **Detect the engine at rung-1** (`semantics/tags.analyze`, since the CCMs compile these to
  no-ops): `grants_storm` (a card gives your spells storm), `mana_on_cast` (magecraft treasure /
  ritual mana returned per cast), `scaling_burn` (X-damage finisher, Fireball/Comet Storm),
  `spell_cost_reduction`, and per-cast burn split by whether COPIES trigger it — `magecraft_damage`
  (magecraft: fires on cast OR copy, so storm amplifies it) vs `cast_damage` (Guttersnipe: fires
  only on the CAST, not the copies).
- **Simulate the go-off turn** (`sim/storm.py`, deterministic, no RNG): at each turn T, take the
  T0 nut-draw mana, then cast the cheapest spells one at a time. Storm counts spells cast *before*
  each one this turn, so the Nth cast is copied `N-1` times: `storm_count += 1`; a magecraft payoff
  fires `storm_count` times (cast + copies), a cast-only payoff (Guttersnipe) fires once; net mana
  accrues per cast+copy; then the burn finisher is cast last, at the peak count, and it + its copies
  each deal X (= remaining mana). The earliest T that reaches lethal (40) is the go-off turn; it
  feeds the Ceiling (like the combo boost) and the bracket (a deck that wins on its nut draw is
  >= Bracket 3).
- **Honest limits (invariant #3):** a best-case *ceiling* estimate — assumes the engine pieces are
  reachable, ignores opponents/interaction/targeting, bounds the chain, and only fires with the
  FULL engine (granter/storm + payoff + spell density), so it never inflates a fair deck. Native-
  storm payoffs without a granter, and treasure-mana doubling (Goldspan), are coarse in this cut.
- **Precision (over-fire guard):** the per-cast/scaling burn must reach a PLAYER (not "to target
  creature" / "among creatures and/or planeswalkers") AND, for a per-cast payoff, trigger on a
  noncreature/instant-sorcery/magecraft cast (not a creature cast). This kills the two real corpus
  false positives — a Rakdos big-creature deck (Shatterskull's creature-only X, Screamer-Killer's
  creature-cast burn) no longer reads as storm.
- **Validated (400 games, seed 42):** a real Prismari list goes off ~T5 → Ceiling **0 → 28**,
  Bracket **2 → 3 (Upgraded)**. Over-fire guard held: Kaalia / Vorel / Aang gained no go-off/bump;
  a full corpus sweep (111 decks) fires on exactly **1** — a genuine Kuja spellslinger (Guttersnipe
  + Storm-Kiln + 43 noncreature spells) — and no fair/midrange deck.

### Go-wide / overrun finisher — the alpha-strike ceiling (2026-07-18)

The same "finisher the combat clock can't see" logic applies to a one-shot mass pump (Craterhoof
Behemoth / Overrun / End-Raze / Triumph of the Hordes): the T0 clock swings the board at its
*current* power, so it never sees that a wide board of small creatures becomes lethal in one
swing once the pump fires. `sim/overrun.py` is the sibling of `sim/storm.py`:

- **Detect the finisher at rung-1** (`overrun_pump` / `overrun_scales` on the EffectVector): a
  `creatures you control ... get +N/+N` (or `+X/+X`) team pump. The **precision guard** is
  requiring *until end of turn* in the same sentence — that excludes STATIC anthem lords
  (Intangible Virtue, Diregraf Captain, Mikaeus), which pump permanently and are not alpha-strike
  finishers. `+X/+X` sets `overrun_scales` (Craterhoof: X = your creatures).
- **Estimate the alpha strike** (`estimate_overrun`, deterministic): reads the T0 **nut** go-wide
  board (P75 of `final_board_power` / the new `final_board_creatures`) and asks whether one swing
  with the pump reaches lethal — `board_power + creatures × pump` (a scaling pump adds
  `creatures²`). Fires only with a real finisher AND a wide board (>= 3 creatures).
- **Feeds the Ceiling only, NOT the bracket.** A go-wide overrun is a *fair* wincon (many B2
  precons run one), so it lifts the nut-draw Ceiling axis but — unlike a storm combo-kill — does
  not gate the bracket. This is deliberate: gating fair green decks to Bracket 3 would hurt casual
  B1–3 accuracy.
- **Validated (corpus sweep, 111 decks):** 35 have a detected finisher, 22 read a lethal alpha —
  all genuine wide green decks (Selvala/elfball/tokens, 6–12 creatures; Craterhoof, Finale, Ezuri,
  End-Raze). No anthem-lord false positive. Over-fire guard held: Prismari / Kaalia / Vorel / Aang
  gained no overrun. T0 change is purely additive (`final_board_creatures` mirrors
  `final_board_power`, changes no decision) — golden master + determinism bit-for-bit.

## Tier 1 — Scripted pressure (planned next)

T0 plus a **meta clock**: a statistical model of what a Commander table does to you, without
simulating opponents as agents. Incoming damage per turn (calibrated from real game-length
data), board wipes at realistic turns (p(wipe by turn t)), targeted removal on your best
permanent, a counterspell budget against your key spells.

This unlocks the **Resilience** axis: run paired simulations (same seeds!) with and without
each disruption class and measure the outcome delta. A deck that goldfishes turn 6 but falls
apart when its enchantment eats removal shows up here — invisible to every static calculator.
Paired-seed design keeps variance low, so a few thousand games give tight deltas.

## Tier 2 — Adversarial engine (the big one)

Full multi-deck games over the CCM: zones (library/hand/battlefield/graveyard/exile/stack),
turn structure with combat, a simplified priority model (players act at defined decision
points rather than full CR §117 priority passing — documented deviation, revisited as CCM
coverage grows), state-based actions, triggered/activated abilities from CCM rungs 2–3, and
rung-1 cards resolved as effect-vector approximations so **an incomplete card pool never
blocks a game from finishing**.

- **1v1 first** (cheaper, correlates with deck quality), then 4-player with a lightweight
  threat-assessment/politics model (target selection proportional to measured threat).
- **Win conditions**: damage, decking, poison, plus CCM-declared alternate wins; games are
  capped (turn limit → adjudicated by board-state heuristic, recorded as such).

### Multiplayer (4-player pod) — stage 1 (2026-07-21)

The engine now runs **N-player pod games**, not just 1v1 (`sim/game.play_table`). The 1v1
engine is untouched (branch on player count; the golden master is byte-identical) — N>2 is new
code:

- **Turn rotation** cycles over the *living* seats (`_to_next_halfturn`); a player at ≤0 life
  or decked is **eliminated** (`_register_deaths`), and the game ends when one seat remains
  (last standing) or the turn cap adjudicates the highest-scoring survivor (`_adjudicate`).
- **Primary opponent (threat focus).** `GameState.other` now means the active player's biggest
  threat — the highest board+life score among the living — which is exactly the sole opponent
  at N=2. Combat **focus-fires** that opponent and single-target effects (removal, burn) hit it.
- **Multi-opponent "each" scaling (stage 2, 2026-07-21).** An "each opponent" effect the
  active player generates now hits the WHOLE table, not just the primary: group-slug / drain
  (`lose_life` each), each-opponent `draw` and `deal_damage`, and board wipes (`destroy`/`deal
  N to each creature`) clear every pod player's board. This is what makes aristocrats and
  group-slug behave like the pod archetypes they are. Threaded via an `others` opponent list
  (empty in 1v1 → byte-identical); single-target effects still hit the primary threat.
- **Death-trigger drains + opponent-cast fan-out (stage 3, 2026-07-21).** An aristocrat death
  drain ("when a creature dies, each opponent loses 1") now hits **all** of the dying creature's
  controller's opponents, and every **opponent's cast-taxer** ("whenever an opponent casts,
  deal 2 to them") fires when the active player casts — so go-wide aristocrats and a table of
  taxers behave like a pod. Death drains scale at the combat and single-target-removal kill
  sites (where `(opponent, *others)` is exactly the owner's opponent set), threaded via
  `_kill(others=...)`; empty in 1v1 -> byte-identical.
- **Remaining stage limits** (the next increments): death drains from a **board wipe** and from
  **activated-ability kills** still resolve against the primary only (the owner varies per
  dying creature — a documented rare case); **reactions** (counter-war, instant removal) are
  1v1-only, so multiplayer resolves spells directly; combat is focus-fire, not per-attacker
  target splitting; there is no politics/threat-negotiation model beyond static threat focus.

Even at stage 1 this is a real adversarial pod: board development, removal, combat, elimination
and last-standing wins all work, driven by the same GreedyAgent. The 4-player-aware **Pod
axis** (`axes.compute_pod`) remains the cheap capacity read; this engine is the path to a pod
*meta-rating*.

### Reactive interaction — the stack MVP (2026-07-13)

Battlecruiser fidelity previously let players act only in their own main phase, so
**counterspells and instant removal were inert** — the Interaction axis counted them but they
changed no games. This increment adds a narrow, honest stack so instant-speed answers matter:

- **Held-up mana.** A player untaps only on its own turn (already true). After making its
  primary play, its greedy agent holds up *surplus* mana (up to the cheapest instant-speed
  answer in hand, capped) rather than jamming a marginal second spell — so answers fire
  opportunistically when the controller has spare mana. It deliberately does **not** durdle a
  whole turn to hold mana up (that tempo tax made instants a net negative); modeling
  intentional tap-out-avoidance is a future upgrade.
- **Counterspells (a real, narrow stack).** When the active player casts a spell, the
  non-active player may counter it if it holds a counter, can pay from *ready* (held-up)
  sources, and the spell is worth countering (value ≥ threshold). Counter-wars resolve as a
  LIFO chain (each side may counter the other's counter until one passes or runs out); a
  countered spell is discarded with no effect. Counter cards are modeled as pure counters
  (secondary text ignored at this fidelity).
- **Instant removal window.** After the active player's main phase and *before* its combat,
  the non-active player casts held-up instant-speed removal on the active player's best
  creature — so it can't attack. Sorcery-speed removal stays main-phase-only.
- **Instant speed** = the card is an `Instant` (Flash permanents are a documented under-count).
  Counter detection: CCM `counter_spell` op, or the rung-1 `counterspell` flag.

Deliberate limits: no reactive burn-to-face, no responding to activated abilities or combat
damage, no split-second/can't-be-countered, and the counter/removal "worth it" calls are
hand-tuned heuristics (replaced by the learned agent at L5). Determinism is preserved — no new
RNG; every reactive decision is a pure function of visible state.

**Reactions as searched decisions (2026-07-21).** The counter-war and the instant-removal
window are no longer auto-resolved inside `apply`; they are explicit **decision nodes** an
Agent chooses at (`sim/game.py`): a cast puts the spell on the stack and opens a
`COUNTER_WINDOW` for the reactor (LIFO — priority alternates on each counter), and the
pre-combat window is a series of `INSTANT_WINDOW` decisions. A window becomes a decision only
when the reactor actually holds a *payable* answer, so search never branches on a non-choice.
This lets **ISMCTS** make reaction calls the greedy value function can't — counter a spell the
greedy threshold would let resolve, or hold a counter greedy would spend — while the
**GreedyAgent reproduces the old resolution bit-for-bit** (same value gate, cheapest counter,
first-payable removal, LIFO parity), so the golden master is unchanged. The "worth it" gate is
now the *agent's* choice rather than an engine constant; `_counter_chain` / `_instant_window`
remain as the greedy reference the agent handlers mirror.

### Event-trigger execution (2026-07-15)

Previously every periodic trigger (cast/attack/upkeep/...) was flattened to a draw-only
`engine_draw` approximation, so **non-draw trigger payoffs changed no games**: aristocrat
"whenever you cast" drains, attack pingers, landfall token-makers — all dropped. Now CCM
cards' event triggers **execute at their event** through the interpreter (the same
per-effect path as resolution effects). Tier affected: T2 only (T0 keeps the rung-1
`engine_draw` statistic — it has no events to fire).

Event model (each is the honest MVP convention, documented in `sim/tier2.py`):

- **`cast_spell` / `cast_creature`** — fire when the *controller* casts a spell (creature
  spell for the latter), from permanents already on the battlefield, **before** any
  counter-war: a countered spell was still cast, so its cast triggers still fire (rules-
  accurate). The just-cast permanent never triggers off its own cast. Reactive casts
  (counters and instant answers cast in the reactive windows) don't fire cast triggers —
  a documented under-count.
- **`opponent_casts_spell`** — same moment, fires for the non-active player's permanents.
- **`attack`** — declare-attackers, **subject-scope aware** (2026-07-21): an attack trigger
  is classified at CCM-load time (`_attack_subject_scope`, from the card's Oracle text + type)
  into one of three subjects, and the engine fans it out to match:
  - **self** ("Whenever *this creature* attacks") — fires once, only when that creature is
    itself among the attackers. A non-attacking creature's self-trigger doesn't fire.
  - **global-each** ("Whenever *a creature you control* attacks") — fires **once per attacking
    creature** (the fan-out this replaced the old flat under-count with); the payoff — a token,
    a draw, a drain — now scales with how wide you swing.
  - **global-once** ("Whenever *one or more creatures you control* attack" / "Whenever you
    attack" / any *non-creature* permanent's attack trigger, which has no attack of its own,
    and "attacks alone" wordings that shouldn't multiply) — fires once per combat with >=1
    attacker.

  Classification is a whole-card Oracle-text heuristic (a card with several attack triggers
  shares one subject) and the fan-out re-fires the same ability, so per-attacker *targeting*
  (e.g. "it gets +X/+X") still can't single out the specific attacker — documented
  approximations that favor the common draw/token/drain payoffs.
- **`combat_damage_to_player`** — fires for each unblocked attacker after combat damage is
  dealt (blocked attackers deal no player damage at this fidelity).
- **`landfall`** — fires when the controller plays its land for the turn.
- **`upkeep` / `draw_step`** — fire at the start of the controller's own turn ("each
  upkeep" wordings under-count to controller-only).
- **`end_step`** — fires after the controller's combat.

No double-count: a CCM permanent's `engine_draw` (which was derived purely from these same
triggers) is zeroed in the engine — its draw triggers now draw for real, at the event, only
when the event happens. Rung-1 cards keep the flat per-turn approximation. Trigger *sources*
that die after triggering still resolve (snapshot iteration — matches the stack rule that a
triggered ability resolves even if its source dies). Determinism preserved: no new RNG.

### cEDH fidelity increment (2026-07-17)

The first real-n anchor gauntlet measured B5 (cEDH) decks rating at the BOTTOM (1326 vs
B3 1603) — battlecruiser fidelity forced them into combat games they never play. Their
actual win path is `ritual mana -> tutor -> cheap combo`, and every link was missing.
This increment adds the minimum honest version of each link (T2 only):

- **Ritual mana** — a resolved `add_mana` effect on a spell (Dark Ritual, Jeska's Will)
  now grants that many READY, TEMPORARY mana sources; the main-phase loop naturally spends
  them on further casts the same turn, and they evaporate at the controller's next untap
  step. Colors honor the CCM `colors` param; an unspecified/"any" color is permissive
  (WUBRGC — a documented slight over-count). Permanent mana rocks are unchanged (they
  come from `mana_ability`, not resolution effects).
- **Tutors to hand** — `search_library` with `to: "hand"` (Demonic Tutor et al.) moves a
  real card from library to hand: a MISSING COMBO PIECE first (combo piece-sets are data
  from Commander Spellbook), else the highest-impact card matching the `what.type` filter.
  Deterministic (library order + stable max), no card names in the engine.
- **Hand-castable combo pieces** — a game-ending combo now also assembles when its
  remaining pieces are IN HAND and their combined mana value fits the controller's ready
  mana at the post-main check (previously every piece had to sit on the battlefield, so
  instant/sorcery combos — Thoracle/Consultation-class, i.e. most cEDH wincons — could
  never fire). Documented under-counts: the greedy agent may tap out before the check
  (deliberate hold-up is Phase 7); a land piece in hand passes at mana value 0.

Determinism preserved — no new RNG. The point of the increment is the re-measure: the
same seed-777 anchor gauntlet, run after these three links exist, is the falsifiable test
of whether the B5 inversion was fidelity (it should shrink) or something deeper.

### Holding combo pieces: the agent was casting away its own wincon (2026-07-31)

The three links above were all present and all working — and cEDH decks still could not
combo. Instrumenting `combo_ready` showed **98% of failed checks were a MISSING PIECE**;
mana bound only 1.4%. Unpressured (30 turns, life set unreachably high so the deck's own
clock is isolated from the beatdown race), cEDH Blue Farm assembled in only 34 of 120
games.

The defect was in the value function, not the simulation. `_combo_bonus` rewarded casting
ANY combo piece regardless of whether the combo could finish, so dedicated instants and
sorceries — whose ops the engine cannot execute anyway — were cast for their ~2.0
popularity prior and went to the graveyard. Blue Farm binned Demonic Consultation 0.85
times per game, Tainted Pact 0.82, Brain Freeze 0.88. Each deck runs ONE copy, so the
first cast removed the wincon from the game permanently.

`_combo_piece_hold` now keeps an instant/sorcery combo piece in hand (the agent already
reads `value <= 0` as "hold it"). Two details matter:

- **There is deliberately no "unless this cast finishes the combo" exception.**
  `combo_ready` resolves a combo from pieces HELD — online or in hand — plus the mana to
  cast the rest. It is a STATE, not a sequence of casts. So casting the last piece is the
  one thing that prevents the win: the card leaves hand for the graveyard and the
  post-main check then sees it missing. Holding is both correct Magic and the only way
  the engine can register the kill.
- **Permanent pieces are still cast.** They stay on the battlefield and count as
  assembled, so casting them is real progress. Only instants/sorceries are held, and only
  when the card has no independent executable value (the popularity prior is excluded
  from that test, so a piece that is also genuine removal or lethal burn still gets cast).

Measured, 120 unpressured games: Blue Farm 34 -> **120/120**, 24.4 -> 13.8 turns;
Tymna/Thrasios 36 -> 94; Meren Hulk 41 -> 66. Head-to-head vs a B2 Ghired list, 5.0% ->
16.0%. Fair B2/B3 decks that happen to run a combo were checked for regression: flat or
slightly up. Every change is gated on the player having a detected combo, so non-combo
decks (including every golden-master deck) are byte-identical.

**Remaining, and honestly so:** Blue Farm's post-fix clock is ~13.8 turns while these
games end at 8.6. That gap is the real battlecruiser-vs-cEDH fidelity ceiling. The lesson
is that "it's a fidelity ceiling" was ALSO a comfortable story that hid a specific agent
bug for two weeks — instrument and count failure reasons before attributing.

**Tutor filters must OR a flattened disjunction.** "An instant or sorcery card" compiles
as `type=instant` + `subtype=sorcery`, and the matcher AND-ed them, asking for a card that
is both — which no card in Magic is, so Mystical Tutor fetched NOTHING. A genuine subtype
(Equipment, Aura, Human) is never also a card type, so a card type sitting in the subtype
slot is an unambiguous flattened disjunction; `artifact` + `Equipment` still AND-s.

### cEDH tutor-destination fix + the assembly-vs-timing finding (2026-07-18)

**Diagnosis first.** Ranking all 11 labeled B5 decks vs a B3/B4 panel showed most win 23–48%
and — the tell — their detected game-ending combos fire ~0% of the time. `combo_ready` already
handles "pieces in hand + affordable → win", so mechanics weren't the blocker; **assembly** was.
Root cause: `_apply_resolved`'s `search_library` branch acted only on `to:hand` tutors (Demonic
Tutor class), while the DOMINANT cEDH tutors compile as `to:top` (Vampiric Tutor, Imperial Seal)
or `to:library` (Mystical/Enlightened/Worldly) — both were **silent no-ops**.

**Fix (this increment).** `to:top`/`to:library` tutors now fetch a card to the top of the library
(drawn next turn), sharing `_tutor_hand`'s missing-combo-piece-first picker and honoring the
`what.type`/`subtype` filter (Mystical → instant/sorcery, etc.). `PlayProfile.tutor` flags a card
as a tutor (any non-land `search_library`); the greedy agent gets a **finish-only** value bonus —
it prioritizes a tutor only when exactly one combo piece is missing (fetching it completes the
win), because tutoring from scratch was measured to be a net-negative tempo trap.

**Honest measured result — necessary but insufficient.** Combo-fire rate rises clearly (e.g.
Yuriko 9→31%, Meren/Tymna 5→14%), but the B5 win rate does NOT move (≈39% before and after, within
noise). Reason: combos still fire ~turn 13 (draw + limited-tutor + mana-limited), so the extra
combo wins REPLACE slow-combat wins in games already being won — they do not convert the early-
race LOSSES into wins. Both levers tried so far — a stronger agent (mcts:100, the 2026-07-17
agent-contrast) and now tutor access — leave the B5 win rate flat. Converting losses→wins requires
the combo to land EARLY (turn 3–6), which needs **fast-mana density** (ritual/Sol-Ring chaining to
an early combo turn) — the next coupled increment. Until then the rule-based bracket gates remain
the honest top-end signal (a stronger agent / more assembly does not fix an engine that can't play
the fast protected combo turn).

### Agents (Layer 3)

Phase 7 (2026-07-17) turned the imperative Tier-2 turn loop into an **action-based state
machine** an Agent drives one decision at a time (`sim/game.py`): a clonable `GameState`, a phase
cursor whose decision points are MAIN / ACTIVATION / COMBAT_ATTACK / COMBAT_BLOCK, and
`legal_actions` / `apply` / `clone` / `determinize`. This is the substrate search needs; the old
engine's rules are unchanged (a golden-master characterization test pins greedy behavior
bit-for-bit, so the calibration instrument is untouched).

1. **GreedyAgent** (`agents/greedy.py`) — the hand-tuned value function, extracted verbatim from
   the old `_main_phase`/`_activation_phase`/`_combat` loops; fast baseline **and** the ISMCTS
   rollout policy. Consumes no randomness.
2. **ISMCTSAgent** (`agents/ismcts.py`) — single-observer Information Set MCTS with
   **determinization** for hidden information (reshuffle the opponent's hand+library from the
   known deck multiset, plus one's own library order — the Cowling/Ward approach for MTG). The
   tree branches only on the root player's decisions; the opponent (and rollouts) play the greedy
   policy; rollouts are truncated (`rollout_depth`) and evaluated by the adjudication-score
   differential. Budgeted per decision (`mcts:N`), so strength trades against speed.
   *It makes the planning decision the greedy value function cannot* — deliberately holding mana
   up for a counter/removal (Phase-6 note): proven by a test where greedy jams a creature and
   taps out while ISMCTS passes to hold the counter it then lands.
   *Scope this step:* reactions (the counter-war, the pre-combat instant window) are still
   auto-resolved by the engine (greedy) — their VALUE is discovered by rolling out the "hold
   mana" line, but they are not yet independent search decisions (a documented follow-up). Combat
   attacker/blocker candidate sets are bounded for tractability.
3. **Learned policy (later)** — value/policy network trained on self-play outcomes, AlphaZero-
   style but scoped: it replaces the GreedyAgent's hand-tuned evaluation, not the whole search.

**Agent strength is part of the measurement instrument**: ratings are always reported *at* an
agent level ("gauntlet rating under mcts:1000"). `gauntlet --agent` tags its output; `duel
--agent-a/--agent-b` pits levels; `ladder` (`ratings/ladder.py`) confirms the ladder is monotone
(more search wins) before the gauntlet is re-based under a new level (see LEARNING.md). *Caveat:*
very low iteration counts can UNDERperform greedy (search noise without enough signal) — the
ladder's useful rungs start around mcts:100.

## Forge oracle (optional cross-check)

Forge (Card-Forge/forge, Java) already runs headless AI-vs-AI matches with W-L-D output and
scripts ~everything in Commander. A thin adapter (JVM subprocess; Manabrew demonstrates
in-process GraalVM if we ever need throughput) gives us:

- **Differential testing**: same matchup in Forge and T2; large win-rate divergence flags
  engine or CCM bugs.
- **Bootstrap labels**: Forge match outcomes can pre-train the card-value model before our T2
  reaches scale.

Forge is a validation instrument, not the foundation — its AI is opaque, its JVM startup is
slow, and building our measurement science on an engine we don't control would cap everything.

## Orchestration (Layer 4)

- A **simulation job** = (deck(s), tier, agent level, engine+CCM versions, seed range, game
  count). Jobs are pure functions of their spec — invariant #1 makes this true.
- **Batching (built, 2026-07-17, `ratings/orchestrator.py`):** gauntlet matchups run across a
  `ProcessPoolExecutor` (no shared state; parallel results are bit-for-bit identical to serial —
  verified on real corpus decks) with an optional disk cache keyed by a job-spec hash + an
  engine tag (the executable-semantics count, so recompiling invalidates it) for resume-for-free.
  `gauntlet --jobs N --cache`. This is what makes an ISMCTS-agent gauntlet affordable overnight
  (measured 4x on 7 uneven mcts jobs; approaches core count on a full gauntlet). Default
  `--jobs 1` — parallelism is a net loss for cheap greedy matchups where pool overhead dominates.
  *Open:* a real SQLite `results.db` with per-turn aggregates (today it's a flat JSON win/loss
  cache); GPU-side, a lockstep vectorized env was investigated and rejected — see
  `spikes/GPU_VECTORIZATION_FINDINGS.md` (fast but discards colors + semantics; the GPU's role is
  the LLM compiler + a future learned evaluator, not the rules engine).
- **Budgeting (future):** analyses declare a games budget; the orchestrator spends it where
  variance is highest (more games for close win rates, fewer for blowouts) — sequential sampling
  with confidence stopping.
- **Reproducibility**: every report can name the exact job specs behind every number.
