import { useEffect, useRef, useState } from 'react'

/**
 * Server log viewer. Renders a header button that opens a modal showing the
 * tail of the in-memory server log buffer (GET /api/logs). Polls every 2s
 * while open and auto-scrolls to the newest line unless the user scrolls up.
 */
export default function LogViewer() {
  const [open, setOpen]       = useState(false)
  const [lines, setLines]     = useState([])
  const [error, setError]     = useState(null)
  const [autoScroll, setAuto] = useState(true)
  const preRef = useRef(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false

    async function fetchLogs() {
      try {
        const res = await fetch('/api/logs?lines=1000')
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        if (!cancelled) { setLines(data.lines || []); setError(null) }
      } catch (err) {
        if (!cancelled) setError(err.message)
      }
    }

    fetchLogs()
    const id = setInterval(fetchLogs, 2000)
    return () => { cancelled = true; clearInterval(id) }
  }, [open])

  // Auto-scroll to bottom when new lines arrive (unless user scrolled up).
  useEffect(() => {
    if (open && autoScroll && preRef.current) {
      preRef.current.scrollTop = preRef.current.scrollHeight
    }
  }, [lines, open, autoScroll])

  function onScroll(e) {
    const el = e.target
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    setAuto(atBottom)
  }

  function lineColor(line) {
    const l = line.toLowerCase()
    if (l.includes('traceback') || l.includes('error') || l.includes('exception') || l.includes('[err]')) return '#f87171'
    if (l.includes('warn')) return '#fbbf24'
    if (l.includes(' 200 ok') || l.includes('[ok]') || l.includes('ready')) return '#4ade80'
    return '#a8a29e'
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title="View server logs"
        style={{ fontSize: '13px', color: '#78716c', background: 'none', border: '1px solid #292524', borderRadius: 8, padding: '5px 12px', cursor: 'pointer' }}
      >
        📜 Logs
      </button>

      {open && (
        <div
          onClick={() => setOpen(false)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{ width: 'min(1000px, 95vw)', height: '80vh', background: '#0c0a09', border: '1px solid #292524', borderRadius: 12, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderBottom: '1px solid #292524' }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: '#eab308', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                Server Logs
              </span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                {!autoScroll && (
                  <button
                    onClick={() => { setAuto(true); if (preRef.current) preRef.current.scrollTop = preRef.current.scrollHeight }}
                    style={{ fontSize: 12, color: '#78716c', background: 'none', border: '1px solid #292524', borderRadius: 6, padding: '3px 10px', cursor: 'pointer' }}
                  >
                    ↓ Jump to latest
                  </button>
                )}
                <button
                  onClick={() => setOpen(false)}
                  style={{ fontSize: 18, color: '#78716c', background: 'none', border: 'none', cursor: 'pointer', lineHeight: 1 }}
                >
                  ✕
                </button>
              </div>
            </div>

            {error && (
              <div style={{ padding: '8px 16px', fontSize: 12, color: '#f87171', borderBottom: '1px solid #292524' }}>
                Couldn’t load logs: {error}
              </div>
            )}

            <pre
              ref={preRef}
              onScroll={onScroll}
              style={{ flex: 1, margin: 0, padding: '12px 16px', overflow: 'auto', fontSize: 12, lineHeight: 1.5, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
            >
              {lines.length === 0 && !error
                ? <span style={{ color: '#57534e' }}>No log output yet…</span>
                : lines.map((line, i) => (
                    <div key={i} style={{ color: lineColor(line) }}>{line}</div>
                  ))}
            </pre>
          </div>
        </div>
      )}
    </>
  )
}
