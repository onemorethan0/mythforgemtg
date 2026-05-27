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
    status = f"{Colors.GREEN}✓{Colors.END}" if condition else f"{Colors.RED}✗{Colors.END}"
    print(f"{status} {name}" + (f" — {details}" if details else ""))
    return condition


def check_python():
    print_header("Python Environment")

    try:
        version = sys.version_info
        version_str = f"{version.major}.{version.minor}.{version.micro}"
        check_item("Python version", version.major >= 3 and version.minor >= 8, version_str)

        # Check for key packages
        packages = ['flask', 'requests', 'pillow', 'pydantic']
        all_found = True

        for pkg in packages:
            try:
                __import__(pkg)
                check_item(f"  {pkg}", True)
            except ImportError:
                check_item(f"  {pkg}", False, "run: pip install -r requirements.txt")
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
        result = subprocess.run(['npm', '--version'], capture_output=True, text=True)
        npm_ok = result.returncode == 0
        npm_version = result.stdout.strip() if npm_ok else "not found"
        check_item("npm", npm_ok, npm_version)

        # Check frontend dist
        dist_path = project_root / 'frontend' / 'dist'
        dist_ok = dist_path.exists() and list(dist_path.glob('*.js'))
        check_item("Frontend build (dist/)", dist_ok, "run: make frontend-build" if not dist_ok else "ready")

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

    components = {
        'ollama': 'Ollama (card theming)',
        'comfy': 'ComfyUI (image generation)',
    }

    for cmd, name in components.items():
        try:
            result = subprocess.run(
                ['where' if sys.platform == 'win32' else 'which', cmd],
                capture_output=True
            )
            found = result.returncode == 0
            check_item(name, found, "found" if found else "not found — see INSTALL.md")
        except:
            check_item(name, False)


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


def main():
    print(f"\n{Colors.BOLD}{Colors.CYAN}")
    print("╔═══════════════════════════════════════════════════╗")
    print("║       MYTH FORGE - Installation Verification       ║")
    print("╚═══════════════════════════════════════════════════╝")
    print(Colors.END)

    results = {
        'Python': check_python(),
        'Node.js': check_node(),
        'Directories': check_directories(),
        'API': check_api(),
    }

    check_optional()

    # Summary
    print_header("Summary")

    all_ok = all(results.values())

    for component, status in results.items():
        icon = f"{Colors.GREEN}✓{Colors.END}" if status else f"{Colors.RED}✗{Colors.END}"
        print(f"{icon} {component}")

    print()

    if all_ok:
        print(f"{Colors.GREEN}{Colors.BOLD}")
        print("✓ All essential components are installed!")
        print(Colors.END)
        print("\nYou can now start the server:")
        print(f"  {Colors.BOLD}python server.py{Colors.END}")
        print(f"\nThen open: {Colors.BOLD}http://localhost:8000{Colors.END}\n")
        return 0
    else:
        print(f"{Colors.RED}{Colors.BOLD}")
        print("✗ Some components are missing")
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
