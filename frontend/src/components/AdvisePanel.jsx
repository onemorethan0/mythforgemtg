import { useState } from 'react'

// "Suggest upgrades from my collection" (Myth Suite C4 advisor): asks MythGauntlet
// which OWNED cards measurably improve the deck — every suggestion is an ablation
// re-simulation delta, never popularity. (Drafted by local LLM from spec, reviewed:
// the draft's idle state returned an EMPTY div — the feature rendered nothing until
// you were already loading — and the delta chip stacked under the numbers.)
export default function AdvisePanel({ jobId }) {
  const [phase, setPhase] = useState('idle')
  const [result, setResult] = useState(null)
  const [errMsg, setErrMsg] = useState('')
  const [axis, setAxis] = useState('')

  async function run() {
    if (phase === 'loading') return
    setPhase('loading')
    try {
      const response = await fetch(`/api/deck/${jobId}/advise`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ axis: axis || null }),
      })
      if (response.ok) {
        setResult(await response.json())
        setPhase('done')
      } else {
        let d = 'HTTP ' + response.status
        try { d = (await response.json()).detail || d } catch {}
        setErrMsg(d)
        setPhase('error')
      }
    } catch {
      setErrMsg('Strength API unreachable')
      setPhase('error')
    }
  }

  // Plain function (not a nested component) so re-renders don't remount the select.
  const idleRow = (busy = false) => (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      {!busy && (
        <select
          value={axis}
          onChange={e => setAxis(e.target.value)}
          aria-label="Target axis"
          style={{
            padding: '6px 10px', borderRadius: 8, border: '1px solid #292524',
            background: '#1c1917', color: '#a8a29e', fontSize: 12, fontFamily: 'inherit',
          }}
        >
          <option value="">Weakest axis (auto)</option>
          <option value="consistency">Consistency</option>
          <option value="speed">Speed</option>
          <option value="resilience">Resilience</option>
          <option value="interaction">Interaction</option>
          <option value="ceiling">Ceiling</option>
        </select>
      )}
      <button
        onClick={run}
        disabled={busy}
        title="Test cards you own against this deck by re-simulation (MythGauntlet ablation advisor)"
        style={{
          padding: '7px 16px', borderRadius: 8, border: '1px solid #a16207',
          background: '#1c1408', color: '#eab308', fontWeight: 600, fontSize: 13,
          cursor: busy ? 'default' : 'pointer', fontFamily: 'inherit',
          opacity: busy ? 0.6 : 1,
        }}
      >
        {busy ? '⏳ Testing owned cards…' : '🧭 Suggest upgrades'}
      </button>
      {busy && (
        <span style={{ fontSize: 11, color: '#78716c' }}>
          re-simulating the deck once per owned candidate (~10-30s)
        </span>
      )}
    </div>
  )

  return (
    <div style={{ marginTop: 8 }}>
      {phase === 'idle' && idleRow()}
      {phase === 'loading' && idleRow(true)}
      {phase === 'error' && (
        <>
          {idleRow()}
          <div style={{
            fontSize: 12, color: '#fca5a5', background: '#1c0a0a',
            border: '1px solid #7f1d1d', borderRadius: 8, padding: '8px 12px', marginTop: 8,
          }}>
            {errMsg}
          </div>
        </>
      )}
      {phase === 'done' && result && (
        <>
          <div style={{
            background: '#0c0a09', border: '1px solid #a1620744',
            borderLeft: '3px solid #a16207', borderRadius: 10, padding: 14,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontWeight: 700, fontSize: 13, color: '#d6d3d1' }}>Upgrade advisor</span>
              <span style={{
                fontSize: 10.5, padding: '1px 8px', borderRadius: 20,
                background: '#a1620722', color: '#eab308', border: '1px solid #a16207',
              }}>
                measured, not popularity
              </span>
            </div>
            <div style={{ fontSize: 11.5, color: '#a8a29e', margin: '6px 0' }}>
              Target: {result.axis_label} — deck baseline {Math.round(result.baseline)}/100
            </div>
            {result.cut && (
              <div style={{ fontSize: 11, color: '#78716c', marginBottom: 8 }}>
                Each swap replaces your weakest card: {result.cut}
              </div>
            )}
            {result.suggestions.length > 0 ? (
              result.suggestions.map((s, i) => (
                <div
                  key={s.add}
                  style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '6px 8px', borderRadius: 6,
                    background: i % 2 === 0 ? '#1c1917' : 'transparent',
                  }}
                >
                  <span style={{ fontSize: 12.5, fontWeight: 600, color: '#f5f5f4' }}>{s.add}</span>
                  <span style={{ display: 'flex', alignItems: 'center' }}>
                    <span style={{ fontSize: 11.5, color: '#a8a29e' }}>
                      {Math.round(s.before)} → {Math.round(s.after)}
                    </span>
                    <span style={{
                      fontSize: 11, fontWeight: 700, padding: '1px 7px', borderRadius: 12,
                      background: '#14532d', color: '#86efac', marginLeft: 8,
                    }}>
                      +{s.delta.toFixed(1)}
                    </span>
                  </span>
                </div>
              ))
            ) : (
              <div style={{ fontSize: 12, color: '#a8a29e' }}>
                No owned card improved {result.axis_label} — evaluated {result.evaluated} of{' '}
                {result.candidates_that_fit} that fit this deck's colors.
              </div>
            )}
            <div style={{ fontSize: 10, color: '#57534e', marginTop: 8 }}>
              collection: {result.collection_source} · engine v{result.engine_version}
            </div>
          </div>
          <button
            onClick={() => setPhase('idle')}
            style={{
              background: 'none', border: '1px solid #292524', color: '#78716c',
              fontSize: 12, padding: '6px 14px', borderRadius: 8, marginTop: 8,
              cursor: 'pointer', fontFamily: 'inherit',
            }}
          >
            ↻ Try another axis
          </button>
        </>
      )}
    </div>
  )
}
