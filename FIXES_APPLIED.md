# GutGPT verified-audit fixes

This patch is based on the supplied ZIP and only addresses findings reproduced or directly verified in the code during the audit. The original uploaded ZIP was not modified.

## Changes applied

1. **Red-flag state persists across turns (B1).** Raw-message red flags are saved in `symptom_state.red_flags`, mark the session complete for routine diagnosis, and keep returning a safety response on subsequent turns. A later downplaying message cannot restart routine recommendations in that chat.
2. **Blood presence cannot be overwritten by a broad negation regex (B2).** Removed the generic blood/bleeding false assignment from the post-merge explicit-negatives block. Blood state remains owned by the active-question/contextual resolver. The explicit weight-loss negative handling remains.
3. **Red-flag negation is clause-aware (B3).** Punctuation and conjunctions split clauses before local negation is evaluated. Added coverage for comma-separated symptoms, “No, I have black stool,” negated fainting, and bleeding with lightheadedness. Added “bloody stool” as an explicit bleeding phrase.
4. **Pregnancy/lactation caution is context-aware (B4).** Negated/corrected statements and clear third-party mentions no longer activate the current user's session-long caution; affirmative self-disclosures still do.
5. **Recommendation completion state is consistent (B5).** The common recommendation-finalization helper now marks the assessment complete after its active-question invariant passes, enabling intended persistence for completed product-concern recommendations.
6. **Urgent outcomes are sent to persistence (B6).** The chat endpoint now calls persistence for urgent `SAFETY_REVIEW` outcomes. The persistence guard permits these urgent outcomes even though a clinical questionnaire may still have pending fields.
7. **Unknown bleeding answers do not satisfy safety discriminators (P4).** Unknown status no longer counts as completion for blood presence, blood colour/location/mucus, anal pain, or lump/prolapse questions. This prevents a product recommendation from treating an unknown bleeding discriminator as a negative.
8. **Slow NLU work no longer holds one global conversation lock (P2).** A per-session lock serializes each conversation while the shared lock is held only briefly to obtain that lock. Other sessions can proceed while one session waits for NLU/network work.
9. **Health text is not logged verbatim (S2).** Removed the INFO log containing raw user messages; only redacted message-length telemetry is emitted at DEBUG.
10. **Sensitive files are excluded from Docker build context (S1).** `.dockerignore` now excludes dump files, customer JSON data, backups, logs, and common secret directories.
11. **Session-storage documentation matches the widget (D1).** README now documents `sessionStorage` and clarifies that it survives refreshes in the same tab but not reliably across visits/tabs.

## Verification

- `python -m py_compile *.py`: passed.
- `PYTHONPATH=. pytest -q tests/test_verified_audit_fixes.py tests/test_state_consistency_hardening.py tests/test_bleeding_priority_v20.py`: **37 passed**.
- Tests that import `app.py` could not be collected in this environment because `langchain_core` is not installed. Therefore, urgent persistence and API-level behavior were statically checked but not runtime-verified here.
- No live Groq, PostgreSQL, or deployed-service tests were run.

## Remaining unverified findings

The report's other deployment-dependent or not-reproduced findings (LLM-generated negative grounding, request idempotency, proxy-aware IP rate limiting, session re-registration, concurrent PostgreSQL snapshot writes, age/minor eligibility, dependency/frontend vulnerability checks, and broader uninspected modules) are not represented as fixed in this patch.

## Safety note

Red flags are intentionally sticky for the life of a conversation. A user who corrects a false alarm should start a new chat for a fresh assessment; this conservative behavior should be reviewed against the product's intended clinical policy before deployment.
