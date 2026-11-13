"""Tests for the Gemini REST client. A tiny local HTTP server plays the role of Google, so these tests never touch
the real service and never need a real API key."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.services.gemini_client import AIError, GeminiClient, build_client

FAKE_KEY = "FAKE-KEY-for-tests-1234567890"


class FakeGemini:
    """Runs a local server that returns the queued (status, body, delay) responses in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []  # (path, headers, json body)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                outer.requests.append((self.path, {k.lower(): v for k, v in self.headers.items()}, body))  # header names are case-insensitive
                status, payload, delay = outer.responses.pop(0) if outer.responses else (500, {}, 0)
                if delay:
                    time.sleep(delay)
                raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def ok(text):
    return (200, {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}, 0)


def client_for(fake, **kwargs):
    kwargs.setdefault("backoff", 0.0)
    return GeminiClient(FAKE_KEY, model="gemini-test", timeout=kwargs.pop("timeout", 5), base_url=fake.url, **kwargs)


def kind_of(fake, **kwargs):
    try:
        client_for(fake, **kwargs).generate("system", "user")
    except AIError as exc:
        return exc
    raise AssertionError("expected an AIError")


# ---------------------------------------------------------------- success
def test_successful_call_returns_the_answer_and_sends_the_documented_request():
    fake = FakeGemini([ok("The deadline is 2026-12-31. [Activity]")])
    try:
        answer = client_for(fake).generate("SYSTEM RULES", "CONTEXT AND QUESTION")
    finally:
        fake.close()
    assert answer == "The deadline is 2026-12-31. [Activity]"
    path, headers, body = fake.requests[0]
    assert path == "/v1beta/models/gemini-test:generateContent"
    assert headers["x-goog-api-key"] == FAKE_KEY  # the key travels in a header ...
    assert FAKE_KEY not in path and FAKE_KEY not in json.dumps(body)  # ... never in the URL or the body
    assert body["systemInstruction"]["parts"][0]["text"] == "SYSTEM RULES"
    assert body["contents"][0]["role"] == "user" and body["contents"][0]["parts"][0]["text"] == "CONTEXT AND QUESTION"
    assert body["generationConfig"]["temperature"] == 0.2


def test_multiple_answer_parts_are_joined():
    payload = {"candidates": [{"content": {"parts": [{"text": "Part one. "}, {"text": "Part two."}]}}]}
    fake = FakeGemini([(200, payload, 0)])
    try:
        assert client_for(fake).generate("s", "u") == "Part one. Part two."
    finally:
        fake.close()


# ----------------------------------------------------------- error mapping
def test_invalid_key_is_reported_as_auth_problem():
    body = {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}}
    fake = FakeGemini([(400, body, 0)])
    try:
        err = kind_of(fake)
    finally:
        fake.close()
    assert err.kind == "auth" and err.db_status == "UNAVAILABLE"
    assert "GEMINI_API_KEY" in err.user_message


def test_forbidden_is_auth_unknown_model_is_config_and_other_400_is_config():
    for status, expected in ((403, "auth"), (401, "auth"), (404, "config"), (400, "config")):
        fake = FakeGemini([(status, {"error": {"message": "something else"}}, 0)])
        try:
            assert kind_of(fake).kind == expected, status
        finally:
            fake.close()


def test_rate_limit_is_reported_and_not_retried():
    fake = FakeGemini([(429, {"error": {"message": "quota"}}, 0), ok("never reached")])
    try:
        assert kind_of(fake).kind == "rate_limit"
    finally:
        fake.close()
    assert len(fake.requests) == 1


def test_temporary_server_error_is_retried_once_then_succeeds():
    fake = FakeGemini([(503, {"error": {"message": "overloaded"}}, 0), ok("second try works")])
    try:
        assert client_for(fake).generate("s", "u") == "second try works"
    finally:
        fake.close()
    assert len(fake.requests) == 2


def test_persistent_server_error_gives_up_after_one_retry():
    fake = FakeGemini([(500, {}, 0), (500, {}, 0), ok("never reached")])
    try:
        assert kind_of(fake).kind == "server"
    finally:
        fake.close()
    assert len(fake.requests) == 2


def test_slow_server_times_out_as_network_problem():
    fake = FakeGemini([(200, {"candidates": []}, 1.5)])
    try:
        assert kind_of(fake, timeout=0.3).kind == "network"
    finally:
        fake.close()


def test_unreachable_server_is_a_network_problem():
    fake = FakeGemini([])
    url = fake.url
    fake.close()  # nothing listens on that port any more
    try:
        GeminiClient(FAKE_KEY, base_url=url, timeout=2).generate("s", "u")
    except AIError as exc:
        assert exc.kind == "network"
    else:
        raise AssertionError("expected an AIError")


# --------------------------------------------------------- unusable answers
def test_malformed_and_empty_responses_are_bad_responses():
    for payload in (b"this is not json", b"[]", {"candidates": []}, {"nothing": "here"},
                    {"candidates": [{"content": {"parts": []}}]}, {"candidates": [{"content": {"parts": [{"text": "  "}]}}]}):
        fake = FakeGemini([(200, payload, 0)])
        try:
            err = kind_of(fake)
        finally:
            fake.close()
        assert err.kind == "bad_response" and err.db_status == "FAILED"


def test_blocked_prompts_and_safety_stops_are_reported_as_blocked():
    cases = [
        {"promptFeedback": {"blockReason": "SAFETY"}},
        {"candidates": [{"finishReason": "SAFETY"}]},
        {"candidates": [{"content": {"parts": []}, "finishReason": "PROHIBITED_CONTENT"}]},
    ]
    for payload in cases:
        fake = FakeGemini([(200, payload, 0)])
        try:
            err = kind_of(fake)
        finally:
            fake.close()
        assert err.kind == "blocked" and err.db_status == "FAILED"


# --------------------------------------------------------- key never leaks
def test_the_key_never_appears_in_errors_logs_or_repr(caplog):
    cases = [(400, {"error": {"message": f"bad key {FAKE_KEY}"}}, 0), (500, {}, 0), (500, {}, 0)]
    fake = FakeGemini(cases)
    try:
        with caplog.at_level("DEBUG"):
            err = kind_of(fake)
    finally:
        fake.close()
    assert FAKE_KEY not in str(err) and FAKE_KEY not in err.user_message
    assert FAKE_KEY not in caplog.text
    assert FAKE_KEY not in repr(GeminiClient(FAKE_KEY))


def test_no_key_means_not_configured_without_any_request():
    try:
        GeminiClient("").generate("s", "u")
    except AIError as exc:
        assert exc.kind == "not_configured"
    else:
        raise AssertionError("expected an AIError")


def test_build_client_ignores_missing_or_placeholder_keys():
    assert build_client("", "m", 5) is None and build_client(None, "m", 5) is None
    assert build_client("   ", "m", 5) is None
    assert build_client("your_gemini_key_here", "m", 5) is None
    assert build_client("CHANGE_ME", "m", 5) is None
    assert isinstance(build_client("AIza-real-looking-key", "gemini-2.5-flash", 5), GeminiClient)
