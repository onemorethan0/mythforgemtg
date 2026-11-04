out: tests/test_buildable_pure.py
model: qwen3:8b
include: buildable.py
---
Write `tests/test_buildable_pure.py`: pytest tests for the pure functions in `buildable.py` shown above: `classify_roles`, `is_commander_eligible`, `_is_basic_land`, `_in_identity`, `_legal`, `score_commander`. Do NOT call `find_buildable` (it needs a Scryfall client).

Cards are plain dicts; read from the source exactly which keys each function reads (e.g. `oracle_text`, `type_line`, `color_identity`, `legalities`) and build minimal dicts with only those keys. Derive every expected value by reading the code; if a regex or constant decides it, use an input that clearly matches or clearly does not. Do not encode any Magic rules knowledge beyond what the code itself does.

Write 2-3 tests per function, e.g. a legendary creature is commander-eligible and a plain creature is not; "Basic Land — Forest" is a basic land; a card whose identity is outside the commander's identity is excluded; `score_commander` returns a dict (assert its keys and value types as the source shows).
