out: tests/test_mana_pips_procedural.py
model: qwen3:8b
include: mana_pips.py
---
Write `tests/test_mana_pips_procedural.py`: pytest tests for the CPU-only, ComfyUI-free parts of the source above: `_procedural_silhouette`, `_radial`, `_compose_pip`, `_extract_silhouette`, `save_mana_pips`, `load_mana_pips`. Do NOT call `_flux_silhouette`, `_comfy_post`, `_comfy_get`, `_comfy_view`, or anything that needs a running ComfyUI. If `generate_mana_pips` or `generate_silhouette` could reach ComfyUI, monkeypatch `mana_pips._flux_silhouette` to return None so they take the procedural path; read the source to see whether that is enough, and skip those two functions if it is not clear.

Read exact signatures and return types off the source. Tiny images only.

Cover:
1. `_procedural_silhouette("dragon", "fire")` (use theme/subject strings of your choice) returns a PIL `Image.Image` and is deterministic: two calls give identical bytes (`tobytes()`).
2. `_radial` returns an image of the requested size.
3. `_compose_pip` returns an image; read from the source what size/mode it yields and assert that.
4. `save_mana_pips` then `load_mana_pips` on `tmp_path`: the loaded dict has the same keys that were saved, and each value is an image. Build the input the way the source shows.
5. `_extract_silhouette` on a plain grayscale image: assert it returns an image or None as the source allows (property only).
If an expected value is not certain from the source, assert a property instead.
