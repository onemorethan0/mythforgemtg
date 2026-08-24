# SPEC — Deck Mentor (conversational LLM interface)

A chat surface where a user asks free-form questions about their deck — "what should I cut
for a wrath effect", "why does my curve feel bad", "can I sac this in response to that",
"what's the actual ruling on X" — and gets an answer from a local LLM instead of navigating
panels. The point of the feature is the thing that makes it dangerous: **it must never state
a wrong fact about a card, a rule, or the user's own deck.** A fluent wrong answer is worse
than no feature, because the user has no way to tell it apart from a right one.

## Why this is not "add a chatbox"

Myth Forge already has one precedent for LLM output that is allowed to make factual claims:
`ratings/swap_brief.py`. Its own docstring states the doctrine this spec extends:

> a fluent sentence is a very good disguise for a fabricated one, and on an MTG-facing
> surface a wrong claim about a card is a DEFECT, not an approximation.

Its answer was to split generation in two — a deterministic **claim budget** (`SwapBrief`:
every number and card name the narrative is *entitled* to use, computed offline by the
engine) and a narrative pass that is mechanically checked against that budget
(`allowed_numbers()`, `allowed_card_names()`) before it reaches the user. Nothing about that
pattern is specific to swap explanations. This spec is "make the claim-budget pattern work
for an open-ended conversation instead of one fixed template" — which is a materially harder
problem (unbounded question shape, multi-turn state, and a whole factual domain — rules text
and rulings — that the repo currently has **zero data for**), not a different approach.

Training a model is explicitly on the table per the user's ask, and it has a real place in
this design (Phase 3, below) — but it is **not** the mechanism that prevents hallucination.
Nothing about fine-tuning makes a model's factual claims checkable; a fine-tuned model that
sounds more confident while still occasionally inventing a ruling is a regression, not a fix.
The mechanism that prevents hallucination is retrieval + tool-calling + a mechanical gate,
exactly as `swap_brief` already proved for the narrower case. Training only ever improves
*how* the model uses that mechanism (latency, voice, tool-call reliability) — see Phase 3.

## Two factual domains, and only one of them exists yet

Every question the mentor will face falls into one of two domains, and they need genuinely
different grounding:

**A. Deck telemetry — already computed, already trustworthy.** "Why is my curve bad", "what's
over-supplied", "suggest a swap", "is this deck strong for my pod", "how off-meta is this
build" are all questions the engine (`:8020`) already answers deterministically:
`deck_quality.assess_curve/assess_colors/assess_mana_base`, `ratings.redundancy`,
`ratings.card_impact.assess_card`, `ratings.advisor.advise` (which already emits a
`SwapBrief`), `lift_stats`, `deck_themes`. **The mentor must never compute these itself.** Its
only job here is: call the right measurement, and narrate only what came back.

**B. Rules and card rulings — no corpus exists in this repo today.** Grepped for it — nothing.
Oracle text ships in `data/cards_slim.json`, but oracle text alone does not answer "does this
actually work the way I think", which is precisely the class of question this feature is
supposed to be *for* (the standing project bar — [[user-myth-suite-goal]] — is casual
bracket 1-3 pod-legality/fun questions, and rules interactions are exactly what confuses a
casual table). This is real, un-optional scope: **Phase 0 below is a data-ingestion project
before there is anything to gate against.** Any version of this feature that answers rules
questions from the model's training-time knowledge of Magic rules, ungrounded, is exactly the
failure mode the user is asking to avoid — an LLM's parametric knowledge of the comprehensive
rules is not verifiable and WILL occasionally be wrong in a way that looks identical to being
right.

## Phase 0 — the rules/rulings corpus (data layer, no chat, no UI)

New module `mythgauntlet/data/rulings.py`, mirroring the existing `edhrec.py`/`spellbook.py`
shape (explicit fetch command, cached under `data/`, versioned by snapshot date, offline
after that):

- **Scryfall rulings bulk data** (`bulk-data` → `rulings` object, same endpoint family
  `cards_slim.json` already uses for `oracle_cards`). Per `oracle_id`: `[{published_at,
  source, comment}]`. Slim, cache as `data/rulings_slim.json`, keyed by `oracle_id` so it
  joins straight onto the existing card index — no new identity problem to solve.
- **Comprehensive Rules** (official WotC .txt, versioned by release date). Parsed into
  `{rule_number, text}` records — the numbering (`702.19b`, `104.3a`, …) is the citation unit
  the gate will check against. Store as `data/comprehensive_rules_<date>.json`.
- **Retrieval:** exact rule-number lookup and exact/fuzzy card-name lookup are just dict
  lookups (already the pattern the app uses everywhere — `scryfall_client`, `collection_pool`
  rank keys). For free-text rules questions ("what's a triggered ability") a BM25 index over
  CR section text (`rank-bm25`, pure Python, no embedding model, no GPU) is the right first
  tool — the corpus is small (~700 numbered top-level rules) and CR prose is dense with the
  exact terminology users will actually type, which is where lexical search outperforms
  semantic search. Do not reach for an embedding index until BM25 is measured and found
  insufficient; adding infra the precision requirement doesn't need is its own risk.
- **This phase ships nothing user-visible.** It is done when `lookup_rulings(name)` and
  `search_rules(query)` return correct, citable results against a hand-checked gold set (see
  Phase 4). Testable standalone, same as every other `data/` module in this repo.

## The tool contract — the mentor's only way to assert anything

The chat model runs a tool-calling loop (not a single completion). Every fact in its answer
must trace back to a tool result from *this turn* — this is the literal generalization of
`SwapBrief.allowed_numbers()`/`allowed_card_names()`.

| tool | wraps | domain |
|---|---|---|
| `get_deck_stats(deck_id)` | `compute_stats` (curve/colors/mana_base/archetypes/offmeta) | A |
| `assess_card(deck_id, card_name)` | engine `/card-impact` | A |
| `suggest_swap(deck_id, axis?)` | engine `/advise` → `SwapBrief` | A |
| `lookup_card(name)` | `cards_slim.json` exact/fuzzy | A/B (oracle text) |
| `lookup_rulings(name)` | Phase 0 rulings corpus | B |
| `search_rules(query)` | Phase 0 BM25 over CR | B |
| `get_rule(number)` | Phase 0 CR exact lookup | B |

No tool means no claim. If a question needs a fact no tool can produce (e.g. "what will the
next set do to my deck"), the correct answer is the mentor saying so — not a guess.

## The gate — mechanical, not stylistic

After the model drafts a reply for a turn, before it reaches the user:

1. **Card names** — extract every substring matching a known card name (same index
   `lookup_card` uses). Every one must appear in a tool result returned *this turn* (the
   deck's own cards, or an explicit lookup) — same rule `SwapBrief.allowed_card_names` already
   enforces for swap prose, just applied to the whole reply instead of one template.
2. **Numbers** — same idea as `allowed_numbers()`: every numeric claim (curve deviation,
   oversupply, EDHREC rank, a delta) must appear, rounded, in a tool payload from this turn.
3. **Rule citations** — every CR number (`702.19b`) or quoted ruling sentence must have been
   returned by `search_rules`/`get_rule`/`lookup_rulings` this turn. A citation to a rule
   number the mentor never retrieved is a fabrication by construction and is rejected
   regardless of whether the number happens to be real.
4. **On rejection: regenerate, don't silently strip.** Silently deleting the offending clause
   turns a caught fabrication into an unnoticed one with the surrounding sentence still
   claiming it. Retry with the specific violation named in the retry prompt, capped at N
   attempts, then fall back to a visibly-honest "I can look that up, but I'm not confident
   enough in what I found to state it as fact" — this repo's own standing rule
   ([[feedback-magic-precision]]): an honest under-count beats a confident fabrication.

The gate is pure Python over strings and tool-result payloads — no second LLM call needed to
implement it (a second model "checking" the first is not a mechanical check, it's a second
chance to hallucinate).

## Model / serving

Chat needs native tool-calling, multi-turn. **Smoke-tested 2026-08-24** against both local
candidates behind llama-swap `:8010`, 4 scenarios covering the tool contract's hard cases
(needs a card lookup, needs a rules lookup, a trap question about a nonexistent card with the
mock tool returning `found:False`, and a question needing no tool at all). This is n=4, not
the real Phase 4 gold-set bench — it's a go/no-go signal for which model Phase 1 builds on,
and both should still run the full `mentor_bench.py` gold set once Phase 0/1 exist.

**Result: `qwen3:14b` won cleanly, 4/4.** It called a tool exactly when one was needed, made
no tool call for the no-tool case, and — the case that matters most — on the trap question it
called `lookup_card`, got `found:False` back, and reported "no card named … found" rather than
guessing. Converged to a final answer in 2 turns on every case that needed a tool.

**muse-glimmer failed two of four, in two different directions, which is worse than failing
consistently.** On the rules-lookup case it got the correct rule (704.5c) back on the *first*
tool call, said so in its own reasoning trace ("We have found rule 704.5c … Could also
provide context"), and then kept calling `search_rules` two more times with rephrased queries
instead of answering — never producing a final reply within 3 turns. On the trap question it
did the opposite: it answered directly ("Zzyzx Prism Wyrm is a card whose exact wording …
are not documented") **without calling `lookup_card` at all**, i.e. skipped verification
entirely. It happened to land on a defensible-sounding hedge, but the mechanism was "the model
decided it didn't need to check" — indistinguishable, from the outside, from a model that
skips verification on a card it's *wrong* about and states something false with the same
confident hedge-shaped phrasing. An inconsistent verifier is a harder problem than a
consistently-conservative one, because the claim-budget gate assumes *something* to check the
draft against — a model that sometimes skips the tool call entirely leaves the gate nothing
to verify against on exactly the turns where it matters most.

So: **`qwen3:14b` is the Phase 1 default.** It's also already the app's resident theming
model — no added VRAM footprint on top of what a build session already pays for. Keep
muse-glimmer as a documented fallback only if the real gold-set bench (larger n, real deck
data, real CR text once Phase 0 lands) turns up a qwen3:14b failure mode this smoke test
didn't — not because of any capability muse-glimmer is expected to add; this test found no
evidence it's the better fit for *this* discipline specifically. `qwen2.5-coder:14b` remains
out per existing project doctrine (no native `tool_calls`).

**Temperature low** (0.1-0.2, matching the offload-harness convention for anything that isn't
creative prose) for the tool-selection and drafting steps — precision, not variety, is the
entire point of this feature. qwen3:14b ran this test at temp 0.2 with `enable_thinking:false`
(the themer's existing llama.cpp convention); no need to depart from it.

## API / UI

- `POST /api/mentor/chat` on the existing Forge server (`:8000`): `{deck_id, message,
  history}` → runs the tool loop against `:8010` (model) and `:8020` (engine) + the Phase 0
  corpus, returns `{reply, citations[], tool_trace[]}`.
- Stream tool-call progress for perceived latency ("checking your mana curve…", "looking up
  CR 702.19b…") — same SSE mechanism already used for build progress — but the **final prose
  is released as one gated block**, never streamed token-by-token, because the gate can only
  check a complete draft.
- Every citation (rule number, ruling) renders as an expandable chip showing the verbatim
  retrieved text, not just the model's paraphrase — lets the user catch anything the gate
  missed, and makes the grounding visible rather than asserted.
- A regenerate-then-honest-fallback reply must be visually distinct from a normal one (e.g.
  an amber "couldn't verify precisely" treatment) — the UI must never let an unverified claim
  *look* as confident as a verified one, mirroring how `card_impact._cut_sentence` already
  says out loud when a measurement doesn't back a claim rather than faking it.

## Precision bench — the actual acceptance gate

Matches this repo's existing measurement culture (`builder_bench.py`, the gold-set tables
baked into `swap_brief`/`collection_pool`/`theme_match` docstrings). New
`scripts/mentor_bench.py`:

- A hand-curated gold set (~75-100 Q&A pairs) spanning both domains, including **deliberate
  trap questions** designed to bait fabrication: a card name that doesn't exist, a rules
  interaction with no official ruling, a CR number that was never printed, a question about
  a card not in the user's deck. A correct answer to a trap question is "I don't have that" —
  scored as a pass; any confident answer to a trap question is scored as a hard fail.
- The gate's own reject rate is itself a tracked metric — same "no silent caps" instinct as
  everywhere else in this repo: if the gate is passing 100% of drafts, either the model never
  errs (unlikely) or the extraction is too loose to catch anything, and that's worth knowing
  before shipping.
- This bench is the ship gate for any prompt change, tool addition, or model swap —
  reject-on-trap-question failures block a release the same way a broken test does.

## Phasing

0. **Rulings/CR ingestion.** Offline data module, no model in the loop. Ships when
   `lookup_rulings`/`search_rules` pass a hand-checked gold set.
1. **Tool loop + gate, CLI only** (`mythgauntlet mentor` or a standalone script) — no frontend.
   This is where model choice (qwen3:14b vs muse-glimmer) gets resolved empirically, and where
   `mentor_bench.py` first runs. Hardest correctness problem, solved before any UI work.
2. **`/api/mentor/chat` + a chat panel in Forge**, wired to a real deck, reusing Phase 1's
   loop/gate unchanged.
3. **Optional: distill.** Only after 0-2 are bench-passing and in real use — fine-tune/LoRA a
   smaller local model on the corpus of gated, human-approved transcripts, purely to cut
   latency/VRAM or improve tool-call reliability. The gate stays in the serving path
   regardless of which model drafts the reply; training never removes the need for it.

## Explicitly out of scope

- Answering from the model's own training-time Magic knowledge, ungrounded. Every rules claim
  routes through Phase 0's corpus or it doesn't get made.
- cEDH-register tuning advice — the mentor inherits the same casual bracket 1-3 framing as the
  rest of MythGauntlet ([[user-myth-suite-goal]]).
- Real-time token streaming of the final answer (see API/UI above) — a partial, ungated
  sentence on screen is a claim the user can read before it's been checked.
