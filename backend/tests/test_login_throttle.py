"""Unit tests of the failed-login limiter. Pure Python: no database, no web framework, no real waiting (fake clock)."""
import threading

import app.services.login_throttle as module
from app.services.login_throttle import LoginThrottle, throttle_key, too_many_message

WINDOW = 900  # 15 minutes
LIMIT = 5


class FakeClock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make():
    clock = FakeClock()
    return LoginThrottle(clock), clock


def fail(throttle, key, times):
    for _ in range(times):
        throttle.record_failure(key, WINDOW)


def test_attempts_below_the_limit_are_allowed():
    throttle, _ = make()
    assert throttle.retry_after("a|1", LIMIT, WINDOW) is None
    fail(throttle, "a|1", LIMIT - 1)
    assert throttle.retry_after("a|1", LIMIT, WINDOW) is None


def test_the_limit_blocks_and_reports_how_long_to_wait():
    throttle, clock = make()
    fail(throttle, "a|1", LIMIT)
    assert throttle.retry_after("a|1", LIMIT, WINDOW) == WINDOW
    clock.advance(100)
    assert throttle.retry_after("a|1", LIMIT, WINDOW) == WINDOW - 100


def test_wait_time_is_rounded_up_never_zero():
    throttle, clock = make()
    fail(throttle, "a|1", LIMIT)
    clock.advance(WINDOW - 0.2)
    assert throttle.retry_after("a|1", LIMIT, WINDOW) == 1


def test_the_window_slides_and_the_user_can_try_again():
    throttle, clock = make()
    fail(throttle, "a|1", LIMIT)
    clock.advance(WINDOW + 1)
    assert throttle.retry_after("a|1", LIMIT, WINDOW) is None


def test_a_failure_exactly_one_window_old_has_expired():
    throttle, clock = make()
    fail(throttle, "a|1", LIMIT)
    clock.advance(WINDOW)
    assert throttle.retry_after("a|1", LIMIT, WINDOW) is None


def test_old_failures_expire_one_by_one():
    throttle, clock = make()
    fail(throttle, "a|1", 3)
    clock.advance(600)
    fail(throttle, "a|1", 2)                       # 5 failures in total: blocked
    assert throttle.retry_after("a|1", LIMIT, WINDOW) == WINDOW - 600
    clock.advance(301)                             # the first three are now older than the window
    assert throttle.retry_after("a|1", LIMIT, WINDOW) is None


def test_a_successful_login_clears_the_count():
    throttle, _ = make()
    fail(throttle, "a|1", LIMIT - 1)
    throttle.clear("a|1")
    fail(throttle, "a|1", LIMIT - 1)
    assert throttle.retry_after("a|1", LIMIT, WINDOW) is None   # would be blocked if the count had been kept


def test_clear_also_lifts_a_block():
    throttle, _ = make()
    fail(throttle, "a|1", LIMIT)
    throttle.clear("a|1")
    assert throttle.retry_after("a|1", LIMIT, WINDOW) is None


def test_other_emails_and_other_ips_are_not_affected():
    throttle, _ = make()
    fail(throttle, throttle_key("alice@example.com", "10.0.0.1"), LIMIT)
    assert throttle.retry_after(throttle_key("alice@example.com", "10.0.0.1"), LIMIT, WINDOW) is not None
    assert throttle.retry_after(throttle_key("bob@example.com", "10.0.0.1"), LIMIT, WINDOW) is None
    # a stranger failing on purpose cannot lock the real user out from the real user's own address:
    assert throttle.retry_after(throttle_key("alice@example.com", "203.0.113.9"), LIMIT, WINDOW) is None


def test_a_limit_of_one_blocks_after_the_first_failure():
    throttle, _ = make()
    assert throttle.retry_after("a|1", 1, WINDOW) is None
    fail(throttle, "a|1", 1)
    assert throttle.retry_after("a|1", 1, WINDOW) == WINDOW


def test_checking_does_not_count_as_a_failure():
    throttle, _ = make()
    for _ in range(50):
        throttle.retry_after("a|1", LIMIT, WINDOW)
    assert throttle.retry_after("a|1", LIMIT, WINDOW) is None
    assert "a|1" not in throttle._failures


def test_expired_entries_are_removed_from_memory():
    throttle, clock = make()
    fail(throttle, "a|1", 2)
    clock.advance(WINDOW + 1)
    throttle.retry_after("a|1", LIMIT, WINDOW)
    assert "a|1" not in throttle._failures


def test_reset_forgets_everything():
    throttle, _ = make()
    fail(throttle, "a|1", LIMIT)
    fail(throttle, "b|1", LIMIT)
    throttle.reset()
    assert throttle.retry_after("a|1", LIMIT, WINDOW) is None
    assert throttle.retry_after("b|1", LIMIT, WINDOW) is None


def test_memory_is_capped_so_an_attacker_cannot_fill_it():
    original = module.MAX_TRACKED_KEYS
    module.MAX_TRACKED_KEYS = 20
    try:
        throttle, _ = make()
        for i in range(100):
            fail(throttle, f"user{i}@example.com|9.9.9.9", 1)
        assert len(throttle._failures) <= 20
    finally:
        module.MAX_TRACKED_KEYS = original


def test_when_the_table_is_full_expired_entries_are_dropped_first():
    original = module.MAX_TRACKED_KEYS
    module.MAX_TRACKED_KEYS = 10
    try:
        throttle, clock = make()
        for i in range(10):
            fail(throttle, f"old{i}|1", LIMIT)           # ten blocked keys ...
        clock.advance(WINDOW + 1)                          # ... that have all expired by now
        fail(throttle, "new|1", LIMIT)                     # table over the cap -> expired keys go, this one stays
        assert throttle.retry_after("new|1", LIMIT, WINDOW) is not None
    finally:
        module.MAX_TRACKED_KEYS = original


def test_many_threads_recording_at_once_lose_nothing():
    throttle = LoginThrottle()
    errors = []

    def worker():
        try:
            for _ in range(200):
                throttle.record_failure("a|1", 3600)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(throttle._failures["a|1"]) == 1600


def test_key_combines_email_and_ip():
    assert throttle_key("a@b.com", "1.2.3.4") == "a@b.com|1.2.3.4"
    assert throttle_key("a@b.com", None) == "a@b.com|unknown"
    assert throttle_key("a@b.com", "1.2.3.4") != throttle_key("a@b.com", "1.2.3.5")


def test_a_huge_email_cannot_become_a_huge_key():
    assert len(throttle_key("x" * 100_000, "1.2.3.4")) < 300


def test_message_rounds_up_to_whole_minutes():
    assert too_many_message(1) == "Too many failed login attempts. Please wait 1 minute and try again."
    assert too_many_message(60) == "Too many failed login attempts. Please wait 1 minute and try again."
    assert too_many_message(61) == "Too many failed login attempts. Please wait 2 minutes and try again."
    assert too_many_message(900) == "Too many failed login attempts. Please wait 15 minutes and try again."


def test_message_does_not_say_whether_the_email_exists():
    text = too_many_message(300).lower()
    assert "email" not in text and "account" not in text and "password" not in text
