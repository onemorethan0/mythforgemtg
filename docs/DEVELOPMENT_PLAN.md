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
| B35 | Reference field per bracket (one deck per archetype from the corpus) and matchup win rates | weak against (games) | **done** |
| B36 | Exposure to hate: graveyard, commander, artifacts, flyers, single combo, mana base, speed vs peers | weak against (static) | **done** |
| B37 | Strengths/weaknesses as per-bracket percentiles instead of fixed bars | good at (honestly) | **done** |
| B38 | `/scout` report: template-first text, optional LLM paragraph behind the swap_narrative-style gate; Forge panel | the description | **done** (e53394a; first run ~3 min, cached -- the 30 s target is open; mentor citing it is open) |

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

### The unmodeled-mechanics sweep (owner request, 2026-11-09) -- first pass DONE same day

Shipped (tier0 unless noted), each read strictly from the card's own text with a gold set:
Station/Spacecraft, crewed Vehicles, printed haste, creature tokens (resolve / ETB / upkeep /
end step / cast / attack / landfall / +N loyalty), pump Equipment and Auras (incl. double strike,
infect equipment), proliferate, fixed drains, direct poison, Treasure, extra land drops; poison in
T2 duels. Tooling: `scripts/unmodeled_inventory.py` (unread rules lines, ranked by deck weight),
`scripts/unmodeled_label.py` + `scripts/unmodeled_adjudicate.py` (local-model family labels, gold-set
gated). Model choice measured: qwen3:14b 38/39 gold and 2.5 min per 2,000 shapes; Qwen3.6-35B-A3B
36/39, 6 min, and it disagreed with 14b on 48% of shapes (several plainly wrong); 32b adjudicated.
Read lines 4,096 -> 6,042 of ~36k. Remaining goldfish-relevant families by deck weight: +1/+1
counters, conditional/variable card draw, mana abilities on nonland permanents, free/alternative
costs, temporary team pumps, death-trigger drains and tokens, "*"-power creatures (lands you control).

Measured on all 2,110 labelled decks, refreshed store both sides (no combos, like-for-like):
75 bracket moves, 49 toward the player's label, 26 away; exact 61.3% -> 61.9%; 418 decks kill
sooner, 10 later. With the live pipeline (`bracket_strength_fit.py --collect`), the SHIPPED
model reads exact 60.1% -> 61.5%, B1-3 exact 59.6% -> 61.8% (B1 55 -> 53%, B2 55 -> 63%). A CV refit
on the new rows scores lower (60.2% exact, B1-3 58.3%), so nothing was re-baked. The guard also
caught a crash (attack-triggered Treasure/proliferate, 407 decks) before it reached a user.
Owner's decks: Y'shtola infect list T11 -> T9 (66% of kills by poison, 35% of games by T8 vs 19% for
the counters list); Borg Queen T11 -> T10 with its Spacecraft attacking.

**Second and third passes (same day, 4dba820).** Strict readers in `sim/tier0_readers.py`, each
audited across all ~35k cards for hits and near-misses before wiring: '*' / "for each" power (lands,
creatures, artifacts, hand), +1/+1 counters on entry (fixed, X, fabricate), Hardened Scales /
Doubling Season replacements, Hydra X creatures cast from spare mana, mana-only pump and counter
sinks (incl. monstrosity / adapt), beginning-of-combat counters, prowess, exalted, extort, lifelink
and fixed life gain into Sanguine Bond class drains, the aristocrats finisher (free outlet + death
drains, only when lethal), token doublers, extra combat phases, clones, Lotus Petal, land-Aura ramp,
board-sized draws, affinity for artifacts, convoke, mana flashback, cascade, native storm copies,
haste Equipment (Greaves/Boots) and team haste, pump spells, living weapon. Labelling the 16k-shape
tail ran split across both nodes (node 1 qwen3:14b, node 2 qwen3:8b at 35/39 gold once Ollama was
told `reasoning_effort: none` -- without it 8b spent the whole budget thinking and scored 0/39).
Read lines 6,042 -> 7,328. Corpus guard (2,110 decks, no combos): exact 61.9 -> 62.4%, B1-3 62.1 ->
63.3% (B2 68.6 -> 74.0%, B1 54.4 -> 51.5%), 58 moves, 37 toward the label, 316 decks faster, 13 a
half-to-one turn slower (flashback recasts reorder the greedy casts; checked, not a defect). Live
pipeline, shipped model: exact 61.5 -> 62.1%, B1-3 61.8 -> 62.7%; a CV refit scores 61.1% / 59.8%,
not baked. What is left unread is a long tail (no remaining shape above ~0.3% of deck weight): about
a third is interaction (evasion, removal, protection, counterspells, stax, wipes) that a no-opponent
goldfish cannot use -- T2's job, not tier0's -- and the rest is one-off wording (kicker riders,
recursion, conditional triggers, modal spells, typed lords).

Also found: the engine's card store was 17 days stale (Oct 23) -- every newer card was invisible
(31 of the Borg deck's cards). Refreshed with `mythgauntlet fetch-data --force`; a running engine
needs a restart to load it.

#### The original plan (kept for the method)

Owner: "pour through all the unmodeled things and set up the local LLMs to set up as many as we can
identify". Trigger: a Borg deck rated wrong because Spacecraft never attack -- tier0 adds an attacker
only when the type line says Creature, so a stationed Spacecraft ("It's an artifact creature at 9+",
then "9+ | Flying, first strike") deals nothing (45 Station cards: 40 Spacecraft, 5 Planets).
Vehicles (crew) are the likely sibling gap.

1. **Inventory (deterministic, no LLM).** For every card in the labelled corpus, split the
   reminder-stripped rules lines and mark each line read or unread by a tier0 / T2 consumer
   (the `sim-health` approach: read the sim's own sources, never restate a vocabulary). Rank the
   unread lines by how many corpus decks play them, weighted toward B1-3.
2. **Family labelling (local LLM, closed questions).** qwen3:14b sweeps the unread lines in batches of
   <=4 against a fixed family list (Station, Vehicle/crew, proliferate, equipment grants, landfall
   payoffs, ...); 32b adjudicates disagreements; a gold set first. Extraction and closed questions
   only -- the local models do not write rules code.
3. **Model the top families in Claude** (rules-facing): gold-set tests from printed text, the honest
   under-count where text can't be read exactly, and a corpus guard (exact-vs-label and moves toward or
   away from the label) for each family, one commit each.

Known open items to fold in: Station/Spacecraft, Vehicles, proliferate, equipment that grants infect,
poison in T2 duels, and Y'shtola's two decks re-measured in the app.

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

- 2026-11-10: **B38 scouting report (e53394a).** `ratings/scout.py` assembles the /analyze measurement (card stats, combos, table speed, cached matchups) into one template-rendered page; a test walks the text and fails on an unbacked number or card name. Engine `/scout`, Forge `/api/deck/{id}/scout` (cached per decklist + engine fingerprint), deck-page panel. Verified on a copy of the owner's Borg deck: it surfaced that the deck wins 11% of Bracket 2 four-player games (even seat 25%) despite a T8 goldfish clock. Open: first run ~3 min (spec: 30 s), and the mentor does not yet cite the report.
- 2026-11-10: **The owner's own decks' engines (abd513e).** From the unread lines across the owner's saved decks: granted combat-damage triggers (Locutus of Borg tokens, Supplementation Node, Co-Option Adjutant / Hive Mind Coprocessor draws), 'choose a creature type' cards read for the deck's most common type (Banners, Door of Destinies, Metallic Mimic), Black Market Connections' every-turn modes, Helm of the Host, Aggravated Assault. Deliberately left unread: no-maximum-hand-size, protection grants, opponent taxes -- marking them read would let the cut ranking call protection 'idle'. Token makers that make token makers doubled the board each turn after the kill: no tokens after the kill, MAX_BODIES 400.
- 2026-11-10: **Switch a deck's commander (f2d3874).** Edit deck panel 'Change commander' + POST /api/deck/{id}/set-commander: a legend from the 99 trades places with the commander (both keep art), eligibility per CR 903.3 front face, off-identity cards reported not removed, stale measurements dropped, swap_count bumped so measured panels reset. Partner decks refused for now.
- 2026-11-10: **One cut ranking (a8300fd, 82ee930, 443d962).** Owner: cut answers contradicted each other and Ambulatory Reactor was cut as 'spare ramp'. Researched player practice (EDHREC, TappedOut: protect plan + role floors, cut what doesn't help win, trim the fullest category) and 17Lands' improvement-when-drawn. `ratings/card_ablation`: paired drawn-games ablation (same seeds, card replaced in place by an uncastable blank, compared only over games it is drawn; only those games replayed; shrinkage) -- Sol Ring +0.49 vs the early-window metric's cheap-card-biased +1.17. `ratings/cut_ranking`: protect commander synergy / combos / plan lords / role floors / load-bearing; cut drag, then surplus (the only way interaction or partly-read cards go), then idle. `sim/legibility` (moved from the inventory script) decides which cards a goldfish number may judge. Verdicts, Advise's cut pool and the mentor's role swaps all read it. Also creature mana grants (Reactor, Cryptolith Rite), replicate (Hugh), charge-counter token engines, token typing for lords, 'colorless creatures get +N'.
- 2026-11-10: **Role swaps find a replacement (87f0459).** "What should replace them?" / "running out of gas" almost always ended in "no measured swap": one owned add against two cuts, and draw read only on consistency (floor 2.8 at chat runs) though it shows on clock or ceiling as often. `ROLE_GAIN_AXES` lets a role swap's gain land on any axis the role moves (own axis preferred; answers stay interaction-only; cost check unchanged); the mentor measures 3 adds x 2 cuts (~16-19 s); out-of-gas asks for the draw swap. Y'shtola: +Brainsurge -Rewind, consistency 82.0 -> 85.3, interaction cost stated; Borg: +Erode -Ambulatory Reactor, no cost.
- 2026-11-10: **Advise stops coming back empty (086ccf7).** An auto search bet everything on the weakest axis; on the owner's Y'shtola deck that is ceiling, fixed by the commander + Aura plan, so a 6-minute search returned nothing (Borg Queen: one swap). `advise(fallback_axes=N)` reads the same re-simulations on the next-weakest profile axes too (resilience excepted: its wipe pass doubled run time), each swap naming its own axis; noise-floor and whole-deck net gates unchanged, 0 = old search. Forge sends 3; Mentor's measured-swaps reads only its axis from a mixed result; route timeout 900 -> 1500 s (measured 450-704 s). Swap briefs carry the cut's role in cards (narration had said "30.0 counterspell slots, needing 3" for 10 vs 1). Owner's decks: Y'shtola 5 swaps (was 0), Borg 5 (was 1).
- 2026-11-10: **Mentor / upgrader review on the owner's real transcripts and decks (63b0bf2, 71942bd).** Replayed the owner's past questions on current code and ran Advise + five Mentor questions on the Y'shtola and Borg Queen decks. Fixed: the commander is looked up every turn (card questions ran no deck-wide tool, so the model said it did not know the commander and check 16 could not see claims about it); the lens reports the Treasure a targeted burn spell makes aimed at the commander (Bolt on Smaug 3; an option, never scored) and a card with no lens fact gets "no direct synergy" with the commander's text quoted; new tool `get_card_verdicts` (B31's measured strong/weak cards) prefetched for weakest/strongest/cut questions, with a role swap toward the most under-supplied role, and the measured list leads the reply if the draft names none; "running out of gas" is answered as draw count vs target; gate check 17 rejects generic card-type advice. Typed lords ("Artifact creatures you control get +2/+2", "Other Elves ...") were read as nothing, so Advise offered Locutus as a Borg Queen deck's cut and the verdicts called Tempered Steel weak: tier0 now buffs matching attackers, and `redundancy.plan_lords` keeps an on-plan lord (type covers >= max(6, 25%) of the deck's creatures) out of cut pools and weak verdicts. Guard: exact 62.4% unchanged, 8 moves (4/4), 47 decks faster, none slower. Still weak: Advise on Y'shtola ran 6 min and found no swap (16 of 916 owned cards evaluated); a role swap for draw rarely clears the consistency noise floor, so "what should replace them" often stays "no measured swap".

- 2026-11-09: **Tutors fetch in the goldfish.** tier0 reads a tutor's filter (card types, mana value) and destination (hand / top / battlefield) strictly from its own text -- 68 tutors; additional costs, random discard, multi-card, named, subtype and activated searches fetch nothing. Pick: the missing plan piece (an infect Aura for the commander), else highest impact; the Aura and a tutor that finds it are cast with commander priority. Y'shtola infect list: Aura cast in 78% of games (was 50%), median T7, kills T9 when found. Guard: 953 labelled decks with a readable tutor, 8 bracket moves (4 toward the label, 4 away), exact 651 -> 650 -- neutral.
- 2026-11-09: **Infect, toxic and poison in the goldfish; cast payoffs count their own trigger.** tier0 now routes an infect source's damage to poison (CR 702.90b), adds toxic, and kills at ten (CR 704.5c, kill method `poison`). Infect sources are creatures that PRINT it and the commander while an infect Aura (Phyresis, Glistening Oil, with Oil's upkeep -1/-1 counters killing a 2/4 on the fourth upkeep) is on it; equipment, proliferate and one-shot "gains infect" stay unmodeled. Cast-damage payoffs used to count instants/sorceries for every trigger; a "noncreature spell with mana value 3 or greater" payoff (Y'shtola) now counts artifacts and enchantments and skips cheap spells. Owner's two Y'shtola decks: infect list T11 -> T10 (30% of kills by poison; it finds an Aura in half its games, median T9), counters list T10 -> T9 -- the counters list is still the faster, more consistent deck. Guard: 262 labelled decks with a poison card or cast payoff, 3 bracket moves, all toward the label (exact 156 -> 158); the Corrupting Influence infect precon T11 -> T8, B1 -> B2 (label B2). Not yet: T2 duels have no poison; tutors don't fetch the Aura.
- 2026-11-08: **B35 done: reference field + matchups.** 7 archetypes x Brackets 1-4 from 1,667 decks; "Scout matchups" duels each, verdicts only when the 90% interval clears 50%; stable across seeds (max z 2.5 of 28). Fixed: partner commanders dropped in duels; matchup duels without combos. History tiles now open the newest version (art was "lost" under the original import). Next: B38 (the scouting report).
- 2026-11-08: **B36 done: Weak against.** Nine exposure rows past corpus percentiles (graveyard, commander answered twice via a new goldfish option, wipes, artifacts, enchantments, flyers, single combo, mana base, speed vs peers). Next: B35 (reference field + matchups), then B38 (the scouting report).
- 2026-11-08: **Draw-go tested and measured; History thumbnails.** End-of-turn window pinned by 6 tests (next seat only, no counterspells, flash creature attacks next turn). D6 ablation with draw-go: counters worth -0.2 pts (17.9% vs 18.1% dead) -- within noise of zero, as +1.2 was. History/Recent tiles now frame the card name and whole art. Next: B36 (exposure to hate).
- 2026-11-08: **Smarter counter targeting; counters ablation.** Pod seats counter only what threatens them (primary target, table-wide spell, archenemy, near-lethal). Group comparison was confounded (counter decks close far worse), so D6 now ablates: the same 12 High-Denial decks win 18.3% with counters, 17.1% with them dead (+1.2 pts over 1,440 games; helps 8, hurts 3). Counters are a small edge in the sim, not table-deciding.
- 2026-11-08: **Mana pilot fixed; D6 re-run.** Greedy no longer casts counterspells on an empty stack (it did, wasting them, 1v1 too); `pay_keeping` pays spells while keeping a held answer's colours open, from the first cast; land drops fix the hand's colours. Golden master re-captured (2/16 scenarios, both with instant answers). Counters cast in pods up ~30-100x. D6: High-Denial casual decks still win 19.4% of B2 pods vs Denial-Low 30.3% -- counter density alone does not win casual pods in the sim (caveats: indiscriminate counter targeting, no draw-go). Denial stays a fun dial, not a power input.
- 2026-11-08: **D5 done, D6 run (inconclusive).** Pod games now have a stack and an instant window: priority goes around the table, a seat responds only to flip the stack its way, 1v1 byte-identical. D6 (`scripts/denial_pod_study.py`): High-Denial B1-3 decks win 18.6% of B2 pods, Denial-Low 28.5%, ~unchanged by D5 -- because the greedy pilot can pay for a held counter in ~1-5% of the moments it matters (colour screw, early land count, tapping out). A pod-only colour-aware reserve gave no gain and was dropped. Next: a colour-aware mana pilot or ISMCTS agents before re-reading D6.
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
