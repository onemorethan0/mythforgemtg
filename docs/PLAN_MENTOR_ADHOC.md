# PLAN — Deck Mentor: open-ended "tell me about my deck" questions

Written 2026-09-30, refined the same day into an implementation handoff. Goal: make the mentor
good at ad-hoc, holistic questions — *what does this deck do well / poorly, how does it win,
how do I make it faster / more resilient, what are my weakest cards* — not just the narrow
factual questions `scripts/mentor_bench.py` covers.

**Required reading before any task:** `docs/MENTOR_HANDOFF.md` (seven live campaign rounds,
the method, every gate false-positive already fixed) and this file end to end. The doctrine
does not change: **tools assert, the model narrates, the gate checks.** Every new fact the
mentor can state must come from a tool result; nothing here lets the model compute a rating,
a verdict or a set relationship itself.

---

## 1. Where it stands — measured

Eight open-ended questions were asked of `mentor.chat.ask()` (qwen3:14b, live llama-swap)
against a real corpus deck — Shelob, Child of Ungoliant (`corpus/decks/archidekt-1010839.txt`,
labelled B1) — and every answer was checked against what the engine itself measures for that
deck (`analyze_deck(..., run_resilience=True)`, `tool_get_deck_stats`, `tool_suggest_swap`).

**8/8 came back `gated: true`. By ground truth, about 1 of 8 was a good answer.** The gate's
"no fabricated name/number/rule" was true every time; every failure is in a class the gate
cannot see.

| question | tools called | reply said | engine actually measures |
|---|---|---|---|
| What does it do well / poorly? | `get_deck_stats` | ramp/removal/wipes on target; "lacks counterspells — a significant gap"; black short | Black-source read correct. **Counterspell advice wrong for Golgari** (target 3 is a colour-blind population baseline). Missed both measured strengths (Consistency 82, Resilience 93) |
| Why? Which cards do the most work? | `get_deck_stats`, `suggest_swap` | "the ramp cards are likely the most impactful" — **zero card names** | `insight.key_cards` already lists them (Cultivate, Beast Whisperer, Sylvan Library, Skyfisher Spider…) — no tool exposes it |
| How could I make it faster? | `suggest_swap(speed)` | "cut Gloomwidow's Feast… slightly faster" | **Tool found NO improving swap** (`suggestions: []`); the reply narrated `AdviceReport.cut` (the pool head) as advice. That card is the deck's own theme card |
| How resilient to a wipe? | `get_deck_stats`, `get_bracket_estimate` | "somewhat vulnerable… no dedicated removal" | **Resilience 93/100, listed as a strength.** Inverted verdict; also contradicts answer 1 |
| How does it win? | `get_deck_stats` | "a control deck… powerful late-game finishers" | **Midrange goodstuff, 27 creatures, races with combat, goldfish kill ~T9**, finisher supply 0 |
| Weakest cards? | `suggest_swap(consistency)` | "Gloomwidow's Feast" | Empty suggestion list again, narrated as a finding |
| Biggest weakness vs a B3 pod? | `get_bracket_estimate` | B1, thin mana base (78%) | Defensible — but the first draft was gate-rejected for "citing 3", **which the player typed** |
| Is removal good; what can't it answer? | `get_deck_stats`, `suggest_swap` | "might struggle vs high toughness, tokens, flyers" | Pure speculation; no tool reports what removal can target |

Ground-truth `get_deck_stats.roles` for that deck (note: **`supply` is a STRENGTH score, not a
card count** — `redundancy.card_roles` scores a wipe 3.0, a counterspell 3.0, a tutor 2.0):
`counterspell 0/3, draw 15/16, finisher 0/2, ramp 14/14, removal 4/4, tutor 2/4, wipe 3/3`.
The deck has ONE board wipe; the tool's "wipe 3.0" was narrated as "wipes at target", and a
later answer read it as three. `insight` says "1 wipes" — it is right, the unit is the bug.

---

## 2. Root causes

- **G1 — The mentor cannot see the Power Profile.** `analyze_deck` already computes six axes,
  `insight.axis_why`, `strengths`, `weaknesses`, `archetype`, `gameplan`, `pod_read`,
  `key_cards`, resilience, pod clock, wincon redundancy. `tool_get_bracket_estimate` calls it
  with `run_resilience=False` and keeps only the bracket. Biggest lever.
- **G2 — No card-level view of the deck.** No tool lists the deck's cards or role membership.
- **G3 — `suggest_swap` is toothless and misleading.** `max_eval=4, cut_pool=1` rarely clears
  `min_delta`; the empty result still carries a top-level `cut` that reads like advice.
- **G4 — Role numbers mislead twice.** (a) `supply` is a strength score presented next to
  `target` with no unit, read as a card count. (b) targets are colour-blind: every non-blue
  deck "lacks counterspells"; `finisher 0/2` reads as a gap on a deck whose plan is combat.
- **G5 — The gate checks grounding, not verdicts.** "vulnerable to wipes" / "a control deck"
  carry no name, number or rule. For deck verdicts this IS mechanizable: the engine holds the
  structured answer.
- **G6 — No tool routing for holistic questions** in `SYSTEM_PROMPT`.
- **G7 — Numbers the player typed aren't licensed** (names were, since round 5).
- **G8 — "How do I improve X" has no measured drivers.**
- **G9 — The real swap search (~583 s) can't run inside a 120 s chat turn.**
- **G10 — "Poorly" has no reference point** (no per-bracket axis distributions).
- **G11 — Output shape:** `chat._strip` collapses all whitespace; `MAX_CHARS 1400` /
  `max_tokens 700` will reject complete overviews once G1 lands.
- **G12 — Follow-ups re-simulate** (fresh `analyze_deck` per tool call, per turn).
- **G13 — The bench can't see any of this** (grades non-trap cases on `gated` alone → 8/8).

---

## 3. Working rules for whoever implements this (Sonnet agents + local chain)

1. **Branch/worktree.** All work on branch `mentor-adhoc` in its own worktree. Never touch
   files you weren't asked to: `main`'s working tree carries another session's uncommitted
   `sim/game.py`, `sim/tier2.py`, `agents/greedy.py`, `corpus/decks/*` — none of that is yours.
   Commit per task (message `Mentor adhoc <task id>: ...`, with the repo's usual trailer).
   **Do not push and do not merge** — the orchestrator reviews and merges.
2. **Environment.** `MYTHGAUNTLET_DATA` / `MYTHGAUNTLET_STORE` (user env) point at the sibling
   `Documents\mythgauntlet\{data,ccm}` — that IS the live store (see CLAUDE.md, corrected
   2026-09-30). Leave them alone. Python is `python` (3.14). Tests: `python -m pytest tests -q`
   (baseline ~1569 passing) — must stay green after every task. Engine tests that need cards use
   the `make_card` / `empty_store` fixtures in `tests/engine/conftest.py`; copy the `_ctx(...)`
   pattern from `tests/engine/test_mentor_tools.py`.
3. **Live model.** llama-swap on `127.0.0.1:8010` (qwen3:14b). Check it's up
   (`curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8010/`). If it's down, start
   `E:\llama\start-llama-swap.bat` and **kill it again before you finish** if you started it.
   Do not start ComfyUI or `python server.py` (that starts GPU services). The engine can be
   driven in-process exactly as `scripts/mentor_bench.py` does — no :8020 needed.
4. **Local-LLM offload (the "local chain").** Tasks marked **OFFLOAD** are drafted by the local
   worker, not hand-written: write a spec under `docs/specs/mentor_adhoc/<task>.md` (exact
   export signatures, data shapes copied from THIS file, a worked gold-set table, "output only
   code"), then run
   `python scripts/offload.py docs/specs/mentor_adhoc/<task>.md <target> --model qwen3:14b`
   (use `--model muse-glimmer` for anything with non-trivial logic; it's slower, ~3-4 min, and
   needs the default `--max-tokens`). **Read every drafted file before landing it** — expect 1-2
   real bugs per file. The commit message says which parts were drafted locally and what review
   changed. Tasks marked **CLAUDE** are written directly (surgical diffs into existing files,
   gate logic, anything that reads MTG rules text — a near-miss there is a defect).
5. **Magic is precise.** An honest under-count beats a confident fabrication. When a heuristic
   can't decide, it declines and says so in data (`"unknown"`, `available: false`), never
   guesses.
6. **Verify live, not just in tests.** Every phase ends with the holistic bench (task A0) run
   against real decks through the real model; a phase isn't done until its exit check passes.

---

## 4. Tasks

### Phase A0 — Acceptance harness first (G13)

**A0. `scripts/mentor_holistic_bench.py`** — **OFFLOAD** (scaffold) + **CLAUDE** (grading).
- Loads a deck exactly like `mentor_bench.py` (`load_card_db`, `Deck.parse_text`, `resolve`,
  `rulings.load_comprehensive_rules`, `rulings.load_rulings_db`, `load_store`,
  `SimConfig(turns=DEFAULT_ANALYZE_TURNS, runs=150, seed=42)`, `MentorContext(...)`).
- Computes ground truth once per deck: `analyze_deck(resolved, cfg, store, run_resilience=True)`
  plus `tool_get_deck_stats(ctx).data` and deck colour identity (union of
  `c.color_identity for c in resolved.commanders`).
- Asks the 8 questions from §1 (Q2 as a follow-up with Q1's history), then grades each with
  **mechanical rubrics that read the ground truth** — never an LLM judge:
  | id | question | pass when |
  |---|---|---|
  | overview | What does this deck do well and poorly? | every verdict phrase present agrees with `verdicts.classify` (A-verdicts below); mentions ≥1 of `insight.strengths` topics if non-empty |
  | cards | Which cards are doing the most work? (follow-up) | names ≥1 card from `insight.key_cards` |
  | faster | How could I make this deck faster? | if the speed swap result is empty: contains a "no measured improvement" phrase and no `cut <card>` recommendation; else names the measured add AND cut |
  | resilience | How resilient to a wipe; how to improve? | resilience verdict phrase matches the band (≥65 resilient, <40 vulnerable, else moderate); no opposite phrase |
  | wincon | How does this deck win? | archetype words match `insight.archetype` family; does not name an unmeasured wincon (e.g. "finishers" when finisher supply is 0) |
  | weakest | What are the weakest cards? | same empty-result rule as `faster`; any card named must be in the deck |
  | vs_b3 | Biggest weakness vs a bracket 3 pod? | `gated` true on first attempt (no "cites 3" rejection) |
  | removal | Is my removal good enough; what can't it answer? | after Phase B: every "can't answer X" claim is backed by `removal_coverage`; before Phase B: marked `n/a` |
  | colour | (any reply) | never recommends counterspells when "U" not in deck identity (or any colour outside identity) |
- Deck set: 8-10 corpus decks spanning archetypes — include Shelob (`archidekt-1010839.txt`),
  one partner deck, one spellslinger, one tokens/go-wide, one voltron, one combo-ish B4.
  Pick by reading `corpus/decks/*.txt` headers; record the chosen list as a constant.
- Output: per-deck/per-question PASS/FAIL table + `--json out.json` with replies, tool traces,
  rejections and the rubric's reason string. `--decks` / `--questions` filters.
- The rubric's phrase maps live in `src/mythgauntlet/mentor/verdicts.py` (task F1) so bench and
  gate cannot drift. For A0 create that module with just the phrase maps + `classify` helpers;
  F1 wires it into the gate.
- **Exit:** runs end to end; baseline numbers recorded in this file's §6 log (expect most FAIL).

### Phase A — Let the mentor see what the engine knows (G1, G3, G6, G7, G11, G12)

**A1. Analysis cache** — **CLAUDE**, `src/mythgauntlet/mentor/tools.py`.
- Add `_analysis_for(ctx) -> DeckAnalysis`, memoised per process in a small bounded LRU
  (`functools.lru_cache` can't hash ctx; use an `OrderedDict`, maxsize 8) keyed by
  `(deck_key, ctx.cfg.runs, ctx.cfg.turns, ctx.cfg.seed, tuple(ctx.themes))`, where
  `deck_key` = sorted `(name, qty)` of `resolved.cards` + commander names. Always
  `analyze_deck(ctx.resolved, ctx.cfg, ctx.store, run_resilience=True)`.
- `tool_get_bracket_estimate` switches to `_analysis_for(ctx)` (output shape unchanged).
- Test: two calls on the same ctx run `analyze_deck` once (monkeypatch a counter).

**A2. `get_power_profile` tool** — **CLAUDE**, `tools.py` (+ schema + `_TOOL_FUNCS`).
Returns (all from `_analysis_for(ctx)`; scores rounded to 1 dp):
```python
{
  "found": True,
  "archetype": insight.archetype,              # e.g. "Midrange goodstuff"
  "gameplan": insight.gameplan,
  "pod_read": insight.pod_read,
  "strengths": insight.strengths,              # list[str]
  "weaknesses": insight.weaknesses,            # list[str]
  "axes": {                                    # keys = advisor.AXES keys, + "pod"
    "consistency": {"score": .., "why": insight.axis_why["Consistency"]},
    "speed":       {"score": advisor.axis_score(a, "speed"), "why": axis_why["Speed"]},
    "resilience":  {"score": .., "why": axis_why["Resilience"]},
    "interaction": {"score": .., "why": axis_why["Interaction"]},
    "ceiling":     {"score": .., "why": axis_why["Ceiling"]},
    "pod":         {"score": a.pod.score, "why": axis_why["Pod (multiplayer)"]},
  },
  "weakest_axis": advisor.weakest_axis(a),
  "clock": {"avg_kill_turn": r.avg_kill_turn, "goldfish_kill_rate": r.goldfish_kill_rate,
            "avg_commander_turn": r.avg_commander_turn, "commander_cast_rate": ..,
            "keep_rate": .., "curve_efficiency": .., "fast_kill_turn": ceiling.fast_kill_turn,
            "pod_close_turn": pod.pod_close_turn},
  "resilience": {"score": .., "wipe_turn": a.wipe_turn, "kill_delay_turns": ..},
  "interaction_counts": {"spot_removal": .., "counterspells": .., "board_wipes": ..,
                         "breadth": ..},        # CARD COUNTS from InteractionReport
  "key_cards": [{"role": k.role, "cards": k.names, "more": k.more} for k in insight.key_cards],
  "wincon_redundancy": _to_jsonable(a.wincon_redundancy),
  "bracket": {"bracket": b.bracket, "label": b.label, "plays_up": b.plays_up},
  "verdicts": verdicts.classify_profile(a),     # A0/F1: {"resilience": "resilient", ...}
}
```
`card_names=` licenses every `key_cards` name + commander names. Map `axis_why` keys exactly as
`insight.build_insight` spells them (`"Pod (multiplayer)"` etc.) — read the source, don't guess.
Tool description: *"The deck's measured Power Profile — what it does well and poorly, how it
wins, speed, resilience to wipes, interaction, key cards per role. Call FIRST for any
strengths/weaknesses/observations/'how does it win'/'how fast'/'how resilient' question."*
Test: synthetic deck via fixtures returns every top-level key; key_cards names are licensed.

**A3. Prompt routing** — **CLAUDE**, `mentor/chat.py` `SYSTEM_PROMPT`. Add a paragraph:
strengths / weaknesses / observations / how it wins / speed / resilience / interaction /
"is it good" ⇒ `get_power_profile` first; describe the archetype, win route, speed and
wipe-resilience ONLY from its fields (`verdicts` especially); when naming cards that "do the
work", use `key_cards`; for improvement questions state the weakest axis and its `why`, then
call `suggest_swap` (or later `diagnose_axis`/`get_measured_swaps`). Keep every existing rule.

**A4. `suggest_swap` result shape** — **CLAUDE**, `tool_suggest_swap`.
- Delete the top-level `cut` from the returned data; when `report.suggestions` is empty return
  `{"found": True, "improving_swap_found": False, "axis": .., "baseline": ..,
  "evaluated": .., "message": "Tested N owned cards as adds on <Axis>; none beat the noise
  floor (min gain <min_delta>). No measured swap to recommend."}` and license NO card names.
- Non-empty: add `"improving_swap_found": True`.
- Prompt: an empty result is reported as "I didn't find a measured improvement from your
  collection", never as a cut.
- Tests: empty report → no `cut` key, empty `card_names`; non-empty keeps add/cut licensing.

**A5. License numbers the player typed** — **CLAUDE**, `mentor/gate.py` `check()`.
Scoped: numbers matched by `\bbracket\s*([1-5])\b` (and "B1".."B5") in `question` are added to
the free set for that turn only. Nothing else. Test: "bracket 3 pod" question + reply citing
3 → no reason; reply citing 3 with no bracket mention in question → still flagged.

**A6. Output shape** — **CLAUDE**, `chat.py` + `gate.py`.
- `_strip`: keep paragraph breaks (collapse runs of spaces/tabs, normalise 3+ newlines to 2),
  still strip `<think>`, fences, "Answer:" labels.
- When the tool trace includes `get_power_profile`: `max_tokens=1100`, gate `MAX_CHARS=2400`
  (pass a `max_chars` param into `gate.check`, default unchanged).
- Tests for both.

**A7. Role units in `get_deck_stats`** (G4a) — **CLAUDE**. Each role entry becomes
`{"supply": .., "target": .., "cards": <int card count>, "unit": "strength"}` where `cards`
counts nonland cards (qty-weighted) with that role in `redundancy.card_roles(tags.analyze(c))`,
matching `role_supply`'s commander exclusion. Prompt: talk in `cards`, compare with
`supply`/`target` only as "over/under target". Test: one wipe card → `cards == 1, supply == 3.0`.

**Phase A exit:** holistic bench on all decks: `resilience`, `wincon`, `faster`, `weakest`,
`vs_b3`, `cards` pass on ≥80% of decks; `mentor_bench.py` still ≥47/52; full pytest green.
Record numbers in §6.

### Phase B — Card-level visibility (G2)

**B1. `list_deck_cards(role: str | None = None)`** — **OFFLOAD** (qwen3:14b; pure function
`deck_card_rows(resolved) -> list[dict]` in new `src/mythgauntlet/mentor/deckview.py`, then
CLAUDE wires the tool). Row: `{"name", "qty", "mana_value", "type_line", "roles":
sorted(card_roles(tags.analyze(card)))}` for commander(s) (flag `"commander": True`) + every
card; lands included with `roles: ["land"]`. `role` filters (unknown role → `found: False`
listing valid roles). Licenses returned names. Test via fixtures.

**B2. `removal_coverage()`** — **CLAUDE only** (reads rules text). New
`src/mythgauntlet/mentor/removal.py`, `coverage(resolved) -> dict`:
per interaction card (`fx.removal or fx.board_wipe or fx.counterspell`) → `{"name",
"kind": "spot"|"wipe"|"counter", "hits": subset of {"creature","artifact","enchantment",
"planeswalker","land","nonland_permanent","spell","any_permanent"}, "mode":
"destroy"|"exile"|"bounce"|"damage"|"minus"|"sacrifice"|"counter"|"unknown", "speed":
"instant"|"sorcery", "restrictions": [verbatim clause strings, e.g. "power 3 or less"]}`,
derived from `card.oracle_text` + `type_line`, clause by clause; anything not confidently
parsed → `"unknown"` (never guessed). Aggregate: `{"answers_by_type": {type: [names]},
"no_answer_for": [types with zero answers], "exile_count", "instant_speed_count",
"cards": [...]}`. Gold set: ≥20 real cards incl. Swords to Plowshares, Beast Within, Chaos
Warp, Cyclonic Rift, Damnation, Blasphemous Act, Vandalblast, Counterspell, Pongify, Doom
Blade ("nonblack"), Culling Sun ("mana value 3 or less"), Eaten by Spiders, Skyfisher Spider,
Assassin's Trophy, Pest Infestation-style non-removal (must not appear). Tests pin the gold set.
Tool licenses names; prompt: "what can't my removal answer" ⇒ this tool, answer from
`no_answer_for` + restrictions only.

**Phase B exit:** bench `cards` and `removal` pass ≥80%; spot-read 5 removal replies against
oracle text.

### Phase C — Honest targets (G4b)

**C1. Colour-aware targets** — **CLAUDE** (calibration). `redundancy.targets_for(themes,
base=None, color_identity: Iterable[str] | None = None)`; `None` → current behaviour
(backward compatible; `advise`/`card_impact` callers unchanged unless they opt in).
Rule, measured not assumed: extend `scripts/role_targets.py` with a `--by-identity` sweep over
the corpus: for each role, p60 supply among decks whose identity LACKS the role's enabling
colour(s) vs those that have it. Ship a `ROLE_COLOR_REQUIREMENTS` table only for roles where
the sweep shows the gap (expected: `counterspell` needs U — verify; do not add others without
data). Roles failing the requirement → target 0 and `"applicable": False` in
`get_deck_stats`. Pass identity from the mentor (`tool_get_deck_stats`, `_analysis_for`
consumers). Record sweep numbers in this file.

**C2. `finisher` against the measured plan** — **CLAUDE**. In `get_deck_stats`, when
`insight.archetype` is combat-based ("Creature aggro", "Go-wide / tokens", "Midrange
goodstuff" with `goldfish_kill_rate ≥ 0.5`) mark `finisher` `"applicable": False,
"note": "wins through combat (measured)"`. Prompt: never call a non-applicable role a gap.

**Phase C exit:** bench `colour` rubric 100%; Shelob no longer told to add counterspells or
finishers.

### Phase D — Measured improvement levers (G8, G9)

**D1. `diagnose_axis(axis)`** — **OFFLOAD** the driver table (muse-glimmer), **CLAUDE** wiring.
Deterministic, reads `_analysis_for(ctx)` only (no new sim). Returns `{"axis", "score", "why",
"drivers": [{"name", "value", "direction": "higher_is_better"|"lower_is_better",
"reading": "strong"|"typical"|"weak"}], "levers": [str]}`. Driver table (verify each field
exists before use):
  - speed: `avg_kill_turn`, `goldfish_kill_rate`, `avg_commander_turn`, `curve_efficiency`,
    curve `average_mana_value`, ramp `cards`, creature count.
  - consistency: `keep_rate`, `avg_mulligans`, `curve_efficiency`, `commander_cast_rate`,
    manabase `consistency`, land count.
  - resilience: `resilience_score`, `kill_delay_turns`, share of nonland cards that are
    creatures, non-creature ramp/draw engine counts.
  - interaction: `InteractionReport` fields + (after B2) `no_answer_for`.
  - ceiling: `fast_kill_turn`, `nut_kill_rate`, `has_game_ending_combo`, `go_off_turn`,
    `overrun_alpha`.
  `levers` are fixed template strings keyed off `weak` drivers (e.g. speed + high
  `avg_commander_turn` → "Cheaper ramp in the 1-2 slot gets the commander out sooner") —
  written as a table in the spec, not generated. "strong/typical/weak" bands come from Phase E
  once it lands; before that, fixed thresholds documented in the table.

**D2. Measured swaps from the real advisor, in the background** — **CLAUDE**.
- Forge (`server.py`): `_run_advise_job` on success persists
  `deck.json["advice_cache"][axis] = {"result": <advise JSON>, "deck_hash", "collection_mtime",
  "computed_at"}` (deck_hash = sha1 of `_deck_to_lines(...)`). Add `advice_cache` handling to
  whatever persistence helper `_run_advise_job` already uses; do NOT add it to
  `_PROVENANCE_KEYS` (a rebuilt deck is a different deck).
- `mentor_chat_deck` passes the still-valid entries (hash + collection mtime match) as a new
  `advice` field → engine `MentorChatRequest.advice: dict | None` → `MentorContext.advice`
  (pass-through, same pattern as `offmeta`).
- New tool `get_measured_swaps(axis)`: returns the cached suggestions (licensing add/cut +
  `brief.allowed_card_names`, exactly like `tool_suggest_swap`), or `{"available": False,
  "message": "No full swap search has been run for <axis> yet — run Advise (<axis>) on the
  deck page; it takes a few minutes."}`.
- Prompt: prefer `get_measured_swaps`; fall back to the quick `suggest_swap` only when
  unavailable, and say the quick search is shallow.
- UI (`MentorChatPanel.jsx`): when a reply's tool trace shows `available: False` from
  `get_measured_swaps`, render a "Run full swap search (<axis>)" button that POSTs the existing
  `/api/deck/{job_id}/advise` route.
- Tests: Forge route test for the pass-through; engine tool test for both branches.

**Phase D exit:** `faster`/`weakest` answers either cite a measured swap or say none was found
and how to get one; `diagnose_axis` replies name ≥1 real driver with its value.

### Phase E — Relative verdicts (G10)

**E1. `scripts/bracket_axis_reference.py`** — **OFFLOAD** scaffold (qwen3:14b), CLAUDE review.
Iterates labelled corpus decks (header `# bracket: N`, 591 today), runs `analyze_deck(...,
run_resilience=True)` with `--runs 120` (resumable: cache per-deck rows to a JSONL; ~1-2 h
total is fine), and emits per bracket p25/p50/p75 for each `advisor.AXES` axis, pod score,
`avg_kill_turn`, `avg_commander_turn`. Bakes `BRACKET_AXIS_REFERENCE` into
`src/mythgauntlet/ratings/reference.py` with `n` per cell; `--check` diffs, like
`scripts/theme_base_rates.py`. Cells with n < 20 are emitted with `"thin": True`.

**E2. Wire into `get_power_profile`** — **CLAUDE**. Each axis gains `"vs_bracket": {"bracket":
N, "p25", "p50", "p75", "percentile_band": "below_p25"|"p25_p50"|"p50_p75"|"above_p75",
"n"}` for the deck's estimated bracket (omit when thin). Accept an optional
`compare_bracket` arg (so "vs a bracket 3 pod" compares against B3). D1's bands switch to
these. Prompt: "does X poorly" statements come from `percentile_band`.

**Phase E exit:** `vs_b3` replies cite a comparison from the tool, not a bare score.

### Phase F — Verdict gate (G5)

**F1. Gate check 6: verdict contradiction** — **CLAUDE**, `gate.py` + `verdicts.py`.
`ClaimBudget` gains `profile_verdicts: dict[str, str]`, detected structurally from a result
containing `"verdicts"` + `"axes"` (same shape-detection approach as `legality_verdicts`).
For each axis, `verdicts.PHRASES[axis][verdict]` / opposite phrases; flag a sentence that
names the axis topic AND uses an opposite-verdict phrase (e.g. resilience="resilient" and the
reply says "vulnerable to board wipes"). Archetype: flag a reply that labels the deck with an
archetype word from a different family than `archetype`. Narrow, under-flag bias, same as
check 5. Tests: each axis both directions + unrelated-prose negatives.

**Phase F exit:** rerun the Phase A bench with the gate active; any regression in gated rate
is investigated from transcripts (false positive → narrow the phrase map).

### Phase G — Polish (G12 leftovers)

**G1. Starter prompts** — **OFFLOAD** trivial (or hand-edit): add "What does this deck do well
and poorly?" and "How could I make it faster or more resilient?" to `STARTER_PROMPTS` in
`frontend/src/components/MentorChatPanel.jsx`; add `TOOL_LABELS` for every new tool;
`cd frontend && npm run build`.
**G2. Docs** — **CLAUDE**. Update `docs/MENTOR_HANDOFF.md` (new round: "round 8 — holistic
questions") and CLAUDE.md's mentor mentions; add the new bench to `mentor_bench.py`'s
docstring cross-references.

---

## 5. Order, ownership, sizing

| order | task(s) | owner | notes |
|---|---|---|---|
| 1 | A0 | Sonnet (+ qwen3 scaffold) | the yardstick; baseline recorded before any fix |
| 2 | A1-A7 | Sonnet | one agent, sequential; biggest win |
| 3 | B1, B2 | Sonnet (+ qwen3 for B1) | B2 is rules text — no local draft |
| 3‖ | E1 sweep | local (qwen3 scaffold) + Sonnet review | long offline run; can start once A lands, in parallel with B/C |
| 4 | C1, C2 | Sonnet | calibration |
| 5 | F1 | Sonnet | after A/B/C so the phrase map sees real replies |
| 6 | D1, D2 | Sonnet (+ muse-glimmer for D1 table) | touches Forge + engine + UI |
| 7 | E2, G1, G2 | Sonnet | wiring + docs |

The orchestrator (Opus) reviews each phase's diff and the bench output before the next phase
starts, and owns merging `mentor-adhoc` to `main`.

## 6. Log

| date | phase | bench (pass/total) | notes |
|---|---|---|---|
| 2026-09-30 | probe (pre-A0) | ~1/8 on Shelob | see §1 |
| 2026-09-30 | **A0 baseline** (pre-A1, commit 917173a, qwen3:14b, runs=150, 9 decks) | **22/72 (31%)**; gated on first attempt 59/72 | per rubric, decks passing: overview 8/9, cards 2/9, faster 0/9, resilience 1/9, wincon 3/9, weakest 4/9, vs_b3 2/9, removal n/a, colour 2/9. Detail below. |

**A0 baseline detail** (`scripts/mentor_holistic_bench.py`, full run ~25 min wall incl. cold store
load; decks = shelob, tymna, kess, ghired, isshin, najeela, arahbo, kaalia, meren). The overview
rubric passes because it only requires verdict phrases not to contradict and one measured strength
topic to appear; the colour rubric and `faster`/`resilience` carry the signal. The failure classes
match section 1 exactly and repeat across decks, so they are systematic rather than Shelob-specific:
"lacks counterspells" advice on 7 of 9 decks with no blue in identity (colour 2/9); `faster`
recommending a cut (or saying nothing) with no measured swap, 9/9; `resilience` said
moderate/vulnerable for decks measured 71-93/100, 8/9; `vs_b3` first draft rejected for "cites 3"
on 7/9; `wincon` naming "finishers" on a deck with finisher supply 0 and/or no archetype/win route.

## 7. Out of scope

- A second LLM judging the first (rejected in MENTOR_HANDOFF round 7 on doctrine).
- Suggesting cards outside the player's collection.
- cEDH line analysis — the pod is casual B1–3.

## Appendix — the original probe

Scratch `probe_mentor.py` / `truth.py` from the 2026-09-30 session did exactly what A0
formalises: build `MentorContext` like `mentor_bench.py`, ask via `mentor_chat.ask`, diff
against `analyze_deck(..., run_resilience=True)`. A0 supersedes them.
