"""Unit tests for explainable activity matching (no database, no HTTP)."""
from datetime import date

from app.services.activity_matching import (
    MIN_SUGGEST_SCORE,
    WEIGHTS,
    ActivityProfile,
    DocumentInfo,
    confidence_label,
    rank_activities,
    tokenize,
)
from app.services.info_extraction import extract_information
from app.services.text_cleaning import clean_text

PROJECT = ActivityProfile(1, "MCA Final-Year Project", "PROJECT", "Cogniflow major project for MCA",
                          date(2026, 7, 1), date(2026, 12, 31))
TRIP = ActivityProfile(2, "Goa Trip", "TRIP", "Beach holiday with friends", date(2026, 11, 20), date(2026, 11, 25))
EXAM = ActivityProfile(3, "DBMS Exam", "EXAM", "Database management systems semester exam", None, date(2026, 11, 30))
MEETING = ActivityProfile(4, "Weekly Team Meeting", "MEETING")
ALL = [PROJECT, TRIP, EXAM, MEETING]

PROJECT_DOC = ("MCA Final-Year Project Report\nProject synopsis submitted to the supervisor. The project report covers "
               "the database design, system architecture and the final year project schedule.\nSubmission deadline: 15/12/2026")
EXAM_DOC = ("EXAM NOTICE\nThe semester examination for Database Management Systems will start on 25/11/2026.\n"
            "Hall ticket must be carried. Timetable attached.\nVenue: Seminar Hall B")
TRIP_DOC = ("Flight booking confirmation\nItinerary: Bengaluru to Goa, 20 Nov 2026. Hotel check-in 20 Nov 2026 at "
            "Beach Resort. PNR 4XY7Q. Total amount Rs. 3,000")
MEETING_DOC = "Minutes of the meeting. Agenda: weekly team progress review. Attendees: Dr. Rao, Anita."
RECIPE_DOC = ("Chocolate cake recipe. Mix flour, sugar and cocoa. Bake for forty minutes. "
              "Let the cake cool before adding frosting and serve with cream.")
DOCTOR_DOC = "Appointment slip. Patient: Rahul Verma. Doctor consultation on 12 October 2026 at City Hospital clinic."


def info(raw: str) -> DocumentInfo:
    """Document -> matching input, using the real extraction rules (the same path the application takes)."""
    text = clean_text(raw)
    items = extract_information(text)
    doc_type = next((i.value for i in items if i.info_type == "DOCUMENT_TYPE"), None)
    dates = tuple(date.fromisoformat(i.value) for i in items if i.info_type in ("DATE", "DEADLINE"))
    return DocumentInfo(text, doc_type, dates)


def best(raw: str, profiles=ALL):
    return rank_activities(info(raw), profiles)[0]


def suggested(raw: str, profiles=ALL):
    return [m.activity_id for m in rank_activities(info(raw), profiles) if m.score >= MIN_SUGGEST_SCORE]


# ------------------------------------------------------- realistic documents
def test_project_document_goes_to_the_project():
    top = best(PROJECT_DOC)
    assert top.activity_id == 1 and top.score >= 60
    assert suggested(PROJECT_DOC) == [1]


def test_exam_notice_goes_to_the_exam():
    assert suggested(EXAM_DOC) == [3]


def test_travel_booking_goes_to_the_trip():
    assert suggested(TRIP_DOC) == [2]


def test_meeting_minutes_go_to_the_meeting():
    assert suggested(MEETING_DOC) == [4]


def test_unrelated_document_gets_no_suggestion():
    assert suggested(RECIPE_DOC) == []


def test_document_with_no_matching_activity_gets_no_suggestion():
    """A doctor's slip while the user has no appointment activity: dates alone must not trigger a suggestion."""
    assert suggested(DOCTOR_DOC) == []


# --------------------------------------------------------------- explainability
def test_explanation_names_the_reasons():
    top = best(PROJECT_DOC)
    text = top.explanation
    assert text.startswith(f"Match score {top.score:.1f}/100")
    assert "mca" in text and "2026-12-15" in text and "Project / Academic" in text
    assert set(top.points) == {"text similarity", "title words", "document type", "dates"}
    assert abs(sum(top.points.values()) - top.score) < 0.05


def test_no_signal_explanation_is_honest():
    top = best(RECIPE_DOC)
    assert top.score == 0.0 and "No clear similarity" in top.explanation


# -------------------------------------------------------- individual signals
def test_weights_sum_to_one_and_weak_signals_alone_cannot_trigger_a_suggestion():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9
    assert 100 * (WEIGHTS["type"] + WEIGHTS["date"]) < MIN_SUGGEST_SCORE


def test_title_words_points_are_proportional():
    activity = ActivityProfile(9, "Database Systems Lab", "CUSTOM")
    top = rank_activities(DocumentInfo("We use the database in the lab every week."), [activity])[0]
    assert top.points["title words"] == 20.0  # 2 of the 3 title words (database, lab) are in the document


def test_document_type_hint_only_for_matching_activity_type():
    doc = DocumentInfo("Exam hall ticket and timetable", "Exam notice")
    exam = ActivityProfile(1, "Semester Exam", "EXAM")
    other = ActivityProfile(2, "Semester Exam", "PERSONAL")
    ranked = {m.activity_id: m for m in rank_activities(doc, [exam, other])}
    assert ranked[1].points["document type"] == 15.0 and ranked[2].points["document type"] == 0.0


def test_date_must_fall_inside_the_activity_window():
    activity = ActivityProfile(1, "Report", "CUSTOM", start_date=date(2026, 6, 1), deadline=date(2026, 6, 30))
    inside = rank_activities(DocumentInfo("some text here", None, (date(2026, 6, 15),)), [activity])[0]
    grace = rank_activities(DocumentInfo("some text here", None, (date(2026, 7, 5),)), [activity])[0]  # within 7 days
    outside = rank_activities(DocumentInfo("some text here", None, (date(2026, 9, 1),)), [activity])[0]
    assert (inside.points["dates"], grace.points["dates"], outside.points["dates"]) == (10.0, 10.0, 0.0)


def test_activity_with_only_a_deadline_uses_a_90_day_window():
    activity = ActivityProfile(1, "Report", "CUSTOM", deadline=date(2026, 12, 31))
    near = rank_activities(DocumentInfo("some text here", None, (date(2026, 11, 15),)), [activity])[0]
    far = rank_activities(DocumentInfo("some text here", None, (date(2026, 6, 1),)), [activity])[0]
    assert near.points["dates"] == 10.0 and far.points["dates"] == 0.0


def test_activity_without_dates_never_gets_date_points():
    activity = ActivityProfile(1, "Report", "CUSTOM")
    assert rank_activities(DocumentInfo("some text", None, (date(2026, 1, 1),)), [activity])[0].points["dates"] == 0.0


def test_documents_already_in_the_activity_improve_matching():
    doc = DocumentInfo("compiler design syllabus covering lexical analysis and parsing techniques")
    plain = ActivityProfile(1, "Semester Prep", "CUSTOM")
    informed = ActivityProfile(1, "Semester Prep", "CUSTOM",
                               extra_text="lexical analysis parsing compiler notes and syllabus topics")
    other = ActivityProfile(2, "Garden Work", "CUSTOM")
    before = rank_activities(doc, [plain, other])[0].points["text similarity"]
    after = rank_activities(doc, [informed, other])[0].points["text similarity"]
    assert after > before


# ------------------------------------------------------------ ranking rules
def test_close_scores_are_flagged_as_ambiguous_and_ties_go_to_the_lower_id():
    twin_a = ActivityProfile(5, "Project Work", "PROJECT")
    twin_b = ActivityProfile(6, "Project Work", "PROJECT")
    ranked = rank_activities(DocumentInfo("project work report for the project", "Project / Academic"), [twin_b, twin_a])
    assert [m.activity_id for m in ranked] == [5, 6]
    assert "Another activity scored almost the same" in ranked[0].explanation


def test_results_are_sorted_best_first():
    scores = [m.score for m in rank_activities(info(EXAM_DOC), ALL)]
    assert scores == sorted(scores, reverse=True)


def test_ranking_is_deterministic():
    assert rank_activities(info(TRIP_DOC), ALL) == rank_activities(info(TRIP_DOC), ALL)


def test_no_activities_and_empty_document():
    assert rank_activities(info(PROJECT_DOC), []) == []
    ranked = rank_activities(DocumentInfo("   "), ALL)
    assert [m.score for m in ranked] == [0.0] * 4 and "no readable words" in ranked[0].explanation


# ------------------------------------------------------------------- helpers
def test_tokenize_lowercases_drops_stopwords_and_handles_plurals():
    assert tokenize("The Exams and Studies, of an MCA 2026!") == ["exam", "study", "mca"]
    assert tokenize("Final-Year Project") == ["final", "year", "project"]


def test_plural_forms_match():
    doc = DocumentInfo("Please bring your exams hall tickets")
    activity = ActivityProfile(1, "Exam", "CUSTOM")
    assert rank_activities(doc, [activity])[0].points["title words"] == 30.0


def test_confidence_labels():
    assert confidence_label(75) == "strong" and confidence_label(60) == "strong"
    assert confidence_label(59.9) == "moderate" and confidence_label(40) == "moderate"
    assert confidence_label(39.9) == "weak"
