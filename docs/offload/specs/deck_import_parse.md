out: tests/test_deck_import_parse.py
model: qwen3:14b
include: deck_import.py
---
Write `tests/test_deck_import_parse.py`: pytest tests for the OFFLINE parsing helpers in the source above: `detect_source`, `_parse_text`, `_strip_line_metadata`, `_parse_archidekt`, `_cache_id`. Do NOT call `import_deck`, `_resolve`, any `_fetch_*` function, or anything that touches the network or Scryfall.

Read the real return types and field names (`RawDeck`, `DeckImportError`) off the source. Use only attribute names that appear there.

Cover:
1. `detect_source` on a Moxfield URL, an Archidekt URL, a ManaBox URL, and plain pasted decklist text: read the exact labels it returns off the source and assert those.
2. `_parse_text` on a small decklist like "1 Sol Ring\n4 Island\n" (also try "1x Sol Ring"): total card count and names land in the RawDeck exactly as the source's parsing logic dictates; blank lines and comment lines are tolerated if the source says so.
3. A decklist with a Commander section header: assert what the source does with it.
4. `_strip_line_metadata` on a line with a set code / collector number such as "(MH2) 123" and a foil marker: assert only what the source clearly implements.
5. `_cache_id` is deterministic (same input twice -> same value) and differs for different input.
6. Empty input to `_parse_text`: assert whether it raises `DeckImportError` or returns an empty deck, whichever the source does.
If an expected value is not certain from the source, assert a property instead of a value.
