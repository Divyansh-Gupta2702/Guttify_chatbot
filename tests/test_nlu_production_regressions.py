import nlu_extractor
from guttify_agent import ConversationManager


def _local_only(monkeypatch):
    monkeypatch.setattr(nlu_extractor, "_get_llm", lambda: None)


def test_anal_itching_does_not_become_fissure(monkeypatch):
    _local_only(monkeypatch)
    bot = ConversationManager()
    sid = "anal-itching"
    result = bot.handle_message(sid, "I am feeling itching as well as some discomfort in my anal area")
    state = bot.sessions[sid].symptom_state
    assert result["status"] == "ASK"
    assert state.primary_symptom == "anal burning"
    assert state.itching is True
    assert state.anal_pain is not True


def test_age_answer_cannot_become_duration(monkeypatch):
    _local_only(monkeypatch)
    bot = ConversationManager()
    sid = "age-duration"
    bot.handle_message(sid, "I have stomach pain")
    bot.handle_message(sid, "2 weeks")
    result = bot.handle_message(sid, "34 years old")
    state = bot.sessions[sid].symptom_state
    assert state.age == 34
    assert state.duration == "2 weeks"
    assert result["status"] == "ASK"


def test_mismatched_answer_does_not_consume_stool_question(monkeypatch):
    _local_only(monkeypatch)
    bot = ConversationManager()
    sid = "mismatch-stool"
    for message in [
        "I have an anal fissure",
        "2 days",
        "34 years old",
        "no bleeding",
        "no pain",
        "no lump",
    ]:
        bot.handle_message(sid, message)
    result = bot.handle_message(sid, "no lump")
    assert result["status"] == "ASK"
    assert "hard stools" in result["message"].lower()
    assert bot.sessions[sid].last_question == "constipation"


def test_nlu_model_cannot_invent_duration_or_fissure(monkeypatch):
    class Response:
        content = '{"intent":"answer_question","symptoms":["anal fissures"],"pain":true,"itching":true,"age":34,"duration":"34 years","confidence":0.9}'

    class FakeLLM:
        def invoke(self, prompt):
            return Response()

    monkeypatch.setattr(nlu_extractor, "_get_llm", lambda: FakeLLM())
    facts = nlu_extractor._llm_extract(
        "I am feeling itching as well as some discomfort in my anal area",
        "duration",
        type("S", (), {"to_dict": lambda self: {}})(),
        "answer_question",
    )
    assert facts["symptoms"] == []
    assert facts["pain"] is None
    assert facts["duration"] is None
    assert facts["age"] is None
    assert facts["itching"] is True


def test_constipation_alias_consumes_plain_no_without_repeating(monkeypatch):
    """The legacy `constipation` question ID must use the same parser as stool_straining."""
    _local_only(monkeypatch)
    bot = ConversationManager()
    sid = "constipation-alias-no"
    session = bot._get_session(sid)
    session.last_question = "constipation"
    session.symptom_state.primary_symptom = "piles"
    result = bot.handle_message(sid, "no")
    state = bot.sessions[sid].symptom_state
    assert state.constipation_explicit is False
    assert state.straining is False
    assert result["status"] == "ASK"
    assert "hard stools" not in result["message"].lower() or "strain" not in result["message"].lower()


def test_constipation_alias_understands_natural_negative(monkeypatch):
    """Natural answers such as 'no strain, only normal pooping' become explicit negatives."""
    _local_only(monkeypatch)
    bot = ConversationManager()
    sid = "constipation-natural-negative"
    session = bot._get_session(sid)
    session.last_question = "constipation"
    session.symptom_state.primary_symptom = "piles"
    result = bot.handle_message(sid, "no strain, only normal pooping")
    state = bot.sessions[sid].symptom_state
    assert state.constipation_explicit is None or state.constipation_explicit is False
    assert state.straining is False
    assert result["status"] == "ASK"
    assert "make sure" not in result["message"].lower()


def test_constipation_alias_understands_yes_without_inventing_both_features(monkeypatch):
    """A bare yes confirms constipation but does not fabricate hard stools and straining."""
    _local_only(monkeypatch)
    bot = ConversationManager()
    sid = "constipation-natural-yes"
    session = bot._get_session(sid)
    session.last_question = "constipation"
    session.symptom_state.primary_symptom = "piles"
    bot.handle_message(sid, "yes")
    state = bot.sessions[sid].symptom_state
    assert state.constipation_explicit is True
    assert state.stool_form is None
    assert state.straining is None


def test_age_phrase_is_never_extracted_as_duration(monkeypatch):
    _local_only(monkeypatch)
    from nlu_extractor import extract_natural_facts
    from intent_parser import SymptomState
    facts = extract_natural_facts("32 years of age", "age", SymptomState(duration="2 weeks"))
    assert facts["age"] == 32
    assert facts["duration"] is None


def test_duration_parser_rejects_years_of_age():
    from intent_parser import extract_duration
    assert extract_duration("I am 32 years of age") is None
    assert extract_duration("I am 32 years old") is None
    assert extract_duration("this has lasted 2 years") == "2 years"
