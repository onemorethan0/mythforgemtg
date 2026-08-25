import { useState } from 'react'

// "I own this deck in paper" -> merge its cards into the collection so ownership
// badges reflect reality (idle | saving | done | error message). Extracted
// verbatim from StepDeck.jsx — behavior unchanged.
export function useOwnDeck(deck, jobId, onDeckChange) {
  const [ownDeck, setOwnDeck] = useState('idle')

  async function addDeckToCollection() {
    if (ownDeck === 'saving') return
    setOwnDeck('saving')
    try {
      const names = [deck.commander, ...(deck.deck || [])].filter(Boolean)
        .map(c => `${c.quantity || 1} ${c.original_name}`).join('\n')
      const r = await fetch('/api/collection/import', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: names, mode: 'merge' }),
      })
      if (!r.ok) throw new Error('import failed')
      // Re-fetch so the server recomputes `owned` for every card.
      const d = await fetch(`/api/deck/${jobId}`)
      if (d.ok) onDeckChange?.(await d.json())
      setOwnDeck('done')
    } catch {
      setOwnDeck('error')
    }
  }

  return { ownDeck, addDeckToCollection }
}
