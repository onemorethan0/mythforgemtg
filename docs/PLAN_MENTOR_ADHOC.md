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

**D0. A "clock" axis that measures EARLINESS** — **CLAUDE**, `ratings/advisor.py` (added
2026-09-30 from the orchestrator's review of Phase A). The existing `speed` axis is
`goldfish_kill_rate` (share of games that kill at all within the horizon), NOT how early. Shelob
reads speed 96.7 with a T9 clock, so no speed swap can ever help it, and the model answered
"make it faster" with a CEILING swap (Return of the Wildspeaker) whose own brief shows
`kill_turn_before 9.32 -> kill_turn_after 9.45` — i.e. the deck gets SLOWER on average. Add an
additive axis `clock` to `advisor.AXES` (score = a monotone decreasing map of
`report.avg_kill_turn`, e.g. `100 * (horizon - avg_kill_turn) / horizon` clamped, 0 when no
kill; document the formula), measure its seed-to-seed noise the way `_AXIS_NOISE_FLOOR` was
measured and add its floor there, add `clock` to `suggest_swap`'s enum, and route "faster" →
`clock` in the prompt. `weakest_axis` must NOT start preferring `clock` by accident — decide
explicitly and test it. Any swap reported for "faster" must show `kill_turn_after <
kill_turn_before`; the holistic bench's `faster` rubric gains that check.
**D0b. Disclose an unbacked cut** — **CLAUDE**. When a suggested swap's
`brief.cut.redundancy_backed` is false, the tool data carries `"cut_is_redundant": false` and
the prompt says the cut was the pool's default, not evidence the card is weak (Shelob's
Gloomwidow's Feast — its own theme card — keeps surfacing this way).

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
| 2026-09-30 | E1 | n/a (reference table) | `scripts/bracket_axis_reference.py` baked `ratings/reference.py` from 569 labelled decks (runs=120, seed 42, turns=12, 0 failures, ~32 min): B1 129 / B2 172 / B3 147 / B4 66 / B5 55; **no thin cells** (min n=55); avg_kill_turn None for 8 B1 + 2 B2 + 2 B3 decks, avg_commander_turn None for 3 B1. Medians barely separate brackets: only `interaction` (57.8/63.4/59.5/74.7/90.0) and `consistency`/`speed` at B5 (lower) move; `avg_kill_turn` is flat ~10.0-10.2 (goldfish horizon 12), `ceiling` p50 flat 17-19 (only p75 rises at B5: 36.4 vs 25), `resilience` drifts down 89.9 -> 85.4, `pod` peaks B2-B3 and is LOWEST at B5. Bands are useful for within-bracket placement, weak as a B3-vs-B4 discriminator. |
| 2026-09-30 | **A0 baseline** (pre-A1, commit 917173a, qwen3:14b, runs=150, 9 decks) | **22/72 (31%)**; gated on first attempt 59/72 | per rubric, decks passing: overview 8/9, cards 2/9, faster 0/9, resilience 1/9, wincon 3/9, weakest 4/9, vs_b3 2/9, removal n/a, colour 2/9. Detail below. |

| 2026-09-30 | **Phase A exit check** (HEAD = "A-exit fix 2", qwen3:14b, runs=150, 9 decks; 3 full runs after A1-A7 + 2 fix iterations) | final run **64/72 (89%)** under the final rubric (56/72 as it was originally graded); baseline re-graded under the same rubric **25/72 (35%)**. `mentor_bench.py` on Shelob **50/52** (exit bar 47). Full pytest 1739 passed. | per rubric, final run: overview 9/9, cards 9/9, faster 9/9, resilience 8/9, wincon 9/9, weakest 9/9, vs_b3 8/9, removal n/a, colour 3/9. **Phase A exit met** (every listed rubric >= 80% of decks); `colour` is Phase C's, not Phase A's. Detail and caveats below. |

| 2026-09-30 | orchestrator re-verification (Opus, Shelob only, fresh run) | 6/8 | Reproduced the gain independently. Correct now: archetype/win route (midrange, combat, ~T9), resilient 93%, real key cards, empty-swap honesty. Remaining: `faster` answered with a CEILING swap that makes the average kill slower (9.32->9.45) -> new task D0; cut is the deck's theme card (Gloomwidow's Feast) -> D0b; 'no counterspells' still called a weakness (C1); removal answer generic (B2 wiring); overview FAIL was a rubric false positive ('moderately interactive' read as a resilience claim) -> fix in F1's phrase map. B2 (removal.py) merged into mentor-adhoc; full suite 1798 passed. |

| 2026-09-30 | **Phase B/C exit check** (orchestrator-run after the B/C agent stopped at a usage limit with all four tasks committed; qwen3:14b, runs=150, 9 decks) | **72/81 (89%)**; gated on first attempt 72/72. `mentor_bench.py` Shelob **47/52** (bar 47; 3 gate fallbacks). Full pytest 1892 passed. | per rubric: overview 8/9, cards 9/9, faster 8/9, resilience 7/9, wincon 9/9, weakest 9/9, vs_b3 9/9, **removal 9/9** (new), **colour 4/9** (target 8/9 MISSED). Colour residual is mostly the TOOL, not the model: `insight.axis_why['Interaction']` always says 'N counters' and the replies echo 'no counterspells' as a weakness for non-blue decks; plus a rubric that cannot tell a factual mention from advice (Arahbo's 'consider adding counterspells' is the genuine failure). Resilience residual: Shelob/Tymna answered with a swap and never stated the verdict, and called the cut card 'somewhat redundant' with no redundancy backing (D0b). Both handed to the Phase D agent. |
| 2026-09-30 | **D0 / D0b / D1 / E2 / F1 + C-residual exit check** (branch `mentor-adhoc-d`, qwen3:14b, runs=150, 9 decks; 3 full runs) | final run **79/81 (98%)** as run; **80/81** after one offline rubric-ack tweak (`--regrade`). `mentor_bench.py` Shelob **48/52** (runs: 49, 48, 48; bar 47). Full pytest **2008 passed, 4 skipped** (baseline 1892). | per rubric, final run: overview 9, cards 9, **faster 9/9 (was 5/9 on run 1)**, resilience 9 (was 7 on bc_exit), wincon 9, weakest 9, vs_b3 9, removal 9, colour 7 as run / 8 regraded (was 4 on bc_exit). Gated on first attempt **70/72** (run 1: 69, run 2: 65). Details below. |

**D0 clock noise floor** (`scripts/axis_noise.py --turns N`, 8 corpus decks x 8 seeds, runs=150): `clock` seed-to-seed sd **0.71 at turns=12** (baked: the mentor/analyze/advise horizon) and 1.10 at turns=8; 0.71 points is ~0.09 of a turn, so the caller's `min_delta` (1.0, ~0.12 turn) is the binding floor in practice. Same sweep at turns=12 for the other axes: speed 1.48, ceiling 1.98, consistency 0.87, resilience 0.73, interaction 0.00 (turns=8: 1.71 / 2.20 / 0.82 / 1.03 / 0.00) - sweep-to-sweep noise around the baked turns=8 constants, which were left alone. **Decision, pinned by `test_weakest_axis_never_returns_clock`:** `weakest_axis` never returns `clock`. On the formula `100*(horizon-avg_kill_turn)/horizon` the median corpus deck scores ~16 (avg kill ~10.1 of 12), so the axis would be "the weakest" of nearly every deck. `advisor.PROFILE_AXES` (AXES minus clock) drives `weakest_axis`, `card_impact`'s per-axis sweep (card verdicts unchanged) and the E1 reference; `get_power_profile.axes` keeps its six keys (the kill turn is already in its `clock` block).

**Discrepancies vs the plan text** (code won): (1) D0 adds `clock` to `AXES` as written but several callers iterate `AXES` (card_impact, E1's reference test, get_power_profile) - hence `PROFILE_AXES`. (2) E2: the plan's "D1's bands switch to these" is only true for the metrics that exist in the reference table (avg_kill_turn, avg_commander_turn, the axis scores: resilience_score reads the `resilience` cell, goldfish_kill_rate the `speed` cell x100); every other driver has a fixed threshold (corpus p25/p75 over 866 decks, 30 sampled for the simulated facts, measured 2026-09-30 - documented in `mentor/diagnose.py`). (3) E2 adds an oriented `standing` next to `percentile_band` because the table describes the RAW value and kill turn is lower-is-better. (4) A faster/quicker/speed-up question is now routed to `suggest_swap(axis="clock")` by `chat._route_swap_axis` whatever axis the model passed (live: it kept passing `ceiling`).

**D1 offload review** (`mentor/diagnose.py`, muse-glimmer from `docs/specs/mentor_adhoc/D1.md`; first dispatch HTTP 500 "bad allocation" while two sweeps shared the box, retry 252 s, no qwen fallback needed). The table, thresholds and lever texts matched the spec; review changed: the module docstring was emitted as a bare string after the imports (not a docstring) and omitted the gold-set table; `avg_commander_turn` lacked `none_reading="weak"`; the breadth lever named counterspells (wrong for a no-blue deck - the tool test caught it); every Driver is also a public module constant (unrequested, harmless). The facts builder, tool, schema, prompt and tests are hand-written; a lock-step test pins that every fact the table reads is one the builder supplies.

**Exit-run reading** (replies read, not just scored). Run 1: `faster` 5/9 - three decks stopped after `diagnose_axis` (it explains the cause, so the answer felt complete) and never called `suggest_swap`; Najeela passed `axis="ceiling"` for "faster" and reported a swap whose own brief showed the kill later (9.56 -> 9.79, the new slower-kill check caught it); three non-blue decks were told to "consider counterspells" because `removal_coverage` listed the empty `spell` type as a gap. Fix 1: a once-per-turn nudge when an improvement question ends with no `suggest_swap`, deterministic clock routing, `spell` moved to `not_applicable_types` for a deck without blue. Run 2: `faster` 9/9 but first-attempt gating fell to 65/72 - **10 of 11 rejections were F1's own**: a bare "a quick" read "Provides a quick source of mana" (an Isshin key-cards list) as "the deck is fast" (three rejections, answer fell back to uncertainty), "fast win conditions" described opposing decks, and "already quite fast for its bracket" / "consistency below average for bracket 3 decks" are relative claims the new `vs_bracket` standings license (avg kill turn ~9 is the top quarter of every bracket's decks while the absolute band says slow). Fix 2 (the second and last iteration): the speed phrases only count as a frame for the deck, opponent speech is skipped, relative-to-bracket sentences are exempt from the gate (the absolute verdict is enforced everywhere else), prompt: a standing is not a speed verdict. Run 3: the table above. **F1 rejection counts:** 1 / 10 / 1 verdict rejections in runs 1 / 2 / 3; the run-1 one was genuine ("already quite fast" for a slow deck) and the run-3 one was a false positive ("needs more answers against decks with strong interaction" - the opponent's interaction; fixed after the run, test-pinned, not re-run live); both were repaired by the model on retry. **Colour:** the root cause was the tool (insight lists "0 counters" for every deck): `get_power_profile` now drops the counter count and rewrites breadth to "b of 2 playable types" when `role_applicable("counterspell", identity)` is false; the bench rubric stopped failing factual mentions (re-grade of the saved bc_exit run: colour 4/9 -> 7/9 from the rubric alone). Still failing as run: Tymna ("lacks counterspells due to its colour identity, which does not include blue" - identity-aware, rubric false positive, fixed by an ack tweak) and Isshin (a closing "it lacks the ability to counter spells directly" right after saying that is not a gap - the model contradicting itself; left failing). **Resilience** answers now carry the verdict because `suggest_swap`'s result states the current axis score/verdict; 9/9 on the final run. Not fixed: the removal rubric once failed Tymna on "Haywire Mite, which can't target creatures" (a true statement about a card read as a creature-gap claim) - not reproduced in run 3.

| 2026-09-30 | **Orchestrator independent verification after merging D/E2/F** (merge d19b984, qwen3:14b, runs=150, 9 decks, fresh run) | **78/81 (96%)**; gated on first attempt 69/72. `mentor_bench.py` Shelob **49/52**. Full pytest 2010 passed. | overview/cards/faster/resilience/wincon/weakest/vs_b3 all 9/9; removal 8/9; colour 7/9. Of the 3 FAILs, 2 are rubric false positives (Kaalia: 'This is not considered a gap'; Ghired: 'cannot answer spells, it lacks blue' is TRUE) -- the colour/removal rubrics still match on keywords near a negation. 1 genuine: Shelob overview 'interaction is only moderate ... no counterspell' (mild framing, not advice). vs probe baseline (~1/8 Shelob, 25/72 re-graded): the open-ended feature is now trustworthy on every question type the plan targeted. |

**Phase A exit detail.** Three full runs after the fixes, each re-graded offline under the FINAL
rubric (`--regrade`, no model calls): run 1 62/72, run 2 67/72 (93%), run 3 64/72 (89%) — model
variance between identical-code runs is 3-5 cells, so read every figure as +-5 points. The two
fix iterations, each from reading failing replies: (1) `clock` carries `*_pct` percents (the
model's "50%" for `goldfish_kill_rate 0.5` was gate-rejected, two decks fell back to the
uncertainty reply), tools are re-called on follow-ups, and a model that announces "I'll look
into your collection" and stops gets one nudge to make the `suggest_swap` call; (2) verdict
detectors see through markdown, win-route phrases count as stating the route, resilience
phrases need the wipe as their object, and the prompt asks for the asked-about axis first.
Rubric refinements made while reading replies (so the as-run and re-graded figures differ):
honest "no measured improvement" phrasings, "lacks a finisher" negating a finisher mention,
truncated deck-card names ("Gloomwidow") not counted as foreign cards, markdown/proximity fixes
in `verdicts`. Re-grading the baseline with the same rubric moved it 22 -> 25, so the rubric
changes are not what produced the improvement. **Cold `_analysis_for` at runs=150: 3.4-4.1 s**
(shelob 3.4, kess 3.9, najeela 3.7, tymna partner deck 4.1) — nowhere near the 120 s Forge proxy
timeout; `suggest_swap` (4 re-simulations) remains the slow tool. **Still failing / open:**
`colour` 3/9 (the colour-blind `counterspell` target, Phase C1); `faster` replies often say "your
deck is already quite fast" while `verdicts.speed` is "slow" (ungated verdict contradiction,
Phase F1's job); `overview` is lenient by the plan's own definition (contradiction-free plus
one measured strength topic); `removal` is n/a until Phase B. `mentor_bench.py`'s two failures
are the documented honest-answer scorer residuals (a 704.5f correction and a Sol Ring
premise correction that says "costs {1}").

**C1 sweep (2026-09-30, `python scripts/role_targets.py --by-identity`, 862 corpus decks with a
resolved commander; 9 more have an EMPTY identity = unresolved commander and are excluded, because
8 of those 9 carry counterspells and would contaminate every "lacks" half).** p60 supply (strength
units) and share of decks running any, decks HAVING vs LACKING the enabling colour(s):

| role (baseline target) | needs any of | has: n / p60 / %>0 | lacks: n / p60 / %>0 | shipped |
|---|---|---|---|---|
| counterspell (3) | U | 450 / 9.0 / 84% | 412 / 0.0 / 12% | **yes** |
| wipe (3) | W, B, R | 774 / 3.0 / 63% | 88 / 0.0 / 10% | **yes** |
| finisher (2) | R, G | 639 / 3.0 / 60% | 223 / 0.0 / 17% | **yes** |
| ramp (14), lacking G | G | 417 / 18.0 / 99% | 445 / 10.0 / 96% | no: colourless rocks keep p60 at 10 |
| draw (16), lacking U | U | 450 / 18.5 / 99% | 412 / 13.0 / 99% | no: every colour draws |
| removal (4), tutor (4), wipe/finisher single colours | -- | differences of 1 or none | -- | no |

The bar (documented at `ROLE_COLOR_REQUIREMENTS`): the LACKING half's p60 is zero while the HAVING
half sits at or above the role's own baseline. Only those three pairs clear it; the plan expected
only `counterspell`, and the data added `wipe` and `finisher` (both measured as ANY-of sets, since
several colours fill them). `wipe` and `finisher` are the debatable two -- colourless options exist
(the residual 10-17%), which is why the mentor flag says "not applicable", never "impossible"; drop an
entry from the table to revert it. `targets_for(..., color_identity=None)` is byte-identical to the
old behaviour and `advise`/`card_impact`/`swap_brief` do not pass an identity (only the mentor's
`get_deck_stats` does); an empty identity counts as unknown, not colourless.

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
