"""Combos on the clock (B33, docs/SPEC_deck_scouting_report.md).

For each graded game-ending combo the deck holds: in what share of games is it ASSEMBLED by
turn T, with every piece where Spellbook says it must be and the mana to start it. Then the
combined clock: per game, the earlier of the goldfish damage kill and the combo kill.

How a game is read. Every figure comes from the goldfish runs the rest of the analysis uses
(tier0 records the turn each card was first seen and the mana available each turn), replayed
as a pilot who PRIORITISES the combo: each turn it fires the combo if it can, else casts a
tutor for a missing piece, else deploys a piece that must be on the battlefield, cheapest
first, within that turn's mana. The replay is per combo and does not take mana from the
goldfish's own plays, so it is the combo line on its own, not a second strategy layered on top.

What a piece needs, from Spellbook's own per-piece data (`Combo.zones`):
- battlefield (B): cast beforehand, its mana value paid that turn; "without summoning
  sickness" on a creature means it landed on an EARLIER turn (CR 302.6). A land piece costs
  no mana.
- hand (H): in hand when the combo starts; its cost is already in Spellbook's
  `manaValueNeeded`, which is the mana to execute (0 for Krenko + Skirk Prospector + Goblin
  Warchief, 3 for Thassa's Oracle + Demonic Consultation).
- command zone (C) / the commander: available from turn 1, no draw needed (CR 903.6); a
  commander that must be on the battlefield is cast from the command zone like any piece.
Not timed, and said so: graveyard / exile / library-only pieces, any other required state
(counters, attachments), multiple copies, and generic template cards ("Persist Creature"). A
non-deterministic combo is timed but never counted as a kill (CR 104.4b); an advantage combo
(infinite mana with no outlet) is timed but is not a kill on its own.

Tutors (semantics/tutor_reach.py) are extra outs, gated on the OBJECT they can find and paying
their own cost. Colour of the mana is not checked (tier0 tracks a count of available mana);
counted, mana-for-mana, the clock is the earliest a combo-first pilot could go, unopposed.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from mythgauntlet.data.spellbook import ComboGrade, normalize_name
from mythgauntlet.model.card import Card
from mythgauntlet.semantics.tutor_reach import TutorReach, tutor_reach

REPORT_TURNS = range(3, 11)
_HASTY_TOKENS_RE = re.compile(r"infinite (?:creature |1/1 )?tokens with haste", re.IGNORECASE)
_TOKENS_RE = re.compile(r"infinite (?:creature |1/1 )?tokens", re.IGNORECASE)


@dataclass(frozen=True)
class _Piece:
    name: str
    card: Card
    mode: str            # "B" battlefield, "H" hand, "C" command zone (always available)
    commander: bool
    untapped: bool       # must have been on the battlefield since an earlier turn


@dataclass(frozen=True)
class TimedCombo:
    cards: tuple[str, ...]
    produces: tuple[str, ...]
    kind: str                       # "kill" | "kill_next_turn" | "advantage"
    deterministic: bool | None      # None = not judged
    timed: bool
    not_timed: str | None           # why not, when not timed
    mana_value: int
    tutors: tuple[str, ...] = ()    # tutors counted as outs for at least one piece
    by_turn: dict[int, float] = field(default_factory=dict)
    turn_25: int | None = None      # first turn the share of games assembled reaches 25% / 50%
    turn_50: int | None = None
    text: str = ""
    # Spellbook prerequisites the clock cannot check ("You have a way to give Brash Taunter
    # lifelink"). Timed anyway, but such a combo is not counted as a kill.
    assumes: tuple[str, ...] = ()

    @property
    def counts_as_kill(self) -> bool:
        return (self.timed and self.kind != "advantage" and self.deterministic is not False
                and not self.assumes)


@dataclass(frozen=True)
class ComboClock:
    games: int
    horizon: int
    combos: list[TimedCombo]
    # Combined clock: per game, the earlier of the damage kill and a timed kill combo.
    killing_games: int
    p25: float | None
    median: float | None
    p75: float | None
    by_turn: dict[int, float]
    combo_first_games: int          # games the combo kill came strictly before the damage kill
    combo_first_median: float | None
    lead_combo: tuple[str, ...]     # the combo that most often comes first
    text: str


_WORD_N = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
           "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_SICK_RE = re.compile(r"^(?P<who>.+?) (?:does not|doesn't) have summoning sickness\.?$")
_CONTROL_N_RE = re.compile(
    r"^you control (?:at least (?P<n>\w+)|a number of) (?P<type>[a-z]+?)s?"
    r"(?: that is equal to or greater than (?P<n2>\w+) plus [^.]*commander tax)?\.?$")
_LIFE_RE = re.compile(r"^your life total is at least (?P<n>\d+)\.?$")
_ACCEPTED = (
    re.compile(r"^you have enough mana (?:available )?to cast "),   # the mana check covers it
    re.compile(r"^you have at least (?:one|two|three) opponents?\.?$"),  # a Commander pod
)


@dataclass(frozen=True)
class _Prereqs:
    untapped: frozenset[str]            # normalized piece names that must be untapped-ready
    board: tuple[tuple[int, str], ...]  # (count, card type) you must control
    assumed: tuple[str, ...]            # prerequisites the clock cannot check


def _prereqs(combo, piece_names: list[str], start_life: int = 40) -> _Prereqs:
    """Read Spellbook's prerequisite lines into what the clock can check. Anything it cannot
    is kept, verbatim, as an assumption: the combo is still timed but is not counted as a kill
    in the combined clock."""
    untapped: set[str] = set()
    board: list[tuple[int, str]] = []
    assumed: list[str] = []
    text = "\n".join([combo.easy_prerequisites or "", combo.notable_prerequisites or ""])
    by_norm = {normalize_name(n): n for n in piece_names}
    for raw in re.split(r"\n+", text):
        line = raw.strip().strip("/").strip()
        if not line:
            continue
        low = line.casefold()
        m = _SICK_RE.match(low)
        if m:
            who = normalize_name(m.group("who"))
            hit = next((n for n in by_norm if n == who or n.split(",")[0] == who), None)
            if hit is not None:
                untapped.add(hit)
                continue
        m = _CONTROL_N_RE.match(low)
        if m:
            n = _WORD_N.get(m.group("n2") or m.group("n") or "", None)
            if n is None and (m.group("n2") or m.group("n") or "").isdigit():
                n = int(m.group("n2") or m.group("n"))
            if n is not None:
                board.append((n, m.group("type")))
                continue
        m = _LIFE_RE.match(low)
        if m and int(m.group("n")) <= start_life:
            continue
        if any(rx.match(low) for rx in _ACCEPTED):
            continue
        assumed.append(line)
    return _Prereqs(frozenset(untapped), tuple(board), tuple(assumed))


def _kind(produces: tuple[str, ...], terminal: bool) -> str:
    if terminal or any(_HASTY_TOKENS_RE.search(p) for p in produces):
        return "kill"
    if any(_TOKENS_RE.search(p) for p in produces):
        return "kill_next_turn"     # an infinite board without haste swings the next turn
    return "advantage"


def _pieces(grade: ComboGrade, by_name: dict[str, Card], commanders: set[str],
            untapped_names: frozenset[str] = frozenset()
            ) -> tuple[list[_Piece] | None, str | None]:
    c = grade.combo
    if not c.zones or len(c.zones) != len(c.cards):
        return None, "no per-piece zone data"
    if c.templates:
        return None, "also needs " + ", ".join(c.templates) + " (a generic card, not timed)"
    out = []
    for i, name in enumerate(c.cards):
        card = by_name.get(normalize_name(name))
        if card is None:
            return None, f"{name} is not in the deck"
        if c.quantities and c.quantities[i] > 1:
            return None, f"needs {c.quantities[i]} copies of {name}"
        if c.other_state and c.other_state[i]:
            return None, f"{name} needs a board state the clock does not model"
        zones = set(c.zones[i])
        is_cmd = normalize_name(name) in commanders
        if is_cmd:
            mode = "C" if zones & {"C", "H"} else ("B" if "B" in zones else None)
        else:
            mode = "H" if "H" in zones else ("B" if "B" in zones else None)
        if mode is None:
            where = {"G": "graveyard", "E": "exile", "L": "library"}
            return None, (f"{name} must start in the "
                          + "/".join(where.get(z, z) for z in sorted(zones)))
        untapped = (bool(c.needs_untapped and c.needs_untapped[i])
                    or normalize_name(name) in untapped_names) and card.is_creature
        out.append(_Piece(name=card.name, card=card, mode=mode, commander=is_cmd,
                          untapped=untapped))
    return out, None


def _controls(run, turn: int, ctype: str, pieces: list[_Piece], deployed: list,
              others: list[Card], commander: Card | None) -> int:
    """Permanents of `ctype` you control on `turn`: the pieces this replay deployed, plus the
    deck's other cards the goldfish has cast by then (and its commander). Tokens are not
    tracked, so Krenko's own goblins never count: an under-count, never a guess."""
    from mythgauntlet.semantics.tutor_reach import _type_tokens

    n = sum(1 for i, p in enumerate(pieces)
            if deployed[i] is not None and ctype in _type_tokens(p.card))
    played = run.played_turn
    for c in others:
        t = played.get(c.name)
        if t is not None and t <= turn and ctype in _type_tokens(c):
            n += 1
    if commander is not None and run.commander_turn is not None \
            and run.commander_turn <= turn and ctype in _type_tokens(commander):
        n += 1
    return n


def assemble_turn(run, pieces: list[_Piece], tutors: list[TutorReach], mana_value: int,
                  horizon: int, board: tuple[tuple[int, str], ...] = (),
                  others: list[Card] = (), commander: Card | None = None) -> int | None:
    """The first turn this game can start the combo, or None within the horizon. `board` is
    the prerequisite "you control at least N <type>s"; `others` are the deck's non-piece cards
    and `commander` a commander that is not a piece (both only count toward `board`)."""
    seen = run.seen_turn
    mana = run.mana_available_by_turn
    creatures = run.board_creatures_by_turn
    n = len(pieces)
    in_hand = [False] * n
    deployed: list[int | None] = [None] * n
    arrive: dict[int, list[int]] = {}
    pending = [False] * n      # tutored to the top: arrives with next turn's draw
    uses = {t.name: 0 for t in tutors}
    tutor_on_board: dict[str, int] = {}
    for turn in range(1, horizon + 1):
        budget = mana[turn - 1] if turn - 1 < len(mana) else (mana[-1] if mana else 0)
        n_creatures = creatures[turn - 1] if turn - 1 < len(creatures) else 0
        for i, p in enumerate(pieces):
            if p.commander or seen.get(p.name, math.inf) <= turn:
                in_hand[i] = True
        for i in arrive.pop(turn, ()):
            in_hand[i] = True
            pending[i] = False
        while True:
            ready = True
            cost = mana_value
            for i, p in enumerate(pieces):
                if p.mode == "B" and deployed[i] is not None:
                    if p.untapped and deployed[i] >= turn:
                        ready = False          # summoning sick this turn (CR 302.6)
                        break
                    continue
                if not in_hand[i]:
                    ready = False
                    break
                if p.mode == "B":
                    if p.untapped:
                        ready = False
                        break
                    cost += 0 if p.card.is_land else p.card.mana_value
            if ready and cost <= budget and all(
                    _controls(run, turn, ctype, pieces, deployed, others, commander) >= need
                    for need, ctype in board):
                return turn
            best = None   # (cost, order, apply)
            missing = [i for i, p in enumerate(pieces)
                       if not in_hand[i] and deployed[i] is None and not pending[i]]
            for t in tutors:
                if seen.get(t.name, math.inf) > turn:
                    continue
                if not t.repeatable and uses[t.name] >= 1:
                    continue
                if t.needs_creature and n_creatures <= 0:
                    continue
                reach = [i for i in missing if t.can_fetch(pieces[i].card)
                         and not (t.destination == "battlefield" and pieces[i].mode != "B")]
                if not reach:
                    continue
                if t.timing == "activated" and t.name not in tutor_on_board:
                    c = t.cast_cost
                    if c <= budget and (best is None or (c, 1) < best[:2]):
                        best = (c, 1, ("deploy_tutor", t, None))
                    continue
                if t.timing == "activated" and tutor_on_board[t.name] >= turn:
                    continue      # activated abilities from the turn after it lands
                if t.timing == "activated" and t.repeatable and uses[t.name] >= turn:
                    continue      # one activation per turn, conservatively
                take = reach[: int(min(t.per_use, len(reach)))]
                base = t.use_cost if t.timing == "activated" else t.cast_cost
                c = base + (max(pieces[i].card.mana_value for i in take) if t.x_cost else 0)
                if c <= budget and (best is None or (c, 0) < best[:2]):
                    best = (c, 0, ("tutor", t, take))
            for i, p in enumerate(pieces):
                if p.mode == "B" and in_hand[i] and deployed[i] is None:
                    c = 0 if p.card.is_land else p.card.mana_value
                    if c <= budget and (best is None or (c, 2) < best[:2]):
                        best = (c, 2, ("deploy", None, i))
            if best is None:
                break
            c, _o, (what, t, arg) = best
            budget -= c
            if what == "deploy":
                deployed[arg] = turn
            elif what == "deploy_tutor":
                tutor_on_board[t.name] = turn
            else:
                # A repeatable activated tutor records the turn of its last use (one per
                # turn); anything else counts its uses.
                uses[t.name] = (turn if (t.timing == "activated" and t.repeatable)
                                else uses[t.name] + 1)
                for i in arg:
                    if t.destination == "hand":
                        in_hand[i] = True
                    elif t.destination == "top":
                        arrive.setdefault(turn + 1, []).append(i)   # drawn next turn
                        pending[i] = True
                    else:                                           # onto the battlefield
                        in_hand[i] = True
                        deployed[i] = turn
    return None


def _first_reaching(by_turn: dict[int, float], share: float) -> int | None:
    for t in sorted(by_turn):
        if by_turn[t] >= share:
            return t
    return None


def _quantile(xs, q):
    from mythgauntlet.ratings.kill_speed import quantile
    return quantile(xs, q)


def compute(runs, grades, deck_cards: list[Card], commanders: list[Card], horizon: int
            ) -> ComboClock:
    by_name: dict[str, Card] = {}
    for c in list(deck_cards) + list(commanders):
        by_name[normalize_name(c.name)] = c
        by_name.setdefault(normalize_name(c.front_name), c)
    cmd_names = {normalize_name(c.name) for c in commanders} | {
        normalize_name(c.front_name) for c in commanders}
    all_tutors = [r for r in (tutor_reach(c) for c in deck_cards) if r is not None]
    n = len(runs)
    timed: list[TimedCombo] = []
    kill_turns_by_combo: list[tuple[TimedCombo, list[int | None]]] = []
    for g in grades:
        c = g.combo
        det = None if g.determinism is None else g.determinism.deterministic
        kind = _kind(c.produces, g.terminal)
        pre = _prereqs(c, list(c.cards))
        pieces, why = _pieces(g, by_name, cmd_names, pre.untapped)
        if pieces is None:
            timed.append(TimedCombo(cards=c.cards, produces=c.produces, kind=kind,
                                    deterministic=det, timed=False, not_timed=why,
                                    mana_value=c.mana_value,
                                    text=f"{' + '.join(c.cards)}: not timed ({why})."))
            continue
        names = {p.name for p in pieces}
        tutors = [t for t in all_tutors if t.name not in names
                  and any(t.can_fetch(p.card) for p in pieces if not p.commander)]
        others = [d for d in deck_cards if d.name not in names]
        cmd_other = next((cm for cm in commanders if cm.name not in names), None)
        turns = [assemble_turn(r, pieces, tutors, c.mana_value, horizon, pre.board, others,
                               cmd_other) for r in runs]
        by_turn = {t: round(sum(1 for x in turns if x is not None and x <= t) / n, 3)
                   for t in REPORT_TURNS if t <= horizon} if n else {}
        full = {t: sum(1 for x in turns if x is not None and x <= t) / n
                for t in range(1, horizon + 1)} if n else {}
        tc = TimedCombo(cards=c.cards, produces=c.produces, kind=kind, deterministic=det,
                        timed=True, not_timed=None, mana_value=c.mana_value,
                        tutors=tuple(sorted(t.name for t in tutors)), by_turn=by_turn,
                        turn_25=_first_reaching(full, 0.25), turn_50=_first_reaching(full, 0.5),
                        assumes=pre.assumed)
        tc = TimedCombo(**{**tc.__dict__, "text": _describe_combo(tc, n)})
        timed.append(tc)
        if tc.counts_as_kill:
            delay = 1 if kind == "kill_next_turn" else 0
            kill_turns_by_combo.append(
                (tc, [None if x is None or x + delay > horizon else x + delay for x in turns]))
    return _combine(runs, timed, kill_turns_by_combo, horizon)


_PLAIN_LEADS = frozenset({"you", "your", "an", "a", "the", "no", "there", "at", "each", "all"})


def _lower_lead(sentence: str) -> str:
    """Lower-case a prerequisite's first word mid-sentence, unless it is a card name."""
    first = sentence.split(" ", 1)[0]
    return sentence[:1].lower() + sentence[1:] if first.casefold() in _PLAIN_LEADS else sentence


def _describe_combo(tc: TimedCombo, games: int) -> str:
    name = " + ".join(tc.cards)
    caveat = ""
    if tc.assumes:
        caveat = (" Not counted as a kill: it also needs " + "; ".join(
            _lower_lead(a).rstrip(".") for a in tc.assumes) + ".")
    elif tc.deterministic is False:
        caveat = " Not a guaranteed win (it hinges on chance or an opponent's choice)."
    elif tc.kind == "advantage":
        caveat = " Not a kill on its own: it needs an outlet."
    elif tc.kind == "kill_next_turn":
        caveat = " Its infinite board has no haste, so it kills the turn after."
    if tc.turn_25 is None:
        best = max(tc.by_turn.values(), default=0.0)
        return (f"{name}: assembled in under 25% of {games} games by any turn "
                f"(best {best:.0%}).{caveat}")
    out = f"{name}: assembled by T{tc.turn_25} in 25% of games"
    out += f", by T{tc.turn_50} in half" if tc.turn_50 is not None else ", never in half"
    if tc.tutors:
        out += f" (counting {len(tc.tutors)} tutor{'s' if len(tc.tutors) > 1 else ''})"
    return out + "." + caveat


def _combine(runs, timed, kill_turns_by_combo, horizon) -> ComboClock:
    n = len(runs)
    combined: list[int] = []
    first_turns: list[int] = []
    lead_count: dict[tuple, int] = {}
    for gi, r in enumerate(runs):
        best_combo = None
        best_turn = None
        for tc, turns in kill_turns_by_combo:
            t = turns[gi]
            if t is not None and (best_turn is None or t < best_turn):
                best_turn, best_combo = t, tc
        dmg = r.kill_turn
        if best_turn is not None and (dmg is None or best_turn < dmg):
            combined.append(best_turn)
            first_turns.append(best_turn)
            lead_count[best_combo.cards] = lead_count.get(best_combo.cards, 0) + 1
        elif dmg is not None:
            combined.append(dmg)
    lead = max(lead_count, key=lambda k: (lead_count[k], k)) if lead_count else ()
    by_turn = {t: round(sum(1 for x in combined if x <= t) / n, 3)
               for t in REPORT_TURNS if t <= horizon} if n else {}
    clock = dict(
        games=n, horizon=horizon, combos=timed, killing_games=len(combined),
        p25=_quantile(combined, 0.25), median=_quantile(combined, 0.5),
        p75=_quantile(combined, 0.75), by_turn=by_turn,
        combo_first_games=len(first_turns), combo_first_median=_quantile(first_turns, 0.5),
        lead_combo=lead,
    )
    damage = [r.kill_turn for r in runs if r.kill_turn is not None]
    return ComboClock(**clock, text=_describe_clock(clock, damage, timed))


def _num(x: float) -> str:
    return f"{x:.0f}" if float(x).is_integer() else f"{x:.1f}"


def _describe_clock(c: dict, damage: list[int], timed: list[TimedCombo]) -> str:
    n = c["games"]
    if not any(t.timed for t in timed):
        return "No combo could be timed." if timed else "No game-ending combo in the deck."
    dmg_med = _quantile(damage, 0.5)
    head = (f"Unopposed, it kills by damage around T{_num(dmg_med)}" if dmg_med is not None
            else "Unopposed, it has no damage kill in the horizon")
    if not c["combo_first_games"]:
        return head + "; no timed kill combo comes first in any game."
    share = c["combo_first_games"] / n
    return (f"{head}; a combo kills first in {share:.0%} of games (median "
            f"T{_num(c['combo_first_median'])}), most often {' + '.join(c['lead_combo'])}. "
            f"Combined: median T{_num(c['median'])} over {c['killing_games']} of {n} games.")
