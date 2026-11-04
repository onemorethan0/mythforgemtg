out: tests/test_set_symbol_pure.py
model: qwen3:8b
include: set_symbol.py
---
Write `tests/test_set_symbol_pure.py`: pytest tests for the CPU-only drawing helpers in `set_symbol.py` shown above. Do NOT call `generate_set_symbol`, `_render_relief`, or `save_set_symbol` unless the source clearly needs no ComfyUI/network for them; skip them otherwise.

Cover:
1. `_hue_to_rgb` returns a 3-tuple of ints each in 0..255 for several hues (0.0, 0.33, 0.9, 1.0); `_darken` of a colour returns a tuple with each channel <= the original and the same length.
2. `_polygon_points` / `_star_points`: read their signatures off the source; the number of points returned matches what the code's loop produces (derive it from the code; if unsure, assert only `len(points) > 2` and that every point is a 2-tuple of numbers).
3. Each `_draw_shape_N_*` function runs on a small RGBA `Image.new("RGBA", (64, 64))` with an `ImageDraw.Draw` and colours of your choice without raising, and changes at least one pixel from fully transparent (use `Image.getbbox()` on the alpha channel: it must not be None). Discover the shape functions with `getattr` over `dir(set_symbol)` names that start with `_draw_shape_` rather than listing them by hand.
4. `_normalize_rarity`: read the mapping in the source and assert it for the rarities shown plus an unknown/empty input exactly as the code does.
5. `colorize_by_rarity(symbol, rarity)` on a small grayscale-or-RGBA symbol image returns a PIL image of the same size for each rarity the source handles (read its signature carefully).
If an expected value is not certain from the source, assert a property instead.
