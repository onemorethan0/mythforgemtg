"""
MTG card renderer — real frame PNGs + real fonts + inline SVG symbols.

Render pipeline:
  1. Build a 1440×2016 canvas (3× for anti-aliasing)
  2. Composite: black → bg PNG → art image → frame PNG → boxes (name/type bars)
     → legendary crown (if applicable) → text + mana pips → PT badge
  3. Downscale to 750×1050 with LANCZOS

The 3× supersampling produces noticeably sharper oracle text and mana symbol
linework. Output is 750×1050 px (2.5″×3.5″ at 300 DPI), exactly matching the
PDF exporter's print target — no upscaling quality loss in the final PDF.
All layout constants derive from _MM so they scale automatically.

Assets in card_assets/ (copied from wingedsheep/mtg-card-generator):
  frames/      — full-card frame overlays (transparent art + inner areas)
  bg/          — inner card background
  boxes/       — name-bar / type-bar strips
  pt_boxes/    — power/toughness badge
  legendary_crowns/ — legendary ornament overlay
  symbols/     — SVG mana & tap symbols (T, W, U, B, R, G, 0-20, X, …)
  fonts/       — beleren-bold_P1.01.ttf, mplantin.ttf, MPlantin-Italic.ttf
"""
from __future__ import annotations

import io
import math
import re
import textwrap
from functools import lru_cache
from pathlib import Path
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

# ── Paths ─────────────────────────────────────────────────────────────────────
_ASSETS   = Path("card_assets")
_FONTS    = _ASSETS / "fonts"
_ART_CACHE = Path("scryfall_cache")

# ── Canvas dimensions ─────────────────────────────────────────────────────────
# Card = 63.5 × 88.9 mm; we render at 3× for anti-aliasing then downscale.
CARD_W, CARD_H = 750, 1050          # final output (2.5"×3.5" @ 300 DPI — matches PDF exporter, no upscale needed)
_W2, _H2       = 1440, 2016        # internal 3× canvas (still 3× for AA, ~1.9× downscale to output)
_MM            = _W2 / 63.5        # px per mm at 3× ≈ 22.68

def _mm(v: float) -> int:
    return round(v * _MM)

# Asset layout in 3× px  (derived from wingedsheep CSS — all values via _mm())
_BG_X, _BG_Y   = _mm(2.5),  _mm(2.25)
_BG_W, _BG_H   = _mm(58.5), _mm(78.0)

_FR_X, _FR_Y   = _mm(2.56), _mm(3.5)
_FR_W, _FR_H   = _mm(57.33), _mm(79.0)

_ART_X, _ART_Y = _mm(4.4),  _mm(9.55)
_ART_W, _ART_H = _mm(54.7), _mm(39.9)

_BAR_W, _BAR_H = _mm(53.8), _mm(5.1)
_BAR_X         = (_W2 - _BAR_W) // 2
_NAME_Y        = _mm(4.0)
_TYPE_Y        = _mm(49.9)

_ORA_X         = _mm(4.4)
_ORA_Y         = _mm(55.6)
_ORA_W         = _mm(54.7)
_ORA_H         = _mm(26.0)

# P/T badge: real MTG boxes are wider than tall (~15.5×8.3 mm). The pt_boxes
# assets are 555×296 (≈1.88:1); resizing them into a square squashed the badge,
# so match the asset's aspect (W/H ≈ 1.88) to keep it rectangular.
_PT_W, _PT_H   = _mm(15.5), _mm(8.25)
_PT_X          = _W2 - _mm(3.2) - _PT_W
_PT_Y          = _H2 - _mm(3.5) - _PT_H

_CROWN_W       = _mm(57.0)
_CROWN_X       = (_W2 - _CROWN_W) // 2
_CROWN_Y       = _mm(2.5)

# Text positioning inside bars
_NAME_TY  = _NAME_Y + _BAR_H // 2      # vertical centre of name bar
_TYPE_TY  = _TYPE_Y + _BAR_H // 2      # vertical centre of type bar
_NAME_TX  = _BAR_X + _mm(1.5)          # left margin inside name bar
_NAME_TX_MAX = _BAR_X + _BAR_W - _mm(1.5)

# Oracle text padding inside the text box
_ORA_PAD  = _mm(1.0)

# ── Colours for text drawn on frame ───────────────────────────────────────────
_DARK_TEXT  = (10,  8,  4)
_LIGHT_TEXT = (240, 235, 220)

# Per-key text colours (name/type bar foreground).
# NOTE: this is only a *fallback seed*. The real choice is made at draw time by
# sampling the composited pixels under each text region (see _legible_text_color)
# so the border-theme tint and the actual box artwork are accounted for.
_BAR_FG: dict[str, tuple] = {
    "U":         _LIGHT_TEXT,
    "B":         _LIGHT_TEXT,
    "UB":        _LIGHT_TEXT,
    "UR":        _LIGHT_TEXT,
    "BR":        _LIGHT_TEXT,
    "BG":        _LIGHT_TEXT,
}

# ── Frame style (module-global, set once per build — mirrors set_custom_pips) ──
# "builtin" → bundled wingedsheep frames (default). "m15" → official-style M15
# frames via a locally-installed Card Conjurer (cc_frames.py); falls back to
# built-in if those assets aren't present.
_FRAME_STYLE = "builtin"

def set_frame_style(style: str) -> None:
    """Select the frame system for subsequent render_card() calls."""
    global _FRAME_STYLE
    _FRAME_STYLE = (style or "builtin").lower()


# ── Legibility: pick white vs black text by contrast against real pixels ───────
def _rel_luminance(rgb: tuple) -> float:
    """WCAG relative luminance of an sRGB colour (ignores any alpha)."""
    def _lin(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * _lin(rgb[0]) + 0.7152 * _lin(rgb[1]) + 0.0722 * _lin(rgb[2])


def _contrast_ratio(a: tuple, b: tuple) -> float:
    """WCAG contrast ratio between two colours (1.0 .. 21.0)."""
    la, lb = _rel_luminance(a), _rel_luminance(b)
    hi, lo = (la, lb) if la >= lb else (lb, la)
    return (hi + 0.05) / (lo + 0.05)


def _avg_region_rgb(canvas: Image.Image, box: tuple) -> Optional[tuple]:
    """Mean RGB of a canvas region, downsampled for speed/noise tolerance.
    Returns None if the box is degenerate or off-canvas."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(canvas.width, x1), min(canvas.height, y1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    region = canvas.crop((x0, y0, x1, y1)).convert("RGB")
    region.thumbnail((24, 12), Image.BILINEAR)
    px = list(region.getdata())
    n = len(px) or 1
    return (sum(p[0] for p in px) // n,
            sum(p[1] for p in px) // n,
            sum(p[2] for p in px) // n)


def _legible_text_color(canvas: Image.Image, box: tuple,
                        fallback: tuple = _DARK_TEXT) -> tuple:
    """Choose _LIGHT_TEXT or _DARK_TEXT for the best contrast against whatever is
    currently composited under `box`. Sampled AFTER frame/boxes/crown/border-theme
    are drawn, so tints are accounted for. Falls back to `fallback` (the static
    per-key colour) when the region can't be sampled."""
    bg = _avg_region_rgb(canvas, box)
    if bg is None:
        return fallback
    return (_LIGHT_TEXT
            if _contrast_ratio(_LIGHT_TEXT, bg) >= _contrast_ratio(_DARK_TEXT, bg)
            else _DARK_TEXT)


def _draw_legible_text(draw: "ImageDraw.ImageDraw", canvas: Image.Image,
                       pos: tuple, text: str, font, box: tuple, *,
                       anchor: str, fallback: tuple = _DARK_TEXT,
                       halo: bool = True) -> tuple:
    """Draw `text` in whichever of light/dark text reads best against the pixels
    under `box`, with a subtle opposite-colour halo so it never blends into a
    busy or mid-luminance bar. Returns the chosen foreground colour."""
    fg = _legible_text_color(canvas, box, fallback=fallback)
    stroke_w = max(1, round(_mm(0.06))) if halo else 0
    stroke_fill = None
    if stroke_w:
        halo_rgb = _DARK_TEXT if fg == _LIGHT_TEXT else _LIGHT_TEXT
        stroke_fill = (halo_rgb[0], halo_rgb[1], halo_rgb[2], 90)
    draw.text(pos, text, font=font, fill=fg, anchor=anchor,
              stroke_width=stroke_w, stroke_fill=stroke_fill)
    return fg

# ── Font helpers ───────────────────────────────────────────────────────────────
@lru_cache(maxsize=32)
def _beleren(size: int) -> ImageFont.FreeTypeFont:
    p = _FONTS / "beleren-bold_P1.01.ttf"
    if p.exists():
        return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size=size)

@lru_cache(maxsize=32)
def _mplantin(size: int) -> ImageFont.FreeTypeFont:
    p = _FONTS / "mplantin.ttf"
    if p.exists():
        return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size=size)

@lru_cache(maxsize=32)
def _mplantin_italic(size: int) -> ImageFont.FreeTypeFont:
    p = _FONTS / "MPlantin-Italic.ttf"
    if p.exists():
        return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size=size)


# ── P/T sizing (shared by the built-in renderer and cc_frames) ────────────────
# Real M15 P/T digits measure 0.0395 of card height (2X2 Marchesa scan, digit
# ink height / card height — they fill ~86% of the badge interior). All three
# frame systems previously rendered digits at roughly half that, which read as
# tiny numbers floating in an oversized badge.
_PT_INK_FRAC = 0.0395


@lru_cache(maxsize=1)
def _beleren_digit_ratio() -> float:
    """Digit ink height as a fraction of the font em size (measured once)."""
    try:
        bb = _beleren(100).getbbox("3")
        r = (bb[3] - bb[1]) / 100
        if 0.4 < r < 1.0:
            return r
    except Exception:
        pass
    return 0.71


def _pt_font_for(pt_str: str, max_w: int, canvas_h: int) -> ImageFont.FreeTypeFont:
    """Beleren sized so digits hit the real-card ink fraction, shrunk to fit
    max_w for long strings ('10/10', '13/13', '*/*')."""
    size = max(12, int(_PT_INK_FRAC * canvas_h / _beleren_digit_ratio()))
    font = _beleren(size)
    try:
        while font.getlength(pt_str) > max_w and size > 12:
            size = max(12, int(size * 0.92))
            font = _beleren(size)
    except Exception:
        pass
    return font

# ── SVG → PIL via pixie ───────────────────────────────────────────────────────
_SYM_CACHE: dict[tuple[str, int], Image.Image] = {}

# Custom themed mana pips (W/U/B/R/G/C → base RGBA image). When set via
# set_custom_pips(), these override the stock SVG symbols everywhere a mana
# symbol is drawn (cost row + inline oracle text). _CUSTOM_GEN versions the
# resize cache so swapping decks never serves a stale pip.
_CUSTOM_PIPS: dict[str, Image.Image] = {}
_CUSTOM_GEN = 0


def set_custom_pips(mapping: Optional[dict[str, Image.Image]]) -> None:
    """Install (or clear, with None/{}) per-deck custom mana pips."""
    global _CUSTOM_PIPS, _CUSTOM_GEN
    _CUSTOM_PIPS = dict(mapping) if mapping else {}
    _CUSTOM_GEN += 1


def _svg_sym(name: str, size: int) -> Optional[Image.Image]:
    """Rasterise a symbol SVG to a square PIL RGBA image at `size` px."""
    upper = name.upper()
    custom = _CUSTOM_PIPS.get(upper)
    if custom is not None:
        ckey = (f"__pip{_CUSTOM_GEN}__{upper}", size)
        cached = _SYM_CACHE.get(ckey)
        if cached is not None:
            return cached
        img = custom.resize((size, size), Image.LANCZOS)
        _SYM_CACHE[ckey] = img
        return img

    key = (upper, size)
    if key in _SYM_CACHE:
        return _SYM_CACHE[key]

    svg_path = _ASSETS / "symbols" / f"{name.upper()}.svg"
    if not svg_path.exists():
        return None
    try:
        import pixie, tempfile, os
        src = pixie.read_image(str(svg_path))
        # pixie.resize() does NOT modify in-place; create a new target image.
        # Use a temp file with a unique name so concurrent warm-up calls never
        # collide (pixie has no in-memory PNG encode path).
        dst = pixie.Image(size, size)
        ctx = dst.new_context()
        ctx.scale(size / src.width, size / src.height)
        ctx.draw_image(src, 0, 0)
        fd, tmp_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            dst.write_file(tmp_path)
            pil = Image.open(tmp_path).convert("RGBA").copy()
        finally:
            os.unlink(tmp_path)
        _SYM_CACHE[key] = pil
        return pil
    except Exception as e:
        print(f"  [renderer] SVG rasterise failed ({name}): {e}")
        return None


def _warm_symbol_cache() -> None:
    """
    Pre-rasterise every mana/tap symbol SVG at the two sizes used during rendering:
      • inline oracle text symbols  → _mm(2.4)
      • mana-cost pip row           → _mm(3.0)

    Called once at module import so per-card rendering never pays the SVG parse
    + pixie rasterise cost.  On an RTX 3090 machine this typically takes < 1 s
    for the ~30 symbols in card_assets/symbols/.
    """
    sym_dir = _ASSETS / "symbols"
    if not sym_dir.exists():
        return
    sizes = [_mm(2.4), _mm(3.0)]
    svgs  = list(sym_dir.glob("*.svg"))
    if not svgs:
        return
    loaded = 0
    for svg_path in svgs:
        name = svg_path.stem.upper()
        for sz in sizes:
            result = _svg_sym(name, sz)
            if result is not None:
                loaded += 1
    print(f"  [renderer] Symbol cache warmed: {loaded} rasters "
          f"({len(svgs)} symbols × {len(sizes)} sizes)")


# Called once at import time — all subsequent renders hit the dict directly.
_warm_symbol_cache()


# ── Mana parsing ──────────────────────────────────────────────────────────────
def _parse_mana(mana_str: str) -> list[str]:
    """Return list of mana symbol codes from a Scryfall mana cost string."""
    return re.findall(r"\{([^}]+)\}", mana_str)


# ── Colour key logic ──────────────────────────────────────────────────────────
_WUBRG = "WUBRG"

def _sort_colors(colors: list[str]) -> str:
    return "".join(sorted(colors, key=lambda c: _WUBRG.index(c) if c in _WUBRG else 99))

def _frame_key(colors: list[str], type_line: str) -> str:
    """Map card colours + type to the asset filename stem."""
    tl = (type_line or "").lower()
    if "land" in tl:
        return "Land"
    if not colors:
        if "artifact" in tl:
            return "Artifact"
        return "Colourless"
    if len(colors) == 1:
        return colors[0]
    if len(colors) == 2:
        return _sort_colors(colors)
    return "Gold"

def _box_key(frame_key: str) -> str:
    """Map the full frame key to the simpler boxes/pt_boxes filename stem."""
    if frame_key in ("W","U","B","R","G","Artifact","Colourless","Land"):
        return frame_key
    return "Gold"

def _crown_key(frame_key: str) -> str:
    """Map frame key to legendary crown filename (same folder, same names)."""
    return frame_key  # legendary_crowns has the same stems as frames


# ── Asset loader with caching ─────────────────────────────────────────────────
_IMG_CACHE: dict[str, Image.Image] = {}

def _load_asset(folder: str, stem: str) -> Optional[Image.Image]:
    key = f"{folder}/{stem}"
    if key in _IMG_CACHE:
        return _IMG_CACHE[key]
    p = _ASSETS / folder / f"{stem}.png"
    if not p.exists():
        # fallback: Gold or Colourless
        for fallback in ("Gold", "Colourless", "W"):
            fp = _ASSETS / folder / f"{fallback}.png"
            if fp.exists():
                p = fp
                break
        else:
            return None
    img = Image.open(p).convert("RGBA")
    _IMG_CACHE[key] = img
    return img


# ── Art fetch ─────────────────────────────────────────────────────────────────
def _fetch_scryfall_art(url: str, cache_key: str) -> Optional[Image.Image]:
    if not url:
        return None
    _ART_CACHE.mkdir(exist_ok=True)
    safe   = "".join(c if c.isalnum() else "_" for c in cache_key)[:64]
    cached = _ART_CACHE / f"{safe}.jpg"
    if cached.exists():
        try:
            # ⚠️ Caller must close() this image after use
            img = Image.open(cached)
            # Load image data immediately so file handle can be closed by PIL
            img.load()
            return img
        except Exception:
            cached.unlink(missing_ok=True)
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            cached.write_bytes(r.content)
            # ⚠️ Caller must close() this image after use
            img = Image.open(io.BytesIO(r.content))
            # Load data immediately to avoid file handle issues
            img.load()
            return img
    except Exception as e:
        print(f"  [renderer] Scryfall art fetch failed for {cache_key}: {e}")
    return None


# ── Inline-symbol text renderer ───────────────────────────────────────────────
_SYM_RE = re.compile(r"\{([^}]+)\}")


def _italic_regions(text: str) -> list[tuple[str, bool]]:
    """Split `text` into consecutive (segment, is_italic) runs where any
    parenthetical reminder text — including the parentheses — is italic.
    Paren depth is tracked across the whole string so reminders that contain
    '{T}'-style symbols or nested parens stay italic end-to-end; unbalanced
    parens are left upright."""
    runs: list[tuple[str, bool]] = []
    buf: list[str] = []
    cur = False          # italic flag of the run currently being accumulated
    depth = 0
    for ch in text:
        if ch == "(":
            ital = True
            depth += 1
        elif ch == ")":
            ital = depth > 0
            depth = max(0, depth - 1)
        else:
            ital = depth > 0
        if ital != cur and buf:
            runs.append(("".join(buf), cur))
            buf = []
        cur = ital
        buf.append(ch)
    if buf:
        runs.append(("".join(buf), cur))
    return runs


def _tokenise(text: str) -> list[tuple[str, str, bool]]:
    """Split text into ('text', str, italic) and ('sym', name, False) tokens.
    Reminder text in parentheses is flagged italic so it renders in MPlantin-
    Italic inline — not only when a whole paragraph is parenthetical."""
    tokens: list[tuple[str, str, bool]] = []
    for seg, ital in _italic_regions(text):
        pos = 0
        for m in _SYM_RE.finditer(seg):
            if m.start() > pos:
                tokens.append(("text", seg[pos:m.start()], ital))
            tokens.append(("sym", m.group(1), False))
            pos = m.end()
        if pos < len(seg):
            tokens.append(("text", seg[pos:], ital))
    return tokens


def _draw_oracle_text(
    img: Image.Image,
    text: str,
    x: int,
    y: int,
    max_w: int,
    max_h: int,
    sym_size: int,
    font_size: int,
    fg: tuple,
    center_v: bool = False,
) -> int:
    """
    Render oracle text with inline symbols into `img`.
    Automatically shrinks font/symbol to fit, or grows them for short text.
    When center_v=True the rendered block is vertically centred in max_h.
    Returns the final body font size, so flavor text can be drawn at the same
    size for a consistent look on a single card.
    """
    # ── Shrink phase: up to 8 attempts ────────────────────────────────────────
    for attempt in range(8):
        fnt_body   = _mplantin(font_size)
        fnt_italic = _mplantin_italic(font_size)
        lh = font_size + _mm(0.4)

        lines   = _build_oracle_lines(text, fnt_body, fnt_italic, sym_size, max_w)
        total_h = len(lines) * lh

        if total_h <= max_h or attempt == 7:
            break
        font_size = max(int(font_size * 0.88), 12)
        sym_size  = max(int(sym_size  * 0.88), 12)

    # ── Grow phase: expand for short text so it fills the box nicely ──────────
    if center_v and total_h < max_h * 0.55:
        for _ in range(5):
            new_fs   = min(int(font_size * 1.12), _mm(3.4))
            new_ss   = min(int(sym_size  * 1.12), _mm(3.4))
            new_body = _mplantin(new_fs)
            new_ital = _mplantin_italic(new_fs)
            new_lns  = _build_oracle_lines(text, new_body, new_ital, new_ss, max_w)
            new_lh   = new_fs + _mm(0.4)
            if len(new_lns) * new_lh > max_h * 0.82:
                break
            font_size, sym_size = new_fs, new_ss
            fnt_body   = new_body
            fnt_italic = new_ital
            lh         = new_lh
            lines      = new_lns
            total_h    = len(lines) * lh

    # ── Vertical centering ────────────────────────────────────────────────────
    start_y = y + max(0, (max_h - total_h) // 2) if center_v else y

    draw  = ImageDraw.Draw(img)
    cur_y = start_y
    for line_tokens in lines:
        if cur_y + lh > y + max_h:
            break
        _draw_line(draw, img, line_tokens, x, cur_y, sym_size,
                   fnt_body, fnt_italic, fg, lh)
        cur_y += lh
    return font_size


def _draw_flavor_text(
    img: Image.Image,
    text: str,
    x: int,
    y: int,
    max_w: int,
    max_h: int,
    font_size: int,
    fg: tuple,
) -> None:
    """Render flavor text in italic, vertically centred within the allocated area."""
    for attempt in range(5):
        fnt  = _mplantin_italic(font_size)
        lh   = font_size + _mm(0.35)
        words = text.split()
        lines: list[str] = []
        cur   = ""
        for w in words:
            test = f"{cur} {w}".strip()
            try:
                w_len = round(fnt.getlength(test))
            except Exception:
                w_len = len(test) * (font_size // 2)
            if w_len <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        total_h = len(lines) * lh
        if total_h <= max_h or attempt == 4:
            break
        font_size = max(int(font_size * 0.88), 12)

    start_y = y + max(0, (max_h - total_h) // 2)
    draw    = ImageDraw.Draw(img)
    cur_y   = start_y
    for line in lines:
        if cur_y + lh > y + max_h:
            break
        draw.text((x, cur_y), line, font=fnt, fill=fg)
        cur_y += lh


def _build_oracle_lines(
    text: str,
    font_body: ImageFont.FreeTypeFont,
    font_italic: ImageFont.FreeTypeFont,
    sym_size: int,
    max_w: int,
) -> list[list[tuple[str, str, bool]]]:
    """Word-wrap oracle text (with inline symbols + italic reminder spans) to
    fit within max_w pixels. Each line is a list of (kind, value, italic) tokens."""
    result = []
    for para in text.split("\n"):
        if not para.strip():
            result.append([])
            continue
        tokens = _tokenise(para)
        result.extend(_wrap_tokens(tokens, font_body, font_italic, sym_size, max_w))
    return result


def _token_width(
    token: tuple[str, str, bool],
    font_body: ImageFont.FreeTypeFont,
    font_italic: ImageFont.FreeTypeFont,
    sym_size: int,
) -> int:
    if token[0] == "sym":
        return sym_size + 2
    font = font_italic if token[2] else font_body
    try:
        return round(font.getlength(token[1]))
    except Exception:
        return len(token[1]) * (font.size // 2)


def _wrap_tokens(
    tokens: list[tuple[str, str, bool]],
    font_body: ImageFont.FreeTypeFont,
    font_italic: ImageFont.FreeTypeFont,
    sym_size: int,
    max_w: int,
) -> list[list[tuple[str, str, bool]]]:
    """Wrap a list of (kind, value, italic) tokens into lines of at most max_w px."""
    lines   = []
    cur_line: list[tuple[str, str, bool]] = []
    cur_w   = 0

    def flush():
        if cur_line:
            lines.append(list(cur_line))

    for token in tokens:
        if token[0] == "text":
            ital = token[2]
            # split on spaces, keeping spaces as part of following word
            words = re.split(r"(?<= )", token[1])
            for word in words:
                if not word:
                    continue
                w = _token_width(("text", word, ital), font_body, font_italic, sym_size)
                if cur_w + w > max_w and cur_line:
                    flush()
                    cur_line = []
                    cur_w = 0
                    word = word.lstrip(" ")
                    w = _token_width(("text", word, ital), font_body, font_italic, sym_size)
                cur_line.append(("text", word, ital))
                cur_w += w
        else:  # sym
            w = sym_size + 2
            if cur_w + w > max_w and cur_line:
                flush()
                cur_line = []
                cur_w = 0
            cur_line.append(token)
            cur_w += w

    flush()
    return lines


def _draw_line(
    draw: ImageDraw.ImageDraw,
    img: Image.Image,
    tokens: list[tuple[str, str, bool]],
    x: int,
    y: int,
    sym_size: int,
    font_body: ImageFont.FreeTypeFont,
    font_italic: ImageFont.FreeTypeFont,
    fg: tuple,
    lh: int,
) -> None:
    cx = x
    sym_y = y + (lh - sym_size) // 2
    for token in tokens:
        if token[0] == "text":
            font = font_italic if token[2] else font_body
            draw.text((cx, y), token[1], font=font, fill=fg)
            try:
                cx += round(font.getlength(token[1]))
            except Exception:
                cx += len(token[1]) * (font.size // 2)
        else:
            sym_img = _svg_sym(token[1], sym_size)
            if sym_img:
                img.paste(sym_img, (cx, sym_y), sym_img)
                cx += sym_size + 2
            else:
                # fallback: draw a small circle with the symbol letter
                r = sym_size // 2
                draw.ellipse([cx, sym_y, cx + sym_size, sym_y + sym_size],
                             fill=(140, 140, 140))
                draw.text((cx + r, sym_y + r), token[1][:2].upper(),
                          font=_mplantin(max(sym_size - 4, 10)), fill=(255, 255, 255),
                          anchor="mm")
                cx += sym_size + 2


# ── Mana pip row ──────────────────────────────────────────────────────────────
def _draw_mana_row(
    img: Image.Image,
    pips: list[str],
    right_x: int,
    centre_y: int,
    pip_size: int,
) -> int:
    """Draw mana pips right-aligned from right_x. Returns leftmost x used.

    Each pip gets a hard dark drop shadow offset down(-left) — real M15 cost
    rows have one (measured ≈+8.5%/−2% of pip diameter on a 2X2 scan); without
    it the discs read as pasted-on. Inter-pip gap is proportional (~3% of
    diameter — real pips nearly touch)."""
    cx = right_x
    gap   = max(2, round(pip_size * 0.03))
    sh_dx = -max(1, round(pip_size * 0.02))
    sh_dy = max(2, round(pip_size * 0.085))
    for sym in reversed(pips):
        sym_img = _svg_sym(sym, pip_size)
        if sym_img:
            px = cx - pip_size
            py = centre_y - pip_size // 2
            shadow = Image.new("RGBA", sym_img.size, (0, 0, 0, 255))
            shadow.putalpha(sym_img.getchannel("A"))
            img.paste(shadow, (px + sh_dx, py + sh_dy), shadow)
            img.paste(sym_img, (px, py), sym_img)
            cx = px - gap
        else:
            # fallback coloured circle
            draw = ImageDraw.Draw(img)
            px, py = cx - pip_size, centre_y - pip_size // 2
            draw.ellipse([px, py, px + pip_size, py + pip_size], fill=(140, 140, 140))
            draw.text((px + pip_size // 2, centre_y), sym[:2].upper(),
                      font=_beleren(max(pip_size - 8, 10)), fill=(255, 255, 255), anchor="mm")
            cx = px - gap
    return cx


# ── Border-theme decoration ───────────────────────────────────────────────────
# Each card gets sparse corner ornaments drawn on a transparent overlay and
# alpha-composited AFTER the frame but BEFORE oracle text.  The style is derived
# from a free-text description so users can type anything natural.

_BORDER_THEME_MAP: list[tuple[list[str], str, tuple]] = [
    (['vine','leaf','forest','nature','plant','druid','grove','growth','garden',
      'bloom','floral','flower','herb','fern','moss','jungle','swamp','root'],
     'vine', (55, 130, 45)),
    (['frost','ice','snow','winter','cold','frozen','crystal','glacier','blizzard','tundra'],
     'frost', (145, 205, 245)),
    (['fire','flame','ember','burn','heat','lava','volcano','inferno','blaze','torch','ash','cinder'],
     'flame', (255, 108, 25)),
    (['arcane','rune','mystical','spell','wizard','sigil','glyph','eldritch','cosmic','magic',
      'runic','astral','aether','arcana','mage'],
     'arcane', (148, 78, 218)),
    (['circuit','tech','cyber','steam','machine','robot','construct','mechanic','gear',
      'clock','pipe','punk','neon','wire','matrix'],
     'circuit', (35, 195, 195)),
    (['ocean','wave','sea','water','river','lake','tide','coral','nautical','aqua','marine',
      'flood'],
     'wave', (28, 115, 195)),
    (['shadow','dark','void','abyss','night','ghost','skull','bone','death','undead',
      'crypt','tomb','blood','horror','gothic','dread'],
     'shadow', (90, 50, 140)),
]
_BORDER_THEME_DEFAULT = ('ornate', (198, 162, 48))


def _classify_border_theme(desc: str) -> tuple[str, tuple]:
    t = desc.lower()
    for keywords, style, rgb in _BORDER_THEME_MAP:
        if any(k in t for k in keywords):
            return style, rgb
    return _BORDER_THEME_DEFAULT


# cx, cy = exact corner coordinate; sx/sy = direction signs (+1 = toward card interior)
# sz = ornament bounding size in px; col = RGBA; lw = line width

def _vine_corner(draw: ImageDraw.ImageDraw, cx: int, cy: int,
                  sx: int, sy: int, sz: int, col: tuple, lw: int) -> None:
    h = [
        (cx,                        cy),
        (cx + sx*int(sz*.28),       cy + sy*int(sz*.07)),
        (cx + sx*int(sz*.55),       cy + sy*int(sz*.18)),
        (cx + sx*int(sz*.76),       cy + sy*int(sz*.44)),
    ]
    draw.line(h, fill=col, width=lw)
    r = max(2, lw+1)
    draw.ellipse([h[-1][0]-r, h[-1][1]-r, h[-1][0]+r, h[-1][1]+r], fill=col)
    v = [
        (cx,                        cy),
        (cx + sx*int(sz*.09),       cy + sy*int(sz*.30)),
        (cx + sx*int(sz*.20),       cy + sy*int(sz*.58)),
        (cx + sx*int(sz*.36),       cy + sy*int(sz*.78)),
    ]
    draw.line(v, fill=col, width=lw)
    draw.ellipse([v[-1][0]-r, v[-1][1]-r, v[-1][0]+r, v[-1][1]+r], fill=col)
    m = h[2]
    bx = m[0] + sx*int(sz*.14)
    by = m[1] - sy*int(sz*.22)
    draw.line([m, (bx, by)], fill=col, width=max(1, lw-1))
    draw.ellipse([bx-r, by-r, bx+r, by+r], fill=col)
    cr = int(sz*.13)
    ac = (cx + sx*int(sz*.14), cy + sy*int(sz*.14))
    arc_map = {(1,1):(180,270), (-1,1):(270,360), (1,-1):(90,180), (-1,-1):(0,90)}
    a_s, a_e = arc_map.get((sx, sy), (180, 270))
    draw.arc([ac[0]-cr, ac[1]-cr, ac[0]+cr, ac[1]+cr], start=a_s, end=a_e,
             fill=col, width=max(1, lw-1))


def _frost_corner(draw: ImageDraw.ImageDraw, cx: int, cy: int,
                   sx: int, sy: int, sz: int, col: tuple, lw: int) -> None:
    de = (cx + sx*int(sz*.62), cy + sy*int(sz*.62))
    draw.line([(cx, cy), de], fill=col, width=lw)
    r = max(1, lw)
    draw.ellipse([de[0]-r, de[1]-r, de[0]+r, de[1]+r], fill=col)
    for frac, blen in ((0.35, 0.19), (0.60, 0.14)):
        px = cx + sx*int(sz*frac);  py = cy + sy*int(sz*frac)
        bp = int(sz*blen)
        for sign in (1, -1):
            draw.line([(px, py), (int(px + sign*sy*bp), int(py - sign*sx*bp))],
                      fill=col, width=max(1, lw-1))
    xe = (cx + sx*int(sz*.55), cy)
    draw.line([(cx, cy), xe], fill=col, width=lw)
    draw.ellipse([xe[0]-r, xe[1]-r, xe[0]+r, xe[1]+r], fill=col)
    tick = int(sz*.11)
    xmid = cx + sx*int(sz*.30)
    draw.line([(xmid, cy-tick), (xmid, cy+tick)], fill=col, width=max(1, lw-1))
    ye = (cx, cy + sy*int(sz*.55))
    draw.line([(cx, cy), ye], fill=col, width=lw)
    draw.ellipse([ye[0]-r, ye[1]-r, ye[0]+r, ye[1]+r], fill=col)
    ymid = cy + sy*int(sz*.30)
    draw.line([(cx-tick, ymid), (cx+tick, ymid)], fill=col, width=max(1, lw-1))


def _flame_corner(draw: ImageDraw.ImageDraw, cx: int, cy: int,
                   sx: int, sy: int, sz: int, col: tuple, lw: int) -> None:
    for i, deg in enumerate((18, 42, 68)):
        rad = math.radians(deg)
        ln = int(sz * (0.68 - i*0.08))
        ex = cx + sx*int(ln*math.cos(rad));  ey = cy + sy*int(ln*math.sin(rad))
        draw.line([(cx, cy), (ex, ey)], fill=col, width=max(1, lw-(i>0)))
        r = max(1, lw-1)
        draw.ellipse([ex-r, ey-r, ex+r, ey+r], fill=col)
    for rx, ry in ((0.34, 0.18), (0.52, 0.33), (0.22, 0.50), (0.58, 0.14), (0.14, 0.44)):
        spx = cx + sx*int(sz*rx);  spy = cy + sy*int(sz*ry)
        draw.ellipse([spx-1, spy-1, spx+2, spy+2], fill=col)


def _arcane_corner(draw: ImageDraw.ImageDraw, cx: int, cy: int,
                    sx: int, sy: int, sz: int, col: tuple, lw: int) -> None:
    arc_r = int(sz*.44)
    arc_map = {(1,1):(0,90), (-1,1):(90,180), (1,-1):(270,360), (-1,-1):(180,270)}
    a_s, a_e = arc_map.get((sx, sy), (0, 90))
    draw.arc([cx-arc_r, cy-arc_r, cx+arc_r, cy+arc_r],
             start=a_s, end=a_e, fill=col, width=lw)
    tick = int(sz*.07)
    for spx, spy in (
        (cx + sx*arc_r,              cy),
        (cx,                         cy + sy*arc_r),
        (cx + sx*int(arc_r*.707),   cy + sy*int(arc_r*.707)),
    ):
        draw.line([(spx-tick, spy), (spx+tick, spy)], fill=col, width=max(1, lw-1))
        draw.line([(spx, spy-tick), (spx, spy+tick)], fill=col, width=max(1, lw-1))
    r = max(2, lw+1)
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=col)


def _circuit_corner(draw: ImageDraw.ImageDraw, cx: int, cy: int,
                     sx: int, sy: int, sz: int, col: tuple, lw: int) -> None:
    sq = max(3, lw+1)
    t1m = (cx + sx*int(sz*.52), cy)
    t1e = (cx + sx*int(sz*.52), cy + sy*int(sz*.38))
    draw.line([(cx, cy), t1m, t1e], fill=col, width=lw)
    for px, py in (t1m, t1e):
        draw.rectangle([px-sq, py-sq, px+sq, py+sq], fill=col)
    t2m = (cx, cy + sy*int(sz*.52))
    t2e = (cx + sx*int(sz*.38), cy + sy*int(sz*.52))
    draw.line([(cx, cy), t2m, t2e], fill=col, width=lw)
    for px, py in (t2m, t2e):
        draw.rectangle([px-sq, py-sq, px+sq, py+sq], fill=col)
    p1 = (cx + sx*int(sz*.16), cy)
    p2 = (cx + sx*int(sz*.16), cy + sy*int(sz*.16))
    p3 = (cx + sx*int(sz*.32), cy + sy*int(sz*.16))
    draw.line([p1, p2, p3], fill=col, width=max(1, lw-1))
    draw.rectangle([p3[0]-sq+1, p3[1]-sq+1, p3[0]+sq-1, p3[1]+sq-1], fill=col)
    for px, py in (t1e, t2e):
        r = max(3, lw+2)
        draw.ellipse([px-r, py-r, px+r, py+r], outline=col, width=max(1, lw-1))


def _wave_corner(draw: ImageDraw.ImageDraw, cx: int, cy: int,
                  sx: int, sy: int, sz: int, col: tuple, lw: int) -> None:
    steps = 22
    pts_x = []
    for i in range(steps+1):
        t = i/steps
        pts_x.append((
            cx + sx*int(sz*t*.80),
            cy + sy*int(math.sin(t*math.pi*2.2)*sz*.11 + sz*.09),
        ))
    draw.line(pts_x, fill=col, width=lw)
    pts_y = []
    for i in range(steps+1):
        t = i/steps
        pts_y.append((
            cx + sx*int(math.sin(t*math.pi*2.2)*sz*.11 + sz*.09),
            cy + sy*int(sz*t*.80),
        ))
    draw.line(pts_y, fill=col, width=lw)
    r = max(2, lw)
    for rx, ry in ((0.24, 0.36), (0.44, 0.20), (0.15, 0.54)):
        dpx = cx + sx*int(sz*rx);  dpy = cy + sy*int(sz*ry)
        draw.ellipse([dpx-r, dpy-r, dpx+r, dpy+r], fill=col)


def _shadow_corner(overlay: Image.Image, cx: int, cy: int,
                    sx: int, sy: int, sz: int, col: tuple) -> None:
    draw = ImageDraw.Draw(overlay)
    base_r = int(sz*.52)
    base_a = col[3] if len(col) > 3 else 100
    for step in range(6):
        r = int(base_r*(1 - step*.13))
        a = max(0, int(base_a*(.65 - step*.10)))
        dx = cx + sx*int(sz*step*.04);  dy = cy + sy*int(sz*step*.04)
        draw.ellipse([dx-r, dy-r, dx+r, dy+r], fill=(*col[:3], a))
    wisp_a = max(0, int(base_a*.45))
    for x1r, y1r, x2r, y2r in ((0.28, 0.08, 0.58, 0.38), (0.08, 0.28, 0.38, 0.58)):
        draw.line([
            (cx + sx*int(sz*x1r), cy + sy*int(sz*y1r)),
            (cx + sx*int(sz*x2r), cy + sy*int(sz*y2r)),
        ], fill=(*col[:3], wisp_a), width=max(1, int(sz*.018)))


def _ornate_corner(draw: ImageDraw.ImageDraw, cx: int, cy: int,
                    sx: int, sy: int, sz: int, col: tuple, lw: int) -> None:
    bl = int(sz*.64)
    draw.line([(cx, cy), (cx + sx*bl, cy)], fill=col, width=lw)
    draw.line([(cx, cy), (cx, cy + sy*bl)], fill=col, width=lw)
    r = max(2, lw)
    for frac in (0.28, 0.52, 0.76):
        hx = cx + sx*int(bl*frac)
        draw.ellipse([hx-r, cy-r, hx+r, cy+r], fill=col)
        vy = cy + sy*int(bl*frac)
        draw.ellipse([cx-r, vy-r, cx+r, vy+r], fill=col)
    d = int(sz*.10)
    draw.polygon([(cx, cy-d), (cx+sx*d, cy), (cx, cy+sy*d), (cx-sx*d, cy)], fill=col)
    sr = int(sz*.20)
    sac = (cx + sx*int(sz*.14), cy + sy*int(sz*.14))
    arc_map = {(1,1):(180,270), (-1,1):(270,360), (1,-1):(90,180), (-1,-1):(0,90)}
    a_s, a_e = arc_map.get((sx, sy), (180, 270))
    draw.arc([sac[0]-sr, sac[1]-sr, sac[0]+sr, sac[1]+sr],
             start=a_s, end=a_e, fill=col, width=max(1, lw-1))


def _dispatch_corner(
    overlay: Image.Image,
    draw: ImageDraw.ImageDraw,
    style: str,
    cx: int, cy: int, sx: int, sy: int, sz: int, col: tuple, lw: int,
) -> None:
    if   style == 'vine':    _vine_corner(draw, cx, cy, sx, sy, sz, col, lw)
    elif style == 'frost':   _frost_corner(draw, cx, cy, sx, sy, sz, col, lw)
    elif style == 'flame':   _flame_corner(draw, cx, cy, sx, sy, sz, col, lw)
    elif style == 'arcane':  _arcane_corner(draw, cx, cy, sx, sy, sz, col, lw)
    elif style == 'circuit': _circuit_corner(draw, cx, cy, sx, sy, sz, col, lw)
    elif style == 'wave':    _wave_corner(draw, cx, cy, sx, sy, sz, col, lw)
    elif style == 'shadow':  _shadow_corner(overlay, cx, cy, sx, sy, sz, col)
    else:                    _ornate_corner(draw, cx, cy, sx, sy, sz, col, lw)


def _draw_border_theme(
    canvas: Image.Image,
    border_theme: str,
    intensity: float = 0.72,
) -> None:
    """Alpha-composite a thematic border decoration onto the card canvas.

    Visual layers:
      1. A FILLED band that covers the entire frame chrome perimeter, tinting
         it with the theme colour.  The chrome spans from BG_X to ART_X on
         each side (~22 px at output) — we fill it entirely so the effect
         survives the 3×→1× LANCZOS downscale and is immediately visible.
      2. Corner ornaments (style-specific) drawn over the chrome at each corner.
      3. Subtler corner ornaments at the oracle text-box corners.

    Called after the frame chrome is composited but before text is drawn.
    """
    if not (border_theme or "").strip():
        return

    style, rgb = _classify_border_theme(border_theme)
    alpha = int(255 * min(max(intensity, 0.05), 0.95))

    # ── Geometry: frame chrome dimensions ────────────────────────────────────
    # The chrome band runs between the outer card edge (BG_X/BG_Y) and the
    # inner content area (ART_X / just above ORA_Y+ORA_H).
    # We fill this band completely so it's visible after downscaling.
    chrome_h = _ART_X - _BG_X        # horizontal chrome width  ≈ 43 px at 3×
    chrome_v_top = _ART_Y - _BG_Y    # vertical chrome height (top) ≈ 166 px
    # The oracle text-box can extend to or past the BG bottom edge — clamp it.
    bg_bottom   = _BG_Y + _BG_H
    ora_bottom  = _ORA_Y + _ORA_H
    chrome_v_bot = bg_bottom - ora_bottom   # may be ≤ 0 if oracle runs to edge

    # ── Layer 1: chrome band fill ─────────────────────────────────────────────
    # Draw four filled rectangles, one for each side of the chrome band.
    # Each rect is fully opaque at the inner face and blends outward so the
    # coloured overlay tints the chrome without obliterating its texture.
    fill_col   = (*rgb, int(alpha * 0.68))  # main chrome tint

    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    # Left band
    draw.rectangle([_BG_X, _BG_Y, _BG_X + chrome_h, bg_bottom],
                   fill=fill_col)
    # Right band
    draw.rectangle([_BG_X + _BG_W - chrome_h, _BG_Y,
                    _BG_X + _BG_W,              bg_bottom],
                   fill=fill_col)
    # Top band (between the left/right bands)
    draw.rectangle([_BG_X + chrome_h,          _BG_Y,
                    _BG_X + _BG_W - chrome_h,  _BG_Y + chrome_v_top],
                   fill=fill_col)
    # Bottom band — only draw if oracle box doesn't reach the card edge
    if chrome_v_bot > 0:
        draw.rectangle([_BG_X + chrome_h,          ora_bottom,
                        _BG_X + _BG_W - chrome_h,  bg_bottom],
                       fill=fill_col)

    # Thin bright inner-edge line (inner face of the chrome, where it meets art)
    inner_lw = max(5, _mm(0.22))   # ~5 px at 3× → ~2.5 px at output
    inner_col = (*rgb, min(255, int(alpha * 1.2)))
    # Horizontal inner lines (constrained to span only between vertical bands)
    draw.line([(_BG_X + chrome_h, _BG_Y + chrome_v_top),
               (_BG_X + _BG_W - chrome_h, _BG_Y + chrome_v_top)],
              fill=inner_col, width=inner_lw)
    if chrome_v_bot > 0:
        draw.line([(_BG_X + chrome_h, ora_bottom),
                   (_BG_X + _BG_W - chrome_h, ora_bottom)],
                  fill=inner_col, width=inner_lw)
    # Vertical inner lines
    draw.line([(_BG_X + chrome_h, _BG_Y),
               (_BG_X + chrome_h, bg_bottom)],
              fill=inner_col, width=inner_lw)
    draw.line([(_BG_X + _BG_W - chrome_h, _BG_Y),
               (_BG_X + _BG_W - chrome_h, bg_bottom)],
              fill=inner_col, width=inner_lw)

    # ── Layer 2: corner ornaments at all four outer card corners ──────────────
    corner_lw  = max(5, _mm(0.22))
    corner_orn = _mm(9.0)   # ~204 px at 3× → ~106 px at output
    corner_col = (*rgb, int(alpha * 0.92))
    for cx, cy, sx, sy in (
        (_BG_X,           _BG_Y,          1,  1),
        (_BG_X + _BG_W,   _BG_Y,         -1,  1),
        (_BG_X,           _BG_Y + _BG_H,  1, -1),
        (_BG_X + _BG_W,   _BG_Y + _BG_H, -1, -1),
    ):
        _dispatch_corner(overlay, draw, style, cx, cy, sx, sy,
                         corner_orn, corner_col, corner_lw)

    # ── Layer 3: oracle text-box corner ornaments ─────────────────────────────
    text_col = (*rgb, int(alpha * 0.55))
    text_orn  = _mm(5.5)
    text_lw   = max(4, _mm(0.18))
    for cx, cy, sx, sy in (
        (_ORA_X,           _ORA_Y,          1,  1),
        (_ORA_X + _ORA_W,  _ORA_Y,         -1,  1),
        (_ORA_X,           _ORA_Y + _ORA_H, 1, -1),
        (_ORA_X + _ORA_W,  _ORA_Y + _ORA_H,-1, -1),
    ):
        _dispatch_corner(overlay, draw, style, cx, cy, sx, sy,
                         text_orn, text_col, text_lw)

    canvas.alpha_composite(overlay)


# ── Main render ───────────────────────────────────────────────────────────────
def render_card(
    card:         dict,
    themed_name:  str,
    oracle_text:  str,
    art_image:    Optional[Image.Image] = None,
    set_symbol:   Optional[Image.Image] = None,
    flavor_text:  str = "",
    border_theme: str = "",
) -> Image.Image:
    """
    Render a full MTG-style card.
    Returns a 750×1050 RGBA PIL Image.
    """
    # ── Optional: Card Conjurer frame packs from a locally-installed CC (assets
    # the user supplies themselves, like LoRAs/checkpoints). Selected per-build
    # via set_frame_style() — e.g. "m15" (regular) or "m15_fullart" (borderless
    # full-art). Requires MYTHFORGE_CC_DIR + the pack's assets present; any miss
    # falls through to the built-in frames.
    if _FRAME_STYLE != "builtin":
        try:
            import cc_frames
            if cc_frames.is_available(_FRAME_STYLE):
                _cc = cc_frames.render_card_cc(
                    card, themed_name, oracle_text,
                    art_image, set_symbol, flavor_text, border_theme,
                    style=_FRAME_STYLE)
                if _cc is not None:
                    return _cc
        except Exception as _e:
            print(f"  [render_card] CC frame render failed ({_e}); using built-in frames")

    colors    = card.get("color_identity", [])
    type_line = card.get("type_line", "")
    mana_cost = card.get("mana_cost", "") or ""
    power     = card.get("power")
    toughness = card.get("toughness")
    is_legendary = "Legendary" in (type_line or "")

    fk  = _frame_key(colors, type_line)
    bk  = _box_key(fk)
    bar_fg = _BAR_FG.get(fk, _DARK_TEXT)

    # ── 2× canvas ─────────────────────────────────────────────────────────────
    canvas = Image.new("RGBA", (_W2, _H2), (0, 0, 0, 255))

    # ── Layer 1: inner background ─────────────────────────────────────────────
    bg_img = _load_asset("bg", fk)
    if bg_img:
        bg_scaled = bg_img.resize((_BG_W, _BG_H), Image.LANCZOS)
        canvas.paste(bg_scaled, (_BG_X, _BG_Y), bg_scaled)

    # ── Layer 2: art image ────────────────────────────────────────────────────
    if art_image:
        art = ImageOps.fit(art_image.convert("RGBA"), (_ART_W, _ART_H), Image.LANCZOS)
    else:
        # plain dark gradient placeholder
        art = Image.new("RGBA", (_ART_W, _ART_H), (20, 18, 14, 255))
        d   = ImageDraw.Draw(art)
        d.text((_ART_W // 2, _ART_H // 2), themed_name,
               font=_beleren(_mm(2)), fill=(60, 55, 45, 255), anchor="mm")
    canvas.paste(art, (_ART_X, _ART_Y))

    # ── Layer 3: frame overlay ────────────────────────────────────────────────
    frame_img = _load_asset("frames", fk)
    if frame_img:
        fr_scaled = frame_img.resize((_FR_W, _FR_H), Image.LANCZOS)
        canvas.paste(fr_scaled, (_FR_X, _FR_Y), fr_scaled)

    # ── Layer 4: name bar (top-line boxes strip) ──────────────────────────────
    boxes_img = _load_asset("boxes", bk)
    if boxes_img:
        # Boxes PNG contains both name and type bar designs stacked.
        # top-line = top portion; mid-line (background-position: 0 bottom) = bottom portion
        boxes_w = _BAR_W
        boxes_h = round(boxes_img.height * (_BAR_W / boxes_img.width))
        boxes_scaled = boxes_img.resize((boxes_w, boxes_h), Image.LANCZOS)

        # Name bar: top slice
        name_slice = boxes_scaled.crop((0, 0, boxes_w, _BAR_H))
        canvas.paste(name_slice, (_BAR_X, _NAME_Y), name_slice)

        # Type bar: bottom slice (background-position: 0 bottom)
        type_slice = boxes_scaled.crop((0, boxes_h - _BAR_H, boxes_w, boxes_h))
        canvas.paste(type_slice, (_BAR_X, _TYPE_Y), type_slice)

    # ── Layer 5: legendary crown ──────────────────────────────────────────────
    if is_legendary:
        crown_img = _load_asset("legendary_crowns", _crown_key(fk))
        if crown_img:
            crown_h = round(crown_img.height * (_CROWN_W / crown_img.width))
            crown_scaled = crown_img.resize((_CROWN_W, crown_h), Image.LANCZOS)
            canvas.paste(crown_scaled, (_CROWN_X, _CROWN_Y), crown_scaled)

    # ── Layer 5.5: border theme decorations ───────────────────────────────────
    # Composited AFTER the frame chrome but BEFORE any text so decorations
    # never obscure card rules text or name bars.
    if border_theme:
        _draw_border_theme(canvas, border_theme)
        print(f"  [render_card] Applied border theme: {border_theme!r}")

    draw = ImageDraw.Draw(canvas)

    # ── Layer 6: name text + mana pips ────────────────────────────────────────
    # Check whether to show an original-card-name subtitle in the name bar
    original_name = (card.get("name") or "").strip()
    show_subtitle = bool(original_name and original_name != themed_name.strip())

    pips     = _parse_mana(mana_cost)
    pip_size = _mm(3.0)          # ≈ 45px at 2× — slightly smaller when subtitle present

    # Vertical anchor for name + pips:
    #   • Without subtitle → vertical centre of the bar
    #   • With subtitle    → upper 40 % of the bar, leaving room for subtitle below
    if show_subtitle:
        name_cy = _NAME_Y + round(_BAR_H * 0.33)   # upper third — leaves room for subtitle
    else:
        name_cy = _NAME_TY   # bar centre

    # Draw pips right-aligned; returns leftmost x used
    pip_right  = _BAR_X + _BAR_W - _mm(0.5)
    pip_left_x = _draw_mana_row(canvas, pips, pip_right, name_cy, pip_size)
    name_max_x = pip_left_x - _mm(0.5)

    # Main (themed) name
    name_font_size = _mm(2.6) if show_subtitle else _mm(2.8)
    name_font = _beleren(name_font_size)
    name_text = themed_name
    max_name_w = name_max_x - _NAME_TX
    try:
        # 1. Shrink font first (down to ~1.4mm / ~53% of default) before truncating
        min_font_size = _mm(1.4)
        while name_font.getlength(name_text) > max_name_w and name_font_size > min_font_size:
            name_font_size = max(int(name_font_size * 0.90), min_font_size)
            name_font = _beleren(name_font_size)
        # 2. Only truncate as a last resort if still too wide at minimum font size
        while name_font.getlength(name_text) > max_name_w and len(name_text) > 4:
            name_text = name_text[:-2] + "…"
    except Exception:
        pass
    # Choose white/black by contrast against the actual name-bar pixels (incl.
    # any border-theme tint), sampled under the text's own bounding box.
    _name_w   = max(name_font.getlength(name_text), _mm(6))
    name_box  = (_NAME_TX, name_cy - name_font_size * 0.5,
                 _NAME_TX + _name_w, name_cy + name_font_size * 0.5)
    bar_fg = _draw_legible_text(
        draw, canvas, (_NAME_TX, name_cy), name_text, name_font, name_box,
        anchor="lm", fallback=_BAR_FG.get(fk, _DARK_TEXT))

    # ── Original card name subtitle ────────────────────────────────────────────
    if show_subtitle:
        sub_size = _mm(1.55)      # ~23px at 2× → ~12px at final output
        sub_font = _mplantin_italic(sub_size)
        sub_text = original_name
        sub_max_w = _BAR_W - _mm(2.0)
        try:
            while sub_font.getlength(sub_text) > sub_max_w and len(sub_text) > 4:
                sub_text = sub_text[:-2] + "…"
        except Exception:
            pass
        # Draw centred, anchored to the bottom of the name bar
        # Use a slightly muted version of bar_fg for visual hierarchy
        sub_fg = tuple(
            max(0, min(255, int(c * 0.72 + 128 * 0.28)))
            for c in bar_fg[:3]
        )
        sub_cx = _BAR_X + _BAR_W // 2
        # Seat the subtitle inside the bar (baseline ~0.9 mm above the bottom edge)
        # so its descenders don't spill onto/below the name-bar border.
        sub_y  = _NAME_Y + _BAR_H - _mm(0.9)
        draw.text((sub_cx, sub_y), sub_text,
                  font=sub_font, fill=sub_fg, anchor="mb")

    # ── Layer 7: type line ────────────────────────────────────────────────────
    type_font_size = _mm(2.1)    # MPlantin at ~2.1mm
    type_font = _mplantin(type_font_size)
    type_text = type_line
    max_type_w = _BAR_W - _mm(8)
    try:
        # Shrink the font first so the FULL type (incl. the creature subtype after
        # "—") fits. Never split on "—" / drop the subtype — that silently turned
        # "Legendary Creature — Faerie Warlock" into "Legendary Creature".
        min_type_size = _mm(1.5)
        while type_font.getlength(type_text) > max_type_w and type_font_size > min_type_size:
            type_font_size = max(int(type_font_size * 0.92), min_type_size)
            type_font = _mplantin(type_font_size)
        # Only if still too wide at the smallest size, ellipsis-truncate the tail
        # (keeps the leading type + as much subtype as fits).
        while type_font.getlength(type_text) > max_type_w and len(type_text) > 4:
            type_text = type_text[:-2] + "…"
    except Exception:
        pass

    # Set symbol (right side of type bar)
    set_sym_size = _mm(3.2)
    set_sym_x    = _BAR_X + _BAR_W - set_sym_size - _mm(0.5)
    set_sym_y    = _TYPE_Y + (_BAR_H - set_sym_size) // 2
    if set_symbol:
        # Tint the symbol to the card's rarity metal (common=black, uncommon=
        # silver, rare=gold, mythic=orange) — the symbol image is a neutral relief.
        sym_img = set_symbol
        _rar = (card.get("rarity") or "").strip()
        if _rar:
            try:
                from set_symbol import colorize_by_rarity
                sym_img = colorize_by_rarity(set_symbol, _rar)
            except Exception:
                sym_img = set_symbol
        ss = sym_img.convert("RGBA").resize((set_sym_size, set_sym_size), Image.LANCZOS)
        canvas.paste(ss, (set_sym_x, set_sym_y), ss)

    _type_x   = _BAR_X + _mm(1.5)
    _type_w   = max(type_font.getlength(type_text), _mm(6))
    type_box  = (_type_x, _TYPE_TY - type_font_size * 0.5,
                 _type_x + _type_w, _TYPE_TY + type_font_size * 0.5)
    _draw_legible_text(
        draw, canvas, (_type_x, _TYPE_TY), type_text, type_font, type_box,
        anchor="lm", fallback=_BAR_FG.get(fk, _DARK_TEXT))

    # ── Layer 8: oracle text + flavor text ───────────────────────────────────
    oracle_fg  = _DARK_TEXT
    sym_size   = _mm(2.4)     # inline symbol size
    body_size  = _mm(2.2)     # MPlantin body font size

    ora_x = _ORA_X + _ORA_PAD
    ora_y = _ORA_Y + _ORA_PAD
    ora_w = _ORA_W - 2 * _ORA_PAD
    ora_h = _ORA_H - 2 * _ORA_PAD

    # Keep body text clear of the P/T badge (sits bottom-right). End the text
    # area just above the badge so flavor text never renders underneath it.
    if power is not None and toughness is not None:
        ora_h = min(ora_h, (_PT_Y - _mm(1.2)) - ora_y)

    has_oracle = bool((oracle_text or "").strip())
    has_flavor = bool((flavor_text or "").strip())

    if has_oracle and has_flavor:
        # Split: ~68 % rules text, thin separator, ~28 % flavor text
        rules_h = round(ora_h * 0.68)
        sep_gap = _mm(1.2)
        flav_y  = ora_y + rules_h + sep_gap
        flav_h  = ora_h - rules_h - sep_gap
    elif has_flavor and not has_oracle:
        rules_h = 0
        flav_y  = ora_y
        flav_h  = ora_h
    else:
        rules_h = ora_h
        flav_y  = 0
        flav_h  = 0

    rules_size = body_size
    if has_oracle:
        rules_size = _draw_oracle_text(
            canvas, oracle_text,
            ora_x, ora_y, ora_w, rules_h if rules_h else ora_h,
            sym_size, body_size, oracle_fg,
            center_v=True,
        )

    # Decorative separator between rules and flavor text
    if has_oracle and has_flavor:
        sep_y = ora_y + rules_h + _mm(0.55)
        sx1   = ora_x + _mm(3.5)
        sx2   = ora_x + ora_w - _mm(3.5)
        draw.line([(sx1, sep_y), (sx2, sep_y)],
                  fill=(110, 98, 78, 200), width=max(1, round(_mm(0.08))))

    if has_flavor and flav_h > 0:
        # Match the rules-text size so a single card never mixes sizes; fall
        # back to a default only when there's no rules text to match.
        flav_font = rules_size if has_oracle else _mm(1.85)
        _draw_flavor_text(
            canvas, flavor_text,
            ora_x, flav_y, ora_w, flav_h,
            flav_font, oracle_fg,
        )

    # ── Layer 9: P/T badge ────────────────────────────────────────────────────
    if power is not None and toughness is not None:
        pt_str = f"{power}/{toughness}"
        pt_img = _load_asset("pt_boxes", bk)
        if pt_img:
            pt_scaled = pt_img.resize((_PT_W, _PT_H), Image.LANCZOS)
            canvas.paste(pt_scaled, (_PT_X, _PT_Y), pt_scaled)
        else:
            draw.rounded_rectangle([_PT_X, _PT_Y, _PT_X + _PT_W, _PT_Y + _PT_H],
                                   radius=_mm(0.8), fill=(200, 185, 145))

        # Size digits to the real-card ink fraction, shrinking only when a long
        # string ("10/10", "*/*") would overflow the badge's inner width.
        pt_font = _pt_font_for(pt_str, _PT_W - _mm(3.0), _H2)
        pt_box  = (_PT_X, _PT_Y, _PT_X + _PT_W, _PT_Y + _PT_H)
        _draw_legible_text(
            draw, canvas, (_PT_X + _PT_W // 2, _PT_Y + _PT_H // 2),
            pt_str, pt_font, pt_box, anchor="mm", fallback=_DARK_TEXT)

    # ── Downscale 2× → 1× with LANCZOS ───────────────────────────────────────
    out = canvas.resize((CARD_W, CARD_H), Image.LANCZOS)
    return out


# ── Animated cards: composite a sequence of art frames into card frames ───────
def render_card_frames(
    card:         dict,
    themed_name:  str,
    oracle_text:  str,
    art_frames:   list,
    set_symbol:   Optional[Image.Image] = None,
    flavor_text:  str = "",
    border_theme: str = "",
) -> list:
    """
    Render one full card image per art frame, reusing render_card so the frame,
    text, mana symbols, crown and P/T stay pixel-identical across the sequence
    and only the ART moves. Honors the active frame style (built-in or M15 via
    set_frame_style) exactly like a normal render. Returns a list of 750×1050
    RGBA images, one per input art frame.

    This is the compositing half of the "animate card" feature: an image-to-video
    model produces `art_frames`; here each is dropped into the card's art window
    with the static chrome re-composited on top.
    """
    frames = []
    for art in art_frames:
        frames.append(render_card(
            card, themed_name, oracle_text,
            art_image=art, set_symbol=set_symbol,
            flavor_text=flavor_text, border_theme=border_theme,
        ))
    return frames


# ── Batch helpers ─────────────────────────────────────────────────────────────
def render_deck_thumbnails(
    commander_tc,
    deck_tcs: list,
    theme: str,
    art_paths: dict[str, Optional[Path]],
    output_dir: Path,
    oracle_overrides: Optional[dict[str, str]] = None,
    flavor_overrides: Optional[dict[str, str]] = None,
    border_theme: str = "",
    render_keys: Optional[dict[str, str]] = None,
) -> dict[str, Path]:
    """
    Render all unique cards as card-frame PNGs.
    Returns original_name → PNG path.

    oracle_overrides: original_name → processed oracle text (self-refs replaced)
    flavor_overrides: original_name → Ollama-generated flavor text
    render_keys: optional dict mapping original_name → render_key for PNG filename
    """
    from set_symbol import generate_set_symbol

    output_dir.mkdir(parents=True, exist_ok=True)
    sym    = generate_set_symbol(theme)
    saved: dict[str, Path] = {}

    all_tcs = [commander_tc] + deck_tcs
    seen: set[str] = set()
    total = len({tc.original_name for tc in all_tcs})
    idx   = 0

    for tc in all_tcs:
        name = tc.original_name
        if name in seen:
            continue
        seen.add(name)
        idx += 1

        art: Optional[Image.Image] = None

        ap = art_paths.get(name)
        if ap and Path(ap).exists():
            art = Image.open(ap)
        else:
            scryfall_url = (
                (tc.card.get("image_uris") or {}).get("art_crop") or
                (tc.card.get("image_uris") or {}).get("normal", "")
            )
            if scryfall_url:
                art = _fetch_scryfall_art(scryfall_url, name)

        try:
            safe = "".join(c if c.isalnum() else "_" for c in name)[:48]
            # Use render_key if provided (includes deck index for uniqueness)
            filename = render_keys.get(name, safe) if render_keys else safe
            out  = output_dir / f"{filename}.png"

            # Skip cards already rendered inline during the art-gen phase
            if out.exists():
                saved[name] = out
                print(f"  [renderer] [{idx}/{total}] {'cached':12s}  {name}")
                continue

            oracle  = (oracle_overrides or {}).get(name) or tc.card.get("oracle_text", "")
            flavor  = (flavor_overrides or {}).get(name) or ""
            card_img = render_card(
                tc.card, tc.themed_name, oracle,
                art_image=art, set_symbol=sym, flavor_text=flavor,
                border_theme=border_theme,
            )
            card_img.save(out, "PNG")
            card_img.close()  # Close the rendered card image
            saved[name] = out
            print(f"  [renderer] [{idx}/{total}] {'art' if art else 'placeholder':12s}  {name}")
        finally:
            # Always close the source art image to prevent handle leak
            if art is not None:
                art.close()

    return saved
