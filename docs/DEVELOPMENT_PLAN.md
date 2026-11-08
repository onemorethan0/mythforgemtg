# Myth Forge: continuing development plan (from the 2026-11-07 review)

The map is the 2026-11-07 full review (local `docs/REVIEW_2026-11-07_full.md`; its findings are
summarised in `STATUS.md` section 0) and the earlier deck-building review
([`DECKBUILD_REVIEW.md`](DECKBUILD_REVIEW.md), B14-B18). This file turns both into one ordered plan.
Item IDs continue [`BACKLOG.md`](BACKLOG.md)'s numbering; when an item moves, update its row here
and its status in STATUS.md.

## Direction in one paragraph

Myth Forge is already ahead of every public deck site at **understanding** a deck (simulation,
bracket with reasons, mentor, measured upgrades) and at **making** one (auto-build, theming, art).
It was behind on the **everyday mechanics** those sites are built around; the review closed the
first three (legality, sample hand, manual edit). The direction from here is: finish that parity
where it serves a casual pod (what does this deck cost, what am I missing, export it where my
friends play), then make the builder **check its own output** against the plan it was asked for,
and only then restructure the large files. Every step is judged against the standing goal: casual
Bracket 1-3, "is this deck fun and on-level for my pod". A wrong card model is a defect.

## Principles (each one cost real time when it was skipped)

1. **Measure before changing.** Each item names the number that says it worked. A clause or
   threshold changes only with a before/after table over real data (the oracle bulk, the corpus,
   the bench, or the user's saved library).
2. **Fix the class, not the instance.** When a bug has a twin (two classifiers, two exports, five
   copies of a conversion), fix all of them and pin it with a test that fails on the twin.
3. **Live-check anything that leaves the process.** A rewritten Scryfall query is run against
   Scryfall before commit (the 2026-11-07 protection rewrite leaked colour identity and only the
   live check caught it).
4. **Never test destructively on a real deck.** Duplicate, test, delete the copy.
5. **Offload only self-contained, non-rules modules**, and read every draft (the record is still
   1-2 real bugs per drafted file). Rules-facing work stays with Claude.

## The plan

Status: `todo`, `doing`, `done`, `deferred`. Owner as in BACKLOG.md (C / N / U).

### Phase 0: re-baseline (no behaviour change)

| ID | Item | Accept | Status |
|---|---|---|---|
| B19 | Re-run `builder_bench.py` after the role-query audit and compare with `docs/bench/current.json` | the comparison table recorded below; no degraded builds; any metric that moved > noise explained | **done** (see log) |

### Phase 1: everyday parity that serves a casual pod

| ID | Item | Why | Accept | Status |
|---|---|---|---|---|
| B20 | **Deck price**: total value, and the cost of what you don't own | the first number Moxfield/Archidekt show; for a casual player "what do I still have to buy" is the real question | deck page shows total and to-acquire USD, card count priced vs unpriced (never a silent partial sum), owned cards from the collection's own printing-faithful prices; works offline from cache | **done** |
| B21 | **Legality fix-it**: one action on a flagged deck that removes off-identity / banned / extra copies and refills legally | the check now flags 22 of 136 saved decks (Marchesa, old Tymna builds) and offers no way out | a flagged deck becomes legal in one call; a duplicate-deck test; refill respects the bracket and identity | **done** |
| B22 | **Persist printings on deck cards** (set, collector number, finish) at build and import | known open since 2026-10-07: the "exact deck printing" rule is inert; blocks B23 | stored deck cards carry set + collector number; import keeps the source deck's printing | todo |
| B23 | **Export formats**: Arena / MTGO-style `1 Name (SET) 123`, CSV | friends play on different sites; plain text already round-trips | each format round-trips through our importer; Moxfield and Archidekt accept the text format | todo (after B22) |
| B24 | **Considering pile (maybeboard)**: park candidate cards on a deck, promote with a swap | how people actually tune a deck between games | add/remove/promote; never counted in legality, strength or stats | todo |

### Phase 2: the builder checks its own work (casual B1-3 core)

| ID | Item | Why | Accept | Status |
|---|---|---|---|---|
| B25 | **Role coverage report** on every build: count the 99 with the shared classifier, compare with the slot plan, record in deck.json and the build log | the build is open-loop (DECKBUILD_REVIEW F3); the builder cannot see that a "removal" slot drew a non-removal card | `stats.roles` = planned vs got per role; under-supplied roles named in the UI | todo |
| B26 | **One role vocabulary** (B16): role candidates from Scryfall must also pass the shared classifier for that role | the query and the classifier now share gates (2026-11-07) but are still two judges; the draw clause admits cycling reminder text | measured: bench role counts move toward plan, no slot left unfilled, classifier misses checked by hand first | todo (after B25) |
| B27 | **Data-driven slot plan + land count from the deck's curve** (B16 / P4) | one fixed recipe for every commander; land count by commander MV only | one resolver replaces five mutations; goldfish land/screw/flood no worse on the bench | todo |
| B15 | remaining: general close-the-loop repair (P2) beyond combos | | | deferred (P2 power trim measured no effect) |

### Phase 2b: the deck scouting report (owner request, 2026-11-07)

Full spec, live-verified field inventory, gaps and acceptance tests:
[`SPEC_deck_scouting_report.md`](SPEC_deck_scouting_report.md). When a deck is rated, say what it is
good at, what it is weak against, its strong and weak cards and combos, how fast it kills one
player and the table, and how. Every sentence backed by a number measured on that deck, judged
against decks of the same bracket.

| ID | Item | Closes | Status |
|---|---|---|---|
| B30 | Per-card telemetry from the goldfish games already played (cast rate, stranded rate, kill-turn uplift when seen early, with intervals) | which cards carry / which are dead | **done** |
| B31 | Strong and weak cards, named only past the measured noise floor | strong/weak cards | **done** |
| B32 | Kill speed as a distribution (p25/median/p75); table speed from the measured four-seat sim, capacity as secondary | speed vs 1 player and the table | **done** |
| B33 | Combos on the clock: assembly probability by turn (draws + tutors + mana), combined clock | combos, real kill speed | **done** |
| B34 | Kill-method attribution (combat / commander damage / drain-burn / combo / alt-win) + top damage cards, in tier0 and T2 | methods it relies on | **done** |
| B35 | Reference field per bracket (one deck per archetype from the corpus) and matchup win rates | weak against (games) | todo |
| B36 | Exposure to hate: graveyard, commander, artifacts, flyers, single combo, mana base, speed vs peers | weak against (static) | todo |
| B37 | Strengths/weaknesses as per-bracket percentiles instead of fixed bars | good at (honestly) | **done** |
| B38 | `/scout` report: template-first text, optional LLM paragraph behind the swap_narrative-style gate; Forge panel | the description | todo |

Follow-up owed by B31 + B34 (both changed what the sim counts): re-fit the strength model's
bracket cut lines (`scripts/bracket_strength_fit.py --collect`, then `--bake`).

Order: B30 -> B34 -> B32/B33 -> B37 -> B36 -> B35 -> B38. First measurement before B30 ships: the
per-card noise floor (it decides how many cards the report can honestly name).

### Phase 3: measurement that can see strength

| ID | Item | Accept | Status |
|---|---|---|---|
| B17 | Strength-aware builder bench (P5): engine bracket/axes per build, EDHREC synergy secondary | a change that raises synergy but lowers strength shows red | todo |

### Phase 4: structure and hands-on UX

| ID | Item | Accept | Status |
|---|---|---|---|
| B18 | Split `StepDeck.jsx` (1,720 lines) and `api/jobs_build.py` (1,130); component tests for the wizard | no build-path file over ~600 lines; suite green at each step | todo |
| B28 | Hands-on UX pass at desktop and phone widths (P7); replace native `alert()` with the toaster | defects filed here; zero `alert(` in src | todo |
| B29 | Frontend bundle > 500 kB: code-split the heavy panels | Vite warning gone; first paint unchanged or faster | todo |

## Order and why

**Updated 2026-11-07:** B19-B21 are done. The scouting report (Phase 2b) is now the priority, at
the owner's request; B25 (role coverage report) can run beside B30, since both add measurements
to a build without changing it. The rest of the original order below still holds.

B19 first (it is the baseline every Phase 2 item is judged against), then B20 and B21 (cheap,
visible, and the legality check created the need for B21), then B25 before B26 (you cannot unify
two judges until the build reports what the judge saw). B22 -> B23 are a pair. Phase 3-4 follow;
B18 can be taken in slices whenever a file is being edited anyway.

## Progress log

Newest first. One line per change, with the commit.

- 2026-11-08: **D4 done: pod check.** `ratings/pod_fit.py` + engine `/pod-fit` + Forge `/api/deck/{id}/pod-fit` + a "Pod check" panel (library decks or pasted lists). Power / pace / denial / predictability, each ok-warn-fail with a sentence for the pre-game talk. Live: three B3 library decks + a pasted Oloro combo deck -> lopsided, naming Oloro. Next: D5 (multiplayer reactions in the pod sim) to test the predictions, or B36.
- 2026-11-08: **D3 done: Denial / Pace / Inevitability dials** (`ratings/dials.py`, `/analyze` `dials`, chips under the bracket badge with reasons). Denial High: 2-7% of B1-3, 61% of B5. Pace by shares of games ended by T6/T10 (a median read nothing Fast). Inevitability High: 0% of B1-2, 52% of B5. Known limit: the goldfish under-times cEDH, so Pace reads Fast for only 20% of B5. Next: D4 pod fit, or B36.
- 2026-11-08: **D2 done: lock pieces and denial roles.** `ratings/denial.py` names lock pieces in six kinds (untap, spell/draw limit, attack, can't-lose, ability) from object- and scope-gated text, plus counterspells, lasting theft, extra turns and land denial; 58 Commander-legal locks, every one reviewed; 37-card gold set. `/analyze` `denial` block and a "What it denies other players" panel. Casual decks rarely run counters (median 0 at B1-2), so one control deck faces none back. Next: D3 (Denial/Inevitability dials) or B36.
- 2026-11-08: **D1 done (table brackets design): the mass-land-denial gate reads Wizards' whole definition.** Keep-tapped and mana-change cards now count (Winter Orb, Static Orb, Stasis, Blood Moon, Back to Basics, Contamination, ...; +13 cards); Pox and planeswalker ultimates no longer do (-2), nor do extra-turn ultimates and skip-then-take turns (-6). Engine and Forge copies stay identical (pinned by a test). Labelled decks whose gate changed: exact vs label 36 -> 50 of 76. Label audit gains mass land denial (2,112 labels kept). Next: B36, or D2 (Lock list + denial tagging).
- 2026-11-08: **B37 done; labelled corpus 624 -> 2,122 with every label audited against the official gates.** Strengths/weaknesses are the top/bottom quarter of the deck's labelled bracket peers, each line led by the absolute verdict word (`insight.absolute_band`) so the mentor cannot turn "lower than most peers" into "vulnerable"; 22/25 strength cells fire for 15-35% (fixed bars: 12/25); mentor bench unchanged against a same-day baseline. Corpus: 178 WotC precons (B2) + 1,508 Archidekt decks; 188 labels demoted (Game Changers past the limit, two-card infinites at B1-2). Strength model holds on 3.4x the decks (exact 60.1%); refit not baked (B1 recall cost). Forge: kill/combo clock panel; the player's stated bracket beside ours, with the rules verdict per bracket from the engine. Open: `_scan` MLD/extra-turn false positives in the live gate; precons read B1 by the model in 50/140. Next: B36.
- 2026-11-08: **B33 done.** Combos on the clock (`ratings/combo_clock.py`): per combo, share of games assembled by T3-T10 from the goldfish's own draws, with Spellbook's per-piece zones/summoning-sickness flags and prerequisites (checkable ones applied, the rest stated and kept out of the kill clock); tutors as outs gated on their own search object (`semantics/tutor_reach.py`, 50/50 real tutors read right); combined damage-or-combo clock. Draw-only assembly within 2 points of the exact hypergeometric. Next: B37.
- 2026-11-08: **B32 done.** Kill speed as a range (`ratings/kill_speed.py`): unopposed p25/median/p75 + share killed by T6/8/10 (mean pinned to `avg_kill_turn`); the table as a measured four-seat pod against corpus decks labelled with the deck's bracket (`/analyze table_speed`, `/pod field_bracket`), wins with a 90% interval, winning round, turn-cap wins apart, capacity as the unopposed line. Krenko kills unopposed in 99% but wins 22% of pods: the gap the measured headline exists for. Next: B33.
- 2026-11-07: **B34 done.** Kill-method attribution in tier0 (per card and per source, pinned to sum to the game's own damage) and T2 (combat vs noncombat; `/duel` win methods). Forced an engine fix: tier0 now applies the commander-damage rule (CR 704.5a); it had been ignored in 6-21% of games for commander-centric decks. Guard 58.5/91.8 -> 58.2/91.8, two boundary decks moved. Next: B32.
- 2026-11-07: **B31 done.** `ratings/card_verdicts.py`: strong (speeds the kill, combo pieces, commander synergy) and weak (stranded with colour/cost/outranked reason, slows the kill on clock cards the goldfish fully models, redundant in card counts). Hand review on 8 decks rewrote 4 rules before shipping, and found an engine defect: planeswalker ultimates read as on-cast effects (Ugin drew 7). Fixed in the tagger (CR 606.6); bracket guard 58.7/91.8 -> 58.5/91.8, one deck moved. Next: B34 (kill-method attribution).
- 2026-11-07: **B30 done.** Per-card goldfish telemetry (seen/played turn per card, recorded only: byte-identical play, no measurable cost) + `ratings/card_stats.py` + opt-in `/analyze card_stats`. Noise floor measured: 300 games names 4/72 cards; a dedicated 2,000-game pass (~3 s) gives +-0.14-turn intervals, calibrated, top/bottom significant in 8/8 seeds. Found: goldfish uplift ranks removal and wipes last (no opponent to answer), so B31 must never call interaction weak on it (spec section 6).
- 2026-11-07: **Phase 2b specced** (`SPEC_deck_scouting_report.md`, B30-B38) from a live `/analyze` + `/breakdown` inventory. Notable while measuring: a Krenko deck holding Krenko + Skirk Prospector + Goblin Warchief (infinite hasty tokens) reads "kill ~T9", because the goldfish clock never executes combos (B33).
- 2026-11-07: **B21 done.** `deck_legality.plan_fix` (pure: remove off-identity/banned, reduce extra
  copies, trim the biggest basic stack when over 100, refill up to 15, else "rebuild") +
  `POST /api/deck/{id}/fix-legality` (dry run by default; apply writes a NEW deck `fixed_from` the
  source; "legal fix" lineage badge in History) + `LegalityFix` UI. Old decks' ban status now comes
  from the local bulk store (the 17-card Thelon list was hiding a banned Mana Crypt). A lost partner
  can be named and is validated with the pairing rules; a recorded partner whose card was never in
  the list is put back. Verified on DUPLICATES of 4 real flagged decks (Marchesa, two old Tymna
  builds, the Azula import), all legal, copies deleted. Found on the way: the refill's bracket
  filter started at zero Game Changers and added Force of Will to a deck already at the B3 cap of
  3 (`BracketFilter.count_existing` now charges the deck's own); and the pairing check called a
  commander with no stored text "no partner ability" (unknown is not illegal).
- 2026-11-07: **B20 done.** `deck_price.py` + `GET /api/deck/{id}/price` + `DeckPrice` on the deck page.
  First cut priced from the oracle bulk's default printing and left Forest, Evolving Wilds, Lotus
  Petal and Mox Diamond unpriced on real decks (promo/foil-only defaults); now the cheapest nonfoil
  English printing from the per-printing store, oracle bulk as fallback. A batched indexed lookup
  (`scryfall_prints.prints_of_many`) took a deck from ~5 s to ~0.1 s. Real decks: 100/100 priced.
- 2026-11-07: **B19 done.** 20/20 valid, 0 padded, colours ok 20/20; synergy 15.62 -> 15.64, curve
  deviation 16.0 -> 15.5, weakest-theme 7.22 -> 7.11 (noise). Role means (classifier-counted, so
  they also move with the classifier fix): ramp 17.35 -> 17.85, finisher 3.25 -> 4.25, others flat.
  Ramp still counts ~18 against a plan of 10: the B25 target. Promoted to `docs/bench/current.json`.
- 2026-11-07: plan written.
