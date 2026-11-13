"""Pure dashboard calculations (no database, no web framework): upcoming deadlines and the task priority summary."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from app.services.priority import LEVELS, calculate_priority

DEADLINE_WINDOW_DAYS = 30
MAX_DEADLINES = 10
MAX_PRIORITY_TASKS = 5


@dataclass(frozen=True)
class TaskRow:
    id: int
    title: str
    due_date: Optional[date]
    importance: int
    status: str
    manual_priority: Optional[str]
    activity_id: int
    activity_title: str
    activity_priority: int


@dataclass(frozen=True)
class DeadlineEntry:
    kind: str  # "activity" or "task"
    id: int
    title: str
    activity_id: int
    activity_title: str
    due_date: date
    days_left: int


@dataclass(frozen=True)
class PriorityTaskEntry:
    id: int
    title: str
    activity_id: int
    activity_title: str
    due_date: Optional[date]
    level: str
    score: float
    explanation: str


def merge_deadlines(
    activity_rows: Iterable[Tuple[int, str, Optional[date]]],  # (id, title, deadline)
    task_rows: Iterable[TaskRow],
    today: date,
    window_days: int = DEADLINE_WINDOW_DAYS,
    limit: int = MAX_DEADLINES,
) -> List[DeadlineEntry]:
    """Open activities and open tasks whose date is today or within `window_days`, earliest first."""
    last = today + timedelta(days=window_days)
    items: List[DeadlineEntry] = []
    for activity_id, title, deadline in activity_rows:
        if deadline is not None and today <= deadline <= last:
            items.append(DeadlineEntry("activity", activity_id, title, activity_id, title, deadline, (deadline - today).days))
    for t in task_rows:
        if t.status != "COMPLETED" and t.due_date is not None and today <= t.due_date <= last:
            items.append(DeadlineEntry("task", t.id, t.title, t.activity_id, t.activity_title, t.due_date, (t.due_date - today).days))
    items.sort(key=lambda i: (i.due_date, i.kind, i.id))  # same day: activities first
    return items[:limit]


def summarize_tasks(
    task_rows: Sequence[TaskRow], today: date, top: int = MAX_PRIORITY_TASKS
) -> Tuple[Dict[str, int], int, List[PriorityTaskEntry]]:
    """(count of open tasks per priority level, number of overdue open tasks, most urgent Critical/High tasks)."""
    counts = {level: 0 for level in LEVELS}
    overdue = 0
    urgent = []
    for t in task_rows:
        if t.status == "COMPLETED":
            continue
        result = calculate_priority(
            due_date=t.due_date, importance=t.importance, status=t.status,
            activity_priority=t.activity_priority, today=today, manual_priority=t.manual_priority,
        )
        counts[result.level] += 1
        if t.due_date is not None and t.due_date < today:
            overdue += 1
        if result.level in ("CRITICAL", "HIGH"):
            urgent.append((LEVELS.index(result.level), -result.score, t.id, PriorityTaskEntry(
                t.id, t.title, t.activity_id, t.activity_title, t.due_date, result.level, result.score, result.explanation)))
    urgent.sort(key=lambda x: x[:3])
    return counts, overdue, [u[3] for u in urgent[:top]]
