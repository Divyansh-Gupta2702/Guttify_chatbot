from support_footer import append_human_support_footer, HUMAN_SUPPORT_FOOTER


def test_completed_assessment_footer_includes_customer_support_contacts():
    reply = append_human_support_footer("Your assessment result is ready.")
    assert "For human support, contact Customer Support:" in reply
    assert "📧 Email: guttify01@gmail.com" in reply
    assert "📞 Phone: +91 9818693589" in reply


def test_footer_is_not_duplicated():
    reply = "Your assessment result is ready." + HUMAN_SUPPORT_FOOTER
    assert append_human_support_footer(reply).count("guttify01@gmail.com") == 1
    assert append_human_support_footer(reply).count("+91 9818693589") == 1
