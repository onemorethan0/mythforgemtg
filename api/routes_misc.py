"""Health, model/style catalogues, frame config, face upload and the log viewer.
"""
from __future__ import annotations

import io
import logging
import os
import time
import uuid
from typing import List

import requests
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.logbuffer import _LOG_BUFFER
from image_gen import ImageGen, _is_flux, _is_krea, _is_qwen, _is_sd35, _is_sdxl
from model3d import Model3DGen

logger = logging.getLogger("server")
router = APIRouter()


# ── Capability probe cache ─────────────────────────────────────────────────────
# /api/face-method is called on every step-mount by the UI, but each call
# triggers 5+ HTTP requests to ComfyUI. Cache results for a short window.
_probe_cache: dict = {"ts": 0, "data": None}
_PROBE_TTL = 8.0   # seconds


@router.get("/api/face-method")
def face_method():
    """Probe face-conditioning engine and available checkpoints (cached ~8s)."""
    now = time.time()
    if _probe_cache["data"] and (now - _probe_cache["ts"]) < _PROBE_TTL:
        return _probe_cache["data"]

    # Check ComfyUI reachability before doing the expensive probe
    try:
        requests.get("http://127.0.0.1:8188/system_stats", timeout=3)
    except Exception:
        result = {"face_method": "not available", "available": False,
                  "comfyui_offline": True, "has_schnell": False, "has_dev": False}
        _probe_cache.update({"ts": now, "data": result})
        return result

    try:
        # Single ImageGen() call handles both checkpoint detection and face
        # method setup. We avoid the duplicate list_checkpoints() HTTP roundtrip.
        ckpts = ImageGen.list_checkpoints()
        gen   = ImageGen()
        result = {
            "face_method":     gen.face_method_label,
            "available":       gen.face_method != "none",
            "comfyui_offline": False,
            "has_schnell":     len(ckpts["schnell"]) > 0,
            "has_dev":         len(ckpts["dev"]) > 0,
            "checkpoints":     ckpts,
        }
        _probe_cache.update({"ts": now, "data": result})
        return result
    except Exception as e:
        return {"face_method": "not available", "available": False,
                "comfyui_offline": False, "has_schnell": False, "has_dev": False,
                "error": str(e)}


@router.get("/api/comfy-status")
def comfy_status():
    """
    Lightweight ComfyUI readiness probe for the UI.  Returns the same dict
    shape used by the build pre-flight so the frontend can warn the user
    before they kick off a long build that would otherwise fall back to
    Scryfall art on every card.
    """
    return ImageGen.health_check()


@router.get("/api/health")
def health_check():
    """
    System health check: returns status of ComfyUI and Ollama services.
    Used by the frontend status indicator in the corner.
    """
    from themer import LLM_BACKEND, installed_models

    comfyui_status = "up"

    # Check ComfyUI
    try:
        r = requests.get("http://127.0.0.1:8188/system_stats", timeout=2)
        if r.status_code != 200:
            comfyui_status = "down"
    except Exception:
        comfyui_status = "down"

    # Check the LLM backend (llama.cpp via llama-swap, or Ollama)
    llm_status = "up" if installed_models(timeout=2) else "down"

    return {
        "comfyui": comfyui_status,
        # `ollama` key retained for backward compat; `llm` is the current key.
        "ollama": llm_status,
        "llm": llm_status,
        "llm_backend": LLM_BACKEND,
        "timestamp": time.time()
    }


@router.get("/api/llm-models")
def get_llm_models():
    """
    Return the curated LLM catalog with per-entry installed status.
    The UI uses this to populate the model selector in StepTheme.
    Entries flagged installed=False are shown disabled with a pull hint.
    """
    from themer import list_available_llms
    return list_available_llms()


@router.get("/api/frame-styles")
def get_frame_styles():
    """Frame systems the UI can offer. 'builtin' is always available; 'm15'
    requires a local Card Conjurer install (MYTHFORGE_CC_DIR) with M15 assets."""
    try:
        import cc_frames
        m15_ok = cc_frames.is_available("m15")
        fullart_ok = cc_frames.is_available("m15_fullart")
        extended_ok = cc_frames.is_available("m15_extended")
    except Exception:
        m15_ok = fullart_ok = extended_ok = False
    cc_hint = "Install Card Conjurer locally and set MYTHFORGE_CC_DIR to enable."
    return {
        "styles": [
            {"key": "builtin", "label": "Built-in Frames", "available": True,
             "note": "Bundled proxy frames — always available."},
            {"key": "m15", "label": "Official-style (M15)", "available": m15_ok,
             "note": ("Modern frames rendered from your local Card Conjurer install."
                      if m15_ok else cc_hint)},
            {"key": "m15_extended", "label": "Extended-art (M15)", "available": extended_ok,
             "note": ("Full-width extended art with a normal text box, from your local Card Conjurer."
                      if extended_ok else cc_hint)},
            {"key": "m15_fullart", "label": "Full-art (Borderless)", "available": fullart_ok,
             "note": ("Edge-to-edge full-art borderless frames from your local Card Conjurer."
                      if fullart_ok else cc_hint)},
        ],
        "default": "builtin",
    }


class FrameConfigRequest(BaseModel):
    cc_dir: str = Field("", max_length=600)


@router.get("/api/frame-config")
def get_frame_config():
    """Current Card Conjurer folder setting (for the in-app configuration field)."""
    try:
        import cc_frames
        return {
            "cc_dir":   cc_frames.configured_cc_dir(),
            "from_env": bool(os.environ.get("MYTHFORGE_CC_DIR", "").strip()),
            "valid":    cc_frames.cc_root() is not None,
        }
    except Exception as e:
        return {"cc_dir": "", "from_env": False, "valid": False, "error": str(e)}


@router.post("/api/frame-config")
def set_frame_config(req: FrameConfigRequest):
    """Set the Card Conjurer folder from the UI. Persists to cc_config.json.
    The MYTHFORGE_CC_DIR env var (if set) always takes precedence over this."""
    import cc_frames
    if os.environ.get("MYTHFORGE_CC_DIR", "").strip():
        return {
            "ok": False,
            "error": "The MYTHFORGE_CC_DIR environment variable is set and overrides this setting. Unset it to configure the folder here.",
            "cc_dir": cc_frames.configured_cc_dir(),
            "valid": cc_frames.cc_root() is not None,
        }
    path = (req.cc_dir or "").strip()
    cc_frames.set_cc_dir(path)
    root = cc_frames.cc_root()
    valid = root is not None
    return {
        "ok": True,
        "cc_dir": cc_frames.configured_cc_dir(),
        "valid": valid,
        "m15":         cc_frames.is_available("m15"),
        "m15_fullart": cc_frames.is_available("m15_fullart"),
        "note": ("" if valid or not path else
                 "Folder set, but no img/frames found there — check the path points to your Card Conjurer root."),
    }


@router.get("/api/art-styles")
def get_art_styles():
    """
    Return all LoRA presets with per-LoRA install status.
    The UI uses this to show ready/missing badges and download hints.
    """
    from image_gen import get_all_presets

    # Query ComfyUI for installed LoRAs (tolerate ComfyUI being offline)
    installed_lower: list[str] = []
    try:
        r = requests.get("http://127.0.0.1:8188/object_info/LoraLoader", timeout=5)
        if r.status_code == 200:
            raw = (r.json()
                   .get("LoraLoader", {})
                   .get("input", {}).get("required", {})
                   .get("lora_name", [[]])[0])
            installed_lower = [f.lower() for f in raw]
    except Exception:
        pass

    from image_gen import _load_custom_presets
    custom_keys = set(_load_custom_presets().keys())

    result = []
    for key, preset in get_all_presets().items():
        loras = []
        for entry in preset["loras"]:
            frags = entry.get("fragments", [entry.get("fragment", "")])
            is_inst = any(
                any(frag.lower() in f for frag in frags)
                for f in installed_lower
            )
            loras.append({
                "label":         entry["label"],
                "installed":     is_inst,
                "download_url":  entry.get("download_url"),
                "download_note": entry.get("download_note"),
            })
        all_inst = all(l["installed"] for l in loras)
        any_inst = any(l["installed"] for l in loras)

        # Style variants (per-card rotation stacks) — surfaced so the UI can show a
        # "flavor" selector. Each variant is ready only when ALL its LoRAs are
        # installed; "Variety mix" (auto) is added client-side as the default.
        variants = []
        for stack in preset.get("lora_rotation", []) or []:
            v_loras = stack.get("loras", [])
            v_status = []
            for entry in v_loras:
                frags = entry.get("fragments", [entry.get("fragment", "")])
                v_status.append(any(
                    any(frag.lower() in f for frag in frags)
                    for f in installed_lower
                ))
            variants.append({
                "label":       stack.get("label", "Variant"),
                "description": stack.get("description", ""),
                "ready":       bool(v_status) and all(v_status),
                "partial":     any(v_status) and not all(v_status),
            })

        result.append({
            "key":         key,
            "label":       preset["label"],
            "description": preset["description"],
            "icon":        preset["icon"],
            "ready":       all_inst,
            "partial":     any_inst and not all_inst,
            "loras":       loras,
            "variants":    variants,
            "custom":      key in custom_keys,
            # Model type constraint — tells the UI which checkpoint family is required
            "required_checkpoint_type": preset.get("required_checkpoint_type"),
            # Include full config so the UI can pre-populate the editor
            "flux_prefix":      preset.get("flux_prefix") or "",
            "negative_prompt":  preset.get("negative_prompt", ""),
            "style_guide_hint": preset.get("style_guide_hint", ""),
            "themer_medium":    preset.get("themer_medium", ""),
            "themer_quality":   preset.get("themer_quality", ""),
        })
    return result


@router.get("/api/checkpoints")
def get_checkpoints():
    """
    Return all available checkpoints in ComfyUI.
    Enables UI dropdown for explicit checkpoint selection.
    """
    try:
        r = requests.get("http://127.0.0.1:8188/object_info/CheckpointLoaderSimple", timeout=5)
        if r.status_code == 200:
            ckpts = (
                r.json()
                .get("CheckpointLoaderSimple", {})
                .get("input", {}).get("required", {})
                .get("ckpt_name", [[]])[0]
            )
            # Filter out LTX and unconfirmed models
            usable = [c for c in ckpts if not c.startswith("LTX") and not c.startswith("Unconfirmed")]

            # Categorize by type using the same detection functions as image_gen.py
            result = []
            for ckpt in sorted(usable):
                if _is_krea(ckpt):
                    ckpt_type = "FLUX Krea"      # flux-dev arch → all FLUX LoRAs apply
                elif _is_flux(ckpt):
                    ckpt_type = "FLUX"
                elif _is_sd35(ckpt):
                    ckpt_type = "SD 3.5"
                elif _is_sdxl(ckpt):
                    ckpt_type = "SDXL"
                else:
                    ckpt_type = "Unknown"

                result.append({
                    "filename": ckpt,
                    "type": ckpt_type,
                    "label": f"{ckpt} ({ckpt_type})"
                })

            # Qwen-Image and FLUX.1-Krea-dev ship as UNET files (diffusion_models),
            # not CheckpointLoaderSimple checkpoints, so they never appear above. Probe
            # UNETLoader and add synthetic entries so the UI can offer them. Only the
            # first of each family is added (the app resolves companions by fragment).
            try:
                ur = requests.get("http://127.0.0.1:8188/object_info/UNETLoader", timeout=5)
                if ur.status_code == 200:
                    unets = (ur.json().get("UNETLoader", {}).get("input", {})
                             .get("required", {}).get("unet_name", [[]])[0]) or []
                    seen_qwen = seen_krea = False
                    for u in sorted(unets):
                        if u.startswith("Unconfirmed"):
                            continue
                        if _is_qwen(u) and not seen_qwen:
                            result.append({"filename": u, "type": "Qwen-Image",
                                           "label": f"{u} (Qwen-Image)"})
                            seen_qwen = True
                        elif _is_krea(u) and not seen_krea:
                            result.append({"filename": u, "type": "FLUX Krea",
                                           "label": f"{u} (FLUX Krea)"})
                            seen_krea = True
            except Exception:
                pass
            return result
    except Exception:
        pass

    return []


@router.get("/api/comfyui/loras")
def list_comfyui_loras():
    """
    Return all LoRA filenames currently installed in ComfyUI.
    Used by the custom-style builder so the user can pick from installed LoRAs.
    """
    try:
        r = requests.get("http://127.0.0.1:8188/object_info/LoraLoader", timeout=5)
        if r.status_code == 200:
            raw = (r.json()
                   .get("LoraLoader", {})
                   .get("input", {}).get("required", {})
                   .get("lora_name", [[]])[0])
            return {"loras": raw, "online": True}
    except Exception:
        pass
    return {"loras": [], "online": False}


@router.post("/api/art-styles/custom")
async def upsert_custom_art_style(payload: dict):
    """
    Create or update a custom art style preset.

    Body shape (all fields except key/label/loras are optional):
    {
      "key":             "my_style",          # slug, no spaces
      "label":           "My Style",
      "description":     "...",
      "icon":            "✨",
      "flux_prefix":     "...",
      "negative_prompt": "...",               # optional
      "style_guide_hint": "...",
      "themer_medium":   '"illustration," or "painting,"',
      "themer_quality":  '"vivid colors" or "detailed"',
      "loras": [
        {
          "fragments":      ["filename_fragment"],
          "trigger":        "trigger word",
          "model_strength": 0.7,
          "clip_strength":  0.7,
          "dark_only":      false,
          "label":          "LoRA Name",
          "download_url":   null,
          "download_note":  ""
        }
      ]
    }
    """
    from image_gen import upsert_custom_preset

    key = payload.get("key", "").strip().replace(" ", "_")
    if not key:
        raise HTTPException(400, "key is required")

    # Guard against overwriting built-in presets
    from image_gen import _LORA_PRESETS
    if key in _LORA_PRESETS:
        raise HTTPException(400, f"'{key}' is a built-in preset and cannot be overwritten. Choose a different key.")

    preset = {
        "label":            payload.get("label", key),
        "description":      payload.get("description", ""),
        "icon":             payload.get("icon", "✨"),
        "flux_prefix":      payload.get("flux_prefix") or None,
        "style_guide_hint": payload.get("style_guide_hint", ""),
        "themer_medium":    payload.get("themer_medium", '"digital painting," or "illustration,"'),
        "themer_quality":   payload.get("themer_quality", '"vivid colors, detailed"'),
        "loras":            payload.get("loras", []),
    }
    # Only include negative_prompt if provided (avoids overriding default _FLUX_NEGATIVE for styles that don't need it)
    if payload.get("negative_prompt"):
        preset["negative_prompt"] = payload["negative_prompt"]

    # Report the truth: _save_custom_presets used to swallow write failures, so this
    # returned ok:True for a style that never reached disk and vanished on reload.
    try:
        upsert_custom_preset(key, preset)
    except OSError as e:
        logger.error("could not save custom art style %r", key, exc_info=e)
        raise HTTPException(500, f"Could not save custom art style '{key}'.") from e
    return {"ok": True, "key": key}


@router.delete("/api/art-styles/custom/{key}")
async def delete_custom_art_style(key: str):
    """Remove a custom art style preset."""
    from image_gen import _LORA_PRESETS, delete_custom_preset
    if key in _LORA_PRESETS:
        raise HTTPException(400, f"'{key}' is a built-in preset and cannot be deleted.")
    try:
        deleted = delete_custom_preset(key)
    except OSError as e:
        logger.error("could not delete custom art style %r", key, exc_info=e)
        raise HTTPException(500, f"Could not delete custom art style '{key}'.") from e
    if not deleted:
        raise HTTPException(404, f"Custom preset '{key}' not found.")
    return {"ok": True, "key": key}


# ── Face upload ───────────────────────────────────────────────────────────────
@router.post("/api/upload-face")
async def upload_face(files: List[UploadFile] = File(...)):
    """
    Accept 1-15 face reference photos (commander group: up to 5; crew group: up to 10).
    Returns a face_key that the client includes in the BuildRequest so the
    art generator can apply the user's likeness to humanoid card art.
    """
    if not files:
        raise HTTPException(400, "No files provided")
    if len(files) > 15:
        raise HTTPException(400, f"Maximum 15 photos per upload group ({len(files)} received)")

    MAX_PER_FILE = 20 * 1024 * 1024   # 20 MB per image
    MAX_TOTAL    = 60 * 1024 * 1024   # 60 MB total across the upload

    face_key  = uuid.uuid4().hex[:16]
    file_list: list[tuple[str, bytes]] = []
    total_bytes = 0
    for f in files:
        data = await f.read()
        if not data:
            raise HTTPException(400, f"File '{f.filename}' is empty")
        if len(data) > MAX_PER_FILE:
            raise HTTPException(413, f"File '{f.filename}' exceeds 20 MB limit")
        total_bytes += len(data)
        if total_bytes > MAX_TOTAL:
            raise HTTPException(413, f"Total upload exceeds {MAX_TOTAL // (1024*1024)} MB")
        # Hard magic-byte check — reject anything that isn't a real image header.
        is_jpeg = data[:3] == b'\xff\xd8\xff'
        is_png  = data[:8] == b'\x89PNG\r\n\x1a\n'
        is_webp = data[:4] == b'RIFF' and data[8:12] == b'WEBP'
        is_gif  = data[:4] == b'GIF8'
        if not (is_jpeg or is_png or is_webp or is_gif):
            raise HTTPException(400, f"File '{f.filename}': not a recognized image (JPEG/PNG/WebP/GIF only)")
        # Defense in depth: ask PIL to verify the body is a parseable image.
        try:
            from PIL import Image as _PILImg
            _img = _PILImg.open(io.BytesIO(data))
            _img.verify()
        except Exception as _ve:
            raise HTTPException(400, f"File '{f.filename}': image data corrupt or unsupported ({_ve})")
        file_list.append((f.filename or "photo.jpg", data))

    from face_ref import save_face_images
    paths = save_face_images(file_list, face_key)

    # Probe which face method ImageGen will use — reuse cached probe if fresh
    # to avoid a 5-roundtrip ComfyUI hit on every face upload.
    method_label = "unknown"
    now = time.time()
    if _probe_cache["data"] and (now - _probe_cache["ts"]) < _PROBE_TTL:
        method_label = _probe_cache["data"].get("face_method", "unknown")
    else:
        try:
            gen = ImageGen()
            method_label = gen.face_method_label
        except Exception:
            pass

    return {
        "face_key":     face_key,
        "count":        len(paths),
        "face_method":  method_label,
    }


@router.get("/api/3d-health")
async def get_3d_health():
    """Return Hunyuan3D v2 / rembg availability status."""
    return JSONResponse(Model3DGen.health_check())


@router.get("/api/logs")
async def get_logs(lines: int = 300):
    """
    Return the most recent server log lines from the in-memory ring buffer.
    Captures stdout/stderr (startup checks, pipeline prints, tracebacks) and
    uvicorn access logs. `lines` is clamped to [1, 5000].
    """
    lines = max(1, min(int(lines), 5000))
    buf = list(_LOG_BUFFER)
    recent = buf[-lines:]
    return JSONResponse({
        "lines":    recent,
        "total":    len(buf),
        "returned": len(recent),
    })
