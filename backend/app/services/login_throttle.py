"""Limits repeated failed logins (pure Python: no framework, no database, so it is unit-tested directly).

Rule (sliding window): when the same email, from the same IP address, has failed to log in `max_failures` times within the
last `window_seconds`, further attempts are refused until the oldest of those failures is older than the window.
A successful login clears the count.

Why the key is "email + IP" and not just the email: if only the email counted, a stranger could lock a real user out of
their own account by failing on purpose. With the IP in the key, only the attacker's own address gets blocked.
Unknown emails are counted exactly like known ones, so the limiter cannot be used to find out which emails are registered.

Known limits (state them in the report; they are design trade-offs, not bugs):
  * the counters live in this process's memory: they reset when the server restarts and are not shared between several
    server processes. One uvicorn process (the way Cogniflow is run) is fully covered.
  * the IP is the address the server sees. Behind a reverse proxy that would be the proxy's address, so a proxy-aware
    setup would need to read a trusted forwarded-for header (not implemented, because it is easy to get wrong).
  * a determined attacker with many IP addresses is not stopped by this alone; it slows down simple guessing.
"""
import math
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, Optional

MAX_TRACKED_KEYS = 10_000   # memory guard: an attacker cannot grow the table without limit
MAX_EMAIL_CHARS = 255       # a huge "email" must not become a huge key


def throttle_key(email: str, ip: Optional[str]) -> str:
    return f"{(email or '')[:MAX_EMAIL_CHARS]}|{ip or 'unknown'}"


def too_many_message(wait_seconds: int) -> str:
    minutes = max(1, math.ceil(wait_seconds / 60))
    return f"Too many failed login attempts. Please wait {minutes} minute{'s' if minutes != 1 else ''} and try again."


class LoginThrottle:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock  # replaced by a fake clock in tests
        self._failures: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()  # FastAPI runs normal (non-async) endpoints in several threads

    def retry_after(self, key: str, max_failures: int, window_seconds: float) -> Optional[int]:
        """None when the attempt may go ahead; otherwise the whole number of seconds the user has to wait."""
        now = self._clock()
        with self._lock:
            times = self._prune(key, now, window_seconds)
            if len(times) < max_failures:
                return None
            return max(1, math.ceil(times[0] + window_seconds - now))

    def record_failure(self, key: str, window_seconds: float) -> None:
        now = self._clock()
        with self._lock:
            times = self._prune(key, now, window_seconds)
            times.append(now)
            self._failures[key] = times
            if len(self._failures) > MAX_TRACKED_KEYS:
                self._shrink(now, window_seconds)

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def reset(self) -> None:
        """Forget everything (used by the automated tests so they cannot affect each other)."""
        with self._lock:
            self._failures.clear()

    # ---- internals (call only while holding the lock)
    def _prune(self, key: str, now: float, window_seconds: float) -> Deque[float]:
        times = self._failures.get(key)
        if times is None:
            return deque()
        cutoff = now - window_seconds
        while times and times[0] <= cutoff:
            times.popleft()
        if not times:
            del self._failures[key]
            return deque()
        return times

    def _shrink(self, now: float, window_seconds: float) -> None:
        cutoff = now - window_seconds
        for stale in [k for k, t in self._failures.items() if not t or t[-1] <= cutoff]:
            del self._failures[stale]
        while len(self._failures) > MAX_TRACKED_KEYS:  # still too many: drop the oldest entries
            del self._failures[next(iter(self._failures))]


login_throttle = LoginThrottle()  # the one instance used by the application
