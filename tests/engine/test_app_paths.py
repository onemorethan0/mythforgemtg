"""`app_paths` is what stops the app forking its own state.

Every path the app owns goes through `app_path()`. A bare relative `Path("cache")` resolves
against the process CWD, so launching the server from another directory silently created a
second `cache/`, a second `generated_art/`, and left `card_assets/` missing — about 220 MB of
orphaned duplicates before anyone noticed. `test_app_paths_absolute` in test_smoke.py guards
the module CONSTANTS; this covers `app_path()` itself.
"""

import os
import tempfile

import app_paths


def test_app_dir_is_absolute():
    assert app_paths.APP_DIR.is_absolute()


def test_app_path_joins_under_app_dir():
    p = app_paths.app_path("cache", "x.json")
    assert p.is_absolute()
    assert p.parent.parent == app_paths.APP_DIR
    assert p.name == "x.json"


def test_app_path_with_no_parts_is_app_dir():
    assert app_paths.app_path() == app_paths.APP_DIR


def test_app_path_is_cwd_independent():
    """The actual bug this module exists to prevent."""
    before = app_paths.app_path("cache")
    original_cwd = os.getcwd()
    try:
        # tempfile.gettempdir(), not os.getenv("TEMP"): TEMP is a Windows variable and is
        # normally unset on Linux, so os.chdir(None) would raise — and CI runs ubuntu.
        os.chdir(tempfile.gettempdir())
        assert os.getcwd() != original_cwd, "chdir did not move; the test would prove nothing"
        assert app_paths.app_path("cache") == before
    finally:
        os.chdir(original_cwd)
