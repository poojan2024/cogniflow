"""Application settings, loaded from environment variables / .env.

The app refuses to start with a missing, short or placeholder JWT secret,
so an insecure configuration cannot be run by accident.
"""
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# backend/.env, found relative to this file (not the current working directory).
# Real environment variables still take priority over the file, which is how the tests override DATABASE_URL.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore")

    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    cors_origins: str = "http://localhost:8501"

    # Login rate limiting (see app/services/login_throttle.py): after this many failed logins for the same
    # email from the same IP within the window, further attempts are refused until the window has passed.
    login_max_failures: int = 5
    login_window_minutes: int = 15

    # Document pipeline (all optional)
    upload_dir: str = ""  # empty = backend/uploads
    max_upload_mb: int = 10
    tesseract_cmd: str = ""  # full path to tesseract(.exe) if it is not on PATH
    ocr_language: str = "eng"
    ocr_max_pdf_pages: int = 10
    ocr_min_confidence: float = 60.0

    # AI assistant (Google Gemini). Optional: without a key the assistant answers in keyword mode.
    gemini_api_key: SecretStr = SecretStr("")  # SecretStr keeps the key out of logs and repr()
    gemini_model: str = "gemini-2.5-flash"
    ai_timeout_seconds: int = 30
    ai_context_max_chars: int = 24000  # upper limit of the activity text sent to Gemini with one question
    ai_max_questions_per_hour: int = 30  # per user; protects the API key from runaway use

    @field_validator("jwt_secret")
    @classmethod
    def jwt_secret_must_be_strong(cls, v: str) -> str:
        if len(v) < 32 or v.lower().startswith("change_me"):
            raise ValueError(
                "JWT_SECRET must be a random value of at least 32 characters "
                "(see .env.example for how to generate one)."
            )
        return v

    @field_validator("access_token_expire_minutes")
    @classmethod
    def expiry_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be positive.")
        return v

    @field_validator("login_max_failures", "login_window_minutes")
    @classmethod
    def login_limits_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("LOGIN_MAX_FAILURES and LOGIN_WINDOW_MINUTES must be positive.")
        return v

    @property
    def upload_path(self) -> Path:
        """Folder where uploaded files are stored (outside any web-served folder)."""
        return Path(self.upload_dir).resolve() if self.upload_dir else _ENV_FILE.parent / "uploads"

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
