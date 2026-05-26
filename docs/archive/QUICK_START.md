# Quick Start Guide

## Hardware Notes

This application is **developed on RTX 3090 + 32GB RAM + Ryzen 5800X3D** and performance expectations are set for that hardware.

**Expected timing** (100-card deck):
- **With FLUX Schnell**: 15-20 minutes
- **With FLUX Dev**: 60-75 minutes (premium quality, slower)

**If you have smaller GPU:**
- Builds will take longer but still work
- FLUX generation may fall back to Scryfall artwork
- Theming will use smaller Ollama models automatically

See `HARDWARE_OPTIMIZATION_GUIDE.md` for full compatibility matrix.

---

## Server Startup

```bash
cd mtg_deck_builder
python server.py
```

You should see:
```
======================================================================
COMMANDER DECK BUILDER - STARTUP CHECKS
======================================================================

[startup] Checking Ollama connectivity...
  [startup] [OK] Ollama reachable - 3 model(s) loaded
  [startup] [OK] Default model available: qwen3:14b
======================================================================

INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

If you see `[!] Default model missing: qwen3:14b`, pull the model first:
```bash
ollama pull qwen3:14b
```

---

## API Quick Reference

### Build a New Deck

```bash
curl -X POST http://localhost:8000/api/deck/build \
  -H "Content-Type: application/json" \
  -d '{
    "commander_name": "Elspeth, Sun's Nemesis",
    "playstyle": "control",
    "art_style": "mtg_fantasy",
    "generate_art": true,
    "model_speed": "quality"
  }'
```

Response: `{"job_id": "abc123..."}`

### Check Build Progress

```bash
curl http://localhost:8000/api/deck/abc123/status
```

### Get Completed Deck

```bash
curl http://localhost:8000/api/deck/abc123
```

### Delete a Deck

```bash
curl -X DELETE http://localhost:8000/api/deck/abc123
```

### Delete Multiple Decks

```bash
curl -X POST http://localhost:8000/api/decks/delete-batch \
  -H "Content-Type: application/json" \
  -d '{"job_ids": ["abc123", "def456"]}'
```

### Re-theme a Deck (new names, prompts, flavor text — keep existing art)

```bash
curl -X POST http://localhost:8000/api/deck/abc123/retheme \
  -H "Content-Type: application/json" \
  -d '{
    "art_theme": "frozen tundra shaman"
  }'
```

### Rebuild Card Art (new art generation — keep existing themes)

> **ComfyUI must be running** for new images to generate.  
> If ComfyUI is offline, existing FLUX art is reused automatically (no quality loss).

```bash
curl -X POST http://localhost:8000/api/deck/abc123/rebuild \
  -H "Content-Type: application/json" \
  -d '{
    "art_style": "anime_illustrated",
    "model_speed": "fast"
  }'
```

### Regenerate Specific Cards Only

```bash
curl -X POST http://localhost:8000/api/deck/abc123/regen-cards \
  -H "Content-Type: application/json" \
  -d '{
    "card_names": ["Sol Ring", "Swords to Plowshares"],
    "art_style": "watercolor"
  }'
```

### Cancel a Build

```bash
curl -X POST http://localhost:8000/api/deck/abc123/cancel
```

---

## Frontend

Open your browser to:
```
http://localhost:8000/
```

---

## Monitoring

### Memory Usage
- Expected: 1-2 GB while running
- Cleanup runs hourly: look for `[cleanup] Expired N old job(s)`

### Rate Limiting
- Limit: 5 builds per 60 seconds per IP
- Error 429: Wait 60 seconds before retrying

### VRAM Management
- Automatic Ollama eviction before FLUX loading
- Automatic cleanup on cancel (background task)
- VRAM polling ensures physical memory freed (not just model unloaded)

---

## Troubleshooting

### "Ollama not reachable"
- Check Ollama is running: `ollama serve`
- Check address is correct (default: http://127.0.0.1:11434)

### "ComfyUI not reachable" during art generation
- Check ComfyUI is running
- Check address is correct (default: http://127.0.0.1:8188)
- Check FLUX checkpoint is loaded in ComfyUI

### Memory growing
- Run: `curl -X POST http://localhost:8000/api/cleanup-expired-jobs` (if endpoint exists)
- Or: Restart server (cleanup runs on startup)

### Rate limit (429) errors
- Expected during stress testing
- Wait 60 seconds between builds
- Or test from different IP addresses

---

## Art Styles

Pass `art_style` in any build/rebuild request. Available presets:

| Key | Label | LoRA Required |
|-----|-------|---------------|
| `mtg_fantasy` | MTG Fantasy | `df_style_v1.1.safetensors` |
| `photorealism` | Photorealism | `xlabs_realism_lora.safetensors` |
| `cyberpunk` | Cyberpunk | `neon_noir_*.safetensors` |
| `desert_punk` | Desert Punk | `retrofuture_*.safetensors` |
| `anime` | Anime / Manga | `flatcolor_anime_flux.safetensors` — flat cel-shaded |
| `anime_illustrated` | Anime Illustrated | `semi_realistic_anime_flux.safetensors` — detailed shading & depth |
| `anime_soft` | Anime Artbook | `softserve_anime_flux.safetensors` — painterly artbook quality |
| `art_nouveau` | Art Nouveau | `mucha_style_flux.safetensors` |
| `gothic_horror` | Gothic Horror | `Dark_Gothic_Horror*.safetensors` |
| `watercolor` | Watercolor | `WATERCOLOR-lora*.safetensors` |
| `steampunk` | Steampunk | `SteampunkIllustration_v1.safetensors` |
| `oil_painting` | Oil Painting | *(prompt-only, no LoRA)* |
| `pixel_art` | Pixel Art | `Pixel_Art_FLUX.safetensors` |
| `eldritch` | Eldritch Horror | `Eldritch_Comics_for_Flux*.safetensors` |
| `stained_glass` | Stained Glass | `Stained_Glass_Style.safetensors` |

Drop `.safetensors` files in `ComfyUI/models/loras/` — they activate automatically by filename fragment match. Run `GET /api/art-styles` to see which LoRAs are currently detected.

---

## Key Features

✅ **Memory Safe** — Automatic cleanup every hour, no leaks  
✅ **Resource Protected** — Rate limiting prevents exhaustion  
✅ **VRAM Smart** — Two-stage eviction ensures CUDA memory freed  
✅ **Cancellable** — Background VRAM eviction prevents freeze  
✅ **Deletable** — Single and batch deck deletion  
✅ **Non-Blocking** — Fast startup, doesn't wait for model pulls  
✅ **Art Preserved** — Rebuild reuses existing FLUX art if ComfyUI is offline  
✅ **Themed Borders** — Free-text border theme tints the card chrome in 7 palettes  

---

## Need Help?

Check the documentation files:
- `DEPLOYMENT_READY.md` — Full deployment guide
- `FINAL_IMPROVEMENTS_SUMMARY.md` — Technical improvements
- `CODE_REVIEW.md` — Detailed code analysis
