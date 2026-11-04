"""Static integration contract for Bristol chart metadata and widget rendering.

A real Shopify/browser run is still required for production verification.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_questionnaire_binds_chart_only_to_stool_form_question_id():
    source = (ROOT / "symptom_questionnaire.py").read_text(encoding="utf-8")
    assert 'if name == "stool_form":' in source
    assert "[[BRISTOL_STOOL_CHART]]" in source


def test_resume_api_returns_question_and_asset_metadata():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '"question_id": pending_id' in source
    assert '"display_asset": "bristol_stool_chart" if pending_id == "stool_form" else None' in source
    assert "pending_question" in source


def test_chat_api_returns_backward_compatible_question_metadata():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "question_metadata: dict | None = None" in source
    assert '"display_asset": "bristol_stool_chart" if active_question_id == "stool_form" else None' in source


def test_backend_serves_the_approved_png_asset_with_image_content_type():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '@app.get("/assets/bristol-stool-chart.png"' in source
    assert 'BRISTOL_CHART_FILE = BASE_DIR / "Bristol Stool Chart Infographic.png"' in source
    assert 'media_type="image/png"' in source


def test_widget_uses_metadata_and_the_backend_asset_origin():
    source = (ROOT / "gutgpt-widget.js").read_text(encoding="utf-8")
    assert '`${GUTGPT_API_URL}/assets/bristol-stool-chart.png`' in source
    assert 'data.question_metadata.display_asset === "bristol_stool_chart"' in source
    assert 'pendingQuestion.display_asset === "bristol_stool_chart"' in source
    assert '"[[BRISTOL_STOOL_CHART]]"' in source
    assert '.bristol-stool-chart' in source


def test_widget_has_graceful_image_failure_fallback_and_single_click_handler():
    source = (ROOT / "gutgpt-widget.js").read_text(encoding="utf-8")
    assert 'messages.addEventListener("error"' in source
    assert 'className = "bristol-chart-fallback"' in source
    assert 'data-bristol-type' in source
    assert 'messages.addEventListener("click"' in source


def test_unrelated_question_ids_do_not_trigger_chart_asset_metadata():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'active_question_id == "stool_form"' in source
    assert 'pending_id == "stool_form"' in source
