"""Global search: every data type, filters, literal wildcards, and strict ownership."""
import io

from tests.conftest import make_activity


def search(client, headers, q, **params):
    res = client.get("/search", params={"q": q, **params}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def by_type(data, kind):
    return [h for h in data["results"] if h["type"] == kind]


def seed(client, headers):
    """One activity containing a note, task, expense and document that all mention searchable words."""
    act = make_activity(client, headers, description="Cogniflow major project for the final year")
    aid = act["id"]
    client.post(f"/activities/{aid}/notes", json={"title": "Supervisor meeting", "content": "Discuss the OCR module and testing"}, headers=headers)
    client.post(f"/activities/{aid}/tasks", json={"title": "Write chapter on OCR", "description": "include accuracy results"}, headers=headers)
    client.post(f"/activities/{aid}/expenses", json={"description": "Printing thesis", "amount": "450", "category": "Stationery"}, headers=headers)
    text = "EXAM NOTICE\nThe semester exam timetable is attached.\nVenue: Seminar Hall B"
    doc = client.post("/documents", files={"file": ("notice.txt", io.BytesIO(text.encode()), "text/plain")},
                      data={"activity_id": str(aid)}, headers=headers)
    assert doc.status_code == 201, doc.text
    return act, doc.json()


def test_search_finds_every_kind_of_data(client, alice):
    act, doc = seed(client, alice)

    activities = by_type(search(client, alice, "cogniflow"), "activities")
    assert [h["id"] for h in activities] == [act["id"]] and "Cogniflow" in activities[0]["snippet"]

    ocr = search(client, alice, "ocr")  # case-insensitive, in a note and a task
    assert {h["title"] for h in ocr["results"]} == {"Supervisor meeting", "Write chapter on OCR"}
    assert by_type(ocr, "notes")[0]["activity_title"] == "MCA Final-Year Project"

    hall = search(client, alice, "seminar hall")
    assert by_type(hall, "documents")[0]["document_id"] == doc["id"]  # found in the extracted text
    assert by_type(hall, "extracted")[0]["document_id"] == doc["id"]  # and as an extracted LOCATION item

    assert by_type(search(client, alice, "stationery"), "expenses")[0]["title"] == "Printing thesis"
    assert by_type(search(client, alice, "notice.txt"), "documents")  # by file name


def test_snippet_shows_context_around_the_match(client, alice):
    seed(client, alice)
    snippet = by_type(search(client, alice, "accuracy"), "tasks")[0]["snippet"]
    assert "accuracy results" in snippet


def test_types_filter_and_counts(client, alice):
    seed(client, alice)
    data = search(client, alice, "ocr", types="notes")
    assert set(data["counts"]) == {"notes"} and data["total"] == 1
    assert search(client, alice, "ocr")["counts"]["tasks"] == 1


def test_limit_applies_per_type(client, alice):
    aid = make_activity(client, alice)["id"]
    for i in range(4):
        client.post(f"/activities/{aid}/notes", json={"title": f"alpha note {i}"}, headers=alice)
    assert len(by_type(search(client, alice, "alpha", limit=2), "notes")) == 2


def test_no_match_returns_an_empty_result(client, alice):
    seed(client, alice)
    data = search(client, alice, "zebra")
    assert data["total"] == 0 and data["results"] == []


def test_invalid_search_input_is_rejected(client, alice):
    assert client.get("/search", params={"q": "a"}, headers=alice).status_code == 422  # too short
    assert client.get("/search", params={"q": "  "}, headers=alice).status_code == 422
    assert client.get("/search", headers=alice).status_code == 422  # missing
    assert client.get("/search", params={"q": "ocr", "types": "notes,secrets"}, headers=alice).status_code == 422
    assert client.get("/search", params={"q": "ocr", "limit": 100}, headers=alice).status_code == 422


def test_percent_and_underscore_are_matched_literally(client, alice):
    make_activity(client, alice, title="100% done")
    make_activity(client, alice, title="Something else")
    assert [h["title"] for h in by_type(search(client, alice, "0%"), "activities")] == ["100% done"]
    assert by_type(search(client, alice, "%%"), "activities") == []
    assert by_type(search(client, alice, "so_e"), "activities") == []  # "_" is not a wildcard


# ---------------------------------------------------------------- ownership
def test_search_never_returns_another_users_data(client, alice, bob):
    seed(client, alice)
    bob_act = make_activity(client, bob, title="Bob private", description="OCR secrets")
    client.post(f"/activities/{bob_act['id']}/notes", json={"title": "bob OCR note", "content": "secret plan"}, headers=bob)

    alice_view = search(client, alice, "secret")
    assert alice_view["total"] == 0
    bob_ocr = search(client, bob, "ocr")
    assert {h["title"] for h in bob_ocr["results"]} == {"Bob private", "bob OCR note"}
    assert search(client, bob, "seminar hall")["total"] == 0  # Alice's document text is invisible to Bob
    assert search(client, bob, "stationery")["total"] == 0


def test_search_requires_login(client):
    assert client.get("/search", params={"q": "ocr"}).status_code == 401
