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
import collection

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
    # Multi-face cards (MDFC/split/transform) reskin each face independently and
    # never bleed across the '//'. Regression: a single split on the first '—' used
    # to drag the back face's "Legendary"/"Creature"/"//" into the front subtypes.
    check("tl.multiface",
          f("Creature — Ogre Shaman // Legendary Creature — Ogre Shaman",
            {"Ogre": "Rusted Colossus", "Shaman": "Holo-Priest"}),
          "Creature — Holo-Priest // Legendary Creature — Holo-Priest")


def test_collect_tribes_multiface():
    # The 'all cards become the same creature type' import bug: a '//' card leaked
    # non-subtype tokens ('//', 'Legendary', 'Creature', a stray '—') into the tribe
    # list, which were then sent to the LLM and mapped. Only real subtypes survive.
    cards = [
        {"type_line": "Creature — Ogre Shaman // Legendary Creature — Ogre Shaman"},
        {"type_line": "Creature — Demon Spirit"},
        {"type_line": "Basic Land — Mountain"},
        {"type_line": "Instant — Arcane"},
    ]
    tribes = themer._collect_tribes(cards)
    check_true("tribes.clean", set(tribes) == {"Ogre", "Shaman", "Demon", "Spirit"})
    for junk in ("//", "Legendary", "Creature", "—", "Arcane"):
        check_true(f"tribes.no_{junk}", junk not in tribes)


def test_decluster_name_words():
    f = themer._decluster_name_words
    # A faction named "the Ashen Covenant" was prefixing every black card with
    # "Ashen". Cap "ashen" to one appearance; strip it (cleanly) from the rest.
    names = ["Ashen Wisp", "Ashen Reckoning", "Ashen Lord of the Void",
             "Plague of Ashen Blood", "Yukora, the Ashen Warden"]
    out = f(names, ["ashen", "covenant"], cap=1)
    check("declus.keep_first", out[0], "Ashen Wisp")          # first keeps the word
    check("declus.strip2",     out[1], "Reckoning")
    check("declus.strip3",     out[2], "Lord of the Void")
    check("declus.mid_of",     out[3], "Plague of Blood")     # tidy "of Ashen Blood" → "of Blood"
    check("declus.comma",      out[4], "Yukora, the Warden")
    # Only one card ends up containing "ashen".
    check_true("declus.count", sum("ashen" in n.lower() for n in out) == 1)
    # No faction words → identity; empty/none-safe.
    check("declus.noop", f(["Brass Skyship", "Iron Gale"], []), ["Brass Skyship", "Iron Gale"])
    # Never shrink a name below 3 chars (would-be-empty strip is skipped).
    check("declus.minlen", f(["Ash", "Ash"], ["ash"], cap=1), ["Ash", "Ash"])


def test_route_card_face():
    from image_gen import route_card_face as r
    crew = ["a", "b", "c"]
    # Commander deck: the commander card gets the commander hero face.
    check("face.cmd_deck", r(is_cmd=True, is_commander_deck=True, commander_face="C",
          crew_faces=crew, face_gender="male", crew_gender="female",
          card_type_line="", card_name="Cmd", face_assignments=None, crew_idx=0),
          ("C", "male", False, 0))
    # Non-commander import: the elected display face is NOT a hero — no face.
    check("face.noncmd_cmd", r(is_cmd=True, is_commander_deck=False, commander_face="C",
          crew_faces=crew, face_gender="male", crew_gender="female",
          card_type_line="", card_name="Cmd", face_assignments=None, crew_idx=0),
          (None, "either", False, 0))
    # Explicit assignment wins and BYPASSES the humanoid gate (even on a Land).
    check("face.assign_land", r(is_cmd=False, is_commander_deck=False, commander_face=None,
          crew_faces=crew, face_gender="m", crew_gender="f",
          card_type_line="Land", card_name="Tower",
          face_assignments={"Tower": 2}, crew_idx=0),
          ("c", "f", True, 0))
    # In explicit mode an UNassigned card gets no face (no round-robin fallback).
    check("face.assign_unassigned", r(is_cmd=False, is_commander_deck=False, commander_face=None,
          crew_faces=crew, face_gender="m", crew_gender="f",
          card_type_line="Creature — Human Soldier", card_name="Grunt",
          face_assignments={"Tower": 2}, crew_idx=0),
          (None, "either", False, 0))
    # An out-of-range index is ignored safely.
    check("face.assign_oob", r(is_cmd=False, is_commander_deck=False, commander_face=None,
          crew_faces=crew, face_gender="m", crew_gender="f",
          card_type_line="Creature — Human", card_name="X",
          face_assignments={"X": 9}, crew_idx=0),
          (None, "either", False, 0))
    # Legacy round-robin (no assignments) still cycles crew across humanoids.
    check("face.rr_human", r(is_cmd=False, is_commander_deck=True, commander_face=None,
          crew_faces=crew, face_gender="m", crew_gender="f",
          card_type_line="Creature — Human Wizard", card_name="Mage",
          face_assignments=None, crew_idx=1),
          ("b", "f", True, 2))
    # Non-humanoid in round-robin mode → no face, idx unchanged.
    check("face.rr_nonhuman", r(is_cmd=False, is_commander_deck=True, commander_face=None,
          crew_faces=crew, face_gender="m", crew_gender="f",
          card_type_line="Creature — Dragon", card_name="Wyrm",
          face_assignments=None, crew_idx=1),
          (None, "either", False, 1))


def test_face_swap_profile():
    # Style-aware ReActor tuning + multi-photo blend graph wiring.
    import image_gen as ig
    R = ["none", "GFPGANv1.4.pth", "GPEN-BFR-512.onnx", "codeformer-v0.1.0.pth"]

    # Medium classification: FLUX realistic → photoreal; RO/painterly → illustrated;
    # pixel sprite → swap disabled.
    check("face.medium_flux",   ig._face_render_medium("mtg_fantasy", "flux1-dev.safetensors"), "photoreal")
    check("face.medium_ro",     ig._face_render_medium("ragnarok_online", "illustrious.safetensors"), "illustrated")
    check("face.medium_oil",    ig._face_render_medium("oil_painting", "flux1-dev.safetensors"), "illustrated")
    check("face.medium_sdxl",   ig._face_render_medium("mtg_fantasy", "illustrious.safetensors"), "illustrated")
    check("face.medium_pixel",  ig._face_render_medium("ragnarok_sprite", "illustrious.safetensors"), "pixel")

    photo = ig._resolve_face_swap_profile("mtg_fantasy", "flux1-dev.safetensors", R)
    ill   = ig._resolve_face_swap_profile("ragnarok_online", "illustrious.safetensors", R)
    pix   = ig._resolve_face_swap_profile("ragnarok_sprite", "illustrious.safetensors", R)
    # Photoreal: crisp GPEN restore at high visibility; illustrated: soft codeformer.
    check_true("face.photo_gpen",   photo.restore_model == "GPEN-BFR-512.onnx" and photo.restore_visibility >= 0.8)
    check_true("face.ill_soft",     ill.restore_visibility <= 0.6 and "codeformer" in ill.restore_model.lower())
    check_true("face.pixel_off",    pix.enabled is False)

    # Graph wiring: single photo → source_image; ≥2 → blended FACE_MODEL; boost present.
    base = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
        "6": {"class_type": "VAEDecode", "inputs": {}},
        "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "mtg_card", "images": ["6", 0]}},
    }
    one = ig._append_reactor(dict(base), ["a.jpg"], profile=photo)
    many = ig._append_reactor(dict(base), ["a.jpg", "b.jpg", "c.jpg"], profile=photo)
    rid_one = next(k for k, n in one.items() if n["class_type"] == "ReActorFaceSwap")
    rid_many = next(k for k, n in many.items() if n["class_type"] == "ReActorFaceSwap")
    check_true("face.single_source",  "source_image" in one[rid_one]["inputs"])
    check_true("face.blend_model",    "face_model" in many[rid_many]["inputs"])
    check_true("face.blend_builds",   any(n["class_type"] == "ReActorBuildFaceModel" for n in many.values()))
    check_true("face.has_boost",      "face_boost" in one[rid_one]["inputs"])
    # SaveImage must be rewired to the reactor output, and every node-ref must resolve.
    save = next(n for n in many.values() if n["class_type"] == "SaveImage")
    check_true("face.save_rewired",   save["inputs"]["images"][0] == rid_many)
    refs_ok = all(
        v[0] in many
        for n in many.values() for v in n.get("inputs", {}).values()
        if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str)
    )
    check_true("face.refs_valid", refs_ok)


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


def test_creative_brief_helpers():
    """Deterministic pieces of the faithfulness pipeline (no LLM)."""
    # _spec_to_seed: structured spec → labelled seed (not a flattened blob)
    seed = themer._spec_to_seed({"setting": "a neon megacity", "genres": ["Cyberpunk"],
                                 "moods": ["Gritty"], "lighting": [], "inspiration": "Blade Runner"})
    check_true("brief.seed.setting", "Setting: a neon megacity" in seed)
    check_true("brief.seed.genre",   "Genre: Cyberpunk" in seed)
    check_true("brief.seed.insp",    "Inspired by: Blade Runner" in seed)
    check_true("brief.seed.no_empty_lighting", "Lighting" not in seed)
    # empty spec falls back to the flat theme string (imports / old decks)
    check("brief.seed.fallback", themer._spec_to_seed(None, "old flat theme"), "old flat theme")

    # _extract_user_motifs: salient words, stopwords dropped
    motifs = themer._extract_user_motifs({"setting": "a smoky jazz speakeasy with literal magic",
                                          "inspiration": ""})
    check_true("brief.motifs.keep", "speakeasy" in motifs and "smoky" in motifs)
    check_true("brief.motifs.drop_stop", "literal" not in motifs and "with" not in motifs)

    # _normalize_bible: coerces types + back-fills must_include when LLM under-delivers
    nb = themer._normalize_bible({"world": "", "must_include": ["velvet booths"],
                                  "signature_details": "a single string", "zones": []},
                                 "Setting: a jazz speakeasy", None, "a jazz speakeasy", "balanced")
    check_true("brief.norm.world_fallback", len(nb["world"]) > 0)
    check_true("brief.norm.backfill", len(nb["must_include"]) >= 2)        # back-filled from seed words
    check_true("brief.norm.sig_listified", isinstance(nb["signature_details"], list))

    # _word_root + verify_motif_coverage: morphology-tolerant, no gross false positives
    check("brief.root.fungus", themer._word_root("fungus"), "fung")
    check("brief.root.bees",   themer._word_root("bees"),   "bee")
    cov = themer.verify_motif_coverage(
        ["bioluminescent fungus", "clockwork bees", "neon hologram"],
        ["a fungal spire glows", "a clockwork bee drifts past"])
    check_true("brief.cov.fungal", cov["bioluminescent fungus"] >= 1)      # fungus≈fungal
    check_true("brief.cov.bees",   cov["clockwork bees"] >= 1)             # bees≈bee
    check("brief.cov.absent",      cov["neon hologram"], 0)                # not present → ⚠

    # _extract_json_object: tolerates prose wrap + a trailing comma
    obj = themer._extract_json_object('sure! {"a": 1, "b": [2, 3,],}  done')
    check_true("brief.json.parsed", isinstance(obj, dict) and obj.get("a") == 1)


def test_name_art_coherence():
    """The art_prompt must depict the card's OWN themed_name, not a divergent
    invented subject ('named subject missing' fix)."""
    inc, rep = themer._name_art_incoherent, themer._repair_name_lead
    # divergent proper-name lead → flagged + realigned to the real name
    check_true("coh.divergent.flag",
               inc("Shimmerfang Skirmisher", "Shadow Snarler with translucent azure wings over a glade"))
    check_true("coh.divergent.fix",
               rep("Shimmerfang Skirmisher", "Shadow Snarler with translucent azure wings over a glade")
               .startswith("Shimmerfang Skirmisher with translucent"))
    # article-led depiction → left alone (this is the GOOD pattern)
    check_true("coh.article.keep",
               not inc("Nightpaw Lifebound Striker", "a sleek black hound with violet eyes crouches in a glade"))
    # already leads with the right name → left alone
    check_true("coh.aligned.keep",
               not inc("Runed Canopy Glade", "Runed Canopy Glade, a glowing arboreal arena at dusk"))
    # sentence-initial adjective that contains a name word → not a divergent name
    check_true("coh.adj.keep",
               not inc("Golden Dawn Herald", "Golden light floods a cathedral as a herald raises a horn"))


def test_oracle_reminder_italics():
    """Inline parenthetical reminder text is flagged italic (not only when a
    whole paragraph is parenthetical), and _draw_oracle_text reports its final
    body font size so flavor text can be drawn at the same size."""
    # _italic_regions: the reminder span (incl. parens) is italic; the rest upright
    regs = cr._italic_regions("Dethrone (Whenever this attacks, draw.) Done")
    check("ital.reconstruct", "".join(s for s, _ in regs),
          "Dethrone (Whenever this attacks, draw.) Done")
    check("ital.span", "".join(s for s, it in regs if it),
          "(Whenever this attacks, draw.)")
    check_true("ital.keyword_upright",
               all(not it for s, it in regs if "Dethrone" in s))

    # _tokenise carries the italic flag through to text tokens
    toks = cr._tokenise("Flying (It can't be blocked.)")
    check_true("tok.reminder_italic",
               any(t[0] == "text" and t[2] and "blocked" in t[1] for t in toks))
    check_true("tok.body_upright",
               any(t[0] == "text" and not t[2] and "Flying" in t[1] for t in toks))

    # a reminder that contains a {symbol} stays italic end-to-end
    toks2 = cr._tokenise("({T}: Add {G}.)")
    check_true("tok.sym_reminder_italic",
               all(t[2] for t in toks2 if t[0] == "text"))

    # _draw_oracle_text returns the final body font size (int) it settled on
    from PIL import Image
    img = Image.new("RGBA", (300, 200), (0, 0, 0, 255))
    size = cr._draw_oracle_text(img, "Counter target spell.", 10, 10, 280, 180,
                                cr._mm(2.4), cr._mm(2.2), cr._DARK_TEXT, center_v=True)
    check_true("oracle.returns_int", isinstance(size, int) and size > 0)


def test_card_video_helpers():
    """Pure-logic guards for the animate-card pipeline (no GPU/ComfyUI)."""
    import card_video as cv

    # motion prompt: preset text + the card's art prompt, capped
    mp = cv.build_motion_prompt("elements", "a neon dragon over a rain-slick city")
    check_true("cv.motion.preset", "drifting embers" in mp)
    check_true("cv.motion.art",    "neon dragon" in mp)
    check("cv.motion.fallback_preset",
          cv.build_motion_prompt("nope", ""), cv._MOTION_PRESETS["subtle"])

    # ping-pong: seamless loop without duplicating the two endpoints
    seq = cv.ping_pong(list(range(5)), loop=True)
    check("cv.pingpong.len", len(seq), 8)              # 5 + 3 reversed-interior
    check("cv.pingpong.ends", (seq[0], seq[-1]), (0, 1))
    check("cv.pingpong.noloop", cv.ping_pong([1, 2, 3], loop=False), [1, 2, 3])

    # workflow builder: placeholders filled, numerics typed as int, nodes present
    wf = cv.build_workflow("ltxv", "art.png", "subtle motion", "pfx",
                           frames=49, fps=24, w=768, h=512, seed=7,
                           models={"ckpt": "ltx.safetensors"})
    classes = {n["class_type"] for n in wf.values()}
    check_true("cv.wf.i2v_node", "LTXVImgToVideo" in classes)
    check_true("cv.wf.save", "SaveImage" in classes)
    i2v = next(n for n in wf.values() if n["class_type"] == "LTXVImgToVideo")
    check("cv.wf.length_int", i2v["inputs"]["length"], 49)
    check_true("cv.wf.length_is_int", isinstance(i2v["inputs"]["length"], int))
    ckpt = next(n for n in wf.values() if n["class_type"] == "CheckpointLoaderSimple")
    check("cv.wf.model", ckpt["inputs"]["ckpt_name"], "ltx.safetensors")

    # health_check shape (ComfyUI is down in CI → ok False, actionable hint)
    h = cv.health_check()
    check_true("cv.health.keys", all(k in h for k in ("ok", "method", "hint", "models")))
    check_true("cv.health.gated", h["ok"] in (True, False))


def test_set_bible_factions():
    """Set Bible colour-faction helpers + faction-aware palette (no LLM)."""
    import themer as T

    cmd  = {"name": "Atraxa", "color_identity": ["W", "U", "B", "G"]}
    deck = [{"name": "Bolt", "color_identity": ["R"], "type_line": "Instant"}]
    check("sb.colors", T._deck_color_identity(cmd, deck), ["W", "U", "B", "R", "G"])

    fb = T._fallback_factions(["U", "R"])
    check_true("sb.fallback.shape",
               all(k in fb["factions"]["U"] for k in ("name", "people", "aesthetic", "palette")))

    norm = T._normalize_factions(
        {"factions": {"U": {"name": "the Glitch Choir", "people": "data-spirits",
                            "aesthetic": "neon glass", "motifs": ["halos"],
                            "palette": "electric teal, black"}},
         "mechanic_flavor": {"draw": "data-divination"}, "lore": "war over the grid"},
        ["U", "R"], "teal/red")
    check("sb.norm.kept",   norm["factions"]["U"]["name"], "the Glitch Choir")
    check_true("sb.norm.filled", bool(norm["factions"]["R"]["name"]))   # R from fallback

    # Faction palette wins over the static stock palette for that colour
    pal = T._color_palette_hint(["U"], "", norm["factions"])
    check("sb.palette.faction", pal, "electric teal, black")
    check("sb.faction.tag", T._card_faction_tag(["U"], norm["factions"]), "the Glitch Choir")


def test_foil_and_formats():
    """Procedural foil frames + multi-format encode dispatch (no GPU)."""
    import tempfile, pathlib
    from PIL import Image
    import card_video as cv

    check("fmt.list", cv.VIDEO_FORMATS, ("mp4", "webp", "gif"))
    check_true("fmt.options", {f["key"] for f in cv.format_options()} == {"mp4", "webp", "gif"})
    check_true("foil.styles", {s["key"] for s in cv.foil_styles()} >= {"holo", "gold", "silver"})

    base = Image.new("RGBA", (120, 168), (40, 60, 90, 255))
    frames = cv.foil_frames([base], count=6, style="holo")
    check("foil.count", len(frames), 6)
    check("foil.size",  frames[0].size, (120, 168))
    check_true("foil.changes", list(frames[0].getdata()) != list(frames[3].getdata()))

    d = pathlib.Path(tempfile.mkdtemp())
    out = d / "t.webp"
    cv.encode_loop(frames, out, fmt="webp", fps=12, loop=False)
    check_true("foil.webp_written", out.exists() and out.stat().st_size > 0)
    try:
        cv.encode_loop(frames, d / "t.bogus", fmt="bogus")
        check_true("foil.bad_fmt_raises", False)
    except ValueError:
        check_true("foil.bad_fmt_raises", True)


def test_commander_user_name():
    """'Your Name' → '<name>, <title>': keep a genuine themed title, regenerate a
    leaked original title from the reskinned creature type, always drop the
    original first name (no LLM — uses the deterministic fallback)."""
    import themer as T

    cmd = {"name": "Urza, Lord High Artificer",
           "type_line": "Legendary Creature — Human Artificer",
           "oracle_text": "create a token", "color_identity": ["U"]}

    # Leak detection
    check_true("uname.leak.orig", T._title_is_original("Lord High Artificer", "Urza, Lord High Artificer"))
    check_true("uname.leak.new",  not T._title_is_original("the Glitch Conductor", "Urza, Lord High Artificer"))

    # Reskinned creature type drives the generated title
    check("uname.reskin", T._primary_reskinned_type(cmd, {"Artificer": "Netrunner"}), "Netrunner")

    # A genuinely themed title is kept, first name swapped to the user's
    keep = T.compose_commander_name("Ravn", "Urza, the Glitch Conductor", cmd,
                                    theme="cyberpunk", world_bible={"world": "neon city"},
                                    tribal_map={})
    check("uname.keep_title", keep, "Ravn, the Glitch Conductor")

    # A leaked original title is regenerated; force the deterministic fallback with
    # an unreachable model. Result must be "Ravn, ..." and contain neither the
    # original first name nor the original title.
    regen = T.compose_commander_name("Ravn", "Urza, Lord High Artificer", cmd,
                                     theme="cyberpunk", world_bible={"world": "neon city"},
                                     tribal_map={"Artificer": "Netrunner"}, model="__no_such_model__")
    check_true("uname.regen.prefix", regen.startswith("Ravn, "))
    check_true("uname.regen.no_orig_first", "Urza" not in regen)
    check_true("uname.regen.no_orig_title", "Artificer" not in regen)
    check_true("uname.regen.fits_type", "Netrunner" in regen)

    # No user name → unchanged
    check("uname.empty", T.compose_commander_name("", "Urza, the X", cmd), "Urza, the X")


# ── Myth Suite collection contract + collection-aware building (C4) ───────────
def test_collection_owned_key():
    ok = collection.owned_key
    check("ck.simple",  ok("Sol Ring"), "sol ring")
    check("ck.case",    ok("  LIGHTNING BOLT "), "lightning bolt")
    check("ck.dfc",     ok("Fire // Ice"), "fire")


def test_collection_parse():
    owned = collection.parse_owned("Count,Name,Edition\n1,Sol Ring,cmd\n2,Lightning Bolt,lea\n")
    check_true("parse.csv.sol",  "sol ring" in owned)
    check_true("parse.csv.bolt", "lightning bolt" in owned)
    owned2 = collection.parse_owned("1 Sol Ring\nCommander: Krenko, Mob Boss\nCounterspell (mmq) 62\n")
    check_true("parse.dl.sol",     "sol ring" in owned2)
    check_true("parse.dl.cmdr",    "krenko, mob boss" in owned2)
    check_true("parse.dl.setcode", "counterspell" in owned2)  # trailing (SET) 123 stripped
    check("parse.empty", collection.parse_owned(""), set())


def test_collection_owned_count():
    owned = {"sol ring", "counterspell"}
    cards = [{"name": "Sol Ring"}, {"name": "Llanowar Elves"}, {"name": "Counterspell"}]
    check("count.two",      collection.owned_count(cards, owned), 2)
    check("count.no_owned", collection.owned_count(cards, set()), 0)


def test_import_preserves_decklist():
    """Importing a paper deck must not change which cards are in it.

    Regression: 'Commander: <Name>' (the most common paper/export form) matched no
    rule, was silently DISCARDED, and the commanderless deck then had a maindeck card
    auto-elected into the commander slot — so the import changed the user's deck."""
    from deck_import import _parse_text
    raw = _parse_text("Commander: Krenko, Mob Boss\n\n1 Sol Ring\n1 Lightning Bolt\n2 Mountain")
    check("imp.cmdr", raw.commander_names, ["Krenko, Mob Boss"])
    check("imp.cards", [n for n, _ in raw.card_entries],
          ["Sol Ring", "Lightning Bolt", "Mountain"])
    check("imp.qty", dict(raw.card_entries)["Mountain"], 2)
    # bare-header form still works
    raw2 = _parse_text("Commander\n1 Krenko, Mob Boss\n\nDeck\n1 Sol Ring")
    check("imp.hdr.cmdr", raw2.commander_names, ["Krenko, Mob Boss"])
    check("imp.hdr.cards", [n for n, _ in raw2.card_entries], ["Sol Ring"])


def test_import_line_formats():
    """Every mainstream decklist export must parse into the SAME cards.

    Regression: the name group was lazy and ran to end-of-line, so anything the
    exporter appended after the name became part of it. "1x Sol Ring (c21) 263
    [Ramp{noPrice}]" resolved as a card by that literal name — i.e. it silently
    left the user's deck and reappeared only as an `unresolved` entry. Archidekt's
    own text export takes exactly that path, and its "[Commander{top}]" tag went
    with it, so the commander was dropped and a maindeck card got auto-elected into
    the face slot in its place."""
    from deck_import import _parse_text, _strip_line_metadata, _QTY_RE

    def name_of(line):
        m = _QTY_RE.match(line)
        return _strip_line_metadata(m.group("rest"))[0] if m else None

    check("fmt.archidekt", name_of("1x Sol Ring (c21) 263 [Ramp{noPrice}]"), "Sol Ring")
    check("fmt.moxfield",  name_of("1 Sol Ring (C21) 263"), "Sol Ring")
    check("fmt.mtgo",      name_of("4 Lightning Bolt [M11] 149"), "Lightning Bolt")
    check("fmt.foil",      name_of("1 Chandra, Torch of Defiance (KLD) 110 *F*"), "Chandra, Torch of Defiance")
    check("fmt.hash",      name_of("1 Sol Ring #263"), "Sol Ring")
    # Names that must survive untouched: an embedded number, and a split card whose
    # "//" separator must never be read as a comment.
    check("fmt.numeric",   name_of("1 Borrowing 100,000 Arrows"), "Borrowing 100,000 Arrows")
    check("fmt.split",     name_of("1 Fire // Ice"), "Fire // Ice")
    check("fmt.dfc",       name_of("1 Bonecrusher Giant // Stomp (ELD) 115"), "Bonecrusher Giant // Stomp")

    # Cards whose NAME ends in a number. A general "strip a bare trailing number"
    # rule cannot tell these from a collector number and truncated all five — found
    # by replaying the 10,824 distinct card names in corpus/ through the stripper in
    # six line shapes (64,944 checks, now zero damage). The number is metadata only
    # when a printing token sits directly in front of it, as in "[M11] 149".
    for nm in ("Pip-Boy 3000", "Black Waltz No. 3", "Avalanche of Sector 7",
               "Behemoth of Vault 0", "Michelangelo, Weirdness to 11"):
        check(f"fmt.numname.{nm}",      name_of(f"1 {nm}"), nm)
        check(f"fmt.numname.set.{nm}",  name_of(f"1 {nm} (pip) 123"), nm)
        check(f"fmt.numname.cat.{nm}",  name_of(f"1x {nm} [Ramp{{noPrice}}]"), nm)

    # Archidekt's text export has no section headers at all — the category tag is
    # the only signal for the commander and the sideboard.
    arch = _parse_text(
        "1x Krenko, Mob Boss (jmp) 341 [Commander{top}]\n"
        "1x Sol Ring (c21) 263 [Ramp{noPrice}]\n"
        "2x Mountain (unf) 239 [Land]\n"
        "1x Counterspell (mh2) 267 [Sideboard]\n")
    check("fmt.arch.cmdr",  arch.commander_names, ["Krenko, Mob Boss"])
    check("fmt.arch.cards", [n for n, _ in arch.card_entries], ["Sol Ring", "Mountain"])
    check("fmt.arch.qty",   dict(arch.card_entries)["Mountain"], 2)
    # MWS/Apprentice "SB:" lines are sideboard, not maindeck.
    mws = _parse_text("SB: 1 Counterspell\n4 Lightning Bolt\n")
    check("fmt.mws", [n for n, _ in mws.card_entries], ["Lightning Bolt"])


def test_import_zone_headers():
    """Zone headers must be recognised through every decoration a real export uses.

    Missing one is worse than dropping a card: an unrecognised "Sideboard (15)" folds
    fifteen cards the user never wanted INTO their maindeck, and an unrecognised
    "Commander (1)" leaves the commander in the 99 for _apply_auto_face to replace
    with whatever card happened to cost the most mana."""
    from deck_import import _parse_text

    # Archidekt / TappedOut / Moxfield category exports: "(N)" suffix.
    counted = _parse_text(
        "Commander (1)\n1x Krenko, Mob Boss (jmp) 341\n\n"
        "Creatures (2)\n1x Goblin Chieftain (m10) 137\n1x Skirk Prospector (dom) 143\n\n"
        "Sideboard (2)\n1x Counterspell (mh2) 267\n1x Negate (m19) 69\n")
    check("zone.count.cmdr",  counted.commander_names, ["Krenko, Mob Boss"])
    check("zone.count.cards", [n for n, _ in counted.card_entries],
          ["Goblin Chieftain", "Skirk Prospector"])

    # Deckstats: "//" categories. The reader must LEAVE the commander section when a
    # non-zone category follows, or every creature is read as a commander.
    ds = _parse_text(
        "//Commander\n1 Krenko, Mob Boss\n"
        "//Creatures\n1 Goblin Chieftain\n1 Skirk Prospector\n"
        "//Sideboard\n1 Counterspell\n")
    check("zone.ds.cmdr",  ds.commander_names, ["Krenko, Mob Boss"])
    check("zone.ds.cards", [n for n, _ in ds.card_entries],
          ["Goblin Chieftain", "Skirk Prospector"])

    # Regressions: the plain forms must keep working.
    check("zone.paper", _parse_text("Commander: Krenko, Mob Boss\n\n1 Sol Ring\n").commander_names,
          ["Krenko, Mob Boss"])
    check("zone.bare", _parse_text("Commander\n1 Krenko, Mob Boss\n\nDeck\n1 Sol Ring\n").commander_names,
          ["Krenko, Mob Boss"])
    check("zone.mtga_sb", [n for n, _ in _parse_text(
        "Deck\n1 Sol Ring (C21) 263\n\nSideboard\n1 Counterspell (MH2) 267\n").card_entries],
        ["Sol Ring"])

    # Moxfield's header-less plain export encodes the commander POSITIONALLY: first
    # paragraph, then the maindeck. Recorded as a hint only — _resolve promotes it
    # solely when Scryfall confirms the card is legendary.
    mox = _parse_text("1 Krenko, Mob Boss (JMP) 341\n\n1 Sol Ring (C21) 263\n1 Lightning Bolt (M11) 149\n")
    check("zone.mox.hint", mox.leading_names, ["Krenko, Mob Boss"])
    # A tagged deck never needs the hint, and neither does a list with no clear opener.
    check("zone.mox.no_hint_when_tagged",
          _parse_text("Commander: Krenko, Mob Boss\n\n1 Sol Ring\n").leading_names, [])
    check("zone.mox.no_hint_when_long",
          _parse_text("1 A\n1 B\n1 C\n\n1 Sol Ring\n").leading_names, [])


def test_archidekt_respects_included_in_deck():
    """Archidekt says which categories are in the deck — believe it, don't guess.

    Judging by category NAME was wrong in both directions. A user's own not-in-deck
    piles ("cut", "Too sauced", "Graveyard support?") were imported as real cards,
    and a category literally named "Sideboard" that the user had INCLUDED was thrown
    away. Over 40 real corpus decks the two rules disagree on 7; the worst imported a
    166-card "deck" out of a 100-card list."""
    from deck_import import _parse_archidekt

    def card(name, cats, qty=1):
        return {"quantity": qty, "categories": cats, "card": {"oracleCard": {"name": name}}}

    raw = _parse_archidekt({
        "name": "Test deck",
        "categories": [
            {"name": "Commander",  "includedInDeck": True},
            {"name": "Ramp",       "includedInDeck": True},
            {"name": "Sideboard",  "includedInDeck": True},   # user INCLUDED it
            {"name": "Maybeboard", "includedInDeck": False},
            {"name": "cut",        "includedInDeck": False},  # custom exclude pile
        ],
        "cards": [
            card("Krenko, Mob Boss", ["Commander"]),
            card("Sol Ring",         ["Ramp"]),
            card("Mountain",         ["Ramp"], qty=8),
            card("Lightning Bolt",   ["Sideboard"]),          # kept: includedInDeck
            card("Negate",           ["Maybeboard"]),         # dropped
            card("Counterspell",     ["cut"]),                # dropped
        ],
    })
    check("arch.cmdr",  raw.commander_names, ["Krenko, Mob Boss"])
    check("arch.cards", [n for n, _ in raw.card_entries],
          ["Sol Ring", "Mountain", "Lightning Bolt"])
    check("arch.total", sum(q for _, q in raw.card_entries), 10)

    # No category metadata at all (older/partial responses) → fall back to the name test.
    legacy = _parse_archidekt({"name": "Legacy", "categories": [], "cards": [
        card("Sol Ring", ["Ramp"]),
        card("Negate",   ["Sideboard"]),
    ]})
    check("arch.legacy", [n for n, _ in legacy.card_entries], ["Sol Ring"])


def test_leading_commander_promotion():
    """The positional-commander hint may only promote a REAL legendary card.

    _apply_auto_face used to elect the highest-mana-value legendary creature into the
    face slot for these decks, which on a 100-card list is usually the wrong card
    while the real commander stays buried in the 99. Promotion is structural (first
    paragraph) AND verified (Scryfall says legendary) — a non-legendary opener falls
    through to the honest election instead of inventing a commander."""
    from deck_import import ImportedDeck, _promote_leading_commander

    krenko = {"name": "Krenko, Mob Boss", "type_line": "Legendary Creature — Goblin Warrior",
              "quantity": 1}
    bolt   = {"name": "Lightning Bolt", "type_line": "Instant", "quantity": 1}
    mtn    = {"name": "Mountain", "type_line": "Basic Land — Mountain", "quantity": 8}

    imp = ImportedDeck(name="d", source="text", commander=None,
                       deck=[dict(krenko), dict(bolt), dict(mtn)])
    before = imp.total_cards()
    _promote_leading_commander(imp, ["Krenko, Mob Boss"])
    check("promote.cmdr",  (imp.commander or {}).get("name"), "Krenko, Mob Boss")
    check("promote.pulled", [c["name"] for c in imp.deck], ["Lightning Bolt", "Mountain"])
    check("promote.total",  imp.total_cards(), before)   # 1 out of the deck, 1 into the face

    # Not legendary → left alone entirely.
    imp2 = ImportedDeck(name="d", source="text", commander=None,
                        deck=[dict(bolt), dict(mtn)])
    _promote_leading_commander(imp2, ["Lightning Bolt"])
    check_true("promote.no_invent", imp2.commander is None)
    check("promote.untouched", [c["name"] for c in imp2.deck], ["Lightning Bolt", "Mountain"])

    # A multi-copy opener decrements rather than removing the stack.
    imp3 = ImportedDeck(name="d", source="text", commander=None,
                        deck=[{**krenko, "quantity": 2}, dict(bolt)])
    _promote_leading_commander(imp3, ["Krenko, Mob Boss"])
    check("promote.decrement", imp3.deck[0]["quantity"], 1)


def test_deck_identity_is_preserved():
    """A deck's card list and provenance must survive every derived-deck boundary.

    Rebuild/retheme write a NEW deck.json under a NEW job id. Anything not carried
    across is lost — and losing `imported` re-arms the worst bug in this area:
    Edit & Rebuild reads that flag to decide whether to reuse the stored card list
    or generate a fresh one, so a rethemed import that forgot it would silently
    regenerate into a different deck."""
    try:
        import server
    except Exception as e:                      # fastapi/pydantic missing
        check("identity.import", f"skipped: {e}", f"skipped: {e}")
        return

    # ── _preserve_decklist: a short themer batch never shrinks the deck ──
    raw = [{"name": "Sol Ring"}, {"name": "Lightning Bolt"}, {"name": "Mountain"}]
    short = [server.ThemedCard("Sol Ring", "Ring of Suns", "art", "", raw[0])]
    out = server._preserve_decklist(short, raw)
    check("keep.len",   len(out), 3)
    check("keep.order", [tc.original_name for tc in out],
          ["Sol Ring", "Lightning Bolt", "Mountain"])
    check("keep.themed", out[0].themed_name, "Ring of Suns")   # real theming kept
    check("keep.plain",  out[2].themed_name, "Mountain")       # gap filled, not dropped
    same = server._preserve_decklist(
        [server.ThemedCard(c["name"], "X", "", "", c) for c in raw], raw)
    check("keep.noop", [tc.themed_name for tc in same], ["X", "X", "X"])

    # ── _carry_provenance: identity travels, imported_only tracks art ──
    src = {"imported": True, "imported_only": True, "import_source": "archidekt",
           "import_name": "My Deck", "import_unresolved": ["Bogus Card"],
           "import_auto_face": True, "is_commander_deck": False,
           "face_assignments": {"Sol Ring": 0}, "theme": "not provenance"}
    themed = server._carry_provenance({}, src, generated_art=True)
    check_true("prov.imported",     themed["imported"] is True)
    check("prov.source",            themed["import_source"], "archidekt")
    check("prov.unresolved",        themed["import_unresolved"], ["Bogus Card"])
    check_true("prov.not_cmd_deck", themed["is_commander_deck"] is False)
    check("prov.assignments",       themed["face_assignments"], {"Sol Ring": 0})
    check_true("prov.no_theme",     "theme" not in themed)
    # art was generated → it is no longer an "import with no art yet"
    check_true("prov.only_cleared", "imported_only" not in themed)
    text_only = server._carry_provenance({}, src, generated_art=False)
    check_true("prov.only_kept",    text_only["imported_only"] is True)

    # ── _stored_card_to_raw: re-theming starts from the REAL printed type ──
    stored = {"original_name": "Knight of the White Orchid",
              "themed_name": "Holo-Priest of Dawn",
              "type_line": "Creature — Holo-Priest",         # last theme's reskin
              "original_type_line": "Creature — Human Knight",
              "scryfall_img": "", "quantity": 1}
    check("raw.type", server._stored_card_to_raw(stored)["type_line"],
          "Creature — Human Knight")
    check("raw.keywords", server._stored_card_to_raw(stored)["keywords"], [])
    # the rebuild path must still see the themed line (it keeps names as-is)
    check("raw.rebuild_untouched", server._stored_card_to_dict(stored)["type_line"],
          "Creature — Holo-Priest")


def test_export_covers_unrendered_cards():
    """An imported deck with no AI art must still export.

    build_zip/build_pdf looked only in renders/<job>/cards/. A deck saved straight
    from an import has none of those, so the ZIP came out empty and the PDF raised
    "No rendered card images found" — on the one deck whose export is just its real
    cards. The server now passes a resolver that falls back to Scryfall art."""
    import io
    import zipfile
    from pathlib import Path
    import exporter

    cmd  = {"render_key": "Krenko_000", "original_name": "Krenko", "quantity": 1}
    deck = [{"render_key": "Sol_Ring_001", "quantity": 1},
            {"render_key": "Mountain_002", "quantity": 3}]

    # Default resolver + nothing on disk = the old, empty result.
    empty = exporter.build_zip(cmd, deck, Path("/nonexistent"))
    check("exp.default_empty", len(zipfile.ZipFile(io.BytesIO(empty)).namelist()), 0)

    # A resolver standing in for the Scryfall fallback fills every slot, and a
    # quantity-3 entry still yields three printable copies.
    here = Path(__file__).resolve()
    data = exporter.build_zip(cmd, deck, Path("/nonexistent"), image_for=lambda c: here)
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    check("exp.slots", len(names), 5)          # commander + 1 + 3 copies
    check_true("exp.commander", any(n.startswith("00_commander_") for n in names))
    check_true("exp.copies", sum(1 for n in names if "Mountain_002" in n) == 3)


def test_fuzzy_substitution_guard():
    """A typo must NOT silently become a different card in an imported decklist."""
    from scryfall_client import _fuzzy_is_plausible
    check_true("fz.near", _fuzzy_is_plausible("Krenko Mob Boss", "Krenko, Mob Boss"))
    check_true("fz.dfc", _fuzzy_is_plausible("Aang, at the Crossroads",
                                             "Aang, at the Crossroads // Aang, Destined Savior"))
    check_true("fz.typo", not _fuzzy_is_plausible("sol rng", "Oathsworn Giant"))
    check_true("fz.other", not _fuzzy_is_plausible("Jace, the Mind Sculptor", "Jace Beleren"))


def test_collection_printings():
    """The same card owned in several sets stays several rows, and set/collector number
    survive both the CSV and decklist import forms. Ownership stays NAME-level."""
    import tempfile, pathlib
    p = pathlib.Path(tempfile.gettempdir()) / "mf_printing_test.csv"
    for f in (p, p.with_suffix(".csv.bak")):
        if f.exists():
            f.unlink()
    # CSV with Edition + Collector Number
    rows = collection._parse_rows(
        "Count,Name,Edition,Collector Number\n1,Sol Ring,C21,263\n2,Sol Ring,LTC,284\n1,Bolt,,")
    check("pr.csv.len", len(rows), 3)
    check("pr.csv.sets", [r["set"] for r in rows], ["C21", "LTC", ""])
    # decklist "(SET) num" suffix
    d = collection._parse_rows("1 Sol Ring (C21) 263\n1 Sol Ring (LTC)\n2 Mountain")
    check("pr.deck.sets", [r["set"] for r in d], ["C21", "LTC", ""])
    check("pr.deck.name", d[0]["name"], "Sol Ring")
    # per-printing add / remove
    collection.write_collection(rows, p)
    collection.add_card("Sol Ring", 1, p, set_code="C21")          # merges that printing
    collection.add_card("Sol Ring", 3, p, set_code="LTR", cn="1")  # new printing
    got = [(r["name"], r["count"], r["set"]) for r in collection.load_collection(p)]
    check("pr.merge", ("Sol Ring", 2, "C21") in got, True)
    check("pr.newprint", ("Sol Ring", 3, "LTR") in got, True)
    # ownership is name-level regardless of printings
    check_true("pr.owned", "sol ring" in collection.load_owned_names(p))
    collection.remove_card("Sol Ring", p, set_code="LTC")
    check_true("pr.rm.one", not any(r["set"] == "LTC" for r in collection.load_collection(p)))
    check_true("pr.rm.keeps", any(r["set"] == "C21" for r in collection.load_collection(p)))
    for f in (p, p.with_suffix(".csv.bak")):
        if f.exists():
            f.unlink()


def test_collection_preserves_scanner_columns():
    """A Forge edit must not delete columns Forge doesn't model.

    MythScanner's export writes Condition/Language/Foil to the same canonical CSV. Forge
    only models Count/Name/Edition/Collector Number, and used to rewrite the file with just
    those four — so one +/- click silently destroyed the scanner's per-copy data.
    """
    import tempfile, pathlib
    p = pathlib.Path(tempfile.gettempdir()) / "mf_coll_cols_test.csv"
    p.unlink(missing_ok=True)
    p.write_text("\n".join([
        "Count,Name,Edition,Condition,Language,Foil,Collector Number",
        "2,Sol Ring,LTC,NM,en,foil,284",
        "1,Forest,ZNR,LP,en,,270",
        "",
    ]), encoding="utf-8")

    collection.write_collection(collection.load_collection(p), p)
    text = p.read_text(encoding="utf-8-sig")
    for col in ("Condition", "Language", "Foil"):
        check_true(f"cols.header.{col}", col in text.splitlines()[0])
    check_true("cols.values_kept", "NM" in text and "foil" in text)

    # ...and they survive an actual edit, not just a passthrough rewrite.
    collection.add_card("Sol Ring", 1, p, set_code="LTC", cn="284")
    after = p.read_text(encoding="utf-8-sig")
    row = [ln for ln in after.splitlines() if ln.startswith("3,Sol Ring")]
    check("cols.edit_count", len(row), 1)
    check_true("cols.edit_keeps_extra", "NM,en,foil" in row[0])
    p.unlink(missing_ok=True)
    p.with_suffix(".csv.bak").unlink(missing_ok=True)


def test_suite_path_contract():
    """C1 is mirrored in three repos; this pins Forge's copy to the contract.

    Forge, MythScanner and MythGauntlet each compute this path independently — the first
    two cannot import MythGauntlet's config.py, so the constant is duplicated by necessity.
    An identical assertion lives in each repo (MythGauntlet tests/test_config_suite.py,
    Scanner tests/test_export.py) so whichever copy drifts fails its OWN suite instead of
    silently pointing an app at a different collection file. Contract: MYTHSUITE_DIR
    overrides, default ~/Documents/MythSuite, filename collection.csv.
    See mythgauntlet docs/SUITE_PLAN.md (C1).
    """
    import pathlib as _pl
    prior = os.environ.pop("MYTHSUITE_DIR", None)
    try:
        check("suite.default_dir", collection.suite_dir(),
              _pl.Path.home() / "Documents" / "MythSuite")
        check("suite.default_file", collection.suite_collection_path(),
              _pl.Path.home() / "Documents" / "MythSuite" / "collection.csv")
        os.environ["MYTHSUITE_DIR"] = r"C:\elsewhere\Suite"
        check("suite.override", collection.suite_collection_path(),
              _pl.Path(r"C:\elsewhere\Suite") / "collection.csv")
    finally:
        os.environ.pop("MYTHSUITE_DIR", None)
        if prior is not None:
            os.environ["MYTHSUITE_DIR"] = prior


def test_collection_write_is_atomic():
    """A failed write must leave the previous collection intact, not a truncated file.

    This file is the canonical Myth Suite collection, MythScanner writes the same path, and
    Forge rewrites it on every +/- click. Opening the real path with "w" truncates it up
    front, so an interrupted write used to destroy the collection and a concurrent reader
    could see a partial one. write_collection now builds a temp file beside it and
    os.replace()s in.
    """
    import tempfile, pathlib, csv as _csv
    p = pathlib.Path(tempfile.gettempdir()) / "mf_coll_atomic_test.csv"
    p.unlink(missing_ok=True)
    collection.write_collection([{"name": "Sol Ring", "count": 1}], p)
    before = p.read_bytes()

    # Blow up midway through serialising the new contents.
    class Boom(Exception):
        pass

    real_writer = _csv.writer

    def exploding_writer(*a, **kw):
        w = real_writer(*a, **kw)
        class W:
            def writerow(self, row):
                if row and row[0] != "Count":
                    raise Boom("disk full")
                return w.writerow(row)
        return W()

    _csv.writer = exploding_writer
    try:
        collection.write_collection([{"name": "Black Lotus", "count": 99}], p)
        check_true("atomic.raised", False)          # should not reach here
    except Boom:
        pass
    finally:
        _csv.writer = real_writer

    check("atomic.original_intact", p.read_bytes(), before)
    check("atomic.still_loads", len(collection.load_collection(p)), 1)
    check_true("atomic.no_tmp_left",
               not (p.parent / f".{p.name}.tmp").exists())
    p.unlink(missing_ok=True)
    p.with_suffix(".csv.bak").unlink(missing_ok=True)


def test_collection_crud():
    import tempfile, pathlib
    p = pathlib.Path(tempfile.gettempdir()) / "mf_coll_crud_test.csv"
    if p.exists():
        p.unlink()
    bak = p.with_suffix(".csv.bak")
    # write + quantity-aware load
    collection.write_collection([{"name": "Sol Ring", "count": 1},
                                 {"name": "Fire // Ice", "count": 2}], p)
    rows = collection.load_collection(p)
    check("crud.load.len", len(rows), 2)
    check("crud.load.count", rows[1]["count"], 2)
    # add merges onto existing (front-face keyed)
    collection.add_card("Sol Ring", 2, p)
    check("crud.add.merge", collection._find_row(collection.load_collection(p), "sol ring")["count"], 3)
    collection.add_card("Llanowar Elves", 1, p)
    check("crud.add.new", len(collection.load_collection(p)), 3)
    # set_count, and 0 removes
    collection.set_count("Sol Ring", 5, p)
    check("crud.setcount", collection._find_row(collection.load_collection(p), "sol ring")["count"], 5)
    collection.set_count("Sol Ring", 0, p)
    check_true("crud.setcount.zero_removes",
               collection._find_row(collection.load_collection(p), "sol ring") is None)
    # remove via front face
    collection.remove_card("Fire", p)
    check_true("crud.remove.dfc",
               collection._find_row(collection.load_collection(p), "fire // ice") is None)
    # bulk import merge then replace
    collection.bulk_import("2 Llanowar Elves\n1 Brainstorm", "merge", p)
    check("crud.bulk.merge", collection._find_row(collection.load_collection(p), "llanowar elves")["count"], 3)
    collection.bulk_import("Count,Name\n4,Island", "replace", p)
    rows2 = collection.load_collection(p)
    check("crud.bulk.replace.len", len(rows2), 1)
    check("crud.bulk.replace.count", rows2[0]["count"], 4)
    # .bak is created on write
    check_true("crud.bak_exists", bak.exists())
    p.unlink()
    if bak.exists():
        bak.unlink()


def test_buildable_scan():
    import buildable as bd
    # role classification
    ramp = {"type_line": "Artifact", "oracle_text": "{T}: Add {C}{C}."}
    draw = {"type_line": "Instant", "oracle_text": "Draw two cards."}
    removal = {"type_line": "Instant", "oracle_text": "Destroy target creature."}
    wipe = {"type_line": "Sorcery", "oracle_text": "Destroy all creatures."}
    check_true("bd.ramp", "ramp" in bd.classify_roles(ramp))
    check_true("bd.draw", "draw" in bd.classify_roles(draw))
    check_true("bd.removal", "removal" in bd.classify_roles(removal))
    check_true("bd.wipe", "wipe" in bd.classify_roles(wipe))
    # commander eligibility (legendary creature vs not; DFC face; explicit text)
    check_true("bd.cmd.legcrea", bd.is_commander_eligible(
        {"type_line": "Legendary Creature — Elf Druid"}))
    check_true("bd.cmd.no", not bd.is_commander_eligible(
        {"type_line": "Creature — Goblin"}))
    check_true("bd.cmd.text", bd.is_commander_eligible(
        {"type_line": "Legendary Planeswalker — X", "oracle_text": "X can be your commander."}))
    # scoring: color-identity filter + role floors -> gaps
    cmd = {"id": "c", "name": "Cmd", "color_identity": ["G"], "type_line": "Legendary Creature",
           "legalities": {"commander": "legal"}}
    pool = [cmd] + [
        {"id": f"g{i}", "name": f"G{i}", "color_identity": ["G"], "type_line": "Creature",
         "legalities": {"commander": "legal"}, "oracle_text": "Draw a card."} for i in range(5)
    ] + [
        {"id": "u1", "name": "OffColor", "color_identity": ["U"], "type_line": "Creature",
         "legalities": {"commander": "legal"}, "oracle_text": ""},
        {"id": "b1", "name": "Forest", "color_identity": [], "type_line": "Basic Land — Forest",
         "legalities": {"commander": "legal"}},
    ]
    s = bd.score_commander(cmd, pool)
    check("bd.score.nonland", s["owned_nonland"], 5)        # off-color + basic excluded
    check("bd.score.draw", s["roles"]["draw"], 5)
    check_true("bd.score.gaps", "ramp" in s["gaps"] and "removal" in s["gaps"])
    check_true("bd.score.pct", s["buildable_pct"] == round(100 * 5 / bd.TARGET_NONLAND))


def test_prefer_owned():
    from deck_builder import DeckBuilder
    b = DeckBuilder(None)  # _prefer_owned never touches the client
    cands = [{"name": "A"}, {"name": "B"}, {"name": "C"}, {"name": "D"}]
    check("prefer.off", [c["name"] for c in b._prefer_owned(cands)], ["A", "B", "C", "D"])
    b._owned = {"c", "a"}  # owned-first, EDHREC order kept within each group
    check("prefer.on", [c["name"] for c in b._prefer_owned(cands)], ["A", "C", "B", "D"])


# ── App paths are CWD-independent ────────────────────────────────────────────
# Every data dir the app reads or writes must resolve against the app directory,
# never the process CWD. When these were bare relative literals, launching the
# server by absolute path (shortcut / IDE / scheduler) forked the app's state into
# whatever directory the process started in: a second cache/ that never hit its own
# imported-deck entries, a second generated_art/ the deck view couldn't find art in,
# and card_assets/ fonts missing outright.
_DATA_DIR_NAMES = ("card_assets", "scryfall_cache", "face_uploads", "generated_art",
                   "cache", "renders", "cc_config.json")


def test_app_paths_absolute():
    import re
    from pathlib import Path
    from app_paths import APP_DIR
    import card_video, deck_import, face_ref, scryfall_client

    for label, p in (("renderer.assets", cr._ASSETS),
                     ("renderer.art_cache", cr._ART_CACHE),
                     ("cc.config", cc_frames._CONFIG_FILE),
                     ("video.workflows", card_video._WORKFLOW_DIR),
                     ("import.cache", deck_import._CACHE_DIR),
                     ("face.dir", face_ref.FACE_DIR),
                     ("scryfall.cache", scryfall_client._CACHE_DIR)):
        check_true(f"paths.{label}.absolute", p.is_absolute())
        check_true(f"paths.{label}.under_app", APP_DIR in p.parents or p == APP_DIR)

    # Source guard: no runtime module may reintroduce a CWD-relative data path.
    # (Dev-only ro_*/test_* scratch scripts are exempt — they write scratch output.)
    # Matches Path("cache") and the _Path alias server.py uses; app_path() is
    # lowercase, so it never trips the pattern.
    pat = re.compile(r'Path\(\s*["\'](' + "|".join(_DATA_DIR_NAMES) + r')[/"\']')
    exempt = {"app_paths.py", "install.py", "verify-setup.py", "recover_deck.py",
              "test_render.py", "test_gen.py"}
    offenders = []
    for src in sorted(APP_DIR.glob("*.py")) + sorted((APP_DIR / "utilities").glob("*.py")):
        if src.name in exempt or src.name.startswith(("ro_", "gen_")):
            continue
        for i, line in enumerate(src.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line):
                offenders.append(f"{src.name}:{i}")
    check("paths.no_cwd_relative", offenders, [])


def main():
    for fn in (test_commander_tribe, test_name_too_close, test_tribal_text,
               test_tribal_type_line, test_parse_mana, test_frame_key, test_legibility,
               test_theme_detection, test_creature_floor_plan,
               test_pad_with_basics, test_set_symbol_rarity, test_ro_race_class,
               test_ro_class_override, test_stub_prompt, test_ro_tribal_map,
               test_subject_directives, test_artifact_object_kind,
               test_creative_brief_helpers, test_name_art_coherence,
               test_oracle_reminder_italics, test_card_video_helpers,
               test_set_bible_factions, test_foil_and_formats,
               test_commander_user_name,
               test_collection_owned_key, test_collection_parse,
               test_collection_owned_count, test_prefer_owned,
               test_collection_write_is_atomic, test_suite_path_contract, test_collection_preserves_scanner_columns,
               # Deck import / identity. These existed but were never listed here, so
               # `python tests/test_smoke.py` skipped them entirely.
               test_import_preserves_decklist, test_import_line_formats,
               test_import_zone_headers, test_leading_commander_promotion,
               test_archidekt_respects_included_in_deck,
               test_fuzzy_substitution_guard, test_deck_identity_is_preserved,
               test_export_covers_unrendered_cards,
               test_app_paths_absolute):
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
