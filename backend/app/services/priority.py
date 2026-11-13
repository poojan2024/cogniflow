"""Weighted Task Priority Scoring Algorithm.

Pure, deterministic Python: no database, no AI, no network. The same inputs always give the same result,
and every result carries an explanation, so the score can be demonstrated and defended in the viva.

    score (0-100) = 100 x ( 0.40 x deadline_urgency
                          + 0.30 x task_importance
                          + 0.15 x activity_priority
                          + 0.15 x overdue_or_status_risk )

Every factor is first normalized to the range 0..1:

  deadline_urgency   no deadline -> 0.  Overdue -> 1.  Otherwise 1 - days_left/14, never below 0
                     (due today = 1.0, due in 7 days = 0.5, due in 14 or more days = 0).
  task_importance    (importance - 1) / 4      importance is the user's 1..5 rating.
  activity_priority  (priority - 1) / 4        priority of the activity the task belongs to, 1..5.
  overdue/status     overdue and incomplete = 1.0, not started (PENDING) = 0.5, IN_PROGRESS = 0.3.

Score -> level:  >= 80 CRITICAL,  >= 60 HIGH,  >= 35 MEDIUM,  otherwise LOW.
A COMPLETED task is never an active priority (score 0, is_active False).
The user may override the level manually; the calculated score and level are still reported.

IMPORTANT (honesty): the weights, the 14-day horizon, the status risk values and the thresholds are
design judgements chosen to give sensible rankings. They are NOT derived from data and NOT scientifically
proven. See docs/priority_algorithm.md for the reasoning behind each choice.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple

# ----------------------------------------------------------------- parameters
WEIGHTS = {"deadline": 0.40, "importance": 0.30, "activity": 0.15, "status": 0.15}
URGENCY_HORIZON_DAYS = 14
OVERDUE_RISK = 1.0
STATUS_RISK = {"PENDING": 0.5, "IN_PROGRESS": 0.3}
LEVELS = ("CRITICAL", "HIGH", "MEDIUM", "LOW")  # most to least urgent
LEVEL_THRESHOLDS = (("CRITICAL", 80.0), ("HIGH", 60.0), ("MEDIUM", 35.0))  # anything lower is LOW
SCALE_WORDS = {1: "very low", 2: "low", 3: "medium", 4: "high", 5: "very high"}

if abs(sum(WEIGHTS.values()) - 1.0) > 1e-9:  # fail loudly if someone edits the weights incorrectly
    raise RuntimeError("Priority weights must add up to 1.0")


# --------------------------------------------------------------------- result
@dataclass(frozen=True)
class Factor:
    name: str
    detail: str
    normalized: float  # 0..1
    weight: float
    points: float  # normalized x weight x 100 = contribution to the score


@dataclass(frozen=True)
class PriorityResult:
    score: float  # 0..100 (0 for completed tasks)
    level: str  # the level to show: the manual override if set, otherwise the calculated level
    calculated_level: str  # what the algorithm alone produced
    is_overridden: bool
    is_active: bool  # False for completed tasks
    explanation: str
    factors: Tuple[Factor, ...]


# -------------------------------------------------------------------- helpers
def deadline_urgency(due_date: Optional[date], today: date) -> Tuple[float, Optional[int]]:
    """Return (urgency 0..1, days_left). days_left is None when there is no deadline, negative when overdue."""
    if due_date is None:
        return 0.0, None
    days_left = (due_date - today).days
    if days_left < 0:
        return 1.0, days_left
    return max(0.0, 1.0 - days_left / URGENCY_HORIZON_DAYS), days_left


def level_for_score(score: float) -> str:
    for level, minimum in LEVEL_THRESHOLDS:
        if score >= minimum:
            return level
    return "LOW"


def _days(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


def _join(phrases: list) -> str:
    return phrases[0] if len(phrases) == 1 else ", ".join(phrases[:-1]) + " and " + phrases[-1]


# ----------------------------------------------------------------- the algorithm
def calculate_priority(
    *,
    due_date: Optional[date],
    importance: int,
    status: str,
    activity_priority: int,
    today: date,
    manual_priority: Optional[str] = None,
) -> PriorityResult:
    if not 1 <= importance <= 5:
        raise ValueError("importance must be between 1 and 5")
    if not 1 <= activity_priority <= 5:
        raise ValueError("activity_priority must be between 1 and 5")
    if status not in ("PENDING", "IN_PROGRESS", "COMPLETED"):
        raise ValueError(f"unknown task status: {status}")
    if manual_priority is not None and manual_priority not in LEVELS:
        raise ValueError(f"unknown manual priority: {manual_priority}")

    # A completed task is finished work: never an active priority, whatever else is set.
    if status == "COMPLETED":
        return PriorityResult(
            score=0.0,
            level="LOW",
            calculated_level="LOW",
            is_overridden=False,
            is_active=False,
            explanation="The task is completed, so it is not an active priority.",
            factors=(),
        )

    urgency, days_left = deadline_urgency(due_date, today)
    overdue = days_left is not None and days_left < 0
    importance_n = (importance - 1) / 4
    activity_n = (activity_priority - 1) / 4
    status_n = OVERDUE_RISK if overdue else STATUS_RISK[status]

    # (name, human detail, normalized value, weight key, phrase used in the explanation)
    if days_left is None:
        deadline_detail = deadline_phrase = "no deadline is set"
    elif overdue:
        deadline_detail = f"overdue by {_days(-days_left)}"
        deadline_phrase = f"the deadline passed {_days(-days_left)} ago"
    elif days_left == 0:
        deadline_detail = "due today"
        deadline_phrase = "the deadline is today"
    elif days_left <= 7:
        deadline_detail = f"due in {_days(days_left)}"
        deadline_phrase = f"the deadline is approaching ({_days(days_left)} left)"
    else:
        deadline_detail = f"due in {_days(days_left)}"
        deadline_phrase = f"the deadline is {_days(days_left)} away"

    if overdue:
        status_detail, status_phrase = "overdue and incomplete", "the task is overdue and still incomplete"
    elif status == "PENDING":
        status_detail, status_phrase = "not started", "the task has not been started"
    else:
        status_detail, status_phrase = "in progress", "the task is in progress"

    rows = [
        ("Deadline urgency", deadline_detail, urgency, "deadline", deadline_phrase),
        ("Task importance", f"{importance}/5", importance_n, "importance",
         f"the task importance is {SCALE_WORDS[importance]} ({importance}/5)"),
        ("Activity priority", f"{activity_priority}/5", activity_n, "activity",
         f"the activity priority is {SCALE_WORDS[activity_priority]} ({activity_priority}/5)"),
        ("Overdue / status", status_detail, status_n, "status", status_phrase),
    ]

    factors = tuple(
        Factor(name, detail, round(norm, 4), WEIGHTS[key], round(WEIGHTS[key] * norm * 100, 2))
        for name, detail, norm, key, _ in rows
    )
    score = round(sum(WEIGHTS[key] * norm * 100 for _, _, norm, key, _ in rows), 2)
    calculated_level = level_for_score(score)
    reasons = _join([phrase for *_, phrase in rows])

    if manual_priority is not None:
        explanation = (
            f"{manual_priority.capitalize()} priority (set manually; the calculated priority is "
            f"{calculated_level.capitalize()}, score {score:.1f}/100). The calculation considered: {reasons}."
        )
        return PriorityResult(score, manual_priority, calculated_level, True, True, explanation, factors)

    explanation = f"{calculated_level.capitalize()} priority (score {score:.1f}/100) because {reasons}."
    return PriorityResult(score, calculated_level, calculated_level, False, True, explanation, factors)
