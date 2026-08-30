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
        # Nothing alphabetic at all (numbers, symbols, emoji only)
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
