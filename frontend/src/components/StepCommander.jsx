import { useState, useRef, useEffect, useCallback } from 'react'
import ManaCost from './ManaCost'

const s = {
  card:     { maxWidth: 600, width: '100%', background: '#1c1917', border: '1px solid #292524', borderRadius: 16, padding: 32, marginTop: 16 },
  title:    { fontSize: 28, fontWeight: 700, color: '#eab308', marginBottom: 8, letterSpacing: '0.05em' },
  sub:      { fontSize: 14, color: '#78716c', marginBottom: 28 },
  row:      { display: 'flex', gap: 12, marginBottom: 4, position: 'relative' },
  inputWrap:{ flex: 1, position: 'relative' },
  input:    { width: '100%', boxSizing: 'border-box', background: '#0c0a09', border: '1px solid #44403c', borderRadius: 10, padding: '10px 16px', color: '#f5f5f4', fontSize: 15, outline: 'none', fontFamily: 'inherit' },
  inputOpen:{ borderBottomLeftRadius: 0, borderBottomRightRadius: 0, borderBottom: '1px solid #292524' },
  dropdown: { position: 'absolute', top: '100%', left: 0, right: 0, background: '#1c1917', border: '1px solid #44403c', borderTop: 'none', borderBottomLeftRadius: 10, borderBottomRightRadius: 10, zIndex: 100, overflow: 'hidden' },
  suggestion:(active) => ({ padding: '9px 16px', fontSize: 14, color: active ? '#eab308' : '#d6d3d1', background: active ? '#292524' : 'transparent', cursor: 'pointer', borderBottom: '1px solid #1c1917' }),
  btnGold:  { padding: '10px 24px', background: 'linear-gradient(180deg,#eab308,#a16207)', border: 'none', borderRadius: 10, color: '#0c0a09', fontWeight: 700, fontSize: 15, cursor: 'pointer', letterSpacing: '0.05em', fontFamily: 'inherit', whiteSpace: 'nowrap' },
  btnDisabled: { opacity: 0.4, cursor: 'not-allowed' },
  err:      { color: '#f87171', fontSize: 13, marginTop: 8, marginBottom: 4 },
  preview:  { display: 'flex', gap: 20, background: '#0c0a09', border: '1px solid #292524', borderRadius: 12, padding: 20, marginTop: 16 },
  img:      { width: 120, borderRadius: 8, flexShrink: 0 },
  meta:     { flex: 1 },
  name:     { fontSize: 18, fontWeight: 700, color: '#f5f5f4', marginBottom: 4 },
  type:     { fontSize: 12, color: '#a8a29e', marginBottom: 8 },
  oracle:   { fontSize: 12, color: '#d6d3d1', lineHeight: 1.6, maxHeight: 100, overflow: 'auto' },
  legal:    { display: 'inline-block', fontSize: 11, padding: '2px 8px', borderRadius: 20, marginTop: 8 },
  btnNext:  { width: '100%', marginTop: 20, padding: '12px', background: 'linear-gradient(180deg,#eab308,#a16207)', border: 'none', borderRadius: 10, color: '#0c0a09', fontWeight: 700, fontSize: 16, cursor: 'pointer', fontFamily: 'inherit', letterSpacing: '0.05em' },
}

const BRACKETS = [
  { n: 1, label: 'Exhibition', desc: 'Precon power. No Game Changers, extra turns, mass land destruction, or combos. Basics-heavy mana, theme-first.' },
  { n: 2, label: 'Core',       desc: 'Solid casual. Good synergies, no Game Changers or fast mana. A clean, fair deck.' },
  { n: 3, label: 'Upgraded',   desc: 'The popular bracket. Strong synergies + up to 3 Game Changers — a well-rounded competitive-casual deck.' },
  { n: 4, label: 'Optimized',  desc: 'High-powered: fast mana, tutors, and combos allowed. A strong goodstuff/value list — add your own combo lines to fully optimize.' },
  { n: 5, label: 'cEDH',       desc: 'Maximum power, no restrictions. A high-power goodstuff list with extra draw + interaction; a tuned tournament combo deck still needs hand-crafting.' },
]

export default function StepCommander({ onNext, bracket, onBracketChange, playstyle, onPlaystyleChange }) {
  const [query, setQuery]           = useState('')
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState('')
  const [result, setResult]         = useState(null)
  const [playstyles, setPlaystyles] = useState([])
  const [genLoading, setGenLoading] = useState(false)
  const [genErr, setGenErr]         = useState('')
  const [suggestions, setSuggestions] = useState([])
  const [showDrop, setShowDrop]     = useState(false)
  const [activeIdx, setActiveIdx]   = useState(-1)
  const inputRef  = useRef()
  const debounce  = useRef()

  // ── Import mode ─────────────────────────────────────────────────────────────
  const [mode, setMode]               = useState('generate')   // 'generate' | 'import'
  const [importText, setImportText]   = useState('')
  const [importLoading, setImportLoading] = useState(false)
  const [importErr, setImportErr]     = useState('')
  const [preview, setPreview]         = useState(null)
  const [cmdOverride, setCmdOverride] = useState('')

  async function doPreview(forceRefresh = false) {
    const val = importText.trim()
    if (!val) return
    setImportLoading(true); setImportErr(''); setPreview(null)
    try {
      const res = await fetch('/api/deck/import-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: val, force_refresh: forceRefresh }),
      })
      const data = await res.json()
      if (!res.ok) { setImportErr(data.detail || 'Import failed.'); setImportLoading(false); return }
      setPreview(data)
      setCmdOverride(data.commander?.name || '')
    } catch {
      setImportErr('Server unreachable. Is the backend running?')
    }
    setImportLoading(false)
  }

  function useImported() {
    if (!preview) return
    const mode2 = importText.trim().toLowerCase().startsWith('http') ? 'url' : 'text'
    const cmdName = preview.commander?.name || cmdOverride.trim()
    onNext({
      name:       cmdName,
      full_name:  cmdName,
      type_line:  preview.commander?.type_line || '',
      image_url:  preview.commander?.image_url || '',
      colors:     preview.colors || [],
      _import:    { mode: mode2, value: importText.trim() },
    })
  }

  // Fetch autocomplete suggestions with 200ms debounce
  const fetchSuggestions = useCallback((val) => {
    clearTimeout(debounce.current)
    if (val.trim().length < 2) { setSuggestions([]); setShowDrop(false); return }
    debounce.current = setTimeout(async () => {
      try {
        const r = await fetch(`/api/commander/autocomplete?q=${encodeURIComponent(val)}`)
        const d = await r.json()
        setSuggestions(d.suggestions || [])
        setShowDrop((d.suggestions || []).length > 0)
      } catch { setSuggestions([]); setShowDrop(false) }
    }, 200)
  }, [])

  function handleChange(e) {
    const val = e.target.value
    setQuery(val)
    setResult(null)
    setError('')
    setActiveIdx(-1)
    fetchSuggestions(val)
  }

  function pickSuggestion(name) {
    setQuery(name)
    setSuggestions([])
    setShowDrop(false)
    setActiveIdx(-1)
    doSearch(name)
  }

  function handleKeyDown(e) {
    if (!showDrop || !suggestions.length) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setActiveIdx(i => Math.min(i + 1, suggestions.length - 1)) }
    if (e.key === 'ArrowUp')   { e.preventDefault(); setActiveIdx(i => Math.max(i - 1, -1)) }
    if (e.key === 'Enter' && activeIdx >= 0) { e.preventDefault(); pickSuggestion(suggestions[activeIdx]) }
    if (e.key === 'Escape')    { setShowDrop(false) }
  }

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e) { if (!e.target.closest('[data-cmd-search]')) setShowDrop(false) }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  useEffect(() => {
    fetch('/api/playstyles').then(r => r.json()).then(setPlaystyles).catch(() => {})
  }, [])

  // Phase 1: build the decklist now (no art) so the theme step can show tribes.
  async function generateList() {
    if (!result) return
    setGenLoading(true); setGenErr('')
    try {
      const res = await fetch('/api/deck/generate-list', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          commander_name: result.full_name || result.name,
          playstyle, bracket,
        }),
      })
      const data = await res.json()
      if (!res.ok) { setGenErr(data.detail || 'Could not generate the decklist.'); setGenLoading(false); return }
      onNext({ ...result, _generated: { deck: data.deck, tribes: data.tribes, stats: data.stats } })
    } catch {
      setGenErr('Server unreachable. Is the backend running?')
    }
    setGenLoading(false)
  }

  async function doSearch(name) {
    const q = (name || query).trim()
    if (!q) return
    setLoading(true); setError(''); setResult(null); setShowDrop(false)
    try {
      const res = await fetch('/api/commander/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q }),
      })
      if (!res.ok) { setError('Commander not found — check spelling or try the full name.'); setLoading(false); return }
      setResult(await res.json())
    } catch {
      setError('Server unreachable. Is the backend running?')
    }
    setLoading(false)
  }

  function handleSubmit(e) {
    e.preventDefault()
    if (activeIdx >= 0 && showDrop) { pickSuggestion(suggestions[activeIdx]); return }
    setShowDrop(false)
    doSearch()
  }

  const COLOR_NAMES = { W: 'White', U: 'Blue', B: 'Black', R: 'Red', G: 'Green' }

  const tabStyle = (active) => ({
    flex: 1, padding: '10px 0', textAlign: 'center', cursor: 'pointer',
    fontSize: 14, fontWeight: 700, letterSpacing: '0.03em',
    background: active ? '#292524' : 'transparent',
    color: active ? '#eab308' : '#78716c',
    border: '1px solid #292524', borderRadius: 10,
  })

  return (
    <div style={s.card}>
      <h2 style={s.title}>{mode === 'import' ? 'Import a Deck' : 'Choose Your Commander'}</h2>
      <p style={s.sub}>
        {mode === 'import'
          ? 'Paste a Moxfield or Archidekt URL, or any decklist text, to retheme a deck you already own.'
          : 'Search for any legendary creature to generate a new deck.'}
      </p>

      <div style={{ display: 'flex', gap: 10, marginBottom: 20 }}>
        <div style={tabStyle(mode === 'generate')} onClick={() => setMode('generate')}>✨ Generate a deck</div>
        <div style={tabStyle(mode === 'import')}   onClick={() => setMode('import')}>📥 Import a deck</div>
      </div>

      {mode === 'import' && (
        <div>
          <textarea
            style={{ ...s.input, minHeight: 110, resize: 'vertical', fontFamily: 'inherit' }}
            placeholder={"https://www.moxfield.com/decks/...\nor\nhttps://archidekt.com/decks/...\n\nor paste a decklist:\nCommander\n1 Atraxa, Praetors' Voice\n\nDeck\n1 Sol Ring\n..."}
            value={importText}
            onChange={e => { setImportText(e.target.value); setPreview(null); setImportErr('') }}
          />
          <div style={{ fontSize: 12, color: '#57534e', margin: '8px 0 12px' }}>
            ManaBox: in the app, export the deck as text and paste it here. Moxfield links are best-effort —
            if one fails, paste the list instead. Imported decks are cached, so re-importing is instant.
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button
              style={{ ...s.btnGold, ...(importLoading || !importText.trim() ? s.btnDisabled : {}) }}
              disabled={importLoading || !importText.trim()}
              onClick={() => doPreview(false)}
            >
              {importLoading ? 'Importing…' : 'Preview deck'}
            </button>
            {preview && (
              <button style={{ ...s.btnGold, background: '#292524', color: '#d6d3d1' }}
                      onClick={() => doPreview(true)} disabled={importLoading}>
                ↻ Re-pull (skip cache)
              </button>
            )}
          </div>
          {importErr && <p style={s.err}>{importErr}</p>}

          {preview && (
            <div style={{ ...s.preview, flexDirection: 'column', gap: 12 }}>
              <div style={{ display: 'flex', gap: 16 }}>
                {preview.commander?.image_url
                  ? <img src={preview.commander.image_url} alt="" style={s.img} />
                  : <div style={{ ...s.img, background: '#292524', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#57534e', fontSize: 12, textAlign: 'center' }}>No commander detected</div>}
                <div style={s.meta}>
                  <div style={s.name}>{preview.name || 'Imported deck'}</div>
                  <div style={s.type}>
                    Source: {preview.source} · {preview.total_cards} cards
                    {preview.unique_cards !== preview.total_cards ? ` (${preview.unique_cards} unique)` : ''}
                  </div>
                  {preview.colors?.length > 0 && (
                    <div style={{ fontSize: 12, color: '#a8a29e', marginBottom: 6 }}>
                      {preview.colors.map(c => COLOR_NAMES[c] || c).join(' / ')}
                    </div>
                  )}
                  {preview.commander
                    ? <div style={{ fontSize: 13, color: '#86efac' }}>Commander: {preview.commander.name}</div>
                    : <div style={{ fontSize: 13, color: '#fca5a5', marginBottom: 6 }}>
                        No commander zone found — type your commander:
                        <input style={{ ...s.input, marginTop: 6 }} value={cmdOverride}
                               placeholder="e.g. Atraxa, Praetors' Voice"
                               onChange={e => setCmdOverride(e.target.value)} />
                      </div>}
                  {preview.partners?.length > 0 &&
                    <div style={{ fontSize: 12, color: '#a8a29e' }}>Partners: {preview.partners.join(', ')}</div>}
                </div>
              </div>
              {preview.unresolved?.length > 0 && (
                <div style={{ fontSize: 12, color: '#fbbf24', background: '#1c1410', padding: 10, borderRadius: 8 }}>
                  ⚠ {preview.unresolved.length} card(s) couldn't be matched and will be skipped:{' '}
                  {preview.unresolved.slice(0, 8).join(', ')}{preview.unresolved.length > 8 ? '…' : ''}
                </div>
              )}
              <button
                style={{ ...s.btnNext, ...((preview.commander || cmdOverride.trim()) ? {} : s.btnDisabled) }}
                disabled={!(preview.commander || cmdOverride.trim())}
                onClick={useImported}
              >
                Retheme this deck →
              </button>
            </div>
          )}
        </div>
      )}

      {mode === 'generate' && (<>
      <form onSubmit={handleSubmit} data-cmd-search>
        <div style={s.row}>
          <div style={s.inputWrap} data-cmd-search>
            <input
              ref={inputRef}
              style={{ ...s.input, ...(showDrop ? s.inputOpen : {}) }}
              placeholder="e.g. Atraxa, Krenko, Syr Gwyn..."
              value={query}
              onChange={handleChange}
              onKeyDown={handleKeyDown}
              onFocus={() => suggestions.length && setShowDrop(true)}
              disabled={loading}
              autoComplete="off"
            />
            {showDrop && suggestions.length > 0 && (
              <div style={s.dropdown} data-cmd-search>
                {suggestions.map((name, i) => (
                  <div
                    key={name}
                    style={s.suggestion(i === activeIdx)}
                    onMouseEnter={() => setActiveIdx(i)}
                    onMouseDown={() => pickSuggestion(name)}
                  >
                    {name}
                  </div>
                ))}
              </div>
            )}
          </div>
          <button
            type="submit"
            style={{ ...s.btnGold, ...(loading || !query.trim() ? s.btnDisabled : {}) }}
            disabled={loading || !query.trim()}
          >
            {loading ? '...' : 'Search'}
          </button>
        </div>
        {error && <p style={s.err}>{error}</p>}
      </form>

      {result && (
        <div>
          <div style={s.preview}>
            {result.image_url
              ? <img src={result.image_url} alt={result.name} style={s.img} />
              : <div style={{ ...s.img, background: '#292524', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#57534e', fontSize: 12 }}>No art</div>
            }
            <div style={s.meta}>
              <div style={s.name}>
                {result.name}
                <span style={{ marginLeft: 10 }}><ManaCost cost={result.mana_cost} /></span>
              </div>
              <div style={s.type}>{result.type_line}</div>
              {result.colors?.length > 0 && (
                <div style={{ fontSize: 12, color: '#a8a29e', marginBottom: 8 }}>
                  {result.colors.map(c => COLOR_NAMES[c] || c).join(' / ')}
                </div>
              )}
              <div style={s.oracle}>{result.oracle_text}</div>
              <span style={{
                ...s.legal,
                background: result.legal ? '#14532d' : '#450a0a',
                color:      result.legal ? '#86efac' : '#fca5a5',
              }}>
                {result.legal ? '✓ Commander Legal' : '✗ Not Legal'}
              </span>
            </div>
          </div>
          {/* Deck setup — bracket + playstyle shape the generated decklist */}
          <div style={{ marginTop: 18, padding: 16, background: '#0c0a09', border: '1px solid #292524', borderRadius: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#d6d3d1', marginBottom: 8 }}>Power bracket</div>
            <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
              {BRACKETS.map(b => (
                <button key={b.n} onClick={() => onBracketChange(b.n)}
                  style={{ flex: 1, padding: '8px 4px', borderRadius: 8, cursor: 'pointer', fontFamily: 'inherit',
                    background: bracket === b.n ? '#eab308' : 'transparent',
                    color: bracket === b.n ? '#0c0a09' : '#78716c',
                    border: `1px solid ${bracket === b.n ? '#eab308' : '#44403c'}`,
                    fontWeight: bracket === b.n ? 800 : 500, fontSize: 12 }}>
                  {b.n}. {b.label}
                </button>
              ))}
            </div>
            <div style={{ fontSize: 12, color: '#78716c', marginTop: -8, marginBottom: 16, lineHeight: 1.5 }}>
              {(BRACKETS.find(b => b.n === bracket) || BRACKETS[2]).desc}
            </div>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#d6d3d1', marginBottom: 8 }}>Playstyle</div>
            <select value={playstyle} onChange={e => onPlaystyleChange(e.target.value)}
              style={{ width: '100%', background: '#1c1917', border: '1px solid #44403c', borderRadius: 8,
                       padding: '9px 12px', color: '#f5f5f4', fontSize: 14, fontFamily: 'inherit', outline: 'none' }}>
              {playstyles.map(ps => <option key={ps.key} value={ps.key}>{ps.label}</option>)}
            </select>
          </div>
          {genErr && <p style={s.err}>{genErr}</p>}
          <button
            style={{ ...s.btnNext, ...(genLoading ? s.btnDisabled : {}) }}
            disabled={genLoading}
            onClick={generateList}
          >
            {genLoading ? 'Building your 99-card deck…' : `Generate decklist with ${result.name} →`}
          </button>
          {genLoading && (
            <p style={{ fontSize: 12, color: '#78716c', marginTop: 8, textAlign: 'center' }}>
              Selecting cards and looking them up on Scryfall. First-time decks can take up
              to a minute; repeat commanders are near-instant (cached). No art is generated yet.
            </p>
          )}
        </div>
      )}
      </>)}
    </div>
  )
}
