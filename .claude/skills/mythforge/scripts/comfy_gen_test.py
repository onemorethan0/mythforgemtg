#!/usr/bin/env python
"""
Generate ONE image through Myth Forge's real FLUX code path and report exposure
metrics — the fast way to verify an image-generation change without a full build.

Run from the repo root (so `import image_gen` works) with ComfyUI up on :8188.

Examples:
  python .claude/skills/mythforge/scripts/comfy_gen_test.py \
    --prompt "digital painting, a neon armored knight in a cyberpunk plaza" \
    --loras "kcyberpunk-02.safetensors:0.7,Neon_Cyberpunk_Detailer_FLUX_multi_trigger.safetensors:0.4" \
    --out /tmp/gen.png

  # no LoRAs, custom guidance/steps/seed:
  python .claude/skills/mythforge/scripts/comfy_gen_test.py -p "a frost mage" --guidance 3.0 --steps 30 --seed 7

Interpretation: mean brightness > 242 or stddev < 8 => the app would reject this as
overexposed/blank and fall back to Scryfall art. Healthy: brightness ~90-170, sd ~50-80.
Read the saved PNG to judge it visually.
"""
import argparse, json, os, time, urllib.request, uuid, sys
from pathlib import Path

# Running a script file puts the script's dir on sys.path, not the cwd. Add the
# cwd (expected to be the repo root) so `import image_gen` resolves.
sys.path.insert(0, os.getcwd())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", "-p", required=True)
    ap.add_argument("--loras", default="", help="comma list of filename:model_strength[:clip_strength]")
    ap.add_argument("--neg", default="", help="negative prompt (FLUX ignores it at cfg 1.0, but kept for SDXL)")
    ap.add_argument("--guidance", type=float, default=3.5)
    ap.add_argument("--steps", type=int, default=None)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--checkpoint", default=None, help="default: auto-detect FLUX dev")
    ap.add_argument("--comfy", default="http://127.0.0.1:8188")
    ap.add_argument("--out", default="/tmp/gen.png")
    args = ap.parse_args()

    try:
        import image_gen
    except Exception as e:
        sys.exit(f"Run from the repo root so 'import image_gen' works ({e})")
    from PIL import Image, ImageStat

    ckpt = args.checkpoint or "flux1-dev-fp8.safetensors"

    gen = image_gen.GenSettings(guidance=args.guidance, steps=args.steps)
    wf = image_gen._build_flux_workflow(ckpt, args.prompt, args.seed, negative=args.neg, gen=gen)

    specs = []
    for tok in [t for t in args.loras.split(",") if t.strip()]:
        parts = tok.split(":")
        fn = parts[0]
        sm = float(parts[1]) if len(parts) > 1 else 0.7
        sc = float(parts[2]) if len(parts) > 2 else 0.0
        specs.append({"filename": fn, "model_strength": sm, "clip_strength": sc})
    if specs:
        wf = image_gen._insert_loras(wf, "1", specs)

    out_dir = image_gen._COMFY_OUTPUT_DIR if hasattr(image_gen, "_COMFY_OUTPUT_DIR") else \
        Path(r"C:\Users\rvn92\Documents\ComfyUI\output")

    def post(p, d):
        return json.loads(urllib.request.urlopen(urllib.request.Request(
            args.comfy + p, data=json.dumps(d).encode(),
            headers={"Content-Type": "application/json"})).read())

    def get(p):
        return json.loads(urllib.request.urlopen(args.comfy + p).read())

    print(f"checkpoint={ckpt} guidance={args.guidance} steps={args.steps or 'default'} "
          f"loras={[s['filename'] for s in specs]}")
    try:
        pid = post("/prompt", {"prompt": wf, "client_id": str(uuid.uuid4())})["prompt_id"]
    except urllib.error.HTTPError as e:
        sys.exit(f"ComfyUI rejected the workflow: {e.read()[:400]}")
    t = time.time()
    while time.time() - t < 240:
        e = get(f"/history/{pid}").get(pid)
        if e and e.get("status", {}).get("completed"):
            for node in e["outputs"].values():
                for im in node.get("images", []):
                    src = out_dir / im.get("subfolder", "") / im["filename"]
                    img = Image.open(src).convert("RGB")
                    img.save(args.out)
                    s = ImageStat.Stat(img)
                    br, sd = sum(s.mean) / 3, sum(s.stddev) / 3
                    bad = br > 242 or sd < 8
                    print(f"-> {args.out}  brightness={br:.1f} stddev={sd:.1f}  "
                          f"{'<<< BAD (app would reject)' if bad else 'OK'}")
                    return
        time.sleep(2)
    sys.exit("Timed out waiting for ComfyUI (240s)")

if __name__ == "__main__":
    main()
