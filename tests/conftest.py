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
import pytest

import test_smoke


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    before = len(test_smoke._fails)
    outcome = yield
    if outcome.exception is None:
        new = test_smoke._fails[before:]
        if new:
            outcome.force_exception(
                AssertionError("check failures:\n  - " + "\n  - ".join(new))
            )
