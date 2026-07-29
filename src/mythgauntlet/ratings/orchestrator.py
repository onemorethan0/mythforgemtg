"""Parallel + cached Tier-2 job orchestrator (docs/SIMULATION.md "Orchestration").

A gauntlet matchup is a PURE function of (decks, DuelConfig) — invariant #1 — so matchups run
independently across a process pool with no shared state, and identical inputs are a cache lookup
instead of a re-run. This is what makes an ISMCTS-agent gauntlet (per-decision search is slow)
feasible overnight: N cores of speedup + resume-for-free across an interrupted run.

Determinism: parallel results are identical to serial, matchup-for-matchup — each duel carries its
own seed and shares no state, so the pool only reorders WHEN work runs, never WHAT it computes.
`run_jobs` returns results in the input order regardless of worker count. There is a test that
pins parallel == serial.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from mythgauntlet.ratings.gauntlet import PairResult
from mythgauntlet.sim.tier2 import DuelConfig, PreparedDeck, duel_prepared


@dataclass(frozen=True)
class Job:
    a: str  # deck name -> key into the `prepared` mapping
    b: str
    cfg: DuelConfig


def _duel(prepared: dict[str, PreparedDeck], job: Job) -> PairResult:
    outcome = duel_prepared(prepared[job.a], prepared[job.b], job.cfg)
    return PairResult(a=job.a, b=job.b, wins_a=outcome.wins_a, wins_b=outcome.wins_b,
                      draws=outcome.draws)


# --- worker (module-level so it pickles under Windows spawn) ------------------------------

_PREPARED: dict[str, PreparedDeck] = {}


def _init_worker(prepared: dict[str, PreparedDeck]) -> None:
    global _PREPARED
    _PREPARED = prepared


def _run_one(job: Job) -> PairResult:
    return _duel(_PREPARED, job)


# --- disk cache for resumability ---------------------------------------------------------


def _job_key(job: Job, engine_tag: str) -> str:
    c = job.cfg
    parts = (engine_tag, job.a, job.b, c.games, c.seed, c.max_turns, c.start_life,
             c.agent_a, c.agent_b, c.mcts_iterations, c.mcts_determinizations, c.rollout_depth)
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()


class JobCache:
    """Tiny disk cache: job hash -> [wins_a, wins_b, draws]. `engine_tag` (e.g. the executable-
    semantics count) is folded into the key, so recompiling the engine naturally invalidates
    stale results rather than silently reusing them. Flushed atomically after each miss."""

    def __init__(self, path: str | Path, engine_tag: str = "") -> None:
        self.path = Path(path)
        self.engine_tag = engine_tag
        self._data: dict[str, list[int]] = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._data = {}

    def get(self, job: Job) -> PairResult | None:
        row = self._data.get(_job_key(job, self.engine_tag))
        if row is None:
            return None
        return PairResult(a=job.a, b=job.b, wins_a=row[0], wins_b=row[1], draws=row[2])

    def put(self, job: Job, result: PairResult) -> None:
        self._data[_job_key(job, self.engine_tag)] = [
            result.wins_a, result.wins_b, result.draws
        ]

    def flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data), encoding="utf-8")
        tmp.replace(self.path)  # atomic


# --- runner ------------------------------------------------------------------------------


def default_workers() -> int:
    """Leave two cores for the OS + the parent (mirrors the workflow-tool cap)."""
    return max(1, (os.cpu_count() or 2) - 2)


def run_jobs(
    prepared: dict[str, PreparedDeck],
    jobs: list[Job],
    workers: int | None = None,
    cache: JobCache | None = None,
    on_done: Callable[[int, int], None] | None = None,
) -> list[PairResult]:
    """Run `jobs` against `prepared`, in parallel with optional caching. Returns PairResults in
    the SAME ORDER as `jobs`, deterministically regardless of `workers`.

    workers: process count (None => default_workers(); 1 => serial, no pool spun up).
    cache:   optional JobCache — hits skip computation; misses are flushed as they complete.
    on_done: optional progress callback(done, total).
    """
    total = len(jobs)
    results: list[PairResult | None] = [None] * total
    todo: list[tuple[int, Job]] = []
    for i, job in enumerate(jobs):
        hit = cache.get(job) if cache else None
        if hit is not None:
            results[i] = hit
        else:
            todo.append((i, job))

    done = total - len(todo)
    if on_done and done:
        on_done(done, total)
    if not todo:
        return results  # type: ignore[return-value]

    n = default_workers() if workers is None else max(1, workers)
    if n == 1 or len(todo) == 1:
        for i, job in todo:
            results[i] = _duel(prepared, job)
            if cache:
                cache.put(job, results[i])
                cache.flush()
            done += 1
            if on_done:
                on_done(done, total)
        return results  # type: ignore[return-value]

    with ProcessPoolExecutor(max_workers=n, initializer=_init_worker,
                             initargs=(prepared,)) as ex:
        futures = {ex.submit(_run_one, job): i for i, job in todo}
        for fut in as_completed(futures):
            i = futures[fut]
            results[i] = fut.result()
            if cache:
                cache.put(jobs[i], results[i])
                cache.flush()
            done += 1
            if on_done:
                on_done(done, total)
    return results  # type: ignore[return-value]
