from intent_parser import SymptomState
from nlu_extractor import extract_natural_facts
from guttify_agent import ConversationManager


def test_bloody_poops_is_detected_deterministically_as_bleeding():
    facts = extract_natural_facts("i am having bloody poops", None, SymptomState())
    assert facts["bleeding"] is True
    assert "bleeding" in facts["symptoms"]
    assert facts["intent"] == "assessment"
    assert facts.get("_resolver_source") != "model"


def test_bloody_stool_phrasings_are_normalized_to_bleeding():
    examples = [
        "bloody stool",
        "blood in my poop",
        "poop with blood",
        "stool with blood",
        "blood while pooping",
        "I am seeing blood in my stool",
    ]
    for message in examples:
        facts = extract_natural_facts(message, None, SymptomState())
        assert facts["bleeding"] is True, (message, facts)
        assert "bleeding" in facts["symptoms"], (message, facts)


def test_explicit_no_bloody_stool_does_not_become_positive_bleeding():
    facts = extract_natural_facts("I do not have blood in my stool", None, SymptomState())
    assert facts["bleeding"] is not True
    assert "bleeding" not in facts["symptoms"]


def test_bleeding_message_starts_assessment_not_irrelevant():
    manager = ConversationManager()
    result = manager.handle_message("bloody-poops-regression", "I am having bloody poops")
    assert result["status"] != "IRRELEVANT"
    assert result.get("recommendations", []) == []
    assert result["status"] in {"ASK", "SAFETY_REVIEW", "DIAGNOSIS"}
