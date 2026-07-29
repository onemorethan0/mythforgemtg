"""Semantics store: which rung does each card resolve at, and what does it say?

Loads the committed CCM artifacts (ccm/authored/ = rung 3, ccm/compiled/ = rung 2) into
one lookup. Every deck report cites the blended coverage this store computes
(invariant #3: honest uncertainty).
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path

from mythgauntlet.config import data_dir
from mythgauntlet.model.card import Card, normalize_name
from mythgauntlet.semantics import compiler

_CACHE_VERSION = 1  # bump when CardSemantics/store internals change


@dataclass(frozen=True)
class CardSemantics:
    rung: int  # 3 authored, 2 compiled, 1 effect-vector fallback
    ccm: dict | None  # present for rung >= 2


@dataclass(frozen=True)
class CoverageReport:
    total: int  # card copies
    rung3: int
    rung2: int
    rung1: int

    @property
    def executable_share(self) -> float:
        """Fraction of card copies at rung >= 2 (structured, executable semantics)."""
        return (self.rung3 + self.rung2) / self.total if self.total else 0.0


class SemanticsStore:
    def __init__(
        self, authored: Path | None = None, compiled: Path | None = None
    ) -> None:
        self._by_name: dict[str, CardSemantics] = {}
        self.skipped: list[str] = []  # malformed artifact files (tolerated, reportable)
        for path, rung in ((compiled or compiler.compiled_dir(), 2),
                           (authored or compiler.authored_dir(), 3)):
            if not path.is_dir():
                continue
            for file in sorted(path.glob("*.json")):
                try:
                    envelope = compiler.read_envelope(file)
                except ValueError as exc:
                    self.skipped.append(str(exc))
                    continue
                name = normalize_name(envelope["card"]["name"])
                existing = self._by_name.get(name)
                # explicit precedence: the higher rung wins regardless of load order
                if existing is None or rung > existing.rung:
                    self._by_name[name] = CardSemantics(rung=rung, ccm=envelope["ccm"])

    def __len__(self) -> int:
        return len(self._by_name)

    def lookup(self, card_name: str) -> CardSemantics:
        return self._by_name.get(
            normalize_name(card_name), CardSemantics(rung=1, ccm=None)
        )

    def coverage(
        self, cards: list[tuple[Card, int]], commanders: list[Card] | None = None
    ) -> CoverageReport:
        counts = {3: 0, 2: 0, 1: 0}
        total = 0
        entries = list(cards) + [(c, 1) for c in commanders or []]
        for card, count in entries:
            counts[self.lookup(card.name).rung] += count
            total += count
        return CoverageReport(total=total, rung3=counts[3], rung2=counts[2], rung1=counts[1])


def _dir_signature(path: Path) -> tuple[int, float]:
    """(file count, newest mtime) — a cheap fingerprint that stat()s instead of parsing."""
    if not path.is_dir():
        return (0, 0.0)
    files = list(path.glob("*.json"))
    if not files:
        return (0, 0.0)
    return (len(files), max(f.stat().st_mtime for f in files))


_process_store: SemanticsStore | None = None  # in-process reuse for the default paths


def load_store(
    authored: Path | None = None, compiled: Path | None = None, use_cache: bool = True
) -> SemanticsStore:
    """Load the SemanticsStore, reusing a pickle cache when the CCM dirs are unchanged.

    Parsing ~9k committed CCM JSONs cold is ~35s; unpickling the cache is sub-second, and
    a process-level singleton avoids even that when a single command builds the store more
    than once. Explicit authored/compiled paths (tests) bypass all caching.
    """
    global _process_store
    default = authored is None and compiled is None
    if default and _process_store is not None:
        return _process_store

    a = authored or compiler.authored_dir()
    c = compiled or compiler.compiled_dir()
    # sig includes the paths, so different path sets never read each other's cache entry.
    sig = (_CACHE_VERSION, str(a), str(c), _dir_signature(c), _dir_signature(a))
    cache = data_dir() / "semantics_store.pkl"

    store: SemanticsStore | None = None
    if use_cache and cache.exists():
        try:
            with open(cache, "rb") as fh:
                payload = pickle.load(fh)
            if payload.get("sig") == sig:
                store = SemanticsStore.__new__(SemanticsStore)
                store._by_name = payload["by_name"]
                store.skipped = payload["skipped"]
        except (pickle.PickleError, OSError, KeyError, EOFError, AttributeError):
            store = None  # corrupt/incompatible cache -> rebuild

    if store is None:
        store = SemanticsStore(authored=a, compiled=c)
        if use_cache:
            try:
                tmp = cache.with_suffix(".pkl.part")
                with open(tmp, "wb") as fh:
                    pickle.dump(
                        {"sig": sig, "by_name": store._by_name, "skipped": store.skipped}, fh
                    )
                tmp.replace(cache)  # atomic
            except OSError:
                pass  # cache is an optimization; never fail the load over it

    if default:
        _process_store = store
    return store
