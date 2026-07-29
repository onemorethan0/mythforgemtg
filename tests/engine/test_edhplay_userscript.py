"""Offline tests for the MythForge->EDHPlay custom-art userscript path."""

from __future__ import annotations

import json

import pytest

from mythgauntlet.data.printings import PrintingDb
from mythgauntlet.edhplay import artsource, userscript
from mythgauntlet.edhplay.artsource import ArtRef, ArtSource
from test_edhplay import make_printing


def _art_map(script_text):
    """Extract the embedded ART json literal from a generated userscript."""
    start = script_text.index("var ART = ") + len("var ART = ")
    line = script_text[start:script_text.index(chr(10), start)].rstrip().rstrip(";")
    return json.loads(line)


def deck_db() -> PrintingDb:
    return PrintingDb([
        make_printing("Sol Ring", "c16", "40", scryfall_id="uuid-solring-c16"),
        make_printing("Sol Ring", "ltc", "280", scryfall_id="uuid-solring-ltc"),
        make_printing("Llanowar Elves", "m19", "314", scryfall_id="uuid-llanowar-m19"),
        make_printing("Command Tower", "cmm", "999", scryfall_id="uuid-cmdtower"),
    ])


# --- userscript generation -------------------------------------------------------------

def test_userscript_maps_all_printings_of_arted_cards():
    pdb = deck_db()
    art = ArtSource(
        by_name={
            "sol ring": ArtRef("url", "http://127.0.0.1:8000/api/deck/J/card-image/Sol_Ring_001"),
        },
        connect_hosts={"127.0.0.1"},
        missing_render=[],
    )
    res = userscript.build_userscript(["Sol Ring", "Llanowar Elves"], art, pdb)
    # Sol Ring has 2 printings -> both UUIDs mapped to the same custom image.
    assert res.uuid_count == 2
    assert res.matched == ["Sol Ring"]
    assert res.no_art == ["Llanowar Elves"]
    # metadata + connect host present
    assert "// @match        https://edhplay.com/*" in res.text
    assert "// @connect      127.0.0.1" in res.text
    assert "GM_xmlhttpRequest" in res.text
    # the embedded ART map contains both Sol Ring UUIDs -> the same URL
    art_map = _art_map(res.text)
    assert art_map["uuid-solring-c16"] == art_map["uuid-solring-ltc"]
    assert "uuid-llanowar-m19" not in art_map


def test_userscript_reports_unmatched_art():
    pdb = deck_db()
    art = ArtSource(
        by_name={"nonexistent card": ArtRef("data", "data:image/png;base64,AAAA")},
        connect_hosts=set(),
        missing_render=[],
    )
    res = userscript.build_userscript(["Sol Ring"], art, pdb)
    assert res.unmatched_art == ["nonexistent card"]
    assert res.matched == []
    assert res.uuid_count == 0


def test_userscript_data_uri_needs_no_connect():
    pdb = deck_db()
    art = ArtSource(
        by_name={"command tower": ArtRef("data", "data:image/png;base64,ZZZZ")},
        connect_hosts=set(),
        missing_render=[],
    )
    res = userscript.build_userscript(["Command Tower"], art, pdb)
    assert res.uuid_count == 1
    assert "// @connect" not in res.text  # embedded data needs no cross-origin fetch
    assert _art_map(res.text)["uuid-cmdtower"].startswith("data:image/png")


# --- art sources -----------------------------------------------------------------------

def test_from_dir_embeds_images(tmp_path):
    # 1x1 transparent PNG
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6300010000050001a5f645400000000049454e44ae426082"
    )
    (tmp_path / "Sol Ring.png").write_bytes(png)
    (tmp_path / "Command Tower.jpg").write_bytes(png)
    (tmp_path / "notes.txt").write_text("ignore me")
    src = artsource.from_dir(str(tmp_path))
    assert set(src.by_name) == {"sol ring", "command tower"}
    assert src.by_name["sol ring"].kind == "data"
    assert src.by_name["sol ring"].value.startswith("data:image/png;base64,")
    assert src.connect_hosts == set()


def test_from_manifest_text_and_json(tmp_path):
    (tmp_path / "m.txt").write_text(
        "# comment\nSol Ring = http://127.0.0.1:8000/a.png\nCommand Tower: https://x.test/b.png\n"
    )
    src = artsource.from_manifest(str(tmp_path / "m.txt"))
    assert src.by_name["sol ring"] == ArtRef("url", "http://127.0.0.1:8000/a.png")
    assert src.connect_hosts == {"127.0.0.1", "x.test"}

    (tmp_path / "m.json").write_text(json.dumps({"Sol Ring": "https://y.test/c.png"}))
    src2 = artsource.from_manifest(str(tmp_path / "m.json"))
    assert src2.by_name["sol ring"].value == "https://y.test/c.png"
    assert src2.connect_hosts == {"y.test"}


def test_resolve_rejects_unknown_spec():
    with pytest.raises(ValueError):
        artsource.resolve("bogus:whatever")


def test_from_mythforge_parses_deck_json(monkeypatch):
    payload = {
        "commander": {"original_name": "Kess, Dissident Mage",
                      "render_key": "Kess_000", "has_render": True},
        "deck": [
            {"original_name": "Sol Ring", "render_key": "Sol_Ring_001", "has_render": True},
            {"original_name": "Opt", "render_key": "Opt_002", "has_render": False},
        ],
    }

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return payload

    monkeypatch.setattr(artsource.requests, "get", lambda *a, **k: FakeResp())
    src = artsource.from_mythforge("JOB", base_url="http://127.0.0.1:8000")
    assert src.by_name["sol ring"] == ArtRef(
        "url", "http://127.0.0.1:8000/api/deck/JOB/card-image/Sol_Ring_001")
    assert src.by_name["kess, dissident mage"].kind == "url"
    assert src.missing_render == ["Opt"]        # has_render False -> skipped
    assert src.connect_hosts == {"127.0.0.1"}
