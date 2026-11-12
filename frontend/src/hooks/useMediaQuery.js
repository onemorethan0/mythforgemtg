import { useSyncExternalStore } from 'react'

// Whether a CSS media query currently matches, kept live. Server-safe and test-safe: with no
// matchMedia (a non-browser environment) it reports false.
export function useMediaQuery(query) {
  const supported = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
  return useSyncExternalStore(
    cb => {
      if (!supported) return () => {}
      const m = window.matchMedia(query)
      m.addEventListener('change', cb)
      return () => m.removeEventListener('change', cb)
    },
    () => (supported ? window.matchMedia(query).matches : false),
    () => false,
  )
}
