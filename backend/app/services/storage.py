"""File storage on local disk.

Security:
  * files are stored under a random name (uuid) chosen by the server; the user's filename is never a path;
  * each user gets their own sub-folder;
  * every resolved path is checked to stay inside the upload folder (path-traversal protection);
  * the upload folder is not served by the web server; files are only reachable through the authenticated
    /documents/{id}/download endpoint, which checks ownership first.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional

from app.core.config import get_settings

logger = logging.getLogger("cogniflow")


def new_stored_filename(extension: str) -> str:
    return f"{uuid.uuid4().hex}{extension}"


def path_for(user_id: int, stored_filename: str) -> Path:
    base = get_settings().upload_path.resolve()
    path = (base / str(user_id) / stored_filename).resolve()
    if base != path and base not in path.parents:  # would escape the upload folder
        raise ValueError("Invalid storage path")
    return path


def save(user_id: int, stored_filename: str, data: bytes) -> Path:
    path = path_for(user_id, stored_filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def delete(user_id: int, stored_filename: str) -> None:
    """Best-effort removal; a missing file is not an error."""
    try:
        path_for(user_id, stored_filename).unlink(missing_ok=True)
    except Exception:
        logger.exception("Could not delete stored file %s", stored_filename)


def exists(user_id: int, stored_filename: str) -> bool:
    try:
        return path_for(user_id, stored_filename).is_file()
    except ValueError:
        return False


def find(user_id: int, stored_filename: str) -> Optional[Path]:
    return path_for(user_id, stored_filename) if exists(user_id, stored_filename) else None
