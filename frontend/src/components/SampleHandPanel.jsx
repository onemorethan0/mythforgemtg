import { useMemo, useState } from 'react'
import { buildLibrary, drawHand, isLand, openingHandOdds } from '../utils/sampleHand'

// "Draw a sample hand" — the playtest button every deck site has. Seven cards from the 99
// (command zone excluded), mulligan, draw the next card, plus the exact hypergeometric odds
// for lands in an opening seven. Client-only: nothing here calls the server.
export default function SampleHandPanel({ deck, jobId }) {
  const library = useMemo(() => buildLibrary(deck?.deck || [], deck?.partners || []),
    [deck?.deck, deck?.partners])
  const odds = useMemo(() => openingHandOdds(library), [library])
  const [state, setState] = useState(null)            // { hand, rest, mulls }

  if (library.length < 7) return null

  const draw7 = (mulls = 0) => setState({ ...drawHand(library), mulls })
  const drawOne = () => setState(s => s && s.rest.length
    ? { ...s, hand: [...s.hand, s.rest[0]], rest: s.rest.slice(1) } : s)
  const img = c => (c.has_render && c.render_key)
    ? `/api/deck/${jobId}/card-image/${c.render_key}` : (c.scryfall_img || '')
  const pct = p => `${Math.round(p * 100)}%`
  const handLands = state ? state.hand.filter(isLand).length : 0

  return (
    <div style={{ background: '#0c0a09', border: '1px solid #292524', borderRadius: 10, padding: 14, marginTop: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: '#d6d3d1', marginRight: 'auto' }}>🎴 Sample hand</div>
        <button style={btn} onClick={() => draw7(0)}>{state ? 'New hand' : 'Draw 7'}</button>
        {state && <button style={btn} onClick={() => draw7(state.mulls + 1)}>Mulligan</button>}
        {state && <button style={btn} onClick={drawOne} disabled={!state.rest.length}>Draw a card</button>}
      </div>
      <div style={{ fontSize: 11.5, color: '#78716c', marginTop: 6 }}>
        {odds.lands} lands in {odds.total} cards · opening seven holds 2–4 lands {pct(odds.p2to4Lands)} of
        the time, at least 3 lands {pct(odds.pAtLeast3Lands)}.
      </div>
      {state && (
        <>
          <div style={{ fontSize: 12, color: '#a8a29e', margin: '10px 0 6px' }}>
            {state.hand.length} cards · {handLands} land{handLands === 1 ? '' : 's'}
            {state.mulls > 0 && ` · mulligan ${state.mulls} (Commander's free first mulligan, then bottom ${Math.max(0, state.mulls - 1)})`}
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {state.hand.map((c, i) => (
              <div key={i} title={`${c.themed_name || c.original_name} (${c.original_name})`}
                   style={{ width: 92, textAlign: 'center' }}>
                {img(c)
                  ? <img src={img(c)} alt={c.original_name} loading="lazy"
                         style={{ width: 92, borderRadius: 5, display: 'block' }} />
                  : <div style={{ width: 92, height: 128, borderRadius: 5, background: '#292524' }} />}
                <div style={{ fontSize: 10, color: '#a8a29e', marginTop: 2, overflow: 'hidden',
                              textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.original_name}</div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

const btn = {
  padding: '6px 12px', borderRadius: 7, fontSize: 12, cursor: 'pointer', fontFamily: 'inherit',
  border: '1px solid #44403c', background: 'none', color: '#d6d3d1',
}
