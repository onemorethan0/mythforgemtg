"""Commander Spellbook parsing (offline fixtures)."""

from mythgauntlet.data.spellbook import (
    _request_body,
    is_winning_combo,
    parse_response,
    winning_combos,
)
from mythgauntlet.model.card import normalize_name


def _payload():
    return {
        "results": {
            "identity": "C",
            "included": [
                {
                    "id": "450",
                    "uses": [
                        {"card": {"name": "Basalt Monolith"}},
                        {"card": {"name": "Rings of Brighthearth"}},
                    ],
                    "produces": [{"feature": {"name": "Infinite colorless mana"}}],
                    "bracketTag": "R",
                    "manaNeeded": "{3}",
                    "popularity": 5000,
                },
                {"id": "bad", "uses": []},  # tolerated: dropped
            ],
            "almostIncluded": [
                {
                    "id": "451",
                    "uses": [
                        {"card": {"name": "Basalt Monolith"}},
                        {"card": {"name": "Forsaken Monument"}},
                    ],
                    "produces": [{"feature": {"name": "Infinite colorless mana"}}],
                }
            ],
        }
    }


def test_parse_included_and_almost():
    report = parse_response(_payload())
    assert report.identity == "C"
    assert len(report.included) == 1  # empty-uses variant dropped
    combo = report.included[0]
    assert combo.cards == ("Basalt Monolith", "Rings of Brighthearth")
    assert combo.produces == ("Infinite colorless mana",)
    assert combo.is_two_card
    assert report.two_card_count == 1
    assert len(report.almost_included) == 1


def test_missing_from_deck():
    report = parse_response(_payload())
    deck = {normalize_name("Basalt Monolith")}
    missing = report.almost_included[0].missing_from(deck)
    assert missing == ("Forsaken Monument",)


def test_request_body_shape():
    body = _request_body([("Sol Ring", 1), ("Forest", 30)], ["Selvala, Heart of the Wilds"])
    assert body["main"][0] == {"card": "Sol Ring", "quantity": 1}
    assert body["main"][1]["quantity"] == 30
    assert body["commanders"] == [{"card": "Selvala, Heart of the Wilds", "quantity": 1}]


def test_parse_tolerates_empty():
    report = parse_response({})
    assert report.included == [] and report.almost_included == []


def _combo(cards, produces):
    return {
        "id": "x", "uses": [{"card": {"name": c}} for c in cards],
        "produces": [{"feature": {"name": p}} for p in produces],
    }


def test_winning_combo_detection():
    lethal = parse_response({"results": {"included": [
        _combo(["A", "B"], ["Infinite colorless mana", "Infinite combat damage"]),
    ]}})
    mana_only = parse_response({"results": {"included": [
        _combo(["C", "D"], ["Infinite colorless mana"]),  # no outlet -> not a win
    ]}})
    tokens = parse_response({"results": {"included": [
        _combo(["E", "F", "G"], ["Infinite storm count", "Infinite creature tokens"]),
    ]}})
    assert is_winning_combo(lethal.included[0])
    assert not is_winning_combo(mana_only.included[0])
    assert is_winning_combo(tokens.included[0])  # an infinite board wins the next combat


def test_winning_combos_returns_normalized_piece_sets():
    report = parse_response({"results": {"included": [
        _combo(["Kiki-Jiki, Mirror Breaker", "Zealous Conscripts"],
               ["Infinite combat damage"]),
        _combo(["Sol Ring", "Mana Vault"], ["Infinite colorless mana"]),  # excluded
        _combo(["Thassa's Oracle", "Demonic Consultation"], ["Win the game"]),
    ]}})
    combos = winning_combos(report)
    assert len(combos) == 2
    assert frozenset({normalize_name("Kiki-Jiki, Mirror Breaker"),
                      normalize_name("Zealous Conscripts")}) in combos
    assert all(isinstance(s, frozenset) for s in combos)


# --- cache freshness ---------------------------------------------------------------

class _Reached(Exception):
    """Raised in place of a real network call."""


def _no_network(*_a, **_kw):
    raise _Reached


def _seed_cache(tmp_path, monkeypatch, age_days):
    """Point data_dir at tmp_path and pre-seed this deck's combo cache, aged."""
    import hashlib
    import json
    import os
    import time

    from mythgauntlet.data import spellbook

    monkeypatch.setenv("MYTHGAUNTLET_DATA", str(tmp_path))
    cards, commanders = [("Basalt Monolith", 1)], ["Thrasios, Triton Hero"]
    body = spellbook._request_body(cards, commanders)
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False)
    key = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    path = spellbook._cache_path(key)
    path.write_text(json.dumps({"results": {"included": []}}), encoding="utf-8")
    when = time.time() - age_days * 86400
    os.utime(path, (when, when))
    return cards, commanders


def test_find_combos_serves_a_fresh_cache_without_network(tmp_path, monkeypatch):
    from mythgauntlet.data import spellbook

    cards, commanders = _seed_cache(tmp_path, monkeypatch, age_days=1)
    monkeypatch.setattr(spellbook.requests, "post", _no_network)
    assert spellbook.find_combos(cards, commanders).included == []


def test_find_combos_refetches_a_stale_cache(tmp_path, monkeypatch):
    """The cache key is the DECKLIST, so an edited deck re-asks on its own — but a deck
    the user leaves alone never did. Spellbook's database grows, and this is the signal
    that lifts a casual deck from Bracket 2 to Bracket 3, so a stale "no combos" verdict
    stuck permanently.
    """
    import pytest

    from mythgauntlet.data import spellbook

    cards, commanders = _seed_cache(tmp_path, monkeypatch,
                                    age_days=spellbook.MAX_AGE_DAYS + 1)
    monkeypatch.setattr(spellbook.requests, "post", _no_network)
    with pytest.raises(_Reached):
        spellbook.find_combos(cards, commanders)


def test_find_combos_max_age_none_accepts_any_cache(tmp_path, monkeypatch):
    from mythgauntlet.data import spellbook

    cards, commanders = _seed_cache(tmp_path, monkeypatch, age_days=999)
    monkeypatch.setattr(spellbook.requests, "post", _no_network)
    assert spellbook.find_combos(cards, commanders, max_age_days=None).included == []


# --- is_cached: MUST mirror find_combos' cache-hit condition exactly ---------------
# (a corpus harness gates a politeness throttle on this: reporting "cached" for a file
# find_combos is about to refetch live anyway would silently skip the throttle on a
# real network call.)

def test_is_cached_true_for_a_fresh_cache(tmp_path, monkeypatch):
    from mythgauntlet.data import spellbook

    cards, commanders = _seed_cache(tmp_path, monkeypatch, age_days=1)
    assert spellbook.is_cached(cards, commanders) is True


def test_is_cached_false_for_a_stale_cache(tmp_path, monkeypatch):
    from mythgauntlet.data import spellbook

    cards, commanders = _seed_cache(tmp_path, monkeypatch,
                                    age_days=spellbook.MAX_AGE_DAYS + 1)
    assert spellbook.is_cached(cards, commanders) is False


def test_is_cached_false_when_no_cache_file_exists(tmp_path, monkeypatch):
    from mythgauntlet.data import spellbook

    monkeypatch.setenv("MYTHGAUNTLET_DATA", str(tmp_path))
    assert spellbook.is_cached([("Sol Ring", 1)], ["Selvala, Heart of the Wilds"]) is False


def test_is_cached_false_for_a_fresh_but_corrupt_cache_file(tmp_path, monkeypatch):
    """The bug this pins: a cache file that EXISTS and is fresh by mtime but fails to
    parse as JSON is a cache MISS to `find_combos` (it catches JSONDecodeError/OSError
    and falls through to a live request) -- `is_cached` reporting True here would make
    a caller skip its politeness throttle on a call that is actually about to hit the
    network live.
    """
    import hashlib
    import json

    import pytest

    from mythgauntlet.data import spellbook

    cards, commanders = _seed_cache(tmp_path, monkeypatch, age_days=1)
    body = spellbook._request_body(cards, commanders)
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False)
    key = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    spellbook._cache_path(key).write_text("{not valid json", encoding="utf-8")

    assert spellbook.is_cached(cards, commanders) is False
    # And find_combos genuinely treats it as a miss too -- proving the two functions
    # agree, not just that is_cached independently says False.
    monkeypatch.setattr(spellbook.requests, "post", _no_network)
    with pytest.raises(_Reached):
        spellbook.find_combos(cards, commanders)
