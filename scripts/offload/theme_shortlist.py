"""Narrow 43 themes to a handful of candidates per card, in code. No model involved."""
from __future__ import annotations
import os, re, sys
from pathlib import Path
ROOT = Path(r"C:\Users\rvn92\Documents\mtg_deck_builder")
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
os.environ.setdefault("MYTHFORGE_EDHREC_LIFT", "off")
import theme_match

# Payoff wording per theme, used ONLY to nominate candidates for the model to choose between.
# Deliberately loose — a false candidate costs one extra option in a multiple-choice prompt,
# while a missing candidate is unrecoverable.
CUES = {
    "aristocrats":  r"\bdies\b|\bsacrifice\b|put into a graveyard from the battlefield|whenever .{0,40}\bdie",
    "graveyard":    r"from your graveyard|in your graveyard|mill|return .{0,30}from .{0,20}graveyard",
    "reanimator":   r"return .{0,40}creature card .{0,30}graveyard .{0,20}battlefield|reanimat",
    "tokens":       r"\btoken\b|create .{0,20}token|creatures you control get",
    "counters":     r"\+1/\+1 counter|\bcounters? on\b|proliferate|charge counter",
    "spellslinger": r"instant or sorcery|instant and sorcery|whenever you cast .{0,25}(instant|sorcery)|magecraft",
    "artifacts":    r"\bartifact\b",
    "enchantress":  r"\benchantment\b|\baura\b",
    "auras":        r"\baura\b|enchanted creature",
    "lifegain":     r"you gain .{0,10}life|whenever you gain life|lifelink",
    "landfall":     r"\bland\b.{0,25}enters|landfall|additional land",
    "draw_matters": r"whenever you draw|second card you draw|if you.{0,20}drawn",
    "etb":          r"enters the battlefield|whenever .{0,30}enters",
    "voltron":      r"equipped creature|\bequip\b|attach",
    "voltron_combat": r"whenever .{0,25}attacks|double strike|deals combat damage",
    "theft":        r"gain control|you may cast .{0,20}from .{0,20}opponent|exile .{0,20}opponent",
    "group_hug":    r"each player draws|each opponent draws|players may",
    "energy":       r"\{E\}|energy counter",
    "impulse":      r"exile the top|play .{0,20}from the top|from among them",
    "face_down":    r"morph|manifest|disguise|face down",
    "sagas":        r"\bSaga\b|lore counter",
    "chaos":        r"at random|coin|vote|goad",
}
_TRIBAL = re.compile(r"^tribal_(.+)$")


def shortlist(card: dict, limit: int = 4) -> list[str]:
    text = f"{card.get('oracle_text') or ''}"
    tl = card.get("type_line") or ""
    scored: dict[str, int] = {}

    for theme, pat in CUES.items():
        if re.search(pat, text, re.I):
            scored[theme] = scored.get(theme, 0) + 2

    # A tribal theme is a candidate only when the rules TEXT names that creature type — a card
    # that merely IS a Dragon is not dragon tribal, which is the taxonomy's own rule.
    for theme in theme_match.THEMES:
        m = _TRIBAL.match(theme)
        if not m:
            continue
        word = m.group(1).rstrip("s")
        if re.search(rf"\b{word}s?\b", text, re.I):
            scored[theme] = scored.get(theme, 0) + 3

    # theme_match already scores a card against every theme locally; use it as a second,
    # independent nominator so a cue-list gap does not silently drop a real candidate.
    for theme in theme_match.THEMES:
        # theme_match scores the TYPE LINE too, so it nominates tribal_wizards for any card
        # that merely IS a Wizard — the exact inference the taxonomy forbids, and the model
        # then dutifully picks the tribe over the real archetype (it did, for Baral and Belbe).
        # Only the text-based cue above may nominate a tribal theme.
        if _TRIBAL.match(theme):
            continue
        try:
            s = theme_match.theme_score(card, theme)
        except Exception:
            continue
        if s and s >= theme_match.STRONG:
            scored[theme] = scored.get(theme, 0) + 2
        elif s:
            scored[theme] = scored.get(theme, 0) + 1

    if "creature" not in tl.casefold():
        for t in ("voltron_combat", "voltron"):
            scored.pop(t, None)

    return [t for t, _ in sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]
