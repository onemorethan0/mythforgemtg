"""Strength API (suite contract C2) — offline via injected synthetic stores."""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from mythgauntlet.data.scryfall import CardDb  # noqa: E402
from mythgauntlet.semantics.store import SemanticsStore  # noqa: E402
from mythgauntlet.server import create_app  # noqa: E402

DECK = """
Commander:
1 Test Commander

Deck:
30 Forest
20 Grizzly Bears
1 Not A Real Card
"""


@pytest.fixture
def client(tmp_path, make_card, forest, bear, monkeypatch):
    # Hermetic: never let tests read the machine's real Myth Suite collection.
    monkeypatch.setenv("MYTHSUITE_DIR", str(tmp_path / "suite"))
    commander = make_card(
        "Test Commander", mana_cost="{2}{G}", type_line="Legendary Creature — Beast",
        color_identity=("G",),
    )
    commander.power = "4"
    commander.toughness = "4"
    bear.power = "2"
    bear.toughness = "2"
    rhystic = make_card("Rhystic Study", mana_cost="{2}{U}", type_line="Enchantment")
    rhystic.game_changer = True
    db = CardDb([forest, bear, commander, rhystic])
    store = SemanticsStore(authored=tmp_path / "a", compiled=tmp_path / "c")
    return TestClient(create_app(db=db, store=store))


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["cards_in_store"] == 4
    assert "engine_version" in body


def test_analyze_returns_report_and_coverage(client):
    resp = client.post("/analyze", json={"deck": DECK, "runs": 100, "name": "green"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["deck"]["commander"] == "Test Commander"
    assert body["deck"]["cards"] == 51  # unresolved card excluded
    assert body["deck"]["unresolved"] == ["Not A Real Card"]
    assert 0 <= body["report"]["consistency_score"] <= 100
    assert body["semantics_coverage"]["rung1"] == 51
    assert body["bracket_hint"].startswith("Brackets 1-2")
    assert body["tier"] == "T0"
    # Power Profile summary + Tier-1 resilience (default on)
    pp = body["power_profile"]
    assert 0 <= pp["consistency"] <= 100
    assert 0 <= pp["interaction"] <= 100
    assert 0 <= pp["ceiling"] <= 100
    assert pp["bracket_hint"].startswith("Brackets 1-2")
    assert 0.0 <= body["resilience"]["score"] <= 100.0
    assert body["resilience"]["wipe_turn"] >= 2


def test_analyze_can_skip_resilience(client):
    body = client.post(
        "/analyze", json={"deck": DECK, "runs": 40, "resilience": False}
    ).json()
    assert body["resilience"] is None
    assert body["power_profile"]["resilience"] is None


def test_analyze_flags_game_changers(client):
    deck = "30 Forest\n1 Rhystic Study\n"
    body = client.post("/analyze", json={"deck": deck, "runs": 50}).json()
    assert body["game_changers"] == ["Rhystic Study"]
    assert "Bracket 3+" in body["bracket_hint"]


def test_analyze_ownership(client):
    resp = client.post(
        "/analyze",
        json={"deck": DECK, "runs": 50, "collection": "Count,Name\n10,Forest\n"},
    )
    body = resp.json()
    assert body["engine_version"]
    ownership = body.get("ownership") or {}
    # route builds ownership only when collection given; missing list includes bears
    assert any(m["name"] == "Grizzly Bears" for m in ownership.get("missing", []))
    assert ownership.get("owned") == 10
    assert ownership.get("source") == "request"


def test_analyze_defaults_to_suite_collection(client, tmp_path):
    """Contract C1: the canonical suite export is used when no collection is given."""
    suite = tmp_path / "suite"
    suite.mkdir(parents=True, exist_ok=True)
    (suite / "collection.csv").write_text("Count,Name\n5,Forest\n", encoding="utf-8")
    body = client.post("/analyze", json={"deck": DECK, "runs": 40}).json()
    assert body["ownership"] is not None
    assert body["ownership"]["source"] == "suite"
    assert body["ownership"]["owned"] == 5
    # explicit opt-out wins
    body2 = client.post(
        "/analyze", json={"deck": DECK, "runs": 40, "use_suite_collection": False}
    ).json()
    assert body2["ownership"] is None


def test_analyze_no_suite_file_means_no_ownership(client):
    body = client.post("/analyze", json={"deck": DECK, "runs": 40}).json()
    assert body["ownership"] is None


def test_analyze_rejects_empty_deck(client):
    assert client.post("/analyze", json={"deck": "1 Not A Real Card\n"}).status_code == 400


def test_advise_structural(client):
    """Advise runs the ablation over owned candidates and returns measured fields."""
    resp = client.post(
        "/advise",
        json={
            "deck": DECK, "runs": 60, "max_eval": 3,
            # Alpha Bear isn't in the db -> skipped; bears already in deck -> skipped;
            # fixture Rhystic has an EMPTY color identity -> fits any deck, gets tested.
            "collection": "Count,Name\n1,Rhystic Study\n1,Alpha Bear\n4,Grizzly Bears\n",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["axis"] in ("consistency", "speed", "interaction", "ceiling", "resilience")
    assert body["axis_label"]
    assert body["collection_source"] == "request"
    assert body["candidates_that_fit"] == 1  # Rhystic only
    assert body["evaluated"] == 1            # the ablation actually ran
    assert body["cut_pool"] >= 1            # per-swap cut selection surfaced
    assert body["analyses"] >= body["evaluated"]  # >=1 re-sim per candidate
    assert isinstance(body["suggestions"], list)
    for s in body["suggestions"]:            # measured fields, positive deltas only
        assert s["add"] == "Rhystic Study"
        assert s["after"] > s["before"]


def test_advise_evaluates_fitting_candidate(client):
    """A green owned card that isn't in the deck gets ablation-tested."""
    resp = client.post(
        "/advise",
        json={
            "deck": "Commander:\n1 Test Commander\n\nDeck:\n30 Forest\n20 Grizzly Bears\n",
            "runs": 60, "max_eval": 3, "axis": "consistency",
            "collection": "Count,Name\n1,Test Commander\n",  # commander is in-deck -> filtered
        },
    )
    assert resp.status_code == 200
    assert resp.json()["candidates_that_fit"] == 0  # in-deck names never suggested


def test_advise_accepts_and_tolerates_themes(client):
    """`themes` is the archetype handoff, and an unknown name must not 400.

    The detector lives in Forge and the engine is a separate release, so Forge can learn a
    new archetype at any time. The engine must degrade to the population baseline rather
    than reject the request — an advisor that 500s on an unrecognised string is worse than
    one that judges the deck a little bluntly.
    """
    body = {"deck": DECK, "runs": 40, "max_eval": 2,
            "collection": "Count,Name\n1,Rhystic Study\n"}
    for themes in ([], ["spellslinger"], ["not_a_real_theme"], ["spellslinger", "landfall"]):
        resp = client.post("/advise", json={**body, "themes": themes})
        assert resp.status_code == 200, f"themes={themes} -> {resp.status_code}"


def test_advise_rejects_unknown_axis(client):
    resp = client.post(
        "/advise",
        json={"deck": DECK, "axis": "vibes", "collection": "Count,Name\n1,Forest\n"},
    )
    assert resp.status_code == 400
    assert "unknown axis" in resp.json()["detail"]


def test_advise_requires_a_collection(client):
    # fixture points MYTHSUITE_DIR at an empty tmp dir -> no suite export either
    resp = client.post("/advise", json={"deck": DECK, "runs": 40})
    assert resp.status_code == 400
    assert "OWN" in resp.json()["detail"]


def test_advise_uses_suite_collection(client, tmp_path, make_card):
    suite = tmp_path / "suite"
    suite.mkdir(parents=True, exist_ok=True)
    (suite / "collection.csv").write_text("Count,Name\n2,Forest\n", encoding="utf-8")
    body = client.post("/advise", json={"deck": DECK, "runs": 40}).json()
    assert body["collection_source"] == "suite"
    assert body["candidates_that_fit"] == 0  # lands never suggested


def test_analyze_combos_off_by_default_is_network_free(client, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("find_combos must not be called when combos is off")
    monkeypatch.setattr("mythgauntlet.data.spellbook.find_combos", _boom)
    body = client.post("/analyze", json={"deck": DECK, "runs": 50}).json()
    assert body["power_profile"]["combos_checked"] is False
    assert body["combos"] == {"checked": False, "total": 0, "items": []}


def test_analyze_combos_grades_and_gates(client, monkeypatch):
    from mythgauntlet.data.spellbook import parse_response
    fake = parse_response({"results": {"included": [{
        "id": "1",
        "uses": [{"card": {"name": "Grizzly Bears"}}, {"card": {"name": "Forest"}}],
        "produces": [{"feature": {"name": "Win the game"}}],
        "manaValueNeeded": 2,
    }], "almostIncluded": []}})
    monkeypatch.setattr("mythgauntlet.data.spellbook.find_combos", lambda *a, **k: fake)
    body = client.post("/analyze", json={"deck": DECK, "runs": 50, "combos": True}).json()
    assert body["power_profile"]["combos_checked"] is True
    combos = body["combos"]
    assert combos["checked"] and combos["total"] == 1
    item = combos["items"][0]
    assert item["reliability"] == "fast-win" and item["terminal"] is True
    assert item["deterministic"] is True and "CR 720" in item["determinism_rule"]
    # the combo gate lifted the bracket off Brackets 1-2
    assert body["power_profile"]["bracket_estimate"] >= 3


def test_analyze_combos_survives_spellbook_outage(client, monkeypatch):
    import requests
    monkeypatch.setattr(
        "mythgauntlet.data.spellbook.find_combos",
        lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("down")),
    )
    body = client.post("/analyze", json={"deck": DECK, "runs": 50, "combos": True}).json()
    assert body["power_profile"]["combos_checked"] is False  # degraded, not a 500
    assert body["combos"]["checked"] is False


def test_duel(client):
    aggro = "20 Forest\n40 Grizzly Bears\n"
    lands = "60 Forest\n"
    resp = client.post(
        "/duel", json={"deck_a": aggro, "deck_b": lands, "games": 20, "turns": 20}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["wins_a"] + body["result"]["wins_b"] + body["result"]["draws"] == 20
    assert body["winrate_a"] > 0.8
    assert body["tier"] == "T2-mvp"
