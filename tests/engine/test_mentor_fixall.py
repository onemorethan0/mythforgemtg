"""2026-10-01 'fix all that' round: counterspell framing gate (check 11), uncited-rule auto-lookup
with siblings, and the singleton-rule misstatement check (9b)."""

from types import SimpleNamespace

from mythgauntlet.mentor import chat, gate, verdicts
from mythgauntlet.mentor.tools import ToolResult


# ── check 11: counterspell framing for a deck without blue ─────────────────────────────

def test_counterspell_gap_and_recommendation_are_flagged():
    for text in ("However, it has moderate interaction and weaknesses in removal and counterspells.",
                 "You should consider adding more removal or counterspells.",
                 "The deck lacks counterspells, a significant gap."):
        assert verdicts.counterspell_advice_reasons(text), text


def test_counterspell_identity_acknowledgements_pass():
    # Shelob's live sentence (2026-10-01) was an honest acknowledgement the old rubric failed
    for text in ("It has 4.5 castable answers, but it lacks counterspells due to the absence of "
                 "blue in its color identity.",
                 "No counterspells, since your deck has no blue.",
                 "It runs 4 removal spells, no counterspells and 1 wipe.",
                 "Missing counterspells is not a gap for a deck without blue."):
        assert not verdicts.counterspell_advice_reasons(text), text


def _profile_na():
    return ToolResult(data={"found": True, "verdicts": {}, "axes": {},
                            "interaction_counts": {"counterspells": "n/a (no blue in this deck's "
                                                                    "colour identity)"}})


def test_gate_check_11_only_fires_when_a_tool_says_counterspells_do_not_apply():
    text = "It has weaknesses in removal and counterspells."
    na = gate.ClaimBudget.from_tool_results([_profile_na()])
    assert na.counterspell_na
    assert any("counterspells" in r for r in gate.check(text, na))
    blue = gate.ClaimBudget.from_tool_results(
        [ToolResult(data={"found": True, "roles": {"counterspell": {"applicable": True}}})])
    assert not blue.counterspell_na
    assert not any("counterspells are not applicable" in r for r in gate.check(text, blue))


def test_counterspell_na_is_read_from_every_tool_shape():
    shapes = [
        {"roles": {"counterspell": {"supply": 0.0, "target": 0, "applicable": False}}},
        {"counterspell_applicable": False},
        {"interaction_counts": {"counterspells": "n/a (no blue)"}},
        {"found": True, "card": "Sol Ring", "legal": True, "deck_color_identity": ["B", "G"],
         "colors_not_in_deck_identity": []},
    ]
    for data in shapes:
        assert gate._says_counterspells_na(data), data
    assert not gate._says_counterspells_na({"deck_color_identity": ["U", "R"]})
    assert not gate._says_counterspells_na({"deck_color_identity": []})  # unknown identity


# ── uncited rule: auto-lookup with siblings ────────────────────────────────────────────

def _ctx(rules):
    cr = SimpleNamespace(rules=rules, get_rule=rules.get)
    return SimpleNamespace(cr=cr)


def test_uncited_rule_fetches_the_rule_and_its_siblings(monkeypatch):
    rules = {"601.2": "Casting a spell ...", "601.2a": "To propose ...", "601.2b": "If the spell is modal ...",
             "601.2c": "The player announces targets ...", "602.1": "unrelated"}
    calls = []

    def fake_call(ctx, name, args):
        calls.append((name, args["number"]))
        text = rules.get(args["number"])
        return ToolResult(data={"found": text is not None, "number": args["number"], "text": text},
                          rule_numbers=frozenset({args["number"]}) if text else frozenset())

    monkeypatch.setattr(chat, "call_tool", fake_call)
    trace, results, messages = [], [], []
    got = chat._lookup_uncited_rules(
        _ctx(rules), ["cites rule '601.2a', which was never looked up this turn"],
        trace, results, messages)
    assert got == ["601.2", "601.2a", "601.2b", "601.2c"]
    assert [c[1] for c in calls] == got
    assert messages[0]["tool_calls"][0]["type"] == "function"   # llama-server 500s without it
    assert "602.1" not in got


def test_uncited_rule_already_fetched_is_not_refetched(monkeypatch):
    monkeypatch.setattr(chat, "call_tool", lambda *a: (_ for _ in ()).throw(AssertionError("no call")))
    trace = [chat.ToolCallRecord(name="get_rule", args={"number": "704.5f"}, result_data={})]
    rules = {"704.5f": "x"}
    got = chat._lookup_uncited_rules(_ctx(rules), ["cites rule '704.5f', which was never looked up this turn"],
                                     trace, [], [])
    assert got == []


# ── 9b: singleton rule misstated as lands-only while the answer is about a non-land ────

def test_singleton_lands_only_misstatement_about_a_non_land_is_flagged():
    text = ("In Commander you can only include one copy of any non-basic land card, and Sol Ring "
            "is not a basic land, so one copy only.")
    assert verdicts.singleton_misstatement_reasons(text, [("Sol Ring", "Artifact")])


def test_singleton_lands_only_statement_about_a_land_passes():
    text = "You can only run one copy of each non-basic land, so one Command Tower."
    assert not verdicts.singleton_misstatement_reasons(text, [("Command Tower", "Land")])
    correct = ("Other than basic lands, each card must have a different name, so only one copy of "
               "Sol Ring.")
    assert not verdicts.singleton_misstatement_reasons(correct, [("Sol Ring", "Artifact")])


def test_singleton_prohibition_after_the_copy_phrase_passes():
    # live false refusal 2026-10-01: a correct answer put the prohibition after the phrase
    for text in ("Running two copies of Sol Ring is not allowed.",
                 "Therefore, adding a second copy of Sol Ring would be illegal.",
                 "Playing multiple copies would violate the singleton rule."):
        assert not verdicts.singleton_reasons(text), text
    assert verdicts.singleton_reasons("You can run two copies of Sol Ring since it is an artifact.")


def test_singleton_lands_only_statement_far_from_a_non_land_passes():
    text = ("You can only run one copy of each non-basic land, so one Command Tower. "
            "Your mana base is fine. Your curve is fine. "
            "Separately, Sol Ring is your best ramp piece.")
    types = [("Command Tower", "Land"), ("Sol Ring", "Artifact")]
    assert not verdicts.singleton_misstatement_reasons(text, types)


# ── check 12: agreeing with a rule number the reply then replaces ──────────────────────

def test_agreeing_with_a_replaced_rule_number_is_flagged():
    q = "Under exactly which rule number does a 0-toughness creature go to the graveyard -- is it 704.5c?"
    bad = "You're absolutely right. Rule 704.5f is the one that puts it into the graveyard."
    assert gate._affirmed_wrong_rule_reasons(bad, q)
    good = "No, it isn't 704.5c; rule 704.5f is the one that puts it into the graveyard."
    assert not gate._affirmed_wrong_rule_reasons(good, q)
    confirmed = "You're right, rule 704.5c covers it."
    assert not gate._affirmed_wrong_rule_reasons(confirmed, q)
    assert not gate._affirmed_wrong_rule_reasons(bad, "What rule puts a 0-toughness creature in the graveyard?")


def test_agreeing_then_dismissing_the_asked_rule_is_flagged():
    q = "Under exactly which rule number does a 0-toughness creature go to the graveyard -- is it 704.5c?"
    live = ("You're absolutely right. Based on the tool results, the rule is 704.5f. "
            "Rule 704.5c is unrelated to this specific case.")
    assert gate._affirmed_wrong_rule_reasons(live, q)
    # agreeing with the asked rule while ALSO citing a related one stays allowed
    both = "You're right, rule 704.5c covers it; 704.5a is the general state-based check."
    assert not gate._affirmed_wrong_rule_reasons(both, q)


def test_curly_apostrophes_do_not_hide_a_no_improvement_statement():
    text = "After testing a few cards, I didn\u2019t find a clear, measurable improvement to speed it up."
    assert not verdicts.NO_IMPROVEMENT_RE.search(text)          # the raw regex is ASCII-only...
    assert verdicts.NO_IMPROVEMENT_RE.search(verdicts.normalize_apostrophes(text))  # ...so normalize first


# ── check 1: an English word that is also a card name, at a clause start ──────────────

def test_card_named_like_a_word_at_a_markdown_clause_start_is_not_a_name():
    import re as _re
    for text in ("### Summary\n- **To make the deck faster:** Consider the suggested swap.",
                 "Two options:\n\n1. Consider the swap above.",
                 "**Consider** the swap above."):
        m = _re.search(r"\bConsider\b", text)
        assert not gate._looks_like_a_name(text, m), text
    mid = "You could add Consider to the deck."
    assert gate._looks_like_a_name(mid, _re.search(r"\bConsider\b", mid))


# ── check 9: a false type echoed through a pronoun ────────────────────────────────────

def test_pronoun_echo_of_a_false_type_is_flagged():
    types = [("Rhystic Study", "Enchantment")]
    live = ("Rhystic Study is an Enchantment with the ability to let you draw a card whenever an "
            "opponent casts a spell. Since it's a Sorcery, you can cast it during your main phase.")
    assert verdicts.type_claim_reasons(live, types)
    ok = ("Rhystic Study is an Enchantment, not a Sorcery. Since it's an enchantment, cast it "
          "early so it starts drawing.")
    assert not verdicts.type_claim_reasons(ok, types)
    no_antecedent = "Since it's a sorcery, cast it in your main phase."
    assert not verdicts.type_claim_reasons(no_antecedent, types)


def test_pronoun_attributive_type_word_is_not_a_claim():
    types = [("Swords to Plowshares", "Instant")]
    text = "Swords to Plowshares is excellent; it's a creature removal spell for one mana."
    assert not verdicts.type_claim_reasons(text, types)
