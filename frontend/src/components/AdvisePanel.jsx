import { useState } from 'react'
import CardHover from './CardHover'

// "Suggest upgrades from my collection" (Myth Suite C4 advisor): asks MythGauntlet
// which OWNED cards measurably improve the deck — every suggestion is an ablation
// re-simulation delta, never popularity. (Drafted by local LLM from spec, reviewed:
// the draft's idle state returned an EMPTY div — the feature rendered nothing until
// you were already loading — and the delta chip stacked under the numbers.)
export default function AdvisePanel({ jobId, onApplied }) {
  const [phase, setPhase] = useState('idle')
  const [result, setResult] = useState(null)
  const [errMsg, setErrMsg] = useState('')
  const [axis, setAxis] = useState('')
  const [applying, setApplying] = useState('')   // add-name of the in-flight swap
  const [applied, setApplied] = useState(null)   // the applied suggestion {add, cut, ...}
  const [applyErr, setApplyErr] = useState('')

  async function applySwap(s) {
    if (applying || applied) return
    setApplying(s.add); setApplyErr('')
    try {
      const response = await fetch(`/api/deck/${jobId}/apply-swap`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // Each suggestion carries its OWN cut (cut_pool>1) — use it, not a global cut.
        body: JSON.stringify({ add: s.add, cut: s.cut }),
      })
      if (response.ok) {
        const updated = await response.json()
        setApplied(s)
        onApplied?.(updated)   // App swaps in the modified deck; measure resets
      } else {
        let d = 'HTTP ' + response.status
        try { d = (await response.json()).detail || d } catch {}
        setApplyErr(d)
      }
    } catch {
      setApplyErr('Server unreachable')
    }
    setApplying('')
  }

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
            <div style={{ fontSize: 11, color: '#78716c', marginBottom: 8 }}>
              Each row: <span style={{ color: '#fca5a5' }}>cut ✕</span> → <span style={{ color: '#86efac' }}>add ✓</span>, with the measured axis gain.
            </div>
            {result.suggestions.length > 0 ? (
              result.suggestions.map((s, i) => (
                <div
                  key={s.add}
                  style={{
                    padding: '7px 8px', borderRadius: 6,
                    background: i % 2 === 0 ? '#1c1917' : 'transparent',
                    opacity: applied && applied.add !== s.add ? 0.45 : 1,
                  }}
                >
                 <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
                  {/* The swap, spelled out: OUT card → IN card (hover a name for its image) */}
                  <span style={{ display: 'flex', alignItems: 'center', gap: 7, minWidth: 0, flex: 1 }}>
                    <CardHover name={s.cut} style={{
                      fontSize: 12, color: '#fca5a5', textDecoration: 'line-through',
                      whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                      maxWidth: '42%', display: 'inline-block', verticalAlign: 'bottom',
                    }}>✕ {s.cut}</CardHover>
                    <span style={{ fontSize: 13, color: '#78716c' }}>→</span>
                    <CardHover name={s.add} style={{
                      fontSize: 12.5, fontWeight: 700, color: '#86efac',
                      whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                      display: 'inline-block', verticalAlign: 'bottom',
                    }}>✓ {s.add}</CardHover>
                  </span>
                  <span style={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
                    <span style={{ fontSize: 11.5, color: '#a8a29e' }}>
                      {Math.round(s.before)} → {Math.round(s.after)}
                    </span>
                    <span style={{
                      fontSize: 11, fontWeight: 700, padding: '1px 7px', borderRadius: 12,
                      background: '#14532d', color: '#86efac', marginLeft: 8,
                    }}>
                      +{s.delta.toFixed(1)}
                    </span>
                    {applied && applied.add === s.add ? (
                      <span style={{
                        fontSize: 11, fontWeight: 700, padding: '2px 10px', borderRadius: 8,
                        marginLeft: 8, background: '#14532d22', color: '#4ade80',
                        border: '1px solid #166534',
                      }}>
                        ✓ Applied
                      </span>
                    ) : (
                      <button
                        onClick={() => applySwap(s)}
                        disabled={!!applying || !!applied}
                        title={`Swap out ${s.cut} for ${s.add} in this deck, then re-measure`}
                        style={{
                          fontSize: 11, fontWeight: 700, padding: '2px 10px', borderRadius: 8,
                          marginLeft: 8, cursor: (applying || applied) ? 'default' : 'pointer',
                          background: '#0c1a0c', color: '#86efac', border: '1px solid #166534',
                          fontFamily: 'inherit', opacity: (applying || applied) ? 0.5 : 1,
                        }}
                      >
                        {applying === s.add ? '…' : 'Apply'}
                      </button>
                    )}
                  </span>
                 </div>
                 {s.reason && (
                   <div style={{ fontSize: 11, color: '#a8a29e', marginTop: 3, paddingLeft: 2 }}>
                     {s.reason}
                   </div>
                 )}
                </div>
              ))
            ) : (
              <div style={{ fontSize: 12, color: '#a8a29e' }}>
                No owned card improved {result.axis_label} by at least{' '}
                {(result.min_delta ?? 1).toFixed(1)} pts — evaluated {result.evaluated} of{' '}
                {result.candidates_that_fit} that fit this deck's colors.
                <div style={{ fontSize: 11, color: '#78716c', marginTop: 4 }}>
                  Smaller gains are simulation noise, so they're filtered out rather than
                  padding the list.
                </div>
              </div>
            )}
            {applyErr && (
              <div style={{
                fontSize: 11.5, color: '#fca5a5', background: '#1c0a0a',
                border: '1px solid #7f1d1d', borderRadius: 8, padding: '6px 10px', marginTop: 8,
              }}>
                Swap failed: {applyErr}
              </div>
            )}
            {applied && (
              <div style={{
                fontSize: 11.5, color: '#86efac', background: '#0c1a0c',
                border: '1px solid #166534', borderRadius: 8, padding: '6px 10px', marginTop: 8,
              }}>
                Swapped in <b>{applied.add}</b> for <b>{applied.cut}</b>. The deck changed, so hit
                {' '}<b>Measure strength</b> above to see the new profile — the other
                suggestions assumed the old list, so re-run the advisor for fresh ones.
              </div>
            )}
            <div style={{ fontSize: 10, color: '#57534e', marginTop: 8 }}>
              collection: {result.collection_source} · engine v{result.engine_version}
            </div>
          </div>
          <button
            onClick={() => { setPhase('idle'); setApplied(null); setApplyErr('') }}
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
