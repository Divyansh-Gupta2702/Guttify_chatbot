"""
Guttify Gibberish Checker
-------------------------
A lightweight, heuristic-only check for keyboard-mash / nonsense input
("asdkjhasd", "qwertyuiop"). This is NOT a language model and it is NOT
trying to be perfect — it's a cheap first filter that lets us skip the
LLM call entirely and reply with something light instead of pretending
to find a product match for noise.

Heuristics used:
1. Vowel ratio — real English words are usually >15% vowels by letter.
2. Long consonant runs (5+ in a row) — very rare in real English.
3. Known keyboard-row substrings ("qwerty", "asdf", etc).
"""
import random
import re

GIBBERISH_RESPONSES = [
    "Is that a cat on the keyboard? \U0001F63E\u2328\uFE0F Try telling me what's going on with your gut.",
    "I think a squirrel just ran across your keyboard. What are you experiencing?",
    "That didn't quite parse as English on my end — mind trying again?",
    "My symptom-decoder just threw an error on that one. Could you rephrase?",
    "Couldn't find a real word in there! What's bothering your stomach today?",
    "I didn't quite catch that 😊 Could you tell me a little more about what you're feeling?",
    "Oops! I'm not sure I understood that. Could you describe your symptoms in a few words?",
    "I'm having a little trouble understanding that message. Let's try again — what's bothering you?",
    "I want to make sure I understand you correctly. Could you rephrase that for me?",
    "Sorry, I couldn't make sense of that message. Tell me what's been troubling your stomach or digestion.",
    "Hmm, I didn't quite get that. Are you experiencing any digestive discomfort today?",
    "Let's try that once more 😊 What symptoms have you been noticing?",
    "I may have misunderstood you. Could you explain what you're experiencing in simple words?",
    "I'm here to help! Could you tell me what doesn't feel right?",
    "That message wasn't quite clear to me. Are you having acidity, bloating, constipation, or something else?",
    "I didn't understand that one, but no worries! Tell me what's bothering you, and we'll take it step by step.",
    "Could you say that another way? I'd like to understand your concern before moving forward.",
    "I'm not sure what you mean just yet. What changes or discomfort have you noticed in your digestion?",
    "Let's start fresh 😊 In your own words, how have you been feeling?",
    "I couldn't identify your concern from that message. Could you share a little more detail?",
    "I'm listening! Could you tell me what symptoms you're experiencing?",
    "Sorry, that didn't come through clearly. What would you like help with today?",
    "I want to give you the most relevant guidance possible. Could you clarify your message?",
    "I'm not able to understand that response. Try describing your concern, even in just a few words.",
    "No worries if it's difficult to explain. You can start with something simple, like 'I feel bloated' or 'I have acidity.'",
    "I didn't quite follow that. Is your concern related to your stomach, bowel movements, or something else?",
    "Let's make this easier 😊 Tell me the main problem you're experiencing, and we'll go from there.",
    "I'm having trouble interpreting that. Could you describe how you're feeling rather than using abbreviations?",
    "I couldn't understand that message. A short description of your symptoms would help me guide you better.",
    "I may have missed what you meant. Could you try sending your message again?",
]

VOWELS = set("aeiouy")
MIN_VOWEL_RATIO = 0.15
MIN_LETTERS_TO_JUDGE = 3
CONSONANT_RUN_PATTERN = re.compile(r"[bcdfghjklmnpqrstvwxz]{5,}")
KEYBOARD_PATTERNS = ["qwerty", "asdf", "zxcv", "hjkl", "wasd", "jkl;"]


def is_gibberish(text):
    """Return True if `text` looks like keyboard mash rather than words."""
    cleaned = re.sub(r"[^a-zA-Z\s]", "", text).strip()

    if not cleaned:
        # Numeric answers such as age ("23") are valid questionnaire input.
        if re.search(r"\d", text):
            return False
        return True

    lowered = cleaned.lower()
    if any(pattern in lowered for pattern in KEYBOARD_PATTERNS):
        return True

    words = lowered.split()
    all_letters = "".join(words)
    if len(all_letters) < MIN_LETTERS_TO_JUDGE:
        # Too short to judge fairly (e.g. "hi", "ok") — let it through.
        return False

    # Check each word on its own so a consonant-heavy word next to another
    # word (e.g. "gerd symptoms") doesn't get falsely joined into one run.
    if any(CONSONANT_RUN_PATTERN.search(word) for word in words):
        return True

    vowel_ratio = sum(1 for c in all_letters if c in VOWELS) / len(all_letters)
    return vowel_ratio < MIN_VOWEL_RATIO


def random_gibberish_response():
    return random.choice(GIBBERISH_RESPONSES)
