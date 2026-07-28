"""
Face reference management for personalised card art.

Uploaded photos are stored per-session under face_uploads/{face_key}/.
During art generation, is_human_card() decides whether each card's art
should feature the user's face — the commander always does.

Supported ComfyUI face-conditioning methods (auto-detected at init):
  pulid_flux       — PuLID for FLUX  (best quality, needs ComfyUI_PuLID_Flux node)
  ipadapter_faceid — IP-Adapter FaceID SDXL  (needs ComfyUI-IPAdapter-plus)
  reactor          — ReActor face swap post-process  (needs ComfyUI-ReActor)
  none             — no face nodes installed; adds textual face hint to prompt
"""
from __future__ import annotations

import re
from pathlib import Path

from app_paths import app_path

FACE_DIR = app_path("face_uploads")

# Maximum non-commander cards that receive face treatment.
# The commander always gets the face; this caps how many deck cards do.
# Keeping it low makes each appearance feel special rather than repetitive.
MAX_FACE_CARDS = 4

# ── Human-subtype detection ───────────────────────────────────────────────────

# MTG type-line words that imply a specific humanoid figure in the art.
# Deliberately conservative — non-humanoid legends (dragons, krakens, etc.)
# should NOT get face treatment even though they are Legendary Creatures.
_HUMANOID_TYPES: frozenset[str] = frozenset({
    "human", "warrior", "wizard", "shaman", "cleric", "knight", "rogue",
    "advisor", "soldier", "berserker", "monk", "druid", "ranger", "paladin",
    "assassin", "pirate", "noble", "artificer", "scout", "mercenary",
    "rebel", "samurai", "ninja", "archer", "spellcaster",
    "hero", "champion", "lord", "queen", "king", "prince", "princess",
    "god", "demigod", "avatar", "bard", "warlock", "sorcerer",
    "alchemist", "investigator", "renegade", "duelist",
    "elf", "dwarf", "goblin", "orc", "vampire", "zombie", "spirit",
    "angel", "demon", "faerie", "merfolk", "minotaur", "centaur", "satyr",
    "giant", "ogre", "troll", "djinn", "efreet", "siren",
})


def save_face_images(files: list[tuple[str, bytes]], session_key: str) -> list[Path]:
    """
    Persist uploaded face image bytes to disk.
    files: list of (original_filename, raw_bytes)
    Returns list of saved Paths in deterministic order.
    """
    dest = FACE_DIR / session_key
    dest.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, (filename, data) in enumerate(files):
        ext = Path(filename).suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"
        p = dest / f"face_{i:02d}{ext}"
        p.write_bytes(data)
        paths.append(p)
        print(f"  [face_ref] Saved face photo {i+1}: {len(data)//1024}KB -> {p.name}")
    return paths


def get_face_paths(session_key: str) -> list[Path]:
    """Return previously saved face image paths for a session key (sorted)."""
    d = FACE_DIR / session_key
    if not d.exists():
        return []
    return sorted(d.glob("face_*"))


def is_human_card(
    type_line: str,
    is_commander: bool = False,
) -> bool:
    """
    Return True if this card's art should feature the user's uploaded face.

    Priority rules (deliberately conservative to avoid overuse):
    1. Commander → always True.
    2. Legendary Creature WITH a humanoid subtype → True.
       (Legendary Dragon / Kraken / etc. → False — they're not people.)
    3. Non-legendary Creature with a humanoid subtype → True.
    4. Everything else → False.

    NOTE: Art-prompt keyword scanning was removed — it caused too many false
    positives (instants/sorceries whose scene mentions a "figure" or "warrior").
    Only type-line subtypes are authoritative for identifying a humanoid character.
    """
    if is_commander:
        return True

    tl = type_line.lower()

    # Any creature card — check for humanoid subtypes in the type line
    if "creature" in tl:
        for word in _HUMANOID_TYPES:
            if re.search(rf"\b{re.escape(word)}\b", tl):
                return True

    return False
