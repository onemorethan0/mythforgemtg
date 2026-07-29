"""Pick one printing (art) per card, by policy and/or explicit per-card overrides.

Two ways to say which art you want:

* A **policy** applied to the whole deck -- e.g. ``newest``, ``borderless``, ``showcase``,
  ``retro``. Ranks the eligible printings of each card and takes the best.
* An **override file** ("your custom-art versions") -- one line per card, ``Name = spec``,
  where spec is an exact printing (``dmu 123`` / ``(dmu) 123`` / ``dmu/123``), a whole set
  (``dmu`` -> newest printing in that set), a Scryfall print id (``scryfall:<uuid>``), or a
  per-card policy keyword (``borderless``). Overrides win; the policy fills in the rest.

Selection is deterministic: ties break by newest release then collector number, and the
``random`` policy draws through ``SeededRng`` so the same seed always yields the same arts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from mythgauntlet.data.printings import Printing, PrintingDb
from mythgauntlet.model.card import normalize_name
from mythgauntlet.sim.rng import SeededRng

# Policy keywords usable both as a deck-wide --policy and inside an override line.
POLICIES = (
    "default", "newest", "oldest", "showcase", "borderless",
    "extended", "fullart", "textless", "retro", "random",
)

# Filters: does a printing qualify for a given art style?
_STYLE_FILTERS: dict[str, Callable[[Printing], bool]] = {
    "showcase": lambda p: p.showcase,
    "borderless": lambda p: p.borderless,
    "extended": lambda p: p.extended,
    "fullart": lambda p: p.full_art,
    "textless": lambda p: p.textless,
    "retro": lambda p: p.retro,
}


@dataclass(frozen=True)
class ArtChoice:
    """The resolved art for one deck card."""

    name: str
    count: int
    printing: Printing | None       # None => let EDHPlay pick its default printing
    source: str                     # "override" | policy name | "fallback" | "default"
    requested: str = ""             # what the override/policy asked for, for reporting
    note: str = ""                  # e.g. "requested art not found; used newest"

    @property
    def resolved(self) -> bool:
        return self.printing is not None


@dataclass
class OverrideError:
    line_no: int
    text: str
    reason: str


@dataclass
class Overrides:
    by_name: dict[str, str] = field(default_factory=dict)   # normalized name -> spec
    errors: list[OverrideError] = field(default_factory=list)


def parse_overrides(text: str) -> Overrides:
    """Parse an art-override file. ``# ...`` and blank lines are comments.

    Accepts ``Name = spec`` and ``Name: spec``. Later lines override earlier ones.
    """
    ov = Overrides()
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        sep = "=" if "=" in line else (":" if ":" in line else "")
        if not sep:
            ov.errors.append(OverrideError(i, raw, "no '=' between card name and art"))
            continue
        name, spec = line.split(sep, 1)
        name, spec = name.strip(), spec.strip()
        if not name or not spec:
            ov.errors.append(OverrideError(i, raw, "empty card name or art spec"))
            continue
        ov.by_name[normalize_name(name)] = spec
    return ov


def _eligible(printings: list[Printing], *, paper_only: bool, lang: str) -> list[Printing]:
    """Printings that will actually render a real card on EDHPlay."""
    out = [p for p in printings if p.has_image and (p.lang == lang or not lang)]
    if paper_only:
        paper = [p for p in out if p.paper]
        if paper:
            out = paper
    return out or [p for p in printings if p.lang == lang] or printings


def _newest_key(p: Printing) -> tuple:
    # released_at is ISO 'YYYY-MM-DD' -> lexicographic sort matches chronological.
    return (p.released_at, p.collector_number)


def _pick_by_policy(
    printings: list[Printing], policy: str, rng: SeededRng | None
) -> Printing | None:
    if not printings:
        return None
    if policy == "oldest":
        return min(printings, key=_newest_key)
    if policy in ("newest", "default"):
        return max(printings, key=_newest_key)
    if policy == "random":
        # Draw over distinct illustrations for variety, deterministically.
        pool = sorted(printings, key=lambda p: p.scryfall_id)
        return (rng or SeededRng(0)).choice(pool)
    style = _STYLE_FILTERS.get(policy)
    if style is not None:
        styled = [p for p in printings if style(p)]
        if styled:
            return max(styled, key=_newest_key)
        return None  # caller decides fallback
    # Unknown policy -> newest.
    return max(printings, key=_newest_key)


def _resolve_spec(
    spec: str, printings: list[Printing], db: PrintingDb, rng: SeededRng | None
) -> tuple[Printing | None, str]:
    """Resolve one override spec against a card's printings. Returns (printing, note)."""
    s = spec.strip()
    low = s.casefold()

    if low.startswith("scryfall:"):
        pid = s.split(":", 1)[1].strip()
        p = db.get_print(pid)
        if p is None:
            return None, f"scryfall id {pid} not found"
        return p, ""

    if low in POLICIES:
        p = _pick_by_policy(printings, low, rng)
        if p is None:
            return None, f"no '{low}' printing for this card"
        return p, ""

    # Exact printing: "SET CN" | "(SET) CN" | "SET/CN"
    cleaned = s.replace("(", " ").replace(")", " ").replace("/", " ")
    parts = cleaned.split()
    if len(parts) >= 2:
        set_code, cn = parts[0], parts[1]
        exact = next(
            (p for p in printings
             if p.set_code.casefold() == set_code.casefold()
             and p.collector_number.casefold() == cn.casefold()),
            None,
        )
        if exact is not None:
            return exact, ""
        # Fall back to the global set/cn index (covers front-face aliasing gaps).
        glob = db.get_set_cn(set_code, cn)
        if glob is not None:
            return glob, ""
        return None, f"printing ({set_code}) {cn} not found for this card"

    # Bare token: treat as a whole set -> newest printing in that set.
    in_set = [p for p in printings if p.set_code.casefold() == low]
    if in_set:
        return max(in_set, key=_newest_key), ""
    return None, f"unrecognized art spec '{spec}'"


def select_arts(
    entries: list[tuple[str, int]],
    db: PrintingDb,
    *,
    policy: str = "default",
    overrides: Overrides | None = None,
    seed: int = 0,
    paper_only: bool = True,
    lang: str = "en",
) -> list[ArtChoice]:
    """Resolve an art for each (name, count) entry.

    Precedence: explicit override -> deck-wide policy -> fallback (newest eligible).
    A card the printings store doesn't know at all yields an unresolved ArtChoice
    (EDHPlay will still import it by name and pick its own default).
    """
    overrides = overrides or Overrides()
    rng = SeededRng(seed)
    choices: list[ArtChoice] = []

    for name, count in entries:
        printings = db.printings(name)
        eligible = _eligible(printings, paper_only=paper_only, lang=lang) if printings else []
        key = normalize_name(name)
        spec = overrides.by_name.get(key)

        if not printings:
            choices.append(ArtChoice(name, count, None, "unknown",
                                     note="card not in printings store"))
            continue

        if spec is not None:
            picked, note = _resolve_spec(spec, eligible, db, rng)
            if picked is not None:
                choices.append(ArtChoice(name, count, picked, "override", requested=spec))
                continue
            # Override failed -> fall back to policy/newest, but report why.
            fallback = _pick_by_policy(eligible, policy, rng) \
                or _pick_by_policy(eligible, "newest", rng)
            choices.append(ArtChoice(
                name, count, fallback, "fallback", requested=spec,
                note=f"{note}; used {'policy '+policy if policy!='default' else 'newest'}",
            ))
            continue

        if policy == "default":
            # No override, no style preference -> leave printing unset (EDHPlay default).
            choices.append(ArtChoice(name, count, None, "default"))
            continue

        picked = _pick_by_policy(eligible, policy, rng)
        if picked is not None:
            choices.append(ArtChoice(name, count, picked, policy))
        else:
            fallback = _pick_by_policy(eligible, "newest", rng)
            choices.append(ArtChoice(
                name, count, fallback, "fallback", requested=policy,
                note=f"no '{policy}' printing; used newest",
            ))

    return choices
