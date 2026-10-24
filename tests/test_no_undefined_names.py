"""No module in the app or engine references a name that does not exist (pyflakes F821).

Found 2026-10-23: a July rename (`_ART_DIR` -> `ART_DIR`, 6899f6a) missed two call sites in
server.py, so "regenerate this card's art" died with a NameError on its first card for three
months and animate's art-crop fallback with it. Nothing failed at import, no test reached the
line, and CI stayed green. This check reads the source, so it cannot be dodged by an untested
code path. Skips (not fails) where ruff is not installed; CI installs it via requirements-dev.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _ruff() -> list[str] | None:
    if shutil.which("ruff"):
        return ["ruff"]
    probe = subprocess.run([sys.executable, "-m", "ruff", "--version"], capture_output=True)
    return [sys.executable, "-m", "ruff"] if probe.returncode == 0 else None


def test_no_undefined_names():
    ruff = _ruff()
    if ruff is None:
        pytest.skip("ruff not installed")
    targets = [str(p) for p in ROOT.glob("*.py")] + [str(ROOT / d) for d in ("api", "src", "utilities")]
    result = subprocess.run(
        [*ruff, "check", "--select", "F821", "--output-format", "concise", "--no-cache", *targets],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, "undefined names:\n" + result.stdout
