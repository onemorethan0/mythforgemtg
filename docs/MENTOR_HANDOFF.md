# Deck Mentor handoff — seven live campaign rounds (2026-08-25, +round 7 2026-09-15)

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

### Round 7 — closing the "what should I even ask" gap, and two more false positives found live

Started from a different angle than rounds 1-6: not a bug report, but an audit of the mentor
against this app's own stated top-level purpose ([[user-myth-suite-goal]], casual bracket 1-3
pod-fit gauging). Reading `tools.py`'s tool table against that bar found two real, load-bearing
gaps — the mentor covered curve/colours/role-supply in real depth but had **no path at all**
to "what bracket is this deck" or "what should I cut", arguably the two most on-mission
questions a real user would ask first.

- **`get_bracket_estimate` (new tool).** Wires `ratings.analysis.analyze_deck` →
  `ratings.bracket.estimate_bracket` in-process — the same pipeline `mythgauntlet analyze` and
  Forge's Analyze panel already use — with `run_resilience=False` and no live Spellbook combo
  lookup, both disclosed honestly via a `combos_checked: false` field the tool adds itself
  (`BracketEstimate` doesn't carry that flag; the HTTP `/analyze` route surfaces it as its own
  top-level key for the same reason, and this tool mirrors that convention). Priced like
  `assess_card` — a few seconds, its own tool rather than folded into the free `get_deck_stats`.
- **`suggest_swap` (un-deferred).** SPEC Phase 1 explicitly deferred this pending the loop being
  "proven live" — six rounds and a hardened gate later, it has been. Suggests ONLY from the
  player's own Myth Suite collection (never general Magic knowledge), reusing the exact
  candidate-selection rule `/advise`'s HTTP route already used — factored into a new shared
  `advisor.owned_candidates()` so the two callers can't drift, this repo's own most-repeated bug
  class. Bounded well below Forge's patient `/advise` panel (`max_eval=4, cut_pool=1` vs.
  `max_eval=16, cut_pool=6, runs=300` — that config measured ~583s off the request thread,
  useless inside a synchronous chat turn). Licenses `SwapBrief.allowed_card_names` in addition
  to the add/cut names themselves, so the swap's own measured reasoning can name a synergy card
  without a false gate rejection.
- **Archetype detection turned out to already be fully wired** (`themes` → Forge's
  `_deck_archetypes(job)` → `get_deck_stats`'s `detected_themes` field) — the audit's initial
  assumption that this was also missing was wrong, caught by reading the code before building
  anything, not by trusting an old write-up.
- **Off-meta (`lift_stats`) is a Forge-root capability, not an engine one** — it needs a live
  EDHREC fetch and Forge's own cache, neither of which the engine process has. `get_deck_stats`
  gained an `offmeta` field that's a PASS-THROUGH of whatever Forge already had cached in
  `deck.json`'s `stats.offmeta`, threaded through `MentorChatRequest.offmeta` exactly like
  `themes` already is — zero new engine-side measurement, zero new network calls from `:8020`.
  `None`/`{"available": false}` when Forge has nothing cached (an older deck, or `lift_stats`
  itself returning `{}` for insufficient EDHREC coverage) — the system prompt says to report
  that honestly rather than guess.
- **`check_legality` had ZERO bench coverage since it shipped in round 6** — a real gap noticed
  while adding the two tools above, not something this round set out to find. Two cases added;
  a live spot-check (outside the full bench) confirmed it's still exactly as solid as round 6
  left it: Lightning Bolt (R) correctly rejected against this session's BG test deck, Golgari
  Signet (BG) correctly accepted, Sun Titan (W) correctly rejected even when the question
  baited a "but it fits my curve" justification.
- **A residual the round-6 writeup named but never stress-tested got its first mechanical
  check**: a reply could call `check_legality`, get a verdict back, and still write the OPPOSITE
  conclusion in prose. `ClaimBudget` now carries `legality_verdicts` (detected structurally from
  a tool result's own shape — `found`+`legal`(bool)+`card`+`colors_not_in_deck_identity`
  together, since `ToolResult` carries no tool name) and `check()` flags a reply whose own
  sentence naming that card uses an explicit legal/illegal phrase contradicting the verdict.
  Deliberately narrow (requires the card name AND an explicit legal/add verb in the same
  sentence) — the same under-flag-over-false-positive bias every other heuristic check in this
  file already follows. Not observed live this session (the model never actually contradicted
  itself in the spot-check above), same as round 6 left it — this closes the mechanism gap, not
  a reproduced bug.

**Two more false positives found by actually re-running `mentor_bench.py` (now 52 cases, +7
covering `bracket`/`suggest_swap`/`check_legality`) against a real corpus deck (Shelob, Child
of Ungoliant) through the live model** — exactly the round 1-6 method, applied to code that
had never been driven live before:

- **"How many lands am I running?" had no licensed number to answer with.** `get_deck_stats`
  reported `nonland_count` but never a land count, so the model either summed per-colour
  manabase sources itself (`15 + 39 = 54`) — a derived number that never appears literally in
  any tool result, correctly gate-rejected three times over — or refused outright. Fixed by
  adding `curve.land_count` (a plain count from `resolved.cards`, auto-licensed the same way
  every other number in `get_deck_stats`'s response already is — no new gate logic needed).
- **A mana-curve bucket LABEL read as a claimed number, the same shape as three already-fixed
  bugs in this file** (the "2-4 mana range" hyphen, list markers, mana-symbol repeats). "5
  **six**-mana cards" was gate-rejected for "citing 6" — the word "six" names which curve
  bucket the licensed "5" belongs to, not an independent fact, and this deck's curve happened
  to contain no literal 6 anywhere to license it against. Fixed with `_CURVE_BUCKET_LABEL_RE`,
  stripped from the NUMBERS scan only, same pattern as the existing `_LIST_MARKER_RE`.
- **Both fixes verified live, twice**: re-running the exact same 50-case bench after each fix
  flipped both cases from FAIL to PASS with no other case moving — the standard proof this
  file's method calls for, not just a passing unit test.
- **Net: 45/50 → 47/50** across the two live runs (bracket ×3 and suggest_swap ×2 all passed on
  first try in both runs). The **remaining 3 failures are the exact same accepted bench-scorer
  residual `_TRAP_HONESTY_PATTERNS`' own comment already names** (a sixth/seventh phrasing of
  "yes, 704.5f is correct" and of an honest false-premise correction, plus a sixth phrasing of
  "the rules I found don't address this") — read individually and confirmed honest/correct
  answers, not new mentor defects. **One of them is worth flagging as a live recurrence, not
  just a scorer gap**: on the second run, `trap_unaddressed_nuance`'s reply admitted "None of
  the rules provided directly address whether a token counts itself" and then continued anyway
  — "However, based on general Magic: The Gathering principles, a token generally does not
  count itself..." — which is the EXACT failure shape round 3 already named and tried to fix
  with a system-prompt instruction ("Do NOT follow that admission with a guess dressed up as a
  conclusion"). It didn't recur on the first run's phrasing of the same question. This is
  gate-invisible by construction (no unlicensed name/number/citation), consistent with the
  SPEC's own documented "the gate cannot verify semantic entailment" limit — recorded here as
  confirmation the prompt-only fix is not fully reliable at temp 0.2, not chased further this
  round (see "what's still open" below for why).
- **This bench run also confirms something structural, not a bug**: `mentor_bench.py` calls
  `mentor_chat.ask()` directly, bypassing the HTTP route entirely — `data/mentor_transcripts.jsonl`
  stayed at exactly 3 lines (0 growth) across ~100 live LLM turns run this session. This is
  correct isolation (synthetic bench probes must not pollute the real-usage signal Phase 3 is
  built to mine), but it also means **the bench cannot be the thing that grows real usage** —
  see "what's still open."

Also touched, lower-stakes: the panel (`MentorChatPanel.jsx`) defaulted `open` to `false` and
showed only a placeholder hint before the first message — checked directly, `data/mentor_transcripts.jsonl`
held exactly 3 turns and 0 feedback records three weeks after round 6 shipped, i.e. real usage
had stayed near zero. Panel now defaults open and shows three one-click starter prompts (one
per new tool) so a real conversation has a lower bar than composing a question from scratch.

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

`scripts/mentor_bench.py` was 44 cases as of round 6 (13 → 43 → 44), including a sixth trap
kind added directly from a real campaign finding (`trap_unaddressed_nuance`, mined from round
5's 506.3a/506.3b miscitation). Round 7 grew it to 52 (45 → 50 → 52: three new domains —
`bracket`, `suggest_swap`, `check_legality`, the last retroactively covering a tool that had
shipped with zero bench coverage since round 6) — still short of the spec's 75-100 target,
said so plainly rather than rounded up.

---

## What's still open

- **The bench is 52/75-100.** Growing it further should come from real transcript data
  (`mentor_transcript_audit.py`'s output) as usage accumulates, not more synthetic guessing —
  that's how `trap_unaddressed_nuance` was added, and it's a stronger case than one invented
  from first principles.
- **Real usage is still the actual bottleneck, and round 7 confirmed it rather than fixing it.**
  `data/mentor_transcripts.jsonl` sat at 3 turns / 0 feedback records for three weeks before
  this round and is STILL at 3 after it — `mentor_bench.py` deliberately bypasses the HTTP
  route (calls `mentor_chat.ask()` directly), so ~100 live LLM turns run this session correctly
  logged NOTHING to the real-usage file. The panel now defaults open with starter prompts
  (round 7's UI change) specifically to lower the bar for a real conversation, but that is a
  bet, not a measurement — check `data/mentor_transcripts.jsonl`'s line count next time this
  file is picked up to see whether it worked. Every item below this one (bench growth past 52,
  the two structural gaps, Phase 3 distillation) is downstream of this one actually moving.
- **Two structural gaps were reconsidered this round, deliberately not built, for a reason
  worth recording rather than leaving as a silent TODO:**
  - *Completeness gaps* (round 2's Embercleave case — a reply 100% faithful to what it
    retrieved, still missing the single most decision-relevant fact) remain unfixed. A
    per-tool "did you check X/Y/Z" checklist was considered again this round and rejected for
    the same reason the SPEC already gives: with real usage still at ~zero, there is no
    frequency signal to size the fix against, and shipping an untested heuristic checklist
    risks new false positives to guard against a pattern observed exactly once, ever. Waits on
    the item above.
  - *Citation-doesn't-support-the-claim* (round 5's 506.3a/506.3b case) — the SPEC's own
    suggested structural fix ("feed the cited rule's text back to the model as a second-pass
    self-check") was reconsidered and rejected on a sharper basis than "not built yet": it IS a
    second LLM call, which `gate.py`'s own module docstring already states this whole
    architecture is built to avoid ("a second model checking the first is not a mechanical
    check, it's a second chance to hallucinate"). Telling "704.5c is real and retrieved but
    about poison counters, not toughness" apart from "704.5f actually establishes this" is a
    semantic-entailment judgment, not a string/regex-checkable one — genuinely not mechanizable
    without an LLM in the loop. Recorded here as a considered-and-declined structural fix, not
    an unattempted one: the prompt-level mitigation (read every sibling before citing) is very
    likely the ceiling for a purely mechanical gate on this specific gap.
- ~~**The generate path still cannot BUILD a legal partner-commander deck end to end**~~ — FIXED
  the same session, once `builder_bench.py` gained the `--partners` measurement this item asked
  for. `DeckBuilder.build()` now takes `partner_count`, shrinks its drafted library by that many
  cards (`library_size = 99 - partner_count`, threaded through the ~20 internal call sites
  documented above), and the server appends the partner card(s) into `deck` afterward — landing
  on a legal 100-card zone. Verified live on Tymna+Thrasios and Vial Smasher+Kraum (see
  `ROADMAP.md` S20 for the full writeup and `docs/bench/partners-s20-fix.json` for the run).
- ~~**`check_legality`'s fix removes the model's OWN subset arithmetic but not a residual risk one
  layer up: a reply could still contradict its own tool's verdict**~~ — MECHANICAL CHECK ADDED
  round 7. `ClaimBudget.legality_verdicts` + a new gate check catches a reply whose own sentence
  naming a checked card uses an explicit legal/illegal phrase contradicting that turn's
  `check_legality` result. Deliberately narrow (same card name + explicit verb, same sentence)
  to keep the under-flag bias every heuristic in this file follows. Still not observed live as
  a genuine failure (the round-7 spot-check on Lightning Bolt/Golgari Signet/Sun Titan never
  contradicted itself) — this closes the mechanism gap, it doesn't confirm the failure mode
  reproduces, same distinction round 6 already drew for the arithmetic fix it replaced.
- **The rules-paraphrase-without-citation heuristic is bounded, not complete** (documented in
  `gate.py` itself): a definition phrased outside its specific hardcoded patterns still slips
  through with zero mechanical check.
- **The gate cannot verify semantic entailment, and completeness gaps are structurally outside
  what a grounding gate can check** — see round 7's two bullets above (both reconsidered and
  deliberately left unbuilt this round, with the reasoning recorded there rather than repeated
  here).

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

**Round 7** additionally touched `src/mythgauntlet/ratings/advisor.py` (new `owned_candidates()`
shared helper, extracted from the `/advise` route's own inline loop), `src/mythgauntlet/server.py`
(`MentorChatRequest.offmeta`, the route threading it into `MentorContext`, and the `/advise`
route now calling `advisor.owned_candidates`), root `server.py` (`_gauntlet_mentor_chat`'s
`offmeta` param, `mentor_chat_deck` reading `job["stats"]["offmeta"]`), and
`frontend/src/components/MentorChatPanel.jsx` (default-open, starter prompts, two new tool
labels). New tests in `tests/engine/test_mentor_tools.py` (bracket + suggest_swap, including a
real positive-swap end-to-end case using the exact fixture shape `test_advisor.py` already
proved reliable), `tests/engine/test_mentor_gate.py` (the contradiction check + the curve-bucket
false-positive fix), `tests/engine/test_server_mentor.py` and `tests/test_mentor_deck_route.py`
(`offmeta` threading both directions). Full repo suite (`python -m pytest tests`) re-run clean
at 1569 passed, 0 failures, before and after every change in this round.

## Round 8 — holistic questions (docs/PLAN_MENTOR_ADHOC.md, 2026-09-30)

**Why.** An ad hoc probe on the Shelob deck (about 1 of 8 holistic questions answered correctly)
showed the mentor was grounded but wrong about the deck: "what does it do well and poorly",
"make it faster", "how resilient is it to a wipe", "which cards do the most work", "what can my
removal not answer" all reached the model with no tool that carried the answer, so it improvised
from verdict-free numbers. Rounds 1-7 graded non-trap questions on `gated` alone, which cannot see
that. Round 8 adds the tools, the verdict vocabulary and an acceptance bench that grades the
substance.

**What shipped (by phase).**
- **A0 bench**: `scripts/mentor_holistic_bench.py` + `mentor_holistic_rubrics.py`, 9 decks x 8
  questions (+ colour), MECHANICAL rubrics only (never an LLM judge). Baseline **22/72 (31%)**.
- **A** (`get_power_profile`, verdict phrases in `mentor/verdicts.py`, `_analysis_for` cache,
  archetype/win route/key cards): **64/72 (89%)**; Shelob `mentor_bench.py` 50/52.
- **B** (`list_deck_cards`, `removal_coverage` with unrestricted coverage) + **C** (colour-aware role
  targets for counterspell/wipe/finisher): **72/81 (89%)**, `removal` 9/9, `colour` 4/9 (target
  missed; the cause was the tool, not the model).
- **D0** (`clock` axis = how EARLY the deck kills; `advisor.PROFILE_AXES` is AXES minus clock and
  drives `weakest_axis`), **D0b** (unbacked-cut disclosure), **D1** (`diagnose_axis`), **E2** (bracket
  standings via `vs_bracket`), **F1** (verdict gate: a reply that contradicts `verdicts.*` is
  rejected and retried), C-residual fixes: **79/81 (98%)**, 80/81 after one offline rubric tweak;
  gated on first attempt 70/72; Shelob `mentor_bench.py` 48/52 (bar 47). Full suite then 2008 passed.
- **D2**: `get_measured_swaps` + Forge `advice_cache` (below).
- **G1/G2**: starter prompts, a label for every tool (parity-tested), these docs. Full suite
  **2041 passed, 4 skipped**.
Read every figure as +-5 points: identical-code runs vary 3-5 cells.

**D2 design (measured swaps).** `suggest_swap` is a 4-simulation, in-chat search; Forge's Advise
panel runs the deep one (minutes). `_run_advise_job` now persists
`deck.json["advice_cache"][axis | "auto"] = {result, deck_hash, collection_mtime, computed_at}`
(NOT in `_PROVENANCE_KEYS`: a rebuilt deck is a different deck). `mentor_chat_deck` sends only
entries whose sha1 of `_deck_to_lines(...)` AND the suite `collection.csv` mtime still match, as
`advice` -> `MentorChatRequest.advice` -> `MentorContext.advice` (pass-through, same as `offmeta`).
`get_measured_swaps(axis)` shares `_swap_result` with `suggest_swap` (same licensing, `cut_is_redundant`
disclosure, `current` block) or returns `{"available": False, ...}`. **qwen3:14b ignores a prompt
rule that says "call get_measured_swaps first"** (live smoke: it went straight to suggest_swap), so
`chat.ask` enforces it: a `suggest_swap` call first runs `get_measured_swaps` for that axis; an
available result IS the answer (the quick search is skipped), an unavailable one is traced (the UI
keys its "Run full swap search (<axis>)" button on `tool_trace[].available === false`, which the HTTP
reply now carries for that one tool) and the quick search runs with a `search_depth` note telling
the model to call it shallow. Live smoke (Shelob, "How could I make this deck faster?"): with a
cached clock search the reply named the cached swap (Sol Ring for Eaten by Spiders) and disclosed the
cut was not evidence of weakness; with `advice=None` it said no measured improvement was found and
pointed at Advise on the deck page.

**Still open.**
- **E1: the axes do not separate brackets.** Over 569 labelled decks only `interaction` (and
  consistency/speed at B5) move between brackets; `avg_kill_turn` is flat ~10 and `ceiling` p50 is flat
  17-19. `vs_bracket` standings are a within-bracket placement, not a B3-vs-B4 discriminator, and the
  prompt says so. A bracket call still belongs to `get_bracket_estimate`.
- **`tags.py` is verb-gated and misclassifies some interaction** (found while writing B2: "destroy
  target" sweeps Naturalize/Vandalblast into creature removal). `mentor/removal.py` reads the OBJECT
  clause by clause and is the authority for what removal can hit; but `get_deck_stats` role supply and
  `list_deck_cards` roles still come from `tags.analyze`, so a role COUNT can disagree with
  `removal_coverage`. Not fixed (it is engine-wide: bracket and the advisor read the same tags). **Largely fixed 2026-10-01** (branch `fix/tags-interaction`, merged in the review round): `tags.interaction_modes` gates the OBJECT and own-permanent/flicker; Naturalize-class answers stay out of `removal`. The two parsers are still separate derivations (`mentor/removal.py` imports tags), so a count can still differ at the edges.
- **Isshin colour self-contradiction.** One closing sentence ("it lacks the ability to counter spells
  directly") after correctly saying counters are not applicable; the colour rubric fails it, the model
  contradicted itself. Left failing (colour 8/9 regraded). **Fixed 2026-10-01** by gate check 11 (counterspell framing for a non-blue deck); colour 9/9 since.
- Plan section 5/7 leftovers: no second LLM judge (rejected, round 7); no suggestions outside the
  player's collection; no cEDH line analysis (casual B1-3 pod). `colour` was the one rubric that needed
  a tool fix, not a prompt fix, so check the TOOL first for the next failing rubric.
- The "Run full swap search" button starts the SAME job as the Advise panel with `narrate: false`
  (fast); it tells the user to ask again rather than re-asking for them. A swap applied or a collection
  edit invalidates the cached search silently (the mentor then says none has been run). An axis-less
  `suggest_swap` call with no cached "auto" search skips the lookup, so no button is offered for it.
- The nudge/route logic in `chat.py` (`_wants_a_swap`, `_route_swap_axis`, `_measured_first`) is regex
  and call-shaped: re-run the holistic bench after touching any of it.

**Dual-goal completion and clock-in-turns (2026-10-01, branch `mentor-dual`).** Two replies the
side-claims round left wrong. (1) "Faster or more resilient" still narrated one goal in 5/9 decks after both
lookups ran deterministically, and two prompt rules and a nudge had not changed it, so `chat._complete_dual`
now completes the reply: for each named goal axis the draft does not address (`verdicts.axis_addressed`: about
the axis AND names the measured add, or says no measured improvement in a sentence naming the axis; the bench
`dual` rubric uses the same function) it appends plain prose built only from that axis's swap result (verdict
and score, the measured swap with its kill-turn change, or "no measured swap ... a full search can be run from
the deck page"), applied before every gate attempt so the shipped text is the checked text. Template numbers
must be licensed: an early draft said "out of 100" and the gate rejected it. (2) The clock axis is a 0-100
score, so "+1.7 points" is ~0.2 turns, yet replies said "1.7 turns" and the gate passed the licensed number.
Clock swap results now carry `kill_turn_before/after/change` and a `clock_note`; gate check 8
(`verdicts.turn_confusion_reasons`, `ClaimBudget.clock_swaps`) flags "<n> turns" only when n matches a clock
score figure and no kill-turn figure; the prompt says clock changes are points. Live: dual 9/9, faster 9/9; the
replies now say "1.7 points ... 0.2 turns". Residuals: a reply that calls the speed half "ceiling" still gets
the speed sentence appended after it (accurate, slightly redundant); the saved JSON from `--json` can carry
mojibake apostrophes (PowerShell), which is a bench artifact, not a runtime one.

**Browser-verified end to end (2026-10-01, Opus, real UI on alt ports :8030/:8040 against a copied
Smaug deck, qwen3:14b).** Both new starter prompts render; "How could I make it faster or more
resilient?" answered honestly ("the quick in-chat search didn't find any measured improvements")
and offered **Run full swap search (clock)**; the button ran the real `/advise` (16 owned cards,
96 re-simulations, ~8.3 min), the panel reported completion, and re-asking answered from the cached
search: add Solemn Simulacrum, cut Ultimate Magic: Meteor, clock 20.1 -> 21.4, average kill turn
9.59 -> 9.43 (genuinely faster), cut redundancy-backed (wipe supply 18 vs target 3). Residuals found
reading the reply against the data, both gate-invisible:
- **The engine's swap brief labels Solemn Simulacrum's one-time death draw as "repeatable draw"**
  (`brief.add.functions`), and the mentor repeated it -- a licensed but WRONG tool fact, i.e. a
  `tags.analyze` draw-classification defect (`engine_draw`), not a mentor fabrication. Fix it in
  the tagger, not the gate. **Fixed 2026-10-01** (branch `fix/engine-draw-one-shot-triggers`):
  `tags._draw_counts` now sends one-shot "when ... dies / enters / leaves / cast" triggers to
  `draw_cards` (406 cards were engines only that way), and `swap_narrative`'s symmetric
  {card draw, repeatable draw} family -- which would have re-licensed the claim for any cantrip
  even with the tagger right -- is now one-directional (an engine is card draw, not vice versa).
- An unmeasured side claim ("cutting it doesn't hurt your interaction or resilience") rode along with
  a measured clock swap; only the clock was simulated. Same class as the generic closing advice in the
  first reply ("consider a scalable win condition"). A candidate for F1's phrase map or a prompt line
  restricting swap narration to the measured axis.
- The combined question ("faster OR more resilient") was answered for speed only.

**Side-claims residuals (2026-10-01, branch `mentor-sideclaims`).** (1) Unmeasured side claims: prompt
restricts swap narration to the measured axis; gate check 7 (`verdicts.unmeasured_side_claims`, shared with the
`faster`/`weakest`/`dual` rubrics) flags a "doesn't hurt / maintaining / unaffected" sentence whose object is a topic
word of an axis the turn's swap results did not measure (needs phrase AND topic, honest "only measured X" sentences and
the measured axis are ignored; 0 live firings in 90 replies). The generic closer is prompt-only (no gate). (2) Dual goals:
`_goal_axes`/`_missing_goal_axes` + one nudge, and stray axes are routed to a named goal (`_route_swap_axis`). A 9th bench
question `dual` was added (`--regrade` of older saved runs is unaffected: it walks saved rows by qid). **Found on the way:
main already failed `resilience` (0/3)** -- after an unavailable `get_measured_swaps` qwen3:14b stops at "run Advise"; `chat.ask`
now runs the owed `suggest_swap` itself (synthetic tool_calls need `type: function`). Still open: `dual` is 5/9 live
(model skips the speed half or omits the no-improvement statement); the Simulacrum "repeatable draw" tagger defect is untouched.

**Card types and the singleton rule (2026-10-01, Opus, branch `mentor-types`).** A live trap reply said "Sol Ring
is a non-basic land, so you can only run one copy" and PASSED: the name was licensed (via `check_legality`), only the
TYPE was invented. Four pieces, each found by fixing the previous one live: (1) **gate check 9** flags a licensed card
given a card type its own type line lacks (`verdicts.type_claim_reasons`; the type word must end the noun phrase, so
"a creature removal spell" never fires), and `chat._with_card_types` gives it the DB type line of EVERY licensed name,
not only `lookup_card` results; on a check-9 failure the loop runs `lookup_card` itself (`_lookup_mistyped_cards`).
(2) With the type corrected the model said **"you can run multiple copies of Sol Ring"** -- the fake type had been
hiding a wrong RULE. **Gate check 10** flags a multiple-copies permission (`verdicts.singleton_reasons`) unless
negated, about basic lands, or naming a card whose own oracle text overrides it (`copy_limit_exception`; the regex
matches exactly 13 cards store-wide: Relentless Rats, Persistent Petitioners, Seven Dwarves, Nazgul, ...);
`check_legality` and `lookup_card` now carry `singleton_rule` = CR 903.5b **read from the rules corpus at runtime**.
Check 5 (legality contradiction) now skips copy-count sentences ("can't add a second copy" is not "can't be added").
(3) **`chat._prelookup_question_cards`** looks up up to 3 cards the PLAYER names before the model writes, so a false
premise ("only costs 2 mana") can be corrected from the real cost. It first broke two fake-card traps ("Quantum Flux
Behemoth" contains the real card "Flux") -- a name embedded in a longer capitalised run is now skipped, and
possessives ("Craterhoof Behemoth's") still match. (4) A fraction in a tool result also licenses its percent form
(0.78 -> "78%"). Result on the trap: "Sol Ring only costs 1 mana, not 2 ... you can only have one copy", gated 3/3.
Residual (fixed the same day, below): qwen3:14b still paraphrases 903.5b as "one copy of any non-basic land card" even with the rule text in hand
(the conclusion is right; the wording is not) -- a prompt-level nit, not gate-checkable without false positives.

**Fix-all round (2026-10-01, Opus, branch `mentor-fixall`).** Three residuals closed. (1) **Gate check 11**:
counterspell framing for a deck without blue. The logic moved from the bench rubric into
`verdicts.counterspell_advice_reasons` (one definition for gate and bench); the gate arms it only when a tool result
says counterspells do not apply (`gate._says_counterspells_na`: `roles.counterspell.applicable` False,
`counterspell_applicable` False, `interaction_counts.counterspells` "n/a ...", or a known `deck_color_identity`
without U). "due to the absence of blue" now counts as an acknowledgement (Shelob's honest sentence used to fail the
rubric). (2) **Uncited rule auto-lookup** (`chat._lookup_uncited_rules`): when the gate refuses a citation that was
never looked up, the loop fetches that rule plus its parent and lettered siblings (cap 10) and tells the model to cite
only the sibling whose text matches. Live: the stack question's 601.2a draft was followed by a clean retry. (3) **Check
9b** (`verdicts.singleton_misstatement_reasons`): "one copy of any non-basic land" while the reply is about a licensed
non-land card is a misstated 903.5b; live the retry states the rule correctly 3/3. Check 10 also learned that a
prohibition can FOLLOW the copy phrase ("running two copies would be illegal / is not allowed") -- a live false
refusal of a correct answer. Result: holistic **90/90**, Shelob 48/52 (the four misses are scorer phrase markers on
correct replies: 704.5c, token nuance, Sol Ring stating `{1}` without "not 2", and a 603.3d reply that opens "You're
correct" before citing the right 603.3 -- the last is a real sycophantic opener worth a prompt line).

**Review + integration round (2026-10-01, Opus).** Three parked branches were reviewed and merged with the
mentor work: `fix/tags-interaction` (interaction tags gate the OBJECT; ccm/profile twins), and the engine-draw chain
(`fix/engine-draw-ability-word` incl. one-shot triggers, activated-draw engines, follow-on sentences, ability-word
prefixes) plus `fix/engine-draw-one-shot-triggers`' swap_narrative fix. Their commit messages carry the store-wide
and bracket measurements (bracket sweep identical throughout); the mentor-facing effect was A/B'd per bench deck:
key cards and verdicts move only where the fixes say they should (edicts and Chaos Warp now removal, Solemn no longer
a draw engine, Tymna interaction thin -> moderate), and `removal_coverage` is byte-identical. Review fixes that each
came from reading a failing reply, not from the rubric score: **check 12** (the reply opens "You're absolutely right"
about the player's rule number, then cites a different one or calls the asked one "unrelated"); **curly apostrophes**
(`verdicts.normalize_apostrophes`, applied once in `gate.check` and `rubrics.grade` -- every phrase regex is ASCII, so
"didn’t find a measurable improvement" read as no statement and "doesn’t hurt the deck’s removal power" slipped
past check 7); **check 1** no longer reads a word at a markdown/list/colon clause start as a card ("- **Faster:**
Consider the swap" refused three correct drafts); **check 9** resolves "it's a Sorcery" to the card named just before
it (the Rhystic Study premise echo); **9b** is scoped to the misstating sentence and its neighbours;
`list_deck_cards` now carries the deck colour identity so check 11 arms on a card-list answer; and the counterspell
acknowledgement learned "does not have blue" / "worth noting". Bench (three full runs on the merged tree, regraded
under the final rubrics): holistic 87, 88, 87 /90; Shelob 47, 49, 48 /52 (bar 47). Remaining misses vary run to
run (a key card not named, a win-route label) and the token-nuance trap's "based on general rules" guess persists.

**Phrasing corpus round (2026-10-02, Opus + qwen3:14b offload).** The bench's run-to-run variance (2-3 cells
between identical-code runs) came mostly from the model wording a correct answer in a way a shared vocabulary did
not recognise, and those vocabularies had only ever been grown one live failure at a time. So qwen3:14b -- the
mentor's own model -- was given labelled prompts and wrote 376 phrasings across 11 categories (positives and hard
negatives), reviewed by hand into `tests/engine/data/mentor_phrasings.json` (`test_mentor_phrasing_corpus.py`).
Measured before the fixes: no-improvement 14/36, admit-then-guess 0/36, counterspell pitch 7/24, plus 6/36
opponent-context false positives that were LATENT in the old verb list ("playing around counterspells"). Shipped:
**gate check 13** (`verdicts.guess_after_admission_reasons` -- admits the rules don't settle it, then answers from
general knowledge; 0 fires on 432 saved real replies), wider `NO_IMPROVEMENT_RE`, counterspell pitch/absence/
opponent handling, a bare "Right," opener for check 12. Tool precision: `removal_coverage` no longer says "only
counterspells answer spells ... no blue plays them" (the model repeated it as fact) and no longer hides a non-blue
deck's real spell answers; the profile keeps a real non-zero counterspell count. **The workflow is the lesson:**
when a rubric or gate check keeps flaking, generate the model's own phrasing space for that category (positives AND
hard negatives) before widening the regex; a new live miss goes into the corpus as an item.

**The acceptance gate for any future mentor change** is
`python scripts/mentor_holistic_bench.py` (9 decks x 8 questions, ~25 min, qwen3:14b on llama-swap
:8010; `--decks a,b --questions x,y` for a subset, `--regrade saved.json` to re-score offline) plus the
existing `scripts/mentor_bench.py` on Shelob (bar 47/52). Compare against the 80/81 row above; a
regression on any rubric is a defect until the replies are read and shown to be a rubric artefact.
Rubrics and the gate share ONE phrase vocabulary (`mythgauntlet.mentor.verdicts`), so a wording
that the bench calls a contradiction is also rejected live, and a verdict phrase added to the gate
is automatically graded.

Files round 8 touches: `src/mythgauntlet/mentor/{tools,chat,verdicts,diagnose,removal,deckview}.py`,
`src/mythgauntlet/ratings/{advisor,reference,redundancy}.py`, `src/mythgauntlet/server.py`
(`MentorChatRequest.advice`, trace `available` flag), root `server.py` (`_run_advise_job`,
`_valid_advice`, `_persist_advice`), `frontend/src/components/{MentorChatPanel,AdvisePanel}.jsx`,
`scripts/mentor_holistic_{bench,rubrics}.py`, `tests/engine/test_mentor_measured_swaps.py`,
`tests/test_mentor_advice_cache.py`, `tests/test_mentor_panel_labels.py`.

## Round 9 — confirming the player's wrong rule number, and a mis-decoded rules corpus (2026-10-05)

**Bench scorer.** `mentor_bench.py`'s false-premise and rule-number traps are now graded on the
TRUE fact (`_TRAP_TRUTH`: Sol Ring is `{1}`, Rhystic Study is an enchantment, 0 toughness is
704.5f, the priority-wait rule is 603.3) plus the affirming form of the bait, not on an honesty
phrase list. That closes the "honesty-marker whack-a-mole" above for these four traps: a correct
reply in any wording passes, an agreeing one still fails.

**Gate check 14 + asked-rule prefetch.** With the scorer honest, one real miss remained: "Doesn't
[the priority-wait rule] live at exactly 603.3d?" -> "You're absolutely correct ... rule 603.3d".
603.3d is real and was retrieved, so checks 2 and 12 both passed it; only the rule TEXTS show it
is wrong. Now:
- `chat._prefetch_question_rules` fetches a question's named rule and its whole family (parent +
  lettered siblings, the same `_rule_family` the uncited-rule retry uses) before the model answers.
- `ClaimBudget.rule_texts` carries every retrieved rule's text (`get_rule`, `search_rules`).
- Check 14 rejects a reply that CONFIRMS the asked rule when a sibling's text shares at least 2 more
  content words with the question than the asked rule's own text does.
- `gate._rule_dismissed` is the one "names the rule only to set it aside" test for checks 12 and
  14; it now reads negations next to the number ("**not** found in 603.3d", "603.3d does not
  address"). Its first live run had check 14 reject a real correction three times and fall back,
  because "not found in" was read as a confirmation.

Live, 3 runs per trap: 6/6 correct, every one gated. qwen3:14b's FIRST draft of the 603.3d answer
still agrees every time; check 14 catches it and the retry answers "No, it isn't 603.3d; it's
603.3", correctly describing what 603.3d does say.

**Check 14 against qwen3:14b's own wording (same round, phrasing-corpus technique).** The first
live version only knew "X is the one/rule" plus an agreement opener. qwen3:14b drafted 525 labelled
replies (wrong confirmations, corrections, confirmations of the RIGHT rule) for both trap pairs.
What that settled:
- **Wording alone cannot separate a correction from a confirmation.** "704.5c is the rule that
  applies when a player has ten poison counters" (a correction describing the wrong rule) and
  "704.5c is the rule you mean" (a confirmation) share the template. Check 14 therefore reads
  CONTENT: a clause naming the asked rule that carries the question's words that rule's own text
  lacks is a confirmation. So is a STRONG form ("the correct rule", "the rule you're thinking of",
  "applies here", "is indeed the"), and so is a WEAK form ("is the rule/one") when the reply never
  cites the better rule or cites it only as "background"/"setup"/"supporting" (demoted).
- **"On the right track" is NOT an agreement opener**: "You're on the right track, but the rule is
  704.5f, not 704.5c" is a correction (the check-12 corpus pins it). "Spot on", "I agree",
  "Absolutely", "Indeed" and "you got it" are agreement openers.
- Tuned on four batches; **two untouched batches: 147/150 confirmations caught, 90/90 corrections and
  right-rule confirmations clean** (0 false positives in all 255 such items). Committed 491
  deduplicated items as `rule_*` categories in `tests/engine/data/mentor_phrasings.json`. Known
  residual misses: "According to 704.5c, a creature with 0 toughness is indeed put into the
  graveyard" (the comma clause-split separates the number from the claim), "603.3d is the answer
  here, stating ...", and "603.3d is the one that deals with the actual handling ..., while 603.3
  is the rule that sets it into motion" (an unlisted demotion).

**The CR corpus was mojibake.** `fetch_comprehensive_rules` decoded the UTF-8 .txt with
`resp.text`, which falls back to Latin-1 when there is no charset, so 6,875 curly quotes were stored
as three junk characters each and quoted to players. `rulings._decode_cr` fixes the fetch and
`_repair_mojibake` heals old stores on load. Curly quotes now fold to ASCII for glossary keys and
BM25 tokens. (A `?` or `�` printed in a Windows console is the console's cp1252, not the data:
check with `ascii()` before chasing it.)
