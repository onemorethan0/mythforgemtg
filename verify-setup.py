#!/usr/bin/env python3
"""
Myth Forge Installation Verification
Checks that all components are properly installed and configured
"""

import sys
import subprocess
from pathlib import Path


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_header(text: str):
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}{Colors.END}\n")


def check_item(name: str, condition: bool, details: str = "") -> bool:
    status = f"{Colors.GREEN}[OK]{Colors.END}" if condition else f"{Colors.RED}[X]{Colors.END}"
    print(f"{status} {name}" + (f" - {details}" if details else ""))
    return condition


def check_python():
    print_header("Python Environment")

    try:
        version = sys.version_info
        version_str = f"{version.major}.{version.minor}.{version.micro}"
        # 3.12 is the floor: the bundled MythGauntlet engine requires it.
        check_item("Python version", (version.major, version.minor) >= (3, 12),
                   version_str + ("" if (version.major, version.minor) >= (3, 12)
                                  else " - need 3.12+ for the engine"))

        # (import name, pip name). These are IMPORT names on purpose — the old list
        # checked 'flask' (this app is FastAPI and never used Flask) and 'pillow'
        # (imports as PIL), so a perfectly good install reported as broken.
        packages = [
            ("fastapi", "fastapi"), ("uvicorn", "uvicorn"), ("pydantic", "pydantic"),
            ("requests", "requests"), ("PIL", "pillow"), ("pixie", "pixie-python"),
            ("rich", "rich"), ("json_repair", "json-repair"),
        ]
        all_found = True

        for mod, pip_name in packages:
            try:
                __import__(mod)
                check_item(f"  {pip_name}", True)
            except ImportError:
                check_item(f"  {pip_name}", False, "run: pip install -r requirements.txt")
                all_found = False

        return all_found
    except Exception as e:
        print(f"{Colors.RED}Error checking Python: {e}{Colors.END}")
        return False


def check_node():
    print_header("Node.js & Frontend")

    project_root = Path(__file__).parent

    try:
        # Check Node
        result = subprocess.run(['node', '--version'], capture_output=True, text=True)
        node_ok = result.returncode == 0
        node_version = result.stdout.strip() if node_ok else "not found"
        check_item("Node.js", node_ok, node_version)

        # Check npm
        # shell=True: npm is npm.cmd on Windows, so a bare exec raises WinError 2 and
        # blew up the whole Node check before it could report anything.
        result = subprocess.run("npm --version", capture_output=True, text=True, shell=True)
        npm_ok = result.returncode == 0
        npm_version = result.stdout.strip() if npm_ok else "not found"
        check_item("npm", npm_ok, npm_version)

        # Check frontend dist
        dist_path = project_root / 'frontend' / 'dist'
        # Vite emits hashed bundles to dist/assets/, not dist/ — the old glob looked in the
        # wrong directory and reported a fully built frontend as missing. (The suggestion is
        # now the npm command rather than `make frontend-build`, which is a real Makefile
        # target but assumes make is installed; on Windows it usually isn't.)
        dist_ok = dist_path.is_dir() and (
            list((dist_path / "assets").glob("*.js")) or list(dist_path.glob("*.js"))
        )
        check_item("Frontend build (dist/)", bool(dist_ok),
                   "ready" if dist_ok else "run: cd frontend && npm run build")

        # Check node_modules
        nm_path = project_root / 'frontend' / 'node_modules'
        nm_ok = nm_path.exists()
        check_item("Frontend dependencies (node_modules)", nm_ok, "run: cd frontend && npm install" if not nm_ok else "installed")

        return node_ok and npm_ok and dist_ok and nm_ok
    except Exception as e:
        print(f"{Colors.RED}Error checking Node.js: {e}{Colors.END}")
        return False


def check_directories():
    print_header("Data Directories")

    project_root = Path(__file__).parent

    dirs = [
        ('data/', project_root / 'data'),
        ('renders/', project_root / 'renders'),
        ('scryfall_cache/', project_root / 'scryfall_cache'),
    ]

    all_ok = True
    for name, path in dirs:
        ok = path.exists() and path.is_dir()
        check_item(name, ok, "exists" if ok else "missing")
        all_ok = all_ok and ok

    return all_ok


def check_optional():
    print_header("Optional Components (Not Required)")

    # The LLM is a SERVICE, not a binary on PATH. Checking `where ollama` reported
    # the default llama.cpp backend as a missing install and pointed at INSTALL.md
    # for a program the app no longer uses — ask the configured backend instead.
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from themer import LLM_BACKEND, installed_models, llm_endpoint_base
        label = 'llama.cpp via llama-swap' if LLM_BACKEND == 'llamacpp' else 'Ollama'
        models = installed_models()
        check_item(
            f'{label} (card theming)',
            bool(models),
            f'reachable at {llm_endpoint_base()} - {len(models)} model(s)' if models
            else f'not reachable at {llm_endpoint_base()} - see INSTALL.md',
        )
    except Exception as e:
        check_item('LLM backend (card theming)', False, f'could not check: {e}')

    # Same story for ComfyUI: it runs as the Desktop app, so `where comfy` reported
    # "not found" while it was serving happily on :8188. Ask the service.
    try:
        import requests
        r = requests.get('http://127.0.0.1:8188/system_stats', timeout=4)
        up = r.status_code == 200
    except Exception:
        up = False
    check_item('ComfyUI (image generation)', up,
               'running on :8188' if up else 'not running on :8188 - see INSTALL.md')


def check_api():
    print_header("API Server")

    project_root = Path(__file__).parent

    # Check server.py exists
    server_path = project_root / 'server.py'
    server_ok = server_path.exists()
    check_item("server.py", server_ok)

    # Check requirements
    req_path = project_root / 'requirements.txt'
    req_ok = req_path.exists()
    check_item("requirements.txt", req_ok)

    return server_ok and req_ok



def check_engine():
    """The MythGauntlet engine (src/mythgauntlet) that measures deck strength.

    Its compiled card semantics are withheld from this repo on purpose
    (docs/ENGINE_DATA.md), so an absent store is reported as INFO, not a failure -
    the engine falls back to Oracle-text heuristics and still produces brackets.
    """
    print_header("Deck Strength Engine (MythGauntlet)")
    project_root = Path(__file__).parent
    src = project_root / "src"
    ok = check_item("Engine source", (src / "mythgauntlet" / "__main__.py").exists(),
                    "src/mythgauntlet")
    if not ok:
        print("  Engine missing - bracket/strength will report as unavailable.")
        return False

    sys.path.insert(0, str(src))
    try:
        from mythgauntlet.semantics import compiler
        from mythgauntlet.semantics.store import SemanticsStore
    except ImportError as exc:
        check_item("Engine imports", False, str(exc))
        print("  Install deps:  python -m pip install -r requirements.txt")
        return False
    check_item("Engine imports", True, "rich + json-repair present")

    # Card data (Scryfall bulk) - needed to resolve decklists.
    try:
        from mythgauntlet.config import data_dir
        cards = data_dir() / "cards_slim.json"
    except Exception:
        cards = project_root / "data" / "cards_slim.json"
    if not check_item("Card data", cards.exists(), str(cards)):
        print("  Fetch it:  set PYTHONPATH=src && python -m mythgauntlet fetch-data")

    # Compiled semantics: absent is EXPECTED for a fresh clone.
    store = SemanticsStore()
    compiled = len(list(compiler.compiled_dir().glob("*.json")))         if compiler.compiled_dir().is_dir() else 0
    if compiled:
        check_item("Card semantics", True,
                   f"{len(store)} cards ({compiled} compiled) from {compiler.store_dir()}")
    else:
        print(f"{Colors.CYAN}[i]{Colors.END} Card semantics - "
              f"{len(store)} authored, 0 compiled (withheld; see docs/ENGINE_DATA.md)")
        print("  The engine runs on Oracle-text fallbacks; brackets still work, less precisely.")
        print(r'  Have a store?  setx MYTHGAUNTLET_STORE "D:\my-ccm-store"')

    # Is it serving?
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8020/health", timeout=2):
            check_item("Strength API (:8020)", True, "running")
    except Exception:
        print(f"{Colors.CYAN}[i]{Colors.END} Strength API (:8020) - not running "
              "(manage.bat starts it; the UI says 'unavailable' until then)")
    return True


def main():
    print(f"\n{Colors.BOLD}{Colors.CYAN}")
    print("+===================================================+")
    print("|       MYTH FORGE - Installation Verification       |")
    print("+===================================================+")
    print(Colors.END)

    results = {
        'Python': check_python(),
        'Node.js': check_node(),
        'Directories': check_directories(),
        'Engine': check_engine(),
        'API': check_api(),
    }

    check_optional()

    # Summary
    print_header("Summary")

    all_ok = all(results.values())

    for component, status in results.items():
        icon = f"{Colors.GREEN}[OK]{Colors.END}" if status else f"{Colors.RED}[X]{Colors.END}"
        print(f"{icon} {component}")

    print()

    if all_ok:
        print(f"{Colors.GREEN}{Colors.BOLD}")
        print("[OK] All essential components are installed!")
        print(Colors.END)
        # manage.bat, not server.py: server.py starts only the web server, while manage.bat
        # also brings up the LLM gateway (:8010) for theming and the engine (:8020) for
        # brackets. Recommending server.py left people with unthemed decks and no bracket.
        print("\nYou can now start Myth Forge:")
        print(f"  {Colors.BOLD}manage.bat{Colors.END}"
              "        (web server + LLM gateway + strength engine)")
        print(f"  {Colors.BOLD}python server.py{Colors.END}  (web server only)")
        print(f"\nThen open: {Colors.BOLD}http://localhost:8000{Colors.END}\n")
        return 0
    else:
        print(f"{Colors.RED}{Colors.BOLD}")
        print("[X] Some components are missing")
        print(Colors.END)
        print("\nRun the installer to fix issues:")

        if sys.platform == 'win32':
            print(f"  {Colors.BOLD}install.bat{Colors.END}")
        else:
            print(f"  {Colors.BOLD}python install.py{Colors.END}")

        print("\nOr see INSTALL.md for manual setup steps.\n")
        return 1


if __name__ == '__main__':
    sys.exit(main())
