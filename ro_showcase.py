"""
Ragnarok Online v5 LoRA showcase — generates a few example cards that deliberately
invoke distinct RO job classes BY NAME (the capability v5 adds) across different
elements/races, then renders them into card frames. One-off; not part of the app.

Run: python ro_showcase.py
Output: ro_showcase/cards/*.png
"""
import os, sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from image_gen import ImageGen, GenSettings
from scryfall_client import ScryfallClient
import card_renderer
from card_renderer import render_card

CKPT = "illustrious-xl-v0.1.safetensors"   # RO preset requires Illustrious XL (SDXL)

# (real MTG card for frame/mana/type, RO themed name, RO-vocabulary art prompt).
# Prompt schema mirrors the preset's themer_vocabulary:
#   [medium], [element], [race], [job class tag], [scene], [composition suffix]
EXAMPLES = [
    ("Knight Exemplar", "Sir Aldric, Rune Vanguard",
     "fantasy card art, holy element, demihuman race, lord knight, a noble armored swordsman "
     "in gleaming silver plate raising a longsword high, heraldic banner, sunlit castle courtyard, "
     "full body portrait, painterly background, saturated colors"),
    ("Snapcaster Mage", "Lyra of the Geffen Tower",
     "fantasy card art, water element, demihuman race, high wizard, a young mage in flowing blue "
     "robes casting a glowing spell, swirling arcane runes, misty ancient library, "
     "full body action pose, vibrant background, jewel-tone palette"),
    ("Royal Assassin", "Veil, the Guillotine Shadow",
     "fantasy card art, shadow element, demihuman race, assassin cross, a hooded rogue with twin "
     "katars crouched in moonlit shadow, dark stone alley, glinting blades, "
     "full body action pose, vibrant background, jewel-tone palette"),
    ("Speaker of the Heavens", "Saint Freya, Radiant Bishop",
     "fantasy card art, holy element, angel race, arch bishop, a radiant priestess in white and "
     "gold vestments with great feathered wings, streaming holy light, grand cathedral, "
     "full body portrait, painterly background, saturated colors"),
]

def main():
    out = Path("ro_showcase"); (out / "art").mkdir(parents=True, exist_ok=True); (out / "cards").mkdir(parents=True, exist_ok=True)
    card_renderer.set_frame_style("builtin")
    sc = ScryfallClient()

    # Force the v5 illustrated LoRA (skip the random illustrated/pixel variant) so
    # every example cleanly demonstrates v5.
    gen_settings = GenSettings(lora_overrides=[{
        "filename": "ro_lora_v5.safetensors",
        "model_strength": 0.85, "clip_strength": 0.7,
        "trigger": "ragnarok online style, ro card art",
    }])
    gen = ImageGen(checkpoint=CKPT, art_style="ragnarok_online",
                   model_speed="quality", gen_settings=gen_settings)
    print(f"  available={gen.available} checkpoint={gen.checkpoint} face={gen.face_method}")
    if not gen.available:
        print("ComfyUI not available"); return

    for orig, themed, prompt in EXAMPLES:
        card = sc.get_card_by_name(orig, fuzzy=True)
        if not card:
            print(f"  ! could not fetch {orig}"); continue
        stem = "".join(c if c.isalnum() else "_" for c in themed)[:40]
        print(f"\n=== {themed}  (<= {card.get('name')}) ===")
        art_path = gen.generate(prompt, str(out / "art" / stem),
                                card_type=card.get("type_line", ""))
        if not art_path:
            print(f"  ! generation failed for {themed}"); continue
        from PIL import Image
        art_img = Image.open(art_path)
        card_img = render_card(card, themed, card.get("oracle_text", ""), art_image=art_img)
        dest = out / "cards" / f"{stem}.png"
        card_img.save(dest, "PNG")
        print(f"  saved {dest}")

if __name__ == "__main__":
    main()
