"""Deck value and cost-to-finish (deck_price.py, B20 in docs/DEVELOPMENT_PLAN.md). Offline."""
from __future__ import annotations

import json
from unittest.mock import patch

from fastapi.testclient import TestClient

import deck_price
import server
from api import state

client = TestClient(server.app)


def _p(usd=None, foil=None, lang="en"):
    return {"lang": lang, "prices": {"usd": usd, "usd_foil": foil, "usd_etched": None}}


def _card(name, qty=1, tl="Artifact"):
    return {"original_name": name, "quantity": qty, "type_line": tl}


def test_cheapest_nonfoil_english_printing_wins():
    prints = {"sol ring": [_p(5.0), _p(1.25), _p(0.5, lang="ja"), _p(None, foil=0.1)]}
    found = deck_price.cheapest_lookup(lambda names: prints)(["Sol Ring"])
    assert found == {"sol ring": {"prices": {"usd": 1.25}}}


def test_a_foil_only_card_is_unpriced_never_valued_at_its_foil_price():
    """Mox Diamond's From the Vault print is foil-only ($1,750 foil): D8, a finish never
    borrows another finish's price."""
    prints = {"mox diamond": [_p(None, foil=1750.27)]}
    rep = deck_price.price_deck([_card("Mox Diamond")],
                                deck_price.cheapest_lookup(lambda n: prints), lambda c: False)
    assert rep["unpriced"] == ["Mox Diamond"] and not rep["complete"] and rep["total"] == 0


def test_fallback_only_for_names_the_print_store_lacks():
    calls = []

    def fallback(names):
        calls.append(list(names))
        return {"new card": {"prices": {"usd": "2.00"}}}
    look = deck_price.cheapest_lookup(lambda n: {"sol ring": [_p(1.0)], "new card": []}, fallback)
    assert look(["Sol Ring", "New Card"])["new card"]["prices"]["usd"] == "2.00"
    assert calls == [["New Card"]]


def test_value_counts_everything_cost_to_finish_skips_owned_and_quantities_multiply():
    prices = {"sol ring": [_p(1.5)], "forest": [_p(0.1)], "the one ring": [_p(100.0)]}
    cards = [_card("Sol Ring"), _card("Forest", 30, "Basic Land — Forest"), _card("The One Ring")]
    rep = deck_price.price_deck(cards, deck_price.cheapest_lookup(lambda n: prices),
                                lambda c: c["original_name"] != "The One Ring")
    assert rep["total"] == 104.5                      # 1.5 + 30 x 0.1 + 100
    assert rep["to_buy"] == 100.0 and rep["to_buy_cards"] == 1
    assert rep["priced_cards"] == 32 and rep["complete"]
    assert rep["cards"][0]["name"] == "The One Ring"   # most expensive first


def test_route_prices_the_whole_command_zone(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "RENDER_DIR", tmp_path / "renders")
    jid = "0123456789abcdef"
    d = tmp_path / "renders" / jid
    d.mkdir(parents=True)
    data = {"status": "done", "commander": _card("Krenko, Mob Boss", tl="Legendary Creature"),
            "deck": [_card("Sol Ring"), _card("Mountain", 98, "Basic Land — Mountain")]}
    (d / "deck.json").write_text(json.dumps(data), encoding="utf-8")
    prints = {"krenko, mob boss": [_p(3.0)], "sol ring": [_p(1.0)], "mountain": [_p(0.05)]}
    import scryfall_prints
    with patch.dict(state._jobs, {}, clear=True), \
            patch.object(scryfall_prints, "prints_of_many", lambda names: prints), \
            patch("api.collection_data._owned_names_cached", lambda: set()):
        r = client.get(f"/api/deck/{jid}/price")
    body = r.json()
    assert r.status_code == 200
    assert body["total"] == round(3.0 + 1.0 + 98 * 0.05, 2)
    assert body["to_buy"] == 4.0                       # basics are always owned
    assert body["priced_cards"] == 100
