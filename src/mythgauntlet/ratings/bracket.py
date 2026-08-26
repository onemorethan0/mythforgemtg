"""Bracket estimate: synthesize the measured axes into an official 1-5 Commander Bracket.

This is the headline user-facing output ("what bracket is my deck?"). It is RULE-BASED,
mirroring how the official WotC Commander Brackets (Feb 2026) actually work — the system is
defined by hard gates (Game Changers count, in-deck game-ending combos of any size, mass land
denial, chained extra turns), not a hidden score. We apply those gates to set the allowed band,
then use the
measured Power Profile axes to place within it, and report a confidence + the reasons that
drove the call.

Honest scope: this is the official-rules estimate, not a learned calibration. A fitted
ordinal model over a large labeled corpus (roadmap Phase 5) is future work — the corpus is
still too small to fit without overfitting. Distinguishing 4 vs 5 (optimization/cEDH intent)
is inherently soft without a gauntlet Meta-strength rating, so the estimate leans on that
when supplied and stays conservative otherwise.

Two boundaries are decided by measurement rather than by a rules gate, and both were
re-measured on 2026-07-28 against the enlarged anchor set (B1 78 / B2 90 / B3 84) using
`scripts/axis_separation.py`. Re-run it before changing either.

**B1 vs B2 — mana-base consistency.** The gates put every zero-Game-Changer deck in the band
[1,2]; placing within it used to test ceiling/speed, which gave 5.9% B1 recall on a sample
that was 44% B1 — i.e. "always say Core" with noise. Mana-base colour consistency is the only
measured signal above "weak" at that boundary (Cohen's d +0.61) and lifts accuracy 58.7% ->
64.5% with balanced recall. See `estimate_bracket` for the table.

**B2 vs B3 — not resolvable, and we say so.** The Game Changer gate itself is good where it
applies (79.2% accuracy over 173 anchors, d +1.27), but 40% of author-labeled Upgraded decks
carry ZERO Game Changers, so the gate must call them Core. `plays_up` marks that band. It
used to gate on ceiling/speed/interaction "upper-Core tuning" thresholds — measured, those
fired on 33% of Upgraded and 37% of Core decks, more often on the ones they should have left
alone, and NOTHING we compute separates that population (best signal d +0.37). So the flag no
longer claims a per-deck reading; it states the calibration fact that applies to every deck in
the band. That is the honest-uncertainty invariant applied to our own heuristic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mythgauntlet.data.spellbook import ComboAssessment
from mythgauntlet.model.card import Card

# Root-level Forge module (`<repo>/bracket.py`, NOT this package). Reachable in the engine's
# real deployed configuration because `manage.bat`'s `:ensure_gauntlet` launches
# `python -m mythgauntlet serve` with the working directory pinned to the repo root
# (`start ... /d "%~dp0"`), and a `-m` invocation prepends the CURRENT WORKING DIRECTORY to
# `sys.path` -- so root `bracket.py` sits on the path even though the engine is otherwise a
# separate process with no Forge package on it (see CLAUDE.md: "the engine runs on :8020
# without Forge on its path" refers to `mythgauntlet.*`, a package import, not a bare
# top-level module next to the launch cwd). Still guarded: this is an implicit dependency on
# HOW the process is launched, not something to assume in every environment (an installed
# package elsewhere, a different launcher). Falling back to empty sets there just means the
# name-list fallback below is inert and `_scan` stays regex-only -- an honest under-count,
# never a crash, matching this file's own philosophy.
try:
    from bracket import EXTRA_TURN_CARDS, MASS_LAND_DESTRUCTION_CARDS
except ImportError:  # pragma: no cover - exercised only when Forge's root isn't on sys.path
    EXTRA_TURN_CARDS = frozenset()
    MASS_LAND_DESTRUCTION_CARDS = frozenset()

BRACKET_LABELS = {1: "Exhibition", 2: "Core", 3: "Upgraded", 4: "Optimized", 5: "cEDH"}

_EXTRA_TURN_RE = re.compile(r"take an extra turn|extra turn after this one", re.IGNORECASE)
# Mass land denial. A SINGLE match forces floor=4/cap=5 below, so a false positive
# here is not a rounding error — it reports a casual deck as "Optimized".
#
# Validated 2026-08-07 by diffing old vs new across all 34,179 cards in
# data/cards_slim.json. The previous patterns were wrong in both directions:
#
#   FABRICATED (forced B4 on 7 cards that are not mass land denial)
#     `lands?` had no word boundary, so "sacrifices all nonLAND permanents" matched.
#     Tragic Arrogance — an ordinary Bracket-2 wrath — reported Bracket 4, as did
#     Shard of the Void Dragon. The other five (Tremble, Yawning Fissure, Hurloon
#     Shaman, Akki Blizzard-Herder, Razing Snidd) sacrifice ONE land: attrition,
#     not MASS denial.
#
#   MISSED (9 cards that really are mass land denial)
#     The literal "destroy all lands" does not appear in Jokulhaups, Obliterate,
#     Devastation, Death Cloud, Pox, Gerrymandering, Realm Razer or Tectonic Hellion.
#
# Two guards are load-bearing and must survive any edit here:
#   \b around land/lands   — stops "nonland" matching.
#   (?!except)             — stops sweepers that explicitly SPARE lands from matching
#                            ("Destroy all permanents except for artifacts and lands":
#                            Scourglass, Elspeth Tirel, World-Bottling Kit), and keeps
#                            graveyard hate out ("other than basic land cards":
#                            Haunting Echoes) via the plural requirement.
# Plural "lands" is deliberate: a single symmetric land sacrifice stays unflagged,
# which is the honest under-count rather than a fabricated Bracket 4.
_MLD_RES = (
    # "Destroy/Exile all … lands" — including the multi-type sweepers.
    re.compile(r"\b(?:destroy|exile) all\b(?:(?!except)[^.])*?\blands\b", re.IGNORECASE),
    # Symmetric or one-sided sacrifice of MULTIPLE lands.
    re.compile(r"\beach (?:player|opponent)\b[^.]*?\bsacrifices?\b[^.]*?\blands\b", re.IGNORECASE),
    # …or of one land per something, which scales into mass denial (Thoughts of Ruin).
    re.compile(r"\beach (?:player|opponent)\b[^.]*?\bsacrifices?\b[^.]*?\bland\b[^.]*?\bfor each\b", re.IGNORECASE),
)


@dataclass
class BracketEstimate:
    bracket: int  # 1-5
    label: str
    confidence: float  # 0-1
    reasons: list[str] = field(default_factory=list)
    game_changers: int = 0
    two_card_combos: int = 0
    extra_turn_cards: int = 0
    mass_land_denial_cards: int = 0
    plays_up: bool = False  # capped at Core by the gates, but measures at the Core/Upgraded edge


def _scan(cards: list[tuple[Card, int]]) -> tuple[int, int]:
    """(extra-turn card copies, mass-land-denial card copies).

    Primarily oracle-text regex (`_EXTRA_TURN_RE`/`_MLD_RES`). Falls back to the name-list
    frozensets (`EXTRA_TURN_CARDS`/`MASS_LAND_DESTRUCTION_CARDS`, imported from root
    `bracket.py` above -- the same lists `BracketFilter.allows()` uses) for a card whose
    oracle text is missing, blank, or doesn't parse cleanly: a KNOWN extra-turn or MLD card
    should not silently pass the gate just because its text field is empty. Regex still runs
    first/always, so a reprint or a new card with the same effect but a name not yet in
    either list is still caught by wording alone.
    """
    extra = mld = 0
    for card, count in cards:
        text = card.oracle_text or ""
        if _EXTRA_TURN_RE.search(text) or card.name in EXTRA_TURN_CARDS:
            extra += count
        if any(r.search(text) for r in _MLD_RES) or card.name in MASS_LAND_DESTRUCTION_CARDS:
            mld += count
    return extra, mld


# B1-vs-B2 threshold on mana-base colour consistency. See estimate_bracket for the
# measurement that chose it; it is a recall-balance choice, not a fitted optimum. The
# PARAMETER defaults to 1.0 (not this value) so every existing caller and any deck we
# can't measure stays on the Bracket-2 side rather than being silently demoted to
# Exhibition.
#
# Moved 0.78 -> 0.80 on 2026-08-07 because the INPUT changed, not because the old value
# was mis-fitted. `manabase.count_sources` now credits fetchlands (they carry
# `produced_mana == []`, so every one of them previously counted as zero colour
# sources). That lifts consistency on 329 of 482 corpus decks (mean +0.040, max +0.208),
# which shifts the whole distribution right and would have skewed the split at 0.78.
# Re-measured over the same 170 labelled B1/B2 anchors, same methodology:
#
#   counting     thresh   acc     B1 recall   B2 recall
#   old (blind)  0.78     0.641     0.603       0.674     <- previous operating point
#   new (fetch)  0.78     0.624     0.487       0.739     <- skewed toward B2
#   new (fetch)  0.80     0.635     0.577       0.685     <- restored, and now correct
#
# Accuracy is unchanged within noise (0.641 vs 0.635 is one deck in 170) — this axis is
# weak either way. The point of the change is that the MODEL is right: a deck running
# four Evolving Wilds is no longer told its mana base is thin.
_EXHIBITION_MANA = 0.80


def _fast_two_card_combo(two_card_combos: int, profile: ComboAssessment | None) -> bool:
    """The cEDH escalation signal. With a graded profile, require the 2-card combo to be a
    FAST TERMINAL win (not e.g. a 2-card infinite-mana engine with no outlet). Without a
    profile (counts-only callers, existing tests), fall back to the old 'any 2-card' rule.
    """
    if profile is not None:
        return profile.fast_terminal_two_card
    return bool(two_card_combos)


def estimate_bracket(
    cards: list[tuple[Card, int]],
    commanders: list[Card],
    *,
    ceiling: float = 0.0,
    speed_kill_rate: float = 0.0,
    consistency: float = 0.0,  # T0 consistency_score (0-100)
    interaction: float = 0.0,  # Interaction axis (0-100)
    avg_kill_turn: float | None = None,  # goldfish mean kill turn
    manabase_consistency: float = 1.0,  # ratings/manabase.py mean colour probability (0-1)
    two_card_combos: int = 0,
    combo_count: int = 0,  # in-deck game-ending combos of ANY size (>= two_card_combos)
    combo_profile: ComboAssessment | None = None,  # graded combos (refines the flat gate)
    can_go_off: bool = False,  # a storm/spellslinger nut-draw kill (sim/storm.py)
    combos_checked: bool = False,
    meta_rating: float | None = None,
    coverage_share: float = 1.0,
) -> BracketEstimate:
    all_cards = list(cards) + [(c, 1) for c in commanders]
    gc_names = {c.name for c, _ in all_cards if c.game_changer}
    gc = len(gc_names)
    extra_turns, mld = _scan(all_cards)

    reasons: list[str] = []

    # --- official hard gates set the allowed band [floor, cap] ---
    if gc == 0:
        floor, cap = 1, 2
        reasons.append("0 Game Changers -> Brackets 1-2")
    elif gc <= 3:
        floor, cap = 3, 3
        reasons.append(f"{gc} Game Changer(s) (<=3) -> Bracket 3")
    else:
        floor, cap = 4, 5
        reasons.append(f"{gc} Game Changers (>3) -> Brackets 4-5")

    combos = max(combo_count, two_card_combos)  # any in-deck game-ending combo (2- or 3+-card)
    if combo_profile is not None:
        combos = max(combos, combo_profile.total)
    if combos:
        if floor < 3:
            floor, cap = max(floor, 3), max(cap, 3)
            if combo_profile is not None and combo_profile.grades:
                # Graded reason: says WHICH kind of combo(s) drove the gate, not just a count.
                reasons.append(combo_profile.gate_reason())
            else:
                detail = f" ({two_card_combos} two-card)" if two_card_combos else ""
                reasons.append(f"{combos} in-deck game-ending combo(s){detail} -> min Bracket 3")
    if can_go_off:
        # a storm/spellslinger deck that reaches lethal on its nut draw is an emergent combo-kill;
        # the commander-as-engine (Prismari class) is invisible to the combat clock (sim/storm.py).
        if floor < 3:
            floor, cap = max(floor, 3), max(cap, 3)
            reasons.append("storm/spellslinger go-off (nut-draw kill) -> min Bracket 3")

        # A genuine engine that converts on a FAST, TYPICAL timeline outgrows the fixed
        # gc<=3 -> exactly-Bracket-3 band, and the official guidelines hand us the exact
        # number to test against: Bracket 3 promises opponents "at least six turns before
        # you win or lose", Bracket 4 promises "at least four". A deck whose REALIZED
        # average kill turn (not the best-case ceiling `estimate_go_off` itself reports --
        # this reads `avg_kill_turn`, the same goldfish-clock figure `apply_nut_kills`
        # already teaches to see this exact kill pattern) sits under six cannot honestly
        # make Bracket 3's promise, whatever its Game Changer count.
        #
        # THIS IS A GUIDELINE-DERIVED THRESHOLD, NOT A CORPUS-FITTED ONE, and that
        # distinction matters here specifically. `scripts/axis_separation.py` measured
        # kill-turn signals as flat/weak across the WHOLE labeled corpus (rho ~ -0.09,
        # never a top-4 B3-vs-B4 signal) -- but that average is diluted by the ~99% of
        # decks with no non-combat engine at all; among decks that actually go off, the
        # labeled corpus holds exactly THREE examples (`corpus/decks/manifest.json`), all
        # zero or three Game Changers, none labeled Bracket 4, none fast enough to trip
        # this gate (avg_kill_turn 7.98 / 8.00 / 10.17 -- all comfortably clear Bracket 3's
        # own six-turn floor and are correctly UNCHANGED by this rule). The gate that
        # motivated it is a real, verified counter-example outside the self-reported
        # corpus: a live Archidekt decklist (Prismari, the Inspiration -- the exact
        # "commander-as-engine" case named in the comment above when this module was
        # built) that this engine measures at avg_kill_turn 4.73 / kill_rate 1.0 / zero
        # Game Changers, and that its own playgroup places at Bracket 4 on that same
        # basis (speed + consistency) -- Archidekt carries no self-reported bracket tag
        # for it (`edhBracket: null`), so this is real community judgment, not another
        # corpus label of the kind this file's other boundaries were fit against.
        #
        # So: verified not to move any of the 3 known anchors, and known to fix the 1
        # concrete case it was written for. That is a much smaller n than this file's
        # other measured boundaries and is recorded here as exactly that -- a principled
        # inference from the rules text, spot-checked, not a statistically powered fit.
        # Revisit with `scripts/axis_separation.py` once the corpus grows more go-off
        # anchors (`mythgauntlet fetch-decks --bracket 4` biased toward spellslinger/storm
        # commanders would be the fastest way to grow this specific cell).
        if avg_kill_turn is not None and avg_kill_turn < 6.0 and floor < 4:
            floor, cap = 4, max(cap, 4)
            reasons.append(
                f"go-off engine converts by turn {avg_kill_turn:.1f} on average, under "
                "Bracket 3's own six-turn floor -> min Bracket 4"
            )
    if mld:
        floor, cap = max(floor, 4), 5
        reasons.append(f"mass land denial ({mld}) -> Brackets 4-5")
    if extra_turns >= 2:
        floor, cap = max(floor, 4), 5
        reasons.append(f"chained extra turns ({extra_turns}) -> Brackets 4-5")

    # --- place within the band using measured power ---
    bracket = floor
    if floor == 1 and cap == 2:
        # 1 (exhibition/ultra-casual) vs 2 (precon-level). Decided on MANA-BASE consistency,
        # measured 2026-07-28 against 155 rules-consistent B1/B2 anchors
        # (scripts/axis_separation.py; re-run it if you change this):
        #
        #   rule                                   acc    B1 recall   B2 recall
        #   ceiling>=15 or speed>=0.10 (OLD)      58.7%       5.9%      100.0%
        #   always say B2 (baseline)              56.1%       0.0%      100.0%
        #   manabase consistency >= 0.78          64.5%      58.8%       69.0%
        #
        # The old gate was "always say B2" with noise on top: it produced Bracket 1 for 6%
        # of decks in a sample that was 44% B1. Ceiling and speed simply do not separate
        # these two (Cohen's d +0.30 and ~+0.09); mana-base consistency does (d +0.61), and
        # it is the ONLY measured signal above "weak" at this boundary. Intuition matches:
        # B1 is "theme over power", where five-colour pet decks live, and their mana is
        # genuinely worse than a precon's.
        #
        # NOTE it must REPLACE the old test, not join it — `OLD or manabase` scores 56.8%,
        # WORSE than manabase alone, because OR-ing an always-B2 rule re-imposes its bias.
        # Accuracy is flat across thresholds 0.70-0.78 (all 64.5%); they differ only in
        # recall balance, so 0.78 is chosen for the most even split rather than a fitted peak.
        if manabase_consistency >= _EXHIBITION_MANA:
            bracket = 2
            reasons.append(
                f"mana base holds up ({manabase_consistency:.0%} colour consistency) "
                "-> Bracket 2 (core)"
            )
        else:
            bracket = 1
            reasons.append(
                f"thin mana base ({manabase_consistency:.0%} colour consistency) "
                "-> Bracket 1 (exhibition)"
            )
    elif floor >= 4:
        # 4 (optimized) vs 5 (cEDH): needs meta-strength/intent; conservative without it
        if meta_rating is not None and meta_rating >= 1650:
            bracket = 5
            reasons.append(f"high gauntlet rating ({meta_rating:.0f}) -> Bracket 5 (cEDH)")
        elif _fast_two_card_combo(two_card_combos, combo_profile) and ceiling >= 40 \
                and speed_kill_rate >= 0.4:
            bracket = 5
            reasons.append("fast combo kill + high ceiling -> Bracket 5 (cEDH) range")
        else:
            bracket = 4
            reasons.append("optimized power; not clearly cEDH-tuned -> Bracket 4")

    # --- B2/B3 boundary banner (honest uncertainty, not a B3 classifier) ---
    # This flag used to gate on _upper_core(ceiling/speed/interaction/consistency). Measured
    # 2026-07-28 against 120 zero-Game-Changer anchors, that gate was WORSE THAN USELESS: it
    # fired on 33% of decks their authors labeled Upgraded and 37% labeled Core — more often
    # on the ones it was supposed to leave alone. So a third of Core decks were told they sit
    # at the Upgraded boundary for no measured reason.
    #
    # Nothing we compute separates that population (best signal nut_kill_rate d=+0.37, weak;
    # everything else weak or none), which is unsurprising: with 0 Game Changers the official
    # gate is silent by design, and the real Core/Upgraded line is card-quality and tuning
    # that goldfish fidelity cannot see.
    #
    # So the flag no longer PRETENDS to detect tuning per deck. It now states a calibration
    # fact that is true of every deck in this position: 40% of author-labeled Upgraded decks
    # (33/83) carry zero Game Changers, so a zero-GC "Core" verdict genuinely cannot rule
    # Upgraded out. That is honest uncertainty; the old banner was false precision.
    #
    # This band also has a Bracket-1 side (the mana-base sub-placement above lands at 1, not
    # 2), and it used to carry NO uncertainty flag at all -- `plays_up` required bracket == 2
    # exactly, on the stated assumption "a deck placed at Bracket 1 isn't at the Core/Upgraded
    # boundary at all" (see the test this replaced, test_plays_up_not_claimed_for_exhibition).
    # That assumption was never measured, and checking it (scripts/bracket_accuracy.py --json,
    # full 297-deck corpus, 2026-08-24) shows it doesn't hold: of decks landing HERE via a thin
    # manabase, 14.1% (10/71) are called Upgraded by their own builder anyway -- lower than the
    # 24.2% (30/124) rate on the Bracket-2 side of this same gate, but not the "not at the
    # boundary at all" the old test claimed. The mechanism is the same reason the Bracket-2
    # side is silent: manabase CONSISTENCY and deck POWER are different things (a deck can run
    # a greedy manabase for power reasons and still be genuinely strong), and the Game Changer
    # gate already can't see power once GC == 0 regardless of which side of the mana-base split
    # a deck lands on.
    plays_up = bracket in (1, 2) and (floor, cap) == (1, 2)
    if plays_up:
        if bracket == 2:
            reasons.append(
                "0 Game Changers caps this at Core, but 40% of decks their authors call "
                "Upgraded also run none -- this boundary is not resolvable from card gates; "
                "read the axes"
            )
        else:
            reasons.append(
                "0 Game Changers and a thin manabase cap this at Exhibition, but the Game "
                "Changer gate is nearly silent on power once it reads zero -- 14% of decks "
                "placed here are called Upgraded by their own builders too; read the axes"
            )

    # --- confidence ---
    confidence = 0.75
    if floor != cap and bracket in (4, 5) and meta_rating is None:
        confidence -= 0.20  # 4-vs-5 is soft without a gauntlet rating
    if combos and not combos_checked:
        confidence -= 0.10
    if not combos_checked:
        # Two different situations, and one flat note described both wrongly. When a caller
        # supplies a combo COUNT without having run a verified check, the gate above has
        # already fired ("N in-deck game-ending combo(s) -> min Bracket 3") and saying
        # "combos not checked" next to it is a contradiction a reader cannot resolve - it
        # reads as "no combo information was used" while a combo promotion is sitting two
        # lines up. The confidence dock was the only signal, and confidence is not in the
        # reason list. Same class as S3: a label that misdescribes what was measured.
        reasons.append(
            f"note: {combos} combo(s) were DECLARED but not verified - the gate above used "
            "an unchecked count (run with --combos to verify)"
            if combos else
            "note: combos not checked (run with --combos for the combo gate)"
        )
        confidence -= 0.05
    confidence *= 0.6 + 0.4 * max(0.0, min(1.0, coverage_share))  # lower if semantics thin
    confidence = max(0.2, min(0.95, confidence))

    return BracketEstimate(
        bracket=bracket,
        label=BRACKET_LABELS[bracket],
        confidence=confidence,
        reasons=reasons,
        game_changers=gc,
        two_card_combos=two_card_combos,
        extra_turn_cards=extra_turns,
        mass_land_denial_cards=mld,
        plays_up=plays_up,
    )
