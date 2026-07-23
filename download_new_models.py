"""Fetch the FLUX.1-Krea-dev and Qwen-Image assets for Myth Forge image gen.

Non-interactive, resumable (skips files already present at a sane size). Pulls the
ComfyUI-ready fp8 files from the Comfy-Org Hugging Face mirrors (Apache/redistributed,
normally no token needed) into the live ComfyUI models tree.

Run:  Documents/ComfyUI/.venv/Scripts/python.exe download_new_models.py [krea|qwen|all]

Detection in image_gen.py:
  • Krea (UNET path): UNETLoader/diffusion_models + DualCLIPLoader(clip_l + t5xxl) + flux VAE.
  • Qwen-Image:       UNETLoader/diffusion_models + CLIPLoader(qwen_2.5_vl) + qwen VAE.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download

MODELS = Path(r"C:\Users\rvn92\Documents\ComfyUI\models")

# (repo_id, remote_path_in_repo, destination_file) — dest is flattened to a plain name.
JOBS = {
    "krea": [
        ("Comfy-Org/FLUX.1-Krea-dev_ComfyUI",
         "split_files/diffusion_models/flux1-krea-dev_fp8_scaled.safetensors",
         MODELS / "diffusion_models" / "flux1-krea-dev_fp8_scaled.safetensors"),
        # clip_l for the flux DualCLIPLoader (t5xxl + ae.safetensors already present).
        ("comfyanonymous/flux_text_encoders",
         "clip_l.safetensors",
         MODELS / "text_encoders" / "clip_l.safetensors"),
    ],
    "qwen": [
        ("Comfy-Org/Qwen-Image_ComfyUI",
         "split_files/diffusion_models/qwen_image_fp8_e4m3fn.safetensors",
         MODELS / "diffusion_models" / "qwen_image_fp8_e4m3fn.safetensors"),
        ("Comfy-Org/Qwen-Image_ComfyUI",
         "split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors",
         MODELS / "text_encoders" / "qwen_2.5_vl_7b_fp8_scaled.safetensors"),
        ("Comfy-Org/Qwen-Image_ComfyUI",
         "split_files/vae/qwen_image_vae.safetensors",
         MODELS / "vae" / "qwen_image_vae.safetensors"),
    ],
}

_MIN_BYTES = 50 * 1024 * 1024   # treat a <50MB "safetensors" as an incomplete stub


def _fetch(repo_id: str, remote: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > _MIN_BYTES:
        print(f"  [ok] already present: {dest.name} ({dest.stat().st_size/1e9:.1f} GB)")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  [get] {repo_id} :: {remote}")
    # Download into the destination folder (hub keeps the repo subpath), then flatten.
    local = hf_hub_download(repo_id=repo_id, filename=remote,
                            local_dir=str(dest.parent))
    local = Path(local)
    if local.resolve() != dest.resolve():
        os.replace(local, dest)
        # Clean up the now-empty split_files/... scaffold the hub created.
        try:
            p = local.parent
            while p != dest.parent and p.exists() and not any(p.iterdir()):
                p.rmdir(); p = p.parent
        except OSError:
            pass
    print(f"  [ok] done: {dest.name} ({dest.stat().st_size/1e9:.1f} GB)")


def main() -> int:
    which = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    keys = ["krea", "qwen"] if which == "all" else [which]
    failed = []
    for k in keys:
        if k not in JOBS:
            print(f"unknown target '{k}' (use krea|qwen|all)"); return 2
        print(f"\n=== {k.upper()} ===")
        for repo_id, remote, dest in JOBS[k]:
            try:
                _fetch(repo_id, remote, dest)
            except Exception as e:
                print(f"  [FAIL] {dest.name}: {e}")
                failed.append((dest.name, str(e)))
    if failed:
        print("\nSome files failed (a gated repo needs `huggingface-cli login`):")
        for name, err in failed:
            print(f"  - {name}: {err[:160]}")
        return 1
    print("\nAll assets present. Restart ComfyUI so the new files register, then pick "
          "the model in Myth Forge's Theme step (✦ Krea / ◈ Qwen-Image).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
