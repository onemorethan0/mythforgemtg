// "Own N/M" badge + "I own this deck in paper" button in the commander banner's
// badge row. Extracted verbatim from StepDeck.jsx — same guard, same markup.
//
// PHYSICAL count, not unique-entry count (same fix as StepDeck.jsx's own qty()) —
// an imported deck aggregates duplicate basics into one dict entry carrying
// quantity: 34, so counting cards.length undercounts. This badge used to sit
// right next to StepDeck's "N cards" badge (quantity-summed) in the same row
// and could show a SMALLER total for the identical deck a few pixels away —
// e.g. "Own 66/66 · all owned" beside "99 cards" — with nothing explaining the
// gap. Found in a 2026-09-15 sweep for this exact bug shape.
const qty = c => Math.max(1, parseInt(c?.quantity, 10) || 1)

export default function OwnershipBadge({ deck, single, ownDeck, onAdd }) {
  if (single || !Array.isArray(deck.deck) || !deck.deck.some(c => 'owned' in c)) return null
  const cards = [deck.commander, ...deck.deck].filter(Boolean)
  const total = cards.reduce((n, c) => n + qty(c), 0)
  const own = cards.filter(c => c.owned).reduce((n, c) => n + qty(c), 0)
  const proxies = total - own
  return (
    <>
      <span title={`${own} you own a real copy of · ${proxies} you don't own yet. Every card here has custom art.`}
        style={{ fontSize: 12, padding: '4px 12px', borderRadius: 20, fontWeight: 700,
          background: '#1c1408', border: '1px solid #a16207', color: '#fde047' }}>
        🎴 Own {own}/{total}{proxies ? ` · ${proxies} not owned` : ' · all owned'}
      </span>
      {proxies > 0 && (
        <button
          onClick={onAdd}
          disabled={ownDeck === 'saving' || ownDeck === 'done'}
          title="You own this deck in paper? Add its cards to your collection so they're marked owned."
          style={{ fontSize: 12, padding: '4px 12px', borderRadius: 20, fontWeight: 700,
            cursor: ownDeck === 'saving' || ownDeck === 'done' ? 'default' : 'pointer',
            fontFamily: 'inherit', background: '#0c1a0c', color: '#86efac',
            border: '1px solid #166534', opacity: ownDeck === 'saving' ? 0.6 : 1 }}>
          {ownDeck === 'saving' ? '…' : ownDeck === 'done' ? '✓ Added to collection'
            : ownDeck === 'error' ? '✕ Failed — retry' : '＋ I own this deck in paper'}
        </button>
      )}
    </>
  )
}
