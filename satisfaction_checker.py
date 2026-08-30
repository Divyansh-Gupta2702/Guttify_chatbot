"""
Guttify Satisfaction / Closing Checker
---------------------------------------
Detects when the user is signaling that they're satisfied with a
recommendation and the conversation can be wrapped up, so the assistant
closes out gracefully instead of leaving the session open indefinitely.

Only used AFTER a product recommendation (or named-product answer) has
already been delivered in the session — see `awaiting_close` in
guttify_agent.py. It is never used to end a conversation that hasn't
produced a recommendation yet.

Intentionally strict, mirroring greeting_checker.py: it only matches when
the ENTIRE message (after stripping punctuation) is a closing/thanks-style
remark, so "thanks, but does it work for kids too?" or "thanks, what about
bloating too?" still flows into the normal conversation instead of ending
it. Only a message that is *purely* a closing remark ends the chat.
"""
import random
import re

# A trailing (or standalone) expression of gratitude.
_GRATITUDE_CORE = r"thanks?( you)?( so much| a lot| a ton| very much)?|appreciate it|ty|thx"
PURE_GRATITUDE_RE = re.compile(r"^(" + _GRATITUDE_CORE + r")$")
GRATITUDE_SUFFIX_RE = re.compile(r"\s+(" + _GRATITUDE_CORE + r")$")

# Single closing/acknowledgement words that are often stacked together
# ("ok great", "cool, perfect thanks") — matched as a repeatable group so
# any run of these still counts as pure closing, not just one at a time.
_ACK_WORD = r"(ok(ay)?|alright|cool|great|perfect|awesome|nice|sure)"
_ACK_RUN = _ACK_WORD + r"(,?\s+" + _ACK_WORD + r")*"

# Short closing/acknowledgement remarks, once any trailing "thanks" has
# been stripped off.
CORE_CLOSING_PATTERNS = [
    _ACK_RUN,
    r"sounds good",
    r"sounds great",
    r"got it",
    r"i'?m good",
    r"im good",
    r"all good",
    r"i'?m all set",
    r"that'?s (helpful|great|perfect|all|it)",
    r"this (helps|helped)( a lot)?",
    r"that (helps|helped)( a lot)?",
    r"no( further| more)? questions?",
    r"no,? that'?s all( for now)?",
    r"that'?s all i needed",
    r"will (try|do) (that|it)",
    r"no,? i'?m (good|all set)",
]
_CORE_RE = re.compile(r"^(" + "|".join(CORE_CLOSING_PATTERNS) + r")$")

CLOSING_RESPONSES = [
    "Glad that helped! This chat will close out now — feel free to start a new one anytime you have another gut-health question. Take care!",
    "You're welcome! I'll wrap up here — just start a fresh conversation whenever you need more help. Take care!",
    "Happy to help! Closing this chat now — start a new one anytime for more Guttify questions.",
]


def is_satisfied_closing(text):
    """Return True if `text`, taken as a whole, is just a closing/thanks
    remark (nothing else meaningful in it)."""
    cleaned = re.sub(r"[^a-zA-Z'\s]", " ", text).strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return False

    if PURE_GRATITUDE_RE.match(cleaned):
        return True

    core = GRATITUDE_SUFFIX_RE.sub("", cleaned)
    return bool(_CORE_RE.match(core))


def random_closing_response():
    return random.choice(CLOSING_RESPONSES)
