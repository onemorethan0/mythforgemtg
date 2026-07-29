# The engine's card semantics — what ships, what doesn't

Myth Forge contains the **MythGauntlet simulation engine** at `src/mythgauntlet/`. The engine
source is open and included. The **compiled card semantics it consumes are not**, and that is
deliberate. This page says exactly what is missing, why, and what the engine does without it.

## The short version

| | included | why |
|---|---|---|
| Engine source (`src/mythgauntlet/`) | ✅ yes | the simulator, ratings, bracket logic, CLI, API |
| Authored exemplars (`ccm/authored/`, 14 files) | ✅ yes | hand-written schema examples — prompt *source*, not compiled output |
| Deck corpus (`corpus/decks/`, 407 lists) | ✅ yes | public decklists + bracket labels; the calibration anchor set |
| **Compiled semantics (`ccm/compiled/`, ~30k)** | ❌ **withheld** | see below |
| **Compilation ledger (`ccm/ledger.json`)** | ❌ **withheld** | per-card status for the above |
| Scryfall bulk (`data/`) | ❌ not shipped | download it yourself: `mythgauntlet fetch-data` |

## Why the compiled semantics are withheld

A **CCM** (Card Capability Model) is a JSON document describing what a card actually *does* —
its costs, triggers, and effects over a closed vocabulary the simulator can execute. It is what
lets the engine play a card rather than pattern-match its Oracle text.

Those ~30,000 documents are not a scrape. Each one was compiled by a local LLM against a
hand-tuned prompt, then put through three validation gates (schema, Scryfall lint, and a
bidirectional cross-check against independent heuristics), with failures quarantined and
retried as the prompt improved. That represents many hundreds of overnight GPU-hours and nine
revisions of the compiler prompt.

**It is also not finished.** The compiler is still running nightly and the quarantine backlog is
still shrinking — the corpus of executable semantics grows and improves week over week. Holding
it back until that work is complete is intentional; distribution terms afterwards are undecided
and may be commercial.

If that changes, this page changes with it.

## What the engine does without it

It still runs. The semantics store has three rungs and degrades cleanly:

- **Rung 3** — hand-authored CCMs. 14 ship here, so the format's exemplars are all present.
- **Rung 2** — LLM-compiled CCMs. **This is the withheld layer.**
- **Rung 1** — Oracle-text effect vectors computed on the fly from card text. Always available.

With rung 2 absent, every card that isn't one of the 14 exemplars falls back to rung 1. The
simulator plays the games, the axes compute, and the bracket estimate still works — the official
bracket gates (Game Changers, combos, mass land denial, extra turns) read card data directly and
don't need CCMs at all. What you lose is fidelity: rung 1 approximates a card's effect from its
text instead of executing a validated model of it, so anything downstream of *how a card
actually resolves* — Ceiling, the storm/overrun finishers, Tier-2 adversarial play — is
coarser.

The engine reports this honestly rather than hiding it. Every analysis states its semantics
coverage, and `mythgauntlet home` shows the store size on the dashboard:

```
| Semantics (CCM)  14 authored + 0 compiled |
```

## Pointing the engine at a store elsewhere

`MYTHGAUNTLET_STORE` relocates the compiled store. Set it to a directory containing
`compiled/` and `ledger.json`:

```bash
setx MYTHGAUNTLET_STORE "C:\path\to\store"    # Windows, persistent
export MYTHGAUNTLET_STORE=/path/to/store          # POSIX
```

Unset, the engine uses this repo's own `ccm/`. The authored exemplars are **not** affected —
they are prompt source, they ship with the engine, and they stay findable either way.

This is how the maintainer's setup runs: the engine is here, the store is versioned in a
separate private repo, and `scripts/overnight.py` compiles straight into it. It also means you
can keep a store on another drive without a 130 MB duplicate beside the source.

## Building your own store

Nothing stops you. The compiler is included and documented:

```bash
mythgauntlet fetch-data                  # Scryfall bulk -> data/
mythgauntlet compile-top 50              # compile the 50 most-played uncompiled cards
mythgauntlet ccm-status                  # coverage + quarantine breakdown
```

It needs an OpenAI-compatible LLM endpoint on `127.0.0.1:8010` (this project uses llama-swap
serving `qwen3:14b`). See `docs/engine/CARD_SEMANTICS.md` for the schema, the validation gates,
and the prompt design. `scripts/overnight.py` is the unattended pipeline that builds the store
in bulk.

The gates are the interesting part and they are all here — the withheld artifact is the *output*
of running them, not the method.
