"""Text extraction for the document pipeline.

  text file          -> read as text                       (method TEXT)
  PDF with real text -> pypdf extraction                    (method TEXT)
  scanned PDF        -> render pages to images, then OCR   (method OCR)
  image              -> OCR with Tesseract                  (method OCR)

Rules: nothing is ever invented. If extraction or OCR fails, the result says so with a user-safe message.
Low-confidence OCR is marked NEEDS_REVIEW so the user checks and corrects it instead of trusting it silently.
OCR libraries are imported lazily, so the rest of Cogniflow keeps working even if they are not installed.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("cogniflow")

WINDOWS_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
MIN_TEXT_CHARS_PER_PAGE = 25  # fewer characters per page than this => treat the PDF as scanned
MIN_OCR_WORDS = 3
MAX_IMAGE_SIDE = 4000  # larger images are scaled down to keep OCR fast
OCR_TIMEOUT_SECONDS = 60
PDF_RENDER_DPI = 200


class OcrUnavailableError(Exception):
    """The OCR engine (Tesseract) or a needed library is not installed."""


class OcrError(Exception):
    """OCR ran but failed (timeout, bad language data, unreadable image)."""


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    method: str  # "TEXT" | "OCR" | "NONE"
    ocr_confidence: Optional[float]  # 0..100 from the OCR engine, None when no OCR was used
    status: str  # "PROCESSED" | "NEEDS_REVIEW" | "FAILED"
    message: Optional[str] = None  # user-safe explanation for NEEDS_REVIEW / FAILED


MSG_NO_TESSERACT = (
    "The OCR engine (Tesseract) is not installed or was not found on the server. "
    "Install Tesseract, or set TESSERACT_CMD in backend/.env, then use Reprocess."
)
MSG_NO_TEXT = "No readable text could be found in this document. You can type the text in manually."


# ---------------------------------------------------------------- OCR engine
def find_tesseract(configured: str = "") -> Optional[str]:
    if configured and Path(configured).is_file():
        return configured
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    if os.name == "nt" and Path(WINDOWS_TESSERACT).is_file():
        return WINDOWS_TESSERACT
    return None


def tesseract_available(configured: str = "") -> bool:
    return find_tesseract(configured) is not None


def ocr_image(img, lang: str = "eng", tesseract_cmd: str = "") -> Tuple[str, float, int]:
    """OCR one PIL image. Returns (text, mean word confidence 0..100, word count)."""
    try:
        import pytesseract
        from PIL import ImageOps
    except ImportError as exc:
        raise OcrUnavailableError("OCR libraries are not installed") from exc

    cmd = find_tesseract(tesseract_cmd)
    if cmd is None:
        raise OcrUnavailableError("Tesseract not found")
    pytesseract.pytesseract.tesseract_cmd = cmd

    img = ImageOps.exif_transpose(img)  # phone photos may be rotated through EXIF metadata
    img = ImageOps.autocontrast(img.convert("L"))
    longest = max(img.size)
    if longest > MAX_IMAGE_SIDE:
        scale = MAX_IMAGE_SIDE / longest
        img = img.resize((int(img.width * scale), int(img.height * scale)))

    try:
        data = pytesseract.image_to_data(
            img, lang=lang, output_type=pytesseract.Output.DICT, timeout=OCR_TIMEOUT_SECONDS
        )
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrUnavailableError("Tesseract not found") from exc
    except RuntimeError as exc:  # pytesseract raises RuntimeError on timeout
        raise OcrError("OCR took too long and was stopped.") from exc
    except pytesseract.TesseractError as exc:
        raise OcrError("The OCR engine could not process this image.") from exc

    lines: List[List[str]] = []
    paragraph_breaks: List[bool] = []
    confidences: List[float] = []
    last_key = None
    last_paragraph = None
    for i, raw_word in enumerate(data["text"]):
        word = (raw_word or "").strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            continue
        if not word or conf < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        if key != last_key:
            paragraph = (data["block_num"][i], data["par_num"][i])
            paragraph_breaks.append(last_paragraph is not None and paragraph != last_paragraph)
            lines.append([])
            last_key, last_paragraph = key, paragraph
        lines[-1].append(word)
        confidences.append(conf)

    text = ""
    for words, new_paragraph in zip(lines, paragraph_breaks):
        text += ("\n\n" if new_paragraph else ("\n" if text else "")) + " ".join(words)
    mean_conf = round(sum(confidences) / len(confidences), 1) if confidences else 0.0
    return text, mean_conf, len(confidences)


def _ocr_outcome(text: str, confidence: float, words: int, min_confidence: float) -> ExtractionResult:
    if not text.strip() or words < MIN_OCR_WORDS:
        return ExtractionResult("", "OCR", confidence if words else None, "FAILED", MSG_NO_TEXT)
    if confidence < min_confidence:
        return ExtractionResult(
            text, "OCR", confidence, "NEEDS_REVIEW",
            f"The text was read with low confidence ({confidence:.0f}%). Please check it and correct any mistakes.",
        )
    return ExtractionResult(text, "OCR", confidence, "PROCESSED")


# ------------------------------------------------------------------- PDF
def _render_pdf_pages(path: Path, max_pages: int, dpi: int = PDF_RENDER_DPI):
    """Render PDF pages to PIL images with pypdfium2. Kept separate so tests can replace it."""
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise OcrUnavailableError("pypdfium2 is not installed") from exc
    pdf = pdfium.PdfDocument(str(path))
    try:
        total = len(pdf)
        images = [pdf[i].render(scale=dpi / 72).to_pil() for i in range(min(total, max_pages))]
    finally:
        pdf.close()
    return images, total


def _extract_pdf(path: Path, lang: str, max_pages: int, min_confidence: float, tesseract_cmd: str) -> ExtractionResult:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ExtractionResult("", "NONE", None, "FAILED", "PDF support (pypdf) is not installed on the server.")

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            return ExtractionResult("", "NONE", None, "FAILED", "The PDF is password-protected and cannot be read.")
        page_count = len(reader.pages)
        embedded = "\n\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        logger.exception("PDF read failed")
        return ExtractionResult("", "NONE", None, "FAILED", "The PDF could not be read. It may be corrupted.")

    meaningful = len(re.sub(r"\s+", "", embedded))
    if page_count and meaningful >= MIN_TEXT_CHARS_PER_PAGE * page_count:
        return ExtractionResult(embedded, "TEXT", None, "PROCESSED")  # real text: no OCR needed

    # Little or no embedded text: this looks like a scanned document, so use OCR.
    partial_note = "Only part of the text could be read automatically. Please check it."
    try:
        images, total_pages = _render_pdf_pages(path, max_pages)
        texts, weighted_conf, words_total = [], 0.0, 0
        for image in images:
            text, conf, words = ocr_image(image, lang, tesseract_cmd)
            if text.strip():
                texts.append(text)
            weighted_conf += conf * words
            words_total += words
        text = "\n\n".join(texts)
        confidence = round(weighted_conf / words_total, 1) if words_total else 0.0
        result = _ocr_outcome(text, confidence, words_total, min_confidence)
        if total_pages > max_pages and result.status != "FAILED":
            note = f"Only the first {max_pages} of {total_pages} pages were read."
            return ExtractionResult(result.text, "OCR", result.ocr_confidence, "NEEDS_REVIEW", note)
        return result
    except OcrUnavailableError:
        if meaningful:
            return ExtractionResult(embedded, "TEXT", None, "NEEDS_REVIEW", partial_note)
        return ExtractionResult("", "NONE", None, "FAILED", MSG_NO_TESSERACT)
    except OcrError as exc:
        if meaningful:
            return ExtractionResult(embedded, "TEXT", None, "NEEDS_REVIEW", partial_note)
        return ExtractionResult("", "NONE", None, "FAILED", str(exc))
    except Exception:
        logger.exception("Scanned PDF processing failed")
        if meaningful:
            return ExtractionResult(embedded, "TEXT", None, "NEEDS_REVIEW", partial_note)
        return ExtractionResult("", "NONE", None, "FAILED", "The scanned PDF could not be processed.")


# ---------------------------------------------------------------- entry point
def extract_text(
    path: Path,
    kind: str,
    *,
    ocr_lang: str = "eng",
    max_pdf_pages: int = 10,
    min_confidence: float = 60.0,
    tesseract_cmd: str = "",
) -> ExtractionResult:
    """kind is "txt", "pdf" or "image" (see file_validation)."""
    try:
        if kind == "txt":
            text = Path(path).read_bytes().decode("utf-8", errors="replace")
            if not text.strip():
                return ExtractionResult("", "NONE", None, "FAILED", "The text file is empty.")
            return ExtractionResult(text, "TEXT", None, "PROCESSED")

        if kind == "pdf":
            return _extract_pdf(Path(path), ocr_lang, max_pdf_pages, min_confidence, tesseract_cmd)

        if kind == "image":
            try:
                from PIL import Image
            except ImportError:
                return ExtractionResult("", "NONE", None, "FAILED", MSG_NO_TESSERACT)
            with Image.open(path) as img:
                img.load()
                text, conf, words = ocr_image(img, ocr_lang, tesseract_cmd)
            return _ocr_outcome(text, conf, words, min_confidence)

        return ExtractionResult("", "NONE", None, "FAILED", "Unsupported document type.")
    except OcrUnavailableError:
        return ExtractionResult("", "NONE", None, "FAILED", MSG_NO_TESSERACT)
    except OcrError as exc:
        return ExtractionResult("", "NONE", None, "FAILED", str(exc))
    except Exception:
        logger.exception("Text extraction failed")
        return ExtractionResult("", "NONE", None, "FAILED", "The file could not be read.")
