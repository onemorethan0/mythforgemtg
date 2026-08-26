# Shortfall map & plan (2026-08-18)

Every number here was **measured this session**, offline where possible, against
`corpus/decks` (483 parseable decks, 391 unique commanders) and the live modules. Nothing in
this file is an estimate unless it says so.

Priority is judged against the project's actual goal — **casual bracket 1–3 gauging: "is this
deck fun and on-level for my pod"** — not cEDH optimisation. A shortfall that misleads a
casual player outranks a precision gap at the top of the ladder.

Companion docs: [`HANDOFF.md`](HANDOFF.md) (what changed and what it measured),
[`ENGINE_DATA.md`](ENGINE_DATA.md) (what ships vs what trains).

---

## The map

> **S12 (DONE 2026-08-26 — see the SHIPPED entry below): the redundancy score was silent on
> 9% of decks, and said so to nobody.**
> `rank_redundant` scores `oversupply / (1 + within_role)`. When a deck over-supplies NOTHING
> every card scores exactly 0.0, and the ordering falls entirely through to the tiebreak —
> **least-played first**, which is the popularity rule the module exists to replace. Roleless
> cards are still protected and sort last, so it is not *pure* popularity; it is "the
> least-played card that carries a role". Measured over 499 corpus decks: **45 (9.0%)**
> over-supply no role at all, **40 (8.0%)** have all six pool slots at score 0.0, and
> **426/2966 (14.4%)** of all cut slots corpus-wide are chosen by that tiebreak. The corpus
> Shelob deck is one: every role sits at or under target, so it offers *Gloomwidow's Feast*
> and *Eaten by Spiders*. **This is a compounding regression from two changes that each
> measured well on their own terms** — raising a target is exactly what makes "nothing is
> over-supplied" more likely:
>
>     targets                                 decks over-supplying nothing
>     original builder-slot                            19  (3.8%)
>     p60 population        (2026-08-14)               38  (7.6%)
>     + archetype           (2026-08-19)               45  (9.0%)
>
> The module has no defined behaviour here and returns `k` candidates as confidently as ever.
>
> **CORRECTION 2026-08-25: the "honest half" is more complete than this entry claimed.**
> Verified live: `redundancy_backed` (`score.oversupply > 0.0`) is computed once in
> `swap_brief.build_swap_brief` and reaches BOTH real user-facing consumers, not one —
> `card_impact._cut_sentence` (single-card assessment) AND, via `SwapSuggestion.brief`,
> Forge's `swap_narrative.check()` gate (the `/advise` swap-suggestion narrative), which
> explicitly forbids the words redundant/redundancy/over-supplied/oversupplied/over-served/
> surplus/excess/duplicated/"too many" whenever the flag is False (`swap_narrative.py:394,
> 570, 597`, tested). Neither consumer can present the tiebreak's output as a measured
> redundancy finding — confirmed by running `test_swap_narrative.py`'s redundancy-gate case.
> **What remains open is narrower than "tell the caller" — it's purely the ordering-in-the-
> degenerate-case doctrine question below**, which two independent attempts already failed to
> answer and which a third attempt should not be guessed at without a genuinely new idea. Note
> the project has already established that **the sim's axis delta cannot see this class of
> defect**, so a new tiebreak cannot be settled by `advisor_bench` and needs an argument from
> doctrine instead.
>
> **THE OBVIOUS FIX WAS PROTOTYPED AND IT IS WRONG — measured 2026-08-20, not shipped.** The
> natural repair is to stop throwing the information away: `score_card` computes
> `over = max(0.0, supply - target)`, and that clamp is what flattens every under-target role
> to the same value. Ranking instead by *unclamped* headroom — cut from the role CLOSEST to
> over-supplied — is the continuous extension of the rule the module already follows, and it
> is surgical (it can only reorder cards scoring exactly 0.0; every positive-score slot is
> untouched). Applied to the corpus it moves 38 of the 45 degenerate decks and cuts their
> overlap with the popularity pool from 0.71 to 0.42 of 6. **It still makes the canonical
> case worse**, for two reasons that are worth writing down because they constrain any future
> attempt:
>
> 1. **Headroom is itself degenerate.** Targets are integers and role supply is frequently
>    integral, so roles land *exactly* at target far more often than not. On the Shelob deck
>    ramp, draw, removal and wipe all sit at headroom **0.0** — four-way tie, nothing
>    discriminated, and the order falls through to the next key anyway.
> 2. **`within_role` INVERTS as a cuttability proxy when nothing is over-supplied.** The
>    module's doctrine is that within-role strength LOWERS the cut score — once ramp is
>    over-served you cut the worst ramp spell. But the module also documents that
>    `within_role` measures *dedication*, not quality: a low score means a hybrid doing other
>    work too. When the role is over-served, "weak contributor" means redundant filler. When
>    the role is merely AT target, "weak contributor" means the card is mostly doing
>    something else — which is usually the deck's theme. So the doctrine-consistent tiebreak
>    promoted *Skyfisher Spider* and *Shelob, Dread Weaver* (both `within_role` 1.0, both
>    spiders in the spider deck) ahead of *Eaten by Spiders*, and re-armed the exact bug the
>    redundancy pool exists to prevent.
>
> Inverting the tiebreak in the degenerate case is not the answer either: it would make the
> ordering **discontinuous at zero**, flipping a card from most-protected to first-cut as
> supply crosses its target by 0.1. The likely real answer is that the caller must be told
> there is no redundancy signal and change what it does, rather than the module inventing an
> order — which is what `card_impact._cut_sentence` now does for one consumer.
>
> **SHIPPED 2026-08-26: a THIRD attempt, from a data source neither prior one touched, and
> it measures well.** Both rejected attempts stayed inside the role/oversupply framework
> (unclamped headroom, inverted tiebreak); this one leaves it entirely and uses **EDHREC
> lift/synergy** — a commander-relative signed fraction already built for `edhrec_lift.py`'s
> role-window ordering — as the degenerate-case tiebreak: negative lift (a generic staple,
> played more OUTSIDE this commander's decks than in them) is offered ahead of positive lift
> (concentrates on decks with this commander, i.e. the deck's own plan), and a card absent
> from the map (EDHREC's page covers only ~250 cards) is treated as NEUTRAL, never as a
> confirmed staple — the same "unmeasured ≠ rejected" judgment `edhrec_lift.py` already makes
> in the opposite direction. `redundancy.rank_redundant`/`advisor.advise`/
> `card_impact.assess_card` all take an optional `lift: dict[str, float] | None` (a plain
> `{normalized card name: synergy}` map, exactly the `themes`-as-plain-strings contract
> `targets_for` already uses — the module stays pure/offline and does not fetch EDHREC
> itself); omitting it reproduces the prior ordering byte-for-byte, which every existing
> caller does until wired. **Wired end to end**: the engine's `/advise` and `/card-impact`
> routes accept `lift`, and Forge's `_gauntlet_advise`/`_gauntlet_card_impact` build it from
> `edhrec_lift.lift_map(commander_name)` (fails soft to `{}`, same cache, same kill switch)
> and pass it through. Keys are normalized (front face, casefolded — `_normalize_lift_name` in
> both `ratings/redundancy.py` and `data/edhrec.py`, matching Forge's `edhrec_lift.normalize_name`)
> because the two processes disagree on display casing and a naive exact-string match would
> have looked wired while silently matching nothing.
>
> **Measured, not just reasoned through.** Of the 45 degenerate corpus decks, only 14 had a
> cached EDHREC page for their commander (coverage is honestly partial, same 16–76% figure
> `lift_stats.py` already documents) — of those 14, the cut pool changed on **10**, and on the
> 6 where BOTH the old and new top pick were independently measured, the new pick's lift was
> strictly LOWER (more generic-staple) every time — **0 regressions in the numerically
> comparable subset**. The other 4 changed cases pair an unmeasured old pick against a
> measured-negative new pick; card identity confirms the same direction (a Boros/Rakdos/Dimir
> Signet, Sol Ring, or Swords to Plowshares replacing a tribal legendary or a build-around
> piece). The Shelob canary — the deck this whole entry was written about — moves from
> offering *Gloomwidow's Feast* to offering *Talisman of Resilience*; the Flubs deck moves
> from offering *Song of Creation* (lift +0.70, a genuine combo piece) to a *Sol Ring* (lift
> −0.19). **Verified live end to end**, not just in the pure function: a real `/card-impact`
> call against the corpus Shelob deck, with vs without `lift`, flips two of three tested
> candidates' VERDICTS (`negative` → `positive`) purely because the fair-pairing cut changes
> from the deck's own theme card to a generic mana rock — the exact "recommended cut changes
> on 95%, verdict on 30%" sensitivity `card_impact` already documents for pool quality in
> general.
>
> **What is still honestly open:** the other 19% of degenerate decks with no cached EDHREC
> page get no benefit from this (falls back to the pre-existing tiebreak, not a regression —
> just unmeasured), and there is no live-collection-based validation of the 4 qualitative
> (unmeasured-old-pick) cases beyond reading the card identities. Tests: 7 new cases in
> `tests/engine/test_redundancy.py` (byte-identical-when-omitted, the degenerate-tie
> precondition, the staple-over-signature preference, unmeasured-is-neutral, and the
> cross-process name-normalization contract, including a DFC front-face case).

> **S13 (new, open): a fixed per-card role strength makes the target granular.** `card_roles`
> returns a FIXED 3.0 for `counterspell` and `wipe`, so supply moves in whole-card steps of
> 3.0 and the target can only ever sit on a card boundary. `counterspell`'s population target
> of 3 therefore means **"one card"**, and any deck running two counterspells is scored 3.0
> over — which then outranks a role that is genuinely but modestly over-served. Corpus deck
> `archidekt-13708248` is a **landfall** deck holding two counterspells: its draw is 0.5 over
> and its counterspell 3.0 over, so it is offered *Flusterstorm*. S10's archetype table fixes
> this only for decks whose archetype is in the table; the granularity is the general case.
>
> **VERIFIED 2026-08-25, reproduced exactly, not stale.** Re-ran `archidekt-13708248` against
> the real `targets_for(["landfall"])` table: ramp supply 18 against the landfall-adjusted
> target 23 (S10) correctly clears (no longer over-supplied), leaving counterspell (supply 6.0,
> 2 real counterspells at the fixed 3.0-per-card strength, target 3, so 3.0 over) as the single
> most over-supplied role — `rank_redundant` offers **Flusterstorm** first, exactly as
> described. Flusterstorm is a narrow storm/combo answer, precisely the "silver bullet the
> pilot chose on purpose" shape S11 already named as the wrong thing to cut.
>
> **A normalization fix was considered and does not obviously resolve it — checked by
> reasoning first, then actually MEASURED 2026-08-25, and the reasoning holds up.** Dividing
> oversupply by the role's own per-card strength (comparing "cards' worth over target" instead
> of raw points) would turn counterspell's 3.0-over into 1.0 "extra card equivalent". Measured
> the real per-card strength distribution across the full 34,179-card pool rather than
> assuming it: median **ramp 1.0, draw 1.5, removal 1.0, wipe 3.0, counterspell 3.0, tutor
> 2.0, finisher 2.0**. Re-running `archidekt-13708248`'s exact canary through this: draw's
> 0.5-point oversupply normalizes to **0.5 / 1.5 = 0.33** card-equivalents, counterspell's
> stays **3.0 / 3.0 = 1.0** — counterspell still wins, Flusterstorm is still offered first.
> **The normalization does not change the outcome on the case it was proposed to fix.**
>
> Worth naming why, since it reframes what S13 actually is: 2 counterspells against a
> population median of ~0 genuinely IS an above-average count for a non-spellslinger deck —
> that read is not the bug. The real complaint is Flusterstorm being a poor pick *within* an
> honestly over-supplied role (a silver bullet, not filler) — which is the `_efficiency`
> within-role ordering question this module already has a mechanism for (mana-value-based
> tiebreak), not the cross-role granularity question S13 was framed as. **Still not fixed** —
> the project's own S17 lesson this same session (a plausible-looking fix reverted after it
> broke Thassa's Oracle) is why an unmeasured reordering of `_efficiency`'s own weighting isn't
> attempted here either without the same sweep-and-validate rigor S10's archetype table used.
>
> **LARGELY MITIGATED, FOUND RATHER THAN BUILT — 2026-08-26, the same day S12's lift tiebreak
> shipped.** `_lift_key` sits in `rank_redundant`'s sort key for *every* tie, not only the
> `oversupply == 0.0` case S12 was written for — and the S13 canary IS a tie: two same-cost
> counterspells scoring identically once the fixed per-card strength clears the role's
> target. Re-running the exact canary with `lift = edhrec_lift.lift_map("Omo, Queen of
> Vesuva")` (the same call the live `/advise` route already makes) flips the pick: An Offer
> You Can't Refuse (measured on Omo's own page at lift -0.07, a confirmed generic staple)
> is offered ahead of Flusterstorm (absent from that page, so neutral). Nobody had re-checked
> S13 against the wiring S12 landed for a different reason.
>
> **Swept, not just re-run once.** Over the 255 corpus decks whose commander has a cached
> EDHREC page: the top redundant pick (population `ROLE_TARGETS`, no archetype narrowing)
> changes for **66** when `lift` is supplied. Of the 40 where BOTH the old and new pick are
> independently measured, the new pick's lift is lower — more generic-staple — **every
> time: 0 regressions**, the same falsifiable shape S12's own validation used. Script:
> scratchpad `s13_sweep.py` (not committed; offline, cache-only, re-runnable).
>
> **Not a fix to the architecture, and say so plainly.** `card_roles` still returns a flat
> 3.0 for counterspell/wipe — the granularity S13 named is still real. What changed is that
> the tiebreak that used to reach for least-played (surfacing the narrow, thematic pick) now
> more often reaches for EDHREC lift instead (surfacing the generic one), *when the commander
> has a cached page*. Coverage is the same honest partial figure documented elsewhere
> (16–76%, `lift_stats.py`) — a deck whose commander has no cached page gets none of this,
> and still falls through to the old least-played rule. Pinned by
> `test_lift_resolves_a_tie_in_a_genuinely_over_supplied_role_too` in
> `tests/engine/test_redundancy.py` (a synthetic case, not a live-data one, so it can't rot
> if the cache changes).
>
> **Effort downgraded to S** because there was nothing to build — this is a measurement that
> the fix already shipped, one row up, for an unrelated reason. What remains genuinely open
> is the `_efficiency` reordering question named above (should a narrow-but-cheap card like
> Flusterstorm earn LESS within-role credit than a generic-but-cheap one, for commanders
> with no EDHREC page at all) — that still needs S10-grade sweep-and-validate rigor and has
> not been attempted.

| # | Shortfall | Measured | Casual impact | Effort |
|---|---|---|---|---|
| S1 | Commander themes undetected | corpus **64/391 (16.4%)** ↓80 · all legends **946/3790 (25.0%)** ↓963 | **High** | part done |
| S2 | ~~Partner decks cannot be BUILT~~ | **fully fixed + verified** 2026-08-25 — analysis/report path AND the physical 98+2 deck (S20) | **Done** | — |
| S3 | ~~Population-relative labels~~ | **audited, 5 of 5** | **Done** | — |
| S4 | Off-meta read too sparse to judge | **12.6%** no verdict · band shipped | part done | M |
| S5 | ~~Dead entries in the theme taxonomy~~ | **3 of 3 cleared** | **Done** | — |
| S6 | ~~Engine card coverage~~ | **91.5%** pool · 100% top-100 · quarantine 956→443 | **Done** | — |
| S7 | Advisor seed variance | **quantified**: ~60% rel sd, needs ~16× runs | **Done** (bounded) | — |
| S8 | ~~Errors via native `alert()`~~ | **already fixed** — entry was stale | **Done** | — |
| **S9** | ~~`voltron_combat` over-claims~~ | **50% → 89% accuracy** · 23.2% → 15.4% of legends | **Done** | — |
| **S10** | ~~`ROLE_TARGETS` is archetype-blind~~ | own-plan cut slots **64.0% → 33.8%** · pool changes on 52/106 | **Done** | — |
| **S11** | ~~`card_impact` cuts by popularity~~ | recommended cut changes **95%** · verdict **30%** | **Done** | — |
| **S12** | ~~Redundancy score silent on 9% of decks~~ | disclosure verified · **3rd-attempt lift tiebreak SHIPPED + wired end-to-end** 2026-08-26 — 10/14 measured decks changed, 0 regressions, live verdict flip confirmed | **Done** | — |
| S13 | Fixed role strength makes targets granular | **largely mitigated by S12's lift wiring, found 2026-08-26** — 0 regressions on 40 comparable cases, but coverage-gated | Medium | S (found already shipped) |
| **S14** | ~~Swap reasons are template fragments~~ | gated narrative shipped · 14b **93.2%** yield / **71.9%** gate | **Done** | — |
| **S15** | ~~`bracket.py` duplicated + unguarded Game Changers/MLD gate~~ | live field confirmed on every search result · 1 name-match bug found · 10 new tests | **Done** | — |
| **S16** | ~~if/otherwise pairs double-credited~~ · condition-check gap partly remains | **24 cards** double-credited (Approach of the 2nd Sun = free win) · **15.78%** of store has a condition | **Done** (otherwise-fix) / open (general case) | S / M |
| S17 | Combo determinism marker vocabulary | +1 real verb widened, 1 attempted widening reverted (false-positived Thassa's Oracle) | **Done** (this pass) | — |
| **S18** | ~~No legend rule / commander-damage modeling in sim~~ | **commander damage fixed + verified** (golden master + 10,240 real games) · legend rule found not applicable (no clone effects modeled) | **Done** | — |
| **S19** | ~~`counter target spell` ignores "can't be countered"~~ | **23 real cards audited, 0 false positives** — non-issue | **Done** | — |
| **S20** | ~~Partner-commander build is 99+1, not 98+2~~ | **fixed + verified** 2026-08-25 — `partner_count` param, live on 2 real pairs | **Done** | — |
| **S21** | ~~Fast go-off engine capped at Bracket 3 regardless of speed~~ | **fixed + verified** 2026-08-26 — real Prismari deck B3→B4, 0 corpus regressions (proof + rerun) | **Done** | — |

---

## S1 — 16.4% of commanders detect no theme *(was 20.5%; substantially landed)*

**Measured.** **64** of 391 unique corpus commanders return `[]` from
`commander_analysis._detect_themes` — down from **80 (20.5% → 16.4%)** across three passes.
Their ~20 theme slots fall through to generic goodstuff, so the builder is blind to the deck's
whole point. Deck-context themes (`deck_themes`) rescue **34 of the 59** that appear as a deck
lead (58%), leaving **42% with no archetype from either source**.

**On the user's own pod, 3 of 7 commanders detected nothing; now 1 does.** Witherbloom → 
`spellslinger`, Vorel of the Hull Clade → `counters`. Only Avatar Aang remains, and honestly so:
its text is "whenever you waterbend, earthbend, firebend, or airbend" — a brand-new set mechanic
with no entry anywhere in the taxonomy, which is a NEW-archetype case, not a pattern gap.

### Landed 2026-08-18

**A card's own NAME was being read as a payoff.** `THEME_PATTERNS` matches by SUBSTRING against
oracle text, and Magic prints a card's name inside its own rules text — so **39 legendary-creature
tribal detections fired on the name alone**, every one inspected wrong. It was worse than a name
collision: *Michelangelo* registered as **Angel** tribal and *Desdemona* as **Demon** tribal,
alongside The Unknown Wizard, Winter Soldier, Green Goblin, Questing Beast and five Skanos
printings. Each false tribal spends a commander's ~20 theme slots on a tribe with no payoff —
the same defect `_detect_themes` already refuses the TYPE LINE to prevent.
`_oracle_without_self_name` strips both the full and pre-comma name per face; 7 cases plus 3
must-survive payoffs are pinned in `tests/test_theme_taxonomy.py`.

**Eleven patterns widened across seven themes**, every one scored for rescues *and* pool
footprint before landing, and every candidate adjudicated by hand against oracle text:

| theme | added | why it was missed |
|---|---|---|
| `spellslinger` | `instant and sorcery spells you cast`, `prowess` | cost reduction and prowess ARE the payoff (Baral, Narset, Thor) |
| `artifacts` | `artifacts you control`, `artifact creatures you control`, `an artifact card`, `artifact creature card`, `artifact cards` | only the singular "artifact you control" existed (Alibou, Tony Stark, Szarekh, Tannuk) |
| `graveyard` | `in all graveyards`, `each player mills` | graveyards as a shared resource, and deliberate self-mill (Coram) |
| `enchantress` | `enchantment you control`, `enchantment spell`, `enchantment cards` | **Tuvasa the Sunlit, the archetype's poster commander, matched none of the three existing patterns** |
| `aristocrats` | `is put into a graveyard from the battlefield`, `sacrifice up to` | Magic's other spelling for "dies" (Agent of the Iron Throne); a variable-count sac outlet (Baba Lysaga) |
| `landfall` | `additional land` | the gap `CLAUDE.md` already flagged (Flubs, the Fool) |
| `counters` | `each kind of counter` | **doubling** counters is a payoff that places none (Vorel) |
| `impulse` | `reveal the top card of your library. you may cast` | reveal-and-cast is impulse without the word "exile" (Yennett) |

**Three candidates were measured and rejected**, which is the part that keeps this honest:
`"sacrifice another"` (0 rescues against 80 legends touched), `"counter on target"` (2.3% of
legends for the same single rescue `"each kind of counter"` gets at 0.2%), and a loose
reanimator phrase that risked re-creating the documented cheat-into-play mislabel. No theme now
exceeds 0.6% of the legend pool from a *new* pattern, and mean themes per commander is **1.38**
— no detection inflation.

**This is under-stated by the corpus.** In the user's own seven-deck pod, **3 of 7 commanders
(43%)** detect nothing: Witherbloom, the Balancer · Vorel of the Hull Clade · Avatar Aang.
Avatar Aang is a transforming commander, a shape the taxonomy has no read on at all.

**Prior attempt, and why it only got so far.** Widening existing patterns was measured at
~5 more commanders and correctly left undone. The remaining gap is **not** more regex on the
same 43 themes — it is archetypes with no entry.

**Plan.**

1. **Work the 24-card review queue** in `docs/data/zero_theme_triage.json`, where the two
   models disagreed. The 52 they agreed were themeless are the NEW-archetype pool; run the
   distinctive-bigram analysis (deterministic, offline — how `face_down`, `sagas` and `impulse`
   were found) over those rather than over all 75.
2. **Qualify each candidate by measurement, exactly as `face_down`/`sagas`/`impulse` were:**
   - how many of the 80 it would rescue (a candidate under ~8 is not worth a theme slot);
   - its `theme_match` STRONG rate over the 34,179-card store — anything scoring like
     `voltron_combat` (19.35% of all cards) is a base-rate trap, not a theme;
   - whether its payoff is distinguishable from an existing role (the `big_mana` failure:
     its "payoffs" were mana *sources*, so it would have spent 20 theme slots duplicating ramp).
3. **Land each survivor as the four coordinated edits** — `THEME_PATTERNS`,
   `THEME_SYNERGY_QUERIES`, `theme_match.THEMES` + `THEME_RULES`, then
   `python scripts/theme_base_rates.py`. `tests/test_theme_taxonomy.py` pins the lock-step;
   a theme present in one structure and absent from another fails **silently**.
4. **Gate on the same before/after** the last three themes used: zero-theme percentage, plus a
   `builder_bench` run to confirm synergy did not regress.

**Definition of done:** zero-theme under 15% of unique commanders, with no theme added whose
STRONG rate exceeds ~2% of the card pool, and `builder_bench` mean synergy not down.

### Plan step 1 (the 24-case review queue) — WORKED, 2026-08-25/26

Ran `commander_analysis._detect_themes` against all 24 disagreement cases in
`docs/data/zero_theme_triage.json` (`agree: False`) against the taxonomy AS IT STANDS after
this session's shipped patterns (reanimator's `"graveyard onto the battlefield"`, plus the
earlier landfall/enchantress/artifacts/spellslinger/impulse widenings). **10 of 24 are already
rescued** — Agent of the Iron Throne, Baba Lysaga, Flubs the Fool, Marina Vendrell, Szarekh,
Tannuk, Thor Odinson, Witherbloom, Tuvasa the Sunlit, Yennett — by patterns landed for OTHER
reasons earlier in the same taxonomy pass, not by anything new. **The remaining 14 were
individually read against real oracle text and are genuinely themeless, not a pattern gap:**

- **Arcades, the Strategist** and **The Master, Transcendent** — already investigated and
  correctly rejected earlier this session (defenders-matter: 1/7 real payoffs; milled-reanimator
  phrasing: only 1 additional rescue).
- **Deadpool, Trading Card**, **Mairsil, the Pretender**, **Omo, Queen of Vesuva** — one-off
  joke/build-around mechanics (text-box swap, ability-theft, universal-type counters) with no
  generalizable archetype to attach to.
- **Arixmethes**, **Selvala**, **Liesa**, **Y'shtola** — real but idiosyncratic triggers (a
  dozing land-creature, power-conditioned draw, symmetric life-loss tax, life-loss-this-turn
  draw) that don't cleanly map onto any of the 43 existing themes without either being too
  narrow to clear the ~8-rescue bar or broad enough to become a base-rate trap.
- **Karona, False God** and **Tymna the Weaver** — confirms `lift_stats.py`'s already-documented
  finding (see `CLAUDE.md`) that these are "value"/partner commanders with genuinely no
  archetype; deck-context themes, not more patterns, is the right answer for them.
- **Candlekeep Sage** and **Folk Hero** — both use the "Commander creatures you own have ..."
  Background templating. **Measured, not assumed**: 28 cards in the full 34,179-card pool use
  this exact lead-in, and every one of the 28 grants a DIFFERENT ability (ETB draw, tribal-spell
  draw, +1/+1 doubling, menace, goad, copy-ability, …) — there is no single payoff phrase that
  rescues more than the 1-2 cards that happen to share it, and matching the shared lead-in
  itself would be matching the MECHANIC (Background), not an archetype, exactly the trap
  `big_mana` and the rejected `"sacrifice another"`/`"counter on target"` candidates already
  fell into. Correctly left themeless.

**No new pattern is worth shipping from this queue.** Every disagreement case is now accounted
for — either already fixed, or read against real text and confirmed to have no archetype a
40-theme taxonomy should own. Zero-theme unique-commander rate is unaffected by this pass (no
new detections beyond the 10 already counted in the 16.4% headline above); what changed is that
the review queue itself is now fully worked rather than an open action item. The path forward
for S1's remaining ~16.4% is plan step 2 as written — the wider legend pool's distinctive-bigram
sweep — not further hand-review of this specific 80-case triage set.

### Second offload round: the whole legend pool, not just the corpus

The corpus is 391 commanders; the app serves any of Magic's **3,790 legendary creatures**, and
a pattern gap that shows up once in the corpus can show up thirty times across the pool. The
rebuilt harness was run over all **525 themeless legends that have at least one candidate**
(`scripts/offload/sweep_all_legends.py`) — 14b in 90 seconds, 32b in ten minutes, two passes,
resumable. Both models scored all 525; they agreed on **257 (49%)**, of which **47** were a
theme.

**The biggest cluster was a trap, and rejecting it is the result.** 28 agreed on `lifegain`,
but the shared wording was `lifelink` (49 rescues, **5.0%** of all legends) and "you gain N
life" (44, **5.8%**) — which identify lifegain **sources**, not payoffs. Filing those would
spend 20 theme slots on bodies that happen to gain life, which is exactly the measured reason
`big_mana` was dropped. Only the two payoff phrasings were taken (`life you gained`, `extort`
— 6 rescues, 0.6%).

**What the round did land: four archetypal commanders the taxonomy should never have missed.**

| commander | was | cause |
|---|---|---|
| **Zur the Enchanter** | *nothing* | tutors "**an** enchantment card" — singular, and the patterns only had plural |
| **Tatyova, Steward of Tides** | *nothing* | **2024 templating**: cards print "a land you control enters", the patterns had the pre-2024 "a land enters the battlefield under your control" |
| **Kurkesh, Onakke Ancient** | *nothing* | "ability of an artifact" |
| **Akal Pakal, First Among Equals** | *nothing* | "an artifact entered" |

### The templating sweep that followed, and the ratchet it produced

The Tatyova case pointed at a class, so every pattern was swept against the full 34,179-card
pool. **Scryfall re-templates old cards to the modern Oracle wording, so pre-2024 phrasing
exists nowhere** — and three patterns were measurably dead:

| theme | dead pattern | matched | modern replacement matches |
|---|---|---|---|
| `enchantress` | `enchantment enters the battlefield` | **0** | 63 |
| `landfall` | `whenever a land enters the battlefield under your control` | **1** | 185 |
| `etb` | `whenever a creature enters the battlefield under your control` | **2** | 244 |

`enchantress` is the one that mattered: that literal was its ONLY templating pattern, so the
theme was running purely on its two "whenever you cast" alternatives.

The sweep then found **twelve more dead patterns across eight themes** — `unblockable`
(re-templated to "can't be blocked"), `flicker` (a flavour word, never printed in rules text),
`reanimate` (a card *name*), `gain {e}` (energy is "you **get** {E}"). **No theme is fully
dead**, so this is weight rather than breakage, though `theft` is down to a single live pattern.

Two guards now hold the line, both skipped in CI where the card pool is absent:
`test_no_theme_has_all_of_its_patterns_dead` (the failure that actually breaks the app — a
theme nothing can trigger, silently) and `test_the_dead_pattern_set_has_not_grown`, a **ratchet**
against `KNOWN_DEAD_PATTERNS`: a newly-dead pattern fails, and so does fixing one without
removing it from the list.

### And the same sweep on the other structure

`theme_match` carries the same wording, so its 94 rule alternatives were swept too — **6 dead,
14 thin (<15 cards)**. The dead six are *the same literals* that were dead in `THEME_PATTERNS`
(`reanimate`, `whenever an enchantment enters`, `exile them, then return`, …), which is this
repo's standing "two structures that must agree" class arriving once more.

The thin list is its own warning: `whenever you cast a sorcery` matches **one** card,
`whenever a land enters the battlefield under your control` **one**, `whenever a creature
enters the battlefield under your control` **two**. Those rules survive only on their sibling
alternatives.

Both structures now have a matching pair of guards — a hard "no theme has zero live
alternatives" and a ratchet against a known-dead set. The known sets store the **plain phrase**
and unescape at comparison time, so they stay readable and carry no backslashes.

**Standing lesson: Magic re-words itself, so a pattern that was correct when written can stop
matching without anything failing.** That is now tested rather than remembered — in both places.

### The n-gram pass ran, and found nothing worth adding — record it

The distinctive-n-gram analysis that found `face_down`, `sagas` and `impulse` was re-run over
the themeless legends (963 of 3790 across ALL of Magic, 25.4% — the corpus figure of 16.4% is
lower because corpus commanders are the popular ones). At a threshold of ≥6 occurrences and
≥1.6 lift it produced 179 two-gram and 199 three-gram candidates, and **essentially all of them
are grammatical fragments**, not mechanics: `or triggered`, `hand the`, `c c`, `before the`,
`that would`. The one real archetype visible is copying activated/triggered abilities
(Riku/Kalamax shape, 6–8 commanders) — below the ~8 threshold and with no coherent card
package to fill 20 slots.

**So the remaining themeless commanders do not share a mechanic**, which is the same conclusion
the earlier pass reached from the other direction and which the offload ensemble independently
supported (52 of 80 agreed "no theme in the vocabulary fits"). Deck-context themes
(`deck_themes`) are the right answer for this tail, not more taxonomy. Re-running the n-gram
pass is not worth doing again until the card pool has grown substantially.

### Working the disagreement queue found one real, precisely-scoped miss — and rejected a second

**2026-08-25.** `docs/data/zero_theme_triage.json`'s 24-card disagreement queue (Plan step 1,
never actually worked before now) was re-checked against the CURRENT taxonomy first: 10 of the
24 are already fixed by the later offload/templating rounds (Tuvasa, Witherbloom, Yennett,
etc.), leaving 14 genuinely still open. Read each one's real oracle text by hand rather than
trusting the "big" model's guessed label (which turned out wrong or too coarse for most of
them — Deadpool/Omo/Mairsil are correctly zero, Mairsil is the already-rejected Riku/Kalamax
copy-ability shape; several "lifegain" guesses are the already-documented lifegain-source trap).

**Rejected: "defenders matter" as a new theme.** Arcades, the Strategist genuinely rewards
defender creatures ("whenever a creature you control with defender enters, draw a card").
Measured before building anything: only **7** legendary creatures in all of Magic even mention
"with defender" in their own text, and inspecting them shows only ONE — Arcades itself — is an
actual payoff; the other six just create Wall tokens as an incidental side effect (Super-Skrull,
Atla Palani, ...), which a broad substring match conflated with the real archetype. A theme
that would exist for exactly one commander in the entire card pool fails the bar every other
addition this session met (`~8` rescues minimum) by an order of magnitude. Not added.

**Fixed: a one-word preposition typo in the `reanimator` pattern, live for years.** The existing
literal is `"from a graveyard TO the battlefield"` — real templating says **"ONTO"**, not "to"
(Chainer, Dementia Master: *"Put target creature card from a graveyard **onto** the
battlefield"*), and Geth, Lord of the Vault's own wording ("from **an opponent's** graveyard")
never contained "a graveyard" as a substring at all. Measured before shipping: the broader
`"graveyard onto the battlefield"` literal hits **86** real cards (**0.25%** base rate, safely
clear of a base-rate trap; `deck_themes.BASE_RATE["reanimator"]` regenerated 0.00545 → 0.00798)
and rescues **4** previously zero-theme commanders — **Chainer, Dementia Master**; **Geth, Lord
of the Vault**; **Vhal, Scholar of Mortality**; **Soul of Windgrace** — verified live against
each one's real card text after the fix. Landed in both structures that must agree
(`commander_analysis.THEME_PATTERNS` and `theme_match.THEME_RULES`), matching the project's own
recurring "two structures drift apart" failure class. 1264/1264 tests green.

**A candidate broader phrase was tried first and correctly narrowed.** The initial substring,
`"to the battlefield under your control"` (no "graveyard" requirement), rescued 10 commanders,
not 4 — but reading each one's real text showed half were semantically wrong: Thassa,
Deep-Dwelling blinks a creature YOU ALREADY CONTROL (a self-ETB-abuse effect, not reanimation
at all) and would have been mislabeled `reanimator`. Requiring "graveyard" in the same phrase
is what correctly excludes Thassa while keeping every genuine reanimation-shaped hit — the
extra word is doing real semantic work, not just narrowing the count.

### The `deck_themes` rescue rate's own gap, investigated and closed as correctly calibrated

**Measured 2026-08-25.** Of 87 themeless-commander corpus decks with enough resolved cards to
judge, `deck_themes.detect_deck_themes` rescues **47 (54%)**, leaving **40 (46%) with no
archetype from either source** — close to this entry's earlier "42%" figure (the exact count
moves slightly with corpus resolution rate, not with any code change). Spot-checking several
of the 40 by hand surfaced a real, sympathetic pattern: Jegantha's `chaos` (2 STRONG cards,
2.49x lift), Nin's `sagas` (2 STRONG, 2.92x lift), Thrasios's `draw_matters` (2 STRONG, 5.79x
lift) all clear `LIFT_FACTOR` (2.0) comfortably and fail ONLY on the absolute `MIN_STRONG = 3`
floor — one card short. On the numbers alone this looked like a real near-miss worth fixing.

**It is not, and the sweep that would have caught this before shipping it now exists
(`scripts/theme_min_strong_sweep.py`), mirroring the exact methodology that originally
calibrated `LIFT_FACTOR` against 40 random piles.** Run against 87 real themeless-commander
decks and 60 random 60-card piles:

| `min_strong` | real recall | random false-positive rate |
|---|---|---|
| 3 (current) | 54.0% | 26.7% |
| 2 | **80.5%** | **81.7%** |
| 1 | 98.9% | 100.0% |

**Lowering the floor to 2 buys +26.5 points of real recall and costs +55 points of noise** —
at that setting the gate is nearly as likely to bless a random 60-card pile with a fake
archetype as it is to correctly find a real one, which destroys the signal `deck_themes`
exists to provide. This is the same failure shape S12's "un-clamp oversupply" and PLAN_CLOCK's
"random order" marker both were: a change that looks like it closes a real gap and instead
trades a smaller, honest miss for a much larger, dishonest hit rate.

**The obvious narrower fix — only lower `MIN_STRONG` for the RARE themes that produced the
near-misses — is also wrong, and for a specific, checkable reason.** Breaking down which
themes drive the `min_strong=2` false-positive rate on random piles shows the noise
concentrated in exactly the LOW base-rate themes (`face_down` 21.7% of random piles, `chaos`
20.0%, `aristocrats` 20.0%, `impulse` 15.0%) — not the high base-rate ones (`counters` 1.7%,
`graveyard` 6.7%) a naive intuition would suspect. The reason is arithmetic: `theme_lift =
strong / (base_rate * scored)`, and a theme with a tiny base rate has a tiny denominator, so
getting even 2 STRONG hits BY PURE CHANCE already produces a large multiplicative lift —
`chaos`'s own base rate (1.23%) times a 60-card pile is an EXPECTED 0.74 cards, so 2 real hits
land at ~2.7x lift from chance alone. The rare themes are exactly the ones two-hits-by-luck
inflates the most, which is the opposite of where a lower floor would be safe.

**Conclusion: `MIN_STRONG = 3` is correctly calibrated as a single global floor and should not
be touched in either direction.** The 40 corpus decks that remain themeless from both sources
are the honest output of a gate doing its job — a felt-real 2-card signal on a rare theme is,
measured against the population, indistinguishable from noise. `theme_min_strong_sweep.py` is
kept (not a throwaway) so a future attempt at this exact idea re-measures rather than
re-guesses.

Every sweep so far asked "what theme does this card have". This one asked the opposite and more
dangerous question: **of the cards a theme already claims, how many does it not deserve?**

`voltron_combat` was the case to audit — `theme_match` scores it STRONG on **19.35% of every
card in Magic** (the documented base-rate trap), and `THEME_PATTERNS` detects it on more legends
than anything except `counters`. The local model audited all **879 legends the theme claims**,
one narrow yes/no each: **313 (36%) are not combat-plan cards**.

**Every flagged claim traces to a bare keyword**, and a hand read of a sample agrees with the
model: `trample` (161), `can't be blocked` (74), `first strike` (58), `double strike` (25).
Rakdos, the Showstopper is a coin-flip board wipe that happens to have trample. Devil Dinosaur
is Dinosaur tribal with trample. Beluna Grandsquall is Adventure cost-reduction with trample.

**This is a rule the codebase already states and this file violates**: `collection_pool`
documents *"having a keyword is not granting it — Smaug HAS indestructible and protects only
itself; Darksteel Plate grants it to another"*, and `theme_match` encodes it as
`strong_type_required`. `THEME_PATTERNS` does not.

Candidate fixes, scored against the audit:

| pattern set | claims | precision | recall | share of all legends |
|---|---|---|---|---|
| **current** (bare keywords) | 878 | **64.4%** | 100% | **23.2%** |
| drop bare keywords | 264 | **96.2%** | 45.0% | 7.0% |
| drop bare + require the keyword be GRANTED | 411 | 83.0% | 60.4% | 15.6% |

### Resolved with a hand-labelled gold set — and it overturned the model's preference

28 cards drawn from **both** sides (fixed seed 11) and labelled by hand from oracle text before
anything was scored. Agreement with the model was **24/28 (86%)**; the four disagreements were
all marginal, and two mattered — it called **Akiri, Line-Slinger** (a textbook equipment-voltron)
and **Rhonas the Indomitable** *not* combat decks.

| pattern set | accuracy | precision | recall | FP | FN |
|---|---|---|---|---|---|
| **original** (bare keywords) | **50%** | 50% | 100% | 14 | 0 |
| drop bare keywords | 82% | 100% | 64% | 0 | 5 |
| **drop bare + require the keyword be GRANTED** | **89%** | 87% | 93% | 2 | 1 |

**On a balanced sample the shipped patterns scored 50% — chance.** They could not distinguish a
combat deck from a non-combat one at all; they simply said yes to everything with a keyword
(14 false positives, 0 false negatives).

Note the model's own labels favoured *"drop bare keywords"* (96.2% precision there). The hand
labels favour the granted variant, which keeps Akiri and Rhonas. **This is the case for gold
sets in one table** — the cheaper signal picked the wrong winner.

**Landed.** `voltron_combat` now claims **584 of 3,790 legends (15.4%)**, down from 879 (23.2%).
`scripts/voltron_gold.py` is the scorer and pins the ORIGINAL list explicitly, because deriving
it from the live module made every row identical the moment the fix landed — quietly turning
the comparison into a no-op.

**The honest cost, stated rather than buried:** themeless legends rose **946 → 1,095 (25.0% →
28.9%)**, because ~295 legends lost a claim that was mostly false and had no other theme. That
moves S1's headline the wrong way. It is still the right trade under this project's standing
bar — an honest under-count beats a confident fabrication — but S1 and S9 pull against each
other and the S1 number should be read with that in mind.

**Still owed:** a `builder_bench` run. This theme feeds ~20 slots on what was 23% of commanders,
so it is the single largest lever on what the builder actually drafts, and the bench is the only
thing that measures that end to end.

---

## S10 — ~~`ROLE_TARGETS` is archetype-blind~~ · DONE 2026-08-19

**The defect.** `redundancy` judged every deck against ONE population baseline, so a deck
that plays to a role as its PLAN read as over-supplied in exactly the thing it was trying to
do. `counterspell`'s population target is **3 supply units — the weight of a single card**,
because the median corpus deck runs zero. Measured over 499 corpus decks, the 24 that
actually ARE spellslinger decks supply a p60 of **12**, with individual decks at 6, 12, 15
and 27. Every one was scored 3x-to-9x over and its interaction became the cut pool. That is
how a Prismari deck came to be told to cut **Flusterstorm** and **Mental Misstep**.

**The fix is a table, and it is measured the same way `ROLE_TARGETS` is** — the p60 of real
supply, but over only the decks detected as each archetype
(`scripts/archetype_role_targets.py`, `--check` diffs, `--audit` shows every candidate cell
and the gate that rejected it).

**Three gates, and all three do work.** (1) at least **20** decks carry the theme — split-half
disagreement falls monotonically with sample size (mean |A−B| 4.45 at n<12, 3.84 at 12–20,
3.04 at 20–30, **1.86 at n≥30**), and relaxing to 12 admits seven cells whose halves disagree
by 8.5–9.0, which is the noise band itself; (2) **both halves** of the theme's decks must
independently exceed the population target — this is what rejects `draw_matters` draw (23.0
overall, halves of 27 and 14), `chaos` counterspell (6 / 0) and `theft` wipe (0 / 6). It is
per (theme, ROLE) rather than per theme, because `draw_matters` is unstable on `draw` and
rock-steady on `counterspell` (9 / 9); (3) a **margin of 3** supply units, so the table
records a difference that changes a judgement rather than a rounding step (this is what drops
`counters` ramp at 15 vs 14 and `tokens` finisher at 4 vs 2).

Five cells survive, and each is Magic-plausible on its face: spellslinger wants counterspells
(12) and card draw (26), draw_matters holds up interaction (9), landfall ramps with lands
(23), chaos draws (28).

**It only ever RAISES a target.** There is no lowering half. The defect is false-positive cut
suggestions, and a lower target manufactures more of them; it is also where small-sample
noise would do the damage.

**Measured payoff** at k=6 (the pool Forge's `/advise` asks for), over the 106 corpus decks
carrying an overridden archetype: the cut pool changes on **52 (49%)**, and the share of cut
slots drawn from the deck's **own plan role falls 64.0% → 33.8%**. Role balance follows —
removal 7% → 16%, draw 45% → 37%, ramp 28% → 20%.

**The residual 33.8% is correct and must not be driven to zero.** A deck really can
over-serve its own plan: the corpus spellslinger deck running **27** counterspells against an
archetype target of 12 IS over-served, and saying so is the module working. Pinned by
`test_an_archetype_target_still_flags_a_genuine_oversupply`.

**The contract, since the detector is in the other process.** `deck_themes` lives in Forge;
the engine runs on :8020 and Forge's modules are not on its path. So `redundancy.targets_for`
takes archetype names as **plain strings** and ignores unknown ones — a Forge that learns a
new archetype tomorrow degrades to the population baseline instead of breaking the advisor.
`advise(themes=…)` threads them, `/advise` accepts a `themes` list, and Forge's
`_deck_archetypes` supplies them. The calibration script is the one place that imports both,
offline, to produce a table of strings; the runtime never crosses the boundary.

**Callers pass the deck's OWN themes, not `merge_themes`' output** — the merged list
deliberately retains commander themes the deck does NOT support (its tier 3), and raising a
target for a plan the deck is not executing would re-open this bug from the other side.

**Honest limit.** `_deck_archetypes` prefers the persisted `stats.archetypes` block because
it was computed from the deck's real cards; the fallback re-derives from stored entries,
where theming has mutated the text those rules read (a tribe reskin rewrites rules text). It
reads `original_type_line` to dodge the worst of that, but on a tribe-reskinned deck built
before `stats.archetypes` existed it can under-detect — which costs precision, not
correctness, since no archetype means the population baseline.

---

## S11 — ~~`card_impact` cuts by popularity~~ · DONE 2026-08-20

**The defect.** `redundancy` replaced `advisor._weakest_cuts` because the least-played cards
in a deck are its pet cards and silver bullets — the ones the pilot put there on purpose.
`ratings/card_impact.assess_card` was never moved over. So "is <card> good in my deck?" —
the one route a user reaches interactively — was answered by swapping the candidate against
the deck's most obscure cards. On the corpus Shelob deck that pool is *Supper for Spiders /
Gloomwidow's Feast / Eaten by Spiders*, the deck's whole reason for existing, which is the
canonical failure this project already named.

**Measured** over 40 (deck, card) cases — 20 corpus decks spread across the corpus, two
legal staples each, full-fidelity store, `cut_pool=3`, `runs=200`:

    recommended CUT changes     38/40  (95%)
    final VERDICT changes       12/40  (30%)

The verdict moving on 30% is the figure that matters: `assess_card` keeps the BEST pairing
across the pool, so a better pool gives the candidate a fairer slot to displace, and the
answer the user reads flips on nearly a third of questions. This was never cosmetic.

**A second defect, stacked on the first.** The user-facing reason line read *"Measured by
swapping it in for X, **the weakest slot it beat**"* — and that was never what was measured.
The pool came from the least-played rule, and least-played is close to the **opposite** of
weakest in a deck someone built on purpose. Same class as S3: wording that claims something
the measurement does not support. `_cut_sentence` now names the deck's most over-supplied
role and by how much.

**And it does not over-claim in the other direction.** Where the deck over-supplies nothing
(S12, 9.0% of corpus decks) there IS no redundant card, so the sentence says that instead of
dressing the tiebreak up as redundancy.

`themes` is threaded the same way S10 threaded it into `/advise` — the contract, the plain
strings, and Forge's `_deck_archetypes` are all reused rather than re-invented.

---

## S14 — the swap reason was a list of fragments, and never said why THAT cut

**The defect.** `advise` assembled `reason` from template fragments — *"A big dragon your
commander can cheat into play; a one-shot team finisher. Measured: kills ~1.2 turns sooner."*
It reads as a list because it is one, and it is silent on the half a user actually questions:
why THAT card is the cut. The advisor has known the answer since `redundancy` landed (the
role, how over-supplied it is, how strongly the card serves it) and never said it.

**A model writes better prose and also fabricates**, and on an MTG-facing surface a wrong
claim about a card is a defect. So generation is split, and the split is the design:

    engine   SwapBrief  — the facts, measured, offline, deterministic
    Forge    prose      — generated locally, then GATED against that brief

**`SwapBrief` is a CLAIM BUDGET.** It carries the only card names that may appear, the only
numbers that may be cited (`allowed_numbers`), each card's functions as the rung-1 vector
actually reads them, and whether the cut was backed by real redundancy at all. That is what
makes the check mechanical instead of a matter of taste — every gate below traces a sentence
to a measured field, the same way the CCM gates trace a capability model to Oracle text.

**Seven checks, each of which rejected something real:** a card outside the swap; a number not
in the brief; prose contradicting the measured direction; a function the vector does not show;
an intensifier a marginal gap has not earned; a claim about an axis nobody measured; and
redundancy language on a deck that over-supplies nothing (the **S12** guard, reused).

**Four of them were FALSE POSITIVES first, and all four were found by reading real output:**

| bug | why it fired | fix |
|---|---|---|
| "team pump" charged to the CUT | nearest-name-either-direction; by the time the phrase appears the cut is closer | attribute to the nearest **preceding** name — English puts the subject first |
| `Vesuva` flagged as foreign | Magic names nest — the commander is *Omo, Queen of Vesuva* | mask allowed names **before** the foreign-name scan |
| "card draw" rejected on a draw-role cut | `card_roles` and `card_functions` are **different vocabularies** (role `draw` ← `repeatable draw`) | widen a cut's vocabulary by the role the engine granted it |
| a board-wipe claim waved through | the negation guard read `n't` **inside the card's own name** — *An Offer You Can't Refuse* | exclude card-name spans from the negator scan |

A false rejection costs only polish, but it silently starves the corpus of exactly the drafts
worth keeping — which is why they are pinned by name in `tests/test_swap_narrative.py`.

**Measured on qwen3:32b over real briefs:** 3 of 7 attempts survived the gate before the
prompt was taught the rules it would be judged by; **3 of 3 on first attempt** after. The
prompt cannot be left to infer them — a rule the gate enforces and the prompt never states is
a guaranteed rejection, and that is pinned by a test too.

### The corpus builder — `scripts/build_reason_sft.py` (2026-08-20)

Rejection sampling, the same shape that built the ~30k CCM corpus with no human annotation:
**teacher drafts → deterministic gates → keep what survives**. Writes the same
`{"messages": [...]}` JSONL that `scripts/train_ccm_lora.py` already consumes.

Two phases, because they are bound by different resources: `--harvest` runs the real advisor
to collect briefs (sim-bound, ~50s/deck, cached to `briefs.json`), `--draft` samples the
teacher k times per brief and gates each (LLM-bound, cheap to re-run). Re-running `--draft`
after tightening the gate is the normal way this corpus improves, which is why they split.

**The split is by DECK, not by swap** — two swaps from one deck share commander, archetype and
role supply, so a per-suggestion split puts near-duplicate context on both sides and flatters
the eval. **The trained system prompt is terser than the teacher's**: the teacher is handed
every rule the gate enforces, and learning those rules is what the fine-tune is *for* — the
same trade `build_ccm_sft.py` makes when it drops its 14 few-shot exemplars.

**`--axes all` is the default, and volume is the lesser reason.** Targeting only the weakest
axis yields 0.9 briefs/deck and a corpus dominated by whichever axes are usually weakest;
sweeping all five yields **7.3 briefs/deck** and covers every axis label the model must write
about. Projected over the full 499-deck corpus: ~3,600 briefs, ~7 hours — an overnight job,
the established pattern here.

**THE GATE HAD SEVEN FALSE POSITIVES, AND EVERY ONE WAS FOUND BY READING REAL OUTPUT.** None
was predicted from the design. Measured over 44 briefs as they were fixed:

| | brief yield | gate pass |
|---|---|---|
| first run | 77.8% | 43.8% |
| after the family + "removes" fixes | 81.8% | 52.2% |
| after the role-word-is-a-card-name fix | **90.9%** | **64.5%** |

The last one is the sharpest example of the class: Magic prints a card called **Counterspell**,
and `counterspell` is simultaneously the engine's role name, so a deck holding that card had
every honest sentence about an over-supplied counterspell role read as naming a foreign card.

**The lesson generalises past this module.** A faithfulness gate cannot be written by reasoning
about what a model might do — the failure modes are collisions between the checker's vocabulary
and ordinary English ("removes", "draw", "Counterspell", `n't` inside a card's own title), and
they only appear when you read what the model actually wrote. Every one is pinned by name in
`tests/test_swap_narrative.py` so the next tightening cannot silently reintroduce it.

### `--bench` answered whether to train, and the answer is not yet

The open question was whether a fine-tune is needed at all. `--bench` runs the same briefs
through several (model, prompt) arms and reports the gate — 44 briefs, k=3:

| arm | brief yield | gate pass | s/brief |
|---|---|---|---|
| qwen3:32b / full | 90.9% | 63.5% | 3.8 |
| **qwen3:14b / full** | **93.2%** | **71.9%** | **1.4** |
| qwen3:8b / full | 75.0% | 43.4% | 1.1 |
| qwen3:14b / short | 81.8% | 52.9% | 1.5 |
| qwen3:8b / short | 81.8% | 52.9% | 0.9 |

**The 14b runtime beats the 32b teacher**, at 2.7× the speed. That is not noise-sized and it
has a mechanism: this is a constrained phrasing task over supplied facts, and a bigger model
writes more elaborately — which is more chances to over-claim, not fewer. Its dominant
rejection is the same one, `claimed a function the vector denies`, just more often. **The
teacher default in `build_reason_sft.py` changed 32b → 14b on this evidence.**

**So the fine-tune has no quality gap to close** on the path a user actually hits. The rule
preamble is worth ~19 points of gate pass on 14b (71.9 → 52.9), and closing *that* is exactly
what training would do — but **dropping the preamble saves no measurable time** (1.4s vs 1.5s
per brief), so the throughput argument, which was the only one left, is not supported either.

**The case that survives is narrower, and it is a real one:** `8b/full` scores 43.4%. If the
runtime ever has to drop to 8b for VRAM, a fine-tune that lifts 8b toward 14b is how to do it,
and this corpus is what that would train on. Until then the corpus earns its keep as the
gate's regression set.

**Recorded as a decision, not a deferral.** Nothing upstream is missing: brief, gate, corpus
builder and bench all exist, and `scripts/train_ccm_lora.py` consumes the output unchanged.
The reason not to train is measured.

### Driving the live route found a defect 29 unit tests and the gate both passed

The wiring was verified end to end — engine on :8020, Forge API on :8000, llama-swap on :8010,
a real stored deck through `POST /api/deck/{id}/advise`. It works, and the improvement over the
template is not subtle: one suggestion's old reason was the vacuous fallback *"Measured to
raise ceiling."*

It also produced this, on a deck supplying **33.0** ramp against a target of **14**:

> *"…over-supplied in its ramp role, contributing only 1 function in a deck that **already has
> 14 ramp sources**"*

**Understating the deck's own ramp by 19, with every number in the budget.** The numeric check
compares a cited value against a set, so a figure bound to the *wrong quantity* passes it
cleanly. Call it relational misassignment: `role_supply`, `role_target` and `oversupply` are
three numbers about one role, and prose can transpose them while staying "faithful" by any
membership test.

Two fixes, because presentation and checking are different jobs:

1. **The facts block presents the comparison as a labelled table**, not an inline clause. The
   old form — `deck supplies 33.0, decks like this one supply 14 (over by 19.0)` — is three
   numbers in a sentence and the model transposed two of them. Three labelled rows are much
   harder to get wrong, and on the re-run the same swap came back with *"the deck providing
   33.0 while similar decks only need 14.0"* — the correct relation.
2. **A narrow gate check** for the specific shape: the target figure attributed to the deck
   (`deck has`, `already runs`, `you have`) when supply and target actually differ. It stays
   quiet when they are equal, and never bans citing the target against the population.

**The lesson is about method, not this bug.** The gate passed it, and so did 29 unit tests
written from the gate's own contract — because both were reasoning about *the checker*. Only
driving the real route on a real deck produced the sentence that exposed it. Same conclusion
the seven false positives reached from the other direction: for a faithfulness layer, output
you have actually read is the only evidence that counts.

---

## S2 — ~~Partner decks can be analysed but not built~~ · DONE 2026-08-18

**Measured.** 33 of 483 corpus decks (6.8%) have 2+ cards in the command zone.

Analysis is already correct — `command_zone_identity` unions the identity and the themes, which
flipped 16 decks from "cannot cast itself" to castable. What does not exist is the **build**
path: `BuildRequest.commander_name` is a single string and there is no second-commander UI.

**Done.** `partner_names` is a **list** on both `BuildRequest` and `GenerateListRequest`
(Partner, Friends forever, Choose a Background and Doctor's companion all land in one slot),
resolved by `_resolve_partners` and handed to `build_commander_profile(card, partners)` — which
already did the right thing, so this was wiring.

**The rules live in `commander_analysis.partner_mechanic` / `can_pair`, read from oracle text
and type line rather than a curated name list** (a name list goes stale every set). `Partner
with X` is tested BEFORE bare `Partner`, because its reminder text contains the word "partner"
too, and it must name its partner **in both directions** — a one-way pairing does not exist.

**An illegal pair is refused, not built.** The zone's colour identity filters every other card,
so an illegal pair does not make a slightly-wrong deck — it makes 99 cards chosen against an
identity that is not legal to play. The refusal names the rule: *"That's a 'Partner with' card —
it pairs only with Toothy, Imaginary Friend."*

Verified end to end against a live build: Tymna + Pir → **HTTP 400** with that message; Tymna +
Thrasios → **HTTP 200**, a **WBGU** deck with sources in all four colours and `mana: ok`, which
is the union identity actually driving card selection. `StepCommander` shows the second-commander
box **only** when the searched commander reports a pairing ability, so the ~93% that cannot
partner never see a control they can't use — confirmed rendering for Tymna and absent for
Kozilek. 21 rules tests in `tests/test_partners.py`.

**Risk:** the colour identity widens to 4–5 colours, which is exactly the case the new
`rainbow` land tier was added for — so run `builder_bench` on a partner roster and check
colours-castable, not just that it builds.

**The risk above was real, and the "sources in all four colours" claim was checking the wrong
field (mentor campaign round 6, 2026-08-25).** `mana: ok` is `assess_mana_base`'s coarse
land/source COUNT check — it never filters by colour, so it stayed true throughout. The
per-colour `quality.colors` block (`deck_quality.assess_colors`) is what actually answers "does
this deck have real WBUG sources", and on a fresh Tymna + Thrasios build it read `colors.ok:
false`, `"U: 0 sources, wants 15"`, `"G: 0 sources, wants 15"` — a FALSE shortfall: the deck
genuinely holds an Island, three Forests and six 5-colour fixers. Root cause: the generate
path's `compute_stats(card, deck)` call never passed `partners=`, so `assess_colors` filtered
every source by the LEAD commander's own identity alone (WB), silently dropping every U/G
source that duals/fixers/basics actually produce — exactly the bug `command_zone_identity` was
built to fix for imports, never ported to the generate path. Worse: the strength engine
(`/measure`, `/advise`, `/card-impact`, `/duel`) and the Deck Mentor (`/mentor`) had an even
deeper version of the same gap — `_deck_to_lines`, the ONE function serializing a Forge deck
for MythGauntlet, only ever wrote a single `Commander:` line, so the engine's own
`ctx.resolved.commanders` never included the partner AT ALL for any of those five routes. Both
layers fixed and verified live (see `MENTOR_HANDOFF.md` round 6): `compute_stats` and all five
`_gauntlet_*` helpers now thread `partners=` through, and `deck.json` persists a new `partners`
field so a rebuild/retheme/mentor-chat/measure on an already-built partner deck doesn't lose it.
**Still open, deliberately not attempted**: the deck actually built is 99 library cards + ONE
commander card (Tymna) — the second commander is never added as a physical card at all, so what
ships is a legal-looking 100-card single-commander pile with a widened identity, not a true
98-library + 2-commander 100-card deck. Fixing that means threading a partner count into
`DeckBuilder.build()`'s slot-planning arithmetic, which hardcodes the literal `99` at ~20
internal call sites with a documented history of exactly this kind of arithmetic bug — not
guessed at without a partner-commander entry in `builder_bench.py`'s roster to measure against
first.

---

## S3 — ~~A population-relative label reads as an absolute claim~~ · DONE 2026-08-18

**Measured.** All five off-meta verdicts are quadrants of a 2×2 cut at **population medians**,
so each is a statement about *other decks*. `off-plan` was fixed this session — its blurb was
false for 80% of the decks it fired on, at 24.8% of all decks.

**`brew` is the same shape and is still shipped.** "Using the commander as a backbone for
something else" fires on 19.3% of decks with a **median 77.0% of measured cards on positive
lift**. That is defensible but it is the same trap, and it was left alone deliberately rather
than by oversight.

**Done.** All five audited against their measured medians. Two rewritten:

- `brew` → *"on-theme overall, but a wide gulf between its best and loosest picks"*. The
  defining feature of that quadrant is the SPREAD, not an absence of synergy.
- `on-rails` → *"plays this commander's most-played cards, and little else"*, replacing "close
  to the typical list" for decks sitting +20.1 ABOVE their page median.

The guard is now table-driven over every verdict (`MEDIAN_STAPLES_PCT` × `_ABSOLUTE_CLAIMS`), so
a verdict added later is covered the day it lands, and a second test fails if the table misses
one. Verified the guard would have caught both original blurbs.

---

## S4 — The off-meta read is often too sparse to judge

**Measured.** `insufficient-data` on **12.6%** of decks; coverage on the user's own pod ran
**27–86%**, with five of seven under 50%. An EDHREC page lists only ~250 cards, so a large
part of every deck is simply unmeasured. This is honestly reported today (coverage is always
shown, and the verdict is withheld below 25%) — the shortfall is that the *answer is missing*,
not that it lies.

**Plan.** Do not paper over it by widening the verdict. Instead raise real coverage:

1. ~~Measure whether EDHREC exposes more of the page than `edhrec_lift` currently parses~~
   **— measured 2026-08-25, and it does.** Verified live against `json.edhrec.com` (not
   assumed): the MAIN commander page's `container.json_dict.cardlists` already captures
   every card list on that page — for Atraxa, Praetors' Voice, 13 cardlists / 292 unique
   cards, matching this module's own worked docstring example exactly, so nothing on the
   main page itself is being missed. But EDHREC also serves per-THEME sub-pages at
   `.../commanders/{slug}/{theme-tag}.json` (discoverable from the main page's own
   `panels.taglinks`), and one of those genuinely carries more: fetching Atraxa's real
   `infect` sub-page live returned **32 cards** (Blightsteel Colossus, Blight Mamba, Fynn
   the Fangbearer, Dark Ritual, ...) that never appear anywhere on the main page at all —
   an 11% expansion for a deck actually built toward that theme.
   **Not integrated this pass, and the reason is a real design gap, not effort alone: which
   theme sub-page to fetch for a given build is not self-evident.** The main page's own
   `taglinks` are sorted by POPULARITY across all decks with this commander, which is a
   different question from "what does THIS deck actually do" — the same distinction
   `redundancy.py`'s `ARCHETYPE_ROLE_TARGETS` and Invariant 4 already exist to enforce
   elsewhere. Auto-fetching the top taglink would silently conflate "popular sub-strategy"
   with "this build's plan" for the majority of Atraxa builds that are NOT infect decks.
   Doing this correctly needs a maintained mapping from `deck_themes`'s own archetype keys
   to EDHREC tag slugs — a real "two structures must agree" surface this repo has been
   burned by repeatedly (the five dead `theme_match` rules, the `edhrec_lift`/
   `mythgauntlet.data.edhrec` slug duplication) — plus a `builder_bench` pass to confirm it
   actually helps before shipping the extra per-build network fetch it costs. Scoped, not
   guessed at: the next session picking this up should build the mapping table and measure
   it exactly the way `archetype_role_targets.py` measured its own table, not skip the gate.
2. ~~Report the figure as a confidence band~~ **— done 2026-08-18.** Corpus coverage over 244
   decks with a cached page runs **p10 0.22 · p25 0.47 · median 0.70 · p75 0.88 · p90 0.98**, so
   a bare percentage invited the reader to weigh a thin reading like a near-complete one.
   `confidence` is now `high` / `medium` / `low` on the block and a coloured chip in the panel,
   with a plain-language line under a `low` reading. **Both the share AND the absolute count
   must clear their bar** — 40% of a 40-card list is a thinner sample than 40% of a 99-card
   one — so the cutoffs are the corpus median and p25 on each axis (coverage 0.70 / 0.47,
   measured 38 / 25). Seven cases pinned in `tests/test_lift_stats.py`.
3. Leave `MIN_COVERAGE` at 0.25. It was calibrated; moving it to manufacture verdicts would
   trade an honest silence for a confident fabrication.

---

## S5 — Three taxonomy entries never fire

**Measured.** `tribal_beasts`, `tribal_slivers` and `tribal_werewolves` are detected on
**zero** of 391 corpus commanders. Nine more fire on 1–2.

This is not automatically a defect — Slivers are genuinely rare, and the corpus is 483 decks,
not all of Magic. But it is the same signature as the five dead `theme_match` rules, which
looked like rarity and were actually broken patterns.

**Resolved this session — mostly good news.** Hand-checked against real commanders:

| pattern | test | result |
|---|---|---|
| `tribal_slivers` | Sliver Overlord, The First Sliver, Sliver Queen | **3/3 detected** — rule works |
| `tribal_werewolves` | Tovolar, Dire Overlord | **detected** — rule works |
| `tribal_beasts` | Ghalta, Kogla, Nemata | 0/3 — **inconclusive**, see below |

So two of the three are **genuine rarity, not dead rules**, and need nothing but this note so
the next person does not re-investigate them.

`tribal_beasts` was inconclusive at first, and the honest reason was that **my three
exemplars were bad tests** — Ghalta is a big creature, Kogla is an Ape, Nemata makes
Saprolings; none of them is a Beast-*tribal* payoff. Note Kogla returned `[]` entirely, so
it is also an S1 case.

**Retested 2026-08-25 against real Beast-tribal payoff commanders, not the corpus's three
bad exemplars.** A direct search of the 34,179-card store for legendary creatures whose own
oracle text names Beasts as a payoff surfaced real candidates: **Slinza, the Spiked
Stampede** ("Beast spells you cast cost {2} less... each other Beast creature you control
enters with an additional +1/+1 counter") and **Radagast, Wizard of Wilds** / **Toby,
Beastie Befriender** (Beast-token generators with Beast-scoped keyword grants). All three
correctly return `tribal_beasts` from `_detect_themes`. **The rule works — it is genuine
rarity, not a dead pattern**, exactly like `tribal_slivers`/`tribal_werewolves` above: these
three commanders are recent enough printings that none of them appear in the (older) 391-deck
corpus, which is why the corpus alone read as 0/391 despite the rule being live. Closes the
one open thread this entry had left; all three original zero-count patterns are now
confirmed genuine rarity rather than breakage.

---

## S6 — coverage is fine; my first two readings of it were not *(priority LOWERED)*

**This entry has been wrong twice, and both errors are worth keeping because they are the same
class the rest of this file keeps finding: measuring one structure when there are two.**

*First reading* — a filename check against the store, which under-reports by 2.4 points because
the store slugifies names and mangles double-faced cards.

*Second reading* — reading `card.name` properly, but **only from `compiled/`**. That produced a
dramatic and completely inverted conclusion: that the **top 100 most-played cards were the
WORST-covered band (91.0%)**, with Sol Ring, Command Tower, Counterspell, Swords to Plowshares,
Rhystic Study, Demonic Tutor and Lightning Bolt all "uncompiled" — i.e. the engine guessing at
the cards every deck plays. I raised this shortfall's priority on that basis and reported it as
a headline finding.

**It was exactly backwards.** Those 14 cards are `ccm/authored/` — hand-authored **rung 3**, the
*highest*-quality tier in the store, deliberately written by hand rather than model-compiled.
`compile-top` skips them by design (`authored_names()`), which is also why they never appear in
the ledger. And they live in a **different root**: `authored/` sits in this repo while
`compiled/` follows `MYTHGAUNTLET_STORE`, so a check that assumes one root silently misses a
whole rung — precisely what `SemanticsStore.__init__` avoids by reading both.

### The corrected picture

| popularity band | cards | covered |
|---|---|---|
| **top 0–100** | 100 | **99.0%** |
| top 100–500 | 400 | 98.5% |
| top 500–1000 | 500 | 97.0% |
| top 1000–5000 | 4,000 | 96.5% |
| top 5000+ | 26,675 | 97.1% |

Pool-wide **90.0%**, and the most-played band is the **best** covered, not the worst. Only
**three** of the top 300 are genuinely absent — and all three are **quarantined with specific
schema errors at prompt v10**, which is the quarantine loop working as designed: it refuses a
malformed CCM rather than storing a wrong one.

| card | quarantine reason |
|---|---|
| The One Ring | `abilities[3].effects[0].target: expected target object, got 'this'` |
| Urza's Saga | `op search_library missing required param count` |
| Sensei's Divining Top | `abilities[0]: needs a non-empty effects list` |

**Done.** All three hand-authored into `ccm/authored/` (15–17), which is what that directory is
for. Each passes schema **and every validation gate**, and the store now reports them at rung 3.

| band | before | after |
|---|---|---|
| top 0–100 | 99.0% | **100.0%** |
| top 100–500 | 98.5% | 99.0% |
| uncompiled in top 300 | 3 | **0** |

**Each is a lossy model, and `ccm/authored/README.md` now says exactly where** — because a CCM
that quietly models the wrong card is worse than none, since the engine executes it at full
value. Sensei's Top uses `scry 3`, which *overstates* selection (scry can bottom, Top cannot)
and omits the put-back-on-library loop entirely. Urza's Saga chapter III uses `saga_chapter`,
which the engine deliberately does **not** execute — the honest under-count the vocabulary is
built for — while its granted abilities are modelled as always-available, which overstates
early. The One Ring's indestructible and protection-from-everything have no op at all, so the
main reason fair decks play it is simply absent.

`scripts/ccm_coverage.py` now reads both rungs and carries the post-mortem in its docstring.

**Standing lesson, earned twice on one shortfall: a measurement tool needs the same scrutiny as
the thing it measures.** Both wrong answers were confident, specific, and quotable.

### The re-compile that the schema fix unlocked (2026-08-18)

Chose this over a plain training run because the ledger was **96.5% already at prompt v10**: a
normal run would have re-compiled 1,116 working cards and touched **zero** of the 956
quarantined. Confirmed exactly — selection returned **0 targets** until `--retry-quarantined`
existed, then 952.

**Result: quarantined 956 → 443, accepted 31,026 → 31,539 — 513 cards recovered.**

| band | before | after |
|---|---|---|
| pool | 90.0% | **91.5%** |
| top 100–500 | 98.5% | 99.2% |
| top 500–1000 | 97.0% | 98.2% |
| top 1000–5000 | 96.5% | **98.2%** |
| top 5000+ | 97.1% | **98.7%** |

**Do not credit the schema widening with 513.** The run confounds two effects, and only one is
mine: the widening was predicted to unlock **141**, and that class is now empty (6 fixable-shaped
errors remain of 443). The other **~372 are the model simply doing better on a second attempt at
the same prompt version** — compilation is non-deterministic, and no card had been retried since
being quarantined. So the honest attribution is: the FLAG unlocked 952 retries worth 513 cards,
of which the schema fix is responsible for roughly 141.

The remaining 443 are genuine model errors the cross-check gates are right to reject — declared
trigger events with no textual support, CCMs claiming draw/mana/removal the oracle text does not
have. Those need better prompting, not a looser schema, and that is the next lever.

## S7 & S8 — known, quantified, lower value

### S7 — the variance is real, and it is a compute problem. Here is the exact price.

I said this might need compute rather than cleverness, then tried the cleverness first. Worth
recording what did **not** work, because both attempts were plausible.

**Attempt 1 — the metric.** The bench total is a sum over a THRESHOLDED selection, and per-deck
deltas arrive in quantised lumps (a suggestion contributes ~7.3 or nothing). Suggestion count
swings 1–5 across seeds (sd 1.53 on mean 3.00, 51% relative) while delta-per-suggestion is a
stable 7.30 — so the count *is* the variance. That looked like a metric-shape problem.

**Attempt 2 — the threshold.** It turned out `min_delta` is not the binding constraint;
`effective_delta` floors at `_AXIS_NOISE_FLOOR`. So I measured that floor properly and found it
**genuinely wrong** (below), fixed it — and the bench spread did not move at all: **79–231
became 76–228**. The reported swaps sit around +7, far above even the corrected floor of ~4.
The threshold was never what gated them.

**What it actually is.** A swap's delta is the difference of two noisy analyses, so its error is
~√2× the axis sd — about **5 points at runs=60, against a ~7-point effect**. A 7±5 measurement
flips in and out between seeds no matter where the threshold sits. Measured directly: 4× the
runs took relative sd **59.9% → 40.6%**, close to the 1/√runs the theory predicts. Extrapolating,
**~16× the runs** (runs≈960) would be needed for ~15% relative sd.

**So the price is now known rather than guessed**, and the mitigation that works is the one
already in place: average across seeds and never quote one. Two changes landed:

- **Default seeds 4 → 8**, and the bench now reports the **standard error of the mean** and the
  **paired per-seed difference**. "spread 76–228" reads as *this number is meaningless*; the mean
  over 8 seeds is far better determined than any single seed, and the paired difference cancels
  the deck/seed noise both strategies share. A mean difference smaller than its own sem is now
  printed as **INCONCLUSIVE** rather than as a winner.

### The noise floor was wrong twice over *(fixed, independent of the above)*

Worth landing on its own even though it did not move the bench:

**It was measured at runs=150 while every caller uses runs=60.** Noise falls as ~1/√runs, so a
flat constant is correct at exactly one run count and was ~1.6× too low in practice. It now
**scales** with `cfg.runs` from a documented reference count.

**`resilience` was floored at 0.0, and that was an artefact.** The original sweep called
`analyze_deck` *without* `run_resilience`, so resilience was never simulated and returned a
constant — a clean 0.00 that read as determinism. It is only ever simulated when it IS the
target axis, which is exactly when the floor is consulted, and its real spread there is **1.24 at
runs=150, ~1.9 at runs=60**. A floor of zero meant every positive resilience delta passed:
resilience advice was unfiltered noise.

Measured spread against the old floors:

| axis | sd @60 | sd @150 | old floor |
|---|---|---|---|
| speed | 3.46 | 2.41 | 1.7 |
| ceiling | 2.44 | 2.98 | 2.3 |
| consistency | 1.40 | 0.89 | 0.9 |
| resilience | **1.91** | **1.24** | **0.0** |
| interaction | 0.00 | 0.00 | 0.0 |

Regenerate with `python scripts/axis_noise.py` (`--check` diffs against the baked values), in
the same idiom as `theme_base_rates.py` and `role_targets.py`. The old test re-implemented the
`max(min_delta, floor)` expression locally, so it could drift from the real function; it now
calls `_noise_floor` directly, and two new tests pin the scaling and the non-zero resilience.

### An "intermittent" test error that was neither intermittent nor contention *(fixed 2026-08-18)*

`tests/engine/test_advisor.py` errored twice under load and I twice put it down to resource
contention. It *was* contention — self-inflicted, and hiding a correctness problem.

`SemanticsStore()` **with no arguments** resolves `compiler.compiled_dir()`, which reads
`MYTHGAUNTLET_STORE`. On a dev machine that variable is set, so a fixture commented
*"empty → everything resolves at rung 1 (offline)"* was loading **31,042 CCMs in 7.5 seconds**:

- the rung-1 tests were running at **rung 2/3** against the real compiled store;
- **CI and a dev machine exercised different code paths** — CI has no store so it genuinely got
  rung 1, and `CLAUDE.md`'s stated invariant that the suite passes with no ccm store was only
  accidentally true;
- each instantiation re-read 31k files, which is where the `OSError` came from — it surfaced
  only when the suite ran beside another job walking the same store.

Five bare calls across two files now use a session-scoped `empty_store` fixture.
**Suite runtime 160s → 74s** (2.2×), and everything still passes at genuine rung 1, so nothing
was quietly depending on real semantics. Guarded by an emptiness assertion plus an **AST scan**
for bare `SemanticsStore()` — the failure is one of INTENT, since the call works fine and
merely does something other than what the surrounding test claims.

**Lesson worth keeping: a comment is not a test.** "Offline", "empty" and "synthetic" are
claims, and this repo now checks all three rather than asserting them in prose.
- **S8 Native `alert()`** for errors. The `Toaster` component already exists — this is a
  substitution at three sites.

---

## Offloading: the first diagnosis was wrong

The first sweep concluded that inferring an archetype from rules text is judgement and sits
outside what the local model can do. **That was a harness failure misread as a capability
limit.** The rebuilt harness lives in [`scripts/offload/`](../scripts/offload/README.md) with
the full post-mortem; the five faults were:

1. **`/no_think` on a reasoning model, and empty replies scored as an answer.** qwen3 spent the
   whole budget in the trace and returned empty content, which the parser recorded as the answer
   `none` — so every card came back unlabelled and it looked like the model refusing to judge.
2. **43 labels, a second output field, JSON, and 4 cards per call.** An A/B showed the model
   answers the *same* discrimination correctly (4/4, both sizes) when the question is narrow.
   The failure was task complexity per call.
3. **Undefined jargon.** `aristocrats` and `draw_matters` are this project's vocabulary, not
   English. Adding a glossary moved the gold set more than any prompt wording — and the
   definitions have to name Magic's *templating*, not just the concept.
4. **Loose definitions for base-rate-trap themes.** `voltron_combat` is STRONG on 19.35% of all
   cards; a loose definition makes it swallow anything mentioning combat.
5. **Interleaving two models.** llama-swap keeps one model resident, so alternating per card
   forced an unload+reload every item and 80 cards did not finish in ten minutes. Two passes
   cost two loads instead of a hundred and sixty.

**The two models fail in opposite directions, which is the useful part.** On the gold set
`qwen3:14b` is 1/4 at assigning a label and 4/4 at answering "none"; `qwen3:32b` is the mirror,
4/4 and 2/4. So the sweep runs both and trusts only agreement — 3/3 correct on gold, 4/4 on the
real run — and turns disagreement into a review queue. Over the 80 zero-theme commanders: **70%
agreement** (4 on a theme, 52 on "none"), **24 queued**, i.e. a review list a quarter the size
of the input.

Model output is still only a **candidate**: all four proposed themes were verified against
oracle text by hand before any pattern was widened. What the sweep buys is not judgement, it is
a much shorter list to judge.

---

## S15 — `bracket.py` was a second, unguarded authority on the same official-rules gate · DONE 2026-08-24

Surfaced auditing the codebase for the same failure class already fixed twice elsewhere
(trigger-event fabrication, `destroy all`/`destroy target` object confusion) while spec'ing the
Deck Mentor feature (`docs/SPEC_deck_mentor.md`) — the audit's brief was "find other places
making a rules-shaped judgment call with no ground truth to check it against," and root
`bracket.py` (the deck **builder**'s per-card gate, `BracketFilter.allows()`) turned out to be
exactly that, in two ways, in the one file:

1. **Game Changers were a hardcoded, dated frozenset (53 names, Feb 9 2026) with no staleness
   check**, while the engine's `ratings/bracket.py` (the deck **analyzer**) reads the identical
   quota live off Scryfall's own `game_changer` field via `data/scryfall.py`, which hard-fails
   on a stale schema by design — the exact "two opinions on one screen drifted" problem the
   engine merge (CLAUDE.md) already fixed once for bracket/strength ratings, just not for the
   builder's own gate. **Confirmed live 2026-08-24**: `/cards/search` — what `deck_builder.py`
   already calls for every candidate — returns `game_changer` on every result, so the fix costs
   nothing extra to fetch. It also caught a real latent bug the frozenset couldn't have: some
   printings of Tergrid, God of Fright report from Scryfall as
   `"Tergrid, God of Fright // Tergrid's Lantern"`, which an exact bare-name match silently
   misses and the live boolean does not.
2. **`_MLD_PATTERNS` was a bare substring check with no object gate** — `"each player destroys
   all"` matches any plural object, not just lands, so a card reading "each player destroys all
   artifacts they control" would have been wrongly read as mass land denial and pushed a casual
   deck to Bracket 4. The engine's own parallel implementation of this same pattern was already
   hardened for precisely this shape on 2026-08-07, validated against all 34,179 cards in the
   engine's store (see `ratings/bracket.py`'s own docstring for the fabricated/missed examples
   it names). This file now carries that same validated regex set rather than a second,
   unfixed copy — ported, not reinvented, so it inherits the existing validation rather than
   needing its own from scratch.

`BracketFilter.allows()` now prefers `card["game_changer"]` whenever the key is present and
falls back to the frozenset only when a card dict genuinely lacks it (synthetic/offline data)
— `.get()` returning `None` means "absent," not "false," so an explicit `False` from Scryfall
is never overridden by a stale name-list hit. Zero test coverage existed for this gate before
today; `tests/test_bracket.py` (10 tests) now pins both fixes, including the exact false-positive
shape named above and the object-blind old behaviour it replaces. Full suite (`tests`, excluding
`tests/engine`) re-run clean: **500 passed, 0 regressions.**

---

## S16–S19 — further rules-grounding gaps · S16/S17/S19 VERIFIED 2026-08-25, S18 still open

Same audit pass that found S15. All four were unverified leads as of 2026-08-18; this pass
re-checked each against the real 31,558-card compiled store and the 34,777-card Scryfall pool
rather than trusting the original description, and two of the four descriptions turned out to
be partially outdated.

- **S16 — RESOLVED IN PART, DOCUMENTED IN PART.** The original description ("X always resolves
  to a flat magnitude of 1") was already stale: `sim/tier2._EngineResolver` resolves X against
  live board state whenever a CCM effect carries an `x_basis` (creatures/permanents/lands/hand
  count) — a real capability added since the audit was written. `condition_holds` genuinely was
  still a hardcoded `True` in BOTH resolvers, and measuring its real impact found something
  worse than the original description: **15.78% of the store (4,981 of 31,558 cards) carry at
  least one conditional effect** (11.94% of all 49,431 effects), and a subset of those are
  actually a paired `if`/`otherwise` split within one ability — two MUTUALLY EXCLUSIVE outcomes
  compiled as two separate conditional effects. Defaulting both to `True` doesn't approximate
  generously, it credits both outcomes at once: **Approach of the Second Sun's win_game and its
  "otherwise" gain_life both fired on a single cast**, crediting the simulation with an outright
  win on turn one for a card that actually requires casting it twice. Fixed: `condition_holds`
  now returns `False` for a bare `"otherwise"` condition, in both `interpreter.DefaultResolver`
  and `sim/tier2._EngineResolver` — the IF branch stays assumed-true (unchanged, consistent with
  the engine's optimistic-default philosophy elsewhere), the paired OTHERWISE branch no longer
  fires alongside it. Measured scope: **24 cards store-wide** (0.08%) carry an otherwise-branch,
  several high-profile (Approach of the Second Sun, Oko the Ringleader, Jace the Perfected
  Mind, Faramir Prince of Ithilien) — small in count, high in per-card severity. Pinned by
  `test_default_resolver_does_not_fire_the_otherwise_branch` / the matching tier2 test.
  **What's still open, honestly:** an ordinary (non-paired) conditional effect — "if you control
  a Dragon, draw two cards" — is still assumed true regardless of board state. That's the
  larger, harder remainder of S16 (a genuine board-state check would need a bounded vocabulary
  the way `x_basis` has one for X, not a general condition parser) and is NOT fixed by this
  pass — only the specific, provably-wrong double-credit case is.
- **S17 — PARTIALLY WIDENED, ONE ATTEMPTED FIX REVERTED.** `combo_rules.classify_determinism`
  itself is honestly designed (its own docstring already says "does NOT prove determinism"),
  so the real question was whether its marker vocabulary has real, verifiable gaps. It did:
  **Fact or Fiction** ("An opponent SEPARATES those cards into two piles") was missed outright
  because the opponent-choice marker only matched the verb "chooses". Widened to
  separates/picks/selects, verified against every one of the 8 real cards in the store using
  those verbs near "opponent" — zero false positives. A SECOND widening (matching "in a random
  order" to catch Possibility Storm's real non-determinism) was tried and **reverted**: it also
  flagged **Thassa's Oracle** — one of the most iconic, fully deterministic cEDH win conditions
  — as non-deterministic, because "put the rest on the bottom in a random order" is common,
  benign anti-stacking templating unrelated to whether the effect's actual outcome (a pure count
  comparison) is deterministic. Reverted rather than shipped; pinned by
  `test_benign_random_order_of_unchosen_cards_is_not_flagged` as the non-regression case.
  Possibility Storm's own randomness, and Chaos Warp's ("shuffles... reveals the top card",
  random in effect but never uses the word "random") remain uncaught — documented as residual
  gaps rather than guessed at with an unproven pattern.
- **S18 — COMMANDER DAMAGE FIXED 2026-08-25; LEGEND RULE FOUND NOT APPLICABLE.** Full writeup:
  `docs/SPEC_commander_damage.md`. A player taking 21+ combat damage from a single opposing
  commander now loses (CR 704.5a), wired into the T2 state machine at the one shared damage-
  application site (`_apply_declare_blocks`) and all four existing win-check call sites,
  behind one shared `commander_damage_lost()` helper rather than a duplicated threshold at
  each site. **Verified two ways.** The golden master (`tests/data/tier2_golden.json`,
  93 synthetic scenarios) was deliberately regenerated: exactly ONE scenario changed —
  `commander_recast` (a 5/5 commander vs. an aggro deck) flipped from a 40-0 blowout to
  `wins_a: 8, wins_b: 32`, which is the S18 gap made concrete (a 5/5 connecting unblocked
  reaches 21 damage on its 5th swing, a kill the old engine structurally could not see); the
  other 92 scenarios are byte-identical, confirming the blast radius is exactly the
  commander-damage path. Then a live, real-corpus check: `mythgauntlet gauntlet --opponents 3
  --games 10` — **10,240 real T2 games, zero crashes** (the run's only errors are an
  unrelated external Commander Spellbook API rate limit, not this change). New unit tests in
  `tests/engine/test_game.py` pin the exact threshold, clone independence (a field missing
  from MCTS's own state-clone silently stops existing under search while staying real at the
  root — checked, and added correctly), blocked-vs-unblocked accrual, and that a
  non-commander dealing the same raw damage does NOT trigger it.
  **The legend rule half is NOT a live gap and was not implemented, for a checkable reason**:
  the engine has no clone/copy-effect modeling anywhere, so no code path can ever put two
  same-named legendary permanents on one battlefield — the state-based check's own
  precondition cannot occur under the current card-effect model. Not deferred; not
  applicable until clone effects are a modeled mechanic, which is real, separate, larger
  future work. **Still open, documented in the spec**: partner-commander damage isn't
  tracked per-source-commander (this engine already simulates a second commander as an
  ordinary library card, not a dedicated attacking permanent, so this inherits rather than
  introduces that gap), and `score()`/`score_reward()` (turn-cap adjudication, MCTS rollout
  evaluation) don't read accumulated commander damage — the win condition now fires
  correctly, only the search heuristic doesn't yet see progress toward it before the kill.
- **S19 — AUDITED, NO REAL INSTANCES FOUND.** Swept all 23 real cards in the 34,777-card store
  matching `_COUNTER_RE` ("counter target ... spell") for a nearby "can't be countered" clause
  that would make the tag a false positive. Zero found. The originally-suspected failure shape
  doesn't manifest against the real card pool — closed as a non-issue, not left open.

---

## S20 — ~~Partner-commander build is 99+1, not a legal 98+2~~ · DONE 2026-08-25

**Found via the mentor campaign's round 6** (see `MENTOR_HANDOFF.md`), while verifying S2's
"Tymna + Thrasios → HTTP 200, a WBGU deck" claim more deeply than build-success. S2's OWN fix
(that round) closed how every downstream consumer *reads* a partner pair's identity — but
building one was never actually checked against what a legal Commander deck requires.

A real Commander deck with two partnered commanders has **100 cards total: 2 in the command
zone + 98 in the library.** `DeckBuilder.build()` always drafted exactly **99** library cards
regardless of partner count (the literal `99` was hardcoded at ~20 internal call sites — plan
normalization, the creature floor, the 99-card guarantee tail — see `CLAUDE.md`'s own extensive
history of bugs in exactly this arithmetic), and the generate path never added the second
commander into `deck` at all (the import path already did, for exactly this reason —
"Partner/companion commanders aren't the face — render them as cards"). A generated Tymna +
Thrasios build shipped **99 library cards + 1 commander (Tymna) = 100 cards**, with Thrasios
entirely absent from the persisted deck, export, render, and card count — not a
slightly-imperfect partner deck, a single-commander deck built against a widened identity.

**Fixed the same session**, once a way to measure it existed. `build()` gained a
`partner_count: int = 0` parameter; every one of the ~20 internal `99` literals inside `build()`
and `_normalize_plan` now reads a `library_size = 99 - partner_count` computed once at the top
— a mechanical, single-purpose substitution, not a rewrite of the arithmetic itself, chosen
specifically to keep the blast radius small against a method with a documented regression
history. `partner_count` defaults to 0, so every existing single-commander call site (including
the fixed 20-commander `builder_bench.py` roster) is byte-for-byte unaffected — verified by
re-running the roster and diffing against the committed baseline: the only two rows that moved
(`valid`/`colors_ok` 20→19) were a live Scryfall rate-limit on one unrelated commander that
session, not a code effect, and every per-commander synergy figure that DID drift by a fraction
of a point tracks live EDHREC-lift data staleness, not this change (`_normalize_plan`'s own
existing tests, which never pass a `target`, are untouched). Both server call sites
(`/api/deck/build`'s generate branch and `/api/deck/generate-list`'s phase 1) now pass
`partner_count=len(partners)` and append the partner card(s) into `deck` afterward — mirroring
the import branch's exact convention — landing on `library_size + partner + face = 100`.

**The measurement gap this needed is now permanent, not one-off.** `builder_bench.py` gained a
`--partners` arm (`PARTNER_PAIRS`, kept deliberately SEPARATE from the fixed, baseline-comparable
`ROSTER`) that checks the three things that were wrong: library size is exactly
`99 - partner_count`, the partner is actually present in the returned deck, and the total lands
on 100. Run live against two real, structurally different pairs — Tymna the Weaver + Thrasios,
Triton Hero (WBGU) and Vial Smasher the Fierce + Kraum, Ludevic's Opus (BRU, near-disjoint
identities sharing one colour) — both came back `library=98 total=100 partner_in_deck=True
colors_ok=True`. Reference run committed at `docs/bench/partners-s20-fix.json`. Also verified
live through the actual running app (`/api/deck/build` → poll → fetch): the persisted deck.json
holds 99 deck-array entries (98 library + Thrasios, itself a fully themed/rendered card with its
own art, name and flavor) + 1 commander = 100, `quality.colors.ok: true`.

New tests: `tests/test_deck_builder_curve.py::test_normalize_plan_honours_a_smaller_target_for_a_partner_commander`
pins `_normalize_plan`'s `target` parameter directly (offline, no network) — the `builder_bench`
live check above is the end-to-end proof; this is the fast regression guard for the arithmetic.

---

## S21 — A fast, genuine engine can't reach Bracket 4 while it has ≤3 Game Changers · DONE 2026-08-26

**Found from a live, real-world counter-example, not the corpus.** The user's own "Prismari,
the Inspiration" spellslinger/storm deck (a real Archidekt list, `inspire_table_salt`) is rated
Bracket 4 by its own playgroup on speed and consistency alone. This engine measured it
accurately in every other respect — `speed_avg_kill_turn: 4.73`, `speed_kill_rate: 1.0`,
`go_off_turn: 5`, `consistency: 78.7` — but reported **Bracket 3**, because `estimate_bracket`'s
gate for 0-3 Game Changers is a FIXED point (`floor, cap = 3, 3`), not a band: once a deck's
combo/go-off gate lands it at Bracket 3, nothing measured about its speed could ever move it
further, no matter how fast it actually kills.

**The first hypothesis (missing Game Changer flags) was checked and refuted, not assumed.**
Ancestral Recall, Dockside Extortionist and Jeweled Lotus looked like plausible mis-flags at
first glance; queried live against Scryfall's own API (not our cache), all three genuinely are
`game_changer: false` today. Our local card store was independently found to be 28 days stale
(a real, separate finding — refreshed via `mythgauntlet fetch-data`, though note the ambient
shell's `MYTHGAUNTLET_DATA` env var points at the OLD pre-merge sibling repo
`Documents\mythgauntlet\data`, not this repo's `data/`; the refresh must override it explicitly
or it silently updates the wrong store — a live instance of the exact CWD/env-relative-path
trap `app_paths.py` exists to prevent on the Forge side). The refresh changed nothing about the
Game Changer flags in question — 53 cards flagged before and after. **Game Changers really is
0 for this deck, correctly.**

**`axis_separation.py` was re-run and the obvious "just weight speed more" fix is WRONG at
corpus scale**, exactly the caution this project applies everywhere: `game_changers` is still
the single strongest B3-vs-B4 signal (Cohen's d **+1.44, STRONG**), and speed/kill-turn signals
are flat across the *whole* ladder (`nut_draw_turn` rho -0.12, `kill_rate` rho +0.03, never a
top-4 signal at any boundary). A population-wide speed-based escalation would have been shipped
on bad evidence.

**The reason the population-wide test is silent: the corpus has almost no data in the exact
cell that matters.** Of 297 labelled decks, only **3 ever go off at all** (`can_go_off=True`),
and **none are labelled Bracket 4** — the population test cannot see a signal that only exists
in a population it doesn't contain. This is an honest data-scarcity finding, not a reason to
give up: it means the fix has to come from the guideline text itself, verified not to disturb
the 3 anchors that do exist, rather than from a corpus-fit that has no B4-go-off examples to
fit against.

**The fix is guideline-derived, not corpus-fitted, and says so.** The bracket document the user
supplied states explicit turn-count floors: Bracket 3 promises opponents "at least six turns
before you win or lose," Bracket 4 "at least four." `estimate_bracket` already accepted an
`avg_kill_turn` parameter and never used it (dead since the function was written). Wired in:
when `can_go_off` and the deck's REALIZED average kill turn (not `estimate_go_off`'s own
best-case ceiling number — the goldfish-clock figure `apply_nut_kills` already teaches to see
this exact kill pattern) is under six, a gc≤3 deck escalates from the fixed Bracket-3 point to
a Bracket-4 floor instead. **Verified not to move any of the 3 real anchors** (7.98 / 8.00 /
10.17, all comfortably clear of six) **and confirmed to fix the 1 concrete case it targets**
(4.73). `scripts/bracket_accuracy.py`'s full 297-deck sweep is therefore mathematically a
no-op under this change — reran it anyway rather than trust the proof alone: **identical
53.9% exact / 91.6% within-one**, zero decks moved.

**Verified live, end to end**, not just in the pure function: re-fetched the real decklist
through `/api/deck/import-preview` (the exact route "Analyze a Deck" calls) before and after —
`bracket_estimate: 3` → `bracket_estimate: 4`, with the new reason line
`"go-off engine converts by turn 4.8 on average, under Bracket 3's own six-turn floor -> min
Bracket 4"` alongside the pre-existing reasons.

**What this is explicitly NOT**: a statistically powered fix. N=1 real-world case plus 3
non-firing anchors is a small evidence base, recorded as exactly that in the code comment. It
is also **narrow by design** — it only ever fires for a verified `can_go_off` engine (a rare
population: 3/297 corpus decks), so it cannot mis-fire on an ordinary midrange goodstuff pile
whose average kill turn happens to be fast for unrelated reasons. Growing this specific cell
(`mythgauntlet fetch-decks --bracket 4` biased toward spellslinger/storm commanders) is the
natural next step if it needs re-validating at scale.

**A separate, larger, still-open finding from the same accuracy sweep, NOT addressed here**:
Bracket 4 recall is 41.2% (9/17 author-labelled B4 decks are called B3 by the engine) and
Bracket 1 recall is 44.3% — most of that gap is almost certainly NOT storm/go-off decks (only
3 corpus decks touch that mechanism at all) but ordinary decks the Game-Changer gate under- or
over-calls for reasons this fix does not touch. This is the same shape as the already-documented
"B2/B3 is not resolvable from the 99 cards" finding, one boundary over, and deserves its own
`axis_separation.py`-style investigation rather than being folded into this fix.

Tests: `tests/engine/test_bracket.py` — `test_fast_go_off_engine_escalates_past_bracket_3`
(pins the exact real numbers), `test_slow_go_off_engine_stays_at_bracket_3` (the 3 real anchors,
unaffected), `test_fast_go_off_does_not_override_a_higher_gate` (a GC-driven Bracket 4+ verdict
is untouched), `test_missing_avg_kill_turn_does_not_crash_or_escalate` (a caller that doesn't
measure it degrades safely).

