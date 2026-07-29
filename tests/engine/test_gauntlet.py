"""Bradley-Terry fitting and matchup sampling (offline, synthetic results)."""

from mythgauntlet.ratings.gauntlet import PairResult, fit_bradley_terry, sample_pairs


def test_transitive_strength_ordering_recovered():
    results = [
        PairResult("alpha", "beta", wins_a=80, wins_b=20),
        PairResult("beta", "gamma", wins_a=80, wins_b=20),
        PairResult("alpha", "gamma", wins_a=90, wins_b=10),
    ]
    ratings = fit_bradley_terry(results)
    assert ratings["alpha"] > ratings["beta"] > ratings["gamma"]


def test_even_matchup_yields_equal_ratings():
    results = [PairResult("x", "y", wins_a=50, wins_b=50)]
    ratings = fit_bradley_terry(results)
    assert abs(ratings["x"] - ratings["y"]) < 1.0


def test_undefeated_deck_stays_finite():
    results = [PairResult("crusher", "victim", wins_a=60, wins_b=0)]
    ratings = fit_bradley_terry(results)
    assert all(abs(r) < 10_000 for r in ratings.values())
    assert ratings["crusher"] > ratings["victim"]


def test_draws_count_half():
    all_draws = fit_bradley_terry([PairResult("p", "q", wins_a=0, wins_b=0, draws=60)])
    assert abs(all_draws["p"] - all_draws["q"]) < 1.0


def test_fit_deterministic():
    results = [
        PairResult("a", "b", 40, 20),
        PairResult("b", "c", 35, 25),
        PairResult("a", "c", 50, 10),
    ]
    assert fit_bradley_terry(results) == fit_bradley_terry(results)


def test_sample_pairs_deterministic_and_covering():
    names = [f"deck{i}" for i in range(10)]
    pairs = sample_pairs(names, opponents_each=3, seed=5)
    assert pairs == sample_pairs(names, opponents_each=3, seed=5)
    assert all(a != b for a, b in pairs)
    assert all(a < b for a, b in pairs)  # canonical ordering, no duplicate mirrored pairs
    appearing = {n for pair in pairs for n in pair}
    assert appearing == set(names)  # every deck plays


def test_sample_pairs_small_pools():
    assert sample_pairs(["only"], opponents_each=3, seed=1) == []
    pairs = sample_pairs(["a", "b"], opponents_each=5, seed=1)
    assert pairs == [("a", "b")]
