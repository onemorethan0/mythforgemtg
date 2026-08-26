"""Commander-conditioned lift ordering. Written from docs/SPEC_edhrec_lift.md.

Offline: every test either builds a payload by hand or monkeypatches the HTTP call. No
network, no reliance on a live EDHREC page.
"""

from __future__ import annotations

import json
import time

import pytest

import edhrec_lift


@pytest.fixture(autouse=True)
def lift_enabled(monkeypatch):
    """tests/conftest.py turns lift OFF for the session (offline builder tests). These
    tests exercise the fetch path itself and stub the HTTP call, so turn it back on."""
    monkeypatch.setenv("MYTHFORGE_EDHREC_LIFT", "on")


def test_kill_switch_short_circuits_before_any_io(monkeypatch):
    """`off` must return {} without touching network or disk."""
    def boom(*a, **kw):
        raise AssertionError("lift_map touched the network while disabled")

    monkeypatch.setenv("MYTHFORGE_EDHREC_LIFT", "off")
    monkeypatch.setattr(edhrec_lift.requests, "get", boom)
    assert edhrec_lift.enabled() is False
    assert edhrec_lift.lift_map("Kadena, Slinking Sorcerer") == {}


def _payload(*pairs: tuple[str, float]) -> dict:
    """A minimal EDHREC commander page carrying the given (name, synergy) rows."""
    return {
        "container": {
            "json_dict": {
                "cardlists": [
                    {
                        "tag": "highsynergycards",
                        "cardviews": [
                            {"name": n, "synergy": s, "num_decks": 10,
                             "potential_decks": 100}
                            for n, s in pairs
                        ],
                    }
                ]
            }
        }
    }


def _cards(*names: str) -> list[dict]:
    return [{"name": n} for n in names]


# ── slug / normalize ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("Kadena, Slinking Sorcerer", "kadena-slinking-sorcerer"),
    ("Atraxa, Praetors' Voice", "atraxa-praetors-voice"),
    ("Fire // Ice", "fire"),                       # front face only
    ("  Spaced   Out  ", "spaced-out"),            # no dangling dashes
])
def test_commander_slug(name, expected):
    assert edhrec_lift.commander_slug(name) == expected


def test_slug_matches_the_engine_implementation():
    """Two copies of this rule exist (app root + engine); they must not drift."""
    from mythgauntlet.data import edhrec as engine_edhrec
    for name in ["Kadena, Slinking Sorcerer", "Atraxa, Praetors' Voice", "Fire // Ice"]:
        assert edhrec_lift.commander_slug(name) == engine_edhrec.commander_slug(name)


def test_normalize_name_front_face_and_case():
    assert edhrec_lift.normalize_name("Fire // Ice") == "fire"
    assert edhrec_lift.normalize_name("SOL  Ring") == "sol ring"


# ── lift_order ──────────────────────────────────────────────────────────────────

def test_lift_order_three_tiers():
    """positive (by lift desc) -> unknown (original order) -> negative (original order)."""
    cards = _cards("Staple", "BigSynergy", "Unknown A", "SmallSynergy", "Unknown B", "Anti")
    lifts = {
        "staple": 0.0,          # exactly zero counts as non-positive
        "bigsynergy": 0.90,
        "smallsynergy": 0.10,
        "anti": -0.15,
    }
    out = [c["name"] for c in edhrec_lift.lift_order(cards, lifts)]
    assert out == ["BigSynergy", "SmallSynergy", "Unknown A", "Unknown B", "Staple", "Anti"]


def test_unknown_outranks_measured_negative():
    """An absent card is UNMEASURED, not rejected — a card printed last week has no
    EDHREC history, and demoting it below a known-negative staple would penalise every
    new release."""
    cards = _cards("Counterspell", "Brand New Card")
    out = [c["name"] for c in edhrec_lift.lift_order(cards, {"counterspell": -0.13})]
    assert out == ["Brand New Card", "Counterspell"]


def test_lift_order_is_a_noop_without_lifts():
    cards = _cards("A", "B", "C")
    assert [c["name"] for c in edhrec_lift.lift_order(cards, {})] == ["A", "B", "C"]


def test_lift_order_does_not_mutate_input():
    cards = _cards("Low", "High")
    original = list(cards)
    edhrec_lift.lift_order(cards, {"high": 0.9, "low": 0.1})
    assert cards == original


def test_equal_lifts_keep_incoming_order():
    """Ties fall back to the incoming EDHREC-rank order, and the sort must never try to
    compare two card dicts (which are not orderable)."""
    cards = _cards("First", "Second", "Third")
    out = [c["name"] for c in edhrec_lift.lift_order(cards, {n.casefold(): 0.5 for n in
                                                            ("First", "Second", "Third")})]
    assert out == ["First", "Second", "Third"]


def test_lift_order_tolerates_a_missing_name_key():
    out = edhrec_lift.lift_order([{}, {"name": "Known"}], {"known": 0.5})
    assert [c.get("name") for c in out] == ["Known", None]


# ── parsing ─────────────────────────────────────────────────────────────────────

def test_parse_keeps_first_synergy_for_a_repeated_name():
    payload = {
        "container": {"json_dict": {"cardlists": [
            {"tag": "a", "cardviews": [{"name": "Dup", "synergy": 0.5}]},
            {"tag": "b", "cardviews": [{"name": "Dup", "synergy": 0.1}]},
        ]}}
    }
    assert edhrec_lift._parse_lifts(payload) == {"dup": 0.5}


@pytest.mark.parametrize("payload", [
    {}, {"container": {}}, {"container": {"json_dict": {"cardlists": None}}},
    {"container": {"json_dict": {"cardlists": ["not a dict"]}}},
    {"container": {"json_dict": {"cardlists": [{"cardviews": [{"name": "X"}]}]}}},   # no synergy
])
def test_parse_degrades_to_empty_on_a_shape_change(payload):
    """Unofficial API: a shape change must mean 'no ordering hint', never an exception."""
    assert edhrec_lift._parse_lifts(payload) == {}


# ── lift_map: caching, staleness, failure ───────────────────────────────────────

@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(edhrec_lift, "app_path", lambda *p: tmp_path.joinpath(*p))
    return tmp_path / "cache" / "edhrec"


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_lift_map_fetches_parses_and_caches(cache_dir, monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return _Resp(_payload(("Stratus Dancer", 0.9)))

    monkeypatch.setattr(edhrec_lift.requests, "get", fake_get)
    got = edhrec_lift.lift_map("Kadena, Slinking Sorcerer")
    assert got == {"stratus dancer": 0.9}
    cached = cache_dir / "kadena-slinking-sorcerer.json"
    assert cached.exists()
    # The cache holds the RAW PAYLOAD; a second call must PARSE it, not return it.
    assert "container" in json.loads(cached.read_text(encoding="utf-8"))
    assert edhrec_lift.lift_map("Kadena, Slinking Sorcerer") == {"stratus dancer": 0.9}
    assert len(calls) == 1                       # second call served from cache


def test_stale_cache_is_refetched(cache_dir, monkeypatch):
    """A cache that never expires can only ever recommend old cards."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "old-one.json"
    path.write_text(json.dumps(_payload(("Old Card", 0.5))), encoding="utf-8")
    stale = time.time() - 30 * 86400
    import os
    os.utime(path, (stale, stale))

    monkeypatch.setattr(edhrec_lift.requests, "get",
                        lambda url, **kw: _Resp(_payload(("New Card", 0.7))))
    assert edhrec_lift.lift_map("Old One") == {"new card": 0.7}


def test_max_age_days_zero_forces_a_refetch(cache_dir, monkeypatch):
    """`or CACHE_MAX_AGE_DAYS` would turn an explicit 0 back into the 14-day default."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "x.json").write_text(json.dumps(_payload(("Cached", 0.5))), encoding="utf-8")
    monkeypatch.setattr(edhrec_lift.requests, "get",
                        lambda url, **kw: _Resp(_payload(("Fetched", 0.7))))
    assert edhrec_lift.lift_map("X", max_age_days=0) == {"fetched": 0.7}


def test_failed_refetch_falls_back_to_the_stale_cache(cache_dir, monkeypatch):
    """Out-of-date lift still beats no lift."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "y.json"
    path.write_text(json.dumps(_payload(("Old Card", 0.5))), encoding="utf-8")
    stale = time.time() - 30 * 86400
    import os
    os.utime(path, (stale, stale))

    def boom(url, **kw):
        raise OSError("network down")

    monkeypatch.setattr(edhrec_lift.requests, "get", boom)
    assert edhrec_lift.lift_map("Y") == {"old card": 0.5}


def test_lift_map_returns_empty_on_total_failure(cache_dir, monkeypatch):
    """No cache and no network: a build must not fail because EDHREC is unreachable."""
    def boom(url, **kw):
        raise OSError("network down")

    monkeypatch.setattr(edhrec_lift.requests, "get", boom)
    assert edhrec_lift.lift_map("Nobody") == {}
    assert edhrec_lift.lift_map("") == {}


# ── theme sub-pages (S4, 2026-08-26) ─────────────────────────────────────────────

def test_tag_for_themes_picks_the_first_mapped_theme():
    """Caller's own priority order wins — the deck's strongest detected theme first."""
    assert edhrec_lift.tag_for_themes(["not_a_theme", "landfall", "tokens"]) == "landfall"


def test_tag_for_themes_returns_none_for_no_match():
    assert edhrec_lift.tag_for_themes(["draw_matters"]) is None    # deliberately unmapped
    assert edhrec_lift.tag_for_themes([]) is None
    assert edhrec_lift.tag_for_themes(None) is None


def test_archetype_tags_are_plausible_slugs():
    """Every value must look like a real EDHREC slug (lower-case, hyphen-separated) —
    catches a copy-paste of a THEME_PATTERNS key instead of the verified tag."""
    import re
    slug_re = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
    for theme, tag in edhrec_lift.ARCHETYPE_EDHREC_TAGS.items():
        assert slug_re.match(tag), f"{theme} -> {tag!r} is not a plausible EDHREC slug"


def test_archetype_tags_are_known_deck_themes_keys():
    """Every key must be a real `commander_analysis.THEME_PATTERNS` name — the same
    lock-step class this repo has caught repeatedly (theme taxonomy, role targets)."""
    import commander_analysis
    unknown = set(edhrec_lift.ARCHETYPE_EDHREC_TAGS) - set(commander_analysis.THEME_PATTERNS)
    assert not unknown, f"mapped themes that do not exist: {sorted(unknown)}"


def test_theme_lift_map_fetches_the_tag_specific_url(cache_dir, monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return _Resp(_payload(("Lotus Cobra", 0.4)))

    monkeypatch.setattr(edhrec_lift.requests, "get", fake_get)
    got = edhrec_lift.theme_lift_map("Omo, Queen of Vesuva", "landfall")
    assert got == {"lotus cobra": 0.4}
    assert calls == ["https://json.edhrec.com/pages/commanders/omo-queen-of-vesuva/"
                      "landfall.json"]
    assert (cache_dir / "omo-queen-of-vesuva__landfall.json").exists()


def test_theme_lift_map_cache_is_separate_from_the_main_page(cache_dir, monkeypatch):
    """The main page and a theme sub-page must not collide on one cache file."""
    monkeypatch.setattr(edhrec_lift.requests, "get",
                        lambda url, **kw: _Resp(_payload(("Main Card", 0.2))))
    edhrec_lift.lift_map("Omo, Queen of Vesuva")
    monkeypatch.setattr(edhrec_lift.requests, "get",
                        lambda url, **kw: _Resp(_payload(("Sub Card", 0.3))))
    edhrec_lift.theme_lift_map("Omo, Queen of Vesuva", "landfall")
    assert (cache_dir / "omo-queen-of-vesuva.json").exists()
    assert (cache_dir / "omo-queen-of-vesuva__landfall.json").exists()
    assert edhrec_lift.lift_map("Omo, Queen of Vesuva") == {"main card": 0.2}


def test_theme_lift_map_respects_the_kill_switch(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("theme_lift_map touched the network while disabled")

    monkeypatch.setenv("MYTHFORGE_EDHREC_LIFT", "off")
    monkeypatch.setattr(edhrec_lift.requests, "get", boom)
    assert edhrec_lift.theme_lift_map("Omo, Queen of Vesuva", "landfall") == {}


def test_theme_lift_map_degrades_to_empty_without_a_tag():
    assert edhrec_lift.theme_lift_map("Omo, Queen of Vesuva", "") == {}


def test_cache_refresh_overwrites_an_existing_file(cache_dir, monkeypatch):
    """Windows: Path.rename() raises when the target exists, so a refresh would silently
    never update. The write must use replace()."""
    monkeypatch.setattr(edhrec_lift.requests, "get",
                        lambda url, **kw: _Resp(_payload(("First", 0.5))))
    edhrec_lift.lift_map("Z")
    monkeypatch.setattr(edhrec_lift.requests, "get",
                        lambda url, **kw: _Resp(_payload(("Second", 0.6))))
    assert edhrec_lift.lift_map("Z", force=True) == {"second": 0.6}
    payload = json.loads((cache_dir / "z.json").read_text(encoding="utf-8"))
    names = [v["name"] for v in payload["container"]["json_dict"]["cardlists"][0]["cardviews"]]
    assert names == ["Second"]
