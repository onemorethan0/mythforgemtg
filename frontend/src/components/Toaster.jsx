import { useEffect, useState } from 'react'
import { getToasts, subscribe, dismiss } from '../utils/toast'

// Non-blocking notifications, replacing native alert().
//
// alert() is modal, unstyled, uncopyable, and gone the moment it is dismissed — bad for a
// tool whose failures arrive during a 40-minute GPU build and whose error text is often a
// long server detail worth reading twice. Errors here persist until dismissed and can be
// copied; success/info fade. The store lives in utils/toast.js.

const btn = {
  background: 'none', border: 'none', color: '#78716c',
  cursor: 'pointer', fontSize: 11, fontFamily: 'inherit', padding: 0,
}
const ACCENT = { error: '#f87171', success: '#4ade80', info: '#eab308' }

export default function Toaster() {
  // Seeded from the store, so anything raised before this mounted is on screen at first
  // paint — no synchronous setState in an effect just to catch up.
  const [toasts, setToasts] = useState(getToasts)

  useEffect(() => subscribe(setToasts), [])

  // One timer per auto-dismissing toast, cleared on unmount and whenever the list changes.
  // Safe to re-run: ids are stable and dismiss() is idempotent.
  useEffect(() => {
    const timers = toasts
      .filter((t) => t.timeout)
      .map((t) => setTimeout(() => dismiss(t.id), t.timeout))
    return () => timers.forEach(clearTimeout)
  }, [toasts])

  if (!toasts.length) return null

  return (
    <div style={{
      position: 'fixed', right: 18, bottom: 18, zIndex: 9999,
      display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 420,
    }}>
      {toasts.map((t) => <Toast key={t.id} toast={t} />)}
    </div>
  )
}

function Toast({ toast }) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const t = setTimeout(() => setCopied(false), 1500)
    return () => clearTimeout(t)
  }, [copied])

  async function copy() {
    try {
      await navigator.clipboard.writeText(toast.message)
      setCopied(true)
    } catch {
      // clipboard is undefined on insecure origins and rejects when the document is not
      // focused. Say so in place rather than console.error-ing where nobody will look.
      setCopied('failed')
    }
  }

  return (
    <div
      role={toast.kind === 'error' ? 'alert' : 'status'}
      style={{
        background: '#1c1917', border: '1px solid #292524',
        borderLeft: `3px solid ${ACCENT[toast.kind] || ACCENT.info}`,
        borderRadius: 10, padding: '10px 12px', color: '#f5f5f4',
        fontSize: 13, lineHeight: 1.45, boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
        display: 'flex', gap: 10, alignItems: 'flex-start',
      }}
    >
      <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', flex: 1 }}>
        {toast.message}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-end' }}>
        <button style={btn} aria-label="Dismiss" onClick={() => dismiss(toast.id)}>✕</button>
        {toast.kind === 'error' && (
          <button style={btn} onClick={copy}>
            {copied === true ? 'Copied' : copied === 'failed' ? 'Copy failed' : 'Copy'}
          </button>
        )}
      </div>
    </div>
  )
}
