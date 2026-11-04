"""The collection API routes that had no tests: import, list (filter / paginate), stats, health,
repair + undo, bulk and delete. Offline: MYTHSUITE_DIR points at tmp_path, and the card store may
be absent (CI's state), so nothing here asserts on enriched metadata."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server

client = TestClient(server.app)
HEADER = "Count,Name,Edition,Collector Number,Foil,Language,Condition,Scryfall ID\n"


@pytest.fixture
def csv_path(tmp_path, monkeypatch):
    monkeypatch.setenv("MYTHSUITE_DIR", str(tmp_path))
    return tmp_path / "collection.csv"


def _seed(csv_path, *lines):
    csv_path.write_text(HEADER + "".join(l + "\n" for l in lines), encoding="utf-8")


def _names():
    return sorted(c["name"] for c in client.get("/api/collection", params={"limit": 0}).json()["cards"])


# -- import --------------------------------------------------------------------------------------------

def test_import_requires_text(csv_path):
    assert client.post("/api/collection/import", json={"text": "   "}).status_code == 400


def test_import_merge_adds_to_what_is_there(csv_path):
    _seed(csv_path, "1,Sol Ring,C21,263,,,,")
    r = client.post("/api/collection/import", json={"text": "2 Island\n3 Sol Ring (C21) 263"})
    assert r.status_code == 200 and r.json()["imported_mode"] == "merge"
    assert _names() == ["Island", "Sol Ring"]
    sol = next(c for c in client.get("/api/collection", params={"limit": 0}).json()["cards"]
               if c["name"] == "Sol Ring")
    assert sol["count"] == 4                                   # 1 existing + 3 imported, same printing


def test_import_replace_overwrites_and_unknown_mode_means_merge(csv_path):
    _seed(csv_path, "1,Sol Ring,C21,263,,,,")
    r = client.post("/api/collection/import", json={"text": "1 Island", "mode": "replace"})
    assert r.json()["imported_mode"] == "replace" and _names() == ["Island"]
    r = client.post("/api/collection/import", json={"text": "1 Forest", "mode": "bogus"})
    assert r.json()["imported_mode"] == "merge" and _names() == ["Forest", "Island"]


def test_import_reads_1x_quantities_and_set_tags(csv_path):
    client.post("/api/collection/import", json={"text": "4x Lightning Bolt (M11) 149 *F*"})
    card = client.get("/api/collection", params={"limit": 0}).json()["cards"][0]
    assert (card["name"], card["count"], card["set"], card["finish"]) == ("Lightning Bolt", 4, "M11", "foil")


# -- list ----------------------------------------------------------------------------------------------------

def test_list_filters_by_name_query_and_reports_the_matched_total(csv_path):
    _seed(csv_path, "1,Sol Ring,,,,,,", "1,Solemn Simulacrum,,,,,,", "1,Island,,,,,,")
    body = client.get("/api/collection", params={"q": "sol"}).json()
    assert body["matched"] == 2
    assert sorted(c["name"] for c in body["cards"]) == ["Sol Ring", "Solemn Simulacrum"]


def test_list_paginates_and_clamps_bad_offsets(csv_path):
    _seed(csv_path, *[f"1,Card {chr(65 + i)},,,,,," for i in range(6)])
    page = client.get("/api/collection", params={"limit": 2, "offset": 2}).json()
    assert page["matched"] == 6 and [c["name"] for c in page["cards"]] == ["Card C", "Card D"]
    neg = client.get("/api/collection", params={"limit": 2, "offset": -5}).json()
    assert [c["name"] for c in neg["cards"]] == ["Card A", "Card B"]
    assert len(client.get("/api/collection", params={"limit": 0}).json()["cards"]) == 6


def test_list_sorts_both_directions_and_unknown_group_means_none(csv_path):
    _seed(csv_path, "1,Beta,,,,,,", "1,Alpha,,,,,,", "1,Gamma,,,,,,")
    asc = [c["name"] for c in client.get("/api/collection", params={"limit": 0}).json()["cards"]]
    desc = [c["name"] for c in client.get("/api/collection",
                                          params={"limit": 0, "direction": "desc"}).json()["cards"]]
    assert asc == ["Alpha", "Beta", "Gamma"] and desc == asc[::-1]
    assert client.get("/api/collection", params={"group": "not-a-group"}).status_code == 200


def test_list_min_count_filter(csv_path):
    _seed(csv_path, "1,One Copy,,,,,,", "4,Four Copies,,,,,,")
    body = client.get("/api/collection", params={"min_count": 3}).json()
    assert [c["name"] for c in body["cards"]] == ["Four Copies"]


def test_list_of_an_empty_collection(csv_path):
    body = client.get("/api/collection").json()
    assert body["cards"] == [] and body["matched"] == 0


# -- stats / health ----------------------------------------------------------------------------------------------

def test_stats_clamps_top_n_and_answers_on_an_empty_collection(csv_path):
    assert client.get("/api/collection/stats").status_code == 200
    assert client.get("/api/collection/stats", params={"top_n": 9999}).status_code == 200
    assert client.get("/api/collection/stats", params={"top_n": -3}).status_code == 200


def test_health_finds_a_whole_decklist_line_stored_as_a_name(csv_path):
    _seed(csv_path, '1,"13x Island (msh) 290 [Land]",,,,,,', "1,Sol Ring,C21,263,,,,")
    body = client.get("/api/collection/health").json()
    assert body["affected"] == 1 and len(body["issues"]) == 1
    assert body["truncated"] is False
    capped = client.get("/api/collection/health", params={"limit": 1}).json()
    assert capped["shown"] == 1


# -- repair / undo ---------------------------------------------------------------------------------------------------

def test_repair_defaults_to_a_dry_run_and_changes_nothing(csv_path):
    _seed(csv_path, '1,"13x Island (msh) 290 [Land]",,,,,,')
    before = csv_path.read_bytes()
    r = client.post("/api/collection/repair", json={})
    assert r.status_code == 200 and r.json()["dry_run"] is True
    assert csv_path.read_bytes() == before


def test_a_real_repair_rewrites_the_card_and_undo_brings_it_back_and_is_itself_undoable(csv_path):
    _seed(csv_path, '1,"13x Island (msh) 290 [Land]",,,,,,')
    original = csv_path.read_bytes()
    assert client.post("/api/collection/repair", json={"dry_run": False}).status_code == 200
    repaired = csv_path.read_bytes()
    assert repaired != original and _names() == ["Island"]
    assert client.post("/api/collection/undo").status_code == 200
    assert csv_path.read_bytes() == original                      # restored exactly
    assert client.post("/api/collection/undo").status_code == 200
    assert csv_path.read_bytes() == repaired                      # pressing it twice swaps back


def test_undo_with_nothing_to_restore_is_a_404(csv_path):
    _seed(csv_path, "1,Sol Ring,,,,,,")
    assert client.post("/api/collection/undo").status_code == 404


# -- bulk ----------------------------------------------------------------------------------------------------------------

def test_bulk_validates_its_input(csv_path):
    _seed(csv_path, "1,Sol Ring,,,,,,")
    assert client.post("/api/collection/bulk", json={"action": "explode", "targets": [{"name": "x"}]}).status_code == 400
    assert client.post("/api/collection/bulk", json={"action": "remove", "targets": []}).status_code == 400
    stale = client.post("/api/collection/bulk", json={"action": "remove", "targets": [{"row_id": "deadbeef0000"}]})
    assert stale.status_code == 409


def test_bulk_remove_and_set_count_by_name(csv_path):
    _seed(csv_path, "2,Sol Ring,,,,,,", "1,Island,,,,,,", "1,Forest,,,,,,")
    r = client.post("/api/collection/bulk", json={"action": "set_count", "count": 7,
                                                  "targets": [{"name": "Sol Ring"}]})
    assert r.status_code == 200
    assert next(c for c in client.get("/api/collection", params={"limit": 0}).json()["cards"]
                if c["name"] == "Sol Ring")["count"] == 7
    r = client.post("/api/collection/bulk", json={"action": "remove",
                                                  "targets": [{"name": "Island"}, {"name": "Forest"}]})
    assert r.status_code == 200 and _names() == ["Sol Ring"]


# -- delete ------------------------------------------------------------------------------------------------------------------

def test_delete_needs_a_name_or_a_row_id(csv_path):
    _seed(csv_path, "1,Sol Ring,,,,,,")
    assert client.delete("/api/collection").status_code == 400


def test_delete_by_name_is_front_face_and_case_insensitive(csv_path):
    _seed(csv_path, "1,Fire // Ice,,,,,,", "1,Island,,,,,,")
    assert client.delete("/api/collection", params={"name": "FIRE"}).status_code == 200
    assert _names() == ["Island"]


def test_delete_by_a_stale_row_id_is_a_409(csv_path):
    _seed(csv_path, "1,Sol Ring,,,,,,")
    assert client.delete("/api/collection", params={"row_id": "deadbeef0000"}).status_code == 409
    assert _names() == ["Sol Ring"]


def test_delete_by_row_id_removes_exactly_that_row(csv_path):
    _seed(csv_path, "1,Sol Ring,C21,263,,,,", "1,Sol Ring,C21,263,foil,,,")
    cards = client.get("/api/collection", params={"limit": 0}).json()["cards"]
    foil = next(c for c in cards if c["finish"] == "foil")
    assert client.delete("/api/collection", params={"row_id": foil["row_id"]}).status_code == 200
    left = client.get("/api/collection", params={"limit": 0}).json()["cards"]
    assert [c["finish"] for c in left] == ["nonfoil"]
