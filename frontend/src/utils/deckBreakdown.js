// Pure helpers for the Deck Breakdown panel.

// Cards the engine marked as synergising with the commander. A cached breakdown written
// before `commander_synergy` existed has no such field on its rows: those are skipped.
export function synergyRows(rows) {
  return (rows || [])
    .filter(r => r && r.commander_synergy)
    .map(r => ({
      name: r.name,
      reason: r.commander_synergy.reason || '',
      oneSided: !!r.commander_synergy.one_sided,
      treasure: Number(r.commander_synergy.treasure) || 0,
    }))
}
