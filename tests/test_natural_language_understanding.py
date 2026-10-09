
from guttify_agent import ConversationManager


def visible_state(cm, sid):
    return cm.sessions[sid].symptom_state.to_dict()


def test_contextual_duration_answer_never_becomes_irrelevant():
    cm = ConversationManager()
    sid = "nlu-duration"
    first = cm.handle_message(sid, "I am feeling severe pain in my anal area")
    assert first["status"] == "ASK"
    assert "How long" in first["message"]

    second = cm.handle_message(sid, "2 days")
    state = visible_state(cm, sid)
    assert second["status"] == "ASK"
    assert second["status"] != "IRRELEVANT"
    assert state["duration"] == "2 days"


def test_long_message_extracts_multiple_facts():
    cm = ConversationManager()
    sid = "nlu-long"
    cm.handle_message(
        sid,
        "I've had piles for two months, I'm 23, haven't lost weight, and I don't have constipation.",
    )
    state = visible_state(cm, sid)
    assert state["primary_symptom"] == "piles"
    assert state["duration"] == "2 months"
    assert state["age"] == 23
    assert state["weight_loss"] is False
    assert state["constipation_explicit"] is False


def test_volunteered_bleeding_facts_are_preserved():
    cm = ConversationManager()
    sid = "nlu-volunteered"
    cm.handle_message(
        sid,
        "I've had bright red blood on the toilet paper for two days and there's a sharp tearing pain after I poop.",
    )
    state = visible_state(cm, sid)
    assert state["blood_present"] is True
    assert state["blood_colour"] == "bright_red"
    assert state["blood_location"] == "tissue"
    assert state["duration"] == "2 days"
    assert state["sharp_pain_during_stool"] is True


def test_natural_gut_language_with_multiple_symptoms():
    cm = ConversationManager()
    sid = "nlu-multi"
    cm.handle_message(
        sid,
        "I've been bloated after meals for the last three weeks, passing a lot of gas, and sometimes I don't poop for two or three days.",
    )
    state = visible_state(cm, sid)
    assert state["primary_symptom"] == "bloating"
    assert "gas" in state["secondary_symptoms"]
    assert state["duration"] == "3 weeks"
    assert state["constipation_explicit"] is True


def test_negated_stool_facts_are_not_created_by_nlu():
    cm = ConversationManager()
    sid = "nlu-negation"
    for message in [
        "I have bright red blood when I poop",
        "2 months",
        "23",
        "on tissue",
        "no sharp pain",
        "yes lump",
        "no hard stools and no straining",
    ]:
        result = cm.handle_message(sid, message)

    state = visible_state(cm, sid)
    assert state["sharp_pain_during_stool"] is False
    assert state["straining"] is False
    assert state["stool_form"] is None
    assert result["screening"]["pattern"] == "Possible hemorrhoid pattern"


def test_active_question_interprets_natural_weight_loss_negative():
    cm = ConversationManager()
    sid = "nlu-weight"
    cm.handle_message(sid, "I have had piles for two months")
    # Duration is answered in the same message; the next question is weight loss.
    state = visible_state(cm, sid)
    assert state["duration"] == "2 months"
    result = cm.handle_message(sid, "No, not really. I've actually gained a little weight.")
    state = visible_state(cm, sid)
    assert state["weight_loss"] is False
    assert result["status"] != "IRRELEVANT"


def test_active_question_interprets_natural_stool_negative():
    cm = ConversationManager()
    sid = "nlu-stool"
    cm.handle_message(sid, "I have constipation")
    cm.handle_message(sid, "2 weeks")
    cm.handle_message(sid, "23")
    cm.handle_message(sid, "No, my stools are pretty normal and I don't have to strain.")
    state = visible_state(cm, sid)
    assert state["straining"] is False
    assert state["stool_form"] is None


def test_long_relevant_message_does_not_become_irrelevant():
    cm = ConversationManager()
    sid = "nlu-relevant-long"
    result = cm.handle_message(
        sid,
        "For the last three weeks my stomach has felt full of air after meals. "
        "I pass a lot of gas, sometimes feel swollen, and on some days I do not "
        "have a bowel movement for two or three days. I have no fever and I "
        "haven't lost weight.",
    )
    assert result["status"] != "IRRELEVANT"
