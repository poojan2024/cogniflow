"""Pure tests (no database, no HTTP) for the dashboard calculations and the search snippet helper."""
from datetime import date, timedelta

from app.services.dashboard_calc import TaskRow, merge_deadlines, summarize_tasks
from app.services.snippets import make_snippet

TODAY = date(2026, 10, 7)


def task(id, days=None, importance=3, status="PENDING", manual=None, act_id=1, act_title="Project", act_priority=3):
    due = None if days is None else TODAY + timedelta(days=days)
    return TaskRow(id, f"task {id}", due, importance, status, manual, act_id, act_title, act_priority)


# ------------------------------------------------------------------ snippets
def test_snippet_shows_text_around_the_match():
    text = "x" * 100 + " the semester exam starts soon " + "y" * 100
    snippet = make_snippet(text, "EXAM")
    assert "semester exam starts" in snippet and snippet.startswith("…") and snippet.endswith("…")


def test_snippet_without_match_returns_the_start():
    assert make_snippet("short text only", "zzz") == "short text only"
    assert make_snippet("a" * 300, "zzz").endswith("…")


def test_snippet_collapses_whitespace_and_handles_empty():
    assert make_snippet("line one\n\n  line   two", "line two") == "line one line two"
    assert make_snippet(None, "x") == "" and make_snippet("", "x") == ""


# ---------------------------------------------------------- upcoming deadlines
def test_deadlines_include_today_and_window_edge_but_not_past_or_far():
    tasks = [task(1, days=0), task(2, days=30), task(3, days=31), task(4, days=-1), task(5, days=None)]
    result = merge_deadlines([], tasks, TODAY)
    assert [d.id for d in result] == [1, 2]
    assert [d.days_left for d in result] == [0, 30]


def test_deadlines_merge_activities_and_tasks_sorted_with_activities_first_on_a_tie():
    activities = [(10, "Exam", TODAY + timedelta(days=5)), (11, "Trip", TODAY + timedelta(days=2))]
    tasks = [task(1, days=5), task(2, days=1)]
    result = merge_deadlines(activities, tasks, TODAY)
    assert [(d.kind, d.id) for d in result] == [("task", 2), ("activity", 11), ("activity", 10), ("task", 1)]


def test_completed_tasks_and_missing_dates_are_not_deadlines():
    assert merge_deadlines([(1, "A", None)], [task(1, days=3, status="COMPLETED")], TODAY) == []


def test_deadlines_respect_the_limit():
    tasks = [task(i, days=i % 5) for i in range(1, 30)]
    assert len(merge_deadlines([], tasks, TODAY, limit=10)) == 10


# ------------------------------------------------------------ task summary
def test_summary_counts_levels_and_overdue():
    rows = [
        task(1, days=-2, importance=5),  # overdue, important  -> CRITICAL (92.5)
        task(2, days=3, importance=5),  # soon, important      -> HIGH (76.43)
        task(3, days=30, importance=1),  # far, minor           -> LOW (15.0)
        task(4, days=-1, importance=1, status="COMPLETED"),  # ignored: completed
    ]
    counts, overdue, urgent = summarize_tasks(rows, TODAY)
    assert counts == {"CRITICAL": 1, "HIGH": 1, "MEDIUM": 0, "LOW": 1}
    assert overdue == 1  # the completed overdue task does not count
    assert [(u.id, u.level) for u in urgent] == [(1, "CRITICAL"), (2, "HIGH")]
    assert urgent[0].score == 92.5 and "deadline passed 2 days ago" in urgent[0].explanation


def test_summary_uses_manual_override_for_counts_and_urgent_list():
    rows = [task(1, days=30, importance=1, manual="CRITICAL")]
    counts, _, urgent = summarize_tasks(rows, TODAY)
    assert counts["CRITICAL"] == 1 and urgent[0].level == "CRITICAL"


def test_urgent_list_is_ordered_by_level_then_score_and_limited():
    rows = [task(i, days=-i, importance=5) for i in range(1, 9)]  # all CRITICAL
    _, _, urgent = summarize_tasks(rows, TODAY, top=5)
    assert len(urgent) == 5
    assert [u.score for u in urgent] == sorted((u.score for u in urgent), reverse=True)


def test_summary_of_nothing_is_all_zero():
    assert summarize_tasks([], TODAY) == ({"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}, 0, [])
