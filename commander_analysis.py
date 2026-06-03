"""
Parses a Scryfall card object for a commander and extracts:
- Color identity
- Keyword abilities
- Mechanical themes (used to steer synergy card selection)
"""
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
    "counters":         ["+1/+1 counter", "proliferate", "put a counter on", "-1/-1 counter"],
    "aristocrats":      ["sacrifice a", "creature you control dies",
                         "another creature dies", "whenever a creature dies",
                         "dies, ", "pay life"],
    "reanimator":       ["from your graveyard", "in your graveyard",
                         "return it to the battlefield", "return target creature card",
                         "reanimate", "from a graveyard to the battlefield"],
    "spellslinger":     ["whenever you cast an instant", "whenever you cast a sorcery",
                         "instant or sorcery spell", "magecraft"],
    "enchantress":      ["whenever an enchantment enters", "whenever you cast an enchantment",
                         "enchantment enters the battlefield"],
    "artifacts":        ["whenever an artifact enters", "whenever you cast an artifact",
                         "artifact you control"],
    "voltron":          ["equip", "equipped creature", "attach", "aura attached"],
    "auras":            ["aura", "enchant creature", "enchanted creature"],
    "tribal_knights":   ["knight"],
    "tribal_ninjas":    ["ninja"],
    "tribal_cats":      ["cats", "cat creature"],
    "draw_matters":     ["whenever you draw a card", "draw a card for each",
                         "whenever a card is drawn"],
    "lifegain":         ["whenever you gain life", "each life you gain",
                         "whenever you gain 1 or more life"],
    "landfall":         ["whenever a land enters the battlefield under your control",
                         "landfall"],
    "graveyard":        ["from your graveyard", "graveyard into your hand",
                         "when this card is put into your graveyard",
                         "flashback", "unearth", "delve"],
    "etb":              ["whenever a creature you control enters",
                         "whenever another creature you control enters",
                         "whenever a creature enters the battlefield under your control",
                         "whenever a nontoken creature enters",
                         "exile it, then return", "exile them, then return",
                         "exile that card, then return", "flicker", "blink"],
    "energy":           ["energy counter", "gain {e}", "{e},"],
    "chaos":            ["flip a coin", "at random", "will of the council", "votes", "goad"],
    "theft":            ["gain control", "under your control until end of turn"],
    "group_hug":        ["each player draws", "each player gains"],
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
    "tokens":           'otag:token-producer OR (o:"create" o:"token")',
    "counters":         'otag:counter-manipulation OR o:"proliferate" OR o:"+1/+1 counter"',
    "aristocrats":      'otag:sacrifice-outlet OR o:"whenever a creature you control dies"',
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
    "voltron_combat":   '(type:equipment OR o:"double strike" OR o:"trample" OR o:"hexproof")',
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


def _detect_themes(card: dict) -> list[str]:
    """Detect strategic themes from the commander's ORACLE TEXT only.

    Deliberately does NOT read the type line: a commander being a "Human Knight"
    or "Phyrexian Angel" doesn't make the deck Human- or Angel-tribal — that mis-
    identified Syr Gwyn as Humans, Atraxa as Angels, Yuriko as Humans, etc. A real
    tribal/archetype commander names its payoff in the rules text ("other Goblins
    you control", "whenever you cast an Aura", "proliferate"), so oracle-only
    detection both kills those false tribals and still catches the true strategy.
    """
    oracle = (card.get("oracle_text") or "").lower()

    found: list[str] = []
    for theme, patterns in THEME_PATTERNS.items():
        for pat in patterns:
            if pat in oracle:
                found.append(theme)
                break
    return found


def build_commander_profile(card: dict) -> CommanderProfile:
    return CommanderProfile(
        name=card["name"],
        color_identity=card.get("color_identity", []),
        oracle_text=card.get("oracle_text", ""),
        keywords=card.get("keywords", []),
        themes=_detect_themes(card),
        mana_value=float(card.get("cmc", 0)),
        type_line=card.get("type_line", ""),
        card=card,
    )
