#!/usr/bin/env python
"""
Inspect installed LoRA safetensors metadata — confirm a LoRA is what you think
before wiring it into a preset. Reads only the header (fast, no full load).

  python .claude/skills/mythforge/scripts/inspect_lora.py kcyberpunk   # match by fragment
  python .claude/skills/mythforge/scripts/inspect_lora.py --all
  python .claude/skills/mythforge/scripts/inspect_lora.py --dir "D:/some/loras" neon

What to check:
  - architecture == flux-1-dev/lora  (for FLUX dev; SDXL LoRAs won't work on FLUX)
  - dim / alpha: alpha/dim is the internal scale. dim2/alpha16 => ~8x, potent at low strength.
  - TE trained: if keys start with lora_te*, the text encoder was trained => clip_strength matters.
    Otherwise it's UNET-only => set clip_strength 0.
  - trigger: ss_tag_frequency often reveals the trained trigger token(s).
"""
import argparse, json, struct, sys
from pathlib import Path

DEFAULT_DIR = Path(r"C:\Users\rvn92\Documents\ComfyUI\models\loras")

def read_header(fp: Path):
    with open(fp, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        return json.loads(f.read(n))

def detect_arch(keys):
    """Determine the REAL architecture from tensor key names — metadata labels
    (modelspec.architecture / ss_base_model_version) are often wrong or missing."""
    s = " ".join(keys[:40])
    if "double_blocks" in s or "single_blocks" in s or "transformer.single_transformer_blocks" in s \
       or "transformer.transformer_blocks" in s:
        return "FLUX"
    if "diffusion_model.layers" in s and "adaLN" in s:
        return "z-image / Lumina (NOT FLUX)"
    if "input_blocks" in s or "down_blocks" in s or "lora_te2" in s:
        return "SD/SDXL (NOT FLUX)"
    return "unknown — inspect keys"

def describe(fp: Path):
    hdr = read_header(fp)
    meta = hdr.get("__metadata__", {})
    keys = [k for k in hdr if k != "__metadata__"]
    te = any(("lora_te" in k) or (".text_" in k) or ("text_encoder" in k) for k in keys)
    tags = meta.get("ss_tag_frequency", "")
    print(f"\n=== {fp.name} ({fp.stat().st_size // (1024*1024)} MB) ===")
    print(f"  REAL arch (from keys): {detect_arch(keys)}")
    print(f"  metadata label        : {meta.get('modelspec.architecture')}  base={meta.get('ss_base_model_version')}  (may be wrong/missing)")
    print(f"  network      : {meta.get('ss_network_module')}  dim={meta.get('ss_network_dim')} alpha={meta.get('ss_network_alpha')}")
    print(f"  tensors      : {len(keys)}   text-encoder trained: {te}  (clip_strength {'matters' if te else 'no-op -> 0'})")
    if tags:
        print(f"  tag_frequency: {str(tags)[:200]}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fragment", nargs="?", default="", help="substring to match in filenames")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    args = ap.parse_args()

    d = Path(args.dir)
    if not d.exists():
        sys.exit(f"loras dir not found: {d}")
    files = sorted(d.glob("*.safetensors"))
    if not args.all:
        files = [f for f in files if args.fragment.lower() in f.name.lower()]
    if not files:
        sys.exit(f"no LoRA matched {args.fragment!r} in {d}")
    for f in files:
        try:
            describe(f)
        except Exception as e:
            print(f"\n=== {f.name} ===\n  (could not read header: {e})")

if __name__ == "__main__":
    main()
