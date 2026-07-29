"""Render resolved art choices into EDHPlay import formats.

Two outputs, both driven by the same `ArtChoice` list:

* **Bulk-import text** -- paste into EDHPlay's "Create Deck -> Bulk Import" box. Each line is
  ``<qty> <Name> (<SET>) <collector_number>`` when an art is pinned, or ``<qty> <Name>`` to
  let EDHPlay choose. Commander(s) are emitted in a leading comment block because you pick the
  commander when you create the deck, not in the pasted 99.
* **API body** -- the JSON `POST /api/v1/decks/{id}/bulk-import` payload
  (``{cards, commander, partner_commander, replace}``), for a scripted direct push.

The (SET) collector suffix is exactly what EDHPlay's own importer parses into
``{name, quantity, set_code, collector_number}`` (see docs/EDHPLAY_EXPORT.md).
"""

from __future__ import annotations

from dataclasses import dataclass

from mythgauntlet.edhplay.artselect import ArtChoice


def _line(choice: ArtChoice) -> str:
    base = f"{choice.count} {choice.name}"
    if choice.printing is not None:
        p = choice.printing
        return f"{base} ({p.set_code}) {p.collector_number}"
    return base


def to_bulk_text(
    main: list[ArtChoice],
    commanders: list[ArtChoice],
    *,
    deck_name: str = "",
    annotate: bool = True,
) -> str:
    """Paste-ready decklist. Commanders go in a comment header, the 99 follow as plain lines."""
    lines: list[str] = []
    if deck_name:
        lines.append(f"# {deck_name} -- EDHPlay import (art pinned by printing)")
    if commanders:
        lines.append("# Commander (choose this when you create the deck):")
        for c in commanders:
            note = f"   # {c.note}" if (annotate and c.note) else ""
            lines.append(f"#   {_line(c)}{note}")
        lines.append("")
    for c in main:
        note = f"   # {c.note}" if (annotate and c.note) else ""
        lines.append(f"{_line(c)}{note}")
    return "\n".join(lines) + "\n"


def _card_obj(choice: ArtChoice) -> dict:
    obj: dict = {"name": choice.name, "quantity": choice.count}
    if choice.printing is not None:
        obj["set_code"] = choice.printing.set_code
        obj["collector_number"] = choice.printing.collector_number
    return obj


def to_api_body(
    main: list[ArtChoice],
    commanders: list[ArtChoice],
    *,
    replace: bool = True,
) -> dict:
    """The `POST /api/v1/decks/{id}/bulk-import` request body.

    EDHPlay takes the commander(s) as separate fields; partner/companion are left to the
    caller (the deck's second commander, if any, maps to ``partner_commander``).
    """
    body: dict = {
        "cards": [_card_obj(c) for c in main],
        "replace": replace,
    }
    if commanders:
        body["commander"] = commanders[0].name
        if len(commanders) > 1:
            body["partner_commander"] = commanders[1].name
    return body


@dataclass
class ExportSummary:
    total: int
    pinned: int              # cards with a chosen printing
    default: int             # left to EDHPlay's default
    unknown: int             # not in the printings store
    fallbacks: list[ArtChoice]
    unknowns: list[ArtChoice]


def summarize(main: list[ArtChoice], commanders: list[ArtChoice]) -> ExportSummary:
    every = commanders + main
    pinned = sum(1 for c in every if c.resolved)
    unknown = [c for c in every if c.source == "unknown"]
    default = [c for c in every if c.source == "default"]
    fallbacks = [c for c in every if c.source == "fallback"]
    return ExportSummary(
        total=len(every),
        pinned=pinned,
        default=len(default),
        unknown=len(unknown),
        fallbacks=fallbacks,
        unknowns=unknown,
    )
