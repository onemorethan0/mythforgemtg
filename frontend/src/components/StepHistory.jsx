import { useEffect, useState } from 'react'

const BRACKET_COLORS = {
  1: '#4ade80',
  2: '#a3e635',
  3: '#eab308',
  4: '#f97316',
  5: '#ef4444',
}
const BRACKET_LABELS = {
  1: 'Exhibition',
  2: 'Core',
  3: 'Upgraded',
  4: 'Optimized',
  5: 'cEDH',
}

function fmt_date(ts) {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

const s = {
  wrap:       { maxWidth: 900, width: '100%', marginTop: 20 },
  header:     { marginBottom: 20 },
  titleRow:   { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 4, flexWrap: 'wrap' },
  title:      { fontSize: 22, fontWeight: 700, color: '#eab308', letterSpacing: '0.05em' },
  sub:        { fontSize: 13, color: '#78716c' },
  grid:       { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 16 },
  card:       { background: '#1c1917', border: '1px solid #292524', borderRadius: 14, overflow: 'hidden', cursor: 'pointer', transition: 'border-color 0.15s, transform 0.15s', display: 'flex', flexDirection: 'column', position: 'relative' },
  cardHov:    { borderColor: '#ca8a04', transform: 'translateY(-2px)' },
  cardSel:    { borderColor: '#ef4444', background: '#1c0a0a' },
  thumb:      { width: '100%', aspectRatio: '4/3', objectFit: 'cover', background: '#0c0a09', display: 'block' },
  thumbFb:    { width: '100%', aspectRatio: '4/3', background: '#0c0a09', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 40, color: '#292524' },
  body:       { padding: '12px 14px', flex: 1, display: 'flex', flexDirection: 'column', gap: 4 },
  name:       { fontSize: 15, fontWeight: 700, color: '#f5f5f4', lineHeight: 1.3 },
  orig:       { fontSize: 11, color: '#57534e' },
  theme:      { fontSize: 12, color: '#a8a29e', marginTop: 4, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' },
  meta:       { display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, flexWrap: 'wrap' },
  bracket:    { fontSize: 10, padding: '2px 7px', borderRadius: 12, fontWeight: 700 },
  count:      { fontSize: 11, color: '#57534e' },
  date:       { fontSize: 11, color: '#44403c', marginLeft: 'auto' },
  loadBtn:    { padding: '8px 0', background: 'linear-gradient(180deg,#eab308,#a16207)', border: 'none', borderRadius: 8, color: '#0c0a09', fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit', fontSize: 13, flex: 1 },
  dupBtn:     { padding: '8px 0', background: '#0f172a', border: '1px solid #1e40af', borderRadius: 8, color: '#7dd3fc', fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit', fontSize: 12, flex: '0 0 auto', minWidth: 84 },
  delBtn:     { padding: '8px 10px', background: '#1c0a0a', border: '1px solid #7f1d1d', borderRadius: 8, color: '#f87171', fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit', fontSize: 12, flex: '0 0 auto' },
  btnRow:     { display: 'flex', gap: 6, marginTop: 10 },
  empty:      { textAlign: 'center', color: '#57534e', padding: '60px 0', fontSize: 15 },
  loading:    { textAlign: 'center', color: '#57534e', padding: '60px 0', fontSize: 15 },
  errMsg:     { textAlign: 'center', color: '#f87171', padding: '40px 0', fontSize: 14 },
  backBtn:    { marginBottom: 20, padding: '8px 18px', background: 'none', border: '1px solid #44403c', borderRadius: 9, color: '#a8a29e', cursor: 'pointer', fontFamily: 'inherit', fontSize: 13 },
  // Batch toolbar
  toolbar:    { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16, flexWrap: 'wrap' },
  selBtn:     { padding: '7px 14px', background: 'none', border: '1px solid #44403c', borderRadius: 8, color: '#a8a29e', cursor: 'pointer', fontFamily: 'inherit', fontSize: 13 },
  selBtnAct:  { border: '1px solid #ef4444', color: '#f87171', background: '#1c0a0a' },
  batchDelBtn:{ padding: '7px 16px', background: '#7f1d1d', border: '1px solid #991b1b', borderRadius: 8, color: '#fca5a5', fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit', fontSize: 13 },
  selAllBtn:  { padding: '7px 14px', background: 'none', border: '1px solid #44403c', borderRadius: 8, color: '#a8a29e', cursor: 'pointer', fontFamily: 'inherit', fontSize: 12 },
  selCount:   { fontSize: 13, color: '#78716c' },
  // Checkbox overlay
  checkWrap:  { position: 'absolute', top: 8, left: 8, zIndex: 10 },
  checkbox:   { width: 20, height: 20, accentColor: '#ef4444', cursor: 'pointer' },
}

// ── Confirmation modal ────────────────────────────────────────────────────────
function ConfirmModal({ message, onConfirm, onCancel }) {
  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 999,
    }}>
      <div style={{
        background: '#1c1917', border: '1px solid #44403c', borderRadius: 14,
        padding: '28px 32px', maxWidth: 380, width: '90%', textAlign: 'center',
      }}>
        <div style={{ fontSize: 32, marginBottom: 12 }}>🗑️</div>
        <div style={{ fontSize: 15, color: '#f5f5f4', marginBottom: 20, lineHeight: 1.5 }}>{message}</div>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'center' }}>
          <button
            onClick={onCancel}
            style={{ padding: '9px 22px', background: 'none', border: '1px solid #44403c', borderRadius: 8, color: '#a8a29e', cursor: 'pointer', fontFamily: 'inherit', fontSize: 14 }}
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            style={{ padding: '9px 22px', background: '#991b1b', border: 'none', borderRadius: 8, color: '#fca5a5', fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit', fontSize: 14 }}
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Single deck card ──────────────────────────────────────────────────────────
function DeckCard({ entry, onLoad, onResume, onDuplicated, onDeleted, selectMode, selected, onToggleSelect }) {
  const [hov, setHov]         = useState(false)
  const [loading, setLoading] = useState(false)
  const [duping, setDuping]   = useState(false)
  const [dupOk, setDupOk]     = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const isBuilding = entry.status === 'building'

  const bColor = BRACKET_COLORS[entry.bracket] || '#78716c'
  const bLabel = BRACKET_LABELS[entry.bracket] || `B${entry.bracket}`

  async function handleLoad() {
    if (selectMode) {
      if (!isBuilding) onToggleSelect(entry.job_id)
      return
    }
    if (isBuilding && onResume) {
      onResume(entry.job_id)
      return
    }
    setLoading(true)
    try {
      const r = await fetch(`/api/deck/${entry.job_id}`)
      if (!r.ok) throw new Error('Deck not found')
      const data = await r.json()
      onLoad(entry.job_id, data)
    } catch (err) {
      setLoading(false)
      if (entry.partial) {
        alert(`This deck is incomplete — ${entry.status === 'building' ? 'it\'s still building. Resume to check progress.' : 'the render data is missing.'}`)
      } else {
        alert('Failed to load deck — the render data may be missing.')
      }
    }
  }

  async function handleDuplicate(e) {
    e.stopPropagation()
    if (duping) return
    setDuping(true)
    try {
      const res = await fetch(`/api/deck/${entry.job_id}/duplicate`, { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setDupOk(true)
      if (onDuplicated) onDuplicated()
      setTimeout(() => setDupOk(false), 3000)
    } catch {
      alert('Duplicate failed. The deck may still be building.')
    } finally {
      setDuping(false)
    }
  }

  async function handleDelete(e) {
    e.stopPropagation()
    setConfirm(true)
  }

  async function confirmDelete() {
    setConfirm(false)
    setDeleting(true)
    try {
      const res = await fetch(`/api/deck/${entry.job_id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      onDeleted(entry.job_id)
    } catch (err) {
      alert(`Delete failed: ${err.message}`)
      setDeleting(false)
    }
  }

  const cardStyle = {
    ...s.card,
    ...(selected ? s.cardSel : hov && !selectMode ? s.cardHov : {}),
    ...(isBuilding ? { borderColor: '#3b82f6', animation: 'pulse-border 2s ease-in-out infinite' } : {}),
    opacity: deleting ? 0.4 : 1,
    transition: 'border-color 0.15s, transform 0.15s, opacity 0.2s',
  }

  return (
    <>
      {confirm && (
        <ConfirmModal
          message={`Permanently delete "${entry.themed_name || entry.commander_name}"? This cannot be undone.`}
          onConfirm={confirmDelete}
          onCancel={() => setConfirm(false)}
        />
      )}
      <div
        style={cardStyle}
        onMouseEnter={() => setHov(true)}
        onMouseLeave={() => setHov(false)}
      >
        {/* Checkbox overlay in select mode */}
        {selectMode && !isBuilding && (
          <div style={s.checkWrap} onClick={e => { e.stopPropagation(); onToggleSelect(entry.job_id) }}>
            <input
              type="checkbox"
              checked={selected}
              readOnly
              style={s.checkbox}
            />
          </div>
        )}

        {entry.thumbnail
          ? <img src={entry.thumbnail} alt={entry.themed_name || entry.commander_name} style={s.thumb} onClick={handleLoad} />
          : <div style={s.thumbFb} onClick={handleLoad}>⚔</div>
        }

        <div style={s.body}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 6 }}>
            <div style={{ ...s.name, flex: 1 }}>{entry.themed_name || entry.commander_name}</div>
            {isBuilding && (
              <span style={{ fontSize: 10, padding: '2px 6px', borderRadius: 8, background: '#0c2a4d', color: '#3b82f6', border: '1px solid #1e40af', flexShrink: 0, marginTop: 2, fontWeight: 600, animation: 'pulse-dot 2s ease-in-out infinite' }}>
                ⚙ building
              </span>
            )}
            {entry.is_copy && !isBuilding && (
              <span style={{ fontSize: 10, padding: '2px 6px', borderRadius: 8, background: '#0f172a', color: '#7dd3fc', border: '1px solid #1e40af', flexShrink: 0, marginTop: 2 }}>
                📋 copy
              </span>
            )}
            {entry.partial && !isBuilding && (
              <span style={{ fontSize: 10, padding: '2px 6px', borderRadius: 8, background: '#1c1207', color: '#fbbf24', border: '1px solid #92400e', flexShrink: 0, marginTop: 2 }}>
                📦 partial
              </span>
            )}
          </div>
          {entry.themed_name && entry.themed_name !== entry.commander_name && (
            <div style={s.orig}>({entry.commander_name})</div>
          )}
          {entry.theme && (
            <div style={s.theme}>{entry.theme}</div>
          )}
          <div style={s.meta}>
            <span style={{ ...s.bracket, background: `${bColor}22`, color: bColor, border: `1px solid ${bColor}44` }}>
              B{entry.bracket} {bLabel}
            </span>
            <span style={s.count}>{entry.card_count} cards</span>
            <span style={s.date}>{fmt_date(entry.built_at)}</span>
          </div>

          {!selectMode && (
            <div style={s.btnRow}>
              <button style={{ ...s.loadBtn, opacity: loading ? 0.6 : 1, background: isBuilding ? '#3b82f6' : 'linear-gradient(180deg,#eab308,#a16207)' }} onClick={handleLoad} disabled={loading || duping || deleting}>
                {loading ? 'Loading…' : isBuilding ? '▶ Resume Building' : 'View & Export →'}
              </button>
              {!isBuilding && (
                <>
                  <button
                    style={{ ...s.dupBtn, opacity: duping ? 0.6 : 1, color: dupOk ? '#4ade80' : '#7dd3fc', borderColor: dupOk ? '#16a34a' : '#1e40af' }}
                    onClick={handleDuplicate}
                    disabled={duping || loading || deleting}
                    title="Create an independent copy of this deck"
                  >
                    {duping ? '⏳' : dupOk ? '✓' : '📋'}
                  </button>
                </>
              )}
              <button
                style={{ ...s.delBtn, opacity: deleting ? 0.5 : 1 }}
                onClick={handleDelete}
                disabled={loading || duping || deleting}
                title="Delete this deck permanently"
              >
                {deleting ? '⏳' : '🗑'}
              </button>
            </div>
          )}

          {selectMode && (
            <div style={{ marginTop: 10, fontSize: 12, color: selected ? '#f87171' : '#57534e', textAlign: 'center' }}>
              {selected ? '✓ Selected for deletion' : 'Click to select'}
            </div>
          )}
        </div>
      </div>
    </>
  )
}

// ── History page ──────────────────────────────────────────────────────────────
export default function StepHistory({ onLoad, onResume, onBack }) {
  const [decks, setDecks]         = useState([])
  const [state, setState]         = useState('loading')
  const [selectMode, setSelectMode] = useState(false)
  const [selected, setSelected]   = useState(new Set())
  const [batchConfirm, setBatchConfirm] = useState(false)
  const [batchDeleting, setBatchDeleting] = useState(false)

  function loadDecks() {
    setState('loading')
    fetch('/api/decks')
      .then(r => r.json())
      .then(data => { setDecks(data); setState('ready') })
      .catch(() => setState('error'))
  }

  useEffect(() => { loadDecks() }, [])

  function handleDeleted(job_id) {
    setDecks(prev => prev.filter(d => d.job_id !== job_id))
    setSelected(prev => { const n = new Set(prev); n.delete(job_id); return n })
  }

  function toggleSelect(job_id) {
    setSelected(prev => {
      const n = new Set(prev)
      if (n.has(job_id)) n.delete(job_id)
      else n.add(job_id)
      return n
    })
  }

  function toggleSelectAll() {
    const nonBuilding = decks.filter(d => d.status !== 'building').map(d => d.job_id)
    if (selected.size === nonBuilding.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(nonBuilding))
    }
  }

  function exitSelectMode() {
    setSelectMode(false)
    setSelected(new Set())
  }

  async function handleBatchDelete() {
    setBatchConfirm(false)
    setBatchDeleting(true)
    try {
      const res = await fetch('/api/decks/delete-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_ids: [...selected] }),
      })
      const data = await res.json()
      const deletedSet = new Set(data.deleted || [])
      setDecks(prev => prev.filter(d => !deletedSet.has(d.job_id)))
      setSelected(new Set())
      if (data.skipped?.length) {
        alert(`${data.deleted.length} deck(s) deleted. ${data.skipped.length} skipped (currently building).`)
      }
    } catch (err) {
      alert(`Batch delete failed: ${err.message}`)
    } finally {
      setBatchDeleting(false)
      setSelectMode(false)
    }
  }

  const nonBuildingCount = decks.filter(d => d.status !== 'building').length

  return (
    <div style={s.wrap}>
      {batchConfirm && (
        <ConfirmModal
          message={`Permanently delete ${selected.size} deck${selected.size !== 1 ? 's' : ''}? This cannot be undone.`}
          onConfirm={handleBatchDelete}
          onCancel={() => setBatchConfirm(false)}
        />
      )}

      <button style={s.backBtn} onClick={onBack}>← New Deck</button>

      <div style={s.header}>
        <div style={s.titleRow}>
          <div style={s.title}>📚 Deck History</div>
          {state === 'ready' && decks.length > 0 && (
            <button
              style={{ ...s.selBtn, ...(selectMode ? s.selBtnAct : {}) }}
              onClick={() => selectMode ? exitSelectMode() : setSelectMode(true)}
            >
              {selectMode ? '✕ Cancel' : '☑ Select'}
            </button>
          )}
        </div>
        <div style={s.sub}>
          {selectMode
            ? 'Select decks to delete, then click Delete Selected.'
            : 'Browse and re-export previously generated decks.'}
        </div>
      </div>

      {/* Batch action toolbar */}
      {selectMode && (
        <div style={s.toolbar}>
          <button style={s.selAllBtn} onClick={toggleSelectAll}>
            {selected.size === nonBuildingCount && nonBuildingCount > 0 ? 'Deselect All' : 'Select All'}
          </button>
          <span style={s.selCount}>
            {selected.size} of {nonBuildingCount} selected
          </span>
          {selected.size > 0 && (
            <button
              style={{ ...s.batchDelBtn, opacity: batchDeleting ? 0.6 : 1 }}
              onClick={() => setBatchConfirm(true)}
              disabled={batchDeleting}
            >
              {batchDeleting ? 'Deleting…' : `🗑 Delete ${selected.size} Deck${selected.size !== 1 ? 's' : ''}`}
            </button>
          )}
        </div>
      )}

      {state === 'loading' && <div style={s.loading}>Loading saved decks…</div>}
      {state === 'error'   && <div style={s.errMsg}>Could not load deck history. Is the server running?</div>}
      {state === 'ready' && decks.length === 0 && (
        <div style={s.empty}>No decks yet — build one to see it here.</div>
      )}
      {state === 'ready' && decks.length > 0 && (
        <div style={s.grid}>
          {decks.map(entry => (
            <DeckCard
              key={entry.job_id}
              entry={entry}
              onLoad={onLoad}
              onResume={onResume}
              onDuplicated={loadDecks}
              onDeleted={handleDeleted}
              selectMode={selectMode}
              selected={selected.has(entry.job_id)}
              onToggleSelect={toggleSelect}
            />
          ))}
        </div>
      )}

      <style>{`
        @keyframes pulse-border {
          0%, 100% { border-color: #3b82f6; box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.1); }
          50% { border-color: #60a5fa; box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.2); }
        }
      `}</style>
    </div>
  )
}
