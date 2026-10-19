# Commander Lens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make role counts, Resilience, Deck Breakdown and Deck Mentor commander-aware, so that, for example, Blasphemous Act under Smaug the Impenetrable reads as a one-sided wipe that also ramps.

**Architecture:** A pure module, `semantics/commander_lens.py`, derives a `CommanderLens` from the command zone's printed keywords and oracle text. It returns additive per-card `LensFacts`. Consumers read those facts: `redundancy` roles, the tier0 wiped run, the mentor tools, gate and diagnose, and the breakdown UI. Base `EffectVector` semantics are never changed.

**Tech Stack:** Python 3.14, pytest; React/Vite for the one frontend task.

**Spec:** `docs/superpowers/specs/2026-10-19-commander-lens-design.md`

## Global Constraints

- Every oracle text in a test is VERBATIM from the card store; the strings in this plan were
  pulled from it on 2026-10-19. Never retype one from memory.
- Tests stay offline: build cards with `make_card` (`tests/engine/conftest.py`), never the live DB.
- A commander that matches no interaction type must leave every output byte-identical.
- Honest under-count: when a matcher cannot be sure (unknown qualifier, unparseable amount, no
  sim context), it claims nothing. It never guesses.
- Wipe modes survived by indestructible: exactly `{"destroy", "damage"}`.
- X = floor(`mana_by_turn[t-1]`) − `card.mana_value` − counter reserve, clamped at 0, where
  `t = ceil(avg_commander_turn) + 1`, clamped to the last simulated turn. The counter reserve
  is the lowest mana value among the deck's counterspells, or 0 if it runs none. No context,
  or a commander never cast in the sim, gives X credit 0.
- Noncombat damage = everything except attacking/blocking combat damage (CR 120.2a/b). Fight is
  noncombat.
- Treasure credit only for MASS damage that hits the commander. Targeted damage, pingers and
  fight get the label only.
- One-shot payoff Treasure counts toward the Ramp role at strength `min(payoff_treasure, 2.0)`
  (`ONE_SHOT_RAMP_CAP = 2.0`, the weight `fetches_land` already uses). The card COUNT is one card.
- Interaction-axis weighting is NOT changed.
- Commit after each task; push to `origin main` at the end. The repo is public: the user
  approved pushing this work.

## Review Focus

1. **Smaug names himself "Smaug", which `tags._self_names` cannot produce.** It splits on ","
   only and yields "smaug the impenetrable". The lens must add a legend's first word (unless it
   is "the"/"a"/"an") plus "this creature". Test owned by Task 2.
2. **A partner pair.** Kinds are the union over both commanders; the Resilience flag reads the
   lead only. Test owned by Task 1.
3. **No sim context, or the commander is never cast** (`avg_commander_turn is None`). X credit
   must be 0 with no exception. Test owned by Task 2.
4. **A wipe that never touches the commander** (Ruinous Ultimatum, "your opponents control").
   It must not be labelled commander synergy, even though it is one-sided anyway. Test owned
   by Task 1.
5. **A stale breakdown cache** (written before this change) has no `commander_synergy` on its
   rows. The panel must render without it. Test owned by Task 7.

---

### Task 1: Lens skeleton + `survives_wipe`

**Files:**
- Create: `src/mythgauntlet/semantics/commander_lens.py`
- Modify: `tests/engine/conftest.py` (`_make_card` gains `keywords`, `power`, `toughness`, `layout`)
- Test: `tests/engine/test_commander_lens.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) LensFacts(wipe_one_sided: bool = False, payoff_kind: str | None = None, payoff_treasure: int = 0, reason: str = "")` with a `.empty` property.
  - `@dataclass(frozen=True) LensDeckContext(mana_by_turn: tuple[int, ...], avg_commander_turn: float | None, counter_reserve: int)`.
  - `@dataclass(frozen=True) CommanderLens(commanders: tuple[Card, ...], kinds: tuple[str, ...], ctx: LensDeckContext | None)`, with:
    - `facts_for(card: Card) -> LensFacts`
    - `survives_mode(mode: str) -> bool`: lead commander only
    - `flagged(cards) -> set[str]`: names with non-empty facts
  - `build_lens(commanders: Sequence[Card], ctx: LensDeckContext | None = None) -> CommanderLens`
  - `admits(obj: str, commander: Card) -> bool | None`
  - kind name `"survives_wipe"`
- Consumes: `tags._clean_text`, `tags._WIPE_ALL_RE`, `tags._DAMAGE_EACH_RE`, `tags._hits_creature`, `tags._flickers`.

**`admits` contract.** Does a wipe's object phrase include this commander? True or False only
when certain; None means unknown, which is treated as no claim. Read the head phrase only (cut
at `" and each "`, `,`, `.`):

| Phrase in head | Result |
|---|---|
| `opponent`, `you don't control` | False |
| `without <kw>` | False if kw in `commander.keywords`, else continue |
| `non-<word>` / `non<word>` | False if word is in the commander's type line (casefolded; e.g. Dragon, legendary), else continue |
| `with power`, `with toughness`, `with mana value`, `tapped`, `attacking`, `blocking`, any other word outside {each, all, other, creature(s), permanent(s), nonland, nontoken} | None |
| only allowed words remain | True |

- [ ] **Step 1: Extend `_make_card`** with `keywords: frozenset[str] = frozenset()`, `power: str | None = None`, `toughness: str | None = None`, `layout: str = "normal"`, all passed through to `Card`.

- [ ] **Step 2: Write the failing tests** in `tests/engine/test_commander_lens.py`, with module-level fixtures built from these verbatim texts:

```python
SMAUG = dict(name="Smaug the Impenetrable", mana_cost="{5}{B}{R}",
    type_line="Legendary Creature — Dragon", power="8", toughness="7",
    keywords=frozenset({"flying", "indestructible", "haste", "treasure"}),
    oracle_text="Flying, indestructible, haste\nWhenever Smaug is dealt noncombat damage, create that many Treasure tokens.")
WRATH = dict(name="Wrath of God", mana_cost="{2}{W}{W}", type_line="Sorcery",
    oracle_text="Destroy all creatures. They can't be regenerated.")
FAREWELL = dict(name="Farewell", mana_cost="{4}{W}{W}", type_line="Sorcery",
    oracle_text="Choose one or more —\n• Exile all artifacts.\n• Exile all creatures.\n• Exile all enchantments.\n• Exile all graveyards.")
DELUGE = dict(name="Toxic Deluge", mana_cost="{2}{B}", type_line="Sorcery",
    oracle_text="As an additional cost to cast this spell, pay X life.\nAll creatures get -X/-X until end of turn.")
RUINOUS = dict(name="Ruinous Ultimatum", mana_cost="{R}{R}{W}{W}{W}{B}{B}", type_line="Sorcery",
    oracle_text="Destroy all nonland permanents your opponents control.")
DESOLATION = dict(name="Desolation of Smaug", mana_cost="{2}{R}{R}", type_line="Sorcery",
    oracle_text="Desolation of Smaug deals 3 damage to each non-Dragon creature.\nAdd four mana in any combination of colors. Spend this mana only to cast Dragon spells.")
```

Tests, each with its assertion:
- `test_smaug_survives_wrath`: `build_lens([smaug]).facts_for(wrath).wipe_one_sided is True` and `"survives_wipe" in lens.kinds`
- `test_exile_wipe_not_one_sided`: Farewell gives `.empty`
- `test_minus_wipe_not_one_sided`: Toxic Deluge gives `.empty`
- `test_opponent_only_wipe_is_not_commander_synergy` (Review Focus 4): Ruinous Ultimatum gives `.empty`
- `test_non_dragon_filter_excludes_smaug`: Desolation of Smaug gives `wipe_one_sided is False` (Smaug is a Dragon, so he is never hit)
- `test_no_commander_is_empty_lens`: `build_lens([]).kinds == ()` and `facts_for(wrath).empty`
- `test_partner_kinds_union_resilience_reads_lead` (Review Focus 2): `build_lens([bear, smaug])` has `"survives_wipe" in kinds` but `survives_mode("destroy") is False`; `build_lens([smaug, bear]).survives_mode("destroy") is True`
- `test_face_ambiguous_commander_is_honest_undercount`: Smaug fields with `layout="transform"` and `keywords=frozenset()` give `"survives_wipe" not in kinds`, with no exception

- [ ] **Step 3: Run the tests and confirm they fail.** Run `python -m pytest tests/engine/test_commander_lens.py -q`. Expected: ImportError on `mythgauntlet.semantics.commander_lens`.

- [ ] **Step 4: Implement** the dataclasses, `admits`, `build_lens` and `survives_wipe` in `semantics/commander_lens.py`. `facts_for` scans `_WIPE_ALL_RE` (mode destroy/exile, as `tags.interaction_modes` does) and `_DAMAGE_EACH_RE` (mode damage). A match yields `wipe_one_sided` when `_hits_creature(obj)` holds, the mode is in the survived set, and `admits(obj, lead) is True`. `reason` reads e.g. `"Smaug the Impenetrable survives this (indestructible)"`. Kind detection: `"indestructible" in c.keywords` over every commander.

- [ ] **Step 5: Run the tests and confirm they pass.** Run `python -m pytest tests/engine/test_commander_lens.py -q`. Expected: all pass.

- [ ] **Step 6: Commit**: `git commit -m "lens: commander lens skeleton + survives_wipe"`

---

### Task 2: `damage_to_self_payoff` + the X budget

**Files:**
- Modify: `src/mythgauntlet/semantics/commander_lens.py`
- Test: `tests/engine/test_commander_lens.py`

**Interfaces:**
- Consumes: Task 1's `LensFacts`, `LensDeckContext`, `admits`, `build_lens`.
- Produces: kind `"damage_to_self_payoff"`; `x_budget(card: Card, ctx: LensDeckContext | None) -> int`; `lens_self_names(card: Card) -> tuple[str, ...]`.

**Detection.** On cleaned commander text, per line, match
`whenever (?P<subj>[^,.]+?) is dealt (?P<nc>noncombat )?damage`, then:
- `subj` must equal one of `lens_self_names` (`tags._self_names` + a legendary's first word
  unless it is the/a/an + `"this creature"`). Kazarov's "a creature an opponent controls" fails
  this.
- Record `noncombat_only = bool(nc)`.
- Record `makes_treasure = "treasure" in` the rest of that sentence.

**Apply.**
- Mass damage: a `_DAMAGE_EACH_RE` clause with `admits(...) is True` gives the label.
  `payoff_treasure` = the printed number from `deals (\d+|x) damage`: an int, or `x_budget` for
  x. "Equal to …" gives 0. Credit only when `makes_treasure`.
- Targeted (`tags._DAMAGE_TARGET_RE` with "any target" or a creature target), or fight: label
  only, `payoff_treasure = 0`.
- Under `noncombat_only`, spell/ability/fight damage all qualify (CR 120.2b). Nothing in a card's
  text is combat damage.

- [ ] **Step 1: Write the failing tests**, with these verbatim fixtures:

```python
BLASPHEMOUS = dict(name="Blasphemous Act", mana_cost="{8}{R}", type_line="Sorcery",
    oracle_text="This spell costs {1} less to cast for each creature on the battlefield.\nBlasphemous Act deals 13 damage to each creature.")
EARTHQUAKE = dict(name="Earthquake", mana_cost="{X}{R}", type_line="Sorcery",
    oracle_text="Earthquake deals X damage to each creature without flying and each player.")
ROLLING = dict(name="Rolling Earthquake", mana_cost="{X}{R}", type_line="Sorcery",
    oracle_text="Rolling Earthquake deals X damage to each creature without horsemanship and each player.")
BOLT = dict(name="Lightning Bolt", mana_cost="{R}", type_line="Instant",
    oracle_text="Lightning Bolt deals 3 damage to any target.")
IGNITION = dict(name="Chandra's Ignition", mana_cost="{3}{R}{R}", type_line="Sorcery",
    oracle_text="Target creature you control deals damage equal to its power to each other creature and each opponent.")
KAZAROV = dict(name="Kazarov, Sengir Pureblood", mana_cost="{5}{B}{B}",
    type_line="Legendary Creature — Vampire", keywords=frozenset({"flying"}), power="4", toughness="4",
    oracle_text="Flying\nWhenever a creature an opponent controls is dealt damage, put a +1/+1 counter on Kazarov.\n{3}{R}: Kazarov deals 2 damage to target creature.")
KLEMENT = dict(name="Klement, Tempest Acolyte", mana_cost="{1}{R}{W}",
    type_line="Legendary Creature — Tiefling Cleric", keywords=frozenset({"double strike"}), power="2", toughness="3",
    oracle_text="Double strike\nWhenever Klement, Tempest Acolyte is dealt damage, it deals that much damage to any target.")
CTX = LensDeckContext(mana_by_turn=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12), avg_commander_turn=6.2, counter_reserve=0)
```

Tests:
- `test_blasphemous_act_under_smaug`: `payoff_treasure == 13`, `payoff_kind == "damage_to_self_payoff"`, `wipe_one_sided is True`
- `test_earthquake_never_hits_flying_smaug`: `payoff_kind is None` and `payoff_treasure == 0`
- `test_rolling_earthquake_x_from_budget`: t = ceil(6.2) + 1 = 8, mana 8, MV 1 (`{X}{R}`), so `payoff_treasure == 7` with `CTX`; with `counter_reserve=2` it is `5`
- `test_x_without_context_is_zero` (Review Focus 3): `build_lens([smaug]).facts_for(rolling).payoff_treasure == 0`; the same holds with `avg_commander_turn=None`
- `test_bolt_is_label_only`: `payoff_kind == "damage_to_self_payoff"` and `payoff_treasure == 0`
- `test_equal_to_damage_is_label_only`: Chandra's Ignition gives the label with `payoff_treasure == 0`
- `test_short_legend_name_detected` (Review Focus 1): `"smaug" in lens_self_names(smaug)` and Smaug's lens has the kind
- `test_full_name_subject_detected`: Klement's lens has the kind; Blasphemous Act gives the label with `payoff_treasure == 0` (no Treasure)
- `test_other_subject_not_detected`: Kazarov's lens has no `damage_to_self_payoff`

- [ ] **Step 2: Run the tests and confirm they fail.** Run `python -m pytest tests/engine/test_commander_lens.py -q`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement** detection, apply, `lens_self_names` and `x_budget(card, ctx)` per the Global Constraints formula. When both kinds apply, a card's facts merge: one `LensFacts`, `wipe_one_sided` OR-ed, `payoff_kind` set, reasons joined with "; ".

- [ ] **Step 4: Run the tests and confirm they pass.** Run `python -m pytest tests/engine/test_commander_lens.py -q`. Expected: all pass.

- [ ] **Step 5: Commit**: `git commit -m "lens: damage_to_self_payoff with oracle-confirmed subject and X budget"`

---

### Task 3: `death_payoff`

**Files:**
- Modify: `src/mythgauntlet/semantics/commander_lens.py`
- Test: `tests/engine/test_commander_lens.py`

**Interfaces:**
- Produces: kind `"death_payoff"` (label only; never `payoff_treasure`).

**Detection.** Commander text matches
`whenever (?:a|another|one or more)(?: other)?(?: nontoken)? creatures?(?: or planeswalkers?)? you control (?:dies|die)`
or `whenever (?:this creature or )?another creature dies` (that also counts yours). Reject
anything containing "an opponent controls".

**Apply.** The label is given to:
- the pilot's wipes whose modes include destroy / damage / minus / static_minus / edict (from
  `tags.interaction_modes(...).wipe`), where `_hits_creature` holds, the object is not
  opponent-only, and bounce/exile-only wipes are excluded (they do not die);
- sacrifice outlets matching `sacrifice (?:a|another) creature:` as an activated cost.

- [ ] **Step 1: Write the failing tests**, with these verbatim fixtures:

```python
MEREN = dict(name="Meren of Clan Nel Toth", mana_cost="{2}{B}{G}",
    type_line="Legendary Creature — Human Shaman", power="3", toughness="4",
    oracle_text="Whenever another creature you control dies, you get an experience counter.\nAt the beginning of your end step, choose target creature card in your graveyard. If that card's mana value is less than or equal to the number of experience counters you have, return it to the battlefield. Otherwise, put it into your hand.")
TOSHIRO = dict(name="Toshiro Umezawa", mana_cost="{1}{B}{B}",
    type_line="Legendary Creature — Human Samurai", keywords=frozenset({"bushido"}), power="2", toughness="2",
    oracle_text="Bushido 1 (Whenever this creature blocks or becomes blocked, it gets +1/+1 until end of turn.)\nWhenever a creature an opponent controls dies, you may cast target instant card from your graveyard. If that spell would be put into a graveyard, exile it instead.")
VISCERA = dict(name="Viscera Seer", mana_cost="{B}", type_line="Creature — Vampire Wizard",
    keywords=frozenset({"scry"}), power="1", toughness="1",
    oracle_text="Sacrifice a creature: Scry 1. (Look at the top card of your library. You may put that card on the bottom.)")
```

Tests:
- `test_meren_wrath_is_death_payoff`: `payoff_kind == "death_payoff"`, `payoff_treasure == 0`
- `test_meren_sac_outlet_is_death_payoff`: Viscera Seer gives `payoff_kind == "death_payoff"`
- `test_meren_farewell_not_payoff`: exile wipe gives `.empty`
- `test_opponent_death_trigger_not_detected`: Toshiro's lens has no `death_payoff`

- [ ] **Step 2: Run the tests and confirm they fail.** Expected: the new tests FAIL.

- [ ] **Step 3: Implement** detection and apply, merged as in Task 2.

- [ ] **Step 4: Run the tests and confirm they pass.** Run `python -m pytest tests/engine/test_commander_lens.py -q`. Expected: all pass.

- [ ] **Step 5: Commit**: `git commit -m "lens: death_payoff for own-creature death triggers"`

---

### Task 4: Roles read the lens

**Files:**
- Modify: `src/mythgauntlet/ratings/redundancy.py`, `src/mythgauntlet/ratings/role_swap.py`, `src/mythgauntlet/mentor/deckview.py`, `src/mythgauntlet/mentor/tools.py:1144`, `src/mythgauntlet/ratings/advisor.py` (where it calls `rank_redundant`)
- Test: `tests/engine/test_commander_lens_roles.py`

**Interfaces:**
- Consumes: `CommanderLens.facts_for`, `CommanderLens.flagged`, `build_lens`.
- Produces:
  - `redundancy.card_roles(ev: EffectVector, facts: LensFacts | None = None) -> dict[str, float]`: when `facts.payoff_treasure > 0`, ramp += `min(payoff_treasure, ONE_SHOT_RAMP_CAP)`.
  - `redundancy.roles_for(card: Card, lens: CommanderLens | None = None) -> dict[str, float]`: the ONE call site shape. Replace every `card_roles(tags.analyze(card))` with it.
  - `role_supply(resolved, lens=None)`, `role_card_counts(resolved, lens=None)`, `score_card(..., lens=None)`, `rank_redundant(..., lens=None)`: a lens-flagged card is `protected`.
  - `role_swap`: cut candidates exclude `lens.flagged(...)`.
  - `deckview.deck_card_rows(resolved, lens=None)`: each row gains `"commander_synergy": {"kind", "reason", "one_sided", "treasure"} | None`.
  - `advise`/`assess_card` build `build_lens(resolved.commanders)` when no lens is passed (no ctx, so no X credit).

- [ ] **Step 1: Write the failing tests** (reuse the Task 1-2 fixtures by importing them from `test_commander_lens`):
- `test_blasphemous_counts_as_ramp_and_wipe_under_smaug`: `roles_for(act, lens)` has `"wipe"` and `ramp == 2.0`
- `test_no_lens_roles_unchanged`: `roles_for(act, None) == card_roles(tags.analyze(act))`
- `test_role_card_counts_identical_for_unmatched_commander`: a resolved deck led by a vanilla `make_card` legend gives the same counts with and without the lens
- `test_flagged_card_is_never_a_redundant_cut`: in a Smaug deck over-supplied on wipes, `rank_redundant(..., lens=lens)` never lists Blasphemous Act ahead of an unflagged wipe, and its score row is `protected`
- `test_deck_card_rows_carry_synergy`: the Blasphemous Act row has `commander_synergy["kind"] == "damage_to_self_payoff"`; a Wrath row under a non-lens commander has `commander_synergy is None`

- [ ] **Step 2: Run the tests and confirm they fail.** Run `python -m pytest tests/engine/test_commander_lens_roles.py -q`.

- [ ] **Step 3: Implement** the signatures above. Thread `lens` through the existing call sites, defaulting to None everywhere so offline callers are unchanged.

- [ ] **Step 4: Run the new tests plus the existing suites they touch.** Run `python -m pytest tests/engine/test_commander_lens_roles.py tests/engine/test_redundancy.py tests/engine/test_role_coverage.py tests/engine/test_advisor.py tests/engine/test_card_impact.py -q`. Expected: all pass.

- [ ] **Step 5: Commit**: `git commit -m "roles: read commander lens facts (ramp credit, protected cuts, row synergy)"`

---

### Task 5: Analysis builds the lens; the Resilience wipe honours survival

**Files:**
- Modify: `src/mythgauntlet/ratings/analysis.py`, `src/mythgauntlet/sim/tier1.py` (`compute_resilience`), `src/mythgauntlet/sim/tier0.py` (`simulate`, `_run_one` ~line 360)
- Test: `tests/engine/test_commander_lens_resilience.py`

**Interfaces:**
- Consumes: `build_lens`, `LensDeckContext`, `CommanderLens.survives_mode`.
- Produces:
  - `DeckAnalysis.lens: CommanderLens | None = None`. `analyze_deck` builds it after `metrics.compute` with `LensDeckContext(tuple(mana_by_turn), report.avg_commander_turn, counter_reserve)`. `mana_by_turn` comes from `_mean_mana_curve` (index 0 = turn 1); `counter_reserve` = min MV over cards with `tags.analyze(c).counterspell`, else 0.
  - `simulate(..., commander_survives_wipe: bool = False)` → `_run_one(..., commander_survives_wipe=False)`.
  - `compute_resilience(..., commander_survives_wipe: bool = False)`. `analyze_deck` passes `lens.survives_mode("destroy")`.
  - In the wiped turn, a surviving on-board commander stays: not returned to zone, no tax. Its own `attack_power`, `board_creatures` slot, engine draw / damage engine and mana source (if it is one) are restored after the board is cleared.

- [ ] **Step 1: Write the failing tests:**
- `test_indestructible_commander_keeps_board_after_wipe`: for a Smaug-led synthetic deck run with `board_wipe_turn=5`, `commander_survives_wipe=True`, every run where `commander_turn < 5` has `board_power_by_turn[4] >= 8`; with the flag False that turn's board power is `< 8` whenever Smaug was the only creature
- `test_flag_off_is_byte_identical`: `simulate(cards, smaug, cfg, board_wipe_turn=5)` equals the same call with `commander_survives_wipe=False` (RunStats lists equal)
- `test_analysis_carries_lens`: `analyze_deck(resolved, small_cfg, empty_store).lens.kinds` contains `"survives_wipe"` for a Smaug deck and is `()` for a vanilla legend

- [ ] **Step 2: Run the tests and confirm they fail.**

- [ ] **Step 3: Implement.** In `_run_one`, keep a running record of the commander's own contributions when `apply_effects(commander)` runs, so they can be re-added after the wipe clears the board.

- [ ] **Step 4: Run the new tests plus the analysis and sim suites.** Run `python -m pytest tests/engine/test_commander_lens_resilience.py tests/engine/test_analysis.py tests/engine/test_game.py -q`. Expected: all pass.

- [ ] **Step 5: Commit**: `git commit -m "resilience: indestructible commander survives the injected destroy wipe"`

---

### Task 6: Mentor tools, diagnose, gate

**Files:**
- Modify: `src/mythgauntlet/mentor/tools.py` (`tool_list_deck_cards`, `tool_get_deck_stats`, `_diagnose_facts`, `tool_suggest_role_swap`), `src/mythgauntlet/mentor/diagnose.py:402`, `src/mythgauntlet/mentor/gate.py` (`ClaimBudget`, `check`), `src/mythgauntlet/mentor/verdicts.py`, `tests/engine/data/mentor_phrasings.json`
- Test: `tests/engine/test_mentor_commander_lens.py`

**Interfaces:**
- Consumes: `DeckAnalysis.lens`, `deck_card_rows(resolved, lens)`, `role_card_counts(resolved, lens)`.
- Produces:
  - `tools._lens_for(ctx) -> CommanderLens | None` (from `_analysis_for(ctx).lens`).
  - `list_deck_cards` rows carry `commander_synergy`; data gains `"commander_lens_kinds": list[str]`.
  - `_diagnose_facts` adds `"commander_folds_to_wipe": not lens.survives_mode("destroy")`. The Lever at `diagnose.py:402` gets `requires="commander_folds_to_wipe"`.
  - `ClaimBudget.synergy_cards: frozenset[str]`, filled in `from_tool_results` from any result row with a non-null `commander_synergy`.
  - `verdicts.commander_synergy_claims(body: str, commander_names) -> list[str]`: card names a sentence claims synergise with the commander. Phrases (ASCII, after `normalize_apostrophes`) are "synerg* with (your commander|<commander name>)", "triggers (your commander|<commander name>)", "works (well )?with (your commander|<commander name>)", "combos with (your commander|<commander name>)".
  - Gate check 16 in `gate.check`: for each claimed card not in `budget.synergy_cards`, add the reason `f"claims {name!r} synergises with the commander; no lens fact backs it"`.

- [ ] **Step 1: Write the failing tests:**
- `test_list_cards_shows_synergy`: on a Smaug MentorContext (follow `test_mentor_tools.py`'s context builder), `tool_list_deck_cards` has a Blasphemous Act row with `commander_synergy` and `"damage_to_self_payoff" in data["commander_lens_kinds"]`
- `test_resilience_wipe_lever_suppressed_for_indestructible`: `tool_diagnose_axis(ctx, "resilience")` lever texts do not include "A board wipe sets the deck back a lot"; for a vanilla-legend deck they do
- `test_gate_rejects_unbacked_synergy_claim`: a budget without Wrath in `synergy_cards`, body "Wrath of God has great synergy with your commander." gives a reason containing "no lens fact"
- `test_gate_accepts_backed_synergy_claim`: the same body with Blasphemous Act in `synergy_cards` gives no check-16 reason
- add phrasing-corpus items (positives and hard negatives such as "works with your mana base") to `mentor_phrasings.json`; the existing `test_mentor_phrasing_corpus.py` must pass

- [ ] **Step 2: Run the tests and confirm they fail.**

- [ ] **Step 3: Implement** the interfaces above.

- [ ] **Step 4: Run the full mentor suites.** Run `python -m pytest tests/engine -q -k "mentor or commander_lens"`. Expected: all pass.

- [ ] **Step 5: Commit**: `git commit -m "mentor: commander lens facts in tools, diagnose and gate check 16"`

---

### Task 7: Deck Breakdown synergy mark

**Files:**
- Modify: `frontend/src/components/DeckBreakdownPanel.jsx`, `frontend/src/utils/deckGrouping.js` (only if role grouping needs the field)
- Test: `frontend/src/utils/deckBreakdown.test.js` (vitest)

**Interfaces:**
- Consumes: breakdown rows' `commander_synergy` (may be absent: stale cache).
- Produces: `synergyRows(rows) -> Array<{name, reason, oneSided, treasure}>` exported from a small pure helper in `frontend/src/utils/deckBreakdown.js`. The panel renders a "Commander synergy" list when the result is non-empty.

- [ ] **Step 1: Write the failing vitest:**
- `synergyRows([{name:"Blasphemous Act", commander_synergy:{kind:"damage_to_self_payoff", reason:"r", one_sided:true, treasure:13}}])` gives one row with `treasure === 13`
- `synergyRows([{name:"Sol Ring"}])` gives `[]` (stale cache, missing field: Review Focus 5)

- [ ] **Step 2: Run and confirm it fails.** Run `cd frontend && npx vitest run src/utils/deckBreakdown.test.js`.

- [ ] **Step 3: Implement** the helper and the panel section.

- [ ] **Step 4: Run vitest, then build.** Run `npx vitest run && npm run build`. Expected: pass, and the build succeeds.

- [ ] **Step 5: Commit**: `git commit -m "breakdown: show commander synergy cards"`

---

### Task 8: Corpus validation + live check, then push

**Files:**
- Create: `scripts/commander_lens_sweep.py`
- Modify: `CLAUDE.md` (one bullet under the MythGauntlet engine notes), `docs/superpowers/specs/2026-10-19-commander-lens-design.md` (status line)

**Interfaces:**
- Consumes: `build_lens`, `role_card_counts`, `deck_card_rows`, `data/edhrec.py` cached pages.
- Produces: `python scripts/commander_lens_sweep.py [--edhrec 30]`, which prints:
  1. **No-change check:** decks whose commander has no kinds, with `role_card_counts` with lens == without. Exit 1 on any difference.
  2. **Moved decks:** each deck whose counts changed, and every flagged card with its reason (for hand review).
  3. **EDHREC coverage:** for up to N lens-covered commanders with a cached page, the share of high-synergy cards (lift > 0.3) the lens flags. Report only.

- [ ] **Step 1: Write the script and run it.** Run `PYTHONPATH=src python scripts/commander_lens_sweep.py --edhrec 30`. Expected: the no-change check passes (exit 0).
- [ ] **Step 2: Hand-review every flagged card in the moved-decks list against its oracle text.** Fix any false positive by class: add a failing test to the owning task's test file, then fix the code. Record the counts.
- [ ] **Step 3: Live mentor check.** Start the engine (`manage.bat` option, or `PYTHONPATH=src python -m mythgauntlet serve`) and ask the mentor, on a Smaug deck containing Blasphemous Act, "should I cut Blasphemous Act?". Expected: the answer is no, and it cites the commander synergy. Paste the reply into the commit message body. Tear down GPU services afterwards (kill :8010 / :8020 if this session started them).
- [ ] **Step 4: Full suite.** Run `python -m pytest tests -q`. Expected: all pass.
- [ ] **Step 5: Update CLAUDE.md and the spec status** with the measured figures (moved decks, flagged cards, EDHREC coverage share).
- [ ] **Step 6: Commit and push**: `git commit -m "lens: corpus sweep + docs"` then `git push origin main`.
