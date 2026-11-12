# GutGPT v18.4.2 — Full questionnaire, age, and Bristol implementation report

**Package status:** Implementation package prepared for review. No production deployment performed. At the time this report was first written, the test suite had not yet been run. A repository revalidation on 2026-11-12 subsequently ran the full suite; current results are recorded in Section 6.

## 1. Source baseline and constraints

- Source archive: `codebase-1.zip`
- Specification: supplied 30-page `Untitled document.pdf`
- Previous code version: `18.4.1-provider-safety-hardening`
- Package version: `18.4.2-individual-question-age-bristol`
- Questionnaire schema fingerprint: `v18.2` (previously `v18.1`)
- Deployment target described by the project: Ubuntu 24.04, PostgreSQL, Gunicorn, Nginx, FastAPI, Shopify embedded widget.

The implementation preserves the existing flow:

```text
User message
  -> NLU extraction
  -> contextual question resolution
  -> state update
  -> deterministic question/rule engine
  -> safety checks
  -> deterministic diagnosis
  -> recommendation eligibility
```

The LLM remains subordinate to the deterministic clinical engine.

## 2. Root causes and implemented corrections

### 2.1 Combined symptom questions and lost secondary branches

**Root causes found in the source:**

1. `symptom_questionnaire.next_question()` selected a single branch from `state.primary_symptom`. Explicitly reported `secondary_symptoms` were stored but their branch-specific follow-ups were not consistently queued.
2. Several existing question IDs owned multiple state fields (`stool_straining`, `bloating_pain`, `pain`, `blood_mucus`, `night_weight_fever`, `vomiting_fever`, `vomiting_fever_swelling`, `swallowing`, `weight_swallow`, `pain_relation`, and `bowel_pattern`).
3. On initial emission, the agent did not always bind the first prompt of a legacy composite question to its exact active component. A short `yes`/`no` could therefore be treated as ambiguous and trigger clarification loops.
4. The existing 15-question ceiling could prevent the questionnaire from finishing several explicitly reported symptom branches.

**Changes:**

- Reworked `next_question()` to queue the primary symptom and all explicitly reported secondary symptom branches. Bleeding remains first whenever `blood_present` is positively established.
- Added stable one-field question IDs that reuse existing state fields. Newly emitted questions now separately ask about hard/loose stool consistency, straining, incomplete evacuation, abdominal pain, pain relation to bowel movements, anal discomfort, sharp pain during stool, mucus, night symptoms, vomiting, fever, abdominal distension, swallowing difficulty, persistent vomiting, vomiting blood, constipation, diarrhea, gas, and bloating.
- Gas and bloating are independently screened; neither is inferred from the other.
- Replaced composite questions in the new questionnaire with one-field questions. Old composite IDs and `_CLARIFICATION_COMPONENTS` remain in `question_schema.py` for previously saved PostgreSQL checkpoints and backward compatibility.
- Reuses existing state values across branches so shared information is not unnecessarily requested again.
- Raised `MAX_QUESTIONS` from 15 to 40. This remains a hard deterministic ceiling but accommodates multiple confirmed symptoms. Conditional branches still skip fields that are already known or not applicable.
- On legacy composite IDs, the agent now binds the first component prompt before accepting a bare yes/no. This preserves older in-progress assessments without requiring a migration.

### 2.2 Repeated age questions

**Root causes found in the source:**

1. `/api/customer/restore` loaded the customer age into the session, but `/api/customer/resume` reconstructed a new session from an assessment checkpoint. A null or stale checkpoint age could replace the profile value.
2. `/api/session/new-assessment` created a fresh `SessionState` but did not copy the registered customer's age into it before saving the initial assessment checkpoint. This caused a returning customer to be asked for age again when starting a new assessment.

**Changes:**

- Added `_validated_customer_age()` and `_reconcile_restored_profile_age()` to centralize valid age handling (whole-number integer 1–120; booleans, null, empty, fractional, zero, negative, and out-of-range values are invalid). The question resolver and natural-language age extractor enforce the same whole-number/range rule.
- Assessment resume reads `customers.age` from PostgreSQL and reconciles it against the assessment snapshot. A valid customer profile age takes precedence; if the profile age is invalid/missing, a valid checkpoint snapshot is retained.
- Registration and customer restoration now place only a validated profile age into the active session.
- New assessment creation copies the validated PostgreSQL customer age into the new session before writing the initial checkpoint.
- When a customer answers a required age question or explicitly corrects age in the summary/correction flow, the API updates `customers.age` for the authenticated customer bound to that session. Invalid values are rejected; if the profile update fails, the session age is reverted and the assessment pauses for a retry rather than claiming the correction was saved.
- No competing age field was introduced. Age remains a customer-profile attribute, with the existing assessment snapshot preserved where the current state model uses it.

### 2.3 Bristol Stool Chart inconsistently displayed

**Root causes found in the source:**

1. The chart marker was inserted only by the normal `stool_form` question path. The clarification fallback text did not always include the marker.
2. The resume API returned the saved transcript but did not always return the deterministic pending prompt. The widget therefore could restore a session without restoring an unappended stool-form question.
3. The widget rendered an embedded image that did not match the separate `Bristol Stool Chart Infographic.png` asset shipped in the ZIP.
4. The rendering trigger depended on a text marker and did not have explicit API question metadata or a graceful image-load failure path.

**Changes:**

- Chart display is bound to the `stool_form` question ID only. The new questionnaire uses that question whenever it asks the user to identify stool consistency. Unrelated questions and diagnoses do not trigger the chart.
- Added the FastAPI asset route `/assets/bristol-stool-chart.png`, serving the exact shipped PNG with `image/png` content type and safe cache headers.
- The widget derives the asset URL from `GUTGPT_API_URL`, so it does not resolve relative to the Shopify host page and does not depend on a local development path.
- Added backward-compatible `ChatResponse.question_metadata` and structured `pending_question` metadata on resume. `display_asset` is set only when the active question ID is `stool_form`.
- Clarification fallback for legacy `stool_form` questions retains the marker. Resume restores the pending question and active component; duplicate transcript prompts are enriched in place rather than appended twice.
- Added an image error handler that logs a safe diagnostic, removes the failed image element, and displays a readable fallback message. Bristol type buttons remain available.
- Existing type-button submissions (`Bristol type 1` through `Bristol type 7`) and existing stool-form parsing/state values are unchanged.

## 3. Changed files

### Backend and widget

- `app.py`
  - Version updated to v18.4.2 and questionnaire schema fingerprint updated to v18.2.
  - Added Bristol PNG asset route.
  - Added validated age reconciliation during profile restore and assessment resume.
  - Added profile-age propagation to fresh assessment sessions before the initial checkpoint is written.
  - Added authenticated PostgreSQL profile-age updates for missing-age answers and explicit age corrections, with safe rollback-to-previous-session-age behavior on persistence failure.
  - Added optional `question_metadata` to `ChatResponse` and structured asset metadata to resumed pending questions.
- `symptom_questionnaire.py`
  - Added a multi-branch queue for primary and secondary symptoms.
  - Replaced newly emitted compound prompts with independent one-field questions.
  - Added independent gas/bloating/constipation/diarrhea checks.
  - Uses the Bristol chart marker only for the stool-form question.
- `question_schema.py`
  - Added stable one-field question IDs and field ownership mappings.
  - Enforced valid whole-number age answers and age completion semantics.
- `intent_parser.py`
  - Prevents fractional ages from being truncated by the natural-language age extractor.
  - Added direct yes/no resolution and semantic completion for those IDs.
  - Retained all legacy composite IDs and component mappings for saved checkpoints.
- `guttify_agent.py`
  - Binds the first component for legacy composite questions on initial emission.
  - Added explicit clarification text for new one-field questions and Bristol chart retry.
  - Increased the bounded question ceiling to 40 for multi-symptom assessment completion.
  - Added the direct anal-discomfort question to unanswered-safety handling.
- `gutgpt-widget.js`
  - Uses the API-origin Bristol asset URL.
  - Uses backend question metadata and restored pending-question metadata.
  - Restores the chart on resume/clarification and prevents duplicate prompts.
  - Adds graceful image failure handling and retains chart selection buttons.
- `VERSION.txt`
  - Updated to `18.4.2-individual-question-age-bristol`.
- `QUESTIONNAIRE_LOOP_AUDIT.md`
  - Added the v18.4.2 dependency map, root-cause findings, and release caveats.
- `PATCH_NOTES_18.4.2.md` (new)
  - Documents the controlled revision and preserved architecture.
- `AUDIT_IMPLEMENTATION_REPORT.md` (new)
  - This implementation report.

### Tests added or updated (not executed)

- `tests/test_profile_age_reconciliation.py` (new in the preceding audit patch; extended for new-assessment initialization, authenticated PostgreSQL age-update behavior, and invalid/fractional age rejection)
- `tests/test_assessment_resume_contract.py` (new in the preceding audit patch; covers structured resume/pending-question metadata)
- `tests/test_individual_component_prompt_regressions.py` (new in the preceding audit patch)
- `tests/test_individual_symptom_questions_v184.py` (new)
- `tests/test_bristol_widget_rendering_contract.py` (new)
- `tests/test_all_symptom_questionnaire_completeness.py` (updated to answer new independent question IDs)
- `tests/test_complete_question_flow_audit_v18.py` (updated to include new question IDs)
- `tests/test_phase1_symptom_summary.py` (updated completed-session fixture)
- `tests/test_questionnaire_loop_simulation.py` (updated scripted conversation for independent questions)

## 4. Database impact and compatibility

- No database migration is required.
- No tables or columns were added or removed.
- No customer or assessment rows are deleted, recreated, or overwritten by this package.
- PostgreSQL remains the required persistence backend. JSON-file fallback remains disabled.
- Existing composite question IDs and legacy checkpoint mappings remain in the schema/resolver for backward compatibility.
- Existing age profile storage remains the single authoritative source for registered customers.

## 5. Clinical, safety, and recommendation integrity

The following source files were not modified:

- `clinical_rule_engine.py`
- `safety_checker.py`
- `recommendation_engine.py`
- `products.json`

No diagnosis criteria, severity thresholds, exclusions, red-flag rules, referral logic, or product eligibility mappings were intentionally changed. All 27 existing outcome patterns remain in the unchanged clinical rule engine. The existing diarrhea restrictions for Digest Boost and Guttify Poopie remain in the unchanged recommendation engine.

This is a source-level preservation statement, not a claim that the full 27-pattern regression suite has passed for this revision. That regression run is part of the next test phase.

## 6. Test and static verification status

**Initial release verification:** the test suite had not been run when this report was first prepared.

**Repository revalidation on 2026-11-12:** `python -m pytest tests -q --tb=no --basetemp=.pytest-tmp` completed with **688 passed, 8 skipped, and 28 subtests passed**. The skipped tests require `GROQ_TEST_DATABASE_URL` to point to a disposable PostgreSQL database.

**Prepared regression coverage:**

- Independent one-field question ownership and bare yes/no resolution.
- Primary plus secondary symptom branch sequencing.
- Gas/bloating independence.
- Age validation, restore precedence, and new-assessment profile propagation.
- Bristol question-ID trigger, API metadata, asset route, frontend rendering, duplicate prevention, and graceful fallback.
- Existing clinical, safety, recommendation, persistence, session lifecycle, and 27-pattern suites remain in the project and are not removed.

**Static checks completed:**

- Python AST parsing succeeded for all 14 changed Python implementation/test files.
- `node --check` succeeded for the modified Shopify widget JavaScript.
- All 41 question IDs emitted by `symptom_questionnaire.py` have a matching `QuestionSpec` owner.
- Every question ID emitted by the revised questionnaire has a scripted answer entry in the updated conversation-completeness fixture.
- The Bristol PNG route and widget asset reference point to the shipped asset name.

**Still requires an external staging environment:**

- Live PostgreSQL restore/new-assessment behavior.
- Actual Shopify browser rendering, image HTTP status, and the production HTTPS asset path.
- Shopify `img-src` Content Security Policy acceptance for the GutGPT API origin.
- Production Nginx routing of `/assets/bristol-stool-chart.png`.

## 7. Deployment preparation (not performed)

No deployment was performed. No production files or database were accessed.

### Back up application and PostgreSQL first

Run on the DigitalOcean server only after the staging checks below pass. Replace the application path if the server uses a different one:

```bash
cd /opt/gutgpt
sudo tar -czf "/root/gutgpt-pre-v18.4.2-$(date +%Y%m%d-%H%M%S).tar.gz" \
  --exclude='venv' --exclude='.venv' --exclude='__pycache__' .
```

Use the same `DATABASE_URL` configured for the GutGPT systemd service to create a PostgreSQL custom-format backup. Do not put the URL or password in shell history:

```bash
sudo -i
set -a
. /opt/gutgpt/.env
set +a
pg_dump "$DATABASE_URL" -Fc -f "/root/gutgpt-db-pre-v18.4.2-$(date +%Y%m%d-%H%M%S).dump"
exit
```

If the server's `.env` is not shell-compatible, load the same secret from the service's existing protected environment source instead. Do not print it.

### Deploy after review

Upload and extract the approved ZIP into a staging copy first. Do not overwrite production directly. After staging validation, back up the current directory and copy the approved source files into `/opt/gutgpt` while preserving `.env`, the virtual environment, and service configuration. No database migration command is required.

Then, in the server's actual project virtual environment:

```bash
cd /opt/gutgpt
source venv/bin/activate
python -m pip install --upgrade pip==26.2
python -m pip install -r requirements.lock.txt
sudo systemctl restart gutgpt
sudo systemctl status gutgpt --no-pager
```

### Verify after deployment

```bash
curl -fsS https://gutgpt.guttify.co.in/api/health
curl -sSI https://gutgpt.guttify.co.in/gutgpt-widget.js
curl -sSI https://gutgpt.guttify.co.in/assets/bristol-stool-chart.png
sudo journalctl -u gutgpt -n 150 --no-pager
```

The Bristol asset request should return HTTP 200 and `Content-Type: image/png`. Then verify the embedded widget on both `gutgpt.guttify.co.in` and `guttify.co.in` in a real browser.

### Roll back application files

Restore the exact application backup created before deployment, preserving `.env` and service configuration, then restart:

```bash
sudo systemctl stop gutgpt
sudo tar -xzf /root/gutgpt-pre-v18.4.2-<timestamp>.tar.gz -C /opt/gutgpt
sudo systemctl start gutgpt
sudo systemctl status gutgpt --no-pager
```

No database rollback is expected because this revision has no schema migration. Keep the database backup until the release is accepted.

## 8. Release decision and remaining risks

**Automated tests pass; production deployment has not been performed.** The full suite and 27-pattern regression are included in the passing test run. Actual PostgreSQL integration, Shopify browser behavior, Nginx asset routing, and Shopify CSP still require staging verification. No production database or storefront was accessed during this revalidation.
