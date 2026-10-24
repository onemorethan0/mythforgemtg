"""In-memory ring buffer of the server's stdout/stderr, served by /api/logs.

server.py installs `_TeeStream` over sys.stdout/sys.stderr at import.
"""
from __future__ import annotations

import collections
from datetime import datetime as _dt

_LOG_BUFFER: "collections.deque[str]" = collections.deque(maxlen=5000)


class _TeeStream:
    """Write-through stream wrapper that mirrors output into _LOG_BUFFER line by line."""

    def __init__(self, original):
        self._original = original
        self._partial = ""

    def write(self, text):
        if self._original is not None:
            try:
                self._original.write(text)
            except Exception:
                pass
        self._partial += text
        while "\n" in self._partial:
            line, self._partial = self._partial.split("\n", 1)
            _LOG_BUFFER.append(f"{_dt.now().strftime('%H:%M:%S')} {line}")
        return len(text)

    def flush(self):
        if self._original is not None:
            try:
                self._original.flush()
            except Exception:
                pass

    def isatty(self):
        # uvicorn's log formatter calls this during config; guard against a
        # None/detached stdout so logging setup never crashes on launch.
        try:
            return bool(self._original) and self._original.isatty()
        except Exception:
            return False

    def __getattr__(self, name):
        return getattr(self._original, name)
