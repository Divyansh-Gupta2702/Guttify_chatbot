
import pytest

import nlu_extractor
from guttify_agent import ConversationManager


def _local_only(monkeypatch):
    monkeypatch.setattr(nlu_extractor, "_get_llm", lambda: None)


def _active(monkeypatch, sid, question):
    _local_only(monkeypatch)
    bot = ConversationManager()
    session = bot._get_session(sid)
    session.last_question = question
    session.symptom_state.primary_symptom = "piles"
    return bot, session


def test_constipation_bare_no_is_resolved(monkeypatch):
    bot, session = _active(monkeypatch, "neg-1", "constipation")
    result = bot.handle_message("neg-1", "no")
    assert session.symptom_state.constipation_explicit is False
    assert session.symptom_state.straining is False
    assert result["status"] != "AMBIGUOUS"
    assert session.last_question != "constipation"


@pytest.mark.parametrize(
    "answer",
    ["I'm not constipated", "no, I don't have constipation"],
)
def test_constipation_natural_negatives_are_resolved(monkeypatch, answer):
    bot, session = _active(monkeypatch, "neg-const-" + str(len(answer)), "constipation")
    result = bot.handle_message("neg-const-" + str(len(answer)), answer)
    assert session.symptom_state.constipation_explicit is False
    assert result["status"] != "AMBIGUOUS"
    assert session.last_question != "constipation"


def test_anal_pain_negative(monkeypatch):
    bot, session = _active(monkeypatch, "neg-anal", "anal_pain")
    result = bot.handle_message("neg-anal", "no pain")
    assert session.symptom_state.anal_pain is False
    assert result["status"] != "AMBIGUOUS"
    assert session.last_question != "anal_pain"


def test_lump_negative_alias(monkeypatch):
    bot, session = _active(monkeypatch, "neg-lump", "lump_or_prolapse")
    result = bot.handle_message("neg-lump", "no lump")
    assert session.symptom_state.lump_or_prolapse is False
    assert result["status"] != "AMBIGUOUS"


def test_bleeding_negative_alias(monkeypatch):
    bot, session = _active(monkeypatch, "neg-blood", "bleeding")
    result = bot.handle_message("neg-blood", "no blood")
    assert session.symptom_state.blood_present is False
    assert result["status"] != "AMBIGUOUS"


def test_weight_loss_negative(monkeypatch):
    bot, session = _active(monkeypatch, "neg-weight", "weight_loss")
    result = bot.handle_message("neg-weight", "no, I haven't lost weight")
    assert session.symptom_state.weight_loss is False
    assert result["status"] != "AMBIGUOUS"


def test_hard_stools_negative(monkeypatch):
    bot, session = _active(monkeypatch, "neg-hard", "hard_stools")
    result = bot.handle_message("neg-hard", "my stools aren't hard")
    assert session.symptom_state.hard_stools is False
    assert result["status"] != "AMBIGUOUS"


def test_straining_negative(monkeypatch):
    bot, session = _active(monkeypatch, "neg-strain", "straining")
    result = bot.handle_message("neg-strain", "I don't strain")
    assert session.symptom_state.straining is False
    assert result["status"] != "AMBIGUOUS"


def test_bare_no_does_not_become_duration_false(monkeypatch):
    bot, session = _active(monkeypatch, "neg-duration", "duration")
    result = bot.handle_message("neg-duration", "no")
    assert session.symptom_state.duration == "unknown"
    assert result["status"] == "ASK"
    assert session.last_question == "duration"
    assert result["status"] != "AMBIGUOUS"


def test_bare_no_medications_is_resolved(monkeypatch):
    bot, session = _active(monkeypatch, "neg-med-bare", "medications")
    result = bot.handle_message("neg-med-bare", "no")
    assert session.symptom_state.medications == "none"
    assert session.last_question != "medications"
    assert result["status"] != "AMBIGUOUS"


def test_bare_no_reflux_is_resolved(monkeypatch):
    bot, session = _active(monkeypatch, "neg-reflux", "reflux")
    result = bot.handle_message("neg-reflux", "no")
    assert session.symptom_state.reflux_present is False
    assert session.last_question != "reflux"
    assert result["status"] != "AMBIGUOUS"


def test_bare_no_timing_is_not_resolved(monkeypatch):
    bot, session = _active(monkeypatch, "neg-timing", "timing")
    result = bot.handle_message("neg-timing", "no")
    assert session.symptom_state.night_time_symptoms is None
    assert session.last_question == "timing"
    assert result["status"] == "ASK"


def test_bare_no_triggers_is_resolved(monkeypatch):
    bot, session = _active(monkeypatch, "neg-triggers", "triggers")
    result = bot.handle_message("neg-triggers", "no")
    assert session.symptom_state.food_related is False
    assert session.last_question != "triggers"
    assert result["status"] != "AMBIGUOUS"


def test_bare_no_swallowing_resolves_all_negative_subfields(monkeypatch):
    bot, session = _active(monkeypatch, "neg-swallow", "swallowing")
    result = bot.handle_message("neg-swallow", "no")
    assert session.symptom_state.difficulty_swallowing is False
    assert session.symptom_state.persistent_vomiting is False
    assert session.symptom_state.vomiting_blood is False
    assert session.last_question != "swallowing"
    assert result["status"] != "AMBIGUOUS"
