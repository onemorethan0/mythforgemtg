"""Rung-1 Oracle-text heuristics -> EffectVector.

This is deliberately the same *category* of analysis every static power calculator performs —
kept honest by being (a) only a fallback rung and (b) explicit about its known blind spots:

  - Conditional taplands ("...unless you control...") are treated as untapped.
  - Modal spells contribute all detected modes (over-counts slightly).
  - Triggered draw ("Whenever...draw", "At the beginning of...draw") and a permanent's
    repeatable activated draw ("{T}: Draw a card") are modeled as a flat engine_draw per
    turn — trigger conditions and activation costs are not evaluated.
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
#
# A land search does not always say "land": "search your library for a Forest card" (Three
# Visits, Skyshroud Claim, Kor Cartographer) and "up to two basic Plains cards" (Archaeomancer's
# Map) name a basic land TYPE. Both regexes read only the word "land", so 83 store cards
# fetched no land (Three Visits was no ramp at all) and the to-hand ones read as TUTORS — the
# Deck Mentor counted Archaeomancer's Map as a tutor. A basic type counts as "land" in both.
_LAND_WORD = r"(?:land|\b(?:plains|island|swamp|mountain|forest|wastes)\b)"
_SEARCH_LAND_RE = re.compile(rf"search your library for .{{0,60}}?{_LAND_WORD}")
_SEARCH_LAND_SYMMETRIC_RE = re.compile(
    rf"each player searches their library for .{{0,60}}?{_LAND_WORD}"
)
_LAND_OBJECT_RE = re.compile(_LAND_WORD)
# Where a searched land goes is the FIRST destination named after the search. Reading
# "battlefield" anywhere in the text made Archaeomancer's Map (to hand; a separate ability
# says "onto the battlefield") land-fetch ramp; reading only the search's own sentence lost
# Verdant Mastery's two-sentence "search ... and reveal them. Put one of them onto the
# battlefield". A graveyard is not a destination here: Elemental Teachings' opponent bins two
# and the rest still enter the battlefield.
_LAND_DESTINATION_RE = re.compile(
    r"onto the battlefield|into (?:your|their) hands?|on top\b|\bexile (?:it|them|that card)")


def _land_reaches_battlefield(text: str, at: int) -> bool:
    m = _LAND_DESTINATION_RE.search(text, at)
    return m is not None and m.group(0) == "onto the battlefield"
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
# An ability word or flavor word in front of a trigger ("Landfall — Whenever ...",
# "Martyrdom — When this creature dies, ...", "Descend 8 — Whenever ..."), a Siege's mode
# bullet ("• Khans — At the beginning of ..."), an Unfinity sticker cost, chained before an
# ability word ("{TK}{TK}{TK} — Magecraft — Whenever ..."). Stripped only when a trigger
# follows. A Saga's chapter numeral ("III — Whenever you cast a spell ... this turn") is NOT
# stripped: the chapter fires once, and the trigger inside it lasts only that turn.
_ABILITY_WORD_PREFIX_RE = re.compile(
    r"^(?:• )?(?![ivx]+(?:, [ivx]+)* — )(?:[^—:.•]{1,40} — ){1,2}"
    r"(?=whenever|when |at the beginning of|at the end of)"
)
# A "when" trigger whose EVENT happens once in the object's life: Solemn Simulacrum's death
# draw, Mulldrifter's ETB draw. Applied to the trigger condition only (text before the
# first comma). A positive list on purpose — "when" alone is not proof of one-shot (The
# Belligerent and Useless Island's "when ... deal combat damage" recurs every combat), and an
# event that does not match keeps the old engine reading rather than guessing. A condition
# that also says "whenever" (Up the Beanstalk: "when this enters and whenever you cast")
# recurs and is excluded. "When you cast THAT/a spell" (Yume) recurs too; only the card's
# own cast trigger ("when you cast this spell", "when you cast Taught by Serra") is one-shot.
#
# Counter thresholds ("when the tenth +1/+1 counter is put on Shang-Chi", Midnight Clock's
# twelfth hour) fire once. Room doors unlock once.
_ONE_SHOT_TRIGGER_RE = re.compile(
    r"^when (?!.*\bwhenever\b).*\b(?:enters|dies|is put into a graveyard from the battlefield"
    r"|leaves the battlefield|is exiled|is turned face up|becomes level|exploits|specializes"
    r"|unlock this door|counter is put on|loses the game|wins the fight|as evidence)\b"
    r"|^when you cast (?!that\b|a\b|an\b|another\b|your\b)"
    r"|^when you sacrifice this\b"
    r"|^when this spell resolves\b"
    # Khârn the Betrayer's "when you lose control of", Plundered Statue's "is put into a
    # graveyard from anywhere": both stood behind a flavor word until the prefix was read.
    r"|^when you lose control of\b"
    r"|^when (?!.*\bwhenever\b).*\bis put into a graveyard from anywhere\b"
)
# A reflexive trigger ("When you do, draw a card") recurs exactly as often as the sentence
# it hangs off: once under Selfcraft Mechan's ETB, every attack under Watchful Naga's exert.
_REFLEXIVE_TRIGGER_RE = re.compile(r"^when (?:you|they|that player) do(?:es)?\b")
# Activated abilities: "<cost>: <effect>" on one line. The cost may sit behind an ability
# word ("Max speed — {1}, ...", "Exhaust — {2}{U}") or a Spacecraft station threshold
# ("2+ | {1}, {T}, ..."). A head without a mana/tap symbol must open with a cost verb, so
# a stray colon in some other sentence is never read as an activation.
_ACTIVATION_PREFIX_RE = re.compile(r"^(?:\d+\+ \| |[^:—]{1,40} — )")
_LOYALTY_COST_RE = re.compile(r"^([+−-]?)(?:\d+|x)$")
_COST_VERB_RE = re.compile(
    r"^(?:sacrifice|discard|exile|tap|tapped|untap|pay|remove|return|put|reveal|uninstall"
    r"|collect|forage|blight|behold)\b"
)
# A cost that consumes THE CARD ITSELF can be paid once: Sunbeam Spellbomb and Courier's
# Briefcase sacrifice themselves, Channel discards itself, a graveyard ability exiles it,
# Attunement returns itself to hand. Sacrificing or exiling OTHER things (a Food, a Treasure,
# "another creature", "two cards from your graveyard") is a renewable resource and stays
# repeatable. `{name}` is filled with the card's own names; old-wording legends still
# say "Sacrifice Stone of Erech" rather than "this artifact".
_SELF_COST_TEMPLATE = (
    r"\b(?:sacrifice|exile|discard|return|shuffle|put) (?:this\b|it\b|{name})"
    r"|\band (?:sacrifice|exile) it\b"
)
# The same, in the EFFECT: Sensei's Divining Top's "draw a card, then put this artifact on top
# of its owner's library" draws the Top itself back — card-neutral and never repeatable;
# Sorcerer's Strongbox sacrifices itself to draw. Only "this"/the card's name here: an
# effect's "put it onto the battlefield" (Thrasios) is some other card.
_SELF_EFFECT_TEMPLATE = r"\b(?:sacrifice|exile|return|shuffle|put) (?:this\b|{name})"
# A TRIGGER that sacrifices the card on its way to the draw fires once: Impaler Shrike's
# "Whenever this creature deals combat damage to a player, you may sacrifice it. If you do,
# draw three cards", Charitable Levy's "... sacrifice it. If you do, draw a card". In a
# trigger, "it" before the draw is the trigger's own object; only a self-sacrifice AT OR
# BEFORE the draw counts — Tellah's and Rent Is Due's sacrifice afterwards end an engine
# that has already been drawing.
_SACRIFICE_IT_RE = re.compile(r"\bsacrifice it\b")
# Exhaust and "activate only once" (but not "only once each turn") cap the ability at one
# use per game; an ability activated from the hand (Forecast) never sits on the battlefield.
_ONCE_ONLY_COST_RE = re.compile(r"^exhaust — |\bfrom your hand\b")
_ONCE_ONLY_LIMIT_RE = re.compile(r"\bactivate only once\b(?! each turn)")
# The draw's SUBJECT is another player, not us: "each opponent draws", "target opponent may
# draw", "each opponent who didn't draws", "each other player draws" (Words of Wisdom,
# Deadpool). "Target opponent may have you draw" (Combustible Gearhulk) is the opponent's
# choice — a punisher, not card advantage we can plan on. Judged from the words right before
# the verb: the old test, the word "opponent" anywhere in the 30 characters before, threw
# away OUR draw whenever the trigger condition named an opponent — "Whenever this creature
# deals combat damage to an opponent, draw a card" (Thieving Magpie, Vedalken Heretic,
# Wavebreak Hippocamp's "each opponent's turn, draw a card").
_OTHER_PLAYER_SUBJECT_RE = re.compile(
    r"\b(?:opponents? (?:may |each |who [^,]*|may have you )?|each other player (?:may )?)$")
# ... but "you and target opponent each draw a card" (Farsight Adept, Teyo) draws us one too.
_SHARED_WITH_OPPONENT_RE = re.compile(r"\byou and [^,]*opponents? each $")
# An anaphoric subject ("that player draws", "they draw") — whose draw it is depends on what
# it points back to, so it is resolved only in two positive shapes, see `_draw_counts`.
_ANAPHOR_SUBJECT_RE = re.compile(r"\b(?:that player|they) (?:may )?$")
_OPPONENT_SCOPE_RE = re.compile(r"\bopponent|\beach other player|\banother player")
# Combat damage to "a player" lands on an opponent (Miss Highwater's "deals combat damage to a
# player who doesn't have a contract counter, they may discard their hand. If they do, they
# draw seven cards" — the damaged opponent draws seven). Used only to scope a follow-on
# sentence's anaphor, see `_draw_counts`.
_COMBAT_DAMAGE_TO_PLAYER_RE = re.compile(r"\bcombat damage to a player\b")
# The trigger's effect opens on the anaphor itself: ", that player discards", ", they may".
_ANAPHOR_EFFECT_RE = re.compile(r", (?:that player|the player|they)\b")
# "If you don't draw a card this way" (Trade Route Envoy) names a draw that did not happen.
_NEGATED_DRAW_RE = re.compile(r"\b(?:don't|didn't|doesn't|do not|did not|does not) $")
_CHOSEN_OPPONENT_RE = re.compile(r"\b(?:choose|target) (?:target )?opponent\b")
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
# A kill whose object is an ANAPHOR for an earlier target: Dispatch ("Tap target creature.
# Metalcraft — If you control three or more artifacts, exile that creature"), Kellan's
# Lightblades ("... if this spell was bargained, destroy that creature instead"). The
# verb-adjacent patterns above need "destroy/exile TARGET ..." and never saw these. The anaphor
# is resolved, not trusted: "destroy that creature" is mostly combat text (Cockatrice, Stinkweed
# Imp: "whenever this creature blocks ..., destroy that creature") or a drawback on your own
# creature (Mogg Cannon's "target creature YOU CONTROL ... destroy that creature at the
# beginning of the next end step"), so the kill counts only when it points back to a TARGET whose
# object passes `_hits_creature` — on the same line, or on the line before when this line is an
# ability-word rider ("Metalcraft — If ...") that has no target of its own. 95 store cards say
# "destroy/exile that creature/permanent"; see tests/engine/test_role_coverage.py.
_ANAPHOR_KILL_RE = re.compile(r"\b(destroy|exile) (?:that|the) (?:creature|permanent)\b")
_TARGET_OBJECT_RE = re.compile(r"\btarget ([^.]{0,60})")
_RIDER_LINE_RE = re.compile(r"^(?:• )?[^—:.\n]{1,40} — (?:if|as long as)\b")
# Answers to a NONCREATURE permanent (Crush Contraband, Naturalize, Vandalblast, Return to
# Nature). Deliberately NOT `removal`: tier2 spends each point of `removal` killing the
# opponent's biggest creature, which is the Naturalize defect the first gating pass fixed. But
# a player counts these as interaction, and with no role at all they vanished from the Deck
# Mentor's role table ("removal: 1 card" for a deck running Crush Contraband). They get their
# own `noncreature_removal` role instead, read by nothing in the simulator. Land destruction
# (Stone Rain) is NOT included — answering a land is not what a Commander player means by an
# artifact/enchantment answer, and it would put Armageddon-class cards in the role.
_NONCREATURE_OBJECT_RE = re.compile(
    r"\b(?:artifacts?|enchantments?|planeswalkers?|battles?|noncreature permanents?)\b")


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


def _hits_noncreature(obj: str) -> bool:
    """The object is an opposing artifact / enchantment / planeswalker / battle on the
    battlefield — same zone, own and count gates as `_hits_creature`."""
    obj = re.split(r"\bfor each\b|,? where\b|\bequal to\b", _wipe_object(obj), maxsplit=1)[0]
    head = _CLAUSE_START_RE.split(obj, maxsplit=1)[0]
    if not _NONCREATURE_OBJECT_RE.search(head):
        return False
    return not (_ZONE_OBJECT_RE.search(head) or _OWN_OBJECT_RE.search(head))


def _anaphor_antecedent(text: str, at: int) -> str | None:
    """The object of the last "target ..." an anaphoric kill at `at` can point back to, or
    None when there is none or the kill is not an ANSWER to it:

    * the target was PUMPED first ("target creature gains trample and gets +X/+0 ... destroy
      that creature if it attacked" — Berserk, Blood Frenzy, War Barge): the destroy is the
      drawback on a creature you are helping, not removal;
    * the kill waits on its death ("When the creature dies this turn, exile the creature" —
      Whippoorwill exiles a graveyard card);
    * the head of the target phrase names no creature or permanent ("target opponent may
      guess if a creature you control ..." — Syx is about YOUR creature).
    """
    start = text.rfind("\n", 0, at) + 1
    region = text[start:at]
    if not _TARGET_OBJECT_RE.search(region) and _RIDER_LINE_RE.match(region) and start:
        prev = text.rfind("\n", 0, start - 1) + 1
        region = text[prev:start - 1]
    found = list(_TARGET_OBJECT_RE.finditer(region))
    if not found:
        return None
    obj = found[-1].group(1)
    between = region[found[-1].start():]
    if (re.search(r"\bgets? \+|\bgains?\b", between)
            or re.search(r"\bdies\b|\bput into a graveyard\b", between.split(".")[-1])):
        return None
    if not _CREATURE_OBJECT_RE.search(_CLAUSE_START_RE.split(obj, maxsplit=1)[0]):
        return None
    return obj


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
    # answers to an artifact/enchantment/planeswalker/battle: destroy|exile|damage|bounce|tuck.
    # Never folded into removal/board_wipe (see _NONCREATURE_OBJECT_RE).
    noncreature: frozenset[str] = frozenset()


def interaction_modes(text: str) -> InteractionModes:
    """Clause modes over CLEANED text (`_clean_text`: casefolded, reminder text stripped)."""
    # Quoted text is KEPT, unlike `_draw_counts`: a granted "{T}: deals 1 damage to any
    # target" (Hermetic Study, Shuriken, Bombardment's Missiles) is interaction the
    # controller really has; stripping it lost 30+ such cards in the first draft.
    spot: set[str] = set()
    wipe: set[str] = set()
    counter: set[str] = set()

    noncreature: set[str] = set()

    for m in _REMOVAL_TARGET_RE.finditer(text):
        verb = "exile" if text.startswith("exile", m.start()) else "destroy"
        if verb == "exile" and _flickers(text, m.start()):
            continue
        if _hits_creature(m.group(1)):
            spot.add(verb)
        elif _hits_noncreature(m.group(1)):
            noncreature.add(verb)
    for m in _ANAPHOR_KILL_RE.finditer(text):
        verb = m.group(1)
        obj = _anaphor_antecedent(text, m.start())
        if (obj is not None and _hits_creature(obj)
                and not (verb == "exile" and _flickers(text, m.start()))):
            spot.add(verb)
    for m in _WIPE_ALL_RE.finditer(text):
        verb = "exile" if text.startswith("exile", m.start()) else "destroy"
        if verb == "exile" and _flickers(text, m.start()):
            continue
        if _hits_creature(m.group(1)):
            # (a mass flicker -- Golden Argosy's "exile each creature that crewed it ...
            # return them" -- is no more a sweep than Ephemerate is removal)
            # Council's Judgment exiles "each permanent with the most votes": one answer.
            (spot if "most votes" in m.group(1) else wipe).add(verb)
        elif _hits_noncreature(m.group(1)):
            noncreature.add(verb)
    for m in _DAMAGE_TARGET_RE.finditer(text):
        obj = m.group(1)
        if obj in ("any target", "targets") or _hits_creature(obj):
            spot.add("damage")
        elif _hits_noncreature(obj) and not re.search(r"\b(?:players?|opponents?)\b", obj):
            # "damage to target player or planeswalker" (Blightning, Vent Sentinel) is burn
            # to the face that may redirect, not an answer to a planeswalker.
            noncreature.add("damage")
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
        elif _hits_noncreature(obj):
            noncreature.add("bounce")
    for rx in (_TUCK_RE, _SHUFFLE_RE):
        for m in rx.finditer(text):
            if _hits_creature(m.group(1)):
                spot.add("tuck")
            elif _hits_noncreature(m.group(1)):
                noncreature.add("tuck")
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
    return InteractionModes(frozenset(spot), frozenset(wipe), frozenset(counter),
                            frozenset(noncreature))


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


def _draw_counts(text: str, names: tuple[str, ...] = ()) -> tuple[int, int]:
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

    A trigger is not an engine just because it is a trigger. "When this creature dies, you
    may draw a card" fires once; counting it as a per-turn engine made Solemn Simulacrum read
    as "repeatable draw" in the swap brief, and the Deck Mentor repeated it (found live
    2026-10-01). 411 cards were engines only through a one-shot dies / enters / leaves /
    cast trigger. Those draws are card advantage the card really has, so they move to the
    immediate count rather than vanishing. Several one-shot triggers on one card take the
    MAX, not the sum: Market Gnome's dies and craft-exile triggers are alternatives, and
    Mephitic Draught's ETB + graveyard pair under-counting by one is the honest direction.

    The converse held for activated abilities: "{T}: Draw a card" was an IMMEDIATE draw, so
    Jayemdae Tome read as one card and Arcanis the Omnipotent as a three-card spell. An
    activated ability on a permanent that stays is a per-turn engine; only a cost that
    consumes the card itself keeps the immediate count (`_activation_kind`). `names` is
    the card's own names, for old-wording costs like "Sacrifice Stone of Erech".

    Whose draw it is matters as much as how often: "that player draws" after an
    opponent-scoped trigger is the OPPONENT drawing (Coveted Jewel, Well of Ideas), and
    "each other player draws" never was ours.

    A trigger's effect often runs past its first sentence: "Whenever this creature deals
    combat damage to a player, you may discard a card. If you do, draw a card." Each sentence
    used to be read on its own, so that draw was IMMEDIATE and ~170 recurring triggers (Gix,
    Yawgmoth Praetor, Academy Raider, Archon of Cruelty) read as one card instead of an
    engine. A FOLLOW-ON sentence — a non-trigger sentence after a trigger on the same line —
    now belongs to that trigger's ability and inherits its kind, so a one-shot ETB's
    follow-on stays one-shot. Within one ability an "instead" sentence is the MAX of the two
    readings, not the sum (Fblthp, The Destined Thief); an ability that sacrifices or exiles
    the card itself at or before its draw is one-shot (Impaler Shrike), one that does so only
    afterwards is still an engine (Tellah). A follow-on anaphor ("If the player does, they
    draw") is the opponent's when the condition is opponent-scoped and the effect opened on
    "that player"/"they" (Skullknocker Ogre, Miss Highwater). A NESTED trigger keeps its own
    kind: Xira's "When that creature dies" under an attack trigger stays one-shot, an honest
    under-count.

    A trigger is recognised at the START of its sentence, so an ability word in front of it
    ("Landfall — Whenever a land you control enters, you gain 1 life and draw a card.") hid
    it: Tatyova's engine read as one immediate card, Sister Repentia's martyrdom and Lord of
    Change's ETB were summed rather than max'd with other one-shots, and Starving Revenant's
    "Descend 8 — Whenever you draw a card, ..." counted the CONDITION as a draw. The prefix
    is stripped before the line is read (`_ABILITY_WORD_PREFIX_RE`).
    """
    text = re.sub(r'"[^"]*"', "", text)
    name_alt = "|".join(re.escape(n) for n in names) or r"(?!x)x"
    self_res = (re.compile(_SELF_COST_TEMPLATE.format(name=name_alt)),
                re.compile(_SELF_EFFECT_TEMPLATE.format(name=name_alt)))
    immediate = 0
    one_shot = 0
    engine = 0
    activated_engine = 0
    prev_one_shot = False  # the sentence a reflexive "when you do" hangs off
    for line in text.split("\n"):
        activated = 0
        line = _ABILITY_WORD_PREFIX_RE.sub("", line)
        activation = _activation_kind(line, *self_res)
        if activation:
            line = line.partition(":")[2]  # the cost never draws ("discard the last card you drew")
        opponent_chosen = False  # Soldevi Sentry: "Choose target opponent. ... that player"
        # The triggered ability the current sentence belongs to: None before any trigger on
        # this line, else whether it is one-shot, and its draws so far.
        ability_one_shot: bool | None = None
        ability_drawn = 0
        ability_anaphor_is_opponent = False
        ability_consumed = False  # its effect has sacrificed/exiled the card itself so far
        for sentence in line.split("."):
            s = sentence.strip()
            if not s:
                continue
            head, sep, tail = s.partition(",")
            triggered = bool(_TRIGGER_RE.match(s))
            reflexive = bool(_REFLEXIVE_TRIGGER_RE.match(head))
            if activation:
                is_one_shot = False
            elif triggered:
                # A legendary name carries its own comma ("When Lutri, Pauper Otter enters the
                # battlefield, ..."), so the event can sit one comma further on.
                is_one_shot = bool(
                    _ONE_SHOT_TRIGGER_RE.match(head)
                    or _ONE_SHOT_TRIGGER_RE.match(",".join(s.split(",")[:2]))
                    or (prev_one_shot and reflexive))
                if not reflexive:
                    # A new trigger starts a new ability; a reflexive one continues the last.
                    one_shot, engine = _close_ability(
                        ability_one_shot, ability_drawn, one_shot, engine)
                    ability_drawn = 0
                    # Its anaphors in later sentences point at the opponent only when the
                    # condition is opponent-scoped AND the effect hands the turn to "that
                    # player" (Skullknocker Ogre: "..., that player discards a card at random.
                    # If the player does, they draw a card"). Gix's "its controller may pay 1
                    # life. If they do, they draw a card" stays ours.
                    ability_anaphor_is_opponent = bool(
                        sep and (_OPPONENT_SCOPE_RE.search(head)
                                 or _COMBAT_DAMAGE_TO_PLAYER_RE.search(head))
                        and _ANAPHOR_EFFECT_RE.search(s))
                ability_one_shot = is_one_shot
            else:
                # A FOLLOW-ON sentence of a trigger ("Whenever ..., you may pay 1 life. If you
                # do, draw a card") is that trigger's effect: it fires exactly as often.
                is_one_shot = bool(ability_one_shot)
            follow_on = not activation and not triggered and ability_one_shot is not None
            if triggered and not activation and not reflexive:
                ability_consumed = False
            if (triggered or follow_on) and not activation:
                effect = tail if triggered and sep else s
                ability_consumed = ability_consumed or bool(
                    self_res[1].search(effect) or _SACRIFICE_IT_RE.search(effect))
            prev_one_shot = is_one_shot
            chose_opponent_before = opponent_chosen
            opponent_chosen = opponent_chosen or bool(_CHOSEN_OPPONENT_RE.search(s))
            if _DRAW_REPLACEMENT_RE.search(s) or _DREW_CONDITION_RE.search(s):
                continue
            if "would lose the game" in s or "0 or less life" in s:
                # Nira, Hellkite Duelist: "the next time you would lose the game this turn,
                # instead draw three cards" — an emergency replacement, not card advantage.
                # Heaven Sent's "if an opponent has 0 or less life, draw seven cards" waits on
                # a state that ends the game first.
                continue
            scan = s
            if triggered:
                # Count only the EFFECT clause. The trigger condition runs to the first comma;
                # "whenever you draw a card, put a counter" must contribute nothing.
                if sep and _DRAW_RE.search(head):
                    scan = tail
            # Whose draw an anaphor names: the opponent when this trigger's own condition is
            # opponent-scoped (Coveted Jewel, Well of Ideas' "each other player's draw step,
            # that player draws", Forced Fruition), or when an earlier sentence of the same
            # ability chose a target opponent (Soldevi Sentry).
            anaphor_is_opponent = chose_opponent_before or (
                triggered and bool(sep) and bool(_OPPONENT_SCOPE_RE.search(head))) or (
                follow_on and ability_anaphor_is_opponent)
            drawn = 0
            for m in _DRAW_RE.finditer(scan):
                before = scan[: m.start()]
                if (_OTHER_PLAYER_SUBJECT_RE.search(before)
                        and not _SHARED_WITH_OPPONENT_RE.search(before)):
                    continue
                if anaphor_is_opponent and _ANAPHOR_SUBJECT_RE.search(before):
                    continue
                if activation == "opponents" and "controller" not in before:
                    continue
                if _NEGATED_DRAW_RE.search(before):
                    continue
                n = _WORD_NUMBERS.get(m.group(1), 0)
                if activation == "repeatable":
                    activated += n
                elif (not activation and (triggered or follow_on)
                        and not (is_one_shot or ability_consumed)):
                    drawn += min(n, 2)  # cap: triggers rarely fire more than ~2x/turn in goldfish
                else:
                    drawn += n
            if not activation and (triggered or follow_on):
                if drawn and ability_consumed:
                    ability_one_shot = True  # the card was used up to pay for this draw
                # "... draw a card. If <condition>, draw two cards instead" (The Destined
                # Thief, Fblthp) is one or the other, never both.
                if follow_on and "instead" in s:
                    ability_drawn = max(ability_drawn, drawn)
                else:
                    ability_drawn += drawn
            else:
                immediate += drawn
        one_shot, engine = _close_ability(ability_one_shot, ability_drawn, one_shot, engine)
        # One activated ability's draws per turn, at the same cap of 2. Several activated draws
        # on one card are usually ALTERNATIVE uses of the same {T} (Krovikan Sorcerer's two
        # discard-to-draw abilities), and "draw a card. If you control eight or more lands,
        # draw two cards instead" (Zimone) is one or the other — so the MAX, not the sum.
        activated_engine = max(activated_engine, min(activated, 2))
    return immediate + one_shot, engine + activated_engine


def _close_ability(ability_one_shot: bool | None, drawn: int,
                   one_shot: int, engine: int) -> tuple[int, int]:
    """Fold one finished triggered ability's draws into (one_shot, engine).

    Several one-shot triggers on one card take the MAX (Market Gnome's alternatives); a
    recurring trigger's draws add to the per-turn engine."""
    if ability_one_shot is None:
        return one_shot, engine
    if ability_one_shot:
        return max(one_shot, drawn), engine
    return one_shot, engine + drawn


def _activation_kind(line: str, self_cost_re: re.Pattern[str],
                     self_effect_re: re.Pattern[str]) -> str | None:
    """"repeatable" / "one_shot" / "opponents" for an activated-ability line, None for
    anything else ("opponents": only an opponent may activate it).

    "{T}: Draw a card" and Arcanis's "{T}: Draw three cards" are per-turn engines: the
    permanent stays and untaps. Before 2026-10-01 every activated draw was read as an
    IMMEDIATE draw on resolution — 498 permanents in the store. Only an ability that uses up
    the card itself, in its cost or its effect, or one capped at once per game, is really
    one-shot; those keep the immediate count. A planeswalker's + or 0 loyalty ability can be activated every turn;
    a − ability spends the loyalty it is paid from, so it stays one-shot (an honest
    under-count for a walker that ticks up and down).
    """
    if ":" not in line:
        return None
    head = line.partition(":")[0].strip()
    if len(head) > 120 or _TRIGGER_RE.match(head) or " if " in f" {head} ":
        return None
    if "only your opponents may activate" in line:
        # The ACTIVATOR is an opponent: Oft-Nabbed Goat's bare "Draw a card" draws for them.
        # Soul Ransom names its draw's subject ("This Aura's controller ... draws") — ours,
        # but on the opponent's schedule, so never an engine.
        return "opponents"
    loyalty = _LOYALTY_COST_RE.match(head)
    if loyalty:
        return "one_shot" if loyalty.group(1) in ("−", "-") else "repeatable"
    cost = _ACTIVATION_PREFIX_RE.sub("", head)
    if "{" not in cost and not _COST_VERB_RE.match(cost):
        return None
    if (_ONCE_ONLY_COST_RE.search(head) or _ONCE_ONLY_LIMIT_RE.search(line)
            or self_cost_re.search(cost) or self_effect_re.search(line.partition(":")[2])):
        return "one_shot"
    return "repeatable"


def _self_names(card: Card) -> tuple[str, ...]:
    """Every way the card's own text can name it: full name, each face, and a legend's short
    name ("Calim" for "Calim, Djinn Emperor"), casefolded like `_clean_text`."""
    names: set[str] = set()
    for full in (card.name or "").split(" // "):
        full = full.strip().casefold()
        if full:
            names.add(full)
            names.add(full.split(",")[0].strip())
    return tuple(sorted((n for n in names if n), key=len, reverse=True))


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


# --- role-only detectors (2026-10-18; feed `redundancy.card_roles`, never the simulator) ---
#
# Measured on a real Jeskai artifact-tokens deck (Vraska, Soul of Stone): 41 of 62 nonland
# cards had NO role, so the Deck Mentor reported one removal spell and one finisher. Each
# detector below is a CLASS that deck exposed, sized over the 33,412-card store first.

# Treasure is mana, but its "Add one mana" lives in reminder text, which `_clean_text` strips —
# so every Treasure maker read as zero ramp. Only REPEATABLE Treasure counts (an ETB/dies
# Treasure is a one-shot, the same as a ritual, which ramp has never counted), and only OURS
# ("its controller creates" / "target opponent creates" is someone else's).
_TREASURE_RE = re.compile(
    r"\bcreates? (a|an|one|two|three|four|five|x|that many|a number of)\b[^.]{0,30}?"
    r"treasure tokens?")
_OTHER_CREATOR_RE = re.compile(
    r"\b(?:opponents?|that player|its controller|their controller|they|each player)"
    r" (?:may )?$")
# A trigger whose EVENT is a price you pay is not free mana: Nuka-Cola Vending Machine's
# "Whenever you sacrifice a Food, create a tapped Treasure" nets -2 once the Food is paid for.
_PAID_EVENT_RE = re.compile(r"^whenever you (?:sacrifice|discard)\b")
# "spells you cast ... cost {N} less" — tribal (Dragonlord's Servant), typed (Geist of Saint
# Thalia, Starnheim Courser), conditional (Semblance Anvil). A sentence that is temporary
# ("this turn", "until your next turn" — Urza's +2, Will Kenrith), aimed at one permanent
# ("spells ... that target this creature" — Elderwood Scion) or somebody else's spells never
# matches. Cost reduction is the CARD's own spells only — "this spell costs {1} less" is
# `self_reduction_per_creature`'s business and reads "costs", not "spells you cast".
_COST_LESS_RE = re.compile(r"\bspells? you cast\b[^.]{0,80}?\bcosts? \{(\d+)\} less\b")
# Improvise / convoke / affinity granted to your spells: each artifact (or creature) pays for
# {1} — Inspiring Statuary is a cost reducer that scales with the board.
_GRANT_ALT_PAY_RE = re.compile(
    r"\bspells you cast have (?:improvise|convoke|affinity for (?:artifacts|creatures"
    r"|artifact creatures))\b")
_TEMPORARY_RE = re.compile(r"\bthis turn\b|\buntil (?:end of turn|your next turn|the end of)")
# Standing permission to use the top of the library as a hand: Mystic Forge, Future Sight,
# Vizier of the Menagerie, Courser of Kruphix's lands. A one-turn window ("until end of turn,
# you may play lands and cast spells from the top" — The Belligerent, Gwenom) is skipped.
_TOP_CAST_RE = re.compile(r"\byou may (?:play|cast) ([^.]{0,80}?) from the top of your library\b")
_ALT_WIN_RE = re.compile(r"\byou win the game\b")
_EXTRA_COMBAT_RE = re.compile(r"\badditional combat phases?\b")
# A STATIC pump to the whole team: Tempered Steel ("Artifact creatures you control get +2/+2"),
# Dictate of Heliod, Intangible Virtue, Jor Kadeen's metalcraft. One-shot "until end of turn"
# pumps are `_overrun`'s. Only these qualifiers may precede the noun — a tribe or colour lord
# ("Other Elves", "white creatures you control") is the tribal/colour plan, and calling every
# lord a finisher would make a tribal deck's lords its cut pool.
_ANTHEM_RE = re.compile(
    r"((?:[\w'-]+ ){0,3})(?:creatures|creature tokens) you control get \+(\d+|x)/[+\-−]?(?:\d+|x)")
_ANTHEM_QUALIFIERS = frozenset({"other", "artifact", "nontoken", "token", "attacking"})


def _treasure_ramp(text: str, is_spell: bool, names: tuple[str, ...]) -> int:
    """Treasure made per turn by a repeatable trigger or activated ability, net of the
    activation's mana cost, capped at 2 (the same goldfish cap the draw engines use)."""
    if is_spell:
        return 0
    text = re.sub(r'"[^"]*"', "", text)  # a GRANTED ability (Furnace Reins) is not this card's
    name_alt = "|".join(re.escape(n) for n in names) or r"(?!x)x"
    self_res = (re.compile(_SELF_COST_TEMPLATE.format(name=name_alt)),
                re.compile(_SELF_EFFECT_TEMPLATE.format(name=name_alt)))
    total = 0
    for line in text.split("\n"):
        line = _ABILITY_WORD_PREFIX_RE.sub("", line.strip())
        activation = _activation_kind(line, *self_res)
        if activation == "repeatable":
            body, cost = line.partition(":")[2], _activation_mana_cost(line)
        elif activation is None and _TRIGGER_RE.match(line):
            head = line.split(",")[0]
            if (_ONE_SHOT_TRIGGER_RE.match(head)
                    or _ONE_SHOT_TRIGGER_RE.match(",".join(line.split(",")[:2]))
                    or _PAID_EVENT_RE.match(head)):
                continue
            body, cost = line, 0
        else:
            continue  # static (Xorn's replacement), one-shot activation, saga chapter
        made = 0
        for m in _TREASURE_RE.finditer(body):
            if _OTHER_CREATOR_RE.search(body[: m.start()]):
                continue
            made += _WORD_NUMBERS.get(m.group(1), 1)
        total += max(0, min(made, 2) - cost)
    return min(total, 2)


def _cost_reduction(text: str) -> int:
    best = 0
    for sentence in re.split(r"[.\n]", text):
        if _TEMPORARY_RE.search(sentence) or "that target" in sentence:
            continue
        m = _COST_LESS_RE.search(sentence)
        if m:
            best = max(best, min(int(m.group(1)), 2))
        elif _GRANT_ALT_PAY_RE.search(sentence):
            best = max(best, 1)
    return best


def _top_of_library(text: str, is_spell: bool) -> bool:
    if is_spell:
        return False
    for sentence in re.split(r"[.\n]", text):
        if _TEMPORARY_RE.search(sentence):
            continue
        m = _TOP_CAST_RE.search(sentence)
        if m and "this card" not in m.group(1):
            return True
    return False


def _team_anthem(text: str) -> bool:
    for sentence in re.split(r"[.\n]", text):
        # Only the PUMP's own duration disqualifies: Sentinel Sarah Lyons' "as long as an
        # artifact entered ... this turn, creatures you control get +2/+2" is a static anthem
        # with a condition, not a one-shot.
        if "until end of turn" in sentence or re.search(r"\bget [^.]*\bthis turn\b", sentence):
            continue
        for m in _ANTHEM_RE.finditer(sentence):
            if m.group(2) == "0":
                continue
            if set(m.group(1).split()) <= _ANTHEM_QUALIFIERS:
                return True
    return False


# Impulse draw: "Exile the top two cards of your library. Until the end of your next turn, you
# may play those cards" (Light Up the Stage, Outpost Siege, Jeska's Will, Wiccan). Red's card
# advantage never says "draw", so `_draw_counts` saw none of it and every red deck read as
# draw-poor. Two sentences of ONE ability: the exile, then a permission whose subject is YOU and
# whose object is the exiled cards as such. Measured over the store before writing a pattern;
# the exclusions are the near-misses that sample turned up, each an honest under-count:
#
# * the permission belongs to someone else — "that creature's controller may play" (Curse of
#   Hospitality), "they may play" (Expedited Inheritance), "each player may play" (Rocco);
# * it is CONDITIONAL or an alternative — "if it's red, you may cast it" (Chandra, Dressed to
#   Kill), "if you don't, you may play" (Spark of Creativity), "during any turn you attacked"
#   (Boros Strike-Captain), "you may cast that card if it's an instant" (Nivix);
# * it is TYPE-RESTRICTED — "an instant or sorcery spell from among" (Chandra, Hope's Beacon),
#   "creature spells from among" (Eager Flameguide), "spells with mana value x or less" (Epic
#   Experiment): how many of the exiled cards are castable is not knowable from the text;
# * it lives on ANOTHER line — "you may play cards exiled with this enchantment" (Theater of
#   Horrors, Nightveil Specter): the permission is a separate static with its own conditions;
# * a reveal-until ("exile cards from the top until you exile a nonland card") is cascade, one
#   free spell, not a look at N cards; a "would draw ... instead" (Eruth) REPLACES a draw;
# * a quoted ability is GRANTED, not this card's (Capricious Sliver, Tavern Brawler).
_IMPULSE_NUMBERS = {**_WORD_NUMBERS, "eight": 8, "nine": 9, "ten": 10}
_IMPULSE_EXILE_RE = re.compile(
    r"\bexiles? (?:the top (\w+) cards?\b|the top card\b|(that many|x|\w+) cards from the top\b"
    r"|cards from the top\b)")
_REVEAL_UNTIL_EXILE_RE = re.compile(r"\buntil (?:you|they) (?:have )?exiled?\b")  # Dream Harvest
# The permission sentence: after an optional window clause, "you may play/cast <the exiled
# cards>". The object must name the exiled cards as such; an adjective between "cast" and
# "spells" (instant, red, creature, artifact) is a type restriction and fails the match.
# "If you do" after an optional exile ("you may exile the top card ... if you do, you may play
# it") is the same ability going ahead, not a condition on the card; "otherwise" is the nonland
# branch of a land check (Bruse Tarl).
_IMPULSE_WINDOW_RE = re.compile(
    r"^(?:(?:until [^,]{1,40}|during your next turn|otherwise|then|if you do), )+")
_IMPULSE_FROM = r"(?:them|those (?:exiled )?cards|the exiled cards|cards exiled this way)"
_IMPULSE_PERMISSION_RE = re.compile(
    r"^you may (?:play|cast) (?:"
    r"(one of (?:those|them|the exiled) cards|one of them|a spell from among \w+(?: \w+){0,3})"
    r"|up to (\w+) of (?:those|them|the exiled) cards"
    r"|that card|those cards|the exiled cards?|it|them|cards exiled this way"
    rf"|(?:lands and cast )?(?:any number of )?spells from among {_IMPULSE_FROM}"
    r")\b")
_IMPULSE_PERMISSION_INLINE_RE = re.compile(r", then (you may (?:play|cast) .*)$")
_CHOOSE_ONE_OF_RE = re.compile(r"\bchoose one(?: of (?:them|those (?:exiled )?cards))?$")
_DISCARD_A_CARD_RE = re.compile(r"\bdiscard (?:a|one) card\b")
_DISCARD_MANY_RE = re.compile(r"\bdiscard (?:x|two|three|\d+) cards|\bdiscard your hand\b")
_SUB_LINE_RE = re.compile(r"^(?:• |\d+(?:—\d+)? \| )")       # a mode bullet / a die result
_SAGA_CHAPTER_RE = re.compile(r"^[ivx]+(?:, [ivx]+)* — ")
_SKIP_DRAW_RE = re.compile(r"\bskip your draw step\b")
_IMPULSE_ONE_SHOT_CAP = 3  # past three cards a one-turn window cannot be spent
_IMPULSE_ENGINE_CAP = 2    # the per-turn goldfish cap every draw engine here uses


def _impulse_in_ability(body: str) -> int:
    """Cards one ability lets us play off the top, net of a discarded card; 0 if none."""
    if _DISCARD_MANY_RE.search(body):
        return 0  # "discard your hand, then exile the top three" is a reset, not advantage
    sentences = [s.strip() for s in body.split(".") if s.strip()]
    for i, s in enumerate(sentences):
        m = _IMPULSE_EXILE_RE.search(s)
        if not m or _REVEAL_UNTIL_EXILE_RE.search(s) or "would draw" in s:
            continue
        word = m.group(1) or m.group(2)
        n = _IMPULSE_NUMBERS.get(word, 1) if word else 1  # x / "that many": a floor of one
        inline = _IMPULSE_PERMISSION_INLINE_RE.search(s[m.end():])
        later = ([inline.group(1)] if inline else []) + sentences[i + 1:]
        for p in later:
            p = _IMPULSE_WINDOW_RE.sub("", p, count=1)
            if " if " in f" {p} ":
                continue  # conditional or alternative permission
            pm = _IMPULSE_PERMISSION_RE.match(p)
            if not pm:
                continue
            if pm.group(1):
                n = 1
            elif pm.group(2):
                n = min(n, _IMPULSE_NUMBERS.get(pm.group(2), 1))
            if any(_CHOOSE_ONE_OF_RE.search(x) for x in sentences[i:i + 3]):
                n = 1  # "exile the top three ... choose one of them. You may play that card"
            if _DISCARD_A_CARD_RE.search(" ".join(sentences[:i + 1])):
                n -= 1  # Party Thrasher: discard, exile two, keep one — a rummage, nets zero
            return max(0, n)
        return 0  # the first exile of the top had no permission for us: not impulse
    return 0


def _impulse_draw(text: str, is_spell: bool, names: tuple[str, ...]) -> tuple[int, int]:
    """(one-shot impulse cards, repeatable impulse cards per turn) — see `_IMPULSE_EXILE_RE`.

    Repeatable is judged exactly as `_treasure_ramp` judges a Treasure engine: a repeatable
    activation or a recurring trigger (`_activation_kind`, `_ONE_SHOT_TRIGGER_RE`, and a paid
    event like Inti's "whenever you discard" is not free). An activation that DISCARDS a card
    nets one fewer (Chase Stein: discard, exile one — zero); a sacrificed creature or artifact
    is not netted, because the fodder is usually a token. A mode bullet or die result inherits
    the kind of the trigger/activation/spell it hangs off, and alternatives take the MAX. A Saga
    chapter, a Room door and a `−` loyalty ability are one-shot."""
    text = re.sub(r'"[^"]*"', "", text)
    name_alt = "|".join(re.escape(n) for n in names) or r"(?!x)x"
    self_res = (re.compile(_SELF_COST_TEMPLATE.format(name=name_alt)),
                re.compile(_SELF_EFFECT_TEMPLATE.format(name=name_alt)))
    one_shot = engine = activated = 0
    parent: str | None = "one_shot" if is_spell else None  # the kind a bullet inherits
    bullets = 0  # the best alternative under the current parent
    for raw in text.split("\n"):
        line = _ABILITY_WORD_PREFIX_RE.sub("", raw.strip())
        sub = bool(_SUB_LINE_RE.match(line))
        if sub:
            line = _SUB_LINE_RE.sub("", line)
        kind: str | None
        activation = None if is_spell else _activation_kind(line, *self_res)
        if is_spell:
            kind, body = "one_shot", line
        elif activation in ("repeatable", "one_shot"):
            kind, head, body = activation, *line.split(":", 1)
            if _DISCARD_MANY_RE.search(head):
                kind = None
            elif _DISCARD_A_CARD_RE.search(head):
                body = "discard a card. " + body
        elif activation is None and _TRIGGER_RE.match(line):
            head = line.split(",")[0]
            if _PAID_EVENT_RE.match(head):
                kind = None
            elif (_ONE_SHOT_TRIGGER_RE.match(head)
                    or _ONE_SHOT_TRIGGER_RE.match(",".join(line.split(",")[:2]))):
                kind = "one_shot"
            else:
                kind = "repeatable"
            body = line
        elif _SAGA_CHAPTER_RE.match(line):
            kind, body = "one_shot", _SAGA_CHAPTER_RE.sub("", line)
        elif sub:
            kind, body = parent, line
        else:
            kind, body = None, line  # a static, an opponents-only activation
        if not sub:
            # A new ability: bank the best alternative of the previous header's modes.
            one_shot, engine = _bank_impulse(parent, bullets, one_shot, engine)
            parent, bullets = kind, 0
            if is_spell:
                parent = "one_shot"
        if kind is None:
            continue
        n = _impulse_in_ability(body)
        if sub:
            bullets = max(bullets, n)
        elif activation == "repeatable" and kind == "repeatable":
            # Several activations are usually alternative uses of one {T} (Oracle's Vault):
            # the MAX, as `_draw_counts` does for activated draws.
            activated = max(activated, min(n, _IMPULSE_ENGINE_CAP))
        else:
            one_shot, engine = _bank_impulse(kind, n, one_shot, engine)
    one_shot, engine = _bank_impulse(parent, bullets, one_shot, engine)
    engine += activated
    if engine and _SKIP_DRAW_RE.search(text):
        engine -= 1  # Wild Wasteland: the upkeep impulse REPLACES the draw step's card
    return min(one_shot, _IMPULSE_ONE_SHOT_CAP), min(engine, _IMPULSE_ENGINE_CAP)


def _bank_impulse(kind: str | None, n: int, one_shot: int, engine: int) -> tuple[int, int]:
    """Several one-shot abilities are alternatives or separate events: the MAX (like
    `_close_ability`). Recurring abilities add, each at the per-turn cap."""
    if not n or kind is None:
        return one_shot, engine
    if kind == "one_shot":
        return max(one_shot, n), engine
    return one_shot, engine + min(n, _IMPULSE_ENGINE_CAP)


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
        # The LAND has to reach the battlefield, so "battlefield" is read in the search's own
        # sentence. Anywhere in the text let Archaeomancer's Map (search to HAND; a separate
        # ability says "onto the battlefield") read as land-fetch ramp.
        if any(_land_reaches_battlefield(text, m.start())
               for rx in (_SEARCH_LAND_RE, _SEARCH_LAND_SYMMETRIC_RE)
               for m in rx.finditer(text)):
            fetches_land = True
            ramp_sources = max(ramp_sources, 1)

    tutor = False
    m = _SEARCH_CARD_RE.search(text)
    if m and not _LAND_OBJECT_RE.search(m.group(1)):
        tutor = True

    modes = interaction_modes(text)
    removal = 1 if modes.spot else 0
    board_wipe = bool(modes.wipe)
    counterspell = bool(modes.counter)
    cheats_creatures = _cheats_creatures(text)
    draw_cards, engine_draw = _draw_counts(text, _self_names(card))

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
    is_spell = card.has_type("Instant") or card.has_type("Sorcery")
    impulse_draw, impulse_engine = _impulse_draw(text, is_spell, _self_names(card))

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
        noncreature_removal=bool(modes.noncreature) and not (modes.spot or modes.wipe),
        treasure_ramp=_treasure_ramp(text, is_spell, _self_names(card)),
        cost_reduction=_cost_reduction(text),
        top_of_library=_top_of_library(text, is_spell),
        impulse_draw=impulse_draw,
        impulse_engine=impulse_engine,
        alt_win=bool(_ALT_WIN_RE.search(text)),
        extra_combat=bool(_EXTRA_COMBAT_RE.search(text)),
        team_anthem=_team_anthem(text),
        impact=impact,
    )
