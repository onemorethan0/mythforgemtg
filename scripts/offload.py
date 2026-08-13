"""Spec -> local llama-swap worker -> code file.

Reusable offload harness for the Myth* repos. Reads a markdown spec, POSTs it to the
llama-swap gateway on 127.0.0.1:8010, strips the fenced code block out of the reply,
and writes it to disk. Claude then reviews the draft before it is landed.

    python scripts/offload.py docs/SPEC_collection_pool.md collection_pool.py \
        --model muse-glimmer

Model notes (see ~/.claude memory `muse-glimmer-usage`):
  * muse-glimmer is a REASONING model — output splits into reasoning_content + content,
    so a small max_tokens returns an EMPTY content string. Keep it >= 400; we use 16000.
  * Its sampling params are specified, not tunable: temp 1.0 / top_p 0.95 / top_k 64.
  * qwen3:* are not reasoning-split and want temp 0.2 for code. --temp overrides.
  * HTTP 500 "upstream command exited prematurely" from llama-swap is a CUDA OOM inside
    llama-server (the desktop is holding 7-8 GB), not a config error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

GATEWAY = "http://127.0.0.1:8010/v1/chat/completions"

# Sampling that each model family actually wants.
_SAMPLING = {
    "muse-glimmer": {"temperature": 1.0, "top_p": 0.95, "top_k": 64},
    "_default":     {"temperature": 0.2, "top_p": 0.9,  "top_k": 40},
}

SYSTEM = (
    "You are a senior Python engineer. You implement a written specification exactly as "
    "given. You output ONLY code, inside a single ```python fenced block, with no prose "
    "before or after it. You never invent APIs, fields, or imports the spec does not name."
    "\n\n"
    "Hard rules, learned from prior rejected drafts:\n"
    "1. NEVER write `from typing import dict` (or `list`, `set`, `tuple`, or an aliased "
    "form like `from typing import dict as TypingDict`). These are builtins. With "
    "`from __future__ import annotations` you write `dict[str, int]` with NO import at "
    "all. This exact line has broken two drafts with an ImportError on the first run.\n"
    "2. Always emit the module docstring the spec asks for, including any worked-example "
    "table. Drafts keep dropping it.\n"
    "3. Budget your output so the code is COMPLETE. Your reasoning is billed against the "
    "same token budget as your answer; a draft that stops mid-function is worthless. "
    "Reason briefly, then write the whole file.\n"
    "4. Close the ```python fence."
)

# ANY language tag, not just python — this harness drafts .jsx/.ts/.md too, and a
# ```jsx fence that the pattern didn't recognise was left IN the written file, where it
# is a syntax error on line 1.
_FENCE = re.compile(r"```[A-Za-z0-9_+-]*[ \t]*\n(.*?)```", re.S)


def extract_code(reply: str) -> str:
    """The largest fenced block, else the reply with an ORPHAN opening fence stripped.

    A truncated reply keeps its opening fence but never emits the closing one, so the
    findall returns nothing and the raw text still carries the fence line — which is a
    syntax error in the written file. Strip it explicitly.
    """
    blocks = _FENCE.findall(reply)
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    text = reply.strip()
    text = re.sub(r"^```[A-Za-z0-9_+-]*[ \t]*\n", "", text)
    text = re.sub(r"\n```\s*$", "", text)
    return text.strip() + "\n"


def dispatch(spec: str, model: str, max_tokens: int, temp: float | None,
             timeout: int) -> tuple[str, str]:
    """POST the spec. Returns (content, reasoning_content)."""
    sampling = dict(_SAMPLING.get(model, _SAMPLING["_default"]))
    if temp is not None:
        sampling["temperature"] = temp
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": spec},
        ],
        "max_tokens": max_tokens,
        **sampling,
    }
    req = urllib.request.Request(
        GATEWAY,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        if e.code == 500 and "prematurely" in body:
            sys.exit(f"llama-swap 500: CUDA OOM loading {model!r} "
                     f"(desktop is holding VRAM). Close apps or use a smaller model.\n{body}")
        sys.exit(f"HTTP {e.code} from llama-swap: {body}")
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    return msg.get("content") or "", msg.get("reasoning_content") or ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--model", default="muse-glimmer")
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--temp", type=float, default=None)
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args()

    spec = args.spec.read_text(encoding="utf-8")
    print(f"[offload] {args.spec.name} -> {args.model} ({len(spec)} chars)", flush=True)

    t0 = time.time()
    content, reasoning = dispatch(spec, args.model, args.max_tokens, args.temp, args.timeout)
    dt = time.time() - t0

    if not content.strip():
        sys.exit(f"[offload] EMPTY content after {dt:.0f}s "
                 f"({len(reasoning)} chars of reasoning). Raise --max-tokens.")

    code = extract_code(content)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(code, encoding="utf-8")
    print(f"[offload] {dt:.0f}s | reasoning {len(reasoning)} ch | "
          f"wrote {args.out} ({len(code.splitlines())} lines)")


if __name__ == "__main__":
    main()
