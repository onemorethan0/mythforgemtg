"""Audit a corpus deck's bracket LABEL against the official hard gates.

The labelled corpus is the reference every bracket measurement is scored against
(`scripts/bracket_accuracy.py`, `ratings/reference.py`, the strength fit). Its labels are the
deck builder's own claim, so a label that the official bracket rules forbid is noise the whole
pipeline then learns from: a "Bracket 2" deck holding four Game Changers is not a Bracket 2
deck by the rules' own text, whatever its builder called it.

The audit only rejects what the rules PROVABLY forbid at the claimed bracket, from the two
gates that can be read without judgement:

  * Game Changers -- an official list (Scryfall's `game_changer` flag). Brackets 1-2 allow
    none, Bracket 3 at most three.
  * Two-card infinite combos -- Brackets 1-2 allow none. A combo counts when Commander
    Spellbook lists it with both pieces in the deck and a truly INFINITE result: its
    "Near-infinite" is a large finite result (Blasphemous Act + Repercussion), and a two-card
    win that loops nothing (Approach of the Second Sun + Windfall) is not an infinite combo.
    The rules' word "intentional" is something no list can see; two pieces that go infinite
    together in a deck labelled 1 or 2 are taken at their word.

NOT audited: mass land denial and chained extra turns. The rules define them by intent
("regularly", "chaining"), and the engine's own reader (`ratings.bracket._scan`) also fires on
Pox, Tectonic Hellion, Magosi, the Waterveil and planeswalker ultimates (Ajani Vengeant -7,
Ral Zarek -7) -- an under-count is the honest choice here. Brackets 4 and 5 have no
restriction to violate, so a 4 or 5 label always passes: dropping "Bracket 4 decks without
Game Changers" would teach the strength model that Bracket 4 means Game Changers.

A failing deck keeps its claim: `mark` rewrites `# bracket: N` to `# bracket_claimed: N` and
adds a `# label_audit:` line, so every `# bracket:` reader drops it from the labelled set and
the deck stays in the corpus. `unmark` restores it, so a re-audit under changed rules is clean.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# `[ \t]*`, not `\s*`: a trailing `\s*$` also eats the newline, and `mark` would join the
# header to the blank line under it
LABEL_RE = re.compile(r"^#[ \t]*bracket:[ \t]*([1-5])[ \t]*$", re.MULTILINE)
CLAIMED_RE = re.compile(r"^#[ \t]*bracket_claimed:[ \t]*([1-5])[ \t]*\n#[ \t]*label_audit:[^\n]*$",
                        re.MULTILINE)

MAX_GAME_CHANGERS = {1: 0, 2: 0, 3: 3}   # brackets 4-5: no limit
# Spellbook writes "Near-infinite" for a large FINITE result; only "Infinite" is a loop.
_INFINITE_RE = re.compile(r"(?<!near-)\binfinite\b", re.IGNORECASE)


@dataclass
class LabelAudit:
    label: int
    ok: bool
    reasons: list[str] = field(default_factory=list)


def audit(label: int, game_changers: set[str] | frozenset[str],
          two_card_infinite: list[tuple[str, ...]]) -> LabelAudit:
    """Whether `label` is allowed by the Game Changer and two-card-infinite gates."""
    reasons: list[str] = []
    limit = MAX_GAME_CHANGERS.get(label)
    if limit is not None and len(game_changers) > limit:
        names = ", ".join(sorted(game_changers)[:5]) + ("..." if len(game_changers) > 5 else "")
        reasons.append(f"{len(game_changers)} Game Changers ({names}); Bracket {label} allows "
                       f"{limit}")
    if label <= 2 and two_card_infinite:
        reasons.append("two-card infinite combo " + " + ".join(two_card_infinite[0])
                       + f"; Bracket {label} allows none")
    return LabelAudit(label, not reasons, reasons)


def two_card_infinite(combo_report) -> list[tuple[str, ...]]:
    """The two-card combos in a `spellbook.ComboReport` whose result is truly infinite."""
    if combo_report is None:
        return []
    return [c.cards for c in combo_report.included
            if c.is_two_card and any(_INFINITE_RE.search(f) for f in c.produces)]


def audit_resolved(resolved, label: int, combo_report) -> LabelAudit:
    """`audit` for a resolved deck. `combo_report` None (a failed lookup) skips the combo gate:
    never assumed clean OR dirty."""
    all_cards = list(resolved.cards) + [(c, 1) for c in resolved.commanders]
    gcs = {c.name for c, _n in all_cards if c.game_changer}
    return audit(label, gcs, two_card_infinite(combo_report))


def unmark(text: str) -> str:
    """A deck file's text with an earlier audit undone (its claimed label restored)."""
    return CLAIMED_RE.sub(lambda m: f"# bracket: {m.group(1)}", text, count=1)


def mark(text: str, result: LabelAudit) -> str:
    """A failing deck's text with its label demoted; unchanged if it passed or has no label."""
    if result.ok or not LABEL_RE.search(text):
        return text
    line = "# label_audit: fails the official Bracket {} gates: {}".format(
        result.label, "; ".join(result.reasons))
    return LABEL_RE.sub(f"# bracket_claimed: {result.label}\n{line}", text, count=1)
