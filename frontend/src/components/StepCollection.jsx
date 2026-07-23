import { useEffect, useState, useCallback, useRef } from 'react'
import CardHover from './CardHover'

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

export default function StepCollection({ onBack, onBuild }) {
  const [cards, setCards]       = useState([])
  const [summary, setSummary]   = useState({ distinct: 0, total_cards: 0, path: '', exists: false })
  const [matched, setMatched]   = useState(0)
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
  const debounce = useRef(null)
  const sugDebounce = useRef(null)

  const loadBuildable = useCallback(() => {
    setBLoading(true)
    fetch('/api/collection/buildable?limit=8')
      .then(r => r.json())
      .then(d => setBuildable(d))
      .catch(() => flash('err', 'Could not scan your collection.'))
      .finally(() => setBLoading(false))
  }, [])

  const flash = (kind, text) => { setMsg({ kind, text }); if (text) setTimeout(() => setMsg(null), 4000) }

  const load = useCallback((query = '') => {
    setLoading(true)
    fetch(`/api/collection?limit=500&q=${encodeURIComponent(query)}`)
      .then(r => r.json())
      .then(d => {
        setCards(d.cards || [])
        setMatched(d.matched || 0)
        setSummary({ distinct: d.distinct, total_cards: d.total_cards, path: d.path, exists: d.exists })
      })
      .catch(() => flash('err', 'Could not load collection — is the server running?'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load('') }, [load])

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
        setSummary({ distinct: d.distinct, total_cards: d.total_cards, path: d.path, exists: d.exists })
        if (okMsg) flash('ok', okMsg(d))
        load(q.trim())
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

  const setCount = (name, count) =>
    apply(fetch('/api/collection/count', {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, count }),
    }), null)

  const removeCard = (name) =>
    // name is a query param, not a path segment — DFC/split names contain '//' and an
    // encoded slash in the path 405s under Starlette routing.
    apply(fetch(`/api/collection?name=${encodeURIComponent(name)}`, { method: 'DELETE' }),
      () => `Removed ${name}`)

  const runImport = () => {
    const text = importText.trim()
    if (!text) return
    apply(fetch('/api/collection/import', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, mode: importMode }),
    }), d => `Imported (${importMode}) — ${d.distinct} cards now`)
    setImportText(''); setShowImport(false)
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
      </div>

      {/* Bulk import */}
      {showImport && (
        <div style={{ margin: '0 0 14px', padding: 14, borderRadius: 10, background: c.panel, border: `1px solid ${c.border}` }}>
          <div style={{ fontSize: 12.5, color: c.dim, marginBottom: 8 }}>
            Paste a Moxfield CSV (<code>Count,Name</code>) or a plain decklist (<code>1 Sol Ring</code>).
          </div>
          <textarea
            value={importText} onChange={e => setImportText(e.target.value)}
            rows={7} placeholder={'Count,Name\n1,Sol Ring\n2,Llanowar Elves'}
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

      {/* Search */}
      <input
        value={q} onChange={e => setQ(e.target.value)}
        placeholder="Search your collection…"
        style={{ width: '100%', boxSizing: 'border-box', padding: '9px 12px', borderRadius: 8, background: c.panel,
                 border: `1px solid ${c.border}`, color: '#f5f5f4', fontFamily: 'inherit', fontSize: 14, marginBottom: 10 }}
      />
      {q && <div style={{ fontSize: 12, color: c.faint, marginBottom: 8 }}>{matched} match{matched === 1 ? '' : 'es'}</div>}

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
            <div key={row.name} style={{
              display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
              background: i % 2 ? '#141210' : c.card, borderBottom: i < cards.length - 1 ? `1px solid ${c.border}` : 'none',
            }}>
              <CardHover name={row.name} style={{ flex: 1, fontSize: 13.5, color: '#f5f5f4', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }}>
                {row.name}
              </CardHover>
              <button onClick={() => setCount(row.name, row.count - 1)} disabled={busy} style={btn({ padding: '2px 10px', fontSize: 16 })}>−</button>
              <span style={{ minWidth: 26, textAlign: 'center', fontSize: 13.5, color: c.gold, fontWeight: 700 }}>{row.count}</span>
              <button onClick={() => setCount(row.name, row.count + 1)} disabled={busy} style={btn({ padding: '2px 10px', fontSize: 16 })}>+</button>
              <button onClick={() => removeCard(row.name)} disabled={busy}
                style={btn({ padding: '2px 10px', color: '#f87171', border: '1px solid #3f1d1d' })} title="Remove">✕</button>
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
