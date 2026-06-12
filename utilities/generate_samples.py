"""Sample-card generator — renders showcase cards from existing built decks.

For each deck job it picks the commander + 3 creatures + 3 spells + 3 lands
(only cards whose generated art is still on disk), re-renders them with the
CURRENT renderer (frame style, custom pips, border theme, rarity-tinted set
symbol all restored from deck.json), and writes:

    <out>/<label>/00_<Themed_Name>.png ... 09_<...>.png   (750×1050 each)
    <out>/<label>/contact_sheet.png                        (10-up overview)
    <out>/<label>/manifest.json                            (what was picked)

Usage:
    python utilities/generate_samples.py <job_id> [...]            # label = job id
    python utilities/generate_samples.py --manifest picks.json     # {label: job_id}
    [--out renders/sample_cards]

No GPU / LLM / network needed — pure PIL re-render from stored data.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

import card_renderer as cr
from set_symbol import generate_set_symbol

_BASICS = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes",
           "Snow-Covered Plains", "Snow-Covered Island", "Snow-Covered Swamp",
           "Snow-Covered Mountain", "Snow-Covered Forest"}


def sanitize(n: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in n)[:48]


def _cmc(c: dict) -> float:
    try:
        return float(c.get("cmc") or 0)
    except Exception:
        return 0.0


def pick_cards(deck: dict, slug: str) -> list[dict]:
    """Commander + 3 creatures + 3 spells + 3 lands, all with art on disk."""
    art_dir = Path("generated_art") / slug

    def has_art(c):
        n = c.get("original_name") or ""
        return bool(n) and (art_dir / f"{sanitize(n)}.png").exists()

    cards = [c for c in (deck.get("deck") or []) if has_art(c)]
    seen: set[str] = set()
    uniq = []
    for c in cards:
        n = c["original_name"]
        if n not in seen:
            seen.add(n)
            uniq.append(c)
    cards = uniq

    def tl(c):
        return c.get("type_line") or ""

    creatures = [c for c in cards if "Creature" in tl(c)]
    lands     = [c for c in cards if "Land" in tl(c) and "Creature" not in tl(c)]
    spells    = [c for c in cards if "Creature" not in tl(c) and "Land" not in tl(c)]

    picks: list[dict] = [deck["commander"]]

    # creatures: 1 legendary if available (crown showcase), rest by reminder
    # text presence then cmc — favors visually/texturally interesting cards.
    legs = sorted([c for c in creatures if "Legendary" in tl(c)], key=_cmc, reverse=True)
    rest = sorted([c for c in creatures if "Legendary" not in tl(c)],
                  key=lambda c: ("(" not in (c.get("oracle_text") or ""), -_cmc(c),
                                 c["original_name"]))
    cpick = (legs[:1] + rest)[:3]
    if len(cpick) < 3:
        cpick = (legs + rest)[:3]
    picks += cpick

    # spells: round-robin the type buckets so the trio shows variety
    buckets: dict[str, list[dict]] = {}
    for c in spells:
        for kind in ("Instant", "Sorcery", "Artifact", "Enchantment", "Planeswalker"):
            if kind in tl(c):
                buckets.setdefault(kind, []).append(c)
                break
        else:
            buckets.setdefault("Other", []).append(c)
    for b in buckets.values():
        b.sort(key=lambda c: (-_cmc(c), c["original_name"]))
    spick: list[dict] = []
    order = ["Instant", "Sorcery", "Artifact", "Enchantment", "Planeswalker", "Other"]
    while len(spick) < 3 and any(buckets.get(k) for k in order):
        for k in order:
            if buckets.get(k) and len(spick) < 3:
                spick.append(buckets[k].pop(0))
    picks += spick

    # lands: nonbasics first (themed names + subtitles), basics as filler
    nonbasic = sorted([c for c in lands if c["original_name"] not in _BASICS],
                      key=lambda c: c["original_name"])
    basic    = [c for c in lands if c["original_name"] in _BASICS]
    picks += (nonbasic + basic)[:3]
    return picks


def render_deck_samples(job: str, label: str, out_root: Path) -> Path:
    job_dir = Path("renders") / job
    deck = json.loads((job_dir / "deck.json").read_text(encoding="utf-8"))
    slug = deck.get("deck_slug") or ""
    art_dir = Path("generated_art") / slug
    out = out_root / label
    out.mkdir(parents=True, exist_ok=True)

    # per-deck renderer state (mirrors server._setup_deck_pips + build wiring)
    pip_dir = job_dir / "pips"
    pips = {}
    for code in ("W", "U", "B", "R", "G", "C"):
        p = pip_dir / f"pip_{code}.png"
        if p.exists():
            pips[code] = Image.open(p).convert("RGBA")
    cr.set_custom_pips(pips or None)
    cr.set_frame_style(deck.get("frame_style", "builtin"))
    theme = deck.get("theme") or deck.get("art_theme") or "fantasy"
    sym = generate_set_symbol(theme, emblem_prompt=deck.get("emblem_prompt") or "")
    border = deck.get("border_theme") or ""

    picks = pick_cards(deck, slug)
    manifest = {"job": job, "label": label, "slug": slug,
                "frame_style": deck.get("frame_style", "builtin"),
                "face_deck": bool(deck.get("face_key")),
                "theme": theme, "cards": []}
    thumbs = []
    for i, c in enumerate(picks):
        oname = c.get("original_name") or ""
        tname = c.get("themed_name") or oname
        card = {
            "name": oname,
            "type_line": c.get("type_line", ""),
            "mana_cost": c.get("mana_cost", "") or "",
            "color_identity": c.get("colors") or c.get("color_identity") or [],
            "power": c.get("power"),
            "toughness": c.get("toughness"),
            "rarity": c.get("rarity", ""),
        }
        art_p = art_dir / f"{sanitize(oname)}.png"
        art = Image.open(art_p).convert("RGBA") if art_p.exists() else None
        img = cr.render_card(card, tname, c.get("oracle_text", "") or "",
                             art_image=art, set_symbol=sym,
                             flavor_text=c.get("flavor_text", "") or "",
                             border_theme=border)
        fn = out / f"{i:02d}_{sanitize(tname)}.png"
        img.save(fn)
        thumbs.append(img)
        manifest["cards"].append({"i": i, "themed": tname, "original": oname,
                                  "type": card["type_line"], "file": fn.name})
        if art:
            art.close()
        print(f"  [{label}] {i:02d} {tname!r:44s} <= {oname!r}")

    # 10-up contact sheet (5×2) at 40 % scale for quick browsing
    tw, th = 300, 420
    sheet = Image.new("RGB", (tw * 5 + 36, th * 2 + 24), (24, 24, 28))
    for i, im in enumerate(thumbs):
        sheet.paste(im.convert("RGB").resize((tw, th), Image.LANCZOS),
                    (6 + (i % 5) * (tw + 6), 6 + (i // 5) * (th + 6)))
    sheet.save(out / "contact_sheet.png")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("jobs", nargs="*", help="render job ids (renders/<job>)")
    ap.add_argument("--manifest", help="JSON file mapping label -> job id")
    ap.add_argument("--out", default="renders/sample_cards", help="output root")
    args = ap.parse_args()

    targets: dict[str, str] = {}
    if args.manifest:
        targets.update(json.loads(Path(args.manifest).read_text(encoding="utf-8")))
    for j in args.jobs:
        targets[j] = j
    if not targets:
        ap.error("no jobs given (positional ids or --manifest)")

    out_root = Path(args.out)
    for label, job in targets.items():
        print(f"[samples] {label} <- renders/{job}")
        render_deck_samples(job, label, out_root)
    print(f"[samples] done -> {out_root}")


if __name__ == "__main__":
    main()
