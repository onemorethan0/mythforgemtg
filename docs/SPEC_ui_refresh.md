# SPEC: UI refresh -- a deck workspace instead of a long page

Status: **draft for review, nothing implemented.** Written 2026-11-12. No GPU is needed for any of
this work: it is front end only, verified in the browser pane.

## 1. What this is for

**What you said:** the app has become crowded and hard to use. The example you gave: removing and
adding cards takes a lot of scrolling.

**My reading of the goal (correct me):** editing and judging a deck should feel like working in a
deck builder, not like reading a report. You should see your cards and the numbers about them
together, change the list in a click or two, and not have to remember where a panel lives.

**Assumptions, not yet confirmed:**
- The deck page (`StepDeck`) is the main problem. Home and History are secondary.
- Look and feel (dark theme, gold accent, card-art-first) stays; the layout and structure change.
- Desktop first (1024 px and wider). Narrow screens need to work, not be the design target.
- Nothing about what the app can do is removed. Every current control still exists after the refresh.

## 2. What is wrong now (measured, 2026-11-12, Locutus of Borg, 1024x768 window)

| Finding | Number |
|---|---|
| Height of the deck page | 9,896 px = **12.9 screens** |
| Where the first card appears | 5.9 screens down |
| Where "Edit deck" (add / remove / swap) is | 5.1 screens down |
| Where "Suggest upgrades" is | 4.9 screens down |
| Blocks stacked in one column before the cards | 17 (stats, 3D print, deck value, Measure + bracket, Upgrade, Sample hand, Edit deck, Change commander, Would this help, Test vs another deck, Pod check, Scout matchups, Scouting report, Ask the Mentor, then Organize / Download / Regenerate) |

So to edit the list you scroll five screens past the analysis tools, find the Edit panel, then
scroll another screen to see the card you are editing. The cards and the controls that change them
are never on screen together.

Structural causes in the code:
- **One 1,776-line file** (`StepDeck.jsx`) holds the whole deck page: 42 `useState` calls and 191
  inline `style={{...}}` objects. Every panel is stacked into one column inside it.
- **No design system.** Colours, spacing and type sizes are repeated as literals in every file.
  Tailwind 4 is installed but unused (0 `className`s in the main screens).
- **No routing.** `App.jsx` is a step state machine (`STEP.COMMANDER ... STEP.DECK, STEP.HISTORY`). The
  browser Back button leaves the app, and a deck has no URL you can bookmark or reload into.
- **Add / remove / swap live in three places:** the Edit deck panel, the Upgrade panel's apply
  button, and (since today) the card selection bar. None of them tells you the card count or
  legality as you change the list; the page-top count is 5 screens away.
- **Slow jobs have no home.** Measure, Upgrade, Scout and Pod check run for seconds to minutes; each
  panel shows its own spinner far from where you are looking.
- **Walls of text:** the Commander legality block can list dozens of cards in red in the sidebar.

## 3. Principles

1. **The card list is the product.** It is on screen first and stays on screen.
2. **Edit where you look.** Adding, removing and swapping happen on the list itself, and the card
   count and legality update in view.
3. **One thing at a time.** Analysis tools are tabs you open, not a column you scroll.
4. **Everything reachable in two clicks.** No control may need more than a tab click and a button.
5. **Structure before paint.** Tokens, shared components and routing come first, so later changes are
   cheap and the old look does not break halfway.

## 4. Approaches considered

| | Idea | Verdict |
|---|---|---|
| A | Keep the single column; collapse each panel into an accordion | Cheapest, but the list still starts below the fold and editing still needs scrolling. Treats the symptom. |
| B | Tabs across the top of the page (Cards / Analysis / Upgrade / Mentor) | Fixes the stack, but you cannot see the cards while reading the analysis, which is the thing you want when judging a swap. |
| **C** | **A deck workspace: card list as the main surface, a right-hand dock with one tool tab open at a time, a pinned add-a-card bar, inline remove, undo** | **Recommended.** Solves the scrolling, keeps cards and numbers together. |
| D | Full rewrite onto a component library and a router in one go | Biggest risk for the least extra benefit; the app keeps working only if nothing is half-migrated. |

## 5. Recommended design (C)

### 5.1 The deck workspace (replaces the `STEP.DECK` page)

```
+----------------------------------------------------------------------------------+
| <- Decks   Locutus of Borg  [WUB]  99/99 + commander   Legal v   [Export v] [...]  |  <- sticky strip
+--------------------------------------------------+-------------------------------+
| [ + Add a card...                        ] [Undo] | [Analyze][Upgrade][Mentor]    |
| Group: Type v   View: Grid | List   Search...    | [Export/Print]                |
|                                                  |                               |
|  Creatures (19)                                  |   (one tab, scrolls inside)   |
|  [card][card][card][card]   hover: x remove      |                               |
|  ...                                             |                               |
|  (the list scrolls; the strip and dock stay)     |   Running: Upgrade 3:12 [x]   |
+--------------------------------------------------+-------------------------------+
```

- **Sticky strip:** back to decks, commander name and colour pips, **card count against 100**
  ("99 + commander" or "101 -- 1 over"), a **legality chip** (green "Legal" or amber "2 issues",
  clicking opens the detail in the dock, never a wall of text in the sidebar), Export menu, overflow
  menu (duplicate, rebuild, 3D, delete).
- **Card list (main column):** unchanged grouping and views (Organize by type / role / colour / mana
  value; grid and list), but it fills the first screen. Each card has **hover actions**: select,
  remove (x), swap (opens the add bar pre-filled with "replace this").
- **Add-a-card bar, pinned above the list:** type to search, Enter adds, the count and legality chip
  update at once. This replaces the Edit deck panel. Remove-only and add-only (built 2026-11-11) stay
  as the underlying behaviour.
- **Undo:** every add, remove or swap raises "Removed X -- Undo" and the strip's Undo button reverts
  the last edit. Needs one small backend route (re-add / restore from the `applied_swaps` record).
- **Selection bar** (multi-select remove, animate, regenerate) stays, but docks above the list
  instead of floating over the Status pill.

### 5.2 The dock (right, about 380 px, collapsible)

One tab open at a time; the dock scrolls inside itself, the page never does.

| Tab | Holds (today's panels, unchanged in behaviour) |
|---|---|
| **Analyze** | Measure + bracket, Power profile, Deck breakdown, Deck value, Sample hand |
| **Upgrade** | Suggest upgrades (Advise), Would this help (card impact), Scouting report, Scout matchups, Test vs another deck, Pod check |
| **Mentor** | Ask the Mentor |
| **Make** | Download (PDF, images, animations), Regenerate, Art style, 3D print |

A tab shows its own sections as collapsed rows with a one-line summary each ("Bracket 2, Core --
measured Nov 11"), so a tab is a table of contents first and a report on demand.

**Job tray** at the bottom of the dock: every running job (Measure, Upgrade, Scout, Pod check) with
its elapsed time, the typical duration ("Upgrade about 6 min") and a cancel button. This is the fix
for "it runs forever": the wait is visible and bounded from anywhere in the workspace.

### 5.3 Other screens
- **Home:** four big cards stay. Add "Continue: <last deck>" so the usual path is one click.
- **History:** keep the family grouping and the new select-and-export bar; add a search box and a
  sort (recent, name, bracket). Layout otherwise unchanged.
- **Build / theme / face steps:** unchanged in phase 1; they take the new tokens and shell only.
- **Collection manager:** out of scope for this refresh.

### 5.4 Foundations (these come first and change nothing you can see)
- **Design tokens** as CSS variables in `index.css`: colours (surface, border, text, accent, ok /
  warn / bad), spacing scale, radii, type scale. The existing dark and gold palette becomes the
  token values.
- **Shared components**, each one small and tested: `Button`, `Panel` (collapsible, with a summary
  line), `Chip`, `Tabs`, `Menu` (the Export menu is the first customer), `Dock`, `JobTray`. Styled with
  the tokens through small CSS files or Tailwind classes -- see decision 2.
- **Routing:** a hash route per screen (`#/deck/<id>`, `#/history`, `#/collection`) so Back works,
  a deck can be bookmarked, and a reload lands where you were. Replaces the step state machine
  for navigation; the build wizard keeps its internal steps.

## 6. Phases (each one ships and leaves the app working)

| Phase | Work | Visible result |
|---|---|---|
| 0 | Tokens, shared components, hash routing. Existing screens keep their look. | None, except Back button and deep links |
| 1 | Workspace shell: sticky strip, dock with four tabs, existing panels moved in unchanged | Cards appear on the first screen; no more five-screen scroll |
| 2 | Add-a-card bar, hover remove, swap-in-place, undo; Edit deck panel retired | Add and remove with no scrolling, with the count in view |
| 3 | Legality chip and popover; stats sidebar becomes the strip; panel summaries; job tray | Walls of text gone; waits visible |
| 4 | Home "continue", History search / sort | Smaller wins |
| 5 | Narrow screens: dock becomes a bottom sheet under 1100 px | Usable on a small window |

Phase 1 alone fixes the complaint you raised; phases 2 and 3 make it pleasant.

## 7. How we will know it worked (acceptance)

Measured on the same Locutus deck at 1024x768 with the browser pane, before and after:
1. The first card is on screen without scrolling. (Now: 5.9 screens down.)
2. Removing a card: 2 interactions (hover, click x) with **0 scrolls**; the count in the strip changes
   in view. Adding a card: type, Enter.
3. Any panel reachable in at most 2 clicks.
4. The page itself does not scroll; the card list and the dock scroll inside their own areas.
5. No horizontal scroll at 1024 px.
6. **Parity checklist:** a table of every control on today's deck page (78 visible controls counted on 2026-11-12, more once panels are opened), each ticked off
   against the new layout. Nothing is dropped silently.
7. Back button returns to the previous screen; reloading `#/deck/<id>` reopens that deck.
8. Keyboard: Tab reaches every action; Esc closes menus and the dock tab popovers.
9. Existing front-end tests (vitest) and the 3,946 backend tests still pass; new components have tests.

## 8. Risks and how they are handled
- **Refactoring the 1,776-line `StepDeck`.** Moved in slices: first lift each panel into its own
  component (they mostly are already), then the shell wraps them. No panel logic is rewritten in
  phase 1.
- **Regressions in a screen with 78 visible controls.** The parity checklist plus a browser-pane click-through
  of each tab after every phase.
- **A half-migrated look.** Tokens first and the old inline values mapped onto them, so old and new
  components match throughout.
- **Undo needs the server.** One new route, tested like `apply-swap`.
- **Cost of the work.** Front-end only; no GPU, no engine. Rough effort: phase 0 two days, 1 two days,
  2 one day, 3 one day, 4 and 5 a day each.

## 9. Decisions I need from you
1. **Dock on the right (recommended) or along the bottom?** Right keeps the list tall and the analysis
   beside it; bottom suits narrow windows but squeezes the list.
2. **Styling:** use the Tailwind already installed (utility classes, fastest to write) or plain CSS
   files with the tokens (fewer concepts, no build coupling)? I lean Tailwind since it is already
   there and unused.
3. **Routing:** add `react-router` (one dependency, standard) or a 40-line hash router of our own?
   I lean the small own router: three routes, no new dependency.
4. **Which panels do you really use?** Anything you never open can move under a "More" row instead of
   getting a tab section. My guess is Duel, Pod check and Scout matchups; tell me if wrong.
5. **Default card view while editing:** grid with art (today) or the compact list? I would default the
   list when you are editing and keep the grid for browsing.
6. **Brand:** keep the dark, gold, art-heavy look as is, or is part of "crowded" the visual density
   itself (borders, badges, many accent colours)? If so, phase 0 also thins the palette.

## 10. Out of scope
The collection manager, the build wizard's internals, card-render art and any GPU work, a mobile app,
and anything that changes what the engine or Mentor calculate.
