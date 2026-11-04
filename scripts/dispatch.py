#!/usr/bin/env python3
"""Dispatch drafting jobs to the local llama-swap worker (spec -> local draft -> review).

    python scripts/offload.py docs/offload/specs/ship-grid.md
    python scripts/offload.py docs/offload/specs/*.md --model qwen3:32b

Each spec is a markdown file whose body is the prompt. A YAML-ish header sets the
output path and optional model:

    out: tests/test_example.py
    model: qwen3:14b
    ---
    <the prompt>

`docs/offload/_context.md` (next to the spec's folder, or in the spec's own folder) is
prepended to every prompt, so each spec only describes its one file.

Drafts land at the `out` path with a .draft suffix (git-ignored). They are NEVER written
straight into the tree -- qwen3:14b reliably returns plausible code carrying one or two
real bugs per file, so a review is part of the loop, not an optional extra.

Ported from skyforge/scripts/offload.py; adds `include:` (comma-separated repo paths whose source is
embedded in the prompt, so specs never paraphrase the API).
"""
import argparse
import concurrent.futures
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request

ENDPOINT = os.environ.get("LLAMA_SWAP_URL", "http://127.0.0.1:8010/v1/chat/completions")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MODEL = "qwen3:14b"
NODES_FILE = os.path.join(ROOT, "scripts", "nodes.json")


def load_nodes():
    """Worker nodes from scripts/nodes.json; falls back to the single LLAMA_SWAP_URL endpoint.

    The first node is the default. A node may set `spread`: the models it accepts when
    --spread fans a batch out (everything else stays on the first node).
    """
    nodes = {}
    if os.path.exists(NODES_FILE):
        with open(NODES_FILE, encoding="utf-8-sig") as f:
            nodes = json.load(f).get("nodes", {})
    if not nodes or "LLAMA_SWAP_URL" in os.environ:
        return {"env": {"url": ENDPOINT, "models": [], "jobs": 2}}
    return nodes


def reachable(url):
    """True if the node's /v1/models answers; keeps a down node from stalling a batch."""
    probe = url.rsplit("/chat/completions", 1)[0] + "/models"
    try:
        urllib.request.urlopen(probe, timeout=3).close()
        return True
    except (urllib.error.URLError, OSError):
        return False

SYSTEM = """You are a senior Python engineer writing pytest tests and small modules for Myth Forge (Python 3.11+, FastAPI, Pillow).

Hard rules:
- Output ONLY the file contents. No prose, no explanation, no ``` fences.
- `from __future__ import annotations`; builtin generics (dict[str, int]); NEVER `from typing import dict/list/set/tuple`.
- Tests use plain pytest (functions, `tmp_path`, `monkeypatch`). No network, no ComfyUI, no GPU, no real Scryfall.
- Import modules exactly as the spec's source shows. Never invent functions, fields, or imports; if the source does not show it, do not call it.
- Assert only behaviour you can read directly off the source shown. If unsure of an expected value, assert a property (type, length, round-trip) instead.
- Magic rules are out of scope: never encode card-rules knowledge.
/no_think"""


def find_context(spec_path):
    here = os.path.dirname(os.path.abspath(spec_path))
    for d in (here, os.path.dirname(here)):
        p = os.path.join(d, "_context.md")
        if os.path.exists(p):
            return open(p, encoding="utf-8-sig").read()
    return ""


def parse_spec(path):
    # utf-8-sig: Windows PowerShell 5.1 writes a BOM that would hide the first header key.
    raw = open(path, encoding="utf-8-sig").read().replace("\r\n", "\n")
    head, sep, body = raw.partition("\n---\n")
    if not sep:
        sys.exit(f"{path}: spec needs a header ending in a `---` line")
    meta = {}
    for line in head.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    if "out" not in meta:
        sys.exit(f"{path}: spec header must set `out:`")
    inc = [p.strip() for p in meta.get("include", "").split(",") if p.strip()]
    fence = "`" * 3
    srcs = "".join(
        "\n\n### SOURCE: " + p + "\n" + fence + "python\n"
        + open(os.path.join(ROOT, p), encoding="utf-8").read()
        + "\n" + fence + "\n"
        for p in inc
    )
    if srcs:
        body = srcs + "\n\n---\n\n" + body
    shared = find_context(path)
    if shared:
        body = shared + "\n\n---\n\n# This file\n\n" + body.strip()
    return meta, body.strip()


def dispatch(prompt, model, endpoint, temperature=0.2, timeout=900, history=None):
    """One chat turn. `history` = prior [assistant, user] messages for a repair round."""
    payload = json.dumps({
        "model": model,
        "temperature": temperature,
        "max_tokens": 8000,
        # Ollama (node 2) ignores /no_think; without this qwen3 can spend the whole budget thinking. llama.cpp ignores it.
        "reasoning_effort": "none",
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ] + list(history or []),
    }).encode()
    req = urllib.request.Request(
        endpoint, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    return data["choices"][0]["message"]["content"]


def clean(text):
    """Models add think blocks and fences despite being told not to."""
    # Think block first: the original stripped fences first, so a leading <think> kept them.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    fenced = re.search(r"```[A-Za-z0-9#+-]*\n(.*?)\n```", text, flags=re.S)
    if fenced:
        text = fenced.group(1)
    return text.strip() + "\n"


def run(spec_path, model_override, node_name, node):
    meta, prompt = parse_spec(spec_path)
    model = model_override or meta.get("model") or DEFAULT_MODEL
    started = time.time()
    content = None
    for attempt in (1, 2):
        try:
            content = clean(dispatch(prompt, model, node["url"]))
            break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # A reset (OSError, e.g. node 2's Ollama restarting mid-reply) used to kill the worker thread and
            # silently drop the rest of the batch. Retry once after a pause, then report and move on.
            if attempt == 2:
                return spec_path, None, f"dispatch to {node_name} failed: {e}"
            time.sleep(30)
    verdict = ""
    if VERIFY and meta["out"].startswith("tests/") and meta["out"].endswith(".py"):
        content, verdict = verify_and_repair(prompt, content, model, node, meta["out"])
    out = os.path.join(ROOT, meta["out"] + ".draft")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return spec_path, out, f"{node_name}  {model}  {len(content):>6} chars  {time.time() - started:.0f}s  {verdict}"


VERIFY = False
REPAIR_ROUNDS = 2


def _pytest_draft(code, out_rel):
    """Run a drafted test file in isolation. Returns (ok, tail). Never touches tests/ proper."""
    import subprocess
    import tempfile
    d = tempfile.mkdtemp(prefix="dispatch_verify_", dir=os.path.join(ROOT, "tests"))
    try:
        p = os.path.join(d, os.path.basename(out_rel))
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(code)
        r = subprocess.run([sys.executable, "-m", "pytest", p, "-q", "--no-header", "-x",
                            "-p", "no:cacheprovider", "--rootdir", ROOT],
                           cwd=ROOT, capture_output=True, text=True, timeout=300)
        tail = "\n".join((r.stdout + r.stderr).splitlines()[-40:])
        return r.returncode == 0, tail
    except subprocess.TimeoutExpired:
        return False, "pytest timed out after 300s"
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def verify_and_repair(prompt, code, model, node, out_rel):
    """Run the draft; on failure send the pytest tail back for up to REPAIR_ROUNDS fixes.

    A pass here only means "runs and its assertions hold"; it does NOT mean the tests are
    meaningful. Read every draft for vacuous asserts before landing it.
    """
    ok, tail = _pytest_draft(code, out_rel)
    rounds = 0
    while not ok and rounds < REPAIR_ROUNDS:
        rounds += 1
        history = [
            {"role": "assistant", "content": code},
            {"role": "user", "content": (
                "Running that file under pytest failed:\n\n" + tail +
                "\n\nFix ONLY what the failure shows. If an assertion's expected value is wrong, "
                "re-derive it from the SOURCE above or weaken it to a property; delete a test you "
                "cannot justify from the source. Output the complete corrected file only.")},
        ]
        try:
            code = clean(dispatch(prompt, model, node["url"], history=history))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return code, f"[verify: repair call failed: {e}]"
        ok, tail = _pytest_draft(code, out_rel)
    return code, f"[verify: {'PASS' if ok else 'FAIL'} after {rounds} repair round(s)]"


def spec_model(spec_path, model_override):
    meta, _ = parse_spec(spec_path)
    return model_override or meta.get("model") or DEFAULT_MODEL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("specs", nargs="+")
    ap.add_argument("--model")
    ap.add_argument("--node", help="send every spec to this node from scripts/nodes.json")
    ap.add_argument("--verify", action="store_true",
                    help="for tests/*.py specs: run the draft under pytest and feed failures back (2 rounds)")
    ap.add_argument("--spread", action="store_true",
                    help="fan the batch out: nodes with a `spread` list also take specs for those models")
    # llama-swap holds one model at a time; parallel calls just queue behind a
    # swap. Two keeps the pipe busy without thrashing the loader.
    ap.add_argument("--jobs", type=int, help="override the per-node concurrency from nodes.json")
    args = ap.parse_args()
    global VERIFY
    VERIFY = args.verify

    nodes = load_nodes()
    if args.node:
        if args.node not in nodes:
            sys.exit(f"unknown node {args.node!r}; have: {', '.join(nodes)}")
        nodes = {args.node: nodes[args.node]}
    elif not args.spread:
        first = next(iter(nodes))
        nodes = {first: nodes[first]}

    live = {}
    for name, node in nodes.items():
        if reachable(node["url"]):
            live[name] = node
        else:
            print(f"  !! node {name} unreachable ({node['url']}) -- skipped")
    if not live:
        sys.exit("no reachable worker node (is llama-swap up on :8010?)")

    default = next(iter(live)) if not args.node else args.node
    # Shared queue; a worker takes the next spec its node is allowed to run. The default
    # node takes anything; others only models in their `spread` list.
    pending = list(args.specs)
    lock = threading.Lock()

    def take(name, node):
        with lock:
            for s in pending:
                if name == default or spec_model(s, args.model) in node.get("spread", []):
                    pending.remove(s)
                    return s
        return None

    def worker(name, node):
        results = []
        while True:
            s = take(name, node)
            if s is None:
                return results
            results.append(run(s, args.model, name, node))

    slots = []
    for name, node in live.items():
        for _ in range(args.jobs or node.get("jobs", 2)):
            slots.append((name, node))
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(slots)) as pool:
        futures = [pool.submit(worker, n, nd) for n, nd in slots]
        for fut in concurrent.futures.as_completed(futures):
            for spec, out, note in fut.result():
                name = os.path.basename(spec)
                if out:
                    print(f"  {name:<28} -> {os.path.relpath(out, ROOT)}\n     {note}")
                else:
                    print(f"  {name:<28} !! {note}")
    for s in pending:
        print(f"  {os.path.basename(s):<28} !! not run: no reachable node serves it")

    print("\nDrafts written with a .draft suffix. Read every one before landing it.")


if __name__ == "__main__":
    main()
