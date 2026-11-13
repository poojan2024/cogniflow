"""Text cleaning: makes extracted/OCR text consistent before information extraction. Never adds content."""
from __future__ import annotations

import re
import unicodedata

MAX_TEXT_CHARS = 200_000  # stored text is capped so one huge document cannot bloat the database

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(raw: str | None) -> str:
    if not raw:
        return ""
    text = unicodedata.normalize("NFC", raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    text = text.replace("\t", " ").replace("\u00a0", " ")
    text = re.sub(r"(\w)-\n([a-z])", r"\1\2", text)  # re-join words split by a hyphen at the end of a line
    text = re.sub(r" {2,}", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MAX_TEXT_CHARS]
