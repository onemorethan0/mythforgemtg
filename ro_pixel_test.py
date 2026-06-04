"""Confirm the RO pixel-sprite LoRA renders. Forces the pixel variant directly."""
import os, sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from image_gen import ImageGen, GenSettings
from scryfall_client import ScryfallClient
import card_renderer
from card_renderer import render_card
from PIL import Image

CKPT = "illustrious-xl-v0.1.safetensors"
PIX_TRIGGER = "pixel art, ragnarok online style, full body, simple background, white background"
EXAMPLES = [
    ("Knight Exemplar", "Pixel Knight of Prontera",
     "a knight in shining plate armor holding a longsword, heroic stance"),
    ("Snapcaster Mage", "Pixel Mage of Geffen",
     "a young wizard in blue robes holding a glowing staff, casting a spell"),
]

def main():
    out = Path("ro_showcase"); (out/"art").mkdir(parents=True, exist_ok=True); (out/"cards").mkdir(parents=True, exist_ok=True)
    card_renderer.set_frame_style("builtin")
    sc = ScryfallClient()
    gs = GenSettings(lora_overrides=[{
        "filename": "ro_pixel_sprite_lora.safetensors",
        "model_strength": 0.9, "clip_strength": 0.75, "trigger": PIX_TRIGGER,
    }])
    gen = ImageGen(checkpoint=CKPT, art_style="ragnarok_online", model_speed="quality", gen_settings=gs)
    print("available=", gen.available)
    for orig, themed, scene in EXAMPLES:
        card = sc.get_card_by_name(orig, fuzzy=True)
        stem = "PIXEL_" + "".join(c if c.isalnum() else "_" for c in themed)[:36]
        ap = gen.generate(f"{scene}", str(out/"art"/stem), card_type=card.get("type_line",""))
        if not ap: print("FAIL", themed); continue
        ci = render_card(card, themed, card.get("oracle_text",""), art_image=Image.open(ap))
        ci.save(out/"cards"/f"{stem}.png"); print("saved", stem)

if __name__ == "__main__":
    main()
