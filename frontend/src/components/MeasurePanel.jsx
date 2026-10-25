import { useEffect, useEffectEvent, useState } from 'react'
import SimStrengthPanel from './SimStrengthPanel'

// "Measure strength" on the result screen: runs the finished deck through the
// MythGauntlet simulation engine (POST /api/deck/{id}/measure) and renders the
// shared Power Profile panel. (Drafted by local LLM from spec, reviewed: the
// draft's run() guard was `state !== 'idle'`, which blocked Re-measure and
// retry-after-error — only 'loading' must be guarded.)
//
// `cached` = the deck's persisted last_measure ({simulation, date}) — when
// present the panel opens pre-filled with the stored profile and a measured-on
// date instead of making the user re-simulate. Mount with key={jobId} so
// navigating between decks resets the state machine.
//
// `cached.stale` (set by GET /api/deck/{id}) means the stored profile came from different
// engine scoring code. It is never shown as current: the panel re-measures on open and says
// so. Before this, a Sep 4 "Resilience 88" sat on the deck page beside the import preview's
// fresh 41 for the same list, with nothing to tell them apart.
export default function MeasurePanel({ jobId, cached }) {
  const hasCache = !!cached?.simulation?.power_profile
  const stale = hasCache && !!cached.stale
  // A stale cache opens straight into "loading" and fetches on mount (below); nothing is
  // set synchronously inside the effect, and `measure` is declared before it is used.
  const [state, setState] = useState(hasCache && !stale ? 'done' : stale ? 'loading' : 'idle')
  const [result, setResult] = useState(hasCache && !stale ? cached.simulation : null)
  const [measuredAt, setMeasuredAt] = useState(hasCache && !stale ? cached.date : null)
  const [errMsg, setErrMsg] = useState('')
  const refreshedStale = stale

  // A promise chain rather than async/await so every state update visibly sits behind the
  // fetch: it is called from a mount effect, and nothing here may set state synchronously.
  const measure = () =>
    fetch(`/api/deck/${jobId}/measure`, { method: 'POST' })
      .then(async response => {
        if (response.ok) {
          setResult(await response.json())
          setMeasuredAt(null)  // fresh numbers, not the cached ones
          setState('done')
        } else {
          let detail = `HTTP ${response.status}`
          try { detail = (await response.json()).detail || detail } catch {}
          setErrMsg(detail)
          setState('error')
        }
      })
      .catch(() => {
        setErrMsg('Strength API unreachable')
        setState('error')
      })

  const run = () => {
    if (state === 'loading') return
    setState('loading')
    measure()
  }

  // Mount-only re-measure of a stale cache; the effect event reads the current jobId.
  const remeasureStale = useEffectEvent(() => { if (stale) measure() })
  useEffect(() => { remeasureStale() }, [])

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
            {stale ? 'the engine changed since the last measurement - re-simulating' : 'playing a few thousand goldfish + resilience games'}
          </span>
        </div>
      )}
      {state === 'done' && (
        <>
          <SimStrengthPanel simulation={result} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8 }}>
            <button
              onClick={run}
              style={{
                padding: '7px 16px', borderRadius: 8,
                border: '1px solid #292524', background: 'none', color: '#78716c',
                fontWeight: 600, fontSize: 12, cursor: 'pointer', fontFamily: 'inherit',
              }}
            >
              ↻ Re-measure
            </button>
            {measuredAt && (
              <span style={{ fontSize: 11, color: '#57534e' }}>
                measured {new Date(measuredAt).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}
              </span>
            )}
            {refreshedStale && !measuredAt && (
              <span style={{ fontSize: 11, color: '#57534e' }}>
                re-measured: the strength engine changed since this deck was last measured
              </span>
            )}
          </div>
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
