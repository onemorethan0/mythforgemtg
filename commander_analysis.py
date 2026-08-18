"""
Parses a Scryfall card object for a commander and extracts:
- Color identity
- Keyword abilities
- Mechanical themes (used to steer synergy card selection)
"""
import re
from dataclasses import dataclass, field
from typing import Optional


# ── Theme detection ──────────────────────────────────────────────────────────
# Each theme maps to a list of oracle-text substrings. If any substring appears
# in the commander's oracle text, the theme is flagged. Order matters for display.

THEME_PATTERNS: dict[str, list[str]] = {
    # Creature tribes
    "tribal_dragons":   ["dragon"],
    "tribal_elves":     ["elf ", "elves"],
    "tribal_zombies":   ["zombie"],
    # "human" alone false-matched transform text like "Human Werewolves" and token
    # makers — require collective/payoff phrasing so it means actual Human tribal.
    "tribal_humans":    ["humans you control", "other human", "human creature", "nonhuman"],
    "tribal_merfolk":   ["merfolk"],
    "tribal_vampires":  ["vampire"],
    "tribal_goblins":   ["goblin"],
    "tribal_soldiers":  ["soldier"],
    "tribal_warriors":  ["warrior"],
    "tribal_wizards":   ["wizard"],
    "tribal_spirits":   ["spirit"],
    "tribal_angels":    ["angel"],
    "tribal_demons":    ["demon"],
    "tribal_beasts":    ["beast"],
    "tribal_dinosaurs": ["dinosaur"],
    "tribal_slivers":   ["sliver"],
    "tribal_werewolves":["werewol"],
    "tribal_wolves":    ["wolves", "wolf "],
    # Mechanical archetypes
    "tokens":           ["create", "token", "populate", "amass", "fabricate"],
    "counters":         ["+1/+1 counter", "proliferate", "put a counter on", "-1/-1 counter",
                         # DOUBLING counters is a counters payoff without placing any — Vorel of
                         # the Hull Clade, an archetypal counters commander, matched nothing.
                         # "counter on target" would also catch it but touches 2.3% of legends
                         # for the same one rescue, so the narrow literal wins.
                         "each kind of counter"],
    "aristocrats":      ["sacrifice a", "creature you control dies",
                         "another creature dies", "whenever a creature dies",
                         "dies, ", "pay life",
                         # Magic's other spelling for "dies" (Agent of the Iron Throne), and
                         # a sacrifice outlet that takes a variable number (Baba Lysaga).
                         # "sacrifice another" was measured and DROPPED: 0 rescues against
                         # 80 legends touched.
                         "is put into a graveyard from the battlefield", "sacrifice up to"],
    "reanimator":       ["from your graveyard", "in your graveyard",
                         "return it to the battlefield", "return target creature card",
                         "reanimate", "from a graveyard to the battlefield"],
    "spellslinger":     ["whenever you cast an instant", "whenever you cast a sorcery",
                         "instant or sorcery spell", "magecraft",
                         # Cost reduction IS the spellslinger payoff — Baral, Chief of
                         # Compliance detected nothing without this.
                         "instant and sorcery spells you cast",
                         # Prowess is a noncreature-spell payoff by definition, so a commander
                         # with it wants a spell deck (Narset, Enlightened Exile; Thor Odinson).
                         "prowess"],
    "enchantress":      ["whenever an enchantment enters", "whenever you cast an enchantment",
                         # Was "enchantment enters the battlefield", which matched ZERO of the
                         # 34,179 cards in the pool — Scryfall re-templates old cards to the
                         # modern Oracle wording, so the pre-2024 phrasing exists nowhere.
                         # The replacement matches 63.
                         "enchantment you control enters",
                         # Tuvasa the Sunlit — the archetype's poster commander — matched none
                         # of the three above: it counts enchantments ("for each enchantment you
                         # control") and triggers on "your FIRST enchantment spell each turn".
                         "enchantment you control", "enchantment spell", "enchantment cards",
                         # Singular. **Zur the Enchanter** — the archetype's namesake — tutors
                         # "an enchantment card" and detected NOTHING before this.
                         "an enchantment card"],
    "artifacts":        ["whenever an artifact enters", "whenever you cast an artifact",
                         "artifact you control",
                         # Plural and the artifact-creature phrasing: Alibou, Ancient Witness
                         # ("other artifact creatures you control") detected nothing, and
                         # "an artifact card" catches artifact tutoring (Tony Stark).
                         "artifacts you control", "artifact creatures you control",
                         "an artifact card",
                         # Singular card-type references: Szarekh mills for an "artifact creature
                         # card", Tannuk grants warp to "Artifact cards ... in your hand".
                         "artifact creature card", "artifact cards",
                         # Artifact ABILITIES and artifact ETB, both payoff-shaped (Kurkesh,
                         # Ashnod the Uncaring, Akal Pakal).
                         "ability of an artifact", "an artifact entered"],
    "voltron":          ["equip", "equipped creature", "attach", "aura attached"],
    "auras":            ["aura", "enchant creature", "enchanted creature"],
    "tribal_knights":   ["knight"],
    "tribal_ninjas":    ["ninja"],
    "tribal_cats":      ["cats", "cat creature"],
    "draw_matters":     ["whenever you draw a card", "draw a card for each",
                         "whenever a card is drawn"],
    "lifegain":         ["whenever you gain life", "each life you gain",
                         "whenever you gain 1 or more life",
                         # PAYOFF phrasings only. The ensemble surfaced a 33-card "lifegain"
                         # cluster here, and most of it was `lifelink` (49 rescues, 5.0% of
                         # legends) and "you gain N life" (44, 5.8%) — which identify lifegain
                         # SOURCES, not payoffs. Filing those as a theme would spend 20 theme
                         # slots on bodies that happen to gain life, which is precisely the
                         # measured reason `big_mana` was dropped. These two pay you FOR the
                         # life: 6 rescues between them, 0.6% of the pool.
                         "life you gained", "extort"],
    # "whenever a land enters the battlefield under your control" was here and matched ONE
    # card in the whole pool; "land you control enters" below matches 185.
    "landfall":         ["landfall",
                         # The gap CLAUDE.md already flagged: extra land drops are the enabler
                         # half of the archetype (Flubs, the Fool detected nothing).
                         "additional land",
                         # 2024 TEMPLATING. Cards now print "a land you control enters", not
                         # "a land enters the battlefield under your control" — the same change
                         # that killed five theme_match rules. Tatyova, Steward of Tides and
                         # Nissa, Vastwood Seer both read as themeless without this.
                         "land you control enters"],
    "graveyard":        ["from your graveyard", "graveyard into your hand",
                         "when this card is put into your graveyard",
                         "flashback", "unearth", "delve",
                         # Graveyards as a shared RESOURCE, and deliberate self-mill —
                         # Coram, the Undertaker detected nothing without these.
                         "in all graveyards", "each player mills"],
    # "whenever a creature enters the battlefield under your control" was here and matched
    # TWO cards; "creature you control enters" below matches 244.
    "etb":              ["whenever a creature you control enters",
                         "whenever another creature you control enters",
                         "whenever a nontoken creature enters",
                         "exile it, then return", "exile them, then return",
                         "exile that card, then return", "flicker", "blink",
                         # Modern ETB templating without the "whenever" prefix, so conditional
                         # and delayed forms match too (Elrond, Clement, Frodo Baggins).
                         "creature you control enters"],
    "energy":           ["energy counter", "gain {e}", "{e},"],
    "chaos":            ["flip a coin", "at random", "will of the council", "votes", "goad"],
    "theft":            ["gain control", "under your control until end of turn"],
    "group_hug":        ["each player draws", "each player gains"],
    # Face-down matters (morph / manifest / disguise / cloak). Added because the
    # taxonomy had NO entry for it at all: Kadena, Slinking Sorcerer — a commander
    # whose whole text is about face-down creatures — detected zero themes, so her
    # ~20 theme slots fell through to generic goodstuff.
    "face_down":        ["face down", "face-down", "manifest", "morph",
                         "turned face up", "disguise", "cloak"],
    "sagas":            ["saga", "lore counter"],
    # Impulse draw: play cards you do not own yet, off the top or from exile. The
    # widest genuine gap — 26 of 381 corpus commanders (6.8%), 10 of them previously
    # themeless. Deliberately NOT "you may play", which is far too broad.
    "impulse":          ["exile the top", "exiles the top", "play the top card",
                         "from the top of your library", "play cards from the top",
                         "you may play that card", "you may cast that card",
                         # Reveal-and-cast off the top is impulse even without the word "exile"
                         # (Yennett, Cryptic Sovereign). Kept as a long literal on purpose —
                         # "reveal the top card" alone is far too broad.
                         "reveal the top card of your library. you may cast"],
    "voltron_combat":   ["first strike", "double strike", "trample", "unblockable",
                         "can't be blocked", "whenever a creature attacks",
                         "whenever a creature you control attacks", "attacking causes",
                         "deals combat damage to a player", "additional combat phase",
                         "whenever one or more creatures you control attack"],
}

THEME_LABELS: dict[str, str] = {
    "tribal_dragons":   "Dragon Tribal",
    "tribal_elves":     "Elf Tribal",
    "tribal_zombies":   "Zombie Tribal",
    "tribal_humans":    "Human Tribal",
    "tribal_merfolk":   "Merfolk Tribal",
    "tribal_vampires":  "Vampire Tribal",
    "tribal_goblins":   "Goblin Tribal",
    "tribal_soldiers":  "Soldier Tribal",
    "tribal_warriors":  "Warrior Tribal",
    "tribal_wizards":   "Wizard Tribal",
    "tribal_spirits":   "Spirit Tribal",
    "tribal_angels":    "Angel Tribal",
    "tribal_demons":    "Demon Tribal",
    "tribal_beasts":    "Beast Tribal",
    "tribal_dinosaurs": "Dinosaur Tribal",
    "tribal_slivers":   "Sliver Tribal",
    "tribal_werewolves":"Werewolf Tribal",
    "tribal_wolves":    "Wolf Tribal",
    "tribal_knights":   "Knight Tribal",
    "tribal_ninjas":    "Ninja Tribal",
    "tribal_cats":      "Cat Tribal",
    "auras":            "Auras / Enchantress",
    "tokens":           "Token / Go-Wide",
    "counters":         "Counters / Proliferate",
    "aristocrats":      "Aristocrats / Sacrifice",
    "reanimator":       "Reanimator / Graveyard",
    "spellslinger":     "Spellslinger",
    "enchantress":      "Enchantress",
    "artifacts":        "Artifacts / Affinity",
    "voltron":          "Voltron / Equipment",
    "draw_matters":     "Draw Matters",
    "lifegain":         "Lifegain",
    "landfall":         "Landfall",
    "graveyard":        "Graveyard Value",
    "etb":              "ETB / Blink",
    "energy":           "Energy",
    "chaos":            "Chaos / Politics",
    "theft":            "Control / Theft",
    "group_hug":        "Group Hug",
    "voltron_combat":   "Combat / Evasion",
    "face_down":        "Face-Down / Morph",
    "sagas":            "Sagas",
    "impulse":          "Impulse Draw",
}

# Per-theme Scryfall search fragments (appended to the base color-identity query)
THEME_SYNERGY_QUERIES: dict[str, str] = {
    # Each tribal query pulls the creatures of that type AND the non-creature
    # payoffs that reward it (anthems, cost-reducers, "Xs you control …"), so a
    # tribal deck gets its lords/support — not just a pile of bodies.
    "tribal_dragons":   '(type:dragon OR (o:"dragon" o:"you control"))',
    "tribal_elves":     '(type:elf OR (o:"elves" o:"you control") OR (o:"elf" o:"you control"))',
    "tribal_zombies":   '(type:zombie OR (o:"zombie" o:"you control"))',
    "tribal_humans":    '(type:human OR (o:"human" o:"you control"))',
    "tribal_merfolk":   '(type:merfolk OR (o:"merfolk" o:"you control"))',
    "tribal_vampires":  '(type:vampire OR (o:"vampire" o:"you control"))',
    "tribal_goblins":   '(type:goblin OR (o:"goblin" o:"you control"))',
    "tribal_soldiers":  '(type:soldier OR (o:"soldier" o:"you control"))',
    "tribal_warriors":  '(type:warrior OR (o:"warrior" o:"you control"))',
    "tribal_wizards":   '(type:wizard OR (o:"wizard" o:"you control"))',
    "tribal_spirits":   '(type:spirit OR (o:"spirit" o:"you control"))',
    "tribal_angels":    '(type:angel OR (o:"angel" o:"you control"))',
    "tribal_demons":    '(type:demon OR (o:"demon" o:"you control"))',
    "tribal_beasts":    '(type:beast OR (o:"beast" o:"you control"))',
    "tribal_dinosaurs": '(type:dinosaur OR (o:"dinosaur" o:"you control"))',
    "tribal_slivers":   '(type:sliver OR (o:"sliver" o:"you control"))',
    "tribal_werewolves":'(type:werewolf OR o:"werewolf" OR o:"daybound")',
    "tribal_wolves":    '(type:wolf OR (o:"wolves" o:"you control"))',
    "tribal_knights":   '(type:knight OR (o:"knight" o:"you control"))',
    "tribal_ninjas":    '(type:ninja OR (o:"ninja" o:"you control") OR otag:ninjutsu)',
    "tribal_cats":      '(type:cat OR (o:"cat" o:"you control"))',
    "auras":            '(type:aura OR otag:enchantress OR o:"whenever you cast an aura")',
    # WRAPPED IN PARENS, and that is load-bearing: DeckBuilder appends `id<=WUBRG`,
    # `legal:commander` and `-type:land` to these, and Scryfall's OR binds LOOSER than the
    # implicit AND. Without the wrapper the filters apply to the LAST branch only, leaving
    # the first branch completely unconstrained — a Shelob (BG) build drafted Professional
    # Face-Breaker ({2}{R}) straight out of `otag:sacrifice-outlet`, which then demanded 14
    # red sources the deck could never have.
    "tokens":           '(otag:token-producer OR (o:"create" o:"token"))',
    "counters":         '(otag:counter-manipulation OR o:"proliferate" OR o:"+1/+1 counter")',
    "aristocrats":      '(otag:sacrifice-outlet OR o:"whenever a creature you control dies")',
    "reanimator":       '(o:"return target creature card from your graveyard" OR o:"reanimate")',
    "spellslinger":     '(o:"whenever you cast an instant" OR o:"whenever you cast a sorcery" OR otag:magecraft)',
    "enchantress":      '(type:enchantment OR o:"whenever an enchantment enters")',
    "artifacts":        '(type:artifact OR o:"whenever an artifact enters")',
    "voltron":          '(type:equipment OR type:aura OR o:"when equipped")',
    "draw_matters":     '(o:"whenever you draw a card" OR o:"whenever a card is drawn")',
    "lifegain":         '(otag:lifegain-payoff OR o:"whenever you gain life")',
    "landfall":         '(otag:landfall OR o:"whenever a land enters the battlefield under your control")',
    "graveyard":        '(otag:graveyard-recursion OR o:"from your graveyard" OR o:"flashback")',
    "etb":              '(otag:etb OR o:"when this enters" OR o:"whenever a creature enters")',
    "energy":           '(o:"energy counter" OR o:"{e}")',
    "chaos":            '(o:"each player" o:"random")',
    "theft":            '(o:"gain control" OR o:"under your control until end of turn")',
    "group_hug":        '(o:"each player draws" OR o:"each player gains")',
    "face_down":        '(o:"morph" OR o:"megamorph" OR o:"manifest" OR o:"disguise" '
                        'OR o:"face-down creature" OR o:"turn it face up")',
    "sagas":            '(type:saga OR o:"lore counter")',
    "impulse":          '(o:"exile the top" OR o:"play the top card of your library" '
                        'OR o:"you may play that card" OR o:"you may cast that card")',
    # Combat/Evasion is a CREATURE theme (you need attackers). It used to lead
    # with type:equipment, which flooded combat commanders (e.g. Aurelia) with
    # Equipment artifacts and almost no creatures — equipment is covered by the
    # separate "voltron" theme. Constrain to creatures with combat/evasion text.
    "voltron_combat":   'type:creature (o:"double strike" OR o:"trample" OR o:"first strike" '
                        'OR o:"menace" OR o:"flying" OR o:"additional combat phase" '
                        'OR o:"an additional combat" OR o:"whenever this creature attacks" '
                        'OR o:"whenever it attacks")',
}


# ── Commander profile ─────────────────────────────────────────────────────────

@dataclass
class CommanderProfile:
    name: str
    color_identity: list[str]      # e.g. ["U", "B"]
    oracle_text: str
    keywords: list[str]            # official MTG keyword abilities
    themes: list[str]              # detected theme keys
    mana_value: float
    type_line: str
    card: dict = field(repr=False) # raw Scryfall card object

    @property
    def color_id_str(self) -> str:
        """Joined color letters, e.g. 'UB'. Empty string = colorless."""
        return "".join(self.color_identity)

    @property
    def is_colorless(self) -> bool:
        return len(self.color_identity) == 0

    @property
    def is_mono(self) -> bool:
        return len(self.color_identity) == 1

    def theme_labels(self) -> list[str]:
        return [THEME_LABELS.get(t, t) for t in self.themes]


def _oracle_without_self_name(card: dict) -> str:
    """Oracle text with the card's OWN printed name removed, lowercased.

    Magic prints a card's name inside its own rules text, so a tribe word that is merely part
    of the name matched as if it were a payoff: **21 of 558 legendary-creature tribal
    detections (3.8%) fired on the name alone** — The Unknown Wizard read as Wizard tribal,
    Winter Soldier as Soldier tribal, Green Goblin as Goblin tribal, Questing Beast and
    Skanos, Dragon Vassal likewise. Each one spends a commander's ~20 theme slots on a tribe
    the deck has no payoff for, which is the same defect class as reading the TYPE LINE that
    this function's docstring already refuses to do.

    Both the full name and the pre-comma short name are stripped, because rules text uses the
    short form ("Skanos deals 2 damage"), and each face of a multi-face card contributes its
    own name.
    """
    text = card.get("oracle_text") or ""
    for face in (card.get("name") or "").split(" // "):
        for form in (face, face.split(",")[0]):
            form = form.strip()
            if len(form) > 2:                 # never strip a 1-2 char token; too collision-prone
                text = re.sub(re.escape(form), " ", text, flags=re.I)
    return text.lower()


def _detect_themes(card: dict) -> list[str]:
    """Detect strategic themes from the commander's ORACLE TEXT only.

    Deliberately does NOT read the type line: a commander being a "Human Knight"
    or "Phyrexian Angel" doesn't make the deck Human- or Angel-tribal — that mis-
    identified Syr Gwyn as Humans, Atraxa as Angels, Yuriko as Humans, etc. A real
    tribal/archetype commander names its payoff in the rules text ("other Goblins
    you control", "whenever you cast an Aura", "proliferate"), so oracle-only
    detection both kills those false tribals and still catches the true strategy.
    """
    oracle = _oracle_without_self_name(card)

    found: list[str] = []
    for theme, patterns in THEME_PATTERNS.items():
        for pat in patterns:
            if pat in oracle:
                found.append(theme)
                break
    return found


# ── Who may share a command zone ─────────────────────────────────────────────
# Rule 903.10 and friends. Kept as data + one predicate because an illegal pair must be
# REFUSED, not built: a deck that cannot be registered is worse than one the user has to
# fix, and the identity of the zone drives colour filtering for all 99 other cards.

PARTNER_PLAIN = "partner"                 # "Partner" — pairs with any other plain Partner
PARTNER_WITH = "partner_with"             # "Partner with <name>" — that ONE card only
FRIENDS_FOREVER = "friends_forever"       # pairs with any other Friends forever
BACKGROUND_CHOOSER = "choose_background"  # pairs with a Background enchantment
BACKGROUND = "background"                 # the Background itself
DOCTOR_COMPANION = "doctors_companion"    # pairs with a Doctor
DOCTOR = "doctor"


def partner_mechanic(card: dict) -> str | None:
    """Which command-zone pairing mechanic this card has, if any.

    Read from oracle text and type line, never from a curated name list — a name list goes
    stale with every set, and this has to be right for cards printed after today.
    """
    text = (card.get("oracle_text") or "").lower()
    type_line = (card.get("type_line") or "").lower()

    if "background" in type_line:
        return BACKGROUND
    if "choose a background" in text:
        return BACKGROUND_CHOOSER
    if "friends forever" in text:
        return FRIENDS_FOREVER
    if "doctor's companion" in text:
        return DOCTOR_COMPANION
    # "Partner with X" is a DIFFERENT mechanic from bare "Partner" and must be tested first,
    # because its reminder text contains the word "partner" too.
    if "partner with" in text:
        return PARTNER_WITH
    if re.search(r"\bpartner\b", text):
        return PARTNER_PLAIN
    # A Doctor is only a pairing card in the presence of a companion, so it is reported last
    # and only when it is actually a Doctor creature.
    if "doctor" in type_line and "time lord" in type_line:
        return DOCTOR
    return None


def _partner_with_target(card: dict) -> str:
    m = re.search(r"partner with ([^\n(]+)", (card.get("oracle_text") or ""), re.I)
    return m.group(1).strip().rstrip(".").casefold() if m else ""


def can_pair(lead: dict, second: dict) -> tuple[bool, str]:
    """Whether these two may share a command zone. Returns (ok, reason-if-not).

    The reason is user-facing, so it names the actual rule rather than saying "invalid".
    """
    a, b = partner_mechanic(lead), partner_mechanic(second)
    if a is None or b is None:
        missing = lead if a is None else second
        return False, (f"{missing.get('name', 'That card')} has no partner ability, so it "
                       f"can't share a command zone.")
    if (lead.get("name") or "").casefold() == (second.get("name") or "").casefold():
        return False, "A commander can't partner with itself."

    pair = {a, b}
    if pair == {PARTNER_PLAIN}:
        return True, ""
    if pair == {FRIENDS_FOREVER}:
        return True, ""
    if pair == {BACKGROUND_CHOOSER, BACKGROUND}:
        return True, ""
    if pair == {DOCTOR_COMPANION, DOCTOR}:
        return True, ""
    if PARTNER_WITH in pair:
        # Must name each other. Checking only one direction would admit a one-way pairing,
        # which does not exist.
        want_a, want_b = _partner_with_target(lead), _partner_with_target(second)
        name_a = (lead.get("name") or "").split(" // ")[0].casefold()
        name_b = (second.get("name") or "").split(" // ")[0].casefold()
        if want_a == name_b and want_b == name_a:
            return True, ""
        named = _partner_with_target(lead) or _partner_with_target(second)
        return False, (f"That's a “Partner with” card — it pairs only with "
                       f"{named.title() or 'its named partner'}.")
    return False, (f"{lead.get('name', 'This commander')} and "
                   f"{second.get('name', 'that card')} have different partner abilities, "
                   f"so they can't be paired.")


def command_zone_identity(card: dict, partners: list[dict] | None = None) -> list[str]:
    """The colour identity of the whole COMMAND ZONE, not just one card.

    A partner pair's identity is the UNION — Tymna the Weaver (BW) beside Thrasios, Triton
    Hero (GU) is a BGUW deck. Reading one half is not an approximation, it is a different
    deck, and everything downstream that filters by identity then filters out real cards:
    `deck_quality.assess_colors` reported an imported Sam + Frodo deck as short FIFTEEN
    black sources while the list actually contained thirty-two, because black was outside
    the half-identity it was given. Every partner deck measured flipped from ok=False to
    ok=True once the union was used, so this was a pure false alarm shown to users.

    Sorted for determinism; WUBRG order is not preserved (nothing downstream depends on
    it, and `assess_colors` keys by colour).
    """
    identity = set(card.get("color_identity") or [])
    for partner in partners or []:
        identity |= set(partner.get("color_identity") or [])
    return sorted(identity)


def build_commander_profile(card: dict,
                            partners: list[dict] | None = None) -> CommanderProfile:
    """Profile the command zone. `partners` covers partner / partner-with / background.

    Themes are the union across the zone: a partner pair's plan comes from BOTH halves,
    and the lead card's themes stay FIRST so `_theme_slot_split` still weights the
    commander the deck is named for. Mana value stays the lead card's — it drives the
    land count and reference curve, which the second commander does not change.
    """
    themes = list(_detect_themes(card))
    for partner in partners or []:
        for theme in _detect_themes(partner):
            if theme not in themes:
                themes.append(theme)
    return CommanderProfile(
        name=card["name"],
        color_identity=command_zone_identity(card, partners),
        oracle_text=card.get("oracle_text", ""),
        keywords=card.get("keywords", []),
        themes=themes,
        mana_value=float(card.get("cmc", 0)),
        type_line=card.get("type_line", ""),
        card=card,
    )
