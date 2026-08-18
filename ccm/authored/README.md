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

## Adding one

1. Match the envelope shape: `{"card": {...}, "ccm": {...}}`, `ccm_version` 1, `rung` 3.
2. Validate before committing — schema **and** all gates:

   ```
   PYTHONPATH=src python -c "from mythgauntlet.semantics import ccm, compiler; from pathlib import Path; e=compiler.read_envelope(Path('ccm/authored/NN-name.json')); print(ccm.validate_schema(e['ccm']))"
   ```

3. Document the approximation here. A CCM that quietly models the wrong card is worse than no
   CCM, because the engine executes it at full value.
