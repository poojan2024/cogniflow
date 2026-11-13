"""Unit tests for the Weighted Task Priority Scoring Algorithm.

These tests need no database and no HTTP client. TODAY is fixed so results never depend on the real date.
"""
from datetime import date, timedelta

from app.services.priority import (
    LEVEL_THRESHOLDS,
    WEIGHTS,
    calculate_priority,
    deadline_urgency,
    level_for_score,
)

TODAY = date(2026, 10, 7)


def calc(days=None, importance=3, status="PENDING", activity=3, manual=None):
    """days = days until the deadline (negative = overdue, None = no deadline)."""
    due = None if days is None else TODAY + timedelta(days=days)
    return calculate_priority(
        due_date=due, importance=importance, status=status,
        activity_priority=activity, today=TODAY, manual_priority=manual,
    )


# ---------------------------------------------- the four cases from the project brief
def test_case1_far_deadline_low_importance_is_low():
    r = calc(days=30, importance=1, activity=3)
    assert (r.score, r.level) == (15.0, "LOW")


def test_case2_approaching_deadline_high_importance_is_high():
    r = calc(days=3, importance=5, activity=3)
    assert (r.score, r.level) == (76.43, "HIGH")


def test_case3_overdue_high_importance_is_critical():
    r = calc(days=-2, importance=5, activity=3)
    assert (r.score, r.level) == (92.5, "CRITICAL")


def test_case4_completed_task_is_not_an_active_priority():
    r = calc(days=-2, importance=5, activity=5, status="COMPLETED")
    assert r.is_active is False and r.score == 0.0 and r.level == "LOW" and r.factors == ()


# ------------------------------------------------------------------ factor details
def test_deadline_urgency_values():
    assert deadline_urgency(None, TODAY) == (0.0, None)
    assert deadline_urgency(TODAY, TODAY) == (1.0, 0)  # due today
    assert deadline_urgency(TODAY + timedelta(days=7), TODAY)[0] == 0.5
    assert deadline_urgency(TODAY + timedelta(days=14), TODAY)[0] == 0.0
    assert deadline_urgency(TODAY + timedelta(days=90), TODAY)[0] == 0.0
    assert deadline_urgency(TODAY - timedelta(days=1), TODAY) == (1.0, -1)  # overdue


def test_weights_sum_to_one_and_thresholds_descend():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9
    minimums = [m for _, m in LEVEL_THRESHOLDS]
    assert minimums == sorted(minimums, reverse=True)


def test_level_boundaries():
    assert level_for_score(80.0) == "CRITICAL" and level_for_score(79.99) == "HIGH"
    assert level_for_score(60.0) == "HIGH" and level_for_score(59.99) == "MEDIUM"
    assert level_for_score(35.0) == "MEDIUM" and level_for_score(34.99) == "LOW"


def test_score_stays_between_0_and_100():
    highest = calc(days=-10, importance=5, activity=5)
    lowest_open = calc(days=None, importance=1, activity=1, status="IN_PROGRESS")
    assert highest.score == 100.0 and highest.level == "CRITICAL"
    assert lowest_open.score == 4.5 and lowest_open.level == "LOW"


def test_factor_points_add_up_to_the_score():
    r = calc(days=3, importance=4, activity=2)
    assert abs(sum(f.points for f in r.factors) - r.score) < 0.05  # only rounding differences


# ------------------------------------------------ monotonic behaviour (sanity checks)
def test_more_importance_never_lowers_the_score():
    scores = [calc(days=5, importance=i).score for i in range(1, 6)]
    assert scores == sorted(scores) and scores[0] < scores[-1]


def test_higher_activity_priority_never_lowers_the_score():
    scores = [calc(days=5, activity=a).score for a in range(1, 6)]
    assert scores == sorted(scores) and scores[0] < scores[-1]


def test_closer_deadline_never_lowers_the_score():
    scores = [calc(days=d).score for d in range(30, -6, -1)]  # 30 days away ... 5 days overdue
    assert scores == sorted(scores) and scores[0] < scores[-1]


def test_overdue_low_importance_outranks_distant_high_importance():
    overdue_minor = calc(days=-1, importance=1)
    distant_major = calc(days=40, importance=5)
    assert overdue_minor.score > distant_major.score


def test_started_task_scores_lower_than_unstarted_one():
    assert calc(days=5, status="IN_PROGRESS").score < calc(days=5, status="PENDING").score


def test_no_deadline_gives_zero_urgency():
    r = calc(days=None, importance=5, activity=5)
    assert r.factors[0].normalized == 0.0 and "no deadline" in r.explanation


# ------------------------------------------------------------------ manual override
def test_manual_override_changes_level_but_reports_calculation():
    r = calc(days=30, importance=1, manual="CRITICAL")
    assert r.is_overridden and r.level == "CRITICAL" and r.calculated_level == "LOW"
    assert r.score == 15.0 and "manually" in r.explanation


def test_override_does_not_revive_a_completed_task():
    r = calc(days=1, importance=5, status="COMPLETED", manual="CRITICAL")
    assert r.is_active is False and r.is_overridden is False


# ----------------------------------------------------- explanation + determinism
def test_explanation_is_human_readable():
    r = calc(days=-2, importance=5, activity=3)
    assert r.explanation.startswith("Critical priority (score 92.5/100)")
    assert "the deadline passed 2 days ago" in r.explanation
    assert "importance is very high (5/5)" in r.explanation
    assert "overdue and still incomplete" in r.explanation


def test_same_inputs_give_identical_results():
    assert calc(days=4, importance=4, activity=2) == calc(days=4, importance=4, activity=2)


def test_invalid_inputs_are_rejected():
    for kwargs in ({"importance": 0}, {"importance": 6}, {"activity": 0}, {"activity": 9},
                   {"status": "DONE"}, {"manual": "URGENT"}):
        try:
            calc(days=1, **kwargs)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {kwargs}")
