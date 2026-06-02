"""
Dependency-free smoke tests for the pure-logic helpers that back the themer,
frame adapter, and renderer. No Ollama / ComfyUI / network required.

Run:  python tests/test_smoke.py    (exit 0 = all pass, 1 = failure)

These lock in behaviour that was previously verified only by one-off manual
checks: commander-name bleed/respelling guard, tribe reskin in type lines and
rules text, commander-tribe auto-detect, mana parsing, frame-key mapping, and
white-vs-black text legibility.
"""
import os
import sys

# Import from the repo root regardless of where pytest/python is invoked.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import themer
import cc_frames
import card_renderer as cr

_fails = []


def check(name, got, want):
    if got != want:
        _fails.append(f"{name}: got {got!r}, want {want!r}")


def check_true(name, cond):
    if not cond:
        _fails.append(f"{name}: expected True")


# ── _commander_tribe: skip the generic "Human" race, honor override ──────────
def test_commander_tribe():
    ct = themer._commander_tribe
    check("tribe.human_wizard", ct({"type_line": "Legendary Creature — Human Wizard"}), "Wizard")
    check("tribe.human_cleric", ct({"type_line": "Legendary Creature — Human Cleric"}), "Cleric")
    check("tribe.cat",          ct({"type_line": "Legendary Creature — Cat"}), "Cat")
    check("tribe.elf_druid",    ct({"type_line": "Legendary Creature — Elf Druid"}), "Elf")
    check("tribe.override",     ct({"type_line": "Legendary Creature — Human Wizard"}, "dragon"), "Dragon")
    check("tribe.typeless",     ct({"type_line": "Legendary Artifact"}), "")


# ── _name_too_close: catch respellings of the commander, spare distinct names ─
def test_name_too_close():
    f = themer._name_too_close
    tok = ["Krenko"]
    for w in ("Kretno", "Krenkor", "Krenko"):
        check_true(f"close.{w}", f(w, tok))
    for w in ("Glitch", "Chrome", "Sparkbound", "Kraken", "Vael"):
        check(f"far.{w}", f(w, tok), False)
    check_true("close.Arahba", f("Arahba", ["Arahbo"]))


# ── tribe reskin in rules text (plural-aware, whole-word) ────────────────────
def test_tribal_text():
    f = themer._apply_tribal_map_to_text
    m = {"Knight": "Cowboy"}
    check("text.equip",  f("Equipment you control have equip Knight {0}.", m),
          "Equipment you control have equip Cowboy {0}.")
    check("text.plural", f("Knights you control get +1/+1.", m),
          "Cowboys you control get +1/+1.")
    check("text.boundary", f("A Knightly order.", m), "A Knightly order.")
    check("text.empty", f("", m), "")
    check("text.nomap", f("Knights attack.", {}), "Knights attack.")


def test_tribal_type_line():
    f = themer._apply_tribal_map_to_type_line
    check("tl.knight", f("Legendary Creature — Human Knight", {"Knight": "Cowboy"}),
          "Legendary Creature — Human Cowboy")
    check("tl.noncreature", f("Instant", {"Knight": "Cowboy"}), "Instant")


def test_parse_mana():
    check("mana.cost", cr._parse_mana("{3}{W}{B}"), ["3", "W", "B"])
    check("mana.empty", cr._parse_mana(""), [])


# ── cc_frames frame-key mapping (per spec) ───────────────────────────────────
def test_frame_key():
    fk = cc_frames._cc_frame_key
    reg = cc_frames._M15
    check("fk.mono_r",  fk(["R"], "Creature — Dragon", reg), "R")
    check("fk.multi",   fk(["W", "U", "B"], "Legendary Creature — Angel", reg), "M")
    check("fk.land",    fk([], "Land", reg), "L")
    check("fk.artifact",fk([], "Artifact", reg), "A")  # M15 regular has no plain C frame
    full = cc_frames._M15_FULLART
    check("fk.colorless_fullart", fk([], "Creature — Eldrazi", full), "C")  # full-art has C


# ── white-vs-black legibility picker ─────────────────────────────────────────
def test_legibility():
    from PIL import Image
    light = cr._LIGHT_TEXT
    dark = cr._DARK_TEXT
    # contrast sanity
    check_true("legib.contrast_blackwhite", cr._contrast_ratio((0, 0, 0), (255, 255, 255)) > 20)
    # dark canvas -> light text ; light canvas -> dark text
    black = Image.new("RGBA", (40, 40), (10, 10, 10, 255))
    white = Image.new("RGBA", (40, 40), (245, 245, 245, 255))
    box = (0, 0, 40, 40)
    check("legib.on_dark",  cr._legible_text_color(black, box, fallback=dark), light)
    check("legib.on_light", cr._legible_text_color(white, box, fallback=dark), dark)


# ── theme detection: oracle-only, no false tribal from the type line ─────────
def test_theme_detection():
    import commander_analysis as ca
    det = ca._detect_themes
    # "Human Knight" who rewards Knights+Equipment must NOT be Human-tribal.
    syr = det({"type_line": "Legendary Creature — Human Knight",
               "oracle_text": "Other Knights you control get +1/+1. Whenever Syr Gwyn attacks, "
                              "attach target Equipment to a Knight. Equip costs you pay cost 0 less."})
    check_true("theme.knight",   "tribal_knights" in syr)
    check_true("theme.voltron",  "voltron" in syr)
    check("theme.not_human",     "tribal_humans" in syr, False)
    # "Phyrexian Angel" proliferate commander must be counters, not Angel-tribal.
    atx = det({"type_line": "Legendary Creature — Phyrexian Angel Horror",
               "oracle_text": "At the beginning of your end step, proliferate."})
    check_true("theme.counters",  "counters" in atx)
    check("theme.not_angel",      "tribal_angels" in atx, False)
    # Aura/voltron commander detected (was previously nothing).
    lp = det({"type_line": "Legendary Creature — Fox Advisor",
              "oracle_text": "Whenever you cast an Aura spell, search your library for an Aura."})
    check_true("theme.auras", "auras" in lp)


def main():
    for fn in (test_commander_tribe, test_name_too_close, test_tribal_text,
               test_tribal_type_line, test_parse_mana, test_frame_key, test_legibility,
               test_theme_detection):
        try:
            fn()
        except Exception as e:  # a thrown error is a failure, not a crash
            _fails.append(f"{fn.__name__}: raised {type(e).__name__}: {e}")
    if _fails:
        print("FAIL ({} issue(s)):".format(len(_fails)))
        for f in _fails:
            print("  -", f)
        sys.exit(1)
    print("OK - all smoke tests passed")


if __name__ == "__main__":
    main()
