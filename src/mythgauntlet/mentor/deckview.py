"""
rows are the mentor's card-level view of the deck; role names come ONLY from
redundancy.card_roles(tags.analyze(card)) (one taxonomy, never a new one); lands carry
["land"]; commanders are listed first and flagged.
"""

from __future__ import annotations

from mythgauntlet.model.deck import ResolvedDeck
from mythgauntlet.ratings import redundancy
from mythgauntlet.semantics import tags


def _roles(card) -> list[str]:
    # Lands carry the one pseudo-role "land" and are never run through tags; every other
    # role name is a key of redundancy.card_roles -- the single taxonomy.
    if card.is_land:
        return ["land"]
    return sorted(redundancy.card_roles(tags.analyze(card)))


def deck_card_rows(resolved: ResolvedDeck) -> list[dict]:
    """One row per distinct card: commanders first (flagged), then the 99 in deck order.

    A name repeated inside `resolved.cards` is merged into one row (qty summed); a commander
    is never merged with a `resolved.cards` row of the same name.
    """
    rows: list[dict] = []
    for commander in resolved.commanders:
        rows.append({
            "name": commander.name,
            "qty": 1,
            "mana_value": commander.mana_value,
            "type_line": commander.type_line,
            "roles": _roles(commander),
            "commander": True,
        })

    by_name: dict[str, dict] = {}
    for card, quantity in resolved.cards:
        row = by_name.get(card.name)
        if row is not None:
            row["qty"] += quantity
            continue
        row = {
            "name": card.name,
            "qty": quantity,
            "mana_value": card.mana_value,
            "type_line": card.type_line,
            "roles": _roles(card),
        }
        by_name[card.name] = row
        rows.append(row)
    return rows
