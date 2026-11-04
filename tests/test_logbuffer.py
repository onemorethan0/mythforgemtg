"""api/logbuffer.py: the stdout/stderr ring buffer behind /api/logs.

Drafted on a local model (qwen3:8b), then corrected by hand: the draft referenced a
non-existent ``_LOG_MIRROR``, compared exact timestamps (flaky across a second boundary)
and its "write raises" case never made the write raise.
"""
from __future__ import annotations

import collections
import io

import pytest

from api import logbuffer


@pytest.fixture(autouse=True)
def _clean_buffer():
    logbuffer._LOG_BUFFER.clear()
    yield
    logbuffer._LOG_BUFFER.clear()


def test_complete_line_reaches_stream_and_buffer():
    stream = io.StringIO()
    logbuffer._TeeStream(stream).write("hello\n")
    assert stream.getvalue() == "hello\n"
    assert len(logbuffer._LOG_BUFFER) == 1
    assert logbuffer._LOG_BUFFER[0].endswith(" hello")


def test_timestamp_prefix_is_hh_mm_ss():
    logbuffer._TeeStream(io.StringIO()).write("x\n")
    stamp = logbuffer._LOG_BUFFER[0].split(" ", 1)[0]
    parts = stamp.split(":")
    assert len(parts) == 3 and all(len(p) == 2 and p.isdigit() for p in parts)


def test_partial_write_waits_for_newline():
    tee = logbuffer._TeeStream(io.StringIO())
    tee.write("ab")
    assert len(logbuffer._LOG_BUFFER) == 0
    tee.write("c\n")
    assert len(logbuffer._LOG_BUFFER) == 1
    assert logbuffer._LOG_BUFFER[0].endswith(" abc")


def test_two_lines_in_one_write_keep_order():
    logbuffer._TeeStream(io.StringIO()).write("a\nb\n")
    assert [e.split(" ", 1)[1] for e in logbuffer._LOG_BUFFER] == ["a", "b"]


def test_write_returns_length():
    assert logbuffer._TeeStream(io.StringIO()).write("hello") == 5


def test_none_original_is_safe():
    tee = logbuffer._TeeStream(None)
    tee.write("test\n")
    tee.flush()
    assert logbuffer._LOG_BUFFER[0].endswith(" test")
    assert tee.isatty() is False


def test_failing_original_write_still_buffers():
    class Broken:
        def write(self, _text):
            raise OSError("closed")

        def flush(self):
            raise OSError("closed")

    tee = logbuffer._TeeStream(Broken())
    tee.write("kept\n")
    tee.flush()  # must not raise
    assert logbuffer._LOG_BUFFER[0].endswith(" kept")


def test_isatty_false_when_original_raises():
    class Odd:
        def isatty(self):
            raise ValueError("detached")

    assert logbuffer._TeeStream(Odd()).isatty() is False


def test_buffer_is_a_bounded_deque():
    assert isinstance(logbuffer._LOG_BUFFER, collections.deque)
    assert logbuffer._LOG_BUFFER.maxlen == 5000
    tee = logbuffer._TeeStream(None)
    for i in range(5001):
        tee.write(f"{i}\n")
    assert len(logbuffer._LOG_BUFFER) == 5000
    assert logbuffer._LOG_BUFFER[0].endswith(" 1")  # the oldest line was evicted
