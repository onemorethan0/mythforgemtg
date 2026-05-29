"""
Commander 3D Model Generator — Hunyuan3D v2 via ComfyUI + rembg background removal.

Pipeline:
  1. Load commander raw art (FLUX-generated PNG or Scryfall fallback)
  2. Background removal via rembg (pure Python, auto-downloads RMBG model once)
  3. 3D generation via ComfyUI Hunyuan3D v2 workflow → GLB file
  4. GLB → STL conversion via trimesh

Required ComfyUI models (download once):
  diffusion_models/  hunyuan3d-dit-v2-0-turbo.safetensors  (DiT, ~2 GB)
                     https://huggingface.co/tencent/Hunyuan3D-2/resolve/main/hunyuan3d-dit-v2-0-turbo.safetensors
  vae/               hunyuan3d-vae-v2-0-fp16.safetensors    (VAE, ~400 MB)
                     https://huggingface.co/tencent/Hunyuan3D-2/resolve/main/hunyuan3d-vae-v2-0-fp16.safetensors
  clip_vision/       sigclip_vision_patch14_384.safetensors  (CLIP, ~1.9 GB)
                     https://huggingface.co/Comfy-Org/sigclip_vision_patch14_384/resolve/main/sigclip_vision_patch14_384.safetensors

Alternatively use the download helper:
  python model3d.py --download-models
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

import requests

# Patch stdout for Windows UTF-8
if hasattr(sys.stdout, "buffer") and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer") and sys.stderr.encoding.lower().replace("-", "") != "utf8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Configuration ─────────────────────────────────────────────────────────────

_COMFY_PORT_CANDIDATES = [8188, 8000, 8001, 8002]
_COMFY_OUTPUT_DIR = Path(r"C:\Users\rvn92\Documents\ComfyUI\output")

# Hunyuan3D model filenames (user places these in ComfyUI/models/* dirs)
HUNYUAN3D_DIT_MODEL  = "hunyuan3d-dit-v2-0-turbo.safetensors"   # diffusion_models/
HUNYUAN3D_VAE_MODEL  = "hunyuan3d-vae-v2-0-fp16.safetensors"    # vae/
HUNYUAN3D_CLIP_MODEL = "sigclip_vision_patch14_384.safetensors"  # clip_vision/

# Hunyuan3D v2 generation settings (community-tested, 2025)
H3D_RESOLUTION    = 64     # latent resolution (higher = more detail, more VRAM)
H3D_STEPS         = 20     # denoising steps (20 is the Tencent default for turbo)
H3D_CFG           = 5.0    # classifier-free guidance
H3D_NUM_CHUNKS    = 8000   # VAE decode chunk size (reduce if OOM)
H3D_OCTREE_RES    = 256    # octree resolution for VAE decode
H3D_VOXEL_THRESH  = 0.6    # VoxelToMesh threshold (0.6 = balanced detail/watertight)

# ComfyUI workflow poll
_POLL_INTERVAL = 2.0
_OUTPUT_TIMEOUT = 600  # 10 min max for 3D generation


# ── ComfyUI connection helpers ────────────────────────────────────────────────

def _detect_comfy_base() -> str:
    for port in _COMFY_PORT_CANDIDATES:
        url = f"http://127.0.0.1:{port}"
        try:
            r = requests.get(f"{url}/system_stats", timeout=2)
            if r.status_code == 200:
                data = r.json()
                if "system" in data or "devices" in data:
                    return url
        except requests.RequestException:
            pass
    return "http://127.0.0.1:8188"


def _comfy_base() -> str:
    return _detect_comfy_base()


def _submit_workflow(workflow: dict, comfy_base: str) -> Optional[str]:
    """Submit a workflow to ComfyUI and return the prompt_id."""
    client_id = str(uuid.uuid4())
    payload = {"prompt": workflow, "client_id": client_id}
    r = requests.post(f"{comfy_base}/prompt", json=payload, timeout=15)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"ComfyUI /prompt rejected: {r.status_code} {r.text[:300]}")
    return r.json()["prompt_id"]


def _wait_for_completion(prompt_id: str, comfy_base: str,
                          progress_cb: Optional[Callable[[str], None]] = None,
                          timeout: float = _OUTPUT_TIMEOUT) -> dict:
    """
    Poll ComfyUI /history until the prompt completes.
    Returns the outputs dict from the history entry.
    Raises RuntimeError on timeout or execution error.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{comfy_base}/history/{prompt_id}", timeout=10)
            if r.status_code == 200:
                hist = r.json()
                entry = hist.get(prompt_id, {})
                if entry:
                    # Check for execution errors
                    status = entry.get("status", {})
                    if status.get("status_str") == "error":
                        msgs = status.get("messages", [])
                        err_msg = next(
                            (m[1].get("exception_message", str(m)) for m in msgs
                             if m[0] == "execution_error"), "unknown error"
                        )
                        raise RuntimeError(f"ComfyUI execution error: {err_msg}")
                    # Check for completion
                    if status.get("completed", False):
                        return entry.get("outputs", {})
        except RuntimeError:
            raise
        except Exception as e:
            print(f"  [model3d] poll error: {e}")

        if progress_cb:
            elapsed = int(timeout - (deadline - time.monotonic()))
            progress_cb(f"Generating 3D mesh… ({elapsed}s)")
        time.sleep(_POLL_INTERVAL)

    raise RuntimeError(f"3D generation timed out after {timeout}s")


def _find_glb_output(outputs: dict) -> Optional[Path]:
    """
    Scan ComfyUI history outputs for a GLB file and return its path.
    Handles both SaveGLB (outputs images list with .glb type) and file_path outputs.
    """
    for node_id, node_out in outputs.items():
        # SaveGLB stores in 'mesh' or 'images' with type 'output'
        for key in ("mesh", "images", "files"):
            for item in node_out.get(key, []):
                if isinstance(item, dict):
                    fname = item.get("filename", "")
                    subfolder = item.get("subfolder", "")
                    if fname.lower().endswith(".glb"):
                        glb_path = _COMFY_OUTPUT_DIR / subfolder / fname
                        if glb_path.exists():
                            return glb_path
        # GeomPackSaveMesh stores in 'file_path'
        for fp in node_out.get("file_path", []):
            p = Path(fp) if isinstance(fp, str) else Path(fp.get("value", ""))
            if p.suffix.lower() == ".glb" and p.exists():
                return p
    return None


# ── Model availability checks ─────────────────────────────────────────────────

def _comfy_models_dir() -> Path:
    """Return the ComfyUI models directory."""
    # Try to infer from ComfyUI output dir
    return _COMFY_OUTPUT_DIR.parent / "models"


def _check_hunyuan3d_models() -> dict:
    """Return which Hunyuan3D models are present on disk."""
    base = _comfy_models_dir()
    dit  = base / "diffusion_models" / HUNYUAN3D_DIT_MODEL
    vae  = base / "vae"              / HUNYUAN3D_VAE_MODEL
    clip = base / "clip_vision"      / HUNYUAN3D_CLIP_MODEL
    return {
        "dit":  dit.exists(),
        "vae":  vae.exists(),
        "clip": clip.exists(),
        "all":  dit.exists() and vae.exists() and clip.exists(),
        "dit_path":  str(dit),
        "vae_path":  str(vae),
        "clip_path": str(clip),
    }


def _check_comfy_nodes() -> bool:
    """Return True if Hunyuan3D v2 nodes are available in the running ComfyUI."""
    base = _comfy_base()
    try:
        r = requests.get(f"{base}/object_info/Hunyuan3Dv2Conditioning", timeout=5)
        if r.status_code != 200:
            return False
        data = r.json()
        # Single-node endpoint returns {"Hunyuan3Dv2Conditioning": {...node_info...}}
        node_info = data.get("Hunyuan3Dv2Conditioning", {})
        return "input" in node_info
    except Exception:
        return False


# ── Background removal (rembg) ────────────────────────────────────────────────

def remove_background(image_path: Path,
                       output_path: Path,
                       progress_cb: Optional[Callable[[str], None]] = None) -> Path:
    """
    Remove the background from an image using rembg (RMBG-1.4 via onnxruntime).

    Downloads the onnx model on first run (~170 MB, cached at ~/.u2net/).
    Returns the output path (RGBA PNG with transparent background).
    """
    from PIL import Image as _Image
    try:
        from rembg import remove as _rembg_remove
    except ImportError:
        raise RuntimeError("rembg not installed — run: pip install rembg")

    if progress_cb:
        progress_cb("Removing background (rembg)…")

    print(f"  [model3d] rembg: removing background from {image_path.name}")
    inp = _Image.open(image_path).convert("RGBA")

    # rembg processes PIL images directly
    result = _rembg_remove(inp)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(output_path, "PNG")
    print(f"  [model3d] rembg: saved to {output_path.name} ({result.size})")
    return output_path


# ── Hunyuan3D v2 ComfyUI workflow ─────────────────────────────────────────────

def _build_hunyuan3d_workflow(image_comfy_name: str, job_prefix: str) -> dict:
    """
    Build a ComfyUI workflow that:
      1. Loads the bg-removed commander image
      2. Encodes it with CLIP Vision
      3. Runs Hunyuan3D v2 DiT sampling
      4. Decodes voxels to mesh
      5. Converts voxels to mesh
      6. Saves as GLB

    image_comfy_name: the filename as registered in ComfyUI /upload/image
    job_prefix: used as the GLB filename prefix (e.g. "3d/commander_abc123")
    """
    seed = int(time.time() * 1000) % (2**31)
    return {
        # ── Loaders ────────────────────────────────────────────────────────────
        "1": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name":    HUNYUAN3D_DIT_MODEL,
                "weight_dtype": "fp8_e4m3fn",
            },
        },
        "2": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": HUNYUAN3D_VAE_MODEL},
        },
        "3": {
            "class_type": "CLIPVisionLoader",
            "inputs": {"clip_name": HUNYUAN3D_CLIP_MODEL},
        },
        # ── Image load + CLIP vision encode ───────────────────────────────────
        "4": {
            "class_type": "LoadImage",
            "inputs": {"image": image_comfy_name},
        },
        "5": {
            "class_type": "CLIPVisionEncode",
            "inputs": {
                "clip_vision": ["3", 0],
                "image":       ["4", 0],
            },
        },
        # ── Hunyuan3D conditioning ─────────────────────────────────────────────
        "6": {
            "class_type": "Hunyuan3Dv2Conditioning",
            "inputs": {
                "clip_vision_output": ["5", 0],
            },
        },
        # ── Empty latent ───────────────────────────────────────────────────────
        "7": {
            "class_type": "EmptyLatentHunyuan3Dv2",
            "inputs": {
                "resolution": H3D_RESOLUTION,
                "batch_size": 1,
            },
        },
        # ── KSampler ──────────────────────────────────────────────────────────
        "8": {
            "class_type": "KSampler",
            "inputs": {
                "model":          ["1", 0],
                "positive":       ["6", 0],
                "negative":       ["6", 1],
                "latent_image":   ["7", 0],
                "seed":           seed,
                "steps":          H3D_STEPS,
                "cfg":            H3D_CFG,
                "sampler_name":   "euler",
                "scheduler":      "simple",
                "denoise":        1.0,
            },
        },
        # ── VAE decode → voxel ────────────────────────────────────────────────
        "9": {
            "class_type": "VAEDecodeHunyuan3D",
            "inputs": {
                "samples":           ["8", 0],
                "vae":               ["2", 0],
                "num_chunks":        H3D_NUM_CHUNKS,
                "octree_resolution": H3D_OCTREE_RES,
            },
        },
        # ── Voxel → mesh ──────────────────────────────────────────────────────
        "10": {
            "class_type": "VoxelToMesh",
            "inputs": {
                "voxel":     ["9", 0],
                "algorithm": "surface net",
                "threshold": H3D_VOXEL_THRESH,
            },
        },
        # ── Save as GLB ───────────────────────────────────────────────────────
        "11": {
            "class_type": "SaveGLB",
            "inputs": {
                "mesh":            ["10", 0],
                "filename_prefix": job_prefix,
            },
        },
    }


def _upload_image_to_comfy(image_path: Path, comfy_base: str) -> str:
    """
    Upload an image to ComfyUI via /upload/image.
    Returns the filename as ComfyUI knows it (used in LoadImage nodes).
    """
    with open(image_path, "rb") as f:
        files = {"image": (image_path.name, f, "image/png")}
        r = requests.post(f"{comfy_base}/upload/image",
                          files=files,
                          data={"overwrite": "true"},
                          timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"ComfyUI image upload failed: {r.status_code} {r.text[:200]}")
    result = r.json()
    # ComfyUI may return {"name": "...", "subfolder": "...", "type": "input"}
    # The LoadImage node wants just the filename (relative to the input dir)
    subfolder = result.get("subfolder", "")
    name = result.get("name", image_path.name)
    return f"{subfolder}/{name}" if subfolder else name


def generate_3d_mesh(
    nobg_image_path: Path,
    glb_output_path: Path,
    progress_cb: Optional[Callable[[str], None]] = None,
    comfy_base: str = "",
) -> Path:
    """
    Generate a 3D GLB mesh from a background-removed image using
    Hunyuan3D v2 via ComfyUI.

    Returns glb_output_path once the file is written.
    Raises RuntimeError if ComfyUI or models are unavailable.
    """
    if not comfy_base:
        comfy_base = _comfy_base()

    # Upload image to ComfyUI input
    if progress_cb:
        progress_cb("Uploading image to ComfyUI…")
    comfy_name = _upload_image_to_comfy(nobg_image_path, comfy_base)
    print(f"  [model3d] uploaded to ComfyUI as: {comfy_name}")

    # Unique prefix so we can find the output GLB
    job_prefix = f"3d/commander_{uuid.uuid4().hex[:8]}"

    # Build and submit workflow
    workflow = _build_hunyuan3d_workflow(comfy_name, job_prefix)
    if progress_cb:
        progress_cb("Submitting 3D generation workflow…")
    prompt_id = _submit_workflow(workflow, comfy_base)
    print(f"  [model3d] prompt_id: {prompt_id}")

    # Wait for completion
    if progress_cb:
        progress_cb("Generating 3D mesh (Hunyuan3D v2)… this takes 2–5 minutes")
    outputs = _wait_for_completion(prompt_id, comfy_base, progress_cb=progress_cb)

    # Locate the GLB file
    glb_source = _find_glb_output(outputs)
    if glb_source is None:
        # Fallback: scan ComfyUI output/3d/ for the prefix
        glb_dir = _COMFY_OUTPUT_DIR / "3d"
        prefix_stem = job_prefix.split("/")[-1]
        candidates = sorted(glb_dir.glob(f"{prefix_stem}*.glb"),
                             key=lambda p: p.stat().st_mtime,
                             reverse=True) if glb_dir.exists() else []
        if candidates:
            glb_source = candidates[0]
        else:
            raise RuntimeError(
                "ComfyUI completed but no GLB output found. "
                "Check the ComfyUI console for errors."
            )

    # Copy to our renders directory
    glb_output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(glb_source, glb_output_path)
    print(f"  [model3d] GLB saved: {glb_output_path} ({glb_output_path.stat().st_size // 1024} KB)")
    return glb_output_path


# ── GLB → STL conversion ──────────────────────────────────────────────────────

def convert_glb_to_stl(glb_path: Path, stl_path: Path,
                        progress_cb: Optional[Callable[[str], None]] = None) -> Path:
    """
    Convert a GLB mesh file to STL using trimesh.

    Applies basic mesh cleanup:
      - Merge duplicate vertices
      - Remove degenerate faces
      - Fix winding (important for 3D printing)
    Returns stl_path.
    """
    try:
        import trimesh
    except ImportError:
        raise RuntimeError("trimesh not installed — run: pip install trimesh")

    if progress_cb:
        progress_cb("Converting GLB → STL…")

    print(f"  [model3d] loading GLB: {glb_path}")
    scene = trimesh.load(str(glb_path), force="scene")

    # Flatten scene (multiple meshes) into a single mesh
    if isinstance(scene, trimesh.Scene):
        meshes = [g for g in scene.dump() if isinstance(g, trimesh.Trimesh) and len(g.faces) > 0]
        if not meshes:
            raise RuntimeError("GLB contains no valid mesh geometry")
        mesh = trimesh.util.concatenate(meshes)
    else:
        mesh = scene

    # Mesh cleanup for 3D print quality
    mesh.merge_vertices()
    mesh.remove_degenerate_faces()
    trimesh.repair.fix_normals(mesh)
    trimesh.repair.fix_winding(mesh)

    # Export
    stl_path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(stl_path))
    size_kb = stl_path.stat().st_size // 1024
    print(f"  [model3d] STL saved: {stl_path} ({size_kb} KB, "
          f"{len(mesh.faces):,} faces, {len(mesh.vertices):,} vertices)")
    return stl_path


# ── Top-level orchestrator ────────────────────────────────────────────────────

def generate_commander_3d(
    art_path: Path,
    output_dir: Path,
    progress_cb: Optional[Callable[[str], None]] = None,
    comfy_base: str = "",
) -> Path:
    """
    Full pipeline: art PNG → STL.

    Steps:
      1. Background removal (rembg)
      2. Hunyuan3D v2 mesh generation (ComfyUI)
      3. GLB → STL conversion (trimesh)

    Returns: Path to the generated .stl file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    nobg_path = output_dir / "commander_nobg.png"
    glb_path  = output_dir / "commander_3d.glb"
    stl_path  = output_dir / "commander_3d.stl"

    # ── Step 1: Background removal ──────────────────────────────────────────
    if progress_cb:
        progress_cb("Removing background…")
    remove_background(art_path, nobg_path, progress_cb=progress_cb)

    # ── Step 2: 3D mesh generation ──────────────────────────────────────────
    if progress_cb:
        progress_cb("Starting 3D mesh generation (Hunyuan3D v2)…")
    generate_3d_mesh(nobg_path, glb_path, progress_cb=progress_cb,
                     comfy_base=comfy_base or _comfy_base())

    # ── Step 3: GLB → STL ──────────────────────────────────────────────────
    if progress_cb:
        progress_cb("Exporting STL for 3D printing…")
    convert_glb_to_stl(glb_path, stl_path, progress_cb=progress_cb)

    if progress_cb:
        progress_cb("Done! STL ready for download.")
    return stl_path


# ── Health check ──────────────────────────────────────────────────────────────

class Model3DGen:
    """
    Thin wrapper that exposes health_check() for the server startup and
    endpoint guards, mirroring the ImageGen pattern.
    """

    @staticmethod
    def health_check() -> dict:
        """
        Returns {ok, message, hint, models}.
        ok=True means everything is ready to generate a 3D model.
        """
        # Check ComfyUI
        base = _comfy_base()
        try:
            r = requests.get(f"{base}/system_stats", timeout=3)
            comfy_ok = r.status_code == 200
        except Exception:
            comfy_ok = False

        if not comfy_ok:
            return {
                "ok": False,
                "message": "ComfyUI is not running",
                "hint": "Start ComfyUI Desktop before generating a 3D model.",
                "models": {},
            }

        # Check Hunyuan3D nodes
        nodes_ok = _check_comfy_nodes()
        if not nodes_ok:
            return {
                "ok": False,
                "message": "Hunyuan3D v2 nodes not found in ComfyUI",
                "hint": (
                    "Update ComfyUI to the latest version — Hunyuan3D v2 nodes are "
                    "built-in since ComfyUI 0.3.x. Run: git pull in your ComfyUI folder."
                ),
                "models": {},
            }

        # Check model files
        model_status = _check_hunyuan3d_models()
        if not model_status["all"]:
            missing = []
            if not model_status["dit"]:
                missing.append(f"diffusion_models/{HUNYUAN3D_DIT_MODEL}")
            if not model_status["vae"]:
                missing.append(f"vae/{HUNYUAN3D_VAE_MODEL}")
            if not model_status["clip"]:
                missing.append(f"clip_vision/{HUNYUAN3D_CLIP_MODEL}")
            return {
                "ok": False,
                "message": f"Missing Hunyuan3D model file(s): {', '.join(missing)}",
                "hint": "Run `python model3d.py --download-models` to download the required models.",
                "models": model_status,
                "missing": missing,
            }

        # Check rembg
        try:
            import rembg  # noqa: F401
            rembg_ok = True
        except ImportError:
            rembg_ok = False

        if not rembg_ok:
            return {
                "ok": False,
                "message": "rembg library not installed",
                "hint": "Run: pip install rembg",
                "models": model_status,
            }

        return {
            "ok": True,
            "message": "Hunyuan3D v2 ready (ComfyUI + rembg)",
            "hint": "",
            "models": model_status,
        }


# ── Model downloader (CLI helper) ─────────────────────────────────────────────

_MODEL_DOWNLOADS = [
    {
        "name":    HUNYUAN3D_DIT_MODEL,
        "dest":    f"diffusion_models/{HUNYUAN3D_DIT_MODEL}",
        "url":     "https://huggingface.co/tencent/Hunyuan3D-2/resolve/main/hunyuan3d-dit-v2-0-turbo.safetensors",
        "size_mb": 2100,
    },
    {
        "name":    HUNYUAN3D_VAE_MODEL,
        "dest":    f"vae/{HUNYUAN3D_VAE_MODEL}",
        "url":     "https://huggingface.co/tencent/Hunyuan3D-2/resolve/main/hunyuan3d-vae-v2-0-fp16.safetensors",
        "size_mb": 400,
    },
    {
        "name":    HUNYUAN3D_CLIP_MODEL,
        "dest":    f"clip_vision/{HUNYUAN3D_CLIP_MODEL}",
        "url":     "https://huggingface.co/Comfy-Org/sigclip_vision_patch14_384/resolve/main/sigclip_vision_patch14_384.safetensors",
        "size_mb": 1900,
    },
]


def download_models(dry_run: bool = False) -> None:
    """Download Hunyuan3D v2 model files to the ComfyUI models directory."""
    models_dir = _comfy_models_dir()
    print(f"\nHunyuan3D v2 Model Downloader")
    print(f"Target: {models_dir}\n")

    for m in _MODEL_DOWNLOADS:
        dest = models_dir / m["dest"]
        if dest.exists():
            print(f"  [OK] Already present: {m['dest']} ({dest.stat().st_size // 1024 // 1024} MB)")
            continue
        print(f"  [--] Downloading {m['name']} (~{m['size_mb']} MB)")
        print(f"       URL: {m['url']}")
        if dry_run:
            print("       (dry-run — skipping)")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with requests.get(m["url"], stream=True, timeout=30) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = downloaded / total * 100
                            print(f"\r       {pct:.1f}%", end="", flush=True)
            print(f"\r  [OK] Saved: {dest}")
        except Exception as e:
            dest.unlink(missing_ok=True)
            print(f"\n  [ERR] Failed: {e}")

    print("\nDone. Restart ComfyUI for the new models to appear.")


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Commander 3D Model Generator")
    ap.add_argument("--health",           action="store_true", help="Check system health")
    ap.add_argument("--download-models",  action="store_true", help="Download Hunyuan3D v2 models")
    ap.add_argument("--dry-run",          action="store_true", help="Dry run (no downloads)")
    ap.add_argument("--generate",         metavar="IMAGE",     help="Generate STL from image path")
    ap.add_argument("--out",              metavar="DIR",       default=".", help="Output directory")
    args = ap.parse_args()

    if args.health:
        h = Model3DGen.health_check()
        print(json.dumps(h, indent=2))

    elif args.download_models:
        download_models(dry_run=args.dry_run)

    elif args.generate:
        art = Path(args.generate)
        if not art.exists():
            print(f"ERROR: {art} not found")
            sys.exit(1)
        out_dir = Path(args.out)
        print(f"Generating 3D model from: {art}")

        def _cb(msg):
            print(f"  → {msg}")

        stl = generate_commander_3d(art, out_dir, progress_cb=_cb)
        print(f"\nSTL written: {stl}")

    else:
        ap.print_help()
