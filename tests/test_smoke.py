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
    # When MULTIPLE subtypes map (all-tribes auto-reskin), collapse to ONE — the
    # trailing token (MTG lists race then class, so it's the job/class).
    check("tl.collapse_last", f("Creature — Human Knight", {"Human": "Demihuman", "Knight": "Lord Knight"}),
          "Creature — Lord Knight")
    check("tl.collapse_generic", f("Creature — Elf Warrior", {"Elf": "Chrome Sentinel", "Warrior": "Steel Blade"}),
          "Creature — Steel Blade")


def test_subject_directives():
    # With a tribal_map active (auto-reskin default ON), non-creature permanents
    # must NOT be labelled "a creature of the theme world". Each card type gets its
    # own subject directive; only Artifact CREATURES stay creatures.
    cards = [
        {"name": "Sol Ring",      "type_line": "Artifact",                              "oracle_text": "{T}: Add {C}{C}.", "cmc": 1},
        {"name": "Skullclamp",    "type_line": "Artifact — Equipment",                  "oracle_text": "+1/-1",            "cmc": 1},
        {"name": "Copter",        "type_line": "Artifact — Vehicle",                    "oracle_text": "Flying",           "cmc": 2},
        {"name": "Tower",         "type_line": "Land",                                  "oracle_text": "Add mana.",        "cmc": 0},
        {"name": "Study",         "type_line": "Enchantment",                           "oracle_text": "draw a card",      "cmc": 3},
        {"name": "Wurmcoil",      "type_line": "Artifact Creature — Phyrexian Wurm",    "oracle_text": "deathtouch",       "cmc": 6, "power": "6", "toughness": "6"},
    ]
    p = themer._batch_prompt_v2("neon city", "Hero", cards, tribal_map={"Wurm": "Iron Leviathan"})
    line = {ln.split("|")[1]: ln.split("|")[2] for ln in p.splitlines() if ln[:2].rstrip("|").isdigit() and "|" in ln}
    check_true("subj.artifact_object",  "OBJECT" in line["Sol Ring"])
    check_true("subj.equipment_object", "OBJECT" in line["Skullclamp"] and "equipment" in line["Skullclamp"].lower())
    check_true("subj.vehicle_object",   "OBJECT" in line["Copter"] and "vehicle" in line["Copter"].lower())
    check_true("subj.land_place",       "PLACE" in line["Tower"])
    check_true("subj.enchantment_aura", "AURA" in line["Study"])
    # Non-creatures are NEVER called "a creature of the theme world"
    for nm in ("Sol Ring", "Skullclamp", "Copter", "Tower", "Study"):
        check_true(f"subj.not_creature.{nm}", "a creature of the theme world" not in line[nm])
    # Artifact CREATURE still reskins as a creature/being
    check_true("subj.artifact_creature", "reskin" in line["Wurmcoil"] and "Iron Leviathan" in line["Wurmcoil"])


def test_artifact_object_kind():
    f = themer._artifact_object_kind
    check_true("aok.equipment", "equipment" in f(["Equipment"]).lower())
    check_true("aok.vehicle",   "vehicle"  in f(["Vehicle"]).lower())
    check_true("aok.token",     "token"    in f(["Treasure"]).lower())
    check_true("aok.default",   "relic"    in f([]).lower() or "device" in f([]).lower())


def test_ro_tribal_map():
    # Deterministic RO reskin: jobs/monsters/races, one per type (no LLM).
    m = themer._generate_ro_tribal_map(
        ["Knight", "Wizard", "Cleric", "Cat", "Elf", "Dragon", "Zombie", "Merfolk", "Goblin", "Spirit"])
    check("ro.knight",  m["Knight"],  "Lord Knight")
    check("ro.wizard",  m["Wizard"],  "High Wizard")
    check("ro.cleric",  m["Cleric"],  "Arch Bishop")
    check("ro.cat",     m["Cat"],     "Brute")      # beast → brute monster race
    check("ro.elf",     m["Elf"],     "Demihuman")
    check("ro.dragon",  m["Dragon"],  "Dragon")
    check("ro.zombie",  m["Zombie"],  "Undead")
    check("ro.merfolk", m["Merfolk"], "Fish")
    check("ro.goblin",  m["Goblin"],  "Demon")
    check("ro.spirit",  m["Spirit"],  "Formless")


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
    check("ro.knight",    f("Legendary Creature — Human Knight"),   ("demihuman race", "lord_knight_(ragnarok_online)"))
    check("ro.wizard",    f("Creature — Human Wizard"),             ("demihuman race", "high_wizard_(ragnarok_online)"))
    check("ro.cleric",    f("Creature — Human Cleric"),             ("demihuman race", "arch_bishop_(ragnarok_online)"))
    check("ro.assassin",  f("Creature — Human Assassin"),           ("demihuman race", "assassin_cross_(ragnarok_online)"))
    check("ro.elf_druid", f("Creature — Elf Druid"),                ("demihuman race", "sorcerer_(ragnarok_online)"))
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
    check("ro.zombie_wizard", f("Creature — Zombie Wizard"),        ("undead race", "high_wizard_(ragnarok_online)"))


def test_ro_class_override():
    f = themer._ro_class_from_text
    # UI picker format "<Class> class, ..." — works for ANY class generically
    check("ovr.pick_monk",   f("Monk class, wearing a cowboy hat"), "monk_(ragnarok_online)")
    check("ovr.pick_lk",     f("Lord Knight class, in gold armor"), "lord_knight_(ragnarok_online)")
    check("ovr.pick_arch",   f("Archbishop class"),                 "arch_bishop_(ragnarok_online)")  # alias
    check("ovr.pick_gx",     f("Guillotine Cross class, hooded"),   "guillotine_cross_(ragnarok_online)")
    check("ovr.pick_super",  f("Super Novice class"),               "super_novice_(ragnarok_online)")
    # Free text (no "class" word) — keyword fallback
    check("ovr.monk",   f("a monk wearing a cowboy hat"), "monk_(ragnarok_online)")
    check("ovr.champion", f("transcendent champion"),     "champion_(ragnarok_online)")
    check("ovr.archbishop", f("an arch bishop of light"), "arch_bishop_(ragnarok_online)")
    # no class word -> no override
    check("ovr.none",   f("a brave hero on a hill"),      "")
    check("ovr.empty",  f(""),                            "")


# ── creature-floor planning (deck_builder) ───────────────────────────────────
def test_creature_floor_plan():
    from deck_builder import DeckBuilder
    p = DeckBuilder._creature_floor_plan
    # Support leads: trim theme hard (→10), reserve ~20 bodies (Syr Gwyn/Sram bug).
    check("floor.voltron",     p(["voltron", "tribal_knights"]), (10, 20))
    check("floor.auras",       p(["auras"]),                     (10, 20))
    check("floor.enchantress", p(["enchantress"]),               (10, 20))
    # Creature-hungry leads: keep most of the theme, reserve a high floor (Meren).
    check("floor.aristocrats", p(["aristocrats", "reanimator"]), (15, 22))
    check("floor.reanimator",  p(["reanimator"]),                (15, 18))
    # Sac/reanimator riding shotgun under a NON-aggro lead → modest trim + floor
    # (Korvold counters+aristocrats, 14 creatures → 20).
    check("floor.korvold",     p(["counters", "aristocrats"]),   (15, 20))
    # …but NOT under an aggro lead — tokens/tribal already field a wide board, so
    # the aggro bump owns them (Chainer tokens+reanimator stays as-is).
    check("floor.chainer",     p(["tokens", "reanimator"]),      (None, 0))
    check("floor.tribal_lead", p(["tribal_goblins", "reanimator"]), (None, 0))
    # Creature-centric / vanilla leads: no floor at all (no regression).
    check("floor.tokens",      p(["tribal_goblins", "tokens"]),  (None, 0))
    check("floor.counters",    p(["counters"]),                  (None, 0))
    check("floor.landfall",    p(["landfall"]),                  (None, 0))
    check("floor.none",        p([]),                            (None, 0))


# ── basic-land guarantee (deck reaches exactly 99 even if Scryfall is short) ──
def test_pad_with_basics():
    from deck_builder import DeckBuilder

    class _FakeClient:                     # echoes the exact-name query back
        def search_cards(self, q):
            return {"data": [{"name": q.strip('!"'), "type_line": "Basic Land"}]}

    class _Prof:
        def __init__(self, ci): self.color_identity = ci

    b = DeckBuilder(_FakeClient()); b._deck = []
    n = b._pad_with_basics(_Prof(["G", "W"]), 5)
    check("pad.count",   n, 5)
    check("pad.deck_len", len(b._deck), 5)
    # cycles the on-color basics in color order (G→Forest, W→Plains)
    check("pad.cycle", [c["name"] for c in b._deck],
          ["Forest", "Plains", "Forest", "Plains", "Forest"])
    # colorless commander → Wastes
    b2 = DeckBuilder(_FakeClient()); b2._deck = []
    b2._pad_with_basics(_Prof([]), 3)
    check("pad.colorless", [c["name"] for c in b2._deck], ["Wastes", "Wastes", "Wastes"])
    # want<=0 is a no-op
    b3 = DeckBuilder(_FakeClient()); b3._deck = []
    check("pad.zero", b3._pad_with_basics(_Prof(["R"]), 0), 0)
    check("pad.zero_len", len(b3._deck), 0)

    # Scryfall fully down → synthetic basics still guarantee the count (legal 99).
    import deck_builder as _db
    _db._BASIC_LAND_CACHE.pop("Mountain", None)   # ensure a true cache miss
    class _DeadClient:
        def search_cards(self, q): return {"data": []}
    b4 = DeckBuilder(_DeadClient()); b4._deck = []
    n4 = b4._pad_with_basics(_Prof(["R"]), 4)
    check("pad.dead_count", n4, 4)
    check("pad.dead_names", [c["name"] for c in b4._deck], ["Mountain"] * 4)
    check_true("pad.dead_synthetic", all(c.get("_synthetic") for c in b4._deck))
    check_true("pad.dead_typeline", b4._deck[0]["type_line"] == "Basic Land — Mountain")


# ── set-symbol rarity metal colouring ────────────────────────────────────────
def test_set_symbol_rarity():
    import set_symbol as ss
    # rarity normalization + aliases
    check("rar.norm_mythic",  ss._normalize_rarity("Mythic Rare"), "mythic")
    check("rar.norm_bonus",   ss._normalize_rarity("bonus"),       "special")
    check("rar.norm_ts",      ss._normalize_rarity("timeshifted"), "special")
    check("rar.norm_default", ss._normalize_rarity(""),            "common")
    check("rar.norm_plain",   ss._normalize_rarity("RARE"),        "rare")

    def mean_rgb(rar):
        img = ss.generate_set_symbol("dragon crest", size=48, rarity=rar)
        px = img.load()
        n = r = g = b = 0
        for y in range(img.height):
            for x in range(img.width):
                R, G, B, A = px[x, y]
                if A > 40:
                    r += R; g += G; b += B; n += 1
        return (r / n, g / n, b / n) if n else (0.0, 0.0, 0.0)

    cr, un, ra, my = (mean_rgb(x) for x in ("common", "uncommon", "rare", "mythic"))
    lum = lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
    # silver (uncommon) is neutral: R≈G≈B
    check_true("rar.silver_neutral", abs(un[0] - un[2]) < 24 and abs(un[0] - un[1]) < 20)
    # gold (rare) is warm: R clearly above B
    check_true("rar.gold_warm",      ra[0] - ra[2] > 30)
    # mythic is orange: R > G > B with a strong R-B gap
    check_true("rar.mythic_orange",  my[0] > my[1] > my[2] and my[0] - my[2] > 40)
    # common is the darkest of the four
    check_true("rar.common_darkest", lum(cr) < min(lum(un), lum(ra), lum(my)))
    # shape preserved across rarities (same alpha footprint, independent of metal)
    a_cr = ss.generate_set_symbol("dragon crest", size=48, rarity="common").getchannel("A")
    a_my = ss.generate_set_symbol("dragon crest", size=48, rarity="mythic").getchannel("A")
    check("rar.same_shape", a_cr.getbbox(), a_my.getbbox())


def test_stub_prompt():
    f = themer._is_stub_prompt
    # real scenes -> not stubs
    check_true("stub.real1", not f("a white-clad knight in gleaming armor on a battlefield, holy element, lord knight"))
    check_true("stub.real2", not f("a radiant vampire with silver hair floating above a grand library"))
    # boilerplate-only / quality-echo -> stub
    check_true("stub.echo1", f("high-detail illustrated character, fire element, demihuman race, knight, vibrant anime style, full body portrait, saturated colors"))
    check_true("stub.echo2", f("Avacyn, holy element, angel race, detailed anime illustration, jewel-tone palette, full body portrait"))
    check_true("stub.empty", f(""))


def main():
    for fn in (test_commander_tribe, test_name_too_close, test_tribal_text,
               test_tribal_type_line, test_parse_mana, test_frame_key, test_legibility,
               test_theme_detection, test_deck_analysis, test_creature_floor_plan,
               test_pad_with_basics, test_set_symbol_rarity, test_ro_race_class,
               test_ro_class_override, test_stub_prompt, test_ro_tribal_map,
               test_subject_directives, test_artifact_object_kind):
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
