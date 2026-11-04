out: tests/test_api_cards_pure.py
model: qwen3:14b
include: api/cards.py
---
Write `tests/test_api_cards_pure.py`: pytest tests for the pure helpers in `api/cards.py` shown above: `_safe_name`, `_replace_card_self_ref`, `_is_single_card`, `_carry_provenance`, `_normalize_mana_cost`, `_parse_mana_cost`.

Import with `from api import cards`. Do not call any function that touches the filesystem, the network, VRAM or ComfyUI (`_free_all_vram`, `_download_art_to`, `_setup_deck_pips`, `_load_source_deck`, `_write_cancelled_deck`). Read exact behaviour off the docstrings and code; the docstrings describe several rules precisely (brace-free costs are normalized; a hybrid like {2/W} counts as the highest half; `_is_single_card` checks `mode` and `playstyle == "Single Card"`).

For each function, write 2-4 small tests with concrete inputs whose results you can derive by reading the code. `_parse_mana_cost` returns `(mana_value, colors)`: derive both from the code. If you cannot derive an expected value with certainty, assert a property (type, non-negative, idempotence: `_normalize_mana_cost(_normalize_mana_cost(x)) == _normalize_mana_cost(x)`) instead.
