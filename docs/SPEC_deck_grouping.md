# SPEC: `frontend/src/utils/deckGrouping.js`

/no_think

This file is JavaScript (ES module, no TypeScript, no imports, no dependencies). Output ONLY
the JavaScript, inside a single fenced ```js block. Ignore any instruction elsewhere that
says Python.

## Purpose

Pure functions that organise a finished deck's cards into ordered groups for the deck view:
by card type, by functional role (ramp/draw/removal/...), by colour, or by mana value.
No React, no DOM, no fetch. Every function is pure and must not mutate its inputs.

## Card shape (verified against a real stored deck.json)

```js
{
  original_name: "Sol Ring",          // the real card name (string)
  themed_name: "Ring of the Forge",   // display name, ignore here
  type_line: "Artifact",              // may be reskinned by theming
  original_type_line: "Artifact",     // the real type line; may be missing -> fall back to type_line
  mana_cost: "{1}",                   // may be "" or missing (lands)
  cmc: 1.0,                           // number; may be missing on old decks
  colors: ["U"],                      // array of W/U/B/R/G; may be missing or null
  quantity: 1,                        // may be missing (means 1) or a string like "34"
  render_key: "..."                   // ignore here
}
```

## Exports (exact names and signatures)

```js
export const GROUP_BYS = ['type', 'role', 'color', 'cmc', 'none']
export const GROUP_BY_LABELS = { type: 'Card type', role: 'Role', color: 'Color', cmc: 'Mana value', none: 'No grouping' }

export const TYPE_ORDER = ['Creature', 'Instant', 'Sorcery', 'Enchantment', 'Artifact', 'Planeswalker', 'Land']
// Precedence when a type line names several types: an "Artifact Land" is a Land,
// an "Artifact Creature" is a Creature, an "Enchantment Creature" is a Creature.
export const TYPE_PRECEDENCE = ['Land', 'Creature', 'Planeswalker', 'Instant', 'Sorcery', 'Enchantment', 'Artifact']

export const ROLE_ORDER = ['ramp', 'draw', 'removal', 'noncreature_removal', 'wipe', 'counterspell', 'tutor', 'finisher', 'land', 'none']
export const ROLE_LABELS = {
  ramp: 'Ramp', draw: 'Card draw', removal: 'Creature removal',
  noncreature_removal: 'Other removal', wipe: 'Board wipes', counterspell: 'Counterspells',
  tutor: 'Tutors', finisher: 'Finishers', land: 'Lands', none: 'No measured role',
}

export const COLOR_ORDER = ['W', 'U', 'B', 'R', 'G', 'multi', 'colorless', 'land']
export const COLOR_LABELS = { W: 'White', U: 'Blue', B: 'Black', R: 'Red', G: 'Green', multi: 'Multicolor', colorless: 'Colorless', land: 'Lands' }

export function qty(card)            // -> integer >= 1
export function nameKey(name)        // -> string
export function cardTypeLine(card)   // -> string
export function primaryType(card)    // -> one of TYPE_ORDER or 'Other'
export function isLand(card)         // -> boolean
export function cardColors(card)     // -> array subset of ['W','U','B','R','G'], in WUBRG order, no duplicates
export function cardManaValue(card)  // -> number >= 0
export function groupCards(cards, by, rolesByName)  // -> array of groups (see below)
```

## Rules

- `qty(card)`: `Math.max(1, parseInt(card.quantity, 10) || 1)`.
- `nameKey(name)`: `String(name || '').split(' // ')[0].trim().toLowerCase()` (front face, lower case).
- `cardTypeLine(card)`: `card.original_type_line || card.type_line || ''`.
- `primaryType(card)`: the FIRST entry of `TYPE_PRECEDENCE` that `cardTypeLine(card)` contains
  (plain substring match); `'Other'` if none.
- `isLand(card)`: `primaryType(card) === 'Land'`.
- `cardColors(card)`: if `card.colors` is a non-empty array, use the WUBRG letters in it.
  Otherwise derive from `card.mana_cost`: find every `{...}` symbol; for each symbol, every
  letter W/U/B/R/G inside it counts (so hybrid `{W/U}` gives W and U, `{2/W}` gives W,
  Phyrexian `{G/P}` gives G). Return in WUBRG order without duplicates. A card with neither
  returns `[]`.
- `cardManaValue(card)`: if `Number(card.cmc)` is finite, return it. Otherwise parse
  `card.mana_cost`: each `{n}` digit symbol adds n, `{X}` adds 0, a hybrid with a digit half
  (`{2/W}`) adds the larger half (2), every other symbol adds 1. Missing cost -> 0.

### `groupCards(cards, by, rolesByName)`

Returns an array of `{ key, label, cards, count }`, in the fixed order listed for each mode,
**omitting empty groups**. `cards` keeps the input order. `count` is the sum of `qty` over the
group's cards (physical copies, not unique entries). An unknown `by` behaves like `'type'`.

- `'none'`: one group `{ key: 'all', label: 'All cards', ... }` holding every card.
- `'type'`: one group per `TYPE_ORDER` entry then `'Other'`; key = the type name, label = the
  type name pluralised for display: Creature->Creatures, Instant->Instants, Sorcery->Sorceries,
  Enchantment->Enchantments, Artifact->Artifacts, Planeswalker->Planeswalkers, Land->Lands,
  Other->Other.
- `'color'`: lands (by `isLand`) go to `'land'` whatever their colours. Otherwise 0 colours ->
  `'colorless'`, 1 colour -> that letter, 2+ -> `'multi'`. Order and labels from
  `COLOR_ORDER` / `COLOR_LABELS`.
- `'cmc'`: lands go to `'land'` (label `'Lands'`). Otherwise bucket =
  `Math.min(7, Math.floor(cardManaValue(card)))`; key is the string of that number (`'0'` ..
  `'7'`), label is `'0'`..`'6'` and `'7+'` for 7, each prefixed `'MV '` (e.g. `'MV 3'`,
  `'MV 7+'`). Order: `'0'`..`'7'`, then `'land'`.
- `'role'`: `rolesByName` is an object mapping `nameKey(name)` -> array of role strings.
  - If `rolesByName` is null or undefined, return ONE group
    `{ key: 'unmeasured', label: 'Roles not measured yet', cards: all, count }`.
  - Otherwise a card is placed in EVERY group named by its roles (a card that is both ramp
    and draw appears in both groups — this is intended). A card whose entry is missing or an
    empty array goes to `'none'`. A role string not in `ROLE_ORDER` gets its own group after
    the known ones (in first-seen order) with label = the role string with `_` replaced by a
    space and the first letter upper-cased.
  - Order: `ROLE_ORDER` (with `'none'` last of all, after any unknown roles). Labels from
    `ROLE_LABELS`.

## Worked examples (reproduce these in a JSDoc comment at the top of the file)

| input | call | result |
|---|---|---|
| `{colors:null, mana_cost:'{2}{W/U}{B}'}` | `cardColors` | `['W','U','B']` |
| `{cmc:undefined, mana_cost:'{X}{2/W}{G}'}` | `cardManaValue` | `3` |
| `{original_type_line:'Artifact Land', type_line:'Artifact Land'}` | `primaryType` | `'Land'` |
| `{quantity:'34'}` | `qty` | `34` |
| `[Forest x34 qty]`, by `'color'` | `groupCards` | `[{key:'land', label:'Lands', count:34}]` |
| Mind Stone with roles `['draw','ramp']`, by `'role'` | `groupCards` | groups `ramp` then `draw`, each holding Mind Stone |
