"""Myth Forge HTTP API, split out of server.py (2026-10-24). `server:app` stays the entry point.

Imports form a DAG in this order; a module imports only from modules above it:

  logbuffer        stdout/stderr ring buffer behind /api/logs (the tee is installed by server.py)
  state            paths, the job store (_jobs/_progress), locks, rate limiting, SSE,
                   _load_deck_from_disk. Read paths as `state.RENDER_DIR`: tests rebind them.
  models           request models shared by the job workers and their routes
  collection_data  owned-card / owned-printing caches, price-enriched collection rows
  cards            deck.json card schema, provenance, mana costs, render keys, pips
  jobs_*           background workers: build, rebuild, regen + animate, retheme
  routes_*         APIRouter modules, included by server.py (order matters: first match wins)

When monkeypatching in a test, patch the module that LOOKS THE NAME UP, not where it is defined.
"""
