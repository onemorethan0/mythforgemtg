# Hand-authored CCMs (rung 3)

The highest-confidence tier in the semantics store. `compile-top` **skips** every name here
(`compiler.authored_names()`), so these never enter the ledger and never get overwritten by a
model-compiled rung-2 CCM.

Two consequences worth knowing before you measure anything:

- **A card here will look "uncompiled" to any check that reads only `compiled/`.** It happened:
  a coverage script reported Sol Ring, Command Tower and Counterspell as missing and concluded
  the engine was guessing at the format's most-played cards. The opposite was true. Read both
  rungs, as `SemanticsStore.__init__` does.
- **The two rungs live under different roots.** `authored/` is in this repo; `compiled/` follows
  `MYTHGAUNTLET_STORE`. A check that assumes one root silently misses a whole tier.

## Every CCM is a lossy model — write down where

The engine's effect vocabulary is closed and deliberately small. A hand-authored CCM is not a
rules-complete card; it is the best available approximation *within that vocabulary*, and the
approximations below are chosen so the engine **under**-counts rather than fabricates.

### `15-senseis-divining-top`
`{T}: Look at the top three cards … put them back in any order` is modelled as `scry 3`. Scry
can put cards to the BOTTOM and Top cannot, so this slightly **overstates** selection quality.
The second ability's "put Top on top of its owner's library" is not modelled at all — there is
no op for it — so the card's signature loop (Top + shuffle effects, Top as a draw engine) is
absent. Net: closer to right than rung-1 heuristics, still an under-model of a famously fiddly
card.

### `16-urzas-saga`
Chapter III uses the `saga_chapter` trigger event, which `sim/tier2._EVENT_TRIGGERS`
**deliberately does not execute**. That is the honest choice the vocabulary is built for: a
correct-but-unexecuted event under-counts, whereas mapping it to an executable event the card
does not have would fabricate value.

The two granted abilities (I: `{T}: Add {C}`, II: `{2},{T}: make a Construct) are modelled as
plain activated abilities, which **overstates early game** — on the real card they are gained at
chapters I and II and the land sacrifices itself at III. The Construct's "+1/+1 for each
artifact you control" is not expressible, so it is a 0/0 body.

### `17-the-one-ring`
`Indestructible` and the ETB "protection from everything until your next turn" have no op —
the card's actual reason for being played in fair decks is therefore **not modelled**. The
upkeep life loss and the tap-to-draw both scale with burden counters, expressed as `x`, which
the profile resolves to a small default. Net: the draw engine is present at roughly the right
shape, the protection is missing entirely.

### `18-28`, 2026-09-16
Hand-authored after this batch spent a full session finding and fixing compiler defects (the
`look_and_select` zone-evidence gate and its keyword-licensing fixes, `discard`'s missing-count
backstop, several prompt additions) and still could not get these 12 cards through the pipeline
reliably at qwen3:14b/temp 0.2 — either a genuine vocabulary gap or a consistently-wrong LLM
guess the automated retries never converge on.

- **`18-abundance`**: "If you would draw a card, instead search..." is a REPLACEMENT effect on
  every future draw — there is no replacement-effect ability kind and no `would_draw` trigger.
  The underlying search IS modelled (`search_library`, satisfying the gate that requires it
  whenever the reveal-until-match template appears in the text) but wrapped in a triggered
  ability with `event: "other"`, which this engine never executes — an honest "the shape is on
  record, it never fires" rather than either a fabricated trigger or a gate failure.
- **`19-anticausal-vestige`**: the death-trigger draw is modelled; the accompanying "put a
  permanent card with mana value ≤ your lands from hand onto the battlefield" uses `reanimate`,
  which is declared in the vocabulary but **never dispatched by the simulator** — structurally
  honest, functionally inert until reanimate ships.
- **`20-chulane-teller-of-tales`**: same `reanimate`-for-a-land-drop shape as Anticausal Vestige
  on the cast-creature trigger. The bounce ability targets your own creature with
  `return_to_hand`, whose "you"-direction the simulator declines by design (a documented
  2026-09-09 revert after a hand/graveyard-recursion false positive) — structurally correct,
  inert the same way.
- **`21-cunning-wish`, `22-golden-wish`, `23-living-wish`, `24-coax-from-the-blind-eternities`**:
  the Wish cycle fetches a card from OUTSIDE THE GAME (a sideboard) — a zone this vocabulary has
  no concept of, and one Commander's singleton, no-sideboard format makes moot anyway. `[]`
  abilities (an instant/sorcery's lint gate requires a real `spell_effect` ability the moment it
  has ANY ability at all, so a "can't represent this" static note is invalid here — a genuinely
  empty ability list is the only valid honest decline for a pure spell).
- **`25-forgotten-lore`**: the OPPONENT chooses repeatedly from your own graveyard in a
  pay-to-continue loop, ending on their last pick going to your hand — no clean op, and
  modelling either direction (their best pick for you vs. their worst) risks fabricating an
  adversarial choice this engine doesn't otherwise simulate. `[]` abilities.
- **`26-feroz-ulgrothas-warden`**: loyalty-ability planeswalker. `+2`/`0`/`-7` costs follow the
  documented `{"other": "<sign>N loyalty"}` convention. The `+2` Birds' flying and the `-7`
  token's own static ability ("Creature spells cost {2} more") have no representation —
  `create_token` has no keyword-grant field — so both tokens exist with the right body but
  missing text, same limitation every other flying-token-creating card in the store has.
- **`27-tri-sentinel-act-of-vengeance`**: the ETB "for each opponent, deal 3 to up to one
  creature that player controls" is a PER-OPPONENT repeated effect with no clean vocabulary
  shape (not a mass "all creatures" effect, not a single target) — modelled as ONE application,
  under-counting a real 4-player pod's 2-3 actual triggers rather than either fabricating a mass
  wipe or reproducing the model's own 37-effect repetition-bug loop when it tried to unroll the
  "for each" by hand. Unearth is modelled as an activated ability with `reanimate` (self-target,
  from graveyard) for the same structural-record-only reason as Anticausal Vestige above.
- **`28-vault-101-birthday-party`**: Saga chapter I creates both tokens (the Food token's own
  sacrifice ability isn't representable, same limitation as Feroz's tokens above); chapters
  II/III use `reanimate` for "put an Aura/Equipment from hand or graveyard onto the
  battlefield" — the follow-up "attach it to a creature" clause is not modelled, a second layer
  of choice this pass didn't attempt.

**Not authored — a genuine new-vocabulary need, not a hand-authoring gap**: Spara's
Adjudicators' `"{2}, Exile this card from your hand: Target land gains '{T}: Add {G}/{W}/{U}'
...`" grants a NEW mana ability to an arbitrary permanent. `add_mana` has no target field (it
adds to the ACTIVATING player's own pool, immediately) — using it here would misrepresent a
delayed, granted ability as this card producing mana on the spot, the exact "quietly wrong CCM"
this file's own opening section warns against. Left quarantined.

## Adding one

1. Match the envelope shape: `{"card": {...}, "ccm": {...}}`, `ccm_version` 1, `rung` 3.
2. Validate before committing — schema **and** all gates:

   ```
   PYTHONPATH=src python -c "from mythgauntlet.semantics import ccm, compiler; from pathlib import Path; e=compiler.read_envelope(Path('ccm/authored/NN-name.json')); print(ccm.validate_schema(e['ccm']))"
   ```

3. Document the approximation here. A CCM that quietly models the wrong card is worse than no
   CCM, because the engine executes it at full value.
