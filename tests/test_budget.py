from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from occasio.core.budget import AV_SHARE, MONSOON_CONTINGENCY, allocate
from occasio.core.models import CateringStyle, Currency, format_money


def shares(plan) -> dict[str, float]:
    return {line.category: line.percent for line in plan.lines}


def amounts(plan) -> dict[str, int]:
    return {line.category: line.amount_minor for line in plan.lines}


@pytest.mark.parametrize("event_type", ["wedding", "birthday", "community_event"])
@pytest.mark.parametrize("total", [100, 1_234_567, 8_00_000_00, 99_999_99, 1])
def test_allocations_sum_exactly_to_total(make_profile, knowledge, event_type, total):
    plan = allocate(make_profile(event_type=event_type, budget_minor=total), knowledge)
    assert sum(line.amount_minor for line in plan.lines) == total


def test_lines_are_whole_units_except_contingency(make_profile, knowledge):
    plan = allocate(make_profile(budget_minor=1_234_567), knowledge)
    for line in plan.lines:
        if line.category != "contingency":
            assert line.amount_minor % 100 == 0


@pytest.mark.parametrize("bad", [0, -1, -500_00])
def test_zero_or_negative_budget_rejected(make_profile, bad):
    with pytest.raises(ValidationError):
        make_profile(budget_minor=bad)


def test_base_split_used_when_no_rules_fire(make_profile, knowledge):
    plan = allocate(make_profile(event_type="wedding", guest_count=100), knowledge)
    base = knowledge.budget_splits["wedding"]
    assert shares(plan) == {k: float(v) for k, v in base.items()}


def test_every_line_has_a_reason(make_profile, knowledge):
    plan = allocate(make_profile(guest_count=200, setting="outdoor", dietary=["vegan"]), knowledge)
    assert all(line.reason for line in plan.lines)


def test_av_not_added_at_exactly_150_guests(make_profile, knowledge):
    plan = allocate(make_profile(guest_count=150), knowledge)
    assert "sound_av" not in shares(plan)


def test_av_added_above_150_guests(make_profile, knowledge):
    plan = allocate(make_profile(guest_count=151), knowledge)
    s = shares(plan)
    assert s["sound_av"] == pytest.approx(AV_SHARE)
    assert sum(s.values()) == pytest.approx(100, abs=0.05)
    assert "151 guests" in next(line.reason for line in plan.lines if line.category == "sound_av")


@pytest.mark.parametrize("setting", ["outdoor", "mixed"])
def test_monsoon_outdoor_adds_contingency(make_profile, knowledge, setting):
    july = date(2026, 7, 18)
    plan = allocate(make_profile(setting=setting, event_date=july), knowledge)
    base = knowledge.budget_splits["birthday"]["contingency"]
    assert shares(plan)["contingency"] == pytest.approx(base + MONSOON_CONTINGENCY)
    assert sum(shares(plan).values()) == pytest.approx(100, abs=0.05)


def test_indoor_in_monsoon_has_no_extra_contingency(make_profile, knowledge):
    plan = allocate(make_profile(setting="indoor", event_date=date(2026, 7, 18)), knowledge)
    assert shares(plan)["contingency"] == knowledge.budget_splits["birthday"]["contingency"]


def test_outdoor_outside_monsoon_has_no_extra_contingency(make_profile, knowledge):
    plan = allocate(make_profile(setting="outdoor", event_date=date(2026, 2, 14)), knowledge)
    assert shares(plan)["contingency"] == knowledge.budget_splits["birthday"]["contingency"]


def test_regional_monsoon_months_differ(make_profile, knowledge):
    # Chennai's rains come with the northeast monsoon (Oct-Dec), not in July.
    july = allocate(
        make_profile(setting="outdoor", location="Chennai", event_date=date(2026, 7, 18)), knowledge
    )
    nov = allocate(
        make_profile(setting="outdoor", location="Chennai", event_date=date(2026, 11, 14)),
        knowledge,
    )
    base = knowledge.budget_splits["birthday"]["contingency"]
    assert shares(july)["contingency"] == base
    assert shares(nov)["contingency"] == pytest.approx(base + MONSOON_CONTINGENCY)


def test_unknown_location_gets_no_monsoon_rule(make_profile, knowledge):
    plan = allocate(
        make_profile(setting="outdoor", location="Reykjavik", event_date=date(2026, 7, 18)),
        knowledge,
    )
    assert shares(plan)["contingency"] == knowledge.budget_splits["birthday"]["contingency"]


def test_plated_at_exact_threshold(make_profile, knowledge):
    plated_from = knowledge.per_head_thresholds[Currency.INR].plated_from
    plan = allocate(make_profile(guest_count=40, budget_minor=plated_from * 40), knowledge)
    assert plan.catering_style is CateringStyle.PLATED


def test_buffet_just_below_plated_threshold(make_profile, knowledge):
    plated_from = knowledge.per_head_thresholds[Currency.INR].plated_from
    plan = allocate(make_profile(guest_count=40, budget_minor=plated_from * 40 - 40), knowledge)
    assert plan.catering_style is CateringStyle.BUFFET


def test_region_cost_multiplier_raises_threshold(make_profile, knowledge):
    plated_from = knowledge.per_head_thresholds[Currency.INR].plated_from
    plan = allocate(
        make_profile(guest_count=40, budget_minor=plated_from * 40, location="Mumbai"), knowledge
    )
    assert plan.catering_style is CateringStyle.BUFFET
    assert "x1.25" in plan.catering_reason


def test_low_per_head_community_event_goes_potluck(make_profile, knowledge):
    plan = allocate(
        make_profile(event_type="community_event", guest_count=200, budget_minor=50_000_00),
        knowledge,
    )
    assert plan.catering_style is CateringStyle.POTLUCK
    s = shares(plan)
    base = knowledge.budget_splits["community_event"]
    assert s["catering"] < base["catering"]
    assert s["contingency"] > base["contingency"]


def test_low_per_head_birthday_gets_simple_buffet(make_profile, knowledge):
    plan = allocate(make_profile(guest_count=100, budget_minor=10_000_00), knowledge)
    assert plan.catering_style is CateringStyle.BUFFET
    assert "economical" in plan.catering_reason


def test_community_event_never_plated(make_profile, knowledge):
    plan = allocate(make_profile(event_type="community_event", budget_minor=10**10), knowledge)
    assert plan.catering_style is CateringStyle.BUFFET


def test_dietary_flags_annotate_catering(make_profile, knowledge):
    plan = allocate(make_profile(dietary=["vegan", "nut_allergy"]), knowledge)
    catering = next(line for line in plan.lines if line.category == "catering")
    assert any("vegan" in n and "nut allergy" in n for n in catering.notes)


def test_profile_rejects_unknown_fields_and_bad_values(make_profile):
    with pytest.raises(ValidationError):
        make_profile(surprise="field")
    with pytest.raises(ValidationError):
        make_profile(guest_count=0)
    with pytest.raises(ValidationError):
        make_profile(currency="XYZ")
    with pytest.raises(ValidationError):
        make_profile(location="x" * 121)


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        (8_00_000_00, Currency.INR, "₹8,00,000"),
        (40_000_00, Currency.INR, "₹40,000"),
        (999_00, Currency.INR, "₹999"),
        (1_234_567_89, Currency.USD, "$1,234,567.89"),
        (-5_00, Currency.GBP, "-£5"),
    ],
)
def test_format_money(amount, currency, expected):
    assert format_money(amount, currency) == expected
