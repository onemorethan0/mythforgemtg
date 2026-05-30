#!/usr/bin/env python
"""
Render one sample card via card_renderer.render_card and save zoom crops of the
regions that usually have layout bugs (title bar, flavor + P/T badge). Use this to
verify card_renderer.py changes instead of eyeballing the full 750x1050 card.

Run from the repo root. Writes <out>, <out>_top.png, <out>_br.png.

  python .claude/skills/mythforge/scripts/render_card_test.py --out /tmp/card.png
  # exercise a long flavor + a power/toughness creature (stresses the P/T overlap):
  python .claude/skills/mythforge/scripts/render_card_test.py --pt 5/5 \
    --flavor "Her blade remembers every oath sworn in the dark, and every traitor who broke one."
"""
import argparse, os, sys
from pathlib import Path

# Running a script file puts the script's dir on sys.path, not the cwd. Add the
# cwd (expected to be the repo root) so `import card_renderer` resolves.
sys.path.insert(0, os.getcwd())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="Syr Gwyn, Hero of Ashvale", help="original (Scryfall) name -> subtitle")
    ap.add_argument("--themed", default="D, Light of the Caverns", help="themed name -> title")
    ap.add_argument("--type", dest="type_line", default="Legendary Creature — Human Knight")
    ap.add_argument("--mana", default="{3}{R}{W}")
    ap.add_argument("--colors", default="R,W", help="color identity, comma list")
    ap.add_argument("--oracle", default="First strike, vigilance. Whenever this attacks, target Knight or Equipment you control gets +1/+1 until end of turn.")
    ap.add_argument("--flavor", default="Her blade remembers every oath sworn in the dark.")
    ap.add_argument("--pt", default="5/5", help="power/toughness like 5/5, or '' for non-creature")
    ap.add_argument("--out", default="/tmp/card.png")
    args = ap.parse_args()

    try:
        import card_renderer as cr
    except Exception as e:
        sys.exit(f"Run from the repo root so 'import card_renderer' works ({e})")
    from PIL import Image

    card = {
        "name": args.name,
        "color_identity": [c for c in args.colors.split(",") if c],
        "type_line": args.type_line,
        "mana_cost": args.mana,
    }
    if args.pt and "/" in args.pt:
        p, t = args.pt.split("/", 1)
        card["power"], card["toughness"] = p, t

    img = cr.render_card(card, themed_name=args.themed, oracle_text=args.oracle,
                         flavor_text=args.flavor)
    out = Path(args.out)
    img.save(out)
    # Title bar (top) and flavor+P/T (bottom-right) zoomed for inspection.
    img.crop((0, 0, 750, 200)).resize((1500, 400), Image.LANCZOS).save(out.with_name(out.stem + "_top.png"))
    img.crop((380, 760, 750, 1010)).resize((740, 500), Image.LANCZOS).save(out.with_name(out.stem + "_br.png"))
    print(f"saved {out} ({img.size}), plus _top and _br crops — read them to inspect layout")

if __name__ == "__main__":
    main()
