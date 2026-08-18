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

| # | Shortfall | Measured | Casual impact | Effort |
|---|---|---|---|---|
| S1 | Commander themes undetected | corpus **64/391 (16.4%)** ↓80 · all legends **946/3790 (25.0%)** ↓963 | **High** | part done |
| S2 | ~~Partner decks cannot be BUILT~~ | **built + validated** | **Done** | — |
| S3 | ~~Population-relative labels~~ | **audited, 5 of 5** | **Done** | — |
| S4 | Off-meta read too sparse to judge | **12.6%** no verdict · band shipped | part done | M |
| S5 | ~~Dead entries in the theme taxonomy~~ | **3 of 3 cleared** | **Done** | — |
| S6 | Engine card coverage | **31,028 / 34,179 (90.8%)** | Medium | L |
| S7 | Advisor seed variance exceeds its effects | 79–231 on one deck set | Medium | L |
| S8 | ~~Errors via native `alert()`~~ | **already fixed** — entry was stale | **Done** | — |

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

1. Measure whether EDHREC exposes more of the page than `edhrec_lift` currently parses
   (themes/budget sub-pages carry additional cards). **Verify the shape against the live
   endpoint before writing any parser** — this repo has been burned by an assumed API shape.
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

`tribal_beasts` is unresolved, and the honest reason is that **my three exemplars were bad
tests** — Ghalta is a big creature, Kogla is an Ape, Nemata makes Saprolings; none of them is
a Beast-*tribal* payoff. The open action is to find a commander that genuinely rewards Beasts
as a tribe and re-test. Note Kogla returned `[]` entirely, so it is also an S1 case.

**Remaining plan.** Retest `tribal_beasts` properly; annotate the other two as
deliberately-rare in `THEME_PATTERNS` so their zero counts stop looking like the dead-rule
signature.

---

## S6 — 9.2% of cards have no compiled semantics

**Measured.** 31,028 compiled CCMs against a 34,179-card store — **3,151 cards (9.2%)** fall
back to rung-1 Oracle-text heuristics. (Note: the store is present and full-fidelity locally
via `MYTHGAUNTLET_STORE`; the "withheld" note in `ENGINE_DATA.md` is about what *ships*.)

**Plan.** Continue the existing overnight compile; no new mechanism needed. The one worthwhile
change is **reporting**: surface per-deck semantic coverage the way the off-meta read surfaces
EDHREC coverage, so a bracket derived from a deck where a third of the cards are rung-1 is
visibly less certain. A confident bracket over uncompiled cards is the same fabrication class
as S3 and S4.

---

## S7 & S8 — known, quantified, lower value

- **S7 Advisor seed variance (79–231)** swamps the effects being measured. `advisor_bench` is
  multi-seed by default, which is the correct mitigation; genuinely narrowing it means more
  sims per evaluation, i.e. compute, not cleverness. Do not quote single-seed numbers.
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

