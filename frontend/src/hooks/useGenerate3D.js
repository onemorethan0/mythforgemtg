import { useState } from 'react'

// ── 3D Commander generation ────────────────────────────────────────────────
// Owns the state + handler for "Generate 3D Model (STL)" on the deck-result
// screen. Extracted verbatim from StepDeck.jsx — behavior unchanged.
export function useGenerate3D(jobId) {
  const [state, setState]   = useState('idle')   // idle|loading|rmbg|trellis|converting|done|error
  const [msg, setMsg]       = useState('')
  const [stlUrl, setStlUrl] = useState(null)
  const [health, setHealth] = useState(null)     // null | {ok, message, hint, missing}

  async function generate() {
    if (state !== 'idle' && state !== 'error') return

    // Check health first
    setState('loading')
    setMsg('Checking 3D generation availability…')
    try {
      const hRes = await fetch('/api/3d-health')
      const h = await hRes.json()
      setHealth(h)
      if (!h.ok) {
        setState('error')
        setMsg(h.message)
        return
      }
    } catch (err) {
      setState('error')
      setMsg(`Health check failed: ${err.message}`)
      return
    }

    // Start generation
    setMsg('Queuing 3D generation…')
    try {
      const res = await fetch(`/api/deck/${jobId}/generate-3d`, { method: 'POST' })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        const detail = err.detail || {}
        setState('error')
        setMsg(typeof detail === 'string' ? detail : detail.message || `HTTP ${res.status}`)
        if (detail.hint) setHealth(h => ({ ...h, hint: detail.hint }))
        return
      }
      const { job_3d_id } = await res.json()

      // Open SSE stream
      setState('rmbg')
      setMsg('Removing background…')
      const es = new EventSource(`/api/deck/${jobId}/3d-status/${job_3d_id}`)
      // Tracks whether a terminal event (done / server-sent error) already
      // arrived, so the generic onerror connection handler doesn't clobber the
      // real message when the server closes the stream right after sending it.
      let settled = false

      es.addEventListener('progress', e => {
        const data = JSON.parse(e.data)
        const step = data.step || 'rmbg'
        const stateMap = { rmbg: 'rmbg', trellis: 'trellis', converting: 'converting' }
        setState(stateMap[step] || 'trellis')
        setMsg(data.msg || '')
      })

      es.addEventListener('done', e => {
        const data = JSON.parse(e.data)
        settled = true
        setState('done')
        setMsg('3D model ready!')
        setStlUrl(data.stl_url)
        es.close()
      })

      es.addEventListener('error', e => {
        // This listener fires for BOTH a backend-sent `event: error` (which has
        // e.data) and transport-level failures (no e.data). Only the former is a
        // real, final result — let transport errors fall through to es.onerror.
        if (!e.data) return
        let m = 'Generation failed'
        try { m = JSON.parse(e.data).msg || m } catch {}
        settled = true
        setState('error')
        setMsg(m)
        es.close()
      })

      es.onerror = () => {
        // Only a genuine connection drop — if the backend already told us the
        // outcome, keep that message instead of overwriting with a generic one.
        if (!settled) {
          setState('error')
          setMsg('Lost connection to the server before the 3D job reported a result. Check that the Myth Forge server and ComfyUI are still running.')
        }
        es.close()
      }
    } catch (err) {
      setState('error')
      setMsg(`Request failed: ${err.message}`)
    }
  }

  function reset() {
    setState('idle')
    setStlUrl(null)
    setMsg('')
  }

  return { state, msg, stlUrl, health, generate, reset }
}
