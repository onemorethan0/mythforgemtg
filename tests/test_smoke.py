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
    # Reskinning a subtype drops the unmapped race word: "Human Knight" -> "Cowboy"
    # (not "Human Cowboy"), so hybrids like "Squirrel Warrior" read cleanly.
    check("tl.knight", f("Legendary Creature — Human Knight", {"Knight": "Cowboy"}),
          "Legendary Creature — Cowboy")
    check("tl.multiword", f("Creature — Elf Warrior", {"Warrior": "Samurai Oni"}),
          "Creature — Samurai Oni")
    check("tl.unmapped_kept", f("Creature — Human Wizard", {"Knight": "Cowboy"}),
          "Creature — Human Wizard")
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
    # Meren: "another creature you control dies" + "in your graveyard" phrasing
    # used to match nothing — must be aristocrats + reanimator now.
    meren = det({"type_line": "Legendary Creature — Human Shaman",
                 "oracle_text": "Whenever another creature you control dies, you get an "
                 "experience counter. Choose target creature card in your graveyard. "
                 "Return it to the battlefield."})
    check_true("theme.meren_aristocrats", "aristocrats" in meren)
    check_true("theme.meren_reanimator", "reanimator" in meren)
    # Tovolar: "Human Werewolves" transform text must NOT read as Human tribal;
    # it's Werewolf/Wolf.
    tov = det({"type_line": "Legendary Creature — Werewolf",
               "oracle_text": "Whenever a Wolf or Werewolf you control deals combat damage "
               "to a player, draw a card. Transform any number of Human Werewolves you control."})
    check_true("theme.tovolar_werewolf", "tribal_werewolves" in tov)
    check("theme.tovolar_not_human",     "tribal_humans" in tov, False)
    # Najeela: Warriors + attack triggers.
    naj = det({"type_line": "Legendary Creature — Human Warrior",
               "oracle_text": "Whenever a Warrior attacks, create a 1/1 white Warrior "
               "creature token. There is an additional combat phase."})
    check_true("theme.najeela_warrior", "tribal_warriors" in naj)
    # Slivers are a recognized tribe.
    slv = det({"type_line": "Legendary Creature — Sliver",
               "oracle_text": "Sliver creatures you control have cascade."})
    check_true("theme.sliver", "tribal_slivers" in slv)


# ── imported-deck bracket analysis ───────────────────────────────────────────
def test_deck_analysis():
    import deck_analysis as da
    def cd(n, cmc=3, tl="Creature", o=""):
        return {"name": n, "cmc": cmc, "type_line": tl, "oracle_text": o}
    # No power signals -> casual (Bracket 2).
    casual = da.analyze_deck(None, [cd("Grizzly Bears"), cd("Forest", 0, "Basic Land")])
    check("analysis.casual", casual["estimated_bracket"], 2)
    # Mass land destruction forces Bracket >=4.
    mld = da.analyze_deck(None, [cd("Armageddon", 4, "Sorcery", "Destroy all lands.")])
    check_true("analysis.mld>=4", mld["estimated_bracket"] >= 4)
    check_true("analysis.mld_listed", "Armageddon" in mld["signals"]["mass_land_destruction"])
    # 2 Game Changers -> Bracket 3, and they show in scale_down.
    up = da.analyze_deck(None, [cd("Rhystic Study", 3), cd("Cyclonic Rift", 7)])
    check("analysis.gc->3", up["estimated_bracket"], 3)
    check_true("analysis.gc_listed", "Rhystic Study" in up["signals"]["game_changers"])
    # Land ramp is NOT counted as a tutor.
    ramp = da.analyze_deck(None, [cd("Cultivate", 3, "Sorcery",
        "Search your library for up to two basic land cards, reveal them, put one onto the battlefield tapped.")])
    check("analysis.ramp_not_tutor", len(ramp["signals"]["tutors"]), 0)


# ── Ragnarok Online race / job-class mapping (v5 LoRA by-name targeting) ──────
def test_ro_race_class():
    f = themer._ro_race_class
    # creature subtype -> (race, class)
    check("ro.knight",    f("Legendary Creature — Human Knight"),   ("demihuman race", "lord knight"))
    check("ro.wizard",    f("Creature — Human Wizard"),             ("demihuman race", "high wizard"))
    check("ro.cleric",    f("Creature — Human Cleric"),             ("demihuman race", "arch bishop"))
    check("ro.assassin",  f("Creature — Human Assassin"),           ("demihuman race", "guillotine cross"))
    check("ro.elf_druid", f("Creature — Elf Druid"),                ("demihuman race", "sorcerer"))
    # race-only (no clean class mapping)
    check("ro.dragon",    f("Creature — Dragon"),                   ("dragon race", ""))
    check("ro.angel",     f("Legendary Creature — Angel"),          ("angel race", ""))
    check("ro.zombie",    f("Creature — Zombie"),                   ("undead race", ""))
    check("ro.beast",     f("Creature — Beast"),                    ("brute race", ""))
    # creature with no subtype -> demihuman fallback, no class
    check("ro.no_subtype", f("Creature"),                           ("demihuman race", ""))
    # non-creatures -> nothing
    check("ro.instant",   f("Instant"),                             ("", ""))
    check("ro.land",      f("Land"),                                ("", ""))
    check("ro.artifact",  f("Artifact"),                            ("", ""))
    # subtype precedence: class derives from the job subtype even with a race word
    check("ro.zombie_wizard", f("Creature — Zombie Wizard"),        ("undead race", "high wizard"))


def main():
    for fn in (test_commander_tribe, test_name_too_close, test_tribal_text,
               test_tribal_type_line, test_parse_mana, test_frame_key, test_legibility,
               test_theme_detection, test_deck_analysis, test_ro_race_class):
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
