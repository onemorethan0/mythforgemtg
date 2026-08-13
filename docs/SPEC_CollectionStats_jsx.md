# SPEC — `frontend/src/components/CollectionStats.jsx`

/no_think

Write the complete React component file. Output ONLY the code in a single ```jsx fenced
block. No prose. **You are writing JavaScript + JSX, not Python.**

## Context

Myth Forge is a React/Vite SPA with **no CSS framework and no chart library** — every
component uses inline `style={{...}}` objects only. Do not import anything except React.
There is no TypeScript. No `className`. No external packages.

```jsx
import { useState } from 'react'
```
is the ONLY import allowed.

## Props

```jsx
export default function CollectionStats({ stats, onFilter })
```

- `stats` — the payload described below, or `null` while loading.
- `onFilter` — optional `(criteria) => void`. Calling it asks the parent to apply a
  filter. Criteria objects are exactly `{colors:[...]}`, `{types:[...]}`,
  `{rarities:[...]}`, `{cmc_min:n, cmc_max:n}`. Guard every call with `onFilter &&`.

## The `stats` shape (exact — do not invent fields)

```js
{
  totals: { distinct, copies, value, priced, unpriced, unresolved },
  colors:         [{ key:"W", label:"White", distinct, copies, value }],   // key is one of
                                                                          // W U B R G
                                                                          // Multicolor Colorless
  color_presence: [{ key:"W", label:"White", distinct, copies }],          // always 5
  types:          [{ key:"Creature", distinct, copies }],
  rarities:       [{ key:"rare", label:"Rare", distinct, copies, value }],
  curve:          [{ cmc:0, label:"0", distinct, copies }],                // always 8, last is "7+"
  sets:           [{ key:"SOS", distinct, copies, value }],                // <=15; key "—" means
                                                                          // printing unknown
  top_value:      [{ name, set, cn, count, price, total }],
}
```

## Style tokens — copy these exactly, they match the rest of the app

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

Dark theme throughout. Panels: `background: c.panel`, `border: 1px solid ${c.border}`,
`borderRadius: 10`, `padding: 14`. Section headings: `fontSize: 12`, `fontWeight: 700`,
`color: c.dim`, `letterSpacing: '0.06em'`, `textTransform: 'uppercase'`,
`marginBottom: 10`.

## Layout

Return `null` when `stats` is falsy.

A single wrapper `<div>` containing, in order:

**1. Headline row** — three figures side by side (flex, `gap: 18`, wrap):
`$` + `totals.value` (large, `fontSize: 22`, `fontWeight: 700`, `color: c.green`),
`totals.copies` cards, `totals.distinct` unique. Under it, in `fontSize: 11.5` /
`color: c.faint`: `"{priced} priced · {unpriced} unpriced"`, and when
`totals.unresolved > 0` also `" · {unresolved} unrecognized"` in `#f59e0b`.

Format money with
`v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })`.

**2. Colors** — a single horizontal **stacked bar**, height 26, `borderRadius: 6`,
`overflow: 'hidden'`, `display: 'flex'`. One segment per `stats.colors` entry with
`flexGrow: entry.distinct`, `background: MANA[entry.key]`, and `cursor: 'pointer'` when
`onFilter` is given. Clicking calls `onFilter({ colors: [entry.key] })`. Each segment
shows its `distinct` count centered in `fontSize: 10`, `fontWeight: 700` — use
`#1c1917` text on `W` and `Multicolor`, `#f5f5f4` on the rest. `title` attribute:
`` `${label}: ${distinct} cards, ${copies} copies` ``. Skip a segment whose `distinct`
is 0. Below the bar, a small legend: a 9px colour dot + `label` + count per entry,
wrapped in a flex row with `gap: 10`, `fontSize: 11`, `color: c.dim`.

**3. Mana curve** — a column chart from `stats.curve`. A flex row, `alignItems: 'flex-end'`,
`gap: 6`, `height: 90`. Each bucket is a column (`flex: 1`) holding a bar whose height is
`` `${Math.round(100 * distinct / max)}%` `` where `max` is the largest `distinct` in the
array (**guard `max === 0` → render every bar at 0% and never divide by zero**), plus the
`label` underneath in `fontSize: 10`, `color: c.faint`. Bar background `c.gold`,
`borderRadius: '3px 3px 0 0'`, `minHeight: 2`. Clicking a bar calls
`onFilter({ cmc_min: cmc, cmc_max: cmc === 7 ? 99 : cmc })`. `title`:
`` `MV ${label}: ${distinct} cards` ``. Add a caption under the section in `fontSize: 11`
/ `color: c.faint`: `"Lands excluded."`

**4. Types and Rarities** — side by side in a responsive grid
(`display: 'grid'`, `gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))'`,
`gap: 14`). Each is a list of rows: label on the left, `distinct` right-aligned in
`c.gold`, and a thin proportional bar (height 4, `background: c.gold`, width
`${100*distinct/maxOfThatList}%`) under each row. Rows are clickable →
`onFilter({ types: [key] })` / `onFilter({ rarities: [key] })`.

**5. Top value** — a `<ol>`-style list (use divs, not `<ol>`) of `stats.top_value`:
rank, `name`, a small `set` chip when `set` is truthy, `` `x${count}` `` when
`count > 1`, and `$total` right-aligned in `c.green`. `fontSize: 12.5`. Show a
`title` of `` `$${price} each` ``.

**6. Sets** — collapsed by default behind a button reading
`` `Sets (${stats.sets.length}) ▾` `` / `▴` using `useState`. When open, list each set:
`key` (render the `"—"` key as the text `"printing unknown"` in `c.faint`), its `distinct`
count, and `$value`.

## Robustness

Every array access must tolerate a missing/empty array (`(stats.colors || [])`). Never
divide by zero. Never assume `top_value` is non-empty — render a
`"No prices yet."` line in `c.faint` when it is empty.

Give every list item a stable React `key` prop (use the entry's `key`/`cmc`/`name`).

## Style

2-space indent, single quotes, no semicolons at end of statements (the repo omits them),
arrow-function components, `const` over `let`. Keep it under ~230 lines.
