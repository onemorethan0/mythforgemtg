"""SemanticsStore: rung lookup and deck coverage (offline, tmp dirs)."""

import json

from mythgauntlet.semantics.store import SemanticsStore, load_store


def _write_envelope(directory, name, ccm):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name.lower().replace(' ', '-')}.json"
    path.write_text(
        json.dumps({"card": {"name": name}, "ccm": ccm}), encoding="utf-8"
    )


def test_rung_priority_authored_over_compiled(tmp_path):
    authored = tmp_path / "authored"
    compiled = tmp_path / "compiled"
    _write_envelope(compiled, "Sol Ring", {"rung": 2})
    _write_envelope(authored, "Sol Ring", {"rung": 3})
    _write_envelope(compiled, "Arcane Signet", {"rung": 2})
    store = SemanticsStore(authored=authored, compiled=compiled)
    assert store.lookup("sol ring").rung == 3  # authored wins, case-insensitive
    assert store.lookup("Arcane Signet").rung == 2
    assert store.lookup("Unknown Card").rung == 1
    assert store.lookup("Unknown Card").ccm is None


def test_load_store_caches_and_invalidates(tmp_path, monkeypatch):
    """The pickle cache is reused when the CCM dirs are unchanged, rebuilt when they change."""
    monkeypatch.setenv("MYTHGAUNTLET_DATA", str(tmp_path / "data"))  # cache goes here
    authored = tmp_path / "authored"
    compiled = tmp_path / "compiled"
    _write_envelope(compiled, "Sol Ring", {"rung": 2})

    a = load_store(authored=authored, compiled=compiled)
    assert a.lookup("Sol Ring").rung == 2
    cache = tmp_path / "data" / "semantics_store.pkl"
    assert cache.exists()

    # a card added -> the dir signature changes -> the cache is invalidated on next load
    _write_envelope(compiled, "Mana Vault", {"rung": 2})
    b = load_store(authored=authored, compiled=compiled)
    assert b.lookup("Mana Vault").rung == 2
    assert b.lookup("Sol Ring").rung == 2


def test_load_store_survives_corrupt_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("MYTHGAUNTLET_DATA", str(tmp_path / "data"))
    compiled = tmp_path / "compiled"
    _write_envelope(compiled, "Sol Ring", {"rung": 2})
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "semantics_store.pkl").write_bytes(b"not a pickle")
    store = load_store(authored=tmp_path / "none", compiled=compiled)
    assert store.lookup("Sol Ring").rung == 2  # rebuilt from source, no crash


def test_malformed_artifact_skipped_not_fatal(tmp_path):
    compiled = tmp_path / "compiled"
    _write_envelope(compiled, "Good Card", {"rung": 2})
    (compiled / "broken.json").write_text("{not json", encoding="utf-8")
    (compiled / "no-card-key.json").write_text('{"ccm": {}}', encoding="utf-8")
    store = SemanticsStore(authored=tmp_path / "none", compiled=compiled)
    assert store.lookup("Good Card").rung == 2
    assert len(store.skipped) == 2
    assert all("malformed CCM envelope" in s for s in store.skipped)


def test_rung_precedence_is_order_independent(tmp_path):
    """Authored (rung 3) must win over compiled (rung 2) no matter which loads first."""
    authored = tmp_path / "authored"
    compiled = tmp_path / "compiled"
    _write_envelope(authored, "Sol Ring", {"rung": 3, "marker": "authored"})
    _write_envelope(compiled, "Sol Ring", {"rung": 2, "marker": "compiled"})
    forward = SemanticsStore(authored=authored, compiled=compiled)
    assert forward.lookup("Sol Ring").rung == 3
    assert forward.lookup("Sol Ring").ccm["marker"] == "authored"


def test_coverage_counts_copies(tmp_path, make_card, forest):
    compiled = tmp_path / "compiled"
    _write_envelope(compiled, "Grizzly Bears", {"rung": 2})
    store = SemanticsStore(authored=tmp_path / "none", compiled=compiled)
    bear = make_card("Grizzly Bears", mana_cost="{1}{G}")
    unknown = make_card("Mystery Card", mana_cost="{1}")
    report = store.coverage([(bear, 4), (unknown, 2), (forest, 10)])
    assert report.total == 16
    assert report.rung2 == 4
    assert report.rung1 == 12
    assert 0.24 < report.executable_share < 0.26
