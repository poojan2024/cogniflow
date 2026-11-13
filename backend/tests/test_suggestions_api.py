"""Activity suggestions through the API. Key rule: a suggestion NEVER moves a document by itself."""
import io

from tests.conftest import make_activity

PROJECT_DOC = (
    "MCA Final-Year Project Report\nProject synopsis submitted to the supervisor. The project report covers "
    "the database design, system architecture and the final year project schedule.\nSubmission deadline: 15/12/2026"
)
RECIPE_DOC = (
    "Chocolate cake recipe. Mix flour, sugar and cocoa. Bake for forty minutes. "
    "Let the cake cool before adding frosting and serve with cream."
)


def upload(client, headers, text=PROJECT_DOC, name="report.txt", activity_id=None):
    data = {"activity_id": str(activity_id)} if activity_id is not None else {}
    res = client.post("/documents", files={"file": (name, io.BytesIO(text.encode()), "text/plain")},
                      data=data, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def suggestions(client, headers, doc_id):
    res = client.get(f"/documents/{doc_id}/suggestions", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def history_actions(client, headers, activity_id):
    return [h["action"] for h in client.get(f"/activities/{activity_id}/history", headers=headers).json()["items"]]


# --------------------------------------------------- suggest, never move
def test_matching_document_gets_a_pending_suggestion_but_is_not_moved(client, alice):
    project = make_activity(client, alice)
    make_activity(client, alice, title="Goa Trip", activity_type="TRIP")
    doc = upload(client, alice)
    found = suggestions(client, alice, doc["id"])
    assert [s["activity_id"] for s in found] == [project["id"]]
    assert found[0]["status"] == "PENDING"
    # the document was NOT silently moved
    assert client.get(f"/documents/{doc['id']}", headers=alice).json()["activity_id"] is None
    assert "SUGGESTION_GENERATED" in history_actions(client, alice, project["id"])


def test_suggestion_has_score_confidence_and_explanation(client, alice):
    make_activity(client, alice)
    s = suggestions(client, alice, upload(client, alice)["id"])[0]
    assert 30 <= s["score"] <= 100 and s["confidence"] in ("strong", "moderate", "weak")
    assert s["activity_title"] == "MCA Final-Year Project" and s["activity_type"] == "PROJECT"
    assert "Match score" in s["explanation"] and "mca" in s["explanation"]


def test_unrelated_document_gets_no_suggestion(client, alice):
    make_activity(client, alice)
    assert suggestions(client, alice, upload(client, alice, text=RECIPE_DOC)["id"]) == []


def test_document_uploaded_straight_into_an_activity_gets_no_suggestions(client, alice):
    activity = make_activity(client, alice)
    doc = upload(client, alice, activity_id=activity["id"])
    assert suggestions(client, alice, doc["id"]) == []


def test_finished_activities_are_not_suggested(client, alice):
    make_activity(client, alice, status="COMPLETED")
    assert suggestions(client, alice, upload(client, alice)["id"]) == []


# ------------------------------------------------------------------ confirm
def test_confirm_assigns_the_document_and_logs_history(client, alice):
    project = make_activity(client, alice)
    doc = upload(client, alice)
    sid = suggestions(client, alice, doc["id"])[0]["id"]
    res = client.post(f"/documents/{doc['id']}/suggestions/{sid}/confirm", headers=alice)
    assert res.status_code == 200 and res.json()["activity_id"] == project["id"]
    assert suggestions(client, alice, doc["id"])[0]["status"] == "CONFIRMED"
    actions = history_actions(client, alice, project["id"])
    assert "SUGGESTION_CONFIRMED" in actions and "DOCUMENT_ASSIGNED" in actions


def test_confirming_removes_the_other_open_suggestions(client, alice):
    first = make_activity(client, alice)
    make_activity(client, alice, title="MCA Project Review")
    doc = upload(client, alice)
    found = suggestions(client, alice, doc["id"])
    assert len(found) == 2 and found[0]["activity_id"] == first["id"]  # best score first
    client.post(f"/documents/{doc['id']}/suggestions/{found[0]['id']}/confirm", headers=alice)
    after = suggestions(client, alice, doc["id"])
    assert [s["status"] for s in after] == ["CONFIRMED"]


def test_a_suggestion_cannot_be_decided_twice(client, alice):
    make_activity(client, alice)
    doc = upload(client, alice)
    sid = suggestions(client, alice, doc["id"])[0]["id"]
    base = f"/documents/{doc['id']}/suggestions/{sid}"
    assert client.post(f"{base}/confirm", headers=alice).status_code == 200
    assert client.post(f"{base}/confirm", headers=alice).status_code == 409
    assert client.post(f"{base}/reject", headers=alice).status_code == 409


# ------------------------------------------------------------------- reject
def test_reject_keeps_the_document_unassigned_and_manual_choice_still_works(client, alice):
    project = make_activity(client, alice)
    other = make_activity(client, alice, title="Something Else", activity_type="PERSONAL")
    doc = upload(client, alice)
    sid = suggestions(client, alice, doc["id"])[0]["id"]
    res = client.post(f"/documents/{doc['id']}/suggestions/{sid}/reject", headers=alice)
    assert res.status_code == 200 and res.json()[0]["status"] == "REJECTED"
    assert client.get(f"/documents/{doc['id']}", headers=alice).json()["activity_id"] is None  # not moved
    assert "SUGGESTION_REJECTED" in history_actions(client, alice, project["id"])
    # "Select activity manually"
    manual = client.patch(f"/documents/{doc['id']}", json={"activity_id": other["id"]}, headers=alice)
    assert manual.json()["activity_id"] == other["id"]


def test_rejected_activity_is_not_suggested_again(client, alice):
    make_activity(client, alice)
    doc = upload(client, alice)
    sid = suggestions(client, alice, doc["id"])[0]["id"]
    client.post(f"/documents/{doc['id']}/suggestions/{sid}/reject", headers=alice)
    refreshed = client.post(f"/documents/{doc['id']}/suggestions", headers=alice).json()
    assert [s["status"] for s in refreshed] == ["REJECTED"]  # no new PENDING suggestion for the same activity


# ------------------------------------------------------ refresh / regenerate
def test_refresh_finds_a_new_activity_created_after_the_upload(client, alice):
    doc = upload(client, alice)
    assert suggestions(client, alice, doc["id"]) == []
    project = make_activity(client, alice)
    refreshed = client.post(f"/documents/{doc['id']}/suggestions", headers=alice)
    assert refreshed.status_code == 200 and [s["activity_id"] for s in refreshed.json()] == [project["id"]]


def test_refresh_is_refused_for_a_document_already_in_an_activity(client, alice):
    activity = make_activity(client, alice)
    doc = upload(client, alice, activity_id=activity["id"])
    assert client.post(f"/documents/{doc['id']}/suggestions", headers=alice).status_code == 409


def test_correcting_the_text_recalculates_suggestions(client, alice):
    make_activity(client, alice)
    doc = upload(client, alice, text=RECIPE_DOC)
    assert suggestions(client, alice, doc["id"]) == []
    client.patch(f"/documents/{doc['id']}/text", json={"text": PROJECT_DOC}, headers=alice)
    assert len(suggestions(client, alice, doc["id"])) == 1


def test_deleting_the_activity_removes_its_suggestion(client, alice):
    project = make_activity(client, alice)
    doc = upload(client, alice)
    assert len(suggestions(client, alice, doc["id"])) == 1
    client.delete(f"/activities/{project['id']}", headers=alice)
    assert suggestions(client, alice, doc["id"]) == []


# ---------------------------------------------------------------- ownership
def test_other_users_activities_are_never_suggested(client, alice, bob):
    make_activity(client, bob)  # Bob owns a perfectly matching activity
    doc = upload(client, alice)
    assert suggestions(client, alice, doc["id"]) == []


def test_other_user_cannot_see_or_decide_my_suggestions(client, alice, bob):
    make_activity(client, alice)
    doc = upload(client, alice)
    sid = suggestions(client, alice, doc["id"])[0]["id"]
    base = f"/documents/{doc['id']}/suggestions"
    assert client.get(base, headers=bob).status_code == 404
    assert client.post(base, headers=bob).status_code == 404
    assert client.post(f"{base}/{sid}/confirm", headers=bob).status_code == 404
    assert client.post(f"{base}/{sid}/reject", headers=bob).status_code == 404
    assert suggestions(client, alice, doc["id"])[0]["status"] == "PENDING"  # untouched


def test_suggestions_require_login(client, alice):
    make_activity(client, alice)
    doc = upload(client, alice)
    assert client.get(f"/documents/{doc['id']}/suggestions").status_code == 401
