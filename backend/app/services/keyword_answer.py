"""Non-AI answers from an activity's stored data: the fallback when Gemini fails, and the privacy-friendly local mode.

It never generates new statements. It only lists the stored items that match the question, quoting the stored text,
so it cannot invent anything. How it chooses:
  * words in the question that name a kind of data ("tasks", "documents", "expenses", "deadline" ...) select all
    items of that kind;
  * other words are matched against the text of every item (rarer words count more);
  * if nothing matches, it says so.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, List, Sequence, Set, Tuple

from app.services.activity_matching import tokenize
from app.services.assistant_core import ContextItem
from app.services.snippets import make_snippet

NO_MATCH_ANSWER = "I couldn't find anything related to your question in this activity's stored information."
HEADER = "Here is what I found in this activity's stored data (keyword search, not AI):"
MAX_INTENT_ITEMS = 10
MAX_MATCHED_ITEMS = 5
MAX_TOTAL_ITEMS = 12

# question words (already lower-cased and stemmed by tokenize) -> kind of data they ask about
INTENT_WORDS: Dict[str, Set[str]] = {
    "task": {"task", "todo", "pending", "remaining", "unfinished", "complete", "completed", "finish", "overdue", "progress"},
    "document": {"document", "file", "upload", "uploaded", "pdf", "attachment", "scan", "scanned"},
    "note": {"note", "notes"},
    "expense": {"expense", "cost", "spent", "spend", "spending", "total", "money", "paid", "pay", "price", "budget", "bill", "amount"},
    "reminder": {"reminder", "remind", "alert"},
    "activity": {"deadline", "due", "date", "start", "status", "priority", "description", "type", "overview", "summary", "summarize"},
}
DEADLINE_WORDS = {"deadline", "due", "overdue", "date"}
SUMMARY_WORDS = {"summary", "summarize", "overview"}
DATED = re.compile(r"\bdue \d{4}-\d{2}-\d{2}")  # task lines with a due date look like "| due 2026-11-30 ..."


@dataclass(frozen=True)
class KeywordAnswer:
    text: str
    items: Tuple[ContextItem, ...]  # the items the answer is based on (empty when nothing was found)

    @property
    def found(self) -> bool:
        return bool(self.items)


def _scores(question_tokens: Set[str], items: Sequence[ContextItem]) -> Dict[str, Tuple[float, str]]:
    """label -> (score, best matching word) using rarity-weighted word overlap."""
    item_tokens = {i.label: set(tokenize(i.line + " " + i.body)) for i in items}
    n = len(items)
    df = {t: sum(1 for toks in item_tokens.values() if t in toks) for t in question_tokens}
    result: Dict[str, Tuple[float, str]] = {}
    for label, toks in item_tokens.items():
        hits = [(math.log((n + 1) / (df[t] + 1)) + 1.0, t) for t in question_tokens if t in toks]
        if hits:
            result[label] = (sum(w for w, _ in hits), max(hits)[1])
    return result


def answer_from_keywords(question: str, items: Sequence[ContextItem]) -> KeywordAnswer:
    tokens = set(tokenize(question))
    selected: List[ContextItem] = []
    best_word: Dict[str, str] = {}

    def add(item: ContextItem) -> None:
        if all(item.label != s.label for s in selected):
            selected.append(item)

    # 1) words that name a kind of data select every item of that kind
    intents = {kind for kind, words in INTENT_WORDS.items() if tokens & words}
    for kind in intents:
        for item in [i for i in items if i.kind == kind][:MAX_INTENT_ITEMS]:
            add(item)
    if tokens & DEADLINE_WORDS:  # deadline questions also need the tasks that have a due date
        for item in [i for i in items if i.kind == "task" and DATED.search(i.line)][:5]:
            add(item)
    if tokens & SUMMARY_WORDS:
        for kind in ("task", "expense", "note", "document"):
            for item in [i for i in items if i.kind == kind][:3]:
                add(item)

    # 2) words matched against the text of all items
    scores = _scores(tokens - set().union(*INTENT_WORDS.values()), items) if items else {}
    by_label = {i.label: i for i in items}
    for label, (score, word) in sorted(scores.items(), key=lambda kv: (-kv[1][0], kv[0]))[:MAX_MATCHED_ITEMS]:
        add(by_label[label])
        best_word[label] = word

    selected = selected[:MAX_TOTAL_ITEMS]
    if not selected:
        return KeywordAnswer(NO_MATCH_ANSWER, ())

    lines = [HEADER]
    for item in selected:
        lines.append(f"- {item.line}")
        word = best_word.get(item.label)
        if word and item.body:
            snippet = make_snippet(item.body, word)
            if snippet:
                lines.append(f"    {snippet}")
    return KeywordAnswer("\n".join(lines), tuple(selected))
