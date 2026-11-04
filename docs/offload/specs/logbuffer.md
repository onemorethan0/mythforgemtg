out: tests/test_logbuffer.py
model: qwen3:8b
include: api/logbuffer.py
---
Write `tests/test_logbuffer.py`: pytest tests for the `_TeeStream` class and `_LOG_BUFFER` shown in the source above.

Import with `from api import logbuffer` and use `logbuffer._TeeStream`, `logbuffer._LOG_BUFFER`.
Use a fixture that clears `_LOG_BUFFER` before each test. Use `io.StringIO` as the wrapped stream.

Cover:
1. A complete line written ("hello\n") reaches the wrapped stream AND appends one buffer entry whose text ends with " hello" (entries are prefixed with an HH:MM:SS timestamp).
2. A partial write with no newline adds nothing to the buffer until the newline arrives; two writes "ab" then "c\n" produce one entry ending in "abc".
3. One write containing "a\nb\n" produces two entries in order.
4. `write` returns `len(text)`.
5. With `original=None`, write/flush do not raise and the buffer still fills; `isatty()` returns False.
6. A wrapped stream whose `write` raises must not stop the buffer from receiving the line.
7. `isatty()` returns False when the wrapped stream's `isatty` raises.
8. The buffer is a deque with maxlen 5000.
