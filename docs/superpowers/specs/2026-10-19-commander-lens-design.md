# Commander lens: commander-aware card value

**Date:** 2026-10-19
**Status:** implemented 2026-10-19 (branch `feat/commander-lens`). Corpus sweep
(`scripts/commander_lens_sweep.py`, 1,106 corpus decks, 1 unresolved): all 1,074 decks with
no lens kind are identical with and without the lens on the swept surfaces (role card counts,
role_supply strengths, cut-protected set, rank_redundant top 10, deck_card_rows,
survives_mode) -- the sim-reading surfaces (Resilience, LensDeckContext X credit) are covered
by tests, not by the sweep. 31 lens-covered decks (18 commanders); 21 moved: 2 in role counts
and supply (Smaug: Ramp +2 / +1 cards), 19 in the cut-protected set only. 75 distinct flagged
(card, kind) pairs / 149 deck-card instances after hand review fixed 6 false-positive classes
(incl. colour exclusions, Strafe). EDHREC high-synergy (lift > 0.3) coverage 16/125 (12.8%)
over 5 cached single-commander pages (Smaug 13/42 = 31%, Meren 3/27 = 11%). Live mentor check
("should I cut Blasphemous Act?") passes after the deterministic lens prefetch: the reply
keeps the card and cites Smaug surviving the 13 damage for Treasure.
**Scope:** MythForge strength metrics (`src/mythgauntlet/ratings/`), Deck Mentor
(`src/mythgauntlet/mentor/`), one guarded change in `src/mythgauntlet/sim/tier0.py`.

## Problem

Card value is computed identically regardless of commander. The commander currently feeds
only cast timing (`ratings/metrics.py`), colour identity (`ratings/axes.py`) and salt
(`ratings/table_feel.py`). Three concrete defects follow, shown by
**Smaug the Impenetrable** ("Flying, indestructible, haste / Whenever Smaug is dealt
noncombat damage, create that many Treasure tokens"):

1. **Own wipes read as symmetric.** `EffectVector.board_wipe` is a bare bool. Blasphemous Act
   under Smaug is a one-sided wipe that also makes 13 Treasures; the metrics and mentor see
   a reset that costs the pilot their board. Indestructible also survives destroy wipes.
2. **The Resilience test kills every commander.** `sim/tier0.py` (~line 360) clears the board
   and returns the commander to the command zone on the injected wipe, regardless of
   indestructible.
3. **No synergy layer.** Nothing asks "does this card trigger my commander?", so neither the
   role counts nor the mentor can see that a card is a payoff in *this* deck.

Per the standing bar (*Magic is precise, a near-miss is a defect*): an honest under-count is
preferred to a confident fabrication.

## Measured prevalence (3,305 compiled legendary creatures, 2026-10-19)

| Property | Commanders | Changes wipe semantics |
|---|---|---|
| indestructible (printed) | 124 | yes: survives destroy + damage wipes |
| `death` / `creature_dies` trigger | ~196 | yes: own wipe becomes a payoff |
| `dealt_damage` trigger | 22 | yes: damage wipe becomes ramp/value |
| `cast_spell` trigger | 250 | no (deferred, next pass) |

Hexproof (66) and ward (95) are irrelevant to wipes and out of scope.

## Approach

A **fixed list of interaction types**, each a small unit with a precise matcher, assembled
into a per-deck `CommanderLens`. Alternatives rejected: an LLM-drafted per-commander profile
(fabrication risk; needs a per-claim gate, at which point it is this design with an LLM front
end), and EDHREC synergy scores as an input (says *which*, not *why*; cannot express
"one-sided"; mixes synergy with popularity). EDHREC is used only as a coverage test set.

## Design

### Module: `semantics/commander_lens.py`

Lives in `semantics/`, not `ratings/`: `sim/tier1` must read it and `sim/` never imports
`ratings/`.

```
build_lens(commanders: Sequence[Card], ctx: LensDeckContext | None = None) -> CommanderLens
lens.facts_for(card: Card) -> LensFacts            # empty LensFacts when no kind applies
```

Each `LensKind` implements:

- `detect(commander) -> bool`, from printed `keywords` and oracle text only. The compiled
  model is NOT read: it is too coarse (Smaug's compiles to `dealt_damage` with neither the
  subject nor "noncombat"), and since oracle confirmation is mandatory it adds nothing.
- `apply(card, deck_ctx) -> LensFacts`: returns *additional* facts. It never mutates the
  card's `EffectVector`; base semantics stay commander-agnostic.

`LensFacts` (frozen dataclass, all defaults neutral):

- `wipe_one_sided: bool`: the pilot's own wipe whose mode and object filter leave the
  commander standing.
- `payoff_kind: str | None`: name of the interaction type that makes this card a payoff.
- `payoff_treasure: int`: Treasures the payoff yields at the reference turn.
- `reason: str`: short human-readable explanation, for the mentor and Deck Breakdown.

A commander with no matching type gets an empty lens: every output stays byte-identical.

### First-pass interaction types

1. **`survives_wipe`**: commander's printed `keywords` contain `indestructible`. Survives
   wipe modes `destroy` and `damage` (from `semantics.tags.interaction_modes`); does not
   survive `exile`, `bounce`, `edict`, `minus`, `static_minus`. Marks the pilot's own wipes
   of a surviving mode `wipe_one_sided`.
2. **`damage_to_self_payoff`**: commander's oracle text has a "whenever <self> is dealt
   [noncombat] damage" trigger, confirmed by text (self-name or "this creature"). Treasure
   credit applies only to MASS damage that hits the commander ("deals N damage to each
   creature"). Targeted damage and repeatable pingers that *could* be aimed at the commander
   get the `payoff_kind` label with no credit, because a target choice is a decision this
   layer does not make. A noncombat-only trigger ignores only combat damage
   (CR 120.2a: attacking/blocking creatures in the combat damage step). Fight and every spell
   or ability's damage IS noncombat (CR 120.2b), so it counts. Fight is a target choice, so
   label only.
3. **`death_payoff`**: commander has a death trigger whose counted subject is the pilot's
   own creatures ("a creature you control", "another creature"), confirmed by text. Own wipes
   and sacrifice outlets get `payoff_kind="death_payoff"`. No Treasure or number credit in
   this pass; label only.

Deferred to a second pass, using the same structure: `cast_spell` payoffs by spell type,
landfall, "another creature enters", token/sacrifice engines.

### Precision rules (all matchers)

- **Object filter is checked against the commander.** Earthquake and Hurricane hit "each
  creature without flying", so they do not touch Smaug: no hit, no credit. Rolling
  Earthquake (without horsemanship) does hit.
- **Fixed damage:** use the printed number (Blasphemous Act = 13, Star of Extinction = 20).
- **X damage:** X = floor(`avg_mana_available_by_turn[t]`) − the spell's fixed mana cost −
  counter reserve, clamped at 0, where
  - `t = ceil(avg_commander_turn) + 1`: the payoff needs the commander on the
    battlefield. If the commander is never cast in the sim, there is no credit.
  - counter reserve = the lowest mana value among the deck's counterspells (`counterspell`
    or `InteractionModes.counter`); 0 if the deck runs none.
  - if `t` is beyond the simulated horizon, use the last simulated turn.
- **Unparseable amount**: no credit (`payoff_treasure = 0`), but the label is kept if
  the hit itself is certain.

### Consumers

| Consumer | Change |
|---|---|
| `ratings/redundancy.card_roles` | `payoff_treasure > 0` adds the card to the Ramp role (same treatment as `treasure_ramp`). A `wipe_one_sided` wipe stays in the Wipe role, tagged one-sided. |
| Deck Breakdown (`mentor/deckview.py`) | Shows lens-flagged cards with a "commander synergy" mark and `reason`. |
| Interaction axis (`ratings/axes.py`) | No weighting change. One-sided wipes count as wipes, as today. |
| Resilience (`sim/tier0.py`) | The injected opponent wipe is modelled as mode `destroy`. If the lens has `survives_wipe`, the commander stays on the battlefield and keeps its power and any engine it provides. Only wiped runs are affected. Death-payoff value inside the wiped run is deferred. |
| Mentor tools (`mentor/tools.py`) | Expose lens facts per card and the lens's kinds. |
| Mentor diagnose (`mentor/diagnose.py`) | The "a board wipe sets the deck back a lot" Resilience lever is suppressed when the lens has `survives_wipe`. |
| Swap advice (`ratings/role_swap.py`, `ratings/swap_brief.py`) | Never proposes cutting a lens-flagged card without naming the synergy lost. |
| Mentor gate (`mentor/gate.py`) | A new check rejects any claim of commander synergy for a card without a lens fact behind it. |

Partner and background pairs: the lens is built from each commander and the kinds are
unioned. The Resilience change applies only to the lead commander, matching the sim's
existing single-commander model.

## Testing

1. **Hand-checked rules cases** (unit tests). Expected values are asserted from oracle text
   read at test time, never typed from memory:
   - Smaug + Blasphemous Act: one-sided, 13 Treasures.
   - Smaug + Earthquake: no hit (flying), no credit.
   - Smaug + Rolling Earthquake: X from the mana budget, with and without a counter reserve.
   - Smaug + Wrath of God: survives, no payoff.
   - Smaug + Farewell (exile): not marked one-sided.
   - Smaug + Toxic Deluge (−X/−X): not marked one-sided. Indestructible does not stop
     −X/−X; survival depends on X versus toughness, which the lens does not claim.
   - Smaug + Lightning Bolt: `damage_to_self_payoff` label, `payoff_treasure == 0`.
   - One `death_payoff` commander whose trigger counts the pilot's creatures: wipe labelled.
   - Negative control: a commander whose damage trigger names a *different* subject must
     not get `damage_to_self_payoff`.
2. **No-change check:** for every corpus deck whose commander matches no interaction type,
   all metrics must be identical before and after.
3. **Corpus sweep:** list every deck whose metrics moved. In the first sweep, hand-check
   every lens-flagged card for false positives, as was done for the storm and overrun
   finishers.
4. **EDHREC coverage check:** for about 30 lens-covered commanders, record what share of
   their high-synergy EDHREC cards the lens flags. A guide for which type to add next;
   never a gate, never a score input.
5. **Mentor regression:** a stored transcript where a Smaug deck asks "should I cut
   Blasphemous Act?" must get a no that cites the lens fact.

## Out of scope (this pass)

- Simulator playing the interaction (casting the wipe, spending the Treasures). Speed,
  Clock and bracket move only through the inputs above.
- Interaction-axis re-weighting for one-sided wipes.
- `cast_spell`, landfall, ETB-others, token and sacrifice interaction types.
- LLM-drafted lens entries.
