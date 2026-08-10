"""The services.py <- server.py progress-emitter wiring.

`services` cannot import `server._push` (circular), so the coupling is inverted: services
holds a module-level emitter defaulting to None, and server registers `_push` at import
time. Nothing tested that. Delete the registration line and ComfyUI startup progress
silently stops reaching the build UI while every other test still passes.
"""

import server  # noqa: F401  -- imported for its side effect: it registers the emitter
import services


def _restore(original):
    services.set_progress_emitter(original)


def test_emitter_defaults_to_noop():
    """A no-op emitter must not raise — services is usable with no server at all."""
    original = services._progress_emitter
    try:
        services.set_progress_emitter(None)
        services._emit_progress("job1", "progress", "{}")   # must not raise
    finally:
        _restore(original)


def test_emitter_forwards_when_registered():
    received = []
    original = services._progress_emitter
    try:
        services.set_progress_emitter(
            lambda job_id, event, data: received.append((job_id, event, data))
        )
        services._emit_progress("job1", "progress", "hello")
    finally:
        # Restore the ORIGINAL, not None. Resetting to None looks like cleanup but is
        # actually clobbering: `server` is already imported, so a later `import server`
        # is a cached no-op that cannot re-register, and the next test sees None.
        _restore(original)
    assert received == [("job1", "progress", "hello")]


def test_emit_is_silent_without_a_job_id():
    """`_emit_progress` guards on job_id, so a service call outside a build stays quiet."""
    received = []
    original = services._progress_emitter
    try:
        services.set_progress_emitter(
            lambda job_id, event, data: received.append((job_id, event, data))
        )
        services._emit_progress("", "progress", "no job")
    finally:
        _restore(original)
    assert received == []


def test_server_registers_its_push():
    """The wiring this whole file exists to protect."""
    assert services._progress_emitter is not None, "server.py stopped registering its emitter"
    assert services._progress_emitter.__name__ == "_push"
    assert services._progress_emitter is server._push
