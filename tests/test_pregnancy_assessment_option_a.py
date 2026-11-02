from guttify_agent import ConversationManager


def test_pregnancy_caution_allows_explicit_fresh_assessment():
    manager = ConversationManager()
    sid = "pregnancy-option-a"

    caution = manager.handle_message(sid, "I am pregnant")
    assert caution["status"] == "SAFETY_REVIEW"
    assert manager.sessions[sid].pregnancy_lactation_caution is True

    started = manager.handle_message(sid, "Please start a new digestive assessment")
    assert started["status"] == "ASK"
    assert "What digestive symptom" in started["message"]
    assert manager.sessions[sid].pregnancy_lactation_caution is True
    assert manager.sessions[sid].symptom_state.primary_symptom is None


def test_pregnancy_caution_does_not_allow_product_recommendations():
    manager = ConversationManager()
    sid = "pregnancy-product-block"
    manager.handle_message(sid, "I am pregnant")
    manager.handle_message(sid, "Start a digestive assessment")

    result = manager._remember_recommendation(
        manager.sessions[sid],
        {"status": "RECOMMENDATION_FOUND", "recommendations": [{"product_name": "Example"}]},
    )
    assert result["status"] == "SAFETY_REVIEW"
    assert result["recommendations"] == []
    assert result["safety"]["red_flag"] is False


def test_pregnancy_caution_is_not_cleared_by_assessment_reset():
    manager = ConversationManager()
    sid = "pregnancy-caution-persists"
    manager.handle_message(sid, "I am pregnant")
    manager.handle_message(sid, "Start a new gut-health assessment")
    assert manager.sessions[sid].pregnancy_lactation_caution is True
