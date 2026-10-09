# GutGPT NLU / Question-Answer Flow Fix

## Architecture preserved
User message -> NLU extraction -> state update -> existing question/rule engine -> diagnosis/recommendation.

The diagnosis, recommendation, and safety engines were not replaced.

## Changes
- Active `last_question` now has priority over generic keyword extraction.
- Deterministic question-specific extraction runs before LLM semantic extraction.
- Deterministic extraction remains authoritative for high-impact contextual answers and explicit negation.
- Multi-fact messages preserve all confidently identifiable facts.
- Added natural bowel-pattern handling including `normal`, `mixed`, constipation and diarrhea.
- Added contextual severity parsing including `5`, `5/10`, `around 5`, `I'd say 5`, and `rate it 5`.
- Added contextual worsening polarity so `no not getting worse` is false.
- Added contextual vomiting/fever parsing including `neither`, `not that I know of`, and mixed positive/negative answers.
- Ambiguous `yes` to meals-vs-bowel relationship remains unanswered and receives a concise clarification.
- Upper-stomach + meal relation can be extracted from one message.
- Required questions cannot be bypassed by the max-question fallback.
- Structured safety red flags still override question completeness.
- Groq JSON is cleaned before parsing and malformed/unavailable model output falls back to deterministic extraction.
- Added `[NLU][QUESTION_CONTEXT]`, `[NLU][RAW]`, `[NLU][QUESTION_RESOLUTION]`, `[NLU][STATE_UPDATE]`, `[NLU][FALLBACK]`, `[QUESTION][BLOCK]`, and `[SAFETY][BLOCK]` logging.
- Removed the 2,000-character application-level chat limit from `app.py`; Pydantic no longer imposes the previous 4,000-character request cap.

## Verification
- Requested acceptance tests: **11/11 passed**
- Existing regression suite: **146 passed, 18 subtests passed**
- Python syntax compilation: **passed**

- Fixed short-choice answers to the meals-vs-bowel question (`meals`, `food`, `eating`, `bowel movements`, `stool`, `poop`) so the question is not repeated.
- Added natural duration handling for hours, including `for like few hours`, `a couple of hours`, and `2-3 hours`.
- Extended duration-day conversion to understand hour-based durations.
