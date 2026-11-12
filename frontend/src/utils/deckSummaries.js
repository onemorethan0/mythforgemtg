// One-line summaries for the collapsed sections of the Analyze tab. Pure: each takes the data the
// page already holds and returns a short string, or null when there is nothing honest to say yet.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function shortDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '')
  return m ? `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}` : null
}

/** From a /measure result (`power_profile`): "Bracket 2 (Core)". */
export function bracketSummary(simulation) {
  const p = simulation?.power_profile
  if (!p || p.bracket_estimate == null) return null
  return `Bracket ${p.bracket_estimate}${p.bracket_label ? ` (${p.bracket_label})` : ''}`
}

/** From the saved `last_measure` ({ simulation, date }): "Bracket 2 (Core) · measured Nov 9". */
export function measureSummary(lastMeasure) {
  const b = bracketSummary(lastMeasure?.simulation)
  if (!b) return null
  const d = shortDate(lastMeasure?.date)
  return d ? `${b} · measured ${d}` : b
}

/** From the /breakdown data: which core roles the deck is under its typical card count in. */
export function breakdownSummary(breakdown) {
  const under = breakdown?.roles?.under_target
  if (!Array.isArray(under)) return 'not measured yet'
  if (!under.length) return 'every core role at its typical count'
  const names = under.map(r => String(r).replace(/_/g, ' '))
  const shown = names.slice(0, 3).join(', ')
  return `${under.length} role${under.length === 1 ? '' : 's'} under target: ${shown}${names.length > 3 ? '…' : ''}`
}

/** From deck.stats: "Avg MV 3.5 · 37 lands". */
export function statsSummary(stats) {
  if (!stats) return null
  const avg = stats.average_cmc ?? stats.avg_cmc
  const lands = stats.type_counts?.Land
  const bits = []
  if (typeof avg === 'number') bits.push(`Avg MV ${avg.toFixed(1)}`)
  if (typeof lands === 'number') bits.push(`${lands} land${lands === 1 ? '' : 's'}`)
  return bits.length ? bits.join(' · ') : null
}
