"""Upload validation. Never trusts the filename or the browser's Content-Type: the file CONTENT decides.

Allowed: PDF, PNG, JPEG, plain text. Everything else is rejected.
"""
from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass


class UploadRejected(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ValidatedUpload:
    display_name: str  # sanitized original name, for display and download only (never used as a path)
    extension: str  # ".pdf", ".png", ".jpg", ".txt"
    kind: str  # "pdf" | "image" | "txt"
    mime_type: str


# extension -> (kind, mime type)
ALLOWED = {
    ".pdf": ("pdf", "application/pdf"),
    ".png": ("image", "image/png"),
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".txt": ("txt", "text/plain"),
}
MAX_IMAGE_PIXELS = 50_000_000  # protects against decompression bombs


def sanitize_filename(name: str | None) -> str:
    """Keep only the final path component, drop control characters, limit the length."""
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".")
    return name[:200] or "document"


def _sniff(data: bytes) -> str | None:
    """Detect the real file type from its first bytes."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    return None


def validate_upload(filename: str | None, data: bytes) -> ValidatedUpload:
    display = sanitize_filename(filename)
    ext = os.path.splitext(display)[1].lower()

    if ext not in ALLOWED:
        raise UploadRejected("Unsupported file type. Allowed types: PDF, PNG, JPG/JPEG and TXT.", 415)
    if len(data) == 0:
        raise UploadRejected("The file is empty.")

    kind, mime = ALLOWED[ext]
    detected = _sniff(data)

    if kind == "txt":
        if detected is not None or b"\x00" in data[:4096]:
            raise UploadRejected("The file content does not match its .txt extension.")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise UploadRejected("Text files must be UTF-8 encoded.")
    else:
        expected = "pdf" if kind == "pdf" else ("png" if ext == ".png" else "jpeg")
        if detected != expected:
            raise UploadRejected(f"The file content does not match its {ext} extension.")
        if kind == "image":
            _check_image(data)

    return ValidatedUpload(display_name=display, extension=".jpg" if ext == ".jpeg" else ext, kind=kind, mime_type=mime)


def _check_image(data: bytes) -> None:
    """Make sure Pillow can open the image and that it is not absurdly large."""
    try:
        from PIL import Image
    except ImportError:  # Pillow missing: OCR will report it; the upload itself is still allowed
        return
    try:
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            if width * height > MAX_IMAGE_PIXELS:
                raise UploadRejected("The image dimensions are too large.")
            img.verify()
    except UploadRejected:
        raise
    except Exception:
        raise UploadRejected("The image file is corrupted or cannot be read.")
