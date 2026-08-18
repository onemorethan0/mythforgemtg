# Local-model offload harness

Dispatches bulk classification to `qwen3` on the llama-swap gateway (`127.0.0.1:8010`).
Written after a first attempt failed, and **every design choice here is a fix for a specific
measured failure** — read this before changing it, because each rule looks removable and isn't.

    python scripts/offload/gold_themes.py qwen3:32b     # score against hand labels FIRST
    python scripts/offload/sweep_themes.py              # two-model ensemble over the corpus

## The five rules that make it work

**1. Shortlist in code, then ask ONE narrow question.**
The first version asked the model to pick from all 43 themes, name a missing archetype, and
emit JSON, for 4 cards per call: **2/4** on the gold set, with one batch returning malformed
JSON. An A/B then showed the model answers the *same* discrimination correctly (4/4, both model
sizes, thinking on or off) when the question is narrow. **The failure was task complexity per
call, not capability.** `theme_shortlist.shortlist()` narrows 43 → ~2 candidates
deterministically; `client.choose()` asks a single multiple-choice question with no JSON to
malform.

**2. Define your jargon.** `aristocrats`, `voltron` and `draw_matters` are this project's
private vocabulary, not English. Choosing between undefined labels is guessing.
`client.THEME_DEFS` is what took the gold set from 3/8 to 6/8 — a bigger jump than any prompt
wording. Definitions must name Magic's **templating**, not just the concept: three cards failed
on a concept-only `aristocrats` definition, including one whose text literally says "dies".

**3. Definitions of base-rate-trap themes must be restrictive.** `voltron_combat` scores STRONG
on 19.35% of every card in Magic, so a loose definition makes it swallow anything mentioning
combat. Same for `counters`, whose "or other counters" wording matched slumber counters.

**4. `/no_think`, and an empty reply is an ERROR.** qwen3 is a hybrid reasoning model: with
thinking on it spent the whole token budget in the trace and returned **empty content**. The
first parser scored empty as the answer `none`, so every card came back unlabelled and it looked
like a judgement failure. `client.EmptyReply` now separates "the model said none" from "the
model said nothing".

**5. One model per PASS, never interleaved.** llama-swap keeps a single model resident, so
alternating 32b/14b per card forces a full unload+reload **every item** — the interleaved sweep
did not finish 80 cards in ten minutes. Two passes cost two model loads instead of a hundred and
sixty. The same sweep then took 19 minutes, of which the 14b pass was **23 seconds**.

## The two models fail in opposite directions — use both

Measured on an 8-card hand-labelled gold set:

| | assigning a label | answering "none" |
|---|---|---|
| `qwen3:14b` | **1/4** | **4/4** |
| `qwen3:32b` | **4/4** | 2/4 |

So `sweep_themes.py` runs both and trusts only **agreement**, which was 3/3 correct on gold and
4/4 correct on the real sweep. Disagreement becomes a human review queue instead of a silent
guess. Over the 80 zero-theme commanders: **70% agreement** (4 on a theme, 52 on "none"), 24
queued — a review list a quarter the size of the input.

## What this is and is not for

Good: closed-vocabulary extraction and classification where the vocabulary is defined, and
drafting a self-contained module from a precise spec (this is how `collection_pool`,
`deck_quality` and `theme_match` were drafted).

Not good: anything where a near-miss becomes a wrong card in a user's deck. Model output here is
a **candidate**, and a candidate still has to survive the measurement procedure in
`docs/ROADMAP.md` §S1 before it changes the taxonomy. The four themes this sweep proposed were
each verified against oracle text by hand before any pattern was widened.

**Tear the stack down when you are done** — it holds ~18 GB of VRAM.
