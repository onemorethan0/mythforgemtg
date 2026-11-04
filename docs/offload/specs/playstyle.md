out: tests/test_playstyle_pure.py
model: qwen3:8b
include: playstyle.py
---
Write `tests/test_playstyle_pure.py`: pytest tests for `get_slot_adjustments` and `resolve_themes` in `playstyle.py` shown above. Do NOT call `prompt_playstyle` (it reads stdin).

Read the constants (`DEFAULT_SLOTS`, the playstyle table) and the exact signature/return of `resolve_themes` off the source. Cover:
1. `get_slot_adjustments` for every playstyle key present in the source's table returns a dict whose values are ints; an unknown key behaves as the source says (read it; assert exactly that).
2. The adjustments, applied to `DEFAULT_SLOTS`, never produce a negative slot count (derive from the code; if the source does not guarantee it, skip this one).
3. `resolve_themes` with an empty input, with one theme, and with a duplicate: assert exactly what the code does, nothing more.
If an expected value is not certain from the source, assert a property instead.
