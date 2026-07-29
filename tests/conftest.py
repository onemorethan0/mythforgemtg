"""Make `pytest tests/` enforce the smoke tests' checks.

test_smoke.py is dual-entry: `python tests/test_smoke.py` runs main(), which
inspects the module-global `_fails` list and exits 1. The individual `test_*`
functions, though, only APPEND to that list — they never assert. So under pytest
every test passed unconditionally: the suite reported "39 passed" with a genuinely
broken helper underneath (found 2026-07-27 by deliberately reverting a path fix —
the standalone runner caught it, pytest did not).

This hook snapshots `_fails` around each test and raises whatever that test
appended, so both entry points enforce the same checks and the 39 test bodies stay
untouched. It hooks the CALL phase (not a teardown fixture) so a violation is
reported as a real test FAILURE rather than a teardown error.
"""
import os
import sys

import pytest

# The MythGauntlet engine lives at src/mythgauntlet (merged 2026-07-29) and keeps its
# src/ layout so its PROJECT_ROOT (parents[2]) still resolves to this repo root.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import test_smoke


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    # Only the smoke tests report through the _fails list; engine tests (tests/engine)
    # use plain asserts and must not be wrapped.
    if item.module.__name__ != "test_smoke":
        yield
        return
    before = len(test_smoke._fails)
    outcome = yield
    if outcome.exception is None:
        new = test_smoke._fails[before:]
        if new:
            outcome.force_exception(
                AssertionError("check failures:\n  - " + "\n  - ".join(new))
            )
