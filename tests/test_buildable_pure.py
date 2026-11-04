"""buildable.py pure functions.

Drafted on a local model (qwen3:8b), then rewritten: the draft had syntax errors, called
``_in_identity`` with a dict where a set is required, and asserted role sets for cards
whose roles come from ``collection_pool.classify`` (not buildable.py), which it never read.
"""
from __future__ import annotations

import buildable


def _card(name, type_line="Creature — Human", ci=(), legal=True, **kw):
    c = {"id": name, "name": name, "type_line": type_line, "color_identity": list(ci),
         "legalities": {"commander": "legal" if legal else "banned"}, "oracle_text": ""}
    c.update(kw)
    return c


def test_commander_eligibility():
    assert buildable.is_commander_eligible(_card("A", "Legendary Creature — Elf"))
    assert not buildable.is_commander_eligible(_card("B", "Creature — Elf"))
    assert not buildable.is_commander_eligible(_card("C", "Legendary Artifact"))
    assert buildable.is_commander_eligible(
        _card("D", "Legendary Planeswalker — X", oracle_text="D can be your commander."))


def test_commander_eligibility_reads_both_faces_of_a_dfc():
    dfc = {"name": "E", "type_line": "", "card_faces": [
        {"type_line": "Legendary Creature — Human", "oracle_text": ""},
        {"type_line": "Legendary Creature — Werewolf", "oracle_text": ""}]}
    assert buildable.is_commander_eligible(dfc)


def test_basic_land_detection():
    assert buildable._is_basic_land(_card("F", "Basic Land — Forest"))
    assert not buildable._is_basic_land(_card("G", "Land"))
    assert not buildable._is_basic_land(_card("H", "Legendary Land"))


def test_identity_subset_rule():
    assert buildable._in_identity(_card("a", ci="W"), {"W", "U"}, False)
    assert buildable._in_identity(_card("b"), {"W"}, False)          # colourless fits anywhere
    assert not buildable._in_identity(_card("c", ci="WB"), {"W"}, False)


def test_colourless_commander_only_takes_colourless_cards():
    assert buildable._in_identity(_card("a"), set(), True)
    assert not buildable._in_identity(_card("b", ci="W"), set(), True)


def test_legal_means_commander_legal_exactly():
    assert buildable._legal(_card("a"))
    assert not buildable._legal(_card("b", legal=False))
    assert not buildable._legal({"name": "c"})
    assert not buildable._legal({"legalities": None})


def test_classify_roles_only_returns_tracked_roles():
    roles = buildable.classify_roles(_card("a", oracle_text="Draw a card."))
    assert roles <= set(buildable._ROLE_FLOORS)
    assert buildable.classify_roles(_card("blank")) == set()


def test_score_commander_filters_the_pool_and_reports_gaps():
    cmd = _card("Cmd", "Legendary Creature — Elf", ci="G")
    pool = [
        cmd,                                              # the commander itself: excluded
        _card("Bear"),                                    # counted (nonland)
        _card("Wolf", ci="G"),                            # counted (nonland)
        _card("Illegal", legal=False),                    # excluded: not legal
        _card("OffColour", ci="R"),                       # excluded: outside identity
        _card("Forest", "Basic Land — Forest"),           # excluded: basic
        _card("Cave", "Land"),                            # counted as a land
    ]
    r = buildable.score_commander(cmd, pool)
    assert r["commander"] == "Cmd"
    assert r["ci"] == "G" and r["color_identity"] == ["G"]
    assert r["owned_nonland"] == 2 and r["owned_lands"] == 1
    assert r["buildable_pct"] == round(100 * 2 / buildable.TARGET_NONLAND)
    assert set(r["roles"]) == set(buildable._ROLE_FLOORS)
    assert len(r["gaps"]) == len(buildable._ROLE_FLOORS)    # nothing owned fills any role
    assert r["image"] == ""


def test_score_commander_colourless_label_and_pct_cap():
    cmd = _card("Cmd", "Legendary Artifact Creature — Golem")
    pool = [_card(f"c{i}") for i in range(200)]
    r = buildable.score_commander(cmd, pool)
    assert r["ci"] == "C"
    assert r["buildable_pct"] == 100


def test_score_commander_image_prefers_small_then_normal():
    cmd = _card("Cmd", ci="G", image_uris={"small": "s", "normal": "n"})
    assert buildable.score_commander(cmd, [])["image"] == "s"
    cmd = _card("Cmd", ci="G", image_uris={"normal": "n"})
    assert buildable.score_commander(cmd, [])["image"] == "n"
