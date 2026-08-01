# Card Semantics — the Card Capability Model (CCM)

This layer answers one question for every Magic card: **"what does this card do, in terms the
engine can execute?"** It is the genuinely novel subsystem — nothing like it exists in public
tooling — and it is designed so that partial knowledge is useful and total knowledge is never
required.

## Why not just parse Oracle text with regexes?

Regex heuristics (rung 1 below) are what every existing power calculator does, and they top
out fast: "destroy target creature" is easy; "each opponent sacrifices a creature, then if you
control a Zombie, …" is not. Why not a full formal grammar? Because Oracle text is a
controlled natural language with thousands of templates and deliberate exceptions — projects
have tried and stalled for a decade. Why not pure LLM-at-runtime? Too slow for 10⁵ simulated
games and non-deterministic.

The answer is **offline compilation with validation**: use the LLM once per card to produce a
*structured, executable, versioned artifact*, validate it mechanically, cache it forever.

## The semantics ladder

| Rung | Name | Source | Fidelity | Coverage target |
|---|---|---|---|---|
| 3 | **Scripted CCM** | hand-authored YAML | exact | top ~500 Commander staples + all 53 Game Changers |
| 2 | **Compiled CCM** | LLM compilation + validation gates | high | all cards seen in imported decks, then all of Commander |
| 1 | **Effect vector** | Oracle-text heuristics (`semantics/tags.py`) | approximate | 100% today |
| 0 | **Vanilla** | types/cost/PT from Scryfall | floor | 100% by construction |

Every card resolves to the highest rung available. The deck report shows the blended coverage.

## Rung 1 — Effect vectors (built)

A cheap, fully-automatic approximation: regex/keyword heuristics tag each card with functional
roles and magnitudes. This is deliberately the same category of analysis MythForge's
`commander_analysis.py` does (~30 themes), narrowed to what simulation needs:

```python
EffectVector(
    ramp_sources=1,        # permanent mana added when resolved (rocks/dorks/land-fetch)
    draw_cards=2,          # immediate cards drawn on resolution
    tutor=False,           # searches library for a nonland card
    removal=1,             # targeted answers
    board_wipe=False,
    counterspell=False,
    enters_tapped=False,   # for lands
    impact=0.0..1.0,       # generic "how much does resolving this matter" prior,
)                          #   seeded from EDHREC rank, refined by learning loop (L5)
```

Known limits (accepted, documented): conditional taplands ("unless you control…") tag as
tapped; modal spells take their best mode; triggered engines (e.g. "whenever you cast…") are
invisible at this rung. These are exactly the cards the compiler prioritizes.

## Rungs 2–3 — The CCM

A CCM is a YAML/JSON document describing a card as **costs, characteristics, and a list of
abilities**, each ability being `trigger/condition → effects` over a closed vocabulary of
engine primitives. Sketch (schema will be versioned as `ccm/v1`):

```yaml
name: "Cultivate"
ccm_version: 1
rung: 3
cost: {mana: "{2}{G}"}
types: [sorcery]
abilities:
  - kind: spell_effect
    effects:
      - {op: search_library, what: {type: land, subtype: basic}, count: 2,
         then: [{op: put_battlefield, count: 1, tapped: true},
                {op: put_hand, count: 1}]}
      - {op: shuffle}
provenance: {source: hand_authored, author: dorian, date: 2026-07-05}
```

**Effect primitives** are the engine's instruction set — small, closed, and versioned:
`add_mana, draw, search_library, put_battlefield, put_hand, destroy, exile, counter_spell,
deal_damage, gain_life, create_token, pump, tap, untap, sacrifice, discard, mill, scry,
return_to_hand, …` (grow ~5 at a time, only when a tier-2 feature needs them).
**Tolerance (v6+):** a CCM may use ops, trigger events, or target keys outside the
vocabulary — the schema gate KEEPS them, records the ops in `unsupported_ops`, and accepts
the card; the engine models the effects it understands and ignores the rest. Known ops are
still validated strictly (bad params, missing requireds, and Scryfall/cross-check
mismatches still reject). This decouples compilation progress from engine progress: a
Kiki-combo creature whose ETB "draw" is modeled but whose exotic keyword isn't still
contributes its real, checkable behavior instead of being thrown back to rung 1 whole.

**Trigger events must match the text (v10+).** Gate 3 cross-checked ops against the Oracle
text exhaustively and never looked at trigger EVENTS, so a card could declare any event and
be accepted. Smaug the Impenetrable ("whenever Smaug is dealt NONCOMBAT damage, create that
many Treasure tokens") compiled as `combat_damage_to_player`, and the engine duly minted
Treasures every time he connected in combat — an ability the card does not have. An audit of
the committed store found 1,400 cards (4.6%) in that state.

The root cause was a MISSING VOCABULARY, not a careless model: the correct event often did
not exist, so the model reached for the nearest *executable* one. `TRIGGER_EVENTS` therefore
carries events the engine does NOT execute — `self_cast`, `blocks`, `becomes_blocked`,
`dealt_damage`, `saga_chapter`, `creature_dies`, `leaves_battlefield`, `becomes_target`,
`tap_for_mana`, `end_of_combat`. That is deliberate and it is the whole trick:
`sim/tier2._EVENT_TRIGGERS` DROPS an event it cannot execute, so a correct-but-unexecuted
event **under-counts honestly** while a wrong-but-executable one **fabricates value**.

`ccm.cross_check` now requires textual evidence for every declared event. It stays permissive
in the same direction as the rest of gate 3 — `"other"` always passes (and is always the
right answer when nothing fits), an event outside the vocabulary passes, and reminder-text
keywords are licensed exactly as `_KEYWORD_IMPLIED_OPS` does for ops (cascade IS a cast
trigger, modular IS a death trigger, champion/squad/living-weapon are ETBs, and a Saga's
parenthetical literally says "as this Saga enters and after your draw step").

Two lessons worth keeping. **Anchor the pattern against the near-miss, not the phrase:**
"noncombat damage" *contains* the substring "combat damage", so the combat pattern needs a
negative lookbehind; `cast_creature` requires an article so it cannot match "casts THIS
spell". And **tune a gate against real random samples** — three independent 20-card draws
from the store, every flag hand-classified, until false positives fell to ~1 in 20. A naive
first pass claimed 18% of the store was broken; disciplined passes gave a defensible 4.6%.

**X-basis (v8+):** a numeric param of `"X"` may carry a sibling `x_basis` string on the
effect naming what X counts (`mana_paid`, `chosen`, `creatures_you_control`,
`lands_you_control`, `cards_in_hand`, `target_power`, ... — see `ccm.X_BASES`). This exists
because the store showed bare X is overwhelmingly a cost/chosen amount, so the engine must
not guess it from board state; with a declared basis, the T2 resolver scales the
board-derived bases from live state and leaves cost-side bases at the modest default.
The vocabulary is descriptive: unknown basis values are tolerated (only the type is
enforced), so the compiler can name a basis we haven't ranked yet without quarantining.

**Deep JSON repair (v8+):** responses that fail strict parsing and the cheap regex fixes
(trailing commas, Python literals) get a last-resort structural repair via `json-repair`
(missing commas/quotes were ~276 pure-parse quarantines). Repair never auto-accepts: the
repaired document still faces every gate, and accepted docs record
`provenance.json_repaired: true` so audits can stratify repaired vs clean acceptances.

## The compiler pipeline (rung 2)

```
Oracle text ──► PROMPT (few-shot: 20 hand-authored exemplars, primitive vocabulary,
                        schema, "emit JSON only")
            ──► local LLM (llama-swap :8010, qwen3:14b, temperature 0)
            ──► GATE 1: schema validation (pydantic-style, strict; reject unknown ops)
            ──► GATE 2: static lint (costs match Scryfall mana_cost; types match type_line;
                        numeric sanity: no draw-52-cards)
            ──► GATE 3: behavioral property tests — execute the CCM in a micro-sandbox and
                        assert invariants derived from Oracle text by *independent* cheap
                        heuristics (card says "draw" ⇒ hand size must increase; says
                        "destroy target creature" ⇒ needs a creature target; mana produced
                        matches Scryfall's produced_mana field)
            ──► GATE 4 (spot): differential test vs Forge for cards Forge scripts —
                        resolve the same card in both engines, compare observable state deltas
            ──► accepted → ccm store (SQLite, keyed by oracle_id + ccm_version + engine_version)
            └─► rejected → retry with error feedback (≤2), else quarantine queue
                        (card stays at rung 1; queue is the hand-authoring worklist)
```

Design properties worth calling out:

- **Determinism preserved**: the LLM runs at *build* time. Simulation never calls it.
- **Trust is earned mechanically**: a compiled CCM is only used after passing gates; the
  quarantine queue makes failure visible instead of silently wrong.
- **Self-prioritizing**: compilation order = frequency of appearance in user decks × EDHREC
  popularity, so effort lands where users are.
- **Versioned artifacts**: CCMs record schema, engine, and prompt versions. Engine upgrades
  can invalidate and recompile cheaply.

## The coverage ledger

`semantics/` maintains a per-card ledger: rung, validation status, gate failures, last
compiled version. Aggregates power the roadmap ("rung ≥2 coverage of top-1000 EDHREC cards:
X%") and the per-deck coverage score shown in every report.

## Popularity data in this layer

Scryfall's `edhrec_rank` ships in bulk data and seeds each card's `impact` prior at rung 1.
The EDHREC JSON API adds per-commander inclusion & synergy ("% of decks for this commander
minus % for the color identity") — used by L5 to build reference gauntlet decks and to prior
the card-value model. Per invariant #4 (ARCHITECTURE.md), popularity never directly changes a
measured strength score.
