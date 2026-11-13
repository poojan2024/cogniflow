"""The priority score as exposed by the task API (dates are relative to the real today)."""
from datetime import date, timedelta

from tests.conftest import make_activity


def due_in(days):
    return (date.today() + timedelta(days=days)).isoformat()


def add_task(client, headers, aid, title, days=None, importance=3, **extra):
    body = {"title": title, "importance": importance, **extra}
    if days is not None:
        body["due_date"] = due_in(days)
    res = client.post(f"/activities/{aid}/tasks", json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def test_task_response_contains_score_level_explanation_and_factors(client, alice):
    aid = make_activity(client, alice, priority=3)["id"]
    task = add_task(client, alice, aid, "Submit report", days=-2, importance=5)
    p = task["priority"]
    assert p["level"] == "CRITICAL" and p["calculated_level"] == "CRITICAL"
    assert p["score"] == 92.5 and p["is_active"] is True and p["is_overridden"] is False
    assert [f["name"] for f in p["factors"]] == [
        "Deadline urgency", "Task importance", "Activity priority", "Overdue / status",
    ]
    assert "deadline passed 2 days ago" in p["explanation"]


def test_distant_unimportant_task_is_low(client, alice):
    aid = make_activity(client, alice, priority=3)["id"]
    task = add_task(client, alice, aid, "Someday", days=30, importance=1)
    assert task["priority"]["level"] == "LOW" and task["priority"]["score"] == 15.0


def test_completing_a_task_makes_it_inactive(client, alice):
    aid = make_activity(client, alice, priority=3)["id"]
    task = add_task(client, alice, aid, "Urgent", days=-1, importance=5)
    done = client.patch(f"/activities/{aid}/tasks/{task['id']}", json={"status": "COMPLETED"}, headers=alice).json()
    assert done["priority"]["is_active"] is False and done["priority"]["score"] == 0.0


def test_manual_override_and_clearing_it(client, alice):
    aid = make_activity(client, alice, priority=3)["id"]
    task = add_task(client, alice, aid, "Minor", days=30, importance=1)
    url = f"/activities/{aid}/tasks/{task['id']}"
    over = client.patch(url, json={"manual_priority": "CRITICAL"}, headers=alice).json()["priority"]
    assert over["level"] == "CRITICAL" and over["calculated_level"] == "LOW" and over["is_overridden"] is True
    back = client.patch(url, json={"manual_priority": None}, headers=alice).json()["priority"]
    assert back["level"] == "LOW" and back["is_overridden"] is False


def test_activity_priority_affects_task_score(client, alice):
    aid = make_activity(client, alice, priority=1)["id"]
    task = add_task(client, alice, aid, "T", days=5, importance=3)
    before = task["priority"]["score"]
    client.patch(f"/activities/{aid}", json={"priority": 5}, headers=alice)
    after = client.get(f"/activities/{aid}/tasks/{task['id']}", headers=alice).json()["priority"]["score"]
    assert after > before


def test_list_sorted_by_priority_puts_urgent_first_and_completed_last(client, alice):
    aid = make_activity(client, alice, priority=3)["id"]
    add_task(client, alice, aid, "distant", days=40, importance=2)
    done = add_task(client, alice, aid, "finished", days=-5, importance=5)
    add_task(client, alice, aid, "overdue", days=-3, importance=5)
    add_task(client, alice, aid, "soon", days=3, importance=4)
    client.patch(f"/activities/{aid}/tasks/{done['id']}", json={"status": "COMPLETED"}, headers=alice)
    res = client.get(f"/activities/{aid}/tasks", params={"sort": "priority"}, headers=alice).json()
    assert [t["title"] for t in res] == ["overdue", "soon", "distant", "finished"]


def test_filter_by_priority_level_only_returns_active_tasks(client, alice):
    aid = make_activity(client, alice, priority=3)["id"]
    add_task(client, alice, aid, "critical one", days=-3, importance=5)
    gone = add_task(client, alice, aid, "completed critical", days=-3, importance=5)
    add_task(client, alice, aid, "low one", days=40, importance=1)
    client.patch(f"/activities/{aid}/tasks/{gone['id']}", json={"status": "COMPLETED"}, headers=alice)
    res = client.get(f"/activities/{aid}/tasks", params={"priority_level": "CRITICAL"}, headers=alice).json()
    assert [t["title"] for t in res] == ["critical one"]


def test_invalid_sort_or_level_is_422(client, alice):
    aid = make_activity(client, alice)["id"]
    assert client.get(f"/activities/{aid}/tasks", params={"sort": "random"}, headers=alice).status_code == 422
    assert client.get(f"/activities/{aid}/tasks", params={"priority_level": "URGENT"}, headers=alice).status_code == 422
