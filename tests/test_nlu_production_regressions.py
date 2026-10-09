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
