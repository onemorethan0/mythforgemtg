"""Paths and constants shared across the package."""

from __future__ import annotations

import os
from pathlib import Path

# src/mythgauntlet/config.py -> repo root (valid for editable installs / source checkouts)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

USER_AGENT = "MythGauntlet/0.1 (github.com/onemorethan0/mythgauntlet)"

# --- Myth Suite contracts (docs/SUITE_PLAN.md) — single source of truth ----------------
# The local machine's port registry: Odysseus :7000, MythForge :8000, llama-swap :8010,
# THIS strength API :8020, ComfyUI :8188. Forge reaches us via its MYTHGAUNTLET_URL env
# (default http://127.0.0.1:8020) — keep these in lock-step.
STRENGTH_API_HOST = "127.0.0.1"
STRENGTH_API_PORT = 8020


def suite_dir() -> Path:
    """The Myth Suite handoff directory (contract C1). Override: MYTHSUITE_DIR.

    MythScanner writes the collection export here; MythGauntlet and MythForge read it.
    The same MYTHSUITE_DIR override is honored by MythScanner's exporter.
    """
    override = os.environ.get("MYTHSUITE_DIR")
    return Path(override) if override else Path.home() / "Documents" / "MythSuite"


def suite_collection_path() -> Path:
    """Canonical collection file (Moxfield CSV) — contract C1."""
    return suite_dir() / "collection.csv"


def corpus_dir() -> Path:
    """Reference decklist corpus (committed to the repo, unlike data_dir caches)."""
    path = PROJECT_ROOT / "corpus" / "decks"
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    """Local cache directory for bulk card data (gitignored). Override: MYTHGAUNTLET_DATA."""
    override = os.environ.get("MYTHGAUNTLET_DATA")
    path = Path(override) if override else PROJECT_ROOT / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path
