"""
Theme matching for Myth Forge decks using only local card data.
Reproduces Scryfall query semantics with type_line and oracle_text.

Gold set
| Card (type line) | oracle text (abridged, verbatim) | theme | expected |
|---|---|---|---|
| Shivan Dragon (Creature — Dragon) | "Flying / {R}: This creature gets +1/+0…" | tribal_dragons | WEAK |
| Bladewing the Risen (Legendary Creature — Zombie Dragon) | "…{B}{R}: Dragon creatures get +1/+1…" | tribal_dragons | STRONG |
| Bladewing the Risen | (same — no Zombie payoff text) | tribal_zombies | WEAK |
| Goblin Chieftain (Creature — Goblin) | "Other Goblin creatures you control get +1/+1 and have haste." | tribal_goblins | STRONG |
| Jadar, Ghoulcaller (Legendary Creature — Human Wizard) | "…if you control no creatures with decayed, create a 2/2 black Zombie creature token…" | tribal_zombies | STRONG |
| Storm-Kiln Artist (Creature — Dwarf Shaman) | "…Magecraft — Whenever you cast or copy an instant or sorcery spell, create a Treasure token." | spellslinger | STRONG |
| Storm-Kiln Artist | "This creature gets +1/+0 for each artifact you control. …" | artifacts | NO_MATCH |
| Storm-Kiln Artist | "…create a Treasure token." | tokens | STRONG |
| Grave Pact (Enchantment) | "Whenever a creature you control dies, each other player sacrifices a creature…" | aristocrats | STRONG |
| Psychosis Crawler (Artifact Creature — Phyrexian Horror) | "…Whenever you draw a card, each opponent loses 1 life." | draw_matters | STRONG |
| Psychosis Crawler | (same) | artifacts | WEAK |
| Steel Overseer (Artifact Creature — Construct) | "{T}: Put a +1/+1 counter on each artifact creature you control." | counters | STRONG |
| Living Death (Sorcery) | "Each player exiles all creature cards from their graveyard…" | reanimator | NO_MATCH |
| Living Death | (same — "their graveyard", not "your") | graveyard | NO_MATCH |
| Sol Ring (Artifact) | "{T}: Add {C}{C}." | tribal_dragons | NO_MATCH |
| Sol Ring | (same) | artifacts | WEAK |

Gold set — the five DEAD rules revived 2026-08-14
-------------------------------------------------
Each of these themes leads its `THEME_SYNERGY_QUERIES` entry with an `otag:` oracle tag.
An oracle tag has no local equivalent, so the rule here was left holding only the query's
literal fallback — and those literals match almost no printed card. Measured over the
34,846-card store the rules scored: landfall **1** card, chaos 22, aristocrats 34, etb 37,
draw_matters 50. Same failure shape already documented for `enchantress` and `magecraft`.

| Card (type line) | oracle text (abridged, verbatim) | theme | expected |
|---|---|---|---|
| Lotus Cobra (Creature — Snake) | "Landfall — Whenever a land you control enters, create a Treasure token." | landfall | STRONG |
| Tatyova, Benthic Druid (Legendary Creature — Merfolk Druid) | "Whenever a land you control enters, you gain 1 life and draw a card." | landfall | STRONG |
| Blood Artist (Creature — Vampire) | "Whenever this creature or another creature dies, target player loses 1 life…" | aristocrats | STRONG |
| Zulaport Cutthroat (Creature — Human Rogue) | "Whenever this creature or another creature you control dies…" | aristocrats | STRONG |
| Viscera Seer (Creature — Vampire Wizard) | "Sacrifice a creature: Scry 1." | aristocrats | STRONG (the OUTLET half) |
| Murder (Instant) | "Destroy target creature." | aristocrats | NO_MATCH |
| Restoration Angel (Creature — Angel) | "When this creature enters, exile it, then return that card to the battlefield." | etb | STRONG |
| Mulldrifter (Creature — Elemental) | "When this creature enters, draw two cards." | etb | **NO_MATCH** |
| Nekusar, the Mindrazer (Legendary Creature — Zombie Wizard) | "Whenever a player draws a card, Nekusar deals 1 damage to that player." | draw_matters | STRONG |
| Krark's Thumb (Legendary Artifact) | "If you would flip a coin, instead flip two coins and ignore one." | chaos | STRONG |
| Grenzo, Havoc Raiser (Legendary Creature — Goblin Rogue) | "…you may goad target creature." | chaos | STRONG |

MULLDRIFTER IS THE LOAD-BEARING ROW. Its real wording is "When this creature enters",
which the old literal ("when this enters") missed — but widening to match it would be
WORSE than the bug, because most creatures in Magic have an enters trigger and the theme
would fire on a random pile the way voltron_combat (19.35% of all cards) does. `etb` means
the cards that CARE about entering, not every card that enters. After the fix the five
rules score 213 / 430 / 460 / 168 / 124 cards and none is in the noise range.
"""
from __future__ import annotations

import re
from typing import Any

from collection_pool import rank_key

THEMES: tuple[str, ...] = (
    "tribal_dragons",
    "tribal_elves",
    "tribal_zombies",
    "tribal_humans",
    "tribal_merfolk",
    "tribal_vampires",
    "tribal_goblins",
    "tribal_soldiers",
    "tribal_warriors",
    "tribal_wizards",
    "tribal_spirits",
    "tribal_angels",
    "tribal_demons",
    "tribal_beasts",
    "tribal_dinosaurs",
    "tribal_slivers",
    "tribal_werewolves",
    "tribal_wolves",
    "tribal_knights",
    "tribal_ninjas",
    "tribal_cats",
    "auras",
    "tokens",
    "counters",
    "aristocrats",
    "reanimator",
    "spellslinger",
    "enchantress",
    "artifacts",
    "voltron",
    "draw_matters",
    "lifegain",
    "landfall",
    "graveyard",
    "etb",
    "energy",
    "chaos",
    "theft",
    "group_hug",
    "voltron_combat",
    "face_down",
    "sagas",
    "impulse",
)

NO_MATCH: int = 0
WEAK: int = 1
STRONG: int = 2

# Themes where ordering STRONG-before-WEAK is an IMPROVEMENT rather than a regression.
#
# The score is only meaningful when the WEAK tier means "is a member of the thing" and
# STRONG means "rewards the thing". That holds for the tribes: a Dragon deck genuinely
# wants Scourge of Valkas and Utvara Hellkite ahead of a generically-good Dragon, and the
# store agrees — for tribal_dragons the STRONG cards' median EDHREC rank (7003) is BETTER
# than the WEAK ones' (11488).
#
# It does NOT hold where the WEAK tier is a whole CARD TYPE, because that tier contains
# every staple. Measured over the 34k-card store:
#     artifacts    5 STRONG vs 3909 WEAK  — score-first demotes Sol Ring, Arcane Signet,
#                                           Lightning Greaves, Fellwar Stone for five
#                                           obscure "whenever an artifact enters" cards
#     voltron      4 STRONG vs 1909 WEAK  — median ranks 16700 vs 16948, i.e. noise
#     enchantress  0 STRONG                — the rule never fires at all (see below)
# so those keep the plain EDHREC ordering.
#
# For the 15 themes with no WEAK tier at all (tokens, counters, aristocrats, reanimator,
# spellslinger, draw_matters, lifegain, landfall, graveyard, etb, energy, chaos, theft,
# group_hug, voltron_combat) every match is STRONG and score-first is a no-op, so their
# absence here costs nothing.
SCORE_ORDERED: frozenset[str] = frozenset(
    t for t in THEMES if t.startswith("tribal_"))

def _wb(word: str) -> re.Pattern[str]:
    """Word-boundary match that also accepts the regular plural.

    Scryfall's o: operator is a SUBSTRING match, so o:"dragon" hits "Dragons". A bare
    \\bdragon\\b does not, because the trailing s is a word character — which made strict
    mode NARROWER than the query it reproduces and dropped 46 real tribal payoffs
    templated only in the plural (Outpost Siege "choose Khans or Dragons", Death-Priest
    of Myrkul "Skeletons, Vampires, and Zombies you control get +1/+1").

    Still bounded rather than a raw substring: plain "cat" as a substring matches
    escalate, duplicate and scatter — the false-positive class \\b exists to stop."""
    return re.compile(r"\b" + re.escape(word) + r"(?:s|es)?\b", re.IGNORECASE)

def _lit(phrase: str) -> re.Pattern[str]:
    return re.compile(re.escape(phrase), re.IGNORECASE)


def card_text(card: dict) -> str:
    parts: list[str] = []
    if "oracle_text" in card and isinstance(card.get("oracle_text"), str):
        parts.append(card["oracle_text"])
    for face in card.get("card_faces", []) or []:
        ot = face.get("oracle_text")
        if isinstance(ot, str):
            parts.append(ot)
    return "\n".join(parts)


def type_line(card: dict) -> str:
    if "type_line" in card and isinstance(card.get("type_line"), str):
        return card["type_line"]
    lines = []
    for face in card.get("card_faces", []) or []:
        tl = face.get("type_line")
        if isinstance(tl, str):
            lines.append(tl)
    return " // ".join(lines)


def subtypes(card: dict) -> set[str]:
    lines: list[str] = []
    if "type_line" in card and isinstance(card.get("type_line"), str):
        lines.append(card["type_line"])
    else:
        for face in card.get("card_faces", []) or []:
            tl = face.get("type_line")
            if isinstance(tl, str):
                lines.append(tl)
    result: set[str] = set()
    for line in lines:
        # Split FACE BY FACE first. A DFC carries a combined top-level type line
        # ("Creature — Human // Creature — Werewolf"), so splitting on the first dash
        # alone drags the back face's pre-dash words and the separator into the front
        # face's subtypes — {human, creature, werewolf}. themer.py shipped exactly this
        # bug once ("all imported cards become the same creature type"); every reader in
        # that module now splits on "//" first, and so does this one.
        for face in line.split("//"):
            parts = re.split(r"\s*[—-]\s*", face, maxsplit=1)
            if len(parts) == 2:
                for w in re.findall(r"[A-Za-z]+", parts[1]):
                    result.add(w.lower())
    return result


THEME_RULES: dict[str, dict[str, Any]] = {
    "tribal_dragons": {
        "weak_subtype": "dragon",
        "strong_alternatives": [[_wb("dragon"), _lit("you control")]],
    },
    "tribal_elves": {
        "weak_subtype": "elf",
        "strong_alternatives": [
            [_wb("elves"), _lit("you control")],
            [_wb("elf"), _lit("you control")],
        ],
    },
    "tribal_zombies": {
        "weak_subtype": "zombie",
        "strong_alternatives": [[_wb("zombie"), _lit("you control")]],
    },
    "tribal_humans": {
        "weak_subtype": "human",
        "strong_alternatives": [[_wb("human"), _lit("you control")]],
    },
    "tribal_merfolk": {
        "weak_subtype": "merfolk",
        "strong_alternatives": [[_wb("merfolk"), _lit("you control")]],
    },
    "tribal_vampires": {
        "weak_subtype": "vampire",
        "strong_alternatives": [[_wb("vampire"), _lit("you control")]],
    },
    "tribal_goblins": {
        "weak_subtype": "goblin",
        "strong_alternatives": [[_wb("goblin"), _lit("you control")]],
    },
    "tribal_soldiers": {
        "weak_subtype": "soldier",
        "strong_alternatives": [[_wb("soldier"), _lit("you control")]],
    },
    "tribal_warriors": {
        "weak_subtype": "warrior",
        "strong_alternatives": [[_wb("warrior"), _lit("you control")]],
    },
    "tribal_wizards": {
        "weak_subtype": "wizard",
        "strong_alternatives": [[_wb("wizard"), _lit("you control")]],
    },
    "tribal_spirits": {
        "weak_subtype": "spirit",
        "strong_alternatives": [[_wb("spirit"), _lit("you control")]],
    },
    "tribal_angels": {
        "weak_subtype": "angel",
        "strong_alternatives": [[_wb("angel"), _lit("you control")]],
    },
    "tribal_demons": {
        "weak_subtype": "demon",
        "strong_alternatives": [[_wb("demon"), _lit("you control")]],
    },
    "tribal_beasts": {
        "weak_subtype": "beast",
        "strong_alternatives": [[_wb("beast"), _lit("you control")]],
    },
    "tribal_dinosaurs": {
        "weak_subtype": "dinosaur",
        "strong_alternatives": [[_wb("dinosaur"), _lit("you control")]],
    },
    "tribal_slivers": {
        "weak_subtype": "sliver",
        "strong_alternatives": [[_wb("sliver"), _lit("you control")]],
    },
    "tribal_werewolves": {
        "weak_subtype": "werewolf",
        "strong_alternatives": [[_wb("werewolf")], [_wb("daybound")]],
    },
    "tribal_wolves": {
        "weak_subtype": "wolf",
        "strong_alternatives": [[_wb("wolves"), _lit("you control")]],
    },
    "tribal_knights": {
        "weak_subtype": "knight",
        "strong_alternatives": [[_wb("knight"), _lit("you control")]],
    },
    "tribal_ninjas": {
        "weak_subtype": "ninja",
        "strong_alternatives": [[_wb("ninja"), _lit("you control")]],
    },
    "tribal_cats": {
        "weak_subtype": "cat",
        "strong_alternatives": [[_wb("cat"), _lit("you control")]],
    },
    "auras": {
        "weak_type_contains": ["aura"],
        "strong_alternatives": [[_lit("whenever you cast an aura")]],
    },
    "tokens": {
        "strong_alternatives": [[_lit("create"), _lit("token")]],
    },
    "counters": {
        "strong_alternatives": [[_lit("proliferate")], [_lit("+1/+1 counter")]],
    },
    # `otag:sacrifice-outlet` carried the Scryfall query; the literal fallback left here
    # matched none of Blood Artist ("Whenever this creature or another creature dies"),
    # Zulaport Cutthroat ("...or another creature you control dies") or Viscera Seer
    # (a sacrifice OUTLET, a different signal the tag covered and the literal did not).
    # Both halves of the archetype are needed: the death PAYOFF and the outlet that
    # feeds it. "Sacrifice a creature" is required with a colon so it reads an
    # activated COST rather than a one-shot spell that happens to say the words.
    "aristocrats": {
        "strong_alternatives": [
            [_lit("creature you control dies")],
            [_lit("another creature dies")],
            [_lit("or another creature dies")],
            [_lit("whenever a creature dies")],
            [_lit("sacrifice a creature:")],
            [_lit("sacrifice another creature:")],
        ],
    },
    "reanimator": {
        "strong_alternatives": [
            [_lit("return target creature card from your graveyard")],
            [_lit("reanimate")],
        ],
    },
    "spellslinger": {
        "strong_alternatives": [
            [_lit("whenever you cast an instant")],
            [_lit("whenever you cast a sorcery")],
            # otag:magecraft is the query's third alternative. Magecraft is a printed
            # KEYWORD, so the tag's local equivalent is simply the word appearing in
            # rules text — Storm-Kiln Artist reads "Magecraft — Whenever you cast or
            # copy an instant or sorcery spell", which matches neither literal above.
            [_wb("magecraft")],
        ],
    },
    "enchantress": {
        "weak_type_contains": ["enchantment"],
        # The literal from the Scryfall query matched ZERO of the 34k-card store — no
        # printed card is templated "whenever an enchantment enters" unqualified. The
        # real wordings are "whenever you cast an enchantment spell" (Argothian
        # Enchantress, Sythis, Sigil of the Empty Throne) and "whenever an enchantment
        # you control enters". A STRONG tier that can never fire is a dead rule, so the
        # theme silently had no payoff signal at all.
        "strong_alternatives": [
            [_lit("whenever you cast an enchantment")],
            [_lit("whenever an enchantment you control enters")],
            [_lit("whenever another enchantment you control enters")],
            [_lit("whenever an enchantment enters")],
        ],
    },
    "artifacts": {
        "weak_type_contains": ["artifact"],
        "strong_alternatives": [[_lit("whenever an artifact enters")]],
    },
    "voltron": {
        "weak_type_contains": ["equipment", "aura"],
        "strong_alternatives": [[_lit("when equipped")]],
    },
    # Nekusar, the Mindrazer is the canonical draw-matters commander and its wording is
    # "Whenever a PLAYER draws a card" — the group-slug half of the archetype, which
    # neither literal reached.
    "draw_matters": {
        "strong_alternatives": [
            [_lit("whenever you draw a card")],
            [_lit("whenever a card is drawn")],
            [_lit("whenever a player draws a card")],
            [_lit("whenever an opponent draws a card")],
            [_lit("whenever you draw your second card")],
        ],
    },
    "lifegain": {
        "strong_alternatives": [[_lit("whenever you gain life")]],
    },
    # The Scryfall query's FIRST alternative is `otag:landfall`, and an oracle tag has no
    # local equivalent — so this rule was left holding only the query's literal fallback,
    # which no printed card matches. It scored exactly ONE card in the 34,846-card store,
    # and Lotus Cobra, Tatyova, Avenger of Zendikar and Scute Swarm all came back
    # NO_MATCH. Modern templating is "Whenever a land you control enters"; the pre-2024
    # wording is kept for older printings, and "Landfall —" is the printed ability word,
    # which is the most reliable signal of all. Same failure shape as `enchantress` and
    # `magecraft` above.
    "landfall": {
        "strong_alternatives": [
            [_wb("landfall")],
            [_lit("a land you control enters")],
            [_lit("whenever a land enters the battlefield under your control")],
        ],
    },
    "graveyard": {
        "strong_alternatives": [[_lit("from your graveyard")], [_lit("flashback")]],
    },
    # PAYOFFS ONLY, never "this card has an ETB". `otag:etb` carried the query and the
    # literal fallback ("when this enters") matches neither Mulldrifter nor Cloudblazer,
    # whose real wording is "When this creature enters". But widening to THAT would be
    # worse than the bug: most creatures in Magic have an enters trigger, so the theme
    # would fire on a random pile the way voltron_combat (19.35% of all cards) does — see
    # deck_themes.BASE_RATE. What makes a deck an ETB deck is the cards that CARE:
    # repeatable blink and "whenever a creature you control enters" triggers.
    "etb": {
        "strong_alternatives": [
            [_lit("whenever a creature you control enters")],
            [_lit("whenever another creature you control enters")],
            [_lit("whenever a creature enters the battlefield under your control")],
            [_lit("whenever a nontoken creature enters")],
            [_lit("exile it, then return")],
            [_lit("exile them, then return")],
            [_lit("exile that card, then return")],
        ],
    },
    "energy": {
        "strong_alternatives": [[_lit("energy counter")], [_lit("{e}")]],
    },
    # The one theme whose SCRYFALL QUERY is broken too — it has no otag: alternative to
    # fall back on, only `(o:"each player" o:"random")`, which misses coin flips, voting
    # and goad entirely. Krark's Thumb and Grenzo, Havoc Raiser both scored NO_MATCH.
    # These mirror commander_analysis.THEME_PATTERNS["chaos"], which had the right list
    # all along; the conjunction is kept as one alternative among many.
    "chaos": {
        "strong_alternatives": [
            [_lit("flip a coin")],
            [_lit("at random")],
            [_lit("will of the council")],
            [_wb("vote")],
            [_wb("goad")],
            [_lit("each player"), _lit("random")],
        ],
    },
    "theft": {
        "strong_alternatives": [[_lit("gain control")], [_lit("under your control until end of turn")]],
    },
    "group_hug": {
        "strong_alternatives": [[_lit("each player draws")], [_lit("each player gains")]],
    },
    "voltron_combat": {
        "strong_type_required": "creature",
        "strong_alternatives": [
            [_lit("double strike")],
            [_lit("trample")],
            [_lit("first strike")],
            [_lit("menace")],
            [_lit("flying")],
            [_lit("additional combat phase")],
            [_lit("an additional combat")],
            [_lit("whenever this creature attacks")],
            [_lit("whenever it attacks")],
        ],
    },
    # ── Themes added 2026-08-14 to close measured holes in the taxonomy ───────────
    # Each mirrors its THEME_SYNERGY_QUERIES entry, so strict/collection mode fills the
    # same theme slots the Scryfall path would.
    "face_down": {
        # No WEAK tier on purpose. "Face down" is not a card type you can be a member of
        # — a card either interacts with the mechanic or it does not, so there is no
        # "is a face-down card" analogue to a tribe's bodies.
        "strong_alternatives": [
            [_lit("morph")],            # also catches megamorph as a substring
            [_lit("manifest")],
            [_lit("disguise")],
            [_lit("face-down creature")],
            [_lit("turn it face up")],
        ],
    },
    "sagas": {
        # The WEAK tier is very nearly DEAD, and that is fine: measured over the 34,846-card
        # store this rule gives 262 STRONG against 2 WEAK, because a Saga's own reminder
        # text ("...add a lore counter...") makes essentially every Saga STRONG on its own.
        # The type check is kept only as the safety net for those 2 — it costs nothing.
        # NOT added to SCORE_ORDERED: score-first only helps where a real WEAK tier of
        # bodies exists to sort payoffs ahead of, and here there is no such tier.
        "weak_type_contains": ["saga"],
        "strong_alternatives": [
            [_lit("lore counter")],
            [_wb("saga"), _lit("you control")],
        ],
    },
    "impulse": {
        "strong_alternatives": [
            [_lit("exile the top")],
            [_lit("play the top card of your library")],
            [_lit("you may play that card")],
            [_lit("you may cast that card")],
        ],
    },
}


def theme_score(card: dict, theme: str) -> int:
    rule = THEME_RULES.get(theme)
    if rule is None:
        return NO_MATCH
    text = card_text(card)
    tl = type_line(card).lower()
    subs = subtypes(card)

    strong_alts = rule.get("strong_alternatives")
    if strong_alts:
        req_type = rule.get("strong_type_required")
        if req_type:
            if req_type in tl:
                if any(all(p.search(text) for p in alt) for alt in strong_alts):
                    return STRONG
        else:
            if any(all(p.search(text) for p in alt) for alt in strong_alts):
                return STRONG

    weak_sub = rule.get("weak_subtype")
    if weak_sub and weak_sub in subs:
        # UPGRADE, not a wider match. A card already in the tribe by type whose rules
        # text also names the tribe is a payoff, not a vanilla body — Bladewing the
        # Risen's "{B}{R}: Dragon creatures get +1/+1" never says "you control", so the
        # strong_alternatives conjunction misses it and it would rank below every
        # random Dragon. Scryfall provided no ordering here at all (it sorted purely by
        # EDHREC), so refining the order cannot pull in a card the query would have
        # excluded: this branch is reached ONLY for cards that already matched.
        return STRONG if _wb(weak_sub).search(text) else WEAK
    weak_types = rule.get("weak_type_contains")
    if weak_types:
        for w in weak_types:
            if w in tl:
                return WEAK
    return NO_MATCH


def match_themes(cards: list[dict], themes: list[str]) -> dict[str, list[dict]]:
    """theme -> matching cards, STRONG before WEAK then by shared rank_key.

    The score is the primary sort and rank_key breaks ties, so a genuine payoff
    outranks a vanilla tribe member — the ordering Scryfall never provided, since it
    sorted purely by EDHREC."""
    out: dict[str, list[dict]] = {}
    for theme in themes:
        scored = [(theme_score(c, theme), c) for c in cards]
        matched = [(s, c) for s, c in scored if s != NO_MATCH]
        matched.sort(key=lambda item: (-item[0],) + rank_key(item[1]))
        out[theme] = [c for _, c in matched]
    return out
