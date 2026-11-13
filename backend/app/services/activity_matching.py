"""Explainable document -> activity matching. Pure Python: no database, no AI, no network.

    score (0-100) = 100 x ( 0.45 x text_similarity
                          + 0.30 x title_words
                          + 0.15 x type_hint
                          + 0.10 x date_relevance )

  text_similarity  TF-IDF cosine similarity between the document text and the activity "profile"
                   (title repeated 3 times, description, type word, and the text / note titles / task titles
                   already inside the activity). A cosine of COSINE_FULL_SCORE or more counts as 1.0, because a
                   document is much longer than an activity profile, so even strongly related documents have
                   a low raw cosine.
  title_words      share of the activity title's meaningful words that appear in the document (0..1).
  type_hint        1 if the kind of document found by the extraction rules usually belongs to this activity type
                   (for example an exam notice -> Exam), otherwise 0.
  date_relevance   1 if a date or deadline found in the document falls within the activity's dates, otherwise 0.

Every match carries a plain-language explanation of exactly which signals contributed.

IMPORTANT (honesty): the weights, COSINE_FULL_SCORE and the thresholds are design judgements checked on a few
hand-made examples. They are NOT proven or tuned on real data. Suggestions are only suggestions: nothing is moved
until the user confirms (see routers/suggestions.py).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from app.services.info_extraction import STOPWORDS

WEIGHTS = {"text": 0.45, "title": 0.30, "type": 0.15, "date": 0.10}
COSINE_FULL_SCORE = 0.35
MIN_SUGGEST_SCORE = 30.0  # below this no suggestion is made
MAX_SUGGESTIONS = 3
TITLE_REPEAT = 3  # the title counts more than the description in the activity profile
DATE_WINDOW_DAYS = 90  # used when an activity has only a start date or only a deadline
DATE_GRACE_DAYS = 7
AMBIGUOUS_MARGIN = 5.0  # two best scores closer than this are reported as ambiguous

if abs(sum(WEIGHTS.values()) - 1.0) > 1e-9:
    raise RuntimeError("Matching weights must add up to 1.0")

# kind of document (from info_extraction) -> activity types it usually belongs to
DOC_TYPE_TO_ACTIVITY_TYPES: Dict[str, Tuple[str, ...]] = {
    "Exam notice": ("EXAM",),
    "Appointment": ("APPOINTMENT",),
    "Meeting": ("MEETING",),
    "Travel / Booking": ("TRIP",),
    "Project / Academic": ("PROJECT",),
}
TYPE_WORDS = {
    "EXAM": "exam", "TRIP": "trip travel", "MEETING": "meeting", "APPOINTMENT": "appointment",
    "PROJECT": "project", "EVENT": "event", "PERSONAL": "", "CUSTOM": "",
}


# ----------------------------------------------------------------- inputs
@dataclass(frozen=True)
class ActivityProfile:
    activity_id: int
    title: str
    activity_type: str
    description: str = ""
    start_date: Optional[date] = None
    deadline: Optional[date] = None
    extra_text: str = ""  # text of documents already in the activity, note and task titles


@dataclass(frozen=True)
class DocumentInfo:
    text: str
    doc_type: Optional[str] = None  # e.g. "Exam notice"
    dates: Tuple[date, ...] = ()  # dates and deadlines found in the document


@dataclass(frozen=True)
class Match:
    activity_id: int
    score: float  # 0..100
    explanation: str
    points: Dict[str, float] = field(default_factory=dict)  # contribution of each signal to the score


# ------------------------------------------------------------ text helpers
_WORD = re.compile(r"[a-z][a-z0-9]{2,}")


def _stem(word: str) -> str:
    """Very light plural handling so 'exams' matches 'exam'. (Not a real stemmer: a stated limitation.)"""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokenize(text: str) -> List[str]:
    return [_stem(w) for w in _WORD.findall((text or "").lower()) if w not in STOPWORDS]


def _idf(token_lists: Sequence[List[str]]) -> Tuple[Dict[str, float], float]:
    n = len(token_lists)
    df: Counter = Counter()
    for tokens in token_lists:
        df.update(set(tokens))
    idf = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}
    return idf, math.log(n + 1) + 1.0  # second value: idf for a word no activity contains


def _vector(tokens: List[str], idf: Dict[str, float], unseen_idf: float) -> Dict[str, float]:
    return {t: (1.0 + math.log(c)) * idf.get(t, unseen_idf) for t, c in Counter(tokens).items()}


def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b[t] for t, v in a.items() if t in b)
    norm = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return dot / norm if norm else 0.0


def _in_window(day: date, profile: ActivityProfile) -> bool:
    start, end = profile.start_date, profile.deadline
    if start is None and end is None:
        return False
    low = (start if start else end - timedelta(days=DATE_WINDOW_DAYS)) - timedelta(days=DATE_GRACE_DAYS)
    high = (end if end else start + timedelta(days=DATE_WINDOW_DAYS)) + timedelta(days=DATE_GRACE_DAYS)
    return low <= day <= high


def confidence_label(score: float) -> str:
    return "strong" if score >= 60 else "moderate" if score >= 40 else "weak"


def _words(items: Sequence[str], limit: int = 6) -> str:
    return ", ".join(items[:limit])


# ----------------------------------------------------------------- ranking
def rank_activities(document: DocumentInfo, profiles: Sequence[ActivityProfile]) -> List[Match]:
    """Score every activity (best first; ties by activity id). The caller applies MIN_SUGGEST_SCORE."""
    if not profiles:
        return []
    doc_tokens = tokenize(document.text)
    doc_set = set(doc_tokens)
    if not doc_set:
        return [Match(p.activity_id, 0.0, "The document has no readable words to compare.") for p in
                sorted(profiles, key=lambda p: p.activity_id)]

    profile_tokens = [
        tokenize(" ".join([(p.title + " ") * TITLE_REPEAT, p.description, TYPE_WORDS.get(p.activity_type, ""), p.extra_text]))
        for p in profiles
    ]
    idf, unseen = _idf(profile_tokens)
    doc_vec = _vector(doc_tokens, idf, unseen)

    matches: List[Match] = []
    for profile, tokens in zip(profiles, profile_tokens):
        prof_vec = _vector(tokens, idf, unseen)
        cosine = _cosine(doc_vec, prof_vec)
        text_value = min(1.0, cosine / COSINE_FULL_SCORE)

        title_set = set(tokenize(profile.title))
        title_hits = sorted(title_set & doc_set)
        title_value = len(title_hits) / len(title_set) if title_set else 0.0

        wanted = DOC_TYPE_TO_ACTIVITY_TYPES.get(document.doc_type or "", ())
        type_hit = profile.activity_type in wanted
        date_hits = sorted(d for d in document.dates if _in_window(d, profile))

        points = {
            "text similarity": round(100 * WEIGHTS["text"] * text_value, 2),
            "title words": round(100 * WEIGHTS["title"] * title_value, 2),
            "document type": round(100 * WEIGHTS["type"] * (1.0 if type_hit else 0.0), 2),
            "dates": round(100 * WEIGHTS["date"] * (1.0 if date_hits else 0.0), 2),
        }
        score = round(sum(points.values()), 2)

        shared = sorted(
            (t for t in set(doc_vec) & set(prof_vec)),
            key=lambda t: (-(doc_vec[t] * prof_vec[t]), t),
        )
        reasons = []
        if shared and points["text similarity"] > 0:
            reasons.append(f"The document and this activity share important words: {_words(shared, 5)}.")
        if title_hits:
            reasons.append(f"Words from the activity title appear in the document: {_words(title_hits)}.")
        if type_hit:
            reasons.append(
                f"The document was recognized as '{document.doc_type}', which usually belongs to a "
                f"{profile.activity_type.replace('_', ' ').title()} activity."
            )
        if date_hits:
            reasons.append(f"The document mentions {date_hits[0].isoformat()}, which falls within this activity's dates.")
        if not reasons:
            reasons.append("No clear similarity was found.")
        breakdown = " + ".join(f"{name} {value:.1f}" for name, value in points.items())
        explanation = f"Match score {score:.1f}/100 ({breakdown}). " + " ".join(reasons)
        matches.append(Match(profile.activity_id, score, explanation, points))

    matches.sort(key=lambda m: (-m.score, m.activity_id))
    if len(matches) > 1 and matches[0].score >= MIN_SUGGEST_SCORE and matches[0].score - matches[1].score < AMBIGUOUS_MARGIN:
        top = matches[0]
        matches[0] = Match(top.activity_id, top.score,
                           top.explanation + " Another activity scored almost the same, so please check carefully.",
                           top.points)
    return matches
