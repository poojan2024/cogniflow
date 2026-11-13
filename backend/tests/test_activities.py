"""Activity CRUD, search/filter/pagination, history, and ownership."""
from tests.conftest import make_activity


# ------------------------------------------------------------------- CRUD
def test_create_and_get_activity(client, alice):
    created = make_activity(client, alice, description="Final year", deadline="2026-12-01")
    assert created["title"] == "MCA Final-Year Project"
    assert created["status"] == "ACTIVE"
    res = client.get(f"/activities/{created['id']}", headers=alice)
    assert res.status_code == 200 and res.json()["id"] == created["id"]


def test_create_requires_login(client):
    assert client.post("/activities", json={"title": "x"}).status_code == 401
    assert client.get("/activities").status_code == 401


def test_create_rejects_invalid_input(client, alice):
    assert client.post("/activities", json={"title": "x", "activity_type": "HOLIDAY"}, headers=alice).status_code == 422
    assert client.post("/activities", json={"title": "   "}, headers=alice).status_code == 422
    assert client.post("/activities", json={"title": "x", "priority": 9}, headers=alice).status_code == 422
    bad_dates = {"title": "x", "start_date": "2026-05-10", "deadline": "2026-05-01"}
    assert client.post("/activities", json=bad_dates, headers=alice).status_code == 422


def test_update_activity_partial(client, alice):
    act = make_activity(client, alice)
    res = client.patch(f"/activities/{act['id']}", json={"status": "COMPLETED", "priority": 2}, headers=alice)
    assert res.status_code == 200
    assert res.json()["status"] == "COMPLETED" and res.json()["priority"] == 2
    assert res.json()["title"] == act["title"]  # untouched fields stay


def test_update_checks_dates_against_stored_values(client, alice):
    act = make_activity(client, alice, start_date="2026-05-10", deadline="2026-06-01")
    res = client.patch(f"/activities/{act['id']}", json={"deadline": "2026-05-01"}, headers=alice)
    assert res.status_code == 422


def test_update_cannot_null_required_fields(client, alice):
    act = make_activity(client, alice)
    assert client.patch(f"/activities/{act['id']}", json={"title": None}, headers=alice).status_code == 422


def test_delete_activity_removes_it_and_its_contents(client, alice):
    act = make_activity(client, alice)
    aid = act["id"]
    client.post(f"/activities/{aid}/tasks", json={"title": "t"}, headers=alice)
    client.post(f"/activities/{aid}/notes", json={"title": "n"}, headers=alice)
    client.post(f"/activities/{aid}/expenses", json={"description": "e", "amount": "10"}, headers=alice)
    assert client.delete(f"/activities/{aid}", headers=alice).status_code == 204
    assert client.get(f"/activities/{aid}", headers=alice).status_code == 404
    assert client.get(f"/activities/{aid}/tasks", headers=alice).status_code == 404


# ----------------------------------------------- search / filter / pagination
def test_search_filter_and_sort(client, alice):
    make_activity(client, alice, title="Goa Trip", activity_type="TRIP", description="beach holiday", priority=2)
    make_activity(client, alice, title="DBMS Exam", activity_type="EXAM", status="NOT_STARTED", priority=5)
    make_activity(client, alice, title="Team Meeting", activity_type="MEETING")

    def titles(params):
        res = client.get("/activities", params=params, headers=alice)
        assert res.status_code == 200
        return [a["title"] for a in res.json()["items"]]

    assert titles({"q": "goa"}) == ["Goa Trip"]
    assert titles({"q": "BEACH"}) == ["Goa Trip"]  # description search, case-insensitive
    assert titles({"activity_type": "EXAM"}) == ["DBMS Exam"]
    assert titles({"status": "NOT_STARTED"}) == ["DBMS Exam"]
    assert titles({"sort": "priority"})[0] == "DBMS Exam"
    assert titles({"sort": "title"}) == ["DBMS Exam", "Goa Trip", "Team Meeting"]


def test_search_treats_percent_literally(client, alice):
    make_activity(client, alice, title="100% Done")
    make_activity(client, alice, title="Something else")
    res = client.get("/activities", params={"q": "%"}, headers=alice)
    assert [a["title"] for a in res.json()["items"]] == ["100% Done"]


def test_pagination(client, alice):
    for i in range(3):
        make_activity(client, alice, title=f"Activity {i}")
    page1 = client.get("/activities", params={"page": 1, "page_size": 2}, headers=alice).json()
    page2 = client.get("/activities", params={"page": 2, "page_size": 2}, headers=alice).json()
    assert page1["total"] == 3 and len(page1["items"]) == 2 and len(page2["items"]) == 1


def test_invalid_filter_value_is_422(client, alice):
    assert client.get("/activities", params={"status": "NOPE"}, headers=alice).status_code == 422
    assert client.get("/activities", params={"page_size": 1000}, headers=alice).status_code == 422


# ------------------------------------------------------------------ history
def test_history_records_events(client, alice):
    act = make_activity(client, alice)
    client.patch(f"/activities/{act['id']}", json={"priority": 5}, headers=alice)
    client.post(f"/activities/{act['id']}/tasks", json={"title": "Write report"}, headers=alice)
    res = client.get(f"/activities/{act['id']}/history", headers=alice)
    actions = [h["action"] for h in res.json()["items"]]
    assert res.json()["total"] == 3
    assert actions == ["TASK_CREATED", "ACTIVITY_UPDATED", "ACTIVITY_CREATED"]  # newest first


# ---------------------------------------------------------------- ownership
def test_other_user_cannot_see_change_or_delete_activity(client, alice, bob):
    act = make_activity(client, alice)
    url = f"/activities/{act['id']}"
    assert client.get(url, headers=bob).status_code == 404
    assert client.patch(url, json={"title": "hacked"}, headers=bob).status_code == 404
    assert client.delete(url, headers=bob).status_code == 404
    assert client.get(f"{url}/history", headers=bob).status_code == 404
    # still intact for the owner
    assert client.get(url, headers=alice).json()["title"] == act["title"]


def test_list_only_returns_own_activities(client, alice, bob):
    make_activity(client, alice, title="Alice private")
    make_activity(client, bob, title="Bob private")
    assert [a["title"] for a in client.get("/activities", headers=alice).json()["items"]] == ["Alice private"]
    assert [a["title"] for a in client.get("/activities", headers=bob).json()["items"]] == ["Bob private"]
    assert client.get("/activities", params={"q": "Alice"}, headers=bob).json()["total"] == 0
