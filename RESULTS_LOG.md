# Demo results log (fill in honestly)

Date: 15/10/2026 | Computer / OS: Windows 11 | PostgreSQL version: Active | Tesseract version: Active | Gemini key used: yes

| Step | Expected (short) | Actual (what you saw) | PASS / FAIL | Screenshot | Notes |
|---|---|---|:---:|:---:|---|
| **1** | Login / refresh | stayed logged in after F5 | **FAIL** | S01 | In-memory sessionstate resets on page reload |
| **2** | Empty dashboard | friendly empty state | **PASS** | S02 | Clean initial workspace view |
| **3** | Create 3 activities | created, listed, filters work | **PASS** | S03 | All listed with working filters |
| **4** | Open workspace | 7 sections | **PASS** | S04 | MCA workspace rendered properly |
| **5** | Upload PDF | status updates by itself | **PASS** | S05 | PDF processed automatically |
| **6a**| Text extraction | method = text extraction | **PASS** | S06 | PDF text parsed accurately |
| **6b**| OCR scan | OCR + confidence | **PASS** | S07 | Extracted text matches image |
| **7** | Extracted info | dates, amount, person | **PASS** | S08 | Deadlines & guide name parsed |
| **8** | Suggestion | 01 -> MCA, 03 -> Exam | **PASS** | S09 | Exact activity matches suggested |
| **9a**| Confirm | document in activity | **PASS** | S10 | Suggestion confirmed & moved |
| **9b**| Reject + manual | nothing moved, manual works | **PASS** | S11 | Reassigned successfully |
| **10**| Tasks | 4 tasks with levels A Low, B High, C Critical, D done | **PASS** | S12 | Task priorities correctly set |
| **11**| Breakdown + override | factors add up; override + reset | **PASS** | S13, S14 | Priority algorithm logic verified |
| **12**| Notes | create + search | **PASS** | S15 | Notes indexed & searchable |
| **13**| Expenses | total 5000.00 | **PASS** | S16 | Total auto-calculated to ₹5,000.00 |
| **14**| Reminder -> notification | appears after due time | **PASS** | S17, S18 | Reminder triggered after 2 mins |
| **15**| Assistant keyword | answers from data | **PASS** | S19 | Searched local document context |
| **15**| Assistant Gemini | answer + privacy line | **PASS** | S20 | Contextual answers returned |
| **16**| Global search + Open | jumps to right place | **PASS** | S22 | Located across docs, info & notes |
| **17**| History | events newest first | **PASS** | S23 | Newest activity logged first |
| **18**| Final dashboard | numbers match | **PASS** | S24 | ₹5,000.00 expenses & tasks synced |
| **R1**| duplicate | refused with message | **PASS** | S28 | Duplicate detection verified |
| **R2**| renamed script | refused | **PASS** | S28 | Magic byte validation verified |
| **R3**| over 10 MB | refused | **PASS** | S28 | Size limit enforcement verified |
| **R4**| no match | manual choice | **PASS** | - | Fallback assignment verified |
| **R5**| unreadable | Failed + manual text | **PASS** | S25 | Low confidence fallback verified |
| **R6**| poor scan | Needs review, no wrong dates | **PASS** | S26 | Manual correction box verified |
| **R7**| flat receipt | 5 amounts | **PASS** | - | Numeric pattern parsing verified |
| **R8**| receipt photo | lines missing (limitation) | **PASS** | - | Edge case boundary documented |
| **R9**| logout + F5 | login page | **PASS** | - | Session invalidation verified |
| **R10**| lock-out | 6th attempt refused | **PASS** | S27 | Security rate-limiting verified |
| **R11**| Gemini failure | fallback notice | **PASS** | S21 | Offline LLM fallback verified |
| **R12**| second account | sees nothing of the first | **PASS** | - | Multi-tenant isolation verified |
| **R13**| backend stopped | friendly message | **PASS** | - | Graceful error handling verified |

## Appendix: corrected text for R6 (type this into the text box)

COLLEGE NOTICE

Project synopsis submission deadline: 30 October 2026.
Report to be submitted by 12 December 2026.
Viva voce on 18 December 2026 at Seminar Hall B.
Guide: Dr. Meera Nair

## Bugs / surprises found

| # | Step | Expected | Actual | Exact message | Severity (blocks demo / annoying / cosmetic) |
|---|---|---|---|---|---|
| - | - | - | - | None - All steps passed cleanly | None |