"""Document endpoints. Background processing finishes before the test client returns, so a GET right after
an upload already shows the final processing status.

Tests that need real OCR are skipped automatically when Tesseract is not installed.
"""
import io

import pytest

from app.core.config import get_settings
from app.services.text_extraction import tesseract_available
from tests.conftest import make_activity
from tests.helpers import make_text_image, make_text_pdf

needs_tesseract = pytest.mark.skipif(not tesseract_available(), reason="Tesseract is not installed")

NOTICE = (
    "EXAM NOTICE\n"
    "Last date to submit: 30/11/2026\n"
    "Fee: Rs. 500\n"
    "Venue: Seminar Hall B\n"
    "The semester exam timetable is attached."
)


def upload(client, headers, name="notice.txt", content=NOTICE.encode(), activity_id=None, mime="text/plain"):
    data = {"activity_id": str(activity_id)} if activity_id is not None else {}
    return client.post("/documents", files={"file": (name, io.BytesIO(content), mime)}, data=data, headers=headers)


def upload_ok(client, headers, **kwargs):
    res = upload(client, headers, **kwargs)
    assert res.status_code == 201, res.text
    return res.json()


def types(detail, info_type):
    return [i["value"] for i in detail["items"] if i["info_type"] == info_type]


# ------------------------------------------------------------- upload + pipeline
def test_upload_text_file_is_processed_and_information_extracted(client, alice):
    doc = upload_ok(client, alice)
    assert doc["processing_status"] == "UPLOADED" and doc["activity_id"] is None  # returned before processing
    detail = client.get(f"/documents/{doc['id']}", headers=alice).json()
    assert detail["processing_status"] == "PROCESSED" and detail["extraction_method"] == "TEXT"
    assert "EXAM NOTICE" in detail["extracted_text"]
    assert types(detail, "DEADLINE") == ["2026-11-30"]
    assert types(detail, "AMOUNT") == ["INR 500.00"]
    assert types(detail, "LOCATION") == ["Seminar Hall B"]
    assert types(detail, "DOCUMENT_TYPE") == ["Exam notice"]
    assert all(i["source"] == "RULE" and i["context"] for i in detail["items"])


def test_text_pdf_is_read_without_ocr(client, alice):
    pdf = make_text_pdf(["Project Report", "Submission deadline: 15/12/2026", "Supervisor: Dr. Anita Sharma"])
    doc = upload_ok(client, alice, name="report.pdf", content=pdf, mime="application/pdf")
    detail = client.get(f"/documents/{doc['id']}", headers=alice).json()
    assert detail["extraction_method"] == "TEXT" and detail["ocr_confidence"] is None
    assert types(detail, "DEADLINE") == ["2026-12-15"]


@needs_tesseract
def test_image_is_read_with_ocr(client, alice):
    png = make_text_image(["APPOINTMENT NOTICE", "Date: 12 March 2026", "Doctor: Dr. Rao"])
    doc = upload_ok(client, alice, name="scan.png", content=png, mime="image/png")
    detail = client.get(f"/documents/{doc['id']}", headers=alice).json()
    assert detail["extraction_method"] == "OCR" and detail["ocr_confidence"] > 50
    assert detail["processing_status"] in ("PROCESSED", "NEEDS_REVIEW")
    assert "2026-03-12" in types(detail, "DATE")


def test_ocr_failure_is_reported_not_hidden(client, alice, monkeypatch):
    """With no OCR engine the image upload still succeeds, the document is FAILED with an explanation,
    no text is invented, and Reprocess is offered."""
    from app.services import text_extraction

    monkeypatch.setattr(text_extraction, "find_tesseract", lambda configured="": None)
    doc = upload_ok(client, alice, name="scan.png", content=make_text_image(["Hello world"]), mime="image/png")
    detail = client.get(f"/documents/{doc['id']}", headers=alice).json()
    assert detail["processing_status"] == "FAILED" and detail["extracted_text"] is None
    assert detail["items"] == [] and "Tesseract" in detail["error_message"]


def test_upload_directly_into_activity_logs_history(client, alice):
    aid = make_activity(client, alice)["id"]
    doc = upload_ok(client, alice, activity_id=aid)
    assert doc["activity_id"] == aid
    actions = [h["action"] for h in client.get(f"/activities/{aid}/history", headers=alice).json()["items"]]
    assert "DOCUMENT_UPLOADED" in actions and "DOCUMENT_PROCESSED" in actions


# ----------------------------------------------------------------- validation
def test_unsupported_and_mismatched_files_are_rejected(client, alice):
    assert upload(client, alice, name="run.exe", content=b"MZ...").status_code == 415
    assert upload(client, alice, name="fake.pdf", content=b"not a pdf").status_code == 400
    assert upload(client, alice, name="fake.png", content=make_text_pdf(["x"])).status_code == 400
    assert upload(client, alice, name="empty.txt", content=b"").status_code == 400


def test_oversized_file_is_rejected_with_413(client, alice):
    too_big = b"a" * (get_settings().max_upload_mb * 1024 * 1024 + 1)
    assert upload(client, alice, name="big.txt", content=too_big).status_code == 413


def test_malicious_filename_cannot_escape_storage(client, alice):
    doc = upload_ok(client, alice, name="../../evil.txt")
    assert doc["original_filename"] == "evil.txt"


def test_duplicate_upload_is_rejected_and_not_processed_again(client, alice):
    first = upload_ok(client, alice)
    again = upload(client, alice)
    assert again.status_code == 409 and f"#{first['id']}" in again.json()["detail"]
    assert client.get("/documents", headers=alice).json()["total"] == 1


def test_same_file_by_different_users_is_allowed(client, alice, bob):
    assert upload(client, alice).status_code == 201
    assert upload(client, bob).status_code == 201


def test_upload_requires_login(client):
    res = client.post("/documents", files={"file": ("a.txt", io.BytesIO(b"hello"), "text/plain")})
    assert res.status_code == 401


def test_upload_into_someone_elses_activity_is_404(client, alice, bob):
    alice_activity = make_activity(client, alice)["id"]
    assert upload(client, bob, activity_id=alice_activity).status_code == 404


# ------------------------------------------------------------ list / filters
def test_list_filters_and_pagination(client, alice):
    aid = make_activity(client, alice)["id"]
    upload_ok(client, alice, name="a.txt", content=b"first document text here", activity_id=aid)
    upload_ok(client, alice, name="b.txt", content=b"second document text here")
    upload_ok(client, alice, name="c.txt", content=b"third document text here")
    assert client.get("/documents", headers=alice).json()["total"] == 3
    assert client.get("/documents", params={"activity_id": aid}, headers=alice).json()["total"] == 1
    assert client.get("/documents", params={"unassigned": "true"}, headers=alice).json()["total"] == 2
    assert client.get("/documents", params={"status": "PROCESSED"}, headers=alice).json()["total"] == 3
    page = client.get("/documents", params={"page": 2, "page_size": 2}, headers=alice).json()
    assert page["total"] == 3 and len(page["items"]) == 1


# --------------------------------------------------------------- download
def test_download_returns_the_original_bytes(client, alice):
    pdf = make_text_pdf(["Hello download test, long enough to count as text."])
    doc = upload_ok(client, alice, name="my report.pdf", content=pdf, mime="application/pdf")
    res = client.get(f"/documents/{doc['id']}/download", headers=alice)
    assert res.status_code == 200 and res.content == pdf
    assert res.headers["content-type"] == "application/pdf"
    assert res.headers["x-content-type-options"] == "nosniff"


# ------------------------------------------------- manual correction + items
def test_user_can_correct_text_and_items_are_re_extracted(client, alice):
    doc = upload_ok(client, alice)
    res = client.patch(
        f"/documents/{doc['id']}/text",
        json={"text": "Corrected notice. Submit by 01/02/2027. Fee ₹750"},
        headers=alice,
    )
    assert res.status_code == 200
    detail = res.json()
    assert types(detail, "DEADLINE") == ["2027-02-01"] and types(detail, "AMOUNT") == ["INR 750.00"]
    assert detail["processing_status"] == "PROCESSED"


def test_user_can_delete_a_wrong_extracted_item(client, alice):
    doc = upload_ok(client, alice)
    detail = client.get(f"/documents/{doc['id']}", headers=alice).json()
    amount = next(i for i in detail["items"] if i["info_type"] == "AMOUNT")
    assert client.delete(f"/documents/{doc['id']}/items/{amount['id']}", headers=alice).status_code == 204
    assert types(client.get(f"/documents/{doc['id']}", headers=alice).json(), "AMOUNT") == []


def test_reprocess_only_for_failed_or_review_documents(client, alice):
    doc = upload_ok(client, alice)  # PROCESSED
    assert client.post(f"/documents/{doc['id']}/reprocess", headers=alice).status_code == 409


def test_reprocess_after_failure_can_succeed(client, alice, monkeypatch):
    from app.services import text_extraction

    png = make_text_image(["INVOICE", "Total amount due Rs. 900", "Payment received"])
    monkeypatch.setattr(text_extraction, "find_tesseract", lambda configured="": None)
    doc = upload_ok(client, alice, name="inv.png", content=png, mime="image/png")
    assert client.get(f"/documents/{doc['id']}", headers=alice).json()["processing_status"] == "FAILED"
    monkeypatch.undo()
    if not tesseract_available():
        pytest.skip("Tesseract is not installed")
    assert client.post(f"/documents/{doc['id']}/reprocess", headers=alice).status_code == 202
    assert client.get(f"/documents/{doc['id']}", headers=alice).json()["processing_status"] in ("PROCESSED", "NEEDS_REVIEW")


# ------------------------------------------------------------ assign / delete
def test_assign_and_unassign_document(client, alice):
    aid = make_activity(client, alice)["id"]
    doc = upload_ok(client, alice)
    assert client.patch(f"/documents/{doc['id']}", json={"activity_id": aid}, headers=alice).json()["activity_id"] == aid
    assert client.patch(f"/documents/{doc['id']}", json={"activity_id": None}, headers=alice).json()["activity_id"] is None
    actions = [h["action"] for h in client.get(f"/activities/{aid}/history", headers=alice).json()["items"]]
    assert "DOCUMENT_ASSIGNED" in actions and "DOCUMENT_UNASSIGNED" in actions


def test_cannot_assign_document_to_someone_elses_activity(client, alice, bob):
    bob_activity = make_activity(client, bob)["id"]
    doc = upload_ok(client, alice)
    assert client.patch(f"/documents/{doc['id']}", json={"activity_id": bob_activity}, headers=alice).status_code == 404


def test_delete_document_removes_record_and_file(client, alice, db_session):
    from app.models import Document
    from app.services import storage

    doc = upload_ok(client, alice)
    row = db_session.get(Document, doc["id"])
    user_id, stored = row.user_id, row.stored_filename
    assert storage.exists(user_id, stored)
    assert client.delete(f"/documents/{doc['id']}", headers=alice).status_code == 204
    assert client.get(f"/documents/{doc['id']}", headers=alice).status_code == 404
    assert not storage.exists(user_id, stored)


def test_deleting_an_activity_keeps_unrelated_documents(client, alice):
    keep = upload_ok(client, alice, name="keep.txt", content=b"an unassigned document that stays")
    aid = make_activity(client, alice)["id"]
    upload_ok(client, alice, name="gone.txt", content=b"a document inside the activity", activity_id=aid)
    client.delete(f"/activities/{aid}", headers=alice)
    assert client.get(f"/documents/{keep['id']}", headers=alice).status_code == 200
    assert client.get("/documents", headers=alice).json()["total"] == 1


# ---------------------------------------------------------------- ownership
def test_other_user_cannot_access_my_documents(client, alice, bob):
    doc = upload_ok(client, alice)
    did = doc["id"]
    assert client.get(f"/documents/{did}", headers=bob).status_code == 404
    assert client.get(f"/documents/{did}/download", headers=bob).status_code == 404
    assert client.patch(f"/documents/{did}/text", json={"text": "hacked"}, headers=bob).status_code == 404
    assert client.patch(f"/documents/{did}", json={"activity_id": None}, headers=bob).status_code == 404
    assert client.post(f"/documents/{did}/reprocess", headers=bob).status_code == 404
    assert client.delete(f"/documents/{did}", headers=bob).status_code == 404
    assert client.get("/documents", headers=bob).json()["total"] == 0
    assert client.get(f"/documents/{did}", headers=alice).status_code == 200  # still there for the owner


def test_other_user_cannot_delete_items_of_my_document(client, alice, bob):
    doc = upload_ok(client, alice)
    item_id = client.get(f"/documents/{doc['id']}", headers=alice).json()["items"][0]["id"]
    assert client.delete(f"/documents/{doc['id']}/items/{item_id}", headers=bob).status_code == 404
