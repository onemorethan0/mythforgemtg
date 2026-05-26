"""
Applies a user-supplied art/visual theme to a completed deck using Ollama (local LLM).

For each card generates:
  themed_name  — custom alternate name fitting the theme
  art_prompt   — Stable Diffusion prompt (25-40 words), landscape-composed, style-unified
  flavor_text  — 1-2 line flavour quote in the world's voice

Process:
  1. One quick call generates a deck-wide visual style guide (ensures art cohesion).
  2. Cards are processed in batches of 8 — the style guide is injected into every batch.
  3. After all batches, Ollama is unloaded from GPU so ComfyUI can claim the VRAM.

Model notes:
  qwen3:14b (default) — best JSON reliability + creative output at the 12 GB VRAM tier.
  Thinking mode is explicitly disabled ("think": false) so the model does not spend
  tokens on chain-of-thought reasoning before producing the JSON array; this cuts
  latency by ~30–40 % with no quality loss for structured creative tasks.
"""
from __future__ import annotations

import json
import re
import time
from typing import Optional
import requests

OLLAMA_BASE          = "http://127.0.0.1:11434"
OLLAMA_MODEL         = "qwen3:14b"
BATCH_SIZE           = 8
REQUEST_TIMEOUT      = 180
USE_ENHANCED_PROMPTS = True   # True = dual-anchor v2 pipeline  |  False = legacy v1

# ── Medium-tag stripper ───────────────────────────────────────────────────────
# Ollama reliably defaults to "dramatic fantasy oil painting, ..." regardless
# of the medium instruction (strong MTG training-data prior).  We strip the
# leading medium tag so the FLUX prompt isn't contaminated with the wrong style
# — image_gen.py's flux_prefix already establishes the correct art style.
_MEDIUM_PREFIX_RE = re.compile(
    r'^(?:'
    r'(?:dramatic\s+)?fantasy\s+(?:oil\s+)?painting|'
    r'oil\s+painting|'
    r'(?:digital\s+)?painting|'
    r'fantasy\s+illustration|'
    r'(?:photorealistic\s+)?digital\s+art|'
    r'(?:flat\s+colou?r\s+)?anime\s+(?:illustration|art|concept\s+art|[^,]{0,30})|'
    r'manga\s+art|'
    r'concept\s+art|'
    r'illustration|'
    r'photorealistic\s+(?:photography|illustration|digital\s+art)|'
    r'cinematic\s+photograph(?:y)?|'
    r'hyperrealistic\s+illustration|'
    r'watercolou?r\s+(?:illustration|painting)|'
    r'art\s+nouveau\s+illustration|'
    r'dark\s+gothic\s+(?:horror\s+)?illustration|'
    r'(?:dark\s+)?gothic\s+(?:horror\s+)?(?:illustration|painting)|'
    r'post-apocalyptic\s+concept\s+art|'
    r'cyberpunk\s+(?:concept\s+art|digital\s+painting)|'
    r'painterly\s+(?:fantasy\s+)?(?:illustration|painting)|'
    r'steampunk\s+illustration|'
    r'pixel\s+art|'
    r'(?:\w+-)*\w+\s+(?:illustration|painting|art|style)'  # Catch-all: "[adjective(s)]-[medium]"
    r')[,.\s]+',
    re.IGNORECASE,
)

# ── Model catalog ─────────────────────────────────────────────────────────────
# Curated set of LLMs the UI can offer.  Each entry describes a tradeoff so the
# user knows what they're picking.  The "installed" status is verified at
# runtime against Ollama's /api/tags response by list_available_llms().
#
# To add a new option: pull the model with `ollama pull <name>` and add an
# entry here.  The UI will surface it automatically the next time the page loads.
LLM_CATALOG: list[dict] = [
    {
        "key":         "qwen3:14b",
        "label":       "Qwen3 14B",
        "size_gb":     9.3,
        "tier":        "fast",
        "description": "Default — reliable JSON, decent creative prose. ~15–20s/batch.",
    },
    {
        "key":         "qwen3.6:latest",
        "label":       "Qwen 3.6 27B",
        "size_gb":     23.0,
        "tier":        "quality",
        "description": "Newest large Qwen. Best for card names + flavour text. ~90–120s/batch (27B).",
    },
    {
        "key":         "glm-4.7-flash:q4_K_M",
        "label":       "GLM 4.7 Flash",
        "size_gb":     19.0,
        "tier":        "quality",
        "description": "Zhipu AI 32B-class — distinct stylistic voice from Qwen. ~25–35s/batch.",
    },
    {
        "key":         "phi4:14b",
        "label":       "Phi-4 14B",
        "size_gb":     9.1,
        "tier":        "fast",
        "description": "Microsoft — tight, polished output. Less creative flair than Qwen.",
    },
    {
        "key":         "llama3.1:8b",
        "label":       "Llama 3.1 8B",
        "size_gb":     4.9,
        "tier":        "fastest",
        "description": "Meta — smallest/fastest option. Lower quality but ~5–10s/batch.",
    },
]


def list_available_llms() -> list[dict]:
    """
    Return the LLM_CATALOG with an `installed` flag per entry, computed live
    against the running Ollama instance.  Used by the UI to grey out options
    the user hasn't pulled yet.
    """
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        installed = {m["name"] for m in r.json().get("models", [])}
    except Exception:
        installed = set()

    out = []
    for entry in LLM_CATALOG:
        out.append({**entry, "installed": entry["key"] in installed})
    return out


# ── MTG color → visual palette mapping ───────────────────────────────────────
# Used to constrain each card's art palette to its mana identity so colors
# feel mechanically grounded (a W/R card reads holy-fire, not random pastels).

_MTG_COLOR_PALETTES: dict[str, str] = {
    "W": "white, ivory, silver, radiant gold, divine light",
    "U": "blue, azure, cerulean, arcane violet, ethereal cyan",
    "B": "black, charcoal, deep purple, necrotic green, bone white",
    "R": "red, crimson, orange, volcanic ash, smoldering ember",
    "G": "green, olive, earthy brown, natural amber, forest shadow",
}
_COLORLESS_PALETTE = "chrome, steel grey, crystal, void black, starlight silver"

def _color_palette_hint(color_identity: list[str]) -> str:
    """Build a terse palette string from a card's color identity list."""
    if not color_identity:
        return _COLORLESS_PALETTE
    parts = []
    for c in color_identity:
        p = _MTG_COLOR_PALETTES.get(c.upper())
        if p:
            parts.append(p)
    return " / ".join(parts) if parts else _COLORLESS_PALETTE


# ── Style guide ───────────────────────────────────────────────────────────────

_STYLE_GUIDE_SYSTEM = (
    "You are a creative art director for a Magic: The Gathering card set. "
    "Output only the requested content in one sentence. No explanations, no preamble."
)

def _expand_theme(theme: str, model: str = OLLAMA_MODEL) -> tuple[str, list[str]]:
    """
    Expand a short theme phrase into a richer world description plus a list of
    4 visually distinct zones within that world.  These zones are injected into
    every batch prompt so Ollama gives each card a DIFFERENT setting rather than
    repeating the same scene.

    Returns (expanded_theme_str, [zone1, zone2, zone3, zone4]).
    Falls back to (theme, []) on any failure.
    """
    if len(theme.strip()) > 150:
        return theme, []   # already detailed — skip expansion

    system = (
        "You are a visual world-building expert for fantasy card-game art. "
        "Output only what is requested. No preamble, no headers, no extra text."
    )
    user = (
        f'Expand this card-game world theme into a visual world description.\n'
        f'Theme: "{theme}"\n\n'
        f'Output EXACTLY this format (fill in the brackets, keep the labels):\n'
        f'DESCRIPTION: [2-sentence atmospheric description — dominant palette, '
        f'materials, overall mood, unique visual signature of this world]\n'
        f'ZONES: [zone1] | [zone2] | [zone3] | [zone4]\n\n'
        f'ZONES rules:\n'
        f'• Each zone is a specific LOCATION inside this world (5-10 words each)\n'
        f'• All 4 must look visually different from each other\n'
        f'• Vary: indoor/outdoor, time-of-day (dawn/noon/dusk/night), '
        f'weather, scale (intimate/vast)\n'
        f'• Example for "volcanic hellscape":\n'
        f'  "lava-filled magma cavern at night" | '
        f'"ash-grey ruined fortress at dawn" | '
        f'"sulfur geyser plains under noon sun" | '
        f'"obsidian bridge over molten falls"\n'
        f'Be highly specific to the "{theme}" world.'
    )
    payload = {
        "model":   model,
        "think":   False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0.85, "num_ctx": 768, "num_gpu": 99, "num_predict": 200},
    }
    try:
        resp = requests.post(f"{OLLAMA_BASE}/api/chat", json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        raw = resp.json().get("message", {}).get("content", "").strip()

        desc_m  = re.search(r'DESCRIPTION:\s*(.+?)(?=\nZONES:|$)', raw, re.DOTALL | re.IGNORECASE)
        zones_m = re.search(r'ZONES:\s*(.+?)$',                    raw, re.DOTALL | re.IGNORECASE)

        description = desc_m.group(1).strip()  if desc_m  else ""
        zones_raw   = zones_m.group(1).strip() if zones_m else ""
        zones = [z.strip().strip('"').strip("'")
                 for z in re.split(r'\s*\|\s*', zones_raw) if z.strip()]

        expanded = f"{theme} — {description}" if description else theme
        if len(zones) >= 2:
            print(f"  [themer] Theme expanded with {len(zones)} visual zones.")
            for z in zones:
                print(f"           • {z}")
            return expanded, zones[:4]
        print("  [themer] Theme expansion produced no zones, using description only.")
        return expanded, []
    except Exception as e:
        print(f"  [themer] Theme expansion failed ({e}), using original theme.")
    return theme, []


def _generate_style_guide(theme: str, commander_name: str,
                           commander_prompt: str = "",
                           style_guide_hint: str = "",
                           model: str = OLLAMA_MODEL) -> str:
    """
    One quick Ollama call that produces a single-sentence visual fingerprint for the
    entire deck. Every card's art_prompt is later prefixed with this, so all 100
    illustrations look like they come from the same hand and world.
    """
    # If the caller specified a target art style (e.g. anime, cyberpunk, art
    # nouveau), pick a style-matched example.  Without this, Ollama copies the
    # default painterly example and silently produces a painterly style guide
    # even when the user asked for anime — undermining the LoRA downstream.
    hint_lower = (style_guide_hint or "").lower()
    if "anime" in hint_lower or "manga" in hint_lower:
        example = ("Vibrant flat-colour anime illustration with bold cel-shaded "
                   "linework, saturated cyan-and-magenta neon palette, glowing "
                   "neon-rimmed shrines and chibi forest sprites flitting through "
                   "moonlit bamboo groves.")
    elif "cyberpunk" in hint_lower or "neon" in hint_lower:
        example = ("Digital painting in cyberpunk concept art style, vivid electric "
                   "magenta-and-teal neon light flooding rain-slicked streets with "
                   "colorful illumination, holographic billboards and chrome-jawed "
                   "mercenaries bathed in bright neon glow, well-lit vibrant scene.")
    elif "photorealistic" in hint_lower or "photograph" in hint_lower or "cinematic" in hint_lower:
        example = ("Cinematic photorealistic photography with sharp focus and "
                   "shallow depth of field, golden-hour warm palette, weathered "
                   "stone monastery walls and ash-cloaked monks under volumetric "
                   "morning light.")
    elif "mucha" in hint_lower or "nouveau" in hint_lower:
        example = ("Alphonse Mucha art nouveau illustration with flowing organic "
                   "linework, soft gold-and-jade palette and ornamental floral "
                   "borders, ethereal maidens framed by stylised vine arches.")
    elif "gritty" in hint_lower or "post-apocalyptic" in hint_lower or "desert" in hint_lower:
        example = ("Gritty post-apocalyptic concept art with dust-hazed amber "
                   "and rust palette, dramatic side lighting and deep shadows, "
                   "salvaged-metal raiders silhouetted against cracked-red desert "
                   "wastes.")
    else:
        example = ("Painterly fantasy oil painting with rich atmospheric "
                   "lighting, deep jewel-tone palette, ancient cathedral ruins "
                   "and tarnished-bronze warriors framed in moody chiaroscuro.")

    medium_line = (
        f"\nArt style/medium to use (MANDATORY — the style guide MUST be in this medium): {style_guide_hint}"
        if style_guide_hint else ""
    )
    prompt = (
        f"Write a ONE-sentence visual art style guide for a Magic: The Gathering card set.\n"
        f"World theme: {theme}\n"
        f"Protagonist: {commander_name}"
        + (f"\nCommander's personal look: {commander_prompt}" if commander_prompt else "")
        + medium_line
        + f"\n\nDescribe: art medium (which MUST match the style above), dominant color palette "
        f"(honour any specific colors the user mentioned), lighting style, overall mood, "
        f"AND 1-2 iconic visual elements unique to this specific theme "
        f"(e.g. distinctive architecture, materials, creatures, or iconography "
        f"that would immediately signal '{theme}' to a viewer).\n"
        f"Example (in the requested style): '{example}'\n"
        f"Style guide:"
    )
    payload = {
        "model": model,
        "think": False,
        "messages": [
            {"role": "system", "content": _STYLE_GUIDE_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.85, "num_ctx": 512, "num_gpu": 99, "num_predict": 90},
    }
    try:
        resp = requests.post(f"{OLLAMA_BASE}/api/chat", json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        raw   = resp.json().get("message", {}).get("content", "").strip()
        guide = raw.split("\n")[0].strip().strip('"').strip("'")
        if 20 < len(guide) < 260:
            print(f"  [themer] Style guide: {guide}")
            return guide
    except Exception as e:
        print(f"  [themer] Style guide generation failed ({e}), using fallback.")
    # Use the caller-supplied hint as fallback so cyberpunk/anime/etc. presets
    # don't silently fall back to a generic oil-painting style that poisons every
    # card's art prompt with the wrong medium language (e.g. "deep colors,
    # dramatic brushwork" for a neon-lit cyberpunk deck → near-black FLUX output).
    return style_guide_hint or "Dramatic fantasy oil painting with rich atmospheric lighting, deep colors, and detailed brushwork."


# ── Prompt builder ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are a JSON API for a Magic: The Gathering card customization tool. "
    "Given a visual theme and a list of cards, you output a JSON array with themed names, "
    "art descriptions, and flavor text for each card. "
    "Output only valid JSON. No explanations, no refusals, no markdown — only the JSON array."
)

# Maps MTG keywords → visual cues the artist should show
_KEYWORD_VISUALS: dict[str, str] = {
    "Flying":          "airborne, wings spread or levitating",
    "Trample":         "unstoppable force, crushing through",
    "Deathtouch":      "venomous, necrotic aura, lethal touch",
    "Lifelink":        "radiant healing glow, life energy flowing",
    "Vigilance":       "alert, watchful stance, eyes open",
    "Haste":           "blurred motion, speed lines, explosive movement",
    "First Strike":    "weapon already drawn, striking first",
    "Double Strike":   "dual weapon wielder, rapid dual attack",
    "Indestructible":  "impervious, armored, divine shield aura",
    "Hexproof":        "magical barrier surrounding the subject",
    "Menace":          "intimidating presence, two opponents shrinking back",
    "Reach":           "elongated limbs or weapon, reaching upward",
    "Defender":        "defensive stance, fortified position, wall-like",
    "Flash":           "sudden appearance, surprise, materialized from shadow",
    "Prowess":         "glowing with channeled spell energy",
    "Equip":           "being fitted with weapon or armor",
    "Convoke":         "crowd of creatures lending power, hands raised together",
    "Persist":         "undying, rising again, rebirth",
    "Undying":         "returning from death, spectral second life",
    "Regenerate":      "wounds closing, body reforming",
    "Ward":            "magical protection ward, glowing rune shield",
    "Infect":          "corrupting darkness, toxic spreading aura",
    "Wither":          "withering touch, aging on contact",
    "Exalted":         "bathed in golden light when alone",
    "Cascade":         "chain of magical bursts erupting in sequence",
    "Annihilator":     "reality-consuming void, dimensional destruction",
    "Phasing":         "flickering between planes, semi-transparent",
    "Flanking":        "cavalry charge, attacking from the side",
    "Banding":         "united front, shoulder-to-shoulder warriors",
    "Bushido":         "warrior discipline, katana drawn, battle focus",
    "Ninjutsu":        "shadow-step, replacing another in combat",
    "Splice":          "combining two spells into one surge of energy",
    "Sunburst":        "absorbing colors of mana, prismatic radiance",
    "Affinity":        "surrounded by its artifact kin",
    "Modular":         "mechanically transferring power via counters",
    "Offering":        "sacrifice ritual, dark altar",
    "Champion":        "exiling another for temporary power",
    "Evoke":           "spirit briefly summoned then fading",
    "Hideaway":        "secret revealed beneath the card, hidden power",
    "Reinforce":       "granting strength via resource, adding power",
    "Unearth":         "clawing from the earth, undead rising",
    "Retrace":         "discarding land to recast, dust returning to earth",
    "Landfall":        "reacting to land touching down, earth shaking",
    "Proliferate":     "spreading corruption or enhancement to all",
    "Battle cry":      "rallying warriors forward, shouting charge",
    "Morbid":          "fueled by death nearby",
    "Miracle":         "divine intervention, bolt from the heavens",
    "Overload":        "massive area devastation, spell consuming everything",
    "Scavenge":        "picking parts from the fallen",
    "Cipher":          "encoded in a warrior, secret carried within",
    "Evolve":          "transforming, growing more powerful",
    "Extort":          "draining life as tribute, sinister hand outstretched",
    "Fuse":            "two halves snapping together into one power",
    "Tribute":         "offering something valuable or accepting punishment",
    "Inspired":        "awakening after tapping, a moment of revelation",
    "Bestow":          "descending as an enchantment onto another creature",
    "Constellation":   "stars aligning, enchantment magic activating",
    "Dash":            "lightning-fast strike-and-retreat",
    "Exploit":         "sacrificing a creature for dark gain",
    "Menace":          "threatening posture, two opponents recoiling",
    "Renown":          "becoming legendary, standing proud and battle-scarred",
    "Skulk":           "skulking low in shadows, unseen predator",
    "Emerge":          "erupting from a sacrificed host",
    "Escalate":        "each mode adding more power, stacking energy",
    "Meld":            "two cards fusing into one monstrous form",
    "Crew":            "multiple creatures boarding a vehicle together",
    "Fabricate":       "assembling servo tokens or adding power counters",
    "Improvise":       "using artifacts as mana, mechanical ingenuity",
    "Revolt":          "triggered by sacrifice, fueled by loss",
    "Enrage":          "taking damage and responding with fury",
    "Raid":            "empowered by attacking this turn",
    "Embalm":          "mummification ritual, preserved in gold",
    "Eternalize":      "eternal zombie risen in black and gold",
    "Afflict":         "draining life when blocked, pain transferred",
    "Exert":           "pushing beyond limits, exhausted after",
    "Explore":         "surveying terrain, revealing the top of the library",
    "Mentor":          "teaching a smaller creature, guiding hand",
    "Undergrowth":     "fueled by creatures in the graveyard",
    "Jump-start":      "casting again by discarding a card",
    "Spectacle":       "triggered by opponent taking damage, audience watching",
    "Riot":            "chaos energy, haste or growing with a counter",
    "Adapt":           "mutating with +1/+1 counters when able",
    "Amass":           "creating zombie army token, growing horde",
    "Escape":          "clawing out of the graveyard, returning from exile",
    "Mutate":          "merging with another creature, hybrid form",
    "Companion":       "called from outside the game, loyal partner",
    "Foretell":        "hiding a card in exile for later",
    "Boast":           "celebrating after attacking",
    "Disturb":         "spirit returning from graveyard transformed",
    "Cleave":          "stripping away text to reveal brutal core effect",
    "Daybound":        "transforming at dawn, sun-sensitive",
    "Nightbound":      "transforming at nightfall, darkness-driven",
    "Coven":           "three witches of different power gathering",
    "Blitz":           "haste at cost, sacrificed at end of turn",
    "Casualty":        "sacrifice required as a cost",
    "Connive":         "drawing then discarding, rat-like cunning",
    "Enlist":          "recruiting an untapped creature to bolster attack",
    "Read ahead":      "saga chapters chosen freely, knowledge of fate",
    "Ravenous":        "consuming +1/+1 counters equal to mana spent",
    "Spree":           "choosing modes on a modal spell, tactical selection",
    "Offspring":       "creating a smaller token copy",
    "Saddle":          "mounting a creature to ride it as a mount",
    "Plot":            "scheming, exiling to cast later for free",
}

def _mechanic_summary(card: dict) -> str:
    """
    Build a concise mechanic hint from a card's oracle text, keywords, and stats.
    This is injected into the batch prompt so the LLM can ground the art in what
    the card actually does rather than just its name.
    """
    parts: list[str] = []

    # ── Keywords → visual cues ────────────────────────────────────────────────
    kws = card.get("keywords", []) or []
    visual_kws: list[str] = []
    for kw in kws[:5]:  # cap at 5 keywords to stay terse
        hint = _KEYWORD_VISUALS.get(kw)
        if hint:
            visual_kws.append(hint)
        else:
            visual_kws.append(kw.lower())
    if visual_kws:
        parts.append("; ".join(visual_kws))

    # ── Power / toughness → scale hint ────────────────────────────────────────
    power     = card.get("power")
    toughness = card.get("toughness")
    if power is not None and toughness is not None:
        try:
            p = int(power)
            if p >= 7:
                parts.append("massive, towering, earth-shaking")
            elif p >= 4:
                parts.append("powerful, imposing build")
            elif p <= 1:
                parts.append("small, nimble, wiry")
        except ValueError:
            pass  # '*' or 'X' — skip

    # ── Oracle text → effect hint ─────────────────────────────────────────────
    oracle = card.get("oracle_text") or ""
    # Strip reminder text in parentheses
    oracle = re.sub(r"\([^)]+\)", "", oracle).strip()
    if oracle:
        # Take first non-blank line, first sentence
        first_line = next((ln.strip() for ln in oracle.split("\n") if ln.strip()), "")
        first_sent = first_line.split(".")[0].strip()
        # Remove mana symbols like {2}{U}
        first_sent = re.sub(r"\{[^}]+\}", "", first_sent).strip()
        # Trim to 80 chars
        if len(first_sent) > 80:
            first_sent = first_sent[:77] + "…"
        if len(first_sent) > 8:
            parts.append(first_sent)

    return " | ".join(parts) if parts else ""


# ── Card soul classifier (v2 enhanced pipeline) ───────────────────────────────
#
# Each entry: (role_label, soul_phrase, [oracle_regex_patterns])
# Patterns are tested against lowercased oracle text (reminder text stripped).
# First match wins — order from most specific to most general.
#
_SOUL_PATTERNS: list[tuple[str, str, list[str]]] = [
    # Board wipes
    ("WIPE",         "divine judgment, everything obliterated simultaneously",
     [r"destroy all", r"exile all creatures", r"each creature .{0,30}(dies|is destroyed)"]),
    # Single target exile
    ("EXILE",        "target banished into the void, erased from existence",
     [r"exile target"]),
    # Single target destroy
    ("REMOVAL",      "target eliminated, struck down with finality",
     [r"destroy target"]),
    # Direct damage spells
    ("BURN",         "sudden violent energy striking the target, impact erupting",
     [r"deals? \d+ damage to (any target|target (creature|player|planeswalker))"]),
    # Counterspells
    ("COUNTER",      "spell shattered mid-cast, a moment of denial, magic interrupted",
     [r"counter target spell", r"counter target (instant|sorcery|creature)"]),
    # Bounce
    ("BOUNCE",       "target snapped away, unsummoned, returned to nothing",
     [r"return target .{0,40} to (its|their) owner.s hand"]),
    # Reanimation
    ("REANIMATE",    "rising from death, dragged back from the grave, second life",
     [r"return .{0,30} from (your |a |the )?(graveyard|exile) to the battlefield",
      r"put .{0,30} from (your |a |the )?graveyard (onto|into) the battlefield"]),
    # Mill
    ("MILL",         "memories dissolving, mind eroded, library crumbling to dust",
     [r"mill \d+", r"put the top \d+ cards?.{0,20}graveyard"]),
    # Card draw
    ("DRAW",         "visions flooding in, arcane revelation, knowledge surging forth",
     [r"draw \d+ cards?", r"you may draw", r"draw a card"]),
    # Tutor / search
    ("TUTOR",        "searching the depths, ancient secret revealed, sought knowledge found",
     [r"search your library", r"look at the top \d+ cards"]),
    # Token creation
    ("TOKEN",        "summoning ritual, conjured forces multiplying, new life called forth",
     [r"create \d+", r"put \d+ .{0,20}token", r"creates? (a|an) \d*/\d*"]),
    # Ramp / mana
    ("RAMP",         "power channeled and amplified, resources surging into the hands",
     [r"\{t\}.*add .{0,20}mana", r"add \{", r"search.{0,30}basic land",
      r"puts? .{0,30}land .{0,20}onto the battlefield"]),
    # Life gain engines
    ("LIFEGAIN",     "healing radiance pouring in, life energy restored, warmth returning",
     [r"you gain \d+ life", r"gain \d+ life", r"gains? you \d+ life"]),
    # Extra turns / near-win conditions
    ("FINISHER",     "overwhelming game-ending force, the decisive moment, victory at hand",
     [r"take (an )?extra turn", r"win the game", r"deals? .{0,20}damage to each opponent"]),
    # Pump / buff
    ("PUMP",         "power surging into the subject, strength amplified beyond natural limits",
     [r"(gets?|gain) \+\d+/\+\d+", r"target creature gets? \+"]),
    # Equipment attach
    ("EQUIP",        "weapon or armor granted, subject empowered by crafted gear",
     [r"equip"]),
    # Sacrifice engines
    ("SACRIFICE",    "dark ritual, something given to gain greater power",
     [r"sacrifice (a |an |target )?(creature|permanent)", r"as an additional cost.{0,30}sacrifice"]),
    # Discard
    ("DISCARD",      "minds stripped bare, secrets torn away, loss and despair",
     [r"(target player |each player |each opponent )?discards?"]),
    # Counter / proliferate
    ("PROLIFERATE",  "power spreading to all, counters multiplying across the field",
     [r"proliferate"]),
]

# CMC → drama level hint injected into soul phrase
_CMC_WEIGHT: list[tuple[int, str]] = [
    (7, "game-ending scale"),
    (5, "powerful, high-stakes"),
    (3, "mid-range impact"),
    (1, "quick and precise"),
]

def _card_soul(card: dict) -> tuple[str, str]:
    """
    Returns (role_label, soul_phrase) capturing the card's mechanical identity
    as an evocative visual directive for the art prompt.

    The soul phrase is intentionally written as a scene seed — a short description
    of what the card *does* expressed as visual action, not mechanics text.
    """
    oracle   = (card.get("oracle_text") or "").lower()
    oracle   = re.sub(r"\([^)]+\)", "", oracle)          # strip reminder text
    type_line = (card.get("type_line") or "").lower()
    keywords  = {k.lower() for k in (card.get("keywords") or [])}
    cmc       = float(card.get("cmc") or 0)
    power_raw = card.get("power")

    # ── Type shortcuts (non-spell permanents) ────────────────────────────────
    if "land" in type_line and "creature" not in type_line:
        return ("LAND", "a place of power, landscape defining its own identity")
    if "equipment" in type_line:
        return ("EQUIPMENT", "weapon or armor granting power, the wielder transformed")
    if "vehicle" in type_line:
        return ("VEHICLE", "powerful machine crewed and driven into battle")
    if "artifact" in type_line and "creature" not in type_line:
        return ("ARTIFACT", "constructed marvel, engineered power, object of significance")
    if "enchantment" in type_line and "creature" not in type_line:
        if "saga" in type_line:
            return ("SAGA", "unfolding story, sequential events transforming the world")
        return ("ENCHANTMENT", "persistent magic binding the scene, ethereal energy suffusing")

    # ── Oracle pattern matching ───────────────────────────────────────────────
    for role, soul, patterns in _SOUL_PATTERNS:
        for pat in patterns:
            if re.search(pat, oracle):
                # Append CMC weight to soul for high-impact spells
                for threshold, label in _CMC_WEIGHT:
                    if cmc >= threshold:
                        return (role, f"{soul}, {label}")
                return (role, soul)

    # ── Keyword-based creature fallbacks ─────────────────────────────────────
    if "flying" in keywords:
        return ("FLIER", "aerial dominance, commanding the skies, wings fully spread")
    if "annihilator" in keywords:
        return ("ELDRAZI", "reality-consuming void horror, dimensional destruction")
    if "haste" in keywords:
        return ("AGGRO", "explosive sudden violence, striking before defenses can rise")
    if "deathtouch" in keywords:
        return ("DEATHTOUCH", "lethal predator, one touch means death, deadly precision")
    if "lifelink" in keywords:
        return ("LIFELINK", "life-draining force, energy stolen and absorbed")

    # ── Power/toughness → creature scale ─────────────────────────────────────
    try:
        p = int(power_raw or 0)
        if p >= 7:
            return ("BEATER", "massive unstoppable force, earth-shaking colossus")
        if p >= 4:
            return ("THREAT", "powerful dangerous combatant, a force to be reckoned with")
        if p <= 1:
            return ("UTILITY_CREATURE", "small but purposeful, nimble and functional servant")
    except (ValueError, TypeError):
        pass

    # ── CMC-based fallback for high-cost spells ───────────────────────────────
    if cmc >= 6:
        return ("PAYOFF", "late-game powerhouse, a decisive turning point")

    return ("SPELL", "magical energy released, arcane effect erupting")


_DEFAULT_MEDIUM  = '"digital painting," or "fantasy illustration," or "concept art,"'
_DEFAULT_QUALITY = '"painterly brushwork, vivid colors" or "dramatic lighting, intricate detail" or "painterly, rich texture"'

def _batch_prompt(theme: str, commander_name: str, cards: list[dict],
                   style_guide: str = "", commander_prompt: str = "",
                   batch_commander_idx: int = -1,
                   world_zones: Optional[list[str]] = None,
                   themer_medium: str = "",
                   themer_quality: str = "") -> str:
    """
    batch_commander_idx: local index (0-based within this batch) of the commander card,
                         or -1 if the commander is not in this batch.
    """
    lines = []
    for i, c in enumerate(cards):
        tl       = c.get("type_line", "").split("—")[0].strip()
        mechsum  = _mechanic_summary(c)
        palette  = _color_palette_hint(c.get("color_identity") or c.get("colors", []))
        # Format: idx|name|type|mechanics|color_palette
        lines.append(f'{i}|{c["name"]}|{tl}|{mechsum}|{palette}')

    card_block  = "\n".join(lines)
    style_block = (
        f"\nDeck visual style — apply to EVERY art_prompt: {style_guide}"
        if style_guide else ""
    )
    commander_block = ""
    if commander_prompt and batch_commander_idx >= 0:
        commander_block = (
            f"\nCOMMANDER CHARACTER (idx={batch_commander_idx}) — MANDATORY RULE: "
            f"The commander looks like: {commander_prompt}. "
            f"For idx={batch_commander_idx} ONLY — the art_prompt MUST physically describe this character. "
            f"The character description MUST appear immediately after the medium tag, BEFORE any environment or world detail. "
            f"Format: \"[medium], [describe '{commander_prompt}' visually — appearance, pose, action], "
            f"[brief world/environment context], [quality tag]\". "
            f"Do NOT skip the character. Do NOT open with the environment."
        )

    # Build variety / visual-diversity block from world zones
    if world_zones:
        zone_list = " | ".join(f'"{z}"' for z in world_zones)
        variety_block = (
            f"\nVISUAL DIVERSITY — MANDATORY: Every card in this batch MUST be set in a "
            f"DIFFERENT location. Do NOT repeat the same setting, lighting, or time-of-day "
            f"across cards. Cycle through these world zones (and invent more if needed): "
            f"{zone_list}. "
            f"Treat each zone as a distinct scene backdrop. "
            f"If this batch has 8 cards, use at least 4 different zones. "
            f"Vary: indoor/outdoor, time-of-day, weather, ground-level/aerial view, "
            f"intimate/wide shot. A card showing a 'cavern at night' and the next showing "
            f"'open plains at dawn' is correct. Two cards both showing 'dark cave' is wrong."
        )
    else:
        variety_block = (
            "\nVISUAL DIVERSITY — MANDATORY: Every card must use a DIFFERENT setting, "
            "time-of-day, and lighting mood. Vary indoor/outdoor, dawn/noon/dusk/night, "
            "calm/stormy weather, ground-level/aerial perspective. No two cards in the batch "
            "should share the same background environment."
        )

    return f"""You are creating art descriptions for a Magic: The Gathering card set set entirely within the world of: {theme}
Commander/protagonist: {commander_name}{style_block}{commander_block}{variety_block}

WORLD IMMERSION: Every single card exists inside the "{theme}" world. Settings, creatures, objects, architecture, and atmosphere must all feel native to that world. Someone reading an art_prompt should immediately recognise the theme without being told.

Return ONLY a JSON array, nothing else. Each object must have:
- "idx": the card index number
- "themed_name": MTG card name in the "{theme}" world. IGNORE the original name entirely — base it on what the card DOES (mechanics column) and the theme.
    • If the type (column 3) contains "Legendary Creature" OR "Legendary Planeswalker": use the MTG legendary naming convention — "Firstname, Title" or "Name, the Title". STRICT LIMITS: max 6 words total (max 3 words before the comma, max 3 words after). The part before the comma MUST sound like a real character name (not a descriptor). The title after the comma reflects the card's mechanics. Examples: "Vex Thornwood, Blade of the Void", "Kira Ashveil, the Undying", "Sera, Keeper of Flame". NEVER use a long title — keep it punchy.
    • CRITICAL — NAME UNIQUENESS: Each non-commander card (idx ≥ 1) MUST have its OWN unique character name in the pre-comma part. NEVER use "{commander_name}" (or a shortened version of it) as the first name of any non-commander card. Every named character in the deck should have a distinct name. No two non-commander legendary cards should share the same first name.
    • If the type contains "Legendary" but NOT "Creature" or "Planeswalker" (e.g. Legendary Land, Legendary Artifact, Legendary Enchantment): use a plain 2–4 word descriptive name with NO comma. Examples: "The Ashen Citadel", "Void-Forged Relic", "Ember Sanctum", "The Drowned Throne". Short and evocative.
    • All other cards: dramatic 2–5 word descriptive name, no comma. Punchy and specific ("Voidborn Harbinger", "Ashen Reckoning"). NOT generic filler like "Dark Card" or "[Theme] Warrior".
- "art_prompt": 25-40 words. LANDSCAPE orientation. Rules:
    MEDIUM — every prompt MUST begin with the medium: {themer_medium or _DEFAULT_MEDIUM}. Never start with a character or object — always the medium first.
    COLOR HARMONY — column 5 gives this card's MTG color identity palette. Blend those palette tones with the theme's world palette. A W/R card feels holy-fire; a U/B card feels cold-arcane-shadow. NEVER use colors that contradict both the theme AND the card's identity — e.g. don't paint a Black card in pastel pinks. Colorless cards use chrome/crystal/void tones.
    ANATOMY — avoid close-up hands; poses where hands hold a weapon/staff/orb or are not prominent. Never floating limbs.
    QUALITY — end with one of: {themer_quality or _DEFAULT_QUALITY}. Match the art style above — use style-appropriate finishing terms.
    MECHANICS — let the 4th column drive the ART SCENE through theme-appropriate imagery:
      • Deals damage → fire, lightning, violent impact, shockwave
      • Exiles → figure dissolving into void, banishment light, dimensional rift
      • Draws cards → visions, arcane revelation, glowing tome, cosmic eye
      • Creates tokens → summoning ritual, conjured shapes, multiple silhouettes
      • Flying → wings fully spread, figure levitating, aerial vista below
      • Destroys lands → cracked earth, erupting ground, cataclysm
      • Deathtouch → venomous aura, dripping necrotic energy, deadly glow
      • Gains life → golden healing radiance, restoration light, warmth
      • Tutors/searches → open book of secrets, ancient scroll, seeking hand
      • Counterspell → spell shattering mid-air, arcane barrier, void consuming magic
    COMPOSITION by card type — ORDER OF DESCRIPTION MATTERS (image models weight earlier words higher):
      Creature/Planeswalker: SUBJECT FIRST. Format: "[medium], [describe the character — appearance, species, pose, action], [brief world/theme environment detail], [quality]". The character MUST be the first thing described after the medium. NEVER open with environment or world elements for a creature card.
      Instant/Sorcery: wide dynamic action scene, the spell's effect filling the frame. Theme-world setting leads.
      Land: sweeping panorama, environment defining the land's identity, no figures needed. Theme world leads.
      Artifact: object centered, dramatically lit, clean background, detailed craftsmanship. Object leads.
      Enchantment: magical aura, binding energy, ethereal atmosphere around a subject.
    Art style MUST match the deck visual style listed above.
- "flavor_text": 10-15 word in-universe quote in the voice of the "{theme}" world

Cards to process (idx|name|type|mechanics|color_palette):
{card_block}

JSON array:"""


def _batch_prompt_v2(theme: str, commander_name: str, cards: list[dict],
                     style_guide: str = "", commander_prompt: str = "",
                     batch_commander_idx: int = -1,
                     world_zones: Optional[list[str]] = None,
                     themer_medium: str = "",
                     themer_quality: str = "") -> str:
    """
    Enhanced dual-anchor prompt (v2).

    Core change from v1: every art_prompt must satisfy TWO anchors simultaneously:

      1. MECHANICAL SOUL (col 7) — pre-classified visual essence of what the card DOES.
         This defines the *action/subject* of the art.  A removal spell must feel like
         something being destroyed.  A ramp card must feel like power being gathered.

      2. THEME SKIN — the world's visual language clothes the action.  Same destruction,
         but it looks like Devil May Cry or Feudal Japan or Cyberpunk, not generic fantasy.

    The v1 prompt put theme first and mechanics second; v2 makes them co-equal anchors
    so card identity is never drowned out by the world aesthetic.
    """
    lines = []
    for i, c in enumerate(cards):
        tl       = c.get("type_line", "").split("—")[0].strip()
        mechsum  = _mechanic_summary(c)
        palette  = _color_palette_hint(c.get("color_identity") or c.get("colors", []))
        role, soul = _card_soul(c)
        # Format: idx|name|type|mechanics|color_palette|role|soul
        lines.append(f'{i}|{c["name"]}|{tl}|{mechsum}|{palette}|{role}|{soul}')

    card_block  = "\n".join(lines)
    style_block = (
        f"\nDeck visual style — apply to EVERY art_prompt: {style_guide}"
        if style_guide else ""
    )
    commander_block = ""
    if commander_prompt and batch_commander_idx >= 0:
        commander_block = (
            f"\nCOMMANDER CHARACTER (idx={batch_commander_idx}) — MANDATORY RULE: "
            f"The commander looks like: {commander_prompt}. "
            f"For idx={batch_commander_idx} ONLY — the art_prompt MUST physically describe this character. "
            f"The character description MUST appear immediately after the medium tag, BEFORE any environment or world detail. "
            f"Format: \"[medium], [describe '{commander_prompt}' visually — appearance, pose, action], "
            f"[brief world/environment context], [quality tag]\". "
            f"Do NOT skip the character. Do NOT open with the environment."
        )

    if world_zones:
        zone_list = " | ".join(f'"{z}"' for z in world_zones)
        variety_block = (
            f"\nVISUAL DIVERSITY — MANDATORY: Every card in this batch MUST be set in a "
            f"DIFFERENT location. Cycle through these world zones (and invent more if needed): "
            f"{zone_list}. "
            f"Vary: indoor/outdoor, time-of-day, weather, ground-level/aerial view, intimate/wide shot."
        )
    else:
        variety_block = (
            "\nVISUAL DIVERSITY — MANDATORY: Every card must use a DIFFERENT setting, "
            "time-of-day, and lighting mood. No two cards in the batch should share the same backdrop."
        )

    return f"""You are creating art prompts for a Magic: The Gathering card set themed around: {theme}
Commander/protagonist: {commander_name}{style_block}{commander_block}{variety_block}

━━━ DUAL ANCHOR RULE — THE MOST IMPORTANT INSTRUCTION ━━━
Every art_prompt must satisfy TWO anchors at the same time:

  ANCHOR 1 — MECHANICAL SOUL (column 7): This tells you what the card DOES expressed as a
  visual action/scene. It defines the subject of the art and what they are doing.
  The soul MUST be visually present and recognisable. Ask yourself: if you saw only this art,
  could you guess the card's function? If not, the soul is not present.
    • REMOVAL/BURN/WIPE cards → something is being destroyed. Show the moment of destruction.
    • DRAW/TUTOR cards → revelation, visions, knowledge being received or sought.
    • RAMP/TOKEN cards → creation, summoning, gathering, multiplication.
    • COUNTER/BOUNCE cards → something being stopped, denied, or reversed.
    • CREATURE THREATS → the subject's power and presence must be clear and intimidating.
    • LANDS → the landscape IS the card. Pure environment, no characters needed.

  ANCHOR 2 — THEME SKIN: The "{theme}" world's visual language wraps the soul.
  Same action, different aesthetic. A "target destroyed" in a Western theme uses a gunshot.
  In a Devil May Cry theme it's a sword slash with demonic energy. In a fairy tale it's a spell.
  The theme skin is the COSTUME and SETTING, not the action.

Formula for each card: "[theme-styled medium], [SOUL action in theme-world costume/setting], [quality]"
Example: Soul=elimination + Theme=Western → "concept art, a gunslinger's bullet striking a bandit dead centre, dust explosion, sun-bleached desert, dramatic lighting, vivid colors"
Example: Soul=board wipe + Theme=Devil May Cry → "digital painting, Dante's massive sword swing releasing a divine white shockwave that tears through a demon horde simultaneously, hell-lit environment, painterly brushwork"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Return ONLY a JSON array, nothing else. Each object must have:
- "idx": the card index number
- "themed_name": base it on what the card DOES (col 4 mechanics + col 6 role) translated into the "{theme}" world.
    • Legendary Creature / Legendary Planeswalker: "Firstname, Title" — max 6 words, max 3 before comma, max 3 after. Pre-comma MUST be a real-sounding character name. Post-comma reflects the card's ROLE/SOUL, not just its original name.
    • CRITICAL — NAME UNIQUENESS: Every idx ≥ 1 card needs its own unique pre-comma name. NEVER reuse "{commander_name}" as the first name of any non-commander card.
    • Legendary non-creature/planeswalker: plain 2–4 word descriptive name, NO comma ("The Ashen Gate", "Void Crucible").
    • All others: dramatic 2–5 word name, no comma, specific and punchy.
- "art_prompt": 25-40 words. LANDSCAPE orientation. Strict rules:
    MEDIUM — start with: {themer_medium or _DEFAULT_MEDIUM}. Always medium first.
    SOUL — col 7 defines the visual action. It MUST be present. A card with soul "divine judgment, everything obliterated" should show a scene of mass annihilation, not a single warrior standing around.
    COLOR — col 5 color identity: blend with theme palette. W=holy light/white, U=arcane/cold blue, B=shadow/necrotic, R=fire/aggression, G=nature/growth, colorless=void/chrome.
    ANATOMY — no isolated floating limbs. Avoid awkward close-up hands unless dramatically intentional.
    COMPOSITION by ROLE (col 6):
      CREATURE/PLANESWALKER roles: subject FIRST after medium. "[medium], [character appearance + action], [environment detail], [quality]"
      REMOVAL/BURN/WIPE/COUNTER: show the moment of impact/denial. Effect FIRST. "[medium], [the spell effect happening], [target/setting], [quality]"
      DRAW/TUTOR: visions, revelation, light of knowledge. "[medium], [revelation scene], [world setting], [quality]"
      RAMP/TOKEN: creation and summoning. "[medium], [summoning/gathering scene], [world setting], [quality]"
      LAND: environment only. Sweeping panorama. No characters. "[medium], [sweeping theme-world landscape], [quality]"
      ARTIFACT/EQUIPMENT: object centered, dramatically lit. "[medium], [object close-up or in use], [quality]"
      ENCHANTMENT/SAGA: magical aura, persistent energy. "[medium], [aura/binding scene], [quality]"
    QUALITY — end with: {themer_quality or _DEFAULT_QUALITY}
    Art style MUST match deck visual style.
- "flavor_text": 10-15 word in-universe quote in the voice of the "{theme}" world. Reflects the card's SOUL, not just generic atmosphere.

Cards to process (idx|name|type|mechanics|color_palette|role|soul):
{card_block}

JSON array:"""


# ── Ollama client ─────────────────────────────────────────────────────────────

def _ollama_chat(prompt: str, model: str = OLLAMA_MODEL) -> str:
    payload = {
        "model": model,
        # qwen3 supports "think": false to skip the chain-of-thought reasoning pass.
        # For JSON-structured creative tasks this cuts latency ~30-40% with no quality
        # loss. Ignored harmlessly by older models (qwen2.5, etc.).
        "think": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        "stream": True,
        "options": {
            "temperature": 1.1,
            "top_p": 0.95,
            "top_k": 0,
            "num_ctx": 4096,
            "num_gpu": 99,
            # 1024 is too small for verbose 27B+ models (qwen3.6 routinely hits
            # ~1100-1400 tokens for an 8-card batch, causing mid-JSON truncation).
            # 1792 gives comfortable headroom for a full 8-card batch from any model
            # without ballooning memory usage (~0.7 GB extra KV cache at 4096 ctx).
            "num_predict": 1792,
            "repeat_penalty": 1.0,
        },
    }
    resp = requests.post(
        f"{OLLAMA_BASE}/api/chat",
        json=payload,
        stream=True,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()

    parts = []
    deadline = time.monotonic() + REQUEST_TIMEOUT
    for line in resp.iter_lines():
        if time.monotonic() > deadline:
            print("  [themer] Batch timed out mid-stream, using partial response.")
            break
        if not line:
            continue
        try:
            chunk = json.loads(line)
            parts.append(chunk.get("message", {}).get("content", ""))
            if chunk.get("done"):
                break
        except json.JSONDecodeError:
            continue
    return "".join(parts)


def unload_ollama_model(model: str = OLLAMA_MODEL) -> None:
    """Evict the model from GPU VRAM so ComfyUI can claim the memory."""
    try:
        requests.post(
            f"{OLLAMA_BASE}/api/generate",
            json={"model": model, "keep_alive": 0},
            timeout=10,
        )
        print(f"  [themer] Ollama model unloaded from GPU: {model}.")
    except Exception as e:
        print(f"  [themer] Could not unload Ollama model: {e}")


def _parse_batch(raw: str, cards: list[dict]) -> list[dict]:
    """Parse LLM response and merge back with cards."""
    if not raw.strip():
        print("  [WARN] Empty Ollama response for batch")
        return []
    print(f"  [DEBUG] Ollama response ({len(raw)} chars): {raw[:200]}...")

    text = raw.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```$",       "", text, flags=re.MULTILINE)

    bracket_start = text.find("[")
    bracket_end   = text.rfind("]")
    if bracket_start != -1 and bracket_end != -1:
        text = text[bracket_start:bracket_end + 1]

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  [WARN] JSON parse failed: {e}")
        print(f"         Tried to parse: {text[:150]}...")
        return [
            {"idx": i, "themed_name": c["name"], "art_prompt": "", "flavor_text": ""}
            for i, c in enumerate(cards)
        ]

    # Handle bare object (single card) — wrap in list
    if isinstance(parsed, dict):
        # Could be {"idx": 0, ...} or {"cards": [...]}
        if "cards" in parsed and isinstance(parsed["cards"], list):
            parsed = parsed["cards"]
        else:
            parsed = [parsed]

    by_idx = {item["idx"]: item for item in parsed if isinstance(item, dict) and "idx" in item}

    if by_idx:
        sample_idx = next(iter(by_idx.keys()))
        sample = by_idx[sample_idx]
        print(f"  [DEBUG] Sample (idx={sample_idx}): art_prompt={bool(sample.get('art_prompt'))}, "
              f"themed_name={bool(sample.get('themed_name'))}, flavor={bool(sample.get('flavor_text'))}")

    result = []
    for i, card in enumerate(cards):
        entry = by_idx.get(i, {})
        result.append({
            "idx":         i,
            "themed_name": entry.get("themed_name") or card["name"],
            "art_prompt":  entry.get("art_prompt")  or "",
            "flavor_text": entry.get("flavor_text") or "",
        })
    return result


# ── ThemedCard ────────────────────────────────────────────────────────────────

class ThemedCard:
    __slots__ = ("original_name", "themed_name", "art_prompt", "flavor_text", "card")

    def __init__(
        self,
        original_name: str,
        themed_name:   str,
        art_prompt:    str,
        flavor_text:   str,
        card:          dict,
    ):
        self.original_name = original_name
        self.themed_name   = themed_name
        self.art_prompt    = art_prompt
        self.flavor_text   = flavor_text
        self.card          = card


# ── Themer ────────────────────────────────────────────────────────────────────

class Themer:
    def __init__(self, model: str = OLLAMA_MODEL, base_url: str = OLLAMA_BASE):
        self.model    = model
        self.base_url = base_url
        self._verify_ollama()

    def _verify_ollama(self):
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]

            # Check if exact requested model is available
            if self.model not in models:
                # Model not found — try to pick the best alternative
                print(f"  [themer] Model '{self.model}' not installed. Available: {models}")

                # Priority order for fallback: qwen3:32b > qwen2.5-coder > gemma4 > any first
                fallback = None
                for pattern in ["qwen3:32b", "qwen2.5-coder:14b", "gemma4:latest"]:
                    fallback = next((m for m in models if m == pattern), None)
                    if fallback:
                        print(f"  [themer] Using fallback model: {fallback}")
                        self.model = fallback
                        return

                # No exact match found — use first available as last resort
                if models:
                    print(f"  [themer] WARNING: No priority fallback matched. Using: {models[0]}")
                    self.model = models[0]
                else:
                    raise RuntimeError(f"No Ollama models installed at {self.base_url}")
        except requests.RequestException as e:
            raise RuntimeError(
                f"Cannot reach Ollama at {self.base_url} — is it running?\n{e}"
            )

    def _theme_batch(
        self,
        theme:                  str,
        commander_name:         str,
        cards:                  list[dict],
        batch_start:            int,
        style_guide:            str = "",
        commander_prompt:       str = "",
        batch_commander_idx:    int = -1,
        world_zones:            Optional[list[str]] = None,
        themer_medium:          str = "",
        themer_quality:         str = "",
    ) -> list[dict]:
        """
        Process one batch of cards. Returns list of themed dicts.

        Prompt pipeline is controlled by the module-level USE_ENHANCED_PROMPTS flag:
          True  → _batch_prompt_v2 (dual-anchor: mechanical soul + theme skin)
          False → _batch_prompt    (v1 legacy: theme-first world immersion)

        Retry strategy: if ≥ 50% of cards in this batch return empty art_prompts
        (indicating JSON truncation), split into two half-batches and retry each
        independently.  Half-batches require roughly half the num_predict budget,
        so they virtually never truncate.
        """
        _prompt_fn = _batch_prompt_v2 if USE_ENHANCED_PROMPTS else _batch_prompt
        prompt_version = "v2 (dual-anchor)" if USE_ENHANCED_PROMPTS else "v1 (legacy)"

        prompt = _prompt_fn(theme, commander_name, cards, style_guide,
                            commander_prompt=commander_prompt,
                            batch_commander_idx=batch_commander_idx,
                            world_zones=world_zones,
                            themer_medium=themer_medium,
                            themer_quality=themer_quality)
        raw    = _ollama_chat(prompt, model=self.model)
        parsed = _parse_batch(raw, cards)

        # ── Truncation detector ───────────────────────────────────────────────
        # A JSON truncation shows up as:
        #   (a) many cards with empty art_prompts (partial parse), or
        #   (b) completely empty parsed list (blank / totally garbled response).
        # If either condition fires and we have > 1 card, split and retry.
        empty_count = sum(1 for e in parsed if not e.get("art_prompt"))
        # Treat a completely empty parsed list as all-empty
        if not parsed:
            empty_count = len(cards)
        if empty_count >= max(1, len(cards) // 2) and len(cards) > 1:
            print(f"  [themer] {empty_count}/{len(cards)} prompts empty — likely truncation. "
                  f"Retrying as two half-batches ({prompt_version})...")
            mid    = len(cards) // 2
            half_a = cards[:mid]
            half_b = cards[mid:]

            # Commander might be in the first half (batch_start == 0, idx 0)
            cmd_local_a = batch_commander_idx if 0 <= batch_commander_idx < mid else -1
            cmd_local_b = (batch_commander_idx - mid
                           if batch_commander_idx >= mid else -1)

            def _retry_half(sub_cards, offset, cmd_idx):
                sub_prompt = _prompt_fn(
                    theme, commander_name, sub_cards, style_guide,
                    commander_prompt=commander_prompt,
                    batch_commander_idx=cmd_idx,
                    world_zones=world_zones,
                    themer_medium=themer_medium,
                    themer_quality=themer_quality,
                )
                sub_raw    = _ollama_chat(sub_prompt, model=self.model)
                sub_parsed = _parse_batch(sub_raw, sub_cards)
                for e in sub_parsed:
                    e["idx"] += offset
                return sub_parsed

            results_a = _retry_half(half_a, batch_start,       cmd_local_a)
            results_b = _retry_half(half_b, batch_start + mid, cmd_local_b)
            return results_a + results_b

        for entry in parsed:
            entry["idx"] += batch_start
        return parsed

    def theme_deck(
        self,
        theme:              str,
        commander:          dict,
        deck:               list[dict],
        commander_prompt:   str  = "",   # specific appearance description for the commander character
        progress_callback=None,          # callable(batch_num, total_batches, cards_done, total_cards)
        style_guide_hint:   str  = "",   # art style label for the style guide generator (e.g. "flat-colour anime")
        themer_medium:      str  = "",   # medium tag options for batch prompt MEDIUM rule
        themer_quality:     str  = "",   # quality tag options for batch prompt QUALITY rule
    ) -> tuple[ThemedCard, list[ThemedCard]]:
        """
        Apply theme to commander + 99-card deck.
        Returns (themed_commander, themed_deck_99).
        """
        all_cards = [commander] + deck
        total     = len(all_cards)
        themed_entries: dict[int, dict] = {}

        # Expand short themes into a richer world description + visual zone list.
        # Short prompts like "mushroom forest" would otherwise produce 100 nearly-
        # identical backgrounds; zones give Ollama concrete distinct settings to
        # cycle through so each batch of cards feels like a different corner of
        # the world.
        print("\n  Expanding theme for visual diversity...")
        expanded_theme, world_zones = _expand_theme(theme, model=self.model)

        # Generate one deck-wide style guide — used as context in Ollama's batch
        # prompts so every card's scene feels like the same world.
        # NOTE: the style guide is NOT prepended to FLUX prompts (see make() below).
        # flux_prefix in image_gen.py owns the art style; prepending the style guide
        # there caused medium conflicts (oil-painting language in anime builds, etc.).
        print("  Generating deck visual style guide...")
        style_guide = _generate_style_guide(expanded_theme, commander["name"],
                                            commander_prompt=commander_prompt,
                                            style_guide_hint=style_guide_hint,
                                            model=self.model)
        print(f"  [themer] Style guide (Ollama context only): {style_guide[:120]}..."
              if len(style_guide) > 120 else f"  [themer] Style guide: {style_guide}")

        batches = [all_cards[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
        pipeline_label = "v2 dual-anchor" if USE_ENHANCED_PROMPTS else "v1 legacy"
        print(f"  Theming {total} cards via Ollama ({self.model}) "
              f"in {len(batches)} batches (max {BATCH_SIZE}/batch) "
              f"[prompt pipeline: {pipeline_label}]...")

        for b_idx, batch in enumerate(batches):
            batch_start = b_idx * BATCH_SIZE
            hi          = batch_start + len(batch) - 1
            print(f"  Batch {b_idx + 1}/{len(batches)}  "
                  f"(cards {batch_start}–{hi})...", end=" ", flush=True)

            # Determine if the commander card falls in this batch
            cmd_local_idx = -1
            if batch_start == 0:   # commander is always all_cards[0]
                cmd_local_idx = 0

            t0      = time.monotonic()
            entries = self._theme_batch(
                expanded_theme, commander["name"], batch, batch_start, style_guide,
                commander_prompt=commander_prompt,
                batch_commander_idx=cmd_local_idx,
                world_zones=world_zones,
                themer_medium=themer_medium,
                themer_quality=themer_quality,
            )
            elapsed = time.monotonic() - t0

            for e in entries:
                themed_entries[e["idx"]] = e
            print(f"{elapsed:.1f}s")
            if progress_callback:
                try:
                    cards_done = min((b_idx + 1) * BATCH_SIZE, total)
                    progress_callback(b_idx + 1, len(batches), cards_done, total)
                except Exception:
                    pass

        def make(i: int, card: dict) -> ThemedCard:
            e = themed_entries.get(i, {})
            raw_prompt = e.get("art_prompt") or ""

            if raw_prompt:
                # ── Strip Ollama's medium tag ──────────────────────────────────
                # Ollama defaults to "dramatic fantasy oil painting, ..." regardless
                # of instructions due to strong MTG training priors.  Stripping it
                # lets image_gen.py's flux_prefix (which is per-preset and correct)
                # own the style/medium token, which FLUX weights most heavily.
                scene = _MEDIUM_PREFIX_RE.sub("", raw_prompt).strip().lstrip(",. ").strip()
                # Fallback if regex stripped everything
                if not scene:
                    scene = raw_prompt.strip()

                # Additional safety: if scene still starts with [adjective] + [medium],
                # strip it as a fallback (catches edge cases the regex missed)
                if scene and not scene[0].isupper():
                    # e.g., "neon-lit illustration, A ...", find first capital letter
                    words = scene.split()
                    for idx, word in enumerate(words):
                        if word and word[0].isupper():
                            scene = " ".join(words[idx:])
                            break

                # ── Do NOT prepend style_guide to FLUX prompts ─────────────────
                # The style_guide is used by Ollama when generating each card's
                # description (so all scenes feel cohesive), but prepending it to
                # the FLUX prompt adds redundant/contradictory medium language on
                # top of the flux_prefix.  The scene description Ollama generated
                # already bakes in the world/theme context — no double-dipping needed.

                if i == 0 and commander_prompt:
                    # Commander card: inject the user's appearance description once,
                    # before the scene.  Do NOT also include it from raw_prompt —
                    # Ollama sometimes echoes it back, causing duplication.
                    # Strip any commander description Ollama may have echoed back.
                    # Strategy: if scene starts with a close variant of commander_prompt,
                    # drop it; otherwise prepend cleanly.
                    cmd_words = commander_prompt.lower().split()[:4]  # first 4 words
                    if cmd_words and all(w in scene.lower() for w in cmd_words[:2]):
                        # Ollama echoed the commander description — drop Ollama's version
                        full_prompt = f"{commander_prompt}, {scene}"
                    else:
                        full_prompt = f"{commander_prompt}, {scene}"
                else:
                    full_prompt = scene

            else:
                full_prompt = ""

            return ThemedCard(
                original_name=card["name"],
                themed_name  =e.get("themed_name") or card["name"],
                art_prompt   =full_prompt,
                flavor_text  =e.get("flavor_text") or "",
                card         =card,
            )

        themed_all = [make(i, c) for i, c in enumerate(all_cards)]

        # Free GPU VRAM before ComfyUI art generation runs.
        # IMPORTANT: must evict the actual model that was loaded — not the default.
        # A mismatched name is silently ignored by Ollama, leaving the model resident.
        unload_ollama_model(model=self.model)

        return themed_all[0], themed_all[1:]


# ── Display / export helpers ──────────────────────────────────────────────────

def export_themed_deck(
    commander_tc: ThemedCard,
    deck_tcs:     list[ThemedCard],
    theme:        str,
    filepath:     str,
) -> None:
    lines = [
        f"// Theme: {theme}",
        f"// Model: {OLLAMA_MODEL} (local Ollama)",
        "",
        "// COMMANDER",
        f"// {commander_tc.themed_name}  (originally: {commander_tc.original_name})",
        f"// Art: {commander_tc.art_prompt}",
        f"// Flavor: {commander_tc.flavor_text}",
        f"1 {commander_tc.original_name}",
        "",
        "// DECK",
    ]

    seen: dict[str, int] = {}
    ordered: list[ThemedCard] = []
    for tc in deck_tcs:
        n = tc.original_name
        if n not in seen:
            seen[n] = 0
            ordered.append(tc)
        seen[n] += 1

    for tc in ordered:
        count = seen[tc.original_name]
        lines += [
            f"// {tc.themed_name}  (originally: {tc.original_name})",
            f"// Art: {tc.art_prompt}",
            f"// Flavor: {tc.flavor_text}",
            f"{count} {tc.original_name}",
            "",
        ]

    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"  Exported to: {filepath}")
