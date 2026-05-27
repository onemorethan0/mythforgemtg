# Myth Forge Installation Guide

**Myth Forge** is an MTG Commander Deck Builder that generates themed card names and art using AI.

## Quick Start

### Windows Users
```bash
# Run the installer
install.bat
```

### macOS/Linux Users
```bash
# Run the installer
python install.py
```

## System Requirements

### Essential
- **Python 3.8+** — [Download](https://www.python.org/downloads/)
- **Node.js 18+** — [Download](https://nodejs.org/)
- **4GB RAM minimum** (8GB+ recommended)
- **2GB disk space** for dependencies

### Optional (But Highly Recommended)
- **Ollama** — Local LLM for card theming — [Download](https://ollama.ai)
- **ComfyUI** — Image generation workflows — [GitHub](https://github.com/comfyanonymous/ComfyUI)
- **GPU** (NVIDIA/AMD/Intel) — For faster image generation

## Installation Methods

### Method 1: Automated Installation (Recommended)

#### Windows
1. Open Command Prompt in the project directory
2. Run: `install.bat`
3. Follow the on-screen prompts

#### macOS/Linux
1. Open Terminal in the project directory
2. Run: `python install.py`
3. Follow the on-screen prompts

### Method 2: Manual Installation

#### 1. Install Python Dependencies
```bash
python -m pip install -r requirements.txt
```

#### 2. Install Frontend Dependencies
```bash
cd frontend
npm install
npm run build
cd ..
```

#### 3. Create Directories
```bash
mkdir data renders scryfall_cache
```

#### 4. Start the Server
```bash
python server.py
```

Open your browser to: **http://localhost:8000**

## Starting the Application

### After Initial Installation

#### Windows
Double-click `start-mythforge.bat` or run:
```bash
python server.py
```

#### macOS/Linux
Run the startup script:
```bash
bash start-mythforge.sh
```

Or directly:
```bash
python server.py
```

The application will be available at: **http://localhost:8000**

## Optional Setup

### Ollama (For Better Card Theming)

Ollama provides local AI models for card name and flavor text generation.

#### Windows/macOS
- Download installer from [ollama.ai](https://ollama.ai)
- Install and run

#### Linux
```bash
curl https://ollama.ai/install.sh | sh
```

#### Pull a Model
```bash
ollama pull qwen2:7b
```

The app will auto-detect Ollama. If running on a different port/address, update `server.py`.

### ComfyUI (For Image Generation)

ComfyUI provides the image generation pipeline using Stable Diffusion, FLUX, and other models.

Follow the official setup guide: [ComfyUI Installation](https://github.com/comfyanonymous/ComfyUI#installation)

Key steps:
1. Clone the repository
2. Install Python dependencies
3. Download required models (Checkpoints, VAE, etc.)
4. Start ComfyUI

The Myth Forge app will connect to ComfyUI automatically on `localhost:8188`.

### GPU Support (Optional)

For faster image generation, install GPU drivers:

#### NVIDIA (CUDA)
- Download: [NVIDIA CUDA Toolkit](https://developer.nvidia.com/cuda-toolkit)
- Follow installation instructions
- Install CUDNN if needed

#### AMD (ROCm)
- Download: [AMD ROCm](https://rocmdocs.amd.com)
- Follow OS-specific installation

#### Intel (OneAPI)
- Download: [Intel OneAPI](https://www.intel.com/content/www/us/en/develop/tools/oneapi/base-toolkit.html)
- Follow installation instructions

## Development

### Building Frontend After Code Changes
```bash
make frontend-build
```

Or manually:
```bash
cd frontend
npm run build
cd ..
```

Then refresh your browser (Ctrl+Shift+R on Windows).

### Development Server (Hot Reload)
For active frontend development:
```bash
make frontend-dev
```

This starts a Vite dev server on `localhost:5173` with hot reload.

### Useful Make Commands
```bash
make frontend-build    # Build for production
make frontend-dev      # Start dev server with hot reload
make rebuild           # Clean rebuild
```

## Troubleshooting

### "Python not found"
- Install Python 3.8+ from [python.org](https://www.python.org)
- **Important**: Check "Add Python to PATH" during installation
- Restart Command Prompt/Terminal after installing

### "Node.js/npm not found"
- Install Node.js 18+ from [nodejs.org](https://nodejs.org)
- Choose the LTS version
- Restart Command Prompt/Terminal after installing

### "Failed to install dependencies"
```bash
# Try clearing npm cache
npm cache clean --force

# Then retry
npm install
```

### Frontend changes don't appear in browser
1. Make sure you rebuilt: `npm run build` (from `frontend/` directory)
2. Hard refresh browser: `Ctrl+Shift+R` (Windows) or `Cmd+Shift+R` (Mac)
3. Check that `frontend/dist/` was updated: `ls -la frontend/dist/`

### Server won't start
1. Check that port 8000 isn't in use: 
   - Windows: `netstat -ano | findstr :8000`
   - macOS/Linux: `lsof -i :8000`
2. Try a different port: `python server.py --port 8001`

### ComfyUI not detected
- Ensure ComfyUI is running on `localhost:8188`
- Check that it's accessible: `curl http://localhost:8188/api/`
- Update the API URL in `server.py` if using a different address

### Ollama not detected
- Ensure Ollama is running
- Check that `qwen2:7b` is pulled: `ollama list`
- On different systems, may need to update the API URL in `server.py`

## Architecture

```
mythforge/
├── server.py              # Flask API server
├── image_gen.py           # Image generation (ComfyUI orchestration)
├── themer.py              # Card theming (Ollama integration)
├── frontend/              # React + Vite
│   ├── src/               # Source code
│   ├── dist/              # Production build (served by Flask)
│   └── package.json       # Frontend dependencies
├── requirements.txt       # Python dependencies
└── data/                  # Generated decks & renders
```

## Performance Tips

### Faster Builds
- Use SSD for project directory
- Keep `node_modules` on same drive
- Use dedicated GPU if available

### Better Generation Quality
- Run Ollama with more VRAM: `OLLAMA_NUM_GPU=1 ollama serve`
- Use larger ComfyUI models (more VRAM needed)
- Set image generation to "quality" mode in app

### Memory Usage
- ComfyUI: 6GB+ VRAM for FLUX, 4GB+ for SDXL
- Ollama: 4GB+ RAM for larger models
- Ensure at least 8GB system RAM available

## Getting Help

- Check the [GitHub Issues](https://github.com/onemorethan0/mythforgemtg/issues)
- Review the [README](./README.md) for more details
- Check `server.log` for errors

## Next Steps

1. **Start the app**: Run installer or `python server.py`
2. **Open browser**: Visit http://localhost:8000
3. **Create a deck**: Choose a commander and follow the workflow
4. **Explore features**: Adjust themes, regenerate cards, export decks

Enjoy building!

---

**Myth Forge** by OneMoreThan0 — Generate legendary decks with AI ⚔️
