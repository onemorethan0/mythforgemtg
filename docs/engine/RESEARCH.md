# Research — prior art survey and design conclusions

What exists, what it proves, and what MythGauntlet takes from each. (Survey date: 2026-07-05.)

## Rules engines

| Project | Notes | What we take |
|---|---|---|
| **Forge** ([Card-Forge/forge](https://github.com/Card-Forge/forge), Java) | 15+ years old; scripts the vast majority of cards; supports **headless AI-vs-AI matches** with per-game logs and W-L-D outcomes. AI is heuristic, opaque, and not built for measurement. | The cross-check oracle (SIMULATION.md). Proof that near-complete card scripting is achievable with a DSL + years of community effort — and that we shouldn't rebuild it; we should *measure against* it. |
| **XMage** (Java) | Full rules enforcement, online play focus; card code is Java classes; AI weaker than Forge's. | Evidence that "cards as code" scales worse than "cards as data" (Forge's script files). CCM chooses data. |
| **Manabrew** ([witchesofthehill/manabrew](https://github.com/witchesofthehill/manabrew), Rust) | Runs the Forge engine **in-process** via GraalVM native-image compilation. | The throughput path if the Forge adapter ever becomes hot. |
| **MTG Arena / MTGO** | Closed. Arena's rules engine (GRE) is the industrial benchmark; no API. | Nothing directly; confirms no shortcut exists. |

## Academic work

- **Ward & Cowling (2009), Cowling et al. ISMCTS line (2012)** — Monte Carlo search applied
  to MTG card play; **Information Set MCTS with determinization** handles hidden information.
  → Our T2 agent design (SIMULATION.md) is ISMCTS with determinization; this is proven ground.
- **Churchill, Biderman & Herrick (2019), "Magic: The Gathering is Turing Complete"**
  ([arXiv:1904.09828](https://arxiv.org/abs/1904.09828)) — optimal MTG play is undecidable in
  the general case. → The philosophical license for tiered fidelity: perfect simulation is
  impossible, so *calibrated approximation* is the correct ambition, not a compromise.
- **MTG-Causal-RL (2025)** ([arXiv:2605.06066](https://arxiv.org/abs/2605.06066)) — Gymnasium
  benchmark on MTG with partial observability and stochastic draws; five Standard archetypes;
  causal credit assignment (CGFA-PPO). → Validates MTG-as-RL-testbed; their credit-assignment
  framing parallels our card-value model (LEARNING.md §3a). Watch for reusable env design.
- **"Learning With Generalised Card Representations for MTG" (2024)**
  ([arXiv:2407.05879](https://arxiv.org/abs/2407.05879)) — card embeddings generalizing to
  unseen cards (55% human-pick prediction in draft). → Blueprint for the *learned* fallback:
  a card-embedding model could eventually replace hand-built effect vectors at rung 1.
- **UrzaGPT (2025)** ([arXiv:2508.08382](https://arxiv.org/abs/2508.08382)) — LoRA-tuned LLMs
  for draft pick prediction. → LLMs understand card function well enough to be useful — but as
  *offline* components. Reinforces the compile-time-LLM design (CARD_SEMANTICS.md).
- **Drafting RL surveys (2022)** ([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S1875952122000490))
  — deck-*building* RL exists mostly for arena/draft modes in simpler CCGs. Constructed-deck
  *evaluation* via simulation is essentially unoccupied academic territory.

## Power-level tools (the competition)

EDH Power Level (edhpowerlevel.com), Draftsim's bracket calculator, ScrollVault, Commander
Power Meter, cardsrealm, DeckCheck, edhmeta, BrackCheck… All share one architecture: static
decklist heuristics (Game Changer counts, combo DB lookups, curve stats, salt/price,
popularity weights). Documented community criticisms: subjective scales, card
misclassification, blindness to synergy/consistency/resilience, unvalidatable scores. One
tool claims "97% bracket accuracy" on 36 reference decks — n=36, self-graded, no methodology.

**None simulate games. None learn. That is the moat.**

Also notable: **CardCognition** ([reecevela/cardcognition](https://github.com/reecevela/cardcognition))
scrapes EDHREC for synergy-based suggestions — popularity-derived, no gameplay grounding;
and **pyedhrec** ([PyPI](https://pypi.org/project/pyedhrec/)) wraps the open
`json.edhrec.com` API we plan to use.

## Design conclusions (the "so what")

1. **Don't rebuild Forge; out-measure it.** Building card coverage took Forge a community and
   a decade. Our leverage is a *measurement instrument* (tiers + ratings + calibration) that
   no engine project ever built, using Forge as a free validator.
2. **Cards as data, compiled offline.** XMage's cards-as-code is a dead end for us; Forge's
   script DSL worked. The CCM + LLM compiler is that idea modernized: local LLMs make per-card
   compilation ~free, and validation gates make it trustworthy.
3. **ISMCTS is the right T2 agent.** Proven in MTG specifically; no research risk at MVP
   strength. Learned evaluation slots in later without changing the search skeleton.
4. **Credit assignment is the emerging research frontier** (causal RL paper) — our
   games-DB-first design means we accumulate exactly the data that line of work needs.
5. **The official Bracket system is our calibration gift**: it created shared labels
   (precon = 2, cEDH = 5) that make "deck strength" externally meaningful for the first time.
   Static tools squandered it; a simulator can actually fit it.

## Sources

- https://github.com/Card-Forge/forge — Forge engine
- https://slightlymagic.net/forum/viewtopic.php?f=52&t=20283 — Forge headless AI-vs-AI
- https://github.com/witchesofthehill/manabrew — Manabrew (Forge via GraalVM)
- https://cgomesu.com/blog/forge-xmage-mtg/ — Forge vs XMage comparison
- https://arxiv.org/abs/1904.09828 — MTG is Turing Complete
- https://arxiv.org/abs/2605.06066 — Causal RL for MTG benchmark
- https://arxiv.org/abs/2407.05879 — Generalised card representations
- https://arxiv.org/abs/2508.08382 — UrzaGPT
- https://magic.wizards.com/en/news/announcements/introducing-commander-brackets-beta — Brackets
- https://magic.wizards.com/en/news/announcements/commander-brackets-beta-update-february-9-2026 — Game Changers update (53 cards)
- https://edhrec.com/faq — EDHREC data/FAQ; https://pypi.org/project/pyedhrec/ — API wrapper
- https://edhpowerlevel.com/ , https://draftsim.com/edh-power-level/ , https://scrollvault.net/tools/commander-bracket/ — representative static calculators
