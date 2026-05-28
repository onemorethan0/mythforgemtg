# Server Cleanup Utilities

If you see orphaned `python.exe` processes in Task Manager but nothing on the taskbar, use these utilities to clean them up.

## Problem

When you start the Myth Forge server multiple times without properly stopping the previous instance, Python processes can become orphaned (running in the background but not visible on the taskbar).

**Symptoms:**
- `python.exe` appears in Task Manager
- No Python windows visible on taskbar
- Port 8000 already in use error when starting Myth Forge
- Can't connect to server

**Important:** These tools manage ONLY the Myth Forge server on port 8000. ComfyUI (port 8188) and Ollama (port 11434) are separate services and won't be killed.

## Solutions

### Option 1: Check Status First (Recommended)

**Double-click** `check-servers.bat` to see what's running:

```batch
check-servers.bat
```

Shows:
- ✓ ComfyUI status (port 8188)
- ✓ Myth Forge status (port 8000)
- ✓ Ollama status (port 11434)
- ✓ Any orphaned Python processes

**Do this first to understand the current state.**

### Option 2: Kill Only Myth Forge

**Double-click** `kill-servers.bat` to kill orphaned Myth Forge:

```batch
kill-servers.bat
```

This:
- ✓ Kills ONLY Myth Forge process on port 8000
- ✓ Leaves ComfyUI and Ollama running
- ✓ Safe to run anytime
- ✓ Cleans up orphaned processes

### Option 3: Clean Start (Batch Script) - RECOMMENDED

**Double-click** `start-clean.bat` to kill old Myth Forge and start fresh:

```batch
start-clean.bat
```

This:
- ✓ Kills ONLY the old Myth Forge server (port 8000)
- ✓ Does NOT touch ComfyUI or Ollama
- ✓ Waits for cleanup (2 seconds)
- ✓ Starts Myth Forge fresh
- ✓ Shows output window so you can see startup

**This is the recommended way to start the Myth Forge server.**

### Option 4: Python Cleanup Script

Run `kill-servers.py` for more detailed process information:

```bash
python kill-servers.py
```

This:
- ✓ Lists all Python processes
- ✓ Shows command line for each
- ✓ Only kills server processes (safe)
- ✓ Shows which processes were killed

## Three Separate Services

Myth Forge requires THREE services to be running:

| Service | Port | Status | How to Start |
|---------|------|--------|--------------|
| **ComfyUI** | 8188 | Separate window | Must be started manually |
| **Ollama** | 11434 | Background | Starts automatically or manually |
| **Myth Forge** | 8000 | Main app | `start-clean.bat` |

## Workflow

### Quick Start (Every Day):

1. **Check status**: `check-servers.bat` (see what's running)
2. **Start ComfyUI**: Open separate terminal/window, run ComfyUI
3. **Start Myth Forge**: Double-click `start-clean.bat`
4. **Open browser**: Navigate to `http://localhost:8000`
5. **Done!** ✓

### If Myth Forge Won't Start:

```
1. Double-click: check-servers.bat
   ↓
2. See "Myth Forge: ✓ RUNNING" or "✗ NOT RUNNING"?
   ↓
3. If ✓ RUNNING but won't work:
   - Double-click: kill-servers.bat
   - Wait 2 seconds
   ↓
4. Double-click: start-clean.bat
   ↓
5. ✓ Myth Forge should start cleanly
```

### Common Scenarios:

**Scenario: Getting "Port 8000 already in use"**
```
1. check-servers.bat
2. See Myth Forge still running
3. kill-servers.bat
4. start-clean.bat
```

**Scenario: Restarting everything**
```
1. Close ComfyUI window (Ctrl+C)
2. kill-servers.bat (kill Myth Forge)
3. Restart ComfyUI in separate window
4. start-clean.bat (start Myth Forge)
```

**Scenario: Daily use**
```
- ComfyUI: Already running from yesterday
- Myth Forge: start-clean.bat
- Ollama: Auto-starts, no action needed
```

## Task Manager Guide

To see what Python processes are running:

1. **Open Task Manager** (Ctrl+Shift+Esc)
2. **Click "Processes" tab**
3. **Look for** `python.exe` or `cmd.exe`
4. **Right-click → End Task** if needed

**Note:** The cleanup scripts automate this for you.

## Port Conflicts

If you get `Port 8000 already in use`:

```
ERROR: Address already in use
```

**Fix:**
```bash
# Find and kill the process using port 8000
netstat -ano | find ":8000"
# Note the PID (last column)
taskkill /PID <PID> /F
```

Or just run: `kill-servers.bat`

## Preventing Orphaned Processes

### Best Practices:

1. **Always close servers properly**
   - Press `Ctrl+C` in the terminal window
   - Wait for "shutdown complete" message

2. **Before restarting, run cleanup**
   ```bash
   start-clean.bat
   ```

3. **Check before starting**
   ```bash
   netstat -ano | find ":8000"
   # Should show nothing if port is free
   ```

4. **Use `start-clean.bat` as your default**
   - It automatically handles cleanup
   - No need to manually kill processes

## Script Details

### kill-servers.bat
- Finds processes on ports 8000 and 8188
- Gracefully kills them with timeout
- Platform: Windows batch script
- Safe: Only kills known server ports

### start-clean.bat
- Kills all Python processes
- Waits 2 seconds for cleanup
- Starts fresh server
- Platform: Windows batch script
- Safe: Clean restart workflow

### kill-servers.py
- Lists all Python processes
- Shows command line details
- Only kills `server.py` or `main.py` processes
- Platform: Cross-platform (Windows/Mac/Linux)
- Safe: Selective killing

## Troubleshooting

### "Process not killed"
→ Run with Administrator: Right-click → Run as Administrator

### "Port still in use after kill"
→ Wait 10 seconds and try again
→ Check Task Manager to confirm process is gone

### "Can't run batch scripts"
→ Use Python version instead: `python kill-servers.py`
→ Or use manual Task Manager → End Task

### Multiple Python processes
→ Run the script again to get all of them
→ Check Task Manager to verify cleanup

## Advanced: Manual Cleanup

If none of the scripts work:

1. **Open Task Manager** (Ctrl+Shift+Esc)
2. **Click "Processes" tab**
3. **Find** `python.exe` entries
4. **Click to select**
5. **Click "End Task" button**
6. **Repeat for all python.exe entries**

## Still Having Issues?

### Check if ports are listening:
```bash
netstat -ano | find ":8000"
netstat -ano | find ":8188"
```

### Check running Python processes:
```bash
tasklist | find "python"
```

### Nuclear option (kills all Python):
```bash
taskkill /IM python.exe /F
```

---

**Pro Tip:** Create a shortcut to `start-clean.bat` on your desktop for quick access!

