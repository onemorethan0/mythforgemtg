#!/usr/bin/env python3
"""
Myth Forge - Model Downloader
Downloads recommended checkpoints and optional LoRAs for MTG card generation.
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Optional

# Colors for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    END = '\033[0m'


def find_comfyui_dir() -> Optional[Path]:
    """Find ComfyUI directory by looking in common locations."""
    candidates = [
        Path.cwd() / "ComfyUI",
        Path.home() / "ComfyUI",
        Path(os.environ.get("COMFYUI_DIR", "")),
        Path("../ComfyUI"),
        Path("../../ComfyUI"),
    ]

    for path in candidates:
        if path.exists() and (path / "main.py").exists():
            return path

    return None


def ensure_comfyui_dir(comfyui_dir: Path) -> None:
    """Ensure ComfyUI directories exist."""
    for subdir in ["models/checkpoints", "models/loras", "models/vae"]:
        (comfyui_dir / subdir).mkdir(parents=True, exist_ok=True)


def print_header(text: str) -> None:
    """Print a formatted header."""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}{Colors.END}\n")


def print_success(text: str) -> None:
    """Print success message."""
    print(f"{Colors.GREEN}[OK]{Colors.END} {text}")


def print_warning(text: str) -> None:
    """Print warning message."""
    print(f"{Colors.YELLOW}[!]{Colors.END} {text}")


def print_error(text: str) -> None:
    """Print error message."""
    print(f"{Colors.RED}[X]{Colors.END} {text}")


def check_huggingface_cli() -> bool:
    """Check if huggingface-hub is installed."""
    try:
        import huggingface_hub
        return True
    except ImportError:
        return False


def install_huggingface_cli() -> bool:
    """Try to install huggingface-hub."""
    try:
        print_warning("Installing huggingface-hub for faster downloads...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "huggingface-hub", "-q"])
        print_success("huggingface-hub installed")
        return True
    except Exception as e:
        print_error(f"Could not install huggingface-hub: {e}")
        return False


def download_checkpoint(comfyui_dir: Path, model_type: str, url: str, filename: str) -> bool:
    """Download a checkpoint using huggingface-hub or curl."""
    dest = comfyui_dir / "models" / "checkpoints" / filename

    if dest.exists():
        print_success(f"{filename} already exists")
        return True

    print_warning(f"Downloading {filename}... (this may take a few minutes)")

    try:
        # Try huggingface-hub first (faster)
        if check_huggingface_cli():
            from huggingface_hub import hf_hub_download

            if "huggingface.co" in url:
                # Extract repo_id and filename from URL
                parts = url.replace("https://huggingface.co/", "").split("/")
                repo_id = f"{parts[0]}/{parts[1]}"
                file_name = parts[-1]

                hf_hub_download(
                    repo_id=repo_id,
                    filename=file_name,
                    local_dir=dest.parent,
                    local_dir_use_symlinks=False,
                )
                print_success(f"{filename} downloaded")
                return True

        # Fallback to curl
        print_warning(f"Downloading via curl... (large file, please wait)")
        subprocess.check_call(
            ["curl", "-L", url, "-o", str(dest)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print_success(f"{filename} downloaded")
        return True

    except Exception as e:
        print_error(f"Download failed: {e}")
        print_warning(f"Manual download: {url}")
        return False


def main():
    """Main entry point."""
    print_header("Myth Forge Model Downloader")

    # Find ComfyUI
    print("Locating ComfyUI...")
    comfyui_dir = find_comfyui_dir()

    if not comfyui_dir:
        print_error("ComfyUI not found!")
        print_warning("Please install ComfyUI from: https://github.com/comfyanonymous/ComfyUI")
        sys.exit(1)

    print_success(f"Found ComfyUI at: {comfyui_dir}")
    ensure_comfyui_dir(comfyui_dir)

    # Ask user what to download
    print_header("Download Options")
    print("""
1. FLUX Schnell (RECOMMENDED)
   - Fast generation (5-10 seconds per image)
   - Good quality
   - ~24GB

2. FLUX Dev
   - Highest quality
   - Slower (30-60 seconds per image)
   - ~24GB

3. SD 3.5 Large
   - Good all-around
   - Medium speed
   - ~7.7GB

4. Skip Checkpoint (use existing)

5. Download All

Choose option (1-5): """, end="")

    choice = input().strip()

    checkpoints = {
        "1": {
            "name": "FLUX Schnell",
            "url": "https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/flux1-schnell.safetensors",
            "filename": "flux1-schnell.safetensors",
        },
        "2": {
            "name": "FLUX Dev",
            "url": "https://huggingface.co/black-forest-labs/FLUX.1-dev/resolve/main/flux1-dev.safetensors",
            "filename": "flux1-dev.safetensors",
        },
        "3": {
            "name": "SD 3.5 Large",
            "url": "https://huggingface.co/stabilityai/stable-diffusion-3.5-large/resolve/main/sd3.5_large.safetensors",
            "filename": "sd3.5_large.safetensors",
        },
    }

    if choice == "5":
        # Download all
        for key in ["1", "2", "3"]:
            cp = checkpoints[key]
            print(f"\nDownloading {cp['name']}...")
            download_checkpoint(comfyui_dir, key, cp["url"], cp["filename"])
    elif choice in checkpoints:
        cp = checkpoints[choice]
        download_checkpoint(comfyui_dir, choice, cp["url"], cp["filename"])
    elif choice != "4":
        print_warning("Invalid choice, skipping checkpoint download")

    # Ask about LoRAs
    print_header("Optional: Download LoRAs")
    print("""
LoRAs enhance image quality for specific styles. You can skip this for now.

Download recommended LoRAs? (y/n): """, end="")

    if input().strip().lower() == "y":
        print_warning("LoRA downloads are best done manually via CivitAI:")
        print("""
Recommended LoRAs:
1. MTG v2 (Core MTG aesthetic)
   https://civitai.com/models/669671

2. MTG Composition (Better layouts)
   https://civitai.com/models/567735

3. Realism (Realistic styles)
   https://civitai.com/models/680417

4. Darkness (Dark/horror themes)
   https://civitai.com/models/300898

5. Sketch (Hand-drawn styles)
   https://civitai.com/models/730615

Save downloaded files to: {comfyui_dir / 'models' / 'loras'}
        """)

    print_header("Setup Complete!")
    print(f"Models location: {comfyui_dir / 'models' / 'checkpoints'}")
    print(f"LoRAs location: {comfyui_dir / 'models' / 'loras'}")
    print()
    print("Next steps:")
    print("1. Restart ComfyUI if it's running")
    print("2. Start Myth Forge: python server.py")
    print("3. Open http://localhost:8000")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(0)
