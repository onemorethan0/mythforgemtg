import { useEffect, useRef, useState } from 'react'
import { tracked } from '../utils/jobs'

// Pod check (D4, docs/DESIGN_table_brackets.md): will THIS deck and up to three others have a
// good game together? Each seat is a library deck or a pasted list; MythGauntlet measures each
// one (bracket + Denial/Pace/Inevitability) and checks the pod for power, pace, denial and
// predictability mismatches. A prediction from goldfish measurements and card roles -- the
// panel says so -- not a simulated pod game.

const STATUS = {
  ok: { icon: '✓', color: '#4ade80' },
  warn: { icon: '!', color: '#eab308' },
  fail: { icon: '✕', color: '#ef4444' },
}
const DIAL_COLORS = { Low: '#4ade80', Medium: '#eab308', High: '#ef4444', Fast: '#ef4444', Typical: '#a8a29e', Long: '#38bdf8' }
const CHECK_LABEL = { power: 'Power', pace: 'Pace', denial: 'Denial', inevitability: 'Predictability' }
const EMPTY_SEAT = { mode: 'library', jobId: '', text: '', name: '' }

const box = {
  width: '100%', boxSizing: 'border-box', padding: '6px 10px', borderRadius: 8,
  border: '1px solid #292524', background: '#1c1917', color: '#e7e5e4', fontSize: 12,
  fontFamily: 'inherit',
}

function Seat({ index, seat, library, onChange }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 4 }}>
        <span style={{ fontSize: 11, color: '#a8a29e', minWidth: 46 }}>Seat {index}</span>
        {['library', 'paste'].map((m) => (
          <button key={m} type="button" onClick={() => onChange({ ...seat, mode: m })}
            style={{
              fontSize: 10.5, padding: '1px 8px', borderRadius: 10, cursor: 'pointer', fontFamily: 'inherit',
              background: seat.mode === m ? '#0c2a4d' : 'transparent',
              color: seat.mode === m ? '#7dd3fc' : '#78716c',
              border: `1px solid ${seat.mode === m ? '#0ea5e9' : '#44403c'}`,
            }}>
            {m === 'library' ? 'From my library' : 'Paste a list'}
          </button>
        ))}
      </div>
      {seat.mode === 'library' ? (
        <select value={seat.jobId} onChange={(e) => onChange({ ...seat, jobId: e.target.value })} style={box}>
          <option value="">— empty seat —</option>
          {library.map((d) => (
            <option key={d.job_id} value={d.job_id}>
              {d.themed_name || d.commander_name}{d.themed_name && d.commander_name ? ` (${d.commander_name})` : ''}
            </option>
          ))}
        </select>
      ) : (
        <>
          <input value={seat.name} onChange={(e) => onChange({ ...seat, name: e.target.value })}
            placeholder="Whose deck? (optional)" style={{ ...box, marginBottom: 4 }} />
          <textarea value={seat.text} onChange={(e) => onChange({ ...seat, text: e.target.value })}
            rows={4} placeholder={'Commander: Ghired, Conclave Exile\n1 Sol Ring\n…'}
            style={{ ...box, fontFamily: 'monospace', resize: 'vertical' }} />
        </>
      )}
    </div>
  )
}

export default function PodCheckPanel({ jobId }) {
  const [open, setOpen] = useState(false)
  const [library, setLibrary] = useState([])
  const [seats, setSeats] = useState([EMPTY_SEAT, EMPTY_SEAT, EMPTY_SEAT])
  const [phase, setPhase] = useState('idle')   // idle | loading | done | error
  const [result, setResult] = useState(null)
  const [errMsg, setErrMsg] = useState('')
  const cancelledRef = useRef(false)
  useEffect(() => () => { cancelledRef.current = true }, [])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    fetch('/api/decks').then((r) => r.json()).then((rows) => {
      if (cancelled) return
      setLibrary((rows || []).filter((d) => d.job_id !== jobId && (d.card_count || 0) >= 60))
    }).catch(() => {})
    return () => { cancelled = true }
  }, [open, jobId])

  const filled = seats.filter((s) => (s.mode === 'library' ? s.jobId : s.text.trim()))

  function run() {
    if (phase === 'loading' || !filled.length) return undefined
    return tracked('Pod check', null, runInner)
  }

  async function runInner() {
    setPhase('loading'); setErrMsg('')
    try {
      const response = await fetch(`/api/deck/${jobId}/pod-fit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          seats: filled.map((s) => (s.mode === 'library' ? { job_id: s.jobId } : { text: s.text, name: s.name })),
        }),
      })
      if (cancelledRef.current) return
      if (response.ok) {
        setResult(await response.json()); setPhase('done')
      } else {
        let d = 'HTTP ' + response.status
        try { d = (await response.json()).detail || d } catch {}
        setErrMsg(d); setPhase('error')
      }
    } catch {
      if (cancelledRef.current) return
      setErrMsg('Strength API unreachable'); setPhase('error')
    }
  }

  const AC = '#34d399'
  if (!open) {
    return (
      <button onClick={() => setOpen(true)}
        title="Check whether this deck and your friends' decks will have a good game together"
        style={{
          marginTop: 10, marginLeft: 8, padding: '7px 16px', borderRadius: 8, border: `1px solid ${AC}66`,
          background: '#06231a', color: AC, fontWeight: 600, fontSize: 13, cursor: 'pointer', fontFamily: 'inherit',
        }}>
        🎲 Pod check
      </button>
    )
  }

  const fit = result?.fit
  return (
    <div style={{ marginTop: 10, background: '#0c0a09', border: `1px solid ${AC}44`, borderLeft: `3px solid ${AC}`, borderRadius: 10, padding: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ fontWeight: 700, fontSize: 13, color: '#d6d3d1' }}>Pod check</span>
        <span style={{ fontSize: 10.5, color: '#78716c' }}>will these decks have a good game together?</span>
      </div>

      {phase !== 'done' && (
        <>
          <div style={{ fontSize: 11.5, color: '#a8a29e', marginBottom: 8 }}>
            Seat 1 is this deck. Add up to three more from your library or paste a friend's list.
          </div>
          {seats.map((s, i) => (
            <Seat key={i} index={i + 2} seat={s} library={library}
              onChange={(next) => setSeats(seats.map((x, j) => (j === i ? next : x)))} />
          ))}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}>
            <button onClick={run} disabled={phase === 'loading' || !filled.length}
              style={{
                padding: '7px 16px', borderRadius: 8, border: `1px solid ${AC}88`, background: '#06231a', color: AC,
                fontWeight: 600, fontSize: 13, fontFamily: 'inherit',
                cursor: phase === 'loading' || !filled.length ? 'default' : 'pointer',
                opacity: phase === 'loading' || !filled.length ? 0.5 : 1,
              }}>
              {phase === 'loading' ? `⏳ Measuring ${filled.length + 1} decks…` : '🎲 Check this pod'}
            </button>
            <button onClick={() => setOpen(false)}
              style={{ background: 'none', border: '1px solid #292524', color: '#78716c', fontSize: 12, padding: '6px 12px', borderRadius: 8, cursor: 'pointer', fontFamily: 'inherit' }}>
              Cancel
            </button>
          </div>
          {phase === 'error' && (
            <div style={{ fontSize: 12, color: '#fca5a5', background: '#1c0a0a', border: '1px solid #7f1d1d', borderRadius: 8, padding: '8px 12px', marginTop: 8 }}>
              {errMsg}
            </div>
          )}
        </>
      )}

      {phase === 'done' && fit && (
        <>
          <div style={{
            fontSize: 12.5, fontWeight: 700, marginBottom: 8,
            color: fit.fun ? (fit.checks.some((c) => c.status === 'warn') ? '#eab308' : '#4ade80') : '#ef4444',
          }}>
            {fit.summary}
          </div>
          {fit.checks.map((c) => {
            const st = STATUS[c.status] || STATUS.ok
            return (
              <div key={c.key} style={{ display: 'flex', gap: 8, fontSize: 11.5, lineHeight: 1.45, marginBottom: 5 }}>
                <span style={{ color: st.color, fontWeight: 800, width: 12, textAlign: 'center' }}>{st.icon}</span>
                <span style={{ color: '#78716c', minWidth: 92 }}>{CHECK_LABEL[c.key] || c.key}</span>
                <span style={{ color: c.status === 'ok' ? '#a8a29e' : '#e7e5e4' }}>{c.text}</span>
              </div>
            )
          })}
          <div style={{ marginTop: 10, borderTop: '1px solid #292524', paddingTop: 8 }}>
            {result.seats.map((s, i) => (
              <div key={i} style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6, fontSize: 11.5, marginBottom: 5 }}>
                <span style={{ color: '#d6d3d1', minWidth: 160 }}>{i === 0 ? '★ ' : ''}{s.name}</span>
                <span style={{ color: '#a8a29e' }}>Bracket {s.bracket}</span>
                {[['denial', 'Denial'], ['pace', 'Pace'], ['inevitability', 'Inevitability']].map(([k, label]) => {
                  const d = s.dials?.[k]
                  if (!d) return null
                  const col = DIAL_COLORS[d.band] || '#a8a29e'
                  return (
                    <span key={k} title={(d.reasons || []).join('\n')}
                      style={{ fontSize: 10.5, padding: '1px 7px', borderRadius: 10, cursor: 'help', border: `1px solid ${col}`, color: '#d6d3d1', background: `${col}1a` }}>
                      {label} <b style={{ color: col }}>{d.band}</b>
                    </span>
                  )
                })}
              </div>
            ))}
          </div>
          <div style={{ fontSize: 10, color: '#57534e', marginTop: 6 }}>
            A prediction from each deck's simulated games and card roles, not a played pod game.
          </div>
          <button onClick={() => { setPhase('idle'); setResult(null) }}
            style={{ marginTop: 8, background: 'none', border: '1px solid #292524', color: '#78716c', fontSize: 12, padding: '6px 12px', borderRadius: 8, cursor: 'pointer', fontFamily: 'inherit' }}>
            ↻ Change seats
          </button>
        </>
      )}
    </div>
  )
}
