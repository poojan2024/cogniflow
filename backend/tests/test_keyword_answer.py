"""Pure tests for the non-AI keyword answers."""
from app.services.assistant_core import ContextItem
from app.services.keyword_answer import HEADER, NO_MATCH_ANSWER, answer_from_keywords
from tests.assistant_samples import (
    ACTIVITY, DOC_12, DOC_13, EXPENSE_7, EXPENSE_8, EXPENSE_TOTAL, NOTE_3, REMINDER, TASK_5, TASK_6, TASK_7, sample_items,
)


def labels(answer):
    return [i.label for i in answer.items]


def test_document_question_lists_all_documents_and_nothing_else():
    a = answer_from_keywords("What documents have I uploaded?", sample_items())
    assert labels(a) == ["Doc 12", "Doc 13"] and a.found
    assert a.text.startswith(HEADER) and "- [Doc 12] notice.txt" in a.text and "- [Doc 13] report.pdf" in a.text


def test_deadline_question_returns_the_activity_and_dated_open_tasks():
    a = answer_from_keywords("What is the project deadline?", sample_items())
    assert "Activity" in labels(a) and "Task 5" in labels(a)
    assert "deadline 2026-12-31" in a.text
    assert "Task 6" not in labels(a)  # no due date, so it cannot answer a deadline question


def test_expense_question_returns_the_total_and_the_expenses():
    a = answer_from_keywords("How much did I spend in total?", sample_items())
    assert labels(a)[:3] == ["Expenses", "Expense 7", "Expense 8"]
    assert "Total of 2 expenses: 4200.00" in a.text


def test_task_question_lists_open_and_completed_tasks():
    a = answer_from_keywords("Which tasks are still pending?", sample_items())
    assert [l for l in labels(a) if l.startswith("Task")] == ["Task 5", "Task 6", "Task 7"]


def test_reminder_question():
    assert labels(answer_from_keywords("Do I have any reminders?", sample_items())) == ["Reminder 2"]


def test_word_match_finds_the_note_and_shows_a_snippet_from_its_text():
    a = answer_from_keywords("what did the supervisor say about accuracy", sample_items())
    assert "Note 3" in labels(a) and "accuracy table" in a.text


def test_a_specific_word_matches_only_the_relevant_item():
    a = answer_from_keywords("OCR", sample_items())
    assert labels(a) == ["Note 3"]


def test_summary_question_samples_every_kind_of_data():
    a = answer_from_keywords("Summarize the important information", sample_items())
    kinds = {i.kind for i in a.items}
    assert {"activity", "task", "expense", "note", "document"} <= kinds


def test_unrelated_question_finds_nothing_and_does_not_invent():
    a = answer_from_keywords("What is the capital of France?", sample_items())
    assert a.text == NO_MATCH_ANSWER and not a.found and a.items == ()


def test_no_data_at_all():
    assert answer_from_keywords("What is the deadline?", []).text == NO_MATCH_ANSWER


def test_answer_only_quotes_stored_lines():
    """Every bullet of the answer is exactly a stored line: the keyword mode cannot make statements up."""
    a = answer_from_keywords("deadline documents expenses tasks", sample_items())
    stored = {i.line for i in sample_items()}
    bullets = [ln[2:] for ln in a.text.splitlines() if ln.startswith("- ")]
    assert bullets and all(b in stored for b in bullets)


def test_number_of_listed_items_is_capped():
    many = [ContextItem(f"Task {i}", "task", f"t{i}", f"[Task {i}] t{i} | status PENDING | due 2026-11-{i % 28 + 1:02d} (x days left)")
            for i in range(1, 40)]
    assert len(answer_from_keywords("tasks", many).items) <= 12


def test_results_are_deterministic():
    assert answer_from_keywords("deadline", sample_items()) == answer_from_keywords("deadline", sample_items())
