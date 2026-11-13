# Activity Matching and Suggestions

Code: `backend/app/services/activity_matching.py` (pure scoring), `services/suggestions.py` (database part),
`routers/suggestions.py` (confirm / reject). No AI service is used. The same input always gives the same result.

## 1. Purpose
When a document is uploaded without choosing an activity, Cogniflow suggests which of the user's own activities it
probably belongs to and explains why. **The document is never moved by the system.** The user confirms or rejects.

## 2. Score
```
Score (0-100) = 100 x ( 0.45 x TextSimilarity + 0.30 x TitleWords + 0.15 x TypeHint + 0.10 x DateRelevance )
```
| Signal | Weight | How it is calculated (each value is 0..1) |
|---|---|---|
| Text similarity | 0.45 | TF-IDF cosine similarity between the document text and the activity profile. The profile is the title (counted 3 times), description, a word for the activity type, and the text of documents, note titles and task titles already in that activity. A cosine of 0.35 or more counts as 1.0, because documents are much longer than activity profiles. |
| Title words | 0.30 | share of the activity title's meaningful words that occur in the document (plural forms are matched) |
| Document type hint | 0.15 | 1 if the kind of document found by the extraction rules usually belongs to the activity type: exam notice -> Exam, appointment -> Appointment, meeting -> Meeting, travel / booking -> Trip, project / academic -> Project |
| Date relevance | 0.10 | 1 if a date or deadline in the document falls inside the activity's dates (7 days of grace; an activity with only a start date or only a deadline uses a 90-day window) |

A suggestion is created only when the score is **30 or more**. At most 3 suggestions are kept, best first. Type hint and dates together
can give at most 25 points, so these weak signals alone can never create a suggestion. Labels: 60+ strong, 40+ moderate, otherwise weak.
Only open activities (not started, active, on hold) of the same user are compared. An activity the user rejected for a document is not suggested again for it.
If the two best scores are within 5 points, the explanation says so.

## 3. Explanation (example from the tests)
"Match score 90.0/100 (text similarity 45.0 + title words 30.0 + document type 15.0 + dates 0.0). The document and this activity share
important words: project, final, year, mca. Words from the activity title appear in the document: final, mca, project, year.
The document was recognized as 'Project / Academic', which usually belongs to a Project activity."

## 4. User flow
Upload -> processing -> suggestions stored as PENDING -> user **confirms** (document moves into the activity, other open suggestions removed)
or **rejects** (document stays unassigned; the user can choose an activity manually with `PATCH /documents/{id}`).
Generating, confirming and rejecting are written to the activity history (`SUGGESTION_GENERATED`, `SUGGESTION_CONFIRMED`,
`SUGGESTION_REJECTED`, `DOCUMENT_ASSIGNED`). Suggestions are recalculated when the text is corrected or when the user asks (`POST /documents/{id}/suggestions`).

## 5. Honest limits (state these in the report)
- The weights, the 0.35 cosine cap and the 30-point threshold are design judgements checked on a few hand-made examples. They are **not proven and not tuned on real data**.
- The score is a similarity score, not a probability. Very short or very generic documents can score 0 or be ambiguous.
- Word matching is literal: only simple plural forms are handled; synonyms ("holiday" / "trip") are not understood.
- A new activity with no description and no content has little to match on except its title.
- Suggestions are only as good as the text extraction; OCR errors reduce matching quality.

## 6. Testing
`tests/test_activity_matching.py`: 22 unit tests (realistic project, exam, trip and meeting documents, unrelated documents, each signal
separately, ties, ambiguity, determinism). `tests/test_suggestions_api.py`: 17 API tests (no silent move, confirm, reject, no repeat after
rejection, other users' activities never suggested, ownership).

## 7. Viva answers
- **Why not ask AI?** The matching must be explainable and work offline; every point of the score can be traced to a visible signal. AI could be added later as an optional helper.
- **Why confirm / reject?** A wrong automatic move could hide an important document, so the user always decides.
- **Is it accurate?** It works on the examples tested, but it has not been evaluated on a real dataset.
