"""Notes and expenses: CRUD, note search, exact totals, and ownership."""
from decimal import Decimal

from tests.conftest import make_activity


# -------------------------------------------------------------------- notes
def test_note_crud_and_search(client, alice):
    aid = make_activity(client, alice)["id"]
    base = f"/activities/{aid}/notes"

    n1 = client.post(base, json={"title": "Supervisor meeting", "content": "Discuss the OCR module"}, headers=alice)
    assert n1.status_code == 201
    client.post(base, json={"title": "Ideas", "content": "weighted scoring"}, headers=alice)

    assert len(client.get(base, headers=alice).json()) == 2
    assert [n["title"] for n in client.get(base, params={"q": "ocr"}, headers=alice).json()] == ["Supervisor meeting"]
    assert [n["title"] for n in client.get(base, params={"q": "IDEAS"}, headers=alice).json()] == ["Ideas"]

    nid = n1.json()["id"]
    upd = client.patch(f"{base}/{nid}", json={"content": "Updated content"}, headers=alice)
    assert upd.status_code == 200 and upd.json()["content"] == "Updated content"
    assert client.delete(f"{base}/{nid}", headers=alice).status_code == 204
    assert client.get(f"{base}/{nid}", headers=alice).status_code == 404


def test_note_validation(client, alice):
    aid = make_activity(client, alice)["id"]
    assert client.post(f"/activities/{aid}/notes", json={"title": "  "}, headers=alice).status_code == 422


def test_other_user_cannot_touch_my_notes(client, alice, bob):
    aid = make_activity(client, alice)["id"]
    nid = client.post(f"/activities/{aid}/notes", json={"title": "secret"}, headers=alice).json()["id"]
    base = f"/activities/{aid}/notes"
    assert client.get(base, headers=bob).status_code == 404
    assert client.get(f"{base}/{nid}", headers=bob).status_code == 404
    assert client.patch(f"{base}/{nid}", json={"title": "x"}, headers=bob).status_code == 404
    assert client.delete(f"{base}/{nid}", headers=bob).status_code == 404


# ----------------------------------------------------------------- expenses
def add_expense(client, headers, aid, description, amount, **extra):
    res = client.post(
        f"/activities/{aid}/expenses",
        json={"description": description, "amount": amount, **extra},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_trip_expense_total(client, alice):
    """The example from the project brief: hotel 3000 + transport 1200 + food 800 = 5000."""
    aid = make_activity(client, alice, title="Goa Trip", activity_type="TRIP")["id"]
    add_expense(client, alice, aid, "Hotel", "3000", category="Stay", expense_date="2026-11-02")
    add_expense(client, alice, aid, "Transport", "1200", category="Travel", expense_date="2026-11-01")
    add_expense(client, alice, aid, "Food", "800", category="Food", expense_date="2026-11-03")
    data = client.get(f"/activities/{aid}/expenses", headers=alice).json()
    assert data["count"] == 3
    assert Decimal(data["total_amount"]) == Decimal("5000.00")
    assert [e["description"] for e in data["items"]] == ["Food", "Hotel", "Transport"]  # newest date first


def test_total_is_exact_for_decimals(client, alice):
    aid = make_activity(client, alice)["id"]
    for _ in range(3):
        add_expense(client, alice, aid, "Coffee", "0.10")
    total = client.get(f"/activities/{aid}/expenses", headers=alice).json()["total_amount"]
    assert Decimal(total) == Decimal("0.30")  # float arithmetic would give 0.30000000000000004


def test_edit_and_delete_expense_update_total(client, alice):
    aid = make_activity(client, alice)["id"]
    e1 = add_expense(client, alice, aid, "Hotel", "3000")
    e2 = add_expense(client, alice, aid, "Food", "800")
    base = f"/activities/{aid}/expenses"
    assert client.patch(f"{base}/{e1['id']}", json={"amount": "2500.50"}, headers=alice).status_code == 200
    assert Decimal(client.get(base, headers=alice).json()["total_amount"]) == Decimal("3300.50")
    assert client.delete(f"{base}/{e2['id']}", headers=alice).status_code == 204
    assert Decimal(client.get(base, headers=alice).json()["total_amount"]) == Decimal("2500.50")


def test_empty_activity_has_zero_total(client, alice):
    aid = make_activity(client, alice)["id"]
    data = client.get(f"/activities/{aid}/expenses", headers=alice).json()
    assert data["count"] == 0 and Decimal(data["total_amount"]) == Decimal("0.00")


def test_expense_validation(client, alice):
    aid = make_activity(client, alice)["id"]
    url = f"/activities/{aid}/expenses"
    assert client.post(url, json={"description": "x", "amount": "-5"}, headers=alice).status_code == 422
    assert client.post(url, json={"description": "x", "amount": "abc"}, headers=alice).status_code == 422
    assert client.post(url, json={"description": "x", "amount": "1.999"}, headers=alice).status_code == 422
    assert client.post(url, json={"description": "", "amount": "5"}, headers=alice).status_code == 422
    assert client.post(url, json={"amount": "5"}, headers=alice).status_code == 422


def test_other_user_cannot_touch_my_expenses(client, alice, bob):
    aid = make_activity(client, alice)["id"]
    eid = add_expense(client, alice, aid, "Hotel", "3000")["id"]
    base = f"/activities/{aid}/expenses"
    assert client.get(base, headers=bob).status_code == 404
    assert client.post(base, json={"description": "x", "amount": "1"}, headers=bob).status_code == 404
    assert client.patch(f"{base}/{eid}", json={"amount": "1"}, headers=bob).status_code == 404
    assert client.delete(f"{base}/{eid}", headers=bob).status_code == 404
    assert Decimal(client.get(base, headers=alice).json()["total_amount"]) == Decimal("3000.00")
