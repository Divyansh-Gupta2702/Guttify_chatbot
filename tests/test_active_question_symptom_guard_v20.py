from types import SimpleNamespace

from nlu_extractor import extract_natural_facts


def state(primary="acidity"):
    return SimpleNamespace(
        primary_symptom=primary,
        secondary_symptoms=[],
    )


def test_simple_no_does_not_emit_session_symptom():
    facts = extract_natural_facts("no", "swallowing", state())
    assert facts["symptoms"] == []
    assert facts["difficulty_swallowing"] is False
    assert facts["persistent_vomiting"] is False
    assert facts["vomiting_blood"] is False


def test_simple_yes_does_not_emit_primary_symptom():
    facts = extract_natural_facts("yes", "reflux", state())
    assert facts["symptoms"] == []
    assert facts["reflux_present"] is True


def test_explicit_volunteered_symptoms_survive_active_question_guard():
    facts = extract_natural_facts(
        "no difficulty swallowing, but I have bloating and gas",
        "swallowing",
        state(),
    )
    assert facts["difficulty_swallowing"] is False
    assert set(facts["symptoms"]) >= {"bloating", "gas"}


def test_explicit_acidity_survives_reflux_question():
    facts = extract_natural_facts("yes, I also have acidity and gas", "reflux", state())
    assert facts["reflux_present"] is True
    assert set(facts["symptoms"]) >= {"acidity", "gas"}
