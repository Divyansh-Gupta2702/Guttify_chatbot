"""Static release-contract checks for deployment fixes that need no live DB."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_chat_authorizes_and_checks_idempotency_before_conversation_mutation():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    chat = source[source.index("def _chat_impl("):source.index('@app.post("/api/chat"')]
    assert chat.index('raise HTTPException(status_code=410, detail="SESSION_EXPIRED")') < chat.index("_begin_chat_idempotency(")
    assert chat.index('raise HTTPException(status_code=403, detail="CUSTOMER_REGISTRATION_REQUIRED")') < chat.index("_begin_chat_idempotency(")
    assert chat.index("_begin_chat_idempotency(") < chat.index("conversation_manager.handle_message(")


def test_capacity_eviction_clears_all_session_mappings():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    cleanup = source[source.index("def _cleanup_sessions("):source.index("# Session state is kept in-process")]
    capacity = cleanup[cleanup.index("if len(HISTORY_LAST_ACCESS) > MAX_SESSIONS:"):]
    assert "SESSION_CUSTOMER_IDS.pop(sid, None)" in capacity
    assert "SESSION_ASSESSMENT_IDS.pop(sid, None)" in capacity
    assert "REGISTERED_CUSTOMER_SESSIONS.discard(sid)" in capacity


def test_native_postgres_example_uses_standard_port_and_documents_admin_secret():
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "@localhost:5432/gutgpt" in env
    assert "GUTGPT_ADMIN_TOKEN=" in env


def test_sensitive_backup_and_old_backup_source_are_excluded_from_release_tree():
    assert not (ROOT / "gutgpt_local_backup.dump").exists()
    assert not (ROOT / "src" / "gutgpt_local_backup.dump").exists()
    assert not (ROOT / "app.py.bak").exists()
    assert not (ROOT / "src" / "app.py.bak").exists()


def test_runtime_manifests_declare_direct_runtime_dependencies():
    pipfile = (ROOT / "Pipfile").read_text(encoding="utf-8").lower()
    for dependency in ("python-dotenv", "pyjwt", "psycopg", "tenacity", "langsmith"):
        assert dependency in pipfile


def test_documentation_matches_english_only_postgres_production_mode():
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert "english only" in readme
    assert "database_url" in readme
    assert "supported indian-language codes" not in readme
