import { useEffect, useRef, useState } from 'react'

// ── Styles ────────────────────────────────────────────────────────────────────
const c = {
  wrap:       { maxWidth: 700, width: '100%', marginTop: 32 },
  header:     { textAlign: 'center', marginBottom: 28 },
  heroIcon:   { fontSize: 52, marginBottom: 10 },
  heroTitle:  { fontSize: 24, fontWeight: 700, color: '#eab308', margin: 0 },
  heroSub:    { fontSize: 13, color: '#78716c', marginTop: 6 },

  panel:      { background: '#1c1917', border: '1px solid #292524', borderRadius: 14, padding: '8px 20px 16px' },

  // step row
  row:        { display: 'flex', alignItems: 'flex-start', gap: 14, padding: '12px 0', borderBottom: '1px solid #1c1917' },
  rowIcon:    { fontSize: 18, minWidth: 24, paddingTop: 1 },
  rowBody:    { flex: 1, minWidth: 0 },
  rowLabel:   { fontSize: 11, color: '#57534e', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 3 },
  rowMsg:     (active) => ({ fontSize: 14, color: active ? '#fde047' : '#a8a29e', fontWeight: active ? 500 : 400 }),
  rowDot:     { width: 8, height: 8, borderRadius: '50%', background: '#eab308', marginTop: 5, flexShrink: 0, animation: 'pulse-dot 1.2s ease-in-out infinite' },

  // progress bar
  barTrack:   { height: 6, borderRadius: 3, background: '#292524', marginTop: 8, overflow: 'hidden' },
  barFill:    (pct, color='#eab308') => ({
    height: '100%', borderRadius: 3,
    background: color,
    width: `${Math.min(100, Math.max(0, pct))}%`,
    transition: 'width 0.4s ease',
  }),

  // art card detail row
  artCard:    { display: 'flex', alignItems: 'center', gap: 8, marginTop: 6, flexWrap: 'wrap' },
  artName:    { fontSize: 13, color: '#f5f5f4', fontWeight: 600, flex: 1, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' },
  artBadge:   (color='#44403c', text='#a8a29e') => ({ fontSize: 10, padding: '2px 7px', borderRadius: 20, background: color, color: text, flexShrink: 0 }),
  artMeta:    { fontSize: 12, color: '#57534e' },

  // counters row
  counters:   { display: 'flex', gap: 16, marginTop: 8, flexWrap: 'wrap' },
  countItem:  { fontSize: 12, color: '#78716c' },
  countVal:   { color: '#d6d3d1', fontWeight: 600 },

  empty:      { padding: '20px 0', color: '#57534e', fontSize: 14, textAlign: 'center' },
}

const STEP_META = {
  commander: { icon: '🔍', label: 'Commander Lookup' },
  deck:      { icon: '🃏', label: 'Deck Construction' },
  theme:     { icon: '✨', label: 'Theming with Ollama' },
  symbol:    { icon: '🔮', label: 'Set Symbol' },
  art:       { icon: '🎨', label: 'Card Art (ComfyUI)' },
  render:    { icon: '🖼',  label: 'Rendering Frames' },
}
const STEP_ORDER = ['commander', 'deck', 'theme', 'symbol', 'art', 'render']

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmt_time(secs) {
  if (!secs || secs < 0) return '--'
  if (secs < 60) return `${secs}s`
  const m = Math.floor(secs / 60), s = secs % 60
  return s > 0 ? `${m}m ${s}s` : `${m}m`
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ProgressBar({ pct, color }) {
  return (
    <div style={c.barTrack}>
      <div style={c.barFill(pct, color)} />
    </div>
  )
}

function ThemeDetail({ data }) {
  if (!data) return null
  const { batch, total_batches, cards_done, total_cards, pct } = data
  return (
    <div style={{ marginTop: 6 }}>
      <ProgressBar pct={pct || 0} color="#a78bfa" />
      <div style={c.counters}>
        <span style={c.countItem}>Batch <span style={c.countVal}>{batch}/{total_batches}</span></span>
        <span style={c.countItem}>Cards <span style={c.countVal}>{cards_done}/{total_cards}</span></span>
        <span style={c.countItem}><span style={c.countVal}>{pct || 0}%</span> complete</span>
      </div>
    </div>
  )
}

function ArtDetail({ data, active }) {
  if (!data) return null
  const { card_num, total, card_name, has_face, pct, elapsed, eta, last_ok } = data
  return (
    <div style={{ marginTop: 6 }}>
      <ProgressBar pct={pct || 0} color="#eab308" />

      {card_name && (
        <div style={c.artCard}>
          <span style={c.artName}>{card_name}</span>
          {has_face && (
            <span style={c.artBadge('#eab30822', '#eab308')}>👤 face</span>
          )}
          {last_ok === false && (
            <span style={c.artBadge('#450a0a', '#fca5a5')}>⚠ failed</span>
          )}
        </div>
      )}

      <div style={c.counters}>
        <span style={c.countItem}>Card <span style={c.countVal}>{card_num}/{total}</span></span>
        <span style={c.countItem}><span style={c.countVal}>{(pct||0).toFixed(1)}%</span></span>
        {elapsed != null && <span style={c.countItem}>Elapsed <span style={c.countVal}>{fmt_time(elapsed)}</span></span>}
        {active && eta != null && eta > 0 && (
          <span style={c.countItem}>ETA <span style={{ ...c.countVal, color: '#fde047' }}>{fmt_time(eta)}</span></span>
        )}
      </div>
    </div>
  )
}

// ── Live card grid ────────────────────────────────────────────────────────────
function CardGrid({ jobId, cards }) {
  if (!cards.length) return null
  return (
    <div style={{ marginTop: 20 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 10 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: '#a8a29e' }}>
          Generated Cards
        </span>
        <span style={{ fontSize: 12, color: '#57534e' }}>
          {cards.length} rendered
        </span>
      </div>
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(72px, 1fr))',
        gap: 6,
        maxHeight: 420,
        overflowY: 'auto',
        paddingRight: 4,
      }}>
        {cards.map((card, idx) => (
          <CardThumb key={card.key} jobId={jobId} card={card} isLatest={idx === cards.length - 1} />
        ))}
      </div>
    </div>
  )
}

function CardThumb({ jobId, card, isLatest }) {
  const [hovered, setHovered] = useState(false)
  // Append a timestamp so re-renders of the same card (e.g. after regen
  // mid-build) bypass the browser's HTTP cache.
  const src = `/api/deck/${jobId}/card-image/${card.key}?t=${card.ts || 0}`
  return (
    <div
      style={{ position: 'relative', cursor: 'default' }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <img
        src={src}
        alt={card.name}
        style={{
          width: '100%',
          aspectRatio: '480 / 672',
          borderRadius: 4,
          display: 'block',
          border: isLatest ? '2px solid #eab308' : '2px solid transparent',
          transition: 'border-color 0.3s',
          animation: isLatest ? 'card-pop 0.3s ease-out' : 'none',
        }}
      />
      {/* Name tooltip on hover */}
      {hovered && (
        <div style={{
          position: 'absolute',
          bottom: '105%',
          left: '50%',
          transform: 'translateX(-50%)',
          background: '#0c0a09',
          border: '1px solid #44403c',
          borderRadius: 6,
          padding: '4px 8px',
          fontSize: 11,
          color: '#f5f5f4',
          whiteSpace: 'nowrap',
          zIndex: 10,
          pointerEvents: 'none',
          maxWidth: 180,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}>
          {card.name}
        </div>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function StepBuilding({ jobId, onDone, onError }) {
  const [byStep, setByStep]       = useState({})
  const [themeData, setThemeData] = useState(null)
  const [artData, setArtData]     = useState(null)
  const [status, setStatus]       = useState('building')
  const [readyCards, setReadyCards] = useState([])    // {key, name} as they arrive
  const [cancelState, setCancelState] = useState('idle')  // idle | cancelling | cancelled

  const evtRef    = useRef(null)
  const bottomRef = useRef(null)

  // Keep latest handler refs so the EventSource useEffect (which depends only
  // on jobId) always calls the current onDone/onError even if the parent
  // re-renders with new closures.
  const onDoneRef  = useRef(onDone)
  const onErrorRef = useRef(onError)
  useEffect(() => { onDoneRef.current  = onDone  }, [onDone])
  useEffect(() => { onErrorRef.current = onError }, [onError])

  useEffect(() => {
    if (!jobId) return
    const src = new EventSource(`/api/deck/${jobId}/events`)
    evtRef.current = src

    src.addEventListener('progress', e => {
      try {
        const d = JSON.parse(e.data)
        setByStep(prev => ({ ...prev, [d.step]: d.msg }))

        if (d.step === 'theme' && d.batch != null) {
          setThemeData({ batch: d.batch, total_batches: d.total_batches,
                         cards_done: d.cards_done, total_cards: d.total_cards, pct: d.pct })
        }
        if (d.step === 'art' && d.card_num != null) {
          setArtData({ card_num: d.card_num, total: d.total, card_name: d.card_name,
                       has_face: d.has_face, pct: d.pct, elapsed: d.elapsed,
                       eta: d.eta, last_ok: d.last_ok })
        }
      } catch {}
    })

    // New: card_ready fires after each card is rendered inline
    src.addEventListener('card_ready', e => {
      try {
        const d = JSON.parse(e.data)
        setReadyCards(prev => {
          // If this card key already exists (e.g. regen mid-build), replace it
          // with a fresh timestamp so the <img> reloads.
          const existing = prev.findIndex(c => c.key === d.key)
          const entry = { key: d.key, name: d.name, ts: Date.now() }
          if (existing >= 0) {
            const next = prev.slice()
            next[existing] = entry
            return next
          }
          return [...prev, entry]
        })
      } catch {}
    })

    src.addEventListener('done', e => {
      src.close()
      setStatus('done')
      try {
        const d = JSON.parse(e.data)
        fetch(`/api/deck/${d.job_id}`)
          .then(async r => {
            if (!r.ok) {
              // Server responded with an error status — read the detail so the
              // user sees the real reason instead of "Failed to load deck result".
              let detail = `HTTP ${r.status}`
              try {
                const body = await r.json()
                if (body && body.detail) detail = body.detail
              } catch {}
              throw new Error(detail)
            }
            return r.json()
          })
          .then(onDoneRef.current)
          .catch(err => onErrorRef.current(`Failed to load deck result: ${err.message || err}`))
      } catch { onErrorRef.current('Bad done event') }
    })

    src.addEventListener('error', e => {
      // Distinguish server-sent error events (have e.data) from native
      // EventSource connection errors (no e.data).  Connection errors trigger
      // a normal browser reconnect — do NOT treat them as fatal build errors.
      if (!e.data) return
      src.close()
      setStatus('error')
      try { const d = JSON.parse(e.data); onErrorRef.current(d.msg) }
      catch { onErrorRef.current('Unknown build error') }
    })

    src.onerror = () => {
      // Connection-level error (drop / reconnect).  Check the job status so we
      // can recover if the SSE stream ended after a "done" or "error" push.
      // We intentionally do NOT call onError here — transient reconnects during
      // the long art-gen step are normal and must not abort the build.
      fetch(`/api/deck/${jobId}/status`)
        .then(r => r.json())
        .then(d => {
          if (d.status === 'error') {
            src.close()
            onErrorRef.current(d.error || 'Build failed')
          } else if (d.status === 'done') {
            src.close()
            fetch(`/api/deck/${jobId}`)
              .then(async r => {
                if (!r.ok) {
                  let detail = `HTTP ${r.status}`
                  try { const body = await r.json(); if (body?.detail) detail = body.detail } catch {}
                  throw new Error(detail)
                }
                return r.json()
              })
              .then(onDoneRef.current)
              .catch(err => onErrorRef.current(`Failed to load deck: ${err.message || err}`))
          }
          // still building — let EventSource reconnect automatically
        })
        .catch(() => {})  // network totally down — just wait
    }

    return () => src.close()
  }, [jobId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [byStep, artData, themeData])

  async function handleCancel() {
    if (cancelState !== 'idle') return
    setCancelState('cancelling')
    try {
      await fetch(`/api/deck/${jobId}/cancel`, { method: 'POST' })
    } catch {}
    // UI updates when the build finishes and sends 'done'
  }

  const visibleSteps = STEP_ORDER.filter(s => byStep[s])
  const lastStep = visibleSteps[visibleSteps.length - 1] || null

  // Compute overall rough % for hero bar
  const STEP_WEIGHTS = { commander: 2, deck: 5, theme: 20, symbol: 1, art: 65, render: 7 }
  let heroProgress = 0
  STEP_ORDER.forEach(s => {
    if (!byStep[s]) return
    const w = STEP_WEIGHTS[s] || 5
    if (s !== lastStep || status === 'done') {
      heroProgress += w
    } else if (s === 'art' && artData) {
      heroProgress += w * (artData.pct / 100)
    } else if (s === 'theme' && themeData) {
      heroProgress += w * ((themeData.pct || 0) / 100)
    } else {
      heroProgress += w * 0.5
    }
  })
  const totalWeight = Object.values(STEP_WEIGHTS).reduce((a, b) => a + b, 0)
  const heroPct = Math.min(100, Math.round((heroProgress / totalWeight) * 100))

  const isCancelling = cancelState === 'cancelling'
  const canCancel    = status === 'building' && cancelState === 'idle'

  return (
    <div style={c.wrap}>
      {/* Header */}
      <div style={c.header}>
        <div style={c.heroIcon}>{status === 'done' ? '✅' : isCancelling ? '⏹️' : '⚙️'}</div>
        <h2 style={c.heroTitle}>
          {status === 'done' ? 'Deck Complete!' : isCancelling ? 'Cancelling…' : 'Forging Your Deck…'}
        </h2>
        <p style={c.heroSub}>
          {status === 'done'
            ? 'Your deck is ready.'
            : isCancelling
              ? 'Finishing the current card, then stopping. Deck will show what was completed.'
              : byStep.art
                ? 'Generating card art with FLUX — this is the long step.'
                : 'Hang tight while we build and theme your deck.'}
        </p>

        {/* Overall progress bar */}
        {status !== 'done' && (
          <div style={{ marginTop: 14, padding: '0 16px' }}>
            <ProgressBar pct={heroPct} color={isCancelling ? '#78716c' : heroPct < 70 ? '#eab308' : '#22c55e'} />
            <div style={{ fontSize: 12, color: '#57534e', marginTop: 4 }}>{heroPct}% overall</div>
          </div>
        )}

        {/* Cancel button */}
        {canCancel && (
          <button
            onClick={handleCancel}
            style={{
              marginTop: 16,
              padding: '8px 22px',
              background: 'none',
              border: '1px solid #44403c',
              borderRadius: 8,
              color: '#78716c',
              fontSize: 13,
              cursor: 'pointer',
              fontFamily: 'inherit',
              transition: 'border-color 0.15s, color 0.15s',
            }}
            onMouseEnter={e => { e.target.style.borderColor = '#ef4444'; e.target.style.color = '#fca5a5' }}
            onMouseLeave={e => { e.target.style.borderColor = '#44403c'; e.target.style.color = '#78716c' }}
          >
            ✕ Cancel Build
          </button>
        )}
        {isCancelling && (
          <div style={{ marginTop: 16, fontSize: 12, color: '#57534e' }}>
            Waiting for current card to finish…
          </div>
        )}
      </div>

      {/* Step log */}
      <div style={c.panel}>
        {visibleSteps.length === 0 && (
          <div style={c.empty}>Connecting to build pipeline…</div>
        )}

        {STEP_ORDER.filter(s => byStep[s]).map(s => {
          const meta   = STEP_META[s] || { icon: '⚙', label: s }
          const active = s === lastStep && status === 'building'
          return (
            <div key={s} style={c.row}>
              <span style={c.rowIcon}>{meta.icon}</span>
              <div style={c.rowBody}>
                <div style={c.rowLabel}>{meta.label}</div>
                <div style={c.rowMsg(active)}>{byStep[s]}</div>

                {/* Theme inline detail */}
                {s === 'theme' && themeData && (
                  <ThemeDetail data={themeData} />
                )}

                {/* Art inline detail */}
                {s === 'art' && artData && (
                  <ArtDetail data={artData} active={active} />
                )}
              </div>
              {active && <div style={c.rowDot} />}
            </div>
          )
        })}
      </div>

      {/* Live card grid — fills in as art generates */}
      <CardGrid jobId={jobId} cards={readyCards} />

      <div ref={bottomRef} />

      <style>{`
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; transform: scale(1); }
          50%       { opacity: 0.4; transform: scale(0.7); }
        }
        @keyframes card-pop {
          from { opacity: 0; transform: scale(0.88); }
          to   { opacity: 1; transform: scale(1); }
        }
      `}</style>
    </div>
  )
}
