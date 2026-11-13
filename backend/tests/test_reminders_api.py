"""Reminders and notifications. Reminder times must carry a time zone and are stored as UTC."""
from datetime import datetime, timedelta, timezone

from tests.conftest import make_activity


def when(**delta):
    """An ISO timestamp with an explicit offset, relative to now."""
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def add_reminder(client, headers, aid, title="Submit report", remind_at=None, **extra):
    body = {"title": title, "remind_at": remind_at or when(days=1), **extra}
    res = client.post(f"/activities/{aid}/reminders", json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def notifications(client, headers, **params):
    res = client.get("/notifications", params=params, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


# ---------------------------------------------------------------- CRUD
def test_create_list_get_update_delete_reminder(client, alice):
    aid = make_activity(client, alice)["id"]
    r = add_reminder(client, alice, aid)
    assert r["is_triggered"] is False and r["activity_id"] == aid
    base = f"/activities/{aid}/reminders"
    assert [x["id"] for x in client.get(base, headers=alice).json()] == [r["id"]]
    assert client.get(f"{base}/{r['id']}", headers=alice).json()["title"] == "Submit report"
    upd = client.patch(f"{base}/{r['id']}", json={"title": "Submit final report"}, headers=alice)
    assert upd.status_code == 200 and upd.json()["title"] == "Submit final report"
    assert client.delete(f"{base}/{r['id']}", headers=alice).status_code == 204
    assert client.get(f"{base}/{r['id']}", headers=alice).status_code == 404


def test_time_zone_is_required_and_stored_as_utc(client, alice):
    aid = make_activity(client, alice)["id"]
    url = f"/activities/{aid}/reminders"
    naive = client.post(url, json={"title": "x", "remind_at": "2026-10-12T09:00:00"}, headers=alice)
    assert naive.status_code == 422 and "time zone" in naive.text
    ok = add_reminder(client, alice, aid, remind_at="2026-10-12T09:00:00+05:30")
    assert datetime.fromisoformat(ok["remind_at"]) == datetime(2026, 10, 12, 3, 30, tzinfo=timezone.utc)


def test_reminder_validation(client, alice):
    aid = make_activity(client, alice)["id"]
    url = f"/activities/{aid}/reminders"
    assert client.post(url, json={"title": "  ", "remind_at": when(days=1)}, headers=alice).status_code == 422
    assert client.post(url, json={"title": "x", "remind_at": "not a date"}, headers=alice).status_code == 422
    assert client.post(url, json={"remind_at": when(days=1)}, headers=alice).status_code == 422


def test_pending_only_filter(client, alice):
    aid = make_activity(client, alice)["id"]
    add_reminder(client, alice, aid, "past", when(hours=-1))
    add_reminder(client, alice, aid, "future", when(days=2))
    notifications(client, alice)  # triggers the past one
    base = f"/activities/{aid}/reminders"
    assert len(client.get(base, headers=alice).json()) == 2
    assert [r["title"] for r in client.get(base, params={"pending_only": "true"}, headers=alice).json()] == ["future"]


def test_reminder_can_be_linked_to_a_task_of_the_same_activity_only(client, alice):
    a1 = make_activity(client, alice)["id"]
    a2 = make_activity(client, alice, title="Other")["id"]
    own_task = client.post(f"/activities/{a1}/tasks", json={"title": "t"}, headers=alice).json()["id"]
    foreign_task = client.post(f"/activities/{a2}/tasks", json={"title": "t"}, headers=alice).json()["id"]
    assert add_reminder(client, alice, a1, task_id=own_task)["task_id"] == own_task
    bad = client.post(f"/activities/{a1}/reminders", json={"title": "x", "remind_at": when(days=1), "task_id": foreign_task}, headers=alice)
    assert bad.status_code == 404


def test_reminder_creation_is_logged(client, alice):
    aid = make_activity(client, alice)["id"]
    add_reminder(client, alice, aid)
    actions = [h["action"] for h in client.get(f"/activities/{aid}/history", headers=alice).json()["items"]]
    assert "REMINDER_CREATED" in actions


# ----------------------------------------------- trigger -> notification logic
def test_due_reminder_becomes_exactly_one_notification(client, alice):
    aid = make_activity(client, alice, title="MCA Project")["id"]
    add_reminder(client, alice, aid, "Submit synopsis", when(minutes=-5))
    first = notifications(client, alice)
    assert first["total"] == 1 and first["unread_count"] == 1
    assert "Submit synopsis" in first["items"][0]["message"] and "MCA Project" in first["items"][0]["message"]
    assert notifications(client, alice)["total"] == 1  # loading again does not create a duplicate
    assert client.get(f"/activities/{aid}/reminders", headers=alice).json()[0]["is_triggered"] is True


def test_future_reminder_does_not_notify_yet(client, alice):
    aid = make_activity(client, alice)["id"]
    add_reminder(client, alice, aid, "later", when(days=3))
    assert notifications(client, alice)["total"] == 0


def test_rescheduling_a_triggered_reminder_arms_it_again(client, alice):
    aid = make_activity(client, alice)["id"]
    r = add_reminder(client, alice, aid, "x", when(minutes=-5))
    assert notifications(client, alice)["total"] == 1
    client.patch(f"/activities/{aid}/reminders/{r['id']}", json={"remind_at": when(days=2)}, headers=alice)
    assert client.get(f"/activities/{aid}/reminders/{r['id']}", headers=alice).json()["is_triggered"] is False
    assert notifications(client, alice)["total"] == 1  # nothing new until the new time
    client.patch(f"/activities/{aid}/reminders/{r['id']}", json={"remind_at": when(minutes=-1)}, headers=alice)
    assert notifications(client, alice)["total"] == 2


def test_deleting_a_reminder_keeps_its_notification(client, alice):
    aid = make_activity(client, alice)["id"]
    r = add_reminder(client, alice, aid, "x", when(minutes=-5))
    notifications(client, alice)
    client.delete(f"/activities/{aid}/reminders/{r['id']}", headers=alice)
    items = notifications(client, alice)["items"]
    assert len(items) == 1 and items[0]["reminder_id"] is None


# ------------------------------------------------------------ notifications
def test_mark_read_read_all_and_delete(client, alice):
    aid = make_activity(client, alice)["id"]
    for i in range(3):
        add_reminder(client, alice, aid, f"r{i}", when(minutes=-5 - i))
    data = notifications(client, alice)
    assert data["total"] == 3 and data["unread_count"] == 3
    first = data["items"][0]["id"]
    assert client.post(f"/notifications/{first}/read", headers=alice).json()["is_read"] is True
    assert notifications(client, alice)["unread_count"] == 2
    assert notifications(client, alice, unread_only="true")["total"] == 2
    assert client.post("/notifications/read-all", headers=alice).json() == {"updated": 2}
    assert notifications(client, alice)["unread_count"] == 0
    assert client.delete(f"/notifications/{first}", headers=alice).status_code == 204
    assert notifications(client, alice)["total"] == 2


def test_notification_pagination(client, alice):
    aid = make_activity(client, alice)["id"]
    for i in range(3):
        add_reminder(client, alice, aid, f"r{i}", when(minutes=-5))
    page = notifications(client, alice, page=2, page_size=2)
    assert page["total"] == 3 and len(page["items"]) == 1


# ---------------------------------------------------------------- ownership
def test_other_user_cannot_use_my_reminders_or_notifications(client, alice, bob):
    aid = make_activity(client, alice)["id"]
    r = add_reminder(client, alice, aid, "private", when(minutes=-5))
    base = f"/activities/{aid}/reminders"
    assert client.get(base, headers=bob).status_code == 404
    assert client.post(base, json={"title": "x", "remind_at": when(days=1)}, headers=bob).status_code == 404
    assert client.patch(f"{base}/{r['id']}", json={"title": "hacked"}, headers=bob).status_code == 404
    assert client.delete(f"{base}/{r['id']}", headers=bob).status_code == 404

    mine = notifications(client, alice)["items"][0]["id"]
    assert notifications(client, bob)["total"] == 0  # Bob's load must not trigger or reveal Alice's reminder
    assert client.post(f"/notifications/{mine}/read", headers=bob).status_code == 404
    assert client.delete(f"/notifications/{mine}", headers=bob).status_code == 404
    assert notifications(client, alice)["unread_count"] == 1  # untouched


def test_reminders_and_notifications_require_login(client, alice):
    aid = make_activity(client, alice)["id"]
    assert client.get(f"/activities/{aid}/reminders").status_code == 401
    assert client.get("/notifications").status_code == 401
