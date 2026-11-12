# GutGPT v18.4.2 — Individual questionnaire, profile age, and Bristol rendering

## Scope

This is a controlled revision of the existing v18.4.1 codebase. The questionnaire schema fingerprint is advanced from `v18.1` to `v18.2` to identify the new stable one-field question IDs. It preserves the deterministic clinical architecture, the 27 existing clinical outcome patterns, safety gates, PostgreSQL-only customer/assessment persistence, authentication/session protections, and product eligibility rules.

## Questionnaire flow

- Reworked the deterministic question queue to process the primary symptom and all explicitly reported secondary symptoms instead of stopping after the first branch.
- Reused existing state fields and added stable one-field question IDs for abdominal pain, pain/bowel relation, anal discomfort, sharp pain during stool, mucus, night symptoms, vomiting, fever, abdominal distension, swallowing difficulty, persistent vomiting, vomiting blood, constipation, diarrhea, gas, and bloating.
- Replaced newly emitted composite symptom questions with individual prompts. Existing composite question IDs and component resolvers remain available for old PostgreSQL checkpoints and backward compatibility.
- Added explicit individual gas and bloating screening so one is never inferred from the other.
- Reused already answered shared fields across symptom branches; no stale assessment-specific values are carried into a new assessment.
- Raised the deterministic maximum question ceiling from 15 to 40 to accommodate several confirmed symptom branches while retaining a hard upper bound. Conditional fields remain skipped when already known or not applicable.

## Customer age

- Validated profile age when loading a customer during registration and restoration. Whole-number ages 1–120 are accepted; fractional, zero, negative, boolean, null, and out-of-range values are rejected consistently by the API, resolver, and age extractor.
- Reconciled PostgreSQL `customers.age` with an assessment checkpoint during resume; valid profile age wins over null/stale checkpoint age.
- Copied the validated profile age into a fresh `SessionState` when a returning customer explicitly starts a new assessment, before the initial PostgreSQL checkpoint is written.
- Persisted a newly supplied required age or explicit summary age correction back to the authenticated customer's PostgreSQL profile. If persistence fails, the session age is reverted and the assessment pauses for retry.
- Kept age as a customer-profile attribute; no competing age field or schema migration was introduced.

## Bristol Stool Chart

- Kept the chart bound to the `stool_form` question ID, not diagnosis labels or text matching.
- Ensured constipation, diarrhea, gas/bloating, piles/fissure, and bleeding branches use the stool-form question when stool consistency is required.
- Added backward-compatible `question_metadata.display_asset` to chat responses and structured asset metadata to restored pending questions.
- Preserved chart metadata during resume and clarification; prevented duplicate chart prompts when the transcript already contains the active question.
- Added a same-origin API asset route at `/assets/bristol-stool-chart.png` that serves the exact `Bristol Stool Chart Infographic.png` shipped in the archive with `image/png` content type and safe cache headers.
- The widget derives the asset URL from the configured GutGPT API origin, so it does not resolve relative to the Shopify host page or depend on a local development path.
- Added a safe image-load failure handler. The broken image element is removed and an accessible fallback message remains alongside the type-selection buttons.
- Chart selection still submits `Bristol type N`; the existing deterministic stool-form parser maps it to the existing 1–7 value.

## Database / security / clinical integrity

- No database migration.
- No database drop, recreation, or data deletion.
- PostgreSQL remains required for customer and assessment persistence; JSON-file fallback remains disabled.
- No changes to JWT verification, customer binding, token rotation, rate limiting, session lifecycle protection, safety checker, clinical rule engine, product catalog, or recommendation eligibility.
- Digest Boost and Poopie diarrhea restrictions remain in the unchanged recommendation engine.

## Tests added or updated

- Added independent-question ownership and multi-symptom sequencing regression coverage.
- Added Bristol backend/widget rendering contract checks, including asset metadata, fallback, and duplicate prevention.
- Extended profile-age reconciliation coverage to include fresh assessment initialization.
- Updated existing conversation fixtures to answer the new one-field question IDs rather than obsolete composite prompts.

## Verification status

At the time of the original release package, the test suite had not yet been executed. A repository revalidation on 2026-11-12 ran `python -m pytest tests -q --tb=no --basetemp=.pytest-tmp`: **688 passed, 8 skipped, and 28 subtests passed**. The skipped PostgreSQL integration tests require a disposable `GROQ_TEST_DATABASE_URL`.

Actual PostgreSQL restore/new-assessment behavior, production HTTPS asset delivery, and Shopify browser rendering still require a staging environment.

## Repository audit follow-up (2026-11-12)

- Production startup now fails when the selected provider key is missing or uses an obvious `.env.example` placeholder. Gemini also requires `GEMINI_PAID_TIER_CONFIRMED=true`.
- The Docker image now upgrades to the pinned pip version and installs `requirements.lock.txt` for repeatable dependency resolution.
- Added `CUSTOMER_CHAT_STATE_MIGRATION.md` to document the startup schema migration and its backup/staging requirements.
- Updated this note and `AUDIT_IMPLEMENTATION_REPORT.md` with the current test results and staging-only verification limits.
