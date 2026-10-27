# Keep this focused detector test runnable even when optional Groq dependencies
# are not installed in a lightweight test environment.
import sys
import types

if "langchain_groq" not in sys.modules:
    groq_stub = types.ModuleType("langchain_groq")
    groq_stub.ChatGroq = object
    sys.modules["langchain_groq"] = groq_stub

from multilingual import detect_input_language, translate_to_english


def test_detects_common_hinglish_symptom_phrases():
    examples = [
        "Mujhe acidity hoti hai",
        "Mere pet mein dard hai",
        "Khana khane ke baad gas hoti hai",
        "Mujhe kabz hai",
        "Pet phool raha hai",
    ]
    for message in examples:
        assert detect_input_language(message, "en") == "hi-latn", message


def test_detects_short_hinglish_contextual_answers():
    examples = ["haan", "han", "ji", "bilkul", "nahi", "raat ko", "subah", "do din se", "hafte se", "kabhi kabhi"]
    for message in examples:
        assert detect_input_language(message, "en") == "hi-latn", message


def test_keeps_ordinary_english_as_english():
    examples = ["I have stomach pain", "It started yesterday", "Yes, sometimes after meals"]
    for message in examples:
        assert detect_input_language(message, "en") == "en", message



def test_short_hinglish_answers_translate_without_groq():
    examples = {
        "nahi": "no",
        "Nahi": "no",
        "nhi": "no",
        "nahin": "no",
        "bilkul nahi": "no",
        "haan": "yes",
        "ji": "yes",
        "raat ko": "at night",
    }
    for message, expected in examples.items():
        assert translate_to_english(message, "hi-latn") == expected, message
