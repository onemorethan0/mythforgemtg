"""Parallel + cached job orchestrator (ratings/orchestrator.py). Offline/synthetic.

Pins the two guarantees: parallel results are identical to serial (determinism across a process
pool), and the disk cache makes a re-run a lookup while an engine_tag change invalidates it.
"""

from __future__ import annotations

from mythgauntlet.ratings.orchestrator import Job, JobCache, run_jobs
from mythgauntlet.sim.tier2 import DuelConfig, prepare_deck


def _decks(make_card):
    forest = make_card("Forest", type_line="Basic Land - Forest",
                       produced_mana=("G",), color_identity=("G",))

    def creature(name, cost, power):
        c = make_card(name, mana_cost=cost, type_line="Creature - Beast", color_identity=("G",))
        c.power, c.toughness = str(power), str(power)
        return c

    aggro = prepare_deck("aggro", [(forest, 24), (creature("Bear", "{1}{G}", 3), 36)], None, None)
    mid = prepare_deck("mid", [(forest, 26), (creature("Ox", "{2}{G}", 4), 34)], None, None)
    slow = prepare_deck("slow", [(forest, 60)], None, None)
    return {"aggro": aggro, "mid": mid, "slow": slow}


def _jobs():
    def cfg(seed):
        return DuelConfig(games=12, seed=seed, max_turns=20)
    return [
        Job("aggro", "slow", cfg(1)),
        Job("aggro", "mid", cfg(2)),
        Job("mid", "slow", cfg(3)),
        Job("mid", "aggro", cfg(4)),
    ]


def test_parallel_matches_serial(make_card):
    prepared, jobs = _decks(make_card), _jobs()
    serial = run_jobs(prepared, jobs, workers=1)
    parallel = run_jobs(prepared, jobs, workers=2)
    assert [(r.a, r.b, r.wins_a, r.wins_b, r.draws) for r in serial] == \
           [(r.a, r.b, r.wins_a, r.wins_b, r.draws) for r in parallel]
    # results are returned in input order, not completion order
    assert [(r.a, r.b) for r in parallel] == [(j.a, j.b) for j in jobs]


def test_cache_hits_and_invalidation(make_card, tmp_path):
    prepared, jobs = _decks(make_card), _jobs()
    path = tmp_path / "cache.json"

    seen: list[int] = []
    cache = JobCache(path, engine_tag="v1")
    first = run_jobs(prepared, jobs, workers=1, cache=cache,
                     on_done=lambda d, t: seen.append(d))
    assert path.exists()

    # second run, same tag -> every job is a cache hit (on_done fires once with all done)
    hits: list[int] = []
    cache2 = JobCache(path, engine_tag="v1")
    second = run_jobs(prepared, jobs, workers=1, cache=cache2,
                      on_done=lambda d, t: hits.append(d))
    assert [(r.wins_a, r.wins_b, r.draws) for r in second] == \
           [(r.wins_a, r.wins_b, r.draws) for r in first]
    assert hits == [len(jobs)]  # all pre-satisfied from cache, single progress tick

    # a different engine_tag must NOT reuse the stale results
    cache3 = JobCache(path, engine_tag="v2")
    assert all(cache3.get(j) is None for j in jobs)


def test_cache_invalidates_on_deck_content_change_under_the_same_name(make_card, tmp_path):
    """A corpus deck edited in place (same NAME, different cards) must not silently reuse a
    cached result computed against the OLD decklist -- the cache key has to be sensitive to
    deck CONTENT, not just the name used to look it up in `prepared`."""
    forest = make_card("Forest", type_line="Basic Land - Forest",
                       produced_mana=("G",), color_identity=("G",))

    def creature(name, cost, power):
        c = make_card(name, mana_cost=cost, type_line="Creature - Beast", color_identity=("G",))
        c.power, c.toughness = str(power), str(power)
        return c

    slow = prepare_deck("slow", [(forest, 60)], None, None)
    original = {
        "variant": prepare_deck("variant", [(forest, 24), (creature("Bear", "{1}{G}", 3), 36)],
                                None, None),
        "slow": slow,
    }
    # Same deck NAME ("variant"), very different contents -- a huge aggro creature instead
    # of a small one, which should swing the duel outcome against the unchanging "slow" deck.
    edited = {
        "variant": prepare_deck("variant", [(forest, 24), (creature("Titan", "{1}{G}", 99), 36)],
                                None, None),
        "slow": slow,
    }
    jobs = [Job("variant", "slow", DuelConfig(games=12, seed=1, max_turns=20))]
    path = tmp_path / "cache.json"

    cache = JobCache(path, engine_tag="v1")
    run_jobs(original, jobs, workers=1, cache=cache)
    # The stale key (bare deck names) WOULD still be a hit here under the old scheme --
    # content hashing must force a fresh computation instead.
    assert cache.get(jobs[0], edited) is None


def test_empty_jobs_is_noop(make_card):
    assert run_jobs(_decks(make_card), [], workers=2) == []


def test_gauntlet_parser_accepts_jobs_and_cache():
    from mythgauntlet.cli import build_parser

    args = build_parser().parse_args(["gauntlet", "--jobs", "8", "--cache", "--agent", "mcts:100"])
    assert args.jobs == 8 and args.cache is True and args.agent == "mcts:100"


def test_deck_hash_is_deterministic_and_sensitive_to_recompiled_semantics(make_card):
    """A card re-compiled in place (same name, same count of semantics) must change the deck's
    cache identity; rebuilding the same deck must not."""
    import dataclasses

    from mythgauntlet.ratings.orchestrator import _deck_content_hash

    forest = make_card("Forest", type_line="Basic Land - Forest",
                       produced_mana=("G",), color_identity=("G",))
    bear = make_card("Bear", mana_cost="{1}{G}", type_line="Creature - Beast",
                     color_identity=("G",))
    bear.power, bear.toughness = "2", "2"
    build = lambda: prepare_deck("d", [(forest, 24), (bear, 36)], None, None)  # noqa: E731
    assert _deck_content_hash(build()) == _deck_content_hash(build())

    deck = build()
    idx = next(i for i, gc in enumerate(deck.cards) if gc.name == "Bear")
    deck.cards[idx] = dataclasses.replace(
        deck.cards[idx], resolve_abilities=({"kind": "spell_effect", "effects": []},))
    assert _deck_content_hash(deck) != _deck_content_hash(build())


def test_cache_flush_survives_a_locked_destination(tmp_path, monkeypatch):
    """Windows `replace` raises PermissionError while a scanner/reader holds the file. That
    used to escape run_jobs' pool loop and stall the whole gauntlet for hours (2026-10-07/08)."""
    from pathlib import Path

    from mythgauntlet.ratings import orchestrator

    cache = JobCache(tmp_path / "c.json")
    cache._data["k"] = [1, 2, 3]
    monkeypatch.setattr(orchestrator.time, "sleep", lambda s: None)
    real_replace, calls = Path.replace, []

    def flaky(self, target):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(5, "Access is denied")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky)
    cache.flush()  # two failures then success: must not raise
    assert JobCache(tmp_path / "c.json")._data == {"k": [1, 2, 3]}

    monkeypatch.setattr(Path, "replace", lambda self, target: (_ for _ in ()).throw(
        PermissionError(5, "Access is denied")))
    cache.flush()  # permanently locked: still must not raise


def test_a_failing_pool_loop_does_not_wait_out_the_queue(make_card, tmp_path, monkeypatch):
    """An error in the collection loop must cancel queued matchups, not block on them."""
    import pytest

    prepared, jobs = _decks(make_card), _jobs()
    cache = JobCache(tmp_path / "c.json")

    def boom():
        raise RuntimeError("collector blew up")

    monkeypatch.setattr(cache, "flush", boom)
    with pytest.raises(RuntimeError, match="collector blew up"):
        run_jobs(prepared, jobs, workers=2, cache=cache)
