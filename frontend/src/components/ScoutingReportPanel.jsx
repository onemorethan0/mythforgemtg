import { useEffect, useRef, useState } from 'react'

// Scouting report (B38): one page of what this deck is, its bracket, how fast and how it kills,
// what it is good at and weak against, its strongest and weakest cards (the same cut ranking the
// Mentor and Advise use), its combos and the caveats. Every line is a measured field rendered by
// a template on the engine (ratings/scout.py) -- no model-written prose. Cached per decklist.

const AC = '#38bdf8'

function Section({ title, lines, color }) {
  if (!lines || !lines.length) return null
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 11.5, fontWeight: 700, color: color || '#d6d3d1', marginBottom: 3 }}>{title}</div>
      <ul style={{ margin: 0, paddingLeft: 18 }}>
        {lines.map((l, i) => (
          <li key={i} style={{ fontSize: 11.5, color: '#d6d3d1', lineHeight: 1.45 }}>
            {typeof l === 'string' ? l : l.text}
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function ScoutingReportPanel({ jobId }) {
  const [open, setOpen] = useState(false)
  const [phase, setPhase] = useState('idle')   // idle | loading | done | error
  const [result, setResult] = useState(null)
  const [errMsg, setErrMsg] = useState('')
  const cancelledRef = useRef(false)
  useEffect(() => () => { cancelledRef.current = true }, [])

  useEffect(() => {
    let cancelled = false
    fetch(`/api/deck/${jobId}/scout`).then((r) => (r.ok ? r.json() : null)).then((d) => {
      if (!cancelled && d?.cached) { setResult(d); setPhase('done'); setOpen(true) }
    }).catch(() => {})
    return () => { cancelled = true }
  }, [jobId])

  async function run() {
    if (phase === 'loading') return
    setOpen(true); setPhase('loading'); setErrMsg('')
    try {
      const r = await fetch(`/api/deck/${jobId}/scout`, { method: 'POST' })
      if (cancelledRef.current) return
      if (r.ok) { setResult(await r.json()); setPhase('done') } else {
        let d = 'HTTP ' + r.status
        try { d = (await r.json()).detail || d } catch { /* keep status */ }
        setErrMsg(d); setPhase('error')
      }
    } catch {
      if (!cancelledRef.current) { setErrMsg('Strength API unreachable'); setPhase('error') }
    }
  }

  const button = (label) => (
    <button onClick={run} disabled={phase === 'loading'}
      title="Measure this deck and write up what it is, how it wins, its best and worst cards (about a minute)"
      style={{ marginTop: 10, marginLeft: open ? 0 : 8, padding: '7px 16px', borderRadius: 8, border: `1px solid ${AC}66`, background: '#06141f', color: AC, fontWeight: 600, fontSize: 13, cursor: phase === 'loading' ? 'default' : 'pointer', fontFamily: 'inherit', opacity: phase === 'loading' ? 0.6 : 1 }}>
      {label}
    </button>
  )
  if (!open) return button('📋 Scouting report')

  const r = result?.report
  const b = r?.bracket || {}
  return (
    <div style={{ marginTop: 10, background: '#0c0a09', border: `1px solid ${AC}44`, borderLeft: `3px solid ${AC}`, borderRadius: 10, padding: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ fontWeight: 700, fontSize: 13, color: '#d6d3d1' }}>Scouting report</span>
        <span style={{ fontSize: 10.5, color: '#78716c' }}>every line is measured on this deck</span>
      </div>
      {phase === 'loading' && <div style={{ fontSize: 11.5, color: '#a8a29e' }}>⏳ Measuring the deck and each card's part in it…</div>}
      {phase === 'error' && <div style={{ fontSize: 12, color: '#fca5a5' }}>{errMsg}</div>}
      {phase === 'done' && r && (
        <>
          {r.gameplan && <div style={{ fontSize: 12, color: '#e7e5e4', marginBottom: 8, lineHeight: 1.45 }}>{r.gameplan}</div>}
          {b.bracket && (
            <Section title={`Bracket ${b.bracket} (${b.label || ''})${b.pod_read ? ' — ' + b.pod_read : ''}`}
                     lines={b.reasons} />
          )}
          <Section title="How fast" lines={r.clock} />
          <Section title="How it wins" lines={r.how_it_wins} />
          <Section title="Good at" lines={r.strengths} color="#86efac" />
          <Section title="Weak against" lines={r.weak_against} color="#fca5a5" />
          <Section title="Strongest cards" lines={r.strong_cards} color="#86efac" />
          <Section title="Weakest cards (best cuts first)" lines={r.weak_cards} color="#fca5a5" />
          <Section title="Combos" lines={r.combos} />
          <Section title="Table feel" lines={r.dials} />
          <Section title="Caveats" lines={r.caveats} color="#a8a29e" />
          {result.computed_at && <div style={{ fontSize: 10, color: '#57534e' }}>measured {result.computed_at.replace('T', ' ')}</div>}
        </>
      )}
      {phase !== 'loading' && button(phase === 'done' ? '↻ Re-run report' : '📋 Scouting report')}
    </div>
  )
}
