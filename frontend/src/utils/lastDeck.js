// "Continue where you left off": the deck last open on the deck page, remembered per browser so the
// Home screen can offer it in one click. Kept in localStorage (a convenience, never state that matters),
// and every function tolerates storage being unavailable or holding junk.
const KEY = 'mtg_last_deck'
const DECK_ID = /^[0-9a-f]{16}$/

export function rememberLastDeck(storage, id, name, now = Date.now()) {
  if (!DECK_ID.test(id || '') || !name) return
  try { storage.setItem(KEY, JSON.stringify({ id, name: String(name), at: now })) } catch { /* not persisted */ }
}

/** { id, name, at } or null: never a malformed id, so it is always safe to build a route from. */
export function readLastDeck(storage) {
  try {
    const v = JSON.parse(storage.getItem(KEY))
    if (v && DECK_ID.test(v.id || '') && typeof v.name === 'string' && v.name) {
      return { id: v.id, name: v.name, at: Number(v.at) || 0 }
    }
  } catch { /* unreadable: no last deck */ }
  return null
}

export function forgetLastDeck(storage) {
  try { storage.removeItem(KEY) } catch { /* nothing to forget */ }
}

/** 90_000 -> "a minute ago", 2 hours -> "2 hours ago", 2 days -> "2 days ago". */
export function timeAgo(at, now = Date.now()) {
  const s = Math.max(0, Math.floor((now - at) / 1000))
  if (!at || s < 45) return 'just now'
  const m = Math.round(s / 60)
  if (m < 60) return m <= 1 ? 'a minute ago' : `${m} minutes ago`
  const h = Math.round(m / 60)
  if (h < 24) return h === 1 ? 'an hour ago' : `${h} hours ago`
  const d = Math.round(h / 24)
  if (d < 14) return d === 1 ? 'yesterday' : `${d} days ago`
  return `${Math.round(d / 7)} weeks ago`
}
