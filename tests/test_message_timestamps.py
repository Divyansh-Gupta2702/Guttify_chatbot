from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_chat_bubbles_display_local_send_time():
    source = (ROOT / "gutgpt-widget.js").read_text(encoding="utf-8")
    assert 'className = "msg-time"' in source
    assert 'toLocaleString([], {' in source
    assert 'month: "short", day: "numeric", year: "numeric"' in source
    assert "timeElement.dateTime = time.iso" in source


def test_restored_messages_keep_their_persisted_timestamps():
    widget = (ROOT / "gutgpt-widget.js").read_text(encoding="utf-8")
    backend = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'item.created_at || item.timestamp' in widget
    assert "SELECT sequence_no, role, content, created_at FROM assessment_messages" in backend
    assert "SELECT role, content, created_at FROM (" in backend
    assert '"created_at": r["created_at"].astimezone(INDIA_TZ).isoformat()' in backend
    assert "INSERT INTO assessment_messages (assessment_id, sequence_no, turn_id, role, content, created_at)" in backend
    assert '_to_utc_datetime(item.get("created_at"))' in backend
    assert "user_message_at=user_message_at.isoformat()" in backend
    assert "assistant_message_at=assistant_message_at.isoformat()" in backend
