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
| S1 | Commander themes undetected | **75 / 391 (19.2%)** ↓ from 80 | **High** | M |
| S2 | Partner decks cannot be BUILT | **33 / 483 (6.8%)** | Medium | M |
| S3 | ~~Population-relative labels~~ | **audited, 5 of 5** | **Done** | — |
| S4 | Off-meta read too sparse to judge | **12.6%** `insufficient-data` | Medium | M |
| S5 | ~~Dead entries in the theme taxonomy~~ | **3 of 3 cleared** | **Done** | — |
| S6 | Engine card coverage | **31,028 / 34,179 (90.8%)** | Medium | L |
| S7 | Advisor seed variance exceeds its effects | 79–231 on one deck set | Medium | L |
| S8 | Errors surface via native `alert()` | 3 sites | Low | S |

---

## S1 — 19.2% of commanders detect no theme *(highest value, partially landed)*

**Measured.** **75** of 391 unique corpus commanders return `[]` from
`commander_analysis._detect_themes` — down from 80 after the two fixes below. Their ~20 theme
slots fall through to generic goodstuff, so the builder is blind to the deck's whole point.
Deck-context themes (`deck_themes`) rescue **39 of the 69** that appear as a deck lead (57%),
leaving **43% with no archetype from either source**.

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

**Three patterns widened**, each from a commander the offload ensemble flagged and I verified by
hand: `spellslinger` gained `"instant and sorcery spells you cast"` (cost reduction IS the
payoff — Baral detected nothing), `artifacts` gained the plural and artifact-creature phrasings
plus `"an artifact card"` (Alibou, Tony Stark), `graveyard` gained `"in all graveyards"` and
`"each player mills"` (Coram). Over-fire checked: 6 / 47 / 9 legends newly detected, spot-read
and correct — the 47 is `"artifacts you control"`, which `CLAUDE.md` had already flagged as the
known gap.

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

---

## S2 — Partner decks can be analysed but not built

**Measured.** 33 of 483 corpus decks (6.8%) have 2+ cards in the command zone.

Analysis is already correct — `command_zone_identity` unions the identity and the themes, which
flipped 16 decks from "cannot cast itself" to castable. What does not exist is the **build**
path: `BuildRequest.commander_name` is a single string and there is no second-commander UI.

**Plan.**

1. `BuildRequest.partner_names: list[str] = []` (a list, not a second scalar — Background,
   *Friends forever* and *Choose a Background* all fit the same field).
2. `_run_build` resolves them and hands the pair to `build_commander_profile(card, partners)`,
   which **already** takes `partners` and does the right thing. This is wiring, not new logic.
3. `StepCommander` gains an optional second search box, shown only when the chosen commander's
   oracle text names a partner mechanic (`Partner`, `Partner with`, `Friends forever`,
   `Choose a Background`, `Doctor's companion`) — so it never appears for the 93% that can't
   use it.
4. Validate the pairing server-side and **refuse an illegal pair with a clear message**; an
   illegally-built deck is worse than one the user has to fix.

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
2. If coverage cannot be raised, report the figure as a **confidence band** on the synergy
   number rather than a bare percentage, so a 27%-coverage reading visibly carries less weight.
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

