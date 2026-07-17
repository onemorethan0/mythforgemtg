import { useState } from 'react'
import SimStrengthPanel from './SimStrengthPanel'

// "Measure strength" on the result screen: runs the finished deck through the
// MythGauntlet simulation engine (POST /api/deck/{id}/measure) and renders the
// shared Power Profile panel. (Drafted by local LLM from spec, reviewed: the
// draft's run() guard was `state !== 'idle'`, which blocked Re-measure and
// retry-after-error — only 'loading' must be guarded.)
export default function MeasurePanel({ jobId }) {
  const [state, setState] = useState('idle')
  const [result, setResult] = useState(null)
  const [errMsg, setErrMsg] = useState('')

  const run = async () => {
    if (state === 'loading') return
    setState('loading')
    try {
      const response = await fetch(`/api/deck/${jobId}/measure`, { method: 'POST' })
      if (response.ok) {
        setResult(await response.json())
        setState('done')
      } else {
        let detail = `HTTP ${response.status}`
        try { detail = (await response.json()).detail || detail } catch {}
        setErrMsg(detail)
        setState('error')
      }
    } catch {
      setErrMsg('Strength API unreachable')
      setState('error')
    }
  }

  const mainBtn = (label, disabled = false) => (
    <button
      title="Simulate this deck with MythGauntlet - goldfish consistency, resilience, interaction, and a measured bracket"
      disabled={disabled}
      onClick={run}
      style={{
        padding: '7px 16px', borderRadius: 8, border: '1px solid #0ea5e9',
        background: '#0c2a4d', color: '#7dd3fc', fontWeight: 600, fontSize: 13,
        cursor: disabled ? 'default' : 'pointer', fontFamily: 'inherit',
        opacity: disabled ? 0.6 : 1,
      }}
    >
      {label}
    </button>
  )

  return (
    <div style={{ marginTop: 8 }}>
      {state === 'idle' && mainBtn('⚡ Measure strength')}
      {state === 'loading' && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {mainBtn('⏳ Simulating…', true)}
          <span style={{ fontSize: 11, color: '#78716c' }}>
            playing a few thousand goldfish + resilience games
          </span>
        </div>
      )}
      {state === 'done' && (
        <>
          <SimStrengthPanel simulation={result} />
          <button
            onClick={run}
            style={{
              marginTop: 8, padding: '7px 16px', borderRadius: 8,
              border: '1px solid #292524', background: 'none', color: '#78716c',
              fontWeight: 600, fontSize: 12, cursor: 'pointer', fontFamily: 'inherit',
            }}
          >
            ↻ Re-measure
          </button>
        </>
      )}
      {state === 'error' && (
        <>
          {mainBtn('⚡ Measure strength')}
          <div style={{
            fontSize: 12, color: '#fca5a5', background: '#1c0a0a',
            border: '1px solid #7f1d1d', borderRadius: 8, padding: '8px 12px', marginTop: 8,
          }}>
            {errMsg}
          </div>
        </>
      )}
    </div>
  )
}
