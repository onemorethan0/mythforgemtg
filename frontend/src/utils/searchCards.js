/**
 * Text search over a deck's card list (drafted by local LLM, reviewed).
 *
 * Matching rule: every whitespace-separated term in the query must be a
 * case-insensitive substring of the card's combined original name / themed
 * name / type line / rules text / flavor text.
 *
 * @param {Array} cards - card objects ({original_name, themed_name, type_line, oracle_text, flavor_text})
 * @param {string} query - user-typed search string
 * @returns {Array} matching cards in input order; the ORIGINAL array when the query is blank
 */
export function searchCards(cards, query) {
  if (!Array.isArray(cards)) return []
  if (!query || !query.trim()) return cards
  const terms = query.trim().toLowerCase().split(/\s+/)
  return cards.filter(card => {
    const haystack = [card.original_name, card.themed_name, card.type_line, card.oracle_text, card.flavor_text]
      .filter(field => typeof field === 'string')
      .join('\n').toLowerCase()
    return terms.every(term => haystack.includes(term))
  })
}
