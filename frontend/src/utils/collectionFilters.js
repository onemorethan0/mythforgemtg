// Collection filter state and its query-string form. Pure, so it is unit-tested; the panel in
// StepCollection.jsx only renders it. List filters go on the query as comma-separated values,
// nulls and false are omitted.

export const LIST_FILTERS = ['colors', 'color_presence', 'types', 'rarities', 'sets',
                             'finishes', 'treatments', 'languages']

export const EMPTY_FILTERS = {
  colors: [], color_presence: [], types: [], rarities: [], sets: [],
  finishes: [], treatments: [], languages: [],
  cmc_min: null, cmc_max: null, min_count: null,
  game_changers_only: false, multi_printing: false,
}

// Tolerates a partial object (old state, stats shortcuts) by treating a missing list as empty.
export function hasFilters(f) {
  const x = f || {}
  return LIST_FILTERS.some(k => (x[k] || []).length > 0) ||
    x.cmc_min != null || x.cmc_max != null || x.min_count != null ||
    !!x.game_changers_only || !!x.multi_printing
}

export function filterQuery(f) {
  const x = f || {}
  const p = new URLSearchParams()
  for (const k of LIST_FILTERS) if ((x[k] || []).length) p.set(k, x[k].join(','))
  for (const k of ['cmc_min', 'cmc_max', 'min_count']) if (x[k] != null) p.set(k, String(x[k]))
  if (x.game_changers_only) p.set('game_changers_only', 'true')
  if (x.multi_printing) p.set('multi_printing', 'true')
  return p
}
