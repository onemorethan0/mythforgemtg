"""Turn a swap's measured facts into one honest paragraph, and refuse it when it isn't.

`advise` returns template fragments — `"A big dragon your commander can cheat into play; a
one-shot team finisher. Measured: kills ~1.2 turns sooner."` It reads as a list because it is
one, and it never says why THAT card was the cut, which is the half a user questions.

A language model writes better prose. It also fabricates, and a fluent sentence is an
excellent disguise for an invented one — on an MTG-facing surface a wrong claim about a card
is a defect, not an approximation. So generation here is **draft, then gate**, and the gate
is the point of the module.

WHAT MAKES THIS GATEABLE. The engine emits a `SwapBrief` (`mythgauntlet.ratings.swap_brief`)
that is an explicit CLAIM BUDGET: the only card names that may appear, the only numbers that
may be cited, the card's functions as the rung-1 vector actually read them, and whether the
cut was backed by real redundancy at all. Nothing here is a matter of taste — every check
below traces a sentence back to a measured field, exactly as the CCM compiler's gates trace a
capability model back to Oracle text.

WHAT IT CANNOT DO. There is no validator for "good advice", and this does not pretend to be
one. It catches INVENTION, not weakness: a bland but faithful sentence passes, and that is
the correct bias. The deterministic `reason` is always kept as the fallback, so a rejected
draft costs the user nothing but polish.

Why here and not in the engine: `deck_builder` cannot import `mythgauntlet.*` — the engine is
a separate process on :8020 and Forge runs without `src/` on its path. The brief crosses as
JSON, which is also why `SwapBrief.as_dict()` exists. Same wall the archetype contract
respects from the other side.
"""

from __future__ import annotations

import re

# Reject any draft longer than this. Not a style preference: a model that keeps writing is a
# model that has run out of facts and started composing, and every extra clause is another
# chance to invent. The brief supports two or three sentences of substance.
MAX_CHARS = 420
MIN_CHARS = 40

# Numbers a sentence can legitimately contain that are not measurements — small counts used
# as ordinary English ("one", "a second copy", "turn 1"). Checking these against the brief
# would reject correct prose, so they are exempt and the exemption is deliberately tiny.
_FREE_NUMBERS = {0.0, 1.0, 2.0}

# Tolerance when matching a cited number against the brief. Prose rounds — "about 7" for 7.3
# is honest — so an exact-match rule would fail faithful sentences. Wide enough to forgive
# rounding, far too narrow to let an invented figure through.
_NUMBER_TOLERANCE = 0.6

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")

# Below one card's worth of a role, an "oversupply" is a rounding step and must not be
# narrated as a verdict. Role strengths run 1.0-3.0 per card, so 1.0 is the conservative
# floor at which a gap is definitely at least one real card.
_MARGINAL_OVERSUPPLY = 1.0

_INTENSIFIERS = (
    "well over", "far over", "way over", "much more than", "drowning", "flooded",
    "far too", "way too", "significantly over", "heavily", "massively", "vastly",
)

# The five Power Profile axes. Exactly ONE is measured per swap; naming another asserts a
# measurement that was never taken. `interaction` and `resilience` are especially tempting
# for a model reaching for a satisfying second clause.
# STEMS, not the noun. "far more consistent" is a claim about Consistency and the
# literal "consistency" never matches it - a draft asserting exactly that slipped
# through the check. Each stem covers the noun and the adjective.
_AXIS_STEMS = {
    "consistency": "consisten",
    "speed": "speed",
    "resilience": "resilien",
    "interaction": "interact",
    "ceiling": "ceiling",
}

# Words that assert the cut is surplus. Only usable when the brief says a role was genuinely
# over-supplied — see `redundancy_backed` and ROADMAP S12: on 9.0% of decks nothing is
# over-supplied, `rank_redundant` still owes its caller candidates, and it falls through to a
# least-played tiebreak. Calling that "redundant" invents the finding the module failed to
# make.
_REDUNDANCY_CLAIMS = (
    "redundant", "redundancy", "over-supplied", "oversupplied", "over-served",
    "overserved", "surplus", "too many", "excess", "duplicate", "overkill",
)

# Function vocabulary the gate can adjudicate. A draft may only call the card one of these
# when the brief's `functions` agree. Phrased as the words a model actually reaches for.
_FUNCTION_CLAIMS: dict[str, tuple[str, ...]] = {
    # "accelerat" alone is NOT here: "accelerates the strategy" is ordinary English and
    # rejected a faithful draft. A ramp claim has to name mana.
    "ramp": ("ramp", "mana acceleration", "accelerates your mana", "more mana available"),
    "land ramp": ("land ramp", "fetches a land", "searches for a land"),
    "card draw": ("draw", "cantrip", "card advantage"),
    "repeatable draw": ("repeatable draw", "draw engine"),
    "tutor": ("tutor", "searches your library", "finds your"),
    # NOT "removes": "cutting Xenagos removes a point of ramp" is how anyone describes making
    # a CUT, and reading it as "this card is a removal spell" rejected a faithful draft.
    "removal": ("removal spell", "targeted removal", "destroys target", "exiles target"),
    "board wipe": ("board wipe", "wrath", "sweeper", "mass removal"),
    "counterspell": ("counterspell", "counters a spell", "counters target"),
    "cheats creatures into play": ("cheat", "puts creatures onto the battlefield",
                                   "reanimat"),
    "storm": ("storm",),
    "magecraft burn": ("magecraft",),
    "scaling burn": ("scaling burn", "x-damage", "x damage"),
    "spell cost reduction": ("cost reduction", "costs less"),
    "ritual mana": ("ritual",),
    "team pump": ("team pump", "pumps your team", "anthem", "overrun"),
    "scaling team pump": ("craterhoof", "scaling pump"),
}


# `redundancy.card_roles` and `swap_brief.card_functions` speak DIFFERENT vocabularies, and
# conflating them rejects honest prose. A role is an aggregate over functions: role `draw` is
# `draw_cards + 1.5 * engine_draw`, so a card whose draw is entirely an engine holds the
# function "repeatable draw" and NO "card draw" — while the brief still reports its role as
# `draw` and a writer will naturally say "card draw". Same for `wipe` -> "board wipe" and the
# finisher roll-up.
#
# So a card may also be described by any function that could have produced the ROLE the engine
# assigned it. This widens the vocabulary only for the role the engine already granted; it
# never lets a card be called something outside that role.
_ROLE_VOCABULARY: dict[str, set[str]] = {
    "ramp": {"ramp", "land ramp"},
    "draw": {"card draw", "repeatable draw"},
    "removal": {"removal"},
    "wipe": {"board wipe"},
    "counterspell": {"counterspell"},
    "tutor": {"tutor"},
    "finisher": {"team pump", "scaling team pump", "scaling burn", "storm",
                 "cheats creatures into play", "magecraft burn", "burn per cast"},
}


# Functions that differ by a shade no reader distinguishes. A card holding ANY member lets a
# sentence use any member's wording. Found on real output: "repeatable draw and a bit of ramp"
# was rejected for calling the card "card draw" - on a card whose vector says repeatable draw -
# because the bare word "draw" triggers the card-draw phrasing.
#
# Deliberately NARROW. `removal` and `board wipe` are NOT one family: targeted removal and a
# sweeper are different cards and calling one the other is a real error. Nor are `ramp` and
# `ritual mana` - permanent mana and a one-shot ritual are different promises.
_FUNCTION_FAMILIES: tuple[frozenset[str], ...] = (
    frozenset({"card draw", "repeatable draw"}),
    frozenset({"ramp", "land ramp"}),
    frozenset({"team pump", "scaling team pump"}),
    frozenset({"magecraft burn", "burn per cast", "scaling burn"}),
)


def _widen_by_family(held: set[str]) -> set[str]:
    """Every function `held` licenses, including its family siblings."""
    widened = set(held)
    for family in _FUNCTION_FAMILIES:
        if held & family:
            widened |= family
    return widened


# Card names that are ALSO the vocabulary this gate hands the model. Magic prints a card
# called **Counterspell**, and `counterspell` is simultaneously the engine's role name — so a
# deck holding that card had every honest sentence about an over-supplied counterspell role
# read as naming a foreign card. Six of thirty-six good drafts died on it.
#
# Built from the licensed vocabulary rather than hand-listed, so a role or function added
# later is covered without anyone remembering to come back here. Duress, Regrowth, Fog and
# friends land in it the moment their word becomes vocabulary.
def _vocabulary_names() -> frozenset[str]:
    words = set(_ROLE_VOCABULARY) | set(_FUNCTION_CLAIMS) | set(_AXIS_STEMS)
    for phrases in _FUNCTION_CLAIMS.values():
        words.update(phrases)
    return frozenset(w.casefold() for w in words)


def _looks_like_a_name(text: str, match: re.Match) -> bool:
    """Is this occurrence a proper NAME rather than the common noun?

    Capitalised and not sentence-initial. Crude, and deliberately biased toward letting the
    common-noun reading win: missing a mention of a card that shares its name with a role word
    is a mild under-count, while rejecting honest prose about that role is the failure that
    was actually happening.
    """
    word = text[match.start():match.end()]
    if not word[:1].isupper():
        return False
    before = text[:match.start()].rstrip()
    return bool(before) and before[-1] not in ".!?"


class GateFailure(Exception):
    """A draft asserted something the brief does not support. Carries every reason."""

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("; ".join(reasons))


def _numbers_in(text: str) -> list[float]:
    return [float(m.group()) for m in _NUMBER_RE.finditer(text)]


def _known_card_names(brief: dict) -> set[str]:
    return {n for n in (brief.get("allowed_card_names") or []) if n}


def allowed_numbers(brief: dict) -> set[float]:
    """Rebuild the brief's numeric claim budget from its JSON form.

    Mirrors `SwapBrief.allowed_numbers`. It is duplicated rather than imported for the same
    reason the module lives here at all — Forge cannot import the engine — and
    `test_allowed_numbers_matches_the_engine` pins the two implementations together, exactly
    as `test_slug_matches_the_engine_implementation` does for the EDHREC slug.
    """
    add, cut = brief.get("add") or {}, brief.get("cut") or {}
    nums: set[float] = {
        round(float(brief.get("before", 0.0)), 1),
        round(float(brief.get("after", 0.0)), 1),
        round(abs(float(brief.get("delta", 0.0))), 1),
        float(add.get("mana_value", 0)),
        float(cut.get("mana_value", 0)),
        round(float(cut.get("role_supply", 0.0)), 1),
        float(cut.get("role_target", 0)),
        round(float(cut.get("oversupply", 0.0)), 1),
        round(float(cut.get("within_role", 0.0)), 1),
    }
    for fns in (add.get("functions") or {}, cut.get("functions") or {}):
        for value in fns.values():
            nums.add(round(float(value), 1))

    kt_b, kt_a = brief.get("kill_turn_before"), brief.get("kill_turn_after")
    for reading in (kt_b, kt_a):
        if reading is not None:
            nums.add(round(float(reading), 1))
    if kt_b is not None and kt_a is not None:
        nums.add(round(abs(float(kt_b) - float(kt_a)), 1))

    kr_b, kr_a = brief.get("kill_rate_before"), brief.get("kill_rate_after")
    for rate in (kr_b, kr_a):
        if rate is not None:
            nums.add(round(float(rate) * 100))
    if kr_b is not None and kr_a is not None:
        nums.add(round(abs(float(kr_a) - float(kr_b)) * 100))

    for rank in (add.get("edhrec_rank"), cut.get("edhrec_rank")):
        if rank is not None:
            nums.add(float(rank))
    return {float(n) for n in nums}


def check(text: str, brief: dict, *, deck_card_names: set[str] | None = None) -> list[str]:
    """Every way `text` over-claims against `brief`. Empty list means it is faithful.

    Returns reasons rather than raising so a corpus builder can bucket rejections and see
    WHICH check is doing the work — the same reason `compile_card`'s gates report per-gate
    failures instead of a single boolean.
    """
    reasons: list[str] = []
    body = text.strip()
    lower = body.lower()

    if not MIN_CHARS <= len(body) <= MAX_CHARS:
        reasons.append(f"length {len(body)} outside {MIN_CHARS}-{MAX_CHARS}")

    # 1. CARD NAMES. A model reaching for a plausible synergy piece has invented a card into
    #    someone's decklist. Only the add, the cut and the commander are ever nameable.
    #
    #    The allowed names are MASKED OUT FIRST, because Magic card names nest inside one
    #    another: the commander "Omo, Queen of Vesuva" contains "Vesuva", which is itself a
    #    real card, so scanning the raw text flagged a sentence that only ever named the
    #    commander. Masking is the difference between "did it name a foreign card" and "does
    #    a foreign card's name appear as a substring of a permitted one".
    allowed = _known_card_names(brief)
    masked = body
    for name in sorted(allowed, key=len, reverse=True):     # longest first: nested names
        masked = re.sub(re.escape(name), " ", masked, flags=re.IGNORECASE)
    for name in (deck_card_names or set()) - allowed:
        # Word-boundary match so "Bind" does not fire inside "binding".
        for match in re.finditer(rf"\b{re.escape(name)}\b", masked, re.IGNORECASE):
            if name.casefold() in _vocabulary_names() and not _looks_like_a_name(masked, match):
                # A ROLE word, not a card. See _VOCABULARY_NAMES.
                continue
            reasons.append(f"names a card outside the swap: {name!r}")
            break

    # 2. NUMBERS. Anything cited must trace to a measurement.
    budget = allowed_numbers(brief)
    for value in _numbers_in(body):
        if value in _FREE_NUMBERS:
            continue
        if not any(abs(value - ok) <= _NUMBER_TOLERANCE for ok in budget):
            reasons.append(f"cites {value:g}, which is not in the brief")

    # 3. DIRECTION. The measured delta is the verdict; prose must not contradict its sign.
    delta = float(brief.get("delta", 0.0))
    label = str(brief.get("axis_label", "")).lower()
    if delta > 0 and re.search(rf"(lowers?|reduces?|costs? you|hurts?|worsens?)\s+{label}", lower):
        reasons.append(f"claims the swap lowers {label} while the measured delta is +{delta}")

    # 4. FUNCTION CLAIMS. Calling a card something the rung-1 vector cannot see.
    #
    # Each phrase is attributed to the NEAREST card name, not to every card within a window.
    # Attributing by window alone was the first version and it was wrong in a way that only
    # showed up on good drafts: "Jubilation is a team pump ... An Offer You Can't Refuse is
    # the cut" put both names near "team pump", so a faithful sentence about the ADD was also
    # read as a false claim about the CUT. A false rejection costs polish rather than
    # correctness, but it silently starves the corpus of exactly the drafts worth keeping.
    add_card, cut_card = brief.get("add") or {}, brief.get("cut") or {}
    cards = {
        str(add_card.get("name", "")): (
            "add", _widen_by_family(set(add_card.get("functions") or {}))),
        # The cut also answers to the ROLE the engine assigned it — see _ROLE_VOCABULARY.
        str(cut_card.get("name", "")): (
            "cut",
            _widen_by_family(
                set(cut_card.get("functions") or {})
                | _ROLE_VOCABULARY.get(str(cut_card.get("role") or ""), set())
            ),
        ),
    }
    cards.pop("", None)
    # Where the swap's own card names sit, so a negator printed in a TITLE is not mistaken
    # for the author negating a claim.
    name_spans = [(m.start(), m.end())
                  for name in cards
                  for m in re.finditer(re.escape(name.lower()), lower)]
    seen_claims: set[tuple[str, str]] = set()
    for function, phrases in _FUNCTION_CLAIMS.items():
        for phrase in phrases:
            for match in re.finditer(re.escape(phrase), lower):
                if _negated_before(lower, match.start(), name_spans):
                    continue
                owner = _nearest_card(lower, match.start(), cards)
                if owner is None:
                    continue
                role, held = cards[owner]
                if function in held or (role, function) in seen_claims:
                    continue
                seen_claims.add((role, function))
                reasons.append(f"calls the {role} ({owner}) a {function!r}, "
                               f"which its vector does not show")

    # 5. INTENSITY. "16.5, well over the typical 16" is over by 0.5 — a rounding step dressed
    #    as a verdict. The number is true, so checks 2 and 6 both pass it, and it is still an
    #    over-claim: same shape as S3, where a population-relative label read as an absolute
    #    statement. An intensifier has to be earned by the size of the gap.
    over = float((brief.get("cut") or {}).get("oversupply", 0.0))
    if 0.0 < over < _MARGINAL_OVERSUPPLY:
        for word in _INTENSIFIERS:
            if word in lower:
                reasons.append(
                    f"calls an oversupply of {over:g} {word!r}, which overstates a gap "
                    f"smaller than one card's worth of the role")
                break

    # 6. OTHER AXES. Exactly one axis was measured for this swap. A sentence that also calls
    #    the deck "more consistent" has asserted a second measurement nobody took.
    measured = str(brief.get("axis", "")).lower()
    for axis, stem in _AXIS_STEMS.items():
        if axis == measured:
            continue
        if re.search(rf"\b{stem}\w*", lower):
            reasons.append(f"claims an effect on {axis}, which this swap did not measure")

    # 7. REDUNDANCY. The S12 guard: no calling a cut surplus when nothing was over-supplied.
    cut = brief.get("cut") or {}
    if not cut.get("redundancy_backed"):
        for claim in _REDUNDANCY_CLAIMS:
            if claim in lower:
                reasons.append(
                    f"claims redundancy ({claim!r}) but this deck over-supplies no role, "
                    "so the cut came from the least-played tiebreak")
                break
    return reasons


# How far a function phrase may sit from the card it describes before the attribution is
# treated as unknown (and therefore not a claim worth rejecting).
_ATTRIBUTION_WINDOW = 120

# A phrase inside a negation is not an assertion — "does not counter anything" must not read
# as "calls this a counterspell". Only the text immediately before the phrase is inspected,
# which is where English puts the negator.
_NEGATORS = ("not ", "n't ", "no ", "never ", "without ", "cannot ", "isn't ", "lacks ")


def _negated_before(lower_text: str, pos: int, spans=(), window: int = 24) -> bool:
    """Is the phrase at `pos` inside a negation the AUTHOR wrote?

    `spans` are the character ranges covered by the swap's own card names, and they are
    excluded — because a negator can come from a card's TITLE. "An Offer You Can't Refuse is
    a board wipe" contains `n't ` immediately before the claim, so the guard read the card's
    own name as the author negating themselves and waved a false claim straight through.
    Magic prints plenty of names like it (Can't, Never, No Mercy).
    """
    start = max(0, pos - window)
    haystack = lower_text[start:pos]
    for negator in _NEGATORS:
        index = haystack.find(negator)
        while index != -1:
            absolute = start + index
            if not any(a <= absolute < b for a, b in spans):
                return True
            index = haystack.find(negator, index + 1)
    return False


def _nearest_card(lower_text: str, pos: int, cards: dict) -> str | None:
    """Which of the swap's cards is `pos` describing — the nearest one BEFORE it.

    Preceding, not nearest-in-either-direction, and that distinction was found by reading
    real model output rather than reasoned out. English puts the subject before the
    predicate, so a clause describes the last card named:

        "Adding Mind into Matter ... by giving card draw and the ability to cheat in
         creatures ... Cutting Azami, Lady of Scrolls addresses an over-supply of draw."

    Nearest-either-direction attributed "cheat in creatures" to **Azami**, because by the time
    the phrase appears the cut's name is closer than the add's — and rejected a perfectly
    faithful sentence. Twice, in three drafts.

    Falls back to a following name only when nothing precedes (a clause that opens with the
    predicate). Crude either way: the alternative is parsing English, and the cost of being
    crude is a rejected draft, which is the safe direction.
    """
    best, best_distance = None, _ATTRIBUTION_WINDOW + 1
    for name in cards:
        for match in re.finditer(re.escape(name.lower()), lower_text):
            if match.start() > pos:
                continue                       # this name comes AFTER the phrase
            distance = 0 if match.end() >= pos else pos - match.end()
            if distance < best_distance:
                best, best_distance = name, distance
    if best is not None:
        return best
    # Nothing precedes it — fall back to the nearest following name.
    for name in cards:
        for match in re.finditer(re.escape(name.lower()), lower_text):
            distance = match.start() - pos
            if 0 <= distance < best_distance:
                best, best_distance = name, distance
    return best if best_distance <= _ATTRIBUTION_WINDOW else None


def gate(text: str, brief: dict, *, deck_card_names: set[str] | None = None) -> str:
    """Return `text` if it is faithful to `brief`; raise `GateFailure` otherwise."""
    reasons = check(text, brief, deck_card_names=deck_card_names)
    if reasons:
        raise GateFailure(reasons)
    return text.strip()


# ── Generation ───────────────────────────────────────────────────────────────────
# The draft half. Everything above is the verifier and has no model in it; everything below
# calls one and then submits to the verifier. Keeping the order that way round is deliberate —
# the gate is the contract, the generator is replaceable.

# qwen3:14b is the theming default and is already resident for most of a session. The teacher
# that BUILDS the fine-tune corpus is 32b (see scripts/build_reason_sft.py); this is the
# runtime default, where latency sits on the user's critical path.
DEFAULT_MODEL = "qwen3:14b"

# Low, because this is phrasing over supplied facts, not invention. The corpus builder raises
# it deliberately, to get variety worth curating.
DEFAULT_TEMPERATURE = 0.3

# Enough for three sentences plus slack. The cap is itself a guard: a model that keeps going
# has run out of facts and started composing.
DEFAULT_MAX_TOKENS = 220

_SYSTEM = """You explain ONE card swap in a Magic: The Gathering Commander deck.

You are given measured facts. Write 2-3 sentences of plain prose saying WHY the added card
helps and WHY that particular card is the one to cut. Write for a casual player.

HARD RULES - a violation is rejected outright:
1. Name ONLY these cards: {cards}. Never name any other card, real or imagined.
2. Cite ONLY numbers that appear in the facts below. Never estimate, extrapolate or invent a
   figure. Citing no numbers at all is always acceptable.
3. Describe each card using ONLY the functions listed for it. If a function is not listed,
   the card does not have it as far as you know.
4. {redundancy_rule}
5. The measured direction is the verdict: this swap RAISES {axis_label}. Never say otherwise.
6. {axis_label} is the ONLY axis measured here. Never mention consistency, speed, resilience,
   interaction or ceiling unless it is {axis_label} itself - not even to say a swap does not
   hurt one. Nobody measured that.

Write flowing prose, not a list. No markdown, no bullets, no preamble, no headings. Under 400
characters. Output only the explanation."""

_REDUNDANCY_OK = (
    "The cut IS over-supplied in its role - you may say so, and cite the supply and target."
)
_REDUNDANCY_FORBIDDEN = (
    "This deck over-supplies NO role, so the cut is NOT redundant and you must not call it "
    "redundant, surplus, excess, duplicated or 'too many'. Say instead that nothing in the "
    "deck is clearly spare, so this slot was simply the least-played one carrying a role."
)


def _fn_text(functions: dict | None) -> str:
    if not functions:
        return "none the engine can read from its rules text"
    return ", ".join(f"{word} ({value:g})" for word, value in sorted(functions.items()))


def _facts_block(brief: dict) -> str:
    """The brief rendered for a reader. Only what the prose is allowed to draw on."""
    add, cut = brief.get("add") or {}, brief.get("cut") or {}
    delta = abs(float(brief.get("delta", 0.0)))
    lines = [
        f"Commander: {brief.get('commander') or 'unknown'}",
        f"Deck archetypes: {', '.join(brief.get('archetypes') or []) or 'none detected'}",
        f"Target axis: {brief.get('axis_label')} "
        f"{brief.get('before')} -> {brief.get('after')} (+{delta:.1f})",
        "",
        f"ADD {add.get('name')} - {add.get('type_line')}, mana value {add.get('mana_value')}",
        f"  functions: {_fn_text(add.get('functions'))}",
    ]
    if add.get("on_tribe"):
        lines.append(f"  on-tribe for the commander: {add['on_tribe']}")
    if add.get("commander_can_cheat"):
        lines.append("  the commander can put creatures onto the battlefield")
    lines += [
        "",
        f"CUT {cut.get('name')} - {cut.get('type_line')}, mana value {cut.get('mana_value')}",
        f"  functions: {_fn_text(cut.get('functions'))}",
    ]
    if cut.get("role"):
        lines.append(
            f"  role {cut['role']}: deck supplies {cut.get('role_supply')}, "
            f"decks like this one supply {cut.get('role_target')} "
            f"(over by {cut.get('oversupply')})"
        )
    if cut.get("protected"):
        lines.append("  this card fills no role the engine can read")
    if not cut.get("redundancy_backed"):
        lines.append("  NOTE: no role in this deck is over-supplied")

    kt_b, kt_a = brief.get("kill_turn_before"), brief.get("kill_turn_after")
    if kt_b is not None and kt_a is not None:
        lines += ["", f"Simulated kill turn: {float(kt_b):.1f} -> {float(kt_a):.1f}"]
    kr_b, kr_a = brief.get("kill_rate_before"), brief.get("kill_rate_after")
    if kr_b is not None and kr_a is not None:
        lines.append(
            f"Games that close on the clock: {float(kr_b)*100:.0f}% -> {float(kr_a)*100:.0f}%")
    return "\n".join(lines)


def build_messages(brief: dict, system: str | None = None) -> list[dict]:
    """The chat messages for one brief. Pure - no network, so it is testable and diffable.

    `system` substitutes the whole system prompt. That exists for ONE purpose: a fine-tuned
    model is supposed to have learned the rules, so it would be served the terse prompt
    instead of the full rule sheet — and the size of that gap is the honest argument for
    training at all. Measuring it needs the short prompt to be runnable against an untrained
    model, which is what this override is for. The default is always the full teacher prompt.
    """
    cut = brief.get("cut") or {}
    if system is None:
        system = _SYSTEM.format(
            cards=", ".join(brief.get("allowed_card_names") or []) or "none",
            axis_label=brief.get("axis_label", "the target axis"),
            redundancy_rule=(_REDUNDANCY_OK if cut.get("redundancy_backed")
                             else _REDUNDANCY_FORBIDDEN),
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": _facts_block(brief)},
    ]


def _strip(text: str) -> str:
    """Drop the wrappers small models add: fences, headings, a leading label."""
    body = (text or "").strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[-1].rsplit("```", 1)[0]
    body = re.sub(r"^\s*(explanation|answer|reason)\s*[:\-]\s*", "", body, flags=re.I)
    # Inline emphasis: the prompt forbids markdown and the model emits it anyway (*Card Name*
    # on most drafts). Stripped rather than rejected — it is a formatting tic, not a claim,
    # and rejecting a faithful sentence over asterisks would starve the corpus.
    body = re.sub(r"(\*{1,2}|_{1,2})(?=\S)(.+?)(?<=\S)\1", r"\2", body)
    return " ".join(body.split()).strip()


def narrate(
    brief: dict,
    *,
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    attempts: int = 2,
    deck_card_names: set[str] | None = None,
    collect: list | None = None,
    system: str | None = None,
) -> str | None:
    """A gated narrative for one swap, or None if no attempt passed.

    None is a normal outcome, not an error: the caller keeps the deterministic `reason`. That
    fallback is exactly what lets the gate be strict - refusing a draft costs polish, while
    shipping an invented claim costs the thing this project cares about most.

    `collect`, when given, receives `(text, reasons)` for every attempt including rejected
    ones, which is how the corpus builder measures the gate's own firing rate rather than
    guessing at it.
    """
    from themer import _chat_completion  # deferred: heavy import, and unused by the gate tests

    messages = build_messages(brief, system)
    for attempt in range(max(1, attempts)):
        try:
            raw = _chat_completion(
                messages, model=model,
                # Re-rolling at the same temperature reproduces the same failure surprisingly
                # often; nudging it is cheaper than lengthening the prompt.
                temperature=temperature + 0.15 * attempt,
                num_predict=max_tokens, think=False,
            )
        except Exception as exc:                      # noqa: BLE001 - advice must never fail
            if collect is not None:
                collect.append((None, [f"backend error: {exc}"]))
            return None
        text = _strip(raw)
        reasons = check(text, brief, deck_card_names=deck_card_names)
        if collect is not None:
            collect.append((text, reasons))
        if not reasons:
            return text
    return None
