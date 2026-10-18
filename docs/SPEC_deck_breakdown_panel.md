# SPEC: `frontend/src/components/DeckBreakdownPanel.jsx`

/no_think

This file is a React 19 function component in plain JSX (no TypeScript). Output ONLY the
JSX, inside a single fenced ```jsx block. Ignore any instruction elsewhere that says Python.

## Purpose

Charts for the Deck Mentor's measurements of a finished deck, so the numbers the mentor
answers role questions from are visible without asking: role coverage (cards vs a typical
card target), interaction coverage by permanent type, and colour sources. It also hands the
per-card roles to its parent so the deck view can group cards by role.

No chart library. Draw bars with plain `<div>`s and inline `style={{...}}` objects (the
surrounding app uses inline styles, not CSS classes). Dark theme colours only:
background `#0c0a09` / panels `#1c1917`, borders `#292524`, muted text `#78716c`, body text
`#a8a29e`, bright text `#f5f5f4`, accent gold `#ca8a04`, good `#22c55e`, short/warning
`#f59e0b`, bad `#ef4444`, not-applicable grey `#44403c`. Font sizes 11-13px.

## Imports (exactly these)

```jsx
import { useEffect, useState } from 'react'
```

## Export

```jsx
export default function DeckBreakdownPanel({ jobId, onRoles })
```

- `jobId`: string.
- `onRoles`: optional function. Called with an object mapping card-name-key -> array of
  role strings whenever data arrives, where the key is
  `String(name).split(' // ')[0].trim().toLowerCase()`. Called with `null` while nothing
  has loaded or on error.

## Data

On mount (and whenever `jobId` changes) POST `/api/deck/${jobId}/breakdown`. A "↻ Re-measure"
button POSTs `/api/deck/${jobId}/breakdown?refresh=true`. Use `fetch`; on a non-OK response
read `(await res.json()).detail` (fall back to `res.statusText`) and show it as an error
line. While loading show "Measuring roles…". Guard against setting state after unmount or
after `jobId` changed (an `active` flag in the effect).

Response JSON (verified shape):

```js
{
  cached: true, computed_at: "2026-10-18T11:02:03",
  roles: {
    unit: "cards",
    rows: [ { role: "ramp", cards: 13, card_target: 12, short_by: 0 },
            { role: "removal", cards: 2, card_target: 7, short_by: 5 }, ... ],
    under_target: ["removal", "draw"],
    most_under_supplied: "removal",            // or null
    not_applicable: [ { role: "counterspell", cards: 0, note: "not applicable: ..." } ],
  },
  removal: {
    counts_by_type: { creature: {answers: 6, unrestricted: 4}, artifact: {answers: 2, unrestricted: 2},
                      enchantment: {...}, planeswalker: {...}, land: {...}, spell: {...} },  // spell may be absent
    answers_by_type: { creature: ["Swords to Plowshares", ...], ... },
    no_answer_for: ["planeswalker"],
    no_unrestricted_answer_for: ["planeswalker", "enchantment"],
    not_applicable_types: { spell: "answering spells on the stack is mostly blue's job ..." },
    exile_count: 3, instant_speed_count: 5,
  },
  manabase: {
    sources: { W: 18, U: 14 },                 // only colours in the deck's identity
    consistency: 0.87,
    worst_colors: [ { color: "U", turn: 2, have: 14, need: 16, probability: 0.81, example: "Counterspell" } ],
  },
  curve: { buckets: {"1": 8, "2": 12, ...}, average_mana_value: 3.1, nonland_count: 63, land_count: 36 },
  cards: [ { name: "Sol Ring", qty: 1, roles: ["ramp"], commander: false }, ... ],
}
```

## Layout

A container `<div>` (background `#0c0a09`, border `1px solid #292524`, radius 10, padding 14,
marginBottom 16). Header row: title "📊 Deck Breakdown" (13px bold, `#f5f5f4`), a muted
subtitle "The numbers the Deck Mentor answers from", and on the right the Re-measure button
plus, when `computed_at` is present, "measured <computed_at with 'T' replaced by ' '>".
A "▾ / ▸" toggle collapses the body (default open).

Body: three sections in a responsive grid
(`display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(260px, 1fr))', gap: 16`).

### 1. Role coverage — "Roles (cards vs typical)"

Role labels: ramp "Ramp", draw "Card draw", removal "Creature removal",
noncreature_removal "Other removal", wipe "Board wipes", counterspell "Counterspells",
tutor "Tutors", finisher "Finishers"; any other role: underscores to spaces.

For each row in `roles.rows`: a line with the label on the left and `"{cards} / {card_target}"`
on the right. Below it a bar track (height 8, background `#292524`, radius 4, position
relative). Scale: `max = Math.max(...rows.map(r => Math.max(r.cards, r.card_target)), 1)`.
A filled bar of width `cards/max*100 %`, colour `#22c55e` when `short_by === 0` else
`#f59e0b`. A target tick: absolutely positioned 2px-wide `#f5f5f4` line at
`left: card_target/max*100 %`, full height + 4px (top -2). When
`row.role === roles.most_under_supplied`, show a small `#ef4444` tag "biggest gap" next to
the label. Under the list, for each `not_applicable` entry a muted line
"{label}: {cards} — not a gap for this deck" with `title={note}` as a tooltip.
Footnote (11px muted): "Tick = what a typical deck at this power runs. A card can fill
several roles."

### 2. Interaction — "What your removal can answer"

For each type of `['creature','artifact','enchantment','planeswalker','land','spell']` that
is present in `counts_by_type` AND not a key of `not_applicable_types`: label (capitalised
type) and `"{answers}"` on the right. A bar track like above, scale
`max = Math.max(...answers counts, 1)`: a solid `#ca8a04` bar for `unrestricted/max`, and
directly after it a lighter `#ca8a0455` bar for `(answers - unrestricted)/max` (restricted
answers, e.g. "with flying only"). Bar track `title` = the names in
`answers_by_type[type]` joined with ", ". When `answers === 0` render the count text in
`#ef4444` and append " — no answer". Footer line (11px muted):
`"{exile_count} exile · {instant_speed_count} instant-speed · solid = no targeting restriction"`.

### 3. Mana — "Colour sources"

Colour swatches: W `#f8f6d8`, U `#0e68ab`, B `#4b3f48`, R `#d3202a`, G `#00733e`,
C `#a8a29e`. For each entry of `manabase.sources` a row: swatch circle (12px), letter,
bar (scale = max source count) in the swatch colour, count on the right.
Then for each `worst_colors` entry, a 12px line:
`"{color}: {have} of {need} sources to cast {example} on turn {turn} ({Math.round(probability*100)}%)"`
coloured `#f59e0b` when `have < need` else `#a8a29e`. Then
`"Curve: avg MV {average_mana_value} · {nonland_count} spells · {land_count} lands"` muted.

Render each section only when its data exists. Never throw on a missing key — use `|| {}`
and `|| []` defensively.
