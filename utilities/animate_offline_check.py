"""Offline validation of the animate-card compositing + MP4 encode path.

Synthesizes a fake "I2V" frame sequence from a card's STILL art (a gentle
Ken-Burns push-in + drift + brightness shimmer), composites each frame through
card_renderer.render_card_frames(), and encodes a looping MP4 — proving the
frame/text stays crisp while the art moves, with NO GPU/video model needed.

Usage:
    python utilities/animate_offline_check.py            # one builtin + one borderless deck
    python utilities/animate_offline_check.py <job_id> <original_name>
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageEnhance

import card_renderer as cr
import card_video as cv
from set_symbol import generate_set_symbol

OUT = Path("renders/anim_check")


def sanitize(n):
    return "".join(c if c.isalnum() else "_" for c in n)[:48]


def synth_frames(art: Image.Image, n: int = 24) -> list:
    """Fake cinemagraph: smooth push-in + drift + faint brightness oscillation,
    looping back to the start (so the standalone clip is seamless even before
    ping-pong)."""
    W, H = art.size
    frames = []
    for i in range(n):
        t = i / n
        ease = 0.5 - 0.5 * math.cos(2 * math.pi * t)       # 0→1→0, loops
        zoom = 1.0 + 0.07 * ease
        dx = int(0.02 * W * math.sin(2 * math.pi * t))
        dy = int(0.015 * H * ease)
        cw, ch = int(W / zoom), int(H / zoom)
        cx = (W - cw) // 2 + dx
        cy = (H - ch) // 2 + dy
        cx = max(0, min(W - cw, cx)); cy = max(0, min(H - ch, cy))
        fr = art.crop((cx, cy, cx + cw, cy + ch)).resize((W, H), Image.LANCZOS)
        fr = ImageEnhance.Brightness(fr).enhance(1.0 + 0.05 * ease)
        frames.append(fr)
    return frames


def run(job: str, want_name: str, label: str):
    d = json.loads(Path(f"renders/{job}/deck.json").read_text(encoding="utf-8"))
    slug = d.get("deck_slug")
    art_dir = Path("generated_art") / slug
    cr.set_frame_style(d.get("frame_style", "builtin"))

    # custom pips, if any
    pips = {}
    for code in ("W", "U", "B", "R", "G", "C"):
        p = Path(f"renders/{job}/pips/pip_{code}.png")
        if p.exists():
            pips[code] = Image.open(p).convert("RGBA")
    cr.set_custom_pips(pips or None)
    sym = generate_set_symbol(d.get("theme") or "fantasy",
                              emblem_prompt=d.get("emblem_prompt") or "")

    src = [d["commander"]] + d["deck"]
    card = next((c for c in src if (c.get("original_name") or "") == want_name), None)
    assert card, f"{want_name} not in {job}"
    art_p = art_dir / f"{sanitize(card['original_name'])}.png"
    art = Image.open(art_p).convert("RGBA")

    cd = {"name": card["original_name"], "type_line": card.get("type_line", ""),
          "mana_cost": card.get("mana_cost", "") or "",
          "color_identity": card.get("colors") or [], "power": card.get("power"),
          "toughness": card.get("toughness"), "rarity": card.get("rarity", "")}

    art_frames = synth_frames(art, n=24)
    card_frames = cr.render_card_frames(
        cd, card.get("themed_name", card["original_name"]),
        card.get("oracle_text", "") or "", art_frames, set_symbol=sym,
        flavor_text=card.get("flavor_text", "") or "",
        border_theme=d.get("border_theme", "") or "")

    OUT.mkdir(parents=True, exist_ok=True)
    mp4 = OUT / f"{label}.mp4"
    cv.encode_loop_mp4(card_frames, mp4, fps=24, loop=True)
    # also dump a mid frame to eyeball text crispness
    card_frames[len(card_frames) // 2].convert("RGB").save(OUT / f"{label}_midframe.png")
    print(f"[anim-check] {label}: {len(card_frames)} frames -> {mp4} "
          f"({mp4.stat().st_size // 1024} KB), midframe saved")


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        run(sys.argv[1], sys.argv[2], "custom")
    else:
        run("3d06c4b9f1c447f5", "Najeela, the Blade-Blossom", "builtin_najeela")
        run("532317b8f7ee4def", "Marchesa, the Black Rose", "borderless_marchesa")
    print("[anim-check] done")
