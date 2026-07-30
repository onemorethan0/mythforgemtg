#!/usr/bin/env python3
"""
Myth Forge Installer
Interactive setup for MTG Commander Deck Builder
"""

import os
import sys
import subprocess
import platform
import json
from pathlib import Path
from typing import Optional, List


class Colors:
    """ANSI color codes for terminal output"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'


class MythForgeInstaller:
    def __init__(self):
        self.project_root = Path(__file__).parent
        self.os_type = platform.system()
        self.checks_passed = {}
        self.optional_missing = []

    def print_header(self, text: str):
        """Print colored header"""
        print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 60}")
        print(f"  {text}")
        print(f"{'=' * 60}{Colors.END}\n")

    def print_step(self, number: int, text: str):
        """Print step indicator"""
        print(f"{Colors.CYAN}[{number}]{Colors.END} {text}")

    def print_success(self, text: str):
        """Print success message"""
        print(f"{Colors.GREEN}[OK] {text}{Colors.END}")

    def print_error(self, text: str):
        """Print error message"""
        print(f"{Colors.RED}[X] {text}{Colors.END}")

    def print_warning(self, text: str):
        """Print warning message"""
        print(f"{Colors.YELLOW}[!] {text}{Colors.END}")

    def print_info(self, text: str):
        """Print info message"""
        print(f"{Colors.CYAN}[i] {text}{Colors.END}")

    def ask_yes_no(self, question: str) -> bool:
        """Ask yes/no question"""
        while True:
            response = input(f"\n{question} (y/n): ").lower().strip()
            if response in ('y', 'yes'):
                return True
            elif response in ('n', 'no'):
                return False
            print("Please enter 'y' or 'n'")

    def run_command(self, cmd: List[str], description: str = "") -> bool:
        """Run a command and return success status.

        shell=True on Windows is load-bearing: npm is `npm.cmd`, so a bare exec raises
        WinError 2, which the FileNotFoundError branch below swallowed as a plain failure.
        The frontend install/build steps could never succeed on Windows.
        """
        try:
            if description:
                self.print_info(description)
            use_shell = self.os_type == 'Windows' and cmd and cmd[0] == 'npm'
            subprocess.run(
                subprocess.list2cmdline(cmd) if use_shell else cmd,
                capture_output=True, text=True, check=True, shell=use_shell,
            )
            return True
        except subprocess.CalledProcessError as e:
            if description:
                self.print_error(f"Failed: {description}")
            if e.stderr:
                print(f"  Error: {e.stderr}")
            return False
        except FileNotFoundError:
            return False

    def check_command_exists(self, cmd: str) -> bool:
        """Check if a command exists in PATH"""
        result = subprocess.run(
            ['where' if self.os_type == 'Windows' else 'which', cmd],
            capture_output=True
        )
        return result.returncode == 0

    def check_python_version(self) -> bool:
        """Check Python version. 3.12+ because the bundled MythGauntlet engine requires it
        (the old floor was 3.8, from before the engine merged in)."""
        self.print_step(1, "Checking Python version...")
        version = sys.version_info
        if (version.major, version.minor) >= (3, 12):
            self.print_success(f"Python {version.major}.{version.minor}.{version.micro}")
            self.checks_passed['python'] = True
            return True
        self.print_error(
            f"Python 3.12+ required (you have {version.major}.{version.minor}) - "
            "the deck-strength engine needs it"
        )
        return False

    def check_git(self) -> bool:
        """Check if git is installed"""
        self.print_step(2, "Checking Git...")
        if self.check_command_exists('git'):
            result = subprocess.run(['git', '--version'], capture_output=True, text=True)
            version = result.stdout.strip()
            self.print_success(version)
            self.checks_passed['git'] = True
            return True
        else:
            self.print_error("Git not found")
            self.optional_missing.append("git")
            return False

    def check_node_npm(self) -> bool:
        """Check if Node.js and npm are installed"""
        self.print_step(3, "Checking Node.js and npm...")

        if not self.check_command_exists('node'):
            self.print_error("Node.js not found")
            return False

        if not self.check_command_exists('npm'):
            self.print_error("npm not found")
            return False

        node_result = subprocess.run(['node', '--version'], capture_output=True, text=True)
        npm_result = subprocess.run(['npm', '--version'], capture_output=True, text=True)

        self.print_success(f"Node.js {node_result.stdout.strip()}")
        self.print_success(f"npm {npm_result.stdout.strip()}")
        self.checks_passed['node'] = True
        return True

    def install_python_dependencies(self) -> bool:
        """Install Python dependencies"""
        self.print_step(4, "Installing Python dependencies...")

        requirements_file = self.project_root / 'requirements.txt'
        if not requirements_file.exists():
            self.print_warning("requirements.txt not found")
            return True

        if self.run_command(
            [sys.executable, '-m', 'pip', 'install', '-r', str(requirements_file)],
            "Installing packages from requirements.txt"
        ):
            self.print_success("Python dependencies installed")
            self.checks_passed['python_deps'] = True
            return True
        else:
            self.print_error("Failed to install Python dependencies")
            return False

    def install_node_dependencies(self) -> bool:
        """Install Node.js dependencies"""
        self.print_step(5, "Installing Node.js dependencies...")

        frontend_dir = self.project_root / 'frontend'
        if not frontend_dir.exists():
            self.print_warning("frontend directory not found")
            return True

        # There is no package.json at the repo root, so the old first `npm install` here was
        # a no-op that gated the real one behind its exit status. Install in frontend/ only.
        os.chdir(frontend_dir)
        try:
            ok = self.run_command(['npm', 'install'], "Installing frontend dependencies")
        finally:
            os.chdir(self.project_root)

        if ok:
            self.print_success("Node.js dependencies installed")
            self.checks_passed['node_deps'] = True
            return True

        self.print_error("Failed to install Node.js dependencies")
        return False

    def build_frontend(self) -> bool:
        """Build the frontend"""
        self.print_step(6, "Building frontend...")

        frontend_dir = self.project_root / 'frontend'
        os.chdir(frontend_dir)

        if self.run_command(
            ['npm', 'run', 'build'],
            "Running npm build"
        ):
            os.chdir(self.project_root)
            self.print_success("Frontend built successfully")
            self.checks_passed['frontend_build'] = True
            return True
        else:
            os.chdir(self.project_root)
            self.print_error("Failed to build frontend")
            return False

    def create_directories(self) -> bool:
        """Create necessary directories"""
        self.print_step(7, "Creating data directories...")

        dirs_to_create = [
            self.project_root / 'data',
            self.project_root / 'renders',
            self.project_root / 'scryfall_cache',
        ]

        for dir_path in dirs_to_create:
            dir_path.mkdir(exist_ok=True)
            self.print_info(f"Directory ready: {dir_path.name}/")

        self.print_success("Data directories created")
        self.checks_passed['directories'] = True
        return True

    def create_config(self) -> bool:
        """Create example configuration if it doesn't exist"""
        self.print_step(8, "Checking configuration...")

        config_path = self.project_root / '.env.example'
        if config_path.exists():
            self.print_info("Configuration template found")

            actual_config = self.project_root / '.env'
            if not actual_config.exists():
                self.print_info("Creating .env from template...")
                with open(config_path) as src, open(actual_config, 'w') as dst:
                    dst.write(src.read())
                self.print_success(".env created (please configure if needed)")
            else:
                self.print_info(".env already configured")

        self.checks_passed['config'] = True
        return True

    def print_optional_setup(self):
        """Print optional setup instructions"""
        self.print_header("Optional Setup")

        self.print_info("The following are OPTIONAL but enhance functionality:\n")

        print("  1. Ollama (Local LLM for card theming)")
        print("     Website: https://ollama.ai")
        print("     Windows/Mac: Download installer")
        print("     Linux: curl https://ollama.ai/install.sh | sh")
        print("     Then: ollama pull qwen2:7b\n")

        print("  2. ComfyUI (Stable Diffusion workflows)")
        print("     Website: https://github.com/comfyanonymous/ComfyUI")
        print("     Follow their setup guide for your OS")
        print("     Install required models as documented\n")

        print("  3. CUDA / GPU Support (for faster image generation)")
        print("     NVIDIA: https://developer.nvidia.com/cuda-toolkit")
        print("     AMD: https://rocmdocs.amd.com")
        print("     Intel: https://www.intel.com/content/www/us/en/develop/tools/oneapi/base-toolkit.html\n")

        self.print_info("You can set these up later. The app will work with defaults.")

    def print_startup_instructions(self):
        """Print how to start the application"""
        self.print_header("Ready to Start")

        self.print_success("All essential components installed!")
        print("\n" + "=" * 60)
        print("  Starting Myth Forge")
        print("=" * 60 + "\n")

        # Recommend manage.bat, not `python server.py`: server.py starts ONLY the web
        # server, while manage.bat also brings up the LLM gateway (:8010) for theming and
        # the strength engine (:8020) for brackets. It also used to name
        # start-mythforge.bat, which does not exist in this repo.
        if self.os_type == 'Windows':
            print("  Recommended - starts the web server, the LLM gateway and the engine:\n")
            print(f"  {Colors.BOLD}manage.bat{Colors.END}"
                  '   (or double-click "START MYTH FORGE.bat")\n')
            print("  Web server only (gateway/engine must already be up):\n")
            print(f"  {Colors.BOLD}python server.py{Colors.END}\n")
        else:
            print("  Run from terminal:\n")
            print(f"  {Colors.BOLD}bash start-mythforge.sh{Colors.END}"
                  "   (or: python server.py)\n")

        print("  Then open your browser to: http://localhost:8000\n")
        print("  Verify the install at any time:\n")
        print(f"  {Colors.BOLD}python verify-setup.py{Colors.END}\n")
        print("  Note: deck-strength brackets come from the bundled MythGauntlet engine.")
        print("  Its compiled card semantics are NOT shipped (still in training) - the")
        print("  engine falls back to Oracle-text heuristics. See docs/ENGINE_DATA.md.\n")

        print("=" * 60)
        print("  Quick Reference")
        print("=" * 60 + "\n")

        if self.os_type == 'Windows':
            print(f"  {Colors.BOLD}Build frontend:{Colors.END}  make frontend-build")
            print(f"  {Colors.BOLD}Dev server:{Colors.END}      make frontend-dev")
            print(f"  {Colors.BOLD}API server:{Colors.END}      python server.py\n")
        else:
            print(f"  {Colors.BOLD}Build frontend:{Colors.END}  make frontend-build")
            print(f"  {Colors.BOLD}Dev server:{Colors.END}      make frontend-dev")
            print(f"  {Colors.BOLD}API server:{Colors.END}      python server.py\n")

    def check_optional_dependencies(self):
        """Check for optional but useful dependencies"""
        self.print_header("Optional Dependencies")

        optional = {
            'ollama': 'Ollama (card theming)',
            'comfy': 'ComfyUI (image generation)',
        }

        for cmd, name in optional.items():
            if self.check_command_exists(cmd):
                self.print_success(f"{name} - Found")
            else:
                self.print_warning(f"{name} - Not installed (optional)")

    def run_installation(self) -> bool:
        """Run the full installation process"""
        self.print_header("Myth Forge Installation")
        print(f"Project root: {self.project_root}\n")

        # Essential checks
        if not self.check_python_version():
            return False

        self.check_git()

        if not self.check_node_npm():
            self.print_error("\nNode.js and npm are REQUIRED")
            self.print_info("Download: https://nodejs.org/")
            return False

        # Installation steps
        if not self.install_python_dependencies():
            return False

        if not self.install_node_dependencies():
            return False

        if not self.build_frontend():
            return False

        if not self.create_directories():
            return False

        if not self.create_config():
            return False

        # Post-install info
        self.check_optional_dependencies()
        self.print_optional_setup()

        return True

    def main(self):
        """Main entry point"""
        try:
            success = self.run_installation()

            if success:
                self.print_startup_instructions()

                if self.ask_yes_no("\nWould you like to start the server now?"):
                    self.print_info("Starting API server...")
                    self.run_command([sys.executable, 'server.py'])

                return 0
            else:
                self.print_header("Installation Failed")
                self.print_error("Please fix the errors above and run the installer again.")
                return 1

        except KeyboardInterrupt:
            print(f"\n\n{Colors.YELLOW}Installation cancelled by user{Colors.END}")
            return 1
        except Exception as e:
            self.print_error(f"Unexpected error: {e}")
            return 1


if __name__ == '__main__':
    installer = MythForgeInstaller()
    sys.exit(installer.main())
