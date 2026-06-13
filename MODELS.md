# Models & LoRAs

Where to get the image-generation models. All live under your ComfyUI models dir
(`C:\Users\rvn92\Documents\ComfyUI\models\` on the dev machine).

The easy path: **`download-models.bat`** (Windows) / **`python download-models.py`** (Mac/Linux) — interactive checkpoint downloader. Or `manage.bat` → option 7.

## Checkpoints (need at least one) → `models/checkpoints/`
| Model | Size | Notes |
|---|---|---|
| **FLUX.1 Schnell** | ~24 GB | Fast (8 steps), good quality — best starting point. [HF](https://huggingface.co/black-forest-labs/FLUX.1-schnell) |
| **FLUX.1 Dev** | ~24 GB | Best quality (35 steps), slower. [HF](https://huggingface.co/black-forest-labs/FLUX.1-dev) |
| **Illustrious XL** (SDXL) | ~7.7 GB | Anime/fantasy; **required** for the Ragnarok Online preset. [Civitai](https://civitai.com/models/296424) |
| **SD 3.5 Large** | ~7.7 GB | All-around alternative. [HF](https://huggingface.co/stabilityai/stable-diffusion-3.5-large) |

The app auto-detects checkpoint type (FLUX / SDXL / SD3.5) from the filename and applies the right sampler settings (see [CLAUDE.md](./CLAUDE.md)).

## LoRAs → `models/loras/`
LoRAs are **optional** and **auto-detected by filename fragment** — each art-style preset declares the fragments it looks for, so you just drop a `.safetensors` into `models/loras/` and the matching style activates. The preset → LoRA mapping is the table in [README.md](./README.md#art-style-presets); download links live on each preset's `download_url` in `image_gen.py` (`_LORA_PRESETS`).

Notes when adding a LoRA:
- Must match your checkpoint family (FLUX-dev LoRAs for FLUX dev; verify `modelspec.architecture` in the safetensors metadata). Schnell uses **no** LoRAs.
- Keep filenames close to the preset's fragment (e.g. `kcyberpunk`, `boFLUX_Abyss_Neon`, `Neon_Cyberpunk_Detailer` for the cyberpunk style).
- You can also override the active LoRAs per build in the Theme step's **Advanced → LoRAs** picker.

## Face conditioning (optional)
- **PuLID (FLUX)** — best identity. Install `ComfyUI-PuLID-Flux`, models → `models/pulid/` + an EVA-CLIP.
- **ReActor (swap)** — install `comfyui-reactor-node`; models auto-fetch (`inswapper_128.onnx`, `codeformer`). Runs on CPU here (see [COMFYUI_SETUP.md](./COMFYUI_SETUP.md) for the CUDA-13 note). Requires CUDA 12.x for GPU.
- Auto-detected best-available method wins; tune in the Face step's Advanced panel.

## Animated cards (optional) → image-to-video model
For the **✨ Animate** feature (gallery → looping MP4 cards), install ONE image-to-video model into ComfyUI; the app auto-detects it (`GET /api/video-health`). Both ship as ComfyUI-core nodes — you supply the weights:
- **LTX-Video** (recommended, lighter/faster on a 24 GB card) — checkpoint → `models/checkpoints/` (or `models/diffusion_models/`).
- **Wan 2.x I2V** (heavier, higher motion quality) — DiT → `models/diffusion_models/`, `umt5` text encoder → `models/text_encoders/`, Wan VAE → `models/vae/`, CLIP-Vision → `models/clip_vision/`.

If your ComfyUI version's node inputs differ from the bundled default graph, point `MYTHFORGE_VIDEO_WORKFLOW_LTXV` / `MYTHFORGE_VIDEO_WORKFLOW_WAN` at your own API-format workflow JSON (or drop it at `card_assets/video_workflows/<method>.json`). ~24 GB GPU recommended.

## Storage (rough)
One FLUX checkpoint ~24 GB · one SDXL ~7.7 GB · LoRAs ~20–300 MB each · face models ~1 GB · LTX-Video ~10 GB / Wan I2V ~16–32 GB. Minimal usable setup: one checkpoint (~24 GB).

## Troubleshooting
- **No checkpoints / models not in the selector** — ComfyUI running on :8188? Models in the right folder? Restart ComfyUI.
- **Out of VRAM / very slow** — use Schnell or SDXL, fewer LoRAs, and make sure ComfyUI isn't running with `--highvram` ([COMFYUI_SETUP.md](./COMFYUI_SETUP.md)). GPU tuning: [docs/HARDWARE_OPTIMIZATION_GUIDE.md](docs/HARDWARE_OPTIMIZATION_GUIDE.md).
