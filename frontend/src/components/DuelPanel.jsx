import { useEffect, useRef, useState } from 'react'

// "Test this deck head-to-head" (MythGauntlet Tier-2): paste a friend's decklist and
// get a simulated 1v1 win rate. Battlecruiser fidelity — an honest "how does it play
// against theirs?" read, not a bracket verdict (that's what the strength panel is for).
export default function DuelPanel({ jobId }) {
  const [open, setOpen] = useState(false)
  const [opponent, setOpponent] = useState('')
  const [oppName, setOppName] = useState('')
  const [phase, setPhase] = useState('idle')   // idle | loading | done | error
  const [result, setResult] = useState(null)
  const [errMsg, setErrMsg] = useState('')

  // `run()` is user-triggered (a button click), not mount-triggered — so unlike
  // RecentDecks.jsx's effect-scoped `let cancelled`, the flag has to live past the
  // click in a ref that an unmount-only effect flips. The simulation this kicks off
  // takes ~10-30s; without this, closing/navigating away from the panel mid-run and
  // coming back later still let the stale response call setState on a gone component.
  const cancelledRef = useRef(false)
  useEffect(() => () => { cancelledRef.current = true }, [])

  async function run() {
    if (phase === 'loading' || !opponent.trim()) return
    setPhase('loading'); setErrMsg('')
    try {
      const response = await fetch(`/api/deck/${jobId}/duel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ opponent, opponent_name: oppName || 'Opponent', games: 120 }),
      })
      if (response.ok) {
        const data = await response.json()
        if (cancelledRef.current) return
        setResult(data); setPhase('done')
      } else {
        let d = 'HTTP ' + response.status
        try { d = (await response.json()).detail || d } catch {}
        if (cancelledRef.current) return
        setErrMsg(d); setPhase('error')
      }
    } catch {
      if (cancelledRef.current) return
      setErrMsg('Strength API unreachable'); setPhase('error')
    }
  }

  const AC = '#c084fc'
  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        title="Simulate this deck 1v1 against a friend's decklist (MythGauntlet Tier-2)"
        style={{
          marginTop: 10, padding: '7px 16px', borderRadius: 8, border: `1px solid ${AC}66`,
          background: '#170c1c', color: AC, fontWeight: 600, fontSize: 13, cursor: 'pointer',
          fontFamily: 'inherit',
        }}
      >
        ⚔️ Test vs another deck
      </button>
    )
  }

  const r = result?.result
  const wa = result ? Math.round(result.winrate_a * 100) : 0
  const names = result?.names || ['Your deck', 'Opponent']

  return (
    <div style={{
      marginTop: 10, background: '#0c0a09', border: `1px solid ${AC}44`,
      borderLeft: `3px solid ${AC}`, borderRadius: 10, padding: 14,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ fontWeight: 700, fontSize: 13, color: '#d6d3d1' }}>Head-to-head test</span>
        <span style={{ fontSize: 10.5, padding: '1px 8px', borderRadius: 20, background: `${AC}22`, color: AC, border: `1px solid ${AC}` }}>
          MythGauntlet · Tier-2
        </span>
      </div>

      {phase !== 'done' && (
        <>
          <div style={{ fontSize: 11.5, color: '#a8a29e', marginBottom: 6 }}>
            Paste a friend's decklist (one card per line, Moxfield/plain — a
            <b> Commander:</b> line names the commander).
          </div>
          <input
            value={oppName}
            onChange={e => setOppName(e.target.value)}
            placeholder="Opponent name (optional)"
            style={{
              width: '100%', boxSizing: 'border-box', marginBottom: 6, padding: '6px 10px',
              borderRadius: 8, border: '1px solid #292524', background: '#1c1917',
              color: '#e7e5e4', fontSize: 12, fontFamily: 'inherit',
            }}
          />
          <textarea
            value={opponent}
            onChange={e => setOpponent(e.target.value)}
            placeholder={'Commander: Atraxa, Praetors\' Voice\n1 Sol Ring\n1 Cultivate\n…'}
            rows={6}
            style={{
              width: '100%', boxSizing: 'border-box', padding: '8px 10px', borderRadius: 8,
              border: '1px solid #292524', background: '#1c1917', color: '#e7e5e4',
              fontSize: 12, fontFamily: 'monospace', resize: 'vertical',
            }}
          />
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8 }}>
            <button
              onClick={run}
              disabled={phase === 'loading' || !opponent.trim()}
              style={{
                padding: '7px 16px', borderRadius: 8, border: `1px solid ${AC}88`,
                background: '#170c1c', color: AC, fontWeight: 600, fontSize: 13,
                cursor: (phase === 'loading' || !opponent.trim()) ? 'default' : 'pointer',
                opacity: (phase === 'loading' || !opponent.trim()) ? 0.5 : 1, fontFamily: 'inherit',
              }}
            >
              {phase === 'loading' ? '⏳ Simulating 120 games…' : '⚔️ Test matchup'}
            </button>
            <button
              onClick={() => setOpen(false)}
              style={{
                background: 'none', border: '1px solid #292524', color: '#78716c',
                fontSize: 12, padding: '6px 12px', borderRadius: 8, cursor: 'pointer',
                fontFamily: 'inherit',
              }}
            >
              Cancel
            </button>
          </div>
          {phase === 'error' && (
            <div style={{
              fontSize: 12, color: '#fca5a5', background: '#1c0a0a', border: '1px solid #7f1d1d',
              borderRadius: 8, padding: '8px 12px', marginTop: 8,
            }}>
              {errMsg}
            </div>
          )}
        </>
      )}

      {phase === 'done' && result && (
        <>
          <div style={{ fontSize: 22, fontWeight: 800, color: wa >= 50 ? '#4ade80' : '#f87171', marginBottom: 2 }}>
            {wa}% <span style={{ fontSize: 12, fontWeight: 600, color: '#a8a29e' }}>win rate for {names[0]}</span>
          </div>
          {/* win-rate bar */}
          <div style={{ height: 8, borderRadius: 5, background: '#7f1d1d', overflow: 'hidden', margin: '6px 0 10px' }}>
            <div style={{ height: '100%', width: `${wa}%`, background: '#16a34a' }} />
          </div>
          {r && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, fontSize: 11, marginBottom: 8 }}>
              <span style={{ padding: '2px 8px', borderRadius: 12, background: '#1c1917', border: '1px solid #44403c', color: '#a8a29e' }}>
                Record: <b style={{ color: '#e7e5e4' }}>{r.wins_a}–{r.wins_b}{r.draws ? `–${r.draws}` : ''}</b> ({r.games} games)
              </span>
              <span style={{ padding: '2px 8px', borderRadius: 12, background: '#1c1917', border: '1px solid #44403c', color: '#a8a29e' }}>
                Avg length: <b style={{ color: '#e7e5e4' }}>T{Math.round(r.avg_turns)}</b>
              </span>
              {r.combo_wins > 0 && (
                <span style={{ padding: '2px 8px', borderRadius: 12, background: '#1c1917', border: '1px solid #44403c', color: '#a8a29e' }}>
                  Combo kills: <b style={{ color: '#e7e5e4' }}>{r.combo_wins}</b>
                </span>
              )}
              {r.decked_losses > 0 && (
                <span title="Games where a player lost by drawing from an empty library" style={{ padding: '2px 8px', borderRadius: 12, background: '#1c1917', border: '1px solid #44403c', color: '#a8a29e' }}>
                  Decked out: <b style={{ color: '#e7e5e4' }}>{r.decked_losses}</b>
                </span>
              )}
            </div>
          )}
          <div style={{ fontSize: 10.5, color: '#78716c', lineHeight: 1.5 }}>
            Battlecruiser fidelity (T2 MVP) — a directional matchup read, not a bracket verdict.
            {result.engine_version ? ` engine v${result.engine_version}` : ''}
          </div>
          <button
            onClick={() => { setPhase('idle'); setResult(null) }}
            style={{
              background: 'none', border: '1px solid #292524', color: '#78716c', fontSize: 12,
              padding: '6px 14px', borderRadius: 8, marginTop: 10, cursor: 'pointer', fontFamily: 'inherit',
            }}
          >
            ↻ Test another deck
          </button>
        </>
      )}
    </div>
  )
}
