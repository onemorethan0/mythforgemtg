# Deck Mentor handoff — six live campaign rounds (2026-08-25)

Written for the same reason `HANDOFF.md`/`ROADMAP.md`/`PLAN_CLOCK.md` exist for the builder and
gauging engine: the mentor's Phase 0-3 build (`docs/SPEC_deck_mentor.md`) shipped with unit
tests and a 13-case synthetic bench, but until this session nobody had actually *talked to it*
through the real HTTP route and read what came back. This file is that missing record.

**Read this before touching `mentor/{gate,chat,tools,transcript}.py` or `scripts/mentor_bench.py`.**
Every fix below was found by driving the live route (llama-swap :8010, engine :8020, root
server :8000), not by reasoning about the code — the same lesson `HANDOFF.md` §"a faithfulness
gate cannot be written by reasoning about what a model might do" already drew for `SwapBrief`,
now independently re-derived for the mentor's gate.

---

## The method, since it's reusable

1. Pick a real, already-built deck from your own History. Duplicate it — the original stays
   the untouched "before," the duplicate becomes the "after" you actually edit.
2. Ask real questions through `/api/deck/{job_id}/mentor`, one at a time. Read the `tool_trace`
   in the response and cross-check EVERY specific claim (a number, a rules citation, an oracle
   text quote) against the real source — `data/scryfall.py`'s card DB, `data/rulings.py`'s CR
   corpus, or `mentor_transcripts.jsonl`'s full tool-call record for that turn (the API response
   doesn't include tool result payloads; the transcript log does).
3. Record genuine `up`/`down` feedback via `/api/deck/{job_id}/mentor/feedback` based on that
   check, not on whether the reply sounded right.
4. When something is wrong, read the actual rejected drafts and reasons from the transcript log
   before deciding whether it's a gate bug, a prompt gap, or working as intended.
5. Fix, restart the engine (code changes need `mythgauntlet serve` restarted — it's a separate
   process from the LLM gateway and the web server), and re-ask the SAME question with fresh
   history to confirm the fix actually changed behaviour live.
6. Run `python scripts/mentor_transcript_audit.py` — it automatically re-derives the two signals
   a synthetic bench structurally cannot produce (a `gated: true` reply a human still rejected;
   a reply the gate actually caught mid-turn) from whatever real data now exists.

Five rounds, one deck archetype each, chosen to stress a different part of the surface:

| round | deck | colours/mechanic | commit |
|---|---|---|---|
| 1 | Syr Gwyn, Hero of Ashvale | Mardu voltron/equipment | `ff8300f` |
| 2 | (same, continued) | — | `df9fead` |
| 3 | Urza, Lord High Artificer | mono-U artifacts/combo | `f1728e4` |
| 4 | Arahbo, Roar of the World | GW cat tribal | `19be9de` |
| 5 | Kaalia of the Vast | Mardu "cheat creatures into play" | `19be9de` |

**Session totals: 57 real conversation turns, 49 up / 8 down genuine feedback, 8 confirmed false
negatives** (a `gated: true` reply a critical read still caught as wrong or incomplete) —
sitting in `mentor_transcripts.jsonl` right now, ready for `mentor_transcript_audit.py` to mine.

---

## What was found and fixed, in the order it was found

### Round 1 — the gate's own hardening pass had real false positives

The claim-budget gate had just been widened (previous session) to scan the FULL card index, not
just the current deck, for an unlooked-up card name. That fix was correct in spirit and
introduced real collateral damage, found immediately on first live use:

- **`NUM_RE` read a mana-curve range as two numbers.** "the 2-4 mana range" parsed as citing `2`
  and `-4` (the hyphen read as a minus sign), so a correct curve explanation was gate-rejected
  three times over for "citing -4". Fixed with a lookbehind so `-` only reads as a sign when not
  preceded by a digit.
- **Real (mostly joke-set) card names collide with ordinary English/notation.** "X" (the game's
  own variable-cost notation, e.g. Craterhoof's "+X/+X"), "Wizards", "Overload", "Spells" — all
  real cards, all false-flagged in completely innocent prose. Single-character names excluded
  categorically; multi-character ones are `gate._COMMON_WORD_CARD_NAMES`, an explicit, evolving
  list — see rounds 3 and 4 for how it keeps growing.
- **Markdown numbered-list markers read as cited numbers.** "1. **Point one**... 2. **Point
  two**..." (the model ignoring the system prompt's "no markdown" instruction) had its `1.`/`2.`
  read as asserted facts, not list positions. Stripped before the numbers check specifically.
- **A repeated mana symbol licensed no number at all.** Sol Ring's real oracle text is
  `{T}: Add {C}{C}.` — no literal digit `2` anywhere — so a model correctly saying "two colorless
  mana" was rejected for citing an uncited `2`. `_mana_symbol_counts` now licenses the repetition
  count of any mana symbol in a tool result, not just literal digits already in the string.
- **Two bench-scorer gaps, not gate gaps**: `_TRAP_HONESTY_MARKERS` (literal substrings) missed
  several honest phrasings ("does not exist" vs. "not documented"). Widened; this recurred in
  every subsequent round (see "the honesty-marker whack-a-mole" below).

### Round 2 — a prompt gap, and a completeness gap distinct from fabrication

- **Compound multi-card questions made the model skip tool calls entirely for both cards.**
  "Would X and Y both be good additions?" — asked about two real, unlooked-up cards, and all
  three regeneration attempts narrated confidently about both without calling `assess_card` for
  either. Fixed with an explicit system-prompt instruction: call the tool for EACH card
  separately before answering about any of them.
- **A false-premise correction landed correctly** ("Rhystic Study is a Sorcery" → correctly
  corrected to Enchantment) — confirming the earlier session's false-premise system-prompt
  addition actually works live, not just in the synthetic bench.
- **The completeness-gap finding**: Embercleave's real text has Flash and a cost-reduction
  clause that make it playable far below its printed 6 mana. A reply correctly quoted the text
  but omitted both and called it "6 mana... might be too slow" — nothing individually false, but
  misleading advice as a whole. Rated down. **This is a distinct failure class from fabrication,
  and the gate cannot catch it by design** — it checks whether claims are grounded, not whether
  an answer is complete. This is exactly the "gated: true but not actually good" signal
  `mentor_transcript_audit.py`'s false-negative detector exists to surface.

### Round 3 — the deepest false-positive class, found by testing a DIFFERENT commander

- **A possessive short-form of an already-verified name collided with a real card.** "Urza's
  {5} ability" (Urza, Lord High Artificer already looked up this turn) was rejected because
  "Urza's" is itself a real (joke-set) card name. Unlike the single-word cases in round 1, this
  recurs structurally for ANY multi-word commander name — fixed by masking the short-form
  possessive of a name already in `budget.card_names`, not another list entry.
- **"Ramp" and "Counterspell" are real card names AND two of the app's own role-vocabulary
  words** (`collection_pool.ROLES`, what `get_deck_stats` reports). A much higher-frequency
  collision than anything in round 1, since discussing role supply is one of the mentor's most
  common conversation types. Added to `_COMMON_WORD_CARD_NAMES`.
- **A card's own oracle text can contain a word that's also a real card name, and quoting it
  verbatim got punished for that.** Anguished Unmaking's real text is "Exile target nonland
  permanent" — "Exile" is itself a real card. The model faithfully quoted the retrieved text and
  was rejected for naming an unlooked-up card. This generalizes badly (any fetch/colour-fixing
  card naming a basic land type hits the identical wall — basic land names are always real
  cards). Fixed properly, not with another list entry: `ClaimBudget.source_texts` licenses a
  VERBATIM substring of what a tool call actually returned this turn as a whole, so a
  card-name-shaped word inside an exact echo isn't scanned as an independent claim. A
  PARAPHRASE (not a verbatim quote) is still scanned normally.

### Round 4 — a data gap, and a wrong deckbuilding-legality conclusion

- **`tool_lookup_card` never returned a card's `color_identity` at all.** A reply describing
  mono-green Heroic Intervention as "a green-white card" (likely conflating "fits the deck" with
  "is the deck's own colours") went unverified because there was no field to check it against.
  Added the field; added a system-prompt instruction against the conflation.
- **That fix immediately surfaced a worse, distinct error right behind it.** Once the model
  correctly said "it is green," it concluded the mono-green card "would not be playable in a
  green-white deck... unless you're okay with playing only green cards." Verified against the
  real corpus: **CR 903.5c is a SUBSET relationship** (every colour in the card must appear in
  the commander's identity, not vice versa) — a mono-green card is fully legal in a GW deck.
  This is foundational, stable rules knowledge, unlike a fragile rule number, so it's baked
  directly into the system prompt rather than left to the model's own reasoning about a rule it
  might misremember.

### Round 5 — the deepest citation-quality bug in the whole campaign

- **A real, genuinely-retrieved rule number cited to support something it doesn't establish.**
  Asked whether a creature Kaalia cheats into play still deals combat damage (bypassing
  summoning sickness) and triggers its own ETB abilities, then pushed to verify, the model cited
  `506.3a` and `708.3` — both real, both actually returned by `search_rules` that turn. Neither
  establishes the claim: **506.3a covers NONCREATURE permanents** (506.3b, about creatures
  specifically, was sitting UNUSED in the very same search results), and **708.3 is the
  face-down-entry EXCEPTION** to ETB triggers, not the general rule. Both final conclusions were
  independently verified as correct, but neither citation supports them. This is a sharper
  version of the exact 704.5c/704.5f digit-sharing risk `mentor/gate.py`'s whole citation
  architecture was designed around — except here the gate's own membership check ("was this
  number retrieved this turn?") legitimately PASSES, since 506.3a really was returned. No
  existing mechanism could have caught it. Fixed with a system-prompt instruction: when a search
  result includes multiple sub-rules sharing the same parent number, read every one before
  citing any, since siblings almost always cover mutually exclusive cases. Verified live: a
  fresh ask now reasons from 506.3b's actual text instead of miscitting 506.3a.
- **A different false positive, same session**: "I'll check what Utvara Hellkite has to offer"
  — zero claims about the card, just echoing a name the PLAYER's own question already named
  while announcing intent to look it up — was rejected as an unlooked-up card. Fixed: a bare
  name mention that ALSO appears in the player's own question this turn is exempted (anything
  the model goes on to assert about that card is still fully checked).
- **A subtle, sophisticated hallucination pattern worth naming**: pushed for a second time on
  the same underlying question, the model didn't invent random numbers — it anchored on a REAL
  number from three turns earlier (+7.2 interaction) and perturbed it slightly (+6.8) to look
  like a plausible fresh re-measurement, without calling the tool again. Caught by the gate (the
  card name wasn't re-verified that turn) but worth knowing this failure MODE exists: not just
  "invents facts," but "subtly edits a real fact to look freshly measured."

### Round 6 — the deepest gap yet, and it wasn't in the mentor's prompt at all

Set up to close the campaign's last open item: no partner-commander deck had ever been run
live (ROADMAP S2 claimed the generate path "already works end-to-end — Tymna + Thrasios →
HTTP 200, a WBGU deck", verified only as far as build success, not correctness). Built that
exact deck and found the real gap sat two layers below the mentor, in plumbing every prior
round's fixes sat downstream of without exercising it.

- **The generate-path build never told its own quality report about the second commander.**
  `_run_build`'s generate branch called `compute_stats(card, deck)` with the LEAD commander
  only; `deck_quality.assess_colors` filters mana sources by the commander dict it's handed
  (exactly the bug `command_zone_identity` was built to fix for IMPORTS, 2026-08-14 — see
  `CLAUDE.md`'s commander_analysis section). The built deck genuinely has an Island, three
  Forests and six five-colour fixers (Command Tower, City of Brass, Exotic Orchard, Mana
  Confluence, Cavern of Souls, Reflecting Pool) — real U/G sources — but the report said
  `colors.ok: False`, "U: 0 sources, wants 15", "G: 0 sources, wants 15." Fixed by threading
  `partners=` through (same fix `generate-list`, the phase-1 endpoint, already had — phase 2's
  `prebuilt_deck` branch had the identical gap and got the identical fix).
- **The strength engine and the mentor never knew a second commander existed at all — not a
  measurement bug, an INVISIBILITY bug.** `_deck_to_lines` (the ONE function that serializes a
  Forge deck into MythGauntlet's decklist text for `/analyze`, `/advise`, `/card-impact`, `/duel`
  AND `/mentor/chat`) only ever wrote one `Commander:` line. Every one of those five call sites
  silently dropped the partner — meaning `/api/deck/{id}/measure` (the actual bracket/strength
  GAUGING feature, this project's other stated top priority) graded a partner deck's manabase
  against half its real colour identity too, and the mentor's `ctx.resolved.commanders` was
  just Tymna, full stop. Fixed at the root: `_deck_to_lines(commander, deck, partners=)` emits
  one `Commander:` line per card (mythgauntlet's own `Deck.parse_text` already supported this —
  it was never exercised), persisted `partners` as new deck.json metadata (added to
  `_PROVENANCE_KEYS` so rebuild/retheme don't drop it), and threaded it through all five
  `_gauntlet_*` helpers and their route handlers via a small `_job_partners(job)` shim.
- **Once the mentor could finally see both commanders, it had no TOOL to say who they were.**
  Asked "who are my commanders and what's my colour identity" — the single most natural
  partner-deck question — it answered "I currently don't have access to your decklist,"
  `tool_trace: []`. True cause: no tool ever surfaced `ctx.resolved.commanders`; the only path
  to a card's identity is `lookup_card(name)`, which needs a name the player must already
  supply. Fixed by adding `commanders: [{name, color_identity}]` to `get_deck_stats`'s own
  return (with `card_names=` so stating them is licensed) rather than a whole new tool, since
  `get_deck_stats` already means "ask me about this deck's own shape."
- **The worst finding: a model that correctly RECITES both colour-identity sets can still fail
  the subset check between them.** Asked whether Chaos Warp (mono-red) could be added to the
  now-correctly-WBGU deck, it wrote: *"its color identity (red) is covered by your deck's color
  identity (black, white, green, and blue)"* — red is plainly absent from that list, stated one
  clause earlier, in the same sentence. Lightning Bolt got the same wrong verdict, plus a
  fabricated "you have a good number of red sources" (there are none). This is NOT the
  fame-of-the-card triggering a prior — reproducible on both a household name and Chaos Warp —
  it's `qwen3:14b` failing basic set-subset arithmetic even with correct premises in hand, and a
  system-prompt instruction to "check the letters one at a time" did NOT fix it on retest (the
  model still recited the sets correctly and still drew the wrong conclusion). The gate didn't
  catch it either — no fabricated card name, no fabricated number, no fabricated rule citation,
  just wrong REASONING over real, correctly-cited facts, which is outside the claim-budget
  gate's design by construction (see "what's still open" below, this was already flagged as a
  gap). Fixed by removing the reasoning step from the model entirely: a new deterministic
  `check_legality(name)` tool computes the subset check in Python and returns a `legal` bool +
  `colors_not_in_deck_identity`; the system prompt now says never to do this arithmetic
  yourself even with both sets already in context, and to report the tool's verdict verbatim.
  Verified live: Lightning Bolt and Chaos Warp both correctly rejected, Mystic Confluence still
  correctly accepted, after the fix. Unit-pinned in `tests/engine/test_mentor_tools.py` with a
  synthetic two-commander (WB + GU) fixture, since no real corpus deck has this shape yet to
  drive `mentor_bench.py` — the bench stays 45 cases this round; the regression coverage for
  this class of bug lives at the tool level instead, which is more precise anyway (deterministic
  inputs, not dependent on the live model's phrasing).

This round is the strongest evidence yet for the campaign's whole premise: every one of these
four bugs was invisible to the synthetic bench, to code review, and to the ROADMAP's own
"HTTP 200, a WBGU deck" verification — because none of them are wrong until you actually ask a
real question about a real two-commander deck and check the answer against ground truth.

---

## The honesty-marker whack-a-mole, and why it's a scorer problem, not a gate problem

`scripts/mentor_bench.py`'s `_TRAP_HONESTY_MARKERS`/`_TRAP_HONESTY_PATTERNS` exist to recognize
an HONEST decline on a trap question. Every round found at least one new honest phrasing the
literal-substring list didn't cover ("does not exist" vs. "not documented"; "no Magic: The
Gathering card named X" vs. "no card named X"; three separate phrasings of "yes, 704.5f is the
right rule, not 704.5c"). One case (a fourth phrasing of that same 704.5c/f correction) was
found and DELIBERATELY left unwidened — see `mentor_bench.py`'s own "ACCEPTED RESIDUAL GAP"
comment: a small model's paraphrase space for "here's the correct rule number" is effectively
unbounded, and chasing every phrasing is chasing the scorer, not fixing the mentor. **If this
recurs, the real fix is comparing `MentorReply`'s own structured rule-number field against the
trap's baited number, not another regex** — the model was answering correctly every time across
five live runs; only the bench's ability to RECOGNIZE that kept lagging.

`scripts/mentor_bench.py` is now 44 cases (13 → 43 → 44), including a sixth trap kind added
directly from a real campaign finding (`trap_unaddressed_nuance`, mined from round 5's
506.3a/506.3b miscitation) — still short of the spec's 75-100 target, said so plainly rather
than rounded up.

---

## What's still open

- **The bench is 44/75-100.** Growing it further should come from real transcript data
  (`mentor_transcript_audit.py`'s output) as usage accumulates, not more synthetic guessing —
  that's how `trap_unaddressed_nuance` was added, and it's a stronger case than one invented
  from first principles.
- ~~**The generate path still cannot BUILD a legal partner-commander deck end to end**~~ — FIXED
  the same session, once `builder_bench.py` gained the `--partners` measurement this item asked
  for. `DeckBuilder.build()` now takes `partner_count`, shrinks its drafted library by that many
  cards (`library_size = 99 - partner_count`, threaded through the ~20 internal call sites
  documented above), and the server appends the partner card(s) into `deck` afterward — landing
  on a legal 100-card zone. Verified live on Tymna+Thrasios and Vial Smasher+Kraum (see
  `ROADMAP.md` S20 for the full writeup and `docs/bench/partners-s20-fix.json` for the run).
- **`check_legality`'s fix removes the model's OWN subset arithmetic but not a residual risk one
  layer up: a reply could still contradict its own tool's verdict** (e.g. call the tool, get
  `legal: false`, and write "yes" anyway). Not observed live, but the gate has no mechanism to
  catch a text/tool-result contradiction in general — see the semantic-entailment gap below,
  which this is a narrower instance of. Quoting the tool's `legal` field is now trivial for the
  model (it doesn't have to compute anything, just read a boolean), which is presumed to make
  this much less likely than the subset-arithmetic failure it replaces, but it hasn't been
  stress-tested the way the arithmetic failure was.
- **The rules-paraphrase-without-citation heuristic is bounded, not complete** (documented in
  `gate.py` itself): a definition phrased outside its specific hardcoded patterns still slips
  through with zero mechanical check.
- **The gate cannot verify semantic entailment** — round 5's 506.3a/506.3b case proved a
  citation can be real, genuinely-retrieved, AND still not establish the claim it's attached to.
  The prompt-level fix (read every sibling before citing) narrows this but doesn't close it; a
  structural fix would need something like feeding the specific cited rule's own text back to
  the model as a second-pass self-check before shipping the reply, which hasn't been built.
- **Completeness gaps (round 2's Embercleave case) are structurally outside what a grounding
  gate can check.** A reply can be 100% faithful to what it retrieved and still leave out the
  single most decision-relevant fact. This needs either a "did you check X, Y, Z about this
  card" prompt checklist per tool, or more `mentor_transcript_audit.py`-driven downvoting to
  surface the pattern's real frequency before designing a fix.

## Files this touches, if you're picking this up fresh

`src/mythgauntlet/mentor/{gate,chat,tools,transcript}.py`, `scripts/mentor_bench.py`,
`scripts/mentor_transcript_audit.py`, `tests/engine/test_mentor_{gate,tools,transcript}.py`,
`tests/engine/test_server_mentor.py`, `tests/test_mentor_deck_route.py`. Round 6 also touched
`server.py` (`_run_build`'s `partners` threading, `_deck_to_lines`/`_gauntlet_*`/`_job_partners`,
`_PROVENANCE_KEYS`) and `deck_builder.py`/`commander_analysis.py` were READ but not changed —
see round 6's still-open item on why a full partner-build fix wasn't attempted there. The live campaign
itself used a throwaway `scripts/_campaign_helper.py` (deleted after each round, not committed)
— a thin curl-equivalent that threads conversation history through `/api/deck/{id}/mentor` so
each turn is a one-line command instead of hand-building the history array each time. Recreate
it from this doc's "the method" section if you pick this back up; it's ~70 lines and not worth
version-controlling since it's pure plumbing with no logic of its own.
