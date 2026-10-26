from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "app.py"


def test_legacy_history_writer_does_not_force_existing_assessments_completed():
    source = APP.read_text(encoding="utf-8")
    start = source.index("def _write_customer_records(")
    end = source.index("def _persist_assessment_checkpoint(", start)
    writer = source[start:end]
    conflict = writer.split("ON CONFLICT (session_id) DO UPDATE SET", 1)[1].split('"""', 1)[0]

    assert "status='completed'" not in conflict
    assert "completed_at=EXCLUDED.completed_at" not in conflict
    assert "assessment=EXCLUDED.assessment" in conflict


def test_checkpoint_writer_remains_owner_of_assessment_status():
    source = APP.read_text(encoding="utf-8")
    start = source.index("def _persist_assessment_checkpoint(")
    end = source.find("\ndef ", start + 5)
    checkpoint_writer = source[start:end if end != -1 else None]

    assert '"completed" if not checkpoint["active"] else "active"' in checkpoint_writer
    assert "completed_at=CASE WHEN %s THEN COALESCE(completed_at,NOW()) ELSE completed_at END" in checkpoint_writer
