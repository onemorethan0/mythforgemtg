// Term definitions for the deck-power UI (Power Profile panel, bracket badges).
// ONE place so a term's wording can't drift between the panel, the compact badges, and
// wherever else it gets reused — the same "two structures must agree" discipline the
// engine side already applies to its own taxonomies (theme patterns, role targets).
//
// Kept short (one sentence, plain language) and honest about WHAT is measured and HOW —
// no marketing copy, matching the engine's own "measures and reports, decides nothing"
// tone. Bracket copy is reused verbatim from StepCommander.jsx's BRACKETS array rather
// than re-authored here, so the picker and the measured-result tooltip can't disagree.

export const BRACKET_TERMS = {
  1: { label: 'Exhibition', desc: 'Precon power. No Game Changers, extra turns, mass land destruction, or combos. Basics-heavy mana, theme-first.' },
  2: { label: 'Core', desc: 'Solid casual. Good synergies, no Game Changers or fast mana. A clean, fair deck.' },
  3: { label: 'Upgraded', desc: 'The popular bracket. Strong synergies + up to 3 Game Changers — a well-rounded competitive-casual deck.' },
  4: { label: 'Optimized', desc: 'High-powered: fast mana, tutors, and combos allowed. A strong goodstuff/value list — add your own combo lines to fully optimize.' },
  5: { label: 'cEDH', desc: 'Maximum power, no restrictions. A high-power goodstuff list with extra draw + interaction; a tuned tournament combo deck still needs hand-crafting.' },
}

// The five simulated Power Profile axes, plus the badges/chips that sit around them.
export const TERMS = {
  consistency: 'How reliably the deck executes its plan — mulligan quality and land-drop reliability across many simulated games. Not raw power; a deck can be very consistent and still slow.',
  resilience: "How much of the deck's plan survives a board wipe. Measured by simulating the SAME seed clean and wiped, so only the wipe's effect shows up in the difference.",
  interaction: 'Removal, counterspells, and board wipes the deck actually holds — weighted by how cheap and castable they are, not just counted.',
  ceiling: "The deck's best-case draw: a top-percentile lucky hand, including any detected storm go-off or alpha-strike finish. Reads low if a real finisher isn't one the engine can detect yet.",
  pod: 'Can this deck close a real ~4-player table, not just a 1-on-1 duel? A deck can read fast and consistent above and still barely dent a full pod — this axis is what actually answers that.',
  speed: 'How many turns until an unopposed goldfish kill, and how often the deck actually lands one inside the simulated horizon.',
  semantics_coverage: "The share of this deck's cards the engine can execute at full fidelity in simulation, rather than falling back to a simplified read of the oracle text.",
  game_changers: "Cards on Wizards' official list of the most powerful, format-defining cards in Commander — the main signal that pushes a deck past Bracket 2.",
  bracket_plays_up: "This deck sits on a bracket boundary the engine can't resolve from the card list alone (see the note below) — read the axes rather than trusting the badge alone.",
  storm_go_off: 'A detected spellslinger/storm engine that can close the game off the combat clock entirely, on a good draw.',
  overrun_alpha: 'A wide board plus a one-shot team pump that can end the game in a single combat step, on a good draw.',
  wincon_redundancy: "How many of a role's cards would need to be answered to fully stop that fast, non-combat kill — a lower number means the plan is more fragile to targeted interaction.",
}

// wincon_redundancy role keys (sim/wincon_redundancy.py — a small, fixed vocabulary).
export const WINCON_ROLE_TERMS = {
  storm_granter: 'Grants extra spell casts or copies, powering a storm-style kill.',
  burn_payoff: "Deals direct damage for each spell cast — the storm engine's actual kill condition.",
  overrun_finisher: 'A one-shot team pump that turns a wide board into lethal combat damage.',
  scaling_burn_finisher: 'A burn spell whose damage scales with mana spent — an X-spell style kill.',
}
