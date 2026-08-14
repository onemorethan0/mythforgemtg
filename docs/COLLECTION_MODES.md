# Collection modes and deck quality

Myth Forge's engineering map is `CLAUDE.md`, and that file is **gitignored**
(`.gitignore:32`) — everything in it is local-only and never reaches a fresh clone. This
document is the tracked home for the collection-building modes and the three local
modules that make them work. It assumes you have the code but have never seen `CLAUDE.md`.

## Card sources

`BuildRequest` and `GenerateListRequest` carry a `card_source` field. The constants live
in `deck_builder.py` as `SOURCE_SCRYFALL` / `SOURCE_PREFER` / `SOURCE_COLLECTION`.

| mode | draws from | when the pool is short |
|---|---|---|
| `scryfall` | Scryfall only; the collection is ignored | n/a — the whole format is available |
| `prefer_collection` | owned cards first, then Scryfall | Scryfall staples fill every gap |
| `collection` | **owned cards only**, plus basic lands | reports the gap, pads with basics |

**`use_collection: true` has always meant PREFER, never "owned only."**
`server._resolve_card_source(card_source, use_collection)` derives the mode when
`card_source` is empty or unrecognised, so every caller predating the field keeps its
exact behaviour. Redefining the boolean would have silently narrowed the decks of anyone
already using it — which is why the enum is three-way rather than the flag being
reinterpreted.

Strict mode is reachable from the Collection screen's "Build from what I own" panel: each
buildable commander offers **"Build this →"** (prefer) and a separate **"🎴 Only cards I
own"** (strict). Both route through `App.handleBuildFromCollection(name, strict)`, which
pins `cardSource`. The pin is cleared in `reset()` and on every fresh hub entry, so one
strict build cannot silently constrain an unrelated later one.

## What strict mode cannot do, and how it says so

**Name RESOLUTION still uses Scryfall; only SEARCH is unavailable.** That distinction is
the whole design. Turning owned names into card data is a lookup and is cached;
discovering new cards is a search and is what strict mode forbids. `DeckBuilder._strict()`
gates every draft path, and `tests/test_deck_builder_theme.py` drives a stub client whose
`search_cards_paged` **raises**, so a passing test is positive proof no search happened.

Two honesty channels, because a strict build that quietly ships a worse deck is the
failure mode worth designing against:

* **`builder.shortfall`** — a `dict[str, int]` of per-role deficits. Also carries
  `padded_with_basics` when the owned pool runs dry and `_pad_with_basics` makes up the
  count; without that key a small collection produced a deck that was mostly Mountains
  with nothing saying why.
* **`builder.source_fallback`** — a sentence, set when `_resolve_owned_cards` returns
  nothing (e.g. a red commander over an all-white collection) and the build reverts to
  Scryfall. It replaced a sentinel that rendered as the meaningless "Collection couldn't
  cover: collection (-99)".

Both reach the user: the SSE progress stream during the build, `deck.json`'s `collection`
block afterwards, and an amber line in StepDeck. That line is gated on `deck.collection`
alone — nesting it under the quality block once meant an empty measurement suppressed the
reporting entirely.

Theme synergy is a Scryfall search by construction, so strict mode reproduces it locally
(see `theme_match` below) rather than skipping it.

## The three local modules

All three are pure and offline: standard library only, no network, no imports from the
web stack. That is what lets them be unit-tested with plain dicts.

### `collection_pool.py`

Classifies an owned card into deck roles from its own oracle text, replacing the Scryfall
`otag:` role queries that strict mode cannot run. `classify()` returns any of
`ramp / draw / removal / wipe / protection / finisher`; `build_pool()` partitions a
collection for one commander; `rank_key()` is the repo's single EDHREC ordering.

Each guard exists because the naive version shipped and was wrong:

* **Net-positive mana only.** `{1}, {T}: Add {B}` nets zero and is not ramp. A broad
  `{T}: Add {` pattern matched the substring *inside* that cost and returned `ramp` before
  the gate could reject it. A filter rock (`{1},{T}: Add {W}{W}`, net +1) still is ramp.
* **Counts are words.** Oracle text reads "Draw two cards", not a digit. `draw \d+ cards`
  silently dropped Seize the Spoils, Laughing Mad and Dangerous Wager.
* **"each creature" is SINGULAR.** Blasphemous Act says it twice and never says
  "creatures", so a plural gate wrapping the wipe patterns blocked its own correct match.
* **Object, not just verb.** Vandalblast destroys target *artifact* — removal, not a wipe.
  Rest in Peace exiles all *graveyards* — neither.
* **HAS versus GRANTS.** A creature with indestructible protects only itself; Darksteel
  Plate grants it to another and is protection.
* **Role lists are nonland by construction.** `classify()` legitimately tags Command Tower
  as ramp, but the builder drafts role slots straight from these lists and every
  `ROLE_QUERY` it mirrors carries `-type:land`. When lands leaked in, a strict build pulled
  them into ramp, bypassed the bracket land-tier gate and overshot its land count.
* **`land_tier()` returns `None` meaning "allow".** It identifies only the tiers low
  brackets actually restrict. Mislabelling an ordinary owned dual would gut a manabase,
  whereas admitting one extra good land only softens a cap.

### `deck_quality.py`

Measures a finished list: mana curve against a reference curve, and whether the manabase
can actually cast the deck. It **decides nothing** — nothing here changes card selection.

* **`quantity` is load-bearing.** Basics aggregate into one dict carrying `quantity: 14`,
  so every count sums `qty()` and never uses `len()`. Getting this wrong makes a 36-land
  deck look like a 10-land deck.
* **The average uses TRUE mana value; only bucketing clamps.** Averaging the clamped value
  reported a deck of three 9-drops as 7.0 — understating exactly the top-heavy decks the
  module exists to detect.
* **MV 0 is a one-drop** (`bucket()`). `curve_target` has no bucket 0, so leaving zero-cost
  cards in their own bucket meant they could never satisfy a shortfall and Mox Amber was
  drafted only after every bucket was full.
* **Colour sources come from `produced_mana` or an `Add` clause, never from colour words.**
  A non-producer carries `produced_mana: []`, which is falsy — so a fallback that scanned
  oracle text counted Nim Deathmantle ("is a black Zombie") as a black mana source and
  reported a broken manabase as fine.
* **Source counts are filtered to the deck's identity.** Command Tower lists all five
  colours in `produced_mana` but only makes what your commander's identity allows. An
  imported deck can carry `commander: {"color_identity": None}`, so the filter falls back
  to the colours the deck's own pips demand.

### `theme_match.py`

Reproduces `commander_analysis.THEME_SYNERGY_QUERIES` (40 themes) from `type_line` and
`oracle_text` alone. `theme_score()` returns `NO_MATCH` / `WEAK` / `STRONG`;
`match_themes()` returns theme → ranked cards.

* **Fidelity governs the MATCH SET; the score governs only ORDERING.** A card Scryfall
  would not return is not returned here — including the awkward cases. Living Death says
  "from *their* graveyard", so it is not a `graveyard` card by that query's literal
  reading. Scryfall provided no ordering at all beyond EDHREC, so refining the order
  cannot pull in a card the query excluded.
* **Tribe words accept the regular plural.** Scryfall's `o:` is a substring match, so
  `o:"dragon"` hits "Dragons"; a bare `\bdragon\b` does not. That made strict mode
  narrower than the query it reproduces and dropped 46 real payoffs templated only in the
  plural, such as Death-Priest of Myrkul ("Skeletons, Vampires, and Zombies you control
  get +1/+1"). The `\b` bounds stay, because a raw substring puts `cat` inside `escalate`,
  `duplicate` and `scatter`.
* **`SCORE_ORDERED` limits score-first ordering to the 21 `tribal_*` themes.** The score is
  only meaningful where WEAK means "is a member of the thing". Where WEAK is a whole card
  TYPE it contains every staple: measured over the 34k-card store, `artifacts` has **5
  STRONG against 3909 WEAK**, so reordering would demote Sol Ring, Arcane Signet and
  Lightning Greaves for five obscure artifact-ETB triggers. `voltron` is 4 vs 1909 with
  medians 16700/16948 — noise. For the 15 themes with no WEAK tier at all, every match is
  STRONG and score-first is a no-op.

## Deck quality on every deck

`compute_stats()` attaches a `quality` block, so generate, rebuild, retheme **and imported
decks** all get it from one place — "Analyze a Deck" reports whether a list you already own
can cast itself. The shape is exactly two keys:

```
stats["quality"] = {
  "curve":  {average, verdict, buckets, target, over, under, notes},
  "colors": {ok, pips, sources, required, short, notes},
}
```

`verdict` is one of `ok` / `top-heavy` / `too-flat`. The block is `{}` for a deck with no
nonland cards — a single custom card (`mode: single_card`) carries `deck == []`, and
measuring it anyway reported a deck of one as "short on sources".

`server._backfill_quality` derives the block on load for decks built before it existed;
without that, the feature would only ever have appeared on new decks and the whole stored
library would stay dark. It is **not** written back to disk, so the stored files and the
mtimes History orders by are left alone.

## Working on this code

* Tests run with **no `data/` directory and no network** — that is CI's actual state.
  Never read `data/cards_slim.json` from a test; inline verbatim oracle text as fixtures.
  Note that store is a snapshot: a card newer than its build date will be absent, which is
  not evidence the card is fake.
* **Magic is precise.** A wrong card model is a defect, not an approximation. If a test
  asserts something about a card, the oracle text must actually say it.
* `scripts/offload.py` runs the spec → local model → review loop against llama-swap on
  `127.0.0.1:8010`. It distinguishes two failure signatures: HTTP 500 whose body contains
  `"prematurely"` is a CUDA OOM and is **not** retried; 502/503 is a mid-swap model load
  and **is** retried with backoff. Drafts are never landed unread — expect one or two real
  defects per generated file.
