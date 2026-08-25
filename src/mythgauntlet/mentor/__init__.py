"""Deck Mentor (docs/SPEC_deck_mentor.md, Phase 1): a tool-calling chat loop over a
real deck, gated so an LLM's reply can only assert what a tool call this turn actually
returned. CLI-only in this phase (`mythgauntlet mentor`) -- no server route, no UI; the
hard problem here is the loop and the gate, and that gets solved before either exists.
"""
