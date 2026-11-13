"""Rule-based information extraction. Deterministic, no AI, no network.

Every item keeps the line it came from (`context`), so the user can verify it and delete a wrong one.

Honest limits:
  * Dates written as 03/04/2026 are read DAY-FIRST (03 April), the usual order in India. Month-first is only
    used when the day-first reading is impossible (for example 04/25/2026). The context lets the user check.
  * Names and locations are found only from simple patterns (titles such as Dr./Prof., or labels such as
    "Name:", "Venue:"). This is much weaker than a trained NER model, so expect misses.
  * OCR mistakes (for example the rupee sign read as another character) can cause missed amounts.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

MAX_PER_TYPE = 10
MAX_CONTEXT = 250


@dataclass(frozen=True)
class Item:
    info_type: str  # one of models.INFO_TYPES
    value: str
    context: Optional[str] = None


# ------------------------------------------------------------------- dates
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MONTH_NAME = r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_NOT_PART_OF_NUMBER = r"(?<![\d/.\-])"

_DATE_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("iso", re.compile(_NOT_PART_OF_NUMBER + r"(\d{4})-(\d{1,2})-(\d{1,2})(?![\d])")),
    ("numeric", re.compile(_NOT_PART_OF_NUMBER + r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4}|\d{2})(?![\d])")),
    ("dmy_name", re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s,\-]+(?:of\s+)?" + _MONTH_NAME + r"\.?,?[\s\-]+(\d{4})\b", re.I)),
    ("mdy_name", re.compile(r"\b" + _MONTH_NAME + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I)),
]

_DEADLINE_PHRASES = (
    "deadline", "due date", "due on", "due by", "due:", "last date", "submit by", "submitted by",
    "submission", "on or before", "no later than", "not later than", "closing date", "register by",
    "apply by", "expires", "expiry", "must be submitted", "to be submitted",
)


def _valid_date(year: int, month: int, day: int) -> Optional[date]:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parse_date_match(kind: str, m: "re.Match[str]") -> Optional[date]:
    g = m.groups()
    if kind == "iso":
        return _valid_date(int(g[0]), int(g[1]), int(g[2]))
    if kind == "numeric":
        a, b, y = int(g[0]), int(g[1]), int(g[2])
        year = 2000 + y if y < 100 else y
        return _valid_date(year, b, a) or _valid_date(year, a, b)  # day-first, month-first only as a fallback
    if kind == "dmy_name":
        return _valid_date(int(g[2]), _MONTHS[g[1][:3].lower()], int(g[0]))
    if kind == "mdy_name":
        return _valid_date(int(g[2]), _MONTHS[g[0][:3].lower()], int(g[1]))
    return None


def _line_context(line: str) -> str:
    line = line.strip()
    return line if len(line) <= MAX_CONTEXT else line[: MAX_CONTEXT - 1] + "…"


def _extract_dates(lines: List[str]) -> Tuple[List[Item], List[Item]]:
    deadlines: List[Item] = []
    dates: List[Item] = []
    seen = set()
    for line in lines:
        found = []
        for kind, pattern in _DATE_PATTERNS:
            for m in pattern.finditer(line):
                parsed = _parse_date_match(kind, m)
                if parsed:
                    found.append((m.start(), m.end(), parsed))
        found.sort()
        last_end = -1
        for start, end, parsed in found:
            if start < last_end:  # overlaps a previous match on this line
                continue
            last_end = end
            iso = parsed.isoformat()
            before = line[max(0, start - 80):start].lower()
            is_deadline = any(p in before for p in _DEADLINE_PHRASES)
            key = ("DEADLINE" if is_deadline else "DATE", iso)
            if key in seen:
                continue
            seen.add(key)
            (deadlines if is_deadline else dates).append(Item(key[0], iso, _line_context(line)))
    return deadlines, dates


# ----------------------------------------------------------------- amounts
_CURRENCIES = {"₹": "INR", "rs": "INR", "rs.": "INR", "inr": "INR", "$": "USD", "usd": "USD",
               "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP"}
_NUMBER = r"\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"
_AMOUNT_BEFORE = re.compile(r"(?:(₹|\bRs\.?|\bINR|\bUSD|\$|€|£|\bEUR|\bGBP)\s?)(" + _NUMBER + r")", re.I)
_AMOUNT_AFTER = re.compile(r"\b(" + _NUMBER + r")\s?(rupees|INR|Rs\.?)(?![A-Za-z])", re.I)


def _to_amount(currency: str, number: str) -> Optional[str]:
    try:
        value = Decimal(number.replace(",", ""))
    except InvalidOperation:
        return None
    if value <= 0:
        return None
    code = _CURRENCIES.get(currency.lower(), "INR" if currency.lower() == "rupees" else None)
    return f"{code} {value:.2f}" if code else None


def _extract_amounts(lines: List[str]) -> List[Item]:
    items, seen = [], set()
    for line in lines:
        matches = [(m.start(), _to_amount(m.group(1), m.group(2))) for m in _AMOUNT_BEFORE.finditer(line)]
        matches += [(m.start(), _to_amount(m.group(2), m.group(1))) for m in _AMOUNT_AFTER.finditer(line)]
        for _, value in sorted(matches, key=lambda x: x[0]):
            if value and (value, line) not in seen:
                seen.add((value, line))
                items.append(Item("AMOUNT", value, _line_context(line)))
    return items


# ----------------------------------------------------------- document type
_DOC_TYPES: List[Tuple[str, Tuple[str, ...]]] = [
    ("Invoice / Receipt", ("invoice", "receipt", "bill", "total amount", "gst", "amount due", "paid", "payment")),
    ("Exam notice", ("exam", "examination", "timetable", "time table", "hall ticket", "admit card", "syllabus", "semester")),
    ("Appointment", ("appointment", "doctor", "clinic", "hospital", "consultation", "patient")),
    ("Meeting", ("meeting", "agenda", "minutes", "attendees", "zoom", "conference call")),
    ("Travel / Booking", ("ticket", "booking", "itinerary", "flight", "hotel", "check-in", "pnr", "boarding")),
    ("Project / Academic", ("project", "synopsis", "thesis", "abstract", "supervisor", "dissertation", "guide")),
    ("Certificate", ("certificate", "certify", "certified", "awarded")),
    ("Notice / Circular", ("notice", "circular", "hereby", "notified")),
]


def _classify(text: str) -> Optional[Item]:
    """Pick the type with the most distinct keyword hits. At least 2 hits are required, so weak guesses are skipped."""
    lowered = text.lower()
    best_label, best_hits = None, []
    for label, words in _DOC_TYPES:
        hits = [w for w in words if re.search(r"\b" + re.escape(w) + r"\b", lowered)]
        if len(hits) > len(best_hits):
            best_label, best_hits = label, hits
    if best_label and len(best_hits) >= 2:
        return Item("DOCUMENT_TYPE", best_label, "Matched keywords: " + ", ".join(best_hits))
    return None


# --------------------------------------------------------- names, locations
_TITLE_NAME = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Prof)\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})")
_LABEL_NAME = re.compile(
    r"\b(?:Dear|Name|Candidate Name|Student Name|Patient Name|Attendee|Prepared by|Submitted by)\s*[:\-]?\s+"
    r"((?:(?:Mr|Mrs|Ms|Dr|Prof)\.?\s+)?[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})"
)
_NOT_NAMES = {"Sir", "Madam", "All", "Team", "Students", "Student", "Candidate", "Parent", "Parents", "Sir Madam"}
_LOCATION = re.compile(r"\b(?:Venue|Location|Place|Address)\s*[:\-]\s*(.{3,80})", re.I)


def _extract_people(lines: List[str]) -> List[Item]:
    items, seen = [], set()
    for line in lines:
        for pattern in (_TITLE_NAME, _LABEL_NAME):
            for m in pattern.finditer(line):
                name = re.sub(r"\s+", " ", m.group(0) if pattern is _TITLE_NAME else m.group(1)).strip()
                if name in _NOT_NAMES or name in seen:
                    continue
                seen.add(name)
                items.append(Item("PERSON", name, _line_context(line)))
    return items


def _extract_locations(lines: List[str]) -> List[Item]:
    items, seen = [], set()
    for line in lines:
        m = _LOCATION.search(line)
        if m:
            place = m.group(1).strip(" .,;")
            if place and place.lower() not in seen:
                seen.add(place.lower())
                items.append(Item("LOCATION", place, _line_context(line)))
    return items


# ---------------------------------------------------------------- keywords
_STOPWORDS = set("""
about above after again against all also and any are because been before being below between both but can could
did does doing down during each few for from further had has have having her here hers him his how into its just
more most other our out over own same she should some such than that the their theirs them then there these they
this those through too under until very was were what when where which while who whom why will with would you your
yours please kindly regards thanks thank dear sir madam shall must may might upon within without
""".split())


STOPWORDS = _STOPWORDS  # public name, also used by activity matching


def _extract_keywords(text: str) -> List[Item]:
    words = re.findall(r"[A-Za-z]{4,}", text.lower())
    counts = Counter(w for w in words if w not in _STOPWORDS)
    top = [(w, c) for w, c in sorted(counts.items(), key=lambda x: (-x[1], x[0])) if c >= 2][:8]
    return [Item("KEYWORD", w, f"appears {c} times") for w, c in top]


# ------------------------------------------------------------------ entry
def extract_information(text: str) -> List[Item]:
    """Run all rules on cleaned text. Returns items ordered by type, at most MAX_PER_TYPE of each."""
    if not text or not text.strip():
        return []
    lines = [ln for ln in text.split("\n") if ln.strip()]

    deadlines, dates = _extract_dates(lines)
    doc_type = _classify(text)
    groups: Dict[str, List[Item]] = {
        "DOCUMENT_TYPE": [doc_type] if doc_type else [],
        "DEADLINE": deadlines,
        "DATE": dates,
        "AMOUNT": _extract_amounts(lines),
        "PERSON": _extract_people(lines),
        "LOCATION": _extract_locations(lines),
        "KEYWORD": _extract_keywords(text),
    }
    result: List[Item] = []
    for items in groups.values():
        result.extend(items[:MAX_PER_TYPE])
    return result
