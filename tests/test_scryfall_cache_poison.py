"""A cached name -> card mapping must plausibly be that card (offline)."""
import threading

import scryfall_client as sc


def _client(cache):
    c = object.__new__(sc.ScryfallClient)
    c._card_cache = dict(cache)
    c._cache_lock = threading.Lock()
    return c


def test_a_poisoned_entry_is_dropped_not_served():
    # Live 2026-10-25: written before the fuzzy guard existed, "sol rng" -> Oathsworn Giant
    # kept resolving from the cache and became an imported deck's face card.
    c = _client({"sol rng": {"name": "Oathsworn Giant"}})
    assert c._cache_get("Sol Rng") is None
    assert "sol rng" not in c._card_cache


def test_real_names_faces_and_near_misses_still_hit():
    c = _client({
        "sol ring": {"name": "Sol Ring"},
        "delver of secrets": {"name": "Delver of Secrets // Insectile Aberration"},
        "fire // ice": {"name": "Fire // Ice"},
        "atraxa praetors voice": {"name": "Atraxa, Praetors' Voice"},
    })
    for name in ("Sol Ring", "Delver of Secrets", "Fire // Ice", "Atraxa Praetors Voice"):
        assert c._cache_get(name) is not None, name
