"""Filesystem anchors for Myth Forge.

Every runtime path (assets, caches, generated art) resolves against the directory
this file lives in — NEVER against the process CWD.

Why this module exists: the app's data dirs used to be bare relative `Path("cache")`
/ `Path("generated_art")` / `Path("card_assets")` literals, so they landed wherever
the process happened to be started from. `manage.bat` cds into the repo first, so
that path is fine — but launching `python server.py` by absolute path (a shortcut,
an IDE, a scheduled task, a preview harness) silently forked the app's state: a
second `cache/` that never hit its own imported-deck entries (re-fetching decks and
Scryfall over the network every time), a second `generated_art/` the deck view
couldn't find art in, and `card_assets/` fonts/frames missing entirely. ~220 MB of
orphaned duplicates had accumulated in the user's home directory this way.

Use `app_path(...)` for anything the app ships or owns. User-facing data shared
across the Myth Suite (the collection CSV) belongs under `MYTHSUITE_DIR` instead —
see `collection.py`.
"""
from pathlib import Path

# The repo root: this file sits at the top level of the app.
APP_DIR = Path(__file__).resolve().parent


def app_path(*parts: str) -> Path:
    """An absolute path inside the app directory, independent of the CWD."""
    return APP_DIR.joinpath(*parts)
