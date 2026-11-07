import { useEffect, useState } from 'react'

// Deck value and the cost to finish it (GET /api/deck/{id}/price, deck_price.py, B20).
// Priced offline at each card's cheapest nonfoil printing. Owned cards and basics add to the
// value but not to the cost to finish. A partial total is labelled partial, never shown bare.
const usd = n => `$${Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

export default function DeckPrice({ jobId }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let live = true
    fetch(`/api/deck/${jobId}/price`)
      .then(async r => {
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`)
        return r.json()
      })
      .then(d => { if (live) setData(d) })
      .catch(e => { if (live) setError(e.message || 'unavailable') })
    return () => { live = false }
  }, [jobId])

  if (error) return <div style={{ fontSize: 11, color: '#78716c', marginTop: 10 }}>Price unavailable: {error}</div>
  if (!data) return null
  const toBuy = data.cards.filter(c => !c.owned && c.usd != null)
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ height: 1, background: '#292524', margin: '0 0 12px' }} />
      <div style={{ fontSize: 12 }}>
        <span style={{ color: '#a8a29e' }}>Deck value: </span>
        <span style={{ fontWeight: 700, color: '#e7e5e4' }}>{usd(data.total)}</span>
        <span style={{ color: '#a8a29e' }}> · to finish: </span>
        <span style={{ fontWeight: 700, color: data.to_buy > 0 ? '#fbbf24' : '#86efac' }}>{usd(data.to_buy)}</span>
        <span style={{ color: '#78716c' }}> ({data.to_buy_cards} card{data.to_buy_cards === 1 ? '' : 's'} you don’t own)</span>
      </div>
      {!data.complete && (
        <div style={{ fontSize: 11, color: '#fbbf24', marginTop: 3 }}>
          Partial: no price for {data.unpriced.length} card{data.unpriced.length === 1 ? '' : 's'} ({data.unpriced.slice(0, 4).join(', ')}{data.unpriced.length > 4 ? '…' : ''}).
        </div>
      )}
      <div style={{ fontSize: 11, color: '#78716c', marginTop: 3 }}>
        Cheapest nonfoil printing, Scryfall market USD{data.prices_as_of_days != null ? `, prices ${data.prices_as_of_days < 1 ? 'from today' : `${Math.round(data.prices_as_of_days)} day(s) old`}` : ''}.
        {toBuy.length > 0 && (
          <button onClick={() => setOpen(o => !o)} style={{
            marginLeft: 6, background: 'none', border: 'none', color: '#fbbf24', cursor: 'pointer',
            fontSize: 11, fontFamily: 'inherit', padding: 0, textDecoration: 'underline',
          }}>{open ? 'hide' : 'what to buy'}</button>
        )}
      </div>
      {open && (
        <div style={{ marginTop: 6, maxHeight: 220, overflowY: 'auto' }}>
          {toBuy.map(c => (
            <div key={c.name} style={{ display: 'flex', fontSize: 11.5, color: '#d6d3d1', padding: '2px 0' }}>
              <span style={{ flex: 1 }}>{c.quantity > 1 ? `${c.quantity}× ` : ''}{c.name}</span>
              <span style={{ color: '#a8a29e' }}>{usd(c.usd * c.quantity)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
