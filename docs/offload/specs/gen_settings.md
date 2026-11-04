out: tests/test_gen_settings_models.py
model: qwen3:8b
include: api/models.py
---
Write `tests/test_gen_settings_models.py`: pytest tests for the pure helpers in the source above: `_resolve_gen_settings`, `_gen_settings_to_dict`, `_resolve_gen_settings_reusing`, and the pydantic request models `SearchRequest`, `GenSettingsModel`.

Import with `from api import models`. Read the real signatures, defaults and return types off the source; do not guess them. Do not construct `BuildRequest` or the other large request models.

Cover, asserting only what the source's code makes certain:
1. `_resolve_gen_settings(None)` returns a `GenSettings` instance (the source shows where it comes from) and does not raise.
2. `_gen_settings_to_dict(None)` returns a dict (or whatever the source returns for None).
3. A round trip: build a `GenSettingsModel` with a couple of non-default fields, resolve it, and assert those fields survive on the result.
4. `_gen_settings_to_dict` of a model includes the non-default fields you set.
5. `GenSettingsModel` and `SearchRequest` reject a wrong-typed field with `pydantic.ValidationError` (pick a field the source types as int or str).
If a helper's behaviour is not obvious from the source, assert type/non-crash instead of a value.
