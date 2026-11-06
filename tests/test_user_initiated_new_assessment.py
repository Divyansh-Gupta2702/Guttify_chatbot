from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_widget_exposes_user_initiated_new_assessment_control():
    source = (ROOT / "gutgpt-widget.js").read_text(encoding="utf-8")
    assert 'class="new-assessment-button"' in source
    assert 'class="language-select"' in source
    assert 'class="language-select" aria-label="Chat language" title="Chat language" hidden' in source
    assert "function enableLanguageSelection()" in source
    assert '"/api/session/new-assessment"' in source
    assert "Your previous assessment has been preserved" in source
    registration = source[source.index('intakeForm.addEventListener("submit"'):source.index("function formatHistoryDate")]
    assert "assessmentActions.hidden = false" in registration
    assert "enableLanguageSelection()" in registration
    assert "language === \"hinglish\"" in source
    assert "newAssessment: \"＋ Naya assessment shuru karein\"" in source


def test_backend_creates_new_session_without_replacing_previous_assessment():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '@app.post("/api/session/new-assessment")' in source
    assert "previous_assessment_preserved" in source
    assert "SESSION_CUSTOMER_IDS.get(req.session_id)" in source
    assert "new_state.pregnancy_lactation_caution = carry_pregnancy_caution" in source


def test_new_assessment_keeps_pregnancy_product_restriction():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "new_state.pregnancy_assessment_started = carry_pregnancy_caution" in source
