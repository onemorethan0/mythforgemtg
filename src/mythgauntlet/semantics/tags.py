"""Rung-1 Oracle-text heuristics -> EffectVector.

This is deliberately the same *category* of analysis every static power calculator performs —
kept honest by being (a) only a fallback rung and (b) explicit about its known blind spots:

  - Conditional taplands ("...unless you control...") are treated as untapped.
  - Modal spells contribute all detected modes (over-counts slightly).
  - Triggered draw ("Whenever...draw", "At the beginning of...draw") is modeled as a flat
    engine_draw per turn — trigger conditions are not evaluated.
  - "Each player draws" style symmetric effects count as our draw.

These blind spots define the priority queue for the CCM compiler (docs/CARD_SEMANTICS.md).
"""

from __future__ import annotations

import re

from mythgauntlet.model.card import Card
from mythgauntlet.semantics.model import EffectVector

_REMINDER_RE = re.compile(r"\([^)]*\)")
_WORD_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "x": 1,
}

_ENTERS_TAPPED_RE = re.compile(r"enters (?:the battlefield )?tapped")
_ADD_MANA_RE = re.compile(r"\badd ((?:\{[^}]+\}|,| or |and/or| )+)")
# "search THEIR library" is usually the OPPONENT ramping (Path to Exile, Assassin's
# Trophy) — crediting that to us made premium removal read as our own acceleration.
# A symmetric "each player searches their library" does ramp us, so it still counts.
_SEARCH_LAND_RE = re.compile(r"search your library for .{0,60}?land")
_SEARCH_LAND_SYMMETRIC_RE = re.compile(
    r"each player searches their library for .{0,60}?land"
)
# Worded mana amounts: "Add one mana of any color" (Arcane Signet, Birds of Paradise).
# The symbol regex below only ever matched "{G}"-style clauses, so every rock and dork
# that spells the amount out in words produced ZERO ramp — 416 cards, including EDHREC
# ranks 3, 17, 33 and 48. That is most of the mana acceleration in the format.
_ADD_WORDED_MANA_RE = re.compile(
    r"\badd (a|an|one|two|three|four|five|six|seven|x) (?:additional )?mana"
)
# Mana that is spent by ceasing to exist is not a mana SOURCE. Tier-0 models
# ramp_sources as a permanent that untaps every turn, so a ritual or a sacrifice-for-mana
# artifact modelled that way pays out every turn forever (Dark Ritual was worth three
# permanent sources). The burst is modelled separately as ritual_mana for Tier-2.
# The sacrifice must be the COST OF THE MANA ABILITY ITSELF ("{T}, Sacrifice this
# artifact: Add one mana"). Matching a sacrifice clause anywhere in the text instead
# caught Commander's Sphere, which sacrifices for a CARD and taps for mana repeatably.
_SACRIFICE_FOR_MANA_RE = re.compile(r"sacrifice (?:this|it)[^:.]*:[^.]*\badd\b")
_SEARCH_CARD_RE = re.compile(r"search (?:your|their) library for ([^.]*)")
_DRAW_RE = re.compile(r"draws? (\w+) (?:additional )?cards?")
_TRIGGER_RE = re.compile(r"^(?:whenever|when |at the beginning of|at the end of)")
# "If you would draw ..." REPLACES the draw; the sentence names a draw that never happens.
_DRAW_REPLACEMENT_RE = re.compile(r"\bif [^.]{0,30}?would draw\b")
# "if you drew two or more cards this turn" is a CONDITION on past draws, not a draw.
_DREW_CONDITION_RE = re.compile(r"\bdrew\b")
# Removal and board wipes, gated on WHAT the card actually acts on.
#
# `sim/tier2._apply_resolved` spends these on the opponent's creatures: `p.wipe` calls
# `_wipe_table`, and each point of `p.removal` kills the opponent's biggest creature. So the
# patterns have to mean "can remove a CREATURE from the battlefield" — the same mistake as
# the old `_CHEAT_RE`, which matched on the verb and ignored the object.
#
# Measured over the 34,179-card store: "destroy all"/"exile all" matched 632 cards but only
# 248 can touch a creature. Rest in Peace ("exile all graveyards"), Fracturing Gust
# (artifacts + enchantments), Identity Crisis (hand + graveyard), Vandalblast, Shatterstorm
# and Armageddon each fired a full symmetric CREATURE board wipe. On the removal side,
# "destroy target" matched 324 artifact-only, 125 land-only, 77 enchantment-only and 65
# graveyard-only cards — a Naturalize or a Stone Rain killed the opponent's biggest creature.
#
# `finditer`, not `search`: a modal card only needs ONE mode that hits creatures (Austere
# Command, Farewell), and the earlier modes name artifacts and enchantments.
_CREATURE_OBJECT_RE = re.compile(r"\bcreature|\bpermanent")
# A "creature CARD" is a card in a graveyard/library/hand; a "creature" is a permanent on
# the battlefield. Ghastly Conscription and Shadow of the Enemy exile all creature CARDS
# from a graveyard — no board impact at all, but they read like a wrath without this.
_ZONE_OBJECT_RE = re.compile(r"\bcards?\b")
_WIPE_ALL_RE = re.compile(r"(?:destroy|exile) all ([^.]{0,70})")
_REMOVAL_TARGET_RE = re.compile(r"(?:destroy|exile) target ([^.]{0,50})")
# "any target" reaches a creature; "target player" does not.
_DAMAGE_TARGET_RE = re.compile(r"deals? \d+ damage to (any target|target [^.,]{0,30})")
# Already creature-specific, so they need no object gate. The -N/-N form must reduce
# TOUGHNESS to remove anything: "all creatures get -2/-0" (Marsh Gas, Fyndhorn Pollen) is a
# power debuff that has never killed a creature.
_WIPE_RES = (
    re.compile(r"deals? \d+ damage to each creature"),
    re.compile(r"all creatures get [-−]\d+/[-−][1-9]"),
)


def _wipe_object(phrase: str) -> str:
    """The thing actually swept, with trailing prepositions trimmed.

    "destroy all Equipment attached to that creature" (Corrosive Ooze) and "destroy all
    Auras attached to ..." (Treefolk Mystic) sweep an artifact/enchantment; the creature
    named afterwards is only where it is attached, and leaked into the object otherwise.
    """
    return re.split(r"\battached to\b", phrase, maxsplit=1)[0]


def _is_board_wipe(text: str) -> bool:
    """True only when the sweep can remove CREATURES from the battlefield."""
    if any(r.search(text) for r in _WIPE_RES):
        return True
    for match in _WIPE_ALL_RE.finditer(text):
        obj = _wipe_object(match.group(1))
        if _CREATURE_OBJECT_RE.search(obj) and not _ZONE_OBJECT_RE.search(obj):
            return True
    return False


def _is_removal(text: str) -> bool:
    """True only when the targeted removal can hit a CREATURE."""
    for match in _REMOVAL_TARGET_RE.finditer(text):
        obj = _wipe_object(match.group(1))
        if _CREATURE_OBJECT_RE.search(obj) and not _ZONE_OBJECT_RE.search(obj):
            return True
    return any(
        m.group(1) == "any target" or _CREATURE_OBJECT_RE.search(m.group(1))
        for m in _DAMAGE_TARGET_RE.finditer(text)
    )
_COUNTER_RE = re.compile(r"counter target .{0,40}spell")
# A cheat-into-play enabler (Kaalia, Sneak Attack, Elvish Piper, Quicksilver Amulet).
# `sim/tier0.py` acts on this by pulling the BIGGEST STRANDED CREATURE out of hand and
# swinging with it the same turn, so the tag has to mean "can put an arbitrary creature
# from hand onto the battlefield" — nothing weaker.
#
# It used to be the bare substring "from your hand onto the battlefield", which says
# nothing about WHAT is put. Of the 164 cards matching it in the 34,179-card store, only
# 91 can put a creature. The other 73 were fabricating a goldfish clock out of nothing:
#   50 put a LAND — Sakura-Tribe Scout, Llanowar Scout, Growth Spiral, Spelunking,
#      Burgeoning, Firebrand Ranger. The old comment guarded against library ramp
#      ("...from your library...") but not hand-land ramp, which reads identically.
#    3 put a PLANESWALKER (Planebound Accomplice, The Disciple of Vess).
#   20 put an artifact / Aura / Equipment (Stoneforge Mystic, Copper Gnomes, Holy Avenger)
#      or put THIS card — a self-put is not an enabler at all: it cannot cheat in the fatty
#      stranded next to it, which is the only thing tier0 models.
#
# Known, deliberate under-count: a put restricted to a creature SUBTYPE reads as
# non-creature here ("a Vampire card" — Strefan; "a Construct, Robot, or Vehicle card" —
# Dr. Eggman). That is 2 cards against 73 fabrications, and it errs toward silence.
_HAND_PUT_RE = re.compile(r"put\s+([^.]{0,80}?)\s+from your hand onto the battlefield")
_CHEATABLE_OBJECT_RE = re.compile(r"\bcreature\b|\bpermanent\b")


def _cheats_creatures(text: str) -> bool:
    """True only when the card can put an arbitrary CREATURE from hand onto the battlefield."""
    return any(_CHEATABLE_OBJECT_RE.search(m.group(1)) for m in _HAND_PUT_RE.finditer(text))

# --- storm / spellslinger go-off engine (docs/SIMULATION.md; feeds the Ceiling axis) ---
_GRANTS_STORM_RE = re.compile(r"spells you cast have storm")  # Prismari class
# a spellslinger cast trigger = magecraft OR a noncreature/instant/sorcery cast (NOT creature casts,
# which are a different, damage-matters archetype -- e.g. Screamer-Killer, Rakdos Lord of Riots).
_CAST_TRIGGER_RE = re.compile(
    r"magecraft|whenever you cast [^.]{0,40}?(?:instant|sorcery|noncreature)")
# damage that can reach a PLAYER (a storm finisher must hit face -- "to target creature" doesn't).
_PLAYER_DAMAGE = (
    r"(?:any target|each opponent|target opponent|target player|each player|that player"
    r"|you and each opponent)")
_CAST_TREASURE_RE = re.compile(  # magecraft / cast-trigger that makes a Treasure (= mana)
    r"(?:magecraft|whenever you cast)[^.]{0,80}(?:create|put)[^.]{0,25}treasure")
_CAST_DAMAGE_RE = re.compile(rf"deals? (\d+) damage to {_PLAYER_DAMAGE}")  # Guttersnipe per cast
_SCALING_BURN_RE = re.compile(  # Fireball / Blaze / Comet Storm finisher (must reach a player)
    rf"deals? x damage (?:to {_PLAYER_DAMAGE}|divided[^.]{{0,60}}any (?:number of )?target)")
_COST_REDUCE_RE = re.compile(  # your instant/sorcery spells cost {N} less
    r"(?:instant and sorcery|noncreature|instant, sorcery)[^.]{0,25}spells?[^.]{0,25}"
    r"cost \{(\d+)\} less|spells you cast cost \{(\d+)\} less")
# one-shot overrun finisher (Overrun / Craterhoof / End-Raze). The "until end of turn" is the
# precision guard: it excludes STATIC anthem lords (Intangible Virtue, Diregraf Captain), which
# pump permanently and are NOT alpha-strike finishers.
# allow words between ("...gain trample and get +X/+X") -- real Craterhoof phrases it that way.
_OVERRUN_RE = re.compile(r"creatures you control [^.]{0,40}?get \+(\d+|x)/\+(?:\d+|x)")

# edhrec_rank runs ~1..~30000 (lower = more played). Rank-based prior, refined by L5 later.
_IMPACT_RANK_SCALE = 25_000
_IMPACT_DEFAULT = 0.25


def _clean_text(card: Card) -> str:
    return _REMINDER_RE.sub("", card.oracle_text or "").casefold()


def _activation_mana_cost(text: str) -> int:
    """Generic/coloured mana in the ability's ACTIVATION cost, i.e. before the colon.

    "{1}, {T}: Add {W}{U}" costs 1. {T}/{Q}/{E} are not mana and never count.
    """
    head = text.split(":", 1)[0]
    if len(head) > 60:            # not an activation cost, just a long sentence
        return 0
    total = 0
    for sym in re.findall(r"\{([^}]*)\}", head):
        s = sym.strip().lower()
        if s in ("t", "q", "e") or not s:
            continue
        total += int(s) if s.isdigit() else 1
    return total


def _ramp_from_add_clause(text: str) -> int:
    """NET mana added per activation of an 'Add ...' ability (rocks/dorks), crudely.

    Handles both spellings Magic uses: mana symbols ("Add {C}{C}" — Sol Ring) and words
    ("Add one mana of any color" — Arcane Signet, Birds of Paradise). Only the symbol
    form used to match, so every colour-fixing rock and most dorks read as zero ramp.

    NET, because tier0 spends `ramp_sources` as that many extra mana EVERY TURN. Counting
    the produced symbols and ignoring what the ability costs to activate made an Azorius
    Signet ("{1}, {T}: Add {W}{U}") worth +2 permanent mana when it nets +1, and — the
    common case — made a pure colour FILTER ("{1}, {T}: Add {B}": Abzan Devotee, Bog
    Initiate, Arcum's Astrolabe) worth a full mana per turn when it nets zero. 49 mana
    abilities in the compiled store cost mana; a casual deck runs a lot of them, and the
    inflation lands straight on Speed -> Ceiling -> bracket.
    """
    cost = _activation_mana_cost(text)
    m = _ADD_MANA_RE.search(text)
    if m:
        clause = m.group(1)
        if " or " in clause:  # "Add {G}, {U}, or {R}" produces one mana of a choice
            return max(0, 1 - cost)
        symbols = clause.count("{")
        if symbols:
            return max(0, min(3, symbols) - cost)
    worded = _ADD_WORDED_MANA_RE.search(text)
    if worded:
        return max(0, min(3, _WORD_NUMBERS.get(worded.group(1), 1)) - cost)
    return 0


def _draw_counts(text: str) -> tuple[int, int]:
    """(immediate draws on resolution, repeatable engine draws per turn).

    A card that says "draw" does not necessarily draw. Three contexts mention drawing while
    producing none, and counting them credited 85 of the 3,350 drawing cards with draw they
    do not have — the same VERB-without-CONTEXT mistake as the old `_CHEAT_RE`:

    * **Replacement** — "If you would draw a card, exile the top card face down instead"
      (Asmodeus the Archfiend) was scored **8 immediate draws**; it draws zero. Teferi's
      Ageless Insight scored 3 for a doubling replacement.
    * **Trigger condition** — in "Whenever you draw a card, put a +1/+1 counter", drawing is
      what FIRES the ability, not what it does (Vodalian Wave-Knight, Hoofprints of the Stag,
      Moonring Mirror). Only the effect clause, after the trigger's comma, may count.
    * **Retrospective condition** — "if you drew two or more cards this turn" describes a
      state, not an action.

    This feeds tier0 and the BRACKET, not just the CCM cross-check, so the error was rating
    decks on card advantage they never had.
    """
    immediate = 0
    engine = 0
    for sentence in re.split(r"[.\n]", text):
        s = sentence.strip()
        if not s:
            continue
        if _DRAW_REPLACEMENT_RE.search(s) or _DREW_CONDITION_RE.search(s):
            continue
        triggered = bool(_TRIGGER_RE.match(s))
        scan = s
        if triggered:
            # Count only the EFFECT clause. The trigger condition runs to the first comma;
            # "whenever you draw a card, put a counter" must contribute nothing.
            head, sep, tail = s.partition(",")
            if sep and _DRAW_RE.search(head):
                scan = tail
        for m in _DRAW_RE.finditer(scan):
            window = scan[max(0, m.start() - 30) : m.start()]
            if "opponent" in window:
                continue
            n = _WORD_NUMBERS.get(m.group(1), 0)
            if triggered:
                engine += min(n, 2)  # cap: triggers rarely fire more than ~2x/turn in goldfish
            else:
                immediate += n
    return immediate, engine


def _cast_payoffs(text: str) -> tuple[int, int]:
    """Per-cast burn to a player, split by whether STORM COPIES also trigger it:
    (magecraft_damage, cast_damage). Magecraft fires on cast OR copy (rules keyword), so storm
    amplifies it; a plain 'whenever you cast an instant/sorcery' (Guttersnipe) fires ONLY on the
    cast, not the copies. Requiring the trigger + player-reaching damage in one sentence avoids
    counting a creature-cast pinger or a 'deal N to target creature' as face burn."""
    magecraft = cast_only = 0
    for sentence in re.split(r"[.\n]", text):
        if not _CAST_TRIGGER_RE.search(sentence):
            continue
        m = _CAST_DAMAGE_RE.search(sentence)
        if not m:
            continue
        if "magecraft" in sentence:
            magecraft += int(m.group(1))
        else:
            cast_only += int(m.group(1))
    return magecraft, cast_only


def _overrun(text: str) -> tuple[int, bool]:
    """A one-shot team pump finisher: '(pump, scales)'. Requires 'until end of turn' in the SAME
    sentence so static anthem lords (permanent +1/+1) don't read as an alpha-strike finisher."""
    for sentence in re.split(r"[.\n]", text):
        if "until end of turn" not in sentence:
            continue
        m = _OVERRUN_RE.search(sentence)
        if m:
            g = m.group(1)
            return (0, True) if g == "x" else (int(g), False)
    return 0, False


def analyze(card: Card) -> EffectVector:
    """Compute the rung-1 EffectVector for a card (front face)."""
    text = _clean_text(card)

    enters_tapped = bool(
        card.is_land and _ENTERS_TAPPED_RE.search(text) and "unless" not in text
    )

    ramp_sources = 0
    fetches_land = False
    if not card.is_land:
        # ramp_sources is a PERMANENT that untaps each turn, so only repeatable mana
        # counts. One-shot mana (a ritual, or an artifact that sacrifices itself for
        # mana) would otherwise pay out every turn forever; Tier-2 models that burst as
        # ritual_mana instead.
        one_shot = (
            card.has_type("Instant")
            or card.has_type("Sorcery")
            or bool(_SACRIFICE_FOR_MANA_RE.search(text))
        )
        if not one_shot:
            ramp_sources = _ramp_from_add_clause(text)
        if ((_SEARCH_LAND_RE.search(text) or _SEARCH_LAND_SYMMETRIC_RE.search(text))
                and "battlefield" in text):
            fetches_land = True
            ramp_sources = max(ramp_sources, 1)

    tutor = False
    m = _SEARCH_CARD_RE.search(text)
    if m and "land" not in m.group(1):
        tutor = True

    removal = 1 if _is_removal(text) else 0
    board_wipe = _is_board_wipe(text)
    counterspell = bool(_COUNTER_RE.search(text))
    cheats_creatures = _cheats_creatures(text)
    draw_cards, engine_draw = _draw_counts(text)

    # storm / spellslinger engine facts
    grants_storm = bool(_GRANTS_STORM_RE.search(text))
    mana_on_cast = 1 if _CAST_TREASURE_RE.search(text) else 0
    magecraft_damage, cast_damage = _cast_payoffs(text)
    scaling_burn = bool(_SCALING_BURN_RE.search(text))
    m_cr = _COST_REDUCE_RE.search(text)
    spell_cost_reduction = int(next((g for g in m_cr.groups() if g), 0)) if m_cr else 0
    ritual_mana = 0
    if card.has_type("Instant") or card.has_type("Sorcery"):
        m_add = _ADD_MANA_RE.search(text)
        if m_add:  # a ritual: net mana = mana added (uncapped) minus the spell's cost
            added = 1 if " or " in m_add.group(1) else m_add.group(1).count("{")
            ritual_mana = max(0, added - card.mana_value)
    overrun_pump, overrun_scales = _overrun(text)

    if card.edhrec_rank is not None:
        impact = max(0.0, min(1.0, 1.0 - card.edhrec_rank / _IMPACT_RANK_SCALE))
    else:
        impact = _IMPACT_DEFAULT

    return EffectVector(
        ramp_sources=ramp_sources,
        fetches_land=fetches_land,
        draw_cards=draw_cards,
        engine_draw=engine_draw,
        tutor=tutor,
        removal=removal,
        board_wipe=board_wipe,
        counterspell=counterspell,
        enters_tapped=enters_tapped,
        cheats_creatures=cheats_creatures,
        grants_storm=grants_storm,
        mana_on_cast=mana_on_cast,
        magecraft_damage=magecraft_damage,
        cast_damage=cast_damage,
        scaling_burn=scaling_burn,
        spell_cost_reduction=spell_cost_reduction,
        ritual_mana=ritual_mana,
        overrun_pump=overrun_pump,
        overrun_scales=overrun_scales,
        impact=impact,
    )
