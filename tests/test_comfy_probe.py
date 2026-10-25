"""comfy_probe: parallel port probe with a short cache (offline - the probe is stubbed)."""
import comfy_probe


def _stub(monkeypatch, alive):
    calls = []

    def probe(port):
        calls.append(port)
        return port in alive
    monkeypatch.setattr(comfy_probe, "_probe", probe)
    comfy_probe.reset()
    return calls


def test_finds_the_first_live_candidate_and_caches_it(monkeypatch):
    calls = _stub(monkeypatch, alive={8000})
    assert comfy_probe.detect_comfy_base() == "http://127.0.0.1:8000"
    n = len(calls)
    assert comfy_probe.detect_comfy_base() == "http://127.0.0.1:8000"
    assert len(calls) == n                       # served from cache, no second probe


def test_not_running_falls_back_to_default_and_reset_reprobes(monkeypatch):
    calls = _stub(monkeypatch, alive=set())
    assert comfy_probe.detect_comfy_base() == comfy_probe.DEFAULT_BASE
    n = len(calls)
    comfy_probe.reset()                          # e.g. we just launched ComfyUI
    comfy_probe.detect_comfy_base()
    assert len(calls) == 2 * n


def test_a_missing_answer_expires_sooner_than_a_found_one():
    assert comfy_probe.MISSING_TTL < comfy_probe.FOUND_TTL
