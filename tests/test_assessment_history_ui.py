from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_backend_lists_only_authenticated_customers_assessments():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '@app.post("/api/customer/assessments")' in source
    assert "SESSION_CUSTOMER_IDS.get(req.session_id)" in source
    assert "req.session_id not in REGISTERED_CUSTOMER_SESSIONS" in source
    assert "WHERE customer_id=%s" in source


def test_backend_detail_checks_assessment_ownership_and_returns_transcript():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '@app.post("/api/customer/assessments/detail")' in source
    assert "WHERE assessment_id=%s AND customer_id=%s" in source
    assert "FROM assessment_messages" in source
    assert '"read_only": True' in source
    assert "symptom_summary" in source
    assert "build_symptom_summary(summary_state)" in source


def test_widget_has_history_and_full_transcript_views():
    source = (ROOT / "gutgpt-widget.js").read_text(encoding="utf-8")
    assert 'class="history-button"' in source
    assert 'class="assessment-history"' in source
    assert 'class="history-detail"' in source
    assert '"/api/customer/assessments"' in source
    assert '"/api/customer/assessments/detail"' in source
    assert "View summary & conversation" in source


def test_new_assessment_gets_separate_database_record_before_first_message():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    endpoint = source[source.index('@app.post("/api/session/new-assessment")'):source.index('@app.post("/api/customer/resume")')]
    assert "new_assessment_id = str(uuid.uuid4())" in endpoint
    assert "INSERT INTO customer_assessments" in endpoint
    assert "SESSION_ASSESSMENT_IDS[new_session_id] = new_assessment_id" in endpoint
    assert "SET status='abandoned'" in endpoint
