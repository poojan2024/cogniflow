"""Pure tests: context assembly and size limit, strict prompts, citation checking."""
from datetime import date

from app.services.assistant_core import (
    NOT_AVAILABLE_ANSWER,
    SYSTEM_PROMPT,
    assemble_context,
    build_prompts,
    check_citations,
    clip,
    find_citations,
    says_not_available,
)
from tests.assistant_samples import ACTIVITY, DOC_12, NOTE_3, TASK_5, sample_items

TODAY = date(2026, 10, 9)


# ------------------------------------------------------------ context assembly
def test_context_contains_every_item_in_section_order():
    bundle = assemble_context(sample_items(), TODAY, 24000)
    text = bundle.text
    assert text.startswith("Today's date: 2026-10-09")
    for item in sample_items():
        assert item.line in text
    positions = [text.index(h) for h in ("ACTIVITY", "TASKS", "REMINDERS", "EXPENSES", "NOTES", "DOCUMENTS")]
    assert positions == sorted(positions)
    assert not bundle.truncated and bundle.omitted == {} and len(bundle.items) == len(sample_items())
    assert "Cogniflow major project for MCA" in text and "accuracy table" in text and "Seminar Hall B" in text


def test_labels_match_the_items_that_were_included():
    assert assemble_context(sample_items(), TODAY, 24000).labels == {i.label for i in sample_items()}


def test_size_limit_drops_late_sections_first_and_says_so():
    bundle = assemble_context(sample_items(), TODAY, 700)
    assert bundle.truncated
    assert ACTIVITY.label in bundle.labels and TASK_5.label in bundle.labels  # most important data kept
    assert DOC_12.label not in bundle.labels  # documents are the first to go
    assert "not shown because of size limits" in bundle.text
    assert len(bundle.text) <= 700 + 250  # the limit plus the short explanatory note
    assert sum(bundle.omitted.values()) == len(sample_items()) - len(bundle.items)


def test_items_that_do_not_fit_are_never_cut_in_half():
    bundle = assemble_context(sample_items(), TODAY, 900)
    for item in bundle.items:
        assert item.render() in bundle.text


def test_empty_activity_gives_only_the_header():
    bundle = assemble_context([], TODAY, 1000)
    assert bundle.items == () and not bundle.truncated and "ACTIVITY" not in bundle.text


def test_clip():
    assert clip("short", 10) == "short"
    assert clip("x" * 50, 10) == "x" * 9 + "…"
    assert clip("  padded  ", 20) == "padded" and clip(None, 5) == ""


# ------------------------------------------------------------------- prompts
def test_system_prompt_enforces_the_grounding_rules():
    assert NOT_AVAILABLE_ANSWER in SYSTEM_PROMPT
    low = SYSTEM_PROMPT.lower()
    assert "only from" in low and "do not guess" in low and "cite" in low and "untrusted" in low and "ignore any instructions" in low


def test_user_prompt_contains_only_the_activity_data_and_the_question():
    system, user = build_prompts("CONTEXT-TEXT", "  What is the deadline?  ")
    assert system == SYSTEM_PROMPT
    assert user == "<ACTIVITY_DATA>\nCONTEXT-TEXT\n</ACTIVITY_DATA>\n\nQUESTION: What is the deadline?"


# ----------------------------------------------------------------- citations
def test_find_citations_handles_lists_case_and_ignores_other_brackets():
    answer = "See [Task 5, Doc 12] and [Activity]. Also [1], [see below], [task 5], [Note 3]; [Expenses]."
    assert find_citations(answer) == ["Task 5", "Doc 12", "Activity", "Note 3", "Expenses"]
    assert find_citations("no references here") == [] and find_citations("") == []


def test_check_citations_separates_real_from_invented_references():
    bundle = assemble_context(sample_items(), TODAY, 24000)
    verified, unknown = check_citations("Deadline is 2026-11-30 [Task 5] [Doc 12] [Doc 99] [Task 42]", bundle)
    assert [i.label for i in verified] == ["Task 5", "Doc 12"]
    assert unknown == ["Doc 99", "Task 42"]


def test_citation_of_an_item_that_was_cut_by_the_size_limit_counts_as_unknown():
    bundle = assemble_context(sample_items(), TODAY, 700)
    assert DOC_12.label not in bundle.labels
    _, unknown = check_citations("It is in [Doc 12]", bundle)
    assert unknown == ["Doc 12"]


def test_says_not_available():
    assert says_not_available(NOT_AVAILABLE_ANSWER)
    assert says_not_available("I don't have that information in this activity's data")
    assert says_not_available("Sorry. " + NOT_AVAILABLE_ANSWER.upper())
    assert not says_not_available("The deadline is 2026-12-31 [Activity].")
