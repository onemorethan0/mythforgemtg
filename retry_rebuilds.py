"""
retry_rebuilds.py

Re-runs ONLY the rebuild step for the 12 rethemed decks that failed last night
due to the req.commander_prompt bug (now fixed).  The rethemes all succeeded, so
we use those rethemed job IDs as the source for rebuilds.
"""

import time
import requests
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("retry_rebuilds.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

BASE = "http://localhost:8000"

# Rethemed job IDs → source label mapping (from overnight_retheme.log)
RETHEMED_JOBS = [
    # 1 & 2 already completed successfully — resuming from 3
    ("7437f3ab00c2487d", "Krenko / Hive City (Warhammer 40K)"),
    ("c5e4b9b8aeb14d28", "Urza / Green+Black Cyberpunk rave"),
    ("bc499887b7e24838", "Aurelia / Midgard Ragnarok Online"),
    ("c969b4bc949845cf", "Aang / Musical Performers"),
    ("792e11e445444d8a", "Syr Gwyn / Prontera Halloween RO"),
    ("3d06c4b9f1c447f5", "Najeela / Feudal Japanese samurai"),
    ("5ec251b50a9e4d40", "Krenko / Neon cyberpunk megacity"),
    ("a6bcbe1f4e98401c", "Kaalia / Purple+Black Dark Forest"),
    ("949a7e3e1f87475b", "Krenko / Volcanic goblin warband"),
    ("586deca5d30d4abf", "Thelon / Steampunk fungus grove"),
]


def wait_for_job(job_id, label, timeout=10800):
    deadline = time.time() + timeout
    last_log = 0
    while time.time() < deadline:
        try:
            r = requests.get(f"{BASE}/api/deck/{job_id}/status", timeout=30)
            if r.status_code == 200:
                data = r.json()
                status = data.get("status", "")
                if status == "done":
                    log.info(f"  ✓ {label} [{job_id}] done")
                    return True
                if status in ("error", "cancelled"):
                    log.error(f"  ✗ {label} [{job_id}] status={status}  err={data.get('error','')}")
                    return False
                if time.time() - last_log > 60:
                    log.info(f"  … {label} [{job_id}] {status}")
                    last_log = time.time()
        except Exception as e:
            log.debug(f"  poll error: {e}")
        time.sleep(10)
    log.error(f"  Timeout: {label} [{job_id}]")
    return False


def rebuild(source_id, label):
    r = requests.post(f"{BASE}/api/deck/{source_id}/rebuild",
                      json={"model_speed": "quality"}, timeout=30)
    if r.status_code == 200:
        job_id = r.json()["job_id"]
        log.info(f"  Rebuild started: {job_id}")
        return job_id
    log.error(f"  Rebuild failed for {source_id}: {r.status_code} {r.text[:200]}")
    return None


def main():
    log.info("=" * 60)
    log.info(f"Retry rebuilds — {len(RETHEMED_JOBS)} decks")

    for i, (source_id, label) in enumerate(RETHEMED_JOBS, 1):
        log.info(f"\n[{i}/{len(RETHEMED_JOBS)}] {label}")
        rebuild_id = rebuild(source_id, label)
        if rebuild_id:
            wait_for_job(rebuild_id, label)
        time.sleep(5)

    log.info("\n" + "=" * 60)
    log.info("All rebuilds complete.")


if __name__ == "__main__":
    main()
