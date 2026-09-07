# The engine's card semantics — what ships, what doesn't

Myth Forge contains the **MythGauntlet simulation engine** at `src/mythgauntlet/`. The engine
source is open and included. The **compiled card semantics it consumes are not bundled in this
repo** — they're a separately-downloaded, actively-training dataset. This page says exactly
what's missing, how to get a beta copy, and what the engine does without one.

## The short version

| | included | why |
|---|---|---|
| Engine source (`src/mythgauntlet/`) | ✅ yes | the simulator, ratings, bracket logic, CLI, API |
| Authored exemplars (`ccm/authored/`, 14 files) | ✅ yes | hand-written schema examples — prompt *source*, not compiled output |
| Deck corpus (`corpus/decks/`, 407 lists) | ✅ yes | public decklists + bracket labels; the calibration anchor set |
| **Compiled semantics (`ccm/compiled/`, ~32k)** | 🟡 **beta download** | not in the git repo — `python download-ccm.py`; see below |
| **Compilation ledger (`ccm/ledger.json`)** | 🟡 **beta download** | per-card status for the above, same download |
| Scryfall bulk (`data/`) | ❌ not shipped | download it yourself: `mythgauntlet fetch-data` |

## Why the compiled semantics aren't in the git repo

A **CCM** (Card Capability Model) is a JSON document describing what a card actually *does* —
its costs, triggers, and effects over a closed vocabulary the simulator can execute. It is what
lets the engine play a card rather than pattern-match its Oracle text.

Those ~30,000 documents are not a scrape. Each one was compiled by a local LLM against a
hand-tuned prompt, then put through three validation gates (schema, Scryfall lint, and a
bidirectional cross-check against independent heuristics), with failures quarantined and
retried as the prompt improved. That represents many hundreds of overnight GPU-hours and nine
revisions of the compiler prompt.

**It is also not finished.** The compiler is still running nightly and the quarantine backlog is
still shrinking — the corpus of executable semantics grows and improves week over week. It isn't
bundled in this repo for that reason: baking a moving, imperfect dataset into a versioned git
tree means every user is stuck with whatever vintage they happened to clone.

**A beta snapshot is published separately** for anyone who wants the improved fidelity now,
labeled with its own vintage rather than pretending to be finished — see "Downloading a
compiled snapshot" below. It ships under **CC BY-NC 4.0** (free for personal/non-commercial
use, attribution required — full terms bundled as `LICENSE-CCM-DATA.txt` inside the download)
with a note for anyone who wants a commercial license to contact the maintainer directly.

**The compiler runs nightly (Tuesday–Friday) and will keep running until the quarantine
backlog is gone and every card is on the current prompt version.** The published snapshot is
refreshed from that same run periodically — it is not a one-time drop. Re-downloading later
gets you whatever the compiler has improved since.

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

## Downloading a compiled snapshot (optional, beta)

`download-ccm.py` (or `download-ccm.bat` / `manage.bat` → option 10) fetches the current
published snapshot straight into `ccm/`:

```bash
python download-ccm.py
```

A snapshot is a zip of `compiled/*.json` + `ledger.json` plus a `_manifest.json` that states
its own vintage honestly — the same way every other measurement in this app states its
coverage. After downloading, the script prints that manifest, including `status` (it says
"beta" and that the compiler is still running) and `pct_current_prompt`: the fraction of the
snapshot compiled under the *current* compiler prompt version versus an older one. That number
matters more than the raw card count — an older-prompt card can carry error classes (misread
triggers, wrong costs, phantom targets) that a later prompt revision fixed but hasn't
re-compiled yet. **As of this snapshot: 31,703 cards compiled, 32.2% on the current prompt
(v11).** It's still strictly better than rung-1 fallback for every card it covers — it's just
not finished, and the manifest says so rather than hiding it.

The compiler runs nightly and this number will climb; there's no notification when it does,
so re-run `download-ccm.py` occasionally (it asks before overwriting an existing store) rather
than assuming today's snapshot is the last one.

`MYTHFORGE_CCM_URL` overrides where it downloads from, if you're pointed at a mirror or a
different snapshot than the built-in default.

Nothing downloads automatically — this is opt-in, matches the pattern of
`download-models.py` for art checkpoints, and a missing or 404'd snapshot is not an error:
the engine already runs fine without one.

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
