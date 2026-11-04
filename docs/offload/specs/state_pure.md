out: tests/test_api_state_pure.py
model: qwen3:8b
include: api/state.py
---
Write `tests/test_api_state_pure.py`: pytest tests for the in-memory helpers in `api/state.py` shown above: `_require_job_id`, `_check_rate_limit`, `_push`, `_mark_job_error`, `_finalize_job`, `_serializable_job`, `_trim_in_memory_jobs`, `_get_deck_regen_lock`. Do NOT call `_load_deck_from_disk`, `_backfill_quality` or `_cleanup_expired_jobs` (disk and time dependent).

Import with `from api import state`. Containers such as `state._jobs` are mutated in place: use `monkeypatch.setitem` / `patch.dict(state._jobs, {...}, clear=True)` so each test starts clean and restores state; never rebind them. Read every constant, container name and exact behaviour off the source (limits, key names, event queue shape); do not guess names.

Cover at least: invalid job ids rejected by `_require_job_id` and a valid one returned unchanged (read the validation rule off the source); `_check_rate_limit` allows up to the limit then refuses, and a different client id is independent (clear whatever container holds the counters first); `_mark_job_error` sets the job's error status as the source shows; `_serializable_job` returns something JSON-serialisable (`json.dumps` must succeed) and omits non-serialisable members the source says it strips; `_get_deck_regen_lock` returns the same lock object for the same id and a different one for another id.
If an expected value is not certain from the source, assert a property instead.
