# Rules audit — closing the gap between the engine and the actual Comprehensive Rules

*2026-08-24.*

## The question that started this

The Deck Mentor's Phase 0 (`docs/SPEC_deck_mentor.md`) built a real rulings + Comprehensive
Rules corpus (`data/rulings.py`) so the mentor's chat answers could be grounded instead of
guessed. Using the finished mentor, a natural next question came up: **the simulation/bracket
engine itself never references that corpus at all — so how has it ever been "judging games"
correctly?**

Checked directly: grep for `data.rulings` across `sim/`, `ratings/`, `semantics/` returns
zero hits. The corpus is wired into exactly one place — the mentor's own tools
(`lookup_rulings`, `search_rules`, `get_rule`) — and has no path into the code that actually
plays out goldfish games and estimates brackets. That code has always worked a different way:
every rule it needs (mana value, combat targeting, loop determinism, color identity, the
first-turn draw skip) is hand-encoded as Python by whoever wrote that feature, with the real
CR checked **by hand, once, at the time**, and cited in a comment. That's a reasonable way to
build a rule into code. It is not a way to keep it correct, because a rule number is not a
stable identity — **WotC renumbers the Comprehensive Rules as new mechanics are added** — and
nothing has ever gone back to re-check an old citation against a current corpus.

This doc is that re-check, plus a reusable tool (`scripts/rules_audit.py`) so it doesn't have
to be a one-off.

## What was found

**1. Two citations had gone stale from a WotC renumbering, though the LOGIC they supported was
still correct.**

`semantics/combo_rules.py` and `data/spellbook.py` both cited **CR 720** for loop-determinism
handling (an optional loop can be shortcut to a win; a mandatory loop is a draw). Checked
against the live corpus: **CR 720 is now "Omen Cards"** — an unrelated card-frame mechanic that
took the number after the loop rules were restructured. The actual content moved to **CR 732**
("Loops" — the shortcut-rule mechanics: 732.4 restates the mandatory-loop-is-a-draw rule,
732.5/732.6 cover when a player can be forced to end a loop) cross-referencing **CR 104.4b**
("If a game... enters a 'loop' of mandatory actions... the game is a draw. Loops that contain
an optional action don't result in a draw."). A second, closely-related citation in the same
module — **CR 104.4a** for "a purely mandatory loop is a draw" — was *also* wrong: 104.4a is
actually "if all players lose simultaneously, the game is a draw," a different rule entirely;
the correct citation was 104.4b all along. Both fixed; the classifier's actual behavior
(`_NONDET_MARKERS`, the chance/opponent-choice detection) was already correct and untouched.

**2. `deck_quality.py` and `CLAUDE.md` cited "rule 202.3b" for hybrid mana value; that number is
now the double-faced-card mana-value rule.** The real hybrid rule is **CR 202.3f**: "When
calculating the mana value of an object with a hybrid mana symbol in its mana cost, use the
largest component of each hybrid symbol." `deck_quality.py`'s actual `mana_value()`
implementation already did this correctly (`total += max(halves)`) — citation-only fix, no
behavior change.

**3. A real bug: the engine's OWN mana-cost parser never implemented CR 202.3f at all.**

`model/card.py::ManaCost` — the mana-cost model `sim/tier0.py` and every bracket/curve
computation in `src/mythgauntlet` actually uses — is a **separate, independent implementation**
from `deck_quality.py`'s. Its `mana_value` was a derived property, `generic + len(pips)`, and a
monocolored hybrid symbol like `{2/W}` was stored as a plain color pip (`pips.append({"W"})`) —
so it contributed exactly 1 to mana value, not the 2 that CR 202.3f actually requires. This
wasn't a citation problem; the class docstring already listed it as a known, deliberate
simplification ("Monocolor-hybrid treated as its color pip, never the generic option") with no
rule number attached at all. It just happened to also be the class this repo's own culture
calls a defect once measured: **`deck_quality.mana_value`, `server.py`'s single-card parser,
and `model/card.py::ManaCost` computed three different answers for the same real card.**

Fixed by giving `ManaCost.mana_value` its own CR-202.3-exact computation at parse time,
independent of `generic`/`pips` — which stay exactly as before, because those two fields feed a
**separate, deliberately-simplified PAYMENT model** (`_can_pay` in `sim/tier0.py`): a deck can
always tap 1 W for `{2/W}` instead of finding 2 generic, so treating it as a plain color pip for
*castability* is conservative-correct even though it undercounts the *card's actual value*.
Decoupling the two was the fix — `mana_value` no longer has to agree with a payment
simplification that was never trying to answer the same question.

Verified: `{2/W}` → 2, `{2/B}{2/B}{2/B}` → 6 (the CR's own worked example), `{1}{W/U}{W/U}` → 3
(also the CR's own example — a pure-color hybrid was already correct and is unchanged).

**4. Everything else checked resolves and reads correct.** `CR 903.4` (color identity), `CR
506.3`/`508.1` (attack declaration, backing the pod combat-defender lock), `CR 103.8a`/`103.8c`
(first-turn draw skip, quoted verbatim in `sim/game.py`) all still exist and still say what the
code claims. No drift found there.

## The tool: `scripts/rules_audit.py`

Grep-scans the engine source tree (`src/mythgauntlet`, `deck_quality.py`, `server.py` —
excluding `mentor/`, whose citations are numbers the model retrieved live this turn, not
hand-encoded claims) for every `CR ###`/`rule ###` citation, and checks each rule number against
the currently-fetched Comprehensive Rules corpus. A citation to a number that no longer exists
is flagged automatically — a certain sign of drift. A citation that *does* resolve is not proof
the code's claim about it is still right (that judgment isn't automatable), but printing the
citing line next to the rule's current text turns a fresh corpus search into a five-second
read, which is what made this pass tractable at all.

```
python scripts/rules_audit.py            # every citation, grouped by file, full text
python scripts/rules_audit.py --missing  # only the ones that no longer resolve
```

Run it after any `mythgauntlet fetch-rules --force` (a CR refresh can renumber things again by
the same mechanism that caused this), and periodically regardless — this is a corpus that
drifts on WotC's schedule, not this repo's.

## What this does and doesn't mean

The simulator was never meant to be a rules-*enforcement* engine (a judge, or Forge/XMage) —
it's a heuristic power-level estimator, and it doesn't need to correctly resolve every layered
replacement-effect interaction to do that job. The real risk this closes is narrower and more
concrete: a hand-coded rule assumption silently drifting from what the rule actually says, in a
way that skews a bracket verdict or a curve measurement — which is precisely the shape of bug
this repo has hit repeatedly (`_CHEAT_RE` matching the verb but not the object, the first-draw
skip almost shipping as universal instead of two-player-only, a trigger event matched by a
synonym the evidence gate didn't recognize). Every one of those was caught by a human or model
*happening* to check by hand. This pass, and the tool it leaves behind, is the first time that
checking process has had a live corpus to check against instead of memory.

## Still open

This pass covered every EXPLICIT citation already in the codebase — it did not attempt to find
UNCITED rule-sensitive logic (places where a rule is assumed but no comment says which one).
That's a larger, more judgment-driven audit (combat damage ordering, state-based action
sequencing, layers/timestamps for continuous effects, trigger stacking order) and is the
natural next phase of this work if it's worth the time — `search_rules`/`get_rule` are now
sitting right there to make it tractable the same way they made this pass tractable.
