"""Offline tests for scryfall_prints: every record is hand-written, nothing touches the network."""
import pytest

import scryfall_prints

IMG = {"small": "s", "normal": "n", "art_crop": "a", "large": "l"}


def P(pid, name, set_, cn, released="2020-01-01", **kw):
    base = {"id": pid, "oracle_id": "o-" + name, "name": name, "set": set_, "set_name": set_.upper(),
            "collector_number": cn, "rarity": "common", "released_at": released, "lang": "en",
            "finishes": ["nonfoil", "foil"], "frame": "2015", "frame_effects": [], "full_art": False,
            "promo": False, "promo_types": [], "border_color": "black", "artist": "A",
            "layout": "normal", "digital": False,
            "prices": {"usd": "1.50", "usd_foil": None, "usd_etched": None}, "image_uris": dict(IMG)}
    base.update(kw)
    return base


RECORDS = [
    P("id-c21", "Sol Ring", "c21", "263", "2021-04-23"),
    P("id-cmr", "Sol Ring", "cmr", "472", "2020-11-20"),
    P("id-old", "Sol Ring", "lea", "270", "1993-08-05"),
    P("id-f1", "Forest", "c21", "350", "2021-04-23"),
    P("id-f2", "Forest", "c21", "351", "2021-04-23"),
    P("id-dig", "Sol Ring", "pmtg", "1", digital=True),
    P("id-tok", "Goblin", "tc21", "1", layout="token"),
    P("id-fire", "Fire // Ice", "mh2", "290a", "2021-06-18"),
]


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MYTHFORGE_SCRYFALL_PRINTS", "on")
    out = tmp_path / "scryfall_prints.sqlite"
    assert scryfall_prints._build_db(iter(RECORDS), out) == 6
    monkeypatch.setattr(scryfall_prints, "db_path", lambda: out)
    scryfall_prints._close()
    yield out
    scryfall_prints._close()


def test_slim_print_transform_has_back_image():
    card = P("t", "Delver", "isd", "51a", layout="transform", image_uris=None,
             card_faces=[{"image_uris": {"small": "fs", "normal": "fn", "art_crop": "fa"}},
                         {"image_uris": {"small": "bs", "normal": "bn", "art_crop": "ba"}}])
    del card["image_uris"]
    slim = scryfall_prints.slim_print(card)
    assert slim["images"] == {"small": "fs", "normal": "fn", "art_crop": "fa"}
    assert slim["back_images"] == {"small": "bs", "normal": "bn", "art_crop": "ba"}


def test_slim_print_split_has_no_back_image():
    card = P("s", "Fire // Ice", "mh2", "290", layout="split", card_faces=[{}, {}])
    slim = scryfall_prints.slim_print(card)
    assert slim["images"] == {"small": "s", "normal": "n", "art_crop": "a"}
    assert slim["back_images"] is None


def test_slim_print_shape_and_prices():
    slim = scryfall_prints.slim_print(P("x", "Sol Ring", "c21", "263",
                                        prices={"usd": "1.50", "usd_foil": "3.00", "usd_etched": None}))
    assert slim["set"] == "C21" and slim["cn"] == "263"
    assert slim["prices"] == {"usd": 1.5, "usd_foil": 3.0, "usd_etched": None}


def test_digital_and_token_dropped():
    assert scryfall_prints.slim_print({**RECORDS[0], "digital": True}) is None
    assert scryfall_prints.slim_print({**RECORDS[0], "layout": "token"}) is None


def test_resolve_precedence(tmp_db):
    assert scryfall_prints.resolve("Sol Ring", scryfall_id="id-c21")["set"] == "C21"
    assert scryfall_prints.resolve("Sol Ring", "cmr", "472")["id"] == "id-cmr"
    assert scryfall_prints.resolve("Sol Ring", "C21")["id"] == "id-c21"   # one Sol Ring in C21
    assert scryfall_prints.resolve("Forest", "C21") is None               # several Forests: ambiguous
    # id wins over a conflicting set; an unknown id falls through to set+cn
    assert scryfall_prints.resolve("Sol Ring", "cmr", "472", "id-c21")["id"] == "id-c21"
    assert scryfall_prints.resolve("Sol Ring", "cmr", "472", "nope")["id"] == "id-cmr"
    # a wrong collector number does not fall back to a guess when the set holds one print
    assert scryfall_prints.resolve("Sol Ring", "cmr", "999")["id"] == "id-cmr"
    assert scryfall_prints.resolve("Sol Ring") is None


def test_case_insensitive_set_cn_and_names(tmp_db):
    assert scryfall_prints.by_set_cn("MH2", "290A")["id"] == "id-fire"
    assert scryfall_prints.by_set_cn("mh2", "290a")["id"] == "id-fire"
    assert scryfall_prints.resolve("SOL RING ", "Cmr", "472")["id"] == "id-cmr"
    assert scryfall_prints.resolve("Fire", "mh2", "290a")["id"] == "id-fire"   # front face


def test_prints_of_newest_first(tmp_db):
    assert [p["id"] for p in scryfall_prints.prints_of("sol ring")] == ["id-c21", "id-cmr", "id-old"]
    assert scryfall_prints.prints_of("Nope") == []


def test_by_id(tmp_db):
    assert scryfall_prints.by_id("id-old")["set"] == "LEA"
    assert scryfall_prints.by_id("missing") is None


def test_disabled_returns_none(tmp_db, monkeypatch):
    monkeypatch.setenv("MYTHFORGE_SCRYFALL_PRINTS", "off")
    assert scryfall_prints.resolve("Sol Ring", "cmr", "472") is None
    assert scryfall_prints.by_id("id-c21") is None
    assert scryfall_prints.prints_of("Sol Ring") == []


def test_refresh_async_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("MYTHFORGE_SCRYFALL_PRINTS", "off")
    monkeypatch.setattr(scryfall_prints, "refresh", lambda *a, **k: pytest.fail("must not refresh"))
    scryfall_prints.refresh_async()


def test_missing_db_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("MYTHFORGE_SCRYFALL_PRINTS", "on")
    monkeypatch.setattr(scryfall_prints, "db_path", lambda: tmp_path / "none.sqlite")
    scryfall_prints._close()
    assert scryfall_prints.resolve("Sol Ring", "cmr", "472") is None
    assert scryfall_prints.age_days() is None


def test_failed_build_leaves_no_part(tmp_path):
    out = tmp_path / "x.sqlite"

    def boom():
        yield RECORDS[0]
        raise RuntimeError("bad stream")
    with pytest.raises(RuntimeError):
        scryfall_prints._build_db(boom(), out)
    assert not out.exists()


def test_conn_restats_only_after_the_throttle_and_then_reopens_a_rebuilt_db(tmp_db, monkeypatch):
    import os
    clock = [1000.0]
    monkeypatch.setattr(scryfall_prints.time, "monotonic", lambda: clock[0])
    assert scryfall_prints.by_id("id-c21")["cn"] == "263"
    first = scryfall_prints._CONN
    # rebuild the same path with different data (the connection is released first: Windows
    # will not replace an open file; refresh() does the same under _LOCK)
    new = [P("id-new", "Sol Ring", "znr", "1", "2023-01-01")]
    part = tmp_db.with_suffix(".part")
    scryfall_prints._build_db(iter(new), part)
    first.close()
    os.replace(part, tmp_db)
    os.utime(tmp_db, (tmp_db.stat().st_atime, tmp_db.stat().st_mtime + 10))
    # inside the window nothing is re-stat'd: the (now closed) cached connection is returned
    clock[0] += scryfall_prints.STAT_INTERVAL_S - 0.5
    assert scryfall_prints._conn() is first
    # past the window the file is re-stat'd and the rebuilt DB is opened
    clock[0] += 1.0
    assert scryfall_prints.by_id("id-new")["set"] == "ZNR"
    assert scryfall_prints.by_id("id-c21") is None
    assert scryfall_prints._CONN is not first


def test_conn_does_not_stat_the_db_inside_the_window(tmp_db, monkeypatch):
    clock = [50.0]
    monkeypatch.setattr(scryfall_prints.time, "monotonic", lambda: clock[0])
    scryfall_prints.by_id("id-c21")
    import pathlib
    real = pathlib.Path.stat
    calls = []
    monkeypatch.setattr(pathlib.Path, "stat", lambda self, *a, **k: (calls.append(1), real(self, *a, **k))[1])
    for _ in range(20):
        scryfall_prints.by_id("id-c21")
    assert calls == []
