"""The contextual assistant through the API. A fake AI client replaces Gemini, so these tests never use the network
and never need a real key."""
import io
from datetime import date, timedelta

from app.core.deps import get_ai_client
from app.main import app
from app.services.assistant_core import NOT_AVAILABLE_ANSWER, SYSTEM_PROMPT
from app.services.gemini_client import USER_MESSAGES, AIError
from tests.conftest import make_activity

NOTICE_TEXT = "EXAM NOTICE\nLast date to submit: 30/11/2026\nVenue: Seminar Hall B\nThe semester exam timetable is attached."


class FakeAI:
    """Pretends to be Gemini and records what it was sent."""

    def __init__(self, answer="OK"):
        self.answer = answer
        self.calls = []

    def generate(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        return self.answer


class BrokenAI:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    def generate(self, system_prompt, user_prompt):
        self.calls += 1
        raise self.error


def use_ai(fake):
    app.dependency_overrides[get_ai_client] = lambda: fake  # the client fixture clears all overrides afterwards
    return fake


def day(offset):
    return (date.today() + timedelta(days=offset)).isoformat()


def seed(client, headers):
    """An activity with a deadline, a task, a note, an expense set, a reminder and a processed document."""
    activity = make_activity(client, headers, description="Cogniflow major project for MCA", deadline=day(30))
    aid = activity["id"]
    task = client.post(f"/activities/{aid}/tasks", json={"title": "Write chapter one", "due_date": day(10), "importance": 4}, headers=headers).json()
    note = client.post(f"/activities/{aid}/notes", json={"title": "Supervisor meeting", "content": "Discuss the OCR module and the accuracy table"}, headers=headers).json()
    for desc, amount in (("Hotel", "3000"), ("Transport", "1200"), ("Food", "800")):
        client.post(f"/activities/{aid}/expenses", json={"description": desc, "amount": amount, "category": "Trip"}, headers=headers)
    client.post(f"/activities/{aid}/reminders", json={"title": "Submit synopsis", "remind_at": "2030-01-01T09:00:00+05:30"}, headers=headers)
    doc = client.post("/documents", files={"file": ("notice.txt", io.BytesIO(NOTICE_TEXT.encode()), "text/plain")},
                      data={"activity_id": str(aid)}, headers=headers).json()
    return {"activity": activity, "id": aid, "task": task, "note": note, "doc": doc}


def ask(client, headers, aid, question="What is the deadline?", mode="auto"):
    return client.post(f"/activities/{aid}/assistant/ask", json={"question": question, "mode": mode}, headers=headers)


def ask_ok(client, headers, aid, **kwargs):
    res = ask(client, headers, aid, **kwargs)
    assert res.status_code == 200, res.text
    return res.json()


# ------------------------------------------------------------- AI answers
def test_ai_answer_is_returned_with_verified_references_and_logged(client, alice):
    s = seed(client, alice)
    task_label, doc_label = f"Task {s['task']['id']}", f"Doc {s['doc']['id']}"
    use_ai(FakeAI(f"Chapter one is due soon [{task_label}] and the notice is in [{doc_label}]."))

    data = ask_ok(client, alice, s["id"], question="What do I need to do soon?")
    assert data["source"] == "gemini" and data["ai_status"] == "ok" and data["has_information"] is True
    assert [r["label"] for r in data["references"]] == [task_label, doc_label]
    assert data["unverified_references"] == [] and data["notice"] is None

    history = client.get(f"/activities/{s['id']}/assistant/history", headers=alice).json()
    assert history["total"] == 1
    entry = history["items"][0]
    assert entry["question"] == "What do I need to do soon?" and entry["answer"] == data["answer"]
    assert entry["status"] == "SUCCESS" and entry["source"] == "gemini" and entry["note"] is None
    events = [h["action"] for h in client.get(f"/activities/{s['id']}/history", headers=alice).json()["items"]]
    assert "ASSISTANT_QUESTION" in events


def test_only_this_activitys_data_is_sent_to_gemini(client, alice, bob):
    s = seed(client, alice)
    other = make_activity(client, alice, title="Garden Plans", description="plant roses")
    client.post(f"/activities/{other['id']}/notes", json={"title": "Other activity note", "content": "ALICE-OTHER-SECRET"}, headers=alice)
    bob_act = make_activity(client, bob, title="Bob private")
    client.post(f"/activities/{bob_act['id']}/notes", json={"title": "Bob note", "content": "BOB-SECRET-TEXT"}, headers=bob)

    fake = use_ai(FakeAI("answer"))
    ask_ok(client, alice, s["id"], question="Give me an overview")
    assert len(fake.calls) == 1
    system_prompt, user_prompt = fake.calls[0]

    assert system_prompt == SYSTEM_PROMPT
    # everything from the selected activity: description, deadline, task, note, expenses, reminder, document text and facts
    for expected in ("Cogniflow major project for MCA", day(30), "Write chapter one", "accuracy table", "Hotel",
                     "Total of 3 expenses: 5000.00", "Submit synopsis", "semester exam timetable", "Seminar Hall B",
                     "QUESTION: Give me an overview"):
        assert expected in user_prompt, expected
    # nothing from other activities, other users, or the account itself
    for forbidden in ("ALICE-OTHER-SECRET", "Garden Plans", "BOB-SECRET-TEXT", "Bob private",
                      "alice@example.com", "bob@example.com", "Alice", "$2b$", "password"):
        assert forbidden not in user_prompt, forbidden


def test_missing_information_is_stated_not_invented(client, alice):
    s = seed(client, alice)
    use_ai(FakeAI(NOT_AVAILABLE_ANSWER))
    data = ask_ok(client, alice, s["id"], question="What is the capital of France?")
    assert data["answer"] == NOT_AVAILABLE_ANSWER and data["has_information"] is False
    assert data["source"] == "gemini" and data["references"] == []


def test_references_that_do_not_exist_are_flagged(client, alice):
    s = seed(client, alice)
    use_ai(FakeAI("It is in [Doc 9999] and [Task 4242]."))
    data = ask_ok(client, alice, s["id"])
    assert data["unverified_references"] == ["Doc 9999", "Task 4242"] and data["references"] == []
    assert "double-check" in data["notice"]


# --------------------------------------------------------------- fallback
def test_without_a_gemini_key_the_assistant_falls_back_to_keyword_answers(client, alice):
    s = seed(client, alice)  # the default test override has no AI configured
    data = ask_ok(client, alice, s["id"], question="Which tasks are pending?")
    assert data["source"] == "keyword" and data["ai_status"] == "unavailable"
    assert "not configured" in data["notice"] and "keyword-based answer" in data["notice"]
    assert "Write chapter one" in data["answer"] and data["has_information"] is True
    assert [r["label"] for r in data["references"]] == [f"Task {s['task']['id']}"]
    entry = client.get(f"/activities/{s['id']}/assistant/history", headers=alice).json()["items"][0]
    assert entry["status"] == "UNAVAILABLE" and entry["source"] == "keyword" and "not_configured" in entry["note"]


def test_every_kind_of_ai_failure_gives_a_clear_notice_and_a_keyword_answer(client, alice):
    s = seed(client, alice)
    for kind in ("auth", "config", "rate_limit", "network", "server", "blocked", "bad_response"):
        broken = use_ai(BrokenAI(AIError(kind)))
        data = ask_ok(client, alice, s["id"], question="What documents are uploaded?")
        assert broken.calls == 1
        assert data["source"] == "keyword" and USER_MESSAGES[kind] in data["notice"], kind
        assert data["ai_status"] == ("failed" if kind in ("blocked", "bad_response") else "unavailable")
        assert "notice.txt" in data["answer"]  # the keyword answer still helps
    stored = {h["status"] for h in client.get(f"/activities/{s['id']}/assistant/history", headers=alice).json()["items"]}
    assert stored == {"UNAVAILABLE", "FAILED"}


def test_an_unexpected_error_in_the_ai_layer_does_not_break_the_request(client, alice):
    s = seed(client, alice)
    use_ai(BrokenAI(RuntimeError("boom: internal detail SECRET-KEY-123")))
    res = ask(client, alice, s["id"], question="What documents are uploaded?")
    assert res.status_code == 200
    assert "boom" not in res.text and "SECRET-KEY-123" not in res.text and "Traceback" not in res.text
    assert res.json()["source"] == "keyword"


def test_local_mode_never_contacts_the_ai(client, alice):
    s = seed(client, alice)
    fake = use_ai(FakeAI("should never be used"))
    data = ask_ok(client, alice, s["id"], question="What is the deadline?", mode="local")
    assert fake.calls == [] and data["source"] == "keyword" and data["ai_status"] == "not_used"
    assert "Nothing was sent to Gemini" in data["notice"] and "Activity" in [r["label"] for r in data["references"]]
    entry = client.get(f"/activities/{s['id']}/assistant/history", headers=alice).json()["items"][0]
    assert entry["status"] == "SUCCESS" and entry["source"] == "keyword"


def test_keyword_mode_admits_when_nothing_matches(client, alice):
    s = seed(client, alice)
    data = ask_ok(client, alice, s["id"], question="What is the capital of France?", mode="local")
    assert data["has_information"] is False and data["references"] == []
    assert "couldn't find anything" in data["answer"]


# ------------------------------------------------------------- validation
def test_question_validation(client, alice):
    aid = make_activity(client, alice)["id"]
    for body in ({"question": ""}, {"question": "   "}, {"question": "x" * 1001}, {"question": "ok", "mode": "turbo"}, {}):
        assert client.post(f"/activities/{aid}/assistant/ask", json=body, headers=alice).status_code == 422
    assert client.post(f"/activities/{aid}/assistant/ask", json={"question": "x" * 1000}, headers=alice).status_code == 200


def test_activity_with_no_data_still_answers_honestly(client, alice):
    aid = make_activity(client, alice, title="Empty activity")["id"]
    data = ask_ok(client, alice, aid, question="What documents have I uploaded?", mode="local")
    assert data["has_information"] is False


# ----------------------------------------------------------- history log
def test_history_is_newest_first_paginated_and_deletable(client, alice):
    aid = make_activity(client, alice)["id"]
    for q in ("first question", "second question", "third question"):
        ask_ok(client, alice, aid, question=q, mode="local")
    base = f"/activities/{aid}/assistant/history"
    page = client.get(base, headers=alice).json()
    assert [i["question"] for i in page["items"]] == ["third question", "second question", "first question"]
    assert len(client.get(base, params={"page": 2, "page_size": 2}, headers=alice).json()["items"]) == 1
    assert client.delete(f"{base}/{page['items'][0]['id']}", headers=alice).status_code == 204
    assert client.get(base, headers=alice).json()["total"] == 2
    assert client.delete(f"{base}/999999", headers=alice).status_code == 404


# -------------------------------------------------------- context preview
def test_context_preview_shows_exactly_what_would_be_sent(client, alice):
    s = seed(client, alice)
    other = make_activity(client, alice, title="Garden Plans")
    client.post(f"/activities/{other['id']}/notes", json={"title": "n", "content": "ALICE-OTHER-SECRET"}, headers=alice)
    data = client.get(f"/activities/{s['id']}/assistant/context", headers=alice).json()
    assert "accuracy table" in data["text"] and "semester exam timetable" in data["text"]
    assert "ALICE-OTHER-SECRET" not in data["text"] and data["truncated"] is False
    assert data["char_count"] == len(data["text"])
    labels = [r["label"] for r in data["sources"]]
    assert "Activity" in labels and f"Task {s['task']['id']}" in labels and f"Doc {s['doc']['id']}" in labels


def test_large_activities_are_cut_to_the_size_limit_and_the_user_is_told(client, alice):
    aid = make_activity(client, alice)["id"]
    for i in range(30):
        client.post(f"/activities/{aid}/notes", json={"title": f"note {i}", "content": "word " * 300}, headers=alice)
    data = client.get(f"/activities/{aid}/assistant/context", headers=alice).json()
    assert data["truncated"] is True and "not shown because of size limits" in data["text"]
    assert data["char_count"] <= 24000 + 250
    use_ai(FakeAI("answer"))
    assert ask_ok(client, alice, aid)["context_truncated"] is True


# ---------------------------------------------------------------- limits
def test_hourly_question_limit(client, alice, bob, monkeypatch):
    monkeypatch.setattr("app.routers.assistant._hourly_limit", lambda: 2)
    aid = make_activity(client, alice)["id"]
    assert ask(client, alice, aid, mode="local").status_code == 200
    assert ask(client, alice, aid, mode="local").status_code == 200
    blocked = ask(client, alice, aid, mode="local")
    assert blocked.status_code == 429 and "many questions" in blocked.json()["detail"]
    bob_aid = make_activity(client, bob)["id"]
    assert ask(client, bob, bob_aid, mode="local").status_code == 200  # the limit is per user


def test_status_endpoint_never_reveals_the_key(client, alice):
    off = client.get("/assistant/status", headers=alice).json()
    assert off["ai_configured"] is False and off["provider"] == "gemini"
    use_ai(FakeAI())
    on = client.get("/assistant/status", headers=alice).json()
    assert on["ai_configured"] is True
    assert set(on) == {"provider", "ai_configured", "model", "max_questions_per_hour", "note"}


# --------------------------------------------------------------- ownership
def test_other_user_cannot_use_my_assistant(client, alice, bob):
    s = seed(client, alice)
    ask_ok(client, alice, s["id"], question="my private question", mode="local")
    fake = use_ai(FakeAI("should not be called"))
    base = f"/activities/{s['id']}/assistant"
    assert ask(client, bob, s["id"]).status_code == 404
    assert client.get(f"{base}/history", headers=bob).status_code == 404
    assert client.get(f"{base}/context", headers=bob).status_code == 404
    entry_id = client.get(f"{base}/history", headers=alice).json()["items"][0]["id"]
    assert client.delete(f"{base}/history/{entry_id}", headers=bob).status_code == 404
    assert fake.calls == []  # no data of Alice's was ever sent to the AI on Bob's behalf
    assert client.get(f"{base}/history", headers=alice).json()["total"] == 1


def test_assistant_requires_login(client, alice):
    aid = make_activity(client, alice)["id"]
    assert client.post(f"/activities/{aid}/assistant/ask", json={"question": "hi"}).status_code == 401
    assert client.get(f"/activities/{aid}/assistant/history").status_code == 401
    assert client.get(f"/activities/{aid}/assistant/context").status_code == 401
    assert client.get("/assistant/status").status_code == 401
