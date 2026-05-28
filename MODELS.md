# Myth Forge Models & LoRAs Setup Guide

Complete guide to downloading and setting up image generation models and LoRAs.

## Quick Overview

Myth Forge generates MTG card art using:
- **Checkpoints**: FLUX, SDXL, or SD 3.5 base models
- **LoRAs**: Style enhancement models for MTG aesthetics
- **Optional**: Face conditioning models for character art

## System Requirements for Models

| Model | VRAM Needed | RAM | Notes |
|-------|------------|-----|-------|
| FLUX 1 Dev | 24GB | 8GB | Best quality, slower |
| FLUX 1 Schnell | 16GB | 8GB | Good balance (recommended) |
| SDXL (Illustrious) | 8GB | 8GB | Anime/fantasy style |
| SD 3.5 Large | 12GB | 8GB | High quality |

**Total LoRAs**: ~500MB - 2GB combined

## Quick Setup: Automated Model Downloader

The easiest way to get started:

**Windows:**
```bash
download-models.bat
```

**Mac/Linux:**
```bash
python download-models.py
```

This interactive script will guide you through downloading recommended models with a few simple choices. It handles everything automatically!

---

## Manual Setup: Download a Checkpoint

Or choose ONE checkpoint manually to start:

### Option A: FLUX 1 Schnell (Recommended for Balance)
**Best for**: First-time setup, good quality + speed

1. Visit: https://huggingface.co/black-forest-labs/FLUX.1-schnell
2. Click "Files and versions"
3. Download `flux1-schnell.safetensors` (~24GB)
4. Save to: `ComfyUI/models/checkpoints/`

**Alternative (faster download):**
```bash
cd ComfyUI/models/checkpoints
huggingface-cli download black-forest-labs/FLUX.1-schnell \
  --include "*.safetensors" --local-dir .
```

### Option B: FLUX 1 Dev (Best Quality)
**Best for**: Maximum quality (slower)

1. Visit: https://huggingface.co/black-forest-labs/FLUX.1-dev
2. Download `flux1-dev.safetensors` (~24GB)
3. Save to: `ComfyUI/models/checkpoints/`

### Option C: Illustrious XL (SDXL)
**Best for**: Anime/fantasy art styles

1. Visit: https://civitai.com/models/296424/illustrious-xl
2. Click "Download" button
3. Save to: `ComfyUI/models/checkpoints/`

## Step 2: Download LoRAs (Optional but Recommended)

LoRAs enhance the MTG aesthetic. Add them for better results.

### MTG Style LoRAs

#### 1. MTG v2 (Core MTG look)
- **URL**: https://civitai.com/models/669671
- **What to download**: Any version's `lora.safetensors`
- **Rename to**: `mtg_v2_lora.safetensors`
- **Size**: ~500MB
- **Strength**: 0.80 (auto-set)

**Download steps:**
1. Go to link above
2. Click "Download" on latest version
3. Save file
4. Rename to `mtg_v2_lora.safetensors`
5. Move to `ComfyUI/models/loras/`

#### 2. MTG Composition (Better layouts)
- **URL**: https://civitai.com/models/567735
- **Rename to**: `mtg_composition_lora.safetensors`
- **Size**: ~400MB
- **Strength**: 0.55

#### 3. Realism (Realistic card art)
- **URL**: https://civitai.com/models/680417
- **Rename to**: `xlabs_realism_lora.safetensors`
- **Size**: ~300MB
- **Strength**: 0.70

#### 4. Darkness (Dark/horror themes)
- **URL**: https://civitai.com/models/300898
- **Rename to**: `darkness_lora.safetensors`
- **Size**: ~400MB
- **Strength**: 0.75

#### 5. Sketch (Hand-drawn styles)
- **URL**: https://civitai.com/models/730615
- **Rename to**: `sketch_lora.safetensors`
- **Size**: ~300MB
- **Strength**: 0.50

### Automated LoRA Download

**Coming Soon**: Script to auto-download recommended LoRAs

```bash
python scripts/download-models.py
```

## Step 3: (Optional) Face Conditioning Models

For using character photos in card generation:

### PuLID (For FLUX - Recommended)

1. Install ComfyUI extension:
   ```bash
   cd ComfyUI/custom_nodes
   git clone https://github.com/jojopapricardo/ComfyUI-PuLID.git
   cd ComfyUI-PuLID
   pip install -r requirements.txt
   ```

2. Download models:
   - Visit: https://huggingface.co/instantx/PuLID
   - Download to: `ComfyUI/models/pulid/`

3. Restart ComfyUI

### ReActor (For SDXL/SD3.5)

1. Install ComfyUI extension:
   ```bash
   cd ComfyUI/custom_nodes
   git clone https://github.com/Gourieff/comfyui-reactor.git
   pip install insightface onnxruntime
   ```

2. Download model:
   ```bash
   cd ComfyUI/models/reactor
   wget https://github.com/Gourieff/Assets/raw/main/models/inswapper_128.pth
   ```

3. Restart ComfyUI

## Step 4: Verify Installation

In Myth Forge:

1. Start the app: `python server.py`
2. Open http://localhost:8000
3. Create a new deck
4. Go to "Theme" step
5. If you see your checkpoint in the model selector → ✅ Success!

## Troubleshooting

### "No checkpoints found"
- **Check**: ComfyUI is running on `localhost:8188`
- **Check**: Models are in `ComfyUI/models/checkpoints/`
- **Fix**: Restart ComfyUI after adding models

### Models not appearing in UI
1. Ensure ComfyUI is **running**
2. Restart ComfyUI (`Ctrl+C` then run again)
3. Refresh browser (F5)

### Out of VRAM error
- Use a smaller checkpoint (Schnell instead of Dev)
- Use SDXL instead of FLUX
- Close other GPU applications
- Reduce batch size in Myth Forge settings

### Slow generation
- Use FLUX Schnell instead of Dev
- Use SDXL instead of FLUX
- Reduce LoRA count (use 1-2 instead of all)

## Storage Requirements

| Component | Size |
|-----------|------|
| FLUX checkpoint | ~24GB |
| SDXL checkpoint | ~7.5GB |
| All 5 LoRAs | ~2GB |
| VAE models | ~500MB |
| Face models | ~1GB |
| **Total (all)** | ~40GB |
| **Minimal** | ~25GB |

**Tip**: Use external SSD for models to save space

## Performance Tips

### For Speed (Generation under 10s)
- Use FLUX Schnell
- Use 1-2 LoRAs maximum
- Keep batch size at 1

### For Quality (Best results)
- Use FLUX Dev
- Use 3-4 LoRAs
- Run overnight for batch jobs

### For Memory (Limited VRAM)
- Use SDXL + Illustrious
- Use 1 LoRA only
- Disable face conditioning

## Advanced: Custom Models

You can also use your own LoRAs or checkpoints:

1. Download from CivitAI or HuggingFace
2. Place in appropriate folder:
   - Checkpoints: `ComfyUI/models/checkpoints/`
   - LoRAs: `ComfyUI/models/loras/`
3. Restart ComfyUI
4. Models will auto-appear in selectors

## Model Update Checklist

- [ ] Download at least one checkpoint
- [ ] (Optional) Download MTG LoRAs
- [ ] (Optional) Install PuLID/ReActor for face features
- [ ] Verify models appear in Myth Forge
- [ ] Generate test deck to ensure quality

## Next Steps

1. **Quick Start**: Download FLUX Schnell, skip LoRAs
2. **Enhanced**: Add MTG v2 + Composition LoRAs
3. **Quality**: Switch to FLUX Dev, add all 5 LoRAs
4. **Advanced**: Set up face conditioning for character art

## Getting Help

- **ComfyUI Issues**: https://github.com/comfyanonymous/ComfyUI
- **LoRA Questions**: https://civitai.com
- **Myth Forge Issues**: https://github.com/onemorethan0/mythforgemtg

---

**Happy building!** The app works with any checkpoint you have. Start with one, add LoRAs when you want to refine the aesthetic. ⚔️
