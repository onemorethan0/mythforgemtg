# Myth Forge Development Guide

This guide explains how to develop and test changes to Myth Forge.

## Quick Start: Making Changes

### Frontend Changes (React/Vite)

1. **Edit frontend code** in `frontend/src/`
2. **Restart the server**: Stop `python server.py` and run it again
3. **Hard refresh the browser**: `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (macOS)

The server will automatically rebuild the frontend on startup if source files have changed.

### Backend Changes (Python)

1. **Edit backend code** in `server.py`, `image_gen.py`, etc.
2. **Restart the server**: Stop `python server.py` and run it again

The API will pick up changes on restart.

## Development Workflow

### Option A: Standard Development (Recommended for Most Tasks)

The default workflow is simple:
1. Make changes to frontend or backend
2. Restart `python server.py`
3. The server automatically rebuilds the frontend if needed
4. Hard refresh the browser to see changes

**Pros**: Simple, no extra tools needed, works for both frontend and backend
**Cons**: Brief downtime when restarting server

### Option B: Hot Reload (For Active Frontend Development)

If you're actively editing the frontend and want to see changes in real-time:

**Terminal 1 - Start the dev server** (watches for changes, rebuilds instantly):
```bash
make frontend-dev
```
This starts Vite on `http://localhost:5173` with hot module replacement.

**Terminal 2 - Start the API server**:
```bash
python server.py
```
The API runs on `http://localhost:8000`.

**Open http://localhost:5173** in your browser. Changes to React components will hot-reload instantly.

**Note**: The dev server proxies API calls to `localhost:8000`, so both servers need to be running.

## Common Issues

### Changes Don't Appear After Restart

**Problem**: You restarted the server but the browser still shows old content.

**Solution**: Hard refresh the browser!
- **Windows/Linux**: `Ctrl+Shift+R`
- **macOS**: `Cmd+Shift+R`

This clears the browser cache and forces it to download the latest files from the server.

Regular refresh (`F5` or `Ctrl+R`) may not be enough if the browser cached the old build.

### "Frontend is up to date" but Changes Aren't Showing

**Most likely**: You need to hard refresh the browser (see above).

**Also check**:
1. Did you save the file? (Check file timestamps: `ls -la frontend/src/App.jsx`)
2. Are you editing the right file? (Check for multiple copies of the same component)
3. Is the browser using the correct localhost address? (Check URL: `http://localhost:8000`)

### "Frontend build timed out" Message

**Problem**: The frontend build took longer than 120 seconds.

**Solution**: 
- Check system resources (CPU, disk space)
- Try `make frontend-build` manually to see error details
- Increase timeout in `server.py` line ~204 if needed

### Changes to `package.json` Don't Take Effect

**Problem**: You added a new dependency to `frontend/package.json` but it's not loading.

**Solution**:
1. Delete `node_modules`: `rm -rf frontend/node_modules`
2. Reinstall dependencies: `cd frontend && npm install`
3. Rebuild: `npm run build`
4. Restart the server: `python server.py`

## Build Commands Reference

```bash
# Frontend only
make frontend-build      # Rebuild frontend for production (updates dist/)
make frontend-dev        # Start Vite dev server (hot reload on localhost:5173)
make frontend-rebuild    # Clean rebuild (deletes dist/ first)

# Shortcuts
make build              # Same as frontend-build
make dev                # Same as frontend-dev
make rebuild            # Same as frontend-rebuild
```

## Understanding the Build Process

### Production Build (Used by Server)

```
frontend/src/ (React components) 
    ↓ (npm run build)
frontend/dist/ (Bundled HTML/CSS/JS)
    ↓ (served by server.py)
http://localhost:8000/ (browser)
```

The server serves the built files from `frontend/dist/`. This is fast and production-ready.

### Development Mode (Optional)

```
frontend/src/ (React components)
    ↓ (Vite dev server with hot reload)
http://localhost:5173 (browser)
    ↓ (proxies API calls)
http://localhost:8000 (API server)
```

The Vite dev server watches your files and hot-reloads instantly. Useful for rapid development.

## Automatic Frontend Build on Startup

Every time you start the server, it checks if the frontend needs rebuilding:

```
Server starts
    ↓
Check frontend/src vs frontend/dist modification times
    ↓
If source newer than build: npm run build
    ↓
Print status: "[OK] Frontend is up to date" or "[OK] Frontend rebuilt successfully"
    ↓
Server ready
```

This ensures the frontend is always in sync with the source code.

## Tips for Development

### Use a Text Editor with Auto-Save

If your editor auto-saves, the server will detect changes and rebuild automatically.

### Check Server Startup Messages

The server prints:
- `[OK] Frontend is up to date` — No rebuild needed
- `[!] Frontend source changed — rebuilding...` — Detected changes, rebuilding
- `[OK] Frontend rebuilt successfully` — Build succeeded

If you don't see a rebuild message, check:
1. Did you actually save the file?
2. Is the file in `frontend/src/`?
3. Check file timestamps: `ls -la frontend/src/`

### Monitor Browser Errors

Open the browser console (`F12`) to see JavaScript errors:
- Syntax errors in React components
- Missing imports
- API connection failures

### Use Network Tab for Cache Issues

Open DevTools Network tab (`F12` → Network):
1. Refresh the page
2. Look for `index.html` response
3. Check `Cache-Control` header
4. If cached, do a hard refresh (`Ctrl+Shift+R`)

## Workflow Examples

### Example 1: Update App Header Text

1. Edit `frontend/src/App.jsx`, change header text
2. Save file
3. Restart server: `python server.py`
4. Server detects changes and rebuilds (prints `[!] Frontend source changed — rebuilding...`)
5. In browser, hard refresh: `Ctrl+Shift+R`
6. See your changes on the page

### Example 2: Add New API Endpoint

1. Edit `server.py`, add new `@app.get("/api/...")` endpoint
2. Restart server (Python picks up changes)
3. Frontend can now call the new endpoint

### Example 3: Active Component Development

Use hot reload for faster iteration:

**Terminal 1**:
```bash
make frontend-dev
# Starts: http://localhost:5173
```

**Terminal 2**:
```bash
python server.py
# Starts: http://localhost:8000 (API)
```

Open http://localhost:5173 in browser. Every time you save a component, it hot-reloads in <100ms.

## Troubleshooting Checklist

When changes don't appear:

- [ ] Did you save the file?
- [ ] Did you restart the server (for backend) or save (for frontend with Vite)?
- [ ] Did you hard refresh the browser (`Ctrl+Shift+R` or `Cmd+Shift+R`)?
- [ ] Check browser console (`F12`) for JavaScript errors
- [ ] Check server terminal for build errors
- [ ] Are you looking at the right file? (Check browser URL, file paths)
- [ ] Is the server actually restarted? (Look for startup messages)
- [ ] Try clearing browser cache completely (`F12` → Storage → Clear Site Data)

## Getting Help

1. **Check server startup messages**: They tell you if the frontend built successfully
2. **Check browser console**: `F12` → Console tab shows JavaScript errors
3. **Check network requests**: `F12` → Network tab shows if files are being loaded/cached
4. **Check file system**: Verify files are where you think they are (`ls -la frontend/src/`)

## Next Steps

- [INSTALL.md](./INSTALL.md) — Installation and setup
- [README.md](./README.md) — Project overview
- [MODELS.md](./MODELS.md) — AI model setup

