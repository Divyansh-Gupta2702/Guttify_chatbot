# GutGPT Codebase Scan — 2026-10-13

## Scope
Reviewed the supplied ZIP's Python backend, NLU/rule/recommendation modules, widget/frontend, configuration files, and existing pytest suite. This is a static review plus local tests, not a penetration test or proof of clinical safety.

## Changes applied
1. `app.py`: capped incoming chat messages using `MAX_MESSAGE_LENGTH` (default 4,000 characters; configurable within 256–10,000). This reduces oversized-input CPU/memory abuse.
2. `app.py`: bounded each active session's stored conversation history to 100 messages/entries (latest 100 list items), preventing history from growing indefinitely during a long-lived session.
3. Kept the existing deterministic diagnosis/recommendation flow and session behavior unchanged.

## Findings / remaining risks
### High priority — NLU state-consistency regressions
The supplied test suite has **8 failing tests** (293 passed, 18 subtests passed). All failures are in `tests/test_state_consistency_hardening.py` and involve:
- volunteered symptoms being dropped while another question is active;
- explicit symptom negatives not clearing stale state/primary symptom;
- canonical symptom flags not being set consistently;
- primary symptom duplicated in `secondary_symptoms`.

These were present in the supplied codebase and are **not fixed in this package**; the precise fix needs to be made in the contextual resolver/state merge path and verified against the entire questionnaire regression suite. Do not treat this build as fully regression-clean.

### Medium priority — abuse/rate limiting
There is no application-level rate limit for `/api/session` or `/api/chat`. Message size and per-session history are now bounded, but a distributed client can still create sessions or submit many requests. Add edge rate limiting at the hosting proxy/WAF (preferred) or a shared-store limiter before production traffic increases. Avoid relying on per-process counters in a multi-worker deployment.

### Medium priority — dependency pinning / supply-chain
`requirements.txt` uses unpinned dependencies. This makes builds non-reproducible and may pull breaking or vulnerable versions later. Pin tested versions and run a dependency vulnerability scanner in CI before deployment; versions were not automatically upgraded here to avoid an untested dependency change.

### Configuration checks
- `.env.example` contains a placeholder API key, not an actual secret.
- `.gitignore` excludes `.env`, but verify real keys have never been committed in repository history or pasted into logs.
- CORS is configured from `ALLOWED_ORIGINS`; production must use exact trusted storefront origins and must not use wildcard origins with credentials.
- The API keeps sessions in process memory. Multi-worker/replica deployments need shared session storage or guaranteed single-worker routing.

## Verification
- Python source files compile successfully.
- Pytest: 293 passed, 8 failed, 18 subtests passed.
- No dependency versions were changed, and no production API key was present in the supplied `.env.example`.


## Follow-up regression fixes (2026-10-13)

The eight failures in `tests/test_state_consistency_hardening.py` have now been fixed in `guttify_agent.py`. A deterministic volunteered-symptom reconciliation step preserves symptom disclosures while another question is active, applies explicit negative corrections to stale symptom state, promotes a remaining positive symptom when the previous primary is denied, sets canonical symptom fields (including gas and diarrhea), and removes the primary symptom from the secondary list. The reconciliation runs around the active-question resolver so legacy question parsing cannot reintroduce a false positive.

Validation after the fix:
- `python -m pytest -q --disable-warnings`: **301 passed, 18 subtests passed**.
- `python -m compileall -q .`: passed.

The broader security items listed above (including deployment-level rate limiting and dependency pinning) remain separate follow-up tasks; passing the regression suite is not a security certification.
