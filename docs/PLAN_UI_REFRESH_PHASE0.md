# UI refresh, Phase 0 (foundations) Implementation Plan

> **For agentic workers:** execute task by task; steps use checkbox syntax. Executed natively in one session (the user approved the spec and said to start).

**Goal:** Add design tokens, a small set of shared UI components and hash routing, without changing how any existing screen looks.

**Architecture:** Tokens are CSS variables in one file; shared components are small React components styled by classes that read the tokens; routing is a pure parse/format module plus one effect in `App.jsx` that keeps the URL hash and the existing step state in sync. Existing screens adopt the components only where the swap is visually identical.

**Tech Stack:** React 19, Vite, vitest (pure-logic tests only: there is no jsdom or testing-library), plain CSS variables. Tailwind stays installed but unused (spec decision 2 default: tokens, not utility classes, for phase 0).

**Spec:** `docs/SPEC_ui_refresh.md` (section 5.4 and phase 0 of section 6).

## Global Constraints

- "Existing screens keep their look" (spec section 6, phase 0): no visible change except the Back button and deep links.
- Dark and gold palette becomes the token values, copied from the literals already in the code (below).
- The Back button must work and `#/deck/<id>` must reload into that deck (spec acceptance 7).
- No new dependency (spec decision 3 default: our own small router).
- Existing vitest tests and the 3,946 backend tests keep passing. No GPU, no engine.

## Review Focus

1. A hash with a malformed or unknown deck id (`#/deck/zzz`) opens Home, never a crash or a blank screen.
2. A hash for a deck that was deleted (404): a toast and Home, not an endless spinner.
3. Pressing Back while a build is running must not drop the user out of the build (routes are ignored while `STEP.BUILDING`).
4. The app writing the hash itself must not trigger a second load of the same deck (no loop).
5. A saved active job (`sessionStorage`) and a pasted `#/deck/<id>` disagree: the hash wins; an empty hash keeps today's reconnect behaviour.

## File structure

| File | Responsibility |
|---|---|
| `frontend/src/styles/tokens.css` (new) | every colour, spacing, radius and font-size variable |
| `frontend/src/index.css` (modify) | imports `styles/tokens.css` |
| `frontend/src/components/ui/ui.css` (new) | classes for Button, Chip, Panel, Menu, Tabs, reading only tokens |
| `frontend/src/components/ui/{Button,Chip,Panel,Menu,Tabs}.jsx` (new) | the five components |
| `frontend/src/components/ui/tabsNav.js` (new) | arrow-key logic for Tabs, pure |
| `frontend/src/utils/router.js` (new) | `parseHash`, `formatRoute`: pure |
| `frontend/src/App.jsx` (modify) | the hash <-> step sync effect |
| `frontend/src/components/ExportMenu.jsx`, `EditDeckPanel.jsx` (modify) | first consumers of Menu / Button |

Dock and JobTray are not built here: nothing uses them until phase 1 and 3 (YAGNI).

---

### Task 1: Design tokens

**Files:** create `frontend/src/styles/tokens.css`, `frontend/src/styles/tokens.test.js`; modify `frontend/src/index.css`.

**Interfaces:** Produces the CSS variables below on `:root`; every later task reads them as `var(--name)`.

- [ ] **Step 1: Write the failing test** `tokens.test.js` (vitest, reads the CSS as text): `tokens define the palette` asserts each of these declarations is present with exactly these values (they are the literals used across the app today): `--surface-0: #0c0a09`, `--surface-1: #1c1917`, `--surface-2: #292524`, `--border: #44403c`, `--text: #f5f5f4`, `--text-muted: #a8a29e`, `--text-faint: #78716c`, `--accent: #eab308`, `--accent-strong: #ca8a04`, `--accent-bg: #422006`, `--accent-text: #fde047`, `--ok: #86efac`, `--ok-strong: #15803d`, `--ok-bg: #052e16`, `--bad: #fca5a5`, `--bad-strong: #b91c1c`, `--bad-bg: #450a0a`, `--info: #93c5fd`, `--info-strong: #1d4ed8`, `--info-bg: #1e3a5f`, `--warn: #fcd34d`; spacing `--space-1: 4px` `--space-2: 8px` `--space-3: 12px` `--space-4: 16px` `--space-6: 24px`; radii `--radius-sm: 6px` `--radius-md: 8px` `--radius-lg: 10px`; type `--text-xs: 11px` `--text-sm: 12px` `--text-md: 13px` `--text-lg: 16px`. A second test `index.css imports the tokens` asserts `index.css` contains `@import './styles/tokens.css'`.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/styles` -> FAIL (file missing).
- [ ] **Step 3: Create `tokens.css`** with a single `:root { ... }` block holding exactly the variables above, and add the `@import` as the first line of `index.css`.
- [ ] **Step 4: Run** the same command -> PASS; `npm run build` succeeds.
- [ ] **Step 5: Commit** `git add frontend/src && git commit -m "UI: design tokens"`.

### Task 2: Shared components

**Files:** create `components/ui/{ui.css,Button.jsx,Chip.jsx,Panel.jsx,Menu.jsx,Tabs.jsx,tabsNav.js,tabsNav.test.js}`; modify `ExportMenu.jsx`, `EditDeckPanel.jsx`.

**Interfaces:**
- `Button({ variant = 'neutral', size = 'md', ...buttonProps })`, variants `neutral | primary | danger | ok | info | ghost`; renders `<button className="ui-btn ui-btn--{variant} ui-btn--{size}">`.
- `Chip({ tone = 'neutral', children })`, tones `neutral | ok | warn | bad | info`.
- `Panel({ title, summary, defaultOpen = true, children })`: a titled box; clicking the header toggles; `summary` shows beside the title when collapsed.
- `Menu({ label, children, align = 'left' })`: a button that opens a popover; closes on outside click and Esc; `children` is the popover content.
- `Tabs({ tabs: {key, label}[], value, onChange })`: a `role="tablist"`; Left/Right arrows move, Home/End jump.
- `nextTab(keys: string[], current: string, key: string): string`: pure arrow-key logic in `tabsNav.js`.

- [ ] **Step 1: Write the failing test** `tabsNav.test.js`: `nextTab(['a','b','c'],'a','ArrowRight') === 'b'`; wraps `('c','ArrowRight') === 'a'` and `('a','ArrowLeft') === 'c'`; `Home -> 'a'`, `End -> 'c'`; any other key returns `current`; an unknown `current` returns the first key.
- [ ] **Step 2: Run** `npx vitest run src/components/ui` -> FAIL.
- [ ] **Step 3: Implement** `nextTab` and the five components; `ui.css` styles use only `var(--...)` from Task 1 and map the variants to today's colours (`primary`: `--accent-bg` / `--accent-strong` / `--accent-text`; `danger`: `--bad-bg` / `--bad-strong` / `--bad`; `ok`: `--ok-bg` / `--ok-strong` / `--ok`; `info`: `--info-bg` / `--info-strong` / `--info`; `neutral` and `ghost`: `--surface-1` or transparent, `--border`, `--text-muted`). Import `ui.css` from `main.jsx`.
- [ ] **Step 4: Migrate two consumers with no visible change:** `ExportMenu` uses `Menu` (button and popover) and `Button`; `EditDeckPanel`'s Remove only / Add only / Swap use `Button` (`danger`, `ok`, `primary`).
- [ ] **Step 5: Run** vitest, eslint (`npx eslint src`), `npm run build` -> all pass.
- [ ] **Step 6: Verify in the browser pane** that the Export menu and the Edit deck buttons look as before (screenshot, same colours), and that Esc and outside-click close the menu.
- [ ] **Step 7: Commit** `git commit -m "UI: shared Button, Chip, Panel, Menu, Tabs"`.

### Task 3: Hash routing

**Files:** create `frontend/src/utils/router.js`, `frontend/src/utils/router.test.js`; modify `frontend/src/App.jsx`.

**Interfaces:**
- `parseHash(hash: string): { name: 'home'|'history'|'collection'|'deck', id: string|null }`; unknown or malformed input (including a deck id that is not 16 lowercase hex characters) returns `{ name: 'home', id: null }`.
- `formatRoute(name: string, id?: string): string` returns `#/`, `#/history`, `#/collection` or `#/deck/<id>`.

- [ ] **Step 1: Write the failing tests** (`router.test.js`): `''`, `'#'`, `'#/'` parse to home; `'#/history'` -> history; `'#/collection'` -> collection; `'#/deck/0123456789abcdef'` -> deck with that id; `'#/deck/zzz'`, `'#/deck/'`, `'#/deck/0123456789abcdef/extra'`, `'#/nonsense'` -> home; `formatRoute('deck','0123456789abcdef') === '#/deck/0123456789abcdef'`; `formatRoute('deck')` (no id) throws; `parseHash(formatRoute(n, id))` round-trips for every route.
- [ ] **Step 2: Run** `npx vitest run src/utils/router.test.js` -> FAIL.
- [ ] **Step 3: Implement** the two functions (a regex `^#\/deck\/([0-9a-f]{16})$` for the deck route).
- [ ] **Step 4: Run** -> PASS.
- [ ] **Step 5: Wire `App.jsx`:** (a) write: an effect on `[step, mode, jobId]` sets `location.hash` to `formatRoute(...)` for `STEP.DECK` with a `jobId` (deck), `STEP.HISTORY` (history), `mode === 'collection'` (collection) and the landing hub (home); other steps leave the hash alone; it assigns only when the value differs. (b) read: on `hashchange` (and once at mount, before the existing reconnect logic) parse the hash; ignore it while `step === STEP.BUILDING`; `deck` calls the existing `handleLoadHistoricDeck(id)` unless that deck is already shown; `history` sets `STEP.HISTORY`; `collection` and `home` call the existing handlers for them. A load that fails (404) raises `notify('error', ...)` and falls back to Home. At mount, a non-home hash wins over the saved active job; an empty hash keeps today's behaviour.
- [ ] **Step 6: Verify in the browser pane (checklist):** open a deck from History -> the URL becomes `#/deck/<id>`; reload -> the same deck opens; Back -> History; Back again -> Home; `#/deck/zzz` -> Home; `#/deck/ffffffffffffffff` (no such deck) -> toast and Home; start a build and press Back -> still building; deep link into a deck and press the in-app Home button -> `#/`.
- [ ] **Step 7: Commit** `git commit -m "UI: hash routing (Back button, deep links)"`.

### Task 4: Close the phase

**Files:** modify `docs/SPEC_ui_refresh.md`, `docs/DEVELOPMENT_PLAN.md`.

- [ ] **Step 1:** Compare Home, History and the top of a deck page before and after in the browser pane; nothing may differ visually.
- [ ] **Step 2:** Run `npx eslint src`, `npx vitest run`, `python -m pytest tests -q`; all pass.
- [ ] **Step 3:** Mark phase 0 done in the spec's phase table and add a progress-log line to the development plan.
- [ ] **Step 4: Commit and push**; check `gh run list`.
