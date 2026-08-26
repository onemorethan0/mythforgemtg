import { useEffect, useState, useCallback, useRef } from 'react'
import CardHover from './CardHover'
import CollectionStats from './CollectionStats'
import CollectionGrid from './CollectionGrid'

// Collection manager: browse / add / edit-count / remove the cards the user owns.
// All edits POST to /api/collection/* which writes the canonical MythSuite/collection.csv
// (the same file MythScanner produces and the deck builder reads for owned-aware building).

const c = {
  gold:   '#eab308',
  dim:    '#a8a29e',
  faint:  '#78716c',
  card:   '#1c1917',
  border: '#292524',
  panel:  '#0c0a09',
}

const PAGE = 500   // rows fetched by default; "Show all" refetches with limit=0

const MANA = { W: '#f8f0d8', U: '#4a90d9', B: '#5b5254', R: '#d94a4a', G: '#4aa563',
               Multicolor: '#c9a227', Colorless: '#8a8a8a' }

const SORTS = [
  ['name', 'Name'], ['value', 'Value'], ['price', 'Price'], ['count', 'Copies'],
  ['cmc', 'Mana value'], ['type', 'Type'], ['set', 'Set'], ['edhrec', 'Popularity'],
]

const EMPTY_FILTERS = { colors: [], color_presence: [], types: [], rarities: [], sets: [],
                        cmc_min: null, cmc_max: null, min_count: null, game_changers_only: false }

const hasFilters = f =>
  f.colors.length || f.color_presence.length || f.types.length || f.rarities.length ||
  f.sets.length || f.cmc_min != null || f.cmc_max != null || f.min_count != null ||
  f.game_changers_only

// Filters go on the query string as comma-separated lists; nulls are simply omitted.
function filterQuery(f) {
  const p = new URLSearchParams()
  for (const k of ['colors', 'color_presence', 'types', 'rarities', 'sets'])
    if (f[k].length) p.set(k, f[k].join(','))
  for (const k of ['cmc_min', 'cmc_max', 'min_count']) if (f[k] != null) p.set(k, String(f[k]))
  if (f.game_changers_only) p.set('game_changers_only', 'true')
  return p
}

// Toggle one value inside a multi-select facet.
const toggle = (list, v) => (list.includes(v) ? list.filter(x => x !== v) : [...list, v])

// Must match CollectionGrid's — a card owned in two sets is two rows.
const rowKey = r => `${r.name}|${r.set || ''}|${r.cn || ''}`

export default function StepCollection({ onBack, onBuild }) {
  const [cards, setCards]       = useState([])
  const [summary, setSummary]   = useState({ distinct: 0, total_cards: 0, path: '', exists: false, total_value: 0, priced: 0, prices_updated: null })
  const [matched, setMatched]   = useState(0)
  const [showingAll, setShowingAll] = useState(false)
  const [q, setQ]               = useState('')
  const [loading, setLoading]   = useState(true)
  const [msg, setMsg]           = useState(null)         // {kind:'ok'|'err', text}
  const [addName, setAddName]   = useState('')
  const [addCount, setAddCount] = useState(1)
  const [busy, setBusy]         = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [importText, setImportText] = useState('')
  const [importMode, setImportMode] = useState('merge')
  const [suggests, setSuggests]     = useState([])   // typeahead names for the add box
  const [showSug, setShowSug]       = useState(false)
  const [buildable, setBuildable]   = useState(null)  // {commanders, scanned, candidates}
  const [bLoading, setBLoading]     = useState(false)
  const [showBuild, setShowBuild]   = useState(false)
  const [facets, setFacets]         = useState(null)   // available filter values + counts
  const [filters, setFilters]       = useState(EMPTY_FILTERS)
  const [sort, setSort]             = useState('name')
  const [direction, setDirection]   = useState('asc')
  const [showFilters, setShowFilters] = useState(false)
  const [stats, setStats]           = useState(null)
  const [showStats, setShowStats]   = useState(false)
  const [health, setHealth]         = useState(null)   // {affected, issues, copies_*}
  const [showHealth, setShowHealth] = useState(false)
  // View preference sticks — someone who browses their binder visually wants it every time.
  const [view, setView]             = useState(() => localStorage.getItem('mtg_coll_view') || 'list')
  const [selectMode, setSelectMode] = useState(false)
  const [selected, setSelected]     = useState(() => new Set())
  const [printingFor, setPrintingFor] = useState(null) // row whose printing is being chosen
  const [printings, setPrintings]   = useState([])
  const [pLoading, setPLoading]     = useState(false)
  const debounce = useRef(null)
  const sugDebounce = useRef(null)
  const searchRef = useRef(null)
  const addRef = useRef(null)

  useEffect(() => { localStorage.setItem('mtg_coll_view', view) }, [view])

  // "/" jumps to search from anywhere on the page — the fastest way into a 1000-card list.
  // Ignored while typing in a field, so it never eats a literal slash.
  useEffect(() => {
    const onKey = e => {
      const tag = (e.target.tagName || '').toLowerCase()
      if (tag === 'input' || tag === 'textarea' || tag === 'select') {
        if (e.key === 'Escape') e.target.blur()
        return
      }
      if (e.key === '/') { e.preventDefault(); searchRef.current && searchRef.current.focus() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Declared before the callbacks that close over it. `loadBuildable` used to sit
  // above this line and reference it, which is legal only by accident — useCallback
  // defers the body, so the read lands after initialisation — but it left the memo
  // holding the first render's `flash` forever and tripped react-hooks/immutability.
  const flash = (kind, text) => { setMsg({ kind, text }); if (text) setTimeout(() => setMsg(null), 4000) }

  const loadBuildable = useCallback(() => {
    setBLoading(true)
    fetch('/api/collection/buildable?limit=8')
      .then(r => r.json())
      .then(d => setBuildable(d))
      .catch(() => flash('err', 'Could not scan your collection.'))
      .finally(() => setBLoading(false))
  }, [])

  // Page size for the list. The server also accepts limit<=0 ("all matches", capped at
  // 5000) which is what "Show all" sends. Without the notice below, a collection larger
  // than PAGE lost the overflow SILENTLY — a 986-card collection rendered 500 rows with
  // nothing on screen saying the other 486 existed, and no offset control to reach them.
  const load = useCallback((query = '', all = false) => {
    setLoading(true)
    setShowingAll(all)
    const p = filterQuery(filters)
    p.set('limit', all ? '0' : String(PAGE))
    p.set('q', query)
    p.set('sort', sort)
    p.set('direction', direction)
    fetch(`/api/collection?${p}`)
      .then(r => r.json())
      .then(d => {
        setCards(d.cards || [])
        setMatched(d.matched || 0)
        setFacets(d.facets || null)
        setSummary({ distinct: d.distinct, total_cards: d.total_cards, path: d.path, exists: d.exists,
                     total_value: d.total_value, priced: d.priced, prices_updated: d.prices_updated })
      })
      .catch(() => flash('err', 'Could not load collection — is the server running?'))
      .finally(() => setLoading(false))
  }, [filters, sort, direction])

  const loadStats = useCallback(() => {
    fetch('/api/collection/stats')
      .then(r => r.json()).then(setStats)
      .catch(() => flash('err', 'Could not compute collection stats.'))
  }, [])

  // Read-only scan for rows whose NAME is a whole decklist line. Cheap, so it runs on
  // mount: a collection can be a quarter invisible to deck building without the user
  // ever being told, which is the whole reason this banner exists.
  const loadHealth = useCallback(() => {
    fetch('/api/collection/health')
      .then(r => r.json()).then(setHealth)
      .catch(() => {})
  }, [])

  useEffect(() => { loadHealth() }, [loadHealth])
  useEffect(() => { if (showStats) loadStats() }, [showStats, loadStats])

  // Debounced search
  useEffect(() => {
    if (debounce.current) clearTimeout(debounce.current)
    debounce.current = setTimeout(() => load(q.trim()), 250)
    return () => debounce.current && clearTimeout(debounce.current)
  }, [q, load])

  // Typeahead: fetch Scryfall autocomplete for the add box (debounced).
  useEffect(() => {
    if (sugDebounce.current) clearTimeout(sugDebounce.current)
    const term = addName.trim()
    if (term.length < 2) { setSuggests([]); return }
    sugDebounce.current = setTimeout(() => {
      fetch(`/api/collection/suggest?q=${encodeURIComponent(term)}`)
        .then(r => r.json())
        .then(d => setSuggests(d.suggestions || []))
        .catch(() => setSuggests([]))
    }, 200)
    return () => sugDebounce.current && clearTimeout(sugDebounce.current)
  }, [addName])

  const apply = (promise, okMsg) => {
    setBusy(true)
    promise
      .then(async r => {
        const d = await r.json().catch(() => ({}))
        if (!r.ok) throw new Error(d.detail || 'Request failed')
        setSummary({ distinct: d.distinct, total_cards: d.total_cards, path: d.path, exists: d.exists,
                     total_value: d.total_value, priced: d.priced, prices_updated: d.prices_updated })
        if (okMsg) flash('ok', okMsg(d))
        // Preserve "Show all": an edit must not silently collapse the list back to one page.
        load(q.trim(), showingAll)
      })
      .catch(e => flash('err', String(e.message || e)))
      .finally(() => setBusy(false))
  }

  const addCard = () => {
    const name = addName.trim()
    if (!name) return
    apply(
      fetch('/api/collection/add', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, count: Number(addCount) || 1, validate: true }),
      }),
      d => `Added ${d.resolved_name || name}`,
    )
    setAddName(''); setAddCount(1)
    // Keep the caret in the box: adding cards is something you do in a run of ten, not once.
    addRef.current && addRef.current.focus()
  }

  // Rows are PER PRINTING now, so edits must name the set/collector number or they'd
  // hit the wrong copy of a card owned in several sets.
  const setCount = (row, count) =>
    apply(fetch('/api/collection/count', {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: row.name, count, set_code: row.set || null, cn: row.cn || null }),
    }), null)

  const refreshPrices = () => {
    setMsg({ kind: 'ok', text: 'Fetching current market prices…' })
    apply(fetch('/api/collection/prices', { method: 'POST' }),
      d => `Priced ${d.priced} of ${d.distinct} · collection value $${(d.total_value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`)
  }

  const backfillPrintings = () => {
    setMsg({ kind: 'ok', text: 'Looking up cheapest printings… this can take a minute.' })
    apply(fetch('/api/collection/backfill-printings', { method: 'POST' }),
      d => `Filled ${d.filled} printing${d.filled === 1 ? '' : 's'}${d.failed ? ` · ${d.failed} not found` : ''}`)
  }

  const removeCard = (row) => {
    // name is a query param, not a path segment — DFC/split names contain '//' and an
    // encoded slash in the path 405s under Starlette routing.
    const q = new URLSearchParams({ name: row.name })
    if (row.set) q.set('set_code', row.set)
    if (row.cn) q.set('cn', row.cn)
    return apply(fetch(`/api/collection?${q}`, { method: 'DELETE' }),
      () => `Removed ${row.name}${row.set ? ` (${row.set})` : ''}`)
  }

  const runImport = () => {
    const text = importText.trim()
    if (!text) return
    apply(fetch('/api/collection/import', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, mode: importMode }),
    }), d => `Imported (${importMode}) — ${d.distinct} cards now`)
    setImportText(''); setShowImport(false)
  }

  // Rewrites the canonical CSV, so it is never automatic — the banner explains what
  // will change and this only runs on an explicit click. A .bak is kept; Undo restores it.
  const runRepair = () => {
    apply(fetch('/api/collection/repair', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dry_run: false }),
    }), d => `Repaired ${d.repaired} row${d.repaired === 1 ? '' : 's'}` +
             `${d.merged ? `, merged ${d.merged}` : ''} · ` +
             `${d.copies_after - d.copies_before} copies recovered`)
    setShowHealth(false)
    setTimeout(() => { loadHealth(); if (showStats) loadStats() }, 400)
  }

  const runUndo = () => {
    apply(fetch('/api/collection/undo', { method: 'POST' }), () => 'Restored the previous version')
    setTimeout(() => { loadHealth(); if (showStats) loadStats() }, 400)
  }

  const applyFilter = crit => {
    setFilters(f => ({ ...EMPTY_FILTERS, ...f, ...crit }))
    setShowFilters(true)
  }

  // ── Bulk selection ──────────────────────────────────────────────────────────
  const toggleSelect = row => setSelected(s => {
    const next = new Set(s)
    const k = rowKey(row)
    next.has(k) ? next.delete(k) : next.add(k)
    return next
  })
  const selectedRows = () => cards.filter(r => selected.has(rowKey(r)))
  const clearSelection = () => setSelected(new Set())
  const exitSelect = () => { setSelectMode(false); clearSelection() }

  // One request, one CSV write, one .bak — see /api/collection/bulk. Doing this per row
  // would also overwrite the backup with an already-modified file and cost the user Undo.
  const bulkAction = (action, count = 0) => {
    const targets = selectedRows().map(r => ({ name: r.name, set: r.set || '', cn: r.cn || '' }))
    if (!targets.length) return
    apply(fetch('/api/collection/bulk', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, targets, count }),
    }), d => `${action === 'remove' ? 'Removed' : 'Updated'} ${d.affected} card${d.affected === 1 ? '' : 's'}`)
    exitSelect()
    setTimeout(loadHealth, 400)
  }

  const copySelection = () => {
    const text = selectedRows()
      .map(r => `${r.count} ${r.name}${r.set ? ` (${r.set})${r.cn ? ` ${r.cn}` : ''}` : ''}`)
      .join('\n')
    if (!text) return
    navigator.clipboard.writeText(text)
      .then(() => flash('ok', `Copied ${selected.size} card${selected.size === 1 ? '' : 's'} as a decklist`))
      .catch(() => flash('err', 'Could not copy to the clipboard.'))
  }

  // ── Printing picker ─────────────────────────────────────────────────────────
  // The endpoint already existed and nothing ever called it; 794 rows don't record which
  // printing is owned, and re-adding the card to fix that would lose the count.
  const openPrintings = row => {
    setPrintingFor(row); setPrintings([]); setPLoading(true)
    fetch(`/api/collection/printings?name=${encodeURIComponent(row.name)}`)
      .then(r => r.json())
      .then(d => setPrintings(d.printings || []))
      .catch(() => flash('err', 'Could not load printings.'))
      .finally(() => setPLoading(false))
  }

  const choosePrinting = p => {
    const row = printingFor
    setPrintingFor(null)
    apply(fetch('/api/collection/printing', {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: row.name, set_code: p.set, cn: p.collector_number,
                             from_set: row.set || null, from_cn: row.cn || null }),
    }), () => `${row.name} → ${p.set} ${p.collector_number}`)
  }

  const btn = (extra = {}) => ({
    padding: '8px 14px', borderRadius: 8, cursor: busy ? 'wait' : 'pointer',
    background: c.card, border: `1px solid ${c.border}`, color: c.dim,
    fontFamily: 'inherit', fontSize: 13, ...extra,
  })

  return (
    <div style={{ maxWidth: 860, width: '100%', marginTop: 28 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
        <button onClick={onBack} style={btn()}>← Home</button>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: c.gold, margin: 0 }}>🎴 My Collection</h1>
      </div>
      {/* Value summary — total = price x count across the WHOLE collection */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', margin: '2px 0 6px' }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: '#4ade80' }}>
          ${(summary.total_value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </span>
        <span style={{ fontSize: 11.5, color: c.faint }}>
          {summary.priced ? `${summary.priced}/${summary.distinct} priced` : 'not priced yet'}
          {summary.prices_updated ? ` · updated ${String(summary.prices_updated).replace('T', ' ')}` : ''}
        </span>
        <button onClick={refreshPrices} disabled={busy} style={btn({ padding: '4px 10px', fontSize: 12 })}
          title="Fetch current market prices (Scryfall USD) for every card, batched">
          💲 {summary.priced ? 'Refresh prices' : 'Get prices'}
        </button>
      </div>
      <p style={{ fontSize: 12.5, color: c.faint, margin: '0 0 4px' }}>
        {summary.total_cards} cards · {summary.distinct} unique.
        {' '}Edits save to <code style={{ color: c.dim }}>{summary.path}</code> — the shared Myth Suite file.
      </p>
      {!summary.exists && (
        <p style={{ fontSize: 12.5, color: '#f59e0b', margin: '0 0 8px' }}>
          No collection file yet — adding your first card creates it.
        </p>
      )}

      {/* Message */}
      {msg && (
        <div style={{
          margin: '8px 0', padding: '8px 12px', borderRadius: 8, fontSize: 13,
          background: msg.kind === 'ok' ? '#0f1e12' : '#1e1010',
          border: `1px solid ${msg.kind === 'ok' ? '#22c55e' : '#ef4444'}`,
          color: msg.kind === 'ok' ? '#4ade80' : '#f87171',
        }}>{msg.text}</div>
      )}

      {/* Collection health. These rows hold a whole decklist line where a card name
          should be, so nothing downstream can match them — the user is silently
          building decks from a fraction of what they own. Proposals only until clicked. */}
      {health && health.affected > 0 && (
        <div style={{ margin: '10px 0', padding: 12, borderRadius: 10,
                      background: '#1c1608', border: '1px solid #a16207' }}>
          <div style={{ fontSize: 13.5, color: '#fbbf24', fontWeight: 700, marginBottom: 4 }}>
            ⚠ {health.affected} of {health.rows} rows aren’t stored as card names
          </div>
          <div style={{ fontSize: 12.5, color: c.dim, marginBottom: 8 }}>
            They were imported as whole decklist lines (<code>1x Sol Ring (ltc) 273 [Ramp]</code>),
            so nothing matches them — deck building, “Build from what I own” and upgrade
            advice all skip these cards today. Repairing also recovers{' '}
            <strong style={{ color: '#fbbf24' }}>
              {health.copies_after - health.copies_before} copies
            </strong>{' '}
            whose quantity was lost, and fills in the printing each line named.
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button onClick={runRepair} disabled={busy}
              style={btn({ background: '#3f2d06', border: '1px solid #eab308',
                           color: '#fde047', fontWeight: 700 })}>
              ✓ Repair all {health.affected}
            </button>
            <button onClick={() => setShowHealth(v => !v)} style={btn()}>
              {showHealth ? 'Hide' : 'Review'} changes
            </button>
          </div>
          {showHealth && (
            <div style={{ marginTop: 10, maxHeight: 280, overflowY: 'auto',
                          border: `1px solid ${c.border}`, borderRadius: 8 }}>
              {(health.issues || []).map(iss => (
                <div key={iss.index} style={{ padding: '6px 10px', fontSize: 11.5,
                                              borderBottom: `1px solid ${c.border}` }}>
                  <div style={{ color: c.faint, fontFamily: 'monospace' }}>{iss.current.name}</div>
                  <div style={{ color: '#4ade80', fontFamily: 'monospace' }}>
                    → {iss.proposed.name} · x{iss.proposed.count}
                    {iss.proposed.set ? ` · ${iss.proposed.set} ${iss.proposed.cn}` : ''}
                    {iss.foil ? ' · foil' : ''}
                    {iss.count_conflict && (
                      <span style={{ color: '#fbbf24' }}> (stored count was {iss.current.count})</span>
                    )}
                  </div>
                </div>
              ))}
              {health.truncated && (
                <div style={{ padding: '6px 10px', fontSize: 11.5, color: c.faint }}>
                  … and {health.affected - health.shown} more.
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Insights */}
      <div style={{ margin: '12px 0' }}>
        <button onClick={() => setShowStats(v => !v)}
          style={btn({ width: '100%', textAlign: 'left', fontWeight: 700 })}>
          📊 Collection insights {showStats ? '▲' : '▼'}
        </button>
        {showStats && (
          <div style={{ marginTop: 10 }}>
            {stats ? <CollectionStats stats={stats} onFilter={applyFilter} />
                   : <div style={{ color: c.faint, fontSize: 13, padding: 16, textAlign: 'center' }}>
                       Crunching your collection…
                     </div>}
          </div>
        )}
      </div>

      {/* Buildable-from-collection */}
      <div style={{ margin: '12px 0' }}>
        <button
          onClick={() => { const n = !showBuild; setShowBuild(n); if (n && !buildable) loadBuildable() }}
          style={btn({ background: '#12100a', border: `1px solid ${c.gold}`, color: c.gold, fontWeight: 700, width: '100%', textAlign: 'left' })}>
          🔨 Build from what I own {showBuild ? '▲' : '▼'}
        </button>
        {showBuild && (
          <div style={{ marginTop: 10 }}>
            {bLoading ? (
              <div style={{ color: c.faint, fontSize: 13, padding: 16, textAlign: 'center' }}>
                Scanning your collection…
              </div>
            ) : !buildable || !buildable.commanders?.length ? (
              <div style={{ color: c.faint, fontSize: 13, padding: 16, textAlign: 'center' }}>
                No buildable commanders found yet — add more owned cards.
              </div>
            ) : (
              <>
                <div style={{ fontSize: 12, color: c.faint, marginBottom: 8 }}>
                  {buildable.candidates} legendary creatures in your collection · showing the most complete decks you could build.
                  Bracket is gauged after you build (measure on the result screen).
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 10 }}>
                  {buildable.commanders.map(cm => (
                    <div key={cm.commander} style={{ border: `1px solid ${c.border}`, borderRadius: 10, padding: 12, background: c.card, display: 'flex', gap: 10 }}>
                      {/* `image` has been computed by buildable.score_commander all along
                          (a small Scryfall art crop) but this card was text-only — a grid
                          of "decks you could build" reads far better with actual portraits. */}
                      {cm.image && (
                        <img src={cm.image} alt="" loading="lazy"
                          style={{ width: 56, height: 56, objectFit: 'cover', borderRadius: 8,
                                   border: `1px solid ${c.border}`, flexShrink: 0 }} />
                      )}
                      <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                        <CardHover name={cm.commander} style={{ flex: 1, fontSize: 14, fontWeight: 700, color: '#f5f5f4', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }}>
                          {cm.commander}
                        </CardHover>
                        <span style={{ fontSize: 11, fontWeight: 700, color: c.gold, whiteSpace: 'nowrap' }}>{cm.ci}</span>
                      </div>
                      <div style={{ height: 6, background: '#000', borderRadius: 4, overflow: 'hidden', marginBottom: 6 }}>
                        <div style={{ width: `${cm.buildable_pct}%`, height: '100%', background: cm.buildable_pct >= 100 ? '#22c55e' : '#eab308' }} />
                      </div>
                      <div style={{ fontSize: 11.5, color: c.dim, marginBottom: cm.gaps.length ? 4 : 8 }}>
                        {cm.buildable_pct}% buildable · {cm.owned_nonland} owned on-color cards
                      </div>
                      {cm.gaps.length > 0 && (
                        <div style={{ fontSize: 11, color: '#f59e0b', marginBottom: 8 }}>
                          thin on: {cm.gaps.join(', ')}
                        </div>
                      )}
                      <button
                        onClick={() => onBuild && onBuild(cm.commander)}
                        style={btn({ width: '100%', background: '#1c1410', border: `1px solid ${c.gold}`, color: c.gold, fontWeight: 700 })}>
                        Build this →
                      </button>
                      {/* The separate strict action. "Build this" prefers your cards but
                          still lets Scryfall staples fill a slot the collection can't
                          cover; this one never leaves the collection, so the deck is
                          sleeve-able tonight. Roles it can't fill are reported after. */}
                      <button
                        onClick={() => onBuild && onBuild(cm.commander, true)}
                        title="Use only cards you own. No Scryfall staples will be added to fill gaps."
                        style={btn({ width: '100%', marginTop: 6, background: 'transparent',
                                     border: '1px solid #3f3f46', color: '#a1a1aa', fontWeight: 600, fontSize: 12 })}>
                        🎴 Only cards I own
                      </button>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Add card */}
      <div style={{ display: 'flex', gap: 8, margin: '14px 0', flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 320px', position: 'relative' }}>
          <input
            ref={addRef}
            value={addName}
            onChange={e => { setAddName(e.target.value); setShowSug(true) }}
            onKeyDown={e => { if (e.key === 'Enter') { setShowSug(false); addCard() } if (e.key === 'Escape') setShowSug(false) }}
            onFocus={() => setShowSug(true)}
            onBlur={() => setTimeout(() => setShowSug(false), 150)}
            placeholder="Add a card by name (e.g. Sol Ring)"
            style={{ width: '100%', boxSizing: 'border-box', padding: '9px 12px', borderRadius: 8, background: c.panel,
                     border: `1px solid ${c.border}`, color: '#f5f5f4', fontFamily: 'inherit', fontSize: 14 }}
          />
          {showSug && suggests.length > 0 && (
            <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 20, marginTop: 4,
                          background: c.card, border: `1px solid ${c.border}`, borderRadius: 8,
                          maxHeight: 240, overflowY: 'auto', boxShadow: '0 6px 20px rgba(0,0,0,0.5)' }}>
              {suggests.map(s => (
                <div key={s}
                  onMouseDown={e => { e.preventDefault(); setAddName(s); setShowSug(false) }}
                  style={{ padding: '7px 12px', fontSize: 13.5, color: '#f5f5f4', cursor: 'pointer' }}
                  onMouseEnter={e => e.currentTarget.style.background = '#2a2420'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                  {s}
                </div>
              ))}
            </div>
          )}
        </div>
        <input
          type="number" min="1" value={addCount} onChange={e => setAddCount(e.target.value)}
          style={{ width: 68, padding: '9px 10px', borderRadius: 8, background: c.panel,
                   border: `1px solid ${c.border}`, color: '#f5f5f4', fontFamily: 'inherit', fontSize: 14 }}
        />
        <button onClick={addCard} disabled={busy || !addName.trim()}
          style={btn({ background: '#1c1410', border: `1px solid ${c.gold}`, color: c.gold, fontWeight: 700 })}>
          + Add
        </button>
        <button onClick={() => setShowImport(v => !v)} style={btn()}>⇪ Bulk import</button>
        <button onClick={backfillPrintings} disabled={busy} style={btn()}
          title="Fill in the cheapest printing for any card whose set is unknown (one Scryfall lookup per card — slow on a big collection)">
          🖨 Fill printings
        </button>
        <button onClick={runUndo} disabled={busy} style={btn()}
          title="Restore the collection as it was before the last change (every write keeps one backup)">
          ↶ Undo
        </button>
      </div>

      {/* Bulk import */}
      {showImport && (
        <div style={{ margin: '0 0 14px', padding: 14, borderRadius: 10, background: c.panel, border: `1px solid ${c.border}` }}>
          <div style={{ fontSize: 12.5, color: c.dim, marginBottom: 8 }}>
            Paste a Moxfield CSV (<code>Count,Name,Edition,Collector Number</code>) or a decklist
            (<code>1 Sol Ring (C21) 263</code>). Set info is kept, so the same card in different
            sets stays separate; entries without a set default to the cheapest printing.
          </div>
          <textarea
            value={importText} onChange={e => setImportText(e.target.value)}
            rows={7} placeholder={'Count,Name,Edition,Collector Number\n1,Sol Ring,C21,263\n2,Llanowar Elves,,'}
            style={{ width: '100%', boxSizing: 'border-box', padding: 10, borderRadius: 8, background: '#000',
                     border: `1px solid ${c.border}`, color: '#f5f5f4', fontFamily: 'monospace', fontSize: 12.5 }}
          />
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 8 }}>
            <label style={{ fontSize: 12.5, color: c.dim }}>
              <input type="radio" checked={importMode === 'merge'} onChange={() => setImportMode('merge')} /> Merge (add)
            </label>
            <label style={{ fontSize: 12.5, color: c.dim }}>
              <input type="radio" checked={importMode === 'replace'} onChange={() => setImportMode('replace')} /> Replace all
            </label>
            <button onClick={runImport} disabled={busy || !importText.trim()}
              style={btn({ marginLeft: 'auto', background: '#1c1410', border: `1px solid ${c.gold}`, color: c.gold, fontWeight: 700 })}>
              Import
            </button>
          </div>
          {importMode === 'replace' && (
            <div style={{ fontSize: 11.5, color: '#f59e0b', marginTop: 6 }}>
              Replace overwrites the whole collection (a .bak is kept).
            </div>
          )}
        </div>
      )}

      {/* Search + sort + filter toggle */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
        <input
          ref={searchRef}
          value={q} onChange={e => setQ(e.target.value)}
          placeholder="Search your collection…   (press / )"
          style={{ flex: '1 1 240px', boxSizing: 'border-box', padding: '9px 12px', borderRadius: 8, background: c.panel,
                   border: `1px solid ${c.border}`, color: '#f5f5f4', fontFamily: 'inherit', fontSize: 14 }}
        />
        {/* List vs binder. Two buttons rather than a dropdown — it's a one-click switch. */}
        <div style={{ display: 'flex', borderRadius: 8, overflow: 'hidden', border: `1px solid ${c.border}` }}>
          {[['list', '☰', 'List'], ['grid', '▦', 'Binder']].map(([v, icon, label]) => (
            <button key={v} onClick={() => setView(v)} title={`${label} view`}
              style={{ padding: '8px 12px', border: 'none', cursor: 'pointer', fontFamily: 'inherit',
                       fontSize: 14, background: view === v ? '#1c1410' : c.card,
                       color: view === v ? c.gold : c.dim }}>
              {icon}
            </button>
          ))}
        </div>
        <select value={sort} onChange={e => setSort(e.target.value)}
          style={{ padding: '9px 10px', borderRadius: 8, background: c.panel,
                   border: `1px solid ${c.border}`, color: '#f5f5f4', fontFamily: 'inherit', fontSize: 13 }}>
          {SORTS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
        </select>
        <button onClick={() => setDirection(d => (d === 'asc' ? 'desc' : 'asc'))}
          title={direction === 'asc' ? 'Ascending' : 'Descending'} style={btn({ padding: '8px 12px' })}>
          {direction === 'asc' ? '↑' : '↓'}
        </button>
        <button onClick={() => setShowFilters(v => !v)}
          style={btn(hasFilters(filters)
            ? { background: '#1c1410', border: `1px solid ${c.gold}`, color: c.gold, fontWeight: 700 }
            : {})}>
          ⚗ Filters{hasFilters(filters) ? ' •' : ''}
        </button>
        <button onClick={() => (selectMode ? exitSelect() : setSelectMode(true))}
          title="Select several cards and act on them at once"
          style={btn(selectMode
            ? { background: '#1c1410', border: `1px solid ${c.gold}`, color: c.gold, fontWeight: 700 }
            : {})}>
          ☑ Select
        </button>
      </div>

      {/* Bulk action bar — only while selecting, and it always says how many. */}
      {selectMode && (
        <div style={{ margin: '0 0 10px', padding: '8px 12px', borderRadius: 8, background: '#12100a',
                      border: `1px solid ${c.gold}`, display: 'flex', gap: 8, alignItems: 'center',
                      flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, color: c.gold, fontWeight: 700 }}>
            {selected.size} selected
          </span>
          <button onClick={() => setSelected(new Set(cards.map(rowKey)))} style={btn({ padding: '4px 10px', fontSize: 12 })}>
            Select all {cards.length} shown
          </button>
          <button onClick={clearSelection} disabled={!selected.size} style={btn({ padding: '4px 10px', fontSize: 12 })}>
            Clear
          </button>
          <span style={{ flex: 1 }} />
          <button onClick={copySelection} disabled={!selected.size} style={btn({ padding: '4px 10px', fontSize: 12 })}
            title="Copy as a decklist you can paste into Moxfield or Archidekt">
            ⧉ Copy as list
          </button>
          <button onClick={() => bulkAction('set_count', 1)} disabled={busy || !selected.size}
            style={btn({ padding: '4px 10px', fontSize: 12 })} title="Set every selected card to a single copy">
            Set to 1
          </button>
          <button onClick={() => bulkAction('remove')} disabled={busy || !selected.size}
            style={btn({ padding: '4px 10px', fontSize: 12, color: '#f87171', border: '1px solid #3f1d1d' })}>
            ✕ Remove {selected.size || ''}
          </button>
        </div>
      )}

      {/* Facet panel — only values the collection actually contains are offered, so a
          filter can never produce an empty list by surprise. */}
      {showFilters && facets && (
        <div style={{ margin: '0 0 12px', padding: 12, borderRadius: 10, background: c.panel,
                      border: `1px solid ${c.border}`, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {[['colors', 'Color', facets.colors, MANA],
            ['types', 'Type', facets.types, null],
            ['rarities', 'Rarity', facets.rarities, null]].map(([key, label, list, palette]) => (
            (list || []).length > 0 && (
              <div key={key}>
                <div style={{ fontSize: 11, color: c.faint, marginBottom: 5 }}>{label}</div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {list.map(f => {
                    const on = filters[key].includes(f.key)
                    return (
                      <button key={f.key}
                        onClick={() => setFilters(v => ({ ...v, [key]: toggle(v[key], f.key) }))}
                        style={btn({ padding: '3px 9px', fontSize: 12,
                          background: on ? '#1c1410' : c.card,
                          border: `1px solid ${on ? c.gold : c.border}`,
                          color: on ? c.gold : c.dim, fontWeight: on ? 700 : 400 })}>
                        {palette && (
                          <span style={{ display: 'inline-block', width: 8, height: 8, marginRight: 5,
                                         borderRadius: '50%', background: palette[f.key] || c.faint }} />
                        )}
                        {f.key === '—' ? 'printing unknown' : f.key} <span style={{ opacity: 0.6 }}>{f.count}</span>
                      </button>
                    )
                  })}
                </div>
              </div>
            )
          ))}
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <label style={{ fontSize: 12, color: c.dim, display: 'flex', alignItems: 'center', gap: 6 }}>
              <input type="checkbox" checked={filters.min_count === 2}
                onChange={e => setFilters(v => ({ ...v, min_count: e.target.checked ? 2 : null }))} />
              Duplicates only (2+ copies)
            </label>
            <label style={{ fontSize: 12, color: c.dim, display: 'flex', alignItems: 'center', gap: 6 }}>
              <input type="checkbox" checked={filters.game_changers_only}
                onChange={e => setFilters(v => ({ ...v, game_changers_only: e.target.checked }))} />
              ⚡ Game Changers only
            </label>
            <label style={{ fontSize: 12, color: c.dim, display: 'flex', alignItems: 'center', gap: 6 }}>
              Mana value
              <input type="number" min="0" max={facets.cmc_max || 20} value={filters.cmc_min ?? ''}
                onChange={e => setFilters(v => ({ ...v, cmc_min: e.target.value === '' ? null : Number(e.target.value) }))}
                placeholder="min"
                style={{ width: 56, padding: '4px 6px', borderRadius: 6, background: '#000',
                         border: `1px solid ${c.border}`, color: '#f5f5f4', fontSize: 12 }} />
              –
              <input type="number" min="0" max={facets.cmc_max || 20} value={filters.cmc_max ?? ''}
                onChange={e => setFilters(v => ({ ...v, cmc_max: e.target.value === '' ? null : Number(e.target.value) }))}
                placeholder="max"
                style={{ width: 56, padding: '4px 6px', borderRadius: 6, background: '#000',
                         border: `1px solid ${c.border}`, color: '#f5f5f4', fontSize: 12 }} />
            </label>
            {hasFilters(filters) && (
              <button onClick={() => setFilters(EMPTY_FILTERS)}
                style={btn({ marginLeft: 'auto', padding: '4px 10px', fontSize: 12 })}>
                Clear filters
              </button>
            )}
          </div>
        </div>
      )}
      {(q || matched > cards.length) && (
        <div style={{ fontSize: 12, color: matched > cards.length ? '#fbbf24' : c.faint, marginBottom: 8 }}>
          {q && <>{matched} match{matched === 1 ? '' : 'es'}</>}
          {matched > cards.length && (
            <>
              {q ? ' — ' : ''}showing {cards.length} of {matched}
              <button
                onClick={() => load(q.trim(), true)}
                style={{ marginLeft: 8, background: 'none', border: `1px solid ${c.border}`, borderRadius: 6,
                         color: '#fbbf24', cursor: 'pointer', fontFamily: 'inherit', fontSize: 12, padding: '2px 8px' }}
              >Show all {matched}</button>
            </>
          )}
        </div>
      )}

      {/* List */}
      {loading ? (
        <div style={{ color: c.faint, fontSize: 13, padding: 20, textAlign: 'center' }}>Loading…</div>
      ) : cards.length === 0 ? (
        <div style={{ color: c.faint, fontSize: 13, padding: 20, textAlign: 'center' }}>
          {q ? 'No matching cards.' : 'Your collection is empty — add a card above.'}
        </div>
      ) : view === 'grid' ? (
        <CollectionGrid
          cards={cards} onSetCount={setCount} onRemove={removeCard}
          onPickPrinting={openPrintings} selectMode={selectMode} selected={selected}
          onToggleSelect={toggleSelect} busy={busy}
        />
      ) : (
        <div style={{ border: `1px solid ${c.border}`, borderRadius: 10, overflow: 'hidden' }}>
          {cards.map((row, i) => (
            <div key={`${row.name}|${row.set || ''}|${row.cn || ''}`} style={{
              display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
              background: i % 2 ? '#141210' : c.card, borderBottom: i < cards.length - 1 ? `1px solid ${c.border}` : 'none',
            }}>
              {selectMode && (
                <input type="checkbox" checked={selected.has(rowKey(row))}
                  onChange={() => toggleSelect(row)} style={{ flexShrink: 0, margin: 0 }} />
              )}
              {/* Colour identity dot — the fastest read of "what is this card" in a list
                  this long. An unrecognized row gets a hollow dot rather than a wrong one. */}
              <span title={row.resolved ? `${row.type_line || row.type}${row.mana_cost ? ` · ${row.mana_cost}` : ''}`
                                        : 'Not recognized — check the name'}
                style={{ width: 10, height: 10, borderRadius: '50%', flexShrink: 0,
                  background: !row.resolved ? 'transparent'
                    : (row.colors || []).length > 1 ? MANA.Multicolor
                    : MANA[(row.colors || [])[0]] || MANA.Colorless,
                  border: row.resolved ? 'none' : `1px solid ${c.faint}` }} />
              <CardHover name={row.name} style={{ flex: 1, fontSize: 13.5, color: '#f5f5f4', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }}>
                {row.name}
              </CardHover>
              {/* Same flag CollectionGrid's tile badge reads — enriched onto every row all
                  along, never shown in the list view either. */}
              {row.game_changer && (
                <span title="Official WotC Game Changer" style={{
                  fontSize: 10, fontWeight: 700, padding: '1px 5px', borderRadius: 5,
                  flexShrink: 0, color: '#fbbf24', border: '1px solid #d97706',
                  background: '#78350f22',
                }}>⚡ GC</span>
              )}
              <span title={row.resolved ? `Mana value ${row.cmc}` : ''}
                style={{ fontSize: 11, color: c.faint, minWidth: 46, textAlign: 'right',
                         flexShrink: 0, overflow: 'hidden', whiteSpace: 'nowrap' }}>
                {row.resolved ? `${row.type || ''} ${row.cmc}` : ''}
              </span>
              {/* Which printing this row is. Blank = set unknown (use Fill printings). */}
              {/* The set chip IS the printing control. A row with no printing reads as
                  "set?" rather than a dash, because it's an invitation, not a value. */}
              <button onClick={() => openPrintings(row)} disabled={busy}
                title={row.set ? `${row.set}${row.cn ? ` #${row.cn}` : ''} — click to change printing`
                               : 'Printing unknown — click to choose one'}
                style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '0.04em', flexShrink: 0,
                  padding: '1px 6px', borderRadius: 4, minWidth: 44, textAlign: 'center',
                  fontFamily: 'inherit', cursor: busy ? 'wait' : 'pointer',
                  background: row.set ? '#0c0a09' : 'transparent',
                  border: `1px solid ${row.set ? c.border : '#3f3a2a'}`,
                  color: row.set ? c.dim : '#a16207' }}>
                {row.set || 'set?'}
              </button>
              {/* Market price for this printing (x count shown on hover) */}
              <span title={row.price ? `$${row.price.toFixed(2)} each · $${(row.price * row.count).toFixed(2)} for ${row.count}` : 'No price yet — hit Get prices'}
                style={{ fontSize: 11.5, color: row.price ? '#4ade80' : c.faint, minWidth: 52,
                         textAlign: 'right', flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}>
                {row.price ? `$${row.price.toFixed(2)}` : '—'}
              </span>
              <button onClick={() => setCount(row, row.count - 1)} disabled={busy} style={btn({ padding: '2px 10px', fontSize: 16 })}>−</button>
              <span style={{ minWidth: 26, textAlign: 'center', fontSize: 13.5, color: c.gold, fontWeight: 700 }}>{row.count}</span>
              <button onClick={() => setCount(row, row.count + 1)} disabled={busy} style={btn({ padding: '2px 10px', fontSize: 16 })}>+</button>
              <button onClick={() => removeCard(row)} disabled={busy}
                style={btn({ padding: '2px 10px', color: '#f87171', border: '1px solid #3f1d1d' })} title="Remove this printing">✕</button>
            </div>
          ))}
        </div>
      )}
      {!loading && cards.length >= PAGE && (
        <div style={{ fontSize: 11.5, color: c.faint, marginTop: 8 }}>
          Showing the first {PAGE} — search, filter, or “Show all” above.
        </div>
      )}

      {/* Printing picker */}
      {printingFor && (
        <div onClick={() => setPrintingFor(null)}
          style={{ position: 'fixed', inset: 0, zIndex: 50, background: 'rgba(0,0,0,0.72)',
                   display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div onClick={e => e.stopPropagation()}
            style={{ background: c.panel, border: `1px solid ${c.border}`, borderRadius: 12,
                     padding: 16, maxWidth: 720, width: '100%', maxHeight: '80vh',
                     overflowY: 'auto' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 4 }}>
              <h2 style={{ fontSize: 16, color: c.gold, margin: 0 }}>Choose a printing</h2>
              <span style={{ fontSize: 13, color: '#f5f5f4' }}>{printingFor.name}</span>
              <button onClick={() => setPrintingFor(null)}
                style={btn({ marginLeft: 'auto', padding: '4px 10px', fontSize: 12 })}>Close</button>
            </div>
            <p style={{ fontSize: 12, color: c.faint, margin: '0 0 12px' }}>
              Cheapest first. Picking one keeps your count of {printingFor.count} and prices
              this row as that exact printing instead of a representative one.
            </p>
            {pLoading ? (
              <div style={{ color: c.faint, fontSize: 13, padding: 20, textAlign: 'center' }}>
                Loading printings…
              </div>
            ) : printings.length === 0 ? (
              <div style={{ color: c.faint, fontSize: 13, padding: 20, textAlign: 'center' }}>
                No printings found for this card.
              </div>
            ) : (
              <div style={{ display: 'grid', gap: 10,
                            gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))' }}>
                {printings.map(p => {
                  const current = (p.set || '') === (printingFor.set || '') &&
                                  String(p.collector_number || '') === String(printingFor.cn || '')
                  return (
                    <button key={`${p.set}|${p.collector_number}`} onClick={() => choosePrinting(p)}
                      title={`${p.set_name || p.set} #${p.collector_number}`}
                      style={{ padding: 6, borderRadius: 8, cursor: 'pointer', textAlign: 'center',
                               background: current ? '#1c1410' : c.card, fontFamily: 'inherit',
                               border: `1px solid ${current ? c.gold : c.border}` }}>
                      {p.image
                        ? <img src={p.image} alt="" loading="lazy"
                            style={{ width: '100%', borderRadius: 5, display: 'block' }} />
                        : <div style={{ aspectRatio: '488 / 680', background: c.panel, borderRadius: 5 }} />}
                      <div style={{ fontSize: 11, fontWeight: 700, color: c.dim, marginTop: 5 }}>
                        {p.set} {p.collector_number}
                      </div>
                      <div style={{ fontSize: 11, color: p.usd == null ? c.faint : c.green }}>
                        {p.usd == null ? 'no price' : `$${p.usd.toFixed(2)}`}
                      </div>
                      {current && <div style={{ fontSize: 10, color: c.gold }}>current</div>}
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
