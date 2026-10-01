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
from dataclasses import dataclass

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
#
# THE SECOND PASS (2026-09-30) gated the other half of the same sentence. The first pass
# gated the NOUN; it still read the verb's own quantifier literally ("destroy target",
# "destroy all", "deals \d+ damage") and never asked WHOSE creature it was. Measured over
# the 34,563-card store: removal 2,114 -> 3,460 (+1,405 / -59), board_wipe 466 -> 687
# (+229 / -8), counterspell 433 -> 444; 1,708 cards changed. Two opposite errors:
#   * FALSE POSITIVE — own permanents and flicker. Ephemerate ("exile target creature you
#     control, then return it") and Flicker of Fate were each killing the opponent's
#     biggest creature in tier2 and counting as an answer on the Interaction axis.
#   * MISSED — every removal shape the regexes were not literally spelled for: X / "equal
#     to" / divided damage (Electrodominance, Shatterskull Smashing, Chainweb Aracnir),
#     -N/-N and -X/-X (Toxic Deluge, Collective Brutality, Bloodtithe Harvester), bounce and
#     library tuck (Condemn, Chaos Warp, Chain of Vapor, Otawara), "up to one target"
#     (Spider Food) and "destroy each" (Culling Sun), and exiling a spell (Mindbreak Trap).
#   The old rule also had its own object false positives this pass removes: "destroy target
#   NONcreature permanent" (Bramblecrush, Terastodon) and "creature" appearing only in a
#   count ("damage to target opponent for each creature card" -- Lotleth Giant).
# The Interaction axis moved on 735 of 975 corpus decks (corpus median 64.3 -> 80.4); the
# biggest drops are blink decks whose Ephemerate / Restoration Angel read as removal.
#
# Bounce and tuck count, as removing a creature FROM THE BATTLEFIELD, which is what this
# contract has always said. On the rung-1 path tier2 then spends a bounce as a kill -- an
# over-credit, stated rather than hidden, but small: 2,266 cards have no CCM and only 13
# of the changed cards are bounce/tuck-only among them. With a CCM the interpreter
# executes the real `return_to_hand`. Artifact/enchantment/planeswalker-only
# answers (Fracture, Return to Nature, Masked Vandal) stay OUT, deliberately: `removal`
# is spent as a creature kill, which is exactly the Naturalize defect fixed above.
#
# `mentor/removal.py` (branch mentor-adhoc-b2) is a fuller clause-by-clause parser of the
# same text. It imports THIS module, so it cannot be reused from here without first
# moving its parser below `semantics/`; until then these are two derivations of one rule
# and `tests/engine/test_tags.py` pins this side to the same verified oracle texts.
_CREATURE_OBJECT_RE = re.compile(r"\bcreature|\bpermanent")
# A "creature CARD" is a card in a graveyard/library/hand; a "creature" is a permanent on
# the battlefield. Ghastly Conscription and Shadow of the Enemy exile all creature CARDS
# from a graveyard — no board impact at all, but they read like a wrath without this.
_ZONE_OBJECT_RE = re.compile(r"\bcards?\b")
# What may sit between a verb and "target": "up to one target", "any number of target",
# "another target", "two target". Missing these is how Spider Food read as nothing.
_LEAD = (r"(?:(?:up to (?:one|two|three|four|five|x|\d+)|any number of|one or two"
         r"|one, two, or three|one|two|three|four|x|\d+) )?(?:another |other )?")
_WIPE_ALL_RE = re.compile(r"(?:destroy|exile) (?:all|each) ([^.]{0,70})")
_REMOVAL_TARGET_RE = re.compile(rf"(?:destroy|exile) {_LEAD}target ([^.]{{0,60}})")
# Damage of ANY amount — a digit, X, "twice X", "that much", "damage equal to its power"
# (the bite) — into a targeted object. "any target" / "one or two targets" reach a
# creature; "target player" does not.
# "would deal damage to any target ... prevent that damage" (Circle of Despair, Martyr's
# Cause) is a prevention shield, so a damage clause preceded by "would" is never removal.
_DAMAGE_TARGET_RE = re.compile(
    r"(?<!would )\bdeals? (?:[^.]{0,30}? )?damage(?: equal to [^.]{0,80}?)?"
    r"(?: divided (?:as you choose|evenly)[^.]{0,20}?)? (?:to|among) "
    rf"(?:each of )?{_LEAD}(any target|targets\b|target [^.]{{0,60}})"
)
_DAMAGE_EACH_RE = re.compile(
    r"(?<!would )\bdeals? (?:[^.]{0,30}? )?damage(?: equal to [^.]{0,80}?)? to each (?:other )?"
    r"(creatures?\b[^.]{0,40})"
)
# -N/-N: the TOUGHNESS has to fall to remove anything. "all creatures get -2/-0" (Marsh Gas,
# Fyndhorn Pollen) is a power debuff that has never killed a creature.
_MINUS = r"gets? [+\-−]?[\dx]+/[\-−](?:[1-9]|x)"
_MINUS_TARGET_RE = re.compile(rf"\b{_LEAD}target ([^.]{{0,60}}?) {_MINUS}")
_MINUS_ALL_RE = re.compile(
    # "all/each" must govern the creature noun directly (<=3 modifier words, no comma):
    # "at the beginning of EACH upkeep, this creature ... gets -1/-1" is not a sweep.
    rf"(?:\b(?:all|each) ((?:[\w'-]+ ){{0,3}}?creatures?\b[^.]{{0,40}}?)"
    rf"|^(creatures [^.]{{0,40}}?)|[.:]\s*(creatures [^.]{{0,40}}?)) {_MINUS}",
    re.MULTILINE,
)
_OWNERS = r"(?:its|their) owners?['’]?s?['’]?"
_BOUNCE_RE = re.compile(
    rf"\breturn ({_LEAD}(?:target|all|each)\b[^.]{{0,80}}?) to {_OWNERS} hands?\b"
)
_TUCK_RE = re.compile(
    rf"\bput ({_LEAD}target\b[^.]{{0,60}}?) (?:on (?:the )?(?:top|bottom) of|into) "
    rf"{_OWNERS} librar(?:y|ies)"
)
_SHUFFLE_RE = re.compile(
    rf"\bthe owner of ({_LEAD}target\b[^.]{{0,40}}?) shuffles (?:it|them) into their library"
)
# Two verbs that remove a creature without saying destroy/exile/damage (2026-10-01).
# A fight is mutual damage into "target creature you don't control" (Prey Upon); an edict
# makes ANOTHER player sacrifice (Diabolic Edict, Fleshbag Marauder, Grave Pact). A
# sacrifice YOU make ("sacrifice a creature:") is a cost and never matches: the subject
# has to be a player. "sacrifices ALL ..." is a sweep (Tragic Arrogance).
_FIGHT_RE = re.compile(rf"\bfights? ({_LEAD}target\b[^.(]{{0,60}})")
_EDICT_RE = re.compile(
    r"\b(?:target player|target opponent|each opponent|each other player|each player"
    r"|that player|defending player) sacrifices ([^.]{0,70})"
)
# A return that UNDOES the exile: Ephemerate's "then return it", Flickerwisp's "return
# that card ... at the beginning of the next end step". Two returns are NOT this and keep
# the card as removal: the O-Ring/Fiend Hunter return that waits for the SOURCE to leave
# the battlefield, and a conditional one (Parting Gust's "if the gift wasn't promised").
_FLICKER_RETURN_RE = re.compile(
    r"\breturn (?:it|that card|that creature|that permanent|them|those cards"
    r"|the exiled cards?)\b[^.]*\bto the battlefield"
)
# The object phrase stops where a relative clause begins, so "you control" inside "that's
# attacking you or a planeswalker you control" (Soul Snare) is not read as an own-gate.
_CLAUSE_START_RE = re.compile(
    r"\b(?:with|without|that|that's|which|whose|where|if|unless|until|and|then|except)\b"
)
_OWN_OBJECT_RE = re.compile(r"\byou (?:control|own)\b")


def _wipe_object(phrase: str) -> str:
    """The thing actually swept, with trailing prepositions trimmed.

    "destroy all Equipment attached to that creature" (Corrosive Ooze) and "destroy all
    Auras attached to ..." (Treefolk Mystic) sweep an artifact/enchantment; the creature
    named afterwards is only where it is attached, and leaked into the object otherwise.
    """
    return re.split(r"\battached to\b", phrase, maxsplit=1)[0]


def _hits_creature(obj: str) -> bool:
    """The object can be an opposing creature on the battlefield: it names a creature or
    permanent, not a CARD in some zone, and is not restricted to the caster's own."""
    # A count expression is not part of the object: "target tapped creature for each CARD
    # you've drawn" (Niko Aris) must not trip the zone gate.
    obj = re.split(r"\bfor each\b|,? where\b|\bequal to\b", _wipe_object(obj), maxsplit=1)[0]
    if not _CREATURE_OBJECT_RE.search(obj):
        return False
    # Zone and own gates read only the HEAD noun phrase: "destroy target permanent and
    # return target ... permanent CARD" (Ragnarok) is not a zone object, and "except for
    # creatures you control" (Flame Sweep) is not an own-only object.
    head = _CLAUSE_START_RE.split(obj, maxsplit=1)[0]
    if _ZONE_OBJECT_RE.search(head) or _OWN_OBJECT_RE.search(head):
        return False
    # "noncreature, nonland permanents" (Filter Out) is the one "permanent" that cannot be
    # a creature.
    return not (re.search(r"\bnoncreature\b", head) and not re.search(r"\bcreatures?\b", head))


def _flickers(text: str, at: int) -> bool:
    """The exile at `at` comes straight back: an unconditional return later in the SAME
    paragraph that is not waiting for the source to leave the battlefield."""
    start = text.rfind("\n", 0, at) + 1
    end = text.find("\n", at)
    para = text[start:] if end == -1 else text[start:end]
    for sentence in re.split(r"(?<=\.)\s+", para[at - start:]):
        if not _FLICKER_RETURN_RE.search(sentence):
            continue
        if "leaves the battlefield" in sentence or re.search(r"\b(?:if|unless)\b", sentence):
            continue
        return True
    return False


@dataclass(frozen=True)
class InteractionModes:
    """HOW a card interacts, by mode. `analyze` collapses this to removal/board_wipe/
    counterspell; `ccm.cross_check` reads the modes so its omission gate can ask for the op
    that actually expresses each one (a bounce is `return_to_hand`, a -N/-N is a negative
    `pump`) instead of demanding destroy/exile/deal_damage of every answer."""

    spot: frozenset[str] = frozenset()     # destroy|exile|damage|minus|bounce|tuck|fight|edict
    wipe: frozenset[str] = frozenset()     # destroy|exile|damage|minus|static_minus|bounce|edict
    counter: frozenset[str] = frozenset()  # counter | exile


def interaction_modes(text: str) -> InteractionModes:
    """Clause modes over CLEANED text (`_clean_text`: casefolded, reminder text stripped)."""
    # Quoted text is KEPT, unlike `_draw_counts`: a granted "{T}: deals 1 damage to any
    # target" (Hermetic Study, Shuriken, Bombardment's Missiles) is interaction the
    # controller really has; stripping it lost 30+ such cards in the first draft.
    spot: set[str] = set()
    wipe: set[str] = set()
    counter: set[str] = set()

    for m in _REMOVAL_TARGET_RE.finditer(text):
        verb = "exile" if text.startswith("exile", m.start()) else "destroy"
        if _hits_creature(m.group(1)) and not (verb == "exile" and _flickers(text, m.start())):
            spot.add(verb)
    for m in _WIPE_ALL_RE.finditer(text):
        verb = "exile" if text.startswith("exile", m.start()) else "destroy"
        if _hits_creature(m.group(1)) and not (verb == "exile" and _flickers(text, m.start())):
            # (a mass flicker -- Golden Argosy's "exile each creature that crewed it ...
            # return them" -- is no more a sweep than Ephemerate is removal)
            # Council's Judgment exiles "each permanent with the most votes": one answer.
            (spot if "most votes" in m.group(1) else wipe).add(verb)
    for m in _DAMAGE_TARGET_RE.finditer(text):
        obj = m.group(1)
        if obj in ("any target", "targets") or _hits_creature(obj):
            spot.add("damage")
    for m in _DAMAGE_EACH_RE.finditer(text):
        if _hits_creature(m.group(1)):
            wipe.add("damage")
    for m in _MINUS_TARGET_RE.finditer(text):
        if re.search(r"\bcreatures?\b", m.group(1)) and _hits_creature(m.group(1)):
            spot.add("minus")
    for m in _MINUS_ALL_RE.finditer(text):
        if _hits_creature(next(g for g in m.groups() if g)):
            # A static -N/-N (Elesh Norn, Curse of Death's Hold) has no "until end of
            # turn"; the CCM schema stores statics as notes only, so ccm.cross_check must
            # not demand an op for it.
            line_end = text.find("\n", m.end())
            rest = text[m.end(): None if line_end == -1 else line_end].split(".")[0]
            wipe.add("minus" if "until end of turn" in rest else "static_minus")
    for m in _BOUNCE_RE.finditer(text):
        obj = m.group(1)
        mass = re.match(rf"{_LEAD}(?:all|each)\b", obj)
        if _hits_creature(obj):
            (wipe if mass else spot).add("bounce")
    for rx in (_TUCK_RE, _SHUFFLE_RE):
        for m in rx.finditer(text):
            if _hits_creature(m.group(1)):
                spot.add("tuck")
    for m in _FIGHT_RE.finditer(text):
        if _hits_creature(m.group(1)):
            spot.add("fight")
    for m in _EDICT_RE.finditer(text):
        obj = m.group(1)
        # A PUNISHER is not an answer: "unless that player sacrifices a creature"
        # (Acererak, Indulgent Tormentor, Ogre Marauder) lets the opponent choose the
        # other outcome.
        if text[max(0, m.start() - 7):m.start()] == "unless ":
            continue
        if _hits_creature(obj):
            # Liliana of the Veil's -6 sacrifices one PILE, not the board.
            mass = obj.startswith("all ") and "pile" not in obj
            (wipe if mass else spot).add("edict")

    if _COUNTER_RE.search(text):
        counter.add("counter")
    if _EXILE_SPELL_RE.search(text):
        counter.add("exile")
    return InteractionModes(frozenset(spot), frozenset(wipe), frozenset(counter))


# "counter up to one target spell" missed the old verb-adjacent `counter target`.
_COUNTER_RE = re.compile(rf"counter {_LEAD}target .{{0,40}}spell")
# Exiling a spell on the stack IS countering it (Mindbreak Trap: "Exile any number of
# target spells"). Word-limited so it never reaches past the object into another noun.
_EXILE_SPELL_RE = re.compile(rf"\bexile {_LEAD}target (?:[a-z]+ ){{0,3}}?spells?\b")
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
# THIS spell costs {N} less for each creature already in play (Blasphemous Act / Vanquish
# the Horde class) -- a SEPARATE mechanism from _COST_REDUCE_RE above (that one discounts
# OTHER spells; this one discounts itself). Left unmodeled, sim/tier0.py's castability
# check gates on the full PRINTED mana value (9 for Blasphemous Act), so a card that is
# routinely cast for 2-4 mana in a real game never becomes castable in a goldfish run that
# rarely reaches turn 9 -- it sits dead in every simulated hand, which is a wrong model of
# the card, not a judgement that the deck has too many wipes. "on the battlefield" (Vanquish
# the Horde) counts every player's creatures in a real pod; tier0 has no opponent, so using
# the caster's own live creature count for it is a conservative UNDER-count, not a fabrication.
_SELF_COST_REDUCE_CREATURES_RE = re.compile(
    r"costs? \{(\d+)\} less to cast for each creature\b[^.]{0,20}(?:on the battlefield|you control)")
# "Affinity for creatures" is a KEYWORD whose {1}-less-per-creature rule lives only in its
# reminder text -- which `_clean_text` strips as parenthetical before any regex above ever
# sees it. The keyword itself is a fixed, always-{1} ability (no printed variant reduces by
# more), so recognising the keyword name alone is exact, not a guess.
_AFFINITY_CREATURES_RE = re.compile(r"affinity for creatures")
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

    A fourth context has the same shape: quoted text GRANTING another object an ability
    ('target creature gains "When this creature dies, draw two cards."' — a Saga's
    payoff chapter). The granting sentence is not itself phrased as a trigger ("whenever
    ..."), so the trigger-condition guard above never sees it, and the quoted clause
    reads as this card's own immediate draw — found live 2026-09-16, Fall of Gil-galad's
    chapter III scored 2 immediate draws it never has (the draw belongs to whatever
    creature that ability gets granted to, on ITS death, later). A quoted span in oracle
    text is always the verbatim text of an ability being NAMED or GRANTED, never part of
    the enclosing sentence's own direct action — stripped before scanning, same
    reasoning as the parenthetical reminder text `_clean_text` already strips upstream.
    """
    text = re.sub(r'"[^"]*"', "", text)
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

    modes = interaction_modes(text)
    removal = 1 if modes.spot else 0
    board_wipe = bool(modes.wipe)
    counterspell = bool(modes.counter)
    cheats_creatures = _cheats_creatures(text)
    draw_cards, engine_draw = _draw_counts(text)

    # storm / spellslinger engine facts
    grants_storm = bool(_GRANTS_STORM_RE.search(text))
    mana_on_cast = 1 if _CAST_TREASURE_RE.search(text) else 0
    magecraft_damage, cast_damage = _cast_payoffs(text)
    scaling_burn = bool(_SCALING_BURN_RE.search(text))
    m_cr = _COST_REDUCE_RE.search(text)
    spell_cost_reduction = int(next((g for g in m_cr.groups() if g), 0)) if m_cr else 0
    m_self_cr = _SELF_COST_REDUCE_CREATURES_RE.search(text)
    self_reduction_per_creature = (
        int(m_self_cr.group(1)) if m_self_cr
        else 1 if _AFFINITY_CREATURES_RE.search(text)
        else 0
    )
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
        self_reduction_per_creature=self_reduction_per_creature,
        ritual_mana=ritual_mana,
        overrun_pump=overrun_pump,
        overrun_scales=overrun_scales,
        impact=impact,
    )
