from guttify_agent import ConversationManager


def active(question="duration", primary="bloating"):
    cm = ConversationManager()
    sid = "state-hardening"
    session = cm._get_session(sid)
    session.last_question = question
    session.symptom_state.primary_symptom = primary
    return cm, sid, session


def test_active_question_preserves_volunteered_abdominal_pain():
    cm, sid, session = active()
    session.symptom_state.bloating = True
    cm.handle_message(sid, "I also have abdominal pain")
    assert session.symptom_state.bloating is True
    assert session.symptom_state.abdominal_pain is True


def test_active_question_preserves_multiple_volunteered_symptoms():
    cm, sid, session = active()
    session.symptom_state.bloating = True
    cm.handle_message(sid, "I also have gas and diarrhea")
    assert session.symptom_state.gas is True
    assert session.symptom_state.diarrhea is True
    assert session.symptom_state.diarrhea_explicit is True


def test_explicit_negative_bloating_clears_stale_state_and_branch():
    cm, sid, session = active()
    session.symptom_state.bloating = True
    session.symptom_state.secondary_symptoms = ["bloating"]
    cm.handle_message(sid, "I don't have bloating")
    assert session.symptom_state.bloating is False
    assert session.symptom_state.primary_symptom is None
    assert "bloating" not in session.symptom_state.secondary_symptoms


def test_explicit_negative_diarrhea_clears_both_diarrhea_slots():
    cm, sid, session = active(primary="diarrhea")
    session.symptom_state.diarrhea = True
    session.symptom_state.diarrhea_explicit = True
    session.symptom_state.secondary_symptoms = ["diarrhea"]
    cm.handle_message(sid, "I don't have diarrhea")
    assert session.symptom_state.diarrhea is False
    assert session.symptom_state.diarrhea_explicit is False
    assert session.symptom_state.primary_symptom is None
    assert "diarrhea" not in session.symptom_state.secondary_symptoms


def test_primary_symptom_is_not_duplicated_in_secondary_symptoms():
    cm = ConversationManager()
    sid = "state-hardening-initial"
    cm.handle_message(sid, "I have bloating")
    state = cm._get_session(sid).symptom_state
    assert state.primary_symptom == "bloating"
    assert "bloating" not in state.secondary_symptoms


def test_initial_gas_populates_canonical_gas_field():
    cm = ConversationManager()
    sid = "state-hardening-gas"
    cm.handle_message(sid, "I have gas")
    state = cm._get_session(sid).symptom_state
    assert state.primary_symptom == "gas"
    assert state.gas is True
    assert "gas" not in state.secondary_symptoms


def test_initial_explicit_negative_does_not_create_symptom_branch():
    cm = ConversationManager()
    sid = "state-hardening-negative"
    cm.handle_message(sid, "I don't have bloating")
    state = cm._get_session(sid).symptom_state
    assert state.primary_symptom is None
    assert state.bloating is False
    assert "bloating" not in state.secondary_symptoms


def test_volunteered_positive_can_replace_a_denied_primary_with_remaining_symptom():
    cm, sid, session = active()
    session.symptom_state.bloating = True
    session.symptom_state.secondary_symptoms = ["gas"]
    session.symptom_state.gas = True
    cm.handle_message(sid, "I don't have bloating, but I do have gas")
    assert session.symptom_state.primary_symptom == "gas"
    assert session.symptom_state.gas is True
    assert session.symptom_state.bloating is False
    assert session.symptom_state.secondary_symptoms == []
