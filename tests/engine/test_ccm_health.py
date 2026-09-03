from mythgauntlet.semantics.health import analyze_failures


def _entry(name, status, prompt_version, **extra):
    return {"name": name, "status": status, "prompt_version": prompt_version, **extra}


def test_buckets_quarantined_and_blocked_separately():
    entries = {
        "a": _entry(
            "Card A", "quarantined", 11,
            errors=["[cross_check] trigger event 'etb' has no support in the oracle text"],
        ),
        "b": _entry(
            "Card B", "accepted", 9,
            refresh_failed_at=11,
            refresh_errors=["[cross_check] trigger event 'dealt_damage' has no support in the oracle text"],
        ),
        "c": _entry("Card C", "accepted", 11),  # up to date, not blocked
    }
    result = analyze_failures(entries)
    assert result["prompt_version"] == 11
    assert result["quarantined_total"] == 1
    assert result["blocked_total"] == 1
    assert result["quarantined_classes"][0]["gate"] == "cross_check"
    assert result["blocked_classes"][0]["gate"] == "cross_check"


def test_same_shaped_message_collapses_into_one_class():
    """The whole point: 'etb' and 'dealt_damage' are different VALUES of the same
    trigger-event mismatch shape, and must land in one class, ranked by size."""
    entries = {
        f"c{i}": _entry(
            f"Card {i}", "quarantined", 11,
            errors=[f"[cross_check] trigger event '{event}' has no support in the oracle text"],
        )
        for i, event in enumerate(["etb", "dealt_damage", "leaves_battlefield"])
    }
    result = analyze_failures(entries)
    assert len(result["quarantined_classes"]) == 1
    cls = result["quarantined_classes"][0]
    assert cls["count"] == 3
    assert set(cls["examples"]) == {"Card 0", "Card 1", "Card 2"}


def test_one_card_counts_once_per_class_even_with_repeated_errors():
    entries = {
        "a": _entry(
            "Multi-ability PW", "quarantined", 11,
            errors=[
                "[schema] abilities[0]: needs a non-empty effects list",
                "[schema] abilities[1]: needs a non-empty effects list",
            ],
        ),
    }
    result = analyze_failures(entries)
    assert result["quarantined_classes"][0]["count"] == 1


def test_blocked_entry_missing_refresh_errors_counted_but_not_bucketed():
    """A blocked card with no recorded reason (history — see module docstring) still
    counts toward blocked_total, and blocked_with_data tells you coverage is partial."""
    entries = {
        "up_to_date": _entry("Fresh Card", "accepted", 11),
        "a": _entry("No Data Card", "accepted", 8, refresh_failed_at=11),
        "b": _entry(
            "Has Data Card", "accepted", 9, refresh_failed_at=11,
            refresh_errors=["[lint] cost.mana '{R}' != printed cost '{G}'"],
        ),
    }
    result = analyze_failures(entries)
    assert result["blocked_total"] == 2
    assert result["blocked_with_data"] == 1
    assert sum(c["count"] for c in result["blocked_classes"]) == 1


def test_current_prompt_and_quarantined_authored_cards_are_excluded():
    entries = {
        "a": _entry("Fresh Card", "accepted", 11),
        "b": _entry(
            "Stale Refreshed Ok", "accepted", 9,
            errors=["[cross_check] stale error from a PRIOR compile attempt, not a live block"],
        ),
    }
    result = analyze_failures(entries)
    assert result["blocked_total"] == 0
    assert result["blocked_classes"] == []


def test_top_n_and_samples_per_class_are_respected():
    kinds = ["missing count", "bad controller", "empty effects", "wrong op", "bad cost"]
    entries = {}
    for i, kind in enumerate(kinds):
        entries[f"c{i}"] = _entry(
            f"Card {i}", "quarantined", 11,
            errors=[f"[schema] {kind}"],
        )
    result = analyze_failures(entries, top_n=2, samples_per_class=1)
    assert len(result["quarantined_classes"]) == 2
    for cls in result["quarantined_classes"]:
        assert len(cls["examples"]) <= 1


def test_empty_ledger_does_not_crash():
    result = analyze_failures({})
    assert result["prompt_version"] == 0
    assert result["quarantined_total"] == 0
    assert result["blocked_total"] == 0
    assert result["quarantined_classes"] == []
    assert result["blocked_classes"] == []
