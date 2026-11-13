"""Task CRUD, completion, filters, manual priority override, and ownership."""
from tests.conftest import make_activity


def new_task(client, headers, activity_id, **overrides):
    body = {"title": "Write chapter 1", "importance": 4, "due_date": "2026-11-30"}
    body.update(overrides)
    res = client.post(f"/activities/{activity_id}/tasks", json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def test_create_and_list_tasks(client, alice):
    aid = make_activity(client, alice)["id"]
    task = new_task(client, alice, aid)
    assert task["status"] == "PENDING" and task["completed_at"] is None
    listed = client.get(f"/activities/{aid}/tasks", headers=alice).json()
    assert [t["id"] for t in listed] == [task["id"]]


def test_task_validation(client, alice):
    aid = make_activity(client, alice)["id"]
    url = f"/activities/{aid}/tasks"
    assert client.post(url, json={"title": ""}, headers=alice).status_code == 422
    assert client.post(url, json={"title": "x", "importance": 0}, headers=alice).status_code == 422
    assert client.post(url, json={"title": "x", "status": "DONE"}, headers=alice).status_code == 422
    assert client.post(url, json={"title": "x", "due_date": "not-a-date"}, headers=alice).status_code == 422


def test_update_task(client, alice):
    aid = make_activity(client, alice)["id"]
    task = new_task(client, alice, aid)
    res = client.patch(f"/activities/{aid}/tasks/{task['id']}", json={"title": "Renamed", "importance": 5}, headers=alice)
    assert res.status_code == 200
    assert res.json()["title"] == "Renamed" and res.json()["importance"] == 5


def test_completing_sets_timestamp_and_reopening_clears_it(client, alice):
    aid = make_activity(client, alice)["id"]
    task = new_task(client, alice, aid)
    url = f"/activities/{aid}/tasks/{task['id']}"
    done = client.patch(url, json={"status": "COMPLETED"}, headers=alice).json()
    assert done["status"] == "COMPLETED" and done["completed_at"] is not None
    reopened = client.patch(url, json={"status": "IN_PROGRESS"}, headers=alice).json()
    assert reopened["completed_at"] is None


def test_filter_pending_and_completed(client, alice):
    aid = make_activity(client, alice)["id"]
    a = new_task(client, alice, aid, title="A")
    new_task(client, alice, aid, title="B")
    client.patch(f"/activities/{aid}/tasks/{a['id']}", json={"status": "COMPLETED"}, headers=alice)
    url = f"/activities/{aid}/tasks"
    assert [t["title"] for t in client.get(url, params={"status_filter": "COMPLETED"}, headers=alice).json()] == ["A"]
    assert [t["title"] for t in client.get(url, params={"status_filter": "PENDING"}, headers=alice).json()] == ["B"]


def test_manual_priority_override_can_be_set_and_cleared(client, alice):
    aid = make_activity(client, alice)["id"]
    task = new_task(client, alice, aid)
    url = f"/activities/{aid}/tasks/{task['id']}"
    assert client.patch(url, json={"manual_priority": "CRITICAL"}, headers=alice).json()["manual_priority"] == "CRITICAL"
    assert client.patch(url, json={"manual_priority": None}, headers=alice).json()["manual_priority"] is None
    assert client.patch(url, json={"manual_priority": "URGENT"}, headers=alice).status_code == 422


def test_delete_task(client, alice):
    aid = make_activity(client, alice)["id"]
    task = new_task(client, alice, aid)
    url = f"/activities/{aid}/tasks/{task['id']}"
    assert client.delete(url, headers=alice).status_code == 204
    assert client.get(url, headers=alice).status_code == 404


def test_task_events_are_logged_in_history(client, alice):
    aid = make_activity(client, alice)["id"]
    task = new_task(client, alice, aid)
    client.patch(f"/activities/{aid}/tasks/{task['id']}", json={"status": "COMPLETED"}, headers=alice)
    actions = [h["action"] for h in client.get(f"/activities/{aid}/history", headers=alice).json()["items"]]
    assert "TASK_CREATED" in actions and "TASK_COMPLETED" in actions


# ---------------------------------------------------------------- ownership
def test_other_user_cannot_access_tasks_of_my_activity(client, alice, bob):
    aid = make_activity(client, alice)["id"]
    task = new_task(client, alice, aid)
    base = f"/activities/{aid}/tasks"
    assert client.get(base, headers=bob).status_code == 404
    assert client.post(base, json={"title": "injected"}, headers=bob).status_code == 404
    assert client.get(f"{base}/{task['id']}", headers=bob).status_code == 404
    assert client.patch(f"{base}/{task['id']}", json={"title": "hacked"}, headers=bob).status_code == 404
    assert client.delete(f"{base}/{task['id']}", headers=bob).status_code == 404
    assert client.get(f"{base}/{task['id']}", headers=alice).json()["title"] == task["title"]


def test_task_id_from_another_activity_is_not_reachable(client, alice, bob):
    """Bob owns his own activity, but must not read Alice's task by guessing its id under his own activity."""
    alice_task = new_task(client, alice, make_activity(client, alice)["id"])
    bob_aid = make_activity(client, bob, title="Bob activity")["id"]
    assert client.get(f"/activities/{bob_aid}/tasks/{alice_task['id']}", headers=bob).status_code == 404
    assert client.delete(f"/activities/{bob_aid}/tasks/{alice_task['id']}", headers=bob).status_code == 404


def test_tasks_require_login(client, alice):
    aid = make_activity(client, alice)["id"]
    assert client.get(f"/activities/{aid}/tasks").status_code == 401
