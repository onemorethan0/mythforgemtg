"""Deterministic randomness.

Invariant #1 (docs/ARCHITECTURE.md): ALL randomness in simulation flows through SeededRng.
Never `import random` elsewhere in engine code. `spawn(i)` derives independent per-run
streams so batches parallelize without sharing state.
"""

from __future__ import annotations

import random


class SeededRng:
    def __init__(self, seed: int) -> None:
        self.seed = int(seed)
        self._rng = random.Random(self.seed)

    def spawn(self, index: int) -> SeededRng:
        """Deterministic child stream for run `index`."""
        return SeededRng((self.seed * 1_000_003 + index) & 0xFFFF_FFFF_FFFF)

    def shuffle(self, items: list) -> None:
        self._rng.shuffle(items)

    def random(self) -> float:
        return self._rng.random()

    def choice(self, items):
        return self._rng.choice(items)
