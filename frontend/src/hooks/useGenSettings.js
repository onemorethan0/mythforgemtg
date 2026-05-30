import { useCallback, useState } from 'react'
import { DEFAULTS, stepFields } from '../config/genSettings'

// Persisted, schema-driven generation settings.
// Stores user overrides in localStorage so chosen defaults survive across
// sessions (mirrors the sessionStorage pattern App.jsx uses for the active job).
const LS_KEY = 'mtg_gen_settings'

function load() {
  try {
    const saved = JSON.parse(localStorage.getItem(LS_KEY) || '{}')
    return { ...DEFAULTS, ...saved }
  } catch {
    return { ...DEFAULTS }
  }
}

function save(next) {
  try { localStorage.setItem(LS_KEY, JSON.stringify(next)) } catch {}
  return next
}

export function useGenSettings() {
  const [values, setValues] = useState(load)

  const setField = useCallback((key, val) => {
    setValues(prev => save({ ...prev, [key]: val }))
  }, [])

  // Reset just the fields belonging to one step back to their schema defaults.
  const resetStep = useCallback((step) => {
    setValues(prev => {
      const next = { ...prev }
      for (const f of stepFields(step)) next[f.key] = f.default
      return save(next)
    })
  }, [])

  const resetAll = useCallback(() => {
    setValues(() => save({ ...DEFAULTS }))
  }, [])

  return { values, setField, resetStep, resetAll }
}
