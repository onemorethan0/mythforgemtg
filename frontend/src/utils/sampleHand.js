// Playtest helpers for the deck view: sample opening hands and opening-hand land odds.
// Every mainstream deck site (Moxfield, Archidekt, Deckstats) has a "draw a sample hand"
// button; Myth Forge had a full game simulator but no way to just look at seven cards.
// Drafted by qwen3:14b from a spec, reviewed and corrected by hand (the draft's PRNG was
// not mulberry32 and returned ~0 every call, and the exclude list was case-sensitive).

/** Seeded PRNG (mulberry32): returns () => float in [0, 1). */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function qty(entry) {
  const n = Number.parseInt(entry.quantity, 10);
  return Number.isFinite(n) && n > 0 ? n : 1;
}

/** Expand deck entries by quantity into a flat library, leaving out command-zone cards. */
export function buildLibrary(entries, excludeNames = []) {
  const exclude = new Set(excludeNames.map(n => (n || '').trim().toLowerCase()));
  const library = [];
  for (const entry of entries || []) {
    const name = (entry.original_name || '').trim().toLowerCase();
    if (!name || exclude.has(name)) continue;
    for (let i = 0; i < qty(entry); i++) library.push(entry);
  }
  return library;
}

/** A new Fisher-Yates shuffled array; the input is not mutated. */
export function shuffle(cards, rng = Math.random) {
  const out = [...cards];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/** Shuffle and split into { hand, rest }. */
export function drawHand(library, size = 7, rng = Math.random) {
  const shuffled = shuffle(library, rng);
  return { hand: shuffled.slice(0, size), rest: shuffled.slice(size) };
}

/** True when any face is a land: a spell // land MDFC can be the land drop, and this
 *  matches deck_quality.is_land, so the odds and the Deck health land count agree. */
export function isLand(card) {
  const tl = (card && (card.original_type_line || card.type_line)) || '';
  return /\bland\b/i.test(tl);
}

function logChoose(n, k) {
  if (k < 0 || k > n) return -Infinity;
  let sum = 0;
  for (let i = 0; i < k; i++) sum += Math.log(n - i) - Math.log(i + 1);
  return sum;
}

/** P(at least `atLeast` successes) drawing `draws` from `population` holding `successes`. */
export function hypergeometricAtLeast(population, successes, draws, atLeast) {
  if (atLeast <= 0) return 1;
  const n = Math.min(draws, population);
  const denom = logChoose(population, n);
  let total = 0;
  for (let k = atLeast; k <= Math.min(n, successes); k++) {
    total += Math.exp(logChoose(successes, k) + logChoose(population - successes, n - k) - denom);
  }
  return Math.max(0, Math.min(1, total));
}

/** Land odds for an opening hand of `size` drawn from a flat library. */
export function openingHandOdds(library, size = 7) {
  const lands = library.filter(isLand).length;
  const total = library.length;
  const pAtLeast2Lands = hypergeometricAtLeast(total, lands, size, 2);
  const pAtLeast3Lands = hypergeometricAtLeast(total, lands, size, 3);
  const p2to4Lands = Math.max(0, pAtLeast2Lands - hypergeometricAtLeast(total, lands, size, 5));
  return { lands, total, p2to4Lands, pAtLeast2Lands, pAtLeast3Lands };
}
