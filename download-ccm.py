#!/usr/bin/env python3
"""
Myth Forge - Deck-Strength Data (CCM) Downloader

Fetches a pre-compiled MythGauntlet card-semantics snapshot into ccm/, so the strength
engine runs at rung-2 fidelity (executable card semantics) instead of falling back to
rung-1 Oracle-text heuristics for every card. Entirely optional - the engine, the UI and
the bracket estimate all work without this. See docs/ENGINE_DATA.md.

A snapshot is a zip containing compiled/*.json, ledger.json, and a _manifest.json
describing its vintage (snapshot date, card count, and what fraction is compiled under
the CURRENT compiler prompt vs. an older one - the number that actually matters for
accuracy, since older-prompt cards carry known, since-fixed error classes).
"""

import io
import json
import os
import sys
import zipfile
from pathlib import Path

try:
    import requests
except ImportError:
    print("requests is required: pip install -r requirements.txt")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).parent
CCM_DIR = PROJECT_ROOT / "ccm"

# Overridable so a future snapshot (or a mirror) doesn't need a code change.
DEFAULT_URL = os.environ.get(
    "MYTHFORGE_CCM_URL",
    "https://github.com/onemorethan0/mythforgemtg/releases/download/ccm-data/mythgauntlet-ccm-store.zip",
)


class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    END = "\033[0m"


def _ok(msg: str) -> None:
    print(f"{Colors.GREEN}[OK]{Colors.END} {msg}")


def _warn(msg: str) -> None:
    print(f"{Colors.YELLOW}[!]{Colors.END} {msg}")


def _err(msg: str) -> None:
    print(f"{Colors.RED}[X]{Colors.END} {msg}")


def _info(msg: str) -> None:
    print(f"{Colors.CYAN}[i]{Colors.END} {msg}")


def _compiled_count() -> int:
    compiled = CCM_DIR / "compiled"
    return len(list(compiled.glob("*.json"))) if compiled.is_dir() else 0


def download(url: str) -> bytes:
    _info(f"Downloading {url}")
    with requests.get(url, stream=True, timeout=30) as r:
        if r.status_code == 404:
            raise RuntimeError(
                "Nothing found at that URL (404). Either no snapshot has been published "
                "yet, or MYTHFORGE_CCM_URL points somewhere wrong. This is optional - the "
                "app runs fine without it. See docs/ENGINE_DATA.md."
            )
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        buf = io.BytesIO()
        downloaded = 0
        for chunk in r.iter_content(chunk_size=1 << 20):
            buf.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = downloaded * 100 // total
                print(f"\r  {downloaded / 1e6:,.0f} MB / {total / 1e6:,.0f} MB ({pct}%)",
                      end="", flush=True)
            else:
                print(f"\r  {downloaded / 1e6:,.0f} MB", end="", flush=True)
        print()
        return buf.getvalue()


def extract(data: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        if not any(n.startswith("compiled/") for n in names):
            raise RuntimeError(
                "That archive doesn't look like a CCM snapshot (no compiled/ entries) - "
                "refusing to extract it over ccm/."
            )
        CCM_DIR.mkdir(exist_ok=True)
        zf.extractall(CCM_DIR)

    manifest_path = CCM_DIR / "_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    print(f"{Colors.BOLD}Myth Forge - Deck-Strength Data (CCM) Downloader{Colors.END}\n")
    _info("Optional. Without this, brackets and Power Profile still compute from")
    _info("Oracle-text heuristics - see docs/ENGINE_DATA.md.\n")

    existing = _compiled_count()
    if existing:
        _warn(f"ccm/compiled/ already has {existing} files.")
        if input("Overwrite with the downloaded snapshot? (y/n): ").strip().lower() != "y":
            print("Cancelled.")
            return 0

    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL

    try:
        data = download(url)
        manifest = extract(data)
    except Exception as e:
        _err(str(e))
        return 1

    _ok(f"Installed {_compiled_count()} compiled card semantics into ccm/compiled/")

    if manifest:
        print()
        _info("Snapshot details:")
        for key in (
            "snapshot_date", "status", "license", "compiled", "quarantined",
            "prompt_version_current", "current_prompt_count", "pct_current_prompt",
        ):
            if key in manifest:
                print(f"    {key}: {manifest[key]}")
        if (CCM_DIR / "LICENSE-CCM-DATA.txt").exists():
            _info("Full license terms: ccm/LICENSE-CCM-DATA.txt")
        pct = manifest.get("pct_current_prompt")
        if isinstance(pct, (int, float)) and pct < 100:
            print()
            _warn(
                f"Only {pct}% of this snapshot is compiled under the current prompt "
                "version - the rest predates whatever bug classes that version fixed. "
                "Still strictly better than rung-1 fallback, just not finished."
            )
    else:
        _warn("No manifest found inside the archive - can't report its vintage or coverage.")

    print()
    _info("Restart the strength API to pick it up: manage.bat -> option 5, then option 1.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(1)
