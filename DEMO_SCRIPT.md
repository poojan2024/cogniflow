# Cogniflow demo script (about 60 minutes)

Purpose: run the whole system once on YOUR machine, write down what really happens, and collect the screenshots for the
report. Expected values below were pre-checked by running your backend functions on the sample files (Tesseract 5.3.4 on
Linux). **Your numbers can differ slightly** (OCR confidence especially); a different *outcome* (for example a refused file that
should be accepted) is what to report. Fill in `RESULTS_LOG.md` as you go. Never write a result you did not see.

## 0. Before you start (10 minutes)

| Check | How | Expected |
|---|---|---|
| PostgreSQL running, `backend/.env` set | `DATABASE_URL`, `JWT_SECRET` (32+ chars) | no placeholder values left |
| Tables exist | from `backend/`: `python -m scripts.init_db` | tables created / already exist |
| Tesseract installed | `tesseract --version` | prints a version (if not: OCR steps will show the "install Tesseract" message, which is also worth a screenshot) |
| Backend | from `backend/`: `uvicorn app.main:app --reload` | http://127.0.0.1:8000/health/db shows `"database":"postgresql"` |
| Frontend | from `frontend/`: `pip install -r requirements.txt`, then `streamlit run app.py` | login page at http://localhost:8501 |
| Gemini (optional) | `GEMINI_API_KEY` in `backend/.env`, restart backend | Assistant page says Gemini is set up. Skip if you have no key. |
| Clean data | register a NEW account, e.g. `demo@example.com` | empty dashboard |

Use a normal (not private) browser window. Take screenshots with Win+Shift+S; name them as in section 5.

## 1. Demo data

Create these three activities (Activities page, "New activity"):

| Title | Type | Status | Priority | Start | Deadline | Description |
|---|---|---|---|---|---|---|
| MCA Final-Year Project | Project | Active | 4 | 01/07/2026 | 15/12/2026 | Cogniflow - AI-assisted personal digital organizer. MCA final year major project report and viva. |
| Goa Trip | Trip | Active | 3 | 20/12/2026 | 27/12/2026 | Family holiday in Goa: hotel, travel and food. |
| Semester Exam | Exam | Active | 3 | 10/11/2026 | 25/11/2026 | MCA semester examinations and preparation. |

## 2. The 18-step demo flow

Do **step 14a right after step 4** (a reminder needs a few minutes to become due).

| # | Step | What to do | Expected result |
|---|---|---|---|
| 1 | Login | Try a wrong password once, then log in. Press F5. | Wrong password: clear message, no crash. After F5 you are still logged in. |
| 2 | Dashboard | Open it while empty. | Zeros and a friendly "No activities yet" box. |
| 3 | Create activity | Create the 3 activities above. | "Activity created." each time; they appear in the list; filters/search work. |
| 4 | Workspace | Activities → "Open workspace" on MCA Final-Year Project. | Header with type, status, priority, dates; sections Tasks, Documents, Notes, Expenses, Reminders, Assistant, History. |
| 14a | Reminder (early) | Reminders → add "Submit synopsis" for **2 minutes from now**, link no task. | "Reminder added." listed under Scheduled. |
| 5 | Upload a document | **Documents** page (sidebar). Upload `01_project_guidelines.pdf`, leave "Let Cogniflow suggest an activity". | Details open by themselves; status Queued → Processing → Processed without you pressing anything. |
| 6a | Text extraction | Look at the details. | "Text extraction (the file contains real text)". |
| 6b | OCR | Upload `03_exam_timetable_scan.png`. | "OCR (scanned page or image) · engine confidence ≈ 90+" and the extracted text matches the picture. Compare with the preview (Prepare download shows the image). |
| 7 | Extracted information | Open each document's details. | 01: Document type Project / Academic, Deadlines 30 Oct and 12 Dec 2026, Date 18 Dec 2026, Person Dr. Meera Nair. 03: Exam notice, Deadline 5 Nov, Dates 12/16/20 Nov, Amount INR 1250, Location. |
| 8 | Activity suggestion | Look at the suggestion card of each. | 01 → MCA Final-Year Project (≈100, strong). 03 → Semester Exam (≈69, strong). The "Why was this suggested?" box lists the reasons. Scores are similarity, not probability. |
| 9a | Confirm | Press **Confirm** on 01. | Document moves into MCA Final-Year Project (also visible in that workspace's Documents section). |
| 9b | Reject | Upload `06_meeting_notice.txt` (suggested MCA Project, ≈48 moderate). Press **Reject**. | The message says nothing was moved and the document is still not in any activity. Then pick MCA Final-Year Project yourself in "Choose an activity yourself" and press "Add to this activity". |
| 10 | Tasks | MCA workspace → Tasks. Add the four tasks in section 3. | Each has a calculated priority level and score. |
| 11 | Weighted score | Open "Score breakdown & manual override" on each task; then set an override on the LOW task to High; then "Reset to calculated". | Four weighted factors with bars and points that add up to the total. Override shows "set manually" and keeps the calculated score visible; reset restores it. |
| 12 | Notes | Notes → add "Viva questions", search for "viva". | Note appears; search finds it. |
| 13 | Expense | Goa Trip workspace → Expenses: Hotel ₹3,000 (Accommodation), Transport ₹1,200 (Transport), Food ₹800 (Food). | Total **₹5,000.00**, category chart, edit and delete (with confirmation) work. |
| 14b | Reminder fires | Open **Notifications** after the 2 minutes. | "Reminder: Submit synopsis" appears as new. Mark as read; mark all; delete. |
| 15 | Assistant | MCA workspace → Assistant. First choose "Keyword search only", ask: *What documents have I uploaded?*, *What is the deadline?* If you have a key: switch to Gemini and ask *Summarize the important information from the uploaded documents.* | Keyword mode answers from your data and says "no AI". Gemini mode shows the privacy line, references, and the "Show exactly what data would be used" box matches. |
| 16 | Global search | Search page: "viva", "Meera", "hotel", then untick some places. Press **Open** on a task and a document result. | Results grouped by type; Open jumps to the right section/document. |
| 17 | History | MCA workspace → History. | Newest first: activity created, document assigned, suggestion confirmed, tasks created, reminder created, … |
| 18 | Dashboard | Open Dashboard. | Counts, deadlines, high-priority tasks with explanation, charts, recent documents/activity/reminders, expense total ₹5,000.00. |

## 3. The four priority tasks (in MCA Final-Year Project, activity priority 4)

Due dates are **relative to the day you run the demo**. Expected values were computed with your real algorithm.

| Task title | Due | Importance | Expected score | Expected level |
|---|---|---|---|---|
| A. Collect references | today + 30 days | 1 | 18.75 | Low |
| B. Write chapter 3 | today + 7 days | 4 | 61.25 | High |
| C. Fix database bug | today − 2 days (overdue) | 5 | 96.25 | Critical |
| D. Submit synopsis | today − 2 days, then press **Mark complete** | 5 | not active | Completed, no longer an open priority |
| (extra) E. Final review | today + 3 days | 5 | 80.18 | Critical |

Say in the viva: a task due in 3 days with top importance is already Critical, because the deadline factor carries the
largest weight (40%) and the Critical threshold is 80. These weights are design choices, not scientifically proven.
Also true and worth knowing: an overdue task with the lowest importance in a low-priority activity can still score only Medium.

## 4. Robustness checks (about 15 minutes) - these matter for the report

| # | Do this | Expected |
|---|---|---|
| R1 | Upload `01_project_guidelines.pdf` a second time | "This file was already uploaded (document #…)" (duplicate detection) |
| R2 | Upload `08_renamed_script.pdf` (a script renamed to .pdf) | Refused: "The file content does not match its .pdf extension." (content is checked, not the name) |
| R3 | Upload `09_too_large_over_10MB.txt` | Refused before upload: "larger than 10 MB" |
| R4 | Upload `07_random_recipe.txt` | Processed; "No matching activity was found"; you choose an activity yourself |
| R5 | Upload `05_unreadable_blur.png` | **Failed** with "No readable text could be found…"; the text box is open: type text, Save → items and suggestion appear |
| R6 | Upload `05b_poor_scan.png` | **Needs review**, confidence ≈ 37, garbled text, **no wrong dates created**. Replace the text with the corrected version in `RESULTS_LOG.md` appendix, Save → deadlines 30 Oct / 12 Dec appear, suggestion MCA Final-Year Project (≈51, moderate) |
| R7 | Upload `04b_receipt_flat_scan.png` | OCR ≈ 93, five amounts extracted, total INR 842.50 |
| R8 | Upload `04_receipt_photo.jpg` | **Known limitation to show honestly:** the OCR confidence is high (≈95) but several lines (all prices and TOTAL) are missing from the text. Confidence only measures the words that were read, not the lines that were missed. Fix it by editing the text. |
| R9 | Log out, press F5 | Login page (you are really logged out) |
| R10 | Wrong password 5 times, then the right one | 6th attempt: "Too many failed login attempts. Please wait N minutes…" even with the right password |
| R11 | (If Gemini key) put a wrong key in `.env`, restart backend, ask a question in Gemini mode | A clear notice that Gemini is unavailable and a keyword answer instead; the rest of the app keeps working |
| R12 | Register a second account, log in as it | It sees none of the first account's activities, documents, tasks, notes… |
| R13 | Stop the backend, click around | Friendly "Cannot reach the Cogniflow server" messages, no crash or stack trace |

## 5. Screenshots for Chapter 13 (Results)

S01 login · S02 empty dashboard · S03 activities list · S04 workspace header · S05 upload + processing status ·
S06 text-extraction details · S07 OCR details with confidence · S08 extracted information · S09 suggestion card with reasons ·
S10 after Confirm · S11 after Reject + manual choice · S12 tasks list with levels · S13 score breakdown · S14 manual override ·
S15 notes + search · S16 expenses with total · S17 reminder scheduled · S18 notification · S19 assistant keyword answer ·
S20 assistant Gemini answer + privacy line (if key) · S21 assistant fallback notice · S22 global search · S23 history ·
S24 final dashboard · S25 OCR failed + manual text · S26 Needs review · S27 lock-out message · S28 duplicate/refused uploads.

## 6. What to send me afterwards

1. The filled `RESULTS_LOG.md` (even if everything passed).
2. For every FAIL or surprise: the step number, what you expected, what you saw (exact message), and a screenshot.
3. The terminal output of the backend around the time of a failure (copy the last ~20 lines; make sure no password or key is in it).
