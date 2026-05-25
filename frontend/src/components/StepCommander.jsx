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

export default function StepCommander({ onNext }) {
  const [query, setQuery]           = useState('')
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState('')
  const [result, setResult]         = useState(null)
  const [suggestions, setSuggestions] = useState([])
  const [showDrop, setShowDrop]     = useState(false)
  const [activeIdx, setActiveIdx]   = useState(-1)
  const inputRef  = useRef()
  const debounce  = useRef()

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

  return (
    <div style={s.card}>
      <h2 style={s.title}>Choose Your Commander</h2>
      <p style={s.sub}>Search for any legendary creature.</p>

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
          <button style={s.btnNext} onClick={() => onNext(result)}>
            Build Deck with {result.name} →
          </button>
        </div>
      )}
    </div>
  )
}
