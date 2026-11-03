"""PostgreSQL integration tests; set GROQ_TEST_DATABASE_URL to an isolated DB."""
from __future__ import annotations

import os
import threading
import uuid
from urllib.parse import urlparse

import psycopg
import pytest

import groq_service
from groq_service import GroqBusyError, ensure_shared_limiter_schema, message_call_budget


@pytest.fixture(scope="module")
def test_database_url():
    url = os.getenv("GROQ_TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("GROQ_TEST_DATABASE_URL must point to a disposable PostgreSQL test database")
    dbname = urlparse(url).path.rsplit("/", 1)[-1]
    if "test" not in dbname.lower():
        pytest.fail("Refusing Groq limiter integration tests unless the database name contains 'test'")
    return url


@pytest.fixture(autouse=True)
def isolated_limiter_state(monkeypatch, test_database_url):
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("GROQ_SHARED_LIMITER_ENABLED", "true")
    monkeypatch.setenv("GROQ_SHARED_RPM_LIMIT", "100")
    monkeypatch.setenv("GROQ_SHARED_TPM_LIMIT", "20000")
    monkeypatch.setenv("GROQ_SHARED_MAX_CONCURRENT", "8")
    with psycopg.connect(test_database_url) as conn:
        with conn.cursor() as cur:
            ensure_shared_limiter_schema(cur)
            cur.execute("DELETE FROM groq_shared_leases")
            cur.execute("DELETE FROM groq_shared_usage_window")
    yield
    with psycopg.connect(test_database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM groq_shared_leases")
            cur.execute("DELETE FROM groq_shared_usage_window")


def _reserve(prompt="abcd", *, reason="general_knowledge_answer", output_tokens=20):
    request_id = uuid.uuid4().hex
    with message_call_budget(request_id, max_calls=1):
        return groq_service._shared_capacity_reserve(
            prompt, request_id, reason=reason, output_tokens=output_tokens,
        )


def _usage_row():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT request_count, reserved_tokens, window_started_at FROM groq_shared_usage_window WHERE singleton=1")
            return cur.fetchone()


def test_usage_reconciles_once_by_lease_without_refunding_other_requests():
    lease_id = _reserve()
    assert _usage_row()[1] == 22  # conservative UTF-8 prompt estimate plus 20 output tokens

    groq_service._shared_capacity_release(lease_id, actual_tokens=9, request_id="reconcile-once")
    groq_service._shared_capacity_release(lease_id, actual_tokens=0, request_id="double-release")

    row = _usage_row()
    assert row[0] == 1  # RPM is not refunded
    assert row[1] == 9
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM groq_shared_leases WHERE lease_id=%s", (lease_id,))
            assert cur.fetchone()[0] == 0


def test_missing_usage_keeps_full_reservation_until_window_reset():
    lease_id = _reserve(output_tokens=40)
    before = _usage_row()[1]

    groq_service._shared_capacity_release(lease_id, actual_tokens=None, request_id="missing-usage")

    assert _usage_row()[1] == before


def test_reconciliation_transaction_failure_rolls_back_lease_delete_and_counter_update():
    lease_id = _reserve(output_tokens=20)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE groq_shared_usage_window ADD CONSTRAINT test_hold_reserved_count CHECK (reserved_tokens=22)")

    # The UPDATE violates the temporary test constraint. The DELETE and update
    # share one transaction, so rollback must preserve both reservation records.
    groq_service._shared_capacity_release(lease_id, actual_tokens=9, request_id="forced-rollback")
    assert _usage_row()[1] == 22
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM groq_shared_leases WHERE lease_id=%s", (lease_id,))
            assert cur.fetchone()[0] == 1
            cur.execute("ALTER TABLE groq_shared_usage_window DROP CONSTRAINT test_hold_reserved_count")

    groq_service._shared_capacity_release(lease_id, actual_tokens=9, request_id="retry-after-rollback")
    assert _usage_row()[1] == 9


def test_old_window_completion_cannot_reduce_new_window_reservation():
    old_lease = _reserve(output_tokens=30)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE groq_shared_usage_window SET window_started_at=NOW()-INTERVAL '61 seconds' WHERE singleton=1")

    new_lease = _reserve(output_tokens=20)
    new_window_tokens = _usage_row()[1]
    assert new_window_tokens == 22

    groq_service._shared_capacity_release(old_lease, actual_tokens=1, request_id="old-window")

    assert _usage_row()[1] == new_window_tokens
    groq_service._shared_capacity_release(new_lease, actual_tokens=None)


def test_expired_lease_releases_concurrency_but_not_tpm_before_window_reset():
    expired_lease = _reserve(output_tokens=25)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE groq_shared_leases SET expires_at=NOW()-INTERVAL '1 second' WHERE lease_id=%s", (expired_lease,))

    current_lease = _reserve(output_tokens=25)

    assert _usage_row()[1] == 54
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM groq_shared_leases WHERE expires_at > NOW()")
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT COUNT(*) FROM groq_shared_leases WHERE lease_id=%s", (expired_lease,))
            assert cur.fetchone()[0] == 0
    groq_service._shared_capacity_release(current_lease, actual_tokens=None)


def test_concurrent_reservations_obey_database_concurrency_limit():
    os.environ["GROQ_SHARED_MAX_CONCURRENT"] = "1"
    barrier = threading.Barrier(2)
    results = []

    def reserve_in_thread():
        request_id = uuid.uuid4().hex
        barrier.wait(timeout=3)
        try:
            with message_call_budget(request_id, max_calls=1):
                results.append(groq_service._shared_capacity_reserve(
                    "prompt", request_id, reason="research_summary_answer", output_tokens=20,
                ))
        except Exception as exc:  # test records the DB decision from both workers
            results.append(exc)

    threads = [threading.Thread(target=reserve_in_thread) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    assert all(not thread.is_alive() for thread in threads)
    assert sum(isinstance(value, str) for value in results) == 1
    assert sum(isinstance(value, GroqBusyError) for value in results) == 1
    for value in results:
        if isinstance(value, str):
            groq_service._shared_capacity_release(value, actual_tokens=None)


def test_legacy_lease_schema_migrates_additive_columns_without_rewriting_rows():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE groq_shared_leases")
            cur.execute("CREATE TABLE groq_shared_leases (lease_id TEXT PRIMARY KEY, expires_at TIMESTAMPTZ NOT NULL)")
            cur.execute("INSERT INTO groq_shared_leases(lease_id, expires_at) VALUES ('legacy', NOW()+INTERVAL '30 seconds')")
            ensure_shared_limiter_schema(cur)
            cur.execute("SELECT reserved_tokens, window_started_at FROM groq_shared_leases WHERE lease_id='legacy'")
            assert cur.fetchone() == (None, None)


def test_invalid_postgres_reservation_fails_closed(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://invalid:invalid@127.0.0.1:1/gutgpt_test")
    with message_call_budget("db-failure", max_calls=1), pytest.raises(GroqBusyError):
        groq_service._shared_capacity_reserve(
            "prompt", "db-failure", reason="nlu_extraction", output_tokens=350,
        )
