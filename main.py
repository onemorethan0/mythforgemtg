#!/usr/bin/env python3
"""
Commander Deck Builder — fully local pipeline
  • Card data  : Scryfall API
  • Text gen   : llama.cpp via llama-swap (:8010) / qwen3:14b
  • Image gen  : ComfyUI + local SDXL checkpoint

Three inputs only:
  1. Commander name   (fuzzy Scryfall search)
  2. Playstyle        (optional — auto-detected from commander oracle text)
  3. Art theme        (free-text description)
"""
import sys
from pathlib import Path

from app_paths         import app_path
from scryfall_client    import ScryfallClient
from commander_analysis import build_commander_profile
from deck_builder       import DeckBuilder, compute_stats
from playstyle          import PLAYSTYLES, prompt_playstyle, resolve_themes, get_slot_adjustments
from themer             import Themer, ThemedCard, export_themed_deck
from image_gen          import ImageGen


# ── Formatting ────────────────────────────────────────────────────────────────

def _fmt_mana(mana_cost: str) -> str:
    return (mana_cost or "").replace("{", "").replace("}", "")


def _safe_filename(s: str, maxlen: int = 40) -> str:
    out = "".join(c if c.isalnum() or c in "_-" else "_" for c in s)
    return out[:maxlen].strip("_")


# ── Deck display ──────────────────────────────────────────────────────────────

def print_decklist(
    commander_tc: ThemedCard,
    deck_tcs:     list[ThemedCard],
    stats:        dict,
    art_paths:    dict[str, Path | None] | None = None,
) -> None:
    categories: dict[str, list[ThemedCard]] = {
        "Lands": [], "Creatures": [], "Artifacts": [], "Enchantments": [],
        "Instants": [], "Sorceries": [], "Planeswalkers": [], "Other": [],
    }
    cat_order = [
        "Lands", "Creatures", "Artifacts", "Enchantments",
        "Instants", "Sorceries", "Planeswalkers", "Other",
    ]

    for tc in deck_tcs:
        tl = tc.card.get("type_line", "")
        if   "Land"        in tl: categories["Lands"].append(tc)
        elif "Creature"    in tl: categories["Creatures"].append(tc)
        elif "Artifact"    in tl: categories["Artifacts"].append(tc)
        elif "Enchantment" in tl: categories["Enchantments"].append(tc)
        elif "Instant"     in tl: categories["Instants"].append(tc)
        elif "Sorcery"     in tl: categories["Sorceries"].append(tc)
        elif "Planeswalker"in tl: categories["Planeswalkers"].append(tc)
        else:                     categories["Other"].append(tc)

    print("\n" + "=" * 76)
    mc = _fmt_mana(commander_tc.card.get("mana_cost", ""))
    art_marker = " [art✓]" if (art_paths or {}).get(commander_tc.original_name) else ""
    print(f"  COMMANDER{art_marker}")
    print(f"  {commander_tc.themed_name:<44} [{mc}]")
    if commander_tc.flavor_text:
        print(f"    \"{commander_tc.flavor_text}\"")
    print(f"    Originally: {commander_tc.original_name}")

    for cat in cat_order:
        tcs = categories[cat]
        if not tcs:
            continue
        sorted_tcs = sorted(tcs, key=lambda t: (t.card.get("cmc", 0), t.themed_name))
        print(f"\n  {cat.upper()} ({len(sorted_tcs)})")
        print(f"  {'Themed Name':<44} {'Original':<32} Cost")
        print(f"  {'-'*44}  {'-'*30}  {'-'*10}")

        seen:    dict[str, int]       = {}
        ordered: list[ThemedCard]     = []
        for tc in sorted_tcs:
            n = tc.original_name
            if n not in seen:
                seen[n] = 0
                ordered.append(tc)
            seen[n] += 1

        for tc in ordered:
            count = seen[tc.original_name]
            cnt   = f"{count}x" if count > 1 else "1 "
            mc    = _fmt_mana(tc.card.get("mana_cost", ""))
            art_mark = " ✓" if (art_paths or {}).get(tc.original_name) else ""
            print(f"  {cnt} {tc.themed_name:<42}{art_mark}  {tc.original_name:<30}  {mc}")
            if tc.flavor_text:
                print(f"       \"{tc.flavor_text}\"")

    print("\n" + "=" * 76)
    print(f"  {stats['total_cards']} cards  |  "
          f"Avg CMC {stats['average_cmc']}  |  "
          f"{stats['land_count']} lands")
    print("=" * 76)


def print_stats(stats: dict) -> None:
    print("\n  TYPE BREAKDOWN")
    for t, n in sorted(stats["type_counts"].items(), key=lambda x: -x[1]):
        bar = "█" * (n // 2)
        print(f"    {t:<15} {n:>3}  {bar}")

    print("\n  MANA CURVE (non-land)")
    curve = stats["cmc_curve"]
    if curve:
        peak = max(curve.values())
        for mv, cnt in sorted(curve.items()):
            bar = "█" * max(1, round(cnt * 28 / peak))
            print(f"    MV {mv:>2}  {cnt:>3}  {bar}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 76)
    print("  Commander Deck Builder  |  llama.cpp + ComfyUI + Scryfall  |  100% local")
    print("=" * 76)

    # ── 1. Commander ──────────────────────────────────────────────────────────
    raw_input = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else ""
    if not raw_input:
        raw_input = input("\n  Enter commander name: ").strip()
    if not raw_input:
        print("  Nothing entered. Exiting.")
        sys.exit(1)

    client = ScryfallClient()
    print(f"\n  Searching Scryfall for '{raw_input}'...")
    card = client.get_card_by_name(raw_input, fuzzy=True)

    if not card:
        print(f"  Not found: '{raw_input}'. Check spelling and try again.")
        sys.exit(1)

    legalities = card.get("legalities", {})
    if legalities.get("commander") not in ("legal", "restricted"):
        print(f"\n  Warning: '{card['name']}' may not be legal as a commander.")
        if input("  Continue anyway? [y/N]: ").strip().lower() != "y":
            sys.exit(0)

    # Show commander card
    print(f"\n  ┌─ {card['name']}  {card.get('mana_cost','')}")
    print(f"  │  {card.get('type_line','')}")
    for line in (card.get("oracle_text") or "").split("\n"):
        print(f"  │  {line}")

    profile = build_commander_profile(card)

    # ── 2. Playstyle ──────────────────────────────────────────────────────────
    playstyle_key  = prompt_playstyle()
    ps_data        = PLAYSTYLES[playstyle_key]
    active_themes  = resolve_themes(playstyle_key, profile.themes)
    slot_overrides = get_slot_adjustments(playstyle_key)

    # ── 3. Art theme ──────────────────────────────────────────────────────────
    print("\n  Describe the visual / art theme for your deck.")
    print("  Examples:")
    print("    'dark gothic necromancer ruling a city of the dead'")
    print("    'neon cyberpunk samurai in a corporate dystopia'")
    print("    'ancient Egyptian god-pharaoh commanding undead legions'")
    art_theme = input("\n  Theme: ").strip()
    if not art_theme:
        art_theme = f"epic fantasy art, {card['name']} as the hero"
        print(f"  (defaulting to: {art_theme})")

    # ── Build the deck ────────────────────────────────────────────────────────
    print("\n" + "─" * 76)
    builder = DeckBuilder(client)
    deck    = builder.build(
        profile,
        theme_override = active_themes,
        slot_overrides = slot_overrides,
        playstyle_label = ps_data["label"],
    )
    stats = compute_stats(card, deck)

    # ── Theme via the local LLM (llama.cpp via llama-swap, or Ollama) ─────────
    print("\n" + "─" * 76)
    themed_commander: ThemedCard | None = None
    themed_deck:      list[ThemedCard] | None = None

    try:
        themer = Themer()
        themed_commander, themed_deck = themer.theme_deck(art_theme, card, deck)
    except RuntimeError as e:
        from themer import LLM_BACKEND, llm_endpoint_base
        _llm = "llama.cpp" if LLM_BACKEND == "llamacpp" else "Ollama"
        print(f"\n  {_llm} unavailable at {llm_endpoint_base()} — {e}")
        print("  Continuing with original card names.")
    except Exception as e:
        print(f"\n  Theming error: {e}")
        print("  Continuing with original card names.")

    # Fallback — wrap raw cards as ThemedCards with original names
    if themed_commander is None:
        def _plain(c: dict) -> ThemedCard:
            return ThemedCard(c["name"], c["name"], "", "", c)
        themed_commander = _plain(card)
        themed_deck      = [_plain(c) for c in deck]

    # ── Generate art via ComfyUI ──────────────────────────────────────────────
    print("\n" + "─" * 76)
    art_paths: dict[str, Path | None] = {}

    gen = ImageGen()
    if gen.available:
        deck_slug = _safe_filename(card["name"])
        gen_choice = input(
            "\n  Generate card art with ComfyUI?\n"
            "  [a]ll cards  /  [c]ommander only  /  [n]o: "
        ).strip().lower()

        if gen_choice == "c":
            path = gen.generate(
                themed_commander.art_prompt,
                str(app_path("generated_art") / deck_slug / "commander"),
            )
            art_paths[themed_commander.original_name] = path
            if path:
                print(f"  Commander art saved: {path}")

        elif gen_choice == "a":
            art_paths = gen.generate_deck(themed_commander, themed_deck, deck_slug)
    else:
        print("  ComfyUI not running or no checkpoint loaded — skipping art generation.")
        print("  Start ComfyUI Desktop and download a checkpoint to enable art gen.")

    # ── Display ───────────────────────────────────────────────────────────────
    print_decklist(themed_commander, themed_deck, stats, art_paths)
    print_stats(stats)

    # ── Export ────────────────────────────────────────────────────────────────
    print()
    choice = input(
        "  Export?\n"
        "  [t]hemed full export  /  [m]oxfield plain text  /  [n]o: "
    ).strip().lower()

    safe_cmd   = _safe_filename(card["name"])
    safe_theme = _safe_filename(art_theme[:30])

    if choice == "t":
        path = f"{safe_cmd}_{safe_theme}_themed.txt"
        export_themed_deck(themed_commander, themed_deck, art_theme, path)

    elif choice == "m":
        path = f"{safe_cmd}_EDH.txt"
        counts: dict[str, int] = {}
        for c in deck:
            counts[c["name"]] = counts.get(c["name"], 0) + 1
        lines = [f"// Commander", f"1 {card['name']}", "", "// Deck"]
        for name, cnt in sorted(counts.items()):
            lines.append(f"{cnt} {name}")
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        print(f"\n  Exported to: {path}")


if __name__ == "__main__":
    main()
