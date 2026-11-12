// Hash routes: #/ (home), #/history, #/collection, #/deck/<id>. Pure parse/format; App.jsx keeps
// the hash and its step state in sync. A deck id is a server job id (16 lowercase hex characters,
// the same shape the API's own id check enforces); anything else is not a route and reads as home,
// so a mistyped or hand-edited link lands on the landing hub instead of a blank screen.
const DECK_ID = /^[0-9a-f]{16}$/
const DECK_ROUTE = /^#\/deck\/([^/]*)$/

export function parseHash(hash) {
  const h = typeof hash === 'string' ? hash : ''
  if (h === '' || h === '#' || h === '#/') return { name: 'home', id: null }
  if (h === '#/history') return { name: 'history', id: null }
  if (h === '#/collection') return { name: 'collection', id: null }
  const m = DECK_ROUTE.exec(h)
  if (m && DECK_ID.test(m[1])) return { name: 'deck', id: m[1] }
  return { name: 'home', id: null }
}

export function formatRoute(name, id) {
  if (name === 'deck') {
    if (!DECK_ID.test(id || '')) throw new Error(`formatRoute: a deck route needs a valid id, got ${id}`)
    return `#/deck/${id}`
  }
  if (name === 'history') return '#/history'
  if (name === 'collection') return '#/collection'
  return '#/'
}
