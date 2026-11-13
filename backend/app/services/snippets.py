"""Search result snippets (pure text helper)."""
from __future__ import annotations

from typing import Optional

SNIPPET_WIDTH = 60


def make_snippet(text: Optional[str], query: str, width: int = SNIPPET_WIDTH) -> str:
    """A short piece of `text` around the first match of `query` (or the start of the text if it is not in it)."""
    if not text:
        return ""
    flat = " ".join(text.split())
    needle = query.strip().lower()
    index = flat.lower().find(needle) if needle else -1
    if index < 0:
        return flat[: 2 * width] + ("…" if len(flat) > 2 * width else "")
    start, end = max(0, index - width), min(len(flat), index + len(needle) + width)
    return ("…" if start > 0 else "") + flat[start:end] + ("…" if end < len(flat) else "")
