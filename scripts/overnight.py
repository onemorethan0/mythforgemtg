"""Unattended overnight pipeline: grow the engine while the hardware is idle.

Runs two workstreams concurrently and never stops on a single failure:

  GPU  - CCM compilation in checkpointed chunks. NOTE: compile-top N compiles N NEW
         cards (next-most-popular not yet accepted), so four chunks of 1400 target
         ~5,600 new cards (~6-8h at the measured ~3.4s/card). The ledger saves after
         every card, so any interruption resumes for free. Restarts the llama-swap
         gateway if it goes down.
  CPU  - corpus refresh (Archidekt recent decks), a PRE full-ish round-robin
         gauntlet, and a deep Tier-0 benchmark.

When compilation finishes, a POST gauntlet re-runs with identical seed/params so
the morning report can show exactly how ratings moved as semantics coverage grew
(rating stability vs. knowledge growth = calibration evidence, docs/LEARNING.md).

Everything is logged to data/overnight_<stamp>.log; a morning summary lands in
data/overnight_report_<stamp>.md. The script leaves the git tree uncommitted on
purpose - review and commit happen with human eyes on the report.

Usage:
  .venv\\Scripts\\python scripts\\overnight.py            # full night (~10h GPU)
  .venv\\Scripts\\python scripts\\overnight.py --smoke    # ~5 min wiring check
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _python() -> str:
    """The interpreter to spawn CLI subprocesses with.

    This script came from the standalone MythGauntlet repo, which had its own `.venv`.
    Myth Forge doesn't — it runs on the system interpreter — so prefer a venv when one
    exists (keeps the old layout working) and otherwise use whatever is running us.
    `sys.executable` is right in both the scheduled-task and manual cases.
    """
    venv = REPO / ".venv" / "Scripts" / "python.exe"
    return str(venv if venv.exists() else Path(sys.executable))


PYTHON = _python()

# Subprocesses need src/ importable (the engine keeps its src/ layout) and must inherit the
# compiled-store location, which lives outside this repo — see compiler.store_dir().
_ENV = {**os.environ, "PYTHONPATH": os.pathsep.join(
    filter(None, [str(REPO / "src"), os.environ.get("PYTHONPATH", "")])
)}
DATA = REPO / "data"
# The compiled store (and its ledger) can live outside this repo — the semantics are
# withheld and versioned separately, see compiler.store_dir() / docs/ENGINE_DATA.md.
# Honour the same override the engine does, or the morning report would read a ledger
# that the night never wrote to and cheerfully report "nothing happened".
LEDGER = Path(os.environ.get("MYTHGAUNTLET_STORE") or (REPO / "ccm")) / "ledger.json"
GATEWAY_URL = "http://127.0.0.1:8010/v1/models"
GATEWAY_BAT = Path("E:/llama/start-llama-swap.bat")

STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")
LOG_PATH = DATA / f"overnight_{STAMP}.log"
REPORT_PATH = DATA / f"overnight_report_{STAMP}.md"
_LOG_LOCK = threading.Lock()


def log(message: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
    with _LOG_LOCK:
        print(line, flush=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def run(name: str, *cli_args: str) -> int:
    """Run a mythgauntlet CLI verb, streaming output to the log. Never raises."""
    log(f"START {name}: mythgauntlet {' '.join(cli_args)}")
    started = time.time()
    try:
        proc = subprocess.Popen(
            [PYTHON, "-m", "mythgauntlet", *cli_args],
            cwd=REPO, env=_ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            if line:
                with _LOG_LOCK, open(LOG_PATH, "a", encoding="utf-8") as fh:
                    fh.write(f"    | {line}\n")
        rc = proc.wait()
    except OSError as exc:
        log(f"FAIL  {name}: could not launch ({exc})")
        return -1
    minutes = (time.time() - started) / 60
    log(f"END   {name}: rc={rc} ({minutes:.1f} min)")
    return rc


def gateway_up() -> bool:
    try:
        with urllib.request.urlopen(GATEWAY_URL, timeout=5):
            return True
    except OSError:
        return False


def ensure_gateway(wait_s: int = 240) -> bool:
    if gateway_up():
        return True
    log(f"gateway down - starting {GATEWAY_BAT}")
    try:
        subprocess.Popen(f'cmd /c start "" "{GATEWAY_BAT}"', shell=True)
    except OSError as exc:
        log(f"gateway start failed: {exc}")
        return False
    deadline = time.time() + wait_s
    while time.time() < deadline:
        time.sleep(5)
        if gateway_up():
            log("gateway is up")
            return True
    log("gateway did not come up in time")
    return False


def ledger_stats() -> dict[str, int]:
    """Ledger snapshot. `at_latest_prompt` is what makes a REFRESH night visible:
    recompiling an accepted card to the current prompt leaves total/accepted
    unchanged, so status counts alone would report a productive night as 'nothing
    happened'. Latest version is read from the data (max seen) rather than imported,
    keeping this script free of package imports."""
    if not LEDGER.exists():
        return {}
    with open(LEDGER, encoding="utf-8") as fh:
        entries = json.load(fh).get("entries", {})
    stats: dict[str, int] = {"total": len(entries)}
    for entry in entries.values():
        stats[entry["status"]] = stats.get(entry["status"], 0) + 1
    versions = [e.get("prompt_version") or 0 for e in entries.values()]
    if versions:
        latest = max(versions)
        stats["prompt_version"] = latest
        stats["at_latest_prompt"] = sum(1 for v in versions if v == latest)
    return stats


def latest_gauntlet_file() -> Path | None:
    # only un-renamed run outputs (renamed archives carry a _pre_/_post_/... suffix)
    candidates = sorted(
        (p for p in DATA.glob("gauntlet_*.json") if "_" not in p.stem[len("gauntlet_"):]),
        key=lambda p: p.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


def _archive_gauntlet(tag: str) -> Path | None:
    """Rename the just-written gauntlet_<date>.json to a stamped archive so the next run's output
    doesn't overwrite it. Returns the archived path."""
    latest = latest_gauntlet_file()
    if latest is None:
        return None
    dest = latest.with_name(f"{latest.stem}_{tag}_{STAMP}{latest.suffix}")
    latest.rename(dest)
    log(f"gauntlet {tag} -> {dest.name}")
    return dest


# Weekday the weekly agent-contrast phase runs on (0=Mon). Sunday keeps it off work nights.
AGENT_CONTRAST_WEEKDAY = 6
_WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                  "Saturday", "Sunday")

REDUCED_SEED = "778"  # distinct from the full-gauntlet seed so caches don't collide


def _reduced_scope(smoke: bool) -> list[str]:
    """Fewer opponents/games than the full greedy run — ISMCTS is slow per decision, so the
    agent-contrast gauntlets are deliberately small (the signal is the AGENT delta, not scale)."""
    return ["--opponents", "2", "--games", "6"] if smoke else ["--opponents", "4", "--games", "20"]


def _agent_gauntlet_args(agent: str, cores: int, smoke: bool) -> list[str]:
    return (["--agent", agent, "--jobs", str(cores), "--cache", "--no-combos",
             "--seed", REDUCED_SEED] + _reduced_scope(smoke))


def _bracket_labels() -> dict[str, int]:
    manifest = REPO / "corpus" / "decks" / "manifest.json"
    if not manifest.exists():
        return {}
    with open(manifest, encoding="utf-8") as fh:
        return {Path(e["file"]).stem: e["bracket"]
                for e in json.load(fh).get("decks", []) if e.get("bracket")}


def _bracket_means(ratings: dict[str, float], labels: dict[str, int]) -> str:
    by: dict[int, list[float]] = {}
    for name, rating in ratings.items():
        bracket = labels.get(name)
        if bracket:
            by.setdefault(bracket, []).append(rating)
    if not by:
        return "no labeled decks in this run"
    return "  ".join(f"B{b}:{sum(v) / len(v):.0f}(n={len(v)})" for b, v in sorted(by.items()))


def gpu_worker(chunks: list[int], deadline: float) -> None:
    # --refresh-stale keeps this workstream alive now that the new-card pool is
    # exhausted (2026-07-28: the ledger covers every EDHREC-ranked non-basic card).
    # Without it compile-top returned "nothing to compile" in ~1s per chunk and two
    # consecutive nights produced zero engine growth. With it, the chunks upgrade
    # cards accepted under an older prompt version, most-played first.
    for i, count in enumerate(chunks, 1):
        if time.time() > deadline:
            log(f"GPU: past deadline, skipping chunk {i} ({count} cards)")
            continue
        if not ensure_gateway():
            log(f"GPU: no gateway, skipping chunk {i}")
            continue
        name = f"compile chunk {i}/{len(chunks)} ({count} cards)"
        rc = run(name, "compile-top", str(count), "--refresh-stale")
        if rc != 0:
            log(f"GPU: chunk {i} failed (rc={rc}); retrying once")
            if ensure_gateway():
                run(name + " (retry)", "compile-top", str(count), "--refresh-stale")
    log("GPU: compile workstream finished")


def cpu_worker(smoke: bool, gauntlet_args: list[str]) -> None:
    top = "5" if smoke else "40"
    # Refresh the Scryfall bulk BEFORE anything reads it: without this the card
    # universe never grows, so newly-released sets can't enter the compile pool.
    # (It had gone 23 days stale by 2026-07-28.)
    run("fetch-data (scryfall bulk)", "fetch-data")
    run("fetch-decks (archidekt recent)",
        "fetch-decks", "--source", "archidekt", "--top", top, "--order=-updatedAt")
    run("gauntlet PRE", "gauntlet", *gauntlet_args)
    _archive_gauntlet("pre")
    run("benchmark (deep T0)", "benchmark", "--runs", "300" if smoke else "3000")
    log("CPU: simulation workstream finished")


def _find_archive(suffix: str) -> Path | None:
    return next(iter(sorted(DATA.glob(f"gauntlet_*_{suffix}_{STAMP}.json"))), None)


def _ratings(path: Path | None) -> dict[str, float]:
    if path is None:
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("ratings", {})
    except (OSError, json.JSONDecodeError):
        return {}


def write_report(
    before: dict[str, int], gauntlet_args: list[str], started: float
) -> None:
    after = ledger_stats()
    labels = _bracket_labels()
    pre_r = _ratings(_find_archive("pre"))
    post_r = _ratings(_find_archive("post"))
    rgreedy_r = _ratings(_find_archive("rgreedy"))
    mcts_r = _ratings(_find_archive("mcts"))

    lines = [
        f"# Overnight run report - {STAMP}",
        "",
        f"Wall time: {(time.time() - started) / 3600:.1f} h. Log: {LOG_PATH.name}",
        "",
        "## Semantics compilation (GPU)",
        f"- ledger before: {before or 'n/a'}",
        f"- ledger after:  {after or 'n/a'}",
        f"- newly accepted: {after.get('accepted', 0) - before.get('accepted', 0)}",
        f"- newly quarantined: {after.get('quarantined', 0) - before.get('quarantined', 0)}",
        f"- refreshed to prompt v{after.get('prompt_version', '?')}: "
        f"{after.get('at_latest_prompt', 0) - before.get('at_latest_prompt', 0)}"
        f" (now {after.get('at_latest_prompt', 0)}/{after.get('total', 0)})",
        f"- remaining on an older prompt: "
        f"{after.get('total', 0) - after.get('at_latest_prompt', 0)}",
    ]
    if after == before:
        lines.append(
            "- WARNING: the ledger did not move at all tonight. Either the pool is "
            "genuinely exhausted (check the log for 'Nothing to compile') or the "
            "gateway/compile step failed - these look identical in the counts above."
        )
    lines += [
        "",
        "## Gauntlet ratings (greedy, full), pre vs post compile",
        f"- params: {' '.join(gauntlet_args)}",
    ]
    if pre_r and post_r:
        shared = sorted(set(pre_r) & set(post_r))
        deltas = sorted(((post_r[n] - pre_r[n], n) for n in shared), key=lambda t: -abs(t[0]))
        lines.append(f"- decks rated in both runs: {len(shared)}")
        lines.append(f"- bracket means [greedy, full]: {_bracket_means(post_r, labels)}")
        moved = [d for d, _ in deltas if d]
        if not moved:
            # Say this outright: a top-10 table of "+0.0" reads like a measurement.
            lines.append("- NO deck moved. The night's semantics changes touched no card "
                         "the corpus decks actually play.")
        else:
            lines.append(f"- decks that moved: {len(moved)}")
            lines.append("- biggest movers (post - pre):")
            for delta, name in deltas[:10]:
                lines.append(f"    {delta:+7.1f}  {name}")
    elif pre_r and after == before:
        lines.append("- POST skipped: semantics unchanged, so it would rerun PRE bit-for-bit.")
        lines.append(f"- bracket means [greedy, full]: {_bracket_means(pre_r, labels)}")
    else:
        lines.append("- pre/post comparison unavailable (see log)")

    # The Phase-7 payoff: same reduced scope, ONLY the agent differs.
    lines += ["", "## Agent upgrade: greedy vs ISMCTS at equal scope (Phase 7)"]
    if rgreedy_r and mcts_r:
        shared = sorted(set(rgreedy_r) & set(mcts_r))
        movers = sorted(((mcts_r[n] - rgreedy_r[n], n) for n in shared), key=lambda t: -abs(t[0]))
        lines.append(f"- decks rated under both agents: {len(shared)} (reduced scope, same seed)")
        lines.append(f"- bracket means [greedy]: {_bracket_means(rgreedy_r, labels)}")
        lines.append(f"- bracket means [ISMCTS]: {_bracket_means(mcts_r, labels)}")
        lines.append("- biggest shifts (ISMCTS - greedy):")
        for delta, name in movers[:10]:
            lines.append(f"    {delta:+7.1f}  {name}")
        lines.append("- READ: if ISMCTS lifts B5/cEDH toward B3 the inversion was partly an")
        lines.append("  AGENT-fidelity gap; if it stays inverted it's the ENGINE (cEDH lines")
        lines.append("  under-modeled) -- do NOT feed T2 meta-rating to top-bracket calibration.")
    else:
        lines.append("- ISMCTS agent-contrast unavailable (see log)")

    lines += ["", "## Sanity", ""]
    rc = subprocess.run(
        [PYTHON, "-m", "pytest", "-q"], cwd=REPO, env=_ENV, capture_output=True, text=True
    )
    tail = (rc.stdout or "").strip().splitlines()[-1:] or ["(no output)"]
    lines.append(f"- pytest: rc={rc.returncode} ({tail[0]})")
    lines.append("- git tree left UNCOMMITTED for morning review.")

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"report written: {REPORT_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="small wiring check")
    parser.add_argument("--max-hours", type=float, default=10.0)
    parser.add_argument(
        "--chunk-size", type=int, default=1400,
        help="NEW cards to compile per checkpointed chunk",
    )
    parser.add_argument("--chunks", type=int, default=4)
    parser.add_argument(
        "--agent-contrast", choices=("auto", "always", "never"), default="auto",
        help="greedy-vs-ISMCTS phase. auto (default) = weekly, and only if the night is "
             "still inside --max-hours; always = force it; never = skip. It was nightly "
             "until its matchups tripled with the corpus and it stopped fitting in a night",
    )
    parser.add_argument(
        "--mcts-iters", type=int, default=120,
        help="ISMCTS iterations for the agent-contrast gauntlet (Phase 7 re-basing)",
    )
    args = parser.parse_args()

    DATA.mkdir(exist_ok=True)
    started = time.time()
    deadline = started + args.max_hours * 3600
    log(f"overnight pipeline start (smoke={args.smoke}, max_hours={args.max_hours})")

    before = ledger_stats()
    log(f"ledger before: {before}")

    if args.smoke:
        chunks = [5]
        gauntlet_args = ["--opponents", "2", "--games", "8", "--seed", "777"]
    else:
        chunks = [args.chunk_size] * args.chunks
        gauntlet_args = ["--opponents", "61", "--games", "40", "--seed", "777"]

    cpu = threading.Thread(target=cpu_worker, args=(args.smoke, gauntlet_args))
    cpu.start()
    gpu_worker(chunks, deadline)
    cpu.join()

    # POST gauntlet (greedy, full): identical params/seed, now with the night's semantics
    # coverage. Only worth running if the semantics actually MOVED — with an unchanged
    # ledger this is a bit-identical rerun of PRE (same seed, same params, same store), so
    # it burned ~12 min a night to print a table of "+0.0" that read like a finding.
    after_compile = ledger_stats()
    if after_compile == before:
        log("semantics unchanged tonight - skipping POST gauntlet (would duplicate PRE)")
    else:
        run("gauntlet POST (greedy)", "gauntlet", *gauntlet_args)
        _archive_gauntlet("post")

    # Phase-7 re-basing: two reduced-scope gauntlets at the SAME scope/seed, differing ONLY in
    # the agent. The morning question was whether a stronger agent moves the bracket picture
    # (esp. the cEDH/B5 inversion).
    #
    # NOT NIGHTLY ANY MORE (2026-07-30). Matchups scale with the corpus, and the corpus tripled
    # when the B1-3 anchors were harvested: 389 -> 449 -> 1066. At 1066 the ISMCTS half ran
    # 13+ HOURS and still hadn't finished when the 7/29 run died, so that night produced no
    # report at all and the 7/30 run was refused because the previous instance was still
    # registered as running. Two nights lost to a phase whose headline question is already
    # answered (the inversion is engine fidelity, not agent strength — docs/engine/STATUS.md).
    #
    # So it runs WEEKLY by default and only if the night is still within budget. The compile
    # workstream and the full greedy gauntlet — the parts that actually feed calibration — now
    # always get to finish and report.
    if args.agent_contrast == "never":
        log("agent-contrast: disabled (--agent-contrast never)")
    elif time.time() > deadline:
        log(f"agent-contrast: SKIPPED - past the {args.max_hours}h budget "
            "(compile + gauntlet results are already written)")
    elif args.agent_contrast == "auto" and datetime.now().weekday() != AGENT_CONTRAST_WEEKDAY:
        log("agent-contrast: skipped - runs weekly on "
            f"{_WEEKDAY_NAMES[AGENT_CONTRAST_WEEKDAY]} (--agent-contrast always to force)")
    else:
        cores = max(1, (os.cpu_count() or 4) - 2)
        run("gauntlet reduced (greedy)", "gauntlet",
            *_agent_gauntlet_args("greedy", cores, args.smoke))
        _archive_gauntlet("rgreedy")
        run("gauntlet reduced (ISMCTS)", "gauntlet",
            *_agent_gauntlet_args(f"mcts:{args.mcts_iters}", cores, args.smoke))
        _archive_gauntlet("mcts")

    run("ccm-status", "ccm-status")
    write_report(before, gauntlet_args, started)
    log("overnight pipeline done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
