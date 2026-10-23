"""A short hash of the code that turns a decklist into scores.

Callers that CACHE a measurement (Forge stores `last_measure` in deck.json) record this
beside it and treat a mismatch as stale. `engine_version` cannot do that job: it stayed
0.2.0 through every axis re-model, so a Sep 4 Resilience 88 was shown as current beside a
fresh 41 for the same list (found 2026-10-23).

Only the packages that feed a score are hashed; the mentor, CLI and server do not change a
number. The compiled CCM store is deliberately NOT included: it is recompiled nightly, and
folding it in would mark every cached measurement stale every morning.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

SCORING_PACKAGES = ("agents", "data", "model", "ratings", "semantics", "sim")


def compute(package_dir: Path) -> str:
    h = hashlib.sha1()
    for sub in SCORING_PACKAGES:
        root = package_dir / sub
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            h.update(path.relative_to(package_dir).as_posix().encode())
            h.update(b"\0")
            h.update(path.read_bytes())
    return h.hexdigest()[:12]


@lru_cache(maxsize=1)
def model_fingerprint() -> str:
    return compute(Path(__file__).resolve().parent)
