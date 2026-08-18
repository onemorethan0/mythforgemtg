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
| S1 | Commander themes undetected | **80 / 391 (20.5%)** | **High** | M |
| S2 | Partner decks cannot be BUILT | **33 / 483 (6.8%)** | Medium | M |
| S3 | Population-relative labels read as absolute | 1 of 5 fixed | **High** | S |
| S4 | Off-meta read too sparse to judge | **12.6%** `insufficient-data` | Medium | M |
| S5 | Dead entries in the theme taxonomy | **3 of 43** never fire | Low | S |
| S6 | Engine card coverage | **31,028 / 34,179 (90.8%)** | Medium | L |
| S7 | Advisor seed variance exceeds its effects | 79–231 on one deck set | Medium | L |
| S8 | Errors surface via native `alert()` | 3 sites | Low | S |

---

## S1 — 20.5% of commanders detect no theme *(highest value)*

**Measured.** 80 of 391 unique corpus commanders return `[]` from
`commander_analysis._detect_themes`. Their ~20 theme slots then fall through to generic
goodstuff, so the builder is blind to the deck's whole point. Deck-context themes
(`deck_themes`) rescue **41 of the 74** that appear as a deck lead (55%) — leaving **45% with
no archetype from either source**.

**This is under-stated by the corpus.** In the user's own seven-deck pod, **3 of 7 commanders
(43%)** detect nothing: Witherbloom, the Balancer · Vorel of the Hull Clade · Avatar Aang.
Avatar Aang is a transforming commander, a shape the taxonomy has no read on at all.

**Prior attempt, and why it only got so far.** Widening existing patterns was measured at
~5 more commanders and correctly left undone. The remaining gap is **not** more regex on the
same 43 themes — it is archetypes with no entry.

**Plan.**

1. **Generate candidates with the method that already worked — not with the local model.**
   `face_down`, `sagas` and `impulse` were found by **distinctive-bigram analysis of the
   zero-theme commanders' oracle text against a baseline**: deterministic, offline, no LLM.
   Re-run exactly that over the 80 in `shortfall_zero_theme.json`. The local-model sweep was
   tried this session and **did not earn its place** — see the offload note at the end.
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

## S3 — A population-relative label still reads as an absolute claim

**Measured.** All five off-meta verdicts are quadrants of a 2×2 cut at **population medians**,
so each is a statement about *other decks*. `off-plan` was fixed this session — its blurb was
false for 80% of the decks it fired on, at 24.8% of all decks.

**`brew` is the same shape and is still shipped.** "Using the commander as a backbone for
something else" fires on 19.3% of decks with a **median 77.0% of measured cards on positive
lift**. That is defensible but it is the same trap, and it was left alone deliberately rather
than by oversight.

**Plan.** Cheap and worth doing before it bites:

1. Re-read all five blurbs against their measured quadrant statistics (the cross-tab is in
   `HANDOFF.md` §9) and rewrite any that assert something absolute.
2. Extend `test_off_plan_wording_does_not_claim_the_deck_lacks_synergy` into a table-driven
   check over **every** verdict, so the guard is not one-off.
3. Show the reader the relativity directly — the panel already prints `typical here +6.5`,
   which is the honest frame; consider making that comparison the headline rather than the label.

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

## Honest note on offloading this work

Per standing practice the bulk labelling for S1 went to the local stack (`qwen3:14b` on
llama-swap `:8010`). **A gold set was run first, and it is why the output is used the way it
is.**

Hand-labelled 8 of the 80 from their oracle text, then scored the model against them:

| round | exact | note |
|---|---|---|
| first prompt | **2 / 4** | one batch also returned malformed JSON |
| + worked examples on the observed confusions | **5 / 8** | |

It is **reliable on the negative case** — 4/4 when the correct answer is "no theme in the
vocabulary fits" — and **unreliable at assigning labels**: it read *Agent of the Iron Throne*
("whenever an artifact or creature you control is put into a graveyard from the battlefield,
each opponent loses 1 life") as `graveyard` rather than `aristocrats` **even after a worked
example described that exact wording**, and called a sacrifice outlet `draw_matters`.

So its labels were **not** used as ground truth — feeding 80 near-miss labels into
`THEME_PATTERNS` would inject precisely the defect class this project forbids. The fallback
plan was to use it only as a **candidate generator** for missing archetypes, where a wrong
suggestion costs a discarded candidate rather than a wrong card in someone's deck.

**That fallback also failed, and the sweep is recorded here as a negative result.** All 80
were swept (79 returned). Of the nominations for archetypes *missing* from the vocabulary:

- the **most frequent were already in the vocabulary** — `draw_matters` (3), `tokens` (2),
  `reanimator`, `graveyard`, `lifegain` — a straight violation of the one instruction that
  defined the field;
- the genuinely novel names were a 21-long tail at count 1, mostly not archetypes at all:
  `autostubs`, `disappear`, `warp`, `nightmares`, `villainous`, `legendary`, `mana`;
- the few real ones (`defenders`, `mill`, `eldrazi`) each appeared **once**, and `defenders`
  I had already found by hand-labelling 8 cards.

**Net: eight hand-labels produced more usable signal than the 80-card sweep.** The honest
conclusion is that this task — "infer an archetype from rules text" — is *judgement*, not
extraction, and sits on the wrong side of the line for this model. S1's plan reverts to the
deterministic bigram analysis that actually found the last three themes.

Where the local stack **is** worth the VRAM on this codebase: drafting a self-contained module
from a precise spec (it drafted `collection_pool`, `deck_quality`, `theme_match`), and
closed-vocabulary extraction where the vocabulary is unambiguous. Not this.
