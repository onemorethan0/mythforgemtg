"""
Exports a completed deck as:

  ZIP  — 100 individual PNG files (one per card slot, duplicates included for basics)
  PDF  — Print-ready US Letter pages, 3×3 grid @ 300 DPI
         Card size: 2.5" × 3.5" (exact standard MTG dimensions)
         Cut marks at every card corner for easy trimming

Card images resolve through an optional ``image_for(card)`` callable. The default
looks only in ``render_dir/cards/<render_key>.png``, which is empty for a deck
imported and saved WITHOUT AI art — so those exports came out as a near-empty ZIP
or an outright "No rendered card images found". The server passes a resolver that
falls back to the card's real Scryfall image, so an un-themed import is printable
the moment it's saved.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageDraw

# ── Print constants ────────────────────────────────────────────────────────────
DPI       = 300
PAGE_W_PX = int(8.5  * DPI)   # 2550
PAGE_H_PX = int(11.0 * DPI)   # 3300
CARD_W_PX = int(2.5  * DPI)   # 750
CARD_H_PX = int(3.5  * DPI)   # 1050
COLS      = 3
ROWS      = 3
PER_PAGE  = COLS * ROWS

# Center the card grid on the page
MARGIN_X  = (PAGE_W_PX - COLS * CARD_W_PX) // 2   # 150 px  (0.5" each side)
MARGIN_Y  = (PAGE_H_PX - ROWS * CARD_H_PX) // 2   #  75 px  (0.25" each side)


# ── PDF helpers ───────────────────────────────────────────────────────────────

def _cut_mark(draw: ImageDraw.ImageDraw, x: int, y: int, arm: int = 16) -> None:
    """Small cross cut guide at (x, y). Gap of 3px keeps it off the card edge."""
    gap = 3
    color = (160, 160, 160)
    draw.line([x - arm, y, x - gap, y], fill=color, width=1)
    draw.line([x + gap, y, x + arm, y], fill=color, width=1)
    draw.line([x, y - arm, x, y - gap], fill=color, width=1)
    draw.line([x, y + gap, x, y + arm], fill=color, width=1)


def _make_page(slots: list[Image.Image]) -> Image.Image:
    """Compose one letter-size page with up to 9 card images and cut marks."""
    page = Image.new("RGB", (PAGE_W_PX, PAGE_H_PX), (255, 255, 255))
    draw = ImageDraw.Draw(page)

    for i, card_img in enumerate(slots):
        col = i % COLS
        row = i // COLS
        x   = MARGIN_X + col * CARD_W_PX
        y   = MARGIN_Y + row * CARD_H_PX
        # Scale to exact print size — crop-preserving resize
        scaled = card_img.convert("RGB").resize((CARD_W_PX, CARD_H_PX), Image.LANCZOS)
        page.paste(scaled, (x, y))

    # Cut marks at every grid intersection (all 4×4 = 16 points)
    for r in range(ROWS + 1):
        for c in range(COLS + 1):
            _cut_mark(draw, MARGIN_X + c * CARD_W_PX, MARGIN_Y + r * CARD_H_PX)

    return page


# ── Public API ────────────────────────────────────────────────────────────────

ImageResolver = Callable[[dict], Optional[Path]]


def _default_resolver(render_dir: Path) -> ImageResolver:
    """Rendered-proxy-only lookup — the historical behaviour."""
    def _resolve(card: dict) -> Optional[Path]:
        png = render_dir / "cards" / f"{card.get('render_key', '')}.png"
        return png if png.exists() else None
    return _resolve


def build_zip(
    commander:  dict,
    deck:       list[dict],
    render_dir: Path,
    image_for:  Optional[ImageResolver] = None,
) -> bytes:
    """
    Return ZIP bytes with one PNG per card slot (100 files total).
    Commander is file 00, deck slots are 01-99.
    """
    resolve = image_for or _default_resolver(render_dir)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        png = resolve(commander)
        # A malformed/edge-case commander record without a render_key must not crash
        # the whole export — skip its art like any other missing-art card, rather than
        # raising an unhandled KeyError on the dict subscript.
        if png and not commander.get("render_key"):
            png = None
        if png:
            # A single custom card is a "deck of one": there is no commander and no
            # slot ordering, so name the entry after the card instead of shipping a
            # lone "00_commander_….png".
            if deck:
                zf.write(png, f"00_commander_{commander['render_key']}{png.suffix}")
            else:
                safe = "".join(c if c.isalnum() or c in " -_" else "_"
                               for c in (commander.get("themed_name")
                                         or commander.get("original_name") or "card"))[:60].strip()
                zf.write(png, f"{safe or 'card'}{png.suffix}")

        slot = 0
        for card in deck:
            png = resolve(card)
            render_key = card.get("render_key")
            if not png or not render_key:
                continue
            # Imported decks aggregate duplicate basics into one entry with a
            # quantity; emit one numbered copy per physical card so the proxy set
            # is complete (the art is identical, themed once).
            for copy in range(int(card.get("quantity", 1) or 1)):
                slot += 1
                suffix = f"_c{copy+1}" if card.get("quantity", 1) > 1 else ""
                zf.write(png, f"{slot:02d}_{render_key}{suffix}{png.suffix}")

    buf.seek(0)
    return buf.read()


def build_video_zip(
    commander:  dict,
    deck:       list[dict],
    render_dir: Path,
) -> bytes:
    """
    Return ZIP bytes containing the looping animations that exist for this deck
    (videos/<render_key>.{mp4,webp,gif}). Only cards that were animated are
    included; static cards are skipped. Files are slot-numbered like the PNG export.
    """
    videos_dir = render_dir / "videos"
    _EXTS = ("mp4", "webp", "gif")

    def _find(render_key):
        for ext in _EXTS:
            p = videos_dir / f"{render_key}.{ext}"
            if p.exists():
                return p, ext
        return None, None

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        path, ext = _find(commander["render_key"])
        if path:
            zf.write(path, f"00_commander_{commander['render_key']}.{ext}")
        slot = 0
        for card in deck:
            slot += 1
            path, ext = _find(card["render_key"])
            if path:
                zf.write(path, f"{slot:02d}_{card['render_key']}.{ext}")
    buf.seek(0)
    return buf.read()


def build_pdf(
    commander:  dict,
    deck:       list[dict],
    render_dir: Path,
    image_for:  Optional[ImageResolver] = None,
) -> bytes:
    """
    Return PDF bytes — US Letter, 3×3 card grid, 300 DPI, cut marks.
    100 card slots → ~12 pages.
    """
    resolve   = image_for or _default_resolver(render_dir)
    all_cards = [commander] + list(deck)

    imgs: list[Image.Image] = []
    for card in all_cards:
        png = resolve(card)
        if png:
            # .copy() closes the lazy file handle so we don't leak 100 open files
            # One printable slot per physical copy (imported duplicate basics).
            img = Image.open(png).copy()
            for _ in range(int(card.get("quantity", 1) or 1)):
                imgs.append(img)

    if not imgs:
        raise ValueError("No rendered card images found for this deck.")

    pages = [_make_page(imgs[i : i + PER_PAGE]) for i in range(0, len(imgs), PER_PAGE)]

    buf = io.BytesIO()
    pages[0].save(
        buf,
        format="PDF",
        save_all=True,
        append_images=pages[1:],
        resolution=DPI,
    )
    buf.seek(0)
    return buf.read()
