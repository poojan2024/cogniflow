"""Dashboard summary: numbers, lists, expense totals, attention counters, and ownership."""
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from tests.conftest import make_activity


def day(offset):
    return (date.today() + timedelta(days=offset)).isoformat()


def dashboard(client, headers):
    res = client.get("/dashboard", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def add_task(client, headers, aid, title, days=None, importance=3, **extra):
    body = {"title": title, "importance": importance, **extra}
    if days is not None:
        body["due_date"] = day(days)
    res = client.post(f"/activities/{aid}/tasks", json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def test_empty_dashboard_is_all_zero(client, alice):
    d = dashboard(client, alice)
    assert d["overview"]["total_activities"] == 0 and d["overview"]["pending_tasks"] == 0
    assert d["overview"]["open_tasks_by_priority"] == {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    assert d["upcoming_deadlines"] == [] and d["high_priority_tasks"] == [] and d["recent_activity"] == []
    assert Decimal(d["expenses"]["total"]) == Decimal("0.00")
    assert d["attention"] == {"unread_notifications": 0, "pending_suggestions": 0, "documents_needing_review": 0}


def test_overview_counts_activities_and_tasks(client, alice):
    a1 = make_activity(client, alice, priority=3)["id"]
    make_activity(client, alice, title="On hold", status="ON_HOLD")
    make_activity(client, alice, title="Done", status="COMPLETED")
    add_task(client, alice, a1, "overdue important", days=-2, importance=5)  # CRITICAL, overdue
    add_task(client, alice, a1, "soon important", days=3, importance=5)  # HIGH
    add_task(client, alice, a1, "far minor", days=30, importance=1)  # LOW
    finished = add_task(client, alice, a1, "finished", days=-1, importance=5)
    client.patch(f"/activities/{a1}/tasks/{finished['id']}", json={"status": "COMPLETED"}, headers=alice)

    o = dashboard(client, alice)["overview"]
    assert o["total_activities"] == 3 and o["active_activities"] == 1
    assert o["activities_by_status"] == {"ACTIVE": 1, "ON_HOLD": 1, "COMPLETED": 1}
    assert (o["pending_tasks"], o["completed_tasks"], o["overdue_tasks"]) == (3, 1, 1)
    assert o["open_tasks_by_priority"] == {"CRITICAL": 1, "HIGH": 1, "MEDIUM": 0, "LOW": 1}


def test_high_priority_tasks_are_listed_with_explanations(client, alice):
    a1 = make_activity(client, alice, priority=3)["id"]
    add_task(client, alice, a1, "soon important", days=3, importance=5)
    add_task(client, alice, a1, "overdue important", days=-2, importance=5)
    add_task(client, alice, a1, "far minor", days=30, importance=1)
    urgent = dashboard(client, alice)["high_priority_tasks"]
    assert [(t["title"], t["level"]) for t in urgent] == [("overdue important", "CRITICAL"), ("soon important", "HIGH")]
    assert urgent[0]["score"] == 92.5 and urgent[0]["activity_title"] == "MCA Final-Year Project"
    assert "deadline passed 2 days ago" in urgent[0]["explanation"]


def test_upcoming_deadlines_combine_activities_and_tasks(client, alice):
    soon = make_activity(client, alice, title="Exam", deadline=day(5))["id"]
    make_activity(client, alice, title="Far away", deadline=day(90))
    make_activity(client, alice, title="Finished", deadline=day(2), status="COMPLETED")
    add_task(client, alice, soon, "revise", days=2)
    add_task(client, alice, soon, "past", days=-3)
    items = dashboard(client, alice)["upcoming_deadlines"]
    assert [(i["kind"], i["title"], i["days_left"]) for i in items] == [("task", "revise", 2), ("activity", "Exam", 5)]


def test_expense_summary(client, alice):
    aid = make_activity(client, alice, title="Goa Trip", activity_type="TRIP")["id"]
    other = make_activity(client, alice, title="Project")["id"]
    for desc, amount, category in (("Hotel", "3000", "Stay"), ("Transport", "1200", "Travel"), ("Food", "800", "Food")):
        client.post(f"/activities/{aid}/expenses", json={"description": desc, "amount": amount, "category": category}, headers=alice)
    client.post(f"/activities/{other}/expenses", json={"description": "Printing", "amount": "450"}, headers=alice)
    e = dashboard(client, alice)["expenses"]
    assert Decimal(e["total"]) == Decimal("5450.00")
    assert [(c["label"], Decimal(c["total"])) for c in e["by_category"]][0] == ("Stay", Decimal("3000.00"))
    assert "Uncategorized" in [c["label"] for c in e["by_category"]]
    assert [(a["label"], Decimal(a["total"])) for a in e["by_activity"]] == [
        ("Goa Trip", Decimal("5000.00")), ("Project", Decimal("450.00"))]


def test_reminders_notifications_and_attention(client, alice):
    aid = make_activity(client, alice)["id"]
    now = datetime.now(timezone.utc)
    client.post(f"/activities/{aid}/reminders", json={"title": "due now", "remind_at": (now - timedelta(minutes=5)).isoformat()}, headers=alice)
    client.post(f"/activities/{aid}/reminders", json={"title": "tomorrow", "remind_at": (now + timedelta(days=1)).isoformat()}, headers=alice)
    d = dashboard(client, alice)  # loading the dashboard triggers the due reminder
    assert d["attention"]["unread_notifications"] == 1
    assert [r["title"] for r in d["upcoming_reminders"]] == ["tomorrow"]


def test_documents_recent_list_and_attention_counters(client, alice):
    aid = make_activity(client, alice)["id"]
    text = ("MCA Final-Year Project Report\nProject synopsis submitted to the supervisor. The project report covers "
            "the database design and the final year project schedule.")
    upload = client.post("/documents", files={"file": ("report.txt", io.BytesIO(text.encode()), "text/plain")}, headers=alice)
    assert upload.status_code == 201, upload.text
    d = dashboard(client, alice)
    assert [x["original_filename"] for x in d["recent_documents"]] == ["report.txt"]
    assert d["attention"]["pending_suggestions"] == 1  # waiting for confirm / reject
    sid = client.get(f"/documents/{upload.json()['id']}/suggestions", headers=alice).json()[0]["id"]
    client.post(f"/documents/{upload.json()['id']}/suggestions/{sid}/confirm", headers=alice)
    assert dashboard(client, alice)["attention"]["pending_suggestions"] == 0
    assert any(e["action"] == "SUGGESTION_CONFIRMED" and e["activity_id"] == aid for e in dashboard(client, alice)["recent_activity"])


def test_failed_documents_need_attention(client, alice, monkeypatch):
    from app.services import text_extraction
    from tests.helpers import make_text_image

    monkeypatch.setattr(text_extraction, "find_tesseract", lambda configured="": None)
    client.post("/documents", files={"file": ("scan.png", io.BytesIO(make_text_image(["Hello"])), "image/png")}, headers=alice)
    assert dashboard(client, alice)["attention"]["documents_needing_review"] == 1


def test_recent_activity_lists_latest_events_first(client, alice):
    aid = make_activity(client, alice)["id"]
    add_task(client, alice, aid, "a task")
    events = dashboard(client, alice)["recent_activity"]
    assert [e["action"] for e in events][:2] == ["TASK_CREATED", "ACTIVITY_CREATED"]
    assert events[0]["activity_title"] == "MCA Final-Year Project"


# ---------------------------------------------------------------- ownership
def test_dashboard_only_counts_my_own_data(client, alice, bob):
    a = make_activity(client, alice)["id"]
    add_task(client, alice, a, "alice task", days=-2, importance=5)
    client.post(f"/activities/{a}/expenses", json={"description": "x", "amount": "100"}, headers=alice)

    b = dashboard(client, bob)
    assert b["overview"]["total_activities"] == 0 and b["overview"]["pending_tasks"] == 0
    assert b["high_priority_tasks"] == [] and b["recent_activity"] == []
    assert Decimal(b["expenses"]["total"]) == Decimal("0.00")

    bob_act = make_activity(client, bob, title="Bob activity")["id"]
    add_task(client, bob, bob_act, "bob task", days=1)
    a_view = dashboard(client, alice)
    assert a_view["overview"]["total_activities"] == 1 and a_view["overview"]["pending_tasks"] == 1
    assert all(i["title"] != "bob task" for i in a_view["upcoming_deadlines"])


def test_dashboard_requires_login(client):
    assert client.get("/dashboard").status_code == 401
