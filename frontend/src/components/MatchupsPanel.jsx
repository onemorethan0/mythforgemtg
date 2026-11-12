import { useEffect, useRef, useState } from 'react'
import { tracked } from '../utils/jobs'

// Matchups (B35): this deck against its bracket's reference field -- one corpus deck per
// archetype a casual pod meets -- in two-player Tier-2 duels. Weak / favoured only when the
// 90% interval clears 50%. The fidelity note is printed with every result: these are
// directional, battlecruiser-fidelity duels, not a prediction of a real game.

const VERDICT = {
  weak: { label: 'weak against', color: '#ef4444' },
  favoured: { label: 'favoured', color: '#4ade80' },
  even: { label: 'even', color: '#a8a29e' },
}

function Row({ m }) {
  const v = VERDICT[m.verdict] || VERDICT.even
  const pct = (x) => `${Math.round(x * 100)}%`
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11.5 }}>
        <span style={{ color: '#e7e5e4', minWidth: 170 }}>{m.label}</span>
        <span style={{ color: '#78716c', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>vs {m.opponent}</span>
        <b style={{ color: '#e7e5e4' }}>{pct(m.winrate)}</b>
        <span style={{ fontSize: 10, padding: '1px 7px', borderRadius: 10, border: `1px solid ${v.color}`, color: v.color, background: `${v.color}1a` }}>{v.label}</span>
      </div>
      <div style={{ position: 'relative', height: 6, borderRadius: 4, background: '#0c0a09', margin: '3px 0 2px' }}
        title={`90% interval ${pct(m.low)}-${pct(m.high)} over ${m.games} games`}>
        <div style={{ position: 'absolute', left: '50%', top: -2, bottom: -2, width: 1, background: '#57534e' }} />
        <div style={{ position: 'absolute', left: pct(m.low), width: `${Math.max(1, (m.high - m.low) * 100)}%`, top: 0, bottom: 0, borderRadius: 4, background: `${v.color}55` }} />
        <div style={{ position: 'absolute', left: `calc(${pct(m.winrate)} - 1px)`, width: 3, top: -1, bottom: -1, background: v.color }} />
      </div>
      <div style={{ fontSize: 10, color: '#78716c' }}>{m.why}</div>
    </div>
  )
}

export default function MatchupsPanel({ jobId }) {
  const [open, setOpen] = useState(false)
  const [phase, setPhase] = useState('idle')   // idle | loading | done | error
  const [result, setResult] = useState(null)
  const [errMsg, setErrMsg] = useState('')
  const cancelledRef = useRef(false)
  useEffect(() => () => { cancelledRef.current = true }, [])

  // a cached result for this exact decklist opens straight into the table
  useEffect(() => {
    let cancelled = false
    fetch(`/api/deck/${jobId}/matchups`).then((r) => (r.ok ? r.json() : null)).then((d) => {
      if (!cancelled && d?.cached) { setResult(d); setPhase('done'); setOpen(true) }
    }).catch(() => {})
    return () => { cancelled = true }
  }, [jobId])

  function run() {
    if (phase === 'loading') return undefined
    return tracked('Scout matchups', null, runInner)
  }

  async function runInner() {
    setOpen(true); setPhase('loading'); setErrMsg('')
    try {
      const r = await fetch(`/api/deck/${jobId}/matchups`, { method: 'POST' })
      if (cancelledRef.current) return
      if (r.ok) { setResult(await r.json()); setPhase('done') } else {
        let d = 'HTTP ' + r.status
        try { d = (await r.json()).detail || d } catch {}
        setErrMsg(d); setPhase('error')
      }
    } catch {
      if (!cancelledRef.current) { setErrMsg('Strength API unreachable'); setPhase('error') }
    }
  }

  const AC = '#fbbf24'
  const button = (label) => (
    <button onClick={run} disabled={phase === 'loading'}
      title="Duel this deck against one reference deck per archetype at its bracket (120 games each)"
      style={{ marginTop: 10, marginLeft: open ? 0 : 8, padding: '7px 16px', borderRadius: 8, border: `1px solid ${AC}66`, background: '#1f1606', color: AC, fontWeight: 600, fontSize: 13, cursor: phase === 'loading' ? 'default' : 'pointer', fontFamily: 'inherit', opacity: phase === 'loading' ? 0.6 : 1 }}>
      {label}
    </button>
  )
  if (!open) return button('🧭 Scout matchups')

  return (
    <div style={{ marginTop: 10, background: '#0c0a09', border: `1px solid ${AC}44`, borderLeft: `3px solid ${AC}`, borderRadius: 10, padding: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ fontWeight: 700, fontSize: 13, color: '#d6d3d1' }}>Matchups</span>
        {result && <span style={{ fontSize: 10.5, color: '#78716c' }}>vs the Bracket {result.bracket} reference field · {result.games_each} games each</span>}
      </div>
      {phase === 'loading' && <div style={{ fontSize: 11.5, color: '#a8a29e' }}>⏳ Playing {7 * 120} duels against the reference field…</div>}
      {phase === 'error' && <div style={{ fontSize: 12, color: '#fca5a5' }}>{errMsg}</div>}
      {phase === 'done' && result && (
        <>
          {(result.weak_against?.length > 0 || result.favoured_against?.length > 0) && (
            <div style={{ fontSize: 11.5, lineHeight: 1.5, marginBottom: 8 }}>
              {result.weak_against?.length > 0 && <div style={{ color: '#fca5a5' }}>Weak against: {result.weak_against.join(', ')}</div>}
              {result.favoured_against?.length > 0 && <div style={{ color: '#86efac' }}>Favoured against: {result.favoured_against.join(', ')}</div>}
            </div>
          )}
          {result.matchups.map((m) => <Row key={m.archetype} m={m} />)}
          <div style={{ fontSize: 10, color: '#57534e', marginTop: 6 }}>{result.fidelity}{result.computed_at ? ` · ${result.computed_at.replace('T', ' ')}` : ''}</div>
        </>
      )}
      {phase !== 'loading' && button(phase === 'done' ? '↻ Re-scout' : '🧭 Scout matchups')}
    </div>
  )
}
