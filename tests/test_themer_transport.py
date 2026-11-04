"""themer's LLM transport: what is actually sent to llama-swap / Ollama, and how replies are read.

Pinned because this has already regressed once: the llama.cpp path forwarded only `top_p`, so batch
theming ran with no repetition control and produced stem-clustered names ("Ashen Citadel" ->
"Lost Ashen Citadel" -> "Shattered Ashen Citadel"). Every request is captured through a fake
`requests`; nothing here talks to a model."""
from __future__ import annotations

import json

import pytest

import themer

MSGS = [{"role": "user", "content": "hi"}]
SAMPLERS = dict(top_p=0.9, top_k=40, repeat_penalty=1.1, frequency_penalty=0.4, presence_penalty=0.3)


class _Resp:
    def __init__(self, body=None, lines=None, status=200):
        self._body, self._lines, self.status = body or {}, lines or [], status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def json(self):
        return self._body

    def iter_lines(self):
        return iter(self._lines)


class _Capture:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def post(self, url, json=None, stream=False, timeout=None):
        self.calls.append({"url": url, "json": json, "stream": stream, "timeout": timeout})
        return self.resp

    def get(self, url, timeout=None):
        self.calls.append({"url": url, "timeout": timeout})
        return self.resp


@pytest.fixture
def llama(monkeypatch):
    monkeypatch.setattr(themer, "LLM_BACKEND", "llamacpp")
    monkeypatch.setattr(themer, "LLM_BASE", "http://llm.test")
    cap = _Capture(_Resp({"choices": [{"message": {"content": "ok"}}]}))
    monkeypatch.setattr(themer.requests, "post", cap.post)
    monkeypatch.setattr(themer.requests, "get", cap.get)
    return cap


@pytest.fixture
def ollama(monkeypatch):
    monkeypatch.setattr(themer, "LLM_BACKEND", "ollama")
    monkeypatch.setattr(themer, "OLLAMA_BASE", "http://ollama.test")
    monkeypatch.setattr(themer, "LLM_NUM_CTX", 4096)
    cap = _Capture(_Resp({"message": {"content": "  ok  "}}))
    monkeypatch.setattr(themer.requests, "post", cap.post)
    monkeypatch.setattr(themer.requests, "get", cap.get)
    return cap


# -- llama.cpp request ------------------------------------------------------------------------------

def test_llamacpp_request_carries_all_sampler_fields(llama):
    out = themer._chat_completion(MSGS, model="qwen3:14b", temperature=0.9, num_predict=3072, **SAMPLERS)
    sent = llama.calls[0]["json"]
    assert out == "ok" and llama.calls[0]["url"] == "http://llm.test/v1/chat/completions"
    assert sent["model"] == "qwen3:14b" and sent["temperature"] == 0.9 and sent["max_tokens"] == 3072
    for k, v in SAMPLERS.items():
        assert sent[k] == v, f"{k} was not forwarded to llama-server"


def test_llamacpp_omits_unset_sampler_fields(llama):
    themer._chat_completion(MSGS, model="m", temperature=0.2, num_predict=10)
    sent = llama.calls[0]["json"]
    for k in SAMPLERS:
        assert k not in sent


def test_a_zero_valued_sampler_is_still_forwarded(llama):
    # frequency_penalty=0.0 is a real setting; `if x:` would have dropped it
    themer._chat_completion(MSGS, model="m", temperature=0.0, num_predict=10, frequency_penalty=0.0, top_k=0)
    sent = llama.calls[0]["json"]
    assert sent["frequency_penalty"] == 0.0 and sent["top_k"] == 0 and sent["temperature"] == 0.0


def test_thinking_is_disabled_unless_asked_for(llama):
    themer._chat_completion(MSGS, model="m", temperature=0.2, num_predict=10)
    assert llama.calls[0]["json"]["chat_template_kwargs"] == {"enable_thinking": False}
    themer._chat_completion(MSGS, model="m", temperature=0.2, num_predict=10, think=True)
    assert "chat_template_kwargs" not in llama.calls[1]["json"]


def test_think_blocks_are_stripped_from_the_reply(llama):
    llama.resp = _Resp({"choices": [{"message": {"content": "<think>secret plan</think>Final answer"}}]})
    assert themer._chat_completion(MSGS, model="m", temperature=0.2, num_predict=10) == "Final answer"
    llama.resp = _Resp({"choices": [{"message": {"content": None}}]})
    assert themer._chat_completion(MSGS, model="m", temperature=0.2, num_predict=10) == ""


def test_an_http_error_propagates(llama):
    llama.resp = _Resp(status=503)
    with pytest.raises(RuntimeError):
        themer._chat_completion(MSGS, model="m", temperature=0.2, num_predict=10)


# -- llama.cpp streaming --------------------------------------------------------------------------------

def _sse(*chunks, done=True):
    lines = [b"data: " + json.dumps({"choices": [{"delta": {"content": c}}]}).encode() for c in chunks]
    return lines + ([b"data: [DONE]"] if done else [])


def test_streaming_joins_deltas_and_stops_at_done(llama):
    llama.resp = _Resp(lines=_sse("Hel", "lo") + [b"data: " + json.dumps({"choices": [{"delta": {"content": "!"}}]}).encode()])
    out = themer._chat_completion(MSGS, model="m", temperature=0.2, num_predict=10, stream=True)
    assert out == "Hello"                                       # the chunk after [DONE] is ignored
    assert llama.calls[0]["stream"] is True


def test_streaming_skips_blank_and_malformed_lines_and_handles_str_lines(llama):
    llama.resp = _Resp(lines=[b"", b"data: {not json", "data: " + json.dumps({"choices": [{"delta": {}}]}),
                              "data: " + json.dumps({"choices": [{"delta": {"content": "ok"}}]}), "data: [DONE]"])
    assert themer._chat_completion(MSGS, model="m", temperature=0.2, num_predict=10, stream=True) == "ok"


def test_streaming_strips_think_blocks(llama):
    llama.resp = _Resp(lines=_sse("<think>x</think>", "Real"))
    assert themer._chat_completion(MSGS, model="m", temperature=0.2, num_predict=10, stream=True) == "Real"


def test_streaming_gives_up_at_the_deadline_with_the_partial_reply(llama, monkeypatch):
    clock = iter([0.0, 0.0, 999.0, 999.0, 999.0])
    monkeypatch.setattr(themer.time, "monotonic", lambda: next(clock))
    llama.resp = _Resp(lines=_sse("kept", "dropped", done=False))
    out = themer._chat_completion(MSGS, model="m", temperature=0.2, num_predict=10, stream=True, timeout=5)
    assert out == "kept"


# -- native Ollama -----------------------------------------------------------------------------------------------

def test_ollama_request_nests_samplers_in_options_and_sets_context(ollama):
    out = themer._chat_completion(MSGS, model="qwen3:14b", temperature=0.9, num_predict=3072, think=False, **SAMPLERS)
    sent = ollama.calls[0]["json"]
    assert out == "ok"                                           # stripped
    assert ollama.calls[0]["url"] == "http://ollama.test/api/chat"
    assert sent["think"] is False and sent["stream"] is False
    opts = sent["options"]
    assert opts["num_ctx"] == 4096 and opts["num_predict"] == 3072 and opts["temperature"] == 0.9
    for k, v in SAMPLERS.items():
        assert opts[k] == v


def test_ollama_streaming_joins_message_content_until_done(ollama):
    lines = [json.dumps({"message": {"content": "a"}}), "", "not json",
             json.dumps({"message": {"content": "b"}, "done": True}), json.dumps({"message": {"content": "c"}})]
    ollama.resp = _Resp(lines=lines)
    assert themer._chat_completion(MSGS, model="m", temperature=0.2, num_predict=10, stream=True) == "ab"


# -- discovery / unload --------------------------------------------------------------------------------------------------

def test_endpoint_base_follows_the_backend(monkeypatch):
    monkeypatch.setattr(themer, "LLM_BASE", "http://a")
    monkeypatch.setattr(themer, "OLLAMA_BASE", "http://b")
    monkeypatch.setattr(themer, "LLM_BACKEND", "llamacpp")
    assert themer.llm_endpoint_base() == "http://a"
    monkeypatch.setattr(themer, "LLM_BACKEND", "ollama")
    assert themer.llm_endpoint_base() == "http://b"


def test_installed_models_for_each_backend_and_when_unreachable(llama):
    llama.resp = _Resp({"data": [{"id": "qwen3:14b"}, {"id": ""}, {"nope": 1}]})
    assert themer.installed_models() == {"qwen3:14b"}
    assert llama.calls[-1]["url"] == "http://llm.test/v1/models"
    llama.resp = _Resp(status=500)
    assert themer.installed_models() == set()


def test_installed_models_ollama(ollama):
    ollama.resp = _Resp({"models": [{"name": "qwen3:14b"}, {"name": "gemma4"}]})
    assert themer.installed_models() == {"qwen3:14b", "gemma4"}
    assert ollama.calls[-1]["url"] == "http://ollama.test/api/tags"


def test_unload_posts_to_the_right_endpoint_and_never_raises(llama, monkeypatch):
    themer.llm_unload()
    assert llama.calls[-1]["url"] == "http://llm.test/api/models/unload"
    monkeypatch.setattr(themer.requests, "post", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    themer.llm_unload()                                          # best effort: no exception


def test_unload_on_ollama_sets_keep_alive_zero(ollama):
    themer.llm_unload()
    assert ollama.calls[-1]["url"] == "http://ollama.test/api/generate"
    assert ollama.calls[-1]["json"]["keep_alive"] == 0
