"""Customer support footer for completed GutGPT assessments."""

HUMAN_SUPPORT_FOOTER = (
    "\n\nFor human support, contact Customer Support:\n"
    "📧 Email: guttify01@gmail.com\n"
    "📞 Phone: +91 9818693589"
)


def append_human_support_footer(reply: str) -> str:
    """Add support details once to a completed assessment reply."""
    reply = (reply or "").rstrip()
    if "guttify01@gmail.com" in reply or "+91 9818693589" in reply:
        return reply
    return reply + HUMAN_SUPPORT_FOOTER
