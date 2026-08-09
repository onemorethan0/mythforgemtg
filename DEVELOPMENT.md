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

## Tests

```bash
python -m pytest tests -q          # everything: 49 app + 527 engine
python -m pytest tests/engine -q   # engine only
python tests/test_smoke.py         # app smoke tests, standalone runner
```

`tests/conftest.py` puts `src/` on the path and is what makes pytest *enforce* the app smoke
tests — their bodies append to a `_fails` list rather than asserting, so without that hook they
passed unconditionally. Engine tests use plain asserts and are excluded from the hook.

**CI runs `python -m pytest tests`, installed from `requirements.txt`.** It previously ran only
`python tests/test_smoke.py`, so the engine tests never ran there, and it installed an ad-hoc
package list — which hid `numpy` missing from the manifest even though `card_video.py` imports
it unguarded. The suite passes with no `ccm/` store and no `data/` dir, which is CI's state.

## Working on the engine

The MythGauntlet engine lives at `src/mythgauntlet/`. It keeps its `src/` layout deliberately:
`config.PROJECT_ROOT` resolves via `parents[2]`, so it lands on the repo root unchanged.

```bash
set PYTHONPATH=src
python -m mythgauntlet home        # dashboard: data, semantics coverage, gateways
python -m mythgauntlet doctor      # health check with suggested fixes
python -m mythgauntlet serve       # strength API on :8020 (what the app calls)
```

Three things about it that are invariants, not preferences:

1. **One analysis implementation.** The engine is the sole authority for bracket and strength.
   Myth Forge shipped a second heuristic estimator once; the copies drifted and it was deleted.
   Don't add another.
2. **No axis influences a bracket verdict until it's shown to separate the labeled anchors** —
   `python scripts/axis_separation.py`. Several plausible signals (the goldfish clock, every
   card-quality metric tried) measured as bracket-blind; one strong-looking signal had the
   wrong sign. See `docs/engine/STATUS.md`.
3. **Its compiled semantics are not in this repo** and `ccm/compiled/` is gitignored — see
   [docs/ENGINE_DATA.md](docs/ENGINE_DATA.md). Never commit a store here.

Engine-internal conventions (determinism through one seeded RNG, no card names in `sim/`,
ASCII-only CLI output) are in `docs/engine/ARCHITECTURE.md`.
