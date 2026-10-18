"""Table feel (EDHREC community salt) + the 2026-10-18 Interaction re-calibration.

Offline: the salt store is built in a tmp dir from a hand-written MTGJSON-shaped document.
"""

import json

from mythgauntlet.data import salt
from mythgauntlet.ratings import table_feel
from mythgauntlet.ratings.axes import compute_interaction
from mythgauntlet.ratings.table_feel import compute_table_feel, percentile_of

_ATOMIC = {
    "meta": {"date": "2026-10-18"},
    "data": {
        "Armageddon": [{"edhrecSaltiness": 2.98}],
        "Rhystic Study": [{"edhrecSaltiness": 2.82}],
        "Sol Ring": [{"edhrecSaltiness": 1.59}],
        "Llanowar Elves": [{"edhrecSaltiness": 0.25}],
        "Grizzly Bears": [{"edhrecSaltiness": 0.0}],
        "Island": [{"edhrecSaltiness": 0.9}],
        "Gaea's Cradle": [{"edhrecSaltiness": 2.23}],
        "Fire // Ice": [{"edhrecSaltiness": 0.24}, {"edhrecSaltiness": 0.24}],
        "Unsurveyed Thing": [{}],
        "Empty": [],
    },
}


def _db(tmp_path):
    path = tmp_path / "salt.json"
    path.write_text(json.dumps({"schema": salt.SALT_SCHEMA, "mtgjson_date": "2026-10-18",
                                "fetched_at": "2026-10-18",
                                "cards": salt.extract_salt(_ATOMIC)}), encoding="utf-8")
    return salt.load_salt(path)


def test_extract_salt_keeps_scored_cards_and_aliases_the_front_face():
    out = salt.extract_salt(_ATOMIC)
    assert out["armageddon"] == 2.98 and out["grizzly bears"] == 0.0
    assert out["fire // ice"] == out["fire"] == 0.24
    assert "unsurveyed thing" not in out and "empty" not in out


def test_unscored_card_is_unmeasured_not_zero(tmp_path, make_card):
    db = _db(tmp_path)
    assert db.get(make_card("Grizzly Bears")) == 0.0
    assert db.get(make_card("Unsurveyed Thing")) is None


def test_load_salt_declines_bad_files(tmp_path):
    assert salt.load_salt(tmp_path / "missing.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert salt.load_salt(bad) is None
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"schema": 0, "cards": {}}), encoding="utf-8")
    assert salt.load_salt(old) is None


def test_no_store_reads_unavailable_never_friendly(make_card, monkeypatch, tmp_path):
    monkeypatch.setattr(table_feel, "load_salt", lambda: None)
    rep = compute_table_feel([(make_card("Sol Ring"), 1)], [])
    assert rep.available is False and rep.band == "unavailable" and rep.score is None


def test_low_coverage_reads_unavailable(tmp_path, make_card):
    db = _db(tmp_path)
    cards = [(make_card("Sol Ring"), 1), (make_card("Mystery Card"), 9)]
    rep = compute_table_feel(cards, [], db)
    assert rep.available is False and "1 of 10" in rep.reason


def test_salty_deck_outranks_a_friendly_one_and_lists_the_culprits(tmp_path, make_card, monkeypatch):
    monkeypatch.setattr(table_feel, "SALT_PERCENTILES", tuple(float(x) for x in range(0, 105, 5)))
    db = _db(tmp_path)
    cmdr = make_card("Grizzly Bears")
    salty = [(make_card("Armageddon"), 1), (make_card("Rhystic Study"), 1),
             (make_card("Sol Ring"), 1), (make_card("Llanowar Elves"), 96)]
    friendly = [(make_card("Llanowar Elves"), 99)]
    s = compute_table_feel(salty, [cmdr], db)
    f = compute_table_feel(friendly, [cmdr], db)
    assert s.available and f.available
    assert s.score > f.score
    assert [n for n, _ in s.salty_cards] == ["Armageddon", "Rhystic Study", "Sol Ring"]
    assert s.salty_count == 3 and f.salty_cards == []
    assert s.commander_salt == 0.0


def test_basic_lands_are_not_counted_but_nonbasics_are(tmp_path, make_card):
    """Basics' survey scores are noise (Island 0.90); 30 of them made mono-blue decks salty."""
    db = _db(tmp_path)
    island = make_card("Island", type_line="Basic Land — Island", produced_mana=("U",))
    cradle = make_card("Gaea's Cradle", type_line="Legendary Land")
    elves = make_card("Llanowar Elves")
    base = compute_table_feel([(elves, 69)], [], db)
    with_islands = compute_table_feel([(elves, 69), (island, 30)], [], db)
    with_cradle = compute_table_feel([(elves, 69), (cradle, 1)], [], db)
    assert with_islands.total_salt == base.total_salt
    assert with_cradle.total_salt > base.total_salt
    assert [n for n, _ in with_cradle.salty_cards] == ["Gaea's Cradle"]


def test_noticeable_cards_are_listed_even_below_the_salty_line(tmp_path, make_card):
    db = _db(tmp_path)
    counter = make_card("Counterspell")
    db.cards["counterspell"] = 1.2
    rep = compute_table_feel([(counter, 1), (make_card("Llanowar Elves"), 98)], [], db)
    assert rep.salty_cards == [("Counterspell", 1.2)] and rep.salty_count == 0


def test_percentile_interpolates_and_clamps():
    table = tuple(float(x) for x in range(0, 105, 5))   # p == value
    assert percentile_of(-1.0, table) == 0.0
    assert percentile_of(52.5, table) == 52.5
    assert percentile_of(500.0, table) == 100.0
    assert percentile_of(10.0, ()) is None


def test_bands_are_percentile_cuts():
    assert table_feel.band_for(None) == "unavailable"
    assert table_feel.band_for(10.0) == "friendly"
    assert table_feel.band_for(60.0) == "spicy"
    assert table_feel.band_for(85.0) == "salty"


def test_baked_reference_is_monotone_when_present():
    t = table_feel.SALT_PERCENTILES
    assert len(t) in (0, 21)
    assert list(t) == sorted(t)


# ── Interaction re-calibration ──────────────────────────────────────────────────────

def _kill(make_card):
    return make_card("Kill", mana_cost="{1}{B}", type_line="Instant",
                     oracle_text="Destroy target creature.", color_identity=("B",))


def _naturalize(make_card):
    return make_card("Unmake Relic", mana_cost="{1}{G}", type_line="Instant",
                     oracle_text="Destroy target artifact or enchantment.", color_identity=("G",))


def test_counterspells_are_not_a_missing_type_without_blue(make_card, forest):
    deck = [(forest, 38), (_kill(make_card), 8)]
    golgari = compute_interaction(deck, color_identity={"B", "G"})
    sultai = compute_interaction(deck, color_identity={"B", "G", "U"})
    assert golgari.breadth_max == 3 and sultai.breadth_max == 4
    assert golgari.breadth == sultai.breadth == 1
    assert golgari.score > sultai.score     # 1/3 of playable types beats 1/4


def test_a_counter_outside_blue_still_counts(make_card, forest):
    red_counter = make_card("Red Blast", mana_cost="{R}", type_line="Instant",
                            oracle_text="Counter target spell.", color_identity=("R",))
    rep = compute_interaction([(forest, 38), (red_counter, 1)], color_identity={"R"})
    assert rep.counterspells == 1 and rep.breadth_max == 4 and rep.breadth == 1


def test_artifact_enchantment_answers_are_a_fourth_type_at_half_weight(make_card, forest):
    kill_only = compute_interaction([(forest, 38), (_kill(make_card), 4)], color_identity={"B", "G"})
    both = compute_interaction([(forest, 38), (_kill(make_card), 4), (_naturalize(make_card), 2)],
                               color_identity={"B", "G"})
    assert both.noncreature_answers == 2 and both.answers == 6
    assert both.breadth == 2 and kill_only.breadth == 1
    gain = both.effective_answers - kill_only.effective_answers
    assert 0 < gain < 2 * 1.2    # two answers, counted at half weight
