"""`model_fingerprint` changes when scoring code changes, and only then.

A measurement cached in deck.json was shown as current long after the engine re-modelled
the axes it reports (a Sep 4 Resilience 88 beside today's 41 for the same list), because
nothing recorded WHICH engine produced it - `engine_version` has been 0.2.0 throughout.
"""
from mythgauntlet import fingerprint


def test_stable_within_a_process():
    fingerprint.model_fingerprint.cache_clear()
    a = fingerprint.model_fingerprint()
    assert a == fingerprint.model_fingerprint()
    assert len(a) == 12 and int(a, 16) >= 0


def test_scoring_code_changes_it_and_unrelated_code_does_not(tmp_path):
    pkg = tmp_path / "pkg"
    for sub in ("sim", "mentor"):
        (pkg / sub).mkdir(parents=True)
    (pkg / "sim" / "tier0.py").write_text("X = 1\n")
    (pkg / "mentor" / "chat.py").write_text("Y = 1\n")
    base = fingerprint.compute(pkg)
    (pkg / "mentor" / "chat.py").write_text("Y = 2\n")
    assert fingerprint.compute(pkg) == base          # the mentor does not score decks
    (pkg / "sim" / "tier0.py").write_text("X = 2\n")
    assert fingerprint.compute(pkg) != base
