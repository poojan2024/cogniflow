# Document Intelligence Pipeline

Code: `backend/app/services/` (`file_validation`, `storage`, `text_extraction`, `text_cleaning`, `info_extraction`,
`document_pipeline`) and `backend/app/routers/documents.py`. No AI service is used anywhere in this pipeline.

## 1. Flow (what is implemented)
```
Upload -> File validation -> Secure storage -> [background task]
       -> Text extraction (text file / text PDF)  OR  OCR (image / scanned PDF)
       -> Text cleaning -> Rule-based information extraction -> Store result + status
       -> Activity matching -> Suggestion -> user Confirm / Reject   (see activity_matching.md)
```
Processing runs in a background task, so the upload returns at once with status `UPLOADED`. The client polls
`GET /documents/{id}` until the status is `PROCESSED`, `NEEDS_REVIEW` or `FAILED`.

## 2. Stages
| Stage | What it does |
|---|---|
| Validation | Allowed: PDF, PNG, JPG/JPEG, TXT. The extension and the real file content (magic bytes) must agree; images must open and be under 50 million pixels; maximum size 10 MB (`MAX_UPLOAD_MB`); the same file (SHA-256) is never stored or processed twice per user. |
| Storage | Random server-chosen file name, one folder per user, path checked to stay inside the upload folder, never served directly. Files are only returned by the authenticated `/documents/{id}/download` endpoint after an ownership check. |
| Type detection | Text file: read directly. PDF: pypdf; if it yields fewer than 25 characters per page it is treated as scanned. Image: OCR. |
| OCR | Tesseract via pytesseract. Scanned PDF pages are rendered with pypdfium2 (first 10 pages). The mean word confidence from the OCR engine is stored. Below 60% the document is `NEEDS_REVIEW`; no text or too few words is `FAILED`. |
| Cleaning | Unicode normalization, control characters removed, whitespace collapsed, words split by a hyphen at a line end re-joined. |
| Extraction | Rules only: dates (day-first), deadlines (a date after words such as "last date" or "submit by"), amounts with currency, document type (needs at least 2 keyword hits), names and locations from simple patterns, repeated keywords. Each item stores the source line so the user can check it. |

## 3. When things go wrong
Nothing is invented. No Tesseract, an unreadable image, a corrupted or password-protected PDF, or an empty result all
give status `FAILED` with a plain message. Low-confidence OCR gives `NEEDS_REVIEW`. The user can then:
correct or type the text (`PATCH /documents/{id}/text`, items are extracted again), delete a wrong extracted item,
or run `POST /documents/{id}/reprocess` (only for FAILED / NEEDS_REVIEW documents).

## 4. How uploaded documents are protected
Authentication on every endpoint; ownership checked on every document operation (another user's document returns 404);
content-based validation; random file names; per-user folders; path-traversal check; size limit; no direct file serving;
no stack traces in errors. **Documents are not sent to any external service in this phase.** When the AI assistant is
added, this section must state exactly which text is sent to the AI provider.

## 5. Limitations (state these in the report)
- Dates such as 03/04/2026 are read day-first; the user must check ambiguous ones.
- Names and locations come from simple patterns and will miss many; keyword and document-type rules are simple word lists.
- OCR quality depends on the scan; handwriting and low-resolution photos are unreliable. Only English is configured by default.
- Only the first 10 pages of a scanned PDF are read. Password-protected PDFs are rejected.
- Files are stored on local disk and are not encrypted at rest.

## 6. Tests
`tests/test_document_pipeline.py` (28 tests: validation, cleaning, every extraction rule, text and OCR extraction,
scanned-PDF routing, honest failure paths) and `tests/test_documents_api.py` (API behaviour and ownership).
Results are recorded in the progress report only after they are actually run.

## 7. Viva answers
- **OCR vs text extraction?** A text PDF already contains the characters, so they are read directly (fast, exact). A scan or photo is only pixels, so OCR has to recognize the letters and can make mistakes. That is why OCR results carry a confidence value and can be corrected.
- **What if OCR fails or is poor?** The user is told, nothing is made up, and the text can be corrected manually or processed again.
- **Why not send documents to AI?** Rules are deterministic, work offline and keep personal documents on the server. AI can later help with harder extraction, but only as an optional extra.
