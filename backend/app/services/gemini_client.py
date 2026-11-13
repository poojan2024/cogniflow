"""Minimal client for Google's Gemini REST API (generateContent), standard library only.

Safety rules:
  * the API key is sent in the `x-goog-api-key` header only: never in the URL, never in a log line, never in an error;
  * every failure becomes an AIError with a short, user-safe message (no response bodies, no stack traces);
  * one quick retry for temporary server errors (5xx); nothing else is retried, so a request never hangs for long.

The rest of Cogniflow depends only on `AIError` and on any object with `generate(system_prompt, user_prompt) -> str`,
so tests use fakes and never contact Google.
"""
from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.request
from typing import Callable, Optional
from urllib.parse import quote

logger = logging.getLogger("cogniflow")

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
MAX_RESPONSE_BYTES = 1_000_000
BLOCKED_FINISH_REASONS = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY"}

USER_MESSAGES = {
    "not_configured": "The AI assistant is not configured (no Gemini API key is set on the server).",
    "auth": "Gemini rejected the request. Please check that GEMINI_API_KEY on the server is a valid key.",
    "config": "Gemini could not accept the request. Please check the GEMINI_MODEL setting on the server.",
    "rate_limit": "Gemini is limiting requests right now. Please try again in a minute.",
    "network": "Gemini could not be reached (network problem or timeout).",
    "server": "Gemini had a temporary problem. Please try again later.",
    "blocked": "Gemini declined to answer this question.",
    "bad_response": "Gemini returned an answer that could not be read.",
}
# These two mean "Gemini answered, but not usefully" (stored as FAILED); everything else is "unavailable".
FAILED_KINDS = {"blocked", "bad_response"}


class AIError(Exception):
    """An AI problem with a user-safe message. Never contains the API key or the provider's response."""

    def __init__(self, kind: str):
        self.kind = kind if kind in USER_MESSAGES else "bad_response"
        self.user_message = USER_MESSAGES[self.kind]
        super().__init__(self.kind)

    @property
    def db_status(self) -> str:
        return "FAILED" if self.kind in FAILED_KINDS else "UNAVAILABLE"


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        timeout: float = 30.0,
        base_url: str = DEFAULT_BASE_URL,
        retries: int = 1,
        backoff: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._api_key = api_key
        self.model = model
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self.retries = retries
        self.backoff = backoff
        self._sleep = sleep

    def __repr__(self) -> str:  # never show the key
        return f"GeminiClient(model={self.model!r})"

    # ------------------------------------------------------------------ public
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        if not self._api_key:
            raise AIError("not_configured")
        url = f"{self.base_url}/v1beta/models/{quote(self.model, safe='')}:generateContent"
        body = json.dumps({
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
        }).encode("utf-8")
        request = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": self._api_key},
        )

        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = response.read(MAX_RESPONSE_BYTES)
                return self._parse(payload)
            except urllib.error.HTTPError as exc:
                kind = self._kind_for_http_error(exc)
                logger.warning("Gemini request failed: HTTP %s (%s)", exc.code, kind)
                if kind == "server" and attempt < self.retries:
                    self._sleep(self.backoff)
                    continue
                raise AIError(kind) from None
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError):
                logger.warning("Gemini request failed: network problem or timeout")
                raise AIError("network") from None
        raise AIError("server")  # not reachable, kept for completeness

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _kind_for_http_error(exc: urllib.error.HTTPError) -> str:
        code = exc.code
        if code in (401, 403):
            return "auth"
        if code == 429:
            return "rate_limit"
        if code == 408:
            return "network"
        if code >= 500:
            return "server"
        if code == 400:
            try:
                text = exc.read(65536).decode("utf-8", "replace").lower()
            except Exception:
                text = ""
            # Google answers an invalid key with 400 "API key not valid"
            invalid_key = "api_key_invalid" in text or "api key not valid" in text or ("api key" in text and "valid" in text)
            return "auth" if invalid_key else "config"
        return "config"  # 404 (unknown model) and anything else unexpected

    @staticmethod
    def _parse(payload: bytes) -> str:
        try:
            data = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise AIError("bad_response") from None
        if not isinstance(data, dict):
            raise AIError("bad_response")

        candidates = data.get("candidates") or []
        if not candidates:
            if (data.get("promptFeedback") or {}).get("blockReason"):
                raise AIError("blocked")
            raise AIError("bad_response")

        candidate = candidates[0] if isinstance(candidates[0], dict) else {}
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
        if text:
            return text
        if candidate.get("finishReason") in BLOCKED_FINISH_REASONS:
            raise AIError("blocked")
        raise AIError("bad_response")


def build_client(api_key: Optional[str], model: str, timeout: float) -> Optional[GeminiClient]:
    """None when no usable key is configured (empty or an obvious placeholder)."""
    key = (api_key or "").strip()
    if not key or key.lower().startswith(("your", "change_me", "paste", "xxx")):
        return None
    return GeminiClient(key, model=model, timeout=timeout)
