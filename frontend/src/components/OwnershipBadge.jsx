// "Own N/M" badge + "I own this deck in paper" button in the commander banner's
// badge row. Extracted verbatim from StepDeck.jsx — same guard, same markup.
export default function OwnershipBadge({ deck, single, ownDeck, onAdd }) {
  if (single || !Array.isArray(deck.deck) || !deck.deck.some(c => 'owned' in c)) return null
  const cards = [deck.commander, ...deck.deck].filter(Boolean)
  const total = cards.length
  const own = cards.filter(c => c.owned).length
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
