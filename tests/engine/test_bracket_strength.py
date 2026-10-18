"""The strength-placement bracket path (ratings/strength_model.py + estimate_bracket).

Uses a tiny synthetic model (consistency alone moves the score) so the rules are tested,
not the fitted numbers: official gates are FLOORS, strength places the deck from there.
"""

import pytest

from mythgauntlet.ratings import strength_model
from mythgauntlet.ratings.bracket import estimate_bracket


@pytest.fixture
def toy_model(monkeypatch):
    feats = strength_model.FEATURES
    monkeypatch.setattr(strength_model, "MEANS", {f: 0.0 for f in feats})
    monkeypatch.setattr(strength_model, "SCALES", {f: 1.0 for f in feats})
    monkeypatch.setattr(strength_model, "WEIGHTS",
                        {f: (0.1 if f == "consistency" else 0.0) for f in feats})
    monkeypatch.setattr(strength_model, "INTERCEPT", 0.0)
    monkeypatch.setattr(strength_model, "CUTS", (1.5, 2.5, 3.5, 4.5))


def _feats(score):
    """Features whose toy score is `score` (consistency = 10 x score)."""
    out = {f: 0.0 for f in strength_model.FEATURES}
    out["consistency"] = score * 10.0
    return out


def _gc_card(make_card, name):
    c = make_card(name, mana_cost="{1}{U}", type_line="Artifact")
    c.game_changer = True
    return c


def test_a_strong_zero_game_changer_deck_can_read_upgraded(toy_model, forest, bear):
    """The rules make Game Changers an allowance, never a requirement: 0 GC is not 'Core'."""
    est = estimate_bracket([(forest, 38), (bear, 61)], [], strength_features=_feats(3.0))
    assert est.bracket == 3 and est.floor == 1
    assert est.strength_score == pytest.approx(3.0)
    assert any("measured speed + strength place it at Bracket 3" in r for r in est.reasons)
    assert not any("Brackets 1-2" in r for r in est.reasons)   # the old cap wording is gone


def test_game_changers_set_a_floor_not_a_placement(toy_model, make_card, forest, bear):
    gcs = [(_gc_card(make_card, f"GC {i}"), 1) for i in range(2)]
    est = estimate_bracket([(forest, 38), (bear, 59), *gcs], [], strength_features=_feats(1.0))
    assert est.floor == 3 and est.bracket == 3
    assert any("require at least Bracket 3" in r for r in est.reasons)


def test_four_game_changers_floor_at_optimized(toy_model, make_card, forest, bear):
    gcs = [(_gc_card(make_card, f"GC {i}"), 1) for i in range(4)]
    est = estimate_bracket([(forest, 38), (bear, 57), *gcs], [], strength_features=_feats(2.0))
    assert est.bracket == 4


def test_weak_deck_with_no_gates_reads_exhibition(toy_model, forest, bear):
    est = estimate_bracket([(forest, 38), (bear, 61)], [], strength_features=_feats(1.2))
    assert est.bracket == 1


def test_plays_up_means_just_under_the_next_cut(toy_model, forest, bear):
    near = estimate_bracket([(forest, 38), (bear, 61)], [], strength_features=_feats(2.4))
    mid = estimate_bracket([(forest, 38), (bear, 61)], [], strength_features=_feats(2.0))
    assert near.bracket == 2 and near.plays_up is True
    assert mid.bracket == 2 and mid.plays_up is False
    assert near.confidence < mid.confidence     # a boundary deck is less certain


def test_floored_deck_never_reads_plays_up(toy_model, make_card, forest, bear):
    gcs = [(_gc_card(make_card, "GC 0"), 1)]
    est = estimate_bracket([(forest, 38), (bear, 60), *gcs], [], strength_features=_feats(1.4))
    assert est.bracket == 3 and est.plays_up is False


def test_cedh_combo_escalation_still_applies_at_bracket_4(toy_model, forest, bear):
    est = estimate_bracket([(forest, 38), (bear, 61)], [], strength_features=_feats(4.0),
                           two_card_combos=1, speed_kill_rate=0.3)
    assert est.bracket == 5


def test_unfitted_model_falls_back_to_the_gate_bands(monkeypatch, forest, bear):
    monkeypatch.setattr(strength_model, "WEIGHTS", {})
    est = estimate_bracket([(forest, 38), (bear, 61)], [], strength_features=_feats(3.0))
    assert est.bracket in (1, 2) and est.strength_score is None


def test_missing_resilience_scores_neutral(toy_model):
    feats = _feats(2.0)
    feats["resilience"] = None
    assert strength_model.strength_placement(feats).bracket == 2


def test_card_quality_counts_fast_mana_and_tutors(make_card, forest):
    rock = make_card("Mana Rock", mana_cost="{1}", type_line="Artifact",
                     oracle_text="{T}: Add {C}{C}.", produced_mana=("C",))
    tutor = make_card("Seek", mana_cost="{1}{B}", type_line="Sorcery",
                      oracle_text="Search your library for a card, put it into your hand, then shuffle.")
    q = strength_model.card_quality([(forest, 38), (rock, 2), (tutor, 1)], [])
    assert q["fast_mana"] == 2 and q["tutors"] == 1 and q["gc"] == 0


def test_baked_model_only_pushes_the_way_magic_does():
    """A faster/stronger signal must never LOWER the bracket (the reasons line prints it)."""
    if not strength_model.is_fitted():
        pytest.skip("model not baked")
    for f, w in strength_model.WEIGHTS.items():
        assert w * strength_model.SIGNS[f] >= 0, f
    assert list(strength_model.CUTS) == sorted(strength_model.CUTS)
    assert set(strength_model.WEIGHTS) == set(strength_model.FEATURES)
