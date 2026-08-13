# SPEC — `frontend/src/components/CollectionGrid.jsx`

/no_think

Write the complete React component file. Output ONLY the code in a single ```jsx fenced
block. No prose. **You are writing JavaScript + JSX, not Python.**

## Context

Myth Forge is a React/Vite SPA with **no CSS framework and no chart library**. Every
component styles itself with inline `style={{...}}` objects. No `className`, no
TypeScript, no external packages.

Allowed imports — these two lines EXACTLY, nothing else:

```jsx
import { useState } from 'react'
import CardHover from './CardHover'
```

## What it is

A "binder" grid of the cards the user owns: one tile per collection row, showing the real
card image. It replaces the text list when the user picks grid view. Cards the user owns
several of show a count badge.

## Props

```jsx
export default function CollectionGrid({ cards, onSetCount, onRemove, onPickPrinting,
                                         selectMode, selected, onToggleSelect, busy })
```

- `cards` — array of collection rows (shape below).
- `onSetCount(row, count)` — set an exact count. Count 0 removes.
- `onRemove(row)` — remove the row entirely.
- `onPickPrinting(row)` — open the printing picker for this row. May be undefined.
- `selectMode` — boolean; when true each tile shows a checkbox instead of hover controls.
- `selected` — a `Set` of row keys (see `rowKey` below) currently selected.
- `onToggleSelect(row)` — toggle one row's selection.
- `busy` — boolean; disable all mutating controls while true.

Guard every optional callback with `&&` before calling.

## Row shape (exact — do not invent fields)

```js
{ name, count, set, cn, price, image, cmc, type, type_line, colors, rarity, resolved }
```

- `image` is a small card-image URL **or null**. Null is common — do not assume it.
- `colors` is an array like `['R']`, `['W','U']`, or `[]`.
- `price` is a number or null.
- `resolved` false means the name matched no card.

## Row identity

A card can be owned in several printings, so the name alone is not unique:

```js
const rowKey = r => `${r.name}|${r.set || ''}|${r.cn || ''}`
```

Use it for the React `key` AND for `selected.has(...)`.

## Style tokens — copy these exactly

```js
const c = {
  gold:   '#eab308',
  green:  '#4ade80',
  dim:    '#a8a29e',
  faint:  '#78716c',
  card:   '#1c1917',
  border: '#292524',
  panel:  '#0c0a09',
  text:   '#f5f5f4',
}
const MANA = { W:'#f8f0d8', U:'#4a90d9', B:'#5b5254', R:'#d94a4a', G:'#4aa563',
               Multicolor:'#c9a227', Colorless:'#8a8a8a' }
```

Dark theme throughout.

## Layout

Return an empty-state div (`'Nothing to show.'`, `fontSize: 13`, `color: c.faint`,
`padding: 20`, `textAlign: 'center'`) when `cards` is falsy or empty.

Otherwise a responsive grid:

```js
{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 12 }
```

### Each tile

A `position: 'relative'` div with `borderRadius: 10`, `overflow: 'hidden'`,
`background: c.card`, `border: 1px solid ${c.border}`, and `aspectRatio: '488 / 680'`
(real MTG card proportions). Track hover with a `useState` holding the hovered row key —
one piece of state for the whole grid, not one per tile.

**Image.** When `row.image` is truthy render
`<img src={row.image} alt={row.name} loading="lazy" style={{ width:'100%', height:'100%', objectFit:'cover', display:'block' }} />`.
`loading="lazy"` is required — a thousand tiles must not fetch a thousand images at once.

**No image.** Render a fallback panel instead: `background: c.panel`, centered, showing the
card name in `fontSize: 11.5`, `color: c.dim`, `padding: 8`, `textAlign: 'center'`, with
`overflow: 'hidden'`. Above the name put a colour dot 14px round whose background is
`MANA[colors[0]]` when exactly one colour, `MANA.Multicolor` when more than one, else
`MANA.Colorless` — and when `resolved` is false use a transparent background with
`1px solid ${c.faint}` instead. Under the name show `row.type` in `fontSize: 10` /
`color: c.faint` when present.

**Count badge** — top-left, only when `count > 1`. `position:'absolute'`, `top:6`,
`left:6`, `padding:'1px 7px'`, `borderRadius:6`, `fontSize:11`, `fontWeight:700`,
`background:'rgba(0,0,0,0.82)'`, `color:c.gold`, `border:1px solid ${c.border}`, text
`` `x${count}` ``.

**Price badge** — top-right, only when `price` is a number. Same styling but
`color: c.green` and text `` `$${price.toFixed(2)}` ``.

**Selection.** When `selectMode` is true, render a checkbox at top-left (replacing the
count badge position — put the count badge at `left: 30` instead so they don't overlap).
`<input type="checkbox" checked={selected.has(rowKey(row))} onChange={() => onToggleSelect && onToggleSelect(row)} />`
wrapped in an absolutely positioned label with a dark round background. Clicking anywhere
on the tile in select mode should also toggle it — put `onClick` on the tile itself and
give it `cursor: 'pointer'`.

**Hover controls.** When NOT in select mode and this tile is hovered, render a bar pinned
to the bottom of the tile (`position:'absolute'`, `left:0`, `right:0`, `bottom:0`,
`background:'rgba(0,0,0,0.86)'`, `padding:'6px'`, `display:'flex'`, `gap:4`,
`alignItems:'center'`, `justifyContent:'center'`) containing:
- a `−` button → `onSetCount(row, row.count - 1)`
- the count in `color: c.gold`, `fontWeight: 700`, `minWidth: 18`, centered
- a `+` button → `onSetCount(row, row.count + 1)`
- a `🖨` button → `onPickPrinting(row)`, only rendered when `onPickPrinting` is given,
  `title="Choose printing"`
- a `✕` button → `onRemove(row)`, `color: '#f87171'`, `title="Remove"`

All buttons: `padding:'1px 7px'`, `borderRadius:6`, `fontSize:12`,
`background:c.card`, `border:1px solid ${c.border}`, `color:c.dim`,
`fontFamily:'inherit'`, `cursor: busy ? 'wait' : 'pointer'`, and `disabled={busy}`.
Give each a `title`.

**Name strip.** Always render, under the image, OUTSIDE the aspect-ratio tile — so wrap
each tile and its name in an outer div. The name uses `<CardHover name={row.name}>` around
the text, `fontSize: 11.5`, `color: c.text`, `marginTop: 4`, and single-line ellipsis
(`overflow:'hidden'`, `textOverflow:'ellipsis'`, `whiteSpace:'nowrap'`). Under it, when
`row.set` is truthy, show the set code in `fontSize: 10` / `color: c.faint`; when it is
falsy show nothing.

## Robustness

- Never assume `cards` is an array — guard with `(cards || [])`.
- Never call `.toFixed` on a null price.
- Never assume `selected` exists — default to an empty `Set` when it is undefined.
- Every mapped element needs a stable `key`.

## Style

2-space indent, single quotes, no trailing semicolons, `const` over `let`, arrow
functions. Keep it under ~200 lines.
