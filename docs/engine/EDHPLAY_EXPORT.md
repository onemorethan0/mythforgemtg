# EDHPlay custom-art export

`mythgauntlet edhplay DECK.txt` gets your **MythForge custom card art** onto
[EDHPlay](https://edhplay.com) so you can play your themed deck online with the AI-generated
art (not the stock printing). It produces two things:

1. an EDHPlay **Bulk-Import** decklist (paste into *Create Deck -> Bulk Import*), and
2. a **Tampermonkey userscript** that displays your MythForge renders on the cards while you play.

## Why a userscript (the method, and why it's the only one)

EDHPlay has **no way to upload custom card art**. It renders every card as an `<img>` whose
`src` is a Scryfall image URL keyed by that printing's UUID
(`cards.scryfall.io/normal/front/9/3/<uuid>.jpg`); its only cosmetic options are sleeves and
playmats, and even its "custom token" feature just reuses an existing card's art. There is no
server-side field to point a card at your own image.

So the art is swapped **client-side**. A small userscript watches EDHPlay's DOM and rewrites
the `src` of any card image whose Scryfall UUID belongs to a card we have custom art for,
pointing it at your MythForge render instead. This was verified against the live site: the
swap replaces the card face in hand, on the battlefield and in zoom previews, and re-applies
when EDHPlay re-renders a card.

**Important: the custom art is local to your browser.** Opponents see the normal printing
unless they install the same userscript and can reach the same images. This is for *your* view
of your themed deck.

### How the mapping is robust

The userscript maps **every** printing UUID of each deck card (from the printings store) to
that card's custom image. So the swap fires no matter which printing EDHPlay shows, and you
don't have to make the pasted decklist pick an exact printing.

## Data

Mapping card -> printing UUIDs needs every printing of each card, which the simulation card
store (`oracle_cards`, one printing per card) doesn't carry. So this path uses a separate
store, `data/printings_slim.json`, slimmed from Scryfall's `default_cards` bulk file. One-time
download (~450 MB raw, deleted after slimming), gitignored, never touches the simulation:

```
mythgauntlet edhplay --fetch-printings          # or --fetch-printings --force to refresh
```

## Custom-art sources (`--art-source` / `--myth-job`)

| source | meaning |
|---|---|
| `mythforge:<job_id>` (or `--myth-job <job_id>`) | pull a MythForge build's `deck.json` from `--myth-url` (default `http://127.0.0.1:8000`); each card points at its `card-image/<render_key>` render. Only cards MythForge actually rendered are included. |
| `dir:<path>` | a folder of `<Card Name>.png` (or .jpg/.webp) files, matched by filename. |
| `manifest:<file>` | a JSON `{name: url-or-path}` or text `Name = url-or-path` file. |

By default MythForge/URL art is **fetched at play time** (`GM_xmlhttpRequest`, so EDHPlay's
HTTPS page can read `http://127.0.0.1:8000`), which keeps the userscript small but needs
MythForge running while you play. `--embed` bakes the images into the userscript as data URIs
instead: larger file, but self-contained and portable (no server needed). Local `dir:` /
`manifest:` files are always embedded.

## Usage

```
# 1. one-time: get the printings store
mythgauntlet edhplay --fetch-printings

# 2. build the deck in MythForge, note its job id, then:
mythgauntlet edhplay my_deck.txt --myth-job <JOB_ID> \
    --out my_deck.edhplay.txt --userscript my_deck.user.js

# self-contained variant (no MythForge running at play time):
mythgauntlet edhplay my_deck.txt --myth-job <JOB_ID> --embed --userscript my_deck.user.js

# custom art from a plain folder of images instead of MythForge:
mythgauntlet edhplay my_deck.txt --art-source dir:./my_art --userscript my_deck.user.js
```

Then: paste `my_deck.edhplay.txt` into EDHPlay *Create Deck -> Bulk Import*, and install
`my_deck.user.js` in Tampermonkey. Open EDHPlay and your custom art shows on the cards.

The CLI reports how many cards were matched, how many deck cards had no custom art (they show
their normal printing), any MythForge cards not yet rendered, and any art files whose name
didn't match a deck card.

## Printing selection (the pasted decklist)

Independently of the art swap, the pasted decklist can pin a specific **printing** per card via
EDHPlay's `1 Name (SET) collector` bulk format (verified against EDHPlay's own importer). This
controls the *fallback* art EDHPlay shows for cards you have no custom render for, and is
useful on its own if you just want nicer official printings:

* `--policy default|newest|oldest|borderless|showcase|extended|fullart|textless|retro|random`
  (deck-wide; `default` leaves EDHPlay's own default printing).
* `--art FILE` — per-card overrides, one `Name = spec` line each, where spec is an exact
  printing (`ltc 280` / `(ltc) 280` / `ltc/280`), a whole set (`cmm`), a Scryfall print id
  (`scryfall:<uuid>`), or a policy keyword (`borderless`). Overrides win; misses fall back and
  are reported.
* `--json` emits the `POST /api/v1/decks/{id}/bulk-import` API body
  (`{cards, commander, partner_commander, replace}`) instead of paste text, for a scripted push.

Commander(s) are emitted in a leading comment block because EDHPlay takes the commander when
you create the deck, not in the pasted 99. Names are canonicalized against the `oracle_cards`
store when present so nicknames / front-face names still match.
