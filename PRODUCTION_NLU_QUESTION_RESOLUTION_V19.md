# GutGPT Production NLU + Question Resolution Fix v19

## Scope
This release hardens the existing NLU -> question resolution -> state update pipeline without redesigning diagnosis, safety, or product recommendation logic.

## Changes
- Added a reusable question-aware resolver in `question_schema.py`.
- Added explicit `answered | unknown | unresolved` question status and deterministic confidence.
- Added `answered_unknown_fields` to conversation state so unknown answers resolve a question without becoming clinical true/false facts.
- Added deterministic recognition for yes/no/unknown variants, age, duration, Bristol stool forms, and food triggers.
- Added contextual ownership so bare yes/no only populates fields semantically represented by the active question.
- Hardened Groq response parsing for fenced JSON, preambles, structured content blocks, malformed JSON, and invalid fields.
- Enforced a maximum of one Groq NLU attempt per user message.
- Added production resolver/model/parse/confidence/state-preservation logging.
- Added repeated-clarification protection to prevent identical clarification loops.
- Preserved unrelated confirmed state while resolving the active question.
- Added comprehensive regression tests covering natural language, multi-fact answers, unknown answers, scalar answers, stool forms, food triggers, model parsing, duplicate-call prevention, and clarification loops.

## Validation
Full repository test suite:
- 244 passed
- 18 subtests passed

All existing diagnosis, safety, and product-routing tests remain green.
