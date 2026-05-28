# Server Cleanup Utilities

If you see orphaned `python.exe` processes in Task Manager but nothing on the taskbar, use these utilities to clean them up.

## Problem

When you start the server multiple times without properly stopping the previous instance, Python processes can become orphaned (running in the background but not visible on the taskbar).

**Symptoms:**
- `python.exe` appears in Task Manager
- No Python windows visible on taskbar
- Port 8000 already in use error when starting server
- Can't connect to server

## Solutions

### Option 1: Quick Kill (Batch Script)

**Double-click** `kill-servers.bat` to instantly kill all Python processes:

```batch
kill-servers.bat
```

This:
- ✓ Finds processes using ports 8000 (Myth Forge) and 8188 (ComfyUI)
- ✓ Kills them gracefully
- ✓ Cleans up any orphaned processes
- ✓ Safe to run anytime

### Option 2: Clean Start (Batch Script)

**Double-click** `start-clean.bat` to kill old instances and start fresh:

```batch
start-clean.bat
```

This:
- ✓ Kills any existing Python processes
- ✓ Waits for cleanup (2 seconds)
- ✓ Starts the server fresh
- ✓ Shows output window so you can see startup

**This is the recommended way to start the server** if you're getting "port already in use" errors.

### Option 3: Python Cleanup Script

Run `kill-servers.py` for more detailed process information:

```bash
python kill-servers.py
```

This:
- ✓ Lists all Python processes
- ✓ Shows command line for each
- ✓ Only kills server processes (safe)
- ✓ Shows which processes were killed

## Workflow

### When to Use:

1. **First time using the app today**: Just run `start-mythforge.bat` normally
2. **Getting "port already in use" error**: Run `kill-servers.bat`, then try again
3. **Python processes in Task Manager**: Run `kill-servers.bat`
4. **General cleanup before restarting**: Run `start-clean.bat`

### Step-by-Step:

```
1. See orphaned python.exe in Task Manager
   ↓
2. Double-click kill-servers.bat
   ↓
3. Confirm processes were killed
   ↓
4. Start the server normally with start-mythforge.bat
   ↓
5. ✓ Myth Forge runs cleanly
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

