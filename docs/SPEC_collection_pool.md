# SPEC — `collection_pool.py`

Write ONE new Python file: `collection_pool.py`, at the repo root of Myth Forge.

You are writing a **self-contained, pure, offline** module. It must import ONLY from the
Python standard library (`re`, `dataclasses`, `typing`, `collections`). **No network. No
`requests`. No imports from any other project module.** It will be unit-tested with plain
dicts — never with live Scryfall data.

Output **only the contents of `collection_pool.py`**, in a single ```python fenced block.
No prose before or after. No explanation. `/no_think`

---

## 1. Why this module exists

Myth Forge builds 99-card Commander decks. Today every functional role (ramp, draw,
removal, board wipe, protection, finisher) is filled by querying Scryfall with `otag:` /
oracle-text search, sorted by EDHREC rank.

We are adding a **strict "build only from cards I own"** mode. In that mode Scryfall
search is unavailable — we have only a flat list of card dicts the user owns. So the roles
must be classified **locally, from the card's own oracle text and type line**.

This module is that classifier plus the pool partitioner. It answers:

* what roles does this owned card fill?
* given a commander, which owned cards are legal in the deck, and how do they partition
  into roles, best-first?
* which owned cards could be a commander?

---

## 2. The card dict shape (VERIFIED — do not invent fields)

Cards are Scryfall card objects. Only these keys are guaranteed:

```python
{
  "name": "Blasphemous Act",
  "mana_cost": "{8}{R}",
  "type_line": "Sorcery",
  "oracle_text": "This spell costs {1} less to cast for each creature on the battlefield.\nBlasphemous Act deals 13 damage to each creature.",
  "colors": ["R"],
  "color_identity": ["R"],
  "cmc": 9.0,
  "edhrec_rank": 22,                       # may be absent or None
  "legalities": {"commander": "legal"},    # may be absent
  "card_faces": [ {...}, {...} ],          # ONLY on split/DFC/adventure cards
}
```

**Multi-face cards**: `oracle_text` and `type_line` may be **absent at the top level** and
present only inside `card_faces[]`. Every text/type read MUST consider both faces. There
is existing prior art for this in `buildable.py` (`_card_text`, `_type_line`) — reuse that
exact approach.

---

## 3. Required public API — EXACT signatures

```python
ROLES: tuple[str, ...]        # ("ramp","draw","removal","wipe","protection","finisher")

@dataclass(frozen=True)
class PoolStats:
    total_owned:    int          # cards handed in
    eligible:       int          # survived legality + colour-identity + not-basic
    by_role:        dict[str, int]
    lands:          int          # eligible NONBASIC lands
    creatures:      int          # eligible true creatures (creature, not a land)

@dataclass
class CardPool:
    commander:  dict                       # the commander card dict
    roles:      dict[str, list[dict]]      # role -> cards, EDHREC-best first
    lands:      list[dict]                 # eligible nonbasic lands, best first
    creatures:  list[dict]                 # eligible true creatures, best first
    flex:       list[dict]                 # EVERY eligible nonland card, best first
    stats:      PoolStats

def card_text(card: dict) -> str: ...
    """All oracle text, front + every face, newline-joined."""

def type_line(card: dict) -> str: ...
    """Top-level type_line, else all faces' type lines joined with ' // '."""

def is_basic_land(card: dict) -> bool: ...
def is_land(card: dict) -> bool: ...
def is_creature(card: dict) -> bool: ...
    """A TRUE creature: 'creature' in the type line and 'land' NOT in it."""

def is_commander_legal(card: dict) -> bool: ...
    """legalities.commander == 'legal'. A MISSING legalities dict returns True
    (the caller may hand in slim card dicts); an explicitly non-'legal' value
    returns False."""

def in_identity(card: dict, ci: set[str]) -> bool: ...
    """card.color_identity subset of ci. An EMPTY ci means a colourless commander:
    only cards with an empty colour identity qualify."""

def classify(card: dict) -> set[str]: ...
    """Zero or more of ROLES. See section 4 — this is the heart of the module."""

def is_commander_eligible(card: dict) -> bool: ...
    """Legendary creature, OR text contains 'can be your commander'."""

def owned_commanders(cards: list[dict]) -> list[dict]: ...
    """Commander-eligible cards, sorted by edhrec_rank ascending (None last),
    then by name. Does NOT filter by legality — a banned commander is still
    shown so the caller can explain why it is unavailable."""

def build_pool(commander: dict, cards: list[dict]) -> CardPool: ...
    """Partition the owned cards for this commander. Excludes the commander
    itself (matched by 'name'), basic lands, commander-illegal cards, and
    anything outside the commander's colour identity. Every list is sorted
    EDHREC-best-first (missing/None edhrec_rank sorts LAST, then by name for
    a stable deterministic order). A card appearing in three roles appears in
    all three role lists AND in flex — the lists are views, not a partition."""

def shortfall(pool: CardPool, plan: dict[str, int]) -> dict[str, int]: ...
    """Per-role deficit: max(0, wanted - available) for each key in `plan`.
    Roles the pool covers are OMITTED from the result, so an empty dict means
    'the collection can fill this plan'. `plan` keys not in ROLES (e.g. 'lands')
    are looked up against pool.lands / pool.creatures if named exactly that,
    otherwise ignored."""
```

---

## 4. `classify()` — the classification rules

This is the part that must be **right**, not merely plausible. Magic is precise; a wrong
classification puts a card in the wrong deck slot.

### 4.1 The two failure modes you must avoid

This codebase has repeatedly shipped bugs of exactly two shapes. Both are banned here.

**(A) Matching the VERB and ignoring the OBJECT.**
`"destroy all"` is not a board wipe on its own — *Vandalblast* destroys all artifacts,
*Rest in Peace* exiles all graveyards. A **wipe** must destroy/exile/damage
**creatures specifically**.

**(B) Reading an EFFECT without its COST.**
`"add {B}"` is not ramp if the ability costs `{1}, {T}` to produce one mana — that nets
zero. Similarly a Signet's `{1},{T}: Add {W}{U}` is +1 net, not +2.

### 4.2 Role definitions

**`ramp`** — produces mana or puts extra lands onto the battlefield.
* Mana ability on a permanent: `{T}: Add …` — count it.
* **NET-POSITIVE ONLY.** Count the generic mana in the activation cost against the mana
  added. `{1}, {T}: Add {B}` nets 0 → **NOT ramp**. `{T}: Add {C}{C}` nets 2 → ramp.
  A filter land / filter rock (`{1},{T}: Add {W}{W}`) nets +1 → ramp.
* `search your library for a … land card` and put it onto the battlefield → ramp.
* `play an additional land` → ramp.
* `create a Treasure token` → ramp.
* A one-shot ritual (`Add {R}{R}{R}` on an instant/sorcery) → ramp.
* Cost reduction (`spells you cast cost {1} less`) → ramp.

**`draw`** — net card advantage into hand.
* `draw N cards` → draw. But **`each player draws`** / **`target opponent draws`** without
  you drawing is NOT draw for you — require that the drawer is you, i.e. reject a match
  whose subject is `each opponent` or `target opponent`. `each player` counts (you are a
  player) but only when there is no better signal.
* `look at the top … put … into your hand` → draw.
* An impulse-draw (`exile the top … you may play`) → draw.
* **Cycling / looting / rummaging that only replaces a card is NOT draw.** Specifically:
  a `discard a card` **cost** paired with `draw a card` (singular, one card) nets zero →
  not draw. `Draw two cards` after discarding one is +1 → draw.

**`removal`** — answers ONE opposing permanent (or a small number of targets).
* `destroy target`, `exile target`, `return target … to its owner's hand`.
* `deals N damage to target creature` / `to any target`.
* `target creature gets -X/-X`.
* `each opponent sacrifices` → removal (edict).
* Counterspells → removal.
* **The object matters**: `destroy target creature/permanent/artifact/enchantment/
  planeswalker` all count. `destroy target land` alone also counts.
* If the effect hits **all** creatures, it is `wipe`, not `removal` (a card may be both if
  it has modal text that does each).

**`wipe`** — a mass answer that hits **creatures**.
* `destroy all creatures`, `exile all creatures`, `all creatures get -X/-X`,
  `each creature gets -X/-X`, `deals N damage to each creature`,
  `each player sacrifices … creature`.
* **`destroy all artifacts` / `destroy all enchantments` alone is NOT a wipe** — that is
  `removal`. This is failure mode (A); do not regress it.
* `destroy all nonland permanents` IS a wipe (it hits creatures).

**`protection`** — keeps your stuff alive or stops interaction.
* Grants `hexproof`, `shroud`, `indestructible`, `protection from`, `ward`, or
  `can't be countered` **to something you control**.
* `regenerate`, `phase out`, `return it to the battlefield` (self-recursion).
* A counterspell that protects (`counter target spell that targets`) → protection.
* **A creature that merely HAS indestructible/hexproof as a static keyword is NOT
  protection** — it protects only itself. Require a grant to another permanent, an
  Equipment/Aura, or an instant/sorcery. This is the single most common false positive;
  gate it: if the card is a creature and the keyword appears with no `target` / `creatures
  you control` / `another` nearby, do not tag it.

**`finisher`** — a way to actually close the game.
* `you win the game` / `target opponent loses the game`.
* `additional combat phase`.
* `creatures you control get +X/+X` **and** trample / `creatures you control gain trample`.
* `deals damage equal to … to each opponent`, `each opponent loses N life` at scale.
* `double` damage or power.

### 4.3 Implementation shape

Use module-level compiled regex lists, one per role, exactly like `buildable._ROLE_PATTERNS`.
Then apply the **gates** described above as explicit follow-up checks — do NOT try to
encode "net positive mana" or "grants to another permanent" inside a single regex. Write
small named helpers:

```python
def _net_mana_positive(text: str) -> bool: ...
def _wipe_hits_creatures(text: str) -> bool: ...
def _grants_protection_to_other(card: dict) -> bool: ...
def _is_net_draw(text: str) -> bool: ...
```

Each helper gets a docstring naming the specific card that motivated it.

---

## 5. Gold set — your output MUST produce these exact classifications

These are real cards. Hard-code nothing; the rules in section 4 must *derive* these. Put
them in the module docstring as a comment table so a reviewer can check them.

| Card | oracle text (abridged) | MUST include | MUST NOT include |
|---|---|---|---|
| Sol Ring | `{T}: Add {C}{C}.` | ramp | draw, wipe |
| Arcane Signet | `{T}: Add one mana of any color…` | ramp | — |
| Springleaf Drum | `{T}, Tap an untapped creature you control: Add one mana of any color.` | ramp | — |
| Mind Stone | `{T}: Add {C}.` / `{1}, {T}, Sacrifice this artifact: Draw a card.` | ramp, draw | wipe |
| Blasphemous Act | `deals 13 damage to each creature` | wipe | removal, ramp |
| Vandalblast | `Destroy target artifact…` / `destroy all artifacts your opponents control` | removal | **wipe** |
| Rest in Peace | `Exile all graveyards…` | — | wipe, removal |
| Toxic Deluge | `All creatures get -X/-X` | wipe | — |
| Lightning Bolt | `deals 3 damage to any target` | removal | wipe |
| Phyrexian Arena | `you draw a card and you lose 1 life` | draw | — |
| Seize the Spoils | `discard a card` (cost) / `Draw two cards and create a Treasure token` | draw, ramp | — |
| Laughing Mad | `discard a card` (cost) / `Draw two cards.` | draw | — |
| Dangerous Wager | `Discard your hand, then draw two cards.` | draw | — |
| Darksteel Plate | `Equipped creature has indestructible.` | protection | — |
| Smaug the Impenetrable | `Flying, indestructible, haste` (a creature, keyword only) | — | **protection** |
| Lightning Greaves | `Equipped creature has haste and shroud.` | protection | — |
| Berserkers' Onslaught | `Attacking creatures you control have double strike.` | finisher | — |
| Hellkite Tyrant | `if you control twenty or more artifacts, you win the game` | finisher | — |
| Chaos Warp | `destroy target permanent…` (owner reveals) | removal | wipe |
| Mana Geyser | `Add {R} for each tapped land your opponents control.` | ramp | — |
| Wayfarer's Bauble | `search your library for a basic land card, put it onto the battlefield` | ramp | draw |
| Solemn Simulacrum | search a basic land + `draw a card` on death | ramp, draw | — |
| Command Tower | `{T}: Add one mana of any color…` (a **land**) | ramp | — |

> Note on Command Tower: lands DO classify as ramp under these rules. That is intentional
> and harmless — `build_pool` routes lands into `pool.lands`, and the caller never draws
> lands out of `roles["ramp"]`. Do not add a land exclusion to `classify()`.

---

## 6. Sorting rule (used everywhere)

```python
def rank_key(card: dict) -> tuple:
    """EDHREC-best first; unranked cards last; ties broken by name so the order
    is fully deterministic (the deck builder must be reproducible)."""
    r = card.get("edhrec_rank")
    return (0, r, card.get("name", "")) if isinstance(r, int) else (1, 0, card.get("name", ""))
```

Use this ONE helper for every sort in the module. Do not inline `or 10**9` variants. (It is now PUBLIC — theme_match imports it, so there is one
ordering of edhrec_rank in the repo rather than three that drift.)

---

## 7. Style constraints

* Python 3.14, `from __future__ import annotations` at the top.
* Type-hint every public function.
* Module docstring explains the strict-collection use case in 4–6 lines and carries the
  gold-set table from section 5 as a comment.
* Comments explain **why**, not what. Where a rule exists to prevent a specific bug, name
  the card (`# Vandalblast: 'destroy all' + artifacts is removal, not a wipe`).
* No `print()`. No logging. No I/O of any kind.
* Guard every `.get()` on possibly-missing keys — a card dict may be slim.
* Target roughly 260–340 lines including docstrings.

---

## 8. DRAFT-1 DEFECTS — a previous attempt failed these. Do not repeat them.

A first draft of this module was reviewed and rejected. Every item below was a real bug in
it. Read these before writing a single regex.

**D1 — Oracle text spells card counts as WORDS, not digits.**
The draft used `re.compile(r"draw \d+ cards")`. Real Magic oracle text reads
**"Draw two cards"**, **"draw three cards"** — `\d+` matches none of them. That single
mistake broke *Seize the Spoils*, *Laughing Mad* and *Dangerous Wager*, all of which are in
the gold set as `draw`.
Every count-matching pattern must accept **both** digits and the number words
`one|two|three|four|five|six|seven|eight|nine|ten|X`. Build one shared fragment, e.g.
`_N = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|X)"`, and use it
everywhere a quantity appears. Note that **damage** amounts DO use digits
("deals 3 damage"), but card counts do not — support both regardless.

**D2 — The net-positive-mana gate was unreachable dead code.**
The draft had a broad pattern `r"\{T\}:\s*Add\s+\{"` in `RAMP_PATTERNS`, and only
consulted `_net_mana_positive()` if no pattern matched. But that pattern matches the
substring `{T}: Add {B}` **inside** `{1}, {T}: Add {B}` — so the mana-negative case the
gate exists to reject never reached the gate. This is exactly failure mode (B) from §4.1.
**Fix the ordering:** any candidate matched by an `{T}: Add …` style pattern MUST then be
confirmed by `_net_mana_positive()` before `ramp` is added. The gate is a filter on the
match, never a fallback after it. `{1}, {T}: Add {B}` must return `set()`, not `{"ramp"}`.
Add that card to your own reasoning as a test.

**D3 — `"ward"` as a bare substring is a false positive.**
It matches `Warden`, `Steward`, `forward`, `award`. Use a word boundary: `\bward\b`.
Apply the same scrutiny to every short keyword.

**D4 — The finisher mass-pump rule dropped its conjunction.**
§4.2 requires mass pump **AND** trample. The draft matched
`creatures you control get \+\d+/\+\d+` alone, which tags every small anthem as a
finisher. Require the trample half in the same card text.

**D5 — `deals damage equal to` is far too broad for `finisher`.**
It matched every "deals damage equal to its power to any target" pinger (Kilnmouth
Dragon, Bonehoard, Lashwrithe) — those are removal, not finishers. Require the damage to
hit **each opponent** / **each player**, per §4.2.

**D6 — The draft ran out of output budget and stopped mid-function.**
It never emitted `shortfall()`, never finished `build_pool()`, and had no module
docstring. **Budget your output.** Write the code tersely: no blank-line padding, no
restating the spec in comments. All ten public functions plus both dataclasses must be
present and complete. If you must economise, shorten your reasoning, never the code.

**D7 — `is_basic_land` missed snow basics.**
`"basic land" in type_line` fails on `Basic Snow Land — Forest`. Match `basic` and `land`
as separate tokens in the type line.

---

## 9. Do NOT do these

* Do not modify, import, or reference `deck_builder.py`, `server.py`, `buildable.py`,
  `collection.py`, or `scryfall_client.py`. This file stands alone.
* Do not add a `main()`, a CLI, or an `if __name__ == "__main__"` block.
* Do not write the tests — a separate task covers those.
* Do not use `otag:` or any Scryfall query syntax; there is no network here.
* Do not invent card-dict keys beyond section 2.
