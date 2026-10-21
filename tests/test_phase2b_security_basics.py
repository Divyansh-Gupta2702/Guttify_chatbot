"""Phase 2B security regression tests for CORS configuration validation."""
import pytest

import app as gutgpt_app


@pytest.mark.parametrize("origin", [
    "*",
    "http://example.com",
    "https://example.com/path",
    "https://user:password@example.com",
    "ftp://example.com",
    "https://example.com?next=evil",
])
def test_cors_origin_rejects_unsafe_or_malformed_values(origin):
    with pytest.raises(ValueError):
        gutgpt_app._validate_allowed_origins([origin])


@pytest.mark.parametrize("origin", [
    "https://www.example.com",
    "https://example.com",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
])
def test_cors_origin_accepts_https_and_local_development(origin):
    gutgpt_app._validate_allowed_origins([origin])


def test_restore_cannot_switch_an_already_bound_session_to_another_customer(monkeypatch):
    monkeypatch.setattr(gutgpt_app, "SESSION_CUSTOMER_IDS", {"session-a": "customer-a"})
    with pytest.raises(gutgpt_app.HTTPException) as exc:
        gutgpt_app._assert_session_customer_binding("session-a", "customer-b")
    assert exc.value.status_code == 409


def test_restore_allows_unbound_or_same_customer_session(monkeypatch):
    monkeypatch.setattr(gutgpt_app, "SESSION_CUSTOMER_IDS", {"session-a": "customer-a"})
    gutgpt_app._assert_session_customer_binding("session-new", "customer-b")
    gutgpt_app._assert_session_customer_binding("session-a", "customer-a")


def _fake_request(host="127.0.0.1"):
    from starlette.requests import Request
    return Request({
        "type": "http", "http_version": "1.1", "method": "GET",
        "scheme": "http", "path": "/api/admin/customers", "raw_path": b"/api/admin/customers",
        "query_string": b"", "headers": [], "client": (host, 12345), "server": ("testserver", 80),
    })


def test_admin_token_must_be_at_least_32_bytes(monkeypatch):
    monkeypatch.setenv("GUTGPT_ADMIN_TOKEN", "too-short")
    monkeypatch.setattr(gutgpt_app, "DATABASE_URL", "")
    gutgpt_app._RATE_LIMIT_BUCKETS.clear()
    with pytest.raises(gutgpt_app.HTTPException) as exc:
        gutgpt_app._require_admin("Bearer too-short", _fake_request())
    assert exc.value.status_code == 503


def test_admin_token_accepts_matching_strong_secret(monkeypatch):
    token = "0123456789abcdef0123456789abcdef"
    monkeypatch.setenv("GUTGPT_ADMIN_TOKEN", token)
    monkeypatch.setattr(gutgpt_app, "DATABASE_URL", "")
    gutgpt_app._RATE_LIMIT_BUCKETS.clear()
    gutgpt_app._require_admin(f"Bearer {token}", _fake_request())


def test_local_rate_limiter_returns_429_after_limit(monkeypatch):
    monkeypatch.setattr(gutgpt_app, "DATABASE_URL", "")
    gutgpt_app._RATE_LIMIT_BUCKETS.clear()
    request = _fake_request()
    gutgpt_app._enforce_rate_limit(request, scope="test", identity="client-a", limit=2, window_seconds=60)
    gutgpt_app._enforce_rate_limit(request, scope="test", identity="client-a", limit=2, window_seconds=60)
    with pytest.raises(gutgpt_app.HTTPException) as exc:
        gutgpt_app._enforce_rate_limit(request, scope="test", identity="client-a", limit=2, window_seconds=60)
    assert exc.value.status_code == 429
    assert int(exc.value.headers["Retry-After"]) > 0



def test_registration_rejects_switching_a_bound_session_to_a_new_profile(monkeypatch):
    monkeypatch.setattr(gutgpt_app, "SESSION_CUSTOMER_IDS", {"session-a": "customer-a"})
    with pytest.raises(gutgpt_app.HTTPException) as exc:
        gutgpt_app._assert_registration_customer_binding("session-a", None)
    assert exc.value.status_code == 409


def test_registration_allows_retry_for_same_bound_customer(monkeypatch):
    monkeypatch.setattr(gutgpt_app, "SESSION_CUSTOMER_IDS", {"session-a": "customer-a"})
    gutgpt_app._assert_registration_customer_binding("session-a", {"customer_id": "customer-a"})
