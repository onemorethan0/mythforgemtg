# SPEC — commander damage (CR 704.5a), `src/mythgauntlet/sim/{tier2,game}.py`

ROADMAP.md S18: "No legend rule or commander-damage modeling in sim... an entire Voltron/
commander-damage win condition is structurally invisible to the strength engine."

## What this closes, and what it doesn't

**Commander damage — CLOSED.** A player who has taken 21 or more combat damage from a single
opposing commander loses the game (CR 704.5a), independent of their own life total. The T2
action-based engine (`sim/game.py`, the state machine `duel`/`pod`/`gauntlet` all run on) had
no notion of this at all — a Voltron deck's commander could deal unlimited unblocked combat
damage and the engine would only ever check the DEFENDER's life total, which a 40-life pool
absorbs far longer than 21 damage from one source actually allows in a real game.

**The legend rule — NOT AN ISSUE, and that itself is worth recording.** Investigated before
writing any code: the engine has no clone/copy-effect modeling anywhere (`_Permanent` has no
"copy of" concept, and nothing in `tier2.py`/`game.py` ever creates a second permanent sharing
a name with one already on the battlefield). A player's commander is represented as AT MOST
one `_Permanent` at a time — cast from the command zone, it replaces nothing because nothing
else with that name can exist yet. **The legend rule literally cannot trigger under the
current card-effect model** — there is no code path that would ever create the state-based
check's precondition. This is not "deferred," it is "not applicable until clone effects are
modeled," which is real, separate, larger future work (a Clone/Vesuvan Shapeshifter-class
effect is not on any current roadmap item). Recorded here so a future session does not
re-open S18 assuming both halves are still open.

## Method

`commander_damage_lost(player) -> bool` (`tier2.py`) is the ONE shared check — a duplicated
`>= 21` at each of the four call sites below is exactly the "two structures must agree" class
this repo has been bitten by repeatedly (the theme taxonomy's three structures, the
`edhrec_lift`/`mythgauntlet.data.edhrec` slug duplication).

**Data model** (`_Player.commander_damage_taken: dict[str, int]`, `tier2.py`): cumulative
combat damage taken from ONE opposing commander, keyed by that commander's CONTROLLER's seat
key (not the permanent's own identity — this engine represents at most one on-battlefield
commander permanent per player, so "damage from player X's commander" is unambiguous without
tracking the specific permanent). `_clone_player` (`game.py`) copies this dict — MCTS clones
game state at every search node, and a field left out of `_clone_player` silently stops
existing the moment a clone is taken, which would make commander damage invisible to search
while still real in the root game (a "looks correct in tests, wrong under search" class of
bug worth naming even though it didn't happen here — caught by adding the field to
`_clone_player` in the SAME edit, not as an afterthought).

**Accrual** happens in exactly ONE place: `_apply_declare_blocks` (`game.py`), the sole
combat-damage-to-a-player application site. Only the UNBLOCKED branch accrues — CR 704.5a
counts combat damage dealt **to a player**, and a blocked commander's damage goes to the
blocking creature, not the defending player. `atk.is_commander` (an existing `_Permanent`
field, not new) gates it.

**Loss check** appears at all FOUR places the engine already checks `life <= 0`, matching
their existing asymmetry exactly rather than inventing a new pattern:
- `_register_deaths` (N-player/pod): every living player, alongside `decked`/`life<=0`.
- `_do_turn_start`, `_do_post_main` (1v1): only `opp` (the NON-active player) — mirrors the
  existing code's own asymmetry (it never checks `me.life<=0` at these two points either,
  because a self-loss would already have ended the game at the END of the player's own
  previous turn).
- `_do_end_step` (1v1): BOTH `opp` and `me` — the one checkpoint that already checks both
  life totals, so it is the one checkpoint that must check both commander-damage totals too.

A new `_finish(..., reason="commander_damage")` distinguishes this from `"life"` in
`GameState.result`, the same way `"decked"`/`"combo"`/`"eliminated"` already are.

## Verified

**Golden master**: `tests/data/tier2_golden.json` deliberately regenerated — exactly ONE of
93 scenarios changed. `commander_recast` (a 5/5 "Big Commander" vs. an aggro deck, previously
40-0 to the aggro side) flipped to `wins_a: 8, wins_b: 32`. This is the EXACT S18 gap made
concrete: a 5/5 commander attacking unblocked reaches 21 damage on its 5th connection (25
total, well inside the 25-turn cap), a kill the old engine could not see and the new one
correctly does. All other 92 scenarios are byte-identical, confirming the change's blast
radius is exactly the commander-damage path and nothing else.

**New unit tests** (`tests/engine/test_game.py`): `commander_damage_lost`'s threshold exactly
at 21 (not 20, not 22); `_clone_player` preserves the dict across a mutation of the original;
an unblocked commander attack accrues damage AND reduces life normally; a BLOCKED commander
attack accrues nothing; a non-commander attacker dealing the same raw damage does NOT accrue
commander damage (life loss only); and an end-to-end `duel()` run confirming a 5/5 commander
against an empty-board opponent wins every game via commander damage inside the turn cap.

**Live, real corpus data**: `mythgauntlet duel` between two real corpus decks completes
without error at realistic semantics coverage (87%/67%). A limited-scope full-corpus
`gauntlet --opponents 3 --games 10` sweep run to check for any crash on unusual real card
combinations (see ROADMAP.md S18 for the result once it completes).

## Deliberately not done

- **Partner-commander damage is not tracked per-commander.** A real partner pair deals
  damage from TWO distinct sources, each independently capable of reaching 21 — this
  engine's `_Player.commander` (singular) and `commander_damage_taken` (keyed by
  controller, not permanent) cannot distinguish them. Rare in practice (a partner deck's
  SECOND commander is simulated as an ordinary library card per `ratings/analysis.py`'s own
  documented partner-commander compromise, so it doesn't get a dedicated attacking-commander
  permanent at all today) — not a regression, just an existing simplification this fix
  inherits rather than one it introduces.
- **No score() integration.** `_Player.score()` (turn-cap adjudication) and
  `score_reward()` (MCTS rollout leaf evaluation) do not read `commander_damage_taken` at
  all — a player sitting at 20 accumulated commander damage looks no closer to losing than
  one at 0, to a truncated rollout or a turn-cap draw call. This only matters for games that
  don't actually END via commander damage before the cap/truncation point, which is a
  real but narrower gap than "the win condition is invisible" (the win condition itself now
  fires correctly; only the SEARCH HEURISTIC undervalues progress toward it).
