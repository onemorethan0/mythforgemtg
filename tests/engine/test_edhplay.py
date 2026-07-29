"""Offline tests for the EDHPlay custom-art export (printings + artselect + export)."""

from __future__ import annotations

from mythgauntlet.data.printings import Printing, PrintingDb, _slim
from mythgauntlet.edhplay import export as edh_export
from mythgauntlet.edhplay.artselect import (
    parse_overrides,
    select_arts,
)


def make_printing(
    name: str,
    set_code: str,
    cn: str,
    *,
    oracle_id: str = "o1",
    scryfall_id: str | None = None,
    released: str = "2020-01-01",
    border: str = "black",
    frame: str = "2015",
    frame_effects: tuple[str, ...] = (),
    full_art: bool = False,
    textless: bool = False,
    lang: str = "en",
    games: tuple[str, ...] = ("paper",),
    digital: bool = False,
    image_status: str = "highres_scan",
) -> Printing:
    return Printing(
        name=name,
        oracle_id=oracle_id,
        scryfall_id=scryfall_id or f"{set_code}-{cn}",
        set_code=set_code,
        collector_number=cn,
        released_at=released,
        border_color=border,
        frame=frame,
        frame_effects=frame_effects,
        full_art=full_art,
        textless=textless,
        lang=lang,
        games=games,
        digital=digital,
        image_status=image_status,
    )


def sol_ring_db() -> PrintingDb:
    return PrintingDb([
        make_printing("Sol Ring", "c16", "40", released="2016-11-11"),
        make_printing("Sol Ring", "ltc", "280", released="2022-04-22",
                      border="borderless", frame_effects=("borderless",)),
        make_printing("Sol Ring", "30a", "329", released="2023-11-16",
                      frame="1997", frame_effects=()),
        make_printing("Sol Ring", "sld", "1000", released="2024-01-01",
                      frame_effects=("showcase",)),
    ])


# --- printings store -------------------------------------------------------------------

def test_printingdb_indexes_by_name_id_and_setcn():
    db = sol_ring_db()
    assert "Sol Ring" in db
    assert "sol ring" in db  # normalized
    assert len(db.printings("Sol Ring")) == 4
    assert db.get_print("ltc-280").collector_number == "280"
    assert db.get_set_cn("LTC", "280").set_code == "ltc"  # case-insensitive
    assert db.get_set_cn("zzz", "1") is None


def test_printingdb_front_face_alias():
    db = PrintingDb([make_printing("Fire // Ice", "apc", "128")])
    assert db.printings("Fire")  # front-face name resolves
    assert db.printings("Fire // Ice")


def test_printing_style_properties_and_label():
    borderless = make_printing("X", "ltc", "280", border="borderless",
                               frame_effects=("borderless",))
    assert borderless.borderless and borderless.paper and borderless.has_image
    assert "borderless" in borderless.label()
    retro = make_printing("X", "30a", "1", frame="1997")
    assert retro.retro
    digital = make_printing("X", "y", "1", games=("mtgo",), digital=True)
    assert not digital.paper
    placeholder = make_printing("X", "y", "1", image_status="placeholder")
    assert not placeholder.has_image


def test_slim_skips_tokens_and_missing_ids():
    assert _slim({"layout": "token", "set": "tznr", "collector_number": "1"}) is None
    assert _slim({"layout": "normal", "collector_number": "1"}) is None  # no set
    ok = _slim({"layout": "normal", "name": "Sol Ring", "set": "c16",
                "collector_number": "40", "id": "abc"})
    assert ok["set"] == "c16" and ok["cn"] == "40"


# --- override parsing ------------------------------------------------------------------

def test_parse_overrides_grammar_and_errors():
    ov = parse_overrides(
        "# comment\n"
        "Sol Ring = ltc 280\n"
        "Command Tower: cmm 999\n"
        "\n"
        "Bad Line Without Sep\n"
        "= empty name\n"
    )
    assert ov.by_name["sol ring"] == "ltc 280"
    assert ov.by_name["command tower"] == "cmm 999"
    assert len(ov.errors) == 2


# --- art selection ---------------------------------------------------------------------

def test_default_policy_leaves_printing_unset():
    db = sol_ring_db()
    [choice] = select_arts([("Sol Ring", 1)], db, policy="default")
    assert choice.printing is None
    assert choice.source == "default"


def test_policy_newest_and_oldest():
    db = sol_ring_db()
    newest = select_arts([("Sol Ring", 1)], db, policy="newest")[0]
    assert newest.printing.set_code == "sld"  # 2024
    oldest = select_arts([("Sol Ring", 1)], db, policy="oldest")[0]
    assert oldest.printing.set_code == "c16"  # 2016


def test_policy_style_filters():
    db = sol_ring_db()
    assert select_arts([("Sol Ring", 1)], db, policy="borderless")[0].printing.set_code == "ltc"
    assert select_arts([("Sol Ring", 1)], db, policy="showcase")[0].printing.set_code == "sld"
    assert select_arts([("Sol Ring", 1)], db, policy="retro")[0].printing.set_code == "30a"


def test_policy_style_falls_back_when_absent():
    db = PrintingDb([make_printing("Basic Guy", "abc", "1", released="2021-01-01")])
    choice = select_arts([("Basic Guy", 1)], db, policy="borderless")[0]
    assert choice.source == "fallback"
    assert choice.printing.set_code == "abc"  # newest fallback
    assert "borderless" in choice.note


def test_policy_random_is_deterministic():
    db = sol_ring_db()
    a = select_arts([("Sol Ring", 1)], db, policy="random", seed=7)[0]
    b = select_arts([("Sol Ring", 1)], db, policy="random", seed=7)[0]
    assert a.printing.scryfall_id == b.printing.scryfall_id


def test_override_exact_printing_wins_over_policy():
    db = sol_ring_db()
    ov = parse_overrides("Sol Ring = c16 40")
    choice = select_arts([("Sol Ring", 1)], db, policy="newest", overrides=ov)[0]
    assert choice.source == "override"
    assert choice.printing.set_code == "c16"


def _pick(db, spec):
    return select_arts([("Sol Ring", 1)], db, overrides=parse_overrides(f"Sol Ring = {spec}"))[0]


def test_override_accepts_paren_and_slash_and_set_only():
    db = sol_ring_db()
    assert _pick(db, "(ltc) 280").printing.set_code == "ltc"
    assert _pick(db, "ltc/280").printing.set_code == "ltc"
    # bare set token -> newest printing in that set
    assert _pick(db, "30a").printing.set_code == "30a"


def test_override_scryfall_id_and_keyword():
    db = sol_ring_db()
    by_id = select_arts([("Sol Ring", 1)], db,
                        overrides=parse_overrides("Sol Ring = scryfall:sld-1000"))[0]
    assert by_id.printing.collector_number == "1000"
    by_kw = select_arts([("Sol Ring", 1)], db,
                        overrides=parse_overrides("Sol Ring = showcase"))[0]
    assert by_kw.printing.set_code == "sld"


def test_override_miss_falls_back_and_reports():
    db = sol_ring_db()
    choice = select_arts([("Sol Ring", 1)], db, policy="newest",
                         overrides=parse_overrides("Sol Ring = zzz 5"))[0]
    assert choice.source == "fallback"
    assert choice.printing.set_code == "sld"  # newest
    assert "not found" in choice.note


def test_unknown_card_left_by_name():
    db = sol_ring_db()
    choice = select_arts([("Totally Fake Card", 2)], db, policy="newest")[0]
    assert choice.printing is None
    assert choice.source == "unknown"


def test_paper_only_filter():
    db = PrintingDb([
        make_printing("Digital Only", "mtgo", "1", games=("mtgo",), digital=True),
        make_printing("Digital Only", "prm", "9", games=("paper",)),
    ])
    paper = select_arts([("Digital Only", 1)], db, policy="newest")[0]
    assert paper.printing.set_code == "prm"


# --- export ----------------------------------------------------------------------------

def test_bulk_text_pins_printing_and_headers_commander():
    db = sol_ring_db()
    main = select_arts([("Sol Ring", 1)], db, policy="newest")
    cmds = select_arts([("Kess, Dissident Mage", 1)], db, policy="newest")  # unknown -> by name
    text = edh_export.to_bulk_text(main, cmds, deck_name="Test Deck")
    assert "1 Sol Ring (sld) 1000" in text
    assert "# Commander" in text
    assert "Kess, Dissident Mage" in text
    # commander line is commented out (chosen at deck creation)
    assert "#   1 Kess, Dissident Mage" in text


def test_api_body_shape():
    db = sol_ring_db()
    main = select_arts([("Sol Ring", 2)], db, policy="borderless")
    cmds = select_arts([("A", 1), ("B", 1)], db, policy="newest")
    body = edh_export.to_api_body(main, cmds)
    assert body["replace"] is True
    assert body["cards"][0] == {"name": "Sol Ring", "quantity": 2,
                                "set_code": "ltc", "collector_number": "280"}
    assert body["commander"] == "A"
    assert body["partner_commander"] == "B"


def test_summarize_counts():
    db = sol_ring_db()
    main = select_arts([("Sol Ring", 1), ("Fake", 1)], db, policy="borderless")
    s = edh_export.summarize(main, [])
    assert s.total == 2
    assert s.pinned == 1
    assert s.unknown == 1
