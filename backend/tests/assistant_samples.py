"""Sample activity data (pure, no database) shared by the assistant tests. Line formats match what the real context
builder produces (services/assistant_context.py)."""
from app.services.assistant_core import ContextItem

ACTIVITY = ContextItem(
    "Activity", "activity", "MCA Final-Year Project",
    "[Activity] MCA Final-Year Project | type PROJECT | status ACTIVE | priority 4/5 | start 2026-07-01 | deadline 2026-12-31 (83 days left)",
    "Description: Cogniflow major project for MCA",
)
TASK_5 = ContextItem("Task 5", "task", "Write chapter 1",
                     "[Task 5] Write chapter 1 | status PENDING | due 2026-11-30 (52 days left) | importance 4/5 | priority HIGH (score 70.4)")
TASK_6 = ContextItem("Task 6", "task", "Prepare viva slides",
                     "[Task 6] Prepare viva slides | status PENDING | no due date | importance 3/5 | priority LOW (score 30.0)")
TASK_7 = ContextItem("Task 7", "task", "Submit synopsis",
                     "[Task 7] Submit synopsis | status COMPLETED | due 2026-09-01 | importance 5/5 | completed")
REMINDER = ContextItem("Reminder 2", "reminder", "Submit report",
                       "[Reminder 2] Submit report | at 2026-10-12 03:30 UTC | not yet triggered")
EXPENSE_TOTAL = ContextItem("Expenses", "expense", "Expense total", "[Expenses] Total of 2 expenses: 4200.00")
EXPENSE_7 = ContextItem("Expense 7", "expense", "Hotel", "[Expense 7] Hotel | category Stay | 3000.00 | 2026-11-02")
EXPENSE_8 = ContextItem("Expense 8", "expense", "Transport", "[Expense 8] Transport | category Travel | 1200.00 | 2026-11-01")
NOTE_3 = ContextItem("Note 3", "note", "Supervisor meeting", "[Note 3] Supervisor meeting",
                     "Discuss the OCR module and testing plan. The supervisor wants the accuracy table.")
DOC_12 = ContextItem("Doc 12", "document", "notice.txt", "[Doc 12] notice.txt | status PROCESSED | extraction TEXT",
                     "Extracted facts: DEADLINE 2026-11-30; LOCATION Seminar Hall B\nText: EXAM NOTICE The semester exam timetable is attached.")
DOC_13 = ContextItem("Doc 13", "document", "report.pdf", "[Doc 13] report.pdf | status PROCESSED | extraction TEXT",
                     "Text: The database design and system architecture chapter is complete.")


def sample_items():
    return [ACTIVITY, TASK_5, TASK_6, TASK_7, REMINDER, EXPENSE_TOTAL, EXPENSE_7, EXPENSE_8, NOTE_3, DOC_12, DOC_13]
