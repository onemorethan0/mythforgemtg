// Search and sort for the History page. Pure: each takes the entries /api/decks returns.

export const SORT_MODES = [
  { key: 'recent',  label: 'Recent' },
  { key: 'name',    label: 'Name' },
  { key: 'bracket', label: 'Bracket' },
]

const nameOf = e => (e.themed_name || e.commander_name || '').toLowerCase()
const bracketOf = e => e.measured_bracket ?? e.bracket ?? 0
const ageOf = e => e.built_at || 0

/** True when every word of `query` appears somewhere in the deck's searchable text (its names, theme
 *  and bracket words). An empty query matches everything. */
export function matchesQuery(entry, query) {
  const terms = String(query || '').toLowerCase().split(/\s+/).filter(Boolean)
  if (!terms.length) return true
  const b = bracketOf(entry)
  const hay = [
    entry.themed_name, entry.commander_name, entry.theme, entry.bracket_label, entry.measured_label,
    b ? `bracket ${b} b${b}` : '',
  ].filter(Boolean).join(' ').toLowerCase()
  return terms.every(t => hay.includes(t))
}

/** A sorted copy. recent = newest first; name = A to Z; bracket = highest first, newest within a bracket. */
export function sortEntries(entries, mode) {
  const out = [...entries]
  if (mode === 'name') return out.sort((a, b) => nameOf(a).localeCompare(nameOf(b)) || ageOf(b) - ageOf(a))
  if (mode === 'bracket') return out.sort((a, b) => bracketOf(b) - bracketOf(a) || ageOf(b) - ageOf(a))
  return out.sort((a, b) => ageOf(b) - ageOf(a))
}

/** The ids "Select All" may take: finished decks that match the search. With a search active this
 *  is only what the search shows, so a bulk delete or export can never reach a deck you cannot see. */
export function selectableIds(decks, query) {
  return decks.filter(d => d.status !== 'building' && matchesQuery(d, query)).map(d => d.job_id)
}
