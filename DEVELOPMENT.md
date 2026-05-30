# Development

Architecture, key files, and conventions live in **[CLAUDE.md](./CLAUDE.md)**.
Mandatory change checklist + standards: **[docs/DEVELOPMENT_GUIDELINES.md](docs/DEVELOPMENT_GUIDELINES.md)**.

## Edit → see changes
- **Backend (Python):** edit, then **restart** the server (`manage.bat` → 2 Clean Start, or kill the PID on :8000 and `python server.py`). Nothing hot-reloads Python here.
- **Frontend (React):** edit `frontend/src/`, then either rebuild (`cd frontend && npm run build`) or just restart the server — it auto-rebuilds on startup when `frontend/src` is newer than `frontend/dist`. **Hard-refresh** the browser (`Ctrl+Shift+R`) to drop the cached bundle.

## Hot reload (active frontend work)
```bash
make frontend-dev     # Vite dev server on http://localhost:5173 (HMR), proxies API to :8000
python server.py      # API on :8000 (run in a second terminal)
```
Other make targets: `make frontend-build`, `make rebuild`.

## When changes don't appear
Almost always a stale browser bundle → hard-refresh (`Ctrl+Shift+R`). Otherwise: confirm the file saved, the server restarted (watch its startup log for the rebuild line), and check the browser console (`F12`) for JS errors.
