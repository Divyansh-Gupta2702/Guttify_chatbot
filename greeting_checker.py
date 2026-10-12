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
    r"hiya",
    r"yo+",
    r"sup",
    r"wa+s+up",
    r"what'?s up",
    r"whats up",
    r"what is up",
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
    "Hi! 👋 I'm GutGPT. How can I help with your gut health today?",
    "Hey there! 😊 What's bothering your stomach today?",
    "Hello! 👋 Tell me what you're experiencing, and I'll help you figure it out.",
    "Hi! 😊 How are you feeling today?",
    "Hey! I'm GutGPT. What gut or digestive issue are you dealing with?",
    "Hi! 👋 I'm GutGPT. Tell me about your symptoms and I'll guide you from there.",
    "Hello! Let's understand what's going on with your digestion. What symptoms are you experiencing?",
    "Hi there! 👋 Having trouble with your gut? Tell me what you've been experiencing.",
    "Hello! I can help you understand your digestive symptoms. What's bothering you?",
    "Hey! 👋 Let's get to the bottom of what's troubling your gut. What are you feeling?",
    "Hey! 👋 What's going on with your tummy?",
    "Hi! Tell me what's been bothering your stomach lately.",
    "Hey there! 😊 Bloated, acidic, constipated, or something else?",
    "Hi! 👋 What's your gut telling you today?",
    "Hello! 😊 Start by telling me your main symptom.",
    "Welcome to GutGPT 💜 Let's understand what's going on with your gut.",
    "Hi! 👋 Welcome to GutGPT. Tell me your symptoms and let's get started.",
    "Welcome! 💜 I'm GutGPT, your gut-health assistant. How can I help today?",
    "Hey! 👋 You're in the right place. Tell me what's troubling your digestion.",
    "Welcome to GutGPT! 🌿 What digestive issue would you like help with today?"
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
