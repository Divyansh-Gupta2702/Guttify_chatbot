import json

import company_knowledge
import conversation_intelligence as ci
import research_assistant


def test_company_knowledge_returns_official_source_facts():
    facts = company_knowledge.retrieve_company_context("Guttify company history")
    assert facts
    assert any("2023" in item["fact"] for item in facts)
    assert all(item.get("source", "") for item in facts)


def test_company_knowledge_does_not_invent_unknown_policy_answer():
    facts = company_knowledge.retrieve_company_context("exact return policy refund period")
    assert not any(item["topic"] in {"refund_policy", "return_policy"} for item in facts)


def test_pubmed_sources_are_explicitly_linked():
    rendered = research_assistant.format_research_sources([{
        "title": "A test paper", "pubdate": "2025", "journal": "Test Journal",
        "authors": ["A Author"], "pmid": "12345", "url": "https://pubmed.ncbi.nlm.nih.gov/12345/",
        "abstract": "A test abstract.",
    }])
    assert "PMID: 12345" in rendered
    assert "A test abstract" in rendered
    assert "https://pubmed.ncbi.nlm.nih.gov/12345/" in rendered


def test_classifier_accepts_new_intents(monkeypatch):
    class Response:
        content = json.dumps({"intent": "company_information", "confidence": 0.97})
        response_metadata = {"finish_reason": "stop"}

    monkeypatch.setattr(ci, "_get_llm", lambda _tokens: object())
    monkeypatch.setattr(ci, "invoke_groq", lambda *args, **kwargs: Response())
    assert ci.classify_intent("Who founded Guttify?")["intent"] == "company_information"


def test_general_answer_does_not_return_unapproved_product_names(monkeypatch):
    monkeypatch.setattr(ci, "_get_llm", lambda _tokens: object())

    class Response:
        content = "Digest Boost is a good choice."
        response_metadata = {"finish_reason": "stop"}

    monkeypatch.setattr(ci, "invoke_groq", lambda *args, **kwargs: Response())
    assert ci.answer_general_question("Tell me a joke", product_names=["Digest Boost"]) == ci.SAFE_GENERAL_FALLBACK


def test_research_retrieval_failure_fails_closed(monkeypatch):
    def fail(*args, **kwargs):
        raise TimeoutError()
    monkeypatch.setattr(ci, "search_pubmed", fail)
    answer = ci.answer_research_question("research on dietary fibre")
    assert "couldn't retrieve scientific papers" in answer


def test_general_knowledge_intent_routes_without_starting_assessment(monkeypatch):
    import guttify_agent
    from guttify_agent import ConversationManager

    monkeypatch.setattr(guttify_agent, "classify_intent", lambda *a, **k: {"intent": "general_knowledge_question", "confidence": 0.99})
    monkeypatch.setattr(guttify_agent, "answer_general_question", lambda *a, **k: "A black hole is a region where gravity is so strong that light cannot escape.")
    manager = ConversationManager()
    result = manager.handle_message("expanded-general", "Explain black holes")
    assert result["status"] == "ANSWER"
    assert "black hole" in result["message"]
    assert manager._get_session("expanded-general").symptom_state.primary_symptom is None


def test_company_and_research_intents_use_separate_handlers(monkeypatch):
    import guttify_agent
    from guttify_agent import ConversationManager

    monkeypatch.setattr(guttify_agent, "classify_intent", lambda *a, **k: {"intent": "company_information", "confidence": 0.99})
    monkeypatch.setattr(guttify_agent, "answer_company_question", lambda *a, **k: "Guttify describes its science loop as Test, Interpret, Intervene, Track and Learn.")
    manager = ConversationManager()
    result = manager.handle_message("expanded-company", "What is Guttify's science loop?")
    assert result["status"] == "ANSWER"
    assert "Test, Interpret" in result["message"]
    assert manager._get_session("expanded-company").symptom_state.primary_symptom is None

    monkeypatch.setattr(guttify_agent, "classify_intent", lambda *a, **k: {"intent": "research_summary", "confidence": 0.99})
    monkeypatch.setattr(guttify_agent, "answer_research_question", lambda *a, **k: "Retrieved paper summaries are listed with PubMed citations.")
    result = manager.handle_message("expanded-research", "Summarize research on dietary fibre")
    assert result["status"] == "ANSWER"
    assert "PubMed citations" in result["message"]


def test_expanded_assistant_cannot_bypass_existing_red_flag_gate(monkeypatch):
    import guttify_agent
    from guttify_agent import ConversationManager

    def should_not_route(*args, **kwargs):
        raise AssertionError("LLM router must not run before deterministic safety gate")

    monkeypatch.setattr(guttify_agent, "classify_intent", should_not_route)
    manager = ConversationManager()
    result = manager.handle_message("expanded-red-flag", "I am vomiting blood")
    assert result["status"] == "SAFETY_REVIEW"
    assert result["recommendations"] == []
