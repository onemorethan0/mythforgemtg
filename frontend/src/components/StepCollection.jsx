import { useEffect, useState, useCallback, useRef } from 'react'
import CardHover from './CardHover'
import CollectionStats from './CollectionStats'

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

const EMPTY_FILTERS = { colors: [], types: [], rarities: [], sets: [],
                        cmc_min: null, cmc_max: null, min_count: null }

const hasFilters = f =>
  f.colors.length || f.types.length || f.rarities.length || f.sets.length ||
  f.cmc_min != null || f.cmc_max != null || f.min_count != null

// Filters go on the query string as comma-separated lists; nulls are simply omitted.
function filterQuery(f) {
  const p = new URLSearchParams()
  for (const k of ['colors', 'types', 'rarities', 'sets']) if (f[k].length) p.set(k, f[k].join(','))
  for (const k of ['cmc_min', 'cmc_max', 'min_count']) if (f[k] != null) p.set(k, String(f[k]))
  return p
}

// Toggle one value inside a multi-select facet.
const toggle = (list, v) => (list.includes(v) ? list.filter(x => x !== v) : [...list, v])

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
  const debounce = useRef(null)
  const sugDebounce = useRef(null)

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
                    <div key={cm.commander} style={{ border: `1px solid ${c.border}`, borderRadius: 10, padding: 12, background: c.card }}>
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
          value={q} onChange={e => setQ(e.target.value)}
          placeholder="Search your collection…"
          style={{ flex: '1 1 240px', boxSizing: 'border-box', padding: '9px 12px', borderRadius: 8, background: c.panel,
                   border: `1px solid ${c.border}`, color: '#f5f5f4', fontFamily: 'inherit', fontSize: 14 }}
        />
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
      </div>

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
      ) : (
        <div style={{ border: `1px solid ${c.border}`, borderRadius: 10, overflow: 'hidden' }}>
          {cards.map((row, i) => (
            <div key={`${row.name}|${row.set || ''}|${row.cn || ''}`} style={{
              display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
              background: i % 2 ? '#141210' : c.card, borderBottom: i < cards.length - 1 ? `1px solid ${c.border}` : 'none',
            }}>
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
              <span title={row.resolved ? `Mana value ${row.cmc}` : ''}
                style={{ fontSize: 11, color: c.faint, minWidth: 46, textAlign: 'right',
                         flexShrink: 0, overflow: 'hidden', whiteSpace: 'nowrap' }}>
                {row.resolved ? `${row.type || ''} ${row.cmc}` : ''}
              </span>
              {/* Which printing this row is. Blank = set unknown (use Fill printings). */}
              <span title={row.set ? `${row.set}${row.cn ? ` #${row.cn}` : ''}` : 'Printing unknown'}
                style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '0.04em', flexShrink: 0,
                  padding: '1px 6px', borderRadius: 4, minWidth: 40, textAlign: 'center',
                  background: row.set ? '#0c0a09' : 'transparent',
                  border: `1px solid ${row.set ? c.border : 'transparent'}`,
                  color: row.set ? c.dim : c.faint }}>
                {row.set || '—'}
              </span>
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
      {!loading && cards.length >= 500 && (
        <div style={{ fontSize: 11.5, color: c.faint, marginTop: 8 }}>Showing first 500 — use search to narrow.</div>
      )}
    </div>
  )
}
