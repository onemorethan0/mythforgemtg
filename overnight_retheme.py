"""
overnight_retheme.py

Orchestrates an overnight batch retheme+rebuild run:
  1. Waits for the currently-active build to finish (polls ComfyUI queue)
  2. Restarts the MythForge server
  3. For each selected source deck:
       a. Duplicate  (keeps original untouched)
       b. Retheme    (fresh LLM naming/prompts via latest practices)
       c. Rebuild    (regenerate all card art from new prompts)

Usage:
    C:\Python314\python.exe overnight_retheme.py
"""

import json
import subprocess
import sys
import time
import requests
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("overnight_retheme.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

BASE = "http://localhost:8000"
COMFY = "http://localhost:8188"

# ── Decks to retheme ─────────────────────────────────────────────────────────
# One representative per unique (commander, theme) pair — most recent version.
# The Crystal Caverns job is appended at runtime once the current build finishes.
SOURCE_DECKS = [
    # job_id                  | commander                     | theme
    "84985c45150f4057",       # Syr Gwyn         | The Last Green Hole on earth
    "7d7275667e904857",       # Syr Gwyn         | Western desert post apocalypse
    "f97d02d3e2d94a78",       # Krenko, Mob Boss | Hive City (Warhammer 40K)
    "b9420bd7c1804578",       # Urza             | Green/Black Cyberpunk rave
    "36abb6cd649d4900",       # Aurelia          | Midgard / Ragnarok Online
    "b8e2392132ba45a4",       # Aang             | Musical Performers
    "0d4441bf743e4263",       # Syr Gwyn         | Prontera City, Halloween RO
    "2917b38b394c486f",       # Najeela          | Feudal Japanese samurai
    "3d2a13df181c48b0",       # Krenko           | Neon cyberpunk megacity
    "03e4b5df97024302",       # Kaalia of Vast   | Purple/Black Dark Forest
    "fa9d0d002104403d",       # Krenko           | Volcanic goblin warband
    "2e3f66103b0947c4",       # Thelon           | Steampunk fungus grove
]

ACTIVE_BUILD_JOB = "ed5878d9e9114ed0"   # Crystal Caverns — wait for this first


# ── Helpers ──────────────────────────────────────────────────────────────────

def get(path, **kw):
    return requests.get(BASE + path, timeout=30, **kw)

def post(path, **kw):
    return requests.post(BASE + path, timeout=30, **kw)


def comfy_busy():
    try:
        q = requests.get(COMFY + "/queue", timeout=10).json()
        return len(q.get("queue_running", [])) + len(q.get("queue_pending", [])) > 0
    except Exception:
        return False


def server_alive():
    try:
        requests.get(BASE + "/api/playstyles", timeout=5)
        return True
    except Exception:
        return False


def wait_for_job(job_id: str, label: str, timeout: int = 7200) -> bool:
    """Poll job status until done, error, or timeout. Returns True on success."""
    deadline = time.time() + timeout
    last_log = 0
    while time.time() < deadline:
        try:
            r = get(f"/api/deck/{job_id}/status")
            if r.status_code == 200:
                data = r.json()
                status = data.get("status", "")
                if status == "done":
                    log.info(f"  ✓ {label} [{job_id}] done")
                    return True
                if status in ("error", "cancelled"):
                    log.error(f"  ✗ {label} [{job_id}] ended with status={status}")
                    return False
                # Log progress every 60 s
                if time.time() - last_log > 60:
                    pct = data.get("progress", 0)
                    log.info(f"  … {label} [{job_id}] {status} {pct:.0f}%")
                    last_log = time.time()
            elif r.status_code == 404:
                log.warning(f"  Job {job_id} not found — may not have loaded yet")
        except Exception as e:
            log.debug(f"  poll error: {e}")
        time.sleep(10)
    log.error(f"  Timeout waiting for {label} [{job_id}]")
    return False


def wait_comfy_idle(label="active build"):
    """Block until ComfyUI queue is empty."""
    log.info(f"Waiting for ComfyUI to finish {label}…")
    while comfy_busy():
        time.sleep(15)
    log.info("ComfyUI queue is empty.")


def restart_server():
    """Kill the running server.py process and relaunch it."""
    import subprocess, os

    log.info("Restarting MythForge server…")

    # Kill existing server.py
    result = subprocess.run(
        [
            "powershell", "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
            "| Where-Object { $_.CommandLine -match 'server\\.py' } "
            "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
        ],
        capture_output=True,
    )
    log.info(f"Kill result: rc={result.returncode}")
    time.sleep(3)

    # Relaunch detached
    server_dir = r"C:\Users\rvn92\Documents\mtg_deck_builder"
    logfile = open(os.path.join(server_dir, "server_overnight.log"), "w")
    subprocess.Popen(
        [r"C:\Python314\python.exe", "server.py"],
        cwd=server_dir,
        stdout=logfile,
        stderr=logfile,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )

    # Wait for server to come up (up to 60 s)
    for _ in range(30):
        time.sleep(2)
        if server_alive():
            log.info("Server is back up.")
            return
    log.warning("Server did not respond within 60 s — continuing anyway")


def duplicate(source_job_id: str) -> str | None:
    r = post(f"/api/deck/{source_job_id}/duplicate")
    if r.status_code == 200:
        new_id = r.json()["new_job_id"]
        log.info(f"  Duplicated {source_job_id} → {new_id}")
        return new_id
    log.error(f"  Duplicate failed for {source_job_id}: {r.status_code} {r.text[:200]}")
    return None


def retheme(job_id: str) -> str | None:
    r = post(f"/api/deck/{job_id}/retheme", json={})
    if r.status_code == 200:
        new_id = r.json()["job_id"]
        log.info(f"  Retheme started: {new_id}")
        return new_id
    log.error(f"  Retheme failed for {job_id}: {r.status_code} {r.text[:200]}")
    return None


def rebuild(job_id: str) -> str | None:
    r = post(f"/api/deck/{job_id}/rebuild", json={"model_speed": "quality"})
    if r.status_code == 200:
        new_id = r.json()["job_id"]
        log.info(f"  Rebuild started: {new_id}")
        return new_id
    log.error(f"  Rebuild failed for {job_id}: {r.status_code} {r.text[:200]}")
    return None


def process_deck(source_job_id: str, label: str):
    log.info(f"\n{'='*60}")
    log.info(f"Processing: {label}  [{source_job_id}]")

    # 1. Duplicate (preserve original)
    copy_id = duplicate(source_job_id)
    if not copy_id:
        return

    # 2. Retheme the copy (fresh LLM names/prompts)
    retheme_id = retheme(copy_id)
    if not retheme_id:
        return
    if not wait_for_job(retheme_id, f"retheme/{label}"):
        return

    # 3. Rebuild (regenerate all card art from new prompts)
    rebuild_id = rebuild(retheme_id)
    if not rebuild_id:
        return
    if not wait_for_job(rebuild_id, f"rebuild/{label}", timeout=10800):  # 3 h max
        return

    log.info(f"  ✓✓ {label} complete — final job: {rebuild_id}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("MythForge overnight retheme+rebuild run starting")
    log.info(f"Decks queued: {len(SOURCE_DECKS) + 1} (including Crystal Caverns)")

    # Step 1: Wait for the currently active Crystal Caverns build
    log.info(f"\nStep 1: Waiting for active build [{ACTIVE_BUILD_JOB}] (Crystal Caverns) to finish…")
    wait_comfy_idle("Crystal Caverns")
    # Give the server time to finalize the job record
    time.sleep(30)

    # Step 2: Restart the server
    log.info("\nStep 2: Restarting MythForge server…")
    restart_server()
    time.sleep(5)

    # Step 3: Add the completed Crystal Caverns deck to the queue
    all_decks = SOURCE_DECKS + [ACTIVE_BUILD_JOB]

    # Load deck labels for nicer logging
    import os, json as _json
    labels = {}
    render_base = r"C:\Users\rvn92\Documents\mtg_deck_builder\renders"
    for jid in all_decks:
        try:
            dj = _json.loads(open(os.path.join(render_base, jid, "deck.json")).read())
            cmd = dj.get("commander", {})
            name = cmd.get("original_name", "?") if isinstance(cmd, dict) else "?"
            theme = (dj.get("theme") or "")[:40]
            labels[jid] = f"{name} / {theme}"
        except Exception:
            labels[jid] = jid

    # Step 4: Process each deck
    log.info(f"\nStep 3: Starting retheme+rebuild for {len(all_decks)} decks…")
    for i, jid in enumerate(all_decks, 1):
        lbl = labels.get(jid, jid)
        log.info(f"\n[{i}/{len(all_decks)}] {lbl}")
        try:
            process_deck(jid, lbl)
        except Exception as e:
            log.error(f"  Unhandled error for {jid}: {e}")
        # Short cool-down between decks
        time.sleep(10)

    log.info("\n" + "=" * 60)
    log.info("All decks processed. Overnight run complete.")


if __name__ == "__main__":
    main()
