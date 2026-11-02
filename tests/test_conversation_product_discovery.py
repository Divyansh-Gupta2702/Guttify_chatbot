from guttify_agent import ConversationManager
from recommendation_engine import products
from guttify_chatbot import _deterministic_product_reply


def test_liver_lift_lookup_then_instruction_followup_uses_catalog_data():
    manager = ConversationManager()
    first = manager.handle_message("product-followup", "What is Liver Lift?")
    assert first["status"] == "PRODUCT_INFO_FOUND"
    assert first["product"]["product_name"] == "Liver Lift"

    followup = manager.handle_message("product-followup", "Show me your instruction")
    assert followup["status"] == "PRODUCT_INFO_FOUND"
    assert followup["product"]["how_to_use"] == first["product"]["how_to_use"]
    reply = _deterministic_product_reply(followup["product"], "Show me your instruction")
    assert followup["product"]["how_to_use"] in reply
    assert "How to use Liver Lift" in reply


def test_product_followup_details_do_not_return_completed_recommendation_fallback():
    manager = ConversationManager()
    manager.handle_message("details-followup", "What is Liver Lift?")

    followup = manager.handle_message("details-followup", "I need more details")
    assert followup["status"] == "PRODUCT_INFO_FOUND"
    assert followup["product"]["product_name"] == "Liver Lift"


def test_general_gut_product_discovery_uses_active_catalog_without_diagnosis():
    manager = ConversationManager()
    result = manager.handle_message("browse-products", "What I can have for gut?")

    assert result["status"] == "PRODUCT_DISCOVERY"
    assert {p["product_name"] for p in result["products"]} == {
        p["product_name"] for p in products if p.get("status") == "active"
    }
    assert "specific symptom" in result["message"]
    assert not manager.sessions["browse-products"].symptom_state.primary_symptom


def test_symptom_framed_product_browse_is_not_started_as_diagnosis():
    manager = ConversationManager()
    result = manager.handle_message("browse-bloating", "Do you have anything for bloating?")

    assert result["status"] == "PRODUCT_DISCOVERY"
    assert result["products"]
    assert not manager.sessions["browse-bloating"].symptom_state.primary_symptom


def test_ambiguous_product_request_asks_before_recommending():
    manager = ConversationManager()
    result = manager.handle_message("ambiguous-take", "What should I take?")

    assert result["status"] == "ASK"
    assert "general Guttify product information" in result["message"]
    assert not result.get("recommendations")


def test_education_question_does_not_start_symptom_assessment():
    manager = ConversationManager()
    result = manager.handle_message("education", "What causes bloating?")

    assert result["status"] == "ASK"
    assert "general gut-health information" in result["message"]
    assert not manager.sessions["education"].symptom_state.primary_symptom


def test_product_list_first_item_reference_resolves_from_session_context():
    manager = ConversationManager()
    listed = manager.handle_message("browse-first", "What products do you have for gut health?")
    assert listed["status"] == "PRODUCT_DISCOVERY"

    selected = manager.handle_message("browse-first", "Tell me more about the first one")
    assert selected["status"] == "PRODUCT_INFO_FOUND"
    assert selected["product"]["product_name"] == listed["products"][0]["product_name"]


def test_headache_is_polite_out_of_scope_without_assessment():
    manager = ConversationManager()
    result = manager.handle_message("out-of-scope", "I have headache")

    assert result["status"] == "IRRELEVANT"
    assert "outside" in result["message"]
    assert not manager.sessions["out-of-scope"].symptom_state.primary_symptom


def test_unknown_product_name_is_not_invented():
    manager = ConversationManager()
    result = manager.handle_message("unknown-product", "What is Liver Rocket?")

    assert result["status"] != "PRODUCT_INFO_FOUND"


def test_unrecognized_message_gets_specific_clarification_prompt():
    manager = ConversationManager()
    result = manager.handle_message("gibberish", "Testug")

    assert result["status"] == "IRRELEVANT"
    assert result["message"] == (
        "I didn't quite understand that. Are you looking for information about a Guttify product or do you have a digestive health concern?"
    )
