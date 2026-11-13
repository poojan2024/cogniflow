"""Tests for the document-pipeline building blocks (no database, no HTTP).

The OCR tests run real Tesseract and are skipped automatically if Tesseract is not installed.
"""
import io
from pathlib import Path

import pytest

from app.services import text_extraction
from app.services.file_validation import UploadRejected, sanitize_filename, validate_upload
from app.services.info_extraction import extract_information
from app.services.text_cleaning import clean_text
from app.services.text_extraction import extract_text, tesseract_available
from tests.helpers import make_image_pdf, make_text_image, make_text_image_obj, make_text_pdf

needs_tesseract = pytest.mark.skipif(not tesseract_available(), reason="Tesseract is not installed")


def by_type(items, info_type):
    return [i.value for i in items if i.info_type == info_type]


# --------------------------------------------------------- file validation
def test_valid_files_are_accepted():
    assert validate_upload("Notice.pdf", make_text_pdf(["hi"])).kind == "pdf"
    assert validate_upload("scan.PNG", make_text_image(["hi"])).kind == "image"
    assert validate_upload("photo.jpeg", make_text_image(["hi"], "JPEG")).extension == ".jpg"
    assert validate_upload("notes.txt", b"plain text").kind == "txt"


def test_unsupported_extension_is_rejected_with_415():
    for name in ("virus.exe", "page.html", "script.py", "archive.zip", "noextension"):
        with pytest.raises(UploadRejected) as e:
            validate_upload(name, b"data")
        assert e.value.status_code == 415


def test_content_must_match_extension():
    with pytest.raises(UploadRejected):
        validate_upload("fake.pdf", b"this is not a pdf")
    with pytest.raises(UploadRejected):
        validate_upload("fake.png", make_text_pdf(["x"]))  # a PDF renamed to .png
    with pytest.raises(UploadRejected):
        validate_upload("fake.txt", make_text_pdf(["x"]))  # a PDF renamed to .txt
    with pytest.raises(UploadRejected):
        validate_upload("binary.txt", b"abc\x00def")


def test_empty_and_corrupted_files_are_rejected():
    with pytest.raises(UploadRejected):
        validate_upload("empty.txt", b"")
    with pytest.raises(UploadRejected):
        validate_upload("broken.png", b"\x89PNG\r\n\x1a\n" + b"garbage" * 10)


def test_filename_is_sanitized():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("C:\\Users\\me\\notice.pdf") == "notice.pdf"
    assert sanitize_filename("a\x00b\nc.pdf") == "abc.pdf"
    assert sanitize_filename("") == "document"
    assert len(sanitize_filename("x" * 500 + ".pdf")) <= 200


# ------------------------------------------------------------ text cleaning
def test_clean_text_normalizes_whitespace_and_hyphenation():
    raw = "Exam-\nination   date\t\tis  fixed.\r\n\r\n\r\n\r\nBring ID.\x00"
    assert clean_text(raw) == "Examination date is fixed.\n\nBring ID."


def test_clean_text_keeps_hyphen_before_capital_and_handles_empty():
    assert clean_text("Mid-\nTerm") == "Mid-\nTerm"
    assert clean_text(None) == "" and clean_text("   \n ") == ""


# -------------------------------------------------------- rule-based extraction
def test_dates_in_several_formats_are_normalized():
    text = "Dates: 12/03/2026, 2026-04-05, 7 May 2026, June 9, 2026 and 15th Aug 2026."
    assert by_type(extract_information(text), "DATE") == [
        "2026-03-12", "2026-04-05", "2026-05-07", "2026-06-09", "2026-08-15",
    ]


def test_numeric_dates_are_day_first_with_month_first_fallback():
    assert by_type(extract_information("On 03/04/2026"), "DATE") == ["2026-04-03"]  # 3 April
    assert by_type(extract_information("On 04/25/2026"), "DATE") == ["2026-04-25"]  # only valid as month-first


def test_invalid_dates_are_ignored():
    assert by_type(extract_information("31/02/2026 and 2026-13-45"), "DATE") == []


def test_deadline_keywords_turn_a_date_into_a_deadline():
    items = extract_information("Last date to submit: 30/11/2026\nExam on 05/12/2026")
    assert by_type(items, "DEADLINE") == ["2026-11-30"]
    assert by_type(items, "DATE") == ["2026-12-05"]
    deadline = next(i for i in items if i.info_type == "DEADLINE")
    assert "Last date to submit" in deadline.context  # the source line is kept for verification


def test_amounts_are_normalized_with_currency():
    text = "Hotel ₹3,000.50\nTransport Rs. 1200\nFood 800 rupees\nBooking fee $25\nTotal INR 1,00,000"
    assert by_type(extract_information(text), "AMOUNT") == [
        "INR 3000.50", "INR 1200.00", "INR 800.00", "USD 25.00", "INR 100000.00",
    ]


def test_plain_numbers_without_currency_are_not_amounts():
    assert by_type(extract_information("Room 204, 150 students, phone 9876543210"), "AMOUNT") == []


def test_document_type_needs_two_keyword_hits():
    invoice = extract_information("INVOICE\nTotal amount due: ₹500\nPayment received")
    assert by_type(invoice, "DOCUMENT_TYPE") == ["Invoice / Receipt"]
    assert by_type(extract_information("We had a meeting"), "DOCUMENT_TYPE") == []  # one hit is not enough


def test_people_and_locations_from_simple_patterns():
    text = "Dear Dr. Anita Sharma\nName: Rahul Verma\nVenue: Seminar Hall B, Main Building\nDear Sir"
    items = extract_information(text)
    assert by_type(items, "PERSON") == ["Dr. Anita Sharma", "Rahul Verma"]
    assert by_type(items, "LOCATION") == ["Seminar Hall B, Main Building"]


def test_keywords_need_to_repeat():
    text = "database design database schema database tables and one unique word"
    assert by_type(extract_information(text), "KEYWORD") == ["database"]


def test_empty_text_gives_no_items():
    assert extract_information("") == [] and extract_information("   \n  ") == []


def test_extraction_is_deterministic():
    text = "Deadline: 01/12/2026. Fee ₹500. Dr. Rao will attend."
    assert extract_information(text) == extract_information(text)


# ------------------------------------------------------- text file / text PDF
def test_text_file_extraction(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("Hello world, meeting on 5 May 2026", encoding="utf-8")
    r = extract_text(f, "txt")
    assert (r.method, r.status) == ("TEXT", "PROCESSED") and "meeting" in r.text


def test_empty_text_file_fails_honestly(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("   \n", encoding="utf-8")
    r = extract_text(f, "txt")
    assert r.status == "FAILED" and r.text == "" and r.message


def test_text_pdf_uses_embedded_text_not_ocr(tmp_path):
    f = tmp_path / "notice.pdf"
    f.write_bytes(make_text_pdf(["Exam Notice", "The semester exam starts on 12 March 2026 at Hall B."]))
    r = extract_text(f, "pdf")
    assert (r.method, r.status, r.ocr_confidence) == ("TEXT", "PROCESSED", None)
    assert "semester exam starts on 12 March 2026" in r.text


def test_corrupted_pdf_fails_with_safe_message(tmp_path):
    f = tmp_path / "bad.pdf"
    f.write_bytes(b"%PDF-1.4\nthis is not really a pdf")
    r = extract_text(f, "pdf")
    assert r.status == "FAILED" and r.text == "" and "corrupt" in r.message.lower()


# ------------------------------------------------------------------- OCR
@needs_tesseract
def test_image_goes_through_real_ocr(tmp_path):
    f = tmp_path / "notice.png"
    f.write_bytes(make_text_image(["EXAM NOTICE", "Last date to submit: 30/11/2026", "Fee: Rs. 500"]))
    r = extract_text(f, "image")
    assert r.method == "OCR" and r.status in ("PROCESSED", "NEEDS_REVIEW")
    assert r.ocr_confidence is not None and r.ocr_confidence > 50
    assert "EXAM" in r.text.upper() and "30/11/2026" in r.text
    items = extract_information(clean_text(r.text))
    assert "2026-11-30" in by_type(items, "DEADLINE")


@needs_tesseract
def test_blank_image_fails_instead_of_inventing_text(tmp_path):
    from PIL import Image

    f = tmp_path / "blank.png"
    Image.new("RGB", (600, 400), "white").save(f)
    r = extract_text(f, "image")
    assert r.status == "FAILED" and r.text == "" and r.message


@needs_tesseract
def test_noisy_image_is_not_reported_as_confident(tmp_path):
    """Heavily degraded text must come back FAILED or NEEDS_REVIEW, never a confident PROCESSED result."""
    import random

    img = make_text_image_obj(["Appointment on 12 March 2026"], size=20).convert("L").resize((500, 90))
    random.seed(1)
    pixels = img.load()
    for _ in range(9000):
        pixels[random.randrange(img.width), random.randrange(img.height)] = random.choice((0, 255))
    f = tmp_path / "noisy.png"
    img.save(f)
    r = extract_text(f, "image", min_confidence=95.0)
    assert r.status in ("FAILED", "NEEDS_REVIEW")


@needs_tesseract
def test_scanned_pdf_is_routed_to_ocr(tmp_path, monkeypatch):
    """pypdf finds no text in an image-only PDF, so the pipeline must render the pages and OCR them.
    Rendering is replaced here by the original picture so the test does not need pypdfium2."""
    f = tmp_path / "scan.pdf"
    f.write_bytes(make_image_pdf(["PROJECT REPORT", "Submission deadline 15/12/2026"]))
    picture = make_text_image_obj(["PROJECT REPORT", "Submission deadline 15/12/2026"])
    monkeypatch.setattr(text_extraction, "_render_pdf_pages", lambda path, max_pages, dpi=200: ([picture], 1))
    r = extract_text(f, "pdf")
    assert r.method == "OCR" and "15/12/2026" in r.text


def test_scanned_pdf_without_ocr_engine_reports_failure_honestly(tmp_path, monkeypatch):
    f = tmp_path / "scan.pdf"
    f.write_bytes(make_image_pdf(["PROJECT REPORT"]))

    def no_renderer(path, max_pages, dpi=200):
        raise text_extraction.OcrUnavailableError("missing")

    monkeypatch.setattr(text_extraction, "_render_pdf_pages", no_renderer)
    r = extract_text(f, "pdf")
    assert r.status == "FAILED" and r.text == "" and "Tesseract" in r.message  # nothing is made up


def test_missing_tesseract_gives_actionable_message(tmp_path, monkeypatch):
    from PIL import Image

    f = tmp_path / "a.png"
    Image.new("RGB", (200, 100), "white").save(f)
    monkeypatch.setattr(text_extraction, "find_tesseract", lambda configured="": None)
    r = extract_text(f, "image")
    assert r.status == "FAILED" and "TESSERACT_CMD" in r.message
