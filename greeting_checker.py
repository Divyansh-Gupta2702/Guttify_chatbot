"""
Guttify Greeting Checker
------------------------
Recognizes a plain greeting ("hi", "hello", "yo", "what's up", "good
morning", etc.) so the assistant responds warmly instead of treating it as
gibberish or an off-topic/irrelevant message.

Intentionally strict: it only matches when the ENTIRE message (after
stripping punctuation/whitespace) is just a greeting, so "hi, I have
bloating" still flows into the normal symptom conversation rather than
being swallowed here.
"""
import random
import re

GREETING_PATTERNS = [
    r"hi+",
    r"hello+",
    r"hey+a?",
    r"yo+",
    r"sup",
    r"wa+s+up",
    r"what'?s up",
    r"whats up",
    r"howdy",
    r"greetings",
    r"hola",
    r"namaste",
    r"good\s?(morning|afternoon|evening|day)",
    r"(hi|hello|hey|yo)\s?(there|guttify|guys|team)?",
]

_COMPILED = re.compile(r"^(" + "|".join(GREETING_PATTERNS) + r")[!.\s]*$")

GREETING_RESPONSES = [
    "Hey there! I'm Guttify's product assistant. What's going on with your gut today?",
    "Hi! Happy to help — tell me what you're experiencing and I'll point you to the right product.",
    "Hello! What symptom or concern can I help you with today?",
    "Hey! I'm here to help with Guttify products — what's bothering you?",
    "Hi there! Tell me a bit about what you're experiencing and I'll find the best fit for you.",
]


def is_greeting(text):
    """Return True if `text`, on its own, is just a greeting."""
    cleaned = re.sub(r"[^a-zA-Z'\s]", " ", text).strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return False
    return bool(_COMPILED.match(cleaned))


def random_greeting_response():
    return random.choice(GREETING_RESPONSES)
