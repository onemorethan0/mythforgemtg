// Pure helpers for the printing picker. Printings come from GET /api/collection/printings:
//   { id, set, set_name, cn, released_at, rarity, finishes[], prices:{nonfoil,foil,etched},
//     treatments[], image, art_crop, owned:[{row_id, finish, count}] }
// When the offline store is missing the live fallback omits released_at / finishes / prices
// and only carries the legacy `usd` (the nonfoil price), so every helper tolerates that.

export const FINISH_ORDER = ['nonfoil', 'foil', 'etched']

// The finishes to offer a button for. An empty or missing list means "unknown", and an
// unknown print is only ever offered as nonfoil — never guess that it exists in foil.
export function availableFinishes(p) {
  const fin = Array.isArray(p && p.finishes) ? p.finishes : []
  const known = FINISH_ORDER.filter(f => fin.includes(f))
  return known.length ? known : ['nonfoil']
}

// This finish's own price, or null. A finish with no price shows "—"; another finish's
// price is never borrowed. The legacy `usd` is the nonfoil price and is used only for
// nonfoil, and only when no per-finish price block exists at all.
export function priceFor(p, finish) {
  if (!p) return null
  const prices = p.prices
  if (prices && typeof prices === 'object') {
    const v = prices[finish]
    return typeof v === 'number' ? v : null
  }
  if (finish === 'nonfoil' && typeof p.usd === 'number') return p.usd
  return null
}

// The cheapest price across the print's offered finishes (null when none is priced).
export function cheapestPrice(p) {
  const vals = availableFinishes(p).map(f => priceFor(p, f)).filter(v => v != null)
  return vals.length ? Math.min(...vals) : null
}

export function ownedTotal(p) {
  return ((p && p.owned) || []).reduce((n, o) => n + (Number(o.count) || 0), 0)
}

export function releaseYear(p) {
  const m = /^(\d{4})/.exec((p && p.released_at) || '')
  return m ? m[1] : ''
}

// True when `p` is the printing the row currently is (set + collector number).
export function isCurrentPrint(p, row) {
  if (!row || !row.set) return false
  return String(p.set || '').toLowerCase() === String(row.set).toLowerCase() &&
         String(p.cn || '') === String(row.cn || '')
}

// Text filter on set code or set name; owned-only keeps prints with at least one copy.
export function filterPrintings(list, text, ownedOnly) {
  const t = String(text || '').trim().toLowerCase()
  return (list || []).filter(p => {
    if (ownedOnly && ownedTotal(p) <= 0) return false
    if (!t) return true
    return String(p.set || '').toLowerCase().includes(t) ||
           String(p.set_name || '').toLowerCase().includes(t)
  })
}

// 'newest' | 'oldest' | 'cheapest'. Stable. Prints with no date / no price sort LAST in
// every direction — unknown is not "oldest" and not "cheapest".
export function sortPrintings(list, key) {
  const arr = [...(list || [])]
  const withIdx = arr.map((p, i) => [p, i])
  const cmpNum = (a, b, dir) => {
    if (a == null && b == null) return 0
    if (a == null) return 1
    if (b == null) return -1
    return dir * (a - b)
  }
  const date = p => (p.released_at ? Date.parse(p.released_at) || null : null)
  withIdx.sort(([a, i], [b, j]) => {
    const r = key === 'cheapest' ? cmpNum(cheapestPrice(a), cheapestPrice(b), 1)
      : cmpNum(date(a), date(b), key === 'oldest' ? 1 : -1)
    return r || i - j
  })
  return withIdx.map(([p]) => p)
}
