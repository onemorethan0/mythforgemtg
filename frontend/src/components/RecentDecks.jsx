import { useEffect, useState } from 'react'

// "Recent decks" strip under the landing hub: jump back into a finished deck in
// one click. Renders nothing while loading, on error, or with zero finished decks.
// (Drafted by local LLM from spec, reviewed: effect uses a local cancelled flag —
// not state — so the fetch can't set state after unmount or loop the effect.)
export default function RecentDecks({ onLoad }) {
  const [decks, setDecks] = useState(null)
  const [loadingId, setLoadingId] = useState(null)

  useEffect(() => {
    let cancelled = false
    fetch('/api/decks')
      .then(res => res.json())
      .then(data => {
        if (cancelled || !Array.isArray(data)) return
        setDecks(
          data
            // finished decks carry status null; only in-progress builds say 'building'
            .filter(entry => entry.status !== 'building')
            .sort((a, b) => (b.built_at || 0) - (a.built_at || 0))
            .slice(0, 6)
        )
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  async function handleClick(entry) {
    if (loadingId) return
    setLoadingId(entry.job_id)
    try {
      const res = await fetch(`/api/deck/${entry.job_id}`)
      if (res.ok) {
        onLoad(entry.job_id, await res.json())
        return
      }
    } catch {}
    setLoadingId(null)
  }

  function fmtDate(ts) {
    if (!ts) return ''
    return new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  }

  if (!decks || decks.length === 0) return null

  return (
    <div style={{ maxWidth: 940, width: '100%', marginTop: 36 }}>
      <div style={{ fontSize: 12, color: '#78716c', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 10 }}>
        Recent decks
      </div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', justifyContent: 'center' }}>
        {decks.map(entry => {
          const name = entry.themed_name || entry.commander_name
          return (
            <button
              key={entry.job_id}
              aria-label={name}
              onClick={() => handleClick(entry)}
              style={{
                width: 150, background: '#1c1917', border: '1px solid #292524',
                borderRadius: 12, overflow: 'hidden', cursor: 'pointer', padding: 0,
                textAlign: 'left', fontFamily: 'inherit',
                opacity: loadingId === entry.job_id ? 0.5 : 1,
                transition: 'border-color 0.15s, opacity 0.15s',
              }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = '#ca8a04' }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = '#292524' }}
            >
              {entry.thumbnail ? (
                <img
                  src={entry.thumbnail}
                  alt=""
                  style={{ width: '100%', aspectRatio: '4/3', objectFit: 'cover', display: 'block', background: '#0c0a09' }}
                />
              ) : (
                <div style={{ width: '100%', aspectRatio: '4/3', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#0c0a09' }}>
                  <span style={{ fontSize: 28, color: '#292524' }}>🂠</span>
                </div>
              )}
              <div style={{ padding: '8px 10px' }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: '#f5f5f4', overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>
                  {name}
                </div>
                <div style={{ fontSize: 10, color: '#57534e', marginTop: 2 }}>
                  {fmtDate(entry.built_at)}
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
