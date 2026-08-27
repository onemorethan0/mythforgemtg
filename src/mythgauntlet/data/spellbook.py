"""Commander Spellbook combo lookup (docs/DATA_SOURCES.md).

Commander Spellbook is the community's canonical combo database. Its open
`find-my-combos` endpoint takes a decklist and returns the combos the deck contains
("included") plus near-misses one card away ("almost included") — exactly what the
Ceiling axis and the official bracket combo gates need.

Network happens only in `find_combos` (cached by decklist hash under data/spellbook/).
Parsing is pure and defensive for offline tests.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from mythgauntlet.config import USER_AGENT, data_dir
from mythgauntlet.model.card import normalize_name

if TYPE_CHECKING:  # type-only; determinism verdicts are injected, never imported at runtime
    from mythgauntlet.semantics.combo_rules import DeterminismVerdict

# A combo is treated as game-ending when it produces one of these terminal payoffs.
# Deliberately conservative: "infinite mana" alone is NOT a win (it needs an outlet), so
# we require an actually-lethal feature. Heuristic, documented (docs/SIMULATION.md).
_WINNING_FEATURE_RE = re.compile(
    r"win the game|wins the game|loses the game|each opponent loses|"
    r"infinite (?:combat )?damage|infinite (?:life ?loss|drain|mill|poison)|"
    r"infinite turns|near-infinite (?:damage|mill)|"
    r"infinite (?:creature |1/1 )?tokens",  # an infinite board wins the next combat
    re.IGNORECASE,
)

API_URL = "https://backend.commanderspellbook.com/find-my-combos"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}
# Re-ask Spellbook weekly, matching scryfall.MAX_AGE_DAYS. Their combo database grows
# continuously and this is the signal that lifts a deck from Bracket 2 to Bracket 3.
MAX_AGE_DAYS = 7


@dataclass(frozen=True)
class Combo:
    id: str
    cards: tuple[str, ...]  # card names the combo uses
    produces: tuple[str, ...]  # result features, e.g. 'Infinite colorless mana'
    bracket_tag: str | None  # Spellbook's own bracket categorization
    mana_needed: str
    popularity: int | None
    # Enrichment (previously discarded) — the qualifiers that separate a real wincon from a
    # durdle. Defaulted so older callers / fixtures that build a Combo positionally still work.
    mana_value: int = 0  # Spellbook's manaValueNeeded (total mana to go off)
    description: str = ""  # the step-by-step loop text
    notable_prerequisites: str = ""  # non-trivial game-state the combo needs
    easy_prerequisites: str = ""  # trivial setup (e.g. "a creature on the battlefield")

    @property
    def is_two_card(self) -> bool:
        return len(self.cards) == 2

    def missing_from(self, deck_names: set[str]) -> tuple[str, ...]:
        """Cards this combo needs that a deck (normalized names) doesn't have."""
        return tuple(c for c in self.cards if normalize_name(c) not in deck_names)


@dataclass
class ComboReport:
    identity: str
    included: list[Combo]
    almost_included: list[Combo]

    @property
    def two_card_count(self) -> int:
        return sum(1 for c in self.included if c.is_two_card)


def is_winning_combo(combo: Combo) -> bool:
    """True if any produced feature ends the game (see _WINNING_FEATURE_RE)."""
    return any(_WINNING_FEATURE_RE.search(f) for f in combo.produces)


def winning_combos(report: ComboReport) -> list[frozenset[str]]:
    """Included game-ending combos as sets of normalized piece names.

    The T2 engine (sim/tier2.py) treats a deck as able to win once all pieces of one of
    these sets are simultaneously on its battlefield and no longer summoning-sick.
    """
    out: list[frozenset[str]] = []
    for combo in report.included:
        if is_winning_combo(combo):
            out.append(frozenset(normalize_name(c) for c in combo.cards))
    return out


# --- Combo grading (Layer 1: metadata-only reliability; docs/SIMULATION.md) --------------
# The bracket combo-gate used to treat EVERY game-ending combo identically ("any -> min
# Bracket 3"), so a 3-piece, commander-dependent, {W}{W} infinite-TOKEN loop (Spellbook's
# own bracketTag "E") scored the same as a 2-card, zero-mana "each opponent loses the game".
# These grades expose the qualifiers Spellbook already ships so the gate and the explanations
# can tell a real wincon from a durdle. Deliberately METADATA-ONLY: rules/errata determinism
# (random / coin-flip / mandatory-loop draws, CR 732/104.4b -- verified 2026-08-24; a prior
# version of this comment cited CR 720, since reassigned by WotC to Omen Cards) is a separate
# Layer 2 and is NOT judged here. is_winning_combo() is left untouched -- this only refines
# the winners it already finds.

# Features that WIN the turn the loop assembles, with no extra combat step or outlet needed.
_TERMINAL_FEATURE_RE = re.compile(
    r"win the game|wins the game|loses the game|each opponent loses|"
    r"infinite (?:combat )?damage|infinite (?:life ?loss|drain|mill|poison)|"
    r"infinite turns",
    re.IGNORECASE,
)


def is_terminal_combo(combo: Combo) -> bool:
    """True if this (winning) combo ENDS the game the turn it assembles.

    The complement is an 'advantage' combo (infinite mana / tokens / ETB / storm): still a
    wincon per is_winning_combo(), but it needs an outlet or the next combat to convert, so
    it is slower and more fragile. Only meaningful for combos already game-ending.
    """
    return any(_TERMINAL_FEATURE_RE.search(f) for f in combo.produces)


@dataclass(frozen=True)
class ComboGrade:
    """A single game-ending combo, graded by the qualifiers that gate real power."""

    combo: Combo
    terminal: bool  # wins the turn it assembles (vs needs an outlet / next combat)
    pieces: int
    mana_value: int
    needs_commander: bool  # a piece is one of the deck's commanders (harder to replace)
    spellbook_tag: str | None
    reliability: str  # 'fast-win' | 'strong' | 'slow'
    determinism: DeterminismVerdict | None = None  # Layer 2 rules verdict (None = not judged)

    @property
    def note(self) -> str:
        """One-line ASCII explanation of WHY it graded this way (for the user-facing panel)."""
        bits = [f"{self.pieces} pieces"]
        if self.mana_value:
            bits.append(f"{self.mana_value} mana")
        bits.append("terminal" if self.terminal else "needs an outlet")
        if self.needs_commander:
            bits.append("commander-dependent")
        if self.spellbook_tag:
            bits.append(f"Spellbook tag {self.spellbook_tag}")
        if self.determinism is not None and not self.determinism.deterministic:
            bits.append(f"NON-DETERMINISTIC ({', '.join(self.determinism.markers)})")
        return f"[{self.reliability}] " + ", ".join(bits)


def classify_combo(
    combo: Combo,
    commander_names: frozenset[str] = frozenset(),
    determinism: DeterminismVerdict | None = None,
) -> ComboGrade:
    """Grade one game-ending combo. Shape comes from Spellbook metadata (no sim, no LLM); the
    optional `determinism` verdict (Layer 2, injected) caps an unreliable win's reliability.
    """
    terminal = is_terminal_combo(combo)
    pieces = len(combo.cards)
    mv = int(combo.mana_value or 0)
    cmd_norm = {normalize_name(n) for n in commander_names}
    needs_cmd = any(normalize_name(c) in cmd_norm for c in combo.cards)

    if terminal and pieces <= 2 and mv <= 2 and not needs_cmd:
        reliability = "fast-win"  # the cEDH-shaped signal
    elif terminal and pieces <= 3:
        reliability = "strong"
    else:
        reliability = "slow"  # advantage-only, or many pieces / high mana / commander-gated
    # A win that hinges on chance or an opponent's choice is never a fast/strong wincon,
    # however clean its shape (CR 104.4b). Cap it, but keep the floor -- it is still a wincon.
    if determinism is not None and not determinism.deterministic:
        reliability = "slow"
    return ComboGrade(
        combo=combo, terminal=terminal, pieces=pieces, mana_value=mv,
        needs_commander=needs_cmd, spellbook_tag=combo.bracket_tag, reliability=reliability,
        determinism=determinism,
    )


@dataclass(frozen=True)
class ComboAssessment:
    """Deck-level view of the graded game-ending combos — the combo-gate's rich input."""

    grades: tuple[ComboGrade, ...]

    @property
    def total(self) -> int:
        return len(self.grades)

    @property
    def terminal_count(self) -> int:
        return sum(1 for g in self.grades if g.terminal)

    @property
    def advantage_count(self) -> int:
        return sum(1 for g in self.grades if not g.terminal)

    @property
    def fast_terminal_two_card(self) -> bool:
        """>=1 fast-win, 2-card, terminal combo — the clean cEDH escalation signal."""
        return any(g.reliability == "fast-win" and g.pieces <= 2 for g in self.grades)

    @property
    def terminal_two_card(self) -> bool:
        """>=1 2-card, terminal combo, at ANY reliability grade — not just fast-win.

        Measured against 252 real B3/B4/B5-labelled decks with a live Spellbook lookup
        (`scripts/bracket_b5_gate.py`, `docs/PLAN_CLOCK.md` Sec 1.4): requiring `fast-win`
        specifically found the qualifying signal on only 38 decks (9 of them real B5).
        Dropping the reliability requirement (keeping terminal + <=2 pieces) more than
        doubles the pool to 78 decks and TRIPLES the real-B5 share within it (9 -> 28) —
        most real cEDH decks' actual win conditions are genuine 2-card terminal combos that
        `classify_combo` simply doesn't grade as "fast" (a slower mana cost, a notable
        prerequisite, etc. do not make a combo any less game-ending once assembled). This
        is a strict superset of `fast_terminal_two_card`, so it only ever WIDENS which
        decks are even eligible for a B5 gate to consider — it does not by itself promote
        anything (the gate's ceiling/speed checks still have to clear separately).
        """
        return any(g.terminal and g.pieces <= 2 for g in self.grades)

    @property
    def nondeterministic_count(self) -> int:
        """Winning combos whose result hinges on chance / an opponent's choice (Layer 2)."""
        return sum(
            1 for g in self.grades
            if g.determinism is not None and not g.determinism.deterministic
        )

    def gate_reason(self) -> str:
        """The ASCII reason string the bracket gate shows in place of the flat 'any -> B3'."""
        parts = []
        fast = sum(1 for g in self.grades if g.reliability == "fast-win")
        strong = sum(1 for g in self.grades if g.reliability == "strong")
        slow = sum(1 for g in self.grades if g.reliability == "slow")
        if fast:
            parts.append(f"{fast} fast 2-card terminal")
        if strong:
            parts.append(f"{strong} strong")
        if slow:
            parts.append(f"{slow} slow/needs-outlet")
        breakdown = ", ".join(parts) if parts else "unclassified"
        nd = self.nondeterministic_count
        nd_note = f", {nd} non-deterministic" if nd else ""
        return (
            f"{self.total} in-deck game-ending combo(s) ({breakdown}{nd_note}) "
            "-> min Bracket 3"
        )


def assess_combos(
    report: ComboReport,
    commander_names: frozenset[str] = frozenset(),
    *,
    determinism_fn: Callable[[Combo], DeterminismVerdict | None] | None = None,
) -> ComboAssessment:
    """Grade every game-ending combo the deck actually contains (included + winning).

    `determinism_fn` (Layer 2, injected by the ratings/CLI layer so the data layer stays free
    of the semantics import) maps a combo to its DeterminismVerdict from the pieces' Oracle
    text; when omitted, grading is metadata-only (Layer 1) and determinism is left unjudged.
    """
    grades = tuple(
        classify_combo(
            c, commander_names,
            determinism=determinism_fn(c) if determinism_fn is not None else None,
        )
        for c in report.included
        if is_winning_combo(c)
    )
    return ComboAssessment(grades=grades)


def _variant_to_combo(variant: dict) -> Combo | None:
    uses = variant.get("uses") or []
    cards = tuple(
        (u.get("card") or {}).get("name", "") for u in uses if (u.get("card") or {}).get("name")
    )
    if not cards:
        return None
    produces = tuple(
        (p.get("feature") or {}).get("name", "")
        for p in variant.get("produces") or []
        if (p.get("feature") or {}).get("name")
    )
    try:
        mana_value = int(variant.get("manaValueNeeded") or 0)
    except (TypeError, ValueError):
        mana_value = 0
    return Combo(
        id=str(variant.get("id", "")),
        cards=cards,
        produces=produces,
        bracket_tag=variant.get("bracketTag"),
        mana_needed=variant.get("manaNeeded") or "",
        popularity=variant.get("popularity"),
        mana_value=mana_value,
        description=variant.get("description") or "",
        notable_prerequisites=variant.get("notablePrerequisites") or "",
        easy_prerequisites=variant.get("easyPrerequisites") or "",
    )


def parse_response(payload: dict) -> ComboReport:
    results = payload.get("results") or {}

    def combos(key: str) -> list[Combo]:
        out = []
        for variant in results.get(key) or []:
            combo = _variant_to_combo(variant)
            if combo is not None:
                out.append(combo)
        return out

    return ComboReport(
        identity=results.get("identity", ""),
        included=combos("included"),
        almost_included=combos("almostIncluded"),
    )


def _request_body(cards: list[tuple[str, int]], commanders: list[str]) -> dict:
    return {
        "main": [{"card": name, "quantity": count} for name, count in cards],
        "commanders": [{"card": name, "quantity": 1} for name in commanders],
    }


def find_combos(
    cards: list[tuple[str, int]],
    commanders: list[str],
    force: bool = False,
    max_age_days: float | None = MAX_AGE_DAYS,
) -> ComboReport:
    """Query find-my-combos for a deck. Cached by decklist hash, refetched when stale.

    The age check matters more here than for the card stores. The cache key is the
    DECKLIST, so an edited deck gets a fresh key automatically — but a deck the user keeps
    unchanged never re-asked. Commander Spellbook's database grows continuously, and this
    is the one signal that lifts a casual deck from Bracket 2 to Bracket 3
    (`estimate_bracket`'s combo gate). So a deck saved today kept its "no combos" verdict
    for good, even after Spellbook learned that two cards in it go infinite.

    Pass `max_age_days=None` to accept any cached copy (offline / test use).
    """
    body = _request_body(cards, commanders)
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False)
    cache = _cache_path(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24])
    if cache.exists() and not force and _fresh(cache, max_age_days):
        try:
            with open(cache, encoding="utf-8") as fh:
                return parse_response(json.load(fh))
        except (json.JSONDecodeError, OSError):
            pass  # truncated/corrupt cache -> refetch below
    resp = requests.post(API_URL, headers=HEADERS, json=body, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    tmp = cache.with_suffix(".json.part")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    tmp.replace(cache)  # atomic
    return parse_response(payload)


def _cache_path(key: str) -> Path:
    cache = data_dir() / "spellbook"
    cache.mkdir(parents=True, exist_ok=True)
    return cache / f"{key}.json"


def _fresh(path: Path, max_age_days: float | None) -> bool:
    """Whether a cache file is young enough to serve. None = accept any age."""
    if max_age_days is None:
        return True
    try:
        return (time.time() - path.stat().st_mtime) / 86400 <= max_age_days
    except OSError:
        return False
