"""Static guards that composite questionnaire IDs start with one component prompt."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_composite_prompts_do_not_ask_multiple_independent_symptoms_at_once():
    source = (ROOT / "symptom_questionnaire.py").read_text(encoding="utf-8")
    forbidden = [
        "Are your stools hard or lumpy, and do you need to strain",
        "Do you have bloating or recurring abdominal pain",
        "Do you have abdominal pain or cramps, and does it change",
        "Any repeated vomiting, fever, or severe abdominal swelling",
        "Any difficulty or pain swallowing, persistent vomiting, or vomiting blood",
        "Any blood or mucus in the stool",
        "Do your symptoms wake you at night, or have you had weight loss or fever",
        "Any unexplained weight loss, difficulty swallowing, persistent vomiting, or vomiting blood",
    ]
    for phrase in forbidden:
        assert phrase not in source


def test_bristol_marker_remains_bound_to_stool_form_question_id():
    source = (ROOT / "symptom_questionnaire.py").read_text(encoding="utf-8")
    assert 'if name == "stool_form":' in source
    assert '"[[BRISTOL_STOOL_CHART]]\\n"' in source
