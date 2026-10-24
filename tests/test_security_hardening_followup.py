import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import app as gutgpt_app


@pytest.fixture(autouse=True)
def use_json_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(gutgpt_app, "DATABASE_URL", "")
    monkeypatch.setattr(gutgpt_app, "CUSTOMER_DATA_FILE", tmp_path / "customers.json")
    monkeypatch.setenv("GUTGPT_ADMIN_TOKEN", "test-admin-token-with-at-least-32-bytes-long")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-that-is-at-least-32-bytes-long")
    gutgpt_app._RATE_LIMIT_BUCKETS.clear()
    monkeypatch.setattr(gutgpt_app, "_RATE_LIMIT_CLEANUP_LAST", None)


def _request():
    return Request({
        "type": "http", "http_version": "1.1", "method": "GET",
        "scheme": "http", "path": "/api/admin/customers/download",
        "raw_path": b"/api/admin/customers/download", "query_string": b"",
        "headers": [], "client": ("127.0.0.1", 12345), "server": ("testserver", 80),
    })


def test_admin_json_export_is_valid_json_with_real_trailing_newline():
    gutgpt_app._write_json_records(gutgpt_app.CUSTOMER_DATA_FILE, [{"name": "Test", "contact": "1234567890"}])
    response = gutgpt_app.admin_download_customers(
        _request(), authorization="Bearer test-admin-token-with-at-least-32-bytes-long"
    )
    body = response.body
    assert body.endswith(b"\n")
    assert not body.endswith(b"\\n")
    assert json.loads(body) == [{"name": "Test", "contact": "1234567890"}]


def test_session_binding_is_recovered_from_persistent_customer_record():
    session_id = gutgpt_app.new_session()["session_id"]
    try:
        registered = gutgpt_app.register_customer(gutgpt_app.CustomerRegistrationRequest(
            session_id=session_id, name="Test", age=30, contact="1234567890", city="Delhi", consent=True,
        ))
        gutgpt_app.SESSION_CUSTOMER_IDS.pop(session_id, None)
        records = gutgpt_app._read_customer_records()
        assert session_id in records[0]["bound_session_ids"]
        with pytest.raises(HTTPException) as error:
            gutgpt_app._assert_session_customer_binding(session_id, "different-customer-id")
        assert error.value.status_code == 409
        assert registered["customer_id"] == records[0]["customer_id"]
    finally:
        gutgpt_app.REGISTERED_CUSTOMER_SESSIONS.discard(session_id)
        gutgpt_app.SESSION_CUSTOMER_IDS.pop(session_id, None)
        gutgpt_app.HISTORY.pop(session_id, None)
        gutgpt_app.HISTORY_LAST_ACCESS.pop(session_id, None)
        gutgpt_app.conversation_manager.remove(session_id)


def test_rate_limit_cleanup_schedule_is_deterministic(monkeypatch):
    monkeypatch.setattr(gutgpt_app, "_RATE_LIMIT_CLEANUP_LAST", None)
    assert gutgpt_app._should_cleanup_rate_limits() is True
    assert gutgpt_app._should_cleanup_rate_limits() is False


def test_jwt_key_requires_url_safe_43_character_minimum(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "a" * 32)
    with pytest.raises(HTTPException) as error:
        gutgpt_app._jwt_signing_key()
    assert error.value.status_code == 503


def test_widget_only_distribution_has_no_standalone_customer_frontend():
    root = Path(gutgpt_app.BASE_DIR)
    assert not (root / "index.html").exists()
    assert not (root / "chat.html").exists()

    source = (root / "gutgpt-widget.js").read_text(encoding="utf-8")
    assert "localStorage.getItem(GUEST_TOKEN_STORAGE_KEY)" not in source
    assert "localStorage.setItem(GUEST_TOKEN_STORAGE_KEY" not in source
    assert "sessionStorage.getItem(GUEST_TOKEN_STORAGE_KEY)" in source  # one-time legacy migration only
    assert "sessionStorage.setItem(GUEST_TOKEN_STORAGE_KEY" not in source
    assert 'credentials: "include"' in source


def test_guest_cookie_is_persistent_httponly_and_host_only():
    from fastapi import Response

    response = Response()
    gutgpt_app._set_guest_cookie(
        response, _request(), "test.signed.jwt", gutgpt_app.GUEST_TOKEN_TTL_SECONDS
    )
    header = response.headers.get("set-cookie", "")
    assert "gutgpt_guest_token=test.signed.jwt" in header
    assert "Max-Age=2592000" in header
    assert "HttpOnly" in header
    assert "Path=/" in header
    assert "SameSite=lax" in header
    assert "Domain=" not in header
    assert "Secure" not in header  # local HTTP development; HTTPS uses Secure + SameSite=None
