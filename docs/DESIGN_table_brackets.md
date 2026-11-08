# Table brackets: a bracket that predicts whether the game will be fun

Status: design proposal, 2026-11-08; section 6 is the build order. D1 is done (see the table).

## 1. The problem, in our own data

The official system (Exhibition, Core, Upgraded, Optimized, cEDH) is a card-list contract: the
Game Changer list, plus bans on mass land denial, chained extra turns and two-card
infinite combos at the low end. It is a good **floor** ("this deck can't be lower than X") and a
weak **predictor** of how a game will feel. What we measured while building this app:

| Finding | Number |
|---|---|
| Our strength model, fitted to 2,116 player-labelled decks, puts its weight on the Game Changer count | weight 0.70 for Game Changers vs 0.06 interaction, 0.00 kill speed |
| Players' own labels break the official rules often | 11% of 624 audited labels; 24% of Bracket 1 labels |
| The saltiest cards are mostly not Game Changers | 25 of the 40 saltiest (EDHREC survey): Stasis 3.05, Armageddon 2.98, Winter Orb 2.93, Static Orb 2.71, Smokestack, Blood Moon |
| Lock pieces fall between the rules | the official mass-land-denial text covers "keep lands tapped / change what mana is produced", but our gate (and most players) catch only "destroy lands": Winter Orb, Static Orb, Stasis, Blood Moon, Back to Basics all pass |
| Salt alone misses some feel-bad cards | Solitary Confinement scores 1.0 / 4 in the survey: it rarely shows up, so few people rate it, but when it lands one player stops playing the game |
| Low-bracket clocks are slow | the typical Bracket 1-3 deck's average unopposed kill is about T10 (corpus reference); a slow clock is exactly where card-for-card answers compound |

So the bracket mostly tells you **how many famous cards** a deck has. It does not tell you the
four things that decide whether a pod has fun:

1. **Does everyone get to play?** Counterspell walls, stax, locks and theft remove other
   players' turns. A deck with 12 counters and zero Game Changers is "Bracket 2" and still takes
   the game away from three people.
2. **Does the game end when people expect?** A T6 combo and a T14 grind at one table are both
   unfun for someone.
3. **Is the outcome still open in the middle of the game?** Tutors + deterministic combos make
   results predictable. That is the point of competitive play and the opposite of casual play.
4. **Are the four decks on the same level?** Fun is a property of the POD, not of one deck.

Your observation ("at low bracket, tons of interaction and counters just wins") fits the
mechanism: at Bracket 1-2 the threats are fair and the clock is slow, the other decks pack few
answers, and nothing punishes a durdling control deck. Every 1-for-1 plus card draw compounds.
We have not yet measured it in the pod simulator, and we can't yet: the 4-player sim's reactions
are 1-on-1 only (section 6, D5).

## 2. Design principles

- **Rules set the floor; play patterns set the label.** Keep the official gates as the minimum.
  Decide the placement from what the deck DOES to a game, measured, not from what it contains.
- **Measure outcomes, not card names, wherever we can simulate them;** fall back to a card list
  only for effects the simulator can't play (locks), and keep that list short and explicit like
  the Game Changer list.
- **Predict the pod, not the deck.** The output is "will these four decks have a good game",
  with the deck's own number as an input to that.
- **Say why in table language.** Every flag reads like a pre-game talk line: "runs 11
  counterspells", "has two lock pieces", "usually wins T7-T8".

## 3. The proposal: Bracket + Table Contract

Each deck gets a **power bracket** (1-5, as now, but placed by measured power) and **four
dials**, each Low / Medium / High. Together they are the deck's table contract.

### 3.1 Power bracket (keep, re-based)

Placed from measured outcomes: the kill clock (B32), combo clock (B33), consistency, and win
share against a field of bracket peers (B35). Game Changers stay a floor, as the official rules
use them, but stop being most of the score.

### 3.2 Dial A: Denial (does everyone get to play?)

The share of opponents' game actions the deck stops. It has two sources:

- **Measured:** the pod simulator counts opponents' spells countered, permanents stolen or
  locked, turns skipped or taken, and attacks prevented. The output is "opponent actions denied
  per game", relative to bracket peers.
- **Listed:** a short **Lock list** for effects the simulator can't play, kept like the Game
  Changer list. Examples: Stasis, Winter Orb, Static Orb, Smokestack, Rising Waters, Hokori,
  Solitary Confinement, Ensnaring Bridge, Blood Moon, Back to Basics, Drannith Magistrate,
  Grand Arbiter Augustin IV, Humility.

Proposed rule: **Bracket 1-2 allow no Lock list cards, Bracket 3 allows one, Bracket 4+ any.**
A Bracket 1-2 deck with High measured Denial **plays up one bracket** unless the pod opts in to
a control game. This is the change that catches the 12-counterspell "Bracket 2" deck.

### 3.3 Dial B: Pace (when does the game end?)

The deck's kill window, the middle half of its kill turns from B32/B33, read as Fast (before T7),
Typical (T7-T11) or Long (after T11). A pod is happiest when its windows overlap.

### 3.4 Dial C: Inevitability (is the outcome still open?)

How predictable the deck's win is. Inputs:

- tutors that can find a win piece (B33's tutor reach);
- deterministic combos and their assembly rate;
- how narrow the kill window is (the spread from B32).

High Inevitability is the core of Bracket 4-5 and a warning sign at 1-3: "assembles the same
win most games, around T8".

### 3.5 Dial D: Table feel (how will it feel to face?)

EDHREC salt percentile, which we already have, **plus** the Lock list. Lock cards count as salty
even when the survey under-rates them (Solitary Confinement). Shown as information, never as a
power input.

### 3.6 Pod fit (the prediction)

Given four decks, predict a fun game when all of these hold:

- power brackets are within one of each other;
- pace windows overlap;
- no deck's Denial is two steps above the pod's median;
- at most one deck has High Inevitability, unless the pod is a Bracket 4-5 pod.

Each failed check produces a sentence for the pre-game talk.

## 4. What changes for a player

- The badge reads **"Bracket 2 · Denial High · Pace Long"** instead of "Bracket 2". The extra
  words are exactly what the pod needs to hear before shuffling.
- A counter-heavy precon-power deck no longer hides at Bracket 2: it plays up, or carries
  "Denial High" so the pod can choose.
- Lock pieces get the attention Game Changers get, with a list and a rule.
- The bracket you say and the bracket we measure sit side by side (shipped 2026-11-08), so a
  mismatch is visible before the game.

## 5. What it deliberately does not do

- It does not judge whether control decks are good or bad. Denial is a dial, not a penalty; a
  pod that wants a control mirror can opt in.
- It does not put salt into the power bracket. A deck can be weak and salty, or strong and
  friendly.
- It does not invent labels for fun. Section 6 says how we would get them.

## 6. Build order in this app

| Item | What | Depends on |
|---|---|---|
| D1 (**done** 2026-11-08) | Fix the mass-land-denial gate both ways: add tap-down and mana-change effects (Winter Orb, Static Orb, Stasis, Blood Moon, Back to Basics); drop the false positives (Pox, Tectonic Hellion, Magosi, planeswalker ultimates) | none; rerun the bracket accuracy check |
| D2 | Lock list plus a card tagger for denial roles (counter, stax, lock, theft, extra turn, tap-down), checked against a hand-labelled gold set | none |
| D3 | Denial and Inevitability dials from what the engine already measures (D2 tags, B32 spread, B33 tutors and combos) | D2 |
| D4 | Pod fit check over four decks, shown in the strength panel and before `/pod` | D3, B35 |
| D5 | Multiplayer reactions in the pod simulator (counter whichever spell threatens most, not only the 1-on-1 opponent's) so measured Denial and the "counters win low brackets" claim can be tested | none; the largest item |
| D6 | Validate: in a Bracket 2 field, does a High-Denial deck win far more than its seat share (25%)? If so, the plays-up rule is right. | D5, B35 |
| D7 | Real fun labels: an optional one-tap after-game note in the app ("fun? who ran away with it?"), stored locally, to fit the pod-fit check against real games | D4 |

D1 and D2 are small and independent; D5 is what turns this from a card-list proposal into a
measured one.

**D1 result (2026-11-08).** Rebuilt on Wizards' own wording ("regularly destroy, exile, and bounce
other lands, keep lands tapped, or change what mana is produced by four or more lands per player
without replacing them"; examples Armageddon, Ruination, Sunder, Winter Orb, Blood Moon). Over all
34,733 cards: mass land denial +13 (Winter Orb, Static Orb, Winter Moon, Stasis, Rising Waters,
Hokori, Back to Basics, Blood Moon, Magus of the Moon, Harbinger of the Seas, Contamination,
Infernal Darkness, Ritual of Subdual) and -2 (Pox, a share of lands; Ajani Vengeant's -7). Extra
turns -6 (planeswalker ultimates; Magosi and Wormfang Manta, which skip a turn to take one).
Tectonic Hellion stays: it takes lands on every attack. On the 76 labelled decks whose gate
changed, exact agreement with the label went 36 -> 50 and within-one 64 -> 73; five casual decks
lost a false Bracket 4 floor. The corpus label audit now includes mass land denial (10 more labels
demoted, 2,112 kept), and so does the stated-bracket check in the UI.

