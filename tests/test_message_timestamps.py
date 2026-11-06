from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_chat_bubbles_display_local_send_time():
    source = (ROOT / "gutgpt-widget.js").read_text(encoding="utf-8")
    assert 'className = "msg-time"' in source
    assert 'toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })' in source
    assert "timeElement.dateTime = time.iso" in source


def test_restored_messages_keep_their_persisted_timestamps():
    widget = (ROOT / "gutgpt-widget.js").read_text(encoding="utf-8")
    backend = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'item.created_at || item.timestamp' in widget
    assert "SELECT sequence_no, role, content, created_at FROM assessment_messages" in backend
    assert '"created_at": r["created_at"].astimezone(INDIA_TZ).isoformat()' in backend
