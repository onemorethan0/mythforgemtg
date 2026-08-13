# SPEC — `theme_match.py`

Write ONE new Python file: `theme_match.py`, at the repo root of Myth Forge.

**Self-contained, pure, offline.** Standard library only (`re`, `typing`). **No network.
No imports from any other project module.**

Output **only the contents of `theme_match.py`**, in a single ```python fenced block.
No prose. `/no_think`

---

## 1. Why this module exists

Myth Forge reserves ~20 of a deck's 99 slots for **theme synergy** — the cards that make a
Dragon deck a Dragon deck rather than on-colour goodstuff. Those slots are filled by
Scryfall search (`commander_analysis.THEME_SYNERGY_QUERIES`, reproduced in §3).

The new strict "build only from cards I own" mode has **no Scryfall search**, so it cannot
run those queries at all. Today it skips the theme step entirely and hands those ~20 slots
to the generic goodstuff fill — a strict Dragon deck gets no Dragon payoffs beyond whatever
happens to rank well. This module replaces that search with local matching over the owned
card pool.

**Your job is to reproduce the SEMANTICS of the queries in §3 using only a card's
`type_line` and `oracle_text`.**

---

## 2. Card dict shape (VERIFIED — do not invent fields)

```python
{
  "name": "Bladewing the Risen",
  "type_line": "Legendary Creature — Zombie Dragon",
  "oracle_text": "Flying\nWhen Bladewing enters, you may return target Dragon permanent "
                 "card from your graveyard to the battlefield.\n{B}{R}: Dragon creatures "
                 "get +1/+1 until end of turn",
  "edhrec_rank": 3605,             # may be absent or None
  "card_faces": [ {...}, {...} ],  # split/DFC/adventure ONLY
}
```

`oracle_text` and `type_line` may be **absent at the top level** and present only inside
`card_faces[]`. Every read must consider both faces.

The em-dash in a type line is `—` (U+2014), not a hyphen. Some sources use ` - `. Handle
both. Subtypes are the words AFTER the dash: `Legendary Creature — Zombie Dragon` has
subtypes `Zombie` and `Dragon`.

---

## 3. The queries you are reproducing

These are Scryfall queries. `o:"x"` is a **case-insensitive substring** match on oracle
text. `type:x` matches the type line. `(o:"a" o:"b")` means both substrings appear
**anywhere** in the text — it is co-occurrence, NOT adjacency. `otag:x` is a community tag
with **no local equivalent** — where a query offers `otag:` OR an oracle alternative, use
only the oracle alternative; where a query is `otag:` alone, use the closest oracle-text
approximation you can justify and say so in a comment.

```
tribal_dragons    (type:dragon OR (o:"dragon" o:"you control"))
tribal_elves      (type:elf OR (o:"elves" o:"you control") OR (o:"elf" o:"you control"))
tribal_zombies    (type:zombie OR (o:"zombie" o:"you control"))
tribal_humans     (type:human OR (o:"human" o:"you control"))
tribal_merfolk    (type:merfolk OR (o:"merfolk" o:"you control"))
tribal_vampires   (type:vampire OR (o:"vampire" o:"you control"))
tribal_goblins    (type:goblin OR (o:"goblin" o:"you control"))
tribal_soldiers   (type:soldier OR (o:"soldier" o:"you control"))
tribal_warriors   (type:warrior OR (o:"warrior" o:"you control"))
tribal_wizards    (type:wizard OR (o:"wizard" o:"you control"))
tribal_spirits    (type:spirit OR (o:"spirit" o:"you control"))
tribal_angels     (type:angel OR (o:"angel" o:"you control"))
tribal_demons     (type:demon OR (o:"demon" o:"you control"))
tribal_beasts     (type:beast OR (o:"beast" o:"you control"))
tribal_dinosaurs  (type:dinosaur OR (o:"dinosaur" o:"you control"))
tribal_slivers    (type:sliver OR (o:"sliver" o:"you control"))
tribal_werewolves (type:werewolf OR o:"werewolf" OR o:"daybound")
tribal_wolves     (type:wolf OR (o:"wolves" o:"you control"))
tribal_knights    (type:knight OR (o:"knight" o:"you control"))
tribal_ninjas     (type:ninja OR (o:"ninja" o:"you control") OR otag:ninjutsu)
tribal_cats       (type:cat OR (o:"cat" o:"you control"))
auras             (type:aura OR otag:enchantress OR o:"whenever you cast an aura")
tokens            otag:token-producer OR (o:"create" o:"token")
counters          otag:counter-manipulation OR o:"proliferate" OR o:"+1/+1 counter"
aristocrats       otag:sacrifice-outlet OR o:"whenever a creature you control dies"
reanimator        (o:"return target creature card from your graveyard" OR o:"reanimate")
spellslinger      (o:"whenever you cast an instant" OR o:"whenever you cast a sorcery" OR otag:magecraft)
enchantress       (type:enchantment OR o:"whenever an enchantment enters")
artifacts         (type:artifact OR o:"whenever an artifact enters")
voltron           (type:equipment OR type:aura OR o:"when equipped")
draw_matters      (o:"whenever you draw a card" OR o:"whenever a card is drawn")
lifegain          (otag:lifegain-payoff OR o:"whenever you gain life")
landfall          (otag:landfall OR o:"whenever a land enters the battlefield under your control")
graveyard         (otag:graveyard-recursion OR o:"from your graveyard" OR o:"flashback")
etb               (otag:etb OR o:"when this enters" OR o:"whenever a creature enters")
energy            (o:"energy counter" OR o:"{e}")
chaos             (o:"each player" o:"random")
theft             (o:"gain control" OR o:"under your control until end of turn")
group_hug         (o:"each player draws" OR o:"each player gains")
voltron_combat    type:creature (o:"double strike" OR o:"trample" OR o:"first strike"
                  OR o:"menace" OR o:"flying" OR o:"additional combat phase"
                  OR o:"an additional combat" OR o:"whenever this creature attacks"
                  OR o:"whenever it attacks")
```

**Fidelity beats cleverness.** `graveyard` matches the literal `"from your graveyard"`;
Living Death says "from *their* graveyard" and therefore does NOT match — Scryfall would
not return it either. Do not "improve" a query into matching more than it does. A theme
list that quietly disagrees with the Scryfall path is worse than one that is merely narrow.

---

## 4. Required public API — EXACT signatures

```python
THEMES: tuple[str, ...]      # every key in §3, in that order

NO_MATCH: int = 0
WEAK:     int = 1            # the card IS the thing (type/subtype match only)
STRONG:   int = 2            # the card PAYS OFF the thing (rules-text match)

def card_text(card: dict) -> str: ...
    """All oracle text, front + every face, newline-joined."""

def type_line(card: dict) -> str: ...
    """Top-level type_line, else all faces' type lines joined with ' // '."""

def subtypes(card: dict) -> set[str]: ...
    """Lower-cased subtypes from every face: the words after the em-dash (or ' - ').
    'Legendary Creature — Zombie Dragon' -> {'zombie', 'dragon'}. Returns an empty
    set when there is no dash."""

def theme_score(card: dict, theme: str) -> int: ...
    """NO_MATCH / WEAK / STRONG for this card against this theme.

    STRONG when the card matches on RULES TEXT — it rewards or cares about the theme.
    WEAK when it matches only on type/subtype — it is a member of the tribe, or simply
    has the right card type. An unknown theme name returns NO_MATCH (never raises)."""

def match_themes(cards: list[dict], themes: list[str]) -> dict[str, list[dict]]: ...
    """theme -> the cards that match it, best first.

    Ordering within a theme: STRONG before WEAK, then EDHREC rank ascending with a
    missing/None rank LAST, then name — fully deterministic, because the deck builder
    must be reproducible. Cards scoring NO_MATCH are omitted. Every requested theme
    gets a key even when its list is empty. A card may appear under several themes."""
```

---

## 5. Gold set — VERIFIED oracle text; your output must produce these exactly

Put this table in the module docstring as a comment.

| Card (type line) | oracle text (abridged, verbatim) | theme | expected |
|---|---|---|---|
| Shivan Dragon (Creature — Dragon) | "Flying / {R}: This creature gets +1/+0…" | `tribal_dragons` | **WEAK** |
| Bladewing the Risen (Legendary Creature — Zombie Dragon) | "…{B}{R}: Dragon creatures get +1/+1…" | `tribal_dragons` | **STRONG** |
| Bladewing the Risen | (same — no Zombie payoff text) | `tribal_zombies` | **WEAK** |
| Goblin Chieftain (Creature — Goblin) | "Other Goblin creatures you control get +1/+1 and have haste." | `tribal_goblins` | **STRONG** |
| Jadar, Ghoulcaller (Legendary Creature — Human Wizard) | "…if you control no creatures with decayed, create a 2/2 black Zombie creature token…" | `tribal_zombies` | **STRONG** |
| Storm-Kiln Artist (Creature — Dwarf Shaman) | "…Magecraft — Whenever you cast or copy an instant or sorcery spell, create a Treasure token." | `spellslinger` | **STRONG** |
| Storm-Kiln Artist | "This creature gets +1/+0 for each artifact you control. …" | `artifacts` | **NO_MATCH** |
| Storm-Kiln Artist | "…create a Treasure token." | `tokens` | **STRONG** |
| Grave Pact (Enchantment) | "Whenever a creature you control dies, each other player sacrifices a creature…" | `aristocrats` | **STRONG** |
| Psychosis Crawler (Artifact Creature — Phyrexian Horror) | "…Whenever you draw a card, each opponent loses 1 life." | `draw_matters` | **STRONG** |
| Psychosis Crawler | (same) | `artifacts` | **WEAK** |
| Steel Overseer (Artifact Creature — Construct) | "{T}: Put a +1/+1 counter on each artifact creature you control." | `counters` | **STRONG** |
| Living Death (Sorcery) | "Each player exiles all creature cards from their graveyard…" | `reanimator` | **NO_MATCH** |
| Living Death | (same — "their graveyard", not "your") | `graveyard` | **NO_MATCH** |
| Sol Ring (Artifact) | "{T}: Add {C}{C}." | `tribal_dragons` | **NO_MATCH** |
| Sol Ring | (same) | `artifacts` | **WEAK** |

Note on **Jadar**: it is not a Zombie, but its text contains both "Zombie" and "you
control", which is exactly what `(o:"zombie" o:"you control")` matches. The conjunction is
co-occurrence anywhere in the text, not adjacency. Reproduce that.

Note on **Storm-Kiln Artist vs `artifacts`**: the query is `type:artifact OR o:"whenever an
artifact enters"`. A Creature that merely counts artifacts satisfies neither.

---

## 6. Style constraints

* Python 3.14, `from __future__ import annotations`.
* Type-hint every public function.
* Module docstring: 4–6 lines on purpose + the gold-set table from §5.
* Build the theme rules as a DATA TABLE (theme -> the subtype it needs, the STRONG text
  patterns, the WEAK type patterns), not forty hand-written `if` branches. Adding a theme
  should be adding a row.
* Comments explain **why**. Where fidelity to a Scryfall query drives a decision, say so.
* No `print()`, no logging, no I/O, no `__main__`, no CLI.
* Guard every `.get()` — card dicts may be slim.
* Roughly 260–340 lines including docstrings.

---

## 7. Known failure modes — earlier drafts in this repo shipped every one of these

* **NEVER `from typing import dict`** (or `list`/`set`/`tuple`, or an aliased form). They
  are builtins; with `from __future__ import annotations` you write `dict[str, int]` with
  no import. This exact line broke two drafts with an ImportError on the first run.
* **Matching a verb and ignoring its object.** `o:"create" o:"token"` needs BOTH; a card
  that says "create" alone is not a token producer.
* **Bare substring keywords.** `"cat"` matches "**cat**apult", "es**cat**e",
  "dupli**cat**e"; `"elf"` matches "s**elf**", "hims**elf**"; `"ward"` matches "**Ward**en".
  Tribal TEXT matching must use `\b` word boundaries. This one will wreck the tribal
  themes if you miss it.
* **`\d+` where oracle text uses number words.** Accept both.
* **Emitting an incomplete file.** Your reasoning is billed against the same token budget
  as your answer. Reason briefly, write the whole file, close the fence.
* **Dropping the module docstring.** Drafts keep doing this.
