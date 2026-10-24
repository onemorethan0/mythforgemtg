"""Request models shared by the build/regen job workers and their routes, plus the
gen-settings resolution helpers.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from image_gen import GenSettings

# ── Request / Response models ─────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str


class GenSettingsModel(BaseModel):
    """User-configurable generation knobs from the frontend Advanced panels.
    Mirrors image_gen.GenSettings; all optional so omitting it preserves defaults."""
    guidance:       Optional[float] = None   # FLUX FluxGuidance (1.5–5)
    steps:          Optional[int]   = None   # sampler steps
    sampler:        Optional[str]   = None
    scheduler:      Optional[str]   = None
    seed_mode:      Optional[str]   = None   # "random" | "fixed"
    seed:           Optional[int]   = None
    lora_overrides: Optional[List[dict]] = None  # [{filename, model_strength, clip_strength?, trigger?}]
    style_variant:  Optional[str]   = None   # pin a preset rotation flavor deck-wide ("" / "auto" = Variety mix)
    face_method:    Optional[str]   = None   # None=auto | "reactor" | "pulid_flux" | "none"
    face_weight:    Optional[float] = None
    safe_mode:      Optional[bool]  = None
    enhance:        Optional[bool]  = None   # Perturbed-Attention Guidance (better anatomy; ~2x slower)
    face_fix:       Optional[bool]  = None   # FaceDetailer pass (SDXL/Illustrious; re-renders faces)


def _resolve_gen_settings(gs: "Optional[GenSettingsModel]") -> GenSettings:
    """Convert the API GenSettingsModel into the image_gen.GenSettings dataclass.
    None / missing fields fall back to defaults (existing behavior)."""
    if gs is None:
        return GenSettings()
    try:
        d = gs.model_dump(exclude_none=True)   # pydantic v2
    except AttributeError:
        d = {k: v for k, v in gs.dict().items() if v is not None}  # pydantic v1
    return GenSettings.from_dict(d)


def _gen_settings_to_dict(gs: "Optional[GenSettingsModel]") -> dict:
    """Serialize a request GenSettingsModel to a plain (None-stripped) dict for
    persistence in deck.json, so regen paths can recover the user's advanced
    settings — guidance/steps/lora_overrides and a pinned style_variant."""
    if gs is None:
        return {}
    try:
        return gs.model_dump(exclude_none=True)   # pydantic v2
    except AttributeError:
        return {k: v for k, v in gs.dict().items() if v is not None}  # pydantic v1


def _resolve_gen_settings_reusing(gs: "Optional[GenSettingsModel]",
                                  source_data: "Optional[dict]") -> GenSettings:
    """For regen paths (rebuild / regen-cards / retheme): honor the request's
    gen_settings when provided, else fall back to the gen_settings persisted in the
    source deck.json. This keeps a pinned style_variant (and every other advanced
    knob) alive across a re-generation instead of silently resetting to defaults."""
    if gs is not None:
        return _resolve_gen_settings(gs)
    stored = (source_data or {}).get("gen_settings") or None
    return GenSettings.from_dict(stored)


class BuildRequest(BaseModel):
    # Optional when importing an existing decklist (deck_url / deck_list provide
    # the commander). Required for the generate-a-deck path.
    commander_name:    str = Field("", max_length=120)
    # The command zone can hold TWO cards. A LIST, not a second scalar, because Partner,
    # Friends forever, Choose a Background and Doctor's companion all land in the same slot.
    partner_names:     list[str] = Field(default_factory=list, max_length=2)
    # Import an existing deck instead of generating one. deck_url = a Moxfield/
    # Archidekt URL; deck_list = pasted decklist text. When either is set the
    # 99-card generator is skipped and the imported list is themed/rendered.
    deck_url:          str = Field("", max_length=600)
    deck_list:         str = Field("", max_length=20000)
    # Edit & Rebuild of a deck whose card list must be preserved (imports). The
    # list is restored VERBATIM from that job's deck.json — not re-imported (the
    # upstream deck may have changed since) and not regenerated (DeckBuilder would
    # invent a different deck entirely). Wins over deck_url/deck_list/prebuilt_deck.
    source_deck_id:    str = Field("", max_length=64)
    playstyle:         str = "auto"
    # Caps prevent long appearance dumps from polluting the LLM batch prompt and
    # blowing FLUX's first-N-token attention window (causes "standing portrait"
    # output with no card action).  Cap raised from 400: art_theme is now a
    # back-compat fallback (the structured theme_spec is the primary input) and is
    # persisted/restored, so it must hold the composed structured brief without
    # truncating (a long Setting + all chips can exceed 800; build_creative_brief
    # caps the actual prompt seed at 900 chars regardless).
    art_theme:         str = Field("", max_length=2000)
    commander_prompt:  str = Field("", max_length=500)
    emblem_prompt:     str = Field("", max_length=300)
    art_style:         str = "mtg_fantasy"  # LoRA preset key
    generate_art:      bool = False
    model_speed:       str  = "quality"  # "quality" (flux-dev) or "fast" (flux-schnell) or "sd35" (SD 3.5 Large)
    checkpoint:        Optional[str] = None   # explicit checkpoint filename; None = auto-detect from ComfyUI
    bracket:           int  = 3
    face_key:          Optional[str] = None   # commander face photos
    face_gender:       str = "either"         # "male", "female", or "either"
    crew_key:          Optional[str] = None   # crew face photos for creature cards
    crew_gender:       str = "either"         # gender hint for crew faces
    crew_prompt:       str = ""               # shared appearance notes for crew-faced creatures
    is_commander_deck: bool = True            # False → imported non-Commander list: no auto hero face
    face_assignments:  Optional[dict] = None  # {card original_name: crew-photo index} — explicit per-card faces (non-commander decks)
    user_name:         Optional[str] = None   # replaces the commander's generated first name
    llm_model:         Optional[str] = None   # Ollama model key — None = use themer default
    border_theme:      str           = ""     # free-text description of card-border decoration
    frame_style:       str           = "builtin"  # "builtin" (bundled frames) or "m15" (official-style, needs local Card Conjurer)
    commander_tribe:   str           = ""     # override creature tribe to reskin; "" = auto-detect
    custom_pips:       bool          = False  # themed 2-colour mana pips (disc + black silhouette)
    # Two-phase flow: a decklist generated up front (POST /api/deck/generate-list)
    # is passed back here so the build skips DeckBuilder and themes/renders this
    # exact list. tribal_overrides = user-chosen {OriginalType: Replacement} from
    # the theme step's per-tribe fields (multi-tribe reskin; wins over auto-detect).
    prebuilt_deck:     Optional[list] = None
    tribal_overrides:  Optional[dict] = None
    # "Auto-theme creature types" checkbox: auto-generate ONE theme-fitting
    # replacement for EVERY deck creature type (not just the commander's) and
    # apply it uniformly. Explicit tribal_overrides still win per-type. Defaults
    # ON — a build with no directive gets cohesive theme-fitting creature types.
    auto_theme_tribes: bool          = True
    # Collection-aware building (Myth Suite C4): when true, the 99-card generator
    # PREFERS cards from the user's owned-collection export
    # (Documents/MythSuite/collection.csv), falling back to unowned EDHREC picks
    # when the collection can't cover a slot. Generate path only (imports ignore it).
    use_collection:    bool          = False
    # Which pool the builder may draw from: "scryfall" | "prefer_collection" |
    # "collection". Empty means "derive from use_collection", so every existing caller
    # keeps its exact behaviour — use_collection=True is prefer_collection, not strict.
    card_source:       str           = Field("", max_length=24)
    # Structured "deck vision" fields (setting/moods/genres/lighting/inspiration).
    # Now the PRIMARY theming input: themer.build_creative_brief() reads these as
    # distinct labelled dimensions (not the flattened art_theme blob). Persisted so
    # Edit can restore them.
    theme_spec:        Optional[dict] = None
    # Creativity dial — how much invented detail the creative brief adds on top of
    # the user's stated motifs: "faithful" | "balanced" | "imaginative".
    creativity:        str           = "balanced"
    gen_settings:      Optional[GenSettingsModel] = None   # Advanced-panel overrides


class RebuildRequest(BaseModel):
    """Minimal params needed to re-run art gen for an already-themed deck."""
    art_style:   str = "mtg_fantasy"
    model_speed: str = "quality"
    checkpoint:  Optional[str] = None   # explicit checkpoint; None = auto-detect
    face_key:    Optional[str] = None
    face_gender: str = "either"
    crew_key:    Optional[str] = None
    crew_gender: str = "either"
    crew_prompt: Optional[str] = None   # None → use saved crew_prompt
    gen_settings: Optional[GenSettingsModel] = None


class CardRegenEntry(BaseModel):
    render_key:    str            # safe-name used in the filename / URL
    original_name: str            # canonical MTG card name for lookup fallback
    custom_prompt: Optional[str] = None   # user's custom text (stored separately; never clobbers art_prompt)
    use_custom:    bool = False           # True → feed custom_prompt to generation; False → use LLM art_prompt


class RegenCardsRequest(BaseModel):
    """Per-card regeneration — re-run art gen for a specific subset of cards."""
    cards:       List[CardRegenEntry]
    art_style:   str = "mtg_fantasy"
    model_speed: str = "quality"
    checkpoint:  Optional[str] = None   # explicit checkpoint; None = auto-detect
    face_key:    Optional[str] = None   # commander face override
    face_gender: str = "either"
    crew_key:    Optional[str] = None   # crew faces override for creature cards
    crew_gender: str = "either"
    # Force a single uploaded face onto EVERY selected card, bypassing the
    # commander/humanoid-creature routing. Lets the user drop a friendly face
    # onto any card they picked (even non-humanoid ones) and regenerate it.
    force_face_key:    Optional[str] = None
    force_face_gender: str = "either"
    gen_settings: Optional[GenSettingsModel] = None


class AnimateCardEntry(BaseModel):
    render_key:    str
    original_name: str


class AnimateCardsRequest(BaseModel):
    """Animate a subset of cards — I2V the art and/or overlay a procedural foil
    sheen, recomposite, and encode a looping clip (mp4 / webp / gif)."""
    cards:         List[AnimateCardEntry]
    motion_preset: str = "subtle"
    motion_prompt: Optional[str] = None   # free-text custom motion (wins over motion_preset)
    motion_strength: Optional[float] = None  # 0..1 how much the art moves (LTXV); None → default 0.5
    loop:          bool = True
    loop_style:    Optional[str] = None   # crossfade | bounce | off (motion); None → crossfade
    duration:      Optional[float] = None  # desired clip length (seconds); → frame count (snapped for I2V)
    frames:        Optional[int] = None   # explicit frame-count override (wins over duration)
    fps:           Optional[int] = None
    method:        Optional[str] = None   # override the auto-detected I2V model
    effect:        str = "motion"         # motion | foil | motion_foil
    foil_style:    str = "holo"           # holo | gold | silver (when effect uses foil)
    foil_intensity: Optional[float] = None  # foil sheen strength 0..1 (default ~0.55)
    fmt:           str = "mp4"            # mp4 | webp | gif (output container)


class RethemeRequest(BaseModel):
    """Re-theme an already-built deck: new names/prompts, and new art for them."""
    art_theme:        Optional[str] = None   # None → use saved theme from deck.json
    commander_prompt: Optional[str] = None   # None → use saved commander_prompt
    user_name:        Optional[str] = None   # None → use saved user_name
    llm_model:        Optional[str] = None   # None → use saved llm_model
    commander_tribe:  Optional[str] = None   # None → use saved / auto-detect
    theme_spec:       Optional[dict] = None  # None → use saved structured theme_spec
    creativity:       Optional[str]  = None  # None → use saved creativity dial
    # Art controls. A deck saved straight from an import has generate_art=False and
    # no art_style at all, so retheme used to re-name its cards and then skip art
    # entirely — the "save the list now, generate art later" lifecycle produced no
    # art and offered no way to pick a style. These let that first art run be
    # requested; each falls back to the source deck's value when omitted.
    generate_art:     Optional[bool] = None  # None → use saved generate_art
    art_style:        Optional[str]  = None  # None → use saved art_style
    model_speed:      Optional[str]  = None  # None → use saved model_speed
    checkpoint:       Optional[str]  = None  # None → use saved checkpoint
    gen_settings:     Optional[GenSettingsModel] = None   # None → use saved gen_settings


class SingleCardModel(BaseModel):
    """A user-authored custom card definition for single-card mode."""
    name:        str = Field("", max_length=160)
    mana_cost:   str = Field("", max_length=80)   # e.g. "{2}{W}{U}"
    type_line:   str = Field("", max_length=160)  # e.g. "Legendary Creature — Knight"
    oracle_text: str = Field("", max_length=2000)
    flavor_text: str = Field("", max_length=600)
    power:       Optional[str] = None             # strings so "*"/"1+*" are allowed
    toughness:   Optional[str] = None
    loyalty:     Optional[str] = None             # planeswalkers
    rarity:      str = "rare"                     # common|uncommon|rare|mythic|special
    colors:      Optional[List[str]] = None       # WUBRG; None → derive from mana_cost


class CardBuildRequest(BaseModel):
    """Single custom card → theme + (optional) art + rendered proxy. Reuses the
    deck theming/art knobs; the result persists as a 'deck of one' so every
    existing per-card action (regen/animate/3D/export/history) works on it."""
    card:             SingleCardModel
    # Theming
    theme_mode:       str = "author"   # "author" (keep my name/text; AI art only) | "full" (AI themes/renames)
    art_prompt_mode:  str = "auto"     # "auto" (LLM writes art prompt) | "custom" (user supplies it)
    art_prompt:       str = Field("", max_length=2000)   # used when art_prompt_mode == "custom"
    art_theme:        str = Field("", max_length=2000)
    theme_spec:       Optional[dict] = None
    creativity:       str = "balanced"
    commander_prompt: str = Field("", max_length=500)    # subject appearance
    emblem_prompt:    str = Field("", max_length=300)
    # Art / render
    art_style:        str = "mtg_fantasy"
    generate_art:     bool = False
    model_speed:      str  = "quality"
    checkpoint:       Optional[str] = None
    llm_model:        Optional[str] = None
    border_theme:     str = ""
    frame_style:      str = "builtin"
    custom_pips:      bool = False
    # Face conditioning (single likeness)
    face_key:         Optional[str] = None
    face_gender:      str = "either"
    gen_settings:     Optional[GenSettingsModel] = None
