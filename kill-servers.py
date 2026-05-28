#!/usr/bin/env python3
"""
Utility to kill orphaned Python processes (Myth Forge and ComfyUI servers).
Useful when servers don't show on taskbar but are still running.
"""

import subprocess
import sys
import time

def get_python_pids():
    """Get all Python process IDs."""
    try:
        output = subprocess.check_output('tasklist /FO CSV /NH', shell=True, text=True)
        lines = output.strip().split('\n')
        pids = []
        for line in lines:
            parts = line.split(',')
            if len(parts) >= 2:
                name = parts[0].strip('"')
                if 'python' in name.lower():
                    try:
                        pid = int(parts[1].strip('"'))
                        pids.append(pid)
                    except ValueError:
                        pass
        return pids
    except Exception as e:
        print(f"Error getting process list: {e}")
        return []

def get_process_info(pid):
    """Get command line for a process."""
    try:
        output = subprocess.check_output(
            f'wmic process where ProcessId={pid} get CommandLine',
            shell=True,
            text=True
        )
        lines = output.strip().split('\n')
        if len(lines) > 1:
            return lines[1].strip()
        return "unknown"
    except Exception:
        return "unknown"

def kill_pid(pid):
    """Kill a process by PID."""
    try:
        subprocess.run(f'taskkill /PID {pid} /F /T', shell=True, check=False)
        return True
    except Exception:
        return False

def main():
    print("\n" + "="*50)
    print("  MYTH FORGE - Kill Orphaned Servers")
    print("="*50 + "\n")

    pids = get_python_pids()

    if not pids:
        print("[OK] No Python processes found\n")
        return

    print(f"Found {len(pids)} Python process(es):\n")

    killed_count = 0
    for pid in pids:
        cmd = get_process_info(pid)

        # Kill if it looks like a server
        if 'server.py' in cmd or 'main.py' in cmd or 'comfyui' in cmd.lower():
            print(f"[KILL] PID {pid}: {cmd[:70]}...")
            if kill_pid(pid):
                killed_count += 1
                print(f"       ✓ Killed")
            else:
                print(f"       ✗ Failed to kill")
        else:
            print(f"[SKIP] PID {pid}: {cmd[:70]}...")

    print(f"\n[OK] Killed {killed_count} server process(es)")

    if killed_count > 0:
        print("\nWaiting for cleanup...")
        time.sleep(2)

    print("\n")

if __name__ == '__main__':
    main()
