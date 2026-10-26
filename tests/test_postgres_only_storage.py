"""Regression checks for the PostgreSQL-only storage policy."""
from pathlib import Path

import pytest
from fastapi import HTTPException
import app as gutgpt_app


def test_missing_database_url_fails_closed(monkeypatch):
    monkeypatch.setattr(gutgpt_app, "DATABASE_URL", "")
    with pytest.raises(HTTPException) as error:
        gutgpt_app._postgres_connect()
    assert error.value.status_code == 503
    assert "PostgreSQL" in error.value.detail


def test_production_configuration_requires_database_url(monkeypatch):
    monkeypatch.setattr(gutgpt_app, "DATABASE_URL", "")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-that-is-long-enough-for-a-test-123456789")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://guttify.com")
    monkeypatch.setattr(gutgpt_app, "allowed_origins", ["https://guttify.com"])
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        gutgpt_app.validate_production_configuration()


def test_customer_json_file_fallback_is_absent_from_runtime_source():
    source = (Path(gutgpt_app.BASE_DIR) / "app.py").read_text(encoding="utf-8")
    assert "CUSTOMER_DATA_FILE" not in source
    assert "_read_json_records" not in source
    assert "_write_json_records" not in source
    assert "JSON fallback" not in source


def test_customer_profile_schema_is_minimal_and_chat_state_is_separate():
    source = (Path(gutgpt_app.BASE_DIR) / "app.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS customer_chat_state" in source
    assert "active_checkpoint JSONB" in source
    assert "chat_history JSONB" in source
    assert "bound_session_ids TEXT[]" in source
    assert "CREATE TABLE IF NOT EXISTS customers" in source
    assert "record_json JSONB NOT NULL DEFAULT" not in source
    assert "ALTER TABLE customers DROP COLUMN record_json" in source
    assert "likely_assessment TEXT" in source


def test_per_assessment_chat_history_and_checkpoint_are_normalized():
    source = (Path(gutgpt_app.BASE_DIR) / "app.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS assessment_sessions" not in source
    assert "CREATE TABLE IF NOT EXISTS assessment_session_bindings" not in source
    assert "CREATE TABLE IF NOT EXISTS assessment_messages" in source
    assert "CREATE TABLE IF NOT EXISTS assessment_state" in source
    assert "UNIQUE (assessment_id, sequence_no)" in source
    assert "UNIQUE (assessment_id, turn_id, role)" in source
    assert "SESSION_ASSESSMENT_IDS" in source
    assert "Normalized assessment restore lookup failed" in source
